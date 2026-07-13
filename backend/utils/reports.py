"""
Report generation helpers — CSV + PDF for the monthly payroll email
reports. Extracted from server.py to keep the top-level FastAPI module
focused on routing rather than presentation.

Keep this file pure: no DB access, no request/response types. Callers
pass in already-computed dicts (rows / attendance / totals).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Optional


def fmt_time(iso: Optional[str]) -> str:
    """Format an ISO-8601 timestamp as HH:MM (UTC). Returns "—" for None."""
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d.astimezone(timezone.utc).strftime("%H:%M")
    except Exception:
        return "—"


def fmt_month_label(year: int, month: int) -> str:
    return datetime(year, month, 1).strftime("%B %Y")


def attendance_csv(data: dict) -> bytes:
    """Day-by-day punch sheet CSV."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "Employee Code", "Name", "Date", "First In (UTC)",
        "Last Out (UTC)", "Duration (hh:mm)", "Punches",
    ])
    for a in data.get("attendance", []):
        mins = int(a.get("minutes") or 0)
        dur = f"{mins // 60:02d}:{mins % 60:02d}" if mins else "—"
        w.writerow([
            a.get("employee_code") or "",
            a.get("name") or "",
            a.get("date") or "",
            fmt_time(a.get("first_in")),
            fmt_time(a.get("last_out")),
            dur,
            a.get("punches", 0),
        ])
    return buf.getvalue().encode("utf-8")


def salary_csv(data: dict) -> bytes:
    """Per-employee salary summary CSV."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "Employee Code", "Name", "Email",
        "Present Days", "Half Days", "Absent Days", "Off Days",
        "Working Days", "Total Hours", "Base Salary (INR)",
        "Base Gross (INR)", "Tier Bonus (INR)", "OT Pay (INR)", "Gross (INR)",
    ])
    for r in data.get("rows", []):
        w.writerow([
            r.get("employee_code") or "",
            r.get("name") or "",
            r.get("email") or "",
            r.get("present_days", 0),
            r.get("half_days", 0),
            r.get("absent_days", 0),
            r.get("off_days", 0),
            r.get("working_days", 0),
            r.get("total_hours", 0),
            r.get("salary_monthly") or 0,
            r.get("base_gross", 0),
            r.get("tier_bonus", 0),
            r.get("ot_pay", 0),
            r.get("gross", 0),
        ])
    return buf.getvalue().encode("utf-8")


def pdf_bytes(kind: str, data: dict, company_name: str) -> bytes:
    """Build a small PDF via fpdf2 covering salary summary and/or the
    per-day punch sheet, depending on `kind` ∈ {attendance, salary,
    combined}."""
    from fpdf import FPDF

    pdf = FPDF(
        orientation="L" if kind == "attendance" else "P",
        unit="mm",
        format="A4",
    )
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    label = fmt_month_label(data["year"], data["month"])
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, f"{company_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 11)
    title_map = {
        "attendance": f"Attendance punch sheet — {label}",
        "salary":     f"Salary summary — {label}",
        "combined":   f"Attendance + salary report — {label}",
    }
    pdf.cell(0, 6, title_map.get(kind, "Report"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    if kind in ("salary", "combined"):
        pdf.set_font("Helvetica", "B", 9)
        headers = [
            ("Code", 20), ("Name", 45), ("Pres", 12), ("Half", 12), ("Abs", 12),
            ("Off", 12), ("Hrs", 15), ("Base", 22), ("Bonus", 22), ("Gross", 26),
        ]
        for h, w in headers:
            pdf.cell(w, 6, h, border=1)
        pdf.ln()
        pdf.set_font("Helvetica", "", 8)
        for r in data.get("rows", []):
            cells = [
                (str(r.get("employee_code") or "")[:9], 20),
                (str(r.get("name") or "")[:24], 45),
                (str(r.get("present_days", 0)), 12),
                (str(r.get("half_days", 0)), 12),
                (str(r.get("absent_days", 0)), 12),
                (str(r.get("off_days", 0)), 12),
                (f'{r.get("total_hours", 0):.1f}', 15),
                (f'{(r.get("salary_monthly") or 0):.0f}', 22),
                (f'{r.get("tier_bonus", 0):.0f}', 22),
                (f'{r.get("gross", 0):.0f}', 26),
            ]
            for v, w in cells:
                pdf.cell(w, 5, v, border=1)
            pdf.ln()
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 9)
        totals = data.get("totals", {})
        pdf.cell(
            0, 5,
            f"Employees: {totals.get('employees', 0)}  ·  "
            f"Total hours: {totals.get('total_hours', 0):.2f}  ·  "
            f"Gross total: {totals.get('gross_total', 0):,.0f}",
            new_x="LMARGIN", new_y="NEXT",
        )

    if kind in ("attendance", "combined"):
        if kind == "combined":
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 6, f"Punch sheet — {label}", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        pdf.set_font("Helvetica", "B", 8)
        headers = [
            ("Code", 22), ("Name", 45), ("Date", 26), ("In", 20),
            ("Out", 20), ("Hrs", 18), ("Punches", 20),
        ]
        for h, w in headers:
            pdf.cell(w, 5, h, border=1)
        pdf.ln()
        pdf.set_font("Helvetica", "", 7)
        for a in data.get("attendance", []):
            mins = int(a.get("minutes") or 0)
            dur = f'{mins // 60:02d}:{mins % 60:02d}' if mins else "—"
            cells = [
                (str(a.get("employee_code") or "")[:11], 22),
                (str(a.get("name") or "")[:24], 45),
                (str(a.get("date") or ""), 26),
                (fmt_time(a.get("first_in")), 20),
                (fmt_time(a.get("last_out")), 20),
                (dur, 18),
                (str(a.get("punches", 0)), 20),
            ]
            for v, w in cells:
                pdf.cell(w, 4.5, v, border=1)
            pdf.ln()

    return bytes(pdf.output(dest="S"))
