"""Sales — Proposal Management (MVP).

New, self-contained module. Reuses Company Master (branding), User
Management (auth/roles) and the PDF toolchain. Provides:

  * Proposal CRUD with auto number PROP-YYYY-000001
  * Status workflow (draft/pending_approval/sent/viewed/accepted/rejected/
    expired/converted)
  * Auto scope-of-work generation from selected services
  * Server-side pricing totals
  * Export to professional PDF and to Word (.doc)
  * Dashboard counts

Later phases (approval workflow, email, client portal, version control,
analytics, convert-to-customer) build on this collection.
"""
import html
import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import Response

from server import db, get_user_from_token, require_role, now_iso, logger

router = APIRouter(prefix="/api", tags=["proposals"])

STATUSES = ["draft", "pending_approval", "sent", "viewed", "accepted",
            "rejected", "expired", "converted"]

# Auto scope-of-work snippets keyed by service id.
SCOPE_MAP: Dict[str, List[str]] = {
    "salary_processing": ["Monthly Payroll Processing", "Salary Sheet",
                          "Salary Slip", "Bank Transfer File", "Salary Register"],
    "epf": ["UAN Management", "ECR Upload", "Challan Preparation",
            "Monthly Returns", "Compliance Reports"],
    "esic": ["ESIC Registration & IP mapping", "Contribution Challan",
             "Monthly Returns", "Compliance Reports"],
    "pt": ["PT Registration", "PT Challan", "State-wise PT Returns"],
    "lwf": ["LWF Deduction", "LWF Challan & Returns"],
    "bonus": ["Bonus Eligibility", "Bonus Calculation", "Form C / D Registers"],
    "gratuity": ["Gratuity Eligibility", "Gratuity Liability", "Gratuity Register"],
    "clra": ["Contractor Registers (Form XII–XV)", "Compliance Tracking"],
    "attendance": ["Biometric / GPS / QR Attendance", "Muster Roll", "OT Register"],
    "leave_management": ["Leave Policies", "Leave Ledger", "Approval Workflow"],
    "employee_app": ["Employee Mobile App", "Self-service Payslips & Leave"],
    "employer_portal": ["Employer Web Portal", "Dashboards & Reports"],
    "geo_fencing": ["Geofence Configuration", "Location-verified Attendance"],
    "face_attendance": ["Face-recognition Attendance", "Anti-spoof checks"],
}

SERVICE_LABELS: Dict[str, str] = {
    "salary_processing": "Salary Processing", "salary_slip": "Salary Slip",
    "salary_register": "Salary Register", "bank_advice": "Bank Advice",
    "bonus": "Bonus", "gratuity": "Gratuity", "ff_settlement": "F&F Settlement",
    "reimbursement": "Reimbursement", "loan_management": "Loan Management",
    "epf": "EPF", "esic": "ESIC", "pt": "Professional Tax", "lwf": "LWF",
    "labour_licence": "Labour Licence", "factory_compliance": "Factory Compliance",
    "clra": "CLRA", "bocw": "BOCW", "minimum_wages": "Minimum Wages",
    "register_maintenance": "Register Maintenance", "employee_master": "Employee Master",
    "leave_management": "Leave Management", "attendance": "Attendance",
    "shift_management": "Shift Management", "performance_management": "Performance Management",
    "asset_management": "Asset Management", "employee_app": "Employee Mobile App",
    "employer_portal": "Employer Portal", "offline_pwa": "Offline PWA",
    "face_attendance": "Face Attendance", "qr_attendance": "QR Attendance",
    "geo_fencing": "Geo-Fencing", "gps_attendance": "GPS Attendance",
    "ai_chatbot": "AI Chatbot",
}


async def _guard(authorization: Optional[str], company_id: Optional[str]) -> Dict[str, Any]:
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    admin["_cid"] = company_id
    return admin


async def _next_number() -> str:
    year = datetime.now(timezone.utc).year
    doc = await db.counters.find_one_and_update(
        {"_id": f"proposal_{year}"},
        {"$inc": {"seq": 1}},
        upsert=True, return_document=True,
    )
    seq = (doc or {}).get("seq", 1)
    return f"PROP-{year}-{seq:06d}"


def _compute_pricing(p: Dict[str, Any]) -> Dict[str, float]:
    one_time = float(p.get("one_time") or 0)
    monthly = float(p.get("monthly") or 0)
    per_emp = float(p.get("per_employee") or 0)
    emp_count = float(p.get("employee_count") or 0)
    per_branch = float(p.get("per_branch") or 0)
    branch_count = float(p.get("branch_count") or 0)
    addl = float(p.get("additional") or 0)
    months = float(p.get("billing_months") or 1)

    recurring = (monthly + per_emp * emp_count + per_branch * branch_count) * months
    subtotal = one_time + recurring + addl
    disc_pct = float(p.get("discount_pct") or 0)
    discount = round(subtotal * disc_pct / 100, 2)
    taxable = subtotal - discount
    gst_pct = float(p.get("gst_pct") if p.get("gst_pct") is not None else 18)
    gst = round(taxable * gst_pct / 100, 2)
    grand = round(taxable + gst, 2)
    return {
        "subtotal": round(subtotal, 2), "discount": discount,
        "taxable": round(taxable, 2), "gst": gst, "grand_total": grand,
        "gst_pct": gst_pct, "discount_pct": disc_pct,
    }


def _auto_scope(services: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in services:
        items = SCOPE_MAP.get(s)
        if items:
            out.append({"service": SERVICE_LABELS.get(s, s), "items": items})
    return out


@router.get("/admin/proposals/meta")
async def proposals_meta(authorization: Optional[str] = Header(None)):
    await get_user_from_token(authorization)
    return {"statuses": STATUSES, "service_labels": SERVICE_LABELS}


@router.post("/admin/proposals")
async def create_proposal(payload: Dict[str, Any] = Body(...),
                          authorization: Optional[str] = Header(None)):
    admin = await _guard(authorization, payload.get("company_id"))
    number = await _next_number()
    now = now_iso()
    valid_days = int(payload.get("validity_days") or 30)
    expiry = (datetime.now(timezone.utc) + timedelta(days=valid_days)).strftime("%Y-%m-%d")
    services = payload.get("services") or []
    pricing_in = payload.get("pricing") or {}
    doc = {
        "proposal_id": f"prop_{uuid.uuid4().hex[:12]}",
        "number": number,
        "company_id": admin["_cid"],
        "status": "draft",
        "version": 1,
        "client": payload.get("client") or {},
        "proposal_types": payload.get("proposal_types") or [],
        "services": services,
        "pricing_input": pricing_in,
        "pricing": _compute_pricing(pricing_in),
        "scope": payload.get("scope") or _auto_scope(services),
        "timeline": payload.get("timeline") or [
            {"label": "Week 1", "task": "Requirement Gathering"},
            {"label": "Week 2", "task": "Company Setup"},
            {"label": "Week 3", "task": "Employee Migration"},
            {"label": "Week 4", "task": "User Training"},
            {"label": "Week 5", "task": "Go Live"},
        ],
        "terms": payload.get("terms") or _default_terms(),
        "theme": payload.get("theme") or "corporate",
        "prepared_by": admin.get("name") or admin.get("email"),
        "prepared_by_id": admin["user_id"],
        "proposal_date": now[:10],
        "expiry_date": expiry,
        "created_at": now,
        "created_by": admin["user_id"],
        "audit": [{"action": "created", "by": admin["user_id"],
                   "name": admin.get("name"), "at": now}],
    }
    await db.proposals.insert_one(doc)
    doc.pop("_id", None)
    logger.info("[proposals] created %s by %s", number, admin["user_id"])
    return {"ok": True, "proposal": doc}


def _default_terms() -> str:
    return (
        "1. Proposal Validity: 30 days from the date of issue.\n"
        "2. Payment Terms: One-time setup in advance; monthly charges billed monthly.\n"
        "3. GST: As applicable, extra on all charges.\n"
        "4. Confidentiality: All data shared is kept strictly confidential.\n"
        "5. Cancellation: 30 days written notice by either party.\n"
        "6. Support: Business-hours support (Mon–Sat, 10:00–18:00).\n"
        "7. Data Security: Data encrypted at rest and in transit.\n"
        "8. SLA: 99.5% uptime for the portal.\n"
        "9. Renewal: Auto-renewal annually unless terminated."
    )


@router.get("/admin/proposals")
async def list_proposals(company_id: Optional[str] = None,
                         status: Optional[str] = None,
                         q: Optional[str] = None,
                         authorization: Optional[str] = Header(None)):
    admin = await _guard(authorization, company_id)
    query: Dict[str, Any] = {"company_id": admin["_cid"]}
    if status:
        query["status"] = status
    if q:
        query["$or"] = [
            {"number": {"$regex": q, "$options": "i"}},
            {"client.company_name": {"$regex": q, "$options": "i"}},
        ]
    items = await db.proposals.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    # dashboard counts
    counts = {s: 0 for s in STATUSES}
    total_value = 0.0
    async for p in db.proposals.find({"company_id": admin["_cid"]},
                                     {"_id": 0, "status": 1, "pricing": 1}):
        counts[p.get("status", "draft")] = counts.get(p.get("status", "draft"), 0) + 1
        total_value += float((p.get("pricing") or {}).get("grand_total") or 0)
    return {"proposals": items, "counts": counts, "total": len(items),
            "total_value": round(total_value, 2)}


@router.get("/admin/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, company_id: Optional[str] = None,
                       authorization: Optional[str] = Header(None)):
    admin = await _guard(authorization, company_id)
    p = await db.proposals.find_one(
        {"proposal_id": proposal_id, "company_id": admin["_cid"]}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return p


@router.put("/admin/proposals/{proposal_id}")
async def update_proposal(proposal_id: str, payload: Dict[str, Any] = Body(...),
                          authorization: Optional[str] = Header(None)):
    admin = await _guard(authorization, payload.get("company_id"))
    p = await db.proposals.find_one(
        {"proposal_id": proposal_id, "company_id": admin["_cid"]})
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    updates: Dict[str, Any] = {"updated_at": now_iso()}
    for f in ("client", "proposal_types", "services", "scope", "timeline",
              "terms", "theme"):
        if f in payload:
            updates[f] = payload[f]
    if "services" in payload and "scope" not in payload:
        updates["scope"] = _auto_scope(payload["services"])
    if "pricing" in payload:
        updates["pricing_input"] = payload["pricing"]
        updates["pricing"] = _compute_pricing(payload["pricing"])
    if "status" in payload:
        st = payload["status"]
        if st not in STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        updates["status"] = st
    await db.proposals.update_one(
        {"proposal_id": proposal_id},
        {"$set": updates,
         "$push": {"audit": {"action": "updated", "by": admin["user_id"],
                             "name": admin.get("name"), "at": now_iso()}}},
    )
    return {"ok": True}


@router.delete("/admin/proposals/{proposal_id}")
async def archive_proposal(proposal_id: str, company_id: Optional[str] = None,
                           authorization: Optional[str] = Header(None)):
    # Never hard-delete — mark archived (audit contract).
    admin = await _guard(authorization, company_id)
    res = await db.proposals.update_one(
        {"proposal_id": proposal_id, "company_id": admin["_cid"]},
        {"$set": {"archived": True, "archived_at": now_iso()},
         "$push": {"audit": {"action": "archived", "by": admin["user_id"],
                             "at": now_iso()}}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Document generation (PDF + Word)
# ---------------------------------------------------------------------------
async def _load(proposal_id: str, cid: str) -> Dict[str, Any]:
    p = await db.proposals.find_one(
        {"proposal_id": proposal_id, "company_id": cid}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    company = await db.companies.find_one({"company_id": cid}, {"_id": 0}) or {}
    return {"p": p, "company": company}


def _rs(v: Any) -> str:
    try:
        return f"Rs. {float(v):,.2f}"
    except Exception:
        return "Rs. 0.00"


_SECTIONS = [
    "Cover Page", "Executive Summary", "About Our Company", "Client Requirement",
    "Proposed Solution", "Scope of Work", "Features Included", "Deliverables",
    "Implementation Plan", "Pricing", "Payment Terms", "Support & SLA",
    "Terms & Conditions", "Acceptance Page", "Signature Page",
]


@router.get("/admin/proposals/{proposal_id}/export.pdf")
async def export_pdf(proposal_id: str, company_id: Optional[str] = None,
                     authorization: Optional[str] = Header(None)):
    admin = await _guard(authorization, company_id)
    ctx = await _load(proposal_id, admin["_cid"])
    p, company = ctx["p"], ctx["company"]
    client = p.get("client") or {}
    pr = p.get("pricing") or {}

    from fpdf import FPDF

    def s(t: Any) -> str:
        return str(t or "").encode("latin-1", "replace").decode("latin-1")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)

    def h1(t: str):
        pdf.set_font("Helvetica", "B", 15)
        pdf.set_text_color(15, 46, 61)
        pdf.multi_cell(0, 8, s(t), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(15, 46, 61)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(3)
        pdf.set_text_color(0, 0, 0)

    def para(t: str, size=10.5):
        pdf.set_font("Helvetica", "", size)
        pdf.multi_cell(0, 5.5, s(t), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    # 1. Cover page
    pdf.add_page()
    pdf.ln(40)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(15, 46, 61)
    pdf.multi_cell(0, 12, s("BUSINESS PROPOSAL"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 13)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(0, 7, s(", ".join(p.get("proposal_types") or ["Payroll & Compliance Solution"])), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(20)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 7, s(f"Prepared for: {client.get('company_name', '')}"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 6, s(f"Proposal No: {p.get('number')}  |  Date: {p.get('proposal_date')}"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 6, s(f"Valid till: {p.get('expiry_date')}"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(24)
    pdf.set_font("Helvetica", "B", 13)
    pdf.multi_cell(0, 7, s(company.get("name", "")), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(90, 90, 90)
    addr = ", ".join([x for x in [company.get("address"), company.get("city"),
                                  company.get("state")] if x])
    pdf.multi_cell(0, 5, s(addr), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 5, s(f"GSTIN: {company.get('gstin', '-')}  |  PAN: {company.get('pan', '-')}"), align="C", new_x="LMARGIN", new_y="NEXT")

    # 2. Executive Summary
    pdf.add_page(); h1("Executive Summary")
    para(f"We are pleased to submit this proposal to {client.get('company_name', 'your organisation')} "
         f"for {', '.join(p.get('proposal_types') or ['our services'])}. This document outlines the "
         "proposed solution, scope of work, deliverables, implementation plan and commercials.")

    # 3. About Our Company
    h1("About Our Company")
    para(f"{company.get('name', '')} is a payroll & statutory-compliance services provider delivering "
         "end-to-end payroll processing, EPF/ESIC/PT/LWF compliance, attendance and HRMS technology.")

    # 4. Client Requirement
    pdf.add_page(); h1("Client Requirement")
    for k, lbl in [("industry", "Industry"), ("employee_strength", "Employee Strength"),
                   ("branches", "Branches"), ("payroll_frequency", "Payroll Frequency"),
                   ("existing_software", "Existing Software")]:
        if client.get(k):
            para(f"{lbl}: {client.get(k)}", 10)

    # 5-8 Proposed Solution / Scope / Features / Deliverables
    h1("Proposed Solution & Scope of Work")
    for grp in (p.get("scope") or []):
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 6, s(grp.get("service", "")), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for it in grp.get("items", []):
            pdf.multi_cell(0, 5.2, s(f"   - {it}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    h1("Features Included")
    feats = [SERVICE_LABELS.get(x, x) for x in (p.get("services") or [])]
    para(", ".join(feats) or "-")

    # 9. Implementation Plan
    pdf.add_page(); h1("Implementation Plan")
    for m in (p.get("timeline") or []):
        para(f"{m.get('label', '')}: {m.get('task', '')}", 10)

    # 10. Pricing
    h1("Pricing")
    pi = p.get("pricing_input") or {}
    rows = [
        ("One-time Setup", pi.get("one_time")),
        ("Monthly Charges", pi.get("monthly")),
        ("Per-Employee Charges", pi.get("per_employee")),
        ("Per-Branch Charges", pi.get("per_branch")),
        ("Additional Modules", pi.get("additional")),
    ]
    pdf.set_font("Helvetica", "", 10)
    for lbl, val in rows:
        if val:
            pdf.cell(120, 6, s(lbl))
            pdf.cell(0, 6, s(_rs(val)), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y()); pdf.ln(2)
    for lbl, val in [("Subtotal", pr.get("subtotal")),
                     (f"Discount ({pr.get('discount_pct', 0)}%)", -1 * float(pr.get("discount") or 0)),
                     ("Taxable", pr.get("taxable")),
                     (f"GST ({pr.get('gst_pct', 18)}%)", pr.get("gst"))]:
        pdf.cell(120, 6, s(lbl))
        pdf.cell(0, 6, s(_rs(val)), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(120, 8, s("GRAND TOTAL"))
    pdf.cell(0, 8, s(_rs(pr.get("grand_total"))), align="R", new_x="LMARGIN", new_y="NEXT")

    # 11-13 Terms
    pdf.add_page(); h1("Payment Terms, Support & SLA, Terms & Conditions")
    para(p.get("terms") or "", 10)

    # 14-15 Acceptance + Signature
    pdf.add_page(); h1("Acceptance & Signature")
    para("By signing below, the client accepts this proposal and its terms.")
    pdf.ln(24)
    pdf.cell(90, 6, s("_____________________________"))
    pdf.cell(0, 6, s("_____________________________"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(90, 6, s(f"For {client.get('company_name', 'Client')}"))
    pdf.cell(0, 6, s(f"For {company.get('name', '')}"), new_x="LMARGIN", new_y="NEXT")

    out = pdf.output()
    data = bytes(out) if isinstance(out, (bytearray, bytes)) else out.encode("latin-1")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{p.get("number")}.pdf"'})


@router.get("/admin/proposals/{proposal_id}/export.doc")
async def export_doc(proposal_id: str, company_id: Optional[str] = None,
                     authorization: Optional[str] = Header(None)):
    admin = await _guard(authorization, company_id)
    ctx = await _load(proposal_id, admin["_cid"])
    p, company = ctx["p"], ctx["company"]
    client = p.get("client") or {}
    pr = p.get("pricing") or {}
    pi = p.get("pricing_input") or {}

    def e(t: Any) -> str:
        return html.escape(str(t or ""))

    scope_html = ""
    for grp in (p.get("scope") or []):
        items = "".join(f"<li>{e(i)}</li>" for i in grp.get("items", []))
        scope_html += f"<h3>{e(grp.get('service'))}</h3><ul>{items}</ul>"
    timeline_html = "".join(
        f"<li><b>{e(m.get('label'))}:</b> {e(m.get('task'))}</li>"
        for m in (p.get("timeline") or []))
    price_rows = ""
    for lbl, val in [("One-time Setup", pi.get("one_time")),
                     ("Monthly Charges", pi.get("monthly")),
                     ("Per-Employee Charges", pi.get("per_employee")),
                     ("Per-Branch Charges", pi.get("per_branch")),
                     ("Additional Modules", pi.get("additional"))]:
        if val:
            price_rows += f"<tr><td>{e(lbl)}</td><td style='text-align:right'>{_rs(val)}</td></tr>"
    feats = ", ".join(SERVICE_LABELS.get(x, x) for x in (p.get("services") or []))
    terms_html = e(p.get("terms") or "").replace("\n", "<br/>")

    doc = f"""<html xmlns:o='urn:schemas-microsoft-com:office:office'
    xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'>
    <head><meta charset='utf-8'><title>{e(p.get('number'))}</title>
    <style>body{{font-family:Calibri,Arial,sans-serif;color:#222;}}
    h1{{color:#0F2E3D;}} h2{{color:#0F2E3D;border-bottom:1px solid #0F2E3D;}}
    table{{width:100%;border-collapse:collapse;}} td{{padding:4px 8px;border-bottom:1px solid #ddd;}}
    .total{{font-weight:bold;font-size:14pt;}}</style></head><body>
    <h1 style='text-align:center'>BUSINESS PROPOSAL</h1>
    <p style='text-align:center'>{e(', '.join(p.get('proposal_types') or []))}</p>
    <p style='text-align:center'><b>Prepared for:</b> {e(client.get('company_name'))}<br/>
    Proposal No: {e(p.get('number'))} | Date: {e(p.get('proposal_date'))} | Valid till: {e(p.get('expiry_date'))}</p>
    <hr/>
    <h2>Executive Summary</h2>
    <p>We are pleased to submit this proposal to {e(client.get('company_name') or 'your organisation')}
    for {e(', '.join(p.get('proposal_types') or ['our services']))}.</p>
    <h2>About Our Company</h2>
    <p>{e(company.get('name'))} — payroll & statutory-compliance services provider.<br/>
    {e(company.get('address'))}, {e(company.get('city'))}, {e(company.get('state'))}<br/>
    GSTIN: {e(company.get('gstin') or '-')} | PAN: {e(company.get('pan') or '-')}</p>
    <h2>Client Requirement</h2>
    <p>Industry: {e(client.get('industry'))} | Employee Strength: {e(client.get('employee_strength'))}
    | Branches: {e(client.get('branches'))} | Payroll Frequency: {e(client.get('payroll_frequency'))}</p>
    <h2>Scope of Work</h2>{scope_html}
    <h2>Features Included</h2><p>{e(feats)}</p>
    <h2>Implementation Plan</h2><ul>{timeline_html}</ul>
    <h2>Pricing</h2><table>{price_rows}
    <tr><td>Subtotal</td><td style='text-align:right'>{_rs(pr.get('subtotal'))}</td></tr>
    <tr><td>Discount ({e(pr.get('discount_pct', 0))}%)</td><td style='text-align:right'>-{_rs(pr.get('discount'))}</td></tr>
    <tr><td>GST ({e(pr.get('gst_pct', 18))}%)</td><td style='text-align:right'>{_rs(pr.get('gst'))}</td></tr>
    <tr class='total'><td>GRAND TOTAL</td><td style='text-align:right'>{_rs(pr.get('grand_total'))}</td></tr>
    </table>
    <h2>Terms &amp; Conditions</h2><p>{terms_html}</p>
    <h2>Acceptance &amp; Signature</h2>
    <p>By signing below, the client accepts this proposal and its terms.</p>
    <br/><br/><table><tr><td>_______________________<br/>For {e(client.get('company_name') or 'Client')}</td>
    <td>_______________________<br/>For {e(company.get('name'))}</td></tr></table>
    </body></html>"""

    return Response(
        content=doc.encode("utf-8"), media_type="application/msword",
        headers={"Content-Disposition": f'attachment; filename="{p.get("number")}.doc"'})
