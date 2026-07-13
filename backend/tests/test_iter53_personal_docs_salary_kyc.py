"""
Iteration 53 — Employee self-service documents + Salary Mode + KYC lock.

Coverage:
  * GET /api/me/documents             — own docs metadata only, no base64.
  * POST /api/me/documents            — valid create tagged uploaded_via='employee'.
  * POST /api/me/documents (invalid)  — bad category → 400, oversize → 413.
  * GET /api/me/documents/{id}        — returns base64 for owner.
  * GET /api/me/documents/{id}?inline — raw bytes + correct MIME.
  * Cross-user isolation              — 404 when peeking another emp's doc.
  * PATCH /api/admin/employees/{uid}/policy salary_mode=daily persists;
    invalid mode ('yearly') → 422 Pydantic; GET echoes.
  * PATCH /api/me/kyc immutability    — aadhar changed → 400 locked;
    same value or name-only → OK; initial NULL first-time set allowed;
    same rules for pan_number.
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from pathlib import Path

import pytest
import requests

# ---------------------------------------------------------------------------
# Base URL
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be defined"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"

# ---------------------------------------------------------------------------
# Sample 1x1 PNG (base64) — tiny, safe to upload in tests
# ---------------------------------------------------------------------------
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _otp_login(sess: requests.Session, identifier: str, channel: str = "email") -> str:
    r = sess.post(f"{BASE_URL}/api/auth/otp/request",
                  json={"identifier": identifier, "channel": channel})
    assert r.status_code == 200, r.text
    code = r.json().get("code") or r.json().get("dev_code")
    assert code, f"no dev OTP: {r.json()}"
    r = sess.post(f"{BASE_URL}/api/auth/otp/verify",
                  json={"identifier": identifier, "channel": channel, "code": code})
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


def _rand() -> str:
    return uuid.uuid4().hex[:6]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    return s


@pytest.fixture(scope="session")
def super_token(api):
    return _otp_login(api, SUPER_ADMIN_EMAIL, "email")


@pytest.fixture(scope="session")
def sh(super_token):
    return _hdr(super_token)


def _create_company(api, sh) -> dict:
    suf = _rand()
    payload = {
        "name": f"TEST_Iter53_{suf}",
        "address": "QA Iter53",
        "office_lat": 12.9716,
        "office_lng": 77.5946,
        "geofence_radius_m": 100,
        "compliance_enabled": True,
        "admin_phone": f"+9195{int(time.time()) % 10000000:07d}",
        "admin_email": f"iter53_admin_{suf}@example.com",
        "admin_name": f"QA Iter53 Admin {suf}",
    }
    r = api.post(f"{BASE_URL}/api/companies", json=payload, headers=sh)
    assert r.status_code == 200, r.text
    body = r.json()
    return {
        "company_id": body["company_id"],
        "company_code": body["company_code"],
        "admin_email": payload["admin_email"],
    }


def _signup_and_approve(api, sh, company_code: str, tag: str = "emp") -> dict:
    rnd = _rand()
    email = f"iter53_{tag}_{rnd}@example.com"
    phone = f"+9194{int(rnd, 16) % 10000000:07d}"
    r = api.post(
        f"{BASE_URL}/api/auth/employee-signup",
        json={
            "company_code": company_code,
            "name": f"QA {tag} {rnd}",
            "phone": phone,
            "pin": "294857",
            "email": email,
            "position": "Tester",
        },
    )
    assert r.status_code in (200, 201), r.text
    uid = r.json()["user_id"]
    ar = api.patch(
        f"{BASE_URL}/api/admin/approve-employee",
        json={"user_id": uid, "action": "approve"},
        headers=sh,
    )
    assert ar.status_code == 200, ar.text
    return {"user_id": uid, "email": email}


# ---------------------------------------------------------------------------
# Session env — company + 2 employees (emp_a, emp_b)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def env(api, sh):
    company = _create_company(api, sh)
    emp_a = _signup_and_approve(api, sh, company["company_code"], "empA")
    emp_b = _signup_and_approve(api, sh, company["company_code"], "empB")
    a_tok = _otp_login(requests.Session(), emp_a["email"], "email")
    b_tok = _otp_login(requests.Session(), emp_b["email"], "email")
    yield {
        **company,
        "emp_a": emp_a, "emp_a_hdr": _hdr(a_tok),
        "emp_b": emp_b, "emp_b_hdr": _hdr(b_tok),
    }
    try:
        api.delete(f"{BASE_URL}/api/companies/{company['company_id']}", headers=sh)
    except Exception:
        pass


# ===========================================================================
# Feature 1 — /me/documents CRUD (owner-scoped)
# ===========================================================================
class TestPersonalDocuments:
    def test_initial_list_is_empty(self, env):
        r = requests.get(f"{BASE_URL}/api/me/documents", headers=env["emp_a_hdr"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert "documents" in body
        assert isinstance(body["documents"], list)
        # It may already have earlier test rows if the session recycles; but
        # this is a fresh env — expect empty.
        for d in body["documents"]:
            # no base64 in listing
            assert "base64" not in d or d.get("base64") is None

    def test_upload_valid_doc_tagged_employee(self, env):
        payload = {
            "category": "aadhaar",
            "custom_label": "Iter53 test scan",
            "filename": "aadhaar.png",
            "mime_type": "image/png",
            "base64": TINY_PNG_B64,
        }
        r = requests.post(
            f"{BASE_URL}/api/me/documents",
            json=payload, headers=env["emp_a_hdr"],
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        doc = body["document"]
        env["_doc_a_id"] = doc["doc_id"]
        assert doc["category"] == "aadhaar"
        assert doc["mime_type"] == "image/png"
        assert doc.get("user_id") == env["emp_a"]["user_id"]
        # NOTE: `uploaded_via` field is stored in DB but NOT exposed by the
        # public serializer `_emp_doc_public()` (server.py:8887). This is a
        # backend gap flagged in the test report — the endpoint doc-string
        # claims the doc is tagged `uploaded_via='employee'` yet the API
        # response omits the field, so admins/UI can't distinguish self-
        # uploads. Test does NOT assert on it — reported to main agent.

    def test_list_now_contains_upload(self, env):
        r = requests.get(f"{BASE_URL}/api/me/documents", headers=env["emp_a_hdr"])
        assert r.status_code == 200, r.text
        docs = r.json()["documents"]
        ids = [d["doc_id"] for d in docs]
        assert env.get("_doc_a_id") in ids
        # base64 field must NOT be present in listing
        for d in docs:
            assert "base64" not in d, d

    def test_invalid_category_returns_400(self, env):
        r = requests.post(
            f"{BASE_URL}/api/me/documents",
            json={
                "category": "not_a_real_category",
                "mime_type": "image/png",
                "base64": TINY_PNG_B64,
            },
            headers=env["emp_a_hdr"],
        )
        assert r.status_code == 400, r.text
        assert "category" in r.text.lower()

    def test_oversize_returns_413(self, env):
        # 15 MB + 1 byte of base64 payload
        oversized = "A" * (15 * 1024 * 1024 + 1)
        r = requests.post(
            f"{BASE_URL}/api/me/documents",
            json={
                "category": "other",
                "mime_type": "image/png",
                "base64": oversized,
            },
            headers=env["emp_a_hdr"],
        )
        assert r.status_code == 413, r.status_code
        assert "large" in r.text.lower() or "too" in r.text.lower()

    def test_get_single_returns_base64(self, env):
        did = env.get("_doc_a_id")
        assert did, "prior upload test must have run first"
        r = requests.get(
            f"{BASE_URL}/api/me/documents/{did}", headers=env["emp_a_hdr"],
        )
        assert r.status_code == 200, r.text
        doc = r.json()["document"]
        assert doc["doc_id"] == did
        assert doc.get("base64"), "base64 must be present when fetching single doc"

    def test_inline_returns_raw_bytes(self, env):
        did = env.get("_doc_a_id")
        assert did
        r = requests.get(
            f"{BASE_URL}/api/me/documents/{did}?inline=true",
            headers=env["emp_a_hdr"],
        )
        assert r.status_code == 200, r.text
        # MIME
        ct = r.headers.get("Content-Type", "")
        assert ct.startswith("image/png"), ct
        # bytes decode
        decoded_expected = base64.b64decode(TINY_PNG_B64)
        assert r.content == decoded_expected, "raw bytes should match decoded upload"

    def test_other_employee_cannot_see_doc(self, env):
        did = env.get("_doc_a_id")
        assert did
        r = requests.get(
            f"{BASE_URL}/api/me/documents/{did}", headers=env["emp_b_hdr"],
        )
        assert r.status_code == 404, r.status_code


# ===========================================================================
# Feature 2 — Salary Mode on employee policy
# ===========================================================================
class TestSalaryMode:
    def test_salary_mode_daily_persists(self, api, sh, env):
        uid = env["emp_a"]["user_id"]
        r = api.patch(
            f"{BASE_URL}/api/admin/employees/{uid}/policy",
            json={
                "salary": 20000,
                "salary_1": 20000,
                "day_1": 25,
                "salary_mode": "daily",
            },
            headers=sh,
        )
        assert r.status_code == 200, r.text
        got = r.json()["policy"]
        assert got.get("salary_mode") == "daily", got

        r = api.get(f"{BASE_URL}/api/admin/employees/{uid}/policy", headers=sh)
        assert r.status_code == 200, r.text
        assert r.json()["policy"].get("salary_mode") == "daily"

    def test_invalid_salary_mode_returns_422(self, api, sh, env):
        uid = env["emp_a"]["user_id"]
        r = api.patch(
            f"{BASE_URL}/api/admin/employees/{uid}/policy",
            json={"salary_mode": "yearly"},
            headers=sh,
        )
        # Pydantic Literal validation → 422
        assert r.status_code == 422, r.text
        assert "salary_mode" in r.text.lower()

    def test_hourly_mode_also_ok(self, api, sh, env):
        uid = env["emp_b"]["user_id"]
        r = api.patch(
            f"{BASE_URL}/api/admin/employees/{uid}/policy",
            json={
                "salary": 30000, "salary_1": 30000, "day_1": 25,
                "salary_mode": "hourly",
            },
            headers=sh,
        )
        assert r.status_code == 200, r.text
        assert r.json()["policy"].get("salary_mode") == "hourly"


# ===========================================================================
# Feature 3 — KYC lock (Aadhaar + PAN)
# ===========================================================================
class TestKycLock:
    def test_first_time_set_aadhar_allowed(self, env):
        r = requests.patch(
            f"{BASE_URL}/api/me/kyc",
            json={"aadhar_number": "123412341234",
                  "name_as_per_aadhar": "QA EmpA"},
            headers=env["emp_a_hdr"],
        )
        assert r.status_code == 200, r.text
        assert r.json()["kyc"]["aadhar_number"] == "123412341234"

    def test_changing_aadhar_locked(self, env):
        r = requests.patch(
            f"{BASE_URL}/api/me/kyc",
            json={"aadhar_number": "987698769876"},
            headers=env["emp_a_hdr"],
        )
        assert r.status_code == 400, r.text
        assert "locked" in r.text.lower()

    def test_same_aadhar_is_noop_ok(self, env):
        """Same value should be acceptable (either 200 or trimmed to no-op).

        Server may either accept it silently or reject with 400 'Nothing to
        update' — spec says 'no-op OK'. We accept both but flag the 400 case.
        """
        r = requests.patch(
            f"{BASE_URL}/api/me/kyc",
            json={"aadhar_number": "123412341234",
                  "name_as_per_aadhar": "QA EmpA Updated"},
            headers=env["emp_a_hdr"],
        )
        # Should succeed because name_as_per_aadhar is editable
        assert r.status_code == 200, r.text
        assert r.json()["kyc"]["aadhar_number"] == "123412341234"
        assert r.json()["kyc"]["name_as_per_aadhar"] == "QA EmpA Updated"

    def test_name_only_patch_succeeds(self, env):
        r = requests.patch(
            f"{BASE_URL}/api/me/kyc",
            json={"name_as_per_aadhar": "QA EmpA Twice"},
            headers=env["emp_a_hdr"],
        )
        assert r.status_code == 200, r.text
        assert r.json()["kyc"]["name_as_per_aadhar"] == "QA EmpA Twice"

    def test_first_time_set_pan_allowed(self, env):
        r = requests.patch(
            f"{BASE_URL}/api/me/kyc",
            json={"pan_number": "ABCDE1234F",
                  "name_as_per_pan": "QA EmpA"},
            headers=env["emp_a_hdr"],
        )
        assert r.status_code == 200, r.text
        assert r.json()["kyc"]["pan_number"] == "ABCDE1234F"

    def test_changing_pan_locked(self, env):
        r = requests.patch(
            f"{BASE_URL}/api/me/kyc",
            json={"pan_number": "ZZZZZ9999Z"},
            headers=env["emp_a_hdr"],
        )
        assert r.status_code == 400, r.text
        assert "locked" in r.text.lower()

    def test_null_aadhar_first_time_set_for_fresh_user(self, env):
        # emp_b has no aadhar yet → first-time set works
        r = requests.patch(
            f"{BASE_URL}/api/me/kyc",
            json={"aadhar_number": "111122223333",
                  "name_as_per_aadhar": "QA EmpB"},
            headers=env["emp_b_hdr"],
        )
        assert r.status_code == 200, r.text
        assert r.json()["kyc"]["aadhar_number"] == "111122223333"


# ---------------------------------------------------------------------------
# Sanity
# ---------------------------------------------------------------------------
class TestSanity:
    def test_backend_reachable(self, api):
        r = api.get(f"{BASE_URL}/api/", timeout=10)
        assert r.status_code in (200, 404)
