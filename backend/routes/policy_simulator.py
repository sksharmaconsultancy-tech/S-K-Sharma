"""Iter 290 — Attendance Policy SIMULATOR (user request).

Lets an admin preview how the CURRENT (possibly unsaved) policy settings
would compute a sample day: Worked → Duty / OT / Present credit.

Mirrors the grid-compute day rules:
  * duty_hours_rounding_minutes (same _round_minutes semantics)
  * "Count Present Day @ 8 HRS" sub-point (standard forced to 8)
  * Half-Day Threshold Rule
  * per-firm OT slab (0 / 30 / 60 minutes, floor)
  * policy_2 / default present crediting
"""
from fastapi import APIRouter, Body, Header, HTTPException

from server import get_user_from_token, _round_minutes  # noqa: E402

router = APIRouter(prefix="/api")


def _hhmm_to_min(s: str) -> int:
    try:
        h, m = str(s).strip().split(":")
        return int(h) * 60 + int(m)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Bad time '{s}' — use HH:MM")


@router.post("/admin/attendance-policy/simulate")
async def simulate_policy_day(
    payload: dict = Body(...),
    authorization: str = Header(None),
):
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")

    pol = payload.get("policy") or {}
    pm = pol.get("policy_master") or {}
    in_min = _hhmm_to_min(payload.get("in_time") or "09:00")
    out_min = _hhmm_to_min(payload.get("out_time") or "17:00")
    if out_min <= in_min:            # cross-midnight shift
        out_min += 24 * 60

    worked_min = out_min - in_min
    step = int(pol.get("duty_hours_rounding_minutes") or 0)
    worked_min = _round_minutes(worked_min, step)
    worked = round(worked_min / 60.0, 4)

    full_h = float(pol.get("full_day_hours") or 8.0)
    half_h = float(pol.get("half_day_hours") or 4.0)
    variant = pol.get("policy_variant") or ""
    pm8 = bool(pm.get("compliance_present_8hr"))
    halfday_rule = bool(pm.get("halfday_threshold_rule"))
    slab = pm.get("ot_slab_minutes")
    slab = int(slab) if slab in (0, 30, 60, "0", "30", "60") else 30

    standard_h = 8.0 if pm8 else full_h

    # Duty / OT split at the standard.
    duty = min(worked, standard_h)
    ot = max(0.0, worked - standard_h)
    if not pol.get("ot_allowed", True):
        ot = 0.0
    if ot > 0 and slab:
        ot = (int(round(ot * 60)) // int(slab)) * int(slab) / 60.0

    # Present credit — same precedence as the grid compute.
    notes = []
    if pm8:
        if worked >= 8.0:
            present = 1.0
        elif halfday_rule:
            present = 0.5 if worked >= half_h else 0.0
            notes.append("Half-Day Threshold Rule decided the credit")
        elif worked >= half_h:
            present = 0.5
        elif worked > 0:
            present = 0.0
        else:
            present = 0.0
        notes.insert(0, "8-HR sub-point active: 8+ worked hrs = 1 Present Day")
    elif halfday_rule and worked > 0:
        if worked >= standard_h:
            present = 1.0
        elif worked >= half_h:
            present = 0.5
            duty, ot = half_h, max(0.0, worked - half_h)
            if ot > 0 and slab:
                ot = (int(round(ot * 60)) // int(slab)) * int(slab) / 60.0
            notes.append("Half-Day Threshold Rule: ½ day, remainder → OT")
        else:
            present, duty, ot = 0.0, 0.0, worked
            if slab:
                ot = (int(round(ot * 60)) // int(slab)) * int(slab) / 60.0
            notes.append("Under half-day threshold: 0 present, hours → OT")
    elif variant == "policy_2":
        if worked >= standard_h:
            present = 1.0
        else:
            present, duty, ot = 0.0, 0.0, worked
            if slab:
                ot = (int(round(ot * 60)) // int(slab)) * int(slab) / 60.0
            notes.append("Policy 2: under standard hrs → 0 present, ALL hours → OT")
    else:
        present = 1.0 if worked >= full_h else (0.5 if worked >= half_h else 0.0)

    return {
        "worked_hours": worked,
        "duty_hours": round(duty, 2),
        "ot_hours": round(ot, 2),
        "present": present,
        "standard_hours": standard_h,
        "ot_slab_minutes": slab,
        "notes": notes,
    }
