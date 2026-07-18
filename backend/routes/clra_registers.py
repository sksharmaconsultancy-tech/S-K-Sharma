"""CLRA Central Rules registers — Contract Labour (Regulation & Abolition)
Act, 1970 / Central Rules, 1971.

  * Form XII  (Rule 74) — Register of Contractors (kept by principal employer)
  * Form XIII (Rule 75) — Register of Workmen employed by each Contractor
  * Form XIV  (Rule 76) — Employment Card (one per workman)
  * Form XV   (Rule 78) — Register of Wages (per wage period / month)

Data is derived from the Employee Master (workmen grouped by
``contractor_name``) and, for Form XV, from the finalized salary run of
the selected month when available.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from server import db, get_user_from_token  # noqa: E402
from routes.statutory_registers import (  # noqa: E402
    _check, _company, _new_pdf, _pdf_header, _table, _sig_block,
    _pdf_response, _s, _rs,
)

router = APIRouter(prefix="/api", tags=["clra-registers"])


def _age(dob: Any) -> str:
    s = str(dob or "").strip()
    if not s:
        return ""
    import re
    from datetime import date
    y = mo = d = None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", s)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not y:
        return ""
    today = date.today()
    yrs = today.year - y - ((today.month, today.day) < (mo or 1, d or 1))
    return str(yrs) if 0 < yrs < 120 else ""


def _sex(g: Any) -> str:
    g = str(g or "").strip().lower()
    if g.startswith("f"):
        return "F"
    if g.startswith("m"):
        return "M"
    return ""


def _basic_rate(emp: Dict[str, Any]) -> str:
    for r in (emp.get("salary_structure_actual") or []):
        if isinstance(r, dict) and str(r.get("head", "")).strip().lower().startswith("basic"):
            amt = float(r.get("amount") or 0)
            if amt > 0:
                rt = str(r.get("rate_type") or "").lower()
                suffix = "/day" if rt == "daily" else ("/mo" if r.get("amount") else "")
                return f"{_rs(amt)}{suffix}"
    if emp.get("salary_monthly"):
        return f"{_rs(emp['salary_monthly'])}/mo"
    return ""


async def _workmen(company_id: str) -> List[Dict[str, Any]]:
    return await db.users.find(
        {"role": "employee", "company_id": company_id},
        {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1, "father_name": 1,
         "designation": 1, "position": 1, "department": 1, "gender": 1, "dob": 1,
         "doj": 1, "exit_date": 1, "contractor_name": 1, "address": 1,
         "present_address": 1, "salary_monthly": 1, "salary_structure_actual": 1},
    ).to_list(10000)


def _by_contractor(emps: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for e in emps:
        c = (e.get("contractor_name") or "DIRECT / COMPANY ROLL").strip() or "DIRECT / COMPANY ROLL"
        groups.setdefault(c, []).append(e)
    return dict(sorted(groups.items(), key=lambda kv: kv[0]))


# ---------------------------------------------------------------------------
# FORM XII — Register of Contractors
# ---------------------------------------------------------------------------
@router.get("/admin/clra-registers/form-xii.pdf")
async def clra_form_xii(
    company_id: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check(admin, company_id)
    company = await _company(company_id)
    groups = _by_contractor(await _workmen(company_id))
    location = ", ".join([p for p in [company.get("city"), company.get("state")] if p]) or "-"

    pdf = _new_pdf(landscape=True)
    _pdf_header(
        pdf, "FORM XII",
        "[See Rule 74] Register of Contractors — Contract Labour (R&A) Central Rules, 1971",
        company,
    )
    headers = ["Sl", "Name & address of contractor", "Nature of work / operation",
               "Location of work", "Period of contract (From - To)",
               "Max. no. of workmen employed", "Remarks"]
    widths = [10, 62, 60, 40, 46, 34, 25]
    rows: List[List[str]] = []
    for i, (cname, members) in enumerate(groups.items(), start=1):
        desigs = sorted({(m.get("designation") or m.get("position") or "").strip()
                         for m in members if (m.get("designation") or m.get("position"))})
        nature = ", ".join(list(desigs)[:4]) + (" ..." if len(desigs) > 4 else "")
        rows.append([str(i), cname, nature or "-", location, "", str(len(members)), ""])
    if not rows:
        rows = [["", "NIL", "", "", "", "0", ""]]
    _table(pdf, headers, widths, rows,
           aligns=["C", "L", "L", "L", "C", "C", "L"], font_size=8)
    _sig_block(pdf, company.get("name") or "")
    return _pdf_response(pdf, "CLRA_FormXII_RegisterOfContractors.pdf")


# ---------------------------------------------------------------------------
# FORM XIII — Register of Workmen employed by Contractor
# ---------------------------------------------------------------------------
@router.get("/admin/clra-registers/form-xiii.pdf")
async def clra_form_xiii(
    company_id: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check(admin, company_id)
    company = await _company(company_id)
    groups = _by_contractor(await _workmen(company_id))

    pdf = _new_pdf(landscape=True)
    _pdf_header(
        pdf, "FORM XIII",
        "[See Rule 75] Register of Workmen employed by Contractor — Contract Labour (R&A) Central Rules, 1971",
        company,
    )
    headers = ["Sl", "Name of workman", "Age & Sex", "Father's / Husband's name",
               "Nature of employment / designation", "Permanent address",
               "Date of commencement", "Date of termination", "Remarks"]
    widths = [9, 42, 18, 44, 44, 44, 26, 26, 24]
    for cname, members in groups.items():
        if pdf.get_y() > (pdf.h - 40):
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.cell(0, 6, _s(f"Contractor: {cname}   (Total workmen: {len(members)})"),
                 new_x="LMARGIN", new_y="NEXT")
        rows: List[List[str]] = []
        for i, e in enumerate(members, start=1):
            age = _age(e.get("dob"))
            sex = _sex(e.get("gender"))
            age_sex = f"{age}/{sex}" if (age or sex) else ""
            addr = (e.get("address") or e.get("present_address") or "")[:40]
            rows.append([
                str(i), e.get("name") or "", age_sex, e.get("father_name") or "",
                e.get("designation") or e.get("position") or "", addr,
                e.get("doj") or "", e.get("exit_date") or "", "",
            ])
        _table(pdf, headers, widths, rows,
               aligns=["C", "L", "C", "L", "L", "L", "C", "C", "L"], font_size=7.5)
        pdf.ln(3)
    _sig_block(pdf, company.get("name") or "")
    return _pdf_response(pdf, "CLRA_FormXIII_RegisterOfWorkmen.pdf")


# ---------------------------------------------------------------------------
# FORM XIV — Employment Card (one per workman)
# ---------------------------------------------------------------------------
@router.get("/admin/clra-registers/form-xiv.pdf")
async def clra_form_xiv(
    company_id: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check(admin, company_id)
    company = await _company(company_id)
    emps = await _workmen(company_id)
    est_addr = ", ".join([p for p in [company.get("address"), company.get("city"),
                                      company.get("state")] if p])

    pdf = _new_pdf(landscape=False)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, _s("FORM XIV"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _s("[See Rule 76] Employment Card — Contract Labour (R&A) Central Rules, 1971"),
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    def card(sl: int, e: Dict[str, Any]) -> None:
        if pdf.get_y() > (pdf.h - 62):
            pdf.add_page()
        x0, y0 = pdf.l_margin, pdf.get_y()
        pdf.set_draw_color(15, 46, 61)
        pdf.rect(x0, y0, pdf.w - 2 * pdf.l_margin, 56)
        pdf.set_xy(x0 + 3, y0 + 3)
        lines = [
            ("1. Name & address of establishment", company.get("name", "") + ", " + est_addr),
            ("2. Name & address of contractor", e.get("contractor_name") or "DIRECT / COMPANY ROLL"),
            ("3. Name of workman", e.get("name") or ""),
            ("4. Sl. No. in the Register of Workmen (Form XIII)", str(sl)),
            ("5. Nature of employment / designation",
             e.get("designation") or e.get("position") or ""),
            ("6. Wage rate (with particulars of unit)", _basic_rate(e)),
            ("7. Wage period", "Monthly"),
            ("8. Date of commencement of employment", e.get("doj") or ""),
        ]
        for label, val in lines:
            pdf.set_x(x0 + 3)
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.cell(88, 5.5, _s(label), border=0)
            pdf.set_font("Helvetica", "", 8.5)
            pdf.multi_cell(0, 5.5, _s(": " + (val or "")))
        pdf.set_y(y0 + 58)

    for i, e in enumerate(emps, start=1):
        card(i, e)
    if not emps:
        pdf.cell(0, 8, "No workmen found for this firm.", new_x="LMARGIN", new_y="NEXT")
    return _pdf_response(pdf, "CLRA_FormXIV_EmploymentCards.pdf")


# ---------------------------------------------------------------------------
# FORM XV — Register of Wages (per wage period / month)
# ---------------------------------------------------------------------------
@router.get("/admin/clra-registers/form-xv.pdf")
async def clra_form_xv(
    company_id: str = Query(...),
    month: str = Query(..., description="YYYY-MM"),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check(admin, company_id)
    company = await _company(company_id)

    # Prefer a finalized salary run for the wage period; else any run; else
    # fall back to the employee master (wage rate only).
    run = await db.salary_runs.find_one(
        {"company_id": company_id, "month": month, "finalized": True}, {"_id": 0})
    if not run:
        run = await db.salary_runs.find_one(
            {"company_id": company_id, "month": month}, {"_id": 0})

    emps = {e["user_id"]: e for e in await _workmen(company_id)}

    pdf = _new_pdf(landscape=True)
    _pdf_header(
        pdf, "FORM XV",
        f"[See Rule 78(1)(a)(i)] Register of Wages — wage period {month} — Contract Labour (R&A) Central Rules, 1971",
        company,
    )
    headers = ["Sl", "Name of workman", "Designation", "No. of days worked",
               "Wage rate", "Basic earned", "OT / Other", "Gross (Rs.)",
               "Deductions (Rs.)", "Net paid (Rs.)", "Signature"]
    widths = [9, 40, 34, 22, 24, 26, 24, 26, 28, 26, 24]
    rows: List[List[str]] = []
    total_net = 0.0

    if run and run.get("rows"):
        for i, r in enumerate(run["rows"], start=1):
            emp = emps.get(r.get("user_id"), {})
            gross = float(r.get("total_gross") or 0)
            ded = float(r.get("epf") or 0) + float(r.get("esi") or 0) \
                + float(r.get("adv") or 0) + float(r.get("tds") or 0)
            net = float(r.get("net_pay") or 0) or (gross - ded)
            total_net += net
            rows.append([
                str(i), r.get("name") or "",
                r.get("designation") or "",
                _rs(r.get("p_days") or 0),
                _basic_rate(emp),
                _rs(r.get("basic") or 0),
                _rs(float(r.get("oth_allo") or 0)),
                _rs(gross), _rs(ded), _rs(net), "",
            ])
        rows.append(["", "TOTAL", "", "", "", "", "", "", "", _rs(total_net), ""])
    else:
        # No salary run — list workmen with their wage rate for manual entry.
        for i, e in enumerate(emps.values(), start=1):
            rows.append([
                str(i), e.get("name") or "",
                e.get("designation") or e.get("position") or "",
                "", _basic_rate(e), "", "", "", "", "", "",
            ])

    _table(pdf, headers, widths, rows,
           aligns=["C", "L", "L", "C", "R", "R", "R", "R", "R", "R", "C"],
           font_size=7.5)
    if not (run and run.get("rows")):
        pdf.ln(3)
        pdf.set_font("Helvetica", "I", 8.5)
        pdf.multi_cell(0, 4.5, _s(
            f"Note: No finalized salary run found for {month}. Wage rates are shown "
            "from the Employee Master; earned/gross/net columns are blank for manual "
            "entry. Finalize the salary run for this month to auto-fill them."))
    _sig_block(pdf, company.get("name") or "")
    return _pdf_response(pdf, f"CLRA_FormXV_WageRegister_{month}.pdf")
