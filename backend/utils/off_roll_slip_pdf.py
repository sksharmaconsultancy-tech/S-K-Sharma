"""
Off-Roll Simple Slip — Iter 77j.

A minimal 4-field slip for off-roll (contract / temp) employees:
    Name, Days, Rate, Amount

No compliance / statutory columns. Portrait A5-ish layout suitable for
printing multiple slips per A4 page (2 up).

Consumed by the endpoint::

    GET /api/admin/salary-runs/{run_id}/off-roll-slip/{user_id}
"""
from __future__ import annotations

from io import BytesIO
from typing import Any, Dict

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _fmt_amt(v: Any) -> str:
    """Indian-rupee-style number formatting with a rupee symbol."""
    try:
        n = float(v or 0.0)
    except Exception:
        return "0.00"
    return f"\u20B9 {n:,.2f}"


def build_off_roll_slip_pdf(
    company_name: str,
    period_label: str,
    row: Dict[str, Any],
) -> bytes:
    """Build the simple off-roll slip PDF for a single employee.

    ``row`` must contain: ``name``, ``employee_code`` (opt), ``present_days``,
    ``rate``, ``net`` (final payable). Missing fields fall back to blank.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Off-Roll Slip — {row.get('name') or ''}",
    )
    styles = {
        "title": ParagraphStyle(
            "title",
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=colors.HexColor("#B4232C"),
            spaceAfter=4,
            alignment=1,
        ),
        "period": ParagraphStyle(
            "period",
            fontName="Helvetica",
            fontSize=10,
            textColor=colors.HexColor("#555555"),
            spaceAfter=14,
            alignment=1,
        ),
        "label": ParagraphStyle(
            "label",
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=colors.HexColor("#333333"),
        ),
        "value": ParagraphStyle(
            "value",
            fontName="Helvetica",
            fontSize=11,
            textColor=colors.HexColor("#000000"),
        ),
        "amount_value": ParagraphStyle(
            "amount_value",
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=colors.HexColor("#B4232C"),
        ),
    }

    story = []
    story.append(Paragraph(company_name or "", styles["title"]))
    story.append(Paragraph(f"Off-Roll Salary Slip — {period_label}", styles["period"]))

    name = row.get("name") or "—"
    code = row.get("employee_code") or "—"
    days = row.get("present_days") or 0
    rate = row.get("rate") or 0.0
    net = row.get("net") if row.get("net") is not None else row.get("gross")

    data = [
        [Paragraph("Name", styles["label"]), Paragraph(str(name), styles["value"])],
        [Paragraph("Employee Code", styles["label"]), Paragraph(str(code), styles["value"])],
        [Paragraph("Days Worked", styles["label"]), Paragraph(str(int(days)), styles["value"])],
        [Paragraph("Daily Rate", styles["label"]), Paragraph(_fmt_amt(rate), styles["value"])],
        [Paragraph("Amount Payable", styles["label"]),
         Paragraph(_fmt_amt(net or 0.0), styles["amount_value"])],
    ]
    t = Table(data, colWidths=[45 * mm, 100 * mm])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CCCCCC")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#EEEEEE")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -2), [colors.white, colors.HexColor("#FAFAFA")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#FFF5F5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)

    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "This slip is issued for off-roll / contract engagement. No statutory "
        "deductions (PF, ESI, PT, TDS) are applicable. Amount payable is "
        "days worked \u00D7 daily rate.",
        ParagraphStyle(
            "note",
            fontName="Helvetica-Oblique",
            fontSize=9,
            textColor=colors.HexColor("#666666"),
            alignment=1,
        ),
    ))

    from utils.pdf_branding import punchline_flowables
    story.extend(punchline_flowables())
    doc.build(story)
    return buf.getvalue()
