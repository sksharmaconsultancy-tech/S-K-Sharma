"""Iter 752 check — salary REPROCESS safety after Iter 744-751 changes.

For every existing compliance run in DB: snapshot stored rows (baseline,
generated BEFORE recent changes), regenerate the run twice, and compare
per-user money fields. Restores the original run afterwards.
"""
import hashlib
import os
import sys
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
B = "http://localhost:8001/api"
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]

r = requests.post(f"{B}/auth/admin-password-login",
                  json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"})
j = r.json()
if j.get("twofa_required"):
    db.twofa_pending.update_one({"pending_id": j["pending_token"]},
                                {"$set": {"otp_hash": hashlib.sha256(b"123456").hexdigest()}})
    j = requests.post(f"{B}/auth/2fa/verify",
                      json={"pending_token": j["pending_token"], "otp": "123456"}).json()
H = {"Authorization": f"Bearer {j['session_token']}"}

# safety: koi policy enabled to nahi (jo results badle)
lp_on = db.companies.count_documents({"attendance_policy.late_penalty.enabled": True})
ot_on = db.ot_policies.count_documents({"enabled": True, "approval_required": True})
print(f"late_penalty enabled firms: {lp_on} | OT approval firms: {ot_on}")

FIELDS = ("gross_paid", "monthly_gross", "basic", "hra", "others", "ot_pay",
          "pf", "esic", "total_deduction", "net", "other_deduction",
          "master_deduction", "advance_recovery", "tds")


def cmp_rows(a_rows, b_rows, tagA, tagB):
    a_by = {r["user_id"]: r for r in a_rows}
    b_by = {r["user_id"]: r for r in b_rows}
    diffs = []
    for uid in set(a_by) | set(b_by):
        ra, rb = a_by.get(uid), b_by.get(uid)
        if not ra or not rb:
            diffs.append((uid, "row missing", tagA if not ra else tagB))
            continue
        for f in FIELDS:
            va = round(float(ra.get(f) or 0), 2)
            vb = round(float(rb.get(f) or 0), 2)
            if abs(va - vb) > 0.005:
                diffs.append((ra.get("employee_code"), f, va, vb))
    return diffs


total_bad = 0
runs = list(db.compliance_salary_runs.find({}))
print(f"existing runs: {len(runs)}")
for base in runs:
    cid, month = base["company_id"], base["month"]
    co = db.companies.find_one({"company_id": cid}, {"name": 1})
    label = f"{(co or {}).get('name', cid)} {month}"
    snap = dict(base)
    # regenerate #1
    r1 = requests.post(f"{B}/admin/compliance-salary-runs", headers=H,
                       json={"month": month, "company_id": cid, "fresh": True})
    if r1.status_code != 200:
        print(f"[{label}] regen failed: {r1.text[:120]}")
        continue
    rows1 = r1.json()["run"]["rows"]
    # regenerate #2 (reprocess determinism)
    r2 = requests.post(f"{B}/admin/compliance-salary-runs", headers=H,
                       json={"month": month, "company_id": cid, "fresh": True})
    rows2 = r2.json()["run"]["rows"]
    d_base = cmp_rows(base.get("rows") or [], rows1, "baseline", "new")
    d_rep = cmp_rows(rows1, rows2, "run1", "run2")
    tot_old = round(sum(float(x.get("net") or 0) for x in (base.get("rows") or [])), 2)
    tot_new = round(sum(float(x.get("net") or 0) for x in rows1), 2)
    print(f"[{label}] rows {len(base.get('rows') or [])}→{len(rows1)} | "
          f"net total {tot_old}→{tot_new} | baseline-diffs={len(d_base)} "
          f"reprocess-diffs={len(d_rep)}")
    for d in d_base[:5]:
        print("   baseline diff:", d)
    for d in d_rep[:5]:
        print("   reprocess diff:", d)
    total_bad += len(d_rep)  # determinism must be 0
    # restore original stored run
    db.compliance_salary_runs.delete_many({"company_id": cid, "month": month})
    doc = dict(snap)
    doc.pop("_id", None)
    db.compliance_salary_runs.insert_one(doc)
print("restored all original runs")
print("RESULT:", "REPROCESS SAFE" if total_bad == 0 else f"UNSTABLE ({total_bad} diffs)")
sys.exit(1 if total_bad else 0)
