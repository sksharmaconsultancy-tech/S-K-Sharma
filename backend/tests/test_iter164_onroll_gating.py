"""Iter 164 — On-roll/Off-roll gating by Firm Master 'Offline Salary'.

Backend regression tests for:
 1. Off-roll rejection when firm's Offline Salary is DISABLED (PATCH user-role
    and PATCH employee profile → 400).
 2. Employee CREATE silently coerces is_onroll=True when Offline Salary is off.
 3. Off-roll allowed when Offline Salary is ENABLED.
 4. Compliance Salary Run FORCE-excludes off-roll employees regardless of
    payload.is_onroll.

Cleanup: all mutated Mongo state (firm_masters.salary_process.offline_salary,
users.is_onroll) is restored; any compliance run created is deleted.
"""

import os
import pytest
import requests
from pymongo import MongoClient

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://emplo-connect-1.preview.emergentagent.com"
)
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"

FIRM_ID = "cmp_527fecdd7c"      # Kankani Enterprises
TARGET_USER = "user_44cd6f561da0"  # SURENDRA SINGH, code 50

mongo = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
db = mongo[os.environ.get("DB_NAME", "test_database")]


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{API}/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def restore_state():
    """Snapshot then restore firm's offline_salary flag and target user's is_onroll."""
    fm_snap = db.firm_masters.find_one({"company_id": FIRM_ID}, {"salary_process": 1})
    u_snap = db.users.find_one({"user_id": TARGET_USER}, {"is_onroll": 1})
    created_runs: list[str] = []

    # Expose the list for tests to append into.
    restore_state.created_runs = created_runs

    yield created_runs

    # Restore offline_salary flag
    orig_off = bool(((fm_snap or {}).get("salary_process") or {}).get("offline_salary"))
    db.firm_masters.update_one(
        {"company_id": FIRM_ID},
        {"$set": {"salary_process.offline_salary": orig_off}},
    )
    # Restore is_onroll
    orig_onroll = (u_snap or {}).get("is_onroll", True)
    db.users.update_one(
        {"user_id": TARGET_USER}, {"$set": {"is_onroll": orig_onroll}}
    )
    # Delete any compliance runs we created
    for rid in created_runs:
        db.compliance_salary_runs.delete_one({"run_id": rid})


def _set_offline_salary(enabled: bool):
    db.firm_masters.update_one(
        {"company_id": FIRM_ID},
        {"$set": {"salary_process.offline_salary": enabled}},
    )


# ---------- 1. Off-roll rejection when Offline Salary is DISABLED ----------
class TestOffrollGate:
    def test_precondition_offline_salary_disabled(self):
        _set_offline_salary(False)
        fm = db.firm_masters.find_one({"company_id": FIRM_ID}, {"_id": 0, "salary_process": 1})
        assert fm["salary_process"]["offline_salary"] is False

    def test_user_role_patch_offroll_rejected(self, auth):
        r = requests.patch(
            f"{API}/admin/user-role",
            headers=auth,
            json={"user_id": TARGET_USER, "is_onroll": False},
            timeout=15,
        )
        assert r.status_code == 400, r.text
        detail = (r.json() or {}).get("detail", "")
        assert "Off-roll" in detail or "Offline Salary" in detail

    def test_profile_patch_offroll_rejected(self, auth):
        r = requests.patch(
            f"{API}/admin/employees/{TARGET_USER}/profile",
            headers=auth,
            json={"is_onroll": False},
            timeout=15,
        )
        assert r.status_code == 400, r.text

    def test_user_role_patch_onroll_true_ok(self, auth):
        r = requests.patch(
            f"{API}/admin/user-role",
            headers=auth,
            json={"user_id": TARGET_USER, "is_onroll": True},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        u = db.users.find_one({"user_id": TARGET_USER}, {"_id": 0, "is_onroll": 1})
        assert u["is_onroll"] is True


# ---------- 2. Employee CREATE coercion ----------
class TestCreateCoercion:
    _temp_user_id: str | None = None

    def test_create_coerces_offroll_to_onroll_when_disabled(self, auth):
        _set_offline_salary(False)
        payload = {
            "name": "TEST_Iter164_temp",
            "phone": "+919000164164",
            "company_id": FIRM_ID,
            "is_onroll": False,   # Should be silently coerced to True
        }
        r = requests.post(f"{API}/admin/employees", headers=auth, json=payload, timeout=15)
        assert r.status_code in (200, 201), r.text
        data = r.json()
        uid = (data.get("user") or {}).get("user_id") or data.get("user_id")
        assert uid, f"no user_id in response: {data}"
        TestCreateCoercion._temp_user_id = uid

        doc = db.users.find_one({"user_id": uid}, {"_id": 0, "is_onroll": 1, "company_id": 1})
        assert doc is not None
        assert doc["is_onroll"] is True, f"expected coerced True, got {doc}"
        assert doc["company_id"] == FIRM_ID

    def test_cleanup_temp_employee(self):
        uid = TestCreateCoercion._temp_user_id
        if not uid:
            pytest.skip("no temp user created")
        db.users.delete_one({"user_id": uid})
        assert db.users.find_one({"user_id": uid}) is None


# ---------- 3. Off-roll allowed when Offline Salary is ENABLED ----------
class TestOffrollWhenEnabled:
    def test_enable_offline_and_offroll_allowed(self, auth):
        _set_offline_salary(True)
        r = requests.patch(
            f"{API}/admin/user-role",
            headers=auth,
            json={"user_id": TARGET_USER, "is_onroll": False},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        u = db.users.find_one({"user_id": TARGET_USER}, {"_id": 0, "is_onroll": 1})
        assert u["is_onroll"] is False


# ---------- 4. Compliance run excludes off-roll ----------
class TestComplianceExcludesOffroll:
    def test_compliance_run_excludes_offroll_target(self, auth):
        # Precondition — target is off-roll, firm Offline Salary is ON (so
        # both salary runs are configurable), Compliance requires online_salary.
        u = db.users.find_one({"user_id": TARGET_USER}, {"_id": 0, "is_onroll": 1})
        assert u["is_onroll"] is False, "target must be off-roll before compliance run"

        payload = {
            "month": "2026-07",
            "company_id": FIRM_ID,
            "is_onroll": False,  # Try to trick the endpoint — must be ignored.
        }
        r = requests.post(
            f"{API}/admin/compliance-salary-runs",
            headers=auth,
            json=payload,
            timeout=60,
        )
        assert r.status_code == 200, r.text
        run = (r.json() or {}).get("run") or {}
        rid = run.get("run_id")
        assert rid
        restore_state.created_runs.append(rid)

        rows = run.get("rows") or []
        user_ids = {row.get("user_id") for row in rows}
        assert TARGET_USER not in user_ids, (
            f"off-roll target {TARGET_USER} MUST be excluded from compliance run, "
            f"but was present. rows_count={len(rows)}"
        )
        # And some on-roll employee IS present
        assert len(rows) > 0, "compliance run should include on-roll employees"

    def test_compliance_run_with_null_is_onroll_still_excludes_offroll(self, auth):
        """Even if payload omits is_onroll, off-roll must be excluded."""
        payload = {"month": "2026-07", "company_id": FIRM_ID}
        r = requests.post(
            f"{API}/admin/compliance-salary-runs",
            headers=auth,
            json=payload,
            timeout=60,
        )
        # It may 409 if the previous run for 2026-07 is FINALIZED — but we
        # never finalize, so it should succeed.
        assert r.status_code == 200, r.text
        run = (r.json() or {}).get("run") or {}
        rid = run.get("run_id")
        if rid:
            restore_state.created_runs.append(rid)
        rows = run.get("rows") or []
        user_ids = {row.get("user_id") for row in rows}
        assert TARGET_USER not in user_ids
