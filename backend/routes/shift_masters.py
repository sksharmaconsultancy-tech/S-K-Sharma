"""Iter 86 - Route module: Shift Masters (global catalogue).

Endpoints:
  * GET    /shift-masters              - List all shifts.
  * POST   /shift-masters               - Create (super_admin only).
  * PATCH  /shift-masters/{shift_id}    - Update (super_admin only).
  * DELETE /shift-masters/{shift_id}    - Delete (super_admin only).
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    ShiftMasterIn,
    _validate_hhmm,
)

router = APIRouter(prefix="/api", tags=["shift-masters"])


def _duty_hours(start: str, end: str) -> float:
    """Iter 139 — auto-calculated duty hours from In/Out time (overnight
    shifts wrap past midnight)."""
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    mins = eh * 60 + em - (sh * 60 + sm)
    if mins <= 0:
        mins += 24 * 60
    return round(mins / 60, 2)


@router.get("/shift-masters")
async def list_shift_masters(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    shifts = await db.shift_masters.find(
        {}, {"_id": 0},
    ).sort("name", 1).to_list(500)
    return {"shifts": shifts}


@router.post("/shift-masters")
async def create_shift_master(
    payload: ShiftMasterIn,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin"])
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Shift name is required.")
    start = _validate_hhmm(payload.start, "Start time")
    end = _validate_hhmm(payload.end, "End time")
    clash = await db.shift_masters.find_one(
        {"name": {"$regex": f"^{name}$", "$options": "i"}},
        {"_id": 0, "shift_id": 1},
    )
    if clash:
        raise HTTPException(
            status_code=409,
            detail=f"A shift named '{name}' already exists in the master catalogue.",
        )
    doc = {
        "shift_id": f"sh_{uuid.uuid4().hex[:12]}",
        "name": name,
        "start": start,
        "end": end,
        "duty_hours": _duty_hours(start, end),
        "description": (payload.description or "").strip() or None,
        "created_at": now_iso(),
        "created_by": user["user_id"],
        "updated_at": now_iso(),
    }
    await db.shift_masters.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "shift": doc}


@router.patch("/shift-masters/{shift_id}")
async def update_shift_master(
    shift_id: str,
    payload: ShiftMasterIn,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin"])
    shift = await db.shift_masters.find_one({"shift_id": shift_id}, {"_id": 0})
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")
    updates: dict = {}
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Shift name cannot be empty")
        if name.lower() != (shift.get("name") or "").lower():
            clash = await db.shift_masters.find_one({
                "name": {"$regex": f"^{name}$", "$options": "i"},
                "shift_id": {"$ne": shift_id},
            }, {"_id": 0, "shift_id": 1})
            if clash:
                raise HTTPException(
                    status_code=409,
                    detail=f"Another shift named '{name}' already exists.",
                )
        updates["name"] = name
    if payload.start is not None:
        updates["start"] = _validate_hhmm(payload.start, "Start time")
    if payload.end is not None:
        updates["end"] = _validate_hhmm(payload.end, "End time")
    if payload.description is not None:
        updates["description"] = payload.description.strip() or None
    if "start" in updates or "end" in updates:
        updates["duty_hours"] = _duty_hours(
            updates.get("start", shift.get("start") or "09:00"),
            updates.get("end", shift.get("end") or "18:00"),
        )
    if updates:
        updates["updated_at"] = now_iso()
        updates["updated_by"] = user["user_id"]
        await db.shift_masters.update_one({"shift_id": shift_id}, {"$set": updates})
    fresh = await db.shift_masters.find_one({"shift_id": shift_id}, {"_id": 0})
    return {"ok": True, "shift": fresh}


@router.delete("/shift-masters/{shift_id}")
async def delete_shift_master(
    shift_id: str,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin"])
    r = await db.shift_masters.delete_one({"shift_id": shift_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Shift not found")
    return {"ok": True, "deleted_shift_id": shift_id}


# ---------------------------------------------------------------------------
# Iter 278 (user request) — Company-wise shift assignment from Shift Master.
# The firm picks WHICH master shifts apply to it; employee-wise shift
# dropdowns then only offer the firm's selected shifts. Saving also syncs
# ``attendance_policy.shifts`` so the attendance engine keeps working.
# ---------------------------------------------------------------------------
@router.get("/companies/{company_id}/assigned-shifts")
async def get_company_shifts(
    company_id: str,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    if user.get("role") == "company_admin" and user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorised for this firm")
    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "assigned_shift_ids": 1, "name": 1},
    )
    if not company:
        raise HTTPException(status_code=404, detail="Firm not found")
    ids = company.get("assigned_shift_ids") or []
    shifts = await db.shift_masters.find(
        {"shift_id": {"$in": ids}}, {"_id": 0},
    ).sort("name", 1).to_list(200)
    return {"company_id": company_id, "shift_ids": ids, "shifts": shifts}


@router.put("/companies/{company_id}/assigned-shifts")
async def set_company_shifts(
    company_id: str,
    payload: dict,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin"])
    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "company_id": 1},
    )
    if not company:
        raise HTTPException(status_code=404, detail="Firm not found")
    raw_ids = payload.get("shift_ids")
    if not isinstance(raw_ids, list):
        raise HTTPException(status_code=400, detail="shift_ids must be a list")
    ids = [str(i) for i in raw_ids if str(i).strip()]
    shifts = await db.shift_masters.find(
        {"shift_id": {"$in": ids}}, {"_id": 0},
    ).to_list(200)
    found = {s["shift_id"] for s in shifts}
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(status_code=400,
                            detail=f"Unknown shift_ids: {', '.join(missing)}")
    # Preserve the order the admin selected.
    by_id = {s["shift_id"]: s for s in shifts}
    ordered = [by_id[i] for i in ids]
    await db.companies.update_one(
        {"company_id": company_id},
        {"$set": {
            "assigned_shift_ids": ids,
            # Keep the attendance engine + Employee Master shift pickers in
            # sync: the firm policy's shift list mirrors the selection.
            "attendance_policy.shifts": [
                {"name": s["name"], "start": s["start"], "end": s["end"]}
                for s in ordered
            ],
            "updated_at": now_iso(),
        }},
    )
    return {"ok": True, "company_id": company_id,
            "shift_ids": ids, "shifts": ordered}
