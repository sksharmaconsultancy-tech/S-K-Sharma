"""Iter 125 — Employer Access Rights gating for salary endpoints.

Tests the `require_employer_permission` gate for the Kankani firm's
`company_admin` (admin@kankani.local, cmp_527fecdd7c) against:
  * Salary Actual: POST/GET /api/admin/salary-runs
  * Salary Arrear:  POST/GET /api/admin/arrear-salary-runs
  * Salary Compliance: POST /api/admin/compliance-salary-runs

Super admin is unaffected regardless of the firm's employer_permissions.
"""
import os
import sys
import uuid
import secrets
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv

# Ensure backend .env is loaded so we can talk to Mongo directly for the
# session-injection workaround (Kankani admin's real PIN is unknown).
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["EXPO_BACKEND_URL"].rstrip("/") if os.environ.get("EXPO_BACKEND_URL") else None
if not BASE_URL:
    # Fall back to frontend/.env value which is what real users see
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_ADMIN_PASSWORD = "sharma123"

KANKANI_COMPANY_ID = "cmp_527fecdd7c"
KANKANI_ADMIN_USER_ID = "user_0a38839e3568"
KANKANI_ADMIN_EMAIL = "admin@kankani.local"

SALARY_PERMS = [
    "salary_process:read",
    "salary_process:write",
    "compliance_salary:read",
    "compliance_salary:write",
]

# --------------------------------------------------------------------------
# Session helpers
# --------------------------------------------------------------------------


def _login_super_admin() -> str:
    resp = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": SUPER_ADMIN_EMAIL, "password": SUPER_ADMIN_PASSWORD},
        timeout=30,
    )
    assert resp.status_code == 200, f"super admin login failed: {resp.status_code} {resp.text}"
    tok = resp.json().get("session_token")
    assert tok, f"no session_token in response: {resp.json()}"
    return tok


async def _inject_company_admin_session_async() -> str:
    """Kankani admin's PIN/password was changed by the user — the recorded
    approach in /app/memory/test_credentials.md is to inject a session doc
    directly. Returns the bearer token."""
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    token = f"test_sess_{secrets.token_hex(16)}"
    now = datetime.now(timezone.utc)
    await db.user_sessions.insert_one({
        "session_token": token,
        "user_id": KANKANI_ADMIN_USER_ID,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=2)).isoformat(),
    })
    client.close()
    return token


def _inject_company_admin_session() -> str:
    return asyncio.get_event_loop().run_until_complete(
        _inject_company_admin_session_async()
    ) if False else asyncio.new_event_loop().run_until_complete(
        _inject_company_admin_session_async()
    )


async def _cleanup_session_async(token: str) -> None:
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    await db.user_sessions.delete_one({"session_token": token})
    client.close()


# --------------------------------------------------------------------------
# Employer-permissions helpers (via super-admin API)
# --------------------------------------------------------------------------


def _get_access_rights(sa_token: str) -> dict:
    r = requests.get(
        f"{BASE_URL}/api/admin/companies/{KANKANI_COMPANY_ID}/access-rights",
        headers={"Authorization": f"Bearer {sa_token}"},
        timeout=30,
    )
    assert r.status_code == 200, f"GET access-rights failed: {r.status_code} {r.text}"
    return r.json()


def _set_permissions(sa_token: str, perms):
    """Pass a list to set exactly that array. Pass None to reset (unset)."""
    r = requests.patch(
        f"{BASE_URL}/api/admin/companies/{KANKANI_COMPANY_ID}/access-rights",
        headers={"Authorization": f"Bearer {sa_token}"},
        json={"permissions": perms},
        timeout=30,
    )
    assert r.status_code == 200, f"PATCH access-rights failed: {r.status_code} {r.text}"
    return r.json()


# --------------------------------------------------------------------------
# Salary-run cleanup helpers (delete via direct Mongo)
# --------------------------------------------------------------------------


async def _delete_runs_async(run_ids, arrear_ids, compliance_ids):
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    if run_ids:
        await db.salary_runs.delete_many({"run_id": {"$in": list(run_ids)}})
    if arrear_ids:
        await db.arrear_salary_runs.delete_many({"run_id": {"$in": list(arrear_ids)}})
    if compliance_ids:
        await db.compliance_salary_runs.delete_many({"run_id": {"$in": list(compliance_ids)}})
    client.close()


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def super_admin_token():
    return _login_super_admin()


@pytest.fixture(scope="module")
def company_admin_token():
    tok = _inject_company_admin_session()
    yield tok
    asyncio.new_event_loop().run_until_complete(_cleanup_session_async(tok))


@pytest.fixture(scope="module")
def created_runs():
    """Collects run_ids created during tests for cleanup."""
    bucket = {"salary": set(), "arrear": set(), "compliance": set()}
    yield bucket
    asyncio.new_event_loop().run_until_complete(
        _delete_runs_async(bucket["salary"], bucket["arrear"], bucket["compliance"])
    )


@pytest.fixture(scope="module", autouse=True)
def restore_employer_permissions(super_admin_token):
    """Snapshot the firm's original employer_permissions and restore at end."""
    before = _get_access_rights(super_admin_token)
    original_perms = before.get("permissions") or []
    original_all_enabled = before.get("all_features_enabled", True)
    print(
        f"[SETUP] Kankani original employer_permissions="
        f"{original_perms} all_features_enabled={original_all_enabled}"
    )
    yield
    # Restore
    if original_all_enabled and not original_perms:
        # Unset the field entirely by passing None
        _set_permissions(super_admin_token, None)
        print("[TEARDOWN] Restored Kankani employer_permissions to UNSET (all enabled)")
    else:
        _set_permissions(super_admin_token, original_perms)
        print(f"[TEARDOWN] Restored Kankani employer_permissions to {original_perms}")


# --------------------------------------------------------------------------
# Auth sanity
# --------------------------------------------------------------------------


class TestAuthSanity:
    def test_super_admin_token_works(self, super_admin_token):
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {super_admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("user", {}).get("role") == "super_admin"

    def test_company_admin_token_works(self, company_admin_token):
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {company_admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        user = r.json().get("user", {})
        assert user.get("role") == "company_admin"
        assert user.get("company_id") == KANKANI_COMPANY_ID


# --------------------------------------------------------------------------
# Case A + B — DENIED when firm perms are empty (nothing granted)
# --------------------------------------------------------------------------


class TestDenied:
    """With permissions=[] (no keys granted), company_admin should be
    blocked on all gated salary endpoints with 403."""

    @pytest.fixture(scope="class", autouse=True)
    def _revoke(self, super_admin_token):
        _set_permissions(super_admin_token, [])
        yield

    def test_denied_post_salary_run(self, company_admin_token):
        r = requests.post(
            f"{BASE_URL}/api/admin/salary-runs",
            headers={"Authorization": f"Bearer {company_admin_token}"},
            json={"month": "2026-05", "company_id": KANKANI_COMPANY_ID},
            timeout=60,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:300]}"
        assert "Employer Access Rights" in r.text or "salary_process:write" in r.text, r.text[:300]

    def test_denied_post_arrear_run(self, company_admin_token):
        r = requests.post(
            f"{BASE_URL}/api/admin/arrear-salary-runs",
            headers={"Authorization": f"Bearer {company_admin_token}"},
            json={
                "company_id": KANKANI_COMPANY_ID,
                "from_month": "2026-03",
                "to_month": "2026-04",
            },
            timeout=60,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:300]}"
        assert "Employer Access Rights" in r.text or "salary_process:write" in r.text, r.text[:300]

    def test_denied_post_compliance_run(self, company_admin_token):
        r = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs",
            headers={"Authorization": f"Bearer {company_admin_token}"},
            json={"month": "2026-05", "company_id": KANKANI_COMPANY_ID},
            timeout=60,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:300]}"
        assert "Employer Access Rights" in r.text or "compliance_salary:write" in r.text, r.text[:300]

    def test_denied_get_salary_runs(self, company_admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-runs",
            headers={"Authorization": f"Bearer {company_admin_token}"},
            timeout=30,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:300]}"
        assert "Employer Access Rights" in r.text or "salary_process:read" in r.text, r.text[:300]

    def test_denied_get_arrear_runs(self, company_admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/arrear-salary-runs",
            headers={"Authorization": f"Bearer {company_admin_token}"},
            timeout=30,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:300]}"
        assert "Employer Access Rights" in r.text or "salary_process:read" in r.text, r.text[:300]


# --------------------------------------------------------------------------
# Case D — super admin unaffected by permissions=[]
# --------------------------------------------------------------------------


class TestSuperAdminUnaffected:
    """Same denied-state as TestDenied — super admin still gets 200s."""

    @pytest.fixture(scope="class", autouse=True)
    def _revoke(self, super_admin_token):
        _set_permissions(super_admin_token, [])
        yield

    def test_super_admin_get_salary_runs(self, super_admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-runs",
            params={"company_id": KANKANI_COMPANY_ID},
            headers={"Authorization": f"Bearer {super_admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        assert isinstance(r.json().get("runs"), list)

    def test_super_admin_get_arrear_runs(self, super_admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/arrear-salary-runs",
            params={"company_id": KANKANI_COMPANY_ID},
            headers={"Authorization": f"Bearer {super_admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]

    def test_super_admin_post_salary_run(self, super_admin_token, created_runs):
        month = "2026-05"
        r = requests.post(
            f"{BASE_URL}/api/admin/salary-runs",
            headers={"Authorization": f"Bearer {super_admin_token}"},
            json={"month": month, "company_id": KANKANI_COMPANY_ID},
            timeout=120,
        )
        assert r.status_code == 200, f"super admin POST failed: {r.status_code} {r.text[:300]}"
        run = r.json().get("run") or {}
        assert run.get("run_id"), r.json()
        assert run.get("month") == month
        created_runs["salary"].add(run["run_id"])


# --------------------------------------------------------------------------
# Case C + E — GRANTED, company_admin succeeds
# --------------------------------------------------------------------------


class TestGranted:
    """With all four salary/compliance keys granted, company_admin passes
    the gate. Downstream computation errors (business validation) are OK
    as long as they are NOT 403 for the permission itself."""

    @pytest.fixture(scope="class", autouse=True)
    def _grant(self, super_admin_token):
        j = _set_permissions(super_admin_token, SALARY_PERMS)
        assert set(SALARY_PERMS).issubset(set(j.get("permissions") or [])), j
        yield

    def test_get_salary_runs_ok(self, company_admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-runs",
            headers={"Authorization": f"Bearer {company_admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert isinstance(body.get("runs"), list)

    def test_get_arrear_runs_ok(self, company_admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/arrear-salary-runs",
            headers={"Authorization": f"Bearer {company_admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        assert isinstance(r.json().get("runs"), list)

    def test_post_salary_run_ok(self, company_admin_token, created_runs):
        month = "2026-05"
        r = requests.post(
            f"{BASE_URL}/api/admin/salary-runs",
            headers={"Authorization": f"Bearer {company_admin_token}"},
            json={"month": month, "company_id": KANKANI_COMPANY_ID},
            timeout=120,
        )
        assert r.status_code == 200, f"company_admin POST failed: {r.status_code} {r.text[:400]}"
        run = r.json().get("run") or {}
        assert run.get("run_id"), r.json()
        assert run.get("company_id") == KANKANI_COMPANY_ID
        assert run.get("month") == month
        created_runs["salary"].add(run["run_id"])

    def test_get_single_salary_run_ok(self, company_admin_token, created_runs):
        # Reuse one of the created run_ids
        assert created_runs["salary"], "no salary run created earlier"
        rid = next(iter(created_runs["salary"]))
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-runs/{rid}",
            headers={"Authorization": f"Bearer {company_admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("run", {}).get("run_id") == rid or body.get("run_id") == rid

    def test_post_arrear_run_not_403(self, company_admin_token, created_runs):
        """Arrear needs from/to months and prior compliance runs. If the
        firm has no compliance runs yet, backend may return 400 — that's
        fine, as long as it isn't a 403 permission block."""
        r = requests.post(
            f"{BASE_URL}/api/admin/arrear-salary-runs",
            headers={"Authorization": f"Bearer {company_admin_token}"},
            json={
                "company_id": KANKANI_COMPANY_ID,
                "from_month": "2026-03",
                "to_month": "2026-04",
            },
            timeout=120,
        )
        assert r.status_code != 403, f"unexpected 403 with grant: {r.text[:400]}"
        if r.status_code == 200:
            run = r.json().get("run") or r.json()
            rid = run.get("run_id") if isinstance(run, dict) else None
            if rid:
                created_runs["arrear"].add(rid)

    def test_post_compliance_run_not_403(self, company_admin_token, created_runs):
        r = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs",
            headers={"Authorization": f"Bearer {company_admin_token}"},
            json={"month": "2026-05", "company_id": KANKANI_COMPANY_ID},
            timeout=180,
        )
        assert r.status_code != 403, f"unexpected 403 with grant: {r.text[:400]}"
        if r.status_code == 200:
            run = r.json().get("run") or {}
            rid = run.get("run_id")
            if rid:
                created_runs["compliance"].add(rid)
