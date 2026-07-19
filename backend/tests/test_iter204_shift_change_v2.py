"""Iter 204 — Employee Shift Change Management (v2) backend tests.

Covers: policy toggle -> employee config -> create request -> admin list ->
decide (approve/reject/send_back) -> employee cancel -> xlsx exports ->
reason_mandatory + duplicate + auto_approve edge cases.
"""
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PW = "sharma123"
EMP_LOGIN_ID = "TEST50"
EMP_PIN = "123456"
COMPANY_ID = "cmp_527fecdd7c"

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------- helpers
def _auth_admin() -> str:
    r = requests.post(f"{API}/auth/admin-password-login",
                      json={"email": SUPER_EMAIL, "password": SUPER_PW}, timeout=20)
    assert r.status_code == 200, f"admin login failed {r.status_code} {r.text[:200]}"
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok, r.text
    return tok


def _auth_emp() -> str:
    r = requests.post(f"{API}/auth/pin-login",
                      json={"login_id": EMP_LOGIN_ID, "pin": EMP_PIN}, timeout=20)
    assert r.status_code == 200, f"emp login failed {r.status_code} {r.text[:200]}"
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok, r.text
    return tok


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _auth_admin()


@pytest.fixture(scope="module")
def emp_token() -> str:
    return _auth_emp()


# ---------------------------------------------------------- 1) admin auth smoke
class TestAuth:
    def test_super_admin_login(self):
        r = requests.post(f"{API}/auth/admin-password-login",
                          json={"email": SUPER_EMAIL, "password": SUPER_PW}, timeout=20)
        assert r.status_code == 200
        assert (r.json().get("session_token") or r.json().get("token"))

    def test_employee_pin_login(self):
        r = requests.post(f"{API}/auth/pin-login",
                          json={"login_id": EMP_LOGIN_ID, "pin": EMP_PIN}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json().get("user", {}).get("role") == "employee"


# --------------------------------------------------- 2) enable shift_change cfg
class TestPolicyToggle:
    def test_enable_shift_change_in_policy(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        # Current GET
        r = requests.get(f"{API}/attendance/policy?company_id={COMPANY_ID}",
                         headers=h, timeout=15)
        assert r.status_code == 200, r.text
        cur = r.json().get("policy") or r.json()
        assert isinstance(cur, dict)

        payload = {
            "policy": {
                **{k: v for k, v in cur.items() if k not in ("punch_approval_required",)},
                "shift_change": {
                    "enabled": True,
                    "reason_mandatory": True,
                    "post_punch_allowed": False,
                    "auto_approve": False,
                    "instant_exception": True,
                    "time_window": "any",
                    "approval_levels": "single",
                },
            }
        }
        r = requests.patch(f"{API}/attendance/policy?company_id={COMPANY_ID}",
                           headers=h, json=payload, timeout=20)
        assert r.status_code == 200, f"patch failed {r.status_code} {r.text[:300]}"
        pol = r.json().get("policy") or {}
        sc = pol.get("shift_change") or {}
        assert sc.get("enabled") is True, f"shift_change not saved: {sc}"
        assert sc.get("reason_mandatory") is True
        assert sc.get("time_window") == "any"
        assert sc.get("approval_levels") == "single"


# ---------------------------------------------------- 3) employee config lookup
class TestEmployeeConfig:
    def test_get_config_enabled(self, emp_token):
        h = {"Authorization": f"Bearer {emp_token}"}
        r = requests.get(f"{API}/shift-change/config", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["config"]["enabled"] is True
        assert isinstance(data.get("shifts"), list) and len(data["shifts"]) > 0
        assert "current_shift" in data


# --------------------------------------- 4) reason_mandatory enforcement (400)
class TestReasonMandatory:
    def test_missing_reason_400(self, emp_token):
        h = {"Authorization": f"Bearer {emp_token}"}
        cfg = requests.get(f"{API}/shift-change/config", headers=h, timeout=15).json()
        shifts = cfg["shifts"]
        cur_id = (cfg.get("current_shift") or {}).get("shift_id")
        other = next((s for s in shifts if s["shift_id"] != cur_id), None)
        assert other, "need at least 2 shifts to test"
        today = datetime.now(IST).strftime("%Y-%m-%d")
        r = requests.post(f"{API}/shift-change/requests-v2", headers=h,
                          json={"date": today, "requested_shift_id": other["shift_id"],
                                "reason": ""}, timeout=15)
        assert r.status_code == 400
        assert "reason" in r.text.lower()


# ----------------------------------------- 5) full workflow: create -> approve
class TestFullWorkflow:
    created_id: str = ""
    request_no: str = ""
    date_str: str = ""
    other_shift_id: str = ""

    def test_create_request(self, emp_token):
        h = {"Authorization": f"Bearer {emp_token}"}
        cfg = requests.get(f"{API}/shift-change/config", headers=h, timeout=15).json()
        shifts = cfg["shifts"]
        cur_id = (cfg.get("current_shift") or {}).get("shift_id")
        other = next((s for s in shifts if s["shift_id"] != cur_id), None) or shifts[0]
        # Use a future date to avoid duplicates from prior test runs.
        date = (datetime.now(IST) + timedelta(days=5)).strftime("%Y-%m-%d")
        r = requests.post(f"{API}/shift-change/requests-v2", headers=h,
                          json={"date": date,
                                "requested_shift_id": other["shift_id"],
                                "reason": "TEST_iter204 automated"}, timeout=20)
        assert r.status_code == 200, f"create failed {r.status_code} {r.text[:300]}"
        req = r.json()["request"]
        assert req["status"] == "pending"
        assert req["request_no"].startswith("SCR-")
        TestFullWorkflow.created_id = req["request_id"]
        TestFullWorkflow.request_no = req["request_no"]
        TestFullWorkflow.date_str = date
        TestFullWorkflow.other_shift_id = other["shift_id"]

    def test_my_requests_shows_pending(self, emp_token):
        assert TestFullWorkflow.created_id
        h = {"Authorization": f"Bearer {emp_token}"}
        r = requests.get(f"{API}/shift-change/requests-v2/my", headers=h, timeout=15)
        assert r.status_code == 200
        rows = r.json()["rows"]
        match = next((x for x in rows if x["request_id"] == TestFullWorkflow.created_id), None)
        assert match, f"created request not in /my list; ids={[x['request_id'] for x in rows[:5]]}"
        assert match["status"] == "pending"

    def test_admin_lists_request(self, admin_token):
        assert TestFullWorkflow.created_id
        h = {"Authorization": f"Bearer {admin_token}"}
        r = requests.get(f"{API}/admin/shift-change/requests-v2",
                         params={"company_id": COMPANY_ID, "status": "pending"},
                         headers=h, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "counts" in data
        found = next((x for x in data["rows"] if x["request_id"] == TestFullWorkflow.created_id), None)
        assert found, "created request missing from admin list"

    def test_duplicate_blocked(self, emp_token):
        """Same date + status pending should reject."""
        assert TestFullWorkflow.created_id
        h = {"Authorization": f"Bearer {emp_token}"}
        r = requests.post(f"{API}/shift-change/requests-v2", headers=h,
                          json={"date": TestFullWorkflow.date_str,
                                "requested_shift_id": TestFullWorkflow.other_shift_id,
                                "reason": "dup"}, timeout=15)
        assert r.status_code == 400
        assert "already" in r.text.lower()

    def test_admin_approves_and_creates_daily_assignment(self, admin_token, emp_token):
        assert TestFullWorkflow.created_id
        h = {"Authorization": f"Bearer {admin_token}"}
        r = requests.post(f"{API}/admin/shift-change/requests-v2/decide",
                          headers=h,
                          json={"request_ids": [TestFullWorkflow.created_id],
                                "action": "approve", "remarks": "ok"}, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["processed"] == 1
        # Verify status flipped
        h2 = {"Authorization": f"Bearer {emp_token}"}
        rows = requests.get(f"{API}/shift-change/requests-v2/my",
                            headers=h2, timeout=15).json()["rows"]
        row = next(x for x in rows if x["request_id"] == TestFullWorkflow.created_id)
        assert row["status"] == "approved"
        assert row.get("approved_shift", {}).get("shift_id") == TestFullWorkflow.other_shift_id
        # History trail
        actions = [h.get("action") for h in row.get("history", [])]
        assert "submitted" in actions and "approved" in actions
        # Daily assignment via the report endpoint
        month = TestFullWorkflow.date_str[:7]
        rr = requests.get(f"{API}/admin/shift-change/daily-assignments",
                          params={"company_id": COMPANY_ID, "month": month, "fmt": "json"},
                          headers=h, timeout=15)
        assert rr.status_code == 200
        assigns = rr.json()["rows"]
        got = next((a for a in assigns if a.get("date") == TestFullWorkflow.date_str), None)
        assert got, "daily_shift_assignments not populated after approval"
        assert got.get("source") == "shift_change_request"


# ------------------------------------------- 6) reject + send_back + cancel
class TestOtherActions:
    def _create(self, emp_token, days_ahead):
        h = {"Authorization": f"Bearer {emp_token}"}
        cfg = requests.get(f"{API}/shift-change/config", headers=h, timeout=15).json()
        cur_id = (cfg.get("current_shift") or {}).get("shift_id")
        other = next((s for s in cfg["shifts"] if s["shift_id"] != cur_id), None) or cfg["shifts"][0]
        date = (datetime.now(IST) + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        r = requests.post(f"{API}/shift-change/requests-v2", headers=h,
                          json={"date": date, "requested_shift_id": other["shift_id"],
                                "reason": "TEST_iter204"}, timeout=15)
        assert r.status_code == 200, r.text
        return r.json()["request"]["request_id"]

    def test_reject(self, emp_token, admin_token):
        rid = self._create(emp_token, 10)
        r = requests.post(f"{API}/admin/shift-change/requests-v2/decide",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          json={"request_ids": [rid], "action": "reject",
                                "remarks": "not allowed"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["processed"] == 1
        rows = requests.get(f"{API}/shift-change/requests-v2/my",
                            headers={"Authorization": f"Bearer {emp_token}"},
                            timeout=15).json()["rows"]
        assert next(x for x in rows if x["request_id"] == rid)["status"] == "rejected"

    def test_send_back(self, emp_token, admin_token):
        rid = self._create(emp_token, 12)
        r = requests.post(f"{API}/admin/shift-change/requests-v2/decide",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          json={"request_ids": [rid], "action": "send_back",
                                "remarks": "add proof"}, timeout=15)
        assert r.status_code == 200
        rows = requests.get(f"{API}/shift-change/requests-v2/my",
                            headers={"Authorization": f"Bearer {emp_token}"},
                            timeout=15).json()["rows"]
        assert next(x for x in rows if x["request_id"] == rid)["status"] == "sent_back"

    def test_employee_cancel(self, emp_token):
        rid = self._create(emp_token, 15)
        r = requests.post(f"{API}/shift-change/requests-v2/{rid}/cancel",
                          headers={"Authorization": f"Bearer {emp_token}"}, timeout=15)
        assert r.status_code == 200
        rows = requests.get(f"{API}/shift-change/requests-v2/my",
                            headers={"Authorization": f"Bearer {emp_token}"},
                            timeout=15).json()["rows"]
        assert next(x for x in rows if x["request_id"] == rid)["status"] == "cancelled"


# ---------------------------------------------------------------- 7) xlsx reports
class TestXlsxReports:
    def test_register_xlsx(self, admin_token):
        month = datetime.now(IST).strftime("%Y-%m")
        r = requests.get(f"{API}/admin/shift-change/register",
                         params={"company_id": COMPANY_ID, "month": month, "fmt": "xlsx"},
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "spreadsheetml" in ct or "xlsx" in ct
        assert r.content[:2] == b"PK", "not a valid xlsx (missing PK header)"

    def test_daily_assignments_xlsx(self, admin_token):
        month = datetime.now(IST).strftime("%Y-%m")
        # Also probe next month, since approvals may be for future dates
        for m in {month, (datetime.now(IST) + timedelta(days=30)).strftime("%Y-%m")}:
            r = requests.get(f"{API}/admin/shift-change/daily-assignments",
                             params={"company_id": COMPANY_ID, "month": m, "fmt": "xlsx"},
                             headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)
            assert r.status_code == 200
            assert r.content[:2] == b"PK"


# ------------------------------------------------------- 8) auth-gated 401 smoke
class TestUnauthorized:
    def test_config_requires_auth(self):
        r = requests.get(f"{API}/shift-change/config", timeout=10)
        assert r.status_code in (401, 403)

    def test_admin_list_requires_auth(self):
        r = requests.get(f"{API}/admin/shift-change/requests-v2", timeout=10)
        assert r.status_code in (401, 403)
