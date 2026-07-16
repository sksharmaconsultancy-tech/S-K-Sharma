"""Iter 145 — Web Push Notifications (PWA).

Endpoints
---------
  * GET  /api/push/vapid-public-key  — public VAPID key for the browser.
  * POST /api/push/subscribe         — store the browser PushSubscription.
  * POST /api/push/unsubscribe       — remove a subscription.

Helpers (imported lazily from server.py hooks)
----------------------------------------------
  * push_to_user(user_id, title, body, url)          — all devices of a user.
  * push_to_company_admins(company_id, title, body)  — all admins of a firm
    (+ super admins), used for "new employee joining" alerts.

pywebpush is synchronous, so actual sends run in a thread executor and
never block the event loop. Dead subscriptions (404/410) are pruned.
"""
import asyncio
import json
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from pywebpush import webpush, WebPushException

from server import (  # noqa: E402
    db,
    get_user_from_token,
    now_iso,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["web-push"])

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS_EMAIL = os.environ.get("VAPID_CLAIMS_EMAIL", "mailto:admin@sksharma.co")


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscribe(BaseModel):
    endpoint: str
    keys: PushKeys
    ua: Optional[str] = None  # user-agent label, purely informational


class PushUnsubscribe(BaseModel):
    endpoint: str


@router.get("/push/vapid-public-key")
async def vapid_public_key():
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(status_code=503, detail="Push notifications not configured")
    return {"public_key": VAPID_PUBLIC_KEY}


@router.post("/push/subscribe")
async def push_subscribe(payload: PushSubscribe,
                         authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    # Upsert by endpoint — the same browser re-subscribing simply refreshes
    # its record (and re-binds it to whoever is currently logged in).
    await db.push_subscriptions.update_one(
        {"endpoint": payload.endpoint},
        {"$set": {
            "user_id": user["user_id"],
            "company_id": user.get("company_id"),
            "role": user.get("role"),
            "endpoint": payload.endpoint,
            "keys": payload.keys.model_dump(),
            "ua": payload.ua,
            "updated_at": now_iso(),
        }, "$setOnInsert": {
            "sub_id": f"psub_{uuid.uuid4().hex[:10]}",
            "created_at": now_iso(),
        }},
        upsert=True,
    )
    return {"ok": True}


@router.post("/push/unsubscribe")
async def push_unsubscribe(payload: PushUnsubscribe,
                           authorization: Optional[str] = Header(None)):
    await get_user_from_token(authorization)
    await db.push_subscriptions.delete_one({"endpoint": payload.endpoint})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Send helpers
# ---------------------------------------------------------------------------
def _send_one_sync(sub: dict, payload: str) -> bool:
    """Blocking send for ONE subscription. Returns False when the
    subscription is dead and should be deleted."""
    try:
        webpush(
            subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_CLAIMS_EMAIL},
        )
        return True
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):
            return False  # expired/unsubscribed — prune
        logger.warning(f"[PUSH] send failed ({status}): {e}")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PUSH] send error: {e}")
        return True


async def _send_to_subs(subs: list, title: str, body: str, url: str, tag: Optional[str]):
    if not subs or not VAPID_PRIVATE_KEY:
        return
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    loop = asyncio.get_running_loop()
    results = await asyncio.gather(
        *[loop.run_in_executor(None, _send_one_sync, s, payload) for s in subs],
        return_exceptions=True,
    )
    dead = [s["endpoint"] for s, ok in zip(subs, results) if ok is False]
    if dead:
        await db.push_subscriptions.delete_many({"endpoint": {"$in": dead}})


async def push_to_user(user_id: str, title: str, body: str,
                       url: str = "/", tag: Optional[str] = None):
    """Push to every device the user has subscribed."""
    subs = await db.push_subscriptions.find(
        {"user_id": user_id}, {"_id": 0, "endpoint": 1, "keys": 1}).to_list(20)
    await _send_to_subs(subs, title, body, url, tag)


async def push_to_company_admins(company_id: Optional[str], title: str, body: str,
                                 url: str = "/", tag: Optional[str] = None):
    """Push to all company admins of the firm + every super admin."""
    q = {"$or": [
        {"role": "super_admin"},
        {"role": "sub_admin"},
        {"role": "company_admin", "company_id": company_id},
    ]}
    subs = await db.push_subscriptions.find(
        q, {"_id": 0, "endpoint": 1, "keys": 1}).to_list(100)
    await _send_to_subs(subs, title, body, url, tag)


# ---------------------------------------------------------------------------
# Iter 146 — Geofence punch reminder.
#
# Every 10 minutes: any EMPLOYEE who (a) has a push subscription, (b) shared
# their location within the last 30 min, (c) is INSIDE their firm's office
# geofence, and (d) has NOT punched at all today, gets a "you're at office —
# punch in!" web-push. Max ONE reminder per employee per day
# (db.push_reminder_log), active window 07:00–21:00 IST wall-clock.
# ---------------------------------------------------------------------------
REMINDER_INTERVAL_SEC = 600
REMINDER_LOCATION_MAX_AGE_MIN = 30


def _parse_iso(s: Optional[str]):
    from datetime import datetime
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


async def _punch_reminder_tick():
    from datetime import datetime, timedelta, timezone
    from server import haversine_m, ist_wallclock_now

    now_ist = ist_wallclock_now()
    today = now_ist.strftime("%Y-%m-%d")

    sub_uids = await db.push_subscriptions.distinct("user_id")
    if not sub_uids:
        return

    loc_cutoff = datetime.now(timezone.utc) - timedelta(minutes=REMINDER_LOCATION_MAX_AGE_MIN)
    users = await db.users.find(
        {
            "user_id": {"$in": sub_uids},
            "role": "employee",
            "approval_status": "approved",
            "company_id": {"$ne": None},
            "last_location_lat": {"$ne": None},
            "last_location_lng": {"$ne": None},
        },
        {"_id": 0, "user_id": 1, "name": 1, "company_id": 1,
         "last_location_lat": 1, "last_location_lng": 1, "last_location_at": 1},
    ).to_list(3000)
    if not users:
        return

    comp_cache: dict = {}
    sent = 0
    for u in users:
        loc_at = _parse_iso(u.get("last_location_at"))
        if not loc_at:
            continue
        if loc_at.tzinfo is None:
            loc_at = loc_at.replace(tzinfo=timezone.utc)
        if loc_at < loc_cutoff:
            continue  # stale location — probably not at office anymore

        cid = u["company_id"]
        comp = comp_cache.get(cid)
        if comp is None:
            comp = await db.companies.find_one(
                {"company_id": cid},
                {"_id": 0, "name": 1, "office_lat": 1, "office_lng": 1,
                 "geofence_radius_m": 1}) or {}
            comp_cache[cid] = comp
        if not comp.get("office_lat") or not comp.get("office_lng"):
            continue
        dist = haversine_m(u["last_location_lat"], u["last_location_lng"],
                           comp["office_lat"], comp["office_lng"])
        if dist > (comp.get("geofence_radius_m") or 200):
            continue  # outside the geofence

        # Punched anything today? → no reminder needed.
        if await db.attendance.find_one(
                {"user_id": u["user_id"], "date": today}, {"_id": 1}):
            continue
        # Already reminded today? → max 1/day.
        if await db.push_reminder_log.find_one(
                {"user_id": u["user_id"], "date": today}, {"_id": 1}):
            continue

        await push_to_user(
            u["user_id"],
            "Punch In reminder ⏰",
            f"You are at {comp.get('name') or 'the office'} but haven't punched in yet. "
            "Tap to punch in now.",
            url="/attendance", tag=f"punch_reminder_{today}")
        await db.push_reminder_log.insert_one({
            "user_id": u["user_id"], "date": today,
            "company_id": cid, "distance_m": round(dist, 1),
            "sent_at": now_iso(),
        })
        sent += 1
    if sent:
        logger.info(f"[PUSH REMINDER] sent {sent} geofence punch-in reminder(s)")


async def punch_reminder_loop():
    """Background loop started from server.py startup()."""
    await asyncio.sleep(90)  # let the app finish booting
    logger.info("[PUSH REMINDER] geofence punch-reminder loop started (every 10 min)")
    while True:
        try:
            await _punch_reminder_tick()
        except Exception:
            logger.exception("[PUSH REMINDER] tick failed")
        await asyncio.sleep(REMINDER_INTERVAL_SEC)
