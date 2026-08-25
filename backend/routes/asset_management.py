"""Iter 731 — ASSET MANAGEMENT MODULE (user spec, enterprise-grade).

Standalone module — DOES NOT touch attendance / duty hours / compliance
salary / actual salary / payroll engines. Controlled integrations only:
  * Payroll recovery  → stamps approved monthly recovery into the DRAFT
    compliance run's Other Deduction (manual_fields stamped, same proven
    keep-rule used by Late Penalty) — engine itself untouched.
  * F&F               → exposes pending recovery via /admin/assets/clearance.
  * Notifications     → inserts into the existing db.notifications.

Collections: asset_categories, assets, asset_assignments, asset_incidents,
asset_repairs, asset_recoveries, asset_history (consolidated audit trail —
never deleted).
"""
import io
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from server import db, get_user_from_token, now_iso, sub_admin_can_touch_company  # noqa: E402
from routes.statutory_extra_reports import _emit, _company, _num  # noqa: E402

router = APIRouter(prefix="/api", tags=["assets"])

STATUSES = ["Available", "Assigned", "Under Repair", "Damaged", "Lost",
            "Returned", "Retired"]
DEFAULT_CATEGORIES = ["Laptop", "Desktop", "Mobile", "Tablet", "SIM",
                      "ID Card", "Vehicle", "Uniform", "Tools", "Machinery",
                      "Office Equipment", "Other"]
INCIDENT_TYPES = ["Damage", "Lost", "Missing Accessories", "Theft",
                  "Misuse", "Other"]

ADMIN_ROLES = ("super_admin", "sub_admin", "company_admin")


async def _authz(authorization, company_id=None):
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorised")
    if admin.get("role") == "company_admin":
        company_id = admin.get("company_id")
    if admin.get("role") == "sub_admin" and company_id:
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    return admin, company_id


async def _hist(asset_id, action, by, details="", old=None, new=None):
    await db.asset_history.insert_one({
        "history_id": f"ah_{uuid.uuid4().hex[:10]}", "asset_id": asset_id,
        "action": action, "details": details, "old_value": old,
        "new_value": new, "by": by, "at": now_iso()})


async def _notify(company_id, title, message, target_user_id=None):
    n = {"notification_id": f"n_{uuid.uuid4().hex[:10]}",
         "company_id": company_id, "title": title, "message": message,
         "audience": "user" if target_user_id else "all",
         "created_at": now_iso(), "created_by": "Asset Module"}
    if target_user_id:
        n["target_user_id"] = target_user_id
    await db.notifications.insert_one(n)


async def _get_asset(asset_id):
    a = await db.assets.find_one({"asset_id": asset_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Asset not found")
    return a


def _who(admin):
    return admin.get("name") or admin.get("user_id")


# ─────────────── CATEGORIES ───────────────

@router.get("/admin/assets/categories")
async def list_categories(company_id: Optional[str] = Query(None),
                          authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    custom = await db.asset_categories.find(
        {"company_id": company_id}, {"_id": 0}).to_list(200)
    names = DEFAULT_CATEGORIES + [c["name"] for c in custom
                                  if c["name"] not in DEFAULT_CATEGORIES]
    return {"categories": names}


@router.post("/admin/assets/categories")
async def add_category(payload: dict = Body(...),
                       authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, payload.get("company_id"))
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    await db.asset_categories.update_one(
        {"company_id": company_id, "name": name},
        {"$setOnInsert": {"category_id": f"ac_{uuid.uuid4().hex[:8]}",
                          "company_id": company_id, "name": name,
                          "created_at": now_iso()}}, upsert=True)
    return {"ok": True}


# ─────────────── ASSET MASTER ───────────────

ASSET_FIELDS = ["category", "name", "brand", "model", "serial_number",
                "imei", "reg_number", "purchase_date", "purchase_cost",
                "vendor", "warranty_start", "warranty_end", "amc_start",
                "amc_end", "branch", "location", "remarks", "photo_b64"]


@router.post("/admin/assets")
async def create_asset(payload: dict = Body(...),
                       authorization: Optional[str] = Header(None)):
    admin, company_id = await _authz(authorization, payload.get("company_id"))
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id required")
    if not (payload.get("name") and payload.get("category")):
        raise HTTPException(status_code=400, detail="name & category required")
    sn = (payload.get("serial_number") or "").strip()
    if sn and await db.assets.find_one(
            {"company_id": company_id, "serial_number": sn,
             "archived": {"$ne": True}}):
        raise HTTPException(status_code=400,
                            detail=f"Serial number {sn} already exists")
    seq = await db.assets.count_documents({"company_id": company_id}) + 1
    code = f"AST-{seq:04d}"
    while await db.assets.find_one({"company_id": company_id, "asset_code": code}):
        seq += 1
        code = f"AST-{seq:04d}"
    doc = {"asset_id": f"as_{uuid.uuid4().hex[:10]}", "asset_code": code,
           "company_id": company_id, "status": "Available",
           "archived": False, "created_at": now_iso(),
           "created_by": _who(admin)}
    for f in ASSET_FIELDS:
        doc[f] = payload.get(f)
    doc["purchase_cost"] = _num(doc.get("purchase_cost"))
    await db.assets.insert_one({**doc})
    await _hist(doc["asset_id"], "Purchased / Added to inventory",
                _who(admin), f"{doc['name']} ({code})")
    return {"ok": True, "asset": doc}


@router.patch("/admin/assets/{asset_id}")
async def update_asset(asset_id: str, payload: dict = Body(...),
                       authorization: Optional[str] = Header(None)):
    a = await _get_asset(asset_id)
    admin, _cid = await _authz(authorization, a["company_id"])
    changes, old = {}, {}
    for f in ASSET_FIELDS + ["status"]:
        if f in payload and payload[f] != a.get(f):
            old[f] = a.get(f)
            changes[f] = payload[f]
    if "status" in changes and changes["status"] not in STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if changes:
        if "purchase_cost" in changes:
            changes["purchase_cost"] = _num(changes["purchase_cost"])
        changes["updated_at"] = now_iso()
        changes["updated_by"] = _who(admin)
        await db.assets.update_one({"asset_id": asset_id}, {"$set": changes})
        await _hist(asset_id, "Updated", _who(admin),
                    ", ".join(k for k in changes if k not in ("updated_at", "updated_by")),
                    old=old, new={k: v for k, v in changes.items()
                                  if k not in ("updated_at", "updated_by")})
    return {"ok": True}


@router.get("/admin/assets")
async def list_assets(company_id: Optional[str] = Query(None),
                      q: Optional[str] = Query(None),
                      status: Optional[str] = Query(None),
                      category: Optional[str] = Query(None),
                      branch: Optional[str] = Query(None),
                      authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    f: dict = {"company_id": company_id, "archived": {"$ne": True}}
    if status:
        f["status"] = status
    if category:
        f["category"] = category
    if branch:
        f["branch"] = branch
    items = await db.assets.find(f, {"_id": 0, "photo_b64": 0}).sort(
        "asset_code", 1).to_list(3000)
    if q:
        n = q.strip().lower()
        items = [a for a in items if n in " ".join(
            str(a.get(k) or "") for k in
            ("asset_code", "name", "brand", "model", "serial_number",
             "imei", "assigned_to_name")).lower()]
    return {"assets": items}


@router.get("/admin/assets/{asset_id}/profile")
async def asset_profile(asset_id: str,
                        authorization: Optional[str] = Header(None)):
    a = await _get_asset(asset_id)
    await _authz(authorization, a["company_id"])
    hist = await db.asset_history.find(
        {"asset_id": asset_id}, {"_id": 0}).sort("at", -1).to_list(500)
    assigns = await db.asset_assignments.find(
        {"asset_id": asset_id}, {"_id": 0}).sort("assigned_date", -1).to_list(100)
    repairs = await db.asset_repairs.find(
        {"asset_id": asset_id}, {"_id": 0}).sort("complaint_date", -1).to_list(100)
    incidents = await db.asset_incidents.find(
        {"asset_id": asset_id}, {"_id": 0}).sort("incident_date", -1).to_list(100)
    return {"asset": a, "history": hist, "assignments": assigns,
            "repairs": repairs, "incidents": incidents}


@router.get("/admin/assets/{asset_id}/qr")
async def asset_qr(asset_id: str, token: Optional[str] = Query(None),
                   authorization: Optional[str] = Header(None)):
    import qrcode
    a = await _get_asset(asset_id)
    await _authz(authorization or (f"Bearer {token}" if token else None),
                 a["company_id"])
    img = qrcode.make(f"/asset-profile?id={asset_id}")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


# ─────────────── ASSIGN / RETURN / TRANSFER ───────────────

@router.post("/admin/assets/{asset_id}/assign")
async def assign_asset(asset_id: str, payload: dict = Body(...),
                       authorization: Optional[str] = Header(None)):
    a = await _get_asset(asset_id)
    admin, _cid = await _authz(authorization, a["company_id"])
    if a["status"] not in ("Available", "Returned"):
        raise HTTPException(status_code=400,
                            detail=f"Asset is {a['status']} — assign not allowed")
    user_id = payload.get("user_id")
    emp = await db.users.find_one({"user_id": user_id},
                                  {"_id": 0, "name": 1, "employee_code": 1,
                                   "department": 1, "designation": 1,
                                   "branch": 1, "branch_id": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    asg = {"assignment_id": f"asg_{uuid.uuid4().hex[:10]}",
           "asset_id": asset_id, "asset_code": a["asset_code"],
           "asset_name": a["name"], "company_id": a["company_id"],
           "user_id": user_id, "employee_name": emp.get("name"),
           "employee_code": emp.get("employee_code"),
           "department": emp.get("department"),
           "designation": emp.get("designation"),
           "branch": payload.get("branch") or emp.get("branch"),
           "location": payload.get("location"),
           "assigned_date": (payload.get("assigned_date") or now_iso())[:10],
           "issued_by": _who(admin),
           "condition_at_issue": payload.get("condition_at_issue") or "Good",
           "accessories": payload.get("accessories") or "",
           "expected_return_date": payload.get("expected_return_date"),
           "remarks": payload.get("remarks") or "",
           "acknowledged": False, "active": True, "created_at": now_iso()}
    await db.asset_assignments.insert_one({**asg})
    await db.assets.update_one({"asset_id": asset_id}, {"$set": {
        "status": "Assigned", "assigned_to": user_id,
        "assigned_to_name": emp.get("name"),
        "branch": asg["branch"], "location": asg["location"]}})
    await _hist(asset_id, "Assigned", _who(admin),
                f"→ {emp.get('name')} ({emp.get('employee_code') or ''})")
    await _notify(a["company_id"], "Asset Assigned",
                  f"{a['name']} ({a['asset_code']}) आपको issue हुआ है — "
                  "My Assets में acknowledge करें", user_id)
    return {"ok": True, "assignment": asg}


@router.post("/admin/assets/{asset_id}/return")
async def return_asset(asset_id: str, payload: dict = Body(...),
                       authorization: Optional[str] = Header(None)):
    a = await _get_asset(asset_id)
    admin, _cid = await _authz(authorization, a["company_id"])
    asg = await db.asset_assignments.find_one(
        {"asset_id": asset_id, "active": True}, {"_id": 0})
    if not asg:
        raise HTTPException(status_code=400, detail="No active assignment")
    condition = payload.get("condition_at_return") or "Good"
    outcome = (payload.get("outcome") or "available").lower()
    new_status = {"available": "Available", "damaged": "Damaged",
                  "repair": "Under Repair"}.get(outcome, "Available")
    await db.asset_assignments.update_one(
        {"assignment_id": asg["assignment_id"]},
        {"$set": {"active": False, "return_date": (payload.get("return_date") or now_iso())[:10],
                  "received_by": _who(admin),
                  "condition_at_return": condition,
                  "missing_accessories": payload.get("missing_accessories") or "",
                  "damage_details": payload.get("damage_details") or "",
                  "return_remarks": payload.get("remarks") or ""}})
    await db.assets.update_one({"asset_id": asset_id}, {"$set": {
        "status": new_status, "assigned_to": None, "assigned_to_name": None}})
    await _hist(asset_id, "Returned", _who(admin),
                f"from {asg.get('employee_name')} · condition: {condition} · → {new_status}")
    return {"ok": True, "new_status": new_status}


@router.post("/admin/assets/{asset_id}/transfer")
async def transfer_asset(asset_id: str, payload: dict = Body(...),
                         authorization: Optional[str] = Header(None)):
    a = await _get_asset(asset_id)
    admin, _cid = await _authz(authorization, a["company_id"])
    new_uid = payload.get("user_id")
    sets, det = {}, []
    if new_uid:
        emp = await db.users.find_one({"user_id": new_uid},
                                      {"_id": 0, "name": 1, "employee_code": 1,
                                       "department": 1, "designation": 1, "branch": 1})
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found")
        await db.asset_assignments.update_many(
            {"asset_id": asset_id, "active": True},
            {"$set": {"active": False, "return_date": now_iso()[:10],
                      "received_by": _who(admin),
                      "return_remarks": "Transferred"}})
        asg = {"assignment_id": f"asg_{uuid.uuid4().hex[:10]}",
               "asset_id": asset_id, "asset_code": a["asset_code"],
               "asset_name": a["name"], "company_id": a["company_id"],
               "user_id": new_uid, "employee_name": emp.get("name"),
               "employee_code": emp.get("employee_code"),
               "department": emp.get("department"),
               "designation": emp.get("designation"),
               "branch": payload.get("branch") or emp.get("branch"),
               "location": payload.get("location"),
               "assigned_date": now_iso()[:10], "issued_by": _who(admin),
               "condition_at_issue": payload.get("condition") or "Good",
               "accessories": "", "remarks": "Via transfer",
               "acknowledged": False, "active": True, "created_at": now_iso()}
        await db.asset_assignments.insert_one({**asg})
        sets.update({"status": "Assigned", "assigned_to": new_uid,
                     "assigned_to_name": emp.get("name")})
        det.append(f"{a.get('assigned_to_name') or '-'} → {emp.get('name')}")
        await _notify(a["company_id"], "Asset Transferred",
                      f"{a['name']} ({a['asset_code']}) आपको transfer हुआ है",
                      new_uid)
    for f in ("branch", "location", "department"):
        if payload.get(f):
            det.append(f"{f}: {a.get(f) or '-'} → {payload[f]}")
            sets[f] = payload[f]
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to transfer")
    await db.assets.update_one({"asset_id": asset_id}, {"$set": sets})
    await _hist(asset_id, "Transferred", _who(admin), " · ".join(det),
                old={k: a.get(k) for k in sets}, new=sets)
    return {"ok": True}


# ─────────────── INCIDENTS + RECOVERY ───────────────

@router.post("/admin/assets/{asset_id}/incident")
async def create_incident(asset_id: str, payload: dict = Body(...),
                          authorization: Optional[str] = Header(None)):
    a = await _get_asset(asset_id)
    admin, _cid = await _authz(authorization, a["company_id"])
    itype = payload.get("incident_type") or "Damage"
    if itype not in INCIDENT_TYPES:
        itype = "Other"
    inc = {"incident_id": f"inc_{uuid.uuid4().hex[:10]}",
           "asset_id": asset_id, "asset_code": a["asset_code"],
           "asset_name": a["name"], "company_id": a["company_id"],
           "user_id": payload.get("user_id") or a.get("assigned_to"),
           "employee_name": payload.get("employee_name") or a.get("assigned_to_name"),
           "incident_type": itype,
           "incident_date": (payload.get("incident_date") or now_iso())[:10],
           "description": payload.get("description") or "",
           "damage_details": payload.get("damage_details") or "",
           "estimated_amount": _num(payload.get("estimated_amount")),
           "approved_amount": 0.0, "approval_status": "pending",
           "recovery_status": "none", "remarks": payload.get("remarks") or "",
           "created_by": _who(admin), "created_at": now_iso()}
    await db.asset_incidents.insert_one({**inc})
    if itype == "Lost":
        await db.assets.update_one({"asset_id": asset_id},
                                   {"$set": {"status": "Lost"}})
    elif itype in ("Damage", "Theft"):
        await db.assets.update_one({"asset_id": asset_id},
                                   {"$set": {"status": "Damaged"}})
    await _hist(asset_id, f"Incident: {itype}", _who(admin),
                inc["description"][:120])
    return {"ok": True, "incident": inc}


@router.post("/admin/assets/incidents/{incident_id}/approve")
async def approve_incident(incident_id: str, payload: dict = Body(...),
                           authorization: Optional[str] = Header(None)):
    inc = await db.asset_incidents.find_one({"incident_id": incident_id}, {"_id": 0})
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    admin, _cid = await _authz(authorization, inc["company_id"])
    decision = (payload.get("decision") or "approved").lower()
    if decision == "rejected":
        await db.asset_incidents.update_one(
            {"incident_id": incident_id},
            {"$set": {"approval_status": "rejected",
                      "approved_by": _who(admin), "approved_at": now_iso()}})
        await _hist(inc["asset_id"], "Incident rejected", _who(admin))
        return {"ok": True}
    approved = _num(payload.get("approved_amount"))
    monthly = _num(payload.get("monthly_recovery"))
    sets = {"approval_status": "approved", "approved_amount": approved,
            "approved_by": _who(admin), "approved_at": now_iso()}
    rec = None
    if approved > 0 and inc.get("user_id"):
        if monthly <= 0:
            monthly = approved
        months = max(1, int(-(-approved // monthly)))  # ceil
        start = (payload.get("start_month") or now_iso()[:7])
        y, m = int(start[:4]), int(start[5:7])
        em = m + months - 1
        end = f"{y + (em - 1) // 12}-{((em - 1) % 12) + 1:02d}"
        rec = {"recovery_id": f"rec_{uuid.uuid4().hex[:10]}",
               "incident_id": incident_id, "asset_id": inc["asset_id"],
               "asset_code": inc.get("asset_code"),
               "company_id": inc["company_id"], "user_id": inc["user_id"],
               "employee_name": inc.get("employee_name"),
               "total_recovery": approved, "monthly_recovery": monthly,
               "recovered_amount": 0.0, "pending_amount": approved,
               "start_month": start, "end_month": end,
               "status": "active", "created_at": now_iso(),
               "created_by": _who(admin)}
        await db.asset_recoveries.insert_one({**rec})
        sets["recovery_status"] = "active"
        await _notify(inc["company_id"], "Asset Recovery Approved",
                      f"{inc.get('asset_name')} — ₹{approved} recovery "
                      f"(₹{monthly}/month, {start} से)", inc["user_id"])
    await db.asset_incidents.update_one({"incident_id": incident_id},
                                        {"$set": sets})
    await _hist(inc["asset_id"], "Incident approved", _who(admin),
                f"₹{approved} recovery" if approved else "no recovery")
    return {"ok": True, "recovery": rec}


@router.get("/admin/assets/recoveries")
async def list_recoveries(company_id: Optional[str] = Query(None),
                          authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    items = await db.asset_recoveries.find(
        {"company_id": company_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"recoveries": items}


@router.post("/admin/assets/recoveries/apply")
async def apply_recoveries(payload: dict = Body(...),
                           authorization: Optional[str] = Header(None)):
    """Stamp this month's recovery instalments into the DRAFT compliance
    run's Other Deduction (payroll engine untouched — same keep-rule as
    Late Penalty)."""
    _, company_id = await _authz(authorization, payload.get("company_id"))
    month = str(payload.get("month") or "")[:7]
    if not month:
        raise HTTPException(status_code=400, detail="month required")
    recs = await db.asset_recoveries.find(
        {"company_id": company_id, "status": "active",
         "start_month": {"$lte": month}, "end_month": {"$gte": month}},
        {"_id": 0}).to_list(500)
    due = {}
    for r in recs:
        amt = min(_num(r["monthly_recovery"]), _num(r["pending_amount"]))
        if amt > 0:
            due.setdefault(r["user_id"], []).append((r, round(amt, 2)))
    if not due:
        return {"ok": True, "applied": 0, "detail": "No recoveries due this month"}
    run = await db.compliance_salary_runs.find_one(
        {"company_id": company_id, "month": month,
         "status": {"$nin": ["finalized", "final", "locked"]}},
        {"_id": 0, "run_id": 1, "rows": 1}, sort=[("generated_at", -1)])
    if not run:
        raise HTTPException(status_code=404,
                            detail="No DRAFT compliance salary run for this month — pehle salary process karein")
    applied = 0
    rows = run.get("rows") or []
    for row in rows:
        pairs = due.get(row.get("user_id"))
        if not pairs:
            continue
        amt = round(sum(a for _r, a in pairs), 2)
        row["other_deduction"] = round(_num(row.get("other_deduction")) + amt, 2)
        row["other_deduction_head"] = "Asset Recovery"
        row["manual_fields"] = sorted(set(row.get("manual_fields") or []) | {"other_deduction"})
        applied += 1
        for r, a in pairs:
            new_rec = round(_num(r["recovered_amount"]) + a, 2)
            new_pen = round(_num(r["total_recovery"]) - new_rec, 2)
            await db.asset_recoveries.update_one(
                {"recovery_id": r["recovery_id"]},
                {"$set": {"recovered_amount": new_rec,
                          "pending_amount": max(0.0, new_pen),
                          "status": "completed" if new_pen <= 0 else "active",
                          "last_applied_month": month}})
    await db.compliance_salary_runs.update_one(
        {"run_id": run["run_id"]}, {"$set": {"rows": rows}})
    return {"ok": True, "applied": applied,
            "note": "Ab run ko REPROCESS (With EXISTING Data) karein — net refresh ho jayegi"}


# ─────────────── REPAIRS ───────────────

@router.post("/admin/assets/{asset_id}/repair")
async def create_repair(asset_id: str, payload: dict = Body(...),
                        authorization: Optional[str] = Header(None)):
    a = await _get_asset(asset_id)
    admin, _cid = await _authz(authorization, a["company_id"])
    rep = {"repair_id": f"rep_{uuid.uuid4().hex[:10]}",
           "asset_id": asset_id, "asset_code": a["asset_code"],
           "asset_name": a["name"], "company_id": a["company_id"],
           "complaint_date": (payload.get("complaint_date") or now_iso())[:10],
           "complaint_details": payload.get("complaint_details") or "",
           "service_vendor": payload.get("service_vendor") or "",
           "service_date": payload.get("service_date"),
           "repair_cost": _num(payload.get("repair_cost")),
           "parts_replaced": payload.get("parts_replaced") or "",
           "under_warranty": bool(payload.get("under_warranty")),
           "next_service_date": payload.get("next_service_date"),
           "status": "open", "remarks": payload.get("remarks") or "",
           "created_by": _who(admin), "created_at": now_iso()}
    await db.asset_repairs.insert_one({**rep})
    await db.assets.update_one({"asset_id": asset_id},
                               {"$set": {"status": "Under Repair"}})
    await _hist(asset_id, "Sent for repair", _who(admin),
                rep["complaint_details"][:120])
    return {"ok": True, "repair": rep}


@router.post("/admin/assets/repairs/{repair_id}/complete")
async def complete_repair(repair_id: str, payload: dict = Body(...),
                          authorization: Optional[str] = Header(None)):
    rep = await db.asset_repairs.find_one({"repair_id": repair_id}, {"_id": 0})
    if not rep:
        raise HTTPException(status_code=404, detail="Repair not found")
    admin, _cid = await _authz(authorization, rep["company_id"])
    sets = {"status": "completed", "completed_at": now_iso()}
    for f in ("repair_cost", "parts_replaced", "service_date",
              "next_service_date", "remarks"):
        if payload.get(f) is not None:
            sets[f] = _num(payload[f]) if f == "repair_cost" else payload[f]
    await db.asset_repairs.update_one({"repair_id": repair_id}, {"$set": sets})
    a = await _get_asset(rep["asset_id"])
    new_status = "Assigned" if a.get("assigned_to") else "Available"
    await db.assets.update_one({"asset_id": rep["asset_id"]},
                               {"$set": {"status": new_status}})
    await _hist(rep["asset_id"], "Repair completed", _who(admin),
                f"cost ₹{sets.get('repair_cost', rep.get('repair_cost'))} → {new_status}")
    return {"ok": True, "new_status": new_status}


@router.get("/admin/assets/repairs")
async def list_repairs(company_id: Optional[str] = Query(None),
                       authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    items = await db.asset_repairs.find(
        {"company_id": company_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"repairs": items}


@router.get("/admin/assets/incidents")
async def list_incidents(company_id: Optional[str] = Query(None),
                         authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    items = await db.asset_incidents.find(
        {"company_id": company_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"incidents": items}


# ─────────────── DASHBOARD / REPORTS / CLEARANCE ───────────────

@router.get("/admin/assets/dashboard")
async def asset_dashboard(company_id: Optional[str] = Query(None),
                          authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    assets = await db.assets.find(
        {"company_id": company_id, "archived": {"$ne": True}},
        {"_id": 0, "photo_b64": 0}).to_list(5000)
    by_status = {s: 0 for s in STATUSES}
    by_cat, by_branch = {}, {}
    total_value = 0.0
    today = now_iso()[:10]
    soon = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")
    warranty_exp, amc_exp = [], []
    for a in assets:
        by_status[a.get("status") or "Available"] = by_status.get(a.get("status") or "Available", 0) + 1
        by_cat[a.get("category") or "-"] = by_cat.get(a.get("category") or "-", 0) + 1
        if a.get("branch"):
            by_branch[a["branch"]] = by_branch.get(a["branch"], 0) + 1
        total_value += _num(a.get("purchase_cost"))
        we, ae = a.get("warranty_end"), a.get("amc_end")
        if we and today <= str(we)[:10] <= soon:
            warranty_exp.append({"asset_code": a["asset_code"], "name": a["name"], "date": we})
        if ae and today <= str(ae)[:10] <= soon:
            amc_exp.append({"asset_code": a["asset_code"], "name": a["name"], "date": ae})
    pend_ret = await db.asset_assignments.count_documents(
        {"company_id": company_id, "active": True,
         "expected_return_date": {"$ne": None, "$lt": today}})
    pend_appr = await db.asset_incidents.count_documents(
        {"company_id": company_id, "approval_status": "pending"})
    recs = await db.asset_recoveries.find(
        {"company_id": company_id, "status": "active"},
        {"_id": 0, "pending_amount": 1}).to_list(500)
    repair_cost = 0.0
    async for r in db.asset_repairs.find({"company_id": company_id},
                                         {"_id": 0, "repair_cost": 1}):
        repair_cost += _num(r.get("repair_cost"))
    return {"total_assets": len(assets), "by_status": by_status,
            "by_category": by_cat, "by_branch": by_branch,
            "total_value": round(total_value, 2),
            "warranty_expiring": warranty_exp, "amc_expiring": amc_exp,
            "pending_returns": pend_ret, "pending_approvals": pend_appr,
            "pending_recovery_amount": round(sum(_num(r["pending_amount"]) for r in recs), 2),
            "active_recoveries": len(recs),
            "total_repair_cost": round(repair_cost, 2)}


_REPORTS = {
    "register": ("Asset Register", "assets",
                 [("Code", "asset_code"), ("Category", "category"), ("Name", "name"),
                  ("Brand", "brand"), ("Model", "model"), ("Serial", "serial_number"),
                  ("Status", "status"), ("Assigned To", "assigned_to_name"),
                  ("Branch", "branch"), ("Purchase Date", "purchase_date"),
                  ("Cost", "purchase_cost"), ("Warranty End", "warranty_end")]),
    "assignments": ("Asset Assignment History", "asset_assignments",
                    [("Code", "asset_code"), ("Asset", "asset_name"),
                     ("Employee", "employee_name"), ("Emp Code", "employee_code"),
                     ("Dept", "department"), ("Branch", "branch"),
                     ("Issued", "assigned_date"), ("Issued By", "issued_by"),
                     ("Returned", "return_date"), ("Condition", "condition_at_return"),
                     ("Ack", "acknowledged")]),
    "incidents": ("Asset Damage / Loss Report", "asset_incidents",
                  [("Code", "asset_code"), ("Asset", "asset_name"),
                   ("Employee", "employee_name"), ("Type", "incident_type"),
                   ("Date", "incident_date"), ("Est ₹", "estimated_amount"),
                   ("Approved ₹", "approved_amount"), ("Approval", "approval_status"),
                   ("Recovery", "recovery_status")]),
    "repairs": ("Repair / Maintenance Report", "asset_repairs",
                [("Code", "asset_code"), ("Asset", "asset_name"),
                 ("Complaint", "complaint_date"), ("Vendor", "service_vendor"),
                 ("Service", "service_date"), ("Cost", "repair_cost"),
                 ("Parts", "parts_replaced"), ("Status", "status"),
                 ("Next Service", "next_service_date")]),
    "recoveries": ("Asset Recovery Report", "asset_recoveries",
                   [("Code", "asset_code"), ("Employee", "employee_name"),
                    ("Total ₹", "total_recovery"), ("Monthly ₹", "monthly_recovery"),
                    ("Recovered ₹", "recovered_amount"), ("Pending ₹", "pending_amount"),
                    ("From", "start_month"), ("To", "end_month"),
                    ("Status", "status")]),
}


@router.get("/admin/assets/report/{kind}")
async def asset_report(kind: str, company_id: Optional[str] = Query(None),
                       fmt: str = Query("excel"),
                       authorization: Optional[str] = Header(None),
                       token: Optional[str] = Query(None)):
    _, company_id = await _authz(
        authorization or (f"Bearer {token}" if token else None), company_id)
    if kind not in _REPORTS:
        raise HTTPException(status_code=404, detail="Unknown report")
    title, coll, cols = _REPORTS[kind]
    f: dict = {"company_id": company_id}
    if coll == "assets":
        f["archived"] = {"$ne": True}
    rows = await db[coll].find(f, {"_id": 0, "photo_b64": 0}).to_list(5000)
    company = await _company(company_id)
    ecols = [(h, k, k.endswith(("cost", "amount", "recovery"))) for h, k in cols]
    return _emit(fmt, title=title, subtitle=f"Generated {now_iso()[:10]}",
                 company=company, cols=ecols, rows=rows,
                 fname_base=f"Asset_{kind}")


@router.get("/admin/assets/clearance/{user_id}")
async def asset_clearance(user_id: str,
                          authorization: Optional[str] = Header(None)):
    """Exit / FNF checklist — active assets + pending recovery for one
    employee (FNF engine untouched; this is read-only info)."""
    emp = await db.users.find_one({"user_id": user_id},
                                  {"_id": 0, "company_id": 1, "name": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    await _authz(authorization, emp.get("company_id"))
    active = await db.asset_assignments.find(
        {"user_id": user_id, "active": True}, {"_id": 0}).to_list(100)
    returned = await db.asset_assignments.find(
        {"user_id": user_id, "active": False}, {"_id": 0}).sort(
        "return_date", -1).to_list(100)
    recs = await db.asset_recoveries.find(
        {"user_id": user_id, "status": "active"}, {"_id": 0}).to_list(100)
    return {"employee": emp, "pending_assets": active,
            "returned_assets": returned,
            "pending_recovery": round(sum(_num(r["pending_amount"]) for r in recs), 2),
            "recoveries": recs,
            "clear": len(active) == 0 and not recs}


# ─────────────── EMPLOYEE PWA — MY ASSETS ───────────────

@router.get("/my/assets")
async def my_assets(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    assigns = await db.asset_assignments.find(
        {"user_id": user["user_id"], "active": True}, {"_id": 0}).to_list(50)
    out = []
    for asg in assigns:
        a = await db.assets.find_one(
            {"asset_id": asg["asset_id"]},
            {"_id": 0, "name": 1, "asset_code": 1, "serial_number": 1,
             "brand": 1, "model": 1, "warranty_end": 1, "category": 1,
             "status": 1}) or {}
        out.append({**asg, "asset": a})
    return {"assets": out}


@router.post("/my/assets/{assignment_id}/ack")
async def acknowledge_asset(assignment_id: str,
                            authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    asg = await db.asset_assignments.find_one(
        {"assignment_id": assignment_id, "user_id": user["user_id"]}, {"_id": 0})
    if not asg:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await db.asset_assignments.update_one(
        {"assignment_id": assignment_id},
        {"$set": {"acknowledged": True, "ack_at": now_iso()}})
    await _hist(asg["asset_id"], "Acknowledged by employee",
                user.get("name") or user["user_id"])
    return {"ok": True}


@router.post("/my/assets/{assignment_id}/report")
async def report_asset_issue(assignment_id: str, payload: dict = Body(...),
                             authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    asg = await db.asset_assignments.find_one(
        {"assignment_id": assignment_id, "user_id": user["user_id"]}, {"_id": 0})
    if not asg:
        raise HTTPException(status_code=404, detail="Assignment not found")
    rtype = (payload.get("type") or "issue").lower()  # issue|repair|return
    note = (payload.get("note") or "").strip()
    label = {"issue": "Issue reported", "repair": "Repair requested",
             "return": "Return requested"}.get(rtype, "Issue reported")
    await _hist(asg["asset_id"], f"{label} (employee)",
                user.get("name") or user["user_id"], note[:200])
    await _notify(asg["company_id"], f"Asset {label}",
                  f"{asg.get('asset_name')} ({asg.get('asset_code')}) — "
                  f"{user.get('name')}: {note or label}")
    return {"ok": True}
