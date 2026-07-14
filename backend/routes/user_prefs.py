"""Per-admin preferences — last selected firm.

Super admins and sub admins get their last selected firm restored
automatically after login (requested Iter 124). Stored on the user doc
as ``last_selected_company_id``.
"""
from typing import Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel

from server import db, get_user_from_token, require_role

router = APIRouter(prefix="/api")


class LastCompanyPayload(BaseModel):
    company_id: Optional[str] = None


@router.get("/me/last-company")
async def get_last_company(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    doc = await db.users.find_one(
        {"user_id": user["user_id"]}, {"_id": 0, "last_selected_company_id": 1}
    )
    return {"company_id": (doc or {}).get("last_selected_company_id")}


@router.patch("/me/last-company")
async def set_last_company(
    payload: LastCompanyPayload,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"last_selected_company_id": payload.company_id}},
    )
    return {"ok": True, "company_id": payload.company_id}
