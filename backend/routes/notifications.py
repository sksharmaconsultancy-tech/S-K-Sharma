"""Iter 86 - Route module: Notifications.

Two small endpoints extracted from `server.py`:
  * GET  /notifications   - Feed for the current user (role-scoped).
  * POST /notifications   - Admin broadcast (company-scoped for
                             company_admin, global for super_admin).
"""
import uuid
from datetime import datetime, timedelta, timezone
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


@router.get("/notifications/digest")
async def notifications_digest(authorization: Optional[str] = Header(None)):
    """Iter 669 — 'Yesterday at a glance' digest.

    Summarizes YESTERDAY's (IST calendar day) notification events for the
    current admin: total, counts by category, top highlights (critical >
    important > newest) and — for super admins — a per-firm breakdown.
    """
    user = await get_user_from_token(authorization)
    role = user["role"]
    cid = user.get("company_id")
    # Yesterday in IST (UTC+5:30) expressed as a UTC window.
    ist = timezone(timedelta(hours=5, minutes=30))
    today_ist = datetime.now(ist).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = (today_ist - timedelta(days=1)).astimezone(timezone.utc)
    end_utc = today_ist.astimezone(timezone.utc)
    q: dict = {"created_at": {"$gte": start_utc.isoformat(), "$lt": end_utc.isoformat()}}
    if role == "super_admin":
        pass  # all companies
    elif cid:
        q["$or"] = [{"company_id": None}, {"company_id": {"$exists": False}},
                    {"company_id": cid}]
    else:
        q["$or"] = [{"company_id": None}, {"company_id": {"$exists": False}}]
    notifs = await db.notifications.find(q, {"_id": 0, "read_by": 0}).sort(
        "created_at", -1).to_list(500)
    uid = user["user_id"]
    kept = []
    for n in notifs:
        aud = n.get("audience", "all")
        if (aud == "all"
                or (aud == "user" and n.get("target_user_id") == uid)
                or (aud == "admins" and role in ("company_admin", "super_admin"))
                or (aud == "super_admins" and role == "super_admin")):
            kept.append(n)
    by_category: dict = {}
    for n in kept:
        c = str(n.get("category") or "announcement")
        by_category[c] = by_category.get(c, 0) + 1
    prio_rank = {"critical": 0, "important": 1}
    newest_first = sorted(kept, key=lambda n: n.get("created_at") or "", reverse=True)
    highlights = sorted(
        newest_first,
        key=lambda n: prio_rank.get(str(n.get("priority") or "normal"), 2),
    )[:5]
    per_firm = []
    if role == "super_admin":
        firm_counts: dict = {}
        for n in kept:
            fc = n.get("company_id")
            if fc:
                firm_counts[fc] = firm_counts.get(fc, 0) + 1
        if firm_counts:
            comps = await db.companies.find(
                {"company_id": {"$in": list(firm_counts)}},
                {"_id": 0, "company_id": 1, "name": 1}).to_list(100)
            names = {c["company_id"]: c.get("name") or c["company_id"] for c in comps}
            per_firm = sorted(
                [{"company_id": k, "name": names.get(k, k), "count": v}
                 for k, v in firm_counts.items()],
                key=lambda x: -x["count"])
    return {
        "date_label": (today_ist - timedelta(days=1)).strftime("%d %b %Y"),
        "total": len(kept),
        "by_category": by_category,
        "highlights": highlights,
        "per_firm": per_firm,
    }


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
