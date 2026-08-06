"""Iter 399 — ATTENDANCE ADMIN module (split from attendance_core.py).

Refactor only — MOVED verbatim: admin today / present-not-punched /
approve-punch / auto-close (+loop helper) / open-shifts / roster (+mark),
me/location-ping, manual punch create-edit-delete + audit, record admin
and the admin attendance history endpoints."""
import asyncio
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from pydantic import BaseModel

from server import (  # noqa: E402
    IST_TZ,
    AdminApprovePunch,
    LocationPing,
    _compute_monthly_grid_data,
    _get_policy_from_user,
    _redact_user,
    _resolve_geofence,
    apply_employee_policy_override,
    apply_sub_admin_company_scope,
    db,
    get_user_from_token,
    haversine_m,
    ist_wallclock_iso,
    ist_wallclock_now,
    logger,
    now_iso,
    require_role,
    sub_admin_can_touch_company,
)
from routes.attendance_core import (  # noqa: E402
    apply_contractual_gate,
)
from shared.hours import _compute_day_hours  # noqa: E402
from routes.attendance_location_api import _compute_location_status  # noqa: E402
from shared.dates import _parse_any_date  # noqa: E402

router = APIRouter(prefix="/api")
api = router

_PUNCH_EDIT_LOOKBACK_DAYS = 90


@api.get("/admin/attendance/grid-debug")
async def attendance_grid_debug(
    user_id: str = Query(...),
    date: str = Query(..., description="YYYY-MM-DD"),
    authorization: Optional[str] = Header(None),
):
    """Iter 486 (user bug) — full per-day trace of the attendance engine:
    every stored punch (ALL statuses), what the grid pipeline kept after
    dedupe / re-kind / night-shift stitch, the selected IN & OUT, and the
    exact reason a punch was excluded (e.g. status=pending)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    emp = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "company_id": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised")
    if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, emp.get("company_id")):
        raise HTTPException(status_code=403, detail="Not authorised")

    from server import dedupe_close_punches, stitch_cross_day_ot
    # Iter 503 — honour the firm's Single Machine Attendance Mode config.
    _comp = await db.companies.find_one(
        {"company_id": emp.get("company_id")},
        {"_id": 0, "attendance_config": 1}) or {}
    _att_cfg = _comp.get("attendance_config")
    day = _parse_any_date(date)
    if not day:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    if isinstance(day, datetime):
        day = day.date()
    d_prev = (day - timedelta(days=1)).isoformat()
    d_next = (day + timedelta(days=1)).isoformat()
    date = day.isoformat()

    raw = await db.attendance.find(
        {"user_id": user_id, "date": {"$in": [d_prev, date, d_next]}},
        {"_id": 0, "record_id": 1, "date": 1, "kind": 1, "at": 1,
         "source": 1, "status": 1, "pending_reason": 1, "mock_location": 1},
    ).sort("at", 1).to_list(200)

    stored = []
    excluded = []
    by_day: Dict[str, List[dict]] = {}
    for r in raw:
        entry = {**r}
        if r.get("status") != "approved":
            entry["excluded_reason"] = (
                f"status={r.get('status')}"
                + (f" ({r.get('pending_reason')})" if r.get("pending_reason") else "")
                + " — only APPROVED punches count on the grid. Approve it in the "
                  "Repair modal, or enable Firm Master → Approval Workflow → "
                  "'Auto-approve Mobile App Punches' for app punches.")
            excluded.append(entry)
        else:
            by_day.setdefault(r["date"], []).append(dict(r))
            stored.append(entry)

    processed = stitch_cross_day_ot(dedupe_close_punches(by_day, company_cfg=_att_cfg))
    day_punches = processed.get(date, [])
    ins = [p for p in day_punches if (p.get("kind") or "").lower() == "in"]
    outs = [p for p in day_punches if (p.get("kind") or "").lower() == "out"]
    sel_in = min(ins, key=lambda p: p.get("at") or "") if ins else None
    sel_out = max(outs, key=lambda p: p.get("at") or "") if outs else None
    reason = None
    if not sel_out:
        if any(e.get("kind") == "out" for e in excluded if e.get("date") == date):
            reason = ("An OUT punch EXISTS for this date but is not APPROVED "
                      "— see excluded_punches for the exact status.")
        elif not day_punches:
            reason = "No approved punches stored for this date."
        else:
            reason = ("All approved punches on this date resolved to IN — no "
                      "OUT recorded (machine may be IN-only, or the OUT "
                      "landed on another date).")
    logger.info("[grid-debug] %s %s — raw=%d approved=%d in=%s out=%s reason=%s",
                user_id, date, len(raw), len(stored),
                (sel_in or {}).get("at"), (sel_out or {}).get("at"), reason)
    return {
        "employee": emp,
        "date": date,
        "attendance_config": _att_cfg,
        "raw_punches": raw,
        "excluded_punches": excluded,
        "processed_day_punches": day_punches,
        "selected_in": sel_in,
        "selected_out": sel_out,
        "out_missing_reason": reason,
    }


@api.post("/admin/attendance/cleanup-duplicate-punches")
async def cleanup_duplicate_punches(
    company_id: Optional[str] = Query(None),
    month: Optional[str] = Query(None, description="YYYY-MM (optional — all history if omitted)"),
    dry_run: bool = Query(False),
    authorization: Optional[str] = Header(None),
):
    """Iter 488 (user: "Multi Punch Within the Same time") — mark ALREADY
    STORED duplicate MACHINE punches: any zkteco-source approved punch
    within 5 minutes of the previous kept punch of the same employee gets
    ``status="duplicate"`` so it stays in the raw punch log (user rule:
    NEVER delete raw punches) but is ignored by every calculation.
    Manual / mobile-app punches are never touched."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    if not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    q: dict = {"company_id": company_id, "status": "approved"}
    if month:
        q["date"] = {"$gte": f"{month}-01", "$lte": f"{month}-31"}
    by_user: Dict[str, List[dict]] = {}
    async for p in db.attendance.find(
            q, {"_id": 0, "record_id": 1, "user_id": 1, "at": 1,
                "source": 1, "kind": 1, "date": 1}).sort("at", 1):
        by_user.setdefault(p["user_id"], []).append(p)
    dupes: List[dict] = []
    for _uid, rows in by_user.items():
        last_at = None
        for p in sorted(rows, key=lambda x: x.get("at") or ""):
            try:
                t = datetime.fromisoformat(str(p.get("at")).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            src = str(p.get("source") or "")
            if (last_at is not None and src.startswith("zkteco")
                    and abs((t - last_at).total_seconds()) < 5 * 60):
                dupes.append(p)
                continue  # marked punches do NOT advance the window
            last_at = t
    marked = 0
    if not dry_run and dupes:
        ids = [d["record_id"] for d in dupes]
        r = await db.attendance.update_many(
            {"record_id": {"$in": ids}},
            {"$set": {
                "status": "duplicate",
                "dup_marked_at": now_iso(),
                "dup_marked_by": admin.get("user_id"),
                "decision_reason": (
                    "Duplicate punch within 5 min — kept in the punch log "
                    "but ignored in attendance calculations (Iter 488 cleanup)."),
            }})
        marked = r.modified_count
        logger.info("[dedupe-cleanup] company=%s month=%s marked=%d by=%s",
                    company_id, month, marked, admin.get("user_id"))
    return {
        "ok": True,
        "dry_run": dry_run,
        "duplicates_found": len(dupes),
        "marked": marked,
        "sample": [{"user_id": d["user_id"], "date": d["date"],
                    "at": d["at"], "kind": d["kind"]} for d in dupes[:20]],
    }


@api.get("/admin/attendance/today")
async def admin_attendance_today(
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """List employees who punched IN today, with their first-in / last-out and
    duty hours so far. Scoped to the caller's company for company_admin; super
    admin may pass ?company_id=... to filter."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    scope_company: Optional[str] = None
    if user["role"] == "company_admin":
        scope_company = user.get("company_id")
    elif user["role"] in ("super_admin", "sub_admin") and company_id and company_id != "all":
        # Iter 484 (user bug) — sub_admin's ?company_id= filter was silently
        # IGNORED, and their restricted firm scope was never applied, so the
        # "Present today" list leaked employees of NON-allowed firms.
        scope_company = company_id

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    q: dict = {"date": today}
    if scope_company:
        q["company_id"] = scope_company
    # Enforce the sub-admin's allowed-firms list (restricted scope) — also
    # blocks a sub_admin passing a company_id outside their allow-list.
    apply_sub_admin_company_scope(user, q)
    recs = await db.attendance.find(
        q, {"_id": 0, "selfie_base64": 0, "device_info": 0}
    ).sort("at", 1).to_list(20000)

    # Group by user
    by_user: dict[str, list] = {}
    for r in recs:
        by_user.setdefault(r["user_id"], []).append(r)

    if not by_user:
        return {"date": today, "present": []}

    users = await db.users.find(
        {"user_id": {"$in": list(by_user.keys())}},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "company_id": 1},
    ).to_list(20000)
    users_by_id = {u["user_id"]: u for u in users}

    # Iter 484 (user bug, belt & braces) — when a firm filter is active,
    # drop employees whose CURRENT firm is different even if their punch was
    # stamped with the filtered company (shared machine / bio-code overlap).
    if scope_company:
        by_user = {
            uid: rs for uid, rs in by_user.items()
            if (users_by_id.get(uid) or {}).get("company_id") in (scope_company, None)
        }

    # Fetch company names for a small map (super admin cross-company view)
    company_ids = list({u.get("company_id") for u in users if u.get("company_id")})
    companies = []
    if company_ids:
        companies = await db.companies.find(
            {"company_id": {"$in": company_ids}}, {"_id": 0, "company_id": 1, "name": 1}
        ).to_list(1000)
    company_names = {c["company_id"]: c["name"] for c in companies}

    present: list[dict] = []
    for uid, rs in by_user.items():
        hrs, fin, lout, still = _compute_day_hours(rs)
        u = users_by_id.get(uid, {})
        # Trim each punch to just the fields the timeline UI needs. Explicit
        # allow-list so we never leak selfies / device_info by accident.
        timeline = [
            {
                "at": r.get("at"),
                "kind": r.get("kind"),
                "source": r.get("source"),
                "latitude": r.get("latitude"),
                "longitude": r.get("longitude"),
                "outside_note": r.get("outside_note"),
                "branch_id": r.get("branch_id"),
                "branch_name": r.get("branch_name"),
                "approved_by": r.get("approved_by"),
            }
            for r in rs
        ]
        present.append({
            "user_id": uid,
            "name": u.get("name") or "Unknown",
            "employee_code": u.get("employee_code"),
            "company_id": u.get("company_id"),
            "company_name": company_names.get(u.get("company_id")),
            "first_in": fin,
            "last_out": lout,
            "still_in": still,
            "hours": hrs,
            "punches": len(rs),
            "timeline": timeline,
        })
    # Order by first_in ascending
    present.sort(key=lambda p: p.get("first_in") or "")
    return {"date": today, "present": present}


# ---------------------------------------------------------------------------
# Employee location ping (used by "present but not punched" report)
# ---------------------------------------------------------------------------
@api.post("/me/location-ping")
async def me_location_ping(
    payload: LocationPing,
    authorization: Optional[str] = Header(None),
):
    """Persist the caller's latest known GPS location on their user record.
    Idempotent — called by the mobile app when the attendance screen loads
    or when a location update is available. The location is NOT stored in a
    log, only the most recent value is kept (privacy-respecting).
    """
    user = await get_user_from_token(authorization)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "last_location_lat": payload.latitude,
            "last_location_lng": payload.longitude,
            "last_location_at": now_iso(),
        }},
    )
    return {"ok": True}


@api.get("/admin/attendance/present-not-punched")
async def admin_present_not_punched(
    company_id: Optional[str] = None,
    max_age_minutes: int = Query(60, ge=1, le=1440),
    authorization: Optional[str] = Header(None),
):
    """List employees whose LAST KNOWN location is INSIDE the office
    geofence for their company but who have NOT punched-in (or have not
    punched-out) today.

    - Only recent location pings (within `max_age_minutes`) are considered.
    - Company admins see their own company; super admins can filter by
      `company_id`.

    Response contains two lists: `not_punched_in` and `not_punched_out`.
    Each row includes distance-from-office (m), last-seen timestamp, and
    employee identity so the employer can review + approve.
    """
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])

    scope_company: Optional[str] = None
    if user["role"] == "company_admin":
        scope_company = user.get("company_id")
    elif user["role"] in ("super_admin", "sub_admin") and company_id and company_id != "all":
        scope_company = company_id

    # Load candidate companies + build a fast lookup
    company_query: dict = {}
    if scope_company:
        company_query["company_id"] = scope_company
    # Iter 484 (user bug) — enforce sub-admin restricted firm scope here too.
    apply_sub_admin_company_scope(user, company_query)
    companies = await db.companies.find(
        company_query,
        {"_id": 0, "company_id": 1, "name": 1, "office_lat": 1,
         "office_lng": 1, "geofence_radius_m": 1},
    ).to_list(1000)
    if not companies:
        return {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "not_punched_in": [], "not_punched_out": []}
    companies_by_id = {c["company_id"]: c for c in companies}

    # Load users we care about — only employees with a location ping
    user_query: dict = {
        "role": "employee",
        "last_location_lat": {"$ne": None, "$exists": True},
        "last_location_lng": {"$ne": None, "$exists": True},
    }
    if scope_company:
        user_query["company_id"] = scope_company
    else:
        user_query["company_id"] = {"$in": list(companies_by_id.keys())}

    employees = await db.users.find(
        user_query,
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "phone": 1,
         "employee_code": 1, "company_id": 1, "last_location_lat": 1,
         "last_location_lng": 1, "last_location_at": 1,
         "onboarded": 1, "approval_status": 1, "exit_date": 1},
    ).to_list(20000)

    # Filter to onboarded + approved + not exited employees
    def _eligible(e: dict) -> bool:
        if not e.get("onboarded"):
            return False
        if (e.get("approval_status") or "approved") != "approved":
            return False
        if e.get("exit_date"):
            try:
                if e["exit_date"] <= datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                    return False
            except Exception:
                pass
        return True

    employees = [e for e in employees if _eligible(e)]

    if not employees:
        return {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "not_punched_in": [], "not_punched_out": []}

    # Compute today's attendance state per user in scope
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user_ids = [e["user_id"] for e in employees]
    att = await db.attendance.find(
        {"user_id": {"$in": user_ids}, "date": today},
        {"_id": 0, "user_id": 1, "kind": 1, "at": 1},
    ).sort("at", 1).to_list(20000)
    by_user: dict[str, list] = {}
    for r in att:
        by_user.setdefault(r["user_id"], []).append(r)

    threshold = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

    not_in: list[dict] = []
    not_out: list[dict] = []

    for e in employees:
        comp = companies_by_id.get(e.get("company_id"))
        if not comp:
            continue
        # Recency check
        last_at = e.get("last_location_at")
        try:
            if isinstance(last_at, str):
                last_dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            else:
                last_dt = last_at
        except Exception:
            last_dt = None
        if not last_dt:
            continue
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        if last_dt < threshold:
            continue
        # Distance check
        dist = haversine_m(
            e["last_location_lat"], e["last_location_lng"],
            comp.get("office_lat") or 0.0, comp.get("office_lng") or 0.0,
        )
        radius = comp.get("geofence_radius_m") or 200
        if dist > radius:
            continue

        recs = by_user.get(e["user_id"], [])
        has_in = any((r.get("kind") == "in") for r in recs)
        has_out_after_in = False
        # "has punched out for the current in" — latest kind is "out"
        if recs:
            has_out_after_in = recs[-1].get("kind") == "out"

        row = {
            "user_id": e["user_id"],
            "name": e.get("name") or "Unknown",
            "employee_code": e.get("employee_code"),
            "email": e.get("email"),
            "phone": e.get("phone"),
            "company_id": e.get("company_id"),
            "company_name": comp.get("name"),
            "distance_m": round(dist, 1),
            "geofence_radius_m": radius,
            "last_seen_at": (
                last_dt.isoformat() if hasattr(last_dt, "isoformat") else last_at
            ),
            "last_location_lat": e["last_location_lat"],
            "last_location_lng": e["last_location_lng"],
            "punches_today": len(recs),
        }

        if not has_in:
            not_in.append(row)
        elif not has_out_after_in:
            # Punched in but has not punched out yet
            not_out.append(row)

    not_in.sort(key=lambda r: r.get("distance_m") or 0)
    not_out.sort(key=lambda r: r.get("distance_m") or 0)

    return {
        "date": today,
        "not_punched_in": not_in,
        "not_punched_out": not_out,
    }


@api.post("/admin/attendance/approve-punch")
async def admin_approve_punch(
    payload: AdminApprovePunch,
    authorization: Optional[str] = Header(None),
):
    """Employer creates a punch on behalf of an employee. The employee must
    (a) belong to the employer's company, and (b) currently sit inside the
    office geofence (based on their last-known location). Records the
    creator + optional note for audit."""
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])

    emp = await db.users.find_one({"user_id": payload.user_id}, {"_id": 0})
    if not emp or emp.get("role") != "employee":
        raise HTTPException(status_code=404, detail="Employee not found")

    # Scope: company admins can only act on their own employees
    if admin_user["role"] == "company_admin":
        if emp.get("company_id") != admin_user.get("company_id"):
            raise HTTPException(status_code=403, detail="Employee not in your company")

    comp = await db.companies.find_one({"company_id": emp.get("company_id")}, {"_id": 0})
    if not comp:
        raise HTTPException(status_code=400, detail="Employee has no company assigned")

    lat = emp.get("last_location_lat")
    lng = emp.get("last_location_lng")
    if lat is None or lng is None:
        raise HTTPException(
            status_code=400,
            detail="Employee has not shared their location recently. Ask them to open the app.",
        )
    dist = haversine_m(lat, lng, comp.get("office_lat") or 0.0, comp.get("office_lng") or 0.0)
    radius = comp.get("geofence_radius_m") or 200
    if dist > radius:
        raise HTTPException(
            status_code=400,
            detail=f"Employee is {int(dist)}m from office (allowed {int(radius)}m).",
        )

    # Idempotency (toggle style): allow multiple IN→OUT cycles per day, but
    # never a double-IN or double-OUT (would corrupt shift pairing).
    today = ist_wallclock_now().strftime("%Y-%m-%d")  # Iter 144 — wall-clock
    recs = await db.attendance.find(
        {"user_id": emp["user_id"], "date": today},
        {"_id": 0, "kind": 1, "at": 1},
    ).sort("at", 1).to_list(200)
    last_kind = recs[-1].get("kind") if recs else None
    if payload.kind == "in" and last_kind == "in":
        raise HTTPException(status_code=400, detail="Employee is already punched-in.")
    if payload.kind == "out" and last_kind != "in":
        raise HTTPException(status_code=400, detail="Employee is not currently punched-in.")

    record_id = f"att_{uuid.uuid4().hex[:12]}"
    record = {
        "record_id": record_id,
        "user_id": emp["user_id"],
        "company_id": emp["company_id"],
        "date": today,
        "kind": payload.kind,
        "at": ist_wallclock_iso(),
        "latitude": lat,
        "longitude": lng,
        "distance_m": round(dist, 1),
        "biometric_method": "fingerprint",  # not physically captured
        "selfie_base64": None,
        "device_info": None,
        "source": "admin_approved",
        "approved_by_user_id": admin_user["user_id"],
        "approved_by_name": admin_user.get("name") or admin_user.get("email"),
        "approver_note": (payload.note or "").strip() or None,
    }
    await db.attendance.insert_one(record)
    logger.info(
        f"[ADMIN PUNCH] {admin_user.get('email')} → punched {payload.kind} for "
        f"{emp.get('name')} ({emp.get('employee_code')}) — {int(dist)}m from office",
    )
    # Iter 145 — web-push the punch confirmation to the employee.
    try:
        from routes.web_push import push_to_user
        _k = "IN" if payload.kind == "in" else "OUT"
        await push_to_user(
            emp["user_id"], f"Punch {_k} approved",
            f"Your employer recorded a Punch {_k} for you at "
            f"{ist_wallclock_now().strftime('%I:%M %p')}.",
            url="/attendance", tag=f"punch_{record_id}")
    except Exception:
        pass
    return {"ok": True, "record_id": record_id, "distance_m": round(dist, 1)}


# ---------------------------------------------------------------------------
# Server-side shift auto-close
#
# If an employee punched IN but never punched OUT — because they force-quit
# the app, ran out of battery, or simply stopped using their phone — the
# background auto-punch task can't fire. This job scans for such
# "orphan" open shifts and closes them server-side so payroll doesn't
# skip the day and the admin's Present-Today view doesn't stay pinned on
# stale users.
#
# Two triggers close a shift:
#   1. Elapsed hours since IN >= AUTO_CLOSE_MAX_HOURS (default 12h)
#   2. Last-known GPS ping is outside the branch geofence for
#      >= AUTO_CLOSE_STALE_MINUTES (default 30 min) AND that ping is
#      more recent than the IN timestamp.
#
# Records are stamped with source="server_auto_close" plus a note so
# admins can distinguish auto-closed shifts from genuine punches.
# ---------------------------------------------------------------------------

AUTO_CLOSE_MAX_HOURS = float(os.getenv("AUTO_CLOSE_MAX_HOURS", "12"))
AUTO_CLOSE_STALE_MINUTES = int(os.getenv("AUTO_CLOSE_STALE_MINUTES", "30"))
AUTO_CLOSE_TICK_SECONDS = int(os.getenv("AUTO_CLOSE_TICK_SECONDS", "600"))  # 10 min


async def _auto_close_open_shifts() -> dict:
    """Scan today (UTC) for open IN punches with no matching OUT, and
    auto-close them where policy applies. Returns a summary dict.
    Idempotent — running twice in a row does nothing the second time."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_utc = datetime.now(timezone.utc)
    closed: list[dict] = []

    # Group today's punches by user
    pipeline = [
        {"$match": {"date": today}},
        {"$sort": {"at": 1}},
        {"$group": {
            "_id": "$user_id",
            "records": {"$push": {
                "kind": "$kind",
                "at": "$at",
                "company_id": "$company_id",
                "branch_id": "$branch_id",
            }},
        }},
    ]
    grouped = await db.attendance.aggregate(pipeline).to_list(5000)

    for g in grouped:
        recs = g.get("records") or []
        if not recs or recs[-1].get("kind") != "in":
            continue  # not an open shift

        last_in = recs[-1]
        try:
            last_in_at = datetime.fromisoformat(last_in["at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if last_in_at.tzinfo is None:
            last_in_at = last_in_at.replace(tzinfo=timezone.utc)

        elapsed_h = (now_utc - last_in_at).total_seconds() / 3600.0

        user_id = g["_id"]
        emp = await db.users.find_one(
            {"user_id": user_id},
            {"_id": 0, "user_id": 1, "company_id": 1, "role": 1,
             "last_location_lat": 1, "last_location_lng": 1,
             "last_location_at": 1},
        )
        if not emp or emp.get("role") != "employee":
            continue

        should_close = False
        reason = ""

        if elapsed_h >= AUTO_CLOSE_MAX_HOURS:
            should_close = True
            reason = f"open shift exceeded {AUTO_CLOSE_MAX_HOURS:g}h"

        # Geofence check (only if we haven't already decided to close)
        if not should_close:
            lat = emp.get("last_location_lat")
            lng = emp.get("last_location_lng")
            last_ping_at = emp.get("last_location_at")
            if lat is not None and lng is not None and last_ping_at:
                try:
                    ping_dt = datetime.fromisoformat(str(last_ping_at).replace("Z", "+00:00"))
                    if ping_dt.tzinfo is None:
                        ping_dt = ping_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    ping_dt = None
                if ping_dt and ping_dt > last_in_at:
                    company = await db.companies.find_one(
                        {"company_id": emp.get("company_id")}, {"_id": 0},
                    )
                    if company:
                        dist, closest = await _resolve_geofence(company, lat, lng)
                        radius = (closest or {}).get("geofence_radius_m") or (
                            company.get("geofence_radius_m") or 200
                        )
                        stale_min = (now_utc - ping_dt).total_seconds() / 60.0
                        if dist > radius and stale_min >= AUTO_CLOSE_STALE_MINUTES:
                            should_close = True
                            reason = (
                                f"left geofence {int(dist)}m and no ping for "
                                f"{int(stale_min)} min"
                            )

        if not should_close:
            continue

        record_id = f"att_{uuid.uuid4().hex[:12]}"
        out_at = now_utc if elapsed_h < AUTO_CLOSE_MAX_HOURS else (
            last_in_at + timedelta(hours=AUTO_CLOSE_MAX_HOURS)
        )
        record = {
            "record_id": record_id,
            "user_id": user_id,
            "company_id": emp.get("company_id"),
            "branch_id": last_in.get("branch_id"),
            "date": today,
            "kind": "out",
            "at": out_at.isoformat(),
            "latitude": emp.get("last_location_lat"),
            "longitude": emp.get("last_location_lng"),
            "source": "server_auto_close",
            "outside_note": f"auto-closed: {reason}",
            "auto_closed": True,
        }
        await db.attendance.insert_one(record)
        closed.append({
            "user_id": user_id,
            "record_id": record_id,
            "reason": reason,
            "elapsed_hours": round(elapsed_h, 2),
        })

    return {"scanned": len(grouped), "closed": len(closed), "records": closed}


@api.post("/admin/attendance/auto-close")
async def admin_trigger_auto_close(authorization: Optional[str] = Header(None)):
    """On-demand trigger of the auto-close job. Only super_admin and
    company_admin can invoke — useful for manual verification / testing."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    summary = await _auto_close_open_shifts()
    return {"ok": True, **summary}


@api.get("/admin/attendance/open-shifts")
async def list_open_shifts(
    authorization: Optional[str] = Header(None),
    company_id: Optional[str] = None,
):
    """Return employees who have punched IN today but never punched OUT.
    Useful for admins to see who might need a manual close."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_utc = datetime.now(timezone.utc)

    # Scope filter
    match_q: dict = {"date": today}
    if user["role"] == "company_admin":
        match_q["company_id"] = user.get("company_id")
    elif user["role"] == "super_admin" and company_id and company_id != "all":
        match_q["company_id"] = company_id

    pipeline = [
        {"$match": match_q},
        {"$sort": {"at": 1}},
        {"$group": {
            "_id": "$user_id",
            "records": {"$push": {
                "kind": "$kind",
                "at": "$at",
                "source": "$source",
            }},
            "company_id": {"$last": "$company_id"},
        }},
    ]
    grouped = await db.attendance.aggregate(pipeline).to_list(5000)

    open_shifts: list[dict] = []
    uids: list[str] = []
    for g in grouped:
        recs = g.get("records") or []
        if not recs or recs[-1].get("kind") != "in":
            continue
        uids.append(g["_id"])
        try:
            last_in_at = datetime.fromisoformat(recs[-1]["at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if last_in_at.tzinfo is None:
            last_in_at = last_in_at.replace(tzinfo=timezone.utc)
        elapsed_h = (now_utc - last_in_at).total_seconds() / 3600.0
        open_shifts.append({
            "user_id": g["_id"],
            "company_id": g.get("company_id"),
            "last_in_at": recs[-1]["at"],
            "elapsed_hours": round(elapsed_h, 2),
            "punch_count": len(recs),
            "will_auto_close": elapsed_h >= AUTO_CLOSE_MAX_HOURS,
        })

    if uids:
        users = await db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
             "company_id": 1, "last_location_lat": 1, "last_location_lng": 1,
             "last_location_at": 1},
        ).to_list(1000)
        u_by_id = {u["user_id"]: u for u in users}
        cids = list({u.get("company_id") for u in users if u.get("company_id")})
        companies = await db.companies.find(
            {"company_id": {"$in": cids}},
            {"_id": 0, "company_id": 1, "name": 1},
        ).to_list(500) if cids else []
        c_by_id = {c["company_id"]: c["name"] for c in companies}
        for s in open_shifts:
            u = u_by_id.get(s["user_id"], {})
            s["name"] = u.get("name")
            s["employee_code"] = u.get("employee_code")
            s["company_name"] = c_by_id.get(u.get("company_id"))
            s["last_location_lat"] = u.get("last_location_lat")
            s["last_location_lng"] = u.get("last_location_lng")
            s["last_location_at"] = u.get("last_location_at")

    # Sort: longest open first
    open_shifts.sort(key=lambda x: x["elapsed_hours"], reverse=True)
    return {
        "open_shifts": open_shifts,
        "count": len(open_shifts),
        "auto_close_after_hours": AUTO_CLOSE_MAX_HOURS,
    }


# ---------------------------------------------------------------------------
# Daily roster (resort / hospitality use case)
# Live-in staff can't rely on geofence auto-punch. The supervisor uses
# the roster to (a) see everyone's punch state at a glance and (b)
# batch-record IN/OUT punches or absences without visiting each
# employee's row separately.
# ---------------------------------------------------------------------------


class RosterMark(BaseModel):
    user_id: str
    action: Literal["in", "out", "absent"]


class RosterMarkRequest(BaseModel):
    marks: List[RosterMark]
    note: Optional[str] = None


@api.get("/admin/attendance/roster")
async def get_daily_roster(
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Everyone in scope + their current punch state today. Used by
    the supervisor to mark present/absent for live-in staff whose
    phones may never leave the premises."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scope_filter: dict = {"role": "employee"}
    if admin["role"] == "company_admin":
        scope_filter["company_id"] = admin.get("company_id")
    elif admin["role"] == "super_admin" and company_id and company_id != "all":
        scope_filter["company_id"] = company_id

    users = await db.users.find(
        scope_filter,
        {
            "_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
            "company_id": 1, "shift_start": 1, "shift_end": 1,
            "is_live_in": 1, "onboarded": 1, "approval_status": 1,
            "exit_date": 1,
        },
    ).sort("name", 1).to_list(20000)

    # Drop inactive / unapproved employees from the roster surface.
    users = [
        u for u in users
        if u.get("onboarded")
        and (u.get("approval_status") or "approved") == "approved"
        and not (u.get("exit_date") and u["exit_date"] <= today)
    ]

    if not users:
        return {"date": today, "roster": [], "count": 0}

    uids = [u["user_id"] for u in users]
    recs = await db.attendance.find(
        {"user_id": {"$in": uids}, "date": today},
        {"_id": 0, "user_id": 1, "kind": 1, "at": 1, "source": 1},
    ).sort("at", 1).to_list(50000)
    by_user: dict[str, list[dict]] = {}
    for r in recs:
        by_user.setdefault(r["user_id"], []).append(r)

    roster = []
    for u in users:
        rs = by_user.get(u["user_id"], [])
        last = rs[-1] if rs else None
        first_in = next((x["at"] for x in rs if x["kind"] == "in"), None)
        last_out = None
        for x in reversed(rs):
            if x["kind"] == "out":
                last_out = x["at"]
                break
        state = (
            "in" if last and last["kind"] == "in"
            else "done" if rs
            else "absent"
        )
        roster.append({
            "user_id": u["user_id"],
            "name": u.get("name"),
            "employee_code": u.get("employee_code"),
            "is_live_in": bool(u.get("is_live_in")),
            "shift_start": u.get("shift_start"),
            "shift_end": u.get("shift_end"),
            "first_in": first_in,
            "last_out": last_out,
            "punch_count": len(rs),
            "state": state,
        })
    return {"date": today, "roster": roster, "count": len(roster)}


@api.post("/admin/attendance/roster/mark")
async def batch_roster_mark(
    payload: RosterMarkRequest,
    authorization: Optional[str] = Header(None),
):
    """Bulk record IN/OUT punches for a set of employees. Reuses
    `approve-punch` guard logic. Skipping rows that would create a
    double-IN / double-OUT is silent — we return per-row results."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results = []
    for m in payload.marks:
        emp = await db.users.find_one(
            {"user_id": m.user_id},
            {"_id": 0, "user_id": 1, "company_id": 1, "role": 1},
        )
        if not emp or emp.get("role") != "employee":
            results.append({"user_id": m.user_id, "ok": False, "detail": "not found"})
            continue
        if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
            results.append({"user_id": m.user_id, "ok": False, "detail": "not your company"})
            continue

        if m.action == "absent":
            # Persist an explicit "absent" record so the employee sees the
            # roster decision in their own Today / History screens. Idempotent
            # per user+date — repeated marks just refresh the metadata.
            existing = await db.attendance.find_one(
                {"user_id": m.user_id, "date": today, "kind": "absent"},
                {"_id": 0, "record_id": 1},
            )
            if existing:
                await db.attendance.update_one(
                    {"record_id": existing["record_id"]},
                    {"$set": {
                        "at": now_iso(),
                        "approved_by": admin["user_id"],
                        "roster_note": payload.note,
                    }},
                )
                results.append({
                    "user_id": m.user_id, "ok": True, "action": "absent",
                    "record_id": existing["record_id"], "updated": True,
                })
                continue
            record_id = f"att_{uuid.uuid4().hex[:12]}"
            record = {
                "record_id": record_id,
                "user_id": m.user_id,
                "company_id": emp.get("company_id"),
                "date": today,
                "kind": "absent",
                "at": now_iso(),
                "source": "roster",
                "status": "approved",
                "approved_by": admin["user_id"],
                "roster_note": payload.note,
            }
            await db.attendance.insert_one(record)
            results.append({
                "user_id": m.user_id, "ok": True, "action": "absent",
                "record_id": record_id,
            })
            continue

        # Toggle idempotency check — only among non-absent records
        rs = await db.attendance.find(
            {"user_id": m.user_id, "date": today, "kind": {"$in": ["in", "out"]}},
            {"_id": 0, "kind": 1, "at": 1},
        ).sort("at", 1).to_list(200)
        last_kind = rs[-1].get("kind") if rs else None
        if m.action == "in" and last_kind == "in":
            results.append({"user_id": m.user_id, "ok": False, "detail": "already in"})
            continue
        if m.action == "out" and last_kind != "in":
            results.append({"user_id": m.user_id, "ok": False, "detail": "not currently in"})
            continue

        # If an "absent" record exists for today, marking IN should retract it
        # so the employee's day flips from Absent → Present cleanly.
        if m.action == "in":
            await db.attendance.delete_many(
                {"user_id": m.user_id, "date": today, "kind": "absent"}
            )

        record_id = f"att_{uuid.uuid4().hex[:12]}"
        record = {
            "record_id": record_id,
            "user_id": m.user_id,
            "company_id": emp.get("company_id"),
            "date": today,
            "kind": m.action,
            "at": now_iso(),
            "source": "roster",
            "status": "approved",  # roster punches are pre-approved by admin
            "approved_by": admin["user_id"],
            "roster_note": payload.note,
        }
        await db.attendance.insert_one(record)
        results.append({
            "user_id": m.user_id,
            "ok": True,
            "action": m.action,
            "record_id": record_id,
        })
    return {"results": results, "count": len(results)}


# ---------------------------------------------------------------------------
# In-app messaging
# Admin (company_admin or super_admin) composes announcements or DMs; each
# message stores a `recipient_user_ids` list plus a `read_by` list to power
# unread badges. One-way for now — employees can only read.
# ---------------------------------------------------------------------------

class ManualPunchCreate(BaseModel):
    user_id: str
    kind: Literal["in", "out"]
    at: str  # ISO 8601 with timezone (or "YYYY-MM-DD HH:MM")
    reason: str  # mandatory audit note


class ManualPunchEdit(BaseModel):
    """Any field left None is unchanged."""
    at: Optional[str] = None
    kind: Optional[Literal["in", "out"]] = None
    reason: str  # mandatory audit note on every edit


def _parse_manual_at(raw: str) -> datetime:
    """Accept 'YYYY-MM-DDTHH:MM' / 'YYYY-MM-DD HH:MM' / full ISO w/ tz. Falls
    back to UTC when no timezone is supplied."""
    s = (raw or "").strip()
    if not s:
        raise HTTPException(status_code=400, detail="Time is required")
    s = s.replace("Z", "+00:00")
    # Insert 'T' if missing between date and time
    if len(s) >= 16 and s[10] == " ":
        s = s[:10] + "T" + s[11:]
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid time '{raw}'. Use YYYY-MM-DDTHH:MM.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _enforce_lookback(admin: dict, when: datetime) -> None:
    """Company admins can only edit punches from the last 90 days."""
    if admin.get("role") == "super_admin":
        return
    now = datetime.now(timezone.utc)
    if when > now + timedelta(minutes=5):
        raise HTTPException(
            status_code=400,
            detail="Punch time cannot be in the future.",
        )
    if (now - when).days > _PUNCH_EDIT_LOOKBACK_DAYS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Employer can only edit punches within the last "
                f"{_PUNCH_EDIT_LOOKBACK_DAYS} days. Ask a super admin for older records."
            ),
        )


async def _log_punch_audit(
    action: str,
    admin: dict,
    record_id: str,
    before: Optional[dict],
    after: Optional[dict],
    reason: str,
) -> None:
    """Append to the attendance_audit_log collection. Kept lightweight —
    we deliberately drop base64 blobs to keep the log small."""
    def _clean(d: Optional[dict]) -> Optional[dict]:
        if not d:
            return d
        out = {k: v for k, v in d.items() if k not in ("_id", "selfie_base64", "photo_base64")}
        return out
    try:
        await db.attendance_audit_log.insert_one({
            "audit_id": f"aal_{uuid.uuid4().hex[:12]}",
            "record_id": record_id,
            "action": action,  # "create" | "edit" | "delete"
            "actor_user_id": admin.get("user_id"),
            "actor_role": admin.get("role"),
            "reason": reason,
            "at": now_iso(),
            "before": _clean(before),
            "after": _clean(after),
        })
    except Exception:
        logger.exception("[punch_audit] failed to persist audit row")


@api.get("/admin/attendance/day-status/{company_id}")
async def attendance_day_status(
    company_id: str,
    from_date: str = Query(...),
    to_date: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Iter 94 — Per-employee punch status for a date (or range, max 31
    days). Powers the Punch Approvals source tabs:
      • Updated       → rows where a punch was EDITED (app/web portal)
      • Auto-Punches  → rows where BOTH In & Out punches exist
      • Manual Entries→ rows with MISSING In / Out / Both (fill manually)
    Every active employee × date combo is returned; the client filters.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorised for this company")
    f = (from_date or "").strip()
    t = (to_date or "").strip() or f
    if t < f:
        t = f
    try:
        d0 = datetime.strptime(f, "%Y-%m-%d").date()
        d1 = datetime.strptime(t, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")
    if (d1 - d0).days > 31:
        raise HTTPException(status_code=400, detail="Range too large — max 31 days")

    emps = await db.users.find(
        {"company_id": company_id, "role": "employee",
         "disabled": {"$ne": True}, "exit_date": None},
        {"_id": 0, "user_id": 1, "name": 1, "father_name": 1,
         "designation": 1, "employee_code": 1,
         "shift_start": 1, "shift_end": 1, "attendance_policy_override": 1},
    ).to_list(2000)
    # Iter 95g — resolve each employee's shift times (Shift Master override
    # first, then the mirrored shift_start/shift_end strings) so the Manual
    # Entries tab can offer a one-tap "Fill from shift" for missing punches.
    _shift_docs = await db.shift_masters.find(
        {}, {"_id": 0, "shift_id": 1, "start": 1, "end": 1},
    ).to_list(200)
    _shifts_by_id = {s["shift_id"]: s for s in _shift_docs}
    # Iter 94 — NIGHT-SHIFT aware: fetch one day EITHER side of the range
    # so an 8pm→8am shift pairs its next-morning OUT (and a morning OUT
    # already owned by the previous night's IN isn't double-counted).
    f_minus = (d0 - timedelta(days=1)).strftime("%Y-%m-%d")
    t_plus = (d1 + timedelta(days=1)).strftime("%Y-%m-%d")
    recs = await db.attendance.find(
        {"company_id": company_id, "date": {"$gte": f_minus, "$lte": t_plus},
         "status": {"$ne": "rejected"}},
        {"_id": 0, "record_id": 1, "user_id": 1, "date": 1, "kind": 1,
         "at": 1, "edited_at": 1, "source": 1, "status": 1,
         "edit_reason": 1, "edited_by": 1, "original_at": 1},
    ).to_list(40000)

    # Iter 111 — resolve the editing admin's name for the Updated tab.
    _editor_ids = {r.get("edited_by") for r in recs if r.get("edited_by")}
    _editor_names: Dict[str, str] = {}
    if _editor_ids:
        async for u in db.users.find(
            {"user_id": {"$in": list(_editor_ids)}}, {"_id": 0, "user_id": 1, "name": 1},
        ):
            _editor_names[u["user_id"]] = u.get("name") or u["user_id"]

    def _at_dt(r: dict) -> Optional[datetime]:
        try:
            dt = datetime.fromisoformat((r.get("at") or "").replace("Z", "+00:00"))
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except Exception:
            return None

    def _cell(r: Optional[dict]) -> Optional[dict]:
        if not r:
            return None
        hhmm = ""
        dt = _at_dt(r)
        if dt:
            hhmm = dt.strftime("%H:%M")
        # Iter 111 — original (pre-edit) time for the Updated tab audit view.
        orig_hhmm = None
        if r.get("original_at"):
            try:
                odt = datetime.fromisoformat((r["original_at"] or "").replace("Z", "+00:00"))
                orig_hhmm = (odt.replace(tzinfo=None) if odt.tzinfo else odt).strftime("%H:%M")
            except Exception:
                orig_hhmm = None
        return {
            "record_id": r["record_id"], "at": r.get("at"), "hhmm": hhmm,
            "date": r.get("date"),
            "edited": bool(r.get("edited_at")), "source": r.get("source"),
            "status": r.get("status"),
            "edit_reason": r.get("edit_reason"),
            "edited_by_name": _editor_names.get(r.get("edited_by") or ""),
            "original_hhmm": orig_hhmm,
        }

    by_user: Dict[str, list] = {}
    for r in recs:
        dt = _at_dt(r)
        if dt is None:
            continue
        r["_dt"] = dt
        by_user.setdefault(r["user_id"], []).append(r)
    for lst in by_user.values():
        lst.sort(key=lambda p: p["_dt"])

    dates = []
    cur = d0
    while cur <= d1:
        dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    rows = []
    for e in sorted(emps, key=lambda x: (x.get("name") or "")):
        _ov = e.get("attendance_policy_override") or {}
        _sh = _shifts_by_id.get(_ov.get("shift_id")) or {}
        _shift_start = _sh.get("start") or e.get("shift_start")
        _shift_end = _sh.get("end") or e.get("shift_end")
        ps = by_user.get(e["user_id"], [])
        consumed: set = set()
        # Chronological shift pairing: an IN owns the first un-consumed OUT
        # within the next 24h — even if the OUT lands on the NEXT date
        # (night shift). Process day f-1 first so its next-morning OUT
        # doesn't get misattributed to the first requested day.
        day_pairs: Dict[str, dict] = {}
        for d in [f_minus] + dates:
            first_in = next(
                (p for p in ps
                 if p["date"] == d and p.get("kind") == "in"
                 and p["record_id"] not in consumed),
                None,
            )
            out_rec = None
            if first_in:
                consumed.add(first_in["record_id"])
                limit = first_in["_dt"] + timedelta(hours=24)
                out_rec = next(
                    (p for p in ps
                     if p.get("kind") == "out"
                     and p["record_id"] not in consumed
                     and p["_dt"] > first_in["_dt"] and p["_dt"] <= limit),
                    None,
                )
                if out_rec:
                    consumed.add(out_rec["record_id"])
            else:
                # Orphan OUT (no IN that day and not owned by a previous IN)
                outs = [p for p in ps
                        if p["date"] == d and p.get("kind") == "out"
                        and p["record_id"] not in consumed]
                if outs:
                    out_rec = outs[-1]
                    consumed.add(out_rec["record_id"])
            # Iter 210 — SECOND pair = OT window (e.g. duty 08:00-20:00 then
            # OT-In 20:07 → OT-Out 07:59 next morning). Surfaced as its own
            # OT In / OT Out columns on the Punch Approvals tables.
            # Iter 212 — OT only applies to MORNING-shift employees (first
            # punch before 12:00). Evening/night first punches get no OT
            # pair (user rule).
            ot_in_rec = ot_out_rec = None
            if first_in and out_rec and first_in["_dt"].hour < 12:
                ot_in_rec = next(
                    (p for p in ps
                     if p["date"] == d and p.get("kind") == "in"
                     and p["record_id"] not in consumed
                     and p["_dt"] > out_rec["_dt"]),
                    None,
                )
                if ot_in_rec:
                    consumed.add(ot_in_rec["record_id"])
                    limit2 = ot_in_rec["_dt"] + timedelta(hours=24)
                    ot_out_rec = next(
                        (p for p in ps
                         if p.get("kind") == "out"
                         and p["record_id"] not in consumed
                         and p["_dt"] > ot_in_rec["_dt"] and p["_dt"] <= limit2),
                        None,
                    )
                    if ot_out_rec:
                        consumed.add(ot_out_rec["record_id"])
                else:
                    # Iter 211 — OT-Out WITHOUT an OT-In (employee forgot
                    # the OT-In punch): a second un-consumed OUT later the
                    # same day surfaces as a one-sided OT pair so the admin
                    # can fill the missing OT-In from Punch Approvals.
                    ot_out_rec = next(
                        (p for p in ps
                         if p["date"] == d and p.get("kind") == "out"
                         and p["record_id"] not in consumed
                         and p["_dt"] > out_rec["_dt"]),
                        None,
                    )
                    if ot_out_rec:
                        consumed.add(ot_out_rec["record_id"])
            day_pairs[d] = {"in": first_in, "out": out_rec,
                            "ot_in": ot_in_rec, "ot_out": ot_out_rec}
        for d in dates:
            pr = day_pairs.get(d) or {}
            first_in, out_rec = pr.get("in"), pr.get("out")
            edited_any = bool(
                (first_in and first_in.get("edited_at")) or
                (out_rec and out_rec.get("edited_at"))
            )
            rows.append({
                "key": f"{e['user_id']}|{d}",
                "user_id": e["user_id"],
                "date": d,
                "name": e.get("name"),
                "father_name": e.get("father_name"),
                "designation": e.get("designation"),
                "employee_code": e.get("employee_code"),
                "in": _cell(first_in),
                "out": _cell(out_rec),
                "ot_in": _cell(pr.get("ot_in")),
                "ot_out": _cell(pr.get("ot_out")),
                "updated": edited_any,
                "shift_start": _shift_start,
                "shift_end": _shift_end,
            })
    return {"rows": rows, "from_date": f, "to_date": t, "shifts": _shift_docs}


# ---------------------------------------------------------------------------
# Iter 94 — ADDITIONAL DUTY HRS / AMOUNT (Punch Approvals option).
# Admin can grant extra duty hours or a flat ₹ amount per employee per day
# (only meaningful for days where BOTH punches are complete). Extra HOURS
# flow into the monthly attendance grid (duty totals → P Days); extra
# AMOUNTS are added to "Oth.Allo" during the Actual Salary Process.
# ---------------------------------------------------------------------------
@api.get("/admin/attendance/extra-duty/{company_id}")
async def list_extra_duty(
    company_id: str,
    from_date: str = Query(...),
    to_date: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorised for this company")
    f = (from_date or "").strip()
    t = (to_date or "").strip() or f
    entries = await db.extra_duty_entries.find(
        {"company_id": company_id, "date": {"$gte": f, "$lte": t}},
        {"_id": 0},
    ).to_list(5000)
    return {"entries": entries}


@api.post("/admin/attendance/extra-duty")
async def upsert_extra_duty(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    user_id = str(payload.get("user_id") or "").strip()
    date_s = str(payload.get("date") or "").strip()
    if not user_id or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_s):
        raise HTTPException(status_code=400, detail="user_id and date (YYYY-MM-DD) required")
    emp = await db.users.find_one(
        {"user_id": user_id, "role": "employee"},
        {"_id": 0, "user_id": 1, "company_id": 1},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and admin.get("company_id") != emp.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this employee")
    try:
        extra_hours = round(float(payload.get("extra_hours") or 0.0), 2)
        extra_amount = round(float(payload.get("extra_amount") or 0.0), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="extra_hours / extra_amount must be numbers")
    if extra_amount < 0:
        raise HTTPException(status_code=400, detail="Amount cannot be negative")
    key = {"user_id": user_id, "date": date_s}
    if extra_hours == 0 and extra_amount == 0:
        await db.extra_duty_entries.delete_one(key)
        return {"ok": True, "deleted": True}
    entry = {
        **key,
        "company_id": emp.get("company_id"),
        "extra_hours": extra_hours,
        "extra_amount": extra_amount,
        "note": str(payload.get("note") or "").strip() or None,
        "updated_by": admin["user_id"],
        "updated_at": now_iso(),
    }
    await db.extra_duty_entries.update_one(
        key, {"$set": entry, "$setOnInsert": {"entry_id": f"xd_{uuid.uuid4().hex[:10]}"}},
        upsert=True,
    )
    saved = await db.extra_duty_entries.find_one(key, {"_id": 0})
    return {"ok": True, "entry": saved}


@api.post("/admin/attendance/manual-punch")
async def create_manual_punch(
    payload: ManualPunchCreate,
    authorization: Optional[str] = Header(None),
):
    """Insert a back-dated IN / OUT punch for an employee. The punch is
    auto-approved (`status=approved`) with source=`manual_admin` so
    payroll picks it up immediately.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A short reason is required for audit.")
    emp = await db.users.find_one(
        {"user_id": payload.user_id},
        {"_id": 0, "user_id": 1, "company_id": 1, "role": 1, "name": 1},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Employee not in your company")

    when = _parse_manual_at(payload.at)
    _enforce_lookback(admin, when)

    record_id = f"att_{uuid.uuid4().hex[:12]}"
    record = {
        "record_id": record_id,
        "user_id": payload.user_id,
        "company_id": emp.get("company_id"),
        "date": when.strftime("%Y-%m-%d"),
        "kind": payload.kind,
        "at": when.isoformat().replace("+00:00", "Z"),
        "source": "manual_admin",
        "status": "approved",
        "approved_by": admin["user_id"],
        "manual_reason": reason,
        "created_by": admin["user_id"],
        "created_at": now_iso(),
    }
    await db.attendance.insert_one(record)
    await _log_punch_audit("create", admin, record_id, None, record, reason)
    # Iter 145 — web-push the manual punch approval to the employee.
    try:
        from routes.web_push import push_to_user
        _k = "IN" if payload.kind == "in" else "OUT"
        await push_to_user(
            payload.user_id, f"Punch {_k} added by employer",
            f"A Punch {_k} was recorded for you on {record['date']} ({reason}).",
            url="/attendance", tag=f"punch_{record_id}")
    except Exception:
        pass
    return {"ok": True, "record": {k: v for k, v in record.items() if k != "_id"}}


@api.patch("/admin/attendance/{record_id}")
async def edit_attendance_record(
    record_id: str,
    payload: ManualPunchEdit,
    authorization: Optional[str] = Header(None),
):
    """Edit an existing attendance record's time and/or kind. Reason is
    mandatory for audit."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A short reason is required for audit.")
    rec = await db.attendance.find_one({"record_id": record_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Punch not found")
    if admin["role"] == "company_admin" and rec.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this punch")

    # Guard the ORIGINAL date against lookback for company_admin
    try:
        orig_when = datetime.fromisoformat((rec.get("at") or "").replace("Z", "+00:00"))
        if orig_when.tzinfo is None:
            orig_when = orig_when.replace(tzinfo=timezone.utc)
    except Exception:
        orig_when = datetime.now(timezone.utc)
    _enforce_lookback(admin, orig_when)

    updates: dict = {
        "edited_by": admin["user_id"],
        "edited_at": now_iso(),
        "edit_reason": reason,
        # Iter 94 — per user request, punch edits made by a Company or
        # Super Admin are DIRECTLY linked to Employee Attendance In/Out.
        # The editing admin IS the approver, so the record stays approved
        # and flows straight into the Attendance Report / payroll. Full
        # audit trail retained via attendance_audit_log + edited_* fields.
        "status": "approved",
        "decision_by": admin["user_id"],
        "decision_at": now_iso(),
        "decision_reason": f"Edited by {admin.get('role')}: {reason}",
    }
    if payload.at:
        new_when = _parse_manual_at(payload.at)
        _enforce_lookback(admin, new_when)
        updates["at"] = new_when.isoformat().replace("+00:00", "Z")
        updates["date"] = new_when.strftime("%Y-%m-%d")
        # Preserve original ISO for audit trail
        if not rec.get("original_at"):
            updates["original_at"] = rec.get("at")
    if payload.kind:
        updates["kind"] = payload.kind

    r = await db.attendance.update_one({"record_id": record_id}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Punch disappeared during update")
    new_rec = await db.attendance.find_one(
        {"record_id": record_id}, {"_id": 0, "selfie_base64": 0}
    )
    await _log_punch_audit("edit", admin, record_id, rec, new_rec, reason)
    return {"ok": True, "record": new_rec}


@api.delete("/admin/attendance/{record_id}")
async def delete_attendance_record(
    record_id: str,
    reason: str = Query(..., min_length=1, description="Audit reason (required)"),
    authorization: Optional[str] = Header(None),
):
    """Hard-delete an attendance record. Restricted to 90-day lookback for
    company_admin. Original row is captured in the audit log."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A short reason is required for audit.")
    rec = await db.attendance.find_one({"record_id": record_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Punch not found")
    if admin["role"] == "company_admin" and rec.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this punch")
    try:
        orig_when = datetime.fromisoformat((rec.get("at") or "").replace("Z", "+00:00"))
        if orig_when.tzinfo is None:
            orig_when = orig_when.replace(tzinfo=timezone.utc)
    except Exception:
        orig_when = datetime.now(timezone.utc)
    _enforce_lookback(admin, orig_when)

    await db.attendance.delete_one({"record_id": record_id})
    await _log_punch_audit("delete", admin, record_id, rec, None, reason)
    return {"ok": True, "deleted_record_id": record_id}


@api.get("/admin/attendance/manual-log/{company_id}")
async def manual_punch_log(
    company_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 113 — quick log of admin-created Individual/Manual punches
    (source=manual_admin) for the Punch Approvals review panel, enriched
    with employee + creating-admin names so each entry can be audited or
    undone (DELETE /admin/attendance/{record_id})."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="You can only view your own firm")
    if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm not in your scope")
    q: dict = {"company_id": company_id, "source": "manual_admin"}
    if from_date or to_date:
        rng: dict = {}
        if from_date:
            rng["$gte"] = from_date
        if to_date:
            rng["$lte"] = to_date
        q["date"] = rng
    recs = await db.attendance.find(
        q,
        {"_id": 0, "record_id": 1, "user_id": 1, "date": 1, "kind": 1,
         "at": 1, "manual_reason": 1, "created_by": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(300)
    uids = {r["user_id"] for r in recs} | {r.get("created_by") for r in recs if r.get("created_by")}
    names: Dict[str, dict] = {}
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": list(uids)}},
            {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1},
        ):
            names[u["user_id"]] = u
    for r in recs:
        emp = names.get(r["user_id"]) or {}
        r["employee_name"] = emp.get("name") or r["user_id"]
        r["employee_code"] = emp.get("employee_code")
        r["created_by_name"] = (names.get(r.get("created_by") or "") or {}).get("name")
        r["hhmm"] = (r.get("at") or "")[11:16]
    return {"records": recs, "count": len(recs)}


@api.get("/admin/attendance/{record_id}/audit")
async def get_attendance_audit(
    record_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return the audit trail for a single attendance record. Company
    admins are scoped to their own company via the current record's
    company_id (or via any historical audit row that references it)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    # Attempt to fetch the current record (may be deleted — that's fine)
    rec = await db.attendance.find_one({"record_id": record_id}, {"_id": 0})
    if rec and admin["role"] == "company_admin":
        if rec.get("company_id") != admin.get("company_id"):
            raise HTTPException(status_code=403, detail="Not authorised for this punch")
    rows = await db.attendance_audit_log.find(
        {"record_id": record_id}, {"_id": 0}
    ).sort("at", 1).to_list(200)
    return {"record_id": record_id, "audit": rows, "record": rec}


@api.get("/admin/attendance/history")
async def list_attendance_history(
    user_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD (inclusive)"),
    limit: int = Query(500, ge=1, le=2000),
    authorization: Optional[str] = Header(None),
):
    """Admin-facing history search used by the Back-date Punch editor.
    Company admins are always scoped to their own company."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    q: dict = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif company_id:
        q["company_id"] = company_id
    if user_id:
        q["user_id"] = user_id
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["date"] = rng
    rows = await db.attendance.find(
        q, {"_id": 0, "selfie_base64": 0}
    ).sort("at", -1).to_list(limit)
    return {"records": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Monthly payroll email reports (attendance / salary / combined)
# ---------------------------------------------------------------------------
