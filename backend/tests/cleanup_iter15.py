"""Post-test cleanup for iter_15:
1. Delete test employee (+919999778866)
2. Delete test company (TEST_Iter15_Company)
3. Reset super admin PIN back to bcrypt('246810'), pin_must_change=True,
   pin_fail_count=0, pin_locked_until=None
4. Verify final admin-pin-login with 246810 returns 200
"""
import os
from pathlib import Path
import bcrypt
import requests
from pymongo import MongoClient

for p in [Path("/app/backend/.env"), Path("/app/frontend/.env")]:
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v.strip('"').strip("'"))

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")
client = MongoClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]

# 1. delete test employee
r1 = db.users.delete_many({"phone": "+919999778866"})
print(f"deleted test employees: {r1.deleted_count}")

# 2. delete test company
r2 = db.companies.delete_many({"name": "TEST_Iter15_Company"})
print(f"deleted test companies: {r2.deleted_count}")

# 3. reset super admin PIN to 246810
new_hash = bcrypt.hashpw(b"246810", bcrypt.gensalt()).decode()
res = db.users.update_one(
    {"email": "sksharmaconsultancy@gmail.com"},
    {"$set": {
        "pin_hash": new_hash,
        "pin_must_change": True,
        "pin_fail_count": 0,
        "pin_locked_until": None,
    }},
)
print(f"super admin PIN reset matched={res.matched_count}, modified={res.modified_count}")

# 4. verify login
r = requests.post(f"{BASE}/api/auth/admin-pin-login",
                  json={"identifier": "sksharmaconsultancy@gmail.com", "pin": "246810"})
print(f"final admin-pin-login: {r.status_code}")
assert r.status_code == 200, r.text
body = r.json()
print(f"pin_must_change flag = {body.get('pin_must_change')}")
assert body.get("pin_must_change") is True

client.close()
print("CLEANUP: OK")
