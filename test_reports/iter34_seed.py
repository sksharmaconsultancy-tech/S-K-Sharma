"""Seed a company_admin + employee for iter-34 frontend tests. Prints tokens."""
import json
import uuid
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

MONGO_URL = "mongodb://localhost:27017"
DB = "test_database"
TAG = f"IT34F{uuid.uuid4().hex[:6]}"

cli = MongoClient(MONGO_URL)
db = cli[DB]

now = datetime.now(timezone.utc)
exp = now + timedelta(hours=6)

c_id = f"cmp_{TAG}"
db.companies.insert_one({
    "company_id": c_id,
    "name": f"{TAG} Firm",
    "company_code": f"{TAG[:6]}",
    "office_lat": 12.9,
    "office_lng": 77.6,
    "geofence_radius_m": 200,
    "created_at": now.isoformat(),
})

users = [
    {"user_id": f"u_{TAG}_ca", "name": f"{TAG} CA", "role": "company_admin",
     "email": f"{TAG.lower()}_ca@test.local", "company_id": c_id,
     "employee_code": f"{TAG[:6]}0001", "created_at": now.isoformat()},
    {"user_id": f"u_{TAG}_emp", "name": f"{TAG} Emp", "role": "employee",
     "email": f"{TAG.lower()}_emp@test.local", "company_id": c_id,
     "employee_code": f"{TAG[:6]}0002", "created_at": now.isoformat()},
]
db.users.insert_many(users)

tokens = {}
for u in users:
    tok = f"tok_{TAG}_{u['user_id']}"
    tokens[u["user_id"]] = tok
    db.user_sessions.insert_one({
        "session_token": tok,
        "user_id": u["user_id"],
        "expires_at": exp,
        "created_at": now.isoformat(),
    })

print(json.dumps({
    "tag": TAG,
    "company_id": c_id,
    "ca_token": tokens[f"u_{TAG}_ca"],
    "emp_token": tokens[f"u_{TAG}_emp"],
    "ca_user_id": f"u_{TAG}_ca",
    "emp_user_id": f"u_{TAG}_emp",
}))
