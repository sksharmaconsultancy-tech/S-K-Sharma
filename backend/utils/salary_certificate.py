"""Salary Certificate PDF (Iter 68).

One-page A4 certificate for HR / bank / immigration use.  Uses the same
S.K. Sharma & Co. corporate palette + font stack as
``utils/employee_pdf.py`` so both documents feel like they came off the
same letterhead.

Sections:
  1. Company letterhead (name, address, contact).
  2. Certificate title + reference id + issue date.
  3. Employee identity block (name, code, designation, dept, DOJ, tenure).
  4. Salary structure — computed from the firm's compliance policy and the
     employee's monthly gross.  Falls back to sensible defaults.
  5. Statutory identifiers (UAN, PF #, ESI IP #, PAN).
  6. Signature block for authorised signatory.

Callers pass:
  * ``employee`` — dict with keys name, employee_code, designation,
    department, doj, salary_monthly, uan_no, pf_no, esi_ip_no, pan_no,
    father_name, address.
  * ``company`` — dict with keys name, address, phone, email,
    logo_base64 (optional).
  * ``policy`` — the firm's compliance policy (basic_pct, hra_pct, …).
    Missing keys default to the ``_DEFAULT_POLICY`` in
    ``utils.compliance_salary``.
  * ``month``  — the reference month (``YYYY-MM``) used for the "monthly
    gross" heading; also used to compute tenure.
  * ``signatory_name`` / ``signatory_role`` — printed under the signature
    line.

Returns raw PDF bytes.
"""
from __future__ import annotations

import base64
import io
import uuid
from datetime import datetime, date
from typing import Any, Dict, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Reuse the brand-registered font helper from the master-data PDF so both
# documents render with the exact same Noto Sans typeface.
from utils.employee_pdf import _register_fonts

BRAND = colors.HexColor("#1F4E4E")
BRAND_LIGHT = colors.HexColor("#E6EDED")
ACCENT = colors.HexColor("#C89B3C")
INK = colors.HexColor("#1E2A2A")
INK_SOFT = colors.HexColor("#4C5A5A")
INK_MUTED = colors.HexColor("#7A8686")
LINE = colors.HexColor("#D6DEDE")


def _amt(n: Any) -> str:
    """Format a rupee amount as ``₹1,23,456``."""
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    return "\u20B9" + f"{int(round(v)):,}".replace(",", "_").replace("_", ",")


def _parse_doj(doj: Optional[str]) -> Optional[date]:
    if not doj:
        return None
    try:
        return datetime.strptime(str(doj)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _tenure_str(doj_str: Optional[str], as_of: Optional[date] = None) -> str:
    doj = _parse_doj(doj_str)
    if not doj:
        return "—"
    ref = as_of or date.today()
    years = ref.year - doj.year
    months = ref.month - doj.month
    if months < 0:
        years -= 1
        months += 12
    if years == 0 and months == 0:
        return "New joiner"
    parts = []
    if years > 0:
        parts.append(f"{years} year{'s' if years > 1 else ''}")
    if months > 0:
        parts.append(f"{months} month{'s' if months > 1 else ''}")
    return " ".join(parts) or "—"


_DEFAULT_STRUCTURE = {
    "basic_pct": 40.0,
    "hra_pct": 20.0,
    "conveyance_pct": 5.0,
    "medical_pct": 3.0,
    "special_pct": 32.0,
    "others_pct": 0.0,
}


def _breakdown(
    gross_monthly: float,
    policy: Dict[str, Any],
) -> Dict[str, float]:
    """Return the salary component split derived from firm policy."""
    parts = {}
    for k in _DEFAULT_STRUCTURE:
        pct = policy.get(k)
        if pct is None:
            pct = _DEFAULT_STRUCTURE[k]
        parts[k] = float(pct)
    return {
        "basic": round(gross_monthly * parts["basic_pct"] / 100.0, 2),
        "hra": round(gross_monthly * parts["hra_pct"] / 100.0, 2),
        "conveyance": round(gross_monthly * parts["conveyance_pct"] / 100.0, 2),
        "medical": round(gross_monthly * parts["medical_pct"] / 100.0, 2),
        "special": round(gross_monthly * parts["special_pct"] / 100.0, 2),
        "others": round(gross_monthly * parts["others_pct"] / 100.0, 2),
    }


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_salary_certificate_pdf(
    *,
    employee: Dict[str, Any],
    company: Dict[str, Any],
    policy: Dict[str, Any],
    month: str,
    signatory_name: Optional[str] = None,
    signatory_role: Optional[str] = None,
    certificate_id: Optional[str] = None,
) -> bytes:
    """Return the PDF bytes for a one-page Salary Certificate."""
    reg, bold = _register_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Salary Certificate — {employee.get('name', '')}",
    )

    styles = {
        "brand": ParagraphStyle(
            "brand", fontName=bold, fontSize=15, textColor=BRAND, leading=18,
        ),
        "brand_sub": ParagraphStyle(
            "brand_sub", fontName=reg, fontSize=9, textColor=INK_SOFT, leading=12,
        ),
        "title": ParagraphStyle(
            "title", fontName=bold, fontSize=17, textColor=INK, leading=22,
            alignment=TA_CENTER, spaceAfter=4,
        ),
        "muted_c": ParagraphStyle(
            "muted_c", fontName=reg, fontSize=9, textColor=INK_MUTED,
            alignment=TA_CENTER,
        ),
        "body": ParagraphStyle(
            "body", fontName=reg, fontSize=10.5, textColor=INK, leading=15,
            alignment=TA_LEFT,
        ),
        "label": ParagraphStyle(
            "label", fontName=bold, fontSize=8.5, textColor=INK_SOFT,
            leading=11, textTransform="uppercase",
        ),
        "value": ParagraphStyle(
            "value", fontName=bold, fontSize=11, textColor=INK, leading=15,
        ),
        "sig_line": ParagraphStyle(
            "sig_line", fontName=reg, fontSize=9, textColor=INK,
            alignment=TA_CENTER,
        ),
    }

    flow = []

    # Header — logo + company block
    logo_flow = None
    logo_b64 = company.get("logo_base64")
    if logo_b64:
        try:
            raw = base64.b64decode(logo_b64.split(",", 1)[-1])
            logo_flow = RLImage(io.BytesIO(raw), width=22 * mm, height=22 * mm)
        except Exception:
            logo_flow = None

    company_block = [
        Paragraph(company.get("name") or "S.K. Sharma & Co.", styles["brand"]),
        Paragraph(company.get("address") or "", styles["brand_sub"]),
        Paragraph(
            " · ".join([x for x in (company.get("phone"), company.get("email")) if x]) or "",
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
    flow.append(Spacer(1, 4 * mm))
    flow.append(Table(
        [[""]], colWidths=[174 * mm], rowHeights=[0.6 * mm],
        style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), BRAND)]),
    ))
    flow.append(Spacer(1, 6 * mm))

    # Title + meta
    cert_id = certificate_id or f"SC-{uuid.uuid4().hex[:8].upper()}"
    flow.append(Paragraph("SALARY CERTIFICATE", styles["title"]))
    flow.append(Paragraph(
        f"Certificate No. <b>{cert_id}</b>  ·  Issued on {date.today().strftime('%d-%b-%Y')}"
        f"  ·  Reference month {month}",
        styles["muted_c"],
    ))
    flow.append(Spacer(1, 8 * mm))

    # Salutation
    flow.append(Paragraph("TO WHOMSOEVER IT MAY CONCERN", ParagraphStyle(
        "sal", fontName=bold, fontSize=10.5, textColor=INK, alignment=TA_CENTER,
    )))
    flow.append(Spacer(1, 4 * mm))

    # Body paragraph
    body_txt = (
        f"This is to certify that <b>{employee.get('name', '—')}</b> "
        f"({employee.get('gender', '') or 'S/o' if not employee.get('father_name') else ''} "
        f"{('S/o ' + employee.get('father_name')) if employee.get('father_name') else ''}), "
        f"Employee Code <b>{employee.get('employee_code', '—')}</b>, has been employed with "
        f"<b>{company.get('name') or 'S.K. Sharma &amp; Co.'}</b> as "
        f"<b>{employee.get('designation') or '—'}</b> in the "
        f"<b>{employee.get('department') or '—'}</b> department since "
        f"<b>{employee.get('doj') or '—'}</b> ({_tenure_str(employee.get('doj'))}). "
        f"Their current monthly gross salary is <b>{_amt(employee.get('salary_monthly'))}</b>."
    )
    flow.append(Paragraph(body_txt, styles["body"]))
    flow.append(Spacer(1, 4 * mm))

    # Salary breakdown table
    gross = float(employee.get("salary_monthly") or 0)
    b = _breakdown(gross, policy or {})
    breakdown_rows = [
        [Paragraph("<b>Salary component</b>", styles["label"]),
         Paragraph("<b>Monthly (INR)</b>", styles["label"])],
        ["Basic", _amt(b["basic"])],
        ["HRA", _amt(b["hra"])],
        ["Conveyance", _amt(b["conveyance"])],
        ["Medical", _amt(b["medical"])],
        ["Special", _amt(b["special"])],
        ["Others", _amt(b["others"])],
        [Paragraph("<b>Gross Monthly</b>", ParagraphStyle(
            "bold", fontName=bold, fontSize=10.5, textColor=INK,
        )),
         Paragraph(f"<b>{_amt(gross)}</b>", ParagraphStyle(
            "boldR", fontName=bold, fontSize=10.5, textColor=INK, alignment=TA_RIGHT,
         ))],
        [Paragraph("<b>Annual Gross</b>", ParagraphStyle(
            "bold2", fontName=bold, fontSize=10.5, textColor=INK,
        )),
         Paragraph(f"<b>{_amt(gross * 12)}</b>", ParagraphStyle(
            "bold2R", fontName=bold, fontSize=10.5, textColor=INK, alignment=TA_RIGHT,
         ))],
    ]
    breakdown_tbl = Table(
        breakdown_rows, colWidths=[88 * mm, 62 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), bold),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("FONTNAME", (0, 1), (-1, -3), reg),
            ("FONTSIZE", (0, 1), (-1, -3), 10),
            ("TEXTCOLOR", (0, 1), (-1, -3), INK),
            ("BACKGROUND", (0, -2), (-1, -2), BRAND_LIGHT),
            ("BACKGROUND", (0, -1), (-1, -1), ACCENT),
            ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
            ("LINEBELOW", (0, 0), (-1, -3), 0.4, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]),
    )
    flow.append(breakdown_tbl)
    flow.append(Spacer(1, 5 * mm))

    # Statutory identifiers
    ids_rows = [
        [Paragraph("<b>UAN</b>", styles["label"]),
         Paragraph(employee.get("uan_no") or "—", styles["value"]),
         Paragraph("<b>PF No.</b>", styles["label"]),
         Paragraph(employee.get("pf_no") or "—", styles["value"])],
        [Paragraph("<b>ESI IP</b>", styles["label"]),
         Paragraph(employee.get("esi_ip_no") or "—", styles["value"]),
         Paragraph("<b>PAN</b>", styles["label"]),
         Paragraph(employee.get("pan_no") or "—", styles["value"])],
    ]
    ids_tbl = Table(
        ids_rows, colWidths=[26 * mm, 49 * mm, 26 * mm, 49 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.4, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]),
    )
    flow.append(ids_tbl)
    flow.append(Spacer(1, 4 * mm))

    # Closing paragraph
    flow.append(Paragraph(
        "This certificate is issued at the request of the employee and reflects "
        "the current salary structure as per company records.",
        styles["body"],
    ))
    flow.append(Spacer(1, 12 * mm))

    # Signature block — right-aligned
    sig_name = signatory_name or "HR & Payroll"
    sig_role = signatory_role or "Authorised Signatory"
    sig_tbl = Table(
        [[Paragraph(
            f"<br/><br/>_____________________________<br/>"
            f"<b>{sig_name}</b><br/>"
            f"{sig_role}<br/>"
            f"{company.get('name') or 'S.K. Sharma &amp; Co.'}",
            styles["sig_line"],
        )]],
        colWidths=[80 * mm],
        hAlign="RIGHT",
    )
    flow.append(sig_tbl)

    doc.build(flow)
    return buf.getvalue()
