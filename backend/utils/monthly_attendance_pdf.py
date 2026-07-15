"""Monthly Attendance PDF builders (Iter 77, policy-aligned rewrite).

Both builders now consume the SAME policy-computed ``grid`` payload as the
on-screen Grid View and the XLSX exports (``_compute_monthly_grid_data`` in
``server.py``) so every number honours the Firm Master attendance policy:
approved-only punches, bounce-merge, dedup, OT cap, cross-day OT pairing,
shift/per-employee overrides, weekly-off rules and missing-punch anomalies.

Two variants:
  * ``build_monthly_inout_pdf(grid)``  - one cell per day with IN / OUT / hours.
  * ``build_monthly_hours_pdf(grid)``  - one cell per day showing total hours.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, PageBreak,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER

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


_TRAIL_LABELS = ["Duty HRS", "OT HRS", "Total Duty HRS", "Days", "Extra HRS"]


def _fmt_hhmm(hrs: float) -> str:
    """8.53 → \"08:32\"."""
    if not hrs or hrs <= 0:
        return "00:00"
    h = int(hrs)
    m = int(round((hrs - h) * 60))
    if m >= 60:
        h += 1
        m -= 60
    return f"{h:02d}:{m:02d}"


def _emp_trailing_row(totals: Dict[str, Any]) -> List[str]:
    """Trailing summary values — mirrors the Grid-View XLSX columns."""
    combined = float(totals.get("hours") or 0.0)
    ot = float(totals.get("ot_hours") or 0.0)
    duty_only = round(max(0.0, combined - ot), 2)
    days_int = int(totals.get("total_days_int") or 0)
    extra = float(totals.get("total_extra_hrs") or 0.0)
    return [
        f"{duty_only:.2f}", f"{ot:.2f}", f"{combined:.2f}",
        str(days_int), f"{extra:.2f}",
    ]


def _header_top_row(
    day_labels: List[str], weekday_labels: List[str], idxs: List[int],
) -> List[str]:
    """Header cells: identity columns + selected day columns."""
    return (
        ["Name", "Code", "Bio", "Father", "Dept", "Design."]
        + [
            f"{day_labels[i]}\n{weekday_labels[i] if i < len(weekday_labels) else ''}"
            for i in idxs
        ]
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

def build_monthly_inout_pdf(grid: Dict[str, Any]) -> bytes:
    """Landscape A4 PDF - IN / OUT + working hours per day.

    ``grid`` is the policy-computed payload from
    ``_compute_monthly_grid_data`` — identical numbers to the Grid View
    screen and the IN/OUT XLSX export.
    """
    company_name = ((grid or {}).get("company") or {}).get("name") or ""
    month = grid.get("month") or ""
    day_labels: List[str] = list(grid.get("day_labels") or [])
    weekday_labels: List[str] = list(grid.get("weekday_labels") or [])
    employees: List[Dict[str, Any]] = list(grid.get("employees") or [])
    days_n = len(day_labels)

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
        f"Month: {month} ({days_n} days) &middot; As per Firm Master attendance "
        f"policy &middot; Generated: {now_ist.strftime('%d-%b-%Y %H:%M IST')}",
        _SUB,
    ))

    # Split day columns into pages that fit landscape A4
    idx_pages = _iter_pages_by_days(days_n, chunk=11)

    for page_idx, day_idx_1based in enumerate(idx_pages):
        idxs = [i - 1 for i in day_idx_1based]
        header = _header_top_row(day_labels, weekday_labels, idxs)
        # Also append summary columns ONLY on the last page
        is_last_page = (page_idx == len(idx_pages) - 1)
        if is_last_page:
            header += _TRAIL_LABELS
        rows: List[List[str]] = [header]

        for emp in employees:
            days_cell = emp.get("days") or {}
            row: List[str] = [
                (emp.get("name") or "")[:24],
                (emp.get("employee_code") or "")[:10],
                ("" if emp.get("bio_code") in (None, "") else str(emp.get("bio_code")))[:8],
                (emp.get("father_name") or "")[:18],
                (emp.get("department") or "")[:14],
                ((emp.get("designation") or emp.get("position") or ""))[:14],
            ]
            for i in idxs:
                d = days_cell.get(day_labels[i]) or {}
                if d.get("anomaly"):
                    # Missing-punch day — no duty counted (firm policy rule).
                    row.append(f"{d.get('in') or '-'}\n{d.get('out') or '-'}\nMISS")
                elif d.get("in") or d.get("out"):
                    row.append(
                        f"{d.get('in') or '-'}\n{d.get('out') or '-'}\n"
                        f"{_fmt_hhmm(float(d.get('hours') or 0.0))}"
                    )
                else:
                    row.append("-")
            if is_last_page:
                row += _emp_trailing_row(emp.get("totals") or {})
            rows.append(row)

        # Column widths (landscape A4 usable ~ 285mm)
        identity_w = [28 * mm, 11 * mm, 9 * mm, 20 * mm, 16 * mm, 16 * mm]
        day_w = [14 * mm] * len(idxs)
        summary_w = [13 * mm] * len(_TRAIL_LABELS) if is_last_page else []
        col_widths = identity_w + day_w + summary_w

        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(_table_style(len(employees), len(idxs)))
        story.append(table)
        if not is_last_page:
            story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Hours-only PDF
# ---------------------------------------------------------------------------

def build_monthly_hours_pdf(grid: Dict[str, Any]) -> bytes:
    """Landscape A4 PDF - one cell per day, working hours (duty + OT) in
    HH:MM. Consumes the policy-computed grid so numbers match the Grid View
    screen and the Hours XLSX export."""
    company_name = ((grid or {}).get("company") or {}).get("name") or ""
    month = grid.get("month") or ""
    day_labels: List[str] = list(grid.get("day_labels") or [])
    weekday_labels: List[str] = list(grid.get("weekday_labels") or [])
    employees: List[Dict[str, Any]] = list(grid.get("employees") or [])
    days_n = len(day_labels)

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
        f"Month: {month} ({days_n} days) &middot; As per Firm Master attendance "
        f"policy &middot; Generated: {now_ist.strftime('%d-%b-%Y %H:%M IST')}",
        _SUB,
    ))

    # Days-per-page - can fit more when each cell is 1 line
    idx_pages = _iter_pages_by_days(days_n, chunk=18)

    for page_idx, day_idx_1based in enumerate(idx_pages):
        idxs = [i - 1 for i in day_idx_1based]
        header = _header_top_row(day_labels, weekday_labels, idxs)
        is_last_page = (page_idx == len(idx_pages) - 1)
        if is_last_page:
            header += _TRAIL_LABELS
        rows: List[List[str]] = [header]

        for emp in employees:
            days_cell = emp.get("days") or {}
            row: List[str] = [
                (emp.get("name") or "")[:24],
                (emp.get("employee_code") or "")[:10],
                ("" if emp.get("bio_code") in (None, "") else str(emp.get("bio_code")))[:8],
                (emp.get("father_name") or "")[:18],
                (emp.get("department") or "")[:14],
                ((emp.get("designation") or emp.get("position") or ""))[:14],
            ]
            for i in idxs:
                d = days_cell.get(day_labels[i]) or {}
                if d.get("anomaly"):
                    row.append("MISS")
                else:
                    row.append(_fmt_hhmm(float(d.get("hours") or 0.0)))
            if is_last_page:
                row += _emp_trailing_row(emp.get("totals") or {})
            rows.append(row)

        identity_w = [28 * mm, 11 * mm, 9 * mm, 20 * mm, 16 * mm, 16 * mm]
        day_w = [10 * mm] * len(idxs)
        summary_w = [13 * mm] * len(_TRAIL_LABELS) if is_last_page else []
        col_widths = identity_w + day_w + summary_w

        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(_table_style(len(employees), len(idxs)))
        story.append(table)
        if not is_last_page:
            story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()
