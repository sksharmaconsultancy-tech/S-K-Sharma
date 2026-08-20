"""Iter 624 — MULTI-BRANCH ARCHITECTURE (user spec, 20 sections).

Branch Master extensions (code/address/head/contact/active + link existing),
Employee Home & Authorized branches, Temporary Branch Assignments,
Permanent Branch Transfers (effective-dated, history preserved),
Branch Cost Allocation (single payroll record — allocation is REPORTING
ONLY, never duplicates PF/ESIC) and the Branch Dashboard.

Core rule: Home Branch = permanent assignment; Worked Branch = where the
employee actually punched that day. Salary is computed ONCE per employee by
the existing engines; branch-wise cost = consolidated salary ÷ payable days
× days worked at each branch.
"""

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
)

router = APIRouter(prefix="/api/admin/branch-management", tags=["branch-management"])

_ADMIN_ROLES = ["super_admin", "sub_admin", "company_admin"]


async def _gate(authorization: Optional[str], company_id: Optional[str]) -> tuple[dict, str]:
    """Auth + firm scoping. Returns (admin, effective company_id)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    cid = admin.get("company_id") if admin["role"] == "company_admin" else company_id
    if not cid:
        raise HTTPException(status_code=400, detail="company_id required")
    return admin, cid


def _branch_scope(admin: dict) -> Optional[List[str]]:
    """Branch RBAC: a sub-admin may be restricted to specific branches."""
    ids = admin.get("branch_admin_branch_ids") or []
    return [str(i) for i in ids] if ids else None


async def _firm_branches(cid: str) -> List[dict]:
    """Branches owned by the firm PLUS branches linked to it."""
    return await db.branches.find(
        {"$or": [{"company_id": cid}, {"linked_company_ids": cid}]},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)


# ---------------------------------------------------------------- branches
@router.get("/branches")
async def bm_branches(company_id: Optional[str] = Query(None),
                      authorization: Optional[str] = Header(None)):
    admin, cid = await _gate(authorization, company_id)
    branches = await _firm_branches(cid)
    scope = _branch_scope(admin)
    if scope:
        branches = [b for b in branches if b["branch_id"] in scope]
    return {"branches": branches}


@router.patch("/branches/{branch_id}")
async def bm_update_branch(branch_id: str, body: Dict[str, Any] = Body(...),
                           authorization: Optional[str] = Header(None)):
    """Extended branch fields + unique Branch Code per firm."""
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    b = await db.branches.find_one({"branch_id": branch_id}, {"_id": 0})
    if not b:
        raise HTTPException(status_code=404, detail="Branch not found")
    if admin["role"] == "company_admin" and b.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your branch")
    allowed = ("name", "code", "address", "state", "city", "pin", "head_name",
               "email", "mobile", "office_lat", "office_lng",
               "geofence_radius_m", "active")
    patch = {k: body[k] for k in allowed if k in body}
    code = str(patch.get("code") or "").strip().upper()
    if code:
        patch["code"] = code
        dup = await db.branches.find_one({
            "branch_id": {"$ne": branch_id}, "code": code,
            "$or": [{"company_id": b["company_id"]},
                    {"linked_company_ids": b["company_id"]}],
        }, {"_id": 0, "branch_id": 1})
        if dup:
            raise HTTPException(status_code=409,
                                detail=f"Branch code '{code}' already exists in this firm")
    if not patch:
        return {"ok": True, "branch": b}
    patch["updated_at"] = now_iso()
    await db.branches.update_one({"branch_id": branch_id}, {"$set": patch})
    fresh = await db.branches.find_one({"branch_id": branch_id}, {"_id": 0})
    return {"ok": True, "branch": fresh}


@router.post("/branches/link")
async def bm_link_branch(body: Dict[str, Any] = Body(...),
                         authorization: Optional[str] = Header(None)):
    """Link an EXISTING branch (owned by another firm) to this firm."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])  # cross-firm → elevated
    branch_id = str(body.get("branch_id") or "")
    cid = str(body.get("company_id") or "")
    b = await db.branches.find_one({"branch_id": branch_id}, {"_id": 0})
    if not b or not cid:
        raise HTTPException(status_code=404, detail="Branch/company not found")
    if b.get("company_id") == cid:
        raise HTTPException(status_code=409, detail="Branch already belongs to this firm")
    await db.branches.update_one({"branch_id": branch_id},
                                 {"$addToSet": {"linked_company_ids": cid},
                                  "$set": {"updated_at": now_iso()}})
    return {"ok": True}


@router.post("/branches/unlink")
async def bm_unlink_branch(body: Dict[str, Any] = Body(...),
                           authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    await db.branches.update_one(
        {"branch_id": str(body.get("branch_id") or "")},
        {"$pull": {"linked_company_ids": str(body.get("company_id") or "")}})
    return {"ok": True}


# ------------------------------------------------- employee branch assignment
@router.get("/employees")
async def bm_employees(company_id: Optional[str] = Query(None),
                       branch_id: Optional[str] = Query(None),
                       authorization: Optional[str] = Header(None)):
    admin, cid = await _gate(authorization, company_id)
    q: dict = {"company_id": cid, "role": "employee"}
    if branch_id:
        q["home_branch_id"] = branch_id
    emps = await db.users.find(q, {
        "_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
        "employee_type": 1, "home_branch_id": 1, "authorized_branch_ids": 1,
        "status": 1,
    }).sort("name", 1).to_list(3000)
    return {"employees": emps}


@router.post("/assign")
async def bm_assign(body: Dict[str, Any] = Body(...),
                    authorization: Optional[str] = Header(None)):
    """Set an employee's Home Branch + Authorized Branches (audited)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    uid = str(body.get("user_id") or "")
    emp = await db.users.find_one({"user_id": uid}, {"_id": 0, "user_id": 1,
                                                     "company_id": 1,
                                                     "home_branch_id": 1,
                                                     "authorized_branch_ids": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your employee")
    home = body.get("home_branch_id") or None
    auth = [str(a) for a in (body.get("authorized_branch_ids") or []) if a]
    if home and home not in auth:
        auth.append(home)
    await db.users.update_one({"user_id": uid}, {"$set": {
        "home_branch_id": home, "authorized_branch_ids": auth,
        "branch_assigned_at": now_iso(), "branch_assigned_by": admin["user_id"],
    }})
    await db.branch_audit.insert_one({
        "audit_id": f"bra_{uuid.uuid4().hex[:10]}", "action": "assign",
        "user_id": uid, "by": admin["user_id"], "at": now_iso(),
        "prev": {"home": emp.get("home_branch_id"),
                 "authorized": emp.get("authorized_branch_ids")},
        "new": {"home": home, "authorized": auth},
    })
    return {"ok": True}


# --------------------------------------------------- temporary assignments
@router.get("/temp-assignments")
async def bm_temp_list(company_id: Optional[str] = Query(None),
                       authorization: Optional[str] = Header(None)):
    admin, cid = await _gate(authorization, company_id)
    rows = await db.branch_temp_assignments.find(
        {"company_id": cid}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"assignments": rows}


@router.post("/temp-assignments")
async def bm_temp_create(body: Dict[str, Any] = Body(...),
                         authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    uid = str(body.get("user_id") or "")
    emp = await db.users.find_one({"user_id": uid}, {"_id": 0, "company_id": 1, "name": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your employee")
    frm, to = str(body.get("from_date") or ""), str(body.get("to_date") or "")
    if not (frm and to and frm <= to):
        raise HTTPException(status_code=400, detail="Valid from/to dates required")
    doc = {
        "assign_id": f"bta_{uuid.uuid4().hex[:10]}",
        "company_id": emp["company_id"], "user_id": uid,
        "employee_name": emp.get("name"),
        "branch_id": str(body.get("branch_id") or ""),
        "from_date": frm, "to_date": to,
        "reason": str(body.get("reason") or "").strip() or None,
        "approved_by": admin["user_id"], "status": "approved",
        "created_at": now_iso(),
    }
    if not doc["branch_id"]:
        raise HTTPException(status_code=400, detail="branch_id required")
    await db.branch_temp_assignments.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "assignment": doc}


@router.patch("/temp-assignments/{assign_id}/cancel")
async def bm_temp_cancel(assign_id: str,
                         authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    # History is never deleted — only marked cancelled.
    await db.branch_temp_assignments.update_one(
        {"assign_id": assign_id},
        {"$set": {"status": "cancelled", "cancelled_by": admin["user_id"],
                  "cancelled_at": now_iso()}})
    return {"ok": True}


# ------------------------------------------------------ permanent transfers
@router.get("/transfers")
async def bm_transfers(company_id: Optional[str] = Query(None),
                       authorization: Optional[str] = Header(None)):
    admin, cid = await _gate(authorization, company_id)
    await _apply_due_transfers(cid)
    rows = await db.branch_transfers.find(
        {"company_id": cid}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"transfers": rows}


async def _apply_due_transfers(cid: str) -> None:
    """Lazy applier: pending transfers whose effective date has arrived
    update the employee's CURRENT home branch. Historical attendance keeps
    its stored home_branch snapshot — never rewritten."""
    from datetime import datetime, timedelta, timezone
    today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    async for t in db.branch_transfers.find(
            {"company_id": cid, "status": "pending", "effective_date": {"$lte": today}}):
        auth = ((await db.users.find_one({"user_id": t["user_id"]},
                                         {"_id": 0, "authorized_branch_ids": 1})
                 ) or {}).get("authorized_branch_ids") or []
        if t["new_branch_id"] not in auth:
            auth.append(t["new_branch_id"])
        await db.users.update_one({"user_id": t["user_id"]}, {"$set": {
            "home_branch_id": t["new_branch_id"], "authorized_branch_ids": auth}})
        await db.branch_transfers.update_one(
            {"transfer_id": t["transfer_id"]},
            {"$set": {"status": "applied", "applied_at": now_iso()}})


@router.post("/transfers")
async def bm_transfer_create(body: Dict[str, Any] = Body(...),
                             authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ADMIN_ROLES)
    uid = str(body.get("user_id") or "")
    emp = await db.users.find_one({"user_id": uid}, {"_id": 0, "company_id": 1,
                                                     "name": 1, "home_branch_id": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your employee")
    eff = str(body.get("effective_date") or "")
    new_b = str(body.get("new_branch_id") or "")
    if not (eff and new_b):
        raise HTTPException(status_code=400, detail="effective_date and new_branch_id required")
    doc = {
        "transfer_id": f"btr_{uuid.uuid4().hex[:10]}",
        "company_id": emp["company_id"], "user_id": uid,
        "employee_name": emp.get("name"),
        "prev_branch_id": emp.get("home_branch_id"),
        "new_branch_id": new_b, "effective_date": eff,
        "reason": str(body.get("reason") or "").strip() or None,
        "approved_by": admin["user_id"], "status": "pending",
        "created_at": now_iso(),
    }
    await db.branch_transfers.insert_one(doc)
    await _apply_due_transfers(emp["company_id"])
    doc.pop("_id", None)
    return {"ok": True, "transfer": doc}


# ------------------------------------------------------ allocation engine
async def _month_worked_days(cid: str, month: str) -> Dict[str, Dict[str, float]]:
    """{user_id: {branch_id_or_'': distinct-days}} from punches in month.
    A day's worked branch = branch of the day's first punch that has one."""
    per_day: Dict[tuple, str] = {}
    async for a in db.attendance.find(
            {"company_id": cid, "date": {"$regex": f"^{month}"}},
            {"_id": 0, "user_id": 1, "date": 1, "branch_id": 1, "at": 1}).sort("at", 1):
        k = (a["user_id"], a["date"])
        if k not in per_day or (not per_day[k] and a.get("branch_id")):
            per_day[k] = a.get("branch_id") or ""
    out: Dict[str, Dict[str, float]] = {}
    for (uid, _d), bid in per_day.items():
        out.setdefault(uid, {})
        out[uid][bid] = out[uid].get(bid, 0) + 1
    return out


async def _allocation(cid: str, month: str) -> dict:
    """Consolidated-salary → branch cost allocation (reporting only)."""
    runs = await db.compliance_salary_runs.find(
        {"month": month,
         "$or": [{"company_id": cid}, {"rows.company_id": cid}]},
        {"_id": 0, "run_id": 1, "rows": 1, "created_at": 1, "month_days": 1},
    ).sort("created_at", 1).to_list(50)
    rows_by_uid: Dict[str, dict] = {}
    for r in runs:  # later runs win (dedupe → ONE payroll record per employee)
        for row in (r.get("rows") or []):
            if row.get("company_id") in (None, cid):
                rows_by_uid[row["user_id"]] = row
    worked = await _month_worked_days(cid, month)
    branches = {b["branch_id"]: b for b in await _firm_branches(cid)}
    users = {u["user_id"]: u async for u in db.users.find(
        {"company_id": cid, "role": "employee"},
        {"_id": 0, "user_id": 1, "name": 1, "home_branch_id": 1,
         "authorized_branch_ids": 1, "doj": 1, "date_of_joining": 1,
         "dol": 1, "date_of_leaving": 1})}

    def bname(bid: Optional[str]) -> str:
        if not bid:
            return "Main Office / Unassigned"
        return (branches.get(bid) or {}).get("name") or bid

    emp_rows: List[dict] = []
    totals: Dict[str, dict] = {}
    for uid, row in rows_by_uid.items():
        u = users.get(uid) or {}
        pd = float(row.get("present_days") or 0)
        gross = float(row.get("gross_paid") or 0)
        net = float(row.get("net_payable") or row.get("net_pay") or 0)
        pf_er = float(row.get("pf_employer_total") or 0)
        esic_er = float(row.get("esic_employer") or 0)
        home = u.get("home_branch_id")
        wd = dict(worked.get(uid) or {})
        # normalise punch-days to payable days; days not captured by punches
        # (manual grid entries) fall back to the HOME branch.
        wd_total = sum(wd.values())
        if pd <= 0:
            continue
        alloc_days: Dict[Optional[str], float] = {}
        if wd_total <= 0:
            alloc_days[home] = pd
        else:
            scale = min(1.0, pd / wd_total)
            used = 0.0
            for bid, d in wd.items():
                dd = round(d * scale, 2)
                alloc_days[bid or home] = alloc_days.get(bid or home, 0) + dd
                used += dd
            if pd - used > 0.01:  # remainder → home branch
                alloc_days[home] = alloc_days.get(home, 0) + round(pd - used, 2)
        parts = []
        for bid, days in alloc_days.items():
            share = days / pd
            part = {
                "branch_id": bid, "branch": bname(bid), "days": round(days, 2),
                "gross": round(gross * share, 2), "net": round(net * share, 2),
                "pf_employer": round(pf_er * share, 2),
                "esic_employer": round(esic_er * share, 2),
                "guest": bool(bid and home and bid != home),
            }
            parts.append(part)
            t = totals.setdefault(bid or "", {
                "branch_id": bid, "branch": bname(bid), "employees": set(),
                "days": 0.0, "gross": 0.0, "net": 0.0,
                "pf_employer": 0.0, "esic_employer": 0.0, "guest_days": 0.0})
            t["employees"].add(uid)
            t["days"] += part["days"]
            t["gross"] += part["gross"]
            t["net"] += part["net"]
            t["pf_employer"] += part["pf_employer"]
            t["esic_employer"] += part["esic_employer"]
            if part["guest"]:
                t["guest_days"] += part["days"]
        emp_rows.append({
            "user_id": uid, "name": row.get("name") or u.get("name"),
            "home_branch_id": home, "home_branch": bname(home),
            "present_days": pd, "gross": round(gross, 2), "net": round(net, 2),
            "cross_branch": len([p for p in parts if p["guest"]]) > 0,
            "allocation": parts,
        })
    branch_totals = []
    for t in totals.values():
        t["employees"] = len(t["employees"])
        for k in ("days", "gross", "net", "pf_employer", "esic_employer", "guest_days"):
            t[k] = round(t[k], 2)
        branch_totals.append(t)
    branch_totals.sort(key=lambda x: -x["gross"])
    return {"month": month, "employees": emp_rows, "branches": branch_totals}


@router.get("/allocation")
async def bm_allocation(company_id: Optional[str] = Query(None),
                        month: str = Query(...),
                        branch_id: Optional[str] = Query(None),
                        authorization: Optional[str] = Header(None)):
    admin, cid = await _gate(authorization, company_id)
    data = await _allocation(cid, month)
    scope = _branch_scope(admin)
    if branch_id or scope:
        keep = set([branch_id] if branch_id else scope or [])
        data["branches"] = [b for b in data["branches"] if b.get("branch_id") in keep]
        data["employees"] = [
            e for e in data["employees"]
            if any(p.get("branch_id") in keep for p in e["allocation"])]
    return data


@router.get("/dashboard")
async def bm_dashboard(company_id: Optional[str] = Query(None),
                       month: str = Query(...),
                       authorization: Optional[str] = Header(None)):
    admin, cid = await _gate(authorization, company_id)
    alloc = await _allocation(cid, month)
    branches = await _firm_branches(cid)
    scope = _branch_scope(admin)
    if scope:
        branches = [b for b in branches if b["branch_id"] in scope]
    from datetime import datetime, timedelta, timezone
    today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    # present today per branch (distinct employees with an IN punch)
    present_today: Dict[str, set] = {}
    async for a in db.attendance.find({"company_id": cid, "date": today, "kind": "in"},
                                      {"_id": 0, "user_id": 1, "branch_id": 1}):
        present_today.setdefault(a.get("branch_id") or "", set()).add(a["user_id"])
    # home-branch headcount + joiners/exits in month
    home_counts: Dict[str, int] = {}
    joiners: Dict[str, int] = {}
    exits: Dict[str, int] = {}
    async for u in db.users.find({"company_id": cid, "role": "employee"},
                                 {"_id": 0, "home_branch_id": 1, "doj": 1,
                                  "date_of_joining": 1, "dol": 1,
                                  "date_of_leaving": 1, "status": 1}):
        hb = u.get("home_branch_id") or ""
        if u.get("status") != "inactive":
            home_counts[hb] = home_counts.get(hb, 0) + 1
        doj = str(u.get("doj") or u.get("date_of_joining") or "")
        dol = str(u.get("dol") or u.get("date_of_leaving") or "")
        if doj.startswith(month):
            joiners[hb] = joiners.get(hb, 0) + 1
        if dol.startswith(month):
            exits[hb] = exits.get(hb, 0) + 1
    guests = await db.branch_temp_assignments.count_documents({
        "company_id": cid, "status": "approved",
        "from_date": {"$lte": f"{month}-31"}, "to_date": {"$gte": f"{month}-01"}})
    alloc_by_bid = {b.get("branch_id") or "": b for b in alloc["branches"]}
    cards = []
    ids = [None] + [b["branch_id"] for b in branches]
    for bid in ids:
        key = bid or ""
        a = alloc_by_bid.get(key) or {}
        b = next((x for x in branches if x["branch_id"] == bid), None)
        cards.append({
            "branch_id": bid,
            "branch": (b or {}).get("name") or "Main Office / Unassigned",
            "code": (b or {}).get("code"),
            "active": (b or {}).get("active", True) if b else True,
            "home_employees": home_counts.get(key, 0),
            "present_today": len(present_today.get(key, set())),
            "worked_days": a.get("days", 0),
            "guest_days": a.get("guest_days", 0),
            "gross_cost": a.get("gross", 0),
            "net_cost": a.get("net", 0),
            "pf_liability": a.get("pf_employer", 0),
            "esic_liability": a.get("esic_employer", 0),
            "joiners": joiners.get(key, 0),
            "exits": exits.get(key, 0),
        })
    cross = len([e for e in alloc["employees"] if e.get("cross_branch")])
    return {"month": month, "cards": cards,
            "cross_branch_employees": cross, "guest_assignments": guests}
