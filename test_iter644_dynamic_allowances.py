"""Iter 644 — dynamic allowance columns + OT toggle.

User scenario: Firm has INCENTIVE ticked ON and OVER TIME ticked OFF.
Expected:
  * run rows carry allowance_head_labels == ["INCENTIVE"]
  * each row's allowance_heads / allowance_heads_master break INCENTIVE
    out of the Others bucket (display decomposition)
  * TOTALS UNCHANGED — gross/net/PF/ESIC identical to pre-644 behaviour
  * enabled_allowances does NOT contain "ot" (OVER TIME off) → OT columns
    hide on the sheet; with OVER TIME on it contains "ot"
  * exports: dynamic_csv_columns includes INCENTIVE and drops ot_pay;
    flatten subtracts INCENTIVE from others
"""
import asyncio
import sys

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

MONTH = "2026-07"
CID = "cmp_test_iter644"


async def cleanup(db):
    await db.companies.delete_many({"company_id": CID})
    await db.firm_masters.delete_many({"company_id": CID})
    await db.users.delete_many({"company_id": CID})
    await db.compliance_salary_runs.delete_many({"company_id": CID})
    await db.compliance_master_snapshots.delete_many({"company_id": CID})


async def main():
    import server  # noqa: F401 — load app fully first (circular imports)
    from routes.compliance_salary_runs import (
        _create_compliance_salary_run_core, ComplianceSalaryRunCreate, db)
    from utils.compliance_salary import (
        dynamic_csv_columns, flatten_deduction_heads, round_export_rows)

    await cleanup(db)
    await db.companies.insert_one({
        "company_id": CID, "name": "TEST FIRM ITER644", "active": True})
    await db.firm_masters.insert_one({
        "company_id": CID,
        "salary_process": {"online_salary": True,
                           "days_calc_method": "fixed",
                           "days_calc_fixed": 26},
        "allowances": {"HRA": True, "CONV.": True, "INCENTIVE": True,
                       "OTHER MISC.ALLOWANCE": True, "OVER TIME": False},
        "deductions": {"PF": True, "ESI": True, "TDS": True},
        "epf": {"applicable": True}, "esi": {"applicable": True},
        "updated_at": "2026-06-01T00:00:00Z", "updated_by": "test",
    })
    await db.users.insert_one({
        "user_id": "user_test644", "role": "employee", "company_id": CID,
        "name": "Test Emp 644", "employee_type": "STAFF", "active": True,
        "status": "active", "compliance_basic": 9000,
        "compliance_salary_allowances": [
            {"head": "HRA", "amount": 3600},
            {"head": "INCENTIVE", "amount": 2000},
            {"head": "OTHER MISC.ALLOWANCE", "amount": 440},
        ],
    })
    admin = {"user_id": "user_admin_test", "role": "super_admin",
             "name": "Test Admin", "company_id": None}

    resp = await _create_compliance_salary_run_core(
        ComplianceSalaryRunCreate(month=MONTH, company_id=CID,
                                  month_days=26, present_days_all=26), admin)
    run = resp["run"]
    row = run["rows"][0]

    # ---- 1. labels + breakdown ----
    labels = row.get("allowance_head_labels")
    assert labels == ["INCENTIVE"], f"labels={labels}"
    ah, ahm = row.get("allowance_heads"), row.get("allowance_heads_master")
    print(f"labels={labels} heads_paid={ah} heads_master={ahm}")
    assert ahm.get("INCENTIVE") == 2000, f"master INCENTIVE={ahm}"
    assert abs(ah.get("INCENTIVE", 0) - 2000) <= 1, f"paid INCENTIVE={ah}"

    # ---- 2. totals unchanged: gross = 9000+3600+2000+440 = 15040 ----
    assert abs(row["gross_paid"] - 15040) <= 1, f"gross={row['gross_paid']}"
    # others bucket still CONTAINS incentive internally (display subtracts)
    assert row["others"] >= ah["INCENTIVE"], (row["others"], ah)
    print(f"gross={row['gross_paid']} others(full)={row['others']} "
          f"net={row['net']} pf={row['pf_employee']} esi={row['esic_employee']}")

    # ---- 3. OT excluded from enabled_allowances (OVER TIME off) ----
    en = row.get("enabled_allowances") or []
    assert "ot" not in en, f"enabled_allowances={en}"
    print(f"enabled_allowances={en} (no 'ot' → OT columns hidden)")

    # ---- 4. exports ----
    rows = run["rows"]
    cols = dynamic_csv_columns(rows)
    assert "INCENTIVE" in cols, cols
    assert "ot_pay" not in cols, "ot_pay should be dropped (OT off, no data)"
    flat = flatten_deduction_heads(round_export_rows(rows))
    f0 = flat[0]
    assert f0["INCENTIVE"] == ah["INCENTIVE"], f0.get("INCENTIVE")
    assert f0["others"] == round(row["others"]) - round(ah["INCENTIVE"]), \
        (f0["others"], row["others"])
    print(f"export cols OK (INCENTIVE in, ot_pay out); "
          f"export others={f0['others']} (remainder)")

    # ---- 5. OVER TIME ON → 'ot' lands in the mask ----
    await db.firm_masters.update_one(
        {"company_id": CID}, {"$set": {"allowances.OVER TIME": True}})
    await db.compliance_salary_runs.delete_many({"company_id": CID})
    resp2 = await _create_compliance_salary_run_core(
        ComplianceSalaryRunCreate(month=MONTH, company_id=CID,
                                  month_days=26, present_days_all=26), admin)
    en2 = resp2["run"]["rows"][0].get("enabled_allowances") or []
    assert "ot" in en2, en2
    print(f"OVER TIME on → enabled_allowances={en2} (OT columns shown)")

    await cleanup(db)
    print("ALL CHECKS PASSED ✅")


asyncio.run(main())
