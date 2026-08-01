"""Live check — ZKTeco ADMS/iClock SDK. Simulates a real ZKTeco device
(SN JYK8240100297, Kankani 'Test Gate') doing the full protocol lifecycle
against the running backend, then verifies DB side-effects and cleans up."""
import os
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") + "/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]

SN = "JYK8240100297"
BIO = "72"            # employee code 50 — SURENDRA SINGH
TODAY = datetime.now().strftime("%Y-%m-%d")
TS = f"{TODAY} 09:01:07"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name} {detail}")


# 1) Handshake — device announces itself
r = requests.get(f"{BASE}/iclock/cdata", params={"SN": SN, "options": "all", "pushver": "2.4.1"}, timeout=20)
check("1. Handshake GET /iclock/cdata", r.status_code == 200 and f"GET OPTION FROM: {SN}" in r.text
      and "Realtime=1" in r.text and "TimeZone=" in r.text, f"→ {r.text.splitlines()[:2]}")

# 2) Heartbeat / command poll
r = requests.get(f"{BASE}/iclock/getrequest", params={"SN": SN, "INFO": "Ver 6.60,10,0,125,192.168.1.20"}, timeout=20)
check("2. Heartbeat GET /iclock/getrequest", r.status_code == 200 and r.text.strip().startswith(("OK", "C:")),
      f"→ {r.text.strip()!r}")

# 3) ATTLOG push — one fingerprint punch for bio 72
line = f"{BIO}\t{TS}\t0\t1\t0\t0"
r = requests.post(f"{BASE}/iclock/cdata", params={"SN": SN, "table": "ATTLOG", "Stamp": "9999"},
                  data=line.encode(), timeout=20)
check("3. ATTLOG push ingested", r.status_code == 200 and r.text.strip() == "OK: 1", f"→ {r.text.strip()!r}")

rec = db.attendance.find_one({"device_serial": SN, "at": f"{TODAY}T09:01:07+00:00"})
# NOTE: bio 72 = SURENDRA SINGH who is CONTRACTUAL → machine punches are
# correctly demoted to "pending" (Contractor Punch Approvals, Iter 175).
ok_status = rec and (rec["status"] == "approved" or
                     (rec["status"] == "pending" and rec.get("pending_reason") == "contractual_employee"))
check("4. Punch stored in attendance", bool(rec) and rec["source"] == f"zkteco:{SN}" and ok_status and rec["user_id"],
      f"→ user={rec and rec.get('user_id')} kind={rec and rec.get('kind')} status={rec and rec.get('status')} ({rec and rec.get('pending_reason')})")

# 5) Duplicate replay — device retries the same block → must NOT duplicate
r = requests.post(f"{BASE}/iclock/cdata", params={"SN": SN, "table": "ATTLOG"}, data=line.encode(), timeout=20)
n = db.attendance.count_documents({"device_serial": SN, "at": f"{TODAY}T09:01:07+00:00"})
check("5. Duplicate replay idempotent", r.text.strip() == "OK: 0" and n == 1, f"→ {r.text.strip()!r}, rows={n}")

# 6) Unmapped bio code → parked for admin mapping, not ingested
r = requests.post(f"{BASE}/iclock/cdata", params={"SN": SN, "table": "ATTLOG"},
                  data=f"99999\t{TODAY} 09:02:00\t0\t1\t0\t0".encode(), timeout=20)
um = db.biometric_unmapped.find_one({"device_serial": SN, "device_user_id": "99999"})
check("6. Unmapped punch parked", r.text.strip() == "OK: 0" and bool(um), f"→ {r.text.strip()!r}")

# 7) OPERLOG push accepted + logged
r = requests.post(f"{BASE}/iclock/cdata", params={"SN": SN, "table": "OPERLOG"},
                  data=b"OPLOG 4\t2\t2026-06-01 09:00:00\t0\t0\t0\t0", timeout=20)
check("7. OPERLOG push accepted", r.status_code == 200 and r.text.strip().startswith("OK"))

# 8) Device heartbeat fields updated → shows ONLINE in the portal
d = db.biometric_devices.find_one({"serial_number": SN})
seen = d.get("last_seen_at", "")
check("8. Device marked online (last_seen_at fresh)", seen.startswith(datetime.utcnow().strftime("%Y-%m-%d")),
      f"→ last_seen_at={seen} pushes={d.get('total_pushes')} ingested={d.get('total_punches_ingested')}")

# ---- cleanup test data ----
db.attendance.delete_many({"device_serial": SN, "date": TODAY})
db.biometric_unmapped.delete_many({"device_serial": SN, "device_user_id": "99999"})
db.biometric_operlog.delete_many({"device_serial": SN})
print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed — cleanup done")
sys.exit(1 if FAIL else 0)
