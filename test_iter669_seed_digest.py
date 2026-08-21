"""Seed a few notifications dated YESTERDAY (IST) to exercise the digest."""
import asyncio, os, uuid
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

IST = timezone(timedelta(hours=5, minutes=30))

async def m():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    y = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    rows = [
        ("Salary Locked", "Kankani Enterprises — May 2026 payroll locked by admin.", "salary", "important", "/compliance-salary-run", "cmp_527fecdd7c", 10),
        ("New Leave Request", "RAM SINGH applied for 1 day Casual Leave.", "leave", "normal", "/leaves-admin", "cmp_527fecdd7c", 11),
        ("Import Completed", "Salary sheet import finished — 56 rows.", "import", "normal", "/compliance-salary-run", "cmp_527fecdd7c", 14),
        ("Punch Device Offline", "Branch B2 punch device missed heartbeat.", "attendance", "critical", "/branch-management", "cmp_527fecdd7c", 16),
        ("New Employee — Approval Required", "MOHAN LAL onboarded — approval pending.", "employee", "important", "/employee-approvals", "cmp_527fecdd7c", 18),
    ]
    for title, body, cat, prio, url, cid, hour in rows:
        await db.notifications.insert_one({
            "notification_id": f"n_digest_{uuid.uuid4().hex[:8]}",
            "title": title, "body": body, "audience": "admins",
            "category": cat, "priority": prio, "action_url": url,
            "company_id": cid, "created_by": "Digest Seed",
            "created_at": y.replace(hour=hour).astimezone(timezone.utc).isoformat(),
        })
    n = await db.notifications.count_documents({"notification_id": {"$regex": "^n_digest_"}})
    print("seeded, total digest rows:", n)

asyncio.run(m())
