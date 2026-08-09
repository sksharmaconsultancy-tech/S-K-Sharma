"""Iter 527 backend tests.

Covers three features:
  1. Salary Comparison — grouped by dept / designation / both (removed
     name-wise rows; must have 'employees' + attendance columns).
  2. Central Contractor Wage Registers (Form A–D):
       - /filters, /register/form-{a|b|c|d} JSON + xlsx + pdf exports
       - workflow (prepare→verify→approve→lock→unlock) audit history
       - form-c-entries rejection when Form C period approved/locked
       - masters CRUD (principal-employers, work-orders, employee-map);
         verify Form A picks up mapped contractor/PE/site for employees.
       - custom wage period slicing for Form D (15 day columns).
  3. Present/Absent + Daily OT — dual-row format smoke.
"""
import io
import os

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL",
                          "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"
MONTH = "2026-07"


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com",
                            "password": "sharma123"}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def api(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}",
                      "Content-Type": "application/json"})
    return s


# ---------------------------------------------------------------------------
# 1) Salary Comparison — grouped
# ---------------------------------------------------------------------------
class TestSalaryComparison:
    def _get(self, api, group_by):
        return api.get(f"{BASE_URL}/api/admin/payroll-reports/salary-comparison",
                       params={"company_id": COMPANY_ID, "month": MONTH,
                               "month_b": MONTH, "group_by": group_by},
                       timeout=60)

    def test_group_both_has_section_headers(self, api):
        r = self._get(api, "both")
        assert r.status_code == 200, r.text
        j = r.json()
        col_keys = [c["key"] for c in j["columns"]]
        assert "employees" in col_keys, f"missing employees col: {col_keys}"
        assert "group" in col_keys
        # verify NO name-wise employee columns
        assert "name" not in col_keys and "employee_code" not in col_keys
        groups = [r.get("group") for r in j["rows"]]
        assert "— DEPARTMENT WISE —" in groups
        assert "— DESIGNATION WISE —" in groups
        # totals row must have employees as int
        assert isinstance(j["totals"]["employees"], int)

    def test_group_department_only(self, api):
        r = self._get(api, "department")
        assert r.status_code == 200
        j = r.json()
        groups = [x.get("group") for x in j["rows"]]
        assert "— DESIGNATION WISE —" not in groups
        assert "— DEPARTMENT WISE —" not in groups

    def test_group_designation_only(self, api):
        r = self._get(api, "designation")
        assert r.status_code == 200

    def test_xlsx_binary_ok(self, api):
        r = api.get(
            f"{BASE_URL}/api/admin/payroll-reports/salary-comparison.xlsx",
            params={"company_id": COMPANY_ID, "month": MONTH,
                    "month_b": MONTH, "group_by": "both"}, timeout=60)
        assert r.status_code == 200
        assert r.content[:2] == b"PK"  # xlsx is a zip

    def test_pdf_binary_ok(self, api):
        r = api.get(
            f"{BASE_URL}/api/admin/payroll-reports/salary-comparison.pdf",
            params={"company_id": COMPANY_ID, "month": MONTH,
                    "month_b": MONTH, "group_by": "both"}, timeout=60)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# 2) Central Wage Registers — filters + basic reads
# ---------------------------------------------------------------------------
class TestCentralWageRegistersRead:
    def test_filters(self, api):
        r = api.get(
            f"{BASE_URL}/api/admin/central-wage-registers/filters",
            params={"company_id": COMPANY_ID}, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("contractors", "principal_employers", "work_orders",
                 "sites", "departments", "employee_types", "employees",
                 "framework"):
            assert k in j, f"filters missing {k}"
        assert isinstance(j["employees"], list) and len(j["employees"]) > 0

    @pytest.mark.parametrize("kind", ["form-a", "form-b", "form-c", "form-d"])
    def test_register_json(self, api, kind):
        r = api.get(
            f"{BASE_URL}/api/admin/central-wage-registers/register/{kind}",
            params={"company_id": COMPANY_ID, "month": MONTH}, timeout=90)
        assert r.status_code == 200, f"{kind}: {r.text[:300]}"
        j = r.json()
        for k in ("title", "columns", "rows", "status"):
            assert k in j
        assert isinstance(j["columns"], list) and len(j["columns"]) > 0

    @pytest.mark.parametrize("kind", ["form-a", "form-b", "form-c", "form-d"])
    def test_register_xlsx(self, api, kind):
        r = api.get(
            f"{BASE_URL}/api/admin/central-wage-registers/register/{kind}.xlsx",
            params={"company_id": COMPANY_ID, "month": MONTH}, timeout=90)
        assert r.status_code == 200
        assert r.content[:2] == b"PK"

    @pytest.mark.parametrize("kind", ["form-a", "form-b", "form-c", "form-d"])
    def test_register_pdf(self, api, kind):
        r = api.get(
            f"{BASE_URL}/api/admin/central-wage-registers/register/{kind}.pdf",
            params={"company_id": COMPANY_ID, "month": MONTH}, timeout=120)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# 2b) workflow — status transitions + audit growth on Form B
# ---------------------------------------------------------------------------
class TestWorkflow:
    def _post(self, api, action, register="b", period=MONTH):
        return api.post(
            f"{BASE_URL}/api/admin/central-wage-registers/status",
            json={"company_id": COMPANY_ID, "register": register,
                  "period": period, "action": action,
                  "note": f"pytest {action}"}, timeout=30)

    def test_transitions_and_history(self, api):
        # start from unlock to normalize
        self._post(api, "unlock")
        prev_len = 0
        for action, expected in [("prepare", "draft"), ("verify", "verified"),
                                 ("approve", "approved"), ("lock", "locked"),
                                 ("unlock", "draft")]:
            r = self._post(api, action)
            assert r.status_code == 200, f"{action}: {r.text}"
            j = r.json()
            assert j["status"] == expected
            hist = j["doc"].get("history") or []
            assert len(hist) > prev_len, f"history did not grow at {action}"
            prev_len = len(hist)


# ---------------------------------------------------------------------------
# 2c) Form C entries — lock rejection
# ---------------------------------------------------------------------------
class TestFormCEntriesLock:
    def _c_status(self, api, action):
        return api.post(
            f"{BASE_URL}/api/admin/central-wage-registers/status",
            json={"company_id": COMPANY_ID, "register": "c",
                  "period": MONTH, "action": action}, timeout=30)

    def _get_any_user(self, api):
        r = api.get(
            f"{BASE_URL}/api/admin/central-wage-registers/filters",
            params={"company_id": COMPANY_ID}, timeout=30)
        return r.json()["employees"][0]["user_id"]

    def test_entry_when_draft_then_reject_when_approved(self, api):
        # ensure draft
        self._c_status(api, "unlock")
        uid = self._get_any_user(api)
        payload = {"company_id": COMPANY_ID, "user_id": uid,
                   "date": f"{MONTH}-05", "wage_period": MONTH,
                   "dtype": "Fine", "reason": "pytest fine",
                   "fine_amount": 10}
        r = api.post(
            f"{BASE_URL}/api/admin/central-wage-registers/form-c-entries",
            json=payload, timeout=30)
        assert r.status_code == 200, r.text
        entry_id = r.json()["entry_id"]

        # approve Form C → new entry must 409
        r2 = self._c_status(api, "approve")
        assert r2.status_code == 200
        r3 = api.post(
            f"{BASE_URL}/api/admin/central-wage-registers/form-c-entries",
            json={**payload, "reason": "pytest post-approve"}, timeout=30)
        assert r3.status_code == 409, f"expected 409 got {r3.status_code}: {r3.text}"

        # delete of existing entry must also 409
        r4 = api.delete(
            f"{BASE_URL}/api/admin/central-wage-registers/form-c-entries/{entry_id}",
            params={"company_id": COMPANY_ID}, timeout=30)
        assert r4.status_code == 409

        # unlock and clean up entry
        self._c_status(api, "unlock")
        r5 = api.delete(
            f"{BASE_URL}/api/admin/central-wage-registers/form-c-entries/{entry_id}",
            params={"company_id": COMPANY_ID}, timeout=30)
        assert r5.status_code == 200


# ---------------------------------------------------------------------------
# 2d) masters CRUD — PE, WO, emp-map + Form A reflects mapping
# ---------------------------------------------------------------------------
class TestMastersCRUD:
    def test_full_flow(self, api):
        # PE create
        r = api.post(
            f"{BASE_URL}/api/admin/central-wage-registers/principal-employers",
            json={"company_id": COMPANY_ID, "name": "TEST_PE_pytest",
                  "address": "Bhilwara", "representative": "Test Rep"},
            timeout=30)
        assert r.status_code == 200
        pe_id = r.json()["pe_id"]

        # WO create linked to PE
        r = api.post(
            f"{BASE_URL}/api/admin/central-wage-registers/work-orders",
            json={"company_id": COMPANY_ID, "wo_number": "TEST_WO_PY",
                  "pe_id": pe_id, "site": "TEST_SITE_PY",
                  "description": "pytest WO"}, timeout=30)
        assert r.status_code == 200
        wo_id = r.json()["wo_id"]

        # pick 2 employees, and any contractor if exists
        f = api.get(
            f"{BASE_URL}/api/admin/central-wage-registers/filters",
            params={"company_id": COMPANY_ID}, timeout=30).json()
        emp_ids = [e["user_id"] for e in f["employees"][:2]]
        contractor_id = (f["contractors"][0]["contractor_id"]
                         if f["contractors"] else "")

        # bulk map
        r = api.post(
            f"{BASE_URL}/api/admin/central-wage-registers/employee-map",
            json={"company_id": COMPANY_ID, "user_ids": emp_ids,
                  "contractor_id": contractor_id, "work_order_id": wo_id,
                  "pe_id": pe_id, "site": "TEST_SITE_PY"}, timeout=30)
        assert r.status_code == 200
        assert r.json()["mapped"] == len(emp_ids)

        # Form A must reflect mapping for these employees
        r = api.get(
            f"{BASE_URL}/api/admin/central-wage-registers/register/form-a",
            params={"company_id": COMPANY_ID, "month": MONTH}, timeout=60)
        assert r.status_code == 200
        rows_by_uid = {r_.get("employee_code"): r_ for r_ in r.json()["rows"]}
        # look up any mapped emp by code — get their code
        codes = [e["employee_code"] for e in f["employees"][:2]]
        found = False
        for code in codes:
            row = rows_by_uid.get(code) or {}
            if (row.get("principal_employer") == "TEST_PE_pytest"
                    and row.get("work_location") == "TEST_SITE_PY"):
                found = True
                break
        assert found, f"Form A didn't reflect mapping. codes={codes}"

        # cleanup
        for uid in emp_ids:
            api.delete(
                f"{BASE_URL}/api/admin/central-wage-registers/employee-map/{uid}",
                params={"company_id": COMPANY_ID}, timeout=30)
        api.delete(
            f"{BASE_URL}/api/admin/central-wage-registers/work-orders/{wo_id}",
            params={"company_id": COMPANY_ID}, timeout=30)
        api.delete(
            f"{BASE_URL}/api/admin/central-wage-registers/principal-employers/{pe_id}",
            params={"company_id": COMPANY_ID}, timeout=30)


# ---------------------------------------------------------------------------
# 2e) custom wage period — Form D 15-day slice
# ---------------------------------------------------------------------------
class TestCustomPeriod:
    def test_form_d_15_days(self, api):
        r = api.get(
            f"{BASE_URL}/api/admin/central-wage-registers/register/form-d",
            params={"company_id": COMPANY_ID,
                    "from_date": "2026-07-01",
                    "to_date": "2026-07-15"}, timeout=90)
        assert r.status_code == 200, r.text
        cols = r.json()["columns"]
        # date cols are of form "2026-07-DD"
        day_cols = [c for c in cols if c["key"].startswith("2026-07-")]
        assert len(day_cols) == 15, (
            f"expected 15 day cols, got {len(day_cols)}: "
            f"{[c['key'] for c in day_cols]}")


# ---------------------------------------------------------------------------
# 3) Present/Absent + Daily OT smoke
# ---------------------------------------------------------------------------
class TestPresentAbsentOT:
    def test_old_format_json(self, api):
        r = api.get(f"{BASE_URL}/api/admin/reports/present-absent",
                    params={"company_id": COMPANY_ID, "month": MONTH},
                    timeout=60)
        assert r.status_code == 200, r.text

    def test_new_dual_row_json(self, api):
        r = api.get(f"{BASE_URL}/api/admin/reports/present-absent-ot",
                    params={"company_id": COMPANY_ID, "month": MONTH},
                    timeout=60)
        assert r.status_code == 200, r.text

    def test_new_dual_row_xlsx(self, api):
        r = api.get(f"{BASE_URL}/api/admin/reports/present-absent-ot.xlsx",
                    params={"company_id": COMPANY_ID, "month": MONTH},
                    timeout=60)
        assert r.status_code == 200
        assert r.content[:2] == b"PK"

    def test_new_dual_row_pdf(self, api):
        r = api.get(f"{BASE_URL}/api/admin/reports/present-absent-ot.pdf",
                    params={"company_id": COMPANY_ID, "month": MONTH},
                    timeout=90)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"
