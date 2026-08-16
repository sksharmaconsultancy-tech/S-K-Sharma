"""Iter 589 tests — AI bulk-action engine (preview → approval → execute)."""
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


DEPT = f"T589DEPT_{uuid.uuid4().hex[:4]}"
emp_ids = []
for i, sal in enumerate((10000, 20000, 30000)):
    uid = f"user_t589e{i}_{uuid.uuid4().hex[:6]}"
    emp_ids.append(uid)
    db.users.insert_one({"user_id": uid, "role": "employee", "name": f"T589 Emp{i}",
                         "employee_code": f"T589{i}", "company_id": CID, "active": True,
                         "department": DEPT, "salary_monthly": sal,
                         "created_at": dtm.datetime.utcnow().isoformat()})

sub_id = f"user_t589s_{uuid.uuid4().hex[:6]}"
db.users.insert_one({"user_id": sub_id, "role": "sub_admin", "name": "T589 Sub",
                     "email": f"{sub_id}@t.co", "active": True,
                     "sub_admin_company_scope": "restricted",
                     "sub_admin_company_ids": [CID],
                     "sub_admin_permissions": ["employees:view", "salary_process:view",
                                               "salary_process:edit"],
                     "created_at": dtm.datetime.utcnow().isoformat()})
tok = f"t589_{uuid.uuid4().hex[:8]}"
db.user_sessions.insert_one({"session_token": tok, "user_id": sub_id,
                             "created_at": dtm.datetime.utcnow().isoformat(),
                             "expires_at": "2027-01-01T00:00:00+00:00"})
SUB = {"Authorization": f"Bearer {tok}"}

# 1. preview (super admin, +10% on dept)
r = requests.post(f"{BASE}/admin/ai-bulk/salary/preview", headers=SA,
                  json={"company_id": CID, "department": DEPT, "pct": 10})
pv = r.json().get("preview") or {}
check("preview built (3 emps, correct totals)",
      r.status_code == 200 and pv.get("employees_affected") == 3
      and pv.get("current_payroll") == 60000 and pv.get("new_payroll") == 66000,
      f"{r.status_code} {r.text[:200]}")
check("nothing modified after preview",
      db.users.find_one({"user_id": emp_ids[0]})["salary_monthly"] == 10000)

# 2. super admin executes directly
r = requests.post(f"{BASE}/admin/ai-bulk/salary/execute", headers=SA,
                  json={"preview_id": pv["preview_id"]})
check("super admin execute OK", r.status_code == 200 and r.json().get("executed")
      and r.json().get("employees_changed") == 3, f"{r.status_code} {r.text[:150]}")
check("salaries applied (+10%)",
      db.users.find_one({"user_id": emp_ids[0]})["salary_monthly"] == 11000
      and db.users.find_one({"user_id": emp_ids[2]})["salary_monthly"] == 33000)
check("salary_history rows created (bulk_id)",
      db.salary_history.count_documents({"bulk_id": pv["preview_id"]}) == 3)
check("CRITICAL audit row", db.activity_log.count_documents(
      {"action": "BULK_SALARY_CHANGE", "detail.preview_id": pv["preview_id"]}) == 1)

# 3. double-execute blocked
r = requests.post(f"{BASE}/admin/ai-bulk/salary/execute", headers=SA,
                  json={"preview_id": pv["preview_id"]})
check("re-execute blocked (409)", r.status_code == 409, f"{r.status_code}")

# 4. sub-admin: preview + execute → staged for approval, data unchanged
r = requests.post(f"{BASE}/admin/ai-bulk/salary/preview", headers=SUB,
                  json={"company_id": CID, "department": DEPT, "amount": 500})
pv2 = r.json().get("preview") or {}
check("sub-admin preview OK (+₹500)", r.status_code == 200
      and pv2.get("new_payroll") == 66000 + 1500, f"{r.status_code} {r.text[:150]}")
r = requests.post(f"{BASE}/admin/ai-bulk/salary/execute", headers=SUB,
                  json={"preview_id": pv2["preview_id"]})
apr = r.json().get("approval_id")
check("sub-admin execute → staged", r.status_code == 200
      and r.json().get("approval_required") and apr, f"{r.status_code} {r.text[:150]}")
check("data UNCHANGED while staged",
      db.users.find_one({"user_id": emp_ids[0]})["salary_monthly"] == 11000)

# 5. approval carries CRITICAL risk; sub-admin cannot approve; super approves
r = requests.get(f"{BASE}/admin/approvals/{apr}", headers=SA)
row = r.json()["approval"]
check("approval risk=CRITICAL + payroll old/new",
      row["risk"] == "CRITICAL" and row["new_values"].get("payroll_total") == 67500,
      str(row.get("new_values")))
r = requests.post(f"{BASE}/admin/approvals/{apr}/decide", headers=SUB,
                  json={"decision": "approve"})
check("maker/sub-admin cannot approve bulk → 403", r.status_code == 403, f"{r.status_code}")
r = requests.post(f"{BASE}/admin/approvals/{apr}/decide", headers=SA,
                  json={"decision": "approve", "reason": "ok"})
check("super admin approves bulk", r.status_code == 200
      and r.json()["result"].get("employees_changed") == 3, f"{r.status_code} {r.text[:150]}")
check("staged +₹500 applied after approval",
      db.users.find_one({"user_id": emp_ids[0]})["salary_monthly"] == 11500)

# 6. AI intent end-to-end (LLM parse → preview + confirm action)
r = requests.post(f"{BASE}/admin/ai-assistant/command", headers=SA,
                  json={"text": f"Increase salary of all employees in {DEPT} department by 5%",
                        "company_id": CID}, timeout=120)
j = r.json()
act = j.get("action") or {}
check("AI bulk intent → preview reply + confirm action",
      r.status_code == 200 and "Bulk Salary Change Preview" in (j.get("reply") or "")
      and act.get("type") == "confirm_api"
      and act.get("endpoint") == "/admin/ai-bulk/salary/execute",
      f"{r.status_code} {str(j)[:250]}")
check("AI did NOT change data without confirm",
      db.users.find_one({"user_id": emp_ids[0]})["salary_monthly"] == 11500)

# 7. cross-firm protection: sub-admin restricted elsewhere
sub2 = f"user_t589x_{uuid.uuid4().hex[:6]}"
db.users.insert_one({"user_id": sub2, "role": "sub_admin", "name": "T589 X",
                     "email": f"{sub2}@t.co", "active": True,
                     "sub_admin_company_scope": "restricted",
                     "sub_admin_company_ids": ["cmp_other"],
                     "sub_admin_permissions": ["salary_process:edit"],
                     "created_at": dtm.datetime.utcnow().isoformat()})
tok2 = f"t589x_{uuid.uuid4().hex[:8]}"
db.user_sessions.insert_one({"session_token": tok2, "user_id": sub2,
                             "created_at": dtm.datetime.utcnow().isoformat(),
                             "expires_at": "2027-01-01T00:00:00+00:00"})
r = requests.post(f"{BASE}/admin/ai-bulk/salary/preview",
                  headers={"Authorization": f"Bearer {tok2}"},
                  json={"company_id": CID, "pct": 5})
check("cross-firm bulk preview → 403", r.status_code == 403, f"{r.status_code}")

# cleanup
for u in emp_ids + [sub_id, sub2]:
    db.users.delete_one({"user_id": u})
    db.user_sessions.delete_many({"user_id": u})
    db.salary_history.delete_many({"user_id": u})
    db.activity_log.delete_many({"user_id": u})
db.pending_approvals.delete_many({"company_id": CID, "action_type": "bulk_salary_change"})
db.ai_bulk_previews.delete_many({"department": DEPT})
db.activity_log.delete_many({"detail.department": DEPT})

print(f"\n=== {ok} passed, {fail} failed ===")
sys.exit(1 if fail else 0)
