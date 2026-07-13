#!/usr/bin/env python3
"""S.K. Sharma & Co. — On-Premise EPFO / ESIC Auto-Login Runner.

WHY THIS EXISTS
    EPFO / ESIC government portals block cloud/datacenter IPs at their
    firewall. This little program runs on a PC at YOUR OFFICE (whose
    Indian ISP IP the portals allow), so it can actually reach the portal.

WHAT IT DOES
    1. Logs in to the S.K. Sharma & Co. app to get your data.
    2. Downloads the EPFO ECR (.txt) for the compliance run you pick.
    3. Opens the EPFO portal in a VISIBLE browser.
    4. Fills your portal username + password.
    5. Reads the captcha automatically (the image is sent to the app, which
       reads it with AI, and the answer is typed in for you).
    6. Clicks Login.
    7. Leaves the browser OPEN on the ECR-upload page with your file ready,
       so your team just reviews and clicks the final Upload / Pay steps.

    The final submit & payment are ALWAYS left to a human on purpose.

SETUP (one time, on the office PC)
    1. Install Python 3.10+  ->  https://www.python.org/downloads/
       (tick "Add Python to PATH" during install)
    2. Open Command Prompt / Terminal in this folder and run:
           pip install playwright requests
           python -m playwright install chromium
    3. Copy config.example.json to config.json and fill in your details.

RUN
    python epfo_agent.py

    Optional: pick a specific compliance run and portal:
    python epfo_agent.py --portal epfo --run-id csrun_xxxxx
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing 'requests'. Run:  pip install requests")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Missing 'playwright'. Run:  pip install playwright && python -m playwright install chromium")


HERE = Path(__file__).resolve().parent
PORTAL_URLS = {
    "epfo": "https://unifiedportal-emp.epfindia.gov.in/epfo/",
    "esic": "https://www.esic.in/EmployerPortal/",
}


def load_config() -> dict:
    cfg_path = HERE / "config.json"
    if not cfg_path.exists():
        sys.exit(
            "config.json not found. Copy config.example.json to config.json "
            "and fill in your details first."
        )
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class AppClient:
    """Talks to the S.K. Sharma & Co. backend API."""

    def __init__(self, base_url: str, email: str, password: str):
        self.base = base_url.rstrip("/")
        if not self.base.endswith("/api"):
            self.base += "/api"
        self.email = email
        self.password = password
        self.token = ""

    def login(self) -> None:
        r = requests.post(
            f"{self.base}/auth/admin-password-login",
            json={"email": self.email, "password": self.password},
            timeout=30,
        )
        r.raise_for_status()
        self.token = r.json()["session_token"]
        log("Logged in to the S.K. Sharma & Co. app.")

    @property
    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def list_runs(self, company_id: str | None) -> list[dict]:
        q = f"?company_id={company_id}" if company_id else ""
        r = requests.get(f"{self.base}/admin/compliance-salary-runs{q}",
                         headers=self._h, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("runs", data) if isinstance(data, dict) else data

    def download_ecr(self, run_id: str) -> Path:
        r = requests.get(f"{self.base}/admin/challans/ecr.txt?run_id={run_id}",
                         headers=self._h, timeout=60)
        r.raise_for_status()
        out = HERE / f"ECR_{run_id}.txt"
        out.write_bytes(r.content)
        log(f"Downloaded ECR file -> {out.name} ({len(r.content)} bytes)")
        return out

    def read_captcha(self, image_bytes: bytes, numeric_only: bool = False) -> str:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        r = requests.post(
            f"{self.base}/admin/portal-automation/read-captcha",
            headers=self._h,
            json={"image_base64": b64, "numeric_only": numeric_only},
            timeout=60,
        )
        if r.status_code != 200:
            return ""
        return r.json().get("text", "")


def pick_run(runs: list[dict], run_id: str | None) -> dict:
    if run_id:
        for run in runs:
            if run.get("run_id") == run_id:
                return run
        sys.exit(f"Run {run_id} not found.")
    if not runs:
        sys.exit("No compliance salary runs found in the app. Run one first.")
    print("\nAvailable compliance runs:")
    for i, run in enumerate(runs[:20], 1):
        print(f"  {i}. {run.get('month')} · {run.get('employee_type') or 'All'} "
              f"· {run.get('employees_count', 0)} emp · {run.get('run_id')}")
    choice = input("\nPick a run number: ").strip()
    try:
        return runs[int(choice) - 1]
    except (ValueError, IndexError):
        sys.exit("Invalid choice.")


def find_captcha_image(page):
    for sel in ("img#captchaimg", "img[alt*='captcha' i]", "img[src*='captcha' i]",
                "img[id*='captcha' i]", "#captcha img"):
        loc = page.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def fill_first(page, selectors, value) -> bool:
    for sel in selectors:
        try:
            page.fill(sel, value, timeout=2500)
            return True
        except Exception:
            continue
    return False


def run(portal: str, run_id: str | None) -> None:
    cfg = load_config()
    app = AppClient(cfg["app_base_url"], cfg["app_email"], cfg["app_password"])
    app.login()

    company_id = cfg.get("company_id") or None
    ecr_file = None
    if portal == "epfo":
        runs = app.list_runs(company_id)
        run_doc = pick_run(runs, run_id)
        ecr_file = app.download_ecr(run_doc["run_id"])

    portal_user = cfg["portal_username"]
    portal_pass = cfg["portal_password"]
    url = cfg.get("portal_url") or PORTAL_URLS[portal]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)  # visible for the human
        page = browser.new_page()
        log(f"Opening {portal.upper()} portal ...")
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        body = (page.inner_text("body") or "").lower()
        if "web page blocked" in body or "access denied" in body:
            log("!! Portal blocked THIS network too. This PC's IP is not allowed "
                "by the portal. Try from a machine on the office ISP connection.")
            input("Press Enter to close ...")
            browser.close()
            return

        fill_first(page, ["input[name='username']", "input#username", "input[type='text']"], portal_user)
        fill_first(page, ["input[name='password']", "input#password", "input[type='password']"], portal_pass)
        log("Filled username & password.")

        solved = False
        for attempt in range(1, 4):
            cap = find_captcha_image(page)
            if cap is None:
                log("No captcha field found — you may log in directly.")
                break
            img = cap.screenshot()
            text = app.read_captcha(img, numeric_only=(portal == "esic"))
            if not text:
                log(f"Captcha unreadable (attempt {attempt}) — refreshing ...")
                page.reload(wait_until="domcontentloaded")
                fill_first(page, ["input[name='username']", "input#username", "input[type='text']"], portal_user)
                fill_first(page, ["input[name='password']", "input#password", "input[type='password']"], portal_pass)
                continue
            fill_first(page, ["input[name='captcha' i]", "input#captcha",
                              "input[id*='captcha' i]", "input[placeholder*='captcha' i]"], text)
            log(f"Captcha read automatically: {text}  (attempt {attempt})")
            solved = True
            break

        if solved:
            for sel in ("button[type='submit']", "input[type='submit']",
                        "button:has-text('Sign In')", "button:has-text('Login')"):
                try:
                    if page.locator(sel).first.count() > 0:
                        page.locator(sel).first.click(timeout=3000)
                        log("Clicked Login.")
                        break
                except Exception:
                    continue
            page.wait_for_timeout(3000)

        print("\n" + "=" * 64)
        print(" The browser is now OPEN and logged in (if the captcha was correct).")
        if ecr_file:
            print(f" Your ECR file is ready at:\n   {ecr_file}")
            print(" Go to  Payments -> ECR Upload,  choose Wage Month + rate,")
            print(" attach the file above, then Verify / Upload / Generate Challan.")
        print(" The final Upload & Payment steps are left for you to review.")
        print("=" * 64 + "\n")
        input("Press Enter here when you are done, to close the browser ...")
        browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="On-prem EPFO/ESIC auto-login runner")
    ap.add_argument("--portal", choices=["epfo", "esic"], default="epfo")
    ap.add_argument("--run-id", default=None, help="Compliance run id (EPFO ECR)")
    args = ap.parse_args()
    try:
        run(args.portal, args.run_id)
    except requests.HTTPError as e:
        sys.exit(f"App API error: {e.response.status_code} {e.response.text[:200]}")
    except KeyboardInterrupt:
        print("\nCancelled.")
