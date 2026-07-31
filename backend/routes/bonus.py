"""Iter 409 — STATUTORY BONUS module (extracted from server.py).

Refactor only: every endpoint, model and helper below was MOVED verbatim
from server.py — firm Bonus Policy GET/PUT, bonus run preview / create /
list / get and the XLSX report (Payment of Bonus Act, 1965 — Iter 59).
No behavioural change. ``_compute_bonus_run`` is re-exported through
server.py because routes/statutory_registers.py imports it from there.
"""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from server import (  # noqa: E402
    _resolve_group_employee_ids,
    db,
    get_user_from_token,
    now_iso,
    require_role,
    require_super_admin_strict,
)

router = APIRouter(prefix="/api")
api = router  # endpoints below keep their original @api.* decorators


# ---------------------------------------------------------------------------
# Statutory Bonus Calculation — Iter 59
# ---------------------------------------------------------------------------
# Payment of Bonus Act, 1965 (Indian labour law):
#   • Eligibility: employees whose Basic+DA ≤ eligibility_cap (default ₹21,000)
#   • Bonus payable = rate% × min(actual Basic+DA, wage_ceiling) × months_worked
#   • Statutory min rate 8.33 %, max 20 %
#   • Wage ceiling default ₹7,000 (or state minimum wage, whichever is higher)
#   • Applied per Financial Year (Apr → Mar in India), must be paid within 8
#     months of FY close.
#
# Rules are stored per-firm at companies.bonus_policy so they can be updated
# any time and re-processed. Runs are stored in `bonus_runs`.


def _fy_bounds(fy_start_year: int) -> tuple[str, str]:
    """Return ('YYYY-04-01', 'YYYY+1-03-31') for a given FY start year."""
    return f"{fy_start_year:04d}-04-01", f"{fy_start_year + 1:04d}-03-31"


def _default_bonus_policy() -> Dict[str, Any]:
    return {
        "rate_percent": 8.33,        # statutory minimum
        "wage_ceiling": 7000.0,      # ₹7,000 per month
        "eligibility_cap": 21000.0,  # employees earning ≤ this Basic+DA are eligible
        "basic_percent_of_gross": 50.0,  # if we only have gross, take 50% as basic (labour code)
        "min_months_worked": 1,      # must have worked at least 1 month in FY
    }


class BonusPolicyPayload(BaseModel):
    rate_percent: Optional[float] = None
    wage_ceiling: Optional[float] = None
    eligibility_cap: Optional[float] = None
    basic_percent_of_gross: Optional[float] = None
    min_months_worked: Optional[int] = None
    notes: Optional[str] = None


@api.get("/admin/companies/{company_id}/bonus-policy")
async def get_bonus_policy(
    company_id: str, authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorised")
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "bonus_policy": 1, "name": 1})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    policy = {**_default_bonus_policy(), **(company.get("bonus_policy") or {})}
    return {"company_id": company_id, "name": company.get("name"), "policy": policy}


@api.put("/admin/companies/{company_id}/bonus-policy")
async def set_bonus_policy(
    company_id: str,
    payload: BonusPolicyPayload,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "company_id": 1})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    existing = (await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "bonus_policy": 1}
    )) or {}
    policy = {**_default_bonus_policy(), **(existing.get("bonus_policy") or {})}
    for k, v in payload.dict().items():
        if v is not None:
            policy[k] = v
    # Enforce statutory bounds
    if policy["rate_percent"] < 8.33:
        policy["rate_percent"] = 8.33
    if policy["rate_percent"] > 20.0:
        policy["rate_percent"] = 20.0
    policy["updated_at"] = now_iso()
    policy["updated_by"] = admin["user_id"]
    await db.companies.update_one(
        {"company_id": company_id}, {"$set": {"bonus_policy": policy}}
    )
    return {"ok": True, "policy": policy}


class BonusRunRequest(BaseModel):
    company_id: str
    fy_start_year: int          # e.g. 2025 → FY 2025-26 (Apr 2025 – Mar 2026)
    group_id: Optional[str] = None


async def _compute_bonus_run(
    company_id: str, fy_start_year: int, group_id: Optional[str], admin: dict,
) -> Dict[str, Any]:
    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "name": 1, "bonus_policy": 1}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    policy = {**_default_bonus_policy(), **(company.get("bonus_policy") or {})}

    date_from, date_to = _fy_bounds(fy_start_year)
    fy_label = f"{fy_start_year}-{str(fy_start_year + 1)[-2:]}"

    query: Dict[str, Any] = {"role": "employee", "company_id": company_id}
    grp_uids = await _resolve_group_employee_ids(company_id, group_id)
    grp_name = ""
    if grp_uids is not None:
        query["user_id"] = {"$in": grp_uids}
        grp = await db.masters.find_one(
            {"master_id": group_id, "type": "group"}, {"_id": 0, "name": 1}
        )
        grp_name = (grp or {}).get("name") or ""

    employees = await db.users.find(
        query,
        {
            "_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
            "doj": 1, "exit_date": 1,
            "salary_monthly": 1, "basic_salary": 1,
            "salary_mode": 1, "salary_structure_actual": 1,
        },
    ).to_list(5000)

    rows: List[Dict[str, Any]] = []
    from datetime import date as _date

    def _parse_date(s: str) -> Optional[_date]:
        if not s:
            return None
        try:
            return _date.fromisoformat(s[:10])
        except Exception:
            return None

    fy_start = _date.fromisoformat(date_from)
    fy_end = _date.fromisoformat(date_to)

    for e in employees:
        doj = _parse_date(e.get("doj") or "")
        exit_d = _parse_date(e.get("exit_date") or "")

        # Effective months worked inside the FY window
        eff_start = max(doj, fy_start) if doj else fy_start
        eff_end = min(exit_d, fy_end) if exit_d else fy_end
        if eff_start > eff_end:
            continue
        months_worked = (
            (eff_end.year - eff_start.year) * 12
            + (eff_end.month - eff_start.month)
            + 1
        )
        months_worked = max(0, min(12, months_worked))
        if months_worked < int(policy.get("min_months_worked") or 1):
            continue

        gross = float(e.get("salary_monthly") or 0)
        basic = float(e.get("basic_salary") or 0)
        # Iter 95 — resolve the Basic rate from salary_structure_actual
        # (same priority as the salary grids). Daily / hourly rates are
        # converted to a monthly equivalent (× 26 days / × 8h × 26 days)
        # so bonus math works for Kankani-style daily-rated workers.
        _mode = str(e.get("salary_mode") or "monthly").lower()
        for _r in (e.get("salary_structure_actual") or []):
            if isinstance(_r, dict) and str(_r.get("head", "")).strip().lower().startswith("basic"):
                if float(_r.get("amount") or 0) > 0:
                    basic = float(_r.get("amount") or 0)
                    _rt = str(_r.get("rate_type") or "").strip().lower()
                    if _rt in ("monthly", "daily", "hourly"):
                        _mode = _rt
                break
        if _mode == "daily":
            basic = round(basic * 26.0, 2)
        elif _mode == "hourly":
            basic = round(basic * 8.0 * 26.0, 2)
        if gross <= 0 and basic > 0:
            gross = basic
        if basic <= 0 and gross > 0:
            basic = round(gross * float(policy.get("basic_percent_of_gross") or 50.0) / 100.0, 2)

        eligibility_cap = float(policy.get("eligibility_cap") or 21000.0)
        wage_ceiling = float(policy.get("wage_ceiling") or 7000.0)
        rate = float(policy.get("rate_percent") or 8.33)

        # Not eligible if Basic+DA exceeds cap (we treat basic == Basic+DA proxy)
        eligible = basic <= eligibility_cap
        bonus_wage_base = min(basic, wage_ceiling)
        bonus_amount = round(bonus_wage_base * (rate / 100.0) * months_worked, 2) if eligible else 0.0

        rows.append({
            "user_id": e.get("user_id"),
            "employee_code": e.get("employee_code") or "",
            "name": e.get("name") or "",
            "doj": e.get("doj") or "",
            "exit_date": e.get("exit_date") or "",
            "gross_monthly": gross,
            "basic_monthly": basic,
            "months_worked": months_worked,
            "eligible": eligible,
            "wage_base_used": bonus_wage_base,
            "rate_percent": rate,
            "bonus_amount": bonus_amount,
        })

    total_bonus = round(sum(r["bonus_amount"] for r in rows), 2)
    eligible_count = sum(1 for r in rows if r["eligible"])

    return {
        "company_id": company_id,
        "company_name": company.get("name"),
        "fy_start_year": fy_start_year,
        "fy_label": fy_label,
        "date_from": date_from,
        "date_to": date_to,
        "group_id": group_id or None,
        "group_name": grp_name or None,
        "policy_used": policy,
        "rows": rows,
        "total_employees": len(rows),
        "eligible_count": eligible_count,
        "total_bonus": total_bonus,
    }


@api.post("/admin/bonus-runs/preview")
async def preview_bonus_run(
    payload: BonusRunRequest, authorization: Optional[str] = Header(None),
):
    """Compute bonus for a company + FY without persisting."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    return await _compute_bonus_run(
        payload.company_id, payload.fy_start_year, payload.group_id, admin
    )


@api.post("/admin/bonus-runs")
async def create_bonus_run(
    payload: BonusRunRequest, authorization: Optional[str] = Header(None),
):
    """Compute + persist a bonus run so it can be referenced/downloaded later."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    result = await _compute_bonus_run(
        payload.company_id, payload.fy_start_year, payload.group_id, admin
    )
    run_id = f"br_{uuid.uuid4().hex[:12]}"
    doc = {
        "run_id": run_id,
        "created_at": now_iso(),
        "created_by": admin["user_id"],
        **result,
    }
    await db.bonus_runs.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.get("/admin/bonus-runs")
async def list_bonus_runs(
    company_id: Optional[str] = None,
    company_ids: Optional[List[str]] = Query(
        None, description="Cross-firm filter. Ignored for company_admin."
    ),
    fy_start_year: Optional[int] = None,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    q: Dict[str, Any] = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif company_ids:
        cleaned = [c for c in company_ids if c]
        if cleaned:
            q["company_id"] = {"$in": cleaned}
    elif company_id:
        q["company_id"] = company_id
    if fy_start_year is not None:
        q["fy_start_year"] = int(fy_start_year)
    items = await db.bonus_runs.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    # Strip rows for listing view
    for it in items:
        it.pop("rows", None)
    return {"items": items}


@api.get("/admin/bonus-runs/{run_id}")
async def get_bonus_run(run_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    run = await db.bonus_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Bonus run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised")
    return run


@api.get("/admin/bonus-runs/{run_id}/report.xlsx")
async def download_bonus_report(
    run_id: str, authorization: Optional[str] = Header(None),
):
    """Download the Bonus Report as XLSX."""
    from fastapi.responses import Response
    from openpyxl import Workbook
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    run = await db.bonus_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Bonus run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised")

    wb = Workbook()
    ws = wb.active
    ws.title = f"Bonus {run.get('fy_label') or ''}"[:30] or "Bonus"

    ws.append([f"Statutory Bonus — {run.get('company_name') or ''}"])
    ws.append([f"Financial Year: FY {run.get('fy_label') or ''}"])
    ws.append([f"Period: {run.get('date_from')} → {run.get('date_to')}"])
    if run.get("group_name"):
        ws.append([f"Employee Group: {run.get('group_name')}"])
    policy = run.get("policy_used") or {}
    ws.append([
        f"Rate {policy.get('rate_percent')}%  ·  Wage ceiling ₹{policy.get('wage_ceiling')}  ·  Eligibility cap ₹{policy.get('eligibility_cap')}"
    ])
    ws.append([])

    headers = [
        "Emp Code", "Name", "DOJ", "Exit Date",
        "Gross (Monthly)", "Basic (Monthly)", "Months Worked",
        "Eligible", "Wage Base Used", "Rate %", "Bonus (₹)",
    ]
    ws.append(headers)
    for r in run.get("rows") or []:
        ws.append([
            r.get("employee_code"), r.get("name"),
            r.get("doj"), r.get("exit_date"),
            r.get("gross_monthly"), r.get("basic_monthly"),
            r.get("months_worked"),
            "Yes" if r.get("eligible") else "No",
            r.get("wage_base_used"), r.get("rate_percent"),
            r.get("bonus_amount"),
        ])
    ws.append([])
    ws.append([
        "TOTAL", "", "", "", "", "", "", "",
        "", "", run.get("total_bonus") or 0,
    ])

    # Column widths
    widths = [12, 26, 12, 12, 14, 14, 14, 10, 14, 10, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

    import io as _io
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"BonusReport_{(run.get('company_name') or 'company').replace(' ', '_')}_FY{run.get('fy_label')}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
