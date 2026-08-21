"""E2E: task allotment notification reaches a Sub Super Admin."""
import asyncio, os, secrets, json, urllib.request
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = "http://localhost:8001/api"

def call(path, tok, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body else None)
    req.add_header("Authorization", f"Bearer {tok}")
    if body: req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    sup = await db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}, {"_id": 0, "user_id": 1})
    sub = await db.users.find_one({"role": "sub_admin"}, {"_id": 0, "user_id": 1, "name": 1, "email": 1})
    if not sub:
        print("NO sub_admin user found"); return
    toks = {}
    for label, u in (("sup", sup), ("sub", sub)):
        tok = "testsess_" + secrets.token_hex(16)
        await db.user_sessions.insert_one({
            "session_token": tok, "user_id": u["user_id"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
        toks[label] = tok
    print("sub_admin:", sub.get("name"), sub["user_id"])
    r = call("/admin/portal-tasks", toks["sup"], "POST", {
        "title": "TEST672 Verify GST filings", "priority": "high",
        "assignee_id": sub["user_id"]})
    task_id = r["task"]["task_id"]
    print("task created:", task_id)
    feed = call("/notifications", toks["sub"])["notifications"]
    hits = [n for n in feed if n.get("reference_id") == task_id]
    print("sub_admin feed hits:", len(hits))
    if hits:
        h = hits[0]
        print("  title:", h["title"])
        print("  body:", h["body"])
        print("  category/priority:", h.get("category"), "/", h.get("priority"))
        print("  action_url:", h.get("action_url"))
    # also check digest endpoint doesn't break
    dig = call("/notifications/digest", toks["sub"])
    print("digest ok, total:", dig["total"])
    # cleanup
    await db.portal_tasks.delete_one({"task_id": task_id})
    await db.task_audit.delete_many({"task_id": task_id})
    await db.notifications.delete_many({"reference_id": task_id})
    await db.user_sessions.delete_many({"session_token": {"$in": list(toks.values())}})
    print("cleaned up. PASS" if hits else "FAIL")

asyncio.run(main())
