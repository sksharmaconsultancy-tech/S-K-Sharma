"""Iter 746 — OT MANAGEMENT (user PRD Phase 2).

Attendance OT → Policy validation (min-30-min, rounding, weekly/monthly
caps incl. the configurable 48-hr limit, holiday/weekoff toggles,
applicability) → Eligible vs Excess split → (optional) sequential approval
workflow over the org reporting chain → Approved OT → Payroll.

DEFAULT-SAFE: firms that never save an OT policy (or keep approval OFF)
are untouched — the compliance salary run keeps using grid OT exactly as
before. Only when ``approval_required`` is ON does payroll switch to
APPROVED OT hours.

Collections: ``ot_policies`` (company + optional branch overlay),
``ot_entries`` (one per employee+date), ``hr_audit`` (module="ot").
"""
import calendar
import uuid
from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db, get_user_from_token, now_iso, sub_admin_can_touch_company,
    _compute_monthly_grid_data,
)
from routes.statutory_extra_reports import _emit, _company, _master_gross, _num  # noqa: E402
from routes.org_structure import resolve_approval_chain, _audit  # noqa: E402

router = APIRouter(prefix="/api", tags=["ot-management"])

POLICY_DEFAULT = {
    "enabled": False,
    "approval_required": False,
    "min_ot_minutes": 30,          # PRD: 15/29 min → NOT eligible; 30+ → eligible
    "max_ot_hours_month": 48.0,    # PRD: configurable cap, default 48 (NOT hard-coded)
    "weekly_limit_hours": 0.0,     # 0 = no weekly cap
    "rounding": "none",            # none | down_15 | down_30 | nearest_15 | nearest_30
    "normal_working_hours": 8.0,
    "holiday_ot": True,
    "weekly_off_ot": True,
    "ot_rate_multiplier": 1.0,
    "departments": [],             # empty = all
    "employee_types": [],
    "shifts": [],
    "approval_levels": ["primary_manager"],  # ordered approver types
    "auto_approve": False,         # approval_required ke saath: chain na mile to auto
    "allow_override": True,
    "custom_note": "",
}


async def _authz(authorization, company_id, allow_employee=False):
    admin = await get_user_from_token(authorization)
    role = admin.get("role")
    if role == "employee" and allow_employee:
        return admin, admin.get("company_id")
    if role not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    if role == "company_admin":
        company_id = admin.get("company_id")
    if role == "sub_admin" and company_id:
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return admin, company_id


async def effective_ot_policy(company_id: str, branch_id: Optional[str] = None) -> dict:
    base = await db.ot_policies.find_one(
        {"company_id": company_id, "branch_id": None}, {"_id": 0}) or {}
    pol = {**POLICY_DEFAULT, **base}
    if branch_id:
        b = await db.ot_policies.find_one(
            {"company_id": company_id, "branch_id": branch_id}, {"_id": 0})
        if b:
            pol = {**pol, **{k: v for k, v in b.items() if v is not None}}
    pol["company_id"] = company_id
    return pol


def _round_ot(hours: float, rule: str) -> float:
    if hours <= 0:
        return 0.0
    mins = hours * 60.0
    if rule == "down_15":
        mins = (mins // 15) * 15
    elif rule == "down_30":
        mins = (mins // 30) * 30
    elif rule == "nearest_15":
        mins = round(mins / 15.0) * 15
    elif rule == "nearest_30":
        mins = round(mins / 30.0) * 30
    return round(mins / 60.0, 2)


@router.get("/ot/policy")
async def get_ot_policy(company_id: Optional[str] = Query(None),
                        branch_id: Optional[str] = Query(None),
                        authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    pol = await effective_ot_policy(company_id, branch_id)
    branches = [b async for b in db.branches.find(
        {"company_id": company_id}, {"_id": 0, "branch_id": 1, "name": 1})]
    overrides = [o["branch_id"] async for o in db.ot_policies.find(
        {"company_id": company_id, "branch_id": {"$ne": None}},
        {"_id": 0, "branch_id": 1})]
    return {"policy": pol, "branches": branches, "branch_overrides": overrides}


@router.post("/ot/policy")
async def save_ot_policy(payload: dict = Body(...),
                         authorization: Optional[str] = Header(None)):
    admin, company_id = await _authz(authorization, payload.get("company_id"))
    branch_id = payload.get("branch_id") or None
    doc = {"company_id": company_id, "branch_id": branch_id}
    for k, dflt in POLICY_DEFAULT.items():
        v = payload.get(k, dflt)
        if k in ("min_ot_minutes",):
            v = max(0, min(240, int(_num(v, 30))))
        elif k in ("max_ot_hours_month", "weekly_limit_hours",
                   "normal_working_hours", "ot_rate_multiplier"):
            v = max(0.0, float(_num(v, dflt)))
        elif k == "rounding":
            v = v if v in ("none", "down_15", "down_30", "nearest_15", "nearest_30") else "none"
        elif k == "approval_levels":
            valid = ("primary_manager", "secondary_manager", "dept_head",
                     "hr_manager", "final_approver", "admin")
            v = [x for x in (v or []) if x in valid] or ["primary_manager"]
        elif k in ("departments", "employee_types", "shifts"):
            v = [str(x) for x in (v or [])]
        elif k in ("enabled", "approval_required", "holiday_ot",
                   "weekly_off_ot", "auto_approve", "allow_override"):
            v = bool(v)
        doc[k] = v
    doc["updated_at"] = now_iso()
    doc["updated_by"] = admin.get("user_id")
    prev = await db.ot_policies.find_one(
        {"company_id": company_id, "branch_id": branch_id}, {"_id": 0})
    await db.ot_policies.update_one(
        {"company_id": company_id, "branch_id": branch_id},
        {"$set": doc}, upsert=True)
    await _audit("ot", "policy_save", f"{company_id}:{branch_id or 'firm'}",
                 prev, doc, admin)
    return {"ok": True, "policy": doc}


def _week_key(d: _date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


@router.post("/ot/generate")
async def generate_ot(payload: dict = Body(...),
                      authorization: Optional[str] = Header(None)):
    """Attendance → OT identification → policy validation → eligible/excess
    split → draft/pending/auto-approved entries. Re-running refreshes
    non-finalised entries; approved/rejected/payroll_processed are KEPT."""
    admin, company_id = await _authz(authorization, payload.get("company_id"))
    month = str(payload.get("month") or "")
    if len(month) != 7:
        raise HTTPException(status_code=400, detail="month YYYY-MM required")
    pol = await effective_ot_policy(company_id)
    if not pol.get("enabled"):
        raise HTTPException(status_code=400,
                            detail="OT Policy is not enabled for this firm")
    grid = await _compute_monthly_grid_data(company_id=company_id, month=month)
    y, m = int(month[:4]), int(month[5:7])
    month_days = calendar.monthrange(y, m)[1]
    min_h = pol["min_ot_minutes"] / 60.0
    cap_m = float(pol["max_ot_hours_month"] or 0)
    cap_w = float(pol["weekly_limit_hours"] or 0)
    dep_f = {d.strip().upper() for d in pol["departments"] if d.strip()}
    typ_f = {t.strip().upper() for t in pol["employee_types"] if t.strip()}
    shf_f = {s.strip().upper() for s in pol["shifts"] if s.strip()}
    created = updated = skipped_final = 0
    users_cache: dict = {}
    for r in grid.get("employees") or []:
        u = users_cache.get(r["user_id"])
        if u is None:
            u = await db.users.find_one({"user_id": r["user_id"]}, {"_id": 0}) or {}
            users_cache[r["user_id"]] = u
        if u.get("ot_applicable") is False:
            continue
        if dep_f and str(u.get("department") or "").strip().upper() not in dep_f:
            continue
        if typ_f and str(u.get("employee_type") or "").strip().upper() not in typ_f:
            continue
        if shf_f and str(u.get("shift_name") or "").strip().upper() not in shf_f:
            continue
        gross = _master_gross(u)
        hourly = round(gross / month_days / max(1.0, pol["normal_working_hours"]), 2) if gross else 0.0
        rate = round(hourly * float(pol["ot_rate_multiplier"] or 1.0), 2)
        used_m = 0.0
        used_w: dict = {}
        day_items = sorted((r.get("days") or {}).items(), key=lambda kv: kv[0])
        for dkey, cell in day_items:
            if not isinstance(cell, dict):
                continue
            att_ot = _num(cell.get("ot_hours"))
            if att_ot <= 0:
                continue
            try:
                dd = _date(y, m, int(dkey))
            except (ValueError, TypeError):
                continue
            date_iso = dd.isoformat()
            ot_type = ("holiday" if cell.get("holiday")
                       else "weekly_off" if cell.get("weekly_off") else "normal")
            eligible = att_ot
            reason_bits = []
            if ot_type == "holiday" and not pol["holiday_ot"]:
                eligible, reason_bits = 0.0, ["holiday OT disabled"]
            if ot_type == "weekly_off" and not pol["weekly_off_ot"]:
                eligible, reason_bits = 0.0, ["weekly-off OT disabled"]
            if eligible > 0 and eligible < min_h:
                eligible = 0.0
                reason_bits.append(f"< min {pol['min_ot_minutes']} min")
            if eligible > 0:
                eligible = _round_ot(eligible, pol["rounding"])
            wk = _week_key(dd)
            if eligible > 0 and cap_w > 0:
                room = max(0.0, cap_w - used_w.get(wk, 0.0))
                if eligible > room:
                    reason_bits.append("weekly limit")
                    eligible = round(room, 2)
            if eligible > 0 and cap_m > 0:
                room = max(0.0, cap_m - used_m)
                if eligible > room:
                    reason_bits.append(f"monthly cap {cap_m}h")
                    eligible = round(room, 2)
            used_m = round(used_m + eligible, 2)
            used_w[wk] = round(used_w.get(wk, 0.0) + eligible, 2)
            excess = round(att_ot - eligible, 2)
            prev = await db.ot_entries.find_one(
                {"company_id": company_id, "user_id": r["user_id"],
                 "date": date_iso}, {"_id": 0})
            if prev and prev.get("status") in ("approved", "rejected",
                                               "payroll_processed", "cancelled"):
                skipped_final += 1
                # cap accounting must still respect already-approved hours
                continue
            if pol["approval_required"]:
                chain = await resolve_approval_chain(u, pol["approval_levels"])
                status = "pending" if chain else (
                    "approved" if pol["auto_approve"] else "pending")
                if not chain and not pol["auto_approve"]:
                    chain = [{"approver_type": "admin", "user_id": None,
                              "name": "Admin/HR"}]
            else:
                chain, status = [], "approved"
            doc = {
                "entry_id": (prev or {}).get("entry_id") or f"ot_{uuid.uuid4().hex[:12]}",
                "company_id": company_id, "user_id": r["user_id"],
                "employee_code": u.get("employee_code"), "name": u.get("name"),
                "branch": u.get("branch_name") or "", "department": u.get("department") or "",
                "designation": u.get("designation") or "",
                "month": month, "date": date_iso,
                "shift": u.get("shift_name") or "",
                "in_time": cell.get("in"), "out_time": cell.get("out"),
                "normal_hours": pol["normal_working_hours"],
                "attendance_ot_hours": round(att_ot, 2),
                "eligible_ot_hours": round(eligible, 2),
                "excess_ot_hours": excess,
                "ot_type": ot_type,
                "ot_reason": "; ".join(reason_bits),
                "ot_rate": rate,
                "ot_amount": round(eligible * rate, 2),
                "rate_multiplier": pol["ot_rate_multiplier"],
                "status": status,
                "approval_level": 1 if status == "pending" else 0,
                "chain": [{**c, "status": "pending", "remarks": "", "at": None}
                          for c in chain],
                "updated_at": now_iso(),
            }
            if not prev:
                doc["created_at"] = now_iso()
                doc["created_by"] = admin.get("user_id")
                created += 1
            else:
                updated += 1
            await db.ot_entries.update_one(
                {"company_id": company_id, "user_id": r["user_id"], "date": date_iso},
                {"$set": doc}, upsert=True)
    await _audit("ot", "generate", f"{company_id}:{month}", None,
                 {"created": created, "updated": updated,
                  "kept_finalised": skipped_final}, admin)
    return {"ok": True, "created": created, "updated": updated,
            "kept_finalised": skipped_final,
            "approval_required": pol["approval_required"]}


def _summary(entries) -> dict:
    s = {"attendance_ot": 0.0, "eligible_ot": 0.0, "excess_ot": 0.0,
         "approved_ot": 0.0, "pending_ot": 0.0, "rejected_ot": 0.0,
         "payroll_ot": 0.0, "ot_cost": 0.0, "cap_violations": 0,
         "counts": {}}
    for e in entries:
        s["attendance_ot"] += _num(e.get("attendance_ot_hours"))
        s["eligible_ot"] += _num(e.get("eligible_ot_hours"))
        s["excess_ot"] += _num(e.get("excess_ot_hours"))
        st = e.get("status")
        s["counts"][st] = s["counts"].get(st, 0) + 1
        if _num(e.get("excess_ot_hours")) > 0:
            s["cap_violations"] += 1
        if st in ("approved", "payroll_processed"):
            s["approved_ot"] += _num(e.get("eligible_ot_hours"))
            s["ot_cost"] += _num(e.get("ot_amount"))
        if st == "payroll_processed":
            s["payroll_ot"] += _num(e.get("eligible_ot_hours"))
        if st in ("pending", "draft"):
            s["pending_ot"] += _num(e.get("eligible_ot_hours"))
        if st == "rejected":
            s["rejected_ot"] += _num(e.get("eligible_ot_hours"))
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.items()}


@router.get("/ot/entries")
async def list_ot_entries(company_id: Optional[str] = Query(None),
                          month: Optional[str] = Query(None),
                          status: Optional[str] = Query(None),
                          department: Optional[str] = Query(None),
                          branch: Optional[str] = Query(None),
                          user_id: Optional[str] = Query(None),
                          authorization: Optional[str] = Header(None)):
    actor, company_id = await _authz(authorization, company_id, allow_employee=True)
    flt: dict = {"company_id": company_id}
    if month:
        flt["month"] = month
    if status:
        flt["status"] = status
    if department:
        flt["department"] = {"$regex": f"^{department}$", "$options": "i"}
    if branch:
        flt["branch"] = {"$regex": f"^{branch}$", "$options": "i"}
    if actor.get("role") == "employee":
        # employees: own entries + entries where they are an approver
        flt = {"company_id": company_id,
               "$or": [{"user_id": actor["user_id"]},
                       {"chain.user_id": actor["user_id"]}]}
        if month:
            flt["month"] = month
    elif user_id:
        flt["user_id"] = user_id
    rows = [e async for e in db.ot_entries.find(flt, {"_id": 0})
            .sort([("date", 1), ("employee_code", 1)]).limit(3000)]
    return {"entries": rows, "summary": _summary(rows)}


@router.post("/ot/action")
async def ot_action(payload: dict = Body(...),
                    authorization: Optional[str] = Header(None)):
    """approve | reject | cancel | override — sequential level movement."""
    actor, company_id = await _authz(authorization, payload.get("company_id"),
                                     allow_employee=True)
    action = payload.get("action")
    ids = payload.get("entry_ids") or []
    remarks = str(payload.get("remarks") or "")
    if action not in ("approve", "reject", "cancel", "override") or not ids:
        raise HTTPException(status_code=400, detail="action + entry_ids required")
    is_admin = actor.get("role") in ("super_admin", "sub_admin", "company_admin")
    pol = await effective_ot_policy(company_id)
    done = 0
    for eid in ids:
        e = await db.ot_entries.find_one(
            {"entry_id": eid, "company_id": company_id}, {"_id": 0})
        if not e:
            continue
        if e.get("status") == "payroll_processed" and action != "override":
            raise HTTPException(status_code=409,
                                detail=f"{e.get('employee_code')} {e.get('date')}: payroll processed — modification locked")
        if action == "override":
            if not (is_admin and pol.get("allow_override")):
                raise HTTPException(status_code=403, detail="Override not permitted by policy")
            hours = round(_num(payload.get("override_hours"),
                               e.get("attendance_ot_hours")), 2)
            new = {"eligible_ot_hours": hours,
                   "excess_ot_hours": round(_num(e.get("attendance_ot_hours")) - hours, 2),
                   "ot_amount": round(hours * _num(e.get("ot_rate")), 2),
                   "status": "approved", "override": True,
                   "override_reason": remarks or "admin override",
                   "updated_at": now_iso()}
            await db.ot_entries.update_one({"entry_id": eid}, {"$set": new})
            await _audit("ot", "override", eid, e, new, actor, remarks)
            done += 1
            continue
        if action == "cancel":
            if not is_admin:
                raise HTTPException(status_code=403, detail="Only admin can cancel")
            await db.ot_entries.update_one(
                {"entry_id": eid},
                {"$set": {"status": "cancelled", "updated_at": now_iso()}})
            await _audit("ot", "cancel", eid, {"status": e.get("status")},
                         {"status": "cancelled"}, actor, remarks)
            done += 1
            continue
        if e.get("status") not in ("pending", "draft"):
            continue
        chain = e.get("chain") or []
        lvl = int(e.get("approval_level") or 1)
        idx = lvl - 1
        cur = chain[idx] if 0 <= idx < len(chain) else None
        if not is_admin:
            if not cur or cur.get("user_id") != actor.get("user_id"):
                raise HTTPException(status_code=403,
                                    detail="Aap is level ke approver nahi hain")
        stamp = {"status": "approved" if action == "approve" else "rejected",
                 "remarks": remarks, "at": now_iso(),
                 "acted_by": actor.get("user_id"),
                 "acted_by_name": actor.get("name")}
        if cur:
            chain[idx] = {**cur, **stamp}
        if action == "reject":
            new = {"status": "rejected", "chain": chain,
                   "rejection_reason": remarks, "updated_at": now_iso()}
        elif idx + 1 < len(chain):
            new = {"status": "pending", "approval_level": lvl + 1,
                   "chain": chain, "updated_at": now_iso()}
        else:
            new = {"status": "approved", "chain": chain,
                   "approved_at": now_iso(),
                   "approved_by": actor.get("user_id"), "updated_at": now_iso()}
        await db.ot_entries.update_one({"entry_id": eid}, {"$set": new})
        await _audit("ot", action, eid,
                     {"status": e.get("status"), "level": lvl},
                     {"status": new["status"],
                      "level": new.get("approval_level", lvl)}, actor, remarks)
        done += 1
    return {"ok": True, "processed": done}


@router.post("/ot/resubmit")
async def ot_resubmit(payload: dict = Body(...),
                      authorization: Optional[str] = Header(None)):
    """Rejected entry ko wapas pending me bhejta hai (level 1 se)."""
    admin, company_id = await _authz(authorization, payload.get("company_id"))
    n = 0
    for eid in (payload.get("entry_ids") or []):
        e = await db.ot_entries.find_one(
            {"entry_id": eid, "company_id": company_id, "status": "rejected"},
            {"_id": 0})
        if not e:
            continue
        chain = [{**c, "status": "pending", "remarks": "", "at": None}
                 for c in (e.get("chain") or [])]
        await db.ot_entries.update_one(
            {"entry_id": eid},
            {"$set": {"status": "pending", "approval_level": 1,
                      "chain": chain, "rejection_reason": "",
                      "updated_at": now_iso()}})
        await _audit("ot", "resubmit", eid, {"status": "rejected"},
                     {"status": "pending"}, admin)
        n += 1
    return {"ok": True, "resubmitted": n}


async def approved_ot_hours_map(company_id: str, month: str) -> Optional[dict]:
    """user_id → approved OT hours; ONLY when the firm's OT policy is
    enabled AND approval_required. None → payroll keeps grid OT (legacy)."""
    pol = await effective_ot_policy(company_id)
    if not (pol.get("enabled") and pol.get("approval_required")):
        return None
    out: dict = {}
    async for e in db.ot_entries.find(
            {"company_id": company_id, "month": month,
             "status": {"$in": ["approved", "payroll_processed"]}},
            {"_id": 0, "user_id": 1, "eligible_ot_hours": 1}):
        out[e["user_id"]] = round(out.get(e["user_id"], 0.0)
                                  + _num(e.get("eligible_ot_hours")), 2)
    return out


async def mark_ot_payroll_processed(company_id: str, month: str):
    await db.ot_entries.update_many(
        {"company_id": company_id, "month": month, "status": "approved"},
        {"$set": {"status": "payroll_processed",
                  "payroll_processed_at": now_iso()}})


# ─────────────── OT reports ───────────────

_OT_COLS = [("Emp Code", "employee_code", False), ("Name", "name", False),
            ("Branch", "branch", False), ("Department", "department", False),
            ("Date", "date", False), ("Shift", "shift", False),
            ("In", "in_time", False), ("Out", "out_time", False),
            ("Att. OT", "attendance_ot_hours", True),
            ("Eligible OT", "eligible_ot_hours", True),
            ("Excess OT", "excess_ot_hours", True),
            ("Type", "ot_type", False), ("Rate", "ot_rate", True),
            ("Amount", "ot_amount", True), ("Status", "status", False),
            ("Reason", "ot_reason", False)]


@router.get("/ot/report")
async def ot_report(kind: str = Query("register"),
                    fmt: str = Query("json"),
                    company_id: Optional[str] = Query(None),
                    month: Optional[str] = Query(None),
                    date_from: Optional[str] = Query(None),
                    date_to: Optional[str] = Query(None),
                    department: Optional[str] = Query(None),
                    branch: Optional[str] = Query(None),
                    user_id: Optional[str] = Query(None),
                    status: Optional[str] = Query(None),
                    ot_type: Optional[str] = Query(None),
                    authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    company = await _company(company_id)
    flt: dict = {"company_id": company_id}
    if month:
        flt["month"] = month
    if date_from or date_to:
        flt["date"] = {}
        if date_from:
            flt["date"]["$gte"] = date_from
        if date_to:
            flt["date"]["$lte"] = date_to
    if department:
        flt["department"] = {"$regex": f"^{department}$", "$options": "i"}
    if branch:
        flt["branch"] = {"$regex": f"^{branch}$", "$options": "i"}
    if user_id:
        flt["user_id"] = user_id
    if status:
        flt["status"] = status
    if ot_type:
        flt["ot_type"] = ot_type
    if kind == "approved":
        flt["status"] = {"$in": ["approved", "payroll_processed"]}
    elif kind == "pending":
        flt["status"] = {"$in": ["pending", "draft"]}
    elif kind == "rejected":
        flt["status"] = "rejected"
    elif kind == "excess":
        flt["excess_ot_hours"] = {"$gt": 0}
    rows = [e async for e in db.ot_entries.find(flt, {"_id": 0})
            .sort([("date", 1), ("employee_code", 1)]).limit(6000)]
    titles = {"register": "OT Register", "employee": "Employee-wise OT Report",
              "department": "Department-wise OT Report",
              "branch": "Branch-wise OT Report", "approved": "Approved OT Report",
              "pending": "Pending OT Report", "rejected": "Rejected OT Report",
              "excess": "Excess OT / Cap Violation Report",
              "cost": "OT Cost Report", "history": "OT Approval History"}
    title = titles.get(kind, "OT Register")
    sub = f"{month or (date_from or '') + '—' + (date_to or '')}"
    if kind in ("employee", "department", "branch", "cost"):
        key = {"employee": ("employee_code", "name"),
               "department": ("department",), "branch": ("branch",),
               "cost": ("employee_code", "name")}[kind]
        agg: dict = {}
        for e in rows:
            k = tuple(str(e.get(x) or "") for x in key)
            a = agg.setdefault(k, {"attendance_ot_hours": 0.0,
                                   "eligible_ot_hours": 0.0,
                                   "excess_ot_hours": 0.0, "ot_amount": 0.0,
                                   "days": 0,
                                   **{x: e.get(x) for x in
                                      ("employee_code", "name", "branch", "department")}})
            for f in ("attendance_ot_hours", "eligible_ot_hours",
                      "excess_ot_hours", "ot_amount"):
                a[f] = round(a[f] + _num(e.get(f)), 2)
            a["days"] += 1
        arows = sorted(agg.values(),
                       key=lambda x: str(x.get("employee_code") or x.get("department")
                                         or x.get("branch") or ""))
        cols = [("Emp Code", "employee_code", False), ("Name", "name", False),
                ("Branch", "branch", False), ("Department", "department", False),
                ("OT Days", "days", True), ("Att. OT", "attendance_ot_hours", True),
                ("Eligible OT", "eligible_ot_hours", True),
                ("Excess OT", "excess_ot_hours", True), ("OT Amount", "ot_amount", True)]
        if kind == "department":
            cols = [c for c in cols if c[1] not in ("employee_code", "name")]
        if kind == "branch":
            cols = [c for c in cols if c[1] not in ("employee_code", "name", "department")]
        return _emit(fmt, title=title, subtitle=sub, company=company,
                     cols=cols, rows=arows, fname_base=f"ot_{kind}_{month or 'range'}",
                     json_extra={"summary": _summary(rows)})
    if kind == "history":
        hrows = []
        for e in rows:
            for c in (e.get("chain") or []):
                if c.get("at"):
                    hrows.append({"employee_code": e.get("employee_code"),
                                  "name": e.get("name"), "date": e.get("date"),
                                  "level": c.get("approver_type"),
                                  "approver": c.get("acted_by_name") or c.get("name"),
                                  "action": c.get("status"), "remarks": c.get("remarks"),
                                  "at": c.get("at")})
        cols = [("Emp Code", "employee_code", False), ("Name", "name", False),
                ("Date", "date", False), ("Level", "level", False),
                ("Approver", "approver", False), ("Action", "action", False),
                ("Remarks", "remarks", False), ("At", "at", False)]
        return _emit(fmt, title=title, subtitle=sub, company=company,
                     cols=cols, rows=hrows, fname_base=f"ot_history_{month or 'range'}")
    return _emit(fmt, title=title, subtitle=sub, company=company,
                 cols=_OT_COLS, rows=rows, fname_base=f"ot_{kind}_{month or 'range'}",
                 json_extra={"summary": _summary(rows)})
