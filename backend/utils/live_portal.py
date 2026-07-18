"""Live portal auto-login — in-app viewer backend.

Runs a server-side Playwright session that opens a government portal
(ESIC / EPFO), auto-fills the firm's saved User ID + Password, reads the
text captcha with the Emergent LLM vision reader, and clicks Login —
capturing a screenshot at EVERY step so the frontend can show the
process "live" (poll-based) inside the app.

Because a server-side headless browser session can't be handed to the
user's local Chrome, the UI polls ``get_session`` every ~1.5s and renders
the latest screenshot + step log, giving a real-time view of the robot.

Public API:
    start_live_login(db, company_id, portal) -> session_id (fires bg task)
    get_session(session_id) -> dict | None
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")

logger = logging.getLogger("live_portal")

# In-memory session store (single uvicorn process, asyncio loop).
_SESSIONS: Dict[str, Dict[str, Any]] = {}

_PORTAL_URLS = {
    "esic": "https://portal.esic.gov.in/EmployerPortal/ESICInsurancePortal/Portal_Loginnew.aspx",
    "epfo": "https://unifiedportal-emp.epfindia.gov.in/epfo/",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_session(portal: str) -> str:
    sid = f"llp_{uuid.uuid4().hex[:12]}"
    _SESSIONS[sid] = {
        "session_id": sid,
        "portal": portal,
        "status": "starting",   # starting|running|logged_in|failed|blocked|captcha_failed|done
        "message": "Preparing browser…",
        "steps": [],            # [{at, msg}]
        "screenshot_base64": None,
        "captcha_text": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    return sid


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(session_id)
    if not s:
        return None
    # Return a shallow copy without the heavy step-screenshots list bloat.
    return {
        "session_id": s["session_id"],
        "portal": s["portal"],
        "status": s["status"],
        "message": s["message"],
        "steps": s["steps"][-30:],
        "screenshot_base64": s["screenshot_base64"],
        "captcha_text": s.get("captcha_text"),
        "updated_at": s["updated_at"],
    }


def _step(sid: str, msg: str, status: Optional[str] = None,
          shot_b64: Optional[str] = None, captcha: Optional[str] = None) -> None:
    s = _SESSIONS.get(sid)
    if not s:
        return
    s["steps"].append({"at": _now_iso(), "msg": msg})
    s["message"] = msg
    s["updated_at"] = _now_iso()
    if status:
        s["status"] = status
    if shot_b64:
        s["screenshot_base64"] = shot_b64
    if captcha is not None:
        s["captcha_text"] = captcha
    logger.info("[live-portal %s] %s", sid, msg)


async def start_live_login(db, company_id: str, portal: str) -> str:
    sid = _new_session(portal)
    loop = asyncio.get_event_loop()
    loop.create_task(_run(db, sid, company_id, portal))
    return sid


async def _shot(page) -> Optional[str]:
    try:
        return base64.b64encode(await page.screenshot(full_page=False)).decode("ascii")
    except Exception:
        return None


async def _run(db, sid: str, company_id: str, portal: str) -> None:
    from utils.rpa_worker import (
        _fetch_creds, _find_captcha_image_b64, _fill_captcha_input,
        _click_login_submit, _detect_block_or_error, _login_succeeded,
        _reload_captcha,
    )
    from utils.captcha_reader import read_captcha

    try:
        creds = await _fetch_creds(db, company_id, portal)
    except Exception as exc:  # noqa: BLE001
        _step(sid, f"Could not load credentials: {exc}", status="failed")
        return
    if not creds:
        _step(
            sid,
            f"No {portal.upper()} User ID / Password saved on Firm Master. "
            "Add them under Firm Master → ESIC/EPF Detail and try again.",
            status="failed",
        )
        return

    url = creds.get("login_url") or _PORTAL_URLS.get(portal) or ""

    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception:
        _step(sid, "Browser engine unavailable on the server.", status="failed")
        return

    _step(sid, "Launching secure browser…", status="running")

    try:
        async with async_playwright() as pw:
            launch_kw: Dict[str, Any] = {"headless": True}
            proxy_url = (os.environ.get("PORTAL_PROXY_URL") or "").strip()
            if proxy_url:
                launch_kw["proxy"] = {"server": proxy_url}
            browser = await pw.chromium.launch(**launch_kw)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
            )
            page = await ctx.new_page()

            _step(sid, f"Opening the {portal.upper()} portal…")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            except Exception:  # noqa: BLE001
                _step(
                    sid,
                    "The government portal did not respond — it is not "
                    "reachable from this server's network. Indian government "
                    "portals (ESIC/EPFO) block cloud/datacenter IPs. Run the "
                    "auto-login from an allowed Indian ISP network, or set "
                    "PORTAL_PROXY_URL in the backend to route through one.",
                    status="blocked",
                    shot_b64=await _shot(page),
                )
                await browser.close()
                return
            await page.wait_for_timeout(1200)
            _step(sid, "Portal loaded.", shot_b64=await _shot(page))

            blocked = await _detect_block_or_error(page)
            if blocked:
                _step(sid, blocked + " The portal is blocking this server's IP.",
                      status="blocked", shot_b64=await _shot(page))
                await browser.close()
                return

            MAX = 3
            attempts = 0
            for attempts in range(1, MAX + 1):
                _step(sid, "Filling User ID and Password from Firm Master…")
                await _fill_credentials(page, creds)
                await page.wait_for_timeout(400)
                _step(sid, "User ID and Password entered.", shot_b64=await _shot(page))

                cap_b64 = await _find_captcha_image_b64(page)
                if not cap_b64:
                    # No captcha on this form — just submit.
                    _step(sid, "No captcha detected — signing in…")
                    await _click_login_submit(page)
                    await page.wait_for_timeout(3000)
                    break

                _step(sid, "Reading the captcha with AI vision…")
                numeric = portal == "esic"
                text = await read_captcha(
                    cap_b64, numeric_only=numeric, session_id=f"live-{sid}-{attempts}")
                if not text:
                    _step(sid, f"Captcha unclear (try {attempts}/{MAX}) — refreshing…",
                          shot_b64=await _shot(page))
                    await _reload_captcha(page)
                    await page.wait_for_timeout(900)
                    continue

                _step(sid, f"Captcha read: {text}", captcha=text)
                await _fill_captcha_input(page, text)
                await page.wait_for_timeout(300)
                _step(sid, "Captcha entered — signing in…", shot_b64=await _shot(page))
                await _click_login_submit(page)
                await page.wait_for_timeout(3200)

                if await _login_succeeded(page):
                    break
                _step(sid, f"Sign-in not confirmed (try {attempts}/{MAX}) — retrying…",
                      shot_b64=await _shot(page))
                await _reload_captcha(page)
                await page.wait_for_timeout(900)

            success = await _login_succeeded(page)
            if success:
                _step(sid, "Signed in successfully. Loading dashboard…",
                      status="logged_in", shot_b64=await _shot(page))
                # Keep watching the dashboard render for a short while so the
                # user sees the logged-in portal "live".
                for _ in range(12):
                    await page.wait_for_timeout(2000)
                    shot = await _shot(page)
                    s = _SESSIONS.get(sid)
                    if not s or s["status"] == "closed":
                        break
                    if shot:
                        s["screenshot_base64"] = shot
                        s["updated_at"] = _now_iso()
                _step(sid, "Session finished. You are logged in on the portal above.",
                      status="done", shot_b64=await _shot(page))
            else:
                _step(sid,
                      f"Could not confirm login after {attempts} attempt(s). "
                      "The captcha may be too distorted or credentials incorrect.",
                      status="captcha_failed", shot_b64=await _shot(page))

            await browser.close()
    except Exception as exc:  # noqa: BLE001
        _step(sid, f"Automation error: {exc}", status="failed")


async def _fill_credentials(page, creds: Dict[str, str]) -> None:
    """Fill username + password across common ESIC/EPFO field selectors."""
    for sel in (
        "input[name*='user' i]", "input[id*='user' i]",
        "input[name='username']", "input#username",
        "input[type='text']:not([id*='captcha' i]):not([name*='captcha' i])",
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.fill(creds["user_name"], timeout=3000)
                break
        except Exception:
            continue
    for sel in (
        "input[type='password']", "input[name*='pass' i]", "input[id*='pass' i]",
        "input[name='password']", "input#password",
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.fill(creds["password"], timeout=3000)
                break
        except Exception:
            continue
