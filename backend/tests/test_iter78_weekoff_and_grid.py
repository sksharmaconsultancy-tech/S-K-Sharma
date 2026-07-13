"""Iter 78 - Backend tests for Iter 77d + 77e changes.

Covers:
  * NEW firm-level ``attendance_policy.week_off_min_working_hours`` (float, 0-16).
    When >0 and employee works >= threshold on their weekly-off day →
    ``present_days=1.0`` and ``full_day_pay_weekoff=True``.
  * NEW per-employee override ``attendance_policy_override.week_off_paid_when_absent``
    (bool). When True and week-off day has NO punches →
    ``present_days=1.0`` and ``full_day_pay_weekoff=True``.
  * Legacy ``week_off_full_day`` fallback still works when the min-hour
    threshold is not met.
  * ``_validate_policy`` accepts ``week_off_min_working_hours`` between 0 and 16.
  * HTTP integration on ``/api/admin/attendance/monthly-grid/{cid}/{month}``:
    - Each cell now returns BOTH ``raw_hours`` and ``hours`` (policy-adjusted)
    - Workday: 12h punches + ot_allowed=False → ``raw_hours=12``, ``hours=8``
    - Week-off day: 10h punches → ``hours=10`` (uncapped, no OT restriction),
      ``present=1.0``, ``weekly_off=True``
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

# ------------------------------------------------------------------
# Import compute_textile_day + _validate_policy for direct unit tests.
# ------------------------------------------------------------------
sys.path.insert(0, "/app/backend")
from server import compute_textile_day, _validate_policy  # noqa: E402

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL (or EXPO_BACKEND_URL) must be set"
API = f"{BASE_URL}/api"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"


# ==================================================================
# PART 1 - Direct unit tests on compute_textile_day (Iter 77d rules)
# ==================================================================

def _mk_punches(pairs):
    out = []
    for in_iso, out_iso in pairs:
        out.append({"kind": "in", "at": in_iso})
        out.append({"kind": "out", "at": out_iso})
    return out


def _p1_policy(weekoff_min=0.0, weekly_off_days=None):
    """Build a minimal policy_1 policy dict for compute_textile_day."""
    return {
        "policy_variant": "policy_1",
        "standard_working_hours": 8.0,
        "half_day_hours": 4.0,
        "weekly_off_days": weekly_off_days if weekly_off_days is not None else [6],
        "week_off_min_working_hours": weekoff_min,
    }


# ------------------------------------------------------------------
# 1a) Weekly-off + min-hours THRESHOLD MET → full-day + paid weekoff
# ------------------------------------------------------------------
def test_p1_weekoff_min_hours_met_full_day():
    # Sunday (weekday=6) - week-off day, employee works 10h
    in1 = "2026-01-04T08:00:00+00:00"   # Sunday
    out1 = "2026-01-04T18:00:00+00:00"  # +10h
    punches = _mk_punches([(in1, out1)])
    policy = _p1_policy(weekoff_min=8.0)
    user = {}  # no legacy flags, no override
    result = compute_textile_day(punches, policy, user, day_weekday=6)
    assert result["duty_minutes"] == 10 * 60, result
    assert result["present_days"] == 1.0, result
    assert result["full_day_pay_weekoff"] is True, result
    assert result["is_weekly_off"] is True
    assert any("full-day attendance" in n for n in result["notes"]), result["notes"]


# ------------------------------------------------------------------
# 1b) Weekly-off + UNDER min-hours + NO legacy flag → NO present
# ------------------------------------------------------------------
def test_p1_weekoff_under_min_no_legacy_no_present():
    # Sunday, 6h worked, threshold 8h, no legacy flag
    in1 = "2026-01-04T08:00:00+00:00"
    out1 = "2026-01-04T14:00:00+00:00"  # 6h
    punches = _mk_punches([(in1, out1)])
    policy = _p1_policy(weekoff_min=8.0)
    user = {"week_off_full_day": False}
    result = compute_textile_day(punches, policy, user, day_weekday=6)
    assert result["duty_minutes"] == 6 * 60, result
    assert result["present_days"] == 0.0, result
    assert result["full_day_pay_weekoff"] is False, result
    assert any("under min" in n for n in result["notes"]), result["notes"]


# ------------------------------------------------------------------
# 1c) Weekly-off + UNDER min-hours + LEGACY flag set → full-day (fallback)
# ------------------------------------------------------------------
def test_p1_weekoff_under_min_legacy_flag_full_day():
    in1 = "2026-01-04T08:00:00+00:00"
    out1 = "2026-01-04T14:00:00+00:00"  # 6h
    punches = _mk_punches([(in1, out1)])
    policy = _p1_policy(weekoff_min=8.0)
    user = {"week_off_full_day": True}  # legacy fallback flag
    result = compute_textile_day(punches, policy, user, day_weekday=6)
    assert result["duty_minutes"] == 6 * 60, result
    assert result["present_days"] == 1.0, result
    assert result["full_day_pay_weekoff"] is True, result
    assert any("legacy full-day flag" in n for n in result["notes"]), result["notes"]


# ------------------------------------------------------------------
# 1d) Weekly-off + NO punches + week_off_paid_when_absent=True → full-day
# ------------------------------------------------------------------
def test_p1_weekoff_paid_when_absent_no_punches():
    punches = []
    policy = _p1_policy(weekoff_min=8.0)
    user = {"attendance_policy_override": {"week_off_paid_when_absent": True}}
    result = compute_textile_day(punches, policy, user, day_weekday=6)
    assert result["duty_minutes"] == 0.0, result
    assert result["present_days"] == 1.0, result
    assert result["full_day_pay_weekoff"] is True, result
    assert any("paid-when-absent" in n for n in result["notes"]), result["notes"]


# ------------------------------------------------------------------
# 1e) Weekly-off + NO punches + NO flag → present=0 (unchanged behaviour)
# ------------------------------------------------------------------
def test_p1_weekoff_no_punches_no_flag_no_present():
    punches = []
    policy = _p1_policy(weekoff_min=8.0)
    user = {}
    result = compute_textile_day(punches, policy, user, day_weekday=6)
    assert result["duty_minutes"] == 0.0, result
    assert result["present_days"] == 0.0, result
    assert result["full_day_pay_weekoff"] is False, result


# ------------------------------------------------------------------
# 1f) week_off_min_working_hours=0 (default) still triggers legacy path
# ------------------------------------------------------------------
def test_p1_weekoff_min_zero_any_positive_duty_grants_fullday():
    in1 = "2026-01-04T08:00:00+00:00"
    out1 = "2026-01-04T10:00:00+00:00"  # 2h (any positive duty)
    punches = _mk_punches([(in1, out1)])
    policy = _p1_policy(weekoff_min=0.0)
    user = {}
    result = compute_textile_day(punches, policy, user, day_weekday=6)
    # With threshold=0, meets_min defaults to True → full-day
    assert result["present_days"] == 1.0, result
    assert result["full_day_pay_weekoff"] is True, result


# ==================================================================
# PART 2 - _validate_policy accepts week_off_min_working_hours in [0,16]
# ==================================================================

def _base_valid_policy(week_off_min):
    """Minimum policy blob accepted by _validate_policy for testing."""
    return {
        "shifts": [
            {"name": "General", "start": "09:00", "end": "18:00",
             "grace_late_minutes": 10, "grace_early_out_minutes": 10,
             "half_day_hours": 4.0, "full_day_hours": 8.0,
             "break_hours": 1.0, "is_default": True},
        ],
        "weekly_off_days": [6],
        "grace_minutes_late": 10,
        "half_day_hours": 4.0,
        "full_day_hours": 8.0,
        "break_hours": 1.0,
        "overtime_threshold_hours": 8.0,
        "overtime_multiplier": 1.5,
        "policy_variant": "policy_1",
        "duty_hours_rounding_minutes": 0,
        "standard_working_hours": 8.0,
        "week_off_min_working_hours": week_off_min,
    }


def test_validate_policy_accepts_week_off_min_zero():
    out = _validate_policy(_base_valid_policy(0.0))
    assert out["week_off_min_working_hours"] == 0.0


def test_validate_policy_accepts_week_off_min_eight():
    out = _validate_policy(_base_valid_policy(8.0))
    assert out["week_off_min_working_hours"] == 8.0


def test_validate_policy_accepts_week_off_min_sixteen():
    out = _validate_policy(_base_valid_policy(16.0))
    assert out["week_off_min_working_hours"] == 16.0


def test_validate_policy_rejects_week_off_min_above_16():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _validate_policy(_base_valid_policy(20.0))


def test_validate_policy_rejects_week_off_min_negative():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _validate_policy(_base_valid_policy(-1.0))


# ==================================================================
# PART 3 - HTTP integration test on /admin/attendance/monthly-grid
# ==================================================================

@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def super_token(http):
    r = http.post(
        f"{API}/auth/otp/request",
        json={"identifier": SUPER_EMAIL, "channel": "email"},
        timeout=15,
    )
    assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text}"
    code = r.json().get("dev_code")
    assert code, f"no dev_code in OTP response: {r.json()}"
    r2 = http.post(
        f"{API}/auth/otp/verify",
        json={"identifier": SUPER_EMAIL, "channel": "email", "code": code},
        timeout=15,
    )
    assert r2.status_code == 200, f"otp/verify failed: {r2.status_code} {r2.text}"
    tok = r2.json().get("session_token") or r2.json().get("token")
    assert tok, f"no token in verify response: {r2.json()}"
    return tok


@pytest.fixture(scope="module")
def auth_hdr(super_token):
    return {"Authorization": f"Bearer {super_token}"}


@pytest.fixture(scope="module")
def iter78_env(http, auth_hdr):
    """Create a Policy 1 firm with week_off_min_working_hours=8 + one employee
    with attendance_policy_override.ot_allowed=False. Returns (cid, uid,
    workday_iso, weekoff_iso)."""
    unique = uuid.uuid4().hex[:6]
    payload = {
        "name": f"Iter78-WeekOff-{unique}",
        "code": f"IT78{unique[:4].upper()}",
        "business_category": "industry",
        "business_subcategory": "Textile",
        "policy_variant": "policy_1",
        "office_lat": 28.6139,
        "office_lng": 77.2090,
    }
    r = http.post(f"{API}/companies", json=payload, headers=auth_hdr, timeout=15)
    assert r.status_code in (200, 201), f"create firm failed: {r.status_code} {r.text}"
    data = r.json()
    cid = data.get("company_id") or (data.get("company") or {}).get("company_id")
    assert cid, f"no company_id in response: {data}"

    # GET the current policy (preset supplies shifts) and PATCH with
    # week_off_min_working_hours=8. Ensure Sunday is weekly-off.
    pr = http.get(
        f"{API}/attendance/policy",
        params={"company_id": cid},
        headers=auth_hdr,
        timeout=15,
    )
    assert pr.status_code == 200, pr.text
    pol = (pr.json() or {}).get("policy") or {}
    pol["week_off_min_working_hours"] = 8.0
    pol["weekly_off_days"] = [6]  # Sunday
    pol["policy_variant"] = "policy_1"
    up = http.patch(
        f"{API}/attendance/policy",
        params={"company_id": cid},
        json={"policy": pol},
        headers=auth_hdr,
        timeout=15,
    )
    assert up.status_code == 200, f"patch policy failed: {up.status_code} {up.text}"
    updated = up.json().get("policy") or {}
    assert updated.get("week_off_min_working_hours") == 8.0, updated

    # Create employee
    phone = f"+91982{uuid.uuid4().int % 10_000_000:07d}"
    emp_payload = {
        "name": f"TEST_Iter78_{uuid.uuid4().hex[:6]}",
        "phone": phone,
        "company_id": cid,
        "employee_code": f"T78{uuid.uuid4().hex[:4].upper()}",
        "doj": "2020-01-01",
    }
    er = http.post(f"{API}/admin/employees", json=emp_payload, headers=auth_hdr, timeout=15)
    assert er.status_code in (200, 201), f"create employee failed: {er.status_code} {er.text}"
    uid = er.json().get("user_id") or (er.json().get("employee") or {}).get("user_id")
    assert uid, f"no user_id in response: {er.json()}"

    # Set attendance_policy_override.ot_allowed=False
    ov = http.put(
        f"{API}/admin/employees/{uid}/attendance-policy-override",
        json={"ot_allowed": False},
        headers=auth_hdr,
        timeout=15,
    )
    assert ov.status_code == 200, ov.text
    assert ov.json().get("override", {}).get("ot_allowed") is False

    # Choose a recent workday (Mon-Sat) and its adjacent Sunday for punches.
    # Use *last* Sunday and the Monday before it so we're safely in the past
    # month or current month, both work for monthly-grid.
    today = datetime.now(timezone.utc).date()
    # Find last Sunday
    days_since_sun = (today.weekday() - 6) % 7
    if days_since_sun == 0:
        days_since_sun = 7  # use previous week to avoid "today" edge cases
    last_sun = today - timedelta(days=days_since_sun)
    workday = last_sun - timedelta(days=1)  # Saturday - but Sat may be weekly-off too
    # Actually with weekly_off_days=[6] only Sunday is off. Saturday is fine.
    workday_iso = workday.strftime("%Y-%m-%d")
    weekoff_iso = last_sun.strftime("%Y-%m-%d")

    # Seed 12h of punches on workday (06:00 → 18:00)
    for kind, t in (("in", "06:00:00"), ("out", "18:00:00")):
        rp = http.post(
            f"{API}/admin/attendance/manual-punch",
            json={"user_id": uid, "at": f"{workday_iso}T{t}Z", "kind": kind,
                  "reason": "iter78 workday seed"},
            headers=auth_hdr, timeout=15,
        )
        assert rp.status_code == 200, f"workday punch {kind} failed: {rp.status_code} {rp.text}"

    # Seed 10h of punches on the weekly-off day (08:00 → 18:00)
    for kind, t in (("in", "08:00:00"), ("out", "18:00:00")):
        rp = http.post(
            f"{API}/admin/attendance/manual-punch",
            json={"user_id": uid, "at": f"{weekoff_iso}T{t}Z", "kind": kind,
                  "reason": "iter78 weekoff seed"},
            headers=auth_hdr, timeout=15,
        )
        assert rp.status_code == 200, f"weekoff punch {kind} failed: {rp.status_code} {rp.text}"

    return {
        "cid": cid, "uid": uid,
        "workday": workday_iso, "weekoff": weekoff_iso,
    }


def test_monthly_grid_returns_raw_and_policy_adjusted_hours(http, auth_hdr, iter78_env):
    """Verify cells now contain BOTH ``raw_hours`` and ``hours`` fields, and
    that Policy 1 cap + week-off rules are applied correctly."""
    cid = iter78_env["cid"]
    uid = iter78_env["uid"]
    workday = iter78_env["workday"]
    weekoff = iter78_env["weekoff"]

    # Query the range that spans both days
    r = http.get(
        f"{API}/admin/attendance/monthly-grid/{cid}/2026-01",
        params={"from_date": workday, "to_date": weekoff},
        headers=auth_hdr,
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body.get("employees") or body.get("rows") or []
    row = next((e for e in rows if e.get("user_id") == uid), None)
    assert row is not None, f"employee row missing. rows={[e.get('user_id') for e in rows]}"

    days_cell = row.get("days") or {}
    # Two days spanning same-month → keys are '01','02' style zero-padded DD.
    wday_key = workday[-2:]
    woff_key = weekoff[-2:]

    wcell = days_cell.get(wday_key)
    ocell = days_cell.get(woff_key)
    assert wcell is not None, f"workday cell missing. keys={list(days_cell.keys())}"
    assert ocell is not None, f"weekoff cell missing. keys={list(days_cell.keys())}"

    # ---- Field presence: raw_hours AND hours must be present on each cell ----
    for label, cell in (("workday", wcell), ("weekoff", ocell)):
        assert "raw_hours" in cell, f"{label} cell missing raw_hours: {cell}"
        assert "hours" in cell, f"{label} cell missing hours: {cell}"
        assert "present" in cell, f"{label} cell missing present: {cell}"
        assert "weekly_off" in cell, f"{label} cell missing weekly_off: {cell}"

    # ---- Workday assertions: raw=12, hours=8 (capped, ot_allowed=False) ----
    assert wcell["raw_hours"] == 12.0, wcell
    assert wcell["hours"] == 8.0, wcell
    assert wcell["weekly_off"] is False, wcell
    assert wcell["present"] == 1.0, wcell

    # ---- Weekly-off assertions: hours=10 (uncapped), present=1.0 ----
    assert ocell["weekly_off"] is True, ocell
    assert ocell["raw_hours"] == 10.0, ocell
    # On week-off day, per compute_textile_day, cap is standard_hrs=8 if
    # ot_allowed=False (BEFORE the weekly-off branch). BUT the spec says
    # "hours=10 (uncapped, no OT restriction on week-off)". Check whichever
    # is documented behaviour and REPORT MISMATCH if any.
    assert ocell["hours"] == 10.0, (
        f"week-off day cell should be uncapped at 10h (spec), got {ocell}"
    )
    assert ocell["present"] == 1.0, ocell
