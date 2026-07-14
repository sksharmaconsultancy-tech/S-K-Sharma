"""Iter 91 — Route module: one-page Employee Profile (full edit).

Powers the "one page edit all details" flow: the Add-Employee form
doubles as the EDIT form for existing employees (?user_id= deep link).

  GET   /api/admin/employees/{user_id}/profile  — every editable field
  PATCH /api/admin/employees/{user_id}/profile  — partial update
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    logger,
)

router = APIRouter(prefix="/api/admin", tags=["employee-profile"])

# Editable scalar fields (whitelist).
_STR_FIELDS = [
    "name", "phone", "email", "father_name", "mother_name", "gender",
    "dob", "doj", "exit_date",
    # Iter 94 — Employee Code & Bio Code editable from the one-page form
    # (same format as Add New Employee / Kankani master sheet).
    "employee_code", "bio_code",
    "designation", "department", "employee_type", "employee_group",
    "shift_start", "shift_end", "salary_mode", "compliance_salary_mode",
    "uan_no", "pf_no", "esi_ip_no", "pan_no", "aadhaar_no",
    "bank_name", "bank_account", "bank_ifsc", "address",
    # Extra master fields: blood group, marital status, PAN name, UPI
    "blood_group", "marital_status", "pan_name", "upi_id", "spouse_name",
    # Iter 109 — was missing: Pay Mode (Bank / Cash / Cheque) never saved
    # from the one-page edit form.
    "pay_mode",
    "permanent_address", "emergency_contact_name", "emergency_contact_phone",
]
_NUM_FIELDS = [
    "salary_monthly", "compliance_gross",
    # Iter 126g — Compliance Basic + PF Basic (EPF ceiling rule; PF is
    # calculated on pf_basic when set).
    "compliance_basic", "pf_basic",
    # Iter 126i — VPF (Voluntary PF) amount, deducted with employee PF.
    "vpf_amount",
]
_BOOL_FIELDS = ["is_onroll", "vpf_enabled"]
_LIST_FIELDS = [
    "salary_structure_actual",
    "actual_salary_allowances", "actual_salary_deductions",
    # Iter 109 — was missing: Compliance allowance/deduction line items
    # were silently dropped on edit.
    "compliance_salary_allowances", "compliance_salary_deductions",
    "family_members",
]


async def _get_emp(user_id: str, admin: Dict[str, Any]) -> Dict[str, Any]:
    emp = await db.users.find_one({"user_id": user_id, "role": "employee"}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this employee")
    return emp


@router.get("/employees/{user_id}/profile")
async def get_employee_profile(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    emp = await _get_emp(user_id, admin)
    out: Dict[str, Any] = {
        "user_id": emp["user_id"],
        "employee_code": emp.get("employee_code"),
        "company_id": emp.get("company_id"),
    }
    for k in _STR_FIELDS + _NUM_FIELDS + _BOOL_FIELDS + _LIST_FIELDS:
        out[k] = emp.get(k)
    # Iter 95e — shift assignment (Shift Master reference).
    out["shift_id"] = (emp.get("attendance_policy_override") or {}).get("shift_id")
    # Legacy aliases
    out["aadhaar_no"] = emp.get("aadhaar_no") or emp.get("aadhar_number")
    out["pan_no"] = emp.get("pan_no") or emp.get("pan_number")
    return out


@router.patch("/employees/{user_id}/profile")
async def patch_employee_profile(
    user_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    emp = await _get_emp(user_id, admin)  # 404/403 guard

    # Iter 94 — Employee Code must stay unique within the firm.
    new_code = str(payload.get("employee_code") or "").strip()
    if new_code and new_code != (emp.get("employee_code") or ""):
        dup = await db.users.find_one({
            "company_id": emp.get("company_id"),
            "employee_code": new_code,
            "user_id": {"$ne": user_id},
        }, {"_id": 0, "user_id": 1})
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"Employee code {new_code} is already used in this firm",
            )

    updates: Dict[str, Any] = {}
    for k in _STR_FIELDS:
        if k in payload:
            v = payload[k]
            updates[k] = (str(v).strip() or None) if v is not None else None
    for k in _NUM_FIELDS:
        if k in payload:
            try:
                updates[k] = float(payload[k]) if payload[k] not in (None, "") else None
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{k} must be a number")
    for k in _BOOL_FIELDS:
        if k in payload:
            updates[k] = bool(payload[k])
    for k in _LIST_FIELDS:
        if k in payload and isinstance(payload[k], list):
            updates[k] = payload[k]

    # Employee Type / Group are unified — mirror whichever was sent.
    if "employee_type" in updates or "employee_group" in updates:
        unified = updates.get("employee_type") or updates.get("employee_group")
        updates["employee_type"] = unified
        updates["employee_group"] = unified

    # Iter 95e — Shift assignment via Shift Master. ``shift_id`` maps onto
    # attendance_policy_override.shift_id (preserving other override keys)
    # and mirrors the master's start/end for display.
    if "shift_id" in payload:
        sid = str(payload.get("shift_id") or "").strip()
        override = dict(emp.get("attendance_policy_override") or {})
        if sid:
            shift = await db.shift_masters.find_one(
                {"shift_id": sid}, {"_id": 0, "shift_id": 1, "start": 1, "end": 1},
            )
            if not shift:
                raise HTTPException(status_code=400, detail="Unknown shift — pick one from the Shift Master")
            override["shift_id"] = sid
            updates["shift_start"] = shift.get("start")
            updates["shift_end"] = shift.get("end")
        else:
            override.pop("shift_id", None)
            updates["shift_start"] = None
            updates["shift_end"] = None
        updates["attendance_policy_override"] = override

    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    updates["profile_updated_at"] = now_iso()
    updates["profile_updated_by"] = admin["user_id"]
    await db.users.update_one({"user_id": user_id}, {"$set": updates})
    logger.info("[profile] %s updated %s fields=%s",
                admin["user_id"], user_id, sorted(updates.keys()))
    fresh = await _get_emp(user_id, admin)
    return {"ok": True, "employee": {k: fresh.get(k) for k in
                                     ["user_id", "name", "employee_code"] + _STR_FIELDS}}
