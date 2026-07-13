"""
Iteration 23 backend smoke tests — pending approvals endpoints.

Covers:
- GET /api/admin/pending-approvals as super_admin → 200, returns {"pending":[...]}
- GET /api/company-requests as super_admin → 200, returns {"requests":[...]} where each has status
- GET /api/company-requests as an unauth caller → 401/403 (not accessible to non-super_admin)

Does NOT touch super_admin PIN. Uses OTP dev-mode to obtain a session.
"""
import os
import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
SUPER_EMAIL = "sksharmaconsultancy@gmail.com"


def _otp_login(email: str) -> str:
    """Uses OTP dev mode to obtain a session token."""
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": email, "channel": "email"},
        timeout=15,
    )
    r.raise_for_status()
    code = r.json().get("dev_code")
    assert code, f"dev_code missing in OTP response: {r.json()}"
    v = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": email, "channel": "email", "code": code},
        timeout=15,
    )
    v.raise_for_status()
    tok = v.json().get("session_token")
    assert tok, f"session_token missing in verify: {v.json()}"
    return tok


@pytest.fixture(scope="module")
def super_headers():
    tok = _otp_login(SUPER_EMAIL)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# --- /api/admin/pending-approvals ------------------------------------------------
class TestPendingApprovals:
    def test_pending_approvals_super_admin_200(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/pending-approvals",
            headers=super_headers,
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "pending" in body and isinstance(body["pending"], list)
        # Each pending entry should look like a user doc
        for u in body["pending"]:
            assert "user_id" in u
            assert u.get("approval_status") == "pending"

    def test_pending_approvals_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/pending-approvals", timeout=15)
        assert r.status_code in (401, 403), r.text


# --- /api/company-requests -------------------------------------------------------
class TestCompanyRequests:
    def test_company_requests_super_admin_200(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/company-requests",
            headers=super_headers,
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "requests" in body and isinstance(body["requests"], list)
        for req in body["requests"]:
            # Every request MUST expose a status field so the UI can filter by pending
            assert "status" in req, f"status missing in {req}"

    def test_company_requests_requires_super_admin(self):
        r = requests.get(f"{BASE_URL}/api/company-requests", timeout=15)
        assert r.status_code in (401, 403), r.text
