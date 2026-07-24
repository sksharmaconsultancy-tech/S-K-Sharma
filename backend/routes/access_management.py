"""Iter 286 — Access & Workflow Management (Phase A).

Unified module merging Roles & Permissions + Workflow Builder behind a
single dashboard. Engines stay separate (routes/company_roles.py for
RBAC, routes/approvals_engine.py for workflows) — this module adds the
overview stats + a shared ``access_audit`` trail.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException

from server import db, get_user_from_token, require_role, now_iso, sub_admin_can_touch_company  # noqa: E402

router = APIRouter(prefix="/api", tags=["access-management"])


async def write_access_audit(admin: dict, company_id: Optional[str], action: str,
                             detail: str, extra: Optional[Dict[str, Any]] = None) -> None:
    """Shared audit writer used by company_roles + approvals_engine."""
    try:
        await db.access_audit.insert_one({
            "audit_id": f"acc_{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "action": action,          # role_created / role_updated / ...
            "detail": detail,
            "extra": extra or {},
            "by": (admin or {}).get("user_id"),
            "by_name": (admin or {}).get("name"),
            "by_role": (admin or {}).get("role"),
            "at": now_iso(),
        })
    except Exception:  # audit must never break the main action
        pass


async def _scoped(authorization, company_id: Optional[str]):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin.get("is_company_staff"):
        raise HTTPException(status_code=403, detail="Staff accounts cannot open Access Management")
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    elif admin["role"] == "sub_admin" and company_id and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm outside your scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return admin, company_id


@router.get("/admin/access-management/stats")
async def access_stats(company_id: Optional[str] = None,
                       authorization: Optional[str] = Header(None)):
    _admin, cid = await _scoped(authorization, company_id)
    roles = await db.company_roles.count_documents({"company_id": cid})
    staff = await db.users.count_documents({
        "company_id": cid,
        "$or": [{"role": "company_staff"}, {"role": "employee", "is_company_staff": True}],
    })
    employees = await db.users.count_documents({"company_id": cid, "role": "employee"})
    wf_total = await db.approval_workflows.count_documents({"company_id": cid})
    wf_active = await db.approval_workflows.count_documents({"company_id": cid, "enabled": True})
    pending = await db.approval_requests.count_documents({"company_id": cid, "status": "pending"})
    approved = await db.approval_requests.count_documents({"company_id": cid, "status": "approved"})
    rejected = await db.approval_requests.count_documents({"company_id": cid, "status": "rejected"})
    onboarding_pending = await db.users.count_documents(
        {"company_id": cid, "role": "employee", "onboarding_status": "pending_approval"})
    recent_wf = await db.approval_workflows.find(
        {"company_id": cid}, {"_id": 0, "module": 1, "enabled": 1, "levels": 1,
                              "updated_at": 1, "created_at": 1},
    ).sort("updated_at", -1).to_list(5)
    recent_audit = await db.access_audit.find(
        {"company_id": cid}, {"_id": 0}).sort("at", -1).to_list(8)
    return {
        "company_id": cid,
        "totals": {
            "roles": roles, "staff_users": staff, "employees": employees,
            "workflows": wf_total, "active_workflows": wf_active,
            "pending_approvals": pending, "approved_requests": approved,
            "rejected_requests": rejected,
            "pending_onboarding": onboarding_pending,
        },
        "recent_workflows": [
            {"module": w.get("module"), "enabled": w.get("enabled"),
             "levels": len(w.get("levels") or []),
             "updated_at": w.get("updated_at") or w.get("created_at")}
            for w in recent_wf
        ],
        "recent_audit": recent_audit,
    }


@router.get("/admin/access-management/activity")
async def access_activity(company_id: Optional[str] = None,
                          authorization: Optional[str] = Header(None)):
    """Phase C — Live Activity Monitor. Sliding 12h sessions mean
    last-activity ≈ expires_at − 12h (throttled ±30 min), so 'online' =
    expiry within the last 45 minutes of a fresh extension."""
    _admin, cid = await _scoped(authorization, company_id)
    now = datetime.now(timezone.utc)
    online_cut = now + timedelta(hours=12) - timedelta(minutes=45)
    firm_uids = [u["user_id"] async for u in db.users.find(
        {"company_id": cid}, {"_id": 0, "user_id": 1})]
    sess = await db.user_sessions.find(
        {"user_id": {"$in": firm_uids}, "expires_at": {"$gt": online_cut}},
        {"_id": 0, "user_id": 1, "expires_at": 1},
    ).to_list(300)
    seen: Dict[str, Any] = {}
    for s in sess:
        prev = seen.get(s["user_id"])
        if not prev or s["expires_at"] > prev:
            seen[s["user_id"]] = s["expires_at"]
    users = []
    if seen:
        async for u in db.users.find(
                {"user_id": {"$in": list(seen.keys())}},
                {"_id": 0, "user_id": 1, "name": 1, "role": 1,
                 "employee_code": 1, "is_company_staff": 1}):
            exp = seen[u["user_id"]]
            if hasattr(exp, "tzinfo") and exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            last_active = exp - timedelta(hours=12)
            users.append({**u, "last_active": last_active.isoformat()})
        users.sort(key=lambda x: x["last_active"], reverse=True)
    pending = await db.approval_requests.count_documents({"company_id": cid, "status": "pending"})
    escalated = await db.approval_requests.count_documents(
        {"company_id": cid, "status": "pending", "escalated": True})
    breached = await db.approval_requests.count_documents(
        {"company_id": cid, "status": "pending", "sla_breached": True})
    running = await db.approval_workflows.count_documents({"company_id": cid, "enabled": True})
    recent_perm = await db.access_audit.find(
        {"company_id": cid}, {"_id": 0}).sort("at", -1).to_list(5)
    return {
        "online_users": users[:50],
        "online_count": len(users),
        "pending_approvals": pending,
        "escalated_pending": escalated,
        "sla_breached_pending": breached,
        "running_workflows": running,
        "recent_permission_changes": recent_perm,
        "as_of": now.isoformat(),
    }


@router.get("/admin/access-management/audit")
async def access_audit_log(company_id: Optional[str] = None,
                           authorization: Optional[str] = Header(None)):
    _admin, cid = await _scoped(authorization, company_id)
    acc = await db.access_audit.find({"company_id": cid}, {"_id": 0}).sort("at", -1).to_list(150)
    ob = await db.onboarding_audit.find({"company_id": cid}, {"_id": 0}).sort("at", -1).to_list(100)
    merged = [{**a, "source": "access"} for a in acc] + [
        {"audit_id": o.get("audit_id"), "company_id": o.get("company_id"),
         "action": f"onboarding_{o.get('action')}",
         "detail": (f"{o.get('employee_name') or ''} "
                    f"({o.get('employee_code') or '—'}) → {o.get('new_status') or ''}"
                    + (f" · {o.get('remarks')}" if o.get("remarks") else "")).strip(),
         "by": o.get("by"), "by_name": o.get("by_name"), "by_role": o.get("by_role"),
         "at": o.get("at"), "source": "onboarding"}
        for o in ob
    ]
    merged.sort(key=lambda x: x.get("at") or "", reverse=True)
    return {"logs": merged[:200]}
