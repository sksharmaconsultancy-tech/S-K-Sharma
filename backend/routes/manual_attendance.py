"""Iter 688 — MANUAL ATTENDANCE (Excel-style editable monthly sheet).

Additive OVERLAY on the existing attendance system — punch records are
NEVER modified or deleted. Manual marks live in db.manual_attendance;
approval requests in db.attendance_change_requests; firm-level settings
in firm_masters.manual_attendance.

  GET  /api/admin/manual-attendance/settings/{cid}       · POST same
  GET  /api/admin/manual-attendance/monthly              (grid data)
  POST /api/admin/manual-attendance/save                 (direct/approval)
  GET  /api/admin/manual-attendance/approvals            (pending list)
  POST /api/admin/manual-attendance/approvals/decide     (approve/reject)
  GET  /api/admin/manual-attendance/monthly.xlsx         (grid export)
"""
import io
import uuid
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from server import db, get_user_from_token, require_role, now_iso  # noqa: E402

router = APIRouter(prefix="/api/admin/manual-attendance",
                   tags=["manual-attendance"])

CODES = ("P", "A", "L", "WO", "CO", "HD")
_DEF = {"enabled": True, "approval_required": False, "require_reason": False,
        "maker_checker": True}


async def _auth(authorization):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    return admin


def _mm(month: str) -> str:
    """Accept MM-YYYY or YYYY-MM → YYYY-MM."""
    s = (month or "").strip()
    if len(s) == 7 and s[2] == "-":
        return f"{s[3:]}-{s[:2]}"
    return s


async def _settings(cid: str) -> dict:
    fmdoc = await db.firm_masters.find_one(
        {"company_id": cid}, {"_id": 0, "manual_attendance": 1}) or {}
    return {**_DEF, **(fmdoc.get("manual_attendance") or {})}


@router.get("/settings/{cid}")
async def get_settings(cid: str, authorization: Optional[str] = Header(None)):
    await _auth(authorization)
    return await _settings(cid)


@router.post("/settings/{cid}")
async def save_settings(cid: str, payload: Dict[str, Any] = Body(...),
                        authorization: Optional[str] = Header(None)):
    admin = await _auth(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    doc = {k: bool(payload.get(k, _DEF[k])) for k in _DEF}
    await db.firm_masters.update_one(
        {"company_id": cid}, {"$set": {"manual_attendance": doc}}, upsert=True)
    return {"ok": True, **doc}


async def _grid(cid: str, month: str) -> dict:
    y, m = int(month[:4]), int(month[5:7])
    ndays = monthrange(y, m)[1]
    days = [f"{month}-{d:02d}" for d in range(1, ndays + 1)]
    comp = await db.companies.find_one(
        {"company_id": cid}, {"_id": 0, "attendance_policy": 1})
    firm_wo = {int(x) for x in ((comp or {}).get("attendance_policy")
                                or {}).get("weekly_off_days") or []}
    emps = await db.users.find(
        {"company_id": cid, "role": "employee", "disabled": {"$ne": True}},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
         "department": 1, "weekly_off_days_override": 1}).to_list(5000)
    emps.sort(key=lambda u: str(u.get("employee_code") or "").zfill(8))
    # base statuses from EXISTING punch data (read-only)
    punched: Dict[tuple, bool] = {}
    async for a in db.attendance.find(
            {"company_id": cid, "date": {"$gte": days[0], "$lte": days[-1]}},
            {"_id": 0, "user_id": 1, "date": 1}):
        punched[(a["user_id"], a["date"])] = True
    manual = {(x["user_id"], x["date"]): x async for x in
              db.manual_attendance.find(
                  {"company_id": cid,
                   "date": {"$gte": days[0], "$lte": days[-1]}}, {"_id": 0})}
    pending = {(x["user_id"], x["date"]): x async for x in
               db.attendance_change_requests.find(
                   {"company_id": cid, "status": "PENDING",
                    "date": {"$gte": days[0], "$lte": days[-1]}}, {"_id": 0})}
    today = date.today().isoformat()
    rows = []
    for u in emps:
        _ov = u.get("weekly_off_days_override")
        wo_days = ({int(x) for x in _ov} if isinstance(_ov, list) and _ov
                   else firm_wo)
        cells, tot = {}, {c: 0 for c in CODES}
        for d in days:
            mk = manual.get((u["user_id"], d))
            if mk:
                st, src = mk["status"], "manual"
            elif punched.get((u["user_id"], d)):
                st, src = "P", "punch"
            elif date.fromisoformat(d).weekday() in wo_days:
                st, src = "WO", "policy"
            else:
                st, src = ("A", "auto") if d <= today else ("", "")
            pq = pending.get((u["user_id"], d))
            cells[d] = {"st": st, "src": src,
                        "pending": pq["requested_status"] if pq else None}
            if st in tot:
                tot[st] += 1
        rows.append({"user_id": u["user_id"],
                     "employee_code": u.get("employee_code") or "",
                     "name": u.get("name") or "",
                     "department": u.get("department") or "",
                     "cells": cells, "totals": tot})
    summary = {c: sum(r["totals"][c] for r in rows) for c in CODES}
    summary.update({
        "employees": len(rows),
        "manual": sum(1 for r in rows for c in r["cells"].values()
                      if c["src"] == "manual"),
        "pending": len(pending)})
    return {"month": month, "days": days,
            "weekdays": [date.fromisoformat(d).strftime("%a") for d in days],
            "rows": rows, "summary": summary}


@router.get("/monthly")
async def monthly(company_id: str = Query(...), month: str = Query(...),
                  authorization: Optional[str] = Header(None)):
    await _auth(authorization)
    g = await _grid(company_id, _mm(month))
    g["settings"] = await _settings(company_id)
    return g


@router.post("/save")
async def save(payload: Dict[str, Any] = Body(...),
               authorization: Optional[str] = Header(None)):
    admin = await _auth(authorization)
    cid = payload.get("company_id")
    changes = payload.get("changes") or []
    if not cid or not changes:
        raise HTTPException(status_code=400, detail="company_id and changes required")
    st = await _settings(cid)
    if not st["enabled"]:
        raise HTTPException(status_code=403,
                            detail="Manual attendance editing is disabled in Firm Master")
    if st["require_reason"] and any(not str(c.get("reason") or "").strip()
                                    for c in changes):
        raise HTTPException(status_code=400,
                            detail="Reason is required for every manual change (Firm Master rule)")
    who = admin.get("name") or admin.get("email")
    applied = queued = 0
    for c in changes:
        uid, d = c.get("user_id"), str(c.get("date") or "")[:10]
        new = str(c.get("status") or "").upper()
        if new not in CODES or not uid:
            continue
        audit = {"company_id": cid, "user_id": uid, "date": d,
                 "previous_status": c.get("previous_status"),
                 "requested_status": new,
                 "reason": str(c.get("reason") or "")[:300],
                 "requested_by": who, "requested_by_id": admin.get("user_id"),
                 "requested_at": now_iso(), "source": "manual"}
        if st["approval_required"]:
            await db.attendance_change_requests.update_one(
                {"company_id": cid, "user_id": uid, "date": d,
                 "status": "PENDING"},
                {"$set": {**audit, "status": "PENDING",
                          "request_id": f"acr_{uuid.uuid4().hex[:10]}"}},
                upsert=True)
            queued += 1
        else:
            await db.manual_attendance.update_one(
                {"company_id": cid, "user_id": uid, "date": d},
                {"$set": {"status": new, "updated_by": who,
                          "updated_at": now_iso(), "source": "manual"}},
                upsert=True)
            await db.attendance_change_audit.insert_one(
                {**audit, "status": "APPLIED"})
            applied += 1
    if queued:
        await db.notifications.insert_one({
            "notification_id": f"ntf_{uuid.uuid4().hex[:10]}",
            "company_id": cid, "audience": "admins",
            "title": "New Attendance Change Request",
            "body": f"{queued} attendance change(s) submitted by {who} — pending approval.",
            "category": "attendance", "created_at": now_iso(), "read_by": []})
    return {"ok": True, "applied": applied, "pending": queued,
            "approval_required": st["approval_required"]}


@router.get("/approvals")
async def approvals(company_id: str = Query(...),
                    authorization: Optional[str] = Header(None)):
    await _auth(authorization)
    reqs = await db.attendance_change_requests.find(
        {"company_id": company_id, "status": "PENDING"},
        {"_id": 0}).sort("requested_at", -1).to_list(500)
    names = {u["user_id"]: u async for u in db.users.find(
        {"company_id": company_id, "role": "employee"},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
         "department": 1})}
    for r in reqs:
        u = names.get(r["user_id"]) or {}
        r.update(name=u.get("name"), employee_code=u.get("employee_code"),
                 department=u.get("department"))
    return {"requests": reqs}


@router.post("/approvals/decide")
async def decide(payload: Dict[str, Any] = Body(...),
                 authorization: Optional[str] = Header(None)):
    admin = await _auth(authorization)
    cid = payload.get("company_id")
    ids = payload.get("request_ids") or []
    action = str(payload.get("action") or "").upper()
    reason = str(payload.get("reason") or "")[:300]
    if action not in ("APPROVE", "REJECT") or not ids:
        raise HTTPException(status_code=400, detail="action and request_ids required")
    st = await _settings(cid)
    who = admin.get("name") or admin.get("email")
    done = 0
    for rid in ids[:500]:
        r = await db.attendance_change_requests.find_one(
            {"request_id": rid, "company_id": cid, "status": "PENDING"})
        if not r:
            continue
        # Maker-checker: maker cannot approve own request (Firm Master rule)
        if st["maker_checker"] and r.get("requested_by_id") == admin.get("user_id"):
            raise HTTPException(status_code=403,
                                detail="Maker cannot approve own request")
        upd = {"status": "APPROVED" if action == "APPROVE" else "REJECTED",
               "decided_by": who, "decided_by_id": admin.get("user_id"),
               "decided_at": now_iso(), "rejection_reason": reason or None}
        await db.attendance_change_requests.update_one(
            {"request_id": rid}, {"$set": upd})
        if action == "APPROVE":
            await db.manual_attendance.update_one(
                {"company_id": cid, "user_id": r["user_id"], "date": r["date"]},
                {"$set": {"status": r["requested_status"], "updated_by": who,
                          "updated_at": now_iso(), "source": "manual",
                          "approved": True}}, upsert=True)
        await db.attendance_change_audit.insert_one(
            {k: v for k, v in {**r, **upd}.items() if k != "_id"})
        done += 1
    return {"ok": True, "decided": done}


@router.get("/monthly.xlsx")
async def monthly_xlsx(company_id: str = Query(...), month: str = Query(...),
                       authorization: Optional[str] = Header(None),
                       token: Optional[str] = Query(None)):
    if token and not authorization:
        authorization = f"Bearer {token}"
    await _auth(authorization)
    g = await _grid(company_id, _mm(month))
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"
    hdr = (["Code", "Employee Name", "Department"]
           + [d[8:10] for d in g["days"]] + list(CODES))
    ws.append(hdr)
    ws.append(["", "", ""] + g["weekdays"] + [""] * len(CODES))
    for i in (1, 2):
        for c in ws[i]:
            c.font = Font(bold=True)
            c.alignment = Alignment(horizontal="center")
    for r in g["rows"]:
        ws.append([r["employee_code"], r["name"], r["department"]]
                  + [r["cells"][d]["st"] for d in g["days"]]
                  + [r["totals"][c] for c in CODES])
    for row in ws.iter_rows(min_row=3):
        for c in row[3:]:
            c.alignment = Alignment(horizontal="center")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename=attendance-{_mm(month)}.xlsx"})
