"""
Iter 61 — Multi-Company Compliance Batch Runs + Payslip Auto-Email.

Kept in a dedicated module (see also utils/iter60_features.py). Wired into
server.py via ``register_iter61_features``.

Features:
  A. Multi-company Compliance Salary batch runs
     ─ ``POST /api/admin/compliance-salary-runs/batch`` accepts
       ``{company_ids: [...], month, ...}`` and fires off one background task
       per firm. Returns a ``batch_id`` that the caller polls.
     ─ ``GET  /api/admin/compliance-salary-runs/batches/{batch_id}`` returns
       per-firm status: queued | running | done | failed.
     ─ ``GET  /api/admin/compliance-salary-runs/batches`` lists recent batches.

  B. Payslip auto-email delivery on salary run creation
     ─ Company Master gets a new toggle: ``payslip_email_enabled`` (defaults
       to False). Only Super Admin can flip it (Web).
     ─ ``PATCH /api/admin/companies/{company_id}/payslip-email-config``
     ─ After a salary run's payslips are pushed (``generate_payslips_from_run``),
       if the flag is on, each employee with an email gets a rendered HTML
       payslip via Resend. Delivery logs into ``payslip_email_log``.
     ─ ``POST  /api/admin/salary-runs/{run_id}/email-payslips`` — manually
       trigger the same email batch (dry-run supported).
     ─ ``GET   /api/admin/payslip-email/log?company_id=...``
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Header, APIRouter
from pydantic import BaseModel

log = logging.getLogger("iter61")


# ---------------------------------------------------------------------------
# Resend helper (text + optional HTML body)
# ---------------------------------------------------------------------------
async def _send_email(
    to_emails: List[str],
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> Dict[str, Any]:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip()
    if not api_key or not to_emails:
        return {"delivered": False, "error": "missing_api_key_or_recipient"}
    body: Dict[str, Any] = {
        "from": f"S.K. Sharma & Co. <{from_email}>",
        "to": to_emails,
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        body["html"] = html_body
    try:
        async with httpx.AsyncClient(timeout=20.0) as hc:
            r = await hc.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            if r.status_code >= 300:
                return {"delivered": False, "error": f"resend_{r.status_code}"}
            return {"delivered": True, "email_id": r.json().get("id")}
    except Exception as e:  # noqa: BLE001
        return {"delivered": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------
class ComplianceBatchRequest(BaseModel):
    company_ids: List[str]
    month: str            # YYYY-MM
    employee_type: Optional[str] = None
    is_onroll: Optional[bool] = None


class PayslipEmailConfigPayload(BaseModel):
    enabled: bool


class EmailPayslipsPayload(BaseModel):
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Compliance batch implementation
# ---------------------------------------------------------------------------
async def _run_compliance_batch(
    db,
    *,
    batch_id: str,
    company_ids: List[str],
    month: str,
    employee_type: Optional[str],
    is_onroll: Optional[bool],
    admin: dict,
    compute_fn,           # server._compute_compliance_run (async)
    ComplianceRunPayloadCls,  # server.ComplianceSalaryRunRequest
) -> None:
    """Background worker: iterate each firm and persist a compliance run.
    Updates ``compliance_salary_batches.jobs[i]`` per firm."""
    for cid in company_ids:
        # Mark as running
        await db.compliance_salary_batches.update_one(
            {"batch_id": batch_id, "jobs.company_id": cid},
            {"$set": {"jobs.$.status": "running", "jobs.$.started_at": _now()}},
        )
        try:
            payload = ComplianceRunPayloadCls(
                month=month,
                company_id=cid,
                employee_type=employee_type,
                is_onroll=is_onroll,
            )
            run = await compute_fn(admin, payload)
            run["run_id"] = f"crun_{uuid.uuid4().hex[:12]}"
            run["created_via"] = "batch"
            run["batch_id"] = batch_id
            await db.compliance_salary_runs.insert_one(run)
            await db.compliance_salary_batches.update_one(
                {"batch_id": batch_id, "jobs.company_id": cid},
                {"$set": {
                    "jobs.$.status": "done",
                    "jobs.$.ended_at": _now(),
                    "jobs.$.run_id": run["run_id"],
                    "jobs.$.total_employees": run.get("employees_count"),
                }},
            )
        except Exception as e:  # noqa: BLE001
            log.exception("Compliance batch run for %s failed", cid)
            await db.compliance_salary_batches.update_one(
                {"batch_id": batch_id, "jobs.company_id": cid},
                {"$set": {
                    "jobs.$.status": "failed",
                    "jobs.$.ended_at": _now(),
                    "jobs.$.error": str(e)[:300],
                }},
            )
    # Mark batch overall status
    doc = await db.compliance_salary_batches.find_one({"batch_id": batch_id}, {"_id": 0, "jobs": 1})
    jobs = (doc or {}).get("jobs") or []
    any_failed = any(j.get("status") == "failed" for j in jobs)
    await db.compliance_salary_batches.update_one(
        {"batch_id": batch_id},
        {"$set": {
            "status": "completed_with_errors" if any_failed else "completed",
            "ended_at": _now(),
        }},
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Payslip email helpers
# ---------------------------------------------------------------------------
def _inr(n: Any) -> str:
    try:
        return "₹" + f"{float(n):,.2f}"
    except Exception:
        return "—"


def _payslip_html(company_name: str, month: str, employee: dict, row: dict) -> str:
    """Render a small responsive HTML payslip email."""
    lines = [
        ("Basic", row.get("base_pay")),
        ("HRA", row.get("hra")),
        ("Bonus", row.get("bonus")),
        ("Overtime", row.get("ot_pay")),
        ("Other Earnings", row.get("other_earning")),
        ("Gross", row.get("gross")),
        ("PF (Employee)", row.get("pf") or row.get("pf_employee")),
        ("ESIC (Employee)", row.get("esic") or row.get("esic_employee")),
        ("Professional Tax", row.get("pt")),
        ("TDS", row.get("tds")),
        ("Advance / Loan", row.get("advance")),
        ("Total Deductions", row.get("total_deduction")),
        ("Net Pay", row.get("net")),
    ]
    rows_html = "".join(
        f"<tr><td style='padding:6px 12px;color:#444'>{lbl}</td>"
        f"<td style='padding:6px 12px;text-align:right;color:#111;"
        f"{'font-weight:700' if lbl in ('Gross','Net Pay','Total Deductions') else ''}'>"
        f"{_inr(val)}</td></tr>"
        for lbl, val in lines if val is not None
    )
    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:600px;margin:auto;background:#fff;padding:24px;border:1px solid #e5e7eb;border-radius:12px">
      <div style="text-align:center;margin-bottom:16px">
        <h2 style="margin:0;color:#1a1a1a">S.K. Sharma &amp; Co.</h2>
        <p style="color:#666;margin:4px 0 0 0;font-size:13px">Payslip for {month}</p>
      </div>
      <div style="background:#f9fafb;padding:12px 16px;border-radius:8px;margin-bottom:16px">
        <p style="margin:0;color:#111"><b>{employee.get('name','')}</b>
          {(' · ' + employee['employee_code']) if employee.get('employee_code') else ''}</p>
        <p style="margin:2px 0 0 0;color:#666;font-size:12px">{company_name}</p>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:14px">
        {rows_html}
      </table>
      <p style="color:#999;font-size:11px;margin-top:20px;text-align:center">
        This is a system-generated payslip. Contact your admin if anything looks off.
      </p>
    </div>
    """


async def _email_payslips_for_run(db, run_id: str, *, dry_run: bool = False) -> Dict[str, Any]:
    """Send an HTML payslip email to each employee in the given salary run,
    provided the firm has ``payslip_email_enabled=True``."""
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    cid = run.get("company_id")
    company = await db.companies.find_one(
        {"company_id": cid},
        {"_id": 0, "name": 1, "payslip_email_enabled": 1},
    ) or {}
    if not company.get("payslip_email_enabled"):
        return {
            "delivered": 0, "skipped_no_email": 0,
            "note": "payslip_email_enabled=false on this company",
        }

    company_name = company.get("name") or ""
    delivered = 0
    skipped_no_email = 0
    failed: List[Dict[str, Any]] = []

    for r in (run.get("rows") or []):
        uid = r.get("user_id")
        if not uid:
            continue
        emp = await db.users.find_one(
            {"user_id": uid},
            {"_id": 0, "email": 1, "name": 1, "employee_code": 1},
        )
        if not emp or not emp.get("email"):
            skipped_no_email += 1
            continue

        subject = f"[{company_name}] Payslip — {run.get('month')}"
        text_body = (
            f"Payslip for {emp.get('name')} — {run.get('month')}\n"
            f"Gross: {_inr(r.get('gross'))}\n"
            f"Deductions: {_inr(r.get('total_deduction'))}\n"
            f"Net: {_inr(r.get('net'))}\n"
        )
        html_body = _payslip_html(company_name, run.get("month") or "", emp, r)

        if dry_run:
            delivered += 1
            continue

        result = await _send_email(
            to_emails=[emp["email"]],
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
        await db.payslip_email_log.insert_one({
            "log_id": f"pel_{uuid.uuid4().hex[:12]}",
            "company_id": cid,
            "user_id": uid,
            "email": emp.get("email"),
            "month": run.get("month"),
            "salary_run_id": run_id,
            "delivered": result.get("delivered", False),
            "email_id": result.get("email_id"),
            "error": result.get("error"),
            "sent_at": _now(),
        })
        if result.get("delivered"):
            delivered += 1
        else:
            failed.append({"user_id": uid, "email": emp["email"], "error": result.get("error")})

    return {
        "run_id": run_id,
        "company_id": cid,
        "dry_run": dry_run,
        "delivered": delivered,
        "skipped_no_email": skipped_no_email,
        "failed_count": len(failed),
        "failed_sample": failed[:20],
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register_iter61_features(
    app: FastAPI,
    api: APIRouter,
    db,
    now_iso_fn,
    get_user_from_token,
    require_role,
    require_super_admin_strict,
    *,
    server_module,        # the server module, for _compute_compliance_run + payload cls
):
    """Attach iter61 endpoints. Requires the server module handles that own
    ``_compute_compliance_run`` and the ``ComplianceSalaryRunRequest`` class."""

    # ---------------- Multi-company compliance batch -------------------
    @api.post("/admin/compliance-batches")
    async def create_compliance_batch(
        payload: ComplianceBatchRequest,
        background_tasks: BackgroundTasks,
        authorization: Optional[str] = Header(None),
    ):
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin"])
        if not payload.company_ids:
            raise HTTPException(status_code=400, detail="Pick at least one company")
        if len(payload.company_ids) > 40:
            raise HTTPException(status_code=400, detail="Max 40 companies per batch")

        # Sanity: verify each company exists
        found = await db.companies.find(
            {"company_id": {"$in": payload.company_ids}}, {"_id": 0, "company_id": 1, "name": 1},
        ).to_list(len(payload.company_ids))
        if len(found) != len(payload.company_ids):
            raise HTTPException(status_code=404, detail="One or more companies not found")
        name_by_cid = {c["company_id"]: c["name"] for c in found}

        batch_id = f"bch_{uuid.uuid4().hex[:12]}"
        doc = {
            "batch_id": batch_id,
            "month": payload.month,
            "employee_type": payload.employee_type,
            "is_onroll": payload.is_onroll,
            "status": "running",
            "created_at": _now(),
            "created_by": admin["user_id"],
            "jobs": [
                {
                    "company_id": cid,
                    "company_name": name_by_cid.get(cid, ""),
                    "status": "queued",
                }
                for cid in payload.company_ids
            ],
        }
        await db.compliance_salary_batches.insert_one(doc)

        compute_fn = server_module._compute_compliance_run
        payload_cls = server_module.ComplianceSalaryRunCreate

        async def _run():
            await _run_compliance_batch(
                db,
                batch_id=batch_id,
                company_ids=payload.company_ids,
                month=payload.month,
                employee_type=payload.employee_type,
                is_onroll=payload.is_onroll,
                admin=admin,
                compute_fn=compute_fn,
                ComplianceRunPayloadCls=payload_cls,
            )

        background_tasks.add_task(_run)
        doc.pop("_id", None)
        return doc

    @api.get("/admin/compliance-batches")
    async def list_compliance_batches(
        limit: int = 30, authorization: Optional[str] = Header(None),
    ):
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin"])
        items = await db.compliance_salary_batches.find(
            {}, {"_id": 0},
        ).sort("created_at", -1).to_list(min(limit, 100))
        return {"items": items}

    @api.get("/admin/compliance-batches/{batch_id}")
    async def get_compliance_batch(
        batch_id: str, authorization: Optional[str] = Header(None),
    ):
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin"])
        doc = await db.compliance_salary_batches.find_one({"batch_id": batch_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Batch not found")
        return doc

    # ---------------- Payslip email config / trigger --------------------
    @api.get("/admin/companies/{company_id}/payslip-email-config")
    async def get_payslip_email_config(
        company_id: str, authorization: Optional[str] = Header(None),
    ):
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin", "company_admin"])
        if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
            raise HTTPException(status_code=403, detail="Not authorised")
        c = await db.companies.find_one(
            {"company_id": company_id},
            {"_id": 0, "payslip_email_enabled": 1, "name": 1},
        )
        if not c:
            raise HTTPException(status_code=404, detail="Company not found")
        return {
            "company_id": company_id,
            "name": c.get("name"),
            "enabled": bool(c.get("payslip_email_enabled")),
        }

    @api.put("/admin/companies/{company_id}/payslip-email-config")
    async def set_payslip_email_config(
        company_id: str,
        payload: PayslipEmailConfigPayload,
        authorization: Optional[str] = Header(None),
    ):
        admin = await get_user_from_token(authorization)
        require_super_admin_strict(admin)
        c = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "company_id": 1})
        if not c:
            raise HTTPException(status_code=404, detail="Company not found")
        await db.companies.update_one(
            {"company_id": company_id},
            {"$set": {"payslip_email_enabled": bool(payload.enabled)}},
        )
        return {"ok": True, "enabled": bool(payload.enabled)}

    @api.post("/admin/salary-runs/{run_id}/email-payslips")
    async def email_payslips_for_run(
        run_id: str,
        payload: EmailPayslipsPayload,
        authorization: Optional[str] = Header(None),
    ):
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin"])
        return await _email_payslips_for_run(db, run_id, dry_run=payload.dry_run)

    @api.get("/admin/payslip-email/log")
    async def list_payslip_email_log(
        company_id: Optional[str] = None,
        salary_run_id: Optional[str] = None,
        limit: int = 100,
        authorization: Optional[str] = Header(None),
    ):
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin", "company_admin"])
        q: Dict[str, Any] = {}
        if admin["role"] == "company_admin":
            q["company_id"] = admin.get("company_id")
        elif company_id:
            q["company_id"] = company_id
        if salary_run_id:
            q["salary_run_id"] = salary_run_id
        items = await db.payslip_email_log.find(
            q, {"_id": 0},
        ).sort("sent_at", -1).to_list(min(limit, 500))
        return {"items": items}

    # Hook exposed so server.py can trigger email delivery after payslip
    # generation. We attach the function on the app state so it can be
    # imported without a circular reference.
    app.state.email_payslips_for_run = _email_payslips_for_run
    log.info("[iter61] registered")
