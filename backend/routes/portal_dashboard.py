"""Iter 178 — Modern SaaS Portal Dashboard (Phase 1).

One aggregate endpoint powering the admin web dashboard: KPI cards,
attendance trend (14 days), payroll trend (6 months), per-firm compliance
status, statutory compliance calendar and pending-work counters.
Role-aware: super_admin sees all firms; company_admin only their firm.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from server import db, get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api/admin/portal-dashboard", tags=["portal-dashboard"])

IST = timezone(timedelta(hours=5, minutes=30))


def _statutory_calendar(month: str) -> List[Dict[str, str]]:
    """Standard Indian statutory due dates for the given YYYY-MM."""
    y, m = int(month[:4]), int(month[5:7])
    def d(day: int) -> str:
        return f"{y:04d}-{m:02d}-{day:02d}"
    return [
        {"date": d(7), "title": "TDS deposit (previous month)", "kind": "TDS"},
        {"date": d(15), "title": "PF payment + ECR filing (previous month)", "kind": "EPFO"},
        {"date": d(15), "title": "ESIC contribution payment (previous month)", "kind": "ESIC"},
        {"date": d(21), "title": "Professional Tax deposit (state-wise, typical)", "kind": "PT"},
        {"date": d(25), "title": "PF return verification (IW-1 where applicable)", "kind": "EPFO"},
    ]


@router.get("")
async def portal_dashboard(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    if admin.get("role") == "company_admin":
        company_id = admin.get("company_id")
        if not company_id:
            raise HTTPException(status_code=400, detail="No firm assigned")

    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    month = today[:7]

    comp_q: Dict[str, Any] = {"company_id": company_id} if company_id else {}
    emp_q = {**comp_q, "role": "employee",
             "$or": [{"disabled": {"$ne": True}}, {"disabled": {"$exists": False}}]}

    total_employees = await db.users.count_documents(emp_q)
    present_uids = await db.attendance.distinct("user_id", {
        **comp_q, "date": today, "kind": "in", "status": {"$ne": "rejected"}})
    pending_punches = await db.attendance.count_documents(
        {**comp_q, "status": "pending"})
    pending_leaves = await db.leaves.count_documents({**comp_q, "status": "pending"})
    open_tickets = await db.tickets.count_documents(
        {**comp_q, "status": {"$in": ["open", "in_progress"]}})

    # --- attendance trend (last 14 days: distinct present employees) ---
    days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(13, -1, -1)]
    trend_counts: Dict[str, set] = defaultdict(set)
    async for r in db.attendance.find(
        {**comp_q, "date": {"$gte": days[0], "$lte": today}, "kind": "in",
         "status": {"$ne": "rejected"}},
        {"_id": 0, "date": 1, "user_id": 1},
    ):
        trend_counts[r["date"]].add(r["user_id"])
    attendance_trend = [{"date": d2, "present": len(trend_counts.get(d2, set()))}
                        for d2 in days]

    # --- payroll trend (last 6 months: finalized-first compliance runs) ---
    months: List[str] = []
    y, m = int(month[:4]), int(month[5:7])
    for _ in range(6):
        months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    runs = await db.compliance_salary_runs.find(
        {**comp_q, "month": {"$in": months}},
        {"_id": 0, "month": 1, "company_id": 1, "finalized": 1,
         "generated_at": 1, "totals": 1, "rows": 1},
    ).sort("generated_at", -1).to_list(400)
    best_by: Dict[tuple, dict] = {}
    for r in runs:
        k = (r.get("company_id"), r["month"])
        cur = best_by.get(k)
        if cur is None or (r.get("finalized") and not cur.get("finalized")):
            best_by[k] = r
    payroll_by_month: Dict[str, float] = defaultdict(float)
    for (cid, mth), r in best_by.items():
        tot = (r.get("totals") or {}).get("net")
        if tot is None:
            tot = sum(float(x.get("net") or 0) for x in (r.get("rows") or []))
        payroll_by_month[mth] += float(tot or 0)
    payroll_trend = [{"month": m2, "net_total": round(payroll_by_month.get(m2, 0.0), 0)}
                     for m2 in months]

    # --- per-firm compliance status (current month) ---
    firm_q = {"company_id": company_id} if company_id else {}
    firms = await db.companies.find(firm_q, {"_id": 0, "company_id": 1, "name": 1}).to_list(200)
    month_runs = {r.get("company_id"): r for (cid, mth), r in best_by.items() if mth == month}
    compliance_status = []
    for f in firms:
        r = month_runs.get(f["company_id"])
        compliance_status.append({
            "company_id": f["company_id"],
            "name": f.get("name"),
            "status": ("finalized" if r and r.get("finalized")
                       else "processed" if r else "not_processed"),
        })
    compliance_status.sort(key=lambda x: {"not_processed": 0, "processed": 1, "finalized": 2}[x["status"]])

    # --- expiring compliance documents (30 days) ---
    horizon = (now + timedelta(days=30)).strftime("%Y-%m-%d")
    expiring_docs = 0
    try:
        expiring_docs = await db.compliance_documents.count_documents(
            {**comp_q, "expiry_date": {"$gte": today, "$lte": horizon}})
    except Exception:
        pass

    return {
        "generated_at": now.strftime("%d-%m-%Y %I:%M %p"),
        "month": month,
        "kpis": {
            "total_employees": total_employees,
            "present_today": len(present_uids),
            "absent_today": max(0, total_employees - len(present_uids)),
            "pending_punch_approvals": pending_punches,
            "pending_leaves": pending_leaves,
            "open_tickets": open_tickets,
            "expiring_documents_30d": expiring_docs,
            "firms": len(firms),
            "payroll_finalized_firms": sum(1 for c in compliance_status if c["status"] == "finalized"),
        },
        "attendance_trend": attendance_trend,
        "payroll_trend": payroll_trend,
        "compliance_status": compliance_status[:50],
        "compliance_calendar": _statutory_calendar(month),
    }
