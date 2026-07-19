"""Monthly salary processing — compute + export helpers.

Called from ``POST /api/admin/salary-runs`` and its exports. All heavy
logic lives here to keep server.py light and to allow the compute step
to be unit-tested in isolation.
"""
from __future__ import annotations

import calendar
import csv
import io
import re
from typing import Any, Dict, List, Optional


def actual_days_in_month(year: int, month: int) -> int:
    """Return the actual number of days in a given calendar month."""
    return calendar.monthrange(year, month)[1]


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def compute_present_days_and_ot(
    attendance_rows: List[Dict[str, Any]],
    policy: Dict[str, Any],
) -> Dict[str, float]:
    """Given the attendance records for a single employee across a month,
    return { present_days, half_days, absent_days, duty_hours, ot_hours }.

    Simple aggregation:
      • For each date with an "in" record, we consider it a present day.
      • Duty hours are the sum of paired IN/OUT deltas across the month.
      • Overtime = max(0, duty_hours - present_days * full_day_hours).
      • Half days: dates with duty_hours < full_day but >= half_day.
    """
    full_day_hours = _num(policy.get("full_day_hours"), 8.0)
    half_day_hours = _num(policy.get("half_day_hours"), 4.0)
    # Iter 202 — "Count Present Day @ 8 HRS" (compliance-only sub-point):
    # caller sets ``_present_day_hours_override`` so a day with >= 8 worked
    # hours counts as 1 Present Day even when the firm's duty hours are
    # 10/12; the extra hours flow into OT per the dynamic policy below.
    _pd_override = _num(policy.get("_present_day_hours_override"), 0.0)
    if _pd_override > 0:
        full_day_hours = _pd_override
    # Iter 200 — Policy Master Sub Points (dynamic attendance calc).
    pm = policy.get("policy_master") or {}
    weekly_offs = set(policy.get("weekly_off_days") or [])
    holiday_dates = set(policy.get("_holiday_dates") or [])

    from datetime import datetime, timezone

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for r in attendance_rows or []:
        d = r.get("date")
        if not d:
            continue
        by_date.setdefault(d, []).append(r)

    total_duty_min = 0.0
    forced_ot_min = 0.0
    present_days = 0
    half_days = 0
    absent_days = 0
    for d, rows in by_date.items():
        rows = sorted(rows, key=lambda x: x.get("at") or "")
        # If ANY record for the day is kind='absent', mark absent
        if any(r.get("kind") == "absent" for r in rows):
            absent_days += 1
            continue
        # Pair up IN/OUT
        day_min = 0.0
        open_in: Optional[datetime] = None
        for r in rows:
            k = r.get("kind")
            when_raw = r.get("at") or ""
            try:
                when = datetime.fromisoformat(when_raw.replace("Z", "+00:00"))
            except Exception:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if k == "in":
                open_in = when
            elif k == "out" and open_in is not None:
                dm = (when - open_in).total_seconds() / 60.0
                if dm > 0:
                    day_min += dm
                open_in = None
        day_hours = day_min / 60.0
        # Iter 200 — Policy Master Sub Points:
        #   • week-off worked + weekoff_present_add_ot → ALL hours to OT,
        #     day NOT counted present.
        #   • holiday worked + holiday_present_add_ot → day counts present
        #     AND hours go to OT.
        try:
            _wd = datetime.strptime(d, "%Y-%m-%d").weekday()
        except Exception:
            _wd = None
        if day_min > 0 and _wd is not None and _wd in weekly_offs and pm.get("weekoff_present_add_ot"):
            forced_ot_min += day_min
            continue
        if day_min > 0 and d in holiday_dates and pm.get("holiday_present_add_ot"):
            forced_ot_min += day_min
            present_days += 1
            continue
        total_duty_min += day_min
        if day_hours >= full_day_hours:
            present_days += 1
        elif day_hours >= half_day_hours:
            half_days += 1

    duty_hours = round(total_duty_min / 60.0, 2)
    # Overtime = total worked beyond `present_days * full_day_hours`.
    # Half days DON'T generate OT (partial-day rule).
    threshold_hours = present_days * full_day_hours
    ot_hours = round(max(0.0, duty_hours - threshold_hours) + forced_ot_min / 60.0, 2)
    # Iter 142 — per-employee `ot_allowed` / Firm Master `firm_ot_allowed`
    # gates: when either is explicitly OFF, NO overtime is credited.
    if policy.get("ot_allowed") is False or policy.get("firm_ot_allowed") is False:
        ot_hours = 0.0
    # Effective "present" for pro-ration = full days + 0.5 * half days
    effective_present = present_days + 0.5 * half_days
    # Iter 200 — "Attendance Calculation as per Duty HRS":
    # Days = Total Duty HRS ÷ Daily Duty HRS (firm's full-day hours).
    if pm.get("attendance_by_duty_hours") and full_day_hours > 0:
        effective_present = round(duty_hours / full_day_hours, 2)
        present_days = int(effective_present)
        half_days = 0
    return {
        "present_days": present_days,
        "half_days": half_days,
        "absent_days": absent_days,
        "duty_hours": duty_hours,
        "ot_hours": ot_hours,
        "effective_present": effective_present,
    }


# --------------------------------------------------------------------------- 
# Base salary process — NO statutory compliance deductions here.
# PF / ESIC / PT / TDS are handled in a separate, dedicated Compliance
# Salary Process (with its own salary structure) that will be introduced
# later. This base process ONLY computes gross earnings and subtracts
# per-employee advance/loan balance.
# --------------------------------------------------------------------------- 
DEFAULT_DEDUCTION_CFG: Dict[str, float] = {
    # OT multiplier: 1.5x by default. Textile policy also exposes this.
    "ot_multiplier": 1.5,
}


def compute_salary_row(
    user: Dict[str, Any],
    policy: Dict[str, Any],
    month_days: int,
    stats: Dict[str, float],
    deductions_cfg: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Compute the full salary row for a single employee.

    Args:
        user: Employee doc (must include user_id, name, employee_code,
            employee_type, is_onroll, employee_policy or salary_monthly).
        policy: Merged policy dict (from user.employee_policy).
        month_days: The divisor used for pro-ration when salary_mode='monthly'.
        stats: Dict returned by ``compute_present_days_and_ot``.
        deductions_cfg: Optional overrides on DEFAULT_DEDUCTION_CFG.
    """
    cfg = dict(DEFAULT_DEDUCTION_CFG)
    if deductions_cfg:
        cfg.update({k: float(v) for k, v in deductions_cfg.items() if v is not None})

    salary_mode = (policy.get("salary_mode") or "monthly").lower()
    rate = _num(policy.get("salary") or user.get("salary_monthly"), 0.0)

    # ---- Iter 91 — Employee Master overrides -----------------------------
    # The Salary Update modal saves a fixed structure on the employee doc:
    #   salary_structure_actual: [ {head:"Basic", amount, rate_type},
    #                              {head:"Salary 1..3", amount, working_days} ]
    #   actual_salary_allowances / actual_salary_deductions: [{head, amount}]
    # When a Basic row exists, its amount + rate basis (monthly/daily/
    # hourly) take precedence over policy/salary_monthly.
    struct = user.get("salary_structure_actual") or []
    struct = [r for r in struct if isinstance(r, dict)]
    basic_row = next(
        (r for r in struct
         if str(r.get("head", "")).strip().lower().startswith("basic")),
        None,
    )
    if basic_row and _num(basic_row.get("amount"), 0.0) > 0:
        rate = _num(basic_row.get("amount"), 0.0)
        rt = str(basic_row.get("rate_type") or "").strip().lower()
        if rt in ("monthly", "daily", "hourly"):
            salary_mode = rt

    present_days = float(stats.get("present_days", 0))
    half_days = float(stats.get("half_days", 0))
    effective_present = float(stats.get("effective_present", present_days))
    duty_hours = float(stats.get("duty_hours", 0.0))
    ot_hours = float(stats.get("ot_hours", 0.0))

    # ---- Base pay ----
    per_hour_rate = 0.0
    if salary_mode == "daily":
        base = rate * effective_present
        per_hour_rate = _safe_div(rate, _num(policy.get("full_day_hours"), 8.0))
    elif salary_mode == "hourly":
        base = rate * duty_hours
        per_hour_rate = rate
    else:  # monthly (default) — pro-rate on effective present-days / month_days
        base = _safe_div(rate * effective_present, max(1, month_days))
        per_hour_rate = _safe_div(rate, max(1, month_days) * _num(policy.get("full_day_hours"), 8.0))

    # ---- Tier bonuses (attendance-based). Master "Salary 1/2/3" rows
    # (amount + working_days) take precedence over policy tiers. Only
    # monthly / daily modes unlock the tiers. ----
    bonus = 0.0
    if salary_mode in ("monthly", "daily"):
        for lvl in (1, 2, 3):
            srow = next(
                (r for r in struct
                 if str(r.get("head", "")).strip().lower() == f"salary {lvl}"),
                None,
            )
            if srow and _num(srow.get("amount"), 0.0) > 0:
                bs = _num(srow.get("amount"), 0.0)
                bd = _num(srow.get("working_days"), 0.0) or 999.0
            else:
                bs = _num(policy.get(f"salary_{lvl}"), 0.0)
                bd = _num(policy.get(f"day_{lvl}"), 999.0)
            if bs > 0 and present_days >= bd:
                bonus += bs

    # ---- Overtime pay ----
    ot_pay = ot_hours * per_hour_rate * cfg["ot_multiplier"]

    # ---- Iter 91 — Allowances / Deductions from the Employee Master ----
    allowances_total = sum(
        _num(r.get("amount"), 0.0)
        for r in (user.get("actual_salary_allowances") or [])
        if isinstance(r, dict)
    )
    master_deductions = sum(
        _num(r.get("amount"), 0.0)
        for r in (user.get("actual_salary_deductions") or [])
        if isinstance(r, dict)
    )

    gross = base + bonus + ot_pay + allowances_total

    # ---- Deductions ----
    # BASE salary process deducts per-employee advance/loan balance plus
    # any Deduction heads saved on the Employee Master. Statutory
    # compliance (PF / ESIC / PT / TDS) is intentionally NOT applied here —
    # it lives in the separate Compliance Salary Process.
    advance = _num(user.get("advance_balance"), 0.0)
    total_deduction = advance + master_deductions
    net = gross - total_deduction

    return {
        "user_id": user.get("user_id"),
        "name": user.get("name"),
        "employee_code": user.get("employee_code"),
        "employee_type": user.get("employee_type"),
        # Iter 183 — Branch / Department / Contractor for grid filter chips.
        "branch_name": user.get("branch_name"),
        "department": user.get("department"),
        "contractor_name": user.get("contractor_name"),
        "is_onroll": user.get("is_onroll") is not False,  # default True
        "salary_mode": salary_mode,
        "rate": round(rate, 2),
        "month_days": int(month_days),
        "present_days": int(present_days),
        "half_days": int(half_days),
        "duty_hours": round(duty_hours, 2),
        "ot_hours": round(ot_hours, 2),
        "base_pay": round(base, 2),
        "bonus": round(bonus, 2),
        "ot_pay": round(ot_pay, 2),
        "allowances": round(allowances_total, 2),
        "gross": round(gross, 2),
        "advance": round(advance, 2),
        "other_deductions": round(master_deductions, 2),
        "total_deduction": round(total_deduction, 2),
        "net": round(net, 2),
    }


# --------------------------------------------------------------------------- 
# Exports
# --------------------------------------------------------------------------- 
CSV_COLUMNS = [
    "employee_code", "name", "employee_type", "is_onroll",
    "salary_mode", "rate", "month_days", "present_days", "half_days",
    "duty_hours", "ot_hours",
    "base_pay", "bonus", "ot_pay", "gross",
    "advance", "total_deduction", "net",
]


def to_csv(rows: List[Dict[str, Any]]) -> str:
    """Render the batch as CSV. Compatible with Excel & Google Sheets."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        row = {k: r.get(k, "") for k in CSV_COLUMNS}
        row["is_onroll"] = "On-roll" if r.get("is_onroll") else "Off-roll"
        w.writerow(row)
    return buf.getvalue()


def build_salary_register_pdf(
    run: Dict[str, Any],
    company_name: str = "S.K. Sharma & Co.",
) -> bytes:
    """Return a printable PDF salary register for the batch."""
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
        fontName="Helvetica", fontSize=8, textColor=INK,
    )

    doc = BaseDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=28 * mm, bottomMargin=14 * mm,
        title=f"Salary Register — {run.get('month')}",
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
        c.drawString(12 * mm, H - 12 * mm, company_name)
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#DDEDED"))
        c.drawString(
            12 * mm, H - 18 * mm,
            f"Salary Register  —  {run.get('month')}  ·  "
            f"{len(run.get('rows') or [])} employees  ·  "
            f"month_days={run.get('month_days')}",
        )
        c.drawRightString(W - 12 * mm, H - 12 * mm, f"Run: {run.get('run_id')}")
        c.setFillColor(INK)
        c.setFont("Helvetica", 7)
        c.drawString(12 * mm, 8 * mm, "System-generated salary register.")
        c.drawRightString(W - 12 * mm, 8 * mm, f"Page {d.page}")
        c.restoreState()

    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height, id="body", showBoundary=0,
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_header)])

    story = []
    header = [
        "Code", "Name", "Type", "Roll",
        "Mode", "Rate", "PD", "HD", "OT h",
        "Base", "Bonus", "OT₹", "Gross",
        "Adv", "Ded", "Net",
    ]
    data = [header]
    totals = {k: 0.0 for k in ("base_pay", "bonus", "ot_pay", "gross", "advance", "total_deduction", "net")}
    for r in (run.get("rows") or []):
        data.append([
            r.get("employee_code") or "—",
            (r.get("name") or "")[:28],
            r.get("employee_type") or "—",
            "On" if r.get("is_onroll") else "Off",
            (r.get("salary_mode") or "M")[:1].upper(),
            f"{_num(r.get('rate')):.0f}",
            r.get("present_days") or 0,
            r.get("half_days") or 0,
            f"{_num(r.get('ot_hours')):.1f}",
            f"{_num(r.get('base_pay')):.0f}",
            f"{_num(r.get('bonus')):.0f}",
            f"{_num(r.get('ot_pay')):.0f}",
            f"{_num(r.get('gross')):.0f}",
            f"{_num(r.get('advance')):.0f}",
            f"{_num(r.get('total_deduction')):.0f}",
            f"{_num(r.get('net')):.0f}",
        ])
        for k in totals:
            totals[k] += _num(r.get(k))
    # Totals row
    data.append([
        "", Paragraph("<b>TOTAL</b>", small), "", "", "", "", "", "", "",
        f"{totals['base_pay']:.0f}", f"{totals['bonus']:.0f}", f"{totals['ot_pay']:.0f}",
        f"{totals['gross']:.0f}",
        f"{totals['advance']:.0f}", f"{totals['total_deduction']:.0f}", f"{totals['net']:.0f}",
    ])

    col_widths = [
        18 * mm, 55 * mm, 20 * mm, 12 * mm,  # code / name / type / roll
        12 * mm, 16 * mm, 10 * mm, 10 * mm, 12 * mm,  # mode/rate/PD/HD/OTh
        20 * mm, 16 * mm, 16 * mm, 20 * mm,  # base/bonus/ot/gross
        16 * mm, 18 * mm, 22 * mm,  # adv / ded / net
    ]

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, -1), (-1, -1), BG_SOFT),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BG_SOFT]),
        ("ALIGN", (5, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(Paragraph(
        f"<b>Salary run summary</b> — month: {run.get('month')}  ·  "
        f"employees: {len(run.get('rows') or [])}  ·  "
        f"net payout: ₹{totals['net']:,.0f}",
        heading,
    ))
    story.append(Spacer(1, 6))
    story.append(t)
    doc.build(story)
    return buf.getvalue()


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_month(month_str: str) -> tuple[int, int]:
    """Parse a 'YYYY-MM' string into (year, month) ints. Raises ValueError."""
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
