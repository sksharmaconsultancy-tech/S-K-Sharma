"""Iter 626 — Daily-rated engine enhancement tests (user spec §12/§15).
Run alone: cd /app/backend && python -m pytest tests/test_iter626_daily_engine.py -q
"""
import sys

import pytest

sys.path.insert(0, "/app/backend")


def _daily_emp(rate=450.0, revisions=None):
    e = {
        "user_id": "u_d", "name": "RATAN", "compliance_gross": rate,
        "salary_structure_compliance": [
            {"head": "Basic Salary", "amount": rate, "rate_type": "daily"}],
        "pf_basic": rate, "pf_applicable": True, "esic_applicable": True,
        "compliance_basic": rate,
    }
    if revisions:
        e["daily_rate_revisions"] = revisions
    return e


def _stats(pd=20.0, ot=0.0):
    return {"present_days": pd, "effective_present": pd, "half_days": 0,
            "duty_hours": pd * 8, "ot_hours": ot}


def test_daily_450_x_20_with_calc_detail():
    from utils.compliance_salary import compute_compliance_row
    row = compute_compliance_row(_daily_emp(), {"full_day_hours": 8}, 30,
                                 _stats(20), statutory_cfg={},
                                 firm_pf_enabled=True, firm_esic_enabled=True)
    assert row["gross_paid"] == 9000            # 450 × 20 (no ÷ month days)
    assert row["pf_employee"] == 1080           # 12% × 9000
    assert row["esic_employee"] == round(9000 * 0.0075)  # 0.75%
    cd = row["calc_detail"]
    assert cd["salary_mode"] == "daily"
    assert cd["eligible_paid_days"] == 20
    assert cd["pf_basic_per_unit"] == 450
    assert cd["pf_monthly_equivalent"] == 13500  # 450 × 30 (ceiling check base)
    assert cd["pf_earned_wage"] == 9000
    assert cd["pf_contribution_wage"] == 9000
    assert cd["esic_coverage_wage"] == 13500     # full-month equivalent
    assert cd["esic_contribution_wage"] == 9000


def test_daily_ot_uses_policy_hours_and_multiplier():
    from utils.compliance_salary import compute_compliance_row
    row = compute_compliance_row(
        _daily_emp(), {"full_day_hours": 9, "ot_multiplier": 2.0}, 30,
        _stats(20, ot=9), statutory_cfg={},
        firm_pf_enabled=True, firm_esic_enabled=True)
    # per-hour 450/9=50 → OT 9h × 50 × 2.0 = 900
    assert row["ot_pay"] == 900
    assert row["calc_detail"]["ot_multiplier"] == 2.0
    # default head mapping: ESIC-on-OT follows the configurable head map
    assert row["calc_detail"]["esic_contribution_wage"] == row["esic_wage_base"]


def test_daily_pf_above_ceiling_keeps_adopted_higher_rule():
    """Iter 456 rule preserved: PF Basic filled ABOVE ₹15,000 ceiling on the
    Master = ADOPTED HIGHER PF → PF on full earned wage, no cap."""
    from utils.compliance_salary import compute_compliance_row
    row = compute_compliance_row(_daily_emp(rate=800), {"full_day_hours": 8},
                                 30, _stats(26), statutory_cfg={},
                                 firm_pf_enabled=True, firm_esic_enabled=False)
    assert row["calc_detail"]["pf_earned_wage"] == 20800
    assert row["calc_detail"]["pf_monthly_equivalent"] == 24000  # > ceiling
    assert row["calc_detail"]["pf_contribution_wage"] == row["pf_wages"]
    assert row["pf_employee"] == round(row["pf_wages"] * 0.12)


@pytest.mark.parametrize("grid,expected_factor", [
    # punch dates: 10 days at base 450 (01-15 window) + 10 days at 500
    ({"days": {f"2026-08-{d:02d}": {"hours": 8} for d in
               list(range(1, 11)) + list(range(16, 26))}},
     (10 * 450 + 10 * 500) / (20 * 450.0)),
    # no punches → calendar-proportional: 15 days @450 + 16 days @500 over 31
    (None, (15 * 450 + 16 * 500) / (31 * 450.0)),
])
def test_mid_month_rate_revision(grid, expected_factor):
    import server  # noqa: F401  (break circular import)
    from routes.compliance_salary_runs import _apply_daily_rate_revisions
    emp = _daily_emp(rate=450, revisions=[
        {"effective_from": "2026-08-16", "rate": 500}])
    scaled, audit = _apply_daily_rate_revisions(emp, "2026-08", 31, grid)
    assert audit is not None
    assert abs(audit["weighted_factor"] - expected_factor) < 0.0001
    head = scaled["salary_structure_compliance"][0]
    assert abs(head["amount"] - 450 * expected_factor) < 0.01
    assert abs(scaled["pf_basic"] - 450 * expected_factor) < 0.01
    # original emp untouched (historical safety)
    assert emp["salary_structure_compliance"][0]["amount"] == 450


def test_monthly_employee_unaffected():
    import server  # noqa: F401  (break circular import)
    from routes.compliance_salary_runs import _apply_daily_rate_revisions
    from utils.compliance_salary import compute_compliance_row
    memp = {"user_id": "u_m", "compliance_gross": 14000,
            "salary_structure_compliance": [
                {"head": "Basic Salary", "amount": 14000, "rate_type": "monthly"}],
            "pf_basic": 14000, "pf_applicable": True,
            "daily_rate_revisions": [{"effective_from": "2026-08-16", "rate": 500}]}
    same, audit = _apply_daily_rate_revisions(memp, "2026-08", 31, None)
    assert audit is None and same is memp  # monthly → no change (regression)
    row = compute_compliance_row(memp, {"full_day_hours": 8}, 30,
                                 {"present_days": 21, "effective_present": 21,
                                  "half_days": 0, "duty_hours": 168, "ot_hours": 0},
                                 statutory_cfg={}, firm_pf_enabled=True,
                                 firm_esic_enabled=False)
    assert row["basic"] == 9800 and row["pf_employee"] == 1176  # Iter 622 rule intact
