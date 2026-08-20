"""Iter 646 — imported sheet FOOD ALLOWANCE must land under its own head,
never OT (user bug: BMD STAFF import).

Scenario (NAVNEET SONI): master = basic 9983 + HRA 11964 (no food head);
sheet imports gross 29947 incl FOOD ALLOWANCES 8000, days 30/31.
OLD: diff 8000 → OT (ot_allowed) → wrong OT + ESIC. NEW: → FOOD ALLOWANCES.
"""
import asyncio
import sys

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

MONTH = "2026-07"
CID = "cmp_test_iter646"


async def cleanup(db):
    for col in ("companies", "firm_masters", "users", "compliance_salary_runs",
                "compliance_master_snapshots", "compliance_import_entries"):
        await getattr(db, col).delete_many({"company_id": CID})


async def main():
    import server  # noqa: F401
    from routes.compliance_salary_runs import (
        _create_compliance_salary_run_core, ComplianceSalaryRunCreate, db)

    await cleanup(db)
    await db.companies.insert_one({
        "company_id": CID, "name": "TEST FIRM 646", "active": True,
        "company_code": "T646"})
    await db.firm_masters.insert_one({
        "company_id": CID,
        "salary_process": {"online_salary": True, "ot_allowed": True},
        "allowances": {"HRA": True, "CONV.": True,
                       "FOOD ALLOWANCES": True, "OVER TIME": False},
        "deductions": {"PF": True, "ESI": True},
        "epf": {"applicable": True}, "esi": {"applicable": True},
        "updated_at": "x", "updated_by": "t"})
    await db.users.insert_one({
        "user_id": "u646", "role": "employee", "company_id": CID,
        "name": "NAVNEET TEST", "employee_type": "STAFF", "active": True,
        "status": "active", "compliance_basic": 9983,
        "compliance_salary_allowances": [{"head": "HRA", "amount": 11964}],
    })
    await db.compliance_import_entries.insert_one({
        "user_id": "u646", "company_id": CID, "month": MONTH,
        "present_days": 31, "gross_earning": 29947, "tds": 0,
        "other_less": 0, "ot_hours": 0,
        "custom_allowances": {"FOOD ALLOWANCES": 8000},
    })
    admin = {"user_id": "a", "role": "super_admin", "name": "A",
             "company_id": None}
    resp = await _create_compliance_salary_run_core(
        ComplianceSalaryRunCreate(month=MONTH, company_id=CID,
                                  use_imported_sheet=True, month_days=31),
        admin)
    row = resp["run"]["rows"][0]
    print(f"gross={row['gross_paid']} ot_pay={row['ot_pay']} "
          f"others={row['others']} heads={row.get('allowance_heads')} "
          f"alloc={row.get('difference_allocation_head')!r} "
          f"esic_base={row.get('esic_wage_base')} esic={row.get('esic_employee')}")

    assert abs(row["gross_paid"] - 29947) <= 1, row["gross_paid"]
    # 1. OT must be ZERO — food allowance no longer dumps into OT
    assert float(row.get("ot_pay") or 0) == 0, f"OT={row.get('ot_pay')}"
    # 2. FOOD ALLOWANCES shows under its own dynamic head column
    _fh = (row.get("allowance_heads") or {}).get("FOOD ALLOWANCES", 0)
    assert abs(_fh - 8000) <= 1, f"FOOD head={_fh}"
    assert "FOOD ALLOWANCES" in (row.get("allowance_head_labels") or [])
    # 3. Allocation label reflects the head allocation
    assert "Allowance" in str(row.get("difference_allocation_head")), \
        row.get("difference_allocation_head")
    # 4. Others bucket carries the amount internally (display remainder ≥ 0)
    assert float(row["others"]) >= _fh - 1, (row["others"], _fh)
    print("CASE 1 PASSED — food allowance → own column, OT = 0")

    await cleanup(db)
    print("ALL CHECKS PASSED ✅")


asyncio.run(main())
