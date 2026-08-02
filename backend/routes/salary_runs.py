"""Iter 409 — ACTUAL (legacy) SALARY RUNS module (extracted from server.py).

Refactor only: every endpoint, model and helper below was MOVED verbatim
from server.py — salary-run create / list / get / reprocess, the CSV /
XLSX / register-PDF exports, bulk + single payslip PDFs and ZIPs,
off-roll slips, the annual report and generate-payslips. No behavioural
change. ``_payslip_rows_for_month`` is re-exported through server.py
because the WhatsApp engine accesses it as a server attribute.

``_sort_export_rows`` now lives in shared/sorting.py (used by the
compliance exports too).
"""
import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from pydantic import BaseModel

from server import (  # noqa: E402
    app,
    db,
    get_user_from_token,
    holiday_dates_for_company,
    logger,
    now_iso,
    require_employer_permission,
    require_permission,
    require_role,
)
from shared.dates import (  # noqa: E402
    _month_is_after_exit,
    _month_is_before_doj,
)
from shared.sorting import _sort_export_rows  # noqa: E402

router = APIRouter(prefix="/api")
api = router  # endpoints below keep their original @api.* decorators

class SalaryRunCreate(BaseModel):
    """Body for POST /api/admin/salary-runs.

    * ``month`` — YYYY-MM (e.g. "2026-06")
    * ``month_days`` — optional override; defaults to actual days in month
    * ``employee_type`` — optional filter (e.g. "Staff"). Pass "unset" for
      employees without a type. Omit or "all" for no filter.
    * ``is_onroll`` — True → only on-roll, False → only off-roll, null → both.
    * ``run_type`` — Iter 77j: "compliance" (default) or "off_roll". Off-roll
      forces ``is_onroll=False``, skips tier bonuses, and no statutory
      deductions (pure days × rate).
    * ``deductions`` — optional overrides (only ``ot_multiplier`` is honoured
      in the base process; statutory PF/ESIC/TDS are handled in the separate
      Compliance Salary Process).
    """
    month: str
    company_id: Optional[str] = None
    month_days: Optional[int] = None
    employee_type: Optional[str] = None
    is_onroll: Optional[bool] = None
    run_type: Optional[Literal["compliance", "off_roll"]] = "compliance"
    deductions: Optional[Dict[str, float]] = None


async def _compute_salary_run(
    admin: dict,
    payload: SalaryRunCreate,
) -> dict:
    """Shared compute path used by both the initial create and re-process
    endpoints. Returns the fully-computed run doc ready to be inserted /
    updated in Mongo."""
    from utils.salary_run import (
        actual_days_in_month, parse_month, compute_present_days_and_ot,
        compute_salary_row,
    )
    try:
        year, mon = parse_month(payload.month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    default_days = actual_days_in_month(year, mon)
    month_days = payload.month_days if payload.month_days else default_days
    if not (1 <= int(month_days) <= 31):
        raise HTTPException(status_code=400, detail="month_days must be 1..31")

    # ---- Scope employees ----
    q: dict = {"role": "employee"}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif payload.company_id:
        q["company_id"] = payload.company_id
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

    # Iter 77j - Off-roll runs FORCE the is_onroll=False filter regardless
    # of what the caller passed in the payload.
    run_type = (getattr(payload, "run_type", None) or "compliance").lower()
    if run_type == "off_roll":
        q["is_onroll"] = False
        if "$and" in q:
            q["$and"] = [
                clause for clause in q["$and"]
                if not (isinstance(clause, dict) and "$or" in clause and any(
                    ("is_onroll" in (sub or {})) for sub in (clause.get("$or") or [])
                ))
            ]
            if not q["$and"]:
                q.pop("$and", None)

    employees = await db.users.find(q, {"_id": 0}).to_list(2000)

    # Iter 338 (user request) — Firm Master toggle "Import Freeze gross
    # into Actual Salary": pull the frozen gross per On-Roll employee from
    # the month's processed (imported) Compliance run.
    _freeze_actual_overrides: dict = {}
    _fm_sp = await db.firm_masters.find_one(
        {"company_id": payload.company_id},
        {"_id": 0, "salary_process.freeze_to_actual": 1})
    if bool(((_fm_sp or {}).get("salary_process") or {}).get("freeze_to_actual")):
        _frun = await db.compliance_salary_runs.find_one(
            {"company_id": payload.company_id, "month": payload.month,
             "frozen": True},
            {"_id": 0, "rows.user_id": 1, "rows.imported_gross": 1},
            sort=[("generated_at", -1)])
        for _r in (_frun or {}).get("rows") or []:
            if _r.get("user_id") and _r.get("imported_gross") is not None:
                _freeze_actual_overrides[_r["user_id"]] = _r["imported_gross"]

    # Iter 57 — Exclude employees whose date-of-joining is AFTER the run's
    # month end. Payslips must never be generated for pre-DOJ months.
    employees = [e for e in employees if not _month_is_before_doj(e, payload.month)
                 and not _month_is_after_exit(e, payload.month)
                 and e.get("disabled") is not True]  # Iter 166/168

    # ---- Load attendance for the month once (indexed by user_id) ----
    date_from = f"{year:04d}-{mon:02d}-01"
    date_to = f"{year:04d}-{mon:02d}-{default_days:02d}"
    attendance_by_user: dict = {}
    if employees:
        user_ids = [e["user_id"] for e in employees]
        async for r in db.attendance.find(
            {
                "user_id": {"$in": user_ids},
                "date": {"$gte": date_from, "$lte": date_to},
            },
            {"_id": 0, "user_id": 1, "kind": 1, "at": 1, "date": 1},
        ):
            attendance_by_user.setdefault(r["user_id"], []).append(r)

    # ---- Load company policies (for full_day_hours / half_day_hours) ----
    company_ids = list({e.get("company_id") for e in employees if e.get("company_id")})
    company_policies: dict = {}
    if company_ids:
        async for c in db.companies.find(
            {"company_id": {"$in": company_ids}},
            {
                "_id": 0, "company_id": 1, "attendance_policy": 1, "name": 1,
                # Iter 85 — include compliance_policy so enabled_allowances
                # toggles can be applied when computing rows.
                "compliance_policy": 1,
            },
        ):
            company_policies[c["company_id"]] = c

    # Iter 142 — Firm Master OT gate → stamp firm_ot_allowed on each
    # company's attendance policy so per-day OT math can honor it.
    if company_ids:
        async for _fm in db.firm_masters.find(
            {"company_id": {"$in": company_ids}},
            {"_id": 0, "company_id": 1, "salary_process.ot_allowed": 1},
        ):
            _v = (_fm.get("salary_process") or {}).get("ot_allowed")
            if _v is not None and _fm["company_id"] in company_policies:
                _ap = dict(company_policies[_fm["company_id"]].get("attendance_policy") or {})
                _ap["firm_ot_allowed"] = bool(_v)
                company_policies[_fm["company_id"]]["attendance_policy"] = _ap

    rows = []
    # Iter 200 — Holiday Master dates per firm + per-employee Offline
    # Salary gate (users.offline_salary_enabled = False → excluded from
    # the offline/actual salary run).
    _holidays_by_cid2: Dict[str, list] = {}
    for _cid2_ in {e.get("company_id") for e in employees if e.get("company_id")}:
        _holidays_by_cid2[_cid2_] = sorted(await holiday_dates_for_company(_cid2_))
    for emp in employees:
        # Iter 200 (user request) — per-employee "Offline Salary: Yes/No":
        # excluded employees are skipped in offline/off-roll salary runs.
        if run_type == "off_roll" and emp.get("offline_salary_enabled") is False:
            continue
        emp = dict(emp)
        emp.pop("pin_hash", None)
        emp.pop("password_hash", None)
        emp.pop("temp_pin_plaintext", None)
        emp.pop("temp_password_plaintext", None)
        pol = emp.get("employee_policy") or {}
        company_doc = company_policies.get(emp.get("company_id")) or {}
        # Merge full/half day hours from the company policy so per-day OT
        # math is consistent across textile / non-textile firms.
        att_pol = company_doc.get("attendance_policy") or {}
        merged_pol = {**att_pol, **pol}  # user policy fields win
        merged_pol["_holiday_dates"] = _holidays_by_cid2.get(emp.get("company_id")) or []
        # Iter 142 — per-employee OT flag (override wins over legacy flag).
        _ov = emp.get("attendance_policy_override") or {}
        _emp_ot = _ov.get("ot_allowed", emp.get("ot_applicable"))
        if _emp_ot is not None:
            merged_pol["ot_allowed"] = bool(_emp_ot)
        att_rows = attendance_by_user.get(emp["user_id"], [])
        stats = compute_present_days_and_ot(att_rows, merged_pol)
        # Iter 77j — Off-roll simplified compute: force salary_mode=daily
        # and clear tier bonus fields so the row is a pure days × rate.
        if run_type == "off_roll":
            simple_pol = dict(merged_pol)
            simple_pol["salary_mode"] = "daily"
            for lvl in (1, 2, 3):
                simple_pol[f"salary_{lvl}"] = 0.0
                simple_pol[f"day_{lvl}"] = 999.0
            row = compute_salary_row(
                emp, simple_pol, int(month_days), stats, payload.deductions,
            )
            # Strip statutory columns that don't apply.
            row["run_type"] = "off_roll"
        else:
            row = compute_salary_row(
                emp, merged_pol, int(month_days), stats, payload.deductions,
            )
            row["run_type"] = "compliance"
        row["company_id"] = emp.get("company_id")
        row["company_name"] = company_doc.get("name")
        # Iter 338 (user request) — Firm Master toggle "Import Freeze gross
        # into Actual Salary": On-Roll employees take the FROZEN gross from
        # the processed Compliance run as their Actual gross for the month.
        _fga = _freeze_actual_overrides.get(emp["user_id"]) if _freeze_actual_overrides else None
        if _fga is not None and emp.get("is_onroll") is not False:
            _imp_g = round(float(_fga), 2)
            _calc_g = round(float(row.get("gross") or 0), 2)
            _diff_g = round(_imp_g - _calc_g, 2)
            row["imported_gross"] = _imp_g
            row["calculated_gross"] = _calc_g
            row["difference"] = _diff_g
            row["difference_allocation_head"] = ""
            # Status flag for the grid: ✓ Matched when the frozen gross is
            # within ₹1 of the calculated gross, otherwise "diff".
            row["freeze_actual_status"] = (
                "matched" if abs(_diff_g) < 1.0 else "diff")
            if abs(_diff_g) < 1.0:
                # Snap tiny rounding remainders (paise noise) into Base Pay
                # so the heads still sum to the frozen gross exactly.
                if _diff_g != 0.0:
                    row["base_pay"] = round(
                        float(row.get("base_pay") or 0) + _diff_g, 2)
            elif _diff_g > 0:
                # Imported gross ABOVE master gross → route the difference
                # to OT when the Firm Master allows OT, else to Allowances.
                if att_pol.get("firm_ot_allowed"):
                    row["ot_pay"] = round(
                        float(row.get("ot_pay") or 0) + _diff_g, 2)
                    row["difference_allocation_head"] = "Overtime"
                else:
                    row["allowances"] = round(
                        float(row.get("allowances") or 0) + _diff_g, 2)
                    row["difference_allocation_head"] = "Other Allowances"
            else:
                # Imported gross BELOW master gross → the shortfall comes
                # off Base Pay so the row still sums to the frozen gross.
                row["base_pay"] = round(
                    float(row.get("base_pay") or 0) + _diff_g, 2)
                row["difference_allocation_head"] = "Base Adjustment"
            row["gross"] = _imp_g
            row["net"] = round(_imp_g - float(row.get("total_deduction") or 0), 2)
            row["freeze_gross_imported"] = True
        rows.append(row)

    totals = {
        k: round(sum(r.get(k, 0.0) or 0.0 for r in rows), 2)
        for k in ("base_pay", "bonus", "ot_pay", "gross", "advance", "total_deduction", "net")
    }

    return {
        "month": payload.month,
        "year": year,
        "month_number": mon,
        "month_days": int(month_days),
        "default_month_days": default_days,
        "company_id": q.get("company_id"),
        "employee_type": payload.employee_type,
        "is_onroll_filter": payload.is_onroll,
        "run_type": run_type,   # Iter 77j
        "deductions_cfg": payload.deductions or {},
        "employees_count": len(rows),
        "rows": rows,
        "totals": totals,
        "generated_by": admin["user_id"],
        "generated_at": now_iso(),
    }


@api.post("/admin/salary-runs")
async def create_salary_run(
    payload: SalaryRunCreate,
    authorization: Optional[str] = Header(None),
):
    """Compute + persist a new monthly salary run. Rows are computed
    server-side using each employee's policy, attendance, and the
    configured deductions.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    require_permission(admin, "salary_process:write")
    await require_employer_permission(admin, "salary_process:write", db)
    # Iter 200 (user request) — Attendance Policy "Salary Allowed" gate:
    # actual / compliance / both. Off-roll (actual) runs require "actual"
    # or "both"; compliance runs require "compliance" or "both".
    _gate_cid = getattr(payload, "company_id", None) or admin.get("company_id")
    if _gate_cid:
        _co = await db.companies.find_one(
            {"company_id": _gate_cid}, {"_id": 0, "attendance_policy.salary_allowed": 1})
        _sa = ((_co or {}).get("attendance_policy") or {}).get("salary_allowed") or "both"
        _rt = (getattr(payload, "run_type", None) or "compliance")
        if _rt == "off_roll" and _sa == "compliance":
            raise HTTPException(status_code=400, detail=(
                "Actual/Offline salary runs are not allowed for this firm — "
                "Attendance Policy → Salary Allowed is set to Compliance only."))
        if _rt != "off_roll" and _sa == "actual":
            raise HTTPException(status_code=400, detail=(
                "Compliance salary runs are not allowed for this firm — "
                "Attendance Policy → Salary Allowed is set to Actual only."))
    run = await _compute_salary_run(admin, payload)
    run["run_id"] = f"srun_{uuid.uuid4().hex[:12]}"
    await db.salary_runs.insert_one(run)
    # Iter 77n — real-time broadcast of salary-run created event.
    try:
        from utils.ws_broker import broker as _ws
        await _ws.broadcast_firm(run.get("company_id") or "", {
            "type": "salary.run.created",
            "run_id": run["run_id"],
            "month": run.get("month"),
            "run_type": run.get("run_type"),
            "employees_count": run.get("employees_count"),
        })
    except Exception:
        pass
    return {"ok": True, "run": {k: v for k, v in run.items() if k != "_id"}}


@api.get("/admin/salary-runs")
async def list_salary_runs(
    company_id: Optional[str] = Query(None),
    company_ids: Optional[List[str]] = Query(
        None, description="Cross-firm filter. Ignored for company_admin."
    ),
    month: Optional[str] = Query(None),
    fy_start_year: Optional[int] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """List salary runs with optional filters. Company admins are scoped
    to their own company. Sub-admins have super-admin-like scope."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    q: dict = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif company_ids:
        cleaned = [c for c in company_ids if c]
        if cleaned:
            q["company_id"] = {"$in": cleaned}
    elif company_id:
        q["company_id"] = company_id
    if month:
        q["month"] = month
    # Financial year filter (Apr Y → Mar Y+1)
    if fy_start_year is not None:
        y = int(fy_start_year)
        q["month"] = q.get("month") or {"$gte": f"{y}-04", "$lte": f"{y + 1}-03"}
    runs = await db.salary_runs.find(
        q,
        {
            "_id": 0,
            # Skip the heavy rows on the list view — clients fetch details
            # separately via GET /admin/salary-runs/{run_id}.
            "rows": 0,
        },
    ).sort("generated_at", -1).to_list(500)
    # Iter 85 — Enrich each run with the display names of the users who
    # generated / finalized it. This lets "Past Runs" show an audit
    # trail (date+time+admin) without extra client requests.
    uids: set = set()
    for r in runs:
        for k in ("generated_by", "finalized_by", "updated_by"):
            v = r.get(k)
            if v:
                uids.add(v)
    name_by_uid: dict = {}
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": list(uids)}},
            {"_id": 0, "user_id": 1, "name": 1, "role": 1},
        ):
            name_by_uid[u["user_id"]] = {
                "name": u.get("name") or "—",
                "role": u.get("role") or "",
            }
    for r in runs:
        for src_key, name_key, role_key in (
            ("generated_by", "generated_by_name", "generated_by_role"),
            ("finalized_by", "finalized_by_name", "finalized_by_role"),
            ("updated_by", "updated_by_name", "updated_by_role"),
        ):
            uid = r.get(src_key)
            if uid and uid in name_by_uid:
                r[name_key] = name_by_uid[uid]["name"]
                r[role_key] = name_by_uid[uid]["role"]
    return {"runs": runs}


@api.get("/admin/salary-runs/{run_id}")
async def get_salary_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    return {"run": run}


# Iter 68 — Salary Register PDF (Form 27(1)) — landscape A4 register with
# per-employee earnings + deductions, matching the reference sample the
# user uploaded (DEV KRIPA LABOUR.pdf).
@api.get("/admin/salary-runs/{run_id}/register-form27.pdf")
async def download_salary_register_pdf(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    from fastapi.responses import Response
    from utils.salary_register_pdf import build_salary_register_pdf
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    company = await db.companies.find_one({"company_id": run.get("company_id")}, {"_id": 0}) or {}
    xlsx_bytes = build_salary_register_pdf(
        company=company,
        month=run.get("month") or "",
        month_days=int(run.get("month_days") or 30),
        rows=run.get("rows") or run.get("lines") or [],
        totals=run.get("totals") or {},
        payment_date=run.get("payment_date"),
    )
    fname = f"SalaryRegister_Form27_{(company.get('name') or 'firm').replace(' ', '_')}_{run.get('month') or ''}.pdf"
    return Response(
        content=xlsx_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# Iter 68 — Salary Certificate PDF (per employee, HR / bank use).
@api.get("/admin/employees/{user_id}/salary-certificate.pdf")
async def download_salary_certificate_pdf(
    user_id: str,
    month: Optional[str] = None,
    signatory_name: Optional[str] = None,
    signatory_role: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    from fastapi.responses import Response
    from utils.salary_certificate import build_salary_certificate_pdf
    from routes.report_formats import title_for as _title_for_report
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    emp = await db.users.find_one({"user_id": user_id, "role": "employee"}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this employee")
    company = await db.companies.find_one(
        {"company_id": emp.get("company_id")}, {"_id": 0},
    ) or {}
    policy = company.get("compliance_policy") or {}
    ref_month = month or (datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m"))
    pdf_bytes = build_salary_certificate_pdf(
        employee=emp,
        company=company,
        policy=policy,
        month=ref_month,
        signatory_name=signatory_name,
        signatory_role=signatory_role,
        title=await _title_for_report("salary_certificate", "SALARY CERTIFICATE"),
    )
    fname = f"SalaryCertificate_{(emp.get('name') or 'employee').replace(' ', '_')}_{ref_month}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.post("/admin/salary-runs/{run_id}/reprocess")
async def reprocess_salary_run(
    run_id: str,
    payload: Optional[SalaryRunCreate] = None,
    authorization: Optional[str] = Header(None),
):
    """Re-compute an existing salary run. If a body is supplied it may
    override month_days, filters, deductions etc. Otherwise we reuse the
    previously-stored parameters."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "salary_process:write", db)
    existing = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and existing.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    if payload is None:
        payload = SalaryRunCreate(
            month=existing["month"],
            company_id=existing.get("company_id"),
            month_days=existing.get("month_days"),
            employee_type=existing.get("employee_type"),
            is_onroll=existing.get("is_onroll_filter"),
            deductions=existing.get("deductions_cfg"),
        )
    run = await _compute_salary_run(admin, payload)
    run["run_id"] = run_id
    run["reprocessed_from_at"] = existing.get("generated_at")
    await db.salary_runs.replace_one({"run_id": run_id}, run)
    # Iter 77n — broadcast reprocess event.
    try:
        from utils.ws_broker import broker as _ws
        await _ws.broadcast_firm(run.get("company_id") or "", {
            "type": "salary.run.updated",
            "run_id": run_id,
            "month": run.get("month"),
            "run_type": run.get("run_type"),
            "employees_count": run.get("employees_count"),
        })
    except Exception:
        pass
    return {"ok": True, "run": {k: v for k, v in run.items() if k != "_id"}}



async def _actual_epf_esi_flags(company_id: Optional[str]) -> tuple:
    """Iter 373 (user request) — EPF/ESI column visibility for Actual
    Salary exports: the Firm Master "Applicable" flags are authoritative;
    when never configured, fall back to the Deductions catalog (exactly
    like the compliance engine)."""
    fm = await db.firm_masters.find_one(
        {"company_id": company_id},
        {"_id": 0, "epf": 1, "esi": 1, "deductions": 1}) or {}
    _fm_ded = fm.get("deductions") or {}
    _has_cat = any(bool(v) for v in _fm_ded.values())
    _epf_ap = (fm.get("epf") or {}).get("applicable")
    _esi_ap = (fm.get("esi") or {}).get("applicable")
    show_epf = (bool(_epf_ap) if _epf_ap is not None
                else (bool(_fm_ded.get("PF")) if _has_cat else True))
    show_esi = (bool(_esi_ap) if _esi_ap is not None
                else (bool(_fm_ded.get("ESI")) if _has_cat else True))
    return show_epf, show_esi


@api.get("/admin/salary-runs/{run_id}/export.csv")
async def export_salary_run_csv(
    run_id: str,
    sort_by: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    from utils.salary_run import to_csv
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    # Iter 373 (user request) — ACTUAL runs export the Actual grid columns
    # with EPF/ESI dynamic per Firm Master (matches the PDF register).
    if (run.get("run_type") or "") == "actual":
        from utils.salary_run import to_actual_csv
        show_epf, show_esi = await _actual_epf_esi_flags(run.get("company_id"))
        csv_str = to_actual_csv(_sort_export_rows(run.get("rows") or [], sort_by),
                                show_epf=show_epf, show_esi=show_esi)
    else:
        csv_str = to_csv(_sort_export_rows(run.get("rows") or [], sort_by))
    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="SalaryRun_{run.get("month")}_{run_id}.csv"',
        },
    )


@api.get("/admin/salary-runs/{run_id}/export.xlsx")
async def export_salary_run_xlsx(
    run_id: str,
    sort_by: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 64 — native Excel export for Salary runs.

    Same columns as the CSV, plus:
      • Bold header with brand-tinted fill and frozen top row.
      • Numeric columns typed as numbers with ``#,##0.00`` format so
        Excel opens them locale-safe.
      • Auto-computed TOTAL row for every numeric column.
    """
    from utils.salary_run import CSV_COLUMNS
    from utils.report_xlsx import build_rows_xlsx
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    company_name = "S.K. Sharma & Co."
    if run.get("company_id"):
        c = await db.companies.find_one(
            {"company_id": run["company_id"]}, {"_id": 0, "name": 1}
        )
        if c and c.get("name"):
            company_name = c["name"]
    # Iter 373 (user request) — ACTUAL runs export the Actual grid columns
    # with EPF/ESI dynamic per Firm Master (matches the PDF register).
    if (run.get("run_type") or "") == "actual":
        from utils.salary_run import actual_csv_columns
        show_epf, show_esi = await _actual_epf_esi_flags(run.get("company_id"))
        xlsx_bytes = build_rows_xlsx(
            columns=actual_csv_columns(show_epf, show_esi),
            rows=_sort_export_rows(run.get("rows") or [], sort_by),
            sheet_name="Actual Salary",
            title=f"Actual Salary — {company_name}",
            subtitle=f"Month: {run.get('month')} · Employees: {len(run.get('rows') or [])}",
        )
    else:
        xlsx_bytes = build_rows_xlsx(
            columns=CSV_COLUMNS,
            rows=_sort_export_rows(run.get("rows") or [], sort_by),
            sheet_name="Salary Run",
            title=f"Salary Run — {company_name}",
            subtitle=f"Month: {run.get('month')} · Employees: {len(run.get('rows') or [])}",
        )
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="SalaryRun_{run.get("month")}_{run_id}.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/admin/salary-runs/{run_id}/register.pdf")
async def export_salary_register_pdf(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    from utils.salary_run import build_salary_register_pdf
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    company_name = "S.K. Sharma & Co."
    if run.get("company_id"):
        c = await db.companies.find_one({"company_id": run["company_id"]}, {"_id": 0, "name": 1})
        if c and c.get("name"):
            company_name = c["name"]
    # Iter 372 (user request) — ACTUAL runs get their own register with
    # EPF / ESI columns DYNAMIC per Firm Master (Applicable flags, falling
    # back to the Deductions catalog exactly like the compliance engine).
    if (run.get("run_type") or "") == "actual":
        from utils.salary_run import build_actual_salary_register_pdf
        show_epf, show_esi = await _actual_epf_esi_flags(run.get("company_id"))
        pdf_bytes = build_actual_salary_register_pdf(
            run, company_name=company_name,
            show_epf=show_epf, show_esi=show_esi)
    else:
        from routes.report_formats import get_report_format
        pdf_bytes = build_salary_register_pdf(
            run, company_name=company_name,
            fmt=await get_report_format("salary_register"))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="SalaryRegister_{run.get("month")}_{run_id}.pdf"',
            "Cache-Control": "no-store",
        },
    )


async def _salary_run_attachments(run: Dict[str, Any], formats: List[str]):
    """Iter 438 (user request) — build PDF/Excel/CSV report files for an
    Actual / legacy salary run (same builders as the download endpoints)."""
    from utils.report_xlsx import build_rows_xlsx
    from utils.salary_run import CSV_COLUMNS, to_csv
    month = run.get("month") or ""
    is_actual = (run.get("run_type") or "") == "actual"
    company_name = "S.K. Sharma & Co."
    if run.get("company_id"):
        c = await db.companies.find_one(
            {"company_id": run["company_id"]}, {"_id": 0, "name": 1})
        if c and c.get("name"):
            company_name = c["name"]
    show_epf = show_esi = True
    if is_actual:
        show_epf, show_esi = await _actual_epf_esi_flags(run.get("company_id"))
    rows = run.get("rows") or []
    out = []
    if "pdf" in formats:
        if is_actual:
            from utils.salary_run import build_actual_salary_register_pdf
            pdf_bytes = build_actual_salary_register_pdf(
                run, company_name=company_name,
                show_epf=show_epf, show_esi=show_esi)
        else:
            from routes.report_formats import get_report_format
            from utils.salary_run import build_salary_register_pdf
            pdf_bytes = build_salary_register_pdf(
                run, company_name=company_name,
                fmt=await get_report_format("salary_register"))
        out.append({"filename": f"SalaryRegister_{month}.pdf",
                    "content": pdf_bytes, "mime": "application/pdf"})
    if "xlsx" in formats:
        if is_actual:
            from utils.salary_run import actual_csv_columns
            cols = actual_csv_columns(show_epf, show_esi)
            sheet, title = "Actual Salary", f"Actual Salary — {company_name}"
        else:
            cols, sheet, title = CSV_COLUMNS, "Salary Run", f"Salary Run — {company_name}"
        out.append({"filename": f"SalaryRun_{month}.xlsx",
                    "content": build_rows_xlsx(
                        columns=cols, rows=rows, sheet_name=sheet, title=title,
                        subtitle=f"Month: {month} · Employees: {len(rows)}"),
                    "mime": "application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet"})
    if "csv" in formats:
        if is_actual:
            from utils.salary_run import to_actual_csv
            csv_str = to_actual_csv(rows, show_epf=show_epf, show_esi=show_esi)
        else:
            csv_str = to_csv(rows)
        out.append({"filename": f"SalaryRun_{month}.csv",
                    "content": csv_str.encode("utf-8"), "mime": "text/csv"})
    return out, company_name


@api.post("/admin/salary-runs/{run_id}/email-report")
async def email_salary_run_report(
    run_id: str,
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """Iter 438 (user request) — after Save / Finalize the admin can MAIL
    the Actual Salary reports (PDF / Excel / CSV / All) to any email."""
    from utils.report_email import normalize_formats, send_report_email
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    formats = normalize_formats(payload.get("formats"))
    to = payload.get("to") or admin.get("email") or ""
    attachments, company_name = await _salary_run_attachments(run, formats)
    month = run.get("month") or ""
    label = "Actual Salary" if (run.get("run_type") or "") == "actual" else "Salary Run"
    status = "FINALIZED" if run.get("finalized") else "Draft"
    grp = str(run.get("employee_type") or "").strip() or "All Groups"
    fmt_txt = ", ".join(f.upper() for f in formats)
    res = await send_report_email(
        to,
        f"{label} Report — {company_name} ({month})",
        (f"Please find attached the {label} report(s) for "
         f"{company_name} — {month} ({status}).\n\n"
         f"Employee Group: {grp}\n"
         f"Employees: {len(run.get('rows') or [])}\n"
         f"Formats: {fmt_txt}\n\n"
         f"Sent from Smart Payroll Service."),
        attachments)
    rcpts = ", ".join(res.get("to") or [])
    return {"ok": True, "via": res.get("via"), "to": res.get("to"),
            "formats": formats,
            "message": f"Report ({fmt_txt}) emailed to {rcpts}"}


@api.get("/admin/salary-runs/{run_id}/payslips.pdf")
async def download_bulk_payslips_pdf(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """Combined multi-page PDF — one payslip page per employee in the run.

    Uses the same layout as the single-employee payslip so bulk downloads
    stay visually identical to what employees see in-app.
    """
    from fastapi.responses import Response
    from utils.payslip_pdf import build_bulk_payslip_pdf
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    company = await db.companies.find_one(
        {"company_id": run.get("company_id")}, {"_id": 0},
    ) or {}
    # Enrich rows with employee master data for the payslip header.
    rows = run.get("rows") or []
    uids = [r.get("user_id") for r in rows if r.get("user_id")]
    emps_map: Dict[str, Dict[str, Any]] = {}
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
             "designation": 1, "department": 1, "doj": 1,
             "uan_no": 1, "pf_no": 1, "esi_ip_no": 1, "pan_no": 1,
             "bank_name": 1, "bank_account": 1, "bank_ifsc": 1},
        ):
            emps_map[u["user_id"]] = u
    entries: List[Dict[str, Any]] = []
    for r in rows:
        emp = emps_map.get(r.get("user_id") or "") or {"name": r.get("name")}
        entries.append({"employee": emp, "row": {**r, "month_days": run.get("month_days")}})
    from routes.report_formats import title_for
    pdf_bytes = build_bulk_payslip_pdf(
        company=company, month=run.get("month") or "", entries=entries,
        title=await title_for("payslips", "PAYSLIP"),
    )
    fname = (
        f"Payslips_{(company.get('name') or 'firm').replace(' ', '_')}_"
        f"{run.get('month') or ''}.pdf"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.get("/admin/salary-runs/{run_id}/payslips.zip")
async def download_bulk_payslips_zip(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """ZIP archive containing one PDF per employee.

    File naming inside the ZIP: ``<EmployeeCode>_<Name>_<Month>.pdf``.
    """
    from fastapi.responses import Response
    from utils.payslip_pdf import build_payslip_pdf
    import zipfile

    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    company = await db.companies.find_one(
        {"company_id": run.get("company_id")}, {"_id": 0},
    ) or {}

    rows = run.get("rows") or []
    uids = [r.get("user_id") for r in rows if r.get("user_id")]
    emps_map: Dict[str, Dict[str, Any]] = {}
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
             "designation": 1, "department": 1, "doj": 1,
             "uan_no": 1, "pf_no": 1, "esi_ip_no": 1, "pan_no": 1,
             "bank_name": 1, "bank_account": 1, "bank_ifsc": 1},
        ):
            emps_map[u["user_id"]] = u

    month = run.get("month") or ""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            uid = r.get("user_id")
            if not uid:
                continue
            emp = emps_map.get(uid) or {"name": r.get("name")}
            pdf_bytes = build_payslip_pdf(
                employee=emp,
                company=company,
                row={**r, "month_days": run.get("month_days")},
                month=month,
            )
            safe_code = (emp.get("employee_code") or uid).replace("/", "_")
            safe_name = (emp.get("name") or "employee").replace("/", "_").replace(" ", "_")
            zf.writestr(f"{safe_code}_{safe_name}_{month}.pdf", pdf_bytes)
    fname = (
        f"Payslips_{(company.get('name') or 'firm').replace(' ', '_')}_{month}.zip"
    )
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ---------------------------------------------------------------------------
# Iter 230 (user request) — Employee Report payslips: download or e-mail a
# payslip per employee (or for ALL employees) by firm + month, without
# needing the run_id. Resolution order: latest COMPLIANCE run for the
# month (statutory payslip), else latest ACTUAL salary run (mapped).
# ---------------------------------------------------------------------------
def _actual_row_to_payslip(r: dict, month_days: Any) -> dict:
    """Map an Actual-salary row onto the payslip-PDF field names."""
    epf = float(r.get("epf") or 0)
    esi = float(r.get("esi") or 0)
    adv = float(r.get("adv") or 0)
    tds = float(r.get("tds") or 0)
    return {
        **r,
        "month_days": month_days,
        "present_days": r.get("p_days"),
        "ot_hours": r.get("p_hours"),
        "basic": r.get("basic_salary"),
        "ot_pay": r.get("w_basic_salary"),
        "other_earning": r.get("oth_allo"),
        "gross": r.get("total_gross"),
        "pf_employee": epf,
        "esic_employee": esi,
        "tds": tds,
        "advance": adv,
        "total_deduction": epf + esi + adv + tds,
        "net": r.get("net_pay"),
    }


async def _payslip_rows_for_month(company_id: str, month: str):
    """(rows, month_days, source) for the latest processed run of a month."""
    crun = await db.compliance_salary_runs.find_one(
        {"company_id": company_id, "month": month}, {"_id": 0},
        sort=[("created_at", -1)])
    if crun and (crun.get("rows") or []):
        # Iter 381 (user request) — payslips follow the Firm Master enabled
        # heads; old runs get the live masks stamped like the register.
        # Lazy import — avoids a circular import at module load time
        # (compliance_salary_runs itself imports from server).
        from routes.compliance_salary_runs import _ensure_firm_head_masks
        crun = await _ensure_firm_head_masks(crun)
        return (crun.get("rows") or [], crun.get("month_days"), "compliance")
    arun = await db.salary_runs.find_one(
        {"company_id": company_id, "month": month, "run_type": "actual"},
        {"_id": 0}, sort=[("created_at", -1)])
    if arun and (arun.get("rows") or []):
        rows = [_actual_row_to_payslip(r, arun.get("month_days"))
                for r in (arun.get("rows") or [])]
        return (rows, arun.get("month_days"), "actual")
    return ([], None, None)


_PAYSLIP_EMP_PROJ = {
    "_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "email": 1,
    "designation": 1, "department": 1, "doj": 1, "uan_no": 1, "pf_no": 1,
    "esi_ip_no": 1, "pan_no": 1, "bank_name": 1, "bank_account": 1,
    "bank_ifsc": 1,
}


@api.get("/admin/employee-payslip.pdf")
async def admin_employee_payslip_pdf(
    company_id: str, user_id: str, month: str,
    authorization: Optional[str] = Header(None),
):
    """Payslip PDF for ONE employee by firm + month (no run_id needed)."""
    from fastapi.responses import Response
    from utils.payslip_pdf import build_payslip_pdf
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not your firm")
    rows, month_days, src = await _payslip_rows_for_month(company_id, month)
    row = next((r for r in rows if r.get("user_id") == user_id), None)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="No processed salary found for this employee & month — "
                   "run the Salary Process first.")
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0}) or {}
    emp = await db.users.find_one({"user_id": user_id}, _PAYSLIP_EMP_PROJ) or {}
    pdf = build_payslip_pdf(
        employee=emp, company=company,
        row={**row, "month_days": month_days}, month=month)
    fn = f"Payslip_{(emp.get('employee_code') or user_id)}_{month}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@api.get("/admin/payslips-month.zip")
async def admin_payslips_month_zip(
    company_id: str, month: str,
    authorization: Optional[str] = Header(None),
):
    """ZIP of payslip PDFs for ALL employees of a firm + month."""
    import zipfile
    from fastapi.responses import Response
    from utils.payslip_pdf import build_payslip_pdf
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not your firm")
    rows, month_days, src = await _payslip_rows_for_month(company_id, month)
    if not rows:
        raise HTTPException(status_code=404,
                            detail="No processed salary run found for this month.")
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0}) or {}
    uids = [r.get("user_id") for r in rows if r.get("user_id")]
    emps: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find({"user_id": {"$in": uids}}, _PAYSLIP_EMP_PROJ):
        emps[u["user_id"]] = u
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            uid = r.get("user_id")
            if not uid:
                continue
            emp = emps.get(uid) or {"name": r.get("name")}
            pdf = build_payslip_pdf(
                employee=emp, company=company,
                row={**r, "month_days": month_days}, month=month)
            code = str(emp.get("employee_code") or uid).replace("/", "_")
            nm = str(emp.get("name") or "employee").replace("/", "_").replace(" ", "_")
            zf.writestr(f"{code}_{nm}_{month}.pdf", pdf)
    fn = f"Payslips_{(company.get('name') or 'firm').replace(' ', '_')}_{month}.zip"
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


class PayslipEmailBody(BaseModel):
    company_id: str
    month: str
    user_id: Optional[str] = None  # None → all employees in the run


@api.post("/admin/payslips/email")
async def admin_email_payslips(
    body: PayslipEmailBody,
    authorization: Optional[str] = Header(None),
):
    """E-mail payslip PDFs to employees' e-mail from the Employee Master.
    ``user_id`` set → one employee; omitted → every employee in the run."""
    import base64
    from utils.iter60_features import _send_email_with_attachment
    from utils.payslip_pdf import build_payslip_pdf
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != body.company_id:
        raise HTTPException(status_code=403, detail="Not your firm")
    rows, month_days, src = await _payslip_rows_for_month(body.company_id, body.month)
    if body.user_id:
        rows = [r for r in rows if r.get("user_id") == body.user_id]
    if not rows:
        raise HTTPException(status_code=404,
                            detail="No processed salary found for this month.")
    company = await db.companies.find_one(
        {"company_id": body.company_id}, {"_id": 0}) or {}
    uids = [r.get("user_id") for r in rows if r.get("user_id")]
    emps: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find({"user_id": {"$in": uids}}, _PAYSLIP_EMP_PROJ):
        emps[u["user_id"]] = u
    sent, no_email, failed = [], [], []
    for r in rows:
        uid = r.get("user_id")
        emp = emps.get(uid) or {}
        email = str(emp.get("email") or "").strip()
        if not email or "@" not in email:
            no_email.append(emp.get("name") or r.get("name") or uid)
            continue
        try:
            pdf = build_payslip_pdf(
                employee=emp, company=company,
                row={**r, "month_days": month_days}, month=body.month)
            res = await _send_email_with_attachment(
                to_emails=[email],
                subject=f"Payslip — {body.month} — {company.get('name') or ''}",
                text_body=(
                    f"Dear {emp.get('name') or ''},\n\n"
                    f"Please find attached your payslip for {body.month}.\n\n"
                    f"— {company.get('name') or 'S.K. Sharma & Co.'}"),
                attachments=[{
                    "filename": f"Payslip_{emp.get('employee_code') or uid}_{body.month}.pdf",
                    "content": base64.b64encode(pdf).decode(),
                }])
            (sent if res.get("delivered") else failed).append(
                emp.get("name") or uid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("payslip email to %s failed: %s", email, exc)
            failed.append(emp.get("name") or uid)
    return {"ok": True, "sent": len(sent), "no_email": no_email,
            "failed": failed, "source": src}



# ---------------------------------------------------------------------------
# Iter 77z-final — Off-Roll Simple Slip endpoints
# ---------------------------------------------------------------------------
# The Off-Roll slip is a minimal 4-field PDF for contract/temp employees
# (Name / Days / Rate / Amount) — no compliance / statutory columns.
# Available in two flavours:
#   • single-employee PDF: GET .../off-roll-slip/{user_id}
#   • bulk ZIP archive:    GET .../off-roll-slips.zip
# ---------------------------------------------------------------------------


@api.get("/admin/salary-runs/{run_id}/off-roll-slip/{user_id}")
async def download_off_roll_slip_pdf(
    run_id: str,
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return the Off-Roll Simple Slip PDF for a single employee.

    Only rows tagged ``run_type == "off_roll"`` are eligible. Company
    admins may only download slips for their own firm.
    """
    from fastapi.responses import Response
    from utils.off_roll_slip_pdf import build_off_roll_slip_pdf

    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if run.get("run_type") != "off_roll":
        raise HTTPException(
            status_code=400,
            detail="Off-Roll slips are only available for off-roll salary runs.",
        )
    row = next((r for r in (run.get("rows") or []) if r.get("user_id") == user_id), None)
    if not row:
        raise HTTPException(status_code=404, detail="Employee row not found in this run")
    company = await db.companies.find_one(
        {"company_id": run.get("company_id")}, {"_id": 0, "name": 1},
    ) or {}
    period_label = run.get("month") or ""
    pdf_bytes = build_off_roll_slip_pdf(
        company_name=company.get("name") or "Company",
        period_label=period_label,
        row=row,
    )
    safe_code = (row.get("employee_code") or user_id).replace("/", "_")
    safe_name = (row.get("name") or "employee").replace("/", "_").replace(" ", "_")
    fname = f"OffRollSlip_{safe_code}_{safe_name}_{period_label}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.get("/admin/salary-runs/{run_id}/off-roll-slips.zip")
async def download_bulk_off_roll_slips_zip(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return a ZIP archive of Off-Roll Simple Slip PDFs — one per row."""
    from fastapi.responses import Response
    from utils.off_roll_slip_pdf import build_off_roll_slip_pdf
    import zipfile

    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if run.get("run_type") != "off_roll":
        raise HTTPException(
            status_code=400,
            detail="Off-Roll slips are only available for off-roll salary runs.",
        )
    company = await db.companies.find_one(
        {"company_id": run.get("company_id")}, {"_id": 0, "name": 1},
    ) or {}
    period_label = run.get("month") or ""
    rows = run.get("rows") or []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            if not r.get("user_id"):
                continue
            pdf_bytes = build_off_roll_slip_pdf(
                company_name=company.get("name") or "Company",
                period_label=period_label,
                row=r,
            )
            safe_code = (r.get("employee_code") or r.get("user_id")).replace("/", "_")
            safe_name = (r.get("name") or "employee").replace("/", "_").replace(" ", "_")
            zf.writestr(
                f"OffRollSlip_{safe_code}_{safe_name}_{period_label}.pdf",
                pdf_bytes,
            )
    fname = (
        f"OffRollSlips_{(company.get('name') or 'firm').replace(' ', '_')}_{period_label}.zip"
    )
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )



@api.get("/admin/reports/annual.xlsx")
async def download_annual_report_xlsx(
    fy: str = Query(..., description="Financial year e.g. 2025-26"),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Multi-sheet Annual Report XLSX for one firm and one FY.

    Sheets: Summary · Salary (per-employee) · Attendance · PF & ESIC.
    Company-admins are scoped to their own firm; super/sub-admin must
    pass ``company_id`` explicitly.
    """
    from fastapi.responses import Response
    from utils.annual_report import build_annual_report_xlsx

    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        cid = admin.get("company_id")
    else:
        cid = company_id
    if not cid:
        raise HTTPException(
            status_code=400,
            detail="company_id is required — pick a firm before downloading the annual report.",
        )
    company = await db.companies.find_one({"company_id": cid}, {"_id": 0}) or {}
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    xlsx_bytes = await build_annual_report_xlsx(
        db,
        company_id=cid,
        fy=fy,
        company_name=company.get("name") or "Company",
    )
    fname = (
        f"AnnualReport_{(company.get('name') or 'firm').replace(' ', '_')}_FY{fy}.xlsx"
    )
    return Response(
        content=xlsx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.post("/admin/salary-runs/{run_id}/generate-payslips")
async def generate_payslips_from_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """Push a computed salary run into per-employee payslip records so the
    Employee Payslips screen picks them up. Idempotent per (user_id,
    month) — re-running replaces the previous slip for that month."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "salary_process:write", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    month = run["month"]
    created = 0
    skipped_pre_doj = 0
    for r in (run.get("rows") or []):
        uid = r.get("user_id")
        if not uid:
            continue
        # Iter 57 safety: never generate a payslip for a month before the
        # employee's date-of-joining, even if the row somehow slipped through
        # the compute filter.
        emp = await db.users.find_one({"user_id": uid}, {"_id": 0, "doj": 1})
        if emp and _month_is_before_doj(emp, month):
            skipped_pre_doj += 1
            continue
        # Replace any existing slip for this employee+month
        await db.payslips.delete_many({"employee_user_id": uid, "month": month})
        slip = {
            "slip_id": f"slp_{uuid.uuid4().hex[:12]}",
            "employee_user_id": uid,
            "company_id": r.get("company_id") or run.get("company_id"),
            "month": month,
            "gross": r.get("gross", 0.0),
            "deductions": r.get("total_deduction", 0.0),
            "net": r.get("net", 0.0),
            "status": "paid",
            "generated_by": admin["user_id"],
            "generated_at": now_iso(),
            "salary_run_id": run_id,
            "breakup": {
                "base_pay": r.get("base_pay"),
                "bonus": r.get("bonus"),
                "ot_pay": r.get("ot_pay"),
                "advance": r.get("advance"),
                "present_days": r.get("present_days"),
                "half_days": r.get("half_days"),
                "ot_hours": r.get("ot_hours"),
                "month_days": r.get("month_days"),
            },
        }
        await db.payslips.insert_one(slip)
        created += 1
    await db.salary_runs.update_one(
        {"run_id": run_id},
        {"$set": {"payslips_generated_at": now_iso(), "payslips_count": created}},
    )

    # Iter 61: fire payslip auto-email if the company has enabled it.
    # This is best-effort and does not block/fail the payslip generation.
    email_summary: Optional[Dict[str, Any]] = None
    try:
        email_hook = getattr(app.state, "email_payslips_for_run", None)
        if email_hook is not None:
            email_summary = await email_hook(db, run_id, dry_run=False)
    except Exception:  # noqa: BLE001
        logger.exception("Payslip auto-email hook failed")
    return {
        "ok": True,
        "payslips_count": created,
        "skipped_pre_doj": skipped_pre_doj,
        "email_summary": email_summary,
    }

