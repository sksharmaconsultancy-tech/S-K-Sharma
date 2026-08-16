"""Iter 584 patch — Device Sync Engine: kill auto master-sync, add manual
register/delete. Applied atomically to routes/sync_engine.py."""
import sys

P = "/app/backend/routes/sync_engine.py"
src = open(P).read()
orig = src


def rep(old, new):
    global src
    assert old in src, f"NOT FOUND: {old[:80]!r}"
    assert src.count(old) == 1, f"NOT UNIQUE: {old[:80]!r}"
    src = src.replace(old, new)


# ── 1. Settings: new toggles + auto-sync permanently locked OFF.
rep('''SYNC_DEFAULTS: Dict[str, Any] = {
    "enable_auto_sync": True,''',
    '''# Iter 584 (user spec) — FINAL SYNC RULES. Only three flows are legal:
#   1. MACHINE  → PAYROLL   (punch / ATTLOG sync)
#   2. MACHINE  → MACHINE   (device-to-device sync)
#   3. PORTAL   → DEVICE    (MANUAL employee registration / deletion ONLY)
# Automatic Employee Master → Machine sync is PERMANENTLY DISABLED/LOCKED.
SYNC_DEFAULTS: Dict[str, Any] = {
    "enable_auto_sync": False,  # LOCKED — not configurable (Iter 584)
    "machine_to_payroll_punch_sync": True,
    "machine_to_machine_sync": True,
    "manual_employee_registration": False,
    "manual_employee_delete": False,''')

rep('''    merged = dict(SYNC_DEFAULTS)
    merged.update({k: v for k, v in doc.items() if k in SYNC_DEFAULTS})
    merged["company_id"] = company_id
    return merged''',
    '''    merged = dict(SYNC_DEFAULTS)
    merged.update({k: v for k, v in doc.items() if k in SYNC_DEFAULTS})
    # Iter 584 — automatic Employee Master → Machine sync is LOCKED OFF for
    # every firm regardless of what an old settings document says.
    merged["enable_auto_sync"] = False
    merged["auto_master_sync"] = "DISABLED"
    merged["company_id"] = company_id
    return merged''')

# ── 2. enqueue_employee_sync: sync-type gate + target machines + fields.
rep('''async def enqueue_employee_sync(
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
            return None''',
    '''# Iter 584 — the ONLY sync types allowed to travel PORTAL → DEVICE.
_ALLOWED_PORTAL_SYNC = {"MANUAL_EMPLOYEE_REGISTRATION", "MANUAL_EMPLOYEE_DELETE"}
# Every other master-data type is rejected at the SERVICE layer.
BLOCKED_SYNC_TYPES = {
    "EMPLOYEE_MASTER_AUTO_SYNC", "EMPLOYEE_MASTER_BULK_SYNC",
    "AUTOMATIC_EMPLOYEE_CREATE", "AUTOMATIC_EMPLOYEE_UPDATE",
    "AUTOMATIC_EMPLOYEE_DELETE", "AUTOMATIC_EMPLOYEE_TRANSFER",
}


async def enqueue_employee_sync(
    company_id: str,
    user_id: str,
    action: str,
    actor: str = "system",
    force: bool = False,
    sync_type: str = "EMPLOYEE_MASTER_AUTO_SYNC",
    target_serials: Optional[List[str]] = None,
    send_fields: Optional[List[str]] = None,
) -> Optional[str]:
    """Queue a PORTAL → DEVICE job for one employee.

    Iter 584 — SERVICE-LAYER GUARD: only the two MANUAL sync types are
    permitted. Every automatic Employee-Master trigger (create / update /
    delete / transfer / …, still wired in employees_admin.py etc.) lands
    here with the default sync_type and is silently REJECTED
    (MASTER_DATA_DEVICE_SYNC_DISABLED) — the employee operation itself is
    never affected.
    """
    try:
        if sync_type not in _ALLOWED_PORTAL_SYNC:
            logger.info(
                "[sync] BLOCKED %s (%s) for %s/%s — "
                "MASTER_DATA_DEVICE_SYNC_DISABLED",
                sync_type, action, company_id, user_id)
            return None
        settings = await get_sync_settings(company_id)
        devices = await _sync_enabled_devices(company_id)
        if target_serials:
            want = {str(s) for s in target_serials}
            devices = [d for d in devices if d["serial_number"] in want]
        if not devices:
            return None''')

rep('''            "targets": [d["serial_number"] for d in devices],
            "cmd_ids": [],
            "created_by": actor,
            "created_at": _now(),
            "updated_at": _now(),
            "error": None,
        })
        logger.info("[sync] enqueued %s job=%s pin=%s -> %d device(s)",
                    action, job_id, pin, len(devices))''',
    '''            "targets": [d["serial_number"] for d in devices],
            "cmd_ids": [],
            "source_type": "PORTAL",
            "destination_type": "DEVICE",
            "sync_type": sync_type,
            "send_fields": send_fields,
            "created_by": actor,
            "created_at": _now(),
            "updated_at": _now(),
            "error": None,
        })
        logger.info("[sync] enqueued %s (%s) job=%s pin=%s -> %d device(s)",
                    action, sync_type, job_id, pin, len(devices))''')

# ── 3. enqueue_employee_removal → permanently blocked (auto delete path).
rep('''    """Queue a 'delete' job from an ALREADY-removed employee (the user row is
    gone, so we take the PIN directly). Respects the auto-sync toggle."""
    try:
        settings = await get_sync_settings(company_id)
        if not settings.get("enable_auto_sync"):
            return None''',
    '''    """Iter 584 — BLOCKED. This was the automatic machine-delete fired when
    an employee was removed from the payroll. Per the final sync rules an
    employee deletion / deactivation / transfer must NEVER touch the
    machines automatically — HR must use the manual
    'Delete Employee from Machine' action instead."""
    logger.info("[sync] BLOCKED auto machine-delete pin=%s (%s) — "
                "MASTER_DATA_DEVICE_SYNC_DISABLED", pin, company_id)
    return None
    # --- unreachable legacy body kept for reference ---
    try:
        settings = await get_sync_settings(company_id)
        if not settings.get("enable_auto_sync"):
            return None''')

# ── 4. _dispatch_job — honour per-job field selection for manual jobs.
rep('''    cmds = await _build_commands(emp, job["action"], settings)''',
    '''    # Iter 584 — manual registration sends ONLY the fields the admin picked.
    if job.get("send_fields") is not None:
        f = set(job["send_fields"] or [])
        settings = {**settings,
                    "sync_password": "password" in f,
                    "sync_card": "card" in f,
                    "sync_fingerprints": "fingerprint" in f,
                    "sync_face": "face" in f}
    cmds = await _build_commands(emp, job["action"], settings)''')

# ── 5. PUT settings — the locked key can never be switched back on.
rep('''    update = {k: payload[k] for k in SYNC_DEFAULTS if k in payload}''',
    '''    update = {k: payload[k] for k in SYNC_DEFAULTS if k in payload}
    # Iter 584 — automatic master sync is LOCKED; the toggle is not saved.
    update.pop("enable_auto_sync", None)''')

# ── 6. Block the legacy Portal→Device master push endpoints.
rep('''    user_id = payload.get("user_id")
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
    return {"ok": True, "job_id": job_id}''',
    '''    raise HTTPException(
        status_code=403,
        detail="MASTER_DATA_DEVICE_SYNC_DISABLED — Employee Master → Machine "
               "sync is permanently disabled. Use Device Sync Engine → "
               "Register Employee on Machine (manual).")''')

rep('''    payload = payload or {}
    cid = _scope_company(admin, payload.get("company_id"))
    if not await _sync_enabled_devices(cid):
        raise HTTPException(
            status_code=404,
            detail="No sync-enabled machine registered for this company.")
    q: dict = {"role": "employee", "company_id": cid,''',
    '''    raise HTTPException(
        status_code=403,
        detail="MASTER_DATA_DEVICE_SYNC_DISABLED — bulk Employee Master → "
               "Machine sync (EMPLOYEE_MASTER_BULK_SYNC) is permanently "
               "disabled. Use manual Register Employee on Machine instead.")
    payload = payload or {}
    cid = _scope_company(admin, payload.get("company_id"))
    if not await _sync_enabled_devices(cid):
        raise HTTPException(
            status_code=404,
            detail="No sync-enabled machine registered for this company.")
    q: dict = {"role": "employee", "company_id": cid,''')

# ── 7. Gate the two existing manual delete endpoints on the new setting +
#      route them through the MANUAL_EMPLOYEE_DELETE sync type.
rep('''    if payload.get("dry_run"):
        return {"ok": True, "dry_run": True, "employee": emp}
    job_id = await enqueue_employee_sync(
        cid, emp["user_id"], "delete", actor=admin["user_id"], force=True)''',
    '''    if payload.get("dry_run"):
        return {"ok": True, "dry_run": True, "employee": emp}
    settings = await get_sync_settings(cid)
    if not settings.get("manual_employee_delete"):
        raise HTTPException(status_code=403,
                            detail="MANUAL_EMPLOYEE_DELETE_DISABLED — enable "
                                   "'Manual Employee Delete' in Sync Settings first.")
    if not _has_manual_perm(admin, "delete"):
        raise HTTPException(status_code=403,
                            detail="You lack the BIOMETRIC_MANUAL_EMPLOYEE_DELETE permission.")
    job_id = await enqueue_employee_sync(
        cid, emp["user_id"], "delete", actor=admin["user_id"], force=True,
        sync_type="MANUAL_EMPLOYEE_DELETE")''')

rep('''    if payload.get("dry_run"):
        return {"ok": True, "dry_run": True, "count": len(emps),
                "employees": emps[:200]}
    queued, skipped = [], 0
    for e in emps:
        job_id = await enqueue_employee_sync(
            cid, e["user_id"], "delete", actor=admin["user_id"], force=True)''',
    '''    if payload.get("dry_run"):
        return {"ok": True, "dry_run": True, "count": len(emps),
                "employees": emps[:200]}
    settings = await get_sync_settings(cid)
    if not settings.get("manual_employee_delete"):
        raise HTTPException(status_code=403,
                            detail="MANUAL_EMPLOYEE_DELETE_DISABLED — enable "
                                   "'Manual Employee Delete' in Sync Settings first.")
    if not _has_manual_perm(admin, "delete"):
        raise HTTPException(status_code=403,
                            detail="You lack the BIOMETRIC_MANUAL_EMPLOYEE_DELETE permission.")
    queued, skipped = [], 0
    for e in emps:
        job_id = await enqueue_employee_sync(
            cid, e["user_id"], "delete", actor=admin["user_id"], force=True,
            sync_type="MANUAL_EMPLOYEE_DELETE")''')

open(P, "w").write(src)
print("patched OK,", len(src) - len(orig), "chars added")
