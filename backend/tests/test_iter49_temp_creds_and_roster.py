"""
Iteration 49 — Temp credential display / auto-wipe + Resort Live-in Roster.

Covers:
  * POST /api/companies with admin_phone (+/- admin_email) returns plaintext
    temp_pin / temp_password ONCE and no *_hash fields leak.
  * GET  /api/companies/{id}/details returns a temp_credentials block for the
    super admin as long as pin_must_change / password_must_change is true,
    and hides the plaintext once the admin changes them.
  * POST /api/auth/pin-change  by the new company_admin using the temp_pin
    successfully flips pin_must_change=false and wipes temp_pin_plaintext.
  * POST /api/auth/admin-password-login using temp_password succeeds; then
    /api/auth/admin-set-password wipes temp_password_plaintext.
  * POST /api/companies/{id}/admin/reset-pin      regenerates a fresh temp_pin
  * POST /api/companies/{id}/admin/reset-password regenerates a fresh temp pw
  * Security: temp_pin_plaintext / temp_password_plaintext are NEVER returned
    from /api/auth/me or /api/admin/employees.
  * Resort/Hotel Live-in Roster: GET /admin/attendance/roster,
    POST /admin/attendance/roster/mark  — batch mark IN, verify record.
"""
from __future__ import annotations

import os
import re
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to the same var the tests directory has been using historically
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break

assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be defined"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    return s


def _get_super_admin_token(api: requests.Session) -> str:
    # OTP_DEV_MODE returns the code in the response
    r = api.post(f"{BASE_URL}/api/auth/otp/request",
                 json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email"})
    assert r.status_code == 200, r.text
    body = r.json()
    code = body.get("code") or body.get("dev_code")
    assert code, f"OTP_DEV_MODE not returning code: {body}"
    r = api.post(f"{BASE_URL}/api/auth/otp/verify",
                 json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email", "code": code})
    assert r.status_code == 200, r.text
    token = r.json().get("session_token")
    assert token
    return token


@pytest.fixture(scope="session")
def super_token(api):
    return _get_super_admin_token(api)


@pytest.fixture(scope="session")
def sh(super_token):
    return {"Authorization": f"Bearer {super_token}",
            "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Company + admin scaffolding (one shared throwaway per module)
# ---------------------------------------------------------------------------
def _rand_suffix() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture(scope="session")
def created_company(api, sh):
    """Create a fresh throwaway company WITH both admin_phone and admin_email."""
    suf = _rand_suffix()
    phone = f"+9199{int(time.time()) % 10000000:07d}"
    email = f"qa_admin_{suf}@example.com"
    payload = {
        "name": f"TEST_TempCreds_{suf}",
        "address": "123 QA Street, Bangalore",
        "office_lat": 12.9716,
        "office_lng": 77.5946,
        "geofence_radius_m": 100,
        "compliance_enabled": True,
        "admin_phone": phone,
        "admin_email": email,
        "admin_name": f"QA Admin {suf}",
    }
    r = api.post(f"{BASE_URL}/api/companies", json=payload, headers=sh)
    assert r.status_code == 200, r.text
    data = r.json()
    data["_creds"] = {"phone": phone, "email": email}
    yield data
    # Cleanup — best effort
    try:
        api.delete(f"{BASE_URL}/api/companies/{data['company_id']}", headers=sh)
    except Exception:
        pass


# =============================================================================
# 1. POST /api/companies — temp_pin AND temp_password (both admin channels)
# =============================================================================
class TestCreateCompanyWithBothChannels:
    def test_response_contains_temp_credentials(self, created_company):
        assert "admin" in created_company
        adm = created_company["admin"]
        # Non-empty plaintext credentials returned once
        assert isinstance(adm.get("temp_pin"), str)
        assert re.fullmatch(r"\d{6}", adm["temp_pin"]), adm["temp_pin"]
        # Sanity: not trivially the same digit
        assert len(set(adm["temp_pin"])) > 1
        assert adm["temp_pin"] not in {"123456", "654321", "000000", "111111"}
        assert isinstance(adm.get("temp_password"), str)
        assert len(adm["temp_password"]) >= 8

    def test_response_does_not_leak_hashes(self, created_company):
        adm = created_company["admin"]
        # No pin_hash / password_hash should appear anywhere in create-company response
        flat = str(created_company)
        assert "pin_hash" not in flat
        assert "password_hash" not in flat
        # And the admin block should not carry the plaintext under any hash-flavoured key
        for k in ("pin_hash", "password_hash", "temp_pin_hash", "temp_password_hash"):
            assert k not in adm


# =============================================================================
# 2. POST /api/companies — admin_phone only (no email → temp_password=None)
# =============================================================================
class TestCreateCompanyPhoneOnly:
    def test_no_email_means_no_temp_password(self, api, sh):
        suf = _rand_suffix()
        phone = f"+9198{int(time.time()) % 10000000:07d}"
        payload = {
            "name": f"TEST_PhoneOnly_{suf}",
            "address": "QA lane",
            "office_lat": 12.9,
            "office_lng": 77.6,
            "geofence_radius_m": 80,
            "compliance_enabled": True,
            "admin_phone": phone,
            "admin_name": f"PO Admin {suf}",
        }
        r = api.post(f"{BASE_URL}/api/companies", json=payload, headers=sh)
        assert r.status_code == 200, r.text
        data = r.json()
        try:
            adm = data["admin"]
            assert re.fullmatch(r"\d{6}", adm.get("temp_pin") or ""), adm
            assert adm.get("temp_password") is None, adm
            # Nothing hashy in the response
            assert "pin_hash" not in str(data)
            assert "password_hash" not in str(data)
        finally:
            api.delete(f"{BASE_URL}/api/companies/{data['company_id']}", headers=sh)


# =============================================================================
# 3. GET /api/companies/{id}/details — temp_credentials block visible pre-change
# =============================================================================
class TestCompanyDetailsShowsTempCredsUntilChanged:
    def test_details_shows_plaintext_before_pin_change(self, api, sh, created_company):
        cid = created_company["company_id"]
        r = api.get(f"{BASE_URL}/api/companies/{cid}/details", headers=sh)
        assert r.status_code == 200, r.text
        details = r.json()
        tc = details.get("temp_credentials")
        assert tc, details
        assert tc.get("temp_pin") == created_company["admin"]["temp_pin"]
        assert tc.get("temp_password") == created_company["admin"]["temp_password"]
        assert tc.get("pin_changed") is False
        assert tc.get("password_changed") is False
        # No hashes leak in the whole response
        assert "pin_hash" not in str(details)
        assert "password_hash" not in str(details)


# =============================================================================
# 4. Admin uses temp_pin to log in and change it → plaintext must be wiped.
# =============================================================================
class TestPinChangeWipesPlaintext:
    def test_pin_change_flow(self, api, sh, created_company):
        creds = created_company["_creds"]
        temp_pin = created_company["admin"]["temp_pin"]
        # Login as the new admin using phone + temp_pin
        r = api.post(f"{BASE_URL}/api/auth/admin-pin-login",
                     json={"identifier": creds["phone"], "pin": temp_pin})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("pin_must_change") is True
        admin_token = body["session_token"]
        # Change PIN
        new_pin = "428173"
        r = api.post(f"{BASE_URL}/api/auth/pin-change",
                     json={"current_pin": temp_pin, "new_pin": new_pin},
                     headers={"Authorization": f"Bearer {admin_token}",
                              "Content-Type": "application/json"})
        assert r.status_code == 200, r.text
        # Now check details endpoint as super admin
        cid = created_company["company_id"]
        r = api.get(f"{BASE_URL}/api/companies/{cid}/details", headers=sh)
        assert r.status_code == 200, r.text
        tc = r.json().get("temp_credentials")
        assert tc.get("temp_pin") is None, tc
        assert tc.get("pin_changed") is True, tc
        # temp_password still present because password hasn't been changed yet
        assert tc.get("temp_password") == created_company["admin"]["temp_password"]
        assert tc.get("password_changed") is False


# =============================================================================
# 5. Admin uses temp_password to log in and change it → plaintext must be wiped.
# =============================================================================
class TestPasswordChangeWipesPlaintext:
    def test_password_flow(self, api, sh, created_company):
        creds = created_company["_creds"]
        temp_password = created_company["admin"]["temp_password"]
        r = api.post(f"{BASE_URL}/api/auth/admin-password-login",
                     json={"email": creds["email"], "password": temp_password})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("password_must_change") is True
        admin_token = body["session_token"]
        new_password = "NewStr0ngPass!" + _rand_suffix()
        r = api.post(f"{BASE_URL}/api/auth/admin-set-password",
                     json={"current_password": temp_password, "new_password": new_password},
                     headers={"Authorization": f"Bearer {admin_token}",
                              "Content-Type": "application/json"})
        assert r.status_code == 200, r.text
        # details endpoint
        cid = created_company["company_id"]
        r = api.get(f"{BASE_URL}/api/companies/{cid}/details", headers=sh)
        assert r.status_code == 200, r.text
        tc = r.json().get("temp_credentials")
        assert tc.get("temp_password") is None, tc
        assert tc.get("password_changed") is True, tc


# =============================================================================
# 6. super_admin resets pin / password → plaintext reappears in details block.
# =============================================================================
class TestSuperAdminResetsRegenerate:
    def test_reset_pin_endpoint(self, api, sh, created_company):
        cid = created_company["company_id"]
        r = api.post(f"{BASE_URL}/api/companies/{cid}/admin/reset-pin",
                     json={}, headers=sh)
        assert r.status_code == 200, r.text
        new_temp_pin = r.json().get("temp_pin")
        assert re.fullmatch(r"\d{6}", new_temp_pin or ""), r.json()
        # details reflects it
        d = api.get(f"{BASE_URL}/api/companies/{cid}/details", headers=sh).json()
        assert d["temp_credentials"]["temp_pin"] == new_temp_pin
        assert d["temp_credentials"]["pin_changed"] is False

    def test_reset_password_endpoint(self, api, sh, created_company):
        cid = created_company["company_id"]
        r = api.post(f"{BASE_URL}/api/companies/{cid}/admin/reset-password",
                     json={}, headers=sh)
        assert r.status_code == 200, r.text
        new_temp_pw = r.json().get("temp_password")
        assert isinstance(new_temp_pw, str) and len(new_temp_pw) >= 8
        d = api.get(f"{BASE_URL}/api/companies/{cid}/details", headers=sh).json()
        assert d["temp_credentials"]["temp_password"] == new_temp_pw
        assert d["temp_credentials"]["password_changed"] is False


# =============================================================================
# 7. Security: temp_pin_plaintext / temp_password_plaintext MUST NEVER surface
#    on /auth/me or /admin/employees.
# =============================================================================
class TestSecurityNoLeaks:
    def test_no_leak_on_auth_me(self, api, sh, created_company):
        # log in fresh as the admin using the CURRENT temp_pin (regenerated in prior test)
        cid = created_company["company_id"]
        details = api.get(f"{BASE_URL}/api/companies/{cid}/details", headers=sh).json()
        current_temp_pin = details["temp_credentials"]["temp_pin"]
        creds = created_company["_creds"]
        login = api.post(f"{BASE_URL}/api/auth/admin-pin-login",
                        json={"identifier": creds["phone"], "pin": current_temp_pin})
        assert login.status_code == 200, login.text
        admin_token = login.json()["session_token"]
        me = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {admin_token}"})
        assert me.status_code == 200, me.text
        u = me.json().get("user", {})
        # These plaintext fields must not appear in /auth/me
        assert "temp_pin_plaintext" not in u, u.keys()
        assert "temp_password_plaintext" not in u, u.keys()
        assert "pin_hash" not in u
        assert "password_hash" not in u

    def test_no_leak_on_admin_employees(self, api, sh, created_company):
        cid = created_company["company_id"]
        r = api.get(f"{BASE_URL}/api/admin/employees",
                    headers=sh, params={"company_id": cid})
        assert r.status_code == 200, r.text
        body_text = str(r.json())
        # Neither the plaintext field name nor the hash field name should appear
        assert "temp_pin_plaintext" not in body_text, "LEAK: /admin/employees returns temp_pin_plaintext"
        assert "temp_password_plaintext" not in body_text, "LEAK: /admin/employees returns temp_password_plaintext"
        assert "pin_hash" not in body_text, "LEAK: /admin/employees returns pin_hash"
        assert "password_hash" not in body_text, "LEAK: /admin/employees returns password_hash"


# =============================================================================
# 8. Resort/Hotel Live-in Roster
# =============================================================================
class TestRoster:
    def test_get_and_mark_roster(self, api, sh, created_company):
        cid = created_company["company_id"]
        # Create a live-in employee in the company via db-agnostic path — we
        # can't reach the DB directly here, so provision by creating an
        # employee via /admin/employees POST (if exposed) — otherwise skip
        # the marking sub-test but still verify GET works.

        # GET roster (empty is a valid state)
        r = api.get(f"{BASE_URL}/api/admin/attendance/roster",
                    headers=sh, params={"company_id": cid})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "roster" in body and "date" in body and "count" in body
        assert isinstance(body["roster"], list)

        # Attempt to onboard a live-in employee via the employee-signup path,
        # then approve them + set is_live_in from the admin panel.
        # If any of those endpoints aren't present, we still report the GET
        # coverage and skip mark.
        emp_email = f"qa_livein_{_rand_suffix()}@example.com"
        emp_phone = f"+9197{int(time.time()) % 10000000:07d}"

        # Employee self-signup into the company (no OTP needed for signup)
        company_code = created_company["company_code"]
        sup = api.post(f"{BASE_URL}/api/auth/employee-signup",
                       json={"company_code": company_code,
                             "name": "QA LiveIn",
                             "phone": emp_phone,
                             "pin": "718293",
                             "email": emp_email,
                             "position": "Housekeeping"})
        if sup.status_code not in (200, 201):
            pytest.skip(f"employee-signup unexpected: {sup.status_code} {sup.text}")
        emp_user_id = sup.json()["user_id"]

        # Approve employee (super_admin action)
        approve_r = api.patch(f"{BASE_URL}/api/admin/approve-employee",
                              json={"user_id": emp_user_id, "action": "approve"},
                              headers=sh)
        if approve_r.status_code != 200:
            pytest.skip(f"approve-employee unexpected: {approve_r.status_code} {approve_r.text}")

        # Mark live-in via user-role PATCH
        patch_r = api.patch(f"{BASE_URL}/api/admin/user-role",
                            json={"user_id": emp_user_id,
                                  "is_live_in": True},
                            headers=sh)
        if patch_r.status_code not in (200, 204):
            pytest.skip(f"admin user-role patch unexpected: {patch_r.status_code} {patch_r.text}")

        # GET roster again — the live-in employee should now be listed.
        r = api.get(f"{BASE_URL}/api/admin/attendance/roster",
                    headers=sh, params={"company_id": cid})
        assert r.status_code == 200, r.text
        listing = r.json()["roster"]
        target = next((row for row in listing if row["user_id"] == emp_user_id), None)
        assert target, f"live-in employee not found in roster: {listing}"
        assert target.get("is_live_in") is True
        assert target.get("state") == "absent"  # no punches yet

        # Mark IN via roster — this bypasses geofence entirely.
        mark_r = api.post(f"{BASE_URL}/api/admin/attendance/roster/mark",
                          json={"marks": [{"user_id": emp_user_id, "action": "in"}],
                                "note": "QA test"},
                          headers=sh)
        assert mark_r.status_code == 200, mark_r.text
        results = mark_r.json()["results"]
        assert len(results) == 1 and results[0]["ok"] is True, results

        # Verify state flips to "in"
        r2 = api.get(f"{BASE_URL}/api/admin/attendance/roster",
                     headers=sh, params={"company_id": cid}).json()
        target2 = next((row for row in r2["roster"] if row["user_id"] == emp_user_id), None)
        assert target2 and target2["state"] == "in", target2
