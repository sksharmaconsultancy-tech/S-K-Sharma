"""Standard Compliance Settings — GLOBAL statutory configuration.

Iter 127f (user request): one "Standard Compliance Settings" screen whose
values apply to EVERY firm's Compliance Salary Process (PF/ESIC rates,
ceilings, wage-base floor and whole-rupee rounding rules). Per-run
`statutory_cfg` overrides still win on top of these.

Stored as a singleton doc in ``db.app_settings`` with key
``standard_compliance``.
"""
import re
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
)
from utils.compliance_salary import DEFAULT_STATUTORY_CFG, _ROUNDING_KEYS

router = APIRouter(prefix="/api")

_KEY = {"key": "standard_compliance"}

_NUMERIC_FIELDS = (
    "pf_percent_employee", "pf_percent_employer_epf", "pf_percent_employer_eps",
    "pf_wage_cap", "esic_percent_employee", "esic_percent_employer",
    "esic_gross_threshold", "stat_wage_floor_pct",
    # Iter 160 — EPF Act employer charge accounts
    "pf_admin_percent", "pf_edli_percent", "pf_edli_admin_percent",
)
_ROUND_MODES = ("nearest", "ceil", "floor", "none")


async def get_firm_statutory_overrides(company_id: Optional[str]) -> Dict[str, Any]:
    """Iter 127g — firm-specific statutory overrides saved on the Firm
    Master (``firm_masters.statutory_overrides``). Only explicitly saved
    keys are returned so they layer cleanly on the global standard."""
    if not company_id:
        return {}
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "statutory_overrides": 1})
    raw = (fm or {}).get("statutory_overrides") or {}
    out: Dict[str, Any] = {}
    for k in _NUMERIC_FIELDS:
        if raw.get(k) is not None:
            out[k] = float(raw[k])
    for k in _ROUNDING_KEYS:
        if raw.get(k) in _ROUND_MODES:
            out[k] = raw[k]
    return out


@router.get("/admin/compliance-settings/firm/{company_id}")
async def read_firm_compliance_settings(
    company_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    overrides = await get_firm_statutory_overrides(company_id)
    std = await get_standard_compliance_cfg()
    return {
        "overrides": overrides,
        "effective": {**std, **overrides},
        "standard": std,
        "has_override": bool(overrides),
    }


@router.put("/admin/compliance-settings/firm/{company_id}")
async def save_firm_compliance_settings(
    company_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Save (or clear with {"clear": true}) firm-specific statutory
    overrides — stored on the Firm Master, applied to that firm only."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])

    if payload.get("clear"):
        await db.firm_masters.update_one(
            {"company_id": company_id},
            {"$unset": {"statutory_overrides": ""},
             "$setOnInsert": {"company_id": company_id}},
            upsert=True,
        )
        return {"ok": True, "cleared": True}

    upd: Dict[str, Any] = {}
    for k in _NUMERIC_FIELDS:
        if k in payload and payload[k] is not None:
            try:
                v = float(payload[k])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{k} must be a number")
            if v < 0:
                raise HTTPException(status_code=400, detail=f"{k} cannot be negative")
            upd[k] = v
    for k in _ROUNDING_KEYS:
        if k in payload and payload[k] in _ROUND_MODES:
            upd[k] = payload[k]
    if not upd:
        raise HTTPException(status_code=400, detail="Nothing to update")
    upd["updated_at"] = now_iso()
    upd["updated_by_name"] = admin.get("name") or admin.get("email") or ""
    await db.firm_masters.update_one(
        {"company_id": company_id},
        {"$set": {"statutory_overrides": upd},
         "$setOnInsert": {"company_id": company_id}},
        upsert=True,
    )
    return {"ok": True, "overrides": await get_firm_statutory_overrides(company_id)}


async def get_standard_compliance_cfg(on_date: Optional[str] = None) -> Dict[str, Any]:
    """Effective global statutory cfg = defaults overridden by the saved doc.
    Imported by server.py when computing compliance runs.

    Iter 160 — if ``on_date`` (YYYY-MM-DD) is given, the newest logged
    version whose ``effective_from`` <= on_date is used, so salary runs
    follow the policy that was in force for that period. Falls back to
    the current singleton when no version applies (pre-versioning data).
    """
    doc = await db.app_settings.find_one(_KEY, {"_id": 0}) or {}
    if on_date:
        ver = await db.compliance_settings_log.find_one(
            {"effective_from": {"$lte": on_date}}, {"_id": 0},
            sort=[("effective_from", -1), ("updated_at", -1)])
        if ver:
            doc = ver.get("settings") or {}
    cfg = dict(DEFAULT_STATUTORY_CFG)
    for k in _NUMERIC_FIELDS:
        if doc.get(k) is not None:
            cfg[k] = float(doc[k])
    for k in _ROUNDING_KEYS:
        if doc.get(k) in _ROUND_MODES:
            cfg[k] = doc[k]
    return cfg


@router.get("/admin/compliance-settings")
async def read_compliance_settings(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    doc = await db.app_settings.find_one(_KEY, {"_id": 0}) or {}
    log = await db.compliance_settings_log.find(
        {}, {"_id": 0}).sort(
        [("effective_from", -1), ("updated_at", -1)]).to_list(50)
    return {
        "settings": await get_standard_compliance_cfg(),
        "defaults": DEFAULT_STATUTORY_CFG,
        "updated_at": doc.get("updated_at"),
        "updated_by_name": doc.get("updated_by_name"),
        "effective_from": doc.get("effective_from"),
        "log": log,
    }


@router.put("/admin/compliance-settings")
async def save_compliance_settings(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])  # global — Super Admin only

    upd: Dict[str, Any] = {}
    for k in _NUMERIC_FIELDS:
        if k in payload:
            try:
                v = float(payload[k])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{k} must be a number")
            if v < 0:
                raise HTTPException(status_code=400, detail=f"{k} cannot be negative")
            upd[k] = v
    for k in _ROUNDING_KEYS:
        if k in payload:
            if payload[k] not in _ROUND_MODES:
                raise HTTPException(status_code=400, detail=f"{k} must be one of {_ROUND_MODES}")
            upd[k] = payload[k]
    if not upd:
        raise HTTPException(status_code=400, detail="Nothing to update")

    # Iter 160 — effective date + version log.
    eff = str(payload.get("effective_from") or "").strip() or now_iso()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", eff):
        raise HTTPException(status_code=400,
                            detail="effective_from must be YYYY-MM-DD")
    upd["effective_from"] = eff
    upd["updated_at"] = now_iso()
    upd["updated_by"] = admin["user_id"]
    upd["updated_by_name"] = admin.get("name") or admin.get("email") or ""
    await db.app_settings.update_one(_KEY, {"$set": upd, "$setOnInsert": _KEY}, upsert=True)
    snapshot = await get_standard_compliance_cfg()
    await db.compliance_settings_log.insert_one({
        "log_id": f"csl_{uuid.uuid4().hex[:10]}",
        "effective_from": eff,
        "settings": snapshot,
        "updated_at": upd["updated_at"],
        "updated_by_name": upd["updated_by_name"],
    })
    return {"ok": True, "settings": snapshot}


# ------------------------------------------------------------------------
# Iter 162 — Compliance Salary Register PDF layout (columns / order /
# headings / widths / rows-per-page / row height). Saved ONE TIME here,
# applied automatically on every variant-2 register download.
_LAYOUT_KEY = {"key": "compliance_register_layout"}


@router.get("/admin/compliance-register-layout")
async def get_register_layout(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    from utils.compliance_salary import V2_REGISTER_COLUMNS
    doc = await db.app_settings.find_one(_LAYOUT_KEY, {"_id": 0}) or {}
    return {
        "layout": doc.get("layout") or None,
        "catalog": [{"key": k, "heading": h, "width": w, "numeric": n}
                    for k, h, w, n in V2_REGISTER_COLUMNS],
        "updated_at": doc.get("updated_at"),
        "updated_by_name": doc.get("updated_by_name"),
    }


@router.put("/admin/compliance-register-layout")
async def put_register_layout(payload: Dict[str, Any] = Body(...),
                              authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])  # user directive: super admin ONLY
    from utils.compliance_salary import V2_REGISTER_COLUMNS
    valid = {k for k, _h, _w, _n in V2_REGISTER_COLUMNS}
    cols_in = payload.get("columns") or []
    cols = []
    for c in cols_in:
        if not isinstance(c, dict) or c.get("key") not in valid:
            continue
        item: Dict[str, Any] = {"key": c["key"]}
        if str(c.get("heading") or "").strip():
            item["heading"] = str(c["heading"]).strip()[:40]
        try:
            w = float(c.get("width") or 0)
            if w > 0:
                item["width"] = max(4.0, min(80.0, w))
        except Exception:
            pass
        cols.append(item)
    if not cols:
        raise HTTPException(status_code=400, detail="Select at least one column")
    layout: Dict[str, Any] = {"columns": cols}
    try:
        pp = int(payload.get("per_page") or 10)
        layout["per_page"] = max(1, min(50, pp))
    except Exception:
        layout["per_page"] = 10
    try:
        rh = float(payload.get("row_height") or 0)
        if rh > 0:
            layout["row_height"] = max(3.0, min(30.0, rh))
    except Exception:
        pass
    await db.app_settings.update_one(
        _LAYOUT_KEY,
        {"$set": {"layout": layout, "updated_at": now_iso(),
                  "updated_by_name": admin.get("name") or admin.get("email") or ""},
         "$setOnInsert": _LAYOUT_KEY}, upsert=True)
    return {"ok": True, "layout": layout}


@router.delete("/admin/compliance-register-layout")
async def reset_register_layout(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])  # user directive: super admin ONLY
    await db.app_settings.delete_one(_LAYOUT_KEY)
    return {"ok": True}
