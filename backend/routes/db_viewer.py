"""Iter 106 — Database Viewer / Editor (SUPER ADMIN ONLY).

Lets the operator browse every MongoDB collection of THIS deployment
(preview, production, or the user's own VPS — whichever server the
backend is running on), inspect documents, edit them as raw JSON and
delete them.  Intended as a self-hosted phpMyAdmin-style utility.

Endpoints (all require super_admin):
  * GET    /admin/database/collections
  * GET    /admin/database/{coll}/documents?skip&limit&field&value
  * PUT    /admin/database/{coll}/documents/{doc_id}
  * DELETE /admin/database/{coll}/documents/{doc_id}
"""
import re
from datetime import date, datetime
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Body, Header, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorClient

from server import db, get_user_from_token, require_role, now_iso  # noqa: E402

router = APIRouter(prefix="/api/admin/database", tags=["db-viewer"])

MAX_LIMIT = 50

# ---------------------------------------------------------------------------
# External (personal VPS) database support.
# Config stored in db.app_settings {key: "external_db"} — super admin sets
# the VPS Mongo URI + db name once, then flips the viewer's source toggle.
# ---------------------------------------------------------------------------
_ext_cache: dict = {"key": None, "client": None}


def _mask_uri(uri: str) -> str:
    """Hide the password part of a mongodb:// URI for display."""
    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1****\2", uri or "")


async def _external_cfg() -> Optional[dict]:
    return await db.app_settings.find_one({"key": "external_db"}, {"_id": 0})


def _ext_db_handle(cfg: dict):
    key = f"{cfg.get('mongo_url')}|{cfg.get('db_name')}"
    if _ext_cache["key"] != key or _ext_cache["client"] is None:
        _ext_cache["client"] = AsyncIOMotorClient(
            cfg["mongo_url"], serverSelectionTimeoutMS=6000)
        _ext_cache["key"] = key
    return _ext_cache["client"][cfg.get("db_name") or "payroll_production"]


async def _source_db(source: Optional[str]):
    """Resolve which database handle to use: local (default) or the
    configured personal-VPS Mongo."""
    if (source or "").lower() != "external":
        return db
    cfg = await _external_cfg()
    if not cfg or not cfg.get("mongo_url"):
        raise HTTPException(
            status_code=400,
            detail="VPS database is not configured — open Database Settings first.")
    return _ext_db_handle(cfg)


def _jsonable(v):
    """Recursively convert Mongo types so the document is JSON-safe."""
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, bytes):
        return f"<binary {len(v)} bytes>"
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


async def _require_super(authorization: Optional[str]):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin"])
    return user


@router.get("/config")
async def get_db_config(authorization: Optional[str] = Header(None)):
    """Current VPS-database configuration (password masked)."""
    await _require_super(authorization)
    cfg = await _external_cfg() or {}
    return {
        "configured": bool(cfg.get("mongo_url")),
        "mongo_url_masked": _mask_uri(cfg.get("mongo_url") or ""),
        "db_name": cfg.get("db_name") or "",
        "label": cfg.get("label") or "Personal VPS",
        "updated_at": cfg.get("updated_at"),
    }


@router.put("/config")
async def set_db_config(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Save the personal-VPS Mongo connection (super admin only).
    Body: {mongo_url, db_name, label?}. Pass mongo_url="" to clear."""
    user = await _require_super(authorization)
    mongo_url = (payload.get("mongo_url") or "").strip()
    db_name = (payload.get("db_name") or "").strip()
    label = (payload.get("label") or "Personal VPS").strip()[:60]
    if mongo_url and not mongo_url.startswith(("mongodb://", "mongodb+srv://")):
        raise HTTPException(
            status_code=400,
            detail="mongo_url must start with mongodb:// or mongodb+srv://")
    if not mongo_url:
        await db.app_settings.delete_one({"key": "external_db"})
        _ext_cache["key"] = None
        _ext_cache["client"] = None
        return {"ok": True, "configured": False}
    if not db_name:
        raise HTTPException(status_code=400, detail="db_name is required")
    await db.app_settings.update_one(
        {"key": "external_db"},
        {"$set": {"key": "external_db", "mongo_url": mongo_url,
                  "db_name": db_name, "label": label,
                  "updated_by": user["user_id"], "updated_at": now_iso()}},
        upsert=True)
    _ext_cache["key"] = None  # force reconnect with new settings
    return {"ok": True, "configured": True}


@router.post("/config/test")
async def test_db_config(
    payload: dict = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """Test a VPS Mongo connection. Uses the body's {mongo_url, db_name}
    if given, else the SAVED config."""
    await _require_super(authorization)
    mongo_url = (payload.get("mongo_url") or "").strip()
    db_name = (payload.get("db_name") or "").strip()
    if not mongo_url:
        cfg = await _external_cfg() or {}
        mongo_url = cfg.get("mongo_url") or ""
        db_name = db_name or cfg.get("db_name") or ""
    if not mongo_url:
        raise HTTPException(status_code=400, detail="No VPS database configured")
    try:
        client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=6000)
        names = await client[db_name or "admin"].list_collection_names()
        client.close()
        return {"ok": True, "collections_found": len(names)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


@router.get("/collections")
async def list_collections(
    source: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    await _require_super(authorization)
    d = await _source_db(source)
    try:
        names = sorted(await d.list_collection_names())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach database: {str(e)[:200]}")
    out = []
    for n in names:
        try:
            cnt = await d[n].estimated_document_count()
        except Exception:
            cnt = 0
        out.append({"name": n, "count": cnt})
    return {"collections": out}


@router.get("/filters")
async def filter_options(
    source: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Firm + employee lists for the firm-wise / employee-wise filters."""
    await _require_super(authorization)
    d = await _source_db(source)
    firms = [
        {"company_id": c.get("company_id"), "name": c.get("name"),
         "company_code": c.get("company_code")}
        async for c in d.companies.find(
            {}, {"_id": 0, "company_id": 1, "name": 1, "company_code": 1}
        ).sort("name", 1)
    ]
    employees = [
        {"user_id": u.get("user_id"), "name": u.get("name"),
         "employee_code": u.get("employee_code"), "company_id": u.get("company_id")}
        async for u in d.users.find(
            {"role": "employee"},
            {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "company_id": 1},
        ).sort("name", 1)
    ]
    return {"firms": firms, "employees": employees}


@router.get("/{coll}/documents")
async def list_documents(
    coll: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=MAX_LIMIT),
    field: Optional[str] = Query(None, description="Field name to filter on"),
    value: Optional[str] = Query(None, description="Value (contains match)"),
    company_id: Optional[str] = Query(None, description="Firm-wise filter"),
    user_id: Optional[str] = Query(None, description="Employee-wise filter"),
    source: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    await _require_super(authorization)
    sdb = await _source_db(source)
    try:
        coll_names = await sdb.list_collection_names()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach database: {str(e)[:200]}")
    if coll not in coll_names:
        raise HTTPException(status_code=404, detail="Collection not found")
    q: dict = {}
    if company_id:
        q["company_id"] = company_id
    if user_id:
        q["user_id"] = user_id
    if field and value is not None and value != "":
        f = field.strip()
        # numeric equality if the value looks like a number, else
        # case-insensitive contains
        try:
            num = float(value) if "." in value else int(value)
            q["$or"] = [{f: num}, {f: {"$regex": re.escape(value), "$options": "i"}}]
        except ValueError:
            q[f] = {"$regex": re.escape(value), "$options": "i"}
    total = await sdb[coll].count_documents(q) if q else await sdb[coll].estimated_document_count()
    docs = []
    async for doc in sdb[coll].find(q).sort("_id", -1).skip(skip).limit(limit):
        oid = doc.pop("_id", None)
        docs.append({"__id": str(oid), **_jsonable(doc)})
    return {"documents": docs, "total": total, "skip": skip, "limit": limit}


def _oid(doc_id: str) -> ObjectId:
    try:
        return ObjectId(doc_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid document id")


@router.put("/{coll}/documents/{doc_id}")
async def update_document(
    coll: str,
    doc_id: str,
    payload: dict = Body(...),
    source: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    await _require_super(authorization)
    sdb = await _source_db(source)
    doc = payload.get("document")
    if not isinstance(doc, dict) or not doc:
        raise HTTPException(status_code=400, detail="Body must be {document: {...}}")
    doc.pop("__id", None)
    doc.pop("_id", None)
    r = await sdb[coll].replace_one({"_id": _oid(doc_id)}, doc)
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


@router.delete("/{coll}/documents/{doc_id}")
async def delete_document(
    coll: str,
    doc_id: str,
    source: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    await _require_super(authorization)
    sdb = await _source_db(source)
    r = await sdb[coll].delete_one({"_id": _oid(doc_id)})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}
