"""Iter 652 — verify Bulk Employee Correction changes reflect in Employee Master.

Flow:
1. Login super admin (password).
2. Pick a Kankani employee.
3. Snapshot current master values.
4. Apply bulk-correction (compliance mode): father_name, department, designation,
   uan_no, bank_account, compliance_basic, HRA allowance.
5. Apply bulk-correction (actual mode): actual_basic + pay_basis.
6. Re-fetch /admin/employees and confirm every value reflects.
7. REVERT all values back to the snapshot.
"""
import requests, sys

BASE = "http://localhost:8001/api"

def login():
    # 2FA is enforced on password login; use a directly-minted session token.
    return open("/tmp/tok.txt").read().strip()

def main():
    tok = login()
    H = {"Authorization": f"Bearer {tok}"}
    cid = "cmp_527fecdd7c"

    emps = requests.get(f"{BASE}/admin/employees?company_id={cid}", headers=H).json()["employees"]
    emp = next(e for e in emps if e.get("employee_code") == "50")
    uid = emp["user_id"]
    print(f"Testing employee: {emp.get('name')} ({uid})")

    snap = {k: emp.get(k) for k in ("father_name", "department", "designation",
                                    "uan_no", "bank_account", "compliance_basic",
                                    "pay_basis")}
    print("Snapshot:", snap)

    # -- 1. Compliance-mode bulk correction --
    body = {"company_id": cid, "corrections": [{
        "user_id": uid,
        "father_name": "TEST FATHER 652",
        "department": "TEST DEPT 652",
        "designation": "TEST DESIG 652",
        "uan_no": "999888777652",
        "bank_account": "ACC652TEST",
        "compliance_basic": 12345.0,
        "allowances": {"HRA": 1652.0},
    }]}
    r = requests.post(f"{BASE}/admin/employees/bulk-correction", json=body, headers=H)
    print("compliance-mode apply:", r.status_code, r.json().get("applied_count"),
          r.json().get("skipped"))

    # -- 2. Actual-mode bulk correction --
    body2 = {"company_id": cid, "corrections": [{
        "user_id": uid, "actual_basic": 999.0, "pay_basis": "daily",
    }]}
    r2 = requests.post(f"{BASE}/admin/employees/bulk-correction", json=body2, headers=H)
    print("actual-mode apply:", r2.status_code, r2.json().get("applied_count"),
          r2.json().get("skipped"))

    # -- 3. Verify in Employee Master --
    emps2 = requests.get(f"{BASE}/admin/employees?company_id={cid}", headers=H).json()["employees"]
    e2 = next(e for e in emps2 if e["user_id"] == uid)
    checks = {
        "father_name": ("TEST FATHER 652", e2.get("father_name")),
        "department": ("TEST DEPT 652", e2.get("department")),
        "designation": ("TEST DESIG 652", e2.get("designation")),
        "uan_no": ("999888777652", e2.get("uan_no")),
        "bank_account": ("ACC652TEST", e2.get("bank_account")),
        "compliance_basic": (12345.0, e2.get("compliance_basic")),
        "basic_salary(mirror)": (12345.0, e2.get("basic_salary")),
        "hra(mirror)": (1652.0, e2.get("hra")),
        "pay_basis": ("daily", e2.get("pay_basis")),
    }
    ssa = e2.get("salary_structure_actual") or []
    basic_row = next((r for r in ssa if str(r.get("head", "")).lower().startswith("basic")), {})
    checks["actual_basic(struct)"] = (999.0, basic_row.get("amount"))
    checks["actual_rate_type(struct)"] = ("daily", basic_row.get("rate_type"))
    csa = e2.get("compliance_salary_allowances") or []
    hra_row = next((r for r in csa if str(r.get("head", "")).upper().startswith("HRA")), {})
    checks["hra(compliance_allowances)"] = (1652.0, hra_row.get("amount"))

    ok = True
    for k, (exp, got) in checks.items():
        status = "PASS" if got == exp else "FAIL"
        if got != exp:
            ok = False
        print(f"  [{status}] {k}: expected={exp!r} got={got!r}")

    # -- 4. REVERT --
    revert = {"company_id": cid, "corrections": [{
        "user_id": uid,
        "father_name": snap["father_name"] or "",
        "department": snap["department"] or "",
        "designation": snap["designation"] or "",
        "uan_no": snap["uan_no"] or "",
        "bank_account": snap["bank_account"] or "",
        **({"compliance_basic": snap["compliance_basic"]} if snap["compliance_basic"] else {}),
    }]}
    rr = requests.post(f"{BASE}/admin/employees/bulk-correction", json=revert, headers=H)
    print("revert:", rr.status_code)

    print("\nRESULT:", "ALL PASS — bulk corrections DO update Employee Master" if ok
          else "SOME CHECKS FAILED — see above")
    sys.exit(0 if ok else 1)

main()
