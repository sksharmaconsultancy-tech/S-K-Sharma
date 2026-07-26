"""Iter 313 — ESIC Leave Module.

Workflow (user PRD):
  Employee submits ESIC medical certificate → HR enters the ESIC Leave
  period (From–To) + uploads the certificate → HR/Compliance approves →
  attendance is auto-marked (approved ``esic`` leave record) → the
  Compliance Salary Process auto-imports the ESIC leave days into the
  run's ``esic_leave_days`` column → payroll & statutory reports flow.

Per-firm settings (all default ON per the user's checklist):
  enabled · link_compliance · auto_mark_attendance · lock_after_freeze ·
  require_certificate · allow_backdated (+ max_backdate_days) ·
  show_separate_register (Salary Register column).

Endpoints (super_admin / sub_admin / company_admin):
  GET/PUT /api/admin/esic-leave/settings
  GET     /api/admin/esic-leave?company_id=&month=&status=
  POST    /api/admin/esic-leave
  POST    /api/admin/esic-leave/{entry_id}/certificate
  POST    /api/admin/esic-leave/{entry_id}/approve
  POST    /api/admin/esic-leave/{entry_id}/reject
  DELETE  /api/admin/esic-leave/{entry_id}
  GET     /api/admin/esic-leave/{entry_id}/certificate
"""
import base64
import io
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from server import (  # noqa: E402
    db,
    get_user_from_token,
    now_iso,
    require_role,
)

router = APIRouter(prefix="/api/admin/esic-leave", tags=["esic-leave"])

DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": True,
    "link_compliance": True,
    "auto_mark_attendance": True,
    "lock_after_freeze": True,
    "require_certificate": True,
    "allow_backdated": True,
    "max_backdate_days": 30,
    "show_separate_register": True,
}


async def _admin(authorization: Optional[str]) -> Dict[str, Any]:
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    return admin


def _cid_for(admin: Dict[str, Any], company_id: Optional[str]) -> Optional[str]:
    if admin["role"] == "company_admin":
        return admin.get("company_id")
    return company_id or None


async def get_esic_settings(company_id: Optional[str]) -> Dict[str, Any]:
    """Effective settings for a firm (defaults merged). Import-safe for
    server.py's compliance engine."""
    doc = await db.esic_leave_settings.find_one(
        {"company_id": company_id}, {"_id": 0}) if company_id else None
    return {**DEFAULT_SETTINGS, **(doc or {})}


def _d(v: Any) -> date:
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        raise HTTPException(status_code=400,
                            detail="Dates must be YYYY-MM-DD")


def _overlap_days(f: date, t: date, month: str) -> float:
    """Days of [f, t] falling inside YYYY-MM ``month``."""
    y, m = int(month[:4]), int(month[5:7])
    m0 = date(y, m, 1)
    m1 = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)) - timedelta(days=1)
    lo, hi = max(f, m0), min(t, m1)
    return float((hi - lo).days + 1) if hi >= lo else 0.0


def _months_spanned(f: date, t: date) -> List[str]:
    out, cur = [], date(f.year, f.month, 1)
    while cur <= t:
        out.append(f"{cur.year:04d}-{cur.month:02d}")
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
    return out


async def _frozen_months(company_id: str, months: List[str]) -> List[str]:
    """Months (of the given list) that already have a FROZEN payroll run."""
    out: List[str] = []
    for mo in months:
        if await db.compliance_salary_runs.find_one(
                {"company_id": company_id, "month": mo, "frozen": True},
                {"_id": 1}):
            out.append(mo)
    return out


async def esic_leave_days_map(company_id: str, month: str) -> Dict[str, float]:
    """user_id → approved ESIC leave days inside ``month``. Used by the
    Compliance Salary Process import (server.py)."""
    st = await get_esic_settings(company_id)
    if not (st.get("enabled") and st.get("link_compliance")):
        return {}
    y, m = int(month[:4]), int(month[5:7])
    m0 = f"{y:04d}-{m:02d}-01"
    m1 = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)) - timedelta(days=1)
    out: Dict[str, float] = {}
    async for e in db.esic_leaves.find(
        {"company_id": company_id, "status": "approved",
         "from_date": {"$lte": m1.isoformat()}, "to_date": {"$gte": m0}},
        {"_id": 0, "user_id": 1, "from_date": 1, "to_date": 1},
    ):
        try:
            d = _overlap_days(_d(e["from_date"]), _d(e["to_date"]), month)
        except HTTPException:
            continue
        if d > 0:
            out[e["user_id"]] = out.get(e["user_id"], 0.0) + d
    return out


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@router.get("/settings")
async def read_settings(company_id: Optional[str] = Query(None),
                        authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    cid = _cid_for(admin, company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="company_id required")
    return {"company_id": cid, "settings": await get_esic_settings(cid)}


@router.put("/settings")
async def save_settings(payload: Dict[str, Any] = Body(...),
                        authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    cid = _cid_for(admin, payload.get("company_id"))
    if not cid:
        raise HTTPException(status_code=400, detail="company_id required")
    st = {k: payload.get(k, DEFAULT_SETTINGS[k]) for k in DEFAULT_SETTINGS}
    st["max_backdate_days"] = max(0, int(st.get("max_backdate_days") or 0))
    for k in st:
        if k != "max_backdate_days":
            st[k] = bool(st[k])
    await db.esic_leave_settings.update_one(
        {"company_id": cid},
        {"$set": {**st, "company_id": cid,
                  "updated_at": now_iso(), "updated_by": admin["user_id"]}},
        upsert=True)
    return {"ok": True, "settings": st}


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------
@router.get("")
async def list_entries(company_id: Optional[str] = Query(None),
                       month: Optional[str] = Query(None),
                       status: Optional[str] = Query(None),
                       authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    cid = _cid_for(admin, company_id)
    q: Dict[str, Any] = {}
    if cid:
        q["company_id"] = cid
    if status:
        q["status"] = status
    if month:
        y, m = int(month[:4]), int(month[5:7])
        m1 = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)) - timedelta(days=1)
        q["from_date"] = {"$lte": m1.isoformat()}
        q["to_date"] = {"$gte": f"{y:04d}-{m:02d}-01"}
    entries = await db.esic_leaves.find(
        q, {"_id": 0, "certificate_base64": 0},
    ).sort("created_at", -1).to_list(500)
    return {"entries": entries, "count": len(entries)}


@router.post("")
async def create_entry(payload: Dict[str, Any] = Body(...),
                       authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    cid = _cid_for(admin, payload.get("company_id"))
    user_id = str(payload.get("user_id") or "").strip()
    if not cid or not user_id:
        raise HTTPException(status_code=400,
                            detail="company_id and user_id required")
    st = await get_esic_settings(cid)
    if not st["enabled"]:
        raise HTTPException(status_code=400,
                            detail="ESIC Leave Module is disabled for this firm")
    emp = await db.users.find_one(
        {"user_id": user_id, "role": "employee", "company_id": cid},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "esi_ip_no": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found in this firm")
    f, t = _d(payload.get("from_date")), _d(payload.get("to_date"))
    if t < f:
        raise HTTPException(status_code=400, detail="'To' date is before 'From' date")
    today = date.today()
    if f < today:
        if not st["allow_backdated"]:
            raise HTTPException(status_code=400,
                                detail="Backdated ESIC Leave entry is not allowed for this firm")
        if (today - f).days > int(st["max_backdate_days"]):
            raise HTTPException(
                status_code=400,
                detail=f"Backdated entry limited to {st['max_backdate_days']} day(s)")
    if st["lock_after_freeze"]:
        frozen = await _frozen_months(cid, _months_spanned(f, t))
        if frozen:
            raise HTTPException(
                status_code=409,
                detail=f"Attendance locked — payroll already frozen for {', '.join(frozen)}")
    cert = payload.get("certificate_base64") or None
    entry = {
        "entry_id": f"esl_{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        "user_id": user_id,
        "employee_name": emp.get("name"),
        "employee_code": emp.get("employee_code"),
        "esi_ip_no": emp.get("esi_ip_no"),
        "from_date": f.isoformat(),
        "to_date": t.isoformat(),
        "days": float((t - f).days + 1),
        "remarks": str(payload.get("remarks") or "").strip() or None,
        "certificate_base64": cert,
        "certificate_name": (payload.get("certificate_name") or None) if cert else None,
        "has_certificate": bool(cert),
        "status": "pending",
        "created_by": admin["user_id"],
        "created_by_name": admin.get("name") or admin.get("email"),
        "created_at": now_iso(),
    }
    await db.esic_leaves.insert_one(dict(entry))
    entry.pop("certificate_base64", None)
    return {"ok": True, "entry": entry}


async def _get_entry(entry_id: str, admin: Dict[str, Any],
                     with_cert: bool = False) -> Dict[str, Any]:
    proj = {"_id": 0} if with_cert else {"_id": 0, "certificate_base64": 0}
    e = await db.esic_leaves.find_one({"entry_id": entry_id}, proj)
    if not e:
        raise HTTPException(status_code=404, detail="ESIC Leave entry not found")
    if admin["role"] == "company_admin" and e.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's entry")
    return e


@router.post("/{entry_id}/certificate")
async def upload_certificate(entry_id: str,
                             payload: Dict[str, Any] = Body(...),
                             authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    e = await _get_entry(entry_id, admin)
    cert = payload.get("certificate_base64")
    if not cert:
        raise HTTPException(status_code=400, detail="certificate_base64 required")
    await db.esic_leaves.update_one(
        {"entry_id": entry_id},
        {"$set": {"certificate_base64": cert,
                  "certificate_name": payload.get("certificate_name") or "certificate",
                  "has_certificate": True,
                  "certificate_uploaded_at": now_iso()}})
    return {"ok": True}


@router.get("/{entry_id}/certificate")
async def view_certificate(entry_id: str,
                           authorization: Optional[str] = Header(None),
                           token: Optional[str] = Query(None)):
    admin = await _admin(authorization or (f"Bearer {token}" if token else None))
    e = await _get_entry(entry_id, admin, with_cert=True)
    cert = e.get("certificate_base64")
    if not cert:
        raise HTTPException(status_code=404, detail="No certificate uploaded")
    raw = cert.split(",", 1)[1] if cert.startswith("data:") else cert
    name = str(e.get("certificate_name") or "certificate")
    media = "application/pdf" if name.lower().endswith(".pdf") else "image/jpeg"
    if cert.startswith("data:") and ";" in cert:
        media = cert.split(":", 1)[1].split(";", 1)[0] or media
    try:
        blob = base64.b64decode(raw)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="Corrupt certificate data")
    return StreamingResponse(
        io.BytesIO(blob), media_type=media,
        headers={"Content-Disposition": f'inline; filename="{name}"'})


@router.post("/{entry_id}/approve")
async def approve_entry(entry_id: str,
                        authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    e = await _get_entry(entry_id, admin)
    if e["status"] == "approved":
        return {"ok": True, "entry": e}
    st = await get_esic_settings(e["company_id"])
    if st["require_certificate"] and not e.get("has_certificate"):
        raise HTTPException(status_code=400,
                            detail="Medical certificate required before approval")
    f, t = _d(e["from_date"]), _d(e["to_date"])
    if st["lock_after_freeze"]:
        frozen = await _frozen_months(e["company_id"], _months_spanned(f, t))
        if frozen:
            raise HTTPException(
                status_code=409,
                detail=f"Attendance locked — payroll already frozen for {', '.join(frozen)}")
    upd = {"status": "approved", "approved_by": admin["user_id"],
           "approved_by_name": admin.get("name") or admin.get("email"),
           "approved_at": now_iso()}
    # Auto-mark attendance: approved ESIC leave record (leave reports,
    # detail slip FYTD and future grid marks all read db.leaves).
    if st["auto_mark_attendance"]:
        leave_id = f"lv_{uuid.uuid4().hex[:12]}"
        await db.leaves.insert_one({
            "leave_id": leave_id,
            "user_id": e["user_id"],
            "company_id": e["company_id"],
            "leave_type": "esic",
            "from_date": e["from_date"],
            "to_date": e["to_date"],
            "reason": e.get("remarks") or "ESIC medical leave",
            "status": "approved",
            "approved_by": admin["user_id"],
            "source": "esic_leave_module",
            "esic_entry_id": entry_id,
            "created_at": now_iso(),
        })
        upd["linked_leave_id"] = leave_id
    await db.esic_leaves.update_one({"entry_id": entry_id}, {"$set": upd})
    return {"ok": True, "entry": {**e, **upd}}


@router.post("/{entry_id}/reject")
async def reject_entry(entry_id: str,
                       payload: Dict[str, Any] = Body(default={}),
                       authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    e = await _get_entry(entry_id, admin)
    st = await get_esic_settings(e["company_id"])
    if e["status"] == "approved" and st["lock_after_freeze"]:
        frozen = await _frozen_months(
            e["company_id"], _months_spanned(_d(e["from_date"]), _d(e["to_date"])))
        if frozen:
            raise HTTPException(
                status_code=409,
                detail=f"Attendance locked — payroll already frozen for {', '.join(frozen)}")
    if e.get("linked_leave_id"):
        await db.leaves.delete_one({"leave_id": e["linked_leave_id"]})
    await db.esic_leaves.update_one(
        {"entry_id": entry_id},
        {"$set": {"status": "rejected",
                  "rejected_by": admin["user_id"],
                  "rejected_at": now_iso(),
                  "reject_reason": str(payload.get("reason") or "").strip() or None,
                  "linked_leave_id": None}})
    return {"ok": True}


@router.delete("/{entry_id}")
async def delete_entry(entry_id: str,
                       authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    e = await _get_entry(entry_id, admin)
    st = await get_esic_settings(e["company_id"])
    if e["status"] == "approved" and st["lock_after_freeze"]:
        frozen = await _frozen_months(
            e["company_id"], _months_spanned(_d(e["from_date"]), _d(e["to_date"])))
        if frozen:
            raise HTTPException(
                status_code=409,
                detail=f"Attendance locked — payroll already frozen for {', '.join(frozen)}")
    if e.get("linked_leave_id"):
        await db.leaves.delete_one({"leave_id": e["linked_leave_id"]})
    await db.esic_leaves.delete_one({"entry_id": entry_id})
    return {"ok": True}
