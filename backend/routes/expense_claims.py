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
APPROVER_ROLES = ADMIN_ROLES + ["hr_manager", "manager", "accounts", "finance"]
PENDING_STAGES = ["pending_manager", "pending_accounts", "pending_finance"]


def _scope_cid(user: dict, company_id: Optional[str]) -> Optional[str]:
    """Admin roles (super/sub admins) may pass an explicit company_id;
    everyone else is locked to their own firm."""
    if user.get("role") in ("super_admin", "sub_admin") and company_id:
        return company_id
    return user.get("company_id") or company_id


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
async def list_categories(company_id: Optional[str] = Query(None),
                          include_inactive: int = Query(0),
                          authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    cid = _scope_cid(user, company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="No firm scope")
    await _seed_categories(cid)
    q: dict = {"company_id": cid}
    if not include_inactive:
        q["active"] = True
    rows = await db.expense_categories.find(q, {"_id": 0}).sort(
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
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    q: dict = {"company_id": _scope_cid(user, company_id)}
    if scope == "approvals" and user.get("role") in APPROVER_ROLES:
        # Approver queue — pending claims for the firm (self-approval is
        # still blocked at action time).
        q["status"] = status if status else {"$in": PENDING_STAGES}
        if user.get("role") == "super_admin" and not q["company_id"]:
            q.pop("company_id")
    elif scope == "all" and user.get("role") in ADMIN_ROLES:
        if status:
            q["status"] = status
        if user.get("role") == "super_admin" and not q["company_id"]:
            q.pop("company_id")
    else:
        q["user_id"] = user["user_id"]
        if status:
            q["status"] = status
    rows = await db.expense_claims.find(
        q, {"_id": 0, "attachments.data_b64": 0}).sort(
        "created_at", -1).to_list(300)
    return {"claims": rows}


@router.get("/claims/{claim_id}")
async def get_claim(claim_id: str, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    c = await db.expense_claims.find_one(
        {"claim_id": claim_id}, {"_id": 0, "attachments.data_b64": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Claim not found")
    if c["user_id"] != user["user_id"] and user.get("role") not in APPROVER_ROLES:
        raise HTTPException(status_code=403, detail="Not allowed")
    return {"claim": c}


EDITABLE_FIELDS = ("expense_date", "category_id", "category_name", "vendor",
                   "invoice_no", "project", "client", "payment_mode",
                   "amount", "gst_amount", "description")


@router.put("/claims/{claim_id}")
async def update_claim(claim_id: str, payload: Dict[str, Any] = Body(...),
                       authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    c = await db.expense_claims.find_one(
        {"claim_id": claim_id, "user_id": user["user_id"]},
        {"_id": 0, "status": 1})
    if not c:
        raise HTTPException(status_code=404, detail="Claim not found")
    if c["status"] not in ("draft", "returned"):
        raise HTTPException(status_code=400,
                            detail="Only draft/returned claims can be edited")
    upd = {k: payload[k] for k in EDITABLE_FIELDS if k in payload}
    if "amount" in upd:
        upd["amount"] = float(upd["amount"] or 0)
        if upd["amount"] <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
    if "gst_amount" in upd:
        upd["gst_amount"] = float(upd["gst_amount"] or 0)
    if "description" in upd:
        upd["description"] = str(upd["description"] or "")[:600]
    upd["updated_at"] = now_iso()
    await db.expense_claims.update_one({"claim_id": claim_id}, {"$set": upd})
    await _audit(user, claim_id, "edited", None, upd)
    return {"ok": True}


@router.post("/claims/{claim_id}/cancel")
async def cancel_claim(claim_id: str,
                       authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    c = await db.expense_claims.find_one(
        {"claim_id": claim_id, "user_id": user["user_id"]},
        {"_id": 0, "status": 1})
    if not c:
        raise HTTPException(status_code=404, detail="Claim not found")
    if c["status"] not in ("draft", "returned", "pending_manager"):
        raise HTTPException(status_code=400,
                            detail=f"Cannot cancel a {c['status']} claim")
    await db.expense_claims.update_one(
        {"claim_id": claim_id},
        {"$set": {"status": "cancelled", "updated_at": now_iso()}})
    await _audit(user, claim_id, "cancelled", c["status"], "cancelled")
    return {"ok": True}


@router.get("/reports")
async def expense_reports(month: str = Query(...),
                          company_id: Optional[str] = Query(None),
                          authorization: Optional[str] = Header(None)):
    """Phase 4 — month summary: by status / category / employee."""
    user = await get_user_from_token(authorization)
    require_role(user, APPROVER_ROLES)
    q: dict = {"expense_date": {"$regex": f"^{month}"},
               "status": {"$ne": "cancelled"}}
    cid = _scope_cid(user, company_id)
    if cid:
        q["company_id"] = cid
    rows = await db.expense_claims.find(
        q, {"_id": 0, "attachments": 0}).to_list(3000)
    by_status: Dict[str, dict] = {}
    by_cat: Dict[str, dict] = {}
    by_emp: Dict[str, dict] = {}
    for r in rows:
        amt = float(r.get("amount") or 0)
        paid = float(r.get("paid_amount") or 0)
        s = by_status.setdefault(r["status"], {"count": 0, "amount": 0.0})
        s["count"] += 1; s["amount"] += amt
        cat = r.get("category_name") or "Uncategorised"
        crow = by_cat.setdefault(cat, {"count": 0, "amount": 0.0, "paid": 0.0})
        crow["count"] += 1; crow["amount"] += amt; crow["paid"] += paid
        emp = (r.get("employee") or {})
        key = r["user_id"]
        erow = by_emp.setdefault(key, {
            "name": emp.get("name") or "—",
            "employee_code": emp.get("employee_code") or "",
            "count": 0, "amount": 0.0, "paid": 0.0})
        erow["count"] += 1; erow["amount"] += amt; erow["paid"] += paid
    rnd = lambda d: {k: (round(v, 2) if isinstance(v, float) else v)  # noqa: E731
                     for k, v in d.items()}
    return {"month": month, "total_claims": len(rows),
            "total_amount": round(sum(float(r.get("amount") or 0) for r in rows), 2),
            "total_paid": round(sum(float(r.get("paid_amount") or 0)
                                    for r in rows if r["status"] == "paid"), 2),
            "by_status": {k: rnd(v) for k, v in by_status.items()},
            "by_category": [dict(name=k, **rnd(v))
                            for k, v in sorted(by_cat.items(),
                                               key=lambda x: -x[1]["amount"])],
            "by_employee": sorted([rnd(v) for v in by_emp.values()],
                                  key=lambda x: -x["amount"])}


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


@router.post("/claims/{claim_id}/action")
async def claim_action(claim_id: str,
                       payload: Dict[str, Any] = Body(...),
                       authorization: Optional[str] = Header(None)):
    """Phase 2 — approval workflow: Manager → Accounts → Finance.
    Actions: approve | reject | return. NO SELF-APPROVAL. Admin roles can
    act at any stage (small firms); remarks stored + audit-logged."""
    user = await get_user_from_token(authorization)
    require_role(user, ADMIN_ROLES + ["hr_manager", "manager", "accounts", "finance"])
    c = await db.expense_claims.find_one({"claim_id": claim_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Claim not found")
    if c.get("company_id") != user.get("company_id") and user["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="Not your company's claim")
    if c["user_id"] == user["user_id"]:
        raise HTTPException(status_code=403, detail="Self-approval is not allowed")
    action = str(payload.get("action") or "")
    remarks = str(payload.get("remarks") or "")[:400]
    stage = c["status"]
    CHAIN = {"pending_manager": "pending_accounts",
             "pending_accounts": "pending_finance",
             "pending_finance": "approved"}
    if stage not in CHAIN:
        raise HTTPException(status_code=400, detail=f"No pending action on a {stage} claim")
    if action == "approve":
        new_status = CHAIN[stage]
        upd: dict = {"status": new_status}
        if new_status == "approved":
            upd["approved_amount"] = float(payload.get("approved_amount")
                                           or c.get("amount") or 0)
            upd["approved_at"] = now_iso()
        if stage == "pending_accounts" and "gst_eligible" in payload:
            upd["gst_eligible"] = bool(payload.get("gst_eligible"))
    elif action == "reject":
        new_status = "rejected"; upd = {"status": "rejected", "rejected_at": now_iso()}
    elif action == "return":
        new_status = "returned"; upd = {"status": "returned"}
    else:
        raise HTTPException(status_code=400, detail="action must be approve/reject/return")
    upd["updated_at"] = now_iso()
    await db.expense_claims.update_one(
        {"claim_id": claim_id},
        {"$set": upd,
         "$push": {"approvals": {"stage": stage, "action": action,
                                 "by": user["user_id"], "by_name": user.get("name"),
                                 "role": user.get("role"), "remarks": remarks,
                                 "at": now_iso()}}})
    await _audit(user, claim_id, f"{stage}:{action}", stage, new_status, remarks)
    return {"ok": True, "status": new_status}


@router.post("/claims/{claim_id}/payment")
async def claim_payment(claim_id: str,
                        payload: Dict[str, Any] = Body(...),
                        authorization: Optional[str] = Header(None)):
    """Phase 3 — Finance payment. Only APPROVED claims can be paid;
    PAID claims become immutable."""
    user = await get_user_from_token(authorization)
    require_role(user, ADMIN_ROLES + ["finance"])
    c = await db.expense_claims.find_one({"claim_id": claim_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Claim not found")
    if c["user_id"] == user["user_id"]:
        raise HTTPException(status_code=403, detail="Self-payment is not allowed")
    if c["status"] not in ("approved", "payment_pending", "processing"):
        raise HTTPException(status_code=400,
                            detail="Payment allowed only after final approval")
    mode = str(payload.get("payment_mode") or "bank_transfer")
    paid_amount = float(payload.get("paid_amount")
                        or c.get("approved_amount") or c.get("amount") or 0)
    upd = {"status": "paid", "paid_amount": paid_amount,
           "payment_mode": mode,
           "payment_date": str(payload.get("payment_date") or now_iso()[:10]),
           "payment_reference": str(payload.get("payment_reference") or "")[:120],
           "reimburse_via_payroll": mode == "payroll",
           "paid_by": user["user_id"], "paid_at": now_iso(),
           "updated_at": now_iso()}
    await db.expense_claims.update_one({"claim_id": claim_id}, {"$set": upd})
    await _audit(user, claim_id, "paid", c["status"], "paid",
                 f"{mode} ₹{paid_amount}")
    return {"ok": True, "status": "paid", "paid_amount": paid_amount}


@router.get("/payroll-reimbursements")
async def payroll_reimbursements(
    month: str = Query(...), company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Phase 3 — payroll integration feed: PAID claims flagged
    reimburse_via_payroll for the month, kept SEPARATE from wages
    (per-employee 'Expense Reimbursement' head)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ADMIN_ROLES)
    cid = admin["company_id"] if admin["role"] == "company_admin" else company_id
    q: dict = {"status": "paid", "reimburse_via_payroll": True,
               "payment_date": {"$regex": f"^{month}"}}
    if cid:
        q["company_id"] = cid
    rows = await db.expense_claims.find(
        q, {"_id": 0, "attachments": 0}).to_list(2000)
    per: Dict[str, float] = {}
    for r in rows:
        per[r["user_id"]] = per.get(r["user_id"], 0) + float(r.get("paid_amount") or 0)
    return {"month": month, "head": "Expense Reimbursement",
            "per_employee": [{"user_id": k, "amount": round(v, 2)} for k, v in per.items()],
            "claims": rows}


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
