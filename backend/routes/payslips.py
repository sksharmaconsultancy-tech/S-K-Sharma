"""Iter 86 - Route module: Payslips (employee-facing + admin create).

Endpoints:
  * GET   /payslips                     - Employee's own processed slips.
  * POST  /payslips                     - Admin issues a payslip (marks
                                           it paid immediately).
  * PATCH /payslips/{slip_id}/mark-paid - Admin marks a pending slip paid.

Kept in `server.py` (for now, until the salary-run/PDF utilities are
also extracted):
  * GET /salary/monthly              - 6-month history w/ auto-pending.
  * GET /me/payslips/{slip_id}.pdf   - Employee self-service PDF.
  * Helper fns (`_month_is_before_doj`, `_month_is_complete`,
    `_payslip_is_processed`) - shared with the still-monolithic
    admin salary-run endpoints (referenced at server.py:12393 etc.).
    We import them here from `server`.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    PayslipCreate,
    _month_is_complete,
    _payslip_is_processed,
)

router = APIRouter(prefix="/api", tags=["payslips"])


@router.get("/payslips")
async def my_payslips(authorization: Optional[str] = Header(None)):
    """Employee's own payslip listing. Iter 57: only completed months +
    processed slips are visible to employees. Admins can still access the
    full history via the admin salary-run endpoints."""
    user = await get_user_from_token(authorization)
    now = datetime.now(timezone.utc)
    raw = await db.payslips.find(
        {"employee_user_id": user["user_id"]}, {"_id": 0},
    ).sort("month", -1).to_list(120)
    slips = [
        s for s in raw
        if _month_is_complete(s.get("month", ""), now) and _payslip_is_processed(s)
    ]
    return {"payslips": slips}


@router.post("/payslips")
async def create_payslip(payload: PayslipCreate, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    slip = payload.model_dump()
    slip["slip_id"] = f"ps_{uuid.uuid4().hex[:12]}"
    slip["created_at"] = now_iso()
    slip["created_by"] = user["user_id"]
    slip["status"] = "paid"
    # Attach company_id from admin's context
    if user["role"] == "company_admin":
        slip["company_id"] = user.get("company_id")
    else:
        # Super admin: derive from the target employee
        emp = await db.users.find_one({"user_id": payload.employee_user_id}, {"_id": 0})
        slip["company_id"] = emp.get("company_id") if emp else None
    # Replace any existing pending record for the same employee+month
    await db.payslips.delete_many({
        "employee_user_id": payload.employee_user_id,
        "month": payload.month,
        "status": "pending",
    })
    await db.payslips.insert_one(slip)
    return {k: v for k, v in slip.items() if k != "_id"}


@router.patch("/payslips/{slip_id}/mark-paid")
async def mark_payslip_paid(slip_id: str,
                            authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    r = await db.payslips.update_one(
        {"slip_id": slip_id},
        {"$set": {"status": "paid", "paid_at": now_iso(),
                  "paid_by": user["user_id"]}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Payslip not found")
    return await db.payslips.find_one({"slip_id": slip_id}, {"_id": 0})
