"""Iter 709 — READ-ONLY Payroll Charts & Analytics.

STRICTLY VIEW-ONLY: every endpoint only READS existing collections
(salary_runs, compliance_salary_runs, users, attendance, leaves,
expense_claims, advances, approval_requests). No insert/update/delete,
no recalculation, no process triggers, no status changes. Existing
reports, engines and workflows are untouched — this module only shapes
already-computed data for charts.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from server import db, get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
ADMIN_ROLES = ["super_admin", "sub_admin", "company_admin"]


async def _scope(authorization, company_id) -> str:
    admin = await get_user_from_token(authorization)
    require_role(admin, ADMIN_ROLES)
    cid = admin.get("company_id") if admin.get("role") == "company_admin" else company_id
    if not cid:
        raise HTTPException(status_code=400, detail="company_id is required")
    return cid


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _months_back(month: str, n: int) -> List[str]:
    y, m = int(month[:4]), int(month[5:7])
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


async def _month_rows(cid: str, month: str) -> List[dict]:
    """Rows for the month = latest actual run PER GROUP (READ ONLY)."""
    runs = await db.salary_runs.find(
        {"company_id": cid, "month": month},
        {"_id": 0, "rows": 1, "group_id": 1, "generated_at": 1, "totals": 1},
    ).sort("generated_at", -1).to_list(50)
    rows: List[dict] = []
    best: Dict[str, dict] = {}
    for r in runs:
        gid = r.get("group_id") or "__default__"
        cur = best.get(gid)
        has_val = _f((r.get("totals") or {}).get("total_gross")) > 0
        cur_has = cur is not None and _f((cur.get("totals") or {}).get("total_gross")) > 0
        # Prefer the newest run WITH data; fall back to the newest run.
        if cur is None or (has_val and not cur_has):
            best[gid] = r
    for r in best.values():
        rows.extend(r.get("rows") or [])
    return rows


@router.get("/payroll")
async def payroll_charts(company_id: Optional[str] = Query(None),
                         month: Optional[str] = Query(None),
                         authorization: Optional[str] = Header(None)):
    cid = await _scope(authorization, company_id)
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    # ---- trend across last 6 months -------------------------------------
    trend = []
    for m in _months_back(month, 6):
        rows = await _month_rows(cid, m)
        gross = sum(_f(r.get("total_gross")) for r in rows)
        net = sum(_f(r.get("net_pay")) for r in rows)
        trend.append({"month": m, "gross": round(gross, 2), "net": round(net, 2),
                      "employees": len(rows)})
    # ---- selected month --------------------------------------------------
    rows = await _month_rows(cid, month)
    gross = sum(_f(r.get("total_gross")) for r in rows)
    net = sum(_f(r.get("net_pay")) for r in rows)
    epf = sum(_f(r.get("epf")) for r in rows)
    esi = sum(_f(r.get("esi")) for r in rows)
    tds = sum(_f(r.get("tds")) for r in rows)
    adv = sum(_f(r.get("adv")) for r in rows)
    basic = sum(_f(r.get("basic_salary") or r.get("basic")) for r in rows)
    oth = sum(_f(r.get("oth_allo")) for r in rows)
    deductions = round(epf + esi + tds + adv, 2)
    dept: Dict[str, Dict[str, float]] = {}
    for r in rows:
        d = str(r.get("department") or "Unassigned").strip() or "Unassigned"
        e = dept.setdefault(d, {"gross": 0.0, "net": 0.0, "n": 0})
        e["gross"] += _f(r.get("total_gross"))
        e["net"] += _f(r.get("net_pay"))
        e["n"] += 1
    dept_bar = sorted(
        [{"label": k, "gross": round(v["gross"], 2), "net": round(v["net"], 2),
          "employees": v["n"]} for k, v in dept.items()],
        key=lambda x: -x["gross"])[:12]
    # ---- PF / ESIC employee vs employer (compliance run, READ ONLY) -----
    crun = await db.compliance_salary_runs.find_one(
        {"company_id": cid, "month": month}, {"_id": 0, "rows": 1},
        sort=[("generated_at", -1)])
    crows = (crun or {}).get("rows") or []
    pf_emp = sum(_f(r.get("pf_employee") or r.get("epf_employee") or r.get("epf")) for r in crows)
    pf_er = sum(_f(r.get("pf_employer") or r.get("epf_employer")) for r in crows)
    esic_emp = sum(_f(r.get("esic_employee")) for r in crows)
    esic_er = sum(_f(r.get("esic_employer")) for r in crows)
    return {
        "month": month,
        "kpis": {"employees": len(rows), "gross": round(gross, 2),
                 "net": round(net, 2), "deductions": deductions,
                 "pf": round(epf, 2), "esic": round(esi, 2)},
        "trend": trend,
        "dept_bar": dept_bar,
        "components": [{"label": "Basic", "value": round(basic, 2)},
                       {"label": "Other Allowances", "value": round(oth, 2)},
                       {"label": "Balance Earnings",
                        "value": round(max(0.0, gross - basic - oth), 2)}],
        "deduction_split": [{"label": "PF", "value": round(epf, 2)},
                            {"label": "ESIC", "value": round(esi, 2)},
                            {"label": "TDS", "value": round(tds, 2)},
                            {"label": "Advance", "value": round(adv, 2)}],
        "earn_vs_ded": [{"month": t["month"], "net": t["net"],
                         "deductions": round(t["gross"] - t["net"], 2)}
                        for t in trend],
        "pf_esic": {"pf_employee": round(pf_emp, 2), "pf_employer": round(pf_er, 2),
                    "esic_employee": round(esic_emp, 2), "esic_employer": round(esic_er, 2),
                    "source": "compliance" if crows else "none"},
        "has_data": bool(rows),
    }


@router.get("/attendance")
async def attendance_charts(company_id: Optional[str] = Query(None),
                            month: Optional[str] = Query(None),
                            authorization: Optional[str] = Header(None)):
    cid = await _scope(authorization, company_id)
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    d0 = date.fromisoformat(f"{month}-01")
    d1 = (d0.replace(year=d0.year + 1, month=1) if d0.month == 12
          else d0.replace(month=d0.month + 1)) - timedelta(days=1)
    # Daily distinct-present line (aggregate READ).
    pipe = [
        {"$match": {"company_id": cid, "status": "approved",
                    "date": {"$gte": d0.isoformat(), "$lte": d1.isoformat()}}},
        {"$group": {"_id": {"d": "$date", "u": "$user_id"}}},
        {"$group": {"_id": "$_id.d", "present": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    daily = [{"date": r["_id"], "present": r["present"]}
             async for r in db.attendance.aggregate(pipe)]
    total_emp = await db.users.count_documents({"company_id": cid, "role": "employee"})
    present_days = sum(x["present"] for x in daily)
    # Leave days in month (approved) — READ only.
    leave_days = 0
    leave_types: Dict[str, int] = {}
    async for lv in db.leaves.find(
            {"company_id": cid, "status": "approved",
             "from_date": {"$lte": d1.isoformat()},
             "to_date": {"$gte": d0.isoformat()}},
            {"_id": 0, "from_date": 1, "to_date": 1, "leave_type": 1}):
        try:
            a = max(date.fromisoformat(lv["from_date"]), d0)
            b = min(date.fromisoformat(lv["to_date"]), d1)
            n = max(0, (b - a).days + 1)
        except (ValueError, TypeError, KeyError):
            n = 0
        leave_days += n
        t = (lv.get("leave_type") or "Other").upper()
        leave_types[t] = leave_types.get(t, 0) + n
    workdays = sum(1 for i in range((d1 - d0).days + 1)
                   if (d0 + timedelta(days=i)).weekday() != 6)
    absent_days = max(0, total_emp * workdays - present_days - leave_days)
    # Source split (biometric / manual / face / tour ...) — READ only.
    src_pipe = [
        {"$match": {"company_id": cid, "status": "approved",
                    "date": {"$gte": d0.isoformat(), "$lte": d1.isoformat()}}},
        {"$group": {"_id": {"$ifNull": ["$source", "mobile"]}, "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]
    sources = [{"label": str(r["_id"]), "value": r["n"]}
               async for r in db.attendance.aggregate(src_pipe)]
    return {"month": month, "daily": daily,
            "kpis": {"employees": total_emp, "present_days": present_days,
                     "leave_days": leave_days, "avg_daily_present":
                     round(present_days / max(1, len(daily)), 1) if daily else 0},
            "status_donut": [{"label": "Present", "value": present_days},
                             {"label": "Leave", "value": leave_days},
                             {"label": "Absent", "value": absent_days}],
            "leave_types": [{"label": k, "value": v} for k, v in leave_types.items()],
            "sources": sources[:8]}


@router.get("/people")
async def people_charts(company_id: Optional[str] = Query(None),
                        authorization: Optional[str] = Header(None)):
    cid = await _scope(authorization, company_id)
    emps = await db.users.find(
        {"company_id": cid, "role": "employee"},
        {"_id": 0, "department": 1, "designation": 1, "employee_type": 1,
         "status": 1, "active": 1, "doj": 1, "date_of_joining": 1,
         "uan": 1, "uan_no": 1, "esi_ip_no": 1, "esic_ip": 1}).to_list(20000)

    def _count(field, fallback="Unassigned", top=12):
        c: Dict[str, int] = {}
        for e in emps:
            v = str(e.get(field) or fallback).strip() or fallback
            c[v] = c.get(v, 0) + 1
        return sorted([{"label": k, "value": v} for k, v in c.items()],
                      key=lambda x: -x["value"])[:top]

    active = sum(1 for e in emps
                 if (e.get("status") or "active").lower() not in ("inactive", "exited", "resigned")
                 and e.get("active") is not False)
    uan_yes = sum(1 for e in emps if (e.get("uan") or e.get("uan_no")))
    esic_yes = sum(1 for e in emps if (e.get("esi_ip_no") or e.get("esic_ip")))
    # Joining trend (last 6 months) from doj — READ only.
    now = datetime.now(timezone.utc).strftime("%Y-%m")
    months = _months_back(now, 6)
    joins = {m: 0 for m in months}
    for e in emps:
        dj = str(e.get("doj") or e.get("date_of_joining") or "")[:7]
        if dj in joins:
            joins[dj] += 1
    # Expenses by category / status — READ only.
    cat_pipe = [{"$match": {"company_id": cid, "status": {"$nin": ["draft"]}}},
                {"$group": {"_id": {"$ifNull": ["$category_name", "Other"]},
                            "n": {"$sum": 1}, "amt": {"$sum": "$amount"}}},
                {"$sort": {"amt": -1}}]
    exp_cat = [{"label": str(r["_id"]), "value": round(_f(r["amt"]), 2), "count": r["n"]}
               async for r in db.expense_claims.aggregate(cat_pipe)][:8]
    st_pipe = [{"$match": {"company_id": cid, "status": {"$nin": ["draft"]}}},
               {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    exp_status = [{"label": str(r["_id"]), "value": r["n"]}
                  async for r in db.expense_claims.aggregate(st_pipe)]
    # Approval engine status — READ only.
    ap_pipe = [{"$match": {"company_id": cid}},
               {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    approvals = [{"label": str(r["_id"]), "value": r["n"]}
                 async for r in db.approval_requests.aggregate(ap_pipe)]
    # Advances outstanding — READ only.
    adv_pipe = [{"$match": {"company_id": cid}},
                {"$group": {"_id": "$status", "n": {"$sum": 1},
                            "amt": {"$sum": "$amount"}}}]
    advances = [{"label": str(r["_id"]), "value": round(_f(r["amt"]), 2), "count": r["n"]}
                async for r in db.advances.aggregate(adv_pipe)]
    return {
        "kpis": {"total": len(emps), "active": active,
                 "inactive": len(emps) - active,
                 "uan_available": uan_yes, "esic_available": esic_yes},
        "dept_bar": _count("department"),
        "designation_bar": _count("designation"),
        "type_donut": _count("employee_type", fallback="Regular", top=6),
        "active_donut": [{"label": "Active", "value": active},
                         {"label": "Inactive", "value": len(emps) - active}],
        "uan_donut": [{"label": "UAN Available", "value": uan_yes},
                      {"label": "UAN Missing", "value": len(emps) - uan_yes}],
        "esic_donut": [{"label": "IP Available", "value": esic_yes},
                       {"label": "IP Missing", "value": len(emps) - esic_yes}],
        "joining_trend": [{"month": m, "joins": joins[m]} for m in months],
        "expense_categories": exp_cat, "expense_status": exp_status,
        "approvals": approvals, "advances": advances,
    }
