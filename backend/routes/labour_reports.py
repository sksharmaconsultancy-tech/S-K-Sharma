"""Iter 177 — Labour Law Compliance Reports Module (Phase A + B).

One generic engine powers 22 statutory attendance reports (Daily
Attendance Register, Muster Roll, OT Register, Late Coming, ... ) over
the shared dataset: employees × attendance punches × attendance policy.

Common filters: company, branch/worksite, contractor, department,
designation, employee category (employee_type), gender, shift,
month/year or explicit date range.

Every export carries the statutory header block: company logo + details,
generated date/time (IST) + generated-by, page numbers and a QR
verification code (stored in ``report_verifications``).

Endpoints:
  * GET  /api/admin/labour-reports/catalogue
  * POST /api/admin/labour-reports/generate   (format: json|csv|excel|pdf)
  * GET  /api/admin/labour-reports/verify/{verify_id}
"""
import base64
import csv
import io
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import db, get_user_from_token, require_role, now_iso  # noqa: E402

router = APIRouter(prefix="/api/admin/labour-reports", tags=["labour-reports"])

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Report catalogue
# ---------------------------------------------------------------------------
CATALOGUE: List[Dict[str, str]] = [
    {"key": "daily_attendance", "label": "Daily Attendance Register", "group": "Registers"},
    {"key": "muster_roll", "label": "Muster Roll (Form 25 style)", "group": "Registers"},
    {"key": "monthly_register", "label": "Monthly Attendance Register", "group": "Registers"},
    {"key": "overtime_register", "label": "Overtime Register", "group": "Registers"},
    {"key": "present_absent", "label": "Present / Absent Report", "group": "Daily Reports"},
    {"key": "late_coming", "label": "Late Coming Report", "group": "Daily Reports"},
    {"key": "early_going", "label": "Early Going Report", "group": "Daily Reports"},
    {"key": "miss_punch", "label": "Miss Punch Report", "group": "Daily Reports"},
    {"key": "in_out_punch", "label": "In-Out Punch Report", "group": "Daily Reports"},
    {"key": "half_day", "label": "Half Day Report", "group": "Daily Reports"},
    {"key": "shift_report", "label": "Shift Report", "group": "Shift Reports"},
    {"key": "night_shift", "label": "Night Shift Report", "group": "Shift Reports"},
    {"key": "double_shift", "label": "Double Shift Report", "group": "Shift Reports"},
    {"key": "weekly_off", "label": "Weekly Off Worked Report", "group": "Shift Reports"},
    {"key": "holiday_attendance", "label": "Holiday Attendance Report", "group": "Shift Reports"},
    {"key": "geofence_attendance", "label": "Geofence Attendance Report", "group": "Technology Reports"},
    {"key": "gps_attendance", "label": "GPS Attendance Report", "group": "Technology Reports"},
    {"key": "face_attendance", "label": "Face Recognition Attendance", "group": "Technology Reports"},
    {"key": "qr_attendance", "label": "QR Attendance Report", "group": "Technology Reports"},
    {"key": "biometric_attendance", "label": "Biometric (Device) Attendance", "group": "Technology Reports"},
    {"key": "device_wise", "label": "Device Wise Attendance", "group": "Technology Reports"},
    {"key": "location_wise", "label": "Location / Worksite Wise Attendance", "group": "Technology Reports"},
]
CAT_KEYS = {c["key"] for c in CATALOGUE}


async def _auth(authorization: Optional[str], company_id: str):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    if admin.get("role") == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorised for this firm")
    return admin


# ---------------------------------------------------------------------------
# Shared dataset loader
# ---------------------------------------------------------------------------
def _hhmm(iso: Optional[str]) -> str:
    return iso[11:16] if iso and len(iso) >= 16 else ""


def _mins(hhmm: str) -> Optional[int]:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _dates_between(d1: str, d2: str) -> List[str]:
    a = date.fromisoformat(d1)
    b = date.fromisoformat(d2)
    out = []
    while a <= b:
        out.append(a.isoformat())
        a += timedelta(days=1)
    return out


async def _load_dataset(company_id: str, filters: Dict[str, Any]):
    """Employees (after master filters) + attendance day summaries."""
    # --- date range ---
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    month = filters.get("month")  # "YYYY-MM"
    if month and not (from_date and to_date):
        y, m = int(month[:4]), int(month[5:7])
        from_date = f"{y:04d}-{m:02d}-01"
        nxt = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
        to_date = (nxt - timedelta(days=1)).isoformat()
    if not from_date or not to_date:
        raise HTTPException(status_code=400, detail="Provide month or from_date/to_date")
    if (date.fromisoformat(to_date) - date.fromisoformat(from_date)).days > 62:
        raise HTTPException(status_code=400, detail="Date range too large (max 62 days)")

    # --- employees ---
    q: Dict[str, Any] = {"company_id": company_id, "role": "employee"}
    for f_key, u_key in (
        ("department", "department"), ("designation", "designation"),
        ("employee_category", "employee_type"), ("gender", "gender"),
        ("contractor", "contractor_name"),
    ):
        v = (filters.get(f_key) or "").strip()
        if v:
            q[u_key] = {"$regex": f"^{v}$", "$options": "i"}
    emps = await db.users.find(q, {
        "_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "department": 1,
        "designation": 1, "employee_type": 1, "gender": 1, "contractor_name": 1,
        "shift_start": 1, "shift_end": 1, "father_name": 1, "is_contractual": 1,
    }).sort("employee_code", 1).to_list(5000)
    shift_f = (filters.get("shift") or "").strip()
    if shift_f:
        emps = [e for e in emps
                if f"{e.get('shift_start') or ''}-{e.get('shift_end') or ''}" == shift_f
                or (e.get("shift_start") or "") == shift_f]
    uids = [e["user_id"] for e in emps]

    # --- attendance (approved only — statutory registers) ---
    aq: Dict[str, Any] = {
        "company_id": company_id, "user_id": {"$in": uids},
        "date": {"$gte": from_date, "$lte": to_date},
        "kind": {"$in": ["in", "out"]},
        "status": {"$nin": ["rejected", "pending"]},
    }
    branch = (filters.get("branch_id") or "").strip()
    if branch:
        aq["$or"] = [{"branch_id": branch}, {"worksite_id": branch}]
    recs_by: Dict[tuple, List[dict]] = defaultdict(list)
    async for r in db.attendance.find(aq, {
        "_id": 0, "user_id": 1, "date": 1, "kind": 1, "at": 1, "source": 1,
        "biometric_method": 1, "distance_m": 1, "outside_geofence": 1,
        "latitude": 1, "longitude": 1, "device_info": 1,
        "branch_name": 1, "worksite_name": 1, "gps_verified": 1,
    }).sort("at", 1):
        recs_by[(r["user_id"], r["date"])].append(r)

    # --- policy ---
    policy = await db.attendance_policies.find_one(
        {"company_id": company_id}, {"_id": 0}) or {}

    dates = _dates_between(from_date, to_date)
    return emps, recs_by, policy, dates, from_date, to_date


def _day_summary(recs: List[dict], policy: dict, emp: dict) -> dict:
    ins = [r for r in recs if r["kind"] == "in"]
    outs = [r for r in recs if r["kind"] == "out"]
    first_in = _hhmm(ins[0]["at"]) if ins else ""
    last_out = _hhmm(outs[-1]["at"]) if outs else ""
    hours = 0.0
    # pair sequentially
    pairs = 0
    stack = None
    for r in recs:
        if r["kind"] == "in":
            stack = r
        elif r["kind"] == "out" and stack is not None:
            m1, m2 = _mins(_hhmm(stack["at"])), _mins(_hhmm(r["at"]))
            if m1 is not None and m2 is not None and m2 >= m1:
                hours += (m2 - m1) / 60.0
                pairs += 1
            stack = None
    shift_start = emp.get("shift_start") or policy.get("shift_start") or "09:00"
    shift_end = emp.get("shift_end") or policy.get("shift_end") or "18:00"
    grace = int(policy.get("grace_minutes_late") or 0)
    late_by = 0
    if first_in:
        a, b = _mins(first_in), _mins(shift_start)
        if a is not None and b is not None and a > b + grace:
            late_by = a - b
    early_by = 0
    if last_out:
        a, b = _mins(last_out), _mins(shift_end)
        if a is not None and b is not None and a < b:
            early_by = b - a
    full_h = float(policy.get("full_day_hours") or policy.get("standard_working_hours") or 8.0)
    half_h = float(policy.get("half_day_hours") or 4.0)
    ot_threshold = float(policy.get("overtime_threshold_hours") or full_h)
    ot_hours = max(0.0, hours - ot_threshold) if hours else 0.0
    status = "A"
    if recs:
        status = "P" if hours >= half_h or (ins and not outs) else "HD"
        if hours and hours < half_h:
            status = "HD"
    miss = bool((ins and not outs) or (outs and not ins))
    return {
        "first_in": first_in, "last_out": last_out, "hours": round(hours, 2),
        "pairs": pairs, "late_by": late_by, "early_by": early_by,
        "ot_hours": round(ot_hours, 2), "status": status, "miss": miss,
        "recs": recs,
    }


# ---------------------------------------------------------------------------
# Report builders — return (columns, rows)
# ---------------------------------------------------------------------------
def _emp_cols(e: dict) -> List[str]:
    return [str(e.get("employee_code") or ""), e.get("name") or "",
            e.get("department") or "", e.get("designation") or ""]


EMP_HEAD = ["Code", "Employee Name", "Department", "Designation"]


def build_report(key: str, emps, recs_by, policy, dates) -> tuple:
    weekly_offs = set(policy.get("weekly_off_days") or [])
    night_start = policy.get("night_shift_start") or "22:00"
    night_end = policy.get("night_shift_end") or "06:00"
    holidays = set(policy.get("holidays") or [])

    def day_rows(pred, extra_cols, extra_vals):
        cols = ["Date"] + EMP_HEAD + ["In", "Out", "Hours"] + extra_cols
        rows = []
        for d in dates:
            for e in emps:
                recs = recs_by.get((e["user_id"], d))
                if not recs:
                    continue
                s = _day_summary(recs, policy, e)
                if not pred(s, d, e):
                    continue
                rows.append([d] + _emp_cols(e) + [s["first_in"], s["last_out"], s["hours"]]
                            + extra_vals(s, d, e))
        return cols, rows

    if key == "daily_attendance":
        return day_rows(lambda s, d, e: True, ["OT Hrs", "Status"],
                        lambda s, d, e: [s["ot_hours"], s["status"]])

    if key == "in_out_punch":
        cols = ["Date"] + EMP_HEAD + ["Punch Time", "Type", "Source", "Method"]
        rows = []
        for d in dates:
            for e in emps:
                for r in recs_by.get((e["user_id"], d), []):
                    rows.append([d] + _emp_cols(e) + [
                        _hhmm(r["at"]), r["kind"].upper(),
                        (r.get("source") or "")[:24], r.get("biometric_method") or ""])
        return cols, rows

    if key == "muster_roll":
        day_nums = [d[8:10] for d in dates]
        cols = EMP_HEAD[:2] + ["Father Name"] + day_nums + ["P", "HD", "A", "WO"]
        rows = []
        for e in emps:
            marks, p, hd, a, wo = [], 0, 0, 0, 0
            for d in dates:
                wd = date.fromisoformat(d).weekday()
                recs = recs_by.get((e["user_id"], d))
                if recs:
                    s = _day_summary(recs, policy, e)
                    marks.append(s["status"])
                    p += s["status"] == "P"
                    hd += s["status"] == "HD"
                elif wd in weekly_offs:
                    marks.append("WO")
                    wo += 1
                elif d in holidays:
                    marks.append("H")
                else:
                    marks.append("A")
                    a += 1
            rows.append(_emp_cols(e)[:2] + [e.get("father_name") or ""] + marks + [p, hd, a, wo])
        return cols, rows

    if key == "monthly_register":
        cols = EMP_HEAD + ["Present", "Half Days", "Absent", "WO", "Total Hours", "OT Hours", "Late Days"]
        rows = []
        for e in emps:
            p = hd = a = wo = late = 0
            th = ot = 0.0
            for d in dates:
                wd = date.fromisoformat(d).weekday()
                recs = recs_by.get((e["user_id"], d))
                if recs:
                    s = _day_summary(recs, policy, e)
                    p += s["status"] == "P"
                    hd += s["status"] == "HD"
                    th += s["hours"]
                    ot += s["ot_hours"]
                    late += 1 if s["late_by"] > 0 else 0
                elif wd in weekly_offs:
                    wo += 1
                else:
                    a += 1
            rows.append(_emp_cols(e) + [p, hd, a, wo, round(th, 1), round(ot, 1), late])
        return cols, rows

    if key == "present_absent":
        cols = ["Date", "Present", "Half Day", "Absent", "Present Names (codes)"]
        rows = []
        for d in dates:
            p_list, hd_c, a_c = [], 0, 0
            for e in emps:
                recs = recs_by.get((e["user_id"], d))
                if recs:
                    s = _day_summary(recs, policy, e)
                    if s["status"] == "P":
                        p_list.append(str(e.get("employee_code") or e.get("name")))
                    else:
                        hd_c += 1
                else:
                    a_c += 1
            rows.append([d, len(p_list), hd_c, a_c, ", ".join(p_list[:40])])
        return cols, rows

    if key == "late_coming":
        return day_rows(lambda s, d, e: s["late_by"] > 0, ["Late By (min)"],
                        lambda s, d, e: [s["late_by"]])
    if key == "early_going":
        return day_rows(lambda s, d, e: s["early_by"] > 0 and s["last_out"], ["Early By (min)"],
                        lambda s, d, e: [s["early_by"]])
    if key == "miss_punch":
        return day_rows(lambda s, d, e: s["miss"], ["Missing"],
                        lambda s, d, e: ["OUT missing" if s["first_in"] and not s["last_out"] else "IN missing"])
    if key == "half_day":
        return day_rows(lambda s, d, e: s["status"] == "HD", ["Shortfall"],
                        lambda s, d, e: [f"{s['hours']}h worked"])
    if key == "overtime_register":
        return day_rows(lambda s, d, e: s["ot_hours"] > 0, ["OT Hours", "Normal Hours"],
                        lambda s, d, e: [s["ot_hours"], round(s["hours"] - s["ot_hours"], 2)])
    if key == "double_shift":
        return day_rows(lambda s, d, e: s["pairs"] >= 2, ["Shifts (in-out cycles)"],
                        lambda s, d, e: [s["pairs"]])
    if key == "shift_report":
        cols = ["Shift"] + EMP_HEAD + ["Days Present", "Total Hours"]
        rows = []
        for e in emps:
            shift = f"{e.get('shift_start') or '—'} – {e.get('shift_end') or '—'}"
            p, th = 0, 0.0
            for d in dates:
                recs = recs_by.get((e["user_id"], d))
                if recs:
                    s = _day_summary(recs, policy, e)
                    p += 1 if s["status"] in ("P", "HD") else 0
                    th += s["hours"]
            if p:
                rows.append([shift] + _emp_cols(e) + [p, round(th, 1)])
        rows.sort(key=lambda r: r[0])
        return cols, rows
    if key == "night_shift":
        ns, ne = _mins(night_start) or 1320, _mins(night_end) or 360
        def is_night(s, d, e):
            m = _mins(s["first_in"])
            return m is not None and (m >= ns or m <= ne)
        return day_rows(is_night, ["Night Window"], lambda s, d, e: [f"{night_start}–{night_end}"])
    if key == "weekly_off":
        return day_rows(
            lambda s, d, e: date.fromisoformat(d).weekday() in weekly_offs,
            ["Day"], lambda s, d, e: [date.fromisoformat(d).strftime("%A")])
    if key == "holiday_attendance":
        return day_rows(lambda s, d, e: d in holidays, ["Holiday"],
                        lambda s, d, e: [d])
    if key == "geofence_attendance":
        cols = ["Date"] + EMP_HEAD + ["Punch", "Time", "Distance (m)", "Inside Geofence"]
        rows = []
        for d in dates:
            for e in emps:
                for r in recs_by.get((e["user_id"], d), []):
                    if r.get("distance_m") is None:
                        continue
                    rows.append([d] + _emp_cols(e) + [
                        r["kind"].upper(), _hhmm(r["at"]), r.get("distance_m"),
                        "No" if r.get("outside_geofence") else "Yes"])
        return cols, rows
    if key == "gps_attendance":
        cols = ["Date"] + EMP_HEAD + ["Punch", "Time", "Latitude", "Longitude", "GPS Verified"]
        rows = []
        for d in dates:
            for e in emps:
                for r in recs_by.get((e["user_id"], d), []):
                    if r.get("latitude") is None:
                        continue
                    rows.append([d] + _emp_cols(e) + [
                        r["kind"].upper(), _hhmm(r["at"]),
                        round(r["latitude"], 5), round(r["longitude"], 5),
                        "Yes" if r.get("gps_verified") else "No"])
        return cols, rows
    if key == "face_attendance":
        return day_rows(
            lambda s, d, e: any(r.get("biometric_method") == "face" for r in s["recs"]),
            ["Method"], lambda s, d, e: ["Face Recognition"])
    if key == "qr_attendance":
        cols = ["Date"] + EMP_HEAD + ["Punch", "Time", "Source"]
        rows = []
        for d in dates:
            for e in emps:
                for r in recs_by.get((e["user_id"], d), []):
                    if "qr" not in (r.get("source") or "").lower():
                        continue
                    rows.append([d] + _emp_cols(e) + [r["kind"].upper(), _hhmm(r["at"]), r.get("source")])
        return cols, rows
    if key == "biometric_attendance":
        cols = ["Date"] + EMP_HEAD + ["Punch", "Time", "Device Source"]
        rows = []
        for d in dates:
            for e in emps:
                for r in recs_by.get((e["user_id"], d), []):
                    src = (r.get("source") or "").lower()
                    if not ("zk" in src or "import" in src or "device" in src or "biometric" in src):
                        continue
                    rows.append([d] + _emp_cols(e) + [r["kind"].upper(), _hhmm(r["at"]), r.get("source")])
        return cols, rows
    if key == "device_wise":
        cols = ["Device / Source", "Punches", "Employees", "Dates Covered"]
        agg: Dict[str, dict] = defaultdict(lambda: {"punches": 0, "emps": set(), "dates": set()})
        for (uid, d), recs in recs_by.items():
            for r in recs:
                k2 = (r.get("source") or "app").split("_")[0][:32]
                agg[k2]["punches"] += 1
                agg[k2]["emps"].add(uid)
                agg[k2]["dates"].add(d)
        rows = [[k2, v["punches"], len(v["emps"]), len(v["dates"])]
                for k2, v in sorted(agg.items())]
        return cols, rows
    if key == "location_wise":
        cols = ["Location / Worksite", "Punches", "Employees", "Dates Covered"]
        agg2: Dict[str, dict] = defaultdict(lambda: {"punches": 0, "emps": set(), "dates": set()})
        for (uid, d), recs in recs_by.items():
            for r in recs:
                k2 = r.get("worksite_name") or r.get("branch_name") or "Main Office"
                agg2[k2]["punches"] += 1
                agg2[k2]["emps"].add(uid)
                agg2[k2]["dates"].add(d)
        rows = [[k2, v["punches"], len(v["emps"]), len(v["dates"])]
                for k2, v in sorted(agg2.items())]
        return cols, rows

    raise HTTPException(status_code=400, detail=f"Unknown report: {key}")


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------
def _csv_bytes(columns, rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8-sig")


def _excel_bytes(title, header_lines, columns, rows) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    r_i = 1
    for line in header_lines:
        ws.cell(row=r_i, column=1, value=line).font = Font(bold=(r_i <= 2), size=12 if r_i == 1 else 10)
        r_i += 1
    r_i += 1
    for c_i, c in enumerate(columns, start=1):
        cell = ws.cell(row=r_i, column=c_i, value=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1D4ED8")
    for row in rows:
        r_i += 1
        for c_i, v in enumerate(row, start=1):
            ws.cell(row=r_i, column=c_i, value=v)
    for c_i in range(1, len(columns) + 1):
        ws.column_dimensions[ws.cell(row=1, column=c_i).column_letter].width = 16
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _pdf_bytes(title, company, header_meta, columns, rows, verify_id) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.graphics.barcode import qr as rl_qr
    from reportlab.graphics.shapes import Drawing

    buf = io.BytesIO()
    page = landscape(A4) if len(columns) > 8 else A4

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(page[0] - 12 * mm, 8 * mm, f"Page {doc.page}")
        canvas.drawString(12 * mm, 8 * mm, f"Verify: {verify_id}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=page,
                            leftMargin=10 * mm, rightMargin=10 * mm,
                            topMargin=8 * mm, bottomMargin=14 * mm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=13, spaceAfter=1)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=7.5, leading=9.5)

    story: list = []
    # header row: logo | company block | QR
    logo_cell: Any = ""
    if company.get("logo_base64"):
        try:
            logo_cell = RLImage(io.BytesIO(base64.b64decode(company["logo_base64"])),
                                width=18 * mm, height=18 * mm)
        except Exception:
            logo_cell = ""
    qr_widget = rl_qr.QrCodeWidget(f"SKS-REPORT:{verify_id}")
    b = qr_widget.getBounds()
    dr = Drawing(18 * mm, 18 * mm,
                 transform=[18 * mm / (b[2] - b[0]), 0, 0, 18 * mm / (b[3] - b[1]), 0, 0])
    dr.add(qr_widget)
    comp_block = Paragraph(
        f"<b>{company.get('name') or ''}</b><br/>{company.get('address') or ''}<br/>"
        f"{header_meta}", small)
    head_tbl = Table(
        [[logo_cell, comp_block, dr]],
        colWidths=[22 * mm, page[0] - 20 * mm - 22 * mm - 22 * mm, 22 * mm])
    head_tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(head_tbl)
    story.append(Paragraph(title, h1))
    story.append(Spacer(1, 3))

    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=6.8, leading=8.2)
    data = [[Paragraph(f"<b>{c}</b>", cell_style) for c in columns]]
    for r in rows[:4000]:
        data.append([Paragraph(str(v), cell_style) for v in r])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#1D4ED8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.HexColor("#94A3B8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor("#F1F5F9")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/catalogue")
async def catalogue(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    return {"reports": CATALOGUE}


@router.post("/generate")
async def generate(payload: Dict[str, Any] = Body(...),
                   authorization: Optional[str] = Header(None)):
    company_id = str(payload.get("company_id") or "").strip()
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id required")
    admin = await _auth(authorization, company_id)
    key = str(payload.get("report_key") or "").strip()
    if key not in CAT_KEYS:
        raise HTTPException(status_code=400, detail="Unknown report_key")
    fmt = str(payload.get("format") or "json").lower()
    filters = payload.get("filters") or {}

    emps, recs_by, policy, dates, from_date, to_date = await _load_dataset(company_id, filters)
    columns, rows = build_report(key, emps, recs_by, policy, dates)
    label = next(c["label"] for c in CATALOGUE if c["key"] == key)

    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "address": 1, "logo_base64": 1})
    gen_at = datetime.now(IST).strftime("%d-%m-%Y %I:%M %p")
    gen_by = admin.get("name") or admin.get("email") or "Admin"
    verify_id = f"lrv_{uuid.uuid4().hex[:10]}"
    await db.report_verifications.insert_one({
        "verify_id": verify_id, "report_key": key, "company_id": company_id,
        "from_date": from_date, "to_date": to_date, "rows": len(rows),
        "generated_by": admin.get("user_id"), "generated_by_name": gen_by,
        "generated_at": now_iso(),
    })
    header_meta = (f"Period: {from_date} to {to_date} &nbsp;·&nbsp; "
                   f"Generated: {gen_at} IST &nbsp;·&nbsp; Generated by: {gen_by}")

    if fmt == "json":
        return {"report_key": key, "label": label, "columns": columns,
                "rows": rows[:2000], "total_rows": len(rows),
                "from_date": from_date, "to_date": to_date,
                "generated_at": gen_at, "generated_by": gen_by,
                "verify_id": verify_id}
    stem = f"{key}_{from_date}_{to_date}"
    if fmt == "csv":
        return {"filename": f"{stem}.csv",
                "file_base64": base64.b64encode(_csv_bytes(columns, rows)).decode()}
    if fmt == "excel":
        header_lines = [company.get("name") or "", label,
                        f"Period: {from_date} to {to_date}",
                        f"Generated: {gen_at} IST · By: {gen_by} · Verify: {verify_id}"]
        return {"filename": f"{stem}.xlsx",
                "file_base64": base64.b64encode(
                    _excel_bytes(label, header_lines, columns, rows)).decode()}
    if fmt == "pdf":
        return {"filename": f"{stem}.pdf",
                "file_base64": base64.b64encode(
                    _pdf_bytes(label, company or {}, header_meta, columns, rows, verify_id)).decode()}
    raise HTTPException(status_code=400, detail="format must be json|csv|excel|pdf")


@router.get("/verify/{verify_id}")
async def verify_report(verify_id: str):
    """Public verification endpoint for the QR code on printed reports."""
    doc = await db.report_verifications.find_one({"verify_id": verify_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Unknown verification code")
    return {"ok": True, "verification": doc}
