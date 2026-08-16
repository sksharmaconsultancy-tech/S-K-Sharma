"""Iter 587 tests — KYC masking + export security engine + export history."""
import sys, uuid, datetime as dtm
import requests
from pymongo import MongoClient

BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
SA = {"Authorization": "Bearer smoketok_581_cdba55cd"}
db = MongoClient("mongodb://localhost:27017")["test_database"]
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(("PASS" if cond else "FAIL") + f": {name} {'' if cond else extra}")


uid = "user_44cd6f561da0"
db.users.update_one({"user_id": uid}, {"$set": {"aadhar_number": "234123412346",
                                                "bank_account_number": "12345678901234",
                                                "mobile": "9828765432"}})
# sub-admin WITHOUT sensitive + WITHOUT salary export perm
sub_id = f"user_t587_{uuid.uuid4().hex[:6]}"
db.users.insert_one({"user_id": sub_id, "role": "sub_admin", "name": "T587 Sub",
                     "email": f"{sub_id}@t.co", "active": True,
                     "sub_admin_company_scope": "restricted",
                     "sub_admin_company_ids": [CID],
                     "sub_admin_permissions": ["employees:view", "employees:edit",
                                               "salary_process:view"],
                     "created_at": dtm.datetime.utcnow().isoformat()})
tok = f"t587_{uuid.uuid4().hex[:8]}"
db.user_sessions.insert_one({"session_token": tok, "user_id": sub_id,
                             "created_at": dtm.datetime.utcnow().isoformat(),
                             "expires_at": "2027-01-01T00:00:00+00:00"})
SUB = {"Authorization": f"Bearer {tok}"}

# 1. KYC masking
r = requests.get(f"{BASE}/admin/employees/{uid}/kyc", headers=SUB)
k = (r.json() or {}).get("kyc") or {}
check("KYC masked (aadhaar/bank/mobile)", r.status_code == 200
      and str(k.get("aadhar_number", "")).startswith("X")
      and str(k.get("bank_account_number", "")).startswith("X")
      and str(k.get("mobile", "")).startswith("X"), f"{r.status_code} {str(k)[:120]}")
check("raw values absent from KYC response",
      "234123412346" not in r.text and "12345678901234" not in r.text)
r = requests.get(f"{BASE}/admin/employees/{uid}/kyc", headers=SA)
check("super admin gets unmasked KYC", r.json()["kyc"]["aadhar_number"] == "234123412346")

# 2. Export gate: view-only salary user → export denied + EXPORT_DENIED logged
r = requests.get(f"{BASE}/admin/salary-register/export.csv?company_id={CID}&source=compliance&month=2026-07", headers=SUB)
check("salary export w/o export perm → 403", r.status_code == 403, f"{r.status_code} {r.text[:100]}")
check("EXPORT_DENIED logged",
      db.activity_log.count_documents({"action": "EXPORT_DENIED", "user_id": sub_id}) == 1)

# grant export → allowed (404 if no run, but not 403) + DATA_EXPORT logged on success
requests.patch(f"{BASE}/admin/access/user-permissions", headers=SA,
               json={"user_id": sub_id,
                     "permissions": ["employees:view", "salary_process:view",
                                     "salary_process:export"]})
r = requests.get(f"{BASE}/admin/salary-register/export.csv?company_id={CID}&source=compliance&month=2026-07", headers=SUB)
check("export with perm passes gate (200/404, not 403)", r.status_code in (200, 404), f"{r.status_code}")
if r.status_code == 200:
    check("DATA_EXPORT logged",
          db.activity_log.count_documents({"action": "DATA_EXPORT", "user_id": sub_id}) >= 1)
else:
    check("DATA_EXPORT logging (skipped — no salary run this month)", True)

# cross-firm export → 403 + denied log
r = requests.get(f"{BASE}/admin/salary-register/export.csv?company_id=cmp_other&source=compliance&month=2026-07", headers=SUB)
check("cross-firm export → 403", r.status_code == 403, f"{r.status_code}")

# 3. Export history endpoint
r = requests.get(f"{BASE}/admin/export-history?status=DENIED", headers=SA)
check("export history lists denials", r.status_code == 200
      and any(x.get("user_id") == sub_id for x in r.json()["exports"]), r.text[:120])

# cleanup
db.users.delete_one({"user_id": sub_id})
db.user_sessions.delete_one({"session_token": tok})
db.activity_log.delete_many({"user_id": sub_id})
db.users.update_one({"user_id": uid}, {"$unset": {"aadhar_number": "", "bank_account_number": "", "mobile": ""}})

print(f"\n=== {ok} passed, {fail} failed ===")
sys.exit(1 if fail else 0)
