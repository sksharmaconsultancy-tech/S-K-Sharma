"""Iter 545 — MULTIPLE PUNCH REPORT + PUNCH EXCEPTION REPORT (user spec).

* GET /api/admin/multi-punch/report — per employee-day punch register:
  every counted punch, chronological IN→OUT pairs, Duty / Break / OT hours
  and "Punches n / max" against the firm's Attendance Punch Policy.
* GET /api/admin/multi-punch/exceptions — the Punch Exception Log
  (max-limit exceeded, invalid sequence, duplicate IN/OUT …).
Read-only — payroll, salary and attendance data are never touched.
"""
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException

from server import db, get_user_from_token, require_role  # noqa: E402
from utils.punch_policy import resolve_punch_policy  # noqa: E402

router = APIRouter(prefix="/api/admin/multi-punch", tags=["multi-punch"])


async def _auth(authorization: Optional[str], company_id: str):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    if user["role"] == "company_admin" and user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not your firm")
    return user


def _dt(at: str) -> datetime:
    return datetime.fromisoformat(str(at).replace("Z", "+00:00"))


def _hhmm(minutes: float) -> str:
    m = max(0, int(round(minutes)))
    return f"{m // 60:02d}:{m % 60:02d}"


def _pair(punches: List[dict]):
    """Chronological IN→OUT pairing (mirror of the attendance engine)."""
    pairs: List[Dict[str, Any]] = []
    unpaired = 0
    open_in: Optional[dict] = None
    for p in sorted(punches, key=lambda x: x.get("at") or ""):
        if p["kind"] == "in":
            if open_in is not None:
                unpaired += 1
            open_in = p
        else:
            if open_in is None:
                unpaired += 1
                continue
            mins = (_dt(p["at"]) - _dt(open_in["at"])).total_seconds() / 60.0
            if mins > 0:
                pairs.append({"in": str(open_in["at"])[11:16],
                              "out": str(p["at"])[11:16],
                              "minutes": int(round(mins))})
            open_in = None
    if open_in is not None:
        unpaired += 1
    return pairs, unpaired


@router.get("/report")
async def multi_punch_report(
    company_id: str,
    month: str,
    user_id: Optional[str] = None,
    only_multiple: bool = True,
    authorization: Optional[str] = Header(None),
):
    """Punch register. ``only_multiple=true`` (default) lists only the days
    with MORE than 2 counted punches; ``false`` lists every punched day."""
    await _auth(authorization, company_id)
    if len(month) != 7:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "attendance_policy": 1}) or {}
    pol = company.get("attendance_policy") or {}
    quota_min = float(pol.get("full_day_hours") or 8.0) * 60.0

    q_users: Dict[str, Any] = {"company_id": company_id, "role": "employee"}
    if user_id:
        q_users["user_id"] = user_id
    employees = await db.users.find(
        q_users,
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
         "attendance_policy_override": 1},
    ).sort([("employee_code", 1)]).to_list(4000)
    emp_by_id = {e["user_id"]: e for e in employees}
    uids = list(emp_by_id.keys())

    date_from, date_to = f"{month}-01", f"{month}-31"
    by_user_day: Dict[str, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
    async for p in db.attendance.find(
        {"user_id": {"$in": uids}, "date": {"$gte": date_from, "$lte": date_to},
         "kind": {"$in": ["in", "out"]}},
        {"_id": 0, "user_id": 1, "date": 1, "kind": 1, "at": 1,
         "source": 1, "status": 1},
    ).sort([("user_id", 1), ("at", 1)]):
        by_user_day[p["user_id"]][p["date"]].append(p)

    # Exception counts for the month (badge on the row).
    exc_by_user_day: Dict[str, int] = defaultdict(int)
    async for e in db.punch_exceptions.find(
        {"company_id": company_id, "date": {"$gte": date_from, "$lte": date_to}},
        {"_id": 0, "user_id": 1, "date": 1},
    ):
        exc_by_user_day[f"{e.get('user_id')}|{e.get('date')}"] += 1

    rows: List[Dict[str, Any]] = []
    for uid, days in by_user_day.items():
        emp = emp_by_id.get(uid) or {}
        ppol = resolve_punch_policy(emp, company)
        max_allowed = int(ppol.get("effective_max") or 0)
        for d in sorted(days.keys()):
            counted = [p for p in days[d]
                       if (p.get("status") or "approved") in ("approved", "pending")]
            if not counted:
                continue
            if only_multiple and len(counted) <= 2 \
                    and not exc_by_user_day.get(f"{uid}|{d}"):
                continue
            pairs, unpaired = _pair(counted)
            worked = sum(p["minutes"] for p in pairs)
            duty = min(worked, quota_min) if quota_min > 0 else worked
            ot = max(0.0, worked - quota_min) if quota_min > 0 else 0.0
            # Break = gaps between consecutive pairs (spec §5).
            brk = 0.0
            for i in range(1, len(pairs)):
                gap = (
                    _dt(f"{d}T{pairs[i]['in']}:00")
                    - _dt(f"{d}T{pairs[i - 1]['out']}:00")
                ).total_seconds() / 60.0
                if gap > 0:
                    brk += gap
            rows.append({
                "user_id": uid,
                "employee_code": emp.get("employee_code"),
                "name": emp.get("name"),
                "date": d,
                "punches": [
                    {"time": str(p["at"])[11:16], "kind": p["kind"],
                     "source": p.get("source"), "status": p.get("status")}
                    for p in sorted(counted, key=lambda x: x.get("at") or "")
                ],
                "pairs": pairs,
                "unpaired": unpaired,
                "duty_hhmm": _hhmm(duty),
                "break_hhmm": _hhmm(brk),
                "ot_hhmm": _hhmm(ot),
                "punch_count": len(counted),
                "max_allowed": max_allowed or None,
                "limit_reached": bool(max_allowed and len(counted) >= max_allowed),
                "exception_count": exc_by_user_day.get(f"{uid}|{d}", 0),
            })
    rows.sort(key=lambda r: (str(r.get("employee_code") or ""), r["date"]))
    return {"month": month, "rows": rows,
            "total_days": len(rows),
            "quota_minutes": int(quota_min)}


@router.get("/exceptions")
async def punch_exceptions(
    company_id: str,
    month: str,
    user_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Punch Exception Log for the firm + month."""
    await _auth(authorization, company_id)
    if len(month) != 7:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    q: Dict[str, Any] = {"company_id": company_id,
                         "date": {"$gte": f"{month}-01", "$lte": f"{month}-31"}}
    if user_id:
        q["user_id"] = user_id
    rows = await db.punch_exceptions.find(q, {"_id": 0}).sort(
        [("date", -1), ("at", -1)]).to_list(2000)
    return {"month": month, "rows": rows, "total": len(rows)}
