"""Monthly Attendance PDF builders (Iter 77).

Mirrors the XLSX exports in ``utils/monthly_attendance.py`` so admins have
a paper-friendly landscape A4 report identical in numbers to the Grid View
and the Excel export.

Two variants:
  * ``build_monthly_inout_pdf``  - one cell per day with IN / OUT / hours.
  * ``build_monthly_hours_pdf``  - one cell per day showing total hours.

Both reuse the exact same ``_pair_punches`` pairing logic to compute
hours so the numbers stay identical across Grid + Excel + PDF.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from utils.monthly_attendance import (
    _month_bounds,
    _pair_punches,
    _fmt_time_ist,
    _fmt_hours_sample,
    _weekday_short,
    _summary_columns_hours,
    WEEKDAY_SHORT,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TITLE = ParagraphStyle(
    "title", fontName="Helvetica-Bold", fontSize=13, alignment=TA_CENTER,
    textColor=colors.HexColor("#0F3D3E"), spaceAfter=2,
)
_SUB = ParagraphStyle(
    "sub", fontName="Helvetica-Oblique", fontSize=9, alignment=TA_CENTER,
    textColor=colors.HexColor("#475569"), spaceAfter=6,
)
_HDR_BG = colors.HexColor("#1F5254")
_HDR_FG = colors.HexColor("#FFFFFF")
_ZEBRA = colors.HexColor("#F5F7F8")
_TOTAL_BG = colors.HexColor("#E6EDED")
_BORDER = colors.HexColor("#D6DCDC")


def _iter_pages_by_days(days: int, chunk: int) -> List[List[int]]:
    """Split day columns into printable chunks (landscape A4 fits ~16 day
    columns comfortably)."""
    pages: List[List[int]] = []
    d = 1
    while d <= days:
        end = min(d + chunk - 1, days)
        pages.append(list(range(d, end + 1)))
        d = end + 1
    return pages


def _emp_present_and_hours(
    emp: Dict[str, Any],
    y: int, m: int, days: int,
    punches_by_user_day: Dict[str, Dict[str, List[Dict[str, Any]]]],
    weekly_off: Iterable[int] = (6,),
):
    """Return (present_days, tot_min, working_min, weekoff_min, ot_min, day_min_list)."""
    uid = emp.get("user_id") or emp.get("_id")
    by_day = punches_by_user_day.get(uid, {})
    tot = working = weekoff = ot = 0
    present = 0
    day_mins: List[int] = []
    weekly_off_set = set(weekly_off)
    for d in range(1, days + 1):
        key = f"{y:04d}-{m:02d}-{d:02d}"
        day_min, _in, _out = _pair_punches(by_day.get(key, []))
        day_mins.append(day_min)
        tot += day_min
        if day_min > 0:
            present += 1
            if datetime(y, m, d).weekday() in weekly_off_set:
                weekoff += day_min
            else:
                working += day_min
            if day_min > 8 * 60:
                ot += day_min - 8 * 60
    return present, tot, working, weekoff, ot, day_mins


def _summary_totals_row(
    present_days: int,
    tot_min: int,
    working_min: int,
    weekoff_min: int,
    ot_min: int,
) -> List[str]:
    """Build the same trailing summary column values used by the XLSX."""
    return [
        "0:00",                              # Extra Hrs (reserved)
        _fmt_hours_sample(working_min),      # Work Hrs
        _fmt_hours_sample(weekoff_min),      # Week Off Hrs
        "0:00",                              # GP Hrs (reserved)
        "0:00",                              # MOT Hrs (reserved)
        _fmt_hours_sample(ot_min),           # OT Hrs
        "0:00",                              # Lost Hrs (reserved)
        "0",                                 # PL Days
        "0",                                 # CL Days
        _fmt_hours_sample(tot_min % 60 if tot_min else 0),  # Remaining
        str(present_days),                   # Tot. Days
        _fmt_hours_sample(tot_min),          # Tot. Hrs
    ]


def _header_top_row(day_cols: List[int], y: int, m: int) -> List[str]:
    """Header cells: identity columns + selected day columns."""
    return (
        ["Name", "Code", "Bio", "Father", "Dept", "Design."]
        + [f"{d}\n{_weekday_short(y, m, d)}" for d in day_cols]
    )


def _table_style(rows_count: int, day_cols_count: int) -> TableStyle:
    identity_cols = 6
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _HDR_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _HDR_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (identity_cols, 1), (-1, -1), "CENTER"),
        ("ALIGN", (0, 1), (identity_cols - 1, -1), "LEFT"),
        ("FONTSIZE", (0, 1), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.25, _BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]
    # Zebra
    for r in range(1, rows_count + 1):
        if r % 2 == 0:
            style.append(("BACKGROUND", (0, r), (-1, r), _ZEBRA))
    return TableStyle(style)


# ---------------------------------------------------------------------------
# IN / OUT + Hours PDF
# ---------------------------------------------------------------------------

def build_monthly_inout_pdf(
    *,
    company_name: str,
    month: str,
    employees: List[Dict[str, Any]],
    punches_by_user_day: Dict[str, Dict[str, List[Dict[str, Any]]]],
    weekly_off: Iterable[int] = (6,),
) -> bytes:
    """Landscape A4 PDF - IN / OUT + working hours per day."""
    y, m, days = _month_bounds(month)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=6 * mm, rightMargin=6 * mm,
        topMargin=8 * mm, bottomMargin=8 * mm,
    )
    story: List[Any] = []
    story.append(Paragraph(
        f"{company_name} &mdash; Monthly Attendance IN / OUT + Working Hours",
        _TITLE,
    ))
    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    story.append(Paragraph(
        f"Month: {month} ({days} days) &middot; Generated: "
        f"{now_ist.strftime('%d-%b-%Y %H:%M IST')}",
        _SUB,
    ))

    # Split day columns into pages that fit landscape A4
    day_pages = _iter_pages_by_days(days, chunk=11)

    for page_idx, day_cols in enumerate(day_pages):
        # Header row
        header = _header_top_row(day_cols, y, m)
        # Also append summary columns ONLY on the last page
        is_last_page = (page_idx == len(day_pages) - 1)
        if is_last_page:
            header += _summary_columns_hours()
        rows: List[List[str]] = [header]

        for emp in employees:
            uid = emp.get("user_id") or emp.get("_id")
            by_day = punches_by_user_day.get(uid, {})
            row: List[str] = [
                (emp.get("name") or "")[:24],
                (emp.get("employee_code") or "")[:10],
                ("" if emp.get("bio_code") in (None, "") else str(emp.get("bio_code")))[:8],
                (emp.get("father_name") or "")[:18],
                (emp.get("department") or "")[:14],
                (emp.get("position") or "")[:14],
            ]
            for d in day_cols:
                key = f"{y:04d}-{m:02d}-{d:02d}"
                day_punches = by_day.get(key, [])
                day_min, in_dt, out_dt = _pair_punches(day_punches)
                if in_dt or out_dt:
                    in_txt = _fmt_time_ist(in_dt) if in_dt else "-"
                    out_txt = _fmt_time_ist(out_dt) if out_dt else "-"
                    hrs_txt = _fmt_hours_sample(day_min)
                    row.append(f"{in_txt}\n{out_txt}\n{hrs_txt}")
                else:
                    row.append("-")
            if is_last_page:
                present, tot, working, weekoff, ot, _ = _emp_present_and_hours(
                    emp, y, m, days, punches_by_user_day, weekly_off,
                )
                row += _summary_totals_row(present, tot, working, weekoff, ot)
            rows.append(row)

        # Column widths (landscape A4 usable ~ 285mm)
        identity_w = [28 * mm, 11 * mm, 9 * mm, 20 * mm, 16 * mm, 16 * mm]
        day_w = [14 * mm] * len(day_cols)
        summary_w = [12 * mm] * len(_summary_columns_hours()) if is_last_page else []
        col_widths = identity_w + day_w + summary_w

        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(_table_style(len(employees), len(day_cols)))
        story.append(table)
        if not is_last_page:
            story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Hours-only PDF
# ---------------------------------------------------------------------------

def build_monthly_hours_pdf(
    *,
    company_name: str,
    month: str,
    employees: List[Dict[str, Any]],
    punches_by_user_day: Dict[str, Dict[str, List[Dict[str, Any]]]],
    weekly_off: Iterable[int] = (6,),
) -> bytes:
    """Landscape A4 PDF - one cell per day, working hours in HH:MM."""
    y, m, days = _month_bounds(month)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=6 * mm, rightMargin=6 * mm,
        topMargin=8 * mm, bottomMargin=8 * mm,
    )
    story: List[Any] = []
    story.append(Paragraph(
        f"{company_name} &mdash; Monthly Attendance Data (Working Hours)",
        _TITLE,
    ))
    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    story.append(Paragraph(
        f"Month: {month} ({days} days) &middot; Generated: "
        f"{now_ist.strftime('%d-%b-%Y %H:%M IST')}",
        _SUB,
    ))

    # Days-per-page - can fit more when each cell is 1 line
    day_pages = _iter_pages_by_days(days, chunk=18)

    for page_idx, day_cols in enumerate(day_pages):
        header = _header_top_row(day_cols, y, m)
        is_last_page = (page_idx == len(day_pages) - 1)
        if is_last_page:
            header += _summary_columns_hours()
        rows: List[List[str]] = [header]

        for emp in employees:
            uid = emp.get("user_id") or emp.get("_id")
            by_day = punches_by_user_day.get(uid, {})
            row: List[str] = [
                (emp.get("name") or "")[:24],
                (emp.get("employee_code") or "")[:10],
                ("" if emp.get("bio_code") in (None, "") else str(emp.get("bio_code")))[:8],
                (emp.get("father_name") or "")[:18],
                (emp.get("department") or "")[:14],
                (emp.get("position") or "")[:14],
            ]
            for d in day_cols:
                key = f"{y:04d}-{m:02d}-{d:02d}"
                day_punches = by_day.get(key, [])
                day_min, _in, _out = _pair_punches(day_punches)
                row.append(_fmt_hours_sample(day_min))
            if is_last_page:
                present, tot, working, weekoff, ot, _ = _emp_present_and_hours(
                    emp, y, m, days, punches_by_user_day, weekly_off,
                )
                row += _summary_totals_row(present, tot, working, weekoff, ot)
            rows.append(row)

        identity_w = [28 * mm, 11 * mm, 9 * mm, 20 * mm, 16 * mm, 16 * mm]
        day_w = [10 * mm] * len(day_cols)
        summary_w = [12 * mm] * len(_summary_columns_hours()) if is_last_page else []
        col_widths = identity_w + day_w + summary_w

        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(_table_style(len(employees), len(day_cols)))
        story.append(table)
        if not is_last_page:
            story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()
