"""Iter 494 — EMPLOYEE PHOTO engine (enhancement only).

Adds photo support around the EXISTING Device Sync Engine without touching
any sync / attendance / punch-processing logic.

* ``POST /api/admin/employee-photos/thumbs`` — batch thumbnail lookup for
  grids (Live Sync, Punch Log, Verification, Search).  Thumbnails are
  generated LAZILY (96px JPEG ≈3 KB) from ``users.profile_photo_base64``
  (already uploaded via Employee Master → Documents → Photo) and cached in
  ``users.profile_photo_thumb`` so repeat loads are a single indexed read.
* ``GET  /api/admin/employee-photos/{user_id}/full`` — original image for
  the click-to-preview modal only.

Security: same role gate as the attendance / employee master screens.
Performance: thumbs endpoint never returns originals; caps at 300 ids.
"""
import base64
import io
import sys
from typing import Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

sys.path.append("/app/backend")
from server import db, get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api/admin/employee-photos", tags=["employee-photos"])

_THUMB_PX = 96
_MAX_IDS = 300


def _make_thumb(raw_b64: str) -> Optional[str]:
    """96px cover-cropped JPEG thumbnail (b64, no data: prefix)."""
    try:
        from PIL import Image
        s = raw_b64.split(",", 1)[-1]  # tolerate data: URLs
        img = Image.open(io.BytesIO(base64.b64decode(s)))
        img = img.convert("RGB")
        w, h = img.size
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2,
                        (w + side) // 2, (h + side) // 2))
        img = img.resize((_THUMB_PX, _THUMB_PX), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=70)
        return base64.b64encode(out.getvalue()).decode()
    except Exception:
        return None


class ThumbsBody(BaseModel):
    user_ids: List[str]


@router.post("/thumbs")
async def employee_photo_thumbs(
    body: ThumbsBody,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    ids = [str(u) for u in (body.user_ids or []) if u][:_MAX_IDS]
    out: Dict[str, Optional[str]] = {}
    if not ids:
        return {"thumbs": out}
    q: dict = {"user_id": {"$in": ids}}
    if admin["role"] == "company_admin" and admin.get("company_id"):
        q["company_id"] = admin["company_id"]
    need_gen: List[dict] = []
    async for u in db.users.find(
            q, {"_id": 0, "user_id": 1, "profile_photo_thumb": 1,
                "profile_photo_updated_at": 1, "profile_photo_thumb_at": 1,
                "profile_photo_base64": 1}):
        thumb = u.get("profile_photo_thumb")
        fresh = (u.get("profile_photo_thumb_at") or "") >= (u.get("profile_photo_updated_at") or "")
        if thumb and fresh:
            out[u["user_id"]] = thumb
        elif u.get("profile_photo_base64"):
            need_gen.append(u)
        else:
            out[u["user_id"]] = None
    for u in need_gen:
        thumb = _make_thumb(u["profile_photo_base64"])
        out[u["user_id"]] = thumb
        await db.users.update_one(
            {"user_id": u["user_id"]},
            {"$set": {"profile_photo_thumb": thumb,
                      "profile_photo_thumb_at": u.get("profile_photo_updated_at") or "z"}})
    return {"thumbs": out}


@router.get("/{user_id}/full")
async def employee_photo_full(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    q: dict = {"user_id": user_id}
    if admin["role"] == "company_admin" and admin.get("company_id"):
        q["company_id"] = admin["company_id"]
    u = await db.users.find_one(
        q, {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
            "profile_photo_base64": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"user_id": u["user_id"], "name": u.get("name"),
            "employee_code": u.get("employee_code"),
            "photo": u.get("profile_photo_base64")}
