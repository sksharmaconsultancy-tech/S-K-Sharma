"""Backend tests for offboarding/exit_date feature.

Covers:
- GET /api/auth/me returns `company_name` and `offboarded` fields
- PATCH /api/admin/user-role: super_admin can set/clear exit_date, role is optional
- PATCH /api/admin/user-role: company_admin limited to own company, 403 for cross-company
- exit_date="" clears the field
- Super admin auto-promotion on OTP login
- OTP dev-mode returns dev_code, verify returns session_token
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE = os.environ["EXPO_BACKEND_URL"].rstrip("/")
SUPER_EMAIL = "sksharmaconsultancy@gmail.com"


# ---------------- Helpers ----------------
def _otp_login(sess: requests.Session, identifier: str, channel: str = "email"):
    """Perform OTP login and return (session_token, user)."""
    r = sess.post(f"{BASE}/api/auth/otp/request",
                  json={"identifier": identifier, "channel": channel})
    assert r.status_code == 200, r.text
    code = r.json()["dev_code"]
    r = sess.post(f"{BASE}/api/auth/otp/verify",
                  json={"identifier": identifier, "code": code, "channel": channel})
    assert r.status_code == 200, r.text
    j = r.json()
    return j["session_token"], j["user"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# ---------------- Super admin auto-promotion ----------------
class TestSuperAdminPromotion:
    def test_super_admin_email_promoted_on_login(self, s):
        token, user = _otp_login(s, SUPER_EMAIL, "email")
        assert user["role"] == "super_admin", f"Expected super_admin, got {user['role']}"
        # verify via /auth/me
        r = s.get(f"{BASE}/api/auth/me", headers=_auth_headers(token))
        assert r.status_code == 200
        me = r.json()["user"]
        assert me["role"] == "super_admin"
        assert me.get("offboarded") is False


# ---------------- /auth/me offboarded & company_name ----------------
class TestAuthMeOffboarded:
    def test_me_offboarded_false_by_default(self, s):
        email = f"qa_emp_{uuid.uuid4().hex[:8]}@test.com"
        token, _ = _otp_login(s, email, "email")
        r = s.get(f"{BASE}/api/auth/me", headers=_auth_headers(token))
        assert r.status_code == 200
        me = r.json()["user"]
        assert me["offboarded"] is False
        # No company assigned yet -> no company_name
        assert me.get("company_name") is None

    def test_me_offboarded_true_after_super_admin_sets_past_exit(self, s):
        # Setup: super admin creates company, assigns employee, sets exit_date past
        super_token, super_user = _otp_login(s, SUPER_EMAIL, "email")
        super_headers = _auth_headers(super_token)

        # Create company
        cname = f"TEST_Co_{uuid.uuid4().hex[:6]}"
        r = s.post(f"{BASE}/api/companies", headers=super_headers, json={
            "name": cname, "office_lat": 12.9, "office_lng": 77.6,
            "geofence_radius_m": 200, "compliance_enabled": True,
        })
        assert r.status_code == 200, r.text
        company = r.json()
        cid = company["company_id"]

        # Create employee via OTP
        emp_email = f"qa_emp_{uuid.uuid4().hex[:8]}@test.com"
        emp_sess = requests.Session()
        emp_token, emp_user = _otp_login(emp_sess, emp_email, "email")

        # Super admin assigns company and past exit_date
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        r = s.patch(f"{BASE}/api/admin/user-role", headers=super_headers, json={
            "user_id": emp_user["user_id"],
            "company_id": cid,
            "exit_date": yesterday,
        })
        assert r.status_code == 200, r.text
        assert r.json()["exit_date"] == yesterday
        assert r.json()["company_id"] == cid

        # Employee /auth/me should show offboarded True + company_name
        r = emp_sess.get(f"{BASE}/api/auth/me", headers=_auth_headers(emp_token))
        assert r.status_code == 200
        me = r.json()["user"]
        assert me["offboarded"] is True, me
        assert me["company_name"] == cname
        assert me["exit_date"] == yesterday

    def test_me_offboarded_false_when_exit_date_future(self, s):
        super_token, _ = _otp_login(s, SUPER_EMAIL, "email")
        super_headers = _auth_headers(super_token)
        emp_email = f"qa_emp_{uuid.uuid4().hex[:8]}@test.com"
        emp_sess = requests.Session()
        emp_token, emp_user = _otp_login(emp_sess, emp_email, "email")

        future = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        r = s.patch(f"{BASE}/api/admin/user-role", headers=super_headers, json={
            "user_id": emp_user["user_id"], "exit_date": future,
        })
        assert r.status_code == 200

        r = emp_sess.get(f"{BASE}/api/auth/me", headers=_auth_headers(emp_token))
        me = r.json()["user"]
        assert me["offboarded"] is False, "Future exit_date must NOT offboard"
        assert me["exit_date"] == future


# ---------------- PATCH /api/admin/user-role ----------------
class TestRoleUpdateExitDate:
    def test_super_admin_can_clear_exit_date_with_empty_string(self, s):
        super_token, _ = _otp_login(s, SUPER_EMAIL, "email")
        super_headers = _auth_headers(super_token)
        emp_email = f"qa_emp_{uuid.uuid4().hex[:8]}@test.com"
        emp_sess = requests.Session()
        _, emp_user = _otp_login(emp_sess, emp_email, "email")

        past = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        # Set
        r = s.patch(f"{BASE}/api/admin/user-role", headers=super_headers,
                    json={"user_id": emp_user["user_id"], "exit_date": past})
        assert r.status_code == 200
        assert r.json()["exit_date"] == past

        # Clear via empty string
        r = s.patch(f"{BASE}/api/admin/user-role", headers=super_headers,
                    json={"user_id": emp_user["user_id"], "exit_date": ""})
        assert r.status_code == 200, r.text
        assert r.json().get("exit_date") in (None, "")

        # GET to confirm persistence
        r = s.get(f"{BASE}/api/admin/employees", headers=super_headers)
        assert r.status_code == 200
        emp = next((u for u in r.json()["employees"] if u["user_id"] == emp_user["user_id"]), None)
        assert emp is not None
        assert emp.get("exit_date") in (None, "")

    def test_role_is_optional(self, s):
        """RoleUpdate without a `role` field must succeed (role now Optional)."""
        super_token, _ = _otp_login(s, SUPER_EMAIL, "email")
        super_headers = _auth_headers(super_token)
        emp_email = f"qa_emp_{uuid.uuid4().hex[:8]}@test.com"
        emp_sess = requests.Session()
        _, emp_user = _otp_login(emp_sess, emp_email, "email")

        r = s.patch(f"{BASE}/api/admin/user-role", headers=super_headers,
                    json={"user_id": emp_user["user_id"], "department": "Ops"})
        assert r.status_code == 200, r.text
        assert r.json()["department"] == "Ops"
        # role unchanged
        assert r.json()["role"] == "employee"

    def test_company_admin_can_set_exit_date_within_own_company(self, s):
        # Super admin sets up: 1 company, promotes 1 user to company_admin, adds employee
        super_token, _ = _otp_login(s, SUPER_EMAIL, "email")
        super_headers = _auth_headers(super_token)

        cname = f"TEST_Co_{uuid.uuid4().hex[:6]}"
        r = s.post(f"{BASE}/api/companies", headers=super_headers, json={
            "name": cname, "office_lat": 12.9, "office_lng": 77.6,
        })
        assert r.status_code == 200
        cid = r.json()["company_id"]

        # Create company_admin user
        ca_email = f"qa_ca_{uuid.uuid4().hex[:8]}@test.com"
        ca_sess = requests.Session()
        ca_token, ca_user = _otp_login(ca_sess, ca_email, "email")
        r = s.patch(f"{BASE}/api/admin/user-role", headers=super_headers, json={
            "user_id": ca_user["user_id"], "role": "company_admin", "company_id": cid,
        })
        assert r.status_code == 200
        assert r.json()["role"] == "company_admin"

        # Create an employee in same company
        emp_email = f"qa_emp_{uuid.uuid4().hex[:8]}@test.com"
        emp_sess = requests.Session()
        _, emp_user = _otp_login(emp_sess, emp_email, "email")
        r = s.patch(f"{BASE}/api/admin/user-role", headers=super_headers, json={
            "user_id": emp_user["user_id"], "company_id": cid,
        })
        assert r.status_code == 200

        # Company admin sets exit date for that employee
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = ca_sess.patch(f"{BASE}/api/admin/user-role", headers=_auth_headers(ca_token), json={
            "user_id": emp_user["user_id"], "exit_date": today,
        })
        assert r.status_code == 200, r.text
        assert r.json()["exit_date"] == today

        # Employee /auth/me should now show offboarded True with correct company_name
        r = emp_sess.get(f"{BASE}/api/auth/me", headers=_auth_headers(_otp_re_login(emp_sess, emp_email)))
        me = r.json()["user"]
        assert me["offboarded"] is True
        assert me["company_name"] == cname

    def test_company_admin_cannot_set_exit_date_for_other_company(self, s):
        super_token, _ = _otp_login(s, SUPER_EMAIL, "email")
        super_headers = _auth_headers(super_token)

        # Two companies
        r1 = s.post(f"{BASE}/api/companies", headers=super_headers, json={
            "name": f"TEST_A_{uuid.uuid4().hex[:6]}", "office_lat": 12.9, "office_lng": 77.6})
        assert r1.status_code == 200
        cid_a = r1.json()["company_id"]
        r2 = s.post(f"{BASE}/api/companies", headers=super_headers, json={
            "name": f"TEST_B_{uuid.uuid4().hex[:6]}", "office_lat": 12.9, "office_lng": 77.6})
        assert r2.status_code == 200
        cid_b = r2.json()["company_id"]

        # company_admin in A
        ca_email = f"qa_ca_{uuid.uuid4().hex[:8]}@test.com"
        ca_sess = requests.Session()
        ca_token, ca_user = _otp_login(ca_sess, ca_email, "email")
        s.patch(f"{BASE}/api/admin/user-role", headers=super_headers, json={
            "user_id": ca_user["user_id"], "role": "company_admin", "company_id": cid_a})

        # employee in B
        emp_email = f"qa_emp_{uuid.uuid4().hex[:8]}@test.com"
        emp_sess = requests.Session()
        _, emp_user = _otp_login(emp_sess, emp_email, "email")
        s.patch(f"{BASE}/api/admin/user-role", headers=super_headers, json={
            "user_id": emp_user["user_id"], "company_id": cid_b})

        # cross-company attempt -> 403
        r = ca_sess.patch(f"{BASE}/api/admin/user-role", headers=_auth_headers(ca_token), json={
            "user_id": emp_user["user_id"], "exit_date": "2026-01-01"})
        assert r.status_code == 403, r.text

    def test_company_admin_cannot_change_role_or_reassign_company(self, s):
        """Only super_admin can change role/company_id via RoleUpdate."""
        super_token, _ = _otp_login(s, SUPER_EMAIL, "email")
        super_headers = _auth_headers(super_token)
        r = s.post(f"{BASE}/api/companies", headers=super_headers, json={
            "name": f"TEST_C_{uuid.uuid4().hex[:6]}", "office_lat": 12.9, "office_lng": 77.6})
        cid = r.json()["company_id"]
        ca_email = f"qa_ca_{uuid.uuid4().hex[:8]}@test.com"
        ca_sess = requests.Session()
        ca_token, ca_user = _otp_login(ca_sess, ca_email, "email")
        s.patch(f"{BASE}/api/admin/user-role", headers=super_headers, json={
            "user_id": ca_user["user_id"], "role": "company_admin", "company_id": cid})

        emp_email = f"qa_emp_{uuid.uuid4().hex[:8]}@test.com"
        emp_sess = requests.Session()
        _, emp_user = _otp_login(emp_sess, emp_email, "email")
        s.patch(f"{BASE}/api/admin/user-role", headers=super_headers, json={
            "user_id": emp_user["user_id"], "company_id": cid})

        # company_admin tries to promote employee to company_admin (should silently ignore role change)
        r = ca_sess.patch(f"{BASE}/api/admin/user-role", headers=_auth_headers(ca_token), json={
            "user_id": emp_user["user_id"], "role": "company_admin", "department": "HR"})
        assert r.status_code == 200
        assert r.json()["role"] == "employee", "company_admin must NOT be able to change role"
        assert r.json()["department"] == "HR"


def _otp_re_login(sess: requests.Session, email: str) -> str:
    """Helper: fresh OTP login, return new session token."""
    r = sess.post(f"{BASE}/api/auth/otp/request", json={"identifier": email, "channel": "email"})
    code = r.json()["dev_code"]
    r = sess.post(f"{BASE}/api/auth/otp/verify",
                  json={"identifier": email, "code": code, "channel": "email"})
    return r.json()["session_token"]
