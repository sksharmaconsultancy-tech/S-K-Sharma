"""Iter 399 backend regression — attendance_core + payroll_core + shared/dates split.

Verifies the PURE REFACTOR that split the 3,576-line attendance_core.py into:
  - routes/attendance_core.py         (~1,265 lines — employee-facing punch engine)
  - routes/attendance_admin_core.py   (~1,507 lines — admin ops)
  - routes/payroll_core.py            (  744 lines — /salary/monthly, /me/payslips,
                                          /me/id-card, /admin/payroll(+run), _compute_payroll_run,
                                          /admin/employees, /admin/employee-types)
  - shared/dates.py                   (pure date helpers)
  - MessageCreate/MessageAttachment moved into routes/messages.py.

Focus areas (per problem statement):
  (A) EMPLOYEE token flows — riskiest split code:
      login, /attendance/today, /attendance/punch (must NOT 500),
      /attendance/my-month?month=2026-07, /salary/monthly (payroll_core moved),
      /me/payslips/year-summary, /me/id-card.
  (B) ADMIN attendance regressions.
  (C) Manual punch cycle (attendance_admin_core).
  (D) Payroll core admin: employees / employee-types / payroll / payroll/run.
  (E) Downstream imports: /payslips (shared.dates), biometric (apply_contractual_gate
      re-import), messages POST + /sent + cleanup (MessageCreate moved), compliance
      salary runs, employee create+delete cycle.
  (F) Onboarding gate + auto-close loop: admin-password-login works, no NameError in logs.
  (G) openapi paths == 698 exactly.
  (H) Cleanup — test punches / messages / employees removed.
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

MONTH_STR = "2026-07"
MONTH_PAST = "2026-06"
YEAR_INT = 2026
MONTH_INT = 7
MANUAL_DATE = "2026-07-22"
DAY_FROM = "2026-07-01"
DAY_TO = "2026-07-15"


# --------------------------------------------------------------------------- sessions
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
    """Login as TEST50 (SURENDRA SINGH, code 50) via /auth/pin-login."""
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


@pytest.fixture(scope="session")
def emp_user_id(emp) -> str:
    r = emp.get(f"{BASE_URL}/api/auth/me", timeout=30)
    if r.status_code != 200:
        pytest.skip(f"/auth/me failed: {r.status_code}")
    data = r.json()
    return (data.get("user") or data).get("user_id")


# --------------------------------------------------------------------------- (A) Employee flow
class TestEmployeeFlow:
    """Employee-facing routes moved during the split — riskiest surface."""

    def test_attendance_today(self, emp):
        r = emp.get(f"{BASE_URL}/api/attendance/today", timeout=30)
        assert r.status_code == 200, f"/attendance/today → {r.status_code} {r.text[:200]}"
        assert isinstance(r.json(), dict)

    def test_attendance_my_month(self, emp):
        r = emp.get(f"{BASE_URL}/api/attendance/my-month?month={MONTH_STR}", timeout=30)
        assert r.status_code == 200, f"my-month → {r.status_code} {r.text[:200]}"

    def test_attendance_punch_no_500(self, emp):
        """Punch must NOT throw 500 (NameError from refactor)."""
        payload = {"kind": "in", "lat": 25.3479, "lng": 74.6362, "accuracy": 20}
        r = emp.post(f"{BASE_URL}/api/attendance/punch", json=payload, timeout=30)
        assert r.status_code != 500, f"punch returned 500 (REGRESSION!): {r.text[:400]}"
        assert r.status_code < 500, f"punch 5xx: {r.status_code} {r.text[:200]}"

    def test_salary_monthly_payroll_core(self, emp):
        """/salary/monthly moved to payroll_core.py — must still work."""
        # Endpoint returns the last 6 months automatically; month query ignored.
        r = emp.get(f"{BASE_URL}/api/salary/monthly?month={MONTH_PAST}", timeout=30)
        assert r.status_code == 200, f"/salary/monthly → {r.status_code} {r.text[:200]}"
        data = r.json()
        # payloadshape: {payslips: [...]} — accept either shape as long as JSON dict
        assert isinstance(data, (dict, list)), f"unexpected shape: {type(data)}"

    def test_me_payslips_year_summary(self, emp):
        """payroll_core.py: /me/payslips/year-summary."""
        r = emp.get(f"{BASE_URL}/api/me/payslips/year-summary", timeout=30)
        assert r.status_code == 200, f"year-summary → {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "totals" in data and "history" in data and "window_months" in data, (
            f"missing keys in year-summary: {list(data.keys())}"
        )

    def test_me_id_card(self, emp):
        """payroll_core.py: /me/id-card."""
        r = emp.get(f"{BASE_URL}/api/me/id-card", timeout=30)
        assert r.status_code == 200, f"/me/id-card → {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "employee" in data and "qr_payload" in data
        assert data["qr_payload"].startswith("SKSCO|"), f"bad qr_payload: {data['qr_payload']}"


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

    def test_day_status(self, admin):
        r = admin.get(
            f"{BASE_URL}/api/admin/attendance/day-status/{CID}"
            f"?from_date={DAY_FROM}&to_date={DAY_TO}",
            timeout=60,
        )
        assert r.status_code == 200, r.text[:200]


# --------------------------------------------------------------------------- (C) Manual punch cycle
class TestManualPunchCycle:
    """attendance_admin_core.py — full manual-punch CRUD + audit cycle."""

    _target_uid: str | None = None

    def test_pick_target(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/employees?company_id={CID}", timeout=60)
        assert r.status_code == 200
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("employees") or rows.get("items") or rows.get("rows") or []
        target = next(
            (e for e in rows if isinstance(e, dict) and str(e.get("employee_code")) == "50"),
            None,
        ) or next((e for e in rows if isinstance(e, dict) and e.get("user_id")), None)
        assert target
        TestManualPunchCycle._target_uid = target["user_id"]

    def test_create_manual_punch(self, admin):
        uid = TestManualPunchCycle._target_uid
        assert uid
        payload = {
            "user_id": uid,
            "kind": "in",
            "at": f"{MANUAL_DATE}T09:15:00+05:30",
            "reason": "TEST_iter399 manual punch (in)",
        }
        r = admin.post(
            f"{BASE_URL}/api/admin/attendance/manual-punch", json=payload, timeout=60,
        )
        assert r.status_code == 200, f"manual-punch → {r.status_code} {r.text[:300]}"

    def test_verify_in_history(self, admin):
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
        assert items, "manual punch not found in history"

    def test_cleanup_manual_punch(self, admin):
        """CLEANUP: delete every record created for MANUAL_DATE."""
        uid = TestManualPunchCycle._target_uid
        r = admin.get(
            f"{BASE_URL}/api/admin/attendance/history?company_id={CID}"
            f"&user_id={uid}&from_date={MANUAL_DATE}&to_date={MANUAL_DATE}",
            timeout=30,
        )
        items = r.json()
        if isinstance(items, dict):
            items = items.get("records") or items.get("items") or items.get("rows") or []
        for rec in items or []:
            rid = rec.get("record_id") or rec.get("id")
            if not rid:
                continue
            dr = admin.delete(
                f"{BASE_URL}/api/admin/attendance/{rid}?reason=TEST_iter399_cleanup",
                timeout=30,
            )
            assert dr.status_code in (200, 204, 404), dr.text[:200]
        # verify
        r2 = admin.get(
            f"{BASE_URL}/api/admin/attendance/history?company_id={CID}"
            f"&user_id={uid}&from_date={MANUAL_DATE}&to_date={MANUAL_DATE}",
            timeout=30,
        )
        items2 = r2.json()
        if isinstance(items2, dict):
            items2 = items2.get("records") or items2.get("items") or items2.get("rows") or []
        # Only leftover records should be pre-existing (kind != TEST_iter399 reason)
        residual = [
            x for x in (items2 or [])
            if "TEST_iter399" in (x.get("reason") or "") or (x.get("source") == "manual" and "iter399" in (x.get("reason") or "").lower())
        ]
        assert not residual, f"iter399 test records remain: {residual}"


# --------------------------------------------------------------------------- (D) Payroll core
class TestPayrollCore:
    """payroll_core.py — admin endpoints."""

    def test_admin_employees(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/employees?company_id={CID}", timeout=60)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        rows = data if isinstance(data, list) else (
            data.get("employees") or data.get("items") or data.get("rows") or []
        )
        assert isinstance(rows, list) and len(rows) > 0, "no employees returned"

    def test_admin_employee_types(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/employee-types", timeout=30)
        assert r.status_code == 200, r.text[:200]

    def test_admin_payroll_list(self, admin):
        r = admin.get(
            f"{BASE_URL}/api/admin/payroll?company_id={CID}&month={MONTH_STR}",
            timeout=60,
        )
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert "payslips" in data, f"expected payslips key: {list(data.keys())}"

    def test_admin_payroll_run_compute(self, admin):
        """/admin/payroll/run — exercises _compute_payroll_run."""
        r = admin.get(
            f"{BASE_URL}/api/admin/payroll/run"
            f"?year={YEAR_INT}&month={MONTH_INT}&company_id={CID}",
            timeout=120,
        )
        assert r.status_code == 200, f"/admin/payroll/run → {r.status_code} {r.text[:300]}"
        data = r.json()
        # Expected keys: year, month, month_key, days_in_month, off_days_total,
        #   rows, totals, attendance
        assert data.get("year") == YEAR_INT
        assert data.get("month") == MONTH_INT
        assert "rows" in data and "totals" in data


# --------------------------------------------------------------------------- (E) Downstream imports
class TestDownstreamImports:
    """Modules that now import from shared.dates or from attendance_core."""

    def test_payslips_uses_shared_dates(self, admin):
        # payslips.py now imports _month_is_complete/_payslip_is_processed from shared.dates
        r = admin.get(f"{BASE_URL}/api/payslips?company_id={CID}&limit=1", timeout=30)
        assert r.status_code in (200, 403), f"payslips → {r.status_code} {r.text[:200]}"
        assert r.status_code != 500

    def test_biometric_devices_apply_contractual_gate(self, admin):
        # biometric_devices imports apply_contractual_gate from routes.attendance_core
        r = admin.get(f"{BASE_URL}/api/biometric/devices?company_id={CID}", timeout=30)
        assert r.status_code in (200, 401, 403, 404), r.text[:200]
        assert r.status_code != 500

    def test_compliance_salary_runs(self, admin):
        # compliance_salary_runs imports from shared.dates
        r = admin.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs?limit=1", timeout=30,
        )
        assert r.status_code == 200, r.text[:200]


class TestMessagesCycle:
    """MessageCreate/MessageAttachment moved into routes/messages.py — full cycle."""

    _msg_id: str | None = None

    def test_send_message(self, admin, emp_user_id):
        payload = {
            "subject": "TEST_iter399 subject",
            "body": "TEST_iter399 body — refactor regression",
            "recipient_user_ids": [emp_user_id],
            "company_id": CID,
        }
        r = admin.post(f"{BASE_URL}/api/messages", json=payload, timeout=30)
        assert r.status_code == 200, f"/messages POST → {r.status_code} {r.text[:300]}"
        data = r.json()
        assert data.get("ok") is True
        msg = data.get("message") or {}
        assert msg.get("subject") == "TEST_iter399 subject"
        assert msg.get("recipient_count") == 1
        mid = msg.get("message_id")
        assert mid, "no message_id"
        TestMessagesCycle._msg_id = mid

    def test_list_sent(self, admin):
        r = admin.get(f"{BASE_URL}/api/messages/sent?limit=50", timeout=30)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        msgs = data.get("messages") if isinstance(data, dict) else data
        assert msgs is not None
        # Confirm our just-sent message shows up
        found = any(
            (m or {}).get("message_id") == TestMessagesCycle._msg_id
            for m in (msgs or [])
        )
        assert found, "sent message not found in outbox"

    def test_cleanup_message(self):
        """No public DELETE endpoint for messages — delete directly from DB.

        This keeps the test collection clean between runs.
        """
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore

        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        if not (mongo_url and db_name and TestMessagesCycle._msg_id):
            pytest.skip("env not set or no message id")

        async def _cleanup():
            client = AsyncIOMotorClient(mongo_url)
            db_ = client[db_name]
            await db_.messages.delete_one({"message_id": TestMessagesCycle._msg_id})
            client.close()

        asyncio.run(_cleanup())


# --------------------------------------------------------------------------- Employee CRUD downstream
class TestEmployeesAdminCycle:
    """employees_admin now imports _parse_any_date from shared.dates."""

    def test_create_and_delete(self, admin):
        phone10 = "9" + str(int(time.time() * 1000))[-9:]
        payload = {
            "company_id": CID,
            "name": "TEST_ITER399 EMP",
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
        dr = admin.delete(f"{BASE_URL}/api/admin/employees/{uid}", timeout=60)
        assert dr.status_code == 200, f"delete → {dr.status_code} {dr.text[:200]}"


# --------------------------------------------------------------------------- (F) onboarding gate + auto-close
class TestOnboardingAndAutoClose:
    def test_admin_login_uses_onboarding_gate(self):
        """admin-password-login pipes through _onboarding_login_gate."""
        r = requests.post(
            f"{BASE_URL}/api/auth/admin-password-login",
            json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("session_token")

    def test_no_nameerror_in_backend_logs(self):
        """Scan the recent backend error log for NameError/ImportError."""
        try:
            with open("/var/log/supervisor/backend.err.log", "r") as f:
                content = f.read()[-30000:]
        except Exception as e:
            pytest.skip(f"cannot read backend log: {e}")
        # Only care about errors AFTER last successful startup.
        last_start = content.rfind("Application startup complete")
        after = content[last_start:] if last_start >= 0 else content
        for bad in ("NameError:", "ImportError: cannot import name"):
            assert bad not in after, f"post-startup {bad} in backend log:\n{after[-1500:]}"


# --------------------------------------------------------------------------- (G) openapi count
class TestOpenAPICount:
    def test_openapi_698_paths(self):
        try:
            r = requests.get("http://localhost:8001/openapi.json", timeout=30)
        except Exception as e:
            pytest.skip(f"openapi not reachable: {e}")
        assert r.status_code == 200
        paths = r.json().get("paths") or {}
        assert len(paths) == 698, f"openapi count = {len(paths)} (expected 698)"
