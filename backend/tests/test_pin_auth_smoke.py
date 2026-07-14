"""Smoke tests for PIN-based auth (admin + employee + pin-change).

Covers only the new endpoints introduced in the PIN login rework:
  - POST /api/auth/admin-pin-login  (identifier = email OR phone)
  - POST /api/auth/pin-change       (forced change on first login)
  - GET  /api/auth/me               (verify pin_must_change resets)
  - POST /api/auth/pin-login        (invalid credentials path only)

The super-admin temp PIN is intentionally reset to `139848` before each
happy-path run by directly patching the DB, so the tests are idempotent
and can be re-run safely.
"""

from __future__ import annotations

import asyncio
import os
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
NEW_PIN = "452801"

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def api_client() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _reset_super_admin_pin() -> None:
    """Force super-admin back to temp PIN 139848 + pin_must_change=True."""
    async def _do():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        h = bcrypt.hashpw(TEMP_PIN.encode(), bcrypt.gensalt()).decode()
        await db.users.update_one(
            {"email": SA_EMAIL},
            {"$set": {
                "pin_hash": h,
                "pin_must_change": True,
                "pin_locked_until": None,
                "pin_failed_attempts": 0,
            }},
        )
        client.close()

    asyncio.get_event_loop().run_until_complete(_do())


@pytest.fixture(scope="module", autouse=True)
def _prep():
    _reset_super_admin_pin()
    yield
    _reset_super_admin_pin()  # leave DB in a known good state


# --------------------------------------------------------------------------- #
# admin-pin-login
# --------------------------------------------------------------------------- #
class TestAdminPinLogin:
    def test_email_success(self, api_client):
        r = api_client.post(f"{API}/auth/admin-pin-login",
                            json={"identifier": SA_EMAIL, "pin": TEMP_PIN})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "session_token" in d and d["session_token"]
        assert d.get("pin_must_change") is True
        assert d["user"]["email"] == SA_EMAIL
        assert d["user"]["role"] in ("super_admin", "company_admin")

    def test_phone_success(self, api_client):
        # phone flow requires PIN still valid — reset first because previous
        # test may have consumed lockout attempts
        _reset_super_admin_pin()
        r = api_client.post(f"{API}/auth/admin-pin-login",
                            json={"identifier": SA_PHONE, "pin": TEMP_PIN})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("session_token")
        assert d.get("pin_must_change") is True

    def test_wrong_pin_returns_401(self, api_client):
        _reset_super_admin_pin()
        r = api_client.post(f"{API}/auth/admin-pin-login",
                            json={"identifier": SA_EMAIL, "pin": "000001"})
        assert r.status_code == 401, r.text

    def test_missing_identifier_rejected(self, api_client):
        r = api_client.post(f"{API}/auth/admin-pin-login",
                            json={"identifier": "", "pin": TEMP_PIN})
        assert r.status_code in (400, 401, 422)


# --------------------------------------------------------------------------- #
# pin-change + /auth/me
# --------------------------------------------------------------------------- #
class TestPinChangeFlow:
    def _login(self, api_client) -> Dict[str, str]:
        _reset_super_admin_pin()
        r = api_client.post(f"{API}/auth/admin-pin-login",
                            json={"identifier": SA_EMAIL, "pin": TEMP_PIN})
        assert r.status_code == 200, r.text
        return r.json()

    def test_change_pin_success_and_me_reflects(self, api_client):
        login = self._login(api_client)
        token = login["session_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Trivial PINs blocked server-side
        bad = api_client.post(f"{API}/auth/pin-change",
                              json={"current_pin": TEMP_PIN, "new_pin": "111111"},
                              headers=headers)
        assert bad.status_code in (400, 422), bad.text

        # Successful change
        ok = api_client.post(f"{API}/auth/pin-change",
                             json={"current_pin": TEMP_PIN, "new_pin": NEW_PIN},
                             headers=headers)
        assert ok.status_code == 200, ok.text

        # /auth/me reflects change
        me = api_client.get(f"{API}/auth/me", headers=headers)
        assert me.status_code == 200, me.text
        mj = me.json()
        # /auth/me may wrap the payload under "user" or return flat
        me_user = mj.get("user", mj)
        assert me_user.get("pin_must_change") is False, mj

        # Old temp PIN no longer works
        stale = api_client.post(f"{API}/auth/admin-pin-login",
                                json={"identifier": SA_EMAIL, "pin": TEMP_PIN})
        assert stale.status_code == 401

        # New PIN works
        fresh = api_client.post(f"{API}/auth/admin-pin-login",
                                json={"identifier": SA_EMAIL, "pin": NEW_PIN})
        assert fresh.status_code == 200
        assert fresh.json().get("pin_must_change") is False

    def test_wrong_current_pin_rejected(self, api_client):
        login = self._login(api_client)
        token = login["session_token"]
        headers = {"Authorization": f"Bearer {token}"}
        r = api_client.post(f"{API}/auth/pin-change",
                            json={"current_pin": "999999", "new_pin": NEW_PIN},
                            headers=headers)
        assert r.status_code in (400, 401), r.text


# --------------------------------------------------------------------------- #
# employee pin-login (invalid-credentials path only)
# --------------------------------------------------------------------------- #
class TestEmployeePinLoginError:
    def test_invalid_credentials_returns_401(self, api_client):
        r = api_client.post(f"{API}/auth/pin-login", json={
            "company_code": "NOPE01",
            "employee_code": "NOPE-1",
            "pin": "999999",
        })
        assert r.status_code in (401, 404), r.text
