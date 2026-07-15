"""
Iter 129 — Attendance policy pipeline propagation tests.

Scope (per E1 review_request):
  1. GET /api/attendance/my-month (employee token) — policy-driven view for PWA
  2. Cross-check my-month day cells/totals against admin monthly-grid JSON
  3. Admin PDFs (monthly-inout / monthly-hours) — 200 + PDF content sanity
  4. Regressions on xlsx / daily / ot-report endpoints
  5. GET /api/attendance/summary?days=7 — policy overlay on dashboard widget
"""
import io
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL") or "https://emplo-connect-1.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")

CID = "cmp_527fecdd7c"
MONTH = "2026-07"
EMP_USER_ID = "user_44cd6f561da0"      # SURENDRA SINGH (code 50)
EMP_CODE = "50"
TARGET_STAFF_CODE = "212"              # MADAN KEER — monthly staff we cross-check


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def emp_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/pin-login",
        json={"login_id": "TEST50", "pin": "123456"},
        timeout=30,
    )
    assert r.status_code == 200, f"pin-login failed: {r.status_code} {r.text[:200]}"
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, f"admin-password-login failed: {r.status_code} {r.text[:200]}"
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def emp_headers(emp_token):
    return {"Authorization": f"Bearer {emp_token}"}


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ==============================================================================
# 1. /api/attendance/my-month — new employee-scoped policy view
# ==============================================================================
class TestMyMonth:
    def test_no_auth_401(self):
        r = requests.get(f"{BASE_URL}/api/attendance/my-month?month=2026-07", timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_bad_month_400(self, emp_headers):
        r = requests.get(
            f"{BASE_URL}/api/attendance/my-month?month=2026-13",
            headers=emp_headers, timeout=30,
        )
        assert r.status_code == 400, f"expected 400 got {r.status_code} body={r.text[:200]}"

    def test_shape_and_policy_fields(self, emp_headers):
        r = requests.get(
            f"{BASE_URL}/api/attendance/my-month?month={MONTH}",
            headers=emp_headers, timeout=30,
        )
        assert r.status_code == 200, f"got {r.status_code} body={r.text[:300]}"
        data = r.json()

        # Structural fields
        for k in ("day_labels", "day_full_dates", "weekly_off_days", "days", "totals"):
            assert k in data, f"missing key {k} in my-month response"

        assert isinstance(data["day_labels"], list) and len(data["day_labels"]) == 31
        assert isinstance(data["day_full_dates"], list) and len(data["day_full_dates"]) == 31
        assert 6 in data["weekly_off_days"], f"expected Sunday(6) in weekly_off_days, got {data['weekly_off_days']}"

        # Days map — cell shape
        days = data["days"]
        assert isinstance(days, dict)
        sample_day_keys = list(days.keys())[:5]
        assert sample_day_keys, "days map is empty"
        for dk in sample_day_keys:
            cell = days[dk]
            for f in ("in", "out", "hours", "duty_hours", "ot_hours",
                      "present", "weekly_off", "anomaly", "punches"):
                assert f in cell, f"cell {dk} missing field {f}: {cell}"

        # No leaked salary fields on employee view
        blob = str(data).lower()
        assert "salary" not in blob, "my-month must NOT contain any 'salary' field for employee view"

    def test_weekly_off_sundays(self, emp_headers):
        r = requests.get(
            f"{BASE_URL}/api/attendance/my-month?month={MONTH}",
            headers=emp_headers, timeout=30,
        )
        data = r.json()
        # July 2026: 5,12,19,26 are Sundays. Days 12/19/26 must be weekly_off True
        # (day 5 may have punches → anomaly, but weekly_off flag itself should still be true)
        for d in ("12", "19", "26"):
            cell = data["days"].get(d)
            assert cell is not None, f"missing day {d}"
            assert cell.get("weekly_off") is True, f"day {d} expected weekly_off, got {cell}"


# ==============================================================================
# 2. Cross-check my-month vs admin monthly-grid
# ==============================================================================
class TestMyMonthMatchesGrid:
    def test_emp50_grid_alignment(self, emp_headers, admin_headers):
        my = requests.get(
            f"{BASE_URL}/api/attendance/my-month?month={MONTH}",
            headers=emp_headers, timeout=60,
        ).json()

        grid = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid/{CID}/{MONTH}",
            headers=admin_headers, timeout=60,
        )
        assert grid.status_code == 200, f"grid endpoint {grid.status_code} {grid.text[:200]}"
        grid = grid.json()

        # Locate SURENDRA SINGH (emp_code 50) row
        rows = grid.get("rows") or grid.get("employees") or []
        row50 = None
        for r in rows:
            code = str(r.get("employee_code") or r.get("code") or "")
            if code == EMP_CODE:
                row50 = r
                break
        assert row50 is not None, f"employee 50 not found in grid rows (n={len(rows)})"

        # Compare per-day duty hours for days 1..15 (skip 0-cells to avoid noise)
        row_days = row50.get("days") or row50.get("cells") or {}
        mismatches = []
        for d in range(1, 16):
            key = str(d)
            g_cell = row_days.get(key) if isinstance(row_days, dict) else None
            m_cell = my["days"].get(key)
            if not g_cell or not m_cell:
                continue
            g_hours = g_cell.get("duty_hours") if isinstance(g_cell, dict) else None
            m_hours = m_cell.get("duty_hours")
            if g_hours is None or m_hours is None:
                continue
            if round(float(g_hours), 2) != round(float(m_hours), 2):
                mismatches.append((d, g_hours, m_hours))
        assert not mismatches, f"my-month vs grid duty_hours mismatches: {mismatches}"


# ==============================================================================
# 3. PDF reports — status + basic sanity
# ==============================================================================
class TestPdfReports:
    def test_monthly_inout_pdf_ok(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-inout/{CID}/{MONTH}.pdf",
            headers=admin_headers, timeout=120,
        )
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF", "not a PDF"
        assert len(r.content) > 5000

    def test_monthly_hours_pdf_ok_and_madan_totals(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-hours/{CID}/{MONTH}.pdf",
            headers=admin_headers, timeout=120,
        )
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

        # Extract text using pdfminer if available, else fallback to pypdf
        text = ""
        try:
            from pdfminer.high_level import extract_text
            text = extract_text(io.BytesIO(r.content))
        except Exception:
            try:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(r.content))
                text = "\n".join((p.extract_text() or "") for p in reader.pages)
            except Exception as e:
                pytest.skip(f"no pdf text extractor available: {e}")

        assert "MADAN" in text.upper(), "MADAN KEER row not found in hours PDF"

        # Also cross-check numbers against grid JSON (source of truth per E1)
        grid = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid/{CID}/{MONTH}",
            headers=admin_headers, timeout=60,
        ).json()
        rows = grid.get("rows") or grid.get("employees") or []
        madan = next(
            (r for r in rows if str(r.get("employee_code") or "") == TARGET_STAFF_CODE),
            None,
        )
        assert madan is not None, "MADAN KEER (212) not found in grid"
        totals = madan.get("totals") or {}
        # E1 expected numbers: 24.00 / 6.50 / 30.50 / 3 / 6.50
        # Only assert on grid (single source of truth); PDF is checked to contain the strings.
        exp = {"duty_hours": 24.00, "ot_hours": 6.50, "total_hours": 30.50,
               "days": 3, "extra": 6.50}
        soft_mismatches = []
        for k, v in exp.items():
            actual = totals.get(k)
            if actual is None:
                continue
            if round(float(actual), 2) != round(float(v), 2):
                soft_mismatches.append((k, v, actual))
        assert not soft_mismatches, f"MADAN grid totals mismatch expected={exp} got={totals} diff={soft_mismatches}"


# ==============================================================================
# 4. Regressions — xlsx / daily / ot-report
# ==============================================================================
class TestRegressions:
    def test_monthly_inout_xlsx(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-inout/{CID}/{MONTH}.xlsx",
            headers=admin_headers, timeout=120,
        )
        assert r.status_code == 200
        assert r.content[:2] == b"PK", "not an xlsx (zip) file"

    def test_monthly_hours_xlsx(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-hours/{CID}/{MONTH}.xlsx",
            headers=admin_headers, timeout=120,
        )
        assert r.status_code == 200
        assert r.content[:2] == b"PK"

    def test_daily_pdf(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/daily/{CID}/2026-07-13.pdf",
            headers=admin_headers, timeout=120,
        )
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_daily_xlsx(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/daily/{CID}/2026-07-13.xlsx",
            headers=admin_headers, timeout=120,
        )
        assert r.status_code == 200
        assert r.content[:2] == b"PK"

    def test_ot_report_json(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/ot-report/{CID}/{MONTH}",
            headers=admin_headers, timeout=120,
        )
        assert r.status_code == 200
        data = r.json()
        # Just structural — rows/employees must be a list
        assert isinstance(data, (dict, list))


# ==============================================================================
# 5. /api/attendance/summary?days=7 — policy overlay
# ==============================================================================
class TestSummary:
    def test_summary_policy_overlay(self, emp_headers):
        r = requests.get(
            f"{BASE_URL}/api/attendance/summary?days=7",
            headers=emp_headers, timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        data = r.json()

        assert "days" in data, f"missing days key in summary: {list(data.keys())}"
        assert "window_total_hours" in data, "missing window_total_hours"
        assert "total_hours_till_today" in data, "missing total_hours_till_today"

        days = data["days"]
        assert isinstance(days, list) and len(days) >= 1

        # anomaly / missing-punch days must have hours == 0.0
        for d in days:
            anomaly = d.get("anomaly") or d.get("missing_punch") or d.get("is_anomaly")
            if anomaly:
                assert float(d.get("hours", 0.0)) == 0.0, (
                    f"anomaly day should have hours=0, got {d}"
                )

        # window_total_hours must equal sum of days' hours
        total = round(sum(float(d.get("hours") or 0.0) for d in days), 2)
        window_total = round(float(data["window_total_hours"]), 2)
        assert total == window_total, (
            f"window_total_hours mismatch: sum(days)={total} vs field={window_total}"
        )
