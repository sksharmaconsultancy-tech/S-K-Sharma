#!/usr/bin/env python3
"""Iter 89 — Seed default MASTERS (global scope) so Firm Master sections
5 (Allowances) and 6 (Deductions) — plus the app's Groups / Departments /
Designations pickers — always have a starting catalog even on a fresh DB.

Idempotent: only inserts a doc if the same (type, company_id='__global__',
name) triple does not already exist.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


ALLOWANCES = [
    "HRA", "CONV.", "OTH. ALLOW.", "OVER TIME", "INCENTIVE",
    "OTHER MISC.ALLOWANCE", "BONUS", "MEDICAL ALLOWANCES",
    "FOOD ALLOWANCES", "GRATUITY", "LEAVE", "DA",
]
DEDUCTIONS = [
    "PF", "ESI", "I. TAX", "TDS", "OTH. DEDUC.",
    "ADVANCE", "UNIFORM", "CLUB", "CANTEEN", "PT",
]
GROUPS = [
    "Staff", "Labour", "Contractual Labour", "Trainee",
    "Housekeeping", "Security", "Managerial",
]
DEPARTMENTS = [
    "Production", "Quality", "Maintenance", "Stores", "Dispatch",
    "Accounts", "Finance", "HR", "Admin", "Purchase", "Sales", "IT",
]
DESIGNATIONS = [
    "Operator", "Machine Attendant", "Supervisor", "Assistant Manager",
    "Manager", "Senior Manager", "General Manager", "Accountant",
    "Store Keeper", "Loom Fitter", "Electrician", "Quality Checker",
    "HR Executive", "HR Manager", "Packer", "Driver", "Peon",
]


async def _seed_type(db, type_name: str, names: list) -> int:
    inserted = 0
    for name in names:
        exists = await db.masters.find_one(
            {"type": type_name, "company_id": "__global__", "name": name},
            {"_id": 0, "master_id": 1},
        )
        if exists:
            continue
        await db.masters.insert_one({
            "master_id": f"mst_{uuid.uuid4().hex[:10]}",
            "type": type_name,
            "company_id": "__global__",
            "name": name,
            "member_user_ids": [],
            "created_at": _now(),
            "created_by": "system:seed",
        })
        inserted += 1
    return inserted


async def main() -> None:
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    total = 0
    for type_name, names in [
        ("allowance",   ALLOWANCES),
        ("deduction",   DEDUCTIONS),
        ("group",       GROUPS),
        ("department",  DEPARTMENTS),
        ("designation", DESIGNATIONS),
    ]:
        n = await _seed_type(db, type_name, names)
        print(f"  {type_name:12s}  inserted {n:3d}  (total in catalog: {len(names)})")
        total += n
    print(f"\n=> {total} new master rows seeded")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
