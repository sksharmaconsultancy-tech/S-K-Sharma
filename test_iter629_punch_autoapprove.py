"""Iter 629 — PWA punch auto-approve + IST wall-clock display convention."""
import asyncio, os, uuid
from datetime import datetime, timezone, timedelta
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
P = F = 0
def chk(n, c, e=""):
    global P, F
    P, F = (P + 1, F) if c else (P, F + 1)
    print(("  ✅ " if c else "  ❌ ") + n, e if not c else "")

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    comp = await db.companies.find_one({"company_id": CID},
        {"secure_face_punch_enabled": 1, "auto_approve_mobile_punches": 1,
         "punch_approval_required": 1})
    print("firm flags:", {k: comp.get(k) for k in
          ("secure_face_punch_enabled", "auto_approve_mobile_punches")})
    # employee with NO approved face template
    tmpl_uids = {t["user_id"] async for t in db.face_templates.find(
        {"status": "approved"}, {"user_id": 1})}
    emp = await db.users.find_one(
        {"company_id": CID, "role": "employee",
         "user_id": {"$nin": list(tmpl_uids)},
         "$or": [{"employment_status": "active"},
                 {"employment_status": {"$exists": False}}]},
        {"user_id": 1, "employee_code": 1, "is_live_in": 1, "onboarding_status": 1})
    uid = emp["user_id"]
    orig_live_in = emp.get("is_live_in")
    await db.users.update_one({"user_id": uid}, {"$set": {
        "is_live_in": True, "pan_number": "TESTP1234F", "pan_no": "TESTP1234F"}})
    tok = "t_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    await db.user_sessions.insert_one({"session_token": tok, "user_id": uid,
        "expires_at": now + timedelta(hours=1), "created_at": now, "auth_method": "password"})
    H = {"Authorization": f"Bearer {tok}"}
    made = []
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            # 1. default (flag True) → punch auto-approved
            r = await c.post(f"{BASE}/attendance/punch", headers=H,
                             json={"kind": "in", "source": "manual",
                                   "biometric_method": "face"})
            chk("punch accepted", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
            j = r.json()
            chk("status APPROVED (auto)", j.get("status") == "approved", j)
            chk("approval_required false", j.get("approval_required") is False, j)
            rec = await db.attendance.find_one({"record_id": j["record_id"]})
            made.append(rec["record_id"])
            chk("decision_by system:firm-auto-approve",
                rec.get("decision_by") == "system:firm-auto-approve", rec.get("decision_by"))
            # 'at' convention: IST wall-clock labelled UTC
            at = datetime.fromisoformat(rec["at"].replace("Z", "+00:00"))
            ist_wall = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
            drift = abs((at.replace(tzinfo=None) - ist_wall.replace(tzinfo=None)).total_seconds())
            chk("'at' stored as IST wall-clock labelled UTC", drift < 120, f"drift={drift}s at={rec['at']}")

            # 2. ESS attendance returns the raw wall-clock time (frontend now
            #    formats in UTC → shows exactly the stored HH:MM)
            today = ist_wall.strftime("%Y-%m")
            r = await c.get(f"{BASE}/ess/attendance?month={today}", headers=H)
            day = [d for d in r.json()["days"] if d["date"] == rec["date"]]
            chk("ess/attendance exposes punch", bool(day) and day[0]["in"] == rec["at"],
                day[:1])

            # 3. field missing on firm → still auto-approve (default ON)
            await db.companies.update_one({"company_id": CID},
                {"$unset": {"auto_approve_mobile_punches": ""}})
            r = await c.post(f"{BASE}/attendance/punch", headers=H,
                             json={"kind": "out", "source": "manual",
                                   "biometric_method": "face"})
            j = r.json()
            chk("missing flag → default AUTO-APPROVE", j.get("status") == "approved", j)
            made.append(j["record_id"])

            # 4. firm explicitly OFF → punch pends (toggle still respected)
            await db.companies.update_one({"company_id": CID},
                {"$set": {"auto_approve_mobile_punches": False}})
            r = await c.post(f"{BASE}/attendance/punch", headers=H,
                             json={"kind": "in", "source": "manual",
                                   "biometric_method": "face"})
            j = r.json()
            chk("explicit OFF → PENDING", j.get("status") == "pending", j)
            made.append(j["record_id"])
    finally:
        # restore everything
        await db.companies.update_one({"company_id": CID},
            {"$set": {"auto_approve_mobile_punches": True}})
        await db.attendance.delete_many({"record_id": {"$in": made}})
        if orig_live_in is None:
            await db.users.update_one({"user_id": uid}, {"$unset": {
                "is_live_in": "", "pan_number": "", "pan_no": ""}})
        else:
            await db.users.update_one({"user_id": uid}, {
                "$set": {"is_live_in": orig_live_in},
                "$unset": {"pan_number": "", "pan_no": ""}})
        await db.user_sessions.delete_one({"session_token": tok})
    print(f"\nPASS {P} / FAIL {F} (test punches deleted, employee + firm restored)")

asyncio.run(main())
