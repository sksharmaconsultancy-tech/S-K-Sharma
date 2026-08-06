"""SaaS Portal Dashboard — Phase 2.

Adds: Task Management, Client Health Scores, Document Expiry tracking,
enhanced Compliance Calendar (with completion tracking) and a portal
Notification/Alert center. Role-aware: super_admin = all firms,
company_admin = own firm only.
"""
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from server import db, get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api/admin", tags=["portal-phase2"])

IST = timezone(timedelta(hours=5, minutes=30))

TASK_STATUSES = ["open", "in_progress", "submitted", "done", "approved"]
TASK_PRIORITIES = ["low", "medium", "high"]
DOC_TYPES = ["license", "registration", "insurance", "contract", "certificate", "other"]


def _now() -> datetime:
    return datetime.now(IST)


async def _admin(authorization: Optional[str]):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    return admin


async def _super_only(authorization: Optional[str]):
    """Iter 501 (user request) — task CREATION (incl. recurring) is a
    Super Admin-only feature, on web and PWA alike. Strict: sub_admins
    are rejected too."""
    from server import require_super_admin_strict
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    return admin


def _scope(admin: dict, company_id: Optional[str]) -> Optional[str]:
    """company_admin is always locked to their own firm."""
    if admin.get("role") == "company_admin":
        return admin.get("company_id")
    return company_id or None


# ------- Iter 502 — company-wise task-assignment hierarchy helpers -------

def _sub_scope_ids(admin: dict) -> Optional[List[str]]:
    """Sub-admin's assigned company ids; None = all firms."""
    if admin.get("role") != "sub_admin":
        return None
    if (admin.get("sub_admin_company_scope") or "all") == "all":
        return None
    return list(admin.get("sub_admin_company_ids") or [])


async def _task_audit(actor: dict, action: str, task: dict,
                      details: str = "") -> None:
    """Every assignment / reassignment / status / approval action lands in
    the audit log with timestamp + user."""
    await db.task_audit_log.insert_one({
        "audit_id": f"taud_{uuid.uuid4().hex[:12]}",
        "at": _now().isoformat(),
        "action": action,
        "task_id": task.get("task_id"),
        "task_title": task.get("title"),
        "actor_id": actor.get("user_id"),
        "actor_name": actor.get("name") or actor.get("email"),
        "actor_role": actor.get("role"),
        "details": details,
    })


def _is_task_owner(admin: dict, t: dict) -> bool:
    """Sub-admin may act on tasks assigned TO them or created BY them."""
    return t.get("assignee_id") == admin["user_id"] \
        or t.get("created_by") == admin["user_id"]


# ============================= TASKS ================================

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    company_id: Optional[str] = None
    company_ids: Optional[List[str]] = None   # Iter 502 — multi-company
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None        # YYYY-MM-DD
    priority: str = "medium"


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    company_id: Optional[str] = None
    assignee_id: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None


async def _task_out(t: dict) -> dict:
    t.pop("_id", None)
    return t


# ======================= RECURRING TASKS ============================

STATUTORY_PRESETS = [
    {"seed_key": "pf_ecr", "title": "File PF ECR + payment", "day_of_month": 15, "priority": "high"},
    {"seed_key": "esic", "title": "ESIC contribution payment", "day_of_month": 15, "priority": "high"},
    {"seed_key": "tds", "title": "TDS deposit", "day_of_month": 7, "priority": "medium"},
    {"seed_key": "pt", "title": "Professional Tax deposit", "day_of_month": 21, "priority": "medium"},
]


def _month_days(month: str) -> int:
    y, m = int(month[:4]), int(month[5:7])
    if m == 12:
        nxt = datetime(y + 1, 1, 1)
    else:
        nxt = datetime(y, m + 1, 1)
    return (nxt - datetime(y, m, 1)).days


async def _generate_recurring(admin: dict) -> None:
    """Idempotently create this month's tasks from active recurring
    templates visible to this admin. Called lazily on task listing."""
    month = _now().strftime("%Y-%m")
    rq: Dict[str, Any] = {"active": True,
                          "last_generated_month": {"$ne": month}}
    if admin.get("role") == "company_admin":
        rq["company_id"] = admin.get("company_id")
        rq["all_firms"] = {"$ne": True}
    templates = await db.recurring_tasks.find(rq).to_list(200)
    if not templates:
        return
    firms = await db.companies.find(
        {}, {"_id": 0, "company_id": 1, "name": 1}).to_list(300)
    firm_names = {f["company_id"]: f.get("name") for f in firms}
    max_day = _month_days(month)
    for tpl in templates:
        day = min(max(1, int(tpl.get("day_of_month") or 1)), max_day)
        due = f"{month}-{day:02d}"
        if tpl.get("all_firms"):
            targets = [(f["company_id"], firm_names[f["company_id"]]) for f in firms]
        else:
            cid = tpl.get("company_id")
            targets = [(cid, firm_names.get(cid))]
        for cid, cname in targets:
            exists = await db.portal_tasks.find_one(
                {"source_rtask_id": tpl["rtask_id"], "month": month,
                 "company_id": cid})
            if exists:
                continue
            await db.portal_tasks.insert_one({
                "task_id": f"task_{uuid.uuid4().hex[:12]}",
                "title": tpl["title"],
                "description": tpl.get("description"),
                "company_id": cid,
                "company_name": cname,
                "assignee_id": None, "assignee_name": None,
                "due_date": due,
                "priority": tpl.get("priority", "medium"),
                "status": "open",
                "source_rtask_id": tpl["rtask_id"],
                "month": month,
                "created_by": "system:recurring",
                "created_by_name": "Recurring schedule",
                "created_at": _now().isoformat(),
                "updated_at": _now().isoformat(),
            })
        await db.recurring_tasks.update_one(
            {"rtask_id": tpl["rtask_id"]},
            {"$set": {"last_generated_month": month}})


class RecurringCreate(BaseModel):
    title: str
    description: Optional[str] = None
    company_id: Optional[str] = None
    all_firms: bool = False
    day_of_month: int = 15
    priority: str = "medium"


class RecurringUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    day_of_month: Optional[int] = None
    priority: Optional[str] = None
    active: Optional[bool] = None


@router.get("/portal-recurring-tasks")
async def list_recurring_tasks(authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    q: Dict[str, Any] = {}
    if admin.get("role") == "company_admin":
        q = {"company_id": admin.get("company_id"), "all_firms": {"$ne": True}}
    items = await db.recurring_tasks.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"recurring_tasks": items}


@router.post("/portal-recurring-tasks")
async def create_recurring_task(payload: RecurringCreate,
                                authorization: Optional[str] = Header(None)):
    admin = await _super_only(authorization)
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    if payload.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority")
    if not 1 <= int(payload.day_of_month) <= 31:
        raise HTTPException(status_code=400, detail="day_of_month must be 1-31")
    all_firms = bool(payload.all_firms) and admin.get("role") != "company_admin"
    cid = None if all_firms else _scope(admin, payload.company_id)
    if not all_firms and not cid:
        raise HTTPException(status_code=400,
                            detail="Pick a firm or enable all_firms")
    company_name = None
    if cid:
        c = await db.companies.find_one({"company_id": cid}, {"_id": 0, "name": 1})
        company_name = (c or {}).get("name")
    tpl = {
        "rtask_id": f"rtask_{uuid.uuid4().hex[:12]}",
        "title": title,
        "description": (payload.description or "").strip() or None,
        "company_id": cid,
        "company_name": company_name,
        "all_firms": all_firms,
        "day_of_month": int(payload.day_of_month),
        "priority": payload.priority,
        "active": True,
        "last_generated_month": None,
        "created_by": admin["user_id"],
        "created_at": _now().isoformat(),
    }
    await db.recurring_tasks.insert_one(dict(tpl))
    await _generate_recurring(admin)
    return {"ok": True, "recurring_task": tpl}


@router.post("/portal-recurring-tasks/seed-statutory")
async def seed_statutory_recurring(authorization: Optional[str] = Header(None)):
    """One-click: add the 4 standard statutory recurring to-dos.
    Super admin → all firms; company admin → own firm. Idempotent."""
    admin = await _super_only(authorization)
    is_ca = admin.get("role") == "company_admin"
    cid = admin.get("company_id") if is_ca else None
    company_name = None
    if cid:
        c = await db.companies.find_one({"company_id": cid}, {"_id": 0, "name": 1})
        company_name = (c or {}).get("name")
    created = 0
    for p in STATUTORY_PRESETS:
        scope_q = {"seed_key": p["seed_key"],
                   "company_id": cid} if is_ca else {"seed_key": p["seed_key"], "all_firms": True}
        if await db.recurring_tasks.find_one(scope_q):
            continue
        await db.recurring_tasks.insert_one({
            "rtask_id": f"rtask_{uuid.uuid4().hex[:12]}",
            "seed_key": p["seed_key"],
            "title": p["title"],
            "description": "Statutory monthly compliance (auto-created)",
            "company_id": cid,
            "company_name": company_name,
            "all_firms": not is_ca,
            "day_of_month": p["day_of_month"],
            "priority": p["priority"],
            "active": True,
            "last_generated_month": None,
            "created_by": admin["user_id"],
            "created_at": _now().isoformat(),
        })
        created += 1
    await _generate_recurring(admin)
    return {"ok": True, "created": created}


@router.patch("/portal-recurring-tasks/{rtask_id}")
async def update_recurring_task(rtask_id: str, payload: RecurringUpdate,
                                authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    tpl = await db.recurring_tasks.find_one({"rtask_id": rtask_id})
    if not tpl:
        raise HTTPException(status_code=404, detail="Recurring task not found")
    if admin.get("role") == "company_admin" and (
            tpl.get("all_firms") or tpl.get("company_id") != admin.get("company_id")):
        raise HTTPException(status_code=403, detail="Not your firm's recurring task")
    upd: Dict[str, Any] = {}
    if payload.title is not None:
        upd["title"] = payload.title.strip() or tpl["title"]
    if payload.description is not None:
        upd["description"] = payload.description.strip() or None
    if payload.day_of_month is not None:
        if not 1 <= int(payload.day_of_month) <= 31:
            raise HTTPException(status_code=400, detail="day_of_month must be 1-31")
        upd["day_of_month"] = int(payload.day_of_month)
    if payload.priority is not None:
        if payload.priority not in TASK_PRIORITIES:
            raise HTTPException(status_code=400, detail="Invalid priority")
        upd["priority"] = payload.priority
    if payload.active is not None:
        upd["active"] = bool(payload.active)
        if payload.active:
            # allow regeneration for the current month when re-activated
            upd["last_generated_month"] = None
    await db.recurring_tasks.update_one({"rtask_id": rtask_id}, {"$set": upd})
    t2 = await db.recurring_tasks.find_one({"rtask_id": rtask_id}, {"_id": 0})
    return {"ok": True, "recurring_task": t2}


@router.delete("/portal-recurring-tasks/{rtask_id}")
async def delete_recurring_task(rtask_id: str,
                                authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    tpl = await db.recurring_tasks.find_one({"rtask_id": rtask_id})
    if not tpl:
        raise HTTPException(status_code=404, detail="Recurring task not found")
    if admin.get("role") == "company_admin" and (
            tpl.get("all_firms") or tpl.get("company_id") != admin.get("company_id")):
        raise HTTPException(status_code=403, detail="Not your firm's recurring task")
    await db.recurring_tasks.delete_one({"rtask_id": rtask_id})
    return {"ok": True}


@router.get("/portal-tasks")
async def list_tasks(
    status: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    assignee_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await _admin(authorization)
    await _generate_recurring(admin)
    cid = _scope(admin, company_id)
    q: Dict[str, Any] = {}
    if cid:
        q["$or"] = [{"company_id": cid}, {"company_ids": cid}]
    if status and status != "all":
        q["status"] = status
    if assignee_id and admin.get("role") == "super_admin":
        q["assignee_id"] = assignee_id
    # Iter 502 — a sub_admin sees ONLY: tasks assigned to them, tasks they
    # created (internal / delegated), and unassigned tasks of their firms.
    role_or: Optional[List[Dict[str, Any]]] = None
    if admin.get("role") == "sub_admin":
        role_or = [{"assignee_id": admin["user_id"]},
                   {"created_by": admin["user_id"]}]
        scope = _sub_scope_ids(admin)
        if scope is None:
            role_or.append({"assignee_id": None})
        else:
            role_or.append({"assignee_id": None,
                            "$or": [{"company_id": {"$in": scope}},
                                    {"company_ids": {"$in": scope}}]})
        if "$or" in q:
            q = {"$and": [{"$or": q.pop("$or")}, {"$or": role_or}, q]}
        else:
            q["$or"] = role_or
    tasks = await db.portal_tasks.find(q, {"_id": 0}).sort(
        [("status", 1), ("due_date", 1), ("created_at", -1)]).to_list(500)
    today = _now().strftime("%Y-%m-%d")
    counts = {"open": 0, "in_progress": 0, "submitted": 0, "done": 0,
              "approved": 0, "overdue": 0}
    all_q = dict(q)
    all_q.pop("status", None)
    async for t in db.portal_tasks.find(all_q, {"_id": 0, "status": 1, "due_date": 1}):
        counts[t.get("status", "open")] = counts.get(t.get("status", "open"), 0) + 1
        if t.get("status") not in ("done", "approved") \
                and t.get("due_date") and t["due_date"] < today:
            counts["overdue"] += 1
    return {"tasks": tasks, "counts": counts}


@router.get("/portal-tasks/priority")
async def priority_tasks(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Iter 499 (user request) — compact Priority-Tasks highlight for the
    dashboard. Returns ONLY urgent items (max 8): overdue → high priority →
    due today → today's statutory schedule. Completed / low-priority tasks
    are never included. Lightweight: no recurring generation, small
    projection, capped scan."""
    admin = await _admin(authorization)
    cid = _scope(admin, company_id)
    today = _now().strftime("%Y-%m-%d")
    q: Dict[str, Any] = {"status": {"$ne": "done"}}
    if cid:
        q["company_id"] = cid
    q["$or"] = [
        {"due_date": {"$ne": None, "$lte": today}},
        {"priority": "high"},
    ]
    proj = {"_id": 0, "task_id": 1, "title": 1, "company_name": 1,
            "assignee_name": 1, "due_date": 1, "priority": 1, "status": 1}
    items: List[Dict[str, Any]] = []
    async for t in db.portal_tasks.find(q, proj).sort("due_date", 1).limit(60):
        due = t.get("due_date")
        if due and due < today:
            bucket, rank = "overdue", 0
        elif t.get("priority") == "high":
            bucket, rank = "high", 1
        elif due == today:
            bucket, rank = "due_today", 2
        else:
            continue
        items.append({**t, "bucket": bucket, "_rank": rank})
    items.sort(key=lambda x: (x["_rank"], x.get("due_date") or "9999"))
    for it in items:
        it.pop("_rank", None)

    # Today's statutory schedule (not yet ticked in the calendar)
    schedule: List[Dict[str, Any]] = []
    month = today[:7]
    scope_key = cid or "__all__"
    done_keys = {c["item_key"] async for c in db.calendar_completions.find(
        {"month": month, "scope": scope_key}, {"_id": 0, "item_key": 1})}
    for it in _statutory_items(month):
        if it.get("date") == today and it["key"] not in done_keys:
            schedule.append({"key": it["key"], "title": it["title"],
                             "kind": it.get("kind"), "date": it["date"]})

    return {"items": items[:8], "schedule": schedule[:4], "today": today}


@router.post("/portal-tasks")
async def create_task(payload: TaskCreate, authorization: Optional[str] = Header(None)):
    """Iter 502 — hierarchical assignment:
      * super_admin  → may assign ONLY to Sub Super Admins (never directly
        to employees), across one or multiple companies.
      * sub_admin    → may create INTERNAL tasks and assign them to team
        members (employees / company admins) of THEIR assigned companies.
      * company_admin → cannot create tasks (Iter 501 user request).
    """
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin"):
        raise HTTPException(status_code=403,
                            detail="Only Super Admin / Sub Super Admins can create tasks")
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    if payload.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority")

    # ---- companies (single or multiple) ----
    cids: List[str] = [c for c in (payload.company_ids or []) if c]
    if not cids and payload.company_id:
        cids = [payload.company_id]
    my_scope = _sub_scope_ids(admin)
    if admin.get("role") == "sub_admin" and my_scope is not None:
        bad = [c for c in cids if c not in my_scope]
        if bad:
            raise HTTPException(status_code=403,
                                detail="Firm not in your assigned scope")
    company_names: List[str] = []
    for c in cids:
        doc = await db.companies.find_one({"company_id": c}, {"_id": 0, "name": 1})
        if doc:
            company_names.append(doc["name"])

    # ---- assignee validation (RBAC hierarchy) ----
    assignee = None
    if payload.assignee_id:
        assignee = await db.users.find_one(
            {"user_id": payload.assignee_id},
            {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1,
             "company_id": 1, "sub_admin_company_scope": 1,
             "sub_admin_company_ids": 1})
        if not assignee:
            raise HTTPException(status_code=404, detail="Assignee not found")
        if admin.get("role") == "super_admin":
            if assignee.get("role") != "sub_admin":
                raise HTTPException(
                    status_code=400,
                    detail="Super Admin can assign tasks only to Sub Super Admins")
            a_scope = _sub_scope_ids(assignee)
            if a_scope is not None:
                bad = [c for c in cids if c not in a_scope]
                if bad:
                    raise HTTPException(
                        status_code=400,
                        detail="Selected firm(s) are not assigned to this Sub Super Admin")
        else:  # sub_admin delegating internally
            if assignee.get("role") == "sub_admin" \
                    and assignee["user_id"] != admin["user_id"]:
                raise HTTPException(
                    status_code=403,
                    detail="You can assign only to your own team members")
            if assignee.get("role") in ("employee", "company_admin"):
                a_cid = assignee.get("company_id")
                if my_scope is not None and a_cid not in my_scope:
                    raise HTTPException(
                        status_code=403,
                        detail="This member is not in your assigned companies")

    task = {
        "task_id": f"task_{uuid.uuid4().hex[:12]}",
        "title": title,
        "description": (payload.description or "").strip() or None,
        "company_id": cids[0] if cids else None,
        "company_name": company_names[0] if company_names else None,
        "company_ids": cids,
        "company_names": company_names,
        "assignee_id": (assignee or {}).get("user_id"),
        "assignee_name": (assignee or {}).get("name") or (assignee or {}).get("email"),
        "assignee_role": (assignee or {}).get("role"),
        "assigned_by": admin["user_id"],
        "assigned_by_name": admin.get("name") or admin.get("email"),
        "assigned_by_role": admin.get("role"),
        "due_date": payload.due_date or None,
        "priority": payload.priority,
        "status": "open",
        "created_by": admin["user_id"],
        "created_by_name": admin.get("name"),
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
    }
    await db.portal_tasks.insert_one(dict(task))
    await _task_audit(admin, "assigned" if assignee else "created", task,
                      f"→ {(assignee or {}).get('name') or 'unassigned'} · "
                      f"{', '.join(company_names) or 'general'}")
    return {"ok": True, "task": task}


@router.patch("/portal-tasks/{task_id}")
async def update_task(task_id: str, payload: TaskUpdate,
                      authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    t = await db.portal_tasks.find_one({"task_id": task_id})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if admin.get("role") == "company_admin" and t.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's task")
    # Iter 502 — a sub_admin may act only on their own tasks (assigned to
    # them or created by them). Another Sub Super Admin's tasks are off-limits.
    if admin.get("role") == "sub_admin" and not _is_task_owner(admin, t):
        raise HTTPException(status_code=403,
                            detail="Not your task — belongs to another Sub Super Admin")
    upd: Dict[str, Any] = {}
    for f in ["title", "description", "due_date"]:
        v = getattr(payload, f)
        if v is not None:
            upd[f] = v.strip() or None if isinstance(v, str) else v
    if payload.priority is not None:
        if payload.priority not in TASK_PRIORITIES:
            raise HTTPException(status_code=400, detail="Invalid priority")
        upd["priority"] = payload.priority
    if payload.status is not None:
        if payload.status not in TASK_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        # Iter 502 — workflow gates:
        #   approve        → super_admin only
        #   super-assigned → the sub_admin SUBMITS for review (cannot self-done)
        if payload.status == "approved" and admin.get("role") != "super_admin":
            raise HTTPException(status_code=403,
                                detail="Only the Super Admin can approve & close tasks")
        if (payload.status == "done"
                and admin.get("role") == "sub_admin"
                and t.get("assigned_by_role") == "super_admin"
                and t.get("assignee_id") == admin["user_id"]):
            raise HTTPException(
                status_code=400,
                detail="Submit this task for the Super Admin's review instead")
        upd["status"] = payload.status
        if payload.status == "done":
            upd["completed_at"] = _now().isoformat()
            upd["completed_by"] = admin["user_id"]
        elif payload.status == "submitted":
            upd["submitted_at"] = _now().isoformat()
            upd["submitted_by"] = admin["user_id"]
            upd["submitted_by_name"] = admin.get("name") or admin.get("email")
        elif payload.status == "approved":
            upd["approved_at"] = _now().isoformat()
            upd["approved_by"] = admin["user_id"]
            upd["approved_by_name"] = admin.get("name") or admin.get("email")
    if payload.company_id is not None and admin.get("role") != "company_admin":
        upd["company_id"] = payload.company_id or None
        c = await db.companies.find_one({"company_id": payload.company_id}, {"_id": 0, "name": 1})
        upd["company_name"] = (c or {}).get("name")
    if payload.assignee_id is not None:
        upd["assignee_id"] = payload.assignee_id or None
        u = await db.users.find_one({"user_id": payload.assignee_id},
                                    {"_id": 0, "name": 1, "role": 1})
        upd["assignee_name"] = (u or {}).get("name")
        upd["assignee_role"] = (u or {}).get("role")
    # Iter 505 (user request — "Edit Content of Task … maintain log") —
    # field-by-field EDIT LOG for every content change.
    _edit_changes: List[str] = []
    _edit_fields = {"title": "Title", "description": "Description",
                    "due_date": "Due date", "priority": "Priority",
                    "company_id": "Firm"}
    for _f, _lbl in _edit_fields.items():
        if _f in upd and (t.get(_f) or None) != (upd.get(_f) or None):
            if _f == "company_id":
                _old = t.get("company_name") or "None"
                _new = upd.get("company_name") or "None"
            else:
                _old = t.get(_f) if t.get(_f) not in (None, "") else "—"
                _new = upd.get(_f) if upd.get(_f) not in (None, "") else "—"
            _edit_changes.append(f"{_lbl}: “{_old}” → “{_new}”")
    if _edit_changes:
        upd["last_edited_at"] = _now().isoformat()
        upd["last_edited_by"] = admin["user_id"]
        upd["last_edited_by_name"] = admin.get("name") or admin.get("email")
        upd["edited_count"] = int(t.get("edited_count") or 0) + 1
    upd["updated_at"] = _now().isoformat()
    await db.portal_tasks.update_one({"task_id": task_id}, {"$set": upd})
    t2 = await db.portal_tasks.find_one({"task_id": task_id}, {"_id": 0})
    if _edit_changes:
        await _task_audit(admin, "edited", t2, " · ".join(_edit_changes))
    if payload.status is not None:
        await _task_audit(admin, f"status:{payload.status}", t2)
        await _sync_calendar_from_task(admin, t2)
    if payload.assignee_id is not None:
        await _task_audit(admin, "reassigned", t2,
                          f"→ {upd.get('assignee_name') or 'unassigned'}")
    return {"ok": True, "task": t2}


# Statutory recurring preset → compliance-calendar item key mapping
SEED_TO_CAL_KEY = {"pf_ecr": "pf", "esic": "esic", "tds": "tds", "pt": "pt"}


async def _sync_calendar_from_task(admin: dict, task: dict) -> None:
    """Keep the Compliance Calendar tick in sync when a statutory
    recurring task is marked done/reopened."""
    rtask_id = task.get("source_rtask_id")
    if not rtask_id:
        return
    tpl = await db.recurring_tasks.find_one(
        {"rtask_id": rtask_id}, {"_id": 0, "seed_key": 1})
    item_key = SEED_TO_CAL_KEY.get((tpl or {}).get("seed_key") or "")
    if not item_key:
        return
    month = task.get("month") or (task.get("due_date") or "")[:7]
    if not month:
        return
    firm_scope = task.get("company_id") or "__all__"
    if task.get("status") == "done":
        await db.calendar_completions.update_one(
            {"month": month, "scope": firm_scope, "item_key": item_key},
            {"$set": {"completed_by": admin["user_id"],
                      "completed_at": _now().isoformat(),
                      "via": f"task:{task['task_id']}"}},
            upsert=True)
        # if EVERY firm's task for this template+month is done, tick the
        # all-firms calendar view too
        remaining = await db.portal_tasks.count_documents(
            {"source_rtask_id": rtask_id, "month": month,
             "status": {"$ne": "done"}})
        if remaining == 0:
            await db.calendar_completions.update_one(
                {"month": month, "scope": "__all__", "item_key": item_key},
                {"$set": {"completed_by": admin["user_id"],
                          "completed_at": _now().isoformat(),
                          "via": f"task:{task['task_id']}"}},
                upsert=True)
    else:
        # reopened → un-tick this firm's scope and the all-firms rollup
        await db.calendar_completions.delete_many(
            {"month": month, "item_key": item_key,
             "scope": {"$in": [firm_scope, "__all__"]}})


@router.delete("/portal-tasks/{task_id}")
async def delete_task(task_id: str, authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    t = await db.portal_tasks.find_one({"task_id": task_id})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if admin.get("role") == "company_admin" and t.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's task")
    if admin.get("role") == "sub_admin" and not _is_task_owner(admin, t):
        raise HTTPException(status_code=403,
                            detail="Not your task — belongs to another Sub Super Admin")
    await db.portal_tasks.delete_one({"task_id": task_id})
    await _task_audit(admin, "deleted", t)
    return {"ok": True}


# ---------- Iter 502 — hierarchy: assignees, delegation, dashboards ----------

@router.get("/portal-tasks/assignees")
async def task_assignees(authorization: Optional[str] = Header(None)):
    """Who can I assign tasks to?
      * super_admin → the Sub Super Admins (with their assigned firms).
      * sub_admin   → team members (employees / company admins) of THEIR
        assigned companies only."""
    admin = await _admin(authorization)
    if admin.get("role") == "super_admin":
        out = []
        async for u in db.users.find(
                {"role": "sub_admin", "deleted": {"$ne": True}},
                {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1,
                 "sub_admin_company_scope": 1, "sub_admin_company_ids": 1}):
            scope = _sub_scope_ids(u)
            names: List[str] = []
            if scope is not None:
                async for c in db.companies.find(
                        {"company_id": {"$in": scope}}, {"_id": 0, "name": 1}):
                    names.append(c["name"])
            out.append({"user_id": u["user_id"],
                        "name": u.get("name") or u.get("email"),
                        "role": "sub_admin",
                        "company_ids": scope,     # None = all firms
                        "company_names": names})
        return {"assignees": out, "kind": "sub_admins"}
    if admin.get("role") == "sub_admin":
        scope = _sub_scope_ids(admin)
        q: Dict[str, Any] = {"role": {"$in": ["employee", "company_admin"]},
                             "deleted": {"$ne": True}}
        if scope is not None:
            q["company_id"] = {"$in": scope}
        out = []
        async for u in db.users.find(
                q, {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
                    "designation": 1, "role": 1, "company_id": 1}).limit(800):
            out.append({"user_id": u["user_id"],
                        "name": u.get("name") or "",
                        "employee_code": u.get("employee_code") or "",
                        "designation": u.get("designation") or "",
                        "role": u.get("role"),
                        "company_id": u.get("company_id")})
        return {"assignees": out, "kind": "team"}
    return {"assignees": [], "kind": "none"}


class DelegateBody(BaseModel):
    assignee_id: str
    note: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None


@router.post("/portal-tasks/{task_id}/delegate")
async def delegate_task(task_id: str, payload: DelegateBody,
                        authorization: Optional[str] = Header(None)):
    """Iter 502 — a Sub Super Admin distributes a received task to a team
    member within their assigned companies (creates a linked child task)."""
    admin = await _admin(authorization)
    if admin.get("role") not in ("sub_admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Forbidden")
    t = await db.portal_tasks.find_one({"task_id": task_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if admin.get("role") == "sub_admin" and not _is_task_owner(admin, t):
        raise HTTPException(status_code=403,
                            detail="Not your task — belongs to another Sub Super Admin")
    assignee = await db.users.find_one(
        {"user_id": payload.assignee_id},
        {"_id": 0, "user_id": 1, "name": 1, "role": 1, "company_id": 1})
    if not assignee:
        raise HTTPException(status_code=404, detail="Team member not found")
    if admin.get("role") == "super_admin" and assignee.get("role") != "sub_admin":
        raise HTTPException(status_code=400,
                            detail="Super Admin can assign tasks only to Sub Super Admins")
    scope = _sub_scope_ids(admin)
    if admin.get("role") == "sub_admin" and scope is not None \
            and assignee.get("role") in ("employee", "company_admin") \
            and assignee.get("company_id") not in scope:
        raise HTTPException(status_code=403,
                            detail="This member is not in your assigned companies")
    child = {
        **{k: t.get(k) for k in ("title", "company_id", "company_name",
                                 "company_ids", "company_names")},
        "task_id": f"task_{uuid.uuid4().hex[:12]}",
        "description": (payload.note or "").strip() or t.get("description"),
        "assignee_id": assignee["user_id"],
        "assignee_name": assignee.get("name"),
        "assignee_role": assignee.get("role"),
        "assigned_by": admin["user_id"],
        "assigned_by_name": admin.get("name") or admin.get("email"),
        "assigned_by_role": admin.get("role"),
        "parent_task_id": task_id,
        "due_date": payload.due_date or t.get("due_date"),
        "priority": payload.priority if payload.priority in TASK_PRIORITIES else t.get("priority", "medium"),
        "status": "open",
        "created_by": admin["user_id"],
        "created_by_name": admin.get("name"),
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
    }
    await db.portal_tasks.insert_one(dict(child))
    await db.portal_tasks.update_one(
        {"task_id": task_id},
        {"$inc": {"delegated_count": 1},
         "$set": {"updated_at": _now().isoformat()}})
    await _task_audit(admin, "delegated", child,
                      f"from {task_id} → {assignee.get('name')}")
    return {"ok": True, "task": child}


@router.get("/portal-tasks/hub-dashboard")
async def task_hub_dashboard(authorization: Optional[str] = Header(None)):
    """Role-aware hierarchy dashboard counters."""
    admin = await _admin(authorization)
    today = _now().strftime("%Y-%m-%d")
    week = (_now() + timedelta(days=7)).strftime("%Y-%m-%d")
    if admin.get("role") == "super_admin":
        total_companies = await db.companies.count_documents(
            {"deleted": {"$ne": True}})
        total_subs = await db.users.count_documents(
            {"role": "sub_admin", "deleted": {"$ne": True}})
        by_company: Dict[str, Dict[str, Any]] = {}
        overdue = escalated = submitted = 0
        async for t in db.portal_tasks.find(
                {}, {"_id": 0, "status": 1, "due_date": 1, "priority": 1,
                     "company_name": 1}):
            st_ = t.get("status", "open")
            key = t.get("company_name") or "General"
            b = by_company.setdefault(key, {"company": key, "pending": 0, "completed": 0})
            if st_ in ("done", "approved"):
                b["completed"] += 1
            else:
                b["pending"] += 1
                if t.get("due_date") and t["due_date"] < today:
                    overdue += 1
                    if t.get("priority") == "high":
                        escalated += 1
            if st_ == "submitted":
                submitted += 1
        return {"role": "super_admin", "total_companies": total_companies,
                "total_sub_admins": total_subs,
                "overdue": overdue, "escalated": escalated,
                "awaiting_review": submitted,
                "by_company": sorted(by_company.values(),
                                     key=lambda b: -b["pending"])[:12]}
    if admin.get("role") == "sub_admin":
        scope = _sub_scope_ids(admin)
        names: List[str] = []
        if scope is not None:
            async for c in db.companies.find({"company_id": {"$in": scope}},
                                             {"_id": 0, "name": 1}):
                names.append(c["name"])
        me = admin["user_id"]
        pending = completed = high = upcoming = 0
        deleg_total = deleg_done = 0
        async for t in db.portal_tasks.find(
                {"$or": [{"assignee_id": me}, {"created_by": me}]},
                {"_id": 0, "status": 1, "due_date": 1, "priority": 1,
                 "assignee_id": 1, "created_by": 1, "parent_task_id": 1}):
            st_ = t.get("status", "open")
            mine = t.get("assignee_id") == me
            if t.get("created_by") == me and not mine:
                deleg_total += 1
                if st_ in ("done", "approved"):
                    deleg_done += 1
            if st_ in ("done", "approved"):
                completed += 1
            else:
                pending += 1
                if t.get("priority") == "high":
                    high += 1
                if t.get("due_date") and today <= t["due_date"] <= week:
                    upcoming += 1
        return {"role": "sub_admin",
                "assigned_companies": names if scope is not None else ["All firms"],
                "pending": pending, "completed": completed,
                "high_priority": high, "upcoming_deadlines": upcoming,
                "team_total": deleg_total, "team_done": deleg_done}
    return {"role": admin.get("role")}


@router.get("/portal-tasks/{task_id}/audit")
async def task_audit_trail(task_id: str,
                           authorization: Optional[str] = Header(None)):
    await _admin(authorization)
    items = await db.task_audit_log.find(
        {"task_id": task_id}, {"_id": 0}).sort("at", -1).to_list(100)
    return {"audit": items}


# ---------- Iter 503 — task attachments (photo / PDF evidence) ----------

MAX_ATT_BYTES = 10 * 1024 * 1024   # 10 MB per file
MAX_ATT_PER_TASK = 10
ATT_MIMES = ("image/", "application/pdf")


class AttachmentBody(BaseModel):
    filename: str
    mime: str
    file_base64: str


@router.post("/portal-tasks/{task_id}/attachments")
async def add_attachment(task_id: str, payload: AttachmentBody,
                         authorization: Optional[str] = Header(None)):
    """Attach proof (photo / PDF) to a task — e.g. evidence a Sub Super
    Admin uploads before 'Submit for Review'."""
    admin = await _admin(authorization)
    t = await db.portal_tasks.find_one({"task_id": task_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if admin.get("role") == "sub_admin" and not _is_task_owner(admin, t):
        raise HTTPException(status_code=403,
                            detail="Not your task — belongs to another Sub Super Admin")
    if admin.get("role") == "company_admin" \
            and t.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's task")
    mime = (payload.mime or "").lower()
    if not any(mime.startswith(m) for m in ATT_MIMES):
        raise HTTPException(status_code=400,
                            detail="Only images and PDF files are allowed")
    import base64 as _b64
    try:
        raw_len = len(_b64.b64decode(payload.file_base64 or ""))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file data")
    if raw_len == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if raw_len > MAX_ATT_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds the 10 MB limit")
    n = await db.task_attachments.count_documents({"task_id": task_id})
    if n >= MAX_ATT_PER_TASK:
        raise HTTPException(status_code=400,
                            detail=f"Maximum {MAX_ATT_PER_TASK} attachments per task")
    att = {
        "att_id": f"tatt_{uuid.uuid4().hex[:12]}",
        "task_id": task_id,
        "filename": (payload.filename or "file")[:120],
        "mime": mime,
        "size": raw_len,
        "uploaded_by": admin["user_id"],
        "uploaded_by_name": admin.get("name") or admin.get("email"),
        "uploaded_by_role": admin.get("role"),
        "at": _now().isoformat(),
    }
    await db.task_attachments.insert_one({**att, "data_b64": payload.file_base64})
    await db.portal_tasks.update_one(
        {"task_id": task_id},
        {"$inc": {"attachments_count": 1},
         "$set": {"updated_at": _now().isoformat()}})
    await _task_audit(admin, "attachment_added", t,
                      f"{att['filename']} ({round(raw_len / 1024)} KB)")
    return {"ok": True, "attachment": att}


@router.get("/portal-tasks/{task_id}/attachments")
async def list_attachments(task_id: str,
                           authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    t = await db.portal_tasks.find_one({"task_id": task_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if admin.get("role") == "sub_admin" and not _is_task_owner(admin, t):
        raise HTTPException(status_code=403, detail="Not your task")
    items = await db.task_attachments.find(
        {"task_id": task_id}, {"_id": 0, "data_b64": 0}).sort("at", 1).to_list(50)
    return {"attachments": items}


@router.get("/portal-tasks/attachments/{att_id}")
async def get_attachment(att_id: str,
                         authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    a = await db.task_attachments.find_one({"att_id": att_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Attachment not found")
    t = await db.portal_tasks.find_one({"task_id": a["task_id"]}, {"_id": 0})
    if t and admin.get("role") == "sub_admin" and not _is_task_owner(admin, t):
        raise HTTPException(status_code=403, detail="Not your task")
    return {"filename": a["filename"], "mime": a["mime"],
            "file_base64": a.get("data_b64") or ""}


@router.delete("/portal-tasks/attachments/{att_id}")
async def delete_attachment(att_id: str,
                            authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    a = await db.task_attachments.find_one({"att_id": att_id}, {"_id": 0, "data_b64": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if admin.get("role") != "super_admin" and a.get("uploaded_by") != admin["user_id"]:
        raise HTTPException(status_code=403,
                            detail="Only the uploader or the Super Admin can delete this")
    await db.task_attachments.delete_one({"att_id": att_id})
    await db.portal_tasks.update_one(
        {"task_id": a["task_id"]}, {"$inc": {"attachments_count": -1}})
    t = await db.portal_tasks.find_one({"task_id": a["task_id"]}, {"_id": 0}) or {"task_id": a["task_id"]}
    await _task_audit(admin, "attachment_removed", t, a.get("filename") or "")
    return {"ok": True}


# ======================= TRACKED DOCUMENTS ==========================

class TrackedDocCreate(BaseModel):
    title: str
    doc_type: str = "other"
    company_id: Optional[str] = None
    doc_number: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: str                       # YYYY-MM-DD (required)
    remind_days: int = 30
    notes: Optional[str] = None


class TrackedDocUpdate(BaseModel):
    title: Optional[str] = None
    doc_type: Optional[str] = None
    doc_number: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None
    remind_days: Optional[int] = None
    notes: Optional[str] = None


def _doc_bucket(expiry: str, today: str) -> str:
    if expiry < today:
        return "expired"
    d = (datetime.strptime(expiry, "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days
    if d <= 7:
        return "critical"
    if d <= 30:
        return "warning"
    if d <= 90:
        return "upcoming"
    return "ok"


@router.get("/tracked-documents")
async def list_tracked_documents(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await _admin(authorization)
    cid = _scope(admin, company_id)
    q: Dict[str, Any] = {"company_id": cid} if cid else {}
    docs = await db.tracked_documents.find(q, {"_id": 0}).sort("expiry_date", 1).to_list(500)
    today = _now().strftime("%Y-%m-%d")
    buckets = {"expired": 0, "critical": 0, "warning": 0, "upcoming": 0, "ok": 0}
    for d in docs:
        b = _doc_bucket(d.get("expiry_date", "9999-12-31"), today)
        d["bucket"] = b
        d["days_left"] = (datetime.strptime(d["expiry_date"], "%Y-%m-%d")
                          - datetime.strptime(today, "%Y-%m-%d")).days
        buckets[b] += 1
    return {"documents": docs, "buckets": buckets, "today": today}


@router.post("/tracked-documents")
async def create_tracked_document(payload: TrackedDocCreate,
                                  authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    if payload.doc_type not in DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"doc_type must be one of {DOC_TYPES}")
    try:
        datetime.strptime(payload.expiry_date, "%Y-%m-%d")
    except Exception:
        raise HTTPException(status_code=400, detail="expiry_date must be YYYY-MM-DD")
    cid = _scope(admin, payload.company_id)
    company_name = None
    if cid:
        c = await db.companies.find_one({"company_id": cid}, {"_id": 0, "name": 1})
        company_name = (c or {}).get("name")
    doc = {
        "tdoc_id": f"tdoc_{uuid.uuid4().hex[:12]}",
        "title": title,
        "doc_type": payload.doc_type,
        "company_id": cid,
        "company_name": company_name,
        "doc_number": (payload.doc_number or "").strip() or None,
        "issue_date": payload.issue_date or None,
        "expiry_date": payload.expiry_date,
        "remind_days": max(1, int(payload.remind_days or 30)),
        "notes": (payload.notes or "").strip() or None,
        "created_by": admin["user_id"],
        "created_at": _now().isoformat(),
    }
    await db.tracked_documents.insert_one(dict(doc))
    return {"ok": True, "document": doc}


@router.patch("/tracked-documents/{tdoc_id}")
async def update_tracked_document(tdoc_id: str, payload: TrackedDocUpdate,
                                  authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    d = await db.tracked_documents.find_one({"tdoc_id": tdoc_id})
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    if admin.get("role") == "company_admin" and d.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's document")
    upd: Dict[str, Any] = {}
    for f in ["title", "doc_number", "issue_date", "expiry_date", "notes"]:
        v = getattr(payload, f)
        if v is not None:
            upd[f] = v.strip() or None if isinstance(v, str) else v
    if payload.doc_type is not None:
        if payload.doc_type not in DOC_TYPES:
            raise HTTPException(status_code=400, detail="Invalid doc_type")
        upd["doc_type"] = payload.doc_type
    if payload.remind_days is not None:
        upd["remind_days"] = max(1, int(payload.remind_days))
    await db.tracked_documents.update_one({"tdoc_id": tdoc_id}, {"$set": upd})
    d2 = await db.tracked_documents.find_one({"tdoc_id": tdoc_id}, {"_id": 0})
    return {"ok": True, "document": d2}


@router.delete("/tracked-documents/{tdoc_id}")
async def delete_tracked_document(tdoc_id: str,
                                  authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    d = await db.tracked_documents.find_one({"tdoc_id": tdoc_id})
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    if admin.get("role") == "company_admin" and d.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's document")
    await db.tracked_documents.delete_one({"tdoc_id": tdoc_id})
    return {"ok": True}


# ======================= CLIENT HEALTH SCORES =======================

@router.get("/portal-dashboard/client-health")
async def client_health(authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    cid = _scope(admin, None)
    firm_q = {"company_id": cid} if cid else {}
    firms = await db.companies.find(
        firm_q, {"_id": 0, "company_id": 1, "name": 1}).to_list(200)
    now = _now()
    today = now.strftime("%Y-%m-%d")
    month = today[:7]
    horizon30 = (now + timedelta(days=30)).strftime("%Y-%m-%d")

    # bulk aggregates keyed by company_id
    emp_counts: Dict[str, int] = defaultdict(int)
    async for u in db.users.find(
        {"role": "employee",
         "$or": [{"disabled": {"$ne": True}}, {"disabled": {"$exists": False}}]},
        {"_id": 0, "company_id": 1},
    ):
        emp_counts[u.get("company_id")] += 1
    present: Dict[str, set] = defaultdict(set)
    async for r in db.attendance.find(
        {"date": today, "kind": "in", "status": {"$ne": "rejected"}},
        {"_id": 0, "company_id": 1, "user_id": 1},
    ):
        present[r.get("company_id")].add(r["user_id"])
    pend_punch: Dict[str, int] = defaultdict(int)
    async for r in db.attendance.find({"status": "pending"}, {"_id": 0, "company_id": 1}):
        pend_punch[r.get("company_id")] += 1
    pend_leave: Dict[str, int] = defaultdict(int)
    async for r in db.leaves.find({"status": "pending"}, {"_id": 0, "company_id": 1}):
        pend_leave[r.get("company_id")] += 1
    open_tk: Dict[str, int] = defaultdict(int)
    async for r in db.tickets.find(
        {"status": {"$in": ["open", "in_progress"]}}, {"_id": 0, "company_id": 1}
    ):
        open_tk[r.get("company_id")] += 1
    runs: Dict[str, str] = {}
    async for r in db.compliance_salary_runs.find(
        {"month": month}, {"_id": 0, "company_id": 1, "finalized": 1}
    ):
        cur = runs.get(r.get("company_id"))
        st = "finalized" if r.get("finalized") else "processed"
        if cur != "finalized":
            runs[r.get("company_id")] = st
    expiring: Dict[str, int] = defaultdict(int)
    async for d in db.tracked_documents.find(
        {"expiry_date": {"$lte": horizon30}}, {"_id": 0, "company_id": 1}
    ):
        expiring[d.get("company_id")] += 1

    results = []
    for f in firms:
        c = f["company_id"]
        n_emp = emp_counts.get(c, 0)
        att_rate = (len(present.get(c, set())) / n_emp) if n_emp else 0.0
        run_st = runs.get(c, "not_processed")
        factors: List[Dict[str, Any]] = []

        # Payroll compliance — 30 pts
        payroll_pts = 30 if run_st == "finalized" else 15 if run_st == "processed" else 0
        factors.append({"label": f"Payroll ({month})", "score": payroll_pts, "max": 30,
                        "detail": run_st.replace("_", " ")})
        # Attendance activity — 25 pts
        att_pts = round(min(1.0, att_rate / 0.7) * 25)
        factors.append({"label": "Attendance today", "score": att_pts, "max": 25,
                        "detail": f"{len(present.get(c, set()))}/{n_emp} present"})
        # Pending punch approvals — 15 pts
        pp = pend_punch.get(c, 0)
        pp_pts = 15 if pp == 0 else 10 if pp <= 5 else 5 if pp <= 20 else 0
        factors.append({"label": "Punch approvals", "score": pp_pts, "max": 15,
                        "detail": f"{pp} pending"})
        # Pending leaves — 10 pts
        pl = pend_leave.get(c, 0)
        pl_pts = 10 if pl == 0 else 6 if pl <= 3 else 2
        factors.append({"label": "Leave approvals", "score": pl_pts, "max": 10,
                        "detail": f"{pl} pending"})
        # Open tickets — 10 pts
        tk = open_tk.get(c, 0)
        tk_pts = 10 if tk == 0 else 6 if tk <= 3 else 2
        factors.append({"label": "Tickets", "score": tk_pts, "max": 10,
                        "detail": f"{tk} open"})
        # Document expiry — 10 pts
        ex = expiring.get(c, 0)
        ex_pts = 10 if ex == 0 else 5 if ex <= 2 else 0
        factors.append({"label": "Document expiry (30d)", "score": ex_pts, "max": 10,
                        "detail": f"{ex} expiring"})

        score = payroll_pts + att_pts + pp_pts + pl_pts + tk_pts + ex_pts
        grade = ("A" if score >= 85 else "B" if score >= 70
                 else "C" if score >= 50 else "D")
        results.append({
            "company_id": c, "name": f.get("name"), "score": score,
            "grade": grade, "employees": n_emp, "factors": factors,
        })
    results.sort(key=lambda x: x["score"])
    return {"month": month, "clients": results}


# ================== ENHANCED COMPLIANCE CALENDAR ====================

def _statutory_items(month: str) -> List[Dict[str, str]]:
    y, m = int(month[:4]), int(month[5:7])

    def d(day: int) -> str:
        return f"{y:04d}-{m:02d}-{day:02d}"
    return [
        {"key": "tds", "date": d(7), "title": "TDS deposit (previous month)", "kind": "TDS"},
        {"key": "pf", "date": d(15), "title": "PF payment + ECR filing (previous month)", "kind": "EPFO"},
        {"key": "esic", "date": d(15), "title": "ESIC contribution payment (previous month)", "kind": "ESIC"},
        {"key": "pt", "date": d(21), "title": "Professional Tax deposit (state-wise, typical)", "kind": "PT"},
        {"key": "pf_return", "date": d(25), "title": "PF return verification (IW-1 where applicable)", "kind": "EPFO"},
    ]


@router.get("/portal-dashboard/calendar")
async def compliance_calendar(
    month: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await _admin(authorization)
    cid = _scope(admin, company_id)
    month = month or _now().strftime("%Y-%m")
    scope_key = cid or "__all__"

    done_keys = set()
    async for c in db.calendar_completions.find(
        {"month": month, "scope": scope_key}, {"_id": 0, "item_key": 1}
    ):
        done_keys.add(c["item_key"])

    events: List[Dict[str, Any]] = []
    for it in _statutory_items(month):
        events.append({**it, "type": "statutory", "done": it["key"] in done_keys})

    # task due dates in this month
    tq: Dict[str, Any] = {"due_date": {"$gte": f"{month}-01", "$lte": f"{month}-31"}}
    if cid:
        tq["company_id"] = cid
    async for t in db.portal_tasks.find(tq, {"_id": 0}):
        events.append({
            "key": t["task_id"], "date": t["due_date"],
            "title": t["title"], "kind": "TASK", "type": "task",
            "done": t.get("status") == "done",
            "company_name": t.get("company_name"),
        })

    # document expiries in this month
    dq: Dict[str, Any] = {"expiry_date": {"$gte": f"{month}-01", "$lte": f"{month}-31"}}
    if cid:
        dq["company_id"] = cid
    async for d in db.tracked_documents.find(dq, {"_id": 0}):
        events.append({
            "key": d["tdoc_id"], "date": d["expiry_date"],
            "title": f"{d['title']} expires", "kind": "DOC", "type": "document",
            "done": False, "company_name": d.get("company_name"),
        })

    events.sort(key=lambda e: e["date"])
    return {"month": month, "events": events,
            "today": _now().strftime("%Y-%m-%d")}


class CalendarToggle(BaseModel):
    month: str
    item_key: str
    company_id: Optional[str] = None


@router.post("/portal-dashboard/calendar/toggle")
async def toggle_calendar_item(payload: CalendarToggle,
                               authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    cid = _scope(admin, payload.company_id)
    scope_key = cid or "__all__"
    q = {"month": payload.month, "scope": scope_key, "item_key": payload.item_key}
    existing = await db.calendar_completions.find_one(q)
    if existing:
        await db.calendar_completions.delete_one(q)
        return {"ok": True, "done": False}
    await db.calendar_completions.insert_one({
        **q, "completed_by": admin["user_id"], "completed_at": _now().isoformat()})
    return {"ok": True, "done": True}


# ===================== ALERTS / NOTIFICATION CENTER =================

@router.get("/portal-dashboard/alerts")
async def portal_alerts(authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    cid = _scope(admin, None)
    q: Dict[str, Any] = {"company_id": cid} if cid else {}
    now = _now()
    today = now.strftime("%Y-%m-%d")
    month = today[:7]
    alerts: List[Dict[str, Any]] = []

    pend_punch = await db.attendance.count_documents({**q, "status": "pending"})
    if pend_punch:
        alerts.append({"severity": "warning", "icon": "time-outline",
                       "title": f"{pend_punch} punch approval(s) pending",
                       "route": "/punch-approvals"})
    pend_leave = await db.leaves.count_documents({**q, "status": "pending"})
    if pend_leave:
        alerts.append({"severity": "warning", "icon": "calendar-outline",
                       "title": f"{pend_leave} leave request(s) pending",
                       "route": "/leave-approvals"})
    try:
        pend_contract = await db.attendance.count_documents(
            {**q, "status": "pending", "is_contractual": True})
        if pend_contract:
            alerts.append({"severity": "info", "icon": "briefcase-outline",
                           "title": f"{pend_contract} contractor punch(es) awaiting approval",
                           "route": "/contractor-punches"})
    except Exception:
        pass
    open_tickets = await db.tickets.count_documents(
        {**q, "status": {"$in": ["open", "in_progress"]}})
    if open_tickets:
        alerts.append({"severity": "info", "icon": "chatbubbles-outline",
                       "title": f"{open_tickets} service ticket(s) open",
                       "route": "/tickets"})

    # overdue / due-soon tasks
    overdue_tasks = await db.portal_tasks.count_documents(
        {**q, "status": {"$ne": "done"}, "due_date": {"$lt": today, "$ne": None}})
    if overdue_tasks:
        alerts.append({"severity": "critical", "icon": "alert-circle-outline",
                       "title": f"{overdue_tasks} task(s) overdue", "route": None,
                       "tab": "tasks"})

    # expiring documents
    horizon = (now + timedelta(days=30)).strftime("%Y-%m-%d")
    exp_docs = await db.tracked_documents.count_documents(
        {**q, "expiry_date": {"$lte": horizon}})
    if exp_docs:
        expired = await db.tracked_documents.count_documents(
            {**q, "expiry_date": {"$lt": today}})
        alerts.append({
            "severity": "critical" if expired else "warning",
            "icon": "document-text-outline",
            "title": (f"{exp_docs} document(s) expiring within 30 days"
                      + (f" ({expired} already expired)" if expired else "")),
            "route": None, "tab": "documents"})

    # statutory deadlines within next 5 days (not marked done)
    scope_key = cid or "__all__"
    done_keys = set()
    async for c in db.calendar_completions.find(
        {"month": month, "scope": scope_key}, {"_id": 0, "item_key": 1}
    ):
        done_keys.add(c["item_key"])
    soon = (now + timedelta(days=5)).strftime("%Y-%m-%d")
    for it in _statutory_items(month):
        if it["key"] in done_keys:
            continue
        if today <= it["date"] <= soon:
            alerts.append({"severity": "warning", "icon": "shield-outline",
                           "title": f"{it['title']} due {it['date'][8:]}-{it['date'][5:7]}",
                           "route": None, "tab": "calendar"})
        elif it["date"] < today:
            alerts.append({"severity": "critical", "icon": "shield-outline",
                           "title": f"OVERDUE: {it['title']} (was due {it['date'][8:]}-{it['date'][5:7]})",
                           "route": None, "tab": "calendar"})

    # payroll not finalized after the 15th
    if int(today[8:]) > 15:
        firm_q = {"company_id": cid} if cid else {}
        firms = await db.companies.find(
            firm_q, {"_id": 0, "company_id": 1, "name": 1}).to_list(200)
        fin_ids = set(await db.compliance_salary_runs.distinct(
            "company_id", {"month": month, "finalized": True}))
        not_fin = [f.get("name") for f in firms if f["company_id"] not in fin_ids]
        if not_fin:
            alerts.append({
                "severity": "warning", "icon": "cash-outline",
                "title": f"Payroll not finalized for {len(not_fin)} firm(s) — {month}",
                "route": "/compliance-salary-run"})

    # recent broadcast notifications
    notif_q: Dict[str, Any] = {}
    if cid:
        notif_q["$or"] = [{"company_id": cid}, {"audience": "all"}]
    recent = await db.notifications.find(
        notif_q, {"_id": 0, "title": 1, "body": 1, "created_at": 1}
    ).sort("created_at", -1).to_list(10)

    order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: order.get(a["severity"], 3))
    return {"alerts": alerts, "recent_notifications": recent,
            "generated_at": now.strftime("%d-%m-%Y %I:%M %p")}
