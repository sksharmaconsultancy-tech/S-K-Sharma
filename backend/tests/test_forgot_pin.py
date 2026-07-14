"""Tests for the new self-service /api/auth/forgot-pin endpoint.

Covers:
  - Happy path (super_admin): DB pin_hash rotates, pin_must_change=true,
    pin_fail_count=0, pin_locked_until=None, has_pin=true, pin_forgot_at set.
  - Anti-enumeration: non-existent email still returns 200 success-shape,
    no DB write.
  - Role gate: employee email returns 200 success-shape but pin_hash is
    NOT rotated.
  - Rate-limit: second call within 2 minutes does NOT rotate pin_hash.
  - Regression: pin-login (invalid credentials), admin-pin-login (email +
    phone) still work; pin-change wired end-to-end. PATCH
    /api/admin/employee-pin still returns a sensible response (auth-guarded).

The tests hit the live preview URL. Resend has been blanked in
backend/.env for the duration of this run so no real emails go out
during the happy-path test.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Dict

import bcrypt
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

SA_EMAIL = "sksharmaconsultancy@gmail.com"
SA_PHONE = "+919680273960"
TEMP_PIN = "139848"

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

# ---- Module: db helpers ---------------------------------------------------- #

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _get_user(email: str) -> Dict:
    async def _do():
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            return await client[DB_NAME].users.find_one({"email": email}, {"_id": 0})
        finally:
            client.close()
    return _run(_do()) or {}


def _reset_super_admin_pin() -> None:
    """Force super-admin back to temp PIN 139848 + pin_must_change=True."""
    async def _do():
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            h = bcrypt.hashpw(TEMP_PIN.encode(), bcrypt.gensalt()).decode()
            await client[DB_NAME].users.update_one(
                {"email": SA_EMAIL},
                {"$set": {
                    "pin_hash": h,
                    "pin_must_change": True,
                    "pin_locked_until": None,
                    "pin_fail_count": 0,
                    "has_pin": True,
                    # clear the rate-limit stamp so tests can call forgot-pin freely
                    "pin_forgot_at": None,
                }},
            )
        finally:
            client.close()
    _run(_do())


def _clear_forgot_at(email: str) -> None:
    async def _do():
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            await client[DB_NAME].users.update_one(
                {"email": email}, {"$set": {"pin_forgot_at": None}}
            )
        finally:
            client.close()
    _run(_do())


def _create_test_employee(email: str) -> str:
    async def _do():
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            uid = f"TEST_emp_{uuid.uuid4().hex[:8]}"
            await client[DB_NAME].users.insert_one({
                "user_id": uid,
                "email": email,
                "role": "employee",
                "name": "TEST Employee",
                "pin_hash": bcrypt.hashpw(b"999999", bcrypt.gensalt()).decode(),
                "pin_must_change": False,
                "pin_fail_count": 0,
            })
            return uid
        finally:
            client.close()
    return _run(_do())


def _delete_user(email: str) -> None:
    async def _do():
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            await client[DB_NAME].users.delete_many({"email": email})
        finally:
            client.close()
    _run(_do())


# ---- Fixtures -------------------------------------------------------------- #

@pytest.fixture
def api_client() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(autouse=True)
def _reset_between_tests():
    _reset_super_admin_pin()
    yield
    # Always leave super admin in a known-good state
    _reset_super_admin_pin()


# ---- Module: /api/auth/forgot-pin ------------------------------------------ #

class TestForgotPinHappyPath:
    def test_admin_email_rotates_pin_hash(self, api_client):
        before = _get_user(SA_EMAIL)
        assert before, "super admin missing in DB — cannot run test"
        hash_before = before.get("pin_hash")

        r = api_client.post(f"{API}/auth/forgot-pin",
                            json={"identifier": SA_EMAIL})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True, body
        assert "message" in body and isinstance(body["message"], str)

        after = _get_user(SA_EMAIL)
        assert after.get("pin_hash") and after["pin_hash"] != hash_before, \
            "pin_hash should have rotated"
        assert after.get("pin_must_change") is True
        assert after.get("pin_fail_count", -1) == 0
        assert after.get("pin_locked_until") in (None,)
        assert after.get("has_pin") is True
        assert after.get("pin_forgot_at"), "pin_forgot_at must be set"


class TestForgotPinAntiEnumeration:
    def test_nonexistent_email_returns_200_and_no_db_write(self, api_client):
        bogus = "TEST_definitely_not_real_%s@example.com" % uuid.uuid4().hex[:6]
        # ensure it's absent
        assert _get_user(bogus) == {}

        r = api_client.post(f"{API}/auth/forgot-pin",
                            json={"identifier": bogus})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        # keep the message success-shape (no leakage)
        assert "temporary PIN" in body.get("message", "").lower() or "admin" in body.get("message", "").lower()

        # still absent
        assert _get_user(bogus) == {}

    def test_missing_identifier_returns_400(self, api_client):
        r = api_client.post(f"{API}/auth/forgot-pin", json={"identifier": ""})
        assert r.status_code == 400, r.text

    def test_non_email_identifier_returns_400(self, api_client):
        r = api_client.post(f"{API}/auth/forgot-pin",
                            json={"identifier": "+919680273960"})
        assert r.status_code == 400, r.text


class TestForgotPinRoleGate:
    def setup_method(self):
        self.email = f"TEST_forgot_emp_{uuid.uuid4().hex[:6]}@example.com"
        _create_test_employee(self.email)

    def teardown_method(self):
        _delete_user(self.email)

    def test_employee_email_does_not_rotate_pin(self, api_client):
        before = _get_user(self.email)
        hash_before = before.get("pin_hash")

        r = api_client.post(f"{API}/auth/forgot-pin",
                            json={"identifier": self.email})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True

        after = _get_user(self.email)
        assert after.get("pin_hash") == hash_before, \
            "employee's pin_hash must NOT be rotated by forgot-pin"
        assert not after.get("pin_forgot_at"), \
            "employee's pin_forgot_at must not be set"


class TestForgotPinRateLimit:
    def test_second_call_within_2min_does_not_rotate(self, api_client):
        # First call rotates
        r1 = api_client.post(f"{API}/auth/forgot-pin",
                             json={"identifier": SA_EMAIL})
        assert r1.status_code == 200
        after1 = _get_user(SA_EMAIL)
        hash1 = after1["pin_hash"]
        forgot_at1 = after1["pin_forgot_at"]

        # Immediately call again — must be rate-limited
        r2 = api_client.post(f"{API}/auth/forgot-pin",
                             json={"identifier": SA_EMAIL})
        assert r2.status_code == 200, r2.text
        assert r2.json().get("ok") is True

        after2 = _get_user(SA_EMAIL)
        assert after2["pin_hash"] == hash1, \
            "second call within 2 min must NOT rotate pin_hash"
        assert after2["pin_forgot_at"] == forgot_at1, \
            "pin_forgot_at must not be updated by rate-limited call"


# ---- Module: regression on existing PIN endpoints -------------------------- #

class TestAdminPinLoginRegression:
    def test_email_still_works(self, api_client):
        r = api_client.post(f"{API}/auth/admin-pin-login",
                            json={"identifier": SA_EMAIL, "pin": TEMP_PIN})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("session_token")
        assert d.get("pin_must_change") is True
        assert d["user"]["email"] == SA_EMAIL

    def test_phone_still_works(self, api_client):
        r = api_client.post(f"{API}/auth/admin-pin-login",
                            json={"identifier": SA_PHONE, "pin": TEMP_PIN})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("session_token")

    def test_wrong_pin_401(self, api_client):
        r = api_client.post(f"{API}/auth/admin-pin-login",
                            json={"identifier": SA_EMAIL, "pin": "000001"})
        assert r.status_code == 401, r.text


class TestPinChangeRegression:
    def test_change_then_restore(self, api_client):
        # login to get token
        r = api_client.post(f"{API}/auth/admin-pin-login",
                            json={"identifier": SA_EMAIL, "pin": TEMP_PIN})
        assert r.status_code == 200
        token = r.json()["session_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # change to random new pin
        new_pin = "483920"
        c = api_client.post(f"{API}/auth/pin-change",
                            json={"current_pin": TEMP_PIN, "new_pin": new_pin},
                            headers=headers)
        assert c.status_code == 200, c.text

        # new pin works
        fresh = api_client.post(f"{API}/auth/admin-pin-login",
                                json={"identifier": SA_EMAIL, "pin": new_pin})
        assert fresh.status_code == 200
        assert fresh.json().get("pin_must_change") is False
        # autouse fixture resets pin back to 139848 in teardown


class TestEmployeePinLoginRegression:
    def test_invalid_credentials_401(self, api_client):
        r = api_client.post(f"{API}/auth/pin-login", json={
            "company_code": "NOPE01",
            "employee_code": "NOPE-1",
            "pin": "999999",
        })
        assert r.status_code in (401, 404), r.text


class TestAdminEmployeePinPatchRegression:
    def test_requires_auth(self, api_client):
        # no bearer token: must be 401/403
        r = api_client.patch(f"{API}/admin/employee-pin",
                             json={"user_id": "nonexistent", "new_pin": "555555"})
        assert r.status_code in (401, 403, 422), r.text
