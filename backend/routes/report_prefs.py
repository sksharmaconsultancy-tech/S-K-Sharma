"""Iter 496 — Report layout preferences (Universal Report Table engine).

Per-user, per-report saved layout: column widths (drag-resize) and hidden
columns. The frontend also caches these in localStorage; the server copy
makes the layout follow the user onto any device.

  * GET /api/report-prefs/{report_key} — the caller's saved prefs (or null)
  * PUT /api/report-prefs/{report_key} — upsert {w:{col:px}, hide:[col], t:ms}
"""
import sys
from typing import Dict, List, Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

sys.path.append("/app/backend")
from server import db, get_user_from_token, now_iso  # noqa: E402

router = APIRouter(prefix="/api/report-prefs", tags=["report-prefs"])


class ReportPrefs(BaseModel):
    w: Dict[str, float] = Field(default_factory=dict)
    hide: List[str] = Field(default_factory=list)
    t: float = 0


@router.get("/{report_key}")
async def get_report_prefs(report_key: str,
                           authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    doc = await db.report_ui_prefs.find_one(
        {"user_id": user["user_id"], "report_key": report_key},
        {"_id": 0, "w": 1, "hide": 1, "t": 1})
    return {"prefs": doc}


@router.put("/{report_key}")
async def put_report_prefs(report_key: str, body: ReportPrefs,
                           authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    await db.report_ui_prefs.update_one(
        {"user_id": user["user_id"], "report_key": report_key},
        {"$set": {"w": body.w, "hide": body.hide, "t": body.t,
                  "updated_at": now_iso()}},
        upsert=True)
    return {"ok": True}
