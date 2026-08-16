"""Iter 586 tests — scope wiring (attendance/salary), sensitive masking,
granular permission editor, backward-compat migration."""
import sys, uuid, datetime as dtm
import requests
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")
BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
SA = {"Authorization": "Bearer smoketok_581_cdba55cd"}
db = MongoClient("mongodb://localhost:27017")["test_database"]
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(("PASS" if cond else "FAIL") + f": {name} {'' if cond else extra}")


# setup: dept + branch + scoped sub-admin + one employee stamped
dep_id = f"dept_t586_{uuid.uuid4().hex[:6]}"
db.departments.insert_one({"department_id": dep_id, "company_id": CID,
                           "branch_id": None, "name": "T586", "status": "active",
                           "created_at": dtm.datetime.utcnow().isoformat()})
uid = "user_44cd6f561da0"
db.users.update_one({"user_id": uid}, {"$set": {"department_id": dep_id,
                                                "aadhar_number": "234123412346",
                                                "bank_account_number": "12345678901234"}})
sub_id = f"user_t586_{uuid.uuid4().hex[:6]}"
db.users.insert_one({"user_id": sub_id, "role": "sub_admin", "name": "T586 Sub",
                     "email": f"{sub_id}@t.co", "active": True,
                     "sub_admin_company_scope": "restricted",
                     "sub_admin_company_ids": [CID],
                     "sub_admin_permissions": ["employees:read", "employees:write",
                                               "attendance_policy:read", "salary_process:read"],
                     "department_scope": {"all": False, "ids": [dep_id]},
                     "created_at": dtm.datetime.utcnow().isoformat()})
tok = f"t586_{uuid.uuid4().hex[:8]}"
db.user_sessions.insert_one({"session_token": tok, "user_id": sub_id,
                             "created_at": dtm.datetime.utcnow().isoformat(),
                             "expires_at": "2027-01-01T00:00:00+00:00"})
SUB = {"Authorization": f"Bearer {tok}"}

# 1. attendance day-status scoped
today = dtm.date.today().isoformat()
r = requests.get(f"{BASE}/admin/attendance/day-status/{CID}?from_date={today}", headers=SUB)
rows = (r.json() or {}).get("rows") or (r.json() or {}).get("employees") or []
uids = {x.get("user_id") for x in rows}
check("attendance day-status scoped to dept", r.status_code == 200 and uids <= {uid},
      f"{r.status_code} n={len(rows)}")
r2 = requests.get(f"{BASE}/admin/attendance/day-status/{CID}?from_date={today}", headers=SA)
all_rows = (r2.json() or {}).get("rows") or (r2.json() or {}).get("employees") or []
check("super admin sees full attendance", len(all_rows) > len(rows), f"{len(all_rows)} vs {len(rows)}")

# 2. salary register scoped (rows filtered by scoped_user_id_set)
r = requests.get(f"{BASE}/admin/salary-register?company_id={CID}&source=compliance&month=2026-07", headers=SUB)
if r.status_code == 200 and (r.json() or {}).get("run"):
    reg_uids = {x.get("user_id") for x in r.json().get("rows") or []}
    check("salary register scoped", reg_uids <= {uid}, str(list(reg_uids))[:100])
else:
    check("salary register scoped (no run for month — endpoint ok)", r.status_code == 200, r.text[:100])

# 3. sensitive masking: sub WITHOUT sensitive_data:view gets masked values
r = requests.get(f"{BASE}/admin/employees/{uid}/profile", headers=SUB)
p = r.json()
check("masked aadhaar for non-sensitive user",
      r.status_code == 200 and str(p.get("aadhaar_no", "")).startswith("X")
      and p.get("sensitive_masked") is True,
      f"{r.status_code}")
check("masked keeps last 4", str(p.get("aadhaar_no", "")).endswith("2346"), p.get("aadhaar_no"))
check("raw value NOT in response", "234123412346" not in r.text)

# 4. grant sensitive via granular permission editor
r = requests.patch(f"{BASE}/admin/access/user-permissions", headers=SA,
                   json={"user_id": sub_id,
                         "permissions": ["employees:view", "employees:edit",
                                         "attendance_policy:view", "salary_process:view",
                                         "sensitive_data:view"]})
check("permission editor saves granular list", r.status_code == 200, r.text[:150])
r = requests.get(f"{BASE}/admin/employees/{uid}/profile", headers=SUB)
check("unmasked after sensitive_data:view granted",
      r.json().get("aadhaar_no") == "234123412346", str(r.json().get("aadhaar_no")))
n = db.activity_log.count_documents({"action": "SENSITIVE_DATA_VIEWED",
                                     "user_id": sub_id})
check("SENSITIVE_DATA_VIEWED audit logged", n == 1, f"n={n}")
requests.get(f"{BASE}/admin/employees/{uid}/profile", headers=SUB)
n2 = db.activity_log.count_documents({"action": "SENSITIVE_DATA_VIEWED", "user_id": sub_id})
check("audit deduped per day", n2 == 1, f"n2={n2}")
check("audit stores field NAMES not values",
      db.activity_log.find_one({"action": "SENSITIVE_DATA_VIEWED", "user_id": sub_id,
                                "detail.fields": "aadhaar_no"}) is not None
      and db.activity_log.find_one({"action": "SENSITIVE_DATA_VIEWED",
                                    "detail.fields": "234123412346"}) is None)
# granular: view-only now → edit action denied by engine
from shared.authz import authorize
from fastapi import HTTPException
u = db.users.find_one({"user_id": sub_id})
try:
    authorize(u, "employees", "delete", company_id=CID)
    check("granular edit-list excludes delete → 403", False)
except HTTPException as e:
    check("granular edit-list excludes delete → 403", e.status_code == 403)

# 5. backward-compat migration endpoint
r = requests.post(f"{BASE}/admin/access/migrate-sensitive-permission", headers=SA)
check("sensitive backward-compat migration runs", r.status_code == 200, r.text[:120])

# 6. PERMISSION_CHANGED audit
check("PERMISSION_CHANGED audited",
      db.activity_log.count_documents({"action": "PERMISSION_CHANGED"}) >= 1)

# cleanup
db.users.delete_one({"user_id": sub_id})
db.user_sessions.delete_one({"session_token": tok})
db.departments.delete_one({"department_id": dep_id})
db.users.update_one({"user_id": uid}, {"$unset": {"department_id": "", "aadhar_number": "",
                                                  "bank_account_number": ""}})
db.activity_log.delete_many({"user_id": sub_id})

print(f"\n=== {ok} passed, {fail} failed ===")
sys.exit(1 if fail else 0)
