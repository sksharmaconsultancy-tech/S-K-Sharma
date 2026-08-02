"""Iter 438 (user request) — email salary-process reports (PDF/Excel/CSV)
after Save / Finalize on the Compliance & Actual Salary screens.

Tries the admin-configured SMTP (Email Settings page) first, falling back
to the Resend key from the environment.
"""
import base64
import logging
from typing import Any, Dict, List

from fastapi import HTTPException

log = logging.getLogger("report_email")


async def send_report_email(
    to_email,
    subject: str,
    body: str,
    attachments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """``to_email``: one address or a list. ``attachments``:
    [{filename, content(bytes), mime}]."""
    if isinstance(to_email, str):
        to_email = [to_email]
    recipients = []
    for t in to_email or []:
        t = str(t or "").strip()
        if t and "@" in t and t not in recipients:
            recipients.append(t)
    if not recipients:
        raise HTTPException(status_code=400, detail="A valid recipient email is required")
    if not attachments:
        raise HTTPException(status_code=400, detail="No report attachments to send")

    # 1) Admin-configured SMTP (Email Settings)
    from routes.email_notifications import _get_settings, _smtp_send
    settings = await _get_settings()
    if settings and settings.get("username"):
        try:
            for rcpt in recipients:
                await _smtp_send(settings, rcpt, subject, body,
                                 attachments=attachments)
            return {"ok": True, "via": "smtp", "to": recipients}
        except Exception as e:  # noqa: BLE001
            log.warning("SMTP send failed (%s) — trying Resend fallback", e)

    # 2) Resend fallback (env key)
    from utils.iter60_features import _send_email_with_attachment
    res = await _send_email_with_attachment(
        recipients, subject, body,
        attachments=[{
            "filename": a["filename"],
            "content": base64.b64encode(a["content"]).decode(),
        } for a in attachments],
    )
    if not res.get("delivered"):
        raise HTTPException(
            status_code=400,
            detail="Email could not be sent — configure SMTP on the Email "
                   f"Settings page. ({res.get('error') or 'unknown error'})")
    return {"ok": True, "via": "resend", "to": recipients}


def normalize_formats(formats: Any,
                      allowed: tuple = ("pdf", "xlsx", "csv")) -> List[str]:
    """['all'] / 'all' / mixed → ordered unique subset of ``allowed``.
    Iter 440 (user request) — at least ONE format is MANDATORY; the mail
    carries EXACTLY the selected formats."""
    if isinstance(formats, str):
        formats = [formats]
    fl = [str(f or "").strip().lower() for f in (formats or [])]
    if "all" in fl:
        return list(allowed)
    out = [f for f in allowed if f in fl]
    if not out:
        raise HTTPException(
            status_code=400,
            detail="Select at least one report format "
                   f"({' / '.join(a.upper() for a in allowed)} / ALL)")
    return out

