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
DEFAULT_STATUTORY_CFG: Dict[str, float] = {
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
}

_ROUNDING_KEYS = ("pf_rounding", "esic_rounding")

# Iter 162 — column catalog for the customisable v2 register PDF.
# key -> (default heading, default width unit, numeric?)
V2_REGISTER_COLUMNS: List[Any] = [
    ("sno", "S.No", 7, False),
    ("code", "Code", 12, False),
    ("name", "Employee / Father Name", 40, False),
    ("uan_esi", "UAN / ESI No.", 24, False),
    ("desig", "Desig.", 18, False),
    ("days", "Days", 8, True),
    ("basic", "Basic", 13, True),
    ("hra", "HRA", 12, True),
    ("conv", "Conv.", 12, True),
    ("other_earn", "Other", 12, True),
    ("gross", "GROSS", 15, True),
    ("pf", "PF", 12, True),
    ("esi", "ESI", 11, True),
    ("other_ded", "Other Ded.", 12, True),
    ("tds", "TDS", 11, True),
    ("total_ded", "TOTAL DED.", 15, True),
    ("net", "NET PAY", 15, True),
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
) -> Dict[str, Any]:
    """Compute the full compliance salary row for a single employee.

    Args (same shape as ``compute_salary_row``):
        user: Employee doc.
        policy: Merged attendance/pay policy (from user.employee_policy).
        month_days: Divisor for pro-ration when salary_mode='monthly'.
        stats: { present_days, half_days, effective_present, duty_hours, ot_hours }.
    """
    cfg = dict(DEFAULT_STATUTORY_CFG)
    if statutory_cfg:
        for k, v in statutory_cfg.items():
            if v is None:
                continue
            cfg[k] = str(v) if k in _ROUNDING_KEYS else _num(v)

    salary_mode = (policy.get("salary_mode") or "monthly").lower()
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
        if salary_mode == "monthly":
            factor = _safe_div(effective_present, max(1, month_days))
        else:
            factor = 1.0
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
                "basic_amount": round(comp_basic, 2),
                "hra_amount": round(agg["hra"], 2),
                "conv_amount": round(agg["conveyance"], 2),
                "medical_amount": round(agg["medical"], 2),
                "special_amount": round(agg["special"], 2),
                "others_amount": round(agg["others"], 2),
            }
            master_gross_override = comp_basic + allowances_master
        else:
            user = {**user, "basic_amount": round(min(prorated_basic, monthly_gross) if monthly_gross > 0 else prorated_basic, 2)}
            master_user = {**master_user, "basic_amount": round(comp_basic, 2)}
            if monthly_gross <= 0:
                # No compliance_gross/salary on the master — Basic IS the gross.
                monthly_gross = prorated_basic
                master_gross_override = comp_basic
    structure = resolve_structure(user, monthly_gross, company_structure_pct)
    basic = structure["basic"]
    hra = structure["hra"]
    conveyance = structure["conveyance"]
    medical = structure["medical"]
    special = structure["special"]
    others = structure["others"]

    # Gross for statutory purposes:
    # Under new labour code (per client policy), the WAGE BASE for both
    # PF and ESIC is: max(Basic, floor_pct% of Gross Earning).
    # It is capped at ₹15,000 for PF; ESIC applies the same base without
    # a wage cap but only when Gross Earning ≤ ₹21,000.
    gross_paid = monthly_gross + ot_pay  # total "Gross Earning" this month
    floor_pct = _num(cfg.get("stat_wage_floor_pct"), 50.0)
    stat_wage_base = max(basic, gross_paid * (floor_pct / 100.0))

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

    # ---- PF ----
    # Iter 98 — firm-level EPF gate (Firm Master → EPF "Applicable") ANDed
    # with the per-employee flag.
    # Iter 129 (user directive) — PF is calculated ONLY from the Employee
    # Master's "PF Basic Salary" (pf_basic). When it is 0 / blank, NO PF is
    # deducted for that employee, and when filled ALL PF amounts derive
    # from it (pro-rated by attendance for monthly-rated staff).
    pf_basic_override = _num(user.get("pf_basic"), 0.0)
    pf_applicable = (
        firm_pf_enabled
        and user.get("pf_applicable") is not False
        and pf_basic_override > 0
    )
    if pf_applicable:
        if salary_mode == "monthly":
            pf_basic_prorated = _safe_div(
                pf_basic_override * effective_present, max(1, month_days)
            )
        else:
            pf_basic_prorated = pf_basic_override
        # Iter 254 (user directive) — PF is calculated STRICTLY on the
        # Employee Master's "PF Basic Salary". The 50%-of-gross floor rule
        # is IGNORED for PF (it previously inflated PF wages above the
        # entered PF Basic, e.g. PF Basic 15000 with a higher gross).
        pf_base = pf_basic_prorated
        capped_pf_wages = min(pf_base, max(cfg["pf_wage_cap"], pf_basic_prorated))
        pf_employee = capped_pf_wages * (cfg["pf_percent_employee"] / 100.0)
        pf_employer_epf = capped_pf_wages * (cfg["pf_percent_employer_epf"] / 100.0)
        pf_employer_eps = capped_pf_wages * (cfg["pf_percent_employer_eps"] / 100.0)
        pf_employer_total = pf_employer_epf + pf_employer_eps
        # Iter 126i — VPF (Voluntary PF): extra EMPLOYEE-side deduction on
        # top of the statutory PF (employer share unchanged). Pro-rated by
        # attendance for monthly-rated staff.
        vpf = 0.0
        if user.get("vpf_enabled"):
            vpf_amt = _num(user.get("vpf_amount"), 0.0)
            if vpf_amt > 0:
                if salary_mode == "monthly":
                    vpf = _safe_div(vpf_amt * effective_present, max(1, month_days))
                else:
                    vpf = vpf_amt
        pf_employee += vpf
        # Iter 127f — whole-rupee statutory rounding (Standard Settings).
        pf_mode = str(cfg.get("pf_rounding") or "nearest")
        pf_employee = _round_stat(pf_employee, pf_mode)
        pf_employer_epf = _round_stat(pf_employer_epf, pf_mode)
        pf_employer_eps = _round_stat(pf_employer_eps, pf_mode)
        pf_employer_total = pf_employer_epf + pf_employer_eps
    else:
        capped_pf_wages = 0.0
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
    if _esic_elig_basic <= 0:
        _esic_elig_basic = master_structure["basic"]
    esic_applicable = (
        firm_esic_enabled
        and user.get("esic_applicable") is not False
        and _esic_elig_basic <= cfg["esic_gross_threshold"]
    )
    if esic_applicable:
        # Iter 130 (user directive) — ESIC is calculated ON BASIC SALARY
        # (earned basic for the month), exactly per the Standard Compliance
        # Settings. No gross-based wage floor is applied to ESIC.
        esic_wage_base = basic
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
    master_deduction = 0.0
    for r in (user.get("compliance_salary_deductions") or []):
        if not isinstance(r, dict):
            continue
        s = str(r.get("head") or "").strip().lower()
        if "pf" in s or "esi" in s or "provident" in s:
            continue
        master_deduction += _num(r.get("amount"), 0.0)

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
        "monthly_gross": round(monthly_gross, 2),
        "gross_paid": round(gross_paid, 2),
        # PF
        "pf_applicable": pf_applicable,
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
        # Totals
        "total_deduction": round(total_deduction, 2),
        "net": round(net, 2),
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


def to_csv(rows: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        row = {k: r.get(k, "") for k in CSV_COLUMNS}
        row["is_onroll"] = "On-roll" if r.get("is_onroll") else "Off-roll"
        row["pf_applicable"] = "Yes" if r.get("pf_applicable") else "No"
        row["esic_applicable"] = "Yes" if r.get("esic_applicable") else "No"
        w.writerow(row)
    return buf.getvalue()


def build_compliance_register_pdf(
    run: Dict[str, Any],
    company_name: str = "S.K. Sharma & Co.",
    firm: Optional[Dict[str, Any]] = None,
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

    def A(v: Any) -> str:
        try:
            return f"{float(v or 0):.2f}"
        except Exception:
            return "0.00"

    # ---- per-row derived values -----------------------------------------
    def other_earn(r: Dict[str, Any]) -> float:
        return (float(r.get("medical") or 0) + float(r.get("special") or 0)
                + float(r.get("others") or 0) + float(r.get("ot_pay") or 0))

    def pf_ded(r: Dict[str, Any]) -> float:
        return float(r.get("pf_employee") or 0) + float(r.get("vpf_amount") or 0)

    def other_ded(r: Dict[str, Any]) -> float:
        return (float(r.get("other_deduction") or 0)
                + float(r.get("master_deduction") or 0)
                + float(r.get("pt") or 0))

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
        c.setFont("Helvetica", 6.5)
        c.drawString(6 * mm, H - 8 * mm, "[rule 78 (1) (a) (i)]")
        c.setFont("Helvetica-Bold", 7)
        c.drawString(6 * mm, H - 12 * mm, f"P.F.Code: {pf_code}")
        c.drawString(6 * mm, H - 16 * mm, f"ESI Code: {esi_code}")
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(W / 2, H - 8 * mm, f"SALARY REGISTER ({group})")
        c.setFont("Helvetica-Bold", 9.5)
        c.drawCentredString(W / 2, H - 12.5 * mm, f"M/S. {company_name.upper()}")
        c.setFont("Helvetica", 6.5)
        c.drawCentredString(W / 2, H - 16.5 * mm, address)
        c.setFont("Helvetica", 7)
        c.drawRightString(W - 6 * mm, H - 9.5 * mm, "Register of Wages Form No. 27 (1)")
        c.setFont("Helvetica-Bold", 7)
        c.drawRightString(W - 6 * mm, H - 13 * mm, f"Month Days {month_days}")
        c.drawRightString(W - 6 * mm, H - 16.5 * mm, f"FOR THE MONTH {month_label}")
        c.restoreState()

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=5 * mm, rightMargin=5 * mm,
        topMargin=20 * mm, bottomMargin=8 * mm,
        title=f"Salary Register — {month}",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, W - 10 * mm,
                  H - doc.topMargin - doc.bottomMargin, id="f")
    doc.addPageTemplates([PageTemplate(id="pg", frames=[frame], onPage=_header)])

    # ---- table ------------------------------------------------------------
    hdr_top = [
        "S.No", "NAME /\nFATHER NAME", "P.F.NO. /\nESI NO.", "DESIG.",
        "DAYS\n/HRS",
        "----------------- EARNINGS -----------------", "", "", "", "",
        "------------------- DEDUCTIONS -------------------", "", "", "", "", "",
        "NET\nPAYABLE", "SIGN. /\nBANK",
    ]
    hdr_sub = [
        "", "", "", "", "",
        "SALARY", "H.R.A", "CONV.", "OTHER", "TOTAL",
        "P.F.", "E.S.I.", "ADVANCE", "OTHER", "TDS", "TOTAL",
        "AMOUNT", "DATE OF\nPAYMENT",
    ]
    data: List[List[Any]] = [hdr_top, hdr_sub]

    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=5.5, leading=6.5)
    tot = {k: 0.0 for k in (
        "days", "hrs", "sal", "hra", "conv", "oth", "gross",
        "pf", "esi", "adv", "othd", "tds", "ded", "net",
        "pf_wages", "gross_pf", "gross_nonpf", "esi_base", "nonesi_base",
    )}
    for i, r in enumerate(rows, start=1):
        days = float(r.get("present_days") or 0)
        hrs = float(r.get("ot_hours") or 0)
        oth_e = other_earn(r)
        pf_v = pf_ded(r)
        oth_d = other_ded(r)
        gross = float(r.get("gross_paid") or 0)
        tot["days"] += days; tot["hrs"] += hrs
        tot["sal"] += float(r.get("basic") or 0); tot["hra"] += float(r.get("hra") or 0)
        tot["conv"] += float(r.get("conveyance") or 0); tot["oth"] += oth_e
        tot["gross"] += gross
        tot["pf"] += pf_v; tot["esi"] += float(r.get("esic_employee") or 0)
        tot["othd"] += oth_d; tot["tds"] += float(r.get("tds") or 0)
        tot["ded"] += float(r.get("total_deduction") or 0)
        tot["net"] += float(r.get("net") or 0)
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
        ids_p = Paragraph(
            f"UAN No. {r.get('uan_no') or '-'}<br/>ESI: {r.get('esi_ip_no') or '-'}", cell)
        data.append([
            str(i), name_p, ids_p,
            Paragraph((r.get("designation") or "").upper(), cell),
            f"{days:g}/{('%g' % hrs) if hrs else ''}",
            A(r.get("basic")), A(r.get("hra")), A(r.get("conveyance")),
            A(oth_e), A(gross),
            A(pf_v), A(r.get("esic_employee")), "0.00", A(oth_d),
            A(r.get("tds")), A(r.get("total_deduction")),
            A(r.get("net")), "",
        ])
    data.append([
        "", "GRAND TOTAL", "", "", f"{tot['days']:g}/{tot['hrs']:g}",
        A(tot["sal"]), A(tot["hra"]), A(tot["conv"]), A(tot["oth"]), A(tot["gross"]),
        A(tot["pf"]), A(tot["esi"]), "0.00", A(tot["othd"]), A(tot["tds"]), A(tot["ded"]),
        A(tot["net"]), "",
    ])

    widths = [6, 26, 23, 13, 8, 11, 9, 9, 9, 11, 9, 8, 8, 9, 8, 11, 12, 10]
    # Landscape — stretch the reference column ratios to the full width.
    _scale = (W - 12 * mm) / (sum(widths) * mm)
    col_widths = [wmm * mm * _scale for wmm in widths]

    def _base_style() -> list:
        return [
            ("SPAN", (5, 0), (9, 0)), ("SPAN", (10, 0), (15, 0)),
            ("SPAN", (0, 0), (0, 1)), ("SPAN", (1, 0), (1, 1)), ("SPAN", (2, 0), (2, 1)),
            ("SPAN", (3, 0), (3, 1)), ("SPAN", (4, 0), (4, 1)),
            ("SPAN", (16, 0), (16, 1)), ("SPAN", (17, 0), (17, 1)),
            ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 1), 6.5),
            ("FONTNAME", (0, 2), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 2), (-1, -1), 6.5),
            ("ALIGN", (0, 0), (-1, 1), "CENTER"),
            ("ALIGN", (4, 2), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 2), (0, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.black),
            ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]

    # Iter 157 (user request) — fixed 10 employees per A4-landscape page.
    PER_PAGE = 10
    body_rows = data[2:-1]  # employee rows (skip the 2 header rows + total)
    grand_row = data[-1]
    chunks = [body_rows[i:i + PER_PAGE]
              for i in range(0, len(body_rows), PER_PAGE)] or [[]]
    page_tables: List[Any] = []
    for ci, ch in enumerate(chunks):
        is_final = ci == len(chunks) - 1
        d = [hdr_top, hdr_sub] + ch + ([grand_row] if is_final else [])
        t = Table(d, colWidths=col_widths, repeatRows=2)
        st = _base_style()
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
    story.append(sec([
        ("No. Of Emp", str(len(rows))),
        ("Total Salary Amount", A(tot["sal"])),
        ("Total H.R.A Amount", A(tot["hra"])),
        ("Total Conveyance Amount", A(tot["conv"])),
        ("Total Other Amount", A(tot["oth"])),
        ("Total Bonus Amount", "0.00"),
        ("Total Gross Amount", A(tot["gross"])),
    ]))
    story.append(Spacer(1, 4 * mm))
    story.append(sec([
        ("P.F. Deduction Amount", A(tot["pf"])),
        ("ABRY P.F. Benifit", "0.00"),
        ("E.S.I. Deduction Amount", A(tot["esi"])),
        ("Advance Deduction Amount", "0.00"),
        ("Other Deduction Amount", A(tot["othd"])),
        ("TDS Deduction Amount", A(tot["tds"])),
        ("Total Deduction Amount", A(tot["ded"])),
    ]))
    story.append(Spacer(1, 4 * mm))
    story.append(sec([
        ("Total Salary of P.F.", A(tot["pf_wages"])),
        ("Total Less Salary on PF", A(max(0.0, tot["gross_pf"] - tot["pf_wages"]))),
        ("Total Salary of non-P.F", A(tot["gross_nonpf"])),
        ("Total Salary+HRA+CONV(ESI)", A(tot["esi_base"])),
        ("Total Salary+HRA+CONV(NON-ESI)", A(tot["nonesi_base"])),
    ], bold_last=False))
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
    foot = Table([
        [Paragraph("Checked by", lblb), Paragraph(f"For {company_name.upper()}", lblb)],
        [Paragraph("Payment Date ______________", lbl),
         Paragraph("AUTHORISED SIGNATORY/MANAGER", lblb)],
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
    pf_code = str(firm.get("pf_code") or "")
    esi_code = str(firm.get("esi_code") or "")
    address = str(firm.get("address") or "")

    BRAND = rl_colors.HexColor("#0F3B5C")
    BAND = rl_colors.HexColor("#EAF1F7")
    ZEBRA = rl_colors.HexColor("#F6F8FA")

    W, H = landscape(A4)

    def A(v: Any) -> str:
        try:
            return f"{float(v or 0):,.2f}"
        except Exception:
            return "0.00"

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
        c.setFont("Helvetica-Bold", 13)
        c.drawString(8 * mm, H - 9 * mm, company_name.upper())
        c.setFont("Helvetica", 7.5)
        if address:
            c.drawString(8 * mm, H - 13.5 * mm, address[:140])
        c.setFont("Helvetica", 7.5)
        codes = "   ·   ".join(x for x in [
            f"PF Code: {pf_code}" if pf_code else "",
            f"ESI Code: {esi_code}" if esi_code else "",
            f"Group: {group}",
        ] if x)
        c.drawString(8 * mm, H - 17.5 * mm, codes)
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(W - 8 * mm, H - 9 * mm, "SALARY REGISTER (COMPLIANCE)")
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(W - 8 * mm, H - 14.5 * mm, month_label)
        c.restoreState()

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=6 * mm, rightMargin=6 * mm,
        topMargin=24 * mm, bottomMargin=10 * mm,
        title=f"Salary Register (Option 2) — {month}",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, W - 12 * mm,
                  H - doc.topMargin - doc.bottomMargin, id="f")
    doc.addPageTemplates([PageTemplate(id="pg", frames=[frame], onPage=_header)])

    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=6.8, leading=8)

    # Iter 162 — layout-driven columns (choose / order / rename / widths),
    # saved ONE TIME in Settings and applied on every download.
    layout = layout or {}
    _defaults = {k: (h, w) for k, h, w, _n in V2_REGISTER_COLUMNS}
    _numeric = {k for k, _h, _w, n in V2_REGISTER_COLUMNS if n}
    cols_spec = [c for c in (layout.get("columns") or [])
                 if isinstance(c, dict) and c.get("key") in _defaults]
    if not cols_spec:
        cols_spec = [{"key": k} for k, _h, _w, _n in V2_REGISTER_COLUMNS]
    col_keys = [c["key"] for c in cols_spec]
    header = [str(c.get("heading") or _defaults[c["key"]][0]) for c in cols_spec]
    widths = [max(4.0, float(c.get("width") or _defaults[c["key"]][1]))
              for c in cols_spec]
    data: List[List[Any]] = [header]

    def other_earn(r):
        return (float(r.get("medical") or 0) + float(r.get("special") or 0)
                + float(r.get("others") or 0) + float(r.get("ot_pay") or 0))

    def other_ded(r):
        return (float(r.get("other_deduction") or 0)
                + float(r.get("master_deduction") or 0)
                + float(r.get("pt") or 0))

    tot = {k: 0.0 for k in ("days", "basic", "hra", "conv", "oth", "gross",
                            "pf", "esi", "othd", "tds", "ded", "net")}
    for i, r in enumerate(rows, start=1):
        days = float(r.get("present_days") or 0)
        oth_e = other_earn(r)
        pf_v = float(r.get("pf_employee") or 0) + float(r.get("vpf_amount") or 0)
        oth_d = other_ded(r)
        tot["days"] += days
        tot["basic"] += float(r.get("basic") or 0)
        tot["hra"] += float(r.get("hra") or 0)
        tot["conv"] += float(r.get("conveyance") or 0)
        tot["oth"] += oth_e
        tot["gross"] += float(r.get("gross_paid") or 0)
        tot["pf"] += pf_v
        tot["esi"] += float(r.get("esic_employee") or 0)
        tot["othd"] += oth_d
        tot["tds"] += float(r.get("tds") or 0)
        tot["ded"] += float(r.get("total_deduction") or 0)
        tot["net"] += float(r.get("net") or 0)
        vals = {
            "sno": str(i),
            "code": str(r.get("employee_code") or ""),
            "name": Paragraph(
                f"<b>{(r.get('name') or '').upper()}</b><br/>{(r.get('father_name') or '').upper()}",
                cell),
            "uan_esi": Paragraph(
                f"{r.get('uan_no') or '-'}<br/>{r.get('esi_ip_no') or '-'}", cell),
            "desig": Paragraph((r.get("designation") or "").upper(), cell),
            "days": f"{days:g}",
            "basic": A(r.get("basic")), "hra": A(r.get("hra")),
            "conv": A(r.get("conveyance")), "other_earn": A(oth_e),
            "gross": A(r.get("gross_paid")), "pf": A(pf_v),
            "esi": A(r.get("esic_employee")), "other_ded": A(oth_d),
            "tds": A(r.get("tds")), "total_ded": A(r.get("total_deduction")),
            "net": A(r.get("net")),
        }
        data.append([vals[k] for k in col_keys])
    tot_vals = {
        "sno": "", "code": "", "name": "GRAND TOTAL", "uan_esi": "", "desig": "",
        "days": f"{tot['days']:g}", "basic": A(tot["basic"]), "hra": A(tot["hra"]),
        "conv": A(tot["conv"]), "other_earn": A(tot["oth"]), "gross": A(tot["gross"]),
        "pf": A(tot["pf"]), "esi": A(tot["esi"]), "other_ded": A(tot["othd"]),
        "tds": A(tot["tds"]), "total_ded": A(tot["ded"]), "net": A(tot["net"]),
    }
    if "name" not in col_keys and col_keys:
        tot_vals[col_keys[0]] = "GRAND TOTAL"
    data.append([tot_vals[k] for k in col_keys])

    _scale = (W - 12 * mm) / (sum(widths) * mm)
    col_widths = [wmm * mm * _scale for wmm in widths]
    _num_idx = [i for i, k in enumerate(col_keys) if k in _numeric]

    def _v2_style(n_body: int, zebra_offset: int, is_final: bool) -> TableStyle:
        last = n_body + (1 if is_final else 0)  # grand-total row index
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 7),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 6.8),
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
            if k in ("sno", "code"):
                style.append(("ALIGN", (ci_, 0), (ci_, -1), "CENTER"))
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
    body_rows = data[1:-1]
    grand_row = data[-1]
    chunks = [body_rows[i:i + PER_PAGE]
              for i in range(0, len(body_rows), PER_PAGE)] or [[]]
    page_tables: List[Any] = []
    for ci, ch in enumerate(chunks):
        is_final = ci == len(chunks) - 1
        d = [header] + ch + ([grand_row] if is_final else [])
        row_heights = None
        if _rh > 0:
            row_heights = [None] + [_rh * mm] * len(ch) + ([None] if is_final else [])
        t = Table(d, colWidths=col_widths, repeatRows=1, rowHeights=row_heights)
        t.setStyle(_v2_style(len(ch), ci * PER_PAGE, is_final))
        page_tables.append(t)

    lbl = ParagraphStyle("lbl", fontName="Helvetica", fontSize=8.5, leading=12)
    lblb = ParagraphStyle("lblb", fontName="Helvetica-Bold", fontSize=8.5, leading=12)

    summary = Table([[
        Paragraph(f"Employees: <b>{len(rows)}</b>", lbl),
        Paragraph(f"Gross: <b>Rs. {tot['gross']:,.2f}</b>", lbl),
        Paragraph(f"Total Deductions: <b>Rs. {tot['ded']:,.2f}</b>", lbl),
        Paragraph(f"Net Payable: <b>Rs. {tot['net']:,.2f}</b>", lbl),
    ]], colWidths=[(W - 12 * mm) / 4.0] * 4)
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BAND),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    foot = Table([
        [Paragraph("Checked by ____________________", lbl),
         Paragraph(f"For {company_name.upper()}", lblb)],
        [Paragraph("Payment Date ____________________", lbl),
         Paragraph("AUTHORISED SIGNATORY / MANAGER", lblb)],
    ], colWidths=[(W - 12 * mm) / 2.0] * 2)
    foot.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 1), (-1, 1), 14),
    ]))

    story: List[Any] = []
    for ci, t in enumerate(page_tables):
        story.append(t)
        if ci < len(page_tables) - 1:
            story.append(PageBreak())
    story += [
        Spacer(1, 4 * mm),
        summary,
        Spacer(1, 3 * mm),
        Paragraph(f"RUPEES: {_num_to_words_inr(int(round(tot['net'])))} (NET PAYABLE)", lblb),
        Spacer(1, 8 * mm),
        foot,
    ]
    from utils.pdf_branding import punchline_flowables
    story.extend(punchline_flowables())
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
