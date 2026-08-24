"""Iter 707 — Employee PWA Pending Approval Center.

One aggregation endpoint that collects the employee's OWN requests from
every module — the common approval engine (approval_requests) PLUS the
native module collections (leaves, expense_claims, advances, tour_requests)
— and normalises them into one card format with level progress, current
approver, history timeline and status. Employees only ever see their own
requests; no approval action is possible from here.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header

from server import db, get_user_from_token  # noqa: E402

router = APIRouter(prefix="/api/my-approvals", tags=["my-approvals"])

MODULE_LABELS = {
    "advance": "Advance Issuance", "employee_creation": "Employee Onboarding",
    "salary_lock": "Salary Lock", "leave": "Leave Request",
    "shift_change": "Shift Change", "overtime": "Overtime",
    "loan": "Loan", "salary_revision": "Salary Revision",
    "exit": "Exit / Full & Final", "tour": "Official Tour",
}
PENDING = ("pending", "on_hold", "submitted", "pending_approval",
           "pending_manager", "pending_accounts", "pending_finance")

# Native expense stages → level display (Manager → Accounts → Finance).
_EXP_STAGE = {"submitted": (1, "Manager"), "pending_manager": (1, "Manager"),
              "pending_accounts": (2, "Accounts"), "pending_finance": (3, "Finance")}


def _norm_status(s: str) -> str:
    s = (s or "").lower()
    if s in ("pending", "submitted", "pending_approval", "pending_manager",
             "pending_accounts", "pending_finance", "scheduled"):
        return "pending"
    if s == "on_hold":
        return "under_review"
    if s in ("approved", "active", "completed", "paid", "payment_pending",
             "processing"):
        return "approved"
    if s == "rejected":
        return "rejected"
    if s == "returned":
        return "returned"
    if s == "cancelled":
        return "cancelled"
    return s or "pending"


def _eng_levels(req: dict) -> Dict[str, Any]:
    levels = req.get("levels") or []
    cur = int(req.get("current_level") or 1)
    total = len(levels) or 1
    pending_with = None
    if req.get("status") in ("pending", "on_hold") and levels:
        lv = levels[min(cur, total) - 1]
        pending_with = lv.get("role_name") or ("Company Admin"
                                               if lv.get("approver_type") == "company_admin" else "Approver")
    steps = []
    for lv in levels:
        n = int(lv.get("level") or 0)
        nm = lv.get("role_name") or ("Company Admin" if lv.get("approver_type") == "company_admin" else f"Level {n}")
        st = "done" if n < cur or req.get("status") == "approved" else (
            "current" if n == cur and req.get("status") in ("pending", "on_hold") else "todo")
        if req.get("status") in ("rejected", "returned") and n == cur:
            st = req["status"]
        steps.append({"level": n, "name": nm, "state": st})
    return {"level_current": min(cur, total), "level_total": total,
            "pending_with": pending_with, "steps": steps}


def _hist(entries: list, by_key="by_name", act_key="action",
          at_key="at", rm_key="remarks") -> List[dict]:
    out = []
    for h in entries or []:
        out.append({"action": h.get(act_key), "by": h.get(by_key),
                    "at": h.get(at_key), "remarks": h.get(rm_key),
                    "level": h.get("level")})
    return out


@router.get("")
async def my_approvals(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    me = user["user_id"]
    items: List[dict] = []
    by_record: Dict[str, dict] = {}

    # 1) Engine requests (source of truth for level info).
    eng: Dict[str, dict] = {}
    async for r in db.approval_requests.find(
            {"requested_by": me}, {"_id": 0}).sort("created_at", -1).limit(300):
        eng[r.get("record_id")] = r

    # 2) Leaves.
    async for lv in db.leaves.find({"user_id": me}, {"_id": 0}).sort("created_at", -1).limit(100):
        it = {"type": "Leave Request", "type_key": "leave", "icon": "calendar-outline",
              "ref": f"LV-{(lv.get('leave_id') or '')[-6:].upper()}",
              "record_id": lv.get("leave_id"),
              "submitted_at": lv.get("created_at"),
              "from_date": lv.get("from_date"), "to_date": lv.get("to_date"),
              "amount": None, "detail": f"{lv.get('leave_type') or 'Leave'} · {lv.get('reason') or ''}".strip(" ·"),
              "status": _norm_status(lv.get("status")),
              "raw_status": lv.get("status"),
              "last_action_at": lv.get("decided_at") or lv.get("created_at"),
              "level_current": 1, "level_total": 1, "pending_with": "Admin / HR",
              "steps": [], "history": [], "remarks": lv.get("admin_note") or lv.get("decision_note"),
              "edit_route": None}
        by_record[it["record_id"]] = it
        items.append(it)

    # 3) Expense claims.
    async for c in db.expense_claims.find(
            {"user_id": me, "status": {"$ne": "draft"}},
            {"_id": 0, "attachments": 0}).sort("created_at", -1).limit(150):
        stage = _EXP_STAGE.get(c.get("status"))
        it = {"type": "Expense Claim", "type_key": "expense", "icon": "receipt-outline",
              "ref": c.get("claim_no") or c.get("claim_id"),
              "record_id": c.get("claim_id"),
              "submitted_at": c.get("submitted_at") or c.get("created_at"),
              "from_date": c.get("expense_date"), "to_date": None,
              "amount": c.get("amount"),
              "detail": f"{c.get('category_name') or ''} {('· ' + (c.get('tour') or {}).get('tour_no')) if c.get('tour_id') else ''}".strip(),
              "status": _norm_status(c.get("status")), "raw_status": c.get("status"),
              "last_action_at": c.get("updated_at") or c.get("created_at"),
              "level_current": stage[0] if stage else 3, "level_total": 3,
              "pending_with": stage[1] if stage else None,
              "steps": [{"level": i + 1, "name": nm,
                         "state": "current" if stage and stage[0] == i + 1 else
                         ("done" if (not stage and _norm_status(c.get("status")) == "approved")
                          or (stage and i + 1 < stage[0]) else "todo")}
                        for i, nm in enumerate(("Manager", "Accounts", "Finance"))],
              "history": _hist(c.get("approvals") or [], by_key="by_name"),
              "remarks": c.get("return_reason") or c.get("reject_reason"),
              "edit_route": f"/expense-claim-form?claim_id={c.get('claim_id')}"
              if c.get("status") == "returned" else None}
        by_record[it["record_id"]] = it
        items.append(it)

    # 4) Advances.
    async for a in db.advances.find({"user_id": me}, {"_id": 0, "audit": 0}
                                    ).sort("created_at", -1).limit(100):
        it = {"type": "Advance Request", "type_key": "advance", "icon": "wallet-outline",
              "ref": a.get("voucher_no") or f"ADV-{(a.get('advance_id') or '')[-6:].upper()}",
              "record_id": a.get("advance_id"),
              "submitted_at": a.get("created_at"),
              "from_date": a.get("advance_date"), "to_date": None,
              "amount": a.get("amount"),
              "detail": a.get("purpose") or a.get("advance_type") or "",
              "status": _norm_status(a.get("status")), "raw_status": a.get("status"),
              "last_action_at": a.get("updated_at") or a.get("created_at"),
              "level_current": 1, "level_total": 1, "pending_with": "Admin / Accounts",
              "steps": [], "history": [], "remarks": a.get("reject_reason"),
              "edit_route": None}
        by_record[it["record_id"]] = it
        items.append(it)

    # 5) Tours.
    async for t in db.tour_requests.find(
            {"user_id": me, "status": {"$ne": "draft"}},
            {"_id": 0, "attachments": 0}).sort("created_at", -1).limit(100):
        it = {"type": "Official Tour", "type_key": "tour", "icon": "airplane-outline",
              "ref": t.get("tour_no"), "record_id": t.get("tour_id"),
              "submitted_at": t.get("submitted_at") or t.get("created_at"),
              "from_date": t.get("start_date"), "to_date": t.get("end_date"),
              "amount": t.get("total_estimated"),
              "detail": f"{t.get('tour_type')} · {', '.join(t.get('destinations') or [])}",
              "status": _norm_status(t.get("status")), "raw_status": t.get("status"),
              "last_action_at": t.get("updated_at") or t.get("created_at"),
              "level_current": 1, "level_total": 1, "pending_with": "Admin",
              "steps": [], "history": _hist(t.get("approval_history") or []),
              "remarks": None,
              "edit_route": f"/tour-request?id={t.get('tour_id')}"
              if t.get("status") == "returned" else None,
              "view_route": f"/tour-detail?id={t.get('tour_id')}"}
        by_record[it["record_id"]] = it
        items.append(it)

    # 6) Merge engine level data into native items; engine-only modules
    #    become their own cards.
    covered = set()
    for rid, req in eng.items():
        lvl = _eng_levels(req)
        hist = _hist(req.get("history") or [])
        if rid in by_record:
            it = by_record[rid]
            it.update(lvl)
            if hist:
                it["history"] = hist
            covered.add(rid)
        else:
            items.append({
                "type": MODULE_LABELS.get(req.get("module"), req.get("module")),
                "type_key": req.get("module"), "icon": "git-branch-outline",
                "ref": req.get("title") or req.get("request_id"),
                "record_id": rid, "submitted_at": req.get("created_at"),
                "from_date": None, "to_date": None,
                "amount": (req.get("summary") or {}).get("amount"),
                "detail": req.get("title") or "",
                "status": _norm_status(req.get("status")),
                "raw_status": req.get("status"),
                "last_action_at": req.get("updated_at") or req.get("created_at"),
                **lvl, "history": hist, "remarks": None, "edit_route": None})

    items.sort(key=lambda x: str(x.get("submitted_at") or ""), reverse=True)
    counts: Dict[str, int] = {"pending": 0, "under_review": 0, "approved": 0,
                              "rejected": 0, "returned": 0, "cancelled": 0}
    by_type: Dict[str, int] = {}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
        if it["status"] in ("pending", "under_review"):
            by_type[it["type"]] = by_type.get(it["type"], 0) + 1
    return {"items": items[:300], "counts": counts,
            "pending_total": counts["pending"] + counts["under_review"],
            "pending_by_type": [{"type": k, "count": v}
                                for k, v in sorted(by_type.items())]}


@router.get("/summary")
async def my_approvals_summary(authorization: Optional[str] = Header(None)):
    """Light dashboard-card counts (no item payload)."""
    user = await get_user_from_token(authorization)
    me = user["user_id"]
    by_type: Dict[str, int] = {}
    n = await db.leaves.count_documents({"user_id": me, "status": "pending"})
    if n:
        by_type["Leave"] = n
    n = await db.expense_claims.count_documents(
        {"user_id": me, "status": {"$in": ["submitted", "pending_manager",
                                           "pending_accounts", "pending_finance"]}})
    if n:
        by_type["Expense"] = n
    n = await db.tour_requests.count_documents(
        {"user_id": me, "status": {"$in": ["submitted", "pending_approval"]}})
    if n:
        by_type["Tour"] = n
    n = await db.advances.count_documents({"user_id": me, "status": "pending"})
    if n:
        by_type["Advance"] = n
    # Engine-only pending (modules without a native card above).
    n = await db.approval_requests.count_documents(
        {"requested_by": me, "status": {"$in": ["pending", "on_hold"]},
         "module": {"$nin": ["leave", "tour", "advance"]}})
    if n:
        by_type["Other"] = by_type.get("Other", 0) + n
    return {"pending_total": sum(by_type.values()),
            "pending_by_type": [{"type": k, "count": v} for k, v in by_type.items()]}
