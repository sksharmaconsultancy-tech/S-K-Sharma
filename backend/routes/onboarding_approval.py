"""Iter 285 — Employee Onboarding Approval Workflow (Phase 1).

Firm-level policy + Pending Employee Approval dashboard:

  companies.onboarding_approval  (settings dict, defaults in DEFAULT_CFG)
  users.onboarding_status        (None/active | pending_approval | hold |
                                  rejected | approved)
  onboarding_audit               (every approve / reject / hold decision)

Flow: when the firm policy is ENABLED, admin-created employees start as
``pending_approval``. Their logins/punches are gated by the policy
toggles, attendance is stored but the employee is EXCLUDED from salary /
compliance runs (hooks live in server.py) until HR approves. Approving
releases everything automatically.

Approver rights: if a Workflow Builder chain exists for the
``employee_creation`` module, only its eligible approvers (plus
super/sub-admin and the firm owner) may decide; otherwise any
company_admin / super_admin / sub_admin can.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    sub_admin_can_touch_company,
)
from routes.approvals_engine import _user_can_action_level  # noqa: E402

router = APIRouter(prefix="/api", tags=["onboarding-approval"])

DEFAULT_CFG: Dict[str, Any] = {
    "enabled": False,
    "require_hr_approval": True,
    "allow_punch": True,            # punching allowed before approval
    "store_attendance": True,       # hold punches (saved, not payrolled)
    "allow_mobile_login": True,
    "allow_web_login": True,
    "allow_face": True,
    "allow_biometric": True,
    "allow_geo": True,
    "allow_salary": False,
    "allow_leave": False,
    "allow_ot": False,
    "allow_pf": False,
    "allow_esic": False,
    "allow_tds": False,
    "auto_activate": True,
    "approval_expiry_days": 0,      # 0 = unlimited; 1 / 3 / 7
}

PENDING_STATUSES = ["pending_approval", "hold", "rejected"]


async def _scoped_admin(authorization: Optional[str], company_id: Optional[str]):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    elif admin["role"] == "sub_admin" and company_id and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm outside your scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return admin, company_id


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@router.get("/admin/companies/{company_id}/onboarding-approval")
async def get_onboarding_settings(company_id: str, authorization: Optional[str] = Header(None)):
    _admin, cid = await _scoped_admin(authorization, company_id)
    company = await db.companies.find_one({"company_id": cid}, {"_id": 0, "onboarding_approval": 1, "name": 1})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    cfg = {**DEFAULT_CFG, **(company.get("onboarding_approval") or {})}
    return {"company_id": cid, "settings": cfg}


@router.put("/admin/companies/{company_id}/onboarding-approval")
async def put_onboarding_settings(
    company_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin, cid = await _scoped_admin(authorization, company_id)
    cfg: Dict[str, Any] = {}
    for k, default in DEFAULT_CFG.items():
        v = payload.get(k, default)
        if k == "approval_expiry_days":
            try:
                v = int(v or 0)
            except (TypeError, ValueError):
                v = 0
            if v not in (0, 1, 3, 7):
                v = 0
        else:
            v = bool(v)
        cfg[k] = v
    r = await db.companies.update_one(
        {"company_id": cid},
        {"$set": {"onboarding_approval": cfg, "onboarding_approval_updated_at": now_iso(),
                  "onboarding_approval_updated_by": admin["user_id"]}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    await db.onboarding_audit.insert_one({
        "audit_id": f"oba_{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "action": "settings_updated",
        "settings": cfg,
        "by": admin["user_id"],
        "by_name": admin.get("name"),
        "at": now_iso(),
    })
    return {"ok": True, "settings": cfg}


# ---------------------------------------------------------------------------
# Pending Employee Approval dashboard
# ---------------------------------------------------------------------------
def _expiry_state(cfg: Dict[str, Any], pending_since: Optional[str]) -> Dict[str, Any]:
    days = int(cfg.get("approval_expiry_days") or 0)
    if not days or not pending_since:
        return {"expired": False, "expires_at": None}
    try:
        since = datetime.fromisoformat(str(pending_since).replace("Z", "+00:00"))
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    except ValueError:
        return {"expired": False, "expires_at": None}
    exp = since + timedelta(days=days)
    return {"expired": datetime.now(timezone.utc) > exp, "expires_at": exp.isoformat()}


@router.get("/admin/onboarding-approvals")
async def list_onboarding_approvals(
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    _admin, cid = await _scoped_admin(authorization, company_id)
    company = await db.companies.find_one({"company_id": cid}, {"_id": 0, "onboarding_approval": 1})
    cfg = {**DEFAULT_CFG, **((company or {}).get("onboarding_approval") or {})}

    emps = await db.users.find(
        {"company_id": cid, "role": "employee",
         "onboarding_status": {"$in": PENDING_STATUSES}},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "department": 1,
         "designation": 1, "doj": 1, "phone": 1, "email": 1,
         "shift_name": 1, "shift_start": 1, "shift_end": 1,
         "aadhaar_no": 1, "pan_no": 1, "uan_no": 1, "esic_no": 1,
         "bank_account_no": 1, "bank_name": 1, "ifsc": 1,
         "onboarding_status": 1, "onboarding_pending_since": 1,
         "onboarding_remarks": 1, "onboarding_decided_at": 1,
         "onboarding_decided_by_name": 1},
    ).to_list(500)

    uids = [e["user_id"] for e in emps]
    # Today's punches (IST calendar date, same convention as attendance).
    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).strftime("%Y-%m-%d")
    punches_by_uid: Dict[str, list] = {}
    if uids:
        async for p in db.attendance.find(
            {"user_id": {"$in": uids}, "date": today},
            {"_id": 0, "user_id": 1, "kind": 1, "at": 1, "source": 1},
        ).sort("at", 1):
            punches_by_uid.setdefault(p["user_id"], []).append(p)

    docs_by_uid: Dict[str, dict] = {}
    if uids:
        async for d in db.employee_documents.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "doc_id": 1, "category": 1},
        ):
            slot = docs_by_uid.setdefault(d["user_id"], {"photo_doc_id": None, "categories": []})
            slot["categories"].append(d.get("category"))
            if d.get("category") == "photo" and not slot["photo_doc_id"]:
                slot["photo_doc_id"] = d["doc_id"]

    def _hhmm(iso: Optional[str]) -> Optional[str]:
        if not iso:
            return None
        try:
            dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(ist).strftime("%H:%M")
        except ValueError:
            return None

    rows = []
    for e in emps:
        pl = punches_by_uid.get(e["user_id"]) or []
        dd = docs_by_uid.get(e["user_id"]) or {"photo_doc_id": None, "categories": []}
        rows.append({
            **e,
            "first_punch": _hhmm(pl[0]["at"]) if pl else None,
            "last_punch": _hhmm(pl[-1]["at"]) if len(pl) > 1 else None,
            "punch_source": (pl[-1].get("source") if pl else None),
            "punch_count_today": len(pl),
            "photo_doc_id": dd["photo_doc_id"],
            "doc_categories": sorted(set(c for c in dd["categories"] if c)),
            "has_aadhaar": bool(e.get("aadhaar_no")) or "aadhaar" in dd["categories"],
            "has_pan": bool(e.get("pan_no")) or "pan" in dd["categories"],
            "has_bank": bool(e.get("bank_account_no") or e.get("ifsc")) or "bank" in dd["categories"],
            "has_uan": bool(e.get("uan_no")),
            "has_esic": bool(e.get("esic_no")),
            **_expiry_state(cfg, e.get("onboarding_pending_since")),
        })
    rows.sort(key=lambda r: r.get("onboarding_pending_since") or "")
    return {"company_id": cid, "settings": cfg, "employees": rows}


@router.post("/admin/onboarding-approvals/{user_id}/decide")
async def decide_onboarding(
    user_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    action = str(payload.get("action") or "").strip().lower()
    if action not in ("approve", "reject", "hold"):
        raise HTTPException(status_code=400, detail="action must be approve, reject or hold")
    remarks = str(payload.get("remarks") or "").strip()

    emp = await db.users.find_one({"user_id": user_id, "role": "employee"}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    admin, cid = await _scoped_admin(authorization, emp.get("company_id"))

    # Workflow Builder integration — 'Employee Creation' module chain (if
    # enabled) defines who may decide.
    wf = await db.approval_workflows.find_one(
        {"company_id": cid, "module": "employee_creation", "enabled": True}, {"_id": 0})
    if wf:
        levels = wf.get("levels") or []
        if levels and not any(_user_can_action_level(admin, lvl) for lvl in levels):
            raise HTTPException(
                status_code=403,
                detail="You are not an approver in this firm's Employee Creation workflow.")

    company = await db.companies.find_one({"company_id": cid}, {"_id": 0, "onboarding_approval": 1, "name": 1})
    cfg = {**DEFAULT_CFG, **((company or {}).get("onboarding_approval") or {})}

    prev = emp.get("onboarding_status")
    if action == "approve":
        new_status = "active" if cfg.get("auto_activate", True) else "approved"
    elif action == "reject":
        new_status = "rejected"
    else:
        new_status = "hold"

    upd = {
        "onboarding_status": new_status,
        "onboarding_decided_at": now_iso(),
        "onboarding_decided_by": admin["user_id"],
        "onboarding_decided_by_name": admin.get("name"),
        "onboarding_remarks": remarks or None,
    }
    await db.users.update_one({"user_id": user_id}, {"$set": upd})

    await db.onboarding_audit.insert_one({
        "audit_id": f"oba_{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "user_id": user_id,
        "employee_name": emp.get("name"),
        "employee_code": emp.get("employee_code"),
        "action": action,
        "old_status": prev,
        "new_status": new_status,
        "remarks": remarks or None,
        "by": admin["user_id"],
        "by_name": admin.get("name"),
        "by_role": admin.get("role"),
        "at": now_iso(),
    })

    # Notify the employee on their dashboard bell.
    titles = {
        "approve": "Registration approved 🎉",
        "reject": "Registration rejected",
        "hold": "Registration on hold",
    }
    bodies = {
        "approve": "HR approved your registration — your attendance is now live for payroll.",
        "reject": f"Your registration was rejected.{(' Reason: ' + remarks) if remarks else ''} Contact HR.",
        "hold": f"Your registration is on hold.{(' Reason: ' + remarks) if remarks else ''}",
    }
    await db.notifications.insert_one({
        "notification_id": f"n_{uuid.uuid4().hex[:10]}",
        "company_id": cid,
        "audience": "user",
        "target_user_id": user_id,
        "type": f"onboarding.{action}",
        "title": titles[action],
        "body": bodies[action],
        "created_at": now_iso(),
        "created_by": admin["user_id"],
    })
    return {"ok": True, "user_id": user_id, "onboarding_status": new_status}


@router.get("/admin/onboarding-approvals/audit")
async def onboarding_audit(
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    _admin, cid = await _scoped_admin(authorization, company_id)
    logs = await db.onboarding_audit.find(
        {"company_id": cid}, {"_id": 0}).sort("at", -1).to_list(200)
    return {"logs": logs}
