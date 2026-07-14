"""Backend tests for the new employee approval workflow.

Covers:
- POST /api/onboarding sets approval_status='pending' + approval_requested_at
- GET /api/auth/me flags approval_pending / approval_rejected correctly
- Legacy users without approval_status field are treated as approved
- GET /api/admin/pending-approvals RBAC + scoping + company_name
- PATCH /api/admin/approve-employee approve / reject paths + RBAC + validation
- PATCH /api/admin/user-role: super_admin assigning a company_id auto-approves
"""
import os
import uuid
import pytest
import requests

BASE = os.environ["EXPO_BACKEND_URL"].rstrip("/")
SUPER_EMAIL = "sksharmaconsultancy@gmail.com"


# ---------------- helpers ----------------
def _fresh_email(prefix="qa"):
    return f"TEST_{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _fresh_phone():
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


def _otp_login(sess, identifier, channel="email"):
    r = sess.post(f"{BASE}/api/auth/otp/request",
                  json={"identifier": identifier, "channel": channel})
    assert r.status_code == 200, r.text
    code = r.json()["dev_code"]
    v = sess.post(f"{BASE}/api/auth/otp/verify",
                  json={"identifier": identifier, "channel": channel, "code": code})
    assert v.status_code == 200, v.text
    j = v.json()
    return j["session_token"], j["user"]


def _me(sess, token):
    r = sess.get(f"{BASE}/api/auth/me",
                 headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["user"]


@pytest.fixture(scope="module")
def super_admin():
    """Super admin session — sksharmaconsultancy@gmail.com is auto-promoted."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    token, user = _otp_login(s, SUPER_EMAIL, "email")
    user = _me(s, token)
    assert user.get("role") == "super_admin", f"Expected super_admin, got {user.get('role')}"
    return {"session": s, "token": token, "user": user}


@pytest.fixture(scope="module")
def test_company(super_admin):
    """Create a fresh company via super_admin. Returns dict with company_id + code."""
    s = super_admin["session"]
    payload = {
        "name": f"TEST_ApprovalCo_{uuid.uuid4().hex[:6]}",
        "office_lat": 28.6139,
        "office_lng": 77.2090,
        "geofence_m": 200,
    }
    r = s.post(f"{BASE}/api/companies",
               json=payload,
               headers={"Authorization": f"Bearer {super_admin['token']}"})
    assert r.status_code == 200, r.text
    return r.json()


def _self_onboard(sess, token, company_code):
    body = {
        "name": "TEST User",
        "father_name": "F",
        "dob": "1990-01-01",
        "doj": "2024-01-01",
        "shift_start": "09:00",
        "shift_end": "18:00",
        "salary_monthly": 50000,
        "half_day_hrs": 4,
        "full_day_hrs": 8,
        "company_code": company_code,
    }
    return sess.post(f"{BASE}/api/onboarding",
                     json=body,
                     headers={"Authorization": f"Bearer {token}"})


# ---------------- Onboarding sets pending ----------------
class TestOnboardingSetsPending:
    def test_onboarding_returns_pending_status(self, test_company):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        email = _fresh_email("emp")
        token, _ = _otp_login(s, email)

        r = _self_onboard(s, token, test_company["company_code"])
        assert r.status_code == 200, r.text
        j = r.json()
        user = j["user"]
        assert user["approval_status"] == "pending"
        assert isinstance(user.get("approval_requested_at"), str) and len(user["approval_requested_at"]) > 0
        assert user["onboarded"] is True
        assert user["company_id"] == test_company["company_id"]

    def test_me_flags_approval_pending_true(self, test_company):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        email = _fresh_email("emp")
        token, _ = _otp_login(s, email)
        r = _self_onboard(s, token, test_company["company_code"])
        assert r.status_code == 200
        me = _me(s, token)
        assert me["approval_pending"] is True
        assert me["approval_rejected"] is False
        assert me["approval_status"] == "pending"
        # company_name should be enriched
        assert me.get("company_name") == test_company["name"]


# ---------------- Legacy user enrichment ----------------
class TestLegacyEnrichment:
    def test_super_admin_not_flagged_pending(self, super_admin):
        # Super admin exists prior to approval field — should be approved
        me = _me(super_admin["session"], super_admin["token"])
        assert me.get("approval_pending") is False
        assert me.get("approval_rejected") is False
        # Legacy accounts should default to approved
        assert me.get("approval_status") == "approved"

    def test_fresh_employee_without_onboarding_not_pending(self):
        # Fresh OTP-only user with no onboarding: role=employee, no company_id
        # approval_pending must be False (requires company_id)
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        token, _ = _otp_login(s, _fresh_email("nooarding"))
        me = _me(s, token)
        assert me.get("approval_pending") is False


# ---------------- Pending approvals list ----------------
class TestPendingApprovalsList:
    def test_unauth_401(self):
        r = requests.get(f"{BASE}/api/admin/pending-approvals")
        assert r.status_code == 401

    def test_employee_forbidden(self, test_company):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        token, _ = _otp_login(s, _fresh_email("emp"))
        r = s.get(f"{BASE}/api/admin/pending-approvals",
                  headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_super_admin_sees_pending(self, super_admin, test_company):
        # Create a pending employee under this company
        s2 = requests.Session()
        s2.headers.update({"Content-Type": "application/json"})
        email = _fresh_email("plist")
        etok, _ = _otp_login(s2, email)
        r = _self_onboard(s2, etok, test_company["company_code"])
        assert r.status_code == 200
        emp_user_id = r.json()["user"]["user_id"]

        # super admin lists — should contain this user with company_name populated
        lr = super_admin["session"].get(
            f"{BASE}/api/admin/pending-approvals",
            headers={"Authorization": f"Bearer {super_admin['token']}"},
        )
        assert lr.status_code == 200, lr.text
        rows = lr.json().get("pending", [])
        ids = [u["user_id"] for u in rows]
        assert emp_user_id in ids, f"Pending user not returned. Rows: {rows}"
        me_row = next(u for u in rows if u["user_id"] == emp_user_id)
        assert me_row.get("approval_status") == "pending"
        assert me_row.get("company_name") == test_company["name"]

    def test_super_admin_scoped_by_company_id(self, super_admin, test_company):
        r = super_admin["session"].get(
            f"{BASE}/api/admin/pending-approvals?company_id={test_company['company_id']}",
            headers={"Authorization": f"Bearer {super_admin['token']}"},
        )
        assert r.status_code == 200
        for u in r.json().get("pending", []):
            assert u["company_id"] == test_company["company_id"]


# ---------------- Approve / Reject ----------------
class TestApproveReject:
    def test_approve_unlocks_user(self, super_admin, test_company):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        etok, _ = _otp_login(s, _fresh_email("appr"))
        r = _self_onboard(s, etok, test_company["company_code"])
        emp_uid = r.json()["user"]["user_id"]

        # Approve
        dec = super_admin["session"].patch(
            f"{BASE}/api/admin/approve-employee",
            json={"user_id": emp_uid, "action": "approve", "note": "welcome"},
            headers={"Authorization": f"Bearer {super_admin['token']}"},
        )
        assert dec.status_code == 200, dec.text
        assert dec.json()["approval_status"] == "approved"
        assert dec.json()["approved_by"] == super_admin["user"]["user_id"]
        assert dec.json().get("approved_at")

        me = _me(s, etok)
        assert me["approval_pending"] is False
        assert me["approval_rejected"] is False
        assert me["approval_status"] == "approved"
        # Company link retained
        assert me["company_id"] == test_company["company_id"]

    def test_reject_clears_company_and_onboarded(self, super_admin, test_company):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        etok, _ = _otp_login(s, _fresh_email("rej"))
        r = _self_onboard(s, etok, test_company["company_code"])
        emp_uid = r.json()["user"]["user_id"]

        dec = super_admin["session"].patch(
            f"{BASE}/api/admin/approve-employee",
            json={"user_id": emp_uid, "action": "reject", "note": "not a fit"},
            headers={"Authorization": f"Bearer {super_admin['token']}"},
        )
        assert dec.status_code == 200, dec.text
        body = dec.json()
        assert body["approval_status"] == "rejected"
        assert body.get("company_id") is None
        assert body.get("onboarded") is False
        assert body.get("approval_note") == "not a fit"

        me = _me(s, etok)
        assert me["approval_rejected"] is True
        assert me["approval_pending"] is False
        assert me.get("company_id") is None
        assert me.get("onboarded") is False

    def test_invalid_action_400(self, super_admin, test_company):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        etok, _ = _otp_login(s, _fresh_email("badact"))
        r = _self_onboard(s, etok, test_company["company_code"])
        emp_uid = r.json()["user"]["user_id"]

        dec = super_admin["session"].patch(
            f"{BASE}/api/admin/approve-employee",
            json={"user_id": emp_uid, "action": "maybe"},
            headers={"Authorization": f"Bearer {super_admin['token']}"},
        )
        assert dec.status_code == 400

    def test_company_admin_cross_company_forbidden(self, super_admin):
        """company_admin cannot approve users of a different company."""
        s_admin = super_admin["session"]
        atok = super_admin["token"]

        # Create two companies
        def _mk_co(name):
            r = s_admin.post(f"{BASE}/api/companies",
                             json={"name": name, "office_lat": 1.0, "office_lng": 1.0},
                             headers={"Authorization": f"Bearer {atok}"})
            assert r.status_code == 200, r.text
            return r.json()

        co_a = _mk_co(f"TEST_A_{uuid.uuid4().hex[:5]}")
        co_b = _mk_co(f"TEST_B_{uuid.uuid4().hex[:5]}")

        # Create company_admin for co_a
        ca_sess = requests.Session()
        ca_sess.headers.update({"Content-Type": "application/json"})
        ca_email = _fresh_email("ca")
        ca_token, ca_user = _otp_login(ca_sess, ca_email)
        # Promote to company_admin of co_a via super_admin
        pr = s_admin.patch(f"{BASE}/api/admin/user-role",
                           json={"user_id": ca_user["user_id"],
                                 "role": "company_admin",
                                 "company_id": co_a["company_id"]},
                           headers={"Authorization": f"Bearer {atok}"})
        assert pr.status_code == 200, pr.text

        # Employee onboards to co_b
        emp_sess = requests.Session()
        emp_sess.headers.update({"Content-Type": "application/json"})
        etok, _ = _otp_login(emp_sess, _fresh_email("cross"))
        r = _self_onboard(emp_sess, etok, co_b["company_code"])
        emp_uid = r.json()["user"]["user_id"]

        # company_admin for A tries to approve employee in B → 403
        dec = ca_sess.patch(f"{BASE}/api/admin/approve-employee",
                            json={"user_id": emp_uid, "action": "approve"},
                            headers={"Authorization": f"Bearer {ca_token}"})
        assert dec.status_code == 403

        # Also verify company_admin listing is scoped to own company only (no cross-company row leak)
        lr = ca_sess.get(f"{BASE}/api/admin/pending-approvals",
                         headers={"Authorization": f"Bearer {ca_token}"})
        assert lr.status_code == 200
        for u in lr.json().get("pending", []):
            assert u["company_id"] == co_a["company_id"]
            assert u["user_id"] != emp_uid


# ---------------- user-role auto-approves ----------------
class TestUserRoleAutoApprove:
    def test_super_admin_assign_company_auto_approves(self, super_admin, test_company):
        # Fresh employee w/o onboarding
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        etok, euser = _otp_login(s, _fresh_email("assign"))

        r = super_admin["session"].patch(
            f"{BASE}/api/admin/user-role",
            json={"user_id": euser["user_id"], "company_id": test_company["company_id"]},
            headers={"Authorization": f"Bearer {super_admin['token']}"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["company_id"] == test_company["company_id"]
        assert body["approval_status"] == "approved"
        assert body["onboarded"] is True

        me = _me(s, etok)
        assert me["approval_pending"] is False
        assert me["approval_rejected"] is False


# ---------------- Regression: /admin/employees still works ----------------
class TestRegressionEmployees:
    def test_super_admin_can_list_employees(self, super_admin):
        r = super_admin["session"].get(
            f"{BASE}/api/admin/employees",
            headers={"Authorization": f"Bearer {super_admin['token']}"},
        )
        assert r.status_code == 200
        data = r.json()
        # Expect either a list or {employees: [...]}
        rows = data if isinstance(data, list) else data.get("employees", [])
        assert isinstance(rows, list)
