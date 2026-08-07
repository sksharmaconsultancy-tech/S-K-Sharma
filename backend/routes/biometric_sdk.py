"""Iter 512 — Direct SDK pull channel (server → device), ADDITIVE to ADMS.

The existing ADMS/iClock push flow is untouched. Devices whose
`connection_mode` is "sdk" are contacted BY the server using a vendor
adapter from the plug-in registry (`sdk_adapters/`). Pulled punches are fed
through the SAME `_ingest_attlog_line` pipeline the ADMS push uses, so
IN/OUT logic, 5-minute duplicate rules, bio_code matching, contractor
gates and every report behave identically.

Endpoints:
  GET  /api/biometric/sdks                          — list vendor adapters
  POST /api/biometric/devices/{id}/sdk-test         — live connection test
  POST /api/biometric/devices/{id}/sdk-pull         — pull punches now
Background: `sdk_auto_pull_loop` polls devices with auto_pull_minutes > 0.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from server import db, get_user_from_token, require_role  # noqa: E402
from sdk_adapters import get_adapter, list_adapters

router = APIRouter(prefix="/api", tags=["biometric-sdk"])
logger = logging.getLogger("biometric-sdk")


def _now_iso_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def _admin_device(device_id: str, authorization: Optional[str]) -> dict:
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    device = await db.biometric_devices.find_one({"device_id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if admin["role"] == "company_admin" and device.get("company_id") != admin["company_id"]:
        raise HTTPException(status_code=403, detail="Not authorised for this device")
    return device


def _sdk_target(device: dict):
    vendor = (device.get("sdk_vendor") or "").strip()
    host = (device.get("device_ip") or "").strip()
    if not vendor:
        raise HTTPException(status_code=400, detail="Pick a vendor SDK for this device first (edit the device).")
    adapter = get_adapter(vendor)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"Unknown vendor SDK '{vendor}'.")
    if not host:
        raise HTTPException(status_code=400, detail="Enter the device IP / host first (edit the device).")
    port = int(device.get("device_port") or adapter.default_port)
    return adapter, host, port, (device.get("comm_key") or None)


@router.get("/biometric/sdks")
async def list_vendor_sdks(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    return {"adapters": list_adapters()}


@router.post("/biometric/devices/{device_id}/sdk-test")
async def sdk_test_connection(device_id: str, authorization: Optional[str] = Header(None)):
    device = await _admin_device(device_id, authorization)
    adapter, host, port, key = _sdk_target(device)
    try:
        result = await adapter.test_connection(host, port, key)
    except ValueError as e:
        await db.biometric_devices.update_one(
            {"device_id": device_id},
            {"$set": {"sdk_last_test_at": _now_iso_z(), "sdk_last_test_ok": False,
                      "sdk_last_error": str(e)}})
        raise HTTPException(status_code=400, detail=str(e))
    await db.biometric_devices.update_one(
        {"device_id": device_id},
        {"$set": {"sdk_last_test_at": _now_iso_z(), "sdk_last_test_ok": True,
                  "sdk_last_error": None, "sdk_device_info": result.get("info"),
                  "last_seen_at": _now_iso_z()}})
    return {"ok": True, "info": result.get("info")}


async def _run_pull(device: dict, triggered_by: str) -> dict:
    """Pull punches from one device and push them through the ADMS pipeline."""
    from routes.biometric_devices import _ingest_attlog_line  # shared pipeline
    adapter, host, port, key = _sdk_target(device)
    since = device.get("sdk_pull_cursor")  # device-local "YYYY-MM-DD HH:MM:SS"
    punches = await adapter.pull_punches(host, port, key, since=since)
    inserted = skipped = 0
    max_ts = since or ""
    for p in punches:
        ts = p["at"].strftime("%Y-%m-%d %H:%M:%S")
        if ts > max_ts:
            max_ts = ts
        state = p.get("state") or ""
        line = f"{p['device_user_id']}\t{ts}\t{state}\t{p.get('verify') or ''}"
        ok, reason = await _ingest_attlog_line(line, device)
        if ok and reason != "duplicate_ignored":
            inserted += 1
        else:
            skipped += 1
    sets = {
        "sdk_last_pull_at": _now_iso_z(),
        "sdk_last_pull_by": triggered_by,
        "sdk_last_pull_fetched": len(punches),
        "sdk_last_pull_inserted": inserted,
        "sdk_last_error": None,
        "last_seen_at": _now_iso_z(),
    }
    if max_ts:
        sets["sdk_pull_cursor"] = max_ts
    await db.biometric_devices.update_one(
        {"device_id": device["device_id"]},
        {"$set": sets, "$inc": {"total_punches_ingested": inserted}})
    if inserted > 0:
        try:
            from utils.ws_broker import broker as _ws
            if device.get("company_id"):
                await _ws.broadcast_firm(device["company_id"], {
                    "type": "attendance.zk-pushed",
                    "device_serial": device["serial_number"],
                    "inserted": inserted, "table": "SDK-PULL",
                })
        except Exception:
            pass
    logger.info("[sdk-pull] %s fetched=%d inserted=%d skipped=%d by=%s",
                device["serial_number"], len(punches), inserted, skipped, triggered_by)
    return {"ok": True, "fetched": len(punches), "inserted": inserted,
            "skipped": skipped, "cursor": max_ts or since}


@router.post("/biometric/devices/{device_id}/sdk-pull")
async def sdk_pull_now(device_id: str, authorization: Optional[str] = Header(None)):
    device = await _admin_device(device_id, authorization)
    admin = await get_user_from_token(authorization)
    try:
        return await _run_pull(device, triggered_by=admin["user_id"])
    except ValueError as e:
        await db.biometric_devices.update_one(
            {"device_id": device_id},
            {"$set": {"sdk_last_pull_at": _now_iso_z(), "sdk_last_error": str(e)}})
        raise HTTPException(status_code=400, detail=str(e))


async def sdk_auto_pull_loop():
    """Every 60s: pull from SDK devices whose auto_pull interval is due."""
    await asyncio.sleep(20)  # let the app finish booting
    while True:
        try:
            devices = await db.biometric_devices.find({
                "connection_mode": "sdk", "enabled": True,
                "auto_pull_minutes": {"$gt": 0},
            }, {"_id": 0}).to_list(100)
            now = datetime.now(timezone.utc)
            for d in devices:
                mins = int(d.get("auto_pull_minutes") or 0)
                last = d.get("sdk_last_pull_at")
                due = True
                if last:
                    try:
                        lt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                        due = (now - lt).total_seconds() >= mins * 60
                    except Exception:
                        due = True
                if not due:
                    continue
                try:
                    await _run_pull(d, triggered_by="system:auto-pull")
                except Exception as e:
                    await db.biometric_devices.update_one(
                        {"device_id": d["device_id"]},
                        {"$set": {"sdk_last_pull_at": _now_iso_z(),
                                  "sdk_last_error": str(e)[:300]}})
                    logger.warning("[sdk-pull][auto] %s failed: %s",
                                   d.get("serial_number"), e)
        except Exception:
            logger.exception("[sdk-pull] auto loop iteration failed")
        await asyncio.sleep(60)
