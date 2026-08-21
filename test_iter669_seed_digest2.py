"""Seed realistic yesterday-dated notifications (long bodies, 2 firms) to
reproduce the live digest layout issue."""
import asyncio, os, uuid
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

IST = timezone(timedelta(hours=5, minutes=30))
BODY = ("Device BR-02 has been offline for over 15 minutes. Punches are NOT "
        "syncing — check its power and internet connection.")

async def m():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    comps = await db.companies.find({}, {"_id": 0, "company_id": 1, "name": 1}).to_list(5)
    y = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    i = 0
    for c in comps[:2]:
        for h in (8, 9, 11, 13):
            i += 1
            await db.notifications.insert_one({
                "notification_id": f"n_digest_{uuid.uuid4().hex[:8]}",
                "title": "Punch Device Offline",
                "body": BODY,
                "audience": "admins", "category": "attendance",
                "priority": "critical" if h == 8 else "important",
                "action_url": "/branch-management",
                "company_id": c["company_id"], "created_by": "Digest Seed",
                "created_at": y.replace(hour=h).astimezone(timezone.utc).isoformat(),
            })
    print("seeded", i, "rows for", [c["name"] for c in comps[:2]])

asyncio.run(m())
