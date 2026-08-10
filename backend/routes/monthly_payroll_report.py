"""Iter 529 (user request) — MONTHLY PAYROLL ATTENDANCE & SALARY REPORT.

One comprehensive landscape report per employee per month:
  Employee Details → Daily Attendance 1–31 → Attendance Summary →
  Compliance / Actual Gross → Final Salary (selected basis) →
  Deductions → Net Payable → Bank Details.

REPORTING LAYER ONLY — nothing is recalculated here:
  * attendance day codes  → ``_compute_monthly_grid_data`` (the same
    policy engine that powers the Attendance Grid / payroll)
  * leave codes (CL/PL/EL/SL/ESIC) → approved ``leaves`` / ``esic_leaves``
  * payable days / OT     → policy engine + finalized salary run
  * Compliance salary     → latest ``compliance_salary_runs`` of the month
  * Actual salary         → latest ``salary_runs`` of the month
  * deductions            → from the selected basis' payroll run
If payroll wasn't processed → "Salary Not Calculated" (never fake zeros);
if the month has no attendance at all → "Attendance Pending".

Endpoints:
  GET /api/admin/reports/monthly-payroll        (JSON incl. filter meta)
  GET /api/admin/reports/monthly-payroll.xlsx
  GET /api/admin/reports/monthly-payroll.pdf    (A3 landscape, repeat hdr)
"""
from datetime import date, datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from server import (db, get_user_from_token, require_role,  # noqa: E402
                    _compute_monthly_grid_data)
from routes.present_absent_report import _day_status  # noqa: E402
from utils.register_export import register_xlsx  # noqa: E402

router = APIRouter(prefix="/api/admin/reports", tags=["monthly-payroll"])

LEAVE_CODE = {"casual": "CL", "sick": "SL", "earned": "EL",
              "paid": "PL", "privilege": "PL"}


async def _adm(authorization, company_id):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return admin, company_id


def _f(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _s(v) -> str:
    return str(v or "").strip()


def _norm(v) -> str:
    return _s(v).upper()


def _mask_acct(v: str) -> str:
    s = _s(v)
    return f"XXXXXX{s[-4:]}" if len(s) > 4 else s


async def _latest_run(coll, company_id: str, month: str):
    return await coll.find_one(
        {"company_id": company_id, "month": month}, {"_id": 0},
        sort=[("generated_at", -1)])


async def _default_month(company_id: str) -> str:
    """Iter 535 (user request) — month selector defaults to the LAST
    salary-FINALIZED month, never the current month."""
    r = await db.compliance_salary_runs.find_one(
        {"company_id": company_id,
         "$or": [{"finalized": True}, {"frozen": True}]},
        {"_id": 0, "month": 1}, sort=[("month", -1)])
    if not r:  # no finalized run yet → latest processed run
        r = await db.compliance_salary_runs.find_one(
            {"company_id": company_id}, {"_id": 0, "month": 1},
            sort=[("month", -1)])
    if not r:
        r = await db.salary_runs.find_one(
            {"company_id": company_id}, {"_id": 0, "month": 1},
            sort=[("month", -1)])
    return _s((r or {}).get("month"))[:7] or date.today().strftime("%Y-%m")


async def _leave_days(company_id: str, month: str) -> Dict[str, Dict[str, str]]:
    """user_id → {iso_date: leave code} for APPROVED leaves in the month."""
    m0, m1 = f"{month}-01", f"{month}-31"
    out: Dict[str, Dict[str, str]] = {}

    def _mark(uid, fd, td, code):
        fd, td = max(_s(fd)[:10], m0), min(_s(td)[:10], m1)
        try:
            d0 = datetime.strptime(fd, "%Y-%m-%d").date()
            d1 = datetime.strptime(td, "%Y-%m-%d").date()
        except ValueError:
            return
        cur = d0
        while cur <= d1:
            out.setdefault(uid, {})[cur.isoformat()] = code
            cur = date.fromordinal(cur.toordinal() + 1)
    async for lv in db.leaves.find(
            {"status": "approved", "from_date": {"$lte": m1},
             "to_date": {"$gte": m0}},
            {"_id": 0, "user_id": 1, "from_date": 1, "to_date": 1,
             "leave_type": 1}):
        code = LEAVE_CODE.get(_s(lv.get("leave_type")).lower())
        if code:  # unpaid leave stays "A"
            _mark(lv["user_id"], lv["from_date"], lv["to_date"], code)
    async for lv in db.esic_leaves.find(
            {"company_id": company_id, "status": "approved",
             "from_date": {"$lte": m1}, "to_date": {"$gte": m0}},
            {"_id": 0, "user_id": 1, "from_date": 1, "to_date": 1}):
        _mark(lv["user_id"], lv["from_date"], lv["to_date"], "ESIC")
    return out


def _ded_head(dh: dict, *needles: str) -> float:
    tot = 0.0
    for k, v in (dh or {}).items():
        nk = _norm(k).replace(" ", "").replace("-", "")
        if any(n in nk for n in needles):
            tot += _f(v)
    return round(tot, 2)


async def _build(company_id: str, month: str, flt: Dict[str, str],
                 basis: str, salary_type: str,
                 mask_bank: bool) -> Dict[str, Any]:
    grid = await _compute_monthly_grid_data(company_id=company_id,
                                            month=month)
    day_labels: List[str] = grid.get("day_labels") or []
    dfd: List[str] = grid.get("day_full_dates") or [
        f"{month}-{str(d)[:2]}" for d in day_labels]
    n_days = len(day_labels)
    today_iso = date.today().isoformat()
    by_uid_att = {e.get("user_id"): e for e in grid.get("employees") or []}

    # Iter 537 (user report "Attendance Showing Wrong") — day cells now
    # ALWAYS use the attendance-policy engine's split directly:
    # duty_hours (capped at the policy full-day hours) + ot_hours (beyond
    # the policy threshold). No dependence on raw policy fields, so every
    # firm's cells match its Attendance Policy exactly: "8+3" or "8".
    comp_c = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "address": 1, "logo_base64": 1})
    att_mode = "HRS+OT"

    def _hrs(v: float) -> str:
        return f"{v:g}"

    comp_run = await _latest_run(db.compliance_salary_runs, company_id, month)
    act_run = await _latest_run(db.salary_runs, company_id, month)
    # Iter 536 — months that actually HAVE a salary run (for the ‹ › stepper)
    run_months = sorted(
        {_s(m)[:7] for m in
         (await db.compliance_salary_runs.distinct(
             "month", {"company_id": company_id}))
         + (await db.salary_runs.distinct(
             "month", {"company_id": company_id})) if _s(m)})
    comp = {r.get("user_id"): r for r in (comp_run or {}).get("rows") or []}
    act = {r.get("user_id"): r for r in (act_run or {}).get("rows") or []}
    leaves = await _leave_days(company_id, month)

    users = await db.users.find(
        {"company_id": company_id, "role": "employee"},
        {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
         "father_name": 1, "designation": 1, "department": 1, "doj": 1,
         "uan_no": 1, "esi_ip_no": 1, "employee_type": 1,
         "contractor_name": 1, "branch_name": 1, "bank_account": 1,
         "bank_account_name": 1, "bank_name": 1, "bank_ifsc": 1,
         "bank_branch": 1, "exit_date": 1}).to_list(100000)

    term = _s(flt.get("search")).lower()
    ids = set(_s(flt.get("employee_ids")).split(",")) - {""}
    rows: List[dict] = []
    for u in users:
        uid = u["user_id"]
        if flt.get("department") and _norm(u.get("department")) != _norm(flt["department"]):
            continue
        if flt.get("designation") and _norm(u.get("designation")) != _norm(flt["designation"]):
            continue
        if flt.get("employee_type") and _norm(u.get("employee_type")) != _norm(flt["employee_type"]):
            continue
        if flt.get("contractor") and _norm(u.get("contractor_name")) != _norm(flt["contractor"]):
            continue
        if flt.get("branch") and _norm(u.get("branch_name")) != _norm(flt["branch"]):
            continue
        if ids and uid not in ids:
            continue
        if term and term not in f"{u.get('name', '')} {u.get('employee_code', '')}".lower():
            continue
        a = by_uid_att.get(uid) or {}
        lv = leaves.get(uid) or {}
        row: Dict[str, Any] = {
            "employee_code": u.get("employee_code"), "name": u.get("name"),
            "father_name": _s(u.get("father_name")),
            "designation": _s(u.get("designation")),
            "department": _s(u.get("department")),
            "doj": _s(u.get("doj"))[:10],
            "uan": _s(u.get("uan_no")), "esic_ip": _s(u.get("esi_ip_no")),
        }
        # ------- daily attendance 1..n — HOURS per policy (Iter 534),
        # leave/off codes kept; counts still drive the summary columns
        cnt = {"P": 0.0, "L": 0, "WO": 0, "HO": 0, "A": 0}
        any_att = False
        for i, dl in enumerate(day_labels):
            cell = (a.get("days") or {}).get(dl) or {}
            iso = dfd[i] if i < len(dfd) else f"{month}-{str(dl)[:2]}"
            st = _day_status(cell, iso, today_iso) if a else ""
            if st == "A" and iso in lv:
                st = lv[iso]  # CL / PL / EL / SL / ESIC
            code = {"H": "HO"}.get(st, st)
            if code in ("P", "HD"):
                duty = _f(cell.get("duty_hours"))
                ot = _f(cell.get("ot_hours"))
                if not duty and not ot:  # engine cell without split
                    duty = _f(cell.get("hours"))
                val = f"{_hrs(duty)}+{_hrs(ot)}" if ot > 0 else _hrs(duty)
                row[f"d{i + 1}"] = val
            elif code == "A":
                row[f"d{i + 1}"] = "-"
            else:
                row[f"d{i + 1}"] = code
            if code == "P":
                cnt["P"] += 1
                any_att = True
            elif code == "HD":
                cnt["P"] += 0.5
                any_att = True
            elif code in ("CL", "PL", "EL", "SL", "ESIC"):
                cnt["L"] += 1
            elif code == "WO":
                cnt["WO"] += 1
            elif code == "HO":
                cnt["HO"] += 1
            elif code == "A":
                cnt["A"] += 1
        cr, ar = comp.get(uid), act.get(uid)
        # ------- summary (payable days per the attendance policy / run)
        pol_days = _f((a.get("totals") or {}).get("present_days_policy"))
        payable = _f((cr or {}).get("present_days")) or pol_days
        ot_hours = _f((cr or {}).get("ot_hours")) or \
            _f((a.get("totals") or {}).get("ot_hours"))
        row.update({
            "present": round(cnt["P"], 1), "leave": cnt["L"],
            "wo": cnt["WO"], "holiday": cnt["HO"], "absent": cnt["A"],
            "payable_days": payable, "ot_hours": ot_hours,
        })
        # ------- salary (never overwrite one basis with the other)
        comp_gross = _f((cr or {}).get("gross_paid")) if cr else None
        act_gross = _f((ar or {}).get("total_gross")) if ar else None
        b_row = cr if basis == "compliance" else ar
        if not any_att and not b_row:
            row["status_note"] = "Attendance Pending"
        if b_row is None:
            row["status_note"] = row.get("status_note") or "Salary Not Calculated"
            row.update({"comp_gross": comp_gross, "act_gross": act_gross,
                        "final_salary": None, "pf": None, "esic": None,
                        "pt": None, "lwf": None, "tds": None,
                        "advance": None, "other_ded": None,
                        "total_ded": None, "net": None})
        else:
            if basis == "compliance":
                dh = (cr or {}).get("deduction_heads") or {}
                adv = _ded_head(dh, "ADV", "LOAN")
                lwf = _f((cr or {}).get("lwf")) or _ded_head(dh, "LWF")
                pf, esic = _f(cr.get("pf_employee")), _f(cr.get("esic_employee"))
                pt, tds = _f(cr.get("pt")), _f(cr.get("tds"))
                total_ded = _f(cr.get("total_deduction"))
                final = _f(cr.get("gross_paid"))
                net = _f(cr.get("net"))
            else:
                pf, esic = _f(ar.get("epf")), _f(ar.get("esi"))
                pt, lwf = _f(ar.get("pt")), _f(ar.get("lwf"))
                tds, adv = _f(ar.get("tds")), _f(ar.get("adv"))
                total_ded = round(pf + esic + pt + lwf + tds + adv
                                  + _f(ar.get("other_deduction")), 2)
                final = _f(ar.get("total_gross"))
                net = _f(ar.get("net_pay")) or round(final - total_ded, 2)
            other = round(max(0.0, total_ded - pf - esic - pt - lwf
                              - tds - adv), 2)
            row.update({
                "comp_gross": comp_gross, "act_gross": act_gross,
                "final_salary": final, "pf": pf, "esic": esic, "pt": pt,
                "lwf": lwf, "tds": tds, "advance": adv, "other_ded": other,
                "total_ded": total_ded, "net": net})
        # ------- bank
        acct = _s(u.get("bank_account"))
        row.update({
            "acct_name": _s(u.get("bank_account_name")) or u.get("name"),
            "acct_no": _mask_acct(acct) if mask_bank else acct,
            "ifsc": _s(u.get("bank_ifsc")), "bank_name": _s(u.get("bank_name")),
            "bank_branch": _s(u.get("bank_branch")),
            "payment_mode": "Bank" if acct else "Cash",
        })
        rows.append(row)
    rows.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
    for i, r in enumerate(rows, 1):
        r["sr"] = i

    # ------- columns (exact user-specified sequence)
    cols: List[tuple] = [
        ("sr", "S.No"), ("employee_code", "Emp Code"),
        ("name", "Employee Name"), ("father_name", "Father Name"),
        ("designation", "Designation"), ("department", "Department"),
        ("doj", "DOJ"), ("uan", "UAN"), ("esic_ip", "ESIC IP")]
    cols += [(f"d{i + 1}", str(int(str(day_labels[i])[:2])))
             for i in range(n_days)]
    cols += [("present", "Present"), ("leave", "Leave"), ("wo", "WO"),
             ("holiday", "Holiday"), ("absent", "Absent"),
             ("payable_days", "Total Att."), ("ot_hours", "OT Hrs")]
    if salary_type in ("compliance", "both"):
        cols.append(("comp_gross", "Compliance Gross"))
    if salary_type in ("actual", "both"):
        cols.append(("act_gross", "Actual Gross"))
    cols += [("final_salary", f"Final Salary ({basis.title()})"),
             ("pf", "PF"), ("esic", "ESIC"), ("pt", "PT"), ("lwf", "LWF"),
             ("tds", "TDS"), ("advance", "Advance"),
             ("other_ded", "Other Ded."), ("total_ded", "Total Ded."),
             ("net", "Net Payable"), ("acct_name", "A/c Holder"),
             ("acct_no", "Account No."), ("ifsc", "IFSC"),
             ("bank_name", "Bank"), ("bank_branch", "Branch"),
             ("payment_mode", "Mode")]
    # ------- footer totals (numeric columns only)
    totals: Dict[str, Any] = {"name": "TOTAL"}
    for k in ("present", "leave", "wo", "holiday", "absent", "payable_days",
              "ot_hours", "comp_gross", "act_gross", "final_salary", "pf",
              "esic", "pt", "lwf", "tds", "advance", "other_ded",
              "total_ded", "net"):
        totals[k] = round(sum(_f(r.get(k)) for r in rows
                              if r.get(k) is not None), 2)
    comp_c = comp_c or {}
    all_u = users
    meta = {
        "departments": sorted({_s(x.get("department")) for x in all_u} - {""}),
        "designations": sorted({_s(x.get("designation")) for x in all_u} - {""}),
        "employee_types": sorted({_s(x.get("employee_type")) for x in all_u} - {""}),
        "contractors": sorted({_s(x.get("contractor_name")) for x in all_u} - {""}),
        "branches": sorted({_s(x.get("branch_name")) for x in all_u} - {""}),
    }
    return {
        "title": "Monthly Payroll Attendance & Salary Report",
        "company": {"name": (comp_c or {}).get("name"),
                    "address": (comp_c or {}).get("address") or "",
                    "logo_base64": (comp_c or {}).get("logo_base64")},
        "month": month, "basis": basis, "salary_type": salary_type,
        "att_mode": att_mode, "run_months": run_months,
        "day_labels": day_labels,
        "weekday_labels": grid.get("weekday_labels") or [],
        "compliance_run": bool(comp_run),
        "compliance_finalized": bool((comp_run or {}).get("finalized")
                                     or (comp_run or {}).get("frozen")),
        "actual_run": bool(act_run),
        "columns": [{"key": k, "label": lb} for k, lb in cols],
        "rows": rows, "totals": totals, "meta": meta,
        "n_frozen": 9,  # S.No … ESIC IP stay frozen on the web grid
    }


def _flt(branch, department, designation, employee_type, contractor,
         search, employee_ids):
    return {"branch": _s(branch), "department": _s(department),
            "designation": _s(designation),
            "employee_type": _s(employee_type),
            "contractor": _s(contractor), "search": _s(search),
            "employee_ids": _s(employee_ids)}


def _pdf(d: Dict[str, Any]) -> BytesIO:
    """Custom A3-landscape PDF — narrow day cells, repeated header."""
    from reportlab.lib import colors as rl
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A3), leftMargin=5 * mm,
                            rightMargin=5 * mm, topMargin=6 * mm,
                            bottomMargin=8 * mm, title=d["title"])
    W = landscape(A3)[0] - 10 * mm
    cols = d["columns"]
    story = [
        Paragraph(d["company"]["name"] or "", ParagraphStyle(
            "c", fontSize=14, leading=17, fontName="Helvetica-Bold",
            alignment=1)),
        Paragraph(f"{d['title']} — {d['month']} · Salary Basis: "
                  f"{d['basis'].title()} · Day cells: "
                  f"{'Duty HRS + OT HRS' if d.get('att_mode') == 'HRS+OT' else 'Duty HRS'}"
                  " (as per attendance policy)", ParagraphStyle(
                      "t", fontSize=10, leading=13, alignment=1)),
        Spacer(1, 3 * mm)]
    hs = ParagraphStyle("h", fontSize=5.4, leading=6.4,
                        fontName="Helvetica-Bold", alignment=1)
    cs = ParagraphStyle("d", fontSize=5.4, leading=6.4, alignment=1)
    ls = ParagraphStyle("l", fontSize=5.4, leading=6.4, alignment=0)

    def _v(row, c):
        v = row.get(c["key"])
        if isinstance(v, float):
            return f"{v:,.2f}".rstrip("0").rstrip(".")
        return "" if v is None else str(v)
    body = [[Paragraph(c["label"], hs) for c in cols]]
    for r in d["rows"]:
        body.append([Paragraph(_v(r, c),
                               ls if c["key"] in ("name", "father_name")
                               else cs) for c in cols])
    body.append([Paragraph(_v(d["totals"], c) if c["key"] != "name"
                           else "TOTAL", hs) for c in cols])
    widths = []
    for c in cols:
        k = c["key"]
        if k.startswith("d") and k[1:].isdigit():
            widths.append(15.0)
        elif k in ("name", "acct_name"):
            widths.append(52.0)
        elif k in ("father_name", "designation", "bank_name"):
            widths.append(42.0)
        elif k in ("department", "acct_no", "ifsc", "bank_branch", "uan",
                   "esic_ip"):
            widths.append(36.0)
        elif k == "sr":
            widths.append(14.0)
        else:
            widths.append(26.0)
    scale = W / sum(widths)
    tbl = Table(body, colWidths=[w * scale for w in widths], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, rl.HexColor("#9AA0A6")),
        ("BACKGROUND", (0, 0), (-1, 0), rl.HexColor("#DDEBF7")),
        ("BACKGROUND", (0, len(body) - 1), (-1, len(body) - 1),
         rl.HexColor("#FFF2CC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    story.append(tbl)

    def _page(cv, _doc):
        cv.setFont("Helvetica", 7)
        cv.drawRightString(landscape(A3)[0] - 5 * mm, 4 * mm,
                           f"Page {cv.getPageNumber()} · Generated "
                           f"{datetime.now():%d-%m-%Y %H:%M}")
    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    buf.seek(0)
    return buf


@router.get("/monthly-payroll")
async def monthly_payroll(company_id: Optional[str] = None,
                          month: str = "", branch: str = "",
                          department: str = "", designation: str = "",
                          employee_type: str = "", contractor: str = "",
                          salary_type: str = "both",
                          basis: str = "compliance", search: str = "",
                          employee_ids: str = "",
                          token: Optional[str] = Query(None),
                          authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(
        authorization or (f"Bearer {token}" if token else None), company_id)
    month = _s(month)[:7] or await _default_month(company_id)
    basis = "actual" if basis == "actual" else "compliance"
    if salary_type not in ("compliance", "actual", "both"):
        salary_type = "both"
    mask = admin.get("role") not in ("super_admin",)
    return await _build(company_id, month,
                        _flt(branch, department, designation, employee_type,
                             contractor, search, employee_ids),
                        basis, salary_type, mask)


@router.get("/monthly-payroll.xlsx")
async def monthly_payroll_xlsx(company_id: Optional[str] = None,
                               month: str = "", branch: str = "",
                               department: str = "", designation: str = "",
                               employee_type: str = "", contractor: str = "",
                               salary_type: str = "both",
                               basis: str = "compliance", search: str = "",
                               employee_ids: str = "",
                               token: Optional[str] = Query(None),
                               authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(
        authorization or (f"Bearer {token}" if token else None), company_id)
    month = _s(month)[:7] or await _default_month(company_id)
    basis = "actual" if basis == "actual" else "compliance"
    mask = admin.get("role") not in ("super_admin",)
    d = await _build(company_id, month,
                     _flt(branch, department, designation, employee_type,
                          contractor, search, employee_ids),
                     basis, salary_type if salary_type in
                     ("compliance", "actual", "both") else "both", mask)
    buf = register_xlsx(
        d["title"],
        f"{d['company']['name']} · {month} · Salary Basis: {basis.title()}"
        f" · Generated {datetime.now():%d-%m-%Y}",
        d["columns"], d["rows"], d["totals"])
    return StreamingResponse(
        buf, media_type=("application/vnd.openxmlformats-officedocument"
                         ".spreadsheetml.sheet"),
        headers={"Content-Disposition":
                 f'attachment; filename="monthly_payroll_{month}.xlsx"'})


@router.get("/monthly-payroll.pdf")
async def monthly_payroll_pdf(company_id: Optional[str] = None,
                              month: str = "", branch: str = "",
                              department: str = "", designation: str = "",
                              employee_type: str = "", contractor: str = "",
                              salary_type: str = "both",
                              basis: str = "compliance", search: str = "",
                              employee_ids: str = "",
                              token: Optional[str] = Query(None),
                              authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(
        authorization or (f"Bearer {token}" if token else None), company_id)
    month = _s(month)[:7] or await _default_month(company_id)
    basis = "actual" if basis == "actual" else "compliance"
    mask = admin.get("role") not in ("super_admin",)
    d = await _build(company_id, month,
                     _flt(branch, department, designation, employee_type,
                          contractor, search, employee_ids),
                     basis, salary_type if salary_type in
                     ("compliance", "actual", "both") else "both", mask)
    buf = _pdf(d)
    return Response(content=buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'inline; filename="monthly_payroll_{month}.pdf"'})
