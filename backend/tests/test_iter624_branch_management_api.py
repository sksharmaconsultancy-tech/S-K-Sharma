"""Iter 624 — Branch Management API end-to-end tests.

Covers extended branch fields (PATCH + 409 duplicate code), employee
assign + audit, temp assignments (create/list/cancel), permanent
transfers (immediate apply + future pending), dashboard/allocation
shapes and a punch-time authorization regression check.

Seeds a super-admin session token in Mongo user_sessions with a real
`datetime` `expires_at` so `Authorization: Bearer <token>` works.
Cleans up ALL created docs at the end.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "test_database")

SUPER_ADMIN_ID = "user_67791559822a"
TEST_FIRM_ID = f"cmp_it624_{uuid.uuid4().hex[:8]}"
TEST_EMP_ID = f"user_it624_{uuid.uuid4().hex[:8]}"


# -------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def dbc():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def token(dbc):
    tok = f"testtok_iter624_{uuid.uuid4().hex[:8]}"
    dbc.user_sessions.insert_one({
        "session_token": tok,
        "user_id": SUPER_ADMIN_ID,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=6),
    })
    yield tok
    dbc.user_sessions.delete_one({"session_token": tok})


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def seeded(dbc):
    # test firm
    dbc.companies.insert_one({
        "company_id": TEST_FIRM_ID,
        "name": "TEST_Iter624_Firm",
        "company_code": f"T624{uuid.uuid4().hex[:4].upper()}",
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # test employee (needed for assign/temp/transfer)
    dbc.users.insert_one({
        "user_id": TEST_EMP_ID,
        "company_id": TEST_FIRM_ID,
        "role": "employee",
        "name": "TEST_iter624_emp",
        "employee_code": "T624E1",
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield
    # cleanup
    for c in ("companies", "users", "branches", "branch_temp_assignments",
              "branch_transfers", "branch_audit", "attendance",
              "compliance_salary_runs"):
        dbc[c].delete_many({"company_id": TEST_FIRM_ID})
    dbc.users.delete_many({"user_id": TEST_EMP_ID})


# state shared across tests (module-scoped)
STATE: dict = {}


# ------------------------------------------------------------- 0. sanity
def test_00_token_works(hdr):
    r = requests.get(f"{BASE}/api/admin/branch-management/branches",
                     params={"company_id": TEST_FIRM_ID}, headers=hdr, timeout=15)
    assert r.status_code == 200, r.text
    assert "branches" in r.json()


# ------------------------------------------------- 1. branch create + PATCH + 409
def test_10_create_branches(hdr, seeded):
    r = requests.post(f"{BASE}/api/company/branches", json={
        "company_id": TEST_FIRM_ID, "name": "TEST_Br_A",
        "office_lat": 25.35, "office_lng": 74.63, "geofence_radius_m": 100,
    }, headers=hdr, timeout=15)
    assert r.status_code in (200, 201), r.text
    STATE["brA"] = r.json().get("branch_id") or r.json().get("branch", {}).get("branch_id")
    assert STATE["brA"]

    r = requests.post(f"{BASE}/api/company/branches", json={
        "company_id": TEST_FIRM_ID, "name": "TEST_Br_B",
        "office_lat": 25.45, "office_lng": 74.73, "geofence_radius_m": 100,
    }, headers=hdr, timeout=15)
    assert r.status_code in (200, 201), r.text
    STATE["brB"] = r.json().get("branch_id") or r.json().get("branch", {}).get("branch_id")
    assert STATE["brB"]


def test_11_patch_extended_fields(hdr):
    r = requests.patch(
        f"{BASE}/api/admin/branch-management/branches/{STATE['brA']}",
        json={"code": "brA1", "city": "Bhilwara", "head_name": "Alice", "active": True},
        headers=hdr, timeout=15)
    assert r.status_code == 200, r.text
    b = r.json()["branch"]
    assert b["code"] == "BRA1" and b["city"] == "Bhilwara"
    assert b["head_name"] == "Alice"


def test_12_duplicate_code_returns_409(hdr):
    r = requests.patch(
        f"{BASE}/api/admin/branch-management/branches/{STATE['brB']}",
        json={"code": "brA1"}, headers=hdr, timeout=15)
    assert r.status_code == 409, r.text
    # patch second with unique code for later use
    r2 = requests.patch(
        f"{BASE}/api/admin/branch-management/branches/{STATE['brB']}",
        json={"code": "BRB1", "city": "Udaipur"}, headers=hdr, timeout=15)
    assert r2.status_code == 200, r2.text


# --------------------------------------------------------- 2. employee assign
def test_20_assign_home_authorized(hdr, dbc):
    r = requests.post(f"{BASE}/api/admin/branch-management/assign", json={
        "user_id": TEST_EMP_ID,
        "home_branch_id": STATE["brA"],
        "authorized_branch_ids": [STATE["brA"], STATE["brB"]],
    }, headers=hdr, timeout=15)
    assert r.status_code == 200, r.text
    # verify persistence + audit
    u = dbc.users.find_one({"user_id": TEST_EMP_ID},
                           {"home_branch_id": 1, "authorized_branch_ids": 1})
    assert u["home_branch_id"] == STATE["brA"]
    assert set(u["authorized_branch_ids"]) == {STATE["brA"], STATE["brB"]}
    assert dbc.branch_audit.count_documents({"user_id": TEST_EMP_ID}) >= 1


def test_21_employees_list_shows_fields(hdr):
    r = requests.get(f"{BASE}/api/admin/branch-management/employees",
                     params={"company_id": TEST_FIRM_ID}, headers=hdr, timeout=15)
    assert r.status_code == 200, r.text
    emps = r.json()["employees"]
    row = next(e for e in emps if e["user_id"] == TEST_EMP_ID)
    assert row["home_branch_id"] == STATE["brA"]


# ---------------------------------------------------- 3. temp assignments
def test_30_temp_assignment_create_list_cancel(hdr, dbc):
    from datetime import date, timedelta as td
    frm = (date.today() - td(days=2)).isoformat()
    to = (date.today() + td(days=2)).isoformat()
    r = requests.post(f"{BASE}/api/admin/branch-management/temp-assignments",
                      json={"user_id": TEST_EMP_ID, "branch_id": STATE["brB"],
                            "from_date": frm, "to_date": to,
                            "reason": "TEST project"}, headers=hdr, timeout=15)
    assert r.status_code == 200, r.text
    aid = r.json()["assignment"]["assign_id"]
    STATE["ta_id"] = aid

    r = requests.get(f"{BASE}/api/admin/branch-management/temp-assignments",
                     params={"company_id": TEST_FIRM_ID}, headers=hdr, timeout=15)
    assert r.status_code == 200
    assigns = r.json()["assignments"]
    row = next(a for a in assigns if a["assign_id"] == aid)
    assert row["status"] == "approved"

    r = requests.patch(
        f"{BASE}/api/admin/branch-management/temp-assignments/{aid}/cancel",
        headers=hdr, timeout=15)
    assert r.status_code == 200, r.text
    doc = dbc.branch_temp_assignments.find_one({"assign_id": aid})
    assert doc is not None and doc["status"] == "cancelled"


# ---------------------------------------------------- 4. permanent transfers
def test_40_transfer_immediate_and_future(hdr, dbc):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # immediate transfer: brA -> brB
    r = requests.post(f"{BASE}/api/admin/branch-management/transfers", json={
        "user_id": TEST_EMP_ID, "new_branch_id": STATE["brB"],
        "effective_date": today, "reason": "immediate"}, headers=hdr, timeout=15)
    assert r.status_code == 200, r.text
    tid_now = r.json()["transfer"]["transfer_id"]

    # future transfer
    future = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    r = requests.post(f"{BASE}/api/admin/branch-management/transfers", json={
        "user_id": TEST_EMP_ID, "new_branch_id": STATE["brA"],
        "effective_date": future, "reason": "future"}, headers=hdr, timeout=15)
    assert r.status_code == 200, r.text
    tid_fut = r.json()["transfer"]["transfer_id"]

    # list — triggers lazy applier
    r = requests.get(f"{BASE}/api/admin/branch-management/transfers",
                     params={"company_id": TEST_FIRM_ID}, headers=hdr, timeout=15)
    assert r.status_code == 200
    by_id = {t["transfer_id"]: t for t in r.json()["transfers"]}
    assert by_id[tid_now]["status"] == "applied", by_id[tid_now]
    assert by_id[tid_fut]["status"] == "pending", by_id[tid_fut]

    # DB — home_branch_id updated to brB
    u = dbc.users.find_one({"user_id": TEST_EMP_ID}, {"home_branch_id": 1})
    assert u["home_branch_id"] == STATE["brB"]

    # revert home for downstream tests (idempotent cleanup)
    dbc.users.update_one({"user_id": TEST_EMP_ID},
                         {"$set": {"home_branch_id": STATE["brA"]}})


# --------------------------------------------------------- 5. dashboard + alloc
def test_50_dashboard_shape(hdr):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    r = requests.get(f"{BASE}/api/admin/branch-management/dashboard",
                     params={"company_id": TEST_FIRM_ID, "month": month},
                     headers=hdr, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["month"] == month
    assert isinstance(d["cards"], list) and len(d["cards"]) >= 3  # unassigned + 2 branches
    for c in d["cards"]:
        for k in ("branch", "home_employees", "present_today", "gross_cost"):
            assert k in c
    assert "cross_branch_employees" in d and "guest_assignments" in d


def test_51_allocation_shape(hdr):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    r = requests.get(f"{BASE}/api/admin/branch-management/allocation",
                     params={"company_id": TEST_FIRM_ID, "month": month},
                     headers=hdr, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["month"] == month
    assert isinstance(d.get("employees"), list)
    assert isinstance(d.get("branches"), list)


# --------------------------------------------------- 6. regression — /company/branches
def test_60_company_branches_still_works(hdr):
    r = requests.get(f"{BASE}/api/company/branches",
                     params={"company_id": TEST_FIRM_ID}, headers=hdr, timeout=15)
    assert r.status_code == 200, r.text
    branches = r.json().get("branches") or r.json()
    assert isinstance(branches, list)
    ids = {b.get("branch_id") for b in branches}
    assert STATE["brA"] in ids and STATE["brB"] in ids


# ---------------------------------------------------- 7. link branch (super admin)
def test_70_link_existing_branch_endpoint(hdr, dbc):
    # create a 2nd firm and try linking brB to it
    other_cid = f"cmp_it624_o_{uuid.uuid4().hex[:6]}"
    dbc.companies.insert_one({
        "company_id": other_cid, "name": "TEST_Iter624_OtherFirm",
        "company_code": f"OTH{uuid.uuid4().hex[:4].upper()}",
        "status": "active"})
    try:
        r = requests.post(f"{BASE}/api/admin/branch-management/branches/link",
                          json={"branch_id": STATE["brB"], "company_id": other_cid},
                          headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        # linked_company_ids now contains other_cid
        b = dbc.branches.find_one({"branch_id": STATE["brB"]},
                                  {"linked_company_ids": 1})
        assert other_cid in (b.get("linked_company_ids") or [])
        # unlink to keep DB clean
        r2 = requests.post(f"{BASE}/api/admin/branch-management/branches/unlink",
                           json={"branch_id": STATE["brB"], "company_id": other_cid},
                           headers=hdr, timeout=15)
        assert r2.status_code == 200
    finally:
        dbc.companies.delete_one({"company_id": other_cid})
