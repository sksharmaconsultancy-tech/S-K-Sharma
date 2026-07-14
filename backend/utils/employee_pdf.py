"""Generate a printable "Employee Master Data" PDF.

Called by ``GET /api/admin/employees/{user_id}/master-pdf``. Layout is a
2-page official Employee Data Sheet in the same S.K. Sharma & Co. brand as
the prospectus:

* Page 1: Company header + Personal + KYC + Employment sections
* Page 2: Salary policy + Bank + Documents on record + Verification /
  Signature block for HR & Employee.

Returns the PDF bytes so the FastAPI route can stream it AND persist a
copy in Mongo (`employee_master_pdfs` collection) for later re-download.
"""
from __future__ import annotations

import base64
import io
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    HRFlowable,
    Image as RLImage,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# --------------------------------------------------------------------------- 
# Paths & fonts
# --------------------------------------------------------------------------- 
BACKEND_DIR = Path(__file__).resolve().parents[1]
FONTS_DIR = BACKEND_DIR / "assets" / "fonts"

# Corporate palette
BRAND = colors.HexColor("#1F4E4E")
BRAND_LIGHT = colors.HexColor("#E6EDED")
ACCENT = colors.HexColor("#C89B3C")
INK = colors.HexColor("#1E2A2A")
INK_SOFT = colors.HexColor("#4C5A5A")
INK_MUTED = colors.HexColor("#7A8686")
LINE = colors.HexColor("#D6DEDE")
BG_SOFT = colors.HexColor("#F7F9F9")

_FONTS_REGISTERED = False


def _register_fonts() -> Tuple[str, str]:
    global _FONTS_REGISTERED
    reg = "NotoSans"
    bold = "NotoSans-Bold"
    if not _FONTS_REGISTERED:
        try:
            pdfmetrics.registerFont(TTFont(reg, str(FONTS_DIR / "NotoSans-Regular.ttf")))
            pdfmetrics.registerFont(TTFont(bold, str(FONTS_DIR / "NotoSans-Bold.ttf")))
        except Exception:
            # Fallback to built-in Helvetica if font files missing
            reg = "Helvetica"
            bold = "Helvetica-Bold"
        _FONTS_REGISTERED = True
    return reg, bold


def _build_styles() -> dict:
    reg, bold = _register_fonts()
    base = getSampleStyleSheet()

    def _new(name: str, **kw) -> ParagraphStyle:
        return ParagraphStyle(name, parent=base["Normal"], **kw)

    return {
        "reg": reg,
        "bold": bold,
        "h_title": _new(
            "HTitle", fontName=bold, fontSize=18, leading=22,
            textColor=colors.white, alignment=TA_LEFT,
        ),
        "h_sub": _new(
            "HSub", fontName=reg, fontSize=10, leading=13,
            textColor=colors.HexColor("#DDEDED"), alignment=TA_LEFT,
        ),
        "h_meta": _new(
            "HMeta", fontName=reg, fontSize=9, leading=12,
            textColor=colors.HexColor("#CBDDDD"), alignment=TA_RIGHT,
        ),
        "section": _new(
            "Section", fontName=bold, fontSize=11.5, leading=14,
            textColor=BRAND, alignment=TA_LEFT, spaceBefore=8, spaceAfter=4,
        ),
        "label": _new(
            "Label", fontName=bold, fontSize=8.5, leading=11,
            textColor=INK_SOFT, alignment=TA_LEFT,
        ),
        "value": _new(
            "Value", fontName=reg, fontSize=10, leading=13,
            textColor=INK, alignment=TA_LEFT,
        ),
        "small": _new(
            "Small", fontName=reg, fontSize=8, leading=11,
            textColor=INK_MUTED, alignment=TA_LEFT,
        ),
        "footer": _new(
            "Footer", fontName=reg, fontSize=8, leading=11,
            textColor=INK_MUTED, alignment=TA_CENTER,
        ),
        "sig_label": _new(
            "SigLabel", fontName=bold, fontSize=9, leading=12,
            textColor=INK_SOFT, alignment=TA_CENTER,
        ),
    }


# --------------------------------------------------------------------------- 
# Header / footer painters
# --------------------------------------------------------------------------- 
class _DocState:
    """Container passed to page painters via ``BaseDocTemplate.build``."""

    def __init__(self, company_name: str, doc_title: str, ref_no: str):
        self.company_name = company_name
        self.doc_title = doc_title
        self.ref_no = ref_no


def _make_header_painter(state: _DocState):
    reg, bold = _register_fonts()

    def _paint(canvas, doc):
        W, H = A4
        c = canvas
        c.saveState()
        # Header band
        c.setFillColor(BRAND)
        c.rect(0, H - 32 * mm, W, 32 * mm, stroke=0, fill=1)
        # Gold accent
        c.setFillColor(ACCENT)
        c.rect(0, H - 34 * mm, W, 2 * mm, stroke=0, fill=1)
        # Left: company name + doc title
        c.setFillColor(colors.white)
        c.setFont(bold, 15)
        c.drawString(15 * mm, H - 14 * mm, state.company_name)
        c.setFont(reg, 10)
        c.setFillColor(colors.HexColor("#DDEDED"))
        c.drawString(15 * mm, H - 20 * mm, state.doc_title)
        # Right: ref no + date
        c.setFont(reg, 9)
        c.setFillColor(colors.HexColor("#CBDDDD"))
        c.drawRightString(W - 15 * mm, H - 14 * mm, f"Ref: {state.ref_no}")
        c.drawRightString(
            W - 15 * mm, H - 20 * mm,
            "Generated: " + datetime.now().strftime("%d %b %Y  %H:%M"),
        )
        # Footer
        c.setFillColor(INK_MUTED)
        c.setFont(reg, 8)
        c.drawString(15 * mm, 10 * mm, "This is a system-generated Employee Master data sheet.")
        c.drawRightString(W - 15 * mm, 10 * mm, f"Page {doc.page}")
        c.restoreState()

    return _paint


# --------------------------------------------------------------------------- 
# Helpers to build data tables
# --------------------------------------------------------------------------- 
def _fmt_val(v: Any) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        # Salary/money-ish rounding
        if isinstance(v, float):
            return f"{v:,.2f}"
        return f"{v:,}"
    s = str(v).strip()
    return s if s else "—"


def _mask_aadhar(v: Optional[str]) -> str:
    if not v:
        return "—"
    digits = "".join(c for c in v if c.isdigit())
    if len(digits) >= 4:
        return "XXXX-XXXX-" + digits[-4:]
    return v


def _kv_table(rows: List[Tuple[str, Any]], styles: dict, col_widths=None) -> Table:
    """Two-column label/value grid. Accepts a flat list of (label, value)
    tuples and renders them in 2 pairs per row (=4 columns).
    """
    if col_widths is None:
        col_widths = [30 * mm, 55 * mm, 30 * mm, 55 * mm]

    # Chunk into rows of 2 pairs
    grid: List[List[Any]] = []
    for i in range(0, len(rows), 2):
        pair1 = rows[i]
        pair2 = rows[i + 1] if i + 1 < len(rows) else ("", "")
        grid.append([
            Paragraph(pair1[0], styles["label"]),
            Paragraph(_fmt_val(pair1[1]), styles["value"]),
            Paragraph(pair2[0], styles["label"]),
            Paragraph(_fmt_val(pair2[1]), styles["value"]),
        ])

    t = Table(grid, colWidths=col_widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
        ("BACKGROUND", (0, 0), (0, -1), BG_SOFT),
        ("BACKGROUND", (2, 0), (2, -1), BG_SOFT),
    ]))
    return t


def _section_header(styles: dict, title: str) -> Flowable:
    """Coloured band section header."""
    t = Table(
        [[Paragraph(f"<font color='white'><b>{title}</b></font>", styles["value"])]],
        colWidths=[170 * mm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _photo_flowable(base64_png: Optional[str], size: float = 32 * mm) -> Flowable:
    """Return either an Image flowable or a placeholder box."""
    if base64_png:
        try:
            raw = base64_png
            if "," in raw:
                raw = raw.split(",", 1)[1]
            data = base64.b64decode(raw)
            img = RLImage(io.BytesIO(data), width=size, height=size)
            img.hAlign = "RIGHT"
            return img
        except Exception:
            pass
    # Placeholder box
    t = Table([[Paragraph("PHOTO", ParagraphStyle(
        "PhotoPlaceholder", fontSize=8, textColor=INK_MUTED, alignment=TA_CENTER,
    ))]], colWidths=[size], rowHeights=[size])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), BG_SOFT),
    ]))
    return t


def _identity_block(styles: dict, user: dict) -> Flowable:
    """Top identity strip: name / code / role / photo."""
    left = [
        Paragraph(_fmt_val(user.get("name")), ParagraphStyle(
            "IdName", fontName=styles["bold"], fontSize=16, leading=19,
            textColor=INK, alignment=TA_LEFT,
        )),
        Paragraph(
            f"<b>Employee Code:</b> {_fmt_val(user.get('employee_code'))}"
            f"    <b>Role:</b> {_fmt_val(user.get('role', '').replace('_', ' ').title())}",
            styles["value"],
        ),
        Paragraph(
            f"<b>Department:</b> {_fmt_val(user.get('department'))}"
            f"    <b>Designation:</b> {_fmt_val(user.get('designation') or user.get('position'))}",
            styles["value"],
        ),
    ]
    right = _photo_flowable(user.get("picture"))
    t = Table([[left, right]], colWidths=[130 * mm, 40 * mm], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _doc_list_table(styles: dict, documents: List[dict]) -> Flowable:
    """Documents-on-record listing."""
    if not documents:
        return Paragraph(
            "<i>No scan documents on record yet.</i>",
            ParagraphStyle("empty", parent=styles["small"], textColor=INK_MUTED,
                           fontName=styles["reg"], fontSize=9),
        )
    header = ["#", "Category", "Custom label", "File", "Uploaded"]
    rows: List[List[Any]] = [header]
    for i, d in enumerate(documents, start=1):
        rows.append([
            str(i),
            _fmt_val(d.get("category")),
            _fmt_val(d.get("custom_label")),
            _fmt_val(d.get("filename")),
            _fmt_val((d.get("uploaded_at") or "")[:10]),
        ])
    t = Table(rows, colWidths=[10 * mm, 35 * mm, 45 * mm, 50 * mm, 30 * mm], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), styles["bold"]),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
        ("BACKGROUND", (0, 1), (-1, -1), BG_SOFT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _signature_block(styles: dict) -> Flowable:
    """Two-column signature block for HR & Employee."""
    def _sig_cell(title: str) -> Table:
        cell = Table([
            [Paragraph(" ", styles["value"])],  # signature space
            [Paragraph("_________________________________", styles["value"])],
            [Paragraph(f"<b>{title}</b>", styles["sig_label"])],
            [Paragraph("Name & Signature with Date", styles["small"])],
        ], colWidths=[80 * mm])
        cell.setStyle(TableStyle([
            ("TOPPADDING", (0, 0), (-1, 0), 22),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        return cell

    t = Table(
        [[_sig_cell("Employer / HR"), _sig_cell("Employee")]],
        colWidths=[85 * mm, 85 * mm],
        hAlign="LEFT",
    )
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


# --------------------------------------------------------------------------- 
# Main build
# --------------------------------------------------------------------------- 
def build_employee_master_pdf(
    user: dict,
    company: Optional[dict] = None,
    policy: Optional[dict] = None,
    documents: Optional[List[dict]] = None,
) -> bytes:
    """Return the PDF as raw bytes.

    Args:
        user: Full user document (with KYC, bank etc.).
        company: Company doc for header context. Optional.
        policy: Employee policy dict (from user.employee_policy). Optional.
        documents: List of scan-document metadata dicts (no base64). Optional.
    """
    company = company or {}
    policy = policy or user.get("employee_policy") or {}
    documents = documents or []

    styles = _build_styles()
    buf = io.BytesIO()

    company_name = company.get("name") or "Employer"
    ref_no = user.get("employee_code") or user.get("user_id", "")[:10].upper()
    doc_title = f"Employee Master Data Sheet — {user.get('name') or '—'}"
    state = _DocState(company_name=company_name, doc_title=doc_title, ref_no=ref_no)

    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=38 * mm, bottomMargin=16 * mm,
        title=doc_title, author=company_name,
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height, id="body",
        showBoundary=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="main", frames=[frame], onPage=_make_header_painter(state)),
    ])

    story: List[Flowable] = []

    # Identity strip
    story.append(_identity_block(styles, user))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=0.5, color=LINE))

    # --- PERSONAL ---
    story.append(_section_header(styles, "PERSONAL INFORMATION"))
    story.append(_kv_table([
        ("Full Name", user.get("name")),
        ("Father's Name", user.get("father_name")),
        ("Date of Birth", user.get("dob")),
        ("Gender", user.get("gender")),
        ("Blood Group", user.get("blood_group")),
        ("Marital Status", user.get("marital_status")),
        ("Mobile", user.get("phone")),
        ("Email", user.get("email")),
        ("Address", user.get("address") or user.get("current_address")),
        ("Permanent Address", user.get("permanent_address")),
        ("Emergency Contact", user.get("emergency_contact_name")),
        ("Emergency Phone", user.get("emergency_contact_phone")),
    ], styles))

    # --- FAMILY DETAILS (Iter 109) ---
    fam = [f for f in (user.get("family_members") or []) if (f or {}).get("name")]
    if fam:
        story.append(_section_header(styles, "FAMILY DETAILS"))
        story.append(_kv_table([
            (f"{(f.get('relation') or 'Member').title()}",
             f"{f.get('name')}{('  ·  DOB: ' + f['dob']) if f.get('dob') else ''}")
            for f in fam
        ], styles))

    # --- EMPLOYMENT ---
    story.append(_section_header(styles, "EMPLOYMENT DETAILS"))
    story.append(_kv_table([
        ("Employee Code", user.get("employee_code")),
        ("Company", company.get("name")),
        ("Role", (user.get("role") or "").replace("_", " ").title()),
        ("Department", user.get("department")),
        ("Designation", user.get("designation") or user.get("position")),
        ("Employee Group", user.get("employee_group") or user.get("employee_type")),
        ("On-Roll", bool(user.get("is_onroll"))),
        ("Date of Joining", user.get("doj") or user.get("join_date")),
        ("Shift Start", user.get("shift_start") or policy.get("shift_name")),
        ("Shift End", user.get("shift_end") or policy.get("shift_dummy")),
        ("Bio-metric Code", user.get("bio_code") or policy.get("bio_code")),
        ("Live-in Staff", bool(user.get("is_live_in"))),
        ("Approval Status", user.get("approval_status")),
        ("Exit Date", user.get("exit_date")),
    ], styles))

    # --- SALARY (from Employee Master) ---
    story.append(_section_header(styles, "SALARY DETAILS"))
    story.append(_kv_table([
        ("Salary Mode", (user.get("salary_mode") or "").title()),
        ("Actual Salary (Monthly)", user.get("salary_monthly")),
        ("Compliance Gross", user.get("compliance_gross")),
        ("Pay Mode", user.get("pay_mode")),
    ], styles))

    # --- KYC ---
    story.append(_section_header(styles, "KYC / IDENTITY"))
    story.append(_kv_table([
        ("Aadhaar (masked)", _mask_aadhar(user.get("aadhar_number") or user.get("aadhaar_no"))),
        ("Name (as per Aadhaar)", user.get("name_as_per_aadhar")),
        ("PAN", user.get("pan_number") or user.get("pan_no")),
        ("Name (as per PAN)", user.get("name_as_per_pan")),
        ("Driving License", user.get("dl_number")),
        ("Passport", user.get("passport_number")),
    ], styles))

    # --- BANK ---
    story.append(_section_header(styles, "BANK DETAILS"))
    story.append(_kv_table([
        ("Bank Name", user.get("bank_name")),
        ("Account Number", user.get("bank_account_number") or user.get("bank_account")),
        ("IFSC Code", user.get("ifsc_code") or user.get("bank_ifsc")),
        ("Name (as per Bank)", user.get("name_as_per_bank")),
        ("UPI ID", user.get("upi_id")),
        ("PF UAN", user.get("uan_number") or user.get("uan_no")),
        ("PF No.", user.get("pf_no")),
        ("ESI IP No.", user.get("esi_ip_no")),
    ], styles))

    # Page break — salary policy + docs + signatures on page 2
    story.append(PageBreak())

    # --- SALARY POLICY ---
    story.append(_section_header(styles, "SALARY & ATTENDANCE POLICY"))
    story.append(_kv_table([
        ("Monthly Salary (₹)", policy.get("salary") or user.get("salary_monthly")),
        ("Tier 1 Bonus (₹)", policy.get("salary_1")),
        ("Tier 1 min Days", policy.get("day_1")),
        ("Tier 2 Bonus (₹)", policy.get("salary_2")),
        ("Tier 2 min Days", policy.get("day_2")),
        ("Tier 3 Bonus (₹)", policy.get("salary_3")),
        ("Tier 3 min Days", policy.get("day_3")),
        ("Working Hours/day", policy.get("working_hours")),
        ("Full Day Hours", policy.get("fullday_hours") or user.get("full_day_hrs")),
        ("Half Day Hours", policy.get("halfday_hours") or user.get("half_day_hrs")),
        ("Casual Leave (CL)", policy.get("cl_days")),
        ("Paid Leave (PL)", policy.get("pl_days")),
        ("Weekly Off Day", _weekday_name(policy.get("weekly_off"))),
        ("Week-off Min Hrs", policy.get("week_off_min_hours")),
        ("Overtime Allowed", policy.get("ot_allow")),
        ("Full Day Pay on Week-off", policy.get("full_day_salary")),
    ], styles))

    # --- DOCUMENTS ON RECORD ---
    story.append(_section_header(styles, "SCAN DOCUMENTS ON RECORD"))
    story.append(Spacer(1, 4))
    story.append(_doc_list_table(styles, documents))

    # --- DECLARATION + SIGNATURES ---
    story.append(Spacer(1, 10))
    story.append(_section_header(styles, "DECLARATION"))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "I hereby declare that the information provided above is true and correct "
        "to the best of my knowledge. I authorise the employer to verify the same "
        "and understand that any misrepresentation may result in disciplinary action "
        "including termination of employment.",
        styles["value"],
    ))
    story.append(Spacer(1, 18))
    story.append(_signature_block(styles))

    doc.build(story)
    return buf.getvalue()


def _weekday_name(idx: Optional[int]) -> str:
    if idx is None:
        return "—"
    try:
        i = int(idx)
    except Exception:
        return str(idx)
    names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    if 0 <= i < 7:
        return names[i]
    return "—"


def build_employees_master_pdf_bulk(
    users_with_context: List[Dict[str, Any]],
) -> bytes:
    """Bulk export — one section per employee, page-break in-between.

    Each item in ``users_with_context`` must be a dict with keys:
    ``user``, ``company``, ``policy``, ``documents``.
    """
    if not users_with_context:
        # Empty PDF with a friendly message
        return build_employee_master_pdf(
            user={"name": "No employees to export"}, company=None, policy=None, documents=[]
        )

    parts: List[bytes] = [
        build_employee_master_pdf(
            u.get("user", {}), u.get("company"), u.get("policy"), u.get("documents"),
        )
        for u in users_with_context
    ]
    # Merge with pypdf if we have >1 doc
    if len(parts) == 1:
        return parts[0]
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        from PyPDF2 import PdfReader, PdfWriter  # type: ignore
    writer = PdfWriter()
    for b in parts:
        reader = PdfReader(io.BytesIO(b))
        for page in reader.pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
