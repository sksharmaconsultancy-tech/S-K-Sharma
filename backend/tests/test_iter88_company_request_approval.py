"""Iter 88 — Reproduce HTTP 500 on PATCH /api/company-requests/{id} (super_admin Approve).

Covers the 7 edge-case scenarios from the review request PLUS the happy path
and mobile-vs-curl parity check.  Runs against localhost:8001 (backend
supervisor process) and captures the exact traceback if any 500 slips through.
"""
import os
import uuid
import time
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

BASE = os.environ.get("BASE_URL", "http://localhost:8001")
API = f"{BASE}/api"
SUPER_EMAIL = "sksharmaconsultancy@gmail.com"

# ── Mongo direct handle (for seeding pathological docs) ──────────────
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _mongo():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ── Fixtures ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{API}/auth/otp/request",
                      json={"identifier": SUPER_EMAIL, "channel": "email"}, timeout=15)
    assert r.status_code == 200, r.text
    code = r.json()["dev_code"]
    r2 = requests.post(f"{API}/auth/otp/verify",
                       json={"identifier": SUPER_EMAIL, "channel": "email", "code": code}, timeout=15)
    assert r2.status_code == 200, r2.text
    return r2.json()["session_token"]


@pytest.fixture(scope="module")
def hdr(super_token):
    return {"Authorization": f"Bearer {super_token}", "Content-Type": "application/json"}


def _uniq_phone():
    # 10-digit random suffix, prefixed +91
    return "+9198" + str(uuid.uuid4().int)[:8]


def _submit_self_register(company_name=None, phone=None, extra=None):
    payload = {
        "company_name": company_name or f"TEST_Firm_{uuid.uuid4().hex[:6]}",
        "address": "1 Test Street",
        "city": "Mumbai",
        "state": "MH",
        "contact_name": "Test Owner",
        "contact_mobile": phone or _uniq_phone(),
        "contact_email": f"owner_{uuid.uuid4().hex[:6]}@test.local",
        "nature_of_business": "Textile",
        "business_category": "industry",
        "business_subcategory": "textile",
        "office_lat": 19.07,
        "office_lng": 72.87,
        "geofence_radius_m": 200,
        "employee_count": 10,
        "pin": "294817",
    }
    if extra:
        payload.update(extra)
    r = requests.post(f"{API}/auth/company-register", json=payload, timeout=15)
    return r, payload


# ── HAPPY PATH ───────────────────────────────────────────────────────
class TestHappyPath:
    def test_submit_and_approve(self, hdr):
        r, payload = _submit_self_register()
        assert r.status_code == 200, r.text
        req_id = r.json()["request_id"]

        r2 = requests.patch(f"{API}/company-requests/{req_id}",
                            headers=hdr, json={"status": "approved"}, timeout=20)
        assert r2.status_code == 200, f"HTTP {r2.status_code}: {r2.text}"
        body = r2.json()
        assert body.get("company_id"), body
        assert body.get("company_code"), body
        assert body.get("admin_user_id"), body

        # Verify persistence
        company_id = body["company_id"]
        # Cleanup
        async def _clean():
            db = _mongo()
            await db.companies.delete_one({"company_id": company_id})
            await db.users.delete_one({"user_id": body["admin_user_id"]})
            await db.company_requests.delete_one({"request_id": req_id})
        _run(_clean())


# ── EDGE CASE 3: Idempotent double-approve ───────────────────────────
class TestIdempotentReapprove:
    def test_reapprove_returns_already_decided(self, hdr):
        r, _ = _submit_self_register()
        assert r.status_code == 200, r.text
        req_id = r.json()["request_id"]

        # 1st approve
        r1 = requests.patch(f"{API}/company-requests/{req_id}",
                            headers=hdr, json={"status": "approved"}, timeout=20)
        assert r1.status_code == 200, r1.text
        company_id = r1.json()["company_id"]

        # 2nd approve (idempotent)
        r2 = requests.patch(f"{API}/company-requests/{req_id}",
                            headers=hdr, json={"status": "approved"}, timeout=20)
        assert r2.status_code == 200, f"REAPPROVE HTTP {r2.status_code}: {r2.text}"
        body = r2.json()
        assert body.get("already_decided") is True, body
        assert body.get("company_id") == company_id

        # Cleanup
        async def _clean():
            db = _mongo()
            await db.companies.delete_one({"company_id": company_id})
            await db.users.delete_one({"user_id": r1.json()["admin_user_id"]})
            await db.company_requests.delete_one({"request_id": req_id})
        _run(_clean())


# ── EDGE CASE 1: Phone linked to live company_admin of another firm ─
class TestPhoneCollisionLiveAdmin:
    def test_approve_returns_409_not_500(self, hdr):
        # First submit & approve to create a live firm+admin
        phone = _uniq_phone()
        r, _ = _submit_self_register(phone=phone)
        assert r.status_code == 200, r.text
        first_req = r.json()["request_id"]

        r_app = requests.patch(f"{API}/company-requests/{first_req}",
                               headers=hdr, json={"status": "approved"}, timeout=20)
        assert r_app.status_code == 200, r_app.text
        first_company = r_app.json()["company_id"]
        first_admin = r_app.json()["admin_user_id"]

        # Directly seed a *new* pending request that uses the SAME phone —
        # bypassing the /auth/company-register guard which would reject
        # it up front — to isolate the approval-time behaviour.
        req_id = f"req_{uuid.uuid4().hex[:12]}"
        async def _seed():
            db = _mongo()
            await db.company_requests.insert_one({
                "request_id": req_id,
                "kind": "self_register",
                "contact_name": "Second Owner",
                "contact_mobile": phone,
                "contact_email": "second@test.local",
                "company_name": f"TEST_Second_{uuid.uuid4().hex[:6]}",
                "address": "2 Test",
                "city": "Delhi",
                "state": "DL",
                "nature_of_business": "Textile",
                "business_category": "industry",
                "business_subcategory": "textile",
                "office_lat": 19.07,
                "office_lng": 72.87,
                "geofence_radius_m": 200,
                "admin_pin_hash": "$2b$10$abcdefghijklmnopqrstuv",
                "status": "pending",
                "created_at": "2026-01-01T00:00:00Z",
            })
        _run(_seed())

        r2 = requests.patch(f"{API}/company-requests/{req_id}",
                            headers=hdr, json={"status": "approved"}, timeout=20)
        assert r2.status_code == 409, f"Expected 409, got HTTP {r2.status_code}: {r2.text}"
        assert "already registered" in r2.json().get("detail", "").lower() or \
               "company admin" in r2.json().get("detail", "").lower()

        # Cleanup
        async def _clean():
            db = _mongo()
            await db.companies.delete_one({"company_id": first_company})
            await db.users.delete_one({"user_id": first_admin})
            await db.company_requests.delete_many({"request_id": {"$in": [first_req, req_id]}})
        _run(_clean())


# ── EDGE CASE 2: Phone belongs to a super_admin ─────────────────────
class TestPhoneCollisionSuperAdmin:
    def test_approve_returns_409_not_500(self, hdr):
        # The known super_admin phone (do NOT modify PIN)
        super_phone = "+919680273960"

        req_id = f"req_{uuid.uuid4().hex[:12]}"
        async def _seed():
            db = _mongo()
            await db.company_requests.insert_one({
                "request_id": req_id,
                "kind": "self_register",
                "contact_name": "SA Impostor",
                "contact_mobile": super_phone,
                "contact_email": "impostor@test.local",
                "company_name": f"TEST_SA_{uuid.uuid4().hex[:6]}",
                "address": "3 Test",
                "city": "Delhi",
                "state": "DL",
                "nature_of_business": "Textile",
                "business_category": "industry",
                "business_subcategory": "textile",
                "office_lat": 19.07,
                "office_lng": 72.87,
                "geofence_radius_m": 200,
                "admin_pin_hash": "$2b$10$abcdefghijklmnopqrstuv",
                "status": "pending",
                "created_at": "2026-01-01T00:00:00Z",
            })
        _run(_seed())

        r = requests.patch(f"{API}/company-requests/{req_id}",
                           headers=hdr, json={"status": "approved"}, timeout=20)
        assert r.status_code == 409, f"Expected 409, got HTTP {r.status_code}: {r.text}"
        assert "super admin" in r.json().get("detail", "").lower()

        # Also verify super_admin user was NOT touched
        async def _verify():
            db = _mongo()
            u = await db.users.find_one({"phone": super_phone, "role": "super_admin"})
            assert u is not None, "super_admin user was deleted!"

            await db.company_requests.delete_one({"request_id": req_id})
        _run(_verify())


# ── EDGE CASE 4: Missing contact_mobile ─────────────────────────────
class TestMissingContactMobile:
    def test_approve_returns_400_not_500(self, hdr):
        req_id = f"req_{uuid.uuid4().hex[:12]}"
        async def _seed():
            db = _mongo()
            await db.company_requests.insert_one({
                "request_id": req_id,
                "kind": "self_register",
                "contact_name": "No Phone",
                # contact_mobile intentionally missing
                "contact_email": "nophone@test.local",
                "company_name": f"TEST_NoPhone_{uuid.uuid4().hex[:6]}",
                "address": "4 Test",
                "city": "Delhi",
                "state": "DL",
                "nature_of_business": "Textile",
                "business_category": "industry",
                "business_subcategory": "textile",
                "office_lat": 19.07,
                "office_lng": 72.87,
                "geofence_radius_m": 200,
                "admin_pin_hash": "$2b$10$abcdefghijklmnopqrstuv",
                "status": "pending",
                "created_at": "2026-01-01T00:00:00Z",
            })
        _run(_seed())

        r = requests.patch(f"{API}/company-requests/{req_id}",
                           headers=hdr, json={"status": "approved"}, timeout=20)
        assert r.status_code == 400, f"Expected 400, got HTTP {r.status_code}: {r.text}"

        async def _clean():
            await _mongo().company_requests.delete_one({"request_id": req_id})
        _run(_clean())


# ── EDGE CASE 5: Legacy request — no 'kind' + NULL business_category ─
class TestLegacyRequestNoKind:
    def test_approve_no_kind_field(self, hdr):
        """A request with no `kind` field is NOT self_register, so approval
        should just flip status to approved without provisioning a firm."""
        req_id = f"req_{uuid.uuid4().hex[:12]}"
        async def _seed():
            db = _mongo()
            await db.company_requests.insert_one({
                "request_id": req_id,
                # kind intentionally missing
                "contact_name": "Legacy Owner",
                "contact_mobile": _uniq_phone(),
                "contact_email": "legacy@test.local",
                "company_name": f"TEST_Legacy_{uuid.uuid4().hex[:6]}",
                "address": "5 Test",
                "city": "Delhi",
                "state": "DL",
                "nature_of_business": "Textile",
                "business_category": None,   # NULL
                "business_subcategory": None,
                "status": "pending",
                "created_at": "2026-01-01T00:00:00Z",
            })
        _run(_seed())

        r = requests.patch(f"{API}/company-requests/{req_id}",
                           headers=hdr, json={"status": "approved"}, timeout=20)
        assert r.status_code in (200, 400), f"Expected 200/400, got HTTP {r.status_code}: {r.text}"

        async def _clean():
            await _mongo().company_requests.delete_one({"request_id": req_id})
        _run(_clean())

    def test_approve_self_register_null_business_category(self, hdr):
        """kind=self_register but business_category=None — should not crash
        _policy_for_category."""
        req_id = f"req_{uuid.uuid4().hex[:12]}"
        phone = _uniq_phone()
        async def _seed():
            db = _mongo()
            await db.company_requests.insert_one({
                "request_id": req_id,
                "kind": "self_register",
                "contact_name": "NullCat Owner",
                "contact_mobile": phone,
                "contact_email": "nullcat@test.local",
                "company_name": f"TEST_NullCat_{uuid.uuid4().hex[:6]}",
                "address": "6 Test",
                "city": "Delhi",
                "state": "DL",
                "nature_of_business": "Textile",
                "business_category": None,   # NULL
                "business_subcategory": None,
                "office_lat": 19.07,
                "office_lng": 72.87,
                "geofence_radius_m": 200,
                "admin_pin_hash": "$2b$10$abcdefghijklmnopqrstuv",
                "status": "pending",
                "created_at": "2026-01-01T00:00:00Z",
            })
        _run(_seed())

        r = requests.patch(f"{API}/company-requests/{req_id}",
                           headers=hdr, json={"status": "approved"}, timeout=20)
        assert r.status_code == 200, f"Expected 200, got HTTP {r.status_code}: {r.text}"
        body = r.json()
        company_id = body.get("company_id")
        admin_user_id = body.get("admin_user_id")

        async def _clean():
            db = _mongo()
            if company_id:
                await db.companies.delete_one({"company_id": company_id})
            if admin_user_id:
                await db.users.delete_one({"user_id": admin_user_id})
            await db.company_requests.delete_one({"request_id": req_id})
        _run(_clean())


# ── EDGE CASE 6: Duplicate company_name in db.companies ─────────────
class TestDuplicateCompanyName:
    def test_approve_with_duplicate_name(self, hdr):
        name = f"TEST_DupName_{uuid.uuid4().hex[:6]}"
        existing_cid = f"co_{uuid.uuid4().hex[:10]}"
        existing_code = uuid.uuid4().hex[:6].upper()
        async def _seed_company():
            db = _mongo()
            await db.companies.insert_one({
                "company_id": existing_cid,
                "name": name,
                "company_code": existing_code,
                "created_at": "2026-01-01T00:00:00Z",
            })
        _run(_seed_company())

        # Now submit a fresh request with same company name
        r, _ = _submit_self_register(company_name=name)
        assert r.status_code == 200, r.text
        req_id = r.json()["request_id"]

        r2 = requests.patch(f"{API}/company-requests/{req_id}",
                            headers=hdr, json={"status": "approved"}, timeout=20)
        # Expected: 200 (duplicate name is currently ALLOWED — no unique index)
        # or 409 (if a uniqueness check was added). NOT 500.
        assert r2.status_code in (200, 409), f"Expected 200/409, got HTTP {r2.status_code}: {r2.text}"

        # Cleanup
        async def _clean():
            db = _mongo()
            await db.companies.delete_one({"company_id": existing_cid})
            if r2.status_code == 200:
                body = r2.json()
                if body.get("company_id"):
                    await db.companies.delete_one({"company_id": body["company_id"]})
                if body.get("admin_user_id"):
                    await db.users.delete_one({"user_id": body["admin_user_id"]})
            await db.company_requests.delete_one({"request_id": req_id})
        _run(_clean())


# ── EDGE CASE 7: office_lat / office_lng missing or None ────────────
class TestNoGeofence:
    def test_approve_missing_office_coords(self, hdr):
        req_id = f"req_{uuid.uuid4().hex[:12]}"
        phone = _uniq_phone()
        async def _seed():
            db = _mongo()
            await db.company_requests.insert_one({
                "request_id": req_id,
                "kind": "self_register",
                "contact_name": "NoGeo Owner",
                "contact_mobile": phone,
                "contact_email": "nogeo@test.local",
                "company_name": f"TEST_NoGeo_{uuid.uuid4().hex[:6]}",
                "address": "7 Test",
                "city": "Delhi",
                "state": "DL",
                "nature_of_business": "Textile",
                "business_category": "industry",
                "business_subcategory": "textile",
                # office_lat/lng completely missing
                "admin_pin_hash": "$2b$10$abcdefghijklmnopqrstuv",
                "status": "pending",
                "created_at": "2026-01-01T00:00:00Z",
            })
        _run(_seed())

        r = requests.patch(f"{API}/company-requests/{req_id}",
                           headers=hdr, json={"status": "approved"}, timeout=20)
        assert r.status_code == 200, f"Expected 200, got HTTP {r.status_code}: {r.text}"
        body = r.json()

        async def _clean():
            db = _mongo()
            if body.get("company_id"):
                await db.companies.delete_one({"company_id": body["company_id"]})
            if body.get("admin_user_id"):
                await db.users.delete_one({"user_id": body["admin_user_id"]})
            await db.company_requests.delete_one({"request_id": req_id})
        _run(_clean())


# ── MOBILE VS WEB PARITY: With x-forwarded-* headers ────────────────
class TestMobileHeaderParity:
    def test_approve_with_mobile_headers(self, hdr):
        r, _ = _submit_self_register()
        assert r.status_code == 200, r.text
        req_id = r.json()["request_id"]

        mobile_hdr = dict(hdr)
        mobile_hdr.update({
            "x-forwarded-for": "45.113.10.20",
            "x-forwarded-proto": "https",
            "x-forwarded-host": "emplo-connect-1.preview.emergentagent.com",
            "user-agent": "Expo/2.32.0 CFNetwork/1568.100.1 Darwin/24.0.0",
        })
        r2 = requests.patch(f"{API}/company-requests/{req_id}",
                            headers=mobile_hdr, json={"status": "approved"}, timeout=20)
        assert r2.status_code == 200, f"Mobile parity HTTP {r2.status_code}: {r2.text}"

        # Cleanup
        body = r2.json()
        async def _clean():
            db = _mongo()
            if body.get("company_id"):
                await db.companies.delete_one({"company_id": body["company_id"]})
            if body.get("admin_user_id"):
                await db.users.delete_one({"user_id": body["admin_user_id"]})
            await db.company_requests.delete_one({"request_id": req_id})
        _run(_clean())


# ── EDGE CASE via PUBLIC URL: same PATCH via preview URL (mobile app path) ─
class TestViaPreviewURL:
    def test_approve_via_preview_url(self, hdr):
        preview = "https://emplo-connect-1.preview.emergentagent.com/api"
        r, _ = _submit_self_register()
        assert r.status_code == 200, r.text
        req_id = r.json()["request_id"]

        r2 = requests.patch(f"{preview}/company-requests/{req_id}",
                            headers=hdr, json={"status": "approved"}, timeout=25)
        assert r2.status_code == 200, f"PREVIEW HTTP {r2.status_code}: {r2.text}"

        # Cleanup
        body = r2.json()
        async def _clean():
            db = _mongo()
            if body.get("company_id"):
                await db.companies.delete_one({"company_id": body["company_id"]})
            if body.get("admin_user_id"):
                await db.users.delete_one({"user_id": body["admin_user_id"]})
            await db.company_requests.delete_one({"request_id": req_id})
        _run(_clean())


# ── RACE CONDITION: two concurrent Approve taps → currently reproduces HTTP 500
# This is the confirmed root cause of the user's mobile app "HTTP 500" report.
# See report iteration_88.json for the DuplicateKeyError traceback at server.py:5726.
import concurrent.futures as _cf


class TestConcurrentApproveRace:
    def test_two_concurrent_approves_should_not_500(self, hdr):
        r, _ = _submit_self_register()
        assert r.status_code == 200, r.text
        req_id = r.json()["request_id"]

        def _approve():
            return requests.patch(
                f"{API}/company-requests/{req_id}",
                headers=hdr, json={"status": "approved"}, timeout=30,
            )

        with _cf.ThreadPoolExecutor(max_workers=3) as ex:
            results = list(ex.map(lambda _: _approve(), range(3)))

        codes = sorted(r.status_code for r in results)
        # Expected behaviour: exactly one 200 with company_id, the other 2
        # should also be 200 (idempotent — already_decided) OR 409, but
        # NEVER 500.  Today this ASSERT fails: we see [200, 500, 500].
        server_errors = [r for r in results if r.status_code >= 500]
        assert not server_errors, (
            f"RACE CONDITION HTTP 500 (RCA of user's bug). "
            f"Got status codes {codes}. "
            f"First 500 body: {server_errors[0].text[:400]}"
        )

        # Cleanup regardless
        async def _clean():
            db = _mongo()
            cids = set()
            uids = set()
            for r in results:
                if r.status_code == 200:
                    b = r.json()
                    if b.get("company_id"):
                        cids.add(b["company_id"])
                    if b.get("admin_user_id"):
                        uids.add(b["admin_user_id"])
            for c in cids:
                await db.companies.delete_one({"company_id": c})
            for u in uids:
                await db.users.delete_one({"user_id": u})
            await db.company_requests.delete_one({"request_id": req_id})
        _run(_clean())

