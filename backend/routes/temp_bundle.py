"""TEMPORARY — code bundle download for VPS deployment.

Lets the user's VPS fetch the latest workspace code directly when the
GitHub push flow is blocked. Protected by a one-off token. Remove this
module once the GitHub flow is healthy again.
"""
import asyncio
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api")

_TOKEN = "sks-deploy-7391"
_TAR = "/tmp/sksharma-latest.tar.gz"
_LOCK = asyncio.Lock()


async def _build_tar() -> None:
    """(Re)build the code tarball — /tmp is wiped on pod restarts, so the
    bundle is regenerated on demand. .env files are excluded so the VPS
    keeps its own configuration."""
    cmd = (
        "cd /app && tar -czf {out}.part "
        "--exclude='.git' --exclude='node_modules' --exclude='.expo' "
        "--exclude='dist' --exclude='venv' --exclude='__pycache__' "
        "--exclude='*.pyc' --exclude='.env' "
        "backend frontend memory test_reports && mv {out}.part {out}"
    ).format(out=_TAR)
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=f"tar failed: {err.decode()[:200]}")


@router.get("/temp-code-bundle")
async def temp_code_bundle(token: str = Query(...), kind: str = Query("tar")):
    if token != _TOKEN:
        raise HTTPException(status_code=403, detail="Bad token")
    if kind == "bundle":
        path = "/tmp/sksharma-latest.bundle"
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Bundle not found")
        return FileResponse(path, filename=os.path.basename(path),
                            media_type="application/octet-stream")
    if kind == "script":
        # Latest VPS deploy script — lets the user fetch + run it in two
        # lines instead of pasting a long script into the SSH terminal.
        path = "/app/deploy_vps_iter216.sh"
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Deploy script not found")
        return FileResponse(path, filename="deploy216.sh",
                            media_type="text/x-shellscript")
    async with _LOCK:
        # Always rebuild — a cached tar previously served STALE code to the
        # VPS (Iter 191 deploy downloaded Iter 190). Build takes ~2s.
        await _build_tar()
    return FileResponse(_TAR, filename=os.path.basename(_TAR),
                        media_type="application/octet-stream")
