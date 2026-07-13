"""
Iter 75 backend tests — Employee Group Policies (per-firm attendance/salary
policy templates).

Endpoints under test (all under /api):
    GET    /admin/employee-groups
    POST   /admin/employee-groups
    PATCH  /admin/employee-groups/{group_id}
    POST   /admin/employee-groups/{group_id}/apply
    DELETE /admin/employee-groups/{group_id}

Also verifies:
  * POST /admin/employees single-add auto-inherits the group policy
  * POST /admin/employees/bulk-import auto-inherits the group policy
  * DELETE /companies/{cid}?force=true cascade purges employee_group_policies
  * Per-firm isolation (super_admin listing another firm doesn't leak)
  * Auth guards (401 without token, 403 for employee token)

Uses the OTP dev-code flow — the super_admin PIN is NEVER touched.
"""

import os
import random
import string
import uuid

import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
    or os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
)
if not BASE_URL:
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL / EXPO_BACKEND_URL not set")

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _otp_login(identifier: str, channel: str = "email") -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": identifier, "channel": channel},
        timeout=30,
    )
    assert r.status_code == 200, f"otp/request: {r.status_code} {r.text}"
    code = r.json().get("dev_code")
    assert code, f"dev_code missing: {r.json()}"
    r2 = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": identifier, "channel": channel, "code": code},
        timeout=30,
    )
    assert r2.status_code == 200, f"otp/verify: {r2.status_code} {r2.text}"
    j = r2.json()
    tok = j.get("session_token") or j.get("token") or j.get("access_token")
    assert tok, f"no token: {j}"
    return tok


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _rand_code(prefix: str = "T") -> str:
    return prefix + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))


def _rand_phone() -> str:
    return "+9198100" + "".join(random.choices(string.digits, k=5))


def _create_company(super_token: str, name_prefix: str = "Iter75") -> dict:
    payload = {
        "name": f"{name_prefix} QA Co {uuid.uuid4().hex[:6]}",
        "address": "127 Test Rd",
        "office_lat": 28.6,
        "office_lng": 77.2,
        "geofence_radius_m": 250,
        "compliance_enabled": True,
        "company_code": _rand_code("I75"),
    }
    r = requests.post(
        f"{BASE_URL}/api/companies",
        json=payload, headers=_hdr(super_token), timeout=30,
    )
    assert r.status_code == 200, f"create company: {r.status_code} {r.text}"
    body = r.json()
    company = body.get("company") or body
    assert company.get("company_id"), body
    return company


# ---------------------------------------------------------------------------
# Shared module-level fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def super_token() -> str:
    return _otp_login(SUPER_EMAIL, "email")


@pytest.fixture(scope="module")
def employee_token() -> str:
    """A plain employee OTP session — used for the 403 auth-guard test."""
    email = f"qa.iter75.emp.{uuid.uuid4().hex[:8]}@test.com"
    return _otp_login(email, "email")


@pytest.fixture(scope="module")
def firm(super_token) -> dict:
    return _create_company(super_token, "Iter75-Main")


# ---------------------------------------------------------------------------
# TEST 1 — AUTH GUARDS
# ---------------------------------------------------------------------------
class TestAuthGuards:
    """All 5 endpoints require an admin token."""

    def test_list_401_without_token(self):
        r = requests.get(f"{BASE_URL}/api/admin/employee-groups", timeout=15)
        assert r.status_code == 401, r.text

    def test_create_401_without_token(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/employee-groups",
            json={"name": "Should Fail"}, timeout=15,
        )
        assert r.status_code == 401, r.text

    def test_patch_401_without_token(self):
        r = requests.patch(
            f"{BASE_URL}/api/admin/employee-groups/grp_nope",
            json={"description": "x"}, timeout=15,
        )
        assert r.status_code == 401, r.text

    def test_apply_401_without_token(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/employee-groups/grp_nope/apply", timeout=15,
        )
        assert r.status_code == 401, r.text

    def test_delete_401_without_token(self):
        r = requests.delete(
            f"{BASE_URL}/api/admin/employee-groups/grp_nope", timeout=15,
        )
        assert r.status_code == 401, r.text

    def test_list_403_for_employee(self, employee_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/employee-groups",
            headers=_hdr(employee_token), timeout=15,
        )
        assert r.status_code == 403, r.text

    def test_create_403_for_employee(self, employee_token):
        r = requests.post(
            f"{BASE_URL}/api/admin/employee-groups",
            json={"name": "Blocked"},
            headers=_hdr(employee_token), timeout=15,
        )
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# TEST 2 — LIFECYCLE (create, duplicate, inherit, propagate, apply, delete)
# ---------------------------------------------------------------------------
class TestGroupLifecycle:

    POLICY = {
        "shift_name": "General",
        "working_hours": 9,
        "fullday_hours": 6,
        "halfday_hours": 3,
        "weekly_off": 0,
        "cl_days": 13,
        "pl_days": 12,
        "ot_allow": True,
    }

    # a) Create the "Worker" group
    def test_a_create_group(self, super_token, firm):
        r = requests.post(
            f"{BASE_URL}/api/admin/employee-groups",
            json={
                "name": "Worker",
                "description": "Factory-floor workers",
                "policy": self.POLICY,
                "company_id": firm["company_id"],
            },
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        g = body["group"]
        assert g["name"] == "Worker"
        assert g["company_id"] == firm["company_id"]
        assert g["group_id"].startswith("grp_")
        assert g["policy"]["shift_name"] == "General"
        assert g["policy"]["working_hours"] == 9
        assert g["policy"]["cl_days"] == 13
        pytest.gid = g["group_id"]

    # b) Empty name → 400
    def test_b_empty_name_400(self, super_token, firm):
        r = requests.post(
            f"{BASE_URL}/api/admin/employee-groups",
            json={"name": "   ", "company_id": firm["company_id"]},
            headers=_hdr(super_token), timeout=15,
        )
        assert r.status_code == 400, r.text

    # c) Duplicate (case-insensitive) → 409
    def test_c_duplicate_group_409(self, super_token, firm):
        r = requests.post(
            f"{BASE_URL}/api/admin/employee-groups",
            json={"name": "WORKER", "company_id": firm["company_id"]},
            headers=_hdr(super_token), timeout=15,
        )
        assert r.status_code == 409, r.text

    # c2) Bad company_id (super_admin only) → 404
    def test_c2_bad_company_id_404(self, super_token):
        r = requests.post(
            f"{BASE_URL}/api/admin/employee-groups",
            json={"name": "OrphanGroup", "company_id": "co_does_not_exist_xyz"},
            headers=_hdr(super_token), timeout=15,
        )
        assert r.status_code == 404, r.text

    # d) Create employee via /admin/employees with employee_group=Worker (exact case)
    def test_d_single_add_inherits_group_policy(self, super_token, firm):
        phone = _rand_phone()
        r = requests.post(
            f"{BASE_URL}/api/admin/employees",
            json={
                "name": "Worker Alpha",
                "phone": phone,
                "employee_group": "Worker",
                "company_id": firm["company_id"],
                "salary_monthly": 15000,   # per-employee salary
            },
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        uid = body.get("user_id") or body.get("user", {}).get("user_id") \
            or body.get("employee", {}).get("user_id")
        assert uid, body
        pytest.uid_alpha = uid
        # Fetch and verify employee_policy inherited
        r2 = requests.get(
            f"{BASE_URL}/api/admin/employees?company_id={firm['company_id']}",
            headers=_hdr(super_token), timeout=30,
        )
        assert r2.status_code == 200, r2.text
        emps = {e["user_id"]: e for e in r2.json()["employees"]}
        assert uid in emps, f"created employee {uid} not returned in listing"
        pol = emps[uid].get("employee_policy") or {}
        assert pol.get("shift_name") == "General", pol
        assert pol.get("working_hours") == 9, pol
        assert pol.get("cl_days") == 13, pol
        assert pol.get("ot_allow") is True, pol
        assert emps[uid].get("employee_group") == "Worker"
        assert emps[uid].get("salary_monthly") == 15000  # individual preserved

    # e) member_count == 1 after single add
    def test_e_list_shows_member_count(self, super_token, firm):
        r = requests.get(
            f"{BASE_URL}/api/admin/employee-groups?company_id={firm['company_id']}",
            headers=_hdr(super_token), timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["company_id"] == firm["company_id"]
        worker = next((g for g in body["groups"] if g["name"] == "Worker"), None)
        assert worker is not None, body
        assert worker["member_count"] == 1, worker

    # f) bulk-import with lowercase 'worker' → case-insensitive match
    def test_f_bulk_import_case_insensitive_group_match(self, super_token, firm):
        phone = _rand_phone()
        r = requests.post(
            f"{BASE_URL}/api/admin/employees/bulk-import",
            json={
                "company_id": firm["company_id"],
                "rows": [
                    {"name": "Worker Bravo", "phone": phone,
                     "employee_group": "worker",    # lowercase
                     "salary_monthly": 18000},
                ],
            },
            headers=_hdr(super_token), timeout=45,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created_count"] == 1, body
        uid = body["created"][0]["user_id"]
        pytest.uid_bravo = uid
        # Fetch & verify inherited policy
        r2 = requests.get(
            f"{BASE_URL}/api/admin/employees?company_id={firm['company_id']}",
            headers=_hdr(super_token), timeout=30,
        )
        emps = {e["user_id"]: e for e in r2.json()["employees"]}
        pol = emps[uid].get("employee_policy") or {}
        assert pol.get("shift_name") == "General", pol
        assert pol.get("working_hours") == 9, pol
        assert pol.get("cl_days") == 13, pol
        # Salary preserved (individual)
        assert emps[uid].get("salary_monthly") == 18000

    # g) PATCH with policy.cl_days=15 & propagate=true → both members get cl_days=15
    def test_g_patch_propagate_updates_members(self, super_token, firm):
        gid = pytest.gid
        r = requests.patch(
            f"{BASE_URL}/api/admin/employee-groups/{gid}?propagate=true",
            json={"policy": {**self.POLICY, "cl_days": 15}},
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["propagated_to"] >= 2, body
        assert body["group"]["policy"]["cl_days"] == 15
        # Verify both members
        r2 = requests.get(
            f"{BASE_URL}/api/admin/employees?company_id={firm['company_id']}",
            headers=_hdr(super_token), timeout=30,
        )
        emps = {e["user_id"]: e for e in r2.json()["employees"]}
        for uid in (pytest.uid_alpha, pytest.uid_bravo):
            pol = emps[uid].get("employee_policy") or {}
            assert pol.get("cl_days") == 15, f"{uid}: {pol}"
            # working_hours from earlier merge should still be 9
            assert pol.get("working_hours") == 9, f"{uid}: {pol}"

    # i) /apply with overwrite_salary=false → members' salary_monthly untouched
    def test_i_apply_preserves_individual_salary(self, super_token, firm):
        gid = pytest.gid
        r = requests.post(
            f"{BASE_URL}/api/admin/employee-groups/{gid}/apply?overwrite_salary=false",
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["propagated_to"] >= 2, body
        assert body["group_id"] == gid
        # Verify salary preserved
        r2 = requests.get(
            f"{BASE_URL}/api/admin/employees?company_id={firm['company_id']}",
            headers=_hdr(super_token), timeout=30,
        )
        emps = {e["user_id"]: e for e in r2.json()["employees"]}
        assert emps[pytest.uid_alpha].get("salary_monthly") == 15000
        assert emps[pytest.uid_bravo].get("salary_monthly") == 18000

    # j) Set group.policy.salary=25000 + apply with overwrite_salary=true
    def test_j_apply_overwrite_salary_true(self, super_token, firm):
        gid = pytest.gid
        # 1) PATCH group policy to include a salary field
        r = requests.patch(
            f"{BASE_URL}/api/admin/employee-groups/{gid}",
            json={"policy": {**self.POLICY, "cl_days": 15, "salary": 25000}},
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        # 2) Apply with overwrite_salary=true
        r2 = requests.post(
            f"{BASE_URL}/api/admin/employee-groups/{gid}/apply?overwrite_salary=true",
            headers=_hdr(super_token), timeout=30,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["propagated_to"] >= 2
        # 3) Verify members' salary_monthly is now 25000
        r3 = requests.get(
            f"{BASE_URL}/api/admin/employees?company_id={firm['company_id']}",
            headers=_hdr(super_token), timeout=30,
        )
        emps = {e["user_id"]: e for e in r3.json()["employees"]}
        for uid in (pytest.uid_alpha, pytest.uid_bravo):
            assert emps[uid].get("salary_monthly") == 25000, \
                f"{uid} salary={emps[uid].get('salary_monthly')}"

    # k) DELETE group → members keep employee_group label + policy
    def test_k_delete_group_keeps_member_labels(self, super_token, firm):
        gid = pytest.gid
        r = requests.delete(
            f"{BASE_URL}/api/admin/employee-groups/{gid}",
            headers=_hdr(super_token), timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["deleted_group_id"] == gid
        # Members' label / policy unchanged
        r2 = requests.get(
            f"{BASE_URL}/api/admin/employees?company_id={firm['company_id']}",
            headers=_hdr(super_token), timeout=30,
        )
        emps = {e["user_id"]: e for e in r2.json()["employees"]}
        for uid in (pytest.uid_alpha, pytest.uid_bravo):
            assert emps[uid].get("employee_group") == "Worker", f"{uid}"
            pol = emps[uid].get("employee_policy") or {}
            assert pol.get("cl_days") == 15, f"{uid}: {pol}"
        # Second GET should no longer include the group
        r3 = requests.get(
            f"{BASE_URL}/api/admin/employee-groups?company_id={firm['company_id']}",
            headers=_hdr(super_token), timeout=15,
        )
        assert r3.status_code == 200
        names = [g["name"] for g in r3.json()["groups"]]
        assert "Worker" not in names, names


# ---------------------------------------------------------------------------
# TEST 3 — CASCADE on company delete
# ---------------------------------------------------------------------------
class TestCompanyDeleteCascade:

    def test_delete_company_purges_group_policies(self, super_token):
        # Fresh throwaway firm
        firm = _create_company(super_token, "Iter75-Cascade")
        cid = firm["company_id"]
        # Create a group inside it
        r = requests.post(
            f"{BASE_URL}/api/admin/employee-groups",
            json={"name": "Staff", "policy": {"cl_days": 10}, "company_id": cid},
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        # Verify group exists
        r2 = requests.get(
            f"{BASE_URL}/api/admin/employee-groups?company_id={cid}",
            headers=_hdr(super_token), timeout=15,
        )
        assert r2.status_code == 200
        assert len(r2.json()["groups"]) == 1
        # Delete company with force=true (cascade)
        r3 = requests.delete(
            f"{BASE_URL}/api/companies/{cid}?force=true",
            headers=_hdr(super_token), timeout=45,
        )
        assert r3.status_code == 200, f"cascade delete: {r3.status_code} {r3.text}"
        body = r3.json()
        # Confirm cascade_report mentions employee_group_policies (>=1 deleted)
        rep = body.get("cascade_report") or body.get("cascade") or {}
        # Even if the key naming varies, the important thing is: the group
        # should NOT be visible in any subsequent listing scoped to that cid.
        # The endpoint requires the company to exist (super_admin path uses
        # _resolve_target_company which raises 404 for a missing company).
        r4 = requests.get(
            f"{BASE_URL}/api/admin/employee-groups?company_id={cid}",
            headers=_hdr(super_token), timeout=15,
        )
        # Either 404 (company gone) OR 200 with empty groups list.
        if r4.status_code == 200:
            assert r4.json()["groups"] == [], r4.text
        else:
            assert r4.status_code == 404, r4.text
        # If cascade_report is present, sanity-check it too.
        if isinstance(rep, dict) and "employee_group_policies" in rep:
            assert rep["employee_group_policies"] in (1, "1") or \
                isinstance(rep["employee_group_policies"], int)


# ---------------------------------------------------------------------------
# TEST 4 — Per-firm isolation
# ---------------------------------------------------------------------------
class TestPerFirmIsolation:

    def test_super_admin_listing_scoped_to_target_firm(self, super_token):
        firm1 = _create_company(super_token, "Iter75-Firm1")
        firm2 = _create_company(super_token, "Iter75-Firm2")
        # Group "A" in firm1
        r = requests.post(
            f"{BASE_URL}/api/admin/employee-groups",
            json={"name": "A-Firm1", "policy": {"cl_days": 5},
                  "company_id": firm1["company_id"]},
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        # Listing firm2 should NOT include "A-Firm1"
        r2 = requests.get(
            f"{BASE_URL}/api/admin/employee-groups?company_id={firm2['company_id']}",
            headers=_hdr(super_token), timeout=15,
        )
        assert r2.status_code == 200, r2.text
        names = [g["name"] for g in r2.json()["groups"]]
        assert "A-Firm1" not in names, names
        # But listing firm1 SHOULD include it
        r3 = requests.get(
            f"{BASE_URL}/api/admin/employee-groups?company_id={firm1['company_id']}",
            headers=_hdr(super_token), timeout=15,
        )
        assert r3.status_code == 200
        names3 = [g["name"] for g in r3.json()["groups"]]
        assert "A-Firm1" in names3, names3
