"""Approval Workflow Engine (RBAC Phase 3).

Configurable multi-level approval chains per company + module with an
Approval Inbox. Generic engine — first wired module: ADVANCE issuance.

Collections
-----------
approval_workflows:
  workflow_id, company_id, module, enabled,
  levels: [{level, approver_type: "company_admin"|"company_role",
            role_id?, role_name?}]

approval_requests:
  request_id, company_id, module, record_id, title, summary (dict),
  requested_by, requested_by_name, levels (snapshot), current_level,
  status: pending|approved|rejected|on_hold|returned,
  history: [{level, action, by, by_name, remarks, at}], created_at

Rules: maker-checker (requester cannot action own request); approver at
current level = real company_admin / super_admin / sub_admin OR staff
whose company_role matches the level's role_id.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from pydantic import BaseModel

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    sub_admin_can_touch_company,
)

router = APIRouter(prefix="/api/admin", tags=["approval-engine"])

MODULES = [
    {"key": "advance", "label": "Advance Issuance"},
    {"key": "employee_creation", "label": "Employee Creation / Onboarding"},
    {"key": "salary_lock", "label": "Salary Lock"},
    {"key": "leave", "label": "Leave"},
    # Iter 286 — Access & Workflow Management Phase A: configurable chains
    # for upcoming payroll workflows (engine wiring lands per-module).
    {"key": "shift_change", "label": "Shift Change"},
    {"key": "overtime", "label": "Overtime Approval"},
    {"key": "loan", "label": "Loan"},
    {"key": "salary_revision", "label": "Salary Revision"},
    {"key": "exit", "label": "Exit / Full & Final"},
    # Iter 706 — Official Tour Management (routes/tours.py).
    {"key": "tour", "label": "Official Tour"},
]
MODULE_KEYS = {m["key"] for m in MODULES}


async def _admin_scoped(authorization, company_id: Optional[str]) -> tuple:
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    elif admin["role"] == "sub_admin" and company_id and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm outside your scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return admin, company_id


def _user_can_action_level(user: dict, level: Dict[str, Any]) -> bool:
    """Is this user an eligible approver for the given workflow level?"""
    if user.get("role") in ("super_admin", "sub_admin"):
        return True
    if user.get("role") == "company_admin" and not user.get("is_company_staff"):
        return True  # firm owner can act on any level
    # Phase B — a delegated user may act on this level.
    if level.get("delegated_to") and user.get("user_id") == level.get("delegated_to"):
        return True
    # Iter 705 — a directly-assigned employee approver.
    # Iter 748 — reporting-chain approver (user_id resolved at request time).
    if level.get("approver_type") in ("employee", "reporting_chain") \
            and user.get("user_id") == level.get("user_id"):
        return True
    if user.get("is_company_staff") and level.get("approver_type") == "company_role":
        return user.get("company_role_id") == level.get("role_id")
    return False


# ---------------------------------------------------------------------------
# Phase B — conditional rules + SLA helpers
# ---------------------------------------------------------------------------
CONDITION_OPS = (">", ">=", "<", "<=", "==", "!=", "contains")


def _eval_condition(cond: Optional[Dict[str, Any]], summary: Dict[str, Any]) -> bool:
    """Evaluate a level condition against the request summary.
    Unknown / unevaluable conditions FAIL-SAFE to True (level required)."""
    if not cond or not str(cond.get("field") or "").strip():
        return True
    field = str(cond["field"]).strip()
    op = cond.get("op") or "=="
    val = cond.get("value")
    actual = summary.get(field)
    if actual is None:
        for k, v in (summary or {}).items():
            if str(k).lower() == field.lower():
                actual = v
                break
    try:
        if op in (">", ">=", "<", "<="):
            a, b = float(str(actual).replace(",", "")), float(str(val).replace(",", ""))
            return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]
        sa, sb = str(actual or "").strip().lower(), str(val or "").strip().lower()
        if op == "==":
            return sa == sb
        if op == "!=":
            return sa != sb
        if op == "contains":
            return sb in sa
    except (TypeError, ValueError):
        return True
    return True


def _cond_text(cond: Dict[str, Any]) -> str:
    return f"{cond.get('field')} {cond.get('op')} {cond.get('value')}"


async def _auto_escalate_overdue(company_id: str) -> int:
    """SLA auto-escalation (lazy): any pending request whose current level
    has sla_hours set and has been waiting longer moves to the next level
    (or is flagged sla_breached at the final level)."""
    n = 0
    now = datetime.now(timezone.utc)
    async for r in db.approval_requests.find(
            {"company_id": company_id, "status": "pending"}, {"_id": 0}):
        levels = r.get("levels") or []
        cur = next((l for l in levels if l.get("level") == r.get("current_level")), None)
        sla = int((cur or {}).get("sla_hours") or 0)
        if not cur or sla <= 0:
            continue
        since_raw = r.get("level_since") or r.get("created_at")
        try:
            since = datetime.fromisoformat(str(since_raw).replace("Z", "+00:00"))
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if now - since < timedelta(hours=sla):
            continue
        hist = {
            "level": r["current_level"], "action": "auto_escalated",
            "by": "system", "by_name": "SLA Engine",
            "remarks": f"SLA of {sla}h breached at level {r['current_level']}",
            "at": now_iso(),
        }
        upd: Dict[str, Any] = {"escalated": True, "updated_at": now_iso()}
        if r["current_level"] < len(levels):
            upd["current_level"] = r["current_level"] + 1
            upd["level_since"] = now_iso()
        else:
            upd["sla_breached"] = True
            upd["level_since"] = now_iso()  # avoid re-firing every load
        await db.approval_requests.update_one(
            {"request_id": r["request_id"], "status": "pending"},
            {"$set": upd, "$push": {"history": hist}})
        await _wf_notify(r["company_id"], r["module"], "escalated", r,
                         f"SLA of {sla}h breached — auto-escalated")
        n += 1
    return n


# ---------------------------------------------------------------------------
# Engine helpers (imported by feature modules e.g. routes/advances.py)
# ---------------------------------------------------------------------------
async def get_active_workflow(company_id: str, module: str) -> Optional[dict]:
    wf = await db.approval_workflows.find_one(
        {"company_id": company_id, "module": module, "enabled": True}, {"_id": 0})
    if wf and (wf.get("levels") or []):
        return wf
    return None


async def create_approval_request(
    company_id: str, module: str, record_id: str, title: str,
    summary: Dict[str, Any], requested_by: dict, workflow: dict,
) -> dict:
    # Phase B — conditional rules: only levels whose condition matches the
    # request summary are included. If every level is skipped, fall back
    # to a single Company Admin level (fail-safe: never auto-approve).
    all_levels = workflow.get("levels") or []
    applicable, skipped = [], []
    for lv in all_levels:
        if _eval_condition(lv.get("condition"), summary or {}):
            applicable.append(dict(lv))
        else:
            skipped.append(lv)
    if not applicable:
        applicable = [{"level": 1, "approver_type": "company_admin"}]
    # Iter 748 — REPORTING-CHAIN levels: resolve the actual approver from
    # the REQUESTER's org reporting chain (Org Hierarchy module) right now.
    # Unresolvable levels (chain not set for this employee) are skipped
    # with an audit note; if nothing remains, Company Admin fail-safe.
    chain_skips = []
    if any(lv.get("approver_type") == "reporting_chain" for lv in applicable):
        from routes.org_structure import resolve_approval_chain
        emp_doc = await db.users.find_one(
            {"user_id": requested_by.get("user_id")}, {"_id": 0}) or dict(requested_by)
        resolved = []
        for lv in applicable:
            if lv.get("approver_type") != "reporting_chain":
                resolved.append(lv)
                continue
            try:
                hit = await resolve_approval_chain(emp_doc, [lv.get("chain_role")])
            except Exception:
                hit = []
            if hit:
                lv["user_id"] = hit[0]["user_id"]
                lv["approver_name"] = hit[0].get("name")
                lv["role_name"] = (f"{lv.get('role_name') or 'Chain'}: "
                                   f"{hit[0].get('name') or hit[0]['user_id']}")
                resolved.append(lv)
            else:
                chain_skips.append(lv)
        applicable = resolved or [{"level": 1, "approver_type": "company_admin"}]
    for i, lv in enumerate(applicable, start=1):
        lv["level"] = i
    history = [{
        "level": 0, "action": "submitted",
        "by": requested_by.get("user_id"),
        "by_name": requested_by.get("name") or requested_by.get("email"),
        "remarks": None, "at": now_iso(),
    }]
    for lv in chain_skips:
        history.append({
            "level": 0, "action": "level_skipped",
            "by": "system", "by_name": "Reporting Chain",
            "remarks": (f"{lv.get('role_name') or lv.get('chain_role')} skipped — "
                        "employee ki reporting chain me ye role set nahi hai "
                        "(Org Hierarchy → Reporting Structure)"),
            "at": now_iso(),
        })
    for lv in skipped:
        history.append({
            "level": 0, "action": "level_skipped",
            "by": "system", "by_name": "Condition Engine",
            "remarks": (f"{lv.get('role_name') or 'Company Admin'} skipped — "
                        f"condition not met ({_cond_text(lv.get('condition') or {})})"),
            "at": now_iso(),
        })
    req = {
        "request_id": f"apr_{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "module": module,
        "record_id": record_id,
        "title": title,
        "summary": summary,
        "requested_by": requested_by.get("user_id"),
        "requested_by_name": requested_by.get("name") or requested_by.get("email"),
        "levels": applicable,
        "current_level": 1,
        "status": "pending",
        "level_since": now_iso(),
        "history": history,
        "created_at": now_iso(),
    }
    await db.approval_requests.insert_one(req)
    out = {k: v for k, v in req.items() if k != "_id"}
    # Phase C — notify firm admins per workflow notification rules.
    await _wf_notify(company_id, module, "created", out,
                     f"Requested by {out.get('requested_by_name') or '—'}")
    # Iter 749 — instant bell to the Level-1 personal approver (manager).
    await _notify_level_approver(out, 1)
    return out


async def _notify_level_approver(req: Dict[str, Any], level_no: int) -> None:
    """Iter 749 (user request) — bell alert to the PERSONAL approver
    (reporting-chain / direct-employee / delegate) the moment a request
    lands on their level. Never raises."""
    try:
        lv = next((x for x in (req.get("levels") or [])
                   if int(x.get("level") or 0) == int(level_no)), None)
        uid = (lv or {}).get("delegated_to") or (lv or {}).get("user_id")
        if not uid:
            return
        from utils.notify import emit as _emit
        await _emit(db, title="🔔 Approval needed",
                    message=(f"{req.get('title') or req.get('module')} — aapke "
                             f"approval ka intezaar hai (Level {level_no}"
                             + (f" · {lv.get('role_name')}" if lv.get("role_name") else "")
                             + ")"),
                    audience="user", target_user_id=uid,
                    company_id=req.get("company_id"),
                    category="leave" if req.get("module") == "leave" else "system",
                    priority="important", action_url="/approval-inbox",
                    reference_id=req.get("request_id"))
    except Exception:
        pass


async def _finalize(module: str, record_id: str, approved: bool, actor: dict,
                    final_status: Optional[str] = None):
    """Apply the final decision to the underlying record."""
    if module == "tour":
        # Iter 706 — Official Tour: approved / rejected / returned.
        from routes.tours import finalize_tour_approval
        await finalize_tour_approval(
            record_id, final_status or ("approved" if approved else "rejected"), actor)
        return
    if module == "leave":
        # Iter 713 — LEAVE wired into the engine: apply the final workflow
        # decision to the leave record + notify the employee.
        from routes.leaves import finalize_leave_workflow
        await finalize_leave_workflow(
            record_id, final_status or ("approved" if approved else "rejected"), actor)
        return
    if module == "advance":
        from routes.advances import _audit as adv_audit  # local import, no cycle at module load
        a = await db.advances.find_one({"advance_id": record_id}, {"_id": 0})
        if not a:
            return
        if approved:
            new_status = "scheduled" if (a.get("start_month") or "") > now_iso()[:7] else "active"
            detail = "Advance APPROVED via workflow"
        elif (final_status or "") == "returned":
            # Iter 713 (bug fix) — RETURN used to mark the advance REJECTED;
            # a returned advance stays editable for correction & resubmission.
            new_status = "returned"
            detail = "Advance RETURNED for correction via workflow"
        else:
            new_status = "rejected"
            detail = "Advance REJECTED via workflow"
        await db.advances.update_one(
            {"advance_id": record_id},
            {"$set": {"status": new_status, "updated_at": now_iso()},
             "$push": {"audit": adv_audit(actor.get("user_id") or "system", "approval", detail)}},
        )


# ---------------------------------------------------------------------------
# Workflow builder
# ---------------------------------------------------------------------------
@router.get("/approval-workflows")
async def list_workflows(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin, cid = await _admin_scoped(authorization, company_id)
    if admin.get("is_company_staff"):
        raise HTTPException(status_code=403, detail="Staff accounts cannot manage workflows")
    wfs = await db.approval_workflows.find({"company_id": cid}, {"_id": 0}).to_list(50)
    by_mod = {w["module"]: w for w in wfs}
    roles = await db.company_roles.find({"company_id": cid}, {"_id": 0}).sort("name", 1).to_list(100)
    return {
        "modules": MODULES,
        "workflows": by_mod,
        "roles": [{"role_id": r["role_id"], "name": r["name"]} for r in roles],
    }


class WorkflowSave(BaseModel):
    company_id: Optional[str] = None
    module: str
    enabled: bool = True
    levels: List[Dict[str, Any]] = []
    # Phase C — notification rules (dashboard bell to the requester /
    # firm admins). Keys: on_created, on_approved, on_rejected,
    # on_returned, on_escalated.
    notify: Optional[Dict[str, bool]] = None


@router.post("/approval-workflows")
async def save_workflow(payload: WorkflowSave, authorization: Optional[str] = Header(None)):
    admin, cid = await _admin_scoped(authorization, payload.company_id)
    if admin.get("is_company_staff"):
        raise HTTPException(status_code=403, detail="Staff accounts cannot manage workflows")
    if payload.module not in MODULE_KEYS:
        raise HTTPException(status_code=400, detail=f"module must be one of {sorted(MODULE_KEYS)}")
    levels = []
    for i, lv in enumerate(payload.levels or [], start=1):
        atype = lv.get("approver_type")
        if atype not in ("company_admin", "company_role", "employee",
                         "reporting_chain"):
            raise HTTPException(
                status_code=400,
                detail="approver_type must be company_admin|company_role|"
                       "employee|reporting_chain")
        entry: Dict[str, Any] = {"level": i, "approver_type": atype}
        if atype == "reporting_chain":
            # Iter 748 (user request) — approver resolved AT REQUEST TIME
            # from the requester's Org Reporting Chain (Org Hierarchy →
            # Reporting Structure). Same chain reused across modules.
            _CHAIN_LABELS = {
                "primary_manager": "Reporting Manager (chain)",
                "secondary_manager": "Functional Manager (chain)",
                "dept_head": "Dept Head (chain)",
                "hr_manager": "HR Manager (chain)",
                "final_approver": "Final Approver (chain)",
            }
            cr = lv.get("chain_role")
            if cr not in _CHAIN_LABELS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Level {i}: chain_role must be one of {sorted(_CHAIN_LABELS)}")
            entry["chain_role"] = cr
            entry["role_name"] = _CHAIN_LABELS[cr]
        if atype == "employee":
            # Iter 705 — directly-assigned employee approver.
            emp = await db.users.find_one(
                {"user_id": lv.get("user_id"), "company_id": cid},
                {"_id": 0, "user_id": 1, "name": 1, "email": 1, "employee_code": 1})
            if not emp:
                raise HTTPException(status_code=404,
                                    detail=f"Employee not found for level {i}")
            entry["user_id"] = emp["user_id"]
            entry["role_name"] = (emp.get("name") or emp.get("email") or "Employee") + (
                f" ({emp['employee_code']})" if emp.get("employee_code") else "")
        if atype == "company_role":
            role = await db.company_roles.find_one(
                {"role_id": lv.get("role_id"), "company_id": cid}, {"_id": 0})
            if not role:
                raise HTTPException(status_code=404, detail=f"Role not found for level {i}")
            entry["role_id"] = role["role_id"]
            entry["role_name"] = role["name"]
        # Phase B — optional per-level SLA (hours) + condition rule.
        try:
            sla = int(lv.get("sla_hours") or 0)
        except (TypeError, ValueError):
            sla = 0
        if sla > 0:
            entry["sla_hours"] = min(sla, 24 * 30)
        cond = lv.get("condition") or {}
        if str(cond.get("field") or "").strip():
            if cond.get("op") not in CONDITION_OPS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Level {i} condition op must be one of {CONDITION_OPS}")
            entry["condition"] = {
                "field": str(cond["field"]).strip(),
                "op": cond["op"],
                "value": cond.get("value"),
            }
        levels.append(entry)
    # Phase C — notification rules (defaults: all on when omitted).
    notify_defaults = {"on_created": True, "on_approved": True, "on_rejected": True,
                       "on_returned": True, "on_escalated": True}
    notify_cfg = {k: bool((payload.notify or {}).get(k, v)) for k, v in notify_defaults.items()}
    doc = {
        "company_id": cid, "module": payload.module,
        "enabled": bool(payload.enabled) and len(levels) > 0,
        "levels": levels,
        "notify": notify_cfg,
        "updated_at": now_iso(), "updated_by": admin["user_id"],
    }
    existing = await db.approval_workflows.find_one({"company_id": cid, "module": payload.module})
    if existing:
        # Phase C — versioning: snapshot the outgoing config before update.
        prev = {k: v for k, v in existing.items() if k != "_id"}
        version_no = int(existing.get("version") or 1)
        await db.workflow_versions.insert_one({
            "version_id": f"wfv_{uuid.uuid4().hex[:10]}",
            "company_id": cid, "module": payload.module,
            "version": version_no,
            "snapshot": prev,
            "saved_by": admin.get("user_id"), "saved_by_name": admin.get("name"),
            "saved_at": now_iso(),
        })
        doc["version"] = version_no + 1
        await db.approval_workflows.update_one({"_id": existing["_id"]}, {"$set": doc})
        doc["workflow_id"] = existing.get("workflow_id")
    else:
        doc["workflow_id"] = f"wf_{uuid.uuid4().hex[:12]}"
        doc["created_at"] = now_iso()
        doc["version"] = 1
        await db.approval_workflows.insert_one(dict(doc))
    from routes.access_management import write_access_audit
    await write_access_audit(
        admin, cid, "workflow_saved",
        f"Workflow '{payload.module}' saved — {len(levels)} level(s), "
        f"{'ENABLED' if doc['enabled'] else 'disabled'}")
    return {"ok": True, "workflow": {k: v for k, v in doc.items() if k != "_id"}}


# ---------------------------------------------------------------------------
# Iter 705 — employee picker for the workflow builder (direct approver).
# ---------------------------------------------------------------------------
@router.get("/approval-workflows/employee-search")
async def wf_employee_search(
    company_id: Optional[str] = Query(None),
    q: str = Query(""),
    authorization: Optional[str] = Header(None),
):
    admin, cid = await _admin_scoped(authorization, company_id)
    if admin.get("is_company_staff"):
        raise HTTPException(status_code=403, detail="Staff accounts cannot manage workflows")
    qq = (q or "").strip()
    if len(qq) < 2:
        return {"employees": []}
    rx = {"$regex": re.escape(qq), "$options": "i"}
    emps = await db.users.find(
        {"company_id": cid, "role": {"$in": ["employee", "company_staff"]},
         "$or": [{"name": rx}, {"employee_code": rx}, {"email": rx}]},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1},
    ).sort("name", 1).to_list(20)
    return {"employees": emps}


# ---------------------------------------------------------------------------
# Iter 705 — ESS badge: is this employee an assigned approver + pending count.
# ---------------------------------------------------------------------------
@router.get("/approval-inbox/badge")
async def approval_inbox_badge(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    if user.get("role") != "employee" or not user.get("company_id"):
        return {"is_approver": False, "pending": 0}
    me, cid = user["user_id"], user["company_id"]
    is_approver = await db.approval_workflows.count_documents(
        {"company_id": cid, "enabled": True, "levels.user_id": me}) > 0
    pending = await db.approval_requests.count_documents(
        {"company_id": cid, "status": {"$in": ["pending", "on_hold"]},
         "$or": [{"levels.user_id": me}, {"levels.delegated_to": me}]})
    return {"is_approver": bool(is_approver or pending), "pending": pending}


# ---------------------------------------------------------------------------
# Phase C — workflow versioning + notification helper
# ---------------------------------------------------------------------------
@router.get("/approval-workflows/{module}/versions")
async def workflow_versions(module: str, company_id: Optional[str] = Query(None),
                            authorization: Optional[str] = Header(None)):
    _admin, cid = await _admin_scoped(authorization, company_id)
    versions = await db.workflow_versions.find(
        {"company_id": cid, "module": module}, {"_id": 0}
    ).sort("version", -1).to_list(25)
    return {"versions": [
        {"version": v["version"], "saved_at": v.get("saved_at"),
         "saved_by_name": v.get("saved_by_name"),
         "enabled": (v.get("snapshot") or {}).get("enabled"),
         "levels": [
             {"level": l.get("level"),
              "role_name": l.get("role_name") or "Company Admin",
              "sla_hours": l.get("sla_hours"),
              "condition": l.get("condition")}
             for l in (v.get("snapshot") or {}).get("levels") or []],
         } for v in versions]}


@router.post("/approval-workflows/{module}/restore")
async def workflow_restore(module: str, payload: Dict[str, Any] = Body(...),
                           authorization: Optional[str] = Header(None)):
    admin, cid = await _admin_scoped(authorization, payload.get("company_id"))
    if admin.get("is_company_staff"):
        raise HTTPException(status_code=403, detail="Staff accounts cannot manage workflows")
    try:
        version = int(payload.get("version"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="version is required")
    v = await db.workflow_versions.find_one(
        {"company_id": cid, "module": module, "version": version}, {"_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    snap = v.get("snapshot") or {}
    # Restore goes through save so the current config is itself versioned.
    save_payload = WorkflowSave(
        company_id=cid, module=module, enabled=bool(snap.get("enabled")),
        levels=[{"approver_type": l.get("approver_type"), "role_id": l.get("role_id"),
                 "user_id": l.get("user_id"),
                 "sla_hours": l.get("sla_hours"), "condition": l.get("condition")}
                for l in snap.get("levels") or []],
        notify=snap.get("notify"))
    return await save_workflow(save_payload, authorization)


async def _wf_notify(company_id: str, module: str, event: str, req: dict,
                     extra: str = "") -> None:
    """Phase C — dashboard-bell notifications per workflow notify rules.
    on_created → firm admins; other events → the requester."""
    wf = await db.approval_workflows.find_one(
        {"company_id": company_id, "module": module},
        {"_id": 0, "notify": 1})
    rules = (wf or {}).get("notify") or {}
    if not rules.get(f"on_{event}", True):
        return
    titles = {
        "created": f"New approval request: {req.get('title')}",
        "approved": f"Approved ✅ — {req.get('title')}",
        "rejected": f"Rejected ✖ — {req.get('title')}",
        "returned": f"Returned ↩ — {req.get('title')}",
        "escalated": f"Escalated ⚡ — {req.get('title')}",
    }
    targets: List[str] = []
    if event == "created":
        async for u in db.users.find(
                {"company_id": company_id, "role": "company_admin"},
                {"_id": 0, "user_id": 1}).limit(10):
            targets.append(u["user_id"])
    elif req.get("requested_by"):
        targets.append(req["requested_by"])
    for uid in targets:
        try:
            await db.notifications.insert_one({
                "notification_id": f"n_{uuid.uuid4().hex[:10]}",
                "company_id": company_id,
                "audience": "user",
                "target_user_id": uid,
                "type": f"workflow.{module}.{event}",
                "title": titles.get(event, req.get("title")),
                "body": (extra or f"Module: {module}").strip(),
                "created_at": now_iso(),
            })
        except Exception:
            pass



# ---------------------------------------------------------------------------
# Approval inbox
# ---------------------------------------------------------------------------
@router.get("/approval-inbox")
async def approval_inbox(
    company_id: Optional[str] = Query(None),
    status: str = Query("pending"),
    authorization: Optional[str] = Header(None),
):
    # Iter 705 — employee approvers may open the inbox (scoped to requests
    # where they are an assigned approver / delegate / past actor).
    user = await get_user_from_token(authorization)
    mine_or: Optional[List[Dict[str, Any]]] = None
    if user.get("role") == "employee":
        if not user.get("company_id"):
            raise HTTPException(status_code=400, detail="No firm linked to your account")
        admin, cid = user, user["company_id"]
        mine_or = [{"levels.user_id": user["user_id"]},
                   {"levels.delegated_to": user["user_id"]},
                   {"history.by": user["user_id"]}]
    else:
        admin, cid = await _admin_scoped(authorization, company_id)
    # Phase B — lazy SLA auto-escalation before listing.
    escalated_now = await _auto_escalate_overdue(cid)
    q: Dict[str, Any] = {"company_id": cid}
    if mine_or:
        q["$or"] = mine_or
    if status and status != "all":
        q["status"] = "pending" if status == "on_hold" else status
        if status == "on_hold":
            q["status"] = "on_hold"
    reqs = await db.approval_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    out = []
    for r in reqs:
        cur = next((l for l in r.get("levels") or [] if l.get("level") == r.get("current_level")), None)
        r["pending_with"] = (
            (cur or {}).get("role_name") or "Company Admin"
        ) if r.get("status") in ("pending", "on_hold") else None
        r["can_action"] = (
            r.get("status") in ("pending", "on_hold")
            and cur is not None
            and _user_can_action_level(admin, cur)
            and r.get("requested_by") != admin.get("user_id")  # maker-checker
        )
        out.append(r)
    base: Dict[str, Any] = {"company_id": cid}
    if mine_or:
        base["$or"] = mine_or
    counts = {
        st: await db.approval_requests.count_documents({**base, "status": st})
        for st in ("pending", "on_hold", "approved", "rejected", "returned")
    }
    return {"requests": out, "counts": counts, "auto_escalated_now": escalated_now}


@router.post("/approval-requests/{request_id}/action")
async def action_request(
    request_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin", "employee"])
    r = await db.approval_requests.find_one({"request_id": request_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    if admin["role"] in ("company_admin", "employee") and admin.get("company_id") != r.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm")
    if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, r.get("company_id")):
        raise HTTPException(status_code=403, detail="Firm outside your scope")
    if r.get("status") not in ("pending", "on_hold"):
        raise HTTPException(status_code=400, detail="Request is already finalised")

    action = (payload.get("action") or "").strip()
    remarks = (payload.get("remarks") or "").strip() or None
    if action not in ("approve", "reject", "hold", "return", "delegate", "escalate"):
        raise HTTPException(status_code=400,
                            detail="action must be approve|reject|hold|return|delegate|escalate")

    cur = next((l for l in r.get("levels") or [] if l.get("level") == r.get("current_level")), None)
    if not cur or not _user_can_action_level(admin, cur):
        raise HTTPException(status_code=403, detail="You are not the approver for the current level")
    if r.get("requested_by") == admin.get("user_id"):
        raise HTTPException(status_code=403, detail="Maker-checker: you cannot approve your own request")
    if action in ("reject", "return") and not remarks:
        raise HTTPException(status_code=400, detail="Remarks are mandatory to reject or return")

    # Phase B — DELEGATE: hand the current level to another user in the firm.
    if action == "delegate":
        to_uid = str(payload.get("to_user_id") or "").strip()
        if not to_uid:
            raise HTTPException(status_code=400, detail="to_user_id is required to delegate")
        target = await db.users.find_one(
            {"user_id": to_uid, "company_id": r["company_id"]},
            {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1, "is_company_staff": 1})
        if not target or not (target.get("is_company_staff")
                              or target.get("role") in ("company_staff", "company_admin")):
            raise HTTPException(status_code=400, detail="Delegate target must be a staff user or admin of this firm")
        if to_uid == r.get("requested_by"):
            raise HTTPException(status_code=400, detail="Cannot delegate to the requester (maker-checker)")
        await db.approval_requests.update_one(
            {"request_id": request_id, "levels.level": r["current_level"]},
            {"$set": {"levels.$.delegated_to": to_uid,
                      "levels.$.delegated_to_name": target.get("name") or target.get("email"),
                      "updated_at": now_iso()},
             "$push": {"history": {
                 "level": r["current_level"], "action": "delegated",
                 "by": admin["user_id"], "by_name": admin.get("name") or admin.get("email"),
                 "remarks": f"Delegated to {target.get('name') or target.get('email')}"
                            + (f" — {remarks}" if remarks else ""),
                 "at": now_iso()}}})
        fresh = await db.approval_requests.find_one({"request_id": request_id}, {"_id": 0})
        # Iter 749 — bell the delegate so they know it's now on their desk.
        await _notify_level_approver(fresh, r["current_level"])
        return {"ok": True, "request": fresh}

    # Phase B — ESCALATE: jump to the next level immediately.
    if action == "escalate":
        n_levels = len(r.get("levels") or [])
        hist_e = {
            "level": r["current_level"], "action": "escalated",
            "by": admin["user_id"], "by_name": admin.get("name") or admin.get("email"),
            "remarks": remarks or "Escalated manually", "at": now_iso(),
        }
        upd_e: Dict[str, Any] = {"escalated": True, "updated_at": now_iso(), "level_since": now_iso()}
        if r["current_level"] < n_levels:
            upd_e["current_level"] = r["current_level"] + 1
        else:
            upd_e["sla_breached"] = True  # final level — flagged for the firm owner
        await db.approval_requests.update_one(
            {"request_id": request_id}, {"$set": upd_e, "$push": {"history": hist_e}})
        await _wf_notify(r["company_id"], r["module"], "escalated", r,
                         remarks or "Escalated manually")
        if upd_e.get("current_level"):
            # Iter 749 — bell the escalated-to level's personal approver.
            await _notify_level_approver(r, upd_e["current_level"])
        fresh = await db.approval_requests.find_one({"request_id": request_id}, {"_id": 0})
        return {"ok": True, "request": fresh}

    hist = {
        "level": r["current_level"], "action": action,
        "by": admin["user_id"],
        "by_name": (admin.get("staff_role_name") + " · " if admin.get("is_company_staff") else "") + (admin.get("name") or admin.get("email") or ""),
        "remarks": remarks, "at": now_iso(),
    }
    updates: Dict[str, Any] = {}
    if action == "hold":
        updates["status"] = "on_hold"
    elif action == "return":
        updates["status"] = "returned"
    elif action == "reject":
        updates["status"] = "rejected"
    else:  # approve
        n_levels = len(r.get("levels") or [])
        if r["current_level"] >= n_levels:
            updates["status"] = "approved"
        else:
            updates["status"] = "pending"
            updates["current_level"] = r["current_level"] + 1
            updates["level_since"] = now_iso()  # Phase B — SLA clock restarts
    updates["updated_at"] = now_iso()
    await db.approval_requests.update_one(
        {"request_id": request_id}, {"$set": updates, "$push": {"history": hist}})

    if updates.get("status") in ("approved", "rejected", "returned"):
        await _finalize(r["module"], r["record_id"],
                        approved=updates["status"] == "approved", actor=admin,
                        final_status=updates["status"])
        # Phase C — notify the requester per workflow notification rules.
        await _wf_notify(r["company_id"], r["module"], updates["status"], r,
                         remarks or "")
    elif updates.get("current_level"):
        # Iter 749 — request advanced: bell the NEXT level's personal approver.
        await _notify_level_approver(r, updates["current_level"])

    fresh = await db.approval_requests.find_one({"request_id": request_id}, {"_id": 0})
    return {"ok": True, "request": fresh}
