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

from fastapi import APIRouter, Body, Header, HTTPException
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


def _mlabel(month: str) -> str:
    try:
        return datetime(int(month[:4]), int(month[5:7]), 1).strftime("%B %Y")
    except (TypeError, ValueError):
        return str(month or "")


def _months_range(month: str, month_to: str) -> List[str]:
    """Inclusive YYYY-MM list month..month_to (max 24)."""
    out = [month]
    if month_to and month_to > month:
        y, m = int(month[:4]), int(month[5:7])
        while f"{y:04d}-{m:02d}" < month_to and len(out) <= 24:
            m += 1
            if m > 12:
                m, y = 1, y + 1
            out.append(f"{y:04d}-{m:02d}")
    return out


# ---------------------------------------------------------------------------
# Government registers
# ---------------------------------------------------------------------------

async def _wage_register(company_id, month, ctx=None):
    """Iter 477 (user request) — Month-wise OR Periodic (month..month_to).
    Iter 480 (user spec — Phase 2) — statutory columns: allowances split
    (Conveyance / Medical / Special / Others), deductions split
    (PF / ESIC / PT / TDS / Other incl. advance), Bank details."""
    months = _months_range(month, (ctx or {}).get("month_to") or "")
    users = {u["user_id"]: u for u in await _users(company_id)}
    banks: Dict[str, str] = {}
    async for _b in db.users.find(
            {"company_id": company_id, "role": "employee"},
            {"_id": 0, "user_id": 1, "bank_account_no": 1, "bank_ifsc": 1}):
        if _b.get("bank_account_no"):
            banks[_b["user_id"]] = (f"{_b['bank_account_no']} / "
                                    f"{_b.get('bank_ifsc') or ''}").strip(" /")
    _SUM = ("days", "basic", "hra", "conveyance", "medical", "special",
            "others", "overtime", "gross", "pf", "esic", "pt", "tds",
            "other_ded", "deductions", "net")
    agg: Dict[str, dict] = {}
    for mo in months:
        rows_by_uid = await _run_rows(company_id, mo)
        for uid, r in rows_by_uid.items():
            u = users.get(uid) or {}
            d = agg.setdefault(uid, dict(
                {k: 0.0 for k in _SUM},
                employee_code=u.get("employee_code"), name=u.get("name"),
                designation=u.get("designation"), rate=0.0,
                bank=banks.get(uid, "")))
            d["rate"] = _f(r.get("rate")) or d["rate"]
            for k, src in (("days", "present_days"), ("basic", "basic"),
                           ("hra", "hra"), ("conveyance", "conveyance"),
                           ("medical", "medical"), ("special", "special"),
                           ("others", "others"), ("overtime", "ot_pay"),
                           ("gross", "gross_paid"), ("pf", "pf_employee"),
                           ("esic", "esic_employee"), ("pt", "pt"),
                           ("tds", "tds"), ("other_ded", "other_deduction"),
                           ("deductions", "total_deduction"),
                           ("net", "net")):
                d[k] = round(d[k] + _f(r.get(src)), 2)
    out = list(agg.values())
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("designation", "Designation"), ("rate", "Rate of Wages"),
            ("days", "Days Worked"), ("basic", "Basic"), ("hra", "HRA"),
            ("conveyance", "Conveyance"), ("medical", "Medical"),
            ("special", "Special All."), ("others", "Other All."),
            ("overtime", "Overtime"), ("gross", "Gross Wages"),
            ("pf", "PF"), ("esic", "ESIC"), ("pt", "PT"), ("tds", "TDS"),
            ("other_ded", "Adv/Other Ded."),
            ("deductions", "Total Deduction"), ("net", "Net Wages Paid"),
            ("bank", "Bank A/c / IFSC")]
    totals = {"name": "TOTAL"}
    for k in ("basic", "hra", "conveyance", "medical", "special", "others",
              "overtime", "gross", "pf", "esic", "pt", "tds", "other_ded",
              "deductions", "net"):
        totals[k] = round(sum(r[k] for r in out), 2)
    return "Wage Register (Form B)", cols, _srt(out), totals


async def _amount_register(company_id, month, key_fn, label, ctx=None):
    """Iter 433 (user request) — Month-wise OR Periodic (month..month_to)."""
    months = _months_range(month, (ctx or {}).get("month_to") or "")
    users = {u["user_id"]: u for u in await _users(company_id)}
    agg: Dict[str, dict] = {}
    for mo in months:
        rows_by_uid = await _run_rows(company_id, mo)
        for uid, r in rows_by_uid.items():
            amt = key_fn(r)
            if amt <= 0:
                continue
            u = users.get(uid) or {}
            d = agg.setdefault(uid, {
                "employee_code": u.get("employee_code"),
                "name": u.get("name"), "gross": 0.0, "amount": 0.0,
                "reason": "", "recovered": 0.0, "balance": 0})
            d["gross"] = round(d["gross"] + _f(r.get("gross_paid")), 2)
            d["amount"] = round(d["amount"] + amt, 2)
            d["recovered"] = round(d["recovered"] + amt, 2)
    out = list(agg.values())
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("gross", "Gross Wages"), ("amount", f"{label} Amount"),
            ("reason", "Reason/Remarks"), ("recovered", "Recovered"),
            ("balance", "Balance")]
    totals = {"name": "TOTAL",
              "amount": round(sum(r["amount"] for r in out), 2),
              "recovered": round(sum(r["recovered"] for r in out), 2)}
    return f"{label} Register (Form C)", cols, _srt(out), totals


async def _deduction_register(company_id, month, ctx=None):
    """Iter 477 (user request) — Month-wise OR Periodic (month..month_to)."""
    months = _months_range(month, (ctx or {}).get("month_to") or "")
    users = {u["user_id"]: u for u in await _users(company_id)}
    agg: Dict[str, dict] = {}
    for mo in months:
        rows_by_uid = await _run_rows(company_id, mo)
        for uid, r in rows_by_uid.items():
            td = _f(r.get("total_deduction"))
            if td <= 0:
                continue
            u = users.get(uid) or {}
            d = agg.setdefault(uid, {
                "employee_code": u.get("employee_code"),
                "name": u.get("name"), "pf": 0.0, "esic": 0.0, "pt": 0.0,
                "tds": 0.0, "other": 0.0, "total": 0.0, "net": 0.0})
            d["pf"] = round(d["pf"] + _f(r.get("pf_employee")), 2)
            d["esic"] = round(d["esic"] + _f(r.get("esic_employee")), 2)
            d["pt"] = round(d["pt"] + _f(r.get("pt")), 2)
            d["tds"] = round(d["tds"] + _f(r.get("tds")), 2)
            d["other"] = round(d["other"] + _f(r.get("other_deduction")), 2)
            d["total"] = round(d["total"] + td, 2)
            d["net"] = round(d["net"] + _f(r.get("net")), 2)
    out = list(agg.values())
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("pf", "PF"), ("esic", "ESIC"), ("pt", "PT"), ("tds", "TDS"),
            ("other", "Other/Fines"), ("total", "Total Deduction"),
            ("net", "Net Paid")]
    totals = {"name": "TOTAL"}
    for k in ("pf", "esic", "pt", "tds", "other", "total", "net"):
        totals[k] = round(sum(r[k] for r in out), 2)
    return "Deduction Register (Form C)", cols, _srt(out), totals


async def _gratuity_register(company_id, month, ctx=None):
    """Iter 477 (user request) — Periodic: Basic Wages picked from the
    LATEST month in the range that has a processed run row."""
    users = await _users(company_id)
    emp_ids = set((ctx or {}).get("employee_ids") or [])
    rows_by_uid: Dict[str, dict] = {}
    for mo in _months_range(month, (ctx or {}).get("month_to") or ""):
        rows_by_uid.update(await _run_rows(company_id, mo))
    today = date.today()
    out = []
    for u in users:
        if emp_ids and u["user_id"] not in emp_ids:
            continue
        if not emp_ids and not _active(u):
            continue
        doj = _dt(u.get("doj"))
        if not doj and not emp_ids:
            continue
        yrs = ((today - doj).days / 365) if doj else 0.0
        basic = _f((rows_by_uid.get(u["user_id"]) or {}).get("basic")) or \
            _f(u.get("compliance_gross") or u.get("salary_monthly")) * 0.5
        accrued = round(basic * 15 / 26 * int(yrs), 2) if yrs >= 5 else 0
        # Iter 480 (user spec — Phase 2): taxable / exempt split (exempt
        # up to ₹20,00,000 u/s 10(10)), wage definition + payment date.
        exempt = round(min(accrued, 2000000), 2)
        out.append({"employee_code": u.get("employee_code"),
                    "name": u.get("name"), "doj": u.get("doj"),
                    "service_years": round(yrs, 1),
                    "eligible": "Yes" if yrs >= 5 else "No",
                    "eligible_service": int(yrs) if yrs >= 5 else 0,
                    "wage_def": "Basic + DA (last drawn)",
                    "last_basic": round(basic, 2),
                    "accrued_gratuity": accrued,
                    "exempt": exempt,
                    "taxable": round(accrued - exempt, 2),
                    "payment_date": ""})
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("doj", "DOJ"), ("service_years", "Total Service (yrs)"),
            ("eligible", "Eligible (5+ yrs)"),
            ("eligible_service", "Eligible Service (yrs)"),
            ("wage_def", "Wage Definition"),
            ("last_basic", "Last Drawn Wages"),
            ("accrued_gratuity", "Gratuity Amount (15/26 × yrs)"),
            ("exempt", "Exempt Amount"), ("taxable", "Taxable Amount"),
            ("payment_date", "Payment Date")]
    totals = {"name": "TOTAL", "accrued_gratuity": round(
        sum(r["accrued_gratuity"] for r in out), 2)}
    return "Gratuity Register", cols, _srt(out), totals


_GOVT = {
    "wage-register": _wage_register,
    "fine-register": lambda c, m, x=None: _amount_register(
        c, m, lambda r: _f(r.get("fine")) + _f(r.get("other_deduction")),
        "Fine", x),
    "deduction-register": _deduction_register,
    "advance-register": lambda c, m, x=None: _amount_register(
        c, m, lambda r: _f(r.get("advance")) + _f(r.get("advance_recovery")),
        "Advance", x),
    "gratuity-register": _gratuity_register,
}
_GOVT_TITLES = {
    "wage-register": "Wage Register",
    "fine-register": "Fine Register",
    "deduction-register": "Deduction Register",
    "advance-register": "Advance Register",
    "gratuity-register": "Gratuity Register",
}
# Iter 477 (user request — "roll back the format heading") — statutory
# FORM heading printed above every Government Register (PDF + Excel + web
# view), per the Ease of Compliance to Maintain Registers under various
# Labour Laws Rules, 2017 (FORM B = Wage Register, FORM C = Register of
# Loans / Recoveries).
_FORM_RULE = ("[Ease of Compliance to Maintain Registers under various "
              "Labour Laws Rules, 2017]")
_FORM_HEAD = {
    "wage-register": f"FORM B — WAGE REGISTER\n{_FORM_RULE}",
    "fine-register": ("FORM C — REGISTER OF LOANS / RECOVERIES (FINE)\n"
                      f"{_FORM_RULE}"),
    "deduction-register": ("FORM C — REGISTER OF LOANS / RECOVERIES "
                           f"(DEDUCTIONS)\n{_FORM_RULE}"),
    "advance-register": ("FORM C — REGISTER OF LOANS / RECOVERIES "
                         f"(ADVANCES)\n{_FORM_RULE}"),
    "gratuity-register": "[Under the Payment of Gratuity Act, 1972]",
}


async def _form_head(kind: str) -> str:
    """Iter 478 (user request) — heading lines are EDITABLE from the
    portal (Report Hub → pencil on a Government Register). A saved custom
    heading in db.app_settings overrides the built-in FORM text; empty =
    back to default."""
    doc = await db.app_settings.find_one(
        {"key": f"govt_register_heading:{kind}"}, {"_id": 0})
    if doc and str(doc.get("lines") or "").strip():
        return str(doc["lines"]).strip()
    return _FORM_HEAD.get(kind, "")


@govt_router.get("/list")
async def govt_list(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    return {"registers": [{"kind": k, "title": t}
                          for k, t in _GOVT_TITLES.items()]}


# Iter 478 (user request) — portal-editable register headings. NOTE: must
# be registered BEFORE the catch-all /{kind} route below.
@govt_router.get("/headings")
async def govt_headings(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    out = []
    for k, t in _GOVT_TITLES.items():
        doc = await db.app_settings.find_one(
            {"key": f"govt_register_heading:{k}"}, {"_id": 0})
        custom = str((doc or {}).get("lines") or "").strip()
        out.append({"kind": k, "title": t,
                    "default_lines": _FORM_HEAD.get(k, ""),
                    "custom_lines": custom,
                    "effective": custom or _FORM_HEAD.get(k, "")})
    return {"headings": out}


@govt_router.put("/headings/{kind}")
async def govt_heading_save(kind: str, payload: dict = Body(...),
                            authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    if kind not in _GOVT_TITLES:
        raise HTTPException(status_code=404, detail="Unknown register")
    lines = str((payload or {}).get("lines") or "").strip()
    if lines:
        await db.app_settings.update_one(
            {"key": f"govt_register_heading:{kind}"},
            {"$set": {"lines": lines,
                      "updated_at": datetime.utcnow().isoformat(),
                      "updated_by": admin.get("email") or admin.get("user_id")}},
            upsert=True)
    else:
        await db.app_settings.delete_one(
            {"key": f"govt_register_heading:{kind}"})
    return {"ok": True, "effective": lines or _FORM_HEAD.get(kind, "")}


@govt_router.get("/{kind}")
async def govt_json(kind: str, company_id: Optional[str] = None,
                    month: Optional[str] = None, month_to: str = "",
                    employee_ids: str = "",
                    authorization: Optional[str] = Header(None)):
    ctx = {"month_to": month_to.strip(),
           "employee_ids": [e for e in (employee_ids or "").split(",") if e]}
    for ext in ("xlsx", "pdf"):
        if kind.endswith(f".{ext}"):
            return await _govt_exp(kind[: -len(ext) - 1], company_id, month,
                                   authorization, ext, ctx)
    if kind not in _GOVT:
        raise HTTPException(status_code=404, detail="Unknown register")
    company_id = await _adm(authorization, company_id)
    month = month or date.today().strftime("%Y-%m")
    title, cols, rows, totals = await _GOVT[kind](company_id, month, ctx)
    sub = _govt_period(month, ctx)
    return {"title": title, "subtitle": sub,
            "form_line": await _form_head(kind),
            "columns": [{"key": k, "label": lb} for k, lb in cols],
            "rows": rows, "totals": totals,
            "empty_note": _govt_empty_note(kind, month, ctx) if not rows
            else ""}


def _govt_period(month: str, ctx: dict) -> str:
    mt = (ctx or {}).get("month_to") or ""
    if mt and mt > month:
        return f"{_mlabel(month)} to {_mlabel(mt)}"
    return _mlabel(month)


def _govt_empty_note(kind: str, month: str, ctx: dict) -> str:
    """Iter 433 (user request) — centred empty-state line, e.g. the Fine
    Register: 'There is No Fine in this Month of (June 2026)'."""
    labels = {"fine-register": "Fine", "advance-register": "Advance",
              "deduction-register": "Deduction"}
    lb = labels.get(kind)
    if not lb:
        return ""
    mt = (ctx or {}).get("month_to") or ""
    if mt and mt > month:
        return (f"There is No {lb} in the Period of "
                f"({_mlabel(month)} to {_mlabel(mt)})")
    return f"There is No {lb} in this Month of ({_mlabel(month)})"


async def _govt_exp(kind, company_id, month, authorization, fmt, ctx=None):
    if kind not in _GOVT:
        raise HTTPException(status_code=404, detail="Unknown register")
    company_id = await _adm(authorization, company_id)
    month = month or date.today().strftime("%Y-%m")
    c = await _company(company_id)
    title, cols, rows, totals = await _GOVT[kind](company_id, month,
                                                  ctx or {})
    sub = _govt_period(month, ctx or {})
    return _stream(title, f"{c.get('name')} · {sub}", cols, rows, totals,
                   c.get("logo_base64"), fmt,
                   empty_note=_govt_empty_note(kind, month, ctx or {}),
                   form_line=await _form_head(kind))


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
            q = ({"$or": [{"company_id": company_id},
                          {"company_id": {"$exists": False}}]}
                 if company_id else {})
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


def _stream(title, sub, cols, rows, totals, logo, fmt, empty_note=None,
            form_line=None):
    columns = [{"key": k, "label": lb} for k, lb in cols]
    sub = f"{sub} · Generated {datetime.now():%d-%m-%Y}"
    if fmt == "xlsx":
        buf = register_xlsx(title, sub, columns, rows, totals,
                            form_line=form_line)
        mt = ("application/vnd.openxmlformats-officedocument"
              ".spreadsheetml.sheet")
    else:
        buf = register_pdf(title, sub, columns, rows, totals, logo,
                           empty_note=empty_note, form_line=form_line)
        mt = "application/pdf"
    fn_ = f"{title.replace(' ', '_')}.{fmt}"
    return StreamingResponse(buf, media_type=mt, headers={
        "Content-Disposition": f'attachment; filename="{fn_}"'})
