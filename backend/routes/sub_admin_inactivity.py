"""Iter 157 — Sub Admin inactivity monitor.

Policy (user request):
  * 25 days without a login  -> warn the Sub Admin (in-app + push + email).
  * 30 days without a login  -> AUTO-DISABLE the account and notify every
    Super Admin (in-app + push + email) so they can re-enable it manually
    from User Rights -> Sub Admins if needed.

The "inactivity clock" = the most recent of: PIN login, password login,
account creation, or a manual re-enable (``reactivated_at`` set by the
PATCH /admin/sub-admins/{id} handler).
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from server import db, logger, now_iso  # noqa: E402

WARN_DAYS = 25
DISABLE_DAYS = 30
CHECK_INTERVAL_SEC = 6 * 3600  # 4 sweeps a day


def _parse_iso(s: Any) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _last_activity(u: Dict[str, Any]) -> Optional[datetime]:
    stamps = [
        _parse_iso(u.get("pin_last_login_at")),
        _parse_iso(u.get("password_last_login_at")),
        _parse_iso(u.get("reactivated_at")),
        _parse_iso(u.get("created_at")),
    ]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


async def _in_app(target_user_id: str, ntype: str, title: str, body: str):
    await db.notifications.insert_one({
        "notification_id": f"n_{uuid.uuid4().hex[:10]}",
        "company_id": None,
        "audience": "user",
        "target_user_id": target_user_id,
        "type": ntype,
        "title": title,
        "body": body,
        "created_at": now_iso(),
        "created_by": "system",
    })


async def _push(user_id: str, title: str, body: str, url: str = "/sub-admins"):
    try:
        from routes.web_push import push_to_user
        await push_to_user(user_id, title, body, url=url, tag="subadmin-inactivity")
    except Exception:
        logger.exception("[SUBADMIN INACTIVITY] push failed for %s", user_id)


async def _email(to_email: Optional[str], subject: str, body: str):
    if not to_email:
        return
    try:
        from routes.email_notifications import _get_settings, _send_and_log
        settings = await _get_settings()
        if not settings or not settings.get("enabled", True):
            return
        await _send_and_log(settings, to_email, subject, body,
                            event="subadmin_inactivity")
    except Exception:
        logger.exception("[SUBADMIN INACTIVITY] email failed to %s", to_email)


def _fmt(dt: Optional[datetime]) -> str:
    return dt.strftime("%d-%m-%Y") if dt else "—"


async def _warn_sub_admin(u: Dict[str, Any], days: int, last_iso: str):
    left = max(1, DISABLE_DAYS - days)
    title = "⚠️ Account inactivity warning"
    body = (
        f"Hi {u.get('name') or 'Admin'}, you haven't signed in for {days} days. "
        f"Your Sub Admin account will be automatically disabled after "
        f"{DISABLE_DAYS} days of inactivity (~{left} day{'s' if left != 1 else ''} left). "
        f"Please sign in to keep it active."
    )
    await _in_app(u["user_id"], "subadmin.inactivity_warning", title, body)
    await _push(u["user_id"], title, body, url="/")
    await _email(u.get("email"), "S.K. Sharma & Co. — account inactivity warning", body)
    await db.users.update_one(
        {"user_id": u["user_id"]},
        {"$set": {"inactivity_warned_for": last_iso,
                  "inactivity_warned_at": now_iso()}})
    logger.info("[SUBADMIN INACTIVITY] warned %s (%s days)", u.get("name"), days)


async def _auto_disable(u: Dict[str, Any], days: int,
                        last: Optional[datetime],
                        super_admins: List[Dict[str, Any]]):
    await db.users.update_one(
        {"user_id": u["user_id"]},
        {"$set": {
            "disabled": True,
            "disabled_reason": "auto_inactivity",
            "auto_disabled_at": now_iso(),
            "updated_at": now_iso(),
        }})
    name = u.get("name") or u.get("email") or u["user_id"]
    title = "🔒 Sub Admin auto-disabled (30 days inactive)"
    body = (
        f"Sub Admin '{name}' was automatically disabled after {days} days "
        f"without a login (last login: {_fmt(last)}). "
        f"You can re-enable the account anytime from User Rights → Sub Admins."
    )
    for sa in super_admins:
        await _in_app(sa["user_id"], "subadmin.auto_disabled", title, body)
        await _push(sa["user_id"], title, body, url="/sub-admins")
        await _email(sa.get("email"),
                     "S.K. Sharma & Co. — Sub Admin auto-disabled", body)
    # Also tell the sub admin why they can no longer log in.
    await _email(
        u.get("email"),
        "S.K. Sharma & Co. — your account was disabled",
        (f"Hi {u.get('name') or 'Admin'}, your Sub Admin account was "
         f"automatically disabled after {DISABLE_DAYS} days of inactivity. "
         f"Please contact S.K. Sharma & Co. to re-activate it."))
    logger.info("[SUBADMIN INACTIVITY] auto-disabled %s (%s days)", name, days)


async def _tick():
    now = datetime.now(timezone.utc)
    subs = await db.users.find(
        {"role": "sub_admin"},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "disabled": 1,
         "pin_last_login_at": 1, "password_last_login_at": 1,
         "reactivated_at": 1, "created_at": 1, "inactivity_warned_for": 1},
    ).to_list(500)
    supers: Optional[List[Dict[str, Any]]] = None
    for u in subs:
        if u.get("disabled"):
            continue
        last = _last_activity(u)
        if not last:
            continue
        days = (now - last).days
        if days >= DISABLE_DAYS:
            if supers is None:
                supers = await db.users.find(
                    {"role": "super_admin", "disabled": {"$ne": True}},
                    {"_id": 0, "user_id": 1, "name": 1, "email": 1},
                ).to_list(50)
            await _auto_disable(u, days, last, supers)
        elif days >= WARN_DAYS:
            last_iso = last.isoformat()
            if u.get("inactivity_warned_for") != last_iso:
                await _warn_sub_admin(u, days, last_iso)


async def inactivity_loop():
    """Background loop started from server.py startup()."""
    await asyncio.sleep(120)  # let the app finish booting
    logger.info("[SUBADMIN INACTIVITY] monitor started (warn %sd / disable %sd)",
                WARN_DAYS, DISABLE_DAYS)
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("[SUBADMIN INACTIVITY] tick failed")
        await asyncio.sleep(CHECK_INTERVAL_SEC)
