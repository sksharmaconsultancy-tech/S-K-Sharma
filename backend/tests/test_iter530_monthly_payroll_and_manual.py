"""Iter 528-530 backend regression:
- Monthly Payroll Report (JSON/xlsx/pdf) + filters + bank masking + status_note
- User Manual PDF (super_admin only)
"""
import os
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL",
                      "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY = "cmp_527fecdd7c"


@pytest.fixture(scope="module")
def sa_token():
    r = requests.post(f"{BASE}/api/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com",
                            "password": "sharma123"}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def sa_headers(sa_token):
    return {"Authorization": f"Bearer {sa_token}"}


@pytest.fixture(scope="module")
def sub_admin_token():
    """Try to log a non-super-admin (sub_admin) in via password."""
    r = requests.post(f"{BASE}/api/auth/admin-password-login",
                      json={"email": "testsub@sksharma.co",
                            "password": "testsub123"}, timeout=30)
    if r.status_code == 200:
        return r.json().get("session_token")
    return None


# --- Monthly Payroll Report ------------------------------------------------
class TestMonthlyPayrollJSON:
    def test_compliance_basis_2026_07(self, sa_headers):
        r = requests.get(f"{BASE}/api/admin/reports/monthly-payroll",
                         params={"company_id": COMPANY, "month": "2026-07",
                                 "salary_type": "both", "basis": "compliance"},
                         headers=sa_headers, timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["month"] == "2026-07"
        assert d["basis"] == "compliance"
        assert len(d["rows"]) >= 100, f"expected ~127 rows got {len(d['rows'])}"
        assert len(d["columns"]) >= 60, f"expected >=60 cols got {len(d['columns'])}"
        keys = {c["key"] for c in d["columns"]}
        assert {"d1", "d15", "d31"}.issubset(keys)
        assert {"pf", "esic", "pt", "lwf", "tds", "advance", "other_ded",
                "total_ded", "net", "final_salary"}.issubset(keys)
        assert d["totals"].get("name") == "TOTAL"
        meta = d["meta"]
        for k in ("departments", "designations", "employee_types",
                  "contractors", "branches"):
            assert k in meta

    def test_actual_basis(self, sa_headers):
        r = requests.get(f"{BASE}/api/admin/reports/monthly-payroll",
                         params={"company_id": COMPANY, "month": "2026-07",
                                 "basis": "actual"},
                         headers=sa_headers, timeout=90)
        assert r.status_code == 200
        assert r.json()["basis"] == "actual"

    def test_status_note_for_uncalculated_month(self, sa_headers):
        # 2026-05 has no attendance/salary run — must show status_note
        r = requests.get(f"{BASE}/api/admin/reports/monthly-payroll",
                         params={"company_id": COMPANY, "month": "2026-05",
                                 "basis": "compliance"},
                         headers=sa_headers, timeout=90)
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert rows, "expected rows even without salary"
        # every row should have status_note; final_salary/net must be null
        notes = {r_.get("status_note") for r_ in rows}
        assert notes & {"Attendance Pending", "Salary Not Calculated"}, notes
        for r_ in rows:
            if r_.get("status_note"):
                assert r_.get("final_salary") is None, r_
                assert r_.get("net") is None, r_

    def test_filter_narrows_rows(self, sa_headers):
        full = requests.get(f"{BASE}/api/admin/reports/monthly-payroll",
                            params={"company_id": COMPANY, "month": "2026-07"},
                            headers=sa_headers, timeout=90).json()
        types = full["meta"]["employee_types"]
        if not types:
            pytest.skip("no employee_types in meta")
        r = requests.get(f"{BASE}/api/admin/reports/monthly-payroll",
                         params={"company_id": COMPANY, "month": "2026-07",
                                 "employee_type": types[0]},
                         headers=sa_headers, timeout=90)
        assert r.status_code == 200
        assert 0 < len(r.json()["rows"]) <= len(full["rows"])

    def test_search_filter(self, sa_headers):
        r = requests.get(f"{BASE}/api/admin/reports/monthly-payroll",
                         params={"company_id": COMPANY, "month": "2026-07",
                                 "search": "SURENDRA"},
                         headers=sa_headers, timeout=90)
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert len(rows) >= 1
        assert any("SURENDRA" in (row.get("name") or "").upper()
                   for row in rows)


class TestMonthlyPayrollExports:
    def test_xlsx(self, sa_headers):
        r = requests.get(f"{BASE}/api/admin/reports/monthly-payroll.xlsx",
                         params={"company_id": COMPANY, "month": "2026-07"},
                         headers=sa_headers, timeout=180)
        assert r.status_code == 200
        assert "spreadsheet" in r.headers.get("content-type", "").lower()
        assert r.content[:2] == b"PK"
        assert len(r.content) > 5000

    def test_pdf(self, sa_headers):
        r = requests.get(f"{BASE}/api/admin/reports/monthly-payroll.pdf",
                         params={"company_id": COMPANY, "month": "2026-07"},
                         headers=sa_headers, timeout=180)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 5000


class TestBankMasking:
    def test_super_admin_unmasked_or_no_account(self, sa_headers):
        r = requests.get(f"{BASE}/api/admin/reports/monthly-payroll",
                         params={"company_id": COMPANY, "month": "2026-07"},
                         headers=sa_headers, timeout=90)
        assert r.status_code == 200
        rows = r.json()["rows"]
        with_acct = [r_ for r_ in rows if r_.get("acct_no")]
        for r_ in with_acct:
            # super_admin: not masked
            assert not str(r_["acct_no"]).startswith("XXXXXX"), r_["acct_no"]

    def test_sub_admin_masked(self, sub_admin_token):
        if not sub_admin_token:
            pytest.skip("sub_admin login not available")
        h = {"Authorization": f"Bearer {sub_admin_token}"}
        r = requests.get(f"{BASE}/api/admin/reports/monthly-payroll",
                         params={"company_id": COMPANY, "month": "2026-07"},
                         headers=h, timeout=90)
        assert r.status_code == 200
        rows = r.json()["rows"]
        with_acct = [r_ for r_ in rows if r_.get("acct_no")]
        if not with_acct:
            pytest.skip("no bank accounts in dataset")
        for r_ in with_acct:
            assert str(r_["acct_no"]).startswith("XXXXXX"), r_["acct_no"]


# --- User Manual PDF -------------------------------------------------------
class TestUserManual:
    def test_super_admin_ok(self, sa_headers):
        r = requests.get(f"{BASE}/api/admin/user-manual.pdf",
                         headers=sa_headers, timeout=120)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"
        # Expected large PDF (~22 pages). Assert >200KB.
        assert len(r.content) > 200_000, f"pdf too small {len(r.content)}"

    def test_no_auth_401(self):
        r = requests.get(f"{BASE}/api/admin/user-manual.pdf", timeout=30)
        assert r.status_code in (401, 403), r.status_code

    def test_sub_admin_403(self, sub_admin_token):
        if not sub_admin_token:
            pytest.skip("sub_admin login not available")
        h = {"Authorization": f"Bearer {sub_admin_token}"}
        r = requests.get(f"{BASE}/api/admin/user-manual.pdf",
                         headers=h, timeout=60)
        assert r.status_code == 403, r.status_code
