"""Iter 409 — GENERAL MASTERS + FIRM COMPLIANCE POLICY module (extracted
from server.py).

Refactor only: every endpoint, model and helper below was MOVED verbatim
from server.py — Employee Masters CRUD (Group / Department / Designation /
Allowance / Deduction / Holiday, Iter 59), the state-wise PT catalogue
(Iter 178) and the firm-wise Compliance Policy GET/PUT (Iter 59). No
behavioural change.
"""
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from server import (  # noqa: E402
    db,
    get_user_from_token,
    now_iso,
    require_role,
    require_super_admin_strict,
)

router = APIRouter(prefix="/api")
api = router  # endpoints below keep their original @api.* decorators


# ---------------------------------------------------------------------------
# Employee Masters (Group / Department / Designation) — Iter 59
# ---------------------------------------------------------------------------
# Single polymorphic collection `masters` with fields:
#   master_id: str (uuid)
#   type: "group" | "department" | "designation"
#   company_id: str (scoped per firm — super admin selects the firm)
#   name: str
#   member_user_ids: List[str]  (for `group` type, optional otherwise)
#   created_at, updated_at, created_by
_MASTER_TYPES = ("group", "department", "designation", "allowance", "deduction", "holiday")


class MasterUpsert(BaseModel):
    type: str
    company_id: str
    name: str
    member_user_ids: Optional[List[str]] = None
    # Iter 200 — Holiday Master entries carry a calendar date (YYYY-MM-DD).
    date: Optional[str] = None


@api.get("/admin/masters")
async def list_masters(
    type: str,
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if type not in _MASTER_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {_MASTER_TYPES}")
    q: Dict[str, Any] = {"type": type}
    if admin["role"] == "company_admin":
        # Company admin sees THEIR firm's masters + any globally-scoped ones.
        q["company_id"] = {"$in": [admin.get("company_id"), "__global__", None]}
    elif company_id and company_id != "__global__":
        q["company_id"] = {"$in": [company_id, "__global__", None]}
    # else: super/sub admin without a firm filter -> ALL firms + globals.
    # Iter 244 (user bug) — INTERLINK: groups that exist only on employee
    # records (e.g. created during Bulk Employee Import) are auto-registered
    # into the Group Master here, so they show up in the General Masters
    # screen and every Group dropdown across the app.
    if type == "group":
        try:
            u_match: Dict[str, Any] = {"role": "employee"}
            if admin["role"] == "company_admin":
                u_match["company_id"] = admin.get("company_id")
            elif company_id and company_id != "__global__":
                u_match["company_id"] = company_id
            # Iter 294 (user bug: STAFF missing) — the old check collected
            # names GLOBALLY, so a group registered under firm A blocked
            # auto-registration for firm B forever. Track (company, name)
            # pairs instead, honouring __global__ masters for every firm.
            existing_pairs: set = set()
            async for m in db.masters.find(
                {"type": "group"}, {"_id": 0, "name": 1, "company_id": 1}
            ):
                nm0 = (m.get("name") or "").strip().upper()
                existing_pairs.add((m.get("company_id") or "", nm0))

            def _known(cid: str, nm: str) -> bool:
                return ("__global__", nm) in existing_pairs or (cid, nm) in existing_pairs

            # Collect in-use group names from BOTH employee_type and
            # employee_group (legacy imports fill either). $type:string
            # guard prevents $toUpper crashing on non-string legacy values.
            in_use: Dict[Any, bool] = {}
            for fld in ("employee_type", "employee_group"):
                async for row in db.users.aggregate([
                    {"$match": {**u_match, fld: {"$type": "string", "$nin": [""]}}},
                    {"$group": {"_id": {
                        "cid": "$company_id",
                        "name": {"$toUpper": {"$trim": {"input": f"${fld}"}}},
                    }}},
                    {"$limit": 500},
                ]):
                    nm = (row["_id"].get("name") or "").strip()
                    u_cid = row["_id"].get("cid")
                    if nm and u_cid:
                        in_use[(u_cid, nm)] = True
            for (u_cid, nm) in in_use.keys():
                if _known(u_cid, nm):
                    continue
                await db.masters.insert_one({
                    "master_id": f"mst_{uuid.uuid4().hex[:12]}",
                    "type": "group",
                    "company_id": u_cid,
                    "name": nm,
                    "member_user_ids": [],
                    "date": None,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "created_by": admin["user_id"],
                    "scope": "firm",
                    "auto_registered": "bulk_import_interlink",
                })
                existing_pairs.add((u_cid, nm))
        except Exception as _e:
            logging.warning(f"group-master interlink failed: {_e}")
    items = await db.masters.find(q, {"_id": 0}).sort("name", 1).to_list(2000)
    return {"items": items}


@api.post("/admin/masters")
async def create_master(
    payload: MasterUpsert,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if payload.type not in _MASTER_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {_MASTER_TYPES}")
    # Iter 108 — company admins may auto-register masters, but ONLY for
    # their own firm (they cannot create global masters).
    if admin.get("role") == "company_admin":
        if (payload.company_id or "").strip() in ("", "__global__") or \
                payload.company_id != admin.get("company_id"):
            raise HTTPException(status_code=403, detail="You can only add masters for your own firm")
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    # Iter 129j (user directive) — ALL master names (Departments,
    # Designations, Employee Types/Groups, Allowances, Deductions) are
    # stored in CAPITAL LETTERS, so duplicates can never differ by case.
    name = name.upper()
    # Iter 77 - Support GLOBAL masters (available across every firm).
    is_global = (payload.company_id or "").strip() in ("", "__global__")
    # Iter 113 — company admins may add entries ONLY to their own firm
    # (lets manually-typed Designation/Department values persist into the
    # dropdown from the Add-Employee form).
    if admin.get("role") == "company_admin":
        if is_global or payload.company_id != admin.get("company_id"):
            raise HTTPException(status_code=403, detail="You can only add masters for your own firm")
    if is_global:
        target_cid = "__global__"
    else:
        company = await db.companies.find_one(
            {"company_id": payload.company_id}, {"_id": 0, "company_id": 1}
        )
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        target_cid = payload.company_id
    # Iter 139 (user request) — HARD duplicate stop:
    #  • GROUPS are used across the whole master → same name may not exist
    #    in ANY scope (any firm or global).
    #  • Other types: a firm entry may not duplicate its own firm's or a
    #    global one; a GLOBAL entry may not duplicate ANY existing scope.
    dup_q: Dict[str, Any] = {
        "type": payload.type,
        "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
    }
    if payload.type != "group" and not is_global:
        dup_q["company_id"] = {"$in": [target_cid, "__global__", None]}
    if payload.type == "holiday":
        # Same holiday name may repeat on different dates (yearly festivals).
        dup_q["date"] = (payload.date or "").strip()[:10]
    dup = await db.masters.find_one(dup_q, {"_id": 0, "master_id": 1})
    if dup:
        raise HTTPException(status_code=409, detail=f"A {payload.type} named '{name}' already exists")
    master_id = f"mst_{uuid.uuid4().hex[:12]}"
    # Iter 200 — Holiday Master needs a valid date.
    _hol_date = None
    if payload.type == "holiday":
        _hol_date = (payload.date or "").strip()[:10]
        try:
            datetime.strptime(_hol_date, "%Y-%m-%d")
        except Exception:
            raise HTTPException(status_code=400, detail="Holiday requires a valid date (YYYY-MM-DD)")
    doc = {
        "master_id": master_id,
        "type": payload.type,
        "company_id": target_cid,
        "name": name,
        "member_user_ids": list(payload.member_user_ids or []) if payload.type == "group" else [],
        "date": _hol_date,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": admin["user_id"],
        "scope": "global" if is_global else "firm",
    }
    await db.masters.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.patch("/admin/masters/{master_id}")
async def update_master(
    master_id: str,
    payload: MasterUpsert,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    existing = await db.masters.find_one({"master_id": master_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Master not found")
    updates: Dict[str, Any] = {"updated_at": now_iso()}
    if payload.name is not None:
        name = payload.name.strip().upper()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        # Iter 139 (user request) — renames must not create duplicates
        # either (same rules as create; excludes this master itself).
        dup_q: Dict[str, Any] = {
            "type": existing.get("type"),
            "master_id": {"$ne": master_id},
            "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
        }
        if existing.get("type") != "group" and existing.get("company_id") not in ("__global__", None):
            dup_q["company_id"] = {"$in": [existing.get("company_id"), "__global__", None]}
        if await db.masters.find_one(dup_q, {"_id": 0, "master_id": 1}):
            raise HTTPException(
                status_code=409,
                detail=f"A {existing.get('type')} named '{name}' already exists")
        updates["name"] = name
    if payload.type == "group" and payload.member_user_ids is not None:
        updates["member_user_ids"] = list(payload.member_user_ids or [])
    await db.masters.update_one({"master_id": master_id}, {"$set": updates})
    merged = {**existing, **updates}
    merged.pop("_id", None)
    return merged


@api.delete("/admin/masters/{master_id}")
async def delete_master(
    master_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    r = await db.masters.delete_one({"master_id": master_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Master not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Firm-wise Compliance Policy — Iter 59
# ---------------------------------------------------------------------------
# Stored inline on the `companies` doc under `compliance_policy` so it
# overrides the global defaults defined in utils/compliance_salary.py.
# Schema (all fields optional — omit to inherit global):
#   pf_employee_rate, pf_employer_rate, pf_admin_rate, pf_wage_cap,
#   esic_employee_rate, esic_employer_rate, esic_wage_threshold,
#   tds_regime ("old" | "new"), pt_slabs (list of {upto, amount})


class CompliancePolicyPayload(BaseModel):
    pf_employee_rate: Optional[float] = None
    pf_employer_rate: Optional[float] = None
    pf_admin_rate: Optional[float] = None
    pf_wage_cap: Optional[float] = None
    esic_employee_rate: Optional[float] = None
    esic_employer_rate: Optional[float] = None
    esic_wage_threshold: Optional[float] = None
    tds_regime: Optional[str] = None
    pt_slabs: Optional[List[Dict[str, Any]]] = None
    # Iter 178 — state-wise PT: firm's PT state auto-applies statutory slabs.
    pt_state: Optional[str] = None
    apply_pf: Optional[bool] = None
    apply_esic: Optional[bool] = None
    apply_pt: Optional[bool] = None
    apply_tds: Optional[bool] = None
    # Iter 68 — Salary-structure defaults for the compliance run.  Moved from
    # the Compliance Salary screen (which was editable) to a single Firm
    # Settings surface.  Percentages of monthly gross.
    basic_pct: Optional[float] = None
    hra_pct: Optional[float] = None
    conveyance_pct: Optional[float] = None
    medical_pct: Optional[float] = None
    special_pct: Optional[float] = None
    others_pct: Optional[float] = None
    stat_wage_floor_pct: Optional[float] = None
    # Iter 85 — Firm toggle for percentage-based bifurcation.
    # When True: admins enter Compliance Gross ₹ per employee, and the
    # system auto-bifurcates into Basic/HRA/Conveyance/etc using the
    # firm's percentages below.
    # When False: admins must enter each Basic/HRA/etc amount manually
    # on the Employee Master (percentages are ignored).
    allow_percent_bifurcation: Optional[bool] = None
    # Iter 85 — Firm-level allowance selection. Basic is ALWAYS on and
    # cannot be disabled (statutory requirement). The others (HRA,
    # Conveyance, Medical, Special, Others) are opt-in per firm.
    # Compliance Salary Process only shows / applies the enabled heads.
    enabled_allowances: Optional[List[str]] = None  # e.g. ["basic","hra","conveyance"]
    notes: Optional[str] = None


@api.get("/admin/pt-states")
async def list_pt_states(authorization: Optional[str] = Header(None)):
    """Iter 178 — state-wise Professional Tax slab catalogue (monthly
    gross → monthly PT). Used by the firm Compliance Policy screen."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    from utils.compliance_salary import PT_STATE_SLABS
    return {"states": [
        {"state": s, "slabs": slabs, "has_pt": bool(slabs)}
        for s, slabs in sorted(PT_STATE_SLABS.items())
    ]}


@api.get("/admin/companies/{company_id}/compliance-policy")
async def get_company_compliance_policy(
    company_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorised")
    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "compliance_policy": 1, "name": 1}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {
        "company_id": company_id,
        "name": company.get("name"),
        "policy": company.get("compliance_policy") or {},
    }


@api.put("/admin/companies/{company_id}/compliance-policy")
async def set_company_compliance_policy(
    company_id: str,
    payload: CompliancePolicyPayload,
    authorization: Optional[str] = Header(None),
):
    """Web-only endpoint (Super Admin) to set firm-level Compliance policy
    overrides. Any fields left null inherit the global defaults. Merges with
    the existing stored policy so partial PUTs don't wipe unrelated fields."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "company_id": 1, "compliance_policy": 1}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    existing = company.get("compliance_policy") or {}
    incoming = {k: v for k, v in payload.dict().items() if v is not None}
    policy = {**existing, **incoming}
    policy["updated_at"] = now_iso()
    policy["updated_by"] = admin["user_id"]
    await db.companies.update_one(
        {"company_id": company_id}, {"$set": {"compliance_policy": policy}}
    )
    return {"ok": True, "policy": policy}
