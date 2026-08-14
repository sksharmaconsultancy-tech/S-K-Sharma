"""SMS notification service (Iter 576 — Phase 1).

Modules never call MSG91 directly — they call send_sms()/send_otp_sms()
here. Handles: company-wise settings resolution, rate limiting,
sms_log + Users Log (activity_log) entries. SMS failure NEVER raises
into business logic — callers get {"delivered": bool, "error": ...}.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from shared import msg91

SETTINGS_DEFAULTS = {
    "provider": "msg91",
    "enabled": False,
    "otp_enabled": False,
    "authkey": "",
    "sender_id": "",
    "entity_id": "",
    "otp_flow_id": "",       # DLT-approved OTP flow (##otp## variable)
    "default_flow_id": "",   # generic transactional flow for test/notifications
    "toggles": {"salary": True, "attendance": True, "leave": True,
                "payroll": True, "compliance": True, "onboarding": True},
    "rate_otp_per_10min": 3,
    "rate_mobile_per_hour": 5,
    "rate_user_per_min": 10,
}


async def get_sms_settings(db, company_id: Optional[str]) -> dict:
    """Company doc overrides the global doc; defaults fill the gaps."""
    g = await db.sms_settings.find_one({"company_id": "global"}, {"_id": 0}) or {}
    c = {}
    if company_id:
        c = await db.sms_settings.find_one({"company_id": company_id}, {"_id": 0}) or {}
    out = {**SETTINGS_DEFAULTS, **g, **{k: v for k, v in c.items() if v not in (None, "", {})}}
    out["toggles"] = {**SETTINGS_DEFAULTS["toggles"],
                      **(g.get("toggles") or {}), **(c.get("toggles") or {})}
    return out


def _now():
    return datetime.now(timezone.utc)


async def _rate_limited(db, st: dict, mobile: str, user_id: Optional[str],
                        is_otp: bool) -> Optional[str]:
    if is_otp and user_id:
        n = await db.sms_log.count_documents({
            "triggered_for": user_id, "is_otp": True,
            "at_dt": {"$gte": _now() - timedelta(minutes=10)}})
        if n >= int(st["rate_otp_per_10min"]):
            return "Too many OTP requests. Please try again later."
    n = await db.sms_log.count_documents({
        "mobile": mobile, "at_dt": {"$gte": _now() - timedelta(hours=1)}})
    if n >= int(st["rate_mobile_per_hour"]) and is_otp:
        return "Too many OTP requests for this mobile number. Please try again later."
    if user_id:
        n = await db.sms_log.count_documents({
            "triggered_by": user_id, "at_dt": {"$gte": _now() - timedelta(minutes=1)}})
        if n >= int(st["rate_user_per_min"]):
            return "SMS rate limit exceeded. Please wait a minute."
    return None


async def send_sms(db, *, company_id: Optional[str], mobile: str,
                   flow_id: str, variables: dict, notification_type: str,
                   triggered_by: Optional[str] = None,
                   triggered_for: Optional[str] = None,
                   ip: str = "", is_otp: bool = False,
                   settings: Optional[dict] = None) -> dict:
    """Send one template SMS through MSG91. Never raises."""
    st = settings or await get_sms_settings(db, company_id)
    m = msg91.normalize_mobile(mobile)
    log = {
        "log_id": f"sms_{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "mobile": m or (mobile or ""),
        "notification_type": notification_type,
        "flow_id": flow_id or "",
        "request_id": None,
        "status": "QUEUED",
        "error": None,
        "is_otp": is_otp,
        "triggered_by": triggered_by,
        "triggered_for": triggered_for,
        "ip": ip,
        "at": _now().isoformat(),
        "at_dt": _now(),
    }
    try:
        if not st["enabled"]:
            raise msg91.MSG91Error("sms_disabled")
        if not (st["authkey"] and st["sender_id"]):
            raise msg91.MSG91Error("msg91_not_configured")
        if not flow_id:
            raise msg91.MSG91Error("flow_id_missing (add DLT flow id in SMS Settings)")
        if not m:
            raise msg91.MSG91Error("invalid_mobile")
        limited = await _rate_limited(db, st, m, triggered_by or triggered_for, is_otp)
        if limited:
            raise msg91.MSG91Error(f"rate_limited: {limited}")
        res = await msg91.send_flow(st["authkey"], flow_id, st["sender_id"], m, variables)
        log["request_id"] = res.get("request_id")
        log["status"] = "SENT"
    except msg91.MSG91Error as exc:
        log["status"] = "FAILED"
        log["error"] = str(exc)[:250]
    except Exception as exc:  # noqa: BLE001 — SMS must never break callers
        log["status"] = "FAILED"
        log["error"] = f"unexpected: {str(exc)[:200]}"
    await db.sms_log.insert_one(dict(log))
    # Users Log (activity_log) integration — module Messaging.
    await db.activity_log.insert_one({
        "at": log["at"], "actor_id": triggered_by, "company_id": company_id,
        "method": "POST", "path": "/notifications/sms",
        "action": f"LOGIN SMS_{'SENT' if log['status'] == 'SENT' else 'FAILED'}"
        if is_otp else f"CREATE SMS_{'SENT' if log['status'] == 'SENT' else 'FAILED'}",
        "status": 200 if log["status"] == "SENT" else 502,
        "success": log["status"] == "SENT",
        "module": "Messaging", "record_id": log["log_id"],
        "record_label": f"{notification_type} → {msg91.mask_mobile(m)}",
        "changes": [], "old_values": None, "new_values": None,
        "details": (log["error"] or f"request_id={log['request_id']}")[:200],
        "device": "", "ip": ip,
    })
    return {"delivered": log["status"] == "SENT",
            "error": log["error"], "log_id": log["log_id"],
            "request_id": log["request_id"]}


async def send_otp_sms(db, user: dict, code: str, minutes: int, ip: str = "") -> dict:
    """OTP over MSG91 for the 2FA engine (self-generated hashed OTP)."""
    st = await get_sms_settings(db, user.get("company_id"))
    if not (st["enabled"] and st["otp_enabled"]):
        return {"delivered": False, "error": "msg91_otp_disabled"}
    return await send_sms(
        db, company_id=user.get("company_id"), mobile=user.get("phone") or "",
        flow_id=st["otp_flow_id"], variables={"otp": code, "var": code},
        notification_type="LOGIN_OTP", triggered_for=user.get("user_id"),
        ip=ip, is_otp=True, settings=st)
