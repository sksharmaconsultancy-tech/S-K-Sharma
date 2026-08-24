"""Iter 409 — ATTENDANCE SELF-SERVICE + PUNCH APPROVALS module (split out
of routes/attendance_core.py).

Refactor only: every endpoint, model and helper below was MOVED verbatim —
the admin punch-approval queue (pending punches + approve/reject/adjust
decisions), and the employee-facing history, selfie, my-month and summary
endpoints. Pure hour helpers (_compute_day_hours & co.) moved to
shared/hours.py. No behavioural change.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from server import (  # noqa: E402
    _compute_monthly_grid_data,
    apply_employee_policy_override,
    db,
    get_user_from_token,
    logger,
    now_iso,
    require_role,
)
from routes.attendance_location_api import _compute_location_status  # noqa: E402
from shared.hours import _compute_day_hours  # noqa: E402

router = APIRouter(prefix="/api")
api = router


# ---------------------------------------------------------------------------
# Attendance approvals — Approve / Reject / Adjust for AUTO punches when the
# firm has punch_approval_required = True (default).
# ---------------------------------------------------------------------------
class PunchDecision(BaseModel):
    action: Literal["approve", "reject", "adjust"]
    # Required for "adjust" — the corrected wall-clock time. Accepts either a
    # full ISO timestamp or "HH:MM" (interpreted against the record's own date).
    adjusted_time: Optional[str] = None
    reason: Optional[str] = None


def _parse_adjust_time(record: dict, raw: str) -> str:
    """Normalise an admin-supplied adjustment time. Accepts:
      - full ISO ("2026-06-15T09:12:00+00:00")
      - "HH:MM" — combined with the record's `date` in UTC.
    Returns an ISO 8601 string. Raises HTTPException(400) on bad input.
    """
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Please enter the corrected punch time.")
    # HH:MM shorthand
    if re.fullmatch(r"[0-2][0-9]:[0-5][0-9]", raw):
        base_date = record.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            dt = datetime.fromisoformat(f"{base_date}T{raw}:00+00:00")
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid time '{raw}' — use HH:MM (24-hour).")
        return dt.isoformat()
    # Full ISO
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=f"'{raw}' isn’t a valid time. Use HH:MM or a full ISO timestamp.",
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@api.get("/attendance/pending-punches")
async def list_pending_punches(
    company_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    include_decided: bool = Query(False),
    authorization: Optional[str] = Header(None),
):
    """Attendance approval queue for admins. Super admins see all pending
    punches (optionally filtered by ?company_id=); company admins are always
    scoped to their own company. Set ?include_decided=true to also return
    the last N records that were already approved/rejected (audit view)."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "company_admin", "sub_admin"])
    q: dict = {}
    if user["role"] == "company_admin":
        q["company_id"] = user["company_id"]
    elif company_id:
        q["company_id"] = company_id
    if not include_decided:
        q["status"] = "pending"
    else:
        q["status"] = {"$in": ["pending", "approved", "rejected"]}
    records = await db.attendance.find(
        q, {"_id": 0, "selfie_base64": 0}
    ).sort("at", -1).to_list(limit)
    # Attach a compact user summary so the UI doesn't need N follow-up calls
    user_ids = list({r.get("user_id") for r in records if r.get("user_id")})
    users = {}
    if user_ids:
        async for u in db.users.find(
            {"user_id": {"$in": user_ids}},
            {"_id": 0, "user_id": 1, "name": 1, "father_name": 1, "employee_code": 1, "designation": 1, "profile_photo_base64": 1},
        ):
            users[u["user_id"]] = u
    for r in records:
        u = users.get(r.get("user_id")) or {}
        r["employee"] = {
            "user_id": u.get("user_id"),
            "name": u.get("name"),
            "father_name": u.get("father_name"),
            "employee_code": u.get("employee_code"),
            "bio_code": u.get("bio_code"),
            "designation": u.get("designation"),
            "profile_photo_base64": u.get("profile_photo_base64"),
        }
    pending_count = sum(1 for r in records if (r.get("status") or "") == "pending")
    return {"records": records, "pending_count": pending_count}


@api.post("/attendance/punches/{record_id}/decision")
async def decide_punch(
    record_id: str,
    payload: PunchDecision,
    authorization: Optional[str] = Header(None),
):
    """Approve / Reject / Adjust a pending auto-punch."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "company_admin", "sub_admin"])
    rec = await db.attendance.find_one({"record_id": record_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Punch not found")
    if user["role"] == "company_admin" and rec.get("company_id") != user.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this punch")
    if (rec.get("status") or "approved") != "pending":
        # Super admins can retroactively edit any punch (rare, but useful when
        # the admin realises later that yesterday's approved punch is wrong).
        # Company admins can only act on pending punches.
        if user.get("role") != "super_admin":
            raise HTTPException(
                status_code=400,
                detail=f"This punch was already {(rec.get('status') or 'approved')}. Only a super admin can change a decided punch.",
            )
    updates: dict = {
        "decision_by": user["user_id"],
        "decision_at": now_iso(),
        "decision_reason": (payload.reason or "").strip() or None,
    }
    if payload.action == "approve":
        updates["status"] = "approved"
    elif payload.action == "reject":
        # Reject requires a reason so the audit trail is meaningful.
        if not updates["decision_reason"]:
            raise HTTPException(status_code=400, detail="Please provide a short reason for rejecting this punch.")
        updates["status"] = "rejected"
    elif payload.action == "adjust":
        # Adjust = approve with a corrected time. Iter 83-final — Also
        # update the canonical ``at`` field so downstream views (grid,
        # OT report, IN/OUT sheet) pick up the adjusted time. The
        # ORIGINAL punch time is preserved on ``original_at`` for audit.
        if not payload.adjusted_time:
            raise HTTPException(status_code=400, detail="Adjustment time is required to save an adjusted punch.")
        new_iso = _parse_adjust_time(rec, payload.adjusted_time)
        updates["status"] = "approved"
        updates["adjusted_at"] = new_iso
        updates["adjusted_by"] = user["user_id"]
        if not rec.get("original_at"):
            updates["original_at"] = rec.get("at")
        updates["at"] = new_iso
        updates.setdefault("decision_reason", None)
        if not updates["decision_reason"]:
            updates["decision_reason"] = "Time adjusted by admin"
    r = await db.attendance.update_one({"record_id": record_id}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Punch disappeared during update")
    updated = await db.attendance.find_one({"record_id": record_id}, {"_id": 0, "selfie_base64": 0})
    return {"ok": True, "record": updated}


@api.get("/attendance/history")
async def attendance_history(
    days: int = Query(30, le=90),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    # Iter 708 — firm-wise PWA visibility cutoff (records stay in the DB;
    # the employee PWA just no longer receives the wiped months).
    from routes.pwa_data_mgmt import get_hidden_before
    hidden_before = await get_hidden_before(user.get("company_id"))
    if hidden_before and hidden_before > since:
        since = hidden_before
    records = await db.attendance.find(
        {"user_id": user["user_id"], "date": {"$gte": since}},
        {"_id": 0, "selfie_base64": 0},
    ).sort("at", -1).to_list(1000)
    # Iter 64 — surface location_status for the employee-side history UI.
    for r in records:
        if not r.get("location_status"):
            r["location_status"] = _compute_location_status(r)
    return {"records": records}


@api.get("/attendance/{record_id}/selfie")
async def get_my_punch_selfie(
    record_id: str,
    authorization: Optional[str] = Header(None),
):
    """Iter 97 — employee self-access to the selfie captured on their OWN
    punch. Strictly scoped: the attendance record's user_id must match the
    requesting token's user_id."""
    user = await get_user_from_token(authorization)
    rec = await db.attendance.find_one(
        {"record_id": record_id},
        {"_id": 0, "selfie_base64": 1, "user_id": 1},
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Punch not found")
    if rec.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your punch")
    _b64 = rec.get("selfie_base64")
    # Iter 306 — legacy rows stored with a data-URL prefix render blank.
    if _b64 and _b64.startswith("data:"):
        _b64 = _b64.split("base64,", 1)[-1]
    return {"selfie_base64": _b64}


@api.get("/attendance/my-month")
async def my_month_attendance(
    month: str = Query(..., description="YYYY-MM"),
    authorization: Optional[str] = Header(None),
):
    """Employee self-service month view. Computed with the SAME policy
    pipeline as the admin Attendance Grid (bounce-merge, dedup, OT cap,
    weekly-off rules, shift/policy overrides) so the attendance data an
    employee sees always matches their assigned attendance policy."""
    user = await get_user_from_token(authorization)
    company_id = user.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="No firm linked to your account")
    if not re.match(r"^\d{4}-\d{2}$", month or ""):
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    # Iter 708 — firm-wise PWA visibility cutoff: months before the wipe
    # date return an empty (cleared) view on the Employee PWA only.
    from routes.pwa_data_mgmt import get_hidden_before
    hidden_before = await get_hidden_before(company_id)
    if hidden_before and f"{month}-31" < hidden_before:
        return {"month": month, "days": [], "weekly_off_days": [],
                "pwa_wiped": True}
    data = await _compute_monthly_grid_data(
        company_id=company_id, month=month, only_user_id=user["user_id"],
    )
    row = next(
        (r for r in (data.get("employees") or []) if r.get("user_id") == user["user_id"]),
        None,
    )
    # Effective weekly-off days (firm policy + per-employee override) so the
    # client can mark week-offs even on days without punches.
    comp = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "attendance_policy": 1},
    )
    pol = (comp or {}).get("attendance_policy") or {}
    emp_doc = await db.users.find_one(
        {"user_id": user["user_id"]}, {"_id": 0, "attendance_policy_override": 1},
    )
    eff = apply_employee_policy_override(dict(pol), emp_doc or {})
    weekly_off_days = list(eff.get("weekly_off_days") or [])
    weekly_set = set(weekly_off_days)

    labels = data.get("day_labels") or []
    full_dates = data.get("day_full_dates") or []
    days: Dict[str, Any] = {}
    totals: Dict[str, Any] = {}
    if row:
        for idx, lbl in enumerate(labels):
            c = dict((row.get("days") or {}).get(lbl) or {})
            c.pop("salary", None)  # attendance-only view (no pay data here)
            # Grid cells only carry present/weekly_off on cleanly-paired
            # punch days — normalise so EVERY cell has both fields.
            if "present" not in c:
                c["present"] = 0.0
            if "weekly_off" not in c:
                try:
                    wd = datetime.strptime(full_dates[idx], "%Y-%m-%d").weekday()
                except (ValueError, IndexError):
                    wd = -1
                c["weekly_off"] = wd in weekly_set
            days[lbl] = c
        totals = dict(row.get("totals") or {})
        totals.pop("salary_total", None)
    return {
        "month": data.get("month"),
        "day_labels": labels,
        "day_full_dates": full_dates,
        "weekday_labels": data.get("weekday_labels"),
        "full_day_hours": data.get("full_day_hours"),
        "weekly_off_days": weekly_off_days,
        "days": days,
        "totals": totals,
    }


@api.get("/attendance/summary")
async def attendance_summary(
    days: int = Query(7, ge=1, le=90),
    authorization: Optional[str] = Header(None),
):
    """Return per-day duty hours for the last N days for the current user,
    plus total hours worked till today (all-time) and window total."""
    user = await get_user_from_token(authorization)
    since_dt = datetime.now(timezone.utc) - timedelta(days=days - 1)
    since_str = since_dt.strftime("%Y-%m-%d")
    recs = await db.attendance.find(
        {"user_id": user["user_id"], "date": {"$gte": since_str}},
        {"_id": 0, "selfie_base64": 0},
    ).sort("at", 1).to_list(5000)
    by_date: dict[str, list] = {}
    for r in recs:
        by_date.setdefault(r.get("date"), []).append(r)

    days_out: list[dict] = []
    for i in range(days - 1, -1, -1):
        d = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        hrs, fin, lout, still = _compute_day_hours(by_date.get(d) or [])
        days_out.append({
            "date": d,
            "hours": hrs,
            "first_in": fin,
            "last_out": lout,
            "still_in": still,
            "punches": len(by_date.get(d) or []),
        })

    # User directive — the employee-facing duty widget must follow the Firm
    # Master attendance policy. Overlay per-day HOURS from the same grid
    # pipeline the admin Grid View / payroll uses (bounce-merge, dedup, OT
    # cap, shift overrides, missing-punch = 0). first_in/last_out/still_in
    # stay raw so the "currently punched-in" indicator keeps working.
    if user.get("company_id"):
        try:
            to_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            pdata = await _compute_monthly_grid_data(
                company_id=user["company_id"],
                month=since_str[:7],
                from_date=since_str,
                to_date=to_str,
                only_user_id=user["user_id"],
            )
            prow = next(
                (r for r in (pdata.get("employees") or [])
                 if r.get("user_id") == user["user_id"]),
                None,
            )
            if prow:
                cells = prow.get("days") or {}
                labels = pdata.get("day_labels") or []
                dates = pdata.get("day_full_dates") or []
                by_full_date = {
                    dates[i]: cells.get(labels[i]) or {}
                    for i in range(min(len(labels), len(dates)))
                }
                for row in days_out:
                    cell = by_full_date.get(row["date"])
                    if cell is not None and not row.get("still_in"):
                        row["hours"] = float(cell.get("hours") or 0.0)
        except Exception:
            logger.exception("policy overlay failed for /attendance/summary")
    window_total = round(sum(d["hours"] for d in days_out), 2)

    # All-time total — compute across ALL of the user's attendance in one pass
    all_recs = await db.attendance.find(
        {"user_id": user["user_id"]},
        {"_id": 0, "selfie_base64": 0, "device_info": 0},
    ).sort("at", 1).to_list(50000)
    all_by_date: dict[str, list] = {}
    for r in all_recs:
        all_by_date.setdefault(r.get("date"), []).append(r)
    total_all = 0.0
    for d, rs in all_by_date.items():
        h, _, _, _ = _compute_day_hours(rs)
        total_all += h
    total_all = round(total_all, 2)

    return {
        "days": days_out,
        "window_total_hours": window_total,
        "total_hours_till_today": total_all,
    }


@api.post("/attendance/punches/approve-all-pending")
async def approve_all_pending_punches(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Iter 639 (user request) — APPROVE BACKLOG: one click approves EVERY
    pending punch in the admin's scope so the Attendance Grid is instantly
    up to date. Same decision fields as a single approval (full audit)."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "company_admin", "sub_admin"])
    q: dict = {"status": "pending"}
    if user["role"] == "company_admin":
        q["company_id"] = user["company_id"]
    elif company_id:
        q["company_id"] = company_id
    r = await db.attendance.update_many(q, {"$set": {
        "status": "approved",
        "decision_by": user["user_id"],
        "decision_at": now_iso(),
        "decision_reason": "Bulk approve — pending backlog cleared by admin",
    }})
    return {"ok": True, "approved": r.modified_count}
