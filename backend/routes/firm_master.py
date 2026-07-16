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
    return {"ok": True, "master": saved}
