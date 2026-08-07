"""Plug-in SLOTS for vendors whose SDKs are proprietary / Windows-DLL-only
or use their own HTTP protocol (not built yet — user chose ZK-family first).

Each slot appears in the vendor dropdown marked "adapter pending" so a real
adapter can replace it later WITHOUT any core changes: just implement
`test_connection` + `pull_punches` and flip `implemented = True`.
"""
from __future__ import annotations

from sdk_adapters import register
from sdk_adapters.base import BaseDeviceAdapter


class _Pending(BaseDeviceAdapter):
    implemented = False

    async def test_connection(self, host, port, comm_key=None):
        raise ValueError(
            f"The {self.label} adapter is a plug-in slot — not enabled yet. "
            "Use the ADMS push channel for this machine, or ask for this "
            "adapter to be built.")

    async def pull_punches(self, host, port, comm_key=None, since=None):
        raise ValueError(f"The {self.label} adapter is not enabled yet.")


@register
class Suprema(_Pending):
    vendor = "suprema"
    label = "Suprema SDK"
    transport = "tcp"
    default_port = 51211
    notes = "BioStar device SDK — adapter pending."


@register
class Nitgen(_Pending):
    vendor = "nitgen"
    label = "Nitgen SDK"
    default_port = 5005
    notes = "Windows-DLL SDK — adapter pending."


@register
class Virdi(_Pending):
    vendor = "virdi"
    label = "Virdi SDK"
    default_port = 9870
    notes = "UNIS server protocol — adapter pending."


@register
class Anviz(_Pending):
    vendor = "anviz"
    label = "Anviz SDK"
    default_port = 5010
    notes = "Anviz TC-B protocol — adapter pending."


@register
class BioEnable(_Pending):
    vendor = "bioenable"
    label = "BioEnable SDK"
    default_port = 4370
    notes = "Adapter pending — many BioEnable models also work via ADMS push."


@register
class MatrixLegacy(_Pending):
    vendor = "matrix_legacy"
    label = "Matrix Legacy SDK"
    transport = "http"
    default_port = 80
    notes = "COSEC HTTP API — adapter pending (Matrix push webhook already works)."


@register
class HikvisionTA(_Pending):
    vendor = "hikvision"
    label = "Hikvision Attendance SDK"
    transport = "http"
    default_port = 80
    notes = "ISAPI HTTP — adapter pending (skipped per your choice, can add later)."


@register
class DahuaTA(_Pending):
    vendor = "dahua"
    label = "Dahua Attendance SDK"
    transport = "http"
    default_port = 80
    notes = "Dahua HTTP API — adapter pending (skipped per your choice, can add later)."
