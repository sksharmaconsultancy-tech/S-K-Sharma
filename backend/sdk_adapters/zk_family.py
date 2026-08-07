"""ZK-protocol family adapter — the REAL, working direct-pull implementation.

Covers every machine that speaks the ZKTeco standalone TCP/UDP protocol on
port 4370 (the classic "ZKTeco Standalone SDK" wire protocol, implemented
in pure Python via the `pyzk` library — no Windows DLL needed):
  • ZKTeco (all standalone models: K-series, F-series, iFace, MB, SpeedFace…)
  • eSSL legacy models (identity: rebadged ZK firmware)
  • FingerTec, Ronald Jack, BioMax, Realtime — ZK-protocol clones.

The server CONNECTS TO the device (device IP + port + comm key), so the
device must be reachable from the server: on-site port-forward of the
device port or a static/DDNS IP.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from zk import ZK

from sdk_adapters import register
from sdk_adapters.base import BaseDeviceAdapter, PulledPunch

_VERIFY = {0: "password", 1: "fingerprint", 2: "card", 15: "face", 25: "palm"}


def _connect(host: str, port: int, comm_key: Optional[str]):
    try:
        pwd = int(comm_key) if comm_key and str(comm_key).strip() else 0
    except ValueError:
        pwd = 0
    dev = ZK(host, port=int(port or 4370), timeout=10, password=pwd,
             force_udp=False, ommit_ping=True)
    return dev.connect()


def _sync_test(host: str, port: int, comm_key: Optional[str]) -> dict:
    conn = _connect(host, port, comm_key)
    try:
        info = {
            "serial": conn.get_serialnumber(),
            "device_name": conn.get_device_name(),
            "firmware": conn.get_firmware_version(),
            "platform": conn.get_platform(),
            "device_time": str(conn.get_time()),
            "users_on_device": len(conn.get_users() or []),
        }
        try:
            conn.read_sizes()
            info["punches_on_device"] = conn.records
        except Exception:
            pass
        return info
    finally:
        conn.disconnect()


def _sync_pull(host: str, port: int, comm_key: Optional[str],
               since: Optional[str]) -> List[PulledPunch]:
    conn = _connect(host, port, comm_key)
    try:
        conn.disable_device()
        try:
            logs = conn.get_attendance() or []
        finally:
            try:
                conn.enable_device()
            except Exception:
                pass
        out: List[PulledPunch] = []
        for rec in logs:
            ts = rec.timestamp  # naive datetime in DEVICE-LOCAL wall clock
            if since and ts.strftime("%Y-%m-%d %H:%M:%S") <= since:
                continue
            out.append({
                "device_user_id": str(rec.user_id).strip(),
                "at": ts,
                # rec.punch is the machine's own IN/OUT state key (0-5)
                "state": str(rec.punch) if rec.punch is not None else None,
                "verify": _VERIFY.get(rec.status),
            })
        return out
    finally:
        conn.disconnect()


class _ZKFamilyBase(BaseDeviceAdapter):
    transport = "tcp"
    default_port = 4370
    implemented = True

    async def test_connection(self, host, port, comm_key=None) -> dict:
        try:
            info = await asyncio.to_thread(_sync_test, host, port, comm_key)
            return {"ok": True, "info": info}
        except Exception as e:  # pyzk raises generic exceptions
            raise ValueError(_friendly(e)) from e

    async def pull_punches(self, host, port, comm_key=None, since=None):
        try:
            return await asyncio.to_thread(_sync_pull, host, port, comm_key, since)
        except Exception as e:
            raise ValueError(_friendly(e)) from e


def _friendly(e: Exception) -> str:
    msg = str(e) or e.__class__.__name__
    low = msg.lower()
    if ("timed out" in low or "timeout" in low or "can't reach" in low
            or "broken pipe" in low or "refused" in low or "unreachable" in low):
        return ("Device unreachable — check the IP/port and that the site "
                "router forwards this port to the machine (or use a VPN/static IP).")
    if "unauthenticated" in low or "authent" in low:
        return "Device refused the connection — wrong Comm Key (device menu → Comm → Security)."
    return f"Connection failed: {msg[:160]}"


@register
class ZKTecoStandalone(_ZKFamilyBase):
    vendor = "zkteco_standalone"
    label = "ZKTeco Standalone SDK"
    notes = "TCP 4370 — all standalone ZKTeco models (K/F/iFace/MB/SpeedFace)."


@register
class EsslLegacy(_ZKFamilyBase):
    vendor = "essl_legacy"
    label = "eSSL Legacy SDK"
    notes = "TCP 4370 — eSSL models run ZK firmware; same wire protocol."


@register
class FingerTec(_ZKFamilyBase):
    vendor = "fingertec"
    label = "FingerTec SDK"
    notes = "TCP 4370 — FingerTec devices speak the ZK protocol."


@register
class RonaldJack(_ZKFamilyBase):
    vendor = "ronald_jack"
    label = "Ronald Jack SDK"
    notes = "TCP 4370 — Ronald Jack devices speak the ZK protocol."


@register
class BioMax(_ZKFamilyBase):
    vendor = "biomax"
    label = "BioMax SDK"
    notes = "TCP 4370 — BioMax N-series speak the ZK protocol."


@register
class RealtimeTA(_ZKFamilyBase):
    vendor = "realtime"
    label = "Realtime T&A SDK"
    notes = "TCP 4370 — most Realtime T-series speak the ZK protocol."
