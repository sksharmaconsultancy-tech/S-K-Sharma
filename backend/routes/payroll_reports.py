"""Iter 358 — Payroll Reports section.

New reports (existing Salary Register / Payroll Register / Bonus Registers
are linked, not duplicated):
  salary-comparison   (month A vs month B per employee)
  gross-vs-net        (gross, deductions, net, deduction %)
  salary-revision     (any gross change across the FY)
  increment           (gross increases across the FY)
  ex-gratia           (allowance head register across the FY)
  incentive           (allowance head register across the FY)
  arrear              (allowance head register across the FY)
  full-and-final      (exits in FY + last salary)
  ctc-register        (per employee monthly & annual CTC)
  ctc-analysis        (department-wise Cost-to-Company)

  GET /api/admin/payroll-reports/list
  GET /api/admin/payroll-reports/{kind}[.xlsx|.pdf]
      params: company_id, month, month_b, fy_start_year
"""
from datetime import date, datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from server import db, get_user_from_token, require_role  # noqa: E402
from utils.register_export import register_pdf, register_xlsx  # noqa: E402
from routes.labour_statistics import (_dt, _f, _users, _company,  # noqa: E402
                                      _run_rows)
from routes.annual_returns import _fy_months, _fy_rows  # noqa: E402

router = APIRouter(prefix="/api/admin/payroll-reports",
                   tags=["payroll-reports"])


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


def _prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y - (m == 1):04d}-{(m - 2) % 12 + 1:02d}"


def _head_amt(r: dict, *needles: str) -> float:
    tot = 0.0
    for a in r.get("allowances") or []:
        h = str(a.get("head") or "").lower().replace("-", "").replace(" ", "")
        if any(n in h for n in needles):
            tot += _f(a.get("amount"))
    return round(tot, 2)


def _emp_sort(rows):
    rows.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
    return rows


# each builder → (columns[(key,label)], rows, totals|None, subtitle_extra)

async def _salary_comparison(company_id, month, month_b, fy):
    m_a = month_b or _prev_month(month)
    rows_a = await _run_rows(company_id, m_a)
    rows_b = await _run_rows(company_id, month)
    users = {u["user_id"]: u for u in await _users(company_id)}
    out = []
    for uid in set(rows_a) | set(rows_b):
        u = users.get(uid) or {}
        ga = _f((rows_a.get(uid) or {}).get("gross_paid"))
        gb = _f((rows_b.get(uid) or {}).get("gross_paid"))
        na = _f((rows_a.get(uid) or {}).get("net"))
        nb = _f((rows_b.get(uid) or {}).get("net"))
        out.append({"employee_code": u.get("employee_code"),
                    "name": u.get("name"),
                    "gross_a": ga, "gross_b": gb,
                    "gross_diff": round(gb - ga, 2),
                    "net_a": na, "net_b": nb,
                    "net_diff": round(nb - na, 2),
                    "change_pct": round((gb - ga) * 100 / ga, 1) if ga else 0})
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("gross_a", f"Gross {m_a}"), ("gross_b", f"Gross {month}"),
            ("gross_diff", "Gross Diff"), ("net_a", f"Net {m_a}"),
            ("net_b", f"Net {month}"), ("net_diff", "Net Diff"),
            ("change_pct", "Change %")]
    totals = {"name": "TOTAL"}
    for k in ("gross_a", "gross_b", "gross_diff", "net_a", "net_b", "net_diff"):
        totals[k] = round(sum(r[k] for r in out), 2)
    return cols, _emp_sort(out), totals, f"{m_a} vs {month}"


async def _gross_vs_net(company_id, month, month_b, fy):
    rows = await _run_rows(company_id, month)
    users = {u["user_id"]: u for u in await _users(company_id)}
    out = []
    for uid, r in rows.items():
        u = users.get(uid) or {}
        g = _f(r.get("gross_paid"))
        d = _f(r.get("total_deduction"))
        out.append({"employee_code": u.get("employee_code"),
                    "name": u.get("name"), "gross": g, "deductions": d,
                    "net": _f(r.get("net")),
                    "deduction_pct": round(d * 100 / g, 1) if g else 0})
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("gross", "Gross Salary"), ("deductions", "Total Deductions"),
            ("net", "Net Salary"), ("deduction_pct", "Deduction %")]
    totals = {"name": "TOTAL"}
    for k in ("gross", "deductions", "net"):
        totals[k] = round(sum(r[k] for r in out), 2)
    return cols, _emp_sort(out), totals, month


async def _revision(company_id, month, month_b, fy, increments_only=False):
    by_month = await _fy_rows(company_id, fy)
    users = {u["user_id"]: u for u in await _users(company_id)}
    months = [m for m in _fy_months(fy) if m in by_month]
    last_gross: Dict[str, float] = {}
    last_month: Dict[str, str] = {}
    out = []
    for m in months:
        for r in by_month[m]:
            uid = r.get("user_id")
            g = _f(r.get("monthly_gross")) or _f(r.get("gross_paid"))
            if uid in last_gross and g and last_gross[uid] and \
                    abs(g - last_gross[uid]) > 1:
                diff = round(g - last_gross[uid], 2)
                if not increments_only or diff > 0:
                    u = users.get(uid) or {}
                    out.append({
                        "employee_code": u.get("employee_code"),
                        "name": u.get("name"),
                        "from_month": last_month[uid], "to_month": m,
                        "old_gross": last_gross[uid], "new_gross": g,
                        "difference": diff,
                        "change_pct": round(diff * 100 / last_gross[uid], 1)})
            if g:
                last_gross[uid] = g
                last_month[uid] = m
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("from_month", "From Month"), ("to_month", "Effective Month"),
            ("old_gross", "Old Gross"), ("new_gross", "New Gross"),
            ("difference", "Difference"), ("change_pct", "Change %")]
    return cols, _emp_sort(out), None, f"FY {fy}-{str(fy + 1)[-2:]}"


async def _head_register(company_id, fy, needles, label):
    by_month = await _fy_rows(company_id, fy)
    users = {u["user_id"]: u for u in await _users(company_id)}
    per_emp: Dict[str, dict] = {}
    months = [m for m in _fy_months(fy) if m in by_month]
    for m in months:
        for r in by_month[m]:
            amt = _head_amt(r, *needles)
            if not amt:
                continue
            uid = r.get("user_id")
            u = users.get(uid) or {}
            d = per_emp.setdefault(uid, {
                "employee_code": u.get("employee_code"),
                "name": u.get("name"), "total": 0.0})
            d[m] = round(d.get(m, 0) + amt, 2)
            d["total"] = round(d["total"] + amt, 2)
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name")] + \
        [(m, m) for m in months] + [("total", f"Total {label}")]
    out = _emp_sort(list(per_emp.values()))
    totals = {"name": "TOTAL"}
    for m in months + ["total"]:
        totals[m] = round(sum(_f(r.get(m)) for r in out), 2)
    return cols, out, totals, f"FY {fy}-{str(fy + 1)[-2:]}"


async def _fnf(company_id, month, month_b, fy):
    users = await _users(company_id)
    fy_start, fy_end = date(fy, 4, 1), date(fy + 1, 3, 31)
    by_month = await _fy_rows(company_id, fy)
    rows_by_m = {m: {r.get("user_id"): r for r in rr}
                 for m, rr in by_month.items()}
    out = []
    for u in users:
        dol = _dt(u.get("exit_date") or u.get("resign_date"))
        if not dol or not (fy_start <= dol <= fy_end):
            continue
        last_m, last_r = "", {}
        for m in sorted(rows_by_m):
            if u["user_id"] in rows_by_m[m]:
                last_m, last_r = m, rows_by_m[m][u["user_id"]]
        doj = _dt(u.get("doj"))
        out.append({
            "employee_code": u.get("employee_code"), "name": u.get("name"),
            "doj": u.get("doj"), "dol": dol.isoformat(),
            "service_years": (round((dol - doj).days / 365, 1) if doj else 0),
            "last_salary_month": last_m,
            "last_gross": _f(last_r.get("gross_paid")),
            "last_net": _f(last_r.get("net")),
            "gratuity_due": ("Yes" if doj
                             and (dol - doj).days >= 5 * 365 else "No"),
        })
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("doj", "DOJ"), ("dol", "DOL"),
            ("service_years", "Service (yrs)"),
            ("last_salary_month", "Last Salary Month"),
            ("last_gross", "Last Gross"), ("last_net", "Last Net"),
            ("gratuity_due", "Gratuity Due")]
    return cols, _emp_sort(out), None, f"FY {fy}-{str(fy + 1)[-2:]}"


async def _ctc_register(company_id, month, month_b, fy):
    rows = await _run_rows(company_id, month)
    users = {u["user_id"]: u for u in await _users(company_id)}
    out = []
    for uid, r in rows.items():
        u = users.get(uid) or {}
        g = _f(r.get("gross_paid"))
        pf = _f(r.get("pf_employer_total"))
        es = _f(r.get("esic_employer"))
        ctc = round(g + pf + es, 2)
        out.append({"employee_code": u.get("employee_code"),
                    "name": u.get("name"),
                    "department": u.get("department"), "gross": g,
                    "employer_pf": pf, "employer_esic": es,
                    "monthly_ctc": ctc,
                    "annual_ctc": round(ctc * 12, 2)})
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("department", "Department"), ("gross", "Gross"),
            ("employer_pf", "Employer PF"), ("employer_esic", "Employer ESIC"),
            ("monthly_ctc", "Monthly CTC"), ("annual_ctc", "Annual CTC")]
    totals = {"name": "TOTAL"}
    for k in ("gross", "employer_pf", "employer_esic", "monthly_ctc",
              "annual_ctc"):
        totals[k] = round(sum(r[k] for r in out), 2)
    return cols, _emp_sort(out), totals, month


async def _ctc_analysis(company_id, month, month_b, fy):
    rows = await _run_rows(company_id, month)
    users = {u["user_id"]: u for u in await _users(company_id)}
    depts: Dict[str, dict] = {}
    for uid, r in rows.items():
        u = users.get(uid) or {}
        d = depts.setdefault(str(u.get("department") or "GENERAL").upper(),
                             {"employees": 0, "gross": 0.0, "er": 0.0})
        d["employees"] += 1
        d["gross"] += _f(r.get("gross_paid"))
        d["er"] += _f(r.get("pf_employer_total")) + _f(r.get("esic_employer"))
    total_ctc = sum(d["gross"] + d["er"] for d in depts.values()) or 1
    out = []
    for dn in sorted(depts):
        d = depts[dn]
        ctc = round(d["gross"] + d["er"], 2)
        out.append({"department": dn, "employees": d["employees"],
                    "gross": round(d["gross"], 2),
                    "employer_cost": round(d["er"], 2), "monthly_ctc": ctc,
                    "annual_ctc": round(ctc * 12, 2),
                    "avg_ctc_per_employee": round(ctc / d["employees"], 2),
                    "share_pct": round(ctc * 100 / total_ctc, 1)})
    cols = [("department", "Department"), ("employees", "Employees"),
            ("gross", "Gross"), ("employer_cost", "Employer Cost"),
            ("monthly_ctc", "Monthly CTC"), ("annual_ctc", "Annual CTC"),
            ("avg_ctc_per_employee", "Avg CTC / Employee"),
            ("share_pct", "Share %")]
    totals = {"department": "TOTAL"}
    for k in ("employees", "gross", "employer_cost", "monthly_ctc",
              "annual_ctc"):
        totals[k] = round(sum(r[k] for r in out), 2)
    return cols, out, totals, month


async def _ot_department(company_id, month, month_b, fy):
    rows = await _run_rows(company_id, month)
    users = {u["user_id"]: u for u in await _users(company_id)}
    depts: Dict[str, dict] = {}
    for uid, r in rows.items():
        u = users.get(uid) or {}
        d = depts.setdefault(str(u.get("department") or "GENERAL").upper(),
                             {"emp": 0, "ot_emp": 0, "hrs": 0.0, "pay": 0.0,
                              "gross": 0.0})
        d["emp"] += 1
        d["gross"] += _f(r.get("gross_paid"))
        oh, op = _f(r.get("ot_hours")), _f(r.get("ot_pay"))
        if oh or op:
            d["ot_emp"] += 1
            d["hrs"] += oh
            d["pay"] += op
    out = []
    for dn in sorted(depts):
        d = depts[dn]
        out.append({"department": dn, "employees": d["emp"],
                    "ot_employees": d["ot_emp"],
                    "ot_hours": round(d["hrs"], 1),
                    "ot_cost": round(d["pay"], 2),
                    "avg_ot_hours": (round(d["hrs"] / d["ot_emp"], 1)
                                     if d["ot_emp"] else 0),
                    "ot_vs_salary_pct": (round(d["pay"] * 100 / d["gross"], 1)
                                         if d["gross"] else 0)})
    cols = [("department", "Department"), ("employees", "Employees"),
            ("ot_employees", "OT Employees"), ("ot_hours", "OT Hours"),
            ("ot_cost", "OT Cost"), ("avg_ot_hours", "Avg OT Hours"),
            ("ot_vs_salary_pct", "OT vs Salary %")]
    totals = {"department": "TOTAL"}
    for k in ("employees", "ot_employees", "ot_hours", "ot_cost"):
        totals[k] = round(sum(r[k] for r in out), 2)
    return cols, out, totals, month


async def _ot_daily(company_id, month, month_b, fy):
    recs = await db.attendance.find(
        {"company_id": company_id, "timestamp": {"$regex": f"^{month}"}},
        {"_id": 0, "user_id": 1, "timestamp": 1}).to_list(500000)
    by_day: Dict[str, Dict[str, List[str]]] = {}
    for r in recs:
        ts = str(r.get("timestamp"))
        by_day.setdefault(ts[:10], {}).setdefault(
            r["user_id"], []).append(ts[11:16])
    out = []
    for day in sorted(by_day):
        ot_emp, ot_hrs = 0, 0.0
        for times in by_day[day].values():
            times.sort()
            if len(times) > 1:
                try:
                    h1, m1 = map(int, times[0].split(":"))
                    h2, m2 = map(int, times[-1].split(":"))
                    hrs = (h2 * 60 + m2 - h1 * 60 - m1) / 60
                    if hrs > 8:
                        ot_emp += 1
                        ot_hrs += hrs - 8
                except ValueError:
                    continue
        out.append({"date": day, "punched_employees": len(by_day[day]),
                    "ot_employees": ot_emp, "ot_hours": round(ot_hrs, 1)})
    cols = [("date", "Date"), ("punched_employees", "Employees Punched"),
            ("ot_employees", "Employees on OT"), ("ot_hours", "OT Hours")]
    totals = {"date": "TOTAL",
              "ot_employees": sum(r["ot_employees"] for r in out),
              "ot_hours": round(sum(r["ot_hours"] for r in out), 1)}
    return cols, out, totals, month


async def _ot_cost_analysis(company_id, month, month_b, fy):
    by_month = await _fy_rows(company_id, fy)
    out = []
    for m in _fy_months(fy):
        rows = by_month.get(m)
        if not rows:
            continue
        gross = sum(_f(r.get("gross_paid")) for r in rows)
        hrs = sum(_f(r.get("ot_hours")) for r in rows)
        pay = sum(_f(r.get("ot_pay")) for r in rows)
        n = sum(1 for r in rows if _f(r.get("ot_pay")) > 0)
        out.append({"month": m, "ot_employees": n,
                    "ot_hours": round(hrs, 1), "ot_cost": round(pay, 2),
                    "salary_cost": round(gross, 2),
                    "ot_pct_of_salary": round(pay * 100 / gross, 1)
                    if gross else 0,
                    "cost_per_ot_hour": round(pay / hrs, 2) if hrs else 0})
    cols = [("month", "Month"), ("ot_employees", "OT Employees"),
            ("ot_hours", "OT Hours"), ("ot_cost", "OT Cost"),
            ("salary_cost", "Salary Cost"),
            ("ot_pct_of_salary", "OT % of Salary"),
            ("cost_per_ot_hour", "Cost / OT Hour")]
    totals = {"month": "TOTAL"}
    for k in ("ot_employees", "ot_hours", "ot_cost", "salary_cost"):
        totals[k] = round(sum(r[k] for r in out), 2)
    return cols, out, totals, f"FY {fy}-{str(fy + 1)[-2:]}"


_REPORTS = {
    "salary-comparison": ("Salary Comparison", _salary_comparison),
    "gross-vs-net": ("Gross vs Net Analysis", _gross_vs_net),
    "salary-revision": ("Salary Revision Report",
                        lambda c, m, b, f: _revision(c, m, b, f, False)),
    "increment": ("Increment Report",
                  lambda c, m, b, f: _revision(c, m, b, f, True)),
    "ex-gratia": ("Ex-gratia Register",
                  lambda c, m, b, f: _head_register(c, f, ("exgratia",),
                                                    "Ex-gratia")),
    "incentive": ("Incentive Register",
                  lambda c, m, b, f: _head_register(c, f, ("incent",),
                                                    "Incentive")),
    "arrear": ("Arrear Register",
               lambda c, m, b, f: _head_register(c, f, ("arrear",),
                                                 "Arrear")),
    "full-and-final": ("Full & Final Settlement", _fnf),
    "ctc-register": ("CTC Register", _ctc_register),
    "ctc-analysis": ("Cost to Company Analysis", _ctc_analysis),
    "ot-department": ("Department-wise OT Register", _ot_department),
    "ot-daily": ("Daily OT Register", _ot_daily),
    "ot-cost-analysis": ("OT Cost Analysis (FY)", _ot_cost_analysis),
}
# reports that already exist elsewhere in the portal (linked, not rebuilt)
_LINKS = [
    {"title": "Salary Register", "route": "/salary-register"},
    {"title": "Payroll Register (Yearly)", "route": "/payroll-register"},
    {"title": "Bonus Registers (A, B, D)", "route": "/bonus-registers"},
    {"title": "Bonus Yearly Summary", "route": "/bonus-yearly-summary"},
]


@router.get("/list")
async def list_reports(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    return {"reports": [{"kind": k, "title": t}
                        for k, (t, _fn) in _REPORTS.items()],
            "existing": _LINKS}


@router.get("/{kind}")
async def report_json(kind: str, company_id: Optional[str] = None,
                      month: Optional[str] = None,
                      month_b: Optional[str] = None, fy_start_year: int = 0,
                      authorization: Optional[str] = Header(None)):
    for ext in ("xlsx", "pdf"):
        if kind.endswith(f".{ext}"):
            return await _exp(kind[: -len(ext) - 1], company_id, month,
                              month_b, fy_start_year, authorization, ext)
    if kind not in _REPORTS:
        raise HTTPException(status_code=404, detail="Unknown report")
    company_id = await _adm(authorization, company_id)
    month = month or date.today().strftime("%Y-%m")
    fy = _fy_or_now(fy_start_year)
    title, fn = _REPORTS[kind]
    cols, rows, totals, extra = await fn(company_id, month, month_b, fy)
    return {"title": title, "subtitle": extra,
            "columns": [{"key": k, "label": lb} for k, lb in cols],
            "rows": rows, "totals": totals}


async def _exp(kind, company_id, month, month_b, fy_start_year,
               authorization, fmt):
    if kind not in _REPORTS:
        raise HTTPException(status_code=404, detail="Unknown report")
    company_id = await _adm(authorization, company_id)
    month = month or date.today().strftime("%Y-%m")
    fy = _fy_or_now(fy_start_year)
    c = await _company(company_id)
    title, fn = _REPORTS[kind]
    cols, rows, totals, extra = await fn(company_id, month, month_b, fy)
    columns = [{"key": k, "label": lb} for k, lb in cols]
    sub = f"{c.get('name')} · {extra} · Generated {datetime.now():%d-%m-%Y}"
    if fmt == "xlsx":
        buf = register_xlsx(title, sub, columns, rows, totals)
        mt = ("application/vnd.openxmlformats-officedocument"
              ".spreadsheetml.sheet")
    else:
        buf = register_pdf(title, sub, columns, rows, totals,
                           c.get("logo_base64"))
        mt = "application/pdf"
    fn_ = f"{title.replace(' ', '_')}.{fmt}"
    return StreamingResponse(buf, media_type=mt, headers={
        "Content-Disposition": f'attachment; filename="{fn_}"'})
