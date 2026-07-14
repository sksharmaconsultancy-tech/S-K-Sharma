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
import io
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

    # ESIC
    "esic_percent_employee": 0.75,
    "esic_percent_employer": 3.25,
    "esic_gross_threshold": 21000.0,

    # Shared statutory wage-base rule (new labour code, per client policy):
    # PF & ESIC apply on max(Basic, floor_pct% of Gross Earning).
    "stat_wage_floor_pct": 50.0,
}

# --------------------------------------------------------------------------- 
# Professional Tax — monthly ₹ per state. Simplified flat monthly amounts.
# Admins can override per-employee with `pt_amount_override`.
# --------------------------------------------------------------------------- 
PT_STATE_MONTHLY: Dict[str, float] = {
    "Maharashtra": 200.0,
    "Karnataka": 200.0,
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
        cfg.update({k: _num(v) for k, v in statutory_cfg.items() if v is not None})

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
    present_days = int(stats.get("present_days", 0))
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
    comp_basic = _num(user.get("compliance_basic"), 0.0)
    if comp_basic > 0 and not user.get("basic_amount") and not (user.get("salary_structure_compliance") or []):
        if salary_mode == "monthly":
            prorated_basic = _safe_div(comp_basic * effective_present, max(1, month_days))
        else:
            prorated_basic = comp_basic
        user = {**user, "basic_amount": round(min(prorated_basic, monthly_gross), 2)}
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

    # ---- PF ----
    # Iter 98 — firm-level EPF gate (Firm Master → EPF "Applicable") ANDed
    # with the per-employee flag.
    pf_applicable = firm_pf_enabled and user.get("pf_applicable") is not False
    if pf_applicable:
        # Iter 126g — explicit "PF Basic Salary" from the Employee Master.
        # EPF ceiling rule: Basic < ₹15,000 → PF Basic mirrors the Basic
        # (auto-copied by the form); Basic ≥ ₹15,000 → optional, and when
        # filled PF is calculated on the filled amount (no ₹15k cap since
        # the employer chose it explicitly). Pro-rated by attendance for
        # monthly-rated staff.
        pf_basic_override = _num(user.get("pf_basic"), 0.0)
        if pf_basic_override > 0:
            if salary_mode == "monthly":
                capped_pf_wages = _safe_div(
                    pf_basic_override * effective_present, max(1, month_days)
                )
            else:
                capped_pf_wages = pf_basic_override
        else:
            capped_pf_wages = min(stat_wage_base, cfg["pf_wage_cap"])
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
    else:
        capped_pf_wages = 0.0
        vpf = 0.0
        pf_employee = pf_employer_epf = pf_employer_eps = pf_employer_total = 0.0

    # ---- ESIC ----
    # Iter 98 — firm-level ESIC gate (Firm Master → ESI "Applicable") ANDed
    # with the per-employee flag.
    esic_applicable = firm_esic_enabled and user.get("esic_applicable") is not False
    if esic_applicable and gross_paid <= cfg["esic_gross_threshold"]:
        esic_wage_base = stat_wage_base   # SAME base as PF, no ₹15k cap on ESIC
        esic_employee = esic_wage_base * (cfg["esic_percent_employee"] / 100.0)
        esic_employer = esic_wage_base * (cfg["esic_percent_employer"] / 100.0)
    else:
        esic_wage_base = 0.0
        esic_employee = esic_employer = 0.0

    # ---- Professional Tax ----
    pt_state = (user.get("pt_state") or "None").strip() or "None"
    pt_override = user.get("pt_amount_override")
    if pt_override is not None and _num(pt_override, -1) >= 0:
        pt = _num(pt_override, 0.0)
    else:
        pt = PT_STATE_MONTHLY.get(pt_state, 0.0)

    # ---- TDS (manual ₹ per employee) ----
    tds = _num(user.get("tds_amount"), 0.0)

    total_deduction = pf_employee + esic_employee + pt + tds
    net = gross_paid - total_deduction

    # Iter 85 — Master (full-month) values.
    # These are the FULL monthly figures ignoring present days — used
    # to populate the "Master Salary" columns in the Compliance grid so
    # admins can compare full vs pro-rated amounts at a glance.
    if salary_mode == "daily":
        monthly_gross_master = rate * int(month_days)
    elif salary_mode == "hourly":
        monthly_gross_master = rate * (int(month_days) * full_day_hours)
    else:
        monthly_gross_master = rate  # monthly cadence => rate is the full monthly gross
    master_structure = resolve_structure(user, monthly_gross_master, company_structure_pct)

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
) -> bytes:
    """Printable landscape PDF of the compliance salary register."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate, Frame, PageTemplate,
        Paragraph, Spacer, Table, TableStyle,
    )

    BRAND = colors.HexColor("#1F4E4E")
    ACCENT = colors.HexColor("#C89B3C")
    INK = colors.HexColor("#1E2A2A")
    BG_SOFT = colors.HexColor("#F7F9F9")
    LINE = colors.HexColor("#D6DEDE")

    buf = io.BytesIO()
    base = getSampleStyleSheet()
    heading = ParagraphStyle(
        "Heading", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=13, textColor=INK,
    )
    small = ParagraphStyle(
        "Small", parent=base["Normal"],
        fontName="Helvetica", fontSize=7, textColor=INK,
    )

    doc = BaseDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=6 * mm, rightMargin=6 * mm,
        topMargin=28 * mm, bottomMargin=14 * mm,
        title=f"Compliance Salary Register — {run.get('month')}",
    )

    def _header(canvas, d):
        W, H = landscape(A4)
        c = canvas
        c.saveState()
        c.setFillColor(BRAND)
        c.rect(0, H - 22 * mm, W, 22 * mm, stroke=0, fill=1)
        c.setFillColor(ACCENT)
        c.rect(0, H - 24 * mm, W, 2 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(8 * mm, H - 12 * mm, company_name)
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#DDEDED"))
        c.drawString(
            8 * mm, H - 18 * mm,
            f"Compliance Salary Register  —  {run.get('month')}  ·  "
            f"{len(run.get('rows') or [])} employees",
        )
        c.drawRightString(W - 8 * mm, H - 12 * mm, f"Run: {run.get('run_id')}")
        c.setFillColor(INK)
        c.setFont("Helvetica", 6.5)
        c.drawString(8 * mm, 8 * mm, "System-generated compliance salary register (new labour code).")
        c.drawRightString(W - 8 * mm, 8 * mm, f"Page {d.page}")
        c.restoreState()

    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height, id="body", showBoundary=0,
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_header)])

    story = []
    header = [
        "Name", "Father Name", "Designation", "UAN No.", "ESIC No.", "PD",
        "Basic", "HRA", "Conv", "Med", "Spl",
        "Gross",
        "PF (E)", "ESI (E)", "PT", "TDS",
        "Ded", "Net",
        "PF (Er)", "ESI (Er)",
    ]
    data = [header]
    totals = {
        k: 0.0
        for k in (
            "basic", "hra", "conveyance", "medical", "special",
            "gross_paid", "pf_employee", "esic_employee", "pt", "tds",
            "total_deduction", "net", "pf_employer_total", "esic_employer",
        )
    }
    for r in (run.get("rows") or []):
        data.append([
            (r.get("name") or "")[:22],
            (r.get("father_name") or "—")[:20],
            (r.get("designation") or "—")[:16],
            r.get("uan_no") or "—",
            r.get("esi_ip_no") or "—",
            r.get("present_days") or 0,
            f"{_num(r.get('basic')):.0f}",
            f"{_num(r.get('hra')):.0f}",
            f"{_num(r.get('conveyance')):.0f}",
            f"{_num(r.get('medical')):.0f}",
            f"{_num(r.get('special')):.0f}",
            f"{_num(r.get('gross_paid')):.0f}",
            f"{_num(r.get('pf_employee')):.0f}",
            f"{_num(r.get('esic_employee')):.0f}",
            f"{_num(r.get('pt')):.0f}",
            f"{_num(r.get('tds')):.0f}",
            f"{_num(r.get('total_deduction')):.0f}",
            f"{_num(r.get('net')):.0f}",
            f"{_num(r.get('pf_employer_total')):.0f}",
            f"{_num(r.get('esic_employer')):.0f}",
        ])
        for k in totals:
            totals[k] += _num(r.get(k))

    data.append([
        Paragraph("<b>TOTAL</b>", small), "", "", "", "", "",
        f"{totals['basic']:.0f}", f"{totals['hra']:.0f}",
        f"{totals['conveyance']:.0f}", f"{totals['medical']:.0f}", f"{totals['special']:.0f}",
        f"{totals['gross_paid']:.0f}",
        f"{totals['pf_employee']:.0f}", f"{totals['esic_employee']:.0f}",
        f"{totals['pt']:.0f}", f"{totals['tds']:.0f}",
        f"{totals['total_deduction']:.0f}", f"{totals['net']:.0f}",
        f"{totals['pf_employer_total']:.0f}", f"{totals['esic_employer']:.0f}",
    ])

    col_widths = [
        14 * mm,        # code
        44 * mm,        # name
        9 * mm,         # PD
        16 * mm, 16 * mm, 14 * mm, 14 * mm, 16 * mm,   # basic hra conv med spl
        18 * mm,        # gross
        15 * mm, 15 * mm, 12 * mm, 15 * mm,            # pf(e) esi(e) pt tds
        16 * mm, 20 * mm,                              # ded, net
        16 * mm, 16 * mm,                              # pf(er) esi(er)
    ]

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, -1), (-1, -1), BG_SOFT),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BG_SOFT]),
        ("ALIGN", (5, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(Paragraph(
        f"<b>Compliance salary summary</b> — {run.get('month')}  ·  "
        f"employees: {len(run.get('rows') or [])}  ·  "
        f"net payout: ₹{totals['net']:,.0f}  ·  "
        f"total statutory: ₹{totals['total_deduction']:,.0f}",
        heading,
    ))
    story.append(Spacer(1, 6))
    story.append(t)
    doc.build(story)
    return buf.getvalue()


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_month(month_str: str) -> tuple[int, int]:
    m = _MONTH_RE.match((month_str or "").strip())
    if not m:
        raise ValueError("month must be in YYYY-MM format")
    y = int(m.group(1))
    mo = int(m.group(2))
    if not (2020 <= y <= 2100):
        raise ValueError("year out of range")
    if not (1 <= mo <= 12):
        raise ValueError("month must be 1..12")
    return y, mo

    if not (1 <= mo <= 12):
        raise ValueError("month must be 1..12")
    return y, mo
