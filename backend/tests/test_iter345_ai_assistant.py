"""Iter 345 — AI Assistant v2 command routing + download endpoints tests."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
                      timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text[:200]}"
    d = r.json()
    tok = d.get("session_token") or d.get("token")
    assert tok, f"no token in {d}"
    return tok


@pytest.fixture(scope="module")
def hdrs(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _cmd(hdrs, text, retries=1):
    """Send a command with a generous timeout (LLM 5-20s)."""
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.post(
                f"{BASE_URL}/api/admin/ai-assistant/command",
                json={"text": text, "company_id": COMPANY_ID},
                headers=hdrs, timeout=90)
            if r.status_code == 200:
                return r.json()
            last = r
        except requests.RequestException as e:
            last = e
        time.sleep(2)
    if isinstance(last, requests.Response):
        pytest.fail(f"cmd '{text}' -> {last.status_code} {last.text[:200]}")
    pytest.fail(f"cmd '{text}' -> exception {last}")


# -- Intent routing tests -----------------------------------------------------

class TestAiCommandIntents:

    def test_1_data_query_salary_total(self, hdrs):
        j = _cmd(hdrs, "Total net salary in June?")
        assert j["intent"] == "data_query", j
        # Reply should include Compliance or Actual breakdown, no action needed
        assert any(kw in j["reply"] for kw in ["Compliance", "Actual", "salary", "Salary"]), j["reply"]

    def test_2_absent_list(self, hdrs):
        j = _cmd(hdrs, "Who is absent today?")
        assert j["intent"] == "data_query", j
        # Action should be navigate to attendance-grid
        act = j.get("action") or {}
        assert act.get("type") == "navigate", j
        assert "attendance" in (act.get("route") or ""), j

    def test_3_download_bank_sheet(self, hdrs):
        j = _cmd(hdrs, "Download bank sheet for June")
        assert j["intent"] == "report", j
        act = j.get("action") or {}
        assert act.get("type") == "download", j
        assert act.get("auto") is True
        assert "/admin/bank-sheet.xlsx" in (act.get("endpoint") or ""), j

    def test_4_process_compliance_salary(self, hdrs):
        j = _cmd(hdrs, "Process June compliance salary")
        assert j["intent"] == "process_salary", j
        act = j.get("action") or {}
        assert act.get("type") == "confirm_api", j
        assert act.get("method") == "POST"
        assert "compliance-salary-runs" in (act.get("endpoint") or ""), j

    def test_5_finalize_compliance_salary(self, hdrs):
        j = _cmd(hdrs, "Finalize June compliance salary")
        assert j["intent"] == "finalize_salary", j
        act = j.get("action") or {}
        # If already finalized action may be None — but usually confirm_api danger
        if act:
            assert act.get("type") == "confirm_api"
            assert act.get("danger") is True
            assert "/finalize" in (act.get("endpoint") or ""), j
            # run_id must be resolved
            assert "None" not in (act.get("endpoint") or "")

    def test_6_employee_update_resign(self, hdrs):
        j = _cmd(hdrs, "Mark employee 50 resigned")
        assert j["intent"] == "employee_update", j
        act = j.get("action") or {}
        assert act.get("type") == "confirm_api", j
        assert act.get("method") == "POST"
        assert "/admin/ai-assistant/employee-status" in (act.get("endpoint") or ""), j
        assert act.get("danger") is True

    def test_7_hinglish_salary_total(self, hdrs):
        j = _cmd(hdrs, "Kankani ka June salary kitna tha?")
        assert j["intent"] == "data_query", j
        # Should have breakdown of totals
        assert any(k in j["reply"] for k in ["Compliance", "Actual", "salary", "Salary"]), j

    def test_8_compliance_info_esic(self, hdrs):
        j = _cmd(hdrs, "What is the ESIC wage limit rule?")
        assert j["intent"] == "compliance_info", j
        act = j.get("action") or {}
        assert act.get("type") == "link", j
        url = (act.get("url") or "").lower()
        assert ("esic.gov.in" in url) or ("labour.gov.in" in url), act

    def test_9_employee_count(self, hdrs):
        j = _cmd(hdrs, "How many employees active and resigned?")
        assert j["intent"] == "data_query", j
        # Reply should list active/resigned numbers
        rep = j["reply"].lower()
        assert ("active" in rep and ("resigned" in rep or "exited" in rep)), j["reply"]

    def test_10_run_status(self, hdrs):
        j = _cmd(hdrs, "Is June salary finalized?")
        assert j["intent"] == "data_query", j
        rep = j["reply"].lower()
        assert ("finalized" in rep or "draft" in rep or "no salary run" in rep), j["reply"]


# -- Employee status executor -------------------------------------------------

class TestEmployeeStatusExecutor:

    @pytest.fixture(scope="class")
    def emp50(self, hdrs):
        r = requests.get(f"{BASE_URL}/api/admin/employees/list",
                         params={"company_id": COMPANY_ID, "q": "50"},
                         headers=hdrs, timeout=30)
        # try alternative endpoint if above shape mismatches
        if r.status_code != 200:
            r = requests.get(f"{BASE_URL}/api/admin/employees",
                             params={"company_id": COMPANY_ID}, headers=hdrs, timeout=30)
        assert r.status_code == 200, r.text[:200]
        rows = r.json()
        # find rows
        if isinstance(rows, dict):
            rows = rows.get("employees") or rows.get("rows") or rows.get("items") or []
        emp = next((e for e in rows if str(e.get("employee_code")) == "50"), None)
        assert emp, "employee code 50 not found"
        return emp

    def test_resign_then_reactivate(self, hdrs, emp50):
        uid = emp50.get("user_id")
        assert uid
        # Resign
        r = requests.post(f"{BASE_URL}/api/admin/ai-assistant/employee-status",
                          json={"user_id": uid, "status": "resigned"},
                          headers=hdrs, timeout=30)
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("status") == "resigned"
        # ALWAYS re-activate afterwards
        r2 = requests.post(f"{BASE_URL}/api/admin/ai-assistant/employee-status",
                           json={"user_id": uid, "status": "active"},
                           headers=hdrs, timeout=30)
        assert r2.status_code == 200, r2.text[:200]
        assert r2.json().get("status") == "active"


# -- Download endpoints -------------------------------------------------------

class TestDownloadEndpoints:

    def test_bank_sheet_xlsx(self, hdrs):
        r = requests.get(f"{BASE_URL}/api/admin/bank-sheet.xlsx",
                         params={"month": "2026-06", "company_id": COMPANY_ID},
                         headers=hdrs, timeout=60)
        assert r.status_code == 200, r.text[:200]
        ct = r.headers.get("content-type", "")
        assert "spreadsheet" in ct or "xlsx" in ct or "octet-stream" in ct, ct
        assert len(r.content) > 100

    def test_attendance_sheet_xlsx(self, hdrs):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance-sheet/{COMPANY_ID}/2026-06.xlsx",
            headers=hdrs, timeout=60)
        assert r.status_code == 200, r.text[:200]
        ct = r.headers.get("content-type", "")
        assert "spreadsheet" in ct or "xlsx" in ct or "octet-stream" in ct, ct
        assert len(r.content) > 100
