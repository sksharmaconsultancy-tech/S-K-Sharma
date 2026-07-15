"""Iter 129g — one-time migration:
  1. Title-case users.employee_type / employee_group (merges STAFF/Staff).
  2. Title-case + case-insensitively dedupe `masters` (type=group),
     merging member_user_ids into the surviving doc.
  3. Seed the 4 standard GLOBAL Employee Types: Staff, Labour,
     Helping Staff, Other.
Run:  python3 scripts/migrate_employee_types.py
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

PRESETS = ["Staff", "Labour", "Helping Staff", "Other"]


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]

    # 1. Users — Title Case both fields
    fixed = 0
    async for u in db.users.find(
        {"$or": [{"employee_type": {"$nin": [None, ""]}}, {"employee_group": {"$nin": [None, ""]}}]},
        {"_id": 1, "employee_type": 1, "employee_group": 1},
    ):
        et = (u.get("employee_type") or "").strip()
        eg = (u.get("employee_group") or "").strip() or et
        net, neg = et.title() or None, eg.title() or None
        if net != u.get("employee_type") or neg != u.get("employee_group"):
            await db.users.update_one({"_id": u["_id"]}, {"$set": {"employee_type": net, "employee_group": neg}})
            fixed += 1
    print("users normalised:", fixed)

    # 2. Masters (group) — title case + dedupe per company
    seen = {}
    removed = 0
    async for m in db.masters.find({"type": "group"}).sort("created_at", 1):
        key = (m.get("company_id"), (m.get("name") or "").strip().lower())
        name_tc = (m.get("name") or "").strip().title()
        if key in seen:
            surv = seen[key]
            members = list(set((surv.get("member_user_ids") or []) + (m.get("member_user_ids") or [])))
            await db.masters.update_one({"_id": surv["_id"]}, {"$set": {"member_user_ids": members, "name": name_tc}})
            await db.masters.delete_one({"_id": m["_id"]})
            removed += 1
        else:
            if name_tc != m.get("name"):
                await db.masters.update_one({"_id": m["_id"]}, {"$set": {"name": name_tc}})
            m["name"] = name_tc
            seen[key] = m
    print("duplicate group masters merged:", removed)

    # 3. Seed global presets
    added = 0
    for name in PRESETS:
        dup = await db.masters.find_one({"type": "group", "company_id": "__global__",
                                         "name": {"$regex": f"^{name}$", "$options": "i"}})
        if not dup:
            now = datetime.now(timezone.utc).isoformat()
            await db.masters.insert_one({
                "master_id": f"mst_{uuid.uuid4().hex[:12]}",
                "type": "group", "company_id": "__global__", "name": name,
                "member_user_ids": [], "created_at": now, "updated_at": now,
                "created_by": "migration", "scope": "global",
            })
            added += 1
    print("global presets added:", added)

asyncio.run(main())
