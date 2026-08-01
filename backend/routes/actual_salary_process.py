"""Iter 396 — ACTUAL SALARY PROCESS module (extracted from server.py).

Refactor only: helpers (_actual_salary_row_compute, _actual_salary_totals),
models and every endpoint below (branches list, create/process, row patch,
finalize, unlock) were MOVED verbatim from server.py. No behavioural change.
"""
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from pydantic import BaseModel

from server import (  # noqa: E402
    _compute_monthly_grid_data,
    _resolve_group_employee_ids,
    _shift_duration_hours,
    db,
    get_user_from_token,
    load_shift_masters_map,
    logger,
    now_iso,
    require_permission,
    require_role,
)
from routes.compliance_salary_runs import (  # noqa: E402
    _require_firm_salary_permission,
)

from shared.dates import (  # noqa: E402
    _month_is_after_exit,
    _month_is_before_doj,
)

router = APIRouter(prefix="/api")
api = router  # endpoints below keep their original @api.* decorators


def _actual_salary_row_compute(row: dict, month_days: int, ot_basis: str = "basic") -> dict:
    """Apply the payroll formulas (Iter 84 + Iter 85 pt 6 — salary_mode-aware).

    Interpretation of ``basic`` varies by ``salary_mode`` on the row:

    • ``monthly`` (default) — ``basic`` is the FULL MONTHLY rate.
        Basic Salary   = basic × (p_days   / month_days)
        W.Basic Salary = basic × (p_hours) / (month_days × duty_hrs)

    • ``daily``   — ``basic`` is the DAILY rate.
        Basic Salary   = basic × p_days
        W.Basic Salary = basic × p_hours / duty_hrs

    • ``hourly``  — ``basic`` is the HOURLY rate.
        Basic Salary   = basic × p_hours
        W.Basic Salary = basic × p_hours   (same — no additional pro-rating)

    Downstream: EPF / ESI are NOT calculated here (Iter 91). They are
    FETCHED from the latest Compliance Salary run for the same month +
    firm and injected into the row; when the compliance process hasn't
    run yet both stay 0. Net = Gross − (EPF + ESI + Adv + TDS).
    """
    basic = float(row.get("basic") or 0.0)
    duty_hrs = float(row.get("duty_hrs") or 0.0)
    p_days = float(row.get("p_days") or 0.0)
    p_hours = float(row.get("p_hours") or 0.0)
    oth_allo = float(row.get("oth_allo") or 0.0)
    adv = float(row.get("adv") or 0.0)
    tds = float(row.get("tds") or 0.0)
    salary_mode = str(row.get("salary_mode") or "monthly").lower()

    md = max(1, int(month_days or 30))

    # Iter 98 — OT (W.Basic) rate basis. Firm Master → Salary Process
    # Settings → "OT Calculation On" (basic | gross). "gross" folds the
    # Other Allowances into the per-hour OT rate; "basic" (default) keeps
    # the historical behaviour.
    if str(ot_basis or "basic").lower() == "gross":
        if salary_mode == "daily":
            ot_rate = basic + (oth_allo / md)
        elif salary_mode == "hourly":
            ot_rate = basic + (oth_allo / (md * duty_hrs) if duty_hrs > 0 else 0.0)
        else:  # monthly
            ot_rate = basic + oth_allo
    else:
        ot_rate = basic

    if salary_mode == "daily":
        # basic = DAILY rate. Whole days → Basic Sal, extra hours → W.Basic.
        basic_salary = basic * p_days
        w_basic_salary = (ot_rate * p_hours / duty_hrs) if duty_hrs > 0 else 0.0
    elif salary_mode == "hourly":
        # basic = HOURLY rate. Whole days convert to hours (p_days ×
        # duty_hrs) → Basic Sal; the extra hours land in W.Basic.
        basic_salary = basic * (p_days * duty_hrs)
        w_basic_salary = ot_rate * p_hours
    else:  # monthly
        basic_salary = basic * (p_days / md) if md > 0 else 0.0
        denom_hours = md * duty_hrs
        w_basic_salary = (ot_rate * p_hours / denom_hours) if denom_hours > 0 else 0.0

    # Iter 91 — Total Gross = Basic Sal + W.Basic Sal + Oth.Allo (per user).
    # Iter 230 (user request) — manual OT AMOUNT override: when the admin
    # edits the W.Basic (OT) cell, the typed amount wins over the
    # hours-based computation until P Hours is edited again.
    if row.get("w_basic_override") is not None:
        w_basic_salary = float(row.get("w_basic_override") or 0.0)
    total_gross = basic_salary + w_basic_salary + oth_allo
    # Iter 91 — EPF/ESI come from the Compliance run (already on the row).
    epf = float(row.get("epf") or 0.0)
    esi = float(row.get("esi") or 0.0)
    # Iter 421 (user request) — manual "Other Deduction" from Gross.
    other_ded = float(row.get("other_ded") or 0.0)
    net_pay = total_gross - (epf + esi + adv + tds + other_ded)

    row["basic_salary"] = round(basic_salary, 2)
    row["w_basic_salary"] = round(w_basic_salary, 2)
    row["total_gross"] = round(total_gross, 2)
    row["epf"] = round(epf, 2)
    row["esi"] = round(esi, 2)
    row["other_ded"] = round(other_ded, 2)
    row["net_pay"] = round(net_pay, 2)
    return row


def _actual_salary_totals(rows: list) -> dict:
    keys = (
        "basic_salary", "w_basic_salary", "total_gross",
        "epf", "esi", "adv", "tds", "other_ded", "net_pay",
    )
    return {k: round(sum((r.get(k) or 0.0) for r in rows), 2) for k in keys}


class ActualSalaryProcessBody(BaseModel):
    """Body for POST /api/admin/actual-salary-process."""
    month: str
    company_id: Optional[str] = None
    month_days: Optional[int] = None
    attendance_source: Literal["biometric", "manual"] = "biometric"
    employee_type: Optional[str] = None
    group_id: Optional[str] = None
    is_onroll: Optional[bool] = None
    # Iter 298 (user request) — two-branch firms: run the process for ONE
    # branch (its employees' days there + other-branch GUEST days).
    branch_name: Optional[str] = None


class ActualSalaryRowPatchBody(BaseModel):
    user_id: str
    basic: Optional[float] = None
    duty_hrs: Optional[float] = None
    p_days: Optional[float] = None
    p_hours: Optional[float] = None
    oth_allo: Optional[float] = None
    # Iter 230 — manual OT amount (W.Basic) override.
    w_basic: Optional[float] = None
    adv: Optional[float] = None
    tds: Optional[float] = None
    # Iter 421 (user request) — manual Other Deduction from Gross.
    other_ded: Optional[float] = None


@api.get("/admin/branches")
async def list_company_branches(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Iter 298 — distinct employee Branch names for a firm. Drives the
    Actual Salary Process branch selector (two-branch payroll split)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    cid = admin.get("company_id") if admin["role"] == "company_admin" else company_id
    q: dict = {"role": "employee", "branch_name": {"$nin": [None, ""]}}
    if cid:
        q["company_id"] = cid
    vals = await db.users.distinct("branch_name", q)
    return {"branches": sorted({str(v).strip() for v in vals if str(v).strip()})}


@api.post("/admin/actual-salary-process")
async def create_actual_salary_process(
    payload: ActualSalaryProcessBody,
    authorization: Optional[str] = Header(None),
):
    """Compute + persist a new Actual Salary Process run."""
    from utils.salary_run import actual_days_in_month, parse_month
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    require_permission(admin, "salary_process:write")

    try:
        year, mon = parse_month(payload.month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    default_days = actual_days_in_month(year, mon)
    month_days = int(payload.month_days or default_days)
    if not (1 <= month_days <= 31):
        raise HTTPException(status_code=400, detail="month_days must be 1..31")

    # Scope
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    else:
        company_id = payload.company_id
    # Iter 98 — Firm Master gate: Offline Salary must be enabled for the firm.
    await _require_firm_salary_permission(company_id, "offline")

    # Iter 218 (user request) — "Count Present Day @ 8 HRS" firm gate:
    # when this Attendance Policy sub-point is ON (and Salary Allowed
    # includes Compliance), ON-ROLL employees are paid via the Compliance
    # Salary Process ONLY (attendance direct-syncs there @ 8 HRS = 1 day).
    # The Actual Salary Process is limited to OFF-ROLL employees.
    _firm_ap_a: dict = {}
    if company_id:
        _cdoc_a = await db.companies.find_one(
            {"company_id": company_id}, {"_id": 0, "attendance_policy": 1})
        _firm_ap_a = (_cdoc_a or {}).get("attendance_policy") or {}
    _c8_active = bool(
        (_firm_ap_a.get("policy_master") or {}).get("compliance_present_8hr")
        and (_firm_ap_a.get("salary_allowed") or "both") in ("compliance", "both")
    )
    if _c8_active and payload.is_onroll is True:
        raise HTTPException(
            status_code=400,
            detail="\"Count Present Day @ 8 HRS\" is ON in this firm's Attendance "
                   "Policy — On-roll employees are paid via the Compliance Salary "
                   "Process only (attendance syncs there directly). The Actual "
                   "Salary Process is allowed for Off-roll employees only.",
        )
    # Iter 129f (user directive) — a FINALIZED month can never be processed
    # again. Unlock (de-finalize) the run first.
    _fin_q: Dict[str, Any] = {"month": payload.month, "finalized": True}
    if company_id:
        _fin_q["company_id"] = company_id
    # Iter 298 — branch runs are independent lifecycles per branch.
    _br = (payload.branch_name or "").strip()
    _fin_q["branch_name"] = _br if _br else {"$in": [None, ""]}
    if await db.salary_runs.find_one(_fin_q, {"_id": 1}):
        raise HTTPException(
            status_code=409,
            detail="This month's Actual salary is already FINALIZED for this firm — "
                   "it cannot be processed again. Unlock (de-finalize) it first.",
        )

    # Iter 297 (user directive) — NON-DESTRUCTIVE REPROCESS: when the
    # month was already processed for this firm, the newest draft run's
    # ENTERED data (P Days / P Hours / Adv / TDS / manual OT amount) is
    # carried into the new run — reprocess updates the existing data
    # instead of starting from zero.
    _prev_run_a = await db.salary_runs.find_one(
        {
            "run_type": "actual",
            "month": payload.month,
            "company_id": company_id,
            "finalized": {"$ne": True},
            # Iter 298 — merge only within the SAME branch run.
            "branch_name": _br if _br else {"$in": [None, ""]},
        },
        {"_id": 0, "rows": 1},
        sort=[("generated_at", -1)],
    )
    _prev_rows_a: Dict[str, dict] = {
        r.get("user_id"): r for r in ((_prev_run_a or {}).get("rows") or [])
    }

    # Iter 98 — OT calculation basis (basic | gross) from Firm Master →
    # Salary Process Settings. Stored on the run so row edits re-compute
    # with the same basis.
    _ot_basis = "basic"
    if company_id:
        _fm_sp = await db.firm_masters.find_one(
            {"company_id": company_id}, {"_id": 0, "salary_process": 1},
        )
        _ot_basis = str(
            ((_fm_sp or {}).get("salary_process") or {}).get("ot_calc_basis")
            or "basic"
        ).lower()

    q: dict = {"role": "employee"}
    if company_id:
        q["company_id"] = company_id
    if payload.employee_type is not None:
        et = payload.employee_type.strip()
        if et.lower() == "unset":
            q["$or"] = [
                {"employee_type": {"$exists": False}},
                {"employee_type": None},
                {"employee_type": ""},
            ]
        elif et and et.lower() != "all":
            title = et.title()
            q["employee_type"] = {"$in": [title, et, et.lower(), et.upper()]}
    if payload.is_onroll is not None:
        if payload.is_onroll:
            q.setdefault("$and", []).append({
                "$or": [
                    {"is_onroll": True},
                    {"is_onroll": {"$exists": False}},
                    {"is_onroll": None},
                ]
            })
        else:
            q["is_onroll"] = False

    employees = await db.users.find(
        q, {"_id": 0}
    ).sort([("employee_code", 1), ("name", 1)]).to_list(4000)
    employees = [e for e in employees if not _month_is_before_doj(e, payload.month)
                 and not _month_is_after_exit(e, payload.month)
                 and e.get("disabled") is not True]  # Iter 166/168

    # Iter 85 — Exclude resigned/left employees. An employee whose
    # ``exit_date`` is on or before the LAST day of the run month has
    # already left the company and must not appear in the Actual Salary
    # Process (matches the semantics of the offboarded flow).
    def _still_active(u: dict) -> bool:
        ed = u.get("exit_date")
        if not ed:
            return True
        try:
            return str(ed) > f"{year:04d}-{mon:02d}-{default_days:02d}"
        except Exception:
            return True
    employees = [e for e in employees if _still_active(e)]

    # Iter 218 — 8-HR compliance-counting firms: Actual Salary Process
    # excludes ON-ROLL employees (they are paid via Compliance only).
    if _c8_active:
        employees = [e for e in employees if e.get("is_onroll") is False]
        if not employees:
            raise HTTPException(
                status_code=400,
                detail="\"Count Present Day @ 8 HRS\" is ON in this firm's "
                       "Attendance Policy — On-roll employees are paid via the "
                       "Compliance Salary Process only. No Off-roll employees "
                       "matched this filter for the Actual Salary Process.",
            )

    # Group filter (optional)
    if payload.group_id:
        grp_uids = await _resolve_group_employee_ids(company_id or "", payload.group_id)
        if grp_uids is not None:
            employees = [e for e in employees if e.get("user_id") in set(grp_uids)]

    # Iter 298 (user request) — TWO-BRANCH firm support. Machines carry a
    # Branch tag (Device Setup); every attendance DATE is attributed to
    # exactly ONE branch via the day's FIRST machine punch, so a month can
    # be split branch-wise for payroll (separate PF/ESIC registrations).
    _dev_branch: Dict[str, str] = {}
    if company_id:
        async for _bd in db.biometric_devices.find(
            {"company_id": company_id, "branch_name": {"$nin": [None, ""]}},
            {"_id": 0, "serial_number": 1, "branch_name": 1},
        ):
            _dev_branch[str(_bd["serial_number"])] = str(_bd["branch_name"]).strip()
    branch_dates_by_user: Dict[str, Dict[str, str]] = {}
    if _dev_branch and employees:
        _first_at: Dict[tuple, str] = {}
        async for _p in db.attendance.find(
            {
                "user_id": {"$in": [e["user_id"] for e in employees]},
                "date": {"$gte": f"{payload.month}-01", "$lte": f"{payload.month}-31"},
                "source": {"$regex": "^zkteco:"},
            },
            {"_id": 0, "user_id": 1, "date": 1, "at": 1, "source": 1},
        ):
            _b = _dev_branch.get(str(_p.get("source") or "")[7:])
            if not _b:
                continue
            _key = (_p["user_id"], _p["date"])
            _at = str(_p.get("at") or "")
            if _key not in _first_at or _at < _first_at[_key]:
                _first_at[_key] = _at
                branch_dates_by_user.setdefault(_p["user_id"], {})[_p["date"]] = _b


    # Biometric grid data (P Days + P Hours) — only if source=biometric
    grid_by_user: Dict[str, Any] = {}
    if payload.attendance_source == "biometric" and company_id:
        try:
            grid = await _compute_monthly_grid_data(
                company_id, payload.month, group_id=payload.group_id
            )
            # NOTE: the grid compute returns its rows under "employees".
            for gr in grid.get("employees") or grid.get("rows") or []:
                grid_by_user[gr["user_id"]] = gr
        except HTTPException:
            grid_by_user = {}

    # Iter 91 — PF / ESI are FETCHED from the latest Compliance Salary run
    # for the same month + firm (not calculated here). If the compliance
    # process hasn't run yet, both stay 0.
    compliance_by_user: Dict[str, Any] = {}
    if company_id:
        comp_run = await db.compliance_salary_runs.find_one(
            {"month": payload.month, "company_id": company_id},
            {"_id": 0, "rows": 1},
            sort=[("generated_at", -1)],
        )
        for cr in ((comp_run or {}).get("rows") or []):
            compliance_by_user[cr.get("user_id")] = {
                "epf": float(cr.get("pf_employee") or 0.0),
                "esi": float(cr.get("esic_employee") or 0.0),
            }

    # Iter 94 — Additional Duty AMOUNTS (Punch Approvals → Extra Duty).
    # Month's per-day ₹ grants are summed into the Oth.Allo column.
    extra_amt_by_user: Dict[str, float] = {}
    if company_id:
        _xd_rows = await db.extra_duty_entries.find(
            {"company_id": company_id,
             "date": {"$gte": f"{payload.month}-01", "$lte": f"{payload.month}-31"}},
            {"_id": 0, "user_id": 1, "extra_amount": 1},
        ).to_list(10000)
        for en in _xd_rows:
            amt = float(en.get("extra_amount") or 0.0)
            if amt > 0:
                extra_amt_by_user[en["user_id"]] = extra_amt_by_user.get(en["user_id"], 0.0) + amt

    # Iter 217 (user request) — Duty HRS = the EMPLOYEE MASTER's per-day
    # Daily Working HRS. Same resolution as the Attendance Report grid:
    # employee override → assigned shift's length → firm policy → 8.
    # (``_firm_ap_a`` was loaded above for the Iter 218 8-HR gate.)
    _shifts_by_id_a, _ = await load_shift_masters_map()
    _firm_daily_a = float(
        _firm_ap_a.get("standard_working_hours")
        or _firm_ap_a.get("full_day_hours")
        or 8.0
    )

    rows: List[dict] = []
    for emp in employees:
        pol = emp.get("employee_policy") or {}
        # Iter 217 — Duty HRS from the Employee Master (attendance policy
        # override), falling back to the assigned shift, then the firm.
        _ov_ap = emp.get("attendance_policy_override") or {}
        emp_daily_hrs = float(_ov_ap.get("standard_working_hours") or 0)
        if emp_daily_hrs <= 0:
            _sh_a = _shifts_by_id_a.get(_ov_ap.get("shift_id")) if _ov_ap.get("shift_id") else None
            _sh_hrs_a = _shift_duration_hours(_sh_a) if _sh_a else None
            emp_daily_hrs = float(_sh_hrs_a or _firm_daily_a or 8.0)
        basic = float(emp.get("salary_monthly") or pol.get("salary") or 0.0)
        emp_salary_mode = emp.get("salary_mode") or "monthly"
        # Iter 91 — Basic Salary comes from the UPDATED Employee Master
        # (Salary Update modal) when a Basic row exists: its amount and
        # rate basis (monthly / daily / hourly) override salary_monthly.
        _struct = [r for r in (emp.get("salary_structure_actual") or []) if isinstance(r, dict)]
        _basic_row = next(
            (r for r in _struct
             if str(r.get("head", "")).strip().lower().startswith("basic")),
            None,
        )
        if _basic_row and float(_basic_row.get("amount") or 0.0) > 0:
            basic = float(_basic_row.get("amount") or 0.0)
            _rt = str(_basic_row.get("rate_type") or "").strip().lower()
            if _rt in ("monthly", "daily", "hourly"):
                emp_salary_mode = _rt
        # Master allowances pre-fill the Oth.Allo column.
        _allow_total = sum(
            float(r.get("amount") or 0.0)
            for r in (emp.get("actual_salary_allowances") or [])
            if isinstance(r, dict)
        )

        p_days = 0.0
        p_hours = 0.0
        if payload.attendance_source == "biometric":
            g = grid_by_user.get(emp["user_id"]) or {}
            t = g.get("totals") or {}
            # Iter 85 — Per user request: P Days = whole-day count
            # (total_days_int), P Hours = remainder (total_extra_hrs).
            # Iter 216 — prefer the report's "Present Days"
            # (present_days_policy) so half-days (26.5) are kept in
            # per-day policy mode; division mode values are identical.
            # Falls back to legacy present_days / hours when the newer
            # split fields are missing.
            _pd_pref = t.get("present_days_policy")
            if _pd_pref is None:
                _pd_pref = t.get("total_days_computed")
            if _pd_pref is None:
                _pd_pref = t.get("total_days_int")
            p_days = float(_pd_pref if _pd_pref is not None else t.get("present_days") or 0.0)
            p_hours = float(t.get("total_extra_hrs") if t.get("total_extra_hrs") is not None else t.get("hours") or 0.0)

        # Iter 85 — DOJ / Exit-date working-days cap. If the employee
        # joined mid-month or resigned mid-month, cap the maximum
        # allowable P Days to only the days they were actually on the
        # rolls that month. This runs regardless of attendance source
        # (biometric or manual) so admins can't accidentally overpay.
        max_days = month_days
        doj = str(emp.get("doj") or "")
        exit_date = str(emp.get("exit_date") or "")
        month_start = f"{year:04d}-{mon:02d}-01"
        month_end = f"{year:04d}-{mon:02d}-{default_days:02d}"
        try:
            if doj and month_start <= doj <= month_end:
                # DOJ in current month → available days = month_days - DOJ.day + 1
                doj_day = int(doj.split("-")[2])
                max_days = min(max_days, month_days - doj_day + 1)
            if exit_date and month_start <= exit_date <= month_end:
                # Exit in current month → available days = exit.day
                exit_day = int(exit_date.split("-")[2])
                max_days = min(max_days, exit_day)
        except (ValueError, IndexError):
            pass  # invalid date format — fall back to full month_days
        max_days = max(0, max_days)
        p_days = min(p_days, float(max_days))
        # Iter 93 — P Days only in half-day steps (.0 or .5), no other decimals.
        p_days = round(p_days * 2) / 2

        # Iter 298 — branch split: home run subtracts days worked at the
        # OTHER branch; a GUEST row pays only the days worked HERE at a
        # per-day rate (Employee Master branch_rates[branch] override
        # wins, else derived from the master salary).
        _home_b = str(emp.get("branch_name") or "").strip()
        _bcounts: Dict[str, int] = {}
        for _db_ in (branch_dates_by_user.get(emp["user_id"]) or {}).values():
            _bcounts[_db_] = _bcounts.get(_db_, 0) + 1
        _is_guest = False
        if _br:
            if _home_b.lower() == _br.lower():
                _away = sum(
                    n for b, n in _bcounts.items() if b.lower() != _br.lower())
                p_days = max(0.0, p_days - float(_away))
            else:
                _here = sum(
                    n for b, n in _bcounts.items() if b.lower() == _br.lower())
                if _here <= 0 and emp["user_id"] not in _prev_rows_a:
                    continue  # never worked at this branch this month
                _is_guest = True
                p_days = float(min(_here, max_days))
                p_hours = 0.0
                _grate = 0.0
                for _rk, _rv in (emp.get("branch_rates") or {}).items():
                    if str(_rk).strip().lower() == _br.lower():
                        _grate = float(_rv or 0)
                if _grate <= 0:
                    if emp_salary_mode == "monthly":
                        _grate = basic / max(1, month_days)
                    elif emp_salary_mode == "hourly":
                        _grate = basic * emp_daily_hrs
                    else:
                        _grate = basic
                basic = round(_grate, 2)
                emp_salary_mode = "daily"

        # Iter 297 — reprocess KEEPS the previously entered days & manual
        # edits from the old run's row for this employee.
        _prev_a = _prev_rows_a.get(emp["user_id"])
        if _prev_a is not None:
            p_days = min(
                round(float(_prev_a.get("p_days") or 0.0) * 2) / 2,
                float(max_days),
            )
            p_hours = float(_prev_a.get("p_hours") or 0.0)

        row = {
            "user_id": emp["user_id"],
            "employee_code": emp.get("employee_code"),
            "name": emp.get("name"),
            "father_name": emp.get("father_name"),
            "designation": emp.get("designation"),
            "department": emp.get("department"),
            "employee_type": emp.get("employee_type"),
            "doj": emp.get("doj"),
            "exit_date": emp.get("exit_date"),
            "is_onroll": bool(emp.get("is_onroll", True)),
            # Iter 298 — branch metadata for splits / grid filters.
            "branch_name": _home_b or None,
            "guest_of_branch": (_br if _is_guest else None),
            "branch_days": (_bcounts or None),
            "salary_mode": emp_salary_mode,
            "duty_hrs": round(emp_daily_hrs, 2),
            "basic": round(basic, 2),
            "p_days": round(p_days, 2),
            "p_hours": round(p_hours, 2),
            # Iter 85 — Persist the DOJ/exit-derived cap so the frontend
            # can enforce the same limit when admins edit rows inline.
            "max_p_days": int(max_days),
            "oth_allo": round(_allow_total + extra_amt_by_user.get(emp["user_id"], 0.0), 2),
            "adv": 0.0,
            "tds": 0.0,
            # Iter 91 — injected from the compliance run (0 if not processed)
            "epf": (compliance_by_user.get(emp["user_id"]) or {}).get("epf", 0.0),
            "esi": (compliance_by_user.get(emp["user_id"]) or {}).get("esi", 0.0),
        }
        # Iter 297 — manual money edits carried over (defaults are 0, so
        # any non-zero value was typed by the admin in the grid).
        if _prev_a is not None:
            # Iter 422 — carry only the MANUAL portion of Adv: the previous
            # run's adv includes the ledger's advance_recovery, which
            # apply_advance_recovery() re-adds below (idempotent txns).
            # Carrying it verbatim would double the ledger amount.
            row["adv"] = max(0.0, round(
                float(_prev_a.get("adv") or 0.0)
                - float(_prev_a.get("advance_recovery") or 0.0), 2))
            row["tds"] = float(_prev_a.get("tds") or 0.0)
            if _prev_a.get("w_basic_override") is not None:
                row["w_basic_override"] = float(_prev_a["w_basic_override"])
        rows.append(_actual_salary_row_compute(row, month_days, ot_basis=_ot_basis))

    # Advance Management — auto-deduct active advance EMIs / single-shot
    # recoveries into rows BEFORE totals (idempotent per month+process).
    _actual_run_id = f"asal_{uuid.uuid4().hex[:12]}"
    from routes.advances import apply_advance_recovery
    await apply_advance_recovery(company_id, payload.month, "actual", _actual_run_id, rows)

    # Iter 338 (user request) — Firm Master → Salary Process → "Import
    # Freeze gross into Actual Salary": ON-ROLL employees take the month's
    # FROZEN (imported) Compliance gross as their Actual Total Gross.
    # Difference vs the calculated gross routes to OT (W.Basic) when the
    # Firm Master allows OT, else to Oth.Allo. Tiny paise remainders (<₹1)
    # snap into Basic Salary so heads always sum to the frozen gross.
    _sp_cfg = ((_fm_sp or {}).get("salary_process") or {}) if company_id else {}
    if bool(_sp_cfg.get("freeze_to_actual")) and rows:
        _frz_run = await db.compliance_salary_runs.find_one(
            {"company_id": company_id, "month": payload.month, "frozen": True},
            {"_id": 0, "rows.user_id": 1, "rows.imported_gross": 1},
            sort=[("generated_at", -1)],
        )
        _frz_g = {
            r["user_id"]: float(r["imported_gross"])
            for r in ((_frz_run or {}).get("rows") or [])
            if r.get("user_id") and r.get("imported_gross") is not None
        }
        _frz_ot_ok = bool(_sp_cfg.get("ot_allowed"))
        for row in rows:
            _ig = _frz_g.get(row.get("user_id"))
            if _ig is None or row.get("is_onroll") is False:
                continue
            _ig = round(_ig, 2)
            _cg = round(float(row.get("total_gross") or 0), 2)
            _dg = round(_ig - _cg, 2)
            row["imported_gross"] = _ig
            row["calculated_gross"] = _cg
            row["difference"] = _dg
            row["difference_allocation_head"] = ""
            # Status flag for the grid: ✓ Matched within ₹1, else "diff".
            row["freeze_actual_status"] = (
                "matched" if abs(_dg) < 1.0 else "diff")
            if abs(_dg) < 1.0:
                # Snap tiny rounding remainders into Basic Salary.
                if _dg != 0.0:
                    row["basic_salary"] = round(
                        float(row.get("basic_salary") or 0) + _dg, 2)
            elif _dg > 0:
                if _frz_ot_ok:
                    # Persist via w_basic_override so inline edits keep it.
                    row["w_basic_override"] = round(
                        float(row.get("w_basic_salary") or 0) + _dg, 2)
                    row["w_basic_salary"] = row["w_basic_override"]
                    row["difference_allocation_head"] = "Overtime (W.Basic)"
                else:
                    row["oth_allo"] = round(
                        float(row.get("oth_allo") or 0) + _dg, 2)
                    row["difference_allocation_head"] = "Other Allowances"
            else:
                # Imported gross BELOW calculated → shortfall off Basic Sal.
                row["basic_salary"] = round(
                    float(row.get("basic_salary") or 0) + _dg, 2)
                row["difference_allocation_head"] = "Base Adjustment"
            row["total_gross"] = _ig
            row["net_pay"] = round(_ig - (
                float(row.get("epf") or 0) + float(row.get("esi") or 0)
                + float(row.get("adv") or 0) + float(row.get("tds") or 0)), 2)
            row["freeze_gross_imported"] = True

    totals = _actual_salary_totals(rows)

    run = {
        "run_id": _actual_run_id,
        "run_type": "actual",
        "month": payload.month,
        "year": year,
        "month_number": mon,
        "month_days": month_days,
        "default_month_days": default_days,
        "attendance_source": payload.attendance_source,
        "company_id": company_id,
        "employee_type": payload.employee_type,
        "is_onroll_filter": payload.is_onroll,
        "group_id": payload.group_id,
        # Iter 298 — branch-scoped run (None = combined / whole firm).
        "branch_name": _br or None,
        "rows": rows,
        "totals": totals,
        "employees_count": len(rows),
        "finalized": False,
        "ot_calc_basis": _ot_basis,
        "generated_by": admin["user_id"],
        "generated_at": now_iso(),
    }
    await db.salary_runs.insert_one(run)

    # Live sync so the "Past Runs" list refreshes.
    try:
        from utils.ws_broker import broker as _ws
        await _ws.broadcast_firm(company_id or "", {
            "type": "salary.run.created",
            "run_id": run["run_id"],
            "month": run["month"],
            "run_type": "actual",
            "employees_count": run["employees_count"],
        })
    except Exception:
        pass

    return {"ok": True, "run": {k: v for k, v in run.items() if k != "_id"}}


@api.patch("/admin/actual-salary-process/{run_id}/row")
async def patch_actual_salary_row(
    run_id: str,
    body: ActualSalaryRowPatchBody,
    authorization: Optional[str] = Header(None),
):
    """Inline-edit a single row (auto-save). Iter 85 (P Days unlock):
    P Days & P Hours are now ALWAYS editable regardless of the run's
    ``attendance_source``. Biometric-derived values are simply the
    initial defaults — admins can override any row inline until the
    run is finalized. The DOJ / exit-date cap still caps p_days."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    require_permission(admin, "salary_process:write")

    run = await db.salary_runs.find_one(
        {"run_id": run_id, "run_type": "actual"}, {"_id": 0}
    )
    if not run:
        raise HTTPException(status_code=404, detail="Actual salary run not found")
    if run.get("finalized"):
        raise HTTPException(status_code=409, detail="Run is finalized and read-only")

    # Company admin can only touch their own firm's run.
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Cross-company edit blocked")

    rows = list(run.get("rows") or [])
    # Iter 85 — src_lock removed. P Days & P Hours are always editable
    # (see body-parse block below).
    idx = next((i for i, r in enumerate(rows) if r.get("user_id") == body.user_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Employee row not found in run")
    row = dict(rows[idx])

    # Iter 217 (user request) — Basic Salary is NOT editable in the Actual
    # Salary Process; it is always fetched from the Employee Master's
    # Actual Salary (Basic row). ``basic`` was removed from the PATCH body.
    # Iter 298 — EXCEPTION: GUEST rows (other-branch duty) may have their
    # per-day rate (Basic) edited, since the other branch can pay a
    # different rate.
    if body.basic is not None and row.get("guest_of_branch"):
        row["basic"] = float(body.basic)
    if body.duty_hrs is not None:
        row["duty_hrs"] = float(body.duty_hrs)
    if body.oth_allo is not None:
        row["oth_allo"] = float(body.oth_allo)
    # Iter 230 (user request) — OT amount (W.Basic) manual override.
    if body.w_basic is not None:
        row["w_basic_override"] = float(body.w_basic)
    if body.adv is not None:
        row["adv"] = float(body.adv)
    if body.tds is not None:
        row["tds"] = float(body.tds)
    # Iter 421 (user request) — manual Other Deduction from Gross.
    if body.other_ded is not None:
        row["other_ded"] = float(body.other_ded)
    # Iter 85 — P Days & P Hours are now ALWAYS editable regardless of
    # the run's attendance source. Biometric-derived values are just the
    # initial defaults; admins can override any row inline.
    # Iter 423b (user request) — the DOJ/exit/month-days cap on manual
    # P Days entry is REMOVED: admins may enter MORE days than the month
    # (e.g. extra duty paid as additional working days).
    if body.p_days is not None:
        row["p_days"] = float(body.p_days)
    if body.p_hours is not None:
        row["p_hours"] = float(body.p_hours)
        # editing hours re-enables the hours-based OT computation
        row.pop("w_basic_override", None)

    row = _actual_salary_row_compute(
        row, int(run.get("month_days") or 30),
        ot_basis=str(run.get("ot_calc_basis") or "basic"),
    )
    rows[idx] = row

    totals = _actual_salary_totals(rows)
    await db.salary_runs.update_one(
        {"run_id": run_id},
        {"$set": {
            "rows": rows,
            "totals": totals,
            "updated_at": now_iso(),
            "updated_by": admin["user_id"],
        }},
    )
    return {"ok": True, "row": row, "totals": totals}


@api.post("/admin/actual-salary-process/{run_id}/finalize")
async def finalize_actual_salary_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """Freeze the run — subsequent PATCH calls return 409."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    require_permission(admin, "salary_process:write")

    existing = await db.salary_runs.find_one(
        {"run_id": run_id, "run_type": "actual"}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Actual salary run not found")
    if admin["role"] == "company_admin" and existing.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Cross-company action blocked")

    await db.salary_runs.update_one(
        {"run_id": run_id},
        {"$set": {
            "finalized": True,
            "finalized_at": now_iso(),
            "finalized_by": admin["user_id"],
        }},
    )
    # Iter 103 — automated email trigger
    try:
        from routes.email_notifications import fire_email_event
        await fire_email_event("salary_finalized", company_id=existing.get("company_id"),
                               details=f"Actual Salary {existing.get('month')}")
    except Exception:
        pass
    return {"ok": True}


@api.post("/admin/salary-runs/{run_id}/unlock")
async def unlock_actual_salary_run(
    run_id: str,
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """Iter 371 (user request) — Super / Sub Admins can UNLOCK a FINALIZED
    Actual Salary run directly (Configure batch card unlock button)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    existing = await db.salary_runs.find_one(
        {"run_id": run_id, "run_type": "actual"}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Actual salary run not found")
    if not existing.get("finalized"):
        return {"ok": True, "already_unlocked": True}
    await db.salary_runs.update_one(
        {"run_id": run_id},
        {"$set": {
            "finalized": False,
            "unlocked_at": now_iso(),
            "unlocked_by": admin["user_id"],
            "unlock_reason": (payload.get("reason") or "").strip()
                             or f"{admin['role']} unlock",
        }},
    )
    logger.info("[actual-run] unlocked run=%s by %s %s",
                run_id, admin["role"], admin["user_id"])
    return {"ok": True, "unlocked": True}
