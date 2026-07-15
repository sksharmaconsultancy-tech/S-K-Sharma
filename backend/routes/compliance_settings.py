"""Standard Compliance Settings — GLOBAL statutory configuration.

Iter 127f (user request): one "Standard Compliance Settings" screen whose
values apply to EVERY firm's Compliance Salary Process (PF/ESIC rates,
ceilings, wage-base floor and whole-rupee rounding rules). Per-run
`statutory_cfg` overrides still win on top of these.

Stored as a singleton doc in ``db.app_settings`` with key
``standard_compliance``.
"""
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
    require_role(admin, ["super_admin"])

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


async def get_standard_compliance_cfg() -> Dict[str, Any]:
    """Effective global statutory cfg = defaults overridden by the saved doc.
    Imported by server.py when computing compliance runs."""
    doc = await db.app_settings.find_one(_KEY, {"_id": 0}) or {}
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
    return {
        "settings": await get_standard_compliance_cfg(),
        "defaults": DEFAULT_STATUTORY_CFG,
        "updated_at": doc.get("updated_at"),
        "updated_by_name": doc.get("updated_by_name"),
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

    upd["updated_at"] = now_iso()
    upd["updated_by"] = admin["user_id"]
    upd["updated_by_name"] = admin.get("name") or admin.get("email") or ""
    await db.app_settings.update_one(_KEY, {"$set": upd, "$setOnInsert": _KEY}, upsert=True)
    return {"ok": True, "settings": await get_standard_compliance_cfg()}
