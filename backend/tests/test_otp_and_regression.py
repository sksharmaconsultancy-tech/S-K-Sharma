"""Backend tests: OTP login (request/verify), session/logout, and regression endpoints.

Covers:
- OTP request success + validation errors (short phone, bad email)
- OTP verify success + bad code + missing + malformed + consumption + 5-attempt lockout
- Session token works on /auth/me and is invalidated by /auth/logout
- Regression: /api/salary/monthly, /api/payslips/{id}/mark-paid, /api/admin/payroll, /api/companies unauth
- Root endpoint healthcheck
"""
import os
import uuid
import pytest
import requests

BASE = os.environ["EXPO_BACKEND_URL"].rstrip("/")


@pytest.fixture
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# ---------------- Root / health ----------------
def test_root_health(s):
    r = s.get(f"{BASE}/api/")
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert j.get("app") == "S.K. Sharma & Co."


# ---------------- OTP request ----------------
class TestOtpRequest:
    def test_sms_success_returns_dev_code(self, s):
        r = s.post(f"{BASE}/api/auth/otp/request",
                   json={"identifier": "+919812345678", "channel": "sms"})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("ok") is True
        assert isinstance(j.get("expires_in"), int) and j["expires_in"] > 0
        assert "dev_code" in j and isinstance(j["dev_code"], str) and len(j["dev_code"]) == 6 and j["dev_code"].isdigit()
        assert "dev_note" in j

    def test_short_phone_400(self, s):
        r = s.post(f"{BASE}/api/auth/otp/request",
                   json={"identifier": "12", "channel": "sms"})
        assert r.status_code == 400

    def test_invalid_email_400(self, s):
        r = s.post(f"{BASE}/api/auth/otp/request",
                   json={"identifier": "not-an-email", "channel": "email"})
        assert r.status_code == 400

    def test_email_success(self, s):
        r = s.post(f"{BASE}/api/auth/otp/request",
                   json={"identifier": f"test_{uuid.uuid4().hex[:6]}@example.com", "channel": "email"})
        assert r.status_code == 200
        assert "dev_code" in r.json()


# ---------------- OTP verify ----------------
def _fresh_phone():
    # E.164-ish 10-digit random Indian mobile-looking number
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


class TestOtpVerify:
    def test_verify_success_returns_session(self, s):
        phone = _fresh_phone()
        r = s.post(f"{BASE}/api/auth/otp/request",
                   json={"identifier": phone, "channel": "sms"})
        assert r.status_code == 200
        code = r.json()["dev_code"]

        r2 = s.post(f"{BASE}/api/auth/otp/verify",
                    json={"identifier": phone, "channel": "sms", "code": code})
        assert r2.status_code == 200, r2.text
        j = r2.json()
        assert isinstance(j.get("session_token"), str) and len(j["session_token"]) > 10
        assert j.get("user") and "role" in j["user"] and "onboarded" in j["user"]

    def test_verify_no_prior_request(self, s):
        phone = _fresh_phone()
        r = s.post(f"{BASE}/api/auth/otp/verify",
                   json={"identifier": phone, "channel": "sms", "code": "123456"})
        assert r.status_code == 400
        assert "Request a new code" in r.json().get("detail", "")

    def test_verify_malformed_code(self, s):
        phone = _fresh_phone()
        s.post(f"{BASE}/api/auth/otp/request",
               json={"identifier": phone, "channel": "sms"})
        r = s.post(f"{BASE}/api/auth/otp/verify",
                   json={"identifier": phone, "channel": "sms", "code": "abc"})
        assert r.status_code == 400
        assert "6-digit" in r.json().get("detail", "")

    def test_verify_wrong_code(self, s):
        phone = _fresh_phone()
        req = s.post(f"{BASE}/api/auth/otp/request",
                     json={"identifier": phone, "channel": "sms"})
        real = req.json()["dev_code"]
        bad = "000000" if real != "000000" else "111111"
        r = s.post(f"{BASE}/api/auth/otp/verify",
                   json={"identifier": phone, "channel": "sms", "code": bad})
        assert r.status_code == 400
        assert "Incorrect" in r.json().get("detail", "")

    def test_verify_consumed_after_success(self, s):
        phone = _fresh_phone()
        req = s.post(f"{BASE}/api/auth/otp/request",
                     json={"identifier": phone, "channel": "sms"})
        code = req.json()["dev_code"]
        r1 = s.post(f"{BASE}/api/auth/otp/verify",
                    json={"identifier": phone, "channel": "sms", "code": code})
        assert r1.status_code == 200
        # Second verify with same code must fail (record deleted)
        r2 = s.post(f"{BASE}/api/auth/otp/verify",
                    json={"identifier": phone, "channel": "sms", "code": code})
        assert r2.status_code == 400
        assert "Request a new code" in r2.json().get("detail", "")

    def test_verify_five_attempts_locks_out(self, s):
        phone = _fresh_phone()
        req = s.post(f"{BASE}/api/auth/otp/request",
                     json={"identifier": phone, "channel": "sms"})
        real = req.json()["dev_code"]
        bad = "000000" if real != "000000" else "111111"
        # 5 wrong attempts -> the 5th one deletes record (attempts>=5 check happens before hash compare)
        # so attempts 1..4 return Incorrect, 5th also Incorrect BUT increments to 5; 6th finds attempts>=5 and deletes.
        last_status = None
        last_detail = None
        for i in range(6):
            r = s.post(f"{BASE}/api/auth/otp/verify",
                       json={"identifier": phone, "channel": "sms", "code": bad})
            last_status = r.status_code
            last_detail = r.json().get("detail", "")
        assert last_status == 400
        # Final message should be a clear one (either "Too many" or "Request a new" after deletion)
        assert ("Too many" in last_detail) or ("Request a new" in last_detail)


# ---------------- Session token lifecycle ----------------
class TestSessionLifecycle:
    def test_me_and_logout_flow(self, s):
        phone = _fresh_phone()
        req = s.post(f"{BASE}/api/auth/otp/request",
                     json={"identifier": phone, "channel": "sms"})
        code = req.json()["dev_code"]
        verify = s.post(f"{BASE}/api/auth/otp/verify",
                        json={"identifier": phone, "channel": "sms", "code": code})
        assert verify.status_code == 200
        j = verify.json()
        token = j["session_token"]
        user_from_verify = j["user"]

        # /auth/me works
        me = s.get(f"{BASE}/api/auth/me",
                   headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200, me.text
        me_user = me.json()["user"]
        assert me_user["user_id"] == user_from_verify["user_id"]
        assert me_user["role"] == user_from_verify["role"]

        # logout
        lo = s.post(f"{BASE}/api/auth/logout",
                    headers={"Authorization": f"Bearer {token}"})
        assert lo.status_code == 200
        assert lo.json().get("ok") is True

        # token invalidated
        me2 = s.get(f"{BASE}/api/auth/me",
                    headers={"Authorization": f"Bearer {token}"})
        assert me2.status_code == 401


# ---------------- Regression: auth-gated endpoints require token ----------------
class TestRegressionAuthGates:
    def test_salary_monthly_unauth(self, s):
        assert s.get(f"{BASE}/api/salary/monthly").status_code == 401

    def test_mark_paid_unauth(self, s):
        assert s.patch(f"{BASE}/api/payslips/does_not_exist/mark-paid").status_code == 401

    def test_admin_payroll_unauth(self, s):
        assert s.get(f"{BASE}/api/admin/payroll").status_code == 401

    def test_create_company_unauth(self, s):
        assert s.post(f"{BASE}/api/companies",
                      json={"name": "X", "office_lat": 0.0, "office_lng": 0.0}).status_code == 401
