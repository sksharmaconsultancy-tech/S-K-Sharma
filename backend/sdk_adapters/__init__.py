"""Vendor SDK adapter registry — auto-discovers every module in this package.

Add a vendor = drop a file in this folder. Core code never changes.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Dict, List, Optional, Type

from sdk_adapters.base import BaseDeviceAdapter

logger = logging.getLogger("sdk-adapters")

_REGISTRY: Dict[str, BaseDeviceAdapter] = {}


def register(cls: Type[BaseDeviceAdapter]) -> Type[BaseDeviceAdapter]:
    """Class decorator — registers an adapter instance under its vendor id."""
    inst = cls()
    if not inst.vendor:
        raise ValueError(f"{cls.__name__} is missing a vendor id")
    _REGISTRY[inst.vendor] = inst
    return cls


def get_adapter(vendor: str) -> Optional[BaseDeviceAdapter]:
    _discover()
    return _REGISTRY.get((vendor or "").strip().lower())


def list_adapters() -> List[dict]:
    _discover()
    out = [a.describe() for a in _REGISTRY.values()]
    # implemented first, then alphabetical
    out.sort(key=lambda a: (not a["implemented"], a["label"]))
    return out


_discovered = False


def _discover() -> None:
    """Import every module in the package once so @register decorators run."""
    global _discovered
    if _discovered:
        return
    _discovered = True
    import sdk_adapters as pkg
    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name in ("base", "__init__"):
            continue
        try:
            importlib.import_module(f"sdk_adapters.{mod.name}")
        except Exception:
            logger.exception("[sdk-adapters] failed to load plugin %s", mod.name)
