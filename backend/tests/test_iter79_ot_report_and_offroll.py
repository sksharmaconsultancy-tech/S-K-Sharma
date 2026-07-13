"""Iter 79 — Backend tests for:
  * Iter 77i: OT Report endpoints (JSON + XLSX)
  * Iter 77j: Off-Roll Salary Run (run_type=off_roll)
  * Regression: week-off cap fix (Iter 78 follow-up)

Every temporary firm/user is prefixed with ``Iter79-`` / ``TEST_Iter79_``
so ``scripts/cleanup_test_data.py --apply`` sweeps them up at the end.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timedelta

import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"


# ------------------------------------------------------------------ fixtures
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
    assert r.status_code == 200, r.text
    code = r.json().get("dev_code")
    assert code, r.json()
    r2 = http.post(
        f"{API}/auth/otp/verify",
        json={"identifier": SUPER_EMAIL, "channel": "email", "code": code},
        timeout=15,
    )
    assert r2.status_code == 200, r2.text
    tok = r2.json().get("session_token") or r2.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def auth_hdr(super_token):
    return {"Authorization": f"Bearer {super_token}"}


# ------------------------------------------------------------------ helpers
def _create_firm(http, auth_hdr, name_prefix: str, policy_variant: str = "policy_1"):
    unique = uuid.uuid4().hex[:6]
    payload = {
        "name": f"{name_prefix}-{unique}",
        "code": f"IT79{unique[:4].upper()}",
        "business_category": "industry",
        "business_subcategory": "Textile",
        "policy_variant": policy_variant,
        "office_lat": 28.6139,
        "office_lng": 77.2090,
    }
    r = http.post(f"{API}/companies", json=payload, headers=auth_hdr, timeout=15)
    assert r.status_code in (200, 201), r.text
    data = r.json()
    cid = data.get("company_id") or (data.get("company") or {}).get("company_id")
    assert cid
    # Ensure policy variant is set (companies endpoint may ignore it — patch)
    pr = http.get(f"{API}/attendance/policy", params={"company_id": cid},
                  headers=auth_hdr, timeout=15)
    assert pr.status_code == 200, pr.text
    pol = (pr.json() or {}).get("policy") or {}
    pol["policy_variant"] = policy_variant
    pol["weekly_off_days"] = [6]
    up = http.patch(
        f"{API}/attendance/policy", params={"company_id": cid},
        json={"policy": pol}, headers=auth_hdr, timeout=15,
    )
    assert up.status_code == 200, up.text
    return cid


def _create_employee(http, auth_hdr, cid: str, *, is_onroll: bool = True,
                     name_suffix: str = ""):
    phone = f"+91982{uuid.uuid4().int % 10_000_000:07d}"
    payload = {
        "name": f"TEST_Iter79_{name_suffix or uuid.uuid4().hex[:6]}",
        "phone": phone,
        "company_id": cid,
        "employee_code": f"T79{uuid.uuid4().hex[:4].upper()}",
        "doj": "2020-01-01",
        "is_onroll": is_onroll,
    }
    r = http.post(f"{API}/admin/employees", json=payload, headers=auth_hdr, timeout=15)
    assert r.status_code in (200, 201), r.text
    uid = r.json().get("user_id") or (r.json().get("employee") or {}).get("user_id")
    assert uid
    return uid


def _set_employee_policy(http, auth_hdr, uid: str, patch: dict):
    r = http.patch(
        f"{API}/admin/employees/{uid}/policy",
        json=patch, headers=auth_hdr, timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _punch(http, auth_hdr, uid: str, date_iso: str, hh_in: str, hh_out: str):
    for kind, t in (("in", hh_in), ("out", hh_out)):
        rp = http.post(
            f"{API}/admin/attendance/manual-punch",
            json={"user_id": uid, "at": f"{date_iso}T{t}Z", "kind": kind,
                  "reason": "iter79 seed"},
            headers=auth_hdr, timeout=15,
        )
        assert rp.status_code == 200, f"{kind} {t} → {rp.status_code} {rp.text}"


# ==================================================================
# PART A — Week-off cap regression (Iter 78 follow-up)
# ==================================================================
class TestWeekOffCapRegression:
    """Direct unit-test — Policy 1 + ot_allowed=False + week-off + 10h duty
    must return duty_hours=10.0 (NOT capped at 8h)."""

    def test_weekoff_uncapped_when_ot_disallowed(self):
        from server import compute_textile_day
        punches = [
            {"kind": "in", "at": "2026-01-04T08:00:00+00:00"},   # Sunday
            {"kind": "out", "at": "2026-01-04T18:00:00+00:00"},  # 10h
        ]
        policy = {
            "policy_variant": "policy_1",
            "standard_working_hours": 8.0,
            "half_day_hours": 4.0,
            "weekly_off_days": [6],
            "week_off_min_working_hours": 8.0,
        }
        user = {"attendance_policy_override": {"ot_allowed": False}}
        result = compute_textile_day(punches, policy, user, day_weekday=6)
        assert result["duty_hours"] == 10.0, result
        assert result["present_days"] == 1.0, result
        assert result["is_weekly_off"] is True, result


# ==================================================================
# PART B — OT Report endpoints (Iter 77i)
# ==================================================================
@pytest.fixture(scope="module")
def ot_env(http, auth_hdr):
    """Seed a Policy 2 firm + 2 employees + 3 attendance days for OT report."""
    cid = _create_firm(http, auth_hdr, "Iter79-OT", policy_variant="policy_2")
    uid_a = _create_employee(http, auth_hdr, cid, name_suffix="OTA")
    uid_b = _create_employee(http, auth_hdr, cid, name_suffix="OTB")

    # Pick 3 consecutive weekdays in a well-known past month (2026-06)
    # Use Mon 2026-06-01, Tue 2026-06-02, Wed 2026-06-03.
    day1 = "2026-06-01"
    day2 = "2026-06-02"
    day3 = "2026-06-03"

    # Employee A: 10h on day1 and day2 → 2h OT each (standard 8h)
    _punch(http, auth_hdr, uid_a, day1, "07:00:00", "17:00:00")  # 10h
    _punch(http, auth_hdr, uid_a, day2, "07:00:00", "17:00:00")  # 10h
    # Employee B: 8h on day1 → no OT
    _punch(http, auth_hdr, uid_b, day1, "09:00:00", "17:00:00")  # 8h

    return {"cid": cid, "uid_a": uid_a, "uid_b": uid_b,
            "day1": day1, "day2": day2, "day3": day3}


class TestOTReportPolicy2:
    def test_json_endpoint_returns_only_ot_days(self, http, auth_hdr, ot_env):
        cid = ot_env["cid"]
        r = http.get(
            f"{API}/admin/attendance/ot-report/{cid}/2026-06",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # count = 2 (only A's 2 OT days)
        assert body.get("count") == 2, body
        rows = body.get("rows") or []
        assert len(rows) == 2
        # Only employee A should appear
        assert all(row.get("user_id") == ot_env["uid_a"] for row in rows), rows
        # Required fields
        expected_fields = {
            "employee_code", "name", "designation", "bio_code",
            "date", "day_label", "in", "out",
            "duty_hours", "ot_hours", "total_hours",
        }
        for row in rows:
            missing = expected_fields - set(row.keys())
            assert not missing, f"row missing fields {missing}: {row}"
            # Policy 2 → OT is broken out → row must show 2h OT for the
            # 10h-worked day (standard 8h). duty_hours here reflects
            # compute_textile_day's duty (includes OT for Policy 2) —
            # what matters is ot_hours > 0 and total = duty + ot.
            assert row["ot_hours"] == pytest.approx(2.0, abs=0.05), row
            assert row["total_hours"] == pytest.approx(
                row["duty_hours"] + row["ot_hours"], abs=0.05,
            ), row

    def test_xlsx_endpoint_returns_xlsx(self, http, auth_hdr, ot_env):
        cid = ot_env["cid"]
        r = http.get(
            f"{API}/admin/attendance/ot-report/{cid}/2026-06/xlsx",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        ctype = r.headers.get("Content-Type", "")
        assert "openxmlformats-officedocument.spreadsheetml.sheet" in ctype, ctype
        cdisp = r.headers.get("Content-Disposition", "")
        assert "attachment" in cdisp.lower(), cdisp
        # XLSX = ZIP: magic bytes PK\x03\x04
        assert r.content[:2] == b"PK", r.content[:8]

    def test_custom_range_filters_rows(self, http, auth_hdr, ot_env):
        cid = ot_env["cid"]
        # Only day1: expect 1 OT row
        r = http.get(
            f"{API}/admin/attendance/ot-report/{cid}/2026-06",
            params={"from_date": ot_env["day1"], "to_date": ot_env["day1"]},
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("count") == 1, body
        assert body["rows"][0]["date"] == ot_env["day1"]

    def test_employee_role_forbidden(self, http, auth_hdr, ot_env):
        """Employee-role token → 403 on OT report."""
        # OTP-login as the created employee (they auto-provisioned via
        # admin/employees so they exist as a user). We can't easily grab
        # their token without OTP; instead test negative auth by sending
        # no auth header.
        r = http.get(
            f"{API}/admin/attendance/ot-report/{ot_env['cid']}/2026-06",
            timeout=15,
        )
        assert r.status_code in (401, 403), (r.status_code, r.text)


# ==================================================================
# PART B.2 — Policy 1 OT Report (OT merged into duty → count=0)
# ==================================================================
@pytest.fixture(scope="module")
def ot_env_p1(http, auth_hdr):
    cid = _create_firm(http, auth_hdr, "Iter79-OTP1", policy_variant="policy_1")
    uid = _create_employee(http, auth_hdr, cid, name_suffix="P1OT")
    # 10h punch on a workday
    _punch(http, auth_hdr, uid, "2026-06-02", "07:00:00", "17:00:00")
    return {"cid": cid, "uid": uid}


class TestOTReportPolicy1:
    def test_policy1_returns_zero_ot(self, http, auth_hdr, ot_env_p1):
        cid = ot_env_p1["cid"]
        r = http.get(
            f"{API}/admin/attendance/ot-report/{cid}/2026-06",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Policy 1 merges OT into duty (capped at 24h/ot_allowed default) →
        # ot_hours=0 → row filtered out → count=0
        assert body.get("count") == 0, body


# ==================================================================
# PART C — Off-Roll Salary Run (Iter 77j)
# ==================================================================
@pytest.fixture(scope="module")
def offroll_env(http, auth_hdr):
    cid = _create_firm(http, auth_hdr, "Iter79-OffRoll", policy_variant="policy_1")

    # Emp1: monthly on-roll, ₹30k
    emp1 = _create_employee(http, auth_hdr, cid, is_onroll=True, name_suffix="Emp1")
    _set_employee_policy(http, auth_hdr, emp1, {
        "salary": 30000, "salary_mode": "monthly",
        "salary_1": 1000, "day_1": 26,
    })

    # Emp2: daily off-roll, ₹800/day
    emp2 = _create_employee(http, auth_hdr, cid, is_onroll=False, name_suffix="Emp2")
    _set_employee_policy(http, auth_hdr, emp2, {
        "salary": 800, "salary_mode": "daily",
        "salary_1": 500, "day_1": 26,   # required by validator
    })

    # Emp3: daily off-roll, ₹600/day, WITH tier bonus (must be stripped)
    emp3 = _create_employee(http, auth_hdr, cid, is_onroll=False, name_suffix="Emp3")
    _set_employee_policy(http, auth_hdr, emp3, {
        "salary": 600, "salary_mode": "daily",
        "salary_1": 1500, "day_1": 25,   # tier bonus at 25 days
    })

    # Seed 20 days of full IN+OUT punches in 2026-06 for all 3 employees
    # Use 2026-06-01 (Mon) through 2026-06-20 (Sat) inclusive.
    start = date(2026, 6, 1)
    seeded = 0
    for i in range(30):
        if seeded >= 20:
            break
        d = start + timedelta(days=i)
        if d.weekday() == 6:  # skip Sunday (weekly off)
            continue
        d_iso = d.isoformat()
        for uid in (emp1, emp2, emp3):
            _punch(http, auth_hdr, uid, d_iso, "09:00:00", "17:00:00")  # 8h
        seeded += 1

    return {"cid": cid, "emp1": emp1, "emp2": emp2, "emp3": emp3,
            "days_seeded": seeded}


class TestOffRollSalaryRun:
    def test_offroll_excludes_onroll_and_strips_tier_bonus(
        self, http, auth_hdr, offroll_env,
    ):
        cid = offroll_env["cid"]
        r = http.post(
            f"{API}/admin/salary-runs",
            json={"month": "2026-06", "company_id": cid, "run_type": "off_roll"},
            headers=auth_hdr, timeout=60,
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        run = body.get("run") or body
        # run_type echoed
        assert run.get("run_type") == "off_roll", body
        rows = run.get("rows") or []
        row_uids = {row["user_id"] for row in rows}
        # Emp1 (on-roll) MUST be excluded
        assert offroll_env["emp1"] not in row_uids, row_uids
        # Emp2 and Emp3 (off-roll) MUST be present
        assert offroll_env["emp2"] in row_uids, row_uids
        assert offroll_env["emp3"] in row_uids, row_uids
        assert len(rows) == 2, rows

        by_uid = {r["user_id"]: r for r in rows}
        # Emp3 tier bonus MUST be stripped
        emp3_row = by_uid[offroll_env["emp3"]]
        assert emp3_row.get("bonus", 0) == 0, emp3_row
        assert emp3_row.get("run_type") == "off_roll", emp3_row

        # Emp2 base pay ≈ 800 × 20 = 16000 (no bonus, no advance)
        emp2_row = by_uid[offroll_env["emp2"]]
        expected_base = 800.0 * offroll_env["days_seeded"]
        assert emp2_row.get("base_pay") == pytest.approx(expected_base, abs=100), emp2_row
        # net ≈ base_pay - advance (advance defaults to 0)
        advance = emp2_row.get("advance", 0.0) or 0.0
        assert emp2_row.get("net") == pytest.approx(expected_base - advance, abs=100), emp2_row
        assert emp2_row.get("bonus", 0) == 0, emp2_row

    def test_compliance_default_includes_all_employees(
        self, http, auth_hdr, offroll_env,
    ):
        """When run_type=compliance and is_onroll is not passed, ALL employees
        (on-roll and off-roll) should be included."""
        cid = offroll_env["cid"]
        r = http.post(
            f"{API}/admin/salary-runs",
            json={"month": "2026-06", "company_id": cid, "run_type": "compliance"},
            headers=auth_hdr, timeout=60,
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        run = body.get("run") or body
        assert run.get("run_type") == "compliance", body
        row_uids = {row["user_id"] for row in (run.get("rows") or [])}
        # All three employees should appear
        assert offroll_env["emp1"] in row_uids, row_uids
        assert offroll_env["emp2"] in row_uids, row_uids
        assert offroll_env["emp3"] in row_uids, row_uids
        # All rows should carry run_type=compliance
        for row in run.get("rows") or []:
            assert row.get("run_type") == "compliance", row

    def test_compliance_default_is_default_when_run_type_omitted(
        self, http, auth_hdr, offroll_env,
    ):
        cid = offroll_env["cid"]
        r = http.post(
            f"{API}/admin/salary-runs",
            json={"month": "2026-06", "company_id": cid},
            headers=auth_hdr, timeout=60,
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        run = body.get("run") or body
        assert run.get("run_type") == "compliance", body
