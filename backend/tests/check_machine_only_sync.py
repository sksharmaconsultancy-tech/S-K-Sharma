"""Live E2E check — Iter 419 MACHINE-ONLY SYNC (no Employee Master needed).
Simulates: admin presses 'Sync Machines Only' → machine receives DATA QUERY
commands → machine uploads its USER rows + an FP template → worker distributes
users+templates to all machines. Cleans up after itself."""
import os
import sys
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]

SN = "JYK8240100297"
CID = "cmp_527fecdd7c"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name} {detail}")


tok = requests.post(f"{BASE}/auth/admin-password-login",
                    json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
                    timeout=20).json()["session_token"]
H = {"Authorization": f"Bearer {tok}"}

# 1) Start machine-only sync
r = requests.post(f"{BASE}/sync/machines", json={"company_id": CID}, headers=H, timeout=30)
j = r.json()
run_id = j.get("run_id")
check("1. POST /sync/machines starts run", r.status_code == 200 and run_id and "Employee Master is not required" in j["message"],
      f"→ {j.get('message','')[:80]}")

# 2) Machine polls → receives the 3 DATA QUERY harvest commands
r = requests.get(f"{BASE}/iclock/getrequest", params={"SN": SN}, timeout=20)
check("2. Machine receives harvest queries", "DATA QUERY USERINFO" in r.text and "DATA QUERY FINGERTMP" in r.text
      and "DATA QUERY BIODATA" in r.text, f"→ {len(r.text.splitlines())} cmd(s)")

# 3) Machine uploads its user db + one fingerprint template (OPERLOG push)
users_blob = ("USER PIN=901\tName=RAKESH MACHINE\tPri=0\tPasswd=\tCard=112233\tGrp=1\n"
              "USER PIN=902\tName=MEENA MACHINE\tPri=0\tPasswd=\tCard=\tGrp=1\n")
fp_blob = "FP PIN=901\tFID=6\tSize=40\tValid=1\tTMP=TESTTEMPLATEBASE64DATA901\n"
r1 = requests.post(f"{BASE}/iclock/cdata", params={"SN": SN, "table": "OPERLOG"}, data=users_blob.encode(), timeout=20)
r2 = requests.post(f"{BASE}/iclock/cdata", params={"SN": SN, "table": "OPERLOG"}, data=fp_blob.encode(), timeout=20)
mu = db.biometric_machine_users.count_documents({"company_id": CID, "pin": {"$in": ["901", "902"]}})
tp = db.biometric_templates.count_documents({"company_id": CID, "pin": "901", "kind": "fp"})
check("3. Machine users + FP captured", r1.ok and r2.ok and mu == 2 and tp == 1, f"→ users={mu} fp={tp}")

# 4) Force the distribute phase due NOW and wait for the 30s worker
db.machine_sync_runs.update_one({"run_id": run_id}, {"$set": {"distribute_at": "2020-01-01T00:00:00Z"}})
deadline = time.time() + 75
run = None
while time.time() < deadline:
    run = db.machine_sync_runs.find_one({"run_id": run_id})
    if run and run.get("phase") in ("done", "failed"):
        break
    time.sleep(5)
check("4. Worker distributes (phase=done)", bool(run) and run.get("phase") == "done",
      f"→ phase={run and run.get('phase')} queued={run and run.get('queued')} users={run and run.get('users')}")

# 5) USERINFO commands carry the MACHINE names (master never consulted)
cmd = db.biometric_device_cmds.find_one({"device_serial": SN, "status": "pending",
                                         "command": {"$regex": "PIN=901"}})
check("5. Distribute pushes machine-captured name", bool(cmd) and "RAKESH MACHINE" in (cmd or {}).get("command", "")
      and "Card=112233" in (cmd or {}).get("command", ""), f"→ {(cmd or {}).get('command','')[:70]}")

# 6) Origin-device template NOT re-pushed to itself (only 1 machine here)
tcmd = db.biometric_device_cmds.count_documents({"device_serial": SN, "status": "pending",
                                                 "command": {"$regex": "FINGERTMP"}})
check("6. Template skipped on origin machine", tcmd == 0, f"→ fingertmp cmds={tcmd}")

# 7) Status endpoint
r = requests.get(f"{BASE}/sync/machines/status", params={"company_id": CID}, headers=H, timeout=20)
check("7. GET /sync/machines/status", r.status_code == 200 and (r.json().get("run") or {}).get("run_id") == run_id)

# ---- cleanup ----
db.machine_sync_runs.delete_many({"company_id": CID})
db.biometric_machine_users.delete_many({"company_id": CID, "pin": {"$in": ["901", "902"]}})
db.biometric_templates.delete_many({"company_id": CID, "pin": "901"})
db.biometric_device_cmds.delete_many({"device_serial": SN, "status": {"$in": ["pending", "sent"]}})
db.biometric_operlog.delete_many({"device_serial": SN})
print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed — cleanup done")
sys.exit(1 if FAIL else 0)
