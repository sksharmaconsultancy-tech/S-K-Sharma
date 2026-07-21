"""Live Government Portal Automation Engine — Iter 234.

Step-based Playwright engine that runs government-portal flows (EPFO,
ESIC, Shram Suvidha, …) on the server while STREAMING live JPEG frames
to the payroll UI (Automation Monitor screen). Every action is made
human-visible: fields are highlighted (yellow outline) and scrolled
into view before typing, a fake cursor dot moves to each click target,
and typing happens character-by-character.

Controls: pause / resume / retry-step / skip-step / stop / emergency.
CAPTCHA and OTP are NEVER bypassed — the engine first tries the AI
vision reader (existing captcha_reader) and otherwise PAUSES, showing
the captcha image in the UI so the user solves it from the payroll.

Media (major-step screenshots + session video) is stored under
``/app/backend/rpa_media/{job_id}/`` and indexed on the persisted job
doc in ``db.portal_rpa_jobs``.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import random
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")

logger = logging.getLogger("rpa_engine")

MEDIA_ROOT = Path("/app/backend/rpa_media")
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

SPEED_MULT = {"very_slow": 3.0, "slow": 2.0, "normal": 1.0, "fast": 0.5}

PORTALS: Dict[str, Dict[str, str]] = {
    "epfo": {"label": "EPFO — Employer Portal",
             "url": "https://unifiedportal-emp.epfindia.gov.in/epfo/"},
    "esic": {"label": "ESIC — Employer Portal",
             "url": "https://portal.esic.gov.in/EmployerPortal/ESICInsurancePortal/Portal_Loginnew.aspx"},
    "shram_suvidha": {"label": "Shram Suvidha Portal",
                      "url": "https://shramsuvidha.gov.in/user/login"},
    "ptax": {"label": "Professional Tax Portal", "url": ""},
    "labour_license": {"label": "Labour License (State) Portal", "url": ""},
    "factory": {"label": "Factory & Boilers Portal", "url": ""},
}

FLOWS: Dict[str, Dict[str, Any]] = {
    "login": {"label": "Login & Dashboard", "portals": list(PORTALS.keys()),
              "needs_employee": False},
    "epfo_generate_uan": {"label": "Generate UAN (Member Registration)",
                          "portals": ["epfo"], "needs_employee": True},
    "esic_ip_register": {"label": "ESIC IP Registration",
                         "portals": ["esic"], "needs_employee": True},
    # ---- Compliance Automation Studio (Iter 235) ------------------------
    "epfo_ecr_upload": {"label": "ECR Upload → TRRN → Challan → PDF",
                        "portals": ["epfo"], "needs_employee": False,
                        "needs_run": True},
    "esic_contribution_upload": {"label": "Contribution Upload → Challan",
                                 "portals": ["esic"], "needs_employee": False,
                                 "needs_run": True},
    "epfo_member_search": {"label": "Member Search (assisted)",
                           "portals": ["epfo"], "needs_employee": False,
                           "nav": ["Member Search", "MEMBER SEARCH", "Search Member"]},
    "epfo_establishment": {"label": "Establishment Profile (assisted)",
                           "portals": ["epfo"], "needs_employee": False,
                           "nav": ["Establishment", "Profile", "ESTABLISHMENT"]},
    "esic_contribution_history": {"label": "Contribution History (assisted)",
                                  "portals": ["esic"], "needs_employee": False,
                                  "nav": ["Contribution History", "View Contribution",
                                          "Contribution Details"]},
    "esic_dashboard": {"label": "Employer Dashboard (assisted)",
                       "portals": ["esic"], "needs_employee": False, "nav": []},
}

# HARD SAFETY RAIL — automation stops at challan finalisation and NEVER
# clicks anything that could start a bank payment.
_PAYMENT_BLOCKLIST = ("pay", "payment", "net banking", "netbanking",
                      "bank", "debit", "online payment", "make payment")

# ---------------------------------------------------------------------------
# Session stores. _SESSIONS holds JSON-safe live state (polled by the UI);
# _CTRL holds asyncio primitives + browser handles for control actions.
# ---------------------------------------------------------------------------
_SESSIONS: Dict[str, Dict[str, Any]] = {}
_CTRL: Dict[str, Dict[str, Any]] = {}


class _Stop(Exception):
    """Raised inside the runner when the user stops the session."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def get_settings(db) -> Dict[str, Any]:
    doc = await db.rpa_settings.find_one({"_id": "global"}) or {}
    return {
        "speed": doc.get("speed") or "normal",
        "timeout_sec": int(doc.get("timeout_sec") or 25),
        # Security requirement #5 — never more than 3 retries.
        "retry_count": min(3, int(doc.get("retry_count") or 2)),
        "training_mode": bool(doc.get("training_mode") or False),
        # Security requirement #13 — compliance mode (default ON):
        # prioritises stability + responsible interaction over speed.
        "compliance_mode": bool(doc.get("compliance_mode", True)),
    }


async def save_settings(db, payload: Dict[str, Any]) -> Dict[str, Any]:
    cur = await get_settings(db)
    if payload.get("speed") in SPEED_MULT:
        cur["speed"] = payload["speed"]
    if payload.get("timeout_sec"):
        cur["timeout_sec"] = max(5, min(120, int(payload["timeout_sec"])))
    if payload.get("retry_count") is not None:
        cur["retry_count"] = max(1, min(3, int(payload["retry_count"])))
    if payload.get("training_mode") is not None:
        cur["training_mode"] = bool(payload["training_mode"])
    if payload.get("compliance_mode") is not None:
        cur["compliance_mode"] = bool(payload["compliance_mode"])
    await db.rpa_settings.update_one({"_id": "global"}, {"$set": cur}, upsert=True)
    return cur


async def fetch_portal_creds(db, company_id: str, portal: str) -> Optional[Dict[str, str]]:
    """EPFO/ESIC use the Firm Master EPF/ESI sections (existing helper);
    other portals scan the legacy Portal Logins rows by keyword."""
    from utils.rpa_worker import _fetch_creds
    if portal in ("epfo", "esic"):
        return await _fetch_creds(db, company_id, portal)
    master = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "portal_logins": 1})
    if not master:
        return None
    kw = {
        "shram_suvidha": ("shram", "suvidha", "sso"),
        "ptax": ("professional", "ptax", "p.tax", "p tax"),
        "labour_license": ("labour", "labor", "license"),
        "factory": ("factory", "boiler"),
    }.get(portal, (portal,))
    for row in (master.get("portal_logins") or []):
        lt = str(row.get("login_type") or "").lower()
        if any(k in lt for k in kw):
            u = (row.get("user_name") or "").strip()
            p = (row.get("password") or "").strip()
            if u and p:
                return {"user_name": u, "password": p,
                        "login_url": (row.get("login_url") or "").strip()}
    return None


def validate_run_rows(rows: List[dict], portal: str) -> Dict[str, Any]:
    """Pre-flight validation report shown before an ECR / contribution
    upload starts: counts, wages, missing & duplicate UAN / IP numbers."""
    report: Dict[str, Any] = {
        "employee_count": 0, "total_wages": 0, "total_contribution": 0,
        "missing_ids": [], "duplicate_ids": [], "included": 0, "warnings": [],
    }
    seen: Dict[str, str] = {}
    for r in rows:
        name = r.get("name") or r.get("employee_code") or "?"
        report["employee_count"] += 1
        if portal == "epfo":
            if not r.get("pf_applicable"):
                continue
            _id = str(r.get("uan_no") or "").strip()
            wages = float(r.get("pf_wages") or 0)
            contrib = float(r.get("pf_employee") or 0)
            id_ok = _id.isdigit() and len(_id) == 12
            id_label = "UAN"
        else:
            if not r.get("esic_applicable"):
                continue
            _id = str(r.get("esi_ip_no") or "").strip()
            wages = float(r.get("esic_wage_base") or r.get("gross_paid") or 0)
            contrib = float(r.get("esic_employee") or 0)
            id_ok = bool(_id)
            id_label = "ESIC IP No"
        if not id_ok:
            report["missing_ids"].append({"name": name, "issue": f"Missing/invalid {id_label}"})
            continue
        if _id in seen:
            report["duplicate_ids"].append(
                {"name": name, "id": _id, "also": seen[_id]})
            continue
        seen[_id] = name
        report["included"] += 1
        report["total_wages"] += wages
        report["total_contribution"] += contrib
    report["total_wages"] = round(report["total_wages"], 2)
    report["total_contribution"] = round(report["total_contribution"], 2)
    if report["included"] == 0:
        report["warnings"].append("No employee qualifies for this upload — file would be empty.")
    return report


def _employee_snapshot(emp: dict) -> Dict[str, Any]:
    return {
        "user_id": emp.get("user_id"),
        "name": emp.get("name"),
        "father_name": emp.get("father_name"),
        "dob": emp.get("dob"),
        "gender": emp.get("gender"),
        "mobile": emp.get("phone"),
        "email": emp.get("email"),
        "aadhaar": emp.get("aadhaar_no"),
        "pan": emp.get("pan_no"),
        "address": emp.get("present_address") or emp.get("address"),
        "doj": emp.get("doj"),
        "salary": emp.get("salary_monthly"),
        "department": emp.get("department"),
        "designation": emp.get("designation"),
        "employee_code": emp.get("employee_code"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def start_session(
    db, *, company_id: str, portal: str, flow: str,
    employee_id: Optional[str], started_by: str, speed: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Validate + launch a session. Returns (session_id, error)."""
    if portal not in PORTALS:
        return None, f"Unknown portal '{portal}'"
    if flow not in FLOWS:
        return None, f"Unknown flow '{flow}'"
    if portal not in FLOWS[flow]["portals"]:
        return None, f"Flow '{FLOWS[flow]['label']}' is not available for {portal.upper()}"
    employee = None
    if FLOWS[flow]["needs_employee"]:
        if not employee_id:
            return None, "Select an employee for this flow"
        employee = await db.users.find_one({"user_id": employee_id}, {"_id": 0})
        if not employee:
            return None, "Employee not found"
    run = None
    validation = None
    if FLOWS[flow].get("needs_run"):
        if not run_id:
            return None, "Select a Compliance Salary Process (month) for this upload"
        run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
        if not run:
            return None, "Compliance salary run not found"
        rows = run.get("rows") or run.get("lines") or []
        # Enrich UANs from the Employee Master when missing on the row.
        uids = [r.get("user_id") for r in rows if r.get("user_id") and not r.get("uan_no")]
        if uids:
            async for u in db.users.find(
                {"user_id": {"$in": uids}}, {"_id": 0, "user_id": 1, "uan_no": 1}):
                for r in rows:
                    if r.get("user_id") == u["user_id"]:
                        r.setdefault("uan_no", u.get("uan_no"))
        validation = validate_run_rows(rows, portal)
        if validation["included"] == 0:
            return None, ("Validation failed — no employee qualifies for this "
                          "upload. Fix missing UAN / IP numbers first.")
    creds = await fetch_portal_creds(db, company_id, portal)
    if not creds:
        return None, (f"No {portal.upper()} User ID / Password saved on the Firm "
                      "Master. Add them under Firm Master → Portal Logins first.")
    # Security layer — Session Manager + Rate Limiter: portals are processed
    # SEQUENTIALLY per company and the same employer account never has two
    # concurrent login sessions.
    for other in _SESSIONS.values():
        if (other["company_id"] == company_id
                and other["status"] not in ("completed", "failed", "stopped")):
            return None, ("Another automation is already running for this firm "
                          f"({other['portal_label']} — {other['flow_label']}). "
                          "Wait for it to finish or stop it first.")
    settings = await get_settings(db)
    if speed in SPEED_MULT:
        settings["speed"] = speed

    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "name": 1})

    sid = f"rpa_{uuid.uuid4().hex[:12]}"
    job_id = f"rpajob_{uuid.uuid4().hex[:10]}"
    steps = [{"index": i, "name": n, "status": "pending"}
             for i, (n, _) in enumerate(_flow_steps(flow))]
    _SESSIONS[sid] = {
        "session_id": sid, "job_id": job_id,
        "company_id": company_id, "company_name": (company or {}).get("name"),
        "portal": portal, "portal_label": PORTALS[portal]["label"],
        "flow": flow, "flow_label": FLOWS[flow]["label"],
        "employee": _employee_snapshot(employee) if employee else None,
        "run_id": run_id, "run_month": (run or {}).get("month"),
        "validation": validation,
        "downloads": [],
        "status": "launching",
        "message": "Preparing browser…",
        "steps": steps, "current_step": 0, "progress": 0,
        "current_url": None, "network": "online", "browser": "starting",
        "frame_b64": None, "captcha_b64": None, "input_needed": None,
        "logs": [], "screens": [],
        "started_at": _now_iso(), "ended_at": None,
        "elapsed_sec": 0, "eta_sec": None,
        "speed": settings["speed"],
        "error": None, "video": None,
        "started_by": started_by,
    }
    _CTRL[sid] = {
        "pause": asyncio.Event(), "stop": False, "emergency": False,
        "skip": False, "retry": False, "previous": False,
        "input_event": asyncio.Event(), "input_value": None,
        "browser": None, "settings": settings, "creds": creds,
        "run": run, "upload_file": None,
    }
    _CTRL[sid]["pause"].set()  # set = running (cleared = paused)
    asyncio.get_event_loop().create_task(_run_session(db, sid))
    return sid, None


def get_session(sid: str) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(sid)
    if not s:
        return None
    out = dict(s)
    out["logs"] = s["logs"][-60:]
    if s["started_at"] and not s["ended_at"]:
        try:
            t0 = datetime.fromisoformat(s["started_at"].replace("Z", "+00:00"))
            out["elapsed_sec"] = int((datetime.now(timezone.utc) - t0).total_seconds())
        except Exception:
            pass
    return out


def control_session(sid: str, action: str) -> Tuple[bool, str]:
    s, c = _SESSIONS.get(sid), _CTRL.get(sid)
    if not s or not c:
        return False, "Session not found"
    if action == "pause":
        c["pause"].clear()
        _log(sid, "⏸ Paused by user")
        s["status"] = "paused"
    elif action == "resume":
        c["pause"].set()
        _log(sid, "▶ Resumed by user")
        if s["status"] == "paused":
            s["status"] = "running"
    elif action == "retry":
        c["retry"] = True
        c["input_event"].set()
        c["pause"].set()
        _log(sid, "🔁 Retry step requested")
    elif action == "skip":
        c["skip"] = True
        c["input_event"].set()
        c["pause"].set()
        _log(sid, "⏭ Skip step requested")
    elif action == "previous":
        c["previous"] = True
        c["input_event"].set()
        c["pause"].set()
        _log(sid, "⏮ Previous step requested")
    elif action in ("stop", "emergency_stop"):
        c["stop"] = True
        c["emergency"] = action == "emergency_stop"
        c["input_event"].set()
        c["pause"].set()
        _log(sid, "🛑 Emergency stop!" if c["emergency"] else "⏹ Stop requested")
        if c["emergency"] and c.get("browser") is not None:
            # Kill the browser immediately without waiting for step gates.
            async def _kill():
                try:
                    await c["browser"].close()
                except Exception:
                    pass
            asyncio.get_event_loop().create_task(_kill())
    else:
        return False, f"Unknown action '{action}'"
    return True, "ok"


def submit_input(sid: str, value: str) -> Tuple[bool, str]:
    """User-supplied CAPTCHA text / OTP / confirmation from the UI."""
    s, c = _SESSIONS.get(sid), _CTRL.get(sid)
    if not s or not c:
        return False, "Session not found"
    if not s.get("input_needed"):
        return False, "The automation is not waiting for input right now"
    c["input_value"] = (value or "").strip()
    c["input_event"].set()
    return True, "ok"


def list_active() -> List[Dict[str, Any]]:
    return [
        {"session_id": s["session_id"], "portal": s["portal"], "flow": s["flow"],
         "status": s["status"], "company_id": s["company_id"],
         "started_at": s["started_at"]}
        for s in _SESSIONS.values()
        if s["status"] not in ("completed", "failed", "stopped")
    ]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _log(sid: str, msg: str, level: str = "info") -> None:
    s = _SESSIONS.get(sid)
    if not s:
        return
    hhmm = datetime.now(timezone.utc).strftime("%H:%M:%S")
    s["logs"].append({"at": _now_iso(), "t": hhmm, "msg": msg, "level": level})
    s["message"] = msg
    logger.info("[rpa %s] %s", sid, msg)


class Ctx:
    """Per-session helper toolbox passed to every step function."""

    def __init__(self, db, sid: str, page):
        self.db = db
        self.sid = sid
        self.page = page
        self.s = _SESSIONS[sid]
        self.c = _CTRL[sid]
        self.creds = self.c["creds"]
        self.settings = self.c["settings"]
        self.mult = SPEED_MULT.get(self.s["speed"], 1.0)
        if self.settings.get("training_mode"):
            self.mult = max(self.mult, 3.0)
        # Compliance mode (security req #13) — stability over speed: never
        # run faster than 1.5× human pace.
        if self.settings.get("compliance_mode", True):
            self.mult = max(self.mult, 1.5)
        self.timeout_ms = self.settings["timeout_sec"] * 1000

    async def audit(self, event: str, detail: str = "") -> None:
        """Security req #9 — persistent audit trail of every significant
        action (login, upload, download, submission, file generation)."""
        try:
            await self.db.rpa_audit.insert_one({
                "at": _now_iso(), "session_id": self.sid,
                "job_id": self.s["job_id"], "company_id": self.s["company_id"],
                "portal": self.s["portal"], "flow": self.s["flow"],
                "by": self.s.get("started_by"), "event": event, "detail": detail,
            })
        except Exception:
            pass

    async def gate(self) -> None:
        """Honour pause / stop between actions."""
        c = self.c
        if c["stop"]:
            raise _Stop()
        if not c["pause"].is_set():
            self.s["status"] = "paused"
            await c["pause"].wait()
            if c["stop"]:
                raise _Stop()
            self.s["status"] = "running"

    async def sleep(self, sec: float) -> None:
        await self.gate()
        await asyncio.sleep(sec * self.mult)

    def log(self, msg: str, level: str = "info") -> None:
        _log(self.sid, msg, level)

    # ---- Visual helpers --------------------------------------------------
    async def _ensure_overlay(self) -> None:
        try:
            await self.page.evaluate(
                """() => {
                  if (!document.getElementById('__rpa_css')) {
                    const st = document.createElement('style');
                    st.id='__rpa_css';
                    st.textContent = `
                      @keyframes __rpaPulse {0%{box-shadow:0 0 0 0 rgba(250,204,21,.65)}
                        70%{box-shadow:0 0 0 10px rgba(250,204,21,0)}
                        100%{box-shadow:0 0 0 0 rgba(250,204,21,0)}}
                      .__rpa_hl {outline:3px solid #facc15 !important;
                        animation:__rpaPulse 1s ease-out infinite !important;}`;
                    document.head.appendChild(st);
                  }
                  if (!document.getElementById('__rpa_cursor')) {
                    const c = document.createElement('div');
                    c.id='__rpa_cursor';
                    c.style.cssText='position:fixed;z-index:2147483647;width:18px;height:18px;'+
                      'border-radius:50%;background:rgba(239,68,68,.85);border:2px solid #fff;'+
                      'pointer-events:none;transition:all .45s ease;top:10px;left:10px;'+
                      'box-shadow:0 1px 6px rgba(0,0,0,.4)';
                    document.body.appendChild(c);
                  }
                }"""
            )
        except Exception:
            pass

    async def highlight(self, locator) -> None:
        """Scroll into view, yellow pulse highlight, move the fake cursor."""
        await self.gate()
        await self._ensure_overlay()
        try:
            await locator.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        try:
            box = await locator.bounding_box()
            await locator.evaluate("el => el.classList.add('__rpa_hl')")
            if box:
                x = box["x"] + box["width"] / 2
                y = box["y"] + box["height"] / 2
                await self.page.evaluate(
                    """([x,y]) => { const c=document.getElementById('__rpa_cursor');
                        if(c){c.style.left=(x-9)+'px'; c.style.top=(y-9)+'px';} }""",
                    [x, y],
                )
        except Exception:
            pass
        await self.sleep(0.8)

    async def _unhighlight(self, locator) -> None:
        try:
            await locator.evaluate("el => el.classList.remove('__rpa_hl')")
        except Exception:
            pass

    async def click(self, locator, desc: str = "") -> None:
        await self.highlight(locator)
        if desc:
            self.log(f"🖱 Clicking {desc}")
        # Security req #4 — human click cadence: 500–1500 ms before the click.
        await self.sleep(random.uniform(0.5, 1.5) / max(self.mult, 0.01))
        await locator.click(timeout=self.timeout_ms)
        await self._unhighlight(locator)
        # Wait for the page to settle before the next action.
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        await self.sleep(0.4)

    async def type(self, locator, text: str, desc: str = "", secret: bool = False) -> None:
        await self.highlight(locator)
        if desc:
            self.log(f"⌨ Typing {desc}" + ("" if secret else f": {text}"))
        try:
            await locator.click(timeout=4000)
        except Exception:
            pass
        try:
            await locator.fill("", timeout=3000)
        except Exception:
            pass
        # Security req #4 — human typing: 50–150 ms per character.
        delay = int(random.uniform(50, 150) * max(self.mult, 1.0))
        await locator.press_sequentially(str(text), delay=delay, timeout=max(self.timeout_ms, len(str(text)) * delay + 8000))
        await self._unhighlight(locator)
        await self.sleep(0.3)

    async def first_visible(self, selectors: List[str]):
        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

    # ---- Screenshots / media ----------------------------------------------
    def media_dir(self) -> Path:
        d = MEDIA_ROOT / self.s["job_id"]
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def snap(self, tag: str) -> None:
        """Save a MAJOR-step screenshot to disk + index it."""
        try:
            slug = re.sub(r"[^a-z0-9]+", "_", tag.lower()).strip("_")[:40]
            fname = f"{len(self.s['screens']):02d}_{slug}.jpg"
            await self.page.screenshot(path=str(self.media_dir() / fname),
                                       type="jpeg", quality=60)
            self.s["screens"].append({"tag": tag, "file": fname, "at": _now_iso()})
        except Exception:
            pass

    # ---- User-input pauses (captcha / OTP / confirm) -----------------------
    async def wait_user_input(self, kind: str, prompt: str,
                              image_b64: Optional[str] = None) -> str:
        """Block until the user submits a value from the Monitor UI."""
        c, s = self.c, self.s
        c["input_event"].clear()
        c["input_value"] = None
        s["input_needed"] = {"kind": kind, "prompt": prompt}
        s["captcha_b64"] = image_b64
        s["status"] = f"waiting_{kind}"
        self.log(f"⏳ Waiting for you — {prompt}", "warn")
        await c["input_event"].wait()
        s["input_needed"] = None
        s["captcha_b64"] = None
        if c["stop"]:
            raise _Stop()
        if c["retry"] or c["skip"]:
            return ""  # control action pre-empts input
        s["status"] = "running"
        return c["input_value"] or ""


def _flow_steps(flow: str) -> List[Tuple[str, Callable]]:
    base: List[Tuple[str, Callable]] = [
        ("Open Portal", _step_open_portal),
        ("Enter User ID & Password", _step_fill_credentials),
        ("Solve Captcha & Sign In", _step_captcha_and_login),
        ("Verify Login", _step_verify_login),
        ("Dashboard Screenshot", _step_dashboard),
    ]
    if flow == "epfo_generate_uan":
        return base + [
            ("Open Member Registration", _step_epfo_open_registration),
            ("Fill Employee Details", _step_epfo_fill_member),
            ("Review & Confirm", _step_review_confirm),
            ("Submit Registration", _step_epfo_submit),
            ("Capture Acknowledgement", _step_capture_ack),
        ]
    if flow == "epfo_ecr_upload":
        return [("Generate & Validate ECR File", _step_generate_file)] + base + [
            ("Open ECR Upload Page", _step_open_upload_page),
            ("Upload ECR File", _step_upload_file),
            ("Verify ECR Summary", _step_verify_summary),
            ("Generate TRRN", _step_generate_trrn),
            ("Generate Challan", _step_generate_challan),
            ("Download Challan PDF", _step_download_documents),
        ]
    if flow == "esic_contribution_upload":
        return [("Generate Contribution File", _step_generate_file)] + base + [
            ("Open Contribution Upload", _step_open_upload_page),
            ("Upload Contribution File", _step_upload_file),
            ("Verify Contribution", _step_verify_summary),
            ("Generate Challan", _step_generate_challan),
            ("Download Challan", _step_download_documents),
        ]
    fmeta = FLOWS.get(flow) or {}
    if "nav" in fmeta:
        extra: List[Tuple[str, Callable]] = []
        if fmeta["nav"]:
            extra.append(("Open Page", _mk_nav_step(fmeta["nav"])))
        extra.append(("Assisted Live Session", _step_assist_hold))
        return base + extra
    return base


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------
async def _step_open_portal(ctx: Ctx) -> None:
    url = ctx.creds.get("login_url") or PORTALS[ctx.s["portal"]]["url"]
    if not url:
        raise RuntimeError(
            "No portal URL configured. Save the Login URL on the Firm "
            "Master → Portal Logins row for this portal.")
    ctx.log(f"🌐 Opening {ctx.s['portal_label']} …")
    try:
        await ctx.page.goto(url, wait_until="domcontentloaded",
                            timeout=max(ctx.timeout_ms, 30000))
    except Exception as exc:
        ctx.s["network"] = "unreachable"
        raise RuntimeError(
            "The portal did not respond — Indian government portals often "
            "block cloud/datacenter IPs. Run from an allowed network or set "
            "PORTAL_PROXY_URL in the backend .env.") from exc
    await ctx.sleep(1.2)
    from utils.rpa_worker import _detect_block_or_error
    blocked = await _detect_block_or_error(ctx.page)
    if blocked:
        raise RuntimeError(blocked + " — the portal is blocking this server's IP.")
    # Security req #8 — maintenance / downtime detection: stop gracefully.
    try:
        body_txt = (await ctx.page.inner_text("body", timeout=4000) or "").lower()
        for kw in ("under maintenance", "site maintenance", "temporarily unavailable",
                   "server is busy", "service unavailable", "down for maintenance"):
            if kw in body_txt:
                raise RuntimeError(
                    f"The portal shows a maintenance/downtime notice (\u201c{kw}\u201d). "
                    "Automation stopped gracefully — try again later.")
    except RuntimeError:
        raise
    except Exception:
        pass
    ctx.log("✅ Portal loaded")
    await ctx.snap("portal_loaded")


async def _step_fill_credentials(ctx: Ctx) -> None:
    user_loc = await ctx.first_visible([
        "input[name*='user' i]:not([type='password'])", "input[id*='user' i]:not([type='password'])",
        "input[name='username']", "input#username",
        "input[type='text']:not([id*='captcha' i]):not([name*='captcha' i])",
    ])
    if not user_loc:
        raise RuntimeError("Could not find the User ID field — portal layout may have changed.")
    await ctx.type(user_loc, ctx.creds["user_name"], "User ID")
    pass_loc = await ctx.first_visible([
        "input[type='password']", "input[name*='pass' i]", "input[id*='pass' i]",
    ])
    if not pass_loc:
        raise RuntimeError("Could not find the Password field.")
    await ctx.type(pass_loc, ctx.creds["password"], "Password", secret=True)
    ctx.log("✅ Credentials entered")


async def _step_captcha_and_login(ctx: Ctx) -> None:
    from utils.rpa_worker import (
        _find_captcha_image_b64, _fill_captcha_input, _click_login_submit,
        _reload_captcha, _login_succeeded,
    )
    from utils.captcha_reader import read_captcha
    numeric = ctx.s["portal"] == "esic"
    max_auto = min(3, ctx.settings["retry_count"])
    backoff = [5, 15, 30]  # security req #5 — exponential backoff, max 3 retries

    for attempt in range(1, max_auto + 2):
        await ctx.gate()
        if attempt > 1:
            wait_s = backoff[min(attempt - 2, len(backoff) - 1)]
            ctx.log(f"⏳ Backing off {wait_s}s before retry (responsible pacing)…")
            await ctx.sleep(wait_s / max(ctx.mult, 1.0))
        cap_b64 = await _find_captcha_image_b64(ctx.page)
        if not cap_b64:
            ctx.log("No captcha on this form — signing in…")
            await _click_login_submit(ctx.page)
            await ctx.sleep(3.0)
            return
        text: Optional[str] = None
        if attempt <= max_auto and not ctx.settings.get("training_mode"):
            ctx.log(f"🤖 Reading captcha with AI vision (try {attempt}/{max_auto})…")
            text = await read_captcha(cap_b64, numeric_only=numeric,
                                      session_id=f"rpa-{ctx.sid}-{attempt}")
        if not text:
            # Hand over to the human — never bypass, never guess forever.
            text = await ctx.wait_user_input(
                "captcha", "Type the captcha characters shown in the image",
                image_b64=cap_b64)
            if not text:
                # user hit retry/skip — refresh captcha and loop
                await _reload_captcha(ctx.page)
                await ctx.sleep(1.0)
                continue
        ctx.log(f"Captcha entered: {text}")
        cap_loc = await ctx.first_visible([
            "input[name*='captcha' i]", "input[id*='captcha' i]",
            "input[placeholder*='captcha' i]",
        ])
        if cap_loc:
            await ctx.type(cap_loc, text, "Captcha")
        else:
            await _fill_captcha_input(ctx.page, text)
        submit_loc = await ctx.first_visible([
            "button[type='submit']", "input[type='submit']",
            "button:has-text('Sign')", "button:has-text('Login')",
            "a:has-text('Login')",
        ])
        if submit_loc:
            await ctx.click(submit_loc, "Sign In")
        else:
            await _click_login_submit(ctx.page)
        await ctx.sleep(3.2)
        if await _login_succeeded(ctx.page):
            ctx.log("🎉 Login successful")
            await ctx.audit("login_success", ctx.s["portal_label"])
            await ctx.snap("login_success")
            return
        ctx.log(f"Sign-in not confirmed (try {attempt}) — refreshing captcha…", "warn")
        await ctx.snap(f"login_attempt_{attempt}")
        await _reload_captcha(ctx.page)
        await ctx.sleep(1.0)
    raise RuntimeError("Could not confirm login — captcha may be wrong or credentials invalid.")


async def _step_verify_login(ctx: Ctx) -> None:
    from utils.rpa_worker import _login_succeeded
    if not await _login_succeeded(ctx.page):
        raise RuntimeError("Login could not be verified — still on the sign-in page.")
    ctx.log("✅ Login verified")


async def _step_dashboard(ctx: Ctx) -> None:
    await ctx.sleep(1.5)
    await ctx.snap("dashboard")
    ctx.log("📸 Dashboard captured")


async def _step_review_confirm(ctx: Ctx) -> None:
    """Mandatory human checkpoint before anything is submitted to a
    government portal."""
    await ctx.snap("review_before_submit")
    val = await ctx.wait_user_input(
        "confirm",
        "Review the filled form in the live view. Type YES to submit, or "
        "press Skip Step to stop before submission.")
    if val.strip().lower() not in ("yes", "y", "ok", "confirm"):
        raise RuntimeError("Submission not confirmed by user.")
    ctx.log("✅ Submission confirmed by user")


async def _step_capture_ack(ctx: Ctx) -> None:
    await ctx.sleep(2.0)
    await ctx.snap("acknowledgement")
    ctx.log("📸 Acknowledgement captured — check Screenshots on this job.")


# ---- EPFO Generate UAN -----------------------------------------------------
_EPFO_NAV = ["Register Individual", "REGISTER INDIVIDUAL", "Member Registration"]


async def _step_epfo_open_registration(ctx: Ctx) -> None:
    mem = ctx.page.get_by_text("Member", exact=False).first
    try:
        if await mem.count() > 0:
            await ctx.click(mem, "Member menu")
            await ctx.sleep(1.0)
    except Exception:
        pass
    for txt in _EPFO_NAV:
        try:
            loc = ctx.page.get_by_text(txt, exact=False).first
            if await loc.count() > 0:
                await ctx.click(loc, f"'{txt}'")
                await ctx.sleep(2.0)
                await ctx.snap("member_registration_page")
                ctx.log("✅ Member Registration page opened")
                return
        except Exception:
            continue
    raise RuntimeError("Could not open Member → Register Individual — the portal "
                       "menu may have changed.")


async def _fill_mapped_fields(ctx: Ctx, mapping: List[Tuple[str, List[str], Any]]) -> int:
    filled = 0
    for label, selectors, value in mapping:
        if value in (None, ""):
            continue
        loc = await ctx.first_visible(selectors)
        if not loc:
            ctx.log(f"Field not found on portal: {label}", "warn")
            continue
        await ctx.type(loc, str(value), label)
        filled += 1
    return filled


async def _step_epfo_fill_member(ctx: Ctx) -> None:
    e = ctx.s["employee"] or {}
    mapping = [
        ("Aadhaar", ["input[name*='aadhaar' i]", "input[id*='aadhaar' i]",
                     "input[name*='documentNumber' i]"], e.get("aadhaar")),
        ("Name", ["input[name*='memberName' i]", "input[id*='memberName' i]",
                  "input[name*='name' i]:not([name*='father' i]):not([name*='user' i])"], e.get("name")),
        ("Father Name", ["input[name*='father' i]", "input[id*='father' i]"], e.get("father_name")),
        ("Date of Birth", ["input[name*='dob' i]", "input[id*='dob' i]",
                           "input[name*='birth' i]"], e.get("dob")),
        ("Mobile", ["input[name*='mobile' i]", "input[id*='mobile' i]"], e.get("mobile")),
        ("Email", ["input[name*='email' i]", "input[id*='email' i]"], e.get("email")),
        ("Date of Joining", ["input[name*='doj' i]", "input[id*='doj' i]",
                             "input[name*='joining' i]"], e.get("doj")),
        ("Monthly Salary", ["input[name*='wages' i]", "input[id*='wages' i]",
                            "input[name*='salary' i]"], e.get("salary")),
    ]
    filled = await _fill_mapped_fields(ctx, mapping)
    # Gender is usually a <select>
    if e.get("gender"):
        sel = await ctx.first_visible(["select[name*='gender' i]", "select[id*='gender' i]"])
        if sel:
            await ctx.highlight(sel)
            try:
                await sel.select_option(label=str(e["gender"]).capitalize(), timeout=3000)
                filled += 1
                ctx.log(f"Selected Gender: {e['gender']}")
            except Exception:
                ctx.log("Could not select Gender automatically", "warn")
            await ctx._unhighlight(sel)
    await ctx.snap("member_form_filled")
    if filled == 0:
        raise RuntimeError("No form fields matched — portal layout changed. "
                           "Complete manually in the live view or Retry.")
    ctx.log(f"✅ Filled {filled} field(s) from the Employee Master")


async def _step_epfo_submit(ctx: Ctx) -> None:
    btn = await ctx.first_visible([
        "button:has-text('Save')", "input[value*='Save' i]",
        "button:has-text('Submit')", "input[type='submit']",
    ])
    if not btn:
        raise RuntimeError("Save/Submit button not found.")
    await ctx.click(btn, "Save / Submit")
    await ctx.sleep(3.0)
    # OTP gate — EPFO frequently asks for an OTP on the registered mobile.
    otp_loc = await ctx.first_visible([
        "input[name*='otp' i]", "input[id*='otp' i]", "input[placeholder*='otp' i]",
    ])
    if otp_loc:
        otp = await ctx.wait_user_input(
            "otp", "An OTP was sent by the portal — enter it to continue")
        if otp:
            await ctx.type(otp_loc, otp, "OTP")
            ver = await ctx.first_visible([
                "button:has-text('Verify')", "button:has-text('Submit')",
                "input[type='submit']",
            ])
            if ver:
                await ctx.click(ver, "Verify OTP")
            await ctx.sleep(3.0)
    ctx.log("✅ Registration submitted")


# ---- ESIC IP Registration ---------------------------------------------------
_ESIC_NAV = ["Register New IP", "REGISTER NEW IP", "IP Registration",
             "Register new Insured Person"]


async def _step_esic_open_registration(ctx: Ctx) -> None:
    for txt in _ESIC_NAV:
        try:
            loc = ctx.page.get_by_text(txt, exact=False).first
            if await loc.count() > 0:
                await ctx.click(loc, f"'{txt}'")
                await ctx.sleep(2.0)
                await ctx.snap("ip_registration_page")
                ctx.log("✅ IP Registration page opened")
                return
        except Exception:
            continue
    raise RuntimeError("Could not open 'Register New IP' — the ESIC menu may have changed.")


async def _step_esic_fill_member(ctx: Ctx) -> None:
    e = ctx.s["employee"] or {}
    mapping = [
        ("Name", ["input[name*='ipname' i]", "input[id*='ipname' i]",
                  "input[name*='name' i]:not([name*='father' i]):not([name*='user' i])"], e.get("name")),
        ("Father Name", ["input[name*='father' i]", "input[id*='father' i]"], e.get("father_name")),
        ("Date of Birth", ["input[name*='dob' i]", "input[id*='dob' i]"], e.get("dob")),
        ("Mobile", ["input[name*='mobile' i]", "input[id*='mobile' i]"], e.get("mobile")),
        ("Aadhaar", ["input[name*='aadhaar' i]", "input[id*='aadhaar' i]"], e.get("aadhaar")),
        ("Date of Appointment", ["input[name*='appointment' i]", "input[id*='appointment' i]",
                                 "input[name*='doj' i]"], e.get("doj")),
        ("Monthly Wages", ["input[name*='wages' i]", "input[id*='wages' i]"], e.get("salary")),
        ("Address", ["textarea[name*='address' i]", "input[name*='address' i]"], e.get("address")),
    ]
    filled = await _fill_mapped_fields(ctx, mapping)
    await ctx.snap("ip_form_filled")
    if filled == 0:
        raise RuntimeError("No ESIC form fields matched — portal layout changed.")
    ctx.log(f"✅ Filled {filled} field(s) from the Employee Master")


async def _step_esic_submit(ctx: Ctx) -> None:
    btn = await ctx.first_visible([
        "button:has-text('Submit')", "input[value*='Submit' i]",
        "input[type='submit']", "button:has-text('Save')",
    ])
    if not btn:
        raise RuntimeError("Submit button not found.")
    await ctx.click(btn, "Submit")
    await ctx.sleep(3.0)
    ctx.log("✅ Registration submitted")


# ---- Compliance Studio steps (ECR / Contribution uploads) -------------------
async def _step_generate_file(ctx: Ctx) -> None:
    """Server-side: build the PF ECR TXT / ESIC contribution CSV from the
    selected Compliance Salary Process and store it for the upload step."""
    from utils.statutory_bulk import build_pf_ecr_txt, build_esic_mc_csv
    run = ctx.c.get("run") or {}
    rows = run.get("rows") or run.get("lines") or []
    month = run.get("month") or "month"
    v = ctx.s.get("validation") or {}
    ctx.log(f"🧮 Validation: {v.get('included', 0)} of {v.get('employee_count', 0)} "
            f"employees included · wages ₹{v.get('total_wages', 0):,.0f}")
    for w in (v.get("warnings") or []):
        ctx.log(f"⚠ {w}", "warn")
    if ctx.s["portal"] == "epfo":
        body = build_pf_ecr_txt(rows)
        fname = f"PF_ECR_{month}.txt"
    else:
        body = build_esic_mc_csv(rows)
        fname = f"ESIC_MC_{month}.csv"
    if not body.strip():
        raise RuntimeError("Generated file is empty — no eligible employees.")
    fpath = ctx.media_dir() / fname
    fpath.write_bytes(body)
    ctx.c["upload_file"] = str(fpath)
    ctx.s["downloads"].append({"tag": "generated_file", "file": fname, "at": _now_iso()})
    await ctx.audit("file_generated", fname)
    ctx.log(f"📄 {fname} generated ({len(body.splitlines())} line(s))")


_UPLOAD_NAV = {
    "epfo": ["ECR/Return Filing", "ECR/RETURN FILING", "ECR Upload",
             "ECR UPLOAD", "Payments (ECR)"],
    "esic": ["Online Monthly Contribution", "File Monthly Contribution",
             "Upload Excel", "Monthly Contribution", "Bulk Upload"],
}


async def _step_open_upload_page(ctx: Ctx) -> None:
    for txt in _UPLOAD_NAV.get(ctx.s["portal"], []):
        try:
            loc = ctx.page.get_by_text(txt, exact=False).first
            if await loc.count() > 0:
                await ctx.click(loc, f"'{txt}'")
                await ctx.sleep(2.2)
                await ctx.snap("upload_page")
                ctx.log("✅ Upload page opened")
                return
        except Exception:
            continue
    raise RuntimeError("Could not open the upload page — the portal menu may have changed.")


async def _step_upload_file(ctx: Ctx) -> None:
    fpath = ctx.c.get("upload_file")
    if not fpath or not os.path.exists(fpath):
        raise RuntimeError("Generated file missing — rerun the Generate File step.")
    file_input = None
    for sel in ("input[type='file']",):
        try:
            loc = ctx.page.locator(sel).first
            if await loc.count() > 0:
                file_input = loc
                break
        except Exception:
            continue
    if not file_input:
        # Some portals hide the input behind a "Browse" button.
        browse = await ctx.first_visible(
            ["button:has-text('Browse')", "label:has-text('Choose')",
             "button:has-text('Choose File')"])
        if browse:
            await ctx.click(browse, "Browse")
            file_input = ctx.page.locator("input[type='file']").first
    if not file_input or await file_input.count() == 0:
        raise RuntimeError("File upload field not found on this page.")
    ctx.log(f"📤 Uploading {Path(fpath).name} …")
    await file_input.set_input_files(fpath, timeout=ctx.timeout_ms)
    await ctx.sleep(1.0)
    up_btn = await ctx.first_visible(
        ["button:has-text('Upload')", "input[value*='Upload' i]",
         "button[type='submit']", "input[type='submit']"])
    if up_btn:
        await ctx.click(up_btn, "Upload")
    await ctx.sleep(3.0)
    await ctx.snap("file_uploaded")
    await ctx.audit("file_uploaded", Path(fpath).name)
    ctx.log("✅ File uploaded")


async def _step_verify_summary(ctx: Ctx) -> None:
    """Show the portal's summary screen and require human verification
    against the payroll validation numbers before continuing."""
    await ctx.sleep(1.5)
    await ctx.snap("portal_summary")
    v = ctx.s.get("validation") or {}
    val = await ctx.wait_user_input(
        "confirm",
        f"Verify the portal summary matches payroll: {v.get('included', 0)} "
        f"employees, wages ₹{v.get('total_wages', 0):,.0f}. Type YES to continue.")
    if val.strip().lower() not in ("yes", "y", "ok", "confirm"):
        raise RuntimeError("Summary not confirmed by user.")
    ctx.log("✅ Summary verified by user")


async def _safe_click_by_texts(ctx: Ctx, texts: List[str], what: str) -> bool:
    for txt in texts:
        try:
            loc = ctx.page.get_by_text(txt, exact=False).first
            if await loc.count() > 0 and await loc.is_visible():
                label = (await loc.inner_text() or "").lower()
                if any(b in label for b in _PAYMENT_BLOCKLIST):
                    ctx.log(f"🛡 Skipping '{txt}' — payment-related button blocked "
                            "by safety rail", "warn")
                    continue
                await ctx.click(loc, f"'{txt}'")
                await ctx.sleep(2.5)
                return True
        except Exception:
            continue
    ctx.log(f"Could not find a {what} button automatically", "warn")
    return False


async def _step_generate_trrn(ctx: Ctx) -> None:
    ok = await _safe_click_by_texts(
        ctx, ["Verify", "Generate TRRN", "TRRN", "Proceed"], "Generate TRRN")
    await ctx.snap("trrn")
    if not ok:
        val = await ctx.wait_user_input(
            "confirm", "Click Generate TRRN manually is not possible in stream "
            "mode — type YES once the TRRN is visible on screen, or Skip Step.")
        if val.strip().lower() not in ("yes", "y", "ok"):
            raise RuntimeError("TRRN generation not confirmed.")
    ctx.log("✅ TRRN step complete")


async def _step_generate_challan(ctx: Ctx) -> None:
    val = await ctx.wait_user_input(
        "confirm", "About to GENERATE the challan (payment is NEVER clicked). "
        "Type YES to continue.")
    if val.strip().lower() not in ("yes", "y", "ok", "confirm"):
        raise RuntimeError("Challan generation not confirmed by user.")
    await _safe_click_by_texts(
        ctx, ["Prepare Challan", "Generate Challan", "Challan", "Finalize"],
        "Generate Challan")
    await ctx.snap("challan")
    await ctx.audit("challan_generated", "payment NOT initiated (safety rail)")
    ctx.log("✅ Challan step complete — payment NOT initiated (safety rail)")


async def _step_download_documents(ctx: Ctx) -> None:
    """Click every visible download link for challan/receipt/ack PDFs.
    Files are captured by the page 'download' handler into the job folder,
    then AUTO-ATTACHED to the monthly Challan Summary."""
    texts = ["Download Challan", "Challan Receipt", "Download PDF", "Download",
             "Print Challan", "Acknowledgement", "Receipt", "ECR PDF"]
    got = 0
    for txt in texts:
        try:
            loc = ctx.page.get_by_text(txt, exact=False).first
            if await loc.count() > 0 and await loc.is_visible():
                label = (await loc.inner_text() or "").lower()
                if any(b in label for b in _PAYMENT_BLOCKLIST):
                    continue
                await ctx.click(loc, f"'{txt}'")
                await ctx.sleep(3.0)
                got += 1
        except Exception:
            continue
    await ctx.snap("downloads")
    # Auto-attach downloaded PDFs to the monthly Challan Summary.
    await _auto_attach_challans(ctx)
    dl = len(ctx.s.get("downloads") or [])
    ctx.log(f"⬇ Download step done — {dl} file(s) captured on this job")
    if got == 0 and dl <= 1:
        ctx.log("No download links matched — save manually if needed", "warn")


async def _auto_attach_challans(ctx: Ctx) -> None:
    """Insert challan PDFs downloaded by the automation into ``db.challans``
    for this firm+month+portal so they appear on the Challans screen AND
    the Monthly Challan Summary automatically (user request Iter 235)."""
    import base64 as _b64
    month = ctx.s.get("run_month")
    if not month:
        return
    portal = "pf" if ctx.s["portal"] == "epfo" else "esic"
    dl_dir = MEDIA_ROOT / ctx.s["job_id"] / "downloads"
    if not dl_dir.exists():
        return
    attached = 0
    for f in sorted(dl_dir.glob("*")):
        if f.suffix.lower() != ".pdf" or not f.is_file():
            continue
        # Idempotency: don't attach the same filename twice for this job.
        exists = await ctx.db.challans.find_one(
            {"company_id": ctx.s["company_id"], "month": month, "portal": portal,
             "rpa_job_id": ctx.s["job_id"], "file_name": f.name},
            {"_id": 1})
        if exists:
            continue
        try:
            b64 = _b64.b64encode(f.read_bytes()).decode("ascii")
        except Exception:
            continue
        await ctx.db.challans.insert_one({
            "challan_id": f"chl_{uuid.uuid4().hex[:12]}",
            "company_id": ctx.s["company_id"],
            "portal": portal,
            "month": month,
            "amount": float((ctx.s.get("validation") or {}).get("total_contribution") or 0),
            "trrn": None,
            "paid_on": None,
            "notes": f"Auto-attached by Compliance Automation Studio "
                     f"({ctx.s['flow_label']})",
            "file_base64": b64,
            "file_mime": "application/pdf",
            "file_name": f.name,
            "source": "rpa_auto",
            "rpa_job_id": ctx.s["job_id"],
            "created_by": "system:rpa",
            "created_at": _now_iso(),
        })
        attached += 1
    if attached:
        await ctx.audit("challan_attached", f"{attached} PDF(s) → Challan Summary {month}")
        ctx.log(f"📎 Auto-attached {attached} challan PDF(s) to the "
                f"{month} Challan Summary")


def _mk_nav_step(texts: List[str]) -> Callable:
    async def _nav(ctx: Ctx) -> None:
        for txt in texts:
            try:
                loc = ctx.page.get_by_text(txt, exact=False).first
                if await loc.count() > 0 and await loc.is_visible():
                    await ctx.click(loc, f"'{txt}'")
                    await ctx.sleep(2.0)
                    await ctx.snap("page_opened")
                    return
            except Exception:
                continue
        ctx.log("Menu item not found — staying on the current page", "warn")
    return _nav


async def _step_assist_hold(ctx: Ctx) -> None:
    """Keep the live session open so the admin can watch/verify. Ends when
    the user types DONE (or presses Skip/Stop)."""
    await ctx.snap("assisted_view")
    await ctx.wait_user_input(
        "confirm", "Assisted live session — watch the portal above. "
        "Type DONE to finish this job.")
    ctx.log("✅ Assisted session finished")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
async def _frame_loop(sid: str, page) -> None:
    """Capture a live JPEG frame ~every second while the session runs."""
    s = _SESSIONS.get(sid)
    while s and s["status"] not in ("completed", "failed", "stopped"):
        try:
            shot = await page.screenshot(type="jpeg", quality=45)
            s["frame_b64"] = base64.b64encode(shot).decode("ascii")
            s["current_url"] = page.url
            s["network"] = "online"
        except Exception:
            pass
        await asyncio.sleep(1.0)
        s = _SESSIONS.get(sid)


async def _persist_job(db, sid: str) -> None:
    s = _SESSIONS.get(sid)
    if not s:
        return
    doc = {k: v for k, v in s.items() if k not in ("frame_b64", "captcha_b64")}
    doc["logs"] = s["logs"][-200:]
    await db.portal_rpa_jobs.update_one(
        {"job_id": s["job_id"]}, {"$set": doc}, upsert=True)


async def _run_session(db, sid: str) -> None:
    s, c = _SESSIONS[sid], _CTRL[sid]
    steps = _flow_steps(s["flow"])
    total = len(steps)
    browser = None
    page = None
    frame_task = None
    try:
        try:
            from playwright.async_api import async_playwright
        except Exception:
            raise RuntimeError("Playwright browser engine unavailable on the server.")
        _log(sid, "🚀 Launching Chrome…")
        async with async_playwright() as pw:
            launch_kw: Dict[str, Any] = {"headless": True,
                                         "args": ["--start-maximized"]}
            proxy_url = (os.environ.get("PORTAL_PROXY_URL") or "").strip()
            if proxy_url:
                launch_kw["proxy"] = {"server": proxy_url}
            browser = await pw.chromium.launch(**launch_kw)
            c["browser"] = browser
            media_dir = MEDIA_ROOT / s["job_id"]
            media_dir.mkdir(parents=True, exist_ok=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                accept_downloads=True,
                record_video_dir=str(media_dir),
                record_video_size={"width": 1280, "height": 800},
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0 Safari/537.36"),
            )
            page = await context.new_page()

            # Download manager — every portal download lands in the job
            # folder and is indexed on the session/history doc.
            async def _save_dl(download) -> None:
                try:
                    fname = download.suggested_filename or f"file_{len(s['downloads'])}"
                    dest = media_dir / "downloads"
                    dest.mkdir(exist_ok=True)
                    await download.save_as(str(dest / fname))
                    s["downloads"].append(
                        {"tag": "portal_download", "file": f"downloads/{fname}",
                         "at": _now_iso()})
                    _log(sid, f"⬇ Downloaded: {fname}")
                except Exception as exc:  # noqa: BLE001
                    _log(sid, f"Download save failed: {exc}", "warn")

            page.on("download",
                    lambda d: asyncio.get_event_loop().create_task(_save_dl(d)))
            s["browser"] = "running"
            s["status"] = "running"
            _log(sid, "✅ Chrome started")
            frame_task = asyncio.get_event_loop().create_task(_frame_loop(sid, page))
            await _persist_job(db, sid)

            ctx = Ctx(db, sid, page)
            await ctx.audit("session_start",
                            f"{s['flow_label']} on {s['portal_label']}")
            i = 0
            done = 0
            t0 = datetime.now(timezone.utc)
            while i < total:
                await ctx.gate()
                if c.get("previous"):
                    c["previous"] = False
                    i = max(0, i - 1)
                    s["steps"][i]["status"] = "pending"
                    done = max(0, done - 1)
                    _log(sid, f"⏮ Rewinding to step {i + 1}")
                name, fn = steps[i]
                s["current_step"] = i
                s["steps"][i]["status"] = "running"
                s["steps"][i]["started_at"] = _now_iso()
                _log(sid, f"▶ Step {i + 1}/{total}: {name}")
                c["retry"] = False
                c["skip"] = False
                try:
                    await fn(ctx)
                    s["steps"][i]["status"] = "done"
                except _Stop:
                    raise
                except Exception as exc:
                    if c["skip"]:
                        s["steps"][i]["status"] = "skipped"
                        _log(sid, f"⏭ Step skipped: {name}", "warn")
                        i += 1
                        continue
                    # Error dossier: screenshot + html + url
                    s["steps"][i]["status"] = "failed"
                    s["steps"][i]["error"] = str(exc)
                    s["error"] = str(exc)
                    try:
                        await ctx.snap(f"error_{name}")
                        html = await page.content()
                        (media_dir / f"error_{i:02d}.html").write_text(html[:800_000])
                    except Exception:
                        pass
                    _log(sid, f"❌ Step failed: {exc}", "error")
                    # Wait for the user's decision: Retry / Skip / Stop.
                    decision = await ctx.wait_user_input(
                        "decision",
                        f"Step '{name}' failed. Press Retry, Skip Step or Stop.")
                    if c["stop"]:
                        raise _Stop()
                    if c.get("previous"):
                        c["previous"] = False
                        s["steps"][i]["status"] = "pending"
                        i = max(0, i - 1)
                        s["steps"][i]["status"] = "pending"
                        done = max(0, done - 1)
                        continue
                    if c["skip"]:
                        s["steps"][i]["status"] = "skipped"
                        i += 1
                        continue
                    # default (retry pressed or any text) → retry the step
                    s["steps"][i]["status"] = "pending"
                    s["error"] = None
                    _ = decision
                    continue
                s["steps"][i]["ended_at"] = _now_iso()
                done += 1
                i += 1
                s["progress"] = int(done / total * 100)
                elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
                if done:
                    s["eta_sec"] = int(elapsed / done * (total - done))
                await _persist_job(db, sid)

            s["status"] = "completed"
            s["progress"] = 100
            _log(sid, "🏁 Automation completed")
    except _Stop:
        s["status"] = "stopped"
        _log(sid, "⏹ Automation stopped")
    except Exception as exc:  # noqa: BLE001
        s["status"] = "failed"
        s["error"] = str(exc)
        _log(sid, f"❌ Automation failed: {exc}", "error")
    finally:
        s["ended_at"] = _now_iso()
        if frame_task:
            frame_task.cancel()
        # Save the session video (Playwright finalises it on context close).
        video_path = None
        try:
            if page is not None:
                v = page.video
                if v:
                    video_path = await v.path()
        except Exception:
            pass
        try:
            if browser is not None:
                await browser.close()
        except Exception:
            pass
        if video_path and os.path.exists(video_path):
            dest = MEDIA_ROOT / s["job_id"] / "session.webm"
            try:
                if str(dest) != str(video_path):
                    shutil.move(video_path, dest)
                s["video"] = "session.webm"
            except Exception:
                pass
        try:
            await _persist_job(db, sid)
            await db.rpa_audit.insert_one({
                "at": _now_iso(), "session_id": sid, "job_id": s["job_id"],
                "company_id": s["company_id"], "portal": s["portal"],
                "event": "session_end", "detail": s["status"]})
        except Exception:
            pass

