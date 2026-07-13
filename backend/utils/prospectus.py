"""Generate the S.K. Sharma & Co. consultancy prospectus PDF.

Run directly (`python -m backend.utils.prospectus`) to write the artefact to
`/app/deliverables/SKS_Consultancy_Prospectus.pdf` and print its path. Also
exposed as a callable so the FastAPI download route can regenerate on demand.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
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
DELIVERABLES_DIR = Path("/app/deliverables")
DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_OUTPUT = DELIVERABLES_DIR / "SKS_Consultancy_Prospectus.pdf"

# Corporate Deep Teal palette (matches the app)
BRAND = colors.HexColor("#1F4E4E")
BRAND_LIGHT = colors.HexColor("#E6EDED")
ACCENT = colors.HexColor("#C89B3C")
INK = colors.HexColor("#1E2A2A")
INK_SOFT = colors.HexColor("#4C5A5A")
INK_MUTED = colors.HexColor("#7A8686")
LINE = colors.HexColor("#D6DEDE")
BG_SOFT = colors.HexColor("#F7F9F9")
DANGER = colors.HexColor("#B4292A")

# Contact block — locked in from the user's answers
CONSULTANCY_NAME = "S.K. Sharma & Co."
CONSULTANCY_TAGLINE = "Compliance • Payroll • Manpower — Digital Workforce Consultancy"
CONTACT_PERSON = "Ankit Sharma"
CONTACT_PHONE = "+91 96802 73960"
CONTACT_EMAIL = "sksharmaconsultancy@gmail.com"
CONTACT_WEBSITE = "www.esi-pf.com"


# ---------------------------------------------------------------------------
# Fonts — register Latin + Devanagari faces for bilingual EN/HI content.
# ---------------------------------------------------------------------------
_FONTS_REGISTERED = False


def _register_fonts() -> Tuple[str, str, str]:
    """Register the Noto Sans (Latin + Devanagari) fonts once per process.
    Returns (regular_name, bold_name, devanagari_name)."""
    global _FONTS_REGISTERED
    reg = "NotoSans"
    bold = "NotoSans-Bold"
    dev = "NotoSansDeva"
    if not _FONTS_REGISTERED:
        pdfmetrics.registerFont(TTFont(reg, str(FONTS_DIR / "NotoSans-Regular.ttf")))
        # Reuse the italic file as a heavier weight — good enough for headers,
        # avoids downloading a separate bold TTF.
        pdfmetrics.registerFont(TTFont(bold, str(FONTS_DIR / "NotoSans-Bold.ttf")))
        pdfmetrics.registerFont(TTFont(dev, str(FONTS_DIR / "NotoSansDevanagari-Regular.ttf")))
        _FONTS_REGISTERED = True
    return reg, bold, dev


# ---------------------------------------------------------------------------
# Custom flowables
# ---------------------------------------------------------------------------
def _cover_background(canvas, doc):
    """Draw the full-bleed cover background — teal wash + subtle stripe pattern
    + gold accent ribbon at the bottom. Runs before flowables via the Cover
    PageTemplate's onPage hook."""
    W, H = A4
    c = canvas
    c.saveState()
    # Deep teal wash
    c.setFillColor(BRAND)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    # Subtle stripe pattern for depth
    c.setFillColor(BRAND_LIGHT)
    c.setFillAlpha(0.04)
    for i in range(0, int(W), int(6 * mm)):
        c.rect(i, 0, 1.6 * mm, H, stroke=0, fill=1)
    c.setFillAlpha(1)
    # Gold accent ribbon at bottom
    c.setFillColor(ACCENT)
    c.rect(0, 0, W, 14 * mm, stroke=0, fill=1)
    # Small "CONFIDENTIAL" watermark bottom-right on the gold ribbon
    c.setFillColor(colors.HexColor("#2A3E15"))
    c.setFont("NotoSans-Bold", 8)
    c.drawRightString(W - 15 * mm, 4.5 * mm, "CONFIDENTIAL PROSPECTUS")
    c.restoreState()


class Logo(Flowable):
    """Simple SKS monogram — matches the in-app splash aesthetic."""

    def __init__(self, size: float = 26 * mm):
        super().__init__()
        self.size = size
        self.width = size
        self.height = size

    def draw(self):
        c = self.canv
        s = self.size
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.white)
        # Rounded-square badge
        c.roundRect(0, 0, s, s, 6, stroke=0, fill=1)
        # Inner teal ring
        c.setFillColor(BRAND)
        c.roundRect(2.2, 2.2, s - 4.4, s - 4.4, 5, stroke=0, fill=1)
        # SKS text
        c.setFillColor(colors.white)
        c.setFont("NotoSans-Bold", s * 0.32)
        text = "SKS"
        tw = c.stringWidth(text, "NotoSans-Bold", s * 0.32)
        c.drawString((s - tw) / 2, s * 0.42, text)
        # Gold underline (accent)
        c.setStrokeColor(ACCENT)
        c.setLineWidth(1.4)
        c.line(s * 0.28, s * 0.36, s * 0.72, s * 0.36)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def _build_styles() -> dict:
    reg, bold, dev = _register_fonts()
    base = getSampleStyleSheet()
    def _new(name: str, **kw) -> ParagraphStyle:
        s = ParagraphStyle(name, parent=base["Normal"], **kw)
        return s

    return {
        "cover_title": _new(
            "CoverTitle",
            fontName=bold, fontSize=32, leading=38, textColor=colors.white,
            alignment=TA_LEFT, spaceAfter=6,
        ),
        "cover_sub": _new(
            "CoverSub",
            fontName=reg, fontSize=13, leading=18,
            textColor=colors.HexColor("#EFE6C7"), alignment=TA_LEFT,
        ),
        "cover_pill": _new(
            "CoverPill",
            fontName=bold, fontSize=9, leading=11,
            textColor=BRAND, alignment=TA_CENTER,
        ),
        "cover_contact": _new(
            "CoverContact",
            fontName=reg, fontSize=10.5, leading=15, textColor=colors.white, alignment=TA_LEFT,
        ),
        "cover_footer": _new(
            "CoverFooter",
            fontName=reg, fontSize=9, leading=12,
            textColor=colors.HexColor("#B7C7C7"), alignment=TA_CENTER,
        ),
        "h1": _new(
            "H1", fontName=bold, fontSize=22, leading=28, textColor=BRAND,
            spaceAfter=4, spaceBefore=2,
        ),
        "h1_kicker": _new(
            "H1Kicker", fontName=bold, fontSize=9, leading=12, textColor=ACCENT,
            spaceAfter=2,
        ),
        "h2": _new(
            "H2", fontName=bold, fontSize=13.5, leading=18, textColor=BRAND,
            spaceBefore=10, spaceAfter=4,
        ),
        "h3": _new(
            "H3", fontName=bold, fontSize=11, leading=15, textColor=INK,
            spaceBefore=6, spaceAfter=2,
        ),
        "body": _new(
            "Body", fontName=reg, fontSize=10, leading=15, textColor=INK_SOFT,
            alignment=TA_JUSTIFY, spaceAfter=4,
        ),
        "body_left": _new(
            "BodyLeft", fontName=reg, fontSize=10, leading=15, textColor=INK_SOFT,
            spaceAfter=4,
        ),
        "hindi": _new(
            "Hindi", fontName=dev, fontSize=10.5, leading=17,
            textColor=INK_SOFT, alignment=TA_JUSTIFY, spaceAfter=6,
        ),
        "bullet": _new(
            "Bullet", fontName=reg, fontSize=10, leading=15, textColor=INK_SOFT,
            leftIndent=14, bulletIndent=2, spaceAfter=2,
        ),
        "caption": _new(
            "Caption", fontName=reg, fontSize=8.5, leading=11, textColor=INK_MUTED,
            spaceAfter=2, alignment=TA_LEFT,
        ),
        "callout_title": _new(
            "CalloutTitle", fontName=bold, fontSize=11, leading=14, textColor=BRAND,
            spaceAfter=2,
        ),
        "callout_body": _new(
            "CalloutBody", fontName=reg, fontSize=9.5, leading=13, textColor=INK,
        ),
        "small_muted": _new(
            "SmallMuted", fontName=reg, fontSize=8.5, leading=11, textColor=INK_MUTED,
            alignment=TA_CENTER,
        ),
        "footer": _new(
            "Footer", fontName=reg, fontSize=8, leading=10, textColor=INK_MUTED,
            alignment=TA_LEFT,
        ),
        "footer_r": _new(
            "FooterR", fontName=reg, fontSize=8, leading=10, textColor=INK_MUTED,
            alignment=TA_RIGHT,
        ),
    }


# ---------------------------------------------------------------------------
# Page decorations
# ---------------------------------------------------------------------------
def _page_frame(canvas, doc, styles: dict, is_cover: bool = False):
    """Draws top brand strip + page number footer on every non-cover page."""
    canvas.saveState()
    W, H = A4
    if is_cover:
        canvas.restoreState()
        return
    # Top brand strip
    canvas.setFillColor(BRAND)
    canvas.rect(0, H - 12 * mm, W, 12 * mm, stroke=0, fill=1)
    canvas.setFillColor(ACCENT)
    canvas.rect(0, H - 13.5 * mm, W, 1.5 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("NotoSans-Bold", 9)
    canvas.drawString(15 * mm, H - 8 * mm, CONSULTANCY_NAME.upper())
    canvas.setFont("NotoSans", 8.5)
    canvas.setFillColor(colors.HexColor("#EFE6C7"))
    canvas.drawRightString(W - 15 * mm, H - 8 * mm, "Digital Workforce Consultancy")
    # Bottom footer
    canvas.setFillColor(INK_MUTED)
    canvas.setFont("NotoSans", 8)
    canvas.drawString(15 * mm, 10 * mm, f"{CONSULTANCY_NAME} • Confidential Prospectus")
    canvas.drawRightString(W - 15 * mm, 10 * mm, f"Page {canvas.getPageNumber()}")
    # Divider above footer
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.4)
    canvas.line(15 * mm, 13 * mm, W - 15 * mm, 13 * mm)
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Content builders — one function per page/section for readability.
# ---------------------------------------------------------------------------
def _bullet_list(items: List[str], style: ParagraphStyle) -> List:
    story = []
    for it in items:
        story.append(Paragraph(f"•&nbsp;&nbsp;{it}", style))
    return story


def _feature_table(rows: List[Tuple[str, str]], styles: dict) -> Table:
    data = [[Paragraph(f"<b>{k}</b>", styles["h3"]), Paragraph(v, styles["body_left"])] for k, v in rows]
    t = Table(data, colWidths=[52 * mm, None], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ("BACKGROUND", (0, 0), (0, -1), BG_SOFT),
    ]))
    return t


def _kv_table(rows: List[Tuple[str, str]], styles: dict) -> Table:
    data = [[Paragraph(f"<b>{k}</b>", styles["body_left"]), Paragraph(v, styles["body_left"])] for k, v in rows]
    t = Table(data, colWidths=[46 * mm, None], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, LINE),
    ]))
    return t


def _callout(title: str, body: str, styles: dict) -> Table:
    inner = [
        [Paragraph(title, styles["callout_title"])],
        [Paragraph(body, styles["callout_body"])],
    ]
    t = Table(inner, colWidths=[None])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.6, BRAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _section_header(kicker: str, title: str, styles: dict) -> List:
    return [
        Paragraph(kicker.upper(), styles["h1_kicker"]),
        Paragraph(title, styles["h1"]),
        HRFlowable(width="18%", color=ACCENT, thickness=2, spaceAfter=8, spaceBefore=2),
    ]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
def _build_cover(styles: dict, W: float, H: float) -> List:
    """Cover content — the background is drawn by _cover_background via the
    Cover PageTemplate's onPage hook, so this function only supplies flowables."""
    logo = Logo(size=28 * mm)
    contact_lines = (
        f"<b>{CONTACT_PERSON}</b><br/>"
        f"{CONTACT_PHONE}<br/>"
        f"{CONTACT_EMAIL}<br/>"
        f"{CONTACT_WEBSITE}"
    )
    story: List = [
        Spacer(1, 10 * mm),
        logo,
        Spacer(1, 12 * mm),
        Paragraph(
            "<font color='#EFE6C7'>PROJECT PROSPECTUS · " + datetime.now().strftime("%B %Y") + "</font>",
            styles["cover_sub"],
        ),
        Paragraph(CONSULTANCY_NAME, styles["cover_title"]),
        Paragraph(CONSULTANCY_TAGLINE, styles["cover_sub"]),
        Spacer(1, 10 * mm),
        Paragraph(
            "One workplace app for <b>geo-fenced biometric attendance</b>, "
            "<b>multi-shift payroll</b>, <b>labour-law compliance</b>, "
            "and <b>ticketing</b> — offered as a managed consultancy engagement.",
            ParagraphStyle(
                "herohook",
                parent=styles["cover_sub"],
                fontSize=12.5,
                leading=18,
                textColor=colors.white,
            ),
        ),
        Spacer(1, 22 * mm),
        Paragraph("<font color='#EFE6C7'>OFFERED BY</font>", styles["cover_sub"]),
        Paragraph(contact_lines, styles["cover_contact"]),
    ]
    return story


def _build_executive_summary(styles: dict) -> List:
    story: List = []
    story += _section_header("01 · Introduction", "Executive Summary", styles)
    story.append(Paragraph(
        f"<b>{CONSULTANCY_NAME}</b> offers a unified digital workforce platform for Indian "
        f"businesses of every scale — from a 12-bed nursing home and a 40-room resort "
        f"to a 300-worker textile unit and a multi-branch education group. The platform "
        f"replaces paper registers, disconnected biometric readers and manual salary sheets "
        f"with a <b>single mobile-first application</b> that is deployed and managed by us "
        f"on a consultancy basis.",
        styles["body"],
    ))
    story.append(Paragraph(
        "Every module — attendance, leave, payroll, compliance filings, tickets, in-app "
        "messaging — is designed to match the way Indian firms actually operate: shift "
        "rotations, weekly-off holidays, factory overtime, resort live-in employees, "
        "school teaching hours and monthly compliance filings. Firms adopt what they "
        "need, tuned to their business type.",
        styles["body"],
    ))

    # Hindi mirror paragraph
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "<b>संक्षिप्त परिचय:</b> एस.के. शर्मा एंड कंपनी द्वारा प्रस्तुत यह वर्कफोर्स "
        "प्लेटफ़ॉर्म भारतीय व्यवसायों के लिए तैयार किया गया है — अस्पताल, होटल/रिज़ॉर्ट, "
        "उद्योग, स्कूल, आईटी कंपनी, कंस्ट्रक्शन साइट और सर्विस प्रोवाइडर सभी के लिए। "
        "एक ही मोबाइल ऐप में जियो-फेंस बायोमेट्रिक हाजिरी, बहु-शिफ्ट पेरोल, श्रम कानून "
        "अनुपालन और शिकायत टिकट प्रबंधन उपलब्ध है। संपूर्ण सेटअप और रखरखाव हमारी "
        "कंसल्टेंसी टीम द्वारा किया जाता है।",
        styles["hindi"],
    ))
    story.append(Spacer(1, 6))
    story.append(_callout(
        "Why a consultancy engagement, not a SaaS subscription?",
        "We do the heavy lifting so your HR / admin team doesn't have to — geofence setup, "
        "biometric enrolment, shift design, compliance filing calendars, monthly payroll "
        "runs and periodic audits. You get outcomes, not just software.",
        styles,
    ))

    # Impact snapshot
    story.append(Spacer(1, 10))
    story.append(Paragraph("At a glance", styles["h2"]))
    story.append(_kv_table([
        ("Deployment window", "Live within 7 – 14 working days per site"),
        ("Employee onboarding", "Self-serve with OCR ID parsing (~90 seconds / worker)"),
        ("Biometric method", "Live camera face-match (Gemini 3 Flash) + geofence"),
        ("Business types tuned", "9 categories with 25+ industry sub-types"),
        ("Attendance rules", "Presets per business type, admin-editable"),
        ("Payslip delivery", "Email (Resend) + in-app PDF download"),
        ("Data ownership", "Client-owned MongoDB — full export any time"),
    ], styles))
    return story


def _build_product_overview(styles: dict) -> List:
    story: List = []
    story += _section_header("02 · Product", "What the App Does", styles)
    story.append(Paragraph(
        "The platform is offered as an <b>Android + iOS mobile application</b> with a "
        "companion web console for admins. It runs on the employee's own phone using "
        "the device camera and GPS — no dedicated hardware is required at most sites.",
        styles["body"],
    ))
    story.append(Paragraph(
        "यह ऐप कर्मचारी के अपने मोबाइल पर चलता है — कैमरा और जीपीएस के माध्यम से बायोमेट्रिक "
        "एवं जियो-फेंस्ड हाजिरी दर्ज होती है। किसी अतिरिक्त हार्डवेयर की आवश्यकता नहीं है।",
        styles["hindi"],
    ))
    story.append(Spacer(1, 4))
    story.append(_feature_table([
        ("Geo-fenced attendance",
         "Employees punch in / out only when inside a configurable office radius. Auto-punch "
         "triggers on entering / leaving the site, so field staff don't have to remember."),
        ("Face-match biometric",
         "Every punch captures a selfie which is compared to the employee's enrolled photo using "
         "Gemini 3 Flash. Mismatches are flagged for admin review."),
        ("Multiple in/out per day",
         "Realistic for shift workers, resort staff and site engineers — every entry/exit is "
         "logged as a separate session and shown on a timeline."),
        ("Multi-shift & policy tuning",
         "Firms pick a business-type preset (Hospital, Hotel/Resort, Industry, School, IT, "
         "Construction, Automobile, Service, Other). Shifts, weekly-off, overtime and grace "
         "period are all editable."),
        ("Approval workflow",
         "Every auto-punch can be sent to the admin queue for Approve, Reject (mandatory "
         "reason) or Adjust (mandatory manual time). Manual punches skip the queue."),
        ("Live-in / resort staff bypass",
         "Employees flagged as 'live-in' are exempt from the geofence and are marked present "
         "via a daily roster screen — perfect for hotel and hospital staff quarters."),
        ("Leave & approvals",
         "Employees apply from the app; company admin approves; super admin sees a firm-wide "
         "queue. Balance and history stay in sync."),
        ("Payroll & payslips",
         "Monthly salary generation with earnings / deductions / statutory heads. Payslips are "
         "e-mailed via Resend and downloadable in-app."),
        ("Compliance documents",
         "Central vault for PF, ESI, PT, LWF, Shops & Establishment and Factories Act filings "
         "with expiry reminders."),
        ("Tickets & messaging",
         "Employees raise issues (PF query, salary correction, harassment, etc.) with PDF or "
         "photo attachments. Admins broadcast announcements via in-app messages."),
        ("Reports & exports",
         "Attendance registers, salary summaries, muster rolls, statutory returns — all "
         "exportable to XLSX / PDF."),
    ], styles))
    return story


def _build_business_types(styles: dict) -> List:
    story: List = []
    story += _section_header("03 · Firm Master", "Business Types Supported", styles)
    story.append(Paragraph(
        "During onboarding the client picks a business type from a curated dropdown. "
        "This choice pre-loads an attendance policy tuned to that industry (shifts, "
        "weekly-off, overtime thresholds, night allowance, break hours). The company "
        "admin can then override any field on the Attendance Policy screen.",
        styles["body"],
    ))
    story.append(Paragraph(
        "फर्म मास्टर में व्यवसाय का प्रकार चुनते ही उस उद्योग के अनुरूप हाजिरी नीति स्वतः लागू "
        "हो जाती है, जिसे बाद में एडमिन अपनी आवश्यकता अनुसार बदल सकते हैं।",
        styles["hindi"],
    ))
    story.append(Spacer(1, 4))

    biz_rows = [
        ("Hospital",
         "24×7 rotational — 3 shifts, no fixed weekly off, night allowance ON, OT after 8 h @ 1.5×."),
        ("Hotel / Resort",
         "3 rotational shifts, one compensatory weekly-off, night allowance ON. Live-in bypass "
         "supported for staff-quarters employees."),
        ("Industry (Textile · Food · Polybag · Engineering · Chemical · Pharma · Steel · Cement · "
         "Electronics · Paper · Leather · Rubber · Furniture · Fertilizer · Gems · Printing · "
         "Ceramics · Glass · Agro · Mining · Oil & Gas · Marine · Handicrafts + more)",
         "3 shifts (A / B / C), Sunday weekly-off, 1 hour unpaid lunch, OT after 8 h @ 2× "
         "(Factories-Act aligned)."),
        ("Service Provider",
         "Single 9:30 – 18:30 general shift, Sunday off, OT after 9 h @ 1.5×."),
        ("IT Company",
         "10:00 – 19:00 general shift, Saturday + Sunday off, generous 30-minute late grace, OT "
         "recorded only when explicitly approved."),
        ("Construction",
         "Site shift 08:00 – 17:00, rotational weekly-off, OT after 8 h @ 2×."),
        ("School / Education",
         "08:00 – 14:30 teaching hours, Sunday off, no OT (fixed pay). Extra classes tracked "
         "separately as ticket-based claims."),
        ("Automobile Workshop / Dealership",
         "09:00 – 18:00, Sunday off, OT after 8 h @ 1.5×."),
        ("Other",
         "Generic 09:00 – 18:00, Sunday off, OT after 9 h @ 1.5× — fully editable."),
    ]
    story.append(_feature_table(biz_rows, styles))

    story.append(Spacer(1, 8))
    story.append(_callout(
        "Adding a category or sub-type is a 30-minute change",
        "The taxonomy lives server-side and is version-controlled. If your industry isn't listed "
        "we add it — no app update required.",
        styles,
    ))
    return story


def _build_policy_deep_dive(styles: dict) -> List:
    story: List = []
    story += _section_header("04 · Rules Engine", "Attendance Policy Framework", styles)
    story.append(Paragraph(
        "Every firm's attendance rules are captured as a single policy document editable "
        "from the app. The following knobs are available on every business-type preset — "
        "reload the preset any time to start over, or tweak individual fields.",
        styles["body"],
    ))
    story.append(_feature_table([
        ("Shifts (name + start + end)", "Multiple shifts per firm; overnight shifts calculated correctly."),
        ("Weekly off days", "Multi-select — pick zero, one or multiple days per week."),
        ("Grace minutes for late-in", "0 – 120 minutes. Late marks are auto-tagged beyond this."),
        ("Half-day threshold", "Hours below this count as half-day (typical 4 h)."),
        ("Full-day threshold", "Hours at or above this count as full-day (typical 8 h)."),
        ("Break hours (unpaid)", "Deducted from worked hours in reports."),
        ("Overtime threshold", "Hours after which OT starts (typically 8 or 9)."),
        ("Overtime multiplier", "1.0×, 1.5×, 2.0× or a custom decimal."),
        ("Night-shift allowance", "Toggle + configurable window (e.g. 22:00 – 06:00)."),
        ("Punch approval required", "Optional gate — every auto punch waits for admin action."),
    ], styles))
    story.append(Spacer(1, 6))
    story.append(_callout(
        "Approval workflow · Approve / Reject / Adjust",
        "Auto punches created outside the geofence, at odd hours, or by a face that does not "
        "match the enrolled selfie are queued for admin review. The admin can Approve, Reject "
        "with a mandatory reason, or Adjust — entering the corrected wall-clock time (mandatory). "
        "Rejected and pending punches are excluded from working-hours math automatically.",
        styles,
    ))
    return story


def _build_roles(styles: dict) -> List:
    story: List = []
    story += _section_header("05 · Personas", "Who Uses the App", styles)
    story.append(Paragraph("Employee", styles["h2"]))
    story += _bullet_list([
        "PIN or Company-code sign-in in under 15 seconds.",
        "Auto and manual punch with selfie + geofence check.",
        "View own attendance calendar, payslips, tickets and messages.",
        "Apply leave, upload compliance IDs, edit personal profile (with admin approval).",
    ], styles["bullet"])
    story.append(Paragraph("Company Admin", styles["h2"]))
    story += _bullet_list([
        "Employee onboarding with OCR ID parsing (Aadhaar, PAN, driving licence).",
        "Approve leaves, tickets, profile edits and pending punches.",
        "Set / override attendance policy, manage branches and geofence radius.",
        "Generate payroll runs and email payslips (Resend integration).",
        "Broadcast in-app messages and view firm-wide dashboards.",
    ], styles["bullet"])
    story.append(Paragraph("Super Admin (S.K. Sharma & Co.)", styles["h2"]))
    story += _bullet_list([
        "Manage client firms — create, edit, off-board, set business type.",
        "Cross-firm dashboards: employees, present-today, pending approvals, open tickets.",
        "Compliance monitoring across all client firms.",
        "Audit trail of every attendance decision (approve / reject / adjust).",
    ], styles["bullet"])
    return story


def _build_tech_security(styles: dict) -> List:
    story: List = []
    story += _section_header("06 · Under the Hood", "Technology & Security", styles)
    story.append(_feature_table([
        ("Mobile app",
         "Expo React Native — installable via Play Store, App Store or in-house link. Works on "
         "Android 8+ and iOS 14+."),
        ("Backend",
         "Python 3.11 + FastAPI, containerised, deployed on Kubernetes with automatic restarts."),
        ("Database",
         "MongoDB with encrypted-at-rest storage. Full daily backups; on request the entire "
         "dataset is exportable to the client's own MongoDB cluster."),
        ("AI / OCR",
         "Google Gemini 3 Flash — OCR for ID cards and face-match at punch time. No customer "
         "biometric data leaves our stack; only ephemeral base64 selfies are processed."),
        ("Payslip email",
         "Resend transactional email — DKIM signed, delivered from a domain of your choice."),
        ("Authentication",
         "Employee PIN (bcrypt-hashed) + optional biometric device lock. Company Admin gets a "
         "temporary PIN on provisioning that must be changed on first login."),
        ("Session & network",
         "All API calls over HTTPS (TLS 1.3), JWT tokens with 24-hour expiry, refresh via re-login."),
        ("Audit trail",
         "Every attendance decision, profile edit, leave action and payroll change is stored "
         "immutably with the actor's user ID and timestamp."),
        ("Compliance",
         "Aligns with Indian IT Act, Payment of Wages Act 1936, Factories Act 1948, Shops & "
         "Establishments Act (state-specific), PF Act 1952, ESI Act 1948."),
    ], styles))
    return story


def _build_engagement(styles: dict) -> List:
    story: List = []
    story += _section_header("07 · Delivery", "Engagement Timeline", styles)
    story.append(Paragraph(
        "A typical rollout follows the milestones below. For a firm with fewer than 100 "
        "employees and one location, everything from kick-off to first monthly payslip "
        "run happens within 14 working days.",
        styles["body"],
    ))
    tl_rows = [
        ("Day 1 – 2 · Kick-off",
         "Discovery workshop, business-type selection, shift design, geofence marking, "
         "compliance document collection."),
        ("Day 3 – 5 · Provisioning",
         "Client firm created in the console with the recommended attendance-policy preset; "
         "branches and geofences configured; admin credentials issued."),
        ("Day 5 – 8 · Employee onboarding",
         "Bulk import via Excel or self-serve via OCR (Aadhaar / PAN scan). Face enrolment "
         "captured live. Company code shared with employees."),
        ("Day 8 – 10 · Pilot run",
         "First 3 days of live attendance, punch approvals reviewed together, calibration of "
         "grace period and OT thresholds."),
        ("Day 10 – 14 · Payroll & compliance",
         "First payroll run generated and mailed. Compliance document tracker populated. "
         "Handover checklist signed."),
        ("Month 2 onwards · Managed operations",
         "Monthly payroll run, statutory filings tracker, audit reports, quarterly review call."),
    ]
    story.append(_feature_table(tl_rows, styles))
    story.append(Spacer(1, 6))
    story.append(_callout(
        "Support model",
        "During business hours (10:00 – 19:00 IST, Mon – Sat) we respond within 2 hours on "
        "WhatsApp and 4 hours on email. Critical outages are attended within 30 minutes.",
        styles,
    ))
    return story


def _build_consultancy_model(styles: dict) -> List:
    story: List = []
    story += _section_header("08 · Engagement", "Consultancy Model", styles)
    story.append(Paragraph(
        "We work as your outsourced digital HR partner — not as a shrink-wrapped SaaS "
        "vendor. Every plan bundles the software, the setup effort and the ongoing "
        "operational touch-points that most Indian firms actually need.",
        styles["body"],
    ))
    story.append(_feature_table([
        ("Setup",
         "Discovery workshop, geofence marking, attendance-policy tuning, biometric enrolment "
         "for the entire workforce, admin & employee training."),
        ("Managed operations",
         "Monthly payroll run, payslip dispatch, compliance filing calendar, punch approval "
         "sweeps twice a week, quarterly review meeting."),
        ("Support",
         "Named account manager, WhatsApp + email + phone support with defined response SLAs."),
        ("Upgrades",
         "All new features (like ZKTeco physical biometric integration, expense reimbursement, "
         "SQL sync) are shipped free during the engagement."),
        ("Investment",
         "Fee is finalised on the table basis firm size, number of branches and complexity of "
         "compliance filings. Please write in and we will share a right-sized proposal."),
    ], styles))
    story.append(Spacer(1, 6))
    story.append(_callout(
        "Commercials will be discussed on the table",
        "We do not publish list prices — every proposal is scoped to your headcount, sites and "
        "compliance needs so that you pay only for what you use. Contact us for a free 30-minute "
        "discovery call.",
        styles,
    ))
    return story


def _build_contact(styles: dict) -> List:
    story: List = []
    story += _section_header("09 · Next Step", "Let's Talk", styles)
    story.append(Paragraph(
        "The fastest way to see this platform in action is a 30-minute live demo on your "
        "phone. We can walk your team through the exact modules that matter for your "
        "industry, and share sample reports the same day.",
        styles["body"],
    ))
    story.append(Paragraph(
        "एक 30 मिनट के डेमो के लिए हमसे संपर्क करें — हम आपकी टीम को आपके उद्योग के "
        "अनुरूप मॉड्यूल दिखाएंगे और उसी दिन नमूना रिपोर्ट साझा करेंगे।",
        styles["hindi"],
    ))
    story.append(Spacer(1, 8))
    story.append(_feature_table([
        ("Point of contact", f"<b>{CONTACT_PERSON}</b>"),
        ("Phone / WhatsApp", f"<a href='tel:{CONTACT_PHONE}'>{CONTACT_PHONE}</a>"),
        ("Email", f"<a href='mailto:{CONTACT_EMAIL}'>{CONTACT_EMAIL}</a>"),
        ("Website", f"<a href='https://{CONTACT_WEBSITE}'>{CONTACT_WEBSITE}</a>"),
        ("Consultancy", f"{CONSULTANCY_NAME}"),
    ], styles))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", color=LINE, thickness=0.4))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"<font color='{INK_MUTED.hexval()}'>This prospectus is confidential and intended "
        f"solely for the addressee. © {datetime.now().year} {CONSULTANCY_NAME}. "
        f"All product marks are the property of their respective owners.</font>",
        styles["small_muted"],
    ))
    return story


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def generate_prospectus(output_path: os.PathLike | None = None) -> Path:
    """Render the full prospectus to `output_path` (defaults to
    /app/deliverables/SKS_Consultancy_Prospectus.pdf) and return the path.
    """
    output_path = Path(output_path) if output_path else DEFAULT_OUTPUT
    styles = _build_styles()
    W, H = A4

    # BaseDocTemplate lets us use different frames per page (cover has no margin).
    doc = BaseDocTemplate(
        str(output_path),
        pagesize=A4,
        title=f"{CONSULTANCY_NAME} — Project Prospectus",
        author=CONSULTANCY_NAME,
        subject="Digital Workforce Consultancy Prospectus",
        creator=CONSULTANCY_NAME,
    )
    cover_frame = Frame(
        15 * mm, 15 * mm, W - 30 * mm, H - 30 * mm,
        leftPadding=6 * mm, rightPadding=6 * mm,
        topPadding=6 * mm, bottomPadding=6 * mm,
        id="cover",
    )
    content_frame = Frame(
        15 * mm, 15 * mm, W - 30 * mm, H - 30 * mm,
        leftPadding=0, rightPadding=0, topPadding=6 * mm, bottomPadding=8 * mm,
        id="content",
    )
    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[cover_frame],
                     onPage=_cover_background),
        PageTemplate(id="Content", frames=[content_frame],
                     onPage=lambda c, d: _page_frame(c, d, styles, is_cover=False)),
    ])

    story: List = []
    story += _build_cover(styles, W, H)

    # Switch template
    from reportlab.platypus.doctemplate import NextPageTemplate
    story.append(NextPageTemplate("Content"))
    story.append(PageBreak())

    # Content sections — each is a self-contained set of flowables; PageBreak
    # separates them so headings never orphan at the bottom.
    for section in (
        _build_executive_summary(styles),
        _build_product_overview(styles),
        _build_business_types(styles),
        _build_policy_deep_dive(styles),
        _build_roles(styles),
        _build_tech_security(styles),
        _build_engagement(styles),
        _build_consultancy_model(styles),
        _build_contact(styles),
    ):
        story.append(KeepTogether([]))  # noop-guard
        for f in section:
            story.append(f)
        story.append(PageBreak())

    doc.build(story)
    return output_path


if __name__ == "__main__":  # pragma: no cover
    path = generate_prospectus()
    print(f"Prospectus written to: {path}")
