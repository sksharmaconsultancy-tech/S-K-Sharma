"""Iter 741 — PROBATION → CONFIRMATION module + WEEKOFF calendar preview.

Extension only — Employee Master fields are ADDITIVE on users docs
(probation_applicable, probation_months, probation_start, confirmation_due,
employment_status, ...). No attendance/salary logic touched. History in
``probation_history`` (immutable). Letters via existing HR Letters module
(types: confirmation / probation_extension).
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db, get_user_from_token, require_role, now_iso,
    apply_weekoff_rules_for_date, apply_employee_policy_override,
)

router = APIRouter(prefix="/api/admin", tags=["probation-weekoff"])
_ROLES = ["super_admin", "sub_admin", "company_admin"]


def _today() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


async def _gate(authorization, company_id):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ROLES)
    cid = admin.get("company_id") if admin["role"] == "company_admin" else company_id
    if not cid:
        raise HTTPException(status_code=400, detail="company_id required")
    return admin, cid


def _add_months(iso: str, months: int) -> str:
    d = datetime.strptime(iso, "%Y-%m-%d")
    m = d.month - 1 + months
    y, m2 = d.year + m // 12, m % 12 + 1
    import calendar
    day = min(d.day, calendar.monthrange(y, m2)[1])
    return f"{y:04d}-{m2:02d}-{day:02d}"


def _norm_date(v) -> Optional[str]:
    """Accept YYYY-MM-DD or DD-MM-YYYY; return ISO or None."""
    s = str(v or "").strip()
    if not s:
        return None
    import re
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", s)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _prob_status(u: dict, today: str, reminder_days: int) -> str:
    st = u.get("employment_status")
    if st in ("confirmed", "exited"):
        return st
    if not u.get("probation_applicable"):
        return "not_applicable"
    due = u.get("confirmation_due")
    if not due:
        return "on_probation"
    if due < today:
        return "overdue"
    soon = (datetime.strptime(today, "%Y-%m-%d")
            + timedelta(days=reminder_days)).strftime("%Y-%m-%d")
    if due <= soon:
        return "due_soon"
    return "extended" if st == "extended" else "on_probation"


async def _policy(cid: str) -> dict:
    c = await db.companies.find_one({"company_id": cid}, {"_id": 0, "probation_policy": 1})
    p = (c or {}).get("probation_policy") or {}
    return {"default_months": int(p.get("default_months") or 6),
            "reminder_days": int(p.get("reminder_days") or 30),
            "extension_allowed": p.get("extension_allowed", True),
            "max_extension_months": int(p.get("max_extension_months") or 6),
            "confirmation_letter_required": bool(p.get("confirmation_letter_required", True)),
            "notice_period_after_confirmation": p.get("notice_period_after_confirmation") or "one (1) month",
            "active": p.get("active", True)}


async def _hist(admin, uid, action, prev, new, reason=None, remarks=None):
    await db.probation_history.insert_one({
        "hist_id": f"pbh_{uuid.uuid4().hex[:10]}", "user_id": uid,
        "action": action, "prev": prev, "new": new,
        "reason": reason, "remarks": remarks,
        "by": admin["user_id"], "by_name": admin.get("name") or admin.get("email"),
        "at": now_iso()})


@router.get("/probation/policy")
async def probation_policy_get(company_id: Optional[str] = Query(None),
                               authorization: Optional[str] = Header(None)):
    _, cid = await _gate(authorization, company_id)
    return {"policy": await _policy(cid)}


@router.post("/probation/policy")
async def probation_policy_set(body: Dict[str, Any] = Body(...),
                               authorization: Optional[str] = Header(None)):
    admin, cid = await _gate(authorization, body.get("company_id"))
    months = int(body.get("default_months") or 6)
    if not 1 <= months <= 24:
        raise HTTPException(status_code=400, detail="default_months must be 1-24")
    p = {"default_months": months,
         "reminder_days": int(body.get("reminder_days") or 30),
         "extension_allowed": bool(body.get("extension_allowed", True)),
         "max_extension_months": int(body.get("max_extension_months") or 6),
         "confirmation_letter_required": bool(body.get("confirmation_letter_required", True)),
         "notice_period_after_confirmation": str(body.get("notice_period_after_confirmation") or "one (1) month"),
         "active": bool(body.get("active", True)),
         "updated_by": admin["user_id"], "updated_at": now_iso()}
    await db.companies.update_one({"company_id": cid}, {"$set": {"probation_policy": p}})
    return {"ok": True, "policy": p}


@router.get("/probation/list")
async def probation_list(company_id: Optional[str] = Query(None),
                         status: Optional[str] = Query(None),
                         q: Optional[str] = Query(None),
                         authorization: Optional[str] = Header(None)):
    """Dashboard counts + employee list with computed probation status."""
    _, cid = await _gate(authorization, company_id)
    pol = await _policy(cid)
    today = _today()
    emps = await db.users.find(
        {"company_id": cid, "role": "employee", "status": {"$ne": "inactive"}},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "doj": 1,
         "date_of_joining": 1, "department": 1, "designation": 1,
         "probation_applicable": 1, "probation_months": 1, "probation_start": 1,
         "confirmation_due": 1, "original_confirmation_due": 1,
         "employment_status": 1, "confirmation_date": 1,
         "home_branch_id": 1, "branch_name": 1}).sort("name", 1).to_list(3000)
    rows = []
    counts = {"on_probation": 0, "due_soon": 0, "due_15": 0, "overdue": 0,
              "extended": 0, "confirmed_this_month": 0, "total_probation": 0}
    month = today[:7]
    soon15 = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=15)).strftime("%Y-%m-%d")
    for u in emps:
        st = _prob_status(u, today, pol["reminder_days"])
        u["probation_status"] = st
        due = u.get("confirmation_due")
        u["days_remaining"] = ((datetime.strptime(due, "%Y-%m-%d")
                                - datetime.strptime(today, "%Y-%m-%d")).days
                               if due else None)
        if st in ("on_probation", "due_soon", "overdue", "extended"):
            counts["total_probation"] += 1
        if st == "on_probation":
            counts["on_probation"] += 1
        if st == "due_soon":
            counts["due_soon"] += 1
            if due and due <= soon15:
                counts["due_15"] += 1
        if st == "overdue":
            counts["overdue"] += 1
        if st == "extended":
            counts["extended"] += 1
        if st == "confirmed" and str(u.get("confirmation_date") or "").startswith(month):
            counts["confirmed_this_month"] += 1
        rows.append(u)
    if status:
        rows = [r for r in rows if r["probation_status"] == status]
    else:
        rows = [r for r in rows if r["probation_status"] != "not_applicable"]
    if q:
        s = q.strip().lower()
        rows = [r for r in rows if s in (r.get("name") or "").lower()
                or s in (r.get("employee_code") or "").lower()]
    return {"employees": rows, "counts": counts, "policy": pol, "today": today}


@router.post("/probation/init")
async def probation_init(body: Dict[str, Any] = Body(...),
                         authorization: Optional[str] = Header(None)):
    """Set/override probation for one employee (auto due-date from DOJ)."""
    admin, _ = await _gate(authorization, body.get("company_id"))
    uid = str(body.get("user_id") or "")
    u = await db.users.find_one({"user_id": uid}, {"_id": 0, "doj": 1,
                                "date_of_joining": 1, "company_id": 1,
                                "confirmation_due": 1, "employment_status": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    applicable = body.get("probation_applicable", True) is not False
    months = int(body.get("probation_months") or 6)
    if not 1 <= months <= 24:
        raise HTTPException(status_code=400, detail="probation_months must be 1-24")
    start = _norm_date(body.get("probation_start")) or _norm_date(u.get("doj") or u.get("date_of_joining"))
    if applicable and not start:
        raise HTTPException(status_code=400, detail="DOJ / probation start date not found")
    due = _norm_date(body.get("confirmation_due"))
    manual = bool(due)
    if manual and not str(body.get("override_reason") or "").strip():
        raise HTTPException(status_code=400, detail="Manual due-date override requires a reason")
    if applicable and not due:
        due = _add_months(start, months)
    patch = {"probation_applicable": applicable,
             "probation_months": months if applicable else None,
             "probation_start": start if applicable else None,
             "confirmation_due": due if applicable else None,
             "original_confirmation_due": (u.get("confirmation_due")
                                           or due) if applicable else None,
             "employment_status": "on_probation" if applicable else (u.get("employment_status") or None)}
    await db.users.update_one({"user_id": uid}, {"$set": patch})
    await _hist(admin, uid, "probation_set",
                {"due": u.get("confirmation_due"), "status": u.get("employment_status")},
                {"due": due, "months": months, "applicable": applicable},
                reason=str(body.get("override_reason") or "") or None)
    return {"ok": True, **patch}


@router.post("/probation/confirm")
async def probation_confirm(body: Dict[str, Any] = Body(...),
                            authorization: Optional[str] = Header(None)):
    admin, _ = await _gate(authorization, body.get("company_id"))
    uid = str(body.get("user_id") or "")
    u = await db.users.find_one({"user_id": uid}, {"_id": 0, "confirmation_due": 1,
                                "employment_status": 1, "doj": 1, "date_of_joining": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    if u.get("employment_status") == "confirmed":
        raise HTTPException(status_code=400, detail="Employee is already confirmed")
    cdate = _norm_date(body.get("confirmation_date")) or _today()
    doj = _norm_date(u.get("doj") or u.get("date_of_joining"))
    if doj and cdate < doj:
        raise HTTPException(status_code=400, detail="Confirmation date cannot be before DOJ")
    patch = {"employment_status": "confirmed", "confirmation_date": cdate,
             "confirmation_remarks": str(body.get("remarks") or "") or None,
             "confirmed_by": admin.get("name") or admin.get("email"),
             "confirmation_approval_date": now_iso()}
    await db.users.update_one({"user_id": uid}, {"$set": patch})
    await _hist(admin, uid, "confirmed",
                {"status": u.get("employment_status"), "due": u.get("confirmation_due")},
                {"status": "confirmed", "confirmation_date": cdate},
                remarks=patch["confirmation_remarks"])
    return {"ok": True, **patch}


@router.post("/probation/extend")
async def probation_extend(body: Dict[str, Any] = Body(...),
                           authorization: Optional[str] = Header(None)):
    admin, cid = await _gate(authorization, body.get("company_id"))
    pol = await _policy(cid)
    if not pol["extension_allowed"]:
        raise HTTPException(status_code=400, detail="Extension is not allowed by the Probation Policy")
    uid = str(body.get("user_id") or "")
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Extension requires a reason")
    u = await db.users.find_one({"user_id": uid}, {"_id": 0, "confirmation_due": 1,
                                "employment_status": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    if u.get("employment_status") == "confirmed":
        raise HTTPException(status_code=400, detail="Confirmed employee cannot be extended")
    months = int(body.get("extension_months") or 0)
    revised = _norm_date(body.get("revised_confirmation_due"))
    cur = u.get("confirmation_due") or _today()
    if not revised:
        if not 1 <= months <= pol["max_extension_months"]:
            raise HTTPException(status_code=400,
                                detail=f"extension_months must be 1-{pol['max_extension_months']}")
        revised = _add_months(cur, months)
    elif revised < cur and not body.get("authorized_override"):
        raise HTTPException(status_code=400,
                            detail="Revised date is before current due date — needs authorized override")
    patch = {"employment_status": "extended", "confirmation_due": revised,
             "extension_months": months or None, "extension_reason": reason,
             "revised_confirmation_due": revised}
    await db.users.update_one({"user_id": uid}, {"$set": patch})
    await _hist(admin, uid, "extended", {"due": cur, "status": u.get("employment_status")},
                {"due": revised, "months": months}, reason=reason,
                remarks=str(body.get("remarks") or "") or None)
    return {"ok": True, **patch}


@router.get("/probation/history/{user_id}")
async def probation_history(user_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ROLES)
    rows = await db.probation_history.find({"user_id": user_id}, {"_id": 0}) \
        .sort("at", -1).to_list(100)
    return {"history": rows}


@router.get("/probation/export")
async def probation_export(company_id: Optional[str] = Query(None),
                           authorization: Optional[str] = Header(None)):
    import io
    from fastapi.responses import Response
    from openpyxl import Workbook
    from openpyxl.styles import Font
    data = await probation_list(company_id=company_id, status=None, q=None,
                                authorization=authorization)
    wb = Workbook()
    ws = wb.active
    ws.title = "Confirmation Due"
    ws.append(["Code", "Name", "DOJ", "Department", "Designation",
               "Probation Months", "Start", "Original Due", "Current Due",
               "Days Remaining", "Status", "Confirmation Date"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in data["employees"]:
        ws.append([r.get("employee_code"), r.get("name"),
                   r.get("doj") or r.get("date_of_joining"), r.get("department"),
                   r.get("designation"), r.get("probation_months"),
                   r.get("probation_start"), r.get("original_confirmation_due"),
                   r.get("confirmation_due"), r.get("days_remaining"),
                   r.get("probation_status"), r.get("confirmation_date")])
    out = io.BytesIO()
    wb.save(out)
    return Response(content=out.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="Confirmation_Due_Report.xlsx"'})


# ─────────────────────── WEEKOFF CALENDAR PREVIEW ───────────────────────

@router.get("/weekoff/preview")
async def weekoff_preview(company_id: Optional[str] = Query(None),
                          month: str = Query(...),
                          user_id: Optional[str] = Query(None),
                          authorization: Optional[str] = Header(None)):
    """Month calendar showing which dates are weekoff under the active
    rules (fixed / occurrence / alternate) — read-only preview."""
    _, cid = await _gate(authorization, company_id)
    c = await db.companies.find_one({"company_id": cid}, {"_id": 0, "attendance_policy": 1})
    policy = (c or {}).get("attendance_policy") or {}
    user = {}
    if user_id:
        user = await db.users.find_one({"user_id": user_id}, {"_id": 0,
                                       "weekly_off_days_override": 1,
                                       "attendance_policy_override": 1,
                                       "ot_applicable": 1, "name": 1}) or {}
        policy = apply_employee_policy_override(policy, user)
    try:
        yy, mm = int(month[:4]), int(month[5:7])
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    import calendar as _cal
    days_in = _cal.monthrange(yy, mm)[1]
    wd_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    wr = policy.get("weekoff_rules") or {}
    out = []
    for dd in range(1, days_in + 1):
        iso = f"{yy:04d}-{mm:02d}-{dd:02d}"
        wd = datetime(yy, mm, dd).weekday()
        p2 = apply_weekoff_rules_for_date(policy, user, iso)
        is_off = wd in set(p2.get("weekly_off_days") or [])
        rule = "Fixed weekly off"
        if wr.get("type") == "occurrence" and str(wd) in (wr.get("occurrence") or {}):
            occ_no = (dd - 1) // 7 + 1
            rule = f"{occ_no}{'st' if occ_no == 1 else 'nd' if occ_no == 2 else 'rd' if occ_no == 3 else 'th'} {wd_names[wd]}"
        elif wr.get("type") == "alternate" and wd in set((wr.get("alternate") or {}).get("weekdays") or []):
            rule = "Alternate week"
        out.append({"date": iso, "day": wd_names[wd], "weekday": wd,
                    "rule": rule if is_off or (wr.get("type") != "fixed") else "—",
                    "status": "Weekoff" if is_off else "Working"})
    return {"days": out, "weekoff_rules": wr,
            "weekly_off_days": policy.get("weekly_off_days") or [],
            "employee": user.get("name") if user else None}
