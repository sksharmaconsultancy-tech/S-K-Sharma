"""Iter 145 — Punch Log Report (Utility).

Full audit trail of every biometric / app / manual punch, filterable by
date range, machine (device serial or source category) and firm.

Endpoints
---------
GET /api/admin/punch-logs         → JSON rows + machine list for filters
GET /api/admin/punch-logs.xlsx    → Excel download (same filters)
"""
from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from server import (  # noqa: E402
    db,
    get_user_from_token,
    sub_admin_can_touch_company,
)

router = APIRouter(prefix="/api/admin", tags=["punch-logs"])

MAX_JSON_ROWS = 2000
MAX_XLSX_ROWS = 100000


def _source_label(rec: dict) -> str:
    """Human machine/source label for a punch record."""
    serial = str(rec.get("device_serial") or "")
    src = str(rec.get("source") or "")
    if serial.startswith("import:") or src.startswith("import:") or src.startswith("zk_dat"):
        return "Import (.dat/.TXT)"
    if serial:
        return f"Device {serial}"
    if src.startswith("zkteco:"):
        return f"Device {src.split(':', 1)[1]}"
    if src == "manual_admin":
        return "Manual (Admin)"
    if src == "roster":
        return "Roster"
    return "Mobile App"


def _machine_key(rec: dict) -> str:
    serial = str(rec.get("device_serial") or "")
    src = str(rec.get("source") or "")
    if serial.startswith("import:") or src.startswith("import:") or src.startswith("zk_dat"):
        return "import"
    if serial:
        return f"device:{serial}"
    if src.startswith("zkteco:"):
        return f"device:{src.split(':', 1)[1]}"
    if src == "manual_admin":
        return "manual_admin"
    return "app"


async def _query_rows(
    admin: dict,
    company_id: Optional[str],
    machine: Optional[str],
    from_date: Optional[str],
    to_date: Optional[str],
    limit: int,
) -> Dict[str, Any]:
    q: Dict[str, Any] = {"kind": {"$in": ["in", "out"]}}
    if company_id:
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(403, "No access to this firm")
        q["company_id"] = company_id
    elif (admin.get("role") == "sub_admin"
          and (admin.get("sub_admin_company_scope") or "all") != "all"):
        q["company_id"] = {"$in": admin.get("sub_admin_company_ids") or []}
    date_q: Dict[str, str] = {}
    if from_date:
        date_q["$gte"] = from_date
    if to_date:
        date_q["$lte"] = to_date
    if date_q:
        q["date"] = date_q

    recs = await db.attendance.find(
        q,
        {"_id": 0, "record_id": 1, "user_id": 1, "company_id": 1, "date": 1,
         "at": 1, "kind": 1, "source": 1, "device_serial": 1, "status": 1,
         "branch_name": 1},
    ).sort([("at", -1)]).to_list(MAX_XLSX_ROWS)

    # Machine filter applied post-query (source label is derived).
    if machine:
        recs = [r for r in recs if _machine_key(r) == machine]

    # Resolve employee + firm names.
    uids = list({r.get("user_id") for r in recs if r.get("user_id")})
    users: Dict[str, dict] = {}
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "bio_code": 1},
        ):
            users[u["user_id"]] = u
    cids = list({r.get("company_id") for r in recs if r.get("company_id")})
    firms: Dict[str, str] = {}
    if cids:
        async for c in db.companies.find(
            {"company_id": {"$in": cids}}, {"_id": 0, "company_id": 1, "name": 1},
        ):
            firms[c["company_id"]] = c.get("name") or c["company_id"]

    rows: List[Dict[str, Any]] = []
    machines: Dict[str, str] = {}
    for r in recs:
        u = users.get(r.get("user_id") or "", {})
        at = str(r.get("at") or "")
        mkey = _machine_key(r)
        mlabel = _source_label(r)
        machines.setdefault(mkey, mlabel)
        rows.append({
            "date": r.get("date") or at[:10],
            "time": at[11:19] if len(at) >= 19 else at[11:16],
            "kind": r.get("kind"),
            "employee_code": u.get("employee_code") or "",
            "name": u.get("name") or r.get("user_id") or "",
            "bio_code": u.get("bio_code") or "",
            "machine": mlabel,
            "machine_key": mkey,
            "company_name": firms.get(r.get("company_id") or "", ""),
            "status": r.get("status") or "",
            "source": r.get("source") or "",
        })
    return {"rows": rows, "machines": machines}


@router.get("/punch-logs")
async def punch_logs(
    company_id: Optional[str] = Query(None),
    machine: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(403, "Admin only")
    if admin.get("role") == "company_admin":
        company_id = admin.get("company_id")
    data = await _query_rows(admin, company_id, machine, from_date, to_date, MAX_JSON_ROWS)
    rows = data["rows"]
    return {
        "total": len(rows),
        "truncated": len(rows) > MAX_JSON_ROWS,
        "rows": rows[:MAX_JSON_ROWS],
        "machines": [
            {"key": k, "label": v} for k, v in sorted(data["machines"].items())
        ],
    }


@router.get("/daily-attendance")
async def daily_attendance(
    date: str = Query(..., description="YYYY-MM-DD"),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Iter 148 — Date-wise attendance summary, firm-wise (employer PWA
    dashboard). One row per employee with all their punches for the day,
    first-IN / last-OUT, worked hours and Present/Absent status."""
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(403, "Admin only")
    if admin.get("role") == "company_admin":
        company_id = admin.get("company_id")

    uq: Dict[str, Any] = {"role": "employee", "approval_status": "approved"}
    if company_id:
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(403, "No access to this firm")
        uq["company_id"] = company_id
    elif (admin.get("role") == "sub_admin"
          and (admin.get("sub_admin_company_scope") or "all") != "all"):
        uq["company_id"] = {"$in": admin.get("sub_admin_company_ids") or []}

    employees = await db.users.find(
        uq, {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
             "bio_code": 1, "company_id": 1},
    ).to_list(3000)

    aq: Dict[str, Any] = {"date": date, "kind": {"$in": ["in", "out"]}}
    if company_id:
        aq["company_id"] = company_id
    recs = await db.attendance.find(
        aq, {"_id": 0, "user_id": 1, "at": 1, "kind": 1,
             "source": 1, "device_serial": 1},
    ).sort([("at", 1)]).to_list(50000)

    by_user: Dict[str, List[dict]] = {}
    for r in recs:
        by_user.setdefault(r.get("user_id") or "", []).append(r)

    cids = list({e.get("company_id") for e in employees if e.get("company_id")})
    firms: Dict[str, str] = {}
    if cids:
        async for c in db.companies.find(
            {"company_id": {"$in": cids}}, {"_id": 0, "company_id": 1, "name": 1},
        ):
            firms[c["company_id"]] = c.get("name") or c["company_id"]

    def _mins(at: str) -> Optional[int]:
        # Wall-clock convention: read HH:MM verbatim from the ISO string.
        try:
            return int(at[11:13]) * 60 + int(at[14:16])
        except Exception:
            return None

    rows: List[Dict[str, Any]] = []
    present = 0
    for e in employees:
        precs = by_user.get(e["user_id"], [])
        punches = [{
            "time": str(p.get("at") or "")[11:16],
            "kind": p.get("kind"),
            "machine": _source_label(p),
        } for p in precs]
        first_in = next((p for p in precs if p.get("kind") == "in"), None)
        last_out = next((p for p in reversed(precs) if p.get("kind") == "out"), None)
        # Worked minutes: sum of IN→next-OUT pairs.
        worked = 0
        open_in: Optional[int] = None
        for p in precs:
            m = _mins(str(p.get("at") or ""))
            if m is None:
                continue
            if p.get("kind") == "in":
                open_in = m
            elif p.get("kind") == "out" and open_in is not None:
                if m >= open_in:
                    worked += m - open_in
                open_in = None
        status = "present" if precs else "absent"
        if precs:
            present += 1
        rows.append({
            "user_id": e["user_id"],
            "name": e.get("name") or "",
            "employee_code": e.get("employee_code") or "",
            "company_id": e.get("company_id"),
            "company_name": firms.get(e.get("company_id") or "", ""),
            "status": status,
            "punches": punches,
            "first_in": str(first_in.get("at"))[11:16] if first_in else None,
            "last_out": str(last_out.get("at"))[11:16] if last_out else None,
            "worked_hrs": round(worked / 60, 2) if worked else 0,
            "still_in": bool(precs) and precs[-1].get("kind") == "in",
        })

    rows.sort(key=lambda r: (r["status"] != "present",
                             r.get("first_in") or "99:99", r["name"].lower()))
    return {
        "date": date,
        "total": len(rows),
        "present": present,
        "absent": len(rows) - present,
        "rows": rows,
    }


@router.get("/attendance-report/day-counts")
async def attendance_day_counts(
    month: str = Query(..., description="YYYY-MM"),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Iter 154 — day-wise present count for a month (1–31), including how
    many employees worked OT (2nd IN→OUT pair) each day. Tapping a count in
    the UI deep-links to /daily-attendance for the full employee list."""
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(403, "Admin only")
    if admin.get("role") == "company_admin":
        company_id = admin.get("company_id")
    import re as _re
    if not _re.fullmatch(r"\d{4}-\d{2}", month or ""):
        raise HTTPException(400, "month must be YYYY-MM")

    aq: Dict[str, Any] = {
        "date": {"$gte": f"{month}-01", "$lte": f"{month}-31"},
        "kind": {"$in": ["in", "out"]},
        "status": {"$ne": "rejected"},
    }
    if company_id:
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(403, "No access to this firm")
        aq["company_id"] = company_id
    elif (admin.get("role") == "sub_admin"
          and (admin.get("sub_admin_company_scope") or "all") != "all"):
        aq["company_id"] = {"$in": admin.get("sub_admin_company_ids") or []}

    recs = await db.attendance.find(
        aq, {"_id": 0, "date": 1, "user_id": 1, "kind": 1},
    ).to_list(200000)

    # per day: distinct present users + users with ≥2 IN punches (OT pair).
    per_day: Dict[str, Dict[str, Any]] = {}
    for r in recs:
        d = per_day.setdefault(r["date"], {"users": set(), "ins": {}})
        d["users"].add(r["user_id"])
        if r["kind"] == "in":
            d["ins"][r["user_id"]] = d["ins"].get(r["user_id"], 0) + 1

    from calendar import monthrange
    y, m = int(month[:4]), int(month[5:7])
    ndays = monthrange(y, m)[1]
    days = []
    tot_present = tot_ot = 0
    for i in range(1, ndays + 1):
        date = f"{month}-{i:02d}"
        d = per_day.get(date)
        present = len(d["users"]) if d else 0
        ot = sum(1 for c in (d["ins"].values() if d else []) if c >= 2)
        tot_present += present
        tot_ot += ot
        days.append({"date": date, "present": present, "ot_count": ot})
    return {"month": month, "days": days,
            "total_present_mandays": tot_present, "total_ot_mandays": tot_ot}


@router.get("/punch-logs.xlsx")
async def punch_logs_xlsx(
    company_id: Optional[str] = Query(None),
    machine: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(403, "Admin only")
    if admin.get("role") == "company_admin":
        company_id = admin.get("company_id")
    data = await _query_rows(admin, company_id, machine, from_date, to_date, MAX_XLSX_ROWS)

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Punch Log"
    headers = ["Sr", "Date", "Time", "IN/OUT", "Emp Code", "Employee Name",
               "Bio Code", "Machine / Source", "Firm", "Status"]
    ws.append(headers)
    fill = PatternFill("solid", fgColor="1F4E79")
    for col in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = fill
    for i, r in enumerate(data["rows"], start=1):
        ws.append([i, r["date"], r["time"], (r["kind"] or "").upper(),
                   r["employee_code"], r["name"], r["bio_code"],
                   r["machine"], r["company_name"], r["status"]])
    widths = [6, 12, 10, 8, 10, 26, 9, 22, 24, 10]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"Punch_Log_{from_date or 'all'}_{to_date or 'all'}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
