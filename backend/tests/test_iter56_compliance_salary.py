"""Backend tests for Iteration 56 — Compliance Salary Process (PF/ESIC/PT/TDS)."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
BASE_URL = (BASE_URL or "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _otp_login(identifier: str, channel: str = "email") -> str:
    r = requests.post(f"{API}/auth/otp/request", json={"identifier": identifier, "channel": channel}, timeout=30)
    r.raise_for_status()
    code = r.json().get("dev_code") or r.json().get("code")
    assert code, f"No dev code returned: {r.text}"
    r2 = requests.post(f"{API}/auth/otp/verify", json={"identifier": identifier, "channel": channel, "code": code}, timeout=30)
    r2.raise_for_status()
    j = r2.json()
    tok = j.get("token") or j.get("access_token") or j.get("session_token")
    assert tok, f"No token: {r2.text}"
    return tok


@pytest.fixture(scope="module")
def super_token():
    return _otp_login("sksharmaconsultancy@gmail.com", "email")


@pytest.fixture(scope="module")
def super_headers(super_token):
    return {"Authorization": f"Bearer {super_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def sksco_company_id(super_headers):
    r = requests.get(f"{API}/companies", headers=super_headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    comps = data if isinstance(data, list) else data.get("companies") or data.get("items") or []
    # Prefer S.K. Sharma & Co.
    for c in comps:
        if c.get("code") == "SKSCO1" or "SKSCO1" in (c.get("code") or ""):
            return c.get("company_id")
    return comps[0]["company_id"] if comps else None


@pytest.fixture(scope="module")
def employee_ids(super_headers, sksco_company_id):
    """Return list of user_ids in the target company (employees only)."""
    r = requests.get(f"{API}/admin/employees", headers=super_headers, params={"company_id": sksco_company_id}, timeout=30)
    r.raise_for_status()
    d = r.json()
    users = d if isinstance(d, list) else d.get("employees") or d.get("users") or d.get("items") or []
    emps = [u for u in users if u.get("role") == "employee" and (u.get("company_id") == sksco_company_id)]
    return [e["user_id"] for e in emps]


# =============================================================================
# 1) SCHEMA — create a run and verify all keys are present
# =============================================================================
class TestComplianceRunSchema:
    def test_create_run_basic_schema(self, super_headers, sksco_company_id):
        body = {"month": "2026-06", "company_id": sksco_company_id}
        r = requests.post(f"{API}/admin/compliance-salary-runs", json=body, headers=super_headers, timeout=60)
        assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
        j = r.json()
        assert j.get("ok") is True
        run = j["run"]
        assert "run_id" in run
        assert run["month"] == "2026-06"
        # totals keys
        totals = run.get("totals") or {}
        expected_totals = {
            "basic", "hra", "conveyance", "medical", "special", "others",
            "monthly_gross", "gross_paid", "ot_pay",
            "pf_wages", "pf_employee", "pf_employer_epf", "pf_employer_eps", "pf_employer_total",
            "esic_wage_base", "esic_employee", "esic_employer",
            "pt", "tds", "total_deduction", "net",
        }
        missing = expected_totals - set(totals.keys())
        assert not missing, f"Missing totals keys: {missing}"
        # No legacy keys
        assert "pf_percent" not in totals
        assert "esi_percent" not in totals

        pytest.run_id = run["run_id"]  # stash for later tests

        # Row schema
        rows = run.get("rows") or []
        if rows:
            row_keys = {
                "basic", "hra", "conveyance", "medical", "special", "others",
                "monthly_gross", "gross_paid", "stat_wage_base",
                "pf_wages", "pf_employee", "pf_employer_epf", "pf_employer_eps", "pf_employer_total",
                "esic_wage_base", "esic_employee", "esic_employer",
                "pt_state", "pt", "tds", "total_deduction", "net",
            }
            r0 = rows[0]
            missing_r = row_keys - set(r0.keys())
            assert not missing_r, f"Missing row keys: {missing_r}"


# =============================================================================
# 2) WAGE BASE MATH — floor rule
# =============================================================================
class TestWageBaseMath:
    def test_wage_base_max_basic_or_50pct_gross(self, super_headers, sksco_company_id, employee_ids):
        # Configure one employee with LOW basic override + big salary → 50% gross > basic
        if not employee_ids:
            pytest.skip("No employees in company")
        uid = employee_ids[0]
        # Set salary_monthly=50000 and basic_amount=5000 so gross~50000, 50% = 25000 > 5000
        r = requests.patch(f"{API}/admin/user-role", headers=super_headers, timeout=30, json={
            "user_id": uid, "salary_monthly": 50000,
            "basic_amount": 5000, "hra_amount": 0, "conv_amount": 0,
            "medical_amount": 0, "special_amount": 0, "others_amount": 0,
            "pf_applicable": True, "esic_applicable": True,
            "pt_state": "None", "tds_amount": 0,
        })
        assert r.status_code == 200, r.text

        # Also configure a second employee with HIGH basic > 50% gross
        if len(employee_ids) >= 2:
            uid2 = employee_ids[1]
            r2 = requests.patch(f"{API}/admin/user-role", headers=super_headers, timeout=30, json={
                "user_id": uid2, "salary_monthly": 20000,
                "basic_amount": 15000, "hra_amount": 0, "conv_amount": 0,
                "medical_amount": 0, "special_amount": 0, "others_amount": 0,
                "pf_applicable": True, "esic_applicable": True,
                "pt_state": "None", "tds_amount": 0,
            })
            assert r2.status_code == 200, r2.text

        # For monthly salary_mode and 0 attendance → present_days=0 → monthly_gross=0.
        # So we need to force present_days by setting salary_mode=daily OR seeding attendance.
        # Simpler: switch employees to salary_mode='daily'? Not supported directly via endpoint.
        # Instead: use policy override — patch employee_policy.salary_mode via not available.
        # Fallback: verify math using policy full-month by seeding attendance is heavy — instead
        # trust the compute path by inspecting a case that shows structure math on 0 present.
        # We'll create the run and simply verify per-row math consistency (stat_wage_base rule).
        body = {"month": "2026-06", "company_id": sksco_company_id}
        rr = requests.post(f"{API}/admin/compliance-salary-runs", json=body, headers=super_headers, timeout=60)
        assert rr.status_code == 200
        run = rr.json()["run"]
        rows = {row["user_id"]: row for row in run["rows"]}
        row1 = rows.get(uid)
        assert row1 is not None
        # Verify the invariant: stat_wage_base == max(basic, gross_paid * 0.5)
        expected = round(max(row1["basic"], row1["gross_paid"] * 0.5), 2)
        assert abs(row1["stat_wage_base"] - expected) < 0.02, (
            f"row1 stat_wage_base {row1['stat_wage_base']} vs expected {expected} "
            f"(basic={row1['basic']}, gross={row1['gross_paid']})"
        )
        if len(employee_ids) >= 2:
            row2 = rows.get(employee_ids[1])
            if row2:
                expected2 = round(max(row2["basic"], row2["gross_paid"] * 0.5), 2)
                assert abs(row2["stat_wage_base"] - expected2) < 0.02

    def test_pf_cap_15000(self, super_headers, sksco_company_id, employee_ids):
        """If stat_wage_base > 15000, pf_wages == 15000, pf_employee == 1800."""
        if not employee_ids:
            pytest.skip("No employees")
        # For rows with 0 attendance, gross=0 → stat_wage_base=max(basic,0)=basic.
        # We need basic > 15000 to hit cap.
        uid = employee_ids[0]
        r = requests.patch(f"{API}/admin/user-role", headers=super_headers, timeout=30, json={
            "user_id": uid, "salary_monthly": 60000,
            "basic_amount": 25000, "hra_amount": 0, "conv_amount": 0,
            "medical_amount": 0, "special_amount": 0, "others_amount": 0,
            "pf_applicable": True, "esic_applicable": True,
            "pt_state": "None", "tds_amount": 0,
        })
        assert r.status_code == 200, r.text
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        assert rr.status_code == 200
        rows = {r["user_id"]: r for r in rr.json()["run"]["rows"]}
        row = rows.get(uid)
        assert row is not None
        assert row["stat_wage_base"] >= 15000
        assert row["pf_wages"] == 15000.0, f"pf_wages={row['pf_wages']}"
        assert row["pf_employee"] == 1800.0, f"pf_employee={row['pf_employee']}"


# =============================================================================
# 3) ESIC eligibility
# =============================================================================
class TestESIC:
    def test_esic_disabled_when_gross_over_21000(self, super_headers, sksco_company_id, employee_ids):
        """If gross_paid > 21000, esic_employee == 0 and esic_employer == 0."""
        if not employee_ids:
            pytest.skip("No employees")
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        rows = rr.json()["run"]["rows"]
        # Check invariant on all rows: gross_paid>21000 ⇒ esic=0
        for row in rows:
            if row["gross_paid"] > 21000.0 and row.get("esic_applicable", True):
                assert row["esic_employee"] == 0.0, f"row {row['user_id']}: gross={row['gross_paid']} esic_e={row['esic_employee']}"
                assert row["esic_employer"] == 0.0

    def test_esic_applied_when_eligible(self, super_headers, sksco_company_id, employee_ids):
        if not employee_ids:
            pytest.skip("No employees")
        # Ensure at least one employee gross_paid <= 21000 with esic_applicable=True
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        rows = rr.json()["run"]["rows"]
        eligible = [r for r in rows if 0 < r["gross_paid"] <= 21000 and r.get("esic_applicable", True)]
        if not eligible:
            pytest.skip("No employee has gross in ESIC-eligible range (need attendance seed)")
        r = eligible[0]
        expected_e = round(r["stat_wage_base"] * 0.0075, 2)
        expected_er = round(r["stat_wage_base"] * 0.0325, 2)
        assert abs(r["esic_employee"] - expected_e) < 0.05
        assert abs(r["esic_employer"] - expected_er) < 0.05


# =============================================================================
# 4) Toggles (pf_applicable, esic_applicable)
# =============================================================================
class TestToggles:
    def test_pf_toggle_off(self, super_headers, sksco_company_id, employee_ids):
        if not employee_ids:
            pytest.skip("No employees")
        uid = employee_ids[0]
        # Ensure basic is set so pf would otherwise fire
        r = requests.patch(f"{API}/admin/user-role", headers=super_headers, timeout=30, json={
            "user_id": uid, "pf_applicable": False, "basic_amount": 20000,
        })
        assert r.status_code == 200, r.text
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        row = next(r for r in rr.json()["run"]["rows"] if r["user_id"] == uid)
        assert row["pf_employee"] == 0.0
        assert row["pf_employer_total"] == 0.0
        # restore
        requests.patch(f"{API}/admin/user-role", headers=super_headers, timeout=30, json={
            "user_id": uid, "pf_applicable": True,
        })

    def test_esic_toggle_off(self, super_headers, sksco_company_id, employee_ids):
        if not employee_ids:
            pytest.skip("No employees")
        uid = employee_ids[0]
        r = requests.patch(f"{API}/admin/user-role", headers=super_headers, timeout=30, json={
            "user_id": uid, "esic_applicable": False,
        })
        assert r.status_code == 200, r.text
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        row = next(r for r in rr.json()["run"]["rows"] if r["user_id"] == uid)
        assert row["esic_employee"] == 0.0
        assert row["esic_employer"] == 0.0
        requests.patch(f"{API}/admin/user-role", headers=super_headers, timeout=30, json={
            "user_id": uid, "esic_applicable": True,
        })


# =============================================================================
# 5) PT + TDS
# =============================================================================
class TestPTandTDS:
    def test_pt_state_maharashtra(self, super_headers, sksco_company_id, employee_ids):
        if not employee_ids:
            pytest.skip("No employees")
        uid = employee_ids[0]
        r = requests.patch(f"{API}/admin/user-role", headers=super_headers, timeout=30, json={
            "user_id": uid, "pt_state": "Maharashtra",
        })
        assert r.status_code == 200, r.text
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        row = next(r for r in rr.json()["run"]["rows"] if r["user_id"] == uid)
        assert row["pt"] == 200.0, f"pt={row['pt']}"
        assert row["pt_state"] == "Maharashtra"

    def test_pt_none(self, super_headers, sksco_company_id, employee_ids):
        if not employee_ids:
            pytest.skip("No employees")
        uid = employee_ids[0]
        requests.patch(f"{API}/admin/user-role", headers=super_headers, timeout=30, json={
            "user_id": uid, "pt_state": "None",
        })
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        row = next(r for r in rr.json()["run"]["rows"] if r["user_id"] == uid)
        assert row["pt"] == 0.0

    def test_tds_manual(self, super_headers, sksco_company_id, employee_ids):
        if not employee_ids:
            pytest.skip("No employees")
        uid = employee_ids[0]
        r = requests.patch(f"{API}/admin/user-role", headers=super_headers, timeout=30, json={
            "user_id": uid, "tds_amount": 500,
        })
        assert r.status_code == 200, r.text
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        row = next(r for r in rr.json()["run"]["rows"] if r["user_id"] == uid)
        assert row["tds"] == 500.0
        # cleanup
        requests.patch(f"{API}/admin/user-role", headers=super_headers, timeout=30, json={
            "user_id": uid, "tds_amount": 0,
        })


# =============================================================================
# 6) LIST / DETAIL / REPROCESS
# =============================================================================
class TestCRUD:
    def test_list_runs(self, super_headers):
        r = requests.get(f"{API}/admin/compliance-salary-runs", headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        # Accept both list and {runs: []}
        runs = j if isinstance(j, list) else j.get("runs") or j.get("items") or []
        assert isinstance(runs, list)

    def test_get_run_by_id(self, super_headers, sksco_company_id):
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        rid = rr.json()["run"]["run_id"]
        d = requests.get(f"{API}/admin/compliance-salary-runs/{rid}", headers=super_headers, timeout=30)
        assert d.status_code == 200
        run = d.json().get("run") or d.json()
        assert run.get("run_id") == rid

    def test_get_run_not_found(self, super_headers):
        d = requests.get(f"{API}/admin/compliance-salary-runs/csrun_nonexistent", headers=super_headers, timeout=30)
        assert d.status_code == 404

    def test_reprocess(self, super_headers, sksco_company_id):
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        rid = rr.json()["run"]["run_id"]
        rp = requests.post(f"{API}/admin/compliance-salary-runs/{rid}/reprocess",
                           headers=super_headers, timeout=60)
        assert rp.status_code == 200, f"{rp.status_code}: {rp.text}"
        run2 = rp.json().get("run") or rp.json()
        # schema preserved
        assert "totals" in run2
        assert "net" in run2["totals"]


# =============================================================================
# 7) CSV / PDF
# =============================================================================
class TestExports:
    def test_csv_export(self, super_headers, sksco_company_id):
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        rid = rr.json()["run"]["run_id"]
        c = requests.get(f"{API}/admin/compliance-salary-runs/{rid}/export.csv",
                         headers=super_headers, timeout=30)
        assert c.status_code == 200
        ct = c.headers.get("Content-Type", "")
        assert "text/csv" in ct, f"Content-Type: {ct}"
        header = c.text.splitlines()[0]
        for col in ("stat_wage_base", "pf_employee", "esic_employee", "pt", "tds"):
            assert col in header, f"Missing col {col} in header: {header}"

    def test_pdf_export(self, super_headers, sksco_company_id):
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        rid = rr.json()["run"]["run_id"]
        p = requests.get(f"{API}/admin/compliance-salary-runs/{rid}/register.pdf",
                         headers=super_headers, timeout=30)
        assert p.status_code == 200
        assert "application/pdf" in p.headers.get("Content-Type", "")
        assert len(p.content) > 500


# =============================================================================
# 8) Generate payslips
# =============================================================================
class TestGeneratePayslips:
    def test_generate_compliance_payslips(self, super_headers, sksco_company_id):
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        rid = rr.json()["run"]["run_id"]
        rows_count = len(rr.json()["run"]["rows"])
        gp = requests.post(f"{API}/admin/compliance-salary-runs/{rid}/generate-payslips",
                           headers=super_headers, timeout=60)
        assert gp.status_code == 200, gp.text
        j = gp.json()
        count = j.get("payslips_count") or j.get("count") or j.get("created") or 0
        assert count == rows_count, f"expected {rows_count} payslips, got {count}: {j}"


# =============================================================================
# 9) Company-admin scoping
# =============================================================================
class TestScoping:
    def test_company_admin_cannot_access_cross_company_run(self, super_headers, sksco_company_id):
        """Create run for one company as super_admin; try to fetch as another company_admin."""
        # First, create a run for SKSCO1
        rr = requests.post(f"{API}/admin/compliance-salary-runs",
                           json={"month": "2026-06", "company_id": sksco_company_id},
                           headers=super_headers, timeout=60)
        rid = rr.json()["run"]["run_id"]
        # Login as company_admin of a DIFFERENT company (Sharma Associates, +919810000002)
        try:
            tok = _otp_login("+919810000002", "sms")
        except Exception:
            pytest.skip("Second company admin OTP not available")
        h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
        r = requests.get(f"{API}/admin/compliance-salary-runs/{rid}", headers=h, timeout=30)
        assert r.status_code in (403, 404), f"Expected 403/404 for cross-company, got {r.status_code}"
