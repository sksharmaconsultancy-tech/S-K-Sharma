"""Iter 86 - Route module: Compliance documents.

Endpoints:
  * GET  /compliance-docs   - List all compliance documents.
  * POST /compliance-docs   - Create/upload a compliance document.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Header

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
    await get_user_from_token(authorization)
    docs = await db.compliance_docs.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"docs": docs}


@router.post("/compliance-docs")
async def create_doc(payload: ComplianceDocCreate, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin"])
    doc = payload.model_dump()
    doc["doc_id"] = f"doc_{uuid.uuid4().hex[:10]}"
    doc["created_at"] = now_iso()
    doc["created_by"] = user["user_id"]
    await db.compliance_docs.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}
