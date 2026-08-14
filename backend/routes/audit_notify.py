"""Iter 580 — Audit & Activity Email Notification Engine.

Connected to the existing audit system (activity_log). Instant emails for
CRITICAL activities, optional failed-login alerts, and a daily HTML
summary at 08:00 IST. Settings: Administration → Audit Notifications.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request

from server import db, get_user_from_token, require_role, now_iso, logger, _req_ip  # noqa: E402

router = APIRouter(prefix="/api")

DEFAULTS = {
    "key": "audit_email",
    "enabled": False,
    "recipients": [],
    "cc": [],
    "instant_enabled": True,
    "daily_enabled": True,
    "failed_login_notify": False,
}

_CRIT_FIELDS = ("bank", "ifsc", "account", "salary", "basic", "hra", "uan", "pf_", "esic")
_CRIT_PATHS = ("unlock", "rights", "roles", "permission", "sub-admins", "challan", "firm-access")


def is_critical(doc: dict) -> bool:
    action = (doc.get("action") or "").upper()
    path = (doc.get("path") or "").lower()
    module = doc.get("module") or ""
    if action.startswith("DELETE") and module in ("Employee", "Payroll", "Attendance"):
        return True
    if any(p in path for p in _CRIT_PATHS) and doc.get("method") in ("PUT", "PATCH", "POST", "DELETE"):
        return True
    for c in (doc.get("changes") or []):
        f = (c.get("field") or "").lower()
        if any(k in f for k in _CRIT_FIELDS):
            return True
    return False


async def _settings() -> dict:
    doc = await db.audit_notify_settings.find_one({"key": "audit_email"}, {"_id": 0}) or {}
    return {**DEFAULTS, **doc}


async def _send_email(subject: str, html: str, text: str, st: dict) -> bool:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    to = [e for e in (st.get("recipients") or []) if "@" in e]
    if not (api_key and to):
        return False
    payload = {"from": f"S.K. Sharma & Co. Audit <{os.getenv('RESEND_FROM_EMAIL', 'onboarding@resend.dev').strip()}>",
               "to": to, "subject": subject, "text": text, "html": html}
    cc = [e for e in (st.get("cc") or []) if "@" in e]
    if cc:
        payload["cc"] = cc
    try:
        async with httpx.AsyncClient(timeout=10.0) as hc:
            r = await hc.post("https://api.resend.com/emails",
                              headers={"Authorization": f"Bearer {api_key}"}, json=payload)
        logger.info(f"[audit-email] '{subject}' → {len(to)} rcpt ({r.status_code})")
        return r.status_code < 300
    except Exception:
        logger.warning("[audit-email] send failed", exc_info=True)
        return False


def _rows_html(pairs) -> str:
    return "".join(
        f"<tr><td style='padding:4px 14px 4px 0;color:#64748b;font-size:13px;white-space:nowrap'>{k}</td>"
        f"<td style='padding:4px 0;font-size:13px;color:#0f172a'><strong>{v}</strong></td></tr>"
        for k, v in pairs)


def _wrap(title: str, body: str) -> str:
    return ("<div style='font-family:Arial,sans-serif;max-width:640px;margin:0 auto;border:1px solid #e2e8f0;"
            "border-radius:10px;overflow:hidden'>"
            f"<div style='background:#1B3A6E;color:#fff;padding:14px 20px;font-size:15px;font-weight:bold'>{title}</div>"
            f"<div style='padding:18px 20px'>{body}"
            "<p style='font-size:12px;color:#64748b;margin-top:14px'>Full trail: Reports → Users Log Report in the payroll portal.</p></div>"
            "<div style='background:#1B3A6E;padding:12px 20px;text-align:center'>"
            "<span style='font-size:14px;font-weight:800;color:#E39A2A'>From S.K. Sharma &amp; Co</span><br/>"
            "<span style='font-size:12px;font-weight:700;color:#fff;font-style:italic'>Your Trusted Compliance Partner</span></div></div>")


async def on_audit_event(doc: dict):
    """Fire-and-forget hook called by the activity middleware."""
    try:
        st = await _settings()
        if not st["enabled"]:
            return
        failed_login = (doc.get("module") == "Auth") and (doc.get("success") is False)
        crit = is_critical(doc)
        if not ((crit and st["instant_enabled"]) or (failed_login and st["failed_login_notify"])):
            return
        actor = doc.get("actor_name") or doc.get("actor_id") or "Unknown"
        chg = "; ".join(f"{c['field']}: '{c.get('old')}' → '{c.get('new')}'" for c in (doc.get("changes") or [])[:5])
        pairs = [("Event", "CRITICAL ACTIVITY" if crit else "Failed Login"),
                 ("User", f"{actor} ({doc.get('actor_role') or '—'})"),
                 ("Action", doc.get("action") or ""),
                 ("Module", doc.get("module") or ""),
                 ("Record", doc.get("record_label") or doc.get("record_id") or "—"),
                 ("Changes", chg or "—"),
                 ("IP / Device", f"{doc.get('ip') or '—'} / {(doc.get('device') or '')[:60]}"),
                 ("Status", "Success" if doc.get("success") else f"FAILED ({doc.get('status')})"),
                 ("Time (UTC)", (doc.get("at") or "")[:19].replace("T", " "))]
        subj = ("🚨 Critical activity" if crit else "⚠️ Failed login") + f" — {actor}"
        await _send_email(subj, _wrap("🔐 Audit Alert — Smart Payroll", f"<table>{_rows_html(pairs)}</table>"),
                          "\n".join(f"{k}: {v}" for k, v in pairs), st)
    except Exception:
        logger.warning("[audit-email] hook failed", exc_info=True)


async def send_daily_summary(for_date: Optional[str] = None) -> dict:
    st = await _settings()
    day = for_date or (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30) - timedelta(days=1)).strftime("%Y-%m-%d")
    q = {"at": {"$gte": f"{day}T00:00:00", "$lte": f"{day}T23:59:59"}}
    total = fails = crit = 0
    by_user: dict = {}
    by_module: dict = {}
    async for e in db.activity_log.find(q, {"_id": 0}).limit(20000):
        total += 1
        if e.get("success") is False:
            fails += 1
        if is_critical(e):
            crit += 1
        u = e.get("actor_name") or e.get("actor_id") or "System"
        by_user[u] = by_user.get(u, 0) + 1
        m = e.get("module") or "Other"
        by_module[m] = by_module.get(m, 0) + 1
    top_u = sorted(by_user.items(), key=lambda kv: -kv[1])[:10]
    top_m = sorted(by_module.items(), key=lambda kv: -kv[1])[:10]
    pairs = [("Date", day), ("Total Activities", total), ("Failed Actions", fails),
             ("Critical Activities", crit), ("Active Users", len(by_user))]
    body = (f"<table>{_rows_html(pairs)}</table>"
            "<h4 style='margin:14px 0 6px'>By User</h4><table>" + _rows_html(top_u) + "</table>"
            "<h4 style='margin:14px 0 6px'>By Module</h4><table>" + _rows_html(top_m) + "</table>")
    ok = await _send_email(f"📊 Daily Activity Summary — {day}",
                           _wrap("📊 Daily Sub-User Activity Summary", body),
                           f"Daily summary {day}: {total} activities, {fails} failed, {crit} critical", st)
    return {"sent": ok, "date": day, "total": total, "failed": fails, "critical": crit}


async def daily_loop():
    while True:
        try:
            now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
            nxt = now_ist.replace(hour=8, minute=0, second=0, microsecond=0)
            if nxt <= now_ist:
                nxt += timedelta(days=1)
            await asyncio.sleep((nxt - now_ist).total_seconds())
            st = await _settings()
            if st["enabled"] and st["daily_enabled"]:
                await send_daily_summary()
        except Exception:
            logger.warning("[audit-email] daily loop error", exc_info=True)
            await asyncio.sleep(3600)


@router.get("/admin/audit-notify-settings")
async def get_notify_settings(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    return await _settings()


@router.put("/admin/audit-notify-settings")
async def put_notify_settings(payload: dict, request: Request,
                              authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    upd: dict = {}
    for k in ("enabled", "instant_enabled", "daily_enabled", "failed_login_notify"):
        if k in payload:
            upd[k] = bool(payload[k])
    for k in ("recipients", "cc"):
        if k in payload:
            v = payload[k]
            if isinstance(v, str):
                v = [x.strip() for x in v.split(",") if x.strip()]
            if not isinstance(v, list):
                raise HTTPException(status_code=400, detail=f"{k} must be a list")
            upd[k] = [e for e in v if "@" in e][:10]
    if not upd:
        raise HTTPException(status_code=400, detail="Nothing to update")
    upd.update({"key": "audit_email", "updated_at": now_iso(), "updated_by": admin["user_id"]})
    await db.audit_notify_settings.update_one({"key": "audit_email"}, {"$set": upd}, upsert=True)
    await db.activity_log.insert_one({
        "at": now_iso(), "actor_id": admin["user_id"], "actor_name": admin.get("name"),
        "actor_role": admin.get("role"), "company_id": None, "method": "PUT",
        "path": "/api/admin/audit-notify-settings", "action": "UPDATE AUDIT_NOTIFY_SETTINGS",
        "status": 200, "success": True, "module": "Settings", "record_id": "audit_email",
        "record_label": "Audit notification settings", "changes": [], "old_values": None,
        "new_values": None, "details": ", ".join(sorted(k for k in upd if k not in ("key", "updated_at", "updated_by"))),
        "device": (request.headers.get("user-agent") or "")[:200], "ip": _req_ip(request)})
    return {"ok": True}


@router.post("/admin/audit-notify-settings/send-daily-now")
async def send_daily_now(for_date: Optional[str] = Query(None),
                         authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    st = await _settings()
    if not st["enabled"]:
        raise HTTPException(status_code=400, detail="Enable notifications and add recipients first")
    return await send_daily_summary(for_date)
