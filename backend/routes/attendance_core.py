"""Iter 398 — ATTENDANCE CORE module (extracted from server.py).

Refactor only — MOVED verbatim: worksites, employee punch engine
(geofence + face match + onboarding gate), first-punch-status, today,
geofence-exit alert, pending punches + decisions, history + selfie,
my-month, summary, admin today / present-not-punched / approve-punch /
auto-close / open-shifts / roster (+mark) / day-status / extra-duty /
manual-punch / record patch-delete-audit / manual-log / admin history,
the payroll compute engine (_compute_payroll_run) and shared date/report
helpers (_parse_any_date, _month_is_after_exit, _month_is_before_doj,
_employee_inactive_for_report). Shared names are re-imported into
server.py's namespace right after this module loads so every other
route module keeps importing them `from server import ...` unchanged."""
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
    AttendancePunch,
    LocationPing,
    _compare_faces,
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
from routes.attendance_location_api import _compute_location_status  # noqa: E402

router = APIRouter(prefix="/api")
api = router


@api.get("/attendance/worksites")
async def my_worksites(authorization: Optional[str] = Header(None)):
    """Iter 176 — worksites for the guided punch flow: the firm's main
    office plus all active branches (id, name, coords, radius). Available
    to any logged-in employee of the firm."""
    user = await get_user_from_token(authorization)
    if not user.get("company_id"):
        raise HTTPException(status_code=400, detail="No company assigned")
    company = await db.companies.find_one(
        {"company_id": user["company_id"]},
        {"_id": 0, "name": 1, "office_lat": 1, "office_lng": 1, "geofence_radius_m": 1},
    )
    sites: List[dict] = []
    if company and company.get("office_lat") is not None:
        sites.append({
            "worksite_id": "main",
            "name": f"{company.get('name') or 'Main Office'} (Main Office)",
            "office_lat": company["office_lat"],
            "office_lng": company["office_lng"],
            "geofence_radius_m": company.get("geofence_radius_m") or 200,
        })
    async for b in db.branches.find(
        {"company_id": user["company_id"], "active": {"$ne": False}},
        {"_id": 0, "branch_id": 1, "name": 1, "office_lat": 1,
         "office_lng": 1, "geofence_radius_m": 1},
    ):
        sites.append({
            "worksite_id": b["branch_id"],
            "name": b.get("name") or "Branch",
            "office_lat": b["office_lat"],
            "office_lng": b["office_lng"],
            "geofence_radius_m": b.get("geofence_radius_m") or 200,
        })
    return {"worksites": sites}


# ---------------------------------------------------------------------------
# Iter 285 — Employee Onboarding Approval Workflow (Phase 1) gates.
# Settings live at companies.onboarding_approval (routes/onboarding_approval).
ONBOARDING_BLOCKED_STATUSES = ["draft", "pending_approval", "hold", "rejected"]


async def _onboarding_cfg(company_id: Optional[str]) -> dict:
    if not company_id:
        return {}
    c = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "onboarding_approval": 1})
    return (c or {}).get("onboarding_approval") or {}


async def _onboarding_login_gate(user: dict) -> None:
    """Block employee logins while onboarding is unapproved (per firm policy).

    Login is allowed when EITHER mobile or web login is permitted before
    approval (the PWA can't reliably distinguish the two channels).
    """
    if (user or {}).get("role") != "employee":
        return
    st = user.get("onboarding_status")
    if not st or st in ("approved", "active"):
        return
    if st == "rejected":
        raise HTTPException(
            status_code=403,
            detail="Your registration was rejected. Please contact HR.")
    cfg = await _onboarding_cfg(user.get("company_id"))
    if not cfg.get("enabled"):
        return
    if st == "hold":
        raise HTTPException(
            status_code=403,
            detail="Your account is on hold pending HR review. Contact HR.")
    if not (cfg.get("allow_mobile_login", True) or cfg.get("allow_web_login", True)):
        raise HTTPException(
            status_code=403,
            detail="Your account is awaiting HR approval. Please try again once approved.")


def _onboarding_punch_gate(user: dict, company: dict) -> None:
    """Reject punches from unapproved employees per firm policy. When
    'store attendance' is on, punches are accepted (stored) but the
    employee stays excluded from payroll until approval."""
    if (user or {}).get("role") != "employee":
        return
    st = user.get("onboarding_status")
    if not st or st in ("approved", "active"):
        return
    if st == "rejected":
        raise HTTPException(
            status_code=403,
            detail="Registration rejected — punching is disabled. Contact HR.")
    cfg = (company or {}).get("onboarding_approval") or {}
    if not cfg.get("enabled"):
        return
    if not cfg.get("allow_punch", True) and not cfg.get("store_attendance", True):
        raise HTTPException(
            status_code=403,
            detail="Punching is disabled until HR approves your registration.")


async def _onboarding_payroll_exclusion(q: dict, company_id: Optional[str],
                                        allow_keys: list) -> None:
    """Exclude not-yet-approved employees from payroll runs unless the
    firm policy explicitly allows ALL the given processing types before
    approval. Employees without an onboarding_status are unaffected."""
    cfg = await _onboarding_cfg(company_id)
    if cfg.get("enabled") and all(bool(cfg.get(k)) for k in allow_keys):
        return
    q.setdefault("$and", []).append(
        {"onboarding_status": {"$nin": ONBOARDING_BLOCKED_STATUSES}})


@api.post("/attendance/punch")
async def punch(payload: AttendancePunch, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    # Iter 306 (user bug #3) — on WEB the expo-camera base64 includes a
    # "data:image/…;base64," prefix. Stored verbatim, every viewer that
    # builds "data:image/jpeg;base64,<b64>" produced an invalid double
    # prefix → the punch photo rendered BLANK. Strip it at the door.
    if payload.selfie_base64 and payload.selfie_base64.startswith("data:"):
        payload.selfie_base64 = payload.selfie_base64.split("base64,", 1)[-1]
    if not user.get("company_id"):
        raise HTTPException(status_code=400, detail="No company assigned. Contact admin.")
    company = await db.companies.find_one({"company_id": user["company_id"]}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=400, detail="Company not found")

    # Iter 285 — onboarding approval gate (may 403 for unapproved staff).
    _onboarding_punch_gate(user, company)


    # Offline-sync idempotency (Phase 2): if this exact queued punch was
    # already accepted (same client_dedupe_id), return it instead of making
    # a duplicate. Keeps retries / multi-tab sync safe.
    if payload.client_dedupe_id:
        dup = await db.attendance.find_one(
            {"user_id": user["user_id"], "client_dedupe_id": payload.client_dedupe_id},
            {"_id": 0, "status": 1, "attendance_status": 1, "distance_m": 1})
        if dup:
            return {"ok": True, "duplicate": True,
                    "status": dup.get("status"),
                    "attendance_status": dup.get("attendance_status"),
                    "distance_m": dup.get("distance_m", 0),
                    "approval_required": dup.get("status") == "pending"}

    # Live-in staff (e.g. resort housekeeping who sleep on premises) are
    # ALWAYS inside the resort, but they can still be off-duty. For them
    # we bypass the geofence hard-reject entirely — the shift schedule +
    # daily roster handle who's actually working. Face-match (if enabled)
    # still applies so identity is verified.
    is_live_in = bool(user.get("is_live_in"))

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Iter 99 — GEOFENCE IS MANDATORY IN EVERY CONDITION (user rule).
    # ------------------------------------------------------------------
    # The old Iter 57 "no-GPS manual" bypass is REMOVED. Every punch —
    # auto (geofence), manual face or manual fingerprint — must carry GPS
    # coordinates and pass the geofence check. The only exception is
    # live-in staff (always on premises by definition).
    #
    # Iter 64 — GPS punching gating (kept for the punch *mode*):
    # ``gps_allowed`` = firm allows GPS punching AND user opted in. When
    # False the punch is in MANUAL BIOMETRIC mode: selfie + device
    # biometric are required — but the geofence check still applies.
    firm_loc_allow = bool(company.get("location_punching_enabled") is True)
    user_gps_opt = bool(user.get("gps_punch_enabled") is True)
    gps_allowed = firm_loc_allow and user_gps_opt
    manual_mode = not gps_allowed

    if manual_mode and not is_live_in:
        if not payload.selfie_base64:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Face selfie is required for manual punching. "
                    "Please capture a selfie and try again."
                ),
            )
        if payload.biometric_method not in ("fingerprint", "face"):
            raise HTTPException(
                status_code=400,
                detail="Device biometric (fingerprint/face) is required.",
            )

    # Only live-in staff may punch without coordinates.
    no_gps_manual = (
        payload.latitude is None
        or payload.longitude is None
    ) and is_live_in

    if no_gps_manual:
        dist = 0.0
        closest = None
        radius = company.get("geofence_radius_m") or 200
        outside = False   # live-in staff are on premises by definition
    else:
        if payload.latitude is None or payload.longitude is None:
            # Iter 99 — geofence verification is mandatory for every punch.
            raise HTTPException(
                status_code=400,
                detail=(
                    "Location is required — geofence verification is "
                    "mandatory for every punch. Please enable GPS/Location "
                    "and try again."
                ),
            )
        dist, closest = await _resolve_geofence(company, payload.latitude, payload.longitude)
        radius = closest.get("geofence_radius_m", 200) if closest else (
            company.get("geofence_radius_m") or 200
        )
        if not closest:
            # Firm has not configured any geofence (no office coords and no
            # branches) — nothing to verify against. Record the coords and
            # allow; admins should configure the geofence in Companies.
            outside = False
        else:
            # Iter 295 (user bug: "inside the radius but shows Not in
            # Range") — phone GPS (especially browser/PWA geolocation on
            # iOS) can be off by 50–500 m even when the employee is
            # standing in the office. Give the punch the benefit of the
            # device-reported GPS accuracy, CAPPED at 100 m so a wildly
            # inaccurate fix can never be exploited to punch from far away.
            _acc_allow = min(max(float(payload.gps_accuracy_m or 0.0), 0.0), 100.0)
            outside = (dist - _acc_allow) > radius
        if is_live_in:
            outside = False  # never treat live-in staff as outside


    # Load today's punches once — needed for both geofence AND toggle checks.
    # This lets an employee punch IN → OUT → IN → OUT ... any number of times
    # per day (each entry/exit is logged as a separate record), while still
    # rejecting double-IN or double-OUT which would corrupt the log.
    # Rejected punches are ignored for the last-kind check.
    # Iter 144 — "today" follows IST wall-clock (punch storage convention).
    # Phase 2 (offline sync): a punch queued offline carries its ORIGINAL
    # capture time (client_punch_at, real UTC ISO). Honour it so the punch
    # lands on the correct date/time even if it syncs hours/days later.
    punch_at_iso = None
    if payload.offline and payload.client_punch_at:
        try:
            _cap = datetime.fromisoformat(payload.client_punch_at.replace("Z", "+00:00"))
            if _cap.tzinfo is None:
                _cap = _cap.replace(tzinfo=timezone.utc)
            # Convert to IST wall-clock labelled UTC (storage convention).
            _cap_ist = _cap.astimezone(IST_TZ).replace(tzinfo=timezone.utc)
            # Sanity: reject future times / older than 7 days (clock tampering).
            _now = ist_wallclock_now()
            if _now - timedelta(days=7) <= _cap_ist <= _now + timedelta(minutes=10):
                punch_at_iso = _cap_ist.isoformat()
        except Exception:
            punch_at_iso = None
    today = (punch_at_iso[:10] if punch_at_iso
             else ist_wallclock_now().strftime("%Y-%m-%d"))
    today_recs = await db.attendance.find(
        {"user_id": user["user_id"], "date": today,
         "status": {"$ne": "rejected"}},
        {"_id": 0, "kind": 1, "at": 1, "status": 1},
    ).sort("at", 1).to_list(200)
    last_kind = today_recs[-1].get("kind") if today_recs else None

    # -----------------------------------------------------------------------
    # Auto-punch debounce (20 minutes)
    # -----------------------------------------------------------------------
    # When the geofence background task fires an auto-punch we don't want a
    # brief GPS jitter (employee stepped outside for a moment, or the phone
    # briefly lost signal) to record a spurious OUT (or a duplicate IN). Any
    # auto-source punch within `_AUTO_PUNCH_DEBOUNCE_MIN` minutes of the last
    # recorded punch — regardless of kind — is treated as a no-op and returns
    # the previous record so the client can update its local state cleanly.
    _AUTO_PUNCH_DEBOUNCE_MIN = 20  # minutes
    _incoming_src = (payload.source or "manual").lower()
    _is_auto = "auto" in _incoming_src or "geofence" in _incoming_src
    if _is_auto and today_recs:
        last = today_recs[-1]
        try:
            last_at = datetime.fromisoformat((last.get("at") or "").replace("Z", "+00:00"))
        except Exception:
            last_at = None
        if last_at is not None:
            # Iter 144 — compare in wall-clock space (punches are stored as
            # IST wall-clock labelled UTC).
            elapsed = (ist_wallclock_now() - last_at).total_seconds() / 60.0
            if elapsed < _AUTO_PUNCH_DEBOUNCE_MIN:
                logger.info(
                    "[punch] Debouncing auto punch for user=%s (%.1f min since last %s at %s)",
                    user["user_id"], elapsed, last.get("kind"), last.get("at"),
                )
                # Return the previous record so the client stays in sync
                # without surfacing an error to the user.
                return {
                    "ok": True,
                    "debounced": True,
                    "reason": "auto_punch_debounce",
                    "cooldown_minutes_remaining": round(_AUTO_PUNCH_DEBOUNCE_MIN - elapsed, 1),
                    "last_punch": {
                        "kind": last.get("kind"),
                        "at": last.get("at"),
                        "status": last.get("status") or "approved",
                    },
                }

    # Iter 68 — GEOFENCE IS ON BY DEFAULT.
    #
    # Phase-1 geofence POLICY: resolve the effective mode (strict / flexible
    # / field / remote / emergency) for this employee and let it drive the
    # accept / reject / approval decision. Default = strict, which keeps the
    # original behaviour intact for firms that don't configure a policy.
    from routes.geo_policy import resolve_geo_policy, evaluate_geo_punch
    _pol = await resolve_geo_policy(user, company)
    pol_mode = _pol["mode"]
    pol_settings = _pol["settings"]
    pol_decision = evaluate_geo_punch(
        pol_mode, pol_settings,
        outside=bool(outside), dist=float(dist), radius=float(radius),
        lat=payload.latitude, lng=payload.longitude,
        has_selfie=bool(payload.selfie_base64),
        reason=payload.reason, is_live_in=is_live_in,
    )
    # A non-strict mode may permit an outside punch — in that case we skip
    # the legacy hard-reject and let the record carry the policy status.
    policy_allows_outside = bool(pol_decision["allow"]) and pol_mode != "strict"

    # If the policy explicitly rejects (strict-outside, remote-outside,
    # missing reason/selfie for flexible/emergency) surface that message.
    if outside and not pol_decision["allow"]:
        raise HTTPException(status_code=400, detail=pol_decision["reject_reason"])

    # Iter 68 punch policy:
    #   • Outside the geofence → HARD REJECT (strict mode only).
    #   • Inside the geofence  → allow.  Auto-punches ("geofence-auto"
    #     source) are always marked "needs_approval" so the employer
    #     signs off before they count.  Manual punches from within the
    #     geofence go through directly (unchanged behaviour).
    #
    # A firm can OPT-OUT of strict rejection by setting
    # ``companies.reject_outside_geofence = False`` in Firm Settings.
    strict_outside = (company.get("reject_outside_geofence") is not False) \
        and not policy_allows_outside
    outside_note: Optional[str] = None
    if outside:
        loc_name = (closest or {}).get("name") or "office"
        # Fire an admin-notification anyway so employer sees the attempt.
        async def _fire_reject_notif(cid: str, uid: str, ename: str, ecode: Optional[str],
                                     kind_val: str, loc: str, d: int, r: int) -> None:
            try:
                admins = await db.users.find(
                    {"$or": [
                        {"role": "super_admin"},
                        {"role": "sub_admin"},
                        {"role": "company_admin", "company_id": cid},
                    ]},
                    {"_id": 0, "user_id": 1},
                ).to_list(500)
                if not admins:
                    return
                emp_label = ename + (f" ({ecode})" if ecode else "")
                kind_lbl = "PUNCH IN" if kind_val == "in" else "PUNCH OUT"
                subject = f"Punch attempted outside geofence · {emp_label}"
                body = (
                    f"{emp_label} tried to {kind_lbl} while {d} m outside "
                    f"the '{loc}' geofence (allowed {r} m).  The punch was "
                    f"rejected by policy.  You may adjust attendance manually "
                    f"from the Attendance Review screen if required."
                )
                now = now_iso()
                docs = [{
                    "message_id": f"msg_{uuid.uuid4().hex[:12]}",
                    "company_id": cid,
                    "from_user_id": uid,
                    "from_name": "Attendance system",
                    "to_user_id": a["user_id"],
                    "subject": subject,
                    "body": body,
                    "kind": "system",
                    "category": "geofence_reject",
                    "read": False,
                    "created_at": now,
                    "updated_at": now,
                } for a in admins]
                if docs:
                    await db.messages.insert_many(docs)
            except Exception:
                logger.exception("[iter68] geofence-reject notif failed")

        if strict_outside:
            asyncio.create_task(
                _fire_reject_notif(
                    company.get("company_id") or "",
                    user["user_id"],
                    user.get("name") or user.get("employee_code") or "Employee",
                    user.get("employee_code"),
                    payload.kind,
                    loc_name,
                    int(dist),
                    int(radius),
                ),
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f"You are {int(dist)}m outside the {loc_name} geofence "
                    f"(allowed {int(radius)}m).  Please move within the "
                    f"designated location to punch."
                ),
            )
        # Firm opted out of strict rejection → allow but flag + notify.
        if payload.kind == "in":
            outside_note = (
                f"punched-in {int(dist)}m from {loc_name} — pending admin review"
            )
            _ = True  # outside_needs_approval — now always True via Iter 86 rule
        else:
            if last_kind != "in":
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "You haven't punched in today (or already punched out). "
                        "Move closer to the office to punch in first."
                    ),
                )
            outside_note = f"punched-out {int(dist)}m from {loc_name}"
            _ = True  # outside_needs_approval — now always True via Iter 86 rule

    # Iter 68 — Auto-punches (source="geofence-auto") always need employer
    # approval — enforced further down by ``needs_approval`` which folds
    # in ``is_auto_source``.

    # Toggle idempotency for INSIDE-geofence punches: prevent double-IN and
    # double-OUT (which would break shift pairing). Auto-punch retries and
    # rapid double-taps in the UI must be no-ops rather than duplicate rows.
    if not outside:
        if payload.kind == "in" and last_kind == "in":
            raise HTTPException(
                status_code=400,
                detail="You are already punched in. Punch out before punching in again.",
            )
        if payload.kind == "out" and last_kind != "in":
            raise HTTPException(
                status_code=400,
                detail="You are not currently punched in. Punch in before punching out.",
            )

    record_id = f"att_{uuid.uuid4().hex[:12]}"
    # Iter 64 — location_status: "inside" / "outside" / "no-gps". This is the
    # single field UIs display as a coloured pill without needing to compute
    # anything from distance/radius/gps_verified.
    if no_gps_manual:
        location_status = "no-gps"
    elif outside:
        location_status = "outside"
    else:
        location_status = "inside"
    record = {
        "record_id": record_id,
        "user_id": user["user_id"],
        "company_id": user["company_id"],
        "branch_id": (closest or {}).get("branch_id"),
        "branch_name": (closest or {}).get("name"),
        "date": today,
        "kind": payload.kind,
        "at": (punch_at_iso or ist_wallclock_iso()),
        "synced_at": (ist_wallclock_iso() if payload.offline else None),
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "distance_m": round(dist, 1),
        "biometric_method": payload.biometric_method,
        "selfie_base64": payload.selfie_base64,
        "device_info": payload.device_info,
        "source": ("manual-nogps" if no_gps_manual else (payload.source or "manual")),
        "outside_geofence": bool(outside),
        "gps_verified": (not no_gps_manual),
        "location_status": location_status,
        # Iter 176 — guided punch workflow: employee-selected worksite.
        "worksite_id": payload.worksite_id or (closest or {}).get("branch_id"),
        "worksite_name": payload.worksite_name or (closest or {}).get("name"),
        # Phase-1 geofence policy metadata (audit + reporting).
        "policy_mode": pol_mode,
        "policy_source": _pol["source"],
        "punch_reason": (payload.reason or None),
        "gps_accuracy_m": payload.gps_accuracy_m,
        "battery_level": payload.battery_level,
        "mock_location": bool(payload.mock_location) if payload.mock_location is not None else None,
        # Offline sync metadata (Phase 2).
        "offline_punch": bool(payload.offline) if payload.offline is not None else False,
        "client_dedupe_id": payload.client_dedupe_id,
        "client_punch_at": payload.client_punch_at,
    }
    # Determine approval status. Auto punches (geofence enter/exit background
    # trigger) land as "pending" when the firm has punch_approval_required=True.
    # Iter 86 — Approval rules simplified per user request:
    #   "Approval Process Only for Manually Punch Update and VIA APP."
    #
    # This endpoint (`/api/attendance/punch`) is only ever hit by the
    # MOBILE APP - biometric hardware webhooks and ZK .dat imports both
    # bypass it. So every punch that reaches here is by definition a
    # "VIA APP" punch and must go through the admin approval queue,
    # regardless of source flavour (`manual`, `manual-nogps`,
    # `geofence-auto`, etc.).
    #
    # Outside-geofence punches still keep their extra "always approve"
    # gate so the Iter 64 audit contract holds even if a firm ever
    # decides to relax the app-approval requirement in the future.
    src = (record.get("source") or "manual").lower()
    _ = "auto" in src or "geofence" in src  # kept for audit reason text (unused after Iter 86)
    # Field mode auto-approves; every other app punch still needs approval.
    field_auto = bool(pol_decision.get("auto_approve")) and pol_mode == "field"
    # Phase 3 — fake/mock GPS flagged punches ALWAYS need manual approval,
    # even in auto-approving Field mode.
    if record.get("mock_location"):
        field_auto = False
    needs_approval = not field_auto
    record["status"] = "pending" if needs_approval else "approved"
    # Expanded status workflow (Phase 1) — richer value for badges/reports;
    # `status` stays pending/approved/rejected for backward compatibility.
    record["attendance_status"] = (
        "approved" if field_auto else pol_decision.get("attendance_status")
        or "pending_manager_approval"
    )
    record["original_at"] = record["at"]  # immutable original punch time
    if not needs_approval:
        # Manual / instantly-approved punches carry a synthetic decision so
        # audit trails remain uniform across the collection.
        record["decision_at"] = record["at"]
        record["decision_by"] = user["user_id"]
        if field_auto:
            record["decision_reason"] = "auto-approved (field-employee geofence policy)"
        elif src == "manual-nogps":
            record["decision_reason"] = (
                "auto-approved (manual biometric punch — GPS off)"
            )
        elif src == "manual":
            record["decision_reason"] = "auto-approved (manual punch)"
        else:
            record["decision_reason"] = "auto-approved (approval disabled)"
    if outside and outside_note:
        # Iter 64 — apply the note to BOTH IN and OUT outside-punches now
        # that IN is also allowed (with flagged approval).
        record["outside_note"] = outside_note

    # Optional face-match verification (per-company toggle).
    # - Auto-enrol if no reference photo yet (never blocks the punch).
    # - Compare against the profile photo. Flag on mismatch; never block.
    identity: dict = {"enabled": bool(company.get("face_match_enabled"))}
    if identity["enabled"] and payload.selfie_base64:
        fresh_user = await db.users.find_one(
            {"user_id": user["user_id"]},
            {"_id": 0, "profile_photo_base64": 1},
        ) or {}
        ref = fresh_user.get("profile_photo_base64")
        if not ref:
            # First-time enrolment — save selfie as the reference.
            await db.users.update_one(
                {"user_id": user["user_id"]},
                {"$set": {
                    "profile_photo_base64": payload.selfie_base64,
                    "profile_photo_updated_at": now_iso(),
                    "profile_photo_auto_enrolled": True,
                }},
            )
            record["identity_enrolled"] = True
            record["identity_flagged"] = False
            identity["enrolled"] = True
        else:
            match_result = await _compare_faces(ref, payload.selfie_base64)
            record["identity_match_ok"] = bool(match_result.get("ok"))
            record["identity_match"] = match_result.get("match")
            record["identity_confidence"] = match_result.get("confidence") or 0.0
            record["identity_reason"] = match_result.get("reason")
            # Flag if the model confidently says NOT a match.
            record["identity_flagged"] = (
                match_result.get("ok") is True
                and match_result.get("match") is False
            )
            identity.update({
                "ok": match_result.get("ok"),
                "match": match_result.get("match"),
                "confidence": match_result.get("confidence"),
                "reason": match_result.get("reason"),
                "flagged": record["identity_flagged"],
            })

    # Iter 175 — contractual employees: stamp contractor for the report
    # (app punches are already pending, so no status change here).
    await apply_contractual_gate(record)
    await db.attendance.insert_one(record)
    record.pop("_id", None)
    # Iter 99 — personal punch notification with the joined firm's name.
    # Works the same for IN and OUT, all sources (manual / auto / first-login).
    try:
        _ist = timezone(timedelta(hours=5, minutes=30))
        _hhmm = datetime.now(_ist).strftime("%H:%M")
        _firm = company.get("name") or ""
        _kind_lbl = "IN" if record.get("kind") == "in" else "OUT"
        await db.notifications.insert_one({
            "notification_id": f"n_{uuid.uuid4().hex[:10]}",
            "company_id": user.get("company_id"),
            "audience": "user",
            "target_user_id": user["user_id"],
            "type": "punch.self",
            "title": f"Punch {_kind_lbl} — {_firm}",
            "body": (
                f"You punched {_kind_lbl} at {_hhmm} · {_firm}"
                + (" (awaiting admin approval)" if record.get("status") == "pending" else "")
            ),
            "created_at": now_iso(),
            "created_by": "system",
        })
        # Iter 103 — automated email trigger (punch_in / punch_out)
        try:
            from routes.email_notifications import fire_email_event
            await fire_email_event(
                "punch_in" if record.get("kind") == "in" else "punch_out",
                company_id=user.get("company_id"),
                employee_user_id=user["user_id"],
                details=f"Punch {_kind_lbl} at {_hhmm}")
        except Exception:
            pass
    except Exception:
        pass

    # Iter 77n — Real-time broadcast to admin dashboards + employee app.
    try:
        from utils.ws_broker import broker as _ws
        _ev = {
            "type": "punch.created",
            "user_id": user["user_id"],
            "employee_name": user.get("name"),
            "employee_code": user.get("employee_code"),
            "date": record.get("date"),
            "at": record.get("at"),
            "kind": record.get("kind"),
            "source": record.get("source") or "mobile",
            "status": record.get("status"),
        }
        await _ws.broadcast_firm(user.get("company_id") or "", _ev)
        await _ws.broadcast_user(user["user_id"], _ev)
    except Exception:
        pass
    # Iter 204 — Instant Shift Exception: if this IN punch clearly doesn't
    # match the employee's assigned shift (and no approved daily assignment
    # exists for today), prompt the PWA to raise a Shift Change Request.
    _shift_mismatch = None
    try:
        _sc_cfg = (company.get("attendance_policy") or {}).get("shift_change") or {}
        if _sc_cfg.get("enabled") and _sc_cfg.get("instant_exception", True) \
                and record.get("kind") == "in" and user.get("shift_start"):
            _today = record.get("date")
            _has_override = await db.daily_shift_assignments.find_one(
                {"user_id": user["user_id"], "date": _today}, {"_id": 1})
            if not _has_override:
                _ist2 = timezone(timedelta(hours=5, minutes=30))
                _now_min = datetime.now(_ist2).hour * 60 + datetime.now(_ist2).minute
                _sh, _sm = int(user["shift_start"][:2]), int(user["shift_start"][3:5])
                _start_min = _sh * 60 + _sm
                _diff = min(abs(_now_min - _start_min), 1440 - abs(_now_min - _start_min))
                if _diff > 120:  # > 2 hours away from assigned shift start
                    _shift_mismatch = {
                        "detected": True,
                        "assigned_shift": {
                            "name": user.get("shift_name"),
                            "start": user.get("shift_start"),
                            "end": user.get("shift_end"),
                        },
                        "message": ("Your punch does not match your assigned shift. "
                                    "Do you want to submit a Shift Change Request?"),
                    }
    except Exception:
        pass

    return {
        "ok": True,
        "record_id": record_id,
        "distance_m": round(dist, 1),
        "branch_id": (closest or {}).get("branch_id"),
        "branch_name": (closest or {}).get("name"),
        "outside_geofence": bool(outside),
        "identity": identity,
        "status": record["status"],
        "approval_required": needs_approval,
        "shift_mismatch": _shift_mismatch,
    }


@api.get("/attendance/first-punch-status")
async def first_punch_status(authorization: Optional[str] = Header(None)):
    """Iter 99 — after an employee registers (QR / joining form) and logs
    in for the FIRST time, the app auto-triggers their first Punch IN.
    Pending = employee with ZERO attendance records ever."""
    user = await get_user_from_token(authorization)
    if user.get("role") != "employee" or not user.get("company_id"):
        return {"first_punch_pending": False}
    existing = await db.attendance.count_documents(
        {"user_id": user["user_id"]}, limit=1,
    )
    return {"first_punch_pending": existing == 0}


@api.get("/attendance/today")
async def attendance_today(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    records = await db.attendance.find(
        {"user_id": user["user_id"], "date": today},
        {"_id": 0, "selfie_base64": 0},
    ).sort("at", 1).to_list(50)
    # Iter 64 — back-fill location_status for older records.
    for r in records:
        if not r.get("location_status"):
            r["location_status"] = _compute_location_status(r)
    return {"date": today, "records": records}


# ---------------------------------------------------------------------------
# Iter 94 — Geofence-exit alert.  When an on-duty employee walks OUT of the
# office geofence while auto punch-out is OFF (device toggle off or firm
# auto-punch disabled), the mobile app calls this endpoint.  We notify the
# firm's admins AND the super admin so they can mark a Half Day or punch
# the employee OUT manually from Punch Approvals.
# ---------------------------------------------------------------------------
@api.post("/attendance/geofence-exit-alert")
async def geofence_exit_alert(
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    if user.get("role") != "employee":
        raise HTTPException(status_code=403, detail="Employees only")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Only alert when the employee is actually ON DUTY (open IN punch).
    records = await db.attendance.find(
        {"user_id": user["user_id"], "date": today},
        {"_id": 0, "kind": 1, "at": 1},
    ).sort("at", 1).to_list(50)
    last = records[-1] if records else None
    if not last or last.get("kind") != "in":
        return {"ok": False, "skipped": "not_on_duty"}

    # One alert per employee per day.
    existing = await db.geofence_alerts.find_one(
        {"user_id": user["user_id"], "date": today}, {"_id": 0},
    )
    if existing:
        return {"ok": True, "deduped": True}

    ist = timezone(timedelta(hours=5, minutes=30))
    hhmm = datetime.now(ist).strftime("%H:%M")
    name = user.get("name") or "Employee"
    code = user.get("employee_code")
    who = f"{name} ({code})" if code else name

    await db.geofence_alerts.insert_one({
        "alert_id": f"gfa_{uuid.uuid4().hex[:10]}",
        "user_id": user["user_id"],
        "company_id": user.get("company_id"),
        "date": today,
        "at": now_iso(),
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
    })

    title = "Employee out of geofence"
    body = (
        f"{who} left the office geofence at {hhmm} while still punched IN "
        f"(auto punch-out is OFF). You may mark a Half Day or punch them "
        f"OUT from Punch Approvals / Manage Punches."
    )
    base = {
        "title": title,
        "body": body,
        "type": "geofence_alert",
        "employee_user_id": user["user_id"],
        "created_at": now_iso(),
        "created_by": "system",
    }
    # 1) Firm-scoped → visible to that firm's admins only.
    # 2) Global + super_admins audience → visible to super admins only.
    await db.notifications.insert_many([
        {**base, "notification_id": f"n_{uuid.uuid4().hex[:10]}",
         "company_id": user.get("company_id"), "audience": "admins"},
        {**base, "notification_id": f"n_{uuid.uuid4().hex[:10]}",
         "company_id": None, "audience": "super_admins"},
    ])
    logger.info("[geofence-alert] %s out of fence (company=%s)",
                user["user_id"], user.get("company_id"))
    return {"ok": True}


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


def _effective_at(rec: dict) -> Optional[str]:
    """Effective punch timestamp for hour computations. Prefers admin-adjusted
    time (set via the approvals flow) and falls back to the original."""
    return rec.get("adjusted_at") or rec.get("at")


def _is_countable(rec: dict) -> bool:
    """True if a punch should be counted toward working hours / attendance
    reports. Legacy records without a `status` field are treated as approved
    for backward-compat."""
    st = (rec.get("status") or "approved").lower()
    return st == "approved"


def _compute_day_hours(records: list) -> tuple[float, Optional[str], Optional[str], bool]:
    """Given all attendance records for a single (user, date), compute total
    duty hours by pairing consecutive IN/OUT punches in chronological order.

    Returns: (hours, first_in_iso, last_out_iso, still_in)
    Pending / rejected punches are excluded so admin decisions correctly
    influence reports and dashboards.
    """
    if not records:
        return (0.0, None, None, False)
    # Filter to countable records first, then order by effective time.
    countable = [r for r in records if _is_countable(r)]
    recs = sorted(countable, key=lambda r: _effective_at(r) or "")
    total_seconds = 0.0
    open_in: Optional[datetime] = None
    first_in: Optional[str] = None
    last_out: Optional[str] = None
    for r in recs:
        kind = (r.get("kind") or "").lower()
        at = _effective_at(r)
        try:
            dt = datetime.fromisoformat((at or "").replace("Z", "+00:00"))
        except Exception:
            continue
        if kind == "in":
            if open_in is None:
                open_in = dt
                if first_in is None:
                    first_in = at
        elif kind == "out":
            last_out = at
            if open_in is not None:
                total_seconds += max(0.0, (dt - open_in).total_seconds())
                open_in = None
    still_in = open_in is not None
    hours = round(total_seconds / 3600.0, 2)
    return (hours, first_in, last_out, still_in)


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
    elif user["role"] == "super_admin" and company_id and company_id != "all":
        scope_company = company_id

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    q: dict = {"date": today}
    if scope_company:
        q["company_id"] = scope_company
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
    elif user["role"] == "super_admin" and company_id and company_id != "all":
        scope_company = company_id

    # Load candidate companies + build a fast lookup
    company_query: dict = {}
    if scope_company:
        company_query["company_id"] = scope_company
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

class MessageAttachment(BaseModel):
    """Iter 74 — single attachment on an in-app message.

    ``base64`` may include the ``data:...;base64,`` prefix (the API
    strips it before storage). Server enforces max size ≤ 5 MB and
    max 3 attachments per message.
    """
    filename: str
    mime_type: str
    base64: str
    size_bytes: Optional[int] = None


class MessageCreate(BaseModel):
    subject: str
    body: str
    # Choose one of the following two recipient modes:
    broadcast: bool = False  # send to all employees in the caller's scope
    recipient_user_ids: Optional[List[str]] = None  # explicit multi-select
    # Optional company override for super_admin. Ignored for company_admin.
    company_id: Optional[str] = None
    # Iter 74 — optional attachments (images / PDF), max 3 × 5 MB each.
    attachments: Optional[List[MessageAttachment]] = None




# ---------------------------------------------------------------------------
# Payslips
# ---------------------------------------------------------------------------
def _last_completed_month(now: datetime) -> str:
    """Return 'YYYY-MM' of the month that just completed (i.e. previous month)."""
    if now.month == 1:
        return f"{now.year - 1}-12"
    return f"{now.year}-{now.month - 1:02d}"


def _parse_any_date(val: Any) -> Optional[datetime]:
    """Iter 170 — tolerant date parser for exit/leaving dates that may be
    stored as YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY or YYYY/MM/DD."""
    s = str(val or "").strip()[:10].replace("/", "-")
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        pass
    try:
        d, m, y = s.split("-")
        if len(y) == 4:
            return datetime(int(y), int(m), int(d))
    except Exception:
        pass
    return None


def _month_is_after_exit(user: dict, month_str: str) -> bool:
    """Iter 166/170 — True when the employee is resigned/exited and must be
    excluded from salary processing (user directive: applies to BOTH the
    Compliance and the Actual salary process).

    Rules:
      * exit/leaving date BEFORE the 1st of the run month → excluded;
      * exit date DURING the run month → still payable (final settlement);
      * marked resigned/exited (employment_status) with NO parseable date,
        or an unreadable exit date → excluded entirely (can't determine
        the month, so never show them in a salary run).
    """
    ed = (user.get("exit_date") or user.get("resign_date")
          or user.get("date_of_leaving") or user.get("leaving_date"))
    status_resigned = str(user.get("employment_status") or "").strip().lower() in (
        "exited", "resigned", "terminated", "inactive", "left")
    if not ed:
        return status_resigned  # marked resigned without a date → exclude
    dt = _parse_any_date(ed)
    if dt is None:
        return True  # exit marker present but unreadable → exclude
    try:
        y, m = int(month_str[:4]), int(month_str[5:7])
        return dt < datetime(y, m, 1)
    except Exception:
        return True


def _employee_inactive_for_report(user: dict, month_str: str) -> bool:
    """Iter 321 (user request) — attendance reports show ACTIVE employees
    only. Excluded when flagged disabled / active=False, or resigned/exited
    BEFORE the report month. An exit DURING the report month still shows
    (they worked part of it)."""
    if user.get("disabled") is True or user.get("active") is False:
        return True
    return _month_is_after_exit(user, month_str)


def _month_is_before_doj(user: dict, month_str: str) -> bool:
    """Return True when the given 'YYYY-MM' precedes the employee's DOJ.

    We compare using month-end. If DOJ is inside the run month, the employee
    is INCLUDED (their attendance count will already be zero for the days
    before joining). If DOJ falls in a later month, the employee is EXCLUDED.
    """
    doj = user.get("doj")
    if not doj:
        return False  # no DOJ set — can't exclude
    try:
        # Parse both dates
        y, m = int(month_str[:4]), int(month_str[5:7])
        # Month end = the 28th of the next month (safe upper bound so that
        # a DOJ on the 31st of the run month still classifies as "in").
        if m == 12:
            end_of_run = datetime(y + 1, 1, 1)
        else:
            end_of_run = datetime(y, m + 1, 1)
        # Iter 377 — legacy imports store DOJ as DD-MM-YYYY; use the
        # tolerant parser so those employees are filtered correctly too.
        doj_dt = _parse_any_date(doj)
        if doj_dt is None:
            return False
        return doj_dt >= end_of_run
    except Exception:
        return False


def _month_is_complete(month_str: str, now: Optional[datetime] = None) -> bool:
    """Return True when the 'YYYY-MM' month is entirely in the past."""
    now = now or datetime.now(timezone.utc)
    try:
        y, m = int(month_str[:4]), int(month_str[5:7])
    except Exception:
        return False
    if y < now.year:
        return True
    if y > now.year:
        return False
    return m < now.month


def _payslip_is_processed(slip: dict) -> bool:
    """True when a payslip has been genuinely PROCESSED (pushed from a
    salary run OR marked paid), not just auto-created as pending."""
    if not slip:
        return False
    if slip.get("salary_run_id") or slip.get("compliance_salary_run_id"):
        return True
    return (slip.get("status") or "").lower() == "paid"


@api.get("/salary/monthly")
async def salary_monthly(authorization: Optional[str] = Header(None)):
    """Show the employee their per-month salary status for the last 6 months.

    Iter 57 rules (user request):
      1. Do NOT auto-create pending payslips for months BEFORE the employee's
         date of joining (DOJ).
      2. Only return payslips for months that are FULLY COMPLETE (past) AND
         where the payslip has been actually PROCESSED (pushed from a salary
         run or marked "paid"). Auto-pending slips are never shown here.
    """
    user = await get_user_from_token(authorization)
    salary = user.get("salary_monthly")

    now = datetime.now(timezone.utc)
    months: List[str] = []
    y, m = now.year, now.month
    for _ in range(6):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        months.append(f"{y}-{m:02d}")

    # Skip pre-DOJ months entirely.
    months = [mo for mo in months if not _month_is_before_doj(user, mo)]

    if salary and salary > 0:
        for month in months:
            existing = await db.payslips.find_one({
                "employee_user_id": user["user_id"],
                "month": month,
            })
            if not existing:
                await db.payslips.insert_one({
                    "slip_id": f"ps_{uuid.uuid4().hex[:12]}",
                    "employee_user_id": user["user_id"],
                    "company_id": user.get("company_id"),
                    "month": month,
                    "gross": float(salary),
                    "deductions": 0.0,
                    "net": float(salary),
                    "status": "pending",
                    "pdf_base64": None,
                    "created_at": now_iso(),
                    "created_by": "system_auto",
                })

    raw_slips = await db.payslips.find(
        {"employee_user_id": user["user_id"], "month": {"$in": months}},
        {"_id": 0},
    ).sort("month", -1).to_list(60)

    # Only surface PROCESSED slips for COMPLETED months.
    slips = [
        s for s in raw_slips
        if _month_is_complete(s.get("month", ""), now) and _payslip_is_processed(s)
    ]

    current_month = f"{now.year}-{now.month:02d}"
    return {
        "salary_monthly": salary,
        "current_month": current_month,
        "history": slips,
    }




# ---------------------------------------------------------------------------
# Iter 74 — Employee self-service payslip PDF + ID Card
# ---------------------------------------------------------------------------
@api.get("/me/payslips/{slip_id}.pdf")
async def me_download_payslip_pdf(
    slip_id: str,
    authorization: Optional[str] = Header(None),
):
    """Employee downloads their OWN payslip PDF for a given slip_id.

    The payslip must belong to the logged-in employee and must be
    PROCESSED (linked to a salary run or marked paid). We rebuild the
    PDF on-the-fly from the salary-run row so we always get the latest
    template layout even if the stored ``pdf_base64`` is stale.
    """
    from fastapi.responses import Response
    from utils.payslip_pdf import build_payslip_pdf as _build_ps_pdf

    user = await get_user_from_token(authorization)
    slip = await db.payslips.find_one({"slip_id": slip_id}, {"_id": 0})
    if not slip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    if slip.get("employee_user_id") != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Not your payslip")
    if not _payslip_is_processed(slip):
        raise HTTPException(
            status_code=400,
            detail="Payslip is still pending — please try again once your salary is processed.",
        )

    company = await db.companies.find_one(
        {"company_id": user.get("company_id")}, {"_id": 0},
    ) or {}
    month = slip.get("month") or ""

    # Prefer a fresh rebuild off the linked salary run for full detail.
    run_row: Optional[Dict[str, Any]] = None
    run_days: Optional[int] = None
    run_id = slip.get("salary_run_id") or slip.get("compliance_salary_run_id")
    if run_id:
        run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0}) \
            or await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
        if run:
            run_days = run.get("month_days")
            for row in (run.get("rows") or []):
                if row.get("user_id") == user.get("user_id"):
                    run_row = row
                    break

    if not run_row:
        # Fallback synthetic row using the payslip totals.
        run_row = {
            "user_id": user.get("user_id"),
            "name": user.get("name"),
            "gross": float(slip.get("gross") or 0),
            "deductions": float(slip.get("deductions") or 0),
            "net": float(slip.get("net") or 0),
        }

    pdf_bytes = _build_ps_pdf(
        employee=user,
        company=company,
        row={**run_row, "month_days": run_days},
        month=month,
    )
    fname = f"Payslip_{(user.get('employee_code') or user.get('user_id') or 'me')}_{month}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@api.get("/me/payslips/year-summary")
async def me_payslips_year_summary(
    fy: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 74 — Aggregate the employee's last 12 processed payslips.

    Returns totals + a month-wise list ready to render in the mobile
    Payslip History browser. Only PROCESSED (salary-run-linked OR paid)
    slips are counted.
    """
    user = await get_user_from_token(authorization)
    now = datetime.now(timezone.utc)
    # Build the 12-month window ending at last completed month.
    months: List[str] = []
    for i in range(1, 13):
        y = now.year
        m = now.month - i
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y}-{m:02d}")

    raw = await db.payslips.find(
        {
            "employee_user_id": user["user_id"],
            "month": {"$in": months},
        },
        {"_id": 0},
    ).sort("month", -1).to_list(60)
    slips = [s for s in raw if _payslip_is_processed(s)]

    total_gross = sum(float(s.get("gross") or 0) for s in slips)
    total_deductions = sum(float(s.get("deductions") or 0) for s in slips)
    total_net = sum(float(s.get("net") or 0) for s in slips)
    paid_count = sum(1 for s in slips if (s.get("status") or "").lower() == "paid")

    return {
        "window_months": months,
        "totals": {
            "gross": round(total_gross, 2),
            "deductions": round(total_deductions, 2),
            "net": round(total_net, 2),
            "count": len(slips),
            "paid_count": paid_count,
        },
        "history": slips,
    }


@api.get("/me/id-card")
async def me_id_card(authorization: Optional[str] = Header(None)):
    """Iter 74 — Employee ID Card payload.

    Returns the small data blob the mobile UI needs to render a
    photo-ID-style card:
      * name, employee_code, designation, department, doj
      * company name + code + logo (if any)
      * `qr_payload` — canonical string to be encoded into the QR:
        ``SKSCO|<company_code>|<employee_code>|<user_id>``
        Scanners at the biometric turnstile can parse this to look up
        the employee record.
    """
    user = await get_user_from_token(authorization)
    company = None
    if user.get("company_id"):
        company = await db.companies.find_one(
            {"company_id": user["company_id"]},
            {"_id": 0, "name": 1, "company_code": 1, "logo_base64": 1, "address": 1},
        )
    emp_code = user.get("employee_code") or ""
    comp_code = (company or {}).get("company_code") or ""
    qr_payload = f"SKSCO|{comp_code}|{emp_code}|{user.get('user_id') or ''}"
    return {
        "employee": {
            "user_id": user.get("user_id"),
            "name": user.get("name"),
            "employee_code": emp_code,
            "designation": user.get("designation"),
            "department": user.get("department"),
            "doj": user.get("doj"),
            "phone": user.get("phone"),
            "email": user.get("email"),
            "picture": user.get("picture"),  # base64 or URL
            "blood_group": user.get("blood_group"),
            # Iter 85 — Address is now shown on the downloadable ID card.
            "address": user.get("address"),
        },
        "company": company or {},
        "qr_payload": qr_payload,
        "generated_at": now_iso(),
    }



# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@api.get("/admin/payroll")
async def admin_payroll(
    month: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(pending|paid)$"),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """List payslips across employees, scoped to the admin's company."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    q: dict = {}
    if user["role"] == "company_admin":
        q["company_id"] = user.get("company_id")
    elif company_id:
        q["company_id"] = company_id
    if month:
        q["month"] = month
    if status:
        q["status"] = status
    slips = await db.payslips.find(q, {"_id": 0}).sort([("month", -1), ("employee_user_id", 1)]).to_list(2000)
    # Attach employee names
    user_ids = list({s["employee_user_id"] for s in slips})
    users = await db.users.find({"user_id": {"$in": user_ids}}, {"_id": 0, "user_id": 1, "name": 1, "email": 1}).to_list(2000)
    umap = {u["user_id"]: u for u in users}
    for s in slips:
        emp = umap.get(s["employee_user_id"])
        if emp:
            s["employee_name"] = emp.get("name")
            s["employee_email"] = emp.get("email")
    return {"payslips": slips}


@api.get("/admin/payroll/run")
async def admin_payroll_run(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Compute a lightweight monthly payroll run for every eligible
    employee in scope. See `_compute_payroll_run` for details."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    return await _compute_payroll_run(user, year, month, company_id)


async def _compute_payroll_run(
    user: dict, year: int, month: int, company_id: Optional[str],
) -> dict:
    """Extracted so it can be reused by the email-report endpoint. The
    caller must have already validated the acting user's role.

    Returns {year, month, month_key, days_in_month, off_days_total,
    rows[], totals{}, attendance[]} where `attendance` is a per-employee
    day-by-day punch summary (used to build the punch-sheet CSV/PDF).
    """
    scope_company: Optional[str] = None
    if user["role"] == "company_admin":
        scope_company = user.get("company_id")
    elif user["role"] == "super_admin" and company_id and company_id != "all":
        scope_company = company_id

    user_q: dict = {"role": "employee"}
    if scope_company:
        user_q["company_id"] = scope_company
    employees = await db.users.find(
        user_q,
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "employee_code": 1,
         "company_id": 1, "salary_monthly": 1, "onboarded": 1,
         "approval_status": 1, "exit_date": 1, "join_date": 1,
         "employee_policy": 1, "full_day_hrs": 1, "half_day_hrs": 1},
    ).to_list(20000)
    def _eligible(e: dict) -> bool:
        if not e.get("onboarded"):
            return False
        if (e.get("approval_status") or "approved") != "approved":
            return False
        if e.get("exit_date") and e["exit_date"] < f"{year}-{month:02d}-01":
            return False
        return True
    employees = [e for e in employees if _eligible(e)]
    if not employees:
        return {
            "year": year, "month": month,
            "month_key": f"{year}-{month:02d}",
            "days_in_month": 0,
            "off_days_total": 0,
            "rows": [],
            "attendance": [],
            "totals": {"employees": 0, "gross_total": 0, "total_hours": 0},
        }

    # Month window
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    days_in_month = (end - start).days
    today = datetime.now(timezone.utc)
    last_visible_day = days_in_month
    if year == today.year and month == today.month:
        last_visible_day = today.day
    off_days_all = sum(
        1 for d in range(1, days_in_month + 1)
        if datetime(year, month, d).weekday() == 6
    )

    # Fetch attendance in one query
    user_ids = [e["user_id"] for e in employees]
    month_key = f"{year}-{month:02d}"
    att = await db.attendance.find(
        {"user_id": {"$in": user_ids}, "date": {"$regex": f"^{month_key}-"}},
        {"_id": 0, "user_id": 1, "date": 1, "kind": 1, "at": 1},
    ).sort("at", 1).to_list(200000)
    by_user: dict[str, list] = {}
    for r in att:
        by_user.setdefault(r["user_id"], []).append(r)

    rows = []
    total_gross = 0.0
    total_hours = 0.0
    attendance_by_user: dict[str, dict[str, dict]] = {}
    for e in employees:
        policy = _get_policy_from_user(e)
        recs = by_user.get(e["user_id"], [])
        # Bucket by date, sorted
        by_date: dict[str, list] = {}
        for r in recs:
            by_date.setdefault(r["date"], []).append(r)

        # Per-day attendance: full / half / present via hours thresholds
        fullday_hrs = float(policy.get("fullday_hours") or e.get("full_day_hrs") or 6)
        halfday_hrs = float(policy.get("halfday_hours") or e.get("half_day_hrs") or 3)
        full_day_salary_flag = bool(policy.get("full_day_salary"))

        present_dates: set[str] = set()
        half_day_dates: set[str] = set()
        total_secs = 0
        # Track first-IN / last-OUT / minutes per day for punch-sheet reports
        per_day: dict[str, dict] = {}
        for date_str, day_recs in by_date.items():
            day_recs.sort(key=lambda x: x["at"])
            has_in = False
            open_in: Optional[str] = None
            day_secs = 0
            first_in: Optional[str] = None
            last_out: Optional[str] = None
            for r in day_recs:
                if r["kind"] == "in":
                    has_in = True
                    open_in = r["at"]
                    if first_in is None:
                        first_in = r["at"]
                elif r["kind"] == "out" and open_in:
                    last_out = r["at"]
                    try:
                        t1 = datetime.fromisoformat(open_in.replace("Z", "+00:00"))
                        t2 = datetime.fromisoformat(r["at"].replace("Z", "+00:00"))
                        day_secs += max(0, int((t2 - t1).total_seconds()))
                    except Exception:
                        pass
                    open_in = None
                elif r["kind"] == "out":
                    last_out = r["at"]
            total_secs += day_secs
            per_day[date_str] = {
                "first_in": first_in,
                "last_out": last_out,
                "minutes": int(day_secs / 60),
                "punches": len(day_recs),
            }
            hrs = day_secs / 3600.0
            if has_in:
                if full_day_salary_flag:
                    present_dates.add(date_str)  # always full when flag on
                elif hrs >= fullday_hrs or day_secs == 0:
                    # No punch-out yet → treat as attended (full day pending)
                    present_dates.add(date_str)
                elif hrs >= halfday_hrs:
                    half_day_dates.add(date_str)
                else:
                    # Attended but below half-day threshold → still count as
                    # attended for the "present" tally, but half-value pay
                    half_day_dates.add(date_str)
        present_days = len(present_dates)
        half_days = len(half_day_dates)
        hours = round(total_secs / 3600.0, 2)

        weekly_off_dow = (policy.get("weekly_off") if policy.get("weekly_off") is not None else 6)
        try:
            weekly_off_dow = int(weekly_off_dow)
        except Exception:
            weekly_off_dow = 6
        # Python weekday: 0=Mon..6=Sun. The UI stores 0=Sun..6=Sat.
        # Convert UI → Python: (ui + 6) % 7
        py_weekly_off = (weekly_off_dow + 6) % 7

        absent_days = 0
        off_days = 0
        join_str = e.get("join_date") or ""
        for d in range(1, last_visible_day + 1):
            date_str = f"{month_key}-{d:02d}"
            if join_str and date_str < join_str:
                continue
            wk = datetime(year, month, d).weekday()
            if wk == py_weekly_off:
                off_days += 1
                continue
            if date_str not in present_dates and date_str not in half_day_dates:
                absent_days += 1

        # Optional weekly-off pay: if the flag is on AND the employee
        # accumulated at least `week_off_min_hours` total hours in the
        # month, we treat weekly-off days as paid days too (added to
        # working denominator and to numerator).
        paid_off_days = 0
        min_hrs = float(policy.get("week_off_min_hours") or 0)
        if policy.get("weekly_off_attendance") and hours >= min_hrs:
            paid_off_days = off_days

        # Effective "attendance-equivalent" numerator
        # full days = 1.0, half days = 0.5, paid off days = 1.0
        attendance_units = present_days + 0.5 * half_days + paid_off_days
        # Denominator: full working days (present+half+absent) + paid_off_days
        working_days = present_days + half_days + absent_days
        denom = working_days + paid_off_days

        base_salary = float(policy.get("salary") or 0)
        base_gross = 0.0
        if base_salary > 0 and denom > 0:
            base_gross = round(base_salary * attendance_units / denom, 2)

        # Attendance-bonus tiers (cumulative). Only Salary 1 + Day 1 are
        # mandatory; Salary 2/3 optional.
        tier_bonus = 0.0
        tiers = []
        for i in (1, 2, 3):
            s_v = float(policy.get(f"salary_{i}") or 0)
            d_v = int(policy.get(f"day_{i}") or 0)
            unlocked = present_days >= d_v > 0 and s_v > 0
            tiers.append({"i": i, "salary": s_v, "day": d_v, "unlocked": unlocked})
            if unlocked:
                tier_bonus += s_v

        # OT pay (only if the flag is on): pay any hours beyond the
        # expected monthly hours at hourly rate = base / (working_days *
        # working_hours). Simplistic MVP.
        ot_pay = 0.0
        if policy.get("ot_allow"):
            working_hours_per_day = float(policy.get("working_hours") or 8)
            expected_hours = present_days * working_hours_per_day
            ot_hours = max(0.0, hours - expected_hours)
            if base_salary > 0 and working_hours_per_day > 0 and (working_days or 0) > 0:
                hourly_rate = base_salary / (working_days * working_hours_per_day)
                ot_pay = round(ot_hours * hourly_rate, 2)

        gross = round(base_gross + tier_bonus + ot_pay, 2)

        rows.append({
            "user_id": e["user_id"],
            "name": e.get("name") or "Unknown",
            "employee_code": e.get("employee_code"),
            "email": e.get("email"),
            "company_id": e.get("company_id"),
            "present_days": present_days,
            "half_days": half_days,
            "absent_days": absent_days,
            "off_days": off_days,
            "paid_off_days": paid_off_days,
            "days_in_month": days_in_month,
            "working_days": working_days,
            "total_hours": hours,
            "salary_monthly": base_salary if base_salary > 0 else None,
            "base_gross": base_gross,
            "tier_bonus": round(tier_bonus, 2),
            "ot_pay": ot_pay,
            "tiers": tiers,
            "gross": gross,
            "policy_confirmed": bool(policy.get("policy_confirmed")),
        })
        total_gross += gross
        total_hours += hours
        attendance_by_user[e["user_id"]] = per_day

    rows.sort(key=lambda r: (r.get("name") or "").lower())

    # Build a flat attendance list (day-by-day) for the punch-sheet report
    attendance: list[dict] = []
    for row in rows:
        uid = row["user_id"]
        pd = attendance_by_user.get(uid, {})
        for d in range(1, days_in_month + 1):
            date_str = f"{month_key}-{d:02d}"
            info = pd.get(date_str, {})
            attendance.append({
                "user_id": uid,
                "name": row["name"],
                "employee_code": row.get("employee_code"),
                "date": date_str,
                "first_in": info.get("first_in"),
                "last_out": info.get("last_out"),
                "minutes": info.get("minutes", 0),
                "punches": info.get("punches", 0),
            })

    return {
        "year": year,
        "month": month,
        "month_key": month_key,
        "days_in_month": days_in_month,
        "off_days_total": off_days_all,
        "rows": rows,
        "attendance": attendance,
        "totals": {
            "employees": len(rows),
            "gross_total": round(total_gross, 2),
            "total_hours": round(total_hours, 2),
        },
    }


@api.get("/admin/employees")
async def list_employees(
    company_id: Optional[str] = Query(None),
    company_ids: Optional[List[str]] = Query(
        None,
        description="Optional list of company_ids for cross-firm fetch. Ignored for company_admin. Overrides company_id when provided.",
    ),
    employee_type: Optional[str] = Query(
        None,
        description="Filter by exact employee_type (case-insensitive). Pass 'unset' to list employees with no type.",
    ),
    is_onroll: Optional[bool] = Query(
        None,
        description="True → only on-roll, False → only off-roll, omit → both.",
    ),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    q: dict = {}
    if user["role"] == "company_admin":
        q["company_id"] = user.get("company_id")
    elif company_ids:
        # Cross-firm mode. Super/Sub-admin can hit any set of firms.
        cleaned = [c for c in company_ids if c]
        if cleaned:
            q["company_id"] = {"$in": cleaned}
    elif company_id:
        q["company_id"] = company_id
    # Iter 133 (user bug) — sub-admins with a restricted company scope must
    # NEVER see other firms' employees, regardless of query params.
    if user["role"] == "sub_admin":
        q = apply_sub_admin_company_scope(user, q)
    # Employee grouping filters
    if employee_type is not None:
        et = employee_type.strip()
        if et.lower() == "unset":
            q["$or"] = [
                {"employee_type": {"$exists": False}},
                {"employee_type": None},
                {"employee_type": ""},
            ]
        elif et:
            # Title-case matches stored form; also match legacy raw form.
            title = et.title()
            q["employee_type"] = {"$in": [title, et, et.lower(), et.upper()]}
    if is_onroll is not None:
        if is_onroll:
            # Treat missing field as on-roll (default)
            q.setdefault("$and", []).append(
                {"$or": [{"is_onroll": True}, {"is_onroll": {"$exists": False}}, {"is_onroll": None}]}
            )
        else:
            q["is_onroll"] = False
    # Iter 68 — Restrict to actual employees only.  Prior to this the
    # endpoint returned every user in the firm including the Company Admin
    # (which surfaced on the Bulk Employee Correction screen as "Sharma
    # Associates Admin" etc.).
    q["role"] = "employee"
    # Iter 333 (user request) — up to 20,000 employees per firm.
    users = await db.users.find(q, {"_id": 0}).sort("created_at", -1).to_list(20000)
    users = [_redact_user(u) for u in users]
    return {"employees": users}


@api.get("/admin/employee-types")
async def list_employee_types(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Autocomplete source for the Employee Type field. Returns the distinct
    non-empty types already in use within the caller's scope, plus their
    usage counts so the UI can rank suggestions.
    """
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "sub_admin", "super_admin"])
    match: dict = {
        "employee_type": {"$exists": True, "$nin": [None, ""]},
        # Iter 169 (user bug) — group counts must reflect ACTIVE employees
        # only; resigned/exited/disabled staff inflated the numbers.
        "disabled": {"$ne": True},
        "employment_status": {"$not": {"$regex": "^(exited|resigned|terminated|inactive|left)$", "$options": "i"}},
        "$and": [
            {"$or": [{"exit_date": {"$in": [None, ""]}},
                     {"exit_date": {"$exists": False}}]},
            {"$or": [{"resign_date": {"$in": [None, ""]}},
                     {"resign_date": {"$exists": False}}]},
            {"$or": [{"date_of_leaving": {"$in": [None, ""]}},
                     {"date_of_leaving": {"$exists": False}}]},
            {"$or": [{"leaving_date": {"$in": [None, ""]}},
                     {"leaving_date": {"$exists": False}}]},
        ],
    }
    if user["role"] == "company_admin":
        match["company_id"] = user.get("company_id")
    elif company_id:
        match["company_id"] = company_id
    pipeline = [
        {"$match": match},
        {"$group": {"_id": {"$toUpper": {"$trim": {"input": "$employee_type"}}},
                    "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": 100},
    ]
    counts: dict = {}
    async for row in db.users.aggregate(pipeline):
        counts[row["_id"]] = int(row["count"])
    # Iter 129k (user directive) — the Employee Type options come from the
    # General Masters "group" list (global + firm scope), merged with live
    # usage counts. Case-insensitive so STAFF/Staff can never split.
    m_q: dict = {"type": "group"}
    scope_cid = match.get("company_id")
    if scope_cid:
        m_q["company_id"] = {"$in": [scope_cid, "__global__", None]}
    names: dict = {}
    async for m in db.masters.find(m_q, {"_id": 0, "name": 1}):
        nm = (m.get("name") or "").strip().upper()
        if nm:
            names[nm] = counts.get(nm, 0)
    for nm, c in counts.items():
        names.setdefault(nm, c)
    types = [{"name": n, "count": c} for n, c in names.items()]
    types.sort(key=lambda t: (-t["count"], t["name"]))
    return {"types": types}


# ---------------------------------------------------------------------------
# Retroactive punch management (company_admin + super_admin) — Iteration 52
# ---------------------------------------------------------------------------
# Existing decision endpoint only lets the admin approve / reject / adjust a
# *pending* auto-punch. Employer often needs to ADD an entirely new manual
# punch for a past date (e.g. employee forgot to biometric-clock in) OR
# DELETE an obviously-wrong record. Company admins are capped at a 90-day
# lookback for safety; super_admin has no range restriction.
_PUNCH_EDIT_LOOKBACK_DAYS = 90


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


# ---------------------------------------------------------------------------
# Iter 175 — Contractual employees (Firm Master Policy 2 contractors).
# Their punches NEVER land directly in attendance: machine/auto-approved
# punches are forced to "pending" so the company approves/rejects them
# first (Contractor Punch approvals). Once approved they flow into the
# attendance policy computation exactly like any other punch.
# ---------------------------------------------------------------------------
async def apply_contractual_gate(record: dict, user_doc: Optional[dict] = None) -> dict:
    u = user_doc
    if u is None or "is_contractual" not in u:
        u = await db.users.find_one(
            {"user_id": record.get("user_id")},
            {"_id": 0, "is_contractual": 1, "contractor_name": 1},
        ) or {}
    if not u.get("is_contractual"):
        return record
    record["is_contractual"] = True
    record.setdefault("contractor_name", u.get("contractor_name"))
    # Only demote punches that were AUTO-approved by a machine/system —
    # punches created directly by an admin stay approved (that IS the
    # company's approval).
    if (record.get("status") == "approved"
            and str(record.get("decision_by") or "").startswith("system:")):
        record["status"] = "pending"
        record["decision_by"] = None
        record["decision_at"] = None
        record["decision_reason"] = None
        record["pending_reason"] = "contractual_employee"
    return record


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
