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


async def _generate_via_module(
    *,
    portal: str,          # "uan" | "esic" (statutory module keys)
    field: str,           # users field the number lands in
    label: str,
    user_id: str,
    payload: Optional[Dict[str, Any]],
    authorization: Optional[str],
) -> Dict[str, Any]:
    """Shared body for the Employee-Master Generate UAN / ESIC buttons.

    Routes through the Statutory Registration module so every button click
    shows up on the /statutory-registration dashboard with full audit
    history. Supports:
      * ``existing_value`` — link an existing number instead of registering
      * ``overrides``      — unsaved form values (e.g. Aadhaar typed but the
        admin hasn't pressed Save yet) merged into the snapshot
    """
    from routes.statutory_registration import (
        create_registration, queue_rpa_job, link_existing_value, get_settings,
    )

    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    emp = await _load_employee_scoped(user_id, admin)
    payload = payload or {}

    # 1) Link an existing number — no portal registration needed.
    existing_value = (payload.get("existing_value") or "").strip()
    if existing_value:
        res = await link_existing_value(
            portal=portal, admin=admin, emp=emp, value=existing_value)
        return {
            "ok": True, field: res["value"],
            "message": f"Existing {label} {res['value']} saved to the Employee Master.",
        }

    if (emp.get(field) or "").strip():
        return {
            "ok": True, "already_present": True, field: emp[field],
            "message": f"Employee already has {'a' if portal == 'uan' else 'an'} {label} on file.",
        }

    company_id = emp.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="Employee not linked to a firm")

    # 2) Unsaved-form overrides ("generate without Save"): persist an
    # Aadhaar typed in the form so KYC and the snapshot stay in sync.
    overrides = payload.get("overrides") or {}
    ov_aadhaar = "".join(ch for ch in str(overrides.get("aadhaar_no") or "") if ch.isdigit())
    if len(ov_aadhaar) == 12 and not (emp.get("aadhaar_no") or emp.get("aadhar_number") or "").strip():
        await db.users.update_one(
            {"user_id": emp["user_id"]},
            {"$set": {"aadhaar_no": ov_aadhaar, "kyc_updated_at": now_iso(),
                      "kyc_updated_by": admin["user_id"]}},
        )
        emp["aadhaar_no"] = ov_aadhaar

    merged = {**emp, **{k: v for k, v in overrides.items() if v not in (None, "")}}
    _require_aadhaar(merged, f"{'a' if portal == 'uan' else 'an'} {label}")

    # 3) Create (or reuse) the registration record.
    res = await create_registration(
        portal=portal, admin=admin, emp=emp, overrides=overrides,
        source="employee_master",
    )
    reg = res["reg"]

    if reg["status"] == "existing_found":
        dup = reg.get("duplicate") or {}
        return {"ok": True, "registration": reg,
                "message": dup.get("note") or
                f"A matching {label} already exists — link it on the Statutory Registration screen."}
    if res["existing"] and reg["status"] in ("queued", "submitted"):
        return {"ok": True, "registration": reg,
                "message": f"{label} registration is already in progress — track it on the Statutory Registration screen."}
    if res["existing"] and reg["status"] == "pending_approval":
        return {"ok": True, "registration": reg,
                "message": f"{label} registration is awaiting HR approval."}

    # 4) HR-approval gate (staff users / firms with approval enabled).
    settings = await get_settings(company_id)
    if settings.get("require_approval") or admin.get("is_company_staff"):
        await db.statutory_registrations.update_one(
            {"reg_id": reg["reg_id"]},
            {"$set": {"status": "pending_approval", "updated_at": now_iso()},
             "$push": {"history": {
                 "at": now_iso(), "by": admin["user_id"],
                 "by_name": admin.get("name") or "", "action": "submitted",
                 "note": "Employee Master button — sent for HR approval"}}},
        )
        return {"ok": True, "registration": reg,
                "message": f"{label} registration sent for HR approval — approve it on the Statutory Registration screen."}

    # 5) Queue the RPA job.
    q = await queue_rpa_job(portal=portal, admin=admin, emp=emp, reg=reg)
    logger.info("[portal-gen] queued %s reg=%s employee=%s by %s",
                portal, reg["reg_id"], emp["user_id"], admin["user_id"])
    return {
        "ok": True, "job": q["job"], "registration_id": reg["reg_id"],
        "message": (
            f"{label} generation queued. Track progress on the Statutory Registration screen."
            if q["creds_present"] else
            f"{label} job queued in MANUAL mode — portal credentials are "
            "missing on Firm Master, so complete it on the portal and use "
            "Manual Complete."
        ),
    }


@router.post("/employees/{user_id}/generate-uan")
async def generate_uan(
    user_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    authorization: Optional[str] = Header(None),
):
    return await _generate_via_module(
        portal="uan", field="uan_no", label="PF UAN",
        user_id=user_id, payload=payload, authorization=authorization,
    )


@router.post("/employees/{user_id}/generate-esic")
async def generate_esic(
    user_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    authorization: Optional[str] = Header(None),
):
    return await _generate_via_module(
        portal="esic", field="esi_ip_no", label="ESIC IP number",
        user_id=user_id, payload=payload, authorization=authorization,
    )


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
    # Sync the linked Statutory Registration record (if the job came from
    # the registration module / Employee-Master buttons).
    if job.get("reg_id"):
        await db.statutory_registrations.update_one(
            {"reg_id": job["reg_id"]},
            {"$set": {"status": "generated", "value": digits,
                      "completed_at": now_iso(), "updated_at": now_iso()},
             "$push": {"history": {
                 "at": now_iso(), "by": admin["user_id"],
                 "by_name": admin.get("name") or "", "action": "generated",
                 "note": f"Manually completed — {field}={digits}"}}},
        )
    logger.info("[portal-gen] manual complete job=%s field=%s value=%s",
                job_id, field, digits)
    return {"ok": True, "field": field, "value": digits}
