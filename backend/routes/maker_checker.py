"""Iter 587 — RBAC Phase 3: MAKER-CHECKER APPROVAL WORKFLOW.

Critical changes are STAGED (never applied directly) when made by a
non-super-admin, and require a different authorized CHECKER to approve:

  * salary_change    — PATCH /admin/employees/{id}/salary
  * bank_change      — PATCH /admin/employees/{id}/kyc (bank fields)
  * employee_delete  — DELETE /admin/employees/{id}

Rules (user spec):
  - Original data remains UNCHANGED until explicitly approved.
  - Maker can NEVER approve their own request (may reject/withdraw it).
  - Old vs new values are stored on the request for side-by-side review.
  - Every request/decision is audit-logged + email-alerted (best effort).
  - Super Admin actions apply directly (top authority, single-admin org).

Endpoints:
  GET  /api/admin/maker-checker/settings
  PUT  /api/admin/maker-checker/settings              (super admin)
  GET  /api/admin/approvals?status=&company_id=
  GET  /api/admin/approvals/{approval_id}
  POST /api/admin/approvals/{approval_id}/decide      {decision, reason}
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    logger,
)
from shared.authz import (  # noqa: E402
    SENSITIVE_KEYS,
    _mask,
    can_view_sensitive,
    firm_ok,
    has_permission,
)

router = APIRouter(prefix="/api/admin", tags=["maker-checker"])

MC_ACTIONS = ("salary_change", "bank_change", "employee_delete", "bulk_salary_change")
MC_LABELS = {"salary_change": "Salary Change", "bank_change": "Bank Details Change",
             "employee_delete": "Employee Deletion",
             "bulk_salary_change": "Bulk Salary Change"}
# Iter 588 — AI risk engine: risk level per action (drives UI chips and
# documents why approval is required).
MC_RISK = {"salary_change": "HIGH", "bank_change": "HIGH",
           "employee_delete": "CRITICAL", "bulk_salary_change": "CRITICAL"}
# Actions only the Super Admin may approve (4-eyes + top-authority rule).
MC_SUPER_ONLY = ("employee_delete", "bulk_salary_change")
_DEFAULTS = {"enabled": True,
             "actions": {a: True for a in MC_ACTIONS}}
# Daily digest of stale PENDING requests (>24h) — emailed at 09:00 IST.
_DIGEST_DEFAULT = True
_DIGEST_HOUR_IST = 9
_DIGEST_MIN_AGE_HOURS = 24


async def get_mc_settings() -> Dict[str, Any]:
    doc = await db.maker_checker_settings.find_one({"_id_key": "singleton"}, {"_id": 0}) or {}
    actions = {**_DEFAULTS["actions"], **(doc.get("actions") or {})}
    return {"enabled": bool(doc.get("enabled", _DEFAULTS["enabled"])), "actions": actions,
            "digest_enabled": bool(doc.get("digest_enabled", _DIGEST_DEFAULT)),
            "updated_at": doc.get("updated_at"), "updated_by": doc.get("updated_by")}


async def mc_action_enabled(action_type: str) -> bool:
    s = await get_mc_settings()
    return s["enabled"] and bool(s["actions"].get(action_type))


async def _audit(user: dict, action: str, detail: Dict[str, Any],
                 severity: str = "INFO") -> None:
    try:
        await db.activity_log.insert_one({
            "log_id": f"al_{uuid.uuid4().hex[:12]}",
            "user_id": user.get("user_id"), "user_name": user.get("name"),
            "role": user.get("role"), "action": action,
            "module": "maker_checker", "severity": severity, "detail": detail,
            "at": datetime.now(timezone.utc).isoformat()})
    except Exception:
        pass


async def _email_alert(subject: str, body: str) -> None:
    try:
        from server import _try_send_admin_email
        await _try_send_admin_email(subject, body)
    except Exception:
        logger.exception("[maker-checker] email alert failed")


async def stage_if_required(admin: dict, *, action_type: str, module: str,
                            emp: dict, old_values: Dict[str, Any],
                            new_values: Dict[str, Any],
                            apply_spec: Dict[str, Any],
                            notes: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Stage a critical change into the pending-approvals queue.

    Returns None when the caller should APPLY DIRECTLY (super admin, or the
    maker-checker toggle for this action is OFF). Otherwise inserts a
    PENDING approval (deduped per target+action) and returns its summary —
    the caller must NOT modify the original data.
    """
    if admin.get("role") == "super_admin":
        return None
    if not await mc_action_enabled(action_type):
        return None
    existing = await db.pending_approvals.find_one(
        {"action_type": action_type, "target_user_id": emp.get("user_id"),
         "status": "PENDING"}, {"_id": 0, "approval_id": 1})
    if existing:
        return {"approval_id": existing["approval_id"],
                "message": (f"A {MC_LABELS[action_type]} request for this employee is "
                            "already pending approval. No data was changed.")}
    approval_id = f"APR-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:8].upper()}"
    await db.pending_approvals.insert_one({
        "approval_id": approval_id,
        "action_type": action_type,
        "action_label": MC_LABELS[action_type],
        "module": module,
        "company_id": emp.get("company_id"),
        "target_user_id": emp.get("user_id"),
        "target_name": emp.get("name"),
        "target_code": emp.get("employee_code"),
        "maker_id": admin.get("user_id"),
        "maker_name": admin.get("name") or admin.get("email"),
        "maker_role": admin.get("role"),
        "status": "PENDING",
        "old_values": old_values,
        "new_values": new_values,
        "apply_spec": apply_spec,
        "notes": notes,
        "created_at": now_iso(),
    })
    await _audit(admin, "APPROVAL_REQUESTED",
                 {"approval_id": approval_id, "action_type": action_type,
                  "target_user_id": emp.get("user_id"),
                  "target_name": emp.get("name"),
                  "fields": list(new_values.keys())})  # field NAMES only
    await _email_alert(
        f"[Approval Required] {MC_LABELS[action_type]} — {emp.get('name') or emp.get('user_id')}",
        (f"{admin.get('name') or admin.get('email')} ({admin.get('role')}) requested a "
         f"{MC_LABELS[action_type]} for employee {emp.get('name')} "
         f"(code {emp.get('employee_code') or '—'}).\n"
         f"Approval ID: {approval_id}\nFields: {', '.join(new_values.keys())}\n\n"
         "Review it in Admin → Pending Approvals. Nothing is applied until approved."))
    logger.info("[maker-checker] %s staged %s for %s", admin.get("user_id"),
                action_type, emp.get("user_id"))
    return {"approval_id": approval_id,
            "message": (f"{MC_LABELS[action_type]} sent for approval "
                        f"({approval_id}). The original data stays UNCHANGED "
                        "until an authorized approver approves it.")}


# ── Apply-on-approve handlers ───────────────────────────────────────────────
async def _apply_salary(appr: dict, checker: dict) -> Dict[str, Any]:
    uid = appr["target_user_id"]
    emp = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if not emp:
        return {"note": "Employee no longer exists"}
    to_set = dict(appr["apply_spec"].get("to_set") or {})
    to_set["salary_updated_at"] = now_iso()
    keys = [k for k in to_set if k not in ("salary_updated_at", "salary_updated_by")]
    await db.salary_history.insert_one({
        "user_id": uid, "company_id": emp.get("company_id"),
        "changed_at": now_iso(),
        "changed_by": appr["maker_id"], "changed_by_role": appr.get("maker_role"),
        "approved_by": checker["user_id"], "approval_id": appr["approval_id"],
        "notes": appr.get("notes"),
        "prev": {k: emp.get(k) for k in keys},
        "next": {k: to_set.get(k) for k in keys},
    })
    await db.users.update_one({"user_id": uid}, {"$set": to_set})
    return {"applied_fields": keys}


async def _apply_bank(appr: dict, checker: dict) -> Dict[str, Any]:
    uid = appr["target_user_id"]
    emp = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if not emp:
        return {"note": "Employee no longer exists"}
    to_set = dict(appr["apply_spec"].get("to_set") or {})
    to_set["kyc_updated_at"] = now_iso()
    keys = [k for k in to_set if k not in ("kyc_updated_at", "kyc_updated_by")]
    await db.kyc_history.insert_one({
        "user_id": uid, "company_id": emp.get("company_id"),
        "changed_at": now_iso(),
        "changed_by": appr["maker_id"], "changed_by_role": appr.get("maker_role"),
        "approved_by": checker["user_id"], "approval_id": appr["approval_id"],
        "source": appr["apply_spec"].get("source") or "maker_checker",
        "prev": {k: emp.get(k) for k in keys},
        "next": {k: to_set.get(k) for k in keys},
    })
    await db.users.update_one({"user_id": uid}, {"$set": to_set})
    try:
        from shared.attendance_eligibility import auto_release_if_complete
        await auto_release_if_complete(db, uid)
    except Exception:
        pass
    return {"applied_fields": keys}


async def _apply_delete(appr: dict, checker: dict) -> Dict[str, Any]:
    from routes.employees_admin import delete_employee_record
    return await delete_employee_record(
        appr["target_user_id"],
        actor=f"approval:{checker.get('email') or checker['user_id']}")


async def _apply_bulk_salary(appr: dict, checker: dict) -> Dict[str, Any]:
    from routes.ai_bulk_actions import execute_bulk_salary
    preview = await db.ai_bulk_previews.find_one(
        {"preview_id": appr["apply_spec"].get("preview_id")}, {"_id": 0})
    if not preview:
        return {"note": "Preview no longer exists — nothing applied"}
    return await execute_bulk_salary(preview, checker["user_id"],
                                     approval_id=appr["approval_id"])


_APPLY = {"salary_change": _apply_salary, "bank_change": _apply_bank,
          "employee_delete": _apply_delete,
          "bulk_salary_change": _apply_bulk_salary}


# ── Daily overdue-approvals digest (user request) ───────────────────────────
async def send_pending_digest(min_age_hours: int = _DIGEST_MIN_AGE_HOURS) -> Dict[str, Any]:
    """Email approvers a digest of PENDING requests older than 24h so
    nothing sits in the queue unnoticed. Skips the email when there are
    none. Sensitive values are never included — metadata only."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=min_age_hours)).isoformat()
    stale = await db.pending_approvals.find(
        {"status": "PENDING", "created_at": {"$lte": cutoff}},
        {"_id": 0, "approval_id": 1, "action_label": 1, "target_name": 1,
         "target_code": 1, "maker_name": 1, "maker_role": 1,
         "company_id": 1, "created_at": 1},
    ).sort("created_at", 1).to_list(100)
    if not stale:
        return {"sent": False, "stale_count": 0,
                "note": f"No PENDING requests older than {min_age_hours}h"}
    now = datetime.now(timezone.utc)
    lines = []
    for a in stale:
        try:
            age_h = int((now - datetime.fromisoformat(
                str(a["created_at"]).replace("Z", "+00:00"))).total_seconds() // 3600)
        except Exception:
            age_h = min_age_hours
        age = f"{age_h // 24}d {age_h % 24}h" if age_h >= 24 else f"{age_h}h"
        lines.append(
            f"• {a.get('action_label')} — {a.get('target_name') or '—'}"
            f"{' (' + a['target_code'] + ')' if a.get('target_code') else ''}"
            f" | by {a.get('maker_name')} ({a.get('maker_role')})"
            f" | waiting {age} | {a.get('approval_id')}")
    body = (f"{len(stale)} approval request(s) have been PENDING for more than "
            f"{min_age_hours} hours:\n\n" + "\n".join(lines) +
            "\n\nReview them in Administration → Pending Approvals. "
            "Nothing is applied until approved; rejected requests leave the "
            "original data unchanged.")
    await _email_alert(
        f"⏰ Pending Approvals Digest — {len(stale)} request(s) waiting > {min_age_hours}h",
        body)
    logger.info("[maker-checker] digest sent — %d stale requests", len(stale))
    return {"sent": True, "stale_count": len(stale)}


async def digest_loop():
    """Daily at 09:00 IST — one hour after the audit summary."""
    import asyncio
    from datetime import timedelta
    while True:
        try:
            now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
            nxt = now_ist.replace(hour=_DIGEST_HOUR_IST, minute=0, second=0, microsecond=0)
            if nxt <= now_ist:
                nxt += timedelta(days=1)
            await asyncio.sleep((nxt - now_ist).total_seconds())
            st = await get_mc_settings()
            if st["enabled"] and st["digest_enabled"]:
                await send_pending_digest()
        except Exception:
            logger.warning("[maker-checker] digest loop error", exc_info=True)
            import asyncio as _a
            await _a.sleep(3600)


@router.post("/maker-checker/send-digest-now")
async def send_digest_now(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    return await send_pending_digest()


# ── Endpoints ───────────────────────────────────────────────────────────────
@router.get("/maker-checker/settings")
async def read_settings(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    return {"settings": await get_mc_settings(), "actions": list(MC_ACTIONS),
            "labels": MC_LABELS}


@router.put("/maker-checker/settings")
async def write_settings(payload: Dict[str, Any] = Body(...),
                         authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    cur = await get_mc_settings()
    enabled = bool(payload.get("enabled", cur["enabled"]))
    digest_enabled = bool(payload.get("digest_enabled", cur["digest_enabled"]))
    actions = dict(cur["actions"])
    for a, v in (payload.get("actions") or {}).items():
        if a in MC_ACTIONS:
            actions[a] = bool(v)
    await db.maker_checker_settings.update_one(
        {"_id_key": "singleton"},
        {"$set": {"enabled": enabled, "actions": actions,
                  "digest_enabled": digest_enabled,
                  "updated_at": now_iso(), "updated_by": admin["user_id"]}},
        upsert=True)
    await _audit(admin, "MAKER_CHECKER_SETTINGS_CHANGED",
                 {"enabled": enabled, "actions": actions,
                  "digest_enabled": digest_enabled})
    return {"ok": True, "settings": await get_mc_settings()}


def _mask_values(user: dict, values: Dict[str, Any]) -> Dict[str, Any]:
    if can_view_sensitive(user):
        return values
    return {k: (_mask(v, SENSITIVE_KEYS[k]) if k in SENSITIVE_KEYS and v else v)
            for k, v in (values or {}).items()}


def _serialise(user: dict, appr: dict, full: bool = False) -> Dict[str, Any]:
    out = {k: v for k, v in appr.items() if k not in ("_id", "apply_spec")}
    out["risk"] = MC_RISK.get(appr.get("action_type"), "MEDIUM")
    out["old_values"] = _mask_values(user, appr.get("old_values") or {})
    out["new_values"] = _mask_values(user, appr.get("new_values") or {})
    if not full:
        out.pop("result", None)
    return out


@router.get("/approvals")
async def list_approvals(status: Optional[str] = None,
                         company_id: Optional[str] = None,
                         authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status.upper()
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif company_id:
        if not firm_ok(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm outside your scope")
        q["company_id"] = company_id
    items = await db.pending_approvals.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(200)
    if admin["role"] == "sub_admin":
        items = [a for a in items if firm_ok(admin, a.get("company_id"))]
    # Scoped pending count (drives the header badge).
    scope_q: Dict[str, Any] = {k: v for k, v in q.items() if k != "status"}
    if (admin["role"] == "sub_admin"
            and admin.get("sub_admin_company_scope") == "restricted"):
        scope_q["company_id"] = {"$in": admin.get("sub_admin_company_ids") or []}
    pending = await db.pending_approvals.count_documents(
        {**scope_q, "status": "PENDING"})
    return {"approvals": [_serialise(admin, a) for a in items],
            "pending_count": pending}


@router.get("/approvals/{approval_id}")
async def approval_detail(approval_id: str,
                          authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    appr = await db.pending_approvals.find_one({"approval_id": approval_id}, {"_id": 0})
    if not appr:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if not firm_ok(admin, appr.get("company_id")):
        raise HTTPException(status_code=403, detail="Firm outside your scope")
    return {"approval": _serialise(admin, appr, full=True)}


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(approval_id: str,
                          payload: Dict[str, Any] = Body(...),
                          authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    decision = str(payload.get("decision") or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")
    reason = (payload.get("reason") or "").strip() or None
    appr = await db.pending_approvals.find_one({"approval_id": approval_id}, {"_id": 0})
    if not appr:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if appr.get("status") != "PENDING":
        raise HTTPException(status_code=409, detail=f"Request is already {appr.get('status')}")

    is_maker = admin["user_id"] == appr.get("maker_id")
    if decision == "approve":
        # 4-eyes principle — the maker can NEVER approve their own request.
        if is_maker:
            raise HTTPException(status_code=403,
                                detail="Maker cannot approve their own request (4-eyes rule)")
        if admin["role"] != "super_admin":
            if appr["action_type"] in MC_SUPER_ONLY:
                raise HTTPException(status_code=403,
                                    detail=f"{MC_LABELS[appr['action_type']]} can only be approved by the Super Admin")
            if not firm_ok(admin, appr.get("company_id")):
                raise HTTPException(status_code=403, detail="Firm outside your scope")
            if not has_permission(admin, appr.get("module") or "employees", "approve"):
                raise HTTPException(status_code=403,
                                    detail=f"You lack {appr.get('module')}:approve permission")
    else:
        # Reject: any authorized approver, OR the maker withdrawing their own.
        if not is_maker and admin["role"] != "super_admin":
            if not firm_ok(admin, appr.get("company_id")):
                raise HTTPException(status_code=403, detail="Firm outside your scope")
            if not has_permission(admin, appr.get("module") or "employees", "approve"):
                raise HTTPException(status_code=403,
                                    detail=f"You lack {appr.get('module')}:approve permission")

    result: Dict[str, Any] = {}
    if decision == "approve":
        result = await _APPLY[appr["action_type"]](appr, admin)
    new_status = "APPROVED" if decision == "approve" else "REJECTED"
    await db.pending_approvals.update_one(
        {"approval_id": approval_id},
        {"$set": {"status": new_status, "checker_id": admin["user_id"],
                  "checker_name": admin.get("name") or admin.get("email"),
                  "checker_role": admin["role"], "decided_at": now_iso(),
                  "decision_reason": reason, "result": result}})
    await _audit(admin, f"APPROVAL_{new_status}",
                 {"approval_id": approval_id, "action_type": appr["action_type"],
                  "target_user_id": appr.get("target_user_id"),
                  "target_name": appr.get("target_name"),
                  "maker_id": appr.get("maker_id"), "reason": reason},
                 severity="CRITICAL" if appr["action_type"] == "employee_delete" else "INFO")
    await _email_alert(
        f"[Approval {new_status}] {appr.get('action_label')} — {appr.get('target_name')}",
        (f"{admin.get('name') or admin.get('email')} ({admin['role']}) {new_status} "
         f"request {approval_id} ({appr.get('action_label')}) for "
         f"{appr.get('target_name')} raised by {appr.get('maker_name')}."
         + (f"\nReason: {reason}" if reason else "")
         + ("\nThe change has been APPLIED." if new_status == "APPROVED"
            else "\nNothing was changed — original data stays the same.")))
    logger.info("[maker-checker] %s %s by %s", approval_id, new_status, admin["user_id"])
    return {"ok": True, "status": new_status, "result": result}
