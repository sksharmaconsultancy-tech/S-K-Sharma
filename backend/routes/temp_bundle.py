"""TEMPORARY — code bundle download for VPS deployment.

Lets the user's VPS fetch the latest workspace code directly when the
GitHub push flow is blocked. Protected by a one-off token. Remove this
module once the GitHub flow is healthy again.
"""
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api")

_TOKEN = "sks-deploy-7391"


@router.get("/temp-code-bundle")
async def temp_code_bundle(token: str = Query(...), kind: str = Query("bundle")):
    if token != _TOKEN:
        raise HTTPException(status_code=403, detail="Bad token")
    path = "/tmp/sksharma-latest.bundle" if kind == "bundle" else "/tmp/sksharma-latest.tar.gz"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Bundle not found")
    return FileResponse(path, filename=os.path.basename(path), media_type="application/octet-stream")
