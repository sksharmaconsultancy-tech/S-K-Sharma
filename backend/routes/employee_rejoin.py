"""Iter 475 — EMPLOYEE REJOIN (REHIRE) module.

A previously separated employee (resigned / terminated / retired /
absconded / contract completed) can be re-activated WITHOUT losing any
historical payroll, attendance, statutory or employment records:

  * the closing employment period is archived into ``employment_history``
  * the SAME UAN / ESIC IP continue (never re-issued — EPFO/ESIC rules)
  * attendance & payroll restart from the Rejoin Date (old records stay)
  * Firm-Master ``rejoin_policy`` drives employee-code / leave / gratuity
    behaviour
  * every rejoin is stamped into the immutable ``rejoin_audit`` collection
"""

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from server import (  # noqa: E402
    _next_employee_code,
    build_compliance_structure,
    compliance_gross_total,
    db,
    get_user_from_token,
    logger,
    require_role,
)
from shared.dates import _parse_any_date  # noqa: E402

router = APIRouter(prefix="/api")

SEPARATED_STATUSES = {"resigned", "terminated", "retired", "absconded",
                      "exited", "left", "contract_completed",
                      "contract completed"}

REJOIN_POLICY_DEFAULTS = {
    # continue | new
    "employee_code": "continue",
    # continue | reset | manual
    "leave_balance": "continue",
    # continue | fresh
    "gratuity_service": "continue",
    "restore_access": True,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_separated(u: Dict[str, Any]) -> bool:
    status = str(u.get("employment_status") or "").strip().lower()
    return bool(
        u.get("exit_date") or u.get("resign_date")
        or status in SEPARATED_STATUSES or u.get("active") is False
    )


def _to_date(v: Any) -> Optional[date]:
    d = _parse_any_date(v)
    if isinstance(d, datetime):
        return d.date()
    return d


def _last_working_date(u: Dict[str, Any]) -> Optional[date]:
    for k in ("exit_date", "resign_date"):
        d = _to_date(u.get(k))
        if d:
            return d
    return None


def _service_span(start: Optional[date], end: Optional[date]) -> Optional[str]:
    if not start or not end or end < start:
        return None
    days = (end - start).days
    years, rem = divmod(days, 365)
    months = rem // 30
    return f"{years} Years {months} Months"


async def _rejoin_policy(company_id: Optional[str]) -> Dict[str, Any]:
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "rejoin_policy": 1}) or {}
    return {**REJOIN_POLICY_DEFAULTS, **(fm.get("rejoin_policy") or {})}


async def _load_employee(user_id: str, admin: Dict[str, Any]) -> Dict[str, Any]:
    u = await db.users.find_one({"user_id": user_id, "role": "employee"}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and u.get("company_id") != admin["company_id"]:
        raise HTTPException(status_code=403, detail="Not authorised for this employee")
    return u


# --------------------------------------------------------------------------
# Firm-Master rejoin policy
# --------------------------------------------------------------------------
class RejoinPolicyUpdate(BaseModel):
    employee_code: Optional[str] = None       # continue | new
    leave_balance: Optional[str] = None       # continue | reset | manual
    gratuity_service: Optional[str] = None    # continue | fresh
    restore_access: Optional[bool] = None


@router.get("/admin/firm-masters/{company_id}/rejoin-policy")
async def get_rejoin_policy(company_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    return {"policy": await _rejoin_policy(company_id)}


@router.put("/admin/firm-masters/{company_id}/rejoin-policy")
async def update_rejoin_policy(
    company_id: str,
    payload: RejoinPolicyUpdate,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin["company_id"] != company_id:
        raise HTTPException(status_code=403, detail="Not authorised for this firm")
    upd = {f"rejoin_policy.{k}": v for k, v in payload.dict().items() if v is not None}
    if upd:
        await db.firm_masters.update_one(
            {"company_id": company_id}, {"$set": upd}, upsert=True)
    return {"ok": True, "policy": await _rejoin_policy(company_id)}


# --------------------------------------------------------------------------
# Rejoin info (wizard section A + service gap + history + policy)
# --------------------------------------------------------------------------
@router.get("/admin/employees/{user_id}/rejoin-info")
async def rejoin_info(user_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    u = await _load_employee(user_id, admin)
    company = await db.companies.find_one(
        {"company_id": u.get("company_id")}, {"_id": 0, "name": 1}) or {}
    lwd = _last_working_date(u)
    doj = _to_date(u.get("doj"))
    today = datetime.now(timezone.utc).date()
    history = await db.employment_history.find(
        {"user_id": user_id}, {"_id": 0}).sort("sequence", 1).to_list(50)
    return {
        "eligible": _is_separated(u),
        "previous": {
            "employee_code": u.get("employee_code"),
            "name": u.get("name"),
            "doj": u.get("doj"),
            "last_working_date": u.get("exit_date") or u.get("resign_date"),
            "separation_reason": u.get("employment_status") or
                ("resigned" if u.get("resign_date") else ""),
            "department": u.get("department"),
            "designation": u.get("designation"),
            "salary_monthly": u.get("salary_monthly"),
            "compliance_gross": u.get("compliance_gross"),
            "company_id": u.get("company_id"),
            "company_name": company.get("name"),
            "branch_name": u.get("branch_name"),
            "uan_no": u.get("uan_no"),
            "esi_ip_no": u.get("esi_ip_no"),
            "aadhaar_no": u.get("aadhaar_no"),
            "pan_no": u.get("pan_no"),
            "employee_type": u.get("employee_type"),
            "employee_group": u.get("employee_group"),
        },
        "service": {
            "previous_service": _service_span(doj, lwd),
            "gap_days": (today - lwd).days if lwd else None,
        },
        "employment_history": history,
        "policy": await _rejoin_policy(u.get("company_id")),
    }


@router.get("/admin/employees/{user_id}/employment-history")
async def employment_history(user_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    u = await _load_employee(user_id, admin)
    history = await db.employment_history.find(
        {"user_id": user_id}, {"_id": 0}).sort("sequence", 1).to_list(50)
    return {
        "history": history,
        "current": {
            "doj": u.get("doj"),
            "department": u.get("department"),
            "designation": u.get("designation"),
            "salary_monthly": u.get("salary_monthly"),
            "employment_status": u.get("employment_status") or "active",
            "sequence": (u.get("employment_sequence") or 1),
        },
    }


# --------------------------------------------------------------------------
# The rejoin action
# --------------------------------------------------------------------------
class RejoinPayload(BaseModel):
    rejoin_date: str
    rejoin_reason: str
    # New employment period details (only supplied fields are applied)
    employee_type: Optional[str] = None
    employee_group: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    branch_name: Optional[str] = None
    grade: Optional[str] = None
    cost_centre: Optional[str] = None
    contractor_name: Optional[str] = None
    is_onroll: Optional[bool] = None
    salary_monthly: Optional[float] = None
    compliance_basic: Optional[float] = None
    compliance_gross: Optional[float] = None
    compliance_salary_mode: Optional[str] = None
    shift_id: Optional[str] = None
    # Manual leave opening balance (used when policy = manual)
    leave_opening_balance: Optional[float] = None


@router.post("/admin/employees/{user_id}/rejoin")
async def rejoin_employee(
    user_id: str,
    payload: RejoinPayload,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    u = await _load_employee(user_id, admin)

    # ---- validations -----------------------------------------------------
    if not _is_separated(u):
        raise HTTPException(status_code=400,
                            detail="Employee is ACTIVE — only a separated "
                                   "employee can be rejoined")
    rj = _to_date(payload.rejoin_date)
    if not rj:
        raise HTTPException(status_code=400, detail="Invalid Rejoin Date")
    lwd = _last_working_date(u)
    if lwd and rj < lwd:
        raise HTTPException(
            status_code=400,
            detail=f"Rejoin Date cannot be before the Last Working Date ({lwd.isoformat()})")
    if not str(payload.rejoin_reason or "").strip():
        raise HTTPException(status_code=400, detail="Rejoin Reason is required")

    policy = await _rejoin_policy(u.get("company_id"))
    seq = int(u.get("employment_sequence") or 1)

    # ---- 1) archive the closing employment period ------------------------
    hist_doc = {
        "employment_id": f"emh_{uuid.uuid4().hex[:10]}",
        "user_id": user_id,
        "company_id": u.get("company_id"),
        "sequence": seq,
        "employee_code": u.get("employee_code"),
        "doj": u.get("doj"),
        "lwd": u.get("exit_date") or u.get("resign_date"),
        "department": u.get("department"),
        "designation": u.get("designation"),
        "branch_name": u.get("branch_name"),
        "employee_type": u.get("employee_type"),
        "employee_group": u.get("employee_group"),
        "salary_monthly": u.get("salary_monthly"),
        "compliance_basic": u.get("compliance_basic"),
        "compliance_gross": u.get("compliance_gross"),
        "reason_for_leaving": u.get("employment_status") or
            ("resigned" if u.get("resign_date") else ""),
        "status": "closed",
        "archived_at": _now_iso(),
        "archived_by": admin["user_id"],
    }
    await db.employment_history.insert_one(dict(hist_doc))

    # ---- 2) employee code policy -----------------------------------------
    old_code = u.get("employee_code")
    new_code = old_code
    if str(policy.get("employee_code")) == "new":
        try:
            gen = await _next_employee_code(u.get("company_id"))
            if gen:
                new_code = gen
        except Exception:
            logger.warning("[rejoin] new code generation failed", exc_info=True)

    # ---- 3) build the new employment period on the SAME master -----------
    updates: Dict[str, Any] = {
        "doj": rj.isoformat(),
        "employment_status": "active",
        "active": True,
        "employee_code": new_code,
        "rejoin_date": rj.isoformat(),
        "rejoin_reason": payload.rejoin_reason.strip(),
        "employment_sequence": seq + 1,
        "rejoined_at": _now_iso(),
        "rejoined_by": admin["user_id"],
    }
    if new_code != old_code and old_code:
        prev_codes = list(u.get("previous_employee_codes") or [])
        if old_code not in prev_codes:
            prev_codes.append(old_code)
        updates["previous_employee_codes"] = prev_codes
    for f in ("employee_type", "employee_group", "department", "designation",
              "branch_name", "grade", "cost_centre", "contractor_name",
              "shift_id", "compliance_salary_mode"):
        v = getattr(payload, f)
        if v is not None and str(v).strip() != "":
            updates[f] = str(v).strip()
    if payload.is_onroll is not None:
        updates["is_onroll"] = bool(payload.is_onroll)
    if payload.salary_monthly is not None and payload.salary_monthly > 0:
        updates["salary_monthly"] = round(float(payload.salary_monthly), 2)
    if payload.compliance_basic is not None and payload.compliance_basic > 0:
        _basic = round(float(payload.compliance_basic), 2)
        _allow = u.get("compliance_salary_allowances") or []
        _mode = (payload.compliance_salary_mode
                 or u.get("compliance_salary_mode") or "monthly")
        updates["compliance_basic"] = _basic
        updates["compliance_gross"] = (
            round(float(payload.compliance_gross), 2)
            if payload.compliance_gross else compliance_gross_total(_basic, _allow))
        updates["salary_structure_compliance"] = build_compliance_structure(
            _basic, _allow, _mode)
    elif payload.compliance_gross is not None and payload.compliance_gross > 0:
        updates["compliance_gross"] = round(float(payload.compliance_gross), 2)

    # UAN / ESIC IP continue UNCHANGED — never re-issued on rehire.
    # ---- 4) leave policy ---------------------------------------------------
    leave_mode = str(policy.get("leave_balance") or "continue")
    if leave_mode == "reset":
        updates["cl_allowed_override"] = None
        updates["pl_allowed_override"] = None
        updates["leave_opening_balance"] = 0
    elif leave_mode == "manual" and payload.leave_opening_balance is not None:
        updates["leave_opening_balance"] = round(float(payload.leave_opening_balance), 2)
    # "continue" — leave everything as-is.

    # gratuity policy is read at report time (continue previous service or
    # fresh) — stamp the decision on the new period for the reports.
    updates["gratuity_service_policy"] = str(policy.get("gratuity_service") or "continue")

    # Clear separation markers LAST (unsets below).
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": updates,
         "$unset": {"resign_date": "", "exit_date": ""}})

    # ---- 5) immutable audit ------------------------------------------------
    try:
        ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() \
            or (request.client.host if request.client else "")
    except Exception:
        ip = ""
    await db.rejoin_audit.insert_one({
        "audit_id": f"rja_{uuid.uuid4().hex[:10]}",
        "user_id": user_id,
        "employee_name": u.get("name"),
        "company_id": u.get("company_id"),
        "previous_status": u.get("employment_status") or "separated",
        "new_status": "active",
        "previous_code": old_code,
        "new_code": new_code,
        "rejoin_date": rj.isoformat(),
        "rejoin_reason": payload.rejoin_reason.strip(),
        "salary_changed": bool(payload.salary_monthly or payload.compliance_basic),
        "department_change": {"from": u.get("department"),
                              "to": updates.get("department", u.get("department"))},
        "policy_applied": policy,
        "by_user_id": admin["user_id"],
        "by_name": admin.get("name"),
        "ip_address": ip,
        "at": _now_iso(),
    })

    # ---- 6) notifications (best-effort firm broadcast) ---------------------
    try:
        from utils.ws_broker import broker as _ws
        await _ws.broadcast_firm(u.get("company_id"), {
            "type": "employee.rejoined",
            "user_id": user_id,
            "name": u.get("name"),
            "rejoin_date": rj.isoformat(),
        })
    except Exception:
        pass

    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0, "pin_hash": 0})
    return {
        "ok": True,
        "employee": fresh,
        "employment_history_id": hist_doc["employment_id"],
        "employee_code": new_code,
        "message": (
            f"{u.get('name')} rejoined from {rj.isoformat()} "
            f"(employment period #{seq + 1}). UAN/ESIC continue unchanged; "
            "attendance & payroll restart from the rejoin date."
        ),
    }
