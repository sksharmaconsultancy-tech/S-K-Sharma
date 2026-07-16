"""Iter 89 — OCR endpoint for scanning uploaded documents.

Reads Aadhaar / PAN / Voter ID / firm-compliance documents via a vision
LLM (GPT-5.4 by default, configurable) and returns structured JSON so
the frontend can auto-fill the target master (Employee Master or Firm
Master). Multi-language: handles both Hindi and English labels on Indian
identity documents.

  POST /api/admin/ocr/parse-document
      body: {
        document_base64, mime_type?,          # legacy single image
        pages?: [{document_base64, mime_type}],  # multi-page (front/back) or PDF
        document_type?, hint?,
      }
      -> { ok, document_type_detected, fields, raw_text, confidence }

PDF uploads are rasterised server-side (PyMuPDF) — the first 3 pages of
each PDF become images sent to the vision model alongside any photos.
"""
import base64
import json
import os
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from dotenv import load_dotenv

from server import (  # noqa: E402
    get_user_from_token,
    require_role,
    logger,
)

load_dotenv()


router = APIRouter(prefix="/api/admin", tags=["ocr"])


DOC_PROMPTS: Dict[str, str] = {
    "aadhaar": (
        "This is an Indian Aadhaar card. Extract these fields:\n"
        "  name, dob (as DD-MM-YYYY), gender (Male|Female|Other), "
        "aadhaar_no (12 digits, no spaces), address, "
        "father_name (if listed as 'S/O' or 'D/O' - use the parent name)\n"
        "The card is often bilingual (Hindi + English) - use whichever "
        "you can read clearly. If a field is not visible, set it to null."
    ),
    "bank_passbook": (
        "This is an Indian bank passbook front page / cancelled cheque. Extract:\n"
        "  account_holder_name, bank_account_number (digits only), "
        "ifsc_code (AAAA0XXXXXX), bank_name, branch_name\n"
        "If a field is not visible, set it to null."
    ),
    "pan": (
        "This is an Indian PAN card. Extract these fields:\n"
        "  name (as printed - person's name), father_name, "
        "dob (as DD-MM-YYYY), pan_no (10-char AAAAA9999A format)\n"
        "If it is a firm/company PAN, put the entity name in `name` and "
        "leave father_name null. If a field is not visible, set it to null."
    ),
    "voter": (
        "This is an Indian Voter ID (EPIC) card. Extract:\n"
        "  name, father_name, dob (DD-MM-YYYY), gender, "
        "voter_id (EPIC number - alphanumeric), address\n"
        "If any field is not visible, set it to null."
    ),
    "passport": (
        "This is an Indian passport data page. Extract:\n"
        "  name (Given Names + Surname), father_name, dob (DD-MM-YYYY), "
        "gender, passport_no, place_of_birth, "
        "issue_date (DD-MM-YYYY), expiry_date (DD-MM-YYYY), "
        "nationality, address\n"
        "If any field is not visible, set it to null."
    ),
    "driving_license": (
        "This is an Indian Driving License. Extract:\n"
        "  name, father_name, dob (DD-MM-YYYY), address, "
        "dl_no (license number), issue_date (DD-MM-YYYY), "
        "expiry_date (DD-MM-YYYY), vehicle_categories\n"
        "If any field is not visible, set it to null."
    ),
    "firm_pan": (
        "This is a company/firm PAN card. Extract:\n"
        "  company_name, pan_no (AAAAA9999A), "
        "incorporation_date (DD-MM-YYYY if visible)\n"
        "If any field is not visible, set it to null."
    ),
    "firm_compliance": (
        "This is a firm/company compliance certificate (TIN, EPF, ESIC, "
        "factory license, shop-act, or similar). Extract:\n"
        "  description (what kind of certificate this is), "
        "number (registration / certificate number), "
        "issue_date (DD-MM-YYYY), expiry_date (DD-MM-YYYY if applicable), "
        "issuing_authority\n"
        "If any field is not visible, set it to null."
    ),
    "generic": (
        "This is an Indian identity or compliance document. Read every "
        "visible field and return them in a flat JSON object. Look "
        "particularly for these keys: name, father_name, mother_name, "
        "spouse_name, dob (DD-MM-YYYY), gender, aadhaar_no, pan_no, "
        "voter_id, passport_no, dl_no, present_address, permanent_address, "
        "family_members (comma-separated list of any other family names on "
        "the document — spouse, children, siblings, dependents), "
        "issue_date (DD-MM-YYYY), expiry_date (DD-MM-YYYY), number, "
        "company_name, issuing_authority. If a field is not visible, "
        "OMIT it entirely from the JSON (do not set it to null)."
    ),
}


ALLOWED_IMAGE_MIMES = ("image/jpeg", "image/jpg", "image/png", "image/webp")
MAX_PAGES = 4          # hard cap on images sent to the vision model
PDF_MAX_PAGES = 3      # pages rasterised per uploaded PDF


def _strip_data_url(b64: str) -> str:
    if "," in b64 and b64.startswith("data:"):
        return b64.split(",", 1)[1]
    return b64


def _pdf_to_image_b64(pdf_b64: str) -> list:
    """Rasterise the first PDF_MAX_PAGES pages of a base64 PDF into
    PNG base64 strings using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"PDF support unavailable: {exc}",
        )
    try:
        pdf_bytes = base64.b64decode(pdf_b64)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read the PDF file")
    out = []
    for page in doc[:PDF_MAX_PAGES]:
        # 2x zoom ≈ 150 dpi — enough for OCR without huge payloads.
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        out.append(base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    if not out:
        raise HTTPException(status_code=400, detail="PDF has no pages")
    return out


@router.post("/ocr/parse-document")
async def ocr_parse_document(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    return await _parse_document(admin, payload)


# Iter 151 — Employee-accessible OCR (self-onboarding). Any logged-in
# user can scan THEIR OWN identity document to auto-fill the joining form.
user_router = APIRouter(prefix="/api", tags=["ocr"])


@user_router.post("/ocr/parse-my-document")
async def ocr_parse_my_document(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    result = await _parse_document(user, payload)
    # Iter 151 — auto-save the scanned document details onto the employee's
    # own record: full snapshot in `onboarding_ocr` (audit) + standard KYC
    # keys, but NEVER overwriting a field that already has a value.
    try:
        if result.get("ok") and result.get("fields"):
            from server import db, now_iso
            f = result["fields"]
            # Iter 151b — store the scan/captured copy itself in the DB.
            scan_doc_id = await _store_scan_copy(
                user, payload, "onboarding",
                {"document_type_detected": result.get("document_type_detected")})
            kyc_map = {
                "aadhaar_no": "aadhar_number",
                "pan_no": "pan_number",
                "voter_id": "voter_id_no",
                "passport_no": "passport_no",
                "gender": "gender",
                "address": "present_address",
                "present_address": "present_address",
                "father_name": "father_name",
                "name": "name_as_per_aadhar",
                # Iter 155 — bank passbook / cancelled cheque scan.
                "bank_account_number": "bank_account_number",
                "account_no": "bank_account_number",
                "ifsc_code": "ifsc_code",
                "ifsc": "ifsc_code",
                "bank_name": "bank_name",
                "branch_name": "bank_branch",
                "account_holder_name": "name_as_per_bank",
            }
            fresh = await db.users.find_one(
                {"user_id": user["user_id"]},
                {"_id": 0, **{v: 1 for v in kyc_map.values()}}) or {}
            updates: Dict[str, Any] = {
                "onboarding_ocr": {
                    "fields": {k: v for k, v in f.items() if v},
                    "document_type_detected": result.get("document_type_detected"),
                    "confidence": result.get("confidence"),
                    "scan_doc_id": scan_doc_id,
                    "scanned_at": now_iso(),
                },
            }
            for src, dst in kyc_map.items():
                val = f.get(src)
                if val and not fresh.get(dst):
                    if dst == "gender":
                        val = str(val).strip().lower()
                    updates[dst] = str(val).strip()
            await db.users.update_one({"user_id": user["user_id"]}, {"$set": updates})
            logger.info("[ocr] onboarding scan saved for %s — keys=%s",
                        user["user_id"], sorted(updates.keys()))
    except Exception:
        logger.exception("[ocr] failed to persist onboarding scan (non-fatal)")
    return result


@user_router.post("/ocr/parse-family-document")
async def ocr_parse_family_document(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Iter 151 — parse a FAMILY MEMBER's Aadhaar card. Parse-only: nothing
    is written to the employee's own KYC fields (unlike parse-my-document)."""
    user = await get_user_from_token(authorization)
    payload["document_type"] = "aadhaar"
    result = await _parse_document(user, payload)
    # Iter 151b — store the scan copy; frontend passes scan_doc_id back
    # into POST /me/family-members so the image stays linked to the member.
    try:
        if result.get("ok"):
            result["scan_doc_id"] = await _store_scan_copy(
                user, payload, "family_member", {"document_type_detected": "aadhaar"})
    except Exception:
        logger.exception("[ocr] failed to store family scan copy (non-fatal)")
    return result


@user_router.post("/me/family-members")
async def add_my_family_member(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Iter 151 — directly append a family member to the employee's own
    record (no approval flow — same low-risk class as profile photo).
    Used by the 'Scan family member Aadhaar' auto-add button."""
    from server import db, now_iso
    user = await get_user_from_token(authorization)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Family member name is required")
    dob = str(payload.get("dob") or "").strip() or None
    if dob:
        # Accept DD-MM-YYYY (OCR) or YYYY-MM-DD; store ISO.
        import re
        m = re.fullmatch(r"(\d{2})[-/](\d{2})[-/](\d{4})", dob)
        if m:
            dob = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob):
            dob = None
    aadhaar = str(payload.get("aadhaar_no") or "").replace(" ", "").strip() or None
    scan_doc_id = str(payload.get("scan_doc_id") or "").strip() or None
    member = {
        "name": name,
        "relation": str(payload.get("relation") or "").strip() or None,
        "dob": dob,
        "occupation": str(payload.get("occupation") or "").strip() or None,
        "contact": str(payload.get("contact") or "").strip() or None,
        "aadhaar_no": aadhaar,
        "scan_doc_id": scan_doc_id,
        "source": "aadhaar_ocr" if aadhaar else "manual",
        "added_at": now_iso(),
    }
    # Duplicate guard: same aadhaar or same name already declared.
    me = await db.users.find_one(
        {"user_id": user["user_id"]}, {"_id": 0, "family_members": 1}) or {}
    for fm in (me.get("family_members") or []):
        if aadhaar and (fm.get("aadhaar_no") or "").replace(" ", "") == aadhaar:
            raise HTTPException(status_code=400,
                                detail=f"'{fm.get('name')}' with this Aadhaar number is already added.")
        if (fm.get("name") or "").strip().lower() == name.lower():
            raise HTTPException(status_code=400,
                                detail=f"A family member named '{name}' is already added.")
    await db.users.update_one(
        {"user_id": user["user_id"]}, {"$push": {"family_members": member}})
    return {"ok": True, "member": member}


@user_router.get("/me/scanned-documents/{doc_id}")
async def get_my_scanned_document(
    doc_id: str,
    authorization: Optional[str] = Header(None),
):
    """Employee fetches their own stored scan copy."""
    from server import db
    user = await get_user_from_token(authorization)
    doc = await db.scanned_documents.find_one(
        {"doc_id": doc_id, "user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scanned document not found")
    return doc


@router.get("/scanned-documents/{doc_id}")
async def admin_get_scanned_document(
    doc_id: str,
    authorization: Optional[str] = Header(None),
):
    """Admin fetches any employee's stored scan copy (firm-scoped)."""
    from server import db
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    doc = await db.scanned_documents.find_one({"doc_id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Scanned document not found")
    if admin["role"] == "company_admin" and doc.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Document belongs to another firm")
    return doc


async def _store_scan_copy(user: Dict[str, Any], payload: Dict[str, Any],
                           purpose: str, extra: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Iter 151b — persist the uploaded scan/captured images into
    db.scanned_documents (separate collection, keeps user docs small).
    Returns the doc_id, or None when nothing/too large."""
    from server import db, now_iso
    pages = []
    if payload.get("document_base64"):
        pages.append({
            "document_base64": _strip_data_url(payload["document_base64"]),
            "mime_type": (payload.get("mime_type") or "image/jpeg").lower(),
        })
    for p in (payload.get("pages") or []):
        if isinstance(p, dict) and p.get("document_base64"):
            pages.append({
                "document_base64": _strip_data_url(p["document_base64"]),
                "mime_type": (p.get("mime_type") or "image/jpeg").lower(),
            })
    pages = pages[:MAX_PAGES]
    if not pages:
        return None
    if sum(len(p["document_base64"]) for p in pages) > 9_000_000:  # ~6.7MB decoded
        logger.warning("[ocr] scan copy too large — not stored")
        return None
    doc_id = f"scan_{uuid.uuid4().hex[:12]}"
    await db.scanned_documents.insert_one({
        "doc_id": doc_id,
        "user_id": user["user_id"],
        "company_id": user.get("company_id"),
        "purpose": purpose,
        "pages": pages,
        "created_at": now_iso(),
        **(extra or {}),
    })
    return doc_id


async def _parse_document(admin: Dict[str, Any], payload: Dict[str, Any]):
    doc_type = (payload.get("document_type") or "generic").lower()
    hint = (payload.get("hint") or "").strip()

    # Collect pages: new multi-page shape first, then the legacy single
    # `document_base64` for backward compatibility.
    raw_pages = payload.get("pages")
    if not isinstance(raw_pages, list):
        raw_pages = []
    if payload.get("document_base64"):
        raw_pages = [{
            "document_base64": payload["document_base64"],
            "mime_type": payload.get("mime_type") or "image/jpeg",
        }] + raw_pages

    if not raw_pages:
        raise HTTPException(status_code=400, detail="No document uploaded")

    image_pages: list = []  # plain base64 PNG/JPEG strings
    for page in raw_pages[:MAX_PAGES]:
        if not isinstance(page, dict):
            continue
        b64 = _strip_data_url(page.get("document_base64") or "")
        if not b64:
            continue
        mime = (page.get("mime_type") or "image/jpeg").lower()
        # Payload sanity: reject > 8 MB (base64) per page.
        if len(b64) > 8 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File too large (max ~6 MB per page)")
        if mime == "application/pdf":
            image_pages.extend(_pdf_to_image_b64(b64))
        elif mime in ALLOWED_IMAGE_MIMES:
            image_pages.append(b64)
        else:
            raise HTTPException(
                status_code=400,
                detail="Each page must be a JPEG/PNG/WebP image or a PDF",
            )
    image_pages = image_pages[:MAX_PAGES]
    if not image_pages:
        raise HTTPException(status_code=400, detail="No readable pages in upload")

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "EMERGENT_LLM_KEY is not configured. Add it to backend/.env "
                "(get it from Profile → Universal Key on Emergent)."
            ),
        )

    prompt_body = DOC_PROMPTS.get(doc_type, DOC_PROMPTS["generic"])
    if hint:
        prompt_body += f"\n\nAdmin hint: {hint}"

    system_prompt = (
        "You are an OCR + entity-extraction engine for Indian identity "
        "and compliance documents. You are given a photo/scan of the "
        "document. Read every character you can (English AND Devanagari "
        "Hindi) and return ONLY a JSON object matching the requested "
        "schema. Never wrap the JSON in prose or code fences. Never "
        "hallucinate — if a field is not visibly present, set it to null. "
        "Trim whitespace from every string. Uppercase PAN numbers. "
        "Remove spaces from Aadhaar / voter-id / license numbers."
    )

    user_text = (
        f"{prompt_body}\n\n"
        + (
            f"You are given {len(image_pages)} images — they are pages/sides "
            "of the SAME document (e.g. front and back). Read ALL of them "
            "and merge the fields into one result.\n\n"
            if len(image_pages) > 1 else ""
        )
        + "Return JSON with this exact shape:\n"
        "{\n"
        '  "document_type_detected": "aadhaar|pan|voter|passport|driving_license|firm_pan|firm_compliance|other",\n'
        '  "confidence": "high|medium|low",\n'
        '  "fields": { ... requested keys ... },\n'
        '  "raw_text": "the full text you read, line-separated"\n'
        "}"
    )

    try:
        from emergentintegrations.llm.chat import (
            LlmChat, UserMessage, ImageContent,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"emergentintegrations not available: {exc}",
        )

    chat = LlmChat(
        api_key=api_key,
        session_id=f"ocr-{admin['user_id']}",
        system_message=system_prompt,
    ).with_model("openai", "gpt-5.4")

    try:
        response = await chat.send_message(
            UserMessage(
                text=user_text,
                file_contents=[
                    ImageContent(image_base64=b64) for b64 in image_pages
                ],
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[ocr] LLM call failed")
        raise HTTPException(status_code=502, detail=f"OCR failed: {exc}")

    # Response is a string of JSON — parse defensively
    text = (response or "").strip()
    if text.startswith("```"):
        # Strip code fences if the model returned them despite instructions
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Return the raw text so the UI can at least show it
        return {
            "ok": False,
            "error": "LLM returned non-JSON output — please try again.",
            "raw_text": text[:4000],
        }

    fields = parsed.get("fields") or {}
    # Post-process: normalise Aadhaar / PAN / voter formatting
    if fields.get("aadhaar_no"):
        fields["aadhaar_no"] = "".join(ch for ch in str(fields["aadhaar_no"]) if ch.isdigit())[:12]
    if fields.get("pan_no"):
        fields["pan_no"] = str(fields["pan_no"]).upper().replace(" ", "")
    if fields.get("voter_id"):
        fields["voter_id"] = str(fields["voter_id"]).upper().replace(" ", "")

    logger.info(
        "[ocr] parsed doc_type=%s -> detected=%s confidence=%s by %s",
        doc_type,
        parsed.get("document_type_detected"),
        parsed.get("confidence"),
        admin["user_id"],
    )
    return {
        "ok": True,
        "document_type_detected": parsed.get("document_type_detected"),
        "confidence": parsed.get("confidence"),
        "fields": fields,
        "raw_text": parsed.get("raw_text"),
    }
