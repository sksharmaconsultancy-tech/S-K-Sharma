"""Iter 206 — Comp-Off Ledger (user request).

Employees EARN compensatory offs by working on their weekly-off day when
the firm's Attendance Policy → Week-Off Worked Attendance has the
"Comp-Off" toggle enabled:

  worked ≥ full-day threshold → 1.0 comp-off
  worked ≥ half-day threshold → 0.5 comp-off

Earned entries are synced idempotently from the attendance grid (keyed by
user_id + date). Comp-offs are USED either by an admin manual adjustment
or automatically when a leave is approved with "Adjust against Comp-Off"
(see routes/leaves.py).

Collection ``comp_off_ledger``:
  {ledger_id, company_id, user_id, date, days, direction: earn|use,
   source: weekoff_worked|manual|leave_adjust, ref, remarks,
   created_by, created_at}
"""
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    sub_admin_can_touch_company,
)

router = APIRouter(prefix="/api", tags=["comp-off"])


async def _authz_company(admin: dict, company_id: Optional[str]) -> str:
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    return company_id


def _wow_cfg(company: dict) -> dict:
    return ((company or {}).get("attendance_policy") or {}).get("week_off_worked") or {}


async def sync_earned_for_month(company_id: str, month: str) -> int:
    """Idempotently upsert 'earn' entries for week-off days worked in the
    month. Returns the number of earn entries now present for the month."""
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Firm not found")
    wow = _wow_cfg(company)
    if not (wow.get("mode") and wow.get("comp_off")):
        return 0

    half_t = float(wow.get("half_day_threshold") or 4.0)
    full_t = float(wow.get("full_day_threshold") or 8.0)
    double_ot = bool(wow.get("double_ot"))

    from server import _compute_monthly_grid_data
    grid = await _compute_monthly_grid_data(company_id, month)
    day_full_dates = list(grid.get("day_full_dates") or [])
    day_labels = list(grid.get("day_labels") or [])
    count = 0
    for emp in grid.get("employees") or []:
        uid = emp.get("user_id")
        days = emp.get("days") or {}
        for idx, key in enumerate(day_labels):
            cell = days.get(key) or {}
            if not cell.get("weekly_off"):
                continue
            duty = float(cell.get("duty_hours") or 0.0)
            ot = float(cell.get("ot_hours") or 0.0)
            worked = duty + (ot / 2.0 if double_ot else ot)
            credit = 1.0 if worked >= full_t else (0.5 if worked >= half_t else 0.0)
            date_iso = day_full_dates[idx] if idx < len(day_full_dates) else f"{month}-{key}"
            if credit <= 0:
                # remove stale earn (e.g. punches corrected later)
                await db.comp_off_ledger.delete_many({
                    "user_id": uid, "date": date_iso,
                    "direction": "earn", "source": "weekoff_worked"})
                continue
            await db.comp_off_ledger.update_one(
                {"user_id": uid, "date": date_iso,
                 "direction": "earn", "source": "weekoff_worked"},
                {"$set": {"company_id": company_id, "days": credit,
                          "remarks": f"Worked week-off ({worked:g}h)",
                          "updated_at": now_iso()},
                 "$setOnInsert": {"ledger_id": f"cof_{uuid.uuid4().hex[:12]}",
                                  "created_at": now_iso(),
                                  "created_by": "system"}},
                upsert=True,
            )
            count += 1
    return count


async def comp_off_balance(user_id: str) -> Dict[str, float]:
    earned = used = 0.0
    async for e in db.comp_off_ledger.find({"user_id": user_id}, {"_id": 0}):
        d = float(e.get("days") or 0.0)
        if e.get("direction") == "use":
            used += d
        else:
            earned += d
    return {"earned": round(earned, 2), "used": round(used, 2),
            "balance": round(earned - used, 2)}


@router.post("/admin/comp-off/sync")
async def comp_off_sync(payload: Dict[str, Any] = Body(...),
                        authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    company_id = await _authz_company(admin, payload.get("company_id"))
    month = str(payload.get("month") or "")[:7]
    if len(month) != 7:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    n = await sync_earned_for_month(company_id, month)
    return {"ok": True, "earn_entries": n}


@router.get("/admin/comp-off/summary")
async def comp_off_summary(company_id: Optional[str] = Query(None),
                           month: Optional[str] = Query(None),
                           authorization: Optional[str] = Header(None)):
    """Per-employee earned/used/balance + full ledger. Auto-syncs the
    requested month (default: current) before returning."""
    from datetime import date, timedelta

    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    company_id = await _authz_company(admin, company_id)

    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0})
    wow = _wow_cfg(company or {})
    enabled = bool(wow.get("mode") and wow.get("comp_off"))

    m = (month or date.today().isoformat()[:7])[:7]
    if enabled:
        await sync_earned_for_month(company_id, m)
        # also refresh the previous month so month-end work isn't missed
        first = date.fromisoformat(m + "-01")
        prev = (first - timedelta(days=1)).isoformat()[:7]
        await sync_earned_for_month(company_id, prev)

    entries = await db.comp_off_ledger.find(
        {"company_id": company_id}, {"_id": 0},
    ).sort("date", -1).to_list(5000)

    emps = await db.users.find(
        {"role": "employee", "company_id": company_id},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
         "father_name": 1, "designation": 1},
    ).to_list(10000)
    per: Dict[str, Dict[str, float]] = {}
    for e in entries:
        b = per.setdefault(e["user_id"], {"earned": 0.0, "used": 0.0})
        if e.get("direction") == "use":
            b["used"] += float(e.get("days") or 0.0)
        else:
            b["earned"] += float(e.get("days") or 0.0)
    rows = []
    for u in emps:
        b = per.get(u["user_id"]) or {"earned": 0.0, "used": 0.0}
        rows.append({**u,
                     "earned": round(b["earned"], 2),
                     "used": round(b["used"], 2),
                     "balance": round(b["earned"] - b["used"], 2)})
    rows.sort(key=lambda r: (-(r["balance"]), str(r.get("name") or "").lower()))
    return {"company_id": company_id, "month": m, "enabled": enabled,
            "rows": rows, "entries": entries}


@router.post("/admin/comp-off/adjust")
async def comp_off_adjust(payload: Dict[str, Any] = Body(...),
                          authorization: Optional[str] = Header(None)):
    """Manual grant/use: {company_id?, user_id, days, direction, remarks}."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    user_id = payload.get("user_id")
    direction = str(payload.get("direction") or "").lower()
    try:
        days = float(payload.get("days") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="days must be a number")
    if not user_id or direction not in ("earn", "use") or days <= 0 or days > 31:
        raise HTTPException(status_code=400,
                            detail="user_id, direction (earn|use) and days (0–31) are required")
    target = await db.users.find_one({"user_id": user_id},
                                     {"_id": 0, "company_id": 1, "name": 1})
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    await _authz_company(admin, target.get("company_id"))
    if direction == "use":
        bal = await comp_off_balance(user_id)
        if days > bal["balance"]:
            raise HTTPException(status_code=400,
                                detail=f"Insufficient comp-off balance ({bal['balance']:g} day(s) available)")
    entry = {
        "ledger_id": f"cof_{uuid.uuid4().hex[:12]}",
        "company_id": target.get("company_id"),
        "user_id": user_id,
        "date": now_iso()[:10],
        "days": days,
        "direction": direction,
        "source": "manual",
        "ref": None,
        "remarks": payload.get("remarks") or "",
        "created_by": admin["user_id"],
        "created_at": now_iso(),
    }
    await db.comp_off_ledger.insert_one(dict(entry))
    return {"ok": True, "entry": entry,
            "balance": await comp_off_balance(user_id)}


@router.get("/comp-off/my")
async def comp_off_my(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    entries = await db.comp_off_ledger.find(
        {"user_id": user["user_id"]}, {"_id": 0},
    ).sort("date", -1).to_list(200)
    return {**(await comp_off_balance(user["user_id"])), "entries": entries}
