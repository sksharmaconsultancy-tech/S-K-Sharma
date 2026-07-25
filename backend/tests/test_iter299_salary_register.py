"""Iter 299 — Enterprise Salary Register backend regression tests.

Covers:
  * /filters — months, runs, facets for both engines (compliance, actual)
  * /salary-register — dynamic columns/groups/rows/totals/pagination/sort/filter/search
  * exports (csv/xlsx/pdf) status + content-type + non-trivial size for both sources
  * error cases — 404 for a month with no run, 400 for invalid source, 401/403 for auth
  * company_admin scoping — company_id param ignored, only own firm's rows visible

Env: uses EXPO_PUBLIC_BACKEND_URL from /app/frontend/.env
Credentials: super admin (sksharmaconsultancy@gmail.com / sharma123)
Firm: Kankani cmp_527fecdd7c (compliance 2026-04,2026-05 ; actual 2026-03,2026-06,2026-07)
"""

import os
import pytest
import requests

BASE_URL = "https://emplo-connect-1.preview.emergentagent.com"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PASSWORD = "sharma123"

COMPANY_ID = "cmp_527fecdd7c"
COMPLIANCE_MONTH = "2026-05"
ACTUAL_MONTH = "2026-06"

# ---- Fixtures ----------------------------------------------------------------


@pytest.fixture(scope="module")
def super_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    tok = body.get("session_token") or body.get("token")
    assert tok, f"no token in {body}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(super_token):
    return {"Authorization": f"Bearer {super_token}"}


def _get(path, headers=None, params=None):
    return requests.get(f"{BASE_URL}{path}", headers=headers, params=params, timeout=60)


# ---- Auth -------------------------------------------------------------------


class TestAuth:
    def test_no_token_401_or_403(self):
        r = _get("/api/admin/salary-register/filters",
                params={"source": "compliance", "company_id": COMPANY_ID})
        assert r.status_code in (401, 403), r.status_code

    def test_bad_token_401(self):
        r = _get("/api/admin/salary-register",
                 headers={"Authorization": "Bearer garbage"},
                 params={"source": "compliance", "company_id": COMPANY_ID,
                         "month": COMPLIANCE_MONTH})
        assert r.status_code in (401, 403), r.status_code


# ---- /filters ---------------------------------------------------------------


class TestFilters:
    def test_compliance_filters_lists_months(self, auth_headers):
        r = _get("/api/admin/salary-register/filters", headers=auth_headers,
                 params={"source": "compliance", "company_id": COMPANY_ID,
                         "month": COMPLIANCE_MONTH})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        for k in ("months", "runs", "branches", "departments",
                  "employee_types", "contractors"):
            assert k in body, f"missing {k} in {list(body)}"
        assert isinstance(body["months"], list) and len(body["months"]) >= 1
        assert COMPLIANCE_MONTH in body["months"]
        # runs are populated for month
        assert isinstance(body["runs"], list) and len(body["runs"]) >= 1
        assert "run_id" in body["runs"][0]

    def test_actual_filters_lists_months(self, auth_headers):
        r = _get("/api/admin/salary-register/filters", headers=auth_headers,
                 params={"source": "actual", "company_id": COMPANY_ID,
                         "month": ACTUAL_MONTH})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert ACTUAL_MONTH in body["months"]
        assert len(body["runs"]) >= 1, f"expected runs for actual {ACTUAL_MONTH}"


# ---- /salary-register grid --------------------------------------------------


class TestRegisterCompliance:
    def test_grid_returns_dynamic_columns_and_rows(self, auth_headers):
        r = _get("/api/admin/salary-register", headers=auth_headers,
                 params={"source": "compliance", "company_id": COMPANY_ID,
                         "month": COMPLIANCE_MONTH, "page": 1, "page_size": 25})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        for k in ("columns", "groups", "rows", "totals", "total_rows",
                  "page", "page_size", "run_meta"):
            assert k in body
        # Data assertions — 126 employees for Kankani
        assert body["total_rows"] == 126, f"got total_rows={body['total_rows']}"
        assert len(body["rows"]) == 25
        assert body["page"] == 1
        assert body["page_size"] == 25
        # columns must include employee_code + name at minimum
        col_keys = [c["key"] for c in body["columns"]]
        assert "employee_code" in col_keys
        assert "name" in col_keys
        # groups list has expected 6 bands
        group_keys = {g["key"] for g in body["groups"]}
        assert group_keys == {"info", "attendance", "earnings",
                              "deductions", "employer", "net"}
        assert body["run_meta"]["run_id"]

    def test_pagination_page2_returns_remaining(self, auth_headers):
        r = _get("/api/admin/salary-register", headers=auth_headers,
                 params={"source": "compliance", "company_id": COMPANY_ID,
                         "month": COMPLIANCE_MONTH, "page": 2, "page_size": 50})
        assert r.status_code == 200
        body = r.json()
        assert body["total_rows"] == 126
        assert body["page"] == 2
        # rows 51..100 -> 50 rows
        assert len(body["rows"]) == 50

    def test_totals_computed_over_all_filtered_rows_not_page(self, auth_headers):
        r1 = _get("/api/admin/salary-register", headers=auth_headers,
                  params={"source": "compliance", "company_id": COMPANY_ID,
                          "month": COMPLIANCE_MONTH, "page": 1, "page_size": 25})
        r2 = _get("/api/admin/salary-register", headers=auth_headers,
                  params={"source": "compliance", "company_id": COMPANY_ID,
                          "month": COMPLIANCE_MONTH, "page": 3, "page_size": 25})
        assert r1.status_code == r2.status_code == 200
        # totals must not depend on page/page_size
        assert r1.json()["totals"] == r2.json()["totals"]

    def test_search_singh_filters_rows(self, auth_headers):
        r_all = _get("/api/admin/salary-register", headers=auth_headers,
                     params={"source": "compliance", "company_id": COMPANY_ID,
                             "month": COMPLIANCE_MONTH})
        r_srch = _get("/api/admin/salary-register", headers=auth_headers,
                      params={"source": "compliance", "company_id": COMPANY_ID,
                              "month": COMPLIANCE_MONTH, "search": "SINGH"})
        assert r_all.status_code == r_srch.status_code == 200
        assert r_srch.json()["total_rows"] < r_all.json()["total_rows"]
        # every returned row must contain SINGH in name or father_name
        for row in r_srch.json()["rows"]:
            hay = (str(row.get("name") or "") + " " + str(row.get("father_name") or "")
                   + " " + str(row.get("employee_code") or "")).upper()
            assert "SINGH" in hay, f"search leak: {row}"

    def test_employee_type_labour_filter(self, auth_headers):
        r = _get("/api/admin/salary-register", headers=auth_headers,
                 params={"source": "compliance", "company_id": COMPANY_ID,
                         "month": COMPLIANCE_MONTH, "employee_type": "LABOUR"})
        assert r.status_code == 200
        body = r.json()
        for row in body["rows"]:
            assert (row.get("employee_type") or "") == "LABOUR"

    def test_sort_name_desc(self, auth_headers):
        r = _get("/api/admin/salary-register", headers=auth_headers,
                 params={"source": "compliance", "company_id": COMPANY_ID,
                         "month": COMPLIANCE_MONTH, "sort_by": "name",
                         "sort_dir": "desc", "page_size": 10})
        assert r.status_code == 200
        names = [str(r_.get("name") or "").lower() for r_ in r.json()["rows"]]
        assert names == sorted(names, reverse=True), names

    def test_month_with_no_run_returns_empty_grid_not_404(self, auth_headers):
        r = _get("/api/admin/salary-register", headers=auth_headers,
                 params={"source": "compliance", "company_id": COMPANY_ID,
                         "month": "2020-01"})
        assert r.status_code == 200
        body = r.json()
        assert body["total_rows"] == 0
        assert body["rows"] == []
        assert body["run_meta"] is None

    def test_invalid_source_400(self, auth_headers):
        r = _get("/api/admin/salary-register", headers=auth_headers,
                 params={"source": "bogus", "company_id": COMPANY_ID,
                         "month": COMPLIANCE_MONTH})
        assert r.status_code == 400


class TestRegisterActual:
    def test_actual_grid_columns_differ_from_compliance(self, auth_headers):
        r_c = _get("/api/admin/salary-register", headers=auth_headers,
                   params={"source": "compliance", "company_id": COMPANY_ID,
                           "month": COMPLIANCE_MONTH, "page_size": 10})
        r_a = _get("/api/admin/salary-register", headers=auth_headers,
                   params={"source": "actual", "company_id": COMPANY_ID,
                           "month": ACTUAL_MONTH, "page_size": 10})
        assert r_c.status_code == r_a.status_code == 200
        keys_c = {c["key"] for c in r_c.json()["columns"]}
        keys_a = {c["key"] for c in r_a.json()["columns"]}
        # actual-only heads
        assert "net_pay" in keys_a, keys_a
        # compliance-only heads not in actual
        assert "pf_employer_epf" not in keys_a
        # sanity: dynamic column sets not identical
        assert keys_c != keys_a

    def test_actual_run_id_selector_works(self, auth_headers):
        # gather runs for actual month
        r = _get("/api/admin/salary-register/filters", headers=auth_headers,
                 params={"source": "actual", "company_id": COMPANY_ID,
                         "month": ACTUAL_MONTH})
        assert r.status_code == 200
        runs = r.json()["runs"]
        assert len(runs) >= 1
        pick = runs[0]["run_id"]
        r2 = _get("/api/admin/salary-register", headers=auth_headers,
                  params={"source": "actual", "company_id": COMPANY_ID,
                          "month": ACTUAL_MONTH, "run_id": pick, "page_size": 5})
        assert r2.status_code == 200
        assert r2.json()["run_meta"]["run_id"] == pick


# ---- Exports ----------------------------------------------------------------


class TestExports:
    @pytest.mark.parametrize("source,month", [
        ("compliance", COMPLIANCE_MONTH),
        ("actual", ACTUAL_MONTH),
    ])
    def test_csv_export_ok(self, auth_headers, source, month):
        r = _get("/api/admin/salary-register/export.csv", headers=auth_headers,
                 params={"source": source, "company_id": COMPANY_ID, "month": month})
        assert r.status_code == 200, r.text[:200]
        assert "text/csv" in r.headers.get("content-type", "")
        assert len(r.content) > 500
        # first line is header row (starts with utf-8-sig BOM)
        first_line = r.content.splitlines()[0].decode("utf-8-sig")
        assert first_line.startswith("Sr")
        # TOTAL row exists
        assert b"TOTAL" in r.content

    @pytest.mark.parametrize("source,month", [
        ("compliance", COMPLIANCE_MONTH),
        ("actual", ACTUAL_MONTH),
    ])
    def test_xlsx_export_ok(self, auth_headers, source, month):
        r = _get("/api/admin/salary-register/export.xlsx", headers=auth_headers,
                 params={"source": source, "company_id": COMPANY_ID, "month": month})
        assert r.status_code == 200, r.text[:200]
        assert "spreadsheetml" in r.headers.get("content-type", "")
        # xlsx = zip file starts with PK
        assert r.content[:2] == b"PK"
        assert len(r.content) > 2000

    @pytest.mark.parametrize("source,month", [
        ("compliance", COMPLIANCE_MONTH),
        ("actual", ACTUAL_MONTH),
    ])
    def test_pdf_export_ok(self, auth_headers, source, month):
        r = _get("/api/admin/salary-register/export.pdf", headers=auth_headers,
                 params={"source": source, "company_id": COMPANY_ID, "month": month})
        assert r.status_code == 200, r.text[:200]
        assert "application/pdf" in r.headers.get("content-type", "")
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 3000

    def test_csv_export_404_for_month_without_run(self, auth_headers):
        r = _get("/api/admin/salary-register/export.csv", headers=auth_headers,
                 params={"source": "compliance", "company_id": COMPANY_ID,
                         "month": "2020-01"})
        assert r.status_code == 404


# ---- Company admin scoping --------------------------------------------------


class TestCompanyAdminScoping:
    """company_admin must be scoped to their own company; the company_id
    query param must be ignored."""

    @pytest.fixture(scope="class")
    def ca_token(self):
        # Kankani company admin has a known password (Iter 193 note)
        r = requests.post(
            f"{BASE_URL}/api/auth/admin-password-login",
            json={"email": "admin@kankani.local", "password": "Kankani@123"},
            timeout=30,
        )
        if r.status_code != 200:
            pytest.skip(f"company_admin login unavailable: {r.status_code}")
        return r.json().get("session_token") or r.json().get("token")

    def test_ca_ignores_company_id_param(self, ca_token):
        # Pass a bogus company_id — backend must override with admin's own firm.
        r = _get("/api/admin/salary-register", headers={"Authorization": f"Bearer {ca_token}"},
                 params={"source": "compliance", "company_id": "cmp_does_not_exist",
                         "month": COMPLIANCE_MONTH, "page_size": 5})
        assert r.status_code == 200
        body = r.json()
        # If CA is scoped correctly, they'll see Kankani's 126 employees.
        assert body["total_rows"] == 126
