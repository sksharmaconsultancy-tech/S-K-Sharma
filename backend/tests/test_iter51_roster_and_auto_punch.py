"""
Iteration 51 — Roster action → Employee side sync + Auto-punch effective toggle.

Covers:
  * POST /api/admin/attendance/roster/mark
      - action='in'      → creates attendance record source=roster,status=approved
                           and GET /api/attendance/today returns it for that employee.
      - action='out'     → same. If no open IN exists, returns ok:false / detail='not currently in'.
      - action='absent'  → NEW. Persists attendance record kind=absent,
                           source=roster, status=approved. Idempotent second call
                           (updates existing row, no duplicate).
      - Retract: after absent + then IN on same day, absent record must be DELETED.
  * POST /api/attendance/punch — latitude/longitude REQUIRED (422 missing).
  * PATCH /api/companies/{id} — auto_punch_enabled toggle works for super_admin.
      GET /api/companies/{id}/details reflects it.
  * GET /api/auth/me effective_auto_punch resolution
      - company auto_punch_enabled=false → employees see effective_auto_punch=false
      - reset to true → effective_auto_punch=true
      - per-employee override PATCH /api/admin/user-role auto_punch_enabled=false
        even when company is true.
      - explicit null clears the override so it re-inherits company (Pydantic
        model_fields_set behaviour).
      - is_live_in=true → effective_auto_punch=false regardless.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest
import requests


# ---------------------------------------------------------------------------
# Base URL — read from EXPO_PUBLIC_BACKEND_URL (frontend/.env)
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break

assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be defined"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    return s


def _otp_login(api: requests.Session, identifier: str, channel: str = "email") -> str:
    r = api.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": identifier, "channel": channel},
    )
    assert r.status_code == 200, r.text
    code = r.json().get("code") or r.json().get("dev_code")
    assert code, f"OTP dev-code missing: {r.json()}"
    r = api.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": identifier, "channel": channel, "code": code},
    )
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token")
    assert tok
    return tok


@pytest.fixture(scope="session")
def super_token(api):
    return _otp_login(api, SUPER_ADMIN_EMAIL, "email")


@pytest.fixture(scope="session")
def sh(super_token):
    return {"Authorization": f"Bearer {super_token}",
            "Content-Type": "application/json"}


def _rand() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture(scope="session")
def company_with_employees(api, sh):
    """Create throwaway company + 2 employees (regular + will-be-live-in)."""
    suf = _rand()
    payload = {
        "name": f"TEST_Iter51_{suf}",
        "address": "QA Iter51",
        "office_lat": 12.9716,
        "office_lng": 77.5946,
        "geofence_radius_m": 100,
        "compliance_enabled": True,
        "admin_phone": f"+9195{int(time.time()) % 10000000:07d}",
        "admin_email": f"iter51_admin_{suf}@example.com",
        "admin_name": f"QA Iter51 Admin {suf}",
    }
    r = api.post(f"{BASE_URL}/api/companies", json=payload, headers=sh)
    assert r.status_code == 200, r.text
    company = r.json()
    cid = company["company_id"]
    company_code = company["company_code"]

    # Onboard 2 employees
    def _signup(role_tag: str) -> tuple[str, str]:
        rnd = _rand()
        email = f"iter51_{role_tag}_{rnd}@example.com"
        # Use a hex-derived digit suffix so parallel/sequential signups within
        # the same second never collide on phone number.
        phone = f"+9194{int(rnd, 16) % 10000000:07d}"
        r = api.post(
            f"{BASE_URL}/api/auth/employee-signup",
            json={
                "company_code": company_code,
                "name": f"QA {role_tag} {_rand()}",
                "phone": phone,
                "pin": "294857",
                "email": email,
                "position": "Tester",
            },
        )
        assert r.status_code in (200, 201), r.text
        uid = r.json()["user_id"]
        # approve
        ar = api.patch(
            f"{BASE_URL}/api/admin/approve-employee",
            json={"user_id": uid, "action": "approve"},
            headers=sh,
        )
        assert ar.status_code == 200, ar.text
        return uid, email

    emp_uid, emp_email = _signup("emp")
    time.sleep(0.05)
    live_uid, live_email = _signup("livein")

    yield {
        "company_id": cid,
        "company_code": company_code,
        "emp_uid": emp_uid,
        "emp_email": emp_email,
        "live_uid": live_uid,
        "live_email": live_email,
    }

    # cleanup — best effort
    try:
        api.delete(f"{BASE_URL}/api/companies/{cid}", headers=sh)
    except Exception:
        pass


@pytest.fixture(scope="session")
def emp_token(api, company_with_employees):
    return _otp_login(api, company_with_employees["emp_email"], "email")


# ===========================================================================
# 1. Roster mark: IN + reflects on /attendance/today
# ===========================================================================
class TestRosterMarkIn:
    def test_mark_in_creates_record_and_shows_on_today(
        self, api, sh, emp_token, company_with_employees,
    ):
        uid = company_with_employees["emp_uid"]
        r = api.post(
            f"{BASE_URL}/api/admin/attendance/roster/mark",
            json={"marks": [{"user_id": uid, "action": "in"}], "note": "iter51-in"},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 1
        res = body["results"][0]
        assert res["ok"] is True and res["action"] == "in"
        record_id = res["record_id"]

        # Employee side — GET /api/attendance/today
        me_hdr = {"Authorization": f"Bearer {emp_token}"}
        today_r = api.get(f"{BASE_URL}/api/attendance/today", headers=me_hdr)
        assert today_r.status_code == 200, today_r.text
        today_body = today_r.json()
        recs = today_body.get("records") or []
        match = next((x for x in recs if x.get("record_id") == record_id), None)
        assert match, f"record {record_id} not visible to employee: {recs}"
        assert match.get("kind") == "in"
        assert match.get("source") == "roster"
        assert match.get("status") == "approved"


# ===========================================================================
# 2. Roster mark: OUT + guard when no open IN
# ===========================================================================
class TestRosterMarkOut:
    def test_mark_out_after_in(self, api, sh, emp_token, company_with_employees):
        uid = company_with_employees["emp_uid"]
        # Assumes previous test already marked IN
        r = api.post(
            f"{BASE_URL}/api/admin/attendance/roster/mark",
            json={"marks": [{"user_id": uid, "action": "out"}], "note": "iter51-out"},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        res = r.json()["results"][0]
        assert res["ok"] is True and res["action"] == "out"
        record_id = res["record_id"]

        me_hdr = {"Authorization": f"Bearer {emp_token}"}
        today_r = api.get(f"{BASE_URL}/api/attendance/today", headers=me_hdr).json()
        recs = today_r.get("records") or []
        match = next((x for x in recs if x.get("record_id") == record_id), None)
        assert match and match.get("kind") == "out"
        assert match.get("source") == "roster"
        assert match.get("status") == "approved"

    def test_mark_out_without_open_in_returns_not_currently_in(
        self, api, sh, company_with_employees,
    ):
        # live-in employee (no punches yet today)
        uid = company_with_employees["live_uid"]
        r = api.post(
            f"{BASE_URL}/api/admin/attendance/roster/mark",
            json={"marks": [{"user_id": uid, "action": "out"}]},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        res = r.json()["results"][0]
        assert res["ok"] is False, res
        assert "not currently in" in (res.get("detail") or "").lower(), res


# ===========================================================================
# 3. Roster mark: ABSENT (NEW behaviour) + idempotency
# ===========================================================================
class TestRosterMarkAbsent:
    def test_absent_persists_and_shows_on_today(
        self, api, sh, company_with_employees,
    ):
        # Use live employee — they have no IN today. Login as them separately.
        live_email = company_with_employees["live_email"]
        live_token = _otp_login(api, live_email, "email")
        uid = company_with_employees["live_uid"]

        r = api.post(
            f"{BASE_URL}/api/admin/attendance/roster/mark",
            json={"marks": [{"user_id": uid, "action": "absent"}], "note": "leave"},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        res = r.json()["results"][0]
        assert res["ok"] is True and res["action"] == "absent"
        rid = res["record_id"]

        me_hdr = {"Authorization": f"Bearer {live_token}"}
        today = api.get(f"{BASE_URL}/api/attendance/today", headers=me_hdr).json()
        recs = today.get("records") or []
        match = next((x for x in recs if x.get("record_id") == rid), None)
        assert match, f"absent record not visible to employee: {recs}"
        assert match.get("kind") == "absent"
        assert match.get("source") == "roster"
        assert match.get("status") == "approved"

    def test_absent_second_call_is_idempotent(
        self, api, sh, company_with_employees,
    ):
        uid = company_with_employees["live_uid"]
        # First call already made in prior test — call again
        r = api.post(
            f"{BASE_URL}/api/admin/attendance/roster/mark",
            json={"marks": [{"user_id": uid, "action": "absent"}], "note": "refresh"},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        res = r.json()["results"][0]
        assert res["ok"] is True and res["action"] == "absent"
        assert res.get("updated") is True, res

        # Verify only ONE absent record for this user today
        live_token = _otp_login(api, company_with_employees["live_email"], "email")
        me_hdr = {"Authorization": f"Bearer {live_token}"}
        today = api.get(f"{BASE_URL}/api/attendance/today", headers=me_hdr).json()
        absents = [x for x in (today.get("records") or []) if x.get("kind") == "absent"]
        assert len(absents) == 1, f"expected exactly one absent record, got {absents}"


# ===========================================================================
# 4. Retract absent when marking IN on same day
# ===========================================================================
class TestRetractAbsentByIn:
    def test_marking_in_deletes_absent(self, api, sh, company_with_employees):
        uid = company_with_employees["live_uid"]
        # Ensure absent exists (idempotent)
        api.post(
            f"{BASE_URL}/api/admin/attendance/roster/mark",
            json={"marks": [{"user_id": uid, "action": "absent"}]},
            headers=sh,
        )
        # Now mark IN
        r = api.post(
            f"{BASE_URL}/api/admin/attendance/roster/mark",
            json={"marks": [{"user_id": uid, "action": "in"}]},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        res = r.json()["results"][0]
        assert res["ok"] is True and res["action"] == "in", res

        # Absent should be gone; today should show only the IN record
        live_token = _otp_login(api, company_with_employees["live_email"], "email")
        me_hdr = {"Authorization": f"Bearer {live_token}"}
        today = api.get(f"{BASE_URL}/api/attendance/today", headers=me_hdr).json()
        recs = today.get("records") or []
        absents = [x for x in recs if x.get("kind") == "absent"]
        ins = [x for x in recs if x.get("kind") == "in"]
        assert not absents, f"absent should be retracted, still present: {absents}"
        assert ins, f"expected at least one IN record, got {recs}"


# ===========================================================================
# 5. Punch endpoint: latitude / longitude REQUIRED
# ===========================================================================
class TestPunchRequiresLatLng:
    def test_missing_latlng_returns_422(self, api, emp_token):
        me_hdr = {"Authorization": f"Bearer {emp_token}",
                  "Content-Type": "application/json"}
        r = api.post(
            f"{BASE_URL}/api/attendance/punch",
            json={"kind": "in", "biometric_method": "fingerprint"},
            headers=me_hdr,
        )
        assert r.status_code == 422, f"{r.status_code} {r.text[:300]}"
        body = r.json()
        detail = body.get("detail") or []
        flat = str(detail).lower()
        assert "latitude" in flat and "longitude" in flat, detail


# ===========================================================================
# 6. Company setting: auto_punch_enabled toggle
# ===========================================================================
class TestCompanyAutoPunchToggle:
    def test_patch_company_disables_and_reflects_in_details(
        self, api, sh, company_with_employees,
    ):
        cid = company_with_employees["company_id"]
        r = api.patch(
            f"{BASE_URL}/api/companies/{cid}",
            json={"auto_punch_enabled": False},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("auto_punch_enabled") is False

        d = api.get(f"{BASE_URL}/api/companies/{cid}/details", headers=sh)
        assert d.status_code == 200, d.text
        body = d.json()
        # details may nest the company block or return flat
        comp = body.get("company") or body
        assert comp.get("auto_punch_enabled") is False, body


# ===========================================================================
# 7. Effective auto-punch resolution on /auth/me
# ===========================================================================
class TestEffectiveAutoPunch:
    def test_company_false_makes_employee_false(
        self, api, sh, company_with_employees,
    ):
        cid = company_with_employees["company_id"]
        # Ensure company=false (previous test set it, re-assert)
        api.patch(f"{BASE_URL}/api/companies/{cid}",
                  json={"auto_punch_enabled": False}, headers=sh)
        emp_token = _otp_login(api, company_with_employees["emp_email"], "email")
        me = api.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {emp_token}"}).json()
        u = me.get("user") or {}
        assert u.get("effective_auto_punch") is False, u

    def test_company_true_makes_employee_true(
        self, api, sh, company_with_employees,
    ):
        cid = company_with_employees["company_id"]
        r = api.patch(f"{BASE_URL}/api/companies/{cid}",
                      json={"auto_punch_enabled": True}, headers=sh)
        assert r.status_code == 200
        emp_token = _otp_login(api, company_with_employees["emp_email"], "email")
        me = api.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {emp_token}"}).json()
        u = me.get("user") or {}
        # Ensure employee has NO override (should inherit True)
        assert u.get("effective_auto_punch") is True, u

    def test_per_employee_override_false_beats_company_true(
        self, api, sh, company_with_employees,
    ):
        cid = company_with_employees["company_id"]
        # Ensure company=true
        api.patch(f"{BASE_URL}/api/companies/{cid}",
                  json={"auto_punch_enabled": True}, headers=sh)
        # Per-employee override → False
        uid = company_with_employees["emp_uid"]
        r = api.patch(
            f"{BASE_URL}/api/admin/user-role",
            json={"user_id": uid, "auto_punch_enabled": False},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        emp_token = _otp_login(api, company_with_employees["emp_email"], "email")
        me = api.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {emp_token}"}).json()
        u = me.get("user") or {}
        assert u.get("effective_auto_punch") is False, u

    def test_clearing_override_via_null_reinherits_company(
        self, api, sh, company_with_employees,
    ):
        cid = company_with_employees["company_id"]
        # Company = true
        api.patch(f"{BASE_URL}/api/companies/{cid}",
                  json={"auto_punch_enabled": True}, headers=sh)
        uid = company_with_employees["emp_uid"]
        # Explicit null in body → clears override
        r = api.patch(
            f"{BASE_URL}/api/admin/user-role",
            json={"user_id": uid, "auto_punch_enabled": None},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        emp_token = _otp_login(api, company_with_employees["emp_email"], "email")
        me = api.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {emp_token}"}).json()
        u = me.get("user") or {}
        assert u.get("effective_auto_punch") is True, u

    def test_live_in_forces_false_regardless(
        self, api, sh, company_with_employees,
    ):
        cid = company_with_employees["company_id"]
        # Company = true (allow auto-punch broadly)
        api.patch(f"{BASE_URL}/api/companies/{cid}",
                  json={"auto_punch_enabled": True}, headers=sh)
        uid = company_with_employees["live_uid"]
        # Make sure this user has NO explicit override AND set live-in=true
        r = api.patch(
            f"{BASE_URL}/api/admin/user-role",
            json={"user_id": uid, "is_live_in": True,
                  "auto_punch_enabled": None},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        live_token = _otp_login(api, company_with_employees["live_email"], "email")
        me = api.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {live_token}"}).json()
        u = me.get("user") or {}
        assert u.get("is_live_in") is True, u
        assert u.get("effective_auto_punch") is False, u
