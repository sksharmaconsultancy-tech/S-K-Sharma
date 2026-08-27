"""Iter 610 — Employee Self-Service (ESS) backend.
Phase 1 of the ESS spec: My Profile (+change requests), Enhanced
Attendance (with source), Attendance Correction, My Shift/Roster,
My Salary/CTC + PF + ESIC (real payroll data only), unified My Requests,
Notification center (unread/read).
Phase 3: SMS wiring — request decisions notify the employee in-app and
via MSG91 (uses existing sms_service; toggles/flow ids from SMS Settings).
REUSES existing collections: users, attendance, compliance_salary_runs,
daily_shift_assignments, shift_masters, holidays, notifications,
device_change_requests. New collection: ess_requests.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import db, get_user_from_token, require_role, now_iso
from shared.sms_service import get_sms_settings, send_sms

router = APIRouter(prefix="/api", tags=["ess"])

ADMIN_ROLES = ["super_admin", "sub_admin", "company_admin", "hr_manager", "manager"]

PROFILE_FIELDS = [
    "employee_code", "name", "father_name", "mother_name", "gender", "dob",
    "doj", "designation", "department", "branch_name", "worksite",
    "reporting_manager", "mobile", "email", "address", "emergency_contact",
    "emergency_contact_name", "bank_name", "bank_account_no",
    "bank_account_name", "ifsc", "uan_no", "esi_ip_no", "pf_no",
    "employee_type", "employment_status", "photo_b64",
]
# Fields an employee may REQUEST to change (applied only after HR approval)
EDITABLE_PROFILE_FIELDS = [
    "mobile", "email", "address", "emergency_contact",
    "emergency_contact_name", "bank_name", "bank_account_no",
    "bank_account_name", "ifsc",
]
REQUEST_TYPES = [
    "attendance_correction", "profile_correction", "bank_change",
    "document_request", "device_change", "shift_change",
    "advance_request", "reimbursement_request", "other",
]


async def _notify(user_id: str, company_id: Optional[str], title: str,
                  body: str, sms_type: Optional[str] = None,
                  mobile: Optional[str] = None,
                  actor_name: Optional[str] = None,
                  subject_name: Optional[str] = None):
    """In-app notification + optional MSG91 SMS (Phase 3 wiring)."""
    # Iter 754 (user request) — popup par firm + kisne/kiske liye details.
    firm_name = None
    if company_id:
        try:
            _co = await db.companies.find_one(
                {"company_id": company_id}, {"_id": 0, "name": 1})
            firm_name = (_co or {}).get("name")
        except Exception:
            firm_name = None
    await db.notifications.insert_one({
        "notification_id": f"n_{uuid.uuid4().hex[:10]}",
        "company_id": company_id, "audience": "user",
        "firm_name": firm_name,
        "actor_name": (str(actor_name)[:80] if actor_name else None),
        "subject_name": (str(subject_name)[:80] if subject_name else None),
        "target_user_id": user_id, "title": title, "body": body,
        "read_by": [], "created_at": now_iso(), "created_by": "ess",
    })
    if sms_type and mobile:
        try:
            st = await get_sms_settings(db, company_id)
            if st.get("enabled") and st.get("toggles", {}).get(sms_type, True) \
                    and st.get("default_flow_id"):
                await send_sms(
                    db, company_id=company_id, mobile=mobile,
                    flow_id=st["default_flow_id"],
                    variables={"var": body[:100], "message": body[:100]},
                    notification_type=f"ess_{sms_type}",
                    triggered_for=user_id)
        except Exception:  # noqa: BLE001 — SMS must never break the flow
            pass


# ───────────────────────── PROFILE ─────────────────────────
@router.get("/ess/profile")
async def ess_profile(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    u = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    out = {k: u.get(k) for k in PROFILE_FIELDS}
    out["editable_fields"] = EDITABLE_PROFILE_FIELDS
    pend = await db.ess_requests.count_documents(
        {"user_id": user["user_id"], "type": {"$in": ["profile_correction", "bank_change"]},
         "status": {"$in": ["submitted", "under_review"]}})
    out["pending_profile_requests"] = pend
    return {"profile": out}


# ─────────────────── ENHANCED ATTENDANCE ───────────────────
SOURCE_LABEL = {"mobile": "Mobile PWA", "manual": "Manual", "machine": "Machine",
                "zkteco": "ZKTeco", "essl": "ESSL", "import": "Imported",
                "manual_correction": "Manual Correction"}


@router.get("/ess/attendance")
async def ess_attendance(month: str = Query(...),
                         authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    uid, cid = user["user_id"], user.get("company_id")
    recs = await db.attendance.find(
        {"user_id": uid, "date": {"$regex": f"^{month}"}},
        {"_id": 0, "photo_b64": 0, "selfie_b64": 0}).sort("at", 1).to_list(400)
    hols = {h["date"]: h.get("name") or "Holiday" async for h in db.holidays.find(
        {"date": {"$regex": f"^{month}"},
         "$or": [{"company_id": cid}, {"company_id": None},
                 {"company_id": {"$exists": False}}]}, {"_id": 0})}
    days: Dict[str, dict] = {}
    for r in recs:
        d = days.setdefault(r["date"], {"date": r["date"], "punches": []})
        src = (r.get("source") or "mobile").lower()
        d["punches"].append({
            "kind": r.get("kind"), "at": r.get("at"),
            "source": src, "source_label": SOURCE_LABEL.get(src, src.title()),
            "status": r.get("status"),
            "device_serial": r.get("device_serial"),
            "lat": r.get("lat"), "lng": r.get("lng"),
            "liveness_pass": r.get("liveness_pass"),
            "face_match_score": r.get("face_match_score"),
            "record_id": r.get("record_id"),
        })
    out = []
    for d, row in sorted(days.items()):
        ins = [p for p in row["punches"] if p["kind"] == "in"]
        outs = [p for p in row["punches"] if p["kind"] == "out"]
        first_in = ins[0]["at"] if ins else None
        last_out = outs[-1]["at"] if outs else None
        hours = None
        try:
            if first_in and last_out:
                t1 = datetime.fromisoformat(first_in.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(last_out.replace("Z", "+00:00"))
                hours = round(max(0.0, (t2 - t1).total_seconds() / 3600), 2)
        except Exception:  # noqa: BLE001
            pass
        row.update({"in": first_in, "out": last_out, "hours": hours,
                    "holiday": hols.get(d), "status": "present"})
        out.append(row)
    return {"month": month, "days": out, "holidays": hols}


# ─────────────────────── SHIFT / ROSTER ───────────────────────
@router.get("/ess/shift")
async def ess_shift(days: int = Query(8),
                    authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    uid = user["user_id"]
    today = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)  # IST
    dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d")
             for i in range(max(1, min(31, days)))]
    assigns = {a["date"]: a async for a in db.daily_shift_assignments.find(
        {"user_id": uid, "date": {"$in": dates}}, {"_id": 0})}
    if not assigns:
        assigns = {a["date"]: a async for a in db.shift_assignments.find(
            {"user_id": uid, "date": {"$in": dates}}, {"_id": 0})}
    masters = {m["name"]: m async for m in db.shift_masters.find({}, {"_id": 0})}
    u = await db.users.find_one({"user_id": uid}, {"_id": 0, "shift": 1, "worksite": 1, "branch_name": 1}) or {}
    default_shift = u.get("shift")
    roster = []
    for d in dates:
        a = assigns.get(d) or {}
        nm = a.get("shift_name") or default_shift
        m = masters.get(nm) or {}
        roster.append({
            "date": d, "shift_name": nm or "General",
            "start": m.get("start"), "end": m.get("end"),
            "description": m.get("description"),
            "source": a.get("source") or ("assigned" if a else "default"),
            "worksite": u.get("worksite") or u.get("branch_name"),
        })
    return {"today": roster[0], "roster": roster}


# ─────────────── SALARY / CTC + PF + ESIC (real data) ───────────────
def _num(v):
    try:
        return round(float(v or 0), 2)
    except Exception:  # noqa: BLE001
        return 0.0


@router.get("/ess/salary")
async def ess_salary(months: int = Query(12),
                     authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    uid = user["user_id"]
    u = await db.users.find_one({"user_id": uid},
                                {"_id": 0, "employee_code": 1, "company_id": 1}) or {}
    code = u.get("employee_code")
    runs = await db.compliance_salary_runs.find(
        {"company_id": u.get("company_id")},
        {"_id": 0, "month": 1, "year": 1, "month_number": 1, "rows": 1,
         "generated_at": 1, "frozen": 1}).sort("generated_at", -1).to_list(24)
    out, pf, esic = [], [], []
    seen = set()
    for r in runs:
        key = r.get("month") or f"{r.get('year')}-{r.get('month_number')}"
        if key in seen:
            continue
        row = next((x for x in (r.get("rows") or [])
                    if x.get("user_id") == uid or
                    (code and x.get("employee_code") == code)), None)
        if not row:
            continue
        seen.add(key)
        earnings = {
            "basic": _num(row.get("basic")), "hra": _num(row.get("hra")),
            "conveyance": _num(row.get("conveyance")),
            "medical": _num(row.get("medical")), "special": _num(row.get("special")),
            "others": _num(row.get("others")), "ot_pay": _num(row.get("ot_pay")),
        }
        gross = _num(row.get("gross_paid"))
        deductions = {
            "pf": _num(row.get("pf_employee")), "esic": _num(row.get("esic_employee")),
            "pt": _num(row.get("pt")), "tds": _num(row.get("tds")),
            "other": _num(row.get("other_deduction")),
        }
        net = _num(row.get("net"))
        er_pf = _num(row.get("pf_employer_total"))
        er_esic = _num(row.get("esic_employer"))
        out.append({
            "month": key, "present_days": row.get("present_days"),
            "attendance_days": row.get("attendance_days"),
            "ot_hours": _num(row.get("ot_hours")),
            "earnings": earnings, "gross": gross, "deductions": deductions,
            "total_deduction": _num(row.get("total_deduction")),
            "net": net, "ctc": round(gross + er_pf + er_esic, 2),
            "frozen": bool(r.get("frozen")),
        })
        pf.append({"month": key, "uan": row.get("uan_no") or None,
                   "pf_no": row.get("pf_no") or None,
                   "pf_wage": _num(row.get("pf_wages")),
                   "employee": _num(row.get("pf_employee")),
                   "employer_epf": _num(row.get("pf_employer_epf")),
                   "employer_eps": _num(row.get("pf_employer_eps")),
                   "applicable": bool(row.get("pf_applicable") or row.get("pf_eligible"))})
        esic.append({"month": key, "ip_no": row.get("esi_ip_no") or None,
                     "esic_wage": _num(row.get("esic_wage_base")),
                     "employee": _num(row.get("esic_employee")),
                     "employer": _num(row.get("esic_employer")),
                     "applicable": bool(row.get("esic_applicable") or row.get("esic_eligible"))})
        if len(out) >= months:
            break
    prof = await db.users.find_one({"user_id": uid},
                                   {"_id": 0, "uan_no": 1, "esi_ip_no": 1}) or {}
    return {"months": out, "pf": pf, "esic": esic,
            "uan": prof.get("uan_no") or None,
            "esi_ip_no": prof.get("esi_ip_no") or None}


# ─────────────────── UNIFIED MY REQUESTS ───────────────────
async def _next_request_no() -> str:
    ym = datetime.now(timezone.utc).strftime("%y%m")
    n = await db.ess_requests.count_documents({"request_no": {"$regex": f"^REQ{ym}"}})
    return f"REQ{ym}-{n + 1:04d}"


@router.post("/ess/requests")
async def create_request(payload: Dict[str, Any] = Body(...),
                         authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    rtype = str(payload.get("type") or "")
    if rtype not in REQUEST_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {REQUEST_TYPES}")
    body = payload.get("payload") or {}
    if rtype in ("profile_correction", "bank_change"):
        fields = body.get("fields") or {}
        bad = [k for k in fields if k not in EDITABLE_PROFILE_FIELDS]
        if bad:
            raise HTTPException(status_code=400, detail=f"Fields not editable: {bad}")
        if not fields:
            raise HTTPException(status_code=400, detail="No fields requested")
    if rtype == "attendance_correction":
        if not body.get("date"):
            raise HTTPException(status_code=400, detail="date required")
    u = await db.users.find_one({"user_id": user["user_id"]},
                                {"_id": 0, "name": 1, "employee_code": 1, "mobile": 1}) or {}
    doc = {
        "request_id": f"essr_{uuid.uuid4().hex[:10]}",
        "request_no": await _next_request_no(),
        "user_id": user["user_id"], "company_id": user.get("company_id"),
        "employee": {"name": u.get("name"), "employee_code": u.get("employee_code")},
        "type": rtype, "payload": body,
        "reason": str(payload.get("reason") or "")[:500],
        "status": "submitted",
        "history": [{"at": now_iso(), "by": user["user_id"], "action": "submitted"}],
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.ess_requests.insert_one({**doc})
    # Iter 667 (user request) — bell notification to company/super admins
    # when an employee applies to edit their details (approval needed).
    try:
        from utils.notify import emit as _notify
        _tl = {"profile_correction": "Employee Details Edit Request",
               "bank_change": "Bank Details Change Request",
               "attendance_correction": "Attendance Correction Request"}
        await _notify(
            db,
            title=_tl.get(rtype, "Employee Request"),
            message=(f"{u.get('name') or 'An employee'} "
                     f"({u.get('employee_code') or ''}) submitted request "
                     f"#{doc['request_no']} — approval required."),
            audience="admins", company_id=user.get("company_id"),
            category="employee", priority="important",
            actor_name=u.get("name"),
            subject_name=u.get("name"),
            action_url="/ess-requests-admin", reference_id=doc["request_id"])
    except Exception:
        pass
    return {"ok": True, "request": doc}


@router.get("/ess/requests")
async def list_requests(scope: str = Query("mine"),
                        status: Optional[str] = Query(None),
                        company_id: Optional[str] = Query(None),
                        authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    if scope == "admin":
        require_role(user, ADMIN_ROLES)
        q: dict = {}
        cid = user.get("company_id") or company_id
        if user.get("role") in ("super_admin", "sub_admin") and company_id:
            cid = company_id
        if cid:
            q["company_id"] = cid
        if status:
            q["status"] = status
    else:
        q = {"user_id": user["user_id"]}
        if status:
            q["status"] = status
    rows = await db.ess_requests.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(300)
    return {"requests": rows}


@router.post("/ess/requests/{request_id}/decide")
async def decide_request(request_id: str, payload: Dict[str, Any] = Body(...),
                         authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ADMIN_ROLES)
    action = str(payload.get("action") or "")
    if action not in ("under_review", "approve", "reject", "complete"):
        raise HTTPException(status_code=400, detail="Invalid action")
    req = await db.ess_requests.find_one({"request_id": request_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if admin.get("role") not in ("super_admin", "sub_admin") and \
            admin.get("company_id") != req.get("company_id"):
        raise HTTPException(status_code=403, detail="Different firm")
    remarks = str(payload.get("remarks") or "")[:400]
    new_status = {"under_review": "under_review", "approve": "approved",
                  "reject": "rejected", "complete": "completed"}[action]
    applied = None
    if action == "approve":
        applied = await _apply_request(req, admin)
    await db.ess_requests.update_one(
        {"request_id": request_id},
        {"$set": {"status": new_status, "updated_at": now_iso(),
                  "decided_by": admin.get("email") or admin.get("user_id"),
                  "remarks": remarks, "applied": applied},
         "$push": {"history": {"at": now_iso(), "by": admin.get("user_id"),
                               "action": new_status, "remarks": remarks}}})
    # Phase 3 — notify employee (in-app + SMS)
    emp = await db.users.find_one({"user_id": req["user_id"]},
                                  {"_id": 0, "mobile": 1, "name": 1}) or {}
    label = req["type"].replace("_", " ").title()
    await _notify(
        req["user_id"], req.get("company_id"),
        f"Request {new_status.replace('_', ' ')}: {req['request_no']}",
        f"Your {label} request {req['request_no']} is {new_status.replace('_', ' ')}."
        + (f" Remarks: {remarks}" if remarks else ""),
        sms_type="attendance" if req["type"] == "attendance_correction" else "onboarding",
        mobile=emp.get("mobile"),
        actor_name=admin.get("name") or admin.get("email"),
        subject_name=emp.get("name"))
    return {"ok": True, "status": new_status, "applied": applied}


async def _apply_request(req: dict, admin: dict):
    """Approved requests take effect — original data is NEVER deleted."""
    t, body = req["type"], req.get("payload") or {}
    if t == "attendance_correction":
        # Insert corrected punch(es) as NEW records (source=manual_correction)
        inserted = []
        for kind in ("in", "out"):
            at = body.get(f"requested_{kind}")
            if not at:
                continue
            rec = {
                "record_id": f"att_{uuid.uuid4().hex[:10]}",
                "user_id": req["user_id"], "company_id": req.get("company_id"),
                "date": body["date"], "kind": kind, "at": at,
                "source": "manual_correction", "status": "approved",
                "correction_request_id": req["request_id"],
                "corrected_by": admin.get("email") or admin.get("user_id"),
                "created_at": now_iso(),
            }
            await db.attendance.insert_one({**rec})
            inserted.append(rec["record_id"])
        return {"attendance_records": inserted}
    if t in ("profile_correction", "bank_change"):
        fields = {k: v for k, v in (body.get("fields") or {}).items()
                  if k in EDITABLE_PROFILE_FIELDS}
        if fields:
            old = await db.users.find_one({"user_id": req["user_id"]},
                                          {"_id": 0, **{k: 1 for k in fields}}) or {}
            await db.users.update_one({"user_id": req["user_id"]},
                                      {"$set": {**fields, "updated_at": now_iso()}})
            await db.company_audit_log.insert_one({
                "audit_id": f"aud_{uuid.uuid4().hex[:10]}",
                "company_id": req.get("company_id"), "user_id": req["user_id"],
                "event": "ess_profile_change_applied",
                "request_id": req["request_id"], "old": old, "new": fields,
                "by": admin.get("email") or admin.get("user_id"), "at": now_iso()})
            return {"fields_applied": list(fields.keys())}
    if t == "device_change":
        await db.device_change_requests.insert_one({
            "request_id": req["request_id"], "user_id": req["user_id"],
            "company_id": req.get("company_id"), "status": "approved",
            "reason": req.get("reason"), "requested_at": req["created_at"],
            "approved_by": admin.get("email"), "approved_at": now_iso()})
        return {"device_change": "approved — employee can register the new phone"}
    return None


# ─────────────────── NOTIFICATION CENTER ───────────────────
@router.get("/ess/notifications")
async def ess_notifications(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    uid, cid, role = user["user_id"], user.get("company_id"), user["role"]
    q: dict = {"$or": [{"company_id": None}, {"company_id": {"$exists": False}}]}
    if cid:
        q["$or"].append({"company_id": cid})
    rows = await db.notifications.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(200)
    out = []
    for n in rows:
        aud = n.get("audience", "all")
        if aud == "all" or (aud == "employees" and role == "employee") or \
                (aud == "user" and n.get("target_user_id") == uid):
            n["read"] = uid in (n.get("read_by") or [])
            out.append(n)
    unread = sum(1 for n in out if not n["read"])
    return {"notifications": out[:100], "unread": unread}


@router.post("/ess/notifications/read")
async def mark_notifications_read(payload: Dict[str, Any] = Body(default={}),
                                  authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    ids = payload.get("notification_ids")
    q: dict = {"notification_id": {"$in": ids}} if ids else {}
    await db.notifications.update_many(q, {"$addToSet": {"read_by": user["user_id"]}})
    return {"ok": True}
