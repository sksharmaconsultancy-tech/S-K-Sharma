#!/bin/bash
# S.K. Sharma & Co. — ATTENDANCE DIAGNOSTIC (Iter 488)
# Read-only: prints raw punch data so we can see WHY days show "missing OUT".
# Usage on the VPS:
#   bash diag488.sh                # scans ALL firms, current month
#   bash diag488.sh RANJAN         # firms whose name contains RANJAN
#   bash diag488.sh RANJAN 2026-08 # specific month
set -e
APP_DIR=/home/sksharma/app
PY=$APP_DIR/backend/venv/bin/python
export DIAG_NAME_PATTERN="${1:-}"
export DIAG_MONTH="${2:-}"

$PY - <<'PYEOF'
import asyncio, os, re, sys
from collections import Counter, defaultdict
from datetime import date, datetime

sys.path.insert(0, "/home/sksharma/app/backend")
from dotenv import load_dotenv
load_dotenv("/home/sksharma/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient

PAT = os.environ.get("DIAG_NAME_PATTERN") or ""
MONTH = os.environ.get("DIAG_MONTH") or date.today().strftime("%Y-%m")


async def main():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]
    q = {}
    if PAT:
        q["name"] = {"$regex": re.escape(PAT), "$options": "i"}
    comps = await db.companies.find(q, {"_id": 0, "company_id": 1, "name": 1}).to_list(50)
    print(f"=== DIAG 488 — month {MONTH} — {len(comps)} firm(s) ===")
    lo, hi = f"{MONTH}-01", f"{MONTH}-31"
    for c in comps:
        cid = c["company_id"]
        n_pun = await db.attendance.count_documents(
            {"company_id": cid, "date": {"$gte": lo, "$lte": hi}})
        if not n_pun and PAT == "":
            continue  # skip firms with no punches this month in all-firms mode
        print(f"\n########## FIRM: {c['name']} ({cid}) — {n_pun} punches in {MONTH}")

        # --- 1. Devices: config + when they LAST pushed ---------------------
        print("--- DEVICES ---")
        async for d in db.biometric_devices.find({"company_id": cid}, {"_id": 0}):
            print(f"  {d.get('name')!r} SN={d.get('serial_number')} kind={d.get('kind')} "
                  f"enabled={d.get('enabled', True)} last_seen={d.get('last_seen_at')} "
                  f"last_push={d.get('last_push_at')} last_table={d.get('last_push_table')}")

        # --- 2. Per-day per-device punch counts (spot a device going silent)
        print("--- PUNCHES PER DAY PER DEVICE/SOURCE (kind breakdown, ALL statuses) ---")
        agg = defaultdict(Counter)
        stat = defaultdict(Counter)
        async for p in db.attendance.find(
                {"company_id": cid, "date": {"$gte": lo, "$lte": hi}},
                {"_id": 0, "date": 1, "kind": 1, "source": 1, "status": 1}):
            src = (p.get("source") or "?").split(":")[-1][-8:]
            agg[(p["date"], src)][p.get("kind") or "?"] += 1
            stat[p["date"]][p.get("status") or "?"] += 1
        for (dt_, src), kc in sorted(agg.items()):
            print(f"  {dt_} src=…{src:<10} " + "  ".join(f"{k}={v}" for k, v in sorted(kc.items())))
        print("--- STATUS PER DAY ---")
        for dt_, sc in sorted(stat.items()):
            print(f"  {dt_}: " + "  ".join(f"{k}={v}" for k, v in sorted(sc.items())))

        # --- 3. Single-punch days count -------------------------------------
        per = Counter()
        async for p in db.attendance.find(
                {"company_id": cid, "date": {"$gte": lo, "$lte": hi}, "status": "approved"},
                {"_id": 0, "user_id": 1, "date": 1}):
            per[(p["user_id"], p["date"])] += 1
        singles = Counter()
        for (u, dt_), n in per.items():
            if n == 1:
                singles[dt_] += 1
        print("--- EMPLOYEES WITH EXACTLY 1 APPROVED PUNCH (per day) ---")
        for dt_, n in sorted(singles.items()):
            print(f"  {dt_}: {n} employee(s) single-punch")

        # --- 4. Raw rows for the screenshot employees -----------------------
        NAMES = ["BADAM DEVI", "AMIT CHAUDHARY", "ABHISHEK KUCHBANDA",
                 "ASHISH GUPTA", "ANIL KUMAR BHAMBI", "AJIT JHA", "ABHISHEK RATHI"]
        for nm in NAMES:
            u = await db.users.find_one(
                {"company_id": cid, "name": {"$regex": f"^{re.escape(nm)}", "$options": "i"}},
                {"_id": 0, "user_id": 1, "name": 1, "bio_code": 1, "employee_code": 1})
            if not u:
                continue
            print(f"--- RAW PUNCHES: {u['name']} (bio={u.get('bio_code')}, code={u.get('employee_code')}) ---")
            async for p in db.attendance.find(
                    {"user_id": u["user_id"], "date": {"$gte": lo, "$lte": hi}},
                    {"_id": 0, "date": 1, "at": 1, "kind": 1, "status": 1,
                     "source": 1, "device_serial": 1, "pending_reason": 1}).sort("at", 1):
            # keep each row on one line for easy pasting back
                print(f"  {p['date']} at={p.get('at','')[11:19]} kind={p.get('kind'):<4} "
                      f"status={p.get('status'):<9} src={p.get('source')} "
                      f"{('pending:' + str(p.get('pending_reason'))) if p.get('pending_reason') else ''}")

        # --- 5. Unmapped bio codes seen this month ---------------------------
        um = Counter()
        async for x in db.biometric_unmapped.find(
                {"seen_at": {"$gte": lo}}, {"_id": 0, "device_user_id": 1}):
            um[x.get("device_user_id")] += 1
        if um:
            print("--- UNMAPPED DEVICE USER IDS (punches that matched NO employee) ---")
            for k, v in um.most_common(20):
                print(f"  device_user_id={k}: {v} punch(es) DROPPED")

    print("\n=== END DIAG — paste this whole output back to the agent ===")

asyncio.run(main())
PYEOF
