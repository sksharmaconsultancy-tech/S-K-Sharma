"""Iter 395 — WhatsApp Business Cloud API Notification Engine.

Centralized, multi-tenant (per-company) WhatsApp messaging:
  * per-company encrypted credentials (Fernet via utils.secrets_vault)
  * message queue in ``wa_messages`` drained by a 20-s background worker
  * automatic event notifications (payroll / attendance / leave / HR)
  * daily scans (birthday, anniversary, absent today, continuous absence,
    document reminders, holiday reminder)
  * schedules (once / daily / weekly / monthly)
  * chatbot keyword auto-replies via the inbound webhook
  * delivery-status tracking (sent → delivered → read / failed)

Credentials are entered by the user in the WhatsApp Configuration page.
Until then the engine runs in "pending config" mode: messages queue up and
fail gracefully with error="not_configured" (retryable after setup).
"""
import asyncio
import hashlib
import re
import uuid
import base64 as _b64
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from utils.secrets_vault import encrypt_secret, decrypt_secret, MASK

IST = timezone(timedelta(hours=5, minutes=30))

# populated by maybe_start(); avoids circular import with server.py
db = None
logger = None

GRAPH_BASE = "https://graph.facebook.com"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": False,
    "business_number": "",
    "display_name": "",
    "phone_number_id": "",
    "waba_id": "",
    "access_token": "",          # stored encrypted (enc::)
    "webhook_verify_token": "",
    "webhook_secret": "",        # app secret, stored encrypted
    "api_version": "v22.0",
    "default_country_code": "91",
    "queue_enabled": True,
    "retry_failed": True,
    "max_retries": 3,
    "auto_delete_days": 90,
    "daily_limit": 1000,
    "attachment_limit_mb": 16,
    "automation": {},            # {event_key: bool}
}

# every automatic event the engine understands ------------------------------
AUTOMATION_EVENTS: List[Dict[str, str]] = [
    # payroll
    {"key": "salary_processed", "label": "Salary Processed", "group": "Payroll"},
    {"key": "salary_slip", "label": "Salary Slip PDF", "group": "Payroll"},
    {"key": "salary_hold", "label": "Salary Hold", "group": "Payroll"},
    {"key": "salary_released", "label": "Salary Released", "group": "Payroll"},
    {"key": "bonus", "label": "Bonus Payment", "group": "Payroll"},
    {"key": "overtime", "label": "Overtime Payment", "group": "Payroll"},
    {"key": "arrear", "label": "Arrear Payment", "group": "Payroll"},
    {"key": "increment", "label": "Salary Revision / Increment", "group": "Payroll"},
    # attendance
    {"key": "absent_today", "label": "Absent Today", "group": "Attendance"},
    {"key": "late_coming", "label": "Late Coming", "group": "Attendance"},
    {"key": "missing_punch", "label": "Missing Punch", "group": "Attendance"},
    {"key": "continuous_absence", "label": "Continuous Absence (3+ days)", "group": "Attendance"},
    {"key": "shift_change", "label": "Shift Change", "group": "Attendance"},
    {"key": "holiday_reminder", "label": "Holiday Reminder (1 day before)", "group": "Attendance"},
    {"key": "monthly_attendance", "label": "Monthly Attendance Summary", "group": "Attendance"},
    # leave
    {"key": "leave_applied", "label": "Leave Applied", "group": "Leave"},
    {"key": "leave_approved", "label": "Leave Approved", "group": "Leave"},
    {"key": "leave_rejected", "label": "Leave Rejected", "group": "Leave"},
    {"key": "esic_leave", "label": "ESIC Leave", "group": "Leave"},
    # HR / onboarding
    {"key": "welcome", "label": "Welcome Message (New Joining)", "group": "HR"},
    {"key": "birthday", "label": "Birthday Wishes", "group": "HR"},
    {"key": "anniversary", "label": "Work Anniversary Wishes", "group": "HR"},
    {"key": "document_reminder", "label": "Document / KYC Reminder", "group": "HR"},
    {"key": "exit", "label": "Exit / Relieving", "group": "HR"},
    # PF & ESIC
    {"key": "pf_registration", "label": "PF Registration / UAN Generated", "group": "PF & ESIC"},
    {"key": "esic_registration", "label": "ESIC Number Generated", "group": "PF & ESIC"},
    {"key": "kyc_pending", "label": "KYC Pending", "group": "PF & ESIC"},
]

TEMPLATE_VARIABLES = [
    "EmployeeName", "EmployeeCode", "Company", "Month", "Salary",
    "Department", "DOJ", "Designation", "Attendance", "LeaveBalance",
    "PFNumber", "UAN", "ESIC", "Holiday", "Date", "Amount", "Status",
    "LeaveType", "FromDate", "ToDate", "Shift",
]

DEFAULT_TEMPLATES: List[Dict[str, str]] = [
    {"category": "salary_slip", "name": "Salary Slip",
     "body": "Dear {{EmployeeName}} ({{EmployeeCode}}),\nYour salary slip for {{Month}} from {{Company}} is attached.\nNet Pay: ₹{{Salary}}\n— This is an automated message."},
    {"category": "salary_processed", "name": "Salary Processed",
     "body": "Dear {{EmployeeName}},\nYour salary for {{Month}} has been processed by {{Company}}. Net Pay: ₹{{Salary}}.\nIt will be credited to your registered bank account shortly."},
    {"category": "salary_hold", "name": "Salary Hold",
     "body": "Dear {{EmployeeName}},\nYour salary for {{Month}} is currently ON HOLD. Please contact HR at {{Company}} for details."},
    {"category": "salary_released", "name": "Salary Released",
     "body": "Dear {{EmployeeName}},\nGood news! Your held salary for {{Month}} has been RELEASED by {{Company}}."},
    {"category": "bonus", "name": "Bonus Payment",
     "body": "Dear {{EmployeeName}},\nA bonus of ₹{{Amount}} has been credited for you by {{Company}}. Congratulations!"},
    {"category": "overtime", "name": "Overtime Payment",
     "body": "Dear {{EmployeeName}},\nYour overtime payment of ₹{{Amount}} for {{Month}} has been processed by {{Company}}."},
    {"category": "arrear", "name": "Arrear Payment",
     "body": "Dear {{EmployeeName}},\nAn arrear payment of ₹{{Amount}} for {{Month}} has been processed by {{Company}}."},
    {"category": "increment", "name": "Salary Revision",
     "body": "Dear {{EmployeeName}},\nCongratulations! Your salary has been revised effective {{Date}}. New details are available with HR at {{Company}}."},
    {"category": "absent_today", "name": "Absent Today",
     "body": "Dear {{EmployeeName}},\nYou are marked ABSENT today ({{Date}}) at {{Company}}. If this is incorrect, please contact HR or apply for leave."},
    {"category": "late_coming", "name": "Late Coming",
     "body": "Dear {{EmployeeName}},\nYou punched in LATE today ({{Date}}). Please ensure timely attendance. — {{Company}}"},
    {"category": "missing_punch", "name": "Missing Punch",
     "body": "Dear {{EmployeeName}},\nYour OUT punch is missing for {{Date}}. Please regularise it with HR. — {{Company}}"},
    {"category": "continuous_absence", "name": "Continuous Absence",
     "body": "Dear {{EmployeeName}},\nYou have been absent for {{Attendance}} consecutive days. Please contact HR at {{Company}} immediately."},
    {"category": "shift_change", "name": "Shift Change",
     "body": "Dear {{EmployeeName}},\nYour shift has been changed to {{Shift}} effective {{Date}}. — {{Company}}"},
    {"category": "holiday_reminder", "name": "Holiday Reminder",
     "body": "Dear {{EmployeeName}},\nReminder: {{Holiday}} is a holiday on {{Date}}. Enjoy! — {{Company}}"},
    {"category": "monthly_attendance", "name": "Monthly Attendance",
     "body": "Dear {{EmployeeName}},\nYour attendance for {{Month}}: {{Attendance}}. — {{Company}}"},
    {"category": "leave_applied", "name": "Leave Applied",
     "body": "Dear {{EmployeeName}},\nYour {{LeaveType}} leave request from {{FromDate}} to {{ToDate}} has been submitted and is pending approval. — {{Company}}"},
    {"category": "leave_approved", "name": "Leave Approved",
     "body": "Dear {{EmployeeName}},\nYour {{LeaveType}} leave from {{FromDate}} to {{ToDate}} has been APPROVED. — {{Company}}"},
    {"category": "leave_rejected", "name": "Leave Rejected",
     "body": "Dear {{EmployeeName}},\nYour {{LeaveType}} leave from {{FromDate}} to {{ToDate}} has been REJECTED. Please contact HR. — {{Company}}"},
    {"category": "esic_leave", "name": "ESIC Leave",
     "body": "Dear {{EmployeeName}},\nYour ESIC leave from {{FromDate}} to {{ToDate}} has been recorded ({{Status}}). — {{Company}}"},
    {"category": "welcome", "name": "Welcome / Joining",
     "body": "Welcome to {{Company}}, {{EmployeeName}}! 🎉\nYour Employee Code is {{EmployeeCode}}, Department: {{Department}}, Designation: {{Designation}}, DOJ: {{DOJ}}.\nWe are delighted to have you on board!"},
    {"category": "birthday", "name": "Birthday Wishes",
     "body": "Happy Birthday, {{EmployeeName}}! 🎂\nWishing you a wonderful year ahead. — Team {{Company}}"},
    {"category": "anniversary", "name": "Work Anniversary",
     "body": "Congratulations {{EmployeeName}} on completing another year at {{Company}}! 🎉 Thank you for your dedication."},
    {"category": "document_reminder", "name": "Document Reminder",
     "body": "Dear {{EmployeeName}},\nThe following documents are pending in your records: {{Status}}. Please submit them to HR at {{Company}} at the earliest."},
    {"category": "exit", "name": "Exit / Relieving",
     "body": "Dear {{EmployeeName}},\nYour exit formalities with {{Company}} are in process. Please complete pending clearances with HR."},
    {"category": "pf_registration", "name": "PF Registration / UAN",
     "body": "Dear {{EmployeeName}},\nYour PF registration is complete. UAN: {{UAN}}, PF No: {{PFNumber}}. — {{Company}}"},
    {"category": "esic_registration", "name": "ESIC Registration",
     "body": "Dear {{EmployeeName}},\nYour ESIC number has been generated: {{ESIC}}. — {{Company}}"},
    {"category": "kyc_pending", "name": "KYC Pending",
     "body": "Dear {{EmployeeName}},\nYour KYC is incomplete ({{Status}}). Please submit the pending items to HR at {{Company}}."},
    {"category": "festival", "name": "Festival Greetings",
     "body": "Dear {{EmployeeName}},\nWarm wishes on {{Holiday}} from all of us at {{Company}}! 🎊"},
    {"category": "compliance_reminder", "name": "Compliance Reminder",
     "body": "Dear {{EmployeeName}},\nReminder from {{Company}}: {{Status}}. Please take action before the due date {{Date}}."},
    {"category": "custom", "name": "Custom Message",
     "body": "Dear {{EmployeeName}},\n{{Status}}\n— {{Company}}"},
]

CHATBOT_KEYWORDS = ["SALARY", "ATTENDANCE", "LEAVE", "PF", "ESIC",
                    "HOLIDAY", "PROFILE", "BANK", "HELP"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ist_today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- settings
async def get_settings(company_id: str) -> Dict[str, Any]:
    doc = await db.wa_settings.find_one({"company_id": company_id}, {"_id": 0})
    out = {**DEFAULT_SETTINGS, **(doc or {}), "company_id": company_id}
    return out


async def save_settings(company_id: str, patch: Dict[str, Any], by: str) -> Dict[str, Any]:
    cur = await get_settings(company_id)
    allowed = set(DEFAULT_SETTINGS.keys())
    upd: Dict[str, Any] = {}
    for k, v in (patch or {}).items():
        if k not in allowed:
            continue
        if k in ("access_token", "webhook_secret"):
            if v == MASK or v is None:      # untouched in UI
                continue
            upd[k] = encrypt_secret(str(v)) if v else ""
        elif k == "automation" and isinstance(v, dict):
            upd[k] = {**(cur.get("automation") or {}), **v}
        else:
            upd[k] = v
    upd["updated_at"] = now_iso()
    upd["updated_by"] = by
    await db.wa_settings.update_one(
        {"company_id": company_id}, {"$set": upd}, upsert=True)
    return await get_settings(company_id)


def mask_settings(s: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(s)
    for k in ("access_token", "webhook_secret"):
        out[k] = MASK if out.get(k) else ""
    return out


def _configured(s: Dict[str, Any]) -> bool:
    return bool(s.get("enabled") and s.get("phone_number_id") and s.get("access_token"))


# ------------------------------------------------------------- number utils
def normalize_number(raw: Optional[str], country_code: str = "91") -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    if len(digits) == 10:
        return f"{country_code}{digits}"
    if digits.startswith("0") and len(digits) == 11:
        return f"{country_code}{digits[1:]}"
    return digits  # already has country code


def wa_number_for(user: dict, country_code: str = "91") -> Optional[str]:
    return normalize_number(
        user.get("whatsapp_number") or user.get("phone"), country_code)


# ------------------------------------------------------------ template render
_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def build_context(user: dict, company: dict, extra: Optional[dict] = None) -> Dict[str, str]:
    ctx = {
        "EmployeeName": user.get("name") or "",
        "EmployeeCode": user.get("employee_code") or "",
        "Company": (company or {}).get("name") or "",
        "Department": user.get("department") or "",
        "Designation": user.get("position") or "",
        "DOJ": user.get("doj") or "",
        "PFNumber": user.get("pf_number") or user.get("pf_no") or "",
        "UAN": user.get("uan") or user.get("uan_number") or "",
        "ESIC": user.get("esic_number") or user.get("esic_no") or "",
        "Month": "", "Salary": "", "Attendance": "", "LeaveBalance": "",
        "Holiday": "", "Date": ist_today(), "Amount": "", "Status": "",
        "LeaveType": "", "FromDate": "", "ToDate": "", "Shift": "",
    }
    for k, v in (extra or {}).items():
        ctx[k] = "" if v is None else str(v)
    return ctx


def render_template(body: str, ctx: Dict[str, str]) -> str:
    def _sub(m):
        return ctx.get(m.group(1), "")
    return _VAR_RE.sub(_sub, body or "")


async def template_for(company_id: str, category: str) -> Optional[dict]:
    t = await db.wa_templates.find_one(
        {"category": category, "active": {"$ne": False},
         "company_id": {"$in": [company_id, "__global__"]}},
        {"_id": 0}, sort=[("company_id", -1)])  # company-specific wins
    return t


async def seed_default_templates(company_id: str = "__global__") -> int:
    created = 0
    for t in DEFAULT_TEMPLATES:
        exists = await db.wa_templates.find_one(
            {"company_id": company_id, "category": t["category"]}, {"_id": 1})
        if exists:
            continue
        await db.wa_templates.insert_one({
            "template_id": f"wat_{uuid.uuid4().hex[:10]}",
            "company_id": company_id,
            "category": t["category"],
            "name": t["name"],
            "body": t["body"],
            "language": "en",
            "meta_template_name": "",
            "active": True,
            "is_default": True,
            "created_at": now_iso(),
        })
        created += 1
    return created


# ---------------------------------------------------------------- enqueue
async def enqueue_message(
    *, company_id: str, user: Optional[dict], to: Optional[str] = None,
    category: str = "custom", body: Optional[str] = None,
    extra: Optional[dict] = None, source: str = "manual",
    attachment: Optional[dict] = None,  # {filename, mime, b64} OR {payslip:{company_id,user_id,month}}
    created_by: str = "system", scheduled_at: Optional[str] = None,
    dedupe: bool = True,
) -> Optional[dict]:
    """Queue one message. Renders the template NOW (auditable body)."""
    s = await get_settings(company_id)
    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "name": 1}) or {}
    user = user or {}
    to_num = to or wa_number_for(user, s.get("default_country_code") or "91")
    tpl = None
    if body is None:
        tpl = await template_for(company_id, category)
        raw = (tpl or {}).get("body") or ""
    else:
        raw = body
    ctx = build_context(user, company, extra)
    rendered = render_template(raw, ctx)
    if not rendered.strip() and not attachment:
        return None

    doc = {
        "msg_id": f"wam_{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "user_id": user.get("user_id"),
        "employee_code": user.get("employee_code"),
        "employee_name": user.get("name"),
        "to": to_num,
        "category": category,
        "template_id": (tpl or {}).get("template_id"),
        "body": rendered,
        "attachment": attachment,
        "status": "queued" if to_num else "failed",
        "error": None if to_num else "no_whatsapp_number",
        "source": source,             # manual | auto | bulk | scheduled | chatbot
        "retry_count": 0,
        "wa_message_id": None,
        "scheduled_at": scheduled_at or now_iso(),
        "created_at": now_iso(),
        "created_by": created_by,
        "sent_at": None, "delivered_at": None, "read_at": None,
        "response_code": None,
    }
    if dedupe and to_num and source == "auto":
        key = hashlib.sha256(
            f"{company_id}|{user.get('user_id')}|{category}|{rendered}|{ist_today()}"
            .encode()).hexdigest()
        doc["dedupe_key"] = key
        if await db.wa_messages.find_one({"dedupe_key": key}, {"_id": 1}):
            return None  # duplicate suppressed
    await db.wa_messages.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def notify_event(event_type: str, company_id: Optional[str],
                       user_id: Optional[str] = None,
                       extra: Optional[dict] = None,
                       attachment: Optional[dict] = None) -> None:
    """Fire-and-forget hook used by existing modules. NEVER raises."""
    try:
        if not company_id:
            return
        s = await get_settings(company_id)
        if not s.get("enabled") or not (s.get("automation") or {}).get(event_type):
            return
        user = None
        if user_id:
            user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
            if not user:
                return
        await enqueue_message(
            company_id=company_id, user=user, category=event_type,
            extra=extra, source="auto", attachment=attachment,
            created_by="auto-event")
    except Exception:
        if logger:
            logger.warning("[wa] notify_event failed", exc_info=True)


# --------------------------------------------------------------- Graph API
class WhatsAppClient:
    def __init__(self, settings: Dict[str, Any]):
        self.phone_number_id = settings["phone_number_id"]
        self.token = decrypt_secret(settings.get("access_token") or "") or ""
        self.version = settings.get("api_version") or "v22.0"

    def _url(self, path: str) -> str:
        return f"{GRAPH_BASE}/{self.version}/{path}"

    async def _post(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                self._url(f"{self.phone_number_id}/messages"),
                json=payload,
                headers={"Authorization": f"Bearer {self.token}"})
            data = {}
            try:
                data = r.json()
            except Exception:
                pass
            if r.status_code >= 400:
                err = (data.get("error") or {})
                raise WAError(r.status_code, err.get("code"),
                              err.get("message") or r.text[:200])
            return data

    async def send_text(self, to: str, body: str) -> dict:
        return await self._post({
            "messaging_product": "whatsapp", "recipient_type": "individual",
            "to": to, "type": "text",
            "text": {"body": body[:4096], "preview_url": False}})

    async def send_meta_template(self, to: str, name: str, lang: str,
                                 params: List[str]) -> dict:
        comps = []
        if params:
            comps = [{"type": "body",
                      "parameters": [{"type": "text", "text": p} for p in params]}]
        return await self._post({
            "messaging_product": "whatsapp", "recipient_type": "individual",
            "to": to, "type": "template",
            "template": {"name": name, "language": {"code": lang or "en"},
                         "components": comps}})

    async def upload_media(self, filename: str, mime: str, data: bytes) -> str:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(
                self._url(f"{self.phone_number_id}/media"),
                headers={"Authorization": f"Bearer {self.token}"},
                data={"messaging_product": "whatsapp"},
                files={"file": (filename, data, mime)})
            j = r.json()
            if r.status_code >= 400:
                err = (j.get("error") or {})
                raise WAError(r.status_code, err.get("code"),
                              err.get("message") or "media upload failed")
            return j["id"]

    async def send_document(self, to: str, media_id: str, filename: str,
                            caption: str = "") -> dict:
        return await self._post({
            "messaging_product": "whatsapp", "recipient_type": "individual",
            "to": to, "type": "document",
            "document": {"id": media_id, "filename": filename,
                         "caption": caption[:1024]}})


class WAError(Exception):
    def __init__(self, status: int, code, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


RETRYABLE_CODES = {4, 80007, 130429, 131056, 131048}


# ------------------------------------------------------------ queue worker
async def _resolve_attachment(att: dict) -> Optional[Dict[str, Any]]:
    """Return {filename, mime, data(bytes)} for an attachment spec."""
    if not att:
        return None
    if att.get("b64"):
        return {"filename": att.get("filename") or "document",
                "mime": att.get("mime") or "application/octet-stream",
                "data": _b64.b64decode(att["b64"])}
    if att.get("payslip"):
        p = att["payslip"]
        import server as _srv
        rows, month_days, _src = await _srv._payslip_rows_for_month(
            p["company_id"], p["month"])
        row = next((r for r in rows if r.get("user_id") == p["user_id"]), None)
        if not row:
            return None
        emp = await db.users.find_one({"user_id": p["user_id"]}, {"_id": 0}) or {}
        comp = await db.companies.find_one(
            {"company_id": p["company_id"]}, {"_id": 0}) or {}
        from utils.payslip_pdf import build_payslip_pdf
        pdf = build_payslip_pdf(employee=emp, company=comp,
                                row={**row, "month_days": month_days},
                                month=p["month"])
        fn = f"Payslip_{emp.get('employee_code') or p['user_id']}_{p['month']}.pdf"
        return {"filename": fn, "mime": "application/pdf", "data": pdf}
    return None


async def _send_one(msg: dict, s: Dict[str, Any]) -> None:
    client = WhatsAppClient(s)
    tpl = None
    if msg.get("template_id"):
        tpl = await db.wa_templates.find_one(
            {"template_id": msg["template_id"]}, {"_id": 0})
    att = await _resolve_attachment(msg.get("attachment") or {})
    resp = None
    if att:
        limit = float(s.get("attachment_limit_mb") or 16) * 1024 * 1024
        if len(att["data"]) > limit:
            raise WAError(400, "attachment_too_large",
                          f"Attachment exceeds {s.get('attachment_limit_mb')} MB limit")
        media_id = await client.upload_media(att["filename"], att["mime"], att["data"])
        resp = await client.send_document(
            msg["to"], media_id, att["filename"], caption=msg.get("body") or "")
    elif tpl and tpl.get("meta_template_name"):
        ctx_vals = _VAR_RE.findall(tpl.get("body") or "")
        # rendered body already substituted; send rendered values in order
        params: List[str] = []
        # re-render each var against last known values is not possible here;
        # fallback: send rendered full body as single param when vars exist
        if ctx_vals:
            params = [msg.get("body") or ""]
        resp = await client.send_meta_template(
            msg["to"], tpl["meta_template_name"], tpl.get("language") or "en", params)
    else:
        resp = await client.send_text(msg["to"], msg.get("body") or "")
    wa_id = None
    try:
        wa_id = (resp.get("messages") or [{}])[0].get("id")
    except Exception:
        pass
    await db.wa_messages.update_one(
        {"msg_id": msg["msg_id"]},
        {"$set": {"status": "sent", "sent_at": now_iso(),
                  "wa_message_id": wa_id, "error": None,
                  "response_code": 200}})


async def _sent_today_count(company_id: str) -> int:
    start = datetime.now(IST).replace(hour=0, minute=0, second=0).astimezone(timezone.utc).isoformat()
    return await db.wa_messages.count_documents(
        {"company_id": company_id, "sent_at": {"$gte": start}})


async def process_queue(batch: int = 25) -> int:
    """Drain due queued messages. Returns number attempted."""
    now = now_iso()
    cur = db.wa_messages.find(
        {"status": "queued", "scheduled_at": {"$lte": now}},
        {"_id": 0}).sort("created_at", 1).limit(batch)
    n = 0
    settings_cache: Dict[str, dict] = {}
    async for msg in cur:
        cid = msg["company_id"]
        s = settings_cache.get(cid)
        if s is None:
            s = await get_settings(cid)
            settings_cache[cid] = s
        # claim atomically so parallel workers never double-send
        claimed = await db.wa_messages.update_one(
            {"msg_id": msg["msg_id"], "status": "queued"},
            {"$set": {"status": "sending"}})
        if claimed.modified_count == 0:
            continue
        n += 1
        if not _configured(s):
            await db.wa_messages.update_one(
                {"msg_id": msg["msg_id"]},
                {"$set": {"status": "failed", "error": "not_configured",
                          "response_code": 0}})
            continue
        if not s.get("queue_enabled", True):
            await db.wa_messages.update_one(
                {"msg_id": msg["msg_id"]}, {"$set": {"status": "queued"}})
            continue
        if await _sent_today_count(cid) >= int(s.get("daily_limit") or 1000):
            # push to tomorrow 00:05 IST
            nxt = (datetime.now(IST).replace(hour=0, minute=5) + timedelta(days=1))
            await db.wa_messages.update_one(
                {"msg_id": msg["msg_id"]},
                {"$set": {"status": "queued",
                          "scheduled_at": nxt.astimezone(timezone.utc).isoformat(),
                          "error": "daily_limit_reached"}})
            continue
        try:
            await _send_one(msg, s)
        except WAError as e:
            retryable = e.code in RETRYABLE_CODES or e.status >= 500
            rc = int(msg.get("retry_count") or 0)
            can_retry = (s.get("retry_failed", True) and retryable
                         and rc < int(s.get("max_retries") or 3))
            upd = {"error": f"{e.code}: {e.message}"[:300],
                   "response_code": e.status,
                   "retry_count": rc + (1 if can_retry else 0)}
            if can_retry:
                delay = 4 ** (rc + 1)
                upd["status"] = "queued"
                upd["scheduled_at"] = (
                    datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            else:
                upd["status"] = "failed"
            await db.wa_messages.update_one(
                {"msg_id": msg["msg_id"]}, {"$set": upd})
        except Exception as e:  # network / unexpected
            rc = int(msg.get("retry_count") or 0)
            can_retry = s.get("retry_failed", True) and rc < int(s.get("max_retries") or 3)
            await db.wa_messages.update_one(
                {"msg_id": msg["msg_id"]},
                {"$set": {"status": "queued" if can_retry else "failed",
                          "retry_count": rc + 1,
                          "scheduled_at": (datetime.now(timezone.utc)
                                           + timedelta(seconds=60)).isoformat(),
                          "error": str(e)[:300]}})
        await asyncio.sleep(0.3)  # pair-rate friendliness
    return n


# ------------------------------------------------------------- daily scans
async def _active_employees(company_id: str) -> List[dict]:
    return await db.users.find(
        {"company_id": company_id, "role": "employee",
         "$or": [{"exit_date": None}, {"exit_date": {"$exists": False}}, {"exit_date": ""}],
         "active": {"$ne": False}},
        {"_id": 0}).to_list(100000)


def _mmdd(v: Optional[str]) -> Optional[str]:
    """Return MM-DD from DD-MM-YYYY or YYYY-MM-DD strings."""
    if not v:
        return None
    v = str(v)[:10]
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", v)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return f"{m.group(2)}-{m.group(3)}"
    return None


async def daily_scan(company_id: str, s: Dict[str, Any]) -> None:
    """Birthday / anniversary / absence / doc-reminder / holiday scans."""
    auto = s.get("automation") or {}
    today = ist_today()
    today_mmdd = today[5:7] + "-" + today[8:10]
    emps = await _active_employees(company_id)

    if auto.get("birthday") or auto.get("anniversary"):
        for u in emps:
            if auto.get("birthday") and _mmdd(u.get("dob")) == today_mmdd:
                await enqueue_message(company_id=company_id, user=u,
                                      category="birthday", source="auto",
                                      created_by="daily-scan")
            if auto.get("anniversary") and _mmdd(u.get("doj")) == today_mmdd \
                    and str(u.get("doj") or "")[-4:] != today[:4]:
                await enqueue_message(company_id=company_id, user=u,
                                      category="anniversary", source="auto",
                                      created_by="daily-scan")

    if auto.get("absent_today") or auto.get("continuous_absence"):
        punched_today = set()
        async for a in db.attendance.find(
                {"company_id": company_id, "date": today}, {"_id": 0, "user_id": 1}):
            punched_today.add(a["user_id"])
        import server as _srv
        holi = await _srv.holiday_dates_for_company(company_id)
        if today not in holi and datetime.now(IST).weekday() != 6:  # skip Sun/holiday
            for u in emps:
                if u["user_id"] in punched_today:
                    continue
                if auto.get("absent_today"):
                    await enqueue_message(
                        company_id=company_id, user=u, category="absent_today",
                        extra={"Date": today}, source="auto",
                        created_by="daily-scan")
                if auto.get("continuous_absence"):
                    # count consecutive absent days (up to 30 back)
                    streak = 0
                    for i in range(0, 30):
                        d = (datetime.now(IST) - timedelta(days=i)).strftime("%Y-%m-%d")
                        if d in holi:
                            continue
                        rec = await db.attendance.find_one(
                            {"company_id": company_id, "user_id": u["user_id"],
                             "date": d}, {"_id": 1})
                        if rec:
                            break
                        streak += 1
                    if streak >= 3:
                        await enqueue_message(
                            company_id=company_id, user=u,
                            category="continuous_absence",
                            extra={"Attendance": str(streak)}, source="auto",
                            created_by="daily-scan")

    if auto.get("holiday_reminder"):
        tomorrow = (datetime.now(IST) + timedelta(days=1)).strftime("%Y-%m-%d")
        m_ = await db.masters.find_one(
            {"type": "holiday", "date": tomorrow,
             "company_id": {"$in": [company_id, "__global__", None]}},
            {"_id": 0, "name": 1})
        if m_:
            for u in emps:
                await enqueue_message(
                    company_id=company_id, user=u, category="holiday_reminder",
                    extra={"Holiday": m_.get("name") or "Holiday", "Date": tomorrow},
                    source="auto", created_by="daily-scan")

    if auto.get("document_reminder"):
        doc_fields = [("aadhaar", "Aadhaar"), ("pan", "PAN"),
                      ("bank_account", "Bank Details")]
        for u in emps:
            missing = [lbl for f, lbl in doc_fields if not u.get(f)]
            if missing:
                await enqueue_message(
                    company_id=company_id, user=u, category="document_reminder",
                    extra={"Status": ", ".join(missing)}, source="auto",
                    created_by="daily-scan")


async def process_schedules() -> int:
    now = now_iso()
    n = 0
    async for sc in db.wa_schedules.find(
            {"active": {"$ne": False}, "next_run_at": {"$lte": now}}, {"_id": 0}):
        n += 1
        try:
            await _run_schedule(sc)
        except Exception:
            if logger:
                logger.warning("[wa] schedule run failed", exc_info=True)
        nxt = _next_run(sc)
        upd = {"last_run_at": now_iso()}
        if nxt:
            upd["next_run_at"] = nxt
        else:
            upd["active"] = False
        await db.wa_schedules.update_one(
            {"schedule_id": sc["schedule_id"]}, {"$set": upd})
    return n


def _next_run(sc: dict) -> Optional[str]:
    typ = sc.get("type")
    if typ == "once":
        return None
    now = datetime.now(IST)
    hh, mm = (sc.get("time") or "09:00").split(":")
    base = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if typ == "daily":
        nxt = base + timedelta(days=1)
    elif typ == "weekly":
        nxt = base + timedelta(days=7)
    elif typ == "monthly":
        nxt = (base.replace(day=1) + timedelta(days=32)).replace(
            day=min(int(sc.get("day_of_month") or base.day), 28))
    else:
        return None
    return nxt.astimezone(timezone.utc).isoformat()


async def _run_schedule(sc: dict) -> None:
    company_id = sc["company_id"]
    target = sc.get("target") or {}
    users = await resolve_targets(company_id, target)
    for u in users:
        await enqueue_message(
            company_id=company_id, user=u,
            category=sc.get("category") or "custom",
            body=sc.get("custom_body") or None,
            source="scheduled", created_by=f"schedule:{sc['schedule_id']}",
            dedupe=False)


async def resolve_targets(company_id: str, target: dict) -> List[dict]:
    mode = target.get("mode") or "company"
    q: Dict[str, Any] = {"company_id": company_id, "role": "employee",
                         "active": {"$ne": False}}
    if mode == "employees" and target.get("user_ids"):
        q = {"user_id": {"$in": target["user_ids"]}}
    elif mode == "department" and target.get("department"):
        q["department"] = target["department"]
    return await db.users.find(q, {"_id": 0}).to_list(100000)


# ---------------------------------------------------------------- chatbot
async def chatbot_reply(company_id: str, from_number: str, text: str) -> Optional[str]:
    kw = (text or "").strip().upper().split()[0] if text else ""
    if kw not in CHATBOT_KEYWORDS:
        return None
    last10 = re.sub(r"\D", "", from_number)[-10:]
    u = await db.users.find_one(
        {"company_id": company_id, "role": "employee",
         "$or": [{"phone": {"$regex": f"{last10}$"}},
                 {"whatsapp_number": {"$regex": f"{last10}$"}}]},
        {"_id": 0})
    if not u:
        return ("Sorry, we could not match your WhatsApp number to an employee "
                "record. Please contact HR.")
    name = u.get("name") or "Employee"
    if kw == "HELP":
        return (f"Hi {name}! Send any of these keywords:\n" +
                "\n".join(f"• {k}" for k in CHATBOT_KEYWORDS if k != "HELP"))
    if kw == "PROFILE":
        return (f"👤 {name}\nCode: {u.get('employee_code') or '—'}\n"
                f"Department: {u.get('department') or '—'}\n"
                f"Designation: {u.get('position') or '—'}\nDOJ: {u.get('doj') or '—'}")
    if kw == "PF":
        return (f"PF details for {name}:\nUAN: {u.get('uan') or '—'}\n"
                f"PF No: {u.get('pf_number') or u.get('pf_no') or '—'}")
    if kw == "ESIC":
        return f"ESIC number for {name}: {u.get('esic_number') or u.get('esic_no') or '—'}"
    if kw == "BANK":
        acct = str(u.get("bank_account") or "")
        masked = ("•••• " + acct[-4:]) if len(acct) >= 4 else "—"
        return (f"Bank details for {name}:\nA/c: {masked}\n"
                f"IFSC: {u.get('ifsc') or u.get('bank_ifsc') or '—'}")
    if kw == "HOLIDAY":
        today = ist_today()
        rows = await db.masters.find(
            {"type": "holiday", "date": {"$gte": today},
             "company_id": {"$in": [company_id, "__global__", None]}},
            {"_id": 0, "date": 1, "name": 1}).sort("date", 1).limit(5).to_list(5)
        if not rows:
            return "No upcoming holidays found."
        return "📅 Upcoming holidays:\n" + "\n".join(
            f"• {r.get('date')}: {r.get('name') or 'Holiday'}" for r in rows)
    if kw == "SALARY":
        slip = await db.payslips.find_one(
            {"user_id": u["user_id"]}, {"_id": 0},
            sort=[("month", -1)])
        if not slip:
            return "No processed salary found yet. Please contact HR."
        net = slip.get("net_pay") or slip.get("net") or slip.get("net_salary")
        return (f"💰 Latest salary ({slip.get('month')}):\n"
                f"Net Pay: ₹{net if net is not None else '—'}\n"
                f"Status: {slip.get('status') or 'processed'}")
    if kw == "ATTENDANCE":
        month = ist_today()[:7]
        days = await db.attendance.distinct(
            "date", {"user_id": u["user_id"],
                     "date": {"$regex": f"^{month}"}})
        return (f"🗓 Attendance for {month}: present on {len(days)} day(s) "
                f"so far.")
    if kw == "LEAVE":
        rows = await db.leaves.find(
            {"user_id": u["user_id"]}, {"_id": 0, "status": 1, "from_date": 1,
                                        "to_date": 1, "leave_type": 1}
        ).sort("created_at", -1).limit(3).to_list(3)
        if not rows:
            return "No leave records found."
        return "🌴 Your recent leaves:\n" + "\n".join(
            f"• {r.get('leave_type') or 'Leave'} {r.get('from_date')} → "
            f"{r.get('to_date')}: {r.get('status')}" for r in rows)
    return None


# ------------------------------------------------------------ worker loop
_started = False


async def wa_worker_loop():
    if logger:
        logger.info("[wa] WhatsApp queue worker started (20s cadence)")
    last_daily: Dict[str, str] = {}
    last_cleanup = ""
    while True:
        try:
            await process_queue()
            await process_schedules()
            # daily scans — run once per company per day at/after 09:30 IST
            now = datetime.now(IST)
            if now.hour >= 9 and (now.hour > 9 or now.minute >= 30):
                today = ist_today()
                async for s in db.wa_settings.find(
                        {"enabled": True}, {"_id": 0}):
                    cid = s.get("company_id")
                    if not cid:
                        continue
                    marker = last_daily.get(cid) or s.get("last_daily_scan") or ""
                    if marker == today:
                        continue
                    full = {**DEFAULT_SETTINGS, **s}
                    await daily_scan(cid, full)
                    last_daily[cid] = today
                    await db.wa_settings.update_one(
                        {"company_id": cid},
                        {"$set": {"last_daily_scan": today}})
                # log auto-cleanup once a day
                if last_cleanup != today:
                    async for s in db.wa_settings.find({}, {"_id": 0}):
                        days = int(s.get("auto_delete_days") or 0)
                        if days > 0:
                            cutoff = (datetime.now(timezone.utc)
                                      - timedelta(days=days)).isoformat()
                            await db.wa_messages.delete_many(
                                {"company_id": s.get("company_id"),
                                 "created_at": {"$lt": cutoff}})
                    last_cleanup = today
        except Exception:
            if logger:
                logger.warning("[wa] worker loop error", exc_info=True)
        await asyncio.sleep(20)


def maybe_start(app, _db, _logger) -> None:
    global db, logger, _started
    db, logger = _db, _logger
    if _started:
        return
    _started = True

    @app.on_event("startup")
    async def _start_wa_worker():
        asyncio.get_event_loop().create_task(wa_worker_loop())
