"""
Iteration 21 — Biometric Unlock verification.
Light backend smoke only: confirm health + OTP-based ephemeral login still work,
without touching super_admin PIN / state.
"""
import os
import uuid
import time
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or \
       os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
API = f"{BASE}/api"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# ---- Health / root ---------------------------------------------------------
class TestHealth:
    def test_root(self, s):
        r = s.get(f"{API}/")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert "app" in body


# ---- Ephemeral OTP login smoke (no super_admin, no PIN mutation) ----------
class TestOtpLogin:
    def test_otp_email_request_and_verify(self, s):
        email = f"iter21.qa.{uuid.uuid4().hex[:8]}@test.local"
        # 1) Request OTP
        r = s.post(f"{API}/auth/otp/request",
                   json={"channel": "email", "identifier": email})
        assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text}"
        body = r.json()
        # In OTP_DEV_MODE the code is returned in-body
        code = body.get("code") or body.get("dev_code")
        assert code, f"no code/dev_code in response body (dev mode expected): {body}"

        # 2) Verify OTP → issues session_token
        r2 = s.post(f"{API}/auth/otp/verify",
                    json={"channel": "email", "identifier": email, "code": code})
        assert r2.status_code == 200, f"otp/verify failed: {r2.status_code} {r2.text}"
        v = r2.json()
        token = v.get("session_token")
        user = v.get("user") or {}
        assert token, f"no session_token in verify response: {v}"
        assert user.get("email", "").lower() == email.lower()

        # 3) /auth/me must work with token
        me = s.get(f"{API}/auth/me",
                   headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200, f"/auth/me failed: {me.status_code} {me.text}"
        mu = me.json().get("user") or {}
        assert mu.get("email", "").lower() == email.lower()
        assert mu.get("role") in ("employee", "company_admin", "super_admin")


# ---- pin-login invalid path (never mutates super_admin) --------------------
class TestPinLoginInvalid:
    def test_pin_login_bad_credentials_returns_error(self, s):
        # deliberate bogus employee_code + pin so we never touch a real user
        r = s.post(f"{API}/auth/pin-login",
                   json={"employee_code": f"NOPE-{uuid.uuid4().hex[:6]}",
                         "pin": "000000"})
        # Should NOT 500; expect 400/401/404
        assert r.status_code in (400, 401, 403, 404), \
            f"unexpected status: {r.status_code} {r.text}"
