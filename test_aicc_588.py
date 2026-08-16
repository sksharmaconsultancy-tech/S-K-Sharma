"""Iter 588 tests — AI Command Center backend (alerts / insights / activity + scoping)."""
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


# restricted sub-admin scoped to OTHER firm (not Kankani)
sub_id = f"user_t588_{uuid.uuid4().hex[:6]}"
db.users.insert_one({"user_id": sub_id, "role": "sub_admin", "name": "T588 Sub",
                     "email": f"{sub_id}@t.co", "active": True,
                     "sub_admin_company_scope": "restricted",
                     "sub_admin_company_ids": ["cmp_other_firm"],
                     "sub_admin_permissions": ["employees:view"],
                     "created_at": dtm.datetime.utcnow().isoformat()})
tok = f"t588_{uuid.uuid4().hex[:8]}"
db.user_sessions.insert_one({"session_token": tok, "user_id": sub_id,
                             "created_at": dtm.datetime.utcnow().isoformat(),
                             "expires_at": "2027-01-01T00:00:00+00:00"})
SUB = {"Authorization": f"Bearer {tok}"}

# 1. alerts — super admin sees Kankani data
r = requests.get(f"{BASE}/admin/ai-cc/alerts?company_id={CID}", headers=SA)
j = r.json()
check("alerts 200 + has counts", r.status_code == 200 and "counts" in j, f"{r.status_code}")
check("missing bank alert fires (Kankani)",
      any(a["id"] == "missing_bank" and a["count"] > 100 for a in j["alerts"]))
check("severity ordering (CRITICAL first)",
      not j["alerts"] or j["alerts"][0]["severity"] == "CRITICAL")

# 2. alerts — cross-firm blocked for restricted sub-admin
r = requests.get(f"{BASE}/admin/ai-cc/alerts?company_id={CID}", headers=SUB)
check("cross-firm alerts → 403", r.status_code == 403, f"{r.status_code}")
r = requests.get(f"{BASE}/admin/ai-cc/alerts", headers=SUB)
check("scoped alerts (own firms only, no Kankani leak)",
      r.status_code == 200 and not any(a["count"] > 100 for a in r.json()["alerts"]),
      r.text[:120])

# 3. insights — super admin
r = requests.get(f"{BASE}/admin/ai-cc/insights?company_id={CID}&period=this_month", headers=SA)
j = r.json()
check("insights 200 + employee KPIs", r.status_code == 200
      and j["employees"]["total"] > 100 and "payroll" in j and "attendance" in j)
r = requests.get(f"{BASE}/admin/ai-cc/insights?company_id={CID}", headers=SUB)
check("cross-firm insights → 403", r.status_code == 403, f"{r.status_code}")

# 4. AI command creates AI_COMMAND audit row + activity endpoint returns it
before = db.activity_log.count_documents({"action": "AI_COMMAND"})
r = requests.post(f"{BASE}/admin/ai-assistant/command", headers=SA,
                  json={"text": "employee count", "company_id": CID}, timeout=90)
check("ai command still works", r.status_code == 200 and r.json().get("reply"), f"{r.status_code}")
check("AI_COMMAND audit row created",
      db.activity_log.count_documents({"action": "AI_COMMAND"}) == before + 1)
r = requests.get(f"{BASE}/admin/ai-cc/activity", headers=SA)
check("activity endpoint lists AI_COMMAND",
      r.status_code == 200 and any(x["action"] == "AI_COMMAND" for x in r.json()["audit"]))

# 5. maker-checker approvals now carry risk levels
emp_id = f"user_t588emp_{uuid.uuid4().hex[:6]}"
db.users.insert_one({"user_id": emp_id, "role": "employee", "name": "T588 Emp",
                     "employee_code": "T588", "company_id": CID, "active": True,
                     "salary_monthly": 9000,
                     "created_at": dtm.datetime.utcnow().isoformat()})
sub2_id = f"user_t588b_{uuid.uuid4().hex[:6]}"
db.users.insert_one({"user_id": sub2_id, "role": "sub_admin", "name": "T588 Maker",
                     "email": f"{sub2_id}@t.co", "active": True,
                     "sub_admin_company_scope": "restricted",
                     "sub_admin_company_ids": [CID],
                     "sub_admin_permissions": ["employees:view", "salary_process:edit",
                                               "salary_process:view"],
                     "created_at": dtm.datetime.utcnow().isoformat()})
tok2 = f"t588b_{uuid.uuid4().hex[:8]}"
db.user_sessions.insert_one({"session_token": tok2, "user_id": sub2_id,
                             "created_at": dtm.datetime.utcnow().isoformat(),
                             "expires_at": "2027-01-01T00:00:00+00:00"})
SUB2 = {"Authorization": f"Bearer {tok2}"}
r = requests.patch(f"{BASE}/admin/employees/{emp_id}/salary", headers=SUB2,
                   json={"salary_monthly": 12000})
apr = r.json().get("approval_id")
check("salary staged via maker-checker (regression)", bool(apr), r.text[:120])
r = requests.get(f"{BASE}/admin/approvals?status=PENDING", headers=SA)
row = next((a for a in r.json()["approvals"] if a["approval_id"] == apr), {})
check("approval carries risk=HIGH", row.get("risk") == "HIGH", str(row.get("risk")))
requests.post(f"{BASE}/admin/approvals/{apr}/decide", headers=SA,
              json={"decision": "reject", "reason": "test"})

# cleanup
for u in (sub_id, sub2_id, emp_id):
    db.users.delete_one({"user_id": u})
    db.user_sessions.delete_many({"user_id": u})
    db.activity_log.delete_many({"user_id": u})
db.pending_approvals.delete_many({"target_user_id": emp_id})
db.salary_history.delete_many({"user_id": emp_id})

print(f"\n=== {ok} passed, {fail} failed ===")
sys.exit(1 if fail else 0)
