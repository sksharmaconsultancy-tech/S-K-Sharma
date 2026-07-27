"""Iter 89 — Route module: Firm Master (Web Portal only).

Comprehensive firm profile with 17 sections migrated from the user's
legacy Windows Firm Master screen:

  * Header: start_date, category, business_nature, emails
  * Registered / Office / Factory addresses
  * Allowance & Deduction checklists (fixed labels — reusable across firms)
  * Bank details
  * Firm settings (salary structure, toggles)
  * Contact persons (repeatable)
  * Salary process settings + CL/PL + EPF + ESI + Bonus + Report Order
  * Compliance documents grid (13 fixed rows)
  * Portal login credentials grid (5 fixed rows — passwords encrypted at
    rest via ``fernet`` when the key is available; otherwise stored
    plaintext for MVP so an ops admin can re-enter them later.)

Endpoints:
  * GET   /api/admin/firm-master/{company_id}      - Read profile
  * PATCH /api/admin/firm-master/{company_id}      - Upsert profile

The frontend renders the whole thing as a single scrollable form; the
backend does not gate individual fields with validation errors — it
accepts partial payloads and merges into the persisted subdocument so
Save works section-by-section without forcing all-or-nothing input.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    logger,
)


router = APIRouter(prefix="/api/admin", tags=["firm-master"])


# ---------------------------------------------------------------------------
# Fixed catalogs — mirror the exact labels from the legacy screen. Storing
# them as constants (not per-firm records) means every firm inherits the
# same rows automatically, and adding a new label later is a single-file
# code change instead of a data migration.
# ---------------------------------------------------------------------------
ALLOWANCE_LABELS: List[str] = [
    "HRA", "CONV.", "OTH. ALLOW.", "OVER TIME", "INCENTIVE",
    "OTHER MISC.ALLOWANCE", "BONUS", "MEDICAL ALLOWANCES",
    "FOOD ALLOWANCES", "GRATUITY", "LEAVE", "DA",
]

DEDUCTION_LABELS: List[str] = [
    "PF", "ESI", "I. TAX", "TDS", "OTH. DEDUC.",
    "ADVANCE", "UNIFORM", "CLUB", "CANTEEN", "PT",
]

COMPLIANCE_DOC_LABELS: List[str] = [
    "TIN REG. NO.", "FIRM REG. NO.", "POWER CONN. NO.", "E.S.I NO.",
    "SHOP ACT. REG. NO.", "COMPANY PAN NO.", "TAN NO.", "EPF CODE NO.",
    "INCORPORATION CER. NO.", "FACTORY & BOILER LICENCE NO.",
    "LIN NO.", "DIGITAL SIGNATURE", "LABOURE LICENCE",
]

PORTAL_LOGIN_LABELS: List[str] = [
    "PF LOGIN", "ESI Login", "SSO Login", "Rajfeb Login", "PT Login",
]

SALARY_STRUCTURES: List[str] = [
    "Standard Monthly",
    "Per-Day Wages",
    "Piece-Rate",
    "Contractual",
    "Mixed",
]

REPORT_ORDER_OPTIONS: List[str] = [
    "Employee Code",
    "Name (A → Z)",
    "Designation",
    "Department",
    "Date of Joining",
]


def _empty_master(company_id: str, company_name: str = "") -> Dict[str, Any]:
    """Return a fully-populated default firm-master doc so the frontend
    can render every section even for a brand-new firm."""
    return {
        "company_id": company_id,
        "company_name": company_name,
        # Iter 89 — Firm logo (base64 PNG/JPEG data URL). Synced to
        # ``companies.logo_base64`` on save so the admin shell + mobile
        # app can render it without a second fetch.
        "logo": {
            "image_base64": None,
            "mime_type": None,
        },
        "header": {
            "start_date": None,
            "category": None,
            "business_nature": None,
            "email_1": None,
            "email_2": None,
        },
        "registered_address": {
            "address1": None, "address2": None,
            "city": None, "state": None, "pin_code": None,
        },
        "office_address": {
            "same_as_firm": True,
            "address1": None, "address2": None,
            "city": None, "state": None, "pin_code": None,
        },
        "factory_address": {
            "same_as_firm": True,
            "address1": None, "address2": None,
            "city": None, "state": None, "pin_code": None,
        },
        # Fixed allowance/deduction catalogs — value is bool enabled flag.
        "allowances": {label: False for label in ALLOWANCE_LABELS},
        "deductions": {label: False for label in DEDUCTION_LABELS},
        "bank": {
            "account_no": None, "account_name": None,
            "bank_name": None, "branch_name": None, "ifsc": None,
        },
        "settings": {
            "salary_structure": None,
            "reference_by": None,
            "firm_active": True,
            "whatsapp_enable": False,
            "auto_email_process": False,
            "email_enable": False,
            "allow_category_rate": False,
            # Iter 158 — when ON, Employee Code is ALWAYS auto-assigned and
            # the manual code field is locked in Add/Edit Employee.
            "auto_employee_code": False,
        },
        "contact_persons": [],  # {name, mobile, position}
        "salary_process": {
            "online_salary": True,  # Iter 114 — Compliance salary is DEFAULT for every firm
            "offline_salary": False,
            "bio_matrix_attendance": False,
            "gratuity_applicable": False,
            # Iter 142 — firm-wide OT gate. False = NO overtime is
            # calculated for ANY employee of this firm.
            "ot_allowed": True,
            "online_process_days": 0,
            "offline_process_days": 0,
        },
        "leave_policy": {
            "cl_pl_applicable": False,
            "cl_day_limit": 0,
            "pl_day_limit": 0,
        },
        "epf": {
            "applicable": False,
            "applicable_date": None,
            "edli_applicable": False,
            "epf_no": None,
            "group_policy_no": None,
            "epf_user_id": None,
            "epf_password": None,
        },
        "esi": {
            "applicable": False,
            "applicable_date": None,
            "esi_rate": 1,
            "esi_no": None,
            "esi_user_id": None,
            "esi_password": None,
        },
        "bonus": {
            "monthly_bonus": False,
            "gross_mode": None,   # "including" | "excluding"
            "overtime_in_report": False,
            "days_mode": None,    # "fix" | "custom"
            "custom_days": None,
        },
        "report_order": {
            "staff": None,
            "labour": None,
            "other": None,
        },
        "compliance_docs": [
            {"description": label, "number": None,
             "issue_date": None, "expiry_date": None}
            for label in COMPLIANCE_DOC_LABELS
        ],
        "portal_logins": [
            {"login_type": label, "user_name": None,
             "password": None, "unit_location": None, "login_url": None}
            for label in PORTAL_LOGIN_LABELS
        ],
        "updated_at": None,
        "updated_by": None,
    }


def _merge_master(existing: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge helper — top-level sections are replaced wholesale if
    provided, but nested keys are merged so a Save on just one section
    doesn't wipe the rest of the profile."""
    merged: Dict[str, Any] = dict(existing)
    for k, v in (patch or {}).items():
        if k in ("company_id", "company_name"):
            continue  # never overwrite the identity keys
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    return merged


def _ensure_catalogs(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Guarantee the fixed catalog labels are always present even if a
    legacy master was saved before a new label was added."""
    doc.setdefault("allowances", {})
    for lab in ALLOWANCE_LABELS:
        doc["allowances"].setdefault(lab, False)
    doc.setdefault("deductions", {})
    for lab in DEDUCTION_LABELS:
        doc["deductions"].setdefault(lab, False)

    doc.setdefault("compliance_docs", [])
    existing_desc = {r.get("description") for r in doc["compliance_docs"]}
    for lab in COMPLIANCE_DOC_LABELS:
        if lab not in existing_desc:
            doc["compliance_docs"].append({
                "description": lab, "number": None,
                "issue_date": None, "expiry_date": None,
            })

    doc.setdefault("portal_logins", [])
    existing_types = {r.get("login_type") for r in doc["portal_logins"]}
    for lab in PORTAL_LOGIN_LABELS:
        if lab not in existing_types:
            doc["portal_logins"].append({
                "login_type": lab, "user_name": None,
                "password": None, "unit_location": None, "login_url": None,
            })
    return doc


# ---------------------------------------------------------------------------
# SEC-003 — portal credential protection helpers.
# ---------------------------------------------------------------------------
_SECRET_SALARY_FIELDS = (("epf", "epf_password"), ("esi", "esi_password"))


def _mask_secrets(doc: Dict[str, Any]) -> None:
    """Replace stored passwords with a mask before returning to the client."""
    from utils.secrets_vault import MASK
    for row in doc.get("portal_logins") or []:
        if row.get("password"):
            row["password"] = MASK
            row["password_set"] = True
        else:
            row["password_set"] = False
    for sec_key, field in _SECRET_SALARY_FIELDS:
        sec = doc.get(sec_key) or {}
        if sec.get(field):
            sec[field] = MASK
            sec[f"{field}_set"] = True
        elif field in sec:
            sec[f"{field}_set"] = False


def _protect_secrets(merged: Dict[str, Any], existing: Dict[str, Any]) -> None:
    """Encrypt any NEW plaintext passwords; when the client sends back the
    mask (unchanged field) keep the previously stored ciphertext."""
    from utils.secrets_vault import MASK, encrypt_secret

    prev_rows = {str(r.get("login_type") or ""): r
                 for r in existing.get("portal_logins") or []}
    for row in merged.get("portal_logins") or []:
        row.pop("password_set", None)
        val = row.get("password")
        if val == MASK:
            prev = prev_rows.get(str(row.get("login_type") or ""), {})
            row["password"] = prev.get("password") or None
        else:
            row["password"] = encrypt_secret(val) if val else None
    for sec_key, field in _SECRET_SALARY_FIELDS:
        sec = merged.get(sec_key)
        if not isinstance(sec, dict):
            continue
        sec.pop(f"{field}_set", None)
        val = sec.get(field)
        if val == MASK:
            sec[field] = (existing.get(sec_key) or {}).get(field) or None
        else:
            sec[field] = encrypt_secret(val) if val else None


async def migrate_portal_secrets() -> int:
    """One-time idempotent migration: encrypt any legacy PLAINTEXT portal
    passwords already sitting in ``firm_masters``. Returns docs updated."""
    from utils.secrets_vault import encrypt_secret, is_encrypted
    changed = 0
    async for doc in db.firm_masters.find(
            {}, {"_id": 0, "company_id": 1, "portal_logins": 1, "epf": 1, "esi": 1}):
        upd: Dict[str, Any] = {}
        rows = doc.get("portal_logins") or []
        if any(r.get("password") and not is_encrypted(r.get("password")) for r in rows):
            for r in rows:
                if r.get("password") and not is_encrypted(r["password"]):
                    r["password"] = encrypt_secret(r["password"])
            upd["portal_logins"] = rows
        for sec_key, field in _SECRET_SALARY_FIELDS:
            sec = doc.get(sec_key) or {}
            if sec.get(field) and not is_encrypted(sec[field]):
                upd[f"{sec_key}.{field}"] = encrypt_secret(sec[field])
        if upd:
            await db.firm_masters.update_one(
                {"company_id": doc["company_id"]}, {"$set": upd})
            changed += 1
    if changed:
        logger.info("[SEC-003] encrypted legacy portal passwords in %s firm master(s)", changed)
    return changed


async def _assert_firm_access(user: Dict[str, Any], company_id: str) -> Dict[str, Any]:
    """Super Admin sees any firm; sub admins any firm in their scope;
    company_admin only their own."""
    if user["role"] not in ("super_admin", "company_admin", "sub_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    if user["role"] == "company_admin":
        if user.get("company_id") != company_id:
            raise HTTPException(status_code=403, detail="Not your firm")
    if user["role"] == "sub_admin":
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(user, company_id):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Firm not found")
    return company


@router.get("/firm-master/{company_id}")
async def get_firm_master(
    company_id: str,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    company = await _assert_firm_access(user, company_id)
    doc = await db.firm_masters.find_one({"company_id": company_id}, {"_id": 0})
    if not doc:
        doc = _empty_master(company_id, company.get("name", ""))
    else:
        doc = _ensure_catalogs(doc)
        doc.setdefault("company_name", company.get("name", ""))
    # SEC-003 — NEVER return portal passwords (masked; has-password flags
    # let the UI show the field as filled).
    _mask_secrets(doc)

    # Iter 107 — Firm Category auto-selects from the business category
    # picked when the firm was created (if the master has none yet).
    hdr = doc.setdefault("header", {})
    if not (hdr.get("category") or "").strip():
        cat = (company.get("business_category") or "").strip()
        sub = (company.get("business_subcategory") or "").strip()
        if cat:
            hdr["category"] = f"{cat.title()}{' — ' + sub.title() if sub else ''}"

    # Iter 89 — Sections 5 (Allowances) & 6 (Deductions) are now linked
    # to the Masters registry so any custom heads the admin adds via
    # `/admin/masters?type=allowance` etc. appear here too. We merge the
    # legacy fixed labels with any global + firm-scoped custom heads.
    allow_docs = await db.masters.find(
        {"type": "allowance",
         "company_id": {"$in": [company_id, "__global__", None]}},
        {"_id": 0, "name": 1},
    ).sort("name", 1).to_list(500)
    ded_docs = await db.masters.find(
        {"type": "deduction",
         "company_id": {"$in": [company_id, "__global__", None]}},
        {"_id": 0, "name": 1},
    ).sort("name", 1).to_list(500)

    # Preserve order: fixed legacy labels first (they mirror the
    # customer's Windows screen exactly), then any custom heads.
    def _merge(base, extra):
        seen = {x.lower(): True for x in base}
        out = list(base)
        for row in extra:
            n = (row.get("name") or "").strip()
            if n and n.lower() not in seen:
                out.append(n)
                seen[n.lower()] = True
        return out

    allowance_labels = _merge(ALLOWANCE_LABELS, allow_docs)
    deduction_labels = _merge(DEDUCTION_LABELS, ded_docs)

    # Guarantee every label from the merged list has a value in the
    # doc (defaults to False) so the frontend can render both fixed
    # and custom rows uniformly.
    doc.setdefault("allowances", {})
    for lab in allowance_labels:
        doc["allowances"].setdefault(lab, False)
    doc.setdefault("deductions", {})
    for lab in deduction_labels:
        doc["deductions"].setdefault(lab, False)

    return {
        "master": doc,
        "catalogs": {
            "allowance_labels": allowance_labels,
            "deduction_labels": deduction_labels,
            "compliance_doc_labels": COMPLIANCE_DOC_LABELS,
            "portal_login_labels": PORTAL_LOGIN_LABELS,
            "salary_structures": SALARY_STRUCTURES,
            "report_order_options": REPORT_ORDER_OPTIONS,
        },
        "role": user["role"],
    }


@router.patch("/firm-master/{company_id}")
async def upsert_firm_master(
    company_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    company = await _assert_firm_access(user, company_id)

    existing = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0},
    )
    if not existing:
        existing = _empty_master(company_id, company.get("name", ""))
    else:
        existing = _ensure_catalogs(existing)

    merged = _merge_master(existing, payload)
    merged["company_id"] = company_id
    merged["company_name"] = company.get("name", "")
    merged["updated_at"] = now_iso()
    merged["updated_by"] = user["user_id"]
    # SEC-003 — encrypt new passwords / keep existing ones when the client
    # echoes back the mask.
    _protect_secrets(merged, existing)

    # Iter 98 — CL/PL gate: when "CL PL Applicable" is enabled the allowed
    # number of leaves is MANDATORY.
    _lp = merged.get("leave_policy") or {}
    if _lp.get("cl_pl_applicable"):
        _cl = float(_lp.get("cl_day_limit") or 0)
        _pl = float(_lp.get("pl_day_limit") or 0)
        if _cl <= 0 and _pl <= 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    "CL/PL is enabled — please mention the allowed no. of "
                    "leaves (CL Day Limit and/or PL Day Limit)."
                ),
            )

    await db.firm_masters.update_one(
        {"company_id": company_id},
        {"$set": merged},
        upsert=True,
    )
    # Iter 89 — Mirror the firm logo onto ``companies.logo_base64`` so
    # the admin shell + mobile app can render it via the standard
    # /api/companies feed without a second lookup.
    logo_b64 = None
    logo_mime = None
    try:
        logo_b64 = (merged.get("logo") or {}).get("image_base64") or None
        logo_mime = (merged.get("logo") or {}).get("mime_type") or None
    except Exception:
        pass
    await db.companies.update_one(
        {"company_id": company_id},
        {"$set": {
            "logo_base64": logo_b64,
            "logo_mime": logo_mime,
            "logo_updated_at": now_iso() if logo_b64 else None,
        }},
    )
    logger.info(
        "[firm-master] %s updated by %s (%s)",
        company_id, user["user_id"], user["role"],
    )
    saved = await db.firm_masters.find_one({"company_id": company_id}, {"_id": 0})
    _mask_secrets(saved)
    return {"ok": True, "master": saved}


# ---------------------------------------------------------------------------
# Iter 306 (user #14) — Firms ID & Password (PF / ESIC) vault screen.
# SUPER ADMIN ONLY and gated behind the caller's login PIN: passwords are
# decrypted from the secrets vault only after the PIN checks out.
# ---------------------------------------------------------------------------

def _fm_city(fm: Dict[str, Any]) -> str:
    """Best-effort city from registered → office → factory address."""
    for k in ("registered_address", "office_address", "factory_address"):
        c = str(((fm.get(k) or {}).get("city")) or "").strip()
        if c:
            return c
    return ""


@router.post("/firm-credentials")
async def firm_credentials(
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    # Iter 331 (user request) — Sub Super Admins can view firm credentials
    # too (verified against their OWN login PIN).
    require_role(user, ["super_admin", "sub_admin"])
    pin = str(payload.get("pin") or "").strip()
    from server import _verify_pin
    me = await db.users.find_one({"user_id": user["user_id"]},
                                 {"_id": 0, "pin_hash": 1})
    if not pin or not (me or {}).get("pin_hash") or not _verify_pin(pin, me["pin_hash"]):
        raise HTTPException(
            status_code=403,
            detail="Enter your correct Admin PIN to view firm credentials")

    from utils.secrets_vault import decrypt_secret
    names: Dict[str, str] = {}
    async for c in db.companies.find({}, {"_id": 0, "company_id": 1, "name": 1}):
        names[c["company_id"]] = c.get("name") or c["company_id"]

    out: List[Dict[str, Any]] = []
    async for fm in db.firm_masters.find(
        {}, {"_id": 0, "company_id": 1, "epf": 1, "esi": 1, "portal_logins": 1,
             "registered_address": 1, "office_address": 1, "factory_address": 1},
    ):
        cid = fm.get("company_id")
        if cid not in names:
            continue  # orphaned master — firm was deleted
        epf = fm.get("epf") or {}
        esi = fm.get("esi") or {}
        extras = []
        for row in fm.get("portal_logins") or []:
            if row.get("user_name") or row.get("password"):
                extras.append({
                    "login_type": row.get("login_type"),
                    "user_name": row.get("user_name"),
                    "password": decrypt_secret(row.get("password")),
                })
        out.append({
            "company_id": cid,
            "firm_name": names.get(cid, cid),
            "city": _fm_city(fm),
            "epf_code": epf.get("epf_no"),
            "epf_user_id": epf.get("epf_user_id"),
            "epf_password": decrypt_secret(epf.get("epf_password")),
            "esi_no": esi.get("esi_no"),
            "esi_user_id": esi.get("esi_user_id"),
            "esi_password": decrypt_secret(esi.get("esi_password")),
            "other_logins": extras,
        })
    out.sort(key=lambda r: str(r.get("firm_name") or "").lower())
    logger.info("[firm-credentials] revealed to %s (%d firms)",
                user["user_id"], len(out))
    return {"firms": out}


# ---------------------------------------------------------------------------
# Iter 325 (user request) — LIST OF FIRMS: full Firm Master data as an
# Excel-style grid + downloadable XLSX.
# ---------------------------------------------------------------------------
_FIRM_LIST_COLUMNS: List[tuple] = [
    ("firm_name", "Firm Name"), ("category", "Category"),
    ("business_nature", "Business Nature"), ("start_date", "Start Date"),
    ("city", "City"), ("state", "State"), ("pin_code", "Pin Code"),
    ("address", "Registered Address"), ("email_1", "Email 1"),
    ("email_2", "Email 2"),
    ("epf_no", "PF Code"), ("epf_applicable", "PF Applicable"),
    ("esi_no", "ESIC Code"), ("esi_applicable", "ESI Applicable"),
    ("bank_name", "Bank Name"), ("account_no", "Account No"),
    ("ifsc", "IFSC"),
    ("contact_person", "Contact Person"), ("contact_phone", "Contact Phone"),
    ("firm_active", "Active"),
]


async def _firms_master_rows() -> List[Dict[str, Any]]:
    names: Dict[str, str] = {}
    async for c in db.companies.find({}, {"_id": 0, "company_id": 1, "name": 1}):
        names[c["company_id"]] = c.get("name") or c["company_id"]
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    async for fm in db.firm_masters.find({}, {"_id": 0}):
        cid = fm.get("company_id")
        if cid not in names:
            continue
        seen.add(cid)
        ra = fm.get("registered_address") or {}
        hdr = fm.get("header") or {}
        epf = fm.get("epf") or {}
        esi = fm.get("esi") or {}
        bank = fm.get("bank") or {}
        cps = fm.get("contact_persons") or []
        cp = cps[0] if cps else {}
        addr = ", ".join(str(x).strip() for x in [ra.get("address1"), ra.get("address2")]
                         if x and str(x).strip())
        rows.append({
            "company_id": cid,
            "firm_name": names[cid],
            "category": hdr.get("category") or "",
            "business_nature": hdr.get("business_nature") or "",
            "start_date": hdr.get("start_date") or "",
            "city": _fm_city(fm),
            "state": ra.get("state") or "",
            "pin_code": ra.get("pin_code") or "",
            "address": addr,
            "email_1": hdr.get("email_1") or "",
            "email_2": hdr.get("email_2") or "",
            "epf_no": epf.get("epf_no") or "",
            "epf_applicable": "Yes" if epf.get("applicable") else "No",
            "esi_no": esi.get("esi_no") or "",
            "esi_applicable": "Yes" if esi.get("applicable") else "No",
            "bank_name": bank.get("bank_name") or "",
            "account_no": bank.get("account_no") or "",
            "ifsc": bank.get("ifsc") or "",
            "contact_person": (cp.get("name") or "") if isinstance(cp, dict) else "",
            "contact_phone": (cp.get("phone") or cp.get("mobile") or "") if isinstance(cp, dict) else "",
            "firm_active": "Yes" if (fm.get("settings") or {}).get("firm_active", True) else "No",
        })
    # Firms without a saved Firm Master still appear (name only).
    for cid, nm in names.items():
        if cid not in seen:
            rows.append({"company_id": cid, "firm_name": nm,
                         **{k: "" for k, _l in _FIRM_LIST_COLUMNS
                            if k not in ("firm_name",)}})
    rows.sort(key=lambda r: str(r.get("firm_name") or "").lower())
    return rows


@router.get("/firms-master-list")
async def firms_master_list(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin"])
    rows = await _firms_master_rows()
    return {"columns": [{"key": k, "label": l} for k, l in _FIRM_LIST_COLUMNS],
            "firms": rows}


@router.get("/firms-master-list/export.xlsx")
async def firms_master_list_xlsx(authorization: Optional[str] = Header(None)):
    import io as _io
    from fastapi.responses import Response
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin"])
    rows = await _firms_master_rows()
    wb = Workbook()
    ws = wb.active
    ws.title = "Firms Master"
    heads = ["S.No"] + [l for _k, l in _FIRM_LIST_COLUMNS]
    for i, h in enumerate(heads, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0F3B5C")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for r, row in enumerate(rows, 2):
        ws.cell(row=r, column=1, value=r - 1)
        for i, (k, _l) in enumerate(_FIRM_LIST_COLUMNS, 2):
            ws.cell(row=r, column=i, value=row.get(k) or "")
    for i, w in enumerate([6, 32, 14, 18, 12, 14, 14, 10, 34, 24, 24,
                           18, 12, 18, 12, 18, 18, 14, 20, 14, 8], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "C2"
    buf = _io.BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="Firms_Master_List.xlsx"',
                 "Cache-Control": "no-store"})
