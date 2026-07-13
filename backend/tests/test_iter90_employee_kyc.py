"""Iter 90 backend tests — Admin-side Employee KYC / Demographic PATCH endpoint.

Endpoints under test:
  * PATCH /api/admin/employees/{user_id}/kyc
  * GET   /api/admin/employees/{user_id}/kyc

Access model:
  - super_admin / sub_admin → any employee
  - company_admin           → only own firm
  - other roles             → 403

Immutability: Aadhaar + PAN locked after first non-empty write.
Format checks: Aadhaar 12-digit, PAN AAAAA9999A, IFSC XXXX0XXXXXX.
Audit rows written to db.kyc_history on every successful update.
"""
from __future__ import annotations

import os
import uuid
import time
import asyncio
import pytest
import requests
from typing import Any, Dict, Optional, Tuple


BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
KANKANI_ADMIN_PHONE = "+919828100001"        # Prakash Kankani (company_admin)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _otp_login(identifier: str, channel: str = "email") -> str:
    """Perform OTP request/verify and return session token."""
    r = requests.post(
        f"{API}/auth/otp/request",
        json={"identifier": identifier, "channel": channel},
        timeout=30,
    )
    assert r.status_code == 200, f"OTP request failed: {r.status_code} {r.text}"
    dev_code = r.json().get("dev_code")
    assert dev_code, f"No dev_code in OTP response: {r.text}"
    r2 = requests.post(
        f"{API}/auth/otp/verify",
        json={"identifier": identifier, "channel": channel, "code": dev_code},
        timeout=30,
    )
    assert r2.status_code == 200, f"OTP verify failed: {r2.status_code} {r2.text}"
    tok = r2.json().get("session_token") or r2.json().get("token")
    assert tok, f"No session_token: {r2.text}"
    return tok


def _auth(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def super_token() -> str:
    return _otp_login(SUPER_ADMIN_EMAIL, "email")


@pytest.fixture(scope="module")
def kankani_admin_token() -> str:
    return _otp_login(KANKANI_ADMIN_PHONE, "sms")


@pytest.fixture(scope="module")
def kankani_employees(super_token: str):
    """List Kankani employees seen by super_admin. Returns list of user dicts."""
    # Find Kankani company_id via /admin/employees pagination
    r = requests.get(f"{API}/admin/employees?limit=200", headers=_auth(super_token), timeout=30)
    assert r.status_code == 200, f"list employees failed: {r.status_code} {r.text}"
    data = r.json()
    if isinstance(data, dict):
        items = data.get("employees") or data.get("items") or []
    else:
        items = data
    if not isinstance(items, list):
        items = []
    kankani = [u for u in items if u.get("company_id") == "cmp_527fecdd7c"]
    assert kankani, f"No Kankani employees returned to super_admin (got {len(items)} total)"
    return kankani


@pytest.fixture(scope="module")
def target_employee(kankani_employees):
    """Pick a Kankani employee that does NOT yet have aadhar_number set —
    we need a 'fresh' one for the immutability test.
    """
    # Return the whole list-ordered pick; caller can select by index.
    return kankani_employees


def _find_fresh_employee(token: str, employees) -> Optional[dict]:
    """Return the first employee with empty aadhar_number (fresh for lock test)."""
    for u in employees:
        r = requests.get(
            f"{API}/admin/employees/{u['user_id']}/kyc",
            headers=_auth(token),
            timeout=30,
        )
        if r.status_code != 200:
            continue
        kyc = r.json().get("kyc") or {}
        if not kyc.get("aadhar_number") and not kyc.get("pan_number"):
            return u
    return None


# ---------------------------------------------------------------------------
# a. Auth guard — no token
# ---------------------------------------------------------------------------
class TestAuthGuard:
    def test_patch_without_token_returns_401(self, kankani_employees):
        uid = kankani_employees[0]["user_id"]
        r = requests.patch(f"{API}/admin/employees/{uid}/kyc", json={"blood_group": "O+"}, timeout=20)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text}"

    def test_get_without_token_returns_401(self, kankani_employees):
        uid = kankani_employees[0]["user_id"]
        r = requests.get(f"{API}/admin/employees/{uid}/kyc", timeout=20)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text}"

    def test_patch_bad_token(self, kankani_employees):
        uid = kankani_employees[0]["user_id"]
        r = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={"blood_group": "O+"},
            headers={"Authorization": "Bearer garbage-token"},
            timeout=20,
        )
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# b. Role guard — employee cannot use admin endpoint
# ---------------------------------------------------------------------------
class TestRoleGuard:
    def test_employee_cannot_patch(self, kankani_employees):
        # Login as a Kankani employee via SMS OTP (they all have PIN 1234
        # but we bypass PIN by using OTP flow — the phone is on the user record).
        target = None
        for u in kankani_employees:
            if u.get("phone") and u["phone"].startswith("+9198281200"):
                target = u
                break
        assert target, "no Kankani rank-and-file employee found for role guard test"
        emp_token = _otp_login(target["phone"], "sms")
        # PATCH someone else's KYC
        other = next(u for u in kankani_employees if u["user_id"] != target["user_id"])
        r = requests.patch(
            f"{API}/admin/employees/{other['user_id']}/kyc",
            json={"blood_group": "O+"},
            headers=_auth(emp_token),
            timeout=20,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# c. Happy path — super_admin
# ---------------------------------------------------------------------------
class TestHappyPathSuperAdmin:
    def test_patch_and_get_persist(self, super_token, kankani_employees):
        uid = kankani_employees[0]["user_id"]
        payload = {
            "blood_group": "O+",
            "religion": "Hindu",
            "category": "gen",
            "father_name": "Test Father",
            "mother_name": "Test Mother",
            "mobile": "+919999999999",
            "emergency_contact": "9888888888",
            "_source": "ocr",
        }
        r = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json=payload,
            headers=_auth(super_token),
            timeout=30,
        )
        assert r.status_code == 200, f"PATCH failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True
        assert isinstance(body.get("updated_keys"), list) and body["updated_keys"], body
        assert "kyc" in body and isinstance(body["kyc"], dict)
        # Fields reflected
        assert body["kyc"]["blood_group"] == "O+"
        assert body["kyc"]["religion"] == "Hindu"
        assert body["kyc"]["category"] == "gen"
        assert body["kyc"]["father_name"] == "Test Father"
        assert body["kyc"]["mother_name"] == "Test Mother"
        assert body["kyc"]["mobile"] == "+919999999999"
        assert body["kyc"]["emergency_contact"] == "9888888888"

        # GET verifies persistence
        r2 = requests.get(
            f"{API}/admin/employees/{uid}/kyc",
            headers=_auth(super_token),
            timeout=20,
        )
        assert r2.status_code == 200, r2.text
        kyc = r2.json().get("kyc") or {}
        assert kyc.get("blood_group") == "O+"
        assert kyc.get("religion") == "Hindu"
        assert kyc.get("father_name") == "Test Father"
        assert kyc.get("mobile") == "+919999999999"


# ---------------------------------------------------------------------------
# d/e/f. Format validation
# ---------------------------------------------------------------------------
class TestFormatValidation:
    def test_aadhaar_short_returns_400(self, super_token, kankani_employees):
        uid = kankani_employees[0]["user_id"]
        r = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={"aadhar_number": "1234"},
            headers=_auth(super_token),
            timeout=20,
        )
        assert r.status_code == 400, r.text
        assert "Aadhaar" in r.text and "12" in r.text

    def test_pan_bad_format_returns_400(self, super_token, kankani_employees):
        uid = kankani_employees[0]["user_id"]
        r = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={"pan_number": "INVALIDPAN"},
            headers=_auth(super_token),
            timeout=20,
        )
        assert r.status_code == 400, r.text
        assert "PAN" in r.text

    def test_ifsc_bad_format_returns_400(self, super_token, kankani_employees):
        uid = kankani_employees[0]["user_id"]
        r = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={"ifsc_code": "BADIFSC"},
            headers=_auth(super_token),
            timeout=20,
        )
        assert r.status_code == 400, r.text
        assert "IFSC" in r.text and "11" in r.text


# ---------------------------------------------------------------------------
# g. Immutability — Aadhaar and PAN locked after first write
# ---------------------------------------------------------------------------
class TestImmutability:
    """Aadhaar and PAN cannot be changed once set; same value silently passes."""

    def test_aadhaar_immutability(self, super_token, kankani_employees):
        # Pick a truly fresh employee (empty aadhar_number)
        fresh = _find_fresh_employee(super_token, kankani_employees)
        assert fresh is not None, "no fresh employee to test aadhaar lock"
        uid = fresh["user_id"]

        # 1st PATCH — set aadhaar
        aadhar1 = "123456789012"
        r1 = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={"aadhar_number": aadhar1},
            headers=_auth(super_token),
            timeout=20,
        )
        assert r1.status_code == 200, f"first PATCH failed: {r1.status_code} {r1.text}"
        assert r1.json()["kyc"]["aadhar_number"] == aadhar1

        # 2nd PATCH — DIFFERENT aadhaar → 400 locked
        r2 = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={"aadhar_number": "999999999999"},
            headers=_auth(super_token),
            timeout=20,
        )
        assert r2.status_code == 400, r2.text
        assert "locked" in r2.text.lower() or "aadhaar" in r2.text.lower()

        # 3rd PATCH — SAME aadhaar → server drops the field.
        # Since aadhar is the only key, this becomes an empty update → 400 "Nothing to update."
        r3 = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={"aadhar_number": aadhar1},
            headers=_auth(super_token),
            timeout=20,
        )
        # Route drops locked same-value → then hits "Nothing to update." (400)
        assert r3.status_code == 400, r3.text
        assert "Nothing to update" in r3.text

        # 4th PATCH — SAME aadhaar + another editable field → should succeed
        r4 = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={"aadhar_number": aadhar1, "blood_group": "A+"},
            headers=_auth(super_token),
            timeout=20,
        )
        assert r4.status_code == 200, r4.text
        assert r4.json()["kyc"]["aadhar_number"] == aadhar1
        assert r4.json()["kyc"]["blood_group"] == "A+"


# ---------------------------------------------------------------------------
# h. Disability percent clamp / bad value
# ---------------------------------------------------------------------------
class TestDisabilityPercent:
    def test_disability_percent_clamps_to_100(self, super_token, kankani_employees):
        uid = kankani_employees[1]["user_id"]
        r = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={"disability_percent": 250},
            headers=_auth(super_token),
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert float(r.json()["kyc"]["disability_percent"]) == 100.0

    def test_disability_percent_bad_value_returns_400(self, super_token, kankani_employees):
        uid = kankani_employees[1]["user_id"]
        r = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={"disability_percent": "abc"},
            headers=_auth(super_token),
            timeout=20,
        )
        assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# i. Cross-firm guard — company_admin can't touch other firm's employee
# ---------------------------------------------------------------------------
class TestCrossFirmGuard:
    def test_kankani_admin_cannot_patch_non_kankani(self, kankani_admin_token, super_token):
        # No other firm exists in the DB — inject a temporary non-Kankani
        # employee directly via mongo for this test, then clean up.
        temp_uid = f"user_TESTCROSS_{uuid.uuid4().hex[:8]}"
        temp_cid = f"cmp_TESTCROSS_{uuid.uuid4().hex[:8]}"
        _mongo_insert_temp_user(temp_uid, temp_cid)
        try:
            r2 = requests.patch(
                f"{API}/admin/employees/{temp_uid}/kyc",
                json={"blood_group": "B+"},
                headers=_auth(kankani_admin_token),
                timeout=20,
            )
            assert r2.status_code == 403, f"expected 403, got {r2.status_code}: {r2.text}"
        finally:
            _mongo_delete_temp_user(temp_uid)


def _mongo_insert_temp_user(user_id: str, company_id: str) -> None:
    async def _run():
        from motor.motor_asyncio import AsyncIOMotorClient
        mu, dn = _load_mongo_env()
        c = AsyncIOMotorClient(mu)
        try:
            await c[dn].users.insert_one({
                "user_id": user_id,
                "company_id": company_id,
                "role": "employee",
                "name": "TEST_CrossFirm Employee",
                "employee_code": "TESTCROSS01",
                "phone": f"+9188{uuid.uuid4().int % 100000000:08d}",
                "email": f"testcross_{uuid.uuid4().hex[:6]}@test.local",
                "onboarded": True,
                "approval_status": "approved",
            })
        finally:
            c.close()
    _sync(_run)


def _mongo_delete_temp_user(user_id: str) -> None:
    async def _run():
        from motor.motor_asyncio import AsyncIOMotorClient
        mu, dn = _load_mongo_env()
        c = AsyncIOMotorClient(mu)
        try:
            await c[dn].users.delete_one({"user_id": user_id})
            await c[dn].kyc_history.delete_many({"user_id": user_id})
        finally:
            c.close()
    _sync(_run)


def _load_mongo_env() -> Tuple[str, str]:
    mu = os.environ.get("MONGO_URL")
    dn = os.environ.get("DB_NAME")
    if not mu or not dn:
        with open("/app/backend/.env") as fp:
            for line in fp:
                if line.startswith("MONGO_URL=") and not mu:
                    mu = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("DB_NAME=") and not dn:
                    dn = line.split("=", 1)[1].strip().strip('"')
    assert mu and dn, "MONGO_URL / DB_NAME not resolvable"
    return mu, dn


# ---------------------------------------------------------------------------
# j. Empty payload → 400
# ---------------------------------------------------------------------------
class TestEmptyPayload:
    def test_empty_body_returns_400(self, super_token, kankani_employees):
        uid = kankani_employees[0]["user_id"]
        r = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={},
            headers=_auth(super_token),
            timeout=20,
        )
        assert r.status_code == 400, r.text
        assert "Nothing to update" in r.text


# ---------------------------------------------------------------------------
# k. Audit trail — kyc_history row with source=ocr when _source="ocr"
# ---------------------------------------------------------------------------
class TestAuditTrail:
    def test_kyc_history_row_written(self, super_token, kankani_employees):
        # Directly query mongo via the app is not available; instead we verify
        # by making a PATCH with _source="ocr" and then a GET of a debug-safe
        # audit endpoint if it exists. If not, we do a positive assertion on
        # the PATCH response (updated_keys / kyc). The actual mongo row
        # inspection is done via the mongo shell fallback below.
        uid = kankani_employees[2]["user_id"]
        marker = f"AuditTest-{uuid.uuid4().hex[:6]}"
        r = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={"father_name": marker, "_source": "ocr"},
            headers=_auth(super_token),
            timeout=20,
        )
        assert r.status_code == 200, r.text

        # Verify via mongo directly (async)
        row = _read_last_kyc_history(uid)
        assert row is not None, "no kyc_history row written"
        assert row.get("source") == "ocr", f"source={row.get('source')} (want 'ocr')"
        assert row.get("changed_by"), "changed_by missing"
        assert row.get("changed_by_role") in ("super_admin", "sub_admin"), row
        assert "prev" in row and "next" in row
        assert row["next"].get("father_name") == marker

    def test_kyc_history_defaults_source_manual(self, super_token, kankani_employees):
        uid = kankani_employees[2]["user_id"]
        marker = f"MarkerM-{uuid.uuid4().hex[:6]}"
        r = requests.patch(
            f"{API}/admin/employees/{uid}/kyc",
            json={"mother_name": marker},   # no _source
            headers=_auth(super_token),
            timeout=20,
        )
        assert r.status_code == 200, r.text
        row = _read_last_kyc_history(uid)
        assert row is not None
        assert row.get("source") == "manual", f"expected 'manual' default, got {row.get('source')}"


def _read_last_kyc_history(user_id: str) -> Optional[dict]:
    """Fetch most-recent kyc_history entry for a user via motor client."""
    async def _run():
        from motor.motor_asyncio import AsyncIOMotorClient
        mu, dn = _load_mongo_env()
        c = AsyncIOMotorClient(mu)
        try:
            row = await c[dn].kyc_history.find_one(
                {"user_id": user_id},
                sort=[("changed_at", -1)],
            )
            if row and "_id" in row:
                row.pop("_id")
            return row
        finally:
            c.close()
    return _sync(_run)


def _sync(coro_factory):
    """Run an async coroutine factory in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Additional smoke — 404 on unknown user
# ---------------------------------------------------------------------------
class TestUnknownEmployee:
    def test_patch_unknown_user_returns_404(self, super_token):
        r = requests.patch(
            f"{API}/admin/employees/user_doesnotexist/kyc",
            json={"blood_group": "O+"},
            headers=_auth(super_token),
            timeout=20,
        )
        assert r.status_code == 404, r.text

    def test_get_unknown_user_returns_404(self, super_token):
        r = requests.get(
            f"{API}/admin/employees/user_doesnotexist/kyc",
            headers=_auth(super_token),
            timeout=20,
        )
        assert r.status_code == 404, r.text
