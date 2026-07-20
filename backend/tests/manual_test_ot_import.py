import requests, base64, io, asyncio, os
from openpyxl import Workbook

B = "http://localhost:8001/api"
r = requests.post(B+"/auth/admin-password-login", json={"email":"sksharmaconsultancy@gmail.com","password":"sharma123"})
H = {"Authorization":"Bearer "+(r.json().get("token") or r.json().get("session_token"))}
CID = "cmp_527fecdd7c"; UID = "user_44cd6f561da0"

# cleanup any old test punches on 2026-06-16/17
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
async def clean():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME","test_database")]
    n = await db.attendance.delete_many({"user_id":UID,"date":{"$in":["2026-06-16","2026-06-17"]}})
    print("pre-clean:", n.deleted_count)
asyncio.get_event_loop().run_until_complete(clean())

# GAJRAM-style scenario: Tue 16 Jun duty 07:56-19:59, OT 20:07 -> 07:59 next day
wb = Workbook(); ws = wb.active
ws.append(["Bio Code","Name","Date","In Time","Out Time","OT In","OT Out"])
ws.append(["", "SURENDRA SINGH", "16-06-2026", "07:56", "19:59", "20:07", "07:59"])
buf = io.BytesIO(); wb.save(buf)
b64 = base64.b64encode(buf.getvalue()).decode()

pv = requests.post(B+"/admin/punch-import/preview", headers=H,
                   json={"company_id":CID,"file_base64":b64}).json()
print("preview:", pv["summary"])
row = pv["rows"][0]
print("row times:", row.get("in_time"), row.get("out_time"), row.get("ot_in_time"), row.get("ot_out_time"), row["status"])

cm = requests.post(B+"/admin/punch-import/commit", headers=H,
                   json={"company_id":CID,"rows":[r_ for r_ in pv["rows"] if r_["status"]=="matched"]}).json()
print("commit:", cm)

g = requests.get(f"{B}/admin/attendance/monthly-grid/{CID}/2026-06", headers=H).json()
er = next(x for x in g["employees"] if x["user_id"]==UID)
for d in ("16","17"):
    c = er["days"].get(d) or {}
    print(f"day{d}:", {k:c.get(k) for k in ("in","out","ot_in","ot_out","duty_hours","ot_hours","hours","present")})

asyncio.get_event_loop().run_until_complete(clean())
print("post-clean done")
