"""Iter 73 — AI Insights endpoints (super_admin only).

Covers the 4 new endpoints in /app/backend/server.py:
  GET  /api/admin/ai/firms
  POST /api/admin/ai/ask
  GET  /api/admin/ai/summary?month=YYYY-MM
  GET  /api/admin/ai/anomalies

Plus a smoke check on POST /api/admin/employees/bulk-import
(which was previously broken by an IndentationError).
"""
from __future__ import annotations

import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
if not BASE_URL:
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL (or EXPO_BACKEND_URL) must be set for tests")
BASE_URL = BASE_URL.rstrip("/")

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
FALLBACK_STRING = "AI unavailable"


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------
@pytest.fixture(scope="session")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def super_admin_token(api_client):
    """Login as super_admin via the OTP dev-code flow."""
    r1 = api_client.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email"},
        timeout=30,
    )
    assert r1.status_code == 200, f"OTP request failed: {r1.status_code} {r1.text}"
    j1 = r1.json()
    dev_code = j1.get("dev_code")
    assert dev_code, f"dev_code missing from OTP response — check OTP_DEV_MODE. Body: {j1}"

    r2 = api_client.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email", "code": dev_code},
        timeout=30,
    )
    assert r2.status_code == 200, f"OTP verify failed: {r2.status_code} {r2.text}"
    j2 = r2.json()
    tok = j2.get("session_token")
    assert tok, f"session_token missing in OTP verify response: {j2}"
    assert j2.get("user", {}).get("role") == "super_admin", (
        f"expected super_admin role, got: {j2.get('user', {}).get('role')}"
    )
    return tok


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ----------------------------------------------------------------------------
# 1. AUTH GUARD — no token → 401
# ----------------------------------------------------------------------------
class TestAuthGuardNoToken:
    def test_firms_requires_token(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/admin/ai/firms", timeout=15)
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_ask_requires_token(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/admin/ai/ask",
            json={"question": "hello"},
            timeout=15,
        )
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_summary_requires_token(self, api_client):
        r = api_client.get(
            f"{BASE_URL}/api/admin/ai/summary?month=2026-06", timeout=15
        )
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_anomalies_requires_token(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/admin/ai/anomalies", timeout=15)
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"


# ----------------------------------------------------------------------------
# 1b. AUTH GUARD — bad token → 401
# ----------------------------------------------------------------------------
class TestAuthGuardBadToken:
    def test_firms_bad_token(self, api_client):
        r = api_client.get(
            f"{BASE_URL}/api/admin/ai/firms",
            headers=_auth("not-a-real-token"),
            timeout=15,
        )
        assert r.status_code == 401, f"expected 401 for bad token, got {r.status_code}"


# ----------------------------------------------------------------------------
# 1c. AUTH GUARD — non-super-admin (employee) → 403
# ----------------------------------------------------------------------------
@pytest.fixture(scope="session")
def employee_token(api_client):
    """Get an employee-role OTP session so we can verify 403 gating."""
    ident = "qa.iter73.emp@test.com"
    r1 = api_client.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": ident, "channel": "email"},
        timeout=30,
    )
    if r1.status_code != 200:
        pytest.skip(f"OTP request for employee failed: {r1.status_code} {r1.text}")
    code = r1.json().get("dev_code")
    if not code:
        pytest.skip("dev_code not returned for employee OTP")
    r2 = api_client.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": ident, "channel": "email", "code": code},
        timeout=30,
    )
    if r2.status_code != 200:
        pytest.skip(f"OTP verify for employee failed: {r2.status_code} {r2.text}")
    j = r2.json()
    if j.get("user", {}).get("role") != "employee":
        pytest.skip(
            f"expected employee role, got {j.get('user', {}).get('role')} — cannot verify 403"
        )
    return j["session_token"]


class TestAuthGuardEmployee:
    def test_firms_forbidden_for_employee(self, api_client, employee_token):
        r = api_client.get(
            f"{BASE_URL}/api/admin/ai/firms",
            headers=_auth(employee_token),
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403 for employee, got {r.status_code}: {r.text}"

    def test_ask_forbidden_for_employee(self, api_client, employee_token):
        r = api_client.post(
            f"{BASE_URL}/api/admin/ai/ask",
            json={"question": "test"},
            headers=_auth(employee_token),
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403 for employee, got {r.status_code}: {r.text}"

    def test_summary_forbidden_for_employee(self, api_client, employee_token):
        r = api_client.get(
            f"{BASE_URL}/api/admin/ai/summary?month=2026-06",
            headers=_auth(employee_token),
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403 for employee, got {r.status_code}: {r.text}"

    def test_anomalies_forbidden_for_employee(self, api_client, employee_token):
        r = api_client.get(
            f"{BASE_URL}/api/admin/ai/anomalies",
            headers=_auth(employee_token),
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403 for employee, got {r.status_code}: {r.text}"


# ----------------------------------------------------------------------------
# 2. GET /api/admin/ai/firms as super_admin
# ----------------------------------------------------------------------------
class TestFirmsList:
    def test_firms_ok(self, api_client, super_admin_token):
        r = api_client.get(
            f"{BASE_URL}/api/admin/ai/firms",
            headers=_auth(super_admin_token),
            timeout=30,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert "firms" in body, f"'firms' key missing in response: {body}"
        assert isinstance(body["firms"], list), f"firms should be a list, got {type(body['firms'])}"
        # If firms present, spot-check structure & absence of _id
        if body["firms"]:
            f0 = body["firms"][0]
            assert "_id" not in f0, "_id must be excluded from firms payload"


# ----------------------------------------------------------------------------
# 3. POST /api/admin/ai/ask as super_admin
# ----------------------------------------------------------------------------
class TestAiAsk:
    def test_ask_returns_nonempty_reply(self, api_client, super_admin_token):
        r = api_client.post(
            f"{BASE_URL}/api/admin/ai/ask",
            headers=_auth(super_admin_token),
            json={"question": "How many firms and employees do I have right now?"},
            timeout=180,  # LLM calls can be slow
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert "reply" in body and "session_id" in body, f"missing keys in body: {body}"
        reply = body["reply"]
        sid = body["session_id"]
        assert isinstance(reply, str) and reply.strip(), f"'reply' must be non-empty string: {reply!r}"
        assert isinstance(sid, str) and sid.strip(), f"'session_id' must be non-empty string: {sid!r}"
        assert FALLBACK_STRING not in reply, (
            f"reply looks like an AI-unavailable fallback: {reply!r}"
        )

    def test_ask_missing_question_400(self, api_client, super_admin_token):
        r = api_client.post(
            f"{BASE_URL}/api/admin/ai/ask",
            headers=_auth(super_admin_token),
            json={"question": ""},
            timeout=30,
        )
        assert r.status_code == 400, f"expected 400 for empty question, got {r.status_code}: {r.text}"


# ----------------------------------------------------------------------------
# 4. GET /api/admin/ai/summary
# ----------------------------------------------------------------------------
class TestAiSummary:
    def test_summary_ok(self, api_client, super_admin_token):
        r = api_client.get(
            f"{BASE_URL}/api/admin/ai/summary?month=2026-06",
            headers=_auth(super_admin_token),
            timeout=180,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("month") == "2026-06", f"month echo mismatch: {body}"
        summary = body.get("summary", "")
        assert isinstance(summary, str) and summary.strip(), f"'summary' empty: {summary!r}"
        assert FALLBACK_STRING not in summary, f"summary looks like fallback: {summary!r}"

    # 6. VALIDATE bad month
    def test_summary_bad_month_400(self, api_client, super_admin_token):
        r = api_client.get(
            f"{BASE_URL}/api/admin/ai/summary?month=2026",
            headers=_auth(super_admin_token),
            timeout=15,
        )
        assert r.status_code == 400, f"expected 400 for bad month, got {r.status_code}: {r.text}"


# ----------------------------------------------------------------------------
# 5. GET /api/admin/ai/anomalies
# ----------------------------------------------------------------------------
class TestAiAnomalies:
    def test_anomalies_ok(self, api_client, super_admin_token):
        r = api_client.get(
            f"{BASE_URL}/api/admin/ai/anomalies",
            headers=_auth(super_admin_token),
            timeout=180,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        anomalies = body.get("anomalies", "")
        assert isinstance(anomalies, str) and anomalies.strip(), f"'anomalies' empty: {anomalies!r}"
        assert FALLBACK_STRING not in anomalies, f"anomalies looks like fallback: {anomalies!r}"


# ----------------------------------------------------------------------------
# 7. Bulk-import smoke check — endpoint must exist and NOT 5xx
# ----------------------------------------------------------------------------
class TestBulkImportSmoke:
    def test_bulk_import_endpoint_exists(self, api_client):
        """No auth header → we expect 401 (guard) not 5xx (crash).
        The point is only to confirm the previously-broken endpoint is
        back online after the IndentationError fix."""
        r = api_client.post(
            f"{BASE_URL}/api/admin/employees/bulk-import",
            json={"rows": []},
            timeout=15,
        )
        assert r.status_code < 500, (
            f"bulk-import returned server error {r.status_code}: {r.text}"
        )
        # 401 (no token) or 422 (validation) or 400 are all fine here.
        assert r.status_code in (400, 401, 403, 422), (
            f"unexpected status for no-auth bulk-import: {r.status_code}: {r.text}"
        )
