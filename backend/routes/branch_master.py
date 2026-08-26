"""Iter 737 — BRANCH MASTER (complete enhancement, user 25-section spec).

Single source of truth stays ``db.branches`` (same collection used by the
standalone Branches screen, geofence punching, branch-management hub and
branch-extras compliance reports — NO duplicate branch data).

This module ONLY adds master-data fields + mapping/config sections and
read-only dashboards built from EXISTING system data. It does NOT touch:
attendance calculation, duty hours, compliance salary, actual salary,
F&F math, or any report calculation engine.

New nested config sections stored on the branch document:
  * compliance_config  — PT / LWF / Min-Wage / PF / ESIC / Establishment
  * payroll_config     — branch-level payroll DEFAULTS (mapping only)
  * attendance_config  — branch-level attendance DEFAULTS
                         (cross_midnight defaults to True for NEW branches)

Employee ⇄ branch mapping reuses users.home_branch_id and the existing
``branch_transfers`` collection (effective-dated, history never rewritten
— same lazy applier as routes/branch_management.py).
Documents live in ``branch_documents`` (base64, replaced docs kept as
history — mirrors the firm compliance-doc architecture).
Audit trail goes to the existing ``branch_audit`` collection with
field-level old → new values.
"""
import base64
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
)
from routes.branch_management import _apply_due_transfers  # noqa: E402

router = APIRouter(prefix="/api/admin/branch-master", tags=["branch-master"])

_ADMIN_ROLES = ["super_admin", "sub_admin", "company_admin"]

BRANCH_TYPES = ["Head Office", "Branch", "Factory", "Site",
                "Warehouse", "Remote Office", "Other"]

DOC_TYPES = ["Shops & Establishment Certificate", "Labour License",
             "PF Registration", "ESIC Registration", "PT Registration",
             "LWF Registration", "Factory License", "Rent Agreement", "Other"]

# Flat editable fields (top-level on the branch doc).
_BASIC_FIELDS = ("name", "code", "branch_type", "active", "manager_name",
                 "contact_person", "mobile", "email")
_ADDR_FIELDS = ("address1", "address2", "area", "city", "district",
                "state", "pin_code", "country")
_GPS_FIELDS = ("office_lat", "office_lng", "geofence_enabled",
               "geofence_radius_m", "allow_punch_inside", "gps_accuracy_m")
_CONFIG_SECTIONS = ("compliance_config", "payroll_config", "attendance_config")

_ALL_FLAT = _BASIC_FIELDS + _ADDR_FIELDS + _GPS_FIELDS


def _ist_today() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


async def _gate(authorization: Optional[str], company_id: Optional[str]) -> tuple[dict, str]:
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    cid = admin.get("company_id") if admin["role"] == "company_admin" else company_id
    if not cid:
        raise HTTPException(status_code=400, detail="company_id required")
    return admin, cid


async def _get_branch(branch_id: str, admin: dict) -> dict:
    b = await db.branches.find_one({"branch_id": branch_id}, {"_id": 0})
    if not b:
        raise HTTPException(status_code=404, detail="Branch not found")
    if admin["role"] == "company_admin" and b.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your branch")
    # Branch RBAC (existing framework — sub-admins restricted to branches).
    scope = admin.get("branch_admin_branch_ids") or []
    if scope and branch_id not in [str(s) for s in scope]:
        raise HTTPException(status_code=403, detail="Branch not in your scope")
    return b


def _validate(patch: Dict[str, Any]) -> None:
    """Master-data validation with clear messages."""
    if "name" in patch and not str(patch["name"] or "").strip():
        raise HTTPException(status_code=400, detail="Branch Name is required")
    if patch.get("branch_type") and patch["branch_type"] not in BRANCH_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"Branch Type must be one of: {', '.join(BRANCH_TYPES)}")
    pin = str(patch.get("pin_code") or "").strip()
    if pin and not re.fullmatch(r"\d{6}", pin):
        raise HTTPException(status_code=400, detail="PIN Code must be exactly 6 digits")
    email = str(patch.get("email") or "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail="Branch Email is not a valid email address")
    if "office_lat" in patch and patch["office_lat"] is not None:
        try:
            lat = float(patch["office_lat"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Latitude must be a number")
        if not -90 <= lat <= 90:
            raise HTTPException(status_code=400, detail="Latitude must be between -90 and 90")
    if "office_lng" in patch and patch["office_lng"] is not None:
        try:
            lng = float(patch["office_lng"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Longitude must be a number")
        if not -180 <= lng <= 180:
            raise HTTPException(status_code=400, detail="Longitude must be between -180 and 180")
    if "geofence_radius_m" in patch and patch["geofence_radius_m"] is not None:
        try:
            rad = float(patch["geofence_radius_m"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Geofence radius must be a number")
        if rad <= 0:
            raise HTTPException(status_code=400, detail="Geofence radius must be positive")


async def _check_code_unique(code: str, company_id: str, exclude_branch_id: Optional[str]) -> None:
    q: dict = {"code": code,
               "$or": [{"company_id": company_id}, {"linked_company_ids": company_id}]}
    if exclude_branch_id:
        q["branch_id"] = {"$ne": exclude_branch_id}
    dup = await db.branches.find_one(q, {"_id": 0, "branch_id": 1, "name": 1})
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"Branch Code '{code}' is already used by '{dup.get('name')}' in this firm")


async def _audit(admin: dict, branch_id: str, action: str,
                 changes: List[dict]) -> None:
    if not changes:
        return
    await db.branch_audit.insert_one({
        "audit_id": f"bra_{uuid.uuid4().hex[:10]}",
        "action": action, "branch_id": branch_id,
        "by": admin["user_id"], "by_name": admin.get("name") or admin.get("email"),
        "at": now_iso(), "changes": changes,
    })


def _diff(old: dict, patch: dict) -> List[dict]:
    out = []
    for k, v in patch.items():
        if k in ("updated_at",):
            continue
        ov = old.get(k)
        if isinstance(v, dict) and isinstance(ov, dict):
            for sk, sv in v.items():
                if ov.get(sk) != sv:
                    out.append({"field": f"{k}.{sk}", "old": ov.get(sk), "new": sv})
        elif ov != v:
            out.append({"field": k, "old": ov, "new": v})
    return out


# ---------------------------------------------------------------- list
@router.get("/list")
async def bm_list(company_id: Optional[str] = Query(None),
                  search: Optional[str] = Query(None),
                  status: Optional[str] = Query(None),      # active|inactive
                  state: Optional[str] = Query(None),
                  branch_type: Optional[str] = Query(None),
                  authorization: Optional[str] = Header(None)):
    """Branch list + cached-cheap summary counts (employees / present /
    absent today). One users query + one attendance query — no per-branch
    API calls."""
    admin, cid = await _gate(authorization, company_id)
    q: dict = {"$or": [{"company_id": cid}, {"linked_company_ids": cid}]}
    branches = await db.branches.find(q, {"_id": 0}).sort("created_at", 1).to_list(500)
    scope = admin.get("branch_admin_branch_ids") or []
    if scope:
        scope = [str(s) for s in scope]
        branches = [b for b in branches if b["branch_id"] in scope]
    # server-side filters
    if status in ("active", "inactive"):
        want = status == "active"
        branches = [b for b in branches if bool(b.get("active", True)) == want]
    if state:
        branches = [b for b in branches if (b.get("state") or "") == state]
    if branch_type:
        branches = [b for b in branches if (b.get("branch_type") or "") == branch_type]
    if search:
        s = search.strip().lower()
        branches = [b for b in branches if s in (b.get("name") or "").lower()
                    or s in (b.get("code") or "").lower()
                    or s in (b.get("city") or "").lower()]
    # summary counts (single pass)
    today = _ist_today()
    punched = set()
    async for a in db.attendance.find({"company_id": cid, "date": today, "kind": "in"},
                                      {"_id": 0, "user_id": 1}):
        punched.add(a["user_id"])
    emp_total: Dict[str, int] = {}
    emp_active: Dict[str, int] = {}
    present: Dict[str, int] = {}
    async for u in db.users.find({"company_id": cid, "role": "employee"},
                                 {"_id": 0, "user_id": 1, "home_branch_id": 1, "status": 1}):
        hb = u.get("home_branch_id") or ""
        emp_total[hb] = emp_total.get(hb, 0) + 1
        if u.get("status") != "inactive":
            emp_active[hb] = emp_active.get(hb, 0) + 1
            if u["user_id"] in punched:
                present[hb] = present.get(hb, 0) + 1
    for b in branches:
        bid = b["branch_id"]
        b["emp_count"] = emp_total.get(bid, 0)
        b["active_employees"] = emp_active.get(bid, 0)
        b["present_today"] = present.get(bid, 0)
        b["absent_today"] = max(0, emp_active.get(bid, 0) - present.get(bid, 0))
    return {"branches": branches, "branch_types": BRANCH_TYPES,
            "unassigned_employees": emp_total.get("", 0)}


# ---------------------------------------------------------------- create
@router.post("/create")
async def bm_create(body: Dict[str, Any] = Body(...),
                    authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    cid = admin.get("company_id") if admin["role"] == "company_admin" \
        else str(body.get("company_id") or "")
    if not cid:
        raise HTTPException(status_code=400, detail="company_id required")
    company = await db.companies.find_one({"company_id": cid}, {"_id": 0, "company_id": 1})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    patch = {k: body.get(k) for k in _ALL_FLAT if k in body}
    patch["name"] = str(body.get("name") or "").strip()
    _validate(patch)
    if not patch["name"]:
        raise HTTPException(status_code=400, detail="Branch Name is required")
    code = str(patch.get("code") or "").strip().upper()
    if code:
        patch["code"] = code
        await _check_code_unique(code, cid, None)

    branch_id = f"br_{uuid.uuid4().hex[:10]}"
    doc = {
        "branch_id": branch_id, "company_id": cid,
        "branch_type": body.get("branch_type") or "Branch",
        "active": True,
        "address": (str(body.get("address1") or "").strip() or None),  # legacy field kept in sync
        "geofence_radius_m": body.get("geofence_radius_m") or 200,
        "geofence_enabled": bool(body.get("geofence_enabled", True)),
        "allow_punch_inside": bool(body.get("allow_punch_inside", True)),
        # Cross-midnight ON by default for NEW branches (user spec §8) —
        # mapping/default only, attendance engine untouched.
        "attendance_config": {"cross_midnight": True,
                              **(body.get("attendance_config") or {})},
        "compliance_config": body.get("compliance_config") or {},
        "payroll_config": body.get("payroll_config") or {},
        "created_at": now_iso(), "created_by_user_id": admin["user_id"],
        "created_by_name": admin.get("name") or admin.get("email"),
    }
    doc.update({k: v for k, v in patch.items() if v is not None})
    await db.branches.insert_one(doc)
    doc.pop("_id", None)
    await _audit(admin, branch_id, "branch_create",
                 [{"field": "branch", "old": None, "new": doc.get("name")}])
    return {"ok": True, "branch": doc}


# ---------------------------------------------------------------- detail
@router.get("/{branch_id}")
async def bm_detail(branch_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    b = await _get_branch(branch_id, admin)
    audit = await db.branch_audit.find(
        {"branch_id": branch_id}, {"_id": 0}).sort("at", -1).to_list(30)
    return {"branch": b, "audit": audit, "branch_types": BRANCH_TYPES,
            "doc_types": DOC_TYPES}


@router.patch("/{branch_id}")
async def bm_patch(branch_id: str, body: Dict[str, Any] = Body(...),
                   authorization: Optional[str] = Header(None)):
    """Update any master section. Nested configs are MERGED (partial save).
    Field-level audit old → new."""
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    b = await _get_branch(branch_id, admin)

    patch: Dict[str, Any] = {k: body[k] for k in _ALL_FLAT if k in body}
    _validate(patch)
    if "name" in patch:
        patch["name"] = str(patch["name"]).strip()
    if "code" in patch:
        code = str(patch.get("code") or "").strip().upper()
        patch["code"] = code or None
        if code:
            await _check_code_unique(code, b["company_id"], branch_id)
    if "address1" in patch:  # keep legacy single-line address in sync
        parts = [str(body.get(k) or "").strip()
                 for k in ("address1", "address2", "area", "city")]
        patch["address"] = ", ".join([p for p in parts if p]) or None
    # merge nested config sections
    for sec in _CONFIG_SECTIONS:
        if sec in body and isinstance(body[sec], dict):
            merged = dict(b.get(sec) or {})
            merged.update(body[sec])
            patch[sec] = merged
    # document-date sanity used by establishment section
    cc = patch.get("compliance_config") or {}
    rd, ed = str(cc.get("sne_regn_date") or ""), str(cc.get("sne_expiry_date") or "")
    if rd and ed and ed < rd:
        raise HTTPException(status_code=400,
                            detail="Registration Expiry Date cannot be before Registration Date")
    if not patch:
        return {"ok": True, "branch": b}
    changes = _diff(b, patch)
    patch["updated_at"] = now_iso()
    patch["updated_by_name"] = admin.get("name") or admin.get("email")
    await db.branches.update_one({"branch_id": branch_id}, {"$set": patch})
    # Branch renamed? keep the report dimension users.branch_name in sync
    # for CURRENT home employees (old run rows keep their snapshots).
    if "name" in patch and patch["name"] and patch["name"] != b.get("name"):
        await db.users.update_many(
            {"home_branch_id": branch_id},
            {"$set": {"branch_name": patch["name"]}})
    await _audit(admin, branch_id, "branch_update", changes)
    fresh = await db.branches.find_one({"branch_id": branch_id}, {"_id": 0})
    return {"ok": True, "branch": fresh}


# ---------------------------------------------------------------- dashboard
@router.get("/{branch_id}/dashboard")
async def bm_branch_dashboard(branch_id: str,
                              authorization: Optional[str] = Header(None)):
    """Compact per-branch dashboard from EXISTING system data — no new
    calculation engine. Count queries only (fast)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    b = await _get_branch(branch_id, admin)
    cid = b["company_id"]
    today = _ist_today()
    month = today[:7]

    uids_all: List[str] = []
    uids_active: List[str] = []
    joiners = exits = 0
    async for u in db.users.find({"company_id": cid, "role": "employee",
                                  "home_branch_id": branch_id},
                                 {"_id": 0, "user_id": 1, "status": 1, "doj": 1,
                                  "date_of_joining": 1, "dol": 1, "date_of_leaving": 1}):
        uids_all.append(u["user_id"])
        if u.get("status") != "inactive":
            uids_active.append(u["user_id"])
        doj = str(u.get("doj") or u.get("date_of_joining") or "")
        dol = str(u.get("dol") or u.get("date_of_leaving") or "")
        if doj.startswith(month):
            joiners += 1
        if dol.startswith(month):
            exits += 1

    present = len(await db.attendance.distinct(
        "user_id", {"company_id": cid, "date": today, "kind": "in",
                    "user_id": {"$in": uids_active}})) if uids_active else 0
    on_leave = await db.leaves.count_documents(
        {"user_id": {"$in": uids_active}, "status": "approved",
         "from_date": {"$lte": today}, "to_date": {"$gte": today}}) if uids_active else 0
    on_duty = await db.branch_temp_assignments.count_documents(
        {"user_id": {"$in": uids_all}, "status": "approved",
         "from_date": {"$lte": today}, "to_date": {"$gte": today}}) if uids_all else 0
    pending_leaves = await db.leaves.count_documents(
        {"user_id": {"$in": uids_all}, "status": "pending"}) if uids_all else 0
    pending_advances = await db.advances.count_documents(
        {"user_id": {"$in": uids_all}, "status": "pending"}) if uids_all else 0
    open_fnf = await db.fnf_settlements.count_documents(
        {"user_id": {"$in": uids_all},
         "status": {"$nin": ["paid", "cancelled", "rejected"]}}) if uids_all else 0
    run = await db.compliance_salary_runs.find_one(
        {"company_id": cid, "month": month}, {"_id": 0, "status": 1},
        sort=[("generated_at", -1)])

    active = len(uids_active)
    absent = max(0, active - present - on_leave)
    cc = b.get("compliance_config") or {}
    compliance_ok = bool(b.get("state")) and (
        cc.get("pt_applicable") is not None or cc.get("pf_applicable") is not None)
    return {"branch_id": branch_id, "date": today, "month": month,
            "total_employees": len(uids_all), "active_employees": active,
            "inactive_employees": len(uids_all) - active,
            "present_today": present, "absent_today": absent,
            "on_leave": on_leave, "on_duty": on_duty,
            "attendance_pct": round(present / active * 100, 1) if active else 0,
            "payroll_status": (run or {}).get("status") or "not_generated",
            "compliance_status": "configured" if compliance_ok
            else ("state_set" if b.get("state") else "pending"),
            "pending_approvals": pending_leaves + pending_advances,
            "pending_leaves": pending_leaves, "pending_advances": pending_advances,
            "new_joiners": joiners, "exits": exits, "open_fnf": open_fnf}


# ---------------------------------------------------------------- employees
@router.get("/{branch_id}/employees")
async def bm_branch_employees(branch_id: str,
                              q: Optional[str] = Query(None),
                              page: int = Query(1, ge=1),
                              page_size: int = Query(50, ge=1, le=200),
                              authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    b = await _get_branch(branch_id, admin)
    query: dict = {"company_id": b["company_id"], "role": "employee",
                   "home_branch_id": branch_id}
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"name": rx}, {"employee_code": rx}]
    total = await db.users.count_documents(query)
    emps = await db.users.find(query, {
        "_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "status": 1,
        "designation": 1, "department": 1, "doj": 1, "date_of_joining": 1,
        "mobile": 1, "phone": 1,
    }).sort("name", 1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"employees": emps, "total": total, "page": page, "page_size": page_size}


@router.get("/{branch_id}/employees-export")
async def bm_branch_employees_export(branch_id: str,
                                     authorization: Optional[str] = Header(None)):
    import io
    from fastapi.responses import Response
    from openpyxl import Workbook
    from openpyxl.styles import Font
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    b = await _get_branch(branch_id, admin)
    wb = Workbook()
    ws = wb.active
    ws.title = "Employees"
    ws.append([f"Branch Employees — {b.get('name')} ({b.get('code') or b['branch_id']})"])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append([])
    ws.append(["Code", "Name", "Designation", "Department", "DOJ", "Mobile", "Status"])
    for c in ws[3]:
        c.font = Font(bold=True)
    async for u in db.users.find({"company_id": b["company_id"], "role": "employee",
                                  "home_branch_id": branch_id},
                                 {"_id": 0}).sort("name", 1):
        ws.append([u.get("employee_code"), u.get("name"), u.get("designation"),
                   u.get("department"), u.get("doj") or u.get("date_of_joining"),
                   u.get("mobile") or u.get("phone"),
                   "Inactive" if u.get("status") == "inactive" else "Active"])
    out = io.BytesIO()
    wb.save(out)
    fname = f"Branch_Employees_{(b.get('code') or b.get('name') or 'branch').replace(' ', '_')}.xlsx"
    return Response(
        content=out.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------------------------------------------------------------- transfer
@router.post("/transfer")
async def bm_transfer(body: Dict[str, Any] = Body(...),
                      authorization: Optional[str] = Header(None)):
    """Single or BULK controlled transfer. Writes to the existing
    ``branch_transfers`` collection (effective-dated; same lazy applier as
    the branch-management hub) → history is created automatically and old
    payroll/attendance records are NEVER rewritten."""
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    uids = [str(u) for u in (body.get("user_ids") or []) if u]
    if body.get("user_id"):
        uids.append(str(body["user_id"]))
    uids = list(dict.fromkeys(uids))
    new_b = str(body.get("new_branch_id") or "")
    eff = str(body.get("effective_date") or "")
    if not (uids and new_b and eff):
        raise HTTPException(status_code=400,
                            detail="user_ids, new_branch_id and effective_date are required")
    nb = await db.branches.find_one({"branch_id": new_b}, {"_id": 0, "company_id": 1,
                                                           "name": 1, "active": 1})
    if not nb:
        raise HTTPException(status_code=404, detail="Target branch not found")
    if nb.get("active") is False:
        raise HTTPException(status_code=400, detail="Target branch is Inactive — activate it first")
    created = []
    for uid in uids:
        emp = await db.users.find_one({"user_id": uid},
                                      {"_id": 0, "company_id": 1, "name": 1,
                                       "home_branch_id": 1})
        if not emp:
            continue
        if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
            continue
        if emp.get("home_branch_id") == new_b:
            continue  # already there
        doc = {
            "transfer_id": f"btr_{uuid.uuid4().hex[:10]}",
            "company_id": emp["company_id"], "user_id": uid,
            "employee_name": emp.get("name"),
            "prev_branch_id": emp.get("home_branch_id"),
            "new_branch_id": new_b, "effective_date": eff,
            "reason": str(body.get("reason") or "").strip() or None,
            "remarks": str(body.get("remarks") or "").strip() or None,
            "approved_by": admin["user_id"], "status": "pending",
            "created_at": now_iso(),
        }
        await db.branch_transfers.insert_one(doc)
        doc.pop("_id", None)
        created.append(doc)
        await _audit(admin, new_b, "employee_transfer",
                     [{"field": f"employee:{emp.get('name') or uid}",
                       "old": emp.get("home_branch_id"), "new": new_b}])
    if created:
        await _apply_due_transfers(created[0]["company_id"])
    return {"ok": True, "created": len(created), "transfers": created}


# ---------------------------------------------------------------- history
@router.get("/{branch_id}/history")
async def bm_branch_history(branch_id: str,
                            authorization: Optional[str] = Header(None)):
    """Transfers in / out of this branch (never deleted)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    await _get_branch(branch_id, admin)
    rows = await db.branch_transfers.find(
        {"$or": [{"prev_branch_id": branch_id}, {"new_branch_id": branch_id}]},
        {"_id": 0}).sort("created_at", -1).to_list(300)
    names = {b["branch_id"]: b.get("name") for b in await db.branches.find(
        {}, {"_id": 0, "branch_id": 1, "name": 1}).to_list(500)}
    for r in rows:
        r["prev_branch_name"] = names.get(r.get("prev_branch_id")) or "Main / Unassigned"
        r["new_branch_name"] = names.get(r.get("new_branch_id")) or "-"
        r["direction"] = "IN" if r.get("new_branch_id") == branch_id else "OUT"
    return {"history": rows}


@router.get("/employee-history/{user_id}")
async def bm_employee_history(user_id: str,
                              authorization: Optional[str] = Header(None)):
    """Employee → Branch History timeline (effective from/to) built from
    the immutable branch_transfers register."""
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    emp = await db.users.find_one({"user_id": user_id},
                                  {"_id": 0, "company_id": 1, "name": 1,
                                   "home_branch_id": 1, "doj": 1, "date_of_joining": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your employee")
    names = {b["branch_id"]: b.get("name") for b in await db.branches.find(
        {}, {"_id": 0, "branch_id": 1, "name": 1}).to_list(500)}
    transfers = await db.branch_transfers.find(
        {"user_id": user_id, "status": {"$ne": "cancelled"}},
        {"_id": 0}).sort("effective_date", 1).to_list(200)
    timeline = []
    start = str(emp.get("doj") or emp.get("date_of_joining") or "") or None
    prev_branch = transfers[0].get("prev_branch_id") if transfers \
        else emp.get("home_branch_id")
    cur_from = start
    for t in transfers:
        eff = t.get("effective_date")
        timeline.append({
            "from": cur_from, "to": eff,
            "branch_id": prev_branch,
            "branch": names.get(prev_branch) or "Main / Unassigned",
            "transfer_reason": None,
        })
        prev_branch = t.get("new_branch_id")
        cur_from = eff
        timeline[-1]["next_reason"] = t.get("reason")
    timeline.append({"from": cur_from, "to": None,
                     "branch_id": prev_branch,
                     "branch": names.get(prev_branch) or "Main / Unassigned"})
    return {"employee": {"user_id": user_id, "name": emp.get("name")},
            "timeline": timeline, "transfers": [
                {**t, "prev_branch_name": names.get(t.get("prev_branch_id")) or "Main / Unassigned",
                 "new_branch_name": names.get(t.get("new_branch_id")) or "-"}
                for t in transfers]}


# ---------------------------------------------------------------- documents
@router.get("/{branch_id}/documents")
async def bm_docs_list(branch_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    await _get_branch(branch_id, admin)
    today = _ist_today()
    soon = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")
    docs = await db.branch_documents.find(
        {"branch_id": branch_id, "status": {"$ne": "deleted"}},
        {"_id": 0, "file_base64": 0}).sort("created_at", -1).to_list(200)
    for d in docs:
        exp = str(d.get("expiry_date") or "")
        if d.get("status") == "replaced":
            d["expiry_status"] = "replaced"
        elif exp and exp < today:
            d["expiry_status"] = "expired"
        elif exp and exp <= soon:
            d["expiry_status"] = "expiring_soon"
        else:
            d["expiry_status"] = "active"
    return {"documents": docs, "doc_types": DOC_TYPES}


@router.post("/{branch_id}/documents")
async def bm_docs_add(branch_id: str, body: Dict[str, Any] = Body(...),
                      authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    await _get_branch(branch_id, admin)
    doc_type = str(body.get("doc_type") or "").strip()
    if not doc_type:
        raise HTTPException(status_code=400, detail="Document Type is required")
    issue, exp = str(body.get("issue_date") or ""), str(body.get("expiry_date") or "")
    if issue and exp and exp < issue:
        raise HTTPException(status_code=400,
                            detail="Expiry date cannot be before issue date")
    f64 = body.get("file_base64")
    if f64:
        try:
            raw = base64.b64decode(f64.split(",")[-1], validate=False)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid file data")
        if len(raw) > 8 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File too large (max 8 MB)")
    # replacing an older doc of the same type? keep history — mark replaced.
    if body.get("replace_same_type"):
        await db.branch_documents.update_many(
            {"branch_id": branch_id, "doc_type": doc_type,
             "status": {"$nin": ["deleted", "replaced"]}},
            {"$set": {"status": "replaced", "replaced_at": now_iso(),
                      "replaced_by": admin["user_id"]}})
    doc = {
        "doc_id": f"brdoc_{uuid.uuid4().hex[:10]}", "branch_id": branch_id,
        "doc_type": doc_type,
        "doc_number": str(body.get("doc_number") or "").strip() or None,
        "issue_date": issue or None, "expiry_date": exp or None,
        "remarks": str(body.get("remarks") or "").strip() or None,
        "file_name": str(body.get("file_name") or "").strip() or None,
        "file_base64": f64 or None,
        "status": "active",
        "created_at": now_iso(),
        "created_by": admin["user_id"],
        "created_by_name": admin.get("name") or admin.get("email"),
    }
    await db.branch_documents.insert_one(doc)
    doc.pop("_id", None)
    doc.pop("file_base64", None)
    await _audit(admin, branch_id, "document_add",
                 [{"field": f"document:{doc_type}", "old": None,
                   "new": doc.get("doc_number") or doc.get("file_name") or "added"}])
    return {"ok": True, "document": doc}


@router.get("/documents/{doc_id}/file")
async def bm_docs_file(doc_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    d = await db.branch_documents.find_one({"doc_id": doc_id}, {"_id": 0})
    if not d or not d.get("file_base64"):
        raise HTTPException(status_code=404, detail="File not found")
    await _get_branch(d["branch_id"], admin)
    return {"file_name": d.get("file_name") or f"{d.get('doc_type')}.pdf",
            "file_base64": d["file_base64"]}


@router.delete("/documents/{doc_id}")
async def bm_docs_delete(doc_id: str, authorization: Optional[str] = Header(None)):
    """Soft delete — document history is preserved."""
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    d = await db.branch_documents.find_one({"doc_id": doc_id}, {"_id": 0, "branch_id": 1,
                                                                "doc_type": 1})
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    await _get_branch(d["branch_id"], admin)
    await db.branch_documents.update_one(
        {"doc_id": doc_id},
        {"$set": {"status": "deleted", "deleted_at": now_iso(),
                  "deleted_by": admin["user_id"]}})
    await _audit(admin, d["branch_id"], "document_delete",
                 [{"field": f"document:{d.get('doc_type')}", "old": "active",
                   "new": "deleted"}])
    return {"ok": True}
