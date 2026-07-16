"""Iter 155 — Full database backup download (SUPER ADMIN only).

GET /api/admin/database-backup → streams a .zip containing one JSON file
per collection (every document, ObjectId/datetime stringified). Restorable
via mongoimport --jsonArray after dropping the `_id` strings, or usable as
an offline archive/audit copy.
"""
import json
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import FileResponse

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_super_admin_strict,
    logger,
)

router = APIRouter(prefix="/api/admin", tags=["db-backup"])


@router.get("/database-backup")
async def database_backup(background_tasks: BackgroundTasks,
                          authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)  # STRICTLY super admin — sub-admins blocked

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tmp = tempfile.NamedTemporaryFile(
        suffix=".zip", prefix=f"db_backup_{stamp}_", delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        names = await db.list_collection_names()
        total_docs = 0
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(names):
                if name.startswith("system."):
                    continue
                docs = []
                async for d in db[name].find({}):
                    d["_id"] = str(d.get("_id"))
                    docs.append(d)
                total_docs += len(docs)
                zf.writestr(f"{name}.json",
                            json.dumps(docs, default=str, ensure_ascii=False))
            zf.writestr("_backup_info.json", json.dumps({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": admin.get("email") or admin["user_id"],
                "collections": len(names),
                "total_documents": total_docs,
            }, indent=2))
        size_mb = round(os.path.getsize(tmp_path) / (1024 * 1024), 1)
        logger.info(f"[DB BACKUP] {admin.get('email')} downloaded backup "
                    f"({len(names)} collections, {total_docs} docs, {size_mb} MB)")
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        logger.exception("[DB BACKUP] failed")
        raise HTTPException(status_code=500, detail="Backup generation failed")

    background_tasks.add_task(lambda: os.path.exists(tmp_path) and os.unlink(tmp_path))
    return FileResponse(
        tmp_path, media_type="application/zip",
        filename=f"SKSharma_DB_Backup_{stamp}.zip",
    )
