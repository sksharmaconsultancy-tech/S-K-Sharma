"""Iter 657 — freeze-difference allocation to INCENTIVE head.

Rule (user-confirmed): positive freeze diff -> sheet per-head allowances
first, then OT (if firm allows OT + head enabled), then INCENTIVE (if the
INCENTIVE head is enabled in the Firm Master), else Other Allowances.
"""
import requests, sys, asyncio, os, copy
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient

BASE = "http://localhost:8001/api"
TOK = open("/tmp/tok.txt").read().strip()
H = {"Authorization": f"Bearer {TOK}"}
CID = "cmp_527fecdd7c"
UID = "user_44cd6f561da0"  # SURENDRA SINGH, emp code 50 (STAFF)

db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "hrms")]

async def setup(ot_allowed: bool):
    fm = await db.firm_masters.find_one({"company_id": CID})
    await db.firm_masters.update_one({"_id": fm["_id"]}, {"$set": {
        "salary_process.ot_allowed": ot_allowed,
        "salary_process.days_calc_method": "attendance",
        "allowances.INCENTIVE": True,
    }})
    await db.compliance_import_entries.delete_many({"user_id": UID, "month": "2026-06"})
    await db.compliance_import_entries.insert_one({
        "user_id": UID, "company_id": CID, "month": "2026-06",
        "name": "SURENDRA SINGH", "present_days": 26, "gross_earning": 25000.0,
    })
    return fm

async def cleanup(fm_backup):
    await db.firm_masters.replace_one({"_id": fm_backup["_id"]}, fm_backup)
    await db.compliance_import_entries.delete_many({"user_id": UID, "month": "2026-06"})

def process():
    r = requests.post(f"{BASE}/admin/compliance-salary-runs", json={
        "month": "2026-06", "company_id": CID, "employee_type": "STAFF",
        "month_days": 26, "use_imported_sheet": True, "fresh": True,
        "override_month_days": True,
    }, headers=H, timeout=120)
    if r.status_code != 200:
        print("process failed:", r.status_code, r.text[:300]); sys.exit(1)
    j = r.json()
    run = j.get("run") or j
    return run

def check(run, expect_head):
    row = next((x for x in run.get("rows", []) if x.get("user_id") == UID), None)
    if not row:
        print("row for test emp not found"); return False
    ah = row.get("allowance_heads") or {}
    print(f"  gross_paid={row.get('gross_paid')} imported={row.get('imported_gross')} "
          f"diff={row.get('difference')} alloc_head={row.get('difference_allocation_head')!r} "
          f"ot_pay={row.get('ot_pay')} INCENTIVE={ah.get('INCENTIVE')}")
    ok = row.get("difference_allocation_head") == expect_head
    if expect_head == "Incentive":
        ok = ok and (ah.get("INCENTIVE") or 0) > 0 and abs(row.get("gross_paid", 0) - 25000) < 1
    if expect_head == "Overtime":
        ok = ok and (row.get("ot_pay") or 0) > 0
    print(f"  [{'PASS' if ok else 'FAIL'}] expected {expect_head!r}")
    return ok

async def main():
    fm_backup = None
    created_runs = []
    ok_all = True
    try:
        # Case 1: OT OFF + INCENTIVE enabled -> Incentive
        fm_backup = copy.deepcopy(await db.firm_masters.find_one({"company_id": CID}))
        await setup(ot_allowed=False)
        run1 = process(); created_runs.append(run1.get("run_id"))
        print("CASE 1 — OT off, INCENTIVE on:")
        ok_all &= check(run1, "Incentive")
        # Case 2: OT ON -> Overtime (regression, OT wins first)
        await setup(ot_allowed=True)
        run2 = process(); created_runs.append(run2.get("run_id"))
        print("CASE 2 — OT on (OT first):")
        ok_all &= check(run2, "Overtime")
    finally:
        if fm_backup is not None:
            await cleanup(fm_backup)
        for rid in created_runs:
            if rid:
                await db.compliance_salary_runs.delete_one({"run_id": rid})
        print("cleanup done (firm master restored, import entry + test runs removed)")
    print("RESULT:", "ALL PASS" if ok_all else "FAILED")
    sys.exit(0 if ok_all else 1)

asyncio.run(main())
