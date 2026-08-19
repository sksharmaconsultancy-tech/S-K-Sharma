"""Iter 86 - Route module: Compliance documents.

Endpoints:
  * GET  /compliance-docs   - List all compliance documents.
  * POST /compliance-docs   - Create/upload a compliance document.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    ComplianceDocCreate,
)

router = APIRouter(prefix="/api", tags=["compliance-docs"])


@router.get("/compliance-docs")
async def list_docs(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    docs = await db.compliance_docs.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    # Iter 615 (ESS Phase 2) — per-user acknowledgement flags.
    for d in docs:
        acks = d.pop("acknowledgements", None) or []
        mine = next((a for a in acks if a.get("user_id") == user["user_id"]), None)
        d["ack_count"] = len(acks)
        d["acknowledged_by_me"] = bool(mine)
        d["acknowledged_at"] = (mine or {}).get("at")
    return {"docs": docs}


@router.post("/compliance-docs/{doc_id}/acknowledge")
async def acknowledge_doc(doc_id: str, authorization: Optional[str] = Header(None)):
    """Iter 615 (ESS Phase 2) — employee acknowledges reading a published
    company document. Idempotent per user."""
    user = await get_user_from_token(authorization)
    doc = await db.compliance_docs.find_one(
        {"doc_id": doc_id}, {"_id": 0, "doc_id": 1, "acknowledgements": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    mine = next((a for a in (doc.get("acknowledgements") or [])
                 if a.get("user_id") == user["user_id"]), None)
    if mine:
        return {"ok": True, "acknowledged_at": mine.get("at"), "already": True}
    at = now_iso()
    await db.compliance_docs.update_one(
        {"doc_id": doc_id},
        {"$push": {"acknowledgements": {
            "user_id": user["user_id"],
            "name": user.get("name") or user.get("email"),
            "employee_code": user.get("employee_code"),
            "at": at,
        }}})
    return {"ok": True, "acknowledged_at": at}


@router.post("/compliance-docs")
async def create_doc(payload: ComplianceDocCreate, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    doc = payload.model_dump()
    doc["doc_id"] = f"doc_{uuid.uuid4().hex[:10]}"
    doc["created_at"] = now_iso()
    doc["created_by"] = user["user_id"]
    await db.compliance_docs.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}
