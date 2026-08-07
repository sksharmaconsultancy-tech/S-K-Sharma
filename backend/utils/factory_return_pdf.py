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


def _gender_table(label: str, vals: Dict[str, Any], W: float,
                  cols=("men", "women", "children", "total"),
                  heads=("Men", "Women", "Children", "Total")):
    rows = [[Paragraph(f"<b>{label}</b>", CELL)] + [Paragraph(f"<b>{h}</b>", CELL) for h in heads],
            [""] + [str(vals.get(c, 0)) for c in cols]]
    t = Table(rows, colWidths=[W * 0.44] + [W * 0.14] * len(cols))
    t.setStyle(TableStyle(GRID + [
        ("SPAN", (0, 0), (0, 1)),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("BACKGROUND", (1, 0), (-1, 0), rl.HexColor("#E2E8F0")),
    ]))
    return t


def build_form23_pdf(d: Dict[str, Any]) -> bytes:
    """Iter 520 (user upload — official format) — FORM NO. 23 Annual
    Return (Rule 105(i)) with the Payment of Wages Act, 1936 section."""
    f, year = d["firm"], d["year"]
    f23 = d.get("form23") or {}
    man = f23.get("manual") or {}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=_M, rightMargin=_M,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Form 23 Annual Return {year}")
    W = A4[0] - 2 * _M
    flow: List[Any] = []
    flow.append(Paragraph("FORM NO. 23", H1))
    flow.append(Paragraph("[Prescribed under Rule 105(i)] — ANNUAL RETURN "
                          f"for the year ending 31st December, {year}", H2))
    flow.append(Spacer(1, 3 * mm))

    flow.append(Paragraph("GENERAL INFORMATION", SEC))
    flow.append(_kv_table([
        ["Application No.", man.get("application_no")],
        ["Registration No.", f.get("factory_registration_no")],
        ["Name of the Factory", f.get("factory_name")],
        ["Name of the Occupier", f.get("occupier_name")],
        ["Name of the Manager", f.get("factory_manager")],
        ["District", f.get("district")],
        ["Area", man.get("area")],
        ["Address", f.get("factory_address")],
        ["Nature of Industry", f.get("nature_of_manufacturing")],
    ], [W * 0.42, W * 0.58]))

    flow.append(Paragraph(
        "NUMBER OF WORKERS AND PARTICULARS OF EMPLOYMENT", SEC))
    flow.append(_kv_table([
        ["1. Number of days worked in the year", f23.get("days_worked", 0)],
    ], [W * 0.6, W * 0.4]))
    flow.append(Spacer(1, 1.5 * mm))
    flow.append(_gender_table("2. Number of man-days worked during the year",
                              f23.get("man_days") or {}, W))
    flow.append(Spacer(1, 1.5 * mm))
    flow.append(_gender_table(
        "3. Average number of workers employed daily (Adults)",
        f23.get("avg_daily") or {}, W))
    flow.append(Spacer(1, 1.5 * mm))
    flow.append(_gender_table(
        "4. Total number of man-hours worked including overtime",
        f23.get("man_hours") or {}, W))
    flow.append(Spacer(1, 1.5 * mm))
    awh = f23.get("avg_week_hours") or {}
    flow.append(_kv_table([
        ["5. Average number of hours worked per week (Men / Women)",
         f"{awh.get('men', 0)} / {awh.get('women', 0)}"],
        ["6. Dangerous process / operation under Section 87 (Rule 100)",
         man.get("dangerous_process") or "No Dangerous Operation"],
    ], [W * 0.6, W * 0.4]))

    flow.append(Paragraph("LEAVE WITH WAGES", SEC))
    lv = f23.get("leave") or {}
    flow.append(_gender_table("1. Total number of workers employed during the year",
                              lv.get("employed") or {}, W))
    flow.append(Spacer(1, 1.5 * mm))
    flow.append(_gender_table(
        "2. Workers entitled to annual leave with wages",
        lv.get("entitled") or {}, W))
    flow.append(Spacer(1, 1.5 * mm))
    flow.append(_gender_table("3. Workers who were granted leave during the year",
                              lv.get("granted") or {}, W))
    flow.append(Spacer(1, 1.5 * mm))
    flow.append(_kv_table([
        ["4. Workers discharged / dismissed / quit / superannuated / died in service",
         man.get("left_service") or "0"],
        ["5. Workers in respect of whom wages in lieu of leave were paid",
         man.get("wages_in_lieu_paid") or "0"],
    ], [W * 0.6, W * 0.4]))

    flow.append(Paragraph("SAFETY & WELFARE (Sections 40-B, 45–49)", SEC))
    flow.append(_kv_table([
        ["Safety Officers required (Sec 40-B) / appointed",
         f"{man.get('safety_officers_required') or 0} / {man.get('safety_officers_appointed') or 0}"],
        ["Ambulance Room provided (Sec 45)?", man.get("ambulance_room") or "NA"],
        ["Canteen provided (Sec 46)?", man.get("canteen") or "NA"],
        ["Canteen managed — (i) Departmentally / (ii) Through contractor",
         f"{man.get('canteen_departmental') or 'NA'} / {man.get('canteen_contractor') or 'NA'}"],
        ["Adequate shelters / rest rooms (Sec 47)?", man.get("rest_rooms") or "NA"],
        ["Adequate lunch rooms (Sec 47)?", man.get("lunch_rooms") or "NA"],
        ["Crèche provided (Sec 48)?", man.get("creche") or "NA"],
        ["Welfare Officers required (Sec 49) / appointed",
         f"{man.get('welfare_officers_required') or 0} / {man.get('welfare_officers_appointed') or 0}"],
    ], [W * 0.6, W * 0.4]))

    acc = d.get("accidents") or {}
    flow.append(Paragraph("ACCIDENTS", SEC))
    flow.append(_kv_table([
        ["1. Total accidents — (i) Fatal / (ii) Non-fatal",
         f"{acc.get('fatal', 0)} / {acc.get('nonfatal', 0)}"],
        ["2(i). Accidents in which injured workers returned to work in the "
         "SAME year — (aa) accidents / (bb) man-days lost",
         f"{man.get('acc_ret_same_count') or 0} / {man.get('acc_ret_same_mandays') or 0}"],
        ["2(ii). PREVIOUS-year accidents in which workers returned this "
         "year — (aa) accidents / (bb) man-days lost",
         f"{man.get('acc_ret_prev_count') or 0} / {man.get('acc_ret_prev_mandays') or 0}"],
        ["3. Accidents in which injured workers did NOT return during the "
         "year — accidents / man-days lost",
         f"{man.get('acc_not_ret_count') or 0} / {man.get('acc_not_ret_mandays') or 0}"],
    ], [W * 0.62, W * 0.38]))

    flow.append(Paragraph("SAFETY TRAINING", SEC))
    flow.append(_kv_table([
        ["Total safety trainings conducted during the year",
         man.get("safety_trainings") or 0],
        ["Workers provided safety training (Male / Female / Total)",
         f"{man.get('safety_trained_male') or 0} / {man.get('safety_trained_female') or 0} / "
         f"{(int(man.get('safety_trained_male') or 0) + int(man.get('safety_trained_female') or 0)) if str(man.get('safety_trained_male') or '0').isdigit() and str(man.get('safety_trained_female') or '0').isdigit() else '—'}"],
    ], [W * 0.6, W * 0.4]))

    wg = f23.get("wages") or {}
    flow.append(Paragraph(
        "WAGES AND DEDUCTIONS FROM WAGES (Payment of Wages Act, 1936)", SEC))
    flow.append(_kv_table([
        ["Registration No.", f.get("factory_registration_no")],
        ["Name of factory / establishment & postal address",
         f"{f.get('factory_name') or ''}, {f.get('factory_address') or ''}"],
        ["Industry", f.get("nature_of_manufacturing")],
        ["Number of days worked during the year", f23.get("days_worked", 0)],
        ["Average daily number of persons employed",
         (f23.get("avg_daily") or {}).get("total", 0)],
        ["Gross amount paid as remuneration (Rs.)", f"{wg.get('gross', 0):,.2f}"],
        ["  (b) Amount due to profit-sharing bonus (Rs.)",
         man.get("bonus_paid") or "0"],
        ["  (c) Money value of concessions (Rs.)",
         man.get("money_concessions") or "0"],
        ["Total wages paid — (a) Basic wages (Rs.)", f"{wg.get('basic', 0):,.2f}"],
        ["  (b) Dearness and other allowances in cash (Rs.)",
         f"{wg.get('da_allowances', 0):,.2f}"],
        ["  (c) Arrears of previous year paid during the year (Rs.)",
         wg.get("arrears", 0)],
        ["Deductions — (a) Fines (Rs.)", man.get("fines") or "0"],
        ["  (b) Deductions for damage or loss (Rs.)",
         man.get("deduction_damage") or "0"],
        ["  (c) Deductions for breach of contract (Rs.)",
         man.get("deduction_breach") or "0"],
    ], [W * 0.62, W * 0.38]))

    flow.append(Spacer(1, 8 * mm))
    flow.append(Paragraph(
        "Certified that the information furnished above is, to the best of "
        "my knowledge and belief, correct.", CELL))
    flow.append(Spacer(1, 12 * mm))
    sig = Table([[
        Paragraph(f"Date: ____________<br/>Place: {f.get('district') or '____________'}", CELL),
        Paragraph("_____________________<br/>Signature of the Occupier / Manager<br/>"
                  f"({f.get('occupier_name') or f.get('factory_manager') or ''})", CELL),
    ]], colWidths=[W / 2, W / 2])
    sig.setStyle(TableStyle([("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    flow.append(sig)
    doc.build(flow)
    return buf.getvalue()


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
