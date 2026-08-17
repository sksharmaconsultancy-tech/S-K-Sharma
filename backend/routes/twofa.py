"""Iter 569 — 2FA/MFA routes (Super Admin & Sub Admin login security).

Works with the pre-auth challenge created by `_start_2fa_challenge` in
server.py (admin PIN / password login). No full session exists until
`POST /api/auth/2fa/verify` succeeds.

Endpoints:
  * POST /api/auth/2fa/verify          — verify OTP → full session
  * POST /api/auth/2fa/resend          — resend / change delivery method
  * GET  /api/auth/2fa/my-security     — own security overview (masked)
  * PUT  /api/auth/2fa/preferred-method
  * GET  /api/auth/2fa/trusted-devices — list own trusted devices
  * POST /api/auth/2fa/trusted-devices/revoke
  * POST /api/auth/logout-all          — revoke every session of the user
  * GET/PUT /api/admin/security-settings/2fa  — super admin settings
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import os

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from server import (  # noqa: E402
    db, get_user_from_token, require_role, now_iso, logger,
    _hash_otp, _issue_session, _enrich_user_with_company,
    _twofa_settings, _twofa_methods_for_user, _twofa_methods_async,
    _twofa_send_code, _twofa_audit, _twofa_new_code, _mask_email,
    _mask_mobile, _req_ip, OTP_DEV_MODE,
    _send_security_alert, _security_check_new_ip,
)
import secrets as _secrets

router = APIRouter(prefix="/api")


class VerifyReq(BaseModel):
    pending_token: str
    otp: str
    trust_device: bool = False
    device_name: Optional[str] = None


class ResendReq(BaseModel):
    pending_token: str
    method: Optional[str] = None  # switch channel: email | whatsapp | sms


class PreferredMethodReq(BaseModel):
    method: str


class RevokeDeviceReq(BaseModel):
    device_id: str


def _as_utc(v):
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v)
        except ValueError:
            return None
    if isinstance(v, datetime) and v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v


async def _load_pending(pending_token: str) -> dict:
    row = await db.twofa_pending.find_one({"pending_id": (pending_token or "").strip()})
    if not row:
        raise HTTPException(status_code=401, detail="This verification session has expired. Please sign in again.")
    exp = _as_utc(row.get("expires_at"))
    if not exp or exp < datetime.now(timezone.utc):
        await db.twofa_pending.delete_one({"_id": row["_id"]})
        raise HTTPException(status_code=401, detail="This verification session has expired. Please sign in again.")
    return row


@router.post("/auth/2fa/verify")
async def twofa_verify(payload: VerifyReq, request: Request):
    st = await _twofa_settings()
    row = await _load_pending(payload.pending_token)
    user = await db.users.find_one({"user_id": row["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid verification session.")

    if row.get("blocked"):
        raise HTTPException(status_code=429, detail="Too many incorrect OTP attempts. Please request a new OTP.")

    otp = (payload.otp or "").strip()
    if not otp.isdigit() or len(otp) != int(st["otp_length"]):
        raise HTTPException(status_code=400, detail="Invalid OTP. Please check the OTP and try again.")

    otp_exp = _as_utc(row.get("otp_expires_at"))
    if not otp_exp or otp_exp < datetime.now(timezone.utc):
        await _twofa_audit(user, "OTP_EXPIRED", request, False, "OTP expired before verification", row.get("method") or "")
        raise HTTPException(status_code=401, detail="This OTP has expired. Please request a new OTP.")

    if _hash_otp(otp) != row.get("otp_hash"):
        attempts = int(row.get("attempts") or 0) + 1
        max_att = int(st["max_attempts"])
        upd = {"$set": {"attempts": attempts}}
        if attempts >= max_att:
            # Invalidate the OTP entirely — a new one must be requested.
            upd["$set"].update({"blocked": True, "otp_hash": None})
            await db.twofa_pending.update_one({"_id": row["_id"]}, upd)
            await _twofa_audit(user, "OTP_BLOCKED", request, False,
                               f"Blocked after {attempts} failed attempts", row.get("method") or "")
            # Iter 570 — proactive alert to Super Admins on OTP lockout.
            await _send_security_alert(
                f"🚨 OTP lockout — {user.get('name') or user.get('email')}",
                [("Event", "2FA OTP BLOCKED after too many wrong attempts"),
                 ("User", f"{user.get('name') or '—'} ({user.get('role') or '—'})"),
                 ("Email", user.get("email") or "—"),
                 ("Failed Attempts", f"{attempts}/{max_att}"),
                 ("IP Address", _req_ip(request) or "—"),
                 ("Device", (request.headers.get("user-agent") or "")[:120] or "—"),
                 ("Time (UTC)", now_iso()[:19].replace("T", " "))],
                st)
            raise HTTPException(status_code=429, detail="Too many incorrect OTP attempts. Please request a new OTP.")
        await db.twofa_pending.update_one({"_id": row["_id"]}, upd)
        await _twofa_audit(user, "OTP_VERIFICATION_FAILED", request, False,
                           f"Invalid OTP — attempt {attempts}/{max_att}", row.get("method") or "")
        raise HTTPException(status_code=401, detail="Invalid OTP. Please use the code from the NEWEST email and try again.")

    # SUCCESS — one-time use: destroy the pending challenge (also prevents
    # replay), then create the full session (fresh token = regenerated id).
    await db.twofa_pending.delete_one({"_id": row["_id"]})
    token = await _issue_session(user["user_id"], row.get("login_kind") or "password")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"twofa_last_verified_at": now_iso()}})
    await _twofa_audit(user, "OTP_VERIFICATION_SUCCESS", request, True,
                       "2FA verified — session created", row.get("method") or "")
    # Iter 570 — record login IP; alert Super Admins on a brand-new IP.
    await _security_check_new_ip(user, request)

    resp: dict = {}
    # Optional trusted device (only when the feature is enabled in settings).
    if payload.trust_device and st["trusted_device_enabled"]:
        device_token = _secrets.token_hex(32)
        ua = (request.headers.get("user-agent") or "")[:200]
        await db.trusted_devices.insert_one({
            "device_id": f"td_{_secrets.token_hex(8)}",
            "user_id": user["user_id"],
            "token_hash": _hash_otp(device_token),
            "device_name": (payload.device_name or "").strip()[:80] or ua[:80],
            "browser": ua,
            "ip_address": _req_ip(request),
            "created_at": now_iso(),
            "last_used_at": now_iso(),
            "expires_at": datetime.now(timezone.utc) + timedelta(days=int(st["trusted_days"])),
            "revoked_at": None,
        })
        await _twofa_audit(user, "TRUSTED_DEVICE_ADDED", request, True,
                           f"Trusted for {st['trusted_days']} days")
        resp["device_token"] = device_token

    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    fresh = await _enrich_user_with_company(fresh)
    logger.info(f"[2FA] verification OK for {user.get('email') or user.get('phone')}")
    resp.update({
        "session_token": token,
        "user": fresh,
        "pin_must_change": bool(fresh.get("pin_must_change")),
        "password_must_change": bool(fresh.get("password_must_change")),
    })
    return resp


@router.post("/auth/2fa/resend")
async def twofa_resend(payload: ResendReq, request: Request):
    st = await _twofa_settings()
    row = await _load_pending(payload.pending_token)
    user = await db.users.find_one({"user_id": row["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid verification session.")

    now = datetime.now(timezone.utc)
    ra = _as_utc(row.get("resend_available_at"))
    if ra and ra > now:
        wait = int((ra - now).total_seconds()) + 1
        raise HTTPException(status_code=429, detail=f"Please wait {wait}s before requesting another OTP.")

    method = (payload.method or row.get("method") or "email").lower()
    methods = await _twofa_methods_async(user, st)
    m = next((x for x in methods if x["method"] == method), None)
    if not m:
        raise HTTPException(status_code=400, detail="This verification method is not available for your account.")
    if not m["configured"]:
        raise HTTPException(status_code=400, detail="We could not send the OTP using this method. Please try another verification method.")

    changed = method != row.get("method")
    code = _twofa_new_code(int(st["otp_length"]))
    # New OTP invalidates the previous one; attempts reset for the new code.
    await db.twofa_pending.update_one(
        {"_id": row["_id"]},
        {"$set": {
            "otp_hash": _hash_otp(code),
            "otp_expires_at": now + timedelta(minutes=int(st["otp_validity_min"])),
            "attempts": 0,
            "blocked": False,
            "method": method,
            "resend_available_at": now + timedelta(seconds=int(st["resend_cooldown_sec"])),
        }})
    delivery = await _twofa_send_code(user, method, code, st)
    await _twofa_audit(user, "OTP_RESEND" if not changed else "2FA_METHOD_CHANGED",
                       request, True, f"OTP re-issued via {method}", method)
    await _twofa_audit(user, f"OTP_SENT_{method.upper()}", request,
                       bool(delivery["delivered"]), delivery.get("error") or "delivered", method)
    resp = {
        "ok": True,
        "method": method,
        "delivered": delivery["delivered"],
        "otp_expires_in": int(st["otp_validity_min"]) * 60,
        "resend_cooldown": int(st["resend_cooldown_sec"]),
    }
    if delivery.get("error"):
        resp["delivery_error"] = delivery["error"]
    if delivery.get("note"):
        resp["delivery_note"] = delivery["note"]
    if OTP_DEV_MODE:
        resp["dev_hint"] = f"code ends in ...{code[-2:]}"
    return resp


# ── Authenticated security overview / preferences ──────────────────────────

@router.get("/auth/2fa/my-security")
async def my_security(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    st = await _twofa_settings()
    required = user.get("role") in st["mandatory_roles"] or bool(user.get("twofa_enabled"))
    sessions = await db.user_sessions.count_documents({
        "user_id": user["user_id"],
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    devices = await db.trusted_devices.count_documents({
        "user_id": user["user_id"], "revoked_at": None,
    })
    return {
        "twofa_required": required,
        "preferred_method": user.get("twofa_method") or "email",
        "masked_email": _mask_email(user.get("email") or ""),
        "masked_mobile": _mask_mobile(user.get("phone") or ""),
        "methods": await _twofa_methods_async(user, st),
        "last_verified_at": user.get("twofa_last_verified_at"),
        "active_sessions": sessions,
        "trusted_devices": devices,
        "trusted_device_enabled": bool(st["trusted_device_enabled"]),
    }


@router.put("/auth/2fa/preferred-method")
async def set_preferred_method(payload: PreferredMethodReq, request: Request,
                               authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    method = (payload.method or "").lower()
    if method not in ("email", "whatsapp", "sms"):
        raise HTTPException(status_code=400, detail="Invalid method")
    st = await _twofa_settings()
    if not any(m["method"] == method for m in _twofa_methods_for_user(user, st)):
        raise HTTPException(status_code=400, detail="This method is not available for your account.")
    await db.users.update_one({"user_id": user["user_id"]},
                              {"$set": {"twofa_method": method}})
    await _twofa_audit(user, "2FA_METHOD_CHANGED", request, True,
                       f"Preferred method set to {method}", method)
    return {"ok": True, "preferred_method": method}


@router.get("/auth/2fa/trusted-devices")
async def list_trusted_devices(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    out = []
    async for d in db.trusted_devices.find(
        {"user_id": user["user_id"], "revoked_at": None},
        {"_id": 0, "token_hash": 0},
    ).sort("created_at", -1).limit(50):
        exp = _as_utc(d.get("expires_at"))
        d["expires_at"] = exp.isoformat() if exp else None
        d["expired"] = bool(exp and exp < datetime.now(timezone.utc))
        out.append(d)
    return {"devices": out}


@router.post("/auth/2fa/trusted-devices/revoke")
async def revoke_trusted_device(payload: RevokeDeviceReq, request: Request,
                                authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    r = await db.trusted_devices.update_one(
        {"device_id": payload.device_id, "user_id": user["user_id"]},
        {"$set": {"revoked_at": now_iso()}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Device not found")
    await _twofa_audit(user, "TRUSTED_DEVICE_REVOKED", request, True,
                       f"device_id={payload.device_id}")
    return {"ok": True}


@router.post("/auth/logout-all")
async def logout_all(request: Request, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    r = await db.user_sessions.delete_many({"user_id": user["user_id"]})
    await _twofa_audit(user, "ALL_SESSIONS_REVOKED", request, True,
                       f"{r.deleted_count} session(s) revoked")
    return {"ok": True, "revoked": r.deleted_count}


# ── Super-admin security settings ───────────────────────────────────────────

_MASK = "••••••••"
_SECRET_FIELDS_WA = ("access_token",)
_SECRET_FIELDS_SMS = ("twilio_token", "msg91_authkey", "fast2sms_key", "twilio_sid")


@router.get("/admin/security-settings/2fa")
async def get_security_settings(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    st = await _twofa_settings()
    # Mask stored secrets — never send them back to the browser.
    wa = dict(st["whatsapp_config"])
    for f in _SECRET_FIELDS_WA:
        if wa.get(f):
            wa[f] = _MASK
    sms = dict(st["sms_config"])
    for f in _SECRET_FIELDS_SMS:
        if sms.get(f):
            sms[f] = _MASK
    st["whatsapp_config"] = wa
    st["sms_config"] = sms
    st["email_configured"] = bool(os.getenv("RESEND_API_KEY", "").strip())
    return st


@router.put("/admin/security-settings/2fa")
async def update_security_settings(payload: dict, request: Request,
                                   authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    st = await _twofa_settings()
    allowed_int = {"otp_length": (4, 8), "otp_validity_min": (1, 30),
                   "resend_cooldown_sec": (10, 300), "max_attempts": (3, 10),
                   "trusted_days": (1, 90)}
    upd: dict = {}
    for k, (lo, hi) in allowed_int.items():
        if k in payload:
            try:
                v = int(payload[k])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"Invalid value for {k}")
            if not (lo <= v <= hi):
                raise HTTPException(status_code=400, detail=f"{k} must be between {lo} and {hi}")
            upd[k] = v
    for k in ("email_enabled", "whatsapp_enabled", "sms_enabled",
              "trusted_device_enabled", "security_alerts_enabled",
              "otp_email_via_smtp", "fallback_to_admin_email"):
        if k in payload:
            upd[k] = bool(payload[k])
    # Provider configs — masked values ("••••••••") mean "keep existing".
    if isinstance(payload.get("whatsapp_config"), dict):
        wa = dict(st["whatsapp_config"])
        for k, v in payload["whatsapp_config"].items():
            if k in wa and isinstance(v, str) and v != _MASK:
                wa[k] = v.strip()
        upd["whatsapp_config"] = wa
    if isinstance(payload.get("sms_config"), dict):
        sms = dict(st["sms_config"])
        for k, v in payload["sms_config"].items():
            if k in sms and isinstance(v, str) and v != _MASK:
                sms[k] = v.strip()
        upd["sms_config"] = sms
    if not upd:
        raise HTTPException(status_code=400, detail="Nothing to update")
    upd["updated_at"] = now_iso()
    upd["updated_by"] = admin["user_id"]
    await db.security_settings.update_one({"key": "2fa"}, {"$set": upd}, upsert=True)
    await _twofa_audit(admin, "2FA_SETTINGS_UPDATED", request, True,
                       ", ".join(sorted(k for k in upd if k not in ("updated_at", "updated_by"))))
    return {"ok": True}


@router.post("/admin/security-settings/email-check")
async def email_deliverability_check(authorization: Optional[str] = Header(None)):
    """Iter 593 — one-button OTP email deliverability self-check.
    Reports exactly why registered users may not receive OTP mails:
    Resend key present? Which FROM address? Domains verified on the
    account? SMTP fallback configured? Then test-sends to the admin."""
    import httpx
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip()
    from_domain = from_email.split("@")[-1].lower()
    checks: list = []
    advice: list = []
    domains: list = []
    checks.append({"name": "Resend API key configured", "ok": bool(key)})
    if key:
        try:
            async with httpx.AsyncClient(timeout=15) as cl:
                r = await cl.get("https://api.resend.com/domains",
                                 headers={"Authorization": f"Bearer {key}"})
            if r.status_code == 200:
                domains = [{"name": d.get("name"), "status": d.get("status")}
                           for d in (r.json().get("data") or [])]
        except Exception as exc:  # noqa: BLE001
            checks.append({"name": "Resend API reachable", "ok": False, "detail": str(exc)[:120]})
    verified = [d["name"] for d in domains if d.get("status") == "verified"]
    checks.append({"name": "Verified domain on Resend account", "ok": bool(verified),
                   "detail": ", ".join(verified) if verified
                   else "NO verified domains — Resend is in TEST mode (delivers only to the account owner's email)"})
    from_ok = from_domain in [v.lower() for v in verified]
    checks.append({"name": f"FROM address uses a verified domain ({from_email})",
                   "ok": from_ok})
    if not verified:
        advice.append("Verify your domain at resend.com/domains (add the DKIM/SPF DNS records), "
                      "then set RESEND_FROM_EMAIL=no-reply@<your-domain> in backend/.env and restart.")
    elif not from_ok:
        advice.append(f"Change RESEND_FROM_EMAIL to an address on: {', '.join(verified)}.")
    # SMTP fallback status
    smtp_ok = False
    try:
        from routes.email_notifications import _get_settings as _smtp_get
        smtp = await _smtp_get()
        smtp_ok = bool(smtp and smtp.get("enabled") and smtp.get("username"))
    except Exception:
        pass
    st = await _twofa_settings()
    checks.append({"name": "Own SMTP configured (Email Settings)", "ok": smtp_ok})
    checks.append({"name": "'Send OTP via own SMTP' toggle", "ok": bool(st.get("otp_email_via_smtp")),
                   "detail": "ON — OTPs bypass Resend limits" if st.get("otp_email_via_smtp")
                   else "OFF"})
    if not smtp_ok and not verified:
        advice.append("Quick fix without DNS: configure SMTP in Email Settings and switch ON "
                      "'Send OTP via own SMTP' here — OTPs then reach every user immediately.")
    # live test send to the requesting super admin (works even in test mode).
    # Iter 593b — clearly labelled as a TEST so it can't be mistaken for a
    # real login OTP (previously reused the OTP template with 000000).
    test = {"delivered": False, "error": "no key"}
    if key:
        try:
            async with httpx.AsyncClient(timeout=15) as cl:
                tr = await cl.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"from": f"S.K. Sharma & Co <{from_email}>",
                          "to": [admin.get("email") or ""],
                          "subject": "TEST — Email Deliverability Check (please ignore)",
                          "html": ("<p><b>This is only a delivery test</b> triggered from "
                                   "Security · 2FA/MFA → Run Email Deliverability Check.</p>"
                                   "<p>It is <b>not</b> a login code — no action is needed. "
                                   "If you received this, the email pipeline can reach this "
                                   "address.</p><p>— Smart Payroll, S.K. Sharma &amp; Co</p>")})
            if tr.status_code in (200, 201):
                test = {"delivered": True, "error": None}
            else:
                test = {"delivered": False, "error": tr.text[:160]}
        except Exception as exc:  # noqa: BLE001
            test = {"delivered": False, "error": str(exc)[:160]}
    checks.append({"name": f"Test email to {admin.get('email')} (clearly marked TEST)",
                   "ok": bool(test.get("delivered")),
                   "detail": str(test.get("error") or "delivered")[:160]})
    can_deliver_to_all = (bool(verified) and from_ok) or (smtp_ok and bool(st.get("otp_email_via_smtp")))
    verdict = ("✅ OTP emails will reach EVERY registered user."
               if can_deliver_to_all else
               "❌ OTP emails currently reach ONLY the Resend account owner — registered users will NOT receive them.")
    return {"verdict": verdict, "can_deliver_to_all": can_deliver_to_all,
            "from_email": from_email, "domains": domains,
            "checks": checks, "advice": advice}
