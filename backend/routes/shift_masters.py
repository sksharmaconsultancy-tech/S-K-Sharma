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
