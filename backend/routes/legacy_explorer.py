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

from server import get_user_from_token, require_role, db as mongo_db  # noqa: E402

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


_TEXT_TYPES = ("varchar", "nvarchar", "char", "nchar", "text", "ntext")


@router.get("/admin/legacy/discover")
async def legacy_discover(
    db: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    """Iter 299b (user: "How can we check Firms And Employees") — smart
    scan of the legacy database:
      • finds tables/columns that look like COMPANY / FIRM names, pulls
        the distinct company names, and marks which ones ALREADY EXIST
        as firms in the portal;
      • finds tables that look like EMPLOYEE masters (name + PF/ESI/DOJ
        style columns), ranked by match score."""
    import difflib
    await _admin(authorization)
    if not _cfg():
        raise HTTPException(status_code=503, detail="Legacy SQL Server is not configured yet")
    _check_ident(db, "database")

    tables = await _q(
        db,
        "SELECT s.name AS schema_name, t.name AS table_name, "
        "SUM(CASE WHEN p.index_id IN (0,1) THEN p.rows ELSE 0 END) AS row_count "
        "FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id "
        "JOIN sys.partitions p ON p.object_id = t.object_id "
        "GROUP BY s.name, t.name",
    )
    rowcount = {(t["schema_name"], t["table_name"]): int(t["row_count"] or 0) for t in tables}
    cols = await _q(
        db,
        "SELECT s.name AS schema_name, t.name AS table_name, c.name AS col_name, "
        "ty.name AS type_name FROM sys.columns c "
        "JOIN sys.tables t ON t.object_id = c.object_id "
        "JOIN sys.schemas s ON s.schema_id = t.schema_id "
        "JOIN sys.types ty ON ty.user_type_id = c.user_type_id",
    )
    by_table: Dict[tuple, List[dict]] = {}
    for c in cols:
        by_table.setdefault((c["schema_name"], c["table_name"]), []).append(c)

    # ---- Portal firms (to mark matches) ----
    portal = await mongo_db.companies.find({}, {"_id": 0, "company_id": 1, "name": 1}).to_list(300)
    portal_names = [(p.get("name") or "", p) for p in portal if p.get("name")]

    def _match_portal(name: str) -> Optional[dict]:
        n = (name or "").strip().lower()
        if not n:
            return None
        for pn, p in portal_names:
            pl = pn.strip().lower()
            if n == pl or n in pl or pl in n:
                return p
        best = difflib.get_close_matches(n, [pn.strip().lower() for pn, _ in portal_names], n=1, cutoff=0.8)
        if best:
            for pn, p in portal_names:
                if pn.strip().lower() == best[0]:
                    return p
        return None

    # ---- Company-name candidates ----
    def _is_company_col(col: str) -> bool:
        c = col.lower().replace("_", "")
        return any(
            h in c for h in ("companyname", "compname", "firmname", "clientname",
                             "establishmentname", "estname", "unitname", "contractorname")
        ) or (("comp" in c or "firm" in c or "client" in c) and "name" in c)

    company_candidates: List[dict] = []
    seen_names: Dict[str, dict] = {}
    for key, tcols in by_table.items():
        if rowcount.get(key, 0) <= 0:
            continue
        for c in tcols:
            if c["type_name"] not in _TEXT_TYPES or not _is_company_col(c["col_name"]):
                continue
            sch, tbl = key
            try:
                vals = await _q(
                    db,
                    f"SELECT DISTINCT TOP 200 [{c['col_name']}] AS v FROM [{sch}].[{tbl}] "
                    f"WHERE [{c['col_name']}] IS NOT NULL AND LTRIM(RTRIM([{c['col_name']}])) <> ''",
                )
            except HTTPException:
                continue
            names = sorted({str(v["v"]).strip() for v in vals if str(v.get("v") or "").strip()})
            if not names or len(names) > 150:
                continue  # not a company list (empty or too many distinct values)
            entry_vals = []
            for nm in names:
                pm = _match_portal(nm)
                entry_vals.append({
                    "name": nm,
                    "in_portal": bool(pm),
                    "portal_firm": (pm or {}).get("name"),
                    "portal_company_id": (pm or {}).get("company_id"),
                })
                if nm.lower() not in seen_names:
                    seen_names[nm.lower()] = entry_vals[-1]
            company_candidates.append({
                "table": tbl, "schema": sch, "column": c["col_name"],
                "row_count": rowcount.get(key, 0), "companies": entry_vals,
            })
            break  # one company column per table is enough

    # ---- Employee-master candidates (scored) ----
    HINTS = {
        "emp_name": ("empname", "employeename", "workername", "staffname", "labourname"),
        "father": ("father", "fname"),
        "pf": ("pfno", "pfnumber", "uan", "epf"),
        "esi": ("esino", "esicno", "esic", "esinumber"),
        "doj": ("doj", "dateofjoin", "joindate", "joiningdate"),
        "salary": ("basic", "rate", "salary", "wage"),
        "code": ("empcode", "employeecode", "cardno", "tokenno", "punchcode"),
    }
    employee_candidates: List[dict] = []
    for key, tcols in by_table.items():
        if rowcount.get(key, 0) <= 0:
            continue
        norm = [c["col_name"].lower().replace("_", "") for c in tcols]
        matched: Dict[str, str] = {}
        for hint, keys in HINTS.items():
            for i, nc in enumerate(norm):
                if any(k in nc for k in keys):
                    matched[hint] = tcols[i]["col_name"]
                    break
        score = len(matched)
        sch, tbl = key
        tname = tbl.lower()
        if any(h in tname for h in ("emp", "staff", "worker", "labour")):
            score += 2
        if score >= 3:
            employee_candidates.append({
                "table": tbl, "schema": sch, "row_count": rowcount.get(key, 0),
                "score": score, "matched_columns": matched,
            })
    employee_candidates.sort(key=lambda x: (-x["score"], -x["row_count"]))

    return {
        "db": db,
        "portal_firms": [p.get("name") for p in portal],
        "companies_found": sorted(seen_names.values(), key=lambda x: x["name"].lower()),
        "company_tables": company_candidates[:10],
        "employee_tables": employee_candidates[:15],
    }


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
