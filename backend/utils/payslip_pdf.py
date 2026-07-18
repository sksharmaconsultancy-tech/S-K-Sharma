"""Per-employee Payslip PDF — Iter 69.

Compact A4 payslip that mirrors the same brand palette + font stack as
``salary_certificate.py``. Used both for the individual "Download slip"
button and for the bulk-payslip combined PDF / ZIP endpoints.

Sections (top-to-bottom):
  1. Company letterhead (name, address, contact).
  2. Payslip title + reference month + issue date.
  3. Employee identity block (name, code, designation, dept, UAN, PF, bank).
  4. Attendance block (Month days · Present · Half · OT hrs).
  5. Earnings + Deductions two-column table with totals.
  6. Net Pay banner (bold, coloured).
  7. Amount in words.
  8. Authorised signatory footer.

Callers pass:
  * ``employee`` — dict with keys name, employee_code, designation,
    department, doj, uan_no, pf_no, esi_ip_no, pan_no, bank_name,
    bank_account, bank_ifsc.
  * ``company``  — dict with keys name, address, phone, email,
    logo_base64 (optional), pf_code, esic_code.
  * ``row``      — the salary-run row for this employee (base_pay,
    bonus, ot_pay, hra, gross, advance, total_deduction, net, etc.).
  * ``month``    — YYYY-MM.
Returns raw PDF bytes.
"""
from __future__ import annotations

import base64
import io
from datetime import date, datetime
from typing import Any, Dict, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from utils.employee_pdf import _register_fonts

BRAND = colors.HexColor("#1F4E4E")
BRAND_LIGHT = colors.HexColor("#E6EDED")
ACCENT = colors.HexColor("#C89B3C")
INK = colors.HexColor("#1E2A2A")
INK_SOFT = colors.HexColor("#4C5A5A")
INK_MUTED = colors.HexColor("#7A8686")
LINE = colors.HexColor("#D6DEDE")
NET_BG = colors.HexColor("#F0F7F2")


def _amt(n: Any) -> str:
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    return "\u20B9" + f"{int(round(v)):,}".replace(",", "_").replace("_", ",")


def _num_to_words_inr(n: int) -> str:
    """Convert an integer rupee amount to words (Indian numbering)."""
    if n == 0:
        return "Zero Only"
    units = [
        "", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
        "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen",
        "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen",
        "Nineteen",
    ]
    tens = [
        "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty",
        "Seventy", "Eighty", "Ninety",
    ]

    def below_100(x: int) -> str:
        if x < 20:
            return units[x]
        return (tens[x // 10] + (" " + units[x % 10] if x % 10 else "")).strip()

    def below_1000(x: int) -> str:
        if x < 100:
            return below_100(x)
        return (
            units[x // 100]
            + " Hundred"
            + (" " + below_100(x % 100) if x % 100 else "")
        ).strip()

    parts = []
    crore = n // 10_000_000
    n %= 10_000_000
    lakh = n // 100_000
    n %= 100_000
    thousand = n // 1000
    n %= 1000
    rest = n
    if crore:
        parts.append(below_100(crore) + " Crore")
    if lakh:
        parts.append(below_100(lakh) + " Lakh")
    if thousand:
        parts.append(below_100(thousand) + " Thousand")
    if rest:
        parts.append(below_1000(rest))
    return " ".join(parts) + " Only"


def _month_label(month: str) -> str:
    try:
        d = datetime.strptime(month, "%Y-%m")
        return d.strftime("%B %Y")
    except ValueError:
        return month


def _flow_for_employee(
    *,
    employee: Dict[str, Any],
    company: Dict[str, Any],
    row: Dict[str, Any],
    month: str,
    styles: Dict[str, ParagraphStyle],
    reg: str,
    bold: str,
) -> list:
    """Return the reportlab flowables for one employee (one page)."""
    flow = []

    # Header — logo + company block
    logo_flow = None
    logo_b64 = company.get("logo_base64")
    if logo_b64:
        try:
            raw = base64.b64decode(str(logo_b64).split(",", 1)[-1])
            logo_flow = RLImage(io.BytesIO(raw), width=22 * mm, height=22 * mm)
        except Exception:
            logo_flow = None

    company_block = [
        Paragraph(company.get("name") or "S.K. Sharma & Co.", styles["brand"]),
        Paragraph(company.get("address") or "", styles["brand_sub"]),
        Paragraph(
            " · ".join(
                [x for x in (company.get("phone"), company.get("email")) if x]
            )
            or "",
            styles["brand_sub"],
        ),
        Paragraph(
            "  ".join(
                [
                    f"PF: {company.get('pf_code')}" if company.get("pf_code") else "",
                    f"ESIC: {company.get('esic_code')}" if company.get("esic_code") else "",
                ]
            ).strip(),
            styles["brand_sub"],
        ),
    ]
    header_tbl = Table(
        [[logo_flow if logo_flow is not None else "", company_block]],
        colWidths=[26 * mm, None],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]),
    )
    flow.append(header_tbl)
    flow.append(Spacer(1, 3 * mm))
    flow.append(Table(
        [[""]], colWidths=[174 * mm], rowHeights=[0.6 * mm],
        style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), BRAND)]),
    ))
    flow.append(Spacer(1, 4 * mm))

    # Title
    flow.append(Paragraph("PAYSLIP", styles["title"]))
    flow.append(Paragraph(
        f"For the month of <b>{_month_label(month)}</b>  ·  Issued {date.today().strftime('%d-%b-%Y')}",
        styles["muted_c"],
    ))
    flow.append(Spacer(1, 5 * mm))

    # Employee identity block — 2 columns
    ident_rows = [
        [Paragraph("<b>Employee</b>", styles["label"]),
         Paragraph(employee.get("name") or "—", styles["value"]),
         Paragraph("<b>Emp Code</b>", styles["label"]),
         Paragraph(employee.get("employee_code") or "—", styles["value"])],
        [Paragraph("<b>Designation</b>", styles["label"]),
         Paragraph(employee.get("designation") or "—", styles["value"]),
         Paragraph("<b>Department</b>", styles["label"]),
         Paragraph(employee.get("department") or "—", styles["value"])],
        [Paragraph("<b>UAN</b>", styles["label"]),
         Paragraph(employee.get("uan_no") or "—", styles["value"]),
         Paragraph("<b>PF No.</b>", styles["label"]),
         Paragraph(employee.get("pf_no") or "—", styles["value"])],
        [Paragraph("<b>ESI IP</b>", styles["label"]),
         Paragraph(employee.get("esi_ip_no") or "—", styles["value"]),
         Paragraph("<b>PAN</b>", styles["label"]),
         Paragraph(employee.get("pan_no") or "—", styles["value"])],
        [Paragraph("<b>Bank</b>", styles["label"]),
         Paragraph(
             (employee.get("bank_name") or "—")
             + ("  ·  A/C " + str(employee.get("bank_account"))
                if employee.get("bank_account") else "")
             + ("  ·  " + str(employee.get("bank_ifsc"))
                if employee.get("bank_ifsc") else ""),
             styles["value"],
         ),
         Paragraph("<b>DOJ</b>", styles["label"]),
         Paragraph(employee.get("doj") or "—", styles["value"])],
    ]
    ident_tbl = Table(
        ident_rows,
        colWidths=[22 * mm, 65 * mm, 22 * mm, 65 * mm],
        style=TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.4, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
            ("BACKGROUND", (0, 0), (0, -1), BRAND_LIGHT),
            ("BACKGROUND", (2, 0), (2, -1), BRAND_LIGHT),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]),
    )
    flow.append(ident_tbl)
    flow.append(Spacer(1, 4 * mm))

    # Attendance snapshot
    att_rows = [[
        Paragraph("<b>Month days</b>", styles["label"]),
        Paragraph(str(row.get("month_days") or "—"), styles["value"]),
        Paragraph("<b>Present</b>", styles["label"]),
        Paragraph(str(row.get("present_days") or "—"), styles["value"]),
        Paragraph("<b>Half</b>", styles["label"]),
        Paragraph(str(row.get("half_days") or "—"), styles["value"]),
        Paragraph("<b>OT hrs</b>", styles["label"]),
        Paragraph(str(row.get("ot_hours") or "—"), styles["value"]),
    ]]
    att_tbl = Table(
        att_rows,
        colWidths=[22 * mm, 20 * mm, 22 * mm, 20 * mm, 22 * mm, 15 * mm, 22 * mm, 15 * mm],
        style=TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.4, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
            ("BACKGROUND", (0, 0), (0, -1), BRAND_LIGHT),
            ("BACKGROUND", (2, 0), (2, -1), BRAND_LIGHT),
            ("BACKGROUND", (4, 0), (4, -1), BRAND_LIGHT),
            ("BACKGROUND", (6, 0), (6, -1), BRAND_LIGHT),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]),
    )
    flow.append(att_tbl)
    flow.append(Spacer(1, 5 * mm))

    # Earnings / Deductions two-column table
    gross = float(row.get("gross") or row.get("gross_paid") or 0)
    ded_total = float(row.get("total_deduction") or 0)
    net = float(row.get("net") or (gross - ded_total))

    earnings = [
        ("Basic Pay", row.get("base_pay") or row.get("basic")),
        ("HRA", row.get("hra")),
        ("Bonus", row.get("bonus")),
        ("Overtime", row.get("ot_pay")),
        ("Other Earnings", row.get("other_earning")),
    ]
    deductions = [
        ("PF (Employee)", row.get("pf_employee") or row.get("pf")),
        ("ESIC (Employee)", row.get("esic_employee") or row.get("esic")),
        ("Professional Tax", row.get("pt")),
        ("TDS", row.get("tds")),
        ("Advance / Loan", row.get("advance")),
        ("Other Deduction", row.get("other_deduction")),
    ]
    max_rows = max(len(earnings), len(deductions))
    table_rows = [
        [Paragraph("<b>EARNINGS</b>", styles["label"]), "",
         Paragraph("<b>DEDUCTIONS</b>", styles["label"]), ""],
    ]
    for i in range(max_rows):
        el, ev = earnings[i] if i < len(earnings) else ("", None)
        dl, dv = deductions[i] if i < len(deductions) else ("", None)
        table_rows.append([
            Paragraph(el, styles["value_l"]) if el else "",
            Paragraph(_amt(ev), styles["value_r"]) if ev is not None else "",
            Paragraph(dl, styles["value_l"]) if dl else "",
            Paragraph(_amt(dv), styles["value_r"]) if dv is not None else "",
        ])
    # totals row
    table_rows.append([
        Paragraph("<b>Gross Earnings</b>", styles["value_l"]),
        Paragraph(f"<b>{_amt(gross)}</b>", styles["value_r"]),
        Paragraph("<b>Total Deductions</b>", styles["value_l"]),
        Paragraph(f"<b>{_amt(ded_total)}</b>", styles["value_r"]),
    ])
    ed_tbl = Table(
        table_rows,
        colWidths=[45 * mm, 42 * mm, 45 * mm, 42 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, -1), (-1, -1), BRAND_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.4, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]),
    )
    flow.append(ed_tbl)
    flow.append(Spacer(1, 4 * mm))

    # Net pay banner
    net_int = int(round(net))
    net_words = _num_to_words_inr(max(net_int, 0))
    net_tbl = Table(
        [[
            Paragraph("<b>NET PAY</b>", ParagraphStyle(
                "np", fontName=bold, fontSize=12, textColor=BRAND, alignment=TA_LEFT,
            )),
            Paragraph(f"<b>{_amt(net)}</b>", ParagraphStyle(
                "npv", fontName=bold, fontSize=14, textColor=BRAND, alignment=TA_RIGHT,
            )),
        ]],
        colWidths=[100 * mm, 74 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), NET_BG),
            ("BOX", (0, 0), (-1, -1), 1.0, BRAND),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]),
    )
    flow.append(net_tbl)
    flow.append(Spacer(1, 3 * mm))
    flow.append(Paragraph(
        f"<b>In words:</b> Rupees {net_words}",
        styles["body"],
    ))
    flow.append(Spacer(1, 12 * mm))

    # Signatory footer
    flow.append(Table(
        [[Paragraph(
            "Employee signature<br/><br/>_____________________________",
            styles["sig_line"],
        ),
          Paragraph(
            f"For <b>{company.get('name') or 'Company'}</b><br/><br/>_____________________________<br/>Authorised Signatory",
            styles["sig_line"],
        )]],
        colWidths=[80 * mm, 94 * mm],
        style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]),
    ))
    # Punch line footer (Iter 181 — user request)
    flow.append(Spacer(1, 8 * mm))
    flow.append(Paragraph(
        '<i>"Your Satisfaction is Our First Ambition"</i>',
        ParagraphStyle(
            "punchline", parent=styles["muted_c"], fontSize=9.5,
            textColor=BRAND,
        ),
    ))
    return flow


def _build_styles(reg: str, bold: str) -> Dict[str, ParagraphStyle]:
    return {
        "brand": ParagraphStyle(
            "brand", fontName=bold, fontSize=15, textColor=BRAND, leading=18,
        ),
        "brand_sub": ParagraphStyle(
            "brand_sub", fontName=reg, fontSize=9, textColor=INK_SOFT, leading=12,
        ),
        "title": ParagraphStyle(
            "title", fontName=bold, fontSize=15, textColor=INK, leading=20,
            alignment=TA_CENTER, spaceAfter=2,
        ),
        "muted_c": ParagraphStyle(
            "muted_c", fontName=reg, fontSize=9, textColor=INK_MUTED,
            alignment=TA_CENTER,
        ),
        "body": ParagraphStyle(
            "body", fontName=reg, fontSize=10, textColor=INK, leading=14,
            alignment=TA_LEFT,
        ),
        "label": ParagraphStyle(
            "label", fontName=bold, fontSize=8.5, textColor=INK_SOFT,
            leading=11,
        ),
        "value": ParagraphStyle(
            "value", fontName=reg, fontSize=10, textColor=INK, leading=13,
        ),
        "value_l": ParagraphStyle(
            "value_l", fontName=reg, fontSize=9.5, textColor=INK,
            leading=13, alignment=TA_LEFT,
        ),
        "value_r": ParagraphStyle(
            "value_r", fontName=reg, fontSize=9.5, textColor=INK,
            leading=13, alignment=TA_RIGHT,
        ),
        "sig_line": ParagraphStyle(
            "sig_line", fontName=reg, fontSize=9, textColor=INK,
            alignment=TA_CENTER,
        ),
    }


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------

def build_payslip_pdf(
    *,
    employee: Dict[str, Any],
    company: Dict[str, Any],
    row: Dict[str, Any],
    month: str,
) -> bytes:
    """Single-page PDF for one employee."""
    reg, bold = _register_fonts()
    styles = _build_styles(reg, bold)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Payslip — {employee.get('name', '')} — {month}",
    )
    flow = _flow_for_employee(
        employee=employee,
        company=company,
        row=row,
        month=month,
        styles=styles,
        reg=reg,
        bold=bold,
    )
    doc.build(flow)
    return buf.getvalue()


def build_bulk_payslip_pdf(
    *,
    company: Dict[str, Any],
    month: str,
    entries: list[Dict[str, Any]],
) -> bytes:
    """Combined multi-page PDF, one page per employee.

    ``entries`` = list of ``{"employee": {...}, "row": {...}}``.
    """
    from reportlab.platypus import PageBreak
    reg, bold = _register_fonts()
    styles = _build_styles(reg, bold)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Payslips — {company.get('name', '')} — {month}",
    )
    flow = []
    for idx, entry in enumerate(entries):
        page_flow = _flow_for_employee(
            employee=entry.get("employee") or {},
            company=company,
            row=entry.get("row") or {},
            month=month,
            styles=styles,
            reg=reg,
            bold=bold,
        )
        flow.append(KeepTogether(page_flow))
        if idx < len(entries) - 1:
            flow.append(PageBreak())
    if not flow:
        # Empty run — surface a placeholder page so the download still works.
        flow.append(Paragraph(
            f"No payslips in this run for {month}.",
            styles["body"],
        ))
    doc.build(flow)
    return buf.getvalue()
