"""Iter 82 — Backend tests for Iter 77v bug fix.

Bug: Public self-registration endpoint `POST /api/auth/company-register`
was rejecting mobile numbers whose linked user was orphaned (company_id
points to a force-deleted firm). Fix (server.py near L5216): if the
existing user's company_id no longer resolves to a live firm AND the
user's role is company_admin / sub_admin / employee, delete the stale
user + user_sessions and proceed. Live firms and super_admins still
block with 409.

Also verifies Iter 77r admin-side auto-heal (POST /api/companies) still
works — regression from iteration_80.json.

Temp firms/users use prefixes `Iter82-` / `TEST_Iter82_` so they get
picked up by `python3 /app/scripts/cleanup_test_data.py --apply`.
"""

from __future__ import annotations

import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PHONE = "+919680273960"  # seeded super_admin phone (must-not-auto-heal)

# Mongo direct for verifying orphan row + cleanup checks
try:
    from motor.motor_asyncio import AsyncIOMotorClient  # noqa: F401
except Exception:
    pass
import pymongo
MONGO = pymongo.MongoClient(
    os.environ.get("MONGO_URL", "mongodb://localhost:27017")
)
DB = MONGO[os.environ.get("DB_NAME", "test_database")]


# ------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def super_token(http):
    r = http.post(
        f"{API}/auth/otp/request",
        json={"identifier": SUPER_EMAIL, "channel": "email"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    code = r.json().get("dev_code")
    assert code, r.json()
    r2 = http.post(
        f"{API}/auth/otp/verify",
        json={"identifier": SUPER_EMAIL, "channel": "email", "code": code},
        timeout=15,
    )
    assert r2.status_code == 200, r2.text
    tok = r2.json().get("session_token") or r2.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def auth_hdr(super_token):
    return {"Authorization": f"Bearer {super_token}"}


# ------------------------------------------------------------------ helpers
def _uniq_phone() -> str:
    return f"+9198{uuid.uuid4().int % 100_000_000:08d}"


def _uniq_email() -> str:
    return f"iter82.{uuid.uuid4().hex[:8]}@test.local"


def _make_selfreg_payload(phone: str, company_prefix: str = "Iter82-CSR"):
    unique = uuid.uuid4().hex[:6]
    return {
        "company_name": f"{company_prefix}-{unique}",
        "address": "123 Test Lane",
        "city": "Delhi",
        "state": "DL",
        "contact_name": "TEST_Iter82_Owner",
        "contact_mobile": phone,
        "contact_email": _uniq_email(),
        "nature_of_business": "Textile manufacturing",
        "business_category": "industry",
        "business_subcategory": "Textile",
        "pin": "482715",
        "office_lat": 28.6139,
        "office_lng": 77.2090,
        "geofence_radius_m": 200,
        "employee_count": 25,
        "notes": None,
    }


def _create_admin_firm(http, auth_hdr, *, prefix: str, admin_phone: str,
                        admin_email: str):
    """POST /api/companies (super-admin invitation path)."""
    unique = uuid.uuid4().hex[:6]
    payload = {
        "name": f"{prefix}-{unique}",
        "code": f"IT82{unique[:4].upper()}",
        "business_category": "industry",
        "business_subcategory": "Textile",
        "policy_variant": "policy_2",
        "office_lat": 28.6139,
        "office_lng": 77.2090,
        "admin_phone": admin_phone,
        "admin_email": admin_email,
        "admin_name": f"TEST_Iter82_admin_{unique}",
    }
    r = http.post(f"{API}/companies", json=payload, headers=auth_hdr, timeout=20)
    assert r.status_code in (200, 201), r.text
    body = r.json()
    cid = body.get("company_id") or (body.get("company") or {}).get("company_id")
    assert cid
    return cid, body


# ==================================================================
# Part 1 — Bug fix (Iter 77v): self-register auto-heals orphan admin phone
# ==================================================================
class TestSelfRegisterOrphanAutoHeal:
    def test_orphan_admin_phone_auto_heals_on_self_register(
        self, http, auth_hdr,
    ):
        phone = _uniq_phone()
        email = _uniq_email()

        # Step 1: super-admin creates firm A with this admin phone/email
        cid_a, body_a = _create_admin_firm(
            http, auth_hdr, prefix="Iter82-CSR-A",
            admin_phone=phone, admin_email=email,
        )
        admin = body_a.get("admin") or {}
        assert admin.get("phone") == phone, admin
        admin_user_id = admin.get("user_id") or admin.get("id")

        # Verify user + company are live in DB
        u_before = DB.users.find_one({"phone": phone}, {"_id": 0})
        assert u_before is not None, "admin user should exist after firm create"
        assert u_before.get("company_id") == cid_a, u_before
        assert u_before.get("role") in (
            "company_admin", "sub_admin", "employee",
        ), u_before

        # Step 2: delete ONLY the companies row (simulate the orphan
        # scenario the fix targets — an admin user whose company_id
        # points to a firm that no longer exists). We deliberately do
        # NOT use the /companies DELETE endpoint here because it
        # cascade-wipes users when force=true, which would leave no
        # orphan to auto-heal. Real-world orphans arise from historic
        # deletes / bugs / partial cascades. Reproducing via pymongo is
        # the most reliable way to seed the bug's exact precondition.
        DB.companies.delete_one({"company_id": cid_a})
        firm_gone = DB.companies.find_one({"company_id": cid_a})
        assert firm_gone is None, "firm should be deleted"

        # Step 3: confirm orphan user row still exists (company_id points
        # to now-deleted firm) and role is company_admin/sub_admin/employee
        u_orphan = DB.users.find_one({"phone": phone}, {"_id": 0})
        assert u_orphan is not None, "orphan user row should remain"
        assert u_orphan.get("company_id") == cid_a, u_orphan
        assert u_orphan.get("role") in (
            "company_admin", "sub_admin", "employee",
        ), u_orphan

        # Step 4: hit self-registration with the SAME phone → 200
        payload = _make_selfreg_payload(phone)
        r = http.post(f"{API}/auth/company-register", json=payload, timeout=20)
        assert r.status_code == 200, (
            f"Self-register auto-heal FAILED: {r.status_code} {r.text}"
        )
        body = r.json()
        assert body.get("ok") is True, body
        req_id = body.get("request_id")
        assert req_id and req_id.startswith("req_"), body

        # Step 5: verify company_request row exists AND orphan user is gone
        req_row = DB.company_requests.find_one(
            {"request_id": req_id}, {"_id": 0},
        )
        assert req_row is not None, "company_request should be persisted"
        assert req_row.get("contact_mobile") == phone, req_row
        assert req_row.get("company_name") == payload["company_name"], req_row
        assert req_row.get("status") == "pending", req_row

        u_after = DB.users.find_one({"phone": phone}, {"_id": 0})
        assert u_after is None, (
            f"orphan user should be auto-healed (deleted), still found: {u_after}"
        )
        # Sessions for the orphan user should also be gone
        if admin_user_id:
            sess = list(DB.user_sessions.find(
                {"user_id": admin_user_id}, {"_id": 0},
            ))
            assert sess == [], f"orphan sessions should be cleared: {sess}"


# ==================================================================
# Part 2 — Regression: super_admin phone must still block (409)
# ==================================================================
class TestSelfRegisterSuperAdminBlocked:
    def test_super_admin_phone_reuse_blocks_with_409(self, http):
        # The seeded super_admin phone (+919680273960) MUST NOT be
        # auto-healed even if company_id is None (i.e. no live firm).
        u = DB.users.find_one({"phone": SUPER_PHONE}, {"_id": 0, "role": 1})
        assert u and u.get("role") == "super_admin", (
            f"pre-condition: expected super_admin at phone {SUPER_PHONE}, got {u}"
        )
        payload = _make_selfreg_payload(SUPER_PHONE,
                                        company_prefix="Iter82-CSR-SA")
        r = http.post(f"{API}/auth/company-register", json=payload, timeout=20)
        assert r.status_code == 409, (
            f"Expected 409 for super_admin phone reuse; got "
            f"{r.status_code} {r.text}"
        )
        assert "already exists" in r.text.lower(), r.text


# ==================================================================
# Part 3 — Regression: user linked to a LIVE firm must block (409)
# ==================================================================
class TestSelfRegisterLiveFirmBlocked:
    def test_live_firm_admin_phone_blocks_with_409(self, http, auth_hdr):
        phone = _uniq_phone()
        email = _uniq_email()
        cid_live, _ = _create_admin_firm(
            http, auth_hdr, prefix="Iter82-CSR-Live",
            admin_phone=phone, admin_email=email,
        )
        # Sanity — firm is live
        assert DB.companies.find_one({"company_id": cid_live}) is not None

        payload = _make_selfreg_payload(phone,
                                        company_prefix="Iter82-CSR-LiveDup")
        r = http.post(f"{API}/auth/company-register", json=payload, timeout=20)
        assert r.status_code == 409, (
            f"Expected 409 for live-firm phone reuse; got "
            f"{r.status_code} {r.text}"
        )
        assert "already exists" in r.text.lower(), r.text

        # Live user should still be present, untouched
        u_still = DB.users.find_one({"phone": phone}, {"_id": 0})
        assert u_still is not None and u_still.get("company_id") == cid_live, (
            f"Live admin should be untouched: {u_still}"
        )


# ==================================================================
# Part 4 — Regression: /admin/companies (create-firm) auto-heal still works
# (from Iter 77r, iteration_80.json)
# ==================================================================
class TestCreateCompanyOrphanAutoHealStillWorks:
    def test_orphan_reuse_via_create_company_endpoint(self, http, auth_hdr):
        phone = _uniq_phone()
        email = _uniq_email()

        # Firm 1 with phone+email
        cid_1, _ = _create_admin_firm(
            http, auth_hdr, prefix="Iter82-CSR-Reg1",
            admin_phone=phone, admin_email=email,
        )
        # Delete only the companies row so we retain an orphan users row
        # (real-world orphan precondition — force=true would cascade-wipe
        # the users, defeating the auto-heal test).
        DB.companies.delete_one({"company_id": cid_1})
        assert DB.companies.find_one({"company_id": cid_1}) is None
        u_orphan = DB.users.find_one({"phone": phone}, {"_id": 0})
        assert u_orphan is not None and u_orphan.get("company_id") == cid_1

        # Firm 2 with SAME phone+email — expect success (auto-heal)
        cid_2, body_2 = _create_admin_firm(
            http, auth_hdr, prefix="Iter82-CSR-Reg2",
            admin_phone=phone, admin_email=email,
        )
        assert cid_2 != cid_1
        admin_2 = body_2.get("admin") or {}
        assert admin_2.get("phone") == phone, admin_2

        # New admin user now points at firm 2
        u = DB.users.find_one({"phone": phone}, {"_id": 0})
        assert u is not None and u.get("company_id") == cid_2, u


# ==================================================================
# Part 5 — Regression: pending duplicate self-register still blocked (409)
# ==================================================================
class TestSelfRegisterPendingDuplicate:
    def test_pending_duplicate_blocks_with_409(self, http):
        phone = _uniq_phone()
        payload = _make_selfreg_payload(phone, company_prefix="Iter82-CSR-Pend")
        r1 = http.post(f"{API}/auth/company-register", json=payload, timeout=20)
        assert r1.status_code == 200, r1.text

        # Second submission with same phone → pending block
        payload2 = _make_selfreg_payload(phone, company_prefix="Iter82-CSR-Pend2")
        r2 = http.post(f"{API}/auth/company-register", json=payload2, timeout=20)
        assert r2.status_code == 409, (
            f"Expected 409 for pending duplicate; got {r2.status_code} {r2.text}"
        )
        assert "pending" in r2.text.lower(), r2.text
