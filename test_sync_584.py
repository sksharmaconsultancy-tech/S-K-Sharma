"""Iter 584 acceptance tests — Device Sync Engine manual register/delete."""
import sys, uuid, datetime as dtm
import requests
from pymongo import MongoClient

BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
AH = {"Authorization": "Bearer smoketok_581_cdba55cd"}
db = MongoClient("mongodb://localhost:27017")["test_database"]
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(("PASS" if cond else "FAIL") + f": {name} {'' if cond else extra}")


# Seed: 2 machines + machine-user mapping for pin 9950
db.biometric_devices.delete_many({"company_id": CID, "serial_number": {"$in": ["TESTSN01", "TESTSN02"]}})
now = dtm.datetime.now(dtm.timezone.utc).isoformat()
db.biometric_devices.insert_many([
    {"device_id": "d_t1", "company_id": CID, "serial_number": "TESTSN01",
     "name": "Machine-01", "model": "ZKTeco K40", "location": "Gate 1",
     "enabled": True, "sync_enabled": True, "last_seen": now},
    {"device_id": "d_t2", "company_id": CID, "serial_number": "TESTSN02",
     "name": "Machine-02", "model": "eSSL X990", "location": "Gate 2",
     "enabled": True, "sync_enabled": True, "last_seen": "2026-01-01T00:00:00Z"},
])
db.users.update_one({"user_id": "user_44cd6f561da0"}, {"$set": {"bio_code": "9950", "card_no": "CARD9950"}})
db.biometric_machine_users.delete_many({"company_id": CID, "pin": "9950"})
db.biometric_machine_users.insert_one(
    {"company_id": CID, "pin": "9950", "device_serial": "TESTSN02", "name": "SURENDRA"})
db.sync_jobs.delete_many({"company_id": CID})
db.sync_settings.update_one({"company_id": CID}, {"$set": {
    "company_id": CID, "manual_employee_registration": False,
    "manual_employee_delete": False, "enable_auto_sync": True}}, upsert=True)

# Test 1 — Employee create must NOT queue any sync job (auto blocked even
# though a stale settings doc says enable_auto_sync True).
r = requests.post(f"{BASE}/admin/employees", headers=AH, json={
    "company_id": CID, "name": "Sync Test Emp 584", "phone": "9000000584",
    "employee_code": "SYNC584", "bio_code": "8584"})
print("create emp:", r.status_code, r.text[:120])
n = db.sync_jobs.count_documents({"company_id": CID})
check("T1 employee create → NO sync job", n == 0, f"jobs={n}")

# Settings API: auto sync locked
r = requests.get(f"{BASE}/sync/settings?company_id={CID}", headers=AH)
s = r.json()
check("settings: auto_master_sync DISABLED + enable_auto_sync False",
      s.get("auto_master_sync") == "DISABLED" and s.get("enable_auto_sync") is False, str(s)[:200])
r = requests.put(f"{BASE}/sync/settings", headers=AH,
                 json={"company_id": CID, "enable_auto_sync": True})
check("PUT cannot re-enable auto sync", r.json().get("enable_auto_sync") is False, r.text[:150])

# Test 8 — legacy master push endpoints blocked
r = requests.post(f"{BASE}/sync/all", headers=AH, json={"company_id": CID})
check("T8 /sync/all → 403 MASTER_DATA_DEVICE_SYNC_DISABLED",
      r.status_code == 403 and "MASTER_DATA_DEVICE_SYNC_DISABLED" in r.text, f"{r.status_code} {r.text[:120]}")
r = requests.post(f"{BASE}/sync/employee", headers=AH,
                  json={"company_id": CID, "user_id": "user_44cd6f561da0"})
check("/sync/employee → 403 blocked", r.status_code == 403 and "MASTER_DATA" in r.text, r.text[:120])

# Manual registration while feature OFF → 403
r = requests.post(f"{BASE}/device-sync/manual-register-employee", headers=AH,
                  json={"company_id": CID, "employee_code": "50", "device_serials": ["TESTSN01"]})
check("register w/ feature OFF → MANUAL_EMPLOYEE_REGISTRATION_DISABLED",
      r.status_code == 403 and "MANUAL_EMPLOYEE_REGISTRATION_DISABLED" in r.text, r.text[:150])

# Enable both features via API
r = requests.put(f"{BASE}/sync/settings", headers=AH, json={
    "company_id": CID, "manual_employee_registration": True, "manual_employee_delete": True})
check("enable manual features", r.json().get("manual_employee_registration") is True, r.text[:150])

# Preview
r = requests.get(f"{BASE}/device-sync/registration-preview?company_id={CID}&employee_code=50", headers=AH)
p = r.json()
check("preview: employee + device_user_id", r.status_code == 200
      and p["employee"]["device_user_id"] == "9950", r.text[:200])
check("preview: honest template capability",
      p["fields"]["fingerprint"]["available"] is False and p["fields"]["card"]["available"] is True, str(p["fields"])[:200])
mach = {m["serial_number"]: m for m in p["machines"]}
check("preview: dup flag on TESTSN02 + online status",
      mach["TESTSN02"]["already_registered"] is True and mach["TESTSN01"]["online"] is True, str(mach)[:250])

# Test 2 — Manual registration on Machine-01
r = requests.post(f"{BASE}/device-sync/manual-register-employee", headers=AH,
                  json={"company_id": CID, "employee_code": "50",
                        "device_serials": ["TESTSN01"], "fields": ["card"]})
j = r.json()
check("T2 manual register queued", r.status_code == 200 and j.get("status") == "QUEUED", r.text[:200])
job = db.sync_jobs.find_one({"job_id": j.get("job_id")})
check("T2 job sync_type/source/dest + target machine",
      job and job["sync_type"] == "MANUAL_EMPLOYEE_REGISTRATION"
      and job["source_type"] == "PORTAL" and job["targets"] == ["TESTSN01"], str(job)[:200])

# Duplicate protection → 409 on TESTSN02
r = requests.post(f"{BASE}/device-sync/manual-register-employee", headers=AH,
                  json={"company_id": CID, "employee_code": "50", "device_serials": ["TESTSN02"]})
check("duplicate registration → 409", r.status_code == 409, f"{r.status_code} {r.text[:150]}")
r = requests.post(f"{BASE}/device-sync/manual-register-employee", headers=AH,
                  json={"company_id": CID, "employee_code": "50",
                        "device_serials": ["TESTSN02"], "update_existing": True})
check("update_existing allows re-register", r.status_code == 200, r.text[:150])

# Test 3 — employee update → no new job beyond the manual ones
before = db.sync_jobs.count_documents({"company_id": CID})
emp584 = db.users.find_one({"company_id": CID, "employee_code": "SYNC584"}, {"user_id": 1})
if emp584:
    requests.patch(f"{BASE}/admin/employees/{emp584['user_id']}/profile", headers=AH,
                   json={"name": "Sync Test Emp 584 Updated"})
after = db.sync_jobs.count_documents({"company_id": CID})
check("T3 employee update → no auto sync job", after == before, f"{before}->{after}")

# Test 4 — Manual delete from one machine (payroll untouched)
r = requests.post(f"{BASE}/device-sync/manual-delete-employee", headers=AH,
                  json={"company_id": CID, "employee_code": "50", "device_serials": ["TESTSN01"]})
j = r.json()
check("T4 manual delete queued + payroll_unchanged flag",
      r.status_code == 200 and j.get("payroll_unchanged") is True and j["machines"] == ["TESTSN01"], r.text[:200])
u = db.users.find_one({"user_id": "user_44cd6f561da0"}, {"name": 1})
check("T4 payroll employee remains", bool(u))

# delete from all registered needs confirm code
r = requests.post(f"{BASE}/device-sync/manual-delete-employee", headers=AH,
                  json={"company_id": CID, "employee_code": "50", "all_registered": True})
check("all_registered w/o confirm_code → 400", r.status_code == 400, r.text[:120])
r = requests.post(f"{BASE}/device-sync/manual-delete-employee", headers=AH,
                  json={"company_id": CID, "employee_code": "50", "all_registered": True,
                        "confirm_code": "50"})
check("all_registered with confirm_code ok", r.status_code == 200, r.text[:150])

# Test 5 — deactivation → no machine delete
before = db.sync_jobs.count_documents({"company_id": CID, "sync_type": {"$exists": False}})
db.users.update_one({"company_id": CID, "employee_code": "SYNC584"}, {"$set": {"active": False}})
check("T5 deactivate → no auto machine delete",
      db.sync_jobs.count_documents({"company_id": CID, "sync_type": {"$exists": False}}) == before)

# Activity feed
r = requests.get(f"{BASE}/device-sync/activity?company_id={CID}", headers=AH)
check("activity lists manual jobs", r.status_code == 200 and len(r.json()["jobs"]) >= 3, r.text[:150])

# Test 6 — machine-to-machine sync still works
r = requests.post(f"{BASE}/sync/machines", headers=AH, json={"company_id": CID})
check("T6 machine-to-machine sync works", r.status_code == 200 and r.json().get("ok"), r.text[:150])

# cleanup
db.biometric_devices.delete_many({"serial_number": {"$in": ["TESTSN01", "TESTSN02"]}})
db.biometric_machine_users.delete_many({"company_id": CID, "pin": "9950"})
db.sync_jobs.delete_many({"company_id": CID})
db.machine_sync_runs.delete_many({"company_id": CID})
db.biometric_device_cmds.delete_many({"device_serial": {"$in": ["TESTSN01", "TESTSN02"]}})
if emp584:
    db.users.delete_one({"user_id": emp584["user_id"]})

print(f"\n=== {ok} passed, {fail} failed ===")
sys.exit(1 if fail else 0)
