"""Iter 129i — sync General Masters with the forms that use them.

  1. Seed GLOBAL Allowance / Deduction heads (the fixed Firm-Master labels)
     into `masters` so the Masters tabs show every head the Firm Master
     form offers.
  2. Seed per-company Department / Designation masters from values already
     present on employees (so nothing existing is "missing" from Masters).
  3. Case-insensitively dedupe ALL master types (merges member_user_ids).

Run:  python3 scripts/sync_masters_catalog.py
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

ALLOWANCE_LABELS = [
    "HRA", "CONV.", "OTH. ALLOW.", "OVER TIME", "INCENTIVE",
    "OTHER MISC.ALLOWANCE", "BONUS", "MEDICAL ALLOWANCES",
    "FOOD ALLOWANCES", "GRATUITY", "LEAVE", "DA",
]
DEDUCTION_LABELS = [
    "PF", "ESI", "I. TAX", "TDS", "OTH. DEDUC.",
    "ADVANCE", "UNIFORM", "CLUB", "CANTEEN", "PT",
]


def _doc(mtype: str, cid: str, name: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "master_id": f"mst_{uuid.uuid4().hex[:12]}",
        "type": mtype, "company_id": cid, "name": name,
        "member_user_ids": [], "created_at": now, "updated_at": now,
        "created_by": "sync_script", "scope": "global" if cid == "__global__" else "company",
    }


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]

    # 1. Global allowance / deduction heads
    added = 0
    for mtype, labels in (("allowance", ALLOWANCE_LABELS), ("deduction", DEDUCTION_LABELS)):
        names = set()
        async for m in db.masters.find({"type": mtype}, {"_id": 0, "name": 1}):
            names.add((m.get("name") or "").strip().lower())
        for lab in labels:
            if lab.strip().lower() not in names:
                await db.masters.insert_one(_doc(mtype, "__global__", lab.upper()))
                names.add(lab.strip().lower())
                added += 1
    print("allowance/deduction heads added:", added)

    # 2. Department / Designation from employee data (per company)
    added2 = 0
    for field, mtype in (("department", "department"), ("designation", "designation")):
        combos = await db.users.aggregate([
            {"$match": {field: {"$nin": [None, ""]}, "company_id": {"$nin": [None, ""]}}},
            {"$group": {"_id": {"c": "$company_id", "v": {"$trim": {"input": f"${field}"}}}}},
        ]).to_list(2000)
        # existing names per scope (company + global)
        existing = {}
        async for m in db.masters.find({"type": mtype}, {"_id": 0, "company_id": 1, "name": 1}):
            existing.setdefault(m.get("company_id"), set()).add((m.get("name") or "").strip().lower())
        g = existing.get("__global__", set()) | existing.get(None, set())
        for row in combos:
            cid, val = row["_id"]["c"], (row["_id"]["v"] or "").strip()
            if not val:
                continue
            if val.lower() in g or val.lower() in existing.get(cid, set()):
                continue
            await db.masters.insert_one(_doc(mtype, cid, val.upper()))
            existing.setdefault(cid, set()).add(val.lower())
            added2 += 1
    print("department/designation entries added:", added2)

    # 3. UPPERCASE all master names + employee grouping fields (Iter 129j)
    up = 0
    async for m in db.masters.find({}, {"_id": 1, "name": 1}):
        n = (m.get("name") or "").strip()
        if n and n != n.upper():
            await db.masters.update_one({"_id": m["_id"]}, {"$set": {"name": n.upper()}})
            up += 1
    async for u in db.users.find(
        {"$or": [
            {"employee_type": {"$nin": [None, ""]}},
            {"employee_group": {"$nin": [None, ""]}},
            {"department": {"$nin": [None, ""]}},
            {"designation": {"$nin": [None, ""]}},
        ]},
        {"_id": 1, "employee_type": 1, "employee_group": 1, "department": 1, "designation": 1},
    ):
        upd = {}
        for f in ("employee_type", "employee_group", "department", "designation"):
            v = (u.get(f) or "").strip()
            if v and v != v.upper():
                upd[f] = v.upper()
        if upd:
            await db.users.update_one({"_id": u["_id"]}, {"$set": upd})
            up += 1
    print("uppercased docs:", up)

    # 4. Case-insensitive dedupe across ALL master types
    seen, removed = {}, 0
    async for m in db.masters.find({}).sort("created_at", 1):
        key = (m.get("type"), m.get("company_id"), (m.get("name") or "").strip().lower())
        if key in seen:
            surv = seen[key]
            members = list(set((surv.get("member_user_ids") or []) + (m.get("member_user_ids") or [])))
            await db.masters.update_one({"_id": surv["_id"]}, {"$set": {"member_user_ids": members}})
            await db.masters.delete_one({"_id": m["_id"]})
            removed += 1
        else:
            seen[key] = m
    print("duplicates merged:", removed)

asyncio.run(main())
