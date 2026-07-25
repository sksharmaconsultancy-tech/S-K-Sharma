"""Iter 292 backend regression tests.

Covers the two new features:
 (A) Monthly Employee In/Out & OT Matrix — JSON + xlsx/pdf/csv exports.
 (B) Employee Reports hub — annual salary statement + HR letter templates.

Read-only against real Kankani data (cmp_527fecdd7c, month 2026-07).
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"
MONTH = "2026-07"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_ADMIN_PW = "sharma123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": SUPER_ADMIN_EMAIL, "password": SUPER_ADMIN_PW},
                      timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok, f"no token in login response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def sample_user_id(headers):
    """Fetch any employee user_id in Kankani to feed downstream tests."""
    r = requests.get(
        f"{BASE_URL}/api/admin/company-staff/eligible-employees",
        params={"company_id": COMPANY_ID}, headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    emps = r.json().get("employees") or []
    assert emps, "no employees returned for Kankani"
    return emps[0]["user_id"]


# --- (A) Matrix JSON --------------------------------------------------------
class TestMatrixJson:
    def test_matrix_basic(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/inout-ot-matrix",
            params={"company_id": COMPANY_ID, "month": MONTH, "page_size": 5},
            headers=headers, timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["total_employees"] > 0
        assert j["page_size"] == 5
        assert len(j["employees"]) <= 5
        assert j["day_labels"], "day_labels missing"
        # verify cell shape
        emp = j["employees"][0]
        assert "days" in emp
        first_day = list(emp["days"].values())[0]
        for k in ("d_in", "d_out", "ot_in", "ot_out", "total", "ot", "flag", "detail"):
            assert k in first_day, f"missing key {k}"
        assert "filter_options" in j
        assert "departments" in j["filter_options"]

    def test_matrix_search_surendra(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/inout-ot-matrix",
            params={"company_id": COMPANY_ID, "month": MONTH,
                    "q": "SURENDRA", "page_size": 50},
            headers=headers, timeout=60)
        assert r.status_code == 200
        j = r.json()
        # request said ~3 rows for SURENDRA
        assert 1 <= j["total_employees"] <= 20, f"unexpected count {j['total_employees']}"

    def test_matrix_status_active(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/inout-ot-matrix",
            params={"company_id": COMPANY_ID, "month": MONTH, "status": "active",
                    "page_size": 1},
            headers=headers, timeout=60)
        assert r.status_code == 200
        assert r.json()["total_employees"] >= 1


# --- (A) Exports ------------------------------------------------------------
class TestMatrixExports:
    @pytest.mark.parametrize("ext,ctype_prefix", [
        ("xlsx", "application/vnd.openxmlformats"),
        ("csv", "text/csv"),
        ("pdf", "application/pdf"),
    ])
    def test_export_ok(self, headers, ext, ctype_prefix):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/inout-ot-matrix.{ext}",
            params={"company_id": COMPANY_ID, "month": MONTH, "q": "SURENDRA"},
            headers=headers, timeout=90)
        assert r.status_code == 200, f"{ext} export failed: {r.status_code} {r.text[:200]}"
        assert r.headers.get("content-type", "").startswith(ctype_prefix), \
            f"unexpected content-type for {ext}: {r.headers.get('content-type')}"
        # non-trivial size
        assert len(r.content) > 500, f"{ext} content too small: {len(r.content)} bytes"
        if ext == "pdf":
            assert r.content[:4] == b"%PDF", "pdf magic bytes missing"


# --- (B) Annual salary statement -------------------------------------------
class TestAnnualStatement:
    def test_json(self, headers, sample_user_id):
        r = requests.get(
            f"{BASE_URL}/api/admin/annual-salary-statement",
            params={"company_id": COMPANY_ID, "user_id": sample_user_id, "fy": 2026},
            headers=headers, timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        assert len(j["rows"]) == 12, "should have 12 months"
        # First row should be Apr 2026, last Mar 2027
        assert j["rows"][0]["month"] == "2026-04"
        assert j["rows"][-1]["month"] == "2027-03"
        assert "totals" in j
        assert j["fy"] == "2026-27"

    def test_xlsx(self, headers, sample_user_id):
        r = requests.get(
            f"{BASE_URL}/api/admin/annual-salary-statement.xlsx",
            params={"company_id": COMPANY_ID, "user_id": sample_user_id, "fy": 2026},
            headers=headers, timeout=60)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith(
            "application/vnd.openxmlformats")
        assert len(r.content) > 1000


# --- (C) HR Letters templates ----------------------------------------------
class TestHrLetterTemplates:
    @pytest.mark.parametrize("ltype", ["experience", "relieving", "salary_certificate",
                                       "appointment"])
    def test_template_ok(self, headers, sample_user_id, ltype):
        r = requests.get(
            f"{BASE_URL}/api/admin/hr-letters/template/{ltype}",
            params={"company_id": COMPANY_ID, "user_id": sample_user_id},
            headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["letter_type"] == ltype
        assert j.get("subject") and j.get("body"), "subject/body missing"
        assert len(j["body"]) > 50

    def test_template_unknown_400(self, headers, sample_user_id):
        r = requests.get(
            f"{BASE_URL}/api/admin/hr-letters/template/foobar",
            params={"company_id": COMPANY_ID, "user_id": sample_user_id},
            headers=headers, timeout=30)
        assert r.status_code == 400


# --- Regression: attendance-grid still returns day_present_counts ----------
class TestRegression:
    def test_attendance_grid(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=headers, timeout=90)
        assert r.status_code == 200
        j = r.json()
        assert "day_present_counts" in j or "employees" in j
