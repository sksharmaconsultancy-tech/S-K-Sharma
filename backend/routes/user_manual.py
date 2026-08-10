"""Iter 530/531 (user request) — QUICK USER MANUAL PDF (super admin ONLY).

Modern SaaS-style short user manual (~22 pages) generated with REAL portal
screenshots stored in /app/backend/assets/manual/*.png.

AUTO-UPDATE (Iter 531): the manual is rebuilt LIVE on every download —
  * software version + last-updated date come from the running server
    (APP_ITERATION), never hard-coded;
  * a "What's New" page is generated from the ``manual_updates``
    collection (new payroll features are logged there);
  * extra feature sections can be added via the ``manual_sections``
    collection without touching this file;
  * POST /api/admin/user-manual/refresh-screenshots re-captures every
    screenshot from the CURRENT portal UI (playwright, background job);
  * GET  /api/admin/user-manual/status reports capture freshness.

GET /api/admin/user-manual.pdf   → 403 for anyone except super_admin.
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime
from io import BytesIO
from typing import List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import Response

from server import APP_ITERATION, db, get_user_from_token, require_role  # noqa: E402

from reportlab.lib import colors as rl
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, Image, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

router = APIRouter(prefix="/api/admin", tags=["user-manual"])

ASSETS = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                      "assets", "manual")
NAVY = rl.HexColor("#0F3B5C")
TEAL = rl.HexColor("#0E7490")
TEAL_BG = rl.HexColor("#E0F2FE")
AMBER_BG = rl.HexColor("#FEF3C7")
GREY = rl.HexColor("#64748B")

W, H = A4
CW = W - 30 * mm  # content width

# ---------------------------------------------------------------- styles
S_H1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15,
                      leading=19, textColor=NAVY, spaceBefore=6,
                      spaceAfter=2)
S_NAV = ParagraphStyle("nav", fontName="Helvetica-Oblique", fontSize=9,
                       leading=12, textColor=TEAL, spaceAfter=6)
S_BODY = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5,
                        leading=13.5, textColor=rl.HexColor("#1E293B"))
S_STEP = ParagraphStyle("st", parent=S_BODY, leftIndent=14, spaceAfter=1.5)
S_CALL = ParagraphStyle("cl", fontName="Helvetica-Bold", fontSize=8.5,
                        leading=11, textColor=rl.white)
S_NOTE = ParagraphStyle("nt", parent=S_BODY, fontSize=9, leading=12.5)
S_TOC = ParagraphStyle("toc", fontName="Helvetica", fontSize=10.5,
                       leading=17, textColor=rl.HexColor("#1E293B"))


class _Doc(BaseDocTemplate):
    """BaseDocTemplate that feeds section headings into the TOC."""

    def afterFlowable(self, fl):
        if isinstance(fl, Paragraph) and fl.style.name == "h1":
            self.notify("TOCEntry", (0, fl.getPlainText(), self.page))


def _img(name: str, max_h: float = 96 * mm):
    path = os.path.join(ASSETS, f"{name}.png")
    if not os.path.exists(path):
        t = Table([[Paragraph(
            "[SCREENSHOT REQUIRED — INSERT ACTUAL SOFTWARE SCREENSHOT]",
            ParagraphStyle("ph", fontName="Helvetica-Bold", fontSize=10,
                           textColor=GREY, alignment=1))]],
            colWidths=[CW], rowHeights=[40 * mm])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, GREY),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, -1), rl.HexColor("#F1F5F9"))]))
        return t
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(path).getSize()
    w = CW
    h = w * ih / iw
    if h > max_h:
        h = max_h
        w = h * iw / ih
    img = Image(path, width=w, height=h)
    frame = Table([[img]], colWidths=[w + 2])
    frame.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.2, NAVY),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    wrap = Table([[frame]], colWidths=[CW])
    wrap.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    return wrap


def _callouts(items: List[str]):
    cells, wds = [], []
    for i, txt in enumerate(items, 1):
        cells.append(Paragraph(f"{i}", ParagraphStyle(
            "n", fontName="Helvetica-Bold", fontSize=8.5, textColor=rl.white,
            alignment=1)))
        cells.append(Paragraph(txt, ParagraphStyle(
            "t", fontName="Helvetica", fontSize=8.5, leading=10.5,
            textColor=NAVY)))
        wds += [6 * mm, (CW - 6 * mm * len(items)) / len(items)]
    t = Table([cells], colWidths=wds)
    style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 2),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    for i in range(len(items)):
        style.append(("BACKGROUND", (i * 2, 0), (i * 2, 0), TEAL))
        style.append(("ROUNDEDCORNERS", [4]))
    t.setStyle(TableStyle(style))
    return t


def _note(text: str, warn: bool = False):
    t = Table([[Paragraph(("⚠ " if warn else "ℹ ") if False else
                          ("IMPORTANT — " if warn else "NOTE — ") + text,
                          S_NOTE)]], colWidths=[CW])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), AMBER_BG if warn else TEAL_BG),
        ("LINEBEFORE", (0, 0), (0, -1), 3,
         rl.HexColor("#D97706") if warn else TEAL),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _steps(steps: List[str]):
    out = []
    for i, s in enumerate(steps, 1):
        out.append(Paragraph(
            f"<font color='#0E7490'><b>Step {i}:</b></font> {s}", S_STEP))
    return out


def _section(story, no, title, nav, shot, callouts, steps, note=None,
             warn=False, body=None, img_h=96 * mm):
    story.append(Paragraph(f"{no}. {title}", S_H1))
    if nav:
        story.append(Paragraph(f"Navigation: {nav}", S_NAV))
    if body:
        story.append(Paragraph(body, S_BODY))
        story.append(Spacer(1, 3))
    story.append(_img(shot, img_h) if shot else Spacer(1, 0))
    story.append(Spacer(1, 4))
    if callouts:
        story.append(_callouts(callouts))
        story.append(Spacer(1, 4))
    story.extend(_steps(steps))
    if note:
        story.append(Spacer(1, 4))
        story.append(_note(note, warn))
    story.append(PageBreak())


def _shot_meta() -> dict:
    try:
        with open(os.path.join(ASSETS, ".last_capture.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _cover(cv, doc):
    cv.saveState()
    cv.setFillColor(NAVY)
    cv.rect(0, 0, W, H, fill=1, stroke=0)
    cv.setFillColor(TEAL)
    cv.rect(0, H - 58 * mm, W, 16 * mm, fill=1, stroke=0)
    cv.setFillColor(rl.HexColor("#155E75"))
    cv.circle(W - 18 * mm, 24 * mm, 34 * mm, fill=1, stroke=0)
    cv.setFillColor(TEAL)
    cv.circle(W - 34 * mm, 12 * mm, 20 * mm, fill=1, stroke=0)
    cv.setFillColor(rl.white)
    cv.setFont("Helvetica-Bold", 26)
    cv.drawString(20 * mm, H - 90 * mm, "PAYROLL & COMPLIANCE")
    cv.drawString(20 * mm, H - 101 * mm, "MANAGEMENT SOFTWARE")
    cv.setFillColor(rl.HexColor("#7DD3FC"))
    cv.setFont("Helvetica-Bold", 17)
    cv.drawString(20 * mm, H - 118 * mm, "QUICK USER MANUAL")
    cv.setFillColor(rl.HexColor("#CBD5E1"))
    cv.setFont("Helvetica", 11.5)
    cv.drawString(20 * mm, H - 128 * mm,
                  "Quick Guide for HR, Payroll & Compliance Users")
    cv.setFont("Helvetica-Bold", 13)
    cv.setFillColor(rl.white)
    cv.drawString(20 * mm, H - 50 * mm, "S.K. SHARMA & CO.")
    cv.setFont("Helvetica", 9)
    cv.drawString(20 * mm, H - 55 * mm,
                  "Compliance · Payroll · Manpower")
    cv.setFont("Helvetica", 10)
    y = 62 * mm
    for line in (
            "Product By       :  S.K. Sharma & Co. Payroll & Compliance Portal",
            f"Software Version :  Server Iter {APP_ITERATION}",
            "Prepared By      :  Ankit Sharma"):
        cv.drawString(20 * mm, y, line)
        y -= 6.5 * mm
    cv.setFont("Helvetica-BoldOblique", 10.5)
    cv.setFillColor(rl.HexColor("#7DD3FC"))
    cv.drawString(20 * mm, 18 * mm,
                  '"Your Satisfaction is our First Ambition"')
    cv.restoreState()


def _cover_emp(cv, doc):
    cv.saveState()
    cv.setFillColor(TEAL)
    cv.rect(0, 0, W, H, fill=1, stroke=0)
    cv.setFillColor(NAVY)
    cv.rect(0, H - 58 * mm, W, 16 * mm, fill=1, stroke=0)
    cv.setFillColor(rl.HexColor("#155E75"))
    cv.circle(W - 18 * mm, 24 * mm, 34 * mm, fill=1, stroke=0)
    cv.setFillColor(NAVY)
    cv.circle(W - 34 * mm, 12 * mm, 20 * mm, fill=1, stroke=0)
    cv.setFillColor(rl.white)
    cv.setFont("Helvetica-Bold", 26)
    cv.drawString(20 * mm, H - 90 * mm, "EMPLOYEE")
    cv.drawString(20 * mm, H - 101 * mm, "QUICK GUIDE")
    cv.setFillColor(rl.HexColor("#BAE6FD"))
    cv.setFont("Helvetica-Bold", 15)
    cv.drawString(20 * mm, H - 116 * mm,
                  "Punch In · Attendance · Leave · Payslip")
    cv.setFillColor(rl.HexColor("#E0F2FE"))
    cv.setFont("Helvetica", 11.5)
    cv.drawString(20 * mm, H - 126 * mm,
                  "Everything you need — right on your phone")
    cv.setFont("Helvetica-Bold", 13)
    cv.setFillColor(rl.white)
    cv.drawString(20 * mm, H - 50 * mm, "S.K. SHARMA & CO.")
    cv.setFont("Helvetica", 9)
    cv.drawString(20 * mm, H - 55 * mm, "Compliance · Payroll · Manpower")
    cv.setFont("Helvetica", 10)
    y = 62 * mm
    for line in (
            "Product By       :  S.K. Sharma & Co.",
            f"Software Version :  Server Iter {APP_ITERATION}",
            "Prepared By      :  Ankit Sharma"):
        cv.drawString(20 * mm, y, line)
        y -= 6.5 * mm
    cv.setFont("Helvetica-BoldOblique", 10.5)
    cv.setFillColor(rl.HexColor("#E0F2FE"))
    cv.drawString(20 * mm, 18 * mm,
                  '"Your Satisfaction is our First Ambition"')
    cv.restoreState()


def _page(cv, doc):
    cv.saveState()
    cv.setStrokeColor(TEAL)
    cv.setLineWidth(2)
    cv.line(15 * mm, H - 12 * mm, W - 15 * mm, H - 12 * mm)
    cv.setFont("Helvetica-Bold", 8)
    cv.setFillColor(NAVY)
    cv.drawString(15 * mm, H - 10 * mm,
                  getattr(doc, "_hdr_title",
                          "PAYROLL & COMPLIANCE PORTAL — QUICK USER MANUAL"))
    cv.drawRightString(W - 15 * mm, H - 10 * mm, "S.K. SHARMA & CO.")
    cv.setFont("Helvetica-BoldOblique", 8.5)
    cv.setFillColor(TEAL)
    cv.drawString(15 * mm, 8 * mm,
                  '"Your Satisfaction is our First Ambition"')
    cv.setFont("Helvetica", 8)
    cv.setFillColor(GREY)
    cv.drawRightString(W - 15 * mm, 8 * mm, f"Page {cv.getPageNumber()}")
    cv.restoreState()


def build_manual(extras: Optional[list] = None) -> BytesIO:
    buf = BytesIO()
    doc = _Doc(buf, pagesize=A4, title="Quick User Manual")
    fr = Frame(15 * mm, 14 * mm, CW, H - 32 * mm, id="f")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[fr], onPage=_cover),
        PageTemplate(id="body", frames=[fr], onPage=_page)])
    story: list = [NextPageTemplate("body"), PageBreak()]

    # -------- table of contents
    story.append(Paragraph("Table of Contents", ParagraphStyle(
        "toc_h", parent=S_H1)))
    toc = TableOfContents()
    toc.levelStyles = [S_TOC]
    toc.dotsMinLevel = 0
    story.append(toc)
    story.append(PageBreak())

    _section(story, 1, "Login", "Portal URL → Admin Sign In", "login",
             ["Choose 'Admin sign in'", "Enter User ID / Email",
              "Enter PIN or Password", "Click Sign In"],
             ["Open the portal link in Chrome / Edge.",
              "Click <b>Admin sign in</b>.",
              "Enter your registered <b>Email / Mobile</b> and "
              "<b>PIN or Password</b>.",
              "Click <b>Sign In</b>. Use <b>Forgot PIN</b> on the same "
              "screen if you cannot remember your credentials."],
             note="Your account locks after repeated wrong attempts — "
                  "contact the administrator to unlock.")

    _section(story, 2, "Dashboard", "Home → Dashboard", "dashboard",
             ["Active Firm selector", "Priority / Pending tasks",
              "Total Employees & Attendance", "Payroll & Compliance status"],
             ["Select your <b>Firm</b> from the top selector.",
              "Review <b>Priority Tasks</b> (statutory due dates).",
              "Check <b>Total Employees, Today's Attendance and Pending "
              "Payroll</b> cards.",
              "Use the left menu to open any module."],
             note="The bell icon shows notifications; the footer shows the "
                  "server version and connection status.")

    _section(story, 3, "Company / Firm Master", "Firms → Firm Master",
             "firm_master",
             ["Firm list", "Add / edit firm", "Statutory settings",
              "Attendance policy"],
             ["Open <b>Firms</b> from the sidebar.",
              "Click a firm to edit its address, PF/ESIC codes and "
              "statutory settings.",
              "Configure the <b>attendance / OT policy</b> (e.g. Count "
              "Present Day @ 8 HRS) per firm.",
              "Save — the policy automatically drives attendance & payroll."])

    _section(story, 4, "Employee Master", "Employees → Employee Master",
             "employee_master",
             ["Employee search", "Add Employee", "Profile fields",
              "Bank & statutory IDs"],
             ["Open <b>Employee Master</b> and search by name / code.",
              "Click <b>Add Employee</b> to register a new joinee.",
              "Fill the key fields: <b>Name, Father Name, Code, DOJ, "
              "Designation, Department, Mobile, UAN, ESIC IP, Bank "
              "details and Salary</b>.",
              "Save. The employee immediately appears in attendance "
              "and payroll."],
             note="UAN, ESIC and Bank details are mandatory for error-free "
                  "challans and salary payment files.")

    _section(story, 5, "Attendance", "Attendance & Shift → Attendance Grid",
             "attendance",
             ["Month selector", "Day-wise P/A/WO/HO grid",
              "Policy present days", "OT hours"],
             ["Open the <b>Attendance Grid</b> and pick the month.",
              "Review day-wise codes: <b>P</b> Present, <b>A</b> Absent, "
              "<b>WO</b> Weekly Off, <b>HO</b> Holiday, <b>HD</b> Half "
              "Day, Leave codes.",
              "Correct punches where authorised.",
              "Attendance flows automatically into payable days and "
              "payroll."],
             note="Payable days are calculated by the firm's attendance "
                  "policy — never by a fixed formula.")

    _section(story, 6, "Biometric Punch", "Devices & Integration → "
             "Biometric Devices", "biometric",
             ["Registered devices", "Live status", "Punch logs",
              "Employee mapping"],
             ["Biometric machines push punches automatically: <b>Device → "
              "IN/OUT Punch → Attendance → Payroll</b>.",
              "Check device <b>online status</b> here.",
              "Open punch logs to verify IN/OUT times and photos.",
              "Map any 'Not Registered' employees to their profile."])

    _section(story, 7, "Leave & ESIC Leave",
             "Payroll → Leaves · ESIC Leave", "leave",
             ["Leave entry", "Approval", "Balance", "Attendance impact"],
             ["Record leave with type (<b>CL / SL / EL</b>) and dates.",
              "Approve or reject pending requests.",
              "Approved paid leave counts inside payable days as per "
              "policy.",
              "For ESIC sickness benefit, use the <b>ESIC Leave</b> screen "
              "— those days are marked ESIC in reports."])

    _section(story, 8, "Overtime (OT)", "Reports → OT Report", "overtime",
             ["OT hours per day", "OT rate", "OT amount",
              "Payroll integration"],
             ["OT is computed by the firm policy (e.g. hours beyond 8/day "
              "become OT).",
              "Review employee-wise <b>OT Hours</b> here.",
              "OT amount = OT hours × configured OT rate.",
              "The same OT automatically appears in salary processing — "
              "no re-entry."])

    _section(story, 9, "Salary Processing (Actual Salary)",
             "Payroll → Salary Process → Actual Salary", "actual_salary",
             ["Month selection", "Attendance-based payable days",
              "Earnings & OT", "Process / Save run"],
             ["Select firm and <b>payroll month</b>.",
              "Verify payable days pulled from attendance.",
              "Review earnings, OT and deductions per employee.",
              "Click <b>Process</b> and save the run."],
             note="Workflow: Attendance → Payable Days → Salary → OT → "
                  "Deductions → Net Payable.")

    _section(story, 10, "Compliance Salary",
             "Payroll → Salary Process → Compliance Salary",
             "compliance_salary",
             ["Statutory wage calculation", "PF / ESIC / PT / TDS",
              "Freeze / finalize", "Registers & challans"],
             ["Open <b>Compliance Salary</b> for the month.",
              "The engine applies statutory rules, minimum wages and the "
              "8-hour present-day policy.",
              "Review PF, ESIC, PT and TDS amounts.",
              "<b>Finalize / freeze</b> the run — registers, challans and "
              "reports read from this run."])

    # ---- comparison table
    story.append(Paragraph("11. Compliance Salary vs Actual Salary", S_H1))
    cmp_t = Table([
        [Paragraph("<b>Compliance Salary</b>", S_BODY),
         Paragraph("<b>Actual Salary</b>", S_BODY)],
        [Paragraph("Statutory / compliance calculation", S_BODY),
         Paragraph("Actual approved payroll", S_BODY)],
        [Paragraph("Used for applicable compliance processing (PF, ESIC, "
                   "registers, challans)", S_BODY),
         Paragraph("Used for actual employee payment", S_BODY)],
        [Paragraph("Based on configured statutory rules & wage policy",
                   S_BODY),
         Paragraph("Based on the approved salary structure", S_BODY)],
    ], colWidths=[CW / 2, CW / 2])
    cmp_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), rl.white),
        ("GRID", (0, 0), (-1, -1), 0.6, GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl.white, TEAL_BG]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    for i in range(2):
        cmp_t._cellvalues[0][i].style = ParagraphStyle(
            "hh", parent=S_BODY, textColor=rl.white)
    story.append(cmp_t)
    story.append(Spacer(1, 6))
    story.append(_note("Both salaries are calculated independently — one "
                       "never overwrites the other. The selected Salary "
                       "Basis decides the final payable salary.", warn=False))
    story.append(PageBreak())

    _section(story, 12, "Deductions",
             "Payroll → Salary Process / Advance Module", None,
             ["PF & ESIC (auto)", "TDS / PT", "Advance & EMI",
              "Other deductions"],
             ["Statutory deductions (<b>PF, ESIC, PT, TDS</b>) come from "
              "the payroll engine — never entered manually.",
              "Record <b>Advances / Loans</b> in the Advance module; "
              "monthly EMI recovery is automatic.",
              "Other deductions use the configurable deduction heads.",
              "Total deductions are shown on the salary slip and reports."],
             body="All deductions flow from the existing payroll "
                  "calculation engine and firm settings.")

    _section(story, 13, "Payroll Finalization", "Salary Run → Finalize",
             None,
             ["Draft", "Verify", "Approve", "Finalize / Lock"],
             ["Process the run — it starts as <b>Draft</b>.",
              "Verify totals against the attendance summary.",
              "Approve the run (authorised users).",
              "<b>Finalize / freeze</b> — the month is locked for edits."],
             note="Finalized payroll must only be changed through the "
                  "authorised unlock / correction procedure. Every unlock "
                  "is recorded in the audit trail.", warn=True)

    _section(story, 14, "Salary Slip", "Payroll → Payslip", "payslip",
             ["Employee & month", "Earnings", "Deductions",
              "Net payable"],
             ["Open <b>Payslip</b>, choose employee and month.",
              "The slip shows attendance, earnings, OT, deductions, gross "
              "and <b>Net Payable</b>.",
              "Download PDF or share with the employee.",
              "Slips always reflect the finalized payroll."])

    _section(story, 15, "Bank Payment", "Payroll → Bank Transfer", "bank",
             ["Bank sheet", "Account validation", "Export for bank",
              "Payment mode"],
             ["Generate the <b>bank sheet</b> for the finalized month.",
              "Verify account number / IFSC flags.",
              "Export the bank-format Excel for salary upload.",
              "Employees without bank details are listed for cash "
              "payment."])

    _section(story, 16, "Reports (Report Hub)", "Reports → Report Hub",
             "reports",
             ["Report groups", "Month & filters", "Contractor registers",
              "Excel / PDF buttons"],
             ["Open the <b>Report Hub</b> — reports are grouped: "
              "Attendance, Payroll, Compliance, Employee, Bank and "
              "Statutory Registers.",
              "Pick the report, month and filters.",
              "Preview on screen.",
              "Export via the Excel / PDF buttons."])

    _section(story, 17, "Monthly Payroll Report",
             "Reports → Monthly Payroll Report", "monthly_payroll",
             ["Filters & salary basis", "Attendance 1–31",
              "Salary & deductions", "Net payable + bank"],
             ["One report combines <b>Employee → Attendance 1–31 → "
              "Payable Days → Salary → Deductions → Net Payable → Bank</b>.",
              "Choose the <b>Salary Basis</b> (Compliance / Actual).",
              "Scroll — employee columns stay frozen.",
              "Export Excel / PDF (landscape) with footer totals."])

    _section(story, 18, "Excel / PDF Export", "Any report screen", None,
             ["Filter", "Generate", "Export Excel", "Export PDF"],
             ["Set the filters (firm, month, department…).",
              "Generate / preview the report.",
              "Click <b>Excel</b> for spreadsheets or <b>PDF</b> for "
              "print-ready output.",
              "PDFs use landscape orientation with repeated headers for "
              "wide registers."],
             body="Every report follows the same pattern: "
                  "<b>Filter → Generate → Export Excel / PDF</b>.")

    # -------- PWA — install the portal as an app (user request Iter 532)
    story.append(Paragraph("19. Install as an App (PWA)", S_H1))
    story.append(Paragraph(
        "The portal is a <b>Progressive Web App</b> — install it on any "
        "phone, tablet or computer directly from the browser. No Play "
        "Store / App Store download is needed, and it always opens the "
        "latest version.", S_BODY))
    story.append(Spacer(1, 5))
    pwa_t = Table([
        [Paragraph("<b>Device</b>", S_BODY),
         Paragraph("<b>How to install</b>", S_BODY)],
        [Paragraph("Android phone / tablet (Chrome)", S_BODY),
         Paragraph("Open the portal link → tap the <b>3-dot menu</b> "
                   "(top-right) → <b>Install app</b> (or \"Add to Home "
                   "screen\") → Install. The portal icon appears on your "
                   "home screen.", S_BODY)],
        [Paragraph("iPhone / iPad (Safari)", S_BODY),
         Paragraph("Open the portal link → tap the <b>Share</b> button "
                   "(square with arrow) → <b>Add to Home Screen</b> → "
                   "Add.", S_BODY)],
        [Paragraph("Windows / Mac desktop (Chrome or Edge)", S_BODY),
         Paragraph("Open the portal → click the <b>install icon</b> in "
                   "the address bar → Install. The portal "
                   "opens in its own window like a desktop app.", S_BODY)],
    ], colWidths=[CW * 0.32, CW * 0.68])
    pwa_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.6, GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl.white, TEAL_BG]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(pwa_t)
    story.append(Spacer(1, 6))
    for b in ("Full-screen app experience with its own home-screen icon "
              "and splash screen.",
              "Faster loading — the app shell is cached on your device.",
              "Employees can use the same install for punch-in, payslips "
              "and leave requests.",
              "Works on any device with a modern browser — nothing to "
              "publish or update through app stores."):
        story.append(Paragraph(f"<font color='#0E7490'><b>•</b></font> {b}",
                               S_STEP))
    story.append(Spacer(1, 4))
    story.append(_note("After a software update, close the installed app "
                       "FULLY and reopen it twice (desktop: Ctrl+Shift+R) "
                       "so the new version loads.", warn=True))
    story.append(PageBreak())

    # -------- dynamic extra sections (manual_sections collection) so new
    # payroll features extend the manual WITHOUT code changes
    n = 20
    for ex in (extras or []):
        _section(story, n, ex.get("title", "New Feature"),
                 ex.get("nav", ""), ex.get("shot") or None,
                 ex.get("callouts") or [], ex.get("steps") or [],
                 note=ex.get("note") or None)
        n += 1

    # -------- troubleshooting
    story.append(Paragraph(f"{n}. Basic Troubleshooting", S_H1))
    tt = Table([
        [Paragraph("<b>Problem</b>", S_BODY),
         Paragraph("<b>What to do</b>", S_BODY)],
        [Paragraph("Cannot login / forgot PIN", S_BODY),
         Paragraph("Use Forgot PIN on the login screen or contact the "
                   "administrator.", S_BODY)],
        [Paragraph("Punches not appearing", S_BODY),
         Paragraph("Check the biometric device online status under "
                   "Devices & Integration.", S_BODY)],
        [Paragraph("Report shows 'Salary Not Calculated'", S_BODY),
         Paragraph("Process / finalize the salary run for that month "
                   "first.", S_BODY)],
        [Paragraph("Report shows 'Attendance Pending'", S_BODY),
         Paragraph("Attendance for the month has not been captured yet.",
                   S_BODY)],
        [Paragraph("Old data showing after an update", S_BODY),
         Paragraph("Desktop: press Ctrl+Shift+R. Phone app: close fully "
                   "and reopen twice.", S_BODY)],
    ], colWidths=[CW * 0.38, CW * 0.62])
    tt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.6, GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl.white, TEAL_BG]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(tt)
    story.append(PageBreak())

    # -------- final one-page workflow
    story.append(Paragraph(f"{n + 1}. Payroll Quick Workflow", S_H1))
    story.append(Paragraph(
        "The complete monthly cycle at a glance:", S_BODY))
    story.append(Spacer(1, 4))
    flow = ["Company Setup", "Employee Master", "Salary Structure",
            "Attendance", "Leave / OT", "Salary Processing",
            "Compliance Salary", "Actual Salary", "Deductions",
            "Finalization", "Salary Slip / Bank Payment", "Reports"]
    rows = []
    for i, f in enumerate(flow):
        rows.append([Paragraph(f"<b>{f}</b>", ParagraphStyle(
            "fl", fontName="Helvetica-Bold", fontSize=10.5, leading=13,
            textColor=rl.white, alignment=1))])
        if i < len(flow) - 1:
            rows.append([Paragraph("▼", ParagraphStyle(
                "ar", fontSize=8, leading=8, textColor=TEAL, alignment=1))])
    ft = Table(rows, colWidths=[92 * mm])
    style = [("ALIGN", (0, 0), (-1, -1), "CENTER"),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    for i in range(0, len(rows), 2):
        style += [("BACKGROUND", (0, i), (0, i),
                   NAVY if (i // 2) % 2 == 0 else TEAL),
                  ("TOPPADDING", (0, i), (0, i), 5),
                  ("BOTTOMPADDING", (0, i), (0, i), 5),
                  ("ROUNDEDCORNERS", [6])]
    ft.setStyle(TableStyle(style))
    wrap = Table([[ft]], colWidths=[CW])
    wrap.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story.append(wrap)
    story.append(Spacer(1, 8))
    story.append(_note("Need help? Contact S.K. Sharma & Co. — your "
                       "payroll & compliance partner."))

    doc.multiBuild(story)
    buf.seek(0)
    return buf


_SEED_UPDATES = [
    {"date": "2026-08-09", "title": "Monthly Payroll Attendance & Salary Report",
     "desc": "One landscape report: employee details, attendance 1–31, "
             "payable days, compliance/actual gross, deductions, net "
             "payable and bank details with Excel/PDF export.",
     "nav": "Reports → Monthly Payroll Report"},
    {"date": "2026-08-09", "title": "Quick User Manual (PDF)",
     "desc": "Client-ready manual with real screenshots — auto-rebuilds "
             "with the latest version, features and screenshots.",
     "nav": "Administration → User Manual (PDF)"},
    {"date": "2026-08-09", "title": "Central Contractor Wage Registers (Form A–D)",
     "desc": "Form A Employee Register, Form B Wage Register, Form C "
             "Deductions/Advances, Form D Muster Roll with approval "
             "workflow and Excel/PDF export.",
     "nav": "Report Hub → Contractor Registers"},
    {"date": "2026-08-09", "title": "Salary Comparison — Department / Designation wise",
     "desc": "Grouped comparison with No. of Employees and Total "
             "Attendance columns (name-wise rows removed).",
     "nav": "Report Hub → Salary Comparison"},
    {"date": "2026-08-08", "title": "Present / Absent + Daily OT Report",
     "desc": "New format: two rows per employee — daily status and that "
             "day's OT hours, with monthly totals.",
     "nav": "Reports → Present / Absent Report"},
]


async def _manual_data():
    """Live data for the auto-updating manual (changelog + extra
    sections). Seeds the changelog once so it is never empty."""
    if not await db.manual_updates.count_documents({}):
        await db.manual_updates.insert_many(
            [dict(u) for u in _SEED_UPDATES])
    updates = await db.manual_updates.find({}, {"_id": 0}).to_list(200)
    updates.sort(key=lambda u: str(u.get("date") or ""), reverse=True)
    extras = await db.manual_sections.find({}, {"_id": 0}).to_list(100)
    extras.sort(key=lambda x: x.get("order") or 0)
    return updates, extras


@router.get("/user-manual.pdf")
async def user_manual_pdf(token: Optional[str] = Query(None),
                          authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(
        authorization or (f"Bearer {token}" if token else None))
    require_role(admin, ["super_admin"])  # SUPER ADMIN ONLY
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin only")
    extras = (await _manual_data())[1]
    buf = build_manual(extras)
    return Response(content=buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition":
                             'inline; filename="Payroll_Quick_User_Manual.pdf"'})


def build_employee_guide() -> BytesIO:
    """Iter 533 — short phone-first EMPLOYEE Quick Guide (~8 pages):
    install → sign in → punch → attendance → leave → payslip → profile."""
    buf = BytesIO()
    doc = _Doc(buf, pagesize=A4, title="Employee Quick Guide")
    doc._hdr_title = "EMPLOYEE QUICK GUIDE — PAYROLL PORTAL"
    fr = Frame(15 * mm, 14 * mm, CW, H - 32 * mm, id="f")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[fr], onPage=_cover_emp),
        PageTemplate(id="body", frames=[fr], onPage=_page)])
    story: list = [NextPageTemplate("body"), PageBreak()]

    _section(story, 1, "Install the App on Your Phone",
             "Open the portal link your employer shared", None,
             ["Android: 3-dot menu → Install app",
              "iPhone: Share → Add to Home Screen"],
             ["Open the portal link in your phone browser.",
              "<b>Android (Chrome):</b> tap the 3-dot menu → "
              "<b>Install app</b> / \"Add to Home screen\".",
              "<b>iPhone (Safari):</b> tap <b>Share</b> → "
              "<b>Add to Home Screen</b>.",
              "Open the new icon — the portal now works like a mobile "
              "app."],
             note="No Play Store / App Store download is needed.")

    _section(story, 2, "Sign In", "App icon → Sign In", "emp_login",
             ["Enter mobile / email", "Enter your PIN", "Tap Sign In"],
             ["Open the app and choose the employee sign-in.",
              "Enter your registered <b>mobile number / email</b>.",
              "Enter your <b>PIN</b> and tap Sign In.",
              "Forgot your PIN? Contact your HR / admin."],
             img_h=88 * mm)

    _section(story, 3, "Home — Punch In / Punch Out", "Home tab",
             "emp_home",
             ["Big Punch In / Out button", "Today's punch times",
              "Duty hours summary", "My services shortcuts"],
             ["Allow <b>location</b> (and camera if asked) so your punch "
              "is verified.",
              "Tap the big <b>Punch In</b> button when duty starts.",
              "Tap <b>Punch Out</b> when duty ends.",
              "Your punch time, working hours and shift show instantly."],
             note="Punch works only near your assigned site if your firm "
                  "uses geo-fencing.", img_h=88 * mm)

    _section(story, 4, "My Attendance", "Attendance tab", "emp_attendance",
             ["Month view", "P / A / WO / Holiday marks",
              "Worked hours & OT"],
             ["Open the <b>Attendance</b> tab.",
              "See each day: Present, Absent, Weekly Off, Holiday or "
              "Leave.",
              "Check your total present days, hours and OT.",
              "Report any mismatch to HR immediately."],
             img_h=88 * mm)

    _section(story, 5, "Apply Leave", "Leave tab", "emp_leave",
             ["Apply Leave button", "Type & dates", "Status: Pending / "
              "Approved"],
             ["Open the <b>Leave</b> tab and tap Apply.",
              "Choose the leave type (Casual / Sick / Earned) and dates.",
              "Add a short reason and submit.",
              "Track the status — approved leave reflects in attendance "
              "automatically."],
             img_h=88 * mm)

    _section(story, 6, "My Payslip", "Payslip tab", "emp_payslip",
             ["Month selector", "Attendance summary", "Gross salary"],
             ["Open the <b>Payslip</b> tab.",
              "See your present days, hours and salary for the month.",
              "Use the month arrows to view previous months.",
              "Questions about amounts? Contact your HR / employer."],
             img_h=88 * mm)

    _section(story, 7, "My Profile & Documents", "Profile tab",
             "emp_profile",
             ["Personal details", "Bank & IDs", "My documents"],
             ["Open the <b>Profile</b> tab.",
              "Verify your name, mobile, bank account and UAN/ESIC "
              "details.",
              "Upload / view documents when requested.",
              "Wrong details? Ask HR to update them."],
             img_h=88 * mm)

    # help page
    story.append(Paragraph("8. Help & Tips", S_H1))
    ht = Table([
        [Paragraph("<b>Problem</b>", S_BODY),
         Paragraph("<b>What to do</b>", S_BODY)],
        [Paragraph("Punch button not working", S_BODY),
         Paragraph("Turn ON location (GPS) and give the app location "
                   "permission, then try again.", S_BODY)],
        [Paragraph("Forgot PIN", S_BODY),
         Paragraph("Use Forgot PIN on the sign-in screen or contact HR.",
                   S_BODY)],
        [Paragraph("Payslip shows no data", S_BODY),
         Paragraph("Salary for that month may not be processed yet — "
                   "check the previous month.", S_BODY)],
        [Paragraph("App shows old screens", S_BODY),
         Paragraph("Close the app fully and reopen it twice.", S_BODY)],
    ], colWidths=[CW * 0.38, CW * 0.62])
    ht.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("GRID", (0, 0), (-1, -1), 0.6, GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl.white, TEAL_BG]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(ht)
    story.append(Spacer(1, 8))
    story.append(_note("Daily routine: Punch In when duty starts → work → "
                       "Punch Out → check attendance → payslip at month "
                       "end. That's it!"))
    doc.multiBuild(story)
    buf.seek(0)
    return buf


@router.get("/employee-guide.pdf")
async def employee_guide_pdf(token: Optional[str] = Query(None),
                             authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(
        authorization or (f"Bearer {token}" if token else None))
    require_role(admin, ["super_admin"])  # SUPER ADMIN ONLY
    buf = build_employee_guide()
    return Response(content=buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition":
                             'inline; filename="Employee_Quick_Guide.pdf"'})


# ---------------------------------------------------------------------------
# Iter 531 — auto-update helpers: screenshot refresh + changelog logging
# ---------------------------------------------------------------------------
_PID_FILE = os.path.join(ASSETS, ".capture.pid")


def _capture_running() -> bool:
    try:
        with open(_PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


@router.post("/user-manual/refresh-screenshots")
async def refresh_screenshots(authorization: Optional[str] = Header(None)):
    """Re-capture every manual screenshot from the CURRENT portal UI so the
    manual reflects newly shipped payroll features (super admin only)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    try:
        import playwright  # noqa: F401
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Screenshot engine not installed on this server. "
                   "Screenshots ship pre-bundled and can be refreshed from "
                   "the development workspace.")
    if _capture_running():
        return {"ok": True, "status": "already-running"}
    base = (os.environ.get("PORTAL_BASE_URL")
            or "https://emplo-connect-1.preview.emergentagent.com")
    raw_token = (authorization or "").replace("Bearer ", "").strip()
    script = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "manual_capture.py")
    proc = subprocess.Popen(
        [sys.executable, script, "--base", base, "--token", raw_token],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    os.makedirs(ASSETS, exist_ok=True)
    with open(_PID_FILE, "w") as f:
        f.write(str(proc.pid))
    return {"ok": True, "status": "started",
            "note": "Capture takes ~2 minutes; check status, then "
                    "re-download the manual."}


@router.get("/user-manual/status")
async def manual_status(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    shots = [f[:-4] for f in sorted(os.listdir(ASSETS))
             if f.endswith(".png")] if os.path.isdir(ASSETS) else []
    updates, extras = await _manual_data()
    return {"screenshots": len(shots), "capture_running": _capture_running(),
            "last_capture": _shot_meta(),
            "server_version": APP_ITERATION,
            "whats_new_entries": len(updates),
            "extra_sections": len(extras)}


@router.post("/user-manual/log-update")
async def log_update(payload: dict = Body(default={}),  # noqa: B008
                     authorization: Optional[str] = Header(None)):
    """Append a feature to the manual's What's New changelog (used every
    time a new payroll feature ships)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    doc = {"date": str(payload.get("date") or date.today().isoformat())[:10],
           "title": str(payload.get("title") or "").strip(),
           "desc": str(payload.get("desc") or "").strip(),
           "nav": str(payload.get("nav") or "").strip()}
    if not doc["title"]:
        raise HTTPException(status_code=400, detail="title required")
    await db.manual_updates.insert_one(doc)
    return {"ok": True}
