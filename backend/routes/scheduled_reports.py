"""Iter 486 — CLRA Phase 3: SCHEDULED EMAIL REPORTS.

Admins schedule any CLRA / Labour-Code register to be emailed automatically
(daily / weekly / monthly, IST) to chosen recipients as an Excel or PDF
attachment. Uses the firm's existing SMTP settings (Communication → Email
Settings) — nothing is sent if SMTP isn't configured.

    GET    /api/admin/report-schedules?company_id=
    POST   /api/admin/report-schedules            (create / update)
    DELETE /api/admin/report-schedules/{schedule_id}
    POST   /api/admin/report-schedules/{schedule_id}/send-now  (test fire)

Background loop (started from server.py startup) checks every 5 minutes.
"""
import asyncio
import calendar
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import db, get_user_from_token, require_role  # noqa: E402

logger = logging.getLogger("scheduled_reports")
router = APIRouter(prefix="/api/admin", tags=["report-schedules"])

IST = timezone(timedelta(hours=5, minutes=30))
FREQUENCIES = ("daily", "weekly", "monthly")


async def _adm(authorization, company_id):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return admin, company_id


@router.get("/report-schedules")
async def schedules_list(company_id: Optional[str] = None,
                         authorization: Optional[str] = Header(None)):
    _, company_id = await _adm(authorization, company_id)
    rows = await db.report_schedules.find(
        {"company_id": company_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"schedules": rows}


@router.post("/report-schedules")
async def schedules_save(payload: Dict[str, Any] = Body(...),
                         authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(authorization, payload.get("company_id"))
    from routes.clra_labour_reports import _TITLES
    kind = (payload.get("report_kind") or "").strip()
    if kind not in _TITLES:
        raise HTTPException(status_code=400, detail="Unknown report kind")
    freq = (payload.get("frequency") or "monthly").lower()
    if freq not in FREQUENCIES:
        raise HTTPException(status_code=400, detail="frequency must be daily/weekly/monthly")
    recipients = [e.strip() for e in (payload.get("recipients") or [])
                  if (e or "").strip() and "@" in e]
    if not recipients:
        raise HTTPException(status_code=400, detail="At least one recipient email is required")
    hhmm = (payload.get("time") or "09:00").strip()
    try:
        hh, mm = hhmm.split(":")
        assert 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
    except Exception:
        raise HTTPException(status_code=400, detail="time must be HH:MM (24h IST)")
    doc = {
        "schedule_id": payload.get("schedule_id") or f"rsch_{uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "report_kind": kind,
        "fmt": "pdf" if (payload.get("fmt") or "xlsx") == "pdf" else "xlsx",
        "frequency": freq,
        "weekday": int(payload.get("weekday") or 0),          # 0=Mon (weekly)
        "day_of_month": int(payload.get("day_of_month") or 1),  # monthly
        "time": f"{int(hh):02d}:{int(mm):02d}",
        "recipients": recipients,
        "use_previous_month": bool(payload.get("use_previous_month", freq == "monthly")),
        "enabled": bool(payload.get("enabled", True)),
        "created_by": admin.get("user_id"),
        "created_at": payload.get("created_at") or datetime.now(IST).isoformat(),
        "updated_at": datetime.now(IST).isoformat(),
    }
    await db.report_schedules.update_one(
        {"schedule_id": doc["schedule_id"], "company_id": company_id},
        {"$set": doc}, upsert=True)
    return {"ok": True, "schedule": doc}


@router.delete("/report-schedules/{schedule_id}")
async def schedules_delete(schedule_id: str,
                           company_id: Optional[str] = None,
                           authorization: Optional[str] = Header(None)):
    _, company_id = await _adm(authorization, company_id)
    r = await db.report_schedules.delete_one(
        {"schedule_id": schedule_id, "company_id": company_id})
    return {"ok": True, "deleted": r.deleted_count}


@router.post("/report-schedules/{schedule_id}/send-now")
async def schedules_send_now(schedule_id: str,
                             company_id: Optional[str] = None,
                             authorization: Optional[str] = Header(None)):
    _, company_id = await _adm(authorization, company_id)
    s = await db.report_schedules.find_one(
        {"schedule_id": schedule_id, "company_id": company_id}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    ok, detail = await _send_schedule(s, test=True)
    if not ok:
        raise HTTPException(status_code=400, detail=detail)
    return {"ok": True, "detail": detail}


# ---------------------------------------------------------------- sending
def _target_month(s: Dict[str, Any], now: datetime) -> str:
    if s.get("use_previous_month"):
        first = now.replace(day=1) - timedelta(days=1)
        return first.strftime("%Y-%m")
    return now.strftime("%Y-%m")


async def _send_schedule(s: Dict[str, Any], test: bool = False) -> tuple:
    """Generate the report and email it. Returns (ok, detail)."""
    from routes.clra_labour_reports import (_CLRA, _TITLES, _company,
                                            _mlabel, compliance_act_line)
    from utils.register_export import register_pdf, register_xlsx
    from routes.email_notifications import _get_settings, _smtp_send
    settings = await _get_settings()
    if not settings:
        return False, ("SMTP is not configured — set it up in "
                       "Communication → Email Settings first.")
    now = datetime.now(IST)
    month = _target_month(s, now)
    kind = s["report_kind"]
    if kind not in _CLRA:
        return False, f"Unknown report kind {kind}"
    c = await _company(s["company_id"])
    title, cols, rows, totals = await _CLRA[kind](s["company_id"], month)
    columns = [{"key": k, "label": lb} for k, lb in cols]
    sub = (f"{c.get('name')} · {_mlabel(month)} · "
           f"{await compliance_act_line(s['company_id'])} · "
           f"Auto-emailed {now:%d-%m-%Y %H:%M} IST")
    if s.get("fmt") == "pdf":
        buf = register_pdf(title, sub, columns, rows, totals,
                           c.get("logo_base64"))
        mime, ext = "application/pdf", "pdf"
    else:
        buf = register_xlsx(title, sub, columns, rows, totals)
        mime = ("application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet")
        ext = "xlsx"
    content = buf.getvalue() if hasattr(buf, "getvalue") else buf.read()
    fname = f"{title.replace(' ', '_')}_{month}.{ext}"
    body = (f"Scheduled report: {_TITLES.get(kind, kind)}\n"
            f"Firm: {c.get('name')}\nPeriod: {_mlabel(month)}\n"
            f"Rows: {len(rows)}\n\n"
            f"{'(Manual test send)' if test else 'Sent automatically as per your report schedule.'}")
    sent = 0
    for to in s.get("recipients") or []:
        try:
            await _smtp_send(settings, to,
                             f"[{c.get('name')}] {title} — {_mlabel(month)}",
                             body,
                             attachments=[{"filename": fname,
                                           "content": content, "mime": mime}])
            sent += 1
        except Exception as e:
            logger.warning("[report-schedules] send to %s failed: %s", to, e)
    return (sent > 0,
            f"Sent to {sent}/{len(s.get('recipients') or [])} recipient(s)")


def _due_key(s: Dict[str, Any], now: datetime) -> Optional[str]:
    """Return the idempotency key if the schedule is due right now."""
    if now.strftime("%H:%M") < s.get("time", "09:00"):
        return None
    freq = s.get("frequency")
    if freq == "daily":
        return now.strftime("%Y-%m-%d")
    if freq == "weekly":
        if now.weekday() != int(s.get("weekday") or 0):
            return None
        return f"{now.isocalendar().year}-W{now.isocalendar().week}"
    # monthly — clamp the configured day to the month's length
    dom = min(int(s.get("day_of_month") or 1),
              calendar.monthrange(now.year, now.month)[1])
    if now.day != dom:
        return None
    return now.strftime("%Y-%m")


async def scheduled_reports_loop():
    """Background loop — every 5 minutes, fire due schedules exactly once."""
    await asyncio.sleep(30)  # let the app settle
    logger.info("[report-schedules] loop started")
    while True:
        try:
            now = datetime.now(IST)
            async for s in db.report_schedules.find({"enabled": True}, {"_id": 0}):
                key = _due_key(s, now)
                if not key or s.get("last_sent_key") == key:
                    continue
                ok, detail = await _send_schedule(s)
                await db.report_schedules.update_one(
                    {"schedule_id": s["schedule_id"]},
                    {"$set": {"last_sent_key": key,
                              "last_sent_at": now.isoformat(),
                              "last_sent_ok": ok,
                              "last_sent_detail": detail}})
                logger.info("[report-schedules] %s %s → %s",
                            s["schedule_id"], s["report_kind"], detail)
        except Exception:
            logger.exception("[report-schedules] loop iteration failed")
        await asyncio.sleep(300)
