import asyncio, os, secrets
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

async def m():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    u = await db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}, {"_id": 0, "user_id": 1, "role": 1})
    tok = "testsess_" + secrets.token_hex(16)
    await db.user_sessions.insert_one({
        "session_token": tok, "user_id": u["user_id"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
    })
    print(tok, u["role"])

asyncio.run(m())
