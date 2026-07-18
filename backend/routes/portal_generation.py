"""Iter 89 — Portal Automation: per-employee UAN / ESIC generation.

Two focused endpoints exposed on the Employee Master screen:

  * POST /api/admin/employees/{user_id}/generate-uan   - EPFO UAN queue
  * POST /api/admin/employees/{user_id}/generate-esic  - ESIC IP queue

Both endpoints:
  * Verify the caller is a company_admin/super_admin scoped to the
    employee's firm.
  * Ensure the firm's Portal Logins for the target portal are on file
    (looked up from the Firm Master doc). If missing, the endpoint
    returns a 412 so the UI can nudge the admin to fill them.
  * Persist a job in ``portal_automation_jobs`` with a distinctive
    ``action_type`` so the existing /portal-automation page can render
    per-employee generation runs alongside the older salary uploads.

The actual EPFO/ESIC browser automation (login → search / register →
capture UAN → write back to employee) is left to a background worker
that consumes ``pending`` jobs — this MVP focuses on the intent capture
and status feedback so admins have a single-click workflow from the
Employee Master screen.
"""
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    logger,
)


router = APIRouter(prefix="/api/admin", tags=["portal-generation"])


async def _load_employee_scoped(user_id: str, admin: Dict[str, Any]) -> Dict[str, Any]:
    emp = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "pin_hash": 0, "password_hash": 0, "face_reference_base64": 0},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin":
        if emp.get("company_id") != admin.get("company_id"):
            raise HTTPException(status_code=403, detail="Not your firm's employee")
    if admin["role"] == "sub_admin":
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, emp.get("company_id")):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    return emp


async def _portal_creds_present(company_id: str, portal_key: str) -> bool:
    """Credentials live on Firm Master. Iter 98 — the EPF Detail / ESIC
    Detail sections (epf_user_id/epf_password, esi_user_id/esi_password)
    are checked FIRST; the legacy Portal Logins rows ('PF LOGIN' /
    'ESI Login') act as a fallback."""
    master = await db.firm_masters.find_one(
        {"company_id": company_id},
        {"_id": 0, "portal_logins": 1, "epf": 1, "esi": 1},
    )
    if not master:
        return False
    if portal_key == "epfo":
        sec = master.get("epf") or {}
        if (sec.get("epf_user_id") or "").strip() and (sec.get("epf_password") or "").strip():
            return True
    elif portal_key == "esic":
        sec = master.get("esi") or {}
        if (sec.get("esi_user_id") or "").strip() and (sec.get("esi_password") or "").strip():
            return True
    lookup = {
        "epfo": "PF LOGIN",
        "esic": "ESI Login",
    }
    label = lookup.get(portal_key)
    for row in (master.get("portal_logins") or []):
        if row.get("login_type") == label:
            return bool((row.get("user_name") or "").strip()
                        and (row.get("password") or "").strip())
    return False


def _require_aadhaar(emp: Dict[str, Any], what: str) -> None:
    """Iter 91 — Only Aadhaar is mandatory to queue a generation job."""
    aadhaar = (emp.get("aadhaar_no") or emp.get("aadhar_number") or "").strip()
    if not aadhaar:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Aadhaar number is mandatory to generate {what}. "
                "Add the Aadhaar number on the employee's KYC and try again."
            ),
        )


async def _queue_generation_job(
    *,
    portal: str,        # "epfo" | "esic"
    action_type: str,   # "generate_uan" | "generate_esic"
    admin: Dict[str, Any],
    employee: Dict[str, Any],
    creds_present: bool = True,
) -> Dict[str, Any]:
    job_id = f"paj_{uuid.uuid4().hex[:12]}"
    job = {
        "job_id": job_id,
        "portal": portal,
        "action_type": action_type,
        "company_id": employee.get("company_id"),
        "employee_user_id": employee["user_id"],
        "employee_snapshot": {
            "name": employee.get("name"),
            "father_name": employee.get("father_name"),
            "mother_name": employee.get("mother_name"),
            "dob": employee.get("dob"),
            "gender": employee.get("gender"),
            "marital_status": employee.get("marital_status"),
            "aadhaar_no": employee.get("aadhaar_no") or employee.get("aadhar_number"),
            "pan_no": employee.get("pan_no") or employee.get("pan_number"),
            "phone": employee.get("phone"),
            "email": employee.get("email"),
            "doj": employee.get("doj"),
            "employee_code": employee.get("employee_code"),
        },
        # Iter 91 — no portal creds is no longer a blocker: the job is
        # queued straight into manual_required so the ops admin can
        # complete it on the government portal and write the number back.
        "status": "pending" if creds_present else "manual_required",
        "steps": [] if creds_present else [{
            "at": now_iso(),
            "note": (
                "Portal credentials missing on Firm Master — automation "
                "skipped. Complete manually and use Manual Complete."
            ),
        }],
        "created_by": admin["user_id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.portal_automation_jobs.insert_one(job)
    logger.info(
        "[portal-gen] queued %s job=%s employee=%s by %s",
        action_type, job_id, employee["user_id"], admin["user_id"],
    )
    job.pop("_id", None)
    return job


@router.post("/employees/{user_id}/generate-uan")
async def generate_uan(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    emp = await _load_employee_scoped(user_id, admin)

    # If a UAN is already on file we short-circuit — no need to re-run.
    if (emp.get("uan_no") or "").strip():
        return {
            "ok": True,
            "already_present": True,
            "uan_no": emp["uan_no"],
            "message": "Employee already has a UAN on file.",
        }

    company_id = emp.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="Employee not linked to a firm")

    _require_aadhaar(emp, "a PF UAN")
    creds = await _portal_creds_present(company_id, "epfo")

    job = await _queue_generation_job(
        portal="epfo",
        action_type="generate_uan",
        admin=admin,
        employee=emp,
        creds_present=creds,
    )
    return {
        "ok": True, "job": job,
        "message": (
            "UAN generation queued. Track progress on Portal Automation."
            if creds else
            "UAN job queued in MANUAL mode — EPFO portal credentials are "
            "missing on Firm Master, so complete it on the portal and use "
            "Manual Complete on the Portal Automation screen."
        ),
    }


@router.post("/employees/{user_id}/generate-esic")
async def generate_esic(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    emp = await _load_employee_scoped(user_id, admin)

    if (emp.get("esi_ip_no") or "").strip():
        return {
            "ok": True,
            "already_present": True,
            "esi_ip_no": emp["esi_ip_no"],
            "message": "Employee already has an ESIC IP number on file.",
        }

    company_id = emp.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="Employee not linked to a firm")

    _require_aadhaar(emp, "an ESIC IP number")
    creds = await _portal_creds_present(company_id, "esic")

    job = await _queue_generation_job(
        portal="esic",
        action_type="generate_esic",
        admin=admin,
        employee=emp,
        creds_present=creds,
    )
    return {
        "ok": True, "job": job,
        "message": (
            "ESIC generation queued. Track progress on Portal Automation."
            if creds else
            "ESIC job queued in MANUAL mode — ESIC portal credentials are "
            "missing on Firm Master, so complete it on the portal and use "
            "Manual Complete on the Portal Automation screen."
        ),
    }


# ---------------------------------------------------------------------------
# Iter 89 — Manual completion: ops admin obtains the UAN / ESIC number
# from the government portal manually (captcha + OTP flow) and writes it
# back to the app via this endpoint. The endpoint updates BOTH the
# employee record AND the portal_automation_jobs row.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Iter 96h — AI-captcha auto-login test. Runs the Playwright login flow for a
# firm's EPFO/ESIC portal RIGHT NOW (reading the captcha with the AI-vision
# reader) and returns the outcome + a screenshot so the admin can see it work.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Iter 96i — Remote captcha read for the ON-PREMISE EPFO/ESIC runner.
# The office PC (allowed Indian ISP IP) screenshots the portal captcha and
# POSTs it here; the server reads it with the AI-vision reader (keeps the
# Emergent LLM key on the server, never on the office machine).
# ---------------------------------------------------------------------------
@router.post("/portal-automation/read-captcha")
async def read_portal_captcha(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    image_b64 = (payload.get("image_base64") or "").strip()
    if not image_b64:
        raise HTTPException(status_code=400, detail="image_base64 is required")
    numeric_only = bool(payload.get("numeric_only"))

    from utils.captcha_reader import read_captcha

    text = await read_captcha(
        image_b64, numeric_only=numeric_only, session_id=admin["user_id"],
    )
    if not text:
        raise HTTPException(
            status_code=422,
            detail="Could not read the captcha — try refreshing it and send again.",
        )
    return {"ok": True, "text": text}


@router.post("/portal-automation/test-login")
async def test_portal_login(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    portal = (payload.get("portal") or "").lower()
    if portal not in ("epfo", "esic"):
        raise HTTPException(status_code=400, detail="portal must be 'epfo' or 'esic'")

    company_id = payload.get("company_id")
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if admin["role"] == "sub_admin" and company_id:
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")

    from utils.rpa_worker import _fetch_creds, _perform_login

    creds = await _fetch_creds(db, company_id, portal)
    if not creds:
        raise HTTPException(
            status_code=412,
            detail=(
                f"No {portal.upper()} login saved on Firm Master → Portal Logins. "
                "Add the username & password there first."
            ),
        )

    logger.info("[portal-gen] test-login portal=%s company=%s by %s",
                portal, company_id, admin["user_id"])
    result = await _perform_login(portal, creds["login_url"], creds)
    return {
        "ok": bool(result.get("ok")),
        "status": result.get("status"),
        "message": result.get("message"),
        "captcha_attempts": result.get("captcha_attempts", 0),
        "screenshot_base64": result.get("screenshot_b64"),
    }


@router.get("/portal-automation/esic-credentials")
async def get_esic_credentials(
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Return the firm's saved ESIC User ID + Password so the Test screen
    can auto-fill / copy them when opening the portal in a new tab. Role-
    gated to admins scoped to the firm (they entered these themselves)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if admin["role"] == "sub_admin" and company_id:
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")

    from utils.rpa_worker import _fetch_creds

    creds = await _fetch_creds(db, company_id, "esic")
    if not creds:
        raise HTTPException(
            status_code=412,
            detail=(
                "No ESIC User ID / Password saved on Firm Master → ESIC Detail. "
                "Add them there first."
            ),
        )
    return {
        "ok": True,
        "user_id": creds.get("user_name") or "",
        "password": creds.get("password") or "",
        "login_url": creds.get("login_url") or "",
    }


@router.post("/portal-automation/live-login/start")
async def start_live_login_endpoint(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Start a server-side Playwright auto-login the UI can watch live.
    Fetches the firm's saved User ID/Password, reads the captcha with AI
    vision and signs in — returns a session_id to poll for progress."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    portal = (payload.get("portal") or "esic").lower()
    if portal not in ("epfo", "esic"):
        raise HTTPException(status_code=400, detail="portal must be 'epfo' or 'esic'")

    company_id = payload.get("company_id")
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if admin["role"] == "sub_admin" and company_id:
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")

    from utils.live_portal import start_live_login

    session_id = await start_live_login(db, company_id, portal)
    logger.info("[portal-gen] live-login start portal=%s company=%s session=%s by %s",
                portal, company_id, session_id, admin["user_id"])
    return {"ok": True, "session_id": session_id}


@router.get("/portal-automation/live-login/{session_id}")
async def get_live_login_status(
    session_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    from utils.live_portal import get_session

    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return s


@router.post("/portal-automation/jobs/{job_id}/manual-complete")
async def manual_complete_job(
    job_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    job = await db.portal_automation_jobs.find_one(
        {"job_id": job_id}, {"_id": 0},
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Firm scope check
    if admin["role"] == "company_admin":
        if job.get("company_id") != admin.get("company_id"):
            raise HTTPException(status_code=403, detail="Not your firm's job")
    if admin["role"] == "sub_admin":
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, job.get("company_id")):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")

    action = job.get("action_type")
    emp_id = job.get("employee_user_id")
    if not emp_id or action not in ("generate_uan", "generate_esic"):
        raise HTTPException(status_code=400, detail="Job cannot be manually completed")

    value = (payload.get("value") or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Value is required")

    # Light validation — UAN is 12 digits, ESIC IP is 10-17 digits.
    digits = "".join(ch for ch in value if ch.isdigit())
    if action == "generate_uan" and len(digits) != 12:
        raise HTTPException(status_code=400, detail="UAN must be exactly 12 digits")
    if action == "generate_esic" and not (10 <= len(digits) <= 17):
        raise HTTPException(status_code=400, detail="ESIC IP number should be 10-17 digits")

    field = "uan_no" if action == "generate_uan" else "esi_ip_no"
    await db.users.update_one(
        {"user_id": emp_id},
        {"$set": {field: digits, f"{field}_updated_at": now_iso(),
                  f"{field}_source": "manual_portal"}},
    )
    await db.portal_automation_jobs.update_one(
        {"job_id": job_id},
        {"$set": {
            "status": "completed",
            "completed_by": admin["user_id"],
            "completed_at": now_iso(),
            "result": {field: digits},
            "updated_at": now_iso(),
        },
         "$push": {"steps": {
             "at": now_iso(),
             "msg": f"Manually completed by ops admin — wrote {field}={digits} to employee.",
         }}},
    )
    logger.info("[portal-gen] manual complete job=%s field=%s value=%s",
                job_id, field, digits)
    return {"ok": True, "field": field, "value": digits}
