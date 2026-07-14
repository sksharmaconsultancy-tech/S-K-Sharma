"""Super Admin Rights — manage super_admin accounts themselves.

Only a REAL super_admin can access these endpoints (sub-admins are
explicitly rejected). Safety rails:
  * You cannot disable or delete YOURSELF.
  * You cannot delete/disable the LAST enabled super admin.

New super admins can sign in with the email OTP flow (like the primary
super admin) and — when a password is set — the email + password flow.
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel

from server import (  # noqa: E402
    _hash_password,
    db,
    get_user_from_token,
    now_iso,
    require_super_admin_strict,
)

router = APIRouter(prefix="/api/admin/super-admins", tags=["super-admins"])


class SuperAdminCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    password: Optional[str] = None  # optional — OTP login always works


class SuperAdminUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    disabled: Optional[bool] = None


def _sanitise(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("password_hash", "_id")}


async def _enabled_count(exclude_user_id: Optional[str] = None) -> int:
    q: dict = {"role": "super_admin", "disabled": {"$ne": True}}
    if exclude_user_id:
        q["user_id"] = {"$ne": exclude_user_id}
    return await db.users.count_documents(q)


@router.get("")
async def list_super_admins(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    docs = await db.users.find(
        {"role": "super_admin"}, {"_id": 0, "password_hash": 0},
    ).sort("created_at", 1).to_list(100)
    return {
        "super_admins": docs,
        "me": admin["user_id"],
    }


@router.post("")
async def create_super_admin(
    payload: SuperAdminCreate,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    name = (payload.name or "").strip()
    email = (payload.email or "").strip().lower()
    phone = (payload.phone or "").strip() or None
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required for login")
    if payload.password and len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail=f"A user with email {email} already exists")
    if phone and await db.users.find_one({"$or": [{"phone_e164": phone}, {"phone": phone}]}):
        raise HTTPException(status_code=409, detail=f"A user with phone {phone} already exists")

    user_id = f"user_{uuid.uuid4().hex[:12]}"
    doc = {
        "user_id": user_id,
        "role": "super_admin",
        "name": name,
        "email": email,
        "phone": phone,
        "phone_e164": phone,
        "position": "Super Admin",
        "disabled": False,
        "created_at": now_iso(),
        "created_by": admin["user_id"],
        "onboarded": True,
        "approval_status": "approved",
    }
    if payload.password:
        doc["password_hash"] = _hash_password(payload.password)
        doc["password_must_change"] = True
    await db.users.insert_one(doc)

    from utils.welcome_email import send_admin_welcome_email
    await send_admin_welcome_email(
        name=name, email=email, role_label="Super Admin",
        password=payload.password or None,
    )
    return {"ok": True, "super_admin": _sanitise(doc)}


@router.patch("/{user_id}")
async def update_super_admin(
    user_id: str,
    payload: SuperAdminUpdate,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    existing = await db.users.find_one({"user_id": user_id, "role": "super_admin"}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Super admin not found")

    updates: dict = {}
    fset = payload.model_fields_set
    if "name" in fset and payload.name is not None:
        n = payload.name.strip()
        if not n:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        updates["name"] = n
    if "email" in fset and payload.email is not None:
        e = payload.email.strip().lower()
        if not e or "@" not in e:
            raise HTTPException(status_code=400, detail="Invalid email")
        if e != existing.get("email"):
            if await db.users.find_one({"email": e, "user_id": {"$ne": user_id}}):
                raise HTTPException(status_code=409, detail="Email already used")
        updates["email"] = e
    if "phone" in fset:
        p = (payload.phone or "").strip() or None
        if p and p != existing.get("phone_e164"):
            if await db.users.find_one(
                {"$or": [{"phone_e164": p}, {"phone": p}], "user_id": {"$ne": user_id}},
            ):
                raise HTTPException(status_code=409, detail="Phone already used")
        updates["phone_e164"] = p
        updates["phone"] = p
    if "disabled" in fset and payload.disabled is not None:
        if payload.disabled:
            if user_id == admin["user_id"]:
                raise HTTPException(status_code=400, detail="You cannot disable your own account")
            if await _enabled_count(exclude_user_id=user_id) == 0:
                raise HTTPException(status_code=400, detail="Cannot disable the last enabled super admin")
        updates["disabled"] = bool(payload.disabled)

    if updates:
        updates["updated_at"] = now_iso()
        await db.users.update_one({"user_id": user_id}, {"$set": updates})
        if updates.get("disabled"):
            await db.user_sessions.delete_many({"user_id": user_id})

    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0, "password_hash": 0})
    return {"ok": True, "super_admin": fresh}


@router.post("/{user_id}/reset-password")
async def reset_super_admin_password(
    user_id: str,
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    new_pw = (payload or {}).get("password", "")
    if not new_pw or len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    existing = await db.users.find_one({"user_id": user_id, "role": "super_admin"}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Super admin not found")
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "password_hash": _hash_password(new_pw),
            "password_must_change": True,
            "password_fail_count": 0,
            "password_locked_until": None,
            "password_reset_at": now_iso(),
            "password_reset_by": admin["user_id"],
        }},
    )
    return {"ok": True}


@router.delete("/{user_id}")
async def delete_super_admin(user_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    existing = await db.users.find_one({"user_id": user_id, "role": "super_admin"}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Super admin not found")
    if not existing.get("disabled") and await _enabled_count(exclude_user_id=user_id) == 0:
        raise HTTPException(status_code=400, detail="Cannot delete the last enabled super admin")
    await db.user_sessions.delete_many({"user_id": user_id})
    await db.users.delete_one({"user_id": user_id})
    return {"ok": True}
