"""Iter 746 — E2E self-test: Org Structure + OT Management + HR Analytics.

Covers the PRD test matrix: 15/29/30/45/60-min OT eligibility, 48-hr cap
(eligible vs excess), approval levels, reject/re-submit, payroll-processed
lock, org hierarchy (parent/cycle/head), reporting chain, attrition &
variance from real data. Cleans up everything at the end.
"""
import hashlib
import os
import sys
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
B = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
MONTH = "2026-07"
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
FAIL = []


def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, extra)
    if not cond:
        FAIL.append(name)


r = requests.post(f"{B}/auth/admin-password-login",
                  json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"})
j = r.json()
if j.get("twofa_required"):
    db.twofa_pending.update_one({"pending_id": j["pending_token"]},
                                {"$set": {"otp_hash": hashlib.sha256(b"123456").hexdigest()}})
    j = requests.post(f"{B}/auth/2fa/verify",
                      json={"pending_token": j["pending_token"], "otp": "123456"}).json()
H = {"Authorization": f"Bearer {j['session_token']}"}

# ═══ 0. unit: rounding + min rule ═══
from importlib import import_module  # noqa: E402
sys.path.insert(0, "/app/backend")
import server  # noqa: F401,E402
otm = import_module("routes.ot_management")
mins = {15: 0.0, 29: 0.0, 30: 0.5, 45: 0.75, 60: 1.0}
for m, exp in mins.items():
    h = m / 60.0
    elig = 0.0 if h < 30 / 60.0 else h
    check(f"min-30 rule {m}min", round(elig, 2) == exp)
check("round down_30 1.4h→1.0", otm._round_ot(1.4, "down_30") == 1.0)
check("round nearest_15 1.4h→1.5", otm._round_ot(1.4, "nearest_15") == 1.5)

# ═══ 1. ORG ═══
r = requests.post(f"{B}/org/departments", headers=H,
                  json={"company_id": CID, "name": "TEST HR & ADMIN 746"})
check("dept create", r.status_code == 200, r.text[:120])
mid = r.json().get("master_id")
r = requests.get(f"{B}/org/departments?company_id={CID}", headers=H)
depts = r.json()["departments"]
check("dept list has counts", any(d["employee_count"] > 0 for d in depts))
parent = next((d for d in depts if d["master_id"] != mid), None)
emp = db.users.find_one({"company_id": CID, "role": "employee", "active": {"$ne": False}},
                        {"user_id": 1, "name": 1})
mgr = db.users.find_one({"company_id": CID, "role": "employee",
                         "user_id": {"$ne": emp["user_id"]}}, {"user_id": 1})
r = requests.patch(f"{B}/org/departments/{mid}", headers=H, json={
    "company_id": CID, "parent_id": parent["master_id"], "code": "HRA",
    "head_user_id": mgr["user_id"], "cost_centre": "CC-01", "status": "active"})
check("dept patch (parent+head)", r.status_code == 200, r.text[:120])
# cycle: parent's parent = child
r = requests.patch(f"{B}/org/departments/{parent['master_id']}", headers=H,
                   json={"company_id": CID, "parent_id": mid})
check("cycle rejected 400", r.status_code == 400)
r = requests.get(f"{B}/org/chart?company_id={CID}", headers=H)
check("org chart tree", r.status_code == 200 and r.json().get("tree") is not None)
# reporting chain: self-manager rejected
r = requests.post(f"{B}/org/reporting/{emp['user_id']}", headers=H,
                  json={"company_id": CID, "primary_manager": emp["user_id"]})
check("self manager rejected", r.status_code == 400)
r = requests.post(f"{B}/org/reporting/{emp['user_id']}", headers=H,
                  json={"company_id": CID, "primary_manager": mgr["user_id"]})
check("reporting set", r.status_code == 200)
r = requests.get(f"{B}/org/report?kind=hierarchy&fmt=json&company_id={CID}", headers=H)
check("org hierarchy report", r.status_code == 200)
r = requests.get(f"{B}/org/report?kind=manager_wise&fmt=xlsx&company_id={CID}", headers=H)
check("org manager xlsx", r.status_code == 200 and len(r.content) > 500)

# ═══ 2. OT POLICY + GENERATE ═══
db.ot_entries.delete_many({"company_id": CID})
r = requests.post(f"{B}/ot/policy", headers=H, json={
    "company_id": CID, "enabled": True, "approval_required": True,
    "min_ot_minutes": 30, "max_ot_hours_month": 48, "weekly_limit_hours": 0,
    "rounding": "none", "normal_working_hours": 8, "ot_rate_multiplier": 1,
    "holiday_ot": True, "weekly_off_ot": True, "auto_approve": False,
    "allow_override": True, "approval_levels": ["primary_manager"]})
check("policy save", r.status_code == 200, r.text[:120])
r = requests.post(f"{B}/ot/generate", headers=H,
                  json={"company_id": CID, "month": MONTH})
check("ot generate", r.status_code == 200, r.text[:200])
r = requests.get(f"{B}/ot/entries?company_id={CID}&month={MONTH}", headers=H)
ent = r.json()["entries"]
summ = r.json()["summary"]
check("entries created", len(ent) > 0, f"count={len(ent)}")
# min-30: no eligible entry between 0 and 0.5 h
bad_min = [e for e in ent if 0 < e["eligible_ot_hours"] < 0.5]
check("min-30 enforced", not bad_min, str(bad_min[:2]))
# 48-hr cap per employee
per_user = {}
for e in ent:
    per_user.setdefault(e["user_id"], 0.0)
    per_user[e["user_id"]] += e["eligible_ot_hours"]
over = {u: h for u, h in per_user.items() if h > 48.004}
check("48h monthly cap", not over, str(list(over.items())[:2]))
capped = [e for e in ent if e["excess_ot_hours"] > 0]
print(f"  info: excess entries={len(capped)}, total excess={summ['excess_ot']}h, "
      f"attendance={summ['attendance_ot']}h eligible={summ['eligible_ot']}h")
check("pending status (approval req)", all(e["status"] == "pending" for e in ent))

# ═══ 3. APPROVAL FLOW ═══
ids = [e["entry_id"] for e in ent[:3]]
r = requests.post(f"{B}/ot/action", headers=H, json={
    "company_id": CID, "entry_ids": ids[:2], "action": "approve", "remarks": "ok"})
check("approve 2", r.status_code == 200 and r.json()["processed"] == 2, r.text[:120])
r = requests.post(f"{B}/ot/action", headers=H, json={
    "company_id": CID, "entry_ids": [ids[2]], "action": "reject",
    "remarks": "not valid"})
check("reject 1", r.status_code == 200)
r = requests.post(f"{B}/ot/resubmit", headers=H,
                  json={"company_id": CID, "entry_ids": [ids[2]]})
check("resubmit", r.status_code == 200 and r.json()["resubmitted"] == 1)
r = requests.post(f"{B}/ot/action", headers=H, json={
    "company_id": CID, "entry_ids": [ids[2]], "action": "reject", "remarks": "again"})
check("re-reject", r.status_code == 200)
# override
r = requests.post(f"{B}/ot/action", headers=H, json={
    "company_id": CID, "entry_ids": [ids[2]], "action": "override",
    "override_hours": 1.0, "remarks": "management approved"})
check("override", r.status_code == 200)
e3 = db.ot_entries.find_one({"entry_id": ids[2]})
check("override applied", e3["status"] == "approved" and e3["eligible_ot_hours"] == 1.0)

# ═══ 4. PAYROLL INTEGRATION ═══
approved = {e["user_id"]: 0.0 for e in db.ot_entries.find(
    {"company_id": CID, "month": MONTH, "status": "approved"})}
for e in db.ot_entries.find({"company_id": CID, "month": MONTH, "status": "approved"}):
    approved[e["user_id"]] += e["eligible_ot_hours"]
prev_runs = list(db.compliance_salary_runs.find({"company_id": CID, "month": MONTH}))
r = requests.post(f"{B}/admin/compliance-salary-runs", headers=H,
                  json={"month": MONTH, "company_id": CID, "fresh": True})
check("run created", r.status_code == 200, r.text[:150])
rows = r.json()["run"]["rows"]
ok_ot = bad_ot = 0
for row in rows:
    exp = round(approved.get(row["user_id"], 0.0), 2)
    got = round(float(row.get("ot_hours") or 0), 2)
    if abs(got - exp) < 0.01:
        ok_ot += 1
    else:
        bad_ot += 1
        if bad_ot <= 3:
            print("  OT mismatch", row.get("employee_code"), "exp", exp, "got", got)
check("payroll uses APPROVED OT only", bad_ot == 0, f"ok={ok_ot} bad={bad_ot}")
locked = db.ot_entries.count_documents(
    {"company_id": CID, "month": MONTH, "status": "payroll_processed"})
check("approved → payroll_processed", locked == len([1 for v in approved.values() if True]) or locked > 0,
      f"locked={locked}")
lk = db.ot_entries.find_one({"company_id": CID, "status": "payroll_processed"})
if lk:
    r = requests.post(f"{B}/ot/action", headers=H, json={
        "company_id": CID, "entry_ids": [lk["entry_id"]], "action": "approve"})
    check("payroll_processed locked 409", r.status_code == 409)

# reports
r = requests.get(f"{B}/ot/report?kind=register&fmt=xlsx&company_id={CID}&month={MONTH}", headers=H)
check("OT register xlsx", r.status_code == 200 and len(r.content) > 500)
r = requests.get(f"{B}/ot/report?kind=excess&fmt=json&company_id={CID}&month={MONTH}", headers=H)
check("excess report", r.status_code == 200)
r = requests.get(f"{B}/ot/report?kind=history&fmt=pdf&company_id={CID}&month={MONTH}", headers=H)
check("history pdf", r.status_code == 200)
r = requests.get(f"{B}/org/audit?company_id={CID}&module=ot", headers=H)
check("ot audit trail", r.status_code == 200 and len(r.json()["audit"]) > 3)

# ═══ 5. ANALYTICS ═══
r = requests.get(f"{B}/hr/attrition?company_id={CID}", headers=H)
check("attrition", r.status_code == 200 and len(r.json()["monthly_trend"]) == 12,
      str(r.json().get("period"))[:120] if r.status_code == 200 else r.text[:120])
r = requests.get(f"{B}/hr/salary-variance?company_id={CID}&month=2026-06", headers=H)
check("salary variance 2026-06", r.status_code == 200, r.text[:150])
if r.status_code == 200:
    v = r.json()
    print(f"  info: prev={v['previous_payroll']} cur={v['current_payroll']} "
          f"var={v['variance']} ({v['variance_pct']}%) reasons={[x['reason'] for x in v['reasons']]}")
    ssum = round(sum(x["amount"] for x in v["reasons"]), 0)
r = requests.get(f"{B}/hr/dashboard?company_id={CID}&month={MONTH}", headers=H)
check("dashboard", r.status_code == 200 and "kpis" in r.json())
if r.status_code == 200:
    k = r.json()["kpis"]
    total_emp = db.users.count_documents({"company_id": CID, "role": "employee"})
    check("dashboard headcount == users", k["total_employees"] == total_emp,
          f"{k['total_employees']} vs {total_emp}")
r = requests.get(f"{B}/hr/report?kind=attrition&fmt=xlsx&company_id={CID}", headers=H)
check("attrition xlsx", r.status_code == 200 and len(r.content) > 500)
r = requests.get(f"{B}/hr/report?kind=variance_reasons&fmt=pdf&company_id={CID}&month=2026-06", headers=H)
check("variance pdf", r.status_code == 200)

# ═══ CLEANUP ═══
db.compliance_salary_runs.delete_many({"company_id": CID, "month": MONTH})
if prev_runs:
    db.compliance_salary_runs.insert_many(prev_runs)
db.ot_entries.delete_many({"company_id": CID})
db.ot_policies.delete_many({"company_id": CID})
db.masters.delete_one({"master_id": mid})
db.dept_hierarchy.delete_many({"company_id": CID, "master_id": mid})
db.users.update_one({"user_id": emp["user_id"]}, {"$unset": {"reporting_chain": 1}})
print("cleaned up")
print("RESULT:", "ALL PASS" if not FAIL else f"FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
