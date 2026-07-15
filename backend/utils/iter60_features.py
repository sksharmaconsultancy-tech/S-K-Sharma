"""
Iter 60 — Bulk-import Employees, Auto-Email Cron, and Portal Automation.

Kept as a separate module to prevent server.py from ballooning further.
Everything is wired via ``register_iter60_features`` which the main server
calls after ``app.include_router(api)``.

Features:
  A. Bulk-import Employees via Attendance-Sheet upload
     ─ New endpoint ``POST /api/admin/attendance-sheet/bulk-import-employees``
     ─ Detects rows whose employee_code/phone doesn't exist yet and creates
       users with ``pin_must_change=True``, ``approved=False``.
     ─ Auto-creates missing Group / Department / Designation masters.

  B. Auto-email Attendance Sheet cron (Resend)
     ─ APScheduler cron job at 09:00 IST on the 1st of every month.
     ─ For each company with ``attendance_email_recipients`` configured,
       generate the XLSX for the previous month and email it via Resend
       as a base64 attachment.
     ─ Fallback recipient = company_admin's email.
     ─ Admin endpoints to configure recipients and trigger the job now.

  C. Portal Automation (EPFO ECR & ESIC challan uploads)
     ─ Assisted Playwright automation with screenshot audit trail.
     ─ Jobs persisted to ``automation_jobs`` collection.
     ─ Each step captured as a screenshot (base64) stored on the job doc.
     ─ Pauses when captcha/OTP is detected so super-admin can complete
       manually in the same browser session.
"""
from __future__ import annotations

import asyncio
import base64
import calendar
import io
import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Header, APIRouter
from pydantic import BaseModel

log = logging.getLogger("iter60")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
INDIA_TZ = timezone(timedelta(hours=5, minutes=30))


def _prev_month_yyyy_mm(today: Optional[date] = None) -> str:
    today = today or datetime.now(INDIA_TZ).date()
    first_of_month = today.replace(day=1)
    last_of_prev = first_of_month - timedelta(days=1)
    return f"{last_of_prev.year:04d}-{last_of_prev.month:02d}"


async def _send_email_with_attachment(
    to_emails: List[str],
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    attachments: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Send an email via Resend with optional base64 attachments.

    ``attachments`` items must be dicts with ``filename`` and ``content``
    (base64-encoded string) — matches Resend's API.
    """
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
    if attachments:
        body["attachments"] = attachments
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
                return {
                    "delivered": False,
                    "error": f"resend_status_{r.status_code}",
                    "body": r.text[:200],
                }
            data = r.json()
            return {"delivered": True, "email_id": data.get("id")}
    except Exception as e:  # noqa: BLE001
        return {"delivered": False, "error": str(e)}


async def _find_or_create_master(
    db, *, company_id: str, type_: str, name: str, created_by: str, now_iso_fn,
) -> str:
    """Return master_id for the given (company, type, name), creating on miss."""
    name = (name or "").strip()
    if not name:
        return ""
    existing = await db.masters.find_one(
        {"company_id": company_id, "type": type_, "name": name},
        {"_id": 0, "master_id": 1},
    )
    if existing:
        return existing["master_id"]
    master_id = f"mst_{uuid.uuid4().hex[:12]}"
    await db.masters.insert_one({
        "master_id": master_id,
        "type": type_,
        "company_id": company_id,
        "name": name,
        "member_user_ids": [],
        "created_at": now_iso_fn(),
        "updated_at": now_iso_fn(),
        "created_by": created_by,
    })
    return master_id


# ---------------------------------------------------------------------------
# Pydantic payloads
# ---------------------------------------------------------------------------
class BulkImportEmployeesPayload(BaseModel):
    company_id: str
    month: str
    headers: List[str]
    body: List[List[Any]]
    mapping: Dict[str, int]
    default_group_id: Optional[str] = None   # if sheet has no group column
    dry_run: bool = False


class AttendanceEmailConfigPayload(BaseModel):
    recipients: List[str]
    enabled: bool = True


class PortalAutomationJobPayload(BaseModel):
    portal: str            # "epfo" | "esic"
    company_id: str
    compliance_salary_run_id: str


class BulkEmployeeCorrection(BaseModel):
    user_id: str
    # any field below being non-None means "update this field"
    name: Optional[str] = None
    employee_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    doj: Optional[str] = None
    salary_monthly: Optional[float] = None
    basic_salary: Optional[float] = None
    # Iter 134 (user spec) — Compliance Basic + per-head compliance
    # allowance amounts (head -> amount). Editing these keeps the flat
    # master fields (hra / conveyance / over_time / other) in sync.
    compliance_basic: Optional[float] = None
    allowances: Optional[Dict[str, float]] = None
    uan_no: Optional[str] = None
    esi_ip_no: Optional[str] = None
    pf_no: Optional[str] = None
    aadhaar_no: Optional[str] = None
    name_as_per_aadhar: Optional[str] = None
    pan_no: Optional[str] = None
    name_as_per_pan: Optional[str] = None
    bank_account: Optional[str] = None
    bank_account_no: Optional[str] = None   # legacy — mapped to bank_account
    bank_ifsc: Optional[str] = None
    employee_group_id: Optional[str] = None   # master_id (of type=group)
    active: Optional[bool] = None


class BulkEmployeeCorrectionPayload(BaseModel):
    company_id: Optional[str] = None
    # Iter 63 — Cross-firm bulk correction. If supplied (non-empty), rows
    # can span multiple firms; employees are looked up in the union scope.
    company_ids: Optional[List[str]] = None
    corrections: List[BulkEmployeeCorrection]
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Auto-email cron implementation
# ---------------------------------------------------------------------------
async def _run_attendance_email_batch(
    db, *, month: Optional[str] = None, company_id_filter: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Send the attendance-sheet XLSX to each firm's configured recipients.

    Called by the APScheduler cron AND manually via the admin trigger endpoint.
    ``month`` defaults to the previous calendar month.
    """
    from utils.master_sheet import build_master_sheet_xlsx

    target_month = month or _prev_month_yyyy_mm()
    q: Dict[str, Any] = {"attendance_email_enabled": {"$ne": False}}
    if company_id_filter:
        q["company_id"] = company_id_filter

    companies = await db.companies.find(q, {"_id": 0}).to_list(500)
    results: List[Dict[str, Any]] = []

    for c in companies:
        recipients = list(c.get("attendance_email_recipients") or [])
        # Fallback to company_admin email if no explicit list
        if not recipients:
            admin = await db.users.find_one(
                {"company_id": c["company_id"], "role": "company_admin"},
                {"_id": 0, "email": 1},
            )
            if admin and admin.get("email"):
                recipients = [admin["email"]]

        if not recipients:
            results.append({"company_id": c["company_id"], "skipped": "no_recipients"})
            continue

        # Build XLSX
        employees = await db.users.find(
            {"role": "employee", "company_id": c["company_id"]},
            {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1, "doj": 1, "department": 1},
        ).to_list(2000)
        # Attendance snapshot
        try:
            y, m = int(target_month[:4]), int(target_month[5:7])
            days_in_month = calendar.monthrange(y, m)[1]
        except (ValueError, IndexError):
            results.append({"company_id": c["company_id"], "error": "bad_month"})
            continue
        date_from = f"{y:04d}-{m:02d}-01"
        date_to = f"{y:04d}-{m:02d}-{days_in_month:02d}"
        days_by_user: Dict[str, int] = {}
        if employees:
            user_ids = [e["user_id"] for e in employees]
            async for r in db.attendance.find(
                {"user_id": {"$in": user_ids}, "date": {"$gte": date_from, "$lte": date_to},
                 "kind": "in"},
                {"_id": 0, "user_id": 1, "date": 1},
            ):
                days_by_user[r["user_id"]] = days_by_user.get(r["user_id"], 0) + 1

        xlsx_bytes = build_master_sheet_xlsx(
            company_name=c.get("name") or "S.K. Sharma & Co.",
            month=target_month,
            employees=employees,
            attendance_days_by_user=days_by_user,
        )
        filename = f"AttendanceSheet_{(c.get('name') or 'company').replace(' ', '_')}_{target_month}.xlsx"

        if dry_run:
            results.append({
                "company_id": c["company_id"],
                "recipients": recipients,
                "employees": len(employees),
                "dry_run": True,
            })
            continue

        # Email
        att = base64.b64encode(xlsx_bytes).decode("ascii")
        subject = f"[{c.get('name')}] Attendance Sheet — {target_month}"
        text_body = (
            f"Attached: attendance sheet for {c.get('name')} — {target_month}.\n\n"
            "Please fill in Gross, Advance and TDS and return by the 5th so we can process payroll.\n\n"
            "— S.K. Sharma & Co."
        )
        html_body = (
            f"<div style='font-family:sans-serif'><p>Hi team,</p>"
            f"<p>Please find attached the attendance sheet for <b>{c.get('name')}</b> — "
            f"<b>{target_month}</b>. Fill in Gross, Advance and TDS and return by the 5th.</p>"
            f"<p>— S.K. Sharma &amp; Co.</p></div>"
        )
        send_result = await _send_email_with_attachment(
            to_emails=recipients,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            attachments=[{"filename": filename, "content": att}],
        )
        # Persist send log
        await db.attendance_email_log.insert_one({
            "log_id": f"aem_{uuid.uuid4().hex[:12]}",
            "company_id": c["company_id"],
            "month": target_month,
            "recipients": recipients,
            "delivered": send_result.get("delivered", False),
            "email_id": send_result.get("email_id"),
            "error": send_result.get("error"),
            "sent_at": datetime.now(timezone.utc).isoformat(),
        })
        results.append({
            "company_id": c["company_id"],
            "recipients": recipients,
            "delivered": send_result.get("delivered", False),
            "email_id": send_result.get("email_id"),
            "error": send_result.get("error"),
        })

    return {"month": target_month, "results": results}


# ---------------------------------------------------------------------------
# Portal Automation implementation (Playwright)
# ---------------------------------------------------------------------------
_PORTAL_URLS = {
    "epfo": "https://unifiedportal-emp.epfindia.gov.in/epfo/",
    "esic": "https://www.esic.in/EmployerPortal/ESICInsurance1/Employer_Portal.aspx",
}


async def _run_portal_automation(db, *, job_id: str, portal_creds_helper=None):
    """Best-effort Playwright automation. Screenshots each step, pauses on
    OTP/captcha. Screenshots are stored base64-encoded on the job doc so
    the super admin can review them from the UI.
    """
    from utils.portal_creds import decrypt_password  # optional decrypt helper
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        await db.automation_jobs.update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "failed",
                "error": "playwright_not_installed",
                "ended_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        return

    job = await db.automation_jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not job:
        return
    portal = job["portal"]
    url = _PORTAL_URLS.get(portal)
    if not url:
        await db.automation_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "failed", "error": f"unknown_portal_{portal}"}},
        )
        return

    # Fetch portal credentials for this company
    cred_doc = await db.portal_credentials.find_one(
        {"company_id": job["company_id"], "service_name": portal},
        {"_id": 0},
    )
    username = ""
    password = ""
    if cred_doc:
        username = cred_doc.get("username") or ""
        try:
            if cred_doc.get("encrypted_password"):
                password = decrypt_password(cred_doc["encrypted_password"]) or ""
        except Exception:
            password = ""

    steps: List[Dict[str, Any]] = []

    async def _step(name: str, screenshot_b64: Optional[str] = None, detail: str = ""):
        steps.append({
            "name": name,
            "detail": detail,
            "screenshot_b64": screenshot_b64,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        await db.automation_jobs.update_one(
            {"job_id": job_id}, {"$set": {"steps": steps, "status": "running"}}
        )

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            shot = await page.screenshot(full_page=False, type="jpeg", quality=40)
            await _step("Opened portal", base64.b64encode(shot).decode("ascii"), url)

            # Attempt to fill username/password on best-effort common selectors.
            if username:
                for sel in ["input[name*=username]", "input[id*=Username]",
                            "input[id*=Login]", "input[type=text]"]:
                    try:
                        await page.fill(sel, username, timeout=2000)
                        break
                    except Exception:
                        continue
            if password:
                for sel in ["input[type=password]"]:
                    try:
                        await page.fill(sel, password, timeout=2000)
                        break
                    except Exception:
                        continue

            shot = await page.screenshot(full_page=False, type="jpeg", quality=40)
            await _step("Credentials pre-filled", base64.b64encode(shot).decode("ascii"),
                        f"username={username[:4]}***" if username else "no credentials configured")

            # Detect captcha — if the page has an <img> with a captcha-like src
            # we pause and hand back to the super admin.
            has_captcha = False
            try:
                # Common captcha selectors used on gov portals
                has_captcha = await page.evaluate("""
                    () => !!document.querySelector(
                        'img[src*=captcha], img[src*=Captcha], img[id*=Captcha], img[id*=captcha]'
                    )
                """)
            except Exception:
                pass

            if has_captcha:
                shot = await page.screenshot(full_page=False, type="jpeg", quality=40)
                await _step(
                    "Captcha detected — manual completion required",
                    base64.b64encode(shot).decode("ascii"),
                    "Portal shows a captcha. Log into the portal manually to finish the upload.",
                )
                await db.automation_jobs.update_one(
                    {"job_id": job_id},
                    {"$set": {
                        "status": "paused_captcha",
                        "ended_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                await browser.close()
                return

            # We don't attempt actual upload (portals require MFA/OTP);
            # provide guidance instead.
            await _step(
                "Ready for manual upload",
                None,
                "Automated login harness reached the portal home. "
                "Continue the file upload manually from your desk.",
            )
            await db.automation_jobs.update_one(
                {"job_id": job_id},
                {"$set": {
                    "status": "completed_login",
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            await browser.close()
    except Exception as e:  # noqa: BLE001
        log.exception("Portal automation failed")
        await db.automation_jobs.update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "failed",
                "error": str(e)[:500],
                "ended_at": datetime.now(timezone.utc).isoformat(),
            }},
        )


# ---------------------------------------------------------------------------
# Bulk-import employees implementation
# ---------------------------------------------------------------------------
async def _bulk_import_employees_impl(
    db, *, payload: BulkImportEmployeesPayload, admin: dict, now_iso_fn,
) -> Dict[str, Any]:
    from utils.master_sheet import import_rows_via_mapping

    company = await db.companies.find_one(
        {"company_id": payload.company_id}, {"_id": 0, "name": 1}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    records = import_rows_via_mapping(payload.headers, payload.body, payload.mapping)

    created: List[Dict[str, Any]] = []
    updated: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    new_masters: List[Dict[str, Any]] = []

    for rec in records:
        code = (rec.get("employee_code") or "").strip()
        name = (rec.get("name") or "").strip()
        phone = (rec.get("phone") or "").strip()
        email = (rec.get("email") or "").strip().lower() or None

        if not name and not code:
            skipped.append({"reason": "missing_name_and_code"})
            continue

        # Match existing employee by employee_code (preferred), then phone, then name
        query: Dict[str, Any] = {"company_id": payload.company_id, "role": "employee"}
        if code:
            existing = await db.users.find_one({**query, "employee_code": code}, {"_id": 0})
        elif phone:
            existing = await db.users.find_one({**query, "phone": phone}, {"_id": 0})
        else:
            existing = await db.users.find_one({**query, "name": name}, {"_id": 0})

        # Resolve group / department / designation masters
        group_id = payload.default_group_id or None
        if rec.get("employee_group"):
            group_id = await _find_or_create_master(
                db,
                company_id=payload.company_id, type_="group",
                name=rec["employee_group"], created_by=admin["user_id"],
                now_iso_fn=now_iso_fn,
            ) or group_id
            new_masters.append({"type": "group", "name": rec["employee_group"], "master_id": group_id})
        dept_master = None
        if rec.get("department"):
            dept_master = await _find_or_create_master(
                db,
                company_id=payload.company_id, type_="department",
                name=rec["department"], created_by=admin["user_id"],
                now_iso_fn=now_iso_fn,
            )
            new_masters.append({"type": "department", "name": rec["department"], "master_id": dept_master})
        desig_master = None
        if rec.get("designation"):
            desig_master = await _find_or_create_master(
                db,
                company_id=payload.company_id, type_="designation",
                name=rec["designation"], created_by=admin["user_id"],
                now_iso_fn=now_iso_fn,
            )
            new_masters.append({"type": "designation", "name": rec["designation"], "master_id": desig_master})

        updates: Dict[str, Any] = {}
        if rec.get("department"):
            updates["department"] = rec["department"]
        if rec.get("designation"):
            updates["designation"] = rec["designation"]
        if rec.get("doj"):
            updates["doj"] = rec["doj"]
        if "gross_salary" in rec:
            updates["salary_monthly"] = float(rec["gross_salary"] or 0)

        if existing:
            # Update existing
            if payload.dry_run:
                updated.append({"user_id": existing["user_id"], "name": name, "would_update": updates})
                continue
            if updates:
                await db.users.update_one(
                    {"user_id": existing["user_id"]}, {"$set": updates}
                )
            if group_id:
                await db.masters.update_one(
                    {"master_id": group_id},
                    {"$addToSet": {"member_user_ids": existing["user_id"]}},
                )
            updated.append({"user_id": existing["user_id"], "name": name, "updated": updates})
        else:
            # Create new employee (approved=False, pin_must_change=True)
            if payload.dry_run:
                created.append({"name": name, "employee_code": code, "would_create": True})
                continue
            uid = f"user_{uuid.uuid4().hex[:12]}"
            doc = {
                "user_id": uid,
                "role": "employee",
                "company_id": payload.company_id,
                "employee_code": code or None,
                "name": name,
                "phone": phone or None,
                "email": email,
                "department": rec.get("department"),
                "designation": rec.get("designation"),
                "doj": rec.get("doj"),
                "salary_monthly": float(rec.get("gross_salary") or 0) if "gross_salary" in rec else 0,
                "onboarded": False,
                "approved": False,
                "pin_hash": None,
                "pin_must_change": True,
                "password_hash": None,
                "created_at": now_iso_fn(),
                "created_by": admin["user_id"],
                "bulk_import_source": {
                    "month": payload.month,
                    "at": now_iso_fn(),
                },
            }
            try:
                await db.users.insert_one(doc)
            except Exception as e:  # noqa: BLE001
                skipped.append({"reason": f"insert_failed:{str(e)[:80]}", "name": name})
                continue
            if group_id:
                await db.masters.update_one(
                    {"master_id": group_id}, {"$addToSet": {"member_user_ids": uid}},
                )
            doc.pop("_id", None)
            created.append({"user_id": uid, "name": name, "employee_code": code})

    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "new_masters": [nm for nm in new_masters if nm.get("master_id")],
        "dry_run": payload.dry_run,
    }


# ---------------------------------------------------------------------------
# Registration entrypoint
# ---------------------------------------------------------------------------
def register_iter60_features(
    app: FastAPI,
    api: APIRouter,
    db,
    now_iso_fn,
    get_user_from_token,
    require_role,
    require_super_admin_strict,
):
    """Attach all Iter 60 endpoints + start the APScheduler cron."""

    # ---------------- Bulk import ---------------------------------------
    @api.post("/admin/attendance-sheet/bulk-import-employees")
    async def bulk_import_employees(
        payload: BulkImportEmployeesPayload,
        authorization: Optional[str] = Header(None),
    ):
        """Create/Update employees from a parsed attendance-sheet body. Also
        auto-creates missing Group / Department / Designation masters.

        Use ``dry_run: true`` first to preview.
        """
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin"])
        return await _bulk_import_employees_impl(
            db, payload=payload, admin=admin, now_iso_fn=now_iso_fn,
        )

    # ---------------- Bulk Employee Correction --------------------------
    @api.get("/admin/employees/bulk-correction-fields")
    async def bulk_correction_fields(
        company_id: Optional[str] = None,
        authorization: Optional[str] = Header(None),
    ):
        """Return the canonical list of fields for the correction grid.

        Iter 134 (user spec) — column set:
          * Locked identity: Emp Code, Name, Father Name, Phone, Email, DOJ
          * Editable: Department, Designation, Employee Group,
            Basic Salary (Compliance), HRA / Conv. / Other / Overtime +
            every additional allowance head ENABLED in the Firm Master,
            UAN, ESI IP, PF No., Aadhaar (+name), PAN (+name), Bank A/c, IFSC.
          * Active column removed (use the Active/Resigned filter instead).
        """
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin"])

        # Fixed allowance columns per the user's spec; firm-master heads
        # that normalise to one of these are folded in (no duplicates).
        def _norm_head(h: str) -> str:
            return "".join(ch for ch in str(h or "").lower() if ch.isalnum())

        fixed_allow = [("HRA", "hra"), ("Conv.", "conv"), ("Other", "other"),
                       ("Overtime", "overtime")]
        fixed_norms = {n for _, n in fixed_allow} | {"conveyance", "overtime", "overtime", "othersallowance", "others"}
        allow_fields = [
            {"key": f"allow:{lbl}", "label": lbl, "type": "allowance"}
            for lbl, _ in fixed_allow
        ]
        if company_id:
            fm = await db.firm_masters.find_one(
                {"company_id": company_id}, {"_id": 0, "allowances": 1}) or {}
            for head, on in (fm.get("allowances") or {}).items():
                if not on:
                    continue
                if _norm_head(head) in fixed_norms:
                    continue
                allow_fields.append(
                    {"key": f"allow:{head}", "label": head, "type": "allowance"})

        return {"fields": [
            {"key": "employee_code", "label": "Emp Code", "type": "text"},
            {"key": "name", "label": "Name", "type": "text"},
            {"key": "father_name", "label": "Father Name", "type": "text"},
            {"key": "department", "label": "Department", "type": "master:department"},
            {"key": "designation", "label": "Designation", "type": "master:designation"},
            {"key": "phone", "label": "Phone", "type": "text"},
            {"key": "email", "label": "Email", "type": "email"},
            {"key": "doj", "label": "DOJ (YYYY-MM-DD)", "type": "text"},
            {"key": "employee_group_id", "label": "Employee Group", "type": "master:group"},
            {"key": "compliance_basic", "label": "Basic Salary (Compliance)", "type": "number"},
            *allow_fields,
            {"key": "uan_no", "label": "UAN No.", "type": "text"},
            {"key": "esi_ip_no", "label": "ESI IP No.", "type": "text"},
            {"key": "pf_no", "label": "PF No.", "type": "text"},
            {"key": "aadhaar_no", "label": "Aadhaar", "type": "text"},
            {"key": "name_as_per_aadhar", "label": "Name as per Aadhaar", "type": "text"},
            {"key": "pan_no", "label": "PAN", "type": "text"},
            {"key": "name_as_per_pan", "label": "Name as per PAN", "type": "text"},
            {"key": "bank_account", "label": "Bank A/c", "type": "text"},
            {"key": "bank_ifsc", "label": "IFSC", "type": "text"},
        ]}

    @api.post("/admin/employees/bulk-correction")
    async def bulk_employee_correction(
        payload: BulkEmployeeCorrectionPayload,
        authorization: Optional[str] = Header(None),
    ):
        """One-click bulk update for active employees.

        Only fields explicitly set on each row are updated. Group changes are
        also reflected in ``masters.member_user_ids`` (removes from previous
        group, adds to new). ``active=false`` marks the employee inactive
        (soft delete). Returns a per-row applied/skipped summary.
        """
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin"])

        # Iter 63 — union scope. Accept either a single company_id or a
        # list of company_ids. If both are absent, we reject.
        allowed_cids: List[str] = []
        if payload.company_ids:
            allowed_cids = [c for c in payload.company_ids if c]
        if payload.company_id and payload.company_id not in allowed_cids:
            allowed_cids.append(payload.company_id)
        if not allowed_cids:
            raise HTTPException(
                status_code=400,
                detail="Provide company_id or company_ids (at least one firm)",
            )

        # Validate all firms exist in one shot.
        found = await db.companies.find(
            {"company_id": {"$in": allowed_cids}}, {"_id": 0, "company_id": 1}
        ).to_list(len(allowed_cids))
        found_ids = {c["company_id"] for c in found}
        missing = [c for c in allowed_cids if c not in found_ids]
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"Company not found: {', '.join(missing)}",
            )

        applied: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        for row in payload.corrections:
            existing = await db.users.find_one(
                {
                    "user_id": row.user_id,
                    "company_id": {"$in": allowed_cids},
                    "role": "employee",
                },
                {"_id": 0},
            )
            if not existing:
                skipped.append({"user_id": row.user_id, "reason": "not_found"})
                continue
            row_company_id = existing.get("company_id")

            updates: Dict[str, Any] = {}
            row_dict = row.dict()
            group_change_to: Optional[str] = None
            allowance_changes: Optional[Dict[str, float]] = None
            for k, v in row_dict.items():
                if k == "user_id":
                    continue
                if v is None:
                    continue
                if k == "employee_group_id":
                    group_change_to = v  # "" clears the group
                    continue
                if k == "allowances":
                    if isinstance(v, dict) and v:
                        allowance_changes = {str(h): float(a) for h, a in v.items()
                                             if h and a is not None}
                    continue
                if k in ("salary_monthly", "basic_salary") and isinstance(v, (int, float)):
                    updates[k] = float(v)
                elif k == "compliance_basic" and isinstance(v, (int, float)):
                    # Iter 134 — Basic Salary column edits Compliance Basic
                    # and keeps the flat master basic in sync.
                    updates["compliance_basic"] = float(v)
                    updates["basic_salary"] = float(v)
                elif k == "bank_account_no":
                    # Legacy key — the employee master stores bank_account.
                    updates["bank_account"] = (v or "").strip()
                elif k == "active":
                    updates["active"] = bool(v)
                    if not v:
                        updates["exit_date"] = now_iso_fn()[:10]
                elif k == "email":
                    updates["email"] = (v or "").strip().lower() or None
                else:
                    updates[k] = (v or "").strip() if isinstance(v, str) else v

            # Iter 134 — merge per-head compliance allowance edits into
            # ``compliance_salary_allowances`` (upsert by normalised head)
            # and mirror the classic heads onto the flat master fields.
            if allowance_changes:
                def _norm(h: str) -> str:
                    return "".join(ch for ch in str(h or "").lower() if ch.isalnum())
                lines = [dict(x) for x in (existing.get("compliance_salary_allowances") or [])
                         if isinstance(x, dict)]
                for head, amount in allowance_changes.items():
                    nh = _norm(head)
                    hit = next((ln for ln in lines if _norm(ln.get("head")) == nh
                                or (nh == "conv" and _norm(ln.get("head")).startswith("conv"))
                                or (nh.startswith("conv") and _norm(ln.get("head")) == "conv")), None)
                    if hit is not None:
                        hit["amount"] = amount
                    else:
                        lines.append({"head": head, "amount": amount})
                    # Flat master-field mirrors (imported XLSX columns).
                    if nh == "hra":
                        updates["hra"] = amount
                    elif nh.startswith("conv"):
                        updates["conveyance"] = amount
                    elif nh in ("overtime", "ot"):
                        updates["over_time"] = amount
                    elif nh in ("other", "others"):
                        updates["other"] = amount
                updates["compliance_salary_allowances"] = lines

            # Iter 137 — keep the interlinked compliance structure + linked
            # Compliance Gross in sync whenever Basic / allowances change.
            if "compliance_basic" in updates or "compliance_salary_allowances" in updates:
                from server import build_compliance_structure, compliance_gross_total
                _basic = updates.get("compliance_basic",
                                     existing.get("compliance_basic")) or 0
                _allow = updates.get("compliance_salary_allowances",
                                     existing.get("compliance_salary_allowances") or [])
                updates["salary_structure_compliance"] = build_compliance_structure(
                    _basic, _allow, existing.get("compliance_salary_mode"))
                _total = compliance_gross_total(_basic, _allow)
                if _total > 0:
                    updates["compliance_gross"] = _total

            if not updates and group_change_to is None:
                skipped.append({"user_id": row.user_id, "reason": "no_changes"})
                continue

            if payload.dry_run:
                applied.append({
                    "user_id": row.user_id,
                    "would_update": updates,
                    "would_move_to_group": group_change_to,
                    "dry_run": True,
                })
                continue

            if updates:
                updates["last_corrected_at"] = now_iso_fn()
                updates["last_corrected_by"] = admin["user_id"]
                await db.users.update_one({"user_id": row.user_id}, {"$set": updates})

            # Group membership change
            if group_change_to is not None:
                # Remove from any other groups first (firm-scoped + global)
                await db.masters.update_many(
                    {"type": "group",
                     "company_id": {"$in": [row_company_id, "__global__", None]},
                     "member_user_ids": row.user_id},
                    {"$pull": {"member_user_ids": row.user_id}},
                )
                if group_change_to:
                    target = await db.masters.find_one(
                        {"master_id": group_change_to, "type": "group",
                         "company_id": {"$in": [row_company_id, "__global__", None]}},
                        {"_id": 0, "master_id": 1, "name": 1},
                    )
                    if target:
                        await db.masters.update_one(
                            {"master_id": group_change_to},
                            {"$addToSet": {"member_user_ids": row.user_id}},
                        )
                        # Keep the name-based mirrors on the user doc in
                        # sync (Employee Group == Employee Type).
                        await db.users.update_one(
                            {"user_id": row.user_id},
                            {"$set": {"employee_group": target.get("name"),
                                      "employee_type": target.get("name")}},
                        )
                    else:
                        skipped.append({"user_id": row.user_id, "reason": "group_not_found"})
                        continue
                else:
                    await db.users.update_one(
                        {"user_id": row.user_id},
                        {"$set": {"employee_group": None, "employee_type": None}},
                    )

            applied.append({
                "user_id": row.user_id,
                "updated": updates,
                "moved_to_group": group_change_to,
            })

        return {
            "ok": True,
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "applied": applied,
            "skipped": skipped,
            "dry_run": payload.dry_run,
        }

    # ---------------- Attendance email config + trigger ------------------
    @api.get("/admin/companies/{company_id}/attendance-email-config")
    async def get_attendance_email_config(
        company_id: str, authorization: Optional[str] = Header(None),
    ):
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin", "company_admin"])
        if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
            raise HTTPException(status_code=403, detail="Not authorised")
        c = await db.companies.find_one(
            {"company_id": company_id},
            {"_id": 0, "attendance_email_recipients": 1,
             "attendance_email_enabled": 1, "name": 1},
        )
        if not c:
            raise HTTPException(status_code=404, detail="Company not found")
        return {
            "company_id": company_id,
            "name": c.get("name"),
            "recipients": c.get("attendance_email_recipients") or [],
            "enabled": c.get("attendance_email_enabled") if c.get("attendance_email_enabled") is not None else True,
        }

    @api.put("/admin/companies/{company_id}/attendance-email-config")
    async def set_attendance_email_config(
        company_id: str,
        payload: AttendanceEmailConfigPayload,
        authorization: Optional[str] = Header(None),
    ):
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin"])
        c = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "company_id": 1})
        if not c:
            raise HTTPException(status_code=404, detail="Company not found")
        # Clean emails
        clean = [e.strip().lower() for e in (payload.recipients or []) if e and "@" in e]
        await db.companies.update_one(
            {"company_id": company_id},
            {"$set": {
                "attendance_email_recipients": clean,
                "attendance_email_enabled": bool(payload.enabled),
            }},
        )
        return {"ok": True, "recipients": clean, "enabled": bool(payload.enabled)}

    @api.post("/admin/attendance-email/trigger-now")
    async def trigger_attendance_email_now(
        month: Optional[str] = None,
        company_id: Optional[str] = None,
        dry_run: bool = False,
        authorization: Optional[str] = Header(None),
    ):
        """Manually trigger the attendance-sheet email batch. Super admin only."""
        admin = await get_user_from_token(authorization)
        require_super_admin_strict(admin)
        return await _run_attendance_email_batch(
            db, month=month, company_id_filter=company_id, dry_run=dry_run,
        )

    @api.get("/admin/attendance-email/log")
    async def list_attendance_email_log(
        company_id: Optional[str] = None,
        limit: int = 50,
        authorization: Optional[str] = Header(None),
    ):
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin", "company_admin"])
        q: Dict[str, Any] = {}
        if admin["role"] == "company_admin":
            q["company_id"] = admin.get("company_id")
        elif company_id:
            q["company_id"] = company_id
        items = await db.attendance_email_log.find(q, {"_id": 0}).sort("sent_at", -1).to_list(min(limit, 500))
        return {"items": items}

    # ---------------- Portal automation ---------------------------------
    @api.post("/admin/portal-automation/jobs")
    async def create_portal_automation_job(
        payload: PortalAutomationJobPayload,
        background_tasks: BackgroundTasks,
        authorization: Optional[str] = Header(None),
    ):
        """Create a new portal automation job (EPFO or ESIC) and run in
        background. The job screenshots each step; the super admin can
        review progress from the /portal-automation page."""
        admin = await get_user_from_token(authorization)
        require_super_admin_strict(admin)
        if payload.portal not in ("epfo", "esic"):
            raise HTTPException(status_code=400, detail="portal must be 'epfo' or 'esic'")

        # Sanity: run must exist
        run = await db.compliance_salary_runs.find_one(
            {"run_id": payload.compliance_salary_run_id}, {"_id": 0, "company_id": 1, "month": 1},
        )
        if not run:
            raise HTTPException(status_code=404, detail="Compliance salary run not found")
        if run.get("company_id") != payload.company_id:
            raise HTTPException(status_code=400, detail="Company mismatch on the compliance run")

        job_id = f"auto_{uuid.uuid4().hex[:12]}"
        job = {
            "job_id": job_id,
            "portal": payload.portal,
            "company_id": payload.company_id,
            "compliance_salary_run_id": payload.compliance_salary_run_id,
            "month": run.get("month"),
            "status": "queued",
            "steps": [],
            "created_at": now_iso_fn(),
            "created_by": admin["user_id"],
        }
        await db.automation_jobs.insert_one(job)

        async def _run():
            await _run_portal_automation(db, job_id=job_id)

        # Schedule the coroutine as a real background task
        background_tasks.add_task(_run)
        job.pop("_id", None)
        return job

    @api.get("/admin/portal-automation/jobs")
    async def list_portal_automation_jobs(
        company_id: Optional[str] = None,
        limit: int = 20,
        authorization: Optional[str] = Header(None),
    ):
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin"])
        q: Dict[str, Any] = {}
        if company_id:
            q["company_id"] = company_id
        items = await db.automation_jobs.find(
            q, {"_id": 0, "steps": {"$slice": -1}},  # only latest step for list view
        ).sort("created_at", -1).to_list(min(limit, 100))
        return {"items": items}

    @api.get("/admin/portal-automation/jobs/{job_id}")
    async def get_portal_automation_job(
        job_id: str, authorization: Optional[str] = Header(None),
    ):
        admin = await get_user_from_token(authorization)
        require_role(admin, ["super_admin", "sub_admin"])
        job = await db.automation_jobs.find_one({"job_id": job_id}, {"_id": 0})
        if not job:
            raise HTTPException(status_code=404, detail="Automation job not found")
        return job

    # ---------------- Startup: schedule the monthly cron ----------------
    @app.on_event("startup")
    async def _start_attendance_email_scheduler():  # noqa: D401
        # Import inside so tests without APScheduler still boot server.
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            log.warning("APScheduler not installed — auto-email cron disabled")
            return

        # Guard: don't double-schedule during hot reloads
        if getattr(app.state, "attendance_email_scheduler_started", False):
            return
        scheduler = AsyncIOScheduler(timezone=INDIA_TZ)

        async def _job():
            try:
                out = await _run_attendance_email_batch(db)
                log.info("[attendance-email cron] sent %d", len(out.get("results", [])))
            except Exception:  # noqa: BLE001
                log.exception("[attendance-email cron] failed")

        # 09:00 IST on the 1st of every month
        scheduler.add_job(
            _job,
            CronTrigger(day=1, hour=9, minute=0, timezone=INDIA_TZ),
            id="attendance_email_monthly",
            replace_existing=True,
        )
        scheduler.start()
        app.state.attendance_email_scheduler = scheduler
        app.state.attendance_email_scheduler_started = True
        log.info("[attendance-email cron] scheduled: monthly 1st @ 09:00 IST")
