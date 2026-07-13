#!/usr/bin/env python3
"""Iter 89 — Seed script to restore Kankani Enterprises with employees + punches.

Called via `python3 /app/backend/scripts/seed_kankani.py`.

Creates:
  - 1 firm: "Kankani Enterprises" (company_code=KEPS)
  - 1 company_admin user (email=admin@kankani.local, pin=1234)
  - 10 employees with realistic Indian names, salary structures, statutory numbers
  - Past 14 days of IN/OUT punches for each employee (skipping Sundays)

Safe to re-run: does nothing if the firm already exists.
"""
import asyncio
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
import bcrypt


IST = timezone(timedelta(hours=5, minutes=30))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


EMPLOYEES = [
    # (name, father_name, gender, dob, doj, employee_code, position, department, salary)
    ("Ramesh Kumar Sharma",   "Suresh Sharma",   "Male",   "15-06-1988", "01-04-2023", "KEPS0001", "Operator",         "Production",   22000),
    ("Suman Devi Kankani",    "Prakash Kankani", "Female", "22-11-1990", "15-05-2023", "KEPS0002", "Machine Attendant","Production",   18000),
    ("Vijay Singh Rajput",    "Ramnath Rajput",  "Male",   "05-03-1985", "10-01-2022", "KEPS0003", "Supervisor",       "Production",   32000),
    ("Anita Kumari",          "Manohar Lal",     "Female", "18-08-1992", "20-06-2023", "KEPS0004", "Accountant",       "Finance",      28000),
    ("Mahendra Prasad Meena", "Lal Chand Meena", "Male",   "10-01-1980", "05-04-2021", "KEPS0005", "Store Keeper",     "Stores",       24000),
    ("Priya Sharma",          "Anil Sharma",     "Female", "25-09-1995", "01-08-2023", "KEPS0006", "HR Executive",     "HR",           26000),
    ("Rakesh Verma",          "Om Prakash",      "Male",   "12-04-1987", "12-02-2022", "KEPS0007", "Loom Fitter",      "Production",   25000),
    ("Sunita Bai",            "Gopal Ram",       "Female", "30-07-1993", "18-10-2023", "KEPS0008", "Quality Checker",  "Quality",      20000),
    ("Deepak Jain",           "Kailash Jain",    "Male",   "08-12-1989", "22-03-2023", "KEPS0009", "Electrician",      "Maintenance",  27000),
    ("Kavita Sen",            "Rajkumar Sen",    "Female", "14-05-1991", "01-07-2023", "KEPS0010", "Packer",           "Dispatch",     17000),
]


async def main() -> None:
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # ------------------------------------------------------------------
    # 1. Skip if Kankani already exists
    # ------------------------------------------------------------------
    existing = await db.companies.find_one({"name": {"$regex": "Kankani", "$options": "i"}})
    if existing:
        print(f"⚠️  Kankani firm already exists ({existing['company_id']}) — nothing to do.")
        return

    # ------------------------------------------------------------------
    # 2. Create the firm
    # ------------------------------------------------------------------
    company_id = f"cmp_{uuid.uuid4().hex[:10]}"
    company_doc = {
        "company_id": company_id,
        "name": "Kankani Enterprises",
        "address": "Industrial Area, Bhilwara",
        "city": "Bhilwara",
        "state": "Rajasthan",
        "nature_of_business": "Textile Manufacturing",
        "business_category": "textile",
        "business_subcategory": "loom-weaving",
        "attendance_policy": {
            "workday_hours": 8,
            "half_day_hours": 4,
            "grace_minutes": 10,
            "weekly_off_days": [6],  # Sunday
        },
        "office_lat": 25.3463,
        "office_lng": 74.6408,
        "geofence_radius_m": 200,
        "company_code": "KEPS",
        "compliance_enabled": True,
        "created_at": now_iso(),
    }
    await db.companies.insert_one(company_doc)
    print(f"✅ Created firm: Kankani Enterprises → {company_id} (code=KEPS)")

    # ------------------------------------------------------------------
    # 3. Create company_admin
    # ------------------------------------------------------------------
    admin_id = f"user_{uuid.uuid4().hex[:12]}"
    admin_doc = {
        "user_id": admin_id,
        "email": "admin@kankani.local",
        "phone": "+919828100001",
        "name": "Prakash Kankani",
        "picture": None,
        "role": "company_admin",
        "company_id": company_id,
        "employee_code": "ADMIN",
        "position": "Company Admin",
        "onboarded": True,
        "approval_status": "approved",
        "has_pin": True,
        "pin_hash": hash_pin("1234"),
        "pin_must_change": False,
        "pin_set_at": now_iso(),
        "created_at": now_iso(),
    }
    await db.users.insert_one(admin_doc)
    print("✅ Created company_admin: admin@kankani.local (PIN=1234)")

    # ------------------------------------------------------------------
    # 4. Create 10 employees
    # ------------------------------------------------------------------
    employee_ids = []
    for idx, (name, father, gender, dob, doj, ecode, position, dept, salary) in enumerate(EMPLOYEES):
        emp_id = f"user_{uuid.uuid4().hex[:12]}"
        phone = f"+9198281{str(20001 + idx).zfill(5)}"
        uan = str(100000000000 + random.randint(1, 899999999999))[:12]
        esi = str(random.randint(1000000000, 9999999999))
        aadhaar = str(random.randint(100000000000, 999999999999))[:12]
        pan = f"ABCDE{random.randint(1000, 9999)}F"

        emp_doc = {
            "user_id": emp_id,
            "email": None,
            "phone": phone,
            "name": name,
            "father_name": father,
            "picture": None,
            "role": "employee",
            "company_id": company_id,
            "employee_code": ecode,
            "position": position,
            "designation": position,
            "department": dept,
            "gender": gender,
            "dob": dob,
            "doj": doj,
            "uan_no": uan,
            "esi_ip_no": esi,
            "aadhaar_no": aadhaar,
            "pan_no": pan,
            "salary_monthly": salary,
            "salary_structure_actual": [
                {"head": "Basic",  "amount": int(salary * 0.5)},
                {"head": "HRA",    "amount": int(salary * 0.2)},
                {"head": "CONV.",  "amount": int(salary * 0.1)},
                {"head": "OTHER",  "amount": int(salary * 0.2)},
            ],
            "onboarded": True,
            "approval_status": "approved",
            "has_pin": True,
            "pin_hash": hash_pin("1234"),
            "pin_must_change": False,
            "pin_set_at": now_iso(),
            "full_day_hrs": 8,
            "half_day_hrs": 4,
            "weekly_off_day": 6,  # Sunday
            "created_at": now_iso(),
        }
        await db.users.insert_one(emp_doc)
        employee_ids.append((emp_id, ecode, name))
    print(f"✅ Created {len(employee_ids)} employees")

    # ------------------------------------------------------------------
    # 5. Generate IN/OUT punches for past 14 days (skip Sundays)
    # ------------------------------------------------------------------
    punch_count = 0
    today = datetime.now(IST).date()
    for days_back in range(14, 0, -1):
        d = today - timedelta(days=days_back)
        if d.weekday() == 6:  # Sunday
            continue
        date_str = d.isoformat()

        for emp_id, ecode, name in employee_ids:
            # Slightly randomized IN time around 9:00-9:30
            in_hour = 9
            in_minute = random.randint(0, 45)
            # OUT time around 18:00-19:00
            out_hour = 18
            out_minute = random.randint(0, 55)
            # Randomly skip a day for ~5% of employee-days to simulate absents
            if random.random() < 0.05:
                continue

            in_dt = datetime(d.year, d.month, d.day, in_hour, in_minute, 0, tzinfo=IST)
            out_dt = datetime(d.year, d.month, d.day, out_hour, out_minute, 0, tzinfo=IST)

            # IN punch
            await db.attendance.insert_one({
                "record_id": f"att_{uuid.uuid4().hex[:12]}",
                "user_id": emp_id,
                "company_id": company_id,
                "kind": "in",
                "date": date_str,
                "at": in_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "original_at": in_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "latitude": 25.3463 + random.uniform(-0.001, 0.001),
                "longitude": 74.6408 + random.uniform(-0.001, 0.001),
                "distance_m": random.randint(5, 80),
                "source": "seed:kankani-restore",
                "outside_geofence": False,
                "status": "approved",
                "decision_by": "system:seed",
                "decision_at": now_iso(),
                "decision_reason": "Seed data",
                "selfie_base64": None,
            })
            # OUT punch
            await db.attendance.insert_one({
                "record_id": f"att_{uuid.uuid4().hex[:12]}",
                "user_id": emp_id,
                "company_id": company_id,
                "kind": "out",
                "date": date_str,
                "at": out_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "original_at": out_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "latitude": 25.3463 + random.uniform(-0.001, 0.001),
                "longitude": 74.6408 + random.uniform(-0.001, 0.001),
                "distance_m": random.randint(5, 80),
                "source": "seed:kankani-restore",
                "outside_geofence": False,
                "status": "approved",
                "decision_by": "system:seed",
                "decision_at": now_iso(),
                "decision_reason": "Seed data",
                "selfie_base64": None,
            })
            punch_count += 2
    print(f"✅ Created {punch_count} punches across {len(employee_ids)} employees over 14 days")

    client.close()
    print("\n🎉 Kankani Enterprises fully restored.")
    print("─" * 60)
    print("Firm      : Kankani Enterprises (KEPS)")
    print("Admin     : admin@kankani.local  |  PIN: 1234")
    print("Admin PIN : 1234  (Phone: +919828100001)")
    print("Employees : 10 (Ramesh, Suman, Vijay, Anita, Mahendra, Priya, Rakesh, Sunita, Deepak, Kavita)")
    print(f"Punches   : {punch_count} across last 14 working days")
    print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())
