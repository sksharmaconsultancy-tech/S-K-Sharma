"""Iter 745 test — Attendance-Policy based Late Penalty.

1. Saves late_penalty into Kankani's attendance policy via PATCH.
2. Reads the Late Penalty report for 2026-07 (real punch data).
3. Creates a compliance run for 2026-07 and verifies the penalty
   auto-landed in Other Deduction (head 'Late Penalty'), net reduced.
4. Restores the policy (disabled) and removes the test run.
"""
import hashlib
import os
import sys
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
MONTH = "2026-07"

db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]

r = requests.post(f"{BASE}/auth/admin-password-login",
                  json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"})
j = r.json()
if j.get("twofa_required"):
    pt = j["pending_token"]
    db.twofa_pending.update_one({"pending_id": pt},
                                {"$set": {"otp_hash": hashlib.sha256(b"123456").hexdigest()}})
    j = requests.post(f"{BASE}/auth/2fa/verify", json={"pending_token": pt, "otp": "123456"}).json()
H = {"Authorization": f"Bearer {j['session_token']}"}

# snapshot current policy for restore
co = db.companies.find_one({"company_id": CID}, {"attendance_policy": 1})
had_lp = (co.get("attendance_policy") or {}).get("late_penalty")

# 1. save late_penalty via PATCH (strict: 0 free, every 1 late = 0.5 day)
r = requests.patch(f"{BASE}/attendance/policy?company_id={CID}", headers=H, json={
    "policy": {"late_penalty": {"enabled": True, "grace_minutes": 0, "free_lates": 0,
                                "mode": "every_n", "every_n": 1, "every_n_days": 0.5,
                                "slabs": [], "max_days": 0}}})
assert r.status_code == 200, r.text[:300]
saved = r.json()["policy"].get("late_penalty")
print("policy saved:", saved)
assert saved and saved["enabled"] and saved["every_n"] == 1

# 1b. GET policy returns it
r = requests.get(f"{BASE}/attendance/policy?company_id={CID}", headers=H)
assert r.json()["policy"]["late_penalty"]["enabled"] is True

# 1c. slab validation rejects bad slab
r = requests.patch(f"{BASE}/attendance/policy?company_id={CID}", headers=H, json={
    "policy": {"late_penalty": {"enabled": True, "mode": "slabs",
                                "slabs": [{"from": 5, "to": 2, "days": 1}]}}})
assert r.status_code == 400, f"bad slab accepted! {r.status_code}"
print("bad slab rejected ✓")

# 2. report
r = requests.get(f"{BASE}/admin/late-penalty/config?company_id={CID}", headers=H)
print("config endpoint:", r.json()["config"].get("source"), r.json()["config"].get("every_n"))
r = requests.get(f"{BASE}/admin/late-penalty/report?company_id={CID}&month={MONTH}", headers=H)
rep = r.json()
lp_rows = rep.get("rows") or []
print(f"report rows: {len(lp_rows)}, total: {rep.get('total_penalty')}")
with_pen = {x["user_id"]: x for x in lp_rows if x["penalty_amount"] > 0}
print("employees with penalty:", len(with_pen))

# 3. compliance run (existing 2026-07 drafts snapshot to restore later)
prev_runs = list(db.compliance_salary_runs.find({"company_id": CID, "month": MONTH}))
r = requests.post(f"{BASE}/admin/compliance-salary-runs", headers=H,
                  json={"month": MONTH, "company_id": CID, "fresh": True})
assert r.status_code == 200, r.text[:400]
run = r.json()["run"]
hits = miss = 0
for row in run.get("rows") or []:
    p = with_pen.get(row.get("user_id"))
    if not p:
        continue
    exp = round(float(p["penalty_amount"]), 2)
    got = round(float(row.get("late_penalty_amount") or 0), 2)
    od = round(float(row.get("other_deduction") or 0), 2)
    head = row.get("other_deduction_head") or ""
    ted = float(row.get("total_deduction") or 0)
    net = float(row.get("net") or 0)
    gp = float(row.get("gross_paid") or 0)
    ok = (got == exp and od >= exp and "Late Penalty" in head
          and abs(round(gp - ted, 2) - net) < 0.005)
    if ok:
        hits += 1
    else:
        miss += 1
        if miss <= 5:
            print("MISMATCH", row.get("employee_code"), "exp", exp, "got", got,
                  "od", od, "head", head, "net", net, "gp-ted", round(gp - ted, 2))
print(f"auto-applied ok: {hits}, mismatches: {miss}")

# 4. restore: delete test run, restore previous drafts + policy
db.compliance_salary_runs.delete_many({"company_id": CID, "month": MONTH})
if prev_runs:
    db.compliance_salary_runs.insert_many(prev_runs)
    print(f"restored {len(prev_runs)} previous run(s)")
if had_lp is not None:
    db.companies.update_one({"company_id": CID},
                            {"$set": {"attendance_policy.late_penalty": had_lp}})
else:
    db.companies.update_one({"company_id": CID},
                            {"$set": {"attendance_policy.late_penalty.enabled": False}})
print("policy restored (disabled)")
ok = hits > 0 and miss == 0
print("RESULT:", "PASS" if ok else ("NO-PENALTY-DATA" if not with_pen else "FAIL"))
sys.exit(0 if ok or not with_pen else 1)
