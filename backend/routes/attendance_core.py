"""Iter 398/399 — ATTENDANCE CORE (employee-facing) module.

MOVED verbatim from server.py (Iter 398), then split (Iter 399):
this file keeps the employee-facing engine — worksites, punch
(geofence + face match + onboarding gate + contractual gate),
first-punch-status, today, geofence-exit alert, pending punches +
decisions, history + selfie, my-month and summary.
Admin endpoints live in routes/attendance_admin_core.py, payroll
endpoints in routes/payroll_core.py, pure date helpers in
shared/dates.py."""
import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from pydantic import BaseModel

from server import (  # noqa: E402
    IST_TZ,
    AttendancePunch,
    _compare_faces,
    _compute_monthly_grid_data,
    _resolve_geofence,
    apply_employee_policy_override,
    db,
    get_user_from_token,
    ist_wallclock_iso,
    ist_wallclock_now,
    logger,
    now_iso,
    require_role,
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


