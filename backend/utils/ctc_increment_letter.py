"""Iter 500 — CTC Increment / Salary Revision Letter PDF.

One-click letter generated from a ``ctc_revisions`` entry: firm letterhead,
employee block, OLD vs NEW CTC breakup comparison (via the same
``calc_ctc_breakup`` formula engine), increment amount / %, reason,
effective date and authorised-signatory footer. Brand palette matches
``payslip_pdf.py`` / ``salary_certificate.py``.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
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

from utils.employee_pdf import _register_fonts

BRAND = colors.HexColor("#1F4E4E")
BRAND_LIGHT = colors.HexColor("#E6EDED")
INK = colors.HexColor("#1E2A2A")
INK_SOFT = colors.HexColor("#4C5A5A")
LINE = colors.HexColor("#D6DEDE")
GREEN = colors.HexColor("#15803D")
RED = colors.HexColor("#B91C1C")


def _amt(n: Any) -> str:
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    return "\u20B9" + f"{int(round(v)):,}".replace(",", "_").replace("_", ",")


def _dt(s: Optional[str]) -> str:
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return s or "—"


def build_increment_letter_pdf(
    *,
    employee: Dict[str, Any],
    company: Dict[str, Any],
    revision: Dict[str, Any],
    old_breakup: Optional[Dict[str, Any]],
    new_breakup: Optional[Dict[str, Any]],
    new_structure_name: str = "",
) -> bytes:
    reg, bold = _register_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Salary Revision Letter — {employee.get('name', '')}")

    st_brand = ParagraphStyle("b", fontName=bold, fontSize=15, textColor=BRAND, leading=18)
    st_sub = ParagraphStyle("s", fontName=reg, fontSize=9, textColor=INK_SOFT, leading=12)
    st_title = ParagraphStyle("t", fontName=bold, fontSize=13.5, textColor=INK,
                              alignment=TA_CENTER, leading=17)
    st_body = ParagraphStyle("bd", fontName=reg, fontSize=10, textColor=INK, leading=15)
    st_lbl = ParagraphStyle("l", fontName=bold, fontSize=9, textColor=INK_SOFT, leading=12)
    st_l = ParagraphStyle("vl", fontName=reg, fontSize=9.5, textColor=INK,
                          leading=13, alignment=TA_LEFT)
    st_r = ParagraphStyle("vr", fontName=reg, fontSize=9.5, textColor=INK,
                          leading=13, alignment=TA_RIGHT)
    st_sig = ParagraphStyle("sg", fontName=reg, fontSize=9, textColor=INK,
                            alignment=TA_CENTER)

    flow: List[Any] = []
    # letterhead
    flow.append(Paragraph(company.get("name") or "Company", st_brand))
    addr_bits = [company.get("address"), company.get("phone"), company.get("email")]
    flow.append(Paragraph(" · ".join(str(b) for b in addr_bits if b), st_sub))
    flow.append(Spacer(1, 2 * mm))
    flow.append(Table([[""]], colWidths=[174 * mm], rowHeights=[1.2],
                      style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), BRAND)])))
    flow.append(Spacer(1, 5 * mm))

    old_ctc = float(revision.get("old_ctc") or 0)
    new_ctc = float(revision.get("new_ctc") or 0)
    diff = round(new_ctc - old_ctc, 2)
    pct = round(diff / old_ctc * 100, 1) if old_ctc > 0 else None
    is_increment = diff > 0
    title = "SALARY INCREMENT LETTER" if is_increment else "SALARY REVISION LETTER"
    flow.append(Paragraph(title, st_title))
    flow.append(Paragraph(
        f"Ref: {revision.get('rev_id', '')} · Date: {_dt(revision.get('created_at'))}",
        ParagraphStyle("m", parent=st_sub, alignment=TA_CENTER)))
    flow.append(Spacer(1, 5 * mm))

    # addressee
    flow.append(Paragraph(
        f"<b>{employee.get('name') or ''}</b>"
        f"{' · Emp. Code ' + str(employee.get('employee_code')) if employee.get('employee_code') else ''}"
        f"{'<br/>' + str(employee.get('designation')) if employee.get('designation') else ''}"
        f"{' · ' + str(employee.get('department')) if employee.get('department') else ''}",
        st_body))
    flow.append(Spacer(1, 4 * mm))

    # body
    if is_increment:
        body = (f"Dear {employee.get('name') or 'Employee'},<br/><br/>"
                f"We are pleased to inform you that, in recognition of your "
                f"performance and contribution, your annual compensation has "
                f"been revised effective <b>{_dt(revision.get('effective_date'))}</b>. "
                f"Your Monthly CTC stands revised from <b>{_amt(old_ctc)}</b> to "
                f"<b>{_amt(new_ctc)}</b>"
                + (f" — an increase of <b>{_amt(diff)}</b> ({pct}%)." if pct is not None
                   else f" — an increase of <b>{_amt(diff)}</b>."))
    else:
        body = (f"Dear {employee.get('name') or 'Employee'},<br/><br/>"
                f"This is to inform you that your compensation structure has "
                f"been revised effective <b>{_dt(revision.get('effective_date'))}</b>. "
                f"Your revised Monthly CTC is <b>{_amt(new_ctc)}</b>"
                + (f" (previously {_amt(old_ctc)})." if old_ctc > 0 else "."))
    if new_structure_name:
        body += f"<br/>Applicable CTC structure: <b>{new_structure_name}</b>."
    flow.append(Paragraph(body, st_body))
    flow.append(Spacer(1, 5 * mm))

    # comparison table
    def _rows_of(bk: Optional[Dict[str, Any]]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if not bk:
            return out
        for e in bk.get("earnings") or []:
            out[e["label"]] = e["amount"]
        out["__gross"] = bk.get("gross") or 0
        for e in bk.get("employer_contributions") or []:
            out[e["label"]] = e["amount"]
        out["__er"] = bk.get("employer_total") or 0
        out["__net"] = bk.get("net_salary") or 0
        return out

    new_map = _rows_of(new_breakup)
    old_map = _rows_of(old_breakup)
    labels: List[str] = []
    for bk in (new_breakup, old_breakup):
        for sec in ("earnings", "employer_contributions"):
            for e in (bk or {}).get(sec) or []:
                if e["label"] not in labels:
                    labels.append(e["label"])

    def _cell(m: Dict[str, float], k: str) -> str:
        return _amt(m[k]) if k in m else "—"

    trows: List[List[Any]] = [[
        Paragraph("<b>COMPONENT (per month)</b>", ParagraphStyle(
            "h", parent=st_lbl, textColor=colors.white)),
        Paragraph("<b>PREVIOUS</b>", ParagraphStyle(
            "h2", parent=st_lbl, textColor=colors.white, alignment=TA_RIGHT)),
        Paragraph("<b>REVISED</b>", ParagraphStyle(
            "h3", parent=st_lbl, textColor=colors.white, alignment=TA_RIGHT)),
    ]]
    earn_labels = [e["label"] for e in (new_breakup or {}).get("earnings") or []] + \
                  [e["label"] for e in (old_breakup or {}).get("earnings") or []]
    for lb in labels:
        if lb in earn_labels:
            trows.append([Paragraph(lb, st_l),
                          Paragraph(_cell(old_map, lb), st_r),
                          Paragraph(_cell(new_map, lb), st_r)])
    trows.append([Paragraph("<b>Gross Earnings</b>", st_l),
                  Paragraph(f"<b>{_cell(old_map, '__gross')}</b>", st_r),
                  Paragraph(f"<b>{_cell(new_map, '__gross')}</b>", st_r)])
    for lb in labels:
        if lb not in earn_labels:
            trows.append([Paragraph(lb, st_l),
                          Paragraph(_cell(old_map, lb), st_r),
                          Paragraph(_cell(new_map, lb), st_r)])
    trows.append([Paragraph("<b>Total Employer Contribution</b>", st_l),
                  Paragraph(f"<b>{_cell(old_map, '__er')}</b>", st_r),
                  Paragraph(f"<b>{_cell(new_map, '__er')}</b>", st_r)])
    trows.append([Paragraph("<b>Monthly CTC</b>", st_l),
                  Paragraph(f"<b>{_amt(old_ctc) if old_ctc > 0 else '—'}</b>", st_r),
                  Paragraph(f"<b>{_amt(new_ctc)}</b>", st_r)])
    trows.append([Paragraph("<b>Annual CTC</b>", st_l),
                  Paragraph(f"<b>{_amt(old_ctc * 12) if old_ctc > 0 else '—'}</b>", st_r),
                  Paragraph(f"<b>{_amt(new_ctc * 12)}</b>", st_r)])
    trows.append([Paragraph("Estimated Net Salary", st_l),
                  Paragraph(_cell(old_map, "__net"), st_r),
                  Paragraph(_cell(new_map, "__net"), st_r)])
    dcol = GREEN if diff >= 0 else RED
    trows.append([
        Paragraph("<b>Monthly Difference</b>", ParagraphStyle(
            "d", parent=st_l, textColor=dcol)),
        "",
        Paragraph(f"<b>{'+' if diff >= 0 else ''}{_amt(diff)}"
                  + (f" ({pct}%)" if pct is not None else "") + "</b>",
                  ParagraphStyle("dv", parent=st_r, textColor=dcol)),
    ])
    flow.append(Table(
        trows, colWidths=[84 * mm, 45 * mm, 45 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND),
            ("BACKGROUND", (0, -1), (-1, -1), BRAND_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.4, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])))
    flow.append(Spacer(1, 4 * mm))

    if (revision.get("reason") or "").strip():
        flow.append(Paragraph(f"<b>Reason:</b> {revision['reason']}", st_body))
    flow.append(Paragraph(
        "All other terms and conditions of your employment remain unchanged. "
        "We thank you for your dedication and look forward to your continued "
        "contribution.", st_body))
    flow.append(Spacer(1, 12 * mm))

    flow.append(Table(
        [[Paragraph("Employee acknowledgement<br/><br/>_____________________________",
                    st_sig),
          Paragraph(f"For <b>{company.get('name') or 'Company'}</b><br/><br/>"
                    f"_____________________________<br/>Authorised Signatory"
                    + (f"<br/>{revision.get('approved_by')}"
                       if revision.get("approved_by") else ""),
                    st_sig)]],
        colWidths=[80 * mm, 94 * mm],
        style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")])))
    flow.append(Spacer(1, 8 * mm))
    flow.append(Paragraph(
        '<i>"Your Satisfaction is Our First Ambition"</i>',
        ParagraphStyle("p", fontName=reg, fontSize=9.5, textColor=BRAND,
                       alignment=TA_CENTER)))
    doc.build(flow)
    return buf.getvalue()
