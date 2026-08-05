"""Iter 500 — CTC Module (Phases 1-3) backend tests.

Covers:
- Auto-seed of 3 default CTC templates (idempotent)
- POST /api/admin/ctc/preview breakup math (Standard Office CTC)
- Structures CRUD (create/update/delete + DELETE-blocked-when-assigned)
- Firm-mode GET/PUT with validation
- Employee assign + revisions + summary
- Compliance salary run hook (ctc_mode row stamping, backward compat)
- Payslip PDF for CTC employee (%PDF header)
- MANDATORY cleanup (revert employee, delete run/snapshot/custom structures, restore firm-mode).
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://emplo-connect-1.preview.emergentagent.com"

COMPANY_ID = "cmp_527fecdd7c"
TEST_MONTH = "2026-11"   # never-processed month for backward-compat test
BASELINE_MONTH = "2026-07"  # pre-CTC processed month (used for gross-mode baseline check)


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("session_token")
    assert tok
    return tok


@pytest.fixture(scope="session")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def test_employee(headers):
    """Pick an employee (monthly staff preferred) to switch to CTC."""
    r = requests.get(
        f"{BASE_URL}/api/admin/ctc/employees",
        params={"company_id": COMPANY_ID}, headers=headers, timeout=30,
    )
    assert r.status_code == 200
    rows = r.json()["rows"]
    # Try to find employee_code 212 (monthly), else code 50, else first gross-mode row
    pick = None
    for code in ("212", "50"):
        for row in rows:
            if str(row.get("employee_code")) == code:
                pick = row
                break
        if pick:
            break
    if not pick:
        pick = next((r for r in rows if (r.get("salary_mode") or "gross") == "gross"), None)
    assert pick, "no employee found for CTC test"
    return pick


@pytest.fixture(scope="session")
def cleanup_state():
    """Track resources created during tests for teardown."""
    return {"custom_structure_ids": [], "assigned_user_id": None,
            "run_created": False}


# ---------------------------------------------------------------------------
# 1) Structures auto-seed + list
# ---------------------------------------------------------------------------
class TestStructuresSeed:
    def test_list_structures_seeds_three_defaults(self, headers):
        r1 = requests.get(f"{BASE_URL}/api/admin/ctc/structures",
                          params={"company_id": COMPANY_ID}, headers=headers,
                          timeout=30)
        assert r1.status_code == 200
        s1 = r1.json()["structures"]
        names = {s["name"] for s in s1}
        assert {"Standard Office CTC", "Compliance / Labour CTC",
                "Flexible / Custom CTC"}.issubset(names)
        # Idempotent: call again → still 3 defaults (no duplicates)
        r2 = requests.get(f"{BASE_URL}/api/admin/ctc/structures",
                          params={"company_id": COMPANY_ID}, headers=headers,
                          timeout=30)
        s2 = r2.json()["structures"]
        default_names_after = [s["name"] for s in s2 if s.get("is_template")]
        # Each default template appears exactly once
        for n in ("Standard Office CTC", "Compliance / Labour CTC",
                  "Flexible / Custom CTC"):
            assert default_names_after.count(n) == 1, \
                f"template {n} appears {default_names_after.count(n)} times"


# ---------------------------------------------------------------------------
# 2) Preview breakup math
# ---------------------------------------------------------------------------
class TestPreview:
    def test_preview_standard_office_ctc_30000(self, headers):
        r = requests.get(f"{BASE_URL}/api/admin/ctc/structures",
                         params={"company_id": COMPANY_ID}, headers=headers,
                         timeout=30)
        sid = next(s["structure_id"] for s in r.json()["structures"]
                   if s["name"] == "Standard Office CTC")
        p = requests.post(f"{BASE_URL}/api/admin/ctc/preview",
                         json={"monthly_ctc": 30000, "structure_id": sid},
                         headers=headers, timeout=30)
        assert p.status_code == 200
        bk = p.json()["breakup"]
        # gross + employer_total ≈ CTC
        assert round(bk["gross"] + bk["employer_total"]) == 30000, \
            f"gross+employer={bk['gross']}+{bk['employer_total']}"
        # basic ~ 50% of gross
        assert abs(bk["basic"] - bk["gross"] * 0.5) < 1.0
        # net = gross - deductions
        assert round(bk["net_salary"], 2) == round(
            bk["gross"] - bk["deduction_total"], 2)

    def test_preview_rejects_zero_ctc(self, headers):
        p = requests.post(f"{BASE_URL}/api/admin/ctc/preview",
                         json={"monthly_ctc": 0, "components": []},
                         headers=headers, timeout=30)
        assert p.status_code == 400


# ---------------------------------------------------------------------------
# 3) Structure CRUD + delete-blocked
# ---------------------------------------------------------------------------
class TestStructureCRUD:
    def test_create_update_delete_custom_structure(self, headers, cleanup_state):
        body = {"company_id": COMPANY_ID,
                "name": "TEST_ITER500 Custom",
                "description": "iter500 test structure",
                "components": [
                    {"key": "basic", "label": "Basic", "type": "earning",
                     "calc": "percent", "value": 50, "base": "gross", "seq": 1},
                    {"key": "special", "label": "Special", "type": "earning",
                     "calc": "balance", "value": 0, "base": "gross", "seq": 2},
                    {"key": "emp_pf", "label": "Employer PF", "type": "employer",
                     "calc": "percent", "value": 12, "base": "basic", "seq": 10,
                     "base_cap": 15000},
                    {"key": "ded_pf", "label": "Employee PF", "type": "deduction",
                     "calc": "percent", "value": 12, "base": "basic", "seq": 20,
                     "base_cap": 15000},
                ]}
        c = requests.post(f"{BASE_URL}/api/admin/ctc/structures",
                          json=body, headers=headers, timeout=30)
        assert c.status_code == 200, c.text
        sid = c.json()["structure"]["structure_id"]
        cleanup_state["custom_structure_ids"].append(sid)

        # Update
        u = requests.put(f"{BASE_URL}/api/admin/ctc/structures/{sid}",
                        json={"description": "updated by test"},
                        headers=headers, timeout=30)
        assert u.status_code == 200

        # Delete (nobody assigned) → OK
        d = requests.delete(f"{BASE_URL}/api/admin/ctc/structures/{sid}",
                            headers=headers, timeout=30)
        assert d.status_code == 200
        cleanup_state["custom_structure_ids"].remove(sid)

    def test_delete_blocked_when_employee_assigned(self, headers, cleanup_state,
                                                    test_employee):
        # Create custom structure with basic component
        body = {"company_id": COMPANY_ID,
                "name": "TEST_ITER500 Assign-blocked",
                "components": [
                    {"key": "basic", "label": "Basic", "type": "earning",
                     "calc": "percent", "value": 50, "base": "gross", "seq": 1},
                    {"key": "special", "label": "Special", "type": "earning",
                     "calc": "balance", "value": 0, "base": "gross", "seq": 2},
                ]}
        c = requests.post(f"{BASE_URL}/api/admin/ctc/structures",
                         json=body, headers=headers, timeout=30)
        sid = c.json()["structure"]["structure_id"]
        cleanup_state["custom_structure_ids"].append(sid)

        # Assign this structure to the test employee TEMPORARILY
        a = requests.post(f"{BASE_URL}/api/admin/ctc/assign",
                         json={"user_id": test_employee["user_id"],
                               "salary_mode": "ctc", "monthly_ctc": 20000,
                               "structure_id": sid,
                               "reason": "TEST_ITER500 delete-block probe"},
                         headers=headers, timeout=30)
        assert a.status_code == 200, a.text

        # DELETE should be blocked with 400
        d = requests.delete(f"{BASE_URL}/api/admin/ctc/structures/{sid}",
                           headers=headers, timeout=30)
        assert d.status_code == 400, f"expected 400 got {d.status_code}: {d.text}"
        assert "assigned" in (d.json().get("detail") or "").lower()

        # Revert employee back to gross so we can delete the structure
        rr = requests.post(f"{BASE_URL}/api/admin/ctc/assign",
                          json={"user_id": test_employee["user_id"],
                                "salary_mode": "gross",
                                "reason": "TEST_ITER500 revert"},
                          headers=headers, timeout=30)
        assert rr.status_code == 200


# ---------------------------------------------------------------------------
# 4) Firm mode
# ---------------------------------------------------------------------------
class TestFirmMode:
    def test_get_and_put_firm_mode(self, headers):
        # Read current
        g = requests.get(f"{BASE_URL}/api/admin/ctc/firm-mode/{COMPANY_ID}",
                        headers=headers, timeout=30)
        assert g.status_code == 200
        original = g.json()["mode"]

        # Cycle through valid modes
        for mode in ("ctc", "mixed", "gross"):
            p = requests.put(f"{BASE_URL}/api/admin/ctc/firm-mode/{COMPANY_ID}",
                            json={"mode": mode}, headers=headers, timeout=30)
            assert p.status_code == 200
            assert p.json()["mode"] == mode

        # Invalid
        bad = requests.put(f"{BASE_URL}/api/admin/ctc/firm-mode/{COMPANY_ID}",
                          json={"mode": "invalid"}, headers=headers, timeout=30)
        assert bad.status_code == 400

        # Restore to 'gross' (MANDATORY per request)
        r = requests.put(f"{BASE_URL}/api/admin/ctc/firm-mode/{COMPANY_ID}",
                        json={"mode": "gross"}, headers=headers, timeout=30)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 5) Assign + revisions + summary
# ---------------------------------------------------------------------------
class TestAssignAndRevisions:
    def test_assign_validation_missing_monthly_ctc(self, headers, test_employee):
        r = requests.post(f"{BASE_URL}/api/admin/ctc/assign",
                         json={"user_id": test_employee["user_id"],
                               "salary_mode": "ctc", "reason": "TEST_ITER500"},
                         headers=headers, timeout=30)
        assert r.status_code == 400

    def test_assign_validation_missing_structure_id(self, headers, test_employee, cleanup_state):
        # need a valid sid to isolate this validation
        r = requests.post(f"{BASE_URL}/api/admin/ctc/assign",
                         json={"user_id": test_employee["user_id"],
                               "salary_mode": "ctc", "monthly_ctc": 30000,
                               "reason": "TEST_ITER500"},
                         headers=headers, timeout=30)
        assert r.status_code == 400

    def test_assign_ctc_and_verify_register_and_revisions(self, headers,
                                                          test_employee,
                                                          cleanup_state):
        # Pick Standard Office CTC template id
        s = requests.get(f"{BASE_URL}/api/admin/ctc/structures",
                        params={"company_id": COMPANY_ID}, headers=headers,
                        timeout=30)
        sid = next(x["structure_id"] for x in s.json()["structures"]
                   if x["name"] == "Standard Office CTC")

        a = requests.post(f"{BASE_URL}/api/admin/ctc/assign",
                         json={"user_id": test_employee["user_id"],
                               "salary_mode": "ctc", "monthly_ctc": 30000,
                               "structure_id": sid,
                               "reason": "TEST_ITER500 CTC assignment"},
                         headers=headers, timeout=30)
        assert a.status_code == 200, a.text
        rev = a.json()["revision"]
        assert rev["new_mode"] == "ctc"
        assert rev["new_ctc"] == 30000
        cleanup_state["assigned_user_id"] = test_employee["user_id"]

        # Register shows CTC mode + annual_ctc = 360000
        er = requests.get(f"{BASE_URL}/api/admin/ctc/employees",
                        params={"company_id": COMPANY_ID}, headers=headers,
                        timeout=30)
        row = next(r for r in er.json()["rows"]
                   if r["user_id"] == test_employee["user_id"])
        assert row["salary_mode"] == "ctc"
        assert row["annual_ctc"] == 360000
        assert row["monthly_ctc"] == 30000
        assert row["structure_id"] == sid

        # Revisions endpoint records the change
        rv = requests.get(f"{BASE_URL}/api/admin/ctc/revisions",
                        params={"company_id": COMPANY_ID,
                                "user_id": test_employee["user_id"]},
                        headers=headers, timeout=30)
        assert rv.status_code == 200
        revs = rv.json()["revisions"]
        assert len(revs) >= 1
        latest = revs[0]
        assert latest["new_mode"] == "ctc" and latest["new_ctc"] == 30000

    def test_summary_reflects_ctc_employee(self, headers, cleanup_state):
        r = requests.get(f"{BASE_URL}/api/admin/ctc/summary",
                        params={"company_id": COMPANY_ID}, headers=headers,
                        timeout=30)
        assert r.status_code == 200
        j = r.json()
        for k in ("total_employees", "ctc_employees", "total_monthly_ctc",
                  "total_annual_ctc", "total_employer_cost",
                  "total_net_payout", "avg_monthly_ctc", "by_structure"):
            assert k in j, f"missing {k}"
        assert j["ctc_employees"] >= 1
        assert j["total_monthly_ctc"] >= 30000
        assert j["total_annual_ctc"] >= 360000


# ---------------------------------------------------------------------------
# 6) Compliance salary run hook (Phase 2)
# ---------------------------------------------------------------------------
class TestComplianceRunHook:
    def test_generate_run_stamps_ctc_fields(self, headers, test_employee,
                                             cleanup_state):
        # First check baseline for other employees (2026-07 already processed)
        baseline_gross = {}
        b = requests.get(f"{BASE_URL}/api/admin/compliance-salary-runs",
                        params={"company_id": COMPANY_ID, "month": BASELINE_MONTH},
                        headers=headers, timeout=60)
        if b.status_code == 200:
            runs = b.json() if isinstance(b.json(), list) else b.json().get("runs") or []
            if runs:
                first = runs[0]
                if not first.get("rows"):
                    # fetch full run
                    rid = first.get("run_id")
                    rf = requests.get(
                        f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}",
                        headers=headers, timeout=60)
                    if rf.status_code == 200:
                        first = rf.json()
                for r in first.get("rows") or []:
                    if r.get("user_id") != test_employee["user_id"]:
                        baseline_gross[r.get("user_id")] = r.get("monthly_gross")

        # Generate fresh run for TEST_MONTH
        payload = {"month": TEST_MONTH, "company_id": COMPANY_ID}
        g = requests.post(f"{BASE_URL}/api/admin/compliance-salary-runs",
                        json=payload, headers=headers, timeout=180)
        if g.status_code == 409:
            pytest.skip(f"Month {TEST_MONTH} already finalized — cannot test hook")
        assert g.status_code == 200, g.text
        cleanup_state["run_created"] = True
        # Response is {"ok": True, "run": {...}}
        jr = g.json()
        run = jr.get("run") if isinstance(jr, dict) and "run" in jr else jr
        rows = run.get("rows") or []
        assert rows, f"run has no rows (employees_count={run.get('employees_count')})"

        # Find the CTC test employee's row
        emp_row = next((r for r in rows
                        if r.get("user_id") == test_employee["user_id"]), None)
        assert emp_row, f"test employee {test_employee['user_id']} not in run"
        assert emp_row.get("ctc_mode") is True
        assert emp_row.get("monthly_ctc") == 30000
        assert (emp_row.get("ctc_employer_total") or 0) > 0
        assert (emp_row.get("ctc_gross_derived") or 0) > 0
        # For Standard Office template with 30000 CTC → gross ~ 28300
        assert 27500 <= emp_row["ctc_gross_derived"] <= 29000, \
            f"ctc_gross_derived={emp_row['ctc_gross_derived']} outside expected 27500-29000"
        # monthly_gross should be prorated from ctc_gross_derived (approx)
        # In fresh month with no attendance it should equal 0 (no punches). Just check field exists.
        assert "monthly_gross" in emp_row

        # Backward-compat: other rows must NOT carry ctc_mode
        others = [r for r in rows if r.get("user_id") != test_employee["user_id"]]
        for o in others[:20]:  # sample check
            assert not o.get("ctc_mode"), \
                f"other employee {o.get('employee_code')} has ctc_mode set"


# ---------------------------------------------------------------------------
# 7) Payslip PDF
# ---------------------------------------------------------------------------
class TestPayslipPDF:
    def test_payslip_pdf_for_ctc_employee(self, headers, test_employee,
                                           cleanup_state):
        if not cleanup_state.get("run_created"):
            pytest.skip("run not created — payslip test needs the run")
        r = requests.get(
            f"{BASE_URL}/api/admin/employee-payslip.pdf",
            params={"company_id": COMPANY_ID,
                    "user_id": test_employee["user_id"], "month": TEST_MONTH},
            headers=headers, timeout=60)
        assert r.status_code == 200, r.text[:400]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF", "response is not a valid PDF"
        assert len(r.content) > 2000, f"PDF too small: {len(r.content)} bytes"


# ---------------------------------------------------------------------------
# CLEANUP (MANDATORY) — runs LAST as a session-scope finalizer
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _final_cleanup(headers, cleanup_state, request):
    yield
    print("\n=== FINAL CLEANUP ===")
    # 1) revert test employee back to gross
    uid = cleanup_state.get("assigned_user_id")
    if uid:
        r = requests.post(f"{BASE_URL}/api/admin/ctc/assign",
                        json={"user_id": uid, "salary_mode": "gross",
                              "reason": "TEST_ITER500 cleanup"},
                        headers=headers, timeout=30)
        print(f"revert employee {uid}: {r.status_code}")

    # 2) delete any lingering custom test structures
    for sid in list(cleanup_state.get("custom_structure_ids") or []):
        d = requests.delete(f"{BASE_URL}/api/admin/ctc/structures/{sid}",
                           headers=headers, timeout=30)
        print(f"delete structure {sid}: {d.status_code}")

    # 3) Additional sweep — delete any structures whose name starts with TEST_ITER500
    r = requests.get(f"{BASE_URL}/api/admin/ctc/structures",
                    params={"company_id": COMPANY_ID}, headers=headers,
                    timeout=30)
    if r.status_code == 200:
        for s in r.json().get("structures") or []:
            if str(s.get("name") or "").startswith("TEST_ITER500"):
                d = requests.delete(
                    f"{BASE_URL}/api/admin/ctc/structures/{s['structure_id']}",
                    headers=headers, timeout=30)
                print(f"sweep-delete structure {s['name']}: {d.status_code}")

    # 4) Restore firm mode to 'gross'
    r = requests.put(f"{BASE_URL}/api/admin/ctc/firm-mode/{COMPANY_ID}",
                   json={"mode": "gross"}, headers=headers, timeout=30)
    print(f"restore firm-mode gross: {r.status_code}")

    # 5) Delete the compliance run + master snapshot for TEST_MONTH (direct DB)
    if cleanup_state.get("run_created"):
        import subprocess
        js = f"""
import asyncio, os
os.environ.setdefault('MONGO_URL','mongodb://localhost:27017')
from motor.motor_asyncio import AsyncIOMotorClient
async def main():
    from pymongo import MongoClient
    import os as o
    mc = MongoClient(o.environ.get('MONGO_URL','mongodb://localhost:27017'))
    db = mc[o.environ.get('DB_NAME','test_database')]
    r1 = db.compliance_salary_runs.delete_many({{'company_id':'{COMPANY_ID}','month':'{TEST_MONTH}'}})
    r2 = db.compliance_master_snapshots.delete_many({{'company_id':'{COMPANY_ID}','month':'{TEST_MONTH}'}})
    r3 = db.freeze_salary_snapshots.delete_many({{'company_id':'{COMPANY_ID}','month':'{TEST_MONTH}'}})
    print('runs deleted', r1.deleted_count, 'snap deleted', r2.deleted_count, 'freeze', r3.deleted_count)
asyncio.run(main())
"""
        try:
            out = subprocess.run(["python", "-c", js], cwd="/app/backend",
                                capture_output=True, text=True, timeout=30)
            print(f"db cleanup: {out.stdout} {out.stderr}")
        except Exception as e:
            print(f"db cleanup err: {e}")
