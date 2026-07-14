"""Deletion approvals (user directive).

Destructive actions by SUB ADMINS never run directly — they create a
``deletion_requests`` row that the SUPER ADMIN must approve:

  * kind "firm"            — force-delete of a company (cascade)
  * kind "salary_run"      — actual salary run
  * kind "compliance_run"  — compliance salary run

If the Super Admin REJECTS the request, nothing is deleted — the data keeps
showing exactly the same.

Endpoints:
  DELETE /api/admin/salary-runs/{run_id}              (actual run)
  DELETE /api/admin/compliance-salary-runs/{run_id}   (compliance run)
  GET    /api/admin/deletion-requests
  POST   /api/admin/deletion-requests/{request_id}/approve   (super admin)
  POST   /api/admin/deletion-requests/{request_id}/reject    (super admin)
"""
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    delete_company_cascade,
    logger,
)

router = APIRouter(prefix="/api/admin", tags=["deletion-approvals"])

_RUN_KINDS = {
    "salary_run": ("salary_runs", "Actual Salary Run"),
    "compliance_run": ("compliance_salary_runs", "Compliance Salary Run"),
}


async def _queue_request(user: Dict[str, Any], kind: str, target_id: str,
                         target_label: str, company_id: Optional[str],
                         force: bool = False) -> Dict[str, Any]:
    existing = await db.deletion_requests.find_one(
        {"kind": kind, "target_id": target_id, "status": "pending"},
        {"_id": 0, "request_id": 1})
    if existing:
        return {"ok": True, "approval_required": True, "request_id": existing["request_id"],
                "message": "A deletion request for this item is already pending Super Admin approval."}
    req_id = f"delreq_{uuid.uuid4().hex[:12]}"
    await db.deletion_requests.insert_one({
        "request_id": req_id,
        "kind": kind,
        "target_id": target_id,
        "target_label": target_label,
        "company_id": company_id,
        "force": force,
        "requested_by": user["user_id"],
        "requested_by_name": user.get("name") or user.get("email"),
        "requested_by_role": user["role"],
        "status": "pending",
        "requested_at": now_iso(),
    })
    logger.info("[deletion-request] %s %s queued by %s", kind, target_id, user["user_id"])
    return {"ok": True, "approval_required": True, "request_id": req_id,
            "message": ("Deletion sent to the Super Admin for approval — nothing is "
                        "deleted until approved. If rejected, the data stays unchanged.")}


async def _delete_run(kind: str, run_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    col, label = _RUN_KINDS[kind]
    run = await db[col].find_one({"run_id": run_id},
                                 {"_id": 0, "run_id": 1, "month": 1, "company_id": 1})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if user["role"] in ("company_admin",) and run.get("company_id") != user.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's salary run")

    target_label = f"{label} · {run.get('month') or ''}".strip()
    if user["role"] != "super_admin":
        # User directive — salary data deletion is SUBJECT TO SUPER ADMIN
        # approval for everyone except the super admin.
        return await _queue_request(user, kind, run_id, target_label, run.get("company_id"))

    await db[col].delete_one({"run_id": run_id})
    logger.info("[deletion] %s %s deleted directly by super admin %s", kind, run_id, user["user_id"])
    return {"ok": True, "deleted": True}


@router.delete("/salary-runs/{run_id}")
async def delete_salary_run(run_id: str, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    return await _delete_run("salary_run", run_id, user)


@router.delete("/compliance-salary-runs/{run_id}")
async def delete_compliance_run(run_id: str, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    return await _delete_run("compliance_run", run_id, user)


@router.get("/deletion-requests")
async def list_deletion_requests(
    status: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if user["role"] != "super_admin":
        q["requested_by"] = user["user_id"]  # requesters see their own
    items = await db.deletion_requests.find(q, {"_id": 0}).sort("requested_at", -1).to_list(100)
    pending = await db.deletion_requests.count_documents({"status": "pending"})
    return {"requests": items, "pending_count": pending}


@router.post("/deletion-requests/{request_id}/approve")
async def approve_deletion_request(
    request_id: str,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin"])
    req = await db.deletion_requests.find_one({"request_id": request_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"Request is already {req.get('status')}")

    kind = req.get("kind")
    result: Dict[str, Any] = {}
    if kind == "firm":
        company = await db.companies.find_one({"company_id": req["target_id"]}, {"_id": 0, "name": 1})
        if not company:
            result = {"note": "Firm no longer exists"}
        else:
            result = {"cascade": await delete_company_cascade(req["target_id"], bool(req.get("force")))}
    elif kind in _RUN_KINDS:
        col, _ = _RUN_KINDS[kind]
        r = await db[col].delete_one({"run_id": req["target_id"]})
        result = {"deleted_count": r.deleted_count}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown request kind '{kind}'")

    await db.deletion_requests.update_one(
        {"request_id": request_id},
        {"$set": {"status": "approved", "decided_by": user["user_id"],
                  "decided_by_name": user.get("name") or user.get("email"),
                  "decided_at": now_iso(), "result": result}},
    )
    logger.info("[deletion-request] %s APPROVED by %s -> %s", request_id, user["user_id"], result)
    return {"ok": True, "status": "approved", "result": result}


@router.post("/deletion-requests/{request_id}/reject")
async def reject_deletion_request(
    request_id: str,
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin"])
    req = await db.deletion_requests.find_one({"request_id": request_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"Request is already {req.get('status')}")
    await db.deletion_requests.update_one(
        {"request_id": request_id},
        {"$set": {"status": "rejected", "decided_by": user["user_id"],
                  "decided_by_name": user.get("name") or user.get("email"),
                  "decided_at": now_iso(),
                  "reject_reason": (payload.get("reason") or "").strip() or None}},
    )
    # Rejected — nothing was deleted; the data keeps showing the same.
    logger.info("[deletion-request] %s REJECTED by %s", request_id, user["user_id"])
    return {"ok": True, "status": "rejected",
            "message": "Request rejected — no data was deleted; everything stays the same."}
