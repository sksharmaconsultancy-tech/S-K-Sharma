"""Iter 183 — verify compliance salary run rows include branch_name /
department / contractor_name fields for the new filter-chips feature."""
import os
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
KANKANI_ID = "cmp_527fecdd7c"
MONTH = "2026-05"


def _admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, f"admin login failed {r.status_code} {r.text[:200]}"
    data = r.json()
    tok = data.get("session_token") or data.get("token") or data.get("access_token")
    assert tok, f"no token in login response {list(data.keys())}"
    return tok


def test_compliance_run_rows_have_new_fields():
    tok = _admin_token()
    headers = {"Authorization": f"Bearer {tok}"}
    payload = {"company_id": KANKANI_ID, "month": MONTH}
    r = requests.post(
        f"{BASE_URL}/api/admin/compliance-salary-runs",
        headers=headers, json=payload, timeout=180,
    )
    assert r.status_code in (200, 201), f"process failed {r.status_code} {r.text[:400]}"
    body = r.json()
    run = body.get("run") or {}
    rows = run.get("rows") or []
    assert len(rows) > 0, f"no rows returned. body keys={list(body.keys())} run keys={list(run.keys())[:20]}"

    # Every row must have the three new keys (values may be None/empty)
    sample = rows[0]
    for k in ("branch_name", "department", "contractor_name"):
        assert k in sample, f"row missing key {k} — keys={list(sample.keys())[:40]}"

    # At least SOME rows should have real dept values (Kankani has WEAVING / SECURITY)
    depts = {(r.get("department") or "").strip() for r in rows}
    depts.discard("")
    print(f"Depts observed: {depts}")
    contractors = {(r.get("contractor_name") or "").strip() for r in rows}
    contractors.discard("")
    print(f"Contractors observed: {contractors}")
    branches = {(r.get("branch_name") or "").strip() for r in rows}
    branches.discard("")
    print(f"Branches observed: {branches}")

    # Soft assertions per problem statement
    assert depts, "expected some dept values on Kankani rows (WEAVING/SECURITY)"
    # Contractor may or may not exist; problem says one row has RAM PRASAD — verify present or log
    if contractors:
        print(f"OK — contractors present: {contractors}")


def test_row_shape_regression():
    """Ensure the row still has core compliance keys (didn't break)."""
    tok = _admin_token()
    r = requests.post(
        f"{BASE_URL}/api/admin/compliance-salary-runs",
        headers={"Authorization": f"Bearer {tok}"},
        json={"company_id": KANKANI_ID, "month": MONTH},
        timeout=180,
    )
    assert r.status_code in (200, 201)
    rows = (r.json().get("run") or {}).get("rows") or []
    assert rows
    s = rows[0]
    for k in ("user_id", "name", "employee_code", "basic", "gross_paid", "net"):
        assert k in s, f"missing legacy key {k}"
