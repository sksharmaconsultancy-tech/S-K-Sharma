"""Iter 587 tests — RBAC Phase 3 Maker-Checker workflow."""
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


def mk_sub(perms):
    uid = f"user_mc587_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({"user_id": uid, "role": "sub_admin", "name": f"MC {uid[-4:]}",
                         "email": f"{uid}@t.co", "active": True,
                         "sub_admin_company_scope": "restricted",
                         "sub_admin_company_ids": [CID],
                         "sub_admin_permissions": perms,
                         "created_at": dtm.datetime.utcnow().isoformat()})
    tok = f"mc587_{uuid.uuid4().hex[:8]}"
    db.user_sessions.insert_one({"session_token": tok, "user_id": uid,
                                 "created_at": dtm.datetime.utcnow().isoformat(),
                                 "expires_at": "2027-01-01T00:00:00+00:00"})
    return uid, {"Authorization": f"Bearer {tok}"}


maker_id, MK = mk_sub(["employees:view", "employees:edit", "employees:delete",
                       "salary_process:view", "salary_process:edit"])
checker_id, CK = mk_sub(["employees:view", "employees:approve",
                         "salary_process:view", "salary_process:approve",
                         "sensitive_data:view"])
# fresh test employee
emp_id = f"user_mcemp_{uuid.uuid4().hex[:6]}"
db.users.insert_one({"user_id": emp_id, "role": "employee", "name": "MC Test Emp",
                     "employee_code": "MC587", "company_id": CID, "active": True,
                     "salary_monthly": 10000,
                     "bank_account_number": "11112222333344",
                     "created_at": dtm.datetime.utcnow().isoformat()})

# ensure defaults ON
requests.put(f"{BASE}/admin/maker-checker/settings", headers=SA,
             json={"enabled": True, "actions": {"salary_change": True,
                                                "bank_change": True,
                                                "employee_delete": True}})

# 1. salary change by maker → staged, data unchanged
r = requests.patch(f"{BASE}/admin/employees/{emp_id}/salary", headers=MK,
                   json={"salary_monthly": 15000, "notes": "hike"})
j = r.json()
apr1 = j.get("approval_id")
check("salary change staged", r.status_code == 200 and j.get("approval_required") and apr1,
      f"{r.status_code} {r.text[:150]}")
check("salary UNCHANGED in DB",
      db.users.find_one({"user_id": emp_id})["salary_monthly"] == 10000)

# 2. duplicate request deduped
r = requests.patch(f"{BASE}/admin/employees/{emp_id}/salary", headers=MK,
                   json={"salary_monthly": 16000})
check("duplicate staged request deduped", r.json().get("approval_id") == apr1)

# 3. maker cannot approve own
r = requests.post(f"{BASE}/admin/approvals/{apr1}/decide", headers=MK,
                  json={"decision": "approve"})
check("maker cannot approve own → 403", r.status_code == 403, f"{r.status_code}")

# 4. checker approves → applied + history
r = requests.post(f"{BASE}/admin/approvals/{apr1}/decide", headers=CK,
                  json={"decision": "approve", "reason": "ok"})
check("checker approves salary", r.status_code == 200 and r.json().get("status") == "APPROVED",
      f"{r.status_code} {r.text[:120]}")
check("salary APPLIED after approval",
      db.users.find_one({"user_id": emp_id})["salary_monthly"] == 15000)
check("salary_history carries approval_id",
      db.salary_history.count_documents({"user_id": emp_id, "approval_id": apr1}) == 1)

# 5. super admin salary change bypasses (direct apply)
r = requests.patch(f"{BASE}/admin/employees/{emp_id}/salary", headers=SA,
                   json={"salary_monthly": 15500})
check("super admin bypasses maker-checker",
      r.status_code == 200 and not r.json().get("approval_required")
      and db.users.find_one({"user_id": emp_id})["salary_monthly"] == 15500)

# 6. bank change staged; non-bank field applies immediately
r = requests.patch(f"{BASE}/admin/employees/{emp_id}/kyc", headers=MK,
                   json={"bank_account_number": "99998888777766", "father_name": "Ram Lal"})
j = r.json()
apr2 = j.get("approval_id")
check("bank change staged (mixed patch)", r.status_code == 200 and j.get("approval_required") and apr2,
      f"{r.status_code} {r.text[:150]}")
fresh = db.users.find_one({"user_id": emp_id})
check("bank UNCHANGED / father_name applied",
      fresh.get("bank_account_number") == "11112222333344" and fresh.get("father_name") == "Ram Lal")

# 7. masking: maker (no sensitive perm) sees masked old/new in queue
r = requests.get(f"{BASE}/admin/approvals?status=PENDING", headers=MK)
row = next((a for a in r.json()["approvals"] if a["approval_id"] == apr2), {})
check("queue masks bank values for non-sensitive viewer",
      str(row.get("new_values", {}).get("bank_account_number", "")).startswith("X"),
      str(row)[:150])
r = requests.get(f"{BASE}/admin/approvals/{apr2}", headers=CK)
check("checker (sensitive perm) sees raw values",
      r.json()["approval"]["new_values"]["bank_account_number"] == "99998888777766")

# 8. reject bank change → data unchanged
r = requests.post(f"{BASE}/admin/approvals/{apr2}/decide", headers=CK,
                  json={"decision": "reject", "reason": "wrong acct"})
check("bank change rejected", r.status_code == 200 and r.json()["status"] == "REJECTED")
check("bank still UNCHANGED after reject",
      db.users.find_one({"user_id": emp_id})["bank_account_number"] == "11112222333344")

# 9. employee delete: maker requests, sub-admin checker cannot approve, super can
r = requests.delete(f"{BASE}/admin/employees/{emp_id}", headers=MK)
apr3 = r.json().get("approval_id")
check("delete staged by sub-admin", r.status_code == 200 and r.json().get("approval_required") and apr3,
      f"{r.status_code} {r.text[:120]}")
check("employee still exists", db.users.find_one({"user_id": emp_id}) is not None)
r = requests.post(f"{BASE}/admin/approvals/{apr3}/decide", headers=CK,
                  json={"decision": "approve"})
check("sub-admin cannot approve delete → 403", r.status_code == 403, f"{r.status_code}")
r = requests.post(f"{BASE}/admin/approvals/{apr3}/decide", headers=SA,
                  json={"decision": "approve"})
check("super admin approves delete", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
check("employee DELETED after approval", db.users.find_one({"user_id": emp_id}) is None)

# 10. toggle OFF employee_delete → strict 403 for sub admin
requests.put(f"{BASE}/admin/maker-checker/settings", headers=SA,
             json={"actions": {"employee_delete": False}})
r = requests.delete(f"{BASE}/admin/employees/{maker_id}", headers=MK)
check("delete blocked when toggle OFF", r.status_code == 403, f"{r.status_code}")
requests.put(f"{BASE}/admin/maker-checker/settings", headers=SA,
             json={"actions": {"employee_delete": True}})

# 11. audit trail exists
check("audit APPROVAL_REQUESTED logged",
      db.activity_log.count_documents({"action": "APPROVAL_REQUESTED",
                                       "user_id": maker_id}) >= 3)
check("audit APPROVAL_APPROVED logged",
      db.activity_log.count_documents({"action": "APPROVAL_APPROVED"}) >= 1)

# cleanup
for u in (maker_id, checker_id):
    db.users.delete_one({"user_id": u})
    db.user_sessions.delete_many({"user_id": u})
    db.activity_log.delete_many({"user_id": u})
db.users.delete_one({"user_id": emp_id})
db.pending_approvals.delete_many({"target_user_id": emp_id})
db.salary_history.delete_many({"user_id": emp_id})
db.kyc_history.delete_many({"user_id": emp_id})

print(f"\n=== {ok} passed, {fail} failed ===")
sys.exit(1 if fail else 0)
