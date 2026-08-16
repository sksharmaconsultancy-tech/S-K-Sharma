"""Iter 399 — PAYROLL CORE module (split from attendance_core.py).

Refactor only — MOVED verbatim: employee self-service payroll
(/salary/monthly, /me/payslips pdf + year-summary, /me/id-card),
admin payroll (+run) with the _compute_payroll_run engine, and the
admin employees list / employee-types endpoints."""
import asyncio
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from pydantic import BaseModel

from server import (  # noqa: E402
    IST_TZ,
    _compute_monthly_grid_data,
    _get_policy_from_user,
    _redact_user,
    apply_employee_policy_override,
    apply_sub_admin_company_scope,
    db,
    get_user_from_token,
    ist_wallclock_iso,
    ist_wallclock_now,
    logger,
    now_iso,
    require_role,
    sub_admin_can_touch_company,
)
from shared.dates import (  # noqa: E402
    _employee_inactive_for_report,
    _last_completed_month,
    _month_is_after_exit,
    _month_is_before_doj,
    _month_is_complete,
    _parse_any_date,
    _payslip_is_processed,
)

router = APIRouter(prefix="/api")
api = router


@api.get("/salary/monthly")
async def salary_monthly(authorization: Optional[str] = Header(None)):
    """Show the employee their per-month salary status for the last 6 months.

    Iter 57 rules (user request):
      1. Do NOT auto-create pending payslips for months BEFORE the employee's
         date of joining (DOJ).
      2. Only return payslips for months that are FULLY COMPLETE (past) AND
         where the payslip has been actually PROCESSED (pushed from a salary
         run or marked "paid"). Auto-pending slips are never shown here.
    """
    user = await get_user_from_token(authorization)
    salary = user.get("salary_monthly")

    now = datetime.now(timezone.utc)
    months: List[str] = []
    y, m = now.year, now.month
    for _ in range(6):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        months.append(f"{y}-{m:02d}")

    # Skip pre-DOJ months entirely.
    months = [mo for mo in months if not _month_is_before_doj(user, mo)]

    if salary and salary > 0:
        for month in months:
            existing = await db.payslips.find_one({
                "employee_user_id": user["user_id"],
                "month": month,
            })
            if not existing:
                await db.payslips.insert_one({
                    "slip_id": f"ps_{uuid.uuid4().hex[:12]}",
                    "employee_user_id": user["user_id"],
                    "company_id": user.get("company_id"),
                    "month": month,
                    "gross": float(salary),
                    "deductions": 0.0,
                    "net": float(salary),
                    "status": "pending",
                    "pdf_base64": None,
                    "created_at": now_iso(),
                    "created_by": "system_auto",
                })

    raw_slips = await db.payslips.find(
        {"employee_user_id": user["user_id"], "month": {"$in": months}},
        {"_id": 0},
    ).sort("month", -1).to_list(60)

    # Only surface PROCESSED slips for COMPLETED months.
    slips = [
        s for s in raw_slips
        if _month_is_complete(s.get("month", ""), now) and _payslip_is_processed(s)
    ]

    current_month = f"{now.year}-{now.month:02d}"
    return {
        "salary_monthly": salary,
        "current_month": current_month,
        "history": slips,
    }




# ---------------------------------------------------------------------------
# Iter 74 — Employee self-service payslip PDF + ID Card
# ---------------------------------------------------------------------------
@api.get("/me/payslips/{slip_id}.pdf")
async def me_download_payslip_pdf(
    slip_id: str,
    authorization: Optional[str] = Header(None),
):
    """Employee downloads their OWN payslip PDF for a given slip_id.

    The payslip must belong to the logged-in employee and must be
    PROCESSED (linked to a salary run or marked paid). We rebuild the
    PDF on-the-fly from the salary-run row so we always get the latest
    template layout even if the stored ``pdf_base64`` is stale.
    """
    from fastapi.responses import Response
    from utils.payslip_pdf import build_payslip_pdf as _build_ps_pdf

    user = await get_user_from_token(authorization)
    slip = await db.payslips.find_one({"slip_id": slip_id}, {"_id": 0})
    if not slip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    if slip.get("employee_user_id") != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Not your payslip")
    if not _payslip_is_processed(slip):
        raise HTTPException(
            status_code=400,
            detail="Payslip is still pending — please try again once your salary is processed.",
        )

    company = await db.companies.find_one(
        {"company_id": user.get("company_id")}, {"_id": 0},
    ) or {}
    month = slip.get("month") or ""

    # Prefer a fresh rebuild off the linked salary run for full detail.
    run_row: Optional[Dict[str, Any]] = None
    run_days: Optional[int] = None
    run_id = slip.get("salary_run_id") or slip.get("compliance_salary_run_id")
    if run_id:
        run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0}) \
            or await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
        if run:
            run_days = run.get("month_days")
            for row in (run.get("rows") or []):
                if row.get("user_id") == user.get("user_id"):
                    run_row = row
                    break

    if not run_row:
        # Fallback synthetic row using the payslip totals.
        run_row = {
            "user_id": user.get("user_id"),
            "name": user.get("name"),
            "gross": float(slip.get("gross") or 0),
            "deductions": float(slip.get("deductions") or 0),
            "net": float(slip.get("net") or 0),
        }

    pdf_bytes = _build_ps_pdf(
        employee=user,
        company=company,
        row={**run_row, "month_days": run_days},
        month=month,
    )
    fname = f"Payslip_{(user.get('employee_code') or user.get('user_id') or 'me')}_{month}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@api.get("/me/payslips/year-summary")
async def me_payslips_year_summary(
    fy: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 74 — Aggregate the employee's last 12 processed payslips.

    Returns totals + a month-wise list ready to render in the mobile
    Payslip History browser. Only PROCESSED (salary-run-linked OR paid)
    slips are counted.
    """
    user = await get_user_from_token(authorization)
    now = datetime.now(timezone.utc)
    # Build the 12-month window ending at last completed month.
    months: List[str] = []
    for i in range(1, 13):
        y = now.year
        m = now.month - i
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y}-{m:02d}")

    raw = await db.payslips.find(
        {
            "employee_user_id": user["user_id"],
            "month": {"$in": months},
        },
        {"_id": 0},
    ).sort("month", -1).to_list(60)
    slips = [s for s in raw if _payslip_is_processed(s)]

    total_gross = sum(float(s.get("gross") or 0) for s in slips)
    total_deductions = sum(float(s.get("deductions") or 0) for s in slips)
    total_net = sum(float(s.get("net") or 0) for s in slips)
    paid_count = sum(1 for s in slips if (s.get("status") or "").lower() == "paid")

    return {
        "window_months": months,
        "totals": {
            "gross": round(total_gross, 2),
            "deductions": round(total_deductions, 2),
            "net": round(total_net, 2),
            "count": len(slips),
            "paid_count": paid_count,
        },
        "history": slips,
    }


@api.get("/me/id-card")
async def me_id_card(authorization: Optional[str] = Header(None)):
    """Iter 74 — Employee ID Card payload.

    Returns the small data blob the mobile UI needs to render a
    photo-ID-style card:
      * name, employee_code, designation, department, doj
      * company name + code + logo (if any)
      * `qr_payload` — canonical string to be encoded into the QR:
        ``SKSCO|<company_code>|<employee_code>|<user_id>``
        Scanners at the biometric turnstile can parse this to look up
        the employee record.
    """
    user = await get_user_from_token(authorization)
    company = None
    if user.get("company_id"):
        company = await db.companies.find_one(
            {"company_id": user["company_id"]},
            {"_id": 0, "name": 1, "company_code": 1, "logo_base64": 1, "address": 1},
        )
    emp_code = user.get("employee_code") or ""
    comp_code = (company or {}).get("company_code") or ""
    qr_payload = f"SKSCO|{comp_code}|{emp_code}|{user.get('user_id') or ''}"
    return {
        "employee": {
            "user_id": user.get("user_id"),
            "name": user.get("name"),
            "employee_code": emp_code,
            "designation": user.get("designation"),
            "department": user.get("department"),
            "doj": user.get("doj"),
            "phone": user.get("phone"),
            "email": user.get("email"),
            "picture": user.get("picture"),  # base64 or URL
            "blood_group": user.get("blood_group"),
            # Iter 85 — Address is now shown on the downloadable ID card.
            "address": user.get("address"),
        },
        "company": company or {},
        "qr_payload": qr_payload,
        "generated_at": now_iso(),
    }



# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@api.get("/admin/payroll")
async def admin_payroll(
    month: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(pending|paid)$"),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """List payslips across employees, scoped to the admin's company."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    q: dict = {}
    if user["role"] == "company_admin":
        q["company_id"] = user.get("company_id")
    elif company_id:
        q["company_id"] = company_id
    if month:
        q["month"] = month
    if status:
        q["status"] = status
    slips = await db.payslips.find(q, {"_id": 0}).sort([("month", -1), ("employee_user_id", 1)]).to_list(2000)
    # Attach employee names
    user_ids = list({s["employee_user_id"] for s in slips})
    users = await db.users.find({"user_id": {"$in": user_ids}}, {"_id": 0, "user_id": 1, "name": 1, "email": 1}).to_list(2000)
    umap = {u["user_id"]: u for u in users}
    for s in slips:
        emp = umap.get(s["employee_user_id"])
        if emp:
            s["employee_name"] = emp.get("name")
            s["employee_email"] = emp.get("email")
    return {"payslips": slips}


@api.get("/admin/payroll/run")
async def admin_payroll_run(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Compute a lightweight monthly payroll run for every eligible
    employee in scope. See `_compute_payroll_run` for details."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin",
                        "employee"])
    if user.get("role") == "employee":
        # Iter 533 — employees may read ONLY their own payslip row,
        # scoped to their firm (fixes the always-blank payslip tab).
        data = await _compute_payroll_run(
            {**user, "role": "company_admin"}, year, month,
            user.get("company_id"))
        data["rows"] = [r for r in data.get("rows") or []
                        if r.get("user_id") == user.get("user_id")]
        data["attendance"] = [a for a in data.get("attendance") or []
                              if a.get("user_id") == user.get("user_id")]
        data["totals"] = {}
        return data
    return await _compute_payroll_run(user, year, month, company_id)


async def _compute_payroll_run(
    user: dict, year: int, month: int, company_id: Optional[str],
) -> dict:
    """Extracted so it can be reused by the email-report endpoint. The
    caller must have already validated the acting user's role.

    Returns {year, month, month_key, days_in_month, off_days_total,
    rows[], totals{}, attendance[]} where `attendance` is a per-employee
    day-by-day punch summary (used to build the punch-sheet CSV/PDF).
    """
    scope_company: Optional[str] = None
    if user["role"] == "company_admin":
        scope_company = user.get("company_id")
    elif user["role"] == "super_admin" and company_id and company_id != "all":
        scope_company = company_id

    user_q: dict = {"role": "employee"}
    if scope_company:
        user_q["company_id"] = scope_company
    employees = await db.users.find(
        user_q,
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "employee_code": 1,
         "company_id": 1, "salary_monthly": 1, "onboarded": 1,
         "approval_status": 1, "exit_date": 1, "join_date": 1,
         "employee_policy": 1, "full_day_hrs": 1, "half_day_hrs": 1},
    ).to_list(20000)
    def _eligible(e: dict) -> bool:
        if not e.get("onboarded"):
            return False
        if (e.get("approval_status") or "approved") != "approved":
            return False
        if e.get("exit_date") and e["exit_date"] < f"{year}-{month:02d}-01":
            return False
        return True
    employees = [e for e in employees if _eligible(e)]
    if not employees:
        return {
            "year": year, "month": month,
            "month_key": f"{year}-{month:02d}",
            "days_in_month": 0,
            "off_days_total": 0,
            "rows": [],
            "attendance": [],
            "totals": {"employees": 0, "gross_total": 0, "total_hours": 0},
        }

    # Month window
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    days_in_month = (end - start).days
    today = datetime.now(timezone.utc)
    last_visible_day = days_in_month
    if year == today.year and month == today.month:
        last_visible_day = today.day
    off_days_all = sum(
        1 for d in range(1, days_in_month + 1)
        if datetime(year, month, d).weekday() == 6
    )

    # Fetch attendance in one query
    user_ids = [e["user_id"] for e in employees]
    month_key = f"{year}-{month:02d}"
    att = await db.attendance.find(
        {"user_id": {"$in": user_ids}, "date": {"$regex": f"^{month_key}-"}},
        {"_id": 0, "user_id": 1, "date": 1, "kind": 1, "at": 1},
    ).sort("at", 1).to_list(200000)
    by_user: dict[str, list] = {}
    for r in att:
        by_user.setdefault(r["user_id"], []).append(r)

    rows = []
    total_gross = 0.0
    total_hours = 0.0
    attendance_by_user: dict[str, dict[str, dict]] = {}
    for e in employees:
        policy = _get_policy_from_user(e)
        recs = by_user.get(e["user_id"], [])
        # Bucket by date, sorted
        by_date: dict[str, list] = {}
        for r in recs:
            by_date.setdefault(r["date"], []).append(r)

        # Per-day attendance: full / half / present via hours thresholds
        fullday_hrs = float(policy.get("fullday_hours") or e.get("full_day_hrs") or 6)
        halfday_hrs = float(policy.get("halfday_hours") or e.get("half_day_hrs") or 3)
        full_day_salary_flag = bool(policy.get("full_day_salary"))

        present_dates: set[str] = set()
        half_day_dates: set[str] = set()
        total_secs = 0
        # Track first-IN / last-OUT / minutes per day for punch-sheet reports
        per_day: dict[str, dict] = {}
        for date_str, day_recs in by_date.items():
            day_recs.sort(key=lambda x: x["at"])
            has_in = False
            open_in: Optional[str] = None
            day_secs = 0
            first_in: Optional[str] = None
            last_out: Optional[str] = None
            for r in day_recs:
                if r["kind"] == "in":
                    has_in = True
                    open_in = r["at"]
                    if first_in is None:
                        first_in = r["at"]
                elif r["kind"] == "out" and open_in:
                    last_out = r["at"]
                    try:
                        t1 = datetime.fromisoformat(open_in.replace("Z", "+00:00"))
                        t2 = datetime.fromisoformat(r["at"].replace("Z", "+00:00"))
                        day_secs += max(0, int((t2 - t1).total_seconds()))
                    except Exception:
                        pass
                    open_in = None
                elif r["kind"] == "out":
                    last_out = r["at"]
            total_secs += day_secs
            per_day[date_str] = {
                "first_in": first_in,
                "last_out": last_out,
                "minutes": int(day_secs / 60),
                "punches": len(day_recs),
            }
            hrs = day_secs / 3600.0
            if has_in:
                if full_day_salary_flag:
                    present_dates.add(date_str)  # always full when flag on
                elif hrs >= fullday_hrs or day_secs == 0:
                    # No punch-out yet → treat as attended (full day pending)
                    present_dates.add(date_str)
                elif hrs >= halfday_hrs:
                    half_day_dates.add(date_str)
                else:
                    # Attended but below half-day threshold → still count as
                    # attended for the "present" tally, but half-value pay
                    half_day_dates.add(date_str)
        present_days = len(present_dates)
        half_days = len(half_day_dates)
        hours = round(total_secs / 3600.0, 2)

        weekly_off_dow = (policy.get("weekly_off") if policy.get("weekly_off") is not None else 6)
        try:
            weekly_off_dow = int(weekly_off_dow)
        except Exception:
            weekly_off_dow = 6
        # Python weekday: 0=Mon..6=Sun. The UI stores 0=Sun..6=Sat.
        # Convert UI → Python: (ui + 6) % 7
        py_weekly_off = (weekly_off_dow + 6) % 7

        absent_days = 0
        off_days = 0
        join_str = e.get("join_date") or ""
        for d in range(1, last_visible_day + 1):
            date_str = f"{month_key}-{d:02d}"
            if join_str and date_str < join_str:
                continue
            wk = datetime(year, month, d).weekday()
            if wk == py_weekly_off:
                off_days += 1
                continue
            if date_str not in present_dates and date_str not in half_day_dates:
                absent_days += 1

        # Optional weekly-off pay: if the flag is on AND the employee
        # accumulated at least `week_off_min_hours` total hours in the
        # month, we treat weekly-off days as paid days too (added to
        # working denominator and to numerator).
        paid_off_days = 0
        min_hrs = float(policy.get("week_off_min_hours") or 0)
        if policy.get("weekly_off_attendance") and hours >= min_hrs:
            paid_off_days = off_days

        # Effective "attendance-equivalent" numerator
        # full days = 1.0, half days = 0.5, paid off days = 1.0
        attendance_units = present_days + 0.5 * half_days + paid_off_days
        # Denominator: full working days (present+half+absent) + paid_off_days
        working_days = present_days + half_days + absent_days
        denom = working_days + paid_off_days

        base_salary = float(policy.get("salary") or 0)
        base_gross = 0.0
        if base_salary > 0 and denom > 0:
            base_gross = round(base_salary * attendance_units / denom, 2)

        # Attendance-bonus tiers (cumulative). Only Salary 1 + Day 1 are
        # mandatory; Salary 2/3 optional.
        tier_bonus = 0.0
        tiers = []
        for i in (1, 2, 3):
            s_v = float(policy.get(f"salary_{i}") or 0)
            d_v = int(policy.get(f"day_{i}") or 0)
            unlocked = present_days >= d_v > 0 and s_v > 0
            tiers.append({"i": i, "salary": s_v, "day": d_v, "unlocked": unlocked})
            if unlocked:
                tier_bonus += s_v

        # OT pay (only if the flag is on): pay any hours beyond the
        # expected monthly hours at hourly rate = base / (working_days *
        # working_hours). Simplistic MVP.
        ot_pay = 0.0
        if policy.get("ot_allow"):
            working_hours_per_day = float(policy.get("working_hours") or 8)
            expected_hours = present_days * working_hours_per_day
            ot_hours = max(0.0, hours - expected_hours)
            if base_salary > 0 and working_hours_per_day > 0 and (working_days or 0) > 0:
                hourly_rate = base_salary / (working_days * working_hours_per_day)
                ot_pay = round(ot_hours * hourly_rate, 2)

        gross = round(base_gross + tier_bonus + ot_pay, 2)

        rows.append({
            "user_id": e["user_id"],
            "name": e.get("name") or "Unknown",
            "employee_code": e.get("employee_code"),
            "email": e.get("email"),
            "company_id": e.get("company_id"),
            "present_days": present_days,
            "half_days": half_days,
            "absent_days": absent_days,
            "off_days": off_days,
            "paid_off_days": paid_off_days,
            "days_in_month": days_in_month,
            "working_days": working_days,
            "total_hours": hours,
            "salary_monthly": base_salary if base_salary > 0 else None,
            "base_gross": base_gross,
            "tier_bonus": round(tier_bonus, 2),
            "ot_pay": ot_pay,
            "tiers": tiers,
            "gross": gross,
            "policy_confirmed": bool(policy.get("policy_confirmed")),
        })
        total_gross += gross
        total_hours += hours
        attendance_by_user[e["user_id"]] = per_day

    rows.sort(key=lambda r: (r.get("name") or "").lower())

    # Build a flat attendance list (day-by-day) for the punch-sheet report
    attendance: list[dict] = []
    for row in rows:
        uid = row["user_id"]
        pd = attendance_by_user.get(uid, {})
        for d in range(1, days_in_month + 1):
            date_str = f"{month_key}-{d:02d}"
            info = pd.get(date_str, {})
            attendance.append({
                "user_id": uid,
                "name": row["name"],
                "employee_code": row.get("employee_code"),
                "date": date_str,
                "first_in": info.get("first_in"),
                "last_out": info.get("last_out"),
                "minutes": info.get("minutes", 0),
                "punches": info.get("punches", 0),
            })

    return {
        "year": year,
        "month": month,
        "month_key": month_key,
        "days_in_month": days_in_month,
        "off_days_total": off_days_all,
        "rows": rows,
        "attendance": attendance,
        "totals": {
            "employees": len(rows),
            "gross_total": round(total_gross, 2),
            "total_hours": round(total_hours, 2),
        },
    }


@api.get("/admin/employees")
async def list_employees(
    company_id: Optional[str] = Query(None),
    company_ids: Optional[List[str]] = Query(
        None,
        description="Optional list of company_ids for cross-firm fetch. Ignored for company_admin. Overrides company_id when provided.",
    ),
    employee_type: Optional[str] = Query(
        None,
        description="Filter by exact employee_type (case-insensitive). Pass 'unset' to list employees with no type.",
    ),
    is_onroll: Optional[bool] = Query(
        None,
        description="True → only on-roll, False → only off-roll, omit → both.",
    ),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    q: dict = {}
    if user["role"] == "company_admin":
        q["company_id"] = user.get("company_id")
    elif company_ids:
        # Cross-firm mode. Super/Sub-admin can hit any set of firms.
        cleaned = [c for c in company_ids if c]
        if cleaned:
            q["company_id"] = {"$in": cleaned}
    elif company_id:
        q["company_id"] = company_id
    # Iter 133 (user bug) — sub-admins with a restricted company scope must
    # NEVER see other firms' employees, regardless of query params.
    if user["role"] == "sub_admin":
        q = apply_sub_admin_company_scope(user, q)
    # Employee grouping filters
    if employee_type is not None:
        et = employee_type.strip()
        if et.lower() == "unset":
            q["$or"] = [
                {"employee_type": {"$exists": False}},
                {"employee_type": None},
                {"employee_type": ""},
            ]
        elif et:
            # Title-case matches stored form; also match legacy raw form.
            title = et.title()
            q["employee_type"] = {"$in": [title, et, et.lower(), et.upper()]}
    if is_onroll is not None:
        if is_onroll:
            # Treat missing field as on-roll (default)
            q.setdefault("$and", []).append(
                {"$or": [{"is_onroll": True}, {"is_onroll": {"$exists": False}}, {"is_onroll": None}]}
            )
        else:
            q["is_onroll"] = False
    # Iter 68 — Restrict to actual employees only.  Prior to this the
    # endpoint returned every user in the firm including the Company Admin
    # (which surfaced on the Bulk Employee Correction screen as "Sharma
    # Associates Admin" etc.).
    q["role"] = "employee"
    # Iter 585 — RBAC Phase 1: branch/department data scope enforced
    # SERVER-SIDE via the central authorization service (shared/authz.py).
    from shared.authz import scope_filter
    q.update(scope_filter(user))
    # Iter 333 (user request) — up to 20,000 employees per firm.
    users = await db.users.find(q, {"_id": 0}).sort("created_at", -1).to_list(20000)
    users = [_redact_user(u) for u in users]
    return {"employees": users}


@api.get("/admin/employee-types")
async def list_employee_types(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Autocomplete source for the Employee Type field. Returns the distinct
    non-empty types already in use within the caller's scope, plus their
    usage counts so the UI can rank suggestions.
    """
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "sub_admin", "super_admin"])
    match: dict = {
        "employee_type": {"$exists": True, "$nin": [None, ""]},
        # Iter 169 (user bug) — group counts must reflect ACTIVE employees
        # only; resigned/exited/disabled staff inflated the numbers.
        "disabled": {"$ne": True},
        "employment_status": {"$not": {"$regex": "^(exited|resigned|terminated|inactive|left)$", "$options": "i"}},
        "$and": [
            {"$or": [{"exit_date": {"$in": [None, ""]}},
                     {"exit_date": {"$exists": False}}]},
            {"$or": [{"resign_date": {"$in": [None, ""]}},
                     {"resign_date": {"$exists": False}}]},
            {"$or": [{"date_of_leaving": {"$in": [None, ""]}},
                     {"date_of_leaving": {"$exists": False}}]},
            {"$or": [{"leaving_date": {"$in": [None, ""]}},
                     {"leaving_date": {"$exists": False}}]},
        ],
    }
    if user["role"] == "company_admin":
        match["company_id"] = user.get("company_id")
    elif company_id:
        match["company_id"] = company_id
    pipeline = [
        {"$match": match},
        {"$group": {"_id": {"$toUpper": {"$trim": {"input": "$employee_type"}}},
                    "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": 100},
    ]
    counts: dict = {}
    async for row in db.users.aggregate(pipeline):
        counts[row["_id"]] = int(row["count"])
    # Iter 129k (user directive) — the Employee Type options come from the
    # General Masters "group" list (global + firm scope), merged with live
    # usage counts. Case-insensitive so STAFF/Staff can never split.
    m_q: dict = {"type": "group"}
    scope_cid = match.get("company_id")
    if scope_cid:
        m_q["company_id"] = {"$in": [scope_cid, "__global__", None]}
    names: dict = {}
    async for m in db.masters.find(m_q, {"_id": 0, "name": 1}):
        nm = (m.get("name") or "").strip().upper()
        if nm:
            names[nm] = counts.get(nm, 0)
    for nm, c in counts.items():
        names.setdefault(nm, c)
    types = [{"name": n, "count": c} for n, c in names.items()]
    types.sort(key=lambda t: (-t["count"], t["name"]))
    return {"types": types}


# ---------------------------------------------------------------------------
# Retroactive punch management (company_admin + super_admin) — Iteration 52
# ---------------------------------------------------------------------------
# Existing decision endpoint only lets the admin approve / reject / adjust a
# *pending* auto-punch. Employer often needs to ADD an entirely new manual
# punch for a past date (e.g. employee forgot to biometric-clock in) OR
# DELETE an obviously-wrong record. Company admins are capped at a 90-day
# lookback for safety; super_admin has no range restriction.


