"""Iter 358 — Government Registers + Audit Reports.

GOVERNMENT REGISTERS (from monthly compliance salary runs):
  wage-register, fine-register, deduction-register, advance-register,
  gratuity-register
AUDIT REPORTS (from existing audit/log collections):
  payroll-audit, attendance-audit, salary-change-history, user-activity,
  login-history, data-modification, approval-history

  GET /api/admin/govt-registers/list | /{kind}[.xlsx|.pdf]   (month param)
  GET /api/admin/audit-reports/list  | /{kind}[.xlsx|.pdf]   (limit param)
"""
from datetime import date, datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from server import db, get_user_from_token, require_role  # noqa: E402
from utils.register_export import register_pdf, register_xlsx  # noqa: E402
from routes.labour_statistics import (_dt, _f, _users, _company,  # noqa: E402
                                      _run_rows, _active)

govt_router = APIRouter(prefix="/api/admin/govt-registers",
                        tags=["govt-registers"])
audit_router = APIRouter(prefix="/api/admin/audit-reports",
                         tags=["audit-reports"])


async def _adm(authorization, company_id):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return company_id


def _srt(rows):
    rows.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
    return rows


# ---------------------------------------------------------------------------
# Government registers
# ---------------------------------------------------------------------------

async def _wage_register(company_id, month):
    rows_by_uid = await _run_rows(company_id, month)
    users = {u["user_id"]: u for u in await _users(company_id)}
    out = []
    for uid, r in rows_by_uid.items():
        u = users.get(uid) or {}
        out.append({
            "employee_code": u.get("employee_code"), "name": u.get("name"),
            "designation": u.get("designation"),
            "rate": _f(r.get("rate")), "days": _f(r.get("present_days")),
            "basic": _f(r.get("basic")), "hra": _f(r.get("hra")),
            "other_allowances": round(
                _f(r.get("conveyance")) + _f(r.get("special"))
                + _f(r.get("medical")) + _f(r.get("others")), 2),
            "overtime": _f(r.get("ot_pay")),
            "gross": _f(r.get("gross_paid")),
            "deductions": _f(r.get("total_deduction")),
            "net": _f(r.get("net"))})
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("designation", "Designation"), ("rate", "Rate of Wages"),
            ("days", "Days Worked"), ("basic", "Basic"), ("hra", "HRA"),
            ("other_allowances", "Other Allowances"),
            ("overtime", "Overtime"), ("gross", "Gross Wages"),
            ("deductions", "Deductions"), ("net", "Net Wages Paid")]
    totals = {"name": "TOTAL"}
    for k in ("basic", "hra", "other_allowances", "overtime", "gross",
              "deductions", "net"):
        totals[k] = round(sum(r[k] for r in out), 2)
    return "Wage Register (Form)", cols, _srt(out), totals


async def _amount_register(company_id, month, key_fn, label):
    rows_by_uid = await _run_rows(company_id, month)
    users = {u["user_id"]: u for u in await _users(company_id)}
    out = []
    for uid, r in rows_by_uid.items():
        amt = key_fn(r)
        if amt <= 0:
            continue
        u = users.get(uid) or {}
        out.append({"employee_code": u.get("employee_code"),
                    "name": u.get("name"),
                    "gross": _f(r.get("gross_paid")), "amount": amt,
                    "reason": "", "recovered": amt, "balance": 0})
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("gross", "Gross Wages"), ("amount", f"{label} Amount"),
            ("reason", "Reason/Remarks"), ("recovered", "Recovered"),
            ("balance", "Balance")]
    totals = {"name": "TOTAL",
              "amount": round(sum(r["amount"] for r in out), 2),
              "recovered": round(sum(r["recovered"] for r in out), 2)}
    return f"{label} Register (Form)", cols, _srt(out), totals


async def _deduction_register(company_id, month):
    rows_by_uid = await _run_rows(company_id, month)
    users = {u["user_id"]: u for u in await _users(company_id)}
    out = []
    for uid, r in rows_by_uid.items():
        u = users.get(uid) or {}
        td = _f(r.get("total_deduction"))
        if td <= 0:
            continue
        out.append({"employee_code": u.get("employee_code"),
                    "name": u.get("name"), "pf": _f(r.get("pf_employee")),
                    "esic": _f(r.get("esic_employee")), "pt": _f(r.get("pt")),
                    "tds": _f(r.get("tds")),
                    "other": _f(r.get("other_deduction")),
                    "total": td, "net": _f(r.get("net"))})
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("pf", "PF"), ("esic", "ESIC"), ("pt", "PT"), ("tds", "TDS"),
            ("other", "Other/Fines"), ("total", "Total Deduction"),
            ("net", "Net Paid")]
    totals = {"name": "TOTAL"}
    for k in ("pf", "esic", "pt", "tds", "other", "total", "net"):
        totals[k] = round(sum(r[k] for r in out), 2)
    return "Deduction Register (Form)", cols, _srt(out), totals


async def _gratuity_register(company_id, month):
    users = await _users(company_id)
    rows_by_uid = await _run_rows(company_id, month)
    today = date.today()
    out = []
    for u in users:
        if not _active(u):
            continue
        doj = _dt(u.get("doj"))
        if not doj:
            continue
        yrs = (today - doj).days / 365
        basic = _f((rows_by_uid.get(u["user_id"]) or {}).get("basic")) or \
            _f(u.get("compliance_gross") or u.get("salary_monthly")) * 0.5
        accrued = round(basic * 15 / 26 * int(yrs), 2) if yrs >= 5 else 0
        out.append({"employee_code": u.get("employee_code"),
                    "name": u.get("name"), "doj": u.get("doj"),
                    "service_years": round(yrs, 1),
                    "eligible": "Yes" if yrs >= 5 else "No",
                    "last_basic": round(basic, 2),
                    "accrued_gratuity": accrued})
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("doj", "DOJ"), ("service_years", "Service (yrs)"),
            ("eligible", "Eligible (5+ yrs)"), ("last_basic", "Basic Wages"),
            ("accrued_gratuity", "Accrued Gratuity (15/26 × yrs)")]
    totals = {"name": "TOTAL", "accrued_gratuity": round(
        sum(r["accrued_gratuity"] for r in out), 2)}
    return "Gratuity Register", cols, _srt(out), totals


_GOVT = {
    "wage-register": _wage_register,
    "fine-register": lambda c, m: _amount_register(
        c, m, lambda r: _f(r.get("fine")) + _f(r.get("other_deduction")),
        "Fine"),
    "deduction-register": _deduction_register,
    "advance-register": lambda c, m: _amount_register(
        c, m, lambda r: _f(r.get("advance")) + _f(r.get("advance_recovery")),
        "Advance"),
    "gratuity-register": _gratuity_register,
}
_GOVT_TITLES = {
    "wage-register": "Wage Register",
    "fine-register": "Fine Register",
    "deduction-register": "Deduction Register",
    "advance-register": "Advance Register",
    "gratuity-register": "Gratuity Register",
}


@govt_router.get("/list")
async def govt_list(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    return {"registers": [{"kind": k, "title": t}
                          for k, t in _GOVT_TITLES.items()]}


@govt_router.get("/{kind}")
async def govt_json(kind: str, company_id: Optional[str] = None,
                    month: Optional[str] = None,
                    authorization: Optional[str] = Header(None)):
    for ext in ("xlsx", "pdf"):
        if kind.endswith(f".{ext}"):
            return await _govt_exp(kind[: -len(ext) - 1], company_id, month,
                                   authorization, ext)
    if kind not in _GOVT:
        raise HTTPException(status_code=404, detail="Unknown register")
    company_id = await _adm(authorization, company_id)
    month = month or date.today().strftime("%Y-%m")
    title, cols, rows, totals = await _GOVT[kind](company_id, month)
    return {"title": title, "subtitle": month,
            "columns": [{"key": k, "label": lb} for k, lb in cols],
            "rows": rows, "totals": totals}


async def _govt_exp(kind, company_id, month, authorization, fmt):
    if kind not in _GOVT:
        raise HTTPException(status_code=404, detail="Unknown register")
    company_id = await _adm(authorization, company_id)
    month = month or date.today().strftime("%Y-%m")
    c = await _company(company_id)
    title, cols, rows, totals = await _GOVT[kind](company_id, month)
    return _stream(title, f"{c.get('name')} · {month}", cols, rows, totals,
                   c.get("logo_base64"), fmt)


# ---------------------------------------------------------------------------
# Audit reports — from existing audit/log collections
# ---------------------------------------------------------------------------

_AUDIT: Dict[str, dict] = {
    "payroll-audit": {"title": "Payroll Audit Trail",
                      "colls": ["salary_audit_log"]},
    "attendance-audit": {"title": "Attendance Audit Trail",
                         "colls": ["attendance_audit_log"]},
    "salary-change-history": {"title": "Salary Change History",
                              "colls": ["salary_history",
                                        "legacy_salary_history"]},
    "user-activity": {"title": "User Activity Log",
                      "colls": ["activity_log"]},
    "login-history": {"title": "Login History",
                      "colls": ["access_audit", "emp_login_attempts"]},
    "data-modification": {"title": "Data Modification Report",
                          "colls": ["employee_audit_logs", "bulk_ops_log",
                                    "company_audit_log"]},
    "approval-history": {"title": "Approval History",
                         "colls": ["onboarding_audit", "kyc_history"]},
}
_PREF_COLS = ["timestamp", "created_at", "at", "time", "date", "action",
              "event", "kind", "type", "actor", "user", "user_id", "email",
              "employee_code", "employee_name", "name", "field", "old",
              "new", "old_value", "new_value", "details", "note", "reason",
              "month", "status", "ip", "source"]


async def _audit_rows(kind: str, company_id: str, limit: int):
    meta = _AUDIT[kind]
    docs: List[dict] = []
    for coll in meta["colls"]:
        try:
            q = {"$or": [{"company_id": company_id},
                         {"company_id": {"$exists": False}}]}
            found = await db[coll].find(q, {"_id": 0}).sort(
                "$natural", -1).to_list(limit)
            for d in found:
                d["_source"] = coll
            docs += found
        except Exception:  # noqa: BLE001
            continue
    docs = docs[:limit]
    keys: List[str] = ["_source"]
    seen = set(keys)
    for pref in _PREF_COLS:
        if any(pref in d for d in docs) and pref not in seen:
            keys.append(pref)
            seen.add(pref)
    rows = []
    for d in docs:
        row = {}
        for k in keys:
            v = d.get(k)
            if isinstance(v, (dict, list)):
                v = str(v)[:120]
            row[k] = v
        rows.append(row)
    cols = [(k, k.replace("_", " ").title()) for k in keys]
    return meta["title"], cols, rows, None


@audit_router.get("/list")
async def audit_list(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    return {"reports": [{"kind": k, "title": v["title"]}
                        for k, v in _AUDIT.items()]}


@audit_router.get("/{kind}")
async def audit_json(kind: str, company_id: Optional[str] = None,
                     limit: int = 200,
                     authorization: Optional[str] = Header(None)):
    for ext in ("xlsx", "pdf"):
        if kind.endswith(f".{ext}"):
            return await _audit_exp(kind[: -len(ext) - 1], company_id, limit,
                                    authorization, ext)
    if kind not in _AUDIT:
        raise HTTPException(status_code=404, detail="Unknown report")
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    company_id = company_id or ""
    title, cols, rows, totals = await _audit_rows(
        kind, company_id, max(1, min(limit, 1000)))
    return {"title": title, "subtitle": f"latest {len(rows)} entries",
            "columns": [{"key": k, "label": lb} for k, lb in cols],
            "rows": rows, "totals": totals}


async def _audit_exp(kind, company_id, limit, authorization, fmt):
    if kind not in _AUDIT:
        raise HTTPException(status_code=404, detail="Unknown report")
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    title, cols, rows, totals = await _audit_rows(
        kind, company_id or "", max(1, min(limit, 1000)))
    return _stream(title, f"Latest {len(rows)} entries", cols, rows, totals,
                   None, fmt)


def _stream(title, sub, cols, rows, totals, logo, fmt):
    columns = [{"key": k, "label": lb} for k, lb in cols]
    sub = f"{sub} · Generated {datetime.now():%d-%m-%Y}"
    if fmt == "xlsx":
        buf = register_xlsx(title, sub, columns, rows, totals)
        mt = ("application/vnd.openxmlformats-officedocument"
              ".spreadsheetml.sheet")
    else:
        buf = register_pdf(title, sub, columns, rows, totals, logo)
        mt = "application/pdf"
    fn_ = f"{title.replace(' ', '_')}.{fmt}"
    return StreamingResponse(buf, media_type=mt, headers={
        "Content-Disposition": f'attachment; filename="{fn_}"'})
