"""Iter 292 (user request) — Monthly Employee In/Out & Overtime Matrix Report.

A BRAND-NEW report (existing reports untouched): one employee per matrix,
rows = D-In / D-Out / OT-In / OT-Out / Total Hrs / OT Hrs, columns = days
of the month. Reuses the SAME compute pipeline as the on-screen Attendance
Grid (`_compute_monthly_grid_data`) so every figure matches 1:1.

Endpoints (all firm-scoped, super/sub/company admin):
  * GET /api/admin/reports/inout-ot-matrix          — JSON (paginated)
  * GET /api/admin/reports/inout-ot-matrix.xlsx     — Excel, colours preserved
  * GET /api/admin/reports/inout-ot-matrix.pdf      — A4 LANDSCAPE, one
        employee per page, header repeated on every page
  * GET /api/admin/reports/inout-ot-matrix.csv      — plain CSV

Colour legend (matches UI): OT=light blue, Late=yellow, Missing punch=red,
Holiday=grey, Weekly off=light green, Leave=orange, Normal=white.
"""
import csv
import io
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response

router = APIRouter(prefix="/api/admin/reports", tags=["inout-ot-matrix"])

ROW_KEYS = [
    ("d_in", "D-In"), ("d_out", "D-Out"), ("ot_in", "OT-In"),
    ("ot_out", "OT-Out"), ("total", "Total Hrs"), ("ot", "OT Hrs"),
]

# hex colours shared by xlsx + pdf so exports match the screen exactly
FLAG_COLORS = {
    "ot": "DBEAFE",        # light blue
    "late": "FEF08A",      # yellow
    "missing": "FECACA",   # red
    "holiday": "E2E8F0",   # grey
    "weekly_off": "DCFCE7",  # light green
    "leave": "FED7AA",     # orange
}


def _fmt_hm(hours: Any) -> str:
    """Float hours → HH:MM ('-' when zero/empty)."""
    try:
        h = float(hours or 0)
    except (TypeError, ValueError):
        return "-"
    if h <= 0:
        return "-"
    total_min = int(round(h * 60))
    return f"{total_min // 60:02d}:{total_min % 60:02d}"


def _cell_flag(cell: Dict[str, Any]) -> str:
    """Priority: missing > late > ot > leave > holiday > weekly_off > normal."""
    has_in, has_out = bool(cell.get("in")), bool(cell.get("out"))
    if (has_in and not has_out) or (has_out and not has_in):
        return "missing"
    if (cell.get("late_min") or 0) > 0:
        return "late"
    if float(cell.get("ot_hours") or 0) > 0:
        return "ot"
    if cell.get("leave"):
        return "leave"
    if not has_in and cell.get("holiday"):
        return "holiday"
    if not has_in and cell.get("weekly_off"):
        return "weekly_off"
    return "normal"


async def _auth(authorization: Optional[str], company_id: Optional[str]):
    from server import get_user_from_token, require_role, sub_admin_can_touch_company
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin.get("role") == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    if admin.get("role") == "sub_admin" and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm not in your scope")
    return admin, company_id


async def _build(
    company_id: str,
    month: str,
    department: Optional[str] = None,
    designation: Optional[str] = None,
    employee_type: Optional[str] = None,
    contractor: Optional[str] = None,
    shift: Optional[str] = None,
    q: Optional[str] = None,
    status: str = "all",
) -> Dict[str, Any]:
    """Compute the grid once, join extra master fields, apply filters and
    shape the per-employee 6-row matrix."""
    from server import db, _compute_monthly_grid_data
    data = await _compute_monthly_grid_data(company_id, month)
    day_labels: List[str] = data.get("day_labels") or []
    weekday_labels: List[str] = data.get("weekday_labels") or []

    # Extra master fields not present in the grid rows.
    extra: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find(
        {"role": "employee", "company_id": company_id},
        {"_id": 0, "user_id": 1, "employee_type": 1, "contractor_name": 1,
         "shift_name": 1, "department": 1, "designation": 1, "position": 1,
         "exit_date": 1, "employment_status": 1},
    ):
        extra[u["user_id"]] = u

    # Approved leaves for the month (marks the LEAVE colour). Collection may
    # be empty — that's fine.
    leave_days: Dict[str, set] = {}
    try:
        async for lr in db.leave_requests.find(
            {"company_id": company_id, "status": "approved"},
            {"_id": 0, "user_id": 1, "from_date": 1, "to_date": 1},
        ):
            f, t = str(lr.get("from_date") or ""), str(lr.get("to_date") or "")
            if f[:7] <= month <= t[:7]:
                leave_days.setdefault(lr["user_id"], set()).add((f, t))
    except Exception:
        pass

    def _on_leave(uid: str, iso: str) -> bool:
        for f, t in leave_days.get(uid, set()):
            if f <= iso <= t:
                return True
        return False

    term = (q or "").strip().lower()
    out_rows: List[Dict[str, Any]] = []
    for emp in data.get("employees") or []:
        ex = extra.get(emp.get("user_id"), {})
        dept = emp.get("department") or ex.get("department") or ""
        desig = emp.get("designation") or ex.get("designation") or ex.get("position") or ""
        etype = ex.get("employee_type") or ""
        contr = ex.get("contractor_name") or ""
        shf = ex.get("shift_name") or ""
        resigned = bool(ex.get("exit_date")) or str(
            ex.get("employment_status") or "").lower() in (
            "exited", "resigned", "terminated", "inactive", "left")
        if department and dept != department:
            continue
        if designation and desig != designation:
            continue
        if employee_type and etype != employee_type:
            continue
        if contractor and contr != contractor:
            continue
        if shift and shf != shift:
            continue
        if status == "active" and resigned:
            continue
        if status == "resigned" and not resigned:
            continue
        if term and term not in f"{emp.get('name', '')} {emp.get('employee_code', '')}".lower():
            continue

        days: Dict[str, Dict[str, Any]] = {}
        for i, dl in enumerate(day_labels):
            cell = (emp.get("days") or {}).get(dl) or {}
            iso = f"{month}-{str(dl)[:2]}" if len(str(dl)) >= 2 else ""
            leave = _on_leave(emp.get("user_id"), iso) if iso else False
            c = dict(cell)
            c["leave"] = leave
            flag = _cell_flag(c)
            days[dl] = {
                "d_in": cell.get("in") or "-",
                "d_out": cell.get("out") or "-",
                "ot_in": cell.get("ot_in") or "-",
                "ot_out": cell.get("ot_out") or "-",
                "total": _fmt_hm(cell.get("hours")),
                "ot": _fmt_hm(cell.get("ot_hours")),
                "flag": flag,
                # hover / click details
                "detail": {
                    "date": iso,
                    "weekday": weekday_labels[i] if i < len(weekday_labels) else "",
                    "punch_count": cell.get("punches") or 0,
                    "working_hours": _fmt_hm(cell.get("hours")),
                    "break_time": _fmt_hm(cell.get("break_hours")),
                    "late_min": cell.get("late_min") or 0,
                    "early_min": cell.get("early_min") or 0,
                    "ot_hours": _fmt_hm(cell.get("ot_hours")),
                    "sources": cell.get("sources") or [],
                },
            }
        totals = emp.get("totals") or {}
        out_rows.append({
            "user_id": emp.get("user_id"),
            "employee_code": emp.get("employee_code"),
            "name": emp.get("name"),
            "department": dept, "designation": desig,
            "category": etype, "contractor_name": contr, "shift_name": shf,
            "status": "RESIGNED" if resigned else "ACTIVE",
            "days": days,
            "month_total": _fmt_hm(totals.get("duty_hours")),
            "month_ot": _fmt_hm(totals.get("ot_hours")),
            "present_days": totals.get("present_days_policy",
                                       totals.get("present_days")),
        })

    company = data.get("company") or {}
    comp_doc = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "name": 1, "logo_base64": 1})
    y, m = month[:4], month[5:7]
    return {
        "company": {"company_id": company_id,
                    "name": (comp_doc or {}).get("name") or company.get("name"),
                    "logo_base64": (comp_doc or {}).get("logo_base64")},
        "month": month, "year": y, "month_number": m,
        "payroll_period": f"01-{m}-{y} to {len(day_labels):02d}-{m}-{y}",
        "day_labels": day_labels, "weekday_labels": weekday_labels,
        "employees": out_rows,
        "filter_options": {
            "departments": sorted({e.get("department") or "" for e in extra.values()} - {""}),
            "designations": sorted({(e.get("designation") or e.get("position") or "") for e in extra.values()} - {""}),
            "categories": sorted({e.get("employee_type") or "" for e in extra.values()} - {""}),
            "contractors": sorted({e.get("contractor_name") or "" for e in extra.values()} - {""}),
            "shifts": sorted({e.get("shift_name") or "" for e in extra.values()} - {""}),
        },
    }


_FILTER_PARAMS = dict()  # documentation only


@router.get("/inout-ot-matrix")
async def inout_ot_matrix_json(
    month: str,
    company_id: Optional[str] = None,
    department: Optional[str] = None,
    designation: Optional[str] = None,
    employee_type: Optional[str] = None,
    contractor: Optional[str] = None,
    shift: Optional[str] = None,
    q: Optional[str] = None,
    status: str = "all",
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    authorization: Optional[str] = Header(None),
):
    _, cid = await _auth(authorization, company_id)
    data = await _build(cid, month, department, designation, employee_type,
                        contractor, shift, q, status)
    emps = data.pop("employees")
    total = len(emps)
    start = (page - 1) * page_size
    data["employees"] = emps[start:start + page_size]
    data["total_employees"] = total
    data["page"] = page
    data["page_size"] = page_size
    data["total_pages"] = max(1, -(-total // page_size))
    return data


# ---------------------------------------------------------------------------
# Exports — layout mirrors the screen exactly.
# ---------------------------------------------------------------------------
def _header_lines(data: Dict[str, Any], emp: Dict[str, Any]) -> List[str]:
    c = data["company"]
    return [
        f"Company: {c.get('name') or ''}",
        f"Employee: {emp.get('employee_code') or ''} — {emp.get('name') or ''}",
        f"Department: {emp.get('department') or '-'}   Designation: {emp.get('designation') or '-'}   "
        f"Category: {emp.get('category') or '-'}"
        + (f"   Contractor: {emp['contractor_name']}" if emp.get("contractor_name") else ""),
        f"Shift: {emp.get('shift_name') or '-'}   Month: {data['month_number']}/{data['year']}   "
        f"Payroll Period: {data['payroll_period']}",
    ]


@router.get("/inout-ot-matrix.xlsx")
async def inout_ot_matrix_xlsx(
    month: str,
    company_id: Optional[str] = None,
    department: Optional[str] = None,
    designation: Optional[str] = None,
    employee_type: Optional[str] = None,
    contractor: Optional[str] = None,
    shift: Optional[str] = None,
    q: Optional[str] = None,
    status: str = "all",
    authorization: Optional[str] = Header(None),
):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    _, cid = await _auth(authorization, company_id)
    data = await _build(cid, month, department, designation, employee_type,
                        contractor, shift, q, status)
    emps = data["employees"][:150]  # keep workbooks manageable
    if not emps:
        raise HTTPException(status_code=404, detail="No employees match the filters")

    wb = Workbook()
    wb.remove(wb.active)
    thin = Border(*[Side(style="thin", color="CBD5E1")] * 4)
    center = Alignment(horizontal="center", vertical="center")
    used = set()
    for emp in emps:
        base = f"{emp.get('employee_code') or 'E'}"[:24] or "E"
        title = base
        n = 1
        while title in used:
            n += 1
            title = f"{base}-{n}"
        used.add(title)
        ws = wb.create_sheet(title=title)
        ws.page_setup.orientation = "landscape"
        r = 1
        for line in _header_lines(data, emp):
            ws.cell(row=r, column=1, value=line).font = Font(bold=(r == 1), size=10)
            r += 1
        r += 1
        head_row = r
        ws.cell(row=head_row, column=1, value="Attendance").font = Font(bold=True)
        ws.cell(row=head_row, column=1).fill = PatternFill("solid", fgColor="1E3A8A")
        ws.cell(row=head_row, column=1).font = Font(bold=True, color="FFFFFF")
        for j, dl in enumerate(data["day_labels"], start=2):
            cell = ws.cell(row=head_row, column=j, value=str(dl)[:2])
            cell.fill = PatternFill("solid", fgColor="1E3A8A")
            cell.font = Font(bold=True, color="FFFFFF", size=9)
            cell.alignment = center
            cell.border = thin
        for i, (key, label) in enumerate(ROW_KEYS):
            rr = head_row + 1 + i
            lc = ws.cell(row=rr, column=1, value=label)
            lc.font = Font(bold=True, size=9)
            lc.border = thin
            for j, dl in enumerate(data["day_labels"], start=2):
                d = emp["days"].get(dl) or {}
                cell = ws.cell(row=rr, column=j, value=d.get(key) or "-")
                cell.alignment = center
                cell.font = Font(size=8)
                cell.border = thin
                color = FLAG_COLORS.get(d.get("flag") or "")
                if color:
                    cell.fill = PatternFill("solid", fgColor=color)
        # summary row
        sr = head_row + 1 + len(ROW_KEYS)
        ws.cell(row=sr, column=1,
                value=f"Month Totals — Working {emp['month_total']} · OT {emp['month_ot']}"
                      f" · Present Days {emp.get('present_days') or 0}").font = Font(bold=True, size=9)
        ws.column_dimensions["A"].width = 13
        for j in range(2, len(data["day_labels"]) + 2):
            ws.column_dimensions[get_column_letter(j)].width = 6.5
        ws.freeze_panes = "B" + str(head_row + 1)

    buf = io.BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="inout-ot-matrix-{month}.xlsx"'})


@router.get("/inout-ot-matrix.csv")
async def inout_ot_matrix_csv(
    month: str,
    company_id: Optional[str] = None,
    department: Optional[str] = None,
    designation: Optional[str] = None,
    employee_type: Optional[str] = None,
    contractor: Optional[str] = None,
    shift: Optional[str] = None,
    q: Optional[str] = None,
    status: str = "all",
    authorization: Optional[str] = Header(None),
):
    _, cid = await _auth(authorization, company_id)
    data = await _build(cid, month, department, designation, employee_type,
                        contractor, shift, q, status)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Emp Code", "Name", "Department", "Designation", "Shift", "Type"]
               + [str(d)[:2] for d in data["day_labels"]])
    for emp in data["employees"]:
        for key, label in ROW_KEYS:
            w.writerow([emp.get("employee_code"), emp.get("name"),
                        emp.get("department"), emp.get("designation"),
                        emp.get("shift_name"), label]
                       + [(emp["days"].get(dl) or {}).get(key) or "-"
                          for dl in data["day_labels"]])
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="inout-ot-matrix-{month}.csv"'})


@router.get("/inout-ot-matrix.pdf")
async def inout_ot_matrix_pdf(
    month: str,
    company_id: Optional[str] = None,
    department: Optional[str] = None,
    designation: Optional[str] = None,
    employee_type: Optional[str] = None,
    contractor: Optional[str] = None,
    shift: Optional[str] = None,
    q: Optional[str] = None,
    status: str = "all",
    authorization: Optional[str] = Header(None),
):
    """A4 LANDSCAPE — one employee per page, whole month on one page,
    header repeated per page, colours identical to the screen."""
    from reportlab.lib import colors as rl
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)
    from reportlab.lib.styles import ParagraphStyle

    _, cid = await _auth(authorization, company_id)
    data = await _build(cid, month, department, designation, employee_type,
                        contractor, shift, q, status)
    emps = data["employees"][:300]
    if not emps:
        raise HTTPException(status_code=404, detail="No employees match the filters")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=8 * mm, rightMargin=8 * mm,
        topMargin=8 * mm, bottomMargin=8 * mm)
    h1 = ParagraphStyle("h1", fontSize=12, leading=15, spaceAfter=1,
                        fontName="Helvetica-Bold")
    h2 = ParagraphStyle("h2", fontSize=8.5, leading=11)
    flow: List[Any] = []
    ndays = len(data["day_labels"])
    page_w = landscape(A4)[0] - 16 * mm
    label_w = 20 * mm
    day_w = (page_w - label_w) / max(1, ndays)

    flag_fill = {k: rl.HexColor(f"#{v}") for k, v in FLAG_COLORS.items()}
    for idx, emp in enumerate(emps):
        for li, line in enumerate(_header_lines(data, emp)):
            flow.append(Paragraph(line, h1 if li == 0 else h2))
        flow.append(Spacer(1, 3 * mm))
        head = ["Attendance"] + [str(d)[:2] for d in data["day_labels"]]
        body = []
        styles = [
            ("BACKGROUND", (0, 0), (-1, 0), rl.HexColor("#1E3A8A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 5.6),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, rl.HexColor("#CBD5E1")),
            ("TOPPADDING", (0, 0), (-1, -1), 1.6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
            ("LEFTPADDING", (0, 0), (-1, -1), 1),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ]
        for i, (key, label) in enumerate(ROW_KEYS):
            row = [label]
            for j, dl in enumerate(data["day_labels"]):
                d = emp["days"].get(dl) or {}
                row.append(d.get(key) or "-")
                fill = flag_fill.get(d.get("flag") or "")
                if fill:
                    styles.append(("BACKGROUND", (j + 1, i + 1), (j + 1, i + 1), fill))
            body.append(row)
        tbl = Table([head] + body,
                    colWidths=[label_w] + [day_w] * ndays, repeatRows=1)
        tbl.setStyle(TableStyle(styles))
        flow.append(tbl)
        flow.append(Spacer(1, 2 * mm))
        flow.append(Paragraph(
            f"Month Totals — Working {emp['month_total']} · OT {emp['month_ot']} · "
            f"Present Days {emp.get('present_days') or 0}", h2))
        flow.append(Paragraph(
            "Legend: <font backcolor='#DBEAFE'> OT </font> "
            "<font backcolor='#FEF08A'> Late </font> "
            "<font backcolor='#FECACA'> Missing punch </font> "
            "<font backcolor='#E2E8F0'> Holiday </font> "
            "<font backcolor='#DCFCE7'> Weekly off </font> "
            "<font backcolor='#FED7AA'> Leave </font>", h2))
        if idx < len(emps) - 1:
            flow.append(PageBreak())
    doc.build(flow)
    return Response(
        content=buf.getvalue(), media_type="application/pdf",
        headers={"Content-Disposition":
                 f'inline; filename="inout-ot-matrix-{month}.pdf"'})
