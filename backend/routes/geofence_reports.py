"""Geofence Monitor & Registers (Phases 3-8).

Employer-side visibility for the geofence/offline attendance engine:

* ``GET /api/admin/geofence/monitor``  — KPI summary + recent flagged punches
  (offline-synced, fake/mock GPS, outside-geofence, no-GPS, pending approval).
* ``GET /api/admin/geofence/report``   — register rows by type with optional
  CSV export (``format=csv``) for audits.

Data source is the existing ``attendance`` collection — punch records already
carry ``offline_punch``, ``mock_location``, ``outside_geofence``,
``gps_verified``, ``distance_m``, ``policy_mode`` and sync metadata.
"""
import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response

from server import db, get_user_from_token, require_role

router = APIRouter(prefix="/api", tags=["geofence-reports"])

REPORT_TYPES = ("flagged", "offline", "mock", "outside", "no_gps", "pending")

IST = timezone(timedelta(hours=5, minutes=30))


async def _guard(authorization: Optional[str], company_id: Optional[str]) -> str:
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if admin["role"] == "sub_admin" and company_id:
        from server import sub_admin_can_touch_company
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return company_id


def _range(from_: Optional[str], to: Optional[str]) -> (str, str):
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if not from_:
        from_ = today[:8] + "01"          # first of current month (IST)
    if not to:
        to = today
    return from_, to


async def _employees(company_id: str) -> Dict[str, Dict[str, Any]]:
    """user_id -> {name, employee_code, branch_name} for the firm."""
    out: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find(
        {"company_id": company_id},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "branch_name": 1},
    ):
        out[u["user_id"]] = u
    return out


def _is_flagged(r: Dict[str, Any]) -> bool:
    return bool(r.get("offline_punch") or r.get("mock_location")
                or r.get("outside_geofence") or r.get("gps_verified") is False)


def _match(r: Dict[str, Any], rtype: str) -> bool:
    if rtype == "offline":
        return bool(r.get("offline_punch"))
    if rtype == "mock":
        return bool(r.get("mock_location"))
    if rtype == "outside":
        return bool(r.get("outside_geofence"))
    if rtype == "no_gps":
        return r.get("gps_verified") is False or "nogps" in str(r.get("source") or "")
    if rtype == "pending":
        return (r.get("status") == "pending")
    return _is_flagged(r)  # flagged (default)


_PROJ = {"_id": 0, "record_id": 1, "user_id": 1, "date": 1, "kind": 1, "at": 1,
         "distance_m": 1, "outside_geofence": 1, "mock_location": 1,
         "offline_punch": 1, "gps_verified": 1, "gps_accuracy_m": 1,
         "status": 1, "attendance_status": 1, "policy_mode": 1, "source": 1,
         "worksite_name": 1, "synced_at": 1, "client_punch_at": 1,
         "punch_reason": 1}


async def _fetch(company_id: str, from_: str, to: str) -> (List[Dict[str, Any]], Dict[str, Dict[str, Any]]):
    emp = await _employees(company_id)
    if not emp:
        return [], {}
    rows = await db.attendance.find(
        {"user_id": {"$in": list(emp.keys())}, "date": {"$gte": from_, "$lte": to}},
        _PROJ,
    ).sort([("date", -1), ("at", -1)]).to_list(20000)
    return rows, emp


@router.get("/admin/geofence/monitor")
async def geofence_monitor(
    company_id: Optional[str] = None,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    cid = await _guard(authorization, company_id)
    from_, to = _range(from_, to)
    rows, emp = await _fetch(cid, from_, to)

    counts = {"total": len(rows), "offline": 0, "mock": 0, "outside": 0,
              "no_gps": 0, "pending": 0, "flagged": 0}
    by_mode: Dict[str, int] = {}
    flagged_rows: List[Dict[str, Any]] = []
    for r in rows:
        if r.get("offline_punch"):
            counts["offline"] += 1
        if r.get("mock_location"):
            counts["mock"] += 1
        if r.get("outside_geofence"):
            counts["outside"] += 1
        if r.get("gps_verified") is False or "nogps" in str(r.get("source") or ""):
            counts["no_gps"] += 1
        if r.get("status") == "pending":
            counts["pending"] += 1
        m = r.get("policy_mode") or "strict"
        by_mode[m] = by_mode.get(m, 0) + 1
        if _is_flagged(r):
            counts["flagged"] += 1
            if len(flagged_rows) < 20:
                u = emp.get(r.get("user_id")) or {}
                flagged_rows.append({**r, "employee_name": u.get("name"),
                                     "employee_code": u.get("employee_code")})
    return {"company_id": cid, "from": from_, "to": to,
            "counts": counts, "by_mode": by_mode, "recent_flagged": flagged_rows}


@router.get("/admin/geofence/report")
async def geofence_report(
    type: str = "flagged",
    company_id: Optional[str] = None,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    format: str = "json",
    authorization: Optional[str] = Header(None),
):
    if type not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {REPORT_TYPES}")
    cid = await _guard(authorization, company_id)
    from_, to = _range(from_, to)
    rows, emp = await _fetch(cid, from_, to)

    out: List[Dict[str, Any]] = []
    for r in rows:
        if not _match(r, type):
            continue
        u = emp.get(r.get("user_id")) or {}
        out.append({
            "date": r.get("date"),
            "employee_code": u.get("employee_code"),
            "employee_name": u.get("name"),
            "branch": u.get("branch_name"),
            "kind": r.get("kind"),
            "time": (r.get("at") or "")[11:19],
            "worksite": r.get("worksite_name"),
            "distance_m": r.get("distance_m"),
            "policy_mode": r.get("policy_mode"),
            "status": r.get("attendance_status") or r.get("status"),
            "offline_punch": bool(r.get("offline_punch")),
            "captured_at": (r.get("client_punch_at") or "")[:19],
            "synced_at": (r.get("synced_at") or "")[:19],
            "mock_location": bool(r.get("mock_location")),
            "gps_accuracy_m": r.get("gps_accuracy_m"),
            "outside_geofence": bool(r.get("outside_geofence")),
            "reason": r.get("punch_reason"),
        })
        if len(out) >= 5000:
            break

    if format == "csv":
        buf = io.StringIO()
        cols = ["date", "employee_code", "employee_name", "branch", "kind",
                "time", "worksite", "distance_m", "policy_mode", "status",
                "offline_punch", "captured_at", "synced_at", "mock_location",
                "gps_accuracy_m", "outside_geofence", "reason"]
        w = csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        for row in out:
            w.writerow(row)
        fname = f"geofence_{type}_{from_}_{to}.csv"
        return Response(content=buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={fname}"})
    return {"company_id": cid, "type": type, "from": from_, "to": to,
            "count": len(out), "rows": out}
