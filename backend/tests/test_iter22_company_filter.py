"""
Iteration 22 — Backend smoke for the new Super Admin company-wise filter.

Covers:
- GET /api/admin/stats?company_id=<id>   scoped correctly for super_admin
- GET /api/admin/payroll?status=pending&company_id=<id>  returns 200
- GET /api/admin/employees?company_id=<id>  returns only that company's users
- company_admin CANNOT read another company's data via ?company_id=<other>
  (server ignores the param and forces user.company_id)

Uses OTP (dev mode) to sign in as the hard-coded super_admin
(sksharmaconsultancy@gmail.com) without touching its PIN fields.
Creates two ephemeral companies + one ephemeral company_admin (via Path B
`admin_phone` on POST /companies which returns a temp PIN). Cleans up
everything at the end.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or \
           "https://emplo-connect-1.preview.emergentagent.com"
API = f"{BASE_URL}/api"
SUPER_EMAIL = "sksharmaconsultancy@gmail.com"


# ---- helpers --------------------------------------------------------------
def _otp_login(identifier: str, channel: str = "email") -> tuple[str, dict]:
    r = requests.post(f"{API}/auth/otp/request",
                      json={"identifier": identifier, "channel": channel}, timeout=15)
    assert r.status_code == 200, f"otp request failed: {r.status_code} {r.text}"
    code = r.json().get("dev_code")
    assert code, f"no dev_code in OTP response: {r.json()}"
    r2 = requests.post(f"{API}/auth/otp/verify",
                       json={"identifier": identifier, "channel": channel, "code": code}, timeout=15)
    assert r2.status_code == 200, f"otp verify failed: {r2.status_code} {r2.text}"
    body = r2.json()
    return body["session_token"], body["user"]


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ---- fixtures -------------------------------------------------------------
@pytest.fixture(scope="module")
def super_token():
    tok, user = _otp_login(SUPER_EMAIL, "email")
    assert user["role"] == "super_admin", f"expected super_admin, got {user['role']}"
    return tok


@pytest.fixture(scope="module")
def ephemeral_companies(super_token):
    """Create 2 ephemeral companies, delete them (force) at teardown."""
    unique_a = uuid.uuid4().hex[:6]
    unique_b = uuid.uuid4().hex[:6]
    a = requests.post(f"{API}/companies", headers=_auth(super_token),
                      json={"name": f"TEST_ITER22_A_{unique_a}",
                            "address": "Alpha Test Road 42",
                            "office_lat": 28.6139, "office_lng": 77.2090,
                            "geofence_radius_m": 200}, timeout=15)
    assert a.status_code in (200, 201), f"create A failed: {a.status_code} {a.text}"
    body_a = a.json()

    # Company B is created with admin_phone → returns a temp PIN so we can
    # log in as a company_admin
    admin_phone = f"+9198{uuid.uuid4().hex[:8]}"
    b = requests.post(f"{API}/companies", headers=_auth(super_token),
                      json={"name": f"TEST_ITER22_B_{unique_b}",
                            "address": "Bravo Test Lane 7",
                            "office_lat": 28.7041, "office_lng": 77.1025,
                            "geofence_radius_m": 200,
                            "admin_phone": admin_phone}, timeout=15)
    assert b.status_code in (200, 201), f"create B failed: {b.status_code} {b.text}"
    body_b = b.json()
    temp_pin = (body_b.get("admin") or {}).get("temp_pin") or body_b.get("temp_pin")

    yield {"a": body_a, "b": body_b, "admin_phone": admin_phone, "temp_pin": temp_pin}

    for cid in (body_a.get("company_id"), body_b.get("company_id")):
        if cid:
            requests.delete(f"{API}/companies/{cid}?force=true", headers=_auth(super_token), timeout=15)


# ---- tests ----------------------------------------------------------------
class TestSuperAdminCompanyFilter:
    def test_health(self):
        r = requests.get(f"{API}/", timeout=10)
        assert r.status_code == 200

    def test_stats_all_companies(self, super_token):
        r = requests.get(f"{API}/admin/stats", headers=_auth(super_token), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("total_employees", "present_today", "pending_leaves",
                  "open_tickets", "total_companies"):
            assert k in body, f"missing key {k} in stats: {body}"
        assert isinstance(body["total_companies"], int)
        assert body["total_companies"] >= 0

    def test_stats_scoped_by_company_id(self, super_token, ephemeral_companies):
        cid_a = ephemeral_companies["a"]["company_id"]
        r = requests.get(f"{API}/admin/stats?company_id={cid_a}",
                         headers=_auth(super_token), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        # A brand-new empty company should have 0 employees / 0 leaves / 0 tickets
        assert body["total_employees"] == 0, f"expected empty company, got {body}"
        assert body["pending_leaves"] == 0
        assert body["open_tickets"] == 0

    def test_payroll_scoped(self, super_token, ephemeral_companies):
        cid_a = ephemeral_companies["a"]["company_id"]
        r = requests.get(f"{API}/admin/payroll?status=pending&company_id={cid_a}",
                         headers=_auth(super_token), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "payslips" in body
        assert isinstance(body["payslips"], list)
        # Empty company -> no payslips
        assert body["payslips"] == []

    def test_employees_scoped(self, super_token, ephemeral_companies):
        cid_a = ephemeral_companies["a"]["company_id"]
        r = requests.get(f"{API}/admin/employees?company_id={cid_a}",
                         headers=_auth(super_token), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "employees" in body
        # Every returned employee must belong to company_id A (empty is OK)
        for e in body["employees"]:
            assert e.get("company_id") == cid_a, f"leaked user from other company: {e}"

    def test_company_admin_cannot_read_other_company(self, super_token, ephemeral_companies):
        """company_admin who tries ?company_id=<other> must be forced to their own."""
        temp_pin = ephemeral_companies["temp_pin"]
        admin_phone = ephemeral_companies["admin_phone"]
        cid_b = ephemeral_companies["b"]["company_id"]
        cid_a = ephemeral_companies["a"]["company_id"]

        if not temp_pin:
            pytest.skip("Path B did not return temp_pin — cannot test company_admin scoping")

        # Log in as the newly-created company_admin (they belong to company B).
        # Try phone-based pin-login.
        r = requests.post(f"{API}/auth/pin-login",
                          json={"phone": admin_phone, "pin": temp_pin}, timeout=15)
        if r.status_code != 200:
            pytest.skip(f"pin-login for ephemeral admin failed: {r.status_code} {r.text}")
        body = r.json()
        if body.get("must_change_pin"):
            # Change the temp PIN so we get a real session
            new_pin = "594827"
            change_token = body.get("change_token") or body.get("session_token")
            if not change_token:
                pytest.skip("no change_token to complete PIN rotation")
            r2 = requests.post(f"{API}/auth/change-pin",
                               headers={"Authorization": f"Bearer {change_token}"},
                               json={"current_pin": temp_pin, "new_pin": new_pin},
                               timeout=15)
            if r2.status_code != 200:
                pytest.skip(f"change-pin failed: {r2.status_code} {r2.text}")
            r3 = requests.post(f"{API}/auth/pin-login",
                               json={"phone": admin_phone, "pin": new_pin}, timeout=15)
            assert r3.status_code == 200, r3.text
            body = r3.json()

        admin_tok = body.get("session_token")
        assert admin_tok, f"no session token for company_admin: {body}"

        # Verify /auth/me shows they're on company B
        me_resp = requests.get(f"{API}/auth/me", headers=_auth(admin_tok), timeout=15).json()
        me = me_resp.get("user", me_resp)
        assert me.get("role") in ("company_admin", "super_admin"), f"me={me}"
        my_company = me.get("company_id")
        assert my_company == cid_b, f"admin should be on company B, got {my_company}"

        # Request stats with SOMEONE ELSE'S company_id — server MUST ignore it
        r = requests.get(f"{API}/admin/stats?company_id={cid_a}",
                         headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200
        # As a security probe: we can't inspect "which docs" the server counted,
        # but we can assert that both stats endpoints return the SAME totals
        # regardless of the company_id query param (because the server forces
        # user.company_id).
        r_own = requests.get(f"{API}/admin/stats?company_id={cid_b}",
                             headers=_auth(admin_tok), timeout=15)
        r_naked = requests.get(f"{API}/admin/stats",
                               headers=_auth(admin_tok), timeout=15)
        assert r.status_code == r_own.status_code == r_naked.status_code == 200
        # If server ignores hostile company_id, all three responses match.
        assert r.json() == r_own.json() == r_naked.json(), (
            "company_admin scoping leak: /admin/stats returned different values "
            "for company_id=A vs company_id=B vs no param"
        )

        # Same probe for /admin/employees — the response must ONLY contain
        # users of company B, never company A's.
        emp = requests.get(f"{API}/admin/employees?company_id={cid_a}",
                          headers=_auth(admin_tok), timeout=15)
        assert emp.status_code == 200
        for e in emp.json().get("employees", []):
            assert e.get("company_id") == cid_b, (
                f"company_admin leaked employee from another company: {e}"
            )
