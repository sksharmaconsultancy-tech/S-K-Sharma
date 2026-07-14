"""Backend tests for Iter 114 features:
  - GET /api/admin/employee-report
  - GET /api/admin/employee-report/export.xlsx
  - GET /api/admin/employee-report/export.pdf
  - GET /api/admin/users-log (regression on July 2026 window)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
KANKANI_COMPANY_ID = "cmp_527fecdd7c"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    j = r.json()
    tok = j.get("session_token") or j.get("token")
    assert tok, f"no session_token in {j}"
    return tok


@pytest.fixture(scope="module")
def sample_employee_id(admin_token):
    r = requests.get(
        f"{BASE_URL}/api/admin/employees",
        params={"company_id": KANKANI_COMPANY_ID, "limit": 5},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    rows = data if isinstance(data, list) else (data.get("employees") or data.get("items") or [])
    assert rows, "no employees for Kankani"
    return rows[0].get("user_id") or rows[0].get("id")


# --- employee-report JSON -----------------------------------------------
class TestEmployeeReport:
    def test_report_json_ok(self, admin_token, sample_employee_id):
        r = requests.get(
            f"{BASE_URL}/api/admin/employee-report",
            params={"user_id": sample_employee_id, "from_date": "2026-04-01", "to_date": "2026-07-31"},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:400]
        j = r.json()
        # Sections present
        for key in ("employee", "period", "attendance", "leaves", "salary_rows", "compliance_rows", "documents", "tickets"):
            assert key in j, f"missing key {key}"
        emp = j["employee"]
        assert emp.get("user_id") == sample_employee_id
        assert emp.get("company_id") == KANKANI_COMPANY_ID
        assert "name" in emp
        # Attendance shape
        assert "days" in j["attendance"] and "summary" in j["attendance"]
        s = j["attendance"]["summary"]
        for k in ("present_days", "total_punches", "total_hours", "avg_hours"):
            assert k in s
        # Period echoed
        assert j["period"]["from_date"] == "2026-04-01"
        assert j["period"]["to_date"] == "2026-07-31"

    def test_report_missing_dates_returns_400(self, admin_token, sample_employee_id):
        r = requests.get(
            f"{BASE_URL}/api/admin/employee-report",
            params={"user_id": sample_employee_id},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text[:200]}"

    def test_report_unknown_user_returns_404(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/employee-report",
            params={"user_id": "user_doesnotexist_zzz", "from_date": "2026-04-01", "to_date": "2026-07-31"},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 404, f"expected 404 got {r.status_code} {r.text[:200]}"

    def test_report_no_auth_returns_401(self, sample_employee_id):
        r = requests.get(
            f"{BASE_URL}/api/admin/employee-report",
            params={"user_id": sample_employee_id, "from_date": "2026-04-01", "to_date": "2026-07-31"},
            timeout=30,
        )
        assert r.status_code == 401, f"expected 401 got {r.status_code} {r.text[:200]}"


# --- exports -------------------------------------------------------------
class TestEmployeeReportExports:
    def test_xlsx_export(self, admin_token, sample_employee_id):
        r = requests.get(
            f"{BASE_URL}/api/admin/employee-report/export.xlsx",
            params={"user_id": sample_employee_id, "from_date": "2026-04-01", "to_date": "2026-07-31"},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:300]
        assert r.content[:2] == b"PK", "not a valid XLSX (missing PK magic)"
        assert len(r.content) > 1000, f"xlsx too small: {len(r.content)}"
        ct = r.headers.get("content-type", "")
        assert "spreadsheet" in ct or "octet-stream" in ct or "excel" in ct.lower()

    def test_pdf_export(self, admin_token, sample_employee_id):
        r = requests.get(
            f"{BASE_URL}/api/admin/employee-report/export.pdf",
            params={"user_id": sample_employee_id, "from_date": "2026-04-01", "to_date": "2026-07-31"},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:300]
        assert r.content[:4] == b"%PDF", "not a valid PDF (missing %PDF magic)"
        assert len(r.content) > 1000, f"pdf too small: {len(r.content)}"


# --- users-log regression (Sub Admin Performance data source) -----------
class TestUsersLog:
    def test_users_log_july_window(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/users-log",
            params={"from_date": "2026-06-01", "to_date": "2026-07-31"},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:300]
        j = r.json()
        # Accept several shapes: {"events":[...]}, {"items":[...]}, or plain list
        events = j.get("events") if isinstance(j, dict) else j
        if events is None and isinstance(j, dict):
            events = j.get("items") or j.get("rows") or []
        assert isinstance(events, list), f"unexpected shape: {type(events)}"
        # Data exists per problem statement — must have >=1 event
        assert len(events) >= 1, f"expected some events in June-Jul 2026 window, got 0. keys={list(j) if isinstance(j, dict) else 'list'}"
