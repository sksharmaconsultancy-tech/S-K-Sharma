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

TASK_STATUSES = ["open", "in_progress", "done"]
TASK_PRIORITIES = ["low", "medium", "high"]
DOC_TYPES = ["license", "registration", "insurance", "contract", "certificate", "other"]


def _now() -> datetime:
    return datetime.now(IST)


async def _admin(authorization: Optional[str]):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    return admin


def _scope(admin: dict, company_id: Optional[str]) -> Optional[str]:
    """company_admin is always locked to their own firm."""
    if admin.get("role") == "company_admin":
        return admin.get("company_id")
    return company_id or None


# ============================= TASKS ================================

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    company_id: Optional[str] = None
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
    admin = await _admin(authorization)
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
    admin = await _admin(authorization)
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
    authorization: Optional[str] = Header(None),
):
    admin = await _admin(authorization)
    await _generate_recurring(admin)
    cid = _scope(admin, company_id)
    q: Dict[str, Any] = {}
    if cid:
        q["company_id"] = cid
    if status and status != "all":
        q["status"] = status
    tasks = await db.portal_tasks.find(q, {"_id": 0}).sort(
        [("status", 1), ("due_date", 1), ("created_at", -1)]).to_list(500)
    today = _now().strftime("%Y-%m-%d")
    counts = {"open": 0, "in_progress": 0, "done": 0, "overdue": 0}
    all_q = {"company_id": cid} if cid else {}
    async for t in db.portal_tasks.find(all_q, {"_id": 0, "status": 1, "due_date": 1}):
        counts[t.get("status", "open")] = counts.get(t.get("status", "open"), 0) + 1
        if t.get("status") != "done" and t.get("due_date") and t["due_date"] < today:
            counts["overdue"] += 1
    return {"tasks": tasks, "counts": counts}


@router.post("/portal-tasks")
async def create_task(payload: TaskCreate, authorization: Optional[str] = Header(None)):
    admin = await _admin(authorization)
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    if payload.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority")
    cid = _scope(admin, payload.company_id)
    company_name = None
    if cid:
        c = await db.companies.find_one({"company_id": cid}, {"_id": 0, "name": 1})
        company_name = (c or {}).get("name")
    assignee_name = None
    if payload.assignee_id:
        u = await db.users.find_one({"user_id": payload.assignee_id}, {"_id": 0, "name": 1})
        assignee_name = (u or {}).get("name")
    task = {
        "task_id": f"task_{uuid.uuid4().hex[:12]}",
        "title": title,
        "description": (payload.description or "").strip() or None,
        "company_id": cid,
        "company_name": company_name,
        "assignee_id": payload.assignee_id or None,
        "assignee_name": assignee_name,
        "due_date": payload.due_date or None,
        "priority": payload.priority,
        "status": "open",
        "created_by": admin["user_id"],
        "created_by_name": admin.get("name"),
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
    }
    await db.portal_tasks.insert_one(dict(task))
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
        upd["status"] = payload.status
        if payload.status == "done":
            upd["completed_at"] = _now().isoformat()
            upd["completed_by"] = admin["user_id"]
    if payload.company_id is not None and admin.get("role") != "company_admin":
        upd["company_id"] = payload.company_id or None
        c = await db.companies.find_one({"company_id": payload.company_id}, {"_id": 0, "name": 1})
        upd["company_name"] = (c or {}).get("name")
    if payload.assignee_id is not None:
        upd["assignee_id"] = payload.assignee_id or None
        u = await db.users.find_one({"user_id": payload.assignee_id}, {"_id": 0, "name": 1})
        upd["assignee_name"] = (u or {}).get("name")
    upd["updated_at"] = _now().isoformat()
    await db.portal_tasks.update_one({"task_id": task_id}, {"$set": upd})
    t2 = await db.portal_tasks.find_one({"task_id": task_id}, {"_id": 0})
    if payload.status is not None:
        await _sync_calendar_from_task(admin, t2)
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
    await db.portal_tasks.delete_one({"task_id": task_id})
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
