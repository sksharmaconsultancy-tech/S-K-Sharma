"""Iter 357 — Phase D: Factory & Boilers Compliance.

Data-entry masters (factory_records collection, one doc per record with a
`kind`) + computed registers from existing attendance/payroll data + a
compliance dashboard with due-date alerts and risk scoring.

  GET  /api/admin/factory/kinds                       (register catalogue)
  GET  /api/admin/factory/records?kind=…              (list)
  POST /api/admin/factory/records                     (create/update)
  DELETE /api/admin/factory/records/{record_id}
  GET  /api/admin/factory/register/{kind}[.xlsx|.pdf] (register incl. computed)
  GET  /api/admin/factory/dashboard                   (Module 20)
computed kinds: daily-attendance, muster-roll, working-hours, strength
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import StreamingResponse

from server import db, get_user_from_token, require_role  # noqa: E402
from utils.register_export import register_pdf, register_xlsx  # noqa: E402
from routes.labour_statistics import (_active, _bucket, _dt, _f,  # noqa: E402
                                      _gender, _users, _company, _run_rows)

router = APIRouter(prefix="/api/admin/factory", tags=["factory-compliance"])

# Master (data-entry) register kinds → field list (key, label)
_MASTER_KINDS: Dict[str, Dict[str, Any]] = {
    "factory-details": {"title": "Factory Occupier & Manager Details", "fields": [
        ("factory_name", "Factory Name"), ("factory_code", "Factory Code"),
        ("address", "Factory Address"), ("license_no", "Factory License No."),
        ("license_validity", "License Validity"), ("occupier", "Occupier Name"),
        ("manager", "Manager Name"), ("category", "Factory Category"),
        ("process", "Nature of Manufacturing Process"),
        ("max_hp", "Max Installed HP"), ("max_kw", "Max KW"),
        ("pollution_noc", "Pollution NOC"), ("fire_noc", "Fire NOC"),
        ("boiler_registration", "Boiler Registration"),
        ("boiler_inspector", "Boiler Inspector Details")]},
    "license": {"title": "Factory License Register", "fields": [
        ("license_no", "License Number"), ("license_type", "License Type"),
        ("issue_date", "Issue Date"), ("renewal_date", "Renewal Date"),
        ("fees", "Fees"), ("validity", "Validity (expiry)"),
        ("remarks", "Remarks")]},
    "boiler": {"title": "Boiler Register", "fields": [
        ("boiler_no", "Boiler Number"), ("registration_no", "Registration No."),
        ("capacity", "Capacity"), ("pressure", "Pressure"),
        ("manufacturer", "Manufacturer"),
        ("installation_date", "Installation Date"),
        ("inspector", "Inspector Name"), ("last_inspection", "Last Inspection"),
        ("next_inspection", "Next Inspection"),
        ("certificate_no", "Certificate No."), ("status", "Status")]},
    "boiler-inspection": {"title": "Boiler Inspection Register", "fields": [
        ("inspection_date", "Inspection Date"), ("inspector", "Inspector"),
        ("pressure_test", "Pressure Test"), ("hydraulic_test", "Hydraulic Test"),
        ("safety_valve_test", "Safety Valve Test"), ("steam_test", "Steam Test"),
        ("remarks", "Remarks"), ("compliance_status", "Compliance Status")]},
    "boiler-maintenance": {"title": "Boiler Maintenance Register", "fields": [
        ("maintenance_type", "Type (Preventive/Breakdown)"),
        ("maintenance_date", "Maintenance Date"), ("engineer", "Engineer"),
        ("spare_parts", "Spare Parts"), ("downtime_hrs", "Downtime (hrs)"),
        ("cost", "Cost"), ("next_service", "Next Service Due")]},
    "accident": {"title": "Accident Register", "fields": [
        ("accident_no", "Accident No."), ("date", "Date"), ("time", "Time"),
        ("employee", "Employee"), ("department", "Department"),
        ("shift", "Shift"), ("accident_type", "Accident Type"),
        ("body_part", "Body Part"), ("severity", "Severity"),
        ("lost_time_days", "Lost Time (days)"),
        ("treatment", "Medical Treatment"), ("hospital", "Hospital"),
        ("compensation", "Compensation"), ("root_cause", "Root Cause"),
        ("corrective_action", "Corrective Action"), ("status", "Status")]},
    "near-miss": {"title": "Near Miss Register", "fields": [
        ("date", "Incident Date"), ("department", "Department"),
        ("description", "Description"), ("risk_level", "Risk Level"),
        ("action_taken", "Action Taken"),
        ("responsible", "Responsible Person"), ("status", "Status")]},
    "first-aid": {"title": "First Aid Register", "fields": [
        ("employee", "Employee"), ("date", "Date"),
        ("treatment", "Treatment"), ("medicine", "Medicine"),
        ("doctor", "Doctor"), ("follow_up", "Follow-up")]},
    "medical": {"title": "Medical Examination Report", "fields": [
        ("employee", "Employee"), ("department", "Department"),
        ("medical_date", "Medical Date"), ("fitness", "Fitness Status"),
        ("occupational_disease", "Occupational Disease"), ("vision", "Vision"),
        ("hearing", "Hearing"), ("bp", "Blood Pressure"),
        ("doctor_remarks", "Doctor Remarks"), ("next_due", "Next Due Date")]},
    "safety-training": {"title": "Safety Training Register", "fields": [
        ("training", "Training Name"), ("department", "Department"),
        ("trainer", "Trainer"), ("participants", "Participants"),
        ("attendance", "Attendance"), ("certificate", "Certificate"),
        ("next_due", "Next Due")]},
    "ppe": {"title": "PPE Issue Register", "fields": [
        ("employee", "Employee"), ("item", "PPE Item"),
        ("issue_date", "Issue Date"), ("return_date", "Return Date"),
        ("replacement_due", "Replacement Due"), ("remarks", "Remarks")]},
    "fire-safety": {"title": "Fire Safety Register", "fields": [
        ("equipment", "Equipment (Extinguisher/Hydrant/Alarm/Exit)"),
        ("location", "Location"), ("inspection_date", "Inspection Date"),
        ("next_due", "Next Due"), ("status", "Status")]},
    "fuel": {"title": "Fuel Consumption Report", "fields": [
        ("month", "Month"), ("fuel_type", "Fuel (Coal/Gas/Diesel/FO/LDO/Wood)"),
        ("quantity", "Quantity"), ("steam_generated", "Steam Generated"),
        ("efficiency", "Efficiency %"), ("cost", "Cost")]},
    "energy": {"title": "Energy Consumption Report", "fields": [
        ("month", "Month"), ("department", "Department"),
        ("electricity_kwh", "Electricity (kWh)"), ("steam", "Steam"),
        ("compressed_air", "Compressed Air"), ("water", "Water"),
        ("fuel", "Fuel"), ("cost", "Cost")]},
    # Iter 358 — additional Factories Act registers (user request)
    "adult-worker": {"title": "Adult Worker Register (Form)", "fields": [
        ("employee", "Worker Name"), ("employee_code", "Emp Code"),
        ("father_name", "Father's Name"), ("dob", "Date of Birth"),
        ("nature_of_work", "Nature of Work"), ("group", "Group"),
        ("relay", "Relay/Shift"), ("certificate_no", "Fitness Cert. No."),
        ("date_of_employment", "Date of Employment")]},
    "dangerous-occurrence": {"title": "Dangerous Occurrence Register",
                             "fields": [
        ("date", "Date"), ("time", "Time"), ("department", "Department"),
        ("description", "Description of Occurrence"),
        ("persons_affected", "Persons Affected"),
        ("cause", "Cause"), ("action_taken", "Action Taken"),
        ("reported_to", "Reported To"), ("status", "Status")]},
    "welfare": {"title": "Welfare Register", "fields": [
        ("facility", "Facility (Creche/Restroom/Canteen/First-Aid…)"),
        ("location", "Location"), ("in_charge", "In-charge"),
        ("capacity", "Capacity"), ("last_inspection", "Last Inspection"),
        ("remarks", "Remarks")]},
    "canteen": {"title": "Canteen Register", "fields": [
        ("date", "Date"), ("meals_served", "Meals Served"),
        ("rate", "Rate"), ("subsidy", "Subsidy"),
        ("contractor", "Canteen Contractor"), ("remarks", "Remarks")]},
    "machine-operator": {"title": "Machine Operator Register", "fields": [
        ("employee", "Operator Name"), ("employee_code", "Emp Code"),
        ("machine", "Machine"), ("department", "Department"),
        ("trained_on", "Trained On"), ("certificate", "Certificate"),
        ("valid_till", "Valid Till"), ("remarks", "Remarks")]},
}
# due-date field per kind for the dashboard alerts
_DUE_FIELDS = {
    "license": "validity", "boiler": "next_inspection",
    "boiler-maintenance": "next_service", "medical": "next_due",
    "safety-training": "next_due", "ppe": "replacement_due",
    "fire-safety": "next_due", "factory-details": "license_validity",
}


async def _adm(authorization, company_id):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return company_id, admin


@router.get("/kinds")
async def kinds(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    return {"masters": [{"kind": k, "title": v["title"],
                         "fields": [{"key": a, "label": b}
                                    for a, b in v["fields"]]}
                        for k, v in _MASTER_KINDS.items()],
            "computed": [
                {"kind": "daily-attendance",
                 "title": "Daily Factory Attendance Report"},
                {"kind": "present-absent",
                 "title": "Present & Absent Report (employee-wise)"},
                {"kind": "muster-roll", "title": "Daily Muster Roll Register"},
                {"kind": "leave-with-wages",
                 "title": "Leave with Wages Register"},
                {"kind": "working-hours",
                 "title": "Working Hours & Overtime Register"},
                {"kind": "strength", "title": "Factory Strength Register"}]}


@router.get("/records")
async def list_records(kind: str, company_id: Optional[str] = None,
                       authorization: Optional[str] = Header(None)):
    company_id, _a = await _adm(authorization, company_id)
    if kind not in _MASTER_KINDS:
        raise HTTPException(status_code=404, detail="Unknown kind")
    rows = await db.factory_records.find(
        {"company_id": company_id, "kind": kind},
        {"_id": 0}).sort("created_at", -1).to_list(2000)
    return {"kind": kind, "title": _MASTER_KINDS[kind]["title"],
            "fields": [{"key": a, "label": b}
                       for a, b in _MASTER_KINDS[kind]["fields"]],
            "records": rows}


@router.post("/records")
async def save_record(body: dict = Body(...),
                      authorization: Optional[str] = Header(None)):
    company_id, admin = await _adm(authorization, body.get("company_id"))
    kind = body.get("kind")
    if kind not in _MASTER_KINDS:
        raise HTTPException(status_code=400, detail="Unknown kind")
    fields = {k for k, _l in _MASTER_KINDS[kind]["fields"]}
    data = {k: v for k, v in (body.get("data") or {}).items() if k in fields}
    rid = body.get("record_id") or f"fr_{uuid.uuid4().hex[:10]}"
    doc = {"record_id": rid, "company_id": company_id, "kind": kind,
           "data": data, "updated_by": admin.get("user_id"),
           "updated_at": datetime.now(timezone.utc).isoformat()}
    existing = await db.factory_records.find_one({"record_id": rid})
    if existing:
        await db.factory_records.update_one({"record_id": rid}, {"$set": doc})
    else:
        doc["created_at"] = doc["updated_at"]
        await db.factory_records.insert_one(dict(doc))
    return {"ok": True, "record_id": rid}


@router.delete("/records/{record_id}")
async def delete_record(record_id: str,
                        authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    q: Dict[str, Any] = {"record_id": record_id}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    res = await db.factory_records.delete_one(q)
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# computed registers from existing data
# ---------------------------------------------------------------------------

async def _computed(kind: str, company_id: str, day: str, month: str):
    users = await _users(company_id)
    act = [u for u in users if _active(u)]
    if kind == "daily-attendance":
        present = set(await db.attendance.distinct(
            "user_id", {"company_id": company_id,
                        "timestamp": {"$regex": f"^{day}"}}))
        depts: Dict[str, List[dict]] = {}
        for u in act:
            depts.setdefault(str(u.get("department") or "GENERAL").upper(),
                             []).append(u)
        rows = []
        for d in sorted(depts):
            us = depts[d]
            p = sum(1 for u in us if u["user_id"] in present)
            rows.append({
                "department": d,
                "male": sum(1 for u in us if _gender(u) == "Male"),
                "female": sum(1 for u in us if _gender(u) == "Female"),
                "contract": sum(1 for u in us if _bucket(u) == "Contract"),
                "apprentices": sum(1 for u in us
                                   if _bucket(u) == "Apprentice"),
                "staff": sum(1 for u in us if _bucket(u) == "Staff"),
                "total": len(us), "present": p, "absent": len(us) - p,
            })
        cols = [("department", "Department"), ("male", "Male"),
                ("female", "Female"), ("contract", "Contract Workers"),
                ("apprentices", "Apprentices"), ("staff", "Staff"),
                ("total", "Total"), ("present", "Present"),
                ("absent", "Absent")]
        totals = {k: sum(r[k] for r in rows) for k, _l in cols[1:]}
        totals["department"] = "TOTAL"
        return (f"Daily Factory Attendance Report — {day}", cols, rows, totals)
    if kind == "present-absent":
        # user request — employee-wise Present & Absent report: status for
        # the selected day + monthly present/absent day counts.
        present = set(await db.attendance.distinct(
            "user_id", {"company_id": company_id,
                        "timestamp": {"$regex": f"^{day}"}}))
        recs = await db.attendance.find(
            {"company_id": company_id,
             "timestamp": {"$regex": f"^{month}"}},
            {"_id": 0, "user_id": 1, "timestamp": 1}).to_list(500000)
        days_by_uid: Dict[str, set] = {}
        for r in recs:
            days_by_uid.setdefault(r["user_id"], set()).add(
                str(r.get("timestamp"))[:10])
        y, m = int(month[:4]), int(month[5:7])
        today_d = date.today()
        elapsed = (today_d.day if (today_d.year, today_d.month) == (y, m)
                   else (date(y + (m == 12), (m % 12) + 1, 1)
                         - timedelta(days=1)).day)
        rows = []
        for u in sorted(act, key=lambda x: str(
                x.get("employee_code") or "").zfill(8)):
            pd = len(days_by_uid.get(u["user_id"], set()))
            rows.append({
                "employee_code": u.get("employee_code"),
                "name": u.get("name"),
                "department": u.get("department"),
                "today_status": ("PRESENT" if u["user_id"] in present
                                 else "ABSENT"),
                "present_days": pd,
                "absent_days": max(0, elapsed - pd),
            })
        cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
                ("department", "Department"),
                ("today_status", f"Status ({day})"),
                ("present_days", f"Present Days ({month})"),
                ("absent_days", f"Absent Days ({month})")]
        totals = {"name": "TOTAL",
                  "today_status": (f"P:{sum(1 for r in rows if r['today_status'] == 'PRESENT')} "
                                   f"A:{sum(1 for r in rows if r['today_status'] == 'ABSENT')}"),
                  "present_days": sum(r["present_days"] for r in rows),
                  "absent_days": sum(r["absent_days"] for r in rows)}
        return (f"Present & Absent Report — {day}", cols, rows, totals)
    if kind == "leave-with-wages":
        # Leave with Wages Register — from the leave collections when
        # present, else derived from salary-run month days vs present days.
        rows = []
        for coll in ("leaves", "esic_leaves", "leave_requests"):
            try:
                docs = await db[coll].find(
                    {"company_id": company_id},
                    {"_id": 0}).sort("created_at", -1).to_list(2000)
            except Exception:  # noqa: BLE001
                docs = []
            umap = {u["user_id"]: u for u in users}
            for d in docs:
                u = umap.get(d.get("user_id")) or {}
                rows.append({
                    "employee_code": u.get("employee_code")
                    or d.get("employee_code"),
                    "name": u.get("name") or d.get("employee_name"),
                    "leave_type": d.get("leave_type") or d.get("type")
                    or coll.replace("_", " "),
                    "from_date": d.get("from_date") or d.get("start_date"),
                    "to_date": d.get("to_date") or d.get("end_date"),
                    "days": d.get("days") or d.get("total_days"),
                    "status": d.get("status"),
                })
        if not rows:
            run_rows = await _run_rows(company_id, month)
            umap = {u["user_id"]: u for u in users}
            for uid, r in run_rows.items():
                lv = _f(r.get("month_days")) - _f(r.get("present_days")) - \
                    _f(r.get("weekly_off_days"))
                if lv > 0:
                    u = umap.get(uid) or {}
                    rows.append({"employee_code": u.get("employee_code"),
                                 "name": u.get("name"),
                                 "leave_type": "Derived (month days − "
                                 "present − W/O)", "from_date": month,
                                 "to_date": month, "days": round(lv, 1),
                                 "status": "—"})
        rows.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
        cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
                ("leave_type", "Leave Type"), ("from_date", "From"),
                ("to_date", "To"), ("days", "Days"), ("status", "Status")]
        return (f"Leave with Wages Register — {month}", cols, rows, None)
    if kind == "muster-roll":
        recs = await db.attendance.find(
            {"company_id": company_id, "timestamp": {"$regex": f"^{day}"}},
            {"_id": 0, "user_id": 1, "timestamp": 1, "kind": 1}).to_list(50000)
        by_uid: Dict[str, List[dict]] = {}
        for r in recs:
            by_uid.setdefault(r["user_id"], []).append(r)
        umap = {u["user_id"]: u for u in users}
        rows = []
        for uid, rs in by_uid.items():
            u = umap.get(uid) or {}
            times = sorted(str(r.get("timestamp"))[11:16] for r in rs)
            in_t, out_t = times[0], times[-1] if len(times) > 1 else ""
            hrs = 0.0
            if out_t:
                try:
                    h1, m1 = map(int, in_t.split(":"))
                    h2, m2 = map(int, out_t.split(":"))
                    hrs = round((h2 * 60 + m2 - h1 * 60 - m1) / 60, 1)
                except ValueError:
                    pass
            rows.append({"employee_code": u.get("employee_code"),
                         "name": u.get("name"),
                         "department": u.get("department"),
                         "in_time": in_t, "out_time": out_t,
                         "working_hours": hrs,
                         "ot_hours": round(max(0.0, hrs - 8), 1),
                         "status": "P"})
        rows.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
        cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
                ("department", "Department"), ("in_time", "In Time"),
                ("out_time", "Out Time"), ("working_hours", "Working Hours"),
                ("ot_hours", "OT Hours"), ("status", "Status")]
        return (f"Daily Muster Roll Register — {day}", cols, rows, None)
    if kind == "working-hours":
        rows_by_uid = await _run_rows(company_id, month)
        umap = {u["user_id"]: u for u in users}
        rows = []
        for uid, r in rows_by_uid.items():
            u = umap.get(uid) or {}
            days = _f(r.get("present_days"))
            oth = _f(r.get("ot_hours"))
            mh = round(days * 8 + oth, 1)
            rows.append({"employee_code": u.get("employee_code"),
                         "name": u.get("name"),
                         "days": days, "normal_hours": round(days * 8, 1),
                         "ot_hours": oth, "monthly_hours": mh,
                         "violation": ("OT > 50 hrs" if oth > 50 else "")})
        rows.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
        cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
                ("days", "Days"), ("normal_hours", "Normal Hours"),
                ("ot_hours", "OT Hours"), ("monthly_hours", "Monthly Hours"),
                ("violation", "Violation Alert")]
        return (f"Working Hours & Overtime Register — {month}", cols, rows,
                None)
    if kind == "strength":
        depts: Dict[str, List[dict]] = {}
        for u in act:
            depts.setdefault(str(u.get("department") or "GENERAL").upper(),
                             []).append(u)
        rows = []
        for d in sorted(depts):
            us = depts[d]
            rows.append({
                "department": d,
                "permanent": sum(1 for u in us if _bucket(u) not in
                                 ("Contract", "Apprentice", "Trainee")),
                "contract": sum(1 for u in us if _bucket(u) == "Contract"),
                "apprentices": sum(1 for u in us
                                   if _bucket(u) == "Apprentice"),
                "trainees": sum(1 for u in us if _bucket(u) == "Trainee"),
                "male": sum(1 for u in us if _gender(u) == "Male"),
                "female": sum(1 for u in us if _gender(u) == "Female"),
                "total": len(us)})
        cols = [("department", "Department"), ("permanent", "Permanent"),
                ("contract", "Contract Labour"),
                ("apprentices", "Apprentices"), ("trainees", "Trainees"),
                ("male", "Male"), ("female", "Female"), ("total", "Total")]
        totals = {k: sum(r[k] for r in rows) for k, _l in cols[1:]}
        totals["department"] = "TOTAL"
        return ("Factory Strength Register", cols, rows, totals)
    raise HTTPException(status_code=404, detail="Unknown register")


async def _register(kind: str, company_id: str, day: str, month: str):
    if kind in _MASTER_KINDS:
        meta = _MASTER_KINDS[kind]
        recs = await db.factory_records.find(
            {"company_id": company_id, "kind": kind},
            {"_id": 0}).sort("created_at", 1).to_list(2000)
        cols = list(meta["fields"])
        rows = [dict(r.get("data") or {}, record_id=r["record_id"])
                for r in recs]
        return meta["title"], cols, rows, None
    return await _computed(kind, company_id, day, month)


@router.get("/dashboard")
async def factory_dashboard(company_id: Optional[str] = None,
                            authorization: Optional[str] = Header(None)):
    company_id, _a = await _adm(authorization, company_id)
    today = date.today()
    soon = today + timedelta(days=45)
    recs = await db.factory_records.find(
        {"company_id": company_id}, {"_id": 0}).to_list(5000)
    alerts: List[dict] = []
    counts: Dict[str, int] = {}
    for r in recs:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        due_field = _DUE_FIELDS.get(r["kind"])
        if not due_field:
            continue
        d = _dt((r.get("data") or {}).get(due_field))
        if d and d <= soon:
            what = _MASTER_KINDS[r["kind"]]["title"]
            ref = (r.get("data") or {}).get("license_no") \
                or (r.get("data") or {}).get("boiler_no") \
                or (r.get("data") or {}).get("employee") \
                or (r.get("data") or {}).get("equipment") or r["record_id"]
            alerts.append({"kind": r["kind"], "what": what, "ref": str(ref),
                           "due": d.isoformat(),
                           "status": "OVERDUE" if d < today else "DUE SOON"})
    alerts.sort(key=lambda a: a["due"])
    month_start = today.replace(day=1).isoformat()
    accidents = sum(1 for r in recs if r["kind"] == "accident"
                    and str((r.get("data") or {}).get("date") or "")
                    >= month_start)
    near_miss = sum(1 for r in recs if r["kind"] == "near-miss"
                    and str((r.get("data") or {}).get("date") or "")
                    >= month_start)
    overdue = sum(1 for a in alerts if a["status"] == "OVERDUE")
    total_due = len(alerts)
    compliance = max(0, round(100 - overdue * 15 - (total_due - overdue) * 5, 1))
    risk = min(100, round(overdue * 20 + accidents * 10 + near_miss * 3, 1))
    return {"alerts": alerts[:50], "record_counts": counts,
            "accidents_this_month": accidents,
            "near_miss_this_month": near_miss,
            "compliance_pct": compliance, "risk_pct": risk}


@router.get("/register/{kind}")
async def register_json(kind: str, company_id: Optional[str] = None,
                        day: Optional[str] = None,
                        month: Optional[str] = None,
                        authorization: Optional[str] = Header(None)):
    for ext in ("xlsx", "pdf"):  # /{kind} matches before /{kind}.{ext}
        if kind.endswith(f".{ext}"):
            return await _fexp(kind[: -len(ext) - 1], company_id, day,
                               month, authorization, ext)
    company_id, _a = await _adm(authorization, company_id)
    day = day or date.today().isoformat()
    month = month or date.today().strftime("%Y-%m")
    title, cols, rows, totals = await _register(kind, company_id, day, month)
    return {"title": title,
            "columns": [{"key": k, "label": lb} for k, lb in cols],
            "rows": rows, "totals": totals}


@router.get("/register/{kind}.xlsx")
async def register_x(kind: str, company_id: Optional[str] = None,
                     day: Optional[str] = None, month: Optional[str] = None,
                     authorization: Optional[str] = Header(None)):
    return await _fexp(kind, company_id, day, month, authorization, "xlsx")


@router.get("/register/{kind}.pdf")
async def register_p(kind: str, company_id: Optional[str] = None,
                     day: Optional[str] = None, month: Optional[str] = None,
                     authorization: Optional[str] = Header(None)):
    return await _fexp(kind, company_id, day, month, authorization, "pdf")


async def _fexp(kind, company_id, day, month, authorization, fmt):
    company_id, _a = await _adm(authorization, company_id)
    day = day or date.today().isoformat()
    month = month or date.today().strftime("%Y-%m")
    c = await _company(company_id)
    title, cols, rows, totals = await _register(kind, company_id, day, month)
    columns = [{"key": k, "label": lb} for k, lb in cols]
    sub = f"{c.get('name')} · Generated {datetime.now():%d-%m-%Y}"
    if fmt == "xlsx":
        buf = register_xlsx(title, sub, columns, rows, totals)
        mt = ("application/vnd.openxmlformats-officedocument"
              ".spreadsheetml.sheet")
    else:
        buf = register_pdf(title, sub, columns, rows, totals,
                           c.get("logo_base64"))
        mt = "application/pdf"
    fn_ = f"{title.replace(' ', '_').replace('—', '-')}.{fmt}"
    return StreamingResponse(buf, media_type=mt, headers={
        "Content-Disposition": f'attachment; filename="{fn_}"'})
