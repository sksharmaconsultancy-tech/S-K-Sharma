"""Iter 126j — Monthly Challan Summary (user request).

One sheet per month listing ALL ACTIVE firms with:
  • Compliance salary finalize status (Draft / Finalized-Lock)
  • PF / ESIC challan amounts — manual entry OR auto-fetched from the
    challans uploaded via the EPFO/ESIC portal upload screen
  • "Made / Uploaded by" user names
  • Remark — writing "audit" anywhere in the remark LOCKS the row for
    everyone except the Super Admin (until they clear / change it)
  • Email the summary (SMTP) — WhatsApp is composed client-side (wa.me)

Storage: ``challan_summaries`` keyed by (company_id, month).
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import (  # noqa: E402
    bust_audit_lock_cache,
    db,
    get_user_from_token,
    require_role,
    now_iso,
    logger,
)

router = APIRouter(prefix="/api/admin", tags=["challan-summary"])


def _is_audit(remark: str) -> bool:
    return "audit" in (remark or "").strip().lower()


async def _user_name(user_id: Optional[str]) -> str:
    if not user_id:
        return ""
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "name": 1, "email": 1})
    return (u or {}).get("name") or (u or {}).get("email") or ""


@router.get("/challan-summary")
async def get_challan_summary(
    month: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])

    comp_q: Dict[str, Any] = {"active": {"$ne": False}}
    if admin["role"] == "company_admin":
        comp_q["company_id"] = admin.get("company_id")
    companies = await db.companies.find(
        comp_q, {"_id": 0, "company_id": 1, "name": 1}).sort("name", 1).to_list(500)
    cids = [c["company_id"] for c in companies]

    # Compliance finalize status per firm for this month
    runs = await db.compliance_salary_runs.find(
        {"company_id": {"$in": cids}, "month": month},
        {"_id": 0, "company_id": 1, "finalized": 1},
    ).to_list(1000)
    run_status: Dict[str, str] = {}
    for r in runs:
        # any finalized run wins over drafts
        cur = run_status.get(r["company_id"])
        st = "finalized" if r.get("finalized") else "draft"
        if cur != "finalized":
            run_status[r["company_id"]] = st

    # Uploaded challans (auto-fetch amounts + paid date + uploader)
    challans = await db.challans.find(
        {"company_id": {"$in": cids}, "month": month},
        {"_id": 0, "company_id": 1, "portal": 1, "amount": 1,
         "paid_on": 1, "created_by": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(2000)
    auto: Dict[str, Dict[str, Any]] = {}
    for ch in challans:
        key = ch["company_id"]
        slot = auto.setdefault(key, {})
        portal = "pf" if ch.get("portal") == "pf" else "esic"
        if portal not in slot:  # newest first — keep latest upload
            slot[portal] = {"amount": ch.get("amount") or 0,
                            "date": ch.get("paid_on"),
                            "by": ch.get("created_by")}

    # Manual summary rows
    docs = await db.challan_summaries.find(
        {"company_id": {"$in": cids}, "month": month}, {"_id": 0}).to_list(1000)
    manual = {d["company_id"]: d for d in docs}

    # Registered firm contacts (Firm Master header emails + first contact
    # person mobile) for the per-row Email / WhatsApp send buttons.
    fms = await db.firm_masters.find(
        {"company_id": {"$in": cids}},
        {"_id": 0, "company_id": 1, "header.email_1": 1,
         "header.email_2": 1, "contact_persons": 1},
    ).to_list(1000)
    fm_map = {f["company_id"]: f for f in fms}

    name_cache: Dict[str, str] = {}

    async def _nm(uid: Optional[str]) -> str:
        if not uid:
            return ""
        if uid not in name_cache:
            name_cache[uid] = await _user_name(uid)
        return name_cache[uid]

    rows = []
    for c in companies:
        cid = c["company_id"]
        m = manual.get(cid) or {}
        a = auto.get(cid) or {}
        pf_auto = (a.get("pf") or {})
        esic_auto = (a.get("esic") or {})
        pf_amount = m.get("pf_amount")
        esic_amount = m.get("esic_amount")
        fm = fm_map.get(cid) or {}
        hdr = fm.get("header") or {}
        reg_email = (hdr.get("email_1") or hdr.get("email_2") or "") or ""
        reg_wa = next(
            (str(cp.get("mobile")) for cp in (fm.get("contact_persons") or [])
             if cp.get("mobile")), "")
        rows.append({
            "company_id": cid,
            "firm_name": c.get("name") or "",
            "salary_status": run_status.get(cid) or "not_processed",
            "remark": m.get("remark") or "",
            "is_audit": bool(m.get("is_audit")),
            # effective = manual override else auto-fetched from uploads
            "pf_amount": pf_amount if pf_amount is not None else (pf_auto.get("amount") or None),
            "pf_source": "manual" if pf_amount is not None else ("auto" if pf_auto else None),
            "pf_by_name": m.get("pf_by_name") or await _nm(pf_auto.get("by")),
            "pf_date": m.get("pf_date") or pf_auto.get("date"),
            "esic_amount": esic_amount if esic_amount is not None else (esic_auto.get("amount") or None),
            "esic_source": "manual" if esic_amount is not None else ("auto" if esic_auto else None),
            "esic_by_name": m.get("esic_by_name") or await _nm(esic_auto.get("by")),
            "esic_date": m.get("esic_date") or esic_auto.get("date"),
            "reg_email": reg_email,
            "reg_whatsapp": reg_wa,
            "updated_at": m.get("updated_at"),
        })
    return {"month": month, "rows": rows}


@router.patch("/challan-summary/{company_id}/{month}")
async def save_challan_summary_row(
    company_id: str,
    month: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not your firm")

    existing = await db.challan_summaries.find_one(
        {"company_id": company_id, "month": month}, {"_id": 0}) or {}
    if existing.get("is_audit") and admin["role"] != "super_admin":
        raise HTTPException(
            status_code=423,
            detail="This firm is marked as AUDIT — locked until the Super Admin takes action.",
        )

    name = admin.get("name") or admin.get("email") or ""
    upd: Dict[str, Any] = {"updated_at": now_iso()}
    if "pf_amount" in payload:
        v = payload.get("pf_amount")
        upd["pf_amount"] = float(v) if v not in (None, "") else None
        upd["pf_by"] = admin["user_id"]
        upd["pf_by_name"] = name
    if "esic_amount" in payload:
        v = payload.get("esic_amount")
        upd["esic_amount"] = float(v) if v not in (None, "") else None
        upd["esic_by"] = admin["user_id"]
        upd["esic_by_name"] = name
    if "pf_date" in payload:
        upd["pf_date"] = str(payload.get("pf_date") or "").strip() or None
    if "esic_date" in payload:
        upd["esic_date"] = str(payload.get("esic_date") or "").strip() or None
    if "remark" in payload:
        remark = (payload.get("remark") or "").strip()
        upd["remark"] = remark
        upd["is_audit"] = _is_audit(remark)
        upd["remark_by"] = admin["user_id"]
        upd["remark_by_name"] = name

    await db.challan_summaries.update_one(
        {"company_id": company_id, "month": month},
        {"$set": upd, "$setOnInsert": {"company_id": company_id, "month": month}},
        upsert=True,
    )
    if "remark" in payload:
        # The global write-block middleware caches locked firm ids — bust
        # it so an Audit remark takes effect (or clears) immediately.
        bust_audit_lock_cache()
    logger.info("[challan-summary] %s %s saved by %s (%s)",
                company_id, month, admin["user_id"], list(upd.keys()))
    return {"ok": True, "is_audit": upd.get("is_audit", existing.get("is_audit", False))}


@router.post("/challan-summary/{company_id}/{month}/send-email")
async def email_firm_challan_summary(
    company_id: str,
    month: str,
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """Send ONE firm's challan summary to its registered email (Firm
    Master header email_1/email_2) — or to an override typed by the admin."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])

    from routes.email_notifications import _get_settings, _send_and_log  # noqa: E402
    settings = await _get_settings()
    if not settings:
        raise HTTPException(status_code=400, detail="SMTP settings not configured")

    to_email = (payload.get("to") or "").strip()
    if not to_email:
        fm = await db.firm_masters.find_one(
            {"company_id": company_id},
            {"_id": 0, "header.email_1": 1, "header.email_2": 1})
        hdr = (fm or {}).get("header") or {}
        to_email = (hdr.get("email_1") or hdr.get("email_2") or "").strip()
    if not to_email:
        raise HTTPException(
            status_code=400,
            detail="No registered email for this firm — add it in Firm Master.",
        )

    data = await get_challan_summary(month=month, authorization=authorization)
    row = next((r for r in data["rows"] if r["company_id"] == company_id), None)
    if not row:
        raise HTTPException(status_code=404, detail="Firm not found in summary")

    status = {"finalized": "FINALIZED", "draft": "DRAFT"}.get(
        row["salary_status"], "NOT PROCESSED")
    lines = [
        f"Challan Summary — {row['firm_name']} — {month}", "",
        f"Salary Status: {status}",
        "PF Challan: " + (f"₹{row['pf_amount']:.0f}" if row.get("pf_amount") else "—")
        + (f" | Date: {row['pf_date']}" if row.get("pf_date") else "")
        + (f" | By: {row['pf_by_name']}" if row.get("pf_by_name") else ""),
        "ESIC Challan: " + (f"₹{row['esic_amount']:.0f}" if row.get("esic_amount") else "—")
        + (f" | Date: {row['esic_date']}" if row.get("esic_date") else "")
        + (f" | By: {row['esic_by_name']}" if row.get("esic_by_name") else ""),
    ]
    if row.get("remark"):
        lines.append(f"Remark: {row['remark']}")
    if row.get("is_audit"):
        lines.append("⚠ FIRM UNDER AUDIT LOCK")
    entry = await _send_and_log(
        settings, to_email,
        f"Challan Summary — {row['firm_name']} — {month}",
        "\n".join(lines), "challan_summary_firm")
    return {"ok": entry["status"] == "sent", "to": to_email,
            "status": entry["status"], "error": entry.get("error")}


@router.post("/challan-summary/email")
async def email_challan_summary(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    month = (payload.get("month") or "").strip()
    if not month:
        raise HTTPException(status_code=400, detail="month is required")
    to_email = (payload.get("to") or admin.get("email") or "").strip()
    if not to_email:
        raise HTTPException(status_code=400, detail="No recipient email")

    from routes.email_notifications import _get_settings, _send_and_log  # noqa: E402
    settings = await _get_settings()
    if not settings:
        raise HTTPException(status_code=400, detail="SMTP settings not configured")

    data = await get_challan_summary(month=month, authorization=authorization)
    lines = [f"Monthly Challan Summary — {month}", ""]
    for r in data["rows"]:
        status = {"finalized": "FINALIZED", "draft": "DRAFT"}.get(
            r["salary_status"], "NOT PROCESSED")
        lines.append(
            f"• {r['firm_name']} — Salary: {status}"
            + (f" | PF: ₹{r['pf_amount']:.0f} ({r['pf_by_name']})" if r.get("pf_amount") else " | PF: —")
            + (f" | ESIC: ₹{r['esic_amount']:.0f} ({r['esic_by_name']})" if r.get("esic_amount") else " | ESIC: —")
            + (f" | Remark: {r['remark']}" if r.get("remark") else "")
            + (" | ⚠ AUDIT LOCK" if r.get("is_audit") else "")
        )
    body = "\n".join(lines)
    entry = await _send_and_log(
        settings, to_email, f"Monthly Challan Summary — {month}", body,
        "challan_summary")
    return {"ok": entry["status"] == "sent", "to": to_email, "status": entry["status"],
            "error": entry.get("error")}
