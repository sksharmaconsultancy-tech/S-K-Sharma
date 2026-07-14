"""Seed test employees into the SKSCO1 company for pytest coverage.

Creates 5 employees with a mix of DOJ values so the DOJ + month-complete
tests have real data to exercise:
  - 3 with DOJ in the past (2024-01, 2024-06, 2025-01)
  - 1 with DOJ in the far future (2028-01-01) — used by the pre-DOJ test
  - 1 mid-2026 for edge cases

Idempotent: existing users with the same employee_code are left alone.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

EMPLOYEES = [
    {"code": "SK-EMP-001", "name": "Ramesh Kumar",    "doj": "2024-01-15", "salary": 25000},
    {"code": "SK-EMP-002", "name": "Sunita Sharma",   "doj": "2024-06-01", "salary": 32000},
    {"code": "SK-EMP-003", "name": "Vinod Verma",     "doj": "2025-01-10", "salary": 45000},
    {"code": "SK-EMP-004", "name": "Priya Iyer",      "doj": "2026-04-01", "salary": 55000},
    {"code": "SK-EMP-005", "name": "Future Employee", "doj": "2028-01-01", "salary": 60000},
]


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    c = await db.companies.find_one(
        {"$or": [{"company_code": "SKSCO1"}, {"code": "SKSCO1"}]},
        {"_id": 0, "company_id": 1, "name": 1},
    )
    if not c:
        print("SKSCO1 company not found — skipping seed.")
        return
    cid = c["company_id"]
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for e in EMPLOYEES:
        existing = await db.users.find_one(
            {"company_id": cid, "employee_code": e["code"]},
            {"_id": 0, "user_id": 1},
        )
        if existing:
            continue
        doc = {
            "user_id": f"usr_{uuid.uuid4().hex[:12]}",
            "role": "employee",
            "company_id": cid,
            "employee_code": e["code"],
            "name": e["name"],
            "doj": e["doj"],
            "salary_monthly": e["salary"],
            "onboarded": True,
            "approval_status": "approved",
            "created_at": now,
            "created_by": "seed_iter58",
            "is_onroll": True,
            "employee_type": "Staff",
        }
        await db.users.insert_one(doc)
        inserted += 1
    total = await db.users.count_documents({"company_id": cid, "role": "employee"})
    print(f"Seeded {inserted} new employees into {c['name']} (cid={cid}). Total now: {total}.")


if __name__ == "__main__":
    asyncio.run(main())
