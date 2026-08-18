"""Iter 601 — Phase 1 (user spec): DEVICE FACE LOCK via WebAuthn/Passkeys.

The employee's phone biometric (Face ID / Face Unlock / fingerprint) NEVER
leaves the device — the PWA uses the platform authenticator and the backend
verifies the cryptographic assertion (challenge, origin, RP ID, signature,
user-verification flag, sign counter). We store ONLY the WebAuthn public
key + metadata, never any biometric data.

Rules (user decisions):
  * One employee → one ACTIVE device by default (policy-configurable max).
  * FIRST device: employee can self-register from the PWA.
  * REPLACEMENT: employee requests → HR/Admin approves → old credential
    revoked → new registration allowed.
  * Successful device auth issues a short-lived server-side
    verification_session — punch APIs will require it in Phase 3.
    Device auth alone NEVER creates attendance.
"""
import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    logger,
)

router = APIRouter(prefix="/api", tags=["webauthn-devices"])

CHALLENGE_TTL_MIN = 5
VERIFY_SESSION_TTL_MIN = 3   # punch must follow quickly after device auth


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _from_b64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _rp_from_request(request: Request) -> tuple:
    """Derive (rp_id, expected_origin) from the request Origin header —
    works for both the preview URL and the production domain."""
    origin = request.headers.get("origin") or ""
    host = urlparse(origin).hostname if origin else None
    if not host:
        host = (request.headers.get("host") or "localhost").split(":")[0]
        origin = f"https://{host}"
    return host, origin


async def _store_challenge(kind: str, user_id: str, challenge: bytes,
                           rp_id: str, origin: str) -> str:
    ch_id = f"wch_{uuid.uuid4().hex[:16]}"
    await db.webauthn_challenges.insert_one({
        "challenge_id": ch_id, "kind": kind, "user_id": user_id,
        "challenge_b64u": _b64u(challenge), "rp_id": rp_id, "origin": origin,
        "expires_at": (datetime.now(timezone.utc)
                       + timedelta(minutes=CHALLENGE_TTL_MIN)).isoformat(),
        "created_at": now_iso(),
    })
    return ch_id


async def _pop_challenge(ch_id: str, kind: str, user_id: str) -> dict:
    ch = await db.webauthn_challenges.find_one_and_delete(
        {"challenge_id": ch_id, "kind": kind, "user_id": user_id})
    if not ch:
        raise HTTPException(status_code=400, detail="Challenge expired — start again")
    if datetime.fromisoformat(ch["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Challenge expired — start again")
    return ch


def _device_row(c: dict) -> dict:
    return {k: c.get(k) for k in (
        "credential_ref", "device_label", "status", "registered_at",
        "last_used_at", "rp_id", "transports")}


async def _active_creds(user_id: str) -> List[dict]:
    return await db.webauthn_credentials.find(
        {"user_id": user_id, "status": "active"}, {"_id": 0}).to_list(10)


# ─────────────────────────── EMPLOYEE — registration ───────────────────────

@router.post("/attendance/device/register-options")
async def device_register_options(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    active = await _active_creds(user["user_id"])
    # Iter 607 — firm-configurable device limit (1-3, default 1). Under the
    # limit the employee may self-register an ADDITIONAL device; at the
    # limit a replacement needs an APPROVED change request.
    company = await db.companies.find_one(
        {"company_id": user.get("company_id")},
        {"_id": 0, "max_registered_devices": 1}) or {}
    max_dev = max(1, min(3, int(company.get("max_registered_devices") or 1)))
    if len(active) >= max_dev:
        # replacement needs an APPROVED change request
        req = await db.device_change_requests.find_one(
            {"user_id": user["user_id"], "status": "approved"})
        if not req:
            raise HTTPException(
                status_code=403,
                detail="A device is already registered. Request a device "
                       "change — HR/Admin must approve before you can "
                       "register a new phone.")
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, ResidentKeyRequirement,
        UserVerificationRequirement, AuthenticatorAttachment,
    )
    rp_id, origin = _rp_from_request(request)
    opts = generate_registration_options(
        rp_id=rp_id,
        rp_name="S.K. Sharma & Co. HRMS",
        user_id=user["user_id"].encode(),
        user_name=user.get("email") or user.get("employee_code") or user["user_id"],
        user_display_name=user.get("name") or "Employee",
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    ch_id = await _store_challenge("register", user["user_id"],
                                   opts.challenge, rp_id, origin)
    import json as _json
    return {"challenge_id": ch_id, "options": _json.loads(options_to_json(opts))}


@router.post("/attendance/device/register-verify")
async def device_register_verify(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    ch = await _pop_challenge(str(payload.get("challenge_id") or ""),
                              "register", user["user_id"])
    from webauthn import verify_registration_response
    try:
        vr = verify_registration_response(
            credential=payload.get("credential"),
            expected_challenge=_from_b64u(ch["challenge_b64u"]),
            expected_origin=ch["origin"],
            expected_rp_id=ch["rp_id"],
            require_user_verification=True,
        )
    except Exception as e:
        logger.warning("[webauthn] register verify failed: %s", e)
        raise HTTPException(status_code=400,
                            detail="Device registration could not be verified")
    # Iter 607 — replacement vs additional device: only revoke previous
    # credentials when this registration is an APPROVED replacement OR the
    # firm's device limit would be exceeded (default limit 1 keeps the
    # original replace-on-register behaviour).
    company = await db.companies.find_one(
        {"company_id": user.get("company_id")},
        {"_id": 0, "max_registered_devices": 1}) or {}
    max_dev = max(1, min(3, int(company.get("max_registered_devices") or 1)))
    approved_req = await db.device_change_requests.find_one(
        {"user_id": user["user_id"], "status": "approved"})
    n_active = await db.webauthn_credentials.count_documents(
        {"user_id": user["user_id"], "status": "active"})
    if approved_req or n_active >= max_dev:
        await db.webauthn_credentials.update_many(
            {"user_id": user["user_id"], "status": "active"},
            {"$set": {"status": "revoked", "revoked_at": now_iso(),
                      "revoked_reason": "replaced_by_new_registration"}})
        await db.device_change_requests.update_many(
            {"user_id": user["user_id"], "status": "approved"},
            {"$set": {"status": "completed", "completed_at": now_iso()}})
    cred_ref = f"dev_{uuid.uuid4().hex[:12]}"
    await db.webauthn_credentials.insert_one({
        "credential_ref": cred_ref,
        "user_id": user["user_id"],
        "company_id": user.get("company_id"),
        "credential_id_b64u": _b64u(vr.credential_id),
        "public_key_b64u": _b64u(vr.credential_public_key),
        "sign_count": vr.sign_count,
        "device_label": str(payload.get("device_label") or "")[:80],
        "transports": payload.get("transports") or [],
        "rp_id": ch["rp_id"],
        "status": "active",
        "registered_at": now_iso(),
        "last_used_at": None,
    })
    return {"ok": True, "message": "✓ Device registered — this phone is now "
                                   f"linked to {user.get('name')}",
            "device": {"credential_ref": cred_ref}}


# ─────────────────────────── EMPLOYEE — authentication ─────────────────────

@router.post("/attendance/device/auth-options")
async def device_auth_options(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    creds = await _active_creds(user["user_id"])
    if not creds:
        raise HTTPException(status_code=404,
                            detail="No registered device — register this "
                                   "phone first from Device Security.")
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import (
        PublicKeyCredentialDescriptor, UserVerificationRequirement)
    rp_id, origin = _rp_from_request(request)
    opts = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=_from_b64u(c["credential_id_b64u"]))
            for c in creds],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    ch_id = await _store_challenge("auth", user["user_id"],
                                   opts.challenge, rp_id, origin)
    import json as _json
    return {"challenge_id": ch_id, "options": _json.loads(options_to_json(opts))}


@router.post("/attendance/device/auth-verify")
async def device_auth_verify(
    request: Request,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    ch = await _pop_challenge(str(payload.get("challenge_id") or ""),
                              "auth", user["user_id"])
    cred_json = payload.get("credential") or {}
    raw_id = str(cred_json.get("rawId") or cred_json.get("id") or "")
    cred = await db.webauthn_credentials.find_one(
        {"user_id": user["user_id"], "credential_id_b64u": raw_id,
         "status": "active"}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=403,
                            detail="This device is not registered (or was "
                                   "revoked). Contact HR/Admin.")
    from webauthn import verify_authentication_response
    try:
        va = verify_authentication_response(
            credential=cred_json,
            expected_challenge=_from_b64u(ch["challenge_b64u"]),
            expected_origin=ch["origin"],
            expected_rp_id=ch["rp_id"],
            credential_public_key=_from_b64u(cred["public_key_b64u"]),
            credential_current_sign_count=int(cred.get("sign_count") or 0),
            require_user_verification=True,
        )
    except Exception as e:
        logger.warning("[webauthn] auth verify failed: %s", e)
        raise HTTPException(status_code=403,
                            detail="Device verification failed — "
                                   "authenticate with your registered device.")
    await db.webauthn_credentials.update_one(
        {"credential_ref": cred["credential_ref"]},
        {"$set": {"sign_count": va.new_sign_count,
                  "last_used_at": now_iso()}})
    # Short-lived, single-use verification session — Phase 3 punch flow
    # presents this to POST /api/attendance/punch when policy requires it.
    vs_id = f"vs_{uuid.uuid4().hex}"
    await db.punch_verification_sessions.insert_one({
        "session_id": vs_id,
        "user_id": user["user_id"],
        "company_id": user.get("company_id"),
        "device_auth": "pass",
        "credential_ref": cred["credential_ref"],
        "face_match": None,     # filled by the face-verification step
        "liveness": None,
        "anti_spoof": None,
        "used": False,
        "expires_at": (datetime.now(timezone.utc)
                       + timedelta(minutes=VERIFY_SESSION_TTL_MIN)).isoformat(),
        "created_at": now_iso(),
    })
    return {"ok": True, "verification_session_id": vs_id,
            "message": "Device verified ✓"}


# ─────────────────────────── EMPLOYEE — status & change request ────────────

@router.get("/attendance/device/status")
async def device_status(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    creds = await _active_creds(user["user_id"])
    req = await db.device_change_requests.find_one(
        {"user_id": user["user_id"], "status": {"$in": ["pending", "approved"]}},
        {"_id": 0})
    return {"devices": [_device_row(c) for c in creds],
            "change_request": req}


@router.post("/attendance/device/request-change")
async def device_request_change(
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    if not await _active_creds(user["user_id"]):
        raise HTTPException(status_code=400,
                            detail="No registered device — you can register "
                                   "directly, no approval needed.")
    exists = await db.device_change_requests.find_one(
        {"user_id": user["user_id"], "status": {"$in": ["pending", "approved"]}})
    if exists:
        return {"ok": True, "message": "Request already " + exists["status"]}
    await db.device_change_requests.insert_one({
        "request_id": f"dcr_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "company_id": user.get("company_id"),
        "name": user.get("name"),
        "employee_code": user.get("employee_code"),
        "reason": str(payload.get("reason") or "")[:300],
        "status": "pending",
        "requested_at": now_iso(),
    })
    return {"ok": True,
            "message": "Device change requested — HR/Admin approval needed."}


# ─────────────────────────── ADMIN — device management ─────────────────────

@router.get("/admin/attendance/devices")
async def admin_list_devices(
    user_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    q: dict = {}
    if user_id:
        q["user_id"] = user_id
    if admin["role"] == "company_admin":
        q["company_id"] = admin["company_id"]
    elif company_id:
        q["company_id"] = company_id
    creds = await db.webauthn_credentials.find(
        q, {"_id": 0, "public_key_b64u": 0, "credential_id_b64u": 0},
    ).sort("registered_at", -1).to_list(500)
    reqs = await db.device_change_requests.find(
        {**q, "status": "pending"} if q else {"status": "pending"},
        {"_id": 0}).to_list(200)
    # Iter 607 — enrich with employee name/code for the admin UI.
    uids = list({c["user_id"] for c in creds} | {r["user_id"] for r in reqs})
    names = {u["user_id"]: u async for u in db.users.find(
        {"user_id": {"$in": uids}},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1})}
    for row in creds + reqs:
        u = names.get(row["user_id"]) or {}
        row["employee_name"] = u.get("name")
        row["employee_code"] = u.get("employee_code")
    return {"devices": creds, "pending_requests": reqs}


@router.post("/admin/attendance/devices/revoke")
async def admin_revoke_device(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    ref = str(payload.get("credential_ref") or "")
    cred = await db.webauthn_credentials.find_one({"credential_ref": ref}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=404, detail="Device not found")
    if admin["role"] == "company_admin" and cred.get("company_id") != admin["company_id"]:
        raise HTTPException(status_code=403, detail="Not your company's device")
    await db.webauthn_credentials.update_one(
        {"credential_ref": ref},
        {"$set": {"status": "revoked", "revoked_at": now_iso(),
                  "revoked_by": admin["user_id"],
                  "revoked_reason": str(payload.get("reason") or "admin_revoke")}})
    return {"ok": True, "message": "Device revoked — it can no longer authenticate punches."}


@router.post("/admin/attendance/devices/approve-change")
async def admin_approve_change(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    rid = str(payload.get("request_id") or "")
    req = await db.device_change_requests.find_one({"request_id": rid}, {"_id": 0})
    if not req or req.get("status") != "pending":
        raise HTTPException(status_code=404, detail="Pending request not found")
    if admin["role"] == "company_admin" and req.get("company_id") != admin["company_id"]:
        raise HTTPException(status_code=403, detail="Not your company's request")
    approve = bool(payload.get("approve", True))
    await db.device_change_requests.update_one(
        {"request_id": rid},
        {"$set": {"status": "approved" if approve else "rejected",
                  "decided_by": admin["user_id"], "decided_at": now_iso()}})
    return {"ok": True, "status": "approved" if approve else "rejected"}
