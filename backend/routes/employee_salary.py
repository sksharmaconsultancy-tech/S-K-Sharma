"""Iter 89 — Employee Salary Update route.

Focused endpoint for updating an employee's salary structure — both the
ACTUAL salary (what the employee receives in-hand) and the COMPLIANCE
salary (what appears on statutory registers for PF/ESI/TDS).

  * PATCH /api/admin/employees/{user_id}/salary

Payload accepts (all optional — only sent keys are updated):
  {
    "salary_monthly":            <number>,           # monthly gross
    "salary_structure_actual":   [{head, amount}],   # actual break-up
    "salary_structure_compliance": [{head, amount}], # compliance break-up
    "notes":                     <string>,           # optional audit note
  }

Access control:
  - super_admin: any employee
  - company_admin / sub_admin: only employees of their firm
  - regular employee: 403

Every update is written to ``salary_history`` for audit trail.
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


router = APIRouter(prefix="/api/admin", tags=["employee-salary"])


def _round_amount(v: Any) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


_RATE_TYPES = {"daily", "monthly", "hourly"}


def _sanitise_structure(rows: Any) -> list:
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        head = (row.get("head") or "").strip()
        if not head:
            continue
        item: Dict[str, Any] = {"head": head, "amount": _round_amount(row.get("amount"))}
        # Optional extras used by the ACTUAL structure fixed layout:
        #   rate_type    — Basic Salary pay basis (daily / monthly / hourly)
        #   working_days — days count for Salary 1 / 2 / 3 rows
        rate = (row.get("rate_type") or "").strip().lower()
        if rate in _RATE_TYPES:
            item["rate_type"] = rate
        if "working_days" in row:
            item["working_days"] = _round_amount(row.get("working_days"))
        out.append(item)
    return out


@router.get("/employees/{user_id}/salary")
async def get_employee_salary(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    emp = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "pin_hash": 0, "password_hash": 0, "face_reference_base64": 0},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] in ("company_admin", "sub_admin") and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's employee")

    # Firm Master linkage — only allowance/deduction heads ENABLED on the
    # employee's firm appear in the Employee Master salary editor.
    firm_allowance_heads: list = []
    firm_deduction_heads: list = []
    if emp.get("company_id"):
        fm = await db.firm_masters.find_one(
            {"company_id": emp["company_id"]},
            {"_id": 0, "allowances": 1, "deductions": 1},
        ) or {}
        firm_allowance_heads = [k for k, v in (fm.get("allowances") or {}).items() if v]
        firm_deduction_heads = [k for k, v in (fm.get("deductions") or {}).items() if v]

    return {
        "user_id": emp["user_id"],
        "name": emp.get("name"),
        "employee_code": emp.get("employee_code"),
        "company_id": emp.get("company_id"),
        "employee_type": emp.get("employee_type"),
        "salary_monthly": emp.get("salary_monthly") or 0,
        "salary_structure_actual": emp.get("salary_structure_actual") or [],
        "salary_structure_compliance": emp.get("salary_structure_compliance") or [],
        "actual_salary_allowances": emp.get("actual_salary_allowances") or [],
        "actual_salary_deductions": emp.get("actual_salary_deductions") or [],
        "firm_allowance_heads": firm_allowance_heads,
        "firm_deduction_heads": firm_deduction_heads,
        "salary_updated_at": emp.get("salary_updated_at"),
        "salary_updated_by": emp.get("salary_updated_by"),
        # Recent audit trail so the UI can show a "last N changes" ribbon.
        "history": [
            {k: v for k, v in h.items() if k != "_id"}
            for h in await db.salary_history.find(
                {"user_id": user_id}, {"_id": 0},
            ).sort("changed_at", -1).limit(10).to_list(10)
        ],
    }


@router.patch("/employees/{user_id}/salary")
async def update_employee_salary(
    user_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])

    emp = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "pin_hash": 0, "password_hash": 0, "face_reference_base64": 0},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] in ("company_admin", "sub_admin") and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's employee")

    # Build the update patch — only include keys the caller sent.
    to_set: Dict[str, Any] = {}
    if "salary_monthly" in payload:
        to_set["salary_monthly"] = _round_amount(payload["salary_monthly"])
    if "salary_structure_actual" in payload:
        to_set["salary_structure_actual"] = _sanitise_structure(payload["salary_structure_actual"])
    if "salary_structure_compliance" in payload:
        to_set["salary_structure_compliance"] = _sanitise_structure(payload["salary_structure_compliance"])
    if "actual_salary_allowances" in payload:
        to_set["actual_salary_allowances"] = _sanitise_structure(payload["actual_salary_allowances"])
    if "actual_salary_deductions" in payload:
        to_set["actual_salary_deductions"] = _sanitise_structure(payload["actual_salary_deductions"])
    if not to_set:
        raise HTTPException(status_code=400, detail="Nothing to update")
    to_set["salary_updated_at"] = now_iso()
    to_set["salary_updated_by"] = admin["user_id"]

    # Consistency check: if both structures are provided, their totals
    # should be reasonably close to salary_monthly. We warn but don't
    # block — payroll teams sometimes intentionally split PF cap etc.
    warnings = []
    monthly = to_set.get("salary_monthly", emp.get("salary_monthly") or 0)
    for label, key in [
        ("Actual", "salary_structure_actual"),
        ("Compliance", "salary_structure_compliance"),
    ]:
        if key in to_set:
            total = sum(row["amount"] for row in to_set[key])
            if monthly and abs(total - float(monthly)) > 1.0:
                warnings.append(
                    f"{label} structure total {total:.2f} does not match "
                    f"salary_monthly {float(monthly):.2f}"
                )

    # Write audit trail BEFORE the update so we can capture prev/new.
    await db.salary_history.insert_one({
        "user_id": user_id,
        "company_id": emp.get("company_id"),
        "changed_at": now_iso(),
        "changed_by": admin["user_id"],
        "changed_by_role": admin["role"],
        "notes": (payload.get("notes") or "").strip() or None,
        "prev": {
            "salary_monthly": emp.get("salary_monthly") or 0,
            "salary_structure_actual": emp.get("salary_structure_actual") or [],
            "salary_structure_compliance": emp.get("salary_structure_compliance") or [],
            "actual_salary_allowances": emp.get("actual_salary_allowances") or [],
            "actual_salary_deductions": emp.get("actual_salary_deductions") or [],
        },
        "next": {
            "salary_monthly": to_set.get("salary_monthly", emp.get("salary_monthly") or 0),
            "salary_structure_actual": to_set.get("salary_structure_actual",
                                                  emp.get("salary_structure_actual") or []),
            "salary_structure_compliance": to_set.get("salary_structure_compliance",
                                                      emp.get("salary_structure_compliance") or []),
            "actual_salary_allowances": to_set.get("actual_salary_allowances",
                                                   emp.get("actual_salary_allowances") or []),
            "actual_salary_deductions": to_set.get("actual_salary_deductions",
                                                   emp.get("actual_salary_deductions") or []),
        },
    })

    await db.users.update_one({"user_id": user_id}, {"$set": to_set})
    logger.info(
        "[salary] emp=%s updated by %s (%s) — set %s",
        user_id, admin["user_id"], admin["role"], list(to_set.keys()),
    )

    fresh = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "pin_hash": 0, "password_hash": 0, "face_reference_base64": 0},
    ) or {}
    return {
        "ok": True,
        "warnings": warnings,
        "employee": {
            "user_id": fresh.get("user_id"),
            "salary_monthly": fresh.get("salary_monthly") or 0,
            "salary_structure_actual": fresh.get("salary_structure_actual") or [],
            "salary_structure_compliance": fresh.get("salary_structure_compliance") or [],
            "actual_salary_allowances": fresh.get("actual_salary_allowances") or [],
            "actual_salary_deductions": fresh.get("actual_salary_deductions") or [],
            "salary_updated_at": fresh.get("salary_updated_at"),
            "salary_updated_by": fresh.get("salary_updated_by"),
        },
    }
