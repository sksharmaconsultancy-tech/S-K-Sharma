"""Iter 104 — Hospital shift-change workflow.

Rules requested by the client (hospital use-case, 8h = Present, 4h = Half
Day — already modelled by the "hospital" attendance-policy preset):

  * An employee may request a shift change ONLY BEFORE punching in for
    that day.
  * The request needs EMPLOYER APPROVAL.
  * On approval the admin MUST allot the vacated shift to a replacement
    employee who can join on time (mandatory swap).
  * Both employees get an in-app notification:
      "Today your shift is <name> (<start> – <end>). Please punch in timely."
    plus an optional automated email (trigger: shift_allotted).

Endpoints:
  * GET  /shift-change/options                    (employee — shifts + current)
  * POST /shift-change-requests                   (employee)
  * GET  /shift-change-requests                   (employee: own · admin: firm)
  * POST /admin/shift-change-requests/{id}/decide (approve — replacement mandatory / reject)
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
)

router = APIRouter(prefix="/api", tags=["shift-change"])

IST = timezone(timedelta(hours=5, minutes=30))


def _today_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


async def _company_shifts(company_id: Optional[str]) -> list:
    """Shifts from the firm's attendance policy, else the global masters."""
    shifts = []
    if company_id:
        co = await db.companies.find_one(
            {"company_id": company_id}, {"_id": 0, "attendance_policy": 1})
        shifts = ((co or {}).get("attendance_policy") or {}).get("shifts") or []
    if not shifts:
        shifts = [
            {"name": s.get("name"), "start": s.get("start"), "end": s.get("end")}
            async for s in db.shift_masters.find({}, {"_id": 0})
        ]
    return [s for s in shifts if s.get("name")]


def _shift_label(shift: Optional[dict]) -> str:
    if not shift:
        return ""
    t = f" ({shift.get('start')} – {shift.get('end')})" if shift.get("start") else ""
    return f"{shift.get('name')}{t}"


async def _has_punched(user_id: str, date: str) -> bool:
    rec = await db.attendance.find_one(
        {"user_id": user_id, "date": date, "status": {"$ne": "rejected"}},
        {"_id": 0, "record_id": 1})
    return bool(rec)


async def _notify_shift(user_id: str, company_id: Optional[str], shift: dict,
                        date: str) -> None:
    """In-app 'today is your shift' notification + optional email."""
    label = _shift_label(shift)
    title = "Your shift for today" if date == _today_ist() else f"Your shift for {date}"
    body = f"Today your shift is {label}. Please punch in timely." \
        if date == _today_ist() else \
        f"On {date} your shift is {label}. Please punch in timely."
    await db.notifications.insert_one({
        "notification_id": f"n_{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "audience": "user",
        "target_user_id": user_id,
        "type": "shift.allotted",
        "title": title,
        "body": body,
        "created_at": now_iso(),
        "created_by": "system",
    })
    try:
        from routes.email_notifications import fire_email_event
        await fire_email_event("shift_allotted", company_id=company_id,
                               employee_user_id=user_id, details=label)
    except Exception:
        pass


async def _is_hospital_firm(company_id: Optional[str]) -> bool:
    """The shift-change workflow is ONLY for firms whose business
    category is Hospital (per client requirement)."""
    if not company_id:
        return False
    co = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "business_category": 1, "business_subcategory": 1})
    cat = ((co or {}).get("business_category") or "").strip().lower()
    sub = ((co or {}).get("business_subcategory") or "").strip().lower()
    return cat == "hospital" or sub == "hospital"


@router.get("/shift-change/options")
async def shift_change_options(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    allowed = await _is_hospital_firm(user.get("company_id"))
    shifts = await _company_shifts(user.get("company_id")) if allowed else []
    return {
        "allowed": allowed,
        "shifts": shifts,
        "current_shift": user.get("shift_name"),
        "today": _today_ist(),
        "already_punched": await _has_punched(user["user_id"], _today_ist()),
    }


@router.post("/shift-change-requests")
async def create_shift_change_request(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["employee"])
    if not await _is_hospital_firm(user.get("company_id")):
        raise HTTPException(
            status_code=403,
            detail="Shift-change requests are only available for Hospital firms")
    date = (payload.get("date") or _today_ist()).strip()
    requested = (payload.get("requested_shift") or "").strip()
    reason = (payload.get("reason") or "").strip()
    if not requested:
        raise HTTPException(status_code=400, detail="Select the shift you want")
    if date < _today_ist():
        raise HTTPException(status_code=400, detail="Cannot request a shift change for a past date")

    shifts = await _company_shifts(user.get("company_id"))
    shift = next((s for s in shifts if (s.get("name") or "").lower() == requested.lower()), None)
    if not shift:
        raise HTTPException(status_code=400, detail=f"Shift '{requested}' is not defined for your firm")
    if (user.get("shift_name") or "").lower() == requested.lower():
        raise HTTPException(status_code=400, detail="That is already your current shift")

    # RULE: only BEFORE punch-in for that day.
    if await _has_punched(user["user_id"], date):
        raise HTTPException(
            status_code=400,
            detail="You have already punched attendance for this date — shift can "
                   "only be changed BEFORE punching in.")

    dup = await db.shift_change_requests.find_one(
        {"user_id": user["user_id"], "date": date, "status": "pending"}, {"_id": 0})
    if dup:
        raise HTTPException(status_code=409, detail="You already have a pending shift-change request for this date")

    doc = {
        "request_id": f"scr_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "employee_name": user.get("name"),
        "employee_code": user.get("employee_code"),
        "company_id": user.get("company_id"),
        "date": date,
        "current_shift": user.get("shift_name"),
        "requested_shift": shift.get("name"),
        "reason": reason,
        "status": "pending",
        "created_at": now_iso(),
    }
    await db.shift_change_requests.insert_one(dict(doc))

    # Tell the firm admins in-app.
    async for a in db.users.find(
        {"role": "company_admin", "company_id": user.get("company_id")},
        {"_id": 0, "user_id": 1},
    ):
        await db.notifications.insert_one({
            "notification_id": f"n_{uuid.uuid4().hex[:10]}",
            "company_id": user.get("company_id"),
            "audience": "user",
            "target_user_id": a["user_id"],
            "type": "shift.request",
            "title": "Shift change request",
            "body": f"{user.get('name')} requests {doc['requested_shift']} "
                    f"(now {doc['current_shift'] or '—'}) on {date}. "
                    "Approval needs a replacement allotment.",
            "created_at": now_iso(),
            "created_by": "system",
        })
    return {"ok": True, "request": doc}


@router.get("/shift-change-requests")
async def list_shift_change_requests(
    status: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    q: dict = {}
    if user["role"] == "employee":
        q["user_id"] = user["user_id"]
    elif user["role"] == "company_admin":
        q["company_id"] = user.get("company_id")
    elif user["role"] in ("super_admin", "sub_admin"):
        if company_id:
            q["company_id"] = company_id
    else:
        raise HTTPException(status_code=403, detail="Not allowed")
    if status:
        q["status"] = status
    reqs = await db.shift_change_requests.find(
        q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"requests": reqs}


@router.post("/admin/shift-change-requests/{request_id}/decide")
async def decide_shift_change(
    request_id: str,
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    req = await db.shift_change_requests.find_one({"request_id": request_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if admin["role"] == "company_admin" and admin.get("company_id") != req.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm")
    if req.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"Request already {req.get('status')}")

    action = (payload.get("action") or "").lower()
    note = (payload.get("note") or "").strip()
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be approve or reject")

    if action == "reject":
        await db.shift_change_requests.update_one(
            {"request_id": request_id},
            {"$set": {"status": "rejected", "decided_by": admin["user_id"],
                      "decided_at": now_iso(), "note": note}})
        await db.notifications.insert_one({
            "notification_id": f"n_{uuid.uuid4().hex[:10]}",
            "company_id": req.get("company_id"),
            "audience": "user",
            "target_user_id": req["user_id"],
            "type": "shift.rejected",
            "title": "Shift change rejected",
            "body": f"Your shift change to {req['requested_shift']} on {req['date']} "
                    f"was rejected.{(' Note: ' + note) if note else ''}",
            "created_at": now_iso(),
            "created_by": "system",
        })
        return {"ok": True, "status": "rejected"}

    # ---- APPROVE: replacement allotment is MANDATORY --------------------
    replacement_id = payload.get("replacement_user_id")
    if not replacement_id:
        raise HTTPException(
            status_code=400,
            detail="Replacement employee is mandatory — the vacated shift must "
                   "be allotted to someone who can join on time.")
    if replacement_id == req["user_id"]:
        raise HTTPException(status_code=400, detail="Replacement cannot be the same employee")
    replacement = await db.users.find_one(
        {"user_id": replacement_id, "role": "employee",
         "company_id": req.get("company_id")},
        {"_id": 0, "user_id": 1, "name": 1, "shift_name": 1})
    if not replacement:
        raise HTTPException(status_code=404, detail="Replacement employee not found in this firm")
    if await _has_punched(replacement_id, req["date"]):
        raise HTTPException(
            status_code=400,
            detail=f"{replacement.get('name')} has already punched attendance for "
                   f"{req['date']} — pick someone who can join the shift on time.")

    shifts = await _company_shifts(req.get("company_id"))
    new_shift = next((s for s in shifts if (s.get("name") or "").lower() == req["requested_shift"].lower()),
                     {"name": req["requested_shift"]})
    vacated_name = req.get("current_shift") or ""
    vacated_shift = next((s for s in shifts if (s.get("name") or "").lower() == vacated_name.lower()),
                         {"name": vacated_name or new_shift.get("name")})

    # Swap: requester gets the requested shift, replacement covers the vacated one.
    await db.users.update_one({"user_id": req["user_id"]},
                              {"$set": {"shift_name": new_shift.get("name")}})
    await db.users.update_one({"user_id": replacement_id},
                              {"$set": {"shift_name": vacated_shift.get("name")}})
    await db.shift_change_requests.update_one(
        {"request_id": request_id},
        {"$set": {"status": "approved", "decided_by": admin["user_id"],
                  "decided_at": now_iso(), "note": note,
                  "replacement_user_id": replacement_id,
                  "replacement_name": replacement.get("name")}})
    await db.shift_assignments.insert_many([
        {"assignment_id": f"sa_{uuid.uuid4().hex[:10]}", "date": req["date"],
         "company_id": req.get("company_id"), "user_id": req["user_id"],
         "shift_name": new_shift.get("name"), "source": "shift_change",
         "request_id": request_id, "created_at": now_iso()},
        {"assignment_id": f"sa_{uuid.uuid4().hex[:10]}", "date": req["date"],
         "company_id": req.get("company_id"), "user_id": replacement_id,
         "shift_name": vacated_shift.get("name"), "source": "replacement",
         "request_id": request_id, "created_at": now_iso()},
    ])

    # "Today your shift is … punch timely" — to BOTH employees.
    await _notify_shift(req["user_id"], req.get("company_id"), new_shift, req["date"])
    await _notify_shift(replacement_id, req.get("company_id"), vacated_shift, req["date"])

    return {
        "ok": True, "status": "approved",
        "requester_shift": new_shift.get("name"),
        "replacement": {"user_id": replacement_id, "name": replacement.get("name"),
                        "shift": vacated_shift.get("name")},
    }


@router.get("/admin/shift-change-requests/{request_id}/replacement-candidates")
async def replacement_candidates(
    request_id: str,
    authorization: Optional[str] = Header(None),
):
    """Employees of the firm who have NOT punched on the request date —
    i.e. those who can still join the vacated shift on time."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    req = await db.shift_change_requests.find_one({"request_id": request_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if admin["role"] == "company_admin" and admin.get("company_id") != req.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm")
    punched = {r["user_id"] async for r in db.attendance.find(
        {"date": req["date"], "company_id": req.get("company_id"),
         "status": {"$ne": "rejected"}}, {"_id": 0, "user_id": 1})}
    out = []
    async for u in db.users.find(
        {"role": "employee", "company_id": req.get("company_id"),
         "user_id": {"$ne": req["user_id"]}},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "shift_name": 1},
    ).sort("name", 1):
        if u["user_id"] not in punched:
            out.append(u)
    return {"candidates": out, "vacated_shift": req.get("current_shift")}
