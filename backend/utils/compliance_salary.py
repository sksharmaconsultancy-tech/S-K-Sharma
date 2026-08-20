"""Compliance Salary Process — dedicated statutory-deductions payroll engine.

Runs completely separate from the base salary process (``salary_run.py``).
This one owns the *statutory* side of payroll under the new Labour Codes
(2019/20): PF, ESIC, Professional Tax (PT), and TDS.

Salary structure per employee (detailed):
    Basic + HRA + Conveyance + Medical + Special allowance + Others
Every component may be:
    (a) an explicit ₹ amount stored on the employee doc, OR
    (b) derived from a company-level % of the monthly gross ("structure_pct"),
    OR
    (c) a fallback to sensible defaults.

New Labour Code rule for PF & ESIC (per user's directive):
    STATUTORY WAGE BASE = max(Basic, 50% of Gross Earning)
    This single base is used for BOTH Provident Fund and ESIC. It is
    capped at ₹15,000/month for PF only.

    * Employee PF = 12% of min(stat_wage_base, 15000).
    * Employer PF = 12% of the same, split 3.67% EPF + 8.33% EPS.
    * ESIC applies only when monthly Gross Earning ≤ ₹21,000.
      Employee 0.75%, Employer 3.25% — both computed on the same
      stat_wage_base.
    * PT is state-based (monthly slab) with per-employee override.
    * TDS is a manual monthly ₹ amount entered per-employee.
    * Employees can be marked pf_applicable=False or esic_applicable=False
      (e.g. Labour on certain rolls).

Advance / loan deductions are intentionally NOT applied here — they live
on the base salary process (``salary_run.py``). Two separate runs, two
separate payslip artefacts.
"""
from __future__ import annotations

import csv
from datetime import datetime
import io
import math
import re
from typing import Any, Dict, List, Optional

from utils.relation import father_or_spouse_display as _father_or_spouse

# --------------------------------------------------------------------------- 
# Structure defaults — % of monthly gross when no override on the employee.
# Admin can also override these at company level via the run body.
# Together they should sum to 100%. Others is a residual.
# --------------------------------------------------------------------------- 
DEFAULT_STRUCTURE_PCT: Dict[str, float] = {
    "basic": 40.0,
    "hra": 20.0,
    "conveyance": 5.0,
    "medical": 3.0,
    "special": 32.0,   # residual
    "others": 0.0,
}

# --------------------------------------------------------------------------- 
# Statutory rate defaults (all editable via run body)
# --------------------------------------------------------------------------- 
DEFAULT_STATUTORY_CFG: Dict[str, Any] = {
    # PF (new labour code)
    "pf_percent_employee": 12.0,
    "pf_percent_employer_epf": 3.67,
    "pf_percent_employer_eps": 8.33,
    "pf_wage_cap": 15000.0,

    # Iter 160 — EPF Act employer charges (monthly challan accounts):
    #   A/c 2  — EPF Admin Charges  0.50% (min ₹500/month statutory)
    #   A/c 21 — EDLI Contribution  0.50% (on EDLI wages, capped ₹15,000)
    #   A/c 22 — EDLI Admin Charges 0.00% (NIL since 01-04-2017)
    "pf_admin_percent": 0.5,
    "pf_edli_percent": 0.5,
    "pf_edli_admin_percent": 0.0,

    # ESIC
    "esic_percent_employee": 0.75,
    "esic_percent_employer": 3.25,
    "esic_gross_threshold": 21000.0,

    # Shared statutory wage-base rule (new labour code, per client policy):
    # PF & ESIC apply on max(Basic, floor_pct% of Gross Earning).
    "stat_wage_floor_pct": 50.0,

    # Iter 127f — whole-rupee rounding (statutory practice: PF nearest
    # rupee, ESIC rounded UP to the next rupee).
    "pf_rounding": "nearest",     # nearest | ceil | floor | none
    "esic_rounding": "ceil",      # ceil | nearest | floor | none

    # Iter 387 (user request — configurable statutory module, global OR
    # per-firm). Defaults REPLICATE the pre-387 behaviour exactly.
    "pf_enabled": True,                      # module-level PF Applicable
    "esic_enabled": True,                    # module-level ESIC Applicable
    # Wage Definition Rule = the max(Basic, floor% of Gross) floor.
    "wage_definition_rule_enabled": True,
    # When False, employees stay ESIC-covered even above the ceiling.
    "esic_disable_above_ceiling": True,
    "pf_proration_method": "calendar_days",
    "esic_proration_method": "calendar_days",
    "rule_version": "",                      # free label, e.g. "FY 2026-27 v1"
    # Iter 408 (user spec) — Higher PF / VPF company policy (Company Master).
    "allow_higher_pf": True,    # Iter 425b — informational only; engine no
                                # longer gates Higher PF on this switch.
    "allow_vpf": True,          # permit Voluntary PF (employee side only)
    "vpf_max_percent": 0.0,     # 0 = no company limit on VPF %
    # Iter 597 (user spec) — Contractor PF Calculation Rule (PF Settings):
    #   standard              → existing EPF calculation (default)
    #   contractor_wage_based → PF strictly on the EARNED Basic+DA:
    #     earned ≥ ceiling → PF wage = ceiling; earned < ceiling (LOP /
    #     partial month / mid-month join-exit) → PF on the ACTUAL earned wage.
    "contractor_pf_mode": "standard",
    # Sub-rule for Adopt-PF employees during PARTIAL months (contractor mode):
    #   adopted_wage → continue on the FIXED adopted wage regardless of
    #                  attendance (company policy, default per user spec)
    #   earned_wage  → PF on the actual earned adopted wage (recommended)
    "contractor_partial_month_rule": "adopted_wage",
    # head_mapping default is None → DEFAULT_HEAD_MAPPING applies.
}

_ROUNDING_KEYS = ("pf_rounding", "esic_rounding")

# Iter 387 — Salary Head Mapping: which earning heads count as PF / ESIC
# wages. Admin-editable in Standard Compliance Settings (global or firm).
# NOTE (user-confirmed Iter 129/385 rules kept): PF amounts always derive
# from the Employee Master "PF Basic Salary"; the PF flags feed the
# validation/AI-explanation layers. ESIC flags drive the ESIC wage base
# whenever the Wage Definition Rule is switched OFF.
STATUTORY_HEAD_KEYS = ("basic", "hra", "conveyance", "medical", "special", "others", "ot")
DEFAULT_HEAD_MAPPING: Dict[str, Dict[str, bool]] = {
    "basic": {"pf": True, "esic": True},
    "hra": {"pf": False, "esic": True},
    "conveyance": {"pf": False, "esic": True},
    "medical": {"pf": False, "esic": True},
    "special": {"pf": False, "esic": True},
    "others": {"pf": False, "esic": True},
    "ot": {"pf": False, "esic": True},
}

PRORATION_METHODS = ("calendar_days", "paid_days", "attendance_days", "working_days", "none")

# cfg keys passed through as-is (not coerced to float) when merging.
_CFG_PASSTHRU_KEYS = (
    "pf_enabled", "esic_enabled", "wage_definition_rule_enabled",
    "esic_disable_above_ceiling", "pf_proration_method",
    "esic_proration_method", "rule_version", "head_mapping", "_salary_month",
    # Iter 408 — Higher PF / VPF company policy flags.
    "allow_higher_pf", "allow_vpf",
    # Iter 597 — Contractor PF Calculation Rule.
    "contractor_pf_mode", "contractor_partial_month_rule",
)


def _proration_factor(method: str, effective_present: float, month_days: int) -> float:
    """Iter 387 — configurable proration for monthly-rated staff.

    calendar_days → present ÷ days-in-month (pre-387 behaviour, default)
    working_days  → present ÷ 26
    attendance_days → present ÷ 30 (fixed 30-day divisor)
    paid_days     → full wages whenever ANY day is paid
    none          → never prorated
    """
    m = (method or "calendar_days").strip().lower()
    if m == "none":
        return 1.0
    if m == "paid_days":
        return 1.0 if effective_present > 0 else 0.0
    if m == "working_days":
        div = 26.0
    elif m == "attendance_days":
        div = 30.0
    else:
        div = float(max(1, month_days))
    return min(1.0, effective_present / div) if div > 0 else 0.0

# Iter 162 — column catalog for the customisable v2 register PDF.
# key -> (default heading, default width unit, numeric?)
# Iter 273 (user request) — Format 2: Employee Code + UAN/ESI columns
# removed; name shows Father/Spouse; Basic/HRA/Conv. come from the MASTER
# (full-month) salary; Days sits after the earning heads, then GROSS and
# the deductions part; Signature column at the end.
V2_REGISTER_COLUMNS: List[Any] = [
    ("sno", "S.No", 7, False),
    ("name", "Employee / Father-Spouse Name", 44, False),
    ("desig", "Desig.", 18, False),
    # Iter 322 (user request) — statutory ID columns on Format 2.
    ("uan", "UAN No.", 15, False),
    ("pf_no", "EPF No.", 14, False),
    ("esi_no", "ESIC No.", 14, False),
    ("basic", "Basic", 13, True),
    ("hra", "HRA", 12, True),
    ("conv", "Conv.", 12, True),
    ("other_earn", "Other", 12, True),
    ("days", "Days", 8, True),
    ("gross", "GROSS", 15, True),
    ("pf", "PF", 12, True),
    ("esi", "ESI", 11, True),
    # Iter 489 (user bug) — Advance has its OWN column (was inside Other).
    ("advance", "Advance", 12, True),
    ("other_ded", "Other Ded.", 12, True),
    ("tds", "TDS", 11, True),
    ("total_ded", "TOTAL DED.", 15, True),
    ("net", "NET PAY", 15, True),
    ("sign", "Signature", 18, False),
]


def _round_stat(v: float, mode: str) -> float:
    """Whole-rupee statutory rounding."""
    if mode == "ceil":
        return float(math.ceil(v - 1e-9))
    if mode == "floor":
        return float(math.floor(v + 1e-9))
    if mode == "nearest":
        return float(round(v))
    return round(v, 2)

# --------------------------------------------------------------------------- 
# Professional Tax — monthly ₹ per state. Simplified flat monthly amounts.
# Admins can override per-employee with `pt_amount_override`.
# --------------------------------------------------------------------------- 
# ---------------------------------------------------------------------------
# Iter 178 — STATE-WISE PT SLABS (monthly gross → monthly PT ₹).
# `upto: None` means "and above". Set on the FIRM via
# compliance_policy.pt_state; per-employee override still wins.
# ---------------------------------------------------------------------------
PT_STATE_SLABS: Dict[str, List[Dict[str, Any]]] = {
    "Maharashtra": [{"upto": 7500, "amount": 0}, {"upto": 10000, "amount": 175}, {"upto": None, "amount": 200}],
    "Karnataka": [{"upto": 24999, "amount": 0}, {"upto": None, "amount": 200}],
    "West Bengal": [{"upto": 10000, "amount": 0}, {"upto": 15000, "amount": 110}, {"upto": 25000, "amount": 130}, {"upto": 40000, "amount": 150}, {"upto": None, "amount": 200}],
    "Madhya Pradesh": [{"upto": 18750, "amount": 0}, {"upto": 25000, "amount": 125}, {"upto": 33333, "amount": 167}, {"upto": None, "amount": 208}],
    "Gujarat": [{"upto": 11999, "amount": 0}, {"upto": None, "amount": 200}],
    "Telangana": [{"upto": 15000, "amount": 0}, {"upto": 20000, "amount": 150}, {"upto": None, "amount": 200}],
    "Andhra Pradesh": [{"upto": 15000, "amount": 0}, {"upto": 20000, "amount": 150}, {"upto": None, "amount": 200}],
    "Tamil Nadu": [{"upto": 3500, "amount": 0}, {"upto": 5000, "amount": 22}, {"upto": 7500, "amount": 52}, {"upto": 10000, "amount": 115}, {"upto": 12500, "amount": 171}, {"upto": None, "amount": 208}],
    "Kerala": [{"upto": 1999, "amount": 0}, {"upto": 2999, "amount": 20}, {"upto": 4999, "amount": 30}, {"upto": 7499, "amount": 50}, {"upto": 9999, "amount": 75}, {"upto": 12499, "amount": 100}, {"upto": 16666, "amount": 125}, {"upto": 20833, "amount": 166}, {"upto": None, "amount": 208}],
    "Bihar": [{"upto": 25000, "amount": 0}, {"upto": 41666, "amount": 83.33}, {"upto": 83333, "amount": 166.67}, {"upto": None, "amount": 208.33}],
    "Jharkhand": [{"upto": 25000, "amount": 0}, {"upto": 41666, "amount": 100}, {"upto": 66666, "amount": 150}, {"upto": 83333, "amount": 175}, {"upto": None, "amount": 208}],
    "Odisha": [{"upto": 13304, "amount": 0}, {"upto": 25000, "amount": 125}, {"upto": None, "amount": 200}],
    "Assam": [{"upto": 10000, "amount": 0}, {"upto": 15000, "amount": 150}, {"upto": 25000, "amount": 180}, {"upto": None, "amount": 208}],
    "Punjab": [{"upto": 20833, "amount": 0}, {"upto": None, "amount": 200}],
    "Sikkim": [{"upto": 20000, "amount": 0}, {"upto": 30000, "amount": 125}, {"upto": 40000, "amount": 150}, {"upto": None, "amount": 200}],
    "Meghalaya": [{"upto": 4166, "amount": 0}, {"upto": 6250, "amount": 16.5}, {"upto": 8333, "amount": 25}, {"upto": 12500, "amount": 41.5}, {"upto": 16666, "amount": 62.5}, {"upto": 20833, "amount": 83.33}, {"upto": 25000, "amount": 104.16}, {"upto": 29166, "amount": 125}, {"upto": 33333, "amount": 150}, {"upto": 37500, "amount": 175}, {"upto": 41666, "amount": 200}, {"upto": None, "amount": 208}],
    "Tripura": [{"upto": 7500, "amount": 0}, {"upto": 15000, "amount": 150}, {"upto": None, "amount": 208}],
    # States/UTs with NO Professional Tax:
    "Rajasthan": [], "Delhi": [], "Haryana": [], "Uttar Pradesh": [],
    "Uttarakhand": [], "Himachal Pradesh": [], "Chandigarh": [],
    "Jammu & Kashmir": [], "Goa": [{"upto": 15000, "amount": 0}, {"upto": 25000, "amount": 150}, {"upto": None, "amount": 200}],
    "Chhattisgarh": [{"upto": 12500, "amount": 0}, {"upto": 16667, "amount": 150}, {"upto": 20833, "amount": 180}, {"upto": None, "amount": 208}],
}


def pt_from_slabs(monthly_gross: float, slabs: List[Dict[str, Any]]) -> float:
    """Monthly PT ₹ for a monthly gross using {upto, amount} slabs."""
    g = _num(monthly_gross, 0.0)
    for s in slabs or []:
        upto = s.get("upto")
        if upto is None or g <= _num(upto, 0.0):
            return round(_num(s.get("amount"), 0.0), 2)
    return 0.0


PT_STATE_MONTHLY: Dict[str, float] = {
    "Maharashtra": 200.0,    "Karnataka": 200.0,
    "West Bengal": 200.0,
    "Gujarat": 200.0,
    "Tamil Nadu": 208.0,        # ~₹1,250 half-yearly / 6
    "Telangana": 200.0,
    "Andhra Pradesh": 200.0,
    "Madhya Pradesh": 208.0,    # ~₹2,500 annually / 12
    "Kerala": 208.0,
    "Odisha": 200.0,
    "Assam": 208.0,
    "Bihar": 208.0,
    "Punjab": 200.0,
    "Delhi": 0.0,               # no PT in Delhi
    "Uttar Pradesh": 0.0,       # no PT in UP
    "Rajasthan": 0.0,           # no PT in Rajasthan
    "Haryana": 0.0,             # no PT in Haryana
    "Chandigarh": 0.0,
    "None": 0.0,
}


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


# --------------------------------------------------------------------------- 
# Salary structure
# --------------------------------------------------------------------------- 
def resolve_structure(
    user: Dict[str, Any],
    monthly_gross: float,
    company_structure_pct: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """Split ``monthly_gross`` into the six components for an employee.

    Precedence:
      1. Explicit per-employee ₹ overrides — ``basic_amount``, ``hra_amount``,
         ``conv_amount``, ``medical_amount``, ``special_amount``,
         ``others_amount``. If ANY of these are set, we use ALL that are
         present and put the residual into ``special`` (so total == gross).
      2. Per-employee percentages — ``structure_pct: {basic, hra, ...}``.
      3. Company-level percentages passed in ``company_structure_pct``.
      4. ``DEFAULT_STRUCTURE_PCT``.
    """
    keys = ["basic", "hra", "conveyance", "medical", "special", "others"]
    monthly_gross = round(monthly_gross, 2)

    # 0) Iter 91 — Highest precedence: the per-employee structure saved on
    #    the Employee Master via the Salary Update modal
    #    (``salary_structure_compliance`` rows).  Basic ALWAYS comes from
    #    the updated master when a structure with a Basic head exists.
    #    PF/ESI *Employer* rows are excluded (not part of the gross split).
    rows = user.get("salary_structure_compliance") or []
    if isinstance(rows, list) and rows:
        def _head_key(h: Any) -> Optional[str]:
            s = str(h or "").strip().lower()
            if not s or "employer" in s:
                return None
            if s.startswith("basic"):
                return "basic"
            if "hra" in s:
                return "hra"
            if s.startswith("conv"):
                return "conveyance"
            if "medic" in s:
                return "medical"
            if "special" in s:
                return "special"
            return "others"
        mapped: Dict[str, float] = {k: 0.0 for k in keys}
        for row in rows:
            if not isinstance(row, dict):
                continue
            k = _head_key(row.get("head"))
            if not k:
                continue
            mapped[k] += _num(row.get("amount"), 0.0)
        if mapped["basic"] > 0:
            return {k: round(v, 2) for k, v in mapped.items()}

    # 1) Any explicit ₹ overrides on the employee doc?
    override_keys = {
        "basic": user.get("basic_amount"),
        "hra": user.get("hra_amount"),
        "conveyance": user.get("conv_amount"),
        "medical": user.get("medical_amount"),
        "special": user.get("special_amount"),
        "others": user.get("others_amount"),
    }
    has_amount_override = any(v is not None and _num(v, -1) >= 0 for v in override_keys.values())
    if has_amount_override:
        out: Dict[str, float] = {k: _num(override_keys.get(k), 0.0) for k in keys}
        # residual → special
        allocated = sum(out.values())
        if allocated < monthly_gross:
            out["special"] += round(monthly_gross - allocated, 2)
        # Cap at gross (don't overshoot)
        elif allocated > monthly_gross:
            # shrink special first
            excess = allocated - monthly_gross
            out["special"] = max(0.0, out["special"] - excess)
        return {k: round(v, 2) for k, v in out.items()}

    # 2/3/4) percentage-based
    pcts_source: Dict[str, float] = {}
    per_emp_pct = user.get("structure_pct") or {}
    if isinstance(per_emp_pct, dict) and any(k in per_emp_pct for k in keys):
        pcts_source = {k: _num(per_emp_pct.get(k), 0.0) for k in keys}
    elif company_structure_pct:
        pcts_source = {k: _num(company_structure_pct.get(k), 0.0) for k in keys}
    else:
        pcts_source = dict(DEFAULT_STRUCTURE_PCT)

    total_pct = sum(pcts_source.values())
    if total_pct <= 0:
        pcts_source = dict(DEFAULT_STRUCTURE_PCT)
        total_pct = sum(pcts_source.values())

    # Normalise to 100 to protect against operator error.
    scale = 100.0 / total_pct
    parts: Dict[str, float] = {}
    running = 0.0
    for i, k in enumerate(keys):
        pct = pcts_source[k] * scale
        if i == len(keys) - 1:
            # last key soaks the rounding delta
            parts[k] = round(monthly_gross - running, 2)
        else:
            v = round(monthly_gross * pct / 100.0, 2)
            parts[k] = v
            running += v
    return parts


# --------------------------------------------------------------------------- 
# Main compute
# --------------------------------------------------------------------------- 
def compute_compliance_row(
    user: Dict[str, Any],
    policy: Dict[str, Any],
    month_days: int,
    stats: Dict[str, float],
    company_structure_pct: Optional[Dict[str, float]] = None,
    statutory_cfg: Optional[Dict[str, float]] = None,
    firm_pf_enabled: bool = True,
    firm_esic_enabled: bool = True,
    firm_pt: Optional[Dict[str, Any]] = None,
    enabled_allowances: Optional[set] = None,
    custom_allowance_labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Compute the full compliance salary row for a single employee.

    Args (same shape as ``compute_salary_row``):
        user: Employee doc.
        policy: Merged attendance/pay policy (from user.employee_policy).
        month_days: Divisor for pro-ration when salary_mode='monthly'.
        stats: { present_days, half_days, effective_present, duty_hours, ot_hours }.
        enabled_allowances: Iter 630 (user spec) — Firm-Master allowance
            mask. When given, editable heads NOT in the set calculate as 0
            INSIDE the engine (Basic is never masked); stored master values
            are untouched. None = no catalog configured → no masking.
    """
    cfg = dict(DEFAULT_STATUTORY_CFG)
    if statutory_cfg:
        for k, v in statutory_cfg.items():
            if v is None:
                continue
            if k in _ROUNDING_KEYS:
                cfg[k] = str(v)
            elif k in _CFG_PASSTHRU_KEYS:
                # Iter 387 — bool / enum / dict settings pass through as-is.
                cfg[k] = v
            else:
                cfg[k] = _num(v)

    salary_mode = (policy.get("salary_mode") or "monthly").lower()
    # Iter 471 (user bug — RATAN LAL: daily rate 450 × 20 days must be
    # ₹9,000, not 450 × 20 ÷ 31) — the Employee Master's "Rate Basis
    # (Compliance)" (Monthly / Daily / Hourly) governs THIS engine and WINS
    # over the Actual-salary cadence carried on employee_policy. Falls back
    # to the compliance structure's Basic row rate_type.
    _cmode = str(user.get("compliance_salary_mode") or "").strip().lower()
    if _cmode not in ("daily", "hourly", "monthly"):
        _cmode = ""
        for _r in (user.get("salary_structure_compliance") or []):
            if isinstance(_r, dict) and str(_r.get("head", "")).strip().lower().startswith("basic"):
                _rt = str(_r.get("rate_type") or "").strip().lower()
                if _rt in ("daily", "hourly", "monthly"):
                    _cmode = _rt
                break
    if _cmode:
        salary_mode = _cmode
    # Iter 68 — Two salary structures on the employee master:
    #   * ``compliance_gross`` (aka Govt Salary) → used ONLY by the
    #     Compliance Salary Process for statutory calc (PF/ESIC/TDS/PT).
    #   * ``salary_monthly`` (aka Actual Salary) → used by the Base Salary
    #     Run + biometric-attendance-driven proration.  Retains the
    #     historical name for backward compatibility.
    # When ``compliance_gross`` is missing we fall back to ``salary_monthly``.
    rate = _num(
        policy.get("salary")
        or user.get("compliance_gross")
        or user.get("salary_monthly"),
        0.0,
    )
    # Iter 306 (user bug #7 — "Master Rates not Showing") — employees
    # imported with ONLY a salary structure (e.g. Kankani daily-rated
    # workers) have none of the fields above, so every compliance run —
    # and therefore the Salary Register / register PDF — showed Rate 0.
    # Fall back to the structure's "Basic …" row and honour its
    # rate_type (daily / hourly / monthly).
    if rate <= 0:
        for _r in (user.get("salary_structure_actual") or []):
            if isinstance(_r, dict) and str(_r.get("head", "")).strip().lower().startswith("basic"):
                if _num(_r.get("amount"), 0.0) > 0:
                    rate = _num(_r.get("amount"), 0.0)
                    _rt = str(_r.get("rate_type") or "").strip().lower()
                    if _rt in ("monthly", "daily", "hourly"):
                        salary_mode = _rt
                break

    effective_present = float(stats.get("effective_present", stats.get("present_days", 0)))
    duty_hours = float(stats.get("duty_hours", 0.0))
    ot_hours = float(stats.get("ot_hours", 0.0))
    # Iter 219 (user request) — SHOW HALF DAYS: the sheet's Present Days
    # column is the effective present (full days + 0.5 × half days),
    # kept in half-day steps (e.g. 18.5) instead of a truncated integer.
    present_days = round(effective_present * 2) / 2.0
    half_days = int(stats.get("half_days", 0))

    full_day_hours = _num(policy.get("full_day_hours"), 8.0)

    # ---- Monthly gross (only what statutory acts on) ----
    if salary_mode == "daily":
        monthly_gross = rate * effective_present
    elif salary_mode == "hourly":
        monthly_gross = rate * duty_hours
    else:
        monthly_gross = _safe_div(rate * effective_present, max(1, month_days))

    # Overtime and tier bonuses are tracked separately — they are NOT
    # counted as "wages" for PF/PT purposes under new labour code but ARE
    # counted for ESIC (as they form part of gross paid).
    per_hour_rate = 0.0
    if salary_mode == "hourly":
        per_hour_rate = rate
    elif salary_mode == "daily":
        per_hour_rate = _safe_div(rate, full_day_hours)
    else:
        per_hour_rate = _safe_div(rate, max(1, month_days) * full_day_hours)
    ot_multiplier = _num(policy.get("ot_multiplier"), 1.5)
    ot_pay = ot_hours * per_hour_rate * ot_multiplier
    # Iter 406 (user rule — "Gross Earning includes OT") — freeze-import
    # difference allocated to OVERTIME lands INSIDE the compute so the
    # PF / ESIC / PT wage bases are calculated on the FULL Gross Earning
    # including OT (previously it was bolted on after the statutory calc).
    ot_pay += _num(stats.get("ot_pay_extra"), 0.0)

    # ---- Structure split ----
    # Iter 126g — explicit "Compliance Basic Salary" from the Employee
    # Master: feeds the structure split as the highest-precedence basic
    # (pro-rated by attendance for monthly-rated staff) unless the master
    # already carries an explicit basic override / structure rows.
    # Iter 127c — the Firm-Master-linked allowance heads saved on the
    # Employee Master (``compliance_salary_allowances``) are now part of
    # the compliance gross: when present, gross = Basic + Σ allowances
    # (pro-rated) and each head maps into its structure column.
    allow_rows = [
        r for r in (user.get("compliance_salary_allowances") or [])
        if isinstance(r, dict) and _num(r.get("amount"), 0.0) > 0
    ]
    allowances_master = sum(_num(r.get("amount"), 0.0) for r in allow_rows)
    comp_basic = _num(user.get("compliance_basic"), 0.0)
    master_user = user           # for the full-month "Master" columns
    master_gross_override: Optional[float] = None
    if comp_basic > 0 and not user.get("basic_amount") and not (user.get("salary_structure_compliance") or []):
        # Iter 471 — DAILY / HOURLY rate basis: the master's compliance
        # amounts are PER-DAY / PER-HOUR figures, so the earned value is
        # amount × present days (or duty hours); the full-month "Master"
        # columns scale by the month's days (× daily hours).
        if salary_mode == "daily":
            factor = effective_present
        elif salary_mode == "hourly":
            factor = duty_hours
        else:
            factor = _safe_div(effective_present, max(1, month_days))
        _master_mult = (float(month_days) if salary_mode == "daily"
                        else float(month_days) * full_day_hours
                        if salary_mode == "hourly" else 1.0)
        prorated_basic = comp_basic * factor
        if allowances_master > 0:
            # Master structure is authoritative — rebuild the gross
            # bottom-up (also fixes gross=0 when compliance_gross/salary
            # was left blank on the master).
            agg = {"hra": 0.0, "conveyance": 0.0, "medical": 0.0,
                   "special": 0.0, "others": 0.0}
            for r in allow_rows:
                s = str(r.get("head") or "").strip().lower()
                amt = _num(r.get("amount"), 0.0)
                if "hra" in s or "house" in s:
                    agg["hra"] += amt
                elif s.startswith("conv") or "travel" in s:
                    agg["conveyance"] += amt
                elif "medic" in s:
                    agg["medical"] += amt
                elif "special" in s:
                    agg["special"] += amt
                else:
                    agg["others"] += amt
            monthly_gross = (comp_basic + allowances_master) * factor
            user = {
                **user,
                "basic_amount": round(prorated_basic, 2),
                "hra_amount": round(agg["hra"] * factor, 2),
                "conv_amount": round(agg["conveyance"] * factor, 2),
                "medical_amount": round(agg["medical"] * factor, 2),
                "special_amount": round(agg["special"] * factor, 2),
                "others_amount": round(agg["others"] * factor, 2),
            }
            master_user = {
                **master_user,
                "basic_amount": round(comp_basic * _master_mult, 2),
                "hra_amount": round(agg["hra"] * _master_mult, 2),
                "conv_amount": round(agg["conveyance"] * _master_mult, 2),
                "medical_amount": round(agg["medical"] * _master_mult, 2),
                "special_amount": round(agg["special"] * _master_mult, 2),
                "others_amount": round(agg["others"] * _master_mult, 2),
            }
            master_gross_override = (comp_basic + allowances_master) * _master_mult
        else:
            user = {**user, "basic_amount": round(min(prorated_basic, monthly_gross) if monthly_gross > 0 else prorated_basic, 2)}
            master_user = {**master_user, "basic_amount": round(comp_basic * _master_mult, 2)}
            if monthly_gross <= 0:
                # No compliance_gross/salary on the master — Basic IS the gross.
                monthly_gross = prorated_basic
                master_gross_override = comp_basic * _master_mult
    structure = resolve_structure(user, monthly_gross, company_structure_pct)
    # Iter 471 — DAILY / HOURLY rate basis with saved compliance structure
    # rows: the row amounts are PER-DAY / PER-HOUR figures, so the EARNED
    # heads (and the max(Basic, 50% Gross) wage-base floor below) must use
    # amount × present days (or duty hours).
    _sc_rows_471 = user.get("salary_structure_compliance") or []
    _sc_basic_471 = sum(
        _num(_r.get("amount"), 0.0) for _r in _sc_rows_471
        if isinstance(_r, dict)
        and str(_r.get("head") or "").strip().lower().startswith("basic")
        and "employer" not in str(_r.get("head") or "").strip().lower())
    if salary_mode in ("daily", "hourly") and _sc_basic_471 > 0:
        _earn_mult_471 = (effective_present if salary_mode == "daily"
                          else duty_hours)
        structure = {k: round(v * _earn_mult_471, 2)
                     for k, v in structure.items()}
    basic = structure["basic"]
    hra = structure["hra"]
    conveyance = structure["conveyance"]
    medical = structure["medical"]
    special = structure["special"]
    others = structure["others"]

    # Iter 329 (user check) — ZERO-DAY EARNINGS GUARD: with no present days,
    # no duty hours and no OT this month, ALL earned heads must be 0.
    # (Fixed-amount heads like a flat HRA used to leak a full month into
    # 0-day rows, breaking Earnings vs Gross totals on the registers.)
    if effective_present <= 0 and duty_hours <= 0 and ot_pay <= 0:
        basic = hra = conveyance = medical = special = others = 0.0
        monthly_gross = 0.0

    # Iter 630 (user spec — Allowance Enable/Disable contract) — apply the
    # Firm-Master EDITABLE-allowance mask INSIDE the compute: disabled heads
    # calculate as 0 and the masked amount leaves the gross, so Gross Paid /
    # ESIC / PT wage bases genuinely exclude them. Basic (fixed component)
    # is never masked. Stored master values are NEVER modified — re-enabling
    # the head and reprocessing restores them. On freeze-import runs the
    # masked amount becomes part of the Difference, which the caller
    # reallocates ONLY into OT / Other Allowances (the permitted adjustment
    # heads) so Final Gross Paid == Imported Freeze Gross.
    if enabled_allowances is not None:
        _masked630 = 0.0
        if "hra" not in enabled_allowances:
            _masked630 += hra
            hra = 0.0
        if "conveyance" not in enabled_allowances:
            _masked630 += conveyance
            conveyance = 0.0
        if "medical" not in enabled_allowances:
            _masked630 += medical
            medical = 0.0
        if "special" not in enabled_allowances:
            _masked630 += special
            special = 0.0
        if "others" not in enabled_allowances:
            _masked630 += others
            others = 0.0
        if _masked630:
            monthly_gross = round(monthly_gross - _masked630, 2)

    # Iter 406 (user rule) — freeze-import difference allocated to OTHER
    # ALLOWANCES also lands inside the compute (see ot_pay_extra above).
    _oth_extra = _num(stats.get("other_allowance_extra"), 0.0)
    if _oth_extra:
        others += _oth_extra
        monthly_gross = round(monthly_gross + _oth_extra, 2)

    # Gross for statutory purposes:
    # Under new labour code (per client policy), the WAGE BASE for both
    # PF and ESIC is: max(Basic, floor_pct% of Gross Earning).
    # It is capped at ₹15,000 for PF; ESIC applies the same base without
    # a wage cap but only when Gross Earning ≤ ₹21,000.
    gross_paid = monthly_gross + ot_pay  # total "Gross Earning" this month
    floor_pct = _num(cfg.get("stat_wage_floor_pct"), 50.0)
    stat_wage_base = max(basic, gross_paid * (floor_pct / 100.0))

    # Iter 297 (user bug) — ZERO-DAY GUARD: an employee with NO payable
    # days / hours / gross this month must have NO statutory deductions
    # at all (previously the master salary structure leaked a full-month
    # Basic into the ESIC calc, showing ESIC amounts on 0-day rows).
    _zero_pay = (
        effective_present <= 0 and duty_hours <= 0 and gross_paid <= 0
    )

    # Iter 85 — Master (full-month) values.
    # These are the FULL monthly figures ignoring present days — used
    # to populate the "Master Salary" columns in the Compliance grid so
    # admins can compare full vs pro-rated amounts at a glance.
    # (Computed BEFORE statutory so ESIC eligibility can use the
    # full-month Basic — Iter 129 user directive.)
    if salary_mode == "daily":
        monthly_gross_master = rate * int(month_days)
    elif salary_mode == "hourly":
        monthly_gross_master = rate * (int(month_days) * full_day_hours)
    else:
        monthly_gross_master = rate  # monthly cadence => rate is the full monthly gross
    if master_gross_override is not None:
        monthly_gross_master = master_gross_override
    master_structure = resolve_structure(master_user, monthly_gross_master, company_structure_pct)
    # Iter 471 — master (full-month) heads for DAILY / HOURLY structure-row
    # employees scale the per-day/per-hour amounts to the full month.
    if salary_mode in ("daily", "hourly") and _sc_basic_471 > 0 \
            and (master_user.get("salary_structure_compliance") or []):
        _mm_471 = (float(month_days) if salary_mode == "daily"
                   else float(month_days) * full_day_hours)
        master_structure = {k: round(v * _mm_471, 2)
                            for k, v in master_structure.items()}

    # ---- PF ----
    # Iter 98 — firm-level EPF gate (Firm Master → EPF "Applicable") ANDed
    # with the per-employee flag.
    # Iter 129 (user directive) — PF is calculated ONLY from the Employee
    # Master's "PF Basic Salary" (pf_basic). When it is 0 / blank, NO PF is
    # deducted for that employee, and when filled ALL PF amounts derive
    # from it (pro-rated by attendance for monthly-rated staff).
    pf_basic_override = _num(user.get("pf_basic"), 0.0)
    # Iter 387 — Wage Definition Rule = the max(Basic, floor% Gross) floor;
    # configurable (global / per-firm) in Standard Compliance Settings.
    wage_rule_on = cfg.get("wage_definition_rule_enabled") is not False
    # Iter 370 (user bug) — MASTER eligibility is tracked SEPARATELY from
    # the zero-pay guard: a first process with 0 Present Days used to mark
    # the row pf_applicable=False, which froze the grid's client-side
    # recompute (typing days showed no PF/ESIC until a SECOND "Salary
    # Process" click). ``pf_eligible`` is the days-independent flag.
    # Iter 387 — module-level PF switch + Excluded Employee flag; the skip
    # REASON is captured for the audit/"View Calculation" layers.
    _pf_skip_reason = ""
    if not firm_pf_enabled:
        _pf_skip_reason = "EPF marked Not Applicable on the Firm Master"
    elif cfg.get("pf_enabled") is False:
        _pf_skip_reason = "PF module disabled in Compliance Settings"
    elif user.get("pf_applicable") is False:
        _pf_skip_reason = "PF Applicable = No on the Employee Master"
    elif user.get("excluded_employee"):
        _pf_skip_reason = "Excluded Employee (EPF) on the Employee Master"
    elif pf_basic_override <= 0:
        _pf_skip_reason = "PF Basic Salary blank/0 on the Employee Master"
    pf_eligible = not _pf_skip_reason
    pf_applicable = (
        pf_eligible
        and not _zero_pay  # Iter 297 — no PF on a zero-day / zero-pay month
    )
    if pf_eligible and _zero_pay:
        _pf_skip_reason = "Zero-pay month (no payable days / hours / gross)"
    # Iter 622 (user decision — "we don't need this feature; by default
    # divide by the entered Month Days") — PF proration is LOCKED to the
    # sheet's month_days. The Compliance Settings method selector is ON
    # HOLD; any stored value (working_days ÷26 etc.) is IGNORED here until
    # the user re-verifies the alternative rules.
    pf_proration_method = "calendar_days"
    # Iter 408 — PF Contribution Type + Higher PF activation state (also
    # exposed on the row when PF is skipped, for the reports/AI layers).
    _pf_type = str(user.get("pf_contribution_type") or "statutory").lower()
    _hi_active = False
    _hi_reason = ""
    # Iter 597 (user spec) — Contractor Wage-Based PF mode + partial-month
    # policy (from PF Settings, global or per-firm). Note kept for the
    # pf_reason / "View Calculation" layers.
    _contractor_on = str(cfg.get("contractor_pf_mode") or "standard").lower() == "contractor_wage_based"
    _contractor_partial = str(cfg.get("contractor_partial_month_rule") or "adopted_wage").lower()
    _contractor_note = ""
    if pf_applicable:
        # Iter 471 — DAILY / HOURLY rate basis: the PF Basic on the master
        # is a PER-DAY / PER-HOUR figure. Earned PF Basic = rate × days
        # (or hours); ceiling comparisons use the FULL-MONTH equivalent.
        if salary_mode == "daily":
            pf_basic_prorated = pf_basic_override * effective_present
        elif salary_mode == "hourly":
            pf_basic_prorated = pf_basic_override * duty_hours
        else:
            # Iter 387 — configurable proration method (default replicates
            # the old present ÷ month-days behaviour).
            pf_basic_prorated = pf_basic_override * _proration_factor(
                pf_proration_method, effective_present, max(1, month_days))
        _pf_basic_month = (
            pf_basic_override * float(month_days) if salary_mode == "daily"
            else pf_basic_override * float(month_days) * full_day_hours
            if salary_mode == "hourly" else pf_basic_override)
        # Iter 376 (user rule, replaces Iter 254) — PF wage base:
        #   • PF Basic BELOW the ₹15,000 cap → the wage-base FLOOR applies:
        #     wages = max(PF Basic, floor_pct% of Gross Earning), capped
        #     at the PF wage cap (₹15,000).
        #   • PF Basic AT/ABOVE ₹15,000 → the floor does NOT apply; PF is
        #     calculated per the ceiling rule → wages = ₹15,000 (pro-rated
        #     by attendance for monthly-rated staff).
        # Iter 387 — the floor only applies while the Wage Definition Rule
        # is enabled in Compliance Settings.
        if _pf_basic_month < cfg["pf_wage_cap"] and wage_rule_on:
            pf_base = max(pf_basic_prorated, gross_paid * (floor_pct / 100.0))
        else:
            pf_base = pf_basic_prorated
        # Iter 387 — International Worker: EPF applies WITHOUT the wage
        # ceiling (statutory IW rule).
        _intl_worker = bool(user.get("intl_worker"))
        # Iter 408 (user spec) — PF CONTRIBUTION TYPE (Employee Master):
        #   statutory → ceiling applies exactly as before (default)
        #   higher    → BOTH sides on ACTUAL PF wages (or the approved
        #               Higher PF Wage) with NO ceiling — requires company
        #               "Allow Higher PF", approval and the effective window
        #   vpf       → statutory PF + VPF on top (employee side only)
        if _pf_type == "higher":
            _hi_from = str(user.get("higher_pf_from") or "")[:7]
            _hi_to = str(user.get("higher_pf_to") or "")[:7]
            _month_key = str(cfg.get("_salary_month") or "")[:7]
            # Iter 425 (user directive) — Management Approval REMOVED and
            # Iter 425b (user bug) — the company "Allow Higher PF" switch is
            # NO LONGER consulted (it was resolved through time-versioned
            # settings and silently fell back to the ceiling on months whose
            # policy version predated the switch). Marking the EMPLOYEE as
            # Higher PF is enough; only the effective window gates it.
            if _month_key and _hi_from and _month_key < _hi_from:
                _hi_reason = f"effective only from {_hi_from}"
            elif _month_key and _hi_to and _month_key > _hi_to:
                _hi_reason = f"expired after {_hi_to}"
            else:
                _hi_active = True
        if _hi_active:
            _hi_wage = _num(user.get("higher_pf_wage"), 0.0)
            # Iter 457 (user bug — MILAP: Basic 2,30,000 / PF Basic 1,70,000
            # showed PF 27,600 instead of 20,400) — Higher PF contributes on
            # the employee's OWN PF wage, never silently on the full wage
            # base. Precedence:
            #   1. Higher PF Wage filled → PF on that wage (pro-rated).
            #   2. PF Basic filled → PF on the EARNED PF Basic (no ceiling).
            #   3. Neither → actual wage base (max(Basic, floor% Gross)).
            if _hi_wage > 0:
                if _contractor_on and _contractor_partial == "adopted_wage":
                    # Iter 597 Rule 4 (company policy) — FIXED adopted wage
                    # regardless of attendance / LOP.
                    capped_pf_wages = _hi_wage
                    _contractor_note = ("Rule 4 — adopted PF Wage kept FIXED "
                                        "regardless of attendance (company policy)")
                else:
                    _fct = (_proration_factor(
                        pf_proration_method, effective_present,
                        max(1, month_days)) if salary_mode == "monthly" else 1.0)
                    capped_pf_wages = _hi_wage * _fct
                    if _contractor_on:
                        _contractor_note = ("Rule 4 — PF on the EARNED adopted "
                                            "PF Wage (partial attendance)")
            elif pf_basic_override > 0:
                if _contractor_on and _contractor_partial == "adopted_wage":
                    capped_pf_wages = _pf_basic_month
                    _contractor_note = ("Rule 4 — adopted PF Basic kept FIXED "
                                        "regardless of attendance (company policy)")
                else:
                    capped_pf_wages = pf_basic_prorated
                    if _contractor_on:
                        _contractor_note = ("Rule 4 — PF on the EARNED PF Basic "
                                            "(partial attendance)")
            else:
                capped_pf_wages = max(pf_base, stat_wage_base)
        else:
            if _intl_worker:
                capped_pf_wages = pf_base
            elif _contractor_on:
                # Iter 597 (user spec) — CONTRACTOR WAGE-BASED PF (Rules 1-3):
                # PF strictly on the EARNED Basic+DA (PF Basic) of the wage
                # period — the 50% wage-definition floor does NOT apply.
                #   Rule 2 — earned ≥ ceiling → PF wage = ceiling (max PF)
                #   Rule 3 — earned < ceiling (LOP / partial month / mid-month
                #            join or exit) → PF on the ACTUAL earned PF wage.
                if pf_basic_prorated >= cfg["pf_wage_cap"]:
                    capped_pf_wages = cfg["pf_wage_cap"]
                    _contractor_note = (
                        f"Rule 2 — earned PF wage ₹{pf_basic_prorated:,.0f} at/above "
                        f"the ceiling → maximum statutory contribution")
                else:
                    capped_pf_wages = pf_basic_prorated
                    _contractor_note = (
                        "Rule 3 — PARTIAL period (LOP / fewer days): PF on the "
                        "ACTUAL earned PF wage"
                        if _pf_basic_month >= cfg["pf_wage_cap"]
                        else "Rule 1 — PF on the earned Basic+DA (below ceiling)")
            elif _pf_basic_month > cfg["pf_wage_cap"]:
                # Iter 456 (user final PF Engine spec) — PF Basic FILLED
                # ABOVE the ₹15,000 ceiling on the Employee Master = ADOPTED
                # HIGHER PF: PF on the FULL EARNED PF Basic (pro-rated by
                # present days), WITHOUT the ceiling. EPS stays restricted
                # to the statutory ceiling; the balance of the employer
                # share moves to Employer EPF (12%-minus-EPS split below).
                # (Iter 450 confirmed — AMIT PF Basis 17,796 ⇒ PF ₹2,136.)
                capped_pf_wages = pf_basic_prorated
            else:
                # Iter 456 (user final PF Engine spec) — PF Basic ≤ ₹15,000:
                # PF Wage = HIGHER of Earned PF Basic / Earned 50% Compliance
                # Wage Base (pf_base already carries this max, Iter 376),
                # capped at the statutory ceiling. Adopt PF / manual PF Wage
                # and the PF Wage Calculation Method options were REMOVED
                # (user rollback).
                capped_pf_wages = min(pf_base, cfg["pf_wage_cap"])
        pf_employee = capped_pf_wages * (cfg["pf_percent_employee"] / 100.0)
        if _hi_active:
            # ECR-compatible split: employer total on the FULL higher wage;
            # EPS stays on the statutory ceiling (unless the Higher Pension
            # joint option is ticked); EPF gets the remainder.
            _er_total = capped_pf_wages * (
                (cfg["pf_percent_employer_epf"] + cfg["pf_percent_employer_eps"]) / 100.0)
            _eps_wages = (capped_pf_wages if user.get("higher_pension")
                          else min(capped_pf_wages, cfg["pf_wage_cap"]))
            pf_employer_eps = _eps_wages * (cfg["pf_percent_employer_eps"] / 100.0)
            pf_employer_epf = _er_total - pf_employer_eps
        else:
            # Iter 387 — Higher Pension (joint option): EPS contribution on
            # the UNCAPPED PF wages instead of the ceiling.
            # Iter 449 (user spec) — EPS is ALWAYS restricted to the wage
            # ceiling otherwise; Adopt-PF wages above the ceiling follow the
            # ECR split (ER total 12% of the adopted wage, EPS capped,
            # remainder → Employer EPF).
            _eps_wages = (pf_base if user.get("higher_pension")
                          else min(capped_pf_wages, cfg["pf_wage_cap"]))
            pf_employer_eps = _eps_wages * (cfg["pf_percent_employer_eps"] / 100.0)
            if capped_pf_wages > cfg["pf_wage_cap"] and not user.get("higher_pension"):
                _er_tot = capped_pf_wages * (
                    (cfg["pf_percent_employer_epf"] + cfg["pf_percent_employer_eps"]) / 100.0)
                pf_employer_epf = _er_tot - pf_employer_eps
            else:
                pf_employer_epf = capped_pf_wages * (cfg["pf_percent_employer_epf"] / 100.0)
        # Iter 341 (user request) — Employee Master "EPS Disable": the
        # employee is NOT eligible for Pension, so the entire employer
        # share goes to EPF and EPS is 0 (ECR prints EPS as 0).
        if user.get("eps_disabled"):
            pf_employer_epf += pf_employer_eps
            pf_employer_eps = 0.0
        pf_employer_total = pf_employer_epf + pf_employer_eps
        # Iter 126i — VPF (Voluntary PF): extra EMPLOYEE-side deduction on
        # top of the statutory PF (employer share unchanged). Pro-rated by
        # attendance for monthly-rated staff.
        # Iter 408 — VPF also via the Contribution Type dropdown; supports a
        # PERCENTAGE of PF wages (vpf_percent) or the fixed monthly amount;
        # honours the company Allow VPF flag + optional max-% limit.
        vpf = 0.0
        _vpf_on = bool(user.get("vpf_enabled")) or _pf_type == "vpf"
        if _vpf_on and cfg.get("allow_vpf", True) is not False:
            _vpf_pct = _num(user.get("vpf_percent"), 0.0)
            _vpf_lim = _num(cfg.get("vpf_max_percent"), 0.0)
            if _vpf_pct > 0 and _vpf_lim > 0:
                _vpf_pct = min(_vpf_pct, _vpf_lim)
            if _vpf_pct > 0:
                vpf = capped_pf_wages * (_vpf_pct / 100.0)
            else:
                vpf_amt = _num(user.get("vpf_amount"), 0.0)
                if vpf_amt > 0:
                    if salary_mode == "monthly":
                        vpf = _safe_div(vpf_amt * effective_present, max(1, month_days))
                    else:
                        vpf = vpf_amt
            vpf = max(0.0, vpf)
        pf_employee += vpf
        # Iter 127f — whole-rupee statutory rounding (Standard Settings).
        pf_mode = str(cfg.get("pf_rounding") or "nearest")
        pf_employee = _round_stat(pf_employee, pf_mode)
        pf_employer_epf = _round_stat(pf_employer_epf, pf_mode)
        pf_employer_eps = _round_stat(pf_employer_eps, pf_mode)
        pf_employer_total = pf_employer_epf + pf_employer_eps
    else:
        capped_pf_wages = 0.0
        pf_base = pf_basic_prorated = 0.0
        vpf = 0.0
        pf_employee = pf_employer_epf = pf_employer_eps = pf_employer_total = 0.0

    # ---- ESIC ----
    # Iter 98 — firm-level ESIC gate (Firm Master → ESI "Applicable") ANDed
    # with the per-employee flag.
    # Iter 129 (user directive) — ESIC eligibility is now checked against
    # the FULL-MONTH Basic Salary (≤ the limit in Standard Compliance
    # Settings), NOT the gross earning. Rates & rounding still come from
    # the Compliance Settings; the wage base rule is unchanged.
    # Iter 254 (user directive) — ESIC eligibility (≤ limit in Standard
    # Compliance Settings) is checked against the Employee Master's
    # "Compliance Basic Salary" field when it is filled; falls back to the
    # derived full-month Basic otherwise.
    _esic_elig_basic = _num(user.get("compliance_basic"), 0.0)
    # Iter 471 — DAILY / HOURLY rate basis: eligibility compares the
    # FULL-MONTH equivalent of the per-day/per-hour Compliance Basic.
    if _esic_elig_basic > 0 and salary_mode == "daily":
        _esic_elig_basic *= float(month_days)
    elif _esic_elig_basic > 0 and salary_mode == "hourly":
        _esic_elig_basic *= float(month_days) * full_day_hours
    if _esic_elig_basic <= 0:
        _esic_elig_basic = master_structure["basic"]
    # Iter 370 — days-independent ESIC eligibility (see pf_eligible above).
    # Iter 387 — module switch, Temporary Exemption, ESIC Exit Date and the
    # configurable disable-above-ceiling rule; skip REASON captured for the
    # audit / "View Calculation" layers.
    _salary_month = str(cfg.get("_salary_month") or "")[:7]
    _esic_exit_month = str(user.get("esic_exit_date") or "")[:7]
    _head_map = cfg.get("head_mapping") if isinstance(cfg.get("head_mapping"), dict) else None

    def _esic_head_on(k: str) -> bool:
        if not _head_map:
            return DEFAULT_HEAD_MAPPING.get(k, {}).get("esic", True)
        return (_head_map.get(k) or {}).get("esic") is not False

    def _esi_actual_wages(src: Dict[str, Any], ot_component: float) -> float:
        """Actual ESI Wages = sum of ESI-flagged earning heads (+ OT)."""
        return sum(
            _num(src.get(k), 0.0)
            for k in ("basic", "hra", "conveyance", "medical", "special", "others")
            if _esic_head_on(k)
        ) + ot_component

    _esic_skip_reason = ""
    if not firm_esic_enabled:
        _esic_skip_reason = "ESI marked Not Applicable on the Firm Master"
    elif cfg.get("esic_enabled") is False:
        _esic_skip_reason = "ESIC module disabled in Compliance Settings"
    elif user.get("esic_applicable") is False:
        _esic_skip_reason = "ESIC Applicable = No on the Employee Master"
    elif user.get("esic_temp_exempt"):
        _esic_skip_reason = "ESIC Temporary Exemption on the Employee Master"
    elif (_salary_month and _esic_exit_month
          and re.fullmatch(r"\d{4}-\d{2}", _esic_exit_month)
          and _esic_exit_month < _salary_month):
        _esic_skip_reason = (
            f"ESIC Exit Date ({user.get('esic_exit_date')}) is before the salary month")
    elif cfg.get("esic_disable_above_ceiling") is not False:
        # Iter 456 (user rollback) — ESIC eligibility stays on the LEGACY
        # rule: full-month Basic vs the ESIC ceiling. The configurable
        # ESIC Wage Calculation Method was removed.
        if _esic_elig_basic > cfg["esic_gross_threshold"]:
            _esic_skip_reason = (
                f"Basic ₹{_esic_elig_basic:,.0f} above the ESIC ceiling "
                f"₹{cfg['esic_gross_threshold']:,.0f}")
    esic_eligible = not _esic_skip_reason
    esic_applicable = (
        esic_eligible
        # Iter 297 (user bug) — days ZERO in the front window ⇒ ESIC = 0.
        and not _zero_pay
    )
    if esic_eligible and _zero_pay:
        _esic_skip_reason = "Zero-pay month (no payable days / hours / gross)"
    # Iter 622 (user decision) — ESIC proration LOCKED to the sheet's
    # month_days (see PF note above). Stored method is IGNORED.
    esic_proration_method = "calendar_days"

    if esic_applicable:
        # Iter 385 (user confirmed rule) — legacy ESIC wage base follows
        # the 50% floor rule: wage base = max(Basic, floor% × Gross).
        # Iter 387 — Wage Definition Rule OFF ⇒ base = the SUM of earning
        # heads flagged "ESIC Wage" in the Salary Head Mapping (+ OT).
        # Iter 449 (user spec) — ESIC Wage Calculation Method overrides:
        #   actual → Actual ESI Wages · floor → floor% of Gross ·
        #   higher → max(Actual ESI Wages, floor). Default "wage_base"
        #   keeps the legacy rules above unchanged.
        _use_master = esic_proration_method == "none"
        if _use_master:
            _esi_src: Dict[str, Any] = master_structure
            _esi_ot = 0.0
            _esi_gross_ref = monthly_gross_master
        else:
            _esi_src = {"basic": basic, "hra": hra, "conveyance": conveyance,
                        "medical": medical, "special": special, "others": others}
            _esi_ot = ot_pay if _esic_head_on("ot") else 0.0
            _esi_gross_ref = gross_paid
        _esi_actual = _esi_actual_wages(_esi_src, _esi_ot)
        _esi_floor = _esi_gross_ref * (floor_pct / 100.0)
        # Iter 456 (user rollback) — ESIC stays on the LEGACY rules only;
        # the configurable ESIC Wage Calculation Method was removed.
        if wage_rule_on:
            esic_wage_base = (max(master_structure["basic"], _esi_floor)
                              if _use_master else stat_wage_base)
        else:
            esic_wage_base = _esi_actual
        esic_employee = esic_wage_base * (cfg["esic_percent_employee"] / 100.0)
        esic_employer = esic_wage_base * (cfg["esic_percent_employer"] / 100.0)
        # Iter 127f — ESIC statutory rounding (default: UP to next rupee).
        esic_mode = str(cfg.get("esic_rounding") or "ceil")
        esic_employee = _round_stat(esic_employee, esic_mode)
        esic_employer = _round_stat(esic_employer, esic_mode)
    else:
        esic_wage_base = 0.0
        esic_employee = esic_employer = 0.0

    # ---- Professional Tax ----
    # Iter 178 resolution order: per-employee override ▸ firm custom slabs ▸
    # firm STATE slabs (compliance_policy.pt_state) ▸ legacy per-employee
    # flat state amount.
    pt_state = (user.get("pt_state") or "None").strip() or "None"
    pt_override = user.get("pt_amount_override")
    _fpt = firm_pt or {}
    if pt_override is not None and _num(pt_override, -1) >= 0:
        pt = _num(pt_override, 0.0)
    elif isinstance(_fpt.get("slabs"), list) and _fpt.get("slabs"):
        pt = pt_from_slabs(gross_paid, _fpt["slabs"])
    elif (_fpt.get("state") or "").strip():
        pt = pt_from_slabs(gross_paid, PT_STATE_SLABS.get(str(_fpt["state"]).strip(), []))
    else:
        pt = PT_STATE_MONTHLY.get(pt_state, 0.0)

    # ---- TDS (manual ₹ per employee) ----
    tds = _num(user.get("tds_amount"), 0.0)

    # ---- Iter 127c — Firm-linked deduction heads from the Employee Master
    # (compliance section). PF / ESI heads are skipped — those are computed
    # statutorily above and must not double-count.
    # Iter 420 (user request) — per-head breakdown kept so every enabled
    # Firm Master deduction head can render as its OWN dynamic column.
    master_deduction = 0.0
    deduction_heads: Dict[str, float] = {}
    for r in (user.get("compliance_salary_deductions") or []):
        if not isinstance(r, dict):
            continue
        s = str(r.get("head") or "").strip().lower()
        if "pf" in s or "esi" in s or "provident" in s:
            continue
        _amt = _num(r.get("amount"), 0.0)
        master_deduction += _amt
        if _amt:
            _lbl = str(r.get("head") or "").strip() or "OTH. DEDUC."
            deduction_heads[_lbl] = round(deduction_heads.get(_lbl, 0.0) + _amt, 2)

    # Iter 297 — zero-day / zero-pay month ⇒ every deduction is 0.
    if _zero_pay:
        pt = 0.0
        tds = 0.0
        master_deduction = 0.0
        deduction_heads = {}

    total_deduction = pf_employee + esic_employee + pt + tds + master_deduction
    net = gross_paid - total_deduction

    # Iter 230 (user bug — "Gross showing ₹1 low of added allowances") —
    # WHOLE-RUPEE RECONCILIATION: the sheet displays every column as a
    # whole ₹, so rounding each head separately could make
    # Basic+HRA+…+Others differ from Gross by ₹1. Round every head to a
    # whole rupee and absorb the delta into the LARGEST head so the
    # displayed columns always add up exactly to the displayed Gross.
    def _reconcile(heads: Dict[str, float], target: float) -> Dict[str, float]:
        r = {k: float(round(v)) for k, v in heads.items()}
        delta = float(round(target)) - sum(r.values())
        if delta and any(v > 0 for v in r.values()):
            big = max(r, key=lambda k: r[k])
            r[big] = max(0.0, r[big] + delta)
        return r
    _paid = _reconcile(
        {"basic": basic, "hra": hra, "conveyance": conveyance,
         "medical": medical, "special": special, "others": others},
        monthly_gross,
    )
    basic, hra, conveyance = _paid["basic"], _paid["hra"], _paid["conveyance"]
    medical, special, others = _paid["medical"], _paid["special"], _paid["others"]
    _mast = _reconcile(
        {"basic": master_structure["basic"], "hra": master_structure["hra"],
         "conveyance": master_structure["conveyance"],
         "medical": master_structure["medical"],
         "special": master_structure["special"],
         "others": master_structure["others"]},
        monthly_gross_master,
    )
    master_structure = {**master_structure, **_mast}

    # Iter 644 (user request — "Allowances not showing dynamically") —
    # decompose the CUSTOM Firm-Master allowance heads (INCENTIVE / BONUS /
    # DA / …) OUT of the "Others" bucket for DISPLAY ONLY. The amounts stay
    # inside the others totals for every calculation (Gross / PF / ESIC /
    # PT bases are UNCHANGED); the row just carries a per-head breakdown so
    # each enabled head renders as its OWN dynamic column (mirrors the
    # Iter 420 deduction heads). Views/exports subtract it from Others.
    allowance_heads: Dict[str, float] = {}
    allowance_heads_master: Dict[str, float] = {}
    if custom_allowance_labels:
        _lab_low = {str(l).strip().lower(): str(l)
                    for l in custom_allowance_labels if str(l).strip()}

        def _is_others_head(h: Any) -> bool:
            s = str(h or "").strip().lower()
            if not s or "employer" in s or s.startswith("basic"):
                return False
            if "hra" in s or "house" in s:
                return False
            if s.startswith("conv") or "travel" in s:
                return False
            if "medic" in s or "special" in s:
                return False
            return True

        _st_rows = [r for r in (user.get("salary_structure_compliance") or [])
                    if isinstance(r, dict)]
        _has_basic_row = any(
            str(r.get("head") or "").strip().lower().startswith("basic")
            and "employer" not in str(r.get("head") or "").lower()
            and _num(r.get("amount"), 0.0) > 0 for r in _st_rows)
        _src_rows = _st_rows if _has_basic_row else [
            r for r in (user.get("compliance_salary_allowances") or [])
            if isinstance(r, dict)]
        _cust_monthly: Dict[str, float] = {}
        _oth_monthly = 0.0
        for _r in _src_rows:
            _h = str(_r.get("head") or "").strip()
            _a = _num(_r.get("amount"), 0.0)
            if _a <= 0 or not _is_others_head(_h):
                continue
            _oth_monthly += _a
            _lb = _lab_low.get(_h.lower())
            if _lb:
                _cust_monthly[_lb] = _cust_monthly.get(_lb, 0.0) + _a
        if _cust_monthly and _oth_monthly > 0:
            _m_scale = master_structure["others"] / _oth_monthly
            _p_scale = others / _oth_monthly
            _mb = float(master_structure["others"])
            _pb = float(others)
            for _lb, _a in _cust_monthly.items():
                _hm = min(float(round(_a * _m_scale)), _mb)
                _hp = min(float(round(_a * _p_scale)), _pb)
                if _hm > 0:
                    allowance_heads_master[_lb] = _hm
                    _mb -= _hm
                if _hp > 0:
                    allowance_heads[_lb] = _hp
                    _pb -= _hp

    # Iter 633 (user request) — ALWAYS CALCULATE IN ROUND FIGURES: every
    # money figure the sheet stores / displays / reprocesses is a WHOLE
    # RUPEE (the earning heads were already whole-rupee reconciled above).
    # The statutory percentages were applied on the precise values first;
    # the results are rounded here and the totals RE-DERIVED from the
    # rounded parts so every column always tallies exactly.
    monthly_gross = float(round(monthly_gross))
    ot_pay = float(round(ot_pay))
    gross_paid = monthly_gross + ot_pay
    stat_wage_base = float(round(stat_wage_base))
    capped_pf_wages = float(round(capped_pf_wages))
    pf_employee = float(round(pf_employee))
    vpf = float(round(vpf))
    pf_employer_epf = float(round(pf_employer_epf))
    pf_employer_eps = float(round(pf_employer_eps))
    pf_employer_total = pf_employer_epf + pf_employer_eps
    esic_wage_base = float(round(esic_wage_base))
    esic_employee = float(round(esic_employee))
    esic_employer = float(round(esic_employer))
    pt = float(round(pt))
    tds = float(round(tds))
    master_deduction = float(round(master_deduction))
    total_deduction = pf_employee + esic_employee + pt + tds + master_deduction
    net = gross_paid - total_deduction

    # Iter 626 — snapshot of locals for calc_detail: some PF/ESIC variables
    # are only bound on eligible branches (skip paths leave them unset).
    _loc = dict(locals())

    def _cd(name: str) -> float:
        try:
            return round(float(_loc.get(name) or 0), 2)
        except (TypeError, ValueError):
            return 0.0

    return {
        "user_id": user.get("user_id"),
        "name": user.get("name"),
        "employee_code": user.get("employee_code"),
        # User directive — Compliance sheet shows Father Name, Designation,
        # UAN No. & ESIC No. (Employee Code hidden on the UI). Female
        # employees show "D/O father" (unmarried) or spouse name (married).
        "father_name": _father_or_spouse(user),
        "designation": user.get("designation"),
        "uan_no": user.get("uan_no"),
        "esi_ip_no": user.get("esi_ip_no"),
        # Iter 306 (user #4) — PF No shown on the Register Format 1.
        "pf_no": user.get("pf_no"),
        # Iter 306 (user #20) — ESIC Leave days (admin-editable in the grid).
        "esic_leave_days": 0.0,
        "employee_type": user.get("employee_type"),
        # Iter 183 — Branch / Department / Contractor for grid filter chips.
        "branch_name": user.get("branch_name"),
        "department": user.get("department"),
        "contractor_name": user.get("contractor_name"),
        "is_onroll": user.get("is_onroll") is not False,
        "salary_mode": salary_mode,
        "rate": round(rate, 2),
        "month_days": int(month_days),
        "present_days": present_days,
        "half_days": half_days,
        # Iter 85 — Master (full-month) heads. Non-editable on the UI.
        "basic_master": round(master_structure["basic"], 2),
        "hra_master": round(master_structure["hra"], 2),
        "conveyance_master": round(master_structure["conveyance"], 2),
        "medical_master": round(master_structure["medical"], 2),
        "special_master": round(master_structure["special"], 2),
        "others_master": round(master_structure["others"], 2),
        "gross_master": round(monthly_gross_master, 2),
        # Iter 85 — Editable "Other" deduction (advance / recovery / etc.)
        "other_deduction": 0.0,
        "duty_hours": round(duty_hours, 2),
        "ot_hours": round(ot_hours, 2),
        "ot_pay": round(ot_pay, 2),
        # Structure
        "basic": round(basic, 2),
        "hra": round(hra, 2),
        "conveyance": round(conveyance, 2),
        "medical": round(medical, 2),
        "special": round(special, 2),
        "others": round(others, 2),
        # Iter 644 — custom allowance head breakdown (display decomposition
        # of the Others bucket; views subtract this from Others columns).
        "allowance_heads": allowance_heads,
        "allowance_heads_master": allowance_heads_master,
        "monthly_gross": round(monthly_gross, 2),
        "gross_paid": round(gross_paid, 2),
        # PF
        "pf_applicable": pf_applicable,
        # Iter 370 — days-independent flags for the grid's client-side
        # recompute (fixes "first click doesn't calculate PF/ESIC").
        "pf_eligible": pf_eligible,
        "esic_eligible": esic_eligible,
        # Iter 129 — full-month PF Basic Salary from the Employee Master
        # (0 → no PF). Used by the grid's client-side recompute.
        "pf_basic": round(pf_basic_override, 2),
        # Iter 254 — Employee Master Compliance Basic (ESIC eligibility).
        "compliance_basic": round(_num(user.get("compliance_basic"), 0.0), 2),
        "stat_wage_base": round(stat_wage_base, 2),
        "pf_wages": round(capped_pf_wages, 2),
        "pf_employee": round(pf_employee, 2),
        "vpf_amount": round(vpf, 2),
        "pf_employer_epf": round(pf_employer_epf, 2),
        # Iter 341 — EPS Disable flag carried on the row (ECR prints 0).
        "eps_disabled": bool(user.get("eps_disabled")),
        "pf_employer_eps": round(pf_employer_eps, 2),
        "pf_employer_total": round(pf_employer_total, 2),
        # ESIC
        "esic_applicable": esic_applicable,
        "esic_wage_base": round(esic_wage_base, 2),
        "esic_employee": round(esic_employee, 2),
        "esic_employer": round(esic_employer, 2),
        # PT / TDS
        "pt_state": pt_state,
        "pt": round(pt, 2),
        "tds": round(tds, 2),
        # Iter 127c — firm-linked deduction heads from the Employee Master
        "master_deduction": round(master_deduction, 2),
        "deduction_heads": deduction_heads,
        # Totals
        "total_deduction": round(total_deduction, 2),
        "net": round(net, 2),
        # Iter 387 — Phase-1 employee flags carried on the row (grid
        # recompute + ECR/validation layers).
        "higher_pension": bool(user.get("higher_pension")),
        "intl_worker": bool(user.get("intl_worker")),
        "excluded_employee": bool(user.get("excluded_employee")),
        "esic_temp_exempt": bool(user.get("esic_temp_exempt")),
        # Iter 408 — PF Contribution Type snapshot for the reports /
        # validation / AI-explanation layers.
        "pf_contribution_type": _pf_type,
        "pf_higher_active": _hi_active,
        "pf_higher_reason": _hi_reason,
        "pf_ceiling_applied": bool(pf_applicable and not _hi_active
                                   and not user.get("intl_worker")
                                   and pf_base > capped_pf_wages + 0.5),
        "higher_pf_wage": _num(user.get("higher_pf_wage"), 0.0),
        "pf_approval_status": str(user.get("pf_approval_status") or ""),
        "pf_declaration_available": bool(user.get("pf_declaration_available")),
        # Iter 387 — human-readable calculation reasons + full snapshot
        # ("View Calculation" / audit dashboard / AI assistant layers).
        # Iter 626 (user spec §5-§10) — transparent, auditable calculation
        # detail (View Calculation). Separates PF monthly-equivalent /
        # earned / contribution wages and ESIC coverage vs contribution.
        "calc_detail": {
            "salary_mode": salary_mode,
            "rate": _cd("rate"),
            "eligible_paid_days": effective_present,
            "full_day_hours": _cd("full_day_hours"),
            "ot_hours": _cd("ot_hours"),
            "ot_rate_per_hour": round(_cd("per_hour_rate") * (_cd("ot_multiplier") or 1), 2),
            "ot_multiplier": _cd("ot_multiplier"),
            "ot_amount": _cd("ot_pay"),
            "pf_basic_per_unit": _cd("pf_basic_override"),
            "pf_monthly_equivalent": _cd("_pf_basic_month"),
            "pf_earned_wage": _cd("pf_basic_prorated"),
            "pf_contribution_wage": _cd("capped_pf_wages"),
            "pf_wage_ceiling": cfg["pf_wage_cap"],
            "pf_rate_employee_pct": cfg["pf_percent_employee"],
            "wage_definition_rule_on": bool(wage_rule_on),
            "esic_coverage_wage": _cd("_esic_elig_basic"),
            "esic_contribution_wage": _cd("esic_wage_base"),
            "esic_rate_employee_pct": cfg["esic_percent_employee"],
            "esic_rate_employer_pct": cfg["esic_percent_employer"],
        },
        "pf_reason": (
            _pf_skip_reason if not pf_applicable else (
                f"PF ₹{pf_employee:,.0f} = {cfg['pf_percent_employee']:g}% of "
                f"wages ₹{capped_pf_wages:,.0f}"
                + (" (no ceiling — International Worker)" if user.get("intl_worker")
                   else (f" (capped from ₹{pf_base:,.0f} at ₹{cfg['pf_wage_cap']:,.0f})"
                         if pf_base > capped_pf_wages + 0.5 else ""))
                + (f"; CONTRACTOR WAGE-BASED PF — {_contractor_note}"
                   if _contractor_note else "")
                + (f"; floor rule max(PF Basic ₹{pf_basic_prorated:,.0f}, "
                   f"{floor_pct:g}% of Gross)"
                   if (wage_rule_on and _pf_basic_month < cfg["pf_wage_cap"]
                       and not _contractor_on) else "")
                + ("; EPS on uncapped wages (Higher Pension)" if user.get("higher_pension") else "")
                + ("; EPS = 0 (EPS Disabled)" if user.get("eps_disabled") else "")
                + (f"; HIGHER PF — contribution on actual wages ₹{capped_pf_wages:,.0f}, "
                   "NO ceiling (approved by employer)" if _hi_active else "")
                + (f"; Higher PF NOT applied — {_hi_reason}; statutory ceiling used"
                   if (_pf_type == "higher" and not _hi_active) else "")
                + (f"; + VPF ₹{vpf:,.0f}"
                   + (f" ({_num(user.get('vpf_percent'), 0):g}% of PF wages)"
                      if _num(user.get("vpf_percent"), 0) > 0 else "")
                   if vpf > 0 else "")
                + ("; VPF NOT applied — company policy disallows VPF"
                   if (_pf_type == "vpf" and vpf <= 0
                       and cfg.get("allow_vpf", True) is False) else "")
            )
        ),
        "esic_reason": (
            _esic_skip_reason if not esic_applicable else (
                f"ESIC EE ₹{esic_employee:,.0f} / ER ₹{esic_employer:,.0f} = "
                f"{cfg['esic_percent_employee']:g}% / {cfg['esic_percent_employer']:g}% "
                f"of wage base ₹{esic_wage_base:,.0f}"
                + (f" = max(Basic, {floor_pct:g}% of Gross)" if wage_rule_on
                   else " = Σ heads flagged ESIC Wage in the Head Mapping")
            )
        ),
        "calc_snapshot": {
            "rule_version": str(cfg.get("rule_version") or ""),
            "wage_definition_rule": bool(wage_rule_on),
            "pf_proration_method": pf_proration_method,
            # Iter 597 — Contractor PF mode snapshot for audit layers.
            "contractor_pf_mode": ("contractor_wage_based" if _contractor_on else "standard"),
            "contractor_partial_month_rule": _contractor_partial,
            "esic_proration_method": esic_proration_method,
            "stat_wage_floor_pct": floor_pct,
            "pf": {
                "pf_basic_master": round(pf_basic_override, 2),
                "pf_basic_prorated": round(pf_basic_prorated, 2),
                "wage_base": round(pf_base, 2),
                "ceiling": _num(cfg.get("pf_wage_cap"), 15000.0),
                "wages": round(capped_pf_wages, 2),
                "rate_employee": _num(cfg.get("pf_percent_employee"), 12.0),
                "rate_epf": _num(cfg.get("pf_percent_employer_epf"), 3.67),
                "rate_eps": _num(cfg.get("pf_percent_employer_eps"), 8.33),
                "rounding": str(cfg.get("pf_rounding") or "nearest"),
            },
            "esic": {
                "eligibility_basic": round(_esic_elig_basic, 2),
                "ceiling": _num(cfg.get("esic_gross_threshold"), 21000.0),
                "wage_base": round(esic_wage_base, 2),
                "rate_employee": _num(cfg.get("esic_percent_employee"), 0.75),
                "rate_employer": _num(cfg.get("esic_percent_employer"), 3.25),
                "rounding": str(cfg.get("esic_rounding") or "ceil"),
            },
            "heads_considered": {
                k: {
                    "amount": round(_num({"basic": basic, "hra": hra,
                                          "conveyance": conveyance,
                                          "medical": medical, "special": special,
                                          "others": others, "ot": ot_pay}.get(k), 0.0), 2),
                    "esic_wage": _esic_head_on(k),
                    "pf_wage": (
                        (_head_map.get(k) or {}).get("pf") is True if _head_map
                        else DEFAULT_HEAD_MAPPING.get(k, {}).get("pf", False)),
                } for k in STATUTORY_HEAD_KEYS
            },
        },
    }


# --------------------------------------------------------------------------- 
# CSV / PDF exports
# --------------------------------------------------------------------------- 
CSV_COLUMNS = [
    "name", "father_name", "designation", "uan_no", "esi_ip_no",
    "employee_type", "is_onroll",
    "salary_mode", "rate", "month_days", "present_days", "half_days",
    "duty_hours", "ot_hours",
    "basic", "hra", "conveyance", "medical", "special", "others",
    "monthly_gross", "ot_pay", "gross_paid",
    "stat_wage_base",
    "pf_applicable", "pf_wages", "pf_employee", "pf_employer_epf", "pf_employer_eps", "pf_employer_total",
    "esic_applicable", "esic_wage_base", "esic_employee", "esic_employer",
    "pt_state", "pt", "tds",
    "total_deduction", "net",
]


# Iter 632 (user request) — CSV / Excel exports show WHOLE RUPEES only, the
# same as the on-screen grid and the PDF register (Iter 323), so the exported
# sheet never differs from the processed salary by paise. Days / hours / rate
# keep their real precision (e.g. 22.5 present days, daily rate 483.87).
_EXPORT_MONEY_KEYS = (
    "basic", "hra", "conveyance", "medical", "special", "others",
    "monthly_gross", "ot_pay", "gross_paid", "stat_wage_base",
    "pf_wages", "pf_employee", "pf_employer_epf", "pf_employer_eps",
    "pf_employer_total", "vpf_amount",
    "esic_wage_base", "esic_employee", "esic_employer",
    "pt", "tds", "advance_recovery", "other_deduction", "master_deduction",
    "total_deduction", "net",
    "imported_gross", "calculated_gross", "difference",
)


def round_export_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return copies of the rows with every money figure rounded to whole
    rupees (stored run data is NOT modified)."""
    out = []
    for r in rows:
        c = dict(r)
        for k in _EXPORT_MONEY_KEYS:
            v = c.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                c[k] = int(round(float(v)))
        if isinstance(c.get("deduction_heads"), dict):
            c["deduction_heads"] = {
                h: int(round(_num(a, 0.0)))
                for h, a in c["deduction_heads"].items()}
        # Iter 644 — allowance head breakdowns exported as whole rupees too.
        for _hk in ("allowance_heads", "allowance_heads_master"):
            if isinstance(c.get(_hk), dict):
                c[_hk] = {h: int(round(_num(a, 0.0)))
                          for h, a in c[_hk].items()}
        out.append(c)
    return out


def _ded_head_labels(rows: List[Dict[str, Any]]) -> List[str]:
    """Iter 420 — dynamic Firm-Master deduction head labels for a run."""
    r0 = rows[0] if rows else {}
    labels = r0.get("deduction_head_labels")
    if labels is None:
        labels = sorted({h for r in rows for h in (r.get("deduction_heads") or {})})
    return [str(l) for l in labels if l]


def _allow_head_labels(rows: List[Dict[str, Any]]) -> List[str]:
    """Iter 644 — dynamic Firm-Master allowance head labels for a run."""
    r0 = rows[0] if rows else {}
    labels = r0.get("allowance_head_labels")
    if labels is None:
        labels = sorted({h for r in rows for h in (r.get("allowance_heads") or {})})
    return [str(l) for l in labels if l]


def flatten_deduction_heads(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Iter 420 — copy rows with each firm-master deduction head flattened
    to a top-level key so CSV/XLSX exports render one column per head.
    Iter 644 — custom ALLOWANCE heads are flattened the same way and their
    amounts are subtracted from Others (display decomposition)."""
    labels = _ded_head_labels(rows)
    alabels = _allow_head_labels(rows)
    if not labels and not alabels:
        return rows
    out = []
    for r in rows:
        heads = r.get("deduction_heads") or {}
        aheads = r.get("allowance_heads") or {}
        amast = r.get("allowance_heads_master") or {}
        c = {**r, **{l: heads.get(l, 0) for l in labels},
             **{l: aheads.get(l, 0) for l in alabels}}
        if alabels:
            _ap = sum(_num(aheads.get(l), 0.0) for l in alabels)
            _am2 = sum(_num(amast.get(l), 0.0) for l in alabels)
            if _ap and isinstance(c.get("others"), (int, float)):
                c["others"] = max(0, int(round(_num(c.get("others"), 0.0) - _ap)))
            if _am2 and isinstance(c.get("others_master"), (int, float)):
                c["others_master"] = max(0, int(round(
                    _num(c.get("others_master"), 0.0) - _am2)))
        out.append(c)
    return out


def dynamic_csv_columns(rows: List[Dict[str, Any]]) -> List[str]:
    """Iter 373 (user request) — Excel/CSV export columns follow the
    firm-enabled heads so spreadsheets always MATCH the PDF register."""
    r0 = rows[0] if rows else {}
    en = r0.get("enabled_allowances")
    ed = r0.get("enabled_deductions")

    def has_a(k: str) -> bool:
        return (en is None) or (k in en) or k == "basic"

    def has_d(k: str) -> bool:
        return (ed is None) or (k in ed)

    drop: set = set()
    for k in ("hra", "conveyance", "medical", "special", "others"):
        if not has_a(k):
            drop.add(k)
    if not has_d("pf"):
        drop |= {"pf_applicable", "pf_wages", "pf_employee",
                 "pf_employer_epf", "pf_employer_eps", "pf_employer_total"}
    if not has_d("esi"):
        drop |= {"esic_applicable", "esic_wage_base",
                 "esic_employee", "esic_employer"}
    if not has_d("pt"):
        drop |= {"pt_state", "pt"}
    if not has_d("tds"):
        drop.add("tds")
    # Iter 443 — Master-linked ADVANCE / OTH. DEDUC. export columns.
    if not has_d("advance"):
        drop.add("advance_recovery")
    if not has_d("other"):
        drop |= {"other_deduction", "other_deduction_head"}
    cols = [c for c in CSV_COLUMNS if c not in drop]
    # Iter 644 — OT columns follow the Firm-Master "OVER TIME" toggle:
    # hidden when the head is off AND the run carries no OT data (legacy
    # runs with OT amounts keep their columns).
    if not has_a("ot") and not any(
            _num(r.get("ot_pay"), 0.0) or _num(r.get("ot_hours"), 0.0)
            for r in rows):
        cols = [c for c in cols if c not in ("ot_pay", "ot_hours")]
    # Iter 644 — one dynamic column per enabled custom ALLOWANCE head,
    # placed right after Others (or before monthly_gross when Others is
    # disabled).
    alabels = _allow_head_labels(rows)
    if alabels:
        if "others" in cols:
            i2 = cols.index("others") + 1
        elif "monthly_gross" in cols:
            i2 = cols.index("monthly_gross")
        else:
            i2 = len(cols)
        cols[i2:i2] = alabels
    # Iter 420 (user request) — one dynamic column per Firm-Master enabled
    # deduction head, placed just before Total Ded.
    labels = _ded_head_labels(rows)
    if labels:
        idx = cols.index("total_deduction") if "total_deduction" in cols else len(cols)
        cols[idx:idx] = labels
    return cols


def to_csv(rows: List[Dict[str, Any]]) -> str:
    # Iter 373 (user request) — dynamic firm-wise heads in CSV too.
    cols = dynamic_csv_columns(rows)
    # Iter 632 (user request) — whole rupees in exports.
    rows = flatten_deduction_heads(round_export_rows(rows))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        row = {k: r.get(k, "") for k in cols}
        row["is_onroll"] = "On-roll" if r.get("is_onroll") else "Off-roll"
        if "pf_applicable" in cols:
            row["pf_applicable"] = "Yes" if r.get("pf_applicable") else "No"
        if "esic_applicable" in cols:
            row["esic_applicable"] = "Yes" if r.get("esic_applicable") else "No"
        w.writerow(row)
    return buf.getvalue()


def build_compliance_register_pdf(
    run: Dict[str, Any],
    company_name: str = "S.K. Sharma & Co.",
    firm: Optional[Dict[str, Any]] = None,
    title_override: str = "",
    group_by: str = "",
) -> bytes:
    """Statutory SALARY REGISTER — replica of the user's reference format
    (Form No. 27(1) / rule 78(1)(a)(i)) in LANDSCAPE A4 (Iter 137 user
    request), grouped EARNINGS / DEDUCTIONS columns, GRAND TOTAL row and a
    final summary page with amounts in words + signature block."""
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import (
        BaseDocTemplate, Frame, PageTemplate, PageBreak,
        Paragraph, Spacer, Table, TableStyle,
    )
    from utils.salary_register_pdf import _num_to_words_inr

    firm = firm or {}
    rows: List[Dict[str, Any]] = list(run.get("rows") or [])
    month = str(run.get("month") or "")
    try:
        _y, _m = int(month[:4]), int(month[5:7])
        month_label = datetime(_y, _m, 1).strftime("%b %Y").upper()
    except Exception:
        month_label = month
    month_days = run.get("month_days") or run.get("default_month_days") or ""
    group = (run.get("employee_type") or "ALL").upper()

    # Iter 372 (user request) — allowance & deduction HEADS are DYNAMIC per
    # firm: only heads enabled in the Firm Master appear as columns (same
    # masks the on-screen grid uses, stamped on every row by the engine).
    _r0 = rows[0] if rows else {}
    _en = _r0.get("enabled_allowances")
    _ed = _r0.get("enabled_deductions")

    def _has_a(k: str) -> bool:
        return (_en is None) or (k in _en) or k == "basic"

    def _has_d(k: str) -> bool:
        return (_ed is None) or (k in _ed)

    show_hra = _has_a("hra")
    show_conv = _has_a("conveyance")
    show_oth_m = any(_has_a(k) for k in ("medical", "special", "others"))
    show_oth_e = show_oth_m or any(float(r.get("ot_pay") or 0) for r in rows)
    show_pf = _has_d("pf")
    show_esi = _has_d("esi")
    show_tds = _has_d("tds")
    # Iter 645 (user request) — custom allowance heads (INCENTIVE / …) get
    # their OWN columns in the register (decomposed out of OTHER).
    _alab = _allow_head_labels(rows)

    def A(v: Any) -> str:
        # Iter 323 (user request) — whole rupees only, no ".00".
        try:
            return str(int(round(float(v or 0))))
        except Exception:
            return "0"

    # ---- per-row derived values -----------------------------------------
    def other_earn(r: Dict[str, Any]) -> float:
        # Iter 401 (user check) — RESIDUAL (gross − basic − hra − conv) so
        # the EARNINGS columns always tally to the TOTAL column. Daily-rated
        # rows keep the medical/special/other value inside gross while the
        # earned heads stay 0, so summing the heads under-reported "Other".
        g = float(r.get("gross_paid") or 0)
        if g:
            return g - (float(r.get("basic") or 0) + float(r.get("hra") or 0)
                        + float(r.get("conveyance") or 0))
        return (float(r.get("medical") or 0) + float(r.get("special") or 0)
                + float(r.get("others") or 0) + float(r.get("ot_pay") or 0))

    def other_master(r: Dict[str, Any]) -> float:
        return (float(r.get("medical_master") or 0)
                + float(r.get("special_master") or 0)
                + float(r.get("others_master") or 0))

    def pf_ded(r: Dict[str, Any]) -> float:
        return float(r.get("pf_employee") or 0) + float(r.get("vpf_amount") or 0)

    def other_ded(r: Dict[str, Any]) -> float:
        # Iter 489 (user bug) — ADVANCE has its OWN column: it no longer
        # hides inside OTHER.
        return (float(r.get("other_deduction") or 0)
                + float(r.get("master_deduction") or 0)
                + float(r.get("pt") or 0))

    def adv_ded(r: Dict[str, Any]) -> float:
        return float(r.get("advance_recovery") or 0)

    # Iter 401 — show the Other columns whenever any row actually carries a
    # value there, even if the head is not in the firm's enabled allowances
    # (daily-rated firms keep medical/special only on the master).
    show_oth_m = show_oth_m or any(abs(other_master(r)) >= 0.5 for r in rows)
    show_oth_e = show_oth_e or any(abs(other_earn(r)) >= 0.5 for r in rows)
    # Iter 489 (user request) — DEDUCTION columns fully dynamic per the
    # compliance salary process: ADVANCE / OTHER appear only when the head
    # is enabled in the Firm Master or a row actually carries a value.
    show_adv = _has_d("advance") or any(abs(adv_ded(r)) >= 0.5 for r in rows)
    show_othd = (_ed is None) or any(abs(other_ded(r)) >= 0.5 for r in rows)

    # ---- header (drawn on every page) ------------------------------------
    W, H = landscape(A4)
    pf_code = str(firm.get("pf_code") or "")
    esi_code = str(firm.get("esi_code") or "")
    address = str(firm.get("address") or "")

    class _NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for st in self._saved:
                self.__dict__.update(st)
                self.setFont("Helvetica", 7)
                self.setFillColor(rl_colors.black)
                self.drawRightString(W - 6 * mm, H - 6 * mm, f"Page {self._pageNumber} of {total}")
                super().showPage()
            super().save()

    def _header(c, d):
        c.saveState()
        c.setFillColor(rl_colors.black)
        # Iter 330 (user request) — larger report header fonts.
        c.setFont("Helvetica", 8)
        c.drawString(6 * mm, H - 7.5 * mm, "[rule 78 (1) (a) (i)]")
        c.setFont("Helvetica-Bold", 9)
        c.drawString(6 * mm, H - 12 * mm, f"P.F.Code: {pf_code}")
        c.drawString(6 * mm, H - 16.5 * mm, f"ESI Code: {esi_code}")
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(W / 2, H - 7.5 * mm, f"{title_override or 'SALARY REGISTER'} ({group})")
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(W / 2, H - 13 * mm, f"M/S. {company_name.upper()}")
        c.setFont("Helvetica", 8)
        c.drawCentredString(W / 2, H - 17.5 * mm, address)
        c.setFont("Helvetica", 9)
        c.drawRightString(W - 6 * mm, H - 8.5 * mm, "Register of Wages Form No. 27 (1)")
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(W - 6 * mm, H - 12.5 * mm, f"Month Days {month_days}")
        c.drawRightString(W - 6 * mm, H - 16.5 * mm, f"FOR THE MONTH {month_label}")
        c.restoreState()

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=landscape(A4),
        # Iter 433 (user request) — reduced L/R page margins.
        leftMargin=3 * mm, rightMargin=3 * mm,
        topMargin=20 * mm, bottomMargin=8 * mm,
        title=f"Salary Register — {month}",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, W - 6 * mm,
                  H - doc.topMargin - doc.bottomMargin, id="f")
    doc.addPageTemplates([PageTemplate(id="pg", frames=[frame], onPage=_header)])

    # ---- table ------------------------------------------------------------
    # Iter 323 (user request) — MASTER SALARY & ALLOWANCES band inserted
    # between DESIG. and DAYS/HRS, figures centre-aligned, wider SIGN column.
    # Iter 372 (user request) — the bands are built DYNAMICALLY from the
    # firm-enabled heads (see show_* flags above).
    m_cols: List[Any] = [("SALARY", "m_sal")]
    if show_hra:
        m_cols.append(("H.R.A", "m_hra"))
    if show_conv:
        m_cols.append(("CONV.", "m_conv"))
    if show_oth_m:
        m_cols.append(("OTHER", "m_oth"))
    # Iter 645 — dynamic custom allowance head columns (master band).
    for _j, _l in enumerate(_alab):
        m_cols.append((str(_l), f"ma{_j}"))
    m_cols.append(("TOTAL", "m_tot"))
    e_cols: List[Any] = [("SALARY", "sal")]
    if show_hra:
        e_cols.append(("H.R.A", "hra"))
    if show_conv:
        e_cols.append(("CONV.", "conv"))
    if show_oth_e:
        e_cols.append(("OTHER", "oth"))
    # Iter 645 — dynamic custom allowance head columns (earnings band).
    for _j, _l in enumerate(_alab):
        e_cols.append((str(_l), f"ea{_j}"))
    e_cols.append(("TOTAL", "gross"))
    d_cols: List[Any] = []
    if show_pf:
        d_cols.append(("P.F.", "pf"))
    if show_esi:
        d_cols.append(("E.S.I.", "esi"))
    if show_adv:
        d_cols.append(("ADVANCE", "adv"))
    if show_othd:
        d_cols.append(("OTHER", "othd"))
    if show_tds:
        d_cols.append(("TDS", "tds"))
    d_cols.append(("TOTAL", "ded"))
    M0 = 4
    DAYS_I = M0 + len(m_cols)
    E0 = DAYS_I + 1
    D0 = E0 + len(e_cols)
    NET_I = D0 + len(d_cols)
    SIGN_I = NET_I + 1
    NCOLS = SIGN_I + 1
    hdr_top = (
        # Iter 372 (user request) — per-employee "UAN No./P.F./ESI" labels
        # removed from the rows; the column heading identifies them instead.
        ["S.No", "NAME /\nFATHER NAME", "UAN / P.F.NO. /\nESI NO.", "DESIG."]
        + ["-------- MASTER SALARY & ALLOWANCES --------"] + [""] * (len(m_cols) - 1)
        + ["DAYS\n/HRS"]
        + ["-------------- EARNINGS --------------"] + [""] * (len(e_cols) - 1)
        + ["------------- DEDUCTIONS -------------"] + [""] * (len(d_cols) - 1)
        + ["NET\nPAYABLE", "SIGN. /\nBANK"]
    )
    hdr_sub = (
        ["", "", "", ""]
        + [h for h, _k in m_cols] + [""]
        + [h for h, _k in e_cols] + [h for h, _k in d_cols]
        + ["AMOUNT", "DATE OF\nPAYMENT"]
    )
    data: List[List[Any]] = [hdr_top, hdr_sub]

    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=6.5, leading=7.5)
    # Iter 372 (user bug) — long UAN / EPF numbers used to OVERWRITE the
    # neighbouring columns; CJK word-wrap breaks anywhere within the cell.
    idcell = ParagraphStyle("idcell", fontName="Helvetica", fontSize=6,
                            leading=7, wordWrap="CJK")
    tot = {k: 0.0 for k in (
        "days", "hrs", "sal", "hra", "conv", "oth", "gross",
        "m_sal", "m_hra", "m_conv", "m_oth", "m_tot",
        "pf", "esi", "adv", "othd", "tds", "ded", "net",
        "pf_wages", "gross_pf", "gross_nonpf", "esi_base", "nonesi_base",
    )}
    # Iter 645 — dynamic allowance head totals.
    for _j in range(len(_alab)):
        tot[f"ma{_j}"] = 0.0
        tot[f"ea{_j}"] = 0.0
    # Iter 324 (user request) — optional GROUPING with per-group sub-totals.
    body_items: List[Dict[str, Any]] = []
    g_tot = {k: 0.0 for k in tot}
    cur_g: Optional[str] = None
    _grp_head = {"employee_group": "GROUP", "department": "DEPARTMENT",
                 "designation": "DESIGNATION"}.get(group_by, "GROUP")

    def _grp_val(r: Dict[str, Any]) -> str:
        if group_by == "employee_group":
            return str(r.get("employee_group") or r.get("employee_type") or "No Group").upper()
        if group_by == "department":
            return str(r.get("department") or "No Department").upper()
        if group_by == "designation":
            return str(r.get("designation") or "No Designation").upper()
        return ""

    def _sub_cells(gname: str, g: Dict[str, float]) -> List[Any]:
        return (
            ["", f"TOTAL — {gname}", "", ""]
            + [A(g[k]) for _h, k in m_cols]
            + [f"{g['days']:g}/{g['hrs']:g}"]
            + [A(g[k]) for _h, k in e_cols]
            + [A(g[k]) for _h, k in d_cols]
            + [A(g["net"]), ""]
        )

    for i, r in enumerate(rows, start=1):
        if group_by:
            gv = _grp_val(r)
            if gv != cur_g:
                if cur_g is not None:
                    body_items.append({"kind": "sub", "cells": _sub_cells(cur_g, g_tot)})
                cur_g = gv
                for _k in g_tot:
                    g_tot[_k] = 0.0
                body_items.append({"kind": "hdr",
                                   "cells": [f"{_grp_head}: {gv}"]
                                   + [""] * (NCOLS - 1)})
        days = float(r.get("present_days") or 0)
        hrs = float(r.get("ot_hours") or 0)
        oth_e = other_earn(r)
        pf_v = pf_ded(r)
        oth_d = other_ded(r)
        adv_v = adv_ded(r)
        gross = float(r.get("gross_paid") or 0)
        m_sal = float(r.get("basic_master") or 0)
        m_hra = float(r.get("hra_master") or 0)
        m_conv = float(r.get("conveyance_master") or 0)
        m_oth = other_master(r)
        m_tot = m_sal + m_hra + m_conv + m_oth
        # Iter 645 — decompose custom allowance heads out of the OTHER
        # columns (band totals unchanged: OTHER shows the remainder).
        _ah = r.get("allowance_heads") or {}
        _ahm = r.get("allowance_heads_master") or {}
        _ah_vals = [float(_ah.get(_l) or 0) for _l in _alab]
        _ahm_vals = [float(_ahm.get(_l) or 0) for _l in _alab]
        oth_e -= sum(_ah_vals)
        m_oth -= sum(_ahm_vals)
        _pairs = (
            ("days", days), ("hrs", hrs),
            ("m_sal", m_sal), ("m_hra", m_hra), ("m_conv", m_conv),
            ("m_oth", m_oth), ("m_tot", m_tot),
            ("sal", float(r.get("basic") or 0)), ("hra", float(r.get("hra") or 0)),
            ("conv", float(r.get("conveyance") or 0)), ("oth", oth_e),
            ("gross", gross),
            ("pf", pf_v), ("esi", float(r.get("esic_employee") or 0)),
            ("adv", adv_v),
            ("othd", oth_d), ("tds", float(r.get("tds") or 0)),
            ("ded", float(r.get("total_deduction") or 0)),
            ("net", float(r.get("net") or 0)),
            *[(f"ma{_j}", _ahm_vals[_j]) for _j in range(len(_alab))],
            *[(f"ea{_j}", _ah_vals[_j]) for _j in range(len(_alab))],
        )
        for _k, _v in _pairs:
            tot[_k] += _v
            g_tot[_k] += _v
        if r.get("pf_applicable"):
            tot["pf_wages"] += float(r.get("pf_wages") or 0)
            tot["gross_pf"] += gross
        else:
            tot["gross_nonpf"] += gross
        if r.get("esic_applicable"):
            tot["esi_base"] += float(r.get("esic_wage_base") or gross)
        else:
            tot["nonesi_base"] += gross
        name_p = Paragraph(
            f"{(r.get('name') or '').upper()}<br/>S/O {(r.get('father_name') or '').upper()}", cell)
        # Iter 372 (user request) — plain numbers only (no per-row labels);
        # heading column identifies UAN / P.F. / ESI. wordWrap fixes the
        # EPF-No.-overwriting-columns bug.
        ids_p = Paragraph(
            f"{r.get('uan_no') or '-'}<br/>{r.get('pf_no') or '-'}"
            f"<br/>{r.get('esi_ip_no') or '-'}", idcell)
        _rv = {
            "m_sal": m_sal, "m_hra": m_hra, "m_conv": m_conv,
            "m_oth": m_oth, "m_tot": m_tot,
            "sal": r.get("basic"), "hra": r.get("hra"),
            "conv": r.get("conveyance"), "oth": oth_e, "gross": gross,
            "pf": pf_v, "esi": r.get("esic_employee"), "adv": adv_v,
            "othd": oth_d, "tds": r.get("tds"), "ded": r.get("total_deduction"),
            # Iter 645 — dynamic custom allowance head cells.
            **{f"ma{_j}": _ahm_vals[_j] for _j in range(len(_alab))},
            **{f"ea{_j}": _ah_vals[_j] for _j in range(len(_alab))},
        }
        data.append(
            [str(i), name_p, ids_p,
             Paragraph((r.get("designation") or "").upper(), cell)]
            + [A(_rv[k]) for _h, k in m_cols]
            + [f"{days:g}/{('%g' % hrs) if hrs else ''}"]
            + [A(_rv[k]) for _h, k in e_cols]
            + [A(_rv[k]) for _h, k in d_cols]
            + [A(r.get("net")), ""]
        )
        body_items.append({"kind": "emp", "cells": data[-1]})
    if group_by and cur_g is not None:
        body_items.append({"kind": "sub", "cells": _sub_cells(cur_g, g_tot)})
    grand_row = (
        ["", "GRAND TOTAL", "", ""]
        + [A(tot[k]) for _h, k in m_cols]
        + [f"{tot['days']:g}/{tot['hrs']:g}"]
        + [A(tot[k]) for _h, k in e_cols]
        + [A(tot[k]) for _h, k in d_cols]
        + [A(tot["net"]), ""]
    )

    # Iter 323 — wider SIGN column for physical signatures.
    def _wcol(h: str, first: bool) -> float:
        if h == "TOTAL":
            return 9
        if h == "TDS":
            return 6
        return 8 if first else 7

    widths = ([5, 20, 18, 10]
              + [_wcol(h, j == 0) for j, (h, _k) in enumerate(m_cols)]
              + [7]
              + [_wcol(h, j == 0) for j, (h, _k) in enumerate(e_cols)]
              + [_wcol(h, False) for h, _k in d_cols]
              + [10, 18])
    # Landscape — stretch the reference column ratios to the full width.
    _scale = (W - 6 * mm) / (sum(widths) * mm)
    col_widths = [wmm * mm * _scale for wmm in widths]

    def _base_style() -> list:
        return [
            # Iter 372 — dynamic band spans (columns vary per firm).
            ("SPAN", (M0, 0), (DAYS_I - 1, 0)),   # MASTER SALARY band
            ("SPAN", (E0, 0), (D0 - 1, 0)),       # EARNINGS band
            ("SPAN", (D0, 0), (NET_I - 1, 0)),    # DEDUCTIONS band
            ("SPAN", (0, 0), (0, 1)), ("SPAN", (1, 0), (1, 1)), ("SPAN", (2, 0), (2, 1)),
            ("SPAN", (3, 0), (3, 1)), ("SPAN", (DAYS_I, 0), (DAYS_I, 1)),
            ("SPAN", (NET_I, 0), (NET_I, 1)), ("SPAN", (SIGN_I, 0), (SIGN_I, 1)),
            # Iter 326 (user request) — heading highlighted like Format 2.
            ("BACKGROUND", (0, 0), (-1, 1), rl_colors.HexColor("#0F3B5C")),
            ("TEXTCOLOR", (0, 0), (-1, 1), rl_colors.white),
            ("BACKGROUND", (M0, 0), (DAYS_I - 1, 1), rl_colors.HexColor("#1B5480")),
            ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 1), 6),
            ("FONTNAME", (0, 2), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 2), (-1, -1), 6),
            ("ALIGN", (0, 0), (-1, 1), "CENTER"),
            # Iter 323 (user request) — figures centre-aligned.
            ("ALIGN", (M0, 2), (-1, -1), "CENTER"),
            ("ALIGN", (0, 2), (0, -1), "CENTER"),
            # Iter 435 (user request) — Name column LEFT-aligned.
            ("ALIGN", (1, 2), (1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.black),
            ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]

    # Iter 157 (user request) — fixed 10 employees per A4-landscape page.
    PER_PAGE = 10
    chunks = [body_items[i:i + PER_PAGE]
              for i in range(0, len(body_items), PER_PAGE)] or [[]]
    page_tables: List[Any] = []
    for ci, ch in enumerate(chunks):
        is_final = ci == len(chunks) - 1
        d = [hdr_top, hdr_sub] + [it["cells"] for it in ch] + ([grand_row] if is_final else [])
        # Iter 322 — fixed 15 mm employee rows; group header / sub-total 9 mm.
        row_heights = [None, None] + [
            (15 * mm if it["kind"] == "emp" else 9 * mm) for it in ch
        ] + ([None] if is_final else [])
        t = Table(d, colWidths=col_widths, repeatRows=2, rowHeights=row_heights)
        st = _base_style()
        # Iter 324 — group header / sub-total styling.
        for j, it in enumerate(ch):
            ri = 2 + j
            if it["kind"] == "hdr":
                st += [
                    ("SPAN", (0, ri), (-1, ri)),
                    ("BACKGROUND", (0, ri), (-1, ri), rl_colors.HexColor("#DCE6EE")),
                    ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
                    ("FONTSIZE", (0, ri), (-1, ri), 7),
                    ("ALIGN", (0, ri), (-1, ri), "LEFT"),
                ]
            elif it["kind"] == "sub":
                st += [
                    ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
                    ("BACKGROUND", (0, ri), (-1, ri), rl_colors.HexColor("#F2F2F2")),
                ]
        if is_final:
            st.append(("FONTNAME", (0, len(d) - 1), (-1, len(d) - 1), "Helvetica-Bold"))
        t.setStyle(TableStyle(st))
        page_tables.append(t)

    # ---- summary page -----------------------------------------------------
    lbl = ParagraphStyle("lbl", fontName="Helvetica", fontSize=8, leading=11)
    lblb = ParagraphStyle("lblb", fontName="Helvetica-Bold", fontSize=8, leading=11)

    def sec(pairs, bold_last=True):
        d = [[Paragraph(k, lblb if (bold_last and i == len(pairs) - 1) else lbl),
              Paragraph(v, lblb if (bold_last and i == len(pairs) - 1) else lbl)]
             for i, (k, v) in enumerate(pairs)]
        t = Table(d, colWidths=[62 * mm, 32 * mm])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, rl_colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, rl_colors.HexColor("#999999")),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ]))
        return t

    story: List[Any] = []
    for t in page_tables:
        story.append(t)
        story.append(PageBreak())
    # Iter 372 (user request) — summary lines follow the firm-enabled heads.
    _sum1 = [("No. Of Emp", str(len(rows))),
             ("Total Salary Amount", A(tot["sal"]))]
    if show_hra:
        _sum1.append(("Total H.R.A Amount", A(tot["hra"])))
    if show_conv:
        _sum1.append(("Total Conveyance Amount", A(tot["conv"])))
    if show_oth_e:
        _sum1.append(("Total Other Amount", A(tot["oth"])))
    _sum1 += [("Total Bonus Amount", "0"),
              ("Total Gross Amount", A(tot["gross"]))]
    story.append(sec(_sum1))
    story.append(Spacer(1, 4 * mm))
    _sum2: List[Any] = []
    if show_pf:
        _sum2 += [("P.F. Deduction Amount", A(tot["pf"])),
                  ("ABRY P.F. Benifit", "0")]
    if show_esi:
        _sum2.append(("E.S.I. Deduction Amount", A(tot["esi"])))
    _sum2 += [("Advance Deduction Amount", "0"),
              ("Other Deduction Amount", A(tot["othd"]))]
    if show_tds:
        _sum2.append(("TDS Deduction Amount", A(tot["tds"])))
    _sum2.append(("Total Deduction Amount", A(tot["ded"])))
    story.append(sec(_sum2))
    story.append(Spacer(1, 4 * mm))
    _sum3: List[Any] = []
    if show_pf:
        _sum3 += [
            ("Total Salary of P.F.", A(tot["pf_wages"])),
            ("Total Less Salary on PF", A(max(0.0, tot["gross_pf"] - tot["pf_wages"]))),
            ("Total Salary of non-P.F", A(tot["gross_nonpf"])),
        ]
    if show_esi:
        _sum3 += [
            ("Total Salary+HRA+CONV(ESI)", A(tot["esi_base"])),
            ("Total Salary+HRA+CONV(NON-ESI)", A(tot["nonesi_base"])),
        ]
    if _sum3:
        story.append(sec(_sum3, bold_last=False))
        story.append(Spacer(1, 4 * mm))
    story.append(sec([
        ("Total Days ->", f"{tot['days']:g}"),
        ("Total Hours ->", f"{tot['hrs']:g}"),
        ("Net Payable Amount", A(tot["net"])),
    ]))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        f"RUPEES: {_num_to_words_inr(int(round(tot['gross'])))} (GROSS)", lblb))
    story.append(Paragraph(
        f"RUPEES: {_num_to_words_inr(int(round(tot['net'])))} (NET PAYABLE)", lblb))
    story.append(Spacer(1, 14 * mm))
    # Iter 324 (user request) — signature block aligned to the RIGHT side
    # of the summary page.
    lblr = ParagraphStyle("lblr", parent=lbl, alignment=2)
    lblbr = ParagraphStyle("lblbr", parent=lblb, alignment=2)
    foot = Table([
        [Paragraph("Checked by", lblb), Paragraph(f"For {company_name.upper()}", lblbr)],
        [Paragraph("Payment Date ______________", lbl),
         Paragraph("AUTHORISED SIGNATORY/MANAGER", lblbr)],
    ], colWidths=[95 * mm, 95 * mm])
    foot.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 1), (-1, 1), 12),
    ]))
    story.append(foot)

    from utils.pdf_branding import punchline_flowables
    story.extend(punchline_flowables())
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()


def build_compliance_register_pdf_v2(
    run: Dict[str, Any],
    company_name: str = "S.K. Sharma & Co.",
    firm: Optional[Dict[str, Any]] = None,
    layout: Optional[Dict[str, Any]] = None,
    title_override: str = "",
    group_by: str = "",
) -> bytes:
    """Iter 137 — OPTION 2 (recommended modern format).

    Landscape A4 register: colour title band, zebra-striped rows, clear
    per-employee columns (Code / Name / UAN / ESI / Days / earnings /
    deductions / NET), repeating header, page numbers and a compact
    summary + signature strip on the final page."""
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import (
        BaseDocTemplate, Frame, PageTemplate, PageBreak,
        Paragraph, Spacer, Table, TableStyle,
    )
    from utils.salary_register_pdf import _num_to_words_inr

    firm = firm or {}
    rows: List[Dict[str, Any]] = list(run.get("rows") or [])
    month = str(run.get("month") or "")
    try:
        _y, _m = int(month[:4]), int(month[5:7])
        month_label = datetime(_y, _m, 1).strftime("%B %Y")
    except Exception:
        month_label = month
    group = (run.get("employee_type") or "All Employees").upper()
    # Iter 273 (user request) — header shows the Salary Month Days used by
    # the Compliance Salary process (the pro-ration divisor).
    try:
        month_days_hdr = int(run.get("month_days") or 0)
    except Exception:
        month_days_hdr = 0
    pf_code = str(firm.get("pf_code") or "")
    esi_code = str(firm.get("esi_code") or "")
    address = str(firm.get("address") or "")

    BRAND = rl_colors.HexColor("#0F3B5C")
    BAND = rl_colors.HexColor("#EAF1F7")
    ZEBRA = rl_colors.HexColor("#F6F8FA")

    W, H = landscape(A4)

    def A(v: Any) -> str:
        # Iter 323 (user request) — whole rupees only, no ".00".
        try:
            return f"{int(round(float(v or 0))):,}"
        except Exception:
            return "0"

    class _NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for st in self._saved:
                self.__dict__.update(st)
                self.setFont("Helvetica", 7)
                self.setFillColor(rl_colors.HexColor("#666666"))
                self.drawRightString(W - 8 * mm, 5 * mm,
                                     f"Page {self._pageNumber} of {total}")
                super().showPage()
            super().save()

    def _header(c, d):
        c.saveState()
        c.setFillColor(BRAND)
        c.rect(0, H - 20 * mm, W, 20 * mm, stroke=0, fill=1)
        c.setFillColor(rl_colors.white)
        # Iter 330 (user request) — larger report header fonts.
        c.setFont("Helvetica-Bold", 15)
        c.drawString(8 * mm, H - 9 * mm, company_name.upper())
        c.setFont("Helvetica", 9)
        if address:
            c.drawString(8 * mm, H - 14 * mm, address[:140])
        c.setFont("Helvetica", 9)
        codes = "   ·   ".join(x for x in [
            f"PF Code: {pf_code}" if pf_code else "",
            f"ESI Code: {esi_code}" if esi_code else "",
            f"Group: {group}",
        ] if x)
        c.drawString(8 * mm, H - 18.2 * mm, codes)
        c.setFont("Helvetica-Bold", 13)
        c.drawRightString(W - 8 * mm, H - 9 * mm, title_override or "SALARY REGISTER (COMPLIANCE)")
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(W - 8 * mm, H - 14.5 * mm, month_label)
        if month_days_hdr:
            c.setFont("Helvetica", 9)
            c.drawRightString(W - 8 * mm, H - 18.5 * mm,
                              f"Salary Month Days: {month_days_hdr}")
        c.restoreState()

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=landscape(A4),
        # Iter 433 (user request) — reduced L/R page margins.
        leftMargin=4 * mm, rightMargin=4 * mm,
        topMargin=24 * mm, bottomMargin=10 * mm,
        title=f"Salary Register (Option 2) — {month}",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, W - 8 * mm,
                  H - doc.topMargin - doc.bottomMargin, id="f")
    doc.addPageTemplates([PageTemplate(id="pg", frames=[frame], onPage=_header)])

    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=7.8, leading=9)
    # Iter 623 (user bug — Format 2) — long UAN / EPF / ESIC numbers used to
    # OVERWRITE the neighbouring columns (plain strings never wrap in
    # reportlab). Same fix as Format 1 (Iter 372): CJK word-wrap breaks
    # anywhere within the cell so the value stays inside its own column.
    idcell = ParagraphStyle("idcell2", fontName="Helvetica", fontSize=6.4,
                            leading=7.2, alignment=1, wordWrap="CJK")

    # Iter 162 — layout-driven columns (choose / order / rename / widths),
    # saved ONE TIME in Settings and applied on every download.
    layout = layout or {}
    _defaults = {k: (h, w) for k, h, w, _n in V2_REGISTER_COLUMNS}
    _numeric = {k for k, _h, _w, n in V2_REGISTER_COLUMNS if n}
    cols_spec = [c for c in (layout.get("columns") or [])
                 if isinstance(c, dict) and c.get("key") in _defaults]
    if not cols_spec:
        cols_spec = [{"key": k} for k, _h, _w, _n in V2_REGISTER_COLUMNS]
    else:
        # Iter 322 (user request) — the statutory ID columns (UAN / EPF /
        # ESIC No.) must appear even on layouts saved BEFORE they existed:
        # inject them right after Desig. (or Name).
        _have = {c["key"] for c in cols_spec}
        if not _have & {"uan", "pf_no", "esi_no"}:
            _pos = next((i + 1 for i in range(len(cols_spec) - 1, -1, -1)
                         if cols_spec[i]["key"] in ("desig", "name")), 1)
            cols_spec[_pos:_pos] = [{"key": "uan"}, {"key": "pf_no"},
                                    {"key": "esi_no"}]
        # Iter 326 (user request) — Signature column always present (at the
        # end) even on layouts saved before it existed.
        if "sign" not in {c["key"] for c in cols_spec}:
            cols_spec.append({"key": "sign"})
        # Iter 489 (user bug) — ADVANCE column injected into layouts saved
        # before it existed (right before Other Ded. / after ESI).
        if "advance" not in {c["key"] for c in cols_spec}:
            _apos = next((i for i, c in enumerate(cols_spec)
                          if c["key"] in ("other_ded", "tds", "total_ded")),
                         len(cols_spec) - 1)
            cols_spec.insert(_apos, {"key": "advance"})
    # Iter 372 (user request) — heads DYNAMIC per firm: drop columns whose
    # head is disabled in the Firm Master (same masks as the grid).
    _r0v2 = rows[0] if rows else {}
    _env2 = _r0v2.get("enabled_allowances")
    _edv2 = _r0v2.get("enabled_deductions")

    def _has_a2(k: str) -> bool:
        return (_env2 is None) or (k in _env2) or k == "basic"

    def _has_d2(k: str) -> bool:
        return (_edv2 is None) or (k in _edv2)

    _show_oth2 = (any(_has_a2(k) for k in ("medical", "special", "others"))
                  or any(float(r.get("ot_pay") or 0) for r in rows)
                  # Iter 401 — also when a residual Other exists (daily-rated
                  # firms carry medical/special inside gross only).
                  or any(abs(float(r.get("gross_paid") or 0)
                             - float(r.get("basic") or 0)
                             - float(r.get("hra") or 0)
                             - float(r.get("conveyance") or 0)) >= 0.5
                         for r in rows))
    _col_ok = {
        "hra": _has_a2("hra"), "conv": _has_a2("conveyance"),
        "other_earn": _show_oth2, "pf": _has_d2("pf"),
        "esi": _has_d2("esi"), "tds": _has_d2("tds"),
        # Iter 489 — Advance / Other Ded. dynamic per the compliance
        # salary process (enabled head OR an actual value on any row).
        "advance": (_has_d2("advance")
                    or any(abs(float(r.get("advance_recovery") or 0)) >= 0.5
                           for r in rows)),
        "other_ded": ((_edv2 is None)
                      or any(abs(float(r.get("other_deduction") or 0)
                                 + float(r.get("master_deduction") or 0)
                                 + float(r.get("pt") or 0)) >= 0.5
                             for r in rows)),
    }
    cols_spec = [c for c in cols_spec if _col_ok.get(c["key"], True)]
    # Iter 645 (user request) — dynamic custom allowance head columns
    # (INCENTIVE / …) injected right before Other Earn (or Gross); the
    # Other Earn column shows the remainder.
    _alab2 = _allow_head_labels(rows)
    if _alab2:
        _apos2 = next((i for i, c in enumerate(cols_spec)
                       if c["key"] in ("other_earn", "gross")),
                      len(cols_spec))
        cols_spec[_apos2:_apos2] = [
            {"key": f"allow::{_l}", "heading": str(_l), "width": 7}
            for _l in _alab2]
    col_keys = [c["key"] for c in cols_spec]
    header = [str(c.get("heading") or _defaults.get(c["key"], (c["key"], 7))[0])
              for c in cols_spec]
    widths = [max(4.0, float(c.get("width")
                             or _defaults.get(c["key"], ("", 7.0))[1]))
              for c in cols_spec]
    data: List[List[Any]] = [header]

    def other_earn(r):
        # Iter 401 (user check) — RESIDUAL (gross − basic − hra − conv) so
        # Basic + HRA + Conv + Other always equals GROSS. The old value used
        # the MASTER medical/special/other heads (Iter 273), which mixed
        # full-month masters with the pro-rated earned Basic/HRA/Conv
        # (Iter 329) and never tallied for part-month / daily-rated rows.
        g = float(r.get("gross_paid") or 0)
        if g:
            return g - (float(r.get("basic") or 0) + float(r.get("hra") or 0)
                        + float(r.get("conveyance") or 0))
        return (float(r.get("medical") or 0) + float(r.get("special") or 0)
                + float(r.get("others") or 0) + float(r.get("ot_pay") or 0))

    def other_ded(r):
        # Iter 489 (user bug) — ADVANCE shown in its own column, not Other.
        return (float(r.get("other_deduction") or 0)
                + float(r.get("master_deduction") or 0)
                + float(r.get("pt") or 0))

    def adv_ded2(r):
        return float(r.get("advance_recovery") or 0)

    tot = {k: 0.0 for k in ("days", "basic", "hra", "conv", "oth", "gross",
                            "pf", "esi", "adv", "othd", "tds", "ded", "net",
                            "hrs", "sal", "hra_e", "conv_e", "oth_e",
                            "pf_wages", "gross_pf", "gross_nonpf",
                            "esi_base", "nonesi_base")}
    # Iter 645 — dynamic allowance head totals.
    for _l in _alab2:
        tot[f"allow::{_l}"] = 0.0
    # Iter 324 (user request) — optional GROUPING with per-group sub-totals.
    body_items: List[Dict[str, Any]] = []
    g_tot = {k: 0.0 for k in tot}
    cur_g: Optional[str] = None
    _grp_head = {"employee_group": "GROUP", "department": "DEPARTMENT",
                 "designation": "DESIGNATION"}.get(group_by, "GROUP")

    def _grp_val(r: Dict[str, Any]) -> str:
        if group_by == "employee_group":
            return str(r.get("employee_group") or r.get("employee_type") or "No Group").upper()
        if group_by == "department":
            return str(r.get("department") or "No Department").upper()
        if group_by == "designation":
            return str(r.get("designation") or "No Designation").upper()
        return ""

    def _sub_cells(gname: str, g: Dict[str, float]) -> List[Any]:
        sv = {
            "sno": "", "name": f"TOTAL — {gname}", "desig": "",
            "uan": "", "pf_no": "", "esi_no": "",
            "days": f"{g['days']:g}", "basic": A(g["basic"]), "hra": A(g["hra"]),
            "conv": A(g["conv"]), "other_earn": A(g["oth"]), "gross": A(g["gross"]),
            "pf": A(g["pf"]), "esi": A(g["esi"]), "other_ded": A(g["othd"]),
            "tds": A(g["tds"]), "total_ded": A(g["ded"]), "net": A(g["net"]),
            "sign": "",
            **{f"allow::{_l}": A(g.get(f"allow::{_l}")) for _l in _alab2},
        }
        if "name" not in col_keys and col_keys:
            sv[col_keys[0]] = f"TOTAL — {gname}"
        return [sv.get(k, "") for k in col_keys]

    for i, r in enumerate(rows, start=1):
        if group_by:
            gv = _grp_val(r)
            if gv != cur_g:
                if cur_g is not None:
                    body_items.append({"kind": "sub", "cells": _sub_cells(cur_g, g_tot)})
                cur_g = gv
                for _k in g_tot:
                    g_tot[_k] = 0.0
                body_items.append({"kind": "hdr",
                                   "cells": [f"{_grp_head}: {gv}"]
                                   + [""] * (len(col_keys) - 1)})
        days = float(r.get("present_days") or 0)
        oth_e = other_earn(r)
        # Iter 645 — decompose custom allowance heads out of Other Earn.
        _ah2 = r.get("allowance_heads") or {}
        _ah2_vals = {f"allow::{_l}": float(_ah2.get(_l) or 0) for _l in _alab2}
        oth_e -= sum(_ah2_vals.values())
        pf_v = float(r.get("pf_employee") or 0) + float(r.get("vpf_amount") or 0)
        oth_d = other_ded(r)
        adv_v2 = adv_ded2(r)
        _pairs = (
            ("days", days),
            # Iter 329 (user check) — EARNED figures so the earnings columns
            # always add up to the TOTAL (gross earning) column.
            ("basic", float(r.get("basic") or 0)),
            ("hra", float(r.get("hra") or 0)),
            ("conv", float(r.get("conveyance") or 0)),
            ("oth", oth_e),
            *_ah2_vals.items(),
            ("gross", float(r.get("gross_paid") or 0)),
            ("pf", pf_v),
            ("esi", float(r.get("esic_employee") or 0)),
            ("adv", adv_v2),
            ("othd", oth_d),
            ("tds", float(r.get("tds") or 0)),
            ("ded", float(r.get("total_deduction") or 0)),
            ("net", float(r.get("net") or 0)),
        )
        for _k, _v in _pairs:
            tot[_k] += _v
            g_tot[_k] += _v
        # Iter 273 — Format-1-style last-page summary aggregates (EARNED values).
        tot["hrs"] += float(r.get("ot_hours") or 0)
        tot["sal"] += float(r.get("basic") or 0)
        tot["hra_e"] += float(r.get("hra") or 0)
        tot["conv_e"] += float(r.get("conveyance") or 0)
        # Iter 401 — use the same residual Other as the table column so the
        # summary tallies: Salary + HRA + Conv + Other = Gross.
        tot["oth_e"] += oth_e
        _gross_r = float(r.get("gross_paid") or 0)
        if r.get("pf_applicable"):
            tot["pf_wages"] += float(r.get("pf_wages") or 0)
            tot["gross_pf"] += _gross_r
        else:
            tot["gross_nonpf"] += _gross_r
        if r.get("esic_applicable"):
            tot["esi_base"] += float(r.get("esic_wage_base") or _gross_r)
        else:
            tot["nonesi_base"] += _gross_r
        vals = {
            "sno": str(i),
            "name": Paragraph(
                f"<b>{(r.get('name') or '').upper()}</b><br/>{(r.get('father_name') or '').upper()}",
                cell),
            "desig": Paragraph((r.get("designation") or "").upper(), cell),
            # Iter 322 (user request) — statutory ID columns.
            # Iter 623 — wrapped Paragraphs so long IDs can't overflow.
            "uan": Paragraph(str(r.get("uan_no") or "-"), idcell),
            "pf_no": Paragraph(str(r.get("pf_no") or "-"), idcell),
            "esi_no": Paragraph(str(r.get("esi_ip_no") or "-"), idcell),
            "days": f"{days:g}",
            "basic": A(r.get("basic")), "hra": A(r.get("hra")),
            "conv": A(r.get("conveyance")), "other_earn": A(oth_e),
            "gross": A(r.get("gross_paid")), "pf": A(pf_v),
            "esi": A(r.get("esic_employee")), "advance": A(adv_v2),
            "other_ded": A(oth_d),
            "tds": A(r.get("tds")), "total_ded": A(r.get("total_deduction")),
            "net": A(r.get("net")),
            "sign": "",
            **{k2: A(v2) for k2, v2 in _ah2_vals.items()},
        }
        data.append([vals[k] for k in col_keys])
        body_items.append({"kind": "emp", "cells": data[-1]})
    if group_by and cur_g is not None:
        body_items.append({"kind": "sub", "cells": _sub_cells(cur_g, g_tot)})
    tot_vals = {
        "sno": "", "name": "GRAND TOTAL", "desig": "",
        "uan": "", "pf_no": "", "esi_no": "",
        "days": f"{tot['days']:g}", "basic": A(tot["basic"]), "hra": A(tot["hra"]),
        "conv": A(tot["conv"]), "other_earn": A(tot["oth"]), "gross": A(tot["gross"]),
        "pf": A(tot["pf"]), "esi": A(tot["esi"]), "advance": A(tot["adv"]),
        "other_ded": A(tot["othd"]),
        "tds": A(tot["tds"]), "total_ded": A(tot["ded"]), "net": A(tot["net"]),
        "sign": "",
        **{f"allow::{_l}": A(tot.get(f"allow::{_l}")) for _l in _alab2},
    }
    if "name" not in col_keys and col_keys:
        tot_vals[col_keys[0]] = "GRAND TOTAL"
    data.append([tot_vals[k] for k in col_keys])

    _scale = (W - 8 * mm) / (sum(widths) * mm)
    col_widths = [wmm * mm * _scale for wmm in widths]
    _num_idx = [i for i, k in enumerate(col_keys)
                if k in _numeric or k.startswith("allow::")]

    def _v2_style(n_body: int, zebra_offset: int, is_final: bool) -> TableStyle:
        last = n_body + (1 if is_final else 0)  # grand-total row index
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 7.8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.35, rl_colors.HexColor("#B9C4CE")),
            ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        for ci_ in _num_idx:
            style.append(("ALIGN", (ci_, 0), (ci_, -1), "RIGHT"))
        for ci_, k in enumerate(col_keys):
            if k in ("sno", "code", "uan", "pf_no", "esi_no"):
                style.append(("ALIGN", (ci_, 0), (ci_, -1), "CENTER"))
            # Iter 435 (user request) — Name column LEFT-aligned.
            elif k == "name":
                style.append(("ALIGN", (ci_, 1), (ci_, -1), "LEFT"))
        if is_final:
            style.append(("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"))
            style.append(("BACKGROUND", (0, last), (-1, last), BAND))
        for ri in range(1, n_body + 1):
            if (zebra_offset + ri) % 2 == 0:
                style.append(("BACKGROUND", (0, ri), (-1, ri), ZEBRA))
        return TableStyle(style)

    # Iter 157/162 — employees per page + optional fixed row height,
    # both user-configurable in the saved layout.
    try:
        PER_PAGE = max(1, min(50, int(layout.get("per_page") or 10)))
    except Exception:
        PER_PAGE = 10
    try:
        _rh = float(layout.get("row_height") or 0)  # mm; 0 = auto
    except Exception:
        _rh = 0
    grand_row = data[-1]
    item_chunks = [body_items[i:i + PER_PAGE]
                   for i in range(0, len(body_items), PER_PAGE)] or [[]]
    page_tables: List[Any] = []
    for ci, ich in enumerate(item_chunks):
        is_final = ci == len(item_chunks) - 1
        ch = [it["cells"] for it in ich]
        d = [header] + ch + ([grand_row] if is_final else [])
        row_heights = None
        if _rh > 0:
            row_heights = [None] + [
                (_rh * mm if it["kind"] == "emp" else None) for it in ich
            ] + ([None] if is_final else [])
        t = Table(d, colWidths=col_widths, repeatRows=1, rowHeights=row_heights)
        t.setStyle(_v2_style(len(ch), ci * PER_PAGE, is_final))
        # Iter 324 — group header / sub-total styling overrides.
        extra: List[Any] = []
        for j, it in enumerate(ich):
            ri = 1 + j
            if it["kind"] == "hdr":
                extra += [
                    ("SPAN", (0, ri), (-1, ri)),
                    ("BACKGROUND", (0, ri), (-1, ri), rl_colors.HexColor("#D5E3F0")),
                    ("TEXTCOLOR", (0, ri), (-1, ri), BRAND),
                    ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
                    ("FONTSIZE", (0, ri), (-1, ri), 7.5),
                    ("ALIGN", (0, ri), (-1, ri), "LEFT"),
                ]
            elif it["kind"] == "sub":
                extra += [
                    ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
                    ("BACKGROUND", (0, ri), (-1, ri), rl_colors.HexColor("#EFEFEF")),
                ]
        if extra:
            t.setStyle(TableStyle(extra))
        page_tables.append(t)

    lbl = ParagraphStyle("lbl", fontName="Helvetica", fontSize=8.5, leading=12)
    lblb = ParagraphStyle("lblb", fontName="Helvetica-Bold", fontSize=8.5, leading=12)

    # Iter 273 (user request) — Format 2 now shows the SAME detailed
    # last-page summary as Format Option 1.
    def sec(pairs, bold_last=True):
        d = [[Paragraph(k, lblb if (bold_last and i == len(pairs) - 1) else lbl),
              Paragraph(v, lblb if (bold_last and i == len(pairs) - 1) else lbl)]
             for i, (k, v) in enumerate(pairs)]
        t = Table(d, colWidths=[62 * mm, 32 * mm])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, rl_colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, rl_colors.HexColor("#999999")),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ]))
        return t

    # Iter 324 (user request) — signature block aligned to the RIGHT side.
    lblr = ParagraphStyle("lblr2", parent=lblb, alignment=2)
    foot = Table([
        [Paragraph("Checked by ____________________", lbl),
         Paragraph(f"For {company_name.upper()}", lblr)],
        [Paragraph("Payment Date ____________________", lbl),
         Paragraph("AUTHORISED SIGNATORY / MANAGER", lblr)],
    ], colWidths=[(W - 12 * mm) / 2.0] * 2)
    foot.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 1), (-1, 1), 14),
    ]))

    story: List[Any] = []
    for t in page_tables:
        story.append(t)
        story.append(PageBreak())
    # Iter 322 (user report) — the summary page occasionally overflowed by a
    # few mm (long company names / wrapped amount-in-words) leaving a
    # nearly-blank trailing page. Building the summary inside
    # KeepInFrame(shrink) guarantees it always fits on ONE final page.
    from reportlab.platypus import KeepInFrame
    summary: List[Any] = []
    # Iter 372 (user request) — summary lines follow the firm-enabled heads.
    _s1 = [("No. Of Emp", str(len(rows))),
           ("Total Salary Amount", A(tot["sal"]))]
    if _col_ok["hra"]:
        _s1.append(("Total H.R.A Amount", A(tot["hra_e"])))
    if _col_ok["conv"]:
        _s1.append(("Total Conveyance Amount", A(tot["conv_e"])))
    if _col_ok["other_earn"]:
        _s1.append(("Total Other Amount", A(tot["oth_e"])))
    _s1 += [("Total Bonus Amount", "0"),
            ("Total Gross Amount", A(tot["gross"]))]
    summary.append(sec(_s1))
    summary.append(Spacer(1, 4 * mm))
    _s2: List[Any] = []
    if _col_ok["pf"]:
        _s2 += [("P.F. Deduction Amount", A(tot["pf"])),
                ("ABRY P.F. Benifit", "0")]
    if _col_ok["esi"]:
        _s2.append(("E.S.I. Deduction Amount", A(tot["esi"])))
    _s2 += [("Advance Deduction Amount", "0"),
            ("Other Deduction Amount", A(tot["othd"]))]
    if _col_ok["tds"]:
        _s2.append(("TDS Deduction Amount", A(tot["tds"])))
    _s2.append(("Total Deduction Amount", A(tot["ded"])))
    summary.append(sec(_s2))
    summary.append(Spacer(1, 4 * mm))
    _s3: List[Any] = []
    if _col_ok["pf"]:
        _s3 += [
            ("Total Salary of P.F.", A(tot["pf_wages"])),
            ("Total Less Salary on PF", A(max(0.0, tot["gross_pf"] - tot["pf_wages"]))),
            ("Total Salary of non-P.F", A(tot["gross_nonpf"])),
        ]
    if _col_ok["esi"]:
        _s3 += [
            ("Total Salary+HRA+CONV(ESI)", A(tot["esi_base"])),
            ("Total Salary+HRA+CONV(NON-ESI)", A(tot["nonesi_base"])),
        ]
    if _s3:
        summary.append(sec(_s3, bold_last=False))
        summary.append(Spacer(1, 4 * mm))
    summary.append(sec([
        ("Total Days ->", f"{tot['days']:g}"),
        ("Total Hours ->", f"{tot['hrs']:g}"),
        ("Net Payable Amount", A(tot["net"])),
    ]))
    summary.append(Spacer(1, 5 * mm))
    summary.append(Paragraph(
        f"RUPEES: {_num_to_words_inr(int(round(tot['gross'])))} (GROSS)", lblb))
    summary.append(Paragraph(
        f"RUPEES: {_num_to_words_inr(int(round(tot['net'])))} (NET PAYABLE)", lblb))
    summary.append(Spacer(1, 10 * mm))
    summary.append(foot)
    from utils.pdf_branding import punchline_flowables
    summary.extend(punchline_flowables())
    story.append(KeepInFrame(
        W - 12 * mm, H - doc.topMargin - doc.bottomMargin - 2 * mm,
        summary, mode="shrink"))
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()


def parse_month(month_str: str) -> tuple[int, int]:
    m = re.match(r"^(\d{4})-(\d{2})$", (month_str or "").strip())
    if not m:
        raise ValueError("month must be in YYYY-MM format")
    y = int(m.group(1))
    mo = int(m.group(2))
    if not (2020 <= y <= 2100):
        raise ValueError("year out of range")
    if not (1 <= mo <= 12):
        raise ValueError("month must be 1..12")
    return y, mo
