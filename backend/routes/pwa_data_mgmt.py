"""Iter 708 — Firm-wise PWA Attendance Data Auto-Delete & Screenshot
Protection.

STRICT SEPARATION: this is a PWA data LIFECYCLE mechanism, never a database
deletion mechanism. The "wipe" only sets a per-firm visibility cutoff
(`pwa_settings.attendance_hidden_before`) that the EMPLOYEE self-service
attendance endpoints respect. Admin/Employer endpoints, payroll, compliance,
reports, audit and the attendance collection itself are NEVER touched.

Settings live in firm_masters.pwa_settings:
  attendance_autodelete (bool) · autodelete_day (1-28, default 5) ·
  screenshot_protection (bool) · attendance_hidden_before (YYYY-MM-DD) ·
  last_auto_wipe_month (YYYY-MM).
Audit: db.pwa_wipe_audit (immutable via API — no edit/delete endpoints).
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import db, get_user_from_token, require_role, now_iso  # noqa: E402

router = APIRouter(prefix="/api", tags=["pwa-data-mgmt"])

ADMIN_ROLES = ["super_admin", "sub_admin", "company_admin"]
DEFAULTS = {"attendance_autodelete": False, "autodelete_day": 5,
            "screenshot_protection": False, "attendance_hidden_before": None,
            "last_auto_wipe_month": None}


async def get_pwa_settings(company_id: str) -> dict:
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "pwa_settings": 1}) or {}
    return {**DEFAULTS, **(fm.get("pwa_settings") or {})}


async def get_hidden_before(company_id: Optional[str]) -> Optional[str]:
    """Visibility cutoff used by employee self-service attendance endpoints."""
    if not company_id:
        return None
    s = await get_pwa_settings(company_id)
    return s.get("attendance_hidden_before") or None


async def _execute_wipe(company_id: str, trigger: str, actor: Optional[dict]) -> dict:
    """Idempotent PWA-side wipe of the PREVIOUS calendar month:
    sets the visibility cutoff to the 1st of the CURRENT month."""
    today = datetime.now(timezone.utc).date()
    cutoff = today.replace(day=1).isoformat()
    prev_month = (today.replace(day=1).replace(
        year=today.year - 1, month=12) if today.month == 1
        else today.replace(day=1).replace(month=today.month - 1))
    month_cleared = prev_month.strftime("%Y-%m")
    s = await get_pwa_settings(company_id)
    already = (s.get("attendance_hidden_before") or "") >= cutoff
    # Count of PWA records now hidden (records are PRESERVED in the DB).
    affected = await db.attendance.count_documents(
        {"company_id": company_id,
         "date": {"$gte": f"{month_cleared}-01", "$lt": cutoff}})
    if not already:
        await db.firm_masters.update_one(
            {"company_id": company_id},
            {"$set": {"pwa_settings.attendance_hidden_before": cutoff,
                      **({"pwa_settings.last_auto_wipe_month":
                          today.strftime("%Y-%m")} if trigger == "AUTO" else {})}},
            upsert=True)
    elif trigger == "AUTO":
        await db.firm_masters.update_one(
            {"company_id": company_id},
            {"$set": {"pwa_settings.last_auto_wipe_month": today.strftime("%Y-%m")}},
            upsert=True)
    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "name": 1}) or {}
    entry = {
        "audit_id": f"pwaw_{uuid.uuid4().hex[:12]}",
        "company_id": company_id, "company_name": company.get("name"),
        "month_cleared": month_cleared,
        "autodelete_day": s.get("autodelete_day"),
        "executed_at": now_iso(), "trigger": trigger,
        "by": (actor or {}).get("user_id") or "system",
        "by_name": (actor or {}).get("name") or "System Scheduler",
        "affected_pwa_records": affected,
        "status": "already_applied" if already else "executed",
        "note": "PWA visibility cutoff only — database records preserved.",
    }
    await db.pwa_wipe_audit.insert_one(dict(entry))
    entry.pop("_id", None)
    return entry


async def run_autodelete_check(company_id: Optional[str]) -> None:
    """Lazy scheduler — called from the employee pwa-policy endpoint.
    Executes the AUTO wipe once per month on/after the configured day."""
    if not company_id:
        return
    s = await get_pwa_settings(company_id)
    if not s.get("attendance_autodelete"):
        return
    today = datetime.now(timezone.utc).date()
    if today.day < int(s.get("autodelete_day") or 5):
        return
    if s.get("last_auto_wipe_month") == today.strftime("%Y-%m"):
        return
    await _execute_wipe(company_id, "AUTO", None)


def _admin_cid(user: dict, company_id: Optional[str]) -> str:
    cid = user.get("company_id") if user.get("role") == "company_admin" \
        else (company_id or user.get("company_id"))
    if not cid:
        raise HTTPException(status_code=400, detail="company_id is required")
    return cid


@router.get("/admin/pwa-settings")
async def read_pwa_settings(company_id: Optional[str] = Query(None),
                            authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ADMIN_ROLES)
    cid = _admin_cid(admin, company_id)
    audit = await db.pwa_wipe_audit.find(
        {"company_id": cid}, {"_id": 0}).sort("executed_at", -1).to_list(20)
    return {"company_id": cid, "settings": await get_pwa_settings(cid),
            "audit": audit}


@router.post("/admin/pwa-settings")
async def save_pwa_settings(payload: Dict[str, Any] = Body(...),
                            authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ADMIN_ROLES)
    cid = _admin_cid(admin, payload.get("company_id"))
    sets: Dict[str, Any] = {}
    for k in ("attendance_autodelete", "screenshot_protection"):
        if k in payload:
            sets[f"pwa_settings.{k}"] = bool(payload[k])
    if "autodelete_day" in payload:
        try:
            d = int(payload["autodelete_day"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="autodelete_day must be a number")
        if not 1 <= d <= 28:
            raise HTTPException(status_code=400, detail="autodelete_day must be between 1 and 28")
        sets["pwa_settings.autodelete_day"] = d
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    sets["pwa_settings.updated_at"] = now_iso()
    sets["pwa_settings.updated_by"] = admin["user_id"]
    await db.firm_masters.update_one({"company_id": cid}, {"$set": sets}, upsert=True)
    return {"ok": True, "settings": await get_pwa_settings(cid)}


@router.post("/admin/pwa-wipe-last-month")
async def manual_pwa_wipe(payload: Dict[str, Any] = Body(default={}),
                          authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ADMIN_ROLES)
    cid = _admin_cid(admin, payload.get("company_id"))
    entry = await _execute_wipe(cid, "MANUAL", admin)
    return {"ok": True, "result": entry}


@router.get("/pwa-policy")
async def pwa_policy(authorization: Optional[str] = Header(None)):
    """Employee PWA policy — screenshot protection flag + attendance
    visibility cutoff. Also lazily runs the firm's auto-delete check."""
    user = await get_user_from_token(authorization)
    cid = user.get("company_id")
    if not cid:
        return {"screenshot_protection": False, "attendance_hidden_before": None}
    await run_autodelete_check(cid)
    s = await get_pwa_settings(cid)
    return {"screenshot_protection": bool(s.get("screenshot_protection")),
            "attendance_hidden_before": s.get("attendance_hidden_before"),
            "watermark": f"{user.get('name') or ''} · {user.get('employee_code') or ''}".strip(" ·")}
