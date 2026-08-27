"""Iter 394 — COMPLIANCE SALARY RUNS module (extracted from server.py).

Refactor only: every endpoint, model and helper below was MOVED verbatim
from server.py (create/process, list, save-rows, finalize with the
Iter-388 validation gate, unlock, reprocess, CSV/XLSX/register/ECR/ESIC
exports and payslip generation). No behavioural change.
"""
import math
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from pydantic import BaseModel

from server import (  # noqa: E402
    _compute_monthly_grid_data,
    _policy2_biometric_stats,
    db,
    get_user_from_token,
    holiday_dates_for_company,
    logger,
    now_iso,
    require_employer_permission,
    require_role,
    require_super_admin_strict,
)

from shared.sorting import _sort_export_rows  # noqa: E402

from shared.dates import (  # noqa: E402
    _month_is_after_exit,
    _month_is_before_doj,
)
from routes.attendance_core import _onboarding_payroll_exclusion  # noqa: E402

router = APIRouter(prefix="/api")
api = router  # endpoints below keep their original @api.* decorators

class ComplianceSalaryRunCreate(BaseModel):
    """Body for POST /api/admin/compliance-salary-runs.

    * ``month`` — YYYY-MM (e.g. "2026-06")
    * ``month_days`` — optional override; defaults to actual days in month
    * ``employee_type`` — optional filter (e.g. "Staff"). Pass "unset" for
      employees without a type. Omit or "all" for no filter.
    * ``is_onroll`` — True → only on-roll, False → only off-roll, null → both.
    * ``structure_pct`` — optional company-wide salary-structure percentages
      overriding the module defaults. Recognised keys: basic, hra,
      conveyance, medical, special, others.
    * ``statutory_cfg`` — optional overrides for statutory rates. Keys:
      pf_percent_employee, pf_wage_cap, pf_percent_employer_epf,
      pf_percent_employer_eps, esic_percent_employee, esic_percent_employer,
      esic_gross_threshold, stat_wage_floor_pct.
    """
    month: str
    company_id: Optional[str] = None
    month_days: Optional[int] = None
    employee_type: Optional[str] = None
    is_onroll: Optional[bool] = None
    structure_pct: Optional[Dict[str, float]] = None
    statutory_cfg: Optional[Dict[str, float]] = None
    # Iter 101 — import Present Days + Other Deductions from the imported
    # salary sheet (file upload / Gmail attachment) instead of biometric.
    use_imported_sheet: Optional[bool] = False
    # Iter 330 (user request) — copy LAST MONTH's salary into this month
    # exactly as it was (same Present Days / Gross / PF / ESIC / Net).
    copy_last_month: Optional[bool] = False
    # Iter 426 (user request) — reprocess FROM BLANK: rebuild the sheet
    # fresh from attendance + master, DISCARDING the previous draft's
    # manually entered days / edits.
    fresh: Optional[bool] = False
    # Iter 429 (user request) — admin explicitly confirmed a DIFFERENT
    # month-days figure for an already-processed month.
    override_month_days: Optional[bool] = False


async def _compute_compliance_run(
    admin: dict,
    payload: ComplianceSalaryRunCreate,
    prev_rows: Optional[Dict[str, dict]] = None,
    allow_snapshot_create: bool = True,
) -> dict:
    """Shared compute path for compliance salary runs. Mirrors the base
    salary run pipeline (same attendance stats + policy merge) but uses
    ``utils.compliance_salary.compute_compliance_row`` for the payroll
    line items."""
    from utils.salary_run import (
        actual_days_in_month, parse_month, compute_present_days_and_ot,
    )
    from utils.compliance_salary import compute_compliance_row
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
    # Iter 164 (user directive) — Compliance Salary Process is STRICTLY
    # ON-ROLL: off-roll employees are excluded from compliance runs no
    # matter what filter the caller sent. The dedicated off-roll run type
    # (Iter 77j) is the only exception.
    run_type = (getattr(payload, "run_type", None) or "compliance").lower()
    if run_type == "off_roll":
        q["is_onroll"] = False
    else:
        q.pop("is_onroll", None)
        q.setdefault("$and", []).append({
            "$or": [
                {"is_onroll": True},
                {"is_onroll": {"$exists": False}},
                {"is_onroll": None},
            ]
        })

    # Iter 285 — exclude unapproved (onboarding) employees unless the firm
    # policy allows statutory processing before approval.
    await _onboarding_payroll_exclusion(
        q, payload.company_id, ["allow_pf", "allow_esic", "allow_tds"])

    employees = await db.users.find(q, {"_id": 0}).to_list(2000)

    # ---- Iter 485 — MASTER DATA SNAPSHOT (enterprise payroll freeze) ----
    # First generation of firm+month+group freezes every salary-related
    # master value. Reprocess / Delete+Generate read the snapshot instead
    # of the live Employee Master; attendance/OT/leave/advances stay live.
    from utils.master_snapshot import (
        load_master_snapshot, create_master_snapshot, append_new_employees,
        overlay_snapshot,
    )
    _snap_cid = q.get("company_id")
    _snap_map: Dict[str, dict] = {}
    _snap_meta: Optional[dict] = None
    if _snap_cid:
        _snap_map = await load_master_snapshot(
            db, _snap_cid, payload.month, run_type, payload.employee_type)
    if _snap_map:
        _seen_uids = set()
        _overlaid = []
        for e in employees:
            sd = _snap_map.get(e.get("user_id"))
            if sd is not None:
                _seen_uids.add(e["user_id"])
                _overlaid.append(overlay_snapshot(e, sd.get("data") or {}))
            else:
                _overlaid.append(e)  # new joiner — live master (frozen below)
        # Employees REMOVED from the master (or moved out of the group)
        # after the snapshot: resurrect from the snapshot so a
        # Delete + Generate-Again reproduces the identical payroll.
        # Iter 491 (user bug — "Employees Was Delete From Firm Master ...
        # Still Show in Compliance Salary") — resurrect ONLY employees
        # that still EXIST in the Employee Master (e.g. moved out of the
        # group / filters). An employee DELETED from the master data must
        # NEVER re-appear in the salary run.
        _ghost_uids = [u for u in _snap_map if u not in _seen_uids]
        _alive_uids: set = set()
        if _ghost_uids:
            async for _au in db.users.find(
                    {"user_id": {"$in": _ghost_uids}}, {"_id": 0, "user_id": 1}):
                _alive_uids.add(_au["user_id"])
        for _uid, sd in _snap_map.items():
            if _uid in _seen_uids:
                continue
            if _uid not in _alive_uids:
                continue  # deleted from the master — stays out of the run
            _ghost = dict(sd.get("data") or {})
            _ghost["user_id"] = _uid
            _ghost.setdefault("company_id", _snap_cid)
            _ghost.setdefault("employee_code", sd.get("employee_code"))
            _ghost["role"] = "employee"
            _overlaid.append(_ghost)
        employees = _overlaid
        _snap_meta = {
            "used": True,
            "version": int(next(iter(_snap_map.values())).get("version") or 1),
            "employees": len(_snap_map),
        }

    # Iter 167 — "Resigned this month" summary: capture who gets auto-
    # excluded because they resigned/exited before the run month starts,
    # so the Compliance Salary screen can show the list.
    excluded_resigned = [
        {"user_id": e.get("user_id"), "name": e.get("name"),
         "employee_code": e.get("employee_code"),
         "exit_date": str(e.get("exit_date") or e.get("resign_date") or "")[:10]}
        for e in employees if _month_is_after_exit(e, payload.month)
    ]
    excluded_resigned.sort(key=lambda x: (x.get("name") or "").lower())

    # Iter 57 — Exclude employees whose date-of-joining is AFTER the run's
    # month end. Payslips must never be generated for pre-DOJ months.
    employees = [e for e in employees if not _month_is_before_doj(e, payload.month)
                 and not _month_is_after_exit(e, payload.month)
                 and e.get("disabled") is not True]  # Iter 166/168

    # Iter 485 — snapshot bookkeeping AFTER the scope filters, so the
    # frozen set matches exactly who is in the run.
    if _snap_cid:
        if not _snap_map and allow_snapshot_create and employees:
            # FIRST generation → freeze v1. NEVER created on reprocess.
            _n = await create_master_snapshot(
                db, _snap_cid, payload.month, run_type,
                payload.employee_type, employees, admin)
            _snap_meta = {"used": False, "created": True, "version": 1,
                          "employees": _n}
        elif _snap_map:
            # New joiners after the freeze: append THEM to the active
            # version (frozen from now on) — spec: read master once.
            _new = [e for e in employees
                    if e.get("user_id") not in _snap_map]
            if _new:
                await append_new_employees(
                    db, _snap_cid, payload.month, run_type,
                    payload.employee_type, _new, admin,
                    version=int(_snap_meta["version"]) if _snap_meta else 1)
                if _snap_meta:
                    _snap_meta["appended"] = len(_new)

    # Iter 127f/g — statutory config precedence: global Standard Compliance
    # Settings < firm-specific overrides (Firm Master) < per-run cfg.
    from routes.compliance_settings import (
        get_standard_compliance_cfg,
        get_firm_statutory_overrides,
    )
    _std_cfg = await get_standard_compliance_cfg(on_date=f"{payload.month}-31")
    _firm_over = await get_firm_statutory_overrides(payload.company_id)
    effective_statutory = {**_std_cfg, **_firm_over, **(payload.statutory_cfg or {})}
    # Iter 622 (user decision) — PF & ESIC proration LOCKED to the sheet's
    # entered Month Days. Forced here too so the grid's client-side mirror,
    # the View-Calculation layer and the PF badge all reflect the lock even
    # when old settings still store working_days / attendance_days.
    effective_statutory["pf_proration_method"] = "calendar_days"
    effective_statutory["esic_proration_method"] = "calendar_days"
    # Iter 387 — salary month for the engine's ESIC Exit-Date rule.
    effective_statutory["_salary_month"] = payload.month


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
            {"_id": 0, "user_id": 1, "kind": 1, "at": 1, "date": 1,
             "status": 1, "source": 1},
        ):
            attendance_by_user.setdefault(r["user_id"], []).append(r)

    # Iter 101 — Imported salary sheet: manual Present Days + Other
    # Deductions (uploaded file / Gmail attachment) override the biometric
    # attendance for this run.
    am_entries: dict = {}
    if payload.use_imported_sheet:
        _am_q: dict = {"month": payload.month}
        if q.get("company_id"):
            _am_q["company_id"] = q["company_id"]
        async for e in db.compliance_import_entries.find(_am_q, {"_id": 0}):
            am_entries[e["user_id"]] = e

    # Iter 745 — POLICY-BASED LATE PENALTY auto-deduction maps. Built only
    # for firms whose Attendance Policy EXPLICITLY enables late_penalty;
    # imported-sheet runs skip (the sheet is authoritative — the manual
    # Apply button on the Late Penalty screen still works there).
    late_penalty_maps: Dict[str, dict] = {}
    if not payload.use_imported_sheet:
        from routes.hr_extras import policy_late_penalty_map
        for _cid_lp in {e.get("company_id") for e in employees if e.get("company_id")}:
            try:
                _m_lp = await policy_late_penalty_map(_cid_lp, payload.month)
            except Exception:
                _m_lp = {}
            if _m_lp:
                late_penalty_maps[_cid_lp] = _m_lp

    # Iter 746 — APPROVED-OT override maps (user PRD): ONLY when a firm's
    # OT Policy is enabled AND approval_required, payroll uses the APPROVED
    # OT hours instead of raw grid OT (unapproved/excess OT never slips
    # into payroll silently). Firms without the policy stay exactly as-is.
    approved_ot_maps: Dict[str, dict] = {}
    if not payload.use_imported_sheet:
        from routes.ot_management import approved_ot_hours_map
        for _cid_ot in {e.get("company_id") for e in employees if e.get("company_id")}:
            try:
                _m_ot = await approved_ot_hours_map(_cid_ot, payload.month)
            except Exception:
                _m_ot = None
            if _m_ot is not None:
                approved_ot_maps[_cid_ot] = _m_ot

    # Iter 216 (user request) — Compliance Present Days are FETCHED from
    # the Attendance Report grid (the exact same source the Actual Salary
    # Process uses) so the compliance run always matches the report.
    # Imported-sheet runs keep their own source.
    grid_by_user_c: Dict[str, Any] = {}
    if not payload.use_imported_sheet:
        # Iter 217 — resolve grids for EVERY firm in scope (not just the
        # payload's company_id) so super-admin runs without an explicit
        # firm filter still auto-fetch from the Attendance Report.
        for _cidg in {e.get("company_id") for e in employees if e.get("company_id")}:
            try:
                _grid_c = await _compute_monthly_grid_data(_cidg, payload.month)
                for gr in _grid_c.get("employees") or _grid_c.get("rows") or []:
                    grid_by_user_c[gr["user_id"]] = gr
            except HTTPException:
                continue

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
                # Iter 503 — Single Machine Attendance Mode config.
                "attendance_config": 1,
            },
        ):
            company_policies[c["company_id"]] = c

    # Iter 98 — Firm Master EPF / ESI "Applicable" flags gate the statutory
    # calculation firm-wide. When OFF (or the firm has no Firm Master
    # record), PF / ESIC are NOT calculated for that firm's employees.
    firm_stat_flags: dict = {}
    if company_ids:
        async for fm in db.firm_masters.find(
            {"company_id": {"$in": company_ids}},
            {"_id": 0, "company_id": 1, "epf": 1, "esi": 1,
             "salary_process": 1, "allowances": 1, "deductions": 1},
        ):
            _fm_allow = fm.get("allowances") or {}
            _fm_ded = fm.get("deductions") or {}
            # Iter 171 (user request) — Firm Master Allowances/Deductions
            # toggles drive the Compliance Salary columns. A mask of None
            # means the firm never configured that catalog (show defaults).
            _amap = {"HRA": "hra", "CONV.": "conveyance",
                     "MEDICAL ALLOWANCES": "medical", "OTH. ALLOW.": "special",
                     "OTHER MISC.ALLOWANCE": "others",
                     # Iter 644 (user bug — "OT not allowed but showing") —
                     # the "OVER TIME" catalog toggle now drives the OT Hrs
                     # / OT Amt* columns dynamically like every other head.
                     "OVER TIME": "ot"}
            allow_mask = {h for lbl, h in _amap.items() if _fm_allow.get(lbl)}
            # Iter 369 (user request) — EPF / ESI "Applicable" flags are
            # AUTHORITATIVE when explicitly set (True or False): disabled
            # means NO PF/ESIC even if the Deductions catalog has PF/ESI
            # ticked. Only when the flag was never configured (None) do we
            # fall back to the Deductions catalog (keeps the Iter 335 fix).
            _epf_ap = (fm.get("epf") or {}).get("applicable")
            _esi_ap = (fm.get("esi") or {}).get("applicable")
            _pf_col = bool(_epf_ap) if _epf_ap is not None else bool(_fm_ded.get("PF"))
            _esi_col = bool(_esi_ap) if _esi_ap is not None else bool(_fm_ded.get("ESI"))
            ded_mask = set()
            if _pf_col:
                ded_mask.add("pf")
            if _esi_col:
                ded_mask.add("esi")
            if _fm_ded.get("PT"):
                ded_mask.add("pt")
            if _fm_ded.get("TDS") or _fm_ded.get("I. TAX"):
                ded_mask.add("tds")
            # Iter 443 (user request) — Master-linked ADVANCE / OTH. DEDUC.
            # heads gate the built-in Advance* / Other* columns dynamically.
            if _fm_ded.get("ADVANCE"):
                ded_mask.add("advance")
            if _fm_ded.get("OTH. DEDUC."):
                ded_mask.add("other")
            # Iter 420 (user request) — CUSTOM deduction heads enabled in
            # the Firm Master (ADVANCE / UNIFORM / CANTEEN / …) become
            # their own DYNAMIC columns on the Compliance Salary sheet.
            _STAT_DED = {"PF", "ESI", "PT", "TDS", "I. TAX"}
            custom_ded_labels = sorted(
                lbl for lbl, on in _fm_ded.items()
                if on and str(lbl).strip().upper() not in _STAT_DED)
            # Iter 644 (user request — "INCENTIVE ticked but not showing")
            # — CUSTOM allowance heads enabled in the Firm Master
            # (INCENTIVE / BONUS / DA / …) become their own DYNAMIC columns
            # on the sheet (mirrors the Iter 420 deduction columns).
            _STAT_ALLOW = set(_amap)
            custom_allow_labels = sorted(
                lbl for lbl, on in _fm_allow.items()
                if on and str(lbl).strip().upper() not in _STAT_ALLOW)
            firm_stat_flags[fm["company_id"]] = {
                # Iter 369 — "Applicable" flag authoritative (see above).
                "pf": _pf_col,
                "esic": _esi_col,
                # Iter 369 (user request) — MASTER SALARY (Full Month)
                # columns follow the Firm Master Allowances catalog
                # DYNAMICALLY: if the firm configured the catalog, the mask
                # applies even when every head is switched OFF (only Basic
                # + Gross remain). None only when never configured.
                "allow_mask": allow_mask if _fm_allow else None,
                "ded_mask": ded_mask if any(bool(v) for v in _fm_ded.values()) else None,
                # Iter 420 — dynamic custom deduction heads (None when the
                # firm never configured the Deductions catalog).
                "custom_ded_labels": custom_ded_labels if _fm_ded else None,
                # Iter 644 — dynamic custom allowance heads (None when the
                # firm never configured the Allowances catalog).
                "custom_allow_labels": custom_allow_labels if _fm_allow else None,
                # Iter 310 — Freeze Salary difference allocation gate.
                "ot_allowed": bool((fm.get("salary_process") or {}).get("ot_allowed")),
                # Iter 337 (user request) — Days Calculation Method.
                "days_calc_method": str((fm.get("salary_process") or {}).get("days_calc_method") or "attendance_gross_validation"),
                "days_calc_fixed": (fm.get("salary_process") or {}).get("days_calc_fixed") or 26,
                "days_calc_rounding": (fm.get("salary_process") or {}).get("days_calc_rounding", 0.5),
            }
            # Iter 142 — Firm Master OT gate for compliance-salary rows.
            _v = (fm.get("salary_process") or {}).get("ot_allowed")
            if _v is not None and fm["company_id"] in company_policies:
                _ap = dict(company_policies[fm["company_id"]].get("attendance_policy") or {})
                _ap["firm_ot_allowed"] = bool(_v)
                company_policies[fm["company_id"]]["attendance_policy"] = _ap

    # Iter 443 (user request) — "Freeze as Actual Gross" firms: the ACTUAL
    # Salary Process run of the SAME month feeds the compliance run —
    # Total Gross → Freeze gross · Adv → Advance · TDS → TDS ·
    # Other Ded.* → Other Deductions. Newest run wins per employee.
    _fag_cids = [c for c, f in firm_stat_flags.items()
                 if str(f.get("days_calc_method") or "") == "freeze_actual_gross"]
    actual_by_user: Dict[str, dict] = {}
    _fag_used = False
    if _fag_cids:
        async for _ar in db.salary_runs.find(
            {"run_type": "actual", "month": payload.month,
             "company_id": {"$in": _fag_cids}},
            {"_id": 0, "rows": 1},
            sort=[("generated_at", -1)],
        ):
            for _r in _ar.get("rows") or []:
                if _r.get("user_id"):
                    actual_by_user.setdefault(_r["user_id"], _r)

    rows = []
    # Iter 200 — Holiday Master dates per firm (for holiday_present_add_ot).
    _holidays_by_cid: Dict[str, list] = {}
    for _cid_ in {e.get("company_id") for e in employees if e.get("company_id")}:
        _holidays_by_cid[_cid_] = sorted(await holiday_dates_for_company(_cid_))
    # Iter 313 — ESIC Leave Module: auto-import APPROVED ESIC leave days
    # into the run (per firm, honours enabled + link_compliance settings).
    from routes.esic_leave import esic_leave_days_map as _esic_map_fn
    from routes.esic_leave import get_esic_settings as _esic_st_fn
    _esic_maps: Dict[str, Dict[str, float]] = {}
    _esic_on: Dict[str, bool] = {}
    for _cid_ in {e.get("company_id") for e in employees if e.get("company_id")}:
        _esic_maps[_cid_] = await _esic_map_fn(_cid_, payload.month)
        _st_ = await _esic_st_fn(_cid_)
        _esic_on[_cid_] = bool(_st_.get("enabled") and _st_.get("link_compliance"))
    # Iter 500 — CTC MODE (additive): preload the CTC structures assigned to
    # CTC-mode employees so their compliance gross can be derived from the
    # Monthly CTC (gross = CTC − employer cost). Gross-mode employees are
    # completely untouched.
    from routes.ctc_module import calc_ctc_breakup as _ctc_calc
    _ctc_smap: Dict[str, dict] = {}
    _ctc_sids = {e.get("ctc_structure_id") for e in employees
                 if str(e.get("salary_mode") or "").lower() == "ctc"
                 and e.get("ctc_structure_id")}
    if _ctc_sids:
        async for _s_ in db.ctc_structures.find(
                {"structure_id": {"$in": list(_ctc_sids)}}, {"_id": 0}):
            _ctc_smap[_s_["structure_id"]] = _s_
    for emp in employees:
        emp = dict(emp)
        emp.pop("pin_hash", None)
        emp.pop("password_hash", None)
        emp.pop("temp_pin_plaintext", None)
        emp.pop("temp_password_plaintext", None)
        pol = emp.get("employee_policy") or {}
        company_doc = company_policies.get(emp.get("company_id")) or {}
        att_pol = company_doc.get("attendance_policy") or {}
        merged_pol = {**att_pol, **pol}
        merged_pol["_holiday_dates"] = _holidays_by_cid.get(emp.get("company_id")) or []
        # Iter 142 — per-employee OT flag (override wins over legacy flag).
        _emp_ot = (emp.get("attendance_policy_override") or {}).get(
            "ot_allowed", emp.get("ot_applicable"))
        if _emp_ot is not None:
            merged_pol["ot_allowed"] = bool(_emp_ot)
        # Iter 500 — CTC MODE: derive this employee's compliance gross from
        # the Monthly CTC via the assigned CTC structure. The engine then
        # runs EXACTLY as before on that gross (proration, PF/ESIC/PT, OT —
        # all unchanged); the CTC employer-side figures ride along on the
        # row for the register / payslips / reports.
        _ctc_meta = None
        if (str(emp.get("salary_mode") or "").lower() == "ctc"
                and float(emp.get("monthly_ctc") or 0) > 0):
            _s_ctc = _ctc_smap.get(emp.get("ctc_structure_id") or "")
            if _s_ctc:
                _bk = _ctc_calc(float(emp.get("monthly_ctc") or 0),
                                _s_ctc.get("components") or [])
                merged_pol = dict(merged_pol)
                merged_pol["salary"] = _bk["gross"]
                emp["compliance_gross"] = _bk["gross"]
                emp["salary_monthly"] = _bk["gross"]
                emp["compliance_salary_mode"] = "monthly"
                _ctc_meta = {
                    "monthly_ctc": _bk["monthly_ctc"],
                    "ctc_structure_id": _s_ctc["structure_id"],
                    "ctc_structure_name": _s_ctc.get("name") or "",
                    "ctc_gross_derived": _bk["gross"],
                    "ctc_employer_total": _bk["employer_total"],
                    "ctc_employer_contributions": _bk["employer_contributions"],
                }
        att_rows = attendance_by_user.get(emp["user_id"], [])
        _pm_202 = (att_pol.get("policy_master") or {})
        if (att_pol.get("policy_variant") or "").strip() == "policy_2":
            # Iter 129c — Textile Policy 2: Present Days auto-synced from
            # biometrics via the grid's textile pipeline (8 hrs = 1 day).
            stats = _policy2_biometric_stats(
                att_rows, merged_pol, emp,
                company_cfg=company_doc.get("attendance_config"))
        else:
            # Iter 202 — "Count Present Day @ 8 HRS" sub-point: compliance
            # runs count 1 Present Day per 8 worked hrs (extra hrs → OT)
            # when the firm's Salary Allowed includes Compliance.
            if _pm_202.get("compliance_present_8hr") and \
                    (att_pol.get("salary_allowed") or "both") in ("compliance", "both"):
                merged_pol["_present_day_hours_override"] = 8.0
            stats = compute_present_days_and_ot(att_rows, merged_pol)
        # Iter 216 (user request) — override with the Attendance Report's
        # Present Days + OT so the Compliance Salary run always agrees
        # with the report (and the Actual process). Applies to policy_2
        # firms too.
        # Iter 219 — "Count Present Day @ 8 HRS" now ALSO direct-syncs
        # from the Attendance Report grid (same punch pipeline as the
        # report): per day, 8+ worked hrs = 1 Present Day with the extra
        # hrs → OT; the Half-Day Threshold Rule is honoured (½ day, rest
        # → OT); week-off / holiday sub-points mirror the grid compute.
        _g_c = grid_by_user_c.get(emp["user_id"])
        _c8_on = bool(_pm_202.get("compliance_present_8hr")) and \
            (att_pol.get("salary_allowed") or "both") in ("compliance", "both")
        if _g_c and _c8_on:
            _half_h8 = float(merged_pol.get("half_day_hours") or 4.0)
            _hd_rule8 = bool(_pm_202.get("halfday_threshold_rule"))
            _pd8 = 0.0
            _half8 = 0
            _duty8 = 0.0
            _ot8 = 0.0
            for _dcell in (_g_c.get("days") or {}).values():
                _dcell = _dcell or {}
                _w = float(_dcell.get("hours") or _dcell.get("raw_hours") or 0.0)
                if _w <= 0:
                    continue
                if _dcell.get("weekly_off") and _pm_202.get("weekoff_present_add_ot"):
                    _ot8 += _w
                    continue
                if _dcell.get("holiday") and _pm_202.get("holiday_present_add_ot"):
                    _pd8 += 1.0
                    _ot8 += _w
                    continue
                if _w >= 8.0:
                    _pd8 += 1.0
                    _duty8 += 8.0
                    _ot8 += _w - 8.0
                elif _hd_rule8 and _w >= _half_h8:
                    _half8 += 1
                    _duty8 += _half_h8
                    _ot8 += _w - _half_h8
                elif _hd_rule8:
                    _ot8 += _w
                else:
                    if _w >= _half_h8:
                        _half8 += 1
                    _duty8 += _w
            if merged_pol.get("ot_allowed") is False or \
                    merged_pol.get("firm_ot_allowed") is False:
                _ot8 = 0.0
            _eff8 = _pd8 + 0.5 * _half8
            stats = {
                "present_days": round(_eff8 * 2) / 2.0,
                "half_days": _half8,
                "absent_days": 0,
                "duty_hours": round(_duty8, 2),
                "ot_hours": round(_ot8, 2),
                "effective_present": _eff8,
            }
        elif _g_c and not _c8_on:
            _t_c = _g_c.get("totals") or {}
            _pd_c = _t_c.get("present_days_policy")
            if _pd_c is None:
                _pd_c = _t_c.get("total_days_computed")
            if _pd_c is not None:
                _pd_cf = float(_pd_c or 0.0)
                stats = dict(stats)
                # Iter 219 — keep half days (26.5) instead of int().
                stats["present_days"] = round(_pd_cf * 2) / 2.0
                stats["effective_present"] = _pd_cf
                stats["half_days"] = 0
                stats["duty_hours"] = float(
                    _t_c.get("duty_hours")
                    or _t_c.get("hours")
                    or stats.get("duty_hours")
                    or 0.0
                )
                stats["ot_hours"] = float(_t_c.get("ot_hours") or 0.0)
        # Iter 746 — approval-required firms: payroll OT = APPROVED OT only
        # (grid OT is replaced by the month's approved eligible hours).
        _aot_map746 = approved_ot_maps.get(emp.get("company_id"))
        if _aot_map746 is not None:
            stats["ot_hours"] = float(_aot_map746.get(emp["user_id"], 0.0))
        _am = am_entries.get(emp["user_id"]) if payload.use_imported_sheet else None
        # Iter 443 (user request) — "Freeze as Actual Gross": the ACTUAL
        # Salary Process run of the SAME month is the authoritative import
        # source. Its Total Gross becomes the Freeze gross; Adv / TDS /
        # Other Ded.* import into the matching deduction columns below.
        _fag_row = None
        if str((firm_stat_flags.get(emp.get("company_id")) or {}).get(
                "days_calc_method") or "") == "freeze_actual_gross":
            _fag_row = actual_by_user.get(emp["user_id"])
        if _fag_row is not None:
            _fag_used = True
            # Iter 616 (user bug) — this merge used to CLOBBER the uploaded
            # sheet's deduction (e.g. ADVANCE 500) with the Actual run's
            # "Other Ded." value; the sheet's own head/amount now survives
            # and the Actual "Other Ded.*" is carried separately below.
            _am = {
                **(_am or {}),
                "gross_earning": round(float(_fag_row.get("total_gross") or 0), 2),
                "present_days": float((_am or {}).get("present_days")
                                      or _fag_row.get("p_days") or 0),
                "tds": round(float(_fag_row.get("tds") or 0), 2),
                "deduction_amount": float((_am or {}).get("deduction_amount") or 0),
                "deduction_head": (_am or {}).get("deduction_head") or "",
                "other_less": float((_am or {}).get("other_less") or 0.0),
                # Actual run "Other Ded.*" → Other Deductions column.
                "actual_other_ded": round(float(_fag_row.get("other_ded") or 0), 2),
            }
        # A row is FREEZE-driven when the sheet was imported OR the firm
        # uses Freeze-as-Actual-Gross and an Actual run row exists.
        _frz_imp = bool(payload.use_imported_sheet or _fag_row is not None)
        _frz_days_manual = False
        if _frz_imp:
            # Imported sheet wins: present days from the uploaded/email
            # salary sheet (0 when the employee has no row).
            # Iter 219 — half days (e.g. 18.5) are kept, not truncated.
            # Iter 340 (user request) — NEVER above the month's days.
            _pd = min(float((_am or {}).get("present_days") or 0),
                      float(month_days))
            # Iter 723 (user bug — "Reprocess changes the data AGAIN"):
            # Freeze-as-Actual-Gross firms re-pulled the days from the
            # Actual run on EVERY reprocess, wiping the admin's edited
            # Present Days. "With EXISTING Data" promises entered days
            # are KEPT (Iter 297 directive), so a previously saved row
            # whose days differ (or carry the manual stamp) keeps its
            # saved days. Imported-sheet runs keep the sheet
            # authoritative; "From BLANK" still rebuilds fresh.
            # Iter 757 (user bug — "reprocess shows the FIRST imported
            # sheet"): on imported-sheet runs a MANUALLY edited Present
            # Days (explicit manual_fields stamp) is kept too — only
            # untouched rows stay sheet-authoritative.
            _prev_frz = (prev_rows or {}).get(emp["user_id"])
            if payload.use_imported_sheet and _prev_frz is not None and \
                    "present_days" not in set(_prev_frz.get("manual_fields") or []):
                _prev_frz = None
            if _prev_frz is not None:
                _ppd_frz = min(float(_prev_frz.get("present_days") or 0.0),
                               float(month_days))
                _mf_frz = set(_prev_frz.get("manual_fields") or [])
                if "present_days" in _mf_frz or abs(_ppd_frz - _pd) > 0.01:
                    _pd = _ppd_frz
                    _frz_days_manual = True
            _fdh = float(merged_pol.get("full_day_hours") or 8.0)
            stats = {
                "present_days": round(_pd * 2) / 2.0,
                "half_days": 0,
                "effective_present": _pd,
                "duty_hours": round(_pd * _fdh, 2),
                "ot_hours": 0.0,
            }
        # Iter 270 (user request) — "OT Include in Existing Compliance
        # Salary" (Yes/No). When NO, OT Duty HRS are kept OUT of the
        # Compliance Salary (no OT pay in gross) — they auto-import into
        # the separate OT Salary Process instead (no double payment).
        if not _pm_202.get("compliance_ot_include", True):
            stats = dict(stats)
            stats["ot_hours"] = 0.0
        # Iter 427 (user request) — FIXED DAYS (26 / 30 / 31) method now
        # also drives the NORMAL Salary Process (it previously applied to
        # Salary Imports only): every employee is processed at the firm's
        # Fixed Days regardless of attendance. Manually edited days still
        # win on a reprocess (Iter 297 carry below).
        if not payload.use_imported_sheet:
            _dcm0 = firm_stat_flags.get(emp.get("company_id")) or {}
            if str(_dcm0.get("days_calc_method") or "attendance") == "fixed":
                _fx = min(float(_dcm0.get("days_calc_fixed") or 26),
                          float(month_days))
                stats = dict(stats)
                stats["present_days"] = _fx
                stats["effective_present"] = _fx
                stats["half_days"] = 0
                stats["duty_hours"] = round(
                    _fx * float(merged_pol.get("full_day_hours") or 8.0), 2)
        # Iter 297 (user directive) — NON-DESTRUCTIVE REPROCESS: when the
        # month was already processed, the admin's previously ENTERED
        # days are KEPT (never reset to zero). The money fields are
        # recalculated from those preserved days with the current
        # parameters. Imported-sheet runs keep the sheet as the source.
        _prev = (prev_rows or {}).get(emp["user_id"]) \
            if not _frz_imp else None
        if _prev is not None:
            # Iter 340 (user request) — kept days also clamp to month days.
            _ppd = min(float(_prev.get("present_days") or 0.0),
                       float(month_days))
            stats = dict(stats)
            stats["present_days"] = round(_ppd * 2) / 2.0
            stats["effective_present"] = _ppd
            stats["half_days"] = 0
            stats["ot_hours"] = float(_prev.get("ot_hours") or 0.0)
            if _prev.get("duty_hours") is not None:
                stats["duty_hours"] = float(_prev.get("duty_hours") or 0.0)
        _ff = firm_stat_flags.get(emp.get("company_id")) or {"pf": False, "esic": False}
        # ------------------------------------------------------------------
        # Iter 617 (user spec) — DOJ/DOL ELIGIBILITY WINDOW on CALENDAR days.
        # The salary Month Days (override, e.g. 26) stays PURELY the salary
        # denominator; the DOJ/DOL position is judged on the real calendar:
        #   joined mid-month  → allowed = calendar_days − DOJ_day + 1
        #   exited mid-month  → allowed = DOL_day
        #   both in the month → allowed = DOL_day − DOJ_day + 1
        # Final Present Days = MIN(attendance days, allowed, month_days) —
        # attendance stays the source (the window never auto-pays days) and
        # the clamp runs BEFORE the money math so PF/ESIC calculate on the
        # final earned wage.
        # ------------------------------------------------------------------
        _dojdol_allowed = int(default_days)
        _dojdol_reason = ""
        try:
            _doj_s = str(emp.get("doj") or "")
            _dol_s = str(emp.get("exit_date") or "")
            _ms617 = f"{year:04d}-{mon:02d}-01"
            _me617 = f"{year:04d}-{mon:02d}-{default_days:02d}"
            _doj_in = bool(_doj_s and _ms617 <= _doj_s <= _me617)
            _dol_in = bool(_dol_s and _ms617 <= _dol_s <= _me617)
            if _doj_in and _dol_in:
                _dojdol_allowed = (int(_dol_s.split("-")[2])
                                   - int(_doj_s.split("-")[2]) + 1)
                _dojdol_reason = "DOJ and DOL both in this month"
            elif _doj_in:
                _dojdol_allowed = default_days - int(_doj_s.split("-")[2]) + 1
                _dojdol_reason = "joined mid-month (DOJ)"
            elif _dol_in:
                _dojdol_allowed = int(_dol_s.split("-")[2])
                _dojdol_reason = "exited mid-month (DOL)"
            _dojdol_allowed = max(0, _dojdol_allowed)
        except (ValueError, IndexError):
            _dojdol_allowed = int(default_days)
        _att_days_in = float(stats.get("present_days") or 0)
        _final_cap617 = min(float(month_days), float(_dojdol_allowed))
        if _att_days_in > _final_cap617:
            stats = dict(stats)
            stats["present_days"] = _final_cap617
            stats["effective_present"] = min(
                float(stats.get("effective_present") or _att_days_in),
                _final_cap617)
            stats["half_days"] = 0
        # Iter 178 — state-wise PT from the firm's compliance policy.
        _fcp = (company_doc.get("compliance_policy") or {}) if company_doc else {}
        # Iter 630 (user spec — Allowance Enable/Disable contract) — derive
        # the firm's EDITABLE-allowance mask BEFORE the compute so disabled
        # heads calculate as 0 INSIDE the engine (Gross Paid / ESIC / PT
        # bases see the masked structure; on freeze runs the masked amount
        # flows into the Difference → OT / Other Allowances only).
        firm_comp_policy = (company_doc.get("compliance_policy") or {}) if company_doc else {}
        enabled = firm_comp_policy.get("enabled_allowances")
        _pol_set = ({str(x).lower() for x in enabled}
                    if enabled and isinstance(enabled, list) else None)
        _fm_masks = firm_stat_flags.get(emp.get("company_id")) or {}
        _fm_set = _fm_masks.get("allow_mask")
        if _pol_set is not None and _fm_set is not None:
            enabled_set = _pol_set & set(_fm_set)
        elif _pol_set is not None:
            enabled_set = _pol_set
        elif _fm_set is not None:
            enabled_set = set(_fm_set)
        else:
            enabled_set = None
        if enabled_set is not None:
            enabled_set.add("basic")  # Basic (fixed head) is never masked
        # Iter 626 (user spec §12) — mid-month DAILY RATE REVISION.
        emp, _rate_rev_audit = _apply_daily_rate_revisions(
            emp, payload.month, int(month_days), grid_by_user_c.get(emp["user_id"]))
        row = compute_compliance_row(
            emp, merged_pol, int(month_days), stats,
            company_structure_pct=payload.structure_pct,
            statutory_cfg=effective_statutory,
            firm_pf_enabled=_ff["pf"],
            firm_esic_enabled=_ff["esic"],
            firm_pt={"state": _fcp.get("pt_state"), "slabs": _fcp.get("pt_slabs")},
            enabled_allowances=enabled_set,
            custom_allowance_labels=_fm_masks.get("custom_allow_labels"),
        )
        # Iter 406 — remember the stats the FINAL row was computed with so
        # the Freeze block can re-compute statutory on the allocated gross.
        _stats_final = stats
        # Iter 626 — rate revision audit trail on the row (View Calculation).
        if _rate_rev_audit:
            row["rate_revision_audit"] = _rate_rev_audit
        # Iter 337 (user request) — DAYS CALCULATION METHOD (Firm Master →
        # Payroll Settings). For imported (Freeze) runs the Compliance Days
        # can be DERIVED from the imported gross:
        #   Per-Day Gross = Master Monthly Gross ÷ Month Days
        #   Compliance Days = Imported Gross ÷ Per-Day Gross (rounded to
        #   0.50 / 0.25 per firm policy) — statutory is then recalculated
        #   on those days; the remaining difference lands in OT / Other
        #   Allowance via the Freeze block below.
        if _frz_imp and _am is not None:
            row["attendance_days"] = round(
                min(float(_am.get("present_days") or 0), float(month_days)), 2)
            _dcm = firm_stat_flags.get(emp.get("company_id")) or {}
            # Iter 665 (user directive) — Attendance + Gross Validation is
            # the DEFAULT method for every firm (changeable in Firm Master).
            _method = str(_dcm.get("days_calc_method")
                          or "attendance_gross_validation")
            _imp_g0 = round(float(_am.get("gross_earning") or 0), 2)
            # Iter 339 (user request) — ONE-TIME freeze import: when the
            # imported sheet carries a GROSS but NO attendance days, the
            # Compliance Days are auto-derived from that gross (Attendance
            # + Gross Validation behaviour) even when the firm hasn't
            # picked a Days Calculation Method yet — a single import fills
            # the days, recalculates salary/statutory and matches Freeze
            # vs Gross without any reprocess.
            # Iter 339b (user request — "no negative salary figures"):
            # ALSO derive the days when the sheet-days salary OVERSHOOTS
            # the imported gross (would print a negative Difference) — the
            # freeze gross is authoritative, so days shrink to match it.
            if (_method == "attendance" and _imp_g0 > 0
                    and (row["attendance_days"] <= 0
                         or float(row.get("gross_paid") or 0) > _imp_g0 + 0.5)):
                _method = "attendance_gross_validation"
            _new_days = None
            if _method == "fixed":
                if row["attendance_days"] > 0 or _imp_g0 > 0:
                    _new_days = float(_dcm.get("days_calc_fixed") or 26)
            elif _method in ("gross_based", "freeze_based",
                             "attendance_gross_validation",
                             "freeze_actual_gross") and _imp_g0 > 0:
                # Per-Day Gross — from the first pass (exact for both
                # daily-rated and monthly-rated employees); falls back to
                # Master Monthly Gross ÷ Month Days.
                _g0 = float(row.get("gross_paid") or 0)
                _pd0 = float(row.get("present_days") or 0)
                _mg0 = float(row.get("monthly_gross") or 0)
                _per_day = (_g0 / _pd0) if (_g0 > 0 and _pd0 > 0) else (
                    (_mg0 / float(month_days or 1)) if _mg0 > 0 else 0.0)
                if _per_day <= 0:
                    # Iter 339 — DAILY-RATED employees with a gross-only
                    # sheet (0 days): both fallbacks above are 0. Probe a
                    # FULL-MONTH compute to learn the true per-day gross
                    # (rate + allowances) so days can still be derived.
                    _stF = dict(stats)
                    _stF["present_days"] = float(month_days)
                    _stF["effective_present"] = float(month_days)
                    _stF["half_days"] = 0
                    _stF["duty_hours"] = round(
                        float(month_days)
                        * float(merged_pol.get("full_day_hours") or 8.0), 2)
                    _rowF = compute_compliance_row(
                        emp, merged_pol, int(month_days), _stF,
                        company_structure_pct=payload.structure_pct,
                        statutory_cfg=effective_statutory,
                        firm_pf_enabled=_ff["pf"],
                        firm_esic_enabled=_ff["esic"],
                        firm_pt={"state": _fcp.get("pt_state"),
                                 "slabs": _fcp.get("pt_slabs")},
                        enabled_allowances=enabled_set,
                        custom_allowance_labels=_fm_masks.get("custom_allow_labels"),
                    )
                    _gF = float(_rowF.get("gross_paid") or 0)
                    if _gF > 0:
                        _per_day = _gF / float(month_days or 1)
                if _per_day > 0:
                    _rawd = _imp_g0 / _per_day
                    if _method == "freeze_actual_gross":
                        # Iter 337b (user request) — Freeze Salary taken
                        # AS-IS as the Actual Gross: exact fractional days
                        # (no half/full rounding) so the calculated gross
                        # equals the imported gross to the rupee; statutory
                        # is computed on that gross. Iter 340 — FLOOR at 2
                        # decimals so the calc can never overshoot the
                        # imported gross (no negative Difference).
                        _new_days = math.floor(_rawd * 100 + 1e-9) / 100
                    else:
                        try:
                            _step = float(_dcm.get("days_calc_rounding") or 0.5)
                        except (TypeError, ValueError):
                            _step = 0.5
                        # User directive — days land on HALF or FULL days only.
                        _step = 1.0 if _step >= 1 else 0.5
                        # Iter 339b (user request — "no negative salary
                        # figures"): days always round DOWN to the step so
                        # the calculated gross NEVER exceeds the imported
                        # gross. The (positive) remainder goes to OT /
                        # Other Allowance; a round-UP produced overshoots
                        # like −117 in the Difference column.
                        _new_days = math.floor((_rawd + 1e-9) / _step) * _step
                        if _method == "attendance_gross_validation":
                            # Iter 665 (user directive) — sheet DAYS +
                            # GROSS are both authoritative: days may only
                            # AUTO-REDUCE when too high for the gross,
                            # NEVER increase. Any extra imported gross
                            # flows to OT / Incentive / Other Allowance
                            # via the freeze-difference rules.
                            _sheet_d665 = float(row.get("attendance_days") or 0)
                            if _sheet_d665 > 0 and _new_days > _sheet_d665:
                                _new_days = _sheet_d665
            if _new_days is not None:
                _new_days = max(0.0, min(round(_new_days, 2), float(month_days)))
                if abs(_new_days - float(row.get("present_days") or 0)) > 1e-9:
                    _st2 = dict(stats)
                    _st2["present_days"] = _new_days
                    _st2["effective_present"] = _new_days
                    _st2["half_days"] = 0
                    _st2["duty_hours"] = round(
                        _new_days * float(merged_pol.get("full_day_hours") or 8.0), 2)
                    row = compute_compliance_row(
                        emp, merged_pol, int(month_days), _st2,
                        company_structure_pct=payload.structure_pct,
                        statutory_cfg=effective_statutory,
                        firm_pf_enabled=_ff["pf"],
                        firm_esic_enabled=_ff["esic"],
                        firm_pt={"state": _fcp.get("pt_state"),
                                 "slabs": _fcp.get("pt_slabs")},
                        enabled_allowances=enabled_set,
                        custom_allowance_labels=_fm_masks.get("custom_allow_labels"),
                    )
                    _stats_final = _st2
                    row["attendance_days"] = round(
                        min(float(_am.get("present_days") or 0),
                            float(month_days)), 2)
                row["compliance_days"] = _new_days
            else:
                row["compliance_days"] = round(float(row.get("present_days") or 0), 2)
        # Iter 443 (user request) — Master-linked deductions: heads switched
        # OFF in the Firm Master are neither shown nor applied.
        _ded_set0 = _ff.get("ded_mask") if isinstance(_ff, dict) else None
        _oth_on = _ded_set0 is None or "other" in _ded_set0
        _tds_on = _ded_set0 is None or "tds" in _ded_set0
        _adv_on = _ded_set0 is None or "advance" in _ded_set0
        # Iter 100 — Attendance Master "Other Deduction" (Advance/TDS etc.)
        # Iter 616 (user bug) — an imported ADVANCE deduction now lands in
        # the ADVANCE column (advance_recovery), not in Other Deduction.
        # Iter 755 (user bug — "Advance and Other Deductions are merged"):
        # the sheet's ADVANCE column and OTHER DEDUCTION column are now
        # routed SEPARATELY — Advance → ADVANCE column, Other Less →
        # OTHER DEDUCTION column. They are never summed together any more.
        _ded_amt755 = round(float((_am or {}).get("deduction_amount") or 0), 2)
        _oth_amt755 = round(float((_am or {}).get("other_less") or 0), 2)
        if _am and (_ded_amt755 > 0 or _oth_amt755 > 0):
            _head_txt = str(_am.get("deduction_head") or "").strip().upper()
            # deduction_amount comes from Advance-ish sheet columns
            # (ADVANCE / ADV / DEDUCTION AMOUNT); a non-ADV head (e.g.
            # UNIFORM) routes it to Other Deduction under that head.
            _is_adv = "ADV" in _head_txt or not _head_txt
            _adv_part = _ded_amt755 if _is_adv else 0.0
            _oth_part = round(_oth_amt755 + (0.0 if _is_adv else _ded_amt755), 2)
            if _adv_part > 0 and not _adv_on:
                # ADVANCE head OFF in Firm Master → falls back to Other.
                _oth_part = round(_oth_part + _adv_part, 2)
                _adv_part = 0.0
            if _adv_part > 0:
                row["advance_recovery"] = round(
                    float(row.get("advance_recovery") or 0) + _adv_part, 2)
                row["total_deduction"] = round(
                    float(row.get("total_deduction") or 0) + _adv_part, 2)
                row["net"] = round(float(row.get("net") or 0) - _adv_part, 2)
                # Ledger recovery must not double-deduct the sheet figure.
                row["manual_fields"] = sorted(
                    set(row.get("manual_fields") or []) | {"advance_recovery"})
            if _oth_part > 0 and _oth_on:
                row["other_deduction_head"] = (
                    (_am.get("deduction_head") if not _is_adv else None)
                    or "Other Deduction")
                row["other_deduction"] = _oth_part
                row["total_deduction"] = round(
                    float(row.get("total_deduction") or 0) + _oth_part, 2)
                row["net"] = round(float(row.get("net") or 0) - _oth_part, 2)
        # Iter 616 — the Actual run's "Other Ded.*" (freeze-as-actual-gross
        # firms) lands in the Other Deduction column, ON TOP of any sheet
        # deduction routed above.
        _act_od = round(float((_am or {}).get("actual_other_ded") or 0), 2)
        if _am and _act_od > 0 and _oth_on:
            row["other_deduction_head"] = row.get("other_deduction_head") or "Other Ded."
            row["other_deduction"] = round(
                float(row.get("other_deduction") or 0) + _act_od, 2)
            row["total_deduction"] = round(
                float(row.get("total_deduction") or 0) + _act_od, 2)
            row["net"] = round(float(row.get("net") or 0) - _act_od, 2)
        # Iter 297 — reprocess also keeps the manually ENTERED "Other
        # Deduction" from the previous run (default is 0 → any value was
        # typed by the admin).
        if _prev is not None and not _am and _oth_on and \
                float(_prev.get("other_deduction") or 0) > 0:
            _pod = round(float(_prev.get("other_deduction") or 0), 2)
            row["other_deduction_head"] = (
                _prev.get("other_deduction_head") or "Other")
            row["other_deduction"] = _pod
            row["total_deduction"] = round(
                float(row.get("total_deduction") or 0) + _pod, 2)
            row["net"] = round(float(row.get("net") or 0) - _pod, 2)
        row["company_id"] = emp.get("company_id")
        row["company_name"] = company_doc.get("name")
        # Iter 85 — Apply the firm's Compliance-Allowances toggles.
        # Iter 171 — ALSO honour the Firm Master Allowances catalog: when
        # the firm configured allowances there, the two masks intersect.
        # Iter 630 — the mask (enabled_set, derived BEFORE the compute) is
        # now applied INSIDE compute_compliance_row, so heads/gross/ESIC
        # already exclude disabled heads. This block stays as an idempotent
        # safety net for rows merged from auxiliary computes and records
        # the mask on the row.
        if enabled_set is not None:
            for head in ("hra", "conveyance", "medical", "special", "others"):
                if head not in enabled_set:
                    row[head] = 0.0
            # Recompute gross-derived fields to reflect the trimmed heads
            heads_sum = float(
                (row.get("basic") or 0)
                + (row.get("hra") or 0)
                + (row.get("conveyance") or 0)
                + (row.get("medical") or 0)
                + (row.get("special") or 0)
                + (row.get("others") or 0)
            )
            row["monthly_gross"] = round(heads_sum, 2)
            row["enabled_allowances"] = sorted(enabled_set)

        # Iter 171 — Firm Master DEDUCTIONS catalog drives the deduction
        # columns. PF/ESI stay governed by statutory applicability; PT and
        # TDS are zeroed (and removed from Total Ded. / added back to Net)
        # when the firm switched them OFF.
        _ded_set = _fm_masks.get("ded_mask")
        if _ded_set is not None:
            _removed = 0.0
            for _dk in ("pt", "tds"):
                if _dk not in _ded_set and float(row.get(_dk) or 0):
                    _removed += float(row[_dk])
                    row[_dk] = 0.0
            if _removed:
                row["total_deduction"] = round(
                    float(row.get("total_deduction") or 0) - _removed, 2)
                row["net"] = round(float(row.get("net") or 0) + _removed, 2)
            row["enabled_deductions"] = sorted(_ded_set)

        # Iter 644 (user request) — dynamic ALLOWANCE head labels carried
        # on the row so the grid / exports render one column per enabled
        # custom allowance head (INCENTIVE / BONUS / …).
        _customA = _fm_masks.get("custom_allow_labels")
        if _customA is not None:
            row["allowance_head_labels"] = _customA

        # Iter 420 (user request) — DEDUCTIONS follow the Firm Master
        # catalog DYNAMICALLY: each enabled custom head is its own column;
        # amounts on heads the firm switched OFF are removed from Total
        # Ded. and returned to Net.
        _custom = _fm_masks.get("custom_ded_labels")
        if _custom is not None:
            _low = {str(c).strip().lower() for c in _custom}
            _keep: dict = {}
            _rm = 0.0
            for _h, _amt in (row.get("deduction_heads") or {}).items():
                if str(_h).strip().lower() in _low:
                    _keep[_h] = _amt
                else:
                    _rm += float(_amt or 0)
            if _rm:
                row["master_deduction"] = round(
                    float(row.get("master_deduction") or 0) - _rm, 2)
                row["total_deduction"] = round(
                    float(row.get("total_deduction") or 0) - _rm, 2)
                row["net"] = round(float(row.get("net") or 0) + _rm, 2)
            row["deduction_heads"] = _keep
            row["deduction_head_labels"] = _custom

        # Iter 469 (user request — "deduction heads are dynamic") — the
        # imported sheet may carry a COLUMN per enabled Firm-Master
        # deduction head (UNIFORM / CLUB / CANTEEN / …). The sheet value is
        # authoritative for that head and lands in the row's dynamic
        # deduction column.
        if _am and isinstance(_am.get("custom_deductions"), dict) \
                and _am["custom_deductions"]:
            _dh469 = dict(row.get("deduction_heads") or {})
            _low469 = ({str(c).strip().lower() for c in _custom}
                       if _custom is not None else None)
            _add469 = 0.0
            for _h469, _v469 in _am["custom_deductions"].items():
                _v469 = round(float(_v469 or 0), 2)
                if _v469 <= 0:
                    continue
                if _low469 is not None and \
                        str(_h469).strip().lower() not in _low469:
                    continue
                _add469 += _v469 - float(_dh469.get(_h469) or 0)
                _dh469[_h469] = _v469
            if _add469:
                row["master_deduction"] = round(
                    float(row.get("master_deduction") or 0) + _add469, 2)
                row["total_deduction"] = round(
                    float(row.get("total_deduction") or 0) + _add469, 2)
                row["net"] = round(float(row.get("net") or 0) - _add469, 2)
            row["deduction_heads"] = _dh469

        # Iter 328 — imported sheet TDS is authoritative: applied AFTER the
        # firm deduction mask so an explicit TDS on the client sheet always
        # lands on the run.
        if _am and float(_am.get("tds") or 0) > 0 and _tds_on:
            _tds_new = round(float(_am.get("tds") or 0), 2)
            _tds_delta = round(_tds_new - float(row.get("tds") or 0), 2)
            row["tds"] = _tds_new
            row["total_deduction"] = round(float(row.get("total_deduction") or 0) + _tds_delta, 2)
            row["net"] = round(float(row.get("net") or 0) - _tds_delta, 2)

        # Iter 85/617 — stamp the eligibility ceiling + a per-row AUDIT
        # TRAIL. Days were already clamped BEFORE the money math; this is a
        # safety re-cap for paths that overwrite days later (imported-sheet
        # derivations) — those keep their frozen gross by design, but the
        # days column never exceeds the DOJ/DOL window.
        try:
            cap = round(min(float(month_days), float(_dojdol_allowed)), 2)
            if float(row.get("present_days") or 0) > cap:
                row["present_days"] = cap
                if not _dojdol_reason:
                    _dojdol_reason = "salary month-days limit"
            row["max_p_days"] = cap
            row["pay_days_audit"] = {
                "doj": str(emp.get("doj") or "") or None,
                "dol": str(emp.get("exit_date") or "") or None,
                "salary_month_days": float(month_days),
                "calendar_days": int(default_days),
                "attendance_days": round(_att_days_in, 2),
                "dojdol_allowed_days": _dojdol_allowed,
                "final_days": float(row.get("present_days") or 0),
                "cap_reason": (_dojdol_reason
                               if (_att_days_in > cap
                                   or _dojdol_allowed < int(default_days))
                               else ""),
            }
        except (ValueError, IndexError):
            row.setdefault("max_p_days", int(month_days))
        # Iter 374 (user bug) — a REPROCESS must NEVER remove the admin's
        # MANUALLY FILLED amounts (Others / OT Amt / TDS / ESIC Leave).
        # The grid stamps every manual edit on ``manual_fields``; those
        # figures are restored AS-IS and the money math rebuilt around
        # them. Heuristics cover rows saved before the stamp existed:
        # ESIC Leave is manual-entry only; an OT AMOUNT without OT hours
        # and a TDS with no imported sheet were typed by the admin.
        if _prev is not None and not payload.use_imported_sheet:
            _mf = set(_prev.get("manual_fields") or [])
            _fresh_g472 = round(float(row.get("gross_paid") or 0), 2)
            if float(_prev.get("esic_leave_days") or 0) > 0:
                _mf.add("esic_leave_days")
            if float(_prev.get("ot_pay") or 0) > 0 and \
                    float(_prev.get("ot_hours") or 0) <= 0:
                _mf.add("ot_pay")
            if float(_prev.get("tds") or 0) > 0 and not _am:
                _mf.add("tds")
            if _mf:
                row["manual_fields"] = sorted(_mf)
                row["manual_override"] = True
            if "esic_leave_days" in _mf:
                row["esic_leave_days"] = float(_prev.get("esic_leave_days") or 0)
            if "others" in _mf:
                _new_oth = round(float(_prev.get("others") or 0), 2)
                _delta = round(_new_oth - float(row.get("others") or 0), 2)
                if _delta:
                    row["others"] = _new_oth
                    row["monthly_gross"] = round(
                        float(row.get("monthly_gross") or 0) + _delta, 2)
                    row["gross_paid"] = round(
                        float(row.get("gross_paid") or 0) + _delta, 2)
                    row["net"] = round(float(row.get("net") or 0) + _delta, 2)
            # Iter 727 (user request) — manual "OTH. ALLOW." (special)
            # edits survive a reprocess exactly like Others.
            if "special" in _mf:
                _new_spl = round(float(_prev.get("special") or 0), 2)
                _delta = round(_new_spl - float(row.get("special") or 0), 2)
                if _delta:
                    row["special"] = _new_spl
                    row["monthly_gross"] = round(
                        float(row.get("monthly_gross") or 0) + _delta, 2)
                    row["gross_paid"] = round(
                        float(row.get("gross_paid") or 0) + _delta, 2)
                    row["net"] = round(float(row.get("net") or 0) + _delta, 2)
            # Iter 647 (user request) — manually edited custom allowance
            # head amounts (e.g. INCENTIVE) survive a reprocess.
            if "allowance_heads" in _mf and isinstance(
                    _prev.get("allowance_heads"), dict):
                row["allowance_heads"] = _prev["allowance_heads"]
            if "ot_pay" in _mf:
                _new_ot = round(float(_prev.get("ot_pay") or 0), 2)
                _delta = round(_new_ot - float(row.get("ot_pay") or 0), 2)
                if _delta:
                    row["ot_pay"] = _new_ot
                    row["gross_paid"] = round(
                        float(row.get("gross_paid") or 0) + _delta, 2)
                    row["net"] = round(float(row.get("net") or 0) + _delta, 2)
            if "tds" in _mf and _tds_on and not (_am and float(_am.get("tds") or 0) > 0):
                _new_tds = round(float(_prev.get("tds") or 0), 2)
                _delta = round(_new_tds - float(row.get("tds") or 0), 2)
                if _delta:
                    row["tds"] = _new_tds
                    row["total_deduction"] = round(
                        float(row.get("total_deduction") or 0) + _delta, 2)
                    row["net"] = round(float(row.get("net") or 0) - _delta, 2)
            # Iter 422 (user request) — manually edited ADVANCE deduction
            # survives a reprocess. apply_advance_recovery() skips rows
            # whose manual_fields carry "advance_recovery" so the ledger
            # never overwrites the admin's typed amount.
            if "advance_recovery" in _mf and _adv_on:
                _new_adv = round(float(_prev.get("advance_recovery") or 0), 2)
                _delta = round(_new_adv - float(row.get("advance_recovery") or 0), 2)
                if _delta:
                    row["advance_recovery"] = _new_adv
                    row["total_deduction"] = round(
                        float(row.get("total_deduction") or 0) + _delta, 2)
                    row["net"] = round(float(row.get("net") or 0) - _delta, 2)
            # Iter 472 (user request) — manual OT / Others changed the kept
            # Gross Earning: PF / ESIC / PT REFRESH on that kept gross with
            # the CURRENT master data (days and the kept figures stay).
            # Iter 651 (user bug — "reprocess with existing data sometimes
            # gives wrong ESIC until attendance is touched") — the refresh
            # now runs for EVERY kept-gross difference, not only when
            # others/ot carry the manual stamp: whatever moved the kept
            # gross, the statutory figures must follow it.
            _kept_g472 = round(float(row.get("gross_paid") or 0), 2)
            if abs(_kept_g472 - _fresh_g472) > 0.004:
                _st5 = dict(_stats_final)
                _st5["other_allowance_extra"] = round(
                    _kept_g472 - _fresh_g472, 2)
                _row4 = compute_compliance_row(
                    emp, merged_pol, int(month_days), _st5,
                    company_structure_pct=payload.structure_pct,
                    statutory_cfg=effective_statutory,
                    firm_pf_enabled=_ff["pf"],
                    firm_esic_enabled=_ff["esic"],
                    firm_pt={"state": _fcp.get("pt_state"),
                             "slabs": _fcp.get("pt_slabs")},
                    enabled_allowances=enabled_set,
                    custom_allowance_labels=_fm_masks.get("custom_allow_labels"),
                )
                for _k in ("stat_wage_base", "pf_wages", "pf_employee",
                           "pf_employer_epf", "pf_employer_eps",
                           "pf_employer_total", "vpf_amount",
                           "esic_wage_base", "esic_employee",
                           "esic_employer", "calc_note"):
                    if _k in _row4:
                        row[_k] = _row4[_k]
                _ded_set472 = _fm_masks.get("ded_mask")
                if not (_ded_set472 is not None and "pt" not in _ded_set472):
                    row["pt"] = _row4.get("pt", row.get("pt"))
                row["total_deduction"] = round(
                    float(row.get("pf_employee") or 0)
                    + float(row.get("esic_employee") or 0)
                    + float(row.get("pt") or 0)
                    + float(row.get("tds") or 0)
                    + float(row.get("other_deduction") or 0)
                    + float(row.get("master_deduction") or 0)
                    + float(row.get("advance_recovery") or 0), 2)
                row["net"] = round(_kept_g472 - row["total_deduction"], 2)
        # Iter 310 — FREEZE SALARY (user directive): when the run is driven
        # by the IMPORTED sheet, the sheet's Gross Earning is authoritative
        # and gets FROZEN on the run. If Imported Gross > the gross
        # calculated from the Employee Master, the DIFFERENCE is routed to
        # OVERTIME when the Firm Master allows OT
        # (salary_process.ot_allowed) — otherwise to OTHER ALLOWANCES.
        # Runs AFTER the allowance/deduction masks + DOJ cap so nothing
        # later can trim the allocated difference.
        if _frz_imp and _am is not None:
            _imp_g = round(float(_am.get("gross_earning") or 0), 2)
            # Iter 343b (user request) — after the import the admin may EDIT
            # the OT Amount / Other Allowances. A REPROCESS keeps those
            # MANUAL figures; the Freeze (imported) gross stays on the row
            # purely as DISPLAY/comparison data.
            _prev_imp = (prev_rows or {}).get(emp["user_id"])
            if _prev_imp is not None and (
                    _prev_imp.get("manual_override") or _frz_days_manual):
                # Restore the admin's saved figures AS-IS (they were kept
                # consistent by the grid at edit time).
                _fresh_g = round(float(row.get("gross_paid") or 0), 2)
                row["ot_pay"] = round(float(_prev_imp.get("ot_pay") or 0), 2)
                row["others"] = round(float(_prev_imp.get("others") or 0), 2)
                _keep_g = round(float(_prev_imp.get("gross_paid") or 0), 2)
                row["gross_paid"] = _keep_g
                row["manual_override"] = True
                # Iter 422 (user request) — manual ADVANCE edits survive a
                # reprocess on imported (Freeze) runs too. manual_fields is
                # carried so apply_advance_recovery() skips this row.
                _mf_imp = set(_prev_imp.get("manual_fields") or [])
                # Iter 723 — day-edited rows (detected above) carry the
                # stamp forward so every future reprocess keeps them too.
                if _frz_days_manual:
                    _mf_imp.add("present_days")
                    row["manual_override"] = True
                if _mf_imp:
                    row["manual_fields"] = sorted(_mf_imp)
                # Iter 723 (user bug — "Reprocess changes the data AGAIN"):
                # manual TDS / Other Deduction / ESIC-leave typed on a
                # Freeze run were LOST on reprocess (only OT/Others/gross
                # were restored). They now survive exactly like on normal
                # runs (Iter 374 rule). The kept monthly gross is restored
                # too so Gross − OT stays consistent on the sheet.
                if "tds" in _mf_imp:
                    row["tds"] = round(float(_prev_imp.get("tds") or 0), 2)
                # Iter 727 — manual OTH. ALLOW. (special) kept on Freeze
                # runs too (gross already kept via _keep_g above).
                if "special" in _mf_imp:
                    row["special"] = round(
                        float(_prev_imp.get("special") or 0), 2)
                if "other_deduction" in _mf_imp:
                    row["other_deduction"] = round(
                        float(_prev_imp.get("other_deduction") or 0), 2)
                    row["other_deduction_head"] = (
                        _prev_imp.get("other_deduction_head")
                        or row.get("other_deduction_head") or "Other")
                if "esic_leave_days" in _mf_imp:
                    row["esic_leave_days"] = float(
                        _prev_imp.get("esic_leave_days") or 0)
                if "ot_pay" in _mf_imp:
                    # keep the saved OT hours consistent with the kept
                    # manual OT amount (hours never re-pulled over it).
                    row["ot_hours"] = float(_prev_imp.get("ot_hours") or 0.0)
                if float(_prev_imp.get("monthly_gross") or 0) > 0:
                    row["monthly_gross"] = round(
                        float(_prev_imp.get("monthly_gross") or 0), 2)
                # Iter 647 (user request) — manually edited custom allowance
                # head amounts survive a reprocess on Freeze runs too.
                if "allowance_heads" in _mf_imp and isinstance(
                        _prev_imp.get("allowance_heads"), dict):
                    row["allowance_heads"] = _prev_imp["allowance_heads"]
                if "advance_recovery" in _mf_imp:
                    _adv_prev = round(
                        float(_prev_imp.get("advance_recovery") or 0), 2)
                    row["advance_recovery"] = _adv_prev
                # Iter 472 (user request — "Days & Freeze stay the SAME but
                # PF/ESIC must REFRESH per the latest master changes"): the
                # kept gross is authoritative, but the statutory figures are
                # RE-COMPUTED on that kept Gross Earning with the CURRENT
                # Employee Master / Compliance Settings — so a master
                # revision (rate basis, PF Basic, ESIC flags, %s) flows into
                # PF / ESIC / PT on a reprocess without touching the days or
                # the frozen gross / manual OT / Others.
                _st4 = dict(_stats_final)
                _gap4 = round(_keep_g - _fresh_g, 2)
                if abs(_gap4) > 0.004:
                    _st4["other_allowance_extra"] = _gap4
                _row3 = compute_compliance_row(
                    emp, merged_pol, int(month_days), _st4,
                    company_structure_pct=payload.structure_pct,
                    statutory_cfg=effective_statutory,
                    firm_pf_enabled=_ff["pf"],
                    firm_esic_enabled=_ff["esic"],
                    firm_pt={"state": _fcp.get("pt_state"),
                             "slabs": _fcp.get("pt_slabs")},
                    enabled_allowances=enabled_set,
                    custom_allowance_labels=_fm_masks.get("custom_allow_labels"),
                )
                for _k in ("stat_wage_base", "pf_wages", "pf_employee",
                           "pf_employer_epf", "pf_employer_eps",
                           "pf_employer_total", "vpf_amount",
                           "esic_wage_base", "esic_employee",
                           "esic_employer", "calc_note"):
                    if _k in _row3:
                        row[_k] = _row3[_k]
                # PT follows the refreshed gross unless the firm's deduction
                # mask switched it OFF earlier.
                if not (_ded_set is not None and "pt" not in _ded_set):
                    row["pt"] = _row3.get("pt", row.get("pt"))
                row["total_deduction"] = round(
                    float(row.get("pf_employee") or 0)
                    + float(row.get("esic_employee") or 0)
                    + float(row.get("pt") or 0)
                    + float(row.get("tds") or 0)
                    + float(row.get("other_deduction") or 0)
                    + float(row.get("master_deduction") or 0)
                    + float(row.get("advance_recovery") or 0), 2)
                row["net"] = round(_keep_g - row["total_deduction"], 2)
                if _imp_g > 0:
                    row["imported_gross"] = _imp_g
                    row["calculated_gross"] = _keep_g
                    row["difference"] = round(_imp_g - _keep_g, 2)
                    row["freeze_status"] = (
                        "matched" if abs(row["difference"]) < 1 else "diff")
                    row["difference_allocation_head"] = "Manual"
            elif _imp_g > 0:
                _calc_g = round(float(row.get("gross_paid") or 0), 2)
                _diff_g = round(_imp_g - _calc_g, 2)
                row["imported_gross"] = _imp_g
                row["calculated_gross"] = _calc_g
                row["difference"] = _diff_g
                row["difference_allocation_head"] = ""
                # Iter 337 — validation status for the grid (✓ Matched).
                row["freeze_status"] = "matched" if abs(_diff_g) < 1 else "diff"
                if abs(_diff_g) > 0.004:
                    # Iter 406 (user rule — "Gross Earning includes OT") —
                    # the difference is allocated INSIDE the compute
                    # (ot_pay_extra / other_allowance_extra) and the row is
                    # RE-COMPUTED, so PF / ESIC / PT wage bases see the FULL
                    # Gross Earning INCLUDING OT. Previously the diff was
                    # bolted on AFTER the statutory calc, so PF/ESIC never
                    # saw the freeze OT.
                    # Iter 646 (user bug — OT showing for people who never
                    # have OT) — the freeze diff goes to OT only when the
                    # Firm allows OT AND the "OVER TIME" allowance head is
                    # enabled in the catalog; otherwise Other Allowances.
                    _frz_ot = ((firm_stat_flags.get(emp.get("company_id"))
                                or {}).get("ot_allowed")
                               and (enabled_set is None or "ot" in enabled_set))
                    # Iter 657 (user request) — INCENTIVE as an adjust head:
                    # when the firm's Allowance catalog has an INCENTIVE
                    # head enabled, the freeze difference remaining AFTER
                    # the OT rule lands under INCENTIVE (its own editable
                    # column). Priority: OT first, then Incentive, then
                    # Other Allowances.
                    _inc_labels657 = [
                        _l for _l in ((firm_stat_flags.get(emp.get("company_id"))
                                       or {}).get("custom_allow_labels") or [])
                        if str(_l).strip().upper() == "INCENTIVE"]
                    _frz_inc = bool(_inc_labels657)
                    _inc_extra657 = 0.0
                    _st3 = dict(_stats_final)
                    # Iter 646 (user bug — "FOOD ALLOWANCE amount landed in
                    # OT") — per-head allowance amounts typed on the imported
                    # sheet allocate to OTHER ALLOWANCES (shown under their
                    # own dynamic head column), NEVER to OT; only the
                    # remaining difference follows the OT rule.
                    _ca646 = {k: float(v or 0)
                              for k, v in ((_am.get("custom_allowances")
                                            if _am else None) or {}).items()
                              if float(v or 0) > 0}
                    _ca_tot = round(sum(_ca646.values()), 2)
                    _alloc_allow = 0.0
                    if _diff_g > 0:
                        _alloc_allow = round(min(_ca_tot, _diff_g), 2)
                        _rem_diff = round(_diff_g - _alloc_allow, 2)
                        if _alloc_allow > 0:
                            _st3["other_allowance_extra"] = _alloc_allow
                            row["difference_allocation_head"] = "Allowance Heads"
                        if _rem_diff > 0:
                            if _frz_ot:
                                _st3["ot_pay_extra"] = _rem_diff
                                row["difference_allocation_head"] = (
                                    "Allowance Heads + Overtime"
                                    if _alloc_allow else "Overtime")
                            elif _frz_inc:
                                # Iter 657 — remainder to the INCENTIVE
                                # head (inside the compute via Others so
                                # PF/ESIC see it; shown & editable under
                                # the INCENTIVE column below).
                                _inc_extra657 = _rem_diff
                                _st3["other_allowance_extra"] = round(
                                    float(_st3.get("other_allowance_extra")
                                          or 0) + _rem_diff, 2)
                                row["difference_allocation_head"] = (
                                    "Allowance Heads + Incentive"
                                    if _alloc_allow else "Incentive")
                            else:
                                _st3["other_allowance_extra"] = round(
                                    float(_st3.get("other_allowance_extra")
                                          or 0) + _rem_diff, 2)
                                row["difference_allocation_head"] = (
                                    "Other Allowances")
                    else:
                        # Iter 344 (user request) — EXACT match with the
                        # Freeze: trim from OT first, then Other Allowances.
                        _need = -_diff_g
                        _cut_ot = round(min(float(row.get("ot_pay") or 0), _need), 2)
                        _rem = round(_need - _cut_ot, 2)
                        if _cut_ot:
                            _st3["ot_pay_extra"] = -_cut_ot
                        if _rem:
                            _st3["other_allowance_extra"] = -_rem
                        row["difference_allocation_head"] = "Trimmed"
                    _row2 = compute_compliance_row(
                        emp, merged_pol, int(month_days), _st3,
                        company_structure_pct=payload.structure_pct,
                        statutory_cfg=effective_statutory,
                        firm_pf_enabled=_ff["pf"],
                        firm_esic_enabled=_ff["esic"],
                        firm_pt={"state": _fcp.get("pt_state"),
                                 "slabs": _fcp.get("pt_slabs")},
                        enabled_allowances=enabled_set,
                        custom_allowance_labels=_fm_masks.get("custom_allow_labels"),
                    )
                    # Merge the recomputed earnings + statutory figures into
                    # the row (sheet TDS / Other Deduction / deduction masks
                    # applied earlier stay untouched).
                    for _k in ("basic", "hra", "conveyance", "medical",
                               "special", "others", "ot_pay",
                               "monthly_gross", "gross_paid",
                               "stat_wage_base", "pf_wages", "pf_employee",
                               "pf_employer_epf", "pf_employer_eps",
                               "pf_employer_total", "vpf_amount",
                               "esic_wage_base", "esic_employee",
                               "esic_employer", "calc_note"):
                        if _k in _row2:
                            row[_k] = _row2[_k]
                    if "allowance_heads" in _row2:
                        row["allowance_heads"] = _row2["allowance_heads"]
                    # Iter 646 — show the sheet's per-head amounts under
                    # their own dynamic allowance columns (Others shows the
                    # remainder; totals unchanged — the amount already sits
                    # inside Others via other_allowance_extra).
                    if _alloc_allow > 0 and _ca_tot > 0:
                        _ah646 = dict(row.get("allowance_heads") or {})
                        _sc646 = _alloc_allow / _ca_tot
                        for _l6, _v6 in _ca646.items():
                            _ah646[_l6] = round(
                                float(_ah646.get(_l6) or 0) + _v6 * _sc646)
                        row["allowance_heads"] = _ah646
                    # Iter 657 — the Incentive-routed remainder shows under
                    # the firm's INCENTIVE column (editable in the grid;
                    # the amount already sits inside Others in the totals).
                    if _inc_extra657 > 0:
                        _ah657 = dict(row.get("allowance_heads") or {})
                        _il657 = _inc_labels657[0]
                        _ah657[_il657] = round(
                            float(_ah657.get(_il657) or 0) + _inc_extra657)
                        row["allowance_heads"] = _ah657
                    # PT follows the new gross unless the firm's deduction
                    # mask switched it OFF earlier.
                    if not (_ded_set is not None and "pt" not in _ded_set):
                        row["pt"] = _row2.get("pt", row.get("pt"))
                    # Re-apply the firm's allowance mask: heads zeroed
                    # earlier stay zero; an Others-routed freeze diff
                    # survives even a masked-off Others head (unchanged
                    # behaviour from the old post-compute allocation).
                    if enabled_set is not None:
                        for _head in ("hra", "conveyance", "medical", "special"):
                            if _head not in enabled_set:
                                row[_head] = 0.0
                        if "others" not in enabled_set:
                            row["others"] = round(max(
                                0.0, float(_st3.get("other_allowance_extra") or 0)), 2)
                        row["monthly_gross"] = round(sum(
                            float(row.get(_h) or 0)
                            for _h in ("basic", "hra", "conveyance",
                                       "medical", "special", "others")), 2)
                    # Iter 744 (user request — "Excel import par exact match,
                    # 1 Rs difference mid out"): whole-rupee rounding inside
                    # the recompute rounds Monthly Gross and OT SEPARATELY,
                    # so the re-derived earnings can land ±1 Rs off the
                    # Imported Gross. The residual is absorbed into the SAME
                    # editable head the difference was allocated to (OT when
                    # the diff went to Overtime, otherwise Others — mirrored
                    # under the INCENTIVE column when that head carried the
                    # diff) so Basic+…+Others+OT == Imported Gross EXACTLY.
                    _resid744 = round(
                        _imp_g - (float(row.get("monthly_gross") or 0)
                                  + float(row.get("ot_pay") or 0)), 2)
                    if abs(_resid744) > 0.004:
                        _ot744 = float(row.get("ot_pay") or 0)
                        _oth744 = float(row.get("others") or 0)
                        _head744 = str(
                            row.get("difference_allocation_head") or "")
                        if (("Overtime" in _head744
                             or _oth744 + _resid744 < 0)
                                and _ot744 + _resid744 >= 0):
                            row["ot_pay"] = round(_ot744 + _resid744, 2)
                        else:
                            row["others"] = round(_oth744 + _resid744, 2)
                            row["monthly_gross"] = round(
                                float(row.get("monthly_gross") or 0)
                                + _resid744, 2)
                            if _inc_extra657 > 0:
                                _ah744 = dict(row.get("allowance_heads") or {})
                                _il744 = _inc_labels657[0]
                                _ah744[_il744] = round(
                                    float(_ah744.get(_il744) or 0)
                                    + _resid744, 2)
                                row["allowance_heads"] = _ah744
                    row["gross_paid"] = _imp_g
                    row["total_deduction"] = round(
                        float(row.get("pf_employee") or 0)
                        + float(row.get("esic_employee") or 0)
                        + float(row.get("pt") or 0)
                        + float(row.get("tds") or 0)
                        + float(row.get("other_deduction") or 0)
                        # Iter 616 (user bug) — the sheet-imported ADVANCE
                        # was dropped from Total Ded. by this freeze reset.
                        + float(row.get("advance_recovery") or 0)
                        + float(row.get("master_deduction") or 0), 2)
                    row["net"] = round(_imp_g - row["total_deduction"], 2)
        # Iter 443 (user request) — Freeze as Actual Gross: the Actual run's
        # Adv lands in the ADVANCE deduction column (honours the Firm Master
        # ADVANCE toggle; the ledger recovery skips this row via
        # manual_fields so the imported figure is never double-deducted).
        if _fag_row is not None and _adv_on:
            _adv_imp = round(float(_fag_row.get("adv") or 0), 2)
            _sheet_adv = round(float(row.get("advance_recovery") or 0), 2)
            # Iter 616 (user bug) — a 0 Actual-run Adv used to WIPE the
            # advance routed from the uploaded sheet; the Actual figure now
            # only overrides when it actually has a value.
            _target_adv = _adv_imp if _adv_imp > 0 else _sheet_adv
            _adv_d = round(_target_adv - _sheet_adv, 2)
            if _adv_d:
                row["advance_recovery"] = _target_adv
                row["total_deduction"] = round(
                    float(row.get("total_deduction") or 0) + _adv_d, 2)
                row["net"] = round(float(row.get("net") or 0) - _adv_d, 2)
            if _target_adv > 0:
                row["manual_fields"] = sorted(
                    set(row.get("manual_fields") or []) | {"advance_recovery"})
        # Iter 340 (user request) — OT HOURS derived from the OT AMOUNT:
        # OT Hrs = OT Amt ÷ (per-hour rate × OT multiplier). Per-hour rate
        # follows Firm Master "OT Calculation On" (basic | gross):
        # full-month Basic/Gross ÷ Month Days ÷ Daily HRS. Computed for
        # every row so manual OT-hours entry works on normal runs too.
        _fsf_row = firm_stat_flags.get(emp.get("company_id")) or {}
        row["firm_ot_allowed"] = bool(_fsf_row.get("ot_allowed"))
        _fdh3 = float(merged_pol.get("full_day_hours") or 8.0)
        _otm3 = float(merged_pol.get("ot_multiplier") or 2.0)
        _basis3 = str(_fsf_row.get("ot_calc_basis") or "basic")
        _full3 = (float(row.get("gross_master") or 0) if _basis3 == "gross"
                  else float(row.get("basic_master") or 0))
        if _full3 <= 0:
            _full3 = float(row.get("gross_master") or 0)
        _oth_rate = ((_full3 / float(month_days or 26) / _fdh3) * _otm3
                     if _full3 > 0 and _fdh3 > 0 else 0.0)
        row["ot_hourly_rate"] = round(_oth_rate, 4)
        if (_oth_rate > 0 and float(row.get("ot_pay") or 0) > 0
                and float(row.get("ot_hours") or 0) <= 0):
            row["ot_hours"] = round(float(row["ot_pay"]) / _oth_rate, 2)
        # Iter 313 — ESIC Leave Module auto-import.
        # Iter 477 (user request) — the ESIC Leave Master is AUTHORITATIVE:
        # when the module is linked, the column always mirrors the approved
        # entries (0 when none) — the grid cell is no longer editable.
        _esic_d = (_esic_maps.get(emp.get("company_id")) or {}).get(emp.get("user_id"))
        if _esic_on.get(emp.get("company_id")):
            row["esic_leave_days"] = round(float(_esic_d or 0), 1)
        elif _esic_d:
            row["esic_leave_days"] = round(float(_esic_d), 1)
        # Iter 500 — CTC MODE: stamp the CTC figures on the row so the
        # register / payslip / reports can show them. Gross-mode rows carry
        # nothing new (100% backward compatible).
        if _ctc_meta:
            row["ctc_mode"] = True
            row.update(_ctc_meta)
        # Iter 745 — LATE PENALTY (Attendance-Policy based): once the
        # attendance-driven row is final, the month's penalty lands in the
        # OTHER DEDUCTION column automatically (head "Late Penalty").
        # Manually edited Other Deduction always wins (keep-rule respected).
        # Freeze-as-Actual-Gross rows get it too (penalty is a DEDUCTION —
        # the frozen gross is untouched); imported-sheet runs never build
        # the maps (sheet is authoritative — manual Apply covers them).
        _lp745 = (late_penalty_maps.get(emp.get("company_id")) or {}).get(emp["user_id"])
        if _lp745 and "other_deduction" not in set(row.get("manual_fields") or []):
            _lp_amt = round(float(_lp745.get("penalty_amount") or 0), 2)
            if _lp_amt > 0:
                row["late_count"] = _lp745.get("late_days")
                row["late_penalty_days"] = _lp745.get("penalty_days")
                row["late_penalty_amount"] = _lp_amt
                _od745 = round(float(row.get("other_deduction") or 0), 2)
                row["other_deduction"] = round(_od745 + _lp_amt, 2)
                _odh745 = str(row.get("other_deduction_head") or "").strip()
                row["other_deduction_head"] = (
                    f"{_odh745} + Late Penalty" if (_odh745 and _od745 > 0)
                    else "Late Penalty")
                row["total_deduction"] = round(
                    float(row.get("total_deduction") or 0) + _lp_amt, 2)
                row["net"] = round(float(row.get("net") or 0) - _lp_amt, 2)
        rows.append(row)

    totals = {
        k: round(sum(r.get(k, 0.0) or 0.0 for r in rows), 2)
        for k in (
            "basic", "hra", "conveyance", "medical", "special", "others",
            "monthly_gross", "gross_paid", "ot_pay",
            "pf_wages", "pf_employee", "pf_employer_epf", "pf_employer_eps", "pf_employer_total",
            "esic_wage_base", "esic_employee", "esic_employer",
            "pt", "tds",
            "total_deduction", "net",
            # Iter 310 — Freeze Salary comparison totals.
            "imported_gross", "calculated_gross", "difference",
        )
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
        "structure_pct": payload.structure_pct or {},
        "statutory_cfg": payload.statutory_cfg or {},
        # Iter 387 — FULL effective statutory snapshot (standard + firm
        # overrides + per-run cfg) for the grid's client-side recompute and
        # the "View Calculation" layer. Reprocess still re-merges live
        # settings via statutory_cfg above.
        "statutory_effective": effective_statutory,
        "employees_count": len(rows),
        "rows": rows,
        # Iter 167 — resigned staff auto-excluded from this run.
        "excluded_resigned": excluded_resigned,
        "excluded_resigned_count": len(excluded_resigned),
        "attendance_source": (
            "actual_salary_freeze" if (_fag_used and not payload.use_imported_sheet)
            else ("imported_sheet" if payload.use_imported_sheet else "biometric")),
        # Iter 310 — imported-sheet runs are FROZEN (immutable snapshot
        # is written alongside the run — see freeze_salary_snapshots).
        # Iter 443 — Freeze-as-Actual-Gross runs show the Freeze badge too.
        "frozen": bool(payload.use_imported_sheet) or _fag_used,

        "totals": totals,
        # Iter 485 — master snapshot metadata (additive; None for scopes
        # without a firm filter where no snapshot applies).
        "master_snapshot": _snap_meta,
        "generated_by": admin["user_id"],
        "generated_at": now_iso(),
    }


async def _copy_last_month_from_legacy(
    admin: dict,
    payload: ComplianceSalaryRunCreate,
    gate_cid: Optional[str],
    group: str,
    prev_month: str,
) -> Optional[dict]:
    """Iter 375 (user bug) — 'Copy Last Month Salary' FALLBACK: after the
    Old-DB migration the previous month often exists ONLY in the imported
    legacy history (``legacy_salary_history``, kind='online') — the copy
    used to fail with "No Compliance Salary found". This builds the new
    month's editable DRAFT from those locked Old-DB rows instead."""
    from utils.salary_run import actual_days_in_month
    q: Dict[str, Any] = {"kind": "online", "month": prev_month}
    if gate_cid:
        q["company_id"] = gate_cid
    if group:
        q["employee_type"] = {"$regex": f"^{re.escape(group)}$", "$options": "i"}
    hist = await db.legacy_salary_history.find(q, {"_id": 0}).to_list(6000)
    if not hist:
        return None
    y, m = int(payload.month[:4]), int(payload.month[5:7])
    company_doc = await db.companies.find_one(
        {"company_id": gate_cid}, {"_id": 0, "name": 1}) if gate_cid else None
    # Resolve portal employees by user_id first, employee code second.
    uids = [h.get("user_id") for h in hist if h.get("user_id")]
    codes = [h.get("emp_code") for h in hist if h.get("emp_code")]
    _or: List[dict] = []
    if uids:
        _or.append({"user_id": {"$in": uids}})
    if codes:
        _or.append({"employee_code": {"$in": codes + [str(c) for c in codes]}})
    users_by_uid: Dict[str, dict] = {}
    users_by_code: Dict[int, dict] = {}
    if _or:
        async for u in db.users.find(
            {"$or": _or},
            {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
             "father_name": 1, "designation": 1, "uan_no": 1, "esi_ip_no": 1,
             "pf_no": 1, "exit_date": 1, "resign_date": 1, "disabled": 1,
             "company_id": 1, "employee_type": 1, "is_onroll": 1},
        ):
            users_by_uid[u["user_id"]] = u
            try:
                users_by_code[int(float(u.get("employee_code")))] = u
            except (TypeError, ValueError):
                pass

    def _amt(heads: Optional[dict], *needles: str) -> float:
        tot = 0.0
        for k, v in (heads or {}).items():
            ku = str(k).upper()
            if any(n in ku for n in needles):
                tot += float(v or 0)
        return round(tot, 2)

    rows: List[dict] = []
    skipped: List[dict] = []
    for h in hist:
        u = users_by_uid.get(h.get("user_id"))
        if u is None and h.get("emp_code") is not None:
            try:
                u = users_by_code.get(int(float(h["emp_code"])))
            except (TypeError, ValueError):
                u = None
        if u is None:
            skipped.append({"user_id": h.get("user_id"),
                            "name": h.get("name"),
                            "reason": "not found in portal"})
            continue
        if u.get("disabled") is True or _month_is_after_exit(u, payload.month):
            skipped.append({"user_id": u["user_id"], "name": h.get("name")})
            continue
        earn = h.get("earn_heads") or {}
        ded = h.get("deduct_heads") or {}
        gross = round(float(h.get("gross") or 0), 2)
        basic = round(float(h.get("basic") or 0), 2)
        hra = _amt(earn, "HRA")
        conv = _amt(earn, "CONV")
        medical = _amt(earn, "MEDICAL")
        ot_pay = _amt(earn, "OVER TIME", "OVERTIME")
        others = round(max(
            0.0, gross - basic - hra - conv - medical - ot_pay), 2)
        ee_pf = round(float(h.get("ee_pf") or 0), 2)
        er_pf = round(float(h.get("er_pf") or 0), 2)
        pf_wages = round(float(h.get("pf_basic") or 0), 2)
        eps = round(min(pf_wages * 0.0833, er_pf), 2) if er_pf else 0.0
        epf_er = round(er_pf - eps, 2) if er_pf else 0.0
        esi_ee = _amt(ded, "ESI")
        er_esi = round(float(h.get("er_esi") or 0), 2)
        pt = _amt(ded, "PT", "PROF")
        tds = _amt(ded, "TDS")
        other_ded = round(float(h.get("less_adv") or 0)
                          + float(h.get("less_other") or 0)
                          + float(h.get("less_loan") or 0), 2)
        total_ded = round(ee_pf + esi_ee + pt + tds + other_ded, 2)
        net = round(float(h.get("net") or 0), 2) or round(gross - total_ded, 2)
        _esic_on = esi_ee > 0 or er_esi > 0
        rows.append({
            "user_id": u["user_id"],
            "employee_code": u.get("employee_code") or h.get("emp_code"),
            "name": u.get("name") or h.get("name"),
            "father_name": u.get("father_name"),
            "designation": u.get("designation"),
            "employee_type": h.get("employee_type") or u.get("employee_type"),
            "is_onroll": bool(u.get("is_onroll", True)),
            "company_id": u.get("company_id") or gate_cid,
            "company_name": (company_doc or {}).get("name"),
            "uan_no": u.get("uan_no"),
            "esi_ip_no": u.get("esi_ip_no"),
            "pf_no": u.get("pf_no"),
            "salary_mode": "monthly",
            "month_days": h.get("month_days"),
            "present_days": round(float(h.get("present_days") or 0), 2),
            "ot_hours": round(float(h.get("ot_hours") or 0), 2),
            "basic": basic, "hra": hra, "conveyance": conv,
            "medical": medical, "special": 0.0, "others": others,
            "monthly_gross": round(gross - ot_pay, 2),
            "ot_pay": ot_pay,
            "gross_paid": gross,
            "stat_wage_base": pf_wages or basic,
            "pf_applicable": ee_pf > 0,
            "pf_eligible": ee_pf > 0,
            "pf_wages": pf_wages,
            "pf_employee": ee_pf,
            "pf_employer_epf": epf_er,
            "pf_employer_eps": eps,
            "pf_employer_total": er_pf,
            "esic_applicable": _esic_on,
            "esic_eligible": _esic_on,
            "esic_wage_base": gross if _esic_on else 0.0,
            "esic_employee": esi_ee,
            "esic_employer": er_esi,
            "pt": pt,
            "tds": tds,
            "other_deduction": other_ded,
            "other_deduction_head": "Advance/Other" if other_ded else None,
            "total_deduction": total_ded,
            "net": net,
            "copied_from_legacy": True,
        })
    if not rows:
        return None
    totals = {
        k: round(sum(float(r.get(k) or 0.0) for r in rows), 2)
        for k in (
            "basic", "hra", "conveyance", "medical", "special", "others",
            "monthly_gross", "gross_paid", "ot_pay",
            "pf_wages", "pf_employee", "pf_employer_epf", "pf_employer_eps",
            "pf_employer_total",
            "esic_wage_base", "esic_employee", "esic_employer",
            "pt", "tds", "total_deduction", "net",
        )
    }
    _mdays = None
    for h in hist:
        try:
            _mdays = int(float(h.get("month_days")))
            break
        except (TypeError, ValueError):
            continue
    return {
        "month": payload.month,
        "year": y,
        "month_number": m,
        "month_days": _mdays or actual_days_in_month(y, m),
        "default_month_days": actual_days_in_month(y, m),
        "company_id": gate_cid,
        "employee_type": payload.employee_type,
        "structure_pct": {},
        "statutory_cfg": {},
        "employees_count": len(rows),
        "rows": rows,
        "totals": totals,
        "attendance_source": "copied_last_month_legacy",
        "copied_from_month": prev_month,
        "copied_from_legacy": True,
        "copied_skipped": skipped,
        "frozen": False,
        "generated_by": admin["user_id"],
        "generated_at": now_iso(),
    }


async def _copy_last_month_compliance_run(
    admin: dict,
    payload: ComplianceSalaryRunCreate,
    gate_cid: Optional[str],
    group: str,
) -> dict:
    """Iter 330 (user request) — 'Copy Last Month Salary': builds the new
    month's run by copying LAST MONTH's rows exactly as they were (same
    Present Days, Gross, PF/ESIC/PT/TDS, Net). Employees who exited before
    the new month (or were disabled) are dropped. The copied run is a
    normal editable DRAFT — it can be edited, saved and finalized."""
    from utils.salary_run import actual_days_in_month
    y, m = int(payload.month[:4]), int(payload.month[5:7])
    prev_month = f"{y - 1}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"
    _grp_q = (
        {"$regex": f"^{re.escape(group)}$", "$options": "i"} if group
        else {"$in": [None, ""]}
    )
    src = await db.compliance_salary_runs.find_one(
        {"month": prev_month, "company_id": gate_cid, "employee_type": _grp_q},
        {"_id": 0},
        sort=[("finalized", -1), ("generated_at", -1)],
    )
    if not src or not (src.get("rows") or []):
        # Iter 375 (user bug) — after the Old-DB lock, last month exists
        # only in the imported legacy history: copy from there instead.
        legacy = await _copy_last_month_from_legacy(
            admin, payload, gate_cid, group, prev_month)
        if legacy is not None:
            return legacy
        raise HTTPException(
            status_code=404,
            detail=f"No Compliance Salary found for {prev_month} (this firm/"
                   "group) — neither a portal run nor imported Old-DB salary "
                   "history. Process or import last month first, then copy.",
        )
    # Drop employees who exited before the new month or were disabled.
    src_rows = src.get("rows") or []
    uids = [r.get("user_id") for r in src_rows if r.get("user_id")]
    users_by_id: Dict[str, dict] = {}
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "exit_date": 1, "resign_date": 1,
             "disabled": 1},
        ):
            users_by_id[u["user_id"]] = u
    rows = []
    skipped = []
    for r in src_rows:
        u = users_by_id.get(r.get("user_id")) or {}
        if u.get("disabled") is True or _month_is_after_exit(u, payload.month):
            skipped.append({"user_id": r.get("user_id"), "name": r.get("name")})
            continue
        nr = dict(r)
        # Last month's advance EMI must not be carried verbatim — the
        # endpoint re-applies the CURRENT month's advance recovery after
        # this copy (keeps the advance ledger correct).
        _adv = round(float(nr.get("advance_recovery") or 0), 2)
        if _adv:
            nr["advance_recovery"] = 0.0
            nr["total_deduction"] = round(
                float(nr.get("total_deduction") or 0) - _adv, 2)
            nr["net"] = round(float(nr.get("net") or 0) + _adv, 2)
        rows.append(nr)
    totals = {
        k: round(sum(float(r.get(k) or 0.0) for r in rows), 2)
        for k in (
            "basic", "hra", "conveyance", "medical", "special", "others",
            "monthly_gross", "gross_paid", "ot_pay",
            "pf_wages", "pf_employee", "pf_employer_epf", "pf_employer_eps",
            "pf_employer_total",
            "esic_wage_base", "esic_employee", "esic_employer",
            "pt", "tds", "total_deduction", "net",
        )
    }
    return {
        "month": payload.month,
        "year": y,
        "month_number": m,
        "month_days": int(src.get("month_days") or actual_days_in_month(y, m)),
        "default_month_days": actual_days_in_month(y, m),
        "company_id": gate_cid,
        "employee_type": payload.employee_type,
        "structure_pct": src.get("structure_pct") or {},
        "statutory_cfg": src.get("statutory_cfg") or {},
        "employees_count": len(rows),
        "rows": rows,
        "totals": totals,
        "attendance_source": "copied_last_month",
        "copied_from_month": prev_month,
        "copied_from_run_id": src.get("run_id"),
        "copied_skipped": skipped,
        "frozen": False,
        "generated_by": admin["user_id"],
        "generated_at": now_iso(),
    }


async def _firm_offline_salary_enabled(company_id: Optional[str]) -> bool:
    """Iter 164 — True when the firm's Firm Master has 'Offline Salary'
    (salary_process.offline_salary) enabled. Off-roll employees are only
    allowed in such firms; everywhere else employees are always On-roll."""
    if not company_id:
        return False
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "salary_process": 1},
    )
    return bool(((fm or {}).get("salary_process") or {}).get("offline_salary"))


async def _firm_biometric_attendance_enabled(company_id: Optional[str]) -> bool:
    """Iter 165 — True when the firm's Firm Master has 'Bio Matrix
    Attendance' (salary_process.bio_matrix_attendance) enabled. Gates the
    per-employee fingerprint verification requirement."""
    if not company_id:
        return False
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "salary_process": 1},
    )
    return bool(((fm or {}).get("salary_process") or {}).get("bio_matrix_attendance"))


async def _require_firm_salary_permission(company_id: Optional[str], kind: str) -> None:
    """Iter 98 — Firm Master 'Salary Process Settings' gating.

    * ``kind='online'``  → Compliance Salary requires ``salary_process.online_salary``.
    * ``kind='offline'`` → Salary Process (Actual) requires ``salary_process.offline_salary``.

    Raises 403 "You are not permitted for this" when the flag is OFF (or the
    firm was never configured). Skipped when no single firm is in scope
    (e.g. super-admin without a company filter).
    """
    if not company_id:
        return
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "salary_process": 1},
    )
    sp = (fm or {}).get("salary_process") or {}
    allowed = sp.get("online_salary") if kind == "online" else sp.get("offline_salary")
    if not allowed:
        label = (
            "Online Salary (Compliance Salary)" if kind == "online"
            else "Offline Salary (Salary Process Actual)"
        )
        raise HTTPException(
            status_code=403,
            detail=(
                f"You are not permitted for this — {label} is not enabled for "
                "this firm. Enable it in Firm Master → Salary Process Settings."
            ),
        )


@api.post("/admin/compliance-salary-runs")
async def create_compliance_salary_run(
    payload: ComplianceSalaryRunCreate,
    authorization: Optional[str] = Header(None),
):
    """Compute + persist a new compliance salary run (PF/ESIC/PT/TDS)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    # Iter 62 — Compliance is OPT-IN for company admins. Super Admin must
    # explicitly enable compliance_salary:write on the firm's access rights.
    await require_employer_permission(admin, "compliance_salary:write", db)
    return await _create_compliance_salary_run_core(payload, admin)


def _apply_daily_rate_revisions(emp: dict, month: str, month_days: int,
                                grid_cells: Optional[dict]):
    """Iter 626 (user spec §12) — mid-month DAILY RATE REVISION.

    Employee Master may carry ``daily_rate_revisions``:
        [{"effective_from": "YYYY-MM-DD", "rate": 500}, ...]
    For DAILY-rated employees, the applicable rate for each day of the
    month is the latest revision effective on that day (master structure
    = the base rate before the first revision). The month is consolidated
    into ONE row by scaling the per-day head amounts by the weighted
    factor  Σ rate_on(day) ÷ (days × base_rate):
      • with punch data, weights use the ACTUAL worked dates;
      • without punch data (manually typed days), weights use each rate
        period's share of the calendar month.
    Historical runs are untouched — this only affects fresh computes.
    Returns (possibly-scaled shallow copy of emp, audit dict | None).
    """
    revs = [r for r in (emp.get("daily_rate_revisions") or [])
            if r.get("effective_from") and r.get("rate")]
    if not revs:
        return emp, None
    heads = emp.get("salary_structure_compliance") or []
    is_daily = any(str(h.get("rate_type") or "").lower() == "daily" for h in heads) \
        or str(emp.get("compliance_rate_type") or "").lower() == "daily"
    if not is_daily:
        return emp, None
    base_rate = sum(float(h.get("amount") or 0) for h in heads
                    if str(h.get("rate_type") or "daily").lower() == "daily")
    if base_rate <= 0:
        return emp, None
    revs.sort(key=lambda r: str(r["effective_from"]))

    def rate_on(date_str: str) -> float:
        r = base_rate
        for rev in revs:
            if str(rev["effective_from"]) <= date_str:
                r = float(rev["rate"])
        return r

    # 1. actual worked dates from the punch grid when available
    dates: List[str] = []
    for d, cell in ((grid_cells or {}).get("days") or {}).items():
        c = cell or {}
        if float(c.get("hours") or c.get("raw_hours") or 0) > 0:
            dates.append(str(d) if str(d).startswith(month) else f"{month}-{str(d)[-2:]}")
    if dates:
        weighted = sum(rate_on(d) for d in dates) / (len(dates) * base_rate)
    else:
        # 2. fallback — calendar-proportional weighting over the month
        all_days = [f"{month}-{i:02d}" for i in range(1, month_days + 1)]
        weighted = sum(rate_on(d) for d in all_days) / (month_days * base_rate)
    if abs(weighted - 1.0) < 0.0001:
        return emp, None
    scaled = dict(emp)
    scaled["salary_structure_compliance"] = [
        {**h, "amount": round(float(h.get("amount") or 0) * weighted, 4)}
        if str(h.get("rate_type") or "daily").lower() == "daily" else dict(h)
        for h in heads]
    for k in ("pf_basic", "compliance_gross", "compliance_basic"):
        if float(emp.get(k) or 0) > 0:
            scaled[k] = round(float(emp[k]) * weighted, 4)
    audit = {"base_rate": base_rate, "weighted_factor": round(weighted, 6),
             "effective_rate": round(base_rate * weighted, 2),
             "revisions": revs,
             "weight_source": "punch_dates" if dates else "calendar_proportional"}
    return scaled, audit


async def _create_compliance_salary_run_core(
    payload: ComplianceSalaryRunCreate, admin: dict,
) -> dict:
    """Iter 335 — shared core so the sheet import can auto-reprocess the
    month right after importing (user request)."""
    # Iter 98 — Firm Master gate: Online Salary must be enabled for the firm.
    _gate_cid = (
        admin.get("company_id") if admin["role"] == "company_admin"
        else payload.company_id
    )
    await _require_firm_salary_permission(_gate_cid, "online")
    # Iter 129f (user directive) — a FINALIZED month can never be processed
    # again. Iter 257 (user bug): the block is scoped to the SAME employee
    # group — finalizing STAFF must not stop LABOUR from being processed.
    _grp0 = (payload.employee_type or "").strip()
    _fin_q: Dict[str, Any] = {"month": payload.month, "finalized": True}
    if payload.company_id:
        _fin_q["company_id"] = payload.company_id
    _fin_q["employee_type"] = (
        {"$regex": f"^{re.escape(_grp0)}$", "$options": "i"} if _grp0
        else {"$in": [None, ""]}
    )
    if await db.compliance_salary_runs.find_one(_fin_q, {"_id": 1}):
        raise HTTPException(
            status_code=409,
            detail="This month's Compliance salary is already FINALIZED for this "
                   "employee group — it cannot be processed again. Use Unlock "
                   "Request to de-finalize first.",
        )
    # Iter 297 (user directive) — NON-DESTRUCTIVE REPROCESS: when a draft
    # run already exists for this firm + month + group, its rows are
    # passed into the compute so the previously ENTERED days / manual
    # deductions are KEPT (updated in place — never reset to zero).
    _prev_run = await db.compliance_salary_runs.find_one(
        {
            "month": payload.month,
            "company_id": _gate_cid,
            "employee_type": (
                {"$regex": f"^{re.escape(_grp0)}$", "$options": "i"} if _grp0
                else {"$in": [None, ""]}
            ),
            "finalized": {"$ne": True},
        },
        {"_id": 0, "rows": 1, "month_days": 1, "attendance_source": 1,
         "run_id": 1},
        sort=[("generated_at", -1)],
    )
    # Iter 426 (user request) — MONTH DAYS LOCK: once a salary is processed
    # for this firm + month + group, every reprocess (existing OR blank)
    # proceeds with the SAME month days — an accidentally changed value in
    # the form is ignored.
    # Iter 616 (user bug) — IMPORTED-SHEET runs: the typed Month Days
    # (Override) from the form ALWAYS wins — the sheet import used to be
    # silently locked to the previous run's days (e.g. 31) even when the
    # admin entered 26/30 in the Month Days field.
    if (_prev_run and _prev_run.get("month_days")
            and not payload.override_month_days
            and not (payload.use_imported_sheet and payload.month_days)):
        payload.month_days = int(_prev_run["month_days"])
    elif (_gate_cid and not payload.override_month_days
            and not (payload.use_imported_sheet and payload.month_days)):
        # Iter 643 (user bug) — EXCEL IMPORT runs used to skip this branch
        # entirely, so a fresh month imported via sheet defaulted to the
        # CALENDAR days (31) and PF was computed ÷31 instead of the firm's
        # configured default (e.g. Fixed 26). The Firm Master fixed-days
        # rule now applies to imported-sheet runs too; a typed Month Days
        # (Override) still always wins (Iter 616 rule preserved).
        # Iter 427b (user clarification) — FIXED DAYS (26/30/31): the run's
        # MONTH DAYS are FETCHED from the Firm Master's Fixed Days option,
        # so the whole salary basis (divisor + default present days) is the
        # selected fixed figure.
        _fm_sp = ((await db.firm_masters.find_one(
            {"company_id": _gate_cid}, {"_id": 0, "salary_process": 1})
        ) or {}).get("salary_process") or {}
        if str(_fm_sp.get("days_calc_method") or "") == "fixed":
            try:
                payload.month_days = int(_fm_sp.get("days_calc_fixed") or 26)
            except (TypeError, ValueError):
                payload.month_days = 26
    _prev_rows: Dict[str, dict] = {
        r.get("user_id"): r for r in ((_prev_run or {}).get("rows") or [])
    }
    # Iter 426 (user request) — "Reprocess from BLANK": ignore the previous
    # draft entirely so the sheet rebuilds fresh from attendance + master.
    if payload.fresh:
        _prev_rows = {}
    # Iter 728 (user bug — "Reprocess with existing data hides the Freeze
    # Salary column"): a run originally built FROM THE IMPORTED SHEET
    # lost its Freeze columns when the reprocess request omitted
    # use_imported_sheet (the form toggle resets to OFF on reload). A
    # reprocess "With EXISTING Data" now INHERITS the imported-sheet
    # source from the previous draft — provided the sheet data still
    # exists for the month. "From BLANK" keeps the form's choice.
    if (_prev_run and not payload.fresh and not payload.use_imported_sheet
            and str(_prev_run.get("attendance_source") or "") == "imported_sheet"):
        _imp_q728: dict = {"month": payload.month}
        if _gate_cid:
            _imp_q728["company_id"] = _gate_cid
        if await db.compliance_import_entries.count_documents(_imp_q728) > 0:
            payload.use_imported_sheet = True
    # Iter 330 (user request) — "Copy Last Month Salary": build this
    # month's run as an EXACT copy of last month's rows instead of
    # recomputing from attendance / master.
    if payload.copy_last_month:
        run = await _copy_last_month_compliance_run(
            admin, payload, _gate_cid, _grp0)
    elif (_prev_run and not payload.fresh
            and str(_prev_run.get("attendance_source") or "")
            .startswith("copied_last_month")):
        # Iter 616 (user bug) — reprocess "With EXISTING Data" over a
        # COPIED sheet used to silently RECOMPUTE every amount from the
        # CURRENT Employee Master (only the days were kept), so the saved
        # copied values and the reprocessed sheet mismatched. A copied
        # sheet is now kept VERBATIM (rows + totals + saved edits);
        # "From BLANK" still rebuilds fresh from attendance + master.
        _full_prev = await db.compliance_salary_runs.find_one(
            {"run_id": _prev_run["run_id"]}, {"_id": 0})
        run = dict(_full_prev or {})
        run["generated_by"] = admin["user_id"]
        run["generated_at"] = now_iso()
    else:
        run = await _compute_compliance_run(admin, payload, prev_rows=_prev_rows)
    run["run_id"] = f"csrun_{uuid.uuid4().hex[:12]}"
    if _prev_rows and not payload.copy_last_month:
        run["reprocessed"] = True
    # Iter 310 — FREEZE SALARY: imported-sheet runs freeze the exact
    # imported attendance/earnings at process time.
    if payload.use_imported_sheet:
        run["frozen"] = True
        run["frozen_at"] = now_iso()
        run["freeze_snapshot_id"] = f"frz_{uuid.uuid4().hex[:12]}"
    # Advance Management — auto-deduct active advance EMIs / single-shot
    # recoveries into the rows (idempotent per month+process).
    from routes.advances import apply_advance_recovery
    # Iter 443 — Master-linked: rows whose firm disabled the ADVANCE head
    # never receive ledger recoveries (column is hidden on the grid too).
    _adv_rows = [r for r in run["rows"]
                 if r.get("enabled_deductions") is None
                 or "advance" in r["enabled_deductions"]]
    _adv_total = await apply_advance_recovery(
        payload.company_id, payload.month, "compliance", run["run_id"], _adv_rows)
    if _adv_total or any(r.get("advance_recovery") for r in run["rows"]):
        t = run.get("totals") or {}
        t["advance_recovery"] = round(sum(float(r.get("advance_recovery") or 0) for r in run["rows"]), 2)
        t["total_deduction"] = round(sum(float(r.get("total_deduction") or 0) for r in run["rows"]), 2)
        t["net"] = round(sum(float(r.get("net") or 0) for r in run["rows"]), 2)
        run["totals"] = t
    # Iter 174 (user directive) — REPLACE old data: a fresh process for the
    # same firm + month + employee group deletes the previous draft run(s)
    # so only the newest data exists (finalized runs are already blocked
    # above and are never touched).
    _grp = (payload.employee_type or "").strip()
    # Iter 757 (user request) — the draft being replaced is versioned
    # first so its corrections stay in the month's History.
    if _prev_run and (_prev_run.get("rows") or []):
        await _snapshot_run_version(
            {**_prev_run, "company_id": _gate_cid, "month": payload.month,
             "employee_type": payload.employee_type},
            admin, "pre_reprocess")
    await db.compliance_salary_runs.delete_many({
        "month": payload.month,
        # Iter 297 — scope by the EFFECTIVE firm (company_admin's own firm
        # when the payload omits company_id) so old drafts never pile up.
        "company_id": _gate_cid,
        "employee_type": (
            {"$regex": f"^{re.escape(_grp)}$", "$options": "i"} if _grp
            else {"$in": [None, ""]}
        ),
        "finalized": {"$ne": True},
    })
    await db.compliance_salary_runs.insert_one(run)
    # Iter 666 — notification layer (never blocks processing).
    try:
        from utils.notify import emit as _notify
        await _notify(db, title="Salary Processing Completed",
                      message=(f"{payload.month} compliance salary processed for "
                               f"{len(run.get('rows') or [])} employee(s)"
                               f"{' from imported sheet' if payload.use_imported_sheet else ''}."),
                      audience="admins", company_id=payload.company_id,
                      category="salary",
                      priority="important",
                      actor_name=admin.get("name") or admin.get("email"),
                      action_url=f"/compliance-salary-run?run_id={run['run_id']}",
                      reference_id=run["run_id"])
    except Exception:
        pass
    # Iter 310 — immutable Freeze Salary snapshot (never edited by
    # save-rows / reprocess — kept as the audit copy of what was imported
    # and how the difference was allocated).
    if payload.use_imported_sheet:
        await db.freeze_salary_snapshots.insert_one({
            "snapshot_id": run["freeze_snapshot_id"],
            "run_id": run["run_id"],
            "month": payload.month,
            "company_id": _gate_cid,
            "employee_type": _grp or None,
            "source": "imported_sheet",
            "frozen_at": run["frozen_at"],
            "frozen_by": admin["user_id"],
            "rows": [
                {k: r.get(k) for k in (
                    "user_id", "name", "employee_code", "present_days",
                    "imported_gross", "calculated_gross", "difference",
                    "difference_allocation_head", "ot_pay", "others",
                    "monthly_gross", "gross_paid", "total_deduction", "net",
                )} for r in run.get("rows") or []
            ],
        })
    # Iter 182 — audit trail
    from routes.salary_audit import write_salary_audit
    _audit_msg = (
        f"Copied {len(run.get('rows') or [])} employees from "
        f"{run.get('copied_from_month')} (Copy Last Month Salary)"
        if payload.copy_last_month
        else f"Processed {len(run.get('rows') or [])} employees"
    )
    await write_salary_audit(admin, "process", run, _audit_msg)
    # Iter 746 — approved OT consumed by this payroll run is now LOCKED
    # (status payroll_processed → unauthorized modification blocked).
    if payload.company_id and not payload.use_imported_sheet:
        from routes.ot_management import (
            effective_ot_policy, mark_ot_payroll_processed)
        try:
            _p_ot746 = await effective_ot_policy(payload.company_id)
            if _p_ot746.get("enabled") and _p_ot746.get("approval_required"):
                await mark_ot_payroll_processed(payload.company_id, payload.month)
        except Exception:
            pass
    # Iter 485 — audit the master-snapshot lifecycle events.
    _sm = run.get("master_snapshot") or {}
    if _sm.get("created"):
        await write_salary_audit(
            admin, "snapshot_created", run,
            f"Master snapshot v1 frozen ({_sm.get('employees')} employees)")
    elif _sm.get("appended"):
        await write_salary_audit(
            admin, "snapshot_appended", run,
            f"{_sm['appended']} new employee(s) appended to snapshot "
            f"v{_sm.get('version')}")
    return {"ok": True, "run": {k: v for k, v in run.items() if k != "_id"}}


@api.get("/admin/compliance-salary-runs")
async def list_compliance_salary_runs(
    company_id: Optional[str] = Query(None),
    company_ids: Optional[List[str]] = Query(
        None, description="Cross-firm filter. Ignored for company_admin."
    ),
    month: Optional[str] = Query(None),
    fy_start_year: Optional[int] = Query(None),
    finalized_only: bool = Query(
        False, description="Iter 174 — only FINALIZED runs (Automation screens), "
                           "deduped to the newest run per firm+month+group."),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    # Iter 62 — Compliance is OPT-IN for company admins.
    await require_employer_permission(admin, "compliance_salary:read", db)
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
    if fy_start_year is not None:
        y = int(fy_start_year)
        q["month"] = q.get("month") or {"$gte": f"{y}-04", "$lte": f"{y + 1}-03"}
    if finalized_only:
        q["finalized"] = True
    runs = await db.compliance_salary_runs.find(
        q, {"_id": 0, "rows": 0},
    ).sort("generated_at", -1).to_list(500)
    if finalized_only:
        # Keep only the NEWEST run per firm + month + employee group so
        # replaced/reprocessed data never shows alongside the old copy.
        seen: set = set()
        deduped = []
        for r in runs:
            key = (r.get("company_id"), r.get("month"), r.get("employee_type"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
        runs = deduped
    # Iter 85 — Enrich with generator/finalizer names for audit display.
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
    # Iter 452 (user request) — firm name for download filenames
    # ("FIRMNAME_MMYYYY.txt" on the PF/ESIC Upload screen).
    _cids = {r.get("company_id") for r in runs if r.get("company_id")}
    _cname: dict = {}
    if _cids:
        async for c in db.companies.find(
            {"company_id": {"$in": list(_cids)}}, {"_id": 0, "company_id": 1, "name": 1},
        ):
            _cname[c["company_id"]] = c.get("name") or ""
    for r in runs:
        r["company_name"] = _cname.get(r.get("company_id"), "")
    return {"runs": runs}


@api.get("/admin/compliance-salary-runs/{run_id}")
async def get_compliance_salary_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    return {"run": run}


async def _snapshot_run_version(run: dict, admin: dict, kind: str,
                                rows: Optional[list] = None,
                                totals: Optional[dict] = None) -> None:
    """Iter 757 (user request) — every draft save / finalize / reprocess
    stores a full VERSION of the sheet (rows + totals) so each correction
    round can be seen later and restored. Never blocks the main action."""
    try:
        _rows = rows if rows is not None else (run.get("rows") or [])
        _tot = totals if totals is not None else (run.get("totals") or {})
        last = await db.compliance_run_versions.find_one(
            {"run_id": run["run_id"]}, {"version_no": 1},
            sort=[("version_no", -1)])
        vno = int((last or {}).get("version_no") or 0) + 1
        await db.compliance_run_versions.insert_one({
            "version_id": f"crv_{uuid.uuid4().hex[:10]}",
            "run_id": run["run_id"],
            "company_id": run.get("company_id"),
            "month": run.get("month"),
            "employee_type": run.get("employee_type"),
            "version_no": vno,
            "kind": kind,  # draft | finalize | pre_reprocess | restore
            "rows": _rows,
            "totals": _tot,
            "rows_count": len(_rows),
            "net_total": round(sum(float(r.get("net") or 0) for r in _rows), 2),
            "saved_at": now_iso(),
            "saved_by": admin.get("user_id"),
            "saved_by_name": admin.get("name") or admin.get("email"),
        })
        stale = await db.compliance_run_versions.find(
            {"run_id": run["run_id"]}, {"version_id": 1},
        ).sort("version_no", -1).skip(30).to_list(200)
        if stale:
            await db.compliance_run_versions.delete_many(
                {"version_id": {"$in": [s["version_id"] for s in stale]}})
    except Exception as _e:
        logger.warning("[run-versions] snapshot failed run=%s: %s",
                       run.get("run_id"), _e)


@api.get("/admin/compliance-salary-runs/{run_id}/versions")
async def list_compliance_run_versions(
    run_id: str, authorization: Optional[str] = Header(None),
):
    """Iter 757 (user request) — version history of a salary sheet: every
    Save-as-Draft / Finalize / Reprocess is listed with who + when + net."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    run = await db.compliance_salary_runs.find_one(
        {"run_id": run_id}, {"_id": 0, "company_id": 1, "finalized": 1})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    docs = await db.compliance_run_versions.find(
        # Iter 757 — history is MONTH-scoped (firm + month + group): a
        # fresh Salary Process replaces the draft with a NEW run_id, but
        # its earlier corrections must stay visible.
        ({"company_id": run.get("company_id"), "month": run.get("month"),
          "employee_type": run.get("employee_type")}
         if run.get("company_id") and run.get("month")
         else {"run_id": run_id}),
        {"_id": 0, "rows": 0, "totals": 0},
    ).sort([("saved_at", -1)]).to_list(50)
    return {"versions": docs, "finalized": bool(run.get("finalized"))}


@api.post("/admin/compliance-salary-runs/{run_id}/versions/{version_id}/restore")
async def restore_compliance_run_version(
    run_id: str, version_id: str,
    authorization: Optional[str] = Header(None),
):
    """Iter 757 (user request) — put a saved version's rows back on the
    run (the current state is snapshotted first, so nothing is lost)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "compliance_salary:write", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if run.get("finalized"):
        raise HTTPException(
            status_code=400,
            detail="Run is FINALIZED (read-only). Unlock it first, then restore.")
    ver = await db.compliance_run_versions.find_one(
        {"version_id": version_id}, {"_id": 0})
    if not ver or (run.get("company_id")
                   and ver.get("company_id") != run.get("company_id")):
        raise HTTPException(status_code=404, detail="Version not found")
    # Current state is snapshotted FIRST so the restore itself is undoable.
    await _snapshot_run_version(run, admin, "pre_restore")
    updates = {
        "rows": ver.get("rows") or [],
        "totals": ver.get("totals") or {},
        "draft_saved_at": now_iso(),
        "draft_saved_by": admin["user_id"],
        "restored_from_version": ver.get("version_no"),
    }
    await db.compliance_salary_runs.update_one({"run_id": run_id}, {"$set": updates})
    from routes.salary_audit import write_salary_audit
    await write_salary_audit(
        admin, "restore_version", run,
        f"Restored sheet version #{ver.get('version_no')} "
        f"({ver.get('kind')}, saved {ver.get('saved_at')})")
    return {"ok": True, "restored_version_no": ver.get("version_no")}


@api.post("/admin/compliance-salary-runs/{run_id}/save-rows")
async def save_compliance_run_rows(
    run_id: str,
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """Iter 145 — P0 fix: persist grid edits (Present Days, Others, Other
    Deduction and their recomputed row values) made in the Compliance
    Salary sheet. Previously "Save as Draft" saved NOTHING — every edit
    was client-side only and vanished when the run was reopened."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "compliance_salary:write", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if run.get("finalized"):
        raise HTTPException(status_code=400, detail="Run is finalized (read-only). Unlock it first.")

    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail="rows list is required")
    # Iter 420 (user rule) — Present Days can NEVER exceed the number of
    # days in the run's month.
    from utils.salary_run import actual_days_in_month, parse_month
    try:
        _y, _m = parse_month(run.get("month") or "")
        month_days = actual_days_in_month(_y, _m)
    except Exception:
        month_days = 31
    _bad = []
    for r in rows:
        try:
            _pd = float(r.get("present_days") or 0)
        except (TypeError, ValueError):
            _pd = 0.0
        if _pd > month_days:
            _bad.append(f"{r.get('name') or r.get('employee_code') or r.get('user_id')} "
                        f"({_pd:g} days)")
    if _bad:
        raise HTTPException(
            status_code=400,
            detail=(f"Present Days cannot be more than {month_days} days for "
                    f"{run.get('month')}: " + ", ".join(_bad[:10])
                    + ("…" if len(_bad) > 10 else "")))
    # Sanity: the incoming rows must match the run's employees (no adding /
    # dropping rows through this endpoint).
    existing_ids = {r.get("user_id") for r in (run.get("rows") or [])}
    incoming_ids = {r.get("user_id") for r in rows}
    if incoming_ids != existing_ids:
        raise HTTPException(status_code=400, detail="Row set does not match this run — reload and retry.")

    updates: Dict[str, Any] = {
        "rows": rows,
        "draft_saved_at": now_iso(),
        "draft_saved_by": admin["user_id"],
    }
    totals = payload.get("totals")
    if isinstance(totals, dict) and totals:
        updates["totals"] = totals
    await db.compliance_salary_runs.update_one({"run_id": run_id}, {"$set": updates})
    # Iter 757 (user request) — every draft save keeps its own VERSION so
    # 4 saves show as 4 separate corrections in the History.
    await _snapshot_run_version(run, admin, "draft", rows=rows,
                                totals=updates.get("totals") or run.get("totals"))
    # Iter 182 — audit trail
    from routes.salary_audit import write_salary_audit
    await write_salary_audit(admin, "save_rows", run,
                             f"Saved draft edits for {len(rows)} rows")
    return {"ok": True, "draft_saved_at": updates["draft_saved_at"]}


@api.post("/admin/compliance-salary-runs/{run_id}/finalize")
async def finalize_compliance_salary_run(
    run_id: str,
    payload: Optional[Dict[str, Any]] = Body(None),
    authorization: Optional[str] = Header(None),
):
    """Iter 91 — Save/Finalize a compliance salary run. Marks the run as
    finalized (read-only): reprocessing is blocked until unfinalized.

    Iter 388 (Phase 3) — SALARY LOCK VALIDATION: the PF/ESIC Validation
    Engine runs automatically. ERRORS always block the lock; WARNINGS
    block unless a Super Admin locks with ``{"allow_warnings": true}``
    (user-approved override policy)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "compliance_salary:write", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if run.get("finalized"):
        return {"ok": True, "already_finalized": True,
                "finalized_at": run.get("finalized_at")}

    # Iter 388 — pre-lock validation (Phase 3).
    # Iter 423b (user directive — "Please Do Not Block in Any Case, we need
    # to provide Salary Data on high priority") — the PF/ESIC validation
    # still RUNS and its findings are stamped on the run for review, but it
    # NEVER blocks the Salary Lock anymore.
    from routes.compliance_validation import validate_compliance_run
    # Iter 648 (user bug — "Still not able to Lock") — the validator itself
    # can crash on unusual data; per the Iter 423b NON-BLOCKING policy a
    # validator failure must NEVER block the Salary Lock.
    try:
        validation = await validate_compliance_run(run)
    except Exception as _val_err:
        logger.warning("[compliance-run] lock validation crashed run=%s: %s",
                       run_id, _val_err)
        validation = {"errors_count": 0, "warnings_count": 0,
                      "employees_flagged": 0, "checked_at": now_iso(),
                      "validator_error": str(_val_err)[:300]}

    stamp = {
        "finalized": True,
        "finalized_at": now_iso(),
        "finalized_by": admin["user_id"],
        # Iter 388 — lock-time validation summary stored on the run.
        "lock_validation": {
            "errors_count": validation["errors_count"],
            "warnings_count": validation["warnings_count"],
            "employees_flagged": validation["employees_flagged"],
            # Iter 423b — lock proceeded despite findings (non-blocking policy).
            "warnings_overridden": validation["warnings_count"] > 0,
            "errors_overridden": validation["errors_count"] > 0,
            "non_blocking_policy": True,
            "checked_at": validation["checked_at"],
        },
    }
    await db.compliance_salary_runs.update_one({"run_id": run_id}, {"$set": stamp})
    # Iter 757 (user request) — the finalized sheet is versioned too, so the
    # LAST LOCKED data is always available in History after any reprocess.
    await _snapshot_run_version({**run, **stamp}, admin, "finalize")
    logger.info("[compliance-run] finalized run=%s by %s", run_id, admin["user_id"])
    # Iter 666 — notification layer (never blocks the lock).
    try:
        from utils.notify import emit as _notify
        await _notify(db, title="Salary Locked",
                      message=(f"{run.get('month')} salary run "
                               f"({run.get('employee_type') or 'All Groups'}) has been "
                               f"finalized & locked."),
                      audience="admins", company_id=run.get("company_id"),
                      category="salary", priority="important",
                      actor_name=admin.get("name") or admin.get("email"),
                      action_url=f"/compliance-salary-run?run_id={run_id}",
                      reference_id=run_id)
    except Exception:
        pass
    # Iter 388 (Phase 4) — append-only monthly statutory snapshot.
    try:
        from routes.compliance_validation import write_monthly_snapshot
        await write_monthly_snapshot(run, admin, stamp["lock_validation"])
    except Exception as _snap_err:  # snapshot must never block the lock
        logger.warning("[compliance-run] snapshot failed run=%s: %s", run_id, _snap_err)
    # Iter 182 — audit trail (must never block the lock — Iter 648).
    try:
        from routes.salary_audit import write_salary_audit
        await write_salary_audit(
            admin, "finalize", run,
            "Run finalized (locked)"
            + (f" — {validation['errors_count']} error(s), "
               f"{validation['warnings_count']} warning(s) noted (non-blocking policy)"
               if (validation["errors_count"] or validation["warnings_count"]) else ""))
    except Exception as _aud_err:
        logger.warning("[compliance-run] finalize audit failed run=%s: %s",
                       run_id, _aud_err)
    # Iter 103 — automated email trigger
    try:
        from routes.email_notifications import fire_email_event
        await fire_email_event("salary_finalized", company_id=run.get("company_id"),
                               details=f"Compliance Salary {run.get('month')}")
    except Exception:
        pass
    return {"ok": True, **stamp}


@api.post("/admin/compliance-salary-runs/{run_id}/unlock-request")
async def request_compliance_run_unlock(
    run_id: str,
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """Iter 126h — a FINALIZED run is locked for everyone. Sub admins /
    employers must raise an unlock request that the Super Admin approves
    before any change is possible. Super admin unlock is immediate."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "compliance_salary:write", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if not run.get("finalized"):
        return {"ok": True, "already_unlocked": True}
    reason = (payload.get("reason") or "").strip()
    # Iter 371 (user request) — Sub Admins (S.K. Sharma staff) unlock
    # IMMEDIATELY like the Super Admin; only employer company admins go
    # through the approval-request flow.
    if admin["role"] in ("super_admin", "sub_admin"):
        await db.compliance_salary_runs.update_one(
            {"run_id": run_id},
            {"$set": {
                "finalized": False,
                "unlocked_at": now_iso(),
                "unlocked_by": admin["user_id"],
                "unlock_reason": reason or f"{admin['role']} unlock",
            }},
        )
        logger.info("[compliance-run] unlocked run=%s by %s %s",
                    run_id, admin["role"], admin["user_id"])
        return {"ok": True, "unlocked": True}
    dup = await db.salary_unlock_requests.find_one(
        {"run_id": run_id, "status": "pending"}, {"_id": 0, "req_id": 1})
    if dup:
        return {"ok": True, "pending": True, "req_id": dup["req_id"],
                "message": "An unlock request is already pending approval."}
    req = {
        "req_id": f"sur_{uuid.uuid4().hex[:12]}",
        "run_id": run_id,
        "run_type": "compliance",
        "company_id": run.get("company_id"),
        "month": run.get("month"),
        "reason": reason,
        "requested_by": admin["user_id"],
        "requested_by_name": admin.get("name") or admin.get("email") or "",
        "requested_by_role": admin["role"],
        "status": "pending",
        "created_at": now_iso(),
    }
    await db.salary_unlock_requests.insert_one(req)
    req.pop("_id", None)
    return {"ok": True, "pending": True, "req_id": req["req_id"],
            "message": "Unlock request sent to the Super Admin for approval."}


@api.get("/admin/salary-unlock-requests")
async def list_salary_unlock_requests(
    status: Optional[str] = None,
    run_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 126h — pending finalized-salary unlock requests. Super admin
    sees all; requesters see their own (to show 'pending' state)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if run_id:
        q["run_id"] = run_id
    if admin["role"] != "super_admin":
        q["requested_by"] = admin["user_id"]
    rows = await db.salary_unlock_requests.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(200)
    return {"requests": rows}


@api.post("/admin/salary-unlock-requests/{req_id}/decide")
async def decide_salary_unlock_request(
    req_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Iter 126h — Super Admin (only) approves/rejects an unlock request.
    Approval unfinalizes the run so changes become possible again."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    req = await db.salary_unlock_requests.find_one({"req_id": req_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Unlock request not found")
    if req.get("status") != "pending":
        raise HTTPException(status_code=409, detail="Request already decided")
    approve = bool(payload.get("approve"))
    note = (payload.get("note") or "").strip()
    await db.salary_unlock_requests.update_one(
        {"req_id": req_id},
        {"$set": {
            "status": "approved" if approve else "rejected",
            "decided_by": admin["user_id"],
            "decided_at": now_iso(),
            "decision_note": note,
        }},
    )
    if approve:
        await db.compliance_salary_runs.update_one(
            {"run_id": req["run_id"]},
            {"$set": {
                "finalized": False,
                "unlocked_at": now_iso(),
                "unlocked_by": admin["user_id"],
                "unlock_reason": req.get("reason") or "Approved unlock request",
            }},
        )
        logger.info("[compliance-run] unlock APPROVED run=%s req=%s", req["run_id"], req_id)
        # Iter 182 — audit trail
        from routes.salary_audit import write_salary_audit
        run_doc = await db.compliance_salary_runs.find_one(
            {"run_id": req["run_id"]}, {"_id": 0, "run_id": 1, "company_id": 1,
                                        "company_name": 1, "month": 1})
        await write_salary_audit(admin, "unlock", run_doc or {"run_id": req["run_id"]},
                                 f"Unlock approved — {note or 'no note'}")
    return {"ok": True, "approved": approve}


@api.post("/admin/compliance-salary-runs/{run_id}/reprocess")
async def reprocess_compliance_salary_run(
    run_id: str,
    body: Optional[Dict[str, Any]] = Body(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:write", db)
    existing = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and existing.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if existing.get("finalized"):
        raise HTTPException(
            status_code=409,
            detail="Run is finalized and read-only. Unfinalize it first to reprocess.",
        )
    # Iter 98 — Firm Master gate: Online Salary must be enabled for the firm.
    await _require_firm_salary_permission(existing.get("company_id"), "online")

    # Iter 409 — tolerate a missing/partial body: fields not supplied fall
    # back to the run's existing values (previously a body without `month`
    # was rejected with a 422 by Pydantic before reaching this handler).
    body = body or {}
    payload = ComplianceSalaryRunCreate(
        month=body.get("month") or existing["month"],
        company_id=body.get("company_id", existing.get("company_id")),
        month_days=body.get("month_days", existing.get("month_days")),
        employee_type=body.get("employee_type", existing.get("employee_type")),
        is_onroll=body.get("is_onroll", existing.get("is_onroll_filter")),
        structure_pct=body.get("structure_pct", existing.get("structure_pct")),
        statutory_cfg=body.get("statutory_cfg", existing.get("statutory_cfg")),
        use_imported_sheet=bool(body.get("use_imported_sheet", False)),
        copy_last_month=bool(body.get("copy_last_month", False)),
    )
    # Iter 485 — reprocess NEVER creates the master snapshot (spec): it
    # uses the existing one; a legacy month without a snapshot keeps the
    # old live-master behaviour until its next Generate.
    # Iter 757 (user bug — "reprocess shows the FIRST imported sheet"):
    # this endpoint used to recompute WITHOUT the previous rows, so every
    # manual correction saved on the sheet was silently discarded. The
    # existing rows now feed the NON-DESTRUCTIVE reprocess machinery
    # (Iter 297/343b/723) exactly like the Salary Process path; a body
    # with {"fresh": true} still rebuilds from scratch.
    _prev_rows_757: Dict[str, dict] = (
        {} if bool(body.get("fresh")) else
        {r.get("user_id"): r for r in (existing.get("rows") or [])
         if r.get("user_id")})
    # The current state is snapshotted BEFORE the rebuild so nothing is
    # ever lost (visible in the sheet History).
    await _snapshot_run_version(existing, admin, "pre_reprocess")
    run = await _compute_compliance_run(admin, payload,
                                        prev_rows=_prev_rows_757,
                                        allow_snapshot_create=False)
    run["run_id"] = run_id
    run["reprocessed_from_at"] = existing.get("generated_at")
    # Advance Management — re-apply (idempotent) advance deductions so the
    # reprocessed sheet still shows the recovery lines.
    from routes.advances import apply_advance_recovery
    # Iter 443 — Master-linked ADVANCE gate (same as the process endpoint).
    _adv_rows = [r for r in run["rows"]
                 if r.get("enabled_deductions") is None
                 or "advance" in r["enabled_deductions"]]
    _adv_total = await apply_advance_recovery(
        existing.get("company_id"), existing["month"], "compliance", run_id, _adv_rows)
    if _adv_total or any(r.get("advance_recovery") for r in run["rows"]):
        t = run.get("totals") or {}
        t["advance_recovery"] = round(sum(float(r.get("advance_recovery") or 0) for r in run["rows"]), 2)
        t["total_deduction"] = round(sum(float(r.get("total_deduction") or 0) for r in run["rows"]), 2)
        t["net"] = round(sum(float(r.get("net") or 0) for r in run["rows"]), 2)
        run["totals"] = t
    await db.compliance_salary_runs.replace_one({"run_id": run_id}, run)
    return {"ok": True, "run": {k: v for k, v in run.items() if k != "_id"}}


@api.post("/admin/compliance-salary-runs/{run_id}/refresh-master-snapshot")
async def refresh_master_snapshot_endpoint(
    run_id: str,
    request: Request,
    body: Optional[Dict[str, Any]] = Body(None),
    authorization: Optional[str] = Header(None),
):
    """Iter 485 — SUPER ADMIN / SUB SUPER ADMIN ONLY escape hatch: replace
    the frozen payroll snapshot with the CURRENT Employee Master (new
    version — the previous version is kept forever), then reprocess the run
    on the new values."""
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin"):
        raise HTTPException(
            status_code=403,
            detail="Only a Super Admin / Sub Super Admin can refresh the master snapshot.")
    existing = await db.compliance_salary_runs.find_one(
        {"run_id": run_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if existing.get("finalized"):
        raise HTTPException(
            status_code=409,
            detail="Run is finalized and read-only. Unlock it first.")
    _cid = existing.get("company_id")
    if not _cid:
        raise HTTPException(status_code=400,
                            detail="Run has no firm scope — snapshot not applicable.")
    body = body or {}
    reason = (body.get("reason") or "").strip() or None
    run_type = (existing.get("run_type") or "compliance").lower()

    # Live employees for the same scope (mirrors the compute's own query).
    from utils.master_snapshot import refresh_master_snapshot as _refresh
    q: Dict[str, Any] = {"role": "employee", "company_id": _cid}
    _et = (existing.get("employee_type") or "").strip()
    if _et and _et.lower() != "all":
        q["employee_type"] = {"$in": [_et.title(), _et, _et.lower(), _et.upper()]}
    live = await db.users.find(q, {"_id": 0}).to_list(5000)
    live = [e for e in live if not _month_is_before_doj(e, existing["month"])
            and not _month_is_after_exit(e, existing["month"])
            and e.get("disabled") is not True]
    res = await _refresh(db, _cid, existing["month"], run_type,
                         existing.get("employee_type"), live, admin, reason)

    # Full audit trail (who / when / why / from where).
    from routes.salary_audit import write_salary_audit
    await write_salary_audit(
        admin, "refresh_master_snapshot", existing,
        f"Snapshot v{res['old_version']} → v{res['new_version']} "
        f"({res['employees']} employees){' — ' + reason if reason else ''}",
        extra={"ip": (request.client.host if request.client else None),
               "user_agent": request.headers.get("user-agent", "")[:160],
               "reason": reason,
               "old_version": res["old_version"],
               "new_version": res["new_version"]})

    # Reprocess the run so the sheet reflects the refreshed master.
    payload = ComplianceSalaryRunCreate(
        month=existing["month"],
        company_id=_cid,
        month_days=existing.get("month_days"),
        employee_type=existing.get("employee_type"),
        structure_pct=existing.get("structure_pct"),
        statutory_cfg=existing.get("statutory_cfg"),
    )
    # Iter 603 (user bug) — "Refresh Master" was wiping the entered days.
    # Iter 763 (user bug — "refresh master data revise nahi ho raha /
    # calculation bigad rahi hai"): passing the FULL old rows let the
    # non-destructive preserve machinery restore OLD money figures
    # (computed on the OLD rates) over the fresh calculation — rates
    # looked "not revised" and sheets went inconsistent. Refresh Master
    # now keeps ONLY the entered attendance days (and day/OT-hour edits);
    # every rupee figure is recomputed fresh from the NEW master.
    _DAY_KEYS_763 = ("present_days", "compliance_days", "half_days",
                     "week_off_days", "paid_leave_days", "ot_hours")

    def _slim_prev_763(r: dict) -> dict:
        mf = [str(x) for x in (r.get("manual_fields") or [])
              if str(x) in ("present_days", "ot_hours")]
        keep: Dict[str, Any] = {
            "user_id": r.get("user_id"),
            "employee_code": r.get("employee_code"),
            "manual_fields": mf,
            "days_hand_edited": r.get("days_hand_edited"),
        }
        for k in _DAY_KEYS_763:
            if r.get(k) is not None:
                keep[k] = r.get(k)
        return keep

    _prev_rows = {r.get("user_id"): _slim_prev_763(r)
                  for r in (existing.get("rows") or []) if r.get("user_id")}
    # Safety net — the pre-refresh sheet is versioned (restorable from
    # Past Salary Runs → History).
    await _snapshot_run_version(existing, admin, "pre_reprocess")
    run = await _compute_compliance_run(admin, payload,
                                        prev_rows=_prev_rows,
                                        allow_snapshot_create=False)
    run["run_id"] = run_id
    run["reprocessed_from_at"] = existing.get("generated_at")
    from routes.advances import apply_advance_recovery as _adv_fn
    _adv_rows = [r for r in run["rows"]
                 if r.get("enabled_deductions") is None
                 or "advance" in r["enabled_deductions"]]
    await _adv_fn(_cid, existing["month"], "compliance", run_id, _adv_rows)
    await db.compliance_salary_runs.replace_one({"run_id": run_id}, run)
    return {"ok": True, "snapshot": res,
            "run": {k: v for k, v in run.items() if k != "_id"}}


@api.get("/admin/compliance-salary-runs/{run_id}/master-snapshot-info")
async def get_master_snapshot_info(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """Iter 485 — snapshot status badge for the grid header."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    run = await db.compliance_salary_runs.find_one(
        {"run_id": run_id},
        {"_id": 0, "company_id": 1, "month": 1, "employee_type": 1,
         "run_type": 1})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised")
    from utils.master_snapshot import snapshot_scope_key
    if not run.get("company_id"):
        return {"exists": False}
    key = snapshot_scope_key(run["company_id"], run["month"],
                             (run.get("run_type") or "compliance"),
                             run.get("employee_type"))
    cur = await db.compliance_master_snapshots.find_one(
        {**key, "active": True},
        {"_id": 0, "version": 1, "created_at": 1, "created_by_name": 1,
         "source": 1},
        sort=[("version", -1)])
    if not cur:
        return {"exists": False}
    count = await db.compliance_master_snapshots.count_documents(
        {**key, "active": True})
    return {"exists": True, "version": cur.get("version"),
            "created_at": cur.get("created_at"),
            "created_by": cur.get("created_by_name"),
            "source": cur.get("source"), "employees": count}


async def _ensure_firm_head_masks(run: dict) -> dict:
    """Iter 378 (user request) — OLD runs (saved before the head masks were
    stamped on rows, incl. Copy-Last-Month / legacy imports) get the LIVE
    Firm Master Allowance/Deduction masks stamped at EXPORT time, so the
    PDF / Excel / CSV registers match the on-screen grid and the current
    Firm Master settings."""
    rows = run.get("rows") or []
    if not rows:
        return run
    r0 = rows[0]
    if r0.get("enabled_allowances") is not None \
            and r0.get("enabled_deductions") is not None:
        return run
    fm = await db.firm_masters.find_one(
        {"company_id": run.get("company_id")},
        {"_id": 0, "allowances": 1, "deductions": 1, "epf": 1, "esi": 1})
    if not fm:
        return run
    _fm_allow = fm.get("allowances") or {}
    _fm_ded = fm.get("deductions") or {}
    _amap = {"HRA": "hra", "CONV.": "conveyance",
             "MEDICAL ALLOWANCES": "medical", "OTH. ALLOW.": "special",
             "OTHER MISC.ALLOWANCE": "others",
             # Iter 644 — OVER TIME toggle drives the OT columns.
             "OVER TIME": "ot"}
    allow_mask = (sorted({h for lbl, h in _amap.items()
                          if _fm_allow.get(lbl)} | {"basic"})
                  if _fm_allow else None)
    _epf_ap = (fm.get("epf") or {}).get("applicable")
    _esi_ap = (fm.get("esi") or {}).get("applicable")
    ded_configured = (any(bool(v) for v in _fm_ded.values())
                      or _epf_ap is not None or _esi_ap is not None)
    ded_mask: Optional[list] = None
    if ded_configured:
        dm = set()
        if (_epf_ap if _epf_ap is not None else _fm_ded.get("PF")):
            dm.add("pf")
        if (_esi_ap if _esi_ap is not None else _fm_ded.get("ESI")):
            dm.add("esi")
        if _fm_ded.get("PT"):
            dm.add("pt")
        if _fm_ded.get("TDS") or _fm_ded.get("I. TAX"):
            dm.add("tds")
        # Iter 443 — Master-linked ADVANCE / OTH. DEDUC. columns.
        if _fm_ded.get("ADVANCE"):
            dm.add("advance")
        if _fm_ded.get("OTH. DEDUC."):
            dm.add("other")
        ded_mask = sorted(dm)
    for r in rows:
        if allow_mask is not None and r.get("enabled_allowances") is None:
            r["enabled_allowances"] = allow_mask
        if ded_mask is not None and r.get("enabled_deductions") is None:
            r["enabled_deductions"] = ded_mask
    return run


@api.get("/admin/compliance-salary-runs/{run_id}/export.csv")
async def export_compliance_salary_run_csv(
    run_id: str,
    sort_by: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    from utils.compliance_salary import to_csv
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    run = await _ensure_firm_head_masks(run)
    csv_str = to_csv(_sort_export_rows(run.get("rows") or [], sort_by))
    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="ComplianceSalary_{run.get("month")}_{run_id}.csv"',
        },
    )


@api.get("/admin/compliance-salary-runs/{run_id}/export.xlsx")
async def export_compliance_salary_run_xlsx(
    run_id: str,
    sort_by: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 64 — native Excel export for Compliance Salary runs."""
    from utils.compliance_salary import (
        dynamic_csv_columns, flatten_deduction_heads, round_export_rows,
    )
    from utils.report_xlsx import build_rows_xlsx
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    run = await _ensure_firm_head_masks(run)
    company_name = "S.K. Sharma & Co."
    if run.get("company_id"):
        c = await db.companies.find_one(
            {"company_id": run["company_id"]}, {"_id": 0, "name": 1}
        )
        if c and c.get("name"):
            company_name = c["name"]
    xlsx_bytes = build_rows_xlsx(
        # Iter 373 (user request) — dynamic firm-wise heads (matches PDF).
        columns=dynamic_csv_columns(run.get("rows") or []),
        rows=flatten_deduction_heads(round_export_rows(
            _sort_export_rows(run.get("rows") or [], sort_by))),
        sheet_name="Compliance",
        title=f"Compliance Salary — {company_name}",
        subtitle=f"Month: {run.get('month')} · Employees: {len(run.get('rows') or [])}",
    )
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="ComplianceSalary_{run.get("month")}_{run_id}.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/admin/compliance-salary-runs/{run_id}/register.pdf")
async def export_compliance_salary_register_pdf(
    run_id: str,
    variant: int = 1,
    sort_by: str = "",
    group_by: str = "",
    authorization: Optional[str] = Header(None),
):
    from utils.compliance_salary import (
        build_compliance_register_pdf,
        build_compliance_register_pdf_v2,
    )
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    run = await _ensure_firm_head_masks(run)

    # Iter 324 (user request) — SORTING + GROUPING on the register PDF.
    sort_by = str(sort_by or "").strip().lower()
    group_by = str(group_by or "").strip().lower()
    if sort_by not in ("", "name", "code", "designation", "department"):
        sort_by = ""
    if group_by not in ("", "employee_group", "department", "designation"):
        group_by = ""
    _rows = list(run.get("rows") or [])
    if sort_by or group_by:
        # Enrich rows with department / employee group from the Employee
        # Master (older runs may not carry these fields on the row).
        _uids = [r.get("user_id") for r in _rows if r.get("user_id")]
        _umap = {u["user_id"]: u async for u in db.users.find(
            {"user_id": {"$in": _uids}},
            {"_id": 0, "user_id": 1, "employee_code": 1, "department": 1,
             "employee_group": 1, "employee_type": 1, "designation": 1})}
        for r in _rows:
            u = _umap.get(r.get("user_id")) or {}
            r.setdefault("department", u.get("department") or "")
            r.setdefault("employee_code", u.get("employee_code") or "")
            if not r.get("employee_group"):
                r["employee_group"] = (u.get("employee_group")
                                       or u.get("employee_type") or "")

        def _code_key(r):
            c = str(r.get("employee_code") or "").strip()
            try:
                return (0, float(c), "")
            except ValueError:
                return (1, 0.0, c.upper())

        def _sort_key(r):
            if sort_by == "code":
                return _code_key(r)
            if sort_by == "designation":
                return (str(r.get("designation") or "").upper(), str(r.get("name") or "").upper())
            if sort_by == "department":
                return (str(r.get("department") or "").upper(), str(r.get("name") or "").upper())
            return (str(r.get("name") or "").upper(),)

        def _grp_val(r):
            if group_by == "employee_group":
                return str(r.get("employee_group") or "No Group").upper()
            if group_by == "department":
                return str(r.get("department") or "No Department").upper()
            if group_by == "designation":
                return str(r.get("designation") or "No Designation").upper()
            return ""

        if group_by:
            _rows.sort(key=lambda r: (_grp_val(r),) + tuple(_sort_key(r)))
        elif sort_by:
            _rows.sort(key=_sort_key)
        run = {**run, "rows": _rows}

    company_name = "S.K. Sharma & Co."
    firm_info: Dict[str, Any] = {}
    if run.get("company_id"):
        c = await db.companies.find_one(
            {"company_id": run["company_id"]}, {"_id": 0, "name": 1, "address": 1},
        )
        if c and c.get("name"):
            company_name = c["name"]
        fm = await db.firm_masters.find_one(
            {"company_id": run["company_id"]},
            {"_id": 0, "epf": 1, "esi": 1, "registered_address": 1},
        )
        # Iter 137 (user directive) — the register shows the firm's
        # REGISTERED address from the Firm Master, NOT the geofence
        # office address. Falls back to the company address only when
        # no registered address has been filled in.
        ra = (fm or {}).get("registered_address") or {}
        reg_addr = ", ".join(str(x).strip() for x in [
            ra.get("address1"), ra.get("address2"), ra.get("city"),
            ra.get("state"), ra.get("pin_code"),
        ] if x and str(x).strip())
        firm_info["address"] = reg_addr or ((c or {}).get("address") or "")
        firm_info["pf_code"] = ((fm or {}).get("epf") or {}).get("epf_no") or ""
        firm_info["esi_code"] = ((fm or {}).get("esi") or {}).get("esi_no") or ""
    builder = build_compliance_register_pdf_v2 if int(variant or 1) == 2 else build_compliance_register_pdf
    # Iter 306 (user #10) — saved title override from the Report Formats editor.
    from routes.report_formats import get_report_format
    _fmt_id = "compliance_register_v2" if int(variant or 1) == 2 else "compliance_register_v1"
    _title_ov = str((await get_report_format(_fmt_id)).get("title") or "").strip()
    if int(variant or 1) == 2:
        # Iter 162 — apply the ONE-TIME saved register layout (columns /
        # order / headings / widths / rows-per-page / row height).
        _lay = await db.app_settings.find_one(
            {"key": "compliance_register_layout"}, {"_id": 0, "layout": 1})
        pdf_bytes = builder(run, company_name=company_name, firm=firm_info,
                            layout=(_lay or {}).get("layout"), title_override=_title_ov,
                            group_by=group_by)
    else:
        pdf_bytes = builder(run, company_name=company_name, firm=firm_info,
                            title_override=_title_ov, group_by=group_by)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="ComplianceSalaryRegister_{run.get("month")}_{run_id}.pdf"',
            "Cache-Control": "no-store",
        },
    )


async def _compliance_report_attachments(run: Dict[str, Any],
                                         formats: List[str]):
    """Iter 438 (user request) — build PDF/Excel/CSV report files for a
    compliance run (same builders as the download endpoints)."""
    from utils.compliance_salary import (
        build_compliance_register_pdf, dynamic_csv_columns,
        flatten_deduction_heads, to_csv,
    )
    from utils.report_xlsx import build_rows_xlsx
    month = run.get("month") or ""
    company_name = "S.K. Sharma & Co."
    firm_info: Dict[str, Any] = {}
    if run.get("company_id"):
        c = await db.companies.find_one(
            {"company_id": run["company_id"]}, {"_id": 0, "name": 1, "address": 1})
        if c and c.get("name"):
            company_name = c["name"]
        fm = await db.firm_masters.find_one(
            {"company_id": run["company_id"]},
            {"_id": 0, "epf": 1, "esi": 1, "registered_address": 1})
        ra = (fm or {}).get("registered_address") or {}
        reg_addr = ", ".join(str(x).strip() for x in [
            ra.get("address1"), ra.get("address2"), ra.get("city"),
            ra.get("state"), ra.get("pin_code")] if x and str(x).strip())
        firm_info["address"] = reg_addr or ((c or {}).get("address") or "")
        firm_info["pf_code"] = ((fm or {}).get("epf") or {}).get("epf_no") or ""
        firm_info["esi_code"] = ((fm or {}).get("esi") or {}).get("esi_no") or ""
    out = []
    if "pdf" in formats or "pdf2" in formats:
        from routes.report_formats import get_report_format
        if "pdf" in formats:
            _title_ov = str((await get_report_format("compliance_register_v1")).get("title") or "").strip()
            out.append({"filename": f"ComplianceSalaryRegister_{month}.pdf",
                        "content": build_compliance_register_pdf(
                            run, company_name=company_name, firm=firm_info,
                            title_override=_title_ov),
                        "mime": "application/pdf"})
        if "pdf2" in formats:
            # Iter 439 (user request) — PDF Format 2 (Option 2 register).
            from utils.compliance_salary import build_compliance_register_pdf_v2
            _title_ov2 = str((await get_report_format("compliance_register_v2")).get("title") or "").strip()
            _lay = await db.app_settings.find_one(
                {"key": "compliance_register_layout"}, {"_id": 0, "layout": 1})
            out.append({"filename": f"ComplianceSalaryRegister_Format2_{month}.pdf",
                        "content": build_compliance_register_pdf_v2(
                            run, company_name=company_name, firm=firm_info,
                            layout=(_lay or {}).get("layout"),
                            title_override=_title_ov2),
                        "mime": "application/pdf"})
    if "xlsx" in formats:
        out.append({"filename": f"ComplianceSalary_{month}.xlsx",
                    "content": build_rows_xlsx(
                        columns=dynamic_csv_columns(run.get("rows") or []),
                        rows=flatten_deduction_heads(run.get("rows") or []),
                        sheet_name="Compliance",
                        title=f"Compliance Salary — {company_name}",
                        subtitle=f"Month: {month} · Employees: {len(run.get('rows') or [])}"),
                    "mime": "application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet"})
    if "csv" in formats:
        out.append({"filename": f"ComplianceSalary_{month}.csv",
                    "content": to_csv(run.get("rows") or []).encode("utf-8"),
                    "mime": "text/csv"})
    return out, company_name


@api.post("/admin/compliance-salary-runs/{run_id}/email-report")
async def email_compliance_run_report(
    run_id: str,
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """Iter 438 (user request) — after Save / Finalize the admin can MAIL
    the run's reports (PDF / Excel / CSV / All) to any email address."""
    from utils.report_email import normalize_formats, send_report_email
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    run = await _ensure_firm_head_masks(run)
    # Iter 439/440 (user request) — PDF Format 1 & 2; ≥1 format MANDATORY;
    # the mail carries EXACTLY the selected formats.
    formats = normalize_formats(payload.get("formats"),
                                allowed=("pdf", "pdf2", "xlsx", "csv"))
    to = payload.get("to") or admin.get("email") or ""
    attachments, company_name = await _compliance_report_attachments(run, formats)
    month = run.get("month") or ""
    status = "FINALIZED" if run.get("finalized") else "Draft"
    _fmt_labels = {"pdf": "PDF Format 1", "pdf2": "PDF Format 2",
                   "xlsx": "Excel", "csv": "CSV"}
    fmt_txt = ", ".join(_fmt_labels.get(f, f.upper()) for f in formats)
    grp = str(run.get("employee_type") or "").strip() or "All Groups"
    res = await send_report_email(
        to,
        f"Compliance Salary Report — {company_name} ({month})",
        (f"Please find attached the Compliance Salary report(s) for "
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


@api.get("/admin/compliance-salary-runs/{run_id}/pf-ecr.txt")
async def download_pf_ecr(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """PF ECR (Electronic Challan cum Return) text file for one month.

    Layout (hash-separated, no header): ``UAN#NAME#GROSS#EPF_WAGES#
    EPS_WAGES#EDLI_WAGES#EPF_CONTRIB#EPS_CONTRIB#EPF_EPS_DIFF#NCP#REFUND``.
    Uploaded on the EPFO Unified Portal ▸ ECR & Return.
    """
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    rows = run.get("rows") or run.get("lines") or []
    # Enrich with user master fields (UAN) if not already on the row.
    uids = [r.get("user_id") for r in rows if r.get("user_id") and not r.get("uan_no")]
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "uan_no": 1},
        ):
            for r in rows:
                if r.get("user_id") == u["user_id"]:
                    r["uan_no"] = u.get("uan_no")
    # Iter 733 (user-approved audit Bug 1) — use the CORRECT Challans
    # builder (uncapped EPF wages for Higher PF, EPS/EDLI capped,
    # portal-style dues); the old capped builder broke Higher-PF members.
    from routes.challans import _uan_esic_map, _ecr_txt_bytes
    _extra733 = await _uan_esic_map(rows)
    body = _ecr_txt_bytes(run, _extra733, False)
    # Iter 446 (user bug) — EPFO rejects filenames with non-word characters.
    _m = str(run.get("month") or "")
    _mword = f"{_m[5:7]}{_m[:4]}" if len(_m) == 7 and _m[4] == "-" else "month"
    fname = f"PF_ECR_{_mword}.txt"
    return Response(
        content=body,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/admin/compliance-salary-runs/{run_id}/esic-mc.csv")
async def download_esic_mc(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """ESIC Monthly Contribution CSV for the ESIC Insurance Portal."""
    from fastapi.responses import Response
    from utils.statutory_bulk import build_esic_mc_csv
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    rows = run.get("rows") or run.get("lines") or []
    uids = [r.get("user_id") for r in rows if r.get("user_id") and not r.get("esi_ip_no")]
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "esi_ip_no": 1},
        ):
            for r in rows:
                if r.get("user_id") == u["user_id"]:
                    r["esi_ip_no"] = u.get("esi_ip_no")
    body = build_esic_mc_csv(rows)
    fname = f"ESIC_MC_{run.get('month')}.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/admin/compliance-salary-runs/{run_id}/esic-ip-reg.csv")
async def download_esic_ip_reg(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """ESIC Insured-Person Registration CSV (only new joiners).

    Includes only employees that DO NOT yet have an ``esi_ip_no`` in
    the master.  Once the portal returns an IP number for each row the
    operator should update the employee master so the row falls off
    subsequent monthly files.
    """
    from fastapi.responses import Response
    from utils.statutory_bulk import build_esic_ip_reg_csv
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    rows = run.get("rows") or run.get("lines") or []
    # Enrich with the full employee master so we have DOB, addresses, PAN…
    uids = [r.get("user_id") for r in rows if r.get("user_id")]
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "esi_ip_no": 1, "dob": 1, "doj": 1,
             "gender": 1, "father_name": 1, "aadhaar_no": 1, "pan_no": 1,
             "phone": 1, "address": 1, "permanent_address": 1,
             "bank_ifsc": 1, "marital_status": 1},
        ):
            for r in rows:
                if r.get("user_id") == u["user_id"]:
                    for k, v in u.items():
                        r.setdefault(k, v)
    body = build_esic_ip_reg_csv(rows)
    fname = f"ESIC_IP_Registration_{run.get('month')}.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
        },
    )


@api.post("/admin/compliance-salary-runs/{run_id}/generate-payslips")
async def generate_compliance_payslips_from_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """Push a compliance run into per-employee compliance-payslip records.
    Stored separately (kind='compliance') so the base + compliance payslips
    don't collide."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "compliance_salary:write", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    month = run["month"]
    created = 0
    skipped_pre_doj = 0
    for r in (run.get("rows") or []):
        uid = r.get("user_id")
        if not uid:
            continue
        # Iter 57 — never generate a compliance payslip for a month before DOJ.
        emp = await db.users.find_one({"user_id": uid}, {"_id": 0, "doj": 1})
        if emp and _month_is_before_doj(emp, month):
            skipped_pre_doj += 1
            continue
        # Replace existing compliance slip for this employee+month
        await db.payslips.delete_many({
            "employee_user_id": uid, "month": month, "kind": "compliance",
        })
        slip = {
            "slip_id": f"cslp_{uuid.uuid4().hex[:12]}",
            "kind": "compliance",
            "employee_user_id": uid,
            "company_id": r.get("company_id") or run.get("company_id"),
            "month": month,
            "gross": r.get("gross_paid", 0.0),
            "deductions": r.get("total_deduction", 0.0),
            "net": r.get("net", 0.0),
            "status": "paid",
            "generated_by": admin["user_id"],
            "generated_at": now_iso(),
            "compliance_salary_run_id": run_id,
            "breakup": {
                "basic": r.get("basic"),
                "hra": r.get("hra"),
                "conveyance": r.get("conveyance"),
                "medical": r.get("medical"),
                "special": r.get("special"),
                "others": r.get("others"),
                "ot_pay": r.get("ot_pay"),
                "stat_wage_base": r.get("stat_wage_base"),
                "pf_wages": r.get("pf_wages"),
                "pf_employee": r.get("pf_employee"),
                "pf_employer_total": r.get("pf_employer_total"),
                "esic_wage_base": r.get("esic_wage_base"),
                "esic_employee": r.get("esic_employee"),
                "esic_employer": r.get("esic_employer"),
                "pt_state": r.get("pt_state"),
                "pt": r.get("pt"),
                "tds": r.get("tds"),
                "present_days": r.get("present_days"),
                "half_days": r.get("half_days"),
                "month_days": r.get("month_days"),
            },
        }
        # Iter 500 — CTC MODE: carry the CTC annexure onto the slip.
        if r.get("ctc_mode"):
            slip["ctc_mode"] = True
            slip["breakup"]["monthly_ctc"] = r.get("monthly_ctc")
            slip["breakup"]["ctc_structure_name"] = r.get("ctc_structure_name")
            slip["breakup"]["ctc_employer_total"] = r.get("ctc_employer_total")
            slip["breakup"]["ctc_employer_contributions"] = \
                r.get("ctc_employer_contributions")
        await db.payslips.insert_one(slip)
        created += 1
        # Iter 395 — WhatsApp "salary processed" + payslip-PDF notifications
        # (only fire when the firm enabled these automations).
        try:
            from utils.whatsapp_engine import notify_event as _wa_notify
            _net = (slip.get("amounts") or {}).get("net") or slip.get("net_pay")
            await _wa_notify("salary_processed", run.get("company_id"),
                             slip.get("user_id"),
                             extra={"Month": run.get("month"),
                                    "Salary": str(_net if _net is not None else "")})
            await _wa_notify("salary_slip", run.get("company_id"),
                             slip.get("user_id"),
                             extra={"Month": run.get("month"),
                                    "Salary": str(_net if _net is not None else "")},
                             attachment={"payslip": {
                                 "company_id": run.get("company_id"),
                                 "user_id": slip.get("user_id"),
                                 "month": run.get("month")}})
        except Exception:
            pass
    await db.compliance_salary_runs.update_one(
        {"run_id": run_id},
        {"$set": {"payslips_generated_at": now_iso(), "payslips_count": created}},
    )
    return {"ok": True, "payslips_count": created, "skipped_pre_doj": skipped_pre_doj}



@api.get("/admin/compliance-salary-runs/{run_id}/ecr.txt")
async def download_ecr_file(run_id: str, authorization: Optional[str] = Header(None)):
    """Download the EPFO ECR (Electronic Challan return) text file for a
    compliance salary run. Super admin uploads this to unifiedportal-emp.epfindia.gov.in.
    Supports optional ?group_id= filter to only include employees in that
    Employee Group."""
    from utils.master_sheet import build_ecr_text
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised")
    # Iter 341 — stamp the Employee Master "EPS Disable" flag on rows
    # (works for runs generated before the flag existed too).
    _rows_e = run.get("rows") or []
    _uids_e = [r.get("user_id") for r in _rows_e if r.get("user_id")]
    if _uids_e:
        async for u in db.users.find(
            {"user_id": {"$in": _uids_e}, "eps_disabled": True},
            {"_id": 0, "user_id": 1},
        ):
            for r in _rows_e:
                if r.get("user_id") == u["user_id"]:
                    r["eps_disabled"] = True
    txt = build_ecr_text(run)
    # Iter 446 (user bug) — EPFO rejects filenames with non-word characters.
    _m2 = str(run.get("month") or "")
    _m2w = f"{_m2[5:7]}{_m2[:4]}" if len(_m2) == 7 and _m2[4] == "-" else "month"
    return Response(
        content=txt,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="ECR_{_m2w}.txt"'},
    )



# ---------------------------------------------------------------------------
# Iter 631 (user request) — DISABLE WARNING: before an admin switches OFF an
# allowance head in the Firm Master, the frontend asks this endpoint whether
# any PROCESSED month carries amounts in that head. Read-only.
# ---------------------------------------------------------------------------
_ALLOW_LABEL_TO_BUCKET = {
    "HRA": "hra", "CONV.": "conveyance", "MEDICAL ALLOWANCES": "medical",
    "OTH. ALLOW.": "special", "OTHER MISC.ALLOWANCE": "others",
}


@api.get("/admin/compliance-allowance-impact")
async def firm_allowance_impact(
    company_id: str = Query(...),
    head: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorised for this firm")
    bucket = _ALLOW_LABEL_TO_BUCKET.get(str(head or "").strip().upper())
    if not bucket:
        # Custom catalog heads are not part of the salary-column mask.
        return {"applicable": False, "months": []}
    months = await db.compliance_salary_runs.aggregate([
        {"$match": {"company_id": company_id}},
        {"$unwind": "$rows"},
        {"$match": {f"rows.{bucket}": {"$gt": 0}}},
        {"$group": {"_id": "$month",
                    "employees": {"$sum": 1},
                    "total": {"$sum": f"$rows.{bucket}"},
                    "finalized": {"$max": {"$cond": ["$finalized", 1, 0]}}}},
        {"$sort": {"_id": -1}},
        {"$limit": 24},
    ]).to_list(24)
    out = [{"month": m["_id"], "employees": m["employees"],
            "total": round(float(m["total"] or 0), 2),
            "finalized": bool(m.get("finalized"))} for m in months]
    return {"applicable": True, "bucket": bucket, "months": out,
            "total_amount": round(sum(m["total"] for m in out), 2),
            "total_employees": sum(m["employees"] for m in out)}


# ---------------------------------------------------------------------------
# Iter 633 (user request) — EXPORT THE DISPLAYED (unsaved) SHEET: the grid
# posts its CURRENT rows (including edits not yet saved as draft) and gets
# the same whole-rupee Excel back. Nothing is persisted.
# ---------------------------------------------------------------------------
class DisplayExportPayload(BaseModel):
    month: str
    company_id: Optional[str] = None
    rows: List[Dict[str, Any]] = []


@api.post("/admin/compliance-salary-runs/export-display.xlsx")
async def export_displayed_compliance_xlsx(
    payload: DisplayExportPayload,
    authorization: Optional[str] = Header(None),
):
    from utils.compliance_salary import (
        dynamic_csv_columns, flatten_deduction_heads, round_export_rows,
    )
    from utils.report_xlsx import build_rows_xlsx
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    if admin["role"] == "company_admin" and payload.company_id \
            and payload.company_id != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this firm")
    rows = payload.rows or []
    company_name = "S.K. Sharma & Co."
    if payload.company_id:
        c = await db.companies.find_one(
            {"company_id": payload.company_id}, {"_id": 0, "name": 1})
        if c and c.get("name"):
            company_name = c["name"]
    xlsx_bytes = build_rows_xlsx(
        columns=dynamic_csv_columns(rows),
        rows=flatten_deduction_heads(round_export_rows(rows)),
        sheet_name="Compliance",
        title=f"Compliance Salary (Displayed) — {company_name}",
        subtitle=(f"Month: {payload.month} · Employees: {len(rows)} · "
                  "Exported from the on-screen sheet (before save)"),
    )
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="ComplianceSalary_Displayed_{payload.month}.xlsx"',
                 "Cache-Control": "no-store"})
