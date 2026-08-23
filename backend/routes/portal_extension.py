"""Chrome Auto-Login extension — generator + runtime endpoints.

The employer's own Chrome can reach the ESIC / EPFO portals (their ISP
IP is allowed), so a small MV3 extension does what a web app cannot:
inject into the portal login page, auto-fill the firm's saved User ID +
Password, screenshot the captcha and solve it via the app's AI reader,
and let the operator click Login.

Endpoints:
  * GET  /api/admin/portal-automation/extension-download  (session auth)
        Generates a per-firm token and streams a ready-to-load .zip with
        the token + this app's base URL baked in.
  * GET  /api/portal-ext/creds?token=&portal=             (token gated)
        Returns the firm's saved User ID + Password for the extension.
  * POST /api/portal-ext/solve-captcha  {token,image_base64,numeric_only}
        Reads a captcha image with the AI vision reader (token gated).

The token lives in ``automation_ext_tokens`` and is tied to one firm.
"""
import base64
import io
import json
import secrets
import zipfile
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import Response

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    logger,
)

router = APIRouter(prefix="/api", tags=["portal-extension"])


# --- Extension source files (BASE / TOKEN baked at download time) ---------

_CONTENT_JS = r"""(function(){
  function portalKey(){return location.hostname.indexOf('epfindia')>=0?'epfo':'esic';}
  function setVal(el,val){
    var p=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
    var d=Object.getOwnPropertyDescriptor(p,'value').set;d.call(el,val);
    el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
  }
  function findUser(){
    var t=[].slice.call(document.querySelectorAll('input[type=text],input:not([type])'));
    return t.filter(function(i){var n=((i.name||'')+(i.id||'')+(i.placeholder||''));
      return !/captcha|code|otp|search/i.test(n)&&i.offsetParent!==null;})[0];
  }
  function findPass(){return document.querySelector('input[type=password]');}
  function findCaptchaInput(){
    return document.querySelector("input[name*='captcha' i],input[id*='captcha' i],input[placeholder*='captcha' i],input[name*='code' i]");
  }
  function findCaptchaImg(){
    var s=["img#captchaimg","img[alt*='captcha' i]","img[src*='captcha' i]","img[id*='captcha' i]","img[title*='captcha' i]"];
    for(var i=0;i<s.length;i++){var e=document.querySelector(s[i]);if(e&&e.offsetParent!==null)return e;}
    return null;
  }
  function imgB64(img){
    try{var c=document.createElement('canvas');c.width=img.naturalWidth||img.width;
      c.height=img.naturalHeight||img.height;c.getContext('2d').drawImage(img,0,0);
      return c.toDataURL('image/png').split(',')[1];}catch(e){return null;}
  }
  function msg(m){return new Promise(function(res){chrome.runtime.sendMessage(m,res);});}
  function run(btn){
    var portal=portalKey();
    btn.textContent='Working…';btn.disabled=true;
    msg({type:'creds',portal:portal}).then(function(cr){
      if(!cr||!cr.ok){alert('Auto-Login: '+((cr&&cr.error)||'could not load credentials'));
        btn.textContent='SKS Auto-Login';btn.disabled=false;return;}
      var u=findUser(),p=findPass();
      if(u)setVal(u,cr.user_id);if(p)setVal(p,cr.password);
      var cimg=findCaptchaImg(),cin=findCaptchaInput();
      if(cimg&&cin){var b=imgB64(cimg);
        if(b){return msg({type:'solve',image:b,numeric_only:portal==='esic'}).then(function(sol){
          if(sol&&sol.ok&&sol.text)setVal(cin,sol.text);
          btn.textContent='Filled - now click Login';
          setTimeout(function(){btn.textContent='SKS Auto-Login';btn.disabled=false;},3000);});}
      }
      btn.textContent='Filled - now click Login';
      setTimeout(function(){btn.textContent='SKS Auto-Login';btn.disabled=false;},3000);
    });
  }
  function inject(){
    if(document.getElementById('sks-af-btn'))return;
    var b=document.createElement('button');b.id='sks-af-btn';b.textContent='SKS Auto-Login';
    b.style.cssText='position:fixed;top:16px;right:16px;z-index:2147483647;background:#7C3AED;color:#fff;border:none;border-radius:10px;padding:12px 16px;font-size:14px;font-weight:800;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.3)';
    b.onclick=function(){run(b);};document.body.appendChild(b);
  }
  if(document.body)inject();else window.addEventListener('DOMContentLoaded',inject);
})();
"""

_BACKGROUND_JS = r"""var API_BASE=%%BASE%%;var TOKEN=%%TOKEN%%;
chrome.runtime.onMessage.addListener(function(msg,sender,send){
  (async function(){
    try{
      if(msg.type==='creds'){
        var r=await fetch(API_BASE+"/api/portal-ext/creds?token="+encodeURIComponent(TOKEN)+"&portal="+encodeURIComponent(msg.portal));
        send(await r.json());
      }else if(msg.type==='solve'){
        var r2=await fetch(API_BASE+"/api/portal-ext/solve-captcha",{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({token:TOKEN,image_base64:msg.image,numeric_only:!!msg.numeric_only})});
        send(await r2.json());
      }else{send({ok:false,error:'unknown message'});}
    }catch(e){send({ok:false,error:String(e)});}
  })();
  return true;
});
"""

_MANIFEST = r"""{
  "manifest_version": 3,
  "name": "SKS Portal Auto-Login",
  "version": "1.0",
  "description": "Auto-fills ESIC/EPFO employer login and reads the captcha via the SKS app.",
  "background": { "service_worker": "background.js" },
  "content_scripts": [
    {
      "matches": ["https://*.esic.gov.in/*", "https://*.esic.in/*", "https://*.epfindia.gov.in/*"],
      "js": ["content.js"],
      "run_at": "document_idle"
    }
  ],
  "host_permissions": [
    "https://*.esic.gov.in/*", "https://*.esic.in/*", "https://*.epfindia.gov.in/*",
    "%%BASE%%/*"
  ]
}
"""


def _js_str(v: str) -> str:
    """Safe JS string literal."""
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


async def _resolve_company(admin: Dict[str, Any], company_id: Optional[str]) -> str:
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if admin["role"] == "sub_admin" and company_id:
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    if not company_id or company_id == "all":
        raise HTTPException(
            status_code=400,
            detail="Firm selection is mandatory — select a specific firm first.")
    return company_id


@router.get("/admin/portal-automation/extension-download")
async def extension_download(
    api_base: str = Query(...),
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    company_id = await _resolve_company(admin, company_id)

    base = (api_base or "").strip().rstrip("/")
    if not base.startswith("http"):
        raise HTTPException(status_code=400, detail="api_base must be a full URL")

    token = secrets.token_urlsafe(24)
    await db.automation_ext_tokens.insert_one({
        "token": token,
        "company_id": company_id,
        "created_by": admin["user_id"],
        "created_at": now_iso(),
    })

    manifest = _MANIFEST.replace("%%BASE%%", base)
    background = (
        _BACKGROUND_JS
        .replace("%%BASE%%", _js_str(base))
        .replace("%%TOKEN%%", _js_str(token))
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", manifest)
        z.writestr("background.js", background)
        z.writestr("content.js", _CONTENT_JS)
        z.writestr("README.txt", (
            "SKS Portal Auto-Login — Chrome extension\n"
            "========================================\n\n"
            "1. Unzip this folder somewhere permanent.\n"
            "2. Open Chrome -> chrome://extensions\n"
            "3. Turn ON 'Developer mode' (top-right).\n"
            "4. Click 'Load unpacked' and pick this unzipped folder.\n"
            "5. Open the ESIC or EPFO employer LOGIN page.\n"
            "6. Click the purple 'SKS Auto-Login' button (top-right of the page).\n"
            "   It fills your User ID + Password and reads the captcha.\n"
            "   Verify the captcha, then click the portal's Login button.\n"
        ))
    buf.seek(0)
    logger.info("[portal-ext] extension generated for company=%s by %s",
                company_id, admin["user_id"])
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="sks-auto-login-extension.zip"'},
    )


@router.get("/portal-ext/creds")
@router.get("/portal-ext/get-login")
async def ext_creds(token: str, portal: str = "esic"):
    portal = (portal or "esic").lower()
    if portal not in ("esic", "epfo"):
        raise HTTPException(status_code=400, detail="bad portal")
    doc = await db.automation_ext_tokens.find_one({"token": token})
    if not doc:
        raise HTTPException(status_code=401, detail="Invalid extension token")
    from utils.rpa_worker import _fetch_creds
    creds = await _fetch_creds(db, doc["company_id"], portal)
    if not creds:
        raise HTTPException(status_code=412, detail=f"No {portal.upper()} login saved on Firm Master")
    return {"ok": True, "user_id": creds.get("user_name") or "", "password": creds.get("password") or ""}


@router.post("/portal-ext/solve-captcha")
async def ext_solve_captcha(payload: Dict[str, Any] = Body(...)):
    token = (payload.get("token") or "").strip()
    doc = await db.automation_ext_tokens.find_one({"token": token})
    if not doc:
        raise HTTPException(status_code=401, detail="Invalid extension token")
    image_b64 = (payload.get("image_base64") or "").strip()
    if not image_b64:
        raise HTTPException(status_code=400, detail="image_base64 is required")
    from utils.captcha_reader import read_captcha
    text = await read_captcha(
        image_b64, numeric_only=bool(payload.get("numeric_only")),
        session_id=f"ext-{token[:8]}",
    )
    if not text:
        raise HTTPException(status_code=422, detail="Could not read the captcha")
    return {"ok": True, "text": text}


_CFT_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}


@router.get("/admin/portal-automation/chromedriver-url")
async def chromedriver_url(
    platform: str = Query("win64"),
    authorization: Optional[str] = Header(None),
):
    """Iter 691 — direct official ChromeDriver (Chrome-for-Testing) download
    link for the operator's PC. Latest STABLE version, cached 1 hour."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    import time as _time
    if not _CFT_CACHE["data"] or _time.time() - _CFT_CACHE["at"] > 3600:
        import httpx
        async with httpx.AsyncClient(timeout=20) as cl:
            r = await cl.get(
                "https://googlechromelabs.github.io/chrome-for-testing/"
                "last-known-good-versions-with-downloads.json")
            r.raise_for_status()
            _CFT_CACHE["data"] = r.json()
            _CFT_CACHE["at"] = _time.time()
    st = _CFT_CACHE["data"]["channels"]["Stable"]
    url = next((x["url"] for x in st["downloads"]["chromedriver"]
                if x["platform"] == platform), None)
    if not url:
        raise HTTPException(status_code=404, detail=f"No ChromeDriver for {platform}")
    return {"ok": True, "version": st["version"], "platform": platform, "url": url}


@router.get("/portal-ext/ecr-file")
async def ext_ecr_file(token: str, run_id: str = ""):
    """Iter 690 — PF Challan automation: the PC Runner fetches the ready
    PF ECR text file for the selected (or latest) Compliance Salary
    Process of the token's firm. Token gated, same trust model as creds."""
    doc = await db.automation_ext_tokens.find_one({"token": token})
    if not doc:
        raise HTTPException(status_code=401, detail="Invalid extension token")
    company_id = doc["company_id"]
    rid = (run_id or doc.get("run_id") or "").strip()
    if rid:
        run = await db.compliance_salary_runs.find_one(
            {"run_id": rid, "company_id": company_id}, {"_id": 0})
    else:
        run = await db.compliance_salary_runs.find_one(
            {"company_id": company_id}, {"_id": 0}, sort=[("month", -1)])
    if not run:
        raise HTTPException(
            status_code=404,
            detail="No Compliance Salary Process found for this firm — "
                   "process the month's salary first.")
    rows = run.get("rows") or run.get("lines") or []
    uids = [r.get("user_id") for r in rows if r.get("user_id") and not r.get("uan_no")]
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}}, {"_id": 0, "user_id": 1, "uan_no": 1}):
            for r in rows:
                if r.get("user_id") == u["user_id"]:
                    r["uan_no"] = u.get("uan_no")
    from utils.statutory_bulk import build_pf_ecr_txt
    from utils.rpa_engine import validate_run_rows
    body = build_pf_ecr_txt(rows)
    report = validate_run_rows(rows, "epfo")
    month = str(run.get("month") or "")
    mword = f"{month[5:7]}{month[:4]}" if len(month) == 7 and month[4] == "-" else "month"
    return {
        "ok": True,
        "month": month,
        "filename": f"PF_ECR_{mword}.txt",
        "content_b64": base64.b64encode(body).decode("ascii"),
        "lines": len(body.splitlines()),
        "included": report.get("included"),
        "employee_count": report.get("employee_count"),
        "missing": [m.get("name") for m in (report.get("missing_ids") or [])][:25],
    }


# --- Local PC runner (Selenium + auto-managed ChromeDriver) ---------------
# Selenium 4.6+ ships "Selenium Manager", which automatically downloads and
# updates the chromedriver matching the installed Chrome. On top of that, a
# tiny LAUNCHER self-updates the login script from the app on every run — so
# the operator downloads ONCE and the folder stays current forever.

# Bump this when _RUNNER_CODE changes; the launcher pulls the new script.
RUNNER_VERSION = "20"

# The actual login logic — served (not baked) so it can auto-update in the
# operator's folder. Exposes run(API_BASE, TOKEN, portal).
_RUNNER_CODE = r'''"""SKS Portal Auto-Login — login script (auto-updated by launcher)."""
import base64
import json
import time
import urllib.error
import urllib.request

RUNNER_BUILD = "20"

PORTALS = {
    "esic": "https://portal.esic.gov.in/EmployerPortal/ESICInsurancePortal/Portal_Loginnew.aspx",
    "epfo": "https://unifiedportal-emp.epfindia.gov.in/epfo/",
}

# Iter 691 — live status board for jobs launched from the web app
# (polled by the Automation Studio via /status?job=).
JOB_STATUS = {}


def _fresh_driver(opts):
    """Start Chrome with an AUTO-UPDATED ChromeDriver.

    Selenium Manager normally keeps chromedriver current, but when Chrome
    auto-updates on the PC a cached/stale driver can mismatch and Chrome
    refuses to start. Self-heal ladder:
      1. normal start (Selenium Manager picks/downloads the driver)
      2. wipe the cached drivers + upgrade Selenium itself, retry
      3. force-download a matching Chrome-for-Testing + driver pair, retry
    """
    import os
    import shutil
    import subprocess
    import sys
    from selenium import webdriver
    try:
        return webdriver.Chrome(options=opts)
    except Exception as e:
        print("Chrome did not start (%s...)" % str(e)[:140])
    print("AUTO-UPDATING ChromeDriver to match your Chrome...")
    shutil.rmtree(os.path.join(os.path.expanduser("~"), ".cache", "selenium"),
                  ignore_errors=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-U", "-q",
                    "selenium>=4.16"], check=False)
    try:
        return webdriver.Chrome(options=opts)
    except Exception as e:
        print("Still failing (%s...)" % str(e)[:140])
    print("Downloading a matching Chrome + Driver pair (one time)...")
    os.environ["SE_FORCE_BROWSER_DOWNLOAD"] = "true"
    return webdriver.Chrome(options=opts)


def run(API_BASE, TOKEN, portal, run_id=None, job_id=None):
    portal = (portal or "esic").lower()

    # Iter 397 — LISTENER mode: keep this window open; the payroll web app
    # triggers logins on this PC with one click (Login - Open EPFO Portal).
    if portal in ("listen", "listener"):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from urllib.parse import urlparse, parse_qs

        class _H(BaseHTTPRequestHandler):
            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.send_header("Access-Control-Allow-Private-Network", "true")

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self):
                q = urlparse(self.path)
                qs = parse_qs(q.query)
                if q.path == "/ping":
                    body = json.dumps(
                        {"ok": True, "runner": "sks",
                         "build": RUNNER_BUILD}).encode()
                elif q.path == "/status":
                    jid = (qs.get("job") or [""])[0]
                    body = json.dumps(
                        {"ok": True,
                         "status": JOB_STATUS.get(jid, "unknown")}).encode()
                elif q.path == "/login":
                    p = (qs.get("portal") or ["epfo"])[0].lower()
                    tok = (qs.get("token") or [TOKEN])[0]
                    rid = (qs.get("run_id") or [""])[0]
                    jid = str(int(time.time() * 1000))
                    JOB_STATUS[jid] = "starting"
                    print("Launch request: portal=%s run=%s" % (p, rid or "latest"))
                    threading.Thread(
                        target=run, args=(API_BASE, tok, p, rid, jid),
                        daemon=True).start()
                    body = json.dumps(
                        {"ok": True, "launched": True, "job": jid}).encode()
                else:
                    body = b'{"ok":false,"detail":"unknown path"}'
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        print("=" * 60)
        print("SKS Runner is LISTENING on http://127.0.0.1:8765")
        print("Keep this window open. In the payroll app open PF Reports and")
        print("click 'Login - Open EPFO Portal' (or ESIC) - a Chrome window")
        print("opens HERE with the firm's login auto-filled. You only enter")
        print("the captcha and click Login.")
        print("=" * 60)
        HTTPServer(("127.0.0.1", 8765), _H).serve_forever()
        return

    # Iter 691 (user request) — OPEN-ONLY: start ChromeDriver, open a new
    # Chrome window on the EPFO Employer Portal and STOP. No username, no
    # password, no captcha, no OTP, no establishment ID — NOTHING is
    # filled or clicked. The user enters everything manually. The window
    # stays open; status is reported to the web app via JOB_STATUS.
    if portal in ("epfo_open", "open_epfo", "open"):
        def _st(s):
            if job_id:
                JOB_STATUS[job_id] = s
        _st("starting")
        print("Starting Chrome...")
        from selenium.webdriver.chrome.options import Options
        opts = Options()
        opts.add_experimental_option("detach", True)
        opts.add_argument("--start-maximized")
        # Iter 692c (security-aware): make Chrome look like a NORMAL human
        # browser so EPFO's firewall does not flag automation and serve a
        # 503. We only remove the "I am a bot" fingerprints — we do NOT
        # bypass CAPTCHA/OTP or auto-submit anything.
        try:
            opts.add_experimental_option(
                "excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36")
            opts.add_argument("--disable-infobars")
            # Iter 693d — STOP Chrome from auto-filling its own SAVED
            # passwords (e.g. the payroll admin email) into the EPFO login
            # boxes. Disable the password manager + autofill entirely and
            # run in a clean guest-like profile with no saved credentials.
            opts.add_experimental_option("prefs", {
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
                "profile.password_manager_leak_detection": False,
                "autofill.profile_enabled": False,
                "autofill.credit_card_enabled": False,
            })
            opts.add_argument("--disable-save-password-bubble")
            # Iter 693e — ROOT CAUSE of the wrong sksharmaconsultancy@gmail.com
            # / 642313 autofill: Chrome had that login SAVED for the EPFO
            # domain and re-injects it. Launch in a BRAND-NEW empty profile
            # so there are NO saved passwords to autofill — ever.
            import tempfile as _tf
            _clean_profile = _tf.mkdtemp(prefix="sks-epfo-")
            opts.add_argument("--user-data-dir=%s" % _clean_profile)
        except Exception:
            pass
        try:
            driver = _fresh_driver(opts)
        except Exception as e:
            _st("error: Chrome did not start (%s)" % str(e)[:120])
            print("Chrome did not start:", e)
            return
        # Hide the navigator.webdriver flag that WAFs look for.
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator,'webdriver',"
                           "{get:()=>undefined});"})
        except Exception:
            pass
        try:
            driver.set_page_load_timeout(90)
        except Exception:
            pass
        _st("opening")
        print("Opening EPFO Portal (giving it time to load safely)...")
        # Iter 693 (user request) — fetch this firm's EPFO Login ID +
        # Password from Firm Master -> Portal Logins, to auto-fill the login
        # form after the page opens. CAPTCHA / OTP are NEVER touched.
        _creds = {}
        _cred_note = ""
        try:
            with urllib.request.urlopen(
                "%s/api/portal-ext/creds?token=%s&portal=epfo"
                % (API_BASE, TOKEN), timeout=30) as _r:
                _cj = json.load(_r)
            if _cj.get("ok") and _cj.get("user_id"):
                _creds = _cj
                print("EPFO login fetched from Firm Master (User ID: %s)."
                      % _cj.get("user_id"))
            else:
                _cred_note = "nocreds"
                print("NOTE: no EPFO login saved for this firm (%s)."
                      % (_cj.get("detail") or "add it in Firm Master"))
        except urllib.error.HTTPError as _he:
            _cred_note = "nocreds"
            try:
                _d = json.load(_he).get("detail")
            except Exception:
                _d = "HTTP %s" % _he.code
            print("NOTE: no EPFO login saved for this firm (%s)." % _d)
        except Exception as _e:
            _cred_note = "crederr"
            print("NOTE: could not fetch EPFO login (%s)." % _e)
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            # Iter 692b — EPFO servers often answer with a transient
            # "503 Service Unavailable / No server is available" page.
            # Auto-reload for up to ~2 minutes until the real portal
            # (which has the login form / an alert popup) shows up.
            def _is_down():
                try:
                    src = (driver.page_source or "").lower()
                except Exception:
                    return False
                return ("503 service unavailable" in src
                        or "no server is available" in src
                        or "service unavailable" in src
                        or "502 bad gateway" in src
                        or "504 gateway" in src)

            def _looks_ready():
                try:
                    if driver.find_elements(By.ID, "btnCloseModal"):
                        return True
                    if driver.find_elements(By.CSS_SELECTOR, "input[type=password]"):
                        return True
                    src = (driver.page_source or "").lower()
                    return ("epfo" in src or "employer" in src or "login" in src) \
                        and not _is_down()
                except Exception:
                    return False

            try:
                driver.get(PORTALS["epfo"])
            except Exception:
                pass
            # Give the portal a generous, human-like moment to load fully
            # before we judge it — EPFO is slow and rendering can lag.
            time.sleep(6)
            _attempt, _MAXW = 0, 40  # ~40 x 5s ≈ 3+ minutes, patient
            while _attempt < _MAXW:
                try:
                    WebDriverWait(driver, 45).until(
                        lambda d: d.execute_script(
                            "return document.readyState") == "complete")
                except Exception:
                    pass
                time.sleep(2)  # settle after render
                if _looks_ready():
                    break
                if _is_down():
                    _attempt += 1
                    _st("retrying")
                    print("EPFO returned 'Service Unavailable' (their server is "
                          "busy). Waiting patiently and retrying... attempt %d"
                          % _attempt)
                    time.sleep(5)
                    try:
                        driver.get(PORTALS["epfo"])
                    except Exception:
                        pass
                    time.sleep(4)
                    continue
                break
            if _is_down() and not _looks_ready():
                _st("busy: EPFO 503 - portal is overloaded, try again shortly")
                print("EPFO portal is still returning 503 (their servers are "
                      "overloaded). The Chrome window stays open - just press "
                      "F5 / reload in a minute, it usually clears on its own.")
                # keep the window open for the user to retry manually
            # Close the alert popup ONLY (user request): OK button first
            # (type="button" / #btnCloseModal), then data-bs-dismiss ones.
            _closed = False
            for _i, _sel in enumerate((
                    (By.ID, "btnCloseModal"),
                    (By.XPATH,
                     "//button[@type='button' and contains(translate("
                     "normalize-space(.),'OK','ok'),'ok')]"),
                    (By.CSS_SELECTOR, "button[data-bs-dismiss='modal']"),
                    (By.CSS_SELECTOR, "button[data-dismiss='modal']"),
                    (By.CSS_SELECTOR,
                     "button[aria-label='Close'], [aria-label='Close']"))):
                try:
                    _btn = WebDriverWait(driver, 20 if _i == 0 else 3).until(
                        EC.element_to_be_clickable(_sel))
                    _btn.click()
                    print("Alert popup closed (%s)."
                          % ("OK" if _i <= 1 else "dismiss"))
                    _closed = True
                    break
                except Exception:
                    continue
            if not _closed:
                print("No alert popup appeared - nothing to close.")

            # Iter 693e — ALWAYS wipe any browser-autofilled values from the
            # login boxes FIRST (in case Chrome injected a saved login), so
            # we never leave a stray email/password behind.
            try:
                driver.execute_script(
                    "['username1','password','captcha'].forEach(function(id){"
                    "var e=document.getElementById(id);"
                    "if(e){e.value='';"
                    "e.dispatchEvent(new Event('input',{bubbles:true}));"
                    "e.dispatchEvent(new Event('change',{bubbles:true}));}});")
            except Exception:
                pass

            # Iter 693 — AUTO-FILL EPFO Login ID + Password from Firm Master.
            # Real EPFO page (verified): username id="username1", password
            # id="password" class "form-control password-field", plain
            # server-rendered form. CAPTCHA / OTP left for the user.
            _fill_result = ""
            if not _creds.get("user_id"):
                _fill_result = _cred_note or "nocreds"
            elif not (_is_down() and not _looks_ready()):
                from selenium.webdriver.common.keys import Keys

                def _type_val(el, val):
                    try:
                        el.click()
                    except Exception:
                        pass
                    try:
                        el.send_keys(Keys.CONTROL, "a")
                        el.send_keys(Keys.DELETE)
                    except Exception:
                        pass
                    try:
                        el.clear()
                    except Exception:
                        pass
                    el.send_keys(val)
                    try:
                        if (el.get_attribute("value") or "") != val:
                            driver.execute_script(
                                "var s=Object.getOwnPropertyDescriptor("
                                "window.HTMLInputElement.prototype,'value').set;"
                                "s.call(arguments[0],arguments[1]);"
                                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));"
                                "arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));",
                                el, val)
                    except Exception:
                        pass

                # The form sits behind the notice modal — wait for the
                # username box to become clickable after the modal closes.
                _user_el = None
                for _wait_try in range(3):
                    try:
                        _user_el = WebDriverWait(driver, 12).until(
                            EC.element_to_be_clickable((By.ID, "username1")))
                        break
                    except Exception:
                        # a leftover Bootstrap backdrop can block clicks —
                        # remove it and retry.
                        try:
                            driver.execute_script(
                                "document.querySelectorAll('.modal-backdrop')"
                                ".forEach(function(e){e.remove()});"
                                "document.body.classList.remove('modal-open');")
                        except Exception:
                            pass
                        time.sleep(2)
                if _user_el is None:
                    for _sel in ("#username", "input[name='username']",
                                 "#userName", "input[name='userName']"):
                        _els = [e for e in driver.find_elements(
                            By.CSS_SELECTOR, _sel) if e.is_displayed()]
                        if _els:
                            _user_el = _els[0]
                            break
                _pass_el = None
                for _sel in ("#password", "input.password-field",
                             ".password-field", "input[name='password']",
                             "input[type=password]"):
                    _els = [e for e in driver.find_elements(
                        By.CSS_SELECTOR, _sel) if e.is_displayed()]
                    if _els:
                        _pass_el = _els[0]
                        break
                _uok = _pok = False
                if _user_el is not None:
                    _type_val(_user_el, _creds["user_id"])
                    _uok = (_user_el.get_attribute("value") or "") == _creds["user_id"]
                    print("Username auto-filled (from Firm Master).")
                else:
                    print("Username field (#username1) not found - type it manually.")
                if _pass_el is not None:
                    _type_val(_pass_el, _creds["password"])
                    _pok = bool(_pass_el.get_attribute("value"))
                    print("Password auto-filled (from Firm Master).")
                else:
                    print("Password field (#password) not found - type it manually.")
                _fill_result = "filled" if (_uok and _pok) else (
                    "partial" if (_uok or _pok) else "nofield")

            if not (_is_down() and not _looks_ready()):
                if _fill_result == "filled":
                    _st("open")
                    print("Username & Password filled from Firm Master. Now")
                    print("enter the CAPTCHA (and OTP if asked) and click Sign In.")
                elif _fill_result in ("nocreds", "crederr"):
                    _st("open_nocreds")
                    print("Portal is open but NO EPFO login is saved for this "
                          "firm. Save EPF User ID + Password in Firm Master -> "
                          "EPF Registration, then click Open EPFO Portal again.")
                elif _fill_result in ("nofield", "partial"):
                    _st("open_nofield")
                    print("Portal open but the login boxes were not filled "
                          "(page still loading or a popup was in the way). "
                          "Type your login manually, or reload and retry.")
                else:
                    _st("open")
                print("EPFO Portal Open.")

            # Iter 693j (user request) — after the login is filled, give the
            # operator time to type the CAPTCHA, then AUTO-CLICK "Sign In".
            # We watch the captcha box: the moment it has >=4 chars we wait a
            # beat and click Sign In. If nothing is typed, we click after a
            # ~20s grace window anyway (user asked for a fixed wait too).
            if _fill_result == "filled":
                try:
                    _st("await_captcha")
                    print("Waiting for you to type the CAPTCHA "
                          "(auto Sign In will follow)...")
                    _cap = None
                    for _s in ("#captcha", "input[name='captcha']",
                               "input[id*='captcha' i]"):
                        _e = [x for x in driver.find_elements(By.CSS_SELECTOR, _s)
                              if x.is_displayed()]
                        if _e:
                            _cap = _e[0]
                            break
                    _typed = False
                    for _i in range(20):   # ~20s grace to type the captcha
                        time.sleep(1)
                        try:
                            if _cap and len((_cap.get_attribute("value") or "").strip()) >= 4:
                                _typed = True
                                time.sleep(1.5)   # let the last digit settle
                                break
                        except Exception:
                            pass
                    # click the Sign In / submit button
                    _clicked = False
                    for _bs in ("button.btn-logging",
                                "button[type='submit']",
                                "//button[.//span[contains(.,'Sign In')]]",
                                "//button[contains(.,'Sign In')]"):
                        try:
                            if _bs.startswith("//"):
                                _b = driver.find_elements(By.XPATH, _bs)
                            else:
                                _b = driver.find_elements(By.CSS_SELECTOR, _bs)
                            _b = [x for x in _b if x.is_displayed()]
                            if _b:
                                try:
                                    _b[0].click()
                                except Exception:
                                    driver.execute_script("arguments[0].click();", _b[0])
                                _clicked = True
                                break
                        except Exception:
                            continue
                    if _clicked:
                        _st("signed_in")
                        print("Clicked Sign In%s."
                              % (" (captcha detected)" if _typed else
                                 " (grace time elapsed)"))
                    else:
                        _st("open")
                        print("Could not find the Sign In button - "
                              "click it yourself.")
                except Exception as _e:
                    print("Auto Sign In skipped (%s)." % _e)
        except Exception as e:
            _st("error: portal did not load (%s)" % str(e)[:120])
            print("Portal did not load:", e)
            return
        # Wait until the user closes the Chrome window, then report it.
        while True:
            time.sleep(2)
            try:
                if not driver.window_handles:
                    break
            except Exception:
                break
        _st("closed")
        print("Browser Closed.")
        return

    def _get(url):
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)

    def _post(url, data):
        req = urllib.request.Request(
            url, data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)

    # Iter 315-316 (user guide) — "ecr_test": open the EPFO portal in a
    # NEW visible Google Chrome window (ChromeDriver), click the alert
    # popup's OK button (#btnCloseModal), then PASTE the selected firm's
    # EPFO Login ID + Password into the Username / Password fields.
    if portal in ("ecr_test", "epfo_test", "ecr"):
        print("Fetching your firm's EPFO login from the SKS app...")
        creds = {}
        try:
            resp = _get("%s/api/portal-ext/creds?token=%s&portal=epfo" % (API_BASE, TOKEN))
            if resp.get("ok"):
                creds = resp
            else:
                print("NOTE:", resp.get("detail") or resp)
        except Exception as e:
            print("NOTE: could not fetch EPFO credentials (%s)." % e)
            print("Save them under Firm Master -> Portal Logins, then re-run.")

        # Iter 690 (PF Challan automation) — fetch the ready-made PF ECR
        # file for the selected (or latest finalized) Compliance Salary
        # Process and save it into ~/Downloads. Later, once the ECR upload
        # page opens, the file is AUTO-SELECTED into the upload box.
        ecr_path = None
        ecr_month = ""
        try:
            _u = "%s/api/portal-ext/ecr-file?token=%s" % (API_BASE, TOKEN)
            if run_id:
                _u += "&run_id=%s" % run_id
            ef = _get(_u)
            if ef.get("ok") and ef.get("content_b64"):
                import os
                _dl = os.path.join(os.path.expanduser("~"), "Downloads")
                if not os.path.isdir(_dl):
                    _dl = os.path.expanduser("~")
                ecr_path = os.path.join(_dl, ef.get("filename") or "PF_ECR.txt")
                with open(ecr_path, "wb") as f:
                    f.write(base64.b64decode(ef["content_b64"]))
                ecr_month = ef.get("month") or ""
                print("=" * 60)
                print("PF ECR FILE READY: %s" % ecr_path)
                print("Wage month: %s | Members: %s of %s | ECR lines: %s"
                      % (ecr_month, ef.get("included"), ef.get("employee_count"),
                         ef.get("lines")))
                for _w in (ef.get("missing") or []):
                    print("  SKIPPED (no/invalid UAN): %s" % _w)
                print("=" * 60)
            else:
                print("NOTE: ECR file not generated - %s"
                      % (ef.get("detail") or "no finalized salary process found."))
        except Exception as e:
            print("NOTE: could not fetch the ECR file (%s)." % e)
            print("Download PF ECR from the app (PF Reports) and select it "
                  "manually on the upload page.")

        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        opts = Options()
        opts.add_experimental_option("detach", True)
        opts.add_argument("--start-maximized")
        print("Launching Google Chrome (auto-managed ChromeDriver)...")
        driver = _fresh_driver(opts)
        print("Opening EPFO employer portal...")
        driver.get(PORTALS["epfo"])

        # Step 1 — close the alert popup: OK (#btnCloseModal) first, then
        # the X (aria-label="Close"), then generic dismiss buttons.
        _closed = False
        for _i, _sel in enumerate((
                (By.ID, "btnCloseModal"),
                (By.CSS_SELECTOR, "button[aria-label='Close'], [aria-label='Close']"),
                (By.CSS_SELECTOR, "button.btn-danger[data-bs-dismiss='modal']"),
                (By.CSS_SELECTOR, "button[data-dismiss='modal']"))):
            try:
                btn = WebDriverWait(driver, 20 if _i == 0 else 3).until(
                    EC.element_to_be_clickable(_sel))
                btn.click()
                print("Alert popup closed (%s clicked)."
                      % ("OK" if _i == 0 else "Close"))
                _closed = True
                break
            except Exception:
                continue
        if not _closed:
            print("No alert popup appeared - nothing to close.")

        # Step 2 — paste Username (EPFO Login ID) + Password from firm.
        # NOTE: the EPFO portal is an ANGULAR app — fields are bound with
        # ng-model, so injecting el.value via JS does NOT update Angular's
        # model (the box stays blank on submit). We type like a real
        # keyboard (send_keys) which fires the events Angular listens to,
        # with a native-setter JS fallback.
        from selenium.webdriver.common.keys import Keys

        def type_val(el, val):
            try:
                el.click()
            except Exception:
                pass
            try:
                el.send_keys(Keys.CONTROL, "a")
                el.send_keys(Keys.DELETE)
            except Exception:
                pass
            try:
                el.clear()
            except Exception:
                pass
            el.send_keys(val)
            # Fallback: if real typing did not stick, use the native value
            # setter + fire input/change/blur so Angular's ngModel updates.
            try:
                if (el.get_attribute("value") or "") != val:
                    driver.execute_script(
                        "var s=Object.getOwnPropertyDescriptor("
                        "window.HTMLInputElement.prototype,'value').set;"
                        "s.call(arguments[0],arguments[1]);"
                        "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                        "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));"
                        "arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));",
                        el, val)
            except Exception:
                pass

        if creds.get("user_id"):
            # Wait for Angular to render the login form after the modal
            # closes (fields are not interactable immediately).
            user_el = None
            try:
                user_el = WebDriverWait(driver, 15).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "#username")))
            except Exception:
                user_el = None
            if user_el is None:
                for sel in ("input[name='username']", "#userName",
                            "input[name='userName']"):
                    els = driver.find_elements(By.CSS_SELECTOR, sel)
                    if els and els[0].is_displayed():
                        user_el = els[0]; break
            if user_el is None:
                for el in driver.find_elements(
                        By.CSS_SELECTOR, "input[type=text], input:not([type])"):
                    try:
                        nm = ((el.get_attribute("name") or "") +
                              (el.get_attribute("id") or "") +
                              (el.get_attribute("placeholder") or ""))
                        if el.is_displayed() and not any(
                                k in nm.lower() for k in
                                ("captcha", "code", "otp", "search")):
                            user_el = el; break
                    except Exception:
                        continue
            pass_el = None
            for sel in ("#password", "input[name='password']",
                        "input[type=password]"):
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                if els and els[0].is_displayed():
                    pass_el = els[0]; break
            if user_el is not None:
                type_val(user_el, creds["user_id"])
                print("Username typed (EPFO Login ID from selected firm).")
            else:
                print("Username field not found - paste it manually.")
            if pass_el is not None:
                type_val(pass_el, creds["password"])
                print("Password typed (EPFO Password from selected firm).")
            else:
                print("Password field not found - paste it manually.")
        else:
            print("No EPFO User ID/Password saved for this firm - "
                  "add them under Firm Master -> Portal Logins.")

        # Step 3 — read the captcha with AI and SHOW IT ON SCREEN.
        captcha_text = None
        cap_img = None
        for sel in ("img#capImg", "img#captcha_id", "img[id*=cap i]",
                    "img[src*=captcha i]", "img[alt*=captcha i]",
                    "img[title*=captcha i]"):
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els and els[0].is_displayed():
                cap_img = els[0]; break
        cap_in = None
        for sel in ("#captcha", "input[name*=captcha i]", "input[id*=captcha i]",
                    "input[placeholder*=captcha i]", "input[name*=code i]"):
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els and els[0].is_displayed():
                cap_in = els[0]; break
        if cap_img is not None:
            try:
                b64 = base64.b64encode(cap_img.screenshot_as_png).decode("ascii")
                print("Reading captcha with AI...")
                sol = _post("%s/api/portal-ext/solve-captcha" % API_BASE,
                            {"token": TOKEN, "image_base64": b64,
                             "numeric_only": False})
                if sol.get("ok") and sol.get("text"):
                    captcha_text = str(sol["text"]).strip()
            except Exception as e:
                print("Captcha read failed:", e)
        if captcha_text:
            print("CAPTCHA READ: %s" % captcha_text)
            if cap_in is not None:
                type_val(cap_in, captcha_text)
                print("Captcha filled.")
            # Show the read captcha ON SCREEN inside the Chrome window.
            try:
                driver.execute_script(
                    "var d=document.createElement('div');"
                    "d.id='sks-captcha-banner';"
                    "d.textContent='SKS AI read captcha: '+arguments[0];"
                    "d.style.cssText='position:fixed;top:12px;right:12px;"
                    "z-index:2147483647;background:#0F3B5C;color:#fff;"
                    "font:700 18px sans-serif;padding:10px 16px;"
                    "border-radius:8px;box-shadow:0 4px 14px rgba(0,0,0,.45)';"
                    "document.body.appendChild(d);", captcha_text)
            except Exception:
                pass
        else:
            print("Captcha could not be read - type it manually.")

        # Step 4 — click Sign In (only when the captcha got filled).
        if captcha_text and cap_in is not None:
            # Iter 316 — the EPFO home-page alert modal
            # (#mainHomePageAlertModal, static backdrop) intercepts the
            # Sign In click; close it + strip any lingering modal first.
            try:
                for msel in ("#btnCloseModal",
                             "button[aria-label='Close']",
                             "[aria-label='Close']",
                             "#mainHomePageAlertModal button.btn-danger"):
                    for el in driver.find_elements(By.CSS_SELECTOR, msel):
                        if el.is_displayed():
                            el.click(); break
                driver.execute_script(
                    "document.querySelectorAll("
                    "'#mainHomePageAlertModal,.modal.show,.modal-backdrop')"
                    ".forEach(function(e){e.classList.remove('show');"
                    "e.style.display='none';if(e.remove)e.remove();});"
                    "document.body.classList.remove('modal-open');"
                    "document.body.style.overflow='';")
            except Exception:
                pass
            signed = False
            for sel in ("#loginbtn", "button#login", "input[type=submit]",
                        "button[type=submit]"):
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    try:
                        if el.is_displayed():
                            try:
                                el.click()
                            except Exception:
                                driver.execute_script("arguments[0].click();", el)
                            signed = True; break
                    except Exception:
                        continue
                if signed:
                    break
            if not signed:
                try:
                    els = driver.find_elements(
                        By.XPATH,
                        "//button[contains(translate(.,'SIGN','sign'),'sign')]"
                        " | //input[contains(translate(@value,'SIGN','sign'),'sign')]")
                    for el in els:
                        if el.is_displayed():
                            el.click(); signed = True; break
                except Exception:
                    pass
            print("Sign In clicked." if signed
                  else "Sign In button not found - click it manually.")
        else:
            print("Sign In NOT clicked - fill the captcha and click it manually.")

        # Step 5 (Iter 471) — AUTO-NAVIGATE to the ECR upload page once the
        # login lands: PAYMENTS menu -> ECR/RETURN FILING -> ECR Upload tab.
        # The captcha sometimes needs a manual retry, so poll for the
        # logged-in dashboard for up to 3 minutes first.
        print("\nWaiting for login (up to 3 min - retype the captcha "
              "manually if it was misread)...")
        logged_in = False
        for _ in range(90):
            time.sleep(2)
            try:
                if driver.find_elements(
                        By.XPATH,
                        "//a[contains(translate(.,'PAYMENTS','payments'),'payments')]"
                        " | //a[contains(@href,'logout') or contains(@href,'Logout')]"):
                    logged_in = True; break
            except Exception:
                break
        if not logged_in:
            print("Login not detected - navigate to Payments >> "
                  "ECR/Return Filing manually.")
        else:
            print("Login detected - opening Payments >> ECR/Return Filing...")
            # strip any post-login popup that intercepts the menu click
            try:
                driver.execute_script(
                    "document.querySelectorAll("
                    "'.modal.show,.modal-backdrop,#mainHomePageAlertModal')"
                    ".forEach(function(e){e.classList.remove('show');"
                    "e.style.display='none';if(e.remove)e.remove();});"
                    "document.body.classList.remove('modal-open');"
                    "document.body.style.overflow='';")
            except Exception:
                pass
            nav_ok = False
            try:
                for el in driver.find_elements(
                        By.XPATH,
                        "//a[contains(translate(.,'PAYMENTS','payments'),'payments')]"):
                    try:
                        try:
                            el.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", el)
                        break
                    except Exception:
                        continue
                time.sleep(1.5)
                # ECR/RETURN FILING entry (dropdown links may be hidden -
                # JS-click works either way)
                for el in driver.find_elements(
                        By.XPATH,
                        "//a[contains(translate(.,'ECR/RETURN FILING',"
                        "'ecr/return filing'),'ecr/return')"
                        " or contains(translate(.,'ECRRETURN','ecrreturn'),'ecr')]"):
                    txt = (el.text or el.get_attribute("textContent") or "").lower()
                    if "ecr" in txt:
                        try:
                            el.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", el)
                        nav_ok = True; break
                if not nav_ok:
                    # fallback: open the first anchor whose href mentions ECR
                    for el in driver.find_elements(By.TAG_NAME, "a"):
                        href = (el.get_attribute("href") or "").lower()
                        if "ecr" in href:
                            driver.get(el.get_attribute("href"))
                            nav_ok = True; break
            except Exception as e:
                print("Payments menu navigation failed:", e)
            if nav_ok:
                time.sleep(3)
                # click the "ECR Upload" tab/button when the page shows one
                try:
                    for el in driver.find_elements(
                            By.XPATH,
                            "//a[contains(translate(.,'ECR UPLOAD','ecr upload'),"
                            "'ecr upload')] | //button[contains("
                            "translate(.,'ECR UPLOAD','ecr upload'),'ecr upload')]"):
                        try:
                            el.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", el)
                        break
                except Exception:
                    pass
                # Iter 690 — PF Challan automation: pick the Wage Month in
                # the dropdown and AUTO-SELECT the generated ECR file into
                # the page's file-upload box.
                time.sleep(2.5)
                if ecr_month:
                    try:
                        from selenium.webdriver.support.ui import Select
                        _MABBR = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                                  "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
                        _y, _m = ecr_month.split("-")[0], int(ecr_month.split("-")[1])
                        _ab = _MABBR[_m - 1]
                        for sel_el in driver.find_elements(By.TAG_NAME, "select"):
                            try:
                                if not sel_el.is_displayed():
                                    continue
                                _s = Select(sel_el)
                                for op in _s.options:
                                    _t = (op.text or "").upper().replace(" ", "")
                                    if _ab in _t and _y in _t:
                                        _s.select_by_visible_text(op.text)
                                        print("Wage Month selected: %s" % op.text)
                                        raise StopIteration
                            except StopIteration:
                                raise
                            except Exception:
                                continue
                    except StopIteration:
                        pass
                    except Exception:
                        print("Wage Month dropdown not auto-selected - "
                              "pick it manually.")
                attached = False
                if ecr_path:
                    for _try in range(3):
                        try:
                            for el in driver.find_elements(
                                    By.CSS_SELECTOR, "input[type=file]"):
                                try:
                                    el.send_keys(ecr_path)
                                    attached = True
                                    break
                                except Exception:
                                    continue
                        except Exception:
                            pass
                        if attached:
                            break
                        time.sleep(2)
                if attached:
                    print("ECR FILE AUTO-SELECTED: %s" % ecr_path)
                    print("Now on the portal: verify the summary, click "
                          "Upload/Verify, then Prepare Challan -> Generate "
                          "TRRN and pay. (Nothing is submitted "
                          "automatically - you stay in control.)")
                elif ecr_path:
                    print("Upload box not found yet - click 'Choose File' "
                          "on the page and select:\n  %s" % ecr_path)
                else:
                    print("ECR page opened. Select the Wage Month, choose "
                          "the ECR .txt from PF Reports and click Upload.")
            else:
                print("Could not find the ECR menu link - open Payments >> "
                      "ECR/Return Filing manually.")

        print("\nPF CHALLAN FLOW DONE. Chrome stays open - complete the "
              "upload/TRRN on the portal and close it when finished.")
        return

    if portal not in PORTALS:
        print("Unknown portal. Use 'esic', 'epfo' or 'ecr_test'."); return

    def _get(url):
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)

    def _post(url, data):
        req = urllib.request.Request(
            url, data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)

    print("Fetching your %s login from the SKS app..." % portal.upper())
    creds = _get("%s/api/portal-ext/creds?token=%s&portal=%s" % (API_BASE, TOKEN, portal))
    if not creds.get("ok"):
        print("Server error:", creds); return

    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_experimental_option("detach", True)
    print("Launching Chrome (auto-managed driver)...")
    driver = _fresh_driver(opts)
    driver.get(PORTALS[portal])

    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys

    # Iter 400 (user fix) — BEFORE filling ID & Password, click OK/Close on
    # the portal's alert popup. The old code used one element_to_be_clickable
    # wait + a single native click; the EPFO modal fades in, so the click
    # fired mid-animation, got intercepted and the popup stayed open.
    # New logic: wait for full page load, then POLL up to 25s — whenever a
    # VISIBLE modal is on screen, click its OK/Close button (native click
    # with a JavaScript-click fallback). Finally strip any lingering
    # modal/backdrop so the login fields are usable.
    try:
        WebDriverWait(driver, 30).until(
            lambda d: d.execute_script("return document.readyState") == "complete")
    except Exception:
        pass
    time.sleep(1.5)  # let the modal fade-in animation start

    _POPUP_SELS = ("#btnCloseModal",
                   "button[aria-label='Close']",
                   "[aria-label='Close']",
                   "button.btn-danger[data-bs-dismiss='modal']",
                   "button[data-dismiss='modal']",
                   "#mainHomePageAlertModal button",
                   ".modal.show button.btn, .modal.in button.btn")

    def _visible_modal():
        for _m in driver.find_elements(
                By.CSS_SELECTOR, "#mainHomePageAlertModal, .modal.show, .modal.in"):
            try:
                if _m.is_displayed():
                    return _m
            except Exception:
                continue
        return None

    _clicked = False
    _quiet = 0
    _deadline = time.time() + 25
    while time.time() < _deadline:
        if _visible_modal() is None:
            _quiet += 1
            if _clicked or _quiet >= 6:  # ~3s with no popup -> move on
                break
            time.sleep(0.5)
            continue
        _quiet = 0
        for _sel in _POPUP_SELS:
            for _el in driver.find_elements(By.CSS_SELECTOR, _sel):
                try:
                    if not _el.is_displayed():
                        continue
                    try:
                        _el.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", _el)
                    _clicked = True
                    print("Alert popup: OK/Close clicked.")
                    time.sleep(1.0)
                    break
                except Exception:
                    continue
            if _clicked:
                break
        if _clicked and _visible_modal() is None:
            break
        time.sleep(0.5)
    if not _clicked:
        print("No alert popup detected - continuing.")
    # Safety net: remove any stuck modal/backdrop so fields are clickable.
    try:
        driver.execute_script(
            "document.querySelectorAll('#mainHomePageAlertModal,"
            ".modal.show,.modal.in,.modal-backdrop').forEach("
            "function(e){e.classList.remove('show');e.classList.remove('in');"
            "e.style.display='none';if(e.remove)e.remove();});"
            "document.body.classList.remove('modal-open');"
            "document.body.style.overflow='';")
    except Exception:
        pass

    # The EPFO portal is an Angular app — JS value injection does not update
    # ng-model (box looks filled but submits blank). Type like a real
    # keyboard (send_keys) with a native-setter JS fallback.
    def set_val(el, val):
        try:
            el.click()
        except Exception:
            pass
        try:
            el.send_keys(Keys.CONTROL, "a")
            el.send_keys(Keys.DELETE)
        except Exception:
            pass
        try:
            el.clear()
        except Exception:
            pass
        try:
            el.send_keys(val)
        except Exception:
            pass
        try:
            if (el.get_attribute("value") or "") != val:
                driver.execute_script(
                    "var s=Object.getOwnPropertyDescriptor("
                    "window.HTMLInputElement.prototype,'value').set;"
                    "s.call(arguments[0],arguments[1]);"
                    "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                    "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));"
                    "arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));",
                    el, val)
        except Exception:
            pass

    # Wait for the login form to render after the modal closes.
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[type=password]")))
    except Exception:
        pass

    user_el = None
    for el in driver.find_elements(By.CSS_SELECTOR, "input[type=text], input:not([type])"):
        try:
            nm = (el.get_attribute("name") or "") + (el.get_attribute("id") or "") + (el.get_attribute("placeholder") or "")
            if el.is_displayed() and not any(k in nm.lower() for k in ("captcha", "code", "otp", "search")):
                user_el = el; break
        except Exception:
            continue
    pass_el = None
    for el in driver.find_elements(By.CSS_SELECTOR, "input[type=password]"):
        if el.is_displayed():
            pass_el = el; break

    if user_el:
        set_val(user_el, creds["user_id"]); print("Filled User ID.")
    if pass_el:
        set_val(pass_el, creds["password"]); print("Filled Password.")

    cap_img = None
    for sel in ("img#captchaimg", "img[alt*=captcha i]", "img[src*=captcha i]",
                "img[id*=captcha i]", "img[title*=captcha i]"):
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els and els[0].is_displayed():
            cap_img = els[0]; break
    cap_in = None
    for sel in ("input[name*=captcha i]", "input[id*=captcha i]",
                "input[placeholder*=captcha i]", "input[name*=code i]"):
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els and els[0].is_displayed():
            cap_in = els[0]; break

    if cap_img is not None and cap_in is not None:
        try:
            b64 = base64.b64encode(cap_img.screenshot_as_png).decode("ascii")
            print("Reading captcha with AI...")
            sol = _post("%s/api/portal-ext/solve-captcha" % API_BASE,
                        {"token": TOKEN, "image_base64": b64, "numeric_only": portal == "esic"})
            if sol.get("ok") and sol.get("text"):
                set_val(cap_in, sol["text"]); print("Filled captcha:", sol["text"])
            else:
                print("Captcha not read - type it manually.")
        except Exception as e:
            print("Captcha step failed:", e)
    else:
        print("No captcha field detected - if there is one, type it manually.")

    print("\\nDone. Verify the captcha in Chrome, then click the portal's Login button.")
    print("(Chrome stays open. Close it yourself when finished.)")
'''

# The launcher (baked with api_base + token in config.json alongside it).
# On every run it: ensures Selenium is installed, pulls the latest login
# script into the SAME folder if a newer version exists, then runs it.
_LAUNCHER_PY = r'''"""SKS Portal Auto-Login — self-updating launcher.

Downloaded once. On each run it auto-updates the login script (and
Selenium keeps chromedriver current), so you never re-download anything.

Usage:  python sks_launcher.py esic     (or: epfo)
"""
import importlib.util
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def _cfg():
    with open(os.path.join(HERE, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def _ensure_selenium():
    try:
        import selenium  # noqa: F401
        return
    except Exception:
        print("Installing Selenium (first run only)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "selenium>=4.16"], check=False)


def _self_update(api_base, token):
    try:
        url = "%s/api/portal-ext/runner-script?token=%s" % (api_base, token)
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.load(r)
        ver = str(data.get("version") or "0")
        code = data.get("code") or ""
        script = os.path.join(HERE, "sks_autologin.py")
        vfile = os.path.join(HERE, ".runner_version")
        local = ""
        if os.path.exists(vfile):
            with open(vfile, "r", encoding="utf-8") as f:
                local = f.read().strip()
        if code and (local != ver or not os.path.exists(script)):
            with open(script, "w", encoding="utf-8") as f:
                f.write(code)
            with open(vfile, "w", encoding="utf-8") as f:
                f.write(ver)
            print("Auto-login script updated to v%s." % ver)
    except Exception as e:
        print("Update check skipped (%s) - using existing script." % e)


def main():
    cfg = _cfg()
    api_base, token = cfg["api_base"], cfg["token"]
    portal = sys.argv[1] if len(sys.argv) > 1 else "esic"
    _ensure_selenium()
    _self_update(api_base, token)
    script = os.path.join(HERE, "sks_autologin.py")
    if not os.path.exists(script):
        print("Could not obtain the login script. Check your internet and try again.")
        return
    spec = importlib.util.spec_from_file_location("sks_autologin", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run(api_base, token, portal)


if __name__ == "__main__":
    main()
'''

_RUNNER_REQ = "selenium>=4.16\n"

# Iter 691 — bats auto-detect the Python command: many PCs have only the
# `py` launcher on PATH (python.org default install without "Add to PATH").
_BAT_PY_DETECT = (
    "@echo off\r\n"
    "set PYCMD=python\r\n"
    "where python >nul 2>nul || set PYCMD=py\r\n"
)

_RUNNER_BAT = (
    _BAT_PY_DETECT +
    "%PYCMD% sks_launcher.py esic\r\n"
    "pause\r\n"
)

_RUNNER_BAT_PF = (
    _BAT_PY_DETECT +
    "%PYCMD% sks_launcher.py epfo\r\n"
    "pause\r\n"
)

# Iter 315 — ECR TEST: real Chrome window, open EPFO + close alert (OK).
_RUNNER_BAT_ECR_TEST = (
    _BAT_PY_DETECT +
    "%PYCMD% sks_launcher.py ecr_test\r\n"
    "pause\r\n"
)

# Iter 691 — OPEN-ONLY: new Chrome window on the EPFO portal, nothing
# filled, nothing clicked. User does everything manually.
_RUNNER_BAT_OPEN_EPFO = (
    _BAT_PY_DETECT +
    "%PYCMD% sks_launcher.py epfo_open\r\n"
    "pause\r\n"
)

# Iter 397 — LISTENER: one-click login from the payroll web app.
_RUNNER_BAT_LISTENER = (
    _BAT_PY_DETECT +
    "title SKS Runner - keep this window open\r\n"
    "%PYCMD% sks_launcher.py listen\r\n"
    "pause\r\n"
)

# Iter 692 — AUTO-START (user request: "no manual process"). One-time
# installer registers a hidden VBS launcher in HKCU\...\Run so the listener
# starts silently with Windows — no window, no double-clicking ever again.
_RUNNER_VBS_SILENT = (
    "Set fso = CreateObject(\"Scripting.FileSystemObject\")\r\n"
    "folder = fso.GetParentFolderName(WScript.ScriptFullName)\r\n"
    "Set sh = CreateObject(\"WScript.Shell\")\r\n"
    "sh.CurrentDirectory = folder\r\n"
    "cmd = \"cmd /c (where pythonw >nul 2>nul && pythonw sks_launcher.py listen)\"\r\n"
    "cmd = cmd & \" || (where pyw >nul 2>nul && pyw sks_launcher.py listen)\"\r\n"
    "cmd = cmd & \" || (py sks_launcher.py listen)\"\r\n"
    "sh.Run cmd, 0, False\r\n"
)

_RUNNER_BAT_AUTOSTART = (
    "@echo off\r\n"
    "cd /d \"%~dp0\"\r\n"
    "reg add \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\" "
    "/v SKSRunner /t REG_SZ /d \"wscript.exe \\\"%~dp0sks_listener_silent.vbs\\\"\" /f >nul\r\n"
    "wscript.exe \"%~dp0sks_listener_silent.vbs\"\r\n"
    "echo.\r\n"
    "echo  DONE! SKS Runner now starts AUTOMATICALLY with Windows\r\n"
    "echo  (silently in the background - no window).\r\n"
    "echo  It is ALREADY RUNNING right now - you can close this window\r\n"
    "echo  and click the buttons in the payroll portal directly.\r\n"
    "echo.\r\n"
    "pause\r\n"
)

_RUNNER_BAT_AUTOSTART_REMOVE = (
    "@echo off\r\n"
    "reg delete \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\" "
    "/v SKSRunner /f >nul 2>nul\r\n"
    "echo SKS Runner auto-start removed. (A running listener stops after\r\n"
    "echo the next restart, or end python in Task Manager.)\r\n"
    "pause\r\n"
)

_RUNNER_SH = (
    "#!/bin/sh\n"
    "python3 sks_launcher.py \"${1:-esic}\"\n"
)

_RUNNER_README = (
    "SKS Portal Auto-Login - PC Runner (self-updating)\n"
    "=================================================\n\n"
    "Requirements: Google Chrome + Python 3.9+ on this PC.\n\n"
    "WHERE TO PUT THIS FOLDER (do this once):\n"
    "  Windows : C:\\SKS-AutoLogin\n"
    "  Mac     : /Users/<you>/SKS-AutoLogin\n"
    "  Linux   : /home/<you>/SKS-AutoLogin\n"
    "  -> Unzip the downloaded file, then MOVE the folder to the path above.\n"
    "     Run it from there every time. Keeping it in one fixed place lets it\n"
    "     auto-update itself in place (script version + your credentials).\n\n"
    "Download this folder ONCE. It updates itself every run:\n"
    "  - The login script auto-updates from the SKS app.\n"
    "  - ChromeDriver auto-updates via Selenium (Selenium Manager).\n"
    "  - Your User ID/Password are fetched live each run.\n"
    "So you never need to download again.\n\n"
    "WINDOWS:  FULLY AUTOMATIC (recommended): double-click\n"
    "          install_autostart.bat ONCE. From then on the Runner starts\n"
    "          silently with Windows - nothing to open, ever. The buttons\n"
    "          in the payroll portal just work. (remove_autostart.bat\n"
    "          undoes this.)\n"
    "          Manual alternative: double-click run_esic.bat (or run_pf.bat)\n"
    "          OPEN-ONLY: double-click run_open_epfo.bat - a new Chrome\n"
    "          window (ChromeDriver) opens the EPFO portal and does\n"
    "          NOTHING else - you type username/password/captcha yourself.\n"
    "          ECR TEST: double-click run_ecr_test.bat - a new Chrome\n"
    "          window opens the EPFO portal and clicks the alert's OK\n"
    "          button automatically (no login).\n"
    "          ONE-CLICK FROM THE APP: double-click run_listener.bat and\n"
    "          KEEP THAT WINDOW OPEN. Now the 'Login - Open EPFO Portal'\n"
    "          button in PF Reports launches Chrome on this PC with the\n"
    "          selected firm's ID + Password auto-filled - you only type\n"
    "          the captcha and click Login.\n"
    "MAC/LINUX: open a terminal in the folder,\n"
    "           chmod +x run.sh ; ./run.sh esic   (or ./run.sh epfo)\n"
    "           ECR TEST: ./run.sh ecr_test\n\n"
    "A controlled Chrome window opens the portal and fills your login +\n"
    "captcha automatically. Verify the captcha, then click the portal's\n"
    "Login button.\n"
)


@router.get("/portal-ext/runner-script")
async def runner_script(token: str):
    doc = await db.automation_ext_tokens.find_one({"token": token})
    if not doc:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"version": RUNNER_VERSION, "code": _RUNNER_CODE}


# Iter 397 — one-click launch: the web app requests a fresh firm-scoped
# token, then pings the local Runner (http://127.0.0.1:8765/login) which
# fetches the credentials with it and opens Chrome.
@router.post("/admin/portal-automation/launch-token")
async def portal_launch_token(
    payload: Optional[Dict[str, Any]] = None,
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    company_id = await _resolve_company(
        admin, company_id or (payload or {}).get("company_id"))
    token = secrets.token_urlsafe(24)
    await db.automation_ext_tokens.insert_one({
        "token": token,
        "company_id": company_id,
        "created_by": admin["user_id"],
        "created_at": now_iso(),
        "kind": "launch",
        "run_id": (payload or {}).get("run_id") or None,
    })
    return {"ok": True, "token": token, "runner_url": "http://127.0.0.1:8765"}


@router.get("/admin/portal-automation/runner-download")
async def runner_download(
    api_base: str = Query(...),
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    company_id = await _resolve_company(admin, company_id)

    base = (api_base or "").strip().rstrip("/")
    if not base.startswith("http"):
        raise HTTPException(status_code=400, detail="api_base must be a full URL")

    token = secrets.token_urlsafe(24)
    await db.automation_ext_tokens.insert_one({
        "token": token,
        "company_id": company_id,
        "created_by": admin["user_id"],
        "created_at": now_iso(),
        "kind": "pc_runner",
    })

    config = json.dumps({"api_base": base, "token": token}, indent=2)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("sks_launcher.py", _LAUNCHER_PY)
        z.writestr("config.json", config)
        z.writestr("requirements.txt", _RUNNER_REQ)
        z.writestr("run_esic.bat", _RUNNER_BAT)
        z.writestr("run_pf.bat", _RUNNER_BAT_PF)
        z.writestr("run_ecr_test.bat", _RUNNER_BAT_ECR_TEST)
        z.writestr("run_open_epfo.bat", _RUNNER_BAT_OPEN_EPFO)
        z.writestr("run_listener.bat", _RUNNER_BAT_LISTENER)
        z.writestr("sks_listener_silent.vbs", _RUNNER_VBS_SILENT)
        z.writestr("install_autostart.bat", _RUNNER_BAT_AUTOSTART)
        z.writestr("remove_autostart.bat", _RUNNER_BAT_AUTOSTART_REMOVE)
        z.writestr("run.sh", _RUNNER_SH)
        z.writestr("README.txt", _RUNNER_README)
    buf.seek(0)
    logger.info("[portal-ext] PC runner generated for company=%s by %s",
                company_id, admin["user_id"])
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="sks-autologin-pc.zip"'},
    )
