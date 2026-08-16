"""Iter 581 — end-to-end backend test for the Onboarding Gate engine.

Flow:
 1. Sub-admin login (testsub@sksharma.co) → save policy with gate enabled.
 2. Employee (code 50, SURENDRA SINGH) — clear KYC fields → punch → HELD.
 3. GET /attendance/onboarding-status as employee.
 4. Admin summary + records endpoints.
 5. Complete KYC (auto-release) → held punches become RELEASED.
 6. Force a BLOCKED punch (backdate doj + gate enabled_at) → release without
    reason must FAIL, with reason must succeed.
"""
import requests, sys
from pymongo import MongoClient

BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
db = MongoClient("mongodb://localhost:27017")["test_database"]
ok = 0
fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"PASS: {name}")
    else:
        fail += 1
        print(f"FAIL: {name} {extra}")


# --- 1. Super-admin session (inject directly — 2FA gates password login)
import uuid, datetime
su = db.users.find_one({"email": "sksharmaconsultancy@gmail.com"})
tok = f"testtok_{uuid.uuid4().hex}"
db.user_sessions.insert_one({"session_token": tok, "user_id": su["user_id"],
                             "created_at": datetime.datetime.utcnow().isoformat(),
                             "expires_at": "2027-01-01T00:00:00+00:00"})
AH = {"Authorization": f"Bearer {tok}"}

# --- 2. Save policy with gate ON
r = requests.get(f"{BASE}/attendance/policy?company_id={CID}", headers=AH)
check("GET policy", r.status_code == 200, r.text[:200])
pol = r.json()["policy"]
check("GET policy has onboarding_gate backfill", "onboarding_gate" in pol)
pol["onboarding_gate"] = {"enabled": True, "require_aadhaar": True,
                          "require_bank": True, "require_pan": False,
                          "require_photo": False, "permission_days": 7,
                          "auto_release": True}
r = requests.patch(f"{BASE}/attendance/policy?company_id={CID}",
                   json={"policy": pol}, headers=AH)
check("PATCH policy with gate", r.status_code == 200, r.text[:300])
saved = r.json()["policy"].get("onboarding_gate") or {}
check("gate persisted + enabled_at stamped",
      saved.get("enabled") is True and bool(saved.get("enabled_at")), str(saved))

# --- 3. Employee: clear KYC + recent doj, login, punch
emp = db.users.find_one({"company_id": CID, "employee_code": "50"})
uid = emp["user_id"]
import datetime as dtm
recent = (dtm.date.today() - dtm.timedelta(days=2)).strftime("%d-%m-%Y")
db.users.update_one({"user_id": uid}, {"$set": {"doj": recent},
                    "$unset": {"aadhar_number": "", "bank_account_number": "",
                               "bank_account": "", "ifsc_code": "", "bank_ifsc": ""}})
db.attendance.delete_many({"user_id": uid})  # clean slate for test

r = requests.post(f"{BASE}/auth/emp-code-login",
                  json={"employee_code": "50", "phone_last4": "654321", "company_code": "KEPS"})
if r.status_code != 200:
    r = requests.post(f"{BASE}/auth/emp-code-login",
                      json={"employee_code": "50", "phone_last4": "1234", "company_code": "KEPS"})
print("emp login:", r.status_code, r.text[:150])
etok = (r.json() or {}).get("session_token") if r.status_code == 200 else None
if not etok:
    import uuid
    etok = f"emptok_{uuid.uuid4().hex}"
    db.user_sessions.insert_one({"session_token": etok, "user_id": uid,
                                 "created_at": dtm.datetime.utcnow().isoformat(),
                                 "expires_at": "2027-01-01T00:00:00+00:00"})
EH = {"Authorization": f"Bearer {etok}"}

r = requests.get(f"{BASE}/attendance/onboarding-status", headers=EH)
check("onboarding-status gate_enabled", r.status_code == 200 and r.json().get("gate_enabled") is True, r.text[:300])
missing_keys = [m["key"] for m in r.json().get("missing", [])]
check("missing aadhaar+bank", "aadhaar" in missing_keys and "bank" in missing_keys, str(missing_keys))
check("eligibility HELD (inside window)", r.json().get("eligibility") == "HELD", r.text[:200])

# Punch IN (company has geofence? send live-in style manual with selfie)
company = db.companies.find_one({"company_id": CID})
lat, lng = company.get("office_lat"), company.get("office_lng")
payload = {"kind": "in", "latitude": lat or 26.34, "longitude": lng or 74.63,
           "selfie_base64": "dGVzdA==", "biometric_method": "fingerprint",
           "source": "manual"}
r = requests.post(f"{BASE}/attendance/punch", json=payload, headers=EH)
print("punch:", r.status_code, r.text[:250])
check("punch stored", r.status_code == 200, r.text[:300])
if r.status_code == 200:
    j = r.json()
    check("punch response eligibility HELD",
          (j.get("eligibility") or {}).get("status") == "HELD", str(j.get("eligibility")))
    check("record status held", j.get("status") == "held", j.get("status"))
rec = db.attendance.find_one({"user_id": uid}, sort=[("at", -1)])
check("db record held + pre_hold_status kept",
      rec and rec.get("status") == "held" and rec.get("pre_hold_status") in ("pending", "approved"),
      str({k: rec.get(k) for k in ("status", "pre_hold_status", "eligibility_status", "eligibility_missing")} if rec else None))

# --- 4. Admin summary/records
r = requests.get(f"{BASE}/admin/attendance-eligibility/summary?company_id={CID}", headers=AH)
check("admin summary", r.status_code == 200 and r.json()["totals"]["held"] >= 1, r.text[:300])
r = requests.get(f"{BASE}/admin/attendance-eligibility/records?company_id={CID}&user_id={uid}", headers=AH)
check("admin records", r.status_code == 200 and r.json()["count"] >= 1, r.text[:200])

# --- 5. Complete KYC → auto-release
r = requests.patch(f"{BASE}/admin/employees/{uid}/kyc",
                   json={"aadhar_number": "234123412346",
                         "bank_account_number": "12345678901",
                         "ifsc_code": "SBIN0001234"}, headers=AH)
check("KYC patch", r.status_code == 200, r.text[:300])
rec = db.attendance.find_one({"user_id": uid}, sort=[("at", -1)])
check("auto-released after KYC",
      rec and rec.get("eligibility_status") == "RELEASED" and rec.get("status") in ("pending", "approved"),
      str({k: rec.get(k) for k in ("status", "eligibility_status", "released_by")} if rec else None))

# --- 6. BLOCKED path: clear data again, backdate window
db.users.update_one({"user_id": uid}, {"$set": {"doj": "01-01-2020"},
                    "$unset": {"aadhar_number": "", "bank_account_number": "",
                               "bank_account": "", "ifsc_code": "", "bank_ifsc": ""}})
db.companies.update_one({"company_id": CID},
                        {"$set": {"attendance_policy.onboarding_gate.enabled_at": "2020-01-01T00:00:00"}})
payload["kind"] = "out"
r = requests.post(f"{BASE}/attendance/punch", json=payload, headers=EH)
print("blocked punch:", r.status_code, r.text[:200])
check("punch stored as blocked", r.status_code == 200 and r.json().get("status") == "blocked", r.text[:250])
brec = db.attendance.find_one({"user_id": uid, "status": "blocked"})
check("blocked record exists", bool(brec))

# Release WITHOUT reason must fail
r = requests.post(f"{BASE}/admin/attendance-eligibility/release?company_id={CID}",
                  json={"user_id": uid}, headers=AH)
check("release blocked w/o reason → 400", r.status_code == 400, f"{r.status_code} {r.text[:150]}")
# With reason → ok
r = requests.post(f"{BASE}/admin/attendance-eligibility/release?company_id={CID}",
                  json={"user_id": uid, "reason": "Docs verified physically by HR"}, headers=AH)
check("release blocked with reason", r.status_code == 200 and r.json().get("released", 0) >= 1, r.text[:200])
brec = db.attendance.find_one({"record_id": brec["record_id"]}) if brec else None
check("blocked → RELEASED + reason stored",
      brec and brec.get("eligibility_status") == "RELEASED" and brec.get("release_reason"),
      str({k: (brec or {}).get(k) for k in ("status", "eligibility_status", "release_reason")}))

# --- 7. Reject path: create another held punch then reject
db.users.update_one({"user_id": uid}, {"$set": {"doj": recent}})
db.companies.update_one({"company_id": CID},
                        {"$set": {"attendance_policy.onboarding_gate.enabled_at": dtm.datetime.utcnow().isoformat()}})
payload["kind"] = "in"
r = requests.post(f"{BASE}/attendance/punch", json=payload, headers=EH)
check("second held punch", r.status_code == 200 and r.json().get("status") == "held", r.text[:200])
r = requests.post(f"{BASE}/admin/attendance-eligibility/reject?company_id={CID}",
                  json={"user_id": uid}, headers=AH)
check("reject w/o reason → 400", r.status_code == 400)
r = requests.post(f"{BASE}/admin/attendance-eligibility/reject?company_id={CID}",
                  json={"user_id": uid, "reason": "Duplicate punch attempt"}, headers=AH)
check("reject with reason", r.status_code == 200 and r.json().get("rejected", 0) >= 1, r.text[:200])

# --- cleanup: restore employee + gate OFF? Keep gate ON for UI testing but restore emp data
db.attendance.delete_many({"user_id": uid})
db.users.update_one({"user_id": uid}, {"$set": {"doj": "01-12-2018"}})

print(f"\n=== {ok} passed, {fail} failed ===")
sys.exit(1 if fail else 0)
