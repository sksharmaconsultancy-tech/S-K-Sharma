"""Iter 484 — Firm Master v2: normalized Company Contacts, Audit Trail,
Clone / Export configuration, company-code uniqueness check, test WhatsApp.

Contacts are stored NORMALIZED in ``db.company_contacts`` — one document per
contact person — so a firm can have unlimited contacts per type without any
schema change:
    { contact_id, company_id, contact_type, name, designation, mobile,
      alt_mobile, email, personal_email, whatsapp, country_code,
      recipient_permissions{...}, sort_order, created_at, updated_at }

Company-level communication (official emails / website / landline) and
notification preferences stay on the firm_masters doc (``communication`` +
``comm_prefs`` keys) and persist through the normal PATCH firm-master flow.
"""
import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import Response

from server import db, get_user_from_token, now_iso  # noqa: E402
from routes.firm_master import _assert_firm_access, _mask_secrets  # noqa: E402

router = APIRouter(prefix="/api/admin", tags=["firm-master-v2"])

CONTACT_TYPES = ["primary", "hr", "payroll", "compliance", "accounts", "other"]

RECIPIENT_KEYS = [
    "payroll_reports", "compliance_reports", "bank_advice", "pf_notices",
    "esic_notices", "leave_notifications", "attendance_alerts",
]

_CONTACT_FIELDS = [
    "contact_type", "name", "designation", "mobile", "alt_mobile",
    "email", "personal_email", "whatsapp", "country_code", "sort_order",
]


# ---------------------------------------------------------------- audit
async def write_fm_audit(company_id: str, user: Dict[str, Any], action: str,
                         sections: Optional[List[str]] = None,
                         detail: Optional[str] = None) -> None:
    try:
        await db.firm_master_audit.insert_one({
            "audit_id": f"fma_{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "action": action,
            "sections": sections or [],
            "detail": detail,
            "by": user.get("user_id"),
            "by_name": user.get("name") or user.get("email"),
            "by_role": user.get("role"),
            "at": now_iso(),
        })
    except Exception:
        pass


@router.get("/firm-master/{company_id}/audit")
async def fm_audit_list(company_id: str, limit: int = Query(60, le=300),
                        authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    await _assert_firm_access(user, company_id)
    rows = await db.firm_master_audit.find(
        {"company_id": company_id}, {"_id": 0},
    ).sort("at", -1).to_list(limit)
    return {"entries": rows}


# ------------------------------------------------------------- contacts
def _clean_contact(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: (str(raw.get(k)).strip() if raw.get(k) is not None else "")
           for k in _CONTACT_FIELDS if k != "sort_order"}
    if out.get("contact_type") not in CONTACT_TYPES:
        out["contact_type"] = "other"
    out["sort_order"] = int(raw.get("sort_order") or 0)
    perms = raw.get("recipient_permissions") or {}
    out["recipient_permissions"] = {k: bool(perms.get(k)) for k in RECIPIENT_KEYS}
    return out


async def _migrate_legacy_contacts(company_id: str) -> List[Dict[str, Any]]:
    """One-time seed from firm_masters.contact_persons + header emails."""
    fm = await db.firm_masters.find_one(
        {"company_id": company_id},
        {"_id": 0, "contact_persons": 1, "header": 1},
    ) or {}
    docs: List[Dict[str, Any]] = []
    legacy = fm.get("contact_persons") or []
    hdr = fm.get("header") or {}
    for i, row in enumerate(legacy):
        if not ((row.get("name") or "").strip() or (row.get("mobile") or "").strip()):
            continue
        docs.append({
            "contact_id": f"cc_{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "contact_type": "primary" if i == 0 else "other",
            "name": (row.get("name") or "").strip(),
            "designation": (row.get("position") or "").strip(),
            "mobile": (row.get("mobile") or "").strip(),
            "alt_mobile": "", "personal_email": "", "whatsapp": "",
            "country_code": "+91",
            # First contact inherits the firm email that used to live on the
            # old "Firm Header" section.
            "email": (hdr.get("email_1") or "").strip() if i == 0 else "",
            "recipient_permissions": {k: (i == 0) for k in RECIPIENT_KEYS},
            "sort_order": i,
            "migrated_from_legacy": True,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
    if not docs and ((hdr.get("email_1") or "").strip()):
        docs.append({
            "contact_id": f"cc_{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "contact_type": "primary",
            "name": "", "designation": "", "mobile": "", "alt_mobile": "",
            "email": (hdr.get("email_1") or "").strip(),
            "personal_email": "", "whatsapp": "", "country_code": "+91",
            "recipient_permissions": {k: True for k in RECIPIENT_KEYS},
            "sort_order": 0,
            "migrated_from_legacy": True,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
    if docs:
        await db.company_contacts.insert_many(copy.deepcopy(docs))
    for d in docs:
        d.pop("_id", None)
    return docs


@router.get("/firm-master/{company_id}/contacts")
async def fm_contacts_list(company_id: str,
                           authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    await _assert_firm_access(user, company_id)
    rows = await db.company_contacts.find(
        {"company_id": company_id}, {"_id": 0},
    ).sort([("contact_type", 1), ("sort_order", 1)]).to_list(500)
    migrated = False
    if not rows:
        rows = await _migrate_legacy_contacts(company_id)
        migrated = bool(rows)
    return {"contacts": rows, "migrated": migrated,
            "contact_types": CONTACT_TYPES, "recipient_keys": RECIPIENT_KEYS}


@router.put("/firm-master/{company_id}/contacts")
async def fm_contacts_save(company_id: str,
                           payload: Dict[str, Any] = Body(...),
                           authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    await _assert_firm_access(user, company_id)
    incoming = payload.get("contacts") or []
    if not isinstance(incoming, list):
        raise HTTPException(status_code=400, detail="contacts must be a list")
    # Duplicate-email guard across all contact emails (non-empty only).
    seen: Dict[str, str] = {}
    for c in incoming:
        for f in ("email", "personal_email"):
            e = (c.get(f) or "").strip().lower()
            if not e:
                continue
            if e in seen:
                raise HTTPException(
                    status_code=400,
                    detail=f"Duplicate email '{e}' — each contact email must be unique.")
            seen[e] = f
    keep_ids: List[str] = []
    now = now_iso()
    for c in incoming:
        doc = _clean_contact(c)
        cid = c.get("contact_id") or f"cc_{uuid.uuid4().hex[:10]}"
        keep_ids.append(cid)
        doc["updated_at"] = now
        await db.company_contacts.update_one(
            {"company_id": company_id, "contact_id": cid},
            {"$set": doc,
             "$setOnInsert": {"contact_id": cid, "company_id": company_id,
                              "created_at": now}},
            upsert=True,
        )
    await db.company_contacts.delete_many(
        {"company_id": company_id, "contact_id": {"$nin": keep_ids}})
    await write_fm_audit(company_id, user, "contacts_saved",
                         ["contact_details"],
                         f"{len(keep_ids)} contact(s) saved")
    rows = await db.company_contacts.find(
        {"company_id": company_id}, {"_id": 0},
    ).sort([("contact_type", 1), ("sort_order", 1)]).to_list(500)
    return {"ok": True, "contacts": rows}


@router.get("/firm-master/{company_id}/contacts/{contact_id}/vcard")
async def fm_contact_vcard(company_id: str, contact_id: str,
                           authorization: Optional[str] = Header(None),
                           token: Optional[str] = Query(None)):
    user = await get_user_from_token(authorization or (f"Bearer {token}" if token else None))
    await _assert_firm_access(user, company_id)
    c = await db.company_contacts.find_one(
        {"company_id": company_id, "contact_id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    comp = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "name": 1}) or {}
    cc = (c.get("country_code") or "+91").replace("+", "")
    lines = [
        "BEGIN:VCARD", "VERSION:3.0",
        f"FN:{c.get('name') or 'Contact'}",
        f"ORG:{comp.get('name') or ''}",
        f"TITLE:{c.get('designation') or ''}",
    ]
    if c.get("mobile"):
        lines.append(f"TEL;TYPE=CELL:+{cc}{c['mobile']}")
    if c.get("alt_mobile"):
        lines.append(f"TEL;TYPE=CELL:+{cc}{c['alt_mobile']}")
    if c.get("email"):
        lines.append(f"EMAIL;TYPE=WORK:{c['email']}")
    if c.get("personal_email"):
        lines.append(f"EMAIL;TYPE=HOME:{c['personal_email']}")
    lines.append("END:VCARD")
    fname = (c.get("name") or "contact").replace(" ", "_")
    return Response("\r\n".join(lines), media_type="text/vcard",
                    headers={"Content-Disposition": f"attachment; filename={fname}.vcf"})


# ------------------------------------------------- company code uniqueness
@router.get("/firm-master-check-code")
async def fm_check_code(code: str = Query(...),
                        company_id: Optional[str] = Query(None),
                        authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    if user.get("role") not in ("super_admin", "company_admin", "sub_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    code = (code or "").strip().upper()
    if not code:
        return {"unique": False, "detail": "Code is empty"}
    q: Dict[str, Any] = {"company_code": code}
    if company_id:
        q["company_id"] = {"$ne": company_id}
    clash = await db.companies.find_one(q, {"_id": 0, "company_id": 1, "name": 1})
    return {"unique": clash is None,
            "clash_with": (clash or {}).get("name")}


# ------------------------------------------------------------ export/clone
@router.get("/firm-master/{company_id}/export")
async def fm_export(company_id: str,
                    authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    await _assert_firm_access(user, company_id)
    fm = await db.firm_masters.find_one({"company_id": company_id}, {"_id": 0}) or {}
    _mask_secrets(fm)
    contacts = await db.company_contacts.find(
        {"company_id": company_id}, {"_id": 0}).to_list(500)
    comp = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "company_code": 1, "business_category": 1}) or {}
    await write_fm_audit(company_id, user, "config_exported", [], None)
    return {
        "exported_at": now_iso(),
        "exported_by": user.get("email") or user.get("user_id"),
        "company": comp,
        "firm_master": fm,
        "contacts": contacts,
    }


@router.post("/firm-master/{company_id}/clone")
async def fm_clone(company_id: str,
                   payload: Dict[str, Any] = Body(default={}),
                   authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only a super admin can clone a firm")
    await _assert_firm_access(user, company_id)
    new_name = (payload.get("new_name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Please enter a name for the cloned firm")
    src_comp = await db.companies.find_one({"company_id": company_id}, {"_id": 0})
    if not src_comp:
        raise HTTPException(status_code=404, detail="Source firm not found")
    new_id = f"cmp_{uuid.uuid4().hex[:10]}"
    new_code = uuid.uuid4().hex[:6].upper()
    comp = dict(src_comp)
    comp.update({
        "company_id": new_id, "name": new_name, "company_code": new_code,
        "created_at": now_iso(), "cloned_from": company_id,
        "logo_base64": src_comp.get("logo_base64"),
    })
    await db.companies.insert_one(comp)
    fm = await db.firm_masters.find_one({"company_id": company_id}, {"_id": 0})
    if fm:
        fm = dict(fm)
        fm["company_id"] = new_id
        fm["company_name"] = new_name
        gen = dict(fm.get("general") or {})
        gen["company_name"] = new_name
        gen["company_code"] = new_code
        fm["general"] = gen
        fm["cloned_from"] = company_id
        fm["updated_at"] = now_iso()
        fm["updated_by"] = user["user_id"]
        await db.firm_masters.insert_one(fm)
    contacts = await db.company_contacts.find(
        {"company_id": company_id}, {"_id": 0}).to_list(500)
    for c in contacts:
        c["contact_id"] = f"cc_{uuid.uuid4().hex[:10]}"
        c["company_id"] = new_id
        c["created_at"] = now_iso()
    if contacts:
        await db.company_contacts.insert_many(contacts)
    await write_fm_audit(company_id, user, "company_cloned", [],
                         f"→ {new_name} ({new_id})")
    return {"ok": True, "company_id": new_id, "name": new_name,
            "company_code": new_code}


# ---------------------------------------------------------- test whatsapp
@router.post("/firm-master/{company_id}/test-whatsapp")
async def fm_test_whatsapp(company_id: str,
                           payload: Dict[str, Any] = Body(default={}),
                           authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    await _assert_firm_access(user, company_id)
    from utils import whatsapp_engine as wa
    s = await wa.get_settings(company_id)
    if not wa._configured(s):
        return {"ok": False, "configured": False,
                "detail": ("WhatsApp Business API is not configured yet "
                           "(Meta app credentials pending). Configure it in "
                           "Communication → WhatsApp Center once your Meta "
                           "account is unblocked.")}
    to = (payload.get("to") or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="Enter a WhatsApp number to send the test to")
    fake_user = {"user_id": f"test_{user['user_id']}", "name": "Test Contact",
                 "phone": to, "whatsapp": to}
    m = await wa.enqueue_message(
        company_id=company_id, user=fake_user, category="custom",
        body=("This is a TEST message from your Smart Payroll Service portal "
              "confirming the WhatsApp integration is working."),
        extra={}, source="manual", created_by=user["user_id"], dedupe=False)
    return {"ok": bool(m), "configured": True,
            "detail": f"Test message queued to {to}" if m else "Could not queue message"}
