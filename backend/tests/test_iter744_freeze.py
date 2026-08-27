"""Iter 744 test — Excel freeze import must EXACT-match imported gross.

Inserts synthetic compliance_import_entries for 2026-04 (unused month),
creates a run with use_imported_sheet=True and verifies for every row:
  basic+hra+conv+medical+special+others+ot_pay == gross_paid == imported_gross
  net == gross_paid - total_deduction
Cleans up the test run + entries afterwards.
"""
import os
import sys
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
BASE = "http://localhost:8001/api"
MONTH = "2026-04"
CID = "cmp_527fecdd7c"

db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]

# --- login (2FA: overwrite pending otp_hash with a known code) ---
import hashlib
r = requests.post(f"{BASE}/auth/admin-password-login",
                  json={"email": "sksharmaconsultancy@gmail.com",
                        "password": "sharma123"})
assert r.status_code == 200, r.text
j = r.json()
if j.get("twofa_required"):
    pt = j["pending_token"]
    db.twofa_pending.update_one(
        {"pending_id": pt},
        {"$set": {"otp_hash": hashlib.sha256(b"123456").hexdigest()}})
    r = requests.post(f"{BASE}/auth/2fa/verify",
                      json={"pending_token": pt, "otp": "123456"})
    assert r.status_code == 200, r.text[:300]
    j = r.json()
tok = j.get("session_token") or j.get("access_token") or j.get("token")
H = {"Authorization": f"Bearer {tok}"}

# --- build synthetic import entries with awkward gross values ---
emps = list(db.users.find(
    {"company_id": CID, "role": "employee", "status": {"$ne": "inactive"}},
    {"_id": 0, "user_id": 1, "employee_code": 1,
     "salary_structure_compliance": 1}).limit(40))

grosses = [9334, 12001.49, 15000.5, 8887, 21001, 7333.33, 19371, 10000,
           13579.99, 6666.5, 18001, 9999.49, 11111, 14444.51, 20999]
db.compliance_import_entries.delete_many({"month": MONTH, "company_id": CID})
docs = []
for i, e in enumerate(emps):
    docs.append({
        "company_id": CID, "month": MONTH, "user_id": e["user_id"],
        "present_days": 26.0, "deduction_head": "", "deduction_amount": 0.0,
        "gross_earning": grosses[i % len(grosses)],
        "tds": 0.0, "other_less": 0.0, "ot_hours": 0.0,
        "source": "file", "filename": "iter744_test.xls",
    })
assert docs, "no employees with rates found"
db.compliance_import_entries.insert_many(docs)
imp_map = {d["user_id"]: d["gross_earning"] for d in docs}
print(f"inserted {len(docs)} import entries")

# --- delete any old test run then create ---
db.compliance_salary_runs.delete_many({"month": MONTH, "company_id": CID})
r = requests.post(f"{BASE}/admin/compliance-salary-runs", headers=H, json={
    "month": MONTH, "company_id": CID, "use_imported_sheet": True,
    "fresh": True})
assert r.status_code == 200, r.text[:500]
run = r.json().get("run") or {}
run_id = run.get("run_id") or run.get("id")
rows = run.get("rows") or []
assert rows, f"no rows in run! keys={list(run.keys())}"
print(f"run created: {run_id}, rows: {len(rows)}")

EARN = ("basic", "hra", "conveyance", "medical", "special", "others", "ot_pay")
fails = []
checked = 0
for row in rows:
    uid = row.get("user_id")
    if uid not in imp_map:
        continue
    checked += 1
    imp = imp_map[uid]
    gp = float(row.get("gross_paid") or 0)
    comp_sum = round(sum(float(row.get(k) or 0) for k in EARN), 2)
    net = float(row.get("net") or 0)
    ted = float(row.get("total_deduction") or 0)
    mg = float(row.get("monthly_gross") or 0)
    ot = float(row.get("ot_pay") or 0)
    errs = []
    if abs(gp - imp) > 0.004:
        errs.append(f"gross_paid {gp} != imported {imp}")
    if abs(comp_sum - imp) > 0.004:
        errs.append(f"earn-sum {comp_sum} != imported {imp}")
    if abs(round(mg + ot, 2) - imp) > 0.004:
        errs.append(f"mg+ot {round(mg+ot,2)} != imported {imp}")
    if abs(round(gp - ted, 2) - net) > 0.004:
        errs.append(f"net {net} != gross-ded {round(gp-ted,2)}")
    if errs:
        fails.append((row.get("employee_code"), imp, errs,
                      row.get("difference_allocation_head")))

print(f"checked {checked} rows")
if fails:
    print(f"FAIL — {len(fails)} rows mismatch:")
    for f in fails[:15]:
        print(" ", f)
else:
    print("PASS — every row exactly matches imported gross & net tallies")

# --- cleanup ---
db.compliance_import_entries.delete_many({"month": MONTH, "company_id": CID})
db.compliance_salary_runs.delete_many({"month": MONTH, "company_id": CID})
print("cleaned up")
sys.exit(1 if fails else 0)
