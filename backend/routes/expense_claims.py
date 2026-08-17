"""Iter 604 — EXPENSE CLAIMS module Phase 1 (user spec, 29-section brief).

Phase 1 scope: categories master (seeded defaults, admin-editable),
claim CRUD (draft → submit), receipt attachments (base64 in Mongo, type/
size validated, auth-gated download), duplicate detection, AI OCR receipt
extraction (Emergent LLM key, gpt-5.4 vision — extraction only, NEVER
auto-approves), employee dashboard counts, audit trail.
Reuses existing users/companies masters — no duplicate tables.
Approval workflow / policy engine / payments = Phases 2-3.
"""
import base64
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import Response

from server import db, get_user_from_token, require_role, now_iso, logger  # noqa: E402

router = APIRouter(prefix="/api/expense", tags=["expense-claims"])

ADMIN_ROLES = ["super_admin", "company_admin", "sub_admin"]
ALLOWED_MIME = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}
MAX_FILE_MB = 5
DEFAULT_CATEGORIES = [
    ("Travel", ["Bus", "Train", "Flight", "Taxi/Cab", "Auto", "Fuel", "Toll",
                "Parking", "Local Conveyance"]),
    ("Food", ["Breakfast", "Lunch", "Dinner", "Refreshment", "Client Meeting"]),
    ("Accommodation", ["Hotel", "Guest House", "Lodging"]),
    ("Office", ["Stationery", "Printing", "Courier", "Internet", "Mobile", "Software"]),
    ("Client / Business", ["Client Entertainment", "Client Meeting",
                           "Business Promotion", "Gifts", "Event"]),
    ("Other", ["Medical", "Training", "Uniform", "Safety Equipment", "Miscellaneous"]),
]
STATUSES = ["draft", "submitted", "pending_manager", "pending_accounts",
            "pending_finance", "returned", "rejected", "approved",
            "payment_pending", "processing", "paid", "cancelled"]


async def _audit(user: dict, claim_id: str, action: str,
                 old: Any = None, new: Any = None, remarks: str = ""):
    try:
        await db.expense_audit.insert_one({
            "audit_id": f"exa_{uuid.uuid4().hex[:12]}", "claim_id": claim_id,
            "user_id": user.get("user_id"), "name": user.get("name"),
            "role": user.get("role"), "action": action,
            "old": old, "new": new, "remarks": remarks, "at": now_iso()})
    except Exception:
        logger.exception("[expense] audit failed")


async def _seed_categories(company_id: str):
    if await db.expense_categories.count_documents({"company_id": company_id}) > 0:
        return
    docs = []
    for group, subs in DEFAULT_CATEGORIES:
        for s in subs:
            docs.append({"category_id": f"exc_{uuid.uuid4().hex[:10]}",
                         "company_id": company_id, "group": group, "name": s,
                         "active": True, "created_at": now_iso()})
    await db.expense_categories.insert_many(docs)


@router.get("/categories")
async def list_categories(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(status_code=400, detail="No firm scope")
    await _seed_categories(cid)
    rows = await db.expense_categories.find(
        {"company_id": cid, "active": True}, {"_id": 0}).sort(
        [("group", 1), ("name", 1)]).to_list(500)
    return {"categories": rows}


@router.post("/categories")
async def upsert_category(payload: Dict[str, Any] = Body(...),
                          authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ADMIN_ROLES)
    cid = str(payload.get("company_id") or user.get("company_id") or "")
    catid = payload.get("category_id")
    if catid:  # edit / deactivate
        upd = {k: payload[k] for k in ("name", "group", "active") if k in payload}
        r = await db.expense_categories.update_one(
            {"category_id": catid, "company_id": cid}, {"$set": upd})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Category not found")
        return {"ok": True}
    doc = {"category_id": f"exc_{uuid.uuid4().hex[:10]}", "company_id": cid,
           "group": str(payload.get("group") or "Other"),
           "name": str(payload.get("name") or "").strip(),
           "active": True, "created_at": now_iso()}
    if not doc["name"]:
        raise HTTPException(status_code=400, detail="name required")
    await db.expense_categories.insert_one(doc)
    return {"ok": True, "category_id": doc["category_id"]}


async def _next_claim_no(cid: str, month_key: str) -> str:
    n = await db.expense_claims.count_documents(
        {"company_id": cid, "claim_no": {"$regex": f"^EC{month_key}"}})
    return f"EC{month_key}-{n + 1:04d}"


@router.post("/claims")
async def create_claim(payload: Dict[str, Any] = Body(...),
                       authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    cid = user.get("company_id")
    amount = float(payload.get("amount") or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    from datetime import datetime, timezone
    mk = datetime.now(timezone.utc).strftime("%y%m")
    claim = {
        "claim_id": f"exp_{uuid.uuid4().hex[:12]}",
        "claim_no": await _next_claim_no(cid, mk),
        "client_txn_id": payload.get("client_txn_id"),  # offline idempotency
        "user_id": user["user_id"], "company_id": cid,
        # snapshot from Employee Master (read-only on the form)
        "employee": {k: user.get(k) for k in
                     ("name", "employee_code", "department", "designation",
                      "branch", "reporting_manager", "cost_center")},
        "expense_date": str(payload.get("expense_date") or ""),
        "category_id": payload.get("category_id"),
        "category_name": payload.get("category_name"),
        "vendor": str(payload.get("vendor") or ""),
        "invoice_no": str(payload.get("invoice_no") or ""),
        "project": payload.get("project"), "client": payload.get("client"),
        "payment_mode": payload.get("payment_mode"),
        "currency": payload.get("currency") or "INR",
        "amount": amount,
        "gst_amount": float(payload.get("gst_amount") or 0),
        "description": str(payload.get("description") or "")[:600],
        "status": "draft", "approved_amount": None, "paid_amount": None,
        "attachments": [], "created_at": now_iso(), "updated_at": now_iso(),
    }
    # offline idempotency — same client_txn_id never duplicates
    if claim["client_txn_id"]:
        dup = await db.expense_claims.find_one(
            {"user_id": user["user_id"], "client_txn_id": claim["client_txn_id"]},
            {"_id": 0, "claim_id": 1})
        if dup:
            return {"ok": True, "claim_id": dup["claim_id"], "deduped": True}
    await db.expense_claims.insert_one({k: v for k, v in claim.items()})
    await _audit(user, claim["claim_id"], "created", None,
                 {"amount": amount, "claim_no": claim["claim_no"]})
    claim.pop("_id", None)
    return {"ok": True, "claim": claim}


@router.get("/claims")
async def list_claims(
    scope: str = Query("mine"), status: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    q: dict = {"company_id": user.get("company_id")}
    if scope == "mine" or user.get("role") == "employee":
        q["user_id"] = user["user_id"]
    elif user.get("role") not in ADMIN_ROLES:
        q["user_id"] = user["user_id"]
    if status:
        q["status"] = status
    rows = await db.expense_claims.find(
        q, {"_id": 0, "attachments.data_b64": 0}).sort(
        "created_at", -1).to_list(300)
    return {"claims": rows}


@router.get("/dashboard")
async def expense_dashboard(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    q = {"user_id": user["user_id"], "company_id": user.get("company_id")}
    rows = await db.expense_claims.find(
        q, {"_id": 0, "status": 1, "amount": 1, "approved_amount": 1,
            "paid_amount": 1}).to_list(2000)
    def tot(f, sts=None):
        return round(sum(float(r.get(f) or 0) for r in rows
                         if sts is None or r["status"] in sts), 2)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    return {"counts": counts, "total_claims": len(rows),
            "total_claimed": tot("amount"),
            "total_approved": tot("approved_amount"),
            "total_paid": tot("paid_amount", ["paid"]),
            "outstanding": round(tot("approved_amount") - tot("paid_amount", ["paid"]), 2)}


@router.post("/claims/{claim_id}/submit")
async def submit_claim(claim_id: str,
                       payload: Dict[str, Any] = Body(default={}),
                       authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    c = await db.expense_claims.find_one(
        {"claim_id": claim_id, "user_id": user["user_id"]}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Claim not found")
    if c["status"] not in ("draft", "returned"):
        raise HTTPException(status_code=400, detail=f"Cannot submit a {c['status']} claim")
    # Duplicate detection — employee + date + amount (+ vendor/invoice).
    dupq = {"user_id": user["user_id"], "claim_id": {"$ne": claim_id},
            "status": {"$nin": ["rejected", "cancelled"]},
            "expense_date": c.get("expense_date"), "amount": c.get("amount")}
    dup = await db.expense_claims.find_one(dupq, {"_id": 0, "claim_no": 1})
    if not dup and c.get("invoice_no"):
        dup = await db.expense_claims.find_one(
            {"user_id": user["user_id"], "claim_id": {"$ne": claim_id},
             "invoice_no": c["invoice_no"], "vendor": c.get("vendor"),
             "status": {"$nin": ["rejected", "cancelled"]}},
            {"_id": 0, "claim_no": 1})
    if dup and not payload.get("confirm_duplicate"):
        raise HTTPException(
            status_code=409,
            detail=f"Potential duplicate of claim {dup['claim_no']} — confirm "
                   "to submit anyway.")
    await db.expense_claims.update_one(
        {"claim_id": claim_id},
        {"$set": {"status": "pending_manager", "submitted_at": now_iso(),
                  "updated_at": now_iso(),
                  "duplicate_confirmed": bool(dup)}})
    await _audit(user, claim_id, "submitted", c["status"], "pending_manager")
    return {"ok": True, "status": "pending_manager"}


@router.post("/claims/{claim_id}/attachments")
async def add_attachment(claim_id: str,
                         payload: Dict[str, Any] = Body(...),
                         authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    c = await db.expense_claims.find_one(
        {"claim_id": claim_id, "user_id": user["user_id"]},
        {"_id": 0, "status": 1})
    if not c:
        raise HTTPException(status_code=404, detail="Claim not found")
    if c["status"] in ("paid", "cancelled"):
        raise HTTPException(status_code=400, detail="Claim can no longer be edited")
    mime = str(payload.get("mime") or "")
    if mime not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Only PDF/JPG/PNG allowed")
    data = str(payload.get("data_b64") or "")
    if "," in data[:80]:
        data = data.split(",", 1)[1]
    size = int(len(data) * 3 / 4)
    if size > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large (max {MAX_FILE_MB} MB)")
    att = {"doc_id": f"exd_{uuid.uuid4().hex[:10]}",
           "file_name": str(payload.get("file_name") or f"receipt{ALLOWED_MIME[mime]}")[:120],
           "mime": mime, "size": size, "uploaded_by": user["user_id"],
           "uploaded_at": now_iso(), "data_b64": data}
    await db.expense_claims.update_one(
        {"claim_id": claim_id},
        {"$push": {"attachments": att}, "$set": {"updated_at": now_iso()}})
    await _audit(user, claim_id, "receipt_uploaded", None,
                 {"file": att["file_name"], "size": size})
    return {"ok": True, "doc_id": att["doc_id"]}


@router.get("/claims/{claim_id}/attachments/{doc_id}")
async def get_attachment(claim_id: str, doc_id: str,
                         authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    c = await db.expense_claims.find_one({"claim_id": claim_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Claim not found")
    if c["user_id"] != user["user_id"] and user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not allowed")
    att = next((a for a in c.get("attachments", []) if a["doc_id"] == doc_id), None)
    if not att:
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(content=base64.b64decode(att["data_b64"]),
                    media_type=att["mime"],
                    headers={"Content-Disposition":
                             f'inline; filename="{att["file_name"]}"'})


@router.post("/ocr")
async def ocr_receipt(payload: Dict[str, Any] = Body(...),
                      authorization: Optional[str] = Header(None)):
    """AI vision extraction from a receipt image — SUGGESTION ONLY, the
    employee confirms values before saving. Never auto-approves anything."""
    await get_user_from_token(authorization)
    img = str(payload.get("image_b64") or "")
    if "," in img[:80]:
        img = img.split(",", 1)[1]
    if not img:
        raise HTTPException(status_code=400, detail="image_b64 required")
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    key = os.environ.get("EMERGENT_LLM_KEY", "")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
        chat = LlmChat(api_key=key, session_id=f"ocr_{uuid.uuid4().hex[:8]}",
                       system_message="You extract fields from expense receipts. "
                                      "Reply with STRICT JSON only.").with_model("openai", "gpt-5.4")
        resp = await chat.send_message(UserMessage(
            text='Extract from this receipt as JSON: {"vendor":"","invoice_no":"",'
                 '"invoice_date":"YYYY-MM-DD","total_amount":0,"gst_amount":0}. '
                 'Use null when unreadable. JSON only, no markdown.',
            file_contents=[ImageContent(image_base64=img)]))
        import json as _json, re as _re
        m = _re.search(r"\{.*\}", str(resp), _re.S)
        data = _json.loads(m.group(0)) if m else {}
        return {"ok": True, "extracted": data}
    except Exception as e:
        logger.warning("[expense-ocr] failed: %s", e)
        raise HTTPException(status_code=502, detail="OCR extraction failed — fill fields manually")


@router.get("/claims/{claim_id}/audit")
async def claim_audit(claim_id: str, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    c = await db.expense_claims.find_one({"claim_id": claim_id}, {"_id": 0, "user_id": 1})
    if not c:
        raise HTTPException(status_code=404, detail="Claim not found")
    if c["user_id"] != user["user_id"] and user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not allowed")
    rows = await db.expense_audit.find(
        {"claim_id": claim_id}, {"_id": 0}).sort("at", 1).to_list(200)
    return {"audit": rows}
