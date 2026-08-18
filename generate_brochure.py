"""Iter 609 — Client-facing Employee PWA feature brochure (branded PDF).
Generates /app/brochure_employee_pwa.pdf — one polished A4 page,
S.K. Sharma & Co. / smartpayrolling.com branding (#2563EB / #0F172A)."""
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

BLUE = HexColor("#2563EB")
NAVY = HexColor("#0F172A")
DARKBLUE = HexColor("#1E3A8A")
GREY = HexColor("#475569")
LIGHT = HexColor("#EFF6FF")
GREEN = HexColor("#059669")
W, H = A4  # 595 x 842


def wrap(c, text, x, y, width, font="Helvetica", size=8.4, leading=11,
         color=GREY):
    c.setFont(font, size)
    c.setFillColor(color)
    words, line = text.split(), ""
    for w_ in words:
        t = f"{line} {w_}".strip()
        if c.stringWidth(t, font, size) <= width:
            line = t
        else:
            c.drawString(x, y, line)
            y -= leading
            line = w_
    if line:
        c.drawString(x, y, line)
        y -= leading
    return y


def bullet(c, x, y, width, title, desc, accent=BLUE):
    c.setFillColor(accent)
    c.circle(x + 3, y + 2.7, 2.1, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 8.8)
    c.setFillColor(NAVY)
    c.drawString(x + 10, y, title)
    tw = c.stringWidth(title, "Helvetica-Bold", 8.8)
    if desc:
        y = wrap(c, desc, x + 10 + tw + 4, y, width - 10 - tw - 4)
        return y - 2.5
    return y - 13.5


def section(c, x, y, width, label, emoji=""):
    c.setFillColor(BLUE)
    c.roundRect(x, y - 4, width, 16, 4, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 9.5)
    c.setFillColor(white)
    c.drawString(x + 8, y, f"{emoji}{label}")
    return y - 20


c = canvas.Canvas("/app/brochure_employee_pwa.pdf", pagesize=A4)

# ── Header band ──
c.setFillColor(NAVY)
c.rect(0, H - 118, W, 118, stroke=0, fill=1)
c.setFillColor(BLUE)
c.rect(0, H - 124, W, 6, stroke=0, fill=1)
c.setFont("Helvetica-Bold", 21)
c.setFillColor(white)
c.drawString(40, H - 52, "Employee Mobile App (PWA)")
c.setFont("Helvetica", 11)
c.setFillColor(HexColor("#93C5FD"))
c.drawString(40, H - 72, "Complete employee self-service — attendance, payslips, leaves, claims & more")
c.setFont("Helvetica-Bold", 11.5)
c.setFillColor(white)
c.drawRightString(W - 40, H - 48, "S.K. Sharma & Co.")
c.setFont("Helvetica", 9.5)
c.setFillColor(HexColor("#93C5FD"))
c.drawRightString(W - 40, H - 63, "smartpayrolling.com")
c.setFont("Helvetica-Oblique", 9)
c.setFillColor(HexColor("#CBD5E1"))
c.drawString(40, H - 100, "No app-store download needed — employees just open the link and 'Add to Home Screen'. Works on any Android or iPhone.")

# ── Two columns ──
LX, RX = 40, W / 2 + 12
CW = W / 2 - 64
y = H - 152

# LEFT column
yl = section(c, LX, y, CW + 12, "DAILY ESSENTIALS")
yl = bullet(c, LX, yl, CW + 12, "Attendance Punch", "one-tap IN/OUT with GPS geofence + live selfie + exact time")
yl = bullet(c, LX, yl, CW + 12, "Attendance History", "monthly calendar, present/absent, punch photos")
yl = bullet(c, LX, yl, CW + 12, "Leave Management", "apply in seconds, live approval status, leave balance")
yl = bullet(c, LX, yl, CW + 12, "Payslips", "monthly salary slips with full earnings & deductions breakup")
yl = bullet(c, LX, yl, CW + 12, "My Advances", "advances taken, EMI deductions, outstanding balance")
yl = bullet(c, LX, yl, CW + 12, "Tasks", "assigned to-dos from supervisors, mark complete")
yl -= 8
yl = section(c, LX, yl, CW + 12, "EXPENSES & MONEY", )
yl = bullet(c, LX, yl, CW + 12, "Expense Claims (AI-powered)", "photograph the receipt — AI reads vendor, amount, date & GST automatically", GREEN)
yl = bullet(c, LX, yl, CW + 12, "Approval Tracking", "Manager -> Accounts -> Finance, live status on every claim", GREEN)
yl = bullet(c, LX, yl, CW + 12, "Reimbursements", "paid via bank/UPI or directly inside the next salary", GREEN)
yl -= 8
yl = section(c, LX, yl, CW + 12, "DOCUMENTS & IDENTITY")
yl = bullet(c, LX, yl, CW + 12, "Digital ID Card", "company ID card on the phone")
yl = bullet(c, LX, yl, CW + 12, "KYC Upload", "Aadhaar, PAN & bank details — verified by HR")
yl = bullet(c, LX, yl, CW + 12, "My Documents", "offer letters, contracts & company circulars")

# RIGHT column
yr = section(c, RX, y, CW + 12, "BANK-GRADE SECURITY")
yr = bullet(c, RX, yr, CW + 12, "Secure Punch", "registered-device passkey (phone's own Face ID / fingerprint) before the camera opens", DARKBLUE)
yr = bullet(c, RX, yr, CW + 12, "Live Face Verification", "1:1 face match against the enrolled employee — nobody can punch for someone else", DARKBLUE)
yr = bullet(c, RX, yr, CW + 12, "Liveness + Anti-Spoofing", "random challenges block photos, screens & video replays", DARKBLUE)
yr = bullet(c, RX, yr, CW + 12, "Device Binding", "one registered phone per employee; replacement needs HR approval", DARKBLUE)
yr = bullet(c, RX, yr, CW + 12, "Privacy First", "the phone's biometric never leaves the device — only a cryptographic confirmation is used", DARKBLUE)
yr -= 8
yr = section(c, RX, yr, CW + 12, "COMMUNICATION")
yr = bullet(c, RX, yr, CW + 12, "Helpdesk Tickets", "raise HR queries, track resolution")
yr = bullet(c, RX, yr, CW + 12, "Messages & Announcements", "company circulars straight to the phone")
yr -= 8
yr = section(c, RX, yr, CW + 12, "BUILT FOR THE FIELD")
yr = bullet(c, RX, yr, CW + 12, "Works Offline", "punches queue offline & sync automatically — security never bypassed")
yr = bullet(c, RX, yr, CW + 12, "Multi-Worksite", "site selection for employees moving between locations")
yr = bullet(c, RX, yr, CW + 12, "Simple Login", "username/mobile + PIN, easy forgot-PIN recovery")
yr = bullet(c, RX, yr, CW + 12, "Any Phone", "Android & iPhone, installable like a normal app")

# ── Footer band ──
c.setFillColor(LIGHT)
c.roundRect(40, 58, W - 80, 54, 8, stroke=0, fill=1)
c.setFont("Helvetica-Bold", 10.5)
c.setFillColor(NAVY)
c.drawString(56, 90, "Give your workforce a modern self-service experience — zero paperwork, full compliance.")
c.setFont("Helvetica", 9)
c.setFillColor(GREY)
c.drawString(56, 74, "Contact S.K. Sharma & Co. for a demo  ·  sksharmaconsultancy@gmail.com  ·  smartpayrolling.com")
c.setFont("Helvetica", 7.5)
c.setFillColor(HexColor("#94A3B8"))
c.drawCentredString(W / 2, 40, "Powered by SmartPayrolling — attendance, payroll & compliance on one platform.")

c.showPage()

# ═════════════════ PAGE 2 — HOW IT WORKS ═════════════════
c.setFillColor(NAVY)
c.rect(0, H - 86, W, 86, stroke=0, fill=1)
c.setFillColor(BLUE)
c.rect(0, H - 92, W, 6, stroke=0, fill=1)
c.setFont("Helvetica-Bold", 19)
c.setFillColor(white)
c.drawString(40, H - 46, "How It Works")
c.setFont("Helvetica", 10.5)
c.setFillColor(HexColor("#93C5FD"))
c.drawString(40, H - 66, "From setup to salary — fully automatic, zero paperwork")
c.setFont("Helvetica-Bold", 10.5)
c.setFillColor(white)
c.drawRightString(W - 40, H - 46, "S.K. Sharma & Co.")
c.setFont("Helvetica", 9)
c.setFillColor(HexColor("#93C5FD"))
c.drawRightString(W - 40, H - 61, "smartpayrolling.com")


def step_card(c, y, num, title, lines):
    box_h = 26 + len(lines) * 12
    c.setFillColor(LIGHT)
    c.roundRect(40, y - box_h, W - 80, box_h, 8, stroke=0, fill=1)
    c.setFillColor(BLUE)
    c.circle(62, y - 16, 10.5, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(white)
    c.drawCentredString(62, y - 19.5, str(num))
    c.setFont("Helvetica-Bold", 10.5)
    c.setFillColor(NAVY)
    c.drawString(82, y - 20, title)
    yy = y - 36
    c.setFont("Helvetica", 8.6)
    c.setFillColor(GREY)
    for ln in lines:
        c.drawString(82, yy, ln)
        yy -= 12
    return y - box_h - 10


y2 = H - 112
y2 = step_card(c, y2, 1, "One-time setup (by HR)", [
    "Add the employee in Employee Master — the system creates their login (Username / Mobile + PIN).",
    "Optional for Secure Punch: HR enrolls the employee's face (2-5 live samples, stored encrypted).",
])
y2 = step_card(c, y2, 2, "Employee installs the app — no app store", [
    "Open smartpayrolling.com on the phone browser \u2192 'Add to Home Screen' \u2192 works like a normal app.",
    "If Secure Punch is ON: the phone registers as a trusted device using its own Face ID / fingerprint —",
    "the biometric never leaves the phone; the server only receives a cryptographic confirmation.",
])
y2 = step_card(c, y2, 3, "Daily punch — 10 seconds", [
    "Tap PUNCH \u2192 GPS geofence check \u2192 live selfie (photo + exact time recorded) \u2192 attendance marked.",
    "Secure Punch adds: device passkey \u2192 random liveness challenges \u2192 anti-spoofing \u2192 1:1 face match.",
    "No internet? The punch queues offline and syncs automatically — security is never bypassed.",
])
y2 = step_card(c, y2, 4, "Self-service for everything else", [
    "Leave requests, payslip downloads, expense claims (photograph the receipt — AI fills vendor,",
    "amount, date & GST), advances, KYC upload, helpdesk tickets — each flows to the right approver.",
])
y2 = step_card(c, y2, 5, "Employer sees everything live", [
    "Live attendance dashboard, punch log with photos & GPS, leave/expense approval queues —",
    "and it all feeds salary processing and PF / ESIC compliance automatically. HR never re-enters data.",
])

# Punch-flow diagram strip
y2 -= 6
c.setFont("Helvetica-Bold", 10)
c.setFillColor(NAVY)
c.drawString(40, y2, "THE SECURE PUNCH PIPELINE")
y2 -= 26
steps = ["PUNCH", "GPS", "DEVICE\nPASSKEY", "LIVENESS", "ANTI-\nSPOOF", "FACE\nMATCH", "SAVED \u2713"]
bw, gap = 62, 14
x = 40
for i, st_ in enumerate(steps):
    last = i == len(steps) - 1
    c.setFillColor(GREEN if last else BLUE)
    c.roundRect(x, y2 - 14, bw, 30, 6, stroke=0, fill=1)
    c.setFont("Helvetica-Bold", 7.4)
    c.setFillColor(white)
    parts = st_.split("\n")
    if len(parts) == 2:
        c.drawCentredString(x + bw / 2, y2 + 5, parts[0])
        c.drawCentredString(x + bw / 2, y2 - 5, parts[1])
    else:
        c.drawCentredString(x + bw / 2, y2 - 1, parts[0])
    if not last:
        c.setFillColor(HexColor("#94A3B8"))
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(x + bw + gap / 2, y2 - 2, "\u203a")
    x += bw + gap
y2 -= 30
c.setFont("Helvetica-Oblique", 8)
c.setFillColor(GREY)
c.drawString(40, y2, "Any failed check = punch rejected. Nobody can punch for someone else — not with a photo, a video, or even the employee's own phone.")

# Footer
c.setFillColor(LIGHT)
c.roundRect(40, 52, W - 80, 46, 8, stroke=0, fill=1)
c.setFont("Helvetica-Bold", 10)
c.setFillColor(NAVY)
c.drawString(56, 80, "Ready in one day — we handle the full setup for your firm.")
c.setFont("Helvetica", 9)
c.setFillColor(GREY)
c.drawString(56, 65, "S.K. Sharma & Co.  ·  sksharmaconsultancy@gmail.com  ·  smartpayrolling.com")

c.showPage()
c.save()
print("brochure written")
