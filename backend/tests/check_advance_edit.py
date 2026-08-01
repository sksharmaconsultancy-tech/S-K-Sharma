"""Iter 422 — Editable Advance Deduction (Compliance + Actual) backend check."""
import requests

BASE = "https://emplo-connect-1.preview.emergentagent.com/api"
CID = "cmp_527fecdd7c"
MONTH = "2026-05"

s = requests.Session()
r = s.post(f"{BASE}/auth/admin-password-login",
           json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"})
r.raise_for_status()
tok = r.json().get("session_token") or r.json().get("access_token") or r.json().get("token")
H = {"Authorization": f"Bearer {tok}"}

# ---------- COMPLIANCE ----------
r = s.post(f"{BASE}/admin/compliance-salary-runs",
           json={"month": MONTH, "company_id": CID}, headers=H)
print("create compliance run:", r.status_code)
run = r.json().get("run") or r.json()
rid = run["run_id"]
rows = run["rows"]
row0 = rows[0]
uid = row0["user_id"]
old_td = float(row0.get("total_deduction") or 0)
old_net = float(row0.get("net") or 0)
old_adv = float(row0.get("advance_recovery") or 0)
print(f"row0 {row0.get('name')}: adv={old_adv} td={old_td} net={old_net}")

# simulate the grid edit: advance 500, stamp manual_fields, adjust math
new_adv = 500.0
delta = new_adv - old_adv
row0["advance_recovery"] = new_adv
row0["total_deduction"] = round(old_td + delta, 2)
row0["net"] = round(old_net - delta, 2)
row0["manual_override"] = True
row0["manual_fields"] = sorted(set(row0.get("manual_fields") or []) | {"advance_recovery"})
r = s.post(f"{BASE}/admin/compliance-salary-runs/{rid}/save-rows",
           json={"rows": rows, "totals": run.get("totals")}, headers=H)
print("save-rows:", r.status_code, r.json().get("ok"))

# REPROCESS (fresh create for same month) — manual advance must survive
r = s.post(f"{BASE}/admin/compliance-salary-runs",
           json={"month": MONTH, "company_id": CID}, headers=H)
run2 = r.json().get("run") or r.json()
row2 = next(x for x in run2["rows"] if x["user_id"] == uid)
print(f"after reprocess: adv={row2.get('advance_recovery')} "
      f"manual_fields={row2.get('manual_fields')} td={row2.get('total_deduction')} net={row2.get('net')}")
assert float(row2.get("advance_recovery") or 0) == new_adv, "COMPLIANCE ADVANCE LOST ON REPROCESS"
assert abs(float(row2["net"]) - (float(row2["total_deduction"]) * -1
       + float(row2.get("gross_paid") or 0))) < 2, "net != gross - ded"
print("COMPLIANCE OK ✓")

# cleanup the test month draft
s.delete(f"{BASE}/admin/compliance-salary-runs/{run2['run_id']}", headers=H)

# ---------- ACTUAL ----------
r = s.post(f"{BASE}/admin/actual-salary-process",
           json={"month": MONTH, "company_id": CID, "attendance_source": "biometric"},
           headers=H)
print("create actual run:", r.status_code)
if r.status_code != 200:
    print(r.text[:300])
arun = r.json().get("run") or r.json()
arid = arun["run_id"]
arow = arun["rows"][0]
auid = arow["user_id"]
print(f"actual row0 {arow.get('name')}: adv={arow.get('adv')} net={arow.get('net_pay')}")
r = s.patch(f"{BASE}/admin/actual-salary-process/{arid}/row",
            json={"user_id": auid, "adv": 750}, headers=H)
print("patch adv:", r.status_code)
prow = r.json()["row"]
print(f"after patch: adv={prow.get('adv')} net={prow.get('net_pay')}")
assert float(prow["adv"]) == 750.0, "ACTUAL ADV PATCH FAILED"
# reprocess actual — manual adv must carry (minus ledger portion)
r = s.post(f"{BASE}/admin/actual-salary-process",
           json={"month": MONTH, "company_id": CID, "attendance_source": "biometric"},
           headers=H)
arun2 = r.json().get("run") or r.json()
arow2 = next(x for x in arun2["rows"] if x["user_id"] == auid)
print(f"after actual reprocess: adv={arow2.get('adv')} advance_recovery={arow2.get('advance_recovery')}")
assert float(arow2.get("adv") or 0) >= 750.0 - float(arow2.get("advance_recovery") or 0) - 0.01, \
    "ACTUAL ADV LOST ON REPROCESS"
print("ACTUAL OK ✓")
print("ALL CHECKS PASSED")
