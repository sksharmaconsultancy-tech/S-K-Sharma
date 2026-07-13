"""Iter 61 backend tests — Multi-company Compliance batch, UAN/ESI/PF pin-login,
Payslip auto-email config + dry-run.

Environment: uses EXPO_PUBLIC_BACKEND_URL from process env (falls back to the
preview URL currently configured for this workspace).
"""
import os
import time
import uuid
import asyncio
import requests
import pytest

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com"
).rstrip("/")
SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
COMPANY_ADMIN_PHONE = "+919810000001"
COMPANY_ADMIN_PIN = "387908"  # per /app/memory/test_credentials.md


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _otp_login(api, identifier, channel="email"):
    r = api.post(f"{BASE_URL}/api/auth/otp/request", json={"identifier": identifier, "channel": channel})
    assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    code = body.get("dev_code") or body.get("code")
    assert code, f"No dev code in response: {body}"
    r = api.post(f"{BASE_URL}/api/auth/otp/verify",
                 json={"identifier": identifier, "channel": channel, "code": code})
    assert r.status_code == 200, f"otp/verify failed: {r.status_code} {r.text[:200]}"
    return r.json().get("session_token") or r.json().get("token")


@pytest.fixture(scope="session")
def super_headers(api):
    tok = _otp_login(api, SUPER_ADMIN_EMAIL, "email")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def company_admin_headers(api):
    """Best-effort. If temp PIN was already changed, we skip tests that need it."""
    r = api.post(f"{BASE_URL}/api/auth/pin-login",
                 json={"phone": COMPANY_ADMIN_PHONE, "pin": COMPANY_ADMIN_PIN})
    if r.status_code != 200:
        pytest.skip(f"company_admin pin-login not available: {r.status_code} {r.text[:120]}")
    tok = r.json().get("session_token") or r.json().get("token")
    if not tok:
        pytest.skip("company_admin token missing")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def companies(api, super_headers):
    r = api.get(f"{BASE_URL}/api/companies", headers=super_headers)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    items = body if isinstance(body, list) else (body.get("companies") or body.get("items") or [])
    ids = [c["company_id"] for c in items if c.get("company_id")]
    assert len(ids) >= 1, "Need at least one company"
    return items


# ---------------------------------------------------------------------------
# A. Compliance batch — happy path
# ---------------------------------------------------------------------------
class TestComplianceBatch:
    def test_batch_happy_path(self, api, super_headers, companies):
        cids = [c["company_id"] for c in companies][:2]
        if len(cids) < 2:
            cids = cids * 2  # single-company duplicated — still runs
        body = {"company_ids": cids, "month": "2026-05"}
        r = api.post(f"{BASE_URL}/api/admin/compliance-batches",
                     json=body, headers=super_headers)
        assert r.status_code == 200, f"batch create failed: {r.status_code} {r.text[:400]}"
        data = r.json()
        assert "batch_id" in data
        assert data.get("status") == "running"
        batch_id = data["batch_id"]

        # Poll
        deadline = time.time() + 45
        final = None
        while time.time() < deadline:
            g = api.get(f"{BASE_URL}/api/admin/compliance-batches/{batch_id}",
                        headers=super_headers)
            assert g.status_code == 200, g.text[:200]
            final = g.json()
            jobs = final.get("jobs") or []
            if all(j.get("status") in ("done", "failed") for j in jobs) and \
               final.get("status") in ("completed", "completed_with_errors"):
                break
            time.sleep(1)

        assert final is not None
        assert final.get("status") in ("completed", "completed_with_errors"), \
            f"Batch never completed: {final}"
        jobs = final.get("jobs") or []
        assert jobs, "No jobs found in batch"
        for j in jobs:
            assert j.get("status") in ("done", "failed"), j

        # Each done job's run_id must resolve
        for j in jobs:
            if j.get("status") == "done":
                rid = j.get("run_id")
                assert rid, "done job missing run_id"
                rr = api.get(
                    f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}",
                    headers=super_headers,
                )
                assert rr.status_code == 200, f"run {rid} not resolvable: {rr.status_code} {rr.text[:200]}"
                run_body = rr.json()
                run_obj = run_body.get("run") if isinstance(run_body.get("run"), dict) else run_body
                assert run_obj.get("run_id") == rid, f"unexpected run body: {run_body}"

    def test_batch_empty_ids(self, api, super_headers):
        r = api.post(f"{BASE_URL}/api/admin/compliance-batches",
                     json={"company_ids": [], "month": "2026-05"},
                     headers=super_headers)
        assert r.status_code == 400, f"expected 400 empty ids, got {r.status_code} {r.text[:200]}"

    def test_batch_bogus_company(self, api, super_headers):
        r = api.post(f"{BASE_URL}/api/admin/compliance-batches",
                     json={"company_ids": ["cid_does_not_exist_xyz"], "month": "2026-05"},
                     headers=super_headers)
        assert r.status_code == 404, f"expected 404 bogus company, got {r.status_code} {r.text[:200]}"

    def test_batch_company_admin_forbidden(self, api, company_admin_headers, companies):
        cid = companies[0]["company_id"]
        r = api.post(f"{BASE_URL}/api/admin/compliance-batches",
                     json={"company_ids": [cid], "month": "2026-05"},
                     headers=company_admin_headers)
        assert r.status_code == 403, f"expected 403 for company_admin, got {r.status_code} {r.text[:200]}"


# ---------------------------------------------------------------------------
# B. UAN/ESI/PF login validation + happy path via direct DB seed
# ---------------------------------------------------------------------------
class TestPinLoginAlt:
    def test_uan_short_400(self, api):
        r = api.post(f"{BASE_URL}/api/auth/pin-login",
                     json={"uan_no": "1234", "pin": "000000"})
        assert r.status_code == 400, f"expected 400 short UAN, got {r.status_code} {r.text[:200]}"

    def test_uan_unknown_401(self, api):
        r = api.post(f"{BASE_URL}/api/auth/pin-login",
                     json={"uan_no": "999999999999", "pin": "000000"})
        assert r.status_code == 401, f"expected 401 unknown UAN, got {r.status_code} {r.text[:200]}"

    def test_seeded_uan_esi_pf_login_ok(self, api, companies):
        """Seed a test user directly via motor + server._hash_pin, then login."""
        import sys
        sys.path.insert(0, "/app/backend")
        import server as srv  # noqa: E402

        cid = companies[0]["company_id"]
        pin = "654321"
        pin_hash = srv._hash_pin(pin)

        uan = "100200300400"
        esi = "ESI" + uuid.uuid4().hex[:8].upper()
        pf = "PF" + uuid.uuid4().hex[:8].upper()

        user_id = f"usr_test_{uuid.uuid4().hex[:12]}"
        user_doc = {
            "user_id": user_id,
            "role": "employee",
            "company_id": cid,
            "name": "TEST_iter61_alt_login",
            "phone": "+91" + uuid.uuid4().hex[:10],
            "uan_no": uan,
            "esi_ip_no": esi,
            "pf_no": pf,
            "pin_hash": pin_hash,
            "pin_must_change": False,
            "disabled": False,
            "created_at": "2026-01-01T00:00:00+00:00",
        }

        async def _seed_and_cleanup():
            await srv.db.users.insert_one(user_doc)
            try:
                # ---- UAN
                r = api.post(f"{BASE_URL}/api/auth/pin-login",
                             json={"uan_no": uan, "pin": pin})
                assert r.status_code == 200, f"UAN login: {r.status_code} {r.text[:200]}"
                assert (r.json().get("session_token") or r.json().get("token")), \
                    f"missing token in {r.json()}"
                # ---- ESI
                r = api.post(f"{BASE_URL}/api/auth/pin-login",
                             json={"esi_ip_no": esi, "pin": pin})
                assert r.status_code == 200, f"ESI login: {r.status_code} {r.text[:200]}"
                # ---- PF
                r = api.post(f"{BASE_URL}/api/auth/pin-login",
                             json={"pf_no": pf, "pin": pin})
                assert r.status_code == 200, f"PF login: {r.status_code} {r.text[:200]}"
                # ---- Wrong PIN → 401
                r = api.post(f"{BASE_URL}/api/auth/pin-login",
                             json={"uan_no": uan, "pin": "000000"})
                assert r.status_code == 401, f"wrong pin: {r.status_code}"
            finally:
                await srv.db.users.delete_one({"user_id": user_id})

        asyncio.get_event_loop().run_until_complete(_seed_and_cleanup())


# ---------------------------------------------------------------------------
# C. Payslip email config
# ---------------------------------------------------------------------------
class TestPayslipEmailConfig:
    def test_get_put_get_flow(self, api, super_headers, companies):
        cid = companies[0]["company_id"]

        # Turn off first so we know starting state (test is idempotent).
        api.put(
            f"{BASE_URL}/api/admin/companies/{cid}/payslip-email-config",
            json={"enabled": False}, headers=super_headers,
        )

        # GET → false
        r = api.get(
            f"{BASE_URL}/api/admin/companies/{cid}/payslip-email-config",
            headers=super_headers,
        )
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("enabled") is False

        # PUT true
        r = api.put(
            f"{BASE_URL}/api/admin/companies/{cid}/payslip-email-config",
            json={"enabled": True}, headers=super_headers,
        )
        assert r.status_code == 200, r.text[:200]
        assert r.json() == {"ok": True, "enabled": True}

        # GET → true
        r = api.get(
            f"{BASE_URL}/api/admin/companies/{cid}/payslip-email-config",
            headers=super_headers,
        )
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("enabled") is True

    def test_put_company_admin_forbidden(self, api, company_admin_headers, companies):
        # Pick the admin's own company (they are only allowed to READ it, PUT should still 403)
        cid = None
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=company_admin_headers).json()
        cid = me.get("company_id") or companies[0]["company_id"]
        r = requests.put(
            f"{BASE_URL}/api/admin/companies/{cid}/payslip-email-config",
            json={"enabled": True},
            headers=company_admin_headers,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text[:200]}"


# ---------------------------------------------------------------------------
# D. Payslip email — dry-run + disabled short-circuit
# ---------------------------------------------------------------------------
def _find_or_create_run(api, super_headers, cid):
    """Return an existing salary_run_id for cid, or create a fresh one."""
    r = api.get(f"{BASE_URL}/api/admin/salary-runs?company_id={cid}", headers=super_headers)
    if r.status_code == 200:
        body = r.json()
        items = body if isinstance(body, list) else (body.get("items") or body.get("runs") or [])
        if items:
            return items[0].get("run_id"), items[0].get("month")
    # Create — try last few months
    for m in ("2026-01", "2025-12", "2025-11", "2025-10"):
        r = api.post(f"{BASE_URL}/api/admin/salary-runs",
                     json={"month": m, "company_id": cid}, headers=super_headers)
        if r.status_code == 200:
            run = r.json().get("run") or {}
            return run.get("run_id"), m
    return None, None


class TestPayslipEmailTrigger:
    def test_dry_run_no_log_inserts(self, api, super_headers, companies):
        import sys
        sys.path.insert(0, "/app/backend")
        import server as srv  # noqa: E402

        cid = companies[0]["company_id"]

        # Enable payslip_email_enabled first
        r = api.put(
            f"{BASE_URL}/api/admin/companies/{cid}/payslip-email-config",
            json={"enabled": True}, headers=super_headers,
        )
        assert r.status_code == 200

        run_id, month = _find_or_create_run(api, super_headers, cid)
        if not run_id:
            pytest.skip("Could not obtain a salary run for this company")

        # Count logs before
        async def _count():
            return await srv.db.payslip_email_log.count_documents({"salary_run_id": run_id})

        loop = asyncio.get_event_loop()
        before = loop.run_until_complete(_count())

        r = api.post(
            f"{BASE_URL}/api/admin/salary-runs/{run_id}/email-payslips",
            json={"dry_run": True}, headers=super_headers,
        )
        assert r.status_code == 200, f"dry_run: {r.status_code} {r.text[:200]}"
        body = r.json()
        assert isinstance(body.get("delivered"), int)
        assert body.get("delivered") >= 0
        assert isinstance(body.get("skipped_no_email"), int)

        after = loop.run_until_complete(_count())
        assert after == before, f"dry_run should not insert logs (before={before} after={after})"

    def test_disabled_shortcircuit(self, api, super_headers, companies):
        cid = companies[0]["company_id"]

        # Disable
        r = api.put(
            f"{BASE_URL}/api/admin/companies/{cid}/payslip-email-config",
            json={"enabled": False}, headers=super_headers,
        )
        assert r.status_code == 200

        run_id, _ = _find_or_create_run(api, super_headers, cid)
        if not run_id:
            pytest.skip("Could not obtain a salary run for this company")

        r = api.post(
            f"{BASE_URL}/api/admin/salary-runs/{run_id}/email-payslips",
            json={"dry_run": True}, headers=super_headers,
        )
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body.get("delivered") == 0, body
        assert "payslip_email_enabled=false" in (body.get("note") or ""), body
