"""Iter 581 — Attendance Eligibility HR workflow.

* GET  /api/attendance/onboarding-status          — employee PWA banner.
* GET  /api/admin/attendance-eligibility/summary  — per-employee held /
        blocked counts + currently-missing onboarding items.
* GET  /api/admin/attendance-eligibility/records  — raw held/blocked list.
* POST /api/admin/attendance-eligibility/release  — release to the punch's
        original status. Reason is MANDATORY when any record is BLOCKED.
* POST /api/admin/attendance-eligibility/reject   — reject (reason always
        mandatory). Raw punches are never deleted.
"""
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    now_iso,
    require_role,
    sub_admin_can_touch_company,
)
from shared.attendance_eligibility import (  # noqa: E402
    REQUIREMENT_LABELS,
    USER_PROJECTION,
    classify,
    gate_from_company,
    has_profile_photo,
    missing_requirements,
)

router = APIRouter(prefix="/api")

_ADMIN_ROLES = ["super_admin", "sub_admin", "company_admin"]


def _rid_sel(r: dict) -> Dict[str, Any]:
    """Attendance records carry either record_id (app/biometric/API) or
    attendance_id (zk_push) — build the right update selector."""
    if r.get("record_id"):
        return {"record_id": r["record_id"]}
    return {"attendance_id": r.get("attendance_id")}


async def _scoped_company_id(admin: dict, company_id: Optional[str]) -> str:
    if admin["role"] == "company_admin":
        cid = admin.get("company_id")
        if not cid:
            raise HTTPException(status_code=400, detail="You are not linked to any company")
        return cid
    if not company_id:
        raise HTTPException(status_code=400, detail="Please pass ?company_id=")
    if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm not in your scope")
    return company_id


# ---------------------------------------------------------------------------
# Employee-facing onboarding status (PWA banner + checklist).
# ---------------------------------------------------------------------------
@router.get("/attendance/onboarding-status")
async def onboarding_status(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    if user.get("role") != "employee" or not user.get("company_id"):
        return {"gate_enabled": False}
    company = await db.companies.find_one(
        {"company_id": user["company_id"]},
        {"_id": 0, "attendance_policy.onboarding_gate": 1, "attendance_policy.policy_version": 1}) or {}
    gate = gate_from_company(company)
    if not gate["enabled"]:
        return {"gate_enabled": False}
    fresh = await db.users.find_one({"user_id": user["user_id"]}, USER_PROJECTION) or {}
    hp = await has_profile_photo(db, user["user_id"]) if gate["require_photo"] else None
    missing = missing_requirements(fresh, gate, has_photo=hp)
    ev = classify(gate, missing, fresh, date.today().isoformat())
    held = await db.attendance.count_documents(
        {"user_id": user["user_id"], "status": "held"})
    blocked = await db.attendance.count_documents(
        {"user_id": user["user_id"], "status": "blocked"})
    # Iter 582 — onboarding completion % for the PWA widget.
    required = [k for k, flag in (
        ("aadhaar", gate["require_aadhaar"]), ("bank", gate["require_bank"]),
        ("pan", gate["require_pan"]), ("photo", gate["require_photo"])) if flag]
    completed = [k for k in required if k not in missing]
    return {
        "gate_enabled": True,
        "eligibility": ev["eligibility"],
        "missing": [{"key": m, "label": REQUIREMENT_LABELS.get(m, m)} for m in missing],
        "permission_days": ev["permission_days"],
        "days_left": ev["days_left"],
        "deadline": ev["deadline"],
        "auto_release": gate["auto_release"],
        "held_count": held,
        "blocked_count": blocked,
        "required_count": len(required),
        "completed_count": len(completed),
        "onboarding_pct": round(len(completed) * 100 / len(required)) if required else 100,
    }


# ---------------------------------------------------------------------------
# HR dashboard — summary grouped by employee.
# ---------------------------------------------------------------------------
@router.get("/admin/attendance-eligibility/summary")
async def eligibility_summary(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    cid = await _scoped_company_id(admin, company_id)
    company = await db.companies.find_one(
        {"company_id": cid}, {"_id": 0, "attendance_policy.onboarding_gate": 1, "attendance_policy.policy_version": 1}) or {}
    gate = gate_from_company(company)

    rows = await db.attendance.aggregate([
        {"$match": {"company_id": cid, "status": {"$in": ["held", "blocked"]}}},
        {"$group": {
            "_id": {"user_id": "$user_id", "status": "$status"},
            "count": {"$sum": 1},
            "first_date": {"$min": "$date"},
            "last_date": {"$max": "$date"},
        }},
    ]).to_list(2000)

    per_user: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        uid = r["_id"]["user_id"]
        st = r["_id"]["status"]
        e = per_user.setdefault(uid, {
            "user_id": uid, "held_count": 0, "blocked_count": 0,
            "first_date": r["first_date"], "last_date": r["last_date"]})
        e[f"{st}_count"] = r["count"]
        e["first_date"] = min(e["first_date"], r["first_date"])
        e["last_date"] = max(e["last_date"], r["last_date"])

    uids = list(per_user.keys())
    docs = {u["user_id"]: u async for u in db.users.find(
        {"user_id": {"$in": uids}}, USER_PROJECTION)}
    with_photo: set = set()
    if gate["require_photo"] and uids:
        with_photo = set(await db.users.distinct(
            "user_id",
            {"user_id": {"$in": uids},
             "profile_photo_base64": {"$nin": [None, ""]}}))
    employees: List[dict] = []
    for uid, e in per_user.items():
        u = docs.get(uid) or {}
        missing = missing_requirements(
            u, gate,
            has_photo=(uid in with_photo) if gate["require_photo"] else None) \
            if gate["enabled"] else []
        ev = classify(gate, missing, u, date.today().isoformat())
        employees.append({
            **e,
            "name": u.get("name"),
            "employee_code": u.get("employee_code"),
            "missing": [{"key": m, "label": REQUIREMENT_LABELS.get(m, m)} for m in missing],
            "data_complete": not missing,
            "days_left": ev["days_left"],
            "deadline": ev["deadline"],
        })
    employees.sort(key=lambda x: (x["blocked_count"] == 0, x.get("name") or ""))

    # Iter 582 — firm-wide onboarding completion widget (all active
    # employees, not just those with held/blocked punches).
    onboarding = None
    if gate["enabled"]:
        req_keys = [k for k in ("require_aadhaar", "require_bank",
                                "require_pan", "require_photo") if gate[k]]
        emp_docs = await db.users.find(
            {"company_id": cid, "role": "employee", "active": {"$ne": False}},
            USER_PROJECTION).to_list(20000)
        firm_photo: set = set()
        if gate["require_photo"] and emp_docs:
            firm_photo = set(await db.users.distinct(
                "user_id",
                {"company_id": cid, "role": "employee",
                 "profile_photo_base64": {"$nin": [None, ""]}}))
        complete_ct = 0
        items_done = items_total = 0
        for u in emp_docs:
            miss = missing_requirements(
                u, gate,
                has_photo=(u["user_id"] in firm_photo) if gate["require_photo"] else None)
            items_total += len(req_keys)
            items_done += len(req_keys) - len(miss)
            if not miss:
                complete_ct += 1
        onboarding = {
            "total_employees": len(emp_docs),
            "complete": complete_ct,
            "incomplete": len(emp_docs) - complete_ct,
            "pct": round(complete_ct * 100 / len(emp_docs)) if emp_docs else 100,
            "items_pct": round(items_done * 100 / items_total) if items_total else 100,
            "required_items": [REQUIREMENT_LABELS[k.replace("require_", "")]
                               for k in req_keys],
        }
    return {
        "gate": gate,
        "employees": employees,
        "onboarding": onboarding,
        "totals": {
            "held": sum(e["held_count"] for e in employees),
            "blocked": sum(e["blocked_count"] for e in employees),
            "employees": len(employees),
        },
    }


@router.get("/admin/attendance-eligibility/records")
async def eligibility_records(
    company_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="held | blocked | released | rejected"),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    cid = await _scoped_company_id(admin, company_id)
    q: Dict[str, Any] = {"company_id": cid}
    st = (status or "").strip().lower()
    if st in ("held", "blocked"):
        q["status"] = st
    elif st in ("released", "rejected"):
        q["eligibility_status"] = st.upper()
    else:
        q["status"] = {"$in": ["held", "blocked"]}
    if user_id:
        q["user_id"] = user_id
    recs = await db.attendance.find(
        q, {"_id": 0, "selfie_base64": 0}).sort("at", -1).to_list(500)
    uids = list({r.get("user_id") for r in recs})
    names = {u["user_id"]: u async for u in db.users.find(
        {"user_id": {"$in": uids}},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1})}
    for r in recs:
        u = names.get(r.get("user_id")) or {}
        r["employee_name"] = u.get("name")
        r["employee_code"] = u.get("employee_code")
        # zk_push rows carry attendance_id — normalise for the UI selection.
        if not r.get("record_id"):
            r["record_id"] = r.get("attendance_id")
        r["missing_labels"] = [REQUIREMENT_LABELS.get(m, m)
                               for m in (r.get("eligibility_missing") or [])]
    return {"records": recs, "count": len(recs)}


# ---------------------------------------------------------------------------
# Release / Reject.
# ---------------------------------------------------------------------------
async def _load_target_records(cid: str, payload: dict) -> List[dict]:
    q: Dict[str, Any] = {"company_id": cid, "status": {"$in": ["held", "blocked"]}}
    record_ids = payload.get("record_ids")
    user_id = (payload.get("user_id") or "").strip()
    if isinstance(record_ids, list) and record_ids:
        ids = [str(r) for r in record_ids][:1000]
        q["$or"] = [{"record_id": {"$in": ids}}, {"attendance_id": {"$in": ids}}]
    elif user_id:
        q["user_id"] = user_id
    else:
        raise HTTPException(status_code=400,
                            detail="Pass record_ids[] or user_id")
    recs = await db.attendance.find(
        q, {"_id": 0, "record_id": 1, "attendance_id": 1, "user_id": 1,
            "status": 1, "pre_hold_status": 1, "date": 1, "kind": 1,
            "at": 1}).to_list(1000)
    if not recs:
        raise HTTPException(status_code=404,
                            detail="No held/blocked punches matched")
    return recs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _notify_employees(recs: List[dict], cid: str, action: str, reason: str) -> None:
    by_user: Dict[str, int] = {}
    for r in recs:
        by_user[r["user_id"]] = by_user.get(r["user_id"], 0) + 1
    docs = []
    for uid, n in by_user.items():
        verb = "released" if action == "release" else "rejected"
        docs.append({
            "notification_id": f"n_{uuid.uuid4().hex[:10]}",
            "company_id": cid,
            "audience": "user",
            "target_user_id": uid,
            "type": f"attendance.{verb}",
            "title": f"Attendance {verb}",
            "body": (f"HR {verb} {n} of your held/blocked "
                     f"punch{'es' if n != 1 else ''}."
                     + (f" Reason: {reason}" if reason else "")),
            "created_at": _now(),
            "created_by": "system",
        })
    if docs:
        await db.notifications.insert_many(docs)


@router.post("/admin/attendance-eligibility/release")
async def release_punches(
    payload: Dict[str, Any] = Body(...),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Release held/blocked punches back to their original status.

    Reason is MANDATORY when ANY selected record is BLOCKED (user rule:
    'HR still release them manually with authenticate reason')."""
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    cid = await _scoped_company_id(admin, company_id or payload.get("company_id"))
    recs = await _load_target_records(cid, payload)
    reason = str(payload.get("reason") or "").strip()
    any_blocked = any(r.get("status") == "blocked" for r in recs)
    if any_blocked and not reason:
        raise HTTPException(
            status_code=400,
            detail="Release reason is MANDATORY when releasing BLOCKED attendance.")
    released = 0
    for r in recs:
        res = await db.attendance.update_one(
            {**_rid_sel(r), "status": {"$in": ["held", "blocked"]}},
            {"$set": {
                "status": r.get("pre_hold_status") or "approved",
                "eligibility_status": "RELEASED",
                "released_at": _now(),
                "released_by": admin["user_id"],
                "released_from": r.get("status"),
                "release_reason": reason or "Onboarding data completed — released by HR",
            }})
        released += res.modified_count
    await db.eligibility_release_log.insert_one({
        "log_id": f"erl_{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        "action": "release",
        "record_ids": [r.get("record_id") or r.get("attendance_id") for r in recs],
        "count": released,
        "included_blocked": any_blocked,
        "reason": reason,
        "by_user_id": admin["user_id"],
        "by_role": admin["role"],
        "at": now_iso(),
    })
    await _notify_employees(recs, cid, "release", reason)
    return {"ok": True, "released": released}


@router.post("/admin/attendance-eligibility/reject")
async def reject_punches(
    payload: Dict[str, Any] = Body(...),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Reject held/blocked punches. Raw punch stays on file (status
    'rejected', eligibility REJECTED). Reason is always mandatory."""
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    cid = await _scoped_company_id(admin, company_id or payload.get("company_id"))
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400,
                            detail="Rejection reason is mandatory.")
    recs = await _load_target_records(cid, payload)
    rejected = 0
    for r in recs:
        res = await db.attendance.update_one(
            {**_rid_sel(r), "status": {"$in": ["held", "blocked"]}},
            {"$set": {
                "status": "rejected",
                "eligibility_status": "REJECTED",
                "decision_by": admin["user_id"],
                "decision_at": _now(),
                "decision_reason": reason,
            }})
        rejected += res.modified_count
    await db.eligibility_release_log.insert_one({
        "log_id": f"erl_{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        "action": "reject",
        "record_ids": [r.get("record_id") or r.get("attendance_id") for r in recs],
        "count": rejected,
        "reason": reason,
        "by_user_id": admin["user_id"],
        "by_role": admin["role"],
        "at": now_iso(),
    })
    await _notify_employees(recs, cid, "reject", reason)
    return {"ok": True, "rejected": rejected}


@router.post("/admin/attendance-eligibility/reprocess")
async def reprocess_eligibility(
    payload: Dict[str, Any] = Body(default={}),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Iter 583 — POLICY VERSIONING / EXPLICIT REPROCESS.

    Historical punches always keep the eligibility decision (and
    policy_version) they were stamped with; changing the Attendance Policy
    never rewrites them silently. This endpoint is the ONLY way to
    re-evaluate: every HELD/BLOCKED punch (optionally filtered by user /
    date range) is re-run through the CURRENT policy + CURRENT employee
    data:

      * data complete (or gate now off) → RELEASED (reason MANDATORY when
        any BLOCKED punch would be released — user rule)
      * data missing, inside the window  → HELD
      * data missing, window over        → BLOCKED
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    cid = await _scoped_company_id(admin, company_id or payload.get("company_id"))
    company = await db.companies.find_one(
        {"company_id": cid},
        {"_id": 0, "attendance_policy.onboarding_gate": 1,
         "attendance_policy.policy_version": 1}) or {}
    gate = gate_from_company(company)
    ver = int(gate.get("policy_version") or 1)

    q: Dict[str, Any] = {"company_id": cid, "status": {"$in": ["held", "blocked"]}}
    if payload.get("user_id"):
        q["user_id"] = str(payload["user_id"]).strip()
    date_q: Dict[str, Any] = {}
    if payload.get("from_date"):
        date_q["$gte"] = str(payload["from_date"])[:10]
    if payload.get("to_date"):
        date_q["$lte"] = str(payload["to_date"])[:10]
    if date_q:
        q["date"] = date_q
    recs = await db.attendance.find(
        q, {"_id": 0, "record_id": 1, "attendance_id": 1, "user_id": 1,
            "status": 1, "pre_hold_status": 1, "date": 1}).to_list(5000)
    if not recs:
        return {"ok": True, "total": 0, "released": 0, "held": 0,
                "blocked": 0, "unchanged": 0, "policy_version": ver}

    reason = str(payload.get("reason") or "").strip()
    uids = list({r["user_id"] for r in recs})
    docs = {u["user_id"]: u async for u in db.users.find(
        {"user_id": {"$in": uids}}, USER_PROJECTION)}
    with_photo: set = set()
    if gate["enabled"] and gate["require_photo"]:
        with_photo = set(await db.users.distinct(
            "user_id", {"user_id": {"$in": uids},
                        "profile_photo_base64": {"$nin": [None, ""]}}))

    plan = []
    for r in recs:
        u = docs.get(r["user_id"]) or {}
        if not gate["enabled"]:
            plan.append((r, "ACTIVE", None))
            continue
        missing = missing_requirements(
            u, gate,
            has_photo=(r["user_id"] in with_photo) if gate["require_photo"] else None)
        ev = classify(gate, missing, u, r["date"])
        plan.append((r, ev["eligibility"], ev))

    if any(r["status"] == "blocked" and new == "ACTIVE" for r, new, _ in plan) \
            and not reason:
        raise HTTPException(
            status_code=400,
            detail="Reason is MANDATORY — this reprocess would release "
                   "BLOCKED punches.")

    now = _now()
    released = held = blocked = unchanged = 0
    for r, new, ev in plan:
        if new == "ACTIVE":
            await db.attendance.update_one(
                {**_rid_sel(r), "status": {"$in": ["held", "blocked"]}},
                {"$set": {
                    "status": r.get("pre_hold_status") or "approved",
                    "eligibility_status": "RELEASED",
                    "released_at": now,
                    "released_by": admin["user_id"],
                    "released_from": r.get("status"),
                    "release_reason": reason or f"Reprocessed under policy v{ver}",
                    "policy_version": ver,
                    "reprocessed_at": now,
                }})
            released += 1
        else:
            new_status = "held" if new == "HELD" else "blocked"
            if new_status == r.get("status"):
                unchanged += 1
            elif new_status == "held":
                held += 1
            else:
                blocked += 1
            await db.attendance.update_one(
                {**_rid_sel(r), "status": {"$in": ["held", "blocked"]}},
                {"$set": {
                    "status": new_status,
                    "eligibility_status": new.upper(),
                    "eligibility_missing": (ev or {}).get("missing") or [],
                    "eligibility_deadline": (ev or {}).get("deadline"),
                    "policy_version": ver,
                    "reprocessed_at": now,
                    "reprocessed_by": admin["user_id"],
                }})
    await db.eligibility_release_log.insert_one({
        "log_id": f"erl_{uuid.uuid4().hex[:12]}",
        "company_id": cid,
        "action": "reprocess",
        "policy_version": ver,
        "count": len(plan),
        "released": released,
        "moved_to_held": held,
        "moved_to_blocked": blocked,
        "unchanged": unchanged,
        "reason": reason,
        "by_user_id": admin["user_id"],
        "by_role": admin["role"],
        "at": now_iso(),
    })
    if released:
        rel_recs = [r for r, new, _ in plan if new == "ACTIVE"]
        await _notify_employees(rel_recs, cid, "release",
                                reason or f"Reprocessed under policy v{ver}")
    return {"ok": True, "total": len(plan), "released": released,
            "held": held, "blocked": blocked, "unchanged": unchanged,
            "policy_version": ver}
