"""Iter 585 — RBAC Phase 1 automated authorization tests (15 scenarios)."""
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


# ── Engine unit tests (shared/authz.py — same code the APIs use)
from shared.authz import authorize, has_permission, employee_in_scope, scope_filter
from fastapi import HTTPException


def denied(fn):
    try:
        fn()
        return False
    except HTTPException as e:
        return e.status_code == 403


SUPER = {"role": "super_admin", "user_id": "su1"}
SUB_OK = {"role": "sub_admin", "user_id": "sub1", "sub_admin_company_scope": "restricted",
          "sub_admin_company_ids": [CID], "sub_admin_permissions": ["employees:read", "employees:write"]}
CA = {"role": "company_admin", "user_id": "ca1", "company_id": CID}
EMP_A = {"role": "employee", "user_id": "e1", "company_id": CID}
VIEW_ONLY = {**SUB_OK, "sub_admin_permissions": ["salary_process:view"]}
SCOPED = {**SUB_OK, "branch_scope": {"all": False, "ids": ["br1"]},
          "department_scope": {"all": False, "ids": ["dept1"]}}

check("1 Super Admin → allowed", not denied(lambda: authorize(SUPER, "salary_process", "delete", company_id="anything")))
check("2 Sub Admin assigned firm → allowed", not denied(lambda: authorize(SUB_OK, "employees", "view", company_id=CID)))
check("3 Sub Admin unassigned firm → 403", denied(lambda: authorize(SUB_OK, "employees", "view", company_id="cmp_other")))
check("4 Client Admin own firm → allowed", not denied(lambda: authorize(CA, "employees", "edit", company_id=CID)))
check("5 Client Admin other firm → 403", denied(lambda: authorize(CA, "employees", "view", company_id="cmp_other")))
check("6 assigned branch → allowed", not denied(lambda: authorize({**SCOPED, "sub_admin_permissions": ["employees:read"]}, "employees", "view", company_id=CID, branch_id="br1")))
check("7 unauthorized branch → 403", denied(lambda: authorize(SCOPED, "employees", "view", company_id=CID, branch_id="br2")))
check("8 assigned department → allowed", not denied(lambda: authorize({**SCOPED, "sub_admin_permissions": ["employees:read"]}, "employees", "view", company_id=CID, department_id="dept1")))
check("9 unauthorized department → 403", denied(lambda: authorize(SCOPED, "employees", "view", company_id=CID, department_id="dept2")))
check("10 View w/o Edit → Edit 403", denied(lambda: authorize(VIEW_ONLY, "salary_process", "edit", company_id=CID)))
check("11 View w/o Export → Export 403",
      denied(lambda: authorize({**SUB_OK, "sub_admin_permissions": ["salary_process:view"]}, "salary_process", "export", company_id=CID)))
check("12 employee → another employee record → denied",
      not employee_in_scope(EMP_A, {"user_id": "e2", "company_id": CID}))
check("14 unauthorized salary access → 403", denied(lambda: authorize(SUB_OK, "salary_process", "view", company_id=CID)))
check("15 cross-firm export → 403", denied(lambda: authorize(SUB_OK, "reports", "export", company_id="cmp_other")))
# legacy migration: read→view+export, write→add+edit+delete+approve
check("migration read→view+export", has_permission(SUB_OK, "employees", "view") and has_permission(SUB_OK, "employees", "export"))
check("migration write→add+edit+delete+approve",
      all(has_permission(SUB_OK, "employees", a) for a in ("add", "edit", "delete", "approve")))
check("granular view does NOT grant export", not has_permission(VIEW_ONLY, "salary_process", "export"))

# ── API tests (13: direct API/ID manipulation)
# Department master + migration
r = requests.post(f"{BASE}/admin/departments", headers=SA,
                  json={"company_id": CID, "name": "RBAC-HR-585"})
dep = (r.json() or {}).get("department") or {}
check("department create", r.status_code == 200 and dep.get("department_id"), r.text[:150])
r = requests.post(f"{BASE}/admin/departments/migrate-from-employees", headers=SA, json={"company_id": CID})
check("department migration runs", r.status_code == 200, r.text[:150])

# Branch + scoped sub-admin end-to-end
db.branches.update_one({"branch_id": "br_rbac1", "company_id": CID},
                       {"$set": {"branch_id": "br_rbac1", "company_id": CID,
                                 "name": "RBAC Branch", "status": "active"}}, upsert=True)
uid_scope = "user_44cd6f561da0"
db.users.update_one({"user_id": uid_scope}, {"$set": {"branch_id": "br_rbac1",
                                                      "department_id": dep.get("department_id")}})
# create a throwaway sub_admin with restricted scope
sub_id = f"user_rbac_{uuid.uuid4().hex[:6]}"
db.users.insert_one({"user_id": sub_id, "role": "sub_admin", "name": "RBAC Sub",
                     "email": f"{sub_id}@t.co", "active": True,
                     "sub_admin_company_scope": "restricted",
                     "sub_admin_company_ids": [CID],
                     "sub_admin_permissions": ["employees:read", "employees:write"],
                     "created_at": dtm.datetime.utcnow().isoformat()})
tok = f"rbactok_{uuid.uuid4().hex[:8]}"
db.user_sessions.insert_one({"session_token": tok, "user_id": sub_id,
                             "created_at": dtm.datetime.utcnow().isoformat(),
                             "expires_at": "2027-01-01T00:00:00+00:00"})
SUBH = {"Authorization": f"Bearer {tok}"}

# scope assignment via API (validation: bad branch rejected)
r = requests.patch(f"{BASE}/admin/access/user-scope", headers=SA,
                   json={"user_id": sub_id,
                         "branch_scope": {"all": False, "ids": ["br_of_other_firm"]}})
check("scope validation rejects foreign branch", r.status_code == 400, r.text[:150])
r = requests.patch(f"{BASE}/admin/access/user-scope", headers=SA,
                   json={"user_id": sub_id,
                         "branch_scope": {"all": False, "ids": ["br_rbac1"]},
                         "department_scope": {"all": False, "ids": [dep["department_id"]]}})
check("scope assigned", r.status_code == 200, r.text[:200])

# employee list is server-side scoped
r = requests.get(f"{BASE}/admin/employees?company_id={CID}", headers=SUBH)
emps = (r.json() or {}).get("employees") or []
in_scope = all(e.get("branch_id") == "br_rbac1" and e.get("department_id") == dep["department_id"] for e in emps)
check("13a employee list scoped server-side", r.status_code == 200 and len(emps) >= 1 and in_scope,
      f"{r.status_code} n={len(emps)}")
# ID manipulation: employee outside scope → 403
out_emp = db.users.find_one({"company_id": CID, "role": "employee",
                             "user_id": {"$ne": uid_scope}}, {"user_id": 1})
r = requests.get(f"{BASE}/admin/employees/{out_emp['user_id']}/profile", headers=SUBH)
check("13b ID manipulation → 403", r.status_code == 403, f"{r.status_code} {r.text[:100]}")
r = requests.get(f"{BASE}/admin/employees/{uid_scope}/profile", headers=SUBH)
check("13c in-scope employee profile → 200", r.status_code == 200, f"{r.status_code}")
# super admin unaffected
r = requests.get(f"{BASE}/admin/employees/{out_emp['user_id']}/profile", headers=SA)
check("super admin unrestricted", r.status_code == 200)

# Access Preview
r = requests.get(f"{BASE}/admin/access-preview/users?q=RBAC", headers=SA)
check("preview user search", r.status_code == 200 and any(u["user_id"] == sub_id for u in r.json()["users"]), r.text[:150])
r = requests.get(f"{BASE}/admin/access-preview/{sub_id}", headers=SA)
p = r.json()
check("preview effective firm/branch/dept scope",
      r.status_code == 200 and p["firm_scope"]["mode"] == "RESTRICTED_FIRMS"
      and p["branch_scope"]["mode"] == "SELECTED_BRANCHES"
      and p["department_scope"]["mode"] == "SELECTED_DEPARTMENTS", r.text[:250])
check("preview matrix matches engine",
      p["matrix"]["employees"]["view"] is True and p["matrix"]["employees"]["edit"] is True
      and p["matrix"]["salary_process"]["view"] is False, str(p["matrix"])[:200])
check("preview employee count scoped", p["counts"]["employees"] == 1, str(p["counts"]))
# non-super-admin cannot preview
r = requests.get(f"{BASE}/admin/access-preview/{sub_id}", headers=SUBH)
check("preview blocked for non-super-admin", r.status_code == 403, f"{r.status_code}")
# preview change reflects immediately after scope change
requests.patch(f"{BASE}/admin/access/user-scope", headers=SA,
               json={"user_id": sub_id, "branch_scope": {"all": True}})
r = requests.get(f"{BASE}/admin/access-preview/{sub_id}", headers=SA)
check("preview reflects scope change immediately",
      r.json()["branch_scope"]["mode"] == "ALL_BRANCHES", r.text[:150])
# audit events written
n = db.activity_log.count_documents({"action": {"$in": ["DATA_SCOPE_CHANGED", "ACCESS_PREVIEW"]}})
check("scope-change + preview audit logged", n >= 3, f"n={n}")

# cleanup
db.users.delete_one({"user_id": sub_id})
db.user_sessions.delete_one({"session_token": tok})
db.users.update_one({"user_id": uid_scope}, {"$unset": {"branch_id": "", "department_id": ""}})
db.branches.delete_one({"branch_id": "br_rbac1"})
db.departments.delete_one({"department_id": dep.get("department_id")})

print(f"\n=== {ok} passed, {fail} failed ===")
sys.exit(1 if fail else 0)
