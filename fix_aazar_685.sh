#!/bin/bash
# S.K. Sharma & Co. — DATA REPAIR (Iter 685)
# AAZAR DARAN DIGAMBER JAIN MANDIR TRUST: legacy import left YEARS of junk
# HRA/CONV/DA rows inside every employee's compliance salary structure —
# compliance_gross ballooned (e.g. ROSHAN JOSHI ₹14.2 lakh/month).
# User rule: this trust pays NO allowances — Compliance = Basic only.
#
# WHAT IT DOES (for the AAZAR firm ONLY):
#   * compliance_salary_allowances  → []          (junk cleared)
#   * salary_structure_compliance   → [Basic]      (rebuilt clean)
#   * compliance_gross              → = compliance_basic
#   * stale hra_amount / conv_amount / basic_amount overrides cleared
#   * FULL BACKUP of every old value → db.aazar_fix685_backup (restorable)
#   * Employees already clean are SKIPPED. Nothing else is touched.
#
# USAGE (on the VPS):
#   bash fix685.sh          ← DRY RUN (shows what would change, changes NOTHING)
#   bash fix685.sh apply    ← applies the repair (with backup)
#
# AFTER apply: open Compliance Salary → AAZAR → 2026-07 and press
# "Refresh Master" once — the frozen snapshot re-freezes from the clean
# master and the run reprocesses automatically.

MODE="${1:-dry}"

APP_DIR=/home/sksharma/app
PY=$APP_DIR/backend/venv/bin/python
[ -x "$PY" ] || PY=python3

MODE=$MODE $PY - << 'PYEOF'
import asyncio, os, json
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/home/sksharma/app/backend/.env")
load_dotenv("/app/backend/.env")

APPLY = os.environ.get("MODE") == "apply"
FIRM_PATTERN = "AAZAR"


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    comp = await db.companies.find_one(
        {"name": {"$regex": FIRM_PATTERN, "$options": "i"}}, {"_id": 0})
    if not comp:
        print("❌ AAZAR firm not found — nothing done.")
        return
    cid = comp["company_id"]
    print(f"FIRM: {comp.get('name')} ({cid})")
    print(f"MODE: {'APPLY (writing changes + backup)' if APPLY else 'DRY RUN (no changes)'}\n")

    now = datetime.now(timezone.utc).isoformat()
    changed = skipped = 0
    async for e in db.users.find({"company_id": cid, "role": "employee"}, {"_id": 0}):
        basic = float(e.get("compliance_basic") or 0)
        gross = float(e.get("compliance_gross") or 0)
        allows = e.get("compliance_salary_allowances") or []
        struct = e.get("salary_structure_compliance") or []
        extra_rows = [r for r in struct if isinstance(r, dict)
                      and not str(r.get("head") or "").strip().lower().startswith("basic")
                      and float(r.get("amount") or 0) > 0]
        junk_allow = [r for r in allows if isinstance(r, dict)
                      and float(r.get("amount") or 0) > 0]
        stale_amt = any(float(e.get(k) or 0) > 0 for k in
                        ("hra_amount", "conv_amount", "basic_amount"))
        dirty = bool(extra_rows or junk_allow or stale_amt
                     or (basic > 0 and round(gross) != round(basic)))
        if not dirty:
            skipped += 1
            continue
        changed += 1
        junk_total = sum(float(r.get("amount") or 0) for r in extra_rows)
        new_row = {"head": "Basic", "amount": round(basic, 2)}
        rt = str(e.get("compliance_salary_mode") or "").strip().lower()
        if rt in ("monthly", "daily", "hourly"):
            new_row["rate_type"] = rt
        print(f"  {e.get('name')} (code {e.get('employee_code')}): "
              f"gross ₹{gross:,.0f} → ₹{basic:,.0f}  "
              f"(junk rows: {len(extra_rows)}, junk total ₹{junk_total:,.0f})")
        if not APPLY:
            continue
        await db.aazar_fix685_backup.insert_one({
            "user_id": e.get("user_id"), "employee_code": e.get("employee_code"),
            "name": e.get("name"), "company_id": cid, "backed_up_at": now,
            "old": {k: e.get(k) for k in (
                "compliance_basic", "compliance_gross",
                "compliance_salary_allowances", "salary_structure_compliance",
                "hra_amount", "conv_amount", "basic_amount")},
        })
        await db.users.update_one({"user_id": e["user_id"]}, {"$set": {
            "compliance_salary_allowances": [],
            "salary_structure_compliance": [new_row] if basic > 0 else [],
            "compliance_gross": round(basic, 2),
            "hra_amount": None, "conv_amount": None, "basic_amount": None,
            "fix685_applied_at": now,
        }})

    print(f"\n{'✅ REPAIRED' if APPLY else '→ WOULD REPAIR'}: {changed} employee(s); "
          f"already clean: {skipped}")
    if APPLY:
        print("Backup saved in db.aazar_fix685_backup (old values kept).")
        print("\nNEXT STEP: open Compliance Salary → AAZAR → 2026-07 and press")
        print("'Refresh Master' once — grid will show clean Basic-only figures.")
    else:
        print("\nTo apply:  bash fix685.sh apply")

asyncio.run(main())
PYEOF
