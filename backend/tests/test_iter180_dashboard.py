"""Iter 180 — Premium portal dashboard tests.

Verifies the new NEW fields introduced by /api/admin/portal-dashboard as well
as a light regression against iter 178 portal-phase 2 endpoints.
"""
import os
import pytest
import requests

BASE = "https://emplo-connect-1.preview.emergentagent.com"
SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PWD = "sharma123"
KANKANI_CID = "cmp_527fecdd7c"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE}/api/auth/admin-password-login",
                      json={"email": SUPER_EMAIL, "password": SUPER_PWD}, timeout=30)
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token")
    assert tok, r.text
    return tok


@pytest.fixture(scope="module")
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---- portal-dashboard new fields ----
class TestPortalDashboardPremium:
    def test_super_admin_all_firms(self, h):
        r = requests.get(f"{BASE}/api/admin/portal-dashboard", headers=h, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        # KPIs
        k = j["kpis"]
        for key in ("total_employees", "firms", "pending_tasks",
                    "pending_payroll_firms", "payroll_finalized_firms"):
            assert key in k, f"missing kpi {key}"
            assert isinstance(k[key], int)
        # Liabilities
        lb = j["liabilities"]
        for key in ("pf", "esic", "tds", "pt"):
            assert key in lb, f"missing liability {key}"
            assert isinstance(lb[key], (int, float))
        # Donut
        dn = j["compliance_donut"]
        for key in ("complied", "due_soon", "overdue", "pending", "total"):
            assert key in dn
        # arrays
        assert isinstance(j["clients_by_state"], list)
        assert isinstance(j["clients_by_industry"], list)
        eg = j["employee_growth"]
        assert isinstance(eg, list) and len(eg) == 6
        for row in eg:
            assert set(row.keys()) >= {"month", "employees"}
            assert isinstance(row["employees"], int)
        assert isinstance(j["payroll_processed_pct"], int)
        # legacy fields intact
        assert isinstance(j["attendance_trend"], list) and len(j["attendance_trend"]) == 14
        assert isinstance(j["payroll_trend"], list) and len(j["payroll_trend"]) == 6
        assert isinstance(j["compliance_calendar"], list)

    def test_company_scoped(self, h):
        r = requests.get(f"{BASE}/api/admin/portal-dashboard",
                         params={"company_id": KANKANI_CID}, headers=h, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        # For a single-firm scope the donut total must be 1 (only that firm)
        assert j["compliance_donut"]["total"] == 1
        assert j["kpis"]["firms"] == 1
        # State/industry buckets contain at most 1 firm
        assert sum(x["count"] for x in j["clients_by_state"]) == 1
        assert sum(x["count"] for x in j["clients_by_industry"]) == 1

    def test_auth_guard(self):
        r = requests.get(f"{BASE}/api/admin/portal-dashboard", timeout=30)
        assert r.status_code in (401, 403)


# ---- regression: iter 178 endpoints ----
class TestPortalPhase2Regression:
    def test_portal_tasks_list(self, h):
        r = requests.get(f"{BASE}/api/admin/portal-tasks", headers=h, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert isinstance(j.get("tasks"), list)

    def test_tracked_documents_list(self, h):
        r = requests.get(f"{BASE}/api/admin/tracked-documents", headers=h, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "documents" in j and "buckets" in j

    def test_client_health(self, h):
        r = requests.get(f"{BASE}/api/admin/portal-dashboard/client-health",
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert isinstance(j.get("clients"), list)

    def test_calendar(self, h):
        r = requests.get(f"{BASE}/api/admin/portal-dashboard/calendar",
                         params={"month": "2026-07"}, headers=h, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "events" in j

    def test_alerts(self, h):
        r = requests.get(f"{BASE}/api/admin/portal-dashboard/alerts",
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text

    def test_recurring_tasks(self, h):
        r = requests.get(f"{BASE}/api/admin/portal-recurring-tasks",
                         headers=h, timeout=30)
        # endpoint should not 500
        assert r.status_code in (200, 405), r.text

    def test_task_crud_roundtrip(self, h):
        # CREATE
        payload = {"title": "TEST_iter180 task", "due_date": "2026-08-15",
                   "priority": "medium", "kind": "task",
                   "company_id": KANKANI_CID}
        cr = requests.post(f"{BASE}/api/admin/portal-tasks", headers=h,
                           json=payload, timeout=30)
        assert cr.status_code in (200, 201), cr.text
        cj = cr.json()
        tid = (cj.get("task") or {}).get("task_id") or cj.get("id") or cj.get("task_id")
        assert tid, cr.text
        # DELETE
        dr = requests.delete(f"{BASE}/api/admin/portal-tasks/{tid}",
                             headers=h, timeout=30)
        assert dr.status_code in (200, 204), dr.text


# ---- pin login flow used by ESS ----
class TestEssPinLogin:
    def test_pin_login_test50(self):
        r = requests.post(f"{BASE}/api/auth/pin-login",
                          json={"login_id": "TEST50", "pin": "123456"}, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("session_token")
        assert (j.get("user") or {}).get("role") == "employee"
