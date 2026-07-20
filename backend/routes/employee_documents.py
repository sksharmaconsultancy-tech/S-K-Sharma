"""Route module: Employee Master PDF + scan documents (extracted from
server.py during modularization — originally Iteration 50/86).

Endpoints:
  Admin
    * GET    /api/admin/employees/{user_id}/master-pdf
    * GET    /api/admin/employees/master-pdf/bulk
    * GET    /api/admin/employees/{user_id}/documents
    * POST   /api/admin/employees/{user_id}/documents
    * GET    /api/admin/employees/{user_id}/documents/{doc_id}
    * DELETE /api/admin/employees/{user_id}/documents/{doc_id}
  Employee self-service
    * GET  /api/me/documents
    * GET  /api/me/documents/{doc_id}
    * POST /api/me/documents
"""
import base64
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from server import (  # noqa: E402
    db,
    logger,
    now_iso,
    get_user_from_token,
    require_role,
    require_permission,
    sub_admin_can_touch_company,
    _load_scoped_employee_any_role,
    _redact_user,
)

router = APIRouter(prefix="/api", tags=["employee-documents"])


class EmployeeDocUpload(BaseModel):
    """Payload for uploading a scan document (base64 encoded) against an
    employee master record.

    Iter 86 - `name_on_doc` / `dob_on_doc` / `father_name_on_doc` are the
    as-printed metadata captured from the scan. They become MANDATORY
    for uploads after (DOJ + 15 days) — validated server-side. They are
    also cross-checked against the employee master record on save; a
    mismatch does NOT block the upload but the response carries a
    `data_mismatch: true` flag with the list of mismatching fields so
    the client can surface a "Data Not match with Registered Data"
    warning.
    """
    category: str  # one of ALLOWED_DOC_CATEGORIES
    custom_label: Optional[str] = None
    filename: Optional[str] = None
    mime_type: str  # image/jpeg, image/png, application/pdf
    base64: str
    name_on_doc: Optional[str] = None
    dob_on_doc: Optional[str] = None
    father_name_on_doc: Optional[str] = None


ALLOWED_DOC_CATEGORIES = {
    "aadhaar", "pan", "passport", "driving_license",
    "bank_passbook", "educational_certificate", "experience_letter",
    "offer_letter", "signed_contract", "photo", "other",
}

ALLOWED_DOC_MIMES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    "application/pdf",
}

# 10 MB upper bound per scan (base64 grows ~33%, so ~13.5 MB decoded).
MAX_DOC_BASE64_LEN = 15 * 1024 * 1024


def _emp_doc_public(d: dict, include_base64: bool = False) -> dict:
    """Serialise an employee_documents doc for API responses. Base64 is
    excluded by default — only returned when the caller explicitly asks
    for a single doc download."""
    out = {
        "doc_id": d.get("doc_id"),
        "user_id": d.get("user_id"),
        "company_id": d.get("company_id"),
        "category": d.get("category"),
        "custom_label": d.get("custom_label"),
        "filename": d.get("filename"),
        "mime_type": d.get("mime_type"),
        "size_bytes": d.get("size_bytes"),
        "uploaded_by": d.get("uploaded_by"),
        "uploaded_via": d.get("uploaded_via"),
        "uploaded_at": d.get("uploaded_at"),
        # Iter 86 - scanned-doc metadata (Name / DOB / Father Name as
        # printed on the physical document) + mismatch flag against
        # employee master record.
        "name_on_doc": d.get("name_on_doc"),
        "dob_on_doc": d.get("dob_on_doc"),
        "father_name_on_doc": d.get("father_name_on_doc"),
        "grace_expired_at_upload": d.get("grace_expired_at_upload", False),
        "data_mismatch": d.get("data_mismatch", False),
        "mismatched_fields": d.get("mismatched_fields", []),
    }
    if include_base64:
        out["base64"] = d.get("base64")
    return out


@router.get("/admin/employees/{user_id}/master-pdf")
async def download_employee_master_pdf(
    user_id: str,
    inline: bool = Query(False),
    authorization: Optional[str] = Header(None),
):
    """Generate + stream a printable Employee Master PDF and persist a
    copy in the `employee_master_pdfs` collection for record.
    """
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    emp = await _load_scoped_employee_any_role(user_id, admin_user)

    company = None
    if emp.get("company_id"):
        company = await db.companies.find_one(
            {"company_id": emp["company_id"]}, {"_id": 0}
        )

    docs = await db.employee_documents.find(
        {"user_id": user_id},
        {"_id": 0, "base64": 0},  # metadata only for PDF listing
    ).sort("uploaded_at", 1).to_list(200)

    from utils.employee_pdf import build_employee_master_pdf
    pdf_bytes = build_employee_master_pdf(
        user=emp,
        company=company,
        policy=(emp.get("employee_policy") or {}),
        documents=docs,
    )

    # Persist a snapshot copy for the record (base64 for portability)
    try:
        await db.employee_master_pdfs.insert_one({
            "record_id": f"empmpdf_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "company_id": emp.get("company_id"),
            "generated_by": admin_user["user_id"],
            "generated_at": now_iso(),
            "size_bytes": len(pdf_bytes),
            "base64": base64.b64encode(pdf_bytes).decode("ascii"),
        })
    except Exception:
        logger.exception("[employee_master_pdf] snapshot persist failed")

    disp = "inline" if inline else "attachment"
    safe_name = (emp.get("name") or user_id).replace("/", "_").replace(" ", "_")
    filename = f"EmployeeMaster_{safe_name}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disp}; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/admin/employees/master-pdf/bulk")
async def download_employees_master_pdf_bulk(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Bulk export — concatenate every employee's master PDF into a single
    file for record. Scoped by the caller's role.
    """
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    require_permission(admin_user, "employees:read")
    if admin_user["role"] == "sub_admin" and company_id and not sub_admin_can_touch_company(admin_user, company_id):
        raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")

    scope: dict = {"role": "employee"}
    if admin_user["role"] == "company_admin":
        scope["company_id"] = admin_user.get("company_id")
    elif company_id:
        scope["company_id"] = company_id

    users = await db.users.find(scope, {"_id": 0}).sort("created_at", 1).to_list(1000)
    users = [_redact_user(u) for u in users]

    # Preload companies for header context in one shot
    company_ids = list({u.get("company_id") for u in users if u.get("company_id")})
    companies = {}
    if company_ids:
        async for c in db.companies.find(
            {"company_id": {"$in": company_ids}}, {"_id": 0}
        ):
            companies[c["company_id"]] = c

    # Fetch document metadata per user (no base64)
    docs_by_user: dict[str, list[dict]] = {}
    if users:
        user_ids = [u["user_id"] for u in users]
        async for d in db.employee_documents.find(
            {"user_id": {"$in": user_ids}}, {"_id": 0, "base64": 0}
        ):
            docs_by_user.setdefault(d["user_id"], []).append(d)

    items = []
    for u in users:
        items.append({
            "user": u,
            "company": companies.get(u.get("company_id")),
            "policy": u.get("employee_policy") or {},
            "documents": docs_by_user.get(u["user_id"], []),
        })

    from utils.employee_pdf import build_employees_master_pdf_bulk
    pdf_bytes = build_employees_master_pdf_bulk(items)

    try:
        await db.employee_master_pdfs.insert_one({
            "record_id": f"empmpdf_{uuid.uuid4().hex[:12]}",
            "user_id": None,  # bulk export
            "company_id": scope.get("company_id"),
            "employee_count": len(users),
            "generated_by": admin_user["user_id"],
            "generated_at": now_iso(),
            "size_bytes": len(pdf_bytes),
            "base64": base64.b64encode(pdf_bytes).decode("ascii"),
            "is_bulk": True,
        })
    except Exception:
        logger.exception("[employee_master_pdf_bulk] snapshot persist failed")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"EmployeeMaster_Bulk_{stamp}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/admin/employees/{user_id}/documents")
async def list_employee_documents(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    require_permission(admin_user, "employees:read")
    await _load_scoped_employee_any_role(user_id, admin_user)

    docs = await db.employee_documents.find(
        {"user_id": user_id},
        {"_id": 0, "base64": 0},
    ).sort("uploaded_at", -1).to_list(500)
    return {"documents": [_emp_doc_public(d) for d in docs]}


@router.post("/admin/employees/{user_id}/documents")
async def upload_employee_document(
    user_id: str,
    payload: EmployeeDocUpload,
    authorization: Optional[str] = Header(None),
):
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    require_permission(admin_user, "employees:write")
    emp = await _load_scoped_employee_any_role(user_id, admin_user)

    category = (payload.category or "").strip().lower()
    if category not in ALLOWED_DOC_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Allowed: {sorted(ALLOWED_DOC_CATEGORIES)}",
        )
    mime = (payload.mime_type or "").strip().lower()
    if mime not in ALLOWED_DOC_MIMES:
        raise HTTPException(
            status_code=400,
            detail="Only JPEG, PNG, WebP and PDF files are allowed.",
        )

    raw_b64 = payload.base64 or ""
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]
    raw_b64 = raw_b64.strip()
    if not raw_b64:
        raise HTTPException(status_code=400, detail="Empty file payload")
    if len(raw_b64) > MAX_DOC_BASE64_LEN:
        raise HTTPException(
            status_code=413,
            detail="File is too large. Maximum 10 MB per document.",
        )
    try:
        decoded = base64.b64decode(raw_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="File is not valid base64.")
    size_bytes = len(decoded)

    doc = {
        "doc_id": f"empdoc_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "company_id": emp.get("company_id"),
        "category": category,
        "custom_label": (payload.custom_label or "").strip() or None,
        "filename": (payload.filename or "").strip() or None,
        "mime_type": mime,
        "base64": raw_b64,
        "size_bytes": size_bytes,
        "uploaded_by": admin_user["user_id"],
        "uploaded_at": now_iso(),
    }
    await db.employee_documents.insert_one(doc)
    return {"ok": True, "document": _emp_doc_public(doc)}


@router.get("/admin/employees/{user_id}/documents/{doc_id}")
async def get_employee_document(
    user_id: str,
    doc_id: str,
    inline: bool = Query(False),
    authorization: Optional[str] = Header(None),
):
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    require_permission(admin_user, "employees:read")
    await _load_scoped_employee_any_role(user_id, admin_user)

    doc = await db.employee_documents.find_one(
        {"doc_id": doc_id, "user_id": user_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Support two modes:
    # ?inline=true → raw file bytes (for browser preview)
    # default      → JSON with base64 (for mobile viewer)
    if inline:
        try:
            raw = base64.b64decode(doc.get("base64") or "")
        except Exception:
            raise HTTPException(status_code=500, detail="Corrupt document blob")
        return Response(
            content=raw,
            media_type=doc.get("mime_type") or "application/octet-stream",
            headers={
                "Content-Disposition": f'inline; filename="{doc.get("filename") or doc_id}"',
                "Cache-Control": "no-store",
            },
        )
    return {"document": _emp_doc_public(doc, include_base64=True)}


@router.delete("/admin/employees/{user_id}/documents/{doc_id}")
async def delete_employee_document(
    user_id: str,
    doc_id: str,
    authorization: Optional[str] = Header(None),
):
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    await _load_scoped_employee_any_role(user_id, admin_user)

    result = await db.employee_documents.delete_one(
        {"doc_id": doc_id, "user_id": user_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Employee self-service documents — view (read-only) + upload own scans
# ---------------------------------------------------------------------------
# The company-admin endpoints above are gated on role. Employees also need
# to see their own scan documents and upload fresh ones (e.g. resubmitting
# an Aadhaar copy). Delete stays admin-only so the record trail is safe.
@router.get("/me/documents")
async def me_list_my_documents(
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    docs = await db.employee_documents.find(
        {"user_id": user["user_id"]},
        {"_id": 0, "base64": 0},
    ).sort("uploaded_at", -1).to_list(200)
    return {"documents": [_emp_doc_public(d) for d in docs]}


@router.get("/me/documents/{doc_id}")
async def me_get_my_document(
    doc_id: str,
    inline: bool = Query(False),
    authorization: Optional[str] = Header(None),
):
    """Employee downloads / previews their own scan document. Matches the
    admin endpoint but strictly scoped to `user_id == self`.
    """
    user = await get_user_from_token(authorization)
    doc = await db.employee_documents.find_one(
        {"doc_id": doc_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if inline:
        try:
            raw = base64.b64decode(doc.get("base64") or "")
        except Exception:
            raise HTTPException(status_code=500, detail="Corrupt document blob")
        return Response(
            content=raw,
            media_type=doc.get("mime_type") or "application/octet-stream",
            headers={
                "Content-Disposition": f'inline; filename="{doc.get("filename") or doc_id}"',
                "Cache-Control": "no-store",
            },
        )
    return {"document": _emp_doc_public(doc, include_base64=True)}


@router.post("/me/documents")
async def me_upload_my_document(
    payload: EmployeeDocUpload,
    authorization: Optional[str] = Header(None),
):
    """Employee uploads / scans their OWN document. Same validation as the
    admin flow — category whitelist, mime whitelist, 10 MB cap. The record
    is tagged `uploaded_by=<self>` and `uploaded_via="employee"` so
    admins can distinguish HR-uploaded vs self-uploaded originals.
    """
    user = await get_user_from_token(authorization)
    category = (payload.category or "").strip().lower()
    if category not in ALLOWED_DOC_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Allowed: {sorted(ALLOWED_DOC_CATEGORIES)}",
        )
    mime = (payload.mime_type or "").strip().lower()
    if mime not in ALLOWED_DOC_MIMES:
        raise HTTPException(
            status_code=400,
            detail="Only JPEG, PNG, WebP and PDF files are allowed.",
        )
    raw_b64 = payload.base64 or ""
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]
    raw_b64 = raw_b64.strip()
    if not raw_b64:
        raise HTTPException(status_code=400, detail="Empty file payload")
    if len(raw_b64) > MAX_DOC_BASE64_LEN:
        raise HTTPException(
            status_code=413,
            detail="File is too large. Maximum 10 MB per document.",
        )
    try:
        decoded = base64.b64decode(raw_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="File is not valid base64.")
    size_bytes = len(decoded)

    # Iter 86 - Mandatory Name / DOB / Father-Name once the employee is
    # PAST the 15-day grace window from Date of Joining. Within grace
    # they can upload with any/none of the fields; the flag lives on
    # the doc so admins can still see who is still within grace.
    grace_days = 15
    grace_expired = False
    doj_str = (user.get("doj") or "").strip()
    if doj_str:
        try:
            doj_dt = datetime.strptime(doj_str[:10], "%Y-%m-%d")
            days_since_doj = (datetime.utcnow().date() - doj_dt.date()).days
            if days_since_doj > grace_days:
                grace_expired = True
        except Exception:
            grace_expired = False  # unparseable DOJ - be lenient
    name_on_doc = (payload.name_on_doc or "").strip()
    dob_on_doc = (payload.dob_on_doc or "").strip()
    father_name_on_doc = (payload.father_name_on_doc or "").strip()
    if grace_expired and (not name_on_doc or not dob_on_doc or not father_name_on_doc):
        raise HTTPException(
            status_code=400,
            detail=(
                "Name, Date of Birth, and Father Name (as printed on the "
                "document) are mandatory. Your 15-day grace period from "
                "joining has expired."
            ),
        )

    # Cross-check against registered master record. Mismatches are
    # WARNINGS, not blockers - the doc is still saved so the audit
    # trail is preserved. The client is expected to show the warning
    # "Data Not match with Registered Data" via the response payload.
    def _norm(s: Optional[str]) -> str:
        return " ".join((s or "").strip().upper().split())

    reg_name = _norm(user.get("name"))
    reg_father = _norm(user.get("father_name"))
    reg_dob = (user.get("dob") or "").strip()[:10]
    mismatched: list[str] = []
    if name_on_doc and reg_name and _norm(name_on_doc) != reg_name:
        mismatched.append("name")
    if father_name_on_doc and reg_father and _norm(father_name_on_doc) != reg_father:
        mismatched.append("father_name")
    if dob_on_doc and reg_dob and dob_on_doc[:10] != reg_dob:
        mismatched.append("dob")
    data_mismatch = len(mismatched) > 0

    doc = {
        "doc_id": f"empdoc_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "company_id": user.get("company_id"),
        "category": category,
        "custom_label": (payload.custom_label or "").strip() or None,
        "filename": (payload.filename or "").strip() or None,
        "mime_type": mime,
        "base64": raw_b64,
        "size_bytes": size_bytes,
        "name_on_doc": name_on_doc or None,
        "dob_on_doc": dob_on_doc or None,
        "father_name_on_doc": father_name_on_doc or None,
        "grace_expired_at_upload": grace_expired,
        "data_mismatch": data_mismatch,
        "mismatched_fields": mismatched,
        "uploaded_by": user["user_id"],
        "uploaded_via": "employee",  # marker for HR to see self-uploads
        "uploaded_at": now_iso(),
    }
    await db.employee_documents.insert_one(doc)
    return {
        "ok": True,
        "document": _emp_doc_public(doc),
        "data_mismatch": data_mismatch,
        "mismatched_fields": mismatched,
        "warning": (
            "Data Not match with Registered Data"
            if data_mismatch else None
        ),
    }
