"""Iter 479 — Contractor Master (CLRA / Labour Code Phase 1).

Full contractor records replacing the free-text ``contractor_name`` on
employees: licence, PAN/GSTIN, EPF/ESIC codes, security deposit, labour
limits, agreement window and status. Names already present in
``firm_masters.contractors`` (legacy simple list) are auto-seeded on the
first list call so nothing the user typed is lost.

Endpoints (super_admin / sub_admin / company_admin):
  GET    /api/admin/contractors?company_id=
  POST   /api/admin/contractors
  PUT    /api/admin/contractors/{contractor_id}
  DELETE /api/admin/contractors/{contractor_id}
"""
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import db, get_user_from_token, now_iso, require_role  # noqa: E402

router = APIRouter(prefix="/api/admin/contractors", tags=["contractors"])

FIELDS = [
    "name", "code", "address", "mobile", "email", "pan", "gstin",
    "epf_code", "esic_code", "licence_no", "licence_issue_date",
    "licence_expiry_date", "security_deposit", "max_labour",
    "nature_of_work", "agreement_no", "agreement_start", "agreement_end",
    "status",
]


async def _adm(authorization, company_id):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return admin, company_id


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k in FIELDS:
        if k in payload:
            v = payload.get(k)
            if k in ("security_deposit", "max_labour"):
                try:
                    v = float(v or 0)
                except (TypeError, ValueError):
                    v = 0
            else:
                v = str(v or "").strip()
            out[k] = v
    return out


def _renewal(c: dict) -> dict:
    """Licence / agreement expiry flags (60-day lookahead)."""
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=60)).isoformat()
    lic = str(c.get("licence_expiry_date") or "")
    agr = str(c.get("agreement_end") or "")
    c["licence_expired"] = bool(lic and lic < today)
    c["licence_expiring_soon"] = bool(lic and today <= lic <= soon)
    c["agreement_expired"] = bool(agr and agr < today)
    c["agreement_expiring_soon"] = bool(agr and today <= agr <= soon)
    c["renewal_due_date"] = min([d for d in (lic, agr) if d] or [""])
    return c


async def _active_labour_map(company_id: str) -> Dict[str, int]:
    """contractor name (UPPER) → active employee count."""
    out: Dict[str, int] = {}
    async for u in db.users.find(
        {"company_id": company_id, "role": "employee", "active": True,
         "contractor_name": {"$nin": [None, ""]}},
        {"_id": 0, "contractor_name": 1},
    ):
        k = str(u["contractor_name"]).strip().upper()
        out[k] = out.get(k, 0) + 1
    return out


async def _seed_from_firm_master(company_id: str) -> None:
    """One-time import of the legacy Firm-Master contractor name list."""
    if await db.contractors.count_documents({"company_id": company_id}):
        return
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "contractors": 1})
    for c in (fm or {}).get("contractors") or []:
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        await db.contractors.insert_one({
            "contractor_id": f"ctr_{uuid.uuid4().hex[:10]}",
            "company_id": company_id, "name": name,
            "code": "", "address": "", "mobile": "", "email": "",
            "pan": "", "gstin": "", "epf_code": "", "esic_code": "",
            "licence_no": "", "licence_issue_date": "",
            "licence_expiry_date": "",
            "security_deposit": 0, "max_labour": 0,
            "nature_of_work": str(c.get("nature_of_work") or ""),
            "agreement_no": "",
            "agreement_start": str(c.get("from_date") or ""),
            "agreement_end": str(c.get("to_date") or ""),
            "status": "active", "created_at": now_iso(),
            "seeded_from_firm_master": True})


@router.get("")
async def list_contractors(company_id: Optional[str] = None,
                           authorization: Optional[str] = Header(None)):
    _, company_id = await _adm(authorization, company_id)
    await _seed_from_firm_master(company_id)
    labour = await _active_labour_map(company_id)
    out = []
    async for c in db.contractors.find(
            {"company_id": company_id}, {"_id": 0}).sort("name", 1):
        c["current_active_labour"] = labour.get(
            str(c.get("name") or "").strip().upper(), 0)
        out.append(_renewal(c))
    return {"contractors": out}


@router.post("")
async def create_contractor(payload: Dict[str, Any] = Body(...),
                            authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(authorization,
                                   payload.get("company_id"))
    doc = _clean(payload)
    if not doc.get("name"):
        raise HTTPException(status_code=400, detail="Contractor name is required")
    if await db.contractors.find_one(
            {"company_id": company_id,
             "name": {"$regex": f"^{doc['name']}$", "$options": "i"}}):
        raise HTTPException(status_code=400,
                            detail="Contractor with this name already exists")
    doc.setdefault("status", "active")
    doc.update({"contractor_id": f"ctr_{uuid.uuid4().hex[:10]}",
                "company_id": company_id, "created_at": now_iso(),
                "created_by": admin.get("email") or admin.get("user_id")})
    await db.contractors.insert_one(dict(doc))
    doc.pop("_id", None)
    return {"ok": True, "contractor": doc}


@router.put("/{contractor_id}")
async def update_contractor(contractor_id: str,
                            payload: Dict[str, Any] = Body(...),
                            authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(authorization,
                                   payload.get("company_id"))
    old = await db.contractors.find_one(
        {"contractor_id": contractor_id, "company_id": company_id},
        {"_id": 0})
    if not old:
        raise HTTPException(status_code=404, detail="Contractor not found")
    upd = _clean(payload)
    upd["updated_at"] = now_iso()
    upd["updated_by"] = admin.get("email") or admin.get("user_id")
    await db.contractors.update_one(
        {"contractor_id": contractor_id}, {"$set": upd})
    # keep employees linked by name in sync when the name changes
    new_name = upd.get("name")
    if new_name and new_name != old.get("name"):
        await db.users.update_many(
            {"company_id": company_id, "contractor_name": old.get("name")},
            {"$set": {"contractor_name": new_name}})
    return {"ok": True}


@router.delete("/{contractor_id}")
async def delete_contractor(contractor_id: str,
                            company_id: Optional[str] = None,
                            authorization: Optional[str] = Header(None)):
    _, company_id = await _adm(authorization, company_id)
    r = await db.contractors.delete_one(
        {"contractor_id": contractor_id, "company_id": company_id})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Contractor not found")
    return {"ok": True}
