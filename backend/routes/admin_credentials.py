"""Iter 93 — Firm admin login credentials (User ID + Password for App & Web).

Super-admin-only endpoints used by the Access Rights screen to set a
username-style "login_id" and/or password for a firm's company_admin so
the employer can sign in on the mobile app and the web portal with the
same credentials. Follows the auth playbook: bcrypt hashing, unique
case-insensitive login id, no plaintext ever returned.
"""
import re
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from server import (  # noqa: E402
    _hash_password,
    db,
    get_user_from_token,
    now_iso,
    require_super_admin_strict,
)

router = APIRouter(prefix="/api/admin/companies", tags=["admin-credentials"])

_LOGIN_ID_RE = re.compile(r"^[A-Za-z0-9_.]{3,32}$")


class AdminCredentialsSet(BaseModel):
    login_id: Optional[str] = None
    password: Optional[str] = None
    pin: Optional[str] = None  # 6-digit PIN for App login (admin-pin-login)


async def _firm_admin_or_404(company_id: str) -> dict:
    admin_user = await db.users.find_one(
        {"company_id": company_id, "role": "company_admin"},
        {"_id": 0, "password_hash": 0},
        sort=[("created_at", 1)],
    )
    if not admin_user:
        raise HTTPException(status_code=404, detail="No admin account found for this firm")
    return admin_user


@router.get("/{company_id}/admin-credentials")
async def get_admin_credentials(company_id: str, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_super_admin_strict(user)
    target = await _firm_admin_or_404(company_id)
    full = await db.users.find_one({"user_id": target["user_id"]}, {"_id": 0})
    return {
        "user_id": target["user_id"],
        "name": target.get("name"),
        "email": target.get("email"),
        "login_id": target.get("login_id"),
        "has_password": bool(full.get("password_hash")),
        "has_pin": bool(full.get("pin_hash")),
    }


@router.post("/{company_id}/admin-credentials")
async def set_admin_credentials(
    company_id: str,
    payload: AdminCredentialsSet,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_super_admin_strict(user)
    target = await _firm_admin_or_404(company_id)

    updates: dict = {}
    login_id = (payload.login_id or "").strip()
    if login_id:
        if not _LOGIN_ID_RE.match(login_id):
            raise HTTPException(
                status_code=400,
                detail="User ID must be 3-32 characters: letters, numbers, dot or underscore only",
            )
        # Unique across ALL users, case-insensitive (also don't collide with emails)
        clash = await db.users.find_one({
            "user_id": {"$ne": target["user_id"]},
            "$or": [
                {"login_id": {"$regex": f"^{re.escape(login_id)}$", "$options": "i"}},
                {"email": login_id.lower()},
            ],
        }, {"_id": 0, "user_id": 1})
        if clash:
            raise HTTPException(status_code=409, detail=f"User ID '{login_id}' is already taken")
        updates["login_id"] = login_id

    if payload.password:
        if len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        updates["password_hash"] = _hash_password(payload.password)
        updates["password_must_change"] = False
        updates["password_fail_count"] = 0
        updates["password_locked_until"] = None
        updates["password_set_by"] = user["user_id"]
        updates["password_set_at"] = now_iso()

    if payload.pin:
        pin = payload.pin.strip()
        if not pin.isdigit() or len(pin) != 6:
            raise HTTPException(status_code=400, detail="PIN must be exactly 6 digits")
        updates["pin_hash"] = _hash_password(pin)
        updates["has_pin"] = True
        updates["pin_must_change"] = False
        updates["pin_fail_count"] = 0
        updates["pin_locked_until"] = None

    if not updates:
        raise HTTPException(status_code=400, detail="Provide a User ID, password and/or PIN to set")

    await db.users.update_one({"user_id": target["user_id"]}, {"$set": updates})
    fresh = await db.users.find_one({"user_id": target["user_id"]}, {"_id": 0})
    return {
        "ok": True,
        "login_id": fresh.get("login_id"),
        "has_password": bool(fresh.get("password_hash")),
        "has_pin": bool(fresh.get("pin_hash")),
    }
