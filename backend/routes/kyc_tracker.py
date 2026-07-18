"""KYC & Document Expiry Tracker (Enterprise module).

Aggregated per-employee KYC/document status for the admin portal:

  * GET /api/admin/kyc-tracker?company_id=&days=60&include_resigned=false

Per employee it reports:
  - Aadhaar   (aadhar_number | aadhaar_no)
  - PAN       (pan_number | pan_no)
  - Bank      (bank_account_number + ifsc_code)
  - UAN / ESI (uan_no / esi_ip_no)  — informational
  - DL        (dl_number + dl_valid_upto)        → expiry tracked
  - Passport  (passport_no + passport_valid_upto) → expiry tracked
  - Uploaded scan categories from `employee_documents`

Status per employee (priority order): expired > expiring > incomplete > complete.
"Expiring" = any tracked expiry date within the next `days` days (default 60).
Completeness = Aadhaar + PAN + Bank present (DL/Passport are optional IDs).
"""
from datetime import date, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    apply_sub_admin_company_scope,
)

router = APIRouter(prefix="/api/admin", tags=["kyc-tracker"])


def _parse_iso(v: Any) -> Optional[date]:
    s = str(v or "").strip()[:10]
    if not s:
        return None
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


@router.get("/kyc-tracker")
async def kyc_tracker(
    company_id: Optional[str] = Query(None),
    days: int = Query(60, ge=1, le=365),
    include_resigned: bool = Query(False),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])

    if admin.get("role") == "company_admin":
        company_id = admin.get("company_id")
        if not company_id:
            raise HTTPException(status_code=400, detail="No firm assigned")

    q: Dict[str, Any] = {"role": "employee"}
    if company_id:
        q["company_id"] = company_id
    if admin.get("role") == "sub_admin":
        q = apply_sub_admin_company_scope(admin, q)
    if not include_resigned:
        q["$and"] = [
            {"$or": [{"disabled": {"$ne": True}}, {"disabled": {"$exists": False}}]},
            {"$or": [{"exit_date": None}, {"exit_date": {"$exists": False}}, {"exit_date": ""}]},
        ]

    projection = {
        "_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "company_id": 1,
        "department": 1, "designation": 1, "avatar_url": 1,
        "aadhar_number": 1, "aadhaar_no": 1,
        "pan_number": 1, "pan_no": 1,
        "bank_account_number": 1, "ifsc_code": 1, "bank_name": 1,
        "uan_no": 1, "esi_ip_no": 1,
        "dl_number": 1, "dl_valid_upto": 1,
        "passport_no": 1, "passport_valid_upto": 1,
    }
    emps = await db.users.find(q, projection).sort("employee_code", 1).to_list(3000)

    # Company names (badge on rows in "all firms" view).
    comp_names: Dict[str, str] = {}
    async for c in db.companies.find({}, {"_id": 0, "company_id": 1, "name": 1}):
        comp_names[c.get("company_id") or ""] = c.get("name") or ""

    # Uploaded scan categories per employee (single aggregate).
    uids = [e["user_id"] for e in emps]
    docs_by_user: Dict[str, list] = {}
    if uids:
        pipeline = [
            {"$match": {"user_id": {"$in": uids}}},
            {"$group": {"_id": "$user_id", "cats": {"$addToSet": "$category"}}},
        ]
        async for row in db.employee_documents.aggregate(pipeline):
            docs_by_user[row["_id"]] = sorted(c for c in (row.get("cats") or []) if c)

    today = date.today()
    horizon = today + timedelta(days=days)

    out = []
    summary = {
        "total": 0, "complete": 0, "incomplete": 0,
        "missing_aadhaar": 0, "missing_pan": 0, "missing_bank": 0,
        "expiring": 0, "expired": 0,
    }

    for e in emps:
        aadhaar = (e.get("aadhar_number") or e.get("aadhaar_no") or "").strip() or None
        pan = (e.get("pan_number") or e.get("pan_no") or "").strip() or None
        bank_ok = bool((e.get("bank_account_number") or "").strip() and (e.get("ifsc_code") or "").strip())

        expiries = []
        for key in ("dl_valid_upto", "passport_valid_upto"):
            d = _parse_iso(e.get(key))
            if d:
                expiries.append((key, d))
        expired_docs = [k for k, d in expiries if d < today]
        expiring_docs = [k for k, d in expiries if today <= d <= horizon]

        missing = []
        if not aadhaar:
            missing.append("aadhaar")
        if not pan:
            missing.append("pan")
        if not bank_ok:
            missing.append("bank")

        if expired_docs:
            status = "expired"
        elif expiring_docs:
            status = "expiring"
        elif missing:
            status = "incomplete"
        else:
            status = "complete"

        summary["total"] += 1
        if not missing:
            summary["complete"] += 1
        else:
            summary["incomplete"] += 1
        if "aadhaar" in missing:
            summary["missing_aadhaar"] += 1
        if "pan" in missing:
            summary["missing_pan"] += 1
        if "bank" in missing:
            summary["missing_bank"] += 1
        if expired_docs:
            summary["expired"] += 1
        if expiring_docs:
            summary["expiring"] += 1

        out.append({
            "user_id": e["user_id"],
            "name": e.get("name"),
            "employee_code": e.get("employee_code"),
            "company_id": e.get("company_id"),
            "company_name": comp_names.get(e.get("company_id") or "", ""),
            "department": e.get("department"),
            "designation": e.get("designation"),
            "aadhaar_masked": (f"XXXX XXXX {aadhaar[-4:]}" if aadhaar and len(aadhaar) >= 4 else None),
            "has_aadhaar": bool(aadhaar),
            "pan": pan,
            "has_pan": bool(pan),
            "bank_ok": bank_ok,
            "bank_name": e.get("bank_name"),
            "uan_no": e.get("uan_no"),
            "esi_ip_no": e.get("esi_ip_no"),
            "dl_number": e.get("dl_number"),
            "dl_valid_upto": (str(e.get("dl_valid_upto") or "")[:10] or None),
            "passport_no": e.get("passport_no"),
            "passport_valid_upto": (str(e.get("passport_valid_upto") or "")[:10] or None),
            "uploaded_docs": docs_by_user.get(e["user_id"], []),
            "missing": missing,
            "expired_docs": expired_docs,
            "expiring_docs": expiring_docs,
            "status": status,
        })

    return {"summary": summary, "days": days, "employees": out}
