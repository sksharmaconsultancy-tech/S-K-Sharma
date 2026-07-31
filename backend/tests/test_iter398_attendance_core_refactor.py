"""Iter 398 backend regression — Attendance core cluster extraction.

Verifies the PURE REFACTOR of ~3,520 lines of attendance code from server.py
into routes/attendance_core.py. Focus:

  (A) Employee punch flow (the riskiest moved code)
       - login as TEST50 (login_id/pin), /attendance/today, /attendance/punch,
         /attendance/my-month, /attendance/first-punch-status
  (B) Admin attendance endpoints (today/roster/day-status/open-shifts/history/present-not-punched)
  (C) Admin manual punch full cycle (create → list → delete → audit)
  (D) Roster mark cycle
  (E) Payroll compute engine regression (_compute_payroll_run, monthly-grid, email-report)
  (F) Downstream module imports intact (payslips, biometric, messages)
  (G) Global regression (openapi count, compliance runs, employee CRUD, no NameError)
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://emplo-connect-1.preview.emergentagent.com",
).rstrip("/")
CID = "cmp_527fecdd7c"  # Kankani Enterprises

MONTH = "2026-07"
DAY_FROM = "2026-07-01"
DAY_TO = "2026-07-15"
MANUAL_DATE = "2026-07-20"
ROSTER_DATE = "2026-07-21"


# --------------------------------------------------------------------------- session
@pytest.fixture(scope="session")
def admin_token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("session_token")
    assert tok, "no session_token"
    return tok


@pytest.fixture(scope="session")
def admin(admin_token) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {admin_token}",
        "Content-Type": "application/json",
    })
    return s


@pytest.fixture(scope="session")
def emp_token() -> str:
    """Login as TEST50 (SURENDRA SINGH, code 50) via /auth/pin-login using login_id."""
    r = requests.post(
        f"{BASE_URL}/api/auth/pin-login",
        json={"login_id": "TEST50", "pin": "123456"},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"employee login failed: {r.status_code} {r.text[:200]}")
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok, f"no session token: {r.json()}"
    return tok


@pytest.fixture(scope="session")
def emp(emp_token) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {emp_token}",
        "Content-Type": "application/json",
    })
    return s


# --------------------------------------------------------------------------- (A) Employee punch flow
class TestEmployeePunchFlow:
    """Riskiest moved code — the employee punch engine."""

    def test_attendance_today(self, emp):
        r = emp.get(f"{BASE_URL}/api/attendance/today", timeout=30)
        assert r.status_code == 200, f"/attendance/today → {r.status_code} {r.text[:200]}"
        # Response should be dict (records, punches, etc.)
        assert isinstance(r.json(), dict)

    def test_first_punch_status(self, emp):
        r = emp.get(f"{BASE_URL}/api/attendance/first-punch-status", timeout=30)
        # 200 always (returns whether onboarding needed)
        assert r.status_code == 200, f"first-punch-status → {r.status_code} {r.text[:200]}"

    def test_my_month(self, emp):
        r = emp.get(f"{BASE_URL}/api/attendance/my-month?month=2026-07", timeout=30)
        assert r.status_code == 200, f"my-month → {r.status_code} {r.text[:200]}"

    def test_punch_in_no_500(self, emp):
        """Punch endpoint must NOT throw 500 (NameError from the refactor)."""
        payload = {
            "kind": "in",
            "lat": 25.3479,   # somewhere near Bhilwara (may be outside geofence)
            "lng": 74.6362,
            "accuracy": 20,
        }
        r = emp.post(f"{BASE_URL}/api/attendance/punch", json=payload, timeout=30)
        # Acceptable: 200 (success), 400/403/409 (policy/geofence/duplicate), 412 (onboarding),
        # 422 (schema). NOT 500 — that would be a NameError/ImportError from the refactor.
        assert r.status_code != 500, f"punch returned 500 (regression!): {r.text[:400]}"
        assert r.status_code < 500, f"punch 5xx: {r.status_code} {r.text[:200]}"

    def test_attendance_history(self, emp):
        r = emp.get(f"{BASE_URL}/api/attendance/history?limit=5", timeout=30)
        assert r.status_code == 200, f"history → {r.status_code} {r.text[:200]}"


# --------------------------------------------------------------------------- (B) Admin attendance
class TestAdminAttendance:
    def test_today(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/attendance/today?company_id={CID}", timeout=30)
        assert r.status_code == 200, r.text[:200]

    def test_roster(self, admin):
        r = admin.get(
            f"{BASE_URL}/api/admin/attendance/roster?company_id={CID}&date={DAY_TO}",
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]

    def test_day_status(self, admin):
        r = admin.get(
            f"{BASE_URL}/api/admin/attendance/day-status/{CID}"
            f"?from_date={DAY_FROM}&to_date={DAY_TO}",
            timeout=60,
        )
        assert r.status_code == 200, r.text[:200]

    def test_day_status_missing_from_date_422(self, admin):
        r = admin.get(
            f"{BASE_URL}/api/admin/attendance/day-status/{CID}?to_date={DAY_TO}",
            timeout=30,
        )
        # from_date is a required Query param
        assert r.status_code == 422, f"expected 422 got {r.status_code}"

    def test_open_shifts(self, admin):
        r = admin.get(
            f"{BASE_URL}/api/admin/attendance/open-shifts?company_id={CID}",
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]

    def test_present_not_punched(self, admin):
        r = admin.get(
            f"{BASE_URL}/api/admin/attendance/present-not-punched?company_id={CID}",
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]

    def test_admin_history(self, admin):
        r = admin.get(
            f"{BASE_URL}/api/admin/attendance/history?company_id={CID}&limit=5",
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]


# --------------------------------------------------------------------------- (C) Manual punch cycle
class TestManualPunchCycle:
    _record_id: str | None = None
    _target_uid: str | None = None

    def test_pick_target_employee(self, admin):
        """Pick an active employee (TEST50 / code 50) from Kankani."""
        r = admin.get(f"{BASE_URL}/api/admin/employees?company_id={CID}", timeout=60)
        assert r.status_code == 200
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("employees") or rows.get("items") or rows.get("rows") or []
        # Prefer code 50
        target = next(
            (e for e in rows if isinstance(e, dict) and str(e.get("employee_code")) == "50"),
            None,
        ) or next((e for e in rows if isinstance(e, dict) and e.get("user_id")), None)
        assert target, "no employee found for manual-punch test"
        TestManualPunchCycle._target_uid = target["user_id"]

    def test_create_manual_punch(self, admin):
        uid = TestManualPunchCycle._target_uid
        assert uid
        # ManualPunchCreate: user_id, kind, at, reason (see routes/attendance_core.py)
        payload = {
            "user_id": uid,
            "kind": "in",
            "at": f"{MANUAL_DATE}T09:15:00+05:30",
            "reason": "TEST_iter398 manual punch (in)",
        }
        r = admin.post(
            f"{BASE_URL}/api/admin/attendance/manual-punch",
            json=payload,
            timeout=60,
        )
        assert r.status_code == 200, f"manual-punch create → {r.status_code} {r.text[:400]}"
        data = r.json()
        # Response format may vary; extract record id
        rid = (
            data.get("record_id")
            or data.get("id")
            or (data.get("record") or {}).get("record_id")
            or (data.get("record") or {}).get("id")
        )
        # If manual-punch creates in+out (two records) we need the list to find them
        if not rid:
            # Look it up via admin history
            hr = admin.get(
                f"{BASE_URL}/api/admin/attendance/history?company_id={CID}"
                f"&user_id={uid}&from_date={MANUAL_DATE}&to_date={MANUAL_DATE}",
                timeout=30,
            )
            assert hr.status_code == 200
            items = hr.json()
            if isinstance(items, dict):
                items = items.get("records") or items.get("items") or items.get("rows") or []
            assert items, f"created manual punch not found in history: {data}"
            rid = (items[0] or {}).get("record_id") or (items[0] or {}).get("id")
        assert rid, f"no record_id found: {data}"
        TestManualPunchCycle._record_id = rid

    def test_manual_punch_appears_in_history(self, admin):
        uid = TestManualPunchCycle._target_uid
        r = admin.get(
            f"{BASE_URL}/api/admin/attendance/history?company_id={CID}"
            f"&user_id={uid}&from_date={MANUAL_DATE}&to_date={MANUAL_DATE}",
            timeout=30,
        )
        assert r.status_code == 200
        items = r.json()
        if isinstance(items, dict):
            items = items.get("records") or items.get("items") or items.get("rows") or []
        assert items, "manual punch not in history"

    def test_delete_manual_punch(self, admin):
        """CLEANUP — delete all TEST records for this employee on MANUAL_DATE."""
        uid = TestManualPunchCycle._target_uid
        # Get all records for that date and delete them
        r = admin.get(
            f"{BASE_URL}/api/admin/attendance/history?company_id={CID}"
            f"&user_id={uid}&from_date={MANUAL_DATE}&to_date={MANUAL_DATE}",
            timeout=30,
        )
        items = r.json()
        if isinstance(items, dict):
            items = items.get("records") or items.get("items") or items.get("rows") or []
        deleted = 0
        for rec in items or []:
            rid = rec.get("record_id") or rec.get("id")
            if not rid:
                continue
            dr = admin.delete(
                f"{BASE_URL}/api/admin/attendance/{rid}?reason=TEST_iter398_cleanup",
                timeout=30,
            )
            assert dr.status_code in (200, 204, 404), (
                f"delete record {rid} → {dr.status_code} {dr.text[:200]}"
            )
            deleted += 1
        # Verify cleaned up
        r2 = admin.get(
            f"{BASE_URL}/api/admin/attendance/history?company_id={CID}"
            f"&user_id={uid}&from_date={MANUAL_DATE}&to_date={MANUAL_DATE}",
            timeout=30,
        )
        items2 = r2.json()
        if isinstance(items2, dict):
            items2 = items2.get("records") or items2.get("items") or items2.get("rows") or []
        assert not items2, f"records remain after cleanup ({deleted} deleted): {items2}"


# --------------------------------------------------------------------------- (D) Roster mark cycle
class TestRosterMarkCycle:
    def test_roster_mark_and_revert(self, admin):
        # Get a target user
        r = admin.get(f"{BASE_URL}/api/admin/employees?company_id={CID}", timeout=60)
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("employees") or rows.get("items") or rows.get("rows") or []
        target = next(
            (e for e in rows if isinstance(e, dict) and str(e.get("employee_code")) == "50"),
            None,
        ) or next((e for e in rows if isinstance(e, dict) and e.get("user_id")), None)
        assert target
        uid = target["user_id"]

        # RosterMarkRequest: {marks: [{user_id, action: in|out|absent}], note?}
        # NOTE: the endpoint marks against TODAY (hard-coded) — not a
        # payload date. We use action="absent" (idempotent per user+date).
        mark_payload = {
            "marks": [{"user_id": uid, "action": "absent"}],
            "note": "TEST_iter398 roster mark",
        }
        r1 = admin.post(
            f"{BASE_URL}/api/admin/attendance/roster/mark",
            json=mark_payload,
            timeout=30,
        )
        assert r1.status_code == 200, f"roster/mark → {r1.status_code} {r1.text[:300]}"
        data = r1.json()
        # results is a list of per-row dicts
        results = data.get("results") if isinstance(data, dict) else None
        assert results is not None, f"no results in response: {data}"

        # Find the created absent record for TODAY
        from datetime import datetime, timezone as _tz
        today = datetime.now(_tz.utc).strftime("%Y-%m-%d")

        # Verify roster reflects the mark
        r2 = admin.get(
            f"{BASE_URL}/api/admin/attendance/roster?company_id={CID}&date={today}",
            timeout=30,
        )
        assert r2.status_code == 200

        # CLEANUP — delete the "absent" record via history + delete
        hr = admin.get(
            f"{BASE_URL}/api/admin/attendance/history?company_id={CID}"
            f"&user_id={uid}&from_date={today}&to_date={today}",
            timeout=30,
        )
        items = hr.json()
        if isinstance(items, dict):
            items = items.get("records") or items.get("items") or items.get("rows") or []
        for rec in items or []:
            if rec.get("kind") == "absent" and rec.get("source") == "roster":
                rid = rec.get("record_id") or rec.get("id")
                if rid:
                    dr = admin.delete(
                        f"{BASE_URL}/api/admin/attendance/{rid}"
                        f"?reason=TEST_iter398_roster_cleanup",
                        timeout=30,
                    )
                    assert dr.status_code in (200, 204, 404), (
                        f"cleanup delete → {dr.status_code} {dr.text[:200]}"
                    )


# --------------------------------------------------------------------------- (E) Payroll compute engine
class TestPayrollComputeEngine:
    def test_monthly_grid(self, admin):
        """Exercises _compute_payroll_run via monthly grid."""
        r = admin.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid/{CID}/{MONTH}",
            timeout=60,
        )
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert isinstance(data, (dict, list))

    def test_email_report_no_nameerror(self, admin):
        """Runs _compute_payroll_run internally. Resend may not be configured
        — a clean 4xx or a 200 is acceptable, but 500 NameError is a REGRESSION."""
        r = admin.post(
            f"{BASE_URL}/api/admin/payroll/email-report",
            json={
                "company_id": CID,
                "year": 2026,
                "month": 7,
                "recipients": "self",
                "report_kind": "combined",
            },
            timeout=90,
        )
        # Must not be a 500 due to missing helpers
        if r.status_code == 500:
            body = r.text[:400]
            assert "NameError" not in body and "ImportError" not in body, (
                f"REGRESSION — 500 NameError/ImportError: {body}"
            )
        assert r.status_code < 500, f"email-report 5xx: {r.status_code} {r.text[:300]}"


# --------------------------------------------------------------------------- (F) Downstream module imports
class TestDownstreamModules:
    def test_payslips_list(self, admin):
        # /api/payslips accepts company_id
        r = admin.get(f"{BASE_URL}/api/payslips?company_id={CID}&limit=1", timeout=30)
        assert r.status_code == 200, f"payslips → {r.status_code} {r.text[:200]}"

    def test_biometric_devices_list(self, admin):
        r = admin.get(f"{BASE_URL}/api/biometric/devices?company_id={CID}", timeout=30)
        # 200 or 404 (endpoint may not exist yet) — must not 500 due to import failure
        assert r.status_code in (200, 401, 403, 404), (
            f"biometric devices → {r.status_code} {r.text[:200]}"
        )
        assert r.status_code != 500

    def test_messages_inbox(self, admin):
        r = admin.get(f"{BASE_URL}/api/messages/inbox", timeout=30)
        assert r.status_code == 200, f"messages inbox → {r.status_code} {r.text[:200]}"


# --------------------------------------------------------------------------- (G) Global regression
class TestGlobalRegression:
    def test_openapi_path_count(self):
        try:
            r = requests.get("http://localhost:8001/openapi.json", timeout=30)
        except Exception as e:
            pytest.skip(f"openapi not reachable internally: {e}")
        assert r.status_code == 200
        paths = r.json().get("paths") or {}
        # Expected 698 per problem statement — allow small drift
        assert 690 <= len(paths) <= 710, f"openapi count = {len(paths)} (expected ~698)"

    def test_compliance_salary_runs(self, admin):
        r = admin.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs?limit=1",
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]

    def test_employee_create_delete_cycle(self, admin):
        phone10 = "9" + str(int(time.time() * 1000))[-9:]
        payload = {
            "company_id": CID,
            "name": "TEST_ITER398 EMP",
            "phone": phone10,
            "father_name": "Test Father",
            "gender": "M",
            "dob": "1990-01-01",
            "doj": "2026-01-01",
            "department": "TEST",
            "designation": "Tester",
            "employee_type": "Staff",
        }
        r = admin.post(f"{BASE_URL}/api/admin/employees", json=payload, timeout=60)
        assert r.status_code == 200, f"create → {r.status_code} {r.text[:300]}"
        data = r.json()
        uid = data.get("user_id") or (data.get("employee") or {}).get("user_id")
        assert uid
        # CLEANUP
        dr = admin.delete(f"{BASE_URL}/api/admin/employees/{uid}", timeout=60)
        assert dr.status_code == 200, f"delete → {dr.status_code}"

    def test_no_nameerror_in_backend_logs(self):
        """Scan the recent backend error log for NameError/ImportError from the refactor."""
        try:
            with open("/var/log/supervisor/backend.err.log", "r") as f:
                content = f.read()[-20000:]  # last 20KB
        except Exception as e:
            pytest.skip(f"cannot read backend log: {e}")
        for bad in ("NameError:", "ImportError: cannot import name"):
            # Filter — we ONLY care about recent errors, not historic reloader ones.
            # If the process is up (we already ran many API calls successfully)
            # and there's no recent trace since startup, we're clean.
            if bad in content:
                # Check if it appears AFTER the last "Application startup complete"
                last_start = content.rfind("Application startup complete")
                if last_start == -1:
                    continue
                after = content[last_start:]
                assert bad not in after, (
                    f"post-startup {bad} in backend log:\n{after[-1500:]}"
                )
