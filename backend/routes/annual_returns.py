"""Iter 357 — Phase C: Annual Returns Management.

Statutory annual returns auto-prepared from FY compliance salary runs +
Employee Master. Register-style PDF/Excel via utils.register_export.

  GET /api/admin/annual-returns/list
  GET /api/admin/annual-returns/dashboard
  GET /api/admin/annual-returns/{kind}            (JSON)
  GET /api/admin/annual-returns/{kind}.xlsx|.pdf
kinds: minimum-wages, payment-of-wages, bonus, equal-remuneration,
       employment-statistics, social-security, lwf, pt
"""
from datetime import date, datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from server import db, get_user_from_token, require_role  # noqa: E402
from utils.register_export import register_pdf, register_xlsx  # noqa: E402
from routes.labour_statistics import (_active, _bucket, _dt, _f,  # noqa: E402
                                      _gender, _users, _company)

router = APIRouter(prefix="/api/admin/annual-returns", tags=["annual-returns"])


def _fy_months(fy: int) -> List[str]:
    return [f"{fy + (i >= 9):04d}-{((3 + i) % 12) + 1:02d}" for i in range(12)]


async def _fy_rows(company_id: str, fy: int) -> Dict[str, List[dict]]:
    """month -> salary run rows for the FY."""
    out: Dict[str, List[dict]] = {}
    for m in _fy_months(fy):
        run = await db.compliance_salary_runs.find_one(
            {"company_id": company_id, "month": m}, {"_id": 0, "rows": 1},
            sort=[("generated_at", -1)])
        if run:
            out[m] = run.get("rows") or []
    return out


async def _adm(authorization, company_id):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return company_id


def _fy_or_now(fy: int) -> int:
    return fy or (date.today().year if date.today().month >= 4
                  else date.today().year - 1)


# ---------------------------------------------------------------------------
# return builders — each returns (columns, rows, totals)
# ---------------------------------------------------------------------------

async def _minimum_wages(company_id: str, fy: int):
    users = {u["user_id"]: u for u in await _users(company_id)}
    by_month = await _fy_rows(company_id, fy)
    cats: Dict[str, dict] = {}
    firm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "minimum_wage": 1,
                                     "min_wage": 1})
    min_wage = _f((firm or {}).get("minimum_wage") or (firm or {}).get("min_wage"))
    for rows in by_month.values():
        for r in rows:
            u = users.get(r.get("user_id")) or {}
            c = _bucket(u)
            d = cats.setdefault(c, {"category": c, "employees": set(),
                                    "basic": 0, "da": 0, "hra": 0,
                                    "allowances": 0, "gross": 0})
            d["employees"].add(r.get("user_id"))
            d["basic"] += _f(r.get("basic"))
            d["hra"] += _f(r.get("hra"))
            d["allowances"] += (_f(r.get("conveyance")) + _f(r.get("special"))
                                + _f(r.get("medical")) + _f(r.get("others")))
            d["gross"] += _f(r.get("gross_paid"))
    out = []
    for c in sorted(cats):
        d = cats[c]
        n = len(d["employees"]) or 1
        avg_gross = d["gross"] / max(1, len(by_month)) / n
        out.append({
            "category": c, "employees": len(d["employees"]),
            "basic": round(d["basic"], 2), "da": round(d["da"], 2),
            "hra": round(d["hra"], 2),
            "allowances": round(d["allowances"], 2),
            "gross": round(d["gross"], 2),
            "min_wage": min_wage,
            "avg_monthly_gross": round(avg_gross, 2),
            "difference": round(avg_gross - min_wage, 2) if min_wage else 0,
            "compliance_pct": (100.0 if not min_wage or avg_gross >= min_wage
                               else round(avg_gross * 100 / min_wage, 1)),
        })
    cols = [("category", "Category"), ("employees", "Employees"),
            ("basic", "Basic Wages"), ("da", "DA"), ("hra", "HRA"),
            ("allowances", "Allowances"), ("gross", "Gross Salary"),
            ("min_wage", "Minimum Wage"),
            ("avg_monthly_gross", "Avg Monthly Gross"),
            ("difference", "Difference"), ("compliance_pct", "Compliance %")]
    return cols, out, None


async def _payment_of_wages(company_id: str, fy: int):
    by_month = await _fy_rows(company_id, fy)
    out = []
    for m in _fy_months(fy):
        rows = by_month.get(m)
        if not rows:
            continue
        out.append({
            "month": m,
            "employees": len([r for r in rows if _f(r.get("gross_paid")) > 0]),
            "gross": round(sum(_f(r.get("gross_paid")) for r in rows), 2),
            "pf": round(sum(_f(r.get("pf_employee")) for r in rows), 2),
            "esic": round(sum(_f(r.get("esic_employee")) for r in rows), 2),
            "pt": round(sum(_f(r.get("pt")) for r in rows), 2),
            "lwf": round(sum(_f(r.get("lwf")) for r in rows), 2),
            "fines": 0,
            "advances": round(sum(_f(r.get("advance")) for r in rows), 2),
            "deductions": round(sum(_f(r.get("total_deduction"))
                                    for r in rows), 2),
            "net": round(sum(_f(r.get("net")) for r in rows), 2),
            "payment_mode": "Bank",
        })
    cols = [("month", "Month"), ("employees", "Employees Covered"),
            ("gross", "Gross Wages"), ("deductions", "Deductions"),
            ("pf", "PF"), ("esic", "ESIC"), ("pt", "PT"), ("lwf", "LWF"),
            ("fines", "Fines"), ("advances", "Advances"),
            ("net", "Net Wages"), ("payment_mode", "Payment Mode")]
    totals = {k: round(sum(_f(r.get(k)) for r in out), 2)
              for k, _ in cols[1:-1]}
    totals["month"] = "TOTAL"
    return cols, out, totals


async def _bonus_return(company_id: str, fy: int):
    users = {u["user_id"]: u for u in await _users(company_id)}
    by_month = await _fy_rows(company_id, fy)
    firm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "bonus_percent": 1})
    pct = _f((firm or {}).get("bonus_percent")) or 8.33
    per_emp: Dict[str, dict] = {}
    for rows in by_month.values():
        for r in rows:
            uid = r.get("user_id")
            d = per_emp.setdefault(uid, {"wages": 0.0, "months": 0})
            base = min(_f(r.get("basic")), 7000) if _f(r.get("basic")) else 0
            d["wages"] += base
            d["months"] += 1
    out = []
    for uid, d in per_emp.items():
        u = users.get(uid) or {}
        gross_avg = d["wages"] / (d["months"] or 1)
        eligible = 0 < gross_avg  # worked at least a month with basic
        bonus = round(d["wages"] * pct / 100, 2)
        out.append({
            "employee_code": u.get("employee_code"), "name": u.get("name"),
            "months_worked": d["months"],
            "bonus_wages": round(d["wages"], 2),
            "bonus_pct": pct,
            "bonus_amount": bonus if eligible else 0,
            "eligible": "Yes" if eligible else "No",
        })
    out.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("months_worked", "Months Worked"),
            ("bonus_wages", "Bonus Wages (capped 7000)"),
            ("bonus_pct", "Bonus %"), ("bonus_amount", "Bonus Amount"),
            ("eligible", "Eligible")]
    totals = {"name": "TOTAL",
              "bonus_wages": round(sum(r["bonus_wages"] for r in out), 2),
              "bonus_amount": round(sum(r["bonus_amount"] for r in out), 2)}
    return cols, out, totals


async def _equal_remuneration(company_id: str, fy: int):
    users = {u["user_id"]: u for u in await _users(company_id)}
    by_month = await _fy_rows(company_id, fy)
    agg: Dict[str, dict] = {}
    for rows in by_month.values():
        for r in rows:
            u = users.get(r.get("user_id")) or {}
            key = f"{str(u.get('department') or 'GENERAL').upper()}|{_bucket(u)}"
            d = agg.setdefault(key, {"m_n": set(), "f_n": set(),
                                     "m_g": 0.0, "f_g": 0.0,
                                     "m_mm": 0, "f_mm": 0})
            g = _gender(u)
            if g == "Male":
                d["m_n"].add(r.get("user_id"))
                d["m_g"] += _f(r.get("gross_paid"))
                d["m_mm"] += 1
            elif g == "Female":
                d["f_n"].add(r.get("user_id"))
                d["f_g"] += _f(r.get("gross_paid"))
                d["f_mm"] += 1
    out = []
    for key in sorted(agg):
        d = agg[key]
        dept, cat = key.split("|")
        m_avg = d["m_g"] / (d["m_mm"] or 1)
        f_avg = d["f_g"] / (d["f_mm"] or 1)
        out.append({
            "department": dept, "category": cat,
            "male": len(d["m_n"]), "female": len(d["f_n"]),
            "male_avg_salary": round(m_avg, 2),
            "female_avg_salary": round(f_avg, 2),
            "variance_pct": (round((m_avg - f_avg) * 100 / m_avg, 1)
                             if m_avg and d["f_mm"] else 0),
        })
    cols = [("department", "Department"), ("category", "Category"),
            ("male", "Male"), ("female", "Female"),
            ("male_avg_salary", "Male Avg Salary"),
            ("female_avg_salary", "Female Avg Salary"),
            ("variance_pct", "Variance %")]
    return cols, out, None


async def _employment_statistics(company_id: str, fy: int):
    users = await _users(company_id)
    fy_start, fy_end = date(fy, 4, 1), date(fy + 1, 3, 31)

    def _exit(u):
        return _dt(u.get("exit_date") or u.get("resign_date"))
    opening = sum(1 for u in users if (_dt(u.get("doj")) or date.min) < fy_start
                  and (not _exit(u) or _exit(u) >= fy_start))
    joins = [u for u in users if _dt(u.get("doj"))
             and fy_start <= _dt(u.get("doj")) <= fy_end]
    exits = [u for u in users if _exit(u) and fy_start <= _exit(u) <= fy_end]
    resign = [u for u in exits if "termin" not in
              str(u.get("employment_status") or "").lower()]
    closing = opening + len(joins) - len(exits)
    act = [u for u in users if _active(u)]
    rows = [{"particular": p, "value": v} for p, v in [
        ("Opening Strength", opening),
        ("Joining", len(joins)),
        ("Resignation", len(resign)),
        ("Termination", len(exits) - len(resign)),
        ("Closing Strength", closing),
        ("Male (current)", sum(1 for u in act if _gender(u) == "Male")),
        ("Female (current)", sum(1 for u in act if _gender(u) == "Female")),
        ("Contract (current)", sum(1 for u in act if _bucket(u) == "Contract")),
        ("Permanent (current)", sum(1 for u in act
                                    if _bucket(u) != "Contract")),
    ]]
    return [("particular", "Particular"), ("value", "Value")], rows, None


async def _social_security(company_id: str, fy: int):
    users = await _users(company_id)
    act = [u for u in users if _active(u)]
    today = date.today()
    rows = [{"particular": p, "value": v} for p, v in [
        ("PF Employees (PF No.)", sum(1 for u in act if u.get("pf_no"))),
        ("UAN Generated", sum(1 for u in act if u.get("uan_no"))),
        ("ESIC Employees (IP)", sum(1 for u in act if u.get("esi_ip_no"))),
        ("Pension Members (UAN + PF)", sum(
            1 for u in act if u.get("uan_no") and u.get("pf_no"))),
        ("Gratuity Eligible (5+ yrs)", sum(
            1 for u in act if _dt(u.get("doj"))
            and (today - _dt(u.get("doj"))).days >= 5 * 365)),
        ("Bonus Eligible (gross ≤ 21000)", sum(
            1 for u in act if 0 < _f(u.get("compliance_gross")
                                     or u.get("salary_monthly")) <= 21000)),
        ("Total Active Employees", len(act)),
    ]]
    return [("particular", "Particular"), ("value", "Value")], rows, None


async def _lwf(company_id: str, fy: int):
    by_month = await _fy_rows(company_id, fy)
    out = []
    for m in _fy_months(fy):
        rows = by_month.get(m)
        if not rows:
            continue
        emp = sum(_f(r.get("lwf")) for r in rows)
        covered = sum(1 for r in rows if _f(r.get("lwf")) > 0)
        out.append({"month": m, "employees_covered": covered,
                    "employee_contribution": round(emp, 2),
                    "employer_contribution": round(emp * 2, 2),
                    "total_paid": round(emp * 3, 2), "challan_no": ""})
    cols = [("month", "Month"), ("employees_covered", "Employees Covered"),
            ("employee_contribution", "Employee Contribution"),
            ("employer_contribution", "Employer Contribution"),
            ("total_paid", "Amount Paid"), ("challan_no", "Challan No.")]
    totals = {k: round(sum(_f(r.get(k)) for r in out), 2)
              for k, _ in cols[1:-1]}
    totals["month"] = "TOTAL"
    return cols, out, totals


async def _pt(company_id: str, fy: int):
    by_month = await _fy_rows(company_id, fy)
    out = []
    for m in _fy_months(fy):
        rows = by_month.get(m)
        if not rows:
            continue
        amt = sum(_f(r.get("pt")) for r in rows)
        out.append({"month": m,
                    "employees": sum(1 for r in rows if _f(r.get("pt")) > 0),
                    "tax_collected": round(amt, 2),
                    "amount_deposited": round(amt, 2), "balance": 0})
    cols = [("month", "Month"), ("employees", "Employees"),
            ("tax_collected", "Tax Collected"),
            ("amount_deposited", "Amount Deposited"), ("balance", "Balance")]
    totals = {k: round(sum(_f(r.get(k)) for r in out), 2) for k, _ in cols[1:]}
    totals["month"] = "TOTAL"
    return cols, out, totals


_RETURNS = {
    "minimum-wages": ("Minimum Wages Annual Return", _minimum_wages),
    "payment-of-wages": ("Payment of Wages Annual Return", _payment_of_wages),
    "bonus": ("Payment of Bonus Annual Return", _bonus_return),
    "equal-remuneration": ("Equal Remuneration Report", _equal_remuneration),
    "employment-statistics": ("Employment Statistics Return",
                              _employment_statistics),
    "social-security": ("Social Security Statistics", _social_security),
    "lwf": ("Labour Welfare Fund Return", _lwf),
    "pt": ("Professional Tax Annual Return", _pt),
}


@router.get("/list")
async def list_returns(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    return {"returns": [{"kind": k, "title": t}
                        for k, (t, _f_) in _RETURNS.items()]}


@router.get("/dashboard")
async def returns_dashboard(company_id: Optional[str] = None,
                            fy_start_year: int = 0,
                            authorization: Optional[str] = Header(None)):
    company_id = await _adm(authorization, company_id)
    fy = _fy_or_now(fy_start_year)
    by_month = await _fy_rows(company_id, fy)
    users = await _users(company_id)
    act = [u for u in users if _active(u)]
    missing_pf = sum(1 for u in act if not (u.get("pf_no") or u.get("uan_no")))
    missing_esic = sum(1 for u in act if not u.get("esi_ip_no"))
    months_ready = len(by_month)
    items = []
    for k, (t, _f_) in _RETURNS.items():
        items.append({
            "kind": k, "title": t,
            "status": "READY" if months_ready else "NO DATA",
            "due": f"{fy + 1}-04-30",
        })
    score = round(months_ready * 100 / 12, 1)
    validations = []
    if missing_pf:
        validations.append(f"{missing_pf} employees missing PF/UAN number")
    if missing_esic:
        validations.append(f"{missing_esic} employees missing ESIC number")
    if months_ready < 12:
        validations.append(
            f"Salary runs found for only {months_ready}/12 months of the FY")
    return {"fy_start_year": fy, "months_ready": months_ready,
            "returns": items, "compliance_pct": score,
            "validations": validations or ["All checks passed"]}


@router.get("/{kind}")
async def return_json(kind: str, company_id: Optional[str] = None,
                      fy_start_year: int = 0,
                      authorization: Optional[str] = Header(None)):
    for ext in ("xlsx", "pdf"):  # /{kind} matches before /{kind}.{ext}
        if kind.endswith(f".{ext}"):
            return await _exp(kind[: -len(ext) - 1], company_id,
                              fy_start_year, authorization, ext)
    if kind not in _RETURNS:
        raise HTTPException(status_code=404, detail="Unknown return")
    company_id = await _adm(authorization, company_id)
    fy = _fy_or_now(fy_start_year)
    title, fn = _RETURNS[kind]
    cols, rows, totals = await fn(company_id, fy)
    return {"title": title, "fy_start_year": fy,
            "columns": [{"key": k, "label": lb} for k, lb in cols],
            "rows": rows, "totals": totals}


@router.get("/{kind}.xlsx")
async def return_xlsx(kind: str, company_id: Optional[str] = None,
                      fy_start_year: int = 0,
                      authorization: Optional[str] = Header(None)):
    return await _exp(kind, company_id, fy_start_year, authorization, "xlsx")


@router.get("/{kind}.pdf")
async def return_pdf(kind: str, company_id: Optional[str] = None,
                     fy_start_year: int = 0,
                     authorization: Optional[str] = Header(None)):
    return await _exp(kind, company_id, fy_start_year, authorization, "pdf")


async def _exp(kind, company_id, fy_start_year, authorization, fmt):
    if kind not in _RETURNS:
        raise HTTPException(status_code=404, detail="Unknown return")
    company_id = await _adm(authorization, company_id)
    fy = _fy_or_now(fy_start_year)
    c = await _company(company_id)
    title, fn = _RETURNS[kind]
    cols, rows, totals = await fn(company_id, fy)
    columns = [{"key": k, "label": lb} for k, lb in cols]
    sub = (f"{c.get('name')} · FY {fy}-{str(fy + 1)[-2:]} · "
           f"Generated {datetime.now():%d-%m-%Y}")
    if fmt == "xlsx":
        buf = register_xlsx(title, sub, columns, rows, totals)
        mt = ("application/vnd.openxmlformats-officedocument"
              ".spreadsheetml.sheet")
    else:
        buf = register_pdf(title, sub, columns, rows, totals,
                           c.get("logo_base64"))
        mt = "application/pdf"
    fn_ = f"{title.replace(' ', '_')}_FY{fy}.{fmt}"
    return StreamingResponse(buf, media_type=mt, headers={
        "Content-Disposition": f'attachment; filename="{fn_}"'})
