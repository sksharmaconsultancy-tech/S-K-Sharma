"""Iter 366 — BACKUP CENTER.

Lists the daily MongoDB backups produced by backup_mongo_daily.sh
(Iter 365) and lets the admin download them from the browser. Also
exposes a token-guarded ``/latest`` endpoint so a Windows Task Scheduler
job on the user's own PC can auto-download every night's backup.

Endpoints:
  GET /api/admin/backups                       (super/sub admin session)
  GET /api/admin/backups/download/{name}?token=...   (session OR token)
  GET /api/admin/backups/latest?token=...            (token — automation)
"""
import os
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse

from server import get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api/admin/backups", tags=["backup-center"])

# Same style as the deploy-bundle token; needed so the user's PC can pull
# backups nightly without a browser session.
BACKUP_TOKEN = "sks-backup-7391"
_NAME_RE = re.compile(r"^[A-Za-z0-9._\-]+\.(gz|bak|archive)$")


def _bk_dir() -> str:
    for d in (os.environ.get("BACKUP_DIR") or "",
              "/home/sksharma/backups", "/app/backups"):
        if d and os.path.isdir(d):
            return d
    return ""


async def _auth(authorization: Optional[str], token: Optional[str]):
    if token == BACKUP_TOKEN:
        return
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])


def _list_files():
    d = _bk_dir()
    out = []
    if d:
        for fn in os.listdir(d):
            if not _NAME_RE.fullmatch(fn):
                continue
            p = os.path.join(d, fn)
            st = os.stat(p)
            out.append({"name": fn, "size": st.st_size,
                        "size_h": f"{st.st_size / 1048576:.1f} MB",
                        "modified": datetime.fromtimestamp(st.st_mtime)
                        .strftime("%Y-%m-%d %H:%M")})
    out.sort(key=lambda x: x["modified"], reverse=True)
    return d, out


@router.get("")
async def backups_list(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    d, files = _list_files()
    return {"dir": d or None,
            "configured": bool(d),
            "note": (None if d else
                     "Backup folder not found — run the daily-backup setup "
                     "script (deploy365.sh) on the VPS first."),
            "files": files[:60], "token": BACKUP_TOKEN}


@router.get("/latest")
async def backups_latest(token: Optional[str] = None,
                         authorization: Optional[str] = Header(None)):
    await _auth(authorization, token)
    d, files = _list_files()
    mongo = [f for f in files if f["name"].startswith("mongo_")]
    if not mongo:
        raise HTTPException(status_code=404, detail="No backups found yet")
    name = mongo[0]["name"]
    return FileResponse(os.path.join(d, name), filename=name,
                        media_type="application/gzip")


@router.get("/download/{name}")
async def backups_download(name: str, token: Optional[str] = None,
                           authorization: Optional[str] = Header(None)):
    await _auth(authorization, token)
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(status_code=400, detail="Invalid file name")
    d = _bk_dir()
    path = os.path.join(d, name) if d else ""
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(path, filename=name,
                        media_type="application/gzip")
