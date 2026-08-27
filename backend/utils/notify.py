"""Iter 666 — notification emit helper (additive layer over existing events).

Never raises: any failure is swallowed so business flows are untouched.
Categories: attendance · leave · salary · compliance · expense · employee ·
import · system · announcement.  Priorities: normal · important · critical.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional


async def emit(db, *, title: str, message: str,
               audience: str = "admins",
               company_id: Optional[str] = None,
               category: str = "system",
               priority: str = "normal",
               action_url: Optional[str] = None,
               reference_id: Optional[str] = None,
               target_user_id: Optional[str] = None,
               actor_name: Optional[str] = None,
               subject_name: Optional[str] = None) -> None:
    try:
        # Iter 753 (user request) — har popup par FIRM ka naam bhi jaye.
        firm_name = None
        if company_id:
            try:
                _co = await db.companies.find_one(
                    {"company_id": company_id}, {"_id": 0, "name": 1})
                firm_name = (_co or {}).get("name")
            except Exception:
                firm_name = None
        await db.notifications.insert_one({
            "notification_id": f"n_{uuid.uuid4().hex[:10]}",
            "title": str(title)[:120],
            "body": str(message)[:400],
            "audience": audience,
            "company_id": company_id,
            "firm_name": firm_name,
            # Iter 753 — kisne kaam kiya + kiski details change/add hui.
            "actor_name": (str(actor_name)[:80] if actor_name else None),
            "subject_name": (str(subject_name)[:80] if subject_name else None),
            "target_user_id": target_user_id,
            "category": category,
            "priority": priority,
            "action_url": action_url,
            "reference_id": reference_id,
            "read_by": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass
