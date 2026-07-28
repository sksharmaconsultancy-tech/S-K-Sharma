"""Iter 357 — Phase B: Labour Statistics & HR Analytics.

Auto-calculated from Employee Master (users), attendance and the latest
compliance salary runs — no manual entry.

  GET /api/admin/labour-stats/dashboard        (Module 10 — live KPIs + AI insights)
  GET /api/admin/labour-stats/department       (Module 1 register)
  GET /api/admin/labour-stats/category         (Module 2 register)
  GET /api/admin/labour-stats/monthly-return   (Module 7)
  GET /api/admin/labour-stats/turnover         (Module 8, FY trend)
  GET /api/admin/labour-stats/welfare          (Module 6)
  GET /api/admin/labour-stats/{kind}.xlsx|.pdf (register-style exports)
"""
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from server import db, get_user_from_token, require_role  # noqa: E402
from utils.register_export import register_pdf, register_xlsx  # noqa: E402

router = APIRouter(prefix="/api/admin/labour-stats", tags=["labour-stats"])

_LEFT = ("exited", "resigned", "terminated", "inactive", "left")


def _active(u: dict) -> bool:
    return not (u.get("disabled") or u.get("active") is False
                or str(u.get("employment_status") or "").lower() in _LEFT)


def _dt(v) -> Optional[date]:
    if not v:
        return None
    s = str(v)[:10]
    for f in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def _bucket(u: dict) -> str:
    txt = " ".join(str(u.get(k) or "") for k in
                   ("employee_group", "employee_type", "designation")).lower()
    for kw, lbl in (("highly skill", "Highly Skilled"), ("semi", "Semi Skilled"),
                    ("unskill", "Unskilled"), ("skill", "Skilled"),
                    ("supervis", "Supervisor"), ("engineer", "Engineer"),
                    ("executive", "Executive"), ("manager", "Manager"),
                    ("management", "Manager"), ("apprentice", "Apprentice"),
                    ("trainee", "Trainee"), ("contract", "Contract"),
                    ("staff", "Staff")):
        if kw in txt:
            return lbl
    return "Workers"


def _gender(u: dict) -> str:
    g = str(u.get("gender") or "").lower()
    if g.startswith("m"):
        return "Male"
    if g.startswith("f"):
        return "Female"
    return "Other"


async def _company(company_id: str) -> dict:
    c = await db.companies.find_one({"company_id": company_id},
                                    {"_id": 0, "name": 1, "logo_base64": 1})
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    return c


async def _users(company_id: str) -> List[dict]:
    return await db.users.find(
        {"company_id": company_id, "role": "employee"},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "gender": 1,
         "department": 1, "designation": 1, "employee_group": 1,
         "employee_type": 1, "doj": 1, "dob": 1, "exit_date": 1,
         "resign_date": 1, "employment_status": 1, "disabled": 1, "active": 1,
         "pf_no": 1, "uan_no": 1, "esi_ip_no": 1,
         "salary_monthly": 1, "compliance_gross": 1}).to_list(200000)


async def _run_rows(company_id: str, month: str) -> Dict[str, dict]:
    run = await db.compliance_salary_runs.find_one(
        {"company_id": company_id, "month": month}, {"_id": 0, "rows": 1},
        sort=[("generated_at", -1)])
    return {r.get("user_id"): r for r in (run or {}).get("rows") or []}


def _f(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _month_now() -> str:
    return date.today().strftime("%Y-%m")


def _month_range(month: str):
    y, m = int(month[:4]), int(month[5:7])
    start = date(y, m, 1)
    end = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
    return start, end


def _exit_date(u):
    return _dt(u.get("exit_date") or u.get("resign_date"))


async def _admin(authorization, company_id):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return company_id


# ---------------------------------------------------------------------------
# register datasets (shared by JSON + exports)
# ---------------------------------------------------------------------------

async def _dept_register(company_id: str, month: str):
    users = await _users(company_id)
    rows_by_uid = await _run_rows(company_id, month)
    start, end = _month_range(month)
    depts: Dict[str, List[dict]] = {}
    for u in users:
        depts.setdefault(str(u.get("department") or "GENERAL").upper(),
                         []).append(u)
    out = []
    for dname in sorted(depts):
        us = depts[dname]
        act = [u for u in us if _active(u)]
        srows = [rows_by_uid.get(u["user_id"]) for u in us
                 if rows_by_uid.get(u["user_id"])]
        gross = sum(_f(r.get("gross_paid")) for r in srows)
        ot = sum(_f(r.get("ot_pay")) for r in srows)
        er = sum(_f(r.get("pf_employer_total")) + _f(r.get("esic_employer"))
                 for r in srows)
        days = sum(_f(r.get("present_days")) for r in srows)
        joins = sum(1 for u in us if (_dt(u.get("doj")) or date.min) >= start
                    and (_dt(u.get("doj")) or date.min) <= end)
        exits = sum(1 for u in us if _exit_date(u)
                    and start <= _exit_date(u) <= end)
        buckets: Dict[str, int] = {}
        genders: Dict[str, int] = {}
        for u in act:
            buckets[_bucket(u)] = buckets.get(_bucket(u), 0) + 1
            genders[_gender(u)] = genders.get(_gender(u), 0) + 1
        avg_str = max(1.0, (len(act) + len(act) + exits - joins) / 2)
        out.append({
            "department": dname, "present_strength": len(act),
            "male": genders.get("Male", 0), "female": genders.get("Female", 0),
            "other": genders.get("Other", 0),
            "permanent": len(act) - buckets.get("Contract", 0)
            - buckets.get("Apprentice", 0) - buckets.get("Trainee", 0),
            "contract": buckets.get("Contract", 0),
            "apprentice": buckets.get("Apprentice", 0),
            "trainee": buckets.get("Trainee", 0),
            "staff": buckets.get("Staff", 0),
            "workers": buckets.get("Workers", 0),
            "highly_skilled": buckets.get("Highly Skilled", 0),
            "skilled": buckets.get("Skilled", 0),
            "semi_skilled": buckets.get("Semi Skilled", 0),
            "unskilled": buckets.get("Unskilled", 0),
            "supervisor": buckets.get("Supervisor", 0),
            "engineer": buckets.get("Engineer", 0),
            "executive": buckets.get("Executive", 0),
            "manager": buckets.get("Manager", 0),
            "avg_attendance": round(days / len(srows), 1) if srows else 0,
            "avg_salary": round(gross / len(srows), 2) if srows else 0,
            "avg_ot": round(ot / len(srows), 2) if srows else 0,
            "salary_cost": round(gross, 2),
            "labour_cost": round(gross + er, 2),
            "joining": joins, "exit": exits,
            "attrition_pct": round(exits * 100 / avg_str, 1),
        })
    cols = [("department", "Department"), ("present_strength", "Present Strength"),
            ("male", "Male"), ("female", "Female"), ("other", "Other"),
            ("permanent", "Permanent"), ("contract", "Contract"),
            ("apprentice", "Apprentice"), ("trainee", "Trainee"),
            ("staff", "Staff"), ("workers", "Workers"),
            ("highly_skilled", "Highly Skilled"), ("skilled", "Skilled"),
            ("semi_skilled", "Semi Skilled"), ("unskilled", "Unskilled"),
            ("supervisor", "Supervisor"), ("engineer", "Engineer"),
            ("executive", "Executive"), ("manager", "Manager"),
            ("avg_attendance", "Avg Attendance"), ("avg_salary", "Avg Salary"),
            ("avg_ot", "Avg OT"), ("salary_cost", "Salary Cost"),
            ("labour_cost", "Labour Cost"), ("joining", "Joining"),
            ("exit", "Exit"), ("attrition_pct", "Attrition %")]
    totals = {k: round(sum(r[k] for r in out), 2) for k, _ in cols[1:]}
    totals["department"] = "TOTAL"
    return cols, out, totals


async def _cat_register(company_id: str, month: str):
    users = await _users(company_id)
    rows_by_uid = await _run_rows(company_id, month)
    cats: Dict[str, List[dict]] = {}
    for u in users:
        if _active(u):
            cats.setdefault(_bucket(u), []).append(u)
    out = []
    today = date.today()
    for cname in sorted(cats):
        us = cats[cname]
        srows = [rows_by_uid.get(u["user_id"]) for u in us
                 if rows_by_uid.get(u["user_id"])]
        gross = sum(_f(r.get("gross_paid")) for r in srows)
        ot = sum(_f(r.get("ot_pay")) for r in srows)
        er = sum(_f(r.get("pf_employer_total")) + _f(r.get("esic_employer"))
                 for r in srows)
        days = sum(_f(r.get("present_days")) for r in srows)
        genders: Dict[str, int] = {}
        for u in us:
            genders[_gender(u)] = genders.get(_gender(u), 0) + 1
        grat = sum(1 for u in us if _dt(u.get("doj"))
                   and (today - _dt(u.get("doj"))).days >= 5 * 365)
        bonus = sum(1 for u in us if 0 < _f(
            u.get("compliance_gross") or u.get("salary_monthly")) <= 21000)
        out.append({
            "category": cname, "employees": len(us),
            "male": genders.get("Male", 0), "female": genders.get("Female", 0),
            "avg_salary": round(gross / len(srows), 2) if srows else 0,
            "avg_attendance": round(days / len(srows), 1) if srows else 0,
            "avg_ot": round(ot / len(srows), 2) if srows else 0,
            "salary_cost": round(gross, 2),
            "labour_cost": round(gross + er, 2),
            "pf_employees": sum(1 for u in us
                                if u.get("pf_no") or u.get("uan_no")),
            "esic_employees": sum(1 for u in us if u.get("esi_ip_no")),
            "bonus_eligible": bonus, "gratuity_eligible": grat,
        })
    cols = [("category", "Category"), ("employees", "Employees"),
            ("male", "Male"), ("female", "Female"),
            ("avg_salary", "Avg Salary"), ("avg_attendance", "Avg Attendance"),
            ("avg_ot", "Avg OT"), ("salary_cost", "Salary Cost"),
            ("labour_cost", "Labour Cost"), ("pf_employees", "PF Employees"),
            ("esic_employees", "ESIC Employees"),
            ("bonus_eligible", "Bonus Eligible"),
            ("gratuity_eligible", "Gratuity Eligible")]
    totals = {k: round(sum(r[k] for r in out), 2) for k, _ in cols[1:]}
    totals["category"] = "TOTAL"
    return cols, out, totals


async def _monthly_return(company_id: str, month: str):
    users = await _users(company_id)
    rows_by_uid = await _run_rows(company_id, month)
    start, end = _month_range(month)
    joins = [u for u in users if _dt(u.get("doj"))
             and start <= _dt(u.get("doj")) <= end]
    exits = [u for u in users if _exit_date(u)
             and start <= _exit_date(u) <= end]
    resign = [u for u in exits
              if "termin" not in str(u.get("employment_status") or "").lower()]
    closing = sum(1 for u in users if _active(u)
                  or (_exit_date(u) and _exit_date(u) > end))
    srows = list(rows_by_uid.values())
    gross = sum(_f(r.get("gross_paid")) for r in srows)
    pf = sum(_f(r.get("pf_employee")) for r in srows)
    esic = sum(_f(r.get("esic_employee")) for r in srows)
    pt = sum(_f(r.get("pt")) for r in srows)
    net = sum(_f(r.get("net")) for r in srows)
    ot = sum(_f(r.get("ot_pay")) for r in srows)
    er = sum(_f(r.get("pf_employer_total")) + _f(r.get("esic_employer"))
             for r in srows)
    days = sum(_f(r.get("present_days")) for r in srows)
    rows = [{"particular": p, "value": v} for p, v in [
        ("Opening Employees", closing - len(joins) + len(exits)),
        ("New Joining", len(joins)),
        ("Resignation", len(resign)),
        ("Termination", len(exits) - len(resign)),
        ("Closing Strength", closing),
        ("Average Attendance (days)",
         round(days / len(srows), 1) if srows else 0),
        ("Salary Cost (Gross)", round(gross, 2)),
        ("OT Cost", round(ot, 2)),
        ("PF (Employee)", round(pf, 2)),
        ("ESIC (Employee)", round(esic, 2)),
        ("PT", round(pt, 2)),
        ("Net Salary", round(net, 2)),
        ("Employer PF+ESIC", round(er, 2)),
        ("Employer Cost (CTC)", round(gross + er, 2)),
    ]]
    cols = [("particular", "Particular"), ("value", "Value")]
    return cols, rows, None


async def _turnover(company_id: str, fy_start_year: int):
    users = await _users(company_id)
    months = []
    for i in range(12):
        m, y = 4 + i, fy_start_year
        if m > 12:
            m, y = m - 12, y + 1
        months.append(f"{y:04d}-{m:02d}")
    out = []
    today = date.today()
    for mo in months:
        start, end = _month_range(mo)
        if start > today:
            break
        joins = sum(1 for u in users if _dt(u.get("doj"))
                    and start <= _dt(u.get("doj")) <= end)
        ex_users = [u for u in users if _exit_date(u)
                    and start <= _exit_date(u) <= end]
        strength = sum(1 for u in users if (_dt(u.get("doj")) or date.min) <= end
                       and (not _exit_date(u) or _exit_date(u) > end))
        svc = [((_exit_date(u) - _dt(u.get("doj"))).days / 365)
               for u in ex_users if _dt(u.get("doj"))]
        out.append({
            "month": start.strftime("%b-%y").upper(),
            "strength": strength, "joining": joins, "exit": len(ex_users),
            "attrition_pct": round(len(ex_users) * 100 / (strength or 1), 1),
            "avg_service_yrs": round(sum(svc) / len(svc), 1) if svc else 0,
        })
    # department-wise attrition (FY)
    fy_start = date(fy_start_year, 4, 1)
    fy_end = date(fy_start_year + 1, 3, 31)
    dept_attr: Dict[str, Dict[str, int]] = {}
    for u in users:
        d = str(u.get("department") or "GENERAL").upper()
        dept_attr.setdefault(d, {"emp": 0, "exit": 0})
        if _active(u):
            dept_attr[d]["emp"] += 1
        ed = _exit_date(u)
        if ed and fy_start <= ed <= fy_end:
            dept_attr[d]["exit"] += 1
    dept_rows = [{"department": d, "employees": v["emp"], "exits": v["exit"],
                  "attrition_pct": round(v["exit"] * 100 / (v["emp"] + v["exit"] or 1), 1)}
                 for d, v in sorted(dept_attr.items())]
    cols = [("month", "Month"), ("strength", "Strength"),
            ("joining", "Joining"), ("exit", "Exit"),
            ("attrition_pct", "Attrition %"),
            ("avg_service_yrs", "Avg Service (yrs)")]
    return cols, out, None, dept_rows


async def _welfare(company_id: str, month: str):
    users = await _users(company_id)
    act = [u for u in users if _active(u)]
    rows_by_uid = await _run_rows(company_id, month)
    srows = list(rows_by_uid.values())
    male = sum(1 for u in act if _gender(u) == "Male")
    female = sum(1 for u in act if _gender(u) == "Female")
    pf_reg = sum(1 for u in act if u.get("pf_no") or u.get("uan_no"))
    esic_reg = sum(1 for u in act if u.get("esi_ip_no"))
    checks = [pf_reg / (len(act) or 1), esic_reg / (len(act) or 1),
              1.0 if srows else 0.0]
    rows = [{"particular": p, "value": v} for p, v in [
        ("PF Registered", pf_reg),
        ("UAN Generated", sum(1 for u in act if u.get("uan_no"))),
        ("ESIC Registered (IP)", esic_reg),
        ("PT Deducted (this month)",
         sum(1 for r in srows if _f(r.get("pt")) > 0)),
        ("LWF Deducted (this month)",
         sum(1 for r in srows if _f(r.get("lwf")) > 0)),
        ("Bonus Eligible (gross ≤ 21000)", sum(
            1 for u in act if 0 < _f(u.get("compliance_gross")
                                     or u.get("salary_monthly")) <= 21000)),
        ("Gratuity Eligible (5+ yrs)", sum(
            1 for u in act if _dt(u.get("doj"))
            and (date.today() - _dt(u.get("doj"))).days >= 5 * 365)),
        ("Gender Ratio (F per 100 M)",
         round(female * 100 / (male or 1), 1)),
        ("Compliance %", round(sum(checks) * 100 / len(checks), 1)),
    ]]
    cols = [("particular", "Particular"), ("value", "Value")]
    return cols, rows, None


_KINDS = {
    "department": ("Department Labour Statistics Register", _dept_register),
    "category": ("Category Wise Manpower Register", _cat_register),
    "monthly-return": ("Monthly Labour Return", _monthly_return),
    "welfare": ("Labour Welfare & Compliance Statistics", _welfare),
}


@router.get("/dashboard")
async def dashboard(company_id: Optional[str] = None,
                    month: Optional[str] = None,
                    authorization: Optional[str] = Header(None)):
    company_id = await _admin(authorization, company_id)
    month = month or _month_now()
    c = await _company(company_id)
    users = await _users(company_id)
    act = [u for u in users if _active(u)]
    rows_by_uid = await _run_rows(company_id, month)
    srows = list(rows_by_uid.values())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    present_today = await db.attendance.distinct(
        "user_id", {"company_id": company_id,
                    "timestamp": {"$regex": f"^{today}"}})
    gross = sum(_f(r.get("gross_paid")) for r in srows)
    ot_emp = sum(1 for r in srows if _f(r.get("ot_pay")) > 0)
    er = sum(_f(r.get("pf_employer_total")) + _f(r.get("esic_employer"))
             for r in srows)
    start, _e = _month_range(month)
    joins = sum(1 for u in users if _dt(u.get("doj"))
                and start <= _dt(u.get("doj")) <= _e)
    exits = sum(1 for u in users if _exit_date(u)
                and start <= _exit_date(u) <= _e)
    male = sum(1 for u in act if _gender(u) == "Male")
    female = sum(1 for u in act if _gender(u) == "Female")
    # age pyramid
    ages: Dict[str, int] = {"<25": 0, "25-35": 0, "35-45": 0, "45-55": 0,
                            "55+": 0, "N/A": 0}
    for u in act:
        dob = _dt(u.get("dob"))
        if not dob:
            ages["N/A"] += 1
            continue
        a = (date.today() - dob).days // 365
        ages["<25" if a < 25 else "25-35" if a < 35 else "35-45" if a < 45
             else "45-55" if a < 55 else "55+"] += 1
    dept_strength: Dict[str, int] = {}
    for u in act:
        d = str(u.get("department") or "GENERAL").upper()
        dept_strength[d] = dept_strength.get(d, 0) + 1
    pf_reg = sum(1 for u in act if u.get("pf_no") or u.get("uan_no"))
    esic_reg = sum(1 for u in act if u.get("esi_ip_no"))
    # AI insights (rule-based detections)
    insights: List[dict] = []
    attr = exits * 100 / (len(act) or 1)
    if attr > 5:
        insights.append({"level": "high", "text":
                         f"High attrition this month: {attr:.1f}% ({exits} exits)"})
    if srows:
        avg_ot = sum(_f(r.get("ot_hours")) for r in srows) / len(srows)
        if avg_ot > 30:
            insights.append({"level": "high", "text":
                             f"High OT: average {avg_ot:.0f} OT hours/employee"})
        ghost = [r for r in srows if _f(r.get("gross_paid")) > 0
                 and _f(r.get("present_days")) <= 0]
        if ghost:
            insights.append({"level": "high", "text":
                             f"{len(ghost)} possible ghost employees "
                             "(salary paid with 0 attendance)"})
        gl = [r for r in srows if _f(r.get("gross_paid")) > 0]
        if gl:
            avg_g = gross / len(gl)
            anomalies = [r for r in gl if _f(r.get("gross_paid")) > 3 * avg_g]
            if anomalies:
                insights.append({"level": "medium", "text":
                                 f"{len(anomalies)} salary anomalies "
                                 f"(gross > 3× average ₹{avg_g:,.0f})"})
    names: Dict[str, int] = {}
    for u in act:
        k = str(u.get("name") or "").strip().lower()
        names[k] = names.get(k, 0) + 1
    dups = sum(1 for v in names.values() if v > 1)
    if dups:
        insights.append({"level": "medium",
                         "text": f"{dups} duplicate employee names detected"})
    if pf_reg < len(act):
        insights.append({"level": "medium", "text":
                         f"{len(act) - pf_reg} employees without PF/UAN"})
    if not insights:
        insights.append({"level": "ok", "text": "No anomalies detected"})
    return {
        "company_name": c.get("name"), "month": month,
        "kpis": {
            "total_employees": len(act),
            "today_present": len(present_today),
            "today_absent": max(0, len(act) - len(present_today)),
            "ot_employees": ot_emp,
            "salary_cost": round(gross, 2),
            "labour_cost": round(gross + er, 2),
            "avg_salary": round(gross / len(srows), 2) if srows else 0,
            "joining": joins, "exit": exits,
            "attrition_pct": round(attr, 1),
            "gender_ratio": f"{male}M / {female}F",
            "pf_pct": round(pf_reg * 100 / (len(act) or 1), 1),
            "esic_pct": round(esic_reg * 100 / (len(act) or 1), 1),
        },
        "age_distribution": ages,
        "department_strength": dict(sorted(
            dept_strength.items(), key=lambda x: -x[1])[:12]),
        "insights": insights,
    }


@router.get("/turnover")
async def turnover(company_id: Optional[str] = None, fy_start_year: int = 0,
                   authorization: Optional[str] = Header(None)):
    company_id = await _admin(authorization, company_id)
    fy = fy_start_year or (date.today().year if date.today().month >= 4
                           else date.today().year - 1)
    cols, rows, _t, dept_rows = await _turnover(company_id, fy)
    return {"columns": [{"key": k, "label": lb} for k, lb in cols],
            "rows": rows, "department_attrition": dept_rows,
            "fy_start_year": fy}


@router.get("/{kind}")
async def register_json(kind: str, company_id: Optional[str] = None,
                        month: Optional[str] = None,
                        authorization: Optional[str] = Header(None)):
    for ext in ("xlsx", "pdf"):  # /{kind} matches before /{kind}.{ext}
        if kind.endswith(f".{ext}"):
            return await _export(kind[: -len(ext) - 1], company_id, month,
                                 authorization, ext)
    if kind not in _KINDS:
        raise HTTPException(status_code=404, detail="Unknown register")
    company_id = await _admin(authorization, company_id)
    month = month or _month_now()
    title, fn = _KINDS[kind]
    cols, rows, totals = await fn(company_id, month)
    return {"title": title, "month": month,
            "columns": [{"key": k, "label": lb} for k, lb in cols],
            "rows": rows, "totals": totals}


@router.get("/{kind}.xlsx")
async def register_export_xlsx(kind: str, company_id: Optional[str] = None,
                               month: Optional[str] = None,
                               authorization: Optional[str] = Header(None)):
    return await _export(kind, company_id, month, authorization, "xlsx")


@router.get("/{kind}.pdf")
async def register_export_pdf(kind: str, company_id: Optional[str] = None,
                              month: Optional[str] = None,
                              authorization: Optional[str] = Header(None)):
    return await _export(kind, company_id, month, authorization, "pdf")


async def _export(kind, company_id, month, authorization, fmt):
    company_id = await _admin(authorization, company_id)
    month = month or _month_now()
    c = await _company(company_id)
    if kind == "turnover":
        fy = int(month[:4]) if int(month[5:7]) >= 4 else int(month[:4]) - 1
        cols, rows, totals, _d = await _turnover(company_id, fy)
        title = "Employee Turnover Analysis"
        sub = f"{c.get('name')} · FY {fy}-{str(fy + 1)[-2:]}"
    elif kind in _KINDS:
        title, fn = _KINDS[kind]
        cols, rows, totals = await fn(company_id, month)
        sub = f"{c.get('name')} · {month} · Generated {date.today():%d-%m-%Y}"
    else:
        raise HTTPException(status_code=404, detail="Unknown register")
    columns = [{"key": k, "label": lb} for k, lb in cols]
    if fmt == "xlsx":
        buf = register_xlsx(title, sub, columns, rows, totals)
        mt = ("application/vnd.openxmlformats-officedocument"
              ".spreadsheetml.sheet")
    else:
        buf = register_pdf(title, sub, columns, rows, totals,
                           c.get("logo_base64"))
        mt = "application/pdf"
    fn_ = f"{title.replace(' ', '_')}_{month}.{fmt}"
    return StreamingResponse(buf, media_type=mt, headers={
        "Content-Disposition": f'attachment; filename="{fn_}"'})
