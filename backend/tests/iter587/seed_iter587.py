"""Iter 587 UI test seed — creates sub_admin + session + test employee."""
import os, uuid, hashlib, sys
from datetime import datetime, timezone
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]

now = datetime.now(timezone.utc).isoformat()
SUB_ID = "user_test587sub"
EMP_ID = "user_test587emp"
SUB_TOKEN = "sub587tok_" + uuid.uuid4().hex[:10]

# 1) sub_admin
db.users.delete_many({"user_id": {"$in": [SUB_ID, EMP_ID]}})
db.users.insert_one({
    "user_id": SUB_ID,
    "role": "sub_admin",
    "email": "iter587sub@sksharma.co",
    "phone": "+919000587001",
    "name": "Iter587 SubAdmin",
    "sub_admin_company_scope": "restricted",
    "sub_admin_company_ids": ["cmp_527fecdd7c"],
    "sub_admin_permissions": [
        "employees:view", "employees:edit",
        "employees:read", "employees:write",  # backend authz uses read/write
        "salary_process:view", "salary_process:edit",
        "salary_process:read", "salary_process:write",
    ],
    "created_at": now,
    "iter587_test": True,
})

# 2) test employee
db.users.insert_one({
    "user_id": EMP_ID,
    "role": "employee",
    "employee_code": "IT587E1",
    "name": "Iter587 TestEmp",
    "email": "iter587emp@example.local",
    "phone": "+919000587002",
    "company_id": "cmp_527fecdd7c",
    "salary_monthly": 10000,
    "bank_account_number": "11223344556677",
    "bank_ifsc": "SBIN0000001",
    "created_at": now,
    "iter587_test": True,
})

# 3) session for sub_admin
db.user_sessions.delete_many({"session_token": SUB_TOKEN})
db.user_sessions.insert_one({
    "session_token": SUB_TOKEN,
    "user_id": SUB_ID,
    "created_at": now,
    "expires_at": "2099-01-01T00:00:00+00:00",
    "iter587_test": True,
})

print("SUB_ID", SUB_ID)
print("EMP_ID", EMP_ID)
print("SUB_TOKEN", SUB_TOKEN)
