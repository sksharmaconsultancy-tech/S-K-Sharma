"""Repro: night-shift pairing + manual punch display on the monthly grid."""
import asyncio, os, json, secrets, urllib.request
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

IST = timezone(timedelta(hours=5, minutes=30))
CID = "cmp_527fecdd7c"

def ist(d, h, m):
    return datetime(2026, 8, d, h, m, tzinfo=IST).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    sup = await db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}, {"_id": 0, "user_id": 1})
    tok = "testsess_" + secrets.token_hex(16)
    await db.user_sessions.insert_one({"session_token": tok, "user_id": sup["user_id"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    # night-shift test employee
    uid = "u_nighttest_1"
    await db.users.delete_many({"user_id": uid})
    await db.users.insert_one({"user_id": uid, "role": "employee", "company_id": CID,
        "name": "ZZ NIGHT TEST", "employee_code": "ZZNT1", "active": True})
    await db.attendance.delete_many({"user_id": uid})
    # Pattern like KAILASH: IN ~19:50 nightly, OUT next morning ~07:55
    punches = [
        ("in", ist(18, 19, 50)), ("out", ist(19, 7, 52)),
        ("in", ist(19, 19, 49)), ("out", ist(20, 7, 53)),
        ("in", ist(20, 19, 50)), ("out", ist(21, 7, 54)),
        ("in", ist(21, 19, 51)), ("out", ist(22, 7, 58)),
        # 22nd: only the morning OUT so far (like the live case)
        # manual-punch case on 10th: machine IN + manual OUT
        ("in", ist(10, 10, 19)), ("out", ist(10, 22, 19)),
    ]
    for i, (kind, at) in enumerate(punches):
        src = "manual_admin" if i == len(punches) - 1 else "biometric"
        await db.attendance.insert_one({
            "record_id": f"att_nt_{i}", "user_id": uid, "company_id": CID,
            "kind": kind, "at": at, "date": at[:10], "status": "approved",
            "source": src})
    req = urllib.request.Request(
        f"http://localhost:8001/api/admin/attendance/monthly-grid/{CID}/2026-08")
    req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    print("top-level keys:", list(data.keys()))
    rows = data.get("rows") or data.get("employees") or []
    row = next((x for x in rows if x.get("user_id") == uid), None)
    if not row:
        print("row not found; first row sample:", json.dumps(rows[0], default=str)[:300] if rows else None)
    days = data.get("day_labels") or []
    cells = (row or {}).get("days") or (row or {}).get("cells") or []
    print("row keys:", list(row.keys())[:20])
    print("days dict size:", len(cells) if isinstance(cells, dict) else "n/a")
    if isinstance(cells, dict):
        nonnull = {k: v for k, v in cells.items() if v}
        print("non-null day keys:", list(nonnull.keys())[:10])
        for k, v in list(nonnull.items())[:4]:
            print(" ", k, json.dumps(v, default=str)[:240])
    print("totals:", json.dumps((row or {}).get("totals"), default=str)[:300])
    for d in ("10", "18", "19", "20", "21", "22"):
        c = cells.get(d) if isinstance(cells, dict) else None
        print(f"{d}:", json.dumps(c, default=str)[:260])
    # cleanup
    await db.attendance.delete_many({"user_id": uid})
    await db.users.delete_many({"user_id": uid})
    await db.user_sessions.delete_one({"session_token": tok})
    print("cleaned")

asyncio.run(main())
