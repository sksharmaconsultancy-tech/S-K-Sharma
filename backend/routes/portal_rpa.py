"""Live Government Portal Automation Engine + Compliance Automation
Studio — API routes (Iter 234/235).

Session lifecycle:   POST /rpa/start → poll GET /rpa/session/{sid} (1s)
Controls:            POST /rpa/session/{sid}/control  {action}
Captcha / OTP input: POST /rpa/session/{sid}/input    {value}
History + media:     GET  /rpa/history, /rpa/job/{id}, /rpa/media/...
Settings:            GET/POST /rpa/settings
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import FileResponse

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    sub_admin_can_touch_company,
)
from utils import rpa_engine

router = APIRouter(prefix="/api/rpa", tags=["portal-rpa"])

_ADMIN_ROLES = ["super_admin", "sub_admin", "company_admin"]


async def _admin(authorization: Optional[str], company_id: Optional[str] = None) -> dict:
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    if company_id:
        if admin.get("role") == "sub_admin" and not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
        if admin.get("role") == "company_admin" and admin.get("company_id") != company_id:
            raise HTTPException(status_code=403, detail="Not your firm")
    return admin


@router.get("/catalog")
async def rpa_catalog(authorization: Optional[str] = Header(None)):
    """Portals + flows the Studio can run, grouped for the module tree."""
    await _admin(authorization)
    return {
        "portals": [
            {"key": k, **v} for k, v in rpa_engine.PORTALS.items()
        ],
        "flows": [
            {"key": k, "label": v["label"], "portals": v["portals"],
             "needs_employee": v.get("needs_employee", False),
             "needs_run": v.get("needs_run", False)}
            for k, v in rpa_engine.FLOWS.items()
        ],
    }


@router.get("/runs")
async def rpa_runs(company_id: str, authorization: Optional[str] = Header(None)):
    """Compliance Salary Processes usable for ECR / contribution uploads."""
    await _admin(authorization, company_id)
    runs = await db.compliance_salary_runs.find(
        {"company_id": company_id},
        {"_id": 0, "run_id": 1, "month": 1, "status": 1, "created_at": 1},
    ).sort("month", -1).to_list(36)
    return {"runs": runs}


@router.post("/validate")
async def rpa_validate(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Pre-flight validation report (shown before the upload starts)."""
    company_id = payload.get("company_id") or ""
    await _admin(authorization, company_id)
    portal = payload.get("portal") or ""
    run = await db.compliance_salary_runs.find_one(
        {"run_id": payload.get("run_id") or ""}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    rows = run.get("rows") or run.get("lines") or []
    uids = [r.get("user_id") for r in rows if r.get("user_id") and not r.get("uan_no")]
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}}, {"_id": 0, "user_id": 1, "uan_no": 1}):
            for r in rows:
                if r.get("user_id") == u["user_id"]:
                    r.setdefault("uan_no", u.get("uan_no"))
    return {"month": run.get("month"),
            "report": rpa_engine.validate_run_rows(rows, portal)}


@router.post("/start")
async def rpa_start(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    company_id = payload.get("company_id") or ""
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    admin = await _admin(authorization, company_id)
    sid, err = await rpa_engine.start_session(
        db,
        company_id=company_id,
        portal=payload.get("portal") or "",
        flow=payload.get("flow") or "login",
        employee_id=payload.get("employee_id"),
        run_id=payload.get("run_id"),
        speed=payload.get("speed"),
        started_by=admin.get("name") or admin.get("user_id") or "",
    )
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"session_id": sid}


@router.get("/session/{sid}")
async def rpa_session(sid: str, authorization: Optional[str] = Header(None)):
    await _admin(authorization)
    s = rpa_engine.get_session(sid)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s


@router.post("/session/{sid}/control")
async def rpa_control(
    sid: str,
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    await _admin(authorization)
    ok, msg = rpa_engine.control_session(sid, str(payload.get("action") or ""))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@router.post("/session/{sid}/input")
async def rpa_input(
    sid: str,
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    await _admin(authorization)
    ok, msg = rpa_engine.submit_input(sid, str(payload.get("value") or ""))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True}


@router.get("/history")
async def rpa_history(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    await _admin(authorization, company_id)
    q: dict = {}
    if company_id:
        q["company_id"] = company_id
    jobs = await db.portal_rpa_jobs.find(
        q,
        {"_id": 0, "job_id": 1, "session_id": 1, "company_id": 1,
         "company_name": 1, "portal": 1, "portal_label": 1, "flow": 1,
         "flow_label": 1, "status": 1, "started_at": 1, "ended_at": 1,
         "started_by": 1, "error": 1, "run_month": 1,
         "screens": 1, "downloads": 1, "video": 1,
         "employee.name": 1},
    ).sort("started_at", -1).to_list(100)
    return {"jobs": jobs, "active": rpa_engine.list_active()}


@router.get("/job/{job_id}")
async def rpa_job(job_id: str, authorization: Optional[str] = Header(None)):
    await _admin(authorization)
    job = await db.portal_rpa_jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/media/{job_id}/{path:path}")
async def rpa_media(
    job_id: str, path: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    # Media is safe-listed to the job folder; allow ?token= for <img>/<video>
    # tags that can't send Authorization headers.
    await _admin(authorization or (f"Bearer {token}" if token else None))
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="Bad path")
    f = rpa_engine.MEDIA_ROOT / job_id / path
    if not f.exists() or not f.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media_type = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webm": "video/webm", ".mp4": "video/mp4", ".pdf": "application/pdf",
        ".txt": "text/plain", ".csv": "text/csv", ".html": "text/html",
    }.get(Path(path).suffix.lower(), "application/octet-stream")
    return FileResponse(str(f), media_type=media_type, filename=Path(path).name)


@router.get("/settings")
async def rpa_get_settings(authorization: Optional[str] = Header(None)):
    await _admin(authorization)
    return await rpa_engine.get_settings(db)


@router.post("/settings")
async def rpa_save_settings(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await _admin(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    return await rpa_engine.save_settings(db, payload)
