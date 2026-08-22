#!/bin/bash
# S.K. Sharma & Co. — READ-ONLY diagnostic (Iter 685)
# Purpose: user bugs —
#   1. VIPUL ENTERPRISES: STIPHAN/SAHIL daily rate 300 but grid shows 16120
#   2. AAZAR DARAN: no HRA/CONV on master but M.HRA / M.Conv huge
# Prints the live Employee Master vs the FROZEN payroll snapshot + firm
# allowance config. CHANGES NOTHING.
#
# Run on the VPS:
#   wget -O diag685.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=diag685"
#   bash diag685.sh

APP_DIR=/home/sksharma/app
PY=$APP_DIR/backend/venv/bin/python
[ -x "$PY" ] || PY=python3

$PY - << 'PYEOF'
import asyncio, os, json
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/home/sksharma/app/backend/.env")
load_dotenv("/app/backend/.env")

FIRM_PATTERNS = ["VIPUL", "AAZAR"]
EMP_PATTERNS = ["STIPHAN", "SAHIL", "ROSHAN JOSHI", "MANJU DEVI",
                "SHASHI KALA", "RITESH KUMAR SEN", "SHANKARI KUMARI",
                "ASHA KHATIK", "ASHA KUMARI KOLI", "BAJRANG MALI",
                "GUNJAN RANI"]
MASTER_FIELDS = [
    "name", "employee_code", "employee_type", "doj",
    "compliance_salary_mode", "compliance_basic", "compliance_gross",
    "salary_structure_compliance", "compliance_salary_allowances",
    "basic_amount", "hra_amount", "conv_amount", "medical_amount",
    "special_amount", "others_amount", "structure_pct",
    "salary_mode", "salary_monthly", "salary_daily", "rate", "pf_basic",
    "salary_structure_actual",
]

def pick(d, fields):
    return {f: d.get(f) for f in fields if d.get(f) not in (None, "", [], {}, 0)}

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    for pat in FIRM_PATTERNS:
        comp = await db.companies.find_one({"name": {"$regex": pat, "$options": "i"}}, {"_id": 0})
        if not comp:
            print(f"\n=== FIRM '{pat}': NOT FOUND ===")
            continue
        cid = comp["company_id"]
        print(f"\n{'='*70}\n=== FIRM: {comp.get('name')} ({cid}) ===")
        fm = await db.firm_masters.find_one({"company_id": cid}, {"_id": 0})
        if fm:
            cat = fm.get("allowance_catalog") or fm.get("allowances") or []
            print("FIRM allowance catalog:", json.dumps(cat, default=str)[:400])
            print("FIRM salary_process:", json.dumps(fm.get("salary_process") or {}, default=str)[:300])
        cp = (comp.get("compliance_policy") or {})
        print("FIRM enabled_allowances:", cp.get("enabled_allowances"))

        # employee_policy salary (legacy leak check)
        emps = await db.users.find(
            {"company_id": cid, "role": "employee",
             "name": {"$regex": "|".join(EMP_PATTERNS), "$options": "i"}},
            {"_id": 0}).to_list(50)
        if not emps:  # fall back: first 10 employees of the firm
            emps = await db.users.find(
                {"company_id": cid, "role": "employee"}, {"_id": 0}).to_list(10)
        for e in emps:
            print(f"\n--- LIVE MASTER: {e.get('name')} (code {e.get('employee_code')}) ---")
            print(json.dumps(pick(e, MASTER_FIELDS), default=str, ensure_ascii=False)[:900])
            pol = e.get("employee_policy") or {}
            if pol.get("salary") or pol.get("salary_mode"):
                print("employee_policy leak:", {"salary": pol.get("salary"),
                                                "salary_mode": pol.get("salary_mode")})

        # Active frozen snapshots for 2026-07 (all scopes)
        print(f"\n--- FROZEN SNAPSHOTS (2026-07, active) for {comp.get('name')} ---")
        async for s in db.compliance_master_snapshots.find(
                {"company_id": cid, "month": "2026-07", "active": True}, {"_id": 0}):
            nm = (s.get("data") or {}).get("name")
            if any(p.lower() in str(nm or "").lower() for p in EMP_PATTERNS) or len(EMP_PATTERNS) == 0:
                print(f"v{s.get('version')} [{s.get('employee_type_key')}] {nm}:",
                      json.dumps(pick(s.get("data") or {}, MASTER_FIELDS),
                                 default=str, ensure_ascii=False)[:700])

        # Latest run rows for the reported employees
        run = await db.compliance_salary_runs.find_one(
            {"company_id": cid, "month": "2026-07"}, {"_id": 0, "run_id": 1,
             "rows": 1, "employee_type": 1, "month_days": 1},
            sort=[("generated_at", -1)])
        if run:
            print(f"\n--- RUN {run.get('run_id')} (scope {run.get('employee_type')},"
                  f" md {run.get('month_days')}) rows ---")
            for r in (run.get("rows") or []):
                if any(p.lower() in str(r.get("name") or "").lower() for p in EMP_PATTERNS):
                    print(r.get("name"), "|", json.dumps({
                        "mode": r.get("salary_mode"), "rate": r.get("rate"),
                        "M.Basic": r.get("basic_master"), "M.HRA": r.get("hra_master"),
                        "M.Conv": r.get("conveyance_master"), "M.Spl": r.get("special_master"),
                        "M.Others": r.get("others_master"), "M.Gross": r.get("gross_master"),
                    }, default=str))

asyncio.run(main())
PYEOF
echo ""
echo "════ Diagnostic complete — send the FULL output above. Nothing was changed. ════"
