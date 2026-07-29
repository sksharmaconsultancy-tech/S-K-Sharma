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
    # Iter 203 — Half-Day Threshold Rule (see grid compute for the spec).
    _halfday_rule = bool(pm.get("halfday_threshold_rule"))
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
        # Iter 203 — Half-Day Threshold Rule (per-day):
        #   below half-day threshold → ALL hrs to OT, 0 present;
        #   half-day band → ½ day (duty = threshold hrs), rest to OT;
        #   full day → duty capped at full-day hrs, extra to OT.
        # Duty HRS counts ONLY present-day hours; OT never included.
        if _halfday_rule and day_min > 0:
            if day_hours < half_day_hours:
                forced_ot_min += day_min
                continue
            if day_hours < full_day_hours:
                half_days += 1
                total_duty_min += half_day_hours * 60.0
                forced_ot_min += day_min - half_day_hours * 60.0
                continue
            present_days += 1
            total_duty_min += full_day_hours * 60.0
            forced_ot_min += day_min - full_day_hours * 60.0
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
    if _halfday_rule:
        # Iter 203 — duty already credited exactly per present/half days;
        # everything else sits in forced_ot_min.
        threshold_hours = present_days * full_day_hours + half_days * half_day_hours
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


# Iter 373 (user request) — Actual Salary run export columns (dynamic
# EPF / ESI per Firm Master, matching the Actual Salary Register PDF).
ACTUAL_CSV_COLUMNS = [
    "employee_code", "name", "father_name", "designation", "employee_type",
    "salary_mode", "p_days", "p_hours",
    "basic", "basic_salary", "w_basic_salary", "oth_allo", "total_gross",
    "epf", "esi", "adv", "tds", "net_pay",
]


def actual_csv_columns(show_epf: bool = True, show_esi: bool = True) -> List[str]:
    drop = set()
    if not show_epf:
        drop.add("epf")
    if not show_esi:
        drop.add("esi")
    return [c for c in ACTUAL_CSV_COLUMNS if c not in drop]


def to_actual_csv(rows: List[Dict[str, Any]],
                  show_epf: bool = True, show_esi: bool = True) -> str:
    cols = actual_csv_columns(show_epf, show_esi)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in cols})
    return buf.getvalue()


# Iter 274 — editable column catalog for the Actual Salary Register PDF
# (Utilities → PDF Report Formats): (key, default heading, width mm, numeric).
SALARY_REGISTER_COLUMNS = [
    ("sno", "S.No", 8, False), ("code", "Code", 16, False), ("name", "Name", 48, False),
    ("doj", "DOJ", 18, False),
    ("type", "Type", 18, False), ("roll", "Roll", 11, False), ("mode", "Mode", 11, False),
    ("rate", "Rate", 15, True), ("pd", "PD", 9, True), ("hd", "HD", 9, True),
    ("ot_h", "OT h", 11, True), ("base", "Base", 18, True), ("bonus", "Bonus", 15, True),
    ("ot_pay", "OT Pay", 15, True), ("gross", "Gross", 18, True), ("adv", "Adv", 15, True),
    ("ded", "Ded", 16, True), ("net", "Net", 20, True),
]

# Iter 306 (user #12) — DOJ is OPTIONAL: hidden unless the admin enables
# it in Reports → PDF Report Formats → Salary Register.
_REGISTER_DEFAULT_HIDDEN = {"doj"}


def build_salary_register_pdf(
    run: Dict[str, Any],
    company_name: str = "S.K. Sharma & Co.",
    fmt: Dict[str, Any] | None = None,
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

    # Iter 274 — saved PDF Report Format (title / orientation / font size /
    # column show-hide-rename-reorder-width).
    fmt = fmt or {}
    is_land = (fmt.get("orientation") or "landscape") != "portrait"
    pagesize = landscape(A4) if is_land else A4
    try:
        body_fs = float(fmt.get("font_size") or 0) or 7.5
    except Exception:
        body_fs = 7.5
    title_ov = str(fmt.get("title") or "").strip() or "Salary Register"
    cat = {k: (h, w, n) for k, h, w, n in SALARY_REGISTER_COLUMNS}
    spec = [c for c in (fmt.get("columns") or [])
            if isinstance(c, dict) and c.get("key") in cat]
    if not spec:
        spec = [{"key": k} for k, _h, _w, _n in SALARY_REGISTER_COLUMNS
                if k not in _REGISTER_DEFAULT_HIDDEN]
    sel = []
    for c in spec:
        k = c["key"]
        h, w, n = cat[k]
        try:
            width = float(c.get("width") or w)
        except Exception:
            width = w
        sel.append({"key": k, "heading": str(c.get("heading") or h),
                    "width": width, "numeric": n})

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
        buf, pagesize=pagesize,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=28 * mm, bottomMargin=14 * mm,
        title=f"{title_ov} — {run.get('month')}",
    )

    def _header(canvas, d):
        W, H = pagesize
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
            f"{title_ov}  —  {run.get('month')}  ·  "
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
    data = [[s["heading"] for s in sel]]
    totals = {k: 0.0 for k in ("base_pay", "bonus", "ot_pay", "gross", "advance", "total_deduction", "net")}
    for sn, r in enumerate((run.get("rows") or []), start=1):
        vals = {
            "sno": str(sn),
            "code": r.get("employee_code") or "—",
            "name": (r.get("name") or "")[:28],
            "doj": str(r.get("doj") or "—"),
            "type": r.get("employee_type") or "—",
            "roll": "On" if r.get("is_onroll") else "Off",
            "mode": (r.get("salary_mode") or "M")[:1].upper(),
            "rate": f"{_num(r.get('rate')):.0f}",
            "pd": str(r.get("present_days") or 0),
            "hd": str(r.get("half_days") or 0),
            "ot_h": f"{_num(r.get('ot_hours')):.1f}",
            "base": f"{_num(r.get('base_pay')):.0f}",
            "bonus": f"{_num(r.get('bonus')):.0f}",
            "ot_pay": f"{_num(r.get('ot_pay')):.0f}",
            "gross": f"{_num(r.get('gross')):.0f}",
            "adv": f"{_num(r.get('advance')):.0f}",
            "ded": f"{_num(r.get('total_deduction')):.0f}",
            "net": f"{_num(r.get('net')):.0f}",
        }
        data.append([vals[s["key"]] for s in sel])
        for k in totals:
            totals[k] += _num(r.get(k))
    tot_vals = {
        "sno": "", "code": "", "name": Paragraph("<b>TOTAL</b>", small), "doj": "",
        "type": "", "roll": "", "mode": "", "rate": "", "pd": "", "hd": "", "ot_h": "",
        "base": f"{totals['base_pay']:.0f}", "bonus": f"{totals['bonus']:.0f}",
        "ot_pay": f"{totals['ot_pay']:.0f}", "gross": f"{totals['gross']:.0f}",
        "adv": f"{totals['advance']:.0f}", "ded": f"{totals['total_deduction']:.0f}",
        "net": f"{totals['net']:.0f}",
    }
    data.append([tot_vals[s["key"]] for s in sel])

    col_widths = [s["width"] * mm for s in sel]
    usable = pagesize[0] - 20 * mm
    if sum(col_widths) > usable and sum(col_widths) > 0:
        col_widths = [w * usable / sum(col_widths) for w in col_widths]

    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), body_fs),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, -1), (-1, -1), BG_SOFT),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BG_SOFT]),
    ]
    for ci, s in enumerate(sel):
        if s["numeric"]:
            style.append(("ALIGN", (ci, 0), (ci, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
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


def build_actual_salary_register_pdf(
    run: Dict[str, Any],
    company_name: str = "S.K. Sharma & Co.",
    show_epf: bool = True,
    show_esi: bool = True,
) -> bytes:
    """Iter 372 (user request) — Actual Salary register with allowance /
    deduction heads DYNAMIC per firm: the EPF / ESI columns appear only
    when they are Applicable in the Firm Master. Columns mirror the
    Actual Salary Process grid."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate, Frame, PageTemplate,
        Paragraph, Spacer, Table, TableStyle,
    )

    BRAND = colors.HexColor("#0F3B5C")
    BAND = colors.HexColor("#EAF1F7")
    ZEBRA = colors.HexColor("#F6F8FA")
    W, H = landscape(A4)

    rows = list(run.get("rows") or [])
    month = str(run.get("month") or "")
    try:
        from datetime import datetime as _dt
        _y, _m = int(month[:4]), int(month[5:7])
        month_label = _dt(_y, _m, 1).strftime("%B %Y")
    except Exception:
        month_label = month

    def A_(v: Any) -> str:
        try:
            return f"{int(round(float(v or 0))):,}"
        except Exception:
            return "0"

    def N_(v: Any) -> str:
        try:
            f = float(v or 0)
            return f"{f:g}"
        except Exception:
            return "0"

    cols: List[tuple] = [
        ("sno", "SN", 7),
        ("name", "Name / Father Name", 42),
        ("desig", "Desig.", 18),
        ("mdays", "M.Days", 10),
        ("pdays", "P Days", 10),
        ("phours", "P Hours", 11),
        ("basic", "Basic (Master)", 15),
        ("bsalary", "Basic Sal", 14),
        ("wbasic", "W.Basic Sal", 14),
        ("othallo", "Oth.Allo", 13),
        ("gross", "Total Gross", 15),
    ]
    if show_epf:
        cols.append(("epf", "EPF", 12))
    if show_esi:
        cols.append(("esi", "ESI", 12))
    cols += [("adv", "Adv", 11), ("tds", "TDS", 11), ("net", "NET PAY", 15)]
    keys = [k for k, _h, _w in cols]

    def _header(c, d):
        c.saveState()
        c.setFillColor(BRAND)
        c.rect(0, H - 20 * mm, W, 20 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(8 * mm, H - 9 * mm, company_name.upper())
        c.setFont("Helvetica", 9)
        c.drawString(8 * mm, H - 15 * mm,
                     f"Employees: {len(rows)}   ·   Month Days: {run.get('month_days')}")
        c.setFont("Helvetica-Bold", 13)
        c.drawRightString(W - 8 * mm, H - 9 * mm, "ACTUAL SALARY REGISTER")
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(W - 8 * mm, H - 15 * mm, month_label)
        c.setFillColor(colors.HexColor("#666666"))
        c.setFont("Helvetica", 7)
        c.drawRightString(W - 8 * mm, 5 * mm, f"Page {d.page}")
        c.restoreState()

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=6 * mm, rightMargin=6 * mm,
        topMargin=24 * mm, bottomMargin=10 * mm,
        title=f"Actual Salary Register — {month}",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, W - 12 * mm,
                  H - doc.topMargin - doc.bottomMargin, id="f")
    doc.addPageTemplates([PageTemplate(id="pg", frames=[frame], onPage=_header)])

    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=7.5, leading=8.6)
    data: List[List[Any]] = [[h for _k, h, _w in cols]]
    tot = {k: 0.0 for k in ("pdays", "phours", "basic", "bsalary", "wbasic",
                            "othallo", "gross", "epf", "esi", "adv", "tds", "net")}
    for i, r in enumerate(rows, start=1):
        vals = {
            "sno": str(i),
            "name": Paragraph(
                f"<b>{(r.get('name') or '').upper()}</b><br/>"
                f"{(r.get('father_name') or '').upper()}", cell),
            "desig": Paragraph((r.get("designation") or "").upper(), cell),
            "mdays": N_(run.get("month_days")),
            "pdays": N_(r.get("p_days")),
            "phours": N_(r.get("p_hours")),
            "basic": A_(r.get("basic")),
            "bsalary": A_(r.get("basic_salary")),
            "wbasic": A_(r.get("w_basic_salary")),
            "othallo": A_(r.get("oth_allo")),
            "gross": A_(r.get("total_gross")),
            "epf": A_(r.get("epf")),
            "esi": A_(r.get("esi")),
            "adv": A_(r.get("adv")),
            "tds": A_(r.get("tds")),
            "net": A_(r.get("net_pay")),
        }
        data.append([vals[k] for k in keys])
        for tk, rk in (("pdays", "p_days"), ("phours", "p_hours"),
                       ("basic", "basic"), ("bsalary", "basic_salary"),
                       ("wbasic", "w_basic_salary"), ("othallo", "oth_allo"),
                       ("gross", "total_gross"), ("epf", "epf"), ("esi", "esi"),
                       ("adv", "adv"), ("tds", "tds"), ("net", "net_pay")):
            try:
                tot[tk] += float(r.get(rk) or 0)
            except Exception:
                pass
    tot_vals = {
        "sno": "", "name": "GRAND TOTAL", "desig": "", "mdays": "",
        "pdays": f"{tot['pdays']:g}", "phours": f"{tot['phours']:g}",
        "basic": A_(tot["basic"]), "bsalary": A_(tot["bsalary"]),
        "wbasic": A_(tot["wbasic"]), "othallo": A_(tot["othallo"]),
        "gross": A_(tot["gross"]), "epf": A_(tot["epf"]), "esi": A_(tot["esi"]),
        "adv": A_(tot["adv"]), "tds": A_(tot["tds"]), "net": A_(tot["net"]),
    }
    data.append([tot_vals[k] for k in keys])

    widths = [w for _k, _h, w in cols]
    _scale = (W - 12 * mm) / (sum(widths) * mm)
    col_widths = [w * mm * _scale for w in widths]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B9C4CE")),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), BAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for ri in range(1, len(data) - 1):
        if ri % 2 == 0:
            style.append(("BACKGROUND", (0, ri), (-1, ri), ZEBRA))
    t.setStyle(TableStyle(style))

    story: List[Any] = [t, Spacer(1, 8 * mm)]
    try:
        from utils.pdf_branding import punchline_flowables
        story.extend(punchline_flowables())
    except Exception:
        pass
    doc.build(story)
    return buf.getvalue()


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
