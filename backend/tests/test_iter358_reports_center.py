"""Iter 358 — Reports Center backend tests.

Tests focus on VALUE CORRECTNESS (all endpoints already smoke-return 200):
  · payroll-reports: gross-vs-net, ctc-register, salary-comparison, ot-cost-analysis
  · govt-registers: wage-register totals, gratuity-register eligibility rule
  · audit-reports: user-activity _source column, RBAC (company_admin -> 403)
  · exports: increment.xlsx + deduction-register.pdf return correct binary
  · labour-stats: salary-distribution + tenure-analysis bucket shape
  · factory: leave-with-wages register (rows or empty gracefully)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"
MONTH = "2026-07"
FY = 2026


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login", json={
        "email": "sksharmaconsultancy@gmail.com",
        "password": "sharma123",
    }, timeout=30)
    assert r.status_code == 200, f"super login failed: {r.status_code} {r.text}"
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def super_headers(super_token):
    return {"Authorization": f"Bearer {super_token}"}


@pytest.fixture(scope="module")
def company_admin_token():
    # attempt to fetch a company_admin session; if not available,
    # tests using it will be skipped
    for pw in ("Kankani@123",):
        r = requests.post(f"{BASE_URL}/api/auth/admin-password-login", json={
            "email": "admin@kankani.local", "password": pw}, timeout=30)
        if r.status_code == 200:
            return r.json()["session_token"]
    pytest.skip("company_admin password login not available")


# ---------- PAYROLL REPORTS ----------
class TestPayrollReports:
    def test_gross_vs_net_row_consistency(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payroll-reports/gross-vs-net",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert j.get("rows"), "no rows returned"
        # every row: net ≈ gross - deductions (±1 rupee tolerance)
        bad = []
        for row in j["rows"]:
            g = float(row.get("gross") or 0)
            d = float(row.get("deductions") or 0)
            n = float(row.get("net") or 0)
            if abs((g - d) - n) > 1.0:
                bad.append((row.get("employee_code"), g, d, n))
        assert not bad, f"net != gross-deductions for {bad[:5]}"
        # totals row present
        t = j.get("totals")
        assert t and t.get("name") == "TOTAL"
        assert isinstance(t.get("gross"), (int, float))

    def test_ctc_register_formula(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payroll-reports/ctc-register",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert j.get("rows"), "no rows"
        for row in j["rows"][:20]:
            g = float(row.get("gross") or 0)
            pf = float(row.get("employer_pf") or 0)
            es = float(row.get("employer_esic") or 0)
            mctc = float(row.get("monthly_ctc") or 0)
            assert abs((g + pf + es) - mctc) < 0.5, (
                f"CTC formula wrong for {row.get('employee_code')}")

    def test_salary_comparison_diff(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payroll-reports/salary-comparison",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        # subtitle should mention prev month 2026-06
        assert "2026-06" in (j.get("subtitle") or "")
        for row in j.get("rows", [])[:20]:
            ga = float(row.get("gross_a") or 0)
            gb = float(row.get("gross_b") or 0)
            diff = float(row.get("gross_diff") or 0)
            assert abs((gb - ga) - diff) < 0.5

    def test_ot_cost_analysis_months(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payroll-reports/ot-cost-analysis",
            params={"company_id": COMPANY_ID, "fy_start_year": FY},
            headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        months = [row["month"] for row in j.get("rows", [])]
        # expected 2026-04..07 (4 monthly runs available)
        expected = ["2026-04", "2026-05", "2026-06", "2026-07"]
        for m in expected:
            assert m in months, f"missing month {m} in ot-cost-analysis"

    def test_list_returns_all_reports(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payroll-reports/list",
            headers=super_headers, timeout=30)
        assert r.status_code == 200
        kinds = [x["kind"] for x in r.json().get("reports", [])]
        for k in ("salary-comparison", "gross-vs-net", "ctc-register",
                  "ctc-analysis", "increment", "ex-gratia", "incentive",
                  "arrear", "full-and-final", "salary-revision",
                  "ot-department", "ot-daily", "ot-cost-analysis"):
            assert k in kinds, f"missing report {k}"


# ---------- GOVT REGISTERS ----------
class TestGovtRegisters:
    def test_wage_register_totals(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/govt-registers/wage-register",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        rows = j.get("rows") or []
        assert rows, "no wage-register rows"
        t = j.get("totals") or {}
        net_sum = round(sum(float(x.get("net") or 0) for x in rows), 2)
        assert abs(float(t.get("net") or 0) - net_sum) < 1.0, (
            f"totals.net {t.get('net')} != sum(rows.net) {net_sum}")

    def test_gratuity_register_eligibility(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/govt-registers/gratuity-register",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        for row in j.get("rows", []):
            yrs = float(row.get("service_years") or 0)
            elig = row.get("eligible")
            if yrs >= 5:
                assert elig == "Yes", (
                    f"emp {row.get('employee_code')} yrs={yrs} elig={elig}")
            else:
                assert elig == "No", (
                    f"emp {row.get('employee_code')} yrs={yrs} elig={elig}")


# ---------- AUDIT REPORTS ----------
class TestAuditReports:
    def test_user_activity_has_source(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/audit-reports/user-activity",
            params={"limit": 20}, headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        cols = [c["key"] for c in j.get("columns", [])]
        assert "_source" in cols, "audit report missing _source column"

    def test_audit_rejects_company_admin(self, company_admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/audit-reports/user-activity",
            params={"limit": 5},
            headers={"Authorization": f"Bearer {company_admin_token}"},
            timeout=30)
        assert r.status_code == 403, (
            f"company_admin should be blocked, got {r.status_code}")

    def test_audit_allows_super_admin_list(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/audit-reports/list",
            headers=super_headers, timeout=30)
        assert r.status_code == 200
        kinds = [x["kind"] for x in r.json().get("reports", [])]
        for k in ("payroll-audit", "attendance-audit",
                  "salary-change-history", "user-activity",
                  "login-history", "data-modification", "approval-history"):
            assert k in kinds


# ---------- EXPORTS ----------
class TestExports:
    def test_increment_xlsx_binary(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payroll-reports/increment.xlsx",
            params={"company_id": COMPANY_ID, "fy_start_year": FY},
            headers=super_headers, timeout=60)
        assert r.status_code == 200
        assert r.content[:2] == b"PK", (
            "not a valid xlsx (missing PK zip header)")
        assert "spreadsheetml" in r.headers.get("content-type", "")
        assert len(r.content) > 2000, f"xlsx too small: {len(r.content)}"

    def test_deduction_register_pdf_binary(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/govt-registers/deduction-register.pdf",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=super_headers, timeout=60)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF", "not a valid PDF"
        assert "pdf" in r.headers.get("content-type", "")
        assert len(r.content) > 2000, f"pdf too small: {len(r.content)}"


# ---------- LABOUR STATS ----------
class TestLabourStats:
    def test_salary_distribution(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/labour-stats/salary-distribution",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        rows = j.get("rows") or []
        assert rows, "salary-distribution empty"
        for row in rows:
            assert "share_pct" in row, f"missing share_pct: {row}"

    def test_tenure_analysis(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/labour-stats/tenure-analysis",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        rows = j.get("rows") or []
        assert rows, "tenure-analysis empty"
        for row in rows:
            assert "share_pct" in row, f"missing share_pct: {row}"


# ---------- FACTORY REGISTER ----------
class TestFactoryLeaveWithWages:
    def test_leave_with_wages(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/factory/register/leave-with-wages",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        # rows or empty gracefully — must have list shape
        assert isinstance(j.get("rows"), list)
        assert "columns" in j
