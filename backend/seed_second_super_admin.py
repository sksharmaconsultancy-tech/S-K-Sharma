"""Iter 611 — allow a second Super Admin login email (user request).
Idempotent: if the email already exists (any role) it is promoted to
super_admin (existing password kept); otherwise it is created with the
default password below (user should change it after first login).
Runs locally and on the VPS (called by the deploy script)."""
import asyncio
import os
import sys
import uuid

import bcrypt
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

EMAIL = "nikkirock02@gmail.com"
DEFAULT_PASSWORD = "Nikki@2026"


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[
        os.environ.get("DB_NAME", "test_database")]
    u = await db.users.find_one({"email": EMAIL})
    if u:
        upd = {"role": "super_admin", "active": True}
        if not u.get("password_hash"):
            upd["password_hash"] = bcrypt.hashpw(
                DEFAULT_PASSWORD.encode(), bcrypt.gensalt(rounds=12)).decode()
            print(f"{EMAIL}: promoted to super_admin + default password set")
        else:
            print(f"{EMAIL}: promoted to super_admin (existing password kept)")
        await db.users.update_one({"user_id": u["user_id"]}, {"$set": upd})
    else:
        await db.users.insert_one({
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": EMAIL, "name": "Super Admin (Nikki)",
            "role": "super_admin", "active": True,
            "password_hash": bcrypt.hashpw(
                DEFAULT_PASSWORD.encode(), bcrypt.gensalt(rounds=12)).decode(),
            "created_at": "seed_iter611",
        })
        print(f"{EMAIL}: created as super_admin with default password")
    print("done")

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
