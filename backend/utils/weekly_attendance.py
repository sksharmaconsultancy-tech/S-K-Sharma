"""Weekly Attendance Summary PDF (Iter 113).

Landscape A4 — one row per employee for a Mon–Sun week. Consumes the same
grid payload from ``_compute_monthly_grid_data`` (from_date=Monday,
to_date=Sunday) so all policy rules are honoured. The matching XLSX reuses
``build_hours_only_grid_xlsx`` (already Bio-Code aware) — only the PDF
needs a dedicated builder.

Columns: S.No · Bio · Code · Name · Designation · Mon..Sun (per-day HH:MM)
· P Days · Duty HRS · OT HRS · Total HRS
"""
from __future__ import annotations

import io
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from reportlab.lib import colors as rl_colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER


def _hhmm(hrs: float) -> str:
    h = int(hrs)
    m = int(round((hrs - h) * 60))
    if m >= 60:
        h += 1
        m -= 60
    return f"{h:02d}:{m:02d}"


def build_weekly_pdf(grid: Dict[str, Any], wk_from: str, wk_to: str) -> bytes:
    company_name = ((grid or {}).get("company") or {}).get("name") or ""
    day_labels: List[str] = list(grid.get("day_labels") or [])
    weekday_labels: List[str] = list(grid.get("weekday_labels") or [])
    employees: List[Dict[str, Any]] = list(grid.get("employees") or [])

    headers = (
        ["S.No", "Bio", "Code", "Name", "Designation"]
        + [f"{weekday_labels[j] if j < len(weekday_labels) else ''}\n{day_labels[j]}"
           for j in range(len(day_labels))]
        + ["P Days", "Duty HRS", "OT HRS", "Total HRS"]
    )
    data: List[List[str]] = [headers]

    g_present = 0.0
    g_duty = g_ot = g_total = 0.0
    for i, emp in enumerate(employees, start=1):
        days = emp.get("days") or {}
        totals = emp.get("totals") or {}
        combined = float(totals.get("hours") or 0.0)
        ot = float(totals.get("ot_hours") or 0.0)
        duty_only = round(max(0.0, combined - ot), 2)
        present = float(totals.get("present_days") or 0.0)
        g_present += present
        g_duty += duty_only
        g_ot += ot
        g_total += combined
        bio = emp.get("bio_code")
        row = [
            str(i),
            "" if bio in (None, "") else str(bio),
            str(emp.get("employee_code") or ""),
            (emp.get("name") or "")[:26],
            (emp.get("designation") or emp.get("department") or "")[:16],
        ]
        for lbl in day_labels:
            d = days.get(lbl) or {}
            hrs = float(d.get("hours") or 0.0)
            row.append(_hhmm(hrs) if hrs > 0 else ("A" if not d.get("in") else "00:00"))
        row += [
            f"{present:g}", _hhmm(duty_only), _hhmm(ot) if ot > 0 else "-", _hhmm(combined),
        ]
        data.append(row)

    data.append(
        [f"Employees: {len(employees)}", "", "", "", ""]
        + [""] * len(day_labels)
        + [f"{g_present:g}", _hhmm(g_duty), _hhmm(g_ot), _hhmm(g_total)]
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=8 * mm, rightMargin=8 * mm,
        topMargin=8 * mm, bottomMargin=8 * mm,
    )
    title = ParagraphStyle(
        "t", fontName="Helvetica-Bold", fontSize=13, alignment=TA_CENTER,
        textColor=rl_colors.HexColor("#0F3D3E"), spaceAfter=2,
    )
    sub = ParagraphStyle(
        "s", fontName="Helvetica-Oblique", fontSize=9, alignment=TA_CENTER,
        textColor=rl_colors.HexColor("#475569"), spaceAfter=6,
    )
    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    story: List[Any] = [
        Paragraph(f"{company_name} — Weekly Attendance Summary", title),
        Paragraph(
            f"Week: Mon {wk_from} → Sun {wk_to} · Each day cell = Duty + OT (HH:MM) · "
            f"Generated: {now_ist.strftime('%d-%b-%Y %H:%M IST')}",
            sub,
        ),
    ]

    col_w = (
        [10 * mm, 11 * mm, 12 * mm, 44 * mm, 26 * mm]
        + [15 * mm] * len(day_labels)
        + [14 * mm, 16 * mm, 14 * mm, 16 * mm]
    )
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#1F5254")),
        ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (2, -1), "CENTER"),
        ("ALIGN", (5, 1), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.25, rl_colors.HexColor("#D6DCDC")),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("BACKGROUND", (0, len(data) - 1), (-1, len(data) - 1), rl_colors.HexColor("#E6EDED")),
        ("FONTNAME", (0, len(data) - 1), (-1, len(data) - 1), "Helvetica-Bold"),
    ]
    for r in range(1, len(data) - 1):
        if r % 2 == 0:
            style.append(("BACKGROUND", (0, r), (-1, r), rl_colors.HexColor("#F5F7F8")))

    table = Table(data, colWidths=col_w, repeatRows=1)
    table.setStyle(TableStyle(style))
    story.append(table)
    from utils.pdf_branding import punchline_flowables
    story.extend(punchline_flowables())
    doc.build(story)
    return buf.getvalue()
