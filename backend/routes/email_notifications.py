"""Iter 103 — SMTP Email Notifications (Gmail SMTP / any provider).

Runtime-configurable SMTP settings stored in Mongo (``smtp_settings``),
editable any time from the UI. Automated email triggers (``email_triggers``)
fire on app events (leave / punch / salary / joining / tickets) and every
send is logged to ``email_log``. Admins can also compose ad-hoc
notifications (email + in-app) from the UI.

Endpoints (super_admin + sub_admin):
  * GET/PUT  /admin/smtp-settings          (password masked on GET)
  * POST     /admin/smtp-settings/test     (send test mail)
  * GET/PUT  /admin/email-triggers
  * POST     /admin/notifications/compose  (ad-hoc email + in-app)
  * GET      /admin/email-log
"""
import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Optional

import aiosmtplib
from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
)

logger = logging.getLogger("email_notifications")
router = APIRouter(prefix="/api", tags=["email-notifications"])

PASSWORD_MASK = "********"

DEFAULT_SETTINGS = {
    "enabled": False,
    "host": "smtp.gmail.com",
    "port": 587,
    "username": "",
    "password": "",
    "use_tls": False,   # implicit TLS (port 465)
    "start_tls": True,  # STARTTLS (port 587 — Gmail recommended)
    "from_name": "S.K. Sharma & Co.",
    "from_email": "",
}

# Automated trigger catalogue. recipients:
#   employee → the employee involved in the event
#   admins   → company_admin users of the firm
#   custom   → only extra_emails
# extra_emails are ALWAYS appended.
DEFAULT_TRIGGERS = [
    {"event": "leave_applied",   "label": "Leave Applied",            "recipients": "admins",   "subject": "Leave request from {employee_name} — {firm_name}", "body": "{employee_name} has applied for {details}.\nPlease review it in the portal."},
    {"event": "leave_approved",  "label": "Leave Approved",           "recipients": "employee", "subject": "Your leave has been APPROVED — {firm_name}",       "body": "Dear {employee_name},\n\nYour leave request ({details}) has been approved.\n\n{firm_name}"},
    {"event": "leave_rejected",  "label": "Leave Rejected",           "recipients": "employee", "subject": "Your leave has been REJECTED — {firm_name}",       "body": "Dear {employee_name},\n\nYour leave request ({details}) has been rejected.\n\n{firm_name}"},
    {"event": "punch_in",        "label": "Punch In Confirmation",    "recipients": "employee", "subject": "Punch IN recorded — {firm_name}",                  "body": "Dear {employee_name},\n\nYour Punch IN was recorded on {date} at {time}.\n\n{firm_name}"},
    {"event": "punch_out",       "label": "Punch Out Confirmation",   "recipients": "employee", "subject": "Punch OUT recorded — {firm_name}",                 "body": "Dear {employee_name},\n\nYour Punch OUT was recorded on {date} at {time}.\n\n{firm_name}"},
    {"event": "salary_finalized", "label": "Salary Run Finalized",    "recipients": "admins",   "subject": "Salary run finalized — {firm_name} ({details})",   "body": "The salary run for {details} has been finalized for {firm_name}."},
    {"event": "employee_joined", "label": "New Employee Joined",      "recipients": "admins",   "subject": "New employee joined — {firm_name}",                "body": "{employee_name} has been added to {firm_name} on {date}."},
    {"event": "ticket_raised",   "label": "Service Ticket Raised",    "recipients": "admins",   "subject": "New ticket from {employee_name} — {firm_name}",    "body": "{employee_name} raised a ticket: {details}"},
    {"event": "ticket_resolved", "label": "Service Ticket Resolved",  "recipients": "employee", "subject": "Your ticket has been resolved — {firm_name}",      "body": "Dear {employee_name},\n\nYour ticket ({details}) has been resolved.\n\n{firm_name}"},
    {"event": "shift_allotted",  "label": "Shift Allotted / Changed", "recipients": "employee", "subject": "Your shift for today — {firm_name}",               "body": "Dear {employee_name},\n\nToday your shift is {details}. Please punch in timely.\n\n{firm_name}"},
    # Iter 112 — every-morning Daily Attendance Report (Excel + PDF attached).
    # ``send_time`` is IST HH:MM; the report covers YESTERDAY (complete day).
    {"event": "daily_attendance_report", "label": "Daily Attendance Report (Every Morning)", "recipients": "admins", "send_time": "08:00",
     "subject": "Daily Attendance Report — {firm_name} ({date})",
     "body": "Please find attached the Daily Attendance Report for {firm_name} — {date}.\n\nPresent: {present} · Absent: {absent} · Miss Punch: {miss_punch} (of {total} employees)\n\n{firm_name}"},
]


# ---------------------------------------------------------------------------
# Core send helpers
# ---------------------------------------------------------------------------
async def _get_settings() -> Optional[dict]:
    doc = await db.smtp_settings.find_one({"_singleton": True}, {"_id": 0})
    return doc


def _render(template: str, ctx: dict) -> str:
    out = template or ""
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", str(v if v is not None else ""))
    return out


async def _smtp_send(settings: dict, to_email: str, subject: str, body: str,
                     attachments: Optional[list] = None) -> None:
    msg = EmailMessage()
    from_email = settings.get("from_email") or settings.get("username")
    from_name = settings.get("from_name")
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    html = "<div style='font-family:Arial,sans-serif;font-size:14px;color:#1e293b'>" + \
        body.replace("\n", "<br/>") + \
        "<br/><br/><hr style='border:none;border-top:1px solid #e2e8f0'/>" + \
        "<span style='font-size:11px;color:#94a3b8'>Sent automatically by Smart Payroll Service — " + \
        (from_name or "") + "</span></div>"
    msg.add_alternative(html, subtype="html")
    # Iter 112 — optional binary attachments: [{filename, content(bytes), mime}]
    for att in attachments or []:
        mime = att.get("mime") or "application/octet-stream"
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(
            att["content"], maintype=maintype, subtype=subtype or "octet-stream",
            filename=att["filename"],
        )

    kwargs: dict = {
        "hostname": settings["host"],
        "port": int(settings["port"]),
        "username": settings["username"],
        "password": settings["password"],
        "timeout": 25,
    }
    if settings.get("use_tls"):
        kwargs["use_tls"] = True
    elif settings.get("start_tls"):
        kwargs["start_tls"] = True
    await aiosmtplib.send(msg, **kwargs)


async def _send_and_log(settings: dict, to_email: str, subject: str,
                        body: str, event: str,
                        attachments: Optional[list] = None) -> dict:
    entry = {
        "log_id": f"eml_{uuid.uuid4().hex[:10]}",
        "to": to_email,
        "subject": subject,
        "event": event,
        "status": "sent",
        "error": None,
        "sent_at": now_iso(),
    }
    try:
        await _smtp_send(settings, to_email, subject, body, attachments)
    except Exception as e:  # noqa: BLE001 — log every failure kind
        entry["status"] = "failed"
        entry["error"] = str(e)[:300]
        logger.warning("[email] send failed to %s (%s): %s", to_email, event, e)
    await db.email_log.insert_one(dict(entry))
    return entry


async def _resolve_recipients(trigger: dict, company_id: Optional[str],
                              employee: Optional[dict]) -> list:
    emails: list = []
    mode = trigger.get("recipients") or "employee"
    if mode == "employee" and employee and employee.get("email"):
        emails.append(employee["email"])
    elif mode == "admins" and company_id:
        async for a in db.users.find(
            {"role": "company_admin", "company_id": company_id, "email": {"$nin": [None, ""]}},
            {"_id": 0, "email": 1},
        ):
            emails.append(a["email"])
    for e in trigger.get("extra_emails") or []:
        if e and "@" in e:
            emails.append(e.strip())
    # de-dupe, keep order
    seen: set = set()
    return [e for e in emails if not (e.lower() in seen or seen.add(e.lower()))]


async def fire_email_event(event: str, company_id: Optional[str] = None,
                           employee_user_id: Optional[str] = None,
                           details: str = "") -> None:
    """Fire-and-forget automated email for an app event. NEVER raises."""
    try:
        settings = await _get_settings()
        if not settings or not settings.get("enabled") or not settings.get("username"):
            return
        trigger = await db.email_triggers.find_one({"event": event}, {"_id": 0})
        if not trigger or not trigger.get("enabled"):
            return
        employee = None
        if employee_user_id:
            employee = await db.users.find_one(
                {"user_id": employee_user_id},
                {"_id": 0, "name": 1, "email": 1, "employee_code": 1, "company_id": 1})
        cid = company_id or (employee or {}).get("company_id")
        company = await db.companies.find_one({"company_id": cid}, {"_id": 0, "name": 1}) if cid else None
        now = now_iso()
        ctx = {
            "employee_name": (employee or {}).get("name") or "",
            "employee_code": (employee or {}).get("employee_code") or "",
            "firm_name": (company or {}).get("name") or "S.K. Sharma & Co.",
            "date": now[:10],
            "time": now[11:16],
            "details": details,
        }
        recipients = await _resolve_recipients(trigger, cid, employee)
        if not recipients:
            return
        subject = _render(trigger.get("subject") or event, ctx)
        body = _render(trigger.get("body") or details, ctx)

        async def _bg():
            for to in recipients[:25]:
                await _send_and_log(settings, to, subject, body, event)
        asyncio.create_task(_bg())
    except Exception as e:  # noqa: BLE001 — event emails must never break the flow
        logger.warning("[email] fire_email_event(%s) error: %s", event, e)


# ---------------------------------------------------------------------------
# SMTP settings endpoints
# ---------------------------------------------------------------------------
async def _require_admin(authorization):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    return admin


@router.get("/admin/smtp-settings")
async def get_smtp_settings(authorization: Optional[str] = Header(None)):
    await _require_admin(authorization)
    doc = await _get_settings() or dict(DEFAULT_SETTINGS)
    doc.pop("_singleton", None)
    if doc.get("password"):
        doc["password"] = PASSWORD_MASK
        doc["password_set"] = True
    else:
        doc["password_set"] = False
    return {"settings": doc}


@router.put("/admin/smtp-settings")
async def update_smtp_settings(payload: dict = Body(...),
                               authorization: Optional[str] = Header(None)):
    admin = await _require_admin(authorization)
    existing = await _get_settings() or {}
    doc = {**DEFAULT_SETTINGS, **existing}
    for k in ("enabled", "host", "port", "username", "from_name", "from_email",
              "use_tls", "start_tls"):
        if k in payload and payload[k] is not None:
            doc[k] = payload[k]
    # keep the stored password when the UI sends back the mask / empty
    pwd = payload.get("password")
    if pwd and pwd != PASSWORD_MASK:
        doc["password"] = pwd
    try:
        doc["port"] = int(doc["port"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Port must be a number")
    # sane TLS combo: exactly one of use_tls / start_tls
    if doc.get("use_tls"):
        doc["start_tls"] = False
    elif not doc.get("start_tls"):
        doc["start_tls"] = True
    doc["_singleton"] = True
    doc["updated_at"] = now_iso()
    doc["updated_by"] = admin["user_id"]
    await db.smtp_settings.update_one({"_singleton": True}, {"$set": doc}, upsert=True)
    out = {k: v for k, v in doc.items() if k not in ("_singleton",)}
    out["password"] = PASSWORD_MASK if doc.get("password") else ""
    out["password_set"] = bool(doc.get("password"))
    return {"ok": True, "settings": out}


@router.post("/admin/smtp-settings/test")
async def test_smtp_settings(payload: dict = Body(default={}),
                             authorization: Optional[str] = Header(None)):
    admin = await _require_admin(authorization)
    settings = await _get_settings()
    if not settings or not settings.get("username") or not settings.get("password"):
        raise HTTPException(status_code=400, detail="Save the SMTP username and password first")
    to = payload.get("to_email") or admin.get("email") or settings["username"]
    entry = await _send_and_log(
        settings, to,
        "SMTP test — Smart Payroll Service",
        "This is a test email confirming your SMTP settings are working.\n\n"
        f"Host: {settings['host']}:{settings['port']}\nSent: {now_iso()}",
        "smtp_test",
    )
    if entry["status"] == "failed":
        raise HTTPException(status_code=400, detail=f"SMTP test failed: {entry['error']}")
    return {"ok": True, "detail": f"Test email sent to {to}"}


# ---------------------------------------------------------------------------
# Trigger endpoints
# ---------------------------------------------------------------------------
@router.get("/admin/email-triggers")
async def list_email_triggers(authorization: Optional[str] = Header(None)):
    await _require_admin(authorization)
    stored = {t["event"]: t async for t in db.email_triggers.find({}, {"_id": 0})}
    out = []
    for d in DEFAULT_TRIGGERS:
        t = {**d, "enabled": False, "extra_emails": []}
        t.update(stored.get(d["event"]) or {})
        t["label"] = d["label"]  # labels are not editable
        out.append(t)
    return {"triggers": out}


@router.put("/admin/email-triggers")
async def update_email_triggers(payload: dict = Body(...),
                                authorization: Optional[str] = Header(None)):
    admin = await _require_admin(authorization)
    triggers = payload.get("triggers") or []
    valid_events = {d["event"] for d in DEFAULT_TRIGGERS}
    saved = 0
    for t in triggers:
        ev = t.get("event")
        if ev not in valid_events:
            continue
        doc = {
            "event": ev,
            "enabled": bool(t.get("enabled")),
            "recipients": t.get("recipients") or next(d["recipients"] for d in DEFAULT_TRIGGERS if d["event"] == ev),
            "extra_emails": [e.strip() for e in (t.get("extra_emails") or []) if e and "@" in e],
            "subject": t.get("subject") or "",
            "body": t.get("body") or "",
            "updated_at": now_iso(),
            "updated_by": admin["user_id"],
        }
        # Iter 112 — daily report send time (IST HH:MM), validated.
        st = str(t.get("send_time") or "").strip()
        if re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", st):
            doc["send_time"] = f"{int(st.split(':')[0]):02d}:{st.split(':')[1]}"
        await db.email_triggers.update_one({"event": ev}, {"$set": doc}, upsert=True)
        saved += 1
    return {"ok": True, "saved": saved}


# ---------------------------------------------------------------------------
# Compose (ad-hoc) notification
# ---------------------------------------------------------------------------
@router.post("/admin/notifications/compose")
async def compose_notification(payload: dict = Body(...),
                               authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    company_id = payload.get("company_id")
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    # User directive — two audience modes:
    #   * "employers"  → every company admin (all firms), no firm needed
    #   * "employees"  → firm selection is MANDATORY
    audience = (payload.get("audience") or "employees").strip().lower()
    all_companies = bool(payload.get("all_companies")) and admin["role"] in ("super_admin", "sub_admin")
    subject = (payload.get("subject") or "").strip()
    message = (payload.get("message") or "").strip()
    if not subject or not message:
        raise HTTPException(status_code=400, detail="Subject and message are required")
    send_email = bool(payload.get("send_email", True))
    send_inapp = bool(payload.get("send_inapp", True))
    user_ids = payload.get("user_ids") or []          # explicit selection
    to_all = bool(payload.get("all_employees")) or all_companies or audience == "employers"

    # User directive — optional file attachments shared with the mail.
    import base64 as _b64
    attachments: list = []
    for a in (payload.get("attachments") or [])[:5]:
        if not isinstance(a, dict):
            continue
        try:
            content = _b64.b64decode(a.get("content_base64") or "")
        except Exception:
            continue
        if not content or len(content) > 10_000_000:  # 10 MB per file cap
            continue
        attachments.append({
            "filename": str(a.get("filename") or "attachment"),
            "content": content,
            "mime": a.get("mime") or "application/octet-stream",
        })

    if audience == "employers":
        # All Employers = every firm's company admin.
        if admin["role"] not in ("super_admin", "sub_admin"):
            raise HTTPException(status_code=403, detail="Only the super admin can mail all employers")
        q: dict = {"role": "company_admin"}
    else:
        q = {"role": "employee"}
        if not all_companies:
            if not company_id:
                raise HTTPException(
                    status_code=400,
                    detail="Select a firm first — company selection is mandatory when mailing employees")
            q["company_id"] = company_id
    if not to_all:
        if not user_ids:
            raise HTTPException(status_code=400, detail="Select employees or choose All employees")
        q["user_id"] = {"$in": user_ids}
    targets = await db.users.find(
        q, {"_id": 0, "user_id": 1, "name": 1, "email": 1, "company_id": 1}).to_list(5000)
    if not targets:
        raise HTTPException(status_code=404, detail="No matching employees found")

    inapp_count = 0
    if send_inapp:
        docs = [{
            "notification_id": f"ntf_{uuid.uuid4().hex[:12]}",
            "audience": "user",
            "target_user_id": t["user_id"],
            "company_id": t.get("company_id") if (all_companies or audience == "employers") else company_id,
            "title": subject,
            "body": message,
            "created_by": admin["user_id"],
            "created_at": now_iso(),
            "read_by": [],
        } for t in targets]
        if docs:
            await db.notifications.insert_many(docs)
            inapp_count = len(docs)

    email_queued = 0
    skipped_no_email = 0
    if send_email:
        settings = await _get_settings()
        if not settings or not settings.get("enabled") or not settings.get("username"):
            raise HTTPException(
                status_code=400,
                detail="SMTP is not configured/enabled. Configure it in Email Settings first (in-app part was "
                       + ("sent)." if inapp_count else "not sent)."))
        emails = [t["email"] for t in targets if t.get("email")]
        skipped_no_email = len(targets) - len(emails)

        async def _bg():
            for to in emails:
                await _send_and_log(settings, to, subject, message,
                                    "manual_compose", attachments or None)
        if emails:
            asyncio.create_task(_bg())
        email_queued = len(emails)

    return {
        "ok": True,
        "targets": len(targets),
        "audience": audience,
        "all_companies": all_companies,
        "attachments": len(attachments),
        "inapp_sent": inapp_count,
        "emails_queued": email_queued,
        "skipped_no_email": skipped_no_email,
    }


@router.get("/admin/email-log")
async def email_log(limit: int = Query(30, le=200),
                    authorization: Optional[str] = Header(None)):
    await _require_admin(authorization)
    logs = await db.email_log.find({}, {"_id": 0}).sort("sent_at", -1).to_list(limit)
    return {"logs": logs}


# ---------------------------------------------------------------------------
# Iter 112 — Daily Attendance Report auto-email (every morning, IST)
# ---------------------------------------------------------------------------
_IST = timezone(timedelta(hours=5, minutes=30))


async def run_daily_attendance_batch(report_date: Optional[str] = None,
                                     company_id_filter: Optional[str] = None,
                                     include_weekly: bool = False) -> dict:
    """Email the Daily Attendance Report (XLSX + PDF attached) to each
    firm's admins + extra_emails. ``report_date`` defaults to YESTERDAY
    (IST) — the last complete day. Requires SMTP configured & enabled.
    ``include_weekly`` additionally attaches the previous complete Mon–Sun
    Weekly Summary (auto-enabled by the scheduler on Monday mornings)."""
    from server import _compute_monthly_grid_data  # lazy — avoid import cycle
    from utils.daily_attendance import build_daily_xlsx, build_daily_pdf, _daily_rows

    settings = await _get_settings()
    if not settings or not settings.get("enabled") or not settings.get("username"):
        return {"ok": False, "error": "SMTP not configured/enabled"}
    trigger = await db.email_triggers.find_one(
        {"event": "daily_attendance_report"}, {"_id": 0},
    ) or next(d for d in DEFAULT_TRIGGERS if d["event"] == "daily_attendance_report")

    date_s = (report_date or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_s):
        date_s = (datetime.now(_IST) - timedelta(days=1)).strftime("%Y-%m-%d")

    # Iter 113 — previous complete Mon–Sun window ending on/before date_s.
    wk_from = wk_to = None
    if include_weekly:
        d = datetime.strptime(date_s, "%Y-%m-%d")
        wk_to_dt = d - timedelta(days=(d.weekday() + 1) % 7)  # last Sunday <= date_s
        wk_from_dt = wk_to_dt - timedelta(days=6)             # its Monday
        wk_from, wk_to = wk_from_dt.strftime("%Y-%m-%d"), wk_to_dt.strftime("%Y-%m-%d")

    q: dict = {}
    if company_id_filter:
        q["company_id"] = company_id_filter
    companies = await db.companies.find(q, {"_id": 0, "company_id": 1, "name": 1}).to_list(500)
    results = []
    for c in companies:
        cid = c["company_id"]
        try:
            recipients = await _resolve_recipients(trigger, cid, None)
            if not recipients:
                results.append({"company_id": cid, "skipped": "no_recipients"})
                continue
            grid = await _compute_monthly_grid_data(
                company_id=cid, month=date_s[:7],
                group_id=None, from_date=date_s, to_date=date_s,
            )
            if not (grid.get("employees") or []):
                results.append({"company_id": cid, "skipped": "no_employees"})
                continue
            _, summary = _daily_rows(grid)
            xlsx = build_daily_xlsx(grid, date_s)
            pdf = build_daily_pdf(grid, date_s)
            ctx = {
                "firm_name": c.get("name") or "S.K. Sharma & Co.",
                "date": date_s,
                "present": summary["present"],
                "absent": summary["absent"],
                "miss_punch": summary["anomalies"],
                "total": summary["present"] + summary["absent"] + summary["anomalies"],
            }
            subject = _render(trigger.get("subject") or "Daily Attendance Report — {firm_name} ({date})", ctx)
            body = _render(trigger.get("body") or "", ctx)
            slug = (c.get("name") or "company").replace(" ", "_")
            attachments = [
                {"filename": f"DailyAttendance_{slug}_{date_s}.xlsx", "content": xlsx,
                 "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                {"filename": f"DailyAttendance_{slug}_{date_s}.pdf", "content": pdf,
                 "mime": "application/pdf"},
            ]
            # Iter 113 — Monday mornings: attach previous Mon–Sun summary.
            if include_weekly and wk_from and wk_to:
                try:
                    from utils.monthly_attendance import build_hours_only_grid_xlsx
                    from utils.weekly_attendance import build_weekly_pdf
                    wgrid = await _compute_monthly_grid_data(
                        company_id=cid, month=wk_from[:7],
                        group_id=None, from_date=wk_from, to_date=wk_to,
                    )
                    attachments += [
                        {"filename": f"WeeklySummary_{slug}_{wk_from}_to_{wk_to}.xlsx",
                         "content": build_hours_only_grid_xlsx(wgrid),
                         "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                        {"filename": f"WeeklySummary_{slug}_{wk_from}_to_{wk_to}.pdf",
                         "content": build_weekly_pdf(wgrid, wk_from, wk_to),
                         "mime": "application/pdf"},
                    ]
                    body += f"\n\nWeekly Summary attached (Mon {wk_from} → Sun {wk_to})."
                except Exception as we:  # weekly must not block the daily send
                    logger.warning("[daily-report] weekly summary for %s failed: %s", cid, we)
            sent = 0
            for to in recipients[:10]:
                r = await _send_and_log(settings, to, subject, body,
                                        "daily_attendance_report", attachments)
                if r.get("status") == "sent":
                    sent += 1
            results.append({
                "company_id": cid, "recipients": recipients, "sent": sent,
                "present": ctx["present"], "absent": ctx["absent"],
            })
        except Exception as e:  # noqa: BLE001 — one firm must not break the batch
            logger.warning("[daily-report] %s failed: %s", cid, e)
            results.append({"company_id": cid, "error": str(e)[:200]})
    return {"ok": True, "date": date_s, "weekly": {"from": wk_from, "to": wk_to} if include_weekly else None, "results": results}


@router.post("/admin/email-triggers/daily-attendance/send-now")
async def daily_attendance_send_now(payload: dict = Body(default={}),
                                    authorization: Optional[str] = Header(None)):
    """Manually fire the Daily Attendance Report email (test / re-send).
    Optional body: {date: YYYY-MM-DD, company_id, include_weekly: bool}."""
    await _require_admin(authorization)
    out = await run_daily_attendance_batch(
        report_date=payload.get("date"),
        company_id_filter=payload.get("company_id"),
        include_weekly=bool(payload.get("include_weekly")),
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error") or "Send failed")
    return out


async def daily_attendance_report_loop():
    """Started at server startup. Every 60s checks whether the trigger is
    enabled and the IST clock has reached ``send_time``; sends at most once
    per day (``last_sent_date`` guard persisted on the trigger doc)."""
    logger.info("[daily-report] scheduler loop started")
    while True:
        try:
            trigger = await db.email_triggers.find_one(
                {"event": "daily_attendance_report"}, {"_id": 0},
            )
            if trigger and trigger.get("enabled"):
                now = datetime.now(_IST)
                today = now.strftime("%Y-%m-%d")
                send_time = trigger.get("send_time") or "08:00"
                if now.strftime("%H:%M") >= send_time and trigger.get("last_sent_date") != today:
                    # optimistic guard first so a slow batch can't double-send
                    await db.email_triggers.update_one(
                        {"event": "daily_attendance_report"},
                        {"$set": {"last_sent_date": today}},
                    )
                    # Iter 113 — Monday: attach previous Mon–Sun weekly summary
                    out = await run_daily_attendance_batch(include_weekly=(now.weekday() == 0))
                    logger.info("[daily-report] auto-send done: %s", str(out)[:300])
        except Exception:
            logger.exception("[daily-report] loop iteration failed")
        await asyncio.sleep(60)
