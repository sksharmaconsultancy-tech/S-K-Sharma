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
# updates the chromedriver matching the installed Chrome — so the driver
# stays current with no manual step.

_RUNNER_PY = r'''"""SKS Portal Auto-Login — local PC runner.

Runs on YOUR computer (allowed ISP IP), opens Chrome via Selenium, fills
the firm's ESIC / EPFO User ID + Password (fetched live from the SKS app),
reads the captcha with the app's AI, and leaves the browser open for you
to verify the captcha and click Login.

ChromeDriver is handled automatically by Selenium Manager (Selenium 4.6+),
so the driver auto-updates to match your installed Chrome — no manual
driver download or version juggling.

Usage:   python sks_autologin.py           (defaults to ESIC)
         python sks_autologin.py epfo      (EPFO / PF portal)
"""
import base64
import json
import sys
import time
import urllib.request

API_BASE = %%BASE%%
TOKEN = %%TOKEN%%

PORTALS = {
    "esic": "https://portal.esic.gov.in/EmployerPortal/ESICInsurancePortal/Portal_Loginnew.aspx",
    "epfo": "https://unifiedportal-emp.epfindia.gov.in/epfo/",
}


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def _post(url, data):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    portal = (sys.argv[1] if len(sys.argv) > 1 else "esic").lower()
    if portal not in PORTALS:
        print("Unknown portal. Use 'esic' or 'epfo'."); return

    print("Fetching your %s login from the SKS app..." % portal.upper())
    try:
        creds = _get("%s/api/portal-ext/creds?token=%s&portal=%s" % (API_BASE, TOKEN, portal))
    except Exception as e:
        print("Could not load credentials:", e); return
    if not creds.get("ok"):
        print("Server error:", creds); return

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
    except Exception:
        print("Selenium is not installed. Run:  pip install -r requirements.txt")
        return

    opts = Options()
    opts.add_experimental_option("detach", True)  # keep Chrome open after script ends
    print("Launching Chrome (auto-managed driver)...")
    driver = webdriver.Chrome(options=opts)       # Selenium Manager auto-updates the driver
    driver.get(PORTALS[portal])
    time.sleep(3)

    def set_val(el, val):
        driver.execute_script(
            "arguments[0].value=arguments[1];"
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", el, val)

    # User ID: first visible text input that isn't a captcha/otp/search box.
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

    # Captcha: screenshot the image element, ask the app to read it.
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
            png = cap_img.screenshot_as_png
            b64 = base64.b64encode(png).decode("ascii")
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


if __name__ == "__main__":
    main()
'''

_RUNNER_REQ = "selenium>=4.16\n"

_RUNNER_BAT = (
    "@echo off\r\n"
    "echo Installing dependencies (first run only)...\r\n"
    "python -m pip install -r requirements.txt\r\n"
    "echo Starting ESIC auto-login...\r\n"
    "python sks_autologin.py esic\r\n"
    "pause\r\n"
)

_RUNNER_BAT_PF = (
    "@echo off\r\n"
    "python -m pip install -r requirements.txt\r\n"
    "python sks_autologin.py epfo\r\n"
    "pause\r\n"
)

_RUNNER_SH = (
    "#!/bin/sh\n"
    "python3 -m pip install -r requirements.txt\n"
    "python3 sks_autologin.py \"${1:-esic}\"\n"
)

_RUNNER_README = (
    "SKS Portal Auto-Login - PC Runner (ChromeDriver)\n"
    "================================================\n\n"
    "Requirements: Google Chrome + Python 3.9+ installed on this PC.\n"
    "The chromedriver is downloaded & auto-updated by Selenium automatically\n"
    "(Selenium Manager) - you never manage the driver yourself.\n\n"
    "WINDOWS:\n"
    "  - Double-click run_esic.bat   (ESIC login)\n"
    "  - Double-click run_pf.bat      (EPFO / PF login)\n\n"
    "MAC / LINUX:\n"
    "  - chmod +x run.sh  then  ./run.sh esic   (or ./run.sh epfo)\n\n"
    "What happens:\n"
    "  Chrome opens the portal login page, your User ID + Password are filled\n"
    "  from the SKS app, and the captcha is read by AI and filled. Check the\n"
    "  captcha, then click the portal's Login button.\n\n"
    "Credentials update automatically - they are fetched live each run, so you\n"
    "never need to re-download this folder when you change them in Firm Master.\n"
)


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

    runner = (
        _RUNNER_PY
        .replace("%%BASE%%", _js_str(base))
        .replace("%%TOKEN%%", _js_str(token))
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("sks_autologin.py", runner)
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
