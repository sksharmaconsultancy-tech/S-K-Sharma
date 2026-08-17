"""Iter 585 — RBAC Phase 1 routes: Department Master, User Data Scope
(branch/department) assignment, and Access Preview.

All authorization decisions delegate to shared/authz.py (single source of
truth). Scope changes and Access Preview views are audit-logged as CRITICAL
security events into db.activity_log (Users Log Report)."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import db, get_user_from_token, require_role, require_super_admin_strict
from shared.authz import get_effective_access

router = APIRouter(prefix="/api")

# Modules shown in the Access Preview / Roles & Permissions matrix.
# Iter 591 (user request) — the FULL catalog: every module × every action
# (View/Add/Edit/Delete/Export/Approve) is visible and editable.
MODULE_LABELS = {
    "employees": "Employee Master",
    "attendance_policy": "Attendance Policy",
    "attendance_review": "Attendance Review & Reports",
    "punch_approvals": "Punch / Shift Approvals",
    "salary_process": "Salary Processing (Actual)",
    "compliance_salary": "Compliance Salary",
    "compliance": "PF / ESIC / Challans",
    "reports": "Reports & Downloads",
    "masters": "General Masters",
    "companies": "Firm Master",
    "biometric_devices": "Biometric Devices",
    "portal_credentials": "Portal Credentials",
    "company_requests": "Client Requests",
    "tickets": "Tickets / Support",
    "messages": "Messages",
    "user_management": "User Management",
}
PREVIEW_MODULES = list(MODULE_LABELS.keys())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _audit(admin: dict, action: str, detail: dict) -> None:
    try:
        await db.activity_log.insert_one({
            "log_id": f"al_{uuid.uuid4().hex[:12]}",
            "user_id": admin.get("user_id"),
            "user_name": admin.get("name"),
            "role": admin.get("role"),
            "action": action,
            "module": "access_management",
            "severity": "CRITICAL" if action != "ACCESS_PREVIEW" else "INFO",
            "detail": detail,
            "at": _now(),
        })
    except Exception:
        pass


# ── DEPARTMENT MASTER ──────────────────────────────────────────────────────
@router.get("/admin/departments")
async def list_departments(
    company_id: str = Query(...),
    branch_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    from shared.authz import firm_ok
    if not firm_ok(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm outside your scope")
    q: Dict[str, Any] = {"company_id": company_id}
    if branch_id:
        q["branch_id"] = branch_id
    deps = await db.departments.find(q, {"_id": 0}).sort("name", 1).to_list(500)
    return {"departments": deps}


@router.post("/admin/departments")
async def create_department(payload: dict = Body(...),
                            authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    cid = str(payload.get("company_id") or "").strip()
    name = str(payload.get("name") or "").strip()
    branch_id = str(payload.get("branch_id") or "").strip() or None
    from shared.authz import firm_ok
    if not cid or not firm_ok(admin, cid):
        raise HTTPException(status_code=403, detail="Firm outside your scope")
    if not name:
        raise HTTPException(status_code=400, detail="Department name required")
    if branch_id:
        br = await db.branches.find_one({"branch_id": branch_id, "company_id": cid})
        if not br:
            raise HTTPException(status_code=400,
                                detail="Branch does not belong to this firm")
    dup = await db.departments.find_one(
        {"company_id": cid, "branch_id": branch_id,
         "name": {"$regex": f"^{name}$", "$options": "i"}})
    if dup:
        raise HTTPException(status_code=409, detail="Department already exists")
    doc = {"department_id": f"dept_{uuid.uuid4().hex[:10]}", "company_id": cid,
           "branch_id": branch_id, "name": name, "status": "active",
           "created_by": admin["user_id"], "created_at": _now()}
    await db.departments.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "department": doc}


@router.post("/admin/departments/migrate-from-employees")
async def migrate_departments(payload: dict = Body(default={}),
                              authorization: Optional[str] = Header(None)):
    """Build the Department Master from existing free-text employee
    departments and stamp department_id on each employee (no data deleted)."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    cid = payload.get("company_id")
    q: Dict[str, Any] = {"role": "employee",
                         "department": {"$nin": [None, ""]}}
    if cid:
        q["company_id"] = cid
    created = stamped = 0
    async for e in db.users.find(q, {"user_id": 1, "company_id": 1,
                                     "department": 1, "branch_id": 1,
                                     "department_id": 1}):
        name = str(e.get("department") or "").strip()
        if not name:
            continue
        dep = await db.departments.find_one(
            {"company_id": e["company_id"],
             "name": {"$regex": f"^{name}$", "$options": "i"}})
        if not dep:
            dep = {"department_id": f"dept_{uuid.uuid4().hex[:10]}",
                   "company_id": e["company_id"], "branch_id": None,
                   "name": name, "status": "active",
                   "created_by": "migration", "created_at": _now()}
            await db.departments.insert_one(dep)
            created += 1
        if e.get("department_id") != dep["department_id"]:
            await db.users.update_one({"user_id": e["user_id"]},
                                      {"$set": {"department_id": dep["department_id"]}})
            stamped += 1
    await _audit(admin, "DEPARTMENT_MIGRATION",
                 {"company_id": cid, "created": created, "stamped": stamped})
    return {"ok": True, "departments_created": created,
            "employees_stamped": stamped}


# ── USER DATA SCOPE (branch / department) ──────────────────────────────────
@router.patch("/admin/access/user-scope")
async def set_user_scope(payload: dict = Body(...),
                         authorization: Optional[str] = Header(None)):
    """Super Admin assigns branch/department scope to a sub-admin or client
    user. Validates every id against the target user's firm scope; takes
    effect immediately (evaluated per-request, never cached)."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    uid = str(payload.get("user_id") or "").strip()
    target = await db.users.find_one({"user_id": uid})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") not in ("sub_admin", "company_admin"):
        raise HTTPException(status_code=400,
                            detail="Scope applies to sub-admins and client users only")
    updates: Dict[str, Any] = {}
    old: Dict[str, Any] = {}
    # firm ids the target may reach — scope ids must belong to these firms.
    if target["role"] == "sub_admin" and (target.get("sub_admin_company_scope") or "all") != "all":
        firm_ids = target.get("sub_admin_company_ids") or []
    elif target["role"] == "company_admin":
        firm_ids = [target.get("company_id")]
    else:
        firm_ids = None  # all firms
    for key, coll, id_field in (("branch_scope", db.branches, "branch_id"),
                                ("department_scope", db.departments, "department_id")):
        if key not in payload:
            continue
        sc = payload[key]
        if not isinstance(sc, dict):
            raise HTTPException(status_code=400, detail=f"{key} must be an object")
        if sc.get("all", True):
            clean = {"all": True, "ids": []}
        else:
            ids = [str(x) for x in (sc.get("ids") or [])]
            fq: Dict[str, Any] = {id_field: {"$in": ids}}
            if firm_ids is not None:
                fq["company_id"] = {"$in": firm_ids}
            found = await coll.find(fq, {"_id": 0, id_field: 1}).to_list(1000)
            found_ids = {f[id_field] for f in found}
            bad = [i for i in ids if i not in found_ids]
            if bad:
                raise HTTPException(
                    status_code=400,
                    detail=f"{key}: id(s) outside the user's firm scope "
                           f"or non-existent: {bad}")
            clean = {"all": False, "ids": ids}
        old[key] = target.get(key)
        updates[key] = clean
    if not updates:
        raise HTTPException(status_code=400,
                            detail="Pass branch_scope and/or department_scope")
    await db.users.update_one({"user_id": uid}, {"$set": updates})
    await _audit(admin, "DATA_SCOPE_CHANGED",
                 {"target_user_id": uid, "target_name": target.get("name"),
                  "old": old, "new": updates})
    return {"ok": True, "user_id": uid, **updates}


# ── ACCESS PREVIEW ─────────────────────────────────────────────────────────
@router.get("/admin/access-preview/users")
async def preview_user_search(
    q: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    f: Dict[str, Any] = {"role": {"$in": ["sub_admin", "company_admin", "employee"]}}
    if role:
        f["role"] = role
    if company_id:
        f["company_id"] = company_id
    if q:
        f["$or"] = [{"name": {"$regex": q, "$options": "i"}},
                    {"email": {"$regex": q, "$options": "i"}},
                    {"phone": {"$regex": q, "$options": "i"}}]
    users = await db.users.find(
        f, {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1,
            "company_id": 1, "active": 1}).sort("name", 1).to_list(50)
    return {"users": users}


@router.get("/admin/access-preview/{user_id}")
async def access_preview(user_id: str,
                         authorization: Optional[str] = Header(None)):
    """Read-only effective access for any user — calculated by the SAME
    shared/authz.py engine that protects the APIs (Preview == reality)."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    out = await get_effective_access(db, target, PREVIEW_MODULES)
    out["module_labels"] = MODULE_LABELS
    # resolve branch/department names for display
    for key, coll, id_field in (("branch_scope", db.branches, "branch_id"),
                                ("department_scope", db.departments, "department_id")):
        ids = out[key].get(f"{id_field}s")
        if ids:
            docs = await coll.find({id_field: {"$in": ids}},
                                   {"_id": 0, id_field: 1, "name": 1,
                                    "company_id": 1}).to_list(500)
            out[key]["items"] = docs
    await _audit(admin, "ACCESS_PREVIEW",
                 {"viewed_user_id": user_id, "viewed_name": target.get("name"),
                  "viewed_role": target.get("role")})
    return out


# ── Iter 586 — Granular permission editor + sensitive-data migration ───────
GRANULAR_ACTIONS = ["view", "add", "edit", "delete", "export", "approve"]


@router.patch("/admin/access/user-permissions")
async def set_user_permissions(payload: dict = Body(...),
                               authorization: Optional[str] = Header(None)):
    """Super Admin sets the FULL granular permission list for a sub-admin or
    client (staff) user. Format: ["employees:view", "salary_process:export",
    "sensitive_data:view", …]. Legacy read/write keys are also accepted.
    Change is audited as CRITICAL (old vs new)."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    uid = str(payload.get("user_id") or "").strip()
    perms = payload.get("permissions")
    if not isinstance(perms, list):
        raise HTTPException(status_code=400, detail="permissions must be a list")
    clean = sorted({str(p).strip() for p in perms
                    if ":" in str(p) and len(str(p)) < 80})
    target = await db.users.find_one({"user_id": uid})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") == "sub_admin":
        field, old = "sub_admin_permissions", target.get("sub_admin_permissions")
    elif target.get("role") == "company_admin" and target.get("is_company_staff"):
        field, old = "staff_permissions", target.get("staff_permissions")
    else:
        raise HTTPException(status_code=400,
                            detail="Granular permissions apply to sub-admins "
                                   "and client staff users only")
    await db.users.update_one({"user_id": uid}, {"$set": {field: clean}})
    await _audit(admin, "PERMISSION_CHANGED",
                 {"target_user_id": uid, "target_name": target.get("name"),
                  "field": field, "old": old, "new": clean})
    return {"ok": True, "user_id": uid, "permissions": clean}


@router.post("/admin/access/migrate-sensitive-permission")
async def migrate_sensitive_permission(authorization: Optional[str] = Header(None)):
    """One-time idempotent backward-compat migration: sub-admins / client
    staff who could already see employee data (employees:read|write|view)
    keep seeing UNMASKED sensitive values by receiving sensitive_data:view.
    Super Admin can revoke it per user afterwards via user-permissions."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    granted = 0
    for field, rq in (("sub_admin_permissions", {"role": "sub_admin"}),
                      ("staff_permissions", {"role": "company_admin",
                                             "is_company_staff": True})):
        async for u in db.users.find({**rq, field: {"$exists": True}},
                                     {"user_id": 1, field: 1}):
            perms = u.get(field) or []
            if "sensitive_data:view" in perms:
                continue
            if any(p.startswith("employees:") for p in perms):
                await db.users.update_one(
                    {"user_id": u["user_id"]},
                    {"$addToSet": {field: "sensitive_data:view"}})
                granted += 1
    await _audit(admin, "PERMISSION_CHANGED",
                 {"migration": "sensitive_data:view backward-compat",
                  "granted": granted})
    return {"ok": True, "granted": granted}


@router.get("/admin/export-history")
async def export_history(
    company_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="SUCCESS | DENIED"),
    authorization: Optional[str] = Header(None),
):
    """Iter 587 — Export audit history (DATA_EXPORT / EXPORT_DENIED)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    q: Dict[str, Any] = {"action": {"$in": ["DATA_EXPORT", "EXPORT_DENIED"]}}
    if status == "SUCCESS":
        q["action"] = "DATA_EXPORT"
    elif status == "DENIED":
        q["action"] = "EXPORT_DENIED"
    if admin["role"] == "company_admin":
        q["detail.company_id"] = admin.get("company_id")
    elif company_id:
        from shared.authz import firm_ok
        if not firm_ok(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm outside your scope")
        q["detail.company_id"] = company_id
    logs = await db.activity_log.find(q, {"_id": 0}).sort("at", -1).to_list(200)
    return {"exports": logs}
