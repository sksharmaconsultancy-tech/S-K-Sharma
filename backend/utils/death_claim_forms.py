"""Iter 383 (user request) — printable EPFO death-claim forms.

Two builders that replicate the user's attached formats:

* ``build_composite_death_claim_pdf`` — "Composite Claim Form in Death
  Cases" [Form-20 (PF Payment) / Form-10D (Pension) / Form 5-IF (EDLI)]
  replicating the attached Excel layout.
* ``build_form8_pdf`` — "Form No. 8" descriptive roll of the pensioner
  (submitted in DUPLICATE → the PDF contains two identical pages).

Both read the flat ``dc_*`` keys saved on the claim's ``data`` dict by the
Claims form.
"""
from io import BytesIO
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

W, H = A4
LM, RM = 14 * mm, 14 * mm
CW = W - LM - RM


def _s(d: Dict[str, Any], k: str) -> str:
    v = d.get(k)
    return "" if v is None else str(v).strip()


def _dt(v: str) -> str:
    """ISO → DD-MM-YYYY for print; anything else passes through."""
    import re
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else str(v or "")


class _Pdf:
    def __init__(self):
        self.buf = BytesIO()
        self.c = rl_canvas.Canvas(self.buf, pagesize=A4)
        self.y = H - 12 * mm

    def line_row(self, label: str, value: str, num: str = "",
                 h: float = 7 * mm, lw: float = 88 * mm):
        c = self.c
        c.setLineWidth(0.6)
        c.rect(LM, self.y - h, CW, h)
        c.line(LM + 8 * mm, self.y - h, LM + 8 * mm, self.y)
        c.line(LM + 8 * mm + lw, self.y - h, LM + 8 * mm + lw, self.y)
        c.setFont("Helvetica", 8.5)
        c.drawCentredString(LM + 4 * mm, self.y - h + 2.3 * mm, num)
        c.drawString(LM + 10 * mm, self.y - h + 2.3 * mm, label)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(LM + 10 * mm + lw, self.y - h + 2.3 * mm,
                     (value or "")[:62])
        self.y -= h

    def grid(self, col_ws: List[float], rows: List[List[str]],
             h: float = 6.5 * mm, header_bold: bool = True,
             font: float = 7.3):
        c = self.c
        x0 = LM
        for ri, row in enumerate(rows):
            x = x0
            c.setLineWidth(0.6)
            for ci, cell in enumerate(row):
                w = col_ws[ci]
                c.rect(x, self.y - h, w, h)
                c.setFont("Helvetica-Bold" if (ri == 0 and header_bold)
                          else "Helvetica", font)
                txt = str(cell or "")
                maxch = int(w / (font * 0.55))
                c.drawCentredString(x + w / 2, self.y - h + 2.1 * mm,
                                    txt[:maxch])
                x += w
            self.y -= h

    def done(self) -> bytes:
        self.c.save()
        return self.buf.getvalue()


def build_composite_death_claim_pdf(d: Dict[str, Any]) -> bytes:
    p = _Pdf()
    c = p.c
    # ---- header --------------------------------------------------------
    c.setFont("Helvetica", 8)
    c.drawRightString(W - RM, p.y, "www.epfindia.gov.in")
    p.y -= 5 * mm
    c.setFont("Helvetica", 8.5)
    c.drawRightString(W - RM, p.y,
                      f"Mobile Number: {_s(d, 'dc_mobile') or _s(d, 'mobile_no')}")
    p.y -= 7 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(W / 2, p.y, "EMPLOYEES' PROVIDENT FUNDS ORGANISATION")
    p.y -= 6.5 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(W / 2, p.y, "Composite Claim Form in Death Cases")
    p.y -= 5.5 * mm
    c.setFont("Helvetica", 9)
    c.drawCentredString(
        W / 2, p.y,
        "[ Form-20 (PF Payment) / Form 10-D (Pension) / Form 5-IF (EDLI) ]")
    p.y -= 8 * mm

    def _tick(v: str) -> str:
        return "[X]" if str(v or "").lower() in ("1", "true", "yes", "on") \
            else "[  ]"

    p.line_row(
        "Tick whichever is/are applicable",
        f"(i) Provident Fund {_tick(_s(d, 'dc_app_pf'))}   "
        f"Pension {_tick(_s(d, 'dc_app_pension'))}   "
        f"Insurance EDLI {_tick(_s(d, 'dc_app_edli'))}", "1", lw=62 * mm)
    p.line_row("Name of the deceased member (in CAPITAL letters)",
               (_s(d, "employee_name") or "").upper(), "2")
    p.line_row("(a) Father's Name", _s(d, "dc_father"), "3")
    p.line_row("(b) Spouse's Name", _s(d, "dc_spouse"))
    p.line_row("Marital status of deceased member", _s(d, "dc_marital"), "4")
    p.line_row("(a) Aadhaar Number of deceased member (if available)",
               _s(d, "dc_aadhaar"), "5")
    p.line_row("(b) Universal Account Number (UAN)", _s(d, "uan"))
    p.line_row("(c) PF Account No. (in case UAN not available)",
               _s(d, "dc_pf_acc"))
    p.line_row("Date of Leaving Service", _dt(_s(d, "dol")), "6")
    p.line_row("(a) Whether Scheme Certificate has been issued (Yes/No)",
               _s(d, "dc_scheme_issued"), "7")
    p.line_row("(b) If Yes, Number of Scheme Certificate",
               _s(d, "dc_scheme_no"))
    p.line_row("(c) Scheme Certificate issuing office",
               _s(d, "dc_scheme_office"))
    p.line_row("Period of Non-Contributory service (Years/Months/Days)",
               _s(d, "dc_ncp"), "8")
    p.line_row("Date of death of the member", _dt(_s(d, "dc_death_date")), "9")
    p.line_row("Whether the member had died while in service (Yes/No)",
               _s(d, "dc_died_in_service"), "10")
    p.y -= 2 * mm

    # ---- 11. claimants table -------------------------------------------
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(LM, p.y - 3 * mm,
                 "11   CLAIMANT'S DETAILS FOR PROVIDENT FUND, PENSION AND "
                 "INSURANCE (EDLI)")
    p.y -= 5 * mm
    c.setFont("Helvetica", 7.3)
    c.drawString(LM, p.y - 3 * mm,
                 "Particulars of the claimant/minor/nominee(s)/legal "
                 "heir(s)/surviving family member on whose behalf the claim "
                 "is submitted")
    p.y -= 5 * mm
    cw = [9 * mm, 33 * mm, 33 * mm, 26 * mm, 14 * mm, 20 * mm, 18 * mm,
          15 * mm, 14 * mm]
    hdr = ["S.N.", "Name", "Father's / Spouse's Name", "Aadhaar Number",
           "Gender", "Date of Birth", "Marital Status", "Rel. with Member",
           "Guardian"]
    rows = [hdr]
    for i, rn in enumerate(["i", "ii", "iii", "iv"], start=1):
        rows.append([
            rn, _s(d, f"dc_cl{i}_name"), _s(d, f"dc_cl{i}_father"),
            _s(d, f"dc_cl{i}_aadhaar"), _s(d, f"dc_cl{i}_gender"),
            _dt(_s(d, f"dc_cl{i}_dob")), _s(d, f"dc_cl{i}_marital"),
            _s(d, f"dc_cl{i}_rel"), _s(d, f"dc_cl{i}_guardian")])
    p.grid(cw, rows)
    p.y -= 3 * mm

    # ---- 12. bank details PF & EDLI -------------------------------------
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(LM, p.y - 3 * mm,
                 "12   Bank Account details for payment of PF & EDLI")
    p.y -= 5 * mm
    cw2 = [44 * mm, 46 * mm, 46 * mm, 46 * mm]
    p.grid(cw2, [
        ["Bank Account details", "Claimant-I", "Claimant-II", "Claimant-III"],
        ["Name", _s(d, "dc_pfbank1_name"), _s(d, "dc_pfbank2_name"),
         _s(d, "dc_pfbank3_name")],
        ["Savings Bank Account No.", _s(d, "dc_pfbank1_acc"),
         _s(d, "dc_pfbank2_acc"), _s(d, "dc_pfbank3_acc")],
        ["Name & Address of the Bank", _s(d, "dc_pfbank1_bank"),
         _s(d, "dc_pfbank2_bank"), _s(d, "dc_pfbank3_bank")],
        ["IFS Code of Bank", _s(d, "dc_pfbank1_ifsc"),
         _s(d, "dc_pfbank2_ifsc"), _s(d, "dc_pfbank3_ifsc")],
    ])
    p.y -= 3 * mm

    # ---- 13. bank details Pension ---------------------------------------
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(LM, p.y - 3 * mm,
                 "13   Bank Account details for payment of Pension")
    p.y -= 5 * mm
    cw3 = [44 * mm, 34.5 * mm, 34.5 * mm, 34.5 * mm, 34.5 * mm]
    p.grid(cw3, [
        ["Bank Account details", "Claimant-I", "Claimant-II", "Claimant-III",
         "Claimant-IV"],
        ["Name", _s(d, "dc_pnbank1_name"), _s(d, "dc_pnbank2_name"),
         _s(d, "dc_pnbank3_name"), _s(d, "dc_pnbank4_name")],
        ["Savings Bank Account No.", _s(d, "dc_pnbank1_acc"),
         _s(d, "dc_pnbank2_acc"), _s(d, "dc_pnbank3_acc"),
         _s(d, "dc_pnbank4_acc")],
        ["Name & Address of the Bank", _s(d, "dc_pnbank1_bank"),
         _s(d, "dc_pnbank2_bank"), _s(d, "dc_pnbank3_bank"),
         _s(d, "dc_pnbank4_bank")],
        ["IFS Code of Bank", _s(d, "dc_pnbank1_ifsc"),
         _s(d, "dc_pnbank2_ifsc"), _s(d, "dc_pnbank3_ifsc"),
         _s(d, "dc_pnbank4_ifsc")],
    ])
    p.y -= 3 * mm

    # ---- 14. postal address ---------------------------------------------
    p.line_row("Full Postal address of claimant",
               f"{_s(d, 'dc_address')}    Pin: {_s(d, 'dc_pin')}", "14",
               h=9 * mm, lw=62 * mm)
    p.y -= 4 * mm
    c.setFont("Helvetica", 8.5)
    c.drawString(LM + 4 * mm, p.y,
                 "Certified that the particulars are true to the best of my "
                 "knowledge.")
    p.y -= 13 * mm
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(LM + 4 * mm, p.y, "Claimant's Signature")
    c.drawString(W / 2 + 10 * mm, p.y, "Employer's Signature")
    p.y -= 5 * mm
    c.setFont("Helvetica", 8.5)
    c.drawString(LM + 4 * mm, p.y, "Name: " + _s(d, "dc_cl1_name"))
    c.drawString(W / 2 + 10 * mm, p.y, "Designation & Seal of Employer")
    p.y -= 8 * mm
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(LM, p.y, "Enclosures:")
    c.setFont("Helvetica", 8)
    for enc in ["i)   Death Certificate",
                "ii)  Joint photograph of all the claimants",
                "iii) Date of birth certificate of children claiming pension",
                "iv)  Scheme certificate (if applicable)",
                "v)   For verification of bank accounts, a copy of cancelled "
                "cheque or attested copy of first page of bank pass book"]:
        p.y -= 4.2 * mm
        c.drawString(LM + 10 * mm, p.y, enc)
    return p.done()


def _form8_page(p: "_Pdf", d: Dict[str, Any]) -> None:
    c = p.c
    p.y = H - 14 * mm
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(W / 2, p.y, "FORM No. 8")
    p.y -= 6 * mm
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(
        W / 2, p.y,
        "(To be submitted in duplicate in respect of each person eligible "
        "for pension)")
    p.y -= 9 * mm
    rows = [
        ("1", "Name of the member", (_s(d, "employee_name") or "").upper()),
        ("2", "E.P.F. Account Number",
         f"{_s(d, 'dc_pf_acc')}   UAN-{_s(d, 'uan')}"),
        ("3", "Name of the Pensioner", _s(d, "dc_f8_pensioner")),
        ("4", "Father's / Husband's Name", _s(d, "dc_f8_father")),
        ("5", "Sex", _s(d, "dc_f8_sex")),
        ("6", "Nationality", _s(d, "dc_f8_nationality") or "INDIAN"),
        ("7", "Religion", _s(d, "dc_f8_religion")),
        ("8", "Height", _s(d, "dc_f8_height")),
    ]
    for num, lbl, val in rows:
        p.line_row(lbl, val, num, h=9 * mm, lw=80 * mm)
    p.line_row("Personal marks of Identification  (1)",
               _s(d, "dc_f8_mark1"), "9", h=9 * mm, lw=80 * mm)
    p.line_row("                                              (2)",
               _s(d, "dc_f8_mark2"), "", h=9 * mm, lw=80 * mm)
    p.line_row("Specimen signature of pensioner", "", "10", h=16 * mm,
               lw=80 * mm)
    p.y -= 4 * mm
    c.setFont("Helvetica", 8)
    c.drawString(LM, p.y,
                 "11   Only in the case of illiterate Claimant (Pensioner) — "
                 "Left Hand Finger Impression")
    p.y -= 5 * mm
    fw = CW / 5
    p.grid([fw] * 5, [["Thumb", "Index", "Middle", "Ring", "Small"],
                      ["", "", "", "", ""]], h=8 * mm)
    # extra tall empty row for impressions
    p.grid([fw] * 5, [["", "", "", "", ""]], h=18 * mm, header_bold=False)
    p.y -= 12 * mm
    c.setFont("Helvetica", 9)
    c.drawString(LM, p.y, f"Date: {_dt(_s(d, 'dc_f8_date'))}")
    c.drawString(W / 2 + 10 * mm, p.y, "Signature: ______________________")
    p.y -= 8 * mm
    c.drawString(LM, p.y, f"Place: {_s(d, 'dc_f8_place')}")
    p.y -= 16 * mm
    c.drawRightString(W - RM, p.y, "Name of the Attesting Authority")
    p.y -= 5 * mm
    c.drawRightString(W - RM, p.y, "Official Seal")


def build_form8_pdf(d: Dict[str, Any]) -> bytes:
    p = _Pdf()
    _form8_page(p, d)      # copy 1
    p.c.showPage()
    _form8_page(p, d)      # copy 2 (submitted in duplicate)
    return p.done()
