"""Iter 730 — HR Extras (user request, 3 modules):

1. GATE PASS — personal gate pass inserts an approved OUT→IN punch pair
   (source ``gate_pass``) so the existing pairing engine naturally deducts
   the away-time from that day's duty hours. Official passes are recorded
   only (no deduction). Collection ``gate_passes``.

2. LATE PENALTY AUTO — firm-level config (free lates/month + how many
   chargeable lates equal a half-day cut) + monthly report computed from
   the SAME attendance grid (late_min per day cell). "Apply" stamps the
   penalty into the current DRAFT compliance salary run's Other Deduction
   with a manual_fields stamp (the Iter 297/374 keep-rules preserve it on
   Reprocess, which then refreshes the net).

3. F&F CALCULATOR — single-employee Full & Final settlement: earned
   salary of the exit month (grid present days), gratuity (15/26 rule),
   leave encashment / bonus / notice recovery inputs, outstanding advance
   auto-recovery — with a downloadable settlement-sheet PDF.
"""
import calendar
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    now_iso,
    sub_admin_can_touch_company,
    invalidate_grid_cache,
    _compute_monthly_grid_data,
)
from routes.statutory_extra_reports import (  # noqa: E402
    _emit, _company, _master_gross, _num, _service_years, _parse_doj,
)

router = APIRouter(prefix="/api", tags=["hr-extras"])


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


# ═══════════════════════ 1. GATE PASS ═══════════════════════

@router.post("/admin/gate-pass")
async def create_gate_pass(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin, company_id = await _authz(authorization, payload.get("company_id"))
    user_id = payload.get("user_id")
    date = str(payload.get("date") or "")[:10]
    out_t = str(payload.get("out_time") or "").strip()
    in_t = str(payload.get("in_time") or "").strip()
    pass_type = str(payload.get("pass_type") or "personal").lower()
    if not (user_id and date and out_t and in_t):
        raise HTTPException(status_code=400, detail="user_id, date, out_time, in_time required")
    try:
        o = datetime.strptime(f"{date} {out_t}", "%Y-%m-%d %H:%M")
        i = datetime.strptime(f"{date} {in_t}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Times must be HH:MM (24h)")
    if i <= o:
        raise HTTPException(status_code=400, detail="Return (IN) time must be after OUT time")
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0, "company_id": 1, "name": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    gp_id = f"gp_{uuid.uuid4().hex[:10]}"
    minutes = int((i - o).total_seconds() // 60)
    doc = {
        "gate_pass_id": gp_id, "company_id": emp.get("company_id") or company_id,
        "user_id": user_id, "employee_name": emp.get("name"),
        "date": date, "out_time": out_t, "in_time": in_t,
        "minutes": minutes, "pass_type": pass_type,
        "reason": (payload.get("reason") or "").strip(),
        "deducted": pass_type == "personal",
        "created_by": admin.get("name") or admin.get("user_id"),
        "created_at": now_iso(),
    }
    await db.gate_passes.insert_one({**doc})
    if pass_type == "personal":
        # OUT + IN punch pair — the pairing engine deducts the gap.
        for kind, hhmm in (("out", out_t), ("in", in_t)):
            await db.attendance.insert_one({
                "user_id": user_id, "company_id": doc["company_id"],
                "date": date, "kind": kind,
                "at": f"{date}T{hhmm}:00+05:30",
                "source": "gate_pass", "status": "approved",
                "gate_pass_id": gp_id, "created_at": now_iso(),
            })
        invalidate_grid_cache(doc["company_id"])
    return {"ok": True, "gate_pass": doc}


@router.get("/admin/gate-pass")
async def list_gate_passes(
    company_id: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    _, company_id = await _authz(authorization, company_id)
    q: dict = {"company_id": company_id}
    if month:
        q["date"] = {"$gte": f"{month}-01", "$lte": f"{month}-31"}
    items = await db.gate_passes.find(q, {"_id": 0}).sort("date", -1).to_list(2000)
    return {"gate_passes": items}


@router.delete("/admin/gate-pass/{gate_pass_id}")
async def delete_gate_pass(
    gate_pass_id: str,
    authorization: Optional[str] = Header(None),
):
    gp = await db.gate_passes.find_one({"gate_pass_id": gate_pass_id}, {"_id": 0})
    if not gp:
        raise HTTPException(status_code=404, detail="Gate pass not found")
    _, _cid = await _authz(authorization, gp.get("company_id"))
    await db.gate_passes.delete_one({"gate_pass_id": gate_pass_id})
    await db.attendance.delete_many({"gate_pass_id": gate_pass_id})
    invalidate_grid_cache(gp.get("company_id"))
    return {"ok": True}


# ═══════════════════════ 2. LATE PENALTY ═══════════════════════

_LP_DEFAULT = {"enabled": True, "free_lates": 3, "lates_per_half_day": 3}


@router.get("/admin/late-penalty/config")
async def get_late_penalty_config(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    _, company_id = await _authz(authorization, company_id)
    c = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "late_penalty_config": 1})
    return {"config": {**_LP_DEFAULT, **((c or {}).get("late_penalty_config") or {})}}


@router.post("/admin/late-penalty/config")
async def save_late_penalty_config(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    _, company_id = await _authz(authorization, payload.get("company_id"))
    cfg = {
        "enabled": bool(payload.get("enabled", True)),
        "free_lates": max(0, int(_num(payload.get("free_lates"), 3))),
        "lates_per_half_day": max(1, int(_num(payload.get("lates_per_half_day"), 3))),
    }
    await db.companies.update_one({"company_id": company_id},
                                  {"$set": {"late_penalty_config": cfg}})
    return {"ok": True, "config": cfg}


async def _late_penalty_rows(company_id: str, month: str) -> tuple:
    c = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "late_penalty_config": 1})
    cfg = {**_LP_DEFAULT, **((c or {}).get("late_penalty_config") or {})}
    grid = await _compute_monthly_grid_data(company_id=company_id, month=month)
    y, m = int(month[:4]), int(month[5:7])
    month_days = calendar.monthrange(y, m)[1]
    rows = []
    for r in grid.get("employees") or []:
        lates = sum(1 for cell in (r.get("days") or {}).values()
                    if isinstance(cell, dict) and _num(cell.get("late_min")) > 0)
        chargeable = max(0, lates - cfg["free_lates"])
        penalty_days = (chargeable // cfg["lates_per_half_day"]) * 0.5
        u = await db.users.find_one({"user_id": r["user_id"]}, {"_id": 0}) or {}
        gross = _master_gross(u)
        daily = round(gross / month_days, 2) if gross else 0.0
        amount = round(daily * penalty_days, 2)
        if lates > 0:
            rows.append({
                "user_id": r["user_id"], "employee_code": r.get("employee_code"),
                "name": r.get("name"), "late_days": lates,
                "free_lates": cfg["free_lates"], "chargeable": chargeable,
                "penalty_days": penalty_days, "daily_rate": daily,
                "penalty_amount": amount,
            })
    return cfg, rows


@router.get("/admin/late-penalty/report")
async def late_penalty_report(
    company_id: Optional[str] = Query(None),
    month: str = Query(...),
    fmt: str = Query("json"),
    authorization: Optional[str] = Header(None),
):
    _, company_id = await _authz(authorization, company_id)
    cfg, rows = await _late_penalty_rows(company_id, month)
    if fmt == "json":
        return {"config": cfg, "rows": rows,
                "total_penalty": round(sum(r["penalty_amount"] for r in rows), 2)}
    company = await _company(company_id)
    cols = [("Emp Code", "employee_code", False), ("Name", "name", False),
            ("Late Days", "late_days", False), ("Free", "free_lates", False),
            ("Chargeable", "chargeable", False), ("Penalty Days", "penalty_days", False),
            ("Daily Rate", "daily_rate", True), ("Penalty Amount", "penalty_amount", True)]
    return _emit(fmt, title=f"Late Penalty Report — {month}",
                 subtitle=f"Free lates: {cfg['free_lates']} / month · every "
                          f"{cfg['lates_per_half_day']} extra lates = ½ day cut",
                 company=company, cols=cols, rows=rows,
                 fname_base=f"Late_Penalty_{month}")


@router.post("/admin/late-penalty/apply")
async def apply_late_penalty(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Stamp penalties into the current DRAFT compliance run's Other
    Deduction (manual_fields stamped so Reprocess keeps + re-nets them)."""
    _, company_id = await _authz(authorization, payload.get("company_id"))
    month = str(payload.get("month") or "")[:7]
    if not month:
        raise HTTPException(status_code=400, detail="month is required")
    _cfg, rows = await _late_penalty_rows(company_id, month)
    by_uid = {r["user_id"]: r for r in rows if r["penalty_amount"] > 0}
    if not by_uid:
        return {"ok": True, "applied": 0, "detail": "No penalties for this month"}
    run = await db.compliance_salary_runs.find_one(
        {"company_id": company_id, "month": month,
         "status": {"$nin": ["finalized", "final", "locked"]}},
        {"_id": 0, "run_id": 1, "rows": 1}, sort=[("generated_at", -1)])
    if not run:
        raise HTTPException(status_code=404,
                            detail="No DRAFT compliance salary run found for this month — pehle salary process karein")
    applied = 0
    run_rows = run.get("rows") or []
    for row in run_rows:
        p = by_uid.get(row.get("user_id"))
        if not p:
            continue
        row["other_deduction"] = round(_num(row.get("other_deduction")) + p["penalty_amount"], 2)
        row["other_deduction_head"] = "Late Penalty"
        row["manual_fields"] = sorted(set(row.get("manual_fields") or []) | {"other_deduction"})
        applied += 1
    await db.compliance_salary_runs.update_one(
        {"run_id": run["run_id"]}, {"$set": {"rows": run_rows}})
    return {"ok": True, "applied": applied, "run_id": run["run_id"],
            "note": "Ab run ko REPROCESS (With EXISTING Data) karein — net salary refresh ho jayegi"}


# ═══════════════════════ 3. F&F CALCULATOR ═══════════════════════

async def _fnf_compute(user_id: str, exit_date: str, leave_encash_days: float,
                       bonus_amount: float, notice_recovery: float,
                       other_earning: float, other_deduction: float) -> dict:
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    exit_month = exit_date[:7]
    y, m = int(exit_month[:4]), int(exit_month[5:7])
    month_days = calendar.monthrange(y, m)[1]
    gross = _master_gross(u)
    daily = round(gross / month_days, 2) if gross else 0.0
    # Present days of the exit month from the attendance grid
    days_worked = 0.0
    try:
        grid = await _compute_monthly_grid_data(
            company_id=u.get("company_id"), month=exit_month)
        gr = next((r for r in grid.get("employees") or []
                   if r.get("user_id") == user_id), None)
        tot = (gr or {}).get("totals") or {}
        days_worked = _num(tot.get("present_days_policy"), _num(tot.get("present_days")))
    except Exception:
        pass
    earned = round(daily * days_worked, 2)
    yrs = _service_years(u.get("doj"), _parse_doj(exit_date))
    basic = round(gross * 0.5, 2)
    eligible = yrs >= 4.81
    pay_years = int(yrs) + (1 if (yrs - int(yrs)) >= 0.5 else 0)
    gratuity = round(basic * 15.0 / 26.0 * pay_years, 2) if eligible else 0.0
    leave_encash = round(daily * leave_encash_days, 2)
    adv_docs = await db.advances.find(
        {"user_id": user_id}, {"_id": 0, "remaining_balance": 1, "status": 1}).to_list(200)
    adv_out = round(sum(_num(a.get("remaining_balance")) for a in adv_docs
                        if str(a.get("status") or "").lower()
                        not in ("closed", "cancelled", "rejected")), 2)
    # Iter 731 — Asset module integration (read-only): pending approved
    # asset recovery + unreturned assets appear in F&F automatically.
    asset_recs = await db.asset_recoveries.find(
        {"user_id": user_id, "status": "active"},
        {"_id": 0, "pending_amount": 1}).to_list(100)
    asset_recovery = round(sum(_num(r.get("pending_amount")) for r in asset_recs), 2)
    pending_assets = await db.asset_assignments.count_documents(
        {"user_id": user_id, "active": True})
    earn_total = round(earned + gratuity + leave_encash + bonus_amount + other_earning, 2)
    ded_total = round(adv_out + notice_recovery + other_deduction + asset_recovery, 2)
    return {
        "employee": {"user_id": user_id, "name": u.get("name"),
                     "employee_code": u.get("employee_code"), "doj": u.get("doj"),
                     "designation": u.get("designation") or u.get("position"),
                     "company_id": u.get("company_id")},
        "exit_date": exit_date, "service_years": yrs,
        "monthly_gross": round(gross, 2), "daily_rate": daily,
        "days_worked": round(days_worked, 2),
        "earned_salary": earned, "gratuity": gratuity,
        "gratuity_eligible": eligible,
        "leave_encash_days": leave_encash_days, "leave_encashment": leave_encash,
        "bonus_amount": round(bonus_amount, 2),
        "other_earning": round(other_earning, 2),
        "advance_recovery": adv_out,
        "asset_recovery": asset_recovery,
        "pending_assets": pending_assets,
        "notice_recovery": round(notice_recovery, 2),
        "other_deduction": round(other_deduction, 2),
        "total_earnings": earn_total, "total_deductions": ded_total,
        "net_payable": round(earn_total - ded_total, 2),
    }


@router.get("/admin/fnf/calc")
async def fnf_calc(
    user_id: str = Query(...),
    exit_date: str = Query(...),
    leave_encash_days: float = Query(0),
    bonus_amount: float = Query(0),
    notice_recovery: float = Query(0),
    other_earning: float = Query(0),
    other_deduction: float = Query(0),
    fmt: str = Query("json"),
    authorization: Optional[str] = Header(None),
):
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "company_id": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    _, company_id = await _authz(authorization, u.get("company_id"))
    d = await _fnf_compute(user_id, exit_date[:10], leave_encash_days,
                           bonus_amount, notice_recovery, other_earning,
                           other_deduction)
    if fmt == "json":
        return d
    company = await _company(company_id)
    e = d["employee"]
    rows = [
        {"p": "Earned Salary (exit month)", "d": f"{d['days_worked']} days x {d['daily_rate']}", "amt": d["earned_salary"]},
        {"p": "Gratuity", "d": f"{d['service_years']} yrs service" + ("" if d["gratuity_eligible"] else " (not eligible)"), "amt": d["gratuity"]},
        {"p": "Leave Encashment", "d": f"{d['leave_encash_days']} days x {d['daily_rate']}", "amt": d["leave_encashment"]},
        {"p": "Bonus / Ex-gratia", "d": "", "amt": d["bonus_amount"]},
        {"p": "Other Earnings", "d": "", "amt": d["other_earning"]},
        {"p": "TOTAL EARNINGS (A)", "d": "", "amt": d["total_earnings"]},
        {"p": "Advance Recovery", "d": "outstanding balance", "amt": d["advance_recovery"]},
        {"p": "Asset Recovery", "d": "pending approved recovery", "amt": d["asset_recovery"]},
        {"p": "Notice Pay Recovery", "d": "", "amt": d["notice_recovery"]},
        {"p": "Other Deductions", "d": "", "amt": d["other_deduction"]},
        {"p": "TOTAL DEDUCTIONS (B)", "d": "", "amt": d["total_deductions"]},
        {"p": "NET PAYABLE (A - B)", "d": "", "amt": d["net_payable"]},
    ]
    cols = [("Particulars", "p", False), ("Details", "d", False), ("Amount", "amt", True)]
    return _emit(fmt, title="Full & Final Settlement",
                 subtitle=f"{e.get('name')} ({e.get('employee_code') or '-'}) · "
                          f"DOJ {e.get('doj') or '-'} · Exit {d['exit_date']}",
                 company=company, cols=cols, rows=rows,
                 fname_base=f"FnF_{e.get('employee_code') or user_id}",
                 pdf_note="Computed per Payment of Gratuity Act (15/26 rule). "
                          "Advance recovery auto-fetched from the Advances ledger.")
