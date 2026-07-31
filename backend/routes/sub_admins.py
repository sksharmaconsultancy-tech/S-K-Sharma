"""Iter 409 — SUB-ADMINS + EMPLOYER ACCESS module (extracted from server.py).

Refactor only: every endpoint, model and helper below was MOVED verbatim
from server.py — sub-admin CRUD (Iter 57), employer portal credentials
(EPFO/ESIC/Shram Suvidha, Iter 58) and employer access-rights / menu
rights (Iter 58/93). No behavioural change.
"""
import re
import uuid
from typing import List, Literal, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel

from server import (  # noqa: E402
    EMPLOYER_PERMISSION_KEYS,
    SUB_ADMIN_PERMISSION_KEYS,
    _hash_password,
    _hash_pin,
    _normalise_phone,
    db,
    get_user_from_token,
    now_iso,
    require_super_admin_strict,
    sub_admin_can_touch_company,
)

router = APIRouter(prefix="/api")
api = router  # endpoints below keep their original @api.* decorators


# ---------------------------------------------------------------------------
# Sub-admins (delegated super-admin accounts) — Iter 57
# ---------------------------------------------------------------------------
# A super_admin can create sub_admin accounts to delegate portions of the
# Super Admin portal. Sub-admins log in with the same email + password
# (or phone + password) flow as company admins. On login they receive
# `role: "sub_admin"` and their configured permission list + company scope.
# The frontend uses these to build the filtered nav and gate routes.

class SubAdminCreate(BaseModel):
    """Super admin creates a sub-admin. Password is set at creation and
    must be shared with the sub-admin out-of-band (or via the temp-cred flow)."""
    name: str
    email: str
    phone: Optional[str] = None
    password: str
    pin: Optional[str] = None  # Iter 220 — optional separate 6-digit login PIN
    permissions: List[str] = []
    company_scope: Literal["all", "restricted"] = "all"
    company_ids: List[str] = []  # only used when scope=="restricted"
    menu_rights: dict = {}  # Iter 93 — {route: bool}; missing == allowed


class SubAdminUpdate(BaseModel):
    """Any field left as None is unchanged. To change password use the
    dedicated reset endpoint below."""
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    pin: Optional[str] = None  # Iter 220 — set/replace the 6-digit login PIN
    permissions: Optional[List[str]] = None
    company_scope: Optional[Literal["all", "restricted"]] = None
    company_ids: Optional[List[str]] = None
    disabled: Optional[bool] = None
    # Iter 93 — per-sidebar-button visibility {route: bool}; missing == allowed
    menu_rights: Optional[dict] = None


def _validate_sub_admin_permissions(perms: List[str]) -> List[str]:
    """Filter & de-dupe against the known permission keys."""
    if not perms:
        return []
    known = set(SUB_ADMIN_PERMISSION_KEYS)
    return sorted({p for p in perms if p in known})


def _clean_mobile_or_400(raw: Optional[str]) -> Optional[str]:
    """Iter 220 — Mobile-field hygiene: reject emails typed/saved into the
    Mobile No. box and keep only phone characters."""
    p = (raw or "").strip()
    if not p:
        return None
    if "@" in p:
        raise HTTPException(
            status_code=400,
            detail="Mobile No. cannot be an email id — enter a phone number "
                   "(the email goes in the Email field).",
        )
    cleaned = re.sub(r"[^\d+]", "", p)
    if len(re.sub(r"[^\d]", "", cleaned)) < 10:
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit mobile number")
    return cleaned


def _validate_pin_or_400(raw: Optional[str]) -> Optional[str]:
    """Iter 220 — 6-digit PIN validation (returns the clean PIN or None)."""
    p = (raw or "").strip()
    if not p:
        return None
    if not re.fullmatch(r"\d{6}", p):
        raise HTTPException(status_code=400, detail="PIN must be exactly 6 digits")
    return p


def _sanitise_sub_admin(doc: dict) -> dict:
    """Strip sensitive fields before returning a sub-admin to the client."""
    if not doc:
        return doc
    out = {k: v for k, v in doc.items() if k not in (
        "password_hash", "pin_hash",
        "temp_pin_plaintext", "temp_password_plaintext",
    )}
    return out


@api.get("/admin/sub-admin-permission-keys")
async def sub_admin_permission_keys(
    authorization: Optional[str] = Header(None),
):
    """Return the canonical permission-key list so the frontend can render
    checkboxes without hardcoding the list."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    return {"permissions": SUB_ADMIN_PERMISSION_KEYS}


@api.get("/admin/sub-admins")
async def list_sub_admins(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    docs = await db.users.find(
        {"role": "sub_admin"},
        {"_id": 0},
    ).sort("created_at", -1).to_list(500)
    return {"sub_admins": [_sanitise_sub_admin(d) for d in docs]}


@api.post("/admin/sub-admins")
async def create_sub_admin(
    payload: SubAdminCreate,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    name = (payload.name or "").strip()
    email = (payload.email or "").strip().lower()
    phone = _clean_mobile_or_400(payload.phone)
    pin = _validate_pin_or_400(payload.pin)
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required for login")
    if not payload.password or len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    # Uniqueness — reuse the same rules as normal users.
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail=f"A user with email {email} already exists")
    if phone and await db.users.find_one({"phone_e164": phone}):
        raise HTTPException(status_code=409, detail=f"A user with phone {phone} already exists")

    perms = _validate_sub_admin_permissions(payload.permissions or [])
    scope = payload.company_scope or "all"
    company_ids: List[str] = []
    if scope == "restricted":
        company_ids = [c for c in (payload.company_ids or []) if c]
        if not company_ids:
            raise HTTPException(
                status_code=400,
                detail="Restricted scope needs at least one company_id",
            )

    user_id = f"sub_{uuid.uuid4().hex[:12]}"
    doc = {
        "user_id": user_id,
        "role": "sub_admin",
        "name": name,
        "email": email,
        "phone_e164": phone,
        # Iter 220 — mirror into ``phone`` (normalized) so phone + PIN /
        # phone + password logins find the account.
        "phone": _normalise_phone(phone) if phone else None,
        "password_hash": _hash_password(payload.password),
        "password_must_change": True,
        "sub_admin_permissions": perms,
        "sub_admin_company_scope": scope,
        "sub_admin_company_ids": company_ids,
        "menu_rights": {
            str(k): bool(v)
            for k, v in (payload.menu_rights or {}).items()
            if isinstance(k, str) and k.startswith("/")
        },
        "disabled": False,
        "created_at": now_iso(),
        "created_by": admin["user_id"],
        "onboarded": True,
        "approval_status": "approved",
    }
    if pin:
        # Iter 220 — separate 6-digit PIN credential (optional).
        doc["pin_hash"] = _hash_pin(pin)
    await db.users.insert_one(doc)

    from utils.welcome_email import send_admin_welcome_email
    await send_admin_welcome_email(
        name=name, email=email, role_label="Sub Admin",
        password=payload.password,
    )
    return {"ok": True, "sub_admin": _sanitise_sub_admin({k: v for k, v in doc.items() if k != "_id"})}


@api.get("/admin/sub-admins/{user_id}")
async def get_sub_admin(user_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    doc = await db.users.find_one({"user_id": user_id, "role": "sub_admin"}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Sub-admin not found")
    return {"sub_admin": _sanitise_sub_admin(doc)}


@api.patch("/admin/sub-admins/{user_id}")
async def update_sub_admin(
    user_id: str,
    payload: SubAdminUpdate,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    existing = await db.users.find_one({"user_id": user_id, "role": "sub_admin"}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Sub-admin not found")

    updates: dict = {}
    fset = payload.model_fields_set
    if "name" in fset and payload.name is not None:
        n = payload.name.strip()
        if not n:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        updates["name"] = n
    if "email" in fset and payload.email is not None:
        e = payload.email.strip().lower()
        if e and "@" not in e:
            raise HTTPException(status_code=400, detail="Invalid email")
        if e and e != existing.get("email"):
            if await db.users.find_one({"email": e, "user_id": {"$ne": user_id}}):
                raise HTTPException(status_code=409, detail="Email already used")
        updates["email"] = e or None
    if "phone" in fset:
        p = _clean_mobile_or_400(payload.phone)
        if p and p != existing.get("phone_e164"):
            if await db.users.find_one({"phone_e164": p, "user_id": {"$ne": user_id}}):
                raise HTTPException(status_code=409, detail="Phone already used")
        updates["phone_e164"] = p
        updates["phone"] = _normalise_phone(p) if p else None
    if "pin" in fset and payload.pin is not None:
        # Iter 220 — set/replace the separate 6-digit PIN credential.
        _pin = _validate_pin_or_400(payload.pin)
        if _pin:
            updates["pin_hash"] = _hash_pin(_pin)
            updates["pin_fail_count"] = 0
            updates["pin_locked_until"] = None
    if "permissions" in fset and payload.permissions is not None:
        updates["sub_admin_permissions"] = _validate_sub_admin_permissions(payload.permissions)
    if "company_scope" in fset and payload.company_scope is not None:
        updates["sub_admin_company_scope"] = payload.company_scope
    if "company_ids" in fset and payload.company_ids is not None:
        updates["sub_admin_company_ids"] = [c for c in payload.company_ids if c]
    if "disabled" in fset and payload.disabled is not None:
        updates["disabled"] = bool(payload.disabled)
        if payload.disabled:
            updates["disabled_reason"] = "manual"
        else:
            # Iter 157 — re-enable resets the inactivity clock so the
            # auto-disable job doesn't flag the account again immediately.
            updates["disabled_reason"] = None
            updates["auto_disabled_at"] = None
            updates["inactivity_warned_for"] = None
            updates["reactivated_at"] = now_iso()
    if "menu_rights" in fset and payload.menu_rights is not None:
        updates["menu_rights"] = {
            str(k): bool(v)
            for k, v in payload.menu_rights.items()
            if isinstance(k, str) and k.startswith("/")
        }

    resolved_scope = updates.get("sub_admin_company_scope", existing.get("sub_admin_company_scope", "all"))
    resolved_ids = updates.get("sub_admin_company_ids", existing.get("sub_admin_company_ids", []))
    if resolved_scope == "restricted" and not resolved_ids:
        raise HTTPException(status_code=400, detail="Restricted scope needs at least one company_id")

    if updates:
        updates["updated_at"] = now_iso()
        await db.users.update_one({"user_id": user_id}, {"$set": updates})

    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return {"ok": True, "sub_admin": _sanitise_sub_admin(fresh)}


@api.post("/admin/sub-admins/{user_id}/reset-password")
async def reset_sub_admin_password(
    user_id: str,
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    new_pw = (payload or {}).get("password", "")
    if not new_pw or len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    existing = await db.users.find_one({"user_id": user_id, "role": "sub_admin"}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Sub-admin not found")
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


@api.delete("/admin/sub-admins/{user_id}")
async def delete_sub_admin(user_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    existing = await db.users.find_one({"user_id": user_id, "role": "sub_admin"}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Sub-admin not found")
    await db.user_sessions.delete_many({"user_id": user_id})
    await db.users.delete_one({"user_id": user_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Employer portal credentials (EPFO / ESIC / SSO Shram Suvidha) — Iter 58
# ---------------------------------------------------------------------------
# Company admins (and super admins) can store the credentials the firm uses
# on the government labour portals so we can later drive Chrome automation
# to upload ECR + ESIC challans on their behalf. Passwords are encrypted
# at rest with Fernet (see utils/portal_creds).

class PortalCredUpdate(BaseModel):
    """Update a single portal entry. All fields optional — omit to leave
    that portal untouched. Pass ``clear_password=True`` to WIPE a stored
    password. A non-empty ``password`` string sets a new one."""
    portal: Literal["epfo", "esic", "shram_suvidha"]
    username: Optional[str] = None
    password: Optional[str] = None
    notes: Optional[str] = None
    clear_password: Optional[bool] = None


def _company_scope_check(user: dict, company_id: str) -> None:
    """Auth guard shared by portal-cred endpoints. Super admin sees all;
    company admin only their own company; sub_admins with 'companies:write'
    + matching company scope."""
    role = user.get("role")
    if role == "super_admin":
        return
    if role == "company_admin":
        if user.get("company_id") == company_id:
            return
        raise HTTPException(status_code=403, detail="Not authorised for this company")
    if role == "sub_admin":
        if not sub_admin_can_touch_company(user, company_id):
            raise HTTPException(status_code=403, detail="Not authorised for this company")
        if "companies:write" in (user.get("sub_admin_permissions") or []):
            return
        raise HTTPException(status_code=403, detail="Missing 'companies:write' permission")
    raise HTTPException(status_code=403, detail="Forbidden")


@api.get("/admin/companies/{company_id}/portal-credentials")
async def get_portal_credentials(
    company_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return the masked credentials for a company. Passwords are never
    returned in plaintext — only ``has_password: bool``."""
    from utils.portal_creds import sanitise_stored, PORTAL_KEYS, PORTAL_LABELS
    user = await get_user_from_token(authorization)
    _company_scope_check(user, company_id)
    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "portal_credentials": 1},
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return {
        "company_id": company_id,
        "company_name": company.get("name"),
        "portals": sanitise_stored(company.get("portal_credentials") or {}),
        "known_portals": PORTAL_KEYS,
        "portal_labels": PORTAL_LABELS,
    }


@api.patch("/admin/companies/{company_id}/portal-credentials")
async def update_portal_credentials(
    company_id: str,
    payload: PortalCredUpdate,
    authorization: Optional[str] = Header(None),
):
    """Update a single portal's username / password / notes."""
    from utils.portal_creds import (
        encrypt_password, sanitise_stored,
        PORTAL_KEYS, PORTAL_LABELS,
    )
    user = await get_user_from_token(authorization)
    _company_scope_check(user, company_id)
    if payload.portal not in PORTAL_KEYS:
        raise HTTPException(status_code=400, detail="Unknown portal")
    # Include a required field ("name") in the projection so we never get
    # back an empty {} which would falsely trigger the "not found" branch.
    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "portal_credentials": 1},
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    existing = (company.get("portal_credentials") or {}).get(payload.portal) or {}
    updates = dict(existing)
    if payload.username is not None:
        updates["username"] = payload.username.strip()[:200]
    if payload.notes is not None:
        updates["notes"] = payload.notes.strip()[:400]
    if payload.clear_password:
        updates.pop("password_cipher", None)
    elif payload.password is not None and payload.password != "":
        if len(payload.password) > 400:
            raise HTTPException(status_code=400, detail="Password too long")
        updates["password_cipher"] = encrypt_password(payload.password)
    updates["updated_at"] = now_iso()
    updates["updated_by"] = user["user_id"]

    await db.companies.update_one(
        {"company_id": company_id},
        {"$set": {f"portal_credentials.{payload.portal}": updates}},
    )
    fresh = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "portal_credentials": 1},
    )
    return {
        "ok": True,
        "company_id": company_id,
        "company_name": (fresh or {}).get("name"),
        "portals": sanitise_stored((fresh or {}).get("portal_credentials") or {}),
        "portal_labels": PORTAL_LABELS,
    }


# ---------------------------------------------------------------------------
# Employer (Company Admin) access rights — Iter 58
# ---------------------------------------------------------------------------
# Super admin decides which parts of the Company Admin portal each firm's
# admins can access. Stored as `employer_permissions: [str]` on the
# companies doc. An empty / missing list means "all features enabled"
# (backward-compatible for existing firms).

class EmployerAccessUpdate(BaseModel):
    """Replace the entire employer_permissions array on a company. Pass
    ``permissions=None`` to signal 'all features' (empty array wipes to
    zero features, so please be intentional)."""
    permissions: Optional[List[str]] = None
    # Iter 93 — per-sidebar-button visibility map {route: bool}. Missing
    # route == allowed. Pass {} to allow everything again.
    menu_rights: Optional[dict] = None


def _validate_employer_permissions(perms: Optional[List[str]]) -> List[str]:
    if not perms:
        return []
    known = set(EMPLOYER_PERMISSION_KEYS)
    return sorted({p for p in perms if p in known})


@api.get("/admin/employer-permission-keys")
async def employer_permission_keys(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    return {"permissions": EMPLOYER_PERMISSION_KEYS}


@api.get("/admin/companies/{company_id}/access-rights")
async def get_employer_access_rights(
    company_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return the current employer_permissions for a company. Super admin
    can read for any company; company admin sees only their own; sub_admin
    with 'companies:read' + matching scope."""
    user = await get_user_from_token(authorization)
    _company_scope_check(user, company_id)  # write scope; read is stricter than needed but safe
    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "employer_permissions": 1, "employer_menu_rights": 1},
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    perms = company.get("employer_permissions")
    return {
        "company_id": company_id,
        "company_name": company.get("name"),
        "permissions": perms or [],
        "all_features_enabled": not perms,   # empty array == everything on
        "known_permissions": EMPLOYER_PERMISSION_KEYS,
        # Iter 93 — per-sidebar-button gating. Missing key == allowed.
        "menu_rights": company.get("employer_menu_rights") or {},
    }


@api.patch("/admin/companies/{company_id}/access-rights")
async def set_employer_access_rights(
    company_id: str,
    payload: EmployerAccessUpdate,
    authorization: Optional[str] = Header(None),
):
    """Super admin only — replace the employer_permissions array. Pass
    ``permissions=None`` to reset the field to 'all features enabled'."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "name": 1})
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if payload.permissions is None:
        await db.companies.update_one(
            {"company_id": company_id},
            {"$unset": {"employer_permissions": ""}, "$set": {"employer_permissions_updated_at": now_iso()}},
        )
        perms: List[str] = []
    else:
        perms = _validate_employer_permissions(payload.permissions)
        await db.companies.update_one(
            {"company_id": company_id},
            {"$set": {
                "employer_permissions": perms,
                "employer_permissions_updated_at": now_iso(),
                "employer_permissions_updated_by": admin["user_id"],
            }},
        )
    # Iter 93 — per-sidebar-button map. Only touched when the client sends it.
    if payload.menu_rights is not None:
        clean = {
            str(k): bool(v)
            for k, v in payload.menu_rights.items()
            if isinstance(k, str) and k.startswith("/")
        }
        await db.companies.update_one(
            {"company_id": company_id},
            {"$set": {"employer_menu_rights": clean}},
        )
    fresh = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "employer_menu_rights": 1},
    )
    return {
        "ok": True,
        "company_id": company_id,
        "company_name": company.get("name"),
        "permissions": perms,
        "all_features_enabled": not perms,
        "menu_rights": (fresh or {}).get("employer_menu_rights") or {},
    }
