"""Remove test notifications created during Iter 668/669 verification."""
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

async def m():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    r1 = await db.notifications.delete_many({"notification_id": {"$regex": "^n_digest_"}})
    r2 = await db.notifications.delete_many({
        "title": {"$in": ["Salary Processing Completed", "New Leave Request", "Import Completed"]},
        "body": {"$regex": "Kankani Enterprises — June 2026 run finished|SURENDRA SINGH applied for 2 days|import finished — 56 rows processed"},
    })
    print("deleted digest seeds:", r1.deleted_count, "| toast test rows:", r2.deleted_count)

asyncio.run(m())
