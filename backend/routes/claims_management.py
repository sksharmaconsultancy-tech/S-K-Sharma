"""Iter 359 — PF & ESIC Claims Management System.

Full claim lifecycle (application → settlement) linked to Employee Master.
Collection: pf_esic_claims {claim_id, claim_no, claim_kind: pf|esic, data{},
status, timeline[], ai_flags[], company_id, ...}

  GET  /api/admin/claims/meta        (types, statuses, document checklists)
  GET  /api/admin/claims             (filters: claim_kind,status,claim_type,
                                      company_id,q,fy_start_year,executive)
  POST /api/admin/claims             (create/update; timeline + AI checks)
  DELETE /api/admin/claims/{claim_id}
  GET  /api/admin/claims/dashboard
  GET  /api/admin/claims/report/{kind}[.xlsx|.pdf]
"""
import base64
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import StreamingResponse

from server import db, get_user_from_token, require_role  # noqa: E402
from utils.register_export import register_pdf, register_xlsx  # noqa: E402
from routes.labour_statistics import _company, _dt, _f  # noqa: E402

router = APIRouter(prefix="/api/admin/claims", tags=["claims"])

PF_TYPES = ["Final Settlement (Form-19)", "Pension Withdrawal (Form-10C)",
            # Iter 382 (user request) — Form-10D pension, Form 20/5-IF
            # death claims and the Composite Claim Form filing entry.
            "Pension (Form-10D)", "Death Claim (Form-20 / 5-IF)",
            "Composite Claim Form",
            "Partial Withdrawal (Form-31)", "Advance", "Transfer Claim",
            "Higher Pension", "Death Claim", "Nominee Claim", "KYC Update",
            "Bank Correction", "Name Correction", "DOB Correction",
            "Father Name Correction", "Mobile Update", "Email Update",
            "Joint Declaration"]
ESIC_TYPES = ["Sickness Benefit", "Extended Sickness Benefit",
              "Enhanced Sickness Benefit", "Maternity Benefit",
              "Temporary Disablement Benefit",
              "Permanent Disablement Benefit", "Dependants Benefit",
              "Funeral Expenses", "Medical Reimbursement",
              "Unemployment Allowance", "Atal Beemit Vyakti Kalyan"]
PF_STATUSES = ["Pending", "Submitted", "Under Process", "Approved",
               "Rejected", "Settled"]
ESIC_STATUSES = ["Pending", "Submitted", "Verified", "Under Process",
                 "Approved", "Rejected", "Settled"]
DOC_CHECKLIST = {
    "pf": ["Form (signed)", "Cancelled Cheque / Passbook", "Aadhaar",
           "PAN", "Bank KYC verified on UAN", "Date of Exit updated",
           "Joint Declaration (if correction)"],
    "esic": ["Claim Form", "Medical Certificate", "Aadhaar",
             "Bank Details", "Hospital Papers / Bills",
             "Employer Certificate"],
}


async def _adm(authorization, company_id=None):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    return admin, company_id


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _ai_checks(claim: dict) -> List[str]:
    flags: List[str] = []
    d = claim.get("data") or {}
    kind = claim.get("claim_kind")
    ctype = str(d.get("claim_type") or "")
    doj, dol = _dt(d.get("doj")), _dt(d.get("dol"))
    svc_yrs = ((dol or date.today()) - doj).days / 365 if doj else None
    if kind == "pf":
        uan = str(d.get("uan") or "").strip()
        if not uan:
            flags.append("Missing UAN number")
        elif not (uan.isdigit() and len(uan) == 12):
            flags.append(f"UAN '{uan}' looks invalid (must be 12 digits)")
        if "Form-19" in ctype and not d.get("dol"):
            flags.append("Final Settlement needs Date of Leaving")
        # Eligibility checker (service period rules)
        if svc_yrs is not None:
            if "Form-10C" in ctype and svc_yrs >= 9.5:
                flags.append("ELIGIBILITY: 10+ yrs service — Form-10C "
                             "withdrawal not allowed, member gets pension "
                             "(use Form-10D)")
            if "Form-10C" in ctype and svc_yrs < 0.5:
                flags.append("ELIGIBILITY: less than 6 months service — "
                             "pension withdrawal not eligible")
            if "Form-19" in ctype and svc_yrs < 5:
                flags.append("ELIGIBILITY: service < 5 yrs — TDS applicable "
                             "on PF settlement (submit 15G/15H if eligible)")
    else:
        ip = str(d.get("insurance_no") or "").strip()
        if not ip:
            flags.append("Missing ESIC Insurance number")
        elif not (ip.isdigit() and len(ip) in (10, 17)):
            flags.append(f"IP number '{ip}' looks invalid")
        # contribution-history eligibility (needs salary runs with ESIC)
        code = str(d.get("employee_code") or "").strip()
        comp = claim.get("company_id")
        if code and comp and comp != "external" and \
                "Sickness" in ctype:
            paid = 0
            async for run in db.compliance_salary_runs.find(
                    {"company_id": comp}, {"_id": 0, "rows": 1}).sort(
                    "month", -1).limit(9):
                for r in run.get("rows") or []:
                    if str(r.get("employee_code")) == code and \
                            _f(r.get("esic_employee")) > 0:
                        paid += 1
                        break
            if paid < 4:
                flags.append(f"ELIGIBILITY: only {paid} months of ESIC "
                             "contribution found in last 9 months — Sickness "
                             "Benefit needs 78 days contribution in the "
                             "contribution period")
    docs = claim.get("documents") or {}
    missing = [k for k in DOC_CHECKLIST[kind] if not docs.get(k)]
    if missing and claim.get("status") in ("Submitted", "Under Process"):
        flags.append("Missing documents: " + ", ".join(missing[:4]))
    # duplicate open claim
    dup = await db.pf_esic_claims.find_one({
        "claim_id": {"$ne": claim.get("claim_id")},
        "claim_kind": kind, "company_id": claim.get("company_id"),
        "data.employee_code": d.get("employee_code"),
        "data.claim_type": d.get("claim_type"),
        "status": {"$nin": ["Settled", "Rejected"]}}, {"_id": 0,
                                                       "claim_no": 1})
    if dup and d.get("employee_code"):
        flags.append(f"Possible duplicate of open claim {dup['claim_no']}")
    return flags


def _doc_score(claim: dict) -> int:
    """Document Completeness Score (0-100)."""
    checklist = DOC_CHECKLIST[claim["claim_kind"]]
    docs = claim.get("documents") or {}
    done = sum(1 for k in checklist if docs.get(k))
    return round(done * 100 / len(checklist))


async def _expected_settlement(claim: dict) -> Optional[str]:
    """Predict settlement date from historical settled claims."""
    q = {"claim_kind": claim["claim_kind"], "status": "Settled"}
    days: List[int] = []
    async for c in db.pf_esic_claims.find(q, {"_id": 0, "data": 1}).limit(200):
        ad = _dt((c.get("data") or {}).get("application_date"))
        sd = _dt((c.get("data") or {}).get("settlement_date"))
        if ad and sd and 0 <= (sd - ad).days <= 365:
            days.append((sd - ad).days)
    avg = (sum(days) / len(days)) if days else (
        20 if claim["claim_kind"] == "pf" else 30)
    ad = _dt((claim.get("data") or {}).get("application_date")) or date.today()
    return (ad + timedelta(days=int(avg))).isoformat()


@router.get("/meta")
async def meta(authorization: Optional[str] = Header(None)):
    await _adm(authorization)
    return {"pf_types": PF_TYPES, "esic_types": ESIC_TYPES,
            "pf_statuses": PF_STATUSES, "esic_statuses": ESIC_STATUSES,
            "doc_checklist": DOC_CHECKLIST}


@router.get("/employees")
async def claim_employees(company_id: str,
                          authorization: Optional[str] = Header(None)):
    """Employee picker for the claim form (user request).

    Returns every employee of the firm with a ``left`` flag so the UI can
    show ONLY left/resigned employees for PF Form-19 / Form-10C claims and
    the full list (active + resigned) for every other claim type."""
    _admin, cid = await _adm(authorization, company_id)
    company_id = cid or company_id
    if not company_id or company_id == "external":
        return {"employees": []}
    out: List[dict] = []
    async for u in db.users.find(
            {"role": "employee", "company_id": company_id},
            {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
             "uan_no": 1, "esi_ip_no": 1, "pf_no": 1, "department": 1,
             "designation": 1, "position": 1, "phone": 1, "doj": 1,
             "exit_date": 1,
             "resign_date": 1, "date_of_leaving": 1, "leaving_date": 1,
             "employment_status": 1, "active": 1, "disabled": 1}):
        dol = ""
        for k in ("exit_date", "resign_date", "date_of_leaving",
                  "leaving_date"):
            v = str(u.get(k) or "").strip()
            if v:
                dol = v[:10]
                break
        left = bool(dol) or \
            str(u.get("employment_status") or "").lower() in (
                "resigned", "exited", "left", "terminated", "inactive") or \
            u.get("active") is False or u.get("disabled") is True
        out.append({
            "user_id": u["user_id"],
            "employee_code": u.get("employee_code") or "",
            "name": u.get("name") or "",
            "uan_no": u.get("uan_no") or "",
            "esi_ip_no": u.get("esi_ip_no") or "",
            "pf_no": u.get("pf_no") or "",
            "department": u.get("department") or "",
            "designation": u.get("designation") or u.get("position") or "",
            "phone": u.get("phone") or "",
            "doj": str(u.get("doj") or "")[:10],
            "dol": dol,
            "left": left,
        })
    out.sort(key=lambda e: (e.get("name") or "").lower())
    return {"employees": out, "left_count": sum(1 for e in out if e["left"])}


@router.get("/dashboard")
async def dashboard(company_id: Optional[str] = None,
                    authorization: Optional[str] = Header(None)):
    _admin, company_id = await _adm(authorization, company_id)
    q: Dict[str, Any] = {}
    if company_id:
        q["company_id"] = company_id
    claims = await db.pf_esic_claims.find(q, {"_id": 0}).to_list(20000)
    today = date.today()
    week = today + timedelta(days=7)
    month_end = today + timedelta(days=30)
    out = {"total_pf": 0, "total_esic": 0, "pending": 0, "approved": 0,
           "rejected": 0, "settled": 0, "claim_amount": 0.0,
           "settlement_amount": 0.0, "due_today": 0, "due_week": 0,
           "due_month": 0}
    proc_days: List[int] = []
    for c in claims:
        out["total_pf" if c["claim_kind"] == "pf" else "total_esic"] += 1
        s = c.get("status")
        if s in ("Pending", "Submitted", "Under Process", "Verified"):
            out["pending"] += 1
        elif s == "Approved":
            out["approved"] += 1
        elif s == "Rejected":
            out["rejected"] += 1
        elif s == "Settled":
            out["settled"] += 1
            ad = _dt((c.get("data") or {}).get("application_date"))
            sd = _dt((c.get("data") or {}).get("settlement_date"))
            if ad and sd:
                proc_days.append((sd - ad).days)
        out["claim_amount"] += _f((c.get("data") or {}).get("claim_amount"))
        if s == "Settled":
            out["settlement_amount"] += _f(
                (c.get("data") or {}).get("claim_amount"))
        fu = _dt((c.get("data") or {}).get("follow_up_date"))
        if fu and s not in ("Settled", "Rejected"):
            if fu <= today:
                out["due_today"] += 1
            if fu <= week:
                out["due_week"] += 1
            if fu <= month_end:
                out["due_month"] += 1
    out["claim_amount"] = round(out["claim_amount"], 2)
    out["settlement_amount"] = round(out["settlement_amount"], 2)
    out["avg_processing_days"] = (round(sum(proc_days) / len(proc_days), 1)
                                  if proc_days else 0)
    return out


@router.get("")
async def list_claims(claim_kind: str = "pf", status: str = "",
                      claim_type: str = "", q: str = "",
                      executive: str = "", company_id: Optional[str] = None,
                      date_from: str = "", date_to: str = "",
                      sort: str = "date_desc",
                      limit: int = 200,
                      authorization: Optional[str] = Header(None)):
    _admin, company_id = await _adm(authorization, company_id)
    qq: Dict[str, Any] = {"claim_kind": claim_kind}
    if company_id:
        qq["company_id"] = company_id
    if status:
        qq["status"] = status
    if claim_type:
        qq["data.claim_type"] = claim_type
    if executive:
        qq["data.executive"] = {"$regex": executive, "$options": "i"}
    # user request — Application Date range filter.
    if date_from or date_to:
        rng: Dict[str, Any] = {}
        if date_from:
            rng["$gte"] = date_from[:10]
        if date_to:
            rng["$lte"] = date_to[:10]
        qq["data.application_date"] = rng
    if q:
        qq["$or"] = [{"data.employee_name": {"$regex": q, "$options": "i"}},
                     {"data.employee_code": {"$regex": q, "$options": "i"}},
                     {"claim_no": {"$regex": q, "$options": "i"}}]
    rows = await db.pf_esic_claims.find(qq, {"_id": 0}).sort(
        "created_at", -1).to_list(max(1, min(limit, 1000)))
    # user request — sorting: date-wise / name-wise / firm-wise.
    if sort in ("date_asc", "date_desc"):
        rows.sort(key=lambda c: str((c.get("data") or {}).get(
            "application_date") or ""), reverse=(sort == "date_desc"))
    elif sort == "name":
        rows.sort(key=lambda c: str((c.get("data") or {}).get(
            "employee_name") or "").lower())
    elif sort == "firm":
        names = {c["company_id"]: (c.get("name") or "")
                 async for c in db.companies.find(
                     {}, {"_id": 0, "company_id": 1, "name": 1})}

        def _firm(c):
            if c.get("company_id") == "external":
                return str((c.get("data") or {}).get(
                    "company_name") or "~external").lower()
            return names.get(c.get("company_id"), "").lower()
        rows.sort(key=_firm)
    return {"claims": rows}


@router.post("")
async def save_claim(body: dict = Body(...),
                     authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(authorization, body.get("company_id"))
    kind = body.get("claim_kind")
    if kind not in ("pf", "esic"):
        raise HTTPException(status_code=400, detail="claim_kind pf|esic")
    # user request — allow claims for OUTSIDE parties too: pass
    # company_id="external" with data.company_name free text.
    if not company_id:
        if (body.get("data") or {}).get("company_name"):
            company_id = "external"
        else:
            raise HTTPException(
                status_code=400,
                detail="company_id or data.company_name required")
    cid = body.get("claim_id")
    existing = await db.pf_esic_claims.find_one(
        {"claim_id": cid}, {"_id": 0}) if cid else None
    statuses = PF_STATUSES if kind == "pf" else ESIC_STATUSES
    status = body.get("status") or (existing or {}).get("status") or "Pending"
    if status not in statuses:
        raise HTTPException(status_code=400, detail="Bad status")
    data = dict((existing or {}).get("data") or {},
                **(body.get("data") or {}))
    # auto-fill from Employee Master by employee_code
    code = str(data.get("employee_code") or "").strip()
    if code and not data.get("employee_name"):
        u = await db.users.find_one(
            {"company_id": company_id, "role": "employee",
             "employee_code": code}, {"_id": 0})
        if u:
            data.setdefault("employee_name", u.get("name"))
            data.setdefault("uan", u.get("uan_no"))
            data.setdefault("insurance_no", u.get("esi_ip_no"))
            data.setdefault("department", u.get("department"))
            data.setdefault("designation", u.get("designation"))
            data.setdefault("doj", u.get("doj"))
            data.setdefault("dol", u.get("exit_date") or u.get("resign_date"))
            data.setdefault("pf_member_id", u.get("pf_no"))
    documents = dict((existing or {}).get("documents") or {},
                     **(body.get("documents") or {}))
    if not existing:
        seq = await db.pf_esic_claims.count_documents(
            {"claim_kind": kind}) + 1
        claim_no = f"CLM-{kind.upper()}-{seq:05d}"
        cid = f"clm_{uuid.uuid4().hex[:10]}"
        timeline = [{"at": _now(), "status": status,
                     "by": admin.get("name") or admin.get("email"),
                     "note": "Claim created"}]
    else:
        claim_no = existing["claim_no"]
        timeline = existing.get("timeline") or []
        if status != existing.get("status"):
            timeline.append({"at": _now(), "status": status,
                             "by": admin.get("name") or admin.get("email"),
                             "note": body.get("note") or ""})
            if status == "Settled" and not data.get("settlement_date"):
                data["settlement_date"] = date.today().isoformat()
    data.setdefault("application_date", date.today().isoformat())
    # Follow-up Reminder Engine — default follow-up +7 days on open claims
    if status not in ("Settled", "Rejected") and not data.get("follow_up_date"):
        data["follow_up_date"] = (date.today() + timedelta(days=7)).isoformat()
    # log document uploads into the timeline
    if existing:
        new_docs = [k for k, v in documents.items()
                    if v and not (existing.get("documents") or {}).get(k)]
        if new_docs:
            timeline.append({"at": _now(), "status": status,
                             "by": admin.get("name") or admin.get("email"),
                             "note": "Documents added: "
                             + ", ".join(new_docs[:5])})
    doc = {"claim_id": cid, "claim_no": claim_no, "claim_kind": kind,
           "company_id": company_id, "status": status, "data": data,
           "documents": documents, "timeline": timeline,
           "updated_at": _now()}
    doc["ai_flags"] = await _ai_checks(doc)
    doc["doc_score"] = _doc_score(doc)
    doc["expected_settlement"] = await _expected_settlement(doc)
    if existing:
        await db.pf_esic_claims.update_one({"claim_id": cid}, {"$set": doc})
    else:
        doc["created_at"] = _now()
        await db.pf_esic_claims.insert_one(dict(doc))
    return {"ok": True, "claim_id": cid, "claim_no": claim_no,
            "ai_flags": doc["ai_flags"], "doc_score": doc["doc_score"],
            "expected_settlement": doc["expected_settlement"]}


_MAX_DOC_BYTES = 10 * 1024 * 1024  # 10 MB per attached file
_ALLOWED_DOC_TYPES = {
    "application/pdf", "image/jpeg", "image/png", "image/webp", "image/heic",
}


async def _claim_guarded(claim_id: str, admin: dict,
                         company_id: Optional[str]) -> dict:
    claim = await db.pf_esic_claims.find_one({"claim_id": claim_id}, {"_id": 0})
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if company_id and claim.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorised for this claim")
    return claim


def _doc_public(d: dict) -> dict:
    return {k: d.get(k) for k in (
        "doc_id", "claim_id", "doc_name", "filename", "content_type",
        "size", "uploaded_by", "uploaded_at")}


@router.get("/{claim_id}/documents")
async def list_claim_documents(claim_id: str,
                               authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(authorization)
    await _claim_guarded(claim_id, admin, company_id)
    docs = await db.claim_documents.find(
        {"claim_id": claim_id}, {"_id": 0, "base64": 0}).sort(
        "uploaded_at", 1).to_list(200)
    return {"documents": [_doc_public(d) for d in docs]}


@router.post("/{claim_id}/documents")
async def upload_claim_document(claim_id: str, body: dict = Body(...),
                                authorization: Optional[str] = Header(None)):
    """user request — attach the ACTUAL scanned file (PDF / photo) of a
    checklist document (Form-19, cancelled cheque, Aadhaar, …) to a claim,
    turning the claims register into a complete digital file."""
    admin, company_id = await _adm(authorization)
    claim = await _claim_guarded(claim_id, admin, company_id)
    doc_name = str(body.get("doc_name") or "").strip() or "Other"
    filename = str(body.get("filename") or "document").strip()[:120]
    content_type = str(body.get("content_type") or "").strip().lower()
    if content_type not in _ALLOWED_DOC_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Only PDF / JPG / PNG / WEBP / HEIC files are allowed")
    raw = str(body.get("base64") or "")
    if "," in raw[:80]:  # strip a data-URL prefix if the client sent one
        raw = raw.split(",", 1)[1]
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 payload")
    if not decoded:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(decoded) > _MAX_DOC_BYTES:
        raise HTTPException(status_code=400,
                            detail="File too large — max 10 MB per document")
    doc_id = f"cdoc_{uuid.uuid4().hex[:10]}"
    await db.claim_documents.insert_one({
        "doc_id": doc_id, "claim_id": claim_id,
        "company_id": claim.get("company_id"),
        "doc_name": doc_name, "filename": filename,
        "content_type": content_type, "size": len(decoded),
        "base64": raw,
        "uploaded_by": admin.get("name") or admin.get("email"),
        "uploaded_at": _now(),
    })
    # Auto-tick the checklist + timeline entry, then refresh AI/doc score.
    documents = dict(claim.get("documents") or {})
    kind = claim.get("claim_kind") or "pf"
    if doc_name in DOC_CHECKLIST.get(kind, []):
        documents[doc_name] = True
    timeline = list(claim.get("timeline") or [])
    timeline.append({"at": _now(), "status": claim.get("status"),
                     "by": admin.get("name") or admin.get("email"),
                     "note": f"File attached: {doc_name} ({filename})"})
    upd = {"documents": documents, "timeline": timeline,
           "updated_at": _now()}
    merged = dict(claim, **upd)
    upd["ai_flags"] = await _ai_checks(merged)
    upd["doc_score"] = _doc_score(merged)
    await db.pf_esic_claims.update_one({"claim_id": claim_id}, {"$set": upd})
    return {"ok": True, "doc_id": doc_id, "doc_score": upd["doc_score"]}


@router.get("/{claim_id}/documents/{doc_id}/file")
async def download_claim_document(claim_id: str, doc_id: str,
                                  authorization: Optional[str] = Header(None)):
    from fastapi.responses import Response
    admin, company_id = await _adm(authorization)
    await _claim_guarded(claim_id, admin, company_id)
    d = await db.claim_documents.find_one(
        {"doc_id": doc_id, "claim_id": claim_id}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    data = base64.b64decode(d.get("base64") or "")
    return Response(content=data, media_type=d.get("content_type"),
                    headers={"Content-Disposition":
                             f'inline; filename="{d.get("filename")}"'})


@router.delete("/{claim_id}/documents/{doc_id}")
async def delete_claim_document(claim_id: str, doc_id: str,
                                authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(authorization)
    claim = await _claim_guarded(claim_id, admin, company_id)
    d = await db.claim_documents.find_one(
        {"doc_id": doc_id, "claim_id": claim_id}, {"_id": 0, "base64": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.claim_documents.delete_one({"doc_id": doc_id})
    # Untick the checklist when no other file remains for that doc name.
    remaining = await db.claim_documents.count_documents(
        {"claim_id": claim_id, "doc_name": d.get("doc_name")})
    if remaining == 0:
        documents = dict(claim.get("documents") or {})
        if d.get("doc_name") in documents:
            documents[d["doc_name"]] = False
        merged = dict(claim, documents=documents)
        await db.pf_esic_claims.update_one(
            {"claim_id": claim_id},
            {"$set": {"documents": documents,
                      "doc_score": _doc_score(merged),
                      "updated_at": _now()}})
    return {"ok": True}


@router.get("/reminders")
async def reminders(company_id: Optional[str] = None,
                    authorization: Optional[str] = Header(None)):
    """Follow-up Reminder Engine — open claims due for follow-up."""
    _admin, company_id = await _adm(authorization, company_id)
    q: Dict[str, Any] = {"status": {"$nin": ["Settled", "Rejected"]}}
    if company_id:
        q["company_id"] = company_id
    due = []
    today = date.today().isoformat()
    async for c in db.pf_esic_claims.find(q, {"_id": 0}):
        fu = (c.get("data") or {}).get("follow_up_date")
        if fu and str(fu) <= today:
            d = c.get("data") or {}
            due.append({"claim_no": c["claim_no"], "claim_kind": c["claim_kind"],
                        "employee_name": d.get("employee_name"),
                        "claim_type": d.get("claim_type"),
                        "status": c.get("status"), "follow_up_date": fu,
                        "executive": d.get("executive"),
                        "doc_score": c.get("doc_score"),
                        "ai_flags": c.get("ai_flags") or []})
    due.sort(key=lambda x: str(x["follow_up_date"]))
    return {"due": due, "count": len(due)}


@router.delete("/{claim_id}")
async def delete_claim(claim_id: str,
                       authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(authorization)
    q: Dict[str, Any] = {"claim_id": claim_id}
    if company_id:
        q["company_id"] = company_id
    res = await db.pf_esic_claims.delete_one(q)
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Claim not found")
    return {"ok": True}


_REPORT_KINDS = {
    "pf-register": ("PF Claims Register", {"claim_kind": "pf"}),
    "esic-register": ("ESIC Claims Register", {"claim_kind": "esic"}),
    "pending": ("Pending Claims",
                {"status": {"$in": ["Pending", "Submitted", "Under Process",
                                    "Verified"]}}),
    "approved": ("Approved Claims", {"status": "Approved"}),
    "rejected": ("Rejected Claims", {"status": "Rejected"}),
    "settlement": ("Settlement Register", {"status": "Settled"}),
}
_COLS = [("claim_no", "Claim No."), ("claim_kind", "PF/ESIC"),
         ("application_date", "Application Date"),
         ("employee_code", "Emp Code"), ("employee_name", "Employee Name"),
         ("uan", "UAN"), ("insurance_no", "ESIC IP"),
         ("department", "Department"), ("claim_type", "Claim Type"),
         ("claim_amount", "Claim Amount"), ("status", "Status"),
         ("settlement_date", "Settlement Date"),
         ("payment_reference", "Payment Ref."), ("executive", "Executive"),
         ("ai_flags", "AI Alerts")]


async def _report_rows(kind: str, company_id: Optional[str]):
    title, extra = _REPORT_KINDS[kind]
    q: Dict[str, Any] = dict(extra)
    if company_id:
        q["company_id"] = company_id
    claims = await db.pf_esic_claims.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(20000)
    rows = []
    for c in claims:
        d = c.get("data") or {}
        rows.append({
            "claim_no": c["claim_no"], "claim_kind": c["claim_kind"].upper(),
            "application_date": d.get("application_date"),
            "employee_code": d.get("employee_code"),
            "employee_name": d.get("employee_name"), "uan": d.get("uan"),
            "insurance_no": d.get("insurance_no"),
            "department": d.get("department"),
            "claim_type": d.get("claim_type"),
            "claim_amount": _f(d.get("claim_amount")),
            "status": c.get("status"),
            "settlement_date": d.get("settlement_date"),
            "payment_reference": d.get("payment_reference"),
            "executive": d.get("executive"),
            "ai_flags": "; ".join(c.get("ai_flags") or [])[:100]})
    totals = {"employee_name": "TOTAL",
              "claim_amount": round(sum(r["claim_amount"] for r in rows), 2)}
    return title, _COLS, rows, totals


@router.get("/report/{kind}")
async def report(kind: str, company_id: Optional[str] = None,
                 authorization: Optional[str] = Header(None)):
    for ext in ("xlsx", "pdf"):
        if kind.endswith(f".{ext}"):
            return await _rexp(kind[: -len(ext) - 1], company_id,
                               authorization, ext)
    if kind not in _REPORT_KINDS:
        raise HTTPException(status_code=404, detail="Unknown report")
    _admin, company_id = await _adm(authorization, company_id)
    title, cols, rows, totals = await _report_rows(kind, company_id)
    return {"title": title,
            "columns": [{"key": k, "label": lb} for k, lb in cols],
            "rows": rows, "totals": totals}


async def _rexp(kind, company_id, authorization, fmt):
    if kind not in _REPORT_KINDS:
        raise HTTPException(status_code=404, detail="Unknown report")
    _admin, company_id = await _adm(authorization, company_id)
    title, cols, rows, totals = await _report_rows(kind, company_id)
    logo = None
    if company_id:
        c = await _company(company_id)
        logo = c.get("logo_base64")
        title = f"{title} — {c.get('name')}"
    columns = [{"key": k, "label": lb} for k, lb in cols]
    sub = f"Generated {datetime.now():%d-%m-%Y}"
    if fmt == "xlsx":
        buf = register_xlsx(title, sub, columns, rows, totals)
        mt = ("application/vnd.openxmlformats-officedocument"
              ".spreadsheetml.sheet")
    else:
        buf = register_pdf(title, sub, columns, rows, totals, logo)
        mt = "application/pdf"
    return StreamingResponse(buf, media_type=mt, headers={
        "Content-Disposition":
        f'attachment; filename="{title.replace(" ", "_")}.{fmt}"'})
