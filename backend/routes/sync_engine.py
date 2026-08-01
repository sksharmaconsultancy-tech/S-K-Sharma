"""
Real-Time ZKTeco Multi-Device Synchronization Engine — Phase 1.

Modular, queue-based service that keeps employee records synchronised across
every ZKTeco machine of a company over the ADMS push protocol (the machines
poll the server; we queue device commands that they execute on their next
contact — so offline machines auto-catch-up the moment they reconnect).

Layers
------
* Repository:  MongoDB collections (``sync_settings``, ``sync_jobs``,
               ``sync_log``, ``sync_conflicts``) + the existing
               ``biometric_devices`` / ``biometric_device_cmds`` / ``users``.
* Service:     :func:`enqueue_employee_sync`, :func:`process_sync_queue`,
               :func:`get_sync_settings`.
* Worker:      :func:`sync_engine_loop` (runs every 30 s, drains the queue,
               retries failed jobs, reconciles device-command results).
* API:         REST endpoints (``/api/sync/*``) consumed by the dashboard.

Design notes
------------
* Auto-sync fires on employee Create / Update / Delete / Transfer / Disable
  from ``server.py`` — always wrapped so a sync hiccup never breaks the
  employee operation itself.
* Conflict rule (Phase 1): the portal is the source of truth. A conflict is
  logged only when a machine reports biometric templates for an employee the
  portal has none for (so on-device enrolments are never silently lost).
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import db, get_user_from_token, require_role
from routes.biometric_devices import _queue_cmd, _template_to_cmd

logger = logging.getLogger("sync_engine")
router = APIRouter(prefix="/api", tags=["sync-engine"])

# Terminal states of an individual device command (biometric_device_cmds).
_CMD_TERMINAL = {"done", "failed"}

# ---------------------------------------------------------------------------
# Settings (Sync_Settings)
# ---------------------------------------------------------------------------
SYNC_DEFAULTS: Dict[str, Any] = {
    "enable_auto_sync": True,
    "sync_fingerprints": True,
    "sync_face": True,
    "sync_card": True,
    "sync_password": True,
    "sync_photos": False,
    # Iter 419 (user rule): attendance is NEVER synced between machines —
    # it only flows FROM each machine INTO the portal (ATTLOG push).
    "retry_failed": True,
    "max_retry_count": 3,
    "sync_interval": 30,  # seconds (worker cadence)
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def get_sync_settings(company_id: str) -> Dict[str, Any]:
    """Company sync settings, merged over defaults."""
    doc = await db.sync_settings.find_one({"company_id": company_id}, {"_id": 0}) or {}
    merged = dict(SYNC_DEFAULTS)
    merged.update({k: v for k, v in doc.items() if k in SYNC_DEFAULTS})
    merged["company_id"] = company_id
    return merged


async def _sync_enabled_devices(company_id: str) -> List[dict]:
    """Registered, enabled, sync-enabled machines of the company."""
    return await db.biometric_devices.find(
        {"company_id": company_id,
         "enabled": {"$ne": False},
         "sync_enabled": {"$ne": False}},
        {"_id": 0, "serial_number": 1, "name": 1, "last_source_ip": 1},
    ).to_list(200)


# ---------------------------------------------------------------------------
# Command building (Service layer)
# ---------------------------------------------------------------------------
async def _build_commands(
    emp: dict, action: str, settings: dict,
) -> List[Dict[str, str]]:
    """Return the ordered list of ADMS commands for one employee-change.

    Each item is ``{"command": ..., "label": ...}``. USERINFO first (so the
    templates land on an existing user), then fingerprint / face templates
    when enabled by settings.
    """
    pin = str(emp.get("bio_code") or "").strip()
    if not pin:
        return []
    name = (emp.get("name") or "")[:24].replace("\t", " ")

    # Removal actions — take the user OFF the machine so they can't punch.
    if action in ("delete", "disable"):
        return [{
            "command": f"DATA DELETE USERINFO PIN={pin}",
            "label": f"Remove {name or pin} from device ({action})",
        }]

    # Create / update / transfer / enable — (re)push the user record.
    parts = [f"DATA UPDATE USERINFO PIN={pin}", f"Name={name}",
             f"Pri={int(emp.get('privilege') or 0)}"]
    if settings.get("sync_password") and (emp.get("punch_password") or emp.get("device_password")):
        parts.append(f"Passwd={emp.get('punch_password') or emp.get('device_password')}")
    if settings.get("sync_card") and (emp.get("card_no") or emp.get("card_number")):
        parts.append(f"Card={emp.get('card_no') or emp.get('card_number')}")
    cmds: List[Dict[str, str]] = [{
        "command": "\t".join(parts),
        "label": f"Sync user {name or pin}",
    }]

    # Biometric templates (from whatever we've captured for this PIN).
    want_fp = settings.get("sync_fingerprints")
    want_face = settings.get("sync_face")
    if want_fp or want_face:
        kinds = []
        if want_fp:
            kinds.append("fp")
        if want_face:
            kinds.append("face")
        templates = await db.biometric_templates.find(
            {"company_id": emp.get("company_id"), "pin": pin,
             "kind": {"$in": kinds}}, {"_id": 0},
        ).to_list(50)
        for t in templates:
            cmds.append({
                "command": _template_to_cmd(t),
                "label": f"Sync {t.get('kind')} template PIN {pin}",
            })
    return cmds


# ---------------------------------------------------------------------------
# Enqueue (called by server.py employee endpoints + manual sync APIs)
# ---------------------------------------------------------------------------
async def enqueue_employee_sync(
    company_id: str,
    user_id: str,
    action: str,
    actor: str = "system",
    force: bool = False,
) -> Optional[str]:
    """Queue a sync job for one employee change. Returns the job_id, or
    ``None`` when nothing needs syncing (auto-sync off, no devices, no PIN).

    ``force=True`` (manual sync) bypasses the auto-sync toggle.
    """
    try:
        settings = await get_sync_settings(company_id)
        if not force and not settings.get("enable_auto_sync"):
            return None
        devices = await _sync_enabled_devices(company_id)
        if not devices:
            return None
        emp = await db.users.find_one({"user_id": user_id}, {"_id": 0})
        if not emp:
            return None
        pin = str(emp.get("bio_code") or "").strip()
        if not pin:
            # Nothing to push without a machine punch number (Bio Code).
            return None
        job_id = f"sj_{uuid.uuid4().hex[:12]}"
        await db.sync_jobs.insert_one({
            "job_id": job_id,
            "company_id": company_id,
            "user_id": user_id,
            "pin": pin,
            "name": emp.get("name"),
            "action": action,
            "status": "pending",
            "attempts": 0,
            "max_attempts": int(settings.get("max_retry_count") or 3),
            "targets": [d["serial_number"] for d in devices],
            "cmd_ids": [],
            "created_by": actor,
            "created_at": _now(),
            "updated_at": _now(),
            "error": None,
        })
        logger.info("[sync] enqueued %s job=%s pin=%s -> %d device(s)",
                    action, job_id, pin, len(devices))
        return job_id
    except Exception:
        logger.warning("[sync] enqueue failed for %s/%s", company_id, user_id,
                       exc_info=True)
        return None


async def enqueue_employee_removal(
    company_id: str,
    user_id: str,
    pin: str,
    name: Optional[str] = None,
    actor: str = "system",
) -> Optional[str]:
    """Queue a 'delete' job from an ALREADY-removed employee (the user row is
    gone, so we take the PIN directly). Respects the auto-sync toggle."""
    try:
        settings = await get_sync_settings(company_id)
        if not settings.get("enable_auto_sync"):
            return None
        devices = await _sync_enabled_devices(company_id)
        pin = str(pin or "").strip()
        if not devices or not pin:
            return None
        job_id = f"sj_{uuid.uuid4().hex[:12]}"
        await db.sync_jobs.insert_one({
            "job_id": job_id,
            "company_id": company_id,
            "user_id": user_id,
            "pin": pin,
            "name": name,
            "action": "delete",
            "status": "pending",
            "attempts": 0,
            "max_attempts": int(settings.get("max_retry_count") or 3),
            "targets": [d["serial_number"] for d in devices],
            "cmd_ids": [],
            "created_by": actor,
            "created_at": _now(),
            "updated_at": _now(),
            "error": None,
        })
        logger.info("[sync] enqueued delete job=%s pin=%s -> %d device(s)",
                    job_id, pin, len(devices))
        return job_id
    except Exception:
        logger.warning("[sync] removal enqueue failed for %s", company_id,
                       exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Worker (Queue drain + retry + reconcile)
# ---------------------------------------------------------------------------
async def _dispatch_job(job: dict) -> None:
    """Queue this job's device commands and open Sync_Log rows."""
    settings = await get_sync_settings(job["company_id"])
    emp = await db.users.find_one({"user_id": job["user_id"]}, {"_id": 0}) or {
        "bio_code": job.get("pin"), "name": job.get("name"),
        "company_id": job["company_id"],
    }
    cmds = await _build_commands(emp, job["action"], settings)
    if not cmds and job["action"] not in ("delete", "disable"):
        await db.sync_jobs.update_one(
            {"job_id": job["job_id"]},
            {"$set": {"status": "success", "updated_at": _now(),
                      "note": "nothing to sync (no PIN/templates)"}},
        )
        return
    cmd_ids: List[str] = []
    for serial in job["targets"]:
        for c in cmds:
            started = datetime.now(timezone.utc)
            cid = await _queue_cmd(serial, c["command"], job["created_by"], c["label"])
            cmd_ids.append(cid)
            await db.sync_log.insert_one({
                "log_id": f"sl_{uuid.uuid4().hex[:12]}",
                "job_id": job["job_id"],
                "company_id": job["company_id"],
                "user_id": job["user_id"],
                "pin": job.get("pin"),
                "device_serial": serial,
                "action": job["action"],
                "command": c["label"],
                "cmd_id": cid,
                "status": "queued",
                "response": None,
                "error": None,
                "exec_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                "ip": None,
                "created_at": _now(),
            })
    await db.sync_jobs.update_one(
        {"job_id": job["job_id"]},
        {"$set": {"status": "processing", "cmd_ids": cmd_ids,
                  "updated_at": _now()},
         "$inc": {"attempts": 1}},
    )


async def _reconcile_job(job: dict) -> None:
    """Turn a processing job into success / retry / failed by looking at the
    outcome of its queued device commands."""
    cmd_ids = job.get("cmd_ids") or []
    if not cmd_ids:
        return
    cmds = await db.biometric_device_cmds.find(
        {"cmd_id": {"$in": cmd_ids}}, {"_id": 0, "cmd_id": 1, "status": 1,
                                       "device_serial": 1, "result_return": 1},
    ).to_list(len(cmd_ids) + 5)
    by_id = {c["cmd_id"]: c for c in cmds}
    statuses = [by_id.get(cid, {}).get("status", "pending") for cid in cmd_ids]
    done = all(s in _CMD_TERMINAL for s in statuses)
    any_failed = any(s == "failed" for s in statuses)

    # Reflect per-device outcomes into the log rows.
    for c in cmds:
        if c["status"] in _CMD_TERMINAL:
            await db.sync_log.update_one(
                {"cmd_id": c["cmd_id"]},
                {"$set": {
                    "status": "success" if c["status"] == "done" else "failed",
                    "response": c.get("result_return"),
                    "error": None if c["status"] == "done" else f"device return {c.get('result_return')}",
                }},
            )

    if not done:
        return  # still waiting on the machine(s)

    settings = await get_sync_settings(job["company_id"])
    if not any_failed:
        await db.sync_jobs.update_one(
            {"job_id": job["job_id"]},
            {"$set": {"status": "success", "updated_at": _now(),
                      "synced_at": _now(), "error": None}},
        )
        return
    # Some device command failed.
    if settings.get("retry_failed") and job.get("attempts", 0) < job.get("max_attempts", 3):
        await db.sync_jobs.update_one(
            {"job_id": job["job_id"]},
            {"$set": {"status": "retry", "cmd_ids": [], "updated_at": _now(),
                      "error": "one or more devices failed — retrying"}},
        )
    else:
        await db.sync_jobs.update_one(
            {"job_id": job["job_id"]},
            {"$set": {"status": "failed", "updated_at": _now(),
                      "error": "device sync failed after max retries"}},
        )
        # Phase 4 — notify admins of a permanently failed sync.
        try:
            await db.notifications.insert_one({
                "notification_id": f"n_{uuid.uuid4().hex[:10]}",
                "company_id": job.get("company_id"),
                "audience": "admins",
                "type": "sync.failed",
                "title": "❌ Employee sync failed",
                "body": (
                    f"Sync for {job.get('name') or job.get('pin')} failed on one "
                    "or more machines after retries. Open Device Sync Engine → "
                    "History to review."
                ),
                "created_at": _now(),
                "created_by": "system",
            })
        except Exception:
            pass


async def process_sync_queue() -> Dict[str, int]:
    """One worker pass: dispatch new/retry jobs, reconcile in-flight ones.
    A failure on one job never stops the others."""
    dispatched = reconciled = 0
    async for job in db.sync_jobs.find({"status": {"$in": ["pending", "retry"]}}).limit(100):
        try:
            await _dispatch_job(job)
            dispatched += 1
        except Exception:
            logger.warning("[sync] dispatch error job=%s", job.get("job_id"),
                           exc_info=True)
            await db.sync_jobs.update_one(
                {"job_id": job["job_id"]},
                {"$set": {"status": "failed", "error": "dispatch error",
                          "updated_at": _now()}},
            )
    async for job in db.sync_jobs.find({"status": "processing"}).limit(200):
        try:
            await _reconcile_job(job)
            reconciled += 1
        except Exception:
            logger.warning("[sync] reconcile error job=%s", job.get("job_id"),
                           exc_info=True)
    # Iter 419 — machine-only sync runs due for their distribute phase.
    try:
        await _process_machine_sync_runs()
    except Exception:
        logger.warning("[sync] machine-sync pass error", exc_info=True)
    return {"dispatched": dispatched, "reconciled": reconciled}


# ---------------------------------------------------------------------------
# Iter 419 — MACHINE-ONLY SYNC (user request: master data feeding pending).
# Synchronizes the machines with EACH OTHER — users + fingerprint / face
# templates — without touching or requiring the Employee Master.
# Phase 1 (harvest): every machine is asked to upload its user database and
# templates. Phase 2 (distribute, ~2 min later via the worker loop): every
# captured user + template is pushed to every machine (skipping templates on
# their origin machine). Offline machines catch up on their next poll.
# ---------------------------------------------------------------------------
async def _process_machine_sync_runs() -> int:
    processed = 0
    now = _now()
    async for run in db.machine_sync_runs.find(
            {"phase": "harvest", "distribute_at": {"$lte": now}}).limit(5):
        try:
            await _distribute_machine_sync(run)
            processed += 1
        except Exception:
            logger.warning("[sync] machine-sync distribute error run=%s",
                           run.get("run_id"), exc_info=True)
            await db.machine_sync_runs.update_one(
                {"run_id": run["run_id"]},
                {"$set": {"phase": "failed", "error": "distribute error",
                          "updated_at": _now()}},
            )
    return processed


async def _distribute_machine_sync(run: dict) -> None:
    cid = run["company_id"]
    devices = await _sync_enabled_devices(cid)
    templates = await db.biometric_templates.find(
        {"company_id": cid}, {"_id": 0}).to_list(20000)
    musers: Dict[str, dict] = {}
    async for m in db.biometric_machine_users.find({"company_id": cid}, {"_id": 0}):
        musers[str(m.get("pin") or "").strip()] = m
    pins = sorted({str(t["pin"]).strip() for t in templates} | set(musers.keys()))
    pins = [p for p in pins if p]
    queued = 0
    for d in devices:
        sn = d["serial_number"]
        for pin in pins:
            mu = musers.get(pin) or {}
            nm = (mu.get("name") or "")[:24].replace("\t", " ")
            parts = [f"DATA UPDATE USERINFO PIN={pin}", f"Name={nm}",
                     f"Pri={mu.get('pri') or 0}"]
            if mu.get("passwd"):
                parts.append(f"Passwd={mu['passwd']}")
            if mu.get("card"):
                parts.append(f"Card={mu['card']}")
            await _queue_cmd(sn, "\t".join(parts),
                             run.get("created_by") or "system:machine-sync",
                             f"Machine sync user {nm or pin}")
            queued += 1
        for t in templates:
            if t.get("device_serial") == sn:
                continue  # already enrolled on its origin machine
            await _queue_cmd(sn, _template_to_cmd(t),
                             run.get("created_by") or "system:machine-sync",
                             f"Machine sync {t.get('kind')} PIN {t.get('pin')}")
            queued += 1
    await db.machine_sync_runs.update_one(
        {"run_id": run["run_id"]},
        {"$set": {"phase": "done", "queued": queued, "users": len(pins),
                  "templates": len(templates), "devices": len(devices),
                  "distributed_at": _now(), "updated_at": _now()}},
    )
    logger.info("[sync] machine-sync run=%s distributed: %d cmd(s), %d user(s), "
                "%d template(s) -> %d device(s)",
                run.get("run_id"), queued, len(pins), len(templates), len(devices))


async def sync_engine_loop():
    """Background scheduler — drains the sync queue every 30 seconds."""
    logger.info("[sync] engine loop started (30s cadence)")
    # Iter 419 — "Always sync, no approval": clear any conflicts still
    # waiting for review from before the auto-approve rule (idempotent).
    try:
        r = await db.sync_conflicts.update_many(
            {"status": "open"},
            {"$set": {"status": "approved",
                      "resolved_by": "system:auto-approve",
                      "resolved_at": _now()}})
        if r.modified_count:
            logger.info("[sync] auto-approved %d legacy open conflict(s)",
                        r.modified_count)
    except Exception:
        pass
    while True:
        try:
            await process_sync_queue()
        except Exception:
            logger.warning("[sync] engine loop error", exc_info=True)
        await asyncio.sleep(30)


# ---------------------------------------------------------------------------
# Conflict logging (called from the ZKTeco template ingest path)
# ---------------------------------------------------------------------------
async def log_template_conflict(company_id: str, pin: str, device_serial: str,
                                kind: str) -> None:
    """Iter 419 (user rule: "Always sync — no approval needed"): a machine
    holding biometric data the portal has nowhere else is captured and
    AUTO-APPROVED immediately — the template is already stored by the
    ingest path, so it syncs to other machines with zero admin action.
    A resolved audit row is kept so the History still shows what happened."""
    try:
        exists = await db.biometric_templates.count_documents(
            {"company_id": company_id, "pin": pin, "kind": kind,
             "device_serial": {"$ne": device_serial}})
        if exists:
            return
        await db.sync_conflicts.update_one(
            {"company_id": company_id, "pin": pin, "kind": kind,
             "device_serial": device_serial},
            {"$setOnInsert": {
                "conflict_id": f"cf_{uuid.uuid4().hex[:10]}",
                "reason": "machine_only_template",
                "detail": f"{kind} template present only on device {device_serial} — auto-approved",
                "created_at": _now(),
            },
             "$set": {
                "status": "approved",
                "resolved_by": "system:auto-approve",
                "resolved_at": _now(),
            }},
            upsert=True,
        )
    except Exception:
        logger.warning("[sync] conflict log failed", exc_info=True)


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------
def _scope_company(admin: dict, company_id: Optional[str]) -> str:
    if admin["role"] == "company_admin":
        return admin["company_id"]
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return company_id


@router.get("/sync/settings")
async def get_settings_api(company_id: Optional[str] = Query(None),
                           authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    cid = _scope_company(admin, company_id)
    return await get_sync_settings(cid)


@router.put("/sync/settings")
async def put_settings_api(payload: dict = Body(...),
                           authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    cid = _scope_company(admin, payload.get("company_id"))
    update = {k: payload[k] for k in SYNC_DEFAULTS if k in payload}
    if "max_retry_count" in update:
        update["max_retry_count"] = max(0, min(10, int(update["max_retry_count"])))
    if "sync_interval" in update:
        update["sync_interval"] = max(15, min(3600, int(update["sync_interval"])))
    update["updated_at"] = _now()
    await db.sync_settings.update_one(
        {"company_id": cid}, {"$set": {"company_id": cid, **update}}, upsert=True)
    return await get_sync_settings(cid)


@router.post("/sync/employee")
async def sync_employee_api(payload: dict = Body(...),
                            authorization: Optional[str] = Header(None)):
    """Manually queue a sync for one employee. Body: {company_id?, user_id,
    action?}. ``action`` defaults to 'update'."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    cid = _scope_company(admin, payload.get("company_id"))
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    job_id = await enqueue_employee_sync(
        cid, user_id, payload.get("action") or "update",
        actor=admin["user_id"], force=True)
    if not job_id:
        raise HTTPException(
            status_code=400,
            detail="Nothing to sync — check the employee has a Bio Code and "
                   "at least one sync-enabled machine is registered.")
    return {"ok": True, "job_id": job_id}


@router.post("/sync/all")
async def sync_all_api(payload: dict = Body(None),
                       authorization: Optional[str] = Header(None)):
    """Queue a sync for every employee (optionally filtered by department /
    group / branch). Body: {company_id?, department?, group?, branch?}."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    payload = payload or {}
    cid = _scope_company(admin, payload.get("company_id"))
    if not await _sync_enabled_devices(cid):
        raise HTTPException(
            status_code=404,
            detail="No sync-enabled machine registered for this company.")
    q: dict = {"role": "employee", "company_id": cid,
               "bio_code": {"$exists": True, "$nin": [None, ""]}}
    for field, key in (("department", "department"), ("employee_group", "group"),
                       ("branch", "branch")):
        if payload.get(key):
            q[field] = payload[key]
    emps = await db.users.find(q, {"_id": 0, "user_id": 1}).to_list(100000)
    queued = 0
    for e in emps:
        if await enqueue_employee_sync(cid, e["user_id"], "update",
                                       actor=admin["user_id"], force=True):
            queued += 1
    # Iter 419 (user report: "0 employee sync job(s) queued") — when nothing
    # queues, say exactly WHY instead of a bare zero.
    if queued == 0:
        base_q = {"role": "employee", "company_id": cid}
        total = await db.users.count_documents(base_q)
        with_bio = await db.users.count_documents(
            {**base_q, "bio_code": {"$exists": True, "$nin": [None, ""]}})
        filters = {k: payload[k] for k in ("department", "group", "branch") if payload.get(k)}
        if total == 0:
            why = ("this firm has no employees in the portal — check the "
                   "firm selected in the dropdown above.")
        elif with_bio == 0:
            why = (f"none of the {total} employee(s) of this firm have a "
                   "Bio Code (machine punch number). Set Bio Codes in the "
                   "Employee Master first, then sync again.")
        elif filters:
            why = (f"{with_bio} employee(s) have a Bio Code, but none match "
                   f"the selected filter {filters} — clear the filter and retry.")
        else:
            why = (f"{with_bio} employee(s) have a Bio Code but no job could "
                   "be queued — check that at least one machine of this firm "
                   "has Sync enabled (Devices tab).")
        return {"ok": True, "queued": 0, "employees": len(emps),
                "message": f"0 sync jobs queued — {why}"}
    return {"ok": True, "queued": queued, "employees": len(emps),
            "message": f"{queued} employee sync job(s) queued."}


@router.post("/sync/machines")
async def sync_machines_only_api(payload: dict = Body(None),
                                 authorization: Optional[str] = Header(None)):
    """Iter 419 — MACHINE-ONLY sync: synchronize all machines of the firm
    with each other (users + FP/face templates captured ON the machines).
    The Employee Master is NOT checked and NOT required. Body: {company_id?}."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    payload = payload or {}
    cid = _scope_company(admin, payload.get("company_id"))
    devices = await _sync_enabled_devices(cid)
    if not devices:
        raise HTTPException(
            status_code=404,
            detail="No sync-enabled machine registered for this company.")
    # Phase 1 — harvest: ask every machine to upload its users + templates.
    for d in devices:
        for cmd, label in (
            ("DATA QUERY USERINFO", "Machine sync — query users"),
            ("DATA QUERY FINGERTMP", "Machine sync — query fingerprints"),
            ("DATA QUERY BIODATA", "Machine sync — query face/bio-data"),
        ):
            await _queue_cmd(d["serial_number"], cmd, admin["user_id"], label)
    run_id = f"ms_{uuid.uuid4().hex[:12]}"
    await db.machine_sync_runs.insert_one({
        "run_id": run_id,
        "company_id": cid,
        "phase": "harvest",
        # Distribute after the machines had time to upload (~2 minutes).
        "distribute_at": (datetime.now(timezone.utc) + timedelta(seconds=120))
            .isoformat().replace("+00:00", "Z"),
        "created_by": admin["user_id"],
        "created_at": _now(),
        "updated_at": _now(),
    })
    return {
        "ok": True, "run_id": run_id, "devices": len(devices),
        "message": (
            f"Machine-only sync started on {len(devices)} machine(s) — "
            "collecting users + fingerprints/faces from every machine now; "
            "distribution to all machines starts automatically in ~2 minutes. "
            "Employee Master is not required."
        ),
    }


@router.get("/sync/machines/status")
async def sync_machines_status_api(company_id: Optional[str] = Query(None),
                                   authorization: Optional[str] = Header(None)):
    """Latest machine-only sync run for the firm."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    cid = _scope_company(admin, company_id)
    run = await db.machine_sync_runs.find_one(
        {"company_id": cid}, {"_id": 0}, sort=[("created_at", -1)])
    return {"run": run}


@router.get("/sync/machines/overview")
async def sync_machines_overview_api(company_id: Optional[str] = Query(None),
                                     authorization: Optional[str] = Header(None)):
    """Iter 419 (user request) — every registered machine of the firm with
    LIVE on-device counts (employees / fingerprints / punch records, as
    reported by the machine itself on each heartbeat) + online status and
    pending command backlog."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    cid = _scope_company(admin, company_id)
    now = datetime.now(timezone.utc)
    devices = await db.biometric_devices.find(
        {"company_id": cid},
        {"_id": 0, "device_id": 1, "serial_number": 1, "name": 1, "brand": 1,
         "model": 1, "kind": 1, "enabled": 1, "sync_enabled": 1,
         "last_seen_at": 1, "user_count": 1, "fp_count": 1,
         "att_log_count": 1, "firmware": 1, "device_ip": 1,
         "templates_captured": 1, "total_punches_ingested": 1},
    ).to_list(200)
    machines = []
    for d in devices:
        online = False
        last = d.get("last_seen_at")
        if last:
            try:
                online = (now - datetime.fromisoformat(
                    str(last).replace("Z", "+00:00"))).total_seconds() < 180
            except Exception:
                pass
        pending_cmds = await db.biometric_device_cmds.count_documents(
            {"device_serial": d["serial_number"],
             "status": {"$in": ["pending", "sent"]}})
        machines.append({
            **d,
            "online": online,
            "pending_cmds": pending_cmds,
            # Employees ON the machine, as the machine reports on heartbeat.
            "employees_on_machine": d.get("user_count"),
        })
    machines.sort(key=lambda m: (not m["online"], m.get("name") or ""))
    return {"machines": machines}


@router.get("/sync/status")
async def sync_status_api(company_id: Optional[str] = Query(None),
                          authorization: Optional[str] = Header(None)):
    """Live dashboard aggregates."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    dev_q: dict = {}
    job_q: dict = {}
    if admin["role"] == "company_admin":
        dev_q["company_id"] = job_q["company_id"] = admin["company_id"]
    elif company_id:
        dev_q["company_id"] = job_q["company_id"] = company_id
    now = datetime.now(timezone.utc)
    devices = await db.biometric_devices.find(dev_q, {"_id": 0, "last_seen_at": 1}).to_list(500)
    online = 0
    for d in devices:
        last = d.get("last_seen_at")
        if last:
            try:
                if (now - datetime.fromisoformat(str(last).replace("Z", "+00:00"))).total_seconds() < 180:
                    online += 1
            except Exception:
                pass
    async def _count(status):
        return await db.sync_jobs.count_documents({**job_q, "status": status})
    pending = await _count("pending")
    retry = await _count("retry")
    processing = await _count("processing")
    synced = await _count("success")
    failed = await _count("failed")
    last_job = await db.sync_jobs.find(
        {**job_q, "status": "success"}, {"_id": 0, "synced_at": 1, "updated_at": 1},
    ).sort("updated_at", -1).limit(1).to_list(1)
    return {
        "total_devices": len(devices),
        "online_devices": online,
        "offline_devices": len(devices) - online,
        "pending_sync": pending + retry,
        "processing": processing,
        "employees_synced": synced,
        "failed_sync": failed,
        "current_queue": pending + retry + processing,
        "last_sync_time": (last_job[0].get("synced_at") or last_job[0].get("updated_at")) if last_job else None,
        "open_conflicts": await db.sync_conflicts.count_documents({**job_q, "status": "open"}),
    }


@router.get("/queue")
async def sync_queue_api(company_id: Optional[str] = Query(None),
                         status: Optional[str] = Query(None),
                         limit: int = Query(100, ge=1, le=500),
                         authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    q: dict = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin["company_id"]
    elif company_id:
        q["company_id"] = company_id
    if status:
        q["status"] = status
    jobs = await db.sync_jobs.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"jobs": jobs}


@router.get("/sync/logs")
async def sync_logs_api(company_id: Optional[str] = Query(None),
                        limit: int = Query(200, ge=1, le=1000),
                        authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    q: dict = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin["company_id"]
    elif company_id:
        q["company_id"] = company_id
    logs = await db.sync_log.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"logs": logs}


@router.get("/sync/conflicts")
async def sync_conflicts_api(company_id: Optional[str] = Query(None),
                             authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    q: dict = {"status": "open"}
    if admin["role"] == "company_admin":
        q["company_id"] = admin["company_id"]
    elif company_id:
        q["company_id"] = company_id
    items = await db.sync_conflicts.find(q, {"_id": 0}).sort("created_at", -1).to_list(300)
    return {"conflicts": items}


@router.post("/sync/conflicts/{conflict_id}/resolve")
async def resolve_conflict_api(conflict_id: str, payload: dict = Body(None),
                               authorization: Optional[str] = Header(None)):
    """Approve (pull the machine template into the portal) or reject a
    conflict. Body: {decision: 'approve'|'reject'}."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    decision = (payload or {}).get("decision") or "approve"
    cf = await db.sync_conflicts.find_one({"conflict_id": conflict_id}, {"_id": 0})
    if not cf:
        raise HTTPException(status_code=404, detail="Conflict not found")
    if admin["role"] == "company_admin" and cf.get("company_id") != admin["company_id"]:
        raise HTTPException(status_code=403, detail="Not authorised")
    await db.sync_conflicts.update_one(
        {"conflict_id": conflict_id},
        {"$set": {"status": "approved" if decision == "approve" else "rejected",
                  "resolved_by": admin["user_id"], "resolved_at": _now()}},
    )
    return {"ok": True, "decision": decision}


@router.get("/sync/report.xlsx")
async def sync_report_xlsx(company_id: Optional[str] = Query(None),
                           authorization: Optional[str] = Header(None)):
    """Phase 4 — consolidated Sync Report: per-device counts, per-status
    totals and the most recent jobs (incl. failures)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    q: dict = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin["company_id"]
    elif company_id:
        q["company_id"] = company_id
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    jobs = await db.sync_jobs.find(q, {"_id": 0}).sort("created_at", -1).to_list(5000)
    logs = await db.sync_log.find(q, {"_id": 0}).to_list(20000)

    wb = Workbook()
    hf = Font(bold=True, color="FFFFFF")
    hfill = PatternFill("solid", fgColor="1D4ED8")

    def _hdr(ws, cols):
        for i, c in enumerate(cols, 1):
            cell = ws.cell(row=1, column=i, value=c)
            cell.font = hf
            cell.fill = hfill

    # Sheet 1 — status summary
    ws1 = wb.active
    ws1.title = "Summary"
    _hdr(ws1, ["Status", "Jobs"])
    counts: Dict[str, int] = {}
    for j in jobs:
        counts[j.get("status", "?")] = counts.get(j.get("status", "?"), 0) + 1
    r = 2
    for k in ("pending", "processing", "retry", "success", "failed", "cancelled"):
        ws1.cell(row=r, column=1, value=k)
        ws1.cell(row=r, column=2, value=counts.get(k, 0))
        r += 1

    # Sheet 2 — per-device
    ws2 = wb.create_sheet("Device-wise")
    _hdr(ws2, ["Device Serial", "Total", "Success", "Failed", "Queued"])
    dev: Dict[str, Dict[str, int]] = {}
    for lg in logs:
        d = dev.setdefault(lg.get("device_serial", "?"),
                           {"total": 0, "success": 0, "failed": 0, "queued": 0})
        d["total"] += 1
        d[lg.get("status", "queued") if lg.get("status") in ("success", "failed", "queued") else "queued"] += 1
    r = 2
    for serial, d in sorted(dev.items()):
        ws2.cell(row=r, column=1, value=serial)
        ws2.cell(row=r, column=2, value=d["total"])
        ws2.cell(row=r, column=3, value=d["success"])
        ws2.cell(row=r, column=4, value=d["failed"])
        ws2.cell(row=r, column=5, value=d["queued"])
        r += 1

    # Sheet 3 — recent jobs
    ws3 = wb.create_sheet("Jobs")
    _hdr(ws3, ["Job ID", "Employee", "PIN", "Action", "Status", "Attempts",
               "Devices", "Created", "Updated", "Error"])
    for i, j in enumerate(jobs[:2000], start=2):
        vals = [j.get("job_id"), j.get("name"), j.get("pin"), j.get("action"),
                j.get("status"), j.get("attempts"), len(j.get("targets") or []),
                j.get("created_at"), j.get("updated_at"), j.get("error")]
        for c, v in enumerate(vals, 1):
            ws3.cell(row=i, column=c, value=v)

    for ws in (ws1, ws2, ws3):
        for col in ws.columns:
            width = max((len(str(c.value)) for c in col if c.value is not None), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(width + 2, 45)

    buf = BytesIO()
    wb.save(buf)
    from fastapi.responses import Response
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=sync-report.xlsx"},
    )
