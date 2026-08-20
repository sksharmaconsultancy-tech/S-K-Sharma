"""Iter 643 — Excel-import runs must use the Firm Master FIXED month days
(e.g. 26) instead of defaulting to calendar days (31) when no Month Days
override is typed.

Creates a throw-away test firm (+1 employee +1 import entry), runs the
compliance core with use_imported_sheet=True, asserts month_days == 26,
then cleans up. Also asserts a typed month_days still wins (Iter 616 rule).
"""
import asyncio
import sys

sys.path.insert(0, "/app/backend")

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

MONTH = "2026-07"  # July → 31 calendar days (the buggy default)
CID = "cmp_test_iter643"


async def main():
    import server  # load fully first to avoid circular import
    from routes.compliance_salary_runs import (
        _create_compliance_salary_run_core, ComplianceSalaryRunCreate, db)

    # ---- setup throw-away firm + employee + import entry ----
    await cleanup(db)
    await db.companies.insert_one({
        "company_id": CID, "name": "TEST FIRM ITER643", "active": True})
    await db.firm_masters.insert_one({
        "company_id": CID,
        "salary_process": {"online_salary": True,
                           "days_calc_method": "fixed",
                           "days_calc_fixed": 26},
        "updated_at": "2026-06-01T00:00:00Z", "updated_by": "test",
    })
    await db.users.insert_one({
        "user_id": "user_test643", "role": "employee", "company_id": CID,
        "name": "Test Emp 643", "employee_type": "STAFF", "active": True,
        "status": "active", "salary_mode": "monthly", "monthly_salary": 15500,
        "basic_salary": 15500,
    })
    await db.compliance_import_entries.insert_one({
        "user_id": "user_test643", "company_id": CID, "month": MONTH,
        "present_days": 26, "other_deduction": 0, "imported_gross": 15500,
    })
    admin = {"user_id": "user_admin_test", "role": "super_admin",
             "name": "Test Admin", "company_id": None}

    # ---- CASE 1: imported sheet, NO typed month days → firm fixed 26 ----
    resp = await _create_compliance_salary_run_core(
        ComplianceSalaryRunCreate(month=MONTH, company_id=CID,
                                  use_imported_sheet=True), admin)
    run = resp["run"]
    md = int(run["month_days"])
    assert md == 26, f"CASE1 FAILED: month_days={md}, expected 26 (firm fixed)"
    print(f"CASE 1 OK — imported sheet with no override → month_days={md} (firm fixed)")

    # PF divisor sanity: row PF should be based on ÷26, not ÷31
    row = run["rows"][0]
    print(f"   row: present={row.get('present_days')} gross_paid={row.get('gross_paid')} "
          f"pf_ee={row.get('pf_employee')}")

    # ---- CASE 2: imported sheet WITH typed days=30 → typed wins (616) ----
    await db.compliance_salary_runs.delete_many({"company_id": CID})
    resp2 = await _create_compliance_salary_run_core(
        ComplianceSalaryRunCreate(month=MONTH, company_id=CID,
                                  use_imported_sheet=True, month_days=30), admin)
    md2 = int(resp2["run"]["month_days"])
    assert md2 == 30, f"CASE2 FAILED: month_days={md2}, expected 30 (typed wins)"
    print(f"CASE 2 OK — imported sheet with typed 30 → month_days={md2} (typed wins)")

    # ---- CASE 3: prev run lock — reprocess keeps the same days ----
    resp3 = await _create_compliance_salary_run_core(
        ComplianceSalaryRunCreate(month=MONTH, company_id=CID,
                                  use_imported_sheet=True), admin)
    md3 = int(resp3["run"]["month_days"])
    assert md3 == 30, f"CASE3 FAILED: month_days={md3}, expected 30 (prev-run lock)"
    print(f"CASE 3 OK — reprocess without override keeps prev days → {md3}")

    await cleanup(db)
    print("ALL 3 CASES PASSED ✅")


async def cleanup(db):
    await db.companies.delete_many({"company_id": CID})
    await db.firm_masters.delete_many({"company_id": CID})
    await db.users.delete_many({"company_id": CID})
    await db.compliance_import_entries.delete_many({"company_id": CID})
    await db.compliance_salary_runs.delete_many({"company_id": CID})
    await db.compliance_master_snapshots.delete_many({"company_id": CID})


asyncio.run(main())
