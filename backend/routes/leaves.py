"""Iter 86 - Route module: Leaves.

Endpoints:
  * POST  /leaves               - Employee creates a leave request.
  * GET   /leaves?scope=mine|all - Employee sees own; admin sees firm.
  * PATCH /leaves/{leave_id}    - Admin approves/rejects a leave.
"""
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    LeaveCreate,
    LeaveDecision,
)

router = APIRouter(prefix="/api", tags=["leaves"])


@router.post("/leaves")
async def create_leave(payload: LeaveCreate, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)

    # Iter 150 (user directive) — AUTO-BLOCK requests that exceed the
    # employee's remaining CL/PL balance for the year. Balance = per-employee
    # manual override (if set) else Firm Master Leave Policy limit, minus
    # already approved + still-pending CL/PL days this year. Enforced only
    # when the firm has CL/PL enabled OR the employee has a manual override,
    # so firms without a leave policy are unaffected.
    if payload.leave_type in ("casual", "earned"):
        from datetime import date as _date
        try:
            f = _date.fromisoformat(str(payload.from_date)[:10])
            t = _date.fromisoformat(str(payload.to_date)[:10])
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid leave dates")
        requested = (t - f).days + 1
        if requested <= 0:
            raise HTTPException(status_code=400, detail="'To' date must not be before 'From' date")

        kind = "CL" if payload.leave_type == "casual" else "PL"
        fm = await db.firm_masters.find_one(
            {"company_id": user.get("company_id")}, {"_id": 0, "leave_policy": 1},
        ) if user.get("company_id") else None
        lp = (fm or {}).get("leave_policy") or {}
        me = await db.users.find_one(
            {"user_id": user["user_id"]},
            {"_id": 0, "cl_allowed_override": 1, "pl_allowed_override": 1}) or {}
        override = me.get("cl_allowed_override" if kind == "CL" else "pl_allowed_override")
        firm_limit = float(lp.get("cl_day_limit" if kind == "CL" else "pl_day_limit") or 0)
        allowed = float(override) if override is not None else firm_limit
        enforce = bool(lp.get("cl_pl_applicable")) or override is not None

        if enforce:
            year = f.year
            y_start, y_end = _date(year, 1, 1), _date(year, 12, 31)
            taken = 0.0
            async for lv in db.leaves.find(
                {
                    "user_id": user["user_id"],
                    "leave_type": payload.leave_type,
                    "status": {"$in": ["approved", "pending"]},
                    "from_date": {"$lte": y_end.isoformat()},
                    "to_date": {"$gte": y_start.isoformat()},
                },
                {"_id": 0, "from_date": 1, "to_date": 1},
            ):
                try:
                    lf = max(_date.fromisoformat(str(lv["from_date"])[:10]), y_start)
                    lt_ = min(_date.fromisoformat(str(lv["to_date"])[:10]), y_end)
                except (ValueError, TypeError):
                    continue
                d = (lt_ - lf).days + 1
                if d > 0:
                    taken += d
            balance = max(0.0, allowed - taken)
            if requested > balance:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Insufficient {kind} balance: you have {balance:g} day(s) left "
                        f"({allowed:g} allowed − {taken:g} already used/pending in {year}) "
                        f"but requested {requested} day(s)."
                    ),
                )

    leave = {
        "leave_id": f"lv_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "company_id": user.get("company_id"),
        "user_name": user["name"],
        "user_email": user["email"],
        "leave_type": payload.leave_type,
        "from_date": payload.from_date,
        "to_date": payload.to_date,
        "reason": payload.reason,
        "status": "pending",
        "admin_comment": None,
        "decided_by": None,
        "created_at": now_iso(),
    }
    await db.leaves.insert_one(leave)
    # Iter 103 — automated email trigger
    try:
        from routes.email_notifications import fire_email_event
        await fire_email_event(
            "leave_applied", company_id=user.get("company_id"),
            employee_user_id=user["user_id"],
            details=f"{payload.leave_type} leave from {payload.from_date} to {payload.to_date}")
    except Exception:
        pass
    return {k: v for k, v in leave.items() if k != "_id"}


@router.get("/leaves")
async def list_leaves(
    scope: str = Query("mine", pattern="^(mine|all)$"),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    q = {}
    if scope == "mine":
        q = {"user_id": user["user_id"]}
    else:
        require_role(user, ["company_admin", "super_admin"])
        # Company admin sees only their company. Super admin sees all.
        if user["role"] == "company_admin" and user.get("company_id"):
            q = {"company_id": user["company_id"]}
    leaves = await db.leaves.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"leaves": leaves}


@router.patch("/leaves/{leave_id}")
async def decide_leave(leave_id: str, payload: LeaveDecision,
                       authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin"])
    r = await db.leaves.update_one(
        {"leave_id": leave_id},
        {"$set": {"status": payload.status,
                  "admin_comment": payload.comment,
                  "decided_by": user["name"],
                  "decided_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Leave not found")
    leave = await db.leaves.find_one({"leave_id": leave_id}, {"_id": 0})
    # Iter 77n - broadcast leave decision to admins + the employee.
    try:
        from utils.ws_broker import broker as _ws
        _ev = {
            "type": f"leave.{payload.status}",
            "leave_id": leave_id,
            "user_id": leave.get("user_id"),
            "status": payload.status,
            "leave_type": leave.get("leave_type"),
            "from_date": leave.get("from_date"),
            "to_date": leave.get("to_date"),
            "decided_by": user["name"],
        }
        await _ws.broadcast_firm(leave.get("company_id") or "", _ev)
        await _ws.broadcast_user(leave.get("user_id") or "", _ev)
    except Exception:
        pass
    # Iter 103 — automated email trigger
    try:
        from routes.email_notifications import fire_email_event
        _evk = "leave_approved" if payload.status == "approved" else "leave_rejected"
        await fire_email_event(
            _evk, company_id=leave.get("company_id"),
            employee_user_id=leave.get("user_id"),
            details=f"{leave.get('leave_type')} leave {leave.get('from_date')} → {leave.get('to_date')}")
    except Exception:
        pass
    # Iter 145 — web-push the leave decision to the employee's devices.
    try:
        from routes.web_push import push_to_user
        _st = payload.status
        _emoji = "✅" if _st == "approved" else "❌"
        await push_to_user(
            leave.get("user_id") or "",
            f"Leave {_st} {_emoji}",
            f"Your {leave.get('leave_type')} leave ({leave.get('from_date')} → "
            f"{leave.get('to_date')}) was {_st} by {user['name']}.",
            url="/leaves", tag=f"leave_{leave_id}")
    except Exception:
        pass
    return leave


@router.get("/admin/leave-report")
async def leave_report(
    company_id: Optional[str] = Query(None),
    year: int = Query(...),
    authorization: Optional[str] = Header(None),
):
    """Iter 98 — Leave Report (Reports section).

    Per employee for the given calendar year:
      * CL / PL allowed  — from Firm Master → Leave Policy limits.
      * CL / PL taken    — approved leaves (casual → CL, earned → PL),
        clipped to the year window.
      * Balance          — allowed − taken (floored at 0).
    """
    from datetime import date

    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if admin["role"] == "sub_admin" and company_id:
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")

    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "leave_policy": 1},
    )
    lp = (fm or {}).get("leave_policy") or {}
    cl_allowed = float(lp.get("cl_day_limit") or 0)
    pl_allowed = float(lp.get("pl_day_limit") or 0)

    emps = await db.users.find(
        {"role": "employee", "company_id": company_id},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "designation": 1,
         "cl_allowed_override": 1, "pl_allowed_override": 1},
    ).to_list(10000)

    y_start = date(year, 1, 1)
    y_end = date(year, 12, 31)
    taken: dict = {}
    async for lv in db.leaves.find(
        {
            "company_id": company_id,
            "status": "approved",
            "from_date": {"$lte": y_end.isoformat()},
            "to_date": {"$gte": y_start.isoformat()},
        },
        {"_id": 0, "user_id": 1, "leave_type": 1, "from_date": 1, "to_date": 1},
    ):
        try:
            f = max(date.fromisoformat(str(lv["from_date"])[:10]), y_start)
            t = min(date.fromisoformat(str(lv["to_date"])[:10]), y_end)
        except (ValueError, TypeError):
            continue
        d = (t - f).days + 1
        if d <= 0:
            continue
        b = taken.setdefault(lv["user_id"], {"cl": 0.0, "pl": 0.0, "other": 0.0})
        lt = lv.get("leave_type")
        if lt == "casual":
            b["cl"] += d
        elif lt == "earned":
            b["pl"] += d
        else:
            b["other"] += d

    rows = []
    for e in emps:
        t = taken.get(e["user_id"]) or {"cl": 0.0, "pl": 0.0, "other": 0.0}
        # Iter 149 — per-employee manual CL/PL override (None = firm default).
        clo = e.get("cl_allowed_override")
        plo = e.get("pl_allowed_override")
        cl_i = float(clo) if clo is not None else cl_allowed
        pl_i = float(plo) if plo is not None else pl_allowed
        rows.append({
            "user_id": e["user_id"],
            "employee_code": e.get("employee_code"),
            "name": e.get("name"),
            "designation": e.get("designation"),
            "cl_allowed": cl_i,
            "cl_taken": t["cl"],
            "cl_balance": max(0.0, cl_i - t["cl"]),
            "pl_allowed": pl_i,
            "pl_taken": t["pl"],
            "pl_balance": max(0.0, pl_i - t["pl"]),
            "other_taken": t["other"],
            "total_taken": t["cl"] + t["pl"] + t["other"],
            "is_override": clo is not None or plo is not None,
        })

    def _code_key(r):
        c = str(r.get("employee_code") or "").strip()
        try:
            return (0, float(c), "")
        except ValueError:
            return (1, 0.0, c.lower())

    rows.sort(key=_code_key)
    return {
        "company_id": company_id,
        "year": year,
        "cl_pl_applicable": bool(lp.get("cl_pl_applicable")),
        "cl_allowed": cl_allowed,
        "pl_allowed": pl_allowed,
        "rows": rows,
        "employees_count": len(rows),
    }


@router.get("/leaves/balance")
async def my_leave_balance(authorization: Optional[str] = Header(None)):
    """Iter 99 — employee self-service CL/PL balance (current year).
    Allowed limits come from Firm Master → Leave Policy; taken = own
    approved leaves (casual → CL, earned → PL)."""
    from datetime import date

    user = await get_user_from_token(authorization)
    company_id = user.get("company_id")
    year = date.today().year
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "leave_policy": 1},
    ) if company_id else None
    lp = (fm or {}).get("leave_policy") or {}
    cl_allowed = float(lp.get("cl_day_limit") or 0)
    pl_allowed = float(lp.get("pl_day_limit") or 0)
    # Iter 149 — per-employee manual override wins over the firm default.
    me = await db.users.find_one(
        {"user_id": user["user_id"]},
        {"_id": 0, "cl_allowed_override": 1, "pl_allowed_override": 1}) or {}
    if me.get("cl_allowed_override") is not None:
        cl_allowed = float(me["cl_allowed_override"])
    if me.get("pl_allowed_override") is not None:
        pl_allowed = float(me["pl_allowed_override"])

    y_start = date(year, 1, 1)
    y_end = date(year, 12, 31)
    cl_taken = pl_taken = other_taken = 0.0
    async for lv in db.leaves.find(
        {
            "user_id": user["user_id"],
            "status": "approved",
            "from_date": {"$lte": y_end.isoformat()},
            "to_date": {"$gte": y_start.isoformat()},
        },
        {"_id": 0, "leave_type": 1, "from_date": 1, "to_date": 1},
    ):
        try:
            f = max(date.fromisoformat(str(lv["from_date"])[:10]), y_start)
            t = min(date.fromisoformat(str(lv["to_date"])[:10]), y_end)
        except (ValueError, TypeError):
            continue
        d = (t - f).days + 1
        if d <= 0:
            continue
        lt = lv.get("leave_type")
        if lt == "casual":
            cl_taken += d
        elif lt == "earned":
            pl_taken += d
        else:
            other_taken += d

    return {
        "year": year,
        "cl_pl_applicable": bool(lp.get("cl_pl_applicable")),
        # Iter 150 — True when the auto-block rule applies to this employee
        # (firm policy ON or a manual per-employee override exists).
        "enforced": bool(lp.get("cl_pl_applicable"))
                    or me.get("cl_allowed_override") is not None
                    or me.get("pl_allowed_override") is not None,
        "cl_allowed": cl_allowed,
        "cl_taken": cl_taken,
        "cl_balance": max(0.0, cl_allowed - cl_taken),
        "pl_allowed": pl_allowed,
        "pl_taken": pl_taken,
        "pl_balance": max(0.0, pl_allowed - pl_taken),
        "other_taken": other_taken,
    }


# ---------------------------------------------------------------------------
# Iter 149 — Manual CL/PL balance per employee (admin config).
# ---------------------------------------------------------------------------
@router.get("/admin/leave-balance-config")
async def leave_balance_config(
    company_id: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    """Employees of a firm with their manual CL/PL overrides (None = firm
    default) + the firm's default limits, for the config screen."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id") or company_id
    if admin["role"] == "sub_admin":
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")

    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "leave_policy": 1})
    lp = (fm or {}).get("leave_policy") or {}
    emps = await db.users.find(
        {"role": "employee", "company_id": company_id},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "designation": 1,
         "cl_allowed_override": 1, "pl_allowed_override": 1},
    ).to_list(10000)

    def _code_key(r):
        c = str(r.get("employee_code") or "").strip()
        try:
            return (0, float(c), "")
        except ValueError:
            return (1, 0.0, c.lower())

    emps.sort(key=_code_key)
    return {
        "company_id": company_id,
        "cl_default": float(lp.get("cl_day_limit") or 0),
        "pl_default": float(lp.get("pl_day_limit") or 0),
        "cl_pl_applicable": bool(lp.get("cl_pl_applicable")),
        "employees": emps,
    }


@router.patch("/admin/leave-balance")
async def set_leave_balance(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Set / clear the manual CL/PL allowance for ONE employee.
    Body: {user_id, cl_allowed: number|null, pl_allowed: number|null}
    (null clears the override → firm default applies)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    target = await db.users.find_one(
        {"user_id": user_id}, {"_id": 0, "user_id": 1, "company_id": 1, "role": 1})
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and target.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Employee is outside your firm")
    if admin["role"] == "sub_admin":
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, target.get("company_id")):
            raise HTTPException(status_code=403, detail="Employee's firm is outside your assigned scope")

    updates: Dict[str, Any] = {}
    for key, field in (("cl_allowed", "cl_allowed_override"),
                       ("pl_allowed", "pl_allowed_override")):
        if key in payload:
            v = payload[key]
            if v is None or v == "":
                updates[field] = None
            else:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail=f"{key} must be a number")
                if v < 0 or v > 366:
                    raise HTTPException(status_code=400, detail=f"{key} must be between 0 and 366")
                updates[field] = v
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    updates["leave_balance_set_by"] = admin["user_id"]
    updates["leave_balance_set_at"] = now_iso()
    await db.users.update_one({"user_id": user_id}, {"$set": updates})
    return {"ok": True, **{k: v for k, v in updates.items()
                           if k.endswith("_override")}}
