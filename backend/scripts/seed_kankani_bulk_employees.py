#!/usr/bin/env python3
"""Iter 89 — Bulk-seed additional Kankani employees for testing.

Adds N (default 45) employees with realistic Indian names, random
gender/DOB/DOJ, statutory numbers, salary structure, and 14 days of
IN/OUT punches. Safe to re-run: skips employee codes that already exist.
"""
import asyncio
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorClient
import bcrypt


IST = timezone(timedelta(hours=5, minutes=30))
COMPANY_ID = "cmp_527fecdd7c"  # Kankani Enterprises

# ---------------------------------------------------------------------------
# Random-yet-realistic Indian name banks. Split by gender so DOB/pronouns
# stay consistent with the generated payslips.
# ---------------------------------------------------------------------------
MALE_FIRST = [
    "Aakash", "Aarav", "Abhishek", "Aditya", "Ajay", "Amit", "Anil", "Ankit",
    "Arjun", "Ashok", "Deepak", "Dinesh", "Ganesh", "Gaurav", "Harish", "Hitesh",
    "Jitendra", "Karan", "Kishore", "Lokesh", "Manish", "Mohan", "Naveen", "Nikhil",
    "Pankaj", "Prakash", "Rahul", "Rajesh", "Ramesh", "Ravi", "Sachin", "Sandeep",
    "Sanjay", "Shyam", "Sunil", "Suresh", "Tarun", "Umesh", "Vijay", "Vikas",
]
FEMALE_FIRST = [
    "Aarti", "Anita", "Anjali", "Archana", "Deepika", "Divya", "Geeta", "Kavita",
    "Kiran", "Lakshmi", "Madhuri", "Manju", "Meena", "Neha", "Nisha", "Pooja",
    "Preeti", "Priya", "Rekha", "Renu", "Ritu", "Sangeeta", "Seema", "Shalini",
    "Shanti", "Sheela", "Shobha", "Sonia", "Sudha", "Sunita",
]
SURNAMES = [
    "Sharma", "Verma", "Gupta", "Agarwal", "Jain", "Meena", "Rajput", "Choudhary",
    "Yadav", "Prajapat", "Kumawat", "Rathore", "Soni", "Mehta", "Chauhan", "Purohit",
    "Bhati", "Singh", "Kankani", "Vaishnav", "Suthar", "Pareek", "Sen",
]
FATHER_FIRST_MALE = [
    "Ramnath", "Kailash", "Om Prakash", "Suresh", "Ram Lal", "Bhagwan Das",
    "Gopal", "Ganpat", "Lala Ram", "Chunni Lal", "Bhanwar Lal", "Prem Chand",
    "Devi Lal", "Ratan Lal", "Girdhari", "Mool Chand",
]

POSITIONS = [
    ("Operator",             "Production",   14000, 22000),
    ("Machine Attendant",    "Production",   13500, 20000),
    ("Senior Operator",      "Production",   22000, 30000),
    ("Loom Fitter",          "Production",   20000, 32000),
    ("Supervisor",           "Production",   28000, 42000),
    ("Quality Checker",      "Quality",      18000, 26000),
    ("Store Keeper",         "Stores",       20000, 28000),
    ("Store Assistant",      "Stores",       14000, 20000),
    ("Electrician",          "Maintenance",  22000, 30000),
    ("Maintenance Helper",   "Maintenance",  13000, 18000),
    ("Accountant",           "Finance",      25000, 40000),
    ("Accounts Assistant",   "Finance",      15000, 22000),
    ("HR Executive",         "HR",           22000, 30000),
    ("HR Assistant",         "HR",           16000, 22000),
    ("Driver",               "Admin",        14000, 20000),
    ("Peon",                 "Admin",        11000, 16000),
    ("Packer",               "Dispatch",     13000, 18000),
    ("Loader",               "Dispatch",     12000, 16000),
    ("Purchase Executive",   "Purchase",     20000, 28000),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def rand_dob(min_age: int = 22, max_age: int = 55) -> str:
    today = datetime.now(IST).date()
    age = random.randint(min_age, max_age)
    year = today.year - age
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return f"{day:02d}-{month:02d}-{year}"


def rand_doj_within(months_ago_min: int = 6, months_ago_max: int = 60) -> str:
    today = datetime.now(IST).date()
    months = random.randint(months_ago_min, months_ago_max)
    d = today - timedelta(days=months * 30)
    d = d.replace(day=random.randint(1, 28))
    return f"{d.day:02d}-{d.month:02d}-{d.year}"


async def create_employees(db, start_idx: int, count: int) -> list:
    """Create ``count`` employees with codes KEPS{start_idx:04d}..
    Returns a list of (user_id, employee_code, name) tuples."""
    made = []
    for i in range(count):
        idx = start_idx + i
        ecode = f"KEPS{idx:04d}"
        # Skip if this code already exists
        if await db.users.find_one({"employee_code": ecode, "company_id": COMPANY_ID}):
            print(f"  ! {ecode} already exists — skipping")
            continue

        gender = "Female" if random.random() < 0.28 else "Male"
        first = random.choice(FEMALE_FIRST if gender == "Female" else MALE_FIRST)
        surname = random.choice(SURNAMES)
        name = f"{first} {surname}"
        father = f"{random.choice(FATHER_FIRST_MALE)} {surname}"
        position, dept, min_sal, max_sal = random.choice(POSITIONS)
        salary = random.randint(min_sal // 500, max_sal // 500) * 500
        phone = f"+9198281{str(20000 + idx).zfill(5)}"
        uan = str(100000000000 + random.randint(1, 899999999999))[:12]
        esi = str(random.randint(1000000000, 9999999999))
        aadhaar = str(random.randint(100000000000, 999999999999))[:12]
        pan_letters = "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5))
        pan = f"{pan_letters}{random.randint(1000, 9999)}{random.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}"

        emp_doc = {
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": None,
            "phone": phone,
            "name": name,
            "father_name": father,
            "picture": None,
            "role": "employee",
            "company_id": COMPANY_ID,
            "employee_code": ecode,
            "position": position,
            "designation": position,
            "department": dept,
            "gender": gender,
            "dob": rand_dob(),
            "doj": rand_doj_within(),
            "uan_no": uan,
            "esi_ip_no": esi,
            "aadhaar_no": aadhaar,
            "pan_no": pan,
            "salary_monthly": salary,
            "salary_structure_actual": [
                {"head": "Basic", "amount": int(salary * 0.5)},
                {"head": "HRA",   "amount": int(salary * 0.2)},
                {"head": "CONV.", "amount": int(salary * 0.1)},
                {"head": "OTHER", "amount": int(salary * 0.2)},
            ],
            "onboarded": True,
            "approval_status": "approved",
            "has_pin": True,
            "pin_hash": hash_pin("1234"),
            "pin_must_change": False,
            "pin_set_at": now_iso(),
            "full_day_hrs": 8,
            "half_day_hrs": 4,
            "weekly_off_day": 6,
            "created_at": now_iso(),
        }
        await db.users.insert_one(emp_doc)
        made.append((emp_doc["user_id"], ecode, name))
    return made


async def seed_punches(db, employees: list, days_back: int = 14) -> int:
    """Generate IN/OUT punches for each employee over the last N days,
    skipping Sundays. ~5% random absents per employee/day."""
    punch_count = 0
    today = datetime.now(IST).date()
    for days_ago in range(days_back, 0, -1):
        d = today - timedelta(days=days_ago)
        if d.weekday() == 6:  # Sunday
            continue
        date_str = d.isoformat()
        for emp_id, ecode, name in employees:
            if random.random() < 0.05:
                continue
            in_dt = datetime(d.year, d.month, d.day,
                             9, random.randint(0, 45), 0, tzinfo=IST)
            out_dt = datetime(d.year, d.month, d.day,
                              18, random.randint(0, 55), 0, tzinfo=IST)
            for kind, dt in [("in", in_dt), ("out", out_dt)]:
                await db.attendance.insert_one({
                    "record_id": f"att_{uuid.uuid4().hex[:12]}",
                    "user_id": emp_id,
                    "company_id": COMPANY_ID,
                    "kind": kind,
                    "date": date_str,
                    "at": dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "original_at": dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "latitude": 25.3463 + random.uniform(-0.001, 0.001),
                    "longitude": 74.6408 + random.uniform(-0.001, 0.001),
                    "distance_m": random.randint(5, 80),
                    "source": "seed:kankani-bulk",
                    "outside_geofence": False,
                    "status": "approved",
                    "decision_by": "system:seed",
                    "decision_at": now_iso(),
                    "decision_reason": "Seed data",
                    "selfie_base64": None,
                })
                punch_count += 1
    return punch_count


async def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # Find next available employee_code index
    existing_codes = await db.users.find(
        {"company_id": COMPANY_ID, "employee_code": {"$regex": r"^KEPS\d+$"}},
        {"employee_code": 1, "_id": 0},
    ).to_list(1000)
    used = sorted(int(c["employee_code"][4:]) for c in existing_codes
                  if c.get("employee_code", "")[4:].isdigit())
    next_idx = (used[-1] + 1) if used else 11
    print(f"Existing KEPS employee codes: {len(used)} (highest={used[-1] if used else 'none'})")
    print(f"Seeding {count} new employees starting from KEPS{next_idx:04d}")
    print("-" * 60)

    made = await create_employees(db, next_idx, count)
    print(f"✅ Created {len(made)} employees")
    if made:
        print("   Sample:")
        for row in made[:5]:
            print(f"     - {row[1]} · {row[2]}")
        if len(made) > 5:
            print(f"     ... + {len(made) - 5} more")

    punches = await seed_punches(db, made, days_back=14)
    print(f"✅ Created {punches} punches across last 14 working days")

    total_emps = await db.users.count_documents({"company_id": COMPANY_ID, "role": "employee"})
    total_att = await db.attendance.count_documents({"company_id": COMPANY_ID})
    print("-" * 60)
    print(f"Kankani totals now:  employees={total_emps}  attendance_records={total_att}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
