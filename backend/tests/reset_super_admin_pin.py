"""Utility to reset super_admin PIN back to 246810 in temp state.

Usage: python /app/backend/tests/reset_super_admin_pin.py
"""
import asyncio
import os
import sys

import bcrypt
from motor.motor_asyncio import AsyncIOMotorClient

TARGET_EMAIL = "sksharmaconsultancy@gmail.com"
TARGET_PIN = "246810"


async def main() -> int:
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    pin_hash = bcrypt.hashpw(TARGET_PIN.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    res = await db.users.update_one(
        {"email": TARGET_EMAIL},
        {
            "$set": {
                "pin_hash": pin_hash,
                "pin_must_change": True,
                "pin_fail_count": 0,
                "pin_failed_attempts": 0,
                "pin_locked_until": None,
                "has_pin": True,
                "pin_forgot_at": None,
            }
        },
    )
    print(f"matched={res.matched_count} modified={res.modified_count}")

    doc = await db.users.find_one({"email": TARGET_EMAIL}, {"_id": 0, "email": 1, "phone": 1, "pin_must_change": 1, "pin_fail_count": 1, "pin_locked_until": 1})
    print(f"post-reset doc: {doc}")

    client.close()
    return 0 if res.matched_count == 1 else 1


if __name__ == "__main__":
    # Load backend .env
    from pathlib import Path
    env_path = Path("/app/backend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v.strip('"').strip("'"))
    sys.exit(asyncio.run(main()))
