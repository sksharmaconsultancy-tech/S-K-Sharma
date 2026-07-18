"""Salary Register (Labour) — Form No. 27(1) — Iter 68.

Landscape A4 PDF that mirrors the reference sample uploaded by the user
(DEV KRIPA LABOUR.pdf).  One row per employee with earnings and
deductions grouped visually.  This is now the *default* salary format
for a salary run; additional formats can be added later behind the same
endpoint shape.

Header layout (top of every page):
    ┌─────────────────────────────────────────────────────────────────┐
    │  [rule 78 (1) (a) (i)]        SALARY REGISTER (LABOUR)         │
    │  P.F.Code: <pf_code>          <COMPANY NAME>                    │
    │  ESI Code: <esic_code>        <COMPANY ADDRESS>                 │
    │                               Register of Wages Form No. 27 (1) │
    │                               Page X of N                       │
    │                               MonthDays <days>                  │
    │                               FOR THE MONTH <MMM YYYY>          │
    └─────────────────────────────────────────────────────────────────┘

Tabular columns:
    S.No · Name / Father Name · PF No. / ESI No. · Desig. · Days/Hrs
    ── EARNINGS ── Salary · HRA · Conv · OT Amt · TOTAL
    ── DEDUCTIONS ── PF · ESI · Advance · Other · TDS · TOTAL
    Net Payable · Sign / Bank · Date of Payment

Footer (last page): grand totals + amount-in-words + "For <Company>
AUTHORISED SIGNATORY / MANAGER" block.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from utils.employee_pdf import _register_fonts

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _amt(n: Any) -> str:
    try:
        v = round(float(n or 0))
    except (TypeError, ValueError):
        v = 0
    if v == 0:
        return "-"
    return f"{v:,}".replace(",", "_").replace("_", ",")


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
        return (units[x // 100] + " Hundred" + (" " + below_100(x % 100) if x % 100 else "")).strip()

    parts: List[str] = []
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


BRAND = colors.HexColor("#1F5254")
INK = colors.HexColor("#141B1B")
LINE = colors.HexColor("#6E7C7C")
HDR_BG = colors.HexColor("#E6EDED")
ZEBRA = colors.HexColor("#F7F9F9")
GROUP_BG = colors.HexColor("#DDE7E7")


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_salary_register_pdf(
    *,
    company: Dict[str, Any],
    month: str,
    month_days: int,
    rows: List[Dict[str, Any]],
    totals: Optional[Dict[str, float]] = None,
    payment_date: Optional[str] = None,
) -> bytes:
    """Build the Form 27(1) landscape PDF."""
    reg, bold = _register_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=8 * mm, rightMargin=8 * mm,
        topMargin=8 * mm, bottomMargin=10 * mm,
        title=f"Salary Register — {company.get('name') or 'Company'} — {month}",
    )
    styles = {
        "small": ParagraphStyle("small", fontName=reg, fontSize=7.5, textColor=INK, leading=9),
        "smallB": ParagraphStyle("smallB", fontName=bold, fontSize=7.5, textColor=INK, leading=9),
        "hdrL": ParagraphStyle("hdrL", fontName=reg, fontSize=8, textColor=INK, alignment=TA_LEFT, leading=10),
        "hdrC": ParagraphStyle("hdrC", fontName=bold, fontSize=13, textColor=BRAND, alignment=TA_CENTER, leading=15),
        "hdrCS": ParagraphStyle("hdrCS", fontName=reg, fontSize=8, textColor=INK, alignment=TA_CENTER, leading=10),
        "hdrR": ParagraphStyle("hdrR", fontName=reg, fontSize=8, textColor=INK, alignment=TA_RIGHT, leading=10),
        "amt": ParagraphStyle("amt", fontName=reg, fontSize=7.5, textColor=INK, alignment=TA_RIGHT, leading=9),
        "amtB": ParagraphStyle("amtB", fontName=bold, fontSize=8.5, textColor=INK, alignment=TA_RIGHT, leading=10),
        "footNote": ParagraphStyle("footNote", fontName=reg, fontSize=8.5, textColor=INK, leading=11),
        "footSign": ParagraphStyle("footSign", fontName=bold, fontSize=9, textColor=INK, alignment=TA_CENTER, leading=12),
        "grpHdr": ParagraphStyle("grpHdr", fontName=bold, fontSize=8, textColor=INK, alignment=TA_CENTER, leading=10),
    }

    flow: List[Any] = []

    # ── Top header (3 blocks) ──────────────────────────────────────────────
    header_tbl = Table(
        [[
            Paragraph(
                f"<b>[rule 78 (1) (a) (i)]</b><br/>"
                f"<b>P.F.Code:</b> {company.get('pf_code') or '—'}<br/>"
                f"<b>ESI Code:</b> {company.get('esic_code') or '—'}",
                styles["hdrL"],
            ),
            [
                Paragraph("SALARY REGISTER (LABOUR)", styles["hdrC"]),
                Paragraph((company.get("name") or "").upper(), styles["hdrC"]),
                Paragraph(company.get("address") or "", styles["hdrCS"]),
            ],
            Paragraph(
                f"<b>Register of Wages Form No. 27 (1)</b><br/>"
                f"<b>Month Days:</b> {month_days}<br/>"
                f"<b>For the month:</b> {_month_label(month)}",
                styles["hdrR"],
            ),
        ]],
        colWidths=[75 * mm, 130 * mm, 75 * mm],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -1), 1.2, BRAND),
        ]),
    )
    flow.append(header_tbl)
    flow.append(Spacer(1, 2 * mm))

    # ── Column grouping header ─────────────────────────────────────────────
    group_row = [
        "", "", "", "", "",
        Paragraph("── EARNINGS ──", styles["grpHdr"]), "", "", "", "",
        Paragraph("── DEDUCTIONS ──", styles["grpHdr"]), "", "", "", "", "",
        "", "", "",
    ]
    col_hdr = [
        "S.No", "Name / Father Name", "PF No. / ESI No.", "Desig.", "Days/Hrs",
        "Salary", "H.R.A", "Conv.", "OT Amt", "Total",
        "P.F.", "E.S.I.", "Advance", "Other", "TDS", "Total",
        "Net Payable", "Sign / Bank", "Date of Pmt",
    ]

    col_widths_mm = [8, 40, 24, 20, 14, 14, 12, 12, 13, 15, 13, 13, 13, 13, 12, 15, 17, 15, 13]

    grouped_hdr = Table(
        [group_row, col_hdr],
        colWidths=[w * mm for w in col_widths_mm],
        repeatRows=2,
        style=TableStyle([
            ("SPAN", (5, 0), (9, 0)),   # EARNINGS
            ("SPAN", (10, 0), (15, 0)), # DEDUCTIONS
            ("BACKGROUND", (0, 0), (-1, 0), GROUP_BG),
            ("BACKGROUND", (0, 1), (-1, 1), HDR_BG),
            ("FONTNAME", (0, 1), (-1, 1), bold),
            ("FONTSIZE", (0, 1), (-1, 1), 7.5),
            ("ALIGN", (5, 1), (-4, 1), "RIGHT"),
            ("ALIGN", (16, 1), (16, 1), "RIGHT"),
            ("ALIGN", (0, 1), (4, 1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.6, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]),
    )

    # ── Employee data rows ─────────────────────────────────────────────────
    data_rows: List[List[Any]] = []
    if not rows:
        # ReportLab crashes on an empty table body — surface a friendly
        # placeholder row instead so the register PDF still renders for a
        # zero-employee run (e.g. brand-new firm, or an in-progress reprocess).
        data_rows.append([
            "", Paragraph("<i>No employees in this run</i>", styles["small"]),
            "", "", "", "", "", "", "", "",
            "", "", "", "", "", "", "", "", "",
        ])
    for i, r in enumerate(rows, start=1):
        name_fname = (r.get("name") or "").upper()
        if r.get("father_name"):
            name_fname += f"\nS/o {r.get('father_name').upper()}"
        pf_esi = "\n".join([
            r.get("pf_no") or "—",
            r.get("esi_ip_no") or "—",
        ])
        salary = _amt(r.get("basic"))
        hra = _amt(r.get("hra"))
        conv = _amt(r.get("conveyance"))
        ot = _amt(r.get("ot_pay"))
        earnings_total = _amt(r.get("gross_paid") or r.get("gross"))
        pf = _amt(r.get("pf_employee"))
        esi = _amt(r.get("esic_employee"))
        adv = _amt(r.get("advance"))
        other = _amt(r.get("other_deduction"))
        tds = _amt(r.get("tds"))
        ded_total = _amt(r.get("total_deduction"))
        net = _amt(r.get("net"))
        days_hrs = f"{r.get('present_days', 0)}"
        if r.get("duty_hours"):
            days_hrs += f"/{r.get('duty_hours')}"

        data_rows.append([
            str(i),
            Paragraph(name_fname.replace("\n", "<br/>"), styles["small"]),
            Paragraph(pf_esi.replace("\n", "<br/>"), styles["small"]),
            Paragraph(r.get("designation") or "—", styles["small"]),
            Paragraph(days_hrs, styles["small"]),
            Paragraph(salary, styles["amt"]),
            Paragraph(hra, styles["amt"]),
            Paragraph(conv, styles["amt"]),
            Paragraph(ot, styles["amt"]),
            Paragraph(earnings_total, styles["amtB"]),
            Paragraph(pf, styles["amt"]),
            Paragraph(esi, styles["amt"]),
            Paragraph(adv, styles["amt"]),
            Paragraph(other, styles["amt"]),
            Paragraph(tds, styles["amt"]),
            Paragraph(ded_total, styles["amtB"]),
            Paragraph(net, styles["amtB"]),
            "",
            payment_date or "",
        ])

    body_tbl = Table(
        data_rows,
        colWidths=[w * mm for w in col_widths_mm],
        style=TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, ZEBRA]),
        ]),
    )

    flow.append(grouped_hdr)
    flow.append(body_tbl)
    flow.append(Spacer(1, 3 * mm))

    # ── Totals row ─────────────────────────────────────────────────────────
    if totals:
        tot_row = [
            "", Paragraph(f"<b>Total ({len(rows)} employees)</b>", styles["smallB"]),
            "", "", "",
            Paragraph(_amt(totals.get("basic")), styles["amtB"]),
            Paragraph(_amt(totals.get("hra")), styles["amtB"]),
            Paragraph(_amt(totals.get("conveyance")), styles["amtB"]),
            Paragraph(_amt(totals.get("ot_pay")), styles["amtB"]),
            Paragraph(_amt(totals.get("gross")), styles["amtB"]),
            Paragraph(_amt(totals.get("pf_employee")), styles["amtB"]),
            Paragraph(_amt(totals.get("esic_employee")), styles["amtB"]),
            Paragraph(_amt(totals.get("advance")), styles["amtB"]),
            Paragraph(_amt(totals.get("other_deduction")), styles["amtB"]),
            Paragraph(_amt(totals.get("tds")), styles["amtB"]),
            Paragraph(_amt(totals.get("total_deduction")), styles["amtB"]),
            Paragraph(_amt(totals.get("net")), styles["amtB"]),
            "", "",
        ]
        totals_tbl = Table(
            [tot_row], colWidths=[w * mm for w in col_widths_mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), HDR_BG),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]),
        )
        flow.append(totals_tbl)
        flow.append(Spacer(1, 3 * mm))

        # Amount in words
        try:
            net_int = int(round(float(totals.get("net") or 0)))
            words = _num_to_words_inr(net_int)
        except Exception:
            words = "—"
        flow.append(Paragraph(
            f"<b>Net Payable Amount (In Words):</b> Rupees {words}",
            styles["footNote"],
        ))
        flow.append(Spacer(1, 8 * mm))

    # ── Signatory footer ───────────────────────────────────────────────────
    sig_tbl = Table(
        [[
            Paragraph(
                f"<b>Checked by:</b> ____________________<br/><br/>"
                f"<b>Payment Date:</b> {payment_date or '____________'}",
                styles["footNote"],
            ),
            Paragraph(
                f"<b>For {(company.get('name') or 'Company').upper()}</b><br/><br/><br/>"
                f"_______________________________<br/>"
                f"<b>AUTHORISED SIGNATORY / MANAGER</b>",
                styles["footSign"],
            ),
        ]],
        colWidths=[100 * mm, 180 * mm],
        style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]),
    )
    flow.append(sig_tbl)

    from utils.pdf_branding import punchline_flowables
    flow.extend(punchline_flowables())
    doc.build(flow)
    return buf.getvalue()


def _month_label(month: str) -> str:
    try:
        d = datetime.strptime(month, "%Y-%m")
        return d.strftime("%B %Y").upper()
    except ValueError:
        return month
