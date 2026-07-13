"""Iter 85 Review Verification — targeted backend tests for the 6 review items:

  1. Designation Master seed (>=17 Kankani designations)
  3. salary_mode-aware Actual Salary formulas (daily / monthly / hourly)
  4. Biometric source auto-transfer — p_days = total_days_int, p_hours = total_extra_hrs
  5. Compliance enabled_allowances honored end-to-end (rows have zeros for disabled heads)
  6. Regression — p_days / p_hours PATCH unlock still works for biometric run
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
KANKANI_ID = "cmp_cb39e488a0"


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
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
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email", "code": dev},
        timeout=15,
    )
    r.raise_for_status()
    tok = r.json().get("session_token")
    assert tok, r.json()
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# --------------------------------------------------------------------------
# 1. Designation Master seed
# --------------------------------------------------------------------------
class TestDesignationMaster:
    def test_kankani_designations_seeded(self, h):
        r = requests.get(
            f"{BASE_URL}/api/admin/masters",
            params={"type": "designation", "company_id": KANKANI_ID},
            headers=h, timeout=15,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        body = r.json()
        items = body.get("items") or []
        names = [(i.get("name") or "").strip().upper() for i in items]
        # Spec: >=17 designations
        assert len(items) >= 17, (
            f"Expected >=17 designations for Kankani, got {len(items)}: {names}"
        )
        # And uniqueness
        assert len(set(names)) == len(names), f"Duplicate names present: {names}"


# --------------------------------------------------------------------------
# 3. salary_mode-aware compute (unit-style; import server module)
# --------------------------------------------------------------------------
class TestSalaryModeCompute:
    """Verify _actual_salary_row_compute honors salary_mode for
    Actual Salary Process rows."""

    @pytest.fixture(scope="class")
    def compute(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from server import _actual_salary_row_compute
        return _actual_salary_row_compute

    def test_daily_mode_formula(self, compute):
        # Daily-rate 500 × 20 present days = 10000 basic_salary
        row = {
            "basic": 500.0, "duty_hrs": 8.0,
            "p_days": 20.0, "p_hours": 40.0,
            "oth_allo": 0.0, "adv": 0.0, "tds": 0.0,
            "salary_mode": "daily",
        }
        out = compute(dict(row), month_days=30)
        assert out["basic_salary"] == pytest.approx(10000.0, rel=0.001), (
            f"Daily: expected 500×20=10000, got {out['basic_salary']}"
        )
        # w_basic_salary = basic × p_hours / duty_hrs = 500 × 40 / 8 = 2500
        assert out["w_basic_salary"] == pytest.approx(2500.0, rel=0.001), (
            f"Daily w_basic_salary: expected 500×40/8=2500, got {out['w_basic_salary']}"
        )

    def test_hourly_mode_formula(self, compute):
        # Hourly-rate 100 × 40 p_hours = 4000
        row = {
            "basic": 100.0, "duty_hrs": 8.0,
            "p_days": 5.0, "p_hours": 40.0,
            "oth_allo": 0.0, "adv": 0.0, "tds": 0.0,
            "salary_mode": "hourly",
        }
        out = compute(dict(row), month_days=30)
        assert out["basic_salary"] == pytest.approx(4000.0, rel=0.001), (
            f"Hourly: expected 100×40=4000, got {out['basic_salary']}"
        )
        # For hourly, w_basic_salary == basic_salary
        assert out["w_basic_salary"] == out["basic_salary"], (
            f"Hourly w_basic_salary should equal basic_salary, "
            f"got {out['w_basic_salary']} vs {out['basic_salary']}"
        )

    def test_monthly_mode_regression(self, compute):
        # Monthly 30000 × (20/30) = 20000
        row = {
            "basic": 30000.0, "duty_hrs": 8.0,
            "p_days": 20.0, "p_hours": 0.0,
            "oth_allo": 0.0, "adv": 0.0, "tds": 0.0,
            "salary_mode": "monthly",
        }
        out = compute(dict(row), month_days=30)
        assert out["basic_salary"] == pytest.approx(20000.0, rel=0.001)


# --------------------------------------------------------------------------
# 3+4. Live Actual Salary Process for Kankani with biometric source
# --------------------------------------------------------------------------
class TestActualSalaryProcessLive:
    @pytest.fixture(scope="class")
    def run(self, h):
        payload = {
            "month": "2025-11",
            "company_id": KANKANI_ID,
            "attendance_source": "biometric",
        }
        r = requests.post(
            f"{BASE_URL}/api/admin/actual-salary-process",
            json=payload, headers=h, timeout=90,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        return r.json()["run"]

    @pytest.fixture(scope="class")
    def grid(self, h):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid/{KANKANI_ID}/2025-11",
            headers=h, timeout=60,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        return r.json()

    def test_biometric_p_days_matches_total_days_int(self, run, grid):
        """Feature #4 — Verify p_days/p_hours per row come from
        grid.totals.total_days_int / total_extra_hrs."""
        grid_by_user = {}
        for gr in grid.get("employees", []):
            grid_by_user[gr["user_id"]] = gr

        checked = 0
        mismatches = []
        for row in run.get("rows") or []:
            uid = row["user_id"]
            g = grid_by_user.get(uid)
            if not g:
                continue
            t = g.get("totals") or {}
            tdi = t.get("total_days_int")
            teh = t.get("total_extra_hrs")
            if tdi is None and teh is None:
                continue
            # DOJ / exit-date cap can trim p_days below tdi
            cap = float(row.get("max_p_days") or run.get("month_days") or 31)
            expected_p_days = min(float(tdi or 0.0), cap)
            actual_p_days = float(row.get("p_days") or 0.0)
            actual_p_hours = float(row.get("p_hours") or 0.0)

            if abs(actual_p_days - expected_p_days) > 0.01:
                mismatches.append(
                    f"uid={uid} p_days: expected≤{expected_p_days} (tdi={tdi},cap={cap}), got {actual_p_days}"
                )
            if teh is not None and abs(actual_p_hours - float(teh)) > 0.01:
                mismatches.append(
                    f"uid={uid} p_hours: expected {teh}, got {actual_p_hours}"
                )
            checked += 1

        assert checked > 0, "No overlap between run rows and grid rows — cannot verify"
        assert not mismatches, "Mismatches:\n" + "\n".join(mismatches[:10])

    def test_salary_mode_daily_rows_use_daily_formula(self, run):
        """Feature #3 — If a daily-mode row exists, verify basic_salary
        equals basic × p_days (no month_days divisor)."""
        daily_rows = [r for r in run.get("rows") or [] if str(r.get("salary_mode") or "").lower() == "daily"]
        if not daily_rows:
            pytest.skip("No daily-mode employees in Kankani for 2025-11")
        for r in daily_rows[:5]:
            basic = float(r.get("basic") or 0.0)
            p_days = float(r.get("p_days") or 0.0)
            expected = round(basic * p_days, 2)
            actual = float(r.get("basic_salary") or 0.0)
            assert abs(actual - expected) < 0.05, (
                f"Daily-mode row user_id={r.get('user_id')}: "
                f"basic={basic}, p_days={p_days}, expected basic_salary={expected}, got {actual}"
            )
            # And w_basic_salary = basic × p_hours / duty_hrs
            p_hours = float(r.get("p_hours") or 0.0)
            duty_hrs = float(r.get("duty_hrs") or 8.0)
            exp_w = round(basic * p_hours / duty_hrs, 2) if duty_hrs > 0 else 0.0
            act_w = float(r.get("w_basic_salary") or 0.0)
            assert abs(act_w - exp_w) < 0.05, (
                f"Daily row user_id={r.get('user_id')}: "
                f"expected w_basic_salary={exp_w}, got {act_w}"
            )

    def test_salary_mode_hourly_rows_use_hourly_formula(self, run):
        """Feature #3 — If an hourly-mode row exists, basic_salary = basic × p_hours."""
        hourly_rows = [r for r in run.get("rows") or [] if str(r.get("salary_mode") or "").lower() == "hourly"]
        if not hourly_rows:
            pytest.skip("No hourly-mode employees in Kankani for 2025-11")
        for r in hourly_rows[:5]:
            basic = float(r.get("basic") or 0.0)
            p_hours = float(r.get("p_hours") or 0.0)
            expected = round(basic * p_hours, 2)
            actual = float(r.get("basic_salary") or 0.0)
            assert abs(actual - expected) < 0.05, (
                f"Hourly row user_id={r.get('user_id')}: "
                f"basic={basic}, p_hours={p_hours}, expected={expected}, got {actual}"
            )

    # ---------- Feature #6 regression: PATCH p_days on biometric run ----------
    def test_patch_p_days_on_biometric_run(self, h, run):
        target = None
        for r in run.get("rows") or []:
            if float(r.get("max_p_days") or 0) >= 15:
                target = r
                break
        if not target:
            pytest.skip("No row with max_p_days >= 15 to safely test PATCH")
        run_id = run["run_id"]
        r = requests.patch(
            f"{BASE_URL}/api/admin/actual-salary-process/{run_id}/row",
            json={"user_id": target["user_id"], "p_days": 15.0},
            headers=h, timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        row_out = r.json()["row"]
        # Cap-aware: server clamps to min(15, max_p_days)
        cap = float(target.get("max_p_days") or 31)
        expected = min(15.0, cap)
        assert row_out["p_days"] == pytest.approx(expected, rel=0.001), (
            f"After PATCH: p_days expected {expected}, got {row_out['p_days']}"
        )


# --------------------------------------------------------------------------
# 5. Compliance Salary — enabled_allowances honored
# --------------------------------------------------------------------------
class TestComplianceEnabledAllowances:
    def test_toggle_basic_hra_only(self, h):
        # Read current policy
        cur = requests.get(
            f"{BASE_URL}/api/admin/companies/{KANKANI_ID}/compliance-policy",
            headers=h, timeout=15,
        )
        assert cur.status_code == 200
        prev = (cur.json() or {}).get("policy") or {}
        try:
            put = requests.put(
                f"{BASE_URL}/api/admin/companies/{KANKANI_ID}/compliance-policy",
                json={"enabled_allowances": ["basic", "hra"]},
                headers=h, timeout=15,
            )
            assert put.status_code == 200, put.text[:400]
            # Generate a compliance run
            r = requests.post(
                f"{BASE_URL}/api/admin/compliance-salary-runs",
                json={
                    "month": "2025-11", "company_id": KANKANI_ID,
                    "attendance_source": "biometric",
                },
                headers=h, timeout=90,
            )
            assert r.status_code == 200, r.text[:400]
            run = r.json()["run"]
            rows = run.get("rows") or []
            assert rows, "No rows produced"
            # First row should carry enabled_allowances=["basic","hra"]
            first = rows[0]
            ea = first.get("enabled_allowances")
            assert ea is not None, "enabled_allowances not on row"
            assert set(ea) == {"basic", "hra"}, f"enabled_allowances={ea}"
            for row in rows:
                for head in ("conveyance", "medical", "special", "others"):
                    val = float(row.get(head) or 0.0)
                    assert val == 0.0, (
                        f"Row uid={row.get('user_id')} head={head} expected 0, got {val}"
                    )
                # And basic/hra should still be present (>=0)
                assert float(row.get("basic") or 0) >= 0
        finally:
            # Restore
            restore = prev.get("enabled_allowances") or ["basic", "hra", "conveyance", "medical", "special", "others"]
            requests.put(
                f"{BASE_URL}/api/admin/companies/{KANKANI_ID}/compliance-policy",
                json={"enabled_allowances": restore},
                headers=h, timeout=15,
            )
