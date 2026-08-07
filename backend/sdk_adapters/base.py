"""Iter 512 — Vendor SDK plug-in framework (SERVER → DEVICE direct pull).

This is ADDITIVE to the existing ADMS/iClock push channel — nothing about
push connectivity changes. A device whose `connection_mode` is "sdk" is
polled BY the server over the vendor's own protocol.

HOW TO ADD A NEW VENDOR (zero core changes):
  1. Create a new file in this package, e.g. `myvendor.py`.
  2. Subclass `BaseDeviceAdapter`, set `vendor`, `label`, `transport`,
     `default_port` and implement `test_connection()` + `pull_punches()`.
  3. Decorate the class with `@register` (from `sdk_adapters`).
The registry auto-discovers every module in this package at import time.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, TypedDict


class PulledPunch(TypedDict, total=False):
    device_user_id: str        # the user id / bio code stored ON the machine
    at: datetime               # device-local wall-clock time (naive OK)
    state: Optional[str]       # "0"=in "1"=out "2"=break-out "3"=break-in "4"=ot-in "5"=ot-out
    verify: Optional[str]      # verify mode (fingerprint/face/card) if known


class BaseDeviceAdapter:
    """One adapter = one vendor SDK/protocol the server can speak."""

    vendor: str = ""            # machine-readable id, e.g. "zkteco_standalone"
    label: str = ""             # human label shown in the UI
    transport: str = "tcp"      # tcp | udp | http
    default_port: int = 4370
    implemented: bool = True    # False → plug-in slot visible but not usable yet
    notes: str = ""             # UI hint (compat, port-forwarding, etc.)

    async def test_connection(
        self, host: str, port: int, comm_key: Optional[str] = None,
    ) -> dict:
        """Connect to the device and return an info dict:
        {"ok": True, "info": {"serial": ..., "firmware": ..., "users": ...}}
        Raise a ValueError with a human message on failure."""
        raise NotImplementedError

    async def pull_punches(
        self, host: str, port: int, comm_key: Optional[str] = None,
        since: Optional[str] = None,
    ) -> List[PulledPunch]:
        """Fetch attendance logs from the device. `since` is an optional
        device-local cursor "YYYY-MM-DD HH:MM:SS" — return only newer
        punches when given (the server dedupes anyway)."""
        raise NotImplementedError

    def describe(self) -> dict:
        return {
            "vendor": self.vendor,
            "label": self.label,
            "transport": self.transport,
            "default_port": self.default_port,
            "implemented": self.implemented,
            "notes": self.notes,
        }
