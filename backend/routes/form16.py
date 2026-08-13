"""Iter 551 — FORM 16 MODULE (Phase 1: core workflow, user spec).

Payroll → TDS → Form 16. Auto-consolidates finalized payroll (Apr→Mar)
from compliance_salary_runs (fallback: actual salary_runs), computes
Part B under the configurable Tax Configuration Master (new regime
default), runs a Readiness Check, supports generation-time EXTRA income/
deduction heads per employee, statutory-style A4 PDF, bulk ZIP, history
+ audit. Read-only over payroll — finalized runs are never modified.
"""
import io
import re
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import Response

from server import db, get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api/admin/form16", tags=["form16"])

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# Default NEW-REGIME config (editable via Tax Configuration Master).
DEFAULT_CFG = {
    "regime": "new",
    "slabs": [
        {"upto": 400000, "rate": 0}, {"upto": 800000, "rate": 5},
        {"upto": 1200000, "rate": 10}, {"upto": 1600000, "rate": 15},
        {"upto": 2000000, "rate": 20}, {"upto": 2400000, "rate": 25},
        {"upto": None, "rate": 30},
    ],
    "standard_deduction": 75000,
    "rebate_income_limit": 1200000,
    "rebate_max": 60000,
    "cess_pct": 4.0,
}


async def _auth(authorization, company_id):
    u = await get_user_from_token(authorization)
    require_role(u, ["super_admin", "sub_admin", "company_admin"])
    if u["role"] == "company_admin" and u.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not your firm")
    return u


def _fy_months(fy: str) -> List[str]:
    y = int(fy[:4])
    return [f"{y}-{m:02d}" for m in range(4, 13)] + [f"{y+1}-{m:02d}" for m in range(1, 4)]


async def _get_cfg(fy: str) -> dict:
    doc = await db.form16_tax_config.find_one({"fy": fy}, {"_id": 0})
    return doc or {"fy": fy, **DEFAULT_CFG}


def _slab_tax(taxable: float, slabs: List[dict]) -> float:
    tax, prev = 0.0, 0.0
    for s in slabs:
        hi = s["upto"] if s["upto"] is not None else float("inf")
        if taxable > prev:
            tax += (min(taxable, hi) - prev) * float(s["rate"]) / 100.0
        prev = hi
    return max(0.0, tax)


async def _fy_payroll(company_id: str, fy: str) -> Dict[str, Dict[str, Any]]:
    """user_id → {monthly:[{month,gross,tds,epf,esi}], totals}."""
    months = _fy_months(fy)
    out: Dict[str, Dict[str, Any]] = {}
    for coll in (db.compliance_salary_runs, db.salary_runs):
        async for run in coll.find(
            {"company_id": company_id, "month": {"$in": months}},
            {"_id": 0, "month": 1, "rows": 1, "generated_at": 1},
        ).sort([("generated_at", 1)]):
            for r in run.get("rows") or []:
                uid = r.get("user_id")
                if not uid:
                    continue
                d = out.setdefault(uid, {"months": {}})
                if run["month"] in d["months"] and coll is db.salary_runs:
                    continue  # compliance run already covered this month
                d["months"][run["month"]] = {
                    "month": run["month"],
                    "gross": float(r.get("total_gross") or 0),
                    "tds": float(r.get("tds") or 0),
                    "epf": float(r.get("epf") or 0),
                    "esi": float(r.get("esi") or 0),
                }
    for uid, d in out.items():
        ms = [d["months"][m] for m in sorted(d["months"])]
        d["monthly"] = ms
        d["gross"] = round(sum(x["gross"] for x in ms), 2)
        d["tds"] = round(sum(x["tds"] for x in ms), 2)
        d["epf"] = round(sum(x["epf"] for x in ms), 2)
        del d["months"]
    return out


def _part_b(gross: float, tds: float, cfg: dict, extras: Optional[dict] = None) -> dict:
    extras = extras or {}
    other_income = [
        {"label": str(x.get("label") or "Other income"), "amount": float(x.get("amount") or 0)}
        for x in (extras.get("other_income") or []) if float(x.get("amount") or 0) > 0]
    extra_ded = [
        {"label": str(x.get("label") or "Deduction"), "amount": float(x.get("amount") or 0)}
        for x in (extras.get("deductions") or []) if float(x.get("amount") or 0) > 0]
    oi = sum(x["amount"] for x in other_income)
    ed = sum(x["amount"] for x in extra_ded)
    std = min(float(cfg.get("standard_deduction") or 0), gross)
    gti = round(gross - std + oi, 2)
    taxable = max(0.0, round(gti - ed, 2))
    tax = _slab_tax(taxable, cfg["slabs"])
    rebate = min(tax, float(cfg.get("rebate_max") or 0)) \
        if taxable <= float(cfg.get("rebate_income_limit") or 0) else 0.0
    after_rebate = max(0.0, tax - rebate)
    cess = round(after_rebate * float(cfg.get("cess_pct") or 0) / 100.0, 2)
    liability = round(after_rebate + cess, 2)
    return {
        "gross_salary": round(gross, 2), "standard_deduction": std,
        "other_income": other_income, "extra_deductions": extra_ded,
        "gross_total_income": gti, "total_taxable_income": taxable,
        "tax_on_income": round(tax, 2), "rebate_87a": round(rebate, 2),
        "cess": cess, "total_tax_liability": liability,
        "tds_deducted": round(tds, 2),
        "balance_tax": round(max(0.0, liability - tds), 2),
        "excess_tds": round(max(0.0, tds - liability), 2),
        "regime": cfg.get("regime", "new"),
    }


def _readiness(emp: dict, pay: Optional[dict], company: dict) -> dict:
    issues, critical = [], False
    pan = str(emp.get("pan") or "").strip().upper()
    if not pan:
        issues.append("PAN missing"); critical = True
    elif not PAN_RE.match(pan):
        issues.append("PAN invalid"); critical = True
    if not str(company.get("tan") or "").strip():
        issues.append("Employer TAN missing")
    if not pay or not pay.get("monthly"):
        issues.append("No finalized payroll in this FY"); critical = True
    return {"ready": not critical, "issues": issues}


TAN_RE = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")


@router.post("/employer")
async def set_employer_tax_ids(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    """Iter 552 — set employer TAN / PAN right from the Form 16 screen."""
    company_id = str(payload.get("company_id") or "")
    admin = await _auth(authorization, company_id)
    updates = {}
    tan = str(payload.get("tan") or "").strip().upper()
    pan = str(payload.get("pan") or "").strip().upper()
    if tan:
        if not TAN_RE.match(tan):
            raise HTTPException(status_code=400, detail="Invalid TAN (format: ABCD12345E)")
        updates["tan"] = tan
    if pan:
        if not PAN_RE.match(pan):
            raise HTTPException(status_code=400, detail="Invalid PAN (format: ABCDE1234F)")
        updates["pan"] = pan
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to save")
    await db.companies.update_one({"company_id": company_id}, {"$set": updates})
    await db.form16_audit.insert_one({
        "at": datetime.now(timezone.utc).isoformat(), "by": admin.get("user_id"),
        "action": "employer_tax_ids", "company_id": company_id, "set": updates})
    return {"ok": True, **updates}


@router.post("/set-pan")
async def set_employee_pan(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    """Iter 552 — quick employee PAN entry from the Form 16 readiness list."""
    uid = str(payload.get("user_id") or "")
    pan = str(payload.get("pan") or "").strip().upper()
    emp = await db.users.find_one({"user_id": uid}, {"_id": 0, "company_id": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    admin = await _auth(authorization, emp["company_id"])
    if not PAN_RE.match(pan):
        raise HTTPException(status_code=400, detail="Invalid PAN (format: ABCDE1234F)")
    await db.users.update_one({"user_id": uid}, {"$set": {"pan": pan}})
    await db.form16_audit.insert_one({
        "at": datetime.now(timezone.utc).isoformat(), "by": admin.get("user_id"),
        "action": "set_pan", "user_id": uid, "pan": pan})
    return {"ok": True, "pan": pan}


# ---------------- endpoints ----------------

@router.get("/tax-config")
async def get_tax_config(fy: str, authorization: Optional[str] = Header(None)):
    u = await get_user_from_token(authorization)
    require_role(u, ["super_admin", "sub_admin", "company_admin"])
    return await _get_cfg(fy)


@router.put("/tax-config")
async def put_tax_config(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    u = await get_user_from_token(authorization)
    require_role(u, ["super_admin"])
    fy = str(payload.get("fy") or "")
    if not re.match(r"^\d{4}-\d{2}$", fy):
        raise HTTPException(status_code=400, detail="fy must be YYYY-YY")
    doc = {k: payload[k] for k in
           ("regime", "slabs", "standard_deduction", "rebate_income_limit",
            "rebate_max", "cess_pct") if k in payload}
    doc.update({"fy": fy, "updated_by": u.get("user_id"),
                "updated_at": datetime.now(timezone.utc).isoformat()})
    await db.form16_tax_config.update_one({"fy": fy}, {"$set": doc}, upsert=True)
    return await _get_cfg(fy)


@router.get("/employees")
async def form16_employees(
    company_id: str, fy: str, q: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    await _auth(authorization, company_id)
    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "name": 1, "tan": 1, "pan": 1}) or {}
    pay = await _fy_payroll(company_id, fy)
    gen: Dict[str, dict] = {}
    async for g in db.form16_records.find(
        {"company_id": company_id, "fy": fy}, {"_id": 0, "user_id": 1, "record_id": 1,
                                               "version": 1, "generated_at": 1}):
        gen[g["user_id"]] = g
    rows = []
    async for e in db.users.find(
        {"company_id": company_id, "role": "employee"},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "pan": 1,
         "father_name": 1, "designation": 1, "department": 1},
    ).sort([("employee_code", 1)]):
        p = pay.get(e["user_id"])
        if not p and not (q or "").strip():
            continue  # only employees with payroll in the FY
        if q and q.lower() not in (str(e.get("name") or "") + str(e.get("employee_code") or "")).lower():
            continue
        r = _readiness(e, p, company)
        g = gen.get(e["user_id"])
        rows.append({
            "user_id": e["user_id"], "employee_code": e.get("employee_code"),
            "name": e.get("name"), "pan": e.get("pan"),
            "gross": (p or {}).get("gross", 0), "tds": (p or {}).get("tds", 0),
            "tds_applicable": bool((p or {}).get("tds", 0) > 0),
            "ready": r["ready"], "issues": r["issues"],
            "generated": bool(g), "record_id": (g or {}).get("record_id"),
            "version": (g or {}).get("version"),
        })
    ready = sum(1 for r in rows if r["ready"])
    return {
        "company": {"name": company.get("name"), "tan": company.get("tan")},
        "fy": fy, "rows": rows,
        "dashboard": {
            "total_employees": len(rows),
            "tds_applicable": sum(1 for r in rows if r["tds_applicable"]),
            "ready": ready, "pending": len(rows) - ready,
            "generated": sum(1 for r in rows if r["generated"]),
        },
    }


@router.post("/generate")
async def form16_generate(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    company_id = str(payload.get("company_id") or "")
    fy = str(payload.get("fy") or "")
    user_ids: List[str] = list(payload.get("user_ids") or [])
    extras_map: dict = payload.get("extras") or {}
    admin = await _auth(authorization, company_id)
    if not user_ids:
        raise HTTPException(status_code=400, detail="Select at least one employee")
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0}) or {}
    cfg = await _get_cfg(fy)
    pay = await _fy_payroll(company_id, fy)
    done, skipped = [], []
    for uid in user_ids:
        emp = await db.users.find_one({"user_id": uid}, {"_id": 0})
        if not emp:
            skipped.append({"user_id": uid, "reason": "Employee not found"}); continue
        r = _readiness(emp, pay.get(uid), company)
        if not r["ready"]:
            skipped.append({"user_id": uid, "name": emp.get("name"),
                            "reason": "; ".join(r["issues"])}); continue
        p = pay[uid]
        pb = _part_b(p["gross"], p["tds"], cfg, extras_map.get(uid))
        prev = await db.form16_records.find_one(
            {"company_id": company_id, "fy": fy, "user_id": uid}, {"_id": 0, "version": 1})
        version = int((prev or {}).get("version") or 0) + 1
        rec = {
            "record_id": f"f16_{uuid.uuid4().hex[:12]}",
            "company_id": company_id, "fy": fy, "user_id": uid,
            "employee_code": emp.get("employee_code"), "name": emp.get("name"),
            "father_name": emp.get("father_name"), "pan": str(emp.get("pan") or "").upper(),
            "designation": emp.get("designation"), "address": emp.get("address"),
            "doj": emp.get("date_of_joining"),
            "employer": {"name": company.get("name"), "address": company.get("address"),
                         "pan": company.get("pan"), "tan": company.get("tan")},
            "monthly": p["monthly"], "part_b": pb,
            "extras": extras_map.get(uid) or {},
            "version": version, "status": "generated",
            "generated_by": admin.get("user_id"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.form16_records.update_one(
            {"company_id": company_id, "fy": fy, "user_id": uid},
            {"$set": rec}, upsert=True)
        await db.form16_audit.insert_one({
            "at": rec["generated_at"], "by": admin.get("user_id"),
            "action": "generate" if version == 1 else "regenerate",
            "record_id": rec["record_id"], "user_id": uid, "fy": fy,
            "company_id": company_id, "version": version})
        done.append({"user_id": uid, "record_id": rec["record_id"], "version": version})
    return {"ok": True, "generated": done, "skipped": skipped}


def _build_pdf(rec: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors as C
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle)
    from reportlab.lib.styles import ParagraphStyle
    T = ParagraphStyle("t", fontSize=13, fontName="Helvetica-Bold", alignment=1)
    S = ParagraphStyle("s", fontSize=8.5, fontName="Helvetica", alignment=1,
                       textColor=C.HexColor("#475569"))
    H = ParagraphStyle("h", fontSize=10, fontName="Helvetica-Bold",
                       textColor=C.HexColor("#0F3D3E"), spaceBefore=8)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm,
                            topMargin=12*mm, bottomMargin=12*mm)
    pb = rec["part_b"]
    fy = rec["fy"]; ay = f"{int(fy[:4])+1}-{int(fy[:4])+2}"
    def tbl(data, widths=None):
        t = Table(data, colWidths=widths)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, C.HexColor("#CBD5E1")),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("BACKGROUND", (0, 0), (-1, 0), C.HexColor("#EEF2F7")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t
    story = [
        Paragraph("FORM NO. 16", T),
        Paragraph("[See rule 31(1)(a)] — Certificate under Section 203 of the "
                  "Income-tax Act, 1961 for tax deducted at source on salary", S),
        Spacer(1, 6),
        tbl([["Employer", "Employee"],
             [f"{rec['employer'].get('name') or ''}\nPAN: {rec['employer'].get('pan') or '—'}   "
              f"TAN: {rec['employer'].get('tan') or '—'}",
              f"{rec.get('name') or ''} ({rec.get('employee_code') or ''})\n"
              f"PAN: {rec.get('pan') or '—'}   Designation: {rec.get('designation') or '—'}"]]),
        Spacer(1, 4),
        tbl([["Financial Year", "Assessment Year", "Certificate Version", "Generated On"],
             [fy, ay, str(rec.get("version")),
              str(rec.get("generated_at"))[:10]]]),
        Paragraph("PART A — Summary of salary paid and tax deducted (from payroll records)", H),
    ]
    mrows = [["Month", "Salary Paid (₹)", "TDS Deducted (₹)"]]
    for m in rec.get("monthly") or []:
        mrows.append([m["month"], f"{m['gross']:,.2f}", f"{m['tds']:,.2f}"])
    mrows.append(["TOTAL", f"{pb['gross_salary']:,.2f}", f"{pb['tds_deducted']:,.2f}"])
    story.append(tbl(mrows, [40*mm, 60*mm, 60*mm]))
    story.append(Paragraph(f"PART B — Details of salary and tax computation "
                           f"({'New' if pb.get('regime')=='new' else 'Old'} Tax Regime)", H))
    rows = [["Particulars", "Amount (₹)"],
            ["1. Gross Salary", f"{pb['gross_salary']:,.2f}"]]
    for x in pb.get("other_income") or []:
        rows.append([f"    Add: {x['label']} (income declared)", f"{x['amount']:,.2f}"])
    rows += [["2. Less: Standard Deduction", f"{pb['standard_deduction']:,.2f}"],
             ["3. Gross Total Income", f"{pb['gross_total_income']:,.2f}"]]
    for x in pb.get("extra_deductions") or []:
        rows.append([f"    Less: {x['label']}", f"{x['amount']:,.2f}"])
    rows += [["4. Total Taxable Income", f"{pb['total_taxable_income']:,.2f}"],
             ["5. Tax on Total Income", f"{pb['tax_on_income']:,.2f}"],
             ["6. Less: Rebate u/s 87A", f"{pb['rebate_87a']:,.2f}"],
             ["7. Health & Education Cess", f"{pb['cess']:,.2f}"],
             ["8. Total Tax Liability", f"{pb['total_tax_liability']:,.2f}"],
             ["9. Total TDS Deducted", f"{pb['tds_deducted']:,.2f}"],
             ["10. Balance Tax Payable", f"{pb['balance_tax']:,.2f}"],
             ["11. Excess TDS (Refundable)", f"{pb['excess_tds']:,.2f}"]]
    story.append(tbl(rows, [110*mm, 50*mm]))
    story += [Spacer(1, 10), Paragraph(
        "Verification: I, the authorised signatory, certify that the above information is "
        "true, complete and correct based on the books of account, payroll records and "
        "TDS statements.", S), Spacer(1, 16),
        Paragraph(f"For {rec['employer'].get('name') or ''} — Authorised Signatory", S)]
    doc.build(story)
    return buf.getvalue()


@router.get("/{record_id}.pdf")
async def form16_pdf(record_id: str, authorization: Optional[str] = Header(None)):
    rec = await db.form16_records.find_one({"record_id": record_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Form 16 not found")
    await _auth(authorization, rec["company_id"])
    await db.form16_records.update_one(
        {"record_id": record_id},
        {"$set": {"downloaded_at": datetime.now(timezone.utc).isoformat()}})
    pdf = _build_pdf(rec)
    fname = f"Form16_{rec.get('employee_code')}_{rec['fy']}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/bulk.zip")
async def form16_zip(company_id: str, fy: str, authorization: Optional[str] = Header(None)):
    await _auth(authorization, company_id)
    recs = await db.form16_records.find(
        {"company_id": company_id, "fy": fy}, {"_id": 0}).to_list(3000)
    if not recs:
        raise HTTPException(status_code=404, detail="No Form 16 generated yet for this FY")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for r in recs:
            z.writestr(f"Form16_{r.get('employee_code')}_{r.get('name','')}_{fy}.pdf",
                       _build_pdf(r))
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition":
                             f'attachment; filename="Form16_{fy}.zip"'})
