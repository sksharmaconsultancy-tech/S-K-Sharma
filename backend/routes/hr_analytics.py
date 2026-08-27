"""Iter 746 — HR ANALYTICS (user PRD Phase 3).

* Attrition KPI — REAL joining (doj) / exit (resign_date) records only, no
  fabricated history. Attrition % = Exits / Average Headcount × 100.
* Salary Variance — current vs previous compliance salary run with reason
  breakup (joiners / exits / OT / arrear / attendance / deduction / other)
  and employee drill-down.
* Management Dashboard — top KPIs + OT section + movement + org + alerts.
All figures come from the EXISTING masters/runs (source of truth).
"""
import calendar
from datetime import date as _date, datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from server import db, get_user_from_token, sub_admin_can_touch_company  # noqa: E402
from routes.statutory_extra_reports import _emit, _company, _num, _parse_doj  # noqa: E402

router = APIRouter(prefix="/api", tags=["hr-analytics"])


async def _authz(authorization, company_id):
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    if admin.get("role") == "company_admin":
        company_id = admin.get("company_id")
    if admin.get("role") == "sub_admin" and company_id:
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return admin, company_id


def _pd(v):
    """Parse a date-ish value to date (doj / resign_date formats)."""
    if not v:
        return None
    try:
        d = _parse_doj(v)
        if isinstance(d, datetime):
            return d.date()
        return d
    except Exception:
        pass
    for f in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(v)[:10], f).date()
        except ValueError:
            continue
    return None


def _month_bounds(month: str):
    y, m = int(month[:4]), int(month[5:7])
    return _date(y, m, 1), _date(y, m, calendar.monthrange(y, m)[1])


def _prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def _months_range(from_month: str, to_month: str):
    out, cur = [], from_month
    for _ in range(60):
        out.append(cur)
        if cur == to_month:
            break
        y, m = int(cur[:4]), int(cur[5:7])
        cur = f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"
    return out


_INVOL = ("terminat", "abscond", "dismiss", "retrench", "misconduct", "layoff")


async def _emps(company_id):
    return [u async for u in db.users.find(
        {"company_id": company_id, "role": "employee"},
        {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1, "doj": 1,
         "resign_date": 1, "resign_reason": 1, "exit_reason": 1, "active": 1,
         "department": 1, "designation": 1, "branch_name": 1,
         "employee_type": 1, "employment_status": 1})]


def _attrition_for(emps, month):
    ms, me = _month_bounds(month)
    joiners, exits, opening = [], [], 0
    for u in emps:
        doj = _pd(u.get("doj"))
        rd = _pd(u.get("resign_date"))
        if doj and ms <= doj <= me:
            joiners.append(u)
        if rd and ms <= rd <= me:
            exits.append(u)
        joined_before = doj is not None and doj < ms
        exited_before = rd is not None and rd < ms
        if joined_before and not exited_before:
            opening += 1
    closing = opening + len(joiners) - len(exits)
    avg = (opening + closing) / 2.0
    pct = round(len(exits) / avg * 100, 2) if avg > 0 else 0.0
    return {"month": month, "opening": opening, "joiners": len(joiners),
            "exits": len(exits), "closing": closing,
            "avg_headcount": round(avg, 1), "attrition_pct": pct,
            "_joiners": joiners, "_exits": exits}


@router.get("/hr/attrition")
async def attrition(company_id: Optional[str] = Query(None),
                    from_month: Optional[str] = Query(None),
                    to_month: Optional[str] = Query(None),
                    department: Optional[str] = Query(None),
                    branch: Optional[str] = Query(None),
                    designation: Optional[str] = Query(None),
                    employee_type: Optional[str] = Query(None),
                    authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    today = _date.today()
    to_month = to_month or f"{today.year}-{today.month:02d}"
    if not from_month:  # default: last 12 months
        y, m = int(to_month[:4]), int(to_month[5:7])
        m -= 11
        while m <= 0:
            m += 12
            y -= 1
        from_month = f"{y}-{m:02d}"
    emps = await _emps(company_id)

    def keep(u):
        if department and str(u.get("department") or "").strip().upper() != department.strip().upper():
            return False
        if branch and str(u.get("branch_name") or "").strip().upper() != branch.strip().upper():
            return False
        if designation and str(u.get("designation") or "").strip().upper() != designation.strip().upper():
            return False
        if employee_type and str(u.get("employee_type") or "").strip().upper() != employee_type.strip().upper():
            return False
        return True
    emps = [u for u in emps if keep(u)]
    months = _months_range(from_month, to_month)
    trend = [_attrition_for(emps, m) for m in months]
    cur = trend[-1]
    all_exits = [u for t in trend for u in t["_exits"]]
    vol = invol = 0
    reasons: dict = {}
    for u in all_exits:
        rs = str(u.get("resign_reason") or u.get("exit_reason") or "Not specified").strip() or "Not specified"
        reasons[rs] = reasons.get(rs, 0) + 1
        if any(k in rs.lower() for k in _INVOL):
            invol += 1
        else:
            vol += 1

    def bucket(field):
        b: dict = {}
        for u in all_exits:
            k = str(u.get(field) or "Unassigned").strip() or "Unassigned"
            b[k] = b.get(k, 0) + 1
        return sorted(({"name": k, "exits": v} for k, v in b.items()),
                      key=lambda x: -x["exits"])
    period = {"from": from_month, "to": to_month,
              "opening": trend[0]["opening"], "closing": cur["closing"],
              "joiners": sum(t["joiners"] for t in trend),
              "exits": sum(t["exits"] for t in trend),
              "avg_headcount": round(sum(t["avg_headcount"] for t in trend)
                                     / max(1, len(trend)), 1)}
    period["attrition_pct"] = round(
        period["exits"] / period["avg_headcount"] * 100, 2) if period["avg_headcount"] else 0.0
    exits_detail = [{"employee_code": u.get("employee_code"), "name": u.get("name"),
                     "department": u.get("department"), "branch": u.get("branch_name"),
                     "designation": u.get("designation"),
                     "exit_date": str(u.get("resign_date") or ""),
                     "reason": str(u.get("resign_reason") or u.get("exit_reason") or "")}
                    for u in all_exits]
    return {"period": period, "current_month": {k: v for k, v in cur.items()
                                                if not k.startswith("_")},
            "voluntary_exits": vol, "involuntary_exits": invol,
            "exit_reasons": sorted(({"reason": k, "count": v}
                                    for k, v in reasons.items()),
                                   key=lambda x: -x["count"]),
            "department_wise": bucket("department"),
            "branch_wise": bucket("branch_name"),
            "designation_wise": bucket("designation"),
            "monthly_trend": [{k: v for k, v in t.items() if not k.startswith("_")}
                              for t in trend],
            "exits_detail": exits_detail}


async def _run_rows(company_id: str, month: str):
    run = await db.compliance_salary_runs.find_one(
        {"company_id": company_id, "month": month},
        {"_id": 0, "rows": 1}, sort=[("generated_at", -1)])
    return (run or {}).get("rows") or []


@router.get("/hr/salary-variance")
async def salary_variance(company_id: Optional[str] = Query(None),
                          month: Optional[str] = Query(None),
                          branch: Optional[str] = Query(None),
                          department: Optional[str] = Query(None),
                          authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    if not month:
        raise HTTPException(status_code=400, detail="month YYYY-MM required")
    pm = _prev_month(month)
    cur_rows = await _run_rows(company_id, month)
    prev_rows = await _run_rows(company_id, pm)
    if not cur_rows:
        raise HTTPException(status_code=404,
                            detail=f"{month} ka compliance salary run nahi mila")
    if branch or department:
        uids = {u["user_id"] async for u in db.users.find(
            {"company_id": company_id,
             **({"branch_name": {"$regex": f"^{branch}$", "$options": "i"}} if branch else {}),
             **({"department": {"$regex": f"^{department}$", "$options": "i"}} if department else {})},
            {"_id": 0, "user_id": 1})}
        cur_rows = [r for r in cur_rows if r.get("user_id") in uids]
        prev_rows = [r for r in prev_rows if r.get("user_id") in uids]
    cur_by = {r["user_id"]: r for r in cur_rows}
    prev_by = {r["user_id"]: r for r in prev_rows}
    cur_total = round(sum(_num(r.get("gross_paid")) for r in cur_rows), 2)
    prev_total = round(sum(_num(r.get("gross_paid")) for r in prev_rows), 2)
    variance = round(cur_total - prev_total, 2)
    reasons = {k: {"reason": lbl, "amount": 0.0, "count": 0, "employees": []}
               for k, lbl in [
                   ("joiners", "New Joiners"), ("exits", "Employee Exits"),
                   ("ot", "OT Change"), ("arrear", "Arrear"),
                   ("attendance", "Attendance / LOP Variation"),
                   ("deductions", "Deduction Changes"),
                   ("other", "Salary Revision / Other Earnings")]}

    def add(k, uid, amt, prev_v, cur_v, name, code):
        r = reasons[k]
        r["amount"] = round(r["amount"] + amt, 2)
        r["count"] += 1
        if len(r["employees"]) < 400:
            r["employees"].append({"user_id": uid, "employee_code": code,
                                   "name": name, "previous": round(prev_v, 2),
                                   "current": round(cur_v, 2),
                                   "diff": round(amt, 2)})
    for uid, r in cur_by.items():
        p = prev_by.get(uid)
        g = _num(r.get("gross_paid"))
        if not p:
            add("joiners", uid, g, 0, g, r.get("name"), r.get("employee_code"))
            continue
        pg = _num(p.get("gross_paid"))
        diff = round(g - pg, 2)
        if abs(diff) < 0.01:
            pass
        else:
            ot_d = round(_num(r.get("ot_pay")) - _num(p.get("ot_pay")), 2)
            arr_d = round(_num(r.get("arrear")) - _num(p.get("arrear")), 2)
            rem = round(diff - ot_d - arr_d, 2)
            pd_d = _num(r.get("present_days")) - _num(p.get("present_days"))
            if abs(ot_d) >= 0.01:
                add("ot", uid, ot_d, _num(p.get("ot_pay")), _num(r.get("ot_pay")),
                    r.get("name"), r.get("employee_code"))
            if abs(arr_d) >= 0.01:
                add("arrear", uid, arr_d, _num(p.get("arrear")), _num(r.get("arrear")),
                    r.get("name"), r.get("employee_code"))
            if abs(rem) >= 0.01:
                k = "attendance" if abs(pd_d) >= 0.5 else "other"
                add(k, uid, rem, pg, g, r.get("name"), r.get("employee_code"))
        ded_d = round(_num(r.get("total_deduction")) - _num(p.get("total_deduction")), 2)
        if abs(ded_d) >= 0.01:
            add("deductions", uid, ded_d, _num(p.get("total_deduction")),
                _num(r.get("total_deduction")), r.get("name"), r.get("employee_code"))
    for uid, p in prev_by.items():
        if uid not in cur_by:
            pg = _num(p.get("gross_paid"))
            add("exits", uid, -pg, pg, 0, p.get("name"), p.get("employee_code"))
    return {"month": month, "previous_month": pm,
            "previous_payroll": prev_total, "current_payroll": cur_total,
            "variance": variance,
            "variance_pct": round(variance / prev_total * 100, 2) if prev_total else 0.0,
            "employee_count_prev": len(prev_rows),
            "employee_count_cur": len(cur_rows),
            "reasons": [v for v in reasons.values()
                        if v["count"] > 0 or abs(v["amount"]) >= 0.01]}


@router.get("/hr/dashboard")
async def hr_dashboard(company_id: Optional[str] = Query(None),
                       month: Optional[str] = Query(None),
                       authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    today = _date.today()
    month = month or f"{today.year}-{today.month:02d}"
    emps = await _emps(company_id)
    att = _attrition_for(emps, month)
    active = sum(1 for u in emps if u.get("active") is not False
                 and not (_pd(u.get("resign_date")) and _pd(u.get("resign_date")) <= today))
    # payroll
    cur_rows = await _run_rows(company_id, month)
    prev_rows = await _run_rows(company_id, _prev_month(month))
    cur_total = round(sum(_num(r.get("gross_paid")) for r in cur_rows), 2)
    prev_total = round(sum(_num(r.get("gross_paid")) for r in prev_rows), 2)
    # OT
    ot_rows = [e async for e in db.ot_entries.find(
        {"company_id": company_id, "month": month}, {"_id": 0})]
    from routes.ot_management import _summary
    ots = _summary(ot_rows)
    pending_cnt = ots["counts"].get("pending", 0) + ots["counts"].get("draft", 0)
    # org breakdown
    def bucket(field):
        b: dict = {}
        for u in emps:
            rd = _pd(u.get("resign_date"))
            if u.get("active") is False or (rd and rd <= today):
                continue
            k = str(u.get(field) or "Unassigned").strip() or "Unassigned"
            b[k] = b.get(k, 0) + 1
        return sorted(({"name": k, "count": v} for k, v in b.items()),
                      key=lambda x: -x["count"])
    mgr: dict = {}
    names = {u["user_id"]: u.get("name") for u in emps}
    for u in emps:
        pm_id = (u.get("reporting_chain") or {}).get("primary_manager") if isinstance(u.get("reporting_chain"), dict) else None
        if pm_id:
            mgr[pm_id] = mgr.get(pm_id, 0) + 1
    manager_teams = sorted(
        ({"manager": names.get(k) or k, "team_size": v} for k, v in mgr.items()),
        key=lambda x: -x["team_size"])[:25]
    alerts = []
    if pending_cnt:
        alerts.append({"type": "ot_pending", "level": "warn",
                       "text": f"{pending_cnt} OT entries approval pending"})
    if ots["cap_violations"]:
        alerts.append({"type": "ot_cap", "level": "error",
                       "text": f"OT limit exceeded — {ots['cap_violations']} entries me excess OT "
                               f"({ots['excess_ot']} hrs) payroll se bahar rakha gaya"})
    variance = round(cur_total - prev_total, 2)
    return {
        "month": month,
        "kpis": {
            "total_employees": len(emps), "active_employees": active,
            "new_joiners": att["joiners"], "exits": att["exits"],
            "attrition_pct": att["attrition_pct"],
            "current_payroll": cur_total, "previous_payroll": prev_total,
            "salary_variance": variance,
            "salary_variance_pct": round(variance / prev_total * 100, 2) if prev_total else 0.0,
            "ot_hours": ots["eligible_ot"], "ot_cost": ots["ot_cost"],
            "pending_ot_approvals": pending_cnt,
        },
        "ot": ots,
        "movement": {"joiners": att["joiners"], "exits": att["exits"],
                     "attrition_pct": att["attrition_pct"],
                     "department_exits": [
                         {"name": str(u.get("department") or "Unassigned"),
                          "employee": u.get("name")} for u in att["_exits"]]},
        "organization": {"branch_wise": bucket("branch_name"),
                         "department_wise": bucket("department"),
                         "manager_teams": manager_teams},
        "alerts": alerts,
    }


@router.get("/hr/report")
async def hr_report(kind: str = Query("attrition"),
                    fmt: str = Query("json"),
                    company_id: Optional[str] = Query(None),
                    month: Optional[str] = Query(None),
                    from_month: Optional[str] = Query(None),
                    to_month: Optional[str] = Query(None),
                    authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    company = await _company(company_id)
    if kind in ("attrition", "attrition_dept", "attrition_branch", "exit_reasons"):
        data = await attrition(company_id=company_id, from_month=from_month,
                               to_month=to_month, department=None, branch=None,
                               designation=None, employee_type=None,
                               authorization=authorization)
        if kind == "attrition":
            rows = data["monthly_trend"]
            cols = [("Month", "month", False), ("Opening", "opening", True),
                    ("Joiners", "joiners", True), ("Exits", "exits", True),
                    ("Closing", "closing", True), ("Avg HC", "avg_headcount", True),
                    ("Attrition %", "attrition_pct", True)]
            title = "Monthly Attrition Report"
        elif kind == "exit_reasons":
            rows = data["exit_reasons"]
            cols = [("Exit Reason", "reason", False), ("Count", "count", True)]
            title = "Exit Reason Analysis"
        else:
            rows = data["department_wise" if kind == "attrition_dept" else "branch_wise"]
            cols = [("Name", "name", False), ("Exits", "exits", True)]
            title = ("Department-wise" if kind == "attrition_dept"
                     else "Branch-wise") + " Attrition"
        return _emit(fmt, title=title,
                     subtitle=f"{data['period']['from']} — {data['period']['to']}",
                     company=company, cols=cols, rows=rows,
                     fname_base=f"{kind}_{company_id}")
    if kind in ("variance", "variance_reasons"):
        if not month:
            raise HTTPException(status_code=400, detail="month required")
        data = await salary_variance(company_id=company_id, month=month,
                                     branch=None, department=None,
                                     authorization=authorization)
        if kind == "variance":
            rows = []
            for r in data["reasons"]:
                rows.extend([{**e, "reason": r["reason"]} for e in r["employees"]])
            cols = [("Reason", "reason", False), ("Emp Code", "employee_code", False),
                    ("Name", "name", False), ("Previous", "previous", True),
                    ("Current", "current", True), ("Diff", "diff", True)]
            title = "Salary Variance Report"
        else:
            rows = [{"reason": r["reason"], "employees": r["count"],
                     "amount": r["amount"]} for r in data["reasons"]]
            cols = [("Reason", "reason", False), ("Employees", "employees", True),
                    ("Amount", "amount", True)]
            title = "Salary Variance Reason Analysis"
        return _emit(fmt, title=title,
                     subtitle=f"{data['previous_month']} → {data['month']} · "
                              f"₹{data['previous_payroll']} → ₹{data['current_payroll']} "
                              f"({data['variance_pct']}%)",
                     company=company, cols=cols, rows=rows,
                     fname_base=f"{kind}_{month}")
    raise HTTPException(status_code=400, detail="Unknown report kind")
