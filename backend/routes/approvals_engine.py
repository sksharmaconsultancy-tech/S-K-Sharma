"""Approval Workflow Engine (RBAC Phase 3).

Configurable multi-level approval chains per company + module with an
Approval Inbox. Generic engine — first wired module: ADVANCE issuance.

Collections
-----------
approval_workflows:
  workflow_id, company_id, module, enabled,
  levels: [{level, approver_type: "company_admin"|"company_role",
            role_id?, role_name?}]

approval_requests:
  request_id, company_id, module, record_id, title, summary (dict),
  requested_by, requested_by_name, levels (snapshot), current_level,
  status: pending|approved|rejected|on_hold|returned,
  history: [{level, action, by, by_name, remarks, at}], created_at

Rules: maker-checker (requester cannot action own request); approver at
current level = real company_admin / super_admin / sub_admin OR staff
whose company_role matches the level's role_id.
"""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from pydantic import BaseModel

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    sub_admin_can_touch_company,
)

router = APIRouter(prefix="/api/admin", tags=["approval-engine"])

MODULES = [
    {"key": "advance", "label": "Advance Issuance"},
    {"key": "employee_creation", "label": "Employee Creation"},
    {"key": "salary_lock", "label": "Salary Lock"},
    {"key": "leave", "label": "Leave"},
]
MODULE_KEYS = {m["key"] for m in MODULES}


async def _admin_scoped(authorization, company_id: Optional[str]) -> tuple:
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    elif admin["role"] == "sub_admin" and company_id and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm outside your scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return admin, company_id


def _user_can_action_level(user: dict, level: Dict[str, Any]) -> bool:
    """Is this user an eligible approver for the given workflow level?"""
    if user.get("role") in ("super_admin", "sub_admin"):
        return True
    if user.get("role") == "company_admin" and not user.get("is_company_staff"):
        return True  # firm owner can act on any level
    if user.get("is_company_staff") and level.get("approver_type") == "company_role":
        return user.get("company_role_id") == level.get("role_id")
    return False


# ---------------------------------------------------------------------------
# Engine helpers (imported by feature modules e.g. routes/advances.py)
# ---------------------------------------------------------------------------
async def get_active_workflow(company_id: str, module: str) -> Optional[dict]:
    wf = await db.approval_workflows.find_one(
        {"company_id": company_id, "module": module, "enabled": True}, {"_id": 0})
    if wf and (wf.get("levels") or []):
        return wf
    return None


async def create_approval_request(
    company_id: str, module: str, record_id: str, title: str,
    summary: Dict[str, Any], requested_by: dict, workflow: dict,
) -> dict:
    req = {
        "request_id": f"apr_{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "module": module,
        "record_id": record_id,
        "title": title,
        "summary": summary,
        "requested_by": requested_by.get("user_id"),
        "requested_by_name": requested_by.get("name") or requested_by.get("email"),
        "levels": workflow.get("levels") or [],
        "current_level": 1,
        "status": "pending",
        "history": [{
            "level": 0, "action": "submitted",
            "by": requested_by.get("user_id"),
            "by_name": requested_by.get("name") or requested_by.get("email"),
            "remarks": None, "at": now_iso(),
        }],
        "created_at": now_iso(),
    }
    await db.approval_requests.insert_one(req)
    return {k: v for k, v in req.items() if k != "_id"}


async def _finalize(module: str, record_id: str, approved: bool, actor: dict):
    """Apply the final decision to the underlying record."""
    if module == "advance":
        from routes.advances import _audit as adv_audit  # local import, no cycle at module load
        a = await db.advances.find_one({"advance_id": record_id}, {"_id": 0})
        if not a:
            return
        if approved:
            new_status = "scheduled" if (a.get("start_month") or "") > now_iso()[:7] else "active"
            detail = "Advance APPROVED via workflow"
        else:
            new_status = "rejected"
            detail = "Advance REJECTED via workflow"
        await db.advances.update_one(
            {"advance_id": record_id},
            {"$set": {"status": new_status, "updated_at": now_iso()},
             "$push": {"audit": adv_audit(actor.get("user_id") or "system", "approval", detail)}},
        )


# ---------------------------------------------------------------------------
# Workflow builder
# ---------------------------------------------------------------------------
@router.get("/approval-workflows")
async def list_workflows(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin, cid = await _admin_scoped(authorization, company_id)
    if admin.get("is_company_staff"):
        raise HTTPException(status_code=403, detail="Staff accounts cannot manage workflows")
    wfs = await db.approval_workflows.find({"company_id": cid}, {"_id": 0}).to_list(50)
    by_mod = {w["module"]: w for w in wfs}
    roles = await db.company_roles.find({"company_id": cid}, {"_id": 0}).sort("name", 1).to_list(100)
    return {
        "modules": MODULES,
        "workflows": by_mod,
        "roles": [{"role_id": r["role_id"], "name": r["name"]} for r in roles],
    }


class WorkflowSave(BaseModel):
    company_id: Optional[str] = None
    module: str
    enabled: bool = True
    levels: List[Dict[str, Any]] = []


@router.post("/approval-workflows")
async def save_workflow(payload: WorkflowSave, authorization: Optional[str] = Header(None)):
    admin, cid = await _admin_scoped(authorization, payload.company_id)
    if admin.get("is_company_staff"):
        raise HTTPException(status_code=403, detail="Staff accounts cannot manage workflows")
    if payload.module not in MODULE_KEYS:
        raise HTTPException(status_code=400, detail=f"module must be one of {sorted(MODULE_KEYS)}")
    levels = []
    for i, lv in enumerate(payload.levels or [], start=1):
        atype = lv.get("approver_type")
        if atype not in ("company_admin", "company_role"):
            raise HTTPException(status_code=400, detail="approver_type must be company_admin|company_role")
        entry: Dict[str, Any] = {"level": i, "approver_type": atype}
        if atype == "company_role":
            role = await db.company_roles.find_one(
                {"role_id": lv.get("role_id"), "company_id": cid}, {"_id": 0})
            if not role:
                raise HTTPException(status_code=404, detail=f"Role not found for level {i}")
            entry["role_id"] = role["role_id"]
            entry["role_name"] = role["name"]
        levels.append(entry)
    doc = {
        "company_id": cid, "module": payload.module,
        "enabled": bool(payload.enabled) and len(levels) > 0,
        "levels": levels,
        "updated_at": now_iso(), "updated_by": admin["user_id"],
    }
    existing = await db.approval_workflows.find_one({"company_id": cid, "module": payload.module})
    if existing:
        await db.approval_workflows.update_one({"_id": existing["_id"]}, {"$set": doc})
        doc["workflow_id"] = existing.get("workflow_id")
    else:
        doc["workflow_id"] = f"wf_{uuid.uuid4().hex[:12]}"
        doc["created_at"] = now_iso()
        await db.approval_workflows.insert_one(dict(doc))
    return {"ok": True, "workflow": {k: v for k, v in doc.items() if k != "_id"}}


# ---------------------------------------------------------------------------
# Approval inbox
# ---------------------------------------------------------------------------
@router.get("/approval-inbox")
async def approval_inbox(
    company_id: Optional[str] = Query(None),
    status: str = Query("pending"),
    authorization: Optional[str] = Header(None),
):
    admin, cid = await _admin_scoped(authorization, company_id)
    q: Dict[str, Any] = {"company_id": cid}
    if status and status != "all":
        q["status"] = "pending" if status == "on_hold" else status
        if status == "on_hold":
            q["status"] = "on_hold"
    reqs = await db.approval_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    out = []
    for r in reqs:
        cur = next((l for l in r.get("levels") or [] if l.get("level") == r.get("current_level")), None)
        r["pending_with"] = (
            (cur or {}).get("role_name") or "Company Admin"
        ) if r.get("status") in ("pending", "on_hold") else None
        r["can_action"] = (
            r.get("status") in ("pending", "on_hold")
            and cur is not None
            and _user_can_action_level(admin, cur)
            and r.get("requested_by") != admin.get("user_id")  # maker-checker
        )
        out.append(r)
    counts = {
        "pending": await db.approval_requests.count_documents({"company_id": cid, "status": "pending"}),
        "on_hold": await db.approval_requests.count_documents({"company_id": cid, "status": "on_hold"}),
        "approved": await db.approval_requests.count_documents({"company_id": cid, "status": "approved"}),
        "rejected": await db.approval_requests.count_documents({"company_id": cid, "status": "rejected"}),
        "returned": await db.approval_requests.count_documents({"company_id": cid, "status": "returned"}),
    }
    return {"requests": out, "counts": counts}


@router.post("/approval-requests/{request_id}/action")
async def action_request(
    request_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    r = await db.approval_requests.find_one({"request_id": request_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    if admin["role"] == "company_admin" and admin.get("company_id") != r.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm")
    if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, r.get("company_id")):
        raise HTTPException(status_code=403, detail="Firm outside your scope")
    if r.get("status") not in ("pending", "on_hold"):
        raise HTTPException(status_code=400, detail="Request is already finalised")

    action = (payload.get("action") or "").strip()
    remarks = (payload.get("remarks") or "").strip() or None
    if action not in ("approve", "reject", "hold", "return"):
        raise HTTPException(status_code=400, detail="action must be approve|reject|hold|return")

    cur = next((l for l in r.get("levels") or [] if l.get("level") == r.get("current_level")), None)
    if not cur or not _user_can_action_level(admin, cur):
        raise HTTPException(status_code=403, detail="You are not the approver for the current level")
    if r.get("requested_by") == admin.get("user_id"):
        raise HTTPException(status_code=403, detail="Maker-checker: you cannot approve your own request")
    if action in ("reject", "return") and not remarks:
        raise HTTPException(status_code=400, detail="Remarks are mandatory to reject or return")

    hist = {
        "level": r["current_level"], "action": action,
        "by": admin["user_id"],
        "by_name": (admin.get("staff_role_name") + " · " if admin.get("is_company_staff") else "") + (admin.get("name") or admin.get("email") or ""),
        "remarks": remarks, "at": now_iso(),
    }
    updates: Dict[str, Any] = {}
    if action == "hold":
        updates["status"] = "on_hold"
    elif action == "return":
        updates["status"] = "returned"
    elif action == "reject":
        updates["status"] = "rejected"
    else:  # approve
        n_levels = len(r.get("levels") or [])
        if r["current_level"] >= n_levels:
            updates["status"] = "approved"
        else:
            updates["status"] = "pending"
            updates["current_level"] = r["current_level"] + 1
    updates["updated_at"] = now_iso()
    await db.approval_requests.update_one(
        {"request_id": request_id}, {"$set": updates, "$push": {"history": hist}})

    if updates.get("status") in ("approved", "rejected", "returned"):
        await _finalize(r["module"], r["record_id"],
                        approved=updates["status"] == "approved", actor=admin)

    fresh = await db.approval_requests.find_one({"request_id": request_id}, {"_id": 0})
    return {"ok": True, "request": fresh}
