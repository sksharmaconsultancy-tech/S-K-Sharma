"""Iter 159 — India Location master (State / District / PIN Code).

Static reference data (backend/data/india_locations.json — 37 states/UTs,
~727 districts) + live PIN code lookup via the free India Post API
(api.postalpincode.in) with a Mongo cache so repeat lookups are instant
and offline-safe.
"""
import json
import os
import re
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException

from server import db, get_user_from_token, logger, now_iso  # noqa: E402

router = APIRouter(prefix="/api/locations", tags=["locations"])

_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          "data", "india_locations.json")
with open(_DATA_PATH, "r") as _f:
    _STATES: list = json.load(_f)["states"]
_STATE_MAP = {s["state"].lower(): s["districts"] for s in _STATES}


@router.get("/states")
async def list_states(authorization: Optional[str] = Header(None)):
    await get_user_from_token(authorization)
    return {"states": [s["state"] for s in _STATES]}


@router.get("/districts")
async def list_districts(state: str, authorization: Optional[str] = Header(None)):
    await get_user_from_token(authorization)
    districts = _STATE_MAP.get((state or "").strip().lower())
    if districts is None:
        raise HTTPException(status_code=404, detail="Unknown state")
    return {"state": state, "districts": districts}


@router.get("/all")
async def all_locations(authorization: Optional[str] = Header(None)):
    await get_user_from_token(authorization)
    return {"states": _STATES}


@router.get("/pincode/{pin}")
async def pincode_lookup(pin: str, authorization: Optional[str] = Header(None)):
    await get_user_from_token(authorization)
    pin = (pin or "").strip()
    if not re.fullmatch(r"[1-9]\d{5}", pin):
        raise HTTPException(status_code=400, detail="PIN code must be 6 digits")
    cached = await db.pincode_cache.find_one({"pincode": pin}, {"_id": 0})
    if cached:
        return cached
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"https://api.postalpincode.in/pincode/{pin}")
            payload = r.json()
    except Exception:
        logger.warning("[LOCATIONS] India Post lookup failed for %s", pin)
        raise HTTPException(status_code=503,
                            detail="PIN lookup service unavailable — enter State/District manually")
    offices = ((payload or [{}])[0] or {}).get("PostOffice") or []
    if not offices:
        raise HTTPException(status_code=404, detail="PIN code not found")
    doc = {
        "pincode": pin,
        "state": offices[0].get("State") or "",
        "district": offices[0].get("District") or "",
        "post_offices": [o.get("Name") for o in offices if o.get("Name")][:20],
        "cached_at": now_iso(),
    }
    await db.pincode_cache.update_one({"pincode": pin}, {"$set": doc}, upsert=True)
    return doc
