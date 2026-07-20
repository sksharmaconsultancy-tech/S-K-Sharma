import requests, json, asyncio, os, uuid

B = "http://localhost:8001/api"
r = requests.post(B+"/auth/admin-password-login", json={"email":"sksharmaconsultancy@gmail.com","password":"sharma123"})
H = {"Authorization":"Bearer "+(r.json().get("token") or r.json().get("session_token"))}
CID = "cmp_527fecdd7c"; UID = "user_44cd6f561da0"

# 1. enable comp_off in week_off_worked
requests.patch(B+"/attendance/policy", params={"company_id":CID}, headers=H, json={
  "weekly_off_days":[6], "full_day_hours":8, "half_day_hours":4,
  "week_off_worked":{"mode":"full_day_ot","half_day_threshold":4,"full_day_threshold":8,
                     "ot_after":8,"comp_off":True,"salary_credit":True}})

# 2. seed Sunday 2026-06-14 worked 9h
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
async def seed():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME","test_database")]
    await db.attendance.delete_many({"user_id":UID,"date":"2026-06-14"})
    await db.comp_off_ledger.delete_many({"user_id":UID})
    await db.leaves.delete_many({"user_id":UID,"reason":"comp-off e2e test"})
    def rec(kind,hh,mm):
        return {"record_id":"att_"+uuid.uuid4().hex[:12],"user_id":UID,"company_id":CID,
                "date":"2026-06-14","kind":kind,"at":f"2026-06-14T{hh:02d}:{mm:02d}:00+05:30",
                "source":"biometric","status":"approved"}
    await db.attendance.insert_many([rec("in",8,0), rec("out",17,0)])
asyncio.get_event_loop().run_until_complete(seed())

# 3. sync + summary
s = requests.post(B+"/admin/comp-off/sync", headers=H, json={"company_id":CID,"month":"2026-06"})
print("sync:", s.status_code, s.json())
sm = requests.get(B+"/admin/comp-off/summary", headers=H, params={"company_id":CID,"month":"2026-06"}).json()
row = next((x for x in sm["rows"] if x["user_id"]==UID), None)
print("enabled:", sm["enabled"], "| emp50:", {k:row[k] for k in ("earned","used","balance")})

# 4. employee raises 1-day leave and admin approves WITH comp-off
er = requests.post(B+"/auth/pin-login", json={"login_id":"TEST50","pin":"123456"})
if er.status_code != 200:
    er = requests.post(B+"/auth/pin-login", json={"login_id":"TEST50","pin":"654321"})
print("emp login:", er.status_code)
EH = {"Authorization":"Bearer "+(er.json().get("token") or er.json().get("session_token"))}
lv = requests.post(B+"/leaves", headers=EH, json={"leave_type":"sick","from_date":"2026-06-20","to_date":"2026-06-20","reason":"comp-off e2e test"})
print("leave create:", lv.status_code)
lid = lv.json()["leave_id"]
dec = requests.patch(f"{B}/leaves/{lid}", headers=H, json={"status":"approved","use_comp_off":True,"comment":"ok"})
print("approve+compoff:", dec.status_code, "comp_off_adjusted:", dec.json().get("comp_off_adjusted"))
my = requests.get(B+"/comp-off/my", headers=EH).json()
print("employee balance after:", {k:my[k] for k in ("earned","used","balance")})

# 5. insufficient balance case
lv2 = requests.post(B+"/leaves", headers=EH, json={"leave_type":"sick","from_date":"2026-06-22","to_date":"2026-06-25","reason":"comp-off e2e test"})
lid2 = lv2.json()["leave_id"]
dec2 = requests.patch(f"{B}/leaves/{lid2}", headers=H, json={"status":"approved","use_comp_off":True})
print("insufficient case:", dec2.status_code, dec2.json().get("detail","")[:80])

# 6. manual adjust grant 2 then use 1
a1 = requests.post(B+"/admin/comp-off/adjust", headers=H, json={"user_id":UID,"days":2,"direction":"earn","remarks":"manual grant"})
a2 = requests.post(B+"/admin/comp-off/adjust", headers=H, json={"user_id":UID,"days":1,"direction":"use","remarks":"manual use"})
print("manual grant:", a1.status_code, "use:", a2.status_code, "balance:", a2.json().get("balance"))

# cleanup
async def clean():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME","test_database")]
    await db.attendance.delete_many({"user_id":UID,"date":"2026-06-14","source":"biometric"})
    await db.comp_off_ledger.delete_many({"user_id":UID})
    await db.leaves.delete_many({"user_id":UID,"reason":"comp-off e2e test"})
asyncio.get_event_loop().run_until_complete(clean())
print("cleanup done")
