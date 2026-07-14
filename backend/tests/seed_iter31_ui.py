"""Seed ephemeral company + employee + company_admin for iter31 UI test.
Prints JSON with tokens/ids to stdout so the playwright test can consume it.
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
_mc = MongoClient(MONGO_URL)
db = _mc[DB_NAME]

RUN_ID = f"IT31UI{uuid.uuid4().hex[:4]}"
PHONE_STAMP = f"{int(uuid.uuid4().hex[:6], 16) % 100000:05d}"

prefix = f"UI{RUN_ID[-4:]}".upper()[:8]
cid = f"cmp_{uuid.uuid4().hex[:10]}"
now = datetime.now(timezone.utc).isoformat()
db.companies.insert_one({
    "company_id": cid, "company_code": prefix, "name": f"{RUN_ID} FE Co",
    "created_at": now,
})

# Employee via signup
phone_e = f"+919{PHONE_STAMP}0001"
r = requests.post(f"{API}/auth/employee-signup", json={
    "phone": phone_e, "pin": "111222", "company_code": prefix,
    "name": f"{RUN_ID} EmpFE",
})
assert r.status_code == 200, r.text
uid_e = r.json()["user_id"]
db.users.update_one({"user_id": uid_e}, {"$set": {
    "father_name": "OldFatherFE", "dob": "1990-01-15", "doj": "2020-06-01",
    "approval_status": "approved",
}})
r = requests.post(f"{API}/auth/pin-login", json={"phone": phone_e, "pin": "111222"})
assert r.status_code == 200, r.text
tok_e = r.json()["session_token"]

# Admin (mongo-seeded session)
adm_uid = f"usr_{uuid.uuid4().hex[:10]}"
db.users.insert_one({
    "user_id": adm_uid, "role": "company_admin", "company_id": cid,
    "name": f"{RUN_ID} AdmFE",
    "email": f"{RUN_ID.lower()}_adm@test.local",
    "approval_status": "approved", "onboarded": True, "created_at": now,
})
adm_tok = f"tok_{uuid.uuid4().hex}"
db.user_sessions.insert_one({
    "session_token": adm_tok, "user_id": adm_uid, "role": "company_admin",
    "auth_method": "test_seed_iter31_ui", "created_at": now,
    "expires_at": datetime.now(timezone.utc).replace(year=2099).isoformat(),
})

print(json.dumps({
    "run_id": RUN_ID, "prefix": prefix, "cid": cid,
    "uid_e": uid_e, "tok_e": tok_e, "phone_e": phone_e,
    "adm_uid": adm_uid, "adm_tok": adm_tok,
}))
