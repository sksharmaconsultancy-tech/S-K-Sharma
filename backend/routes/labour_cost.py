"""Iter 527 (user-approved improvement) — Daily Labour Cost Dashboard.

One endpoint powering a screen that shows, for a chosen day:
  • Total labour cost, employees present, total hours, OT hours
  • Department-wise cost split
  • Month-to-date daily cost trend

Cost per employee-day uses the SAME shared engine as the Shift Deployment
Report / OT Register (routes.labour_reports._day_cost): rate basis
(Monthly/Daily/Hourly) from the Employee Policy / Master, OT at the policy
multiplier. Hours come from the firm-master attendance-policy engine
(compute_textile_day) with the Attendance-Report punch pipeline (approved
punches, ±1-day window, dedupe + night-shift OUT stitching).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    compute_textile_day,
    dedupe_close_punches,
    stitch_cross_day_ot,
)
from routes.labour_reports import _apply_compliance_8hr, _auth, _day_cost  # noqa: E402

router = APIRouter(prefix="/api/admin")

_EMP_PROJ = {
    "_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "department": 1,
    "employee_policy": 1, "compliance_gross": 1, "salary_monthly": 1,
    "salary_structure_actual": 1, "salary_structure_compliance": 1,
    "compliance_salary_mode": 1, "ot_applicable": 1,
    "attendance_policy_override": 1, "week_off_full_day": 1,
    "week_off_govt_holiday_enabled": 1,
}


@router.get("/labour-cost/dashboard")
async def labour_cost_dashboard(
    company_id: str = Query(...),
    day: str = Query(..., description="YYYY-MM-DD"),
    authorization: Optional[str] = Header(None),
):
    await _auth(authorization, company_id)
    try:
        d_obj = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD")

    comp = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "attendance_policy": 1, "attendance_config": 1})
    if not comp:
        raise HTTPException(status_code=404, detail="Firm not found")
    policy = comp.get("attendance_policy") or {}

    emps = await db.users.find(
        {"company_id": company_id, "role": "employee",
         "status": {"$nin": ["inactive", "archived"]}},
        _EMP_PROJ).to_list(5000)
    emp_by_id = {e["user_id"]: e for e in emps}

    month_start = f"{day[:7]}-01"
    _qf = (date.fromisoformat(month_start) - timedelta(days=1)).isoformat()
    _qt = (d_obj + timedelta(days=1)).isoformat()

    by_user: Dict[str, Dict[str, list]] = {}
    async for r in db.attendance.find(
        {"user_id": {"$in": list(emp_by_id)},
         "date": {"$gte": _qf, "$lte": _qt},
         "kind": {"$in": ["in", "out"]}, "status": "approved"},
        {"_id": 0, "user_id": 1, "date": 1, "kind": 1, "at": 1, "source": 1},
    ).sort([("user_id", 1), ("at", 1)]):
        by_user.setdefault(r["user_id"], {}).setdefault(r["date"], []).append(r)

    trend: Dict[str, float] = {
        (date.fromisoformat(month_start) + timedelta(days=i)).isoformat(): 0.0
        for i in range((d_obj - date.fromisoformat(month_start)).days + 1)
    }
    day_total = {"cost": 0.0, "hours": 0.0, "ot": 0.0, "present": 0}
    dept: Dict[str, Dict[str, Any]] = {}

    for uid, daymap in by_user.items():
        e = emp_by_id[uid]
        repaired = stitch_cross_day_ot(dedupe_close_punches(
            daymap, company_cfg=comp.get("attendance_config")),
            company_cfg=comp.get("attendance_config"))
        for dk, plist in repaired.items():
            if dk not in trend:
                continue
            eng = compute_textile_day(
                plist, policy, e, date.fromisoformat(dk).weekday())
            hours, ot, pd_ = _apply_compliance_8hr(policy, e, eng)
            cost = _day_cost(e, policy, dk, pd_, hours, ot)
            trend[dk] += cost
            if dk == day:
                day_total["cost"] += cost
                day_total["hours"] += hours
                day_total["ot"] += ot
                day_total["present"] += 1
                g = (e.get("department") or "").strip() or "— Not Set —"
                a = dept.setdefault(g, {"department": g, "employees": 0,
                                        "hours": 0.0, "ot": 0.0, "cost": 0.0})
                a["employees"] += 1
                a["hours"] += hours
                a["ot"] += ot
                a["cost"] += cost

    departments = sorted(dept.values(), key=lambda x: -x["cost"])
    for a in departments:
        a["hours"] = round(a["hours"], 1)
        a["ot"] = round(a["ot"], 1)
        a["cost"] = round(a["cost"], 2)

    return {
        "firm": comp.get("name") or "",
        "day": day,
        "total_cost": round(day_total["cost"], 2),
        "employees_present": day_total["present"],
        "total_hours": round(day_total["hours"], 1),
        "ot_hours": round(day_total["ot"], 1),
        "departments": departments,
        "trend": [{"date": k, "cost": round(v, 2)}
                  for k, v in sorted(trend.items())],
        "mtd_cost": round(sum(trend.values()), 2),
    }
