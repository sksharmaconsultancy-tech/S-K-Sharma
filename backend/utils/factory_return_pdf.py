"""Iter 499 — Factory / Boiler Annual Return PDF (government-style Form).

Portrait A4, structured like the statutory annual return under the
Factories Act, 1948 (and Indian Boilers Act, 1923 for the boiler variant):
Part A particulars, Part B employment & wages, Part C leave/OT, Part D
accidents, Part E welfare facilities, signature block.
"""
from typing import Any, Dict, List

import io

from reportlab.lib import colors as rl
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

_M = 14 * mm
H1 = ParagraphStyle("h1", fontSize=13, leading=16, alignment=1,
                    fontName="Helvetica-Bold")
H2 = ParagraphStyle("h2", fontSize=9.5, leading=12, alignment=1,
                    textColor=rl.HexColor("#334155"))
SEC = ParagraphStyle("sec", fontSize=10.5, leading=13,
                     fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=3,
                     textColor=rl.HexColor("#1E3A8A"))
CELL = ParagraphStyle("cell", fontSize=8.5, leading=10.5)

GRID = [
    ("GRID", (0, 0), (-1, -1), 0.4, rl.HexColor("#94A3B8")),
    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
]
HEAD = [("BACKGROUND", (0, 0), (-1, 0), rl.HexColor("#1E3A8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), rl.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]


def _kv_table(pairs: List[List[str]], widths):
    t = Table([[Paragraph(f"<b>{a}</b>", CELL), Paragraph(str(b or "—"), CELL)]
               for a, b in pairs], colWidths=widths)
    t.setStyle(TableStyle(GRID))
    return t


def build_factory_return_pdf(d: Dict[str, Any], boiler: bool = False) -> bytes:
    f, s = d["firm"], d["summary"]
    year = d["year"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=_M, rightMargin=_M,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Annual Return {year}")
    W = A4[0] - 2 * _M
    flow: List[Any] = []

    if boiler:
        flow.append(Paragraph("ANNUAL RETURN — BOILERS", H1))
        flow.append(Paragraph(
            f"(Under the Indian Boilers Act, 1923 and Rules) — Calendar Year {year}", H2))
    else:
        flow.append(Paragraph("ANNUAL RETURN", H1))
        flow.append(Paragraph(
            f"(Under the Factories Act, 1948 and State Factories Rules) — Calendar Year {year}", H2))
    flow.append(Paragraph(
        f"Data source: {d['source'].upper()} (current + imported legacy records merged without duplication)"
        if d["source"] == "combined" else f"Data source: {d['source'].upper()}", H2))
    flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph("PART A — PARTICULARS OF THE FACTORY", SEC))
    pairs = [
        ["1. Name of the Factory", f.get("factory_name")],
        ["2. Address", f.get("factory_address")],
        ["3. Factory License No.", f.get("factory_license_no")],
        ["4. Registration No.", f.get("factory_registration_no")],
    ]
    if boiler:
        pairs.append(["5. Boiler Registration No.", f.get("boiler_registration_no")])
    pairs += [
        [f"{6 if boiler else 5}. Name of the Occupier", f.get("occupier_name")],
        [f"{7 if boiler else 6}. Name of the Factory Manager", f.get("factory_manager")],
        [f"{8 if boiler else 7}. Nature of Manufacturing / Industry",
         f.get("nature_of_manufacturing")],
        [f"{9 if boiler else 8}. District / State",
         f"{f.get('district') or '—'} / {f.get('state') or '—'}"],
    ]
    flow.append(_kv_table(pairs, [W * 0.42, W * 0.58]))

    flow.append(Paragraph("PART B — EMPLOYMENT & WAGES", SEC))
    flow.append(_kv_table([
        ["Average number of workers employed daily", s["avg_daily_employment"]],
        ["Maximum number employed on any day", s["max_employment"]],
        ["Male / Female workers", f"{s['male']} / {s['female']}"],
        ["Contract labour employed", s["contract_labour"]],
        ["Total workers employed during the year", s["employees_total"]],
        ["Total man-days worked", s["total_man_days"]],
        ["Total wages paid (Rs.)", f"{s['total_wages']:,.2f}"],
    ], [W * 0.6, W * 0.4]))

    # monthly table
    rows = [["Month", "Workers", "Man Days", "Avg Daily", "Wages (Rs.)",
             "OT Hrs", "OT (Rs.)", "Leave"]]
    for m in d["monthly"]:
        rows.append([m["month"], m["employees"], m["man_days"],
                     m["avg_daily_employment"], f"{m['wages']:,.0f}",
                     m["ot_hours"], f"{m['ot_amount']:,.0f}", m["leave_days"]])
    if len(rows) > 1:
        t = Table(rows, colWidths=[W * w for w in
                                   (0.14, 0.11, 0.13, 0.12, 0.18, 0.10, 0.12, 0.10)],
                  repeatRows=1)
        t.setStyle(TableStyle(GRID + HEAD + [
            ("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
        flow.append(Spacer(1, 2 * mm))
        flow.append(t)

    flow.append(Paragraph("PART C — OVERTIME & LEAVE WITH WAGES", SEC))
    flow.append(_kv_table([
        ["Total overtime hours worked", s["total_ot_hours"]],
        ["Total overtime wages paid (Rs.)", f"{s['total_ot_amount']:,.2f}"],
        ["Leave with wages availed (days)", s["leave_with_wages"]],
    ], [W * 0.6, W * 0.4]))

    acc = d.get("accidents") or {}
    flow.append(Paragraph("PART D — ACCIDENT STATISTICS", SEC))
    flow.append(_kv_table([
        ["Fatal accidents", acc.get("fatal", 0)],
        ["Non-fatal accidents", acc.get("nonfatal", 0)],
        ["Man-days lost due to accidents", acc.get("mandays_lost", 0)],
    ], [W * 0.6, W * 0.4]))

    wf = d.get("welfare") or {}
    flow.append(Paragraph("PART E — WELFARE FACILITIES", SEC))
    lbl = {"canteen": "Canteen", "rest_room": "Rest / Lunch Room",
           "creche": "Crèche", "first_aid": "First-aid Boxes",
           "ambulance_room": "Ambulance Room",
           "drinking_water": "Drinking Water", "washing_facility": "Washing Facility"}
    flow.append(_kv_table(
        [[v, "Provided" if wf.get(k) else "Not Provided"] for k, v in lbl.items()],
        [W * 0.6, W * 0.4]))

    # dept / category summaries
    for title, arr in [("DEPARTMENT-WISE SUMMARY", d["departments"]),
                       ("CATEGORY-WISE SUMMARY", d["categories"])]:
        if not arr:
            continue
        flow.append(Paragraph(title, SEC))
        rows = [["Name", "Workers", "Man Days", "Wages (Rs.)"]]
        for r in arr:
            rows.append([r["name"], r["employees"], r["man_days"],
                         f"{r['wages']:,.0f}"])
        t = Table(rows, colWidths=[W * 0.46, W * 0.16, W * 0.18, W * 0.20],
                  repeatRows=1)
        t.setStyle(TableStyle(GRID + HEAD + [("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
        flow.append(t)

    flow.append(Spacer(1, 14 * mm))
    sig = Table([[
        Paragraph("_____________________<br/>Signature of Occupier<br/>"
                  f"({f.get('occupier_name') or ''})", CELL),
        Paragraph("_____________________<br/>Signature of Factory Manager<br/>"
                  f"({f.get('factory_manager') or ''})", CELL),
    ]], colWidths=[W / 2, W / 2])
    sig.setStyle(TableStyle([("ALIGN", (0, 0), (0, 0), "LEFT"),
                             ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    flow.append(sig)
    doc.build(flow)
    return buf.getvalue()
