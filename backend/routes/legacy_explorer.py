"""Iter 299 — Legacy SQL Server Explorer (read-only).

The user's old payroll software's SQL Server backup (.bak) is restored on
the VPS into a Dockerised SQL Server Express (see legacy_setup_vps.sh).
These endpoints let the admin BROWSE that legacy data inside the portal
before deciding what to import ("Before Import we want to Check the Data").

Strictly READ-ONLY:
  GET /api/admin/legacy/status                      — connection + databases
  GET /api/admin/legacy/tables?db=                  — tables + row counts
  GET /api/admin/legacy/rows?db=&table=&skip=&limit=&search=

Connection config comes from backend/.env (written by legacy_setup_vps.sh):
  LEGACY_MSSQL_HOST / LEGACY_MSSQL_PORT / LEGACY_MSSQL_USER / LEGACY_MSSQL_PASSWORD
"""
import asyncio
import datetime
import decimal
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from server import get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api", tags=["legacy-explorer"])

_IDENT_RE = re.compile(r"^[A-Za-z0-9_ .$#@\-]{1,128}$")


def _cfg() -> Optional[dict]:
    pw = os.environ.get("LEGACY_MSSQL_PASSWORD")
    if not pw:
        return None
    return {
        "server": os.environ.get("LEGACY_MSSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("LEGACY_MSSQL_PORT", "14333")),
        "user": os.environ.get("LEGACY_MSSQL_USER", "sa"),
        "password": pw,
    }


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        return f"<binary {len(v)} bytes>"
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


def _query(database: Optional[str], sql: str, params: tuple = ()) -> List[dict]:
    """Blocking pymssql query — run via asyncio.to_thread."""
    import pymssql  # imported lazily so the app boots even if lib missing
    cfg = _cfg()
    conn = pymssql.connect(
        server=cfg["server"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], database=database or "master",
        login_timeout=8, timeout=25, as_dict=True,
    )
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall() or []
        return [{k: _jsonable(v) for k, v in r.items()} for r in rows]
    finally:
        conn.close()


async def _q(database: Optional[str], sql: str, params: tuple = ()) -> List[dict]:
    try:
        return await asyncio.to_thread(_query, database, sql, params)
    except ImportError:
        raise HTTPException(status_code=503, detail="pymssql library not installed on this server — run the latest deploy script.")
    except Exception as e:  # connection / query errors
        raise HTTPException(status_code=502, detail=f"Legacy SQL Server error: {str(e)[:300]}")


def _check_ident(name: str, what: str) -> str:
    name = (name or "").strip()
    if not _IDENT_RE.match(name):
        raise HTTPException(status_code=400, detail=f"Invalid {what} name")
    return name


async def _admin(authorization: Optional[str]) -> dict:
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    return admin


@router.get("/admin/legacy/status")
async def legacy_status(authorization: Optional[str] = Header(None)):
    await _admin(authorization)
    if not _cfg():
        return {"configured": False, "connected": False, "databases": []}
    try:
        ver = await _q(None, "SELECT @@VERSION AS v")
        dbs = await _q(
            None,
            "SELECT d.name, CAST(SUM(mf.size) * 8.0 / 1024 AS INT) AS size_mb "
            "FROM sys.databases d JOIN sys.master_files mf ON mf.database_id = d.database_id "
            "WHERE d.database_id > 4 GROUP BY d.name ORDER BY d.name",
        )
        return {
            "configured": True,
            "connected": True,
            "version": (ver[0]["v"].split("\n")[0] if ver else ""),
            "databases": dbs,
        }
    except HTTPException as e:
        return {"configured": True, "connected": False, "error": e.detail, "databases": []}


@router.get("/admin/legacy/tables")
async def legacy_tables(
    db: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    await _admin(authorization)
    if not _cfg():
        raise HTTPException(status_code=503, detail="Legacy SQL Server is not configured yet")
    _check_ident(db, "database")
    rows = await _q(
        db,
        "SELECT s.name AS schema_name, t.name AS table_name, "
        "SUM(CASE WHEN p.index_id IN (0,1) THEN p.rows ELSE 0 END) AS row_count "
        "FROM sys.tables t "
        "JOIN sys.schemas s ON s.schema_id = t.schema_id "
        "JOIN sys.partitions p ON p.object_id = t.object_id "
        "GROUP BY s.name, t.name ORDER BY row_count DESC, t.name",
    )
    return {"db": db, "tables": rows}


@router.get("/admin/legacy/rows")
async def legacy_rows(
    db: str = Query(...),
    table: str = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    await _admin(authorization)
    if not _cfg():
        raise HTTPException(status_code=503, detail="Legacy SQL Server is not configured yet")
    _check_ident(db, "database")
    table = _check_ident(table, "table")

    # Table must actually exist (guards against identifier injection).
    known = await _q(
        db,
        "SELECT s.name AS schema_name, t.name AS table_name FROM sys.tables t "
        "JOIN sys.schemas s ON s.schema_id = t.schema_id",
    )
    match = next((k for k in known if k["table_name"].lower() == table.lower()), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Table '{table}' not found in {db}")
    fq = f"[{match['schema_name']}].[{match['table_name']}]"

    cols = await _q(
        db,
        "SELECT c.name, ty.name AS type_name FROM sys.columns c "
        "JOIN sys.types ty ON ty.user_type_id = c.user_type_id "
        "JOIN sys.tables t ON t.object_id = c.object_id "
        "JOIN sys.schemas s ON s.schema_id = t.schema_id "
        "WHERE t.name = %s AND s.name = %s ORDER BY c.column_id",
        (match["table_name"], match["schema_name"]),
    )

    where = ""
    params: tuple = ()
    if search and search.strip():
        text_cols = [
            c["name"] for c in cols
            if c["type_name"] in ("varchar", "nvarchar", "char", "nchar", "text", "ntext")
        ][:12]
        if text_cols:
            like = " OR ".join(f"[{c}] LIKE %s" for c in text_cols)
            where = f"WHERE ({like})"
            params = tuple(f"%{search.strip()}%" for _ in text_cols)

    total_rows = await _q(db, f"SELECT COUNT(*) AS n FROM {fq} {where}", params)
    rows = await _q(
        db,
        f"SELECT * FROM {fq} {where} ORDER BY 1 "
        f"OFFSET {int(skip)} ROWS FETCH NEXT {int(limit)} ROWS ONLY",
        params,
    )
    return {
        "db": db,
        "table": match["table_name"],
        "columns": cols,
        "total": (total_rows[0]["n"] if total_rows else 0),
        "skip": skip,
        "limit": limit,
        "rows": rows,
    }
