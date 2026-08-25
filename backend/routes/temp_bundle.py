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
        # Iter 419 — the bundle had ballooned to 140 MB and the proxy cut
        # the download at ~90 s. Exclude caches / media that the VPS never
        # needs: metro bundler cache, RPA session recordings, pytest cache.
        "--exclude='.metro-cache' --exclude='rpa_media' "
        "--exclude='.pytest_cache' --exclude='*.webm' "
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
    if kind == "fix685":
        # Iter 685 — AAZAR compliance-structure junk repair (dry-run/apply).
        path = "/app/fix_aazar_685.sh"
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Fix script not found")
        return FileResponse(path, filename="fix685.sh",
                            media_type="text/x-shellscript")
    if kind == "diag685":
        # Iter 685 — READ-ONLY master vs frozen-snapshot diagnostic
        # (VIPUL rate 300 + AAZAR HRA/CONV bugs).
        path = "/app/diag_vipul_aazar_685.sh"
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Diag script not found")
        return FileResponse(path, filename="diag685.sh",
                            media_type="text/x-shellscript")
    if kind == "diag2fa":
        # Iter 570 — 2FA OTP email delivery diagnostic + emergency rescue.
        path = "/app/diag_2fa_570.sh"
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Diag script not found")
        return FileResponse(path, filename="diag2fa.sh",
                            media_type="text/x-shellscript")
    if kind == "diag":
        # Iter 488 — read-only attendance diagnostic for the VPS.
        path = "/app/diag_vps_488.sh"
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Diag script not found")
        return FileResponse(path, filename="diag488.sh",
                            media_type="text/x-shellscript")
    if kind == "fixscript":
        # Iter 441 — backend repair/diagnostic script for the VPS.
        path = "/app/fix_backend_441.sh"
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Fix script not found")
        return FileResponse(path, filename="fix441.sh",
                            media_type="text/x-shellscript")
    if kind == "script":
        # Latest VPS deploy script — lets the user fetch + run it in two
        # lines instead of pasting a long script into the SSH terminal.
        path = "/app/deploy_vps_iter715.sh"
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Deploy script not found")
        return FileResponse(path, filename="deploy715.sh",
                            media_type="text/x-shellscript")
    if kind == "brochure":
        # Iter 609 — client-facing Employee PWA feature brochure (PDF).
        # Lives inside backend/static_assets so it ships in the VPS bundle
        # (works from smartpayrolling.com too, not just the preview).
        path = os.path.join(os.path.dirname(__file__), "..",
                            "static_assets", "brochure_employee_pwa.pdf")
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Brochure not found")
        return FileResponse(path, filename="Employee_PWA_Features_SKSharma.pdf",
                            media_type="application/pdf")
    if kind == "legacy":
        # Iter 299 — SQL Server legacy backup restore + explorer setup.
        path = "/app/legacy_setup_vps.sh"
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Legacy script not found")
        return FileResponse(path, filename="legacy_setup.sh",
                            media_type="text/x-shellscript")
    if kind == "ssl":
        # One-time HTTPS / Let's Encrypt setup script for the VPS.
        path = "/app/setup_ssl_iter236_v2.sh"
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="SSL script not found")
        return FileResponse(path, filename="setup_ssl.sh",
                            media_type="text/x-shellscript")
    async with _LOCK:
        # Always rebuild — a cached tar previously served STALE code to the
        # VPS (Iter 191 deploy downloaded Iter 190). Build takes ~2s.
        await _build_tar()
    return FileResponse(_TAR, filename=os.path.basename(_TAR),
                        media_type="application/octet-stream")
