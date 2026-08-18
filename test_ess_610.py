"""Iter 610 — ESS backend E2E: profile, attendance, shift, salary/pf/esic,
requests (create -> admin approve applies correction), notifications."""
import sys
import time
import hashlib
import requests
from pymongo import MongoClient

BASE = "http://localhost:8001/api"
mdb = MongoClient("mongodb://localhost:27017")["test_database"]
ok = fail = 0


def check(n, c, x=""):
    global ok, fail
    ok, fail = (ok + 1, fail) if c else (ok, fail + 1)
    print(("  ✅ " if c else "  ❌ ") + n, x if not c else "")


r = requests.post(f"{BASE}/auth/pin-login", json={"login_id": "TEST50", "pin": "123456"})
emp = r.json()["session_token"]
j = requests.post(f"{BASE}/auth/admin-password-login",
                  json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"}).json()
row = mdb.twofa_pending.find_one({"pending_id": j["pending_token"]})
code = next(f"{i:06d}" for i in range(1000000)
            if hashlib.sha256(f"{i:06d}".encode()).hexdigest() == row["otp_hash"])
adm = requests.post(f"{BASE}/auth/2fa/verify",
                    json={"pending_token": j["pending_token"], "otp": code}).json()["session_token"]
E, A = {"Authorization": f"Bearer {emp}"}, {"Authorization": f"Bearer {adm}"}
print("logins OK")

r = requests.get(f"{BASE}/ess/profile", headers=E)
check("profile", r.status_code == 200 and r.json()["profile"].get("employee_code") == "50", r.text[:120])

month = time.strftime("%Y-%m")
r = requests.get(f"{BASE}/ess/attendance?month={month}", headers=E)
check("attendance month", r.status_code == 200 and "days" in r.json(), r.text[:120])

r = requests.get(f"{BASE}/ess/shift", headers=E)
check("shift roster", r.status_code == 200 and len(r.json()["roster"]) >= 7, r.text[:120])

r = requests.get(f"{BASE}/ess/salary", headers=E)
check("salary/pf/esic", r.status_code == 200 and "months" in r.json() and "pf" in r.json(), r.text[:150])

# attendance correction request
r = requests.post(f"{BASE}/ess/requests", headers=E, json={
    "type": "attendance_correction", "reason": "Forgot OUT punch (iter610 test)",
    "payload": {"date": "2026-06-10", "requested_out": "2026-06-10T18:05:00+05:30"}})
check("create correction req", r.status_code == 200, r.text[:150])
rid = r.json()["request"]["request_id"]
rno = r.json()["request"]["request_no"]

# profile change request
r = requests.post(f"{BASE}/ess/requests", headers=E, json={
    "type": "profile_correction", "reason": "test",
    "payload": {"fields": {"email": "test50.new@example.com"}}})
check("create profile req", r.status_code == 200, r.text[:150])
rid2 = r.json()["request"]["request_id"]

# invalid field rejected
r = requests.post(f"{BASE}/ess/requests", headers=E, json={
    "type": "profile_correction", "payload": {"fields": {"designation": "CEO"}}})
check("non-editable field blocked", r.status_code == 400)

r = requests.get(f"{BASE}/ess/requests", headers=E)
check("my requests list", any(x["request_id"] == rid for x in r.json()["requests"]))

cid = mdb.users.find_one({"login_id": "TEST50"})["company_id"]
r = requests.get(f"{BASE}/ess/requests?scope=admin&company_id={cid}", headers=A)
check("admin queue", any(x["request_id"] == rid for x in r.json()["requests"]), r.text[:150])

before = mdb.attendance.count_documents({"user_id": mdb.users.find_one({"login_id": "TEST50"})["user_id"], "date": "2026-06-10"})
r = requests.post(f"{BASE}/ess/requests/{rid}/decide", headers=A,
                  json={"action": "approve", "remarks": "ok"})
check("approve correction", r.status_code == 200 and r.json().get("applied"), r.text[:150])
uid = mdb.users.find_one({"login_id": "TEST50"})["user_id"]
after = mdb.attendance.count_documents({"user_id": uid, "date": "2026-06-10"})
check("correction record ADDED (original kept)", after == before + 1, f"{before}->{after}")
check("source=manual_correction", mdb.attendance.find_one(
    {"user_id": uid, "date": "2026-06-10", "source": "manual_correction"}) is not None)

r = requests.post(f"{BASE}/ess/requests/{rid2}/decide", headers=A,
                  json={"action": "approve"})
check("approve profile change", r.status_code == 200 and "email" in str(r.json().get("applied")), r.text[:150])
check("email applied to user", mdb.users.find_one({"user_id": uid})["email"] == "test50.new@example.com")

# employee blocked from deciding
r = requests.post(f"{BASE}/ess/requests/{rid}/decide", headers=E, json={"action": "approve"})
check("employee cannot decide", r.status_code == 403)

# notifications: decision should have created personal notifications
r = requests.get(f"{BASE}/ess/notifications", headers=E)
j = r.json()
check("notifications feed + unread", r.status_code == 200 and j["unread"] >= 2, str(j)[:120])
check("decision notif present", any(rno in (n.get("title") or "") for n in j["notifications"]))
r = requests.post(f"{BASE}/ess/notifications/read", headers=E, json={})
r = requests.get(f"{BASE}/ess/notifications", headers=E)
check("mark all read", r.json()["unread"] == 0)

# isolation — another firm's admin data scope, employee cannot use scope=admin
r = requests.get(f"{BASE}/ess/requests?scope=admin", headers=E)
check("employee blocked from admin scope", r.status_code == 403)

# cleanup test artefacts
mdb.attendance.delete_many({"user_id": uid, "date": "2026-06-10", "source": "manual_correction"})
mdb.ess_requests.delete_many({"request_id": {"$in": [rid, rid2]}})
mdb.users.update_one({"user_id": uid}, {"$unset": {"email": ""}})
print(f"\nRESULT: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
