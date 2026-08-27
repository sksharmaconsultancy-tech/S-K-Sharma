"""Iter 746 — ORGANIZATION STRUCTURE (user PRD Phase 1).

Reusable org framework on top of the EXISTING masters (no duplicate data):
  * Department hierarchy — per-firm OVERLAY (collection ``dept_hierarchy``)
    on the existing ``masters`` (type=department) docs: parent, code, head,
    branch, cost centre, status, effective dates.
  * Reporting chain on ``users.reporting_chain`` — primary / secondary
    manager, dept head, HR manager, final approver (user_ids). Reused by OT
    approval today; Leave / Expense / F&F etc. later.
  * Company-level defaults (``org_defaults``) for HR manager / final
    approver.
  * ``resolve_approval_chain()`` — shared helper other modules import.
  * Org chart + org reports (hierarchy / reporting / manager-wise /
    dept-wise / branch-dept) as xlsx / pdf / json.
Audit: every change appended to ``hr_audit`` (module="org").
"""
from typing import List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import db, get_user_from_token, now_iso, sub_admin_can_touch_company  # noqa: E402
from routes.statutory_extra_reports import _emit, _company, _num  # noqa: E402

router = APIRouter(prefix="/api", tags=["org-structure"])

CHAIN_ROLES = ("primary_manager", "secondary_manager", "dept_head",
               "hr_manager", "final_approver")


async def _authz(authorization: Optional[str], company_id: Optional[str]) -> tuple:
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    if admin.get("role") == "company_admin":
        company_id = admin.get("company_id")
    if admin.get("role") == "sub_admin" and company_id:
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return admin, company_id


async def _audit(module: str, action: str, entity: str, prev, new, admin, reason=""):
    await db.hr_audit.insert_one({
        "module": module, "action": action, "entity_id": entity,
        "prev": prev, "new": new, "reason": reason,
        "by": admin.get("user_id"), "by_name": admin.get("name"),
        "at": now_iso()})


async def _dept_docs(company_id: str) -> List[dict]:
    """Existing department masters merged with the per-firm hierarchy overlay."""
    masters = [m async for m in db.masters.find(
        {"type": "department", "company_id": {"$in": [company_id, "__global__"]}},
        {"_id": 0})]
    overlay = {o["master_id"]: o async for o in db.dept_hierarchy.find(
        {"company_id": company_id}, {"_id": 0})}
    # employee counts by department name (source of truth = users)
    counts: dict = {}
    async for u in db.users.find(
            {"company_id": company_id, "role": "employee", "active": {"$ne": False}},
            {"_id": 0, "department": 1}):
        d = str(u.get("department") or "").strip().upper()
        counts[d] = counts.get(d, 0) + 1
    out = []
    for m in masters:
        o = overlay.get(m["master_id"], {})
        head = None
        if o.get("head_user_id"):
            hu = await db.users.find_one({"user_id": o["head_user_id"]},
                                         {"_id": 0, "name": 1, "employee_code": 1})
            head = ((hu or {}).get("name"))
        out.append({
            "master_id": m["master_id"], "name": m.get("name"),
            "global": m.get("company_id") == "__global__",
            "code": o.get("code") or "",
            "parent_id": o.get("parent_id"),
            "head_user_id": o.get("head_user_id"), "head_name": head,
            "branch_id": o.get("branch_id"), "branch_name": o.get("branch_name"),
            "cost_centre": o.get("cost_centre") or "",
            "status": o.get("status") or "active",
            "effective_from": o.get("effective_from"),
            "effective_to": o.get("effective_to"),
            "employee_count": counts.get(str(m.get("name") or "").strip().upper(), 0),
        })
    return out


@router.get("/org/departments")
async def list_departments(company_id: Optional[str] = Query(None),
                           authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    return {"departments": await _dept_docs(company_id)}


@router.post("/org/departments")
async def create_department(payload: dict = Body(...),
                            authorization: Optional[str] = Header(None)):
    admin, company_id = await _authz(authorization, payload.get("company_id"))
    name = str(payload.get("name") or "").strip().upper()
    if not name:
        raise HTTPException(status_code=400, detail="Department name required")
    if await db.masters.find_one({"type": "department", "name": name,
                                  "company_id": {"$in": [company_id, "__global__"]}}):
        raise HTTPException(status_code=409, detail="Department already exists")
    import uuid
    mid = f"mst_{uuid.uuid4().hex[:10]}"
    await db.masters.insert_one({
        "master_id": mid, "type": "department", "company_id": company_id,
        "name": name, "member_user_ids": [], "created_at": now_iso(),
        "created_by": admin.get("user_id")})
    await _audit("org", "dept_create", mid, None, {"name": name}, admin)
    return {"ok": True, "master_id": mid}


@router.patch("/org/departments/{master_id}")
async def update_department(master_id: str, payload: dict = Body(...),
                            authorization: Optional[str] = Header(None)):
    admin, company_id = await _authz(authorization, payload.get("company_id"))
    m = await db.masters.find_one(
        {"master_id": master_id, "type": "department",
         "company_id": {"$in": [company_id, "__global__"]}}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Department not found")
    # cycle guard — parent must not be self / a descendant
    parent_id = payload.get("parent_id") or None
    if parent_id:
        if parent_id == master_id:
            raise HTTPException(status_code=400, detail="Department cannot be its own parent")
        overlay = {o["master_id"]: o.get("parent_id") async for o in
                   db.dept_hierarchy.find({"company_id": company_id}, {"_id": 0})}
        cur, hops = parent_id, 0
        while cur and hops < 25:
            if cur == master_id:
                raise HTTPException(status_code=400, detail="Cycle in hierarchy not allowed")
            cur = overlay.get(cur)
            hops += 1
    branch_name = None
    if payload.get("branch_id"):
        b = await db.branches.find_one({"branch_id": payload["branch_id"]},
                                       {"_id": 0, "name": 1})
        branch_name = (b or {}).get("name")
    prev = await db.dept_hierarchy.find_one(
        {"company_id": company_id, "master_id": master_id}, {"_id": 0})
    doc = {
        "company_id": company_id, "master_id": master_id,
        "code": str(payload.get("code") or "").strip(),
        "parent_id": parent_id,
        "head_user_id": payload.get("head_user_id") or None,
        "branch_id": payload.get("branch_id") or None,
        "branch_name": branch_name,
        "cost_centre": str(payload.get("cost_centre") or "").strip(),
        "status": "inactive" if payload.get("status") == "inactive" else "active",
        "effective_from": payload.get("effective_from") or None,
        "effective_to": payload.get("effective_to") or None,
        "updated_at": now_iso(), "updated_by": admin.get("user_id"),
    }
    await db.dept_hierarchy.update_one(
        {"company_id": company_id, "master_id": master_id},
        {"$set": doc}, upsert=True)
    await _audit("org", "dept_update", master_id, prev, doc, admin)
    return {"ok": True}


@router.get("/org/chart")
async def org_chart(company_id: Optional[str] = Query(None),
                    authorization: Optional[str] = Header(None)):
    """Firm → Branch → Department tree with heads + employee counts."""
    _, company_id = await _authz(authorization, company_id)
    co = await db.companies.find_one({"company_id": company_id},
                                     {"_id": 0, "name": 1})
    branches = [b async for b in db.branches.find(
        {"company_id": company_id}, {"_id": 0, "branch_id": 1, "name": 1})]
    depts = await _dept_docs(company_id)
    by_parent: dict = {}
    for d in depts:
        by_parent.setdefault(d.get("parent_id"), []).append(d)

    def build(pid):
        return [{**d, "children": build(d["master_id"])}
                for d in sorted(by_parent.get(pid, []), key=lambda x: x["name"] or "")]

    total = sum(d["employee_count"] for d in depts)
    branch_counts: dict = {}
    async for u in db.users.find(
            {"company_id": company_id, "role": "employee", "active": {"$ne": False}},
            {"_id": 0, "branch_name": 1}):
        bn = str(u.get("branch_name") or "Unassigned").strip() or "Unassigned"
        branch_counts[bn] = branch_counts.get(bn, 0) + 1
    return {"firm": (co or {}).get("name"), "total_departments": len(depts),
            "total_employees_in_departments": total,
            "branches": [{**b, "employee_count":
                          branch_counts.get(str(b.get("name") or "").strip(), 0)}
                         for b in branches],
            "tree": build(None)}


@router.get("/org/departments/{master_id}/employees")
async def department_employees(master_id: str,
                               company_id: Optional[str] = Query(None),
                               authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    m = await db.masters.find_one({"master_id": master_id}, {"_id": 0, "name": 1})
    if not m:
        raise HTTPException(status_code=404, detail="Department not found")
    emps = [u async for u in db.users.find(
        {"company_id": company_id, "role": "employee", "active": {"$ne": False},
         "department": {"$regex": f"^{m['name']}$", "$options": "i"}},
        {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
         "designation": 1, "branch_name": 1, "reporting_chain": 1})]
    emps.sort(key=lambda x: str(x.get("employee_code") or ""))
    return {"department": m["name"], "employees": emps}


# ─────────────── Reporting chain ───────────────

@router.get("/org/reporting")
async def reporting_list(company_id: Optional[str] = Query(None),
                         q: Optional[str] = Query(None),
                         authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    flt = {"company_id": company_id, "role": "employee", "active": {"$ne": False}}
    if q:
        flt["$or"] = [{"name": {"$regex": q, "$options": "i"}},
                      {"employee_code": {"$regex": q, "$options": "i"}}]
    emps = [u async for u in db.users.find(
        flt, {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
              "department": 1, "designation": 1, "branch_name": 1,
              "reporting_chain": 1})]
    names = {}
    for e in emps:
        names[e["user_id"]] = e.get("name")
    # resolve chain names (may reference non-employee users too)
    need = set()
    for e in emps:
        for r in CHAIN_ROLES:
            uid = (e.get("reporting_chain") or {}).get(r)
            if uid and uid not in names:
                need.add(uid)
    if need:
        async for u in db.users.find({"user_id": {"$in": list(need)}},
                                     {"_id": 0, "user_id": 1, "name": 1}):
            names[u["user_id"]] = u.get("name")
    for e in emps:
        ch = e.get("reporting_chain") or {}
        e["chain_names"] = {r: names.get(ch.get(r)) for r in CHAIN_ROLES if ch.get(r)}
    emps.sort(key=lambda x: str(x.get("employee_code") or ""))
    return {"employees": emps}


@router.post("/org/reporting/{user_id}")
async def set_reporting(user_id: str, payload: dict = Body(...),
                        authorization: Optional[str] = Header(None)):
    admin, company_id = await _authz(authorization, payload.get("company_id"))
    u = await db.users.find_one({"user_id": user_id, "company_id": company_id},
                                {"_id": 0, "reporting_chain": 1, "name": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    chain = {}
    for r in CHAIN_ROLES:
        v = payload.get(r)
        if v:
            if v == user_id:
                raise HTTPException(status_code=400,
                                    detail=f"{r}: employee khud apna manager nahi ho sakta")
            chain[r] = v
    await db.users.update_one({"user_id": user_id},
                              {"$set": {"reporting_chain": chain}})
    await _audit("org", "reporting_set", user_id,
                 u.get("reporting_chain"), chain, admin)
    return {"ok": True, "reporting_chain": chain}


@router.post("/org/reporting-bulk")
async def set_reporting_bulk(payload: dict = Body(...),
                             authorization: Optional[str] = Header(None)):
    """Assign one chain role to many employees at once."""
    admin, company_id = await _authz(authorization, payload.get("company_id"))
    role = payload.get("chain_role")
    target = payload.get("target_user_id")
    ids = payload.get("user_ids") or []
    if role not in CHAIN_ROLES or not target or not ids:
        raise HTTPException(status_code=400, detail="chain_role, target_user_id, user_ids required")
    n = 0
    for uid in ids:
        if uid == target:
            continue
        r = await db.users.update_one(
            {"user_id": uid, "company_id": company_id},
            {"$set": {f"reporting_chain.{role}": target}})
        n += r.modified_count
    await _audit("org", "reporting_bulk", role, None,
                 {"target": target, "count": n}, admin)
    return {"ok": True, "updated": n}


@router.get("/org/defaults")
async def get_org_defaults(company_id: Optional[str] = Query(None),
                           authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    d = await db.org_defaults.find_one({"company_id": company_id}, {"_id": 0})
    return {"defaults": d or {}}


@router.post("/org/defaults")
async def set_org_defaults(payload: dict = Body(...),
                           authorization: Optional[str] = Header(None)):
    admin, company_id = await _authz(authorization, payload.get("company_id"))
    prev = await db.org_defaults.find_one({"company_id": company_id}, {"_id": 0})
    doc = {"company_id": company_id,
           "hr_manager": payload.get("hr_manager") or None,
           "final_approver": payload.get("final_approver") or None,
           "updated_at": now_iso(), "updated_by": admin.get("user_id")}
    await db.org_defaults.update_one({"company_id": company_id},
                                     {"$set": doc}, upsert=True)
    await _audit("org", "defaults_set", company_id, prev, doc, admin)
    return {"ok": True}


async def resolve_approval_chain(user: dict, approver_types: List[str]) -> List[dict]:
    """SHARED helper — derive the ordered approver list for an employee from
    the org structure. Used by OT approval now; Leave/Expense/F&F later.
    Falls back: dept head from Department Master overlay; HR/final approver
    from company org_defaults; unresolved levels are dropped."""
    chain = user.get("reporting_chain") or {}
    company_id = user.get("company_id")
    defaults = await db.org_defaults.find_one({"company_id": company_id}, {"_id": 0}) or {}
    out = []
    for t in approver_types:
        uid = chain.get(t)
        if not uid and t == "dept_head" and user.get("department"):
            m = await db.masters.find_one(
                {"type": "department",
                 "company_id": {"$in": [company_id, "__global__"]},
                 "name": {"$regex": f"^{str(user['department']).strip()}$",
                          "$options": "i"}}, {"_id": 0, "master_id": 1})
            if m:
                o = await db.dept_hierarchy.find_one(
                    {"company_id": company_id, "master_id": m["master_id"]},
                    {"_id": 0, "head_user_id": 1})
                uid = (o or {}).get("head_user_id")
        if not uid and t in ("hr_manager", "final_approver"):
            uid = defaults.get(t)
        if uid and uid != user.get("user_id"):
            au = await db.users.find_one({"user_id": uid}, {"_id": 0, "name": 1})
            out.append({"approver_type": t, "user_id": uid,
                        "name": (au or {}).get("name")})
    return out


# ─────────────── Org reports ───────────────

@router.get("/org/report")
async def org_report(kind: str = Query("hierarchy"),
                     fmt: str = Query("json"),
                     company_id: Optional[str] = Query(None),
                     authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    company = await _company(company_id)
    if kind == "hierarchy":
        depts = await _dept_docs(company_id)
        by_id = {d["master_id"]: d for d in depts}

        def path(d, hops=0):
            p = by_id.get(d.get("parent_id"))
            return (path(p, hops + 1) + " → " if p and hops < 10 else "") + (d["name"] or "")
        rows = [{"path": path(d), "code": d["code"], "head": d.get("head_name") or "",
                 "branch": d.get("branch_name") or "", "cost_centre": d["cost_centre"],
                 "status": d["status"], "employees": d["employee_count"]}
                for d in sorted(depts, key=lambda x: path(x))]
        cols = [("Department Path", "path", False), ("Code", "code", False),
                ("Head", "head", False), ("Branch", "branch", False),
                ("Cost Centre", "cost_centre", False), ("Status", "status", False),
                ("Employees", "employees", True)]
        return _emit(fmt, title="Department Hierarchy", subtitle="Org Structure",
                     company=company, cols=cols, rows=rows,
                     fname_base=f"dept_hierarchy_{company_id}")
    if kind in ("reporting", "manager_wise", "dept_wise", "branch_dept"):
        emps = [u async for u in db.users.find(
            {"company_id": company_id, "role": "employee", "active": {"$ne": False}},
            {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1, "department": 1,
             "designation": 1, "branch_name": 1, "reporting_chain": 1})]
        names = {e["user_id"]: e.get("name") for e in emps}
        need = {uid for e in emps for uid in (e.get("reporting_chain") or {}).values()
                if uid and uid not in names}
        if need:
            async for u in db.users.find({"user_id": {"$in": list(need)}},
                                         {"_id": 0, "user_id": 1, "name": 1}):
                names[u["user_id"]] = u.get("name")
        rows = []
        for e in sorted(emps, key=lambda x: str(x.get("employee_code") or "")):
            ch = e.get("reporting_chain") or {}
            rows.append({
                "employee_code": e.get("employee_code"), "name": e.get("name"),
                "department": e.get("department") or "", "designation": e.get("designation") or "",
                "branch": e.get("branch_name") or "",
                "primary_manager": names.get(ch.get("primary_manager")) or "",
                "dept_head": names.get(ch.get("dept_head")) or "",
                "hr_manager": names.get(ch.get("hr_manager")) or "",
                "final_approver": names.get(ch.get("final_approver")) or ""})
        if kind == "manager_wise":
            rows.sort(key=lambda r: (r["primary_manager"] or "zzz", str(r["employee_code"])))
        elif kind == "dept_wise":
            rows.sort(key=lambda r: (r["department"] or "zzz", str(r["employee_code"])))
        elif kind == "branch_dept":
            rows.sort(key=lambda r: (r["branch"] or "zzz", r["department"] or "zzz"))
        cols = [("Emp Code", "employee_code", False), ("Name", "name", False),
                ("Branch", "branch", False), ("Department", "department", False),
                ("Designation", "designation", False),
                ("Reporting Manager", "primary_manager", False),
                ("Dept Head", "dept_head", False), ("HR Manager", "hr_manager", False),
                ("Final Approver", "final_approver", False)]
        titles = {"reporting": "Employee Reporting Structure",
                  "manager_wise": "Manager-wise Employee List",
                  "dept_wise": "Department-wise Employee List",
                  "branch_dept": "Branch-wise Department Report"}
        return _emit(fmt, title=titles[kind], subtitle="Org Structure",
                     company=company, cols=cols, rows=rows,
                     fname_base=f"org_{kind}_{company_id}")
    raise HTTPException(status_code=400, detail="Unknown report kind")


@router.get("/org/audit")
async def org_audit_log(company_id: Optional[str] = Query(None),
                        module: str = Query("org"),
                        limit: int = Query(100),
                        authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    rows = [a async for a in db.hr_audit.find(
        {"module": module}, {"_id": 0}).sort("at", -1).limit(min(limit, 500))]
    return {"audit": rows}
