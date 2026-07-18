"""Company Roles & Permission Matrix (RBAC Phase 1).

Company-level staff roles (HR Manager, Payroll Manager, Compliance
Officer, Finance, Attendance Manager, Department Head + custom) with a
checkbox permission matrix. Staff users are stored with
``role="company_staff"`` + ``company_role_id`` and are NORMALIZED to a
firm-scoped ``company_admin`` at token-resolution time (server.py) with
``is_company_staff=True`` and ``staff_permissions=[...]`` so every
existing endpoint keeps its company scoping unchanged. Super/Sub admin
behavior is untouched.
"""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel

from server import (  # noqa: E402
    db,
    get_user_from_token,
    now_iso,
    EMPLOYER_PERMISSION_KEYS,
    _hash_password,
    _validate_password_strength,
    sub_admin_can_touch_company,
)

router = APIRouter(prefix="/api/admin", tags=["company-roles"])

# Friendly permission catalog for the matrix UI. Each module maps onto the
# existing :read/:write keys already enforced across the backend.
PERMISSION_CATALOG = [
    {"module": "Employee Master", "read": "employees:read", "write": "employees:write"},
    {"module": "Attendance Policy", "read": "attendance_policy:read", "write": "attendance_policy:write"},
    {"module": "Punch Approvals", "read": "punch_approvals:read", "write": "punch_approvals:write"},
    {"module": "Attendance Review", "read": "attendance_review:read", "write": "attendance_review:write"},
    {"module": "Biometric Devices", "read": "biometric_devices:read", "write": "biometric_devices:write"},
    {"module": "Salary Process (Actual)", "read": "salary_process:read", "write": "salary_process:write"},
    {"module": "Salary Process (Compliance)", "read": "compliance_salary:read", "write": "compliance_salary:write"},
    {"module": "Messages", "read": "messages:read", "write": "messages:write"},
    {"module": "Tickets", "read": "tickets:read", "write": "tickets:write"},
    {"module": "Portal Credentials", "read": "portal_credentials:read", "write": "portal_credentials:write"},
    {"module": "Statutory Registration (UAN/ESIC)", "read": "registrations:read", "write": "registrations:write"},
]
KNOWN_KEYS = set(EMPLOYER_PERMISSION_KEYS)

DEFAULT_ROLES: List[Dict[str, Any]] = [
    {"name": "HR Manager", "permissions": [
        "employees:read", "employees:write", "attendance_policy:read", "attendance_policy:write",
        "punch_approvals:read", "punch_approvals:write", "messages:read", "messages:write",
        "tickets:read", "tickets:write"]},
    {"name": "Payroll Manager", "permissions": [
        "employees:read", "salary_process:read", "salary_process:write", "compliance_salary:read"]},
    {"name": "Compliance Officer", "permissions": [
        "employees:read", "compliance_salary:read", "compliance_salary:write"]},
    {"name": "Finance", "permissions": [
        "salary_process:read", "compliance_salary:read"]},
    {"name": "Attendance Manager", "permissions": [
        "employees:read", "attendance_review:read", "attendance_review:write",
        "punch_approvals:read", "punch_approvals:write", "biometric_devices:read", "biometric_devices:write"]},
    {"name": "Department Head", "permissions": [
        "employees:read", "punch_approvals:read", "attendance_review:read"]},
]


async def _role_manager(authorization, company_id: Optional[str]) -> tuple:
    """Only REAL admins may manage roles/staff: super_admin, sub_admin
    (scoped), or a genuine company_admin (never company_staff)."""
    admin = await get_user_from_token(authorization)
    role = admin.get("role")
    if admin.get("is_company_staff"):
        raise HTTPException(status_code=403, detail="Staff accounts cannot manage roles")
    if role == "company_admin":
        company_id = admin.get("company_id")
        if not company_id:
            raise HTTPException(status_code=400, detail="No firm assigned")
    elif role == "sub_admin":
        if company_id and not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm outside your scope")
    elif role != "super_admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return admin, company_id


def _clean_perms(perms: List[str]) -> List[str]:
    return [p for p in (perms or []) if p in KNOWN_KEYS]


@router.get("/company-roles/catalog")
async def permission_catalog(authorization: Optional[str] = Header(None)):
    await get_user_from_token(authorization)
    return {"catalog": PERMISSION_CATALOG}


@router.get("/company-roles")
async def list_company_roles(
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    admin, cid = await _role_manager(authorization, company_id)
    roles = await db.company_roles.find({"company_id": cid}, {"_id": 0}).sort("name", 1).to_list(100)
    counts: Dict[str, int] = {}
    async for u in db.users.find({"role": "company_staff", "company_id": cid}, {"_id": 0, "company_role_id": 1}):
        rid = u.get("company_role_id") or ""
        counts[rid] = counts.get(rid, 0) + 1
    for r in roles:
        r["staff_count"] = counts.get(r["role_id"], 0)
    return {"roles": roles}


class RoleCreate(BaseModel):
    company_id: Optional[str] = None
    name: Optional[str] = None
    permissions: List[str] = []
    seed_defaults: bool = False


@router.post("/company-roles")
async def create_company_role(payload: RoleCreate, authorization: Optional[str] = Header(None)):
    admin, cid = await _role_manager(authorization, payload.company_id)
    if payload.seed_defaults:
        created = 0
        for d in DEFAULT_ROLES:
            exists = await db.company_roles.find_one({"company_id": cid, "name": d["name"]})
            if exists:
                continue
            await db.company_roles.insert_one({
                "role_id": f"crole_{uuid.uuid4().hex[:12]}",
                "company_id": cid, "name": d["name"],
                "permissions": _clean_perms(d["permissions"]),
                "is_default": True, "created_at": now_iso(), "created_by": admin["user_id"],
            })
            created += 1
        return {"ok": True, "created": created}
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Role name is required")
    if await db.company_roles.find_one({"company_id": cid, "name": name}):
        raise HTTPException(status_code=400, detail="A role with this name already exists")
    doc = {
        "role_id": f"crole_{uuid.uuid4().hex[:12]}",
        "company_id": cid, "name": name,
        "permissions": _clean_perms(payload.permissions),
        "is_default": False, "created_at": now_iso(), "created_by": admin["user_id"],
    }
    await db.company_roles.insert_one(doc)
    return {"ok": True, "role": {k: v for k, v in doc.items() if k != "_id"}}


@router.patch("/company-roles/{role_id}")
async def update_company_role(
    role_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    r = await db.company_roles.find_one({"role_id": role_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Role not found")
    admin, cid = await _role_manager(authorization, r["company_id"])
    updates: Dict[str, Any] = {}
    if "name" in payload:
        nm = (payload["name"] or "").strip()
        if not nm:
            raise HTTPException(status_code=400, detail="Role name is required")
        updates["name"] = nm
    if "permissions" in payload:
        updates["permissions"] = _clean_perms(payload["permissions"])
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    updates["updated_at"] = now_iso()
    updates["updated_by"] = admin["user_id"]
    await db.company_roles.update_one({"role_id": role_id}, {"$set": updates})
    fresh = await db.company_roles.find_one({"role_id": role_id}, {"_id": 0})
    return {"ok": True, "role": fresh}


@router.delete("/company-roles/{role_id}")
async def delete_company_role(role_id: str, authorization: Optional[str] = Header(None)):
    r = await db.company_roles.find_one({"role_id": role_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Role not found")
    await _role_manager(authorization, r["company_id"])
    n = await db.users.count_documents({"role": "company_staff", "company_role_id": role_id})
    if n:
        raise HTTPException(status_code=400, detail=f"{n} staff user(s) still assigned to this role")
    await db.company_roles.delete_one({"role_id": role_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Staff users (minimal management — full User Management screen is Phase 2)
# ---------------------------------------------------------------------------
class StaffCreate(BaseModel):
    company_id: Optional[str] = None
    name: str
    email: str
    phone: Optional[str] = None
    password: str
    role_id: str


@router.get("/company-staff")
async def list_staff(company_id: Optional[str] = None, authorization: Optional[str] = Header(None)):
    admin, cid = await _role_manager(authorization, company_id)
    users = await db.users.find(
        {"role": "company_staff", "company_id": cid},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "phone": 1,
         "company_role_id": 1, "disabled": 1, "password_last_login_at": 1, "created_at": 1},
    ).sort("name", 1).to_list(200)
    roles = {r["role_id"]: r["name"] async for r in db.company_roles.find({"company_id": cid}, {"_id": 0})}
    for u in users:
        u["role_name"] = roles.get(u.get("company_role_id") or "", "—")
    return {"staff": users}


@router.post("/company-staff")
async def create_staff(payload: StaffCreate, authorization: Optional[str] = Header(None)):
    admin, cid = await _role_manager(authorization, payload.company_id)
    email = (payload.email or "").strip().lower()
    name = (payload.name or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required")
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    role = await db.company_roles.find_one({"role_id": payload.role_id, "company_id": cid}, {"_id": 0})
    if not role:
        raise HTTPException(status_code=404, detail="Role not found for this firm")
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    _validate_password_strength(payload.password)
    doc = {
        "user_id": f"user_{uuid.uuid4().hex[:12]}",
        "role": "company_staff",
        "company_id": cid,
        "company_role_id": payload.role_id,
        "name": name,
        "email": email,
        "phone": (payload.phone or "").strip() or None,
        "password_hash": _hash_password(payload.password),
        "password_set_at": now_iso(),
        "disabled": False,
        "created_at": now_iso(),
        "created_by": admin["user_id"],
    }
    await db.users.insert_one(doc)
    return {"ok": True, "staff": {k: doc[k] for k in
            ("user_id", "name", "email", "phone", "company_role_id")}}


@router.patch("/company-staff/{user_id}")
async def update_staff(
    user_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    u = await db.users.find_one({"user_id": user_id, "role": "company_staff"}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Staff user not found")
    admin, cid = await _role_manager(authorization, u["company_id"])
    updates: Dict[str, Any] = {}
    if "role_id" in payload:
        role = await db.company_roles.find_one({"role_id": payload["role_id"], "company_id": cid})
        if not role:
            raise HTTPException(status_code=404, detail="Role not found for this firm")
        updates["company_role_id"] = payload["role_id"]
    if "disabled" in payload:
        updates["disabled"] = bool(payload["disabled"])
    if "name" in payload and (payload["name"] or "").strip():
        updates["name"] = payload["name"].strip()
    if "password" in payload and payload["password"]:
        _validate_password_strength(payload["password"])
        updates["password_hash"] = _hash_password(payload["password"])
        updates["password_set_at"] = now_iso()
        updates["password_set_by"] = admin["user_id"]
        updates["password_fail_count"] = 0
        updates["password_locked_until"] = None
        # Revoke existing sessions so old credentials can't keep a session alive
        await db.user_sessions.delete_many({"user_id": user_id})
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    await db.users.update_one({"user_id": user_id}, {"$set": updates})
    return {"ok": True}


@router.delete("/company-staff/{user_id}")
async def delete_staff(user_id: str, authorization: Optional[str] = Header(None)):
    u = await db.users.find_one({"user_id": user_id, "role": "company_staff"}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Staff user not found")
    await _role_manager(authorization, u["company_id"])
    await db.user_sessions.delete_many({"user_id": user_id})
    await db.users.delete_one({"user_id": user_id})
    return {"ok": True}
