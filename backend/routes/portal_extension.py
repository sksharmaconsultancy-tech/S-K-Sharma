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
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
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


# --- Local PC runner (Selenium + auto-managed ChromeDriver) ---------------
# Selenium 4.6+ ships "Selenium Manager", which automatically downloads and
# updates the chromedriver matching the installed Chrome. On top of that, a
# tiny LAUNCHER self-updates the login script from the app on every run — so
# the operator downloads ONCE and the folder stays current forever.

# Bump this when _RUNNER_CODE changes; the launcher pulls the new script.
RUNNER_VERSION = "1"

# The actual login logic — served (not baked) so it can auto-update in the
# operator's folder. Exposes run(API_BASE, TOKEN, portal).
_RUNNER_CODE = r'''"""SKS Portal Auto-Login — login script (auto-updated by launcher)."""
import base64
import json
import time
import urllib.request

PORTALS = {
    "esic": "https://portal.esic.gov.in/EmployerPortal/ESICInsurancePortal/Portal_Loginnew.aspx",
    "epfo": "https://unifiedportal-emp.epfindia.gov.in/epfo/",
}


def run(API_BASE, TOKEN, portal):
    portal = (portal or "esic").lower()
    if portal not in PORTALS:
        print("Unknown portal. Use 'esic' or 'epfo'."); return

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
    driver = webdriver.Chrome(options=opts)
    driver.get(PORTALS[portal])
    time.sleep(3)

    def set_val(el, val):
        driver.execute_script(
            "arguments[0].value=arguments[1];"
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", el, val)

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

_RUNNER_BAT = (
    "@echo off\r\n"
    "python sks_launcher.py esic\r\n"
    "pause\r\n"
)

_RUNNER_BAT_PF = (
    "@echo off\r\n"
    "python sks_launcher.py epfo\r\n"
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
    "WINDOWS:  open the folder, double-click run_esic.bat  (or run_pf.bat)\n"
    "MAC/LINUX: open a terminal in the folder,\n"
    "           chmod +x run.sh ; ./run.sh esic   (or ./run.sh epfo)\n\n"
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
