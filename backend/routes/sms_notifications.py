"""Iter 576 — MSG91 SMS Phase 1 routes.

* GET/PUT /api/admin/sms-settings          (company-wise; authkey masked)
* POST    /api/admin/sms-settings/test     (send test SMS)
* GET     /api/admin/sms-logs              (masked mobiles, firm-scoped)
* GET     /api/admin/otp-logs              (from activity_log OTP_* events)
"""
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

from server import db, get_user_from_token, require_role, now_iso, _req_ip  # noqa: E402
from shared.sms_service import get_sms_settings, send_sms, SETTINGS_DEFAULTS  # noqa: E402
from shared.msg91 import mask_mobile  # noqa: E402

router = APIRouter(prefix="/api")
_MASK = "••••••••"


def _scope(admin, company_id):
    if admin["role"] == "company_admin":
        return admin.get("company_id")
    return company_id


@router.get("/admin/sms-settings")
async def get_settings(company_id: Optional[str] = Query(None),
                       authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    st = await get_sms_settings(db, _scope(admin, company_id))
    if st.get("authkey"):
        st["authkey"] = _MASK
        st["authkey_set"] = True
    else:
        st["authkey_set"] = False
    st["api_status"] = "Connected" if st["authkey_set"] and st["sender_id"] else "Not Connected"
    return st


@router.put("/admin/sms-settings")
async def put_settings(payload: dict, request: Request,
                       company_id: Optional[str] = Query(None),
                       authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    key = (company_id or "global").strip() or "global"
    existing = await db.sms_settings.find_one({"company_id": key}, {"_id": 0}) or {}
    upd: dict = {}
    for k in ("enabled", "otp_enabled"):
        if k in payload:
            upd[k] = bool(payload[k])
    for k in ("sender_id", "entity_id", "otp_flow_id", "default_flow_id"):
        if k in payload and isinstance(payload[k], str):
            upd[k] = payload[k].strip()
    for k in ("rate_otp_per_10min", "rate_mobile_per_hour", "rate_user_per_min"):
        if k in payload:
            try:
                v = int(payload[k])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"Invalid {k}")
            if not (1 <= v <= 1000):
                raise HTTPException(status_code=400, detail=f"{k} out of range")
            upd[k] = v
    if isinstance(payload.get("toggles"), dict):
        upd["toggles"] = {**SETTINGS_DEFAULTS["toggles"],
                          **(existing.get("toggles") or {}),
                          **{k: bool(v) for k, v in payload["toggles"].items()
                             if k in SETTINGS_DEFAULTS["toggles"]}}
    ak = payload.get("authkey")
    if isinstance(ak, str) and ak and ak != _MASK:
        upd["authkey"] = ak.strip()
    if not upd:
        raise HTTPException(status_code=400, detail="Nothing to update")
    upd.update({"company_id": key, "provider": "msg91",
                "updated_at": now_iso(), "updated_by": admin["user_id"]})
    await db.sms_settings.update_one({"company_id": key}, {"$set": upd}, upsert=True)
    await db.activity_log.insert_one({
        "at": now_iso(), "actor_id": admin["user_id"], "actor_name": admin.get("name"),
        "actor_role": admin.get("role"), "company_id": None if key == "global" else key,
        "method": "PUT", "path": "/api/admin/sms-settings",
        "action": "UPDATE SMS_SETTINGS", "status": 200, "success": True,
        "module": "Messaging", "record_id": key, "record_label": f"SMS settings ({key})",
        "changes": [], "old_values": None, "new_values": None,
        "details": ", ".join(sorted(k for k in upd if k not in
                                    ("company_id", "provider", "updated_at", "updated_by", "authkey"))),
        "device": (request.headers.get("user-agent") or "")[:200], "ip": _req_ip(request),
    })
    return {"ok": True}


@router.post("/admin/sms-settings/test")
async def test_sms(payload: dict, request: Request,
                   authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    mobile = (payload.get("mobile") or "").strip()
    if not mobile:
        raise HTTPException(status_code=400, detail="Enter a mobile number")
    cid = payload.get("company_id") or None
    st = await get_sms_settings(db, cid)
    flow = (payload.get("flow_id") or st["default_flow_id"] or st["otp_flow_id"]).strip()
    res = await send_sms(
        db, company_id=cid, mobile=mobile, flow_id=flow,
        variables={"var": "TEST", "otp": "000000", "name": admin.get("name") or "Admin"},
        notification_type="TEST_SMS", triggered_by=admin["user_id"],
        ip=_req_ip(request))
    return res


@router.get("/admin/sms-logs")
async def sms_logs(company_id: Optional[str] = Query(None),
                   status: Optional[str] = Query(None),
                   from_date: Optional[str] = Query(None),
                   to_date: Optional[str] = Query(None),
                   authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    q: dict = {}
    cid = _scope(admin, company_id)
    if cid:
        q["company_id"] = cid
    if status:
        q["status"] = status.upper()
    rng = {}
    if from_date:
        rng["$gte"] = f"{from_date}T00:00:00"
    if to_date:
        rng["$lte"] = f"{to_date}T23:59:59"
    if rng:
        q["at"] = rng
    out = []
    async for r in db.sms_log.find(q, {"_id": 0, "at_dt": 0}).sort("at", -1).limit(500):
        r["mobile"] = mask_mobile(r.get("mobile") or "")
        out.append(r)
    total = len(out)
    sent = sum(1 for r in out if r["status"] == "SENT")
    return {"logs": out, "summary": {"total": total, "sent": sent,
                                     "failed": total - sent,
                                     "otp": sum(1 for r in out if r.get("is_otp"))}}


@router.get("/admin/otp-logs")
async def otp_logs(company_id: Optional[str] = Query(None),
                   from_date: Optional[str] = Query(None),
                   to_date: Optional[str] = Query(None),
                   authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    q: dict = {"action": {"$regex": "OTP_|SMS_"}}
    cid = _scope(admin, company_id)
    if cid:
        q["company_id"] = cid
    rng = {}
    if from_date:
        rng["$gte"] = f"{from_date}T00:00:00"
    if to_date:
        rng["$lte"] = f"{to_date}T23:59:59"
    if rng:
        q["at"] = rng
    out = []
    async for e in db.activity_log.find(q, {"_id": 0}).sort("at", -1).limit(500):
        out.append({"at": e.get("at"), "actor_id": e.get("actor_id"),
                    "actor_name": e.get("actor_name"), "company_id": e.get("company_id"),
                    "action": e.get("action"), "success": e.get("success"),
                    "details": e.get("details"), "ip": e.get("ip"),
                    "device": (e.get("device") or "")[:80]})
    return {"logs": out, "count": len(out)}
