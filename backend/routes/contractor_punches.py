"""Iter 175 — Contractor Punch approvals (daily, contractor-wise).

Contractual employees' punches land as ``status=pending`` (see
``apply_contractual_gate``). This module powers the daily report grouped
by contractor where the company approves/rejects each employee's day and
may re-assign the contractor for that individual day. Once approved the
punches flow into the normal attendance-policy computation.

Endpoints:
  * GET  /api/admin/contractor-punches?company_id&date=YYYY-MM-DD
  * POST /api/admin/contractor-punches/decide
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import db, get_user_from_token, require_role, now_iso  # noqa: E402

router = APIRouter(prefix="/api/admin/contractor-punches", tags=["contractor-punches"])


async def _auth(authorization: Optional[str], company_id: str):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    if admin.get("role") != "super_admin" and admin.get("company_id") != company_id:
        if admin.get("role") == "sub_admin":
            from server import sub_admin_can_touch_company
            if sub_admin_can_touch_company(admin, company_id):
                return admin
        raise HTTPException(status_code=403, detail="Not authorised for this firm")
    return admin


def _hhmm(iso: str) -> str:
    try:
        return iso[11:16]
    except Exception:
        return ""


@router.get("")
async def contractor_punch_report(
    company_id: str = Query(...),
    date: str = Query(..., description="YYYY-MM-DD"),
    authorization: Optional[str] = Header(None),
):
    await _auth(authorization, company_id)

    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "contractors": 1, "settings": 1})
    contractors = [
        (c.get("name") or "").strip()
        for c in (fm or {}).get("contractors", []) if (c.get("name") or "").strip()
    ]

    emps = await db.users.find(
        {"company_id": company_id, "is_contractual": True},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "contractor_name": 1},
    ).to_list(3000)
    by_uid = {e["user_id"]: e for e in emps}

    rows_by_uid: Dict[str, List[dict]] = {}
    if by_uid:
        async for r in db.attendance.find(
            {"company_id": company_id, "date": date,
             "user_id": {"$in": list(by_uid)}, "kind": {"$in": ["in", "out"]}},
            {"_id": 0, "record_id": 1, "user_id": 1, "kind": 1, "at": 1,
             "status": 1, "contractor_name": 1, "source": 1},
        ).sort("at", 1):
            rows_by_uid.setdefault(r["user_id"], []).append(r)

    groups: Dict[str, List[dict]] = {}
    summary = {"pending": 0, "approved": 0, "rejected": 0}
    for uid, recs in rows_by_uid.items():
        emp = by_uid[uid]
        # Effective contractor for THIS day: record-level override wins.
        day_contractor = next(
            (r.get("contractor_name") for r in reversed(recs) if r.get("contractor_name")),
            None,
        ) or emp.get("contractor_name") or "Unassigned"
        statuses = {r.get("status") or "approved" for r in recs}
        if "pending" in statuses:
            day_status = "pending"
        elif statuses == {"rejected"}:
            day_status = "rejected"
        elif "rejected" in statuses:
            day_status = "mixed"
        else:
            day_status = "approved"
        if day_status in summary:
            summary[day_status] += 1
        ins = [r for r in recs if r["kind"] == "in"]
        outs = [r for r in recs if r["kind"] == "out"]
        groups.setdefault(day_contractor, []).append({
            "user_id": uid,
            "name": emp.get("name"),
            "employee_code": emp.get("employee_code"),
            "contractor_name": day_contractor,
            "in_hhmm": _hhmm(ins[0]["at"]) if ins else None,
            "out_hhmm": _hhmm(outs[-1]["at"]) if outs else None,
            "punch_count": len(recs),
            "status": day_status,
            "record_ids": [r["record_id"] for r in recs],
        })

    group_list = [
        {"contractor": c, "rows": sorted(v, key=lambda x: (x.get("name") or "").lower())}
        for c, v in sorted(groups.items(), key=lambda kv: kv[0].lower())
    ]
    return {
        "date": date,
        "contractors": contractors,
        "contractual_employees": len(emps),
        "groups": group_list,
        "summary": summary,
    }


@router.post("/decide")
async def decide_contractor_day(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    company_id = str(payload.get("company_id") or "").strip()
    admin = await _auth(authorization, company_id)
    user_id = str(payload.get("user_id") or "").strip()
    date = str(payload.get("date") or "").strip()
    action = str(payload.get("action") or "").strip().lower()
    contractor_name = (payload.get("contractor_name") or "").strip() or None
    if not user_id or not date:
        raise HTTPException(status_code=400, detail="user_id and date are required")
    if action and action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be approve or reject")

    q = {"company_id": company_id, "user_id": user_id,
         "date": date, "kind": {"$in": ["in", "out"]}}
    sets: Dict[str, Any] = {}
    if contractor_name is not None:
        # "change Contractor Name for individual day" — record-level override.
        sets["contractor_name"] = contractor_name
    if action:
        sets.update({
            "status": "approved" if action == "approve" else "rejected",
            "decision_by": admin["user_id"],
            "decision_at": now_iso(),
            "decision_reason": (
                "Contractor punch approved by company" if action == "approve"
                else "Contractor punch rejected by company"),
        })
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.attendance.update_many(q, {"$set": sets})
    return {"ok": True, "updated": res.modified_count}
