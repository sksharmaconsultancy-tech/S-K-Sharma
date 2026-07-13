"""
Iteration 52 — Textile policy + Back-date manual punch editor + Employee grouping.

Coverage:
  * Textile presets & policy PATCH (validation for policy_variant / rounding).
  * /attendance/textile/compute-day for Policy 1 and Policy 2.
  * Per-employee textile flags via PATCH /admin/user-role + echo in /admin/employees.
  * Manual punch CREATE / EDIT / DELETE + audit trail + history.
  * 90-day lookback guard for company_admin; super_admin unrestricted.
  * Cross-company scoping (403 for admin outside owning company).
  * Employee grouping — employee_type title-casing, is_onroll persistence,
    filter chips (?employee_type=... / ?is_onroll=... / ?employee_type=unset).
  * /admin/employee-types distinct list sorted by count desc.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

# ---------------------------------------------------------------------------
# Base URL
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
# Helpers
# ---------------------------------------------------------------------------
def _otp_login(api: requests.Session, identifier: str, channel: str = "email") -> str:
    r = api.post(f"{BASE_URL}/api/auth/otp/request",
                 json={"identifier": identifier, "channel": channel})
    assert r.status_code == 200, r.text
    code = r.json().get("code") or r.json().get("dev_code")
    assert code, f"no dev OTP: {r.json()}"
    r = api.post(f"{BASE_URL}/api/auth/otp/verify",
                 json={"identifier": identifier, "channel": channel, "code": code})
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


def _rand() -> str:
    return uuid.uuid4().hex[:6]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    return s


@pytest.fixture(scope="session")
def super_token(api):
    return _otp_login(api, SUPER_ADMIN_EMAIL, "email")


@pytest.fixture(scope="session")
def sh(super_token):
    return _hdr(super_token)


def _create_company(api, sh, *, textile: bool = True) -> dict:
    suf = _rand()
    payload = {
        "name": f"TEST_Iter52_{'Tex' if textile else 'Oth'}_{suf}",
        "address": "QA Iter52",
        "office_lat": 12.9716,
        "office_lng": 77.5946,
        "geofence_radius_m": 100,
        "compliance_enabled": True,
        "admin_phone": f"+9195{int(time.time()) % 10000000:07d}",
        "admin_email": f"iter52_admin_{suf}@example.com",
        "admin_name": f"QA Iter52 Admin {suf}",
    }
    if textile:
        payload["business_category"] = "industry"
        payload["business_subcategory"] = "Textile"
    r = api.post(f"{BASE_URL}/api/companies", json=payload, headers=sh)
    assert r.status_code == 200, r.text
    body = r.json()
    return {
        "company_id": body["company_id"],
        "company_code": body["company_code"],
        "admin_email": payload["admin_email"],
    }


def _signup_and_approve(api, sh, company_code: str, tag: str = "emp") -> dict:
    rnd = _rand()
    email = f"iter52_{tag}_{rnd}@example.com"
    phone = f"+9194{int(rnd, 16) % 10000000:07d}"
    r = api.post(
        f"{BASE_URL}/api/auth/employee-signup",
        json={
            "company_code": company_code,
            "name": f"QA {tag} {rnd}",
            "phone": phone,
            "pin": "294857",
            "email": email,
            "position": "Tester",
        },
    )
    assert r.status_code in (200, 201), r.text
    uid = r.json()["user_id"]
    ar = api.patch(
        f"{BASE_URL}/api/admin/approve-employee",
        json={"user_id": uid, "action": "approve"},
        headers=sh,
    )
    assert ar.status_code == 200, ar.text
    return {"user_id": uid, "email": email}


# ---------------------------------------------------------------------------
# Session-scoped throwaway textile company + 2 employees
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def textile_env(api, sh):
    company = _create_company(api, sh, textile=True)
    emp_a = _signup_and_approve(api, sh, company["company_code"], "empA")
    emp_b = _signup_and_approve(api, sh, company["company_code"], "empB")
    yield {**company, "emp_a": emp_a, "emp_b": emp_b}
    try:
        api.delete(f"{BASE_URL}/api/companies/{company['company_id']}", headers=sh)
    except Exception:
        pass


@pytest.fixture(scope="session")
def other_env(api, sh):
    """Second (non-related) company used for cross-company scoping tests."""
    company = _create_company(api, sh, textile=False)
    emp = _signup_and_approve(api, sh, company["company_code"], "otherEmp")
    yield {**company, "emp": emp}
    try:
        api.delete(f"{BASE_URL}/api/companies/{company['company_id']}", headers=sh)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Feature 1: Textile presets & PATCH policy validation
# ---------------------------------------------------------------------------
class TestTextilePresets:
    def test_presets_include_textile(self, api, sh):
        r = api.get(f"{BASE_URL}/api/attendance/policy/presets", headers=sh)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "presets" in body
        # Find a preset whose policy has 5 textile shifts + policy_variant.
        textile_match = None
        for p in body["presets"]:
            pol = p.get("policy") or {}
            if pol.get("policy_variant") == "policy_1" and len(pol.get("shifts") or []) == 5:
                textile_match = p
                break
        assert textile_match is not None, (
            "No preset advertises 5 textile shifts + policy_variant='policy_1'. "
            f"presets={[p.get('business_category') for p in body['presets']]}"
        )
        pol = textile_match["policy"]
        assert pol["policy_variant"] == "policy_1"
        assert pol["duty_hours_rounding_minutes"] == 15
        assert len(pol["shifts"]) == 5


class TestPolicyPatchValidation:
    def test_patch_policy_variant_policy_2(self, api, sh, textile_env):
        cid = textile_env["company_id"]
        # Fetch current preset first so we send valid shifts.
        cur = api.get(f"{BASE_URL}/api/attendance/policy?company_id={cid}", headers=sh)
        assert cur.status_code == 200, cur.text
        policy = cur.json()["policy"]
        # Replace with textile-like shifts (5 shifts) + policy_2 + rounding 15
        policy["shifts"] = [
            {"name": "Day 7-7",   "start": "07:00", "end": "19:00"},
            {"name": "Day 8-8",   "start": "08:00", "end": "20:00"},
            {"name": "Night 7-7", "start": "19:00", "end": "07:00"},
            {"name": "Night 8-8", "start": "20:00", "end": "08:00"},
            {"name": "General 9-5", "start": "09:00", "end": "17:00"},
        ]
        policy["policy_variant"] = "policy_2"
        policy["duty_hours_rounding_minutes"] = 15
        policy["standard_working_hours"] = 8
        policy["full_day_hours"] = 8
        policy["week_off_full_day_payment_default"] = True
        policy["weekly_off_days"] = [6]  # Sunday
        r = api.patch(f"{BASE_URL}/api/attendance/policy?company_id={cid}",
                      json={"policy": policy}, headers=sh)
        assert r.status_code == 200, r.text
        saved = r.json()["policy"]
        assert saved["policy_variant"] == "policy_2"
        assert saved["duty_hours_rounding_minutes"] == 15
        assert saved["standard_working_hours"] == 8
        assert saved["week_off_full_day_payment_default"] is True
        # GET verify
        got = api.get(f"{BASE_URL}/api/attendance/policy?company_id={cid}",
                      headers=sh).json()["policy"]
        assert got["policy_variant"] == "policy_2"
        assert got["duty_hours_rounding_minutes"] == 15

    def test_invalid_policy_variant_returns_400(self, api, sh, textile_env):
        cid = textile_env["company_id"]
        cur = api.get(f"{BASE_URL}/api/attendance/policy?company_id={cid}",
                      headers=sh).json()["policy"]
        cur["policy_variant"] = "policy_bogus"
        r = api.patch(f"{BASE_URL}/api/attendance/policy?company_id={cid}",
                      json={"policy": cur}, headers=sh)
        assert r.status_code == 400, r.text
        assert "policy_variant" in r.text

    def test_invalid_rounding_returns_400(self, api, sh, textile_env):
        cid = textile_env["company_id"]
        cur = api.get(f"{BASE_URL}/api/attendance/policy?company_id={cid}",
                      headers=sh).json()["policy"]
        cur["duty_hours_rounding_minutes"] = 7  # not in 0,5,10,15,30
        r = api.patch(f"{BASE_URL}/api/attendance/policy?company_id={cid}",
                      json={"policy": cur}, headers=sh)
        assert r.status_code == 400, r.text
        assert "duty_hours_rounding_minutes" in r.text


# ---------------------------------------------------------------------------
# Feature 2: Compute-day
# ---------------------------------------------------------------------------
def _set_policy_v1(api, sh, cid):
    """Set policy_1, standard_working_hours=8, weekly_off=[6] (Sunday)."""
    cur = api.get(f"{BASE_URL}/api/attendance/policy?company_id={cid}",
                  headers=sh).json()["policy"]
    cur["shifts"] = [
        {"name": "Day 7-7", "start": "07:00", "end": "19:00"},
        {"name": "Day 8-8", "start": "08:00", "end": "20:00"},
        {"name": "Night 7-7", "start": "19:00", "end": "07:00"},
        {"name": "Night 8-8", "start": "20:00", "end": "08:00"},
        {"name": "General 9-5", "start": "09:00", "end": "17:00"},
    ]
    cur["policy_variant"] = "policy_1"
    cur["duty_hours_rounding_minutes"] = 15
    cur["standard_working_hours"] = 8
    cur["full_day_hours"] = 8
    cur["weekly_off_days"] = [6]
    r = api.patch(f"{BASE_URL}/api/attendance/policy?company_id={cid}",
                  json={"policy": cur}, headers=sh)
    assert r.status_code == 200, r.text


def _set_policy_v2(api, sh, cid):
    cur = api.get(f"{BASE_URL}/api/attendance/policy?company_id={cid}",
                  headers=sh).json()["policy"]
    cur["shifts"] = [
        {"name": "Day 7-7", "start": "07:00", "end": "19:00"},
        {"name": "Day 8-8", "start": "08:00", "end": "20:00"},
        {"name": "Night 7-7", "start": "19:00", "end": "07:00"},
        {"name": "Night 8-8", "start": "20:00", "end": "08:00"},
        {"name": "General 9-5", "start": "09:00", "end": "17:00"},
    ]
    cur["policy_variant"] = "policy_2"
    cur["duty_hours_rounding_minutes"] = 15
    cur["standard_working_hours"] = 8
    cur["full_day_hours"] = 8
    cur["weekly_off_days"] = [6]
    r = api.patch(f"{BASE_URL}/api/attendance/policy?company_id={cid}",
                  json={"policy": cur}, headers=sh)
    assert r.status_code == 200, r.text


def _last_weekday(target_weekday: int) -> datetime:
    """Return midday UTC on the most recent past date with the given weekday."""
    now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    delta = (now.weekday() - target_weekday) % 7
    if delta == 0:
        delta = 7  # use previous week to be safe from clock skew
    return now - timedelta(days=delta)


class TestTextileComputeDay:
    def test_policy_1_normal_day_12h(self, api, sh, textile_env):
        cid = textile_env["company_id"]
        _set_policy_v1(api, sh, cid)
        uid = textile_env["emp_a"]["user_id"]
        # Ensure OT applicable (default true, but explicit)
        r = api.patch(
            f"{BASE_URL}/api/admin/user-role",
            json={"user_id": uid, "ot_applicable": True,
                  "week_off_full_day": False,
                  "week_off_govt_holiday_enabled": False},
            headers=sh,
        )
        assert r.status_code == 200, r.text

        # Pick a Monday (weekday=0) in the past, well within lookback.
        d = _last_weekday(0)  # Monday
        date_str = d.strftime("%Y-%m-%d")
        # Punch IN at 08:00, OUT at 20:00 → 12h
        in_at = d.replace(hour=8, minute=0).strftime("%Y-%m-%dT%H:%M")
        out_at = d.replace(hour=20, minute=0).strftime("%Y-%m-%dT%H:%M")

        # Clear any existing punches for that day/user (via manual delete via history)
        hist = api.get(
            f"{BASE_URL}/api/admin/attendance/history"
            f"?user_id={uid}&date_from={date_str}&date_to={date_str}",
            headers=sh,
        ).json()
        for rec in hist.get("records") or []:
            api.delete(
                f"{BASE_URL}/api/admin/attendance/{rec['record_id']}?reason=cleanup",
                headers=sh,
            )

        for kind, at in (("in", in_at), ("out", out_at)):
            r = api.post(
                f"{BASE_URL}/api/admin/attendance/manual-punch",
                json={"user_id": uid, "kind": kind, "at": at, "reason": "seed"},
                headers=sh,
            )
            assert r.status_code == 200, r.text

        r = api.get(
            f"{BASE_URL}/api/attendance/textile/compute-day?user_id={uid}&date={date_str}",
            headers=sh,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["policy_variant"] == "policy_1"
        assert body["duty_hours"] == 12.0, body
        assert body["present_days"] == 1.0, body
        assert body["ot_hours"] == 4.0, body

    def test_policy_2_weekly_off_all_ot(self, api, sh, textile_env):
        cid = textile_env["company_id"]
        _set_policy_v2(api, sh, cid)
        uid = textile_env["emp_b"]["user_id"]
        # Flag as week_off_govt_holiday_enabled=true
        r = api.patch(
            f"{BASE_URL}/api/admin/user-role",
            json={"user_id": uid, "week_off_govt_holiday_enabled": True,
                  "ot_applicable": True, "week_off_full_day": False},
            headers=sh,
        )
        assert r.status_code == 200, r.text

        # Pick a Sunday (weekday=6) in the past
        d = _last_weekday(6)
        date_str = d.strftime("%Y-%m-%d")
        in_at = d.replace(hour=9, minute=0).strftime("%Y-%m-%dT%H:%M")
        out_at = d.replace(hour=17, minute=0).strftime("%Y-%m-%dT%H:%M")

        # Clean existing rows
        hist = api.get(
            f"{BASE_URL}/api/admin/attendance/history"
            f"?user_id={uid}&date_from={date_str}&date_to={date_str}",
            headers=sh,
        ).json()
        for rec in hist.get("records") or []:
            api.delete(
                f"{BASE_URL}/api/admin/attendance/{rec['record_id']}?reason=cleanup",
                headers=sh,
            )
        for kind, at in (("in", in_at), ("out", out_at)):
            r = api.post(
                f"{BASE_URL}/api/admin/attendance/manual-punch",
                json={"user_id": uid, "kind": kind, "at": at, "reason": "seed"},
                headers=sh,
            )
            assert r.status_code == 200, r.text

        r = api.get(
            f"{BASE_URL}/api/attendance/textile/compute-day?user_id={uid}&date={date_str}",
            headers=sh,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["policy_variant"] == "policy_2"
        assert body["is_weekly_off"] is True, body
        assert body["present_days"] == 0.0, body
        assert body["ot_hours"] == body["duty_hours"], body
        assert body["duty_hours"] > 0


# ---------------------------------------------------------------------------
# Feature 3: Per-employee textile flags via /admin/user-role
# ---------------------------------------------------------------------------
class TestPerEmployeeTextileFlags:
    def test_flags_persist_and_echo(self, api, sh, textile_env):
        cid = textile_env["company_id"]
        uid = textile_env["emp_a"]["user_id"]
        r = api.patch(
            f"{BASE_URL}/api/admin/user-role",
            json={
                "user_id": uid,
                "shift_preset_name": "Night 7-7",
                "ot_applicable": False,
                "week_off_full_day": True,
                "week_off_govt_holiday_enabled": True,
            },
            headers=sh,
        )
        assert r.status_code == 200, r.text

        r = api.get(f"{BASE_URL}/api/admin/employees?company_id={cid}", headers=sh)
        assert r.status_code == 200, r.text
        match = next((e for e in r.json()["employees"]
                      if e.get("user_id") == uid), None)
        assert match is not None, r.json()
        assert match.get("shift_preset_name") == "Night 7-7"
        assert match.get("ot_applicable") is False
        assert match.get("week_off_full_day") is True
        assert match.get("week_off_govt_holiday_enabled") is True


# ---------------------------------------------------------------------------
# Feature 4: Manual punch CREATE + audit
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def seeded_punch(api, sh, textile_env):
    """Create one manual punch and share across tests."""
    uid = textile_env["emp_a"]["user_id"]
    at = "2026-06-01T09:00"
    r = api.post(
        f"{BASE_URL}/api/admin/attendance/manual-punch",
        json={"user_id": uid, "kind": "in", "at": at, "reason": "iter52-seed"},
        headers=sh,
    )
    assert r.status_code == 200, r.text
    rec = r.json()["record"]
    return {"record": rec, "user_id": uid}


class TestManualPunchCreate:
    def test_create_manual_punch_basic(self, seeded_punch):
        rec = seeded_punch["record"]
        assert rec["source"] == "manual_admin"
        assert rec["status"] == "approved"
        assert rec["kind"] == "in"
        assert rec["manual_reason"] == "iter52-seed"
        assert rec["date"] == "2026-06-01"

    def test_missing_reason_returns_400(self, api, sh, textile_env):
        uid = textile_env["emp_a"]["user_id"]
        r = api.post(
            f"{BASE_URL}/api/admin/attendance/manual-punch",
            json={"user_id": uid, "kind": "in", "at": "2026-06-02T09:00", "reason": ""},
            headers=sh,
        )
        assert r.status_code == 400, r.text
        assert "reason" in r.text.lower()

    def test_company_admin_cannot_add_older_than_90_days(self, api, textile_env):
        """company_admin login → try to add punch 100 days ago → 400."""
        # Company admin login (temp PIN flow doesn't apply — the create-company
        # helper set admin_email; we can OTP-login as that admin).
        admin_email = textile_env["admin_email"]
        admin_token = _otp_login(requests.Session(), admin_email, "email")
        ah = _hdr(admin_token)
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)) \
            .strftime("%Y-%m-%dT09:00")
        uid = textile_env["emp_a"]["user_id"]
        r = requests.post(
            f"{BASE_URL}/api/admin/attendance/manual-punch",
            json={"user_id": uid, "kind": "in", "at": old_date, "reason": "old"},
            headers=ah,
        )
        assert r.status_code == 400, r.text
        assert "90 days" in r.text.lower() or "last 90" in r.text.lower()


# ---------------------------------------------------------------------------
# Feature 5: Manual punch EDIT
# ---------------------------------------------------------------------------
class TestManualPunchEdit:
    def test_edit_preserves_original_at_and_records_editor(
        self, api, sh, seeded_punch,
    ):
        rid = seeded_punch["record"]["record_id"]
        r = api.patch(
            f"{BASE_URL}/api/admin/attendance/{rid}",
            json={"at": "2026-06-01T10:00", "reason": "correction"},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        rec = r.json()["record"]
        assert rec.get("original_at") is not None
        assert rec.get("edited_by")
        assert rec.get("edited_at")
        assert rec.get("edit_reason") == "correction"
        assert rec.get("at", "").startswith("2026-06-01T10:00")

    def test_edit_missing_reason_returns_400(self, api, sh, seeded_punch):
        rid = seeded_punch["record"]["record_id"]
        r = api.patch(
            f"{BASE_URL}/api/admin/attendance/{rid}",
            json={"at": "2026-06-01T11:00", "reason": "   "},
            headers=sh,
        )
        assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# Feature 6: Manual punch DELETE + audit trail chronology
# ---------------------------------------------------------------------------
class TestManualPunchDeleteAndAudit:
    def test_delete_then_audit_shows_all_three_actions(
        self, api, sh, seeded_punch,
    ):
        rid = seeded_punch["record"]["record_id"]
        r = api.delete(
            f"{BASE_URL}/api/admin/attendance/{rid}?reason=iter52-delete",
            headers=sh,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("deleted_record_id") == rid

        # Audit trail should contain create + edit + delete in order.
        r = api.get(f"{BASE_URL}/api/admin/attendance/{rid}/audit", headers=sh)
        assert r.status_code == 200, r.text
        rows = r.json().get("audit") or []
        actions = [row.get("action") for row in rows]
        assert "create" in actions
        assert "edit" in actions
        assert "delete" in actions
        # last action should be delete
        assert actions[-1] == "delete", actions
        # chronological order — each row's at must be non-decreasing
        ats = [row.get("at") or "" for row in rows]
        assert ats == sorted(ats), ats

        # Delete audit row should have after=None, before=old record
        delete_rows = [row for row in rows if row.get("action") == "delete"]
        assert delete_rows
        assert delete_rows[0].get("after") in (None, {}), delete_rows[0]
        assert delete_rows[0].get("before"), delete_rows[0]


# ---------------------------------------------------------------------------
# Feature 7: Attendance history list
# ---------------------------------------------------------------------------
class TestAttendanceHistory:
    def test_history_filters_by_user_and_date(self, api, sh, textile_env):
        # Seed a couple of punches on a known date
        uid = textile_env["emp_a"]["user_id"]
        at_in = "2026-05-01T09:00"
        at_out = "2026-05-01T18:00"
        for kind, at in (("in", at_in), ("out", at_out)):
            r = api.post(
                f"{BASE_URL}/api/admin/attendance/manual-punch",
                json={"user_id": uid, "kind": kind, "at": at, "reason": "history-seed"},
                headers=sh,
            )
            assert r.status_code == 200, r.text
        r = api.get(
            f"{BASE_URL}/api/admin/attendance/history"
            f"?user_id={uid}&date_from=2026-05-01&date_to=2026-05-01",
            headers=sh,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        recs = body.get("records") or body.get("history") or []
        assert isinstance(recs, list) and len(recs) >= 2, body
        assert all(r.get("user_id") == uid for r in recs)
        assert all(r.get("date") == "2026-05-01" for r in recs)


# ---------------------------------------------------------------------------
# Feature 8: Cross-company scoping (403)
# ---------------------------------------------------------------------------
class TestCrossCompanyScoping:
    def test_company_admin_cannot_edit_other_company_punch(
        self, api, sh, textile_env, other_env,
    ):
        # Create a punch on textile_env's employee (via super admin).
        tex_uid = textile_env["emp_a"]["user_id"]
        r = api.post(
            f"{BASE_URL}/api/admin/attendance/manual-punch",
            json={"user_id": tex_uid, "kind": "in",
                  "at": "2026-06-05T09:00", "reason": "cross-scope-seed"},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        rid = r.json()["record"]["record_id"]

        # Log in as other_env's company_admin
        other_admin_email = other_env["admin_email"]
        other_tok = _otp_login(requests.Session(), other_admin_email, "email")
        oh = _hdr(other_tok)

        # PATCH → 403
        r = requests.patch(
            f"{BASE_URL}/api/admin/attendance/{rid}",
            json={"at": "2026-06-05T10:00", "reason": "hack"},
            headers=oh,
        )
        assert r.status_code == 403, r.text

        # DELETE → 403
        r = requests.delete(
            f"{BASE_URL}/api/admin/attendance/{rid}?reason=hack",
            headers=oh,
        )
        assert r.status_code == 403, r.text

        # CREATE punch on textile_env's employee from other admin → 403
        r = requests.post(
            f"{BASE_URL}/api/admin/attendance/manual-punch",
            json={"user_id": tex_uid, "kind": "in",
                  "at": "2026-06-06T09:00", "reason": "hack"},
            headers=oh,
        )
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Feature 9: Employee Type + On-roll filtering
# ---------------------------------------------------------------------------
class TestEmployeeGrouping:
    def test_employee_type_title_cased(self, api, sh, textile_env):
        uid = textile_env["emp_a"]["user_id"]
        r = api.patch(
            f"{BASE_URL}/api/admin/user-role",
            json={"user_id": uid, "employee_type": "staff"},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        emps = api.get(
            f"{BASE_URL}/api/admin/employees?company_id={textile_env['company_id']}",
            headers=sh,
        ).json()["employees"]
        me = next(e for e in emps if e.get("user_id") == uid)
        assert me.get("employee_type") == "Staff", me

    def test_is_onroll_false_persists(self, api, sh, textile_env):
        uid = textile_env["emp_b"]["user_id"]
        r = api.patch(
            f"{BASE_URL}/api/admin/user-role",
            json={"user_id": uid, "is_onroll": False, "employee_type": "worker"},
            headers=sh,
        )
        assert r.status_code == 200, r.text
        emps = api.get(
            f"{BASE_URL}/api/admin/employees?company_id={textile_env['company_id']}",
            headers=sh,
        ).json()["employees"]
        me = next(e for e in emps if e.get("user_id") == uid)
        assert me.get("is_onroll") is False
        assert me.get("employee_type") == "Worker"

    def test_list_filter_by_employee_type_and_onroll(self, api, sh, textile_env):
        cid = textile_env["company_id"]
        # emp_a: Staff, on-roll True (default); emp_b: Worker, on-roll False
        r = api.get(
            f"{BASE_URL}/api/admin/employees?company_id={cid}"
            f"&employee_type=Staff&is_onroll=true",
            headers=sh,
        )
        assert r.status_code == 200, r.text
        uids = [e["user_id"] for e in r.json()["employees"]]
        assert textile_env["emp_a"]["user_id"] in uids
        assert textile_env["emp_b"]["user_id"] not in uids

        # is_onroll=false → emp_b
        r = api.get(
            f"{BASE_URL}/api/admin/employees?company_id={cid}&is_onroll=false",
            headers=sh,
        )
        uids = [e["user_id"] for e in r.json()["employees"]]
        assert textile_env["emp_b"]["user_id"] in uids

    def test_employee_type_unset_filter(self, api, sh):
        """Create a fresh employee with NO type and confirm ?employee_type=unset returns them."""
        # Piggy-back on textile_env would leave state — create a mini env.
        company = _create_company(api, sh, textile=False)
        try:
            fresh = _signup_and_approve(api, sh, company["company_code"], "unsetEmp")
            r = api.get(
                f"{BASE_URL}/api/admin/employees?company_id={company['company_id']}"
                f"&employee_type=unset",
                headers=sh,
            )
            assert r.status_code == 200, r.text
            uids = [e["user_id"] for e in r.json()["employees"]]
            assert fresh["user_id"] in uids
        finally:
            try:
                api.delete(f"{BASE_URL}/api/companies/{company['company_id']}",
                           headers=sh)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Feature 10: /admin/employee-types distinct list
# ---------------------------------------------------------------------------
class TestEmployeeTypesDistinct:
    def test_distinct_types_sorted_by_count(self, api, sh, textile_env):
        """After previous test bumped emp_a→Staff and emp_b→Worker, the
        distinct endpoint (scoped to company) should return both."""
        # company_admin token so scoping applies
        admin_tok = _otp_login(requests.Session(),
                               textile_env["admin_email"], "email")
        ah = _hdr(admin_tok)
        r = requests.get(f"{BASE_URL}/api/admin/employee-types", headers=ah)
        assert r.status_code == 200, r.text
        body = r.json()
        types = body.get("types") or []
        names = [t.get("name") for t in types]
        assert "Staff" in names, body
        assert "Worker" in names, body
        # Sorted by count desc — check counts are non-increasing.
        counts = [t.get("count", 0) for t in types]
        assert counts == sorted(counts, reverse=True), counts
        # Each row has a positive int count
        for t in types:
            assert isinstance(t.get("count"), int) and t["count"] >= 1


# ---------------------------------------------------------------------------
# Basic health smoke — ensure BASE_URL responds before deep tests run.
# ---------------------------------------------------------------------------
class TestSanity:
    def test_backend_reachable(self, api):
        r = api.get(f"{BASE_URL}/api/", timeout=10)
        # Root may 200 or 404 depending on router; we just want a response.
        assert r.status_code in (200, 404), r.status_code
