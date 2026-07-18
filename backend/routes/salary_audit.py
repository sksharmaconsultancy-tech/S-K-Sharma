"""Iter 182 — Salary Process audit log.

Every Compliance Salary action (process, save draft, finalize, unlock)
writes an entry to ``salary_audit_log``; this router exposes the feed
for the premium Salary Process screens.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, Query

from server import db, get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api/admin", tags=["salary-audit"])

IST = timezone(timedelta(hours=5, minutes=30))


async def write_salary_audit(admin: dict, action: str, run: Optional[dict] = None,
                             detail: str = "", extra: Optional[Dict[str, Any]] = None):
    """Fire-and-forget audit entry (never raises)."""
    try:
        run = run or {}
        await db.salary_audit_log.insert_one({
            "audit_id": f"aud_{uuid.uuid4().hex[:12]}",
            "action": action,                       # process | save_rows | finalize | unlock | ...
            "run_id": run.get("run_id"),
            "company_id": run.get("company_id"),
            "company_name": run.get("company_name"),
            "month": run.get("month"),
            "actor_id": admin.get("user_id"),
            "actor_name": admin.get("name"),
            "actor_role": admin.get("role"),
            "detail": detail,
            **(extra or {}),
            "at": datetime.now(IST).isoformat(),
        })
    except Exception:
        pass


@router.get("/salary-audit-log")
async def list_salary_audit(
    company_id: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    q: Dict[str, Any] = {}
    if admin.get("role") == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif company_id:
        q["company_id"] = company_id
    if month:
        q["month"] = month
    if run_id:
        q["run_id"] = run_id
    entries = await db.salary_audit_log.find(q, {"_id": 0}).sort("at", -1).to_list(limit)
    return {"entries": entries}
