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
    if role == "super_admin":
        # Iter 666 — super admins see notifications across ALL companies.
        q = {}
    elif cid:
        q = {"$or": [{"company_id": None}, {"company_id": {"$exists": False}}, {"company_id": cid}]}
    notifs = await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    out = []
    uid = user["user_id"]
    for n in notifs:
        aud = n.get("audience", "all")
        keep = (
            aud == "all"
            or (aud == "employees" and role == "employee")
            or (aud == "user" and n.get("target_user_id") == uid)
            or (aud == "admins" and role in ("company_admin", "super_admin"))
            or (aud == "super_admins" and role == "super_admin")
        )
        if not keep:
            continue
        # Iter 666 — per-user read state (server-side).
        n["read"] = uid in (n.get("read_by") or [])
        n.pop("read_by", None)
        out.append(n)
    return {"notifications": out}


@router.post("/notifications/mark-read")
async def mark_notifications_read(payload: dict = None,
                                  authorization: Optional[str] = Header(None)):
    """Iter 666 — mark specific ids (or all) as READ for the current user."""
    user = await get_user_from_token(authorization)
    payload = payload or {}
    uid = user["user_id"]
    ids = payload.get("ids") or []
    if payload.get("all"):
        await db.notifications.update_many({}, {"$addToSet": {"read_by": uid}})
    elif ids:
        await db.notifications.update_many(
            {"notification_id": {"$in": [str(i) for i in ids]}},
            {"$addToSet": {"read_by": uid}})
    return {"ok": True}


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
