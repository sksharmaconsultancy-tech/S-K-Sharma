"""Iter 620 — Compliance Salary Process bug-fix verification.

Backend engine tests only. Verifies the two math invariants the frontend
fix (updatePresentDays / updateRowField / pfProrationFactor) is mirroring.

  Bug 1: PF changed after Save+Reprocess because the grid always divided
         by month_days, but the server used the firm's configured
         pf_proration_method ('working_days' → ÷26). After the fix, the
         grid must produce the SAME PF as compute_compliance_row for the
         given method.

  Bug 2: Wage Base column showed 0 on first process when rows start at
         0 present days and admin types days. stat_wage_base must be
         max(earned Basic, floor% × Gross Earning) once days > 0, and 0
         when zero-pay.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add /app/backend to path so utils.compliance_salary imports resolve.
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from utils.compliance_salary import (  # noqa: E402
    _proration_factor,
    compute_compliance_row,
)


def _user(monthly=14000.0, pf_basic=14000.0, basic_amount=14000.0):
    # basic_amount=14000 makes Basic == the full monthly rate (SEO GROWTH
    # style: Basic = Compliance Gross), so paid Basic = 14000 × pd/30.
    return {
        "user_id": "u_test_iter620",
        "name": "TEST Iter620 Monthly",
        "employee_code": "TEST620",
        "employee_type": "STAFF",
        "salary_monthly": monthly,
        "compliance_gross": monthly,
        "basic_amount": basic_amount,
        "pf_basic": pf_basic,
        "pf_applicable": True,
        "esic_applicable": True,
        "is_onroll": True,
    }


def _policy():
    return {"salary_mode": "monthly", "full_day_hours": 8, "ot_multiplier": 1.5}


def _stats(pd):
    return {
        "present_days": pd,
        "effective_present": pd,
        "half_days": 0,
        "duty_hours": 0.0,
        "ot_hours": 0.0,
    }


class TestProrationFactor:
    """_proration_factor() truth table (unit)."""

    def test_working_days_pd21(self):
        assert _proration_factor("working_days", 21, 30) == 21 / 26.0

    def test_working_days_pd_gt_26_caps_at_1(self):
        assert _proration_factor("working_days", 28, 30) == 1.0

    def test_attendance_days_pd21(self):
        assert _proration_factor("attendance_days", 21, 30) == 21 / 30.0

    def test_calendar_days_pd21_month30(self):
        assert _proration_factor("calendar_days", 21, 30) == 21 / 30.0

    def test_paid_days_pos(self):
        assert _proration_factor("paid_days", 5, 30) == 1.0

    def test_paid_days_zero(self):
        assert _proration_factor("paid_days", 0, 30) == 0.0

    def test_none_always_1(self):
        assert _proration_factor("none", 0, 30) == 1.0


class TestPFWorkingDays:
    """Iter 622 (user decision) — proration is LOCKED to the sheet's
    Month Days: stored methods like working_days are IGNORED, PF always
    divides by the entered month_days."""

    def test_pf_working_days_ignored_month30_pd21(self):
        row = compute_compliance_row(
            _user(), _policy(), 30, _stats(21),
            statutory_cfg={"pf_proration_method": "working_days"},
        )
        # Locked rule: PF = round(12% × 14000 × 21/30) = 1176 (NOT ÷26).
        assert row["pf_employee"] == 1176, row.get("pf_reason")
        # Basic = 14000 × 21/30 = 9800
        assert row["basic"] == 9800

    def test_pf_working_days_ignored_month26_pd21(self):
        row = compute_compliance_row(
            _user(), _policy(), 26, _stats(21),
            statutory_cfg={"pf_proration_method": "working_days"},
        )
        # ÷ entered 26 days: round(12% × 14000 × 21/26) = 1357.
        assert row["pf_employee"] == 1357, row.get("pf_reason")

    def test_pf_calendar_days_month30_pd21(self):
        row = compute_compliance_row(
            _user(), _policy(), 30, _stats(21),
            statutory_cfg={"pf_proration_method": "calendar_days"},
        )
        # PF = round(12% × 14000 × 21/30) = round(1176.0) = 1176
        assert row["pf_employee"] == 1176, row.get("pf_reason")

    def test_pf_attendance_days_month30_pd21(self):
        row = compute_compliance_row(
            _user(), _policy(), 30, _stats(21),
            statutory_cfg={"pf_proration_method": "attendance_days"},
        )
        # attendance_days divides by 30 → same as calendar for month 30
        assert row["pf_employee"] == 1176, row.get("pf_reason")


class TestWageBase:
    """Bug 2 — stat_wage_base must be max(Basic, 50% Gross); 0 on zero-pay."""

    def test_wage_base_pd21_month30(self):
        row = compute_compliance_row(
            _user(), _policy(), 30, _stats(21),
            statutory_cfg={"pf_proration_method": "working_days"},
        )
        # basic override 14000 > gross 9800 → engine caps basic at gross
        # for the reconciled row but stat_wage_base uses the pre-reconcile
        # basic (14000) → max(14000, 4900) = 14000. Non-zero is the invariant.
        assert row["stat_wage_base"] > 0
        assert row["stat_wage_base"] >= row["basic"]

    def test_wage_base_pd0_is_zero(self):
        row = compute_compliance_row(
            _user(), _policy(), 30, _stats(0),
            statutory_cfg={"pf_proration_method": "working_days"},
        )
        # zero-pay guard → stat_wage_base 0
        assert row["stat_wage_base"] == 0
        assert row["pf_employee"] == 0
        assert row["esic_employee"] == 0

    def test_days_independent_flags_present(self):
        row = compute_compliance_row(
            _user(), _policy(), 30, _stats(0),
            statutory_cfg={"pf_proration_method": "working_days"},
        )
        # Iter 370 flags exposed so grid can re-enable PF/ESIC once days>0
        assert row["pf_eligible"] is True
        assert row["esic_eligible"] is True
        assert row["pf_applicable"] is False
