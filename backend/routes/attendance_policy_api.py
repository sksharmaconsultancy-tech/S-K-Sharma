"""Iter 397 — ATTENDANCE POLICY API module (extracted from server.py).

Refactor only: policy saved-list / presets / get / patch / reset and the
textile compute-day probe were MOVED verbatim from server.py. Helpers
stay in server.py because the punch/grid engines also use them."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    BUSINESS_CATEGORIES,
    _BUSINESS_CATEGORY_MAP,
    _WEEKDAY_LABELS,
    _get_own_company,
    _is_shift_open,
    _policy_for_category,
    _validate_policy,
    apply_employee_policy_override,
    apply_resolved_shift_to_policy,
    compute_textile_day,
    db,
    get_user_from_token,
    load_daily_shift_overrides,
    load_shift_masters_map,
    now_iso,
    require_role,
    resolve_shift_for_user,
    sub_admin_can_touch_company,
)

router = APIRouter(prefix="/api")
api = router


@api.get("/attendance/policy/saved-list")
async def attendance_policy_saved_list(
    authorization: Optional[str] = Header(None),
):
    """Iter 200 (user request) — firms that already have a saved attendance
    policy, shown at the bottom of the Policy Master screen."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    q: Dict[str, Any] = {"attendance_policy": {"$ne": None}}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    out = []
    async for c in db.companies.find(
        q, {"_id": 0, "company_id": 1, "name": 1,
            "attendance_policy.policy_variant": 1,
            "attendance_policy.full_day_hours": 1,
            "attendance_policy.updated_at": 1,
            "attendance_policy.report_settings.default_view": 1},
    ).sort("name", 1):
        ap = c.get("attendance_policy") or {}
        if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, c["company_id"]):
            continue
        out.append({
            "company_id": c["company_id"],
            "name": c.get("name"),
            "policy_variant": ap.get("policy_variant"),
            "full_day_hours": ap.get("full_day_hours"),
            "default_report": (ap.get("report_settings") or {}).get("default_view"),
            "updated_at": ap.get("updated_at"),
        })
    return {"firms": out}


@api.get("/attendance/policy/presets")
async def list_attendance_policy_presets(
    authorization: Optional[str] = Header(None),
):
    """Available policy presets per business type. Company admins use this to
    pick / reset to a preset from the Attendance Policy screen."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "company_admin", "sub_admin"])
    # Enrich with the human label taken from BUSINESS_CATEGORIES
    # Iter 200 (user directive) — Textile Policy 1/2 & the Hospital preset
    # are RETIRED from the picker: all attendance policy is now managed
    # dynamically from this screen. (Engine support for firms already saved
    # on those variants is unchanged.)
    presets: List[dict] = []
    for cat in BUSINESS_CATEGORIES:
        key = cat["key"]
        if key == "hospital":
            continue
        presets.append({
            "business_category": key,
            "label": cat["label"],
            "policy": _policy_for_category(key),
        })
    return {
        "weekday_labels": _WEEKDAY_LABELS,
        "presets": presets,
    }


@api.get("/attendance/policy")
async def get_attendance_policy(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Returns the effective attendance policy for the caller's company (or a
    specific `company_id` when called by a super admin). If the company has
    no policy on file yet, the preset for its business type is returned so
    the UI always has something to display."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    if user["role"] in ("super_admin", "sub_admin"):
        if not company_id:
            raise HTTPException(status_code=400, detail="Please pass ?company_id=")
        if user["role"] == "sub_admin" and not sub_admin_can_touch_company(user, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
        company = await db.companies.find_one({"company_id": company_id}, {"_id": 0})
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
    else:
        company = await _get_own_company(user)
    policy = company.get("attendance_policy") or _policy_for_category(
        company.get("business_category"), company.get("business_subcategory")
    )
    # `punch_approval_required` lives on the company doc (not the policy blob)
    # because it gates the punch endpoint. We surface it alongside the policy
    # so the Attendance Policy screen can render a single unified form.
    policy = dict(policy)  # avoid mutating cached preset
    policy["punch_approval_required"] = bool(company.get("punch_approval_required", True))
    # Iter 96 — normalise legacy policy shape to the modern keys the UI (and
    # other consumers) read, so nobody crashes on undefined numeric fields.
    _wd = policy.get("workday_hours")
    policy.setdefault("grace_minutes_late", policy.get("grace_minutes", 10))
    policy.setdefault("full_day_hours", _wd if _wd is not None else 8)
    policy.setdefault("half_day_hours", 4)
    policy.setdefault("break_hours", 0)
    policy.setdefault("overtime_threshold_hours", _wd if _wd is not None else 8)
    policy.setdefault("overtime_multiplier", 1)
    policy.setdefault("standard_working_hours", _wd if _wd is not None else 8)
    policy.setdefault("duty_hours_rounding_minutes", 0)
    policy.setdefault("week_off_min_working_hours", 0)
    policy.setdefault("weekly_off_days", [])
    policy.setdefault("shifts", [])
    # Iter 200 — Report Settings default: every report enabled, In/Out first.
    _rs = policy.get("report_settings") if isinstance(policy.get("report_settings"), dict) else {}
    _rs_en = _rs.get("enabled") if isinstance(_rs.get("enabled"), dict) else {}
    policy["report_settings"] = {
        "enabled": {k: bool(_rs_en.get(k, True))
                    for k in ("inout", "ot", "hours", "salary", "inout_salary")},
        "default_view": _rs.get("default_view") or "inout",
    }
    policy.setdefault("salary_allowed", "both")
    policy.setdefault("weekoff_rotation_basis", False)
    # Iter 200/201 — backfill new Policy Master sub-point flags for firms
    # whose policy was saved before these options existed.
    _pm_bf = policy.get("policy_master")
    if isinstance(_pm_bf, dict):
        for _k in ("attendance_by_duty_hours", "weekoff_present_add_ot",
                   "holiday_present_add_ot", "compliance_present_8hr",
                   "halfday_threshold_rule"):
            _pm_bf.setdefault(_k, False)
        # Iter 270 — OT Include in Existing Compliance Salary defaults to
        # YES (current behaviour) for firms saved before the option existed.
        _pm_bf.setdefault("compliance_ot_include", True)
        # Iter 289 — per-firm OT slab (30-min default).
        _pm_bf.setdefault("ot_slab_minutes", 30)
    # Iter 581 — Employee Onboarding Gate backfill for firms whose policy
    # was saved before the gate existed (safe defaults, gate OFF).
    _og = policy.get("onboarding_gate") if isinstance(policy.get("onboarding_gate"), dict) else {}
    policy["onboarding_gate"] = {
        "enabled": bool(_og.get("enabled")),
        "require_aadhaar": bool(_og.get("require_aadhaar", True)),
        "require_bank": bool(_og.get("require_bank", True)),
        "require_pan": bool(_og.get("require_pan", False)),
        "require_photo": bool(_og.get("require_photo", True)),
        "permission_days": int(_og.get("permission_days", 7) or 0),
        "auto_release": bool(_og.get("auto_release", True)),
        "enabled_at": _og.get("enabled_at"),
    }
    # "Default preset" here means: no admin has explicitly saved / overridden
    # the policy yet. Because we auto-attach a preset on company creation,
    # the presence of `attendance_policy` alone isn't a good signal — we
    # instead look for the touch-timestamp that PATCH/reset sets.
    is_default = company.get("attendance_policy_updated_at") is None
    return {
        "company_id": company["company_id"],
        "business_category": company.get("business_category"),
        "business_subcategory": company.get("business_subcategory"),
        "weekday_labels": _WEEKDAY_LABELS,
        "policy": policy,
        "is_default_preset": is_default,
    }


@api.patch("/attendance/policy")
async def update_attendance_policy(
    payload: dict = Body(...),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Update the attendance policy for the caller's company (or a specified
    `company_id` when called by a super admin)."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    if user["role"] in ("super_admin", "sub_admin"):
        if not company_id:
            raise HTTPException(status_code=400, detail="Please pass ?company_id=")
        if user["role"] == "sub_admin" and not sub_admin_can_touch_company(user, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    else:
        company_id = user.get("company_id")
        if not company_id:
            raise HTTPException(status_code=400, detail="You are not linked to any company")
    # Support both { policy: {...} } and a flat body containing the fields.
    raw_policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else payload
    # Extract the company-level `punch_approval_required` toggle before
    # validating the policy blob (validator would otherwise reject it as an
    # unknown key on the shift/hours schema).
    approval_flag = raw_policy.pop("punch_approval_required", None) if isinstance(raw_policy, dict) else None
    # Iter 104 — support PARTIAL updates (e.g. Firm Master's Policy 1/2
    # picker sends only {policy_variant}). Merge the incoming fields onto
    # the firm's existing policy (or its category preset) before validating.
    if isinstance(raw_policy, dict):
        co = await db.companies.find_one(
            {"company_id": company_id},
            {"_id": 0, "attendance_policy": 1, "business_category": 1, "business_subcategory": 1})
        if not co:
            raise HTTPException(status_code=404, detail="Company not found")
        base = co.get("attendance_policy") or {}
        preset = _policy_for_category(
            co.get("business_category"), co.get("business_subcategory")) or {}
        # Legacy firms may hold an old-schema policy without `shifts` —
        # backfill missing required fields from the category preset.
        merged = {**preset, **{k: v for k, v in base.items() if v not in (None, "", [])}, **raw_policy}
        raw_policy = merged
    clean = _validate_policy(raw_policy)
    updates: dict = {
        "attendance_policy": clean,
        "attendance_policy_updated_at": now_iso(),
        "attendance_policy_updated_by": user["user_id"],
    }
    if approval_flag is not None:
        updates["punch_approval_required"] = bool(approval_flag)
    r = await db.companies.update_one(
        {"company_id": company_id},
        {"$set": updates},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    # Return the full policy blob (including the toggle) so the client can
    # rehydrate its form without an extra GET.
    resp_policy = dict(clean)
    if approval_flag is not None:
        resp_policy["punch_approval_required"] = bool(approval_flag)
    else:
        # Include current value from DB for consistency
        cur = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "punch_approval_required": 1})
        resp_policy["punch_approval_required"] = bool((cur or {}).get("punch_approval_required", True))
    return {"ok": True, "policy": resp_policy}


@api.post("/attendance/policy/reset")
async def reset_attendance_policy(
    payload: dict = Body(default={}),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Reset the company's attendance policy to a preset. If `business_category`
    is passed in the body, that preset is used; otherwise falls back to the
    company's own business_category preset."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    if user["role"] in ("super_admin", "sub_admin"):
        if not company_id:
            raise HTTPException(status_code=400, detail="Please pass ?company_id=")
        if user["role"] == "sub_admin" and not sub_admin_can_touch_company(user, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    else:
        company_id = user.get("company_id")
        if not company_id:
            raise HTTPException(status_code=400, detail="You are not linked to any company")
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    override_cat = (payload or {}).get("business_category")
    if override_cat and override_cat not in _BUSINESS_CATEGORY_MAP:
        raise HTTPException(status_code=400, detail="Unknown business category")
    preset_key = override_cat or company.get("business_category")
    preset = _policy_for_category(preset_key)
    await db.companies.update_one(
        {"company_id": company_id},
        {"$set": {
            "attendance_policy": preset,
            "attendance_policy_updated_at": now_iso(),
            "attendance_policy_updated_by": user["user_id"],
        }},
    )
    return {"ok": True, "policy": preset, "reset_to": preset_key or "other"}


@api.get("/attendance/textile/compute-day")
async def attendance_textile_compute_day(
    date: str = Query(..., description="YYYY-MM-DD"),
    user_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Compute a single day's textile duty summary for one employee.

    Returns duty hours, present days (0 / 0.5 / 1), OT minutes and whether
    week-off / holiday transformations kicked in. Admin-only.

    Args:
        date: The calendar date in YYYY-MM-DD (UTC).
        user_id: Employee to compute for. Company admins are scoped to
            their own company; super admins may pass any user_id.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Employee not in your company")
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    company = None
    if emp.get("company_id"):
        company = await db.companies.find_one(
            {"company_id": emp["company_id"]}, {"_id": 0}
        )
    policy = (company or {}).get("attendance_policy") or _policy_for_category(
        (company or {}).get("business_category")
    )
    punches = await db.attendance.find(
        {"user_id": user_id, "date": date},
        {"_id": 0, "kind": 1, "at": 1},
    ).sort("at", 1).to_list(500)
    # Iter 77c — Honour per-employee shift override (manual or auto-by-first-punch)
    shifts_by_id, shifts_list = await load_shift_masters_map()
    # Iter 204 — approved daily shift assignment wins.
    _dso = await load_daily_shift_overrides(emp.get("company_id") or "", date, date)
    resolved_shift = _dso.get((user_id, date)) or resolve_shift_for_user(
        emp, punches, shifts_by_id, shifts_list,
        firm_shift_open=_is_shift_open(policy))
    policy = apply_resolved_shift_to_policy(policy, resolved_shift)
    policy = apply_employee_policy_override(policy, emp)
    summary = compute_textile_day(punches, policy, emp, d.weekday())
    return {
        "user_id": user_id,
        "date": date,
        "policy_variant": policy.get("policy_variant"),
        "resolved_shift": {
            "shift_id": (resolved_shift or {}).get("shift_id"),
            "name": (resolved_shift or {}).get("name"),
            "start": (resolved_shift or {}).get("start"),
            "end": (resolved_shift or {}).get("end"),
        } if resolved_shift else None,
        "punch_count": len(punches),
        **summary,
    }


# ---------------------------------------------------------------------------
# Company registration requests (from prospective client firms)
# ---------------------------------------------------------------------------
