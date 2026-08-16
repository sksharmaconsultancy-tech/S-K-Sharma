"""Iter 589b tests — AI bulk-change UNDO."""
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


DEPT = f"T589U_{uuid.uuid4().hex[:4]}"
emp_ids = []
for i, sal in enumerate((10000, 20000, 30000)):
    uid = f"user_t589u{i}_{uuid.uuid4().hex[:6]}"
    emp_ids.append(uid)
    db.users.insert_one({"user_id": uid, "role": "employee", "name": f"T589U Emp{i}",
                         "employee_code": f"U{i}", "company_id": CID, "active": True,
                         "department": DEPT, "salary_monthly": sal,
                         "created_at": dtm.datetime.utcnow().isoformat()})

# bulk +10% executed by super admin
r = requests.post(f"{BASE}/admin/ai-bulk/salary/preview", headers=SA,
                  json={"company_id": CID, "department": DEPT, "pct": 10})
bulk_id = r.json()["preview"]["preview_id"]
requests.post(f"{BASE}/admin/ai-bulk/salary/execute", headers=SA,
              json={"preview_id": bulk_id})
check("setup: bulk applied",
      db.users.find_one({"user_id": emp_ids[0]})["salary_monthly"] == 11000)

# one employee changed AGAIN after the bulk → must be skipped by undo
db.users.update_one({"user_id": emp_ids[2]}, {"$set": {"salary_monthly": 40000}})

# 1. undo preview (explicit bulk id)
r = requests.post(f"{BASE}/admin/ai-bulk/salary/undo-preview", headers=SA,
                  json={"bulk_id": bulk_id})
pv = r.json().get("preview") or {}
check("undo preview: 2 restorable, 1 skipped",
      r.status_code == 200 and pv.get("employees_affected") == 2 and pv.get("skipped") == 1,
      f"{r.status_code} {r.text[:200]}")
check("undo preview math (restore to originals)",
      pv.get("new_payroll") == 30000 and pv.get("current_payroll") == 33000)
check("nothing modified by preview",
      db.users.find_one({"user_id": emp_ids[0]})["salary_monthly"] == 11000)

# 2. execute undo (super)
r = requests.post(f"{BASE}/admin/ai-bulk/salary/execute", headers=SA,
                  json={"preview_id": pv["preview_id"]})
check("undo executed (2 changed)", r.status_code == 200
      and r.json().get("employees_changed") == 2, f"{r.status_code} {r.text[:150]}")
check("salaries restored / manual change preserved",
      db.users.find_one({"user_id": emp_ids[0]})["salary_monthly"] == 10000
      and db.users.find_one({"user_id": emp_ids[1]})["salary_monthly"] == 20000
      and db.users.find_one({"user_id": emp_ids[2]})["salary_monthly"] == 40000)
src = db.ai_bulk_previews.find_one({"preview_id": bulk_id})
check("source bulk marked UNDONE", src["status"] == "UNDONE"
      and src.get("undone_by") == pv["preview_id"])
check("undo wrote salary_history rows",
      db.salary_history.count_documents({"bulk_id": pv["preview_id"]}) == 2)

# 3. cannot undo twice
r = requests.post(f"{BASE}/admin/ai-bulk/salary/undo-preview", headers=SA,
                  json={"bulk_id": bulk_id})
check("double undo blocked (404/409)", r.status_code in (404, 409), f"{r.status_code}")

# 4. AI intent end-to-end
r = requests.post(f"{BASE}/admin/ai-bulk/salary/preview", headers=SA,
                  json={"company_id": CID, "department": DEPT, "pct": 20})
requests.post(f"{BASE}/admin/ai-bulk/salary/execute", headers=SA,
              json={"preview_id": r.json()["preview"]["preview_id"]})
r = requests.post(f"{BASE}/admin/ai-assistant/command", headers=SA,
                  json={"text": "undo the last bulk salary change", "company_id": CID},
                  timeout=120)
j = r.json()
act = j.get("action") or {}
check("AI undo intent → preview + confirm action",
      r.status_code == 200 and "Undo Bulk Change Preview" in (j.get("reply") or "")
      and act.get("type") == "confirm_api", f"{r.status_code} {str(j)[:250]}")
check("AI did NOT restore without confirm",
      db.users.find_one({"user_id": emp_ids[0]})["salary_monthly"] == 12000)

# cleanup
for u in emp_ids:
    db.users.delete_one({"user_id": u})
    db.salary_history.delete_many({"user_id": u})
db.ai_bulk_previews.delete_many({"department": DEPT})
db.ai_bulk_previews.delete_many({"source_bulk_id": {"$exists": True}, "company_id": CID,
                                 "created_at": {"$gte": dtm.datetime.utcnow().strftime("%Y-%m-%dT00")}})
db.activity_log.delete_many({"detail.department": DEPT})

print(f"\n=== {ok} passed, {fail} failed ===")
sys.exit(1 if fail else 0)
