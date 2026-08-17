"""Iter 595 — quick-mark endpoint test (keyboard quick keys P/A)."""
import asyncio, os, sys, uuid
from datetime import datetime, timezone, timedelta

import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
BASE = "http://localhost:8001/api"


async def main():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]
    su = await db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}, {"user_id": 1})
    token = f"test_{uuid.uuid4().hex}"
    await db.user_sessions.insert_one({
        "session_token": token, "user_id": su["user_id"],
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "created_at": datetime.now(timezone.utc), "auth_method": "password"})
    H = {"Authorization": f"Bearer {token}"}

    emp = await db.users.find_one(
        {"company_id": "cmp_527fecdd7c", "role": "employee", "employee_code": "50"},
        {"user_id": 1, "name": 1, "shift_start": 1, "shift_end": 1})
    uid = emp["user_id"]
    date = "2026-06-02"
    await db.attendance.delete_many({"user_id": uid, "date": date})  # clean slate

    ok = True
    async with httpx.AsyncClient(timeout=30) as c:
        # 1. mark present
        r = await c.post(f"{BASE}/admin/attendance/quick-mark", headers=H,
                         json={"user_id": uid, "date": date, "status": "present"})
        print("1. present:", r.status_code, r.json() if r.status_code == 200 else r.text)
        ok &= r.status_code == 200 and len(r.json()["records"]) == 2

        n = await db.attendance.count_documents({"user_id": uid, "date": {"$gte": date, "$lte": "2026-06-03"},
                                                 "source": "manual_admin", "status": "approved"})
        print("2. punches in DB:", n); ok &= n >= 2

        # 3. present again -> 409
        r = await c.post(f"{BASE}/admin/attendance/quick-mark", headers=H,
                         json={"user_id": uid, "date": date, "status": "present"})
        print("3. duplicate present -> expect 409:", r.status_code); ok &= r.status_code == 409

        # 4. absent -> clears
        r = await c.post(f"{BASE}/admin/attendance/quick-mark", headers=H,
                         json={"user_id": uid, "date": date, "status": "absent"})
        print("4. absent:", r.status_code, r.json()); ok &= r.status_code == 200 and r.json()["deleted"] >= 1

        # 5. audit rows exist
        na = await db.attendance_audit_log.count_documents({"reason": {"$regex": "Keyboard quick key"}})
        print("5. audit rows:", na); ok &= na >= 2

        # 6. bad date
        r = await c.post(f"{BASE}/admin/attendance/quick-mark", headers=H,
                         json={"user_id": uid, "date": "02-06-2026", "status": "present"})
        print("6. bad date -> expect 400:", r.status_code); ok &= r.status_code == 400

    # cleanup any leftover next-day OUT
    await db.attendance.delete_many({"user_id": uid, "date": "2026-06-03", "source": "manual_admin",
                                     "manual_reason": {"$regex": "quick key"}})
    await db.user_sessions.delete_one({"session_token": token})
    print("RESULT:", "PASS ✅" if ok else "FAIL ❌")
    sys.exit(0 if ok else 1)


asyncio.run(main())
