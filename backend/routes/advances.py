"""Employee Advance Management — enterprise module.

Salary / Festival / Loan / Emergency / Medical / Travel / Other advances
with Single-shot or Monthly-EMI recovery, synchronized with BOTH the
Compliance Salary Process and the Actual Salary Process.

Collections
-----------
advances:
  advance_id, voucher_no, user_id, company_id, employee snapshot fields,
  advance_date, advance_type, amount, purpose, payment_mode, remarks,
  recovery_type (single|emi), emi_amount, installments, start_month,
  end_month, recovery_source (compliance|actual|both), priority
  (high|normal|low), recovered_total, remaining_balance,
  status (scheduled|active|on_hold|closed|waived), skip_months [..],
  audit [{at, by, action, detail}], created_at/by

advance_transactions:
  txn_id, advance_id, user_id, company_id, salary_month, amount,
  process_type (compliance|actual|manual|fnf|waiver), run_id,
  balance_applied (bool — 'both'-source mirrors don't re-apply),
  remaining_after, remarks, at, by

Salary integration
------------------
``apply_advance_recovery`` is called from server.py inside the
compliance run compute (create + reprocess) and the actual salary
process create. It is IDEMPOTENT per (advance, month, process): re-runs
reuse the recorded transaction for display without double-deducting.
For ``recovery_source="both"`` the balance decrements only once per
month; the second process shows a mirrored deduction line.
"""
import io
import math
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    require_permission,
    sub_admin_can_touch_company,
    now_iso,
    logger,
)

router = APIRouter(prefix="/api", tags=["advances"])

ADVANCE_TYPES = [
    "Salary Advance", "Festival Advance", "Loan Recovery",
    "Emergency Advance", "Medical Advance", "Travel Advance", "Other",
]
PAYMENT_MODES = ["Cash", "Bank", "UPI", "Cheque"]
PRIO_ORDER = {"high": 0, "normal": 1, "low": 2}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _month_add(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _audit(by: str, action: str, detail: str) -> dict:
    return {"at": now_iso(), "by": by, "action": action, "detail": detail}


async def _next_voucher_no() -> str:
    doc = await db.counters.find_one_and_update(
        {"_id": "advance_voucher"}, {"$inc": {"seq": 1}},
        upsert=True, return_document=True,
    )
    return f"ADV-{int(doc['seq']):05d}"


def _pub(a: dict) -> dict:
    return {k: v for k, v in a.items() if k != "_id"}


async def _scoped_admin(authorization, write=False):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    require_permission(admin, "salary_process:write" if write else "salary_process:read")
    return admin


def _check_scope(admin: dict, company_id: Optional[str]):
    if admin["role"] == "company_admin" and company_id != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm")
    if admin["role"] == "sub_admin" and company_id and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm outside your scope")


def _effective_status(a: dict, today_month: str) -> str:
    """scheduled → active promotion is computed lazily on read."""
    s = a.get("status") or "active"
    if s == "scheduled" and (a.get("start_month") or "") <= today_month:
        return "active"
    return s


def _schedule(a: dict, txns: List[dict]) -> List[dict]:
    """Installment schedule with per-month recovered amounts."""
    if a.get("recovery_type") != "emi":
        rows = []
        m = a.get("start_month") or (a.get("advance_date") or "")[:7]
        ded = sum(t["amount"] for t in txns if t.get("balance_applied", True))
        rows.append({
            "no": 1, "month": m, "emi": a.get("amount"),
            "deducted": round(ded, 2),
            "remaining_after": round(float(a.get("amount") or 0) - ded, 2),
            "status": "paid" if ded >= float(a.get("amount") or 0) else (
                "skipped" if m in (a.get("skip_months") or []) else "upcoming"),
        })
        return rows
    by_month: Dict[str, float] = defaultdict(float)
    for t in txns:
        if t.get("balance_applied", True):
            by_month[t.get("salary_month") or ""] += float(t.get("amount") or 0)
    rows = []
    remaining = float(a.get("amount") or 0)
    n = int(a.get("installments") or 1)
    m = a.get("start_month")
    skips = set(a.get("skip_months") or [])
    i = 0
    guard = 0
    while i < n and guard < 120:
        guard += 1
        if m in skips:
            rows.append({"no": None, "month": m, "emi": 0, "deducted": 0,
                         "remaining_after": round(remaining, 2), "status": "skipped"})
            m = _month_add(m, 1)
            continue
        i += 1
        emi = min(float(a.get("emi_amount") or 0), remaining)
        ded = round(by_month.get(m, 0.0), 2)
        remaining = round(remaining - (ded if ded > 0 else 0), 2)
        rows.append({
            "no": i, "month": m, "emi": round(emi, 2), "deducted": ded,
            "remaining_after": remaining,
            "status": "paid" if ded > 0 else "upcoming",
        })
        m = _month_add(m, 1)
    return rows


def _next_recovery_month(a: dict, today_month: str) -> Optional[str]:
    if (a.get("status") in ("closed", "waived", "on_hold")):
        return None
    m = max(a.get("start_month") or today_month, today_month)
    if (a.get("last_deduction_month") or "") >= m:
        m = _month_add(a["last_deduction_month"], 1)
    skips = set(a.get("skip_months") or [])
    for _ in range(60):
        if m not in skips:
            return m
        m = _month_add(m, 1)
    return m


# ---------------------------------------------------------------------------
# SALARY PROCESS HOOK (called from server.py)
# ---------------------------------------------------------------------------
async def apply_advance_recovery(
    company_id: Optional[str],
    month: str,
    process_type: str,          # "compliance" | "actual"
    run_id: str,
    rows: List[dict],
) -> float:
    """Deduct active advances into salary rows. Idempotent per month+process.
    Mutates rows in place; returns total newly-shown deduction."""
    try:
        user_ids = [r.get("user_id") for r in rows if r.get("user_id")]
        if not user_ids:
            return 0.0
        q: Dict[str, Any] = {
            "user_id": {"$in": user_ids},
            "status": {"$in": ["active", "scheduled"]},
            "recovery_source": {"$in": [process_type, "both"]},
            "start_month": {"$lte": month},
        }
        if company_id:
            q["company_id"] = company_id
        advances = await db.advances.find(q, {"_id": 0}).to_list(5000)
        if not advances:
            return 0.0
        adv_ids = [a["advance_id"] for a in advances]
        # txns already written for this month (any process — needed for
        # 'both' mirroring + idempotency)
        month_txns: Dict[str, List[dict]] = defaultdict(list)
        async for t in db.advance_transactions.find(
            {"advance_id": {"$in": adv_ids}, "salary_month": month}, {"_id": 0},
        ):
            month_txns[t["advance_id"]].append(t)

        by_user: Dict[str, List[dict]] = defaultdict(list)
        for a in advances:
            by_user[a["user_id"]].append(a)

        net_key = "net" if process_type == "compliance" else "net_pay"
        total_new = 0.0
        for row in rows:
            advs = by_user.get(row.get("user_id"))
            if not advs:
                continue
            advs.sort(key=lambda a: (
                PRIO_ORDER.get((a.get("priority") or "normal").lower(), 1),
                a.get("advance_date") or "", a.get("created_at") or "",
            ))
            available = float(row.get(net_key) or 0.0)
            row_total = 0.0
            for a in advs:
                aid = a["advance_id"]
                txns = month_txns.get(aid, [])
                same_proc = [t for t in txns if t.get("process_type") == process_type]
                if same_proc:  # idempotent re-run → display existing amount
                    amt = round(sum(float(t.get("amount") or 0) for t in same_proc), 2)
                    row_total += amt
                    available -= amt
                    continue
                if month in (a.get("skip_months") or []):
                    continue
                applied_other = [t for t in txns if t.get("balance_applied")]
                if applied_other:
                    # 'both' source — mirror the deduction, no balance change
                    amt = round(sum(float(t.get("amount") or 0) for t in applied_other), 2)
                    if amt <= 0:
                        continue
                    await db.advance_transactions.insert_one({
                        "txn_id": f"advtxn_{uuid.uuid4().hex[:12]}",
                        "advance_id": aid, "user_id": a["user_id"],
                        "company_id": a.get("company_id"),
                        "salary_month": month, "amount": amt,
                        "process_type": process_type, "run_id": run_id,
                        "balance_applied": False,
                        "remaining_after": float(a.get("remaining_balance") or 0),
                        "remarks": "Mirror (recovery source: both)",
                        "at": now_iso(), "by": "system",
                    })
                    row_total += amt
                    available -= amt
                    total_new += amt
                    continue
                remaining = float(a.get("remaining_balance") or 0)
                if remaining <= 0:
                    continue
                amt = remaining if a.get("recovery_type") == "single" else min(
                    float(a.get("emi_amount") or 0), remaining)
                amt = round(min(amt, max(0.0, available)), 2)
                if amt <= 0:
                    continue
                new_rem = round(remaining - amt, 2)
                await db.advance_transactions.insert_one({
                    "txn_id": f"advtxn_{uuid.uuid4().hex[:12]}",
                    "advance_id": aid, "user_id": a["user_id"],
                    "company_id": a.get("company_id"),
                    "salary_month": month, "amount": amt,
                    "process_type": process_type, "run_id": run_id,
                    "balance_applied": True,
                    "remaining_after": new_rem, "remarks": None,
                    "at": now_iso(), "by": "system",
                })
                upd: Dict[str, Any] = {
                    "remaining_balance": new_rem,
                    "recovered_total": round(float(a.get("recovered_total") or 0) + amt, 2),
                    "last_deduction_month": month,
                    "updated_at": now_iso(),
                }
                if new_rem <= 0:
                    upd["status"] = "closed"
                    upd["closed_at"] = now_iso()
                elif a.get("status") == "scheduled":
                    upd["status"] = "active"
                await db.advances.update_one(
                    {"advance_id": aid},
                    {"$set": upd, "$push": {"audit": _audit(
                        "system", "recovery",
                        f"{process_type} {month}: -₹{amt} (balance ₹{new_rem})")}},
                )
                a["remaining_balance"] = new_rem  # keep in-memory copy fresh
                a["status"] = upd.get("status", a.get("status"))
                row_total += amt
                available -= amt
                total_new += amt
            if row_total > 0:
                row_total = round(row_total, 2)
                row["advance_recovery"] = row_total
                if process_type == "compliance":
                    row["total_deduction"] = round(float(row.get("total_deduction") or 0) + row_total, 2)
                    row["net"] = round(float(row.get("net") or 0) - row_total, 2)
                else:
                    row["adv"] = round(float(row.get("adv") or 0) + row_total, 2)
                    row["net_pay"] = round(float(row.get("net_pay") or 0) - row_total, 2)
        return round(total_new, 2)
    except Exception:
        logger.exception("[advances] apply_advance_recovery failed — salary run continues")
        return 0.0


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
class AdvanceCreate(BaseModel):
    user_id: str
    advance_date: str                     # YYYY-MM-DD
    advance_type: str = "Salary Advance"
    amount: float
    purpose: Optional[str] = None
    payment_mode: str = "Cash"
    remarks: Optional[str] = None
    recovery_type: str = "emi"            # single | emi
    emi_amount: Optional[float] = None
    installments: Optional[int] = None
    start_month: str                      # YYYY-MM
    recovery_source: str = "both"         # compliance | actual | both
    priority: str = "normal"              # high | normal | low


@router.post("/admin/advances")
async def create_advance(payload: AdvanceCreate, authorization: Optional[str] = Header(None)):
    admin = await _scoped_admin(authorization, write=True)
    emp = await db.users.find_one({"user_id": payload.user_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    _check_scope(admin, emp.get("company_id"))

    amount = round(float(payload.amount or 0), 2)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Advance amount must be > 0")
    if payload.recovery_type not in ("single", "emi"):
        raise HTTPException(status_code=400, detail="recovery_type must be single|emi")
    if payload.recovery_source not in ("compliance", "actual", "both"):
        raise HTTPException(status_code=400, detail="Invalid recovery_source")
    if len(payload.start_month or "") != 7:
        raise HTTPException(status_code=400, detail="start_month must be YYYY-MM")

    emi = None
    installments = 1
    if payload.recovery_type == "emi":
        emi = round(float(payload.emi_amount or 0), 2)
        if emi <= 0:
            raise HTTPException(status_code=400, detail="EMI amount must be > 0")
        if emi > amount:
            raise HTTPException(status_code=400, detail="EMI cannot exceed advance amount")
        installments = int(payload.installments or 0) or math.ceil(amount / emi)
        # never allow schedule shorter than what EMI can recover
        installments = max(installments, math.ceil(amount / emi))
    end_month = _month_add(payload.start_month, installments - 1)

    a = {
        "advance_id": f"adv_{uuid.uuid4().hex[:12]}",
        "voucher_no": await _next_voucher_no(),
        "user_id": emp["user_id"],
        "company_id": emp.get("company_id"),
        "employee_code": emp.get("employee_code"),
        "employee_name": emp.get("name"),
        "father_name": emp.get("father_name"),
        "department": emp.get("department"),
        "designation": emp.get("designation"),
        "branch_name": emp.get("branch_name"),
        "contractor_name": emp.get("contractor_name"),
        "uan_no": emp.get("uan_no"),
        "esi_ip_no": emp.get("esi_ip_no"),
        "advance_date": payload.advance_date,
        "advance_type": payload.advance_type if payload.advance_type in ADVANCE_TYPES else "Other",
        "amount": amount,
        "purpose": (payload.purpose or "").strip() or None,
        "payment_mode": payload.payment_mode if payload.payment_mode in PAYMENT_MODES else "Cash",
        "remarks": (payload.remarks or "").strip() or None,
        "recovery_type": payload.recovery_type,
        "emi_amount": emi,
        "installments": installments,
        "start_month": payload.start_month,
        "end_month": end_month,
        "recovery_source": payload.recovery_source,
        "priority": payload.priority if payload.priority in PRIO_ORDER else "normal",
        "recovered_total": 0.0,
        "remaining_balance": amount,
        "status": "scheduled" if payload.start_month > now_iso()[:7] else "active",
        "skip_months": [],
        "audit": [_audit(admin["user_id"], "create",
                         f"Advance ₹{amount} ({payload.recovery_type})")],
        "created_at": now_iso(),
        "created_by": admin["user_id"],
    }
    # RBAC Phase 3 — if this firm has an enabled approval workflow for the
    # 'advance' module, park the advance as pending_approval and raise an
    # approval request. It only becomes active once the chain approves.
    from routes.approvals_engine import get_active_workflow, create_approval_request
    wf = await get_active_workflow(emp.get("company_id") or "", "advance")
    approval_request = None
    if wf:
        a["status"] = "pending_approval"
        a["audit"].append(_audit(admin["user_id"], "approval", "Sent for approval (workflow)"))
    await db.advances.insert_one(a)
    if wf:
        approval_request = await create_approval_request(
            company_id=emp.get("company_id") or "",
            module="advance",
            record_id=a["advance_id"],
            title=f"{a['voucher_no']} · {a['employee_name']} · ₹{amount}",
            summary={
                "voucher_no": a["voucher_no"], "employee_name": a["employee_name"],
                "employee_code": a.get("employee_code"), "amount": amount,
                "advance_type": a["advance_type"], "recovery_type": a["recovery_type"],
                "emi_amount": a.get("emi_amount"), "start_month": a["start_month"],
            },
            requested_by=admin,
            workflow=wf,
        )
    return {"ok": True, "advance": _pub(a),
            "pending_approval": bool(wf),
            "approval_request_id": (approval_request or {}).get("request_id")}


@router.get("/admin/advances")
async def list_advances(
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await _scoped_admin(authorization)
    query: Dict[str, Any] = {}
    if admin["role"] == "company_admin":
        query["company_id"] = admin.get("company_id")
    elif company_id:
        _check_scope(admin, company_id)
        query["company_id"] = company_id
    if user_id:
        query["user_id"] = user_id
    if status and status != "all":
        query["status"] = status
    if q:
        rx = {"$regex": q.strip(), "$options": "i"}
        query["$or"] = [{"employee_name": rx}, {"employee_code": rx}, {"voucher_no": rx}]
    items = await db.advances.find(query, {"_id": 0, "audit": 0}).sort("created_at", -1).to_list(2000)
    tm = now_iso()[:7]
    for a in items:
        a["status"] = _effective_status(a, tm)
        a["next_recovery_month"] = _next_recovery_month(a, tm)
    summary = {
        "active": sum(1 for a in items if a["status"] in ("active", "scheduled")),
        "on_hold": sum(1 for a in items if a["status"] == "on_hold"),
        "closed": sum(1 for a in items if a["status"] in ("closed", "waived")),
        "outstanding": round(sum(float(a.get("remaining_balance") or 0)
                                 for a in items if a["status"] not in ("closed", "waived")), 2),
        "recovered": round(sum(float(a.get("recovered_total") or 0) for a in items), 2),
        "employees": len({a["user_id"] for a in items if a["status"] in ("active", "scheduled", "on_hold")}),
    }
    return {"advances": items, "summary": summary}


@router.get("/admin/advances/dashboard")
async def advances_dashboard(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await _scoped_admin(authorization)
    query: Dict[str, Any] = {}
    if admin["role"] == "company_admin":
        query["company_id"] = admin.get("company_id")
    elif company_id:
        _check_scope(admin, company_id)
        query["company_id"] = company_id
    items = await db.advances.find(query, {"_id": 0, "audit": 0}).to_list(5000)
    tm = now_iso()[:7]
    for a in items:
        a["status"] = _effective_status(a, tm)
    open_items = [a for a in items if a["status"] not in ("closed", "waived")]

    # Recovered this month + 6-month trend
    tq = dict(query)
    months = [_month_add(tm, -i) for i in range(5, -1, -1)]
    trend = {m: 0.0 for m in months}
    async for t in db.advance_transactions.find(
        {**({"company_id": query["company_id"]} if query.get("company_id") else {}),
         "salary_month": {"$in": months}, "balance_applied": True}, {"_id": 0},
    ):
        trend[t["salary_month"]] = round(trend.get(t["salary_month"], 0) + float(t.get("amount") or 0), 2)

    def _group(key):
        g: Dict[str, float] = defaultdict(float)
        for a in open_items:
            g[(a.get(key) or "—")] += float(a.get("remaining_balance") or 0)
        return sorted(
            [{"label": k, "value": round(v, 2)} for k, v in g.items()],
            key=lambda x: -x["value"])[:8]

    total_amount = sum(float(a.get("amount") or 0) for a in items)
    total_recovered = sum(float(a.get("recovered_total") or 0) for a in items)
    return {
        "kpis": {
            "active": len([a for a in open_items if a["status"] != "on_hold"]),
            "on_hold": len([a for a in open_items if a["status"] == "on_hold"]),
            "outstanding": round(sum(float(a.get("remaining_balance") or 0) for a in open_items), 2),
            "recovered_this_month": trend.get(tm, 0.0),
            "pending_recovery": round(sum(float(a.get("remaining_balance") or 0) for a in open_items), 2),
            "closed": len([a for a in items if a["status"] in ("closed", "waived")]),
            "employees": len({a["user_id"] for a in open_items}),
            "recovery_rate": round(100.0 * total_recovered / total_amount, 1) if total_amount else 0.0,
        },
        "trend": [{"month": m, "value": trend[m]} for m in months],
        "by_department": _group("department"),
        "by_contractor": _group("contractor_name"),
        "by_type": _group("advance_type"),
    }


REPORT_KINDS = {
    "register": "Employee Advance Register",
    "outstanding": "Outstanding Advance Report",
    "monthly_recovery": "Monthly Recovery Report",
    "department": "Department Wise Report",
    "contractor": "Contractor Wise Report",
    "company": "Company Wise Report",
    "closed": "Closed Advances Report",
    "pending": "Pending Recovery Report",
    "recovery_history": "Recovery History",
}


@router.get("/admin/advances/reports")
async def advances_report(
    kind: str = Query("register"),
    company_id: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    format: str = Query("json"),
    authorization: Optional[str] = Header(None),
):
    admin = await _scoped_admin(authorization)
    if kind not in REPORT_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {list(REPORT_KINDS)}")
    query: Dict[str, Any] = {}
    if admin["role"] == "company_admin":
        query["company_id"] = admin.get("company_id")
    elif company_id:
        _check_scope(admin, company_id)
        query["company_id"] = company_id

    tm = now_iso()[:7]
    comp_names: Dict[str, str] = {}
    async for c in db.companies.find({}, {"_id": 0, "company_id": 1, "name": 1}):
        comp_names[c.get("company_id") or ""] = c.get("name") or ""

    if kind in ("monthly_recovery", "recovery_history"):
        tq = dict(query)
        if kind == "monthly_recovery":
            tq["salary_month"] = month or tm
        txns = await db.advance_transactions.find(tq, {"_id": 0}).sort("at", -1).to_list(5000)
        adv_map = {}
        aids = list({t["advance_id"] for t in txns})
        if aids:
            async for a in db.advances.find({"advance_id": {"$in": aids}}, {"_id": 0, "audit": 0}):
                adv_map[a["advance_id"]] = a
        columns = ["Voucher", "Employee", "Code", "Month", "Amount", "Process", "Balance After", "Date"]
        rows = [[
            (adv_map.get(t["advance_id"]) or {}).get("voucher_no"),
            (adv_map.get(t["advance_id"]) or {}).get("employee_name"),
            (adv_map.get(t["advance_id"]) or {}).get("employee_code"),
            t.get("salary_month"), t.get("amount"),
            t.get("process_type") + ("" if t.get("balance_applied", True) else " (mirror)"),
            t.get("remaining_after"), (t.get("at") or "")[:10],
        ] for t in txns]
    else:
        items = await db.advances.find(query, {"_id": 0, "audit": 0}).sort("created_at", -1).to_list(5000)
        for a in items:
            a["status"] = _effective_status(a, tm)
        if kind == "outstanding" or kind == "pending":
            items = [a for a in items if a["status"] not in ("closed", "waived")
                     and float(a.get("remaining_balance") or 0) > 0]
        elif kind == "closed":
            items = [a for a in items if a["status"] in ("closed", "waived")]
        if kind in ("department", "contractor", "company"):
            key = {"department": "department", "contractor": "contractor_name", "company": "company_id"}[kind]
            g: Dict[str, dict] = {}
            for a in items:
                if a["status"] in ("closed", "waived"):
                    continue
                k = a.get(key) or "—"
                if kind == "company":
                    k = comp_names.get(k, k)
                d = g.setdefault(k, {"count": 0, "amount": 0.0, "recovered": 0.0, "outstanding": 0.0})
                d["count"] += 1
                d["amount"] += float(a.get("amount") or 0)
                d["recovered"] += float(a.get("recovered_total") or 0)
                d["outstanding"] += float(a.get("remaining_balance") or 0)
            columns = [kind.title(), "Advances", "Amount", "Recovered", "Outstanding"]
            rows = [[k, d["count"], round(d["amount"], 2), round(d["recovered"], 2), round(d["outstanding"], 2)]
                    for k, d in sorted(g.items(), key=lambda kv: -kv[1]["outstanding"])]
        else:
            columns = ["Voucher", "Date", "Employee", "Code", "Type", "Amount",
                       "Recovery", "EMI", "Recovered", "Outstanding", "Source", "Status"]
            rows = [[
                a.get("voucher_no"), a.get("advance_date"), a.get("employee_name"),
                a.get("employee_code"), a.get("advance_type"), a.get("amount"),
                a.get("recovery_type"), a.get("emi_amount"),
                a.get("recovered_total"), a.get("remaining_balance"),
                a.get("recovery_source"), a.get("status"),
            ] for a in items]

    if format == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = kind[:28]
        ws.append([REPORT_KINDS[kind]])
        ws.append(columns)
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="advance_{kind}.xlsx"'},
        )
    return {"title": REPORT_KINDS[kind], "columns": columns, "rows": rows}


@router.get("/admin/advances/{advance_id}")
async def get_advance(advance_id: str, authorization: Optional[str] = Header(None)):
    admin = await _scoped_admin(authorization)
    a = await db.advances.find_one({"advance_id": advance_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Advance not found")
    _check_scope(admin, a.get("company_id"))
    txns = await db.advance_transactions.find(
        {"advance_id": advance_id}, {"_id": 0}).sort("at", 1).to_list(500)
    tm = now_iso()[:7]
    a["status"] = _effective_status(a, tm)
    a["next_recovery_month"] = _next_recovery_month(a, tm)
    return {"advance": a, "transactions": txns, "schedule": _schedule(a, txns)}


@router.patch("/admin/advances/{advance_id}")
async def update_advance(
    advance_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Edit basic fields. Structural money fields only editable before any
    recovery has happened."""
    admin = await _scoped_admin(authorization, write=True)
    a = await db.advances.find_one({"advance_id": advance_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Advance not found")
    _check_scope(admin, a.get("company_id"))
    if a.get("status") in ("closed", "waived"):
        raise HTTPException(status_code=400, detail="Advance is closed")

    updates: Dict[str, Any] = {}
    for k in ("advance_date", "advance_type", "purpose", "payment_mode",
              "remarks", "recovery_source", "priority"):
        if k in payload:
            updates[k] = payload[k]
    recovered = float(a.get("recovered_total") or 0)
    if recovered <= 0:
        if "amount" in payload:
            amt = round(float(payload["amount"] or 0), 2)
            if amt <= 0:
                raise HTTPException(status_code=400, detail="Amount must be > 0")
            updates["amount"] = amt
            updates["remaining_balance"] = amt
        if "start_month" in payload:
            updates["start_month"] = payload["start_month"]
        if "recovery_type" in payload:
            updates["recovery_type"] = payload["recovery_type"]
    if "emi_amount" in payload:  # EMI change allowed anytime (audit-logged)
        emi = round(float(payload["emi_amount"] or 0), 2)
        if emi <= 0:
            raise HTTPException(status_code=400, detail="EMI must be > 0")
        rem = float(updates.get("remaining_balance", a.get("remaining_balance")) or 0)
        if emi > rem:
            raise HTTPException(status_code=400, detail="EMI cannot exceed remaining balance")
        updates["emi_amount"] = emi
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    # recompute installments/end month if money fields changed
    amt = float(updates.get("amount", a.get("amount")) or 0)
    emi = float(updates.get("emi_amount", a.get("emi_amount")) or 0)
    rtype = updates.get("recovery_type", a.get("recovery_type"))
    start = updates.get("start_month", a.get("start_month"))
    if rtype == "emi" and emi > 0:
        n = math.ceil(amt / emi)
        updates["installments"] = n
        updates["end_month"] = _month_add(start, n - 1)
    updates["updated_at"] = now_iso()
    await db.advances.update_one(
        {"advance_id": advance_id},
        {"$set": updates, "$push": {"audit": _audit(
            admin["user_id"], "edit", f"Updated: {', '.join(updates)}")}},
    )
    fresh = await db.advances.find_one({"advance_id": advance_id}, {"_id": 0, "audit": 0})
    return {"ok": True, "advance": fresh}


@router.post("/admin/advances/{advance_id}/action")
async def advance_action(
    advance_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """pause | resume | skip_month | recover_full | waive"""
    admin = await _scoped_admin(authorization, write=True)
    a = await db.advances.find_one({"advance_id": advance_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Advance not found")
    _check_scope(admin, a.get("company_id"))
    action = (payload.get("action") or "").strip()
    remarks = (payload.get("remarks") or "").strip()
    tm = now_iso()[:7]
    status = _effective_status(a, tm)

    if action in ("recover_full", "waive") and status in ("closed", "waived"):
        raise HTTPException(status_code=400, detail="Advance already closed")

    if action == "pause":
        if status in ("closed", "waived"):
            raise HTTPException(status_code=400, detail="Advance already closed")
        upd = {"status": "on_hold"}
        detail = f"Recovery paused. {remarks}"
    elif action == "resume":
        if a.get("status") != "on_hold":
            raise HTTPException(status_code=400, detail="Advance is not on hold")
        upd = {"status": "active"}
        detail = f"Recovery resumed. {remarks}"
    elif action == "skip_month":
        month = (payload.get("month") or "").strip()
        if len(month) != 7:
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
        if not remarks:
            raise HTTPException(status_code=400, detail="Remarks are mandatory to skip an EMI")
        if month in (a.get("skip_months") or []):
            raise HTTPException(status_code=400, detail="Month already skipped")
        await db.advances.update_one(
            {"advance_id": advance_id},
            {"$push": {"skip_months": month,
                       "audit": _audit(admin["user_id"], "skip_month", f"{month}: {remarks}")},
             "$set": {"updated_at": now_iso()}},
        )
        fresh = await db.advances.find_one({"advance_id": advance_id}, {"_id": 0, "audit": 0})
        return {"ok": True, "advance": fresh}
    elif action in ("recover_full", "waive"):
        remaining = float(a.get("remaining_balance") or 0)
        if remaining <= 0:
            raise HTTPException(status_code=400, detail="Nothing left to recover")
        if action == "waive" and not remarks:
            raise HTTPException(status_code=400, detail="Remarks are mandatory to waive a balance")
        ptype = "waiver" if action == "waive" else (
            "fnf" if payload.get("mode") == "fnf" else "manual")
        await db.advance_transactions.insert_one({
            "txn_id": f"advtxn_{uuid.uuid4().hex[:12]}",
            "advance_id": advance_id, "user_id": a["user_id"],
            "company_id": a.get("company_id"),
            "salary_month": tm, "amount": remaining,
            "process_type": ptype, "run_id": None,
            "balance_applied": True, "remaining_after": 0.0,
            "remarks": remarks or None, "at": now_iso(), "by": admin["user_id"],
        })
        upd = {
            "remaining_balance": 0.0,
            "recovered_total": round(float(a.get("recovered_total") or 0) + (0 if action == "waive" else remaining), 2),
            "status": "waived" if action == "waive" else "closed",
            "closed_at": now_iso(),
        }
        detail = (f"Balance ₹{remaining} {'waived' if action == 'waive' else f'recovered in full ({ptype})'}. {remarks}")
    else:
        raise HTTPException(status_code=400, detail="Unknown action")

    upd["updated_at"] = now_iso()
    await db.advances.update_one(
        {"advance_id": advance_id},
        {"$set": upd, "$push": {"audit": _audit(admin["user_id"], action, detail)}},
    )
    fresh = await db.advances.find_one({"advance_id": advance_id}, {"_id": 0, "audit": 0})
    return {"ok": True, "advance": fresh}


@router.delete("/admin/advances/{advance_id}")
async def delete_advance(advance_id: str, authorization: Optional[str] = Header(None)):
    admin = await _scoped_admin(authorization, write=True)
    a = await db.advances.find_one({"advance_id": advance_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Advance not found")
    _check_scope(admin, a.get("company_id"))
    if float(a.get("recovered_total") or 0) > 0:
        raise HTTPException(
            status_code=400,
            detail="Recoveries already exist — advance cannot be deleted. Waive the balance instead.")
    await db.advance_transactions.delete_many({"advance_id": advance_id})
    await db.advances.delete_one({"advance_id": advance_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Employee self-service
# ---------------------------------------------------------------------------
@router.get("/me/advances")
async def my_advances(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    items = await db.advances.find(
        {"user_id": user["user_id"]}, {"_id": 0, "audit": 0}).sort("created_at", -1).to_list(100)
    tm = now_iso()[:7]
    out = []
    for a in items:
        a["status"] = _effective_status(a, tm)
        a["next_recovery_month"] = _next_recovery_month(a, tm)
        txns = await db.advance_transactions.find(
            {"advance_id": a["advance_id"]}, {"_id": 0}).sort("at", 1).to_list(200)
        a["transactions"] = txns
        a["schedule"] = _schedule(a, txns)
        out.append(a)
    summary = {
        "outstanding": round(sum(float(a.get("remaining_balance") or 0)
                                 for a in out if a["status"] not in ("closed", "waived")), 2),
        "recovered": round(sum(float(a.get("recovered_total") or 0) for a in out), 2),
        "active": sum(1 for a in out if a["status"] in ("active", "scheduled", "on_hold")),
    }
    return {"advances": out, "summary": summary}
