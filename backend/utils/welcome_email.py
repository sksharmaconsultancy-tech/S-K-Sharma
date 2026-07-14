"""Welcome email for newly created admin accounts (super admins & sub admins).

Sent via Resend (reuses utils.iter60_features._send_email_with_attachment).
Fire-and-forget — account creation NEVER fails because an email bounced.
"""
import logging
import os
from typing import Optional

log = logging.getLogger("welcome-email")


async def send_admin_welcome_email(
    *,
    name: str,
    email: str,
    role_label: str,
    password: Optional[str] = None,
) -> None:
    """Email the new admin their login details. Swallows all errors."""
    try:
        from utils.iter60_features import _send_email_with_attachment

        portal_url = os.getenv("APP_PUBLIC_URL", "").strip()
        lines = [
            f"Hello {name},",
            "",
            f"A {role_label} account has been created for you on the "
            "S.K. Sharma & Co. portal.",
            "",
            f"Login email: {email}",
        ]
        if password:
            lines += [
                f"Temporary password: {password}",
                "(You will be asked to change it on first login.)",
            ]
        lines += [
            "You can also sign in with a one-time code (OTP) sent to this email.",
        ]
        if portal_url:
            lines += ["", f"Portal: {portal_url}"]
        lines += ["", "— S.K. Sharma & Co."]

        r = await _send_email_with_attachment(
            to_emails=[email],
            subject=f"Your {role_label} account — S.K. Sharma & Co.",
            text_body="\n".join(lines),
        )
        if not r.get("delivered"):
            log.warning("welcome email to %s not delivered: %s", email, r.get("error"))
    except Exception as exc:  # noqa: BLE001 — never break account creation
        log.warning("welcome email to %s failed: %s", email, exc)
