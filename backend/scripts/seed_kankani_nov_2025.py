"""
Iter 86 — Seed real biometric punch data for KANKANI ENTERPRISES for Nov-2025.

Why this exists
---------------
The Actual Salary Process "auto-transfer" path — where P Days & P Hours are
derived from the biometric attendance grid — was never exercised end-to-end
because Kankani had no Nov-2025 punches in the database. This script
inserts realistic IN/OUT approved punches for ~30 employees across Nov-2025
so that when an admin opens Actual Salary Process for KEPS · 2025-11 with
source = "Biometric (auto)", the P Days & P Hours columns populate from
real data.

It also seeds ONE hourly-mode employee (salary_mode='hourly') so the
hourly formula test case can be validated.

Idempotent: skips punches that already exist for the same
(user_id, date, kind).

Usage:
    python /app/backend/scripts/seed_kankani_nov_2025.py
"""

import os
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
KANKANI_ID = "cmp_cb39e488a0"

client = MongoClient(MONGO_URL)
db = client[DB_NAME]


def rid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def iso_local(dt: datetime) -> str:
    # Store as ISO-8601 UTC string, matching existing punches.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def make_punch(user_id: str, punch_dt: datetime, kind: str) -> dict:
    return {
        "record_id": rid("seed"),
        "user_id": user_id,
        "company_id": KANKANI_ID,
        "branch_id": None,
        "branch_name": "Biometric Terminal (seed:nov-2025)",
        "date": punch_dt.date().isoformat(),
        "kind": kind,
        "at": iso_local(punch_dt),
        "original_at": iso_local(punch_dt),
        "latitude": None,
        "longitude": None,
        "distance_m": None,
        "source": "seed:zk_2025_11_dat",
        "outside_geofence": False,
        "status": "approved",
        "decision_by": "system:seed",
        "decision_at": datetime.now(timezone.utc).isoformat(),
        "decision_reason": "Seeded Nov-2025 biometric data for auto-transfer path validation",
        "device_serial": "seed:zk_2025_11_dat",
        "device_id": None,
        "device_verify_type": None,
        "selfie_base64": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def seed_hourly_employee() -> str:
    """Create ONE hourly-mode employee for Kankani if not already present."""
    existing = db.users.find_one(
        {"company_id": KANKANI_ID, "salary_mode": "hourly"}
    )
    if existing:
        print(f"  [hourly] already exists: {existing.get('employee_code')} · {existing.get('name')} · rate={existing.get('hourly_rate')}")
        return existing["user_id"]

    new_uid = rid("user")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "user_id": new_uid,
        "email": None,
        "role": "employee",
        "company_id": KANKANI_ID,
        "picture": None,
        "onboarded": True,
        "onboarded_at": now,
        "approval_status": "approved",
        "approval_requested_at": now,
        "approved_at": now,
        "approved_by": "seed:nov-2025",
        "has_pin": False,
        "pin_must_change": True,
        "created_at": now,
        "created_by_admin": "seed:nov-2025",
        "employee_code": "H001",
        "name": "HOURLY WORKER ALPHA",
        "father_name": "SEED FATHER",
        "designation": "HOURLY OPERATOR",
        "employee_type": "LABOUR",
        "employee_group": "LABOUR",
        "gender": "MALE",
        "dob": "1990-01-01",
        "doj": "2024-01-01",
        # HOURLY MODE — this is the key differentiator for the formula test.
        "salary_mode": "hourly",
        "hourly_rate": 75.0,     # ₹75 per hour
        "salary_monthly": 0.0,
        "compliance_gross": 0.0,
        "full_day_hrs": 8.0,
        "half_day_hrs": 4.0,
        "pf_no": "0",
        "aadhaar_no": "999900001111",
        "bio_code": "9001",
        "employee_policy": {
            "salary": 75.0,
            "salary_mode": "hourly",
            "hourly_rate": 75.0,
        },
        "is_online": False,
        "is_offline": True,
        "attendance_policy_override": {"ot_allowed": True},
        "ot_applicable": True,
    }
    db.users.insert_one(doc)
    print(f"  [hourly] CREATED: H001 · HOURLY WORKER ALPHA · ₹75/hr · user_id={new_uid}")
    return new_uid


def seed_punches(emp_ids: list[str]) -> tuple[int, int]:
    """
    For each employee, seed IN/OUT punches Mon-Sat for Nov-2025.
    Some randomised variations to make the auto-transfer path
    non-trivial:
      • Attendance ratio: 85–95% (some absent days)
      • 10% of days: only IN (missed OUT — auto-close by policy)
      • 5% of days: OT extending past 6pm (extra_hrs)
      • Sundays: skipped (weekly off)
    Returns (inserted, skipped_existing).
    """
    inserted = 0
    skipped = 0

    y, m = 2025, 11
    start = date(y, m, 1)
    end = date(y, m, 30)  # Nov has 30 days

    for uid in emp_ids:
        rng = random.Random(hash(uid) & 0xFFFFFFFF)
        d = start
        while d <= end:
            if d.weekday() == 6:  # Sunday — weekly off
                d += timedelta(days=1)
                continue

            # Random absence (5–15% chance)
            if rng.random() < 0.10:
                d += timedelta(days=1)
                continue

            # Baseline IN 08:45-09:30, OUT 18:00-19:15
            in_hour = 8
            in_min = rng.randint(45, 89)
            if in_min >= 60:
                in_hour = 9
                in_min -= 60
            in_dt = datetime.combine(d, time(in_hour, in_min))

            missed_out = rng.random() < 0.10
            extended_ot = rng.random() < 0.05

            if not missed_out:
                out_hour = 18
                out_min = rng.randint(0, 75)
                if extended_ot:
                    out_hour = 20
                    out_min = rng.randint(0, 45)
                if out_min >= 60:
                    out_hour += 1
                    out_min -= 60
                out_dt = datetime.combine(d, time(out_hour, out_min))
            else:
                out_dt = None

            # Insert IN — if not already there
            existing_in = db.attendance.find_one(
                {"user_id": uid, "date": d.isoformat(), "kind": "in"}
            )
            if not existing_in:
                db.attendance.insert_one(make_punch(uid, in_dt, "in"))
                inserted += 1
            else:
                skipped += 1

            if out_dt is not None:
                existing_out = db.attendance.find_one(
                    {"user_id": uid, "date": d.isoformat(), "kind": "out"}
                )
                if not existing_out:
                    db.attendance.insert_one(make_punch(uid, out_dt, "out"))
                    inserted += 1
                else:
                    skipped += 1

            d += timedelta(days=1)

    return inserted, skipped


def main() -> None:
    print("=" * 66)
    print("Seeding KANKANI ENTERPRISES · Nov-2025 · Biometric Punches + Hourly EMP")
    print("=" * 66)

    firm = db.companies.find_one({"company_id": KANKANI_ID})
    if not firm:
        raise SystemExit(f"Kankani not found: {KANKANI_ID}")
    print(f"Firm: {firm.get('name')} ({firm.get('company_code')})")

    # 1) Hourly employee first — so we can include it in the punch loop.
    print("\n[1/2] Ensuring hourly-mode employee exists…")
    hourly_uid = seed_hourly_employee()

    # 2) Pick target set: hourly emp + ~30 existing daily-mode staff.
    all_emps = list(
        db.users.find(
            {"company_id": KANKANI_ID, "role": "employee"},
            {"user_id": 1, "employee_code": 1, "name": 1, "salary_mode": 1},
        )
    )
    daily_pool = [e for e in all_emps if e["user_id"] != hourly_uid]
    target = random.Random(42).sample(daily_pool, min(30, len(daily_pool)))
    target_uids = [hourly_uid] + [e["user_id"] for e in target]

    print(f"\n[2/2] Seeding Nov-2025 punches for {len(target_uids)} employees…")
    print(f"      (1 hourly + {len(target)} daily-mode existing staff)")
    ins, skp = seed_punches(target_uids)
    print(f"      Inserted: {ins} punches · Skipped (already existed): {skp}")

    # Summary
    total_nov = db.attendance.count_documents(
        {"company_id": KANKANI_ID, "date": {"$regex": "^2025-11"}}
    )
    approved_nov = db.attendance.count_documents(
        {"company_id": KANKANI_ID, "date": {"$regex": "^2025-11"}, "status": "approved"}
    )
    print("\n" + "=" * 66)
    print(f"DONE. Kankani Nov-2025 punches now in DB: {total_nov} total | {approved_nov} approved")
    print("=" * 66)


if __name__ == "__main__":
    main()
