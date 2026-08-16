"""Iter 589 — AI BULK-ACTION ENGINE (spec §16: bulk action protection).

"Increase salary of all employees in Production department by 5%" must
NEVER execute automatically. Flow:

  AI parses → PREVIEW (server-side authz + computed impact) →
  Super Admin: [Confirm & Execute]   ·   Others: [Send for Approval]
  → Maker-Checker (CRITICAL risk, Super-Admin-only approval) → execute
  → salary_history rows per employee + CRITICAL audit log.

Endpoints:
  POST /api/admin/ai-bulk/salary/preview  {company_id, department?, pct?|amount?}
  POST /api/admin/ai-bulk/salary/execute  {preview_id}
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import db, get_user_from_token, require_role, now_iso, logger  # noqa: E402
from shared.authz import authorize  # noqa: E402

router = APIRouter(prefix="/api/admin/ai-bulk", tags=["ai-bulk"])

_PREVIEW_TTL_MIN = 30
_MAX_EMPLOYEES = 500


async def build_bulk_salary_preview(admin: dict, company_id: str,
                                    department: Optional[str] = None,
                                    pct: Optional[float] = None,
                                    amount: Optional[float] = None) -> Dict[str, Any]:
    """Compute + stage a bulk salary change preview. Nothing is modified."""
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    if pct is None and amount is None:
        raise HTTPException(status_code=400, detail="Provide pct or amount")
    # Central authorization — firm scope + salary edit permission.
    authorize(admin, "salary_process", "edit", company_id=company_id)

    q: Dict[str, Any] = {"role": "employee", "company_id": company_id,
                         "active": {"$ne": False},
                         "employment_status": {"$ne": "resigned"},
                         "salary_monthly": {"$gt": 0}}
    if department:
        q["department"] = {"$regex": f"^{department.strip()}$", "$options": "i"}
    emps = await db.users.find(
        q, {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
            "salary_monthly": 1, "department": 1}).limit(_MAX_EMPLOYEES).to_list(_MAX_EMPLOYEES)
    if not emps:
        raise HTTPException(status_code=404,
                            detail=("No active employees with a salary found"
                                    + (f" in department '{department}'" if department else "")
                                    + " for this firm"))
    rows, cur_total, new_total = [], 0.0, 0.0
    for e in emps:
        old = float(e["salary_monthly"])
        new = round(old * (1 + pct / 100.0)) if pct is not None else round(old + amount)
        if new < 0:
            new = 0
        rows.append({"user_id": e["user_id"], "name": e.get("name"),
                     "employee_code": e.get("employee_code"),
                     "old": old, "new": float(new)})
        cur_total += old
        new_total += new
    firm = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "name": 1})
    preview_id = f"BLK-{uuid.uuid4().hex[:10].upper()}"
    change_label = (f"{'+' if pct >= 0 else ''}{pct}%" if pct is not None
                    else f"{'+' if amount >= 0 else ''}₹{amount:,.0f}")
    doc = {
        "preview_id": preview_id, "kind": "bulk_salary_change",
        "company_id": company_id, "firm_name": (firm or {}).get("name"),
        "department": department, "pct": pct, "amount": amount,
        "change_label": change_label,
        "rows": rows, "employees_affected": len(rows),
        "current_payroll": round(cur_total, 2),
        "new_payroll": round(new_total, 2),
        "difference": round(new_total - cur_total, 2),
        "status": "PREVIEW",
        "created_by": admin["user_id"], "created_by_name": admin.get("name"),
        "created_at": now_iso(),
        "expires_at": (datetime.now(timezone.utc)
                       + timedelta(minutes=_PREVIEW_TTL_MIN)).isoformat(),
    }
    await db.ai_bulk_previews.insert_one(dict(doc))
    doc.pop("rows")
    doc["sample"] = [f"{r['name']} ({r['employee_code'] or '—'}): ₹{r['old']:,.0f} → ₹{r['new']:,.0f}"
                     for r in rows[:5]]
    return doc


async def build_bulk_undo_preview(admin: dict,
                                  bulk_id: Optional[str] = None) -> Dict[str, Any]:
    """Build an UNDO preview for an executed bulk change — restores each
    affected employee to their pre-bulk salary. Employees whose salary was
    changed AGAIN after the bulk (current != bulk 'new') are skipped so we
    never overwrite a newer deliberate change. Nothing is modified here."""
    from shared.authz import firm_ok
    q: Dict[str, Any] = {"kind": "bulk_salary_change", "status": "EXECUTED"}
    if bulk_id:
        q["preview_id"] = bulk_id
    source = None
    async for cand in db.ai_bulk_previews.find(q, {"_id": 0}).sort("executed_at", -1).limit(20):
        if firm_ok(admin, cand.get("company_id")):
            source = cand
            break
    if not source:
        raise HTTPException(status_code=404,
                            detail=("That bulk change was not found or is outside your scope"
                                    if bulk_id else "No executed bulk change found to undo"))
    authorize(admin, "salary_process", "edit", company_id=source["company_id"])

    rows, skipped, cur_total, new_total = [], 0, 0.0, 0.0
    for r in source.get("rows") or []:
        emp = await db.users.find_one({"user_id": r["user_id"]},
                                      {"_id": 0, "salary_monthly": 1, "name": 1,
                                       "employee_code": 1})
        if not emp:
            skipped += 1
            continue
        cur = float(emp.get("salary_monthly") or 0)
        if cur != float(r["new"]):
            skipped += 1  # changed again since the bulk — leave it alone
            continue
        rows.append({"user_id": r["user_id"], "name": emp.get("name") or r.get("name"),
                     "employee_code": emp.get("employee_code") or r.get("employee_code"),
                     "old": cur, "new": float(r["old"])})
        cur_total += cur
        new_total += float(r["old"])
    if not rows:
        raise HTTPException(status_code=409,
                            detail=("Nothing to undo — every affected salary was "
                                    "changed again after that bulk change"))
    preview_id = f"BLK-{uuid.uuid4().hex[:10].upper()}"
    doc = {
        "preview_id": preview_id, "kind": "bulk_salary_undo",
        "source_bulk_id": source["preview_id"],
        "company_id": source["company_id"], "firm_name": source.get("firm_name"),
        "department": source.get("department"),
        "change_label": f"UNDO of {source['preview_id']} ({source.get('change_label')})",
        "rows": rows, "employees_affected": len(rows), "skipped": skipped,
        "current_payroll": round(cur_total, 2),
        "new_payroll": round(new_total, 2),
        "difference": round(new_total - cur_total, 2),
        "status": "PREVIEW",
        "created_by": admin["user_id"], "created_by_name": admin.get("name"),
        "created_at": now_iso(),
        "expires_at": (datetime.now(timezone.utc)
                       + timedelta(minutes=_PREVIEW_TTL_MIN)).isoformat(),
    }
    await db.ai_bulk_previews.insert_one(dict(doc))
    doc.pop("rows")
    doc["sample"] = [f"{r['name']} ({r['employee_code'] or '—'}): ₹{r['old']:,.0f} → ₹{r['new']:,.0f}"
                     for r in rows[:5]]
    return doc


async def execute_bulk_salary(preview: dict, actor_id: str,
                              approval_id: Optional[str] = None) -> Dict[str, Any]:
    """Apply a previewed bulk change — one salary_history row per employee,
    CRITICAL audit log. Idempotent via preview status flag."""
    if preview.get("status") == "EXECUTED":
        return {"note": "Already executed", "employees_affected": preview.get("employees_affected")}
    changed = 0
    for r in preview.get("rows") or []:
        res = await db.users.update_one(
            {"user_id": r["user_id"], "salary_monthly": r["old"]},
            {"$set": {"salary_monthly": r["new"], "salary_updated_at": now_iso(),
                      "salary_updated_by": actor_id}})
        if res.modified_count:
            changed += 1
            await db.salary_history.insert_one({
                "user_id": r["user_id"], "company_id": preview["company_id"],
                "changed_at": now_iso(), "changed_by": preview["created_by"],
                "approved_by": actor_id if approval_id else None,
                "approval_id": approval_id, "bulk_id": preview["preview_id"],
                "notes": f"Bulk change {preview.get('change_label')}"
                         + (f" — dept {preview['department']}" if preview.get("department") else ""),
                "prev": {"salary_monthly": r["old"]},
                "next": {"salary_monthly": r["new"]},
            })
    await db.ai_bulk_previews.update_one(
        {"preview_id": preview["preview_id"]},
        {"$set": {"status": "EXECUTED", "executed_at": now_iso(),
                  "executed_by": actor_id, "employees_changed": changed}})
    # An executed UNDO retires its source bulk so it can't be undone twice.
    if preview.get("kind") == "bulk_salary_undo" and preview.get("source_bulk_id"):
        await db.ai_bulk_previews.update_one(
            {"preview_id": preview["source_bulk_id"]},
            {"$set": {"status": "UNDONE", "undone_by": preview["preview_id"],
                      "undone_at": now_iso()}})
    try:
        await db.activity_log.insert_one({
            "log_id": f"al_{uuid.uuid4().hex[:12]}",
            "user_id": actor_id, "action": "BULK_SALARY_CHANGE",
            "module": "ai_bulk", "severity": "CRITICAL",
            "detail": {"preview_id": preview["preview_id"],
                       "company_id": preview["company_id"],
                       "department": preview.get("department"),
                       "change": preview.get("change_label"),
                       "employees_affected": preview.get("employees_affected"),
                       "employees_changed": changed,
                       "payroll_before": preview.get("current_payroll"),
                       "payroll_after": preview.get("new_payroll"),
                       "requested_by": preview.get("created_by"),
                       "approval_id": approval_id},
            "at": now_iso()})
    except Exception:
        pass
    logger.info("[ai-bulk] %s executed by %s — %d/%d employees changed",
                preview["preview_id"], actor_id, changed,
                preview.get("employees_affected") or 0)
    return {"employees_changed": changed,
            "payroll_after": preview.get("new_payroll")}


@router.post("/salary/preview")
async def bulk_salary_preview(payload: Dict[str, Any] = Body(...),
                              authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    pct = payload.get("pct")
    amount = payload.get("amount")
    return {"ok": True, "preview": await build_bulk_salary_preview(
        admin, payload.get("company_id"), payload.get("department"),
        pct=float(pct) if pct is not None else None,
        amount=float(amount) if amount is not None else None)}


@router.post("/salary/undo-preview")
async def bulk_salary_undo_preview(payload: Dict[str, Any] = Body(default={}),
                                   authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    return {"ok": True, "preview": await build_bulk_undo_preview(
        admin, payload.get("bulk_id"))}


@router.post("/salary/execute")
async def bulk_salary_execute(payload: Dict[str, Any] = Body(...),
                              authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    preview = await db.ai_bulk_previews.find_one(
        {"preview_id": payload.get("preview_id")}, {"_id": 0})
    if not preview:
        raise HTTPException(status_code=404, detail="Preview not found — generate it again")
    if preview["status"] not in ("PREVIEW",):
        raise HTTPException(status_code=409, detail=f"Preview is already {preview['status']}")
    if preview["created_by"] != admin["user_id"] and admin["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="Only the requester can execute this preview")
    if preview.get("expires_at") and preview["expires_at"] < datetime.now(timezone.utc).isoformat():
        raise HTTPException(status_code=410, detail="Preview expired — generate it again")
    # Re-validate authorization at execute time (permissions may have changed).
    authorize(admin, "salary_process", "edit", company_id=preview["company_id"])

    if admin["role"] != "super_admin":
        # CRITICAL risk — stage for Super Admin approval (Maker-Checker).
        from routes.maker_checker import stage_if_required
        staged = await stage_if_required(
            admin, action_type="bulk_salary_change", module="salary_process",
            emp={"user_id": f"BULK:{preview['preview_id']}",
                 "name": (f"{preview['employees_affected']} employees"
                          + (f" — {preview['department']}" if preview.get("department") else "")
                          + f" ({preview.get('firm_name') or preview['company_id']})"),
                 "employee_code": None, "company_id": preview["company_id"]},
            old_values={"payroll_total": preview["current_payroll"],
                        "employees_affected": preview["employees_affected"]},
            new_values={"payroll_total": preview["new_payroll"],
                        "change": preview["change_label"],
                        "difference": preview["difference"]},
            apply_spec={"kind": "bulk_salary", "preview_id": preview["preview_id"]},
            notes=f"Bulk salary change {preview['change_label']}")
        if staged:
            await db.ai_bulk_previews.update_one(
                {"preview_id": preview["preview_id"]},
                {"$set": {"status": "STAGED", "approval_id": staged["approval_id"],
                          # keep the preview alive until the checker decides
                          "expires_at": None}})
            return {"ok": True, "approval_required": True, **staged}

    result = await execute_bulk_salary(preview, admin["user_id"])
    return {"ok": True, "executed": True, **result}
