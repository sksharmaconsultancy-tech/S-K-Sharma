"""Iter 86 - Route module: Notifications.

Two small endpoints extracted from `server.py`:
  * GET  /notifications   - Feed for the current user (role-scoped).
  * POST /notifications   - Admin broadcast (company-scoped for
                             company_admin, global for super_admin).
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Header

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    NotificationCreate,
)

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/notifications")
async def list_notifications(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    role = user["role"]
    cid = user.get("company_id")
    # Fetch global notifications (company_id=None) + user's own company notifications
    q = {"$or": [{"company_id": None}, {"company_id": {"$exists": False}}]}
    if cid:
        q = {"$or": [{"company_id": None}, {"company_id": {"$exists": False}}, {"company_id": cid}]}
    notifs = await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    out = []
    for n in notifs:
        aud = n.get("audience", "all")
        if aud == "all":
            out.append(n)
        elif aud == "employees" and role == "employee":
            out.append(n)
        elif aud == "user" and n.get("target_user_id") == user["user_id"]:
            # Iter 99 — personal notifications (e.g. own punch in/out).
            out.append(n)
        elif aud == "admins" and role in ("company_admin", "super_admin"):
            out.append(n)
        elif aud == "super_admins" and role == "super_admin":
            out.append(n)
    return {"notifications": out}


@router.post("/notifications")
async def create_notification(payload: NotificationCreate,
                              authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    n = payload.model_dump()
    # Company admins can only broadcast within their own company
    if user["role"] == "company_admin":
        n["company_id"] = user.get("company_id")
    n["notification_id"] = f"n_{uuid.uuid4().hex[:10]}"
    n["created_at"] = now_iso()
    n["created_by"] = user["name"]
    await db.notifications.insert_one(n)
    return {k: v for k, v in n.items() if k != "_id"}
