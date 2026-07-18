"""Iter 89 — RPA worker skeleton for EPFO / ESIC portal automation.

Background async loop that consumes ``pending`` docs from the
``portal_automation_jobs`` collection with ``action_type`` in
{``generate_uan``, ``generate_esic``}. For each job, it:

  1. Loads the firm's Portal Login credentials from ``firm_masters``.
  2. Marks the job ``in_progress`` and appends a step-by-step log.
  3. Opens the portal in a headless Playwright browser (if available)
     and attempts login.
  4. Captures a screenshot AFTER LOGIN. Because Indian government
     portals (EPFO / ESIC) require a captcha AND OTP that we cannot
     automate legally at MVP scope, the worker STOPS at the "opened
     portal, ready for manual completion" checkpoint and marks the job
     ``manual_required``. The captured screenshot is stored on the job
     so the ops admin can pick up from the app.
  5. If Playwright is not installed, the worker degrades gracefully:
     it still records the intent, marks the job ``manual_required``,
     and logs the exact portal URL + credentials the ops admin needs.

Runbook (production): install playwright + browsers on the backend
pod, add captcha solver (2captcha) to `.env`, extend `_perform_login`
to detect the "UAN generated" success state, then flip the endpoint
in this file to write the UAN back to the employee record.

The worker is a fire-and-forget task started from server.py at
startup. Enable via ``RPA_WORKER_ENABLED=1`` in ``.env``.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Iter 89 — Ensure Playwright can find Chromium when uvicorn is started
# by supervisord (which does not inherit shell env). Default to the
# system-installed /pw-browsers if the caller hasn't set it.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")


logger = logging.getLogger("rpa_worker")

# Enable/disable the whole worker via env — off by default so dev doesn't
# spin up browser processes accidentally.
ENABLED = os.environ.get("RPA_WORKER_ENABLED", "0") == "1"

# Polling cadence — check the queue every N seconds. Keeps DB pressure
# minimal since new jobs are rare (one per employee onboarding).
POLL_SEC = int(os.environ.get("RPA_WORKER_POLL_SEC", "30"))

_PORTAL_URLS = {
    "epfo": "https://unifiedportal-emp.epfindia.gov.in/epfo/",
    "esic": "https://www.esic.in/EmployerPortal/",
}
_PORTAL_LOGIN_LABEL = {
    "epfo": "PF LOGIN",
    "esic": "ESI Login",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _fetch_creds(db, company_id: str, portal: str) -> Optional[Dict[str, str]]:
    master = await db.firm_masters.find_one(
        {"company_id": company_id},
        {"_id": 0, "portal_logins": 1, "epf": 1, "esi": 1},
    )
    if not master:
        return None
    # Iter 98 — PREFER the credentials saved on Firm Master's EPF Detail /
    # ESIC Detail sections (epf_user_id/epf_password, esi_user_id/esi_password).
    if portal == "epfo":
        sec = master.get("epf") or {}
        u = (sec.get("epf_user_id") or "").strip()
        p = (sec.get("epf_password") or "").strip()
        if u and p:
            return {
                "user_name": u, "password": p, "unit_location": None,
                "login_url": _PORTAL_URLS.get(portal) or "",
            }
    elif portal == "esic":
        sec = master.get("esi") or {}
        u = (sec.get("esi_user_id") or "").strip()
        p = (sec.get("esi_password") or "").strip()
        if u and p:
            return {
                "user_name": u, "password": p, "unit_location": None,
                "login_url": _PORTAL_URLS.get(portal) or "",
            }
    # Fallback — legacy Portal Logins rows ("PF LOGIN" / "ESI Login").
    label = _PORTAL_LOGIN_LABEL.get(portal)
    for row in (master.get("portal_logins") or []):
        if row.get("login_type") == label:
            u = (row.get("user_name") or "").strip()
            p = (row.get("password") or "").strip()
            if u and p:
                return {
                    "user_name": u,
                    "password": p,
                    "unit_location": row.get("unit_location") or None,
                    "login_url": (row.get("login_url") or _PORTAL_URLS.get(portal)) or "",
                }
    return None


async def _append_step(db, job_id: str, msg: str, screenshot_b64: Optional[str] = None) -> None:
    step = {"at": _now_iso(), "msg": msg}
    if screenshot_b64:
        step["screenshot_base64"] = screenshot_b64
    await db.portal_automation_jobs.update_one(
        {"job_id": job_id},
        {"$push": {"steps": step}, "$set": {"updated_at": _now_iso()}},
    )


async def _find_captcha_image_b64(page) -> Optional[str]:
    """Screenshot just the captcha image element and return base64 PNG."""
    for sel in (
        "img#captchaimg", "img[alt*='captcha' i]", "img[src*='captcha' i]",
        "img[id*='captcha' i]", "img[title*='captcha' i]", "#captcha img",
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                shot = await loc.screenshot()
                return base64.b64encode(shot).decode("ascii")
        except Exception:
            continue
    return None


async def _fill_captcha_input(page, value: str) -> bool:
    for sel in (
        "input[name='captcha' i]", "input#captcha", "input[id*='captcha' i]",
        "input[placeholder*='captcha' i]", "input[name*='captcha' i]",
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.fill("", timeout=2000)
                await loc.fill(value, timeout=3000)
                return True
        except Exception:
            continue
    return False


async def _click_login_submit(page) -> bool:
    for sel in (
        "button[type='submit']", "input[type='submit']",
        "button:has-text('Sign In')", "button:has-text('Login')",
        "button:has-text('Log In')", "#login", "#btnLogin", ".login-btn",
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=3000)
                return True
        except Exception:
            continue
    return False


async def _detect_block_or_error(page) -> Optional[str]:
    """Return a message if the portal blocked us / served an error page
    instead of the login form (common: government WAF blocks datacenter
    IPs). None means the page looks like a normal portal page."""
    try:
        body = (await page.inner_text("body", timeout=3000)) or ""
    except Exception:
        body = ""
    low = body.lower()
    markers = [
        "web page blocked", "access denied", "request blocked",
        "attack id", "forbidden", "not authorized to access",
        "your ip", "cannot be displayed",
    ]
    if any(m in low for m in markers):
        # Trim to a short human message.
        snippet = " ".join(body.split())[:200]
        return f"Portal blocked the request: {snippet}"
    return None


async def _login_succeeded(page) -> bool:
    """Heuristic: logged in if a captcha field is gone AND either the URL
    left the login page or a logout/dashboard marker is present. A blocked
    / error page is NEVER counted as success."""
    try:
        if await _detect_block_or_error(page):
            return False
        for sel in ("a:has-text('Logout')", "a:has-text('Sign Out')",
                    "text=Dashboard", "text=Welcome", "[href*='logout' i]"):
            if await page.locator(sel).first.count() > 0:
                return True
        # Captcha still on screen usually means we're still on the login form.
        still_captcha = await page.locator(
            "input[name*='captcha' i], img[id*='captcha' i]"
        ).count()
        url = (page.url or "").lower()
        if still_captcha == 0 and "login" not in url:
            return True
    except Exception:
        pass
    return False


async def _reload_captcha(page) -> None:
    """Click a refresh-captcha control if present, else reload the page."""
    for sel in ("a[title*='refresh' i]", "img[title*='refresh' i]",
                "[id*='refresh' i]", "a:has-text('Refresh')"):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=2000)
                await page.wait_for_timeout(800)
                return
        except Exception:
            continue
    try:
        await page.reload(wait_until="domcontentloaded", timeout=20_000)
    except Exception:
        pass


_UPLOAD_NAV_TEXTS = {
    # Menu texts tried in order after login to reach the upload page.
    "epfo": ["ECR/Return Filing", "ECR/RETURN FILING", "ECR Upload", "ECR UPLOAD", "Payments (ECR)"],
    "esic": ["Online Monthly Contribution", "File Monthly Contribution",
             "Upload Excel", "Monthly Contribution", "Bulk Upload"],
}

# HARD SAFETY RAIL (user directive): automation stops at challan
# finalisation — NEVER click anything that starts a bank payment.
_PAYMENT_BLOCKLIST = ("pay", "payment", "net banking", "netbanking", "sbi",
                      "bank", "debit", "online payment", "make payment")


async def _attempt_portal_upload(page, portal: str, file_name: str,
                                 file_bytes: bytes) -> Dict[str, Any]:
    """Best-effort: from a logged-in portal page, open the contribution
    upload screen and submit the generated file. Stops at challan
    finalisation — payment buttons are never clicked."""
    import mimetypes

    nav_clicked = None
    for txt in _UPLOAD_NAV_TEXTS.get(portal, []):
        try:
            loc = page.get_by_text(txt, exact=False).first
            if await loc.count() > 0:
                await loc.click(timeout=4000)
                await page.wait_for_timeout(2200)
                nav_clicked = txt
                break
        except Exception:
            continue

    async def _find_file_input():
        try:
            if await page.locator("input[type='file']").count() > 0:
                return page.locator("input[type='file']").first
        except Exception:
            pass
        for fr in page.frames:
            try:
                if await fr.locator("input[type='file']").count() > 0:
                    return fr.locator("input[type='file']").first
            except Exception:
                continue
        return None

    file_input = await _find_file_input()
    shot = base64.b64encode(await page.screenshot(full_page=False)).decode("ascii")
    if file_input is None:
        where = f"opened '{nav_clicked}' but " if nav_clicked else ""
        return {
            "uploaded": False,
            "screenshot_b64": shot,
            "message": (
                f"Logged in, {where}no file-chooser was found automatically — "
                "the portal layout may have changed. Download the generated "
                "file from the job and finish the upload manually."
            ),
        }

    mime = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    await file_input.set_input_files(
        {"name": file_name, "mimeType": mime, "buffer": file_bytes})
    await page.wait_for_timeout(1500)

    # Click an Upload/Submit style button — but NEVER anything payment-ish.
    clicked = None
    for txt in ("Upload", "UPLOAD", "Submit", "SUBMIT", "Save", "Validate"):
        try:
            btn = page.get_by_role("button", name=txt).first
            if await btn.count() == 0:
                btn = page.locator(f"input[type='submit'][value*='{txt}' i]").first
            if await btn.count() > 0:
                label = ((await btn.text_content()) or txt).strip().lower()
                if any(b in label for b in _PAYMENT_BLOCKLIST):
                    continue  # safety rail — do not start payment
                await btn.click(timeout=3500)
                await page.wait_for_timeout(3000)
                clicked = txt
                break
        except Exception:
            continue

    shot = base64.b64encode(await page.screenshot(full_page=False)).decode("ascii")
    return {
        "uploaded": True,
        "screenshot_b64": shot,
        "message": (
            f"File '{file_name}' selected on the {portal.upper()} portal"
            + (f" and '{clicked}' clicked." if clicked else " (no submit button found — verify on portal).")
            + " Automation STOPS at challan finalisation — review/approve the "
              "TRRN & challan on the portal; the bank payment step is left to you."
        ),
    }


# ---------------------------------------------------------------------------
# EPF UAN generation automation (user directive) — after login, open
# Member → Register Individual, fill the member form from the Employee
# Master snapshot, submit, and try to read the allotted UAN back.
# ---------------------------------------------------------------------------

_UAN_NAV_TEXTS = ["Register - Individual", "REGISTER - INDIVIDUAL",
                  "Register Individual", "Member Registration"]


def _iso_to_ddmmyyyy(v: Optional[str]) -> str:
    s = (v or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)          # ISO YYYY-MM-DD
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", s)          # DD-MM-YYYY
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return ""


async def _attempt_uan_registration(page, snap: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort EPFO 'Register Individual' member registration. Returns
    {registered: bool, uan: str|None, screenshot_b64, message}."""

    async def _shot() -> str:
        return base64.b64encode(await page.screenshot(full_page=False)).decode("ascii")

    # 1) Open Member menu, then Register Individual.
    try:
        mem = page.get_by_text("Member", exact=False).first
        if await mem.count() > 0:
            await mem.hover()
            await page.wait_for_timeout(700)
            try:
                await mem.click(timeout=3000)
            except Exception:
                pass
            await page.wait_for_timeout(1200)
    except Exception:
        pass
    opened = False
    for txt in _UAN_NAV_TEXTS:
        try:
            loc = page.get_by_text(txt, exact=False).first
            if await loc.count() > 0:
                await loc.click(timeout=4000)
                await page.wait_for_timeout(2500)
                opened = True
                break
        except Exception:
            continue
    if not opened:
        return {
            "registered": False, "uan": None, "screenshot_b64": await _shot(),
            "message": ("Logged in, but could not open Member → Register "
                        "Individual automatically — the portal layout may have "
                        "changed. Register the member manually (details are on "
                        "this job) and use Manual Complete."),
        }

    async def _fill_any(selectors, value) -> bool:
        if not value:
            return False
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.fill(str(value), timeout=2500)
                    return True
            except Exception:
                continue
        return False

    async def _select_any(selectors, label_options) -> bool:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    for lbl in label_options:
                        try:
                            await loc.select_option(label=lbl, timeout=1500)
                            return True
                        except Exception:
                            continue
            except Exception:
                continue
        return False

    # 2) Fill the member registration form.
    aadhaar_ok = await _fill_any(
        ["input[name*='aadhaar' i]", "input[id*='aadhaar' i]",
         "input[name*='documentNumber' i]", "input[id*='documentNo' i]"],
        (snap.get("aadhaar_no") or "").replace(" ", ""),
    )
    await _fill_any(
        ["input[name*='memberName' i]", "input[id*='memberName' i]",
         "input[name*='fullName' i]", "input[id*='name' i][id*='member' i]",
         "input[name='name']"],
        (snap.get("name") or "").upper(),
    )
    await _fill_any(
        ["input[name*='dob' i]", "input[id*='dob' i]",
         "input[name*='dateOfBirth' i]", "input[placeholder*='DD/MM' i]"],
        _iso_to_ddmmyyyy(snap.get("dob")),
    )
    g = (snap.get("gender") or "").strip().lower()
    if g:
        gender_lbls = {"male": ["MALE", "Male", "M"], "female": ["FEMALE", "Female", "F"],
                       "transgender": ["TRANSGENDER", "Transgender", "T"]}.get(g, [g.upper()])
        await _select_any(["select[name*='gender' i]", "select[id*='gender' i]"], gender_lbls)
    await _fill_any(
        ["input[name*='father' i]", "input[id*='father' i]",
         "input[name*='fatherHusband' i]", "input[id*='fh' i]"],
        (snap.get("father_name") or "").upper(),
    )
    ms = (snap.get("marital_status") or "").strip().lower()
    if ms:
        ms_lbls = {"single": ["UNMARRIED", "Unmarried", "Single"],
                   "married": ["MARRIED", "Married"],
                   "widowed": ["WIDOW/WIDOWER", "Widow/Widower", "Widowed"],
                   "divorced": ["DIVORCEE", "Divorcee", "Divorced"]}.get(ms, [ms.upper()])
        await _select_any(["select[name*='marital' i]", "select[id*='marital' i]"], ms_lbls)
    phone = "".join(ch for ch in str(snap.get("phone") or "") if ch.isdigit())[-10:]
    await _fill_any(["input[name*='mobile' i]", "input[id*='mobile' i]"], phone)
    await _fill_any(["input[name*='email' i]", "input[id*='email' i]"], snap.get("email"))
    await _fill_any(
        ["input[name*='doj' i]", "input[id*='doj' i]",
         "input[name*='dateOfJoining' i]", "input[id*='joining' i]"],
        _iso_to_ddmmyyyy(snap.get("doj")),
    )

    if not aadhaar_ok:
        return {
            "registered": False, "uan": None, "screenshot_b64": await _shot(),
            "message": ("Opened the registration page but the Aadhaar field "
                        "was not found — the portal layout may have changed. "
                        "Finish the registration manually and use Manual Complete."),
        }

    # 3) Submit (Save / Submit / Register — never payment-ish buttons).
    clicked = None
    for txt in ("Save", "SAVE", "Submit", "SUBMIT", "Register", "REGISTER"):
        try:
            btn = page.get_by_role("button", name=txt).first
            if await btn.count() == 0:
                btn = page.locator(f"input[type='submit'][value*='{txt}' i]").first
            if await btn.count() > 0:
                label = ((await btn.text_content()) or txt).strip().lower()
                if any(b in label for b in _PAYMENT_BLOCKLIST):
                    continue
                await btn.click(timeout=3500)
                await page.wait_for_timeout(3500)
                clicked = txt
                break
        except Exception:
            continue

    # 4) Try to read the allotted UAN off the page.
    uan = None
    try:
        body = await page.content()
        m = re.search(r"UAN[^0-9]{0,60}(\d{12})", body)
        if m:
            uan = m.group(1)
    except Exception:
        pass

    return {
        "registered": bool(clicked),
        "uan": uan,
        "screenshot_b64": await _shot(),
        "message": (
            (f"Member form filled and '{clicked}' clicked. " if clicked
             else "Member form filled but no Save/Submit button was found. ")
            + (f"Allotted UAN {uan} detected and saved to the Employee Master."
               if uan else
               "UAN not visible yet — approve the member on the portal, then "
               "enter the allotted UAN via Manual Complete.")
        ),
    }


async def _perform_login(portal: str, url: str, creds: Dict[str, str],
                         upload: Optional[Dict[str, Any]] = None,
                         uan_snap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Try to open the portal and login via Playwright, reading the text
    captcha automatically with the AI-vision reader. Returns a dict:
      { "ok": bool, "status": "logged_in" | "captcha_failed" |
        "playwright_missing" | "playwright_error", "screenshot_b64": ...,
        "message": str, "captcha_attempts": int }
    Wrapped in try/except so a missing playwright install falls through to
    ``manual_required`` cleanly."""
    from utils.captcha_reader import read_captcha

    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception:
        return {
            "ok": False,
            "status": "playwright_missing",
            "screenshot_b64": None,
            "message": (
                "playwright is not installed on this pod. Run "
                "`pip install playwright && python -m playwright install chromium` "
                "then set RPA_WORKER_ENABLED=1 in backend/.env."
            ),
        }

    async def _fill_credentials(page) -> None:
        for sel in ("input[name='username']", "input#username", "input[type='text']"):
            try:
                await page.fill(sel, creds["user_name"], timeout=3000)
                break
            except Exception:
                continue
        for sel in ("input[name='password']", "input#password", "input[type='password']"):
            try:
                await page.fill(sel, creds["password"], timeout=3000)
                break
            except Exception:
                continue

    MAX_ATTEMPTS = 3
    try:
        async with async_playwright() as pw:
            # Optional proxy so the RPA can egress from an allowed (Indian
            # ISP) network — government portals block cloud/datacenter IPs.
            # Set PORTAL_PROXY_URL in backend/.env, e.g.
            #   http://user:pass@host:port  or  http://host:port
            launch_kw: Dict[str, Any] = {"headless": True}
            proxy_url = (os.environ.get("PORTAL_PROXY_URL") or "").strip()
            if proxy_url:
                launch_kw["proxy"] = {"server": proxy_url}
            browser = await pw.chromium.launch(**launch_kw)
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            # Government portals frequently block cloud / datacenter IPs at
            # the WAF. Detect that up-front so we return a clear message
            # instead of a misleading "logged in".
            blocked = await _detect_block_or_error(page)
            if blocked:
                shot = base64.b64encode(await page.screenshot(full_page=False)).decode("ascii")
                await browser.close()
                return {
                    "ok": False,
                    "status": "portal_blocked",
                    "screenshot_b64": shot,
                    "captcha_attempts": 0,
                    "message": (
                        blocked + " — the portal is blocking this server's IP. "
                        "Auto-login must run from an allowed (Indian ISP) network."
                    ),
                }

            # Is there even a captcha on this login form?
            has_captcha = False
            for sel in ("img#captchaimg", "img[alt*='captcha' i]", "input[name*='captcha' i]"):
                try:
                    if await page.locator(sel).count() > 0:
                        has_captcha = True
                        break
                except Exception:
                    continue

            last_shot = None
            attempts = 0
            if not has_captcha:
                # No captcha — just fill + submit once.
                await _fill_credentials(page)
                await _click_login_submit(page)
                await page.wait_for_timeout(2500)
                last_shot = base64.b64encode(await page.screenshot(full_page=False)).decode("ascii")
                ok = await _login_succeeded(page)
                if ok and uan_snap:
                    reg = await _attempt_uan_registration(page, uan_snap)
                    await browser.close()
                    return {
                        "ok": reg["registered"],
                        "status": "uan_registered" if reg["registered"] else "uan_manual",
                        "uan": reg.get("uan"),
                        "screenshot_b64": reg.get("screenshot_b64") or last_shot,
                        "captcha_attempts": 0,
                        "message": "Logged in (no captcha). " + reg["message"],
                    }
                if ok and upload:
                    up = await _attempt_portal_upload(
                        page, portal, upload["file_name"], upload["file_bytes"])
                    await browser.close()
                    return {
                        "ok": up["uploaded"],
                        "status": "uploaded" if up["uploaded"] else "upload_manual",
                        "screenshot_b64": up.get("screenshot_b64") or last_shot,
                        "captcha_attempts": 0,
                        "message": "Logged in (no captcha). " + up["message"],
                    }
                await browser.close()
                return {
                    "ok": ok,
                    "status": "logged_in" if ok else "captcha_failed",
                    "screenshot_b64": last_shot,
                    "captcha_attempts": 0,
                    "message": (
                        "Logged in (no captcha on this portal form)."
                        if ok else
                        "Filled the login form but could not confirm a successful login."
                    ),
                }

            # Captcha present — read + submit, retrying on failure.
            for attempts in range(1, MAX_ATTEMPTS + 1):
                await _fill_credentials(page)
                cap_b64 = await _find_captcha_image_b64(page)
                if not cap_b64:
                    break
                numeric = portal == "esic"  # ESIC captchas are often numeric
                text = await read_captcha(
                    cap_b64, numeric_only=numeric, session_id=f"{portal}-{attempts}",
                )
                if not text:
                    await _reload_captcha(page)
                    continue
                await _fill_captcha_input(page, text)
                await _click_login_submit(page)
                await page.wait_for_timeout(2800)
                last_shot = base64.b64encode(await page.screenshot(full_page=False)).decode("ascii")
                if await _login_succeeded(page):
                    if uan_snap:
                        reg = await _attempt_uan_registration(page, uan_snap)
                        await browser.close()
                        return {
                            "ok": reg["registered"],
                            "status": "uan_registered" if reg["registered"] else "uan_manual",
                            "uan": reg.get("uan"),
                            "screenshot_b64": reg.get("screenshot_b64") or last_shot,
                            "captcha_attempts": attempts,
                            "message": (
                                f"Logged in (captcha attempt {attempts}). " + reg["message"]
                            ),
                        }
                    if upload:
                        up = await _attempt_portal_upload(
                            page, portal, upload["file_name"], upload["file_bytes"])
                        await browser.close()
                        return {
                            "ok": up["uploaded"],
                            "status": "uploaded" if up["uploaded"] else "upload_manual",
                            "screenshot_b64": up.get("screenshot_b64") or last_shot,
                            "captcha_attempts": attempts,
                            "message": (
                                f"Logged in (captcha attempt {attempts}). " + up["message"]
                            ),
                        }
                    await browser.close()
                    return {
                        "ok": True,
                        "status": "logged_in",
                        "screenshot_b64": last_shot,
                        "captcha_attempts": attempts,
                        "message": f"Logged in — captcha read automatically (attempt {attempts}).",
                    }
                # Failed — refresh the captcha and retry.
                await _reload_captcha(page)

            if last_shot is None:
                last_shot = base64.b64encode(await page.screenshot(full_page=False)).decode("ascii")
            await browser.close()
            return {
                "ok": False,
                "status": "captcha_failed",
                "screenshot_b64": last_shot,
                "captcha_attempts": attempts,
                "message": (
                    f"Could not log in after {attempts} captcha attempt(s). "
                    "The captcha may be unusually distorted, or the portal "
                    "layout changed. Please complete this login manually."
                ),
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "playwright_error",
            "screenshot_b64": None,
            "message": f"Playwright error: {exc}",
        }


async def _process_one_job(db, job: Dict[str, Any]) -> None:
    job_id = job["job_id"]
    portal = job.get("portal", "epfo")
    company_id = job.get("company_id")
    action = job.get("action_type", "generate_uan")

    await db.portal_automation_jobs.update_one(
        {"job_id": job_id, "status": "pending"},
        {"$set": {"status": "in_progress", "updated_at": _now_iso()}},
    )
    await _append_step(db, job_id, f"Worker picked up {action} for portal={portal}")

    creds = await _fetch_creds(db, company_id, portal)
    if not creds:
        await db.portal_automation_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "failed",
                      "error": "portal_credentials_missing",
                      "updated_at": _now_iso()}},
        )
        await _append_step(
            db, job_id,
            f"No {portal.upper()} credentials on firm_masters.portal_logins — abort.",
        )
        return

    # Challan-upload jobs carry the generated file to submit after login.
    upload_payload = None
    if action in ("upload_ecr", "upload_esic_mc"):
        try:
            upload_payload = {
                "file_name": job.get("file_name") or "upload.bin",
                "file_bytes": base64.b64decode(job.get("file_b64") or ""),
            }
        except Exception:
            upload_payload = None
        if not upload_payload or not upload_payload["file_bytes"]:
            await db.portal_automation_jobs.update_one(
                {"job_id": job_id},
                {"$set": {"status": "failed", "error": "upload_file_missing",
                          "updated_at": _now_iso()}},
            )
            await _append_step(db, job_id, "Generated upload file missing on the job — abort.")
            return

    result = await _perform_login(
        portal, creds["login_url"], creds, upload=upload_payload,
        uan_snap=(job.get("employee_snapshot") if action == "generate_uan" else None),
    )
    await _append_step(db, job_id, result["message"], result.get("screenshot_b64"))

    if result["status"] == "uan_registered":
        uan = result.get("uan")
        emp_id = job.get("employee_user_id")
        if uan and emp_id:
            await db.users.update_one(
                {"user_id": emp_id},
                {"$set": {"uan_no": uan, "uan_no_updated_at": _now_iso(),
                          "uan_no_source": "rpa_auto"}},
            )
            await db.portal_automation_jobs.update_one(
                {"job_id": job_id},
                {"$set": {"status": "completed",
                          "captcha_solved": True,
                          "captcha_attempts": result.get("captcha_attempts", 0),
                          "result": {"uan_no": uan},
                          "completed_at": _now_iso(),
                          "updated_at": _now_iso()}},
            )
            await _append_step(db, job_id,
                               f"UAN {uan} saved to the Employee Master automatically.")
        else:
            await db.portal_automation_jobs.update_one(
                {"job_id": job_id},
                {"$set": {"status": "manual_required",
                          "captcha_solved": True,
                          "captcha_attempts": result.get("captcha_attempts", 0),
                          "manual_reason": (
                              "Member registration was submitted on the EPFO "
                              "portal. Approve the member there, then enter the "
                              "allotted UAN via Manual Complete."),
                          "updated_at": _now_iso()}},
            )
    elif result["status"] == "uan_manual":
        await db.portal_automation_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "manual_required",
                      "captcha_solved": True,
                      "captcha_attempts": result.get("captcha_attempts", 0),
                      "manual_reason": result["message"],
                      "updated_at": _now_iso()}},
        )
    elif result["status"] == "uploaded":
        await db.portal_automation_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "completed",
                      "captcha_solved": True,
                      "captcha_attempts": result.get("captcha_attempts", 0),
                      "note": ("File submitted. Automation stops at challan "
                               "finalisation — verify TRRN/challan on the portal. "
                               "Bank payment is NOT automated."),
                      "updated_at": _now_iso()}},
        )
    elif result["status"] == "upload_manual":
        await db.portal_automation_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "manual_required",
                      "captcha_solved": True,
                      "captcha_attempts": result.get("captcha_attempts", 0),
                      "manual_reason": result["message"],
                      "updated_at": _now_iso()}},
        )
    elif result["status"] == "logged_in":
        # Login succeeded (captcha auto-read). Full UAN/ESIC generation
        # beyond login (member registration + Aadhaar KYC) still needs a
        # human, so mark for manual completion from the logged-in state.
        await db.portal_automation_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "manual_required",
                      "captcha_solved": True,
                      "captcha_attempts": result.get("captcha_attempts", 0),
                      "manual_reason": (
                          "Logged in automatically (captcha read by AI). "
                          "Complete the member registration / KYC steps on "
                          "the portal, then use Manual Complete to save the number."
                      ),
                      "updated_at": _now_iso()}},
        )
    elif result["status"] == "captcha_failed":
        await db.portal_automation_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "manual_required",
                      "captcha_solved": False,
                      "captcha_attempts": result.get("captcha_attempts", 0),
                      "manual_reason": (
                          "Could not read the captcha automatically after "
                          "several tries — please complete the login manually."
                      ),
                      "updated_at": _now_iso()}},
        )
    elif result["status"] == "portal_blocked":
        await db.portal_automation_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "manual_required",
                      "manual_reason": result["message"],
                      "updated_at": _now_iso()}},
        )
    else:
        # playwright_missing / playwright_error / anything else
        await db.portal_automation_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "manual_required",
                      "manual_reason": result["message"],
                      "updated_at": _now_iso()}},
        )


async def rpa_worker_loop(db) -> None:
    """Background task started from server.py at app startup. Runs
    forever, sleeping POLL_SEC seconds between polls."""
    logger.info("[rpa] worker starting — polling every %s sec", POLL_SEC)
    while True:
        try:
            job = await db.portal_automation_jobs.find_one(
                {"status": "pending",
                 "action_type": {"$in": ["generate_uan", "generate_esic",
                                          "upload_ecr", "upload_esic_mc"]}},
                sort=[("created_at", 1)],
            )
            if job:
                logger.info("[rpa] processing job=%s action=%s",
                            job.get("job_id"), job.get("action_type"))
                await _process_one_job(db, job)
            else:
                await asyncio.sleep(POLL_SEC)
        except asyncio.CancelledError:
            logger.info("[rpa] worker cancelled — shutting down")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("[rpa] iteration failed: %s", exc)
            await asyncio.sleep(POLL_SEC)


def maybe_start(app, db) -> None:
    """Wire the worker into the FastAPI app's startup event when
    ``RPA_WORKER_ENABLED=1``."""
    if not ENABLED:
        logger.info("[rpa] worker disabled (RPA_WORKER_ENABLED != 1)")
        return

    @app.on_event("startup")
    async def _start_rpa_worker() -> None:  # noqa: RUF029
        loop = asyncio.get_event_loop()
        loop.create_task(rpa_worker_loop(db))
        logger.info("[rpa] worker task scheduled")
