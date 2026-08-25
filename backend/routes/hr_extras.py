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
                       other_earning: float, other_deduction: float,
                       pf: float = 0, esic: float = 0, pt: float = 0,
                       tds: float = 0, notice_required: float = 0,
                       notice_served: float = 0,
                       auto_leave: bool = False) -> dict:
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
    # Iter 732 — LEAVE LEDGER auto-fetch (same firm leave_policy +
    # approved-leaves math as /leaves/balance — no new leave formula).
    from datetime import date as _date
    exit_year = int(exit_date[:4])
    fm = await db.firm_masters.find_one(
        {"company_id": u.get("company_id")}, {"_id": 0, "leave_policy": 1}) or {}
    lp = fm.get("leave_policy") or {}
    cl_allowed = float(u.get("cl_allowed_override")
                       if u.get("cl_allowed_override") is not None
                       else (lp.get("cl_day_limit") or 0))
    pl_allowed = float(u.get("pl_allowed_override")
                       if u.get("pl_allowed_override") is not None
                       else (lp.get("pl_day_limit") or 0))
    ys, ye = f"{exit_year}-01-01", f"{exit_year}-12-31"
    cl_taken = pl_taken = 0.0
    async for lv in db.leaves.find(
            {"user_id": user_id, "status": "approved",
             "from_date": {"$lte": ye}, "to_date": {"$gte": ys}},
            {"_id": 0, "leave_type": 1, "from_date": 1, "to_date": 1}):
        try:
            f = max(_date.fromisoformat(str(lv["from_date"])[:10]),
                    _date.fromisoformat(ys))
            t = min(_date.fromisoformat(str(lv["to_date"])[:10]),
                    _date.fromisoformat(ye))
            d = max(0, (t - f).days + 1)
        except (ValueError, TypeError):
            continue
        lt = str(lv.get("leave_type") or "").lower()
        if lt.startswith("cas"):
            cl_taken += d
        elif lt.startswith(("earn", "priv")):
            pl_taken += d
    leave_ledger = {"cl_allowed": cl_allowed, "cl_taken": cl_taken,
                    "cl_balance": max(0.0, cl_allowed - cl_taken),
                    "pl_allowed": pl_allowed, "pl_taken": pl_taken,
                    "pl_balance": max(0.0, pl_allowed - pl_taken)}
    if auto_leave:
        leave_encash_days = leave_ledger["pl_balance"]
    # Iter 732 — NOTICE PAY auto-calc: required days from Employee Master
    # (notice_period_days) or param; shortfall × daily rate; manual
    # override still wins when notice_recovery is passed explicitly.
    if not notice_required:
        notice_required = _num(u.get("notice_period_days"))
    notice_shortfall = max(0.0, notice_required - notice_served) if notice_required else 0.0
    if notice_required and notice_recovery == 0:
        notice_recovery = round(daily * notice_shortfall, 2)
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
    statutory_total = round(pf + esic + pt + tds, 2)
    ded_total = round(adv_out + notice_recovery + other_deduction
                      + asset_recovery + statutory_total, 2)
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
        "notice_required": notice_required, "notice_served": notice_served,
        "notice_shortfall": notice_shortfall,
        "leave_ledger": leave_ledger,
        "pf": round(pf, 2), "esic": round(esic, 2), "pt": round(pt, 2),
        "tds": round(tds, 2), "statutory_total": statutory_total,
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
    pf: float = Query(0),
    esic: float = Query(0),
    pt: float = Query(0),
    tds: float = Query(0),
    notice_required: float = Query(0),
    notice_served: float = Query(0),
    auto_leave: bool = Query(False),
    fmt: str = Query("json"),
    authorization: Optional[str] = Header(None),
):
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "company_id": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    _, company_id = await _authz(authorization, u.get("company_id"))
    d = await _fnf_compute(user_id, exit_date[:10], leave_encash_days,
                           bonus_amount, notice_recovery, other_earning,
                           other_deduction, pf=pf, esic=esic, pt=pt, tds=tds,
                           notice_required=notice_required,
                           notice_served=notice_served, auto_leave=auto_leave)
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
        {"p": "Notice Pay Recovery", "d": (f"{d['notice_shortfall']} days shortfall" if d.get("notice_shortfall") else ""), "amt": d["notice_recovery"]},
        {"p": "PF", "d": "", "amt": d.get("pf", 0)},
        {"p": "ESIC", "d": "", "amt": d.get("esic", 0)},
        {"p": "PT", "d": "", "amt": d.get("pt", 0)},
        {"p": "TDS", "d": "", "amt": d.get("tds", 0)},
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


# ═══════════ Iter 732 — F&F SETTLEMENT LIFECYCLE ═══════════
# Draft → Submitted (HR review) → Approved (LOCKED snapshot) →
# Partially Paid / Paid. Rejected / Cancelled / Reopened (revision).
# Approved settlement = immutable historical snapshot (master-data
# changes NEVER alter it). Full audit trail in fnf_audit.

FNF_STATUSES = ["draft", "submitted", "approved", "rejected",
                "partially_paid", "paid", "on_hold", "cancelled", "reopened"]

_FNF_CALC_PARAMS = ["leave_encash_days", "bonus_amount", "notice_recovery",
                    "other_earning", "other_deduction", "pf", "esic", "pt",
                    "tds", "notice_required", "notice_served"]


async def _fnf_audit(sid, action, admin, old=None, new=None, note=""):
    await db.fnf_audit.insert_one({
        "audit_id": f"fa_{uuid.uuid4().hex[:10]}", "settlement_id": sid,
        "action": action, "old_value": old, "new_value": new,
        "note": note, "by": admin.get("name") or admin.get("user_id"),
        "at": now_iso()})


@router.post("/admin/fnf/settlements")
async def save_fnf_settlement(payload: dict = Body(...),
                              authorization: Optional[str] = Header(None)):
    user_id = payload.get("user_id")
    exit_date = str(payload.get("exit_date") or "")[:10]
    if not (user_id and exit_date):
        raise HTTPException(status_code=400, detail="user_id & exit_date required")
    u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "company_id": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    admin, company_id = await _authz(authorization, u.get("company_id"))
    existing = await db.fnf_settlements.find_one(
        {"user_id": user_id, "status": {"$nin": ["cancelled", "rejected"]}},
        {"_id": 0, "settlement_id": 1})
    if existing:
        raise HTTPException(status_code=400,
                            detail=f"Active settlement {existing['settlement_id']} already exists — use Reopen/Cancel")
    params = {k: _num(payload.get(k)) for k in _FNF_CALC_PARAMS}
    calc = await _fnf_compute(user_id, exit_date,
                              params["leave_encash_days"], params["bonus_amount"],
                              params["notice_recovery"], params["other_earning"],
                              params["other_deduction"], pf=params["pf"],
                              esic=params["esic"], pt=params["pt"],
                              tds=params["tds"],
                              notice_required=params["notice_required"],
                              notice_served=params["notice_served"],
                              auto_leave=bool(payload.get("auto_leave")))
    year = exit_date[:4]
    seq = await db.fnf_settlements.count_documents({"company_id": company_id}) + 1
    sid = f"FNF-{year}-{seq:06d}"
    while await db.fnf_settlements.find_one({"settlement_id": sid, "company_id": company_id}):
        seq += 1
        sid = f"FNF-{year}-{seq:06d}"
    # exit-time asset clearance snapshot
    pending_assets = await db.asset_assignments.find(
        {"user_id": user_id, "active": True},
        {"_id": 0, "asset_code": 1, "asset_name": 1, "assigned_date": 1}).to_list(50)
    doc = {"settlement_id": sid, "company_id": company_id,
           "user_id": user_id, "employee": calc["employee"],
           "exit_date": exit_date, "params": params,
           "calc": calc, "net_payable": calc["net_payable"],
           "total_earnings": calc["total_earnings"],
           "total_deductions": calc["total_deductions"],
           "pending_assets_snapshot": pending_assets,
           "status": "draft", "revision": 0, "revisions": [],
           "approvals": [], "payments": [], "paid_amount": 0.0,
           "balance_amount": calc["net_payable"],
           "created_by": admin.get("name") or admin.get("user_id"),
           "created_at": now_iso()}
    await db.fnf_settlements.insert_one({**doc})
    await _fnf_audit(sid, "Created (draft)", admin, new={"net": calc["net_payable"]})
    return {"ok": True, "settlement": doc}


@router.get("/admin/fnf/settlements")
async def list_fnf_settlements(company_id: Optional[str] = Query(None),
                               status: Optional[str] = Query(None),
                               authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    q: dict = {"company_id": company_id}
    if status:
        q["status"] = status
    items = await db.fnf_settlements.find(
        q, {"_id": 0, "calc": 0, "revisions": 0}).sort("created_at", -1).to_list(1000)
    kpi = {"total": len(items), "total_payable": 0.0, "total_paid": 0.0,
           "outstanding": 0.0, "by_status": {}}
    if not status:
        for s in items:
            kpi["by_status"][s["status"]] = kpi["by_status"].get(s["status"], 0) + 1
            if s["status"] not in ("cancelled", "rejected"):
                kpi["total_payable"] += _num(s.get("net_payable"))
                kpi["total_paid"] += _num(s.get("paid_amount"))
        kpi["outstanding"] = round(kpi["total_payable"] - kpi["total_paid"], 2)
        kpi["total_payable"] = round(kpi["total_payable"], 2)
        kpi["total_paid"] = round(kpi["total_paid"], 2)
    return {"settlements": items, "kpi": kpi}


@router.post("/admin/fnf/settlements/{settlement_id}/action")
async def fnf_action(settlement_id: str, payload: dict = Body(...),
                     authorization: Optional[str] = Header(None)):
    s = await db.fnf_settlements.find_one({"settlement_id": settlement_id}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Settlement not found")
    admin, _cid = await _authz(authorization, s["company_id"])
    action = (payload.get("action") or "").lower()
    note = (payload.get("comments") or payload.get("reason") or "").strip()
    cur = s["status"]
    allowed = {"submit": ["draft", "reopened"], "approve": ["submitted"],
               "reject": ["submitted"], "hold": ["submitted", "approved"],
               "cancel": ["draft", "submitted", "reopened", "on_hold"],
               "reopen": ["approved", "rejected", "paid", "partially_paid", "on_hold"]}
    if action not in allowed:
        raise HTTPException(status_code=400, detail="Invalid action")
    if cur not in allowed[action]:
        raise HTTPException(status_code=400,
                            detail=f"Cannot {action} a {cur} settlement")
    new_status = {"submit": "submitted", "approve": "approved",
                  "reject": "rejected", "hold": "on_hold",
                  "cancel": "cancelled", "reopen": "reopened"}[action]
    sets = {"status": new_status}
    if action == "reopen":
        if not note:
            raise HTTPException(status_code=400, detail="Reopen reason required")
        # snapshot the previous version — never deleted
        rev = {"revision": s.get("revision", 0), "status": cur,
               "calc": s.get("calc"), "params": s.get("params"),
               "net_payable": s.get("net_payable"),
               "reopened_by": admin.get("name") or admin.get("user_id"),
               "reason": note, "at": now_iso()}
        await db.fnf_settlements.update_one(
            {"settlement_id": settlement_id},
            {"$push": {"revisions": rev}, "$inc": {"revision": 1}})
        # recalc fresh with saved params
        p = s.get("params") or {}
        calc = await _fnf_compute(s["user_id"], s["exit_date"],
                                  _num(p.get("leave_encash_days")), _num(p.get("bonus_amount")),
                                  _num(p.get("notice_recovery")), _num(p.get("other_earning")),
                                  _num(p.get("other_deduction")), pf=_num(p.get("pf")),
                                  esic=_num(p.get("esic")), pt=_num(p.get("pt")),
                                  tds=_num(p.get("tds")),
                                  notice_required=_num(p.get("notice_required")),
                                  notice_served=_num(p.get("notice_served")))
        sets.update({"calc": calc, "net_payable": calc["net_payable"],
                     "total_earnings": calc["total_earnings"],
                     "total_deductions": calc["total_deductions"],
                     "balance_amount": round(calc["net_payable"] - _num(s.get("paid_amount")), 2)})
    entry = {"level": len(s.get("approvals") or []) + 1, "action": action,
             "by": admin.get("name") or admin.get("user_id"),
             "at": now_iso(), "comments": note}
    await db.fnf_settlements.update_one(
        {"settlement_id": settlement_id},
        {"$set": sets, "$push": {"approvals": entry}})
    await _fnf_audit(settlement_id, action.capitalize(), admin,
                     old={"status": cur}, new={"status": new_status}, note=note)
    return {"ok": True, "status": new_status}


@router.post("/admin/fnf/settlements/{settlement_id}/payment")
async def fnf_payment(settlement_id: str, payload: dict = Body(...),
                      authorization: Optional[str] = Header(None)):
    s = await db.fnf_settlements.find_one({"settlement_id": settlement_id}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Settlement not found")
    admin, _cid = await _authz(authorization, s["company_id"])
    if s["status"] not in ("approved", "partially_paid"):
        raise HTTPException(status_code=400,
                            detail="Payment sirf APPROVED settlement par record hota hai")
    amt = _num(payload.get("paid_amount"))
    if amt <= 0:
        raise HTTPException(status_code=400, detail="paid_amount required")
    pay = {"payment_id": f"fp_{uuid.uuid4().hex[:8]}", "paid_amount": round(amt, 2),
           "payment_date": (payload.get("payment_date") or now_iso())[:10],
           "payment_mode": payload.get("payment_mode") or "Bank",
           "bank_name": payload.get("bank_name") or "",
           "utr": payload.get("utr") or "",
           "remarks": payload.get("remarks") or "",
           "by": admin.get("name") or admin.get("user_id"), "at": now_iso()}
    total_paid = round(_num(s.get("paid_amount")) + amt, 2)
    balance = round(_num(s.get("net_payable")) - total_paid, 2)
    status = "paid" if balance <= 0 else "partially_paid"
    await db.fnf_settlements.update_one(
        {"settlement_id": settlement_id},
        {"$set": {"paid_amount": total_paid, "balance_amount": max(0.0, balance),
                  "status": status},
         "$push": {"payments": pay}})
    await _fnf_audit(settlement_id, "Payment recorded", admin,
                     new={"paid": amt, "utr": pay["utr"]})
    return {"ok": True, "status": status, "paid_amount": total_paid,
            "balance_amount": max(0.0, balance)}


@router.get("/admin/fnf/settlements/{settlement_id}/pdf")
async def fnf_settlement_pdf(settlement_id: str,
                             authorization: Optional[str] = Header(None)):
    s = await db.fnf_settlements.find_one({"settlement_id": settlement_id}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Settlement not found")
    await _authz(authorization, s["company_id"])
    d = s["calc"]
    e = d["employee"]
    company = await _company(s["company_id"])
    rows = [
        {"p": "Earned Salary (exit month)", "d": f"{d['days_worked']} days x {d['daily_rate']}", "amt": d["earned_salary"]},
        {"p": "Gratuity", "d": f"{d['service_years']} yrs", "amt": d["gratuity"]},
        {"p": "Leave Encashment", "d": f"{d['leave_encash_days']} days", "amt": d["leave_encashment"]},
        {"p": "Bonus / Ex-gratia", "d": "", "amt": d["bonus_amount"]},
        {"p": "Other Earnings", "d": "", "amt": d["other_earning"]},
        {"p": "TOTAL EARNINGS (A)", "d": "", "amt": d["total_earnings"]},
        {"p": "Advance Recovery", "d": "", "amt": d["advance_recovery"]},
        {"p": "Asset Recovery", "d": "", "amt": d["asset_recovery"]},
        {"p": "Notice Pay Recovery", "d": "", "amt": d["notice_recovery"]},
        {"p": "PF / ESIC / PT / TDS", "d": "", "amt": d.get("statutory_total", 0)},
        {"p": "Other Deductions", "d": "", "amt": d["other_deduction"]},
        {"p": "TOTAL DEDUCTIONS (B)", "d": "", "amt": d["total_deductions"]},
        {"p": "NET PAYABLE (A - B)", "d": "", "amt": d["net_payable"]},
        {"p": "Paid till date", "d": "", "amt": s.get("paid_amount", 0)},
        {"p": "Balance", "d": "", "amt": s.get("balance_amount", 0)},
    ]
    appr = "; ".join(f"L{a['level']} {a['action']} by {a['by']} ({a['at'][:10]})"
                     for a in (s.get("approvals") or [])[-4:])
    pays = "; ".join(f"₹{p['paid_amount']} {p['payment_mode']} {p.get('utr','')} ({p['payment_date']})"
                     for p in (s.get("payments") or [])[-4:])
    note = (f"Settlement ID: {settlement_id} · Status: {s['status'].upper()} · "
            f"Revision {s.get('revision', 0)} · Generated {now_iso()[:10]}. "
            + (f"Approvals: {appr}. " if appr else "")
            + (f"Payments: {pays}. " if pays else "")
            + "Prepared By ______  Checked By ______  Approved By ______  Employee Sign ______")
    cols = [("Particulars", "p", False), ("Details", "d", False), ("Amount", "amt", True)]
    return _emit("pdf", title=f"Full & Final Settlement — {settlement_id}",
                 subtitle=f"{e.get('name')} ({e.get('employee_code') or '-'}) · DOJ {e.get('doj') or '-'} · Exit {s['exit_date']}",
                 company=company, cols=cols, rows=rows,
                 fname_base=settlement_id, pdf_note=note)


@router.get("/admin/fnf/register")
async def fnf_register(company_id: Optional[str] = Query(None),
                       fmt: str = Query("xlsx"),
                       authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    items = await db.fnf_settlements.find(
        {"company_id": company_id}, {"_id": 0, "calc": 0, "revisions": 0}).sort(
        "created_at", -1).to_list(2000)
    rows = [{"sid": s["settlement_id"], "code": (s.get("employee") or {}).get("employee_code"),
             "name": (s.get("employee") or {}).get("name"),
             "doj": (s.get("employee") or {}).get("doj"),
             "exit": s.get("exit_date"), "earn": s.get("total_earnings"),
             "ded": s.get("total_deductions"), "net": s.get("net_payable"),
             "paid": s.get("paid_amount"), "bal": s.get("balance_amount"),
             "status": s.get("status")} for s in items]
    cols = [("Settlement ID", "sid", False), ("Emp Code", "code", False),
            ("Name", "name", False), ("DOJ", "doj", False), ("Exit", "exit", False),
            ("Earnings", "earn", True), ("Deductions", "ded", True),
            ("Net Payable", "net", True), ("Paid", "paid", True),
            ("Balance", "bal", True), ("Status", "status", False)]
    company = await _company(company_id)
    return _emit(fmt, title="F&F Settlement Register",
                 subtitle=f"Generated {now_iso()[:10]}", company=company,
                 cols=cols, rows=rows, fname_base="FnF_Register")
