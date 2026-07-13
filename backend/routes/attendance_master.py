"""Iter 100 — Attendance Master (Super Admin + Sub Super Admins ONLY).

A compliance-oriented worksheet per firm + month:
  PF No / UAN / ESIC No / Emp ID / Name / Father / Designation / DOJ /
  Compliance salary breakdown (Basic, HRA, Conv + allowances, Total) /
  Present Days (manual) / Other deductions (head + amount, manual) /
  Gross Earning (pro-rated by present days).

Manual entries persist in ``attendance_master_entries`` keyed by
(company_id, month, user_id).
"""
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
)
from utils.compliance_salary import resolve_structure, _num  # noqa: E402

router = APIRouter(prefix="/api", tags=["attendance-master"])


def _code_key(r):
    c = str(r.get("employee_code") or "").strip()
    try:
        return (0, float(c), "")
    except ValueError:
        return (1, 0.0, c.lower())


@router.get("/admin/attendance-master")
async def attendance_master(
    company_id: str = Query(...),
    month: str = Query(...),          # YYYY-MM
    month_days: int = Query(26),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])

    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "compliance_policy": 1, "structure_pct": 1},
    )
    if not company:
        raise HTTPException(status_code=404, detail="Firm not found")
    structure_pct = (
        (company.get("compliance_policy") or {}).get("structure_pct")
        or company.get("structure_pct")
        or None
    )

    entries: dict = {}
    async for e in db.attendance_master_entries.find(
        {"company_id": company_id, "month": month}, {"_id": 0},
    ):
        entries[e["user_id"]] = e

    rows = []
    async for u in db.users.find(
        {"role": "employee", "company_id": company_id},
        {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1, "father_name": 1,
         "designation": 1, "doj": 1, "pf_no": 1, "uan_no": 1, "esi_ip_no": 1,
         "compliance_gross": 1, "salary_monthly": 1, "compliance_salary_mode": 1,
         "basic_amount": 1, "hra_amount": 1, "conv_amount": 1, "medical_amount": 1,
         "special_amount": 1, "others_amount": 1, "structure_pct": 1,
         "compliance_allowances": 1, "is_onroll": 1},
    ):
        total = _num(u.get("compliance_gross") or u.get("salary_monthly"), 0.0)
        structure = resolve_structure(u, total, structure_pct)
        mode = (u.get("compliance_salary_mode") or "monthly").lower()
        ent = entries.get(u["user_id"]) or {}
        present = _num(ent.get("present_days"), 0.0)
        ded_amt = _num(ent.get("deduction_amount"), 0.0)
        if mode == "daily":
            gross = total * present
        else:
            gross = (total * present) / max(1, month_days)
        rows.append({
            "user_id": u["user_id"],
            "pf_no": u.get("pf_no"),
            "uan_no": u.get("uan_no"),
            "esic_no": u.get("esi_ip_no"),
            "employee_code": u.get("employee_code"),
            "name": u.get("name"),
            "father_name": u.get("father_name"),
            "designation": u.get("designation"),
            "doj": u.get("doj"),
            "salary_mode": mode,
            "basic": round(structure["basic"], 2),
            "hra": round(structure["hra"], 2),
            "conveyance": round(structure["conveyance"], 2),
            "medical": round(structure["medical"], 2),
            "special": round(structure["special"], 2),
            "others": round(structure["others"], 2),
            "total_salary": round(total, 2),
            "present_days": present,
            "deduction_head": ent.get("deduction_head") or "",
            "deduction_amount": ded_amt,
            "gross_earning": round(gross, 2),
        })

    rows.sort(key=_code_key)
    return {
        "company_id": company_id,
        "company_name": company.get("name"),
        "month": month,
        "month_days": month_days,
        "rows": rows,
        "employees_count": len(rows),
    }


@router.patch("/admin/attendance-master")
async def save_attendance_master(
    payload: dict,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    company_id = payload.get("company_id")
    month = payload.get("month")
    entries = payload.get("entries") or []
    if not company_id or not month:
        raise HTTPException(status_code=400, detail="company_id and month are required")
    saved = 0
    for e in entries:
        uid = e.get("user_id")
        if not uid:
            continue
        await db.attendance_master_entries.update_one(
            {"company_id": company_id, "month": month, "user_id": uid},
            {"$set": {
                "company_id": company_id,
                "month": month,
                "user_id": uid,
                "present_days": _num(e.get("present_days"), 0.0),
                "deduction_head": (e.get("deduction_head") or "").strip(),
                "deduction_amount": _num(e.get("deduction_amount"), 0.0),
                "updated_at": now_iso(),
                "updated_by": admin["user_id"],
            }},
            upsert=True,
        )
        saved += 1
    return {"ok": True, "saved": saved}
