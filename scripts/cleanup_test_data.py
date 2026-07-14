#!/usr/bin/env python3
"""
Cleanup helper for automated / testing_agent runs.

Removes any TEMPORARY firm, user, attendance, salary-run, ticket, etc. that
was created by the testing_agent during a test iteration.

A record is considered "temporary" when ANY of the following match:
  * companies.name / companies.code matches   ^(Iter\\d+|TEST[_-]|QA[_-]|PYTEST[_-])
  * users.name / employee_code / email matches the same regex family
  * document field ``_test_temp`` is truthy   (best-effort convention)

USAGE
-----
    python3 /app/scripts/cleanup_test_data.py           # dry-run summary
    python3 /app/scripts/cleanup_test_data.py --apply   # actually delete

The script is IDEMPOTENT and NEVER touches production firms (S.K. Sharma &
Co., Sharma Associates, Sharma Services, Sharma Consultancy, Sharma Allied
Services, Demo Textile Mills Pvt Ltd) or the hard-coded super_admin
`sksharmaconsultancy@gmail.com`.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from typing import Iterable, Set

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# ---- Config ---------------------------------------------------------------

# Names / codes that mark a doc as temporary. Case-insensitive.
# NOTE: patterns are strict prefixes (anchored to start-of-string) so a real
# firm/employee whose name merely CONTAINS "test" or "qa" will NEVER match.
TEMP_PATTERNS = [
    r"^Iter\d+[a-z]?[-_]",       # Iter77-P1-abcdef  (must have digit + separator, optional alpha suffix)
    r"^TEST_Iter\d+",      # TEST_Iter77_ab12
    r"^QA_Iter\d+",
    r"^PYTEST_",           # pytest_*
    r"^E2E_",              # e2e_*
    r"^__tmp__",           # __tmp__anything
    r"@test\.local$",      # emails
    r"@qa\.local$",
    r"@pytest\.local$",
]

# Absolute protection list — never delete these firms even if the name
# happens to match one of the regex above (safety net).
PROTECTED_FIRM_NAMES = {
    "S.K. Sharma & Co.",
    "Sharma Associates",
    "Sharma Services",
    "Sharma Consultancy",
    "Sharma Allied Services",
    "Demo Textile Mills Pvt Ltd",
    "Luxe Apparels Private Limited",
    "KANKANI ENTERPRISES",
}
PROTECTED_EMAILS = {"sksharmaconsultancy@gmail.com"}

# --------------------------------------------------------------------------


def _regex_or(patterns: Iterable[str]) -> dict:
    """Build a Mongo $regex OR for a set of patterns on common name fields."""
    ors = []
    for p in patterns:
        ors.append({"name": {"$regex": p, "$options": "i"}})
        ors.append({"code": {"$regex": p, "$options": "i"}})
        ors.append({"email": {"$regex": p, "$options": "i"}})
        ors.append({"employee_code": {"$regex": p, "$options": "i"}})
    ors.append({"_test_temp": True})
    return {"$or": ors}


async def _find_temp_firms(db) -> tuple[list[dict], Set[str]]:
    """Return (docs, set-of-all-id-strings) for all temp firms."""
    docs = await db.companies.find(_regex_or(TEMP_PATTERNS)).to_list(1000)
    # strip protected
    docs = [d for d in docs if d.get("name") not in PROTECTED_FIRM_NAMES]
    ids: Set[str] = set()
    for d in docs:
        for k in ("_id", "id", "company_id"):
            v = d.get(k)
            if v is not None:
                ids.add(str(v))
    return docs, ids


async def _find_temp_users(db) -> tuple[list[dict], Set[str]]:
    docs = await db.users.find(_regex_or(TEMP_PATTERNS)).to_list(2000)
    docs = [d for d in docs if (d.get("email") or "").lower() not in PROTECTED_EMAILS]
    ids: Set[str] = set()
    for d in docs:
        for k in ("_id", "id", "user_id"):
            v = d.get(k)
            if v is not None:
                ids.add(str(v))
    return docs, ids


async def _cleanup(db, firm_ids: Set[str], user_ids: Set[str], apply: bool) -> int:
    """Delete every doc from every collection whose ``company_id``/``user_id``
    is in the temp set. Returns total deleted (or would-be-deleted)."""
    total = 0
    cols = await db.list_collection_names()
    for cname in cols:
        col = db[cname]
        for field, ids in (("company_id", firm_ids), ("user_id", user_ids), ("employee_id", user_ids)):
            if not ids:
                continue
            q = {field: {"$in": list(ids)}}
            if apply:
                r = await col.delete_many(q)
                n = r.deleted_count
            else:
                n = await col.count_documents(q)
            if n:
                total += n
                print(f"  {cname:35s}  {field:11s}  -> {n}")
    return total


async def main(apply: bool) -> int:
    load_dotenv("/app/backend/.env")
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "test_database")
    if not mongo_url:
        print("ERROR: MONGO_URL not set", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    print(f"[cleanup_test_data] DB={db_name}  apply={apply}")
    firms, firm_ids = await _find_temp_firms(db)
    users, user_ids = await _find_temp_users(db)

    print(f"  temp firms: {len(firms)}  temp users: {len(users)}")
    for f in firms:
        print(f"    firm:  name={f.get('name')!r}  code={f.get('code')!r}")
    for u in users:
        print(f"    user:  name={u.get('name')!r}  email={u.get('email')!r}  code={u.get('employee_code')!r}")

    if not (firms or users):
        print("Nothing to clean.")
        return 0

    print("\n[cleanup_test_data] Scanning collections...")
    n = await _cleanup(db, firm_ids, user_ids, apply=apply)

    if apply:
        # Finally drop the firm and user docs themselves.
        if firm_ids:
            r = await db.companies.delete_many({"$or": [
                {"_id": {"$in": list(firm_ids)}},
                {"id": {"$in": list(firm_ids)}},
                {"company_id": {"$in": list(firm_ids)}},
            ]})
            if r.deleted_count:
                print(f"  companies    -> {r.deleted_count} (self)")
                n += r.deleted_count
        if user_ids:
            r = await db.users.delete_many({"$or": [
                {"_id": {"$in": list(user_ids)}},
                {"id": {"$in": list(user_ids)}},
                {"user_id": {"$in": list(user_ids)}},
            ]})
            if r.deleted_count:
                print(f"  users        -> {r.deleted_count} (self)")
                n += r.deleted_count

    print(f"\n[cleanup_test_data] TOTAL {'removed' if apply else 'would remove'}: {n}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually delete (default is dry-run)")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(apply=args.apply)))
