"""Iteration 12 — Contract test for admin-pin-login with fresh PIN 246810.

Verifies:
 - POST /api/auth/admin-pin-login accepts email + PIN 246810  → 200 + session_token + pin_must_change=true
 - POST /api/auth/admin-pin-login accepts phone + PIN 246810 → 200 + session_token + pin_must_change=true
 - Wrong PIN (000000) → 401

Does NOT call /auth/change-pin so the temp PIN 246810 remains valid at end of run.
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
EMAIL = "sksharmaconsultancy@gmail.com"
PHONE = "+919680273960"
PIN = "246810"


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(api_client, identifier, pin):
    return api_client.post(
        f"{BASE_URL}/api/auth/admin-pin-login",
        json={"identifier": identifier, "pin": pin},
        timeout=15,
    )


class TestAdminPinLoginFreshPin:
    def test_email_identifier_pin_246810_returns_200(self, api_client):
        r = _login(api_client, EMAIL, PIN)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("session_token", "").startswith("pin_")
        assert data.get("pin_must_change") is True
        user = data.get("user") or {}
        assert user.get("email") == EMAIL
        assert user.get("role") == "super_admin"

    def test_phone_identifier_pin_246810_returns_200(self, api_client):
        r = _login(api_client, PHONE, PIN)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("session_token", "").startswith("pin_")
        assert data.get("pin_must_change") is True
        user = data.get("user") or {}
        assert user.get("email") == EMAIL
        assert user.get("phone") == PHONE

    def test_wrong_pin_returns_401(self, api_client):
        r = _login(api_client, EMAIL, "000000")
        assert r.status_code == 401, r.text
        assert "Invalid" in (r.json().get("detail") or "")
