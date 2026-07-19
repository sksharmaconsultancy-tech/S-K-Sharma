"""Geofence Attendance Policy — Master, resolver & punch evaluator (Phase 1).

Adds a configurable, multi-level geofence policy on top of the existing
attendance engine WITHOUT changing existing behaviour when a firm keeps
the default (Strict) mode.

Five modes (spec):
  * strict     — outside geofence not allowed.
  * flexible   — allowed outside; stores reason/distance/selfie; Pending
                 Manager Approval.
  * field      — no geofence restriction; auto-approved. For sales /
                 service / field / collection staff.
  * remote     — allowed only from Home / approved remote location.
  * emergency  — allowed anywhere; mandatory selfie + reason + approval.

Assignment levels (most-specific wins):
  employee > site/worksite > branch > contractor > category > company default

Assignments live in ``geo_policy_assignments``; the company default lives
on the company doc (``geo_policy_default`` / ``geo_policy_settings``).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import db, get_user_from_token, require_role, now_iso, logger

router = APIRouter(prefix="/api", tags=["geo-policy"])

MODES = ["strict", "flexible", "field", "remote", "emergency"]

MODE_CATALOGUE = [
    {"mode": "strict", "label": "Strict",
     "desc": "Attendance outside the geofence is not allowed.",
     "color": "#DC2626"},
    {"mode": "flexible", "label": "Flexible",
     "desc": "Allowed outside; captures reason, distance & selfie. Pending manager approval.",
     "color": "#D97706"},
    {"mode": "field", "label": "Field Employee",
     "desc": "No geofence restriction; auto-approved. For sales/service/field/collection staff.",
     "color": "#059669"},
    {"mode": "remote", "label": "Remote Work",
     "desc": "Allowed only from Home or an approved remote location.",
     "color": "#2563EB"},
    {"mode": "emergency", "label": "Emergency",
     "desc": "Allowed anywhere; mandatory selfie + reason + manager approval.",
     "color": "#7C3AED"},
]

_DEFAULT_SETTINGS = {
    "radius_m": None,               # override site radius (None = use site's own)
    "grace_distance_m": 0,          # extra metres tolerated beyond the radius
    "grace_time_min": 0,
    "mandatory_selfie": False,
    "gps_accuracy_threshold_m": 0,  # 0 = no check
    "face_verification_required": False,
    "working_hours": {"start": "", "end": ""},
    # Remote mode: approved locations [{name,lat,lng,radius_m}]
    "approved_locations": [],
}

_FIELD_HINTS = ("sales", "field", "service engineer", "service eng",
                "collection", "delivery", "driver", "marketing", "site engineer")


def _merge_settings(s: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(_DEFAULT_SETTINGS)
    out["working_hours"] = dict(_DEFAULT_SETTINGS["working_hours"])
    out["approved_locations"] = list(_DEFAULT_SETTINGS["approved_locations"])
    if isinstance(s, dict):
        for k, v in s.items():
            if k in out and v is not None:
                out[k] = v
    return out


def _looks_field(user: Dict[str, Any]) -> bool:
    blob = " ".join(str(user.get(k) or "") for k in
                    ("designation", "position", "employee_type", "category")).lower()
    return any(h in blob for h in _FIELD_HINTS)


async def resolve_geo_policy(user: Dict[str, Any], company: Dict[str, Any]) -> Dict[str, Any]:
    """Return {mode, settings, source} for a user, most-specific-first."""
    company_id = company.get("company_id")
    assigns = await db.geo_policy_assignments.find(
        {"company_id": company_id, "active": {"$ne": False}}, {"_id": 0},
    ).to_list(2000)

    def pick(scope: str, *values: Optional[str]) -> Optional[Dict[str, Any]]:
        vals = {str(v).strip().lower() for v in values if v}
        for a in assigns:
            if a.get("scope") == scope and str(a.get("scope_value") or "").strip().lower() in vals:
                return a
        return None

    # 1. Employee-level (per-employee toggle / override)
    a = pick("employee", user.get("user_id"), user.get("employee_code"))
    # 2. Site / worksite
    a = a or pick("site", user.get("worksite_id"), user.get("branch_id"), user.get("branch_name"))
    # 3. Branch
    a = a or pick("branch", user.get("branch_id"), user.get("branch_name"))
    # 4. Contractor
    a = a or pick("contractor", user.get("contractor_name"))
    # 5. Category / employee type
    a = a or pick("category", user.get("employee_type"), user.get("category"))
    if a:
        return {"mode": a.get("mode") or "strict",
                "settings": _merge_settings(a.get("settings")),
                "source": f"{a.get('scope')}:{a.get('scope_value')}"}

    # 6. Derived Field-staff (designation heuristic / explicit toggle)
    if user.get("is_field_staff") is True or _looks_field(user):
        return {"mode": "field", "settings": _merge_settings(None),
                "source": "derived:field-staff"}

    # 7. Company default
    return {"mode": company.get("geo_policy_default") or "strict",
            "settings": _merge_settings(company.get("geo_policy_settings")),
            "source": "company-default"}


def _in_any_location(lat: float, lng: float, locs: List[Dict[str, Any]]) -> bool:
    from server import haversine_m
    for loc in locs or []:
        try:
            d = haversine_m(lat, lng, float(loc["lat"]), float(loc["lng"]))
            if d <= float(loc.get("radius_m") or 200):
                return True
        except Exception:
            continue
    return False


def evaluate_geo_punch(
    mode: str, settings: Dict[str, Any], *,
    outside: bool, dist: float, radius: float,
    lat: Optional[float], lng: Optional[float],
    has_selfie: bool, reason: Optional[str], is_live_in: bool,
) -> Dict[str, Any]:
    """Return a punch decision for the resolved mode.

    Keys: allow(bool), reject_reason(str|None), attendance_status(str),
    auto_approve(bool), require_reason(bool).
    """
    if is_live_in:
        return {"allow": True, "reject_reason": None,
                "attendance_status": "approved", "auto_approve": False,
                "require_reason": False}

    grace = float(settings.get("grace_distance_m") or 0)
    eff_outside = outside and (dist > (radius + grace))

    if mode == "field":
        return {"allow": True, "reject_reason": None,
                "attendance_status": "approved", "auto_approve": True,
                "require_reason": False}

    if mode == "emergency":
        if not has_selfie:
            return {"allow": False,
                    "reject_reason": "Emergency punch requires a selfie.",
                    "attendance_status": "rejected", "auto_approve": False,
                    "require_reason": False}
        if not (reason and reason.strip()):
            return {"allow": False,
                    "reject_reason": "Emergency punch requires a reason.",
                    "attendance_status": "rejected", "auto_approve": False,
                    "require_reason": True}
        return {"allow": True, "reject_reason": None,
                "attendance_status": "pending_manager_approval",
                "auto_approve": False, "require_reason": False}

    if mode == "remote":
        locs = settings.get("approved_locations") or []
        inside_remote = (lat is not None and lng is not None
                         and _in_any_location(lat, lng, locs))
        if inside_remote or not eff_outside:
            return {"allow": True, "reject_reason": None,
                    "attendance_status": "pending_manager_approval",
                    "auto_approve": False, "require_reason": False}
        return {"allow": False,
                "reject_reason": "Attendance is allowed only from your approved remote location.",
                "attendance_status": "rejected", "auto_approve": False,
                "require_reason": False}

    if mode == "flexible":
        if not eff_outside:
            return {"allow": True, "reject_reason": None,
                    "attendance_status": "pending_manager_approval",
                    "auto_approve": False, "require_reason": False}
        if not (reason and reason.strip()):
            return {"allow": False,
                    "reject_reason": "You are outside the work location — please enter a reason.",
                    "attendance_status": "rejected", "auto_approve": False,
                    "require_reason": True}
        return {"allow": True, "reject_reason": None,
                "attendance_status": "pending_manager_approval",
                "auto_approve": False, "require_reason": False}

    # strict (default)
    if eff_outside:
        return {"allow": False,
                "reject_reason": "You are outside the permitted work location.",
                "attendance_status": "rejected", "auto_approve": False,
                "require_reason": False}
    return {"allow": True, "reject_reason": None,
            "attendance_status": "pending_manager_approval",
            "auto_approve": False, "require_reason": False}


# ---------------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------------
async def _guard(authorization: Optional[str], company_id: Optional[str]) -> Dict[str, Any]:
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if admin["role"] == "sub_admin" and company_id:
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    admin["_resolved_company_id"] = company_id
    return admin


@router.get("/admin/geo-policy/modes")
async def geo_policy_modes(authorization: Optional[str] = Header(None)):
    await get_user_from_token(authorization)
    return {"modes": MODE_CATALOGUE, "default_settings": _DEFAULT_SETTINGS}


@router.get("/admin/geo-policy")
async def get_geo_policy(company_id: Optional[str] = None,
                         authorization: Optional[str] = Header(None)):
    admin = await _guard(authorization, company_id)
    cid = admin["_resolved_company_id"]
    company = await db.companies.find_one({"company_id": cid},
                                          {"_id": 0, "geo_policy_default": 1,
                                           "geo_policy_settings": 1}) or {}
    assigns = await db.geo_policy_assignments.find(
        {"company_id": cid}, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return {
        "company_id": cid,
        "default_mode": company.get("geo_policy_default") or "strict",
        "default_settings": _merge_settings(company.get("geo_policy_settings")),
        "assignments": assigns,
        "modes": MODE_CATALOGUE,
    }


@router.put("/admin/geo-policy/default")
async def set_geo_policy_default(payload: Dict[str, Any] = Body(...),
                                 authorization: Optional[str] = Header(None)):
    admin = await _guard(authorization, payload.get("company_id"))
    mode = (payload.get("mode") or "strict").lower()
    if mode not in MODES:
        raise HTTPException(status_code=400, detail="Invalid mode")
    await db.companies.update_one(
        {"company_id": admin["_resolved_company_id"]},
        {"$set": {"geo_policy_default": mode,
                  "geo_policy_settings": _merge_settings(payload.get("settings")),
                  "geo_policy_updated_at": now_iso(),
                  "geo_policy_updated_by": admin["user_id"]}},
    )
    logger.info("[geo-policy] default=%s company=%s by=%s",
                mode, admin["_resolved_company_id"], admin["user_id"])
    return {"ok": True, "default_mode": mode}


@router.post("/admin/geo-policy/assignments")
async def create_assignment(payload: Dict[str, Any] = Body(...),
                            authorization: Optional[str] = Header(None)):
    admin = await _guard(authorization, payload.get("company_id"))
    scope = (payload.get("scope") or "").lower()
    if scope not in ("branch", "site", "contractor", "category", "employee"):
        raise HTTPException(status_code=400, detail="Invalid scope")
    mode = (payload.get("mode") or "").lower()
    if mode not in MODES:
        raise HTTPException(status_code=400, detail="Invalid mode")
    scope_value = str(payload.get("scope_value") or "").strip()
    if not scope_value:
        raise HTTPException(status_code=400, detail="scope_value is required")
    import uuid
    doc = {
        "assignment_id": f"gpa_{uuid.uuid4().hex[:12]}",
        "company_id": admin["_resolved_company_id"],
        "scope": scope,
        "scope_value": scope_value,
        "scope_label": payload.get("scope_label") or scope_value,
        "mode": mode,
        "settings": _merge_settings(payload.get("settings")),
        "active": True,
        "created_at": now_iso(),
        "created_by": admin["user_id"],
    }
    await db.geo_policy_assignments.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "assignment": doc}


@router.put("/admin/geo-policy/assignments/{assignment_id}")
async def update_assignment(assignment_id: str, payload: Dict[str, Any] = Body(...),
                            authorization: Optional[str] = Header(None)):
    admin = await _guard(authorization, payload.get("company_id"))
    existing = await db.geo_policy_assignments.find_one(
        {"assignment_id": assignment_id, "company_id": admin["_resolved_company_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Assignment not found")
    updates: Dict[str, Any] = {"updated_at": now_iso(), "updated_by": admin["user_id"]}
    if "mode" in payload:
        m = (payload["mode"] or "").lower()
        if m not in MODES:
            raise HTTPException(status_code=400, detail="Invalid mode")
        updates["mode"] = m
    if "settings" in payload:
        updates["settings"] = _merge_settings(payload["settings"])
    if "active" in payload:
        updates["active"] = bool(payload["active"])
    if "scope_label" in payload:
        updates["scope_label"] = payload["scope_label"]
    await db.geo_policy_assignments.update_one(
        {"assignment_id": assignment_id}, {"$set": updates})
    return {"ok": True}


@router.delete("/admin/geo-policy/assignments/{assignment_id}")
async def delete_assignment(assignment_id: str, company_id: Optional[str] = None,
                            authorization: Optional[str] = Header(None)):
    admin = await _guard(authorization, company_id)
    res = await db.geo_policy_assignments.delete_one(
        {"assignment_id": assignment_id, "company_id": admin["_resolved_company_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return {"ok": True}


@router.get("/attendance/my-geo-policy")
async def my_geo_policy(authorization: Optional[str] = Header(None)):
    """Employee endpoint — the resolved policy for the current user, so the
    app can show the right mode + capture requirements."""
    user = await get_user_from_token(authorization)
    company = await db.companies.find_one({"company_id": user.get("company_id")},
                                          {"_id": 0}) or {}
    res = await resolve_geo_policy(user, company)
    cat = next((m for m in MODE_CATALOGUE if m["mode"] == res["mode"]), MODE_CATALOGUE[0])
    return {"mode": res["mode"], "label": cat["label"], "color": cat["color"],
            "desc": cat["desc"], "settings": res["settings"], "source": res["source"],
            # Firm Master switch — the PWA enables offline punching only when True.
            "offline_punch_enabled": bool(company.get("offline_geofence_enabled"))}
