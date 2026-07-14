"""Seed ephemeral data for iteration_33_flows E2E tests.

Creates:
  - 1 throwaway company (company_code IF33)
  - 1 company_admin (email + session token)
  - 1 employee with join_date=2025-11-01, 22 IN punches on Nov 2025 (Mon-Sat)
  - 1 session for the employee

Prints IDs/tokens as JSON for the Playwright script to consume.
Cleanup uses the same file after tests via `python iter33_flows_seed.py --cleanup <tag>`.
"""
import os, sys, json, uuid
from datetime import datetime, timezone
from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


def main():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]

    if len(sys.argv) > 1 and sys.argv[1] == "--cleanup":
        tag = sys.argv[2]
        n_att = db.attendance.delete_many({"record_id": {"$regex": f"^att_{tag}_"}}).deleted_count
        n_sess = db.user_sessions.delete_many({"session_token": {"$regex": f"^tk_{tag}_"}}).deleted_count
        n_usr = db.users.delete_many({"user_id": {"$regex": f"^user_{tag}_"}}).deleted_count
        n_co = db.companies.delete_many({"company_id": {"$regex": f"^co_{tag}_"}}).deleted_count
        print(json.dumps({"deleted": {"attendance": n_att, "sessions": n_sess, "users": n_usr, "companies": n_co}}))
        return

    tag = f"if33f{uuid.uuid4().hex[:5]}"
    now = datetime.now(timezone.utc).isoformat()

    # Company
    company_id = f"co_{tag}_{uuid.uuid4().hex[:6]}"
    db.companies.insert_one({
        "company_id": company_id,
        "name": f"IT33-Flows Co {tag}",
        "address": "Preview Test",
        "city": "Delhi", "state": "DL",
        "office_lat": 28.6139, "office_lng": 77.209,
        "geofence_radius_m": 200,
        "company_code": f"F{tag[-4:].upper()}",
        "compliance_enabled": True,
        "created_at": now,
    })

    # Company admin (with email to test self recipient)
    admin_id = f"user_{tag}_ca_{uuid.uuid4().hex[:5]}"
    db.users.insert_one({
        "user_id": admin_id,
        "email": f"admin_{tag}@test.local",
        "phone": f"+91{9800000000 + (uuid.uuid4().int % 10000000):010d}",
        "name": f"IT33F CoAdmin {tag}",
        "role": "company_admin",
        "company_id": company_id,
        "onboarded": True,
        "approval_status": "approved",
        "pin_must_change": False,
        "created_at": now,
    })
    admin_tok = f"tk_{tag}_ca_{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": admin_tok,
        "user_id": admin_id,
        "expires_at": "2099-12-31T00:00:00+00:00",
        "created_at": now,
        "auth_method": "test",
    })

    # Employee
    emp_id = f"user_{tag}_e_{uuid.uuid4().hex[:5]}"
    db.users.insert_one({
        "user_id": emp_id,
        "email": f"emp_{tag}@test.local",
        "phone": f"+91{9700000000 + (uuid.uuid4().int % 10000000):010d}",
        "name": f"IT33F Employee {tag}",
        "role": "employee",
        "company_id": company_id,
        "employee_code": f"F{tag[-4:].upper()}0001",
        "join_date": "2025-11-01",
        "employee_policy": {"salary": 0, "salary_1": 0, "day_1": 0, "policy_confirmed": False},
        "salary_monthly": 0,
        "onboarded": True,
        "approval_status": "approved",
        "pin_must_change": False,
        "created_at": now,
    })
    emp_tok = f"tk_{tag}_e_{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": emp_tok,
        "user_id": emp_id,
        "expires_at": "2099-12-31T00:00:00+00:00",
        "created_at": now,
        "auth_method": "test",
    })

    # 22 IN punches on Nov 2025 (Mon-Sat only; Sundays 2,9,16,23,30)
    sundays = {2, 9, 16, 23, 30}
    chosen = [d for d in range(1, 31) if d not in sundays][:22]
    for d in chosen:
        db.attendance.insert_one({
            "record_id": f"att_{tag}_{uuid.uuid4().hex[:10]}",
            "user_id": emp_id,
            "date": f"2025-11-{d:02d}",
            "kind": "in",
            "at": f"2025-11-{d:02d}T09:00:00+00:00",
            "source": "manual",
        })

    print(json.dumps({
        "tag": tag,
        "company_id": company_id,
        "admin_id": admin_id,
        "admin_token": admin_tok,
        "employee_id": emp_id,
        "employee_token": emp_tok,
    }))


if __name__ == "__main__":
    main()
