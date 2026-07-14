"""Seed ephemeral super_admin + employee sessions for iter32b UI retest.
Does NOT touch the real super_admin (sksharmaconsultancy@gmail.com) — creates a
throwaway user with role=super_admin plus a matching user_sessions row.
Prints JSON with tokens/ids to stdout so the playwright test can consume it.
"""
import json
import os
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://emplo-connect-1.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
_mc = MongoClient(MONGO_URL)
db = _mc[DB_NAME]

RUN_ID = f"IT32B{uuid.uuid4().hex[:4]}"
PHONE_STAMP = f"{int(uuid.uuid4().hex[:6], 16) % 100000:05d}"

prefix = f"UB{RUN_ID[-4:]}".upper()[:8]
cid = f"cmp_{uuid.uuid4().hex[:10]}"
now = datetime.now(timezone.utc).isoformat()

# Company (used for the employee)
db.companies.insert_one({
    "company_id": cid, "company_code": prefix, "name": f"{RUN_ID} FE Co",
    "created_at": now,
    "office_lat": 28.6139, "office_lng": 77.2090, "geofence_radius_m": 200,
})

# Employee via public signup + PIN login
phone_e = f"+919{PHONE_STAMP}0001"
r = requests.post(f"{API}/auth/employee-signup", json={
    "phone": phone_e, "pin": "111222", "company_code": prefix,
    "name": f"{RUN_ID} EmpFE",
})
assert r.status_code == 200, r.text
uid_e = r.json()["user_id"]
db.users.update_one({"user_id": uid_e}, {"$set": {"approval_status": "approved"}})
r = requests.post(f"{API}/auth/pin-login", json={"phone": phone_e, "pin": "111222"})
assert r.status_code == 200, r.text
tok_e = r.json()["session_token"]

# Throwaway super_admin (mongo-seeded — REAL super_admin doc untouched)
sa_uid = f"usr_{uuid.uuid4().hex[:10]}"
db.users.insert_one({
    "user_id": sa_uid,
    "role": "super_admin",
    "name": f"{RUN_ID} SAFake",
    "email": f"{RUN_ID.lower()}_sa@test.local",
    "approval_status": "approved",
    "onboarded": True,
    "pin_must_change": False,
    "created_at": now,
})
sa_tok = f"tok_{uuid.uuid4().hex}"
db.user_sessions.insert_one({
    "session_token": sa_tok,
    "user_id": sa_uid,
    "role": "super_admin",
    "auth_method": "test_seed_iter32b_ui",
    "created_at": now,
    "expires_at": datetime.now(timezone.utc).replace(year=2099).isoformat(),
})

print(json.dumps({
    "run_id": RUN_ID, "prefix": prefix, "cid": cid,
    "uid_e": uid_e, "tok_e": tok_e, "phone_e": phone_e,
    "sa_uid": sa_uid, "sa_tok": sa_tok,
}))
