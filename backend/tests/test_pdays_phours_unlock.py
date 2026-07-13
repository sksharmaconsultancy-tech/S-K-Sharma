"""Backend regression: P Days & P Hours are editable regardless of
attendance_source in Actual Salary Process.

Iter (86) — Removes the previous `src_lock` behavior that silently
ignored p_days/p_hours patches on biometric runs.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or \
    "https://emplo-connect-1.preview.emergentagent.com"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"


# -------------------- fixtures --------------------
@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email"},
        timeout=15,
    )
    r.raise_for_status()
    dev = r.json().get("dev_code")
    assert dev, f"No dev_code: {r.json()}"
    v = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email", "code": dev},
        timeout=15,
    )
    v.raise_for_status()
    tok = v.json().get("session_token")
    assert tok, f"No token: {v.json()}"
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _pick_company_with_employees(h):
    """Return company_id of first firm having >=1 employee."""
    r = requests.get(f"{BASE_URL}/api/companies", headers=h, timeout=15)
    r.raise_for_status()
    companies = r.json().get("companies") or []
    for c in companies:
        cid = c.get("company_id")
        if not cid:
            continue
        u = requests.get(
            f"{BASE_URL}/api/admin/employees",
            params={"company_id": cid, "limit": 5},
            headers=h, timeout=15,
        )
        if u.status_code == 200:
            emps = u.json().get("employees") or u.json().get("users") or []
            if emps:
                return cid
    pytest.skip("No firm with employees available")


# -------------------- tests --------------------
class TestPDaysPHoursUnlockBiometric:
    """The critical test: biometric run MUST accept p_days & p_hours."""

    @pytest.fixture(scope="class")
    def biometric_run(self, h):
        cid = _pick_company_with_employees(h)
        payload = {
            "month": "2025-11",
            "company_id": cid,
            "attendance_source": "biometric",
        }
        r = requests.post(
            f"{BASE_URL}/api/admin/actual-salary-process",
            json=payload, headers=h, timeout=60,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        run = r.json()["run"]
        assert run.get("attendance_source") == "biometric"
        rows = run.get("rows") or []
        assert rows, "Biometric run produced no rows"
        return run

    def test_patch_p_days_on_biometric_run(self, h, biometric_run):
        run_id = biometric_run["run_id"]
        target = biometric_run["rows"][0]
        original_p_days = float(target.get("p_days") or 0.0)
        # Choose value clearly different from original but well below cap
        new_p_days = 15.0
        if abs(original_p_days - new_p_days) < 0.01:
            new_p_days = 10.0

        r = requests.patch(
            f"{BASE_URL}/api/admin/actual-salary-process/{run_id}/row",
            json={"user_id": target["user_id"], "p_days": new_p_days},
            headers=h, timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        row = r.json()["row"]
        cap = float(row.get("max_p_days") or 31)
        expected = min(new_p_days, cap)
        assert row["p_days"] == pytest.approx(expected, abs=0.01), (
            f"p_days on biometric run was NOT saved. "
            f"sent={new_p_days}, cap={cap}, expected={expected}, got={row['p_days']}"
        )

    def test_patch_p_hours_on_biometric_run(self, h, biometric_run):
        run_id = biometric_run["run_id"]
        target = biometric_run["rows"][0]
        new_p_hours = 120.0
        r = requests.patch(
            f"{BASE_URL}/api/admin/actual-salary-process/{run_id}/row",
            json={"user_id": target["user_id"], "p_hours": new_p_hours},
            headers=h, timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        row = r.json()["row"]
        assert row["p_hours"] == pytest.approx(new_p_hours, abs=0.01), (
            f"p_hours on biometric run was NOT saved. "
            f"sent={new_p_hours}, got={row['p_hours']}"
        )

    def test_patch_p_days_cap_enforced(self, h, biometric_run):
        """Send p_days=99 → server must cap to row.max_p_days."""
        run_id = biometric_run["run_id"]
        target = biometric_run["rows"][0]
        cap = float(target.get("max_p_days") or biometric_run.get("month_days") or 31)

        r = requests.patch(
            f"{BASE_URL}/api/admin/actual-salary-process/{run_id}/row",
            json={"user_id": target["user_id"], "p_days": 99.0},
            headers=h, timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        row = r.json()["row"]
        assert row["p_days"] == pytest.approx(cap, abs=0.01), (
            f"Cap not enforced. sent=99, cap={cap}, got={row['p_days']}"
        )

    def test_downstream_recompute(self, h, biometric_run):
        """After editing p_days, basic_salary/epf/net_pay must recompute."""
        run_id = biometric_run["run_id"]
        target = biometric_run["rows"][0]
        # Force recompute with a new p_days
        r = requests.patch(
            f"{BASE_URL}/api/admin/actual-salary-process/{run_id}/row",
            json={"user_id": target["user_id"], "p_days": 5.0},
            headers=h, timeout=20,
        )
        assert r.status_code == 200
        row = r.json()["row"]
        md = int(biometric_run.get("month_days") or 30)
        basic = float(row.get("basic") or 0)
        expected_basic_salary = round(basic * (min(5.0, float(row.get("max_p_days") or md)) / md), 2)
        assert row["basic_salary"] == pytest.approx(expected_basic_salary, abs=0.02), (
            f"basic_salary did NOT recompute. "
            f"expected={expected_basic_salary}, got={row['basic_salary']}"
        )
        expected_epf = round(0.12 * row["basic_salary"], 2)
        assert row["epf"] == pytest.approx(expected_epf, abs=0.02)


class TestPDaysPHoursManualRegression:
    """Manual run should keep working (regression)."""

    def test_patch_p_days_on_manual_run(self, h):
        cid = _pick_company_with_employees(h)
        payload = {
            "month": "2025-11",
            "company_id": cid,
            "attendance_source": "manual",
        }
        r = requests.post(
            f"{BASE_URL}/api/admin/actual-salary-process",
            json=payload, headers=h, timeout=60,
        )
        assert r.status_code == 200
        run = r.json()["run"]
        assert run["attendance_source"] == "manual"
        rows = run.get("rows") or []
        assert rows
        target = rows[0]

        r = requests.patch(
            f"{BASE_URL}/api/admin/actual-salary-process/{run['run_id']}/row",
            json={"user_id": target["user_id"], "p_days": 12.0, "p_hours": 96.0},
            headers=h, timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        row = r.json()["row"]
        cap = float(row.get("max_p_days") or 31)
        assert row["p_days"] == pytest.approx(min(12.0, cap), abs=0.01)
        assert row["p_hours"] == pytest.approx(96.0, abs=0.01)
