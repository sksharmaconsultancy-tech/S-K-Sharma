"""Iter 588 — AI COMMAND CENTER backend (extends the AI Payroll Assistant).

The Command Center is the central AI workspace with 5 sections; this module
powers the three NEW ones (Ask AI reuses /admin/ai-assistant/command and
Approvals reuses /admin/approvals — no duplicated business logic):

  GET /api/admin/ai-cc/alerts    — rule-based alert engine (employee data,
                                   payroll, attendance, compliance) with
                                   CRITICAL / WARNING / INFO severity.
  GET /api/admin/ai-cc/insights  — automatic KPIs + month-over-month payroll
                                   comparison (period selectable).
  GET /api/admin/ai-cc/activity  — AI activity log (own chat history +
                                   AI_COMMAND / APPROVAL audit rows).

SECURITY: everything is server-side scoped. Firm resolution goes through
shared.authz.firm_ok — a sub-admin restricted to Firm A can never receive
Firm B data, whatever the AI/user asks. No LLM call happens here (the
detectors are deterministic rules → fast + cheap + safe).
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from server import db, get_user_from_token, require_role  # noqa: E402
from shared.authz import firm_ok  # noqa: E402

router = APIRouter(prefix="/api/admin/ai-cc", tags=["ai-command-center"])

# Field aliases used across legacy imports.
_AADHAAR = ["aadhar_number", "aadhaar_no"]
_BANK = ["bank_account", "bank_account_number"]
_IFSC = ["ifsc_code", "bank_ifsc"]
_UAN = ["uan", "uan_number"]
_ESIC = ["esic_number", "esic_ip_number"]


def _missing_q(fields: List[str]) -> Dict[str, Any]:
    """Mongo query: ALL alias fields empty/absent."""
    return {"$and": [{"$or": [{f: {"$exists": False}}, {f: None}, {f: ""}]}
                     for f in fields]}


async def _resolve_scope(admin: dict, company_id: Optional[str]) -> Optional[List[str]]:
    """Return the list of company_ids the response may cover (None = all,
    super admin without a firm filter). Raises 403 on out-of-scope firms."""
    role = admin["role"]
    if company_id:
        if not firm_ok(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm outside your scope")
        return [company_id]
    if role == "company_admin":
        return [admin.get("company_id")]
    if role == "sub_admin" and admin.get("sub_admin_company_scope") == "restricted":
        return admin.get("sub_admin_company_ids") or []
    return None  # super admin / unrestricted sub admin → all firms


def _emp_q(cids: Optional[List[str]], active_only: bool = True) -> Dict[str, Any]:
    q: Dict[str, Any] = {"role": "employee"}
    if cids is not None:
        q["company_id"] = {"$in": cids}
    if active_only:
        q["active"] = {"$ne": False}
        q["employment_status"] = {"$ne": "resigned"}
    return q


async def _sample_names(q: Dict[str, Any], limit: int = 5) -> List[str]:
    rows = await db.users.find(q, {"_id": 0, "name": 1, "employee_code": 1}).limit(limit).to_list(limit)
    return [f"{r.get('name')} ({r.get('employee_code') or '—'})" for r in rows]


@router.get("/alerts")
async def ai_alerts(company_id: Optional[str] = Query(None),
                    authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    cids = await _resolve_scope(admin, company_id)
    base = _emp_q(cids)
    alerts: List[Dict[str, Any]] = []

    async def add(aid: str, category: str, severity: str, title: str,
                  q: Dict[str, Any], route: str, detail: str = ""):
        n = await db.users.count_documents(q)
        if n > 0:
            alerts.append({"id": aid, "category": category, "severity": severity,
                           "title": title, "count": n, "detail": detail,
                           "sample": await _sample_names(q), "route": route})

    # ── Employee data ──
    await add("missing_aadhaar", "Employee Data", "WARNING",
              "Employees missing Aadhaar", {**base, **_missing_q(_AADHAAR)},
              "/kyc-tracker", "KYC incomplete — onboarding gate may hold punches")
    await add("missing_bank", "Employee Data", "CRITICAL",
              "Employees missing bank account", {**base, **_missing_q(_BANK)},
              "/kyc-tracker", "Salary/bank sheet cannot be paid out")
    await add("missing_ifsc", "Employee Data", "WARNING",
              "Employees missing IFSC", {**base, **_missing_q(_IFSC)}, "/kyc-tracker")
    await add("missing_uan", "Compliance", "WARNING",
              "Employees missing UAN (PF)", {**base, **_missing_q(_UAN)}, "/kyc-tracker",
              "PF ECR will reject rows without UAN")
    await add("missing_esic", "Compliance", "WARNING",
              "Employees missing ESIC number", {**base, **_missing_q(_ESIC)}, "/kyc-tracker")

    # Duplicate bank account / UAN (across the allowed scope) — CRITICAL.
    for aid, field_group, label in (("dup_bank", _BANK, "bank account"),
                                    ("dup_uan", _UAN, "UAN")):
        pipeline: List[Dict[str, Any]] = [
            {"$match": {**base, "$or": [{f: {"$nin": [None, ""]}} for f in field_group]}},
            {"$project": {"v": {"$ifNull": [f"${field_group[0]}", f"${field_group[1]}"]},
                          "name": 1, "employee_code": 1}},
            {"$match": {"v": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$v", "n": {"$sum": 1},
                        "names": {"$push": {"$concat": ["$name", " (", {"$ifNull": ["$employee_code", "—"]}, ")"]}}}},
            {"$match": {"n": {"$gt": 1}}}, {"$limit": 10},
        ]
        dups = await db.users.aggregate(pipeline).to_list(10)
        if dups:
            alerts.append({
                "id": aid, "category": "Employee Data", "severity": "CRITICAL",
                "title": f"Duplicate {label} shared by multiple employees",
                "count": len(dups),
                "detail": "; ".join(f"…{str(d['_id'])[-4:]}: {', '.join(d['names'][:3])}"
                                    for d in dups[:5]),
                "sample": [], "route": "/admin"})

    # No salary structure — new/active employee that payroll would skip.
    await add("no_salary_structure", "Payroll", "WARNING",
              "Active employees without any salary structure",
              {**base,
               "$and": [{"$or": [{"salary_monthly": {"$exists": False}},
                                 {"salary_monthly": None}, {"salary_monthly": 0}]},
                        {"$or": [{"salary_structure_actual": {"$exists": False}},
                                 {"salary_structure_actual": []}]}]},
              "/admin", "They will be skipped or paid ₹0 in the next salary run")

    # Unusual salary changes (last 31 days, ±30% = WARNING, >100% = CRITICAL).
    since = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    hq: Dict[str, Any] = {"changed_at": {"$gte": since}}
    if cids is not None:
        hq["company_id"] = {"$in": cids}
    big, huge = [], []
    async for h in db.salary_history.find(hq, {"_id": 0, "user_id": 1, "prev": 1, "next": 1}).limit(500):
        try:
            p = float((h.get("prev") or {}).get("salary_monthly") or 0)
            n = float((h.get("next") or {}).get("salary_monthly") or 0)
            if p > 0 and n > 0 and p != n:
                ratio = abs(n - p) / p
                if ratio > 1.0:
                    huge.append(h["user_id"])
                elif ratio > 0.3:
                    big.append(h["user_id"])
        except Exception:
            continue
    if huge:
        alerts.append({"id": "salary_jump_huge", "category": "Payroll", "severity": "CRITICAL",
                       "title": "Salary changed by more than 100% in the last 31 days",
                       "count": len(set(huge)), "detail": "Verify these changes were intended",
                       "sample": [], "route": "/pending-approvals"})
    if big:
        alerts.append({"id": "salary_jump", "category": "Payroll", "severity": "WARNING",
                       "title": "Salary changed by more than 30% in the last 31 days",
                       "count": len(set(big)), "detail": "", "sample": [],
                       "route": "/pending-approvals"})

    # Attendance — HELD / BLOCKED punches (eligibility engine).
    for st_, sev in (("BLOCKED", "CRITICAL"), ("HELD", "WARNING")):
        aq: Dict[str, Any] = {"eligibility_status": st_}
        if cids is not None:
            aq["company_id"] = {"$in": cids}
        n = (await db.attendance.count_documents(aq)
             + await db.zk_push.count_documents(aq))
        if n:
            alerts.append({"id": f"punches_{st_.lower()}", "category": "Attendance",
                           "severity": sev,
                           "title": f"{st_} punches awaiting HR action",
                           "count": n,
                           "detail": "These punches will NOT count in attendance/payroll until released",
                           "sample": [], "route": "/attendance-eligibility"})

    # Maker-checker queue backlog.
    pq: Dict[str, Any] = {"status": "PENDING"}
    if cids is not None:
        pq["company_id"] = {"$in": cids}
    pending = await db.pending_approvals.count_documents(pq)
    if pending:
        alerts.append({"id": "pending_approvals", "category": "Payroll", "severity": "INFO",
                       "title": "Approval requests waiting in the Maker-Checker queue",
                       "count": pending, "detail": "", "sample": [],
                       "route": "/pending-approvals"})

    order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    alerts.sort(key=lambda a: (order.get(a["severity"], 3), -a["count"]))
    counts = {s: sum(1 for a in alerts if a["severity"] == s)
              for s in ("CRITICAL", "WARNING", "INFO")}
    return {"alerts": alerts, "counts": counts,
            "scope": "all_firms" if cids is None else cids}


def _month_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


@router.get("/insights")
async def ai_insights(company_id: Optional[str] = Query(None),
                      period: str = Query("this_month"),
                      authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    cids = await _resolve_scope(admin, company_id)

    now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)  # IST
    if period == "prev_month":
        ref = (now.replace(day=1) - timedelta(days=1))
    else:
        ref = now
    month = _month_str(ref)
    prev_month = _month_str(ref.replace(day=1) - timedelta(days=1))

    # ── Employees ──
    base_all = _emp_q(cids, active_only=False)
    base_active = _emp_q(cids)
    total = await db.users.count_documents(base_all)
    active = await db.users.count_documents(base_active)
    resigned = await db.users.count_documents({**base_all, "employment_status": "resigned"})
    joiners = await db.users.count_documents(
        {**base_all, "$or": [{"joining_date": {"$regex": f"^{month}"}},
                             {"created_at": {"$regex": f"^{month}"}}]})
    exits = await db.users.count_documents(
        {**base_all, "exit_date": {"$regex": f"^{month}"}})
    dept = await db.users.aggregate([
        {"$match": base_active},
        {"$group": {"_id": {"$ifNull": ["$department", "—"]}, "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 8}]).to_list(8)

    # ── Payroll (compliance runs = statutory source of truth) ──
    async def run_totals(m: str) -> Dict[str, float]:
        rq: Dict[str, Any] = {"month": m}
        if cids is not None:
            rq["company_id"] = {"$in": cids}
        out = {"gross": 0.0, "net": 0.0, "pf_employee": 0.0, "pf_employer": 0.0,
               "esic_employee": 0.0, "esic_employer": 0.0, "runs": 0}
        async for r in db.compliance_salary_runs.find(rq, {"_id": 0, "totals": 1}):
            t = r.get("totals") or {}
            out["gross"] += float(t.get("gross_paid") or t.get("monthly_gross") or 0)
            out["net"] += float(t.get("net") or 0)
            out["pf_employee"] += float(t.get("pf_employee") or 0)
            out["pf_employer"] += float(t.get("pf_employer_total") or 0)
            out["esic_employee"] += float(t.get("esic_employee") or 0)
            out["esic_employer"] += float(t.get("esic_employer") or 0)
            out["runs"] += 1
        return {k: round(v, 2) for k, v in out.items()}

    cur = await run_totals(month)
    prev = await run_totals(prev_month)
    growth = None
    if prev["gross"] > 0:
        growth = round((cur["gross"] - prev["gross"]) / prev["gross"] * 100, 1)

    # ── Attendance (period month) ──
    today = now.strftime("%Y-%m-%d")
    atq: Dict[str, Any] = {"date": today, "kind": "in",
                           "eligibility_status": {"$nin": ["HELD", "BLOCKED"]}}
    if cids is not None:
        atq["company_id"] = {"$in": cids}
    present_today = len(await db.attendance.distinct("user_id", atq))
    mq: Dict[str, Any] = {"date": {"$regex": f"^{month}"}, "kind": "in"}
    if cids is not None:
        mq["company_id"] = {"$in": cids}
    punch_days = len(await db.attendance.distinct("date", mq))

    # ── Compliance ──
    pf_eligible = await db.users.count_documents(
        {**base_active, "$or": [{f: {"$nin": [None, ""]}} for f in _UAN]})
    esic_eligible = await db.users.count_documents(
        {**base_active, "$or": [{f: {"$nin": [None, ""]}} for f in _ESIC]})
    missing_kyc = await db.users.count_documents({**base_active, **_missing_q(_AADHAAR)})

    return {
        "period": period, "month": month, "prev_month": prev_month,
        "scope": "all_firms" if cids is None else cids,
        "employees": {"total": total, "active": active, "resigned": resigned,
                      "new_joiners": joiners, "exits": exits,
                      "by_department": [{"department": d["_id"], "count": d["n"]} for d in dept]},
        "payroll": {"month": cur, "previous": prev, "growth_pct": growth},
        "attendance": {"present_today": present_today, "active_employees": active,
                       "present_pct_today": round(present_today / active * 100, 1) if active else 0,
                       "punch_days_this_month": punch_days},
        "compliance": {"pf_eligible": pf_eligible, "esic_eligible": esic_eligible,
                       "missing_aadhaar": missing_kyc},
    }


@router.get("/activity")
async def ai_activity(authorization: Optional[str] = Header(None)):
    """AI activity trail. Own chat exchanges + (for super admin) every
    user's AI_COMMAND / approval audit rows from the immutable activity_log."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    aq: Dict[str, Any] = {"action": {"$in": ["AI_COMMAND", "APPROVAL_REQUESTED",
                                             "APPROVAL_APPROVED", "APPROVAL_REJECTED"]}}
    if admin["role"] != "super_admin":
        aq["user_id"] = admin["user_id"]
    audit = await db.activity_log.find(aq, {"_id": 0}).sort("at", -1).to_list(100)
    chat = await db.ai_chat_history.find(
        {"user_id": admin["user_id"]}, {"_id": 0}).sort("at", -1).to_list(40)
    return {"audit": audit, "chat": list(reversed(chat))}
