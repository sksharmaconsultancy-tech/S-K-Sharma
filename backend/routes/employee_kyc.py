"""Iter 89 (follow-up) — Admin-side Employee KYC / Demographic Update route.

Focused endpoint for updating an employee's identity, demographic and
contact fields directly by an admin (as opposed to the employee-driven
`PATCH /api/me/kyc`).

  * PATCH /api/admin/employees/{user_id}/kyc

Payload accepts any subset of the following keys (all optional — only
sent keys are updated):

  Identity / KYC
    aadhar_number, name_as_per_aadhar,
    pan_number, name_as_per_pan,
    dl_number, voter_id_no, passport_no,

  Demographic (Iter 90 — extended catalogue for post-onboarding OCR)
    dob, gender, blood_group, marital_status,
    religion, caste, sub_caste, category,        # SC/ST/OBC/GEN
    disability_status, disability_percent,

  Family / next of kin
    father_name, mother_name, spouse_name,
    family_members,      # free-form string

  Contact / address
    present_address, permanent_address,
    mobile, alternate_mobile, emergency_contact,

  Banking
    bank_account_number, bank_name, ifsc_code, name_as_per_bank,

Access control:
  - super_admin    → any employee
  - company_admin  → only employees of their firm
  - sub_admin      → only employees of their firm
  - other roles    → 403

Immutability (mirrors /api/me/kyc):
  Aadhaar and PAN are immutable once persisted with a non-empty value.
  Attempting to change them raises 400. Same-value writes are silently
  dropped.  All other fields are freely editable by admin.

Every update writes an entry into ``kyc_history`` for audit trail.
"""
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    logger,
)


router = APIRouter(prefix="/api/admin", tags=["employee-kyc"])


# ---------------------------------------------------------------------------
# Normalisers
# ---------------------------------------------------------------------------
def _digits(v: Any) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def _upper(v: Any) -> str:
    return str(v or "").strip().upper()


def _title(v: Any) -> str:
    return str(v or "").strip()


# Accepted values for enum-like fields — we accept anything else too but
# store as-is (mongo is schemaless). These are for UI hint only.
BLOOD_GROUPS = {"A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"}
GENDERS = {"male", "female", "other"}
MARITAL = {"single", "married", "divorced", "widowed", "separated"}
CATEGORIES = {"gen", "obc", "sc", "st", "ews"}


# Simple set of textual keys the admin can freely edit.  All optional.
FREEFORM_KEYS = {
    # demographic
    "religion",
    "caste",
    "sub_caste",
    "tribe",
    "blood_group",
    "gender",
    "marital_status",
    "category",
    "disability_status",
    "disability_percent",
    "dob",
    # family
    "father_name",
    "mother_name",
    "spouse_name",
    "family_members",
    # address / contact
    "present_address",
    "permanent_address",
    "mobile",
    "alternate_mobile",
    "emergency_contact",
    # bank
    "bank_account_number",
    "bank_name",
    "ifsc_code",
    "name_as_per_bank",
    # extra KYC display names
    "name_as_per_aadhar",
    "name_as_per_pan",
    # extra IDs (voter, passport). DL is validated below.
    "voter_id_no",
    "passport_no",
}


def _validate_kyc_admin(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return normalised update dict or raise HTTPException(400).

    Strict format checks are only applied to the four regulated IDs:
      * aadhar_number  (12 digits)
      * pan_number     (AAAAA9999A format)
      * dl_number      (loose upper-case cleanup)
      * ifsc_code      (11 chars)
    All other fields are stored as trimmed strings.
    """
    updates: Dict[str, Any] = {}

    # Aadhaar
    if "aadhar_number" in payload:
        v = _digits(payload["aadhar_number"])
        if v == "":
            updates["aadhar_number"] = None
        elif len(v) != 12:
            raise HTTPException(status_code=400, detail="Aadhaar must be 12 digits.")
        else:
            updates["aadhar_number"] = v

    # PAN
    if "pan_number" in payload:
        v = _upper(payload["pan_number"])
        if v == "":
            updates["pan_number"] = None
        elif not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", v):
            raise HTTPException(
                status_code=400,
                detail="PAN must match ABCDE1234F (5 letters, 4 digits, 1 letter).",
            )
        else:
            updates["pan_number"] = v

    # Driving License
    if "dl_number" in payload:
        v = _upper(payload["dl_number"])
        updates["dl_number"] = v if v else None

    # IFSC
    if "ifsc_code" in payload:
        v = _upper(payload["ifsc_code"])
        if v and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", v):
            raise HTTPException(
                status_code=400,
                detail="IFSC code must be 11 chars, e.g. HDFC0000123.",
            )
        updates["ifsc_code"] = v or None

    # Mobile normalisation — keep the digits, allow +country prefix.
    for k in ("mobile", "alternate_mobile", "emergency_contact"):
        if k in payload:
            raw = str(payload[k] or "").strip()
            if not raw:
                updates[k] = None
                continue
            # Keep leading '+' if present.
            plus = raw.startswith("+")
            v = _digits(raw)
            if not v:
                updates[k] = None
                continue
            updates[k] = ("+" + v) if plus else v

    # DOB should be a plain ISO YYYY-MM-DD OR common Indian DD-MM-YYYY.
    # Accept as-is; the master form does its own parsing.
    if "dob" in payload:
        v = _title(payload["dob"])
        updates["dob"] = v or None

    # Disability percent → float clamp 0-100
    if "disability_percent" in payload:
        try:
            n = float(payload["disability_percent"] or 0)
            n = max(0.0, min(100.0, n))
            updates["disability_percent"] = round(n, 2)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="disability_percent must be 0-100.")

    # Free-form keys — just trim and store, blank clears.
    for k in FREEFORM_KEYS:
        if k in payload and k not in updates:
            v = _title(payload[k])
            # Normalise a couple of enum-ish keys to lowercase for
            # consistent filtering later.
            if k == "gender" and v:
                v = v.lower()
            if k == "marital_status" and v:
                v = v.lower()
            if k == "category" and v:
                v = v.lower()
            if k == "blood_group" and v:
                v = v.upper().replace(" ", "")
            updates[k] = v or None

    return updates


@router.get("/employees/{user_id}/kyc")
async def get_employee_kyc(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return the KYC + demographic block for one employee.  Used by the
    Employee Master screen right after an OCR autofill to re-render the
    latest values without a full user reload."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    emp = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "pin_hash": 0, "password_hash": 0, "face_reference_base64": 0},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's employee")
    if admin["role"] == "sub_admin":
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, emp.get("company_id")):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")

    keys = [
        "aadhar_number", "name_as_per_aadhar",
        "pan_number", "name_as_per_pan",
        "dl_number", "voter_id_no", "passport_no",
        "dob", "gender", "blood_group", "marital_status",
        "religion", "caste", "sub_caste", "tribe", "category",
        "disability_status", "disability_percent",
        "father_name", "mother_name", "spouse_name", "family_members",
        "present_address", "permanent_address",
        "mobile", "alternate_mobile", "emergency_contact",
        "bank_account_number", "bank_name", "ifsc_code", "name_as_per_bank",
    ]
    return {"kyc": {k: emp.get(k) for k in keys}}


@router.patch("/employees/{user_id}/kyc")
async def update_employee_kyc(
    user_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Admin-side KYC / demographic patch.  See module docstring.

    Response mirrors ``/me/kyc``: ``{"ok": True, "kyc": <fresh>}``.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])

    emp = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "pin_hash": 0, "password_hash": 0, "face_reference_base64": 0},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's employee")
    if admin["role"] == "sub_admin":
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, emp.get("company_id")):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")

    updates = _validate_kyc_admin(payload)
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")

    # Enforce Aadhaar / PAN immutability once persisted.
    prev_snapshot: Dict[str, Any] = {}
    for locked_key, human in (("aadhar_number", "Aadhaar"), ("pan_number", "PAN")):
        existing = (emp.get(locked_key) or "").strip()
        if locked_key in updates and existing:
            new_val = (updates.get(locked_key) or "").strip()
            if new_val != existing:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{human} number is locked after first save. "
                        "Contact SuperAdmin to reset it via a formal KYC reset."
                    ),
                )
            # Same value — drop to avoid a no-op write
            updates.pop(locked_key, None)

    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")

    # Build audit prev / next diff for the changed keys only.
    changed_keys = list(updates.keys())
    for k in changed_keys:
        prev_snapshot[k] = emp.get(k)

    updates["kyc_updated_at"] = now_iso()
    updates["kyc_updated_by"] = admin["user_id"]

    # Keep the master "Address" column in sync — the Employee Master list
    # and Add-Employee form read ``users.address``, so an OCR-scanned
    # present address should land there too.
    if updates.get("present_address"):
        updates["address"] = updates["present_address"]

    await db.kyc_history.insert_one({
        "user_id": user_id,
        "company_id": emp.get("company_id"),
        "changed_at": now_iso(),
        "changed_by": admin["user_id"],
        "changed_by_role": admin["role"],
        "source": (payload.get("_source") or "manual").strip() or "manual",
        "prev": prev_snapshot,
        "next": {k: updates.get(k) for k in changed_keys},
    })

    await db.users.update_one({"user_id": user_id}, {"$set": updates})
    logger.info(
        "[kyc-admin] emp=%s updated by %s (%s) — keys=%s",
        user_id, admin["user_id"], admin["role"], changed_keys,
    )

    fresh = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "pin_hash": 0, "password_hash": 0, "face_reference_base64": 0},
    ) or {}
    keys = [
        "aadhar_number", "name_as_per_aadhar",
        "pan_number", "name_as_per_pan",
        "dl_number", "voter_id_no", "passport_no",
        "dob", "gender", "blood_group", "marital_status",
        "religion", "caste", "sub_caste", "tribe", "category",
        "disability_status", "disability_percent",
        "father_name", "mother_name", "spouse_name", "family_members",
        "present_address", "permanent_address",
        "mobile", "alternate_mobile", "emergency_contact",
        "bank_account_number", "bank_name", "ifsc_code", "name_as_per_bank",
        "kyc_updated_at", "kyc_updated_by",
    ]
    return {
        "ok": True,
        "updated_keys": changed_keys,
        "kyc": {k: fresh.get(k) for k in keys},
    }
