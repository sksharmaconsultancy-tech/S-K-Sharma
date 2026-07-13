"""Iter 95 — Statutory Registers & Annual Returns (web portal).

1. Payment of Bonus Act, 1965 — Rules 1975 registers:
   * Form A — Computation of allocable surplus (Rule 4(a))
   * Form B — Set-on / Set-off of allocable surplus (Rule 4(b))
   * Form C — Bonus paid register, employee-wise (Rule 4(c))
   * Form D — Annual return of bonus paid (Rule 5)
   Financial figures for A/B (+ payment meta for C/D) are entered by the
   admin and stored per (company, FY) in ``db.bonus_financials``.
   Employee bonus rows for C/D come live from ``_compute_bonus_run``.

2. Equal Remuneration Act, 1976 — register/annual return (Form D under the
   ER Rules): category-wise men/women employed with remuneration rates.

3. Inter-State Migrant Workmen Act, 1979 — annual return (Form XXIII
   style): establishment particulars + workmen listing.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    sub_admin_can_touch_company,
    _compute_bonus_run,
)

router = APIRouter(prefix="/api", tags=["statutory-registers"])


async def _check(admin: dict, company_id: str, allow_company_admin: bool = True) -> None:
    roles = ["super_admin", "sub_admin"] + (["company_admin"] if allow_company_admin else [])
    require_role(admin, roles)
    if admin.get("role") == "sub_admin" and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm not in your scope")
    if admin.get("role") == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="You can only access your own firm")


def _fy_label(y: int) -> str:
    return f"{y}-{str(y + 1)[-2:]}"


def _s(txt: Any) -> str:
    return str(txt if txt is not None else "").replace("\u2018", "'") \
        .replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"') \
        .replace("\u2013", "-").replace("\u2014", "-") \
        .replace("\u20b9", "Rs.").encode("latin-1", "replace").decode("latin-1")


def _rs(n: Any) -> str:
    try:
        return f"{float(n):,.2f}"
    except Exception:
        return "0.00"


# ---------------------------------------------------------------------------
# Financial figures (Form A/B inputs + payment meta)
# ---------------------------------------------------------------------------

DEFAULT_FIN: Dict[str, Any] = {
    "gross_profit": 0.0,
    "depreciation": 0.0,          # Sec 6(a)
    "development_rebate": 0.0,    # Sec 6(b)
    "direct_tax": 0.0,            # Sec 6(c)
    "other_sums": 0.0,            # Sec 6(d)
    "allocable_percent": 60.0,    # 67% for banking companies
    "set_on_off_rows": [],        # [{year, allocable_surplus, bonus_payable, set_on, set_off}]
    "payment_date": "",
    "nature_of_industry": "",
    "employer_name": "",
}


class FinancialsPayload(BaseModel):
    company_id: str
    fy_start_year: int
    gross_profit: Optional[float] = None
    depreciation: Optional[float] = None
    development_rebate: Optional[float] = None
    direct_tax: Optional[float] = None
    other_sums: Optional[float] = None
    allocable_percent: Optional[float] = None
    set_on_off_rows: Optional[List[Dict[str, Any]]] = None
    payment_date: Optional[str] = None
    nature_of_industry: Optional[str] = None
    employer_name: Optional[str] = None


async def _get_fin(company_id: str, fy: int) -> Dict[str, Any]:
    doc = await db.bonus_financials.find_one(
        {"company_id": company_id, "fy_start_year": fy}, {"_id": 0},
    )
    return {**DEFAULT_FIN, **(doc or {}), "company_id": company_id, "fy_start_year": fy}


@router.get("/admin/bonus-registers/financials")
async def get_financials(
    company_id: str = Query(...),
    fy_start_year: int = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check(admin, company_id)
    return {"financials": await _get_fin(company_id, fy_start_year)}


@router.put("/admin/bonus-registers/financials")
async def put_financials(payload: FinancialsPayload, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    await _check(admin, payload.company_id)
    updates = {k: v for k, v in payload.model_dump().items()
               if v is not None and k not in ("company_id", "fy_start_year")}
    updates["updated_at"] = now_iso()
    updates["updated_by"] = admin.get("user_id")
    await db.bonus_financials.update_one(
        {"company_id": payload.company_id, "fy_start_year": payload.fy_start_year},
        {"$set": updates},
        upsert=True,
    )
    return {"financials": await _get_fin(payload.company_id, payload.fy_start_year)}


# ---------------------------------------------------------------------------
# PDF plumbing
# ---------------------------------------------------------------------------

def _new_pdf(landscape: bool = False):
    from fpdf import FPDF
    pdf = FPDF(orientation="L" if landscape else "P", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_margins(12, 12, 12)
    return pdf


def _pdf_header(pdf, title: str, subtitle: str, company: dict):
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 7, _s(title), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.cell(0, 5, _s(subtitle), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(0, 5.5, _s(f"Name of establishment: {company.get('name') or ''}"),
             new_x="LMARGIN", new_y="NEXT")
    addr = ", ".join([p for p in [company.get("address"), company.get("city"),
                                  company.get("state")] if p])
    pdf.set_font("Helvetica", "", 9.5)
    if addr:
        pdf.cell(0, 5, _s(f"Address: {addr}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)


def _table(pdf, headers: List[str], widths: List[float], rows: List[List[str]],
           aligns: Optional[List[str]] = None, font_size: float = 8.5):
    aligns = aligns or ["L"] * len(headers)
    pdf.set_font("Helvetica", "B", font_size)
    pdf.set_fill_color(15, 46, 61)
    pdf.set_text_color(255, 255, 255)
    line_h = 5.0
    # Header (multi-line capable via multi_cell math kept simple: single line)
    for h, w in zip(headers, widths):
        pdf.cell(w, 7, _s(h), border=1, align="C", fill=True)
    pdf.ln(7)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", font_size)
    fill = False
    for r in rows:
        if pdf.get_y() > (pdf.h - 20):
            pdf.add_page()
        pdf.set_fill_color(245, 247, 249)
        for val, w, a in zip(r, widths, aligns):
            pdf.cell(w, line_h + 1.5, _s(val), border=1, align=a, fill=fill)
        pdf.ln(line_h + 1.5)
        fill = not fill


def _sig_block(pdf, company_name: str):
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, _s(f"For {company_name}"), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(12)
    pdf.cell(0, 6, "Authorised Signatory", align="R", new_x="LMARGIN", new_y="NEXT")


def _pdf_response(pdf, fname: str) -> Response:
    return Response(
        content=bytes(pdf.output()),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


async def _company(company_id: str) -> dict:
    c = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "address": 1, "city": 1, "state": 1, "company_code": 1},
    )
    if not c:
        raise HTTPException(status_code=404, detail="Firm not found")
    return c


# ---------------------------------------------------------------------------
# FORM A — Computation of allocable surplus
# ---------------------------------------------------------------------------

@router.get("/admin/bonus-registers/form-a.pdf")
async def bonus_form_a(
    company_id: str = Query(...),
    fy_start_year: int = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check(admin, company_id)
    company = await _company(company_id)
    fin = await _get_fin(company_id, fy_start_year)
    fy = _fy_label(fy_start_year)

    gp = float(fin["gross_profit"] or 0)
    dep = float(fin["depreciation"] or 0)
    dev = float(fin["development_rebate"] or 0)
    tax = float(fin["direct_tax"] or 0)
    oth = float(fin["other_sums"] or 0)
    available = gp - (dep + dev + tax + oth)
    pct = float(fin["allocable_percent"] or 60.0)
    allocable = round(available * pct / 100.0, 2)

    pdf = _new_pdf(landscape=True)
    _pdf_header(
        pdf, "FORM A",
        f"[See Rule 4(a), Payment of Bonus Rules, 1975] — Computation of the Allocable Surplus — Accounting Year {fy}",
        company,
    )
    headers = [
        "Accounting Year",
        "Gross Profit (Rs.)",
        "Depreciation Sec 6(a)",
        "Development Rebate Sec 6(b)",
        "Direct Taxes Sec 6(c)",
        "Further Sums Sec 6(d)",
        "Available Surplus (Rs.)",
        f"Allocable Surplus ({pct:g}%)",
    ]
    widths = [30, 34, 34, 36, 32, 32, 36, 39]
    rows = [[fy, _rs(gp), _rs(dep), _rs(dev), _rs(tax), _rs(oth),
             _rs(available), _rs(allocable)]]
    _table(pdf, headers, widths, rows,
           aligns=["C", "R", "R", "R", "R", "R", "R", "R"])
    _sig_block(pdf, company.get("name") or "")
    return _pdf_response(pdf, f"Bonus_FormA_{fy}.pdf")


# ---------------------------------------------------------------------------
# FORM B — Set-on / Set-off of allocable surplus
# ---------------------------------------------------------------------------

@router.get("/admin/bonus-registers/form-b.pdf")
async def bonus_form_b(
    company_id: str = Query(...),
    fy_start_year: int = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check(admin, company_id)
    company = await _company(company_id)
    fin = await _get_fin(company_id, fy_start_year)
    fy = _fy_label(fy_start_year)

    pdf = _new_pdf(landscape=True)
    _pdf_header(
        pdf, "FORM B",
        f"[See Rule 4(b), Payment of Bonus Rules, 1975] — Set-on and Set-off of Allocable Surplus (Sec 15) — Accounting Year {fy}",
        company,
    )
    headers = ["Accounting Year", "Allocable Surplus (Rs.)", "Bonus Payable (Rs.)",
               "Set-on (Rs.)", "Set-off (Rs.)", "Total Set-on / Set-off carried forward (Rs.)"]
    widths = [34, 48, 46, 42, 42, 61]
    srows = fin.get("set_on_off_rows") or []
    rows: List[List[str]] = []
    for r in srows:
        set_on = float(r.get("set_on") or 0)
        set_off = float(r.get("set_off") or 0)
        rows.append([
            str(r.get("year") or ""),
            _rs(r.get("allocable_surplus")),
            _rs(r.get("bonus_payable")),
            _rs(set_on),
            _rs(set_off),
            _rs(set_on - set_off),
        ])
    if not rows:
        rows = [[fy, "0.00", "0.00", "0.00", "0.00", "0.00"]]
    _table(pdf, headers, widths, rows, aligns=["C", "R", "R", "R", "R", "R"])
    _sig_block(pdf, company.get("name") or "")
    return _pdf_response(pdf, f"Bonus_FormB_{fy}.pdf")


# ---------------------------------------------------------------------------
# FORM C — Bonus paid to employees register
# ---------------------------------------------------------------------------

@router.get("/admin/bonus-registers/form-c.pdf")
async def bonus_form_c(
    company_id: str = Query(...),
    fy_start_year: int = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check(admin, company_id, allow_company_admin=False)
    company = await _company(company_id)
    fin = await _get_fin(company_id, fy_start_year)
    fy = _fy_label(fy_start_year)
    run = await _compute_bonus_run(company_id, fy_start_year, None, admin)

    # Join father_name / designation from the employee master.
    uids = [r["user_id"] for r in run["rows"]]
    extra = {u["user_id"]: u for u in await db.users.find(
        {"user_id": {"$in": uids}},
        {"_id": 0, "user_id": 1, "father_name": 1, "designation": 1, "position": 1},
    ).to_list(5000)}

    pdf = _new_pdf(landscape=True)
    _pdf_header(
        pdf, "FORM C",
        f"[See Rule 4(c), Payment of Bonus Rules, 1975] — Bonus paid to employees for the Accounting Year {fy}",
        company,
    )
    headers = ["Sl", "Code", "Name of employee", "Father's name",
               "Designation", "Months", "Wage Rs. p.m.",
               "Bonus Rs.", "Ded. Rs.", "Paid Rs.", "Paid on"]
    widths = [9, 16, 44, 42, 38, 16, 26, 26, 20, 26, 24]
    rows: List[List[str]] = []
    total = 0.0
    pay_date = fin.get("payment_date") or ""
    for i, r in enumerate(run["rows"], start=1):
        ex = extra.get(r["user_id"], {})
        amt = float(r.get("bonus_amount") or 0)
        total += amt
        rows.append([
            str(i),
            str(r.get("employee_code") or ""),
            r.get("name") or "",
            ex.get("father_name") or "",
            ex.get("designation") or ex.get("position") or "",
            str(r.get("months_worked") or 0),
            _rs(r.get("basic_monthly")),
            _rs(amt),
            "0.00",
            _rs(amt),
            pay_date,
        ])
    rows.append(["", "", "TOTAL", "", "", "", "", _rs(total), "0.00", _rs(total), ""])
    _table(pdf, headers, widths, rows,
           aligns=["C", "C", "L", "L", "L", "C", "R", "R", "R", "R", "C"],
           font_size=7.5)
    _sig_block(pdf, company.get("name") or "")
    return _pdf_response(pdf, f"Bonus_FormC_{fy}.pdf")


# ---------------------------------------------------------------------------
# FORM D — Annual return of bonus paid
# ---------------------------------------------------------------------------

@router.get("/admin/bonus-registers/form-d.pdf")
async def bonus_form_d(
    company_id: str = Query(...),
    fy_start_year: int = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check(admin, company_id, allow_company_admin=False)
    company = await _company(company_id)
    fin = await _get_fin(company_id, fy_start_year)
    fy = _fy_label(fy_start_year)
    run = await _compute_bonus_run(company_id, fy_start_year, None, admin)
    rate = float((run.get("policy_used") or {}).get("rate_percent") or 8.33)

    pdf = _new_pdf(landscape=False)
    _pdf_header(
        pdf, "FORM D",
        f"[See Rule 5, Payment of Bonus Rules, 1975] — Annual Return: Bonus paid to employees for the Accounting Year {fy}",
        company,
    )
    addr = ", ".join([p for p in [company.get("address"), company.get("city"),
                                  company.get("state")] if p])
    items = [
        ("1. Name of the establishment and its complete postal address",
         f"{company.get('name') or ''}, {addr}"),
        ("2. Nature of industry", fin.get("nature_of_industry") or ""),
        ("3. Name of the employer", fin.get("employer_name") or ""),
        ("4. Total number of employees", str(run.get("total_employees") or 0)),
        ("5. Number of employees benefited by bonus payments",
         str(run.get("eligible_count") or 0)),
        ("6. Percentage of bonus declared", f"{rate:g}%"),
        ("7. Total amount of bonus payable under Sec 10 / Sec 11",
         f"Rs. {_rs(run.get('total_bonus'))}"),
        ("8. Settlement, if any, reached under Sec 18(1)/12(3) of the Industrial Disputes Act with date", ""),
        ("9. Total amount of bonus actually paid", f"Rs. {_rs(run.get('total_bonus'))}"),
        ("10. Date on which payment was made", fin.get("payment_date") or ""),
        ("11. Whether bonus has been paid to all the employees; if not, reasons for non-payment", ""),
        ("12. Remarks", ""),
    ]
    pdf.set_font("Helvetica", "", 9.5)
    for label, val in items:
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.multi_cell(0, 5.5, _s(label))
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_x(20)
        pdf.multi_cell(0, 5.5, _s(val) if val else "____________________")
        pdf.ln(1.5)
    _sig_block(pdf, company.get("name") or "")
    return _pdf_response(pdf, f"Bonus_FormD_AnnualReturn_{fy}.pdf")


# ---------------------------------------------------------------------------
# Equal Remuneration Act, 1976 — Annual Return / Register (Form D)
# ---------------------------------------------------------------------------

@router.get("/admin/annual-returns/equal-remuneration.pdf")
async def er_annual_return(
    company_id: str = Query(...),
    year: int = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check(admin, company_id)
    company = await _company(company_id)

    emps = await db.users.find(
        {"role": "employee", "company_id": company_id},
        {"_id": 0, "gender": 1, "designation": 1, "position": 1,
         "salary_monthly": 1, "salary_structure_actual": 1},
    ).to_list(5000)

    # Group by category (designation); count men/women; min–max basic rate.
    cats: Dict[str, Dict[str, Any]] = {}
    for e in emps:
        cat = (e.get("designation") or e.get("position") or "GENERAL").strip().upper()
        g = (e.get("gender") or "").strip().lower()
        basic = float(e.get("salary_monthly") or 0)
        for r in (e.get("salary_structure_actual") or []):
            if isinstance(r, dict) and str(r.get("head", "")).strip().lower().startswith("basic"):
                if float(r.get("amount") or 0) > 0:
                    basic = float(r.get("amount") or 0)
                break
        c = cats.setdefault(cat, {"men": 0, "women": 0, "rates": []})
        if g.startswith("f"):
            c["women"] += 1
        else:
            c["men"] += 1
        if basic > 0:
            c["rates"].append(basic)

    pdf = _new_pdf(landscape=True)
    _pdf_header(
        pdf, "FORM D",
        f"[See Rule 6, Equal Remuneration Rules, 1976] — Register / Annual Return under the Equal Remuneration Act, 1976 — Year {year}",
        company,
    )
    headers = ["Sl", "Category of workers", "Brief description of work",
               "No. of Men employed", "No. of Women employed",
               "Rate of remuneration (Rs.)", "Remarks"]
    widths = [10, 58, 58, 34, 36, 52, 25]
    rows: List[List[str]] = []
    tot_m = tot_w = 0
    for i, (cat, c) in enumerate(sorted(cats.items()), start=1):
        tot_m += c["men"]
        tot_w += c["women"]
        rates = c["rates"]
        rate_txt = ""
        if rates:
            lo, hi = min(rates), max(rates)
            rate_txt = _rs(lo) if abs(hi - lo) < 0.01 else f"{_rs(lo)} - {_rs(hi)}"
        rows.append([str(i), cat, cat.title(), str(c["men"]), str(c["women"]),
                     rate_txt, ""])
    rows.append(["", "TOTAL", "", str(tot_m), str(tot_w), "", ""])
    _table(pdf, headers, widths, rows,
           aligns=["C", "L", "L", "C", "C", "R", "L"], font_size=8)
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8.5)
    pdf.multi_cell(0, 4.5, _s(
        "Certified that the same rates of remuneration are paid to men and women "
        "workers performing the same work or work of a similar nature, in compliance "
        "with Section 4 of the Equal Remuneration Act, 1976."))
    _sig_block(pdf, company.get("name") or "")
    return _pdf_response(pdf, f"EqualRemuneration_AnnualReturn_{year}.pdf")


# ---------------------------------------------------------------------------
# Inter-State Migrant Workmen Act, 1979 — Annual Return (Form XXIII style)
# ---------------------------------------------------------------------------

@router.get("/admin/annual-returns/ismw.pdf")
async def ismw_annual_return(
    company_id: str = Query(...),
    year: int = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check(admin, company_id)
    company = await _company(company_id)

    emps = await db.users.find(
        {"role": "employee", "company_id": company_id},
        {"_id": 0, "employee_code": 1, "name": 1, "father_name": 1,
         "designation": 1, "position": 1, "doj": 1, "exit_date": 1,
         "salary_monthly": 1, "address": 1, "present_address": 1, "gender": 1},
    ).to_list(5000)
    home_state = (company.get("state") or "").strip().lower()

    def _is_migrant(e: dict) -> bool:
        # Heuristic: permanent address mentions a different state than the
        # establishment's state. Firms should verify/adjust manually.
        adr = f"{e.get('address') or ''}".lower()
        return bool(adr) and bool(home_state) and home_state not in adr

    migrants = [e for e in emps if _is_migrant(e)]
    listing = migrants if migrants else emps

    pdf = _new_pdf(landscape=True)
    _pdf_header(
        pdf, "FORM XXIII",
        f"[See Rule 56(2), ISMW (RE&CS) Central Rules, 1980] — Annual Return of Inter-State Migrant Workmen — Year ending 31st December {year}",
        company,
    )
    pdf.set_font("Helvetica", "", 9)
    meta = [
        f"1. Full name and address of the principal employer / establishment: {company.get('name') or ''}, "
        + ", ".join([p for p in [company.get('address'), company.get('city'), company.get('state')] if p]),
        f"2. Maximum number of inter-State migrant workmen employed during the year: {len(migrants)}",
        f"3. Total number of workmen employed in the establishment: {len(emps)}",
        "4. Nature of work / operations in which migrant workmen were employed: As per occupation column below",
    ]
    for m in meta:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5, _s(m))
    pdf.ln(3)

    headers = ["Sl", "Emp Code", "Name of workman", "Father's name",
               "Occupation", "Date of employment", "Wage rate (Rs. p.m.)",
               "Home State (per address)"]
    widths = [10, 18, 48, 46, 40, 28, 30, 53]
    rows: List[List[str]] = []
    for i, e in enumerate(listing, start=1):
        rows.append([
            str(i),
            str(e.get("employee_code") or ""),
            e.get("name") or "",
            e.get("father_name") or "",
            e.get("designation") or e.get("position") or "",
            e.get("doj") or "",
            _rs(e.get("salary_monthly")) if e.get("salary_monthly") else "",
            (e.get("address") or "")[:45],
        ])
    if not rows:
        rows = [["", "", "NIL", "", "", "", "", ""]]
    _table(pdf, headers, widths, rows,
           aligns=["C", "C", "L", "L", "L", "C", "R", "L"], font_size=7.5)
    if not migrants:
        pdf.ln(3)
        pdf.set_font("Helvetica", "I", 8.5)
        pdf.multi_cell(0, 4.5, _s(
            "Note: No workman was identified as an inter-State migrant based on the "
            "address records. The full workmen listing is provided above for "
            "verification; strike out rows that do not apply."))
    _sig_block(pdf, company.get("name") or "")
    return _pdf_response(pdf, f"ISMW_AnnualReturn_{year}.pdf")
