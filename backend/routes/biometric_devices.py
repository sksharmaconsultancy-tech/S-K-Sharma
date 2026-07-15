"""ZKTeco biometric device integration (ADMS / iClock push protocol).

Two-device topology chosen by the client:
  • Device A (Serial X) — installed at the entry gate; every punch is IN
  • Device B (Serial Y) — installed at the exit gate; every punch is OUT
We identify the device by the `SN` query-string parameter that ZKTeco firmware
always sends. Punches are auto-approved (skip the mobile approval queue) and
linked to the app user via the pre-existing `bio_code` field on the User
master. Legacy field: `employee_code` is used as a fallback.

iClock endpoints — the ZKTeco firmware calls these paths verbatim. They are
mounted under /api/iclock/ so they follow the standard ingress rule that
maps /api/* to the backend. When deploying, configure the device with:
  Comm → Cloud Server → Server URL: https://<your-host>/api
  (Some firmwares split into Server Address + URL Path — use both fields.)
"""
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional, Tuple

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
)

router = APIRouter(prefix="/api", tags=["biometric-devices"])
logger = logging.getLogger("biometric-devices")


class BiometricDeviceCreate(BaseModel):
    serial_number: str
    name: str
    kind: Literal["in", "out", "both"]
    company_id: Optional[str] = None
    location: Optional[str] = None
    enabled: bool = True


class BiometricDeviceUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[Literal["in", "out", "both"]] = None
    company_id: Optional[str] = None
    location: Optional[str] = None
    enabled: Optional[bool] = None


def _now_iso_z() -> str:
    """UTC ISO timestamp with a trailing Z (some ZKTeco firmwares fussy)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def _match_employee_for_bio(
    device_user_id: str, company_id: Optional[str]
) -> Optional[dict]:
    """Look up the app User for a device-reported user id. Matches on
    `bio_code` first (case-insensitive), then falls back to `employee_code`
    so unmapped early rollouts still work. Scoped to the device's company
    when we know it, else global."""
    device_user_id = (device_user_id or "").strip()
    if not device_user_id:
        return None
    def _scope(q: dict) -> dict:
        if company_id:
            q["company_id"] = company_id
        return q
    # Fast path: exact bio_code
    user = await db.users.find_one(_scope({"bio_code": device_user_id}), {"_id": 0})
    if user:
        return user
    # Case-insensitive bio_code (some sites use alphanumeric IDs)
    user = await db.users.find_one(
        _scope({"bio_code": {"$regex": f"^{re.escape(device_user_id)}$", "$options": "i"}}),
        {"_id": 0},
    )
    if user:
        return user
    # Fallback: employee_code (many firms punch the same number into device + app)
    user = await db.users.find_one(_scope({"employee_code": device_user_id}), {"_id": 0})
    return user


def _parse_zk_timestamp(raw: str) -> Optional[datetime]:
    """ZKTeco ATTLOG timestamps arrive as 'YYYY-MM-DD HH:MM:SS' in the device's
    local time. Devices don't ship the timezone, so we treat the value as UTC
    when the site is running on IST-configured devices (most common in India).
    Callers can override by shifting the returned datetime if they wish."""
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            # ZKTeco AC Mini Plus in India reports IST (UTC+5:30). Convert to UTC.
            dt = dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


async def _ingest_attlog_line(
    line: str, device: dict
) -> Tuple[bool, Optional[str]]:
    """Ingest a single ATTLOG line from a ZKTeco push. Returns (ok, reason).
    Format (tab-separated): user_id\ttimestamp\tstatus\tverify_type\tworkcode\treserved
    """
    if not line or not line.strip():
        return False, "empty"
    parts = line.split("\t")
    if len(parts) < 2:
        # Some devices use spaces or ';' — try a permissive split
        parts = re.split(r"\s+", line.strip(), maxsplit=5)
    if len(parts) < 2:
        return False, "malformed"
    device_user_id = parts[0].strip()
    ts_raw = parts[1].strip() if len(parts) > 1 else ""
    verify_type = parts[3].strip() if len(parts) > 3 else ""
    dt = _parse_zk_timestamp(ts_raw)
    if not dt:
        return False, f"bad_timestamp:{ts_raw}"
    user = await _match_employee_for_bio(device_user_id, device.get("company_id"))
    if not user:
        # Log an unmapped punch so admins can create the mapping later —
        # this keeps the audit trail without breaking the ingest loop.
        await db.biometric_unmapped.insert_one({
            "device_serial": device["serial_number"],
            "device_id": device["device_id"],
            "device_user_id": device_user_id,
            "at": dt.isoformat(),
            "raw": line,
            "seen_at": _now_iso_z(),
        })
        return False, f"unmapped_user:{device_user_id}"
    record_id = f"zk_{uuid.uuid4().hex[:12]}"
    # Iter 143 (user spec) — single-machine "Both IN/OUT" mode: the punch
    # direction alternates per employee per day (first punch = IN, next =
    # OUT, then IN again …), based on the latest earlier punch that day.
    punch_kind = device.get("kind", "in")
    if punch_kind == "both":
        last = await db.attendance.find_one(
            {
                "user_id": user["user_id"],
                "date": dt.strftime("%Y-%m-%d"),
                "kind": {"$in": ["in", "out"]},
                "at": {"$lt": dt.isoformat()},
            },
            {"_id": 0, "kind": 1},
            sort=[("at", -1)],
        )
        punch_kind = "out" if (last and last.get("kind") == "in") else "in"
    record = {
        "record_id": record_id,
        "user_id": user["user_id"],
        "company_id": user.get("company_id"),
        "branch_id": None,
        "branch_name": device.get("location") or device.get("name"),
        "date": dt.strftime("%Y-%m-%d"),
        "kind": punch_kind,
        "at": dt.isoformat(),
        "original_at": dt.isoformat(),
        "latitude": None,
        "longitude": None,
        "distance_m": None,
        "source": f"zkteco:{device['serial_number']}",
        "outside_geofence": False,
        # Machine punches are considered trusted → auto-approved (user chose 4B)
        "status": "approved",
        "decision_by": "system:zkteco",
        "decision_at": _now_iso_z(),
        "decision_reason": f"Auto-approved from ZKTeco device '{device.get('name')}'",
        "device_serial": device["serial_number"],
        "device_id": device["device_id"],
        "device_verify_type": verify_type or None,
        "selfie_base64": None,
    }
    # Idempotency guard: avoid duplicating the same push if the device retries
    exists = await db.attendance.find_one({
        "user_id": user["user_id"],
        "at": record["at"],
        "device_serial": device["serial_number"],
        "kind": record["kind"],
    }, {"_id": 0, "record_id": 1})
    if exists:
        return True, "duplicate_ignored"
    await db.attendance.insert_one(record)
    return True, None


async def _get_device_or_404(sn: str) -> dict:
    device = await db.biometric_devices.find_one(
        {"serial_number": sn}, {"_id": 0}
    )
    if not device or not device.get("enabled", True):
        # We return a plain-text response with status 200 anyway so the device
        # keeps retrying — but log the unknown serial for admin visibility.
        await db.biometric_unknown.update_one(
            {"serial_number": sn},
            {"$setOnInsert": {"first_seen_at": _now_iso_z()},
             "$set": {"last_seen_at": _now_iso_z()},
             "$inc": {"hits": 1}},
            upsert=True,
        )
        raise HTTPException(status_code=404, detail=f"Unknown device {sn}")
    return device


# ---------------------------------------------------------------------------
# iClock endpoints (called by the ZKTeco firmware — no auth header)
# ---------------------------------------------------------------------------
@router.get("/iclock/cdata")
async def iclock_handshake(
    SN: str = Query(..., description="Device serial number"),
    options: Optional[str] = Query(None),
    pushver: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    PushOptionsFlag: Optional[str] = Query(None),
):
    """Initial handshake — device calls this when it comes online. We reply
    with a plain-text config block telling it how often to push logs, what
    tables we accept and what the server clock currently is. This is what
    turns ADMS into a *real-time* channel: the device holds an HTTP long-poll
    open and pushes each new punch within a couple of seconds."""
    await _get_device_or_404(SN)
    await db.biometric_devices.update_one(
        {"serial_number": SN},
        {"$set": {
            "last_seen_at": _now_iso_z(),
            "last_handshake_at": _now_iso_z(),
            "firmware_pushver": pushver,
        }},
    )
    # Standard ADMS response — see ZKTeco Push SDK docs
    body_lines = [
        f"GET OPTION FROM: {SN}",
        "ATTLOGStamp=None",
        "OPERLOGStamp=9999",
        "ATTPHOTOStamp=None",
        "ErrorDelay=30",
        "Delay=10",
        "TransTimes=00:00;14:05",
        "TransInterval=1",
        "TransFlag=TransData AttLog OpLog AttPhoto EnrollUser ChgUser EnrollFP ChgFP UserPic FvFingerVein",
        "TimeZone=8",
        "Realtime=1",
        "Encrypt=None",
        "ServerVer=SKSharma-1.0",
    ]
    return PlainTextResponse("\n".join(body_lines) + "\n")


@router.post("/iclock/cdata")
async def iclock_push(
    request: Request,
    SN: str = Query(...),
    table: Optional[str] = Query(None),
    Stamp: Optional[str] = Query(None),
):
    """Punch push endpoint. The device POSTs blocks of ATTLOG / OPERLOG /
    ATTPHOTO lines here. We parse ATTLOG lines and insert them into the same
    `attendance` collection the mobile app writes to — so reports blend both
    sources natively."""
    device = await _get_device_or_404(SN)
    raw_bytes = await request.body()
    raw = raw_bytes.decode("utf-8", errors="ignore")
    inserted = 0
    skipped = 0
    reasons: List[str] = []
    if (table or "").upper() == "ATTLOG":
        for line in raw.splitlines():
            ok, reason = await _ingest_attlog_line(line, device)
            if ok:
                if reason == "duplicate_ignored":
                    skipped += 1
                else:
                    inserted += 1
            else:
                skipped += 1
                if reason:
                    reasons.append(reason)
    else:
        # OPERLOG / ATTPHOTO / EnrollUser etc. — just log the receipt.
        await db.biometric_operlog.insert_one({
            "device_serial": SN,
            "table": table,
            "stamp": Stamp,
            "raw": raw[:8000],  # cap to keep the doc size reasonable
            "received_at": _now_iso_z(),
        })
    await db.biometric_devices.update_one(
        {"serial_number": SN},
        {"$set": {
            "last_seen_at": _now_iso_z(),
            "last_push_at": _now_iso_z(),
            "last_push_table": table,
        },
         "$inc": {"total_pushes": 1, "total_punches_ingested": inserted}},
    )
    # Iter 77n — Broadcast to the firm channel whenever a push adds
    # punches so admin dashboards refresh in real time.
    if inserted > 0:
        try:
            from utils.ws_broker import broker as _ws
            firm_id = device.get("company_id") if isinstance(device, dict) else None
            if firm_id:
                await _ws.broadcast_firm(firm_id, {
                    "type": "attendance.zk-pushed",
                    "device_serial": SN,
                    "inserted": inserted,
                    "table": table,
                })
        except Exception:
            pass
    # ZKTeco expects a plain "OK" line and the stamp advancement
    # so it can move its cursor forward.
    logger.info(
        "[zkteco] SN=%s table=%s inserted=%d skipped=%d reasons=%s",
        SN, table, inserted, skipped, reasons[:5],
    )
    return PlainTextResponse(f"OK: {inserted}\n")


@router.get("/iclock/getrequest")
async def iclock_getrequest(
    SN: str = Query(...),
    INFO: Optional[str] = Query(None),
):
    """Command-request long-poll — the device asks the server if there are
    any pending commands (enroll user, delete user, sync time, reboot). For
    the current minimal scope we always reply with "OK" (no commands). Every
    successful call still refreshes the device heartbeat so the admin UI can
    show it as online."""
    try:
        await _get_device_or_404(SN)
    except HTTPException:
        return PlainTextResponse("OK\n")
    await db.biometric_devices.update_one(
        {"serial_number": SN},
        {"$set": {
            "last_seen_at": _now_iso_z(),
            "last_getrequest_info": INFO,
        }},
    )
    return PlainTextResponse("OK\n")


@router.get("/iclock/ping")
async def iclock_ping(SN: Optional[str] = Query(None)):
    """Heartbeat used by some firmwares between long-polls."""
    if SN:
        await db.biometric_devices.update_one(
            {"serial_number": SN},
            {"$set": {"last_seen_at": _now_iso_z()}},
        )
    return PlainTextResponse("OK\n")


@router.post("/iclock/devicecmd")
async def iclock_devicecmd(request: Request, SN: str = Query(...)):
    """Command-result reporting — device tells us the outcome of any command
    we previously issued via getrequest. We just accept and log."""
    raw = (await request.body()).decode("utf-8", errors="ignore")
    await db.biometric_devices.update_one(
        {"serial_number": SN},
        {"$set": {"last_seen_at": _now_iso_z()}},
    )
    await db.biometric_cmd_results.insert_one({
        "device_serial": SN,
        "raw": raw[:4000],
        "received_at": _now_iso_z(),
    })
    return PlainTextResponse("OK\n")


# ---------------------------------------------------------------------------
# Admin management APIs (auth-protected) — used by the
# /biometric-devices frontend screen.
# ---------------------------------------------------------------------------
@router.post("/biometric/devices")
async def register_biometric_device(
    payload: BiometricDeviceCreate,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin"])
    sn = payload.serial_number.strip()
    if not sn:
        raise HTTPException(status_code=400, detail="Serial number is required")
    company_id = payload.company_id
    if admin["role"] == "company_admin":
        company_id = admin["company_id"]  # ignore whatever client sent
    if not company_id:
        raise HTTPException(status_code=400, detail="Please pick a company for this device")
    existing = await db.biometric_devices.find_one({"serial_number": sn})
    if existing:
        raise HTTPException(status_code=409, detail=f"Device {sn} is already registered")
    device = {
        "device_id": f"dev_{uuid.uuid4().hex[:10]}",
        "serial_number": sn,
        "name": payload.name.strip() or f"Device {sn}",
        "kind": payload.kind,
        "company_id": company_id,
        "location": (payload.location or "").strip() or None,
        "enabled": payload.enabled,
        "created_at": _now_iso_z(),
        "created_by": admin["user_id"],
        "model": "ZKTeco AC Mini Plus",  # locked to the client's hardware
        "last_seen_at": None,
        "total_pushes": 0,
        "total_punches_ingested": 0,
    }
    await db.biometric_devices.insert_one(device)
    device.pop("_id", None)
    return {"ok": True, "device": device}


@router.get("/biometric/devices")
async def list_biometric_devices(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin"])
    q: dict = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin["company_id"]
    elif company_id:
        q["company_id"] = company_id
    devices = await db.biometric_devices.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    # Attach freshness — "online" if seen in the last 3 minutes
    now = datetime.now(timezone.utc)
    for d in devices:
        last = d.get("last_seen_at")
        online = False
        if last:
            try:
                lt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                online = (now - lt).total_seconds() < 180
            except Exception:
                online = False
        d["online"] = online
    unmapped = await db.biometric_unmapped.count_documents({}) if devices else 0
    return {"devices": devices, "unmapped_count": unmapped}


@router.patch("/biometric/devices/{device_id}")
async def update_biometric_device(
    device_id: str,
    payload: BiometricDeviceUpdate,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin"])
    device = await db.biometric_devices.find_one({"device_id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if admin["role"] == "company_admin" and device.get("company_id") != admin["company_id"]:
        raise HTTPException(status_code=403, detail="Not authorised for this device")
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    if "company_id" in updates and admin["role"] == "company_admin":
        updates.pop("company_id")  # company_admin can't move devices between firms
    await db.biometric_devices.update_one({"device_id": device_id}, {"$set": updates})
    updated = await db.biometric_devices.find_one({"device_id": device_id}, {"_id": 0})
    return {"ok": True, "device": updated}


@router.delete("/biometric/devices/{device_id}")
async def delete_biometric_device(
    device_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin"])
    device = await db.biometric_devices.find_one({"device_id": device_id})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if admin["role"] == "company_admin" and device.get("company_id") != admin["company_id"]:
        raise HTTPException(status_code=403, detail="Not authorised for this device")
    await db.biometric_devices.delete_one({"device_id": device_id})
    return {"ok": True}


@router.get("/biometric/devices/{device_id}/logs")
async def biometric_device_logs(
    device_id: str,
    limit: int = Query(50, ge=1, le=500),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin"])
    device = await db.biometric_devices.find_one({"device_id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if admin["role"] == "company_admin" and device.get("company_id") != admin["company_id"]:
        raise HTTPException(status_code=403, detail="Not authorised for this device")
    logs = await db.attendance.find(
        {"device_serial": device["serial_number"]},
        {"_id": 0, "selfie_base64": 0},
    ).sort("at", -1).to_list(limit)
    return {"device": device, "logs": logs}


@router.get("/biometric/unmapped")
async def biometric_unmapped_punches(
    limit: int = Query(100, ge=1, le=500),
    authorization: Optional[str] = Header(None),
):
    """Punches that arrived from a device but couldn't be mapped to any user
    (bio_code / employee_code not yet set). Admin uses this list to enrol
    workers on the mobile app or add the missing bio_code."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin"])
    q: dict = {}
    if admin["role"] == "company_admin":
        # scope by devices belonging to this company
        my_sns = [d["serial_number"] async for d in db.biometric_devices.find(
            {"company_id": admin["company_id"]}, {"_id": 0, "serial_number": 1}
        )]
        q["device_serial"] = {"$in": my_sns}
    logs = await db.biometric_unmapped.find(q, {"_id": 0}).sort("seen_at", -1).to_list(limit)
    return {"unmapped": logs}


@router.post("/biometric/remap-unmapped")
async def biometric_remap_unmapped(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Iter 93 — Re-map previously-unmapped device punches after an admin
    fixes/updates an employee's bio code in the Employee Master. Each
    stored raw ATTLOG line is re-matched against the CURRENT bio_code /
    employee_code mapping; matches are ingested as normal attendance
    records and removed from the unmapped queue."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin"])
    dev_q: dict = {}
    if admin["role"] == "company_admin":
        dev_q["company_id"] = admin["company_id"]
    elif company_id:
        dev_q["company_id"] = company_id
    devices = {
        d["serial_number"]: d
        async for d in db.biometric_devices.find(dev_q, {"_id": 0})
    }
    q: dict = {}
    if dev_q:  # scope unmapped punches to this firm's devices
        q["device_serial"] = {"$in": list(devices.keys())}
    unmapped = await db.biometric_unmapped.find(q).sort("seen_at", 1).to_list(5000)

    checked = len(unmapped)
    remapped = 0
    still_unmapped = 0
    for doc in unmapped:
        device = devices.get(doc.get("device_serial"))
        if not device:
            device = await db.biometric_devices.find_one(
                {"serial_number": doc.get("device_serial")}, {"_id": 0},
            )
        if not device:
            still_unmapped += 1
            continue
        user = await _match_employee_for_bio(
            doc.get("device_user_id"), device.get("company_id"),
        )
        if not user:
            still_unmapped += 1
            continue
        # Matched now → remove from queue FIRST (ingest re-queues on miss),
        # then run the standard ingest path for dedupe + record shape.
        await db.biometric_unmapped.delete_one({"_id": doc["_id"]})
        ok, _reason = await _ingest_attlog_line(doc.get("raw") or "", device)
        if ok:
            remapped += 1
        else:
            still_unmapped += 1

    # Iter 93 — ALSO re-read every stored .dat import for this scope so
    # punches that were skipped as "unmapped" during the original upload
    # are recovered once the bio code exists. Re-running is idempotent:
    # import_zk_dat_bytes dedupes on (user, at, kind, source_tag).
    from utils.zk_dat_import import import_zk_dat_bytes
    dat_q: dict = {}
    if admin["role"] == "company_admin":
        dat_q["company_id"] = admin["company_id"]
    elif company_id:
        dat_q["company_id"] = company_id
    dat_imports = await db.zk_dat_imports.find(dat_q).sort("uploaded_at", -1).to_list(20)
    dat_files_reread = 0
    dat_recovered = 0
    for imp in dat_imports:
        try:
            stats = await import_zk_dat_bytes(
                db,
                company_id=imp["company_id"],
                in_bytes=(imp.get("in_text") or "").encode() or None,
                out_bytes=(imp.get("out_text") or "").encode() or None,
                combined_bytes=(imp.get("combined_text") or "").encode() or None,
                from_date=imp.get("from_date"),
                to_date=imp.get("to_date"),
                source_tag=imp.get("source_tag"),  # SAME tag → dedupe works
            )
            dat_files_reread += 1
            dat_recovered += int(stats.get("inserted") or 0)
            await db.zk_dat_imports.update_one(
                {"_id": imp["_id"]},
                {"$set": {
                    "last_reread_at": _now_iso_z(),
                    "last_stats": {k: v for k, v in stats.items() if k != "unmapped_bio_codes"},
                }},
            )
        except Exception as exc:
            logger.warning("[remap] .dat re-read failed for %s: %s", imp.get("import_id"), exc)

    return {
        "ok": True,
        "checked": checked,
        "remapped": remapped,
        "still_unmapped": still_unmapped,
        "dat_files_reread": dat_files_reread,
        "dat_recovered": dat_recovered,
    }


@router.post("/biometric/devices/simulate-punch")
async def biometric_simulate_punch(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Dev / QA helper — creates a synthetic ATTLOG line for a registered
    device so admins can rehearse the end-to-end flow without a physical
    machine present."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin"])
    sn = (payload.get("serial_number") or "").strip()
    device_user_id = (payload.get("device_user_id") or "").strip()
    if not sn or not device_user_id:
        raise HTTPException(status_code=400, detail="serial_number and device_user_id are required")
    device = await db.biometric_devices.find_one({"serial_number": sn}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not registered")
    if admin["role"] == "company_admin" and device.get("company_id") != admin["company_id"]:
        raise HTTPException(status_code=403, detail="Not authorised for this device")
    # Craft an ATTLOG line in the exact format the device pushes.
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    line = f"{device_user_id}\t{ist.strftime('%Y-%m-%d %H:%M:%S')}\t0\t1\t0\t0"
    ok, reason = await _ingest_attlog_line(line, device)
    return {"ok": ok, "reason": reason, "line": line}


# ---------------------------------------------------------------------------
# Iter 96b — System Health: biometric last-sync summary for the dashboard.
# ---------------------------------------------------------------------------

@router.get("/admin/system-health/biometric")
async def biometric_system_health(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Last biometric sync info for the dashboard badge.

    Combines the newest .dat import upload, the newest live-device
    heartbeat (ADMS ``last_seen_at``) and the newest biometric-sourced
    punch record. ``status``: ok (<24h), warn (<48h), stale (older/never).
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    if admin.get("role") == "company_admin":
        company_id = admin.get("company_id")
    q = {"company_id": company_id} if company_id else {}

    last_import = await db.zk_dat_imports.find_one(
        q, {"_id": 0, "uploaded_at": 1}, sort=[("uploaded_at", -1)],
    )
    dev_q = dict(q)
    last_device = await db.biometric_devices.find_one(
        dev_q, {"_id": 0, "last_seen_at": 1, "name": 1, "serial": 1},
        sort=[("last_seen_at", -1)],
    )
    punch_q = {**q, "source": {"$regex": "^(import|zkteco|bio)"}}
    last_punch = await db.attendance.find_one(
        punch_q, {"_id": 0, "created_at": 1, "at": 1}, sort=[("created_at", -1)],
    )

    candidates = [
        ("dat_import", (last_import or {}).get("uploaded_at")),
        ("device", (last_device or {}).get("last_seen_at")),
        ("punch", (last_punch or {}).get("created_at")),
    ]
    best_kind, best_at = None, None
    for kind, iso in candidates:
        if not iso:
            continue
        if best_at is None or str(iso) > str(best_at):
            best_kind, best_at = kind, str(iso)

    status = "never"
    hours_ago = None
    if best_at:
        try:
            dt = datetime.fromisoformat(best_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            hours_ago = round(
                (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 1,
            )
            status = "ok" if hours_ago < 24 else ("warn" if hours_ago < 48 else "stale")
        except Exception:
            status = "unknown"

    return {
        "status": status,
        "last_sync_at": best_at,
        "last_sync_kind": best_kind,   # dat_import | device | punch
        "hours_ago": hours_ago,
        "last_import_at": (last_import or {}).get("uploaded_at"),
        "last_device_seen_at": (last_device or {}).get("last_seen_at"),
        "last_punch_created_at": (last_punch or {}).get("created_at"),
        "devices_registered": await db.biometric_devices.count_documents(dev_q),
    }
