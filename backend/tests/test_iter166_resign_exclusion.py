"""Iter 166 — Resigned-employee exclusion from salary processing.

Scenario:
    * Employee user_44cd6f561da0 (SURENDRA SINGH, code 50) in firm cmp_527fecdd7c
      gets exit_date='2026-06-15' injected directly in Mongo.
    * COMPLIANCE run for 2026-07 must EXCLUDE him (other employees present).
    * COMPLIANCE run for 2026-06 must INCLUDE him (exit month itself payable).
    * ACTUAL Salary Process for 2026-07 must ALSO exclude him. Kankani has
      salary_process.offline_salary=False; we flip it to True temporarily to
      exercise the endpoint and restore afterwards.
    * All mutations (exit_date, firm flag) and any runs we create are cleaned
      up in the module-level teardown so no residue is left in the DB.
"""

from __future__ import annotations

import os
import time

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL missing"

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TARGET_USER_ID = "user_44cd6f561da0"
TARGET_EMP_CODE = "50"
COMPANY_ID = "cmp_527fecdd7c"
EXIT_DATE = "2026-06-15"

# Track runs we create for teardown
_created_comp_run_ids: list[str] = []
_created_act_run_ids: list[str] = []
_orig_offline_salary = None


@pytest.fixture(scope="module")
def mongo_db():
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


@pytest.fixture(scope="module")
def token():
    resp = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert resp.status_code == 200, f"admin login failed: {resp.status_code} {resp.text}"
    return resp.json()["session_token"]


@pytest.fixture(scope="module")
def api_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def mutate_and_cleanup(mongo_db):
    """Set exit_date on the target user + flip firm offline_salary; restore
    everything (and delete any runs we generated) at the end."""
    global _orig_offline_salary

    # --- SETUP ---
    mongo_db.users.update_one(
        {"user_id": TARGET_USER_ID}, {"$set": {"exit_date": EXIT_DATE}}
    )
    # Snapshot & flip firm flag so actual-salary-process is callable
    fm = mongo_db.firm_masters.find_one({"company_id": COMPANY_ID}, {"salary_process": 1})
    _orig_offline_salary = ((fm or {}).get("salary_process") or {}).get("offline_salary", False)
    mongo_db.firm_masters.update_one(
        {"company_id": COMPANY_ID},
        {"$set": {"salary_process.offline_salary": True}},
    )
    yield
    # --- TEARDOWN ---
    mongo_db.users.update_one(
        {"user_id": TARGET_USER_ID}, {"$set": {"exit_date": None}}
    )
    mongo_db.firm_masters.update_one(
        {"company_id": COMPANY_ID},
        {"$set": {"salary_process.offline_salary": _orig_offline_salary}},
    )
    if _created_comp_run_ids:
        mongo_db.compliance_salary_runs.delete_many({"run_id": {"$in": _created_comp_run_ids}})
    if _created_act_run_ids:
        mongo_db.salary_runs.delete_many({"run_id": {"$in": _created_act_run_ids}})


# ---------------- unit: helper directly ---------------- #

def test_helper_month_is_after_exit_direct():
    """Unit sanity — verify _month_is_after_exit gives expected results."""
    import sys
    sys.path.insert(0, "/app/backend")
    from server import _month_is_after_exit
    u = {"exit_date": EXIT_DATE}
    # exit 2026-06-15 → 2026-07 is AFTER exit_month → excluded
    assert _month_is_after_exit(u, "2026-07") is True
    # 2026-06 is the exit month → payable → NOT excluded
    assert _month_is_after_exit(u, "2026-06") is False
    # No exit date → never excluded
    assert _month_is_after_exit({}, "2026-07") is False


# ---------------- compliance run ---------------- #

def test_compliance_run_2026_07_excludes_resigned(api_headers, mongo_db):
    """After exit_date=2026-06-15, a 2026-07 compliance run must not list him."""
    resp = requests.post(
        f"{BASE_URL}/api/admin/compliance-salary-runs",
        headers=api_headers,
        json={"month": "2026-07", "company_id": COMPANY_ID},
        timeout=180,
    )
    assert resp.status_code == 200, f"create comp run failed: {resp.status_code} {resp.text}"
    run = resp.json()["run"]
    _created_comp_run_ids.append(run["run_id"])

    rows = run.get("rows") or []
    assert len(rows) > 0, "no rows in run"
    user_ids = {r.get("user_id") for r in rows}
    codes = {str(r.get("employee_code")) for r in rows}
    assert TARGET_USER_ID not in user_ids, (
        f"SURENDRA SINGH (resigned) unexpectedly present in 2026-07 comp run rows"
    )
    assert TARGET_EMP_CODE not in codes
    # Sanity — other employees still processed
    assert len(rows) >= 100, f"row count suspiciously low: {len(rows)}"


def test_compliance_run_2026_06_includes_exit_month(api_headers, mongo_db):
    """Exit month itself is payable → 2026-06 must still include him."""
    resp = requests.post(
        f"{BASE_URL}/api/admin/compliance-salary-runs",
        headers=api_headers,
        json={"month": "2026-06", "company_id": COMPANY_ID},
        timeout=180,
    )
    assert resp.status_code == 200, f"create comp run failed: {resp.status_code} {resp.text}"
    run = resp.json()["run"]
    _created_comp_run_ids.append(run["run_id"])

    rows = run.get("rows") or []
    user_ids = {r.get("user_id") for r in rows}
    assert TARGET_USER_ID in user_ids, (
        "SURENDRA SINGH (exit month = 2026-06) should be INCLUDED for final settlement"
    )


# ---------------- actual salary process ---------------- #

def test_actual_salary_process_2026_07_excludes_resigned(api_headers, mongo_db):
    """POST /api/admin/actual-salary-process for 2026-07 must exclude him."""
    resp = requests.post(
        f"{BASE_URL}/api/admin/actual-salary-process",
        headers=api_headers,
        json={"month": "2026-07", "company_id": COMPANY_ID,
              "attendance_source": "manual"},
        timeout=180,
    )
    # If firm gate still rejects, surface the reason clearly
    assert resp.status_code == 200, (
        f"actual salary process failed: {resp.status_code} {resp.text[:400]}"
    )
    data = resp.json()
    run = data.get("run") or data
    run_id = run.get("run_id")
    if run_id:
        _created_act_run_ids.append(run_id)

    rows = run.get("rows") or []
    assert len(rows) > 0, "actual salary run has no rows"
    user_ids = {r.get("user_id") for r in rows}
    assert TARGET_USER_ID not in user_ids, (
        "SURENDRA SINGH (resigned 2026-06-15) unexpectedly present in actual 2026-07 run"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
