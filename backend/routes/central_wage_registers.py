"""Iter 527 (user request) — CENTRAL CONTRACTOR WAGE REGISTERS (Form A–D).

New INDEPENDENT compliance-register module:
  Compliance → Contractor Registers → Central Wages
    Form A — Employee Register            (Employee + Contractor Master)
    Form B — Wage Register                (approved Compliance Salary run)
    Form C — Deductions / Advances / Recoveries (Advance module + manual)
    Form D — Attendance / Muster Roll     (existing attendance engine)

NOTHING in Employee Master / Contractor Master / Attendance / Payroll /
Compliance Salary is modified — data is READ from those modules. The OT
figures reuse ``_compute_monthly_grid_data`` (the same engine that applies
the firm's "Count Present Day @ 8 HRS" policy), so Form B/D OT always
matches the approved payroll OT.

New collections (module-private):
  cwr_principal_employers  — Principal Employer master
  cwr_work_orders          — Work Order / Contract (contractor → PE → site)
  cwr_emp_map              — employee ↔ contractor/work-order/site mapping
  cwr_form_c               — manual deduction / fine / recovery entries
  cwr_status               — register approval workflow + audit trail
"""
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from server import (db, get_user_from_token, require_role, now_iso,  # noqa: E402
                    _compute_monthly_grid_data)
from routes.present_absent_report import _day_status  # noqa: E402
from utils.register_export import register_pdf, register_xlsx  # noqa: E402

router = APIRouter(prefix="/api/admin/central-wage-registers",
                   tags=["central-wage-registers"])

FRAMEWORK = ("Contract Labour (Regulation & Abolition) Act, 1970 — "
             "Central Rules, 1971 (configurable formats)")

FORM_TITLES = {
    "a": "Form A — Employee Register",
    "b": "Form B — Wage Register",
    "c": "Form C — Register of Deductions / Advances / Recoveries",
    "d": "Form D — Attendance / Muster Roll",
}


async def _adm(authorization, company_id):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return admin, company_id


def _f(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _s(v) -> str:
    return str(v or "").strip()


def _dmy(v) -> str:
    """Iter 687 (user request) — ALL dates shown as DD-MM-YYYY."""
    s = _s(v)[:10]
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return f"{s[8:10]}-{s[5:7]}-{s[0:4]}"
    return s


def _norm(v) -> str:
    return _s(v).upper()


def _first(u: dict, *keys) -> str:
    for k in keys:
        if _s(u.get(k)):
            return _s(u.get(k))
    return ""


def _mask_aadhaar(v) -> str:
    s = "".join(ch for ch in _s(v) if ch.isdigit())
    return f"XXXX-XXXX-{s[-4:]}" if len(s) >= 4 else ""


def _age(dob) -> str:
    s = _s(dob)[:10]
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
        t = date.today()
        yrs = t.year - d.year - ((t.month, t.day) < (d.month, d.day))
        return str(yrs) if 0 < yrs < 120 else ""
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# wage period — calendar month OR custom date range (same for all 4 forms)
# ---------------------------------------------------------------------------
def _period(month: str, from_date: str, to_date: str) -> Dict[str, Any]:
    fd, td = _s(from_date)[:10], _s(to_date)[:10]
    if len(fd) == 10 and len(td) == 10 and fd <= td:
        months, cur = [], fd[:7]
        while cur <= td[:7] and len(months) < 13:
            months.append(cur)
            y, m = int(cur[:4]), int(cur[5:7])
            cur = f"{y + (m == 12):04d}-{(m % 12) + 1:02d}"
        return {"label": f"{fd} to {td}", "months": months,
                "from": fd, "to": td, "custom": True}
    m = _s(month)[:7] or date.today().strftime("%Y-%m")
    return {"label": m, "months": [m], "from": "", "to": "", "custom": False}


# ---------------------------------------------------------------------------
# contractor / work-order / mapping resolution (Employee Master untouched)
# ---------------------------------------------------------------------------
async def _resolve(company_id: str) -> Dict[str, Any]:
    ctrs = {c["contractor_id"]: c async for c in db.contractors.find(
        {"company_id": company_id}, {"_id": 0})}
    by_name = {_norm(c.get("name")): c for c in ctrs.values()}
    pes = {p["pe_id"]: p async for p in db.cwr_principal_employers.find(
        {"company_id": company_id}, {"_id": 0})}
    wos = {w["wo_id"]: w async for w in db.cwr_work_orders.find(
        {"company_id": company_id}, {"_id": 0})}
    maps = {m["user_id"]: m async for m in db.cwr_emp_map.find(
        {"company_id": company_id}, {"_id": 0})}
    return {"ctrs": ctrs, "by_name": by_name, "pes": pes,
            "wos": wos, "maps": maps}


def _emp_ctx(u: dict, res: Dict[str, Any]) -> Dict[str, Any]:
    m = res["maps"].get(u.get("user_id")) or {}
    ctr = (res["ctrs"].get(m.get("contractor_id"))
           or res["by_name"].get(_norm(u.get("contractor_name"))))
    wo = res["wos"].get(m.get("work_order_id"))
    pe = res["pes"].get((wo or {}).get("pe_id") or m.get("pe_id"))
    site = _s(m.get("site")) or _s((wo or {}).get("site"))
    return {"contractor": ctr, "work_order": wo, "pe": pe, "site": site,
            "contractor_name": (ctr or {}).get("name")
            or _s(u.get("contractor_name")),
            "pe_name": (pe or {}).get("name") or "",
            "wo_number": (wo or {}).get("wo_number") or ""}


async def _emps(company_id: str, flt: Dict[str, str], res: Dict[str, Any]):
    users = await db.users.find(
        {"company_id": company_id, "role": "employee"},
        {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
         "father_name": 1, "dob": 1, "gender": 1, "doj": 1, "designation": 1,
         "weekly_off_days_override": 1,
         "department": 1, "employee_type": 1, "contractor_name": 1,
         "uan_no": 1, "esi_ip_no": 1, "aadhaar_no": 1, "pan_no": 1,
         "bank_account_name": 1, "bank_account_no": 1, "account_no": 1,
         "bank_name": 1, "ifsc_code": 1, "ifsc": 1, "exit_date": 1,
         "resign_date": 1, "employment_status": 1}).to_list(100000)
    ids = set((flt.get("employee_ids") or "").split(",")) - {""}
    term = _s(flt.get("search")).lower()
    out = []
    for u in users:
        ctx = _emp_ctx(u, res)
        if flt.get("contractor_id") and \
                (ctx["contractor"] or {}).get("contractor_id") != flt["contractor_id"]:
            continue
        if flt.get("work_order_id") and \
                (ctx["work_order"] or {}).get("wo_id") != flt["work_order_id"]:
            continue
        if flt.get("site") and _norm(ctx["site"]) != _norm(flt["site"]):
            continue
        if flt.get("principal_employer_id") and \
                (ctx["pe"] or {}).get("pe_id") != flt["principal_employer_id"]:
            continue
        if flt.get("department") and \
                _norm(u.get("department")) != _norm(flt["department"]):
            continue
        if flt.get("employee_type") and \
                _norm(u.get("employee_type")) != _norm(flt["employee_type"]):
            continue
        if ids and u["user_id"] not in ids:
            continue
        if term and term not in \
                f"{u.get('name', '')} {u.get('employee_code', '')}".lower():
            continue
        u["_ctx"] = ctx
        out.append(u)
    out.sort(key=lambda x: (str(x.get("employee_code") or "").zfill(8),
                            _s(x.get("name"))))
    return out


async def _run_rows(company_id: str, month: str) -> Dict[str, dict]:
    run = await db.compliance_salary_runs.find_one(
        {"company_id": company_id, "month": month}, {"_id": 0, "rows": 1},
        sort=[("generated_at", -1)])
    return {r.get("user_id"): r for r in (run or {}).get("rows") or []}


async def _att_summary(company_id: str, per: Dict[str, Any]) -> Dict[str, dict]:
    """Day-status counts + worked/OT hours per user for the wage period —
    reuses the SAME attendance engine as the approved payroll (no second
    OT calculation)."""
    today_iso = date.today().isoformat()
    agg: Dict[str, dict] = {}
    for m in per["months"]:
        fd = per["from"] if per["custom"] else None
        td = per["to"] if per["custom"] else None
        data = await _compute_monthly_grid_data(
            company_id=company_id, month=m,
            from_date=max(fd, f"{m}-01") if fd else None,
            to_date=min(td, f"{m}-31") if td else None)
        dls = data.get("day_labels") or []
        dfd = data.get("day_full_dates") or [f"{m}-{str(d)[:2]}" for d in dls]
        for e in data.get("employees") or []:
            uid = e.get("user_id")
            d = agg.setdefault(uid, {
                "P": 0, "HD": 0, "A": 0, "WO": 0, "H": 0, "L": 0,
                "present_days": 0.0, "worked_hours": 0.0, "ot_hours": 0.0,
                "days": {}, "code": e.get("employee_code"),
                "name": e.get("name"),
                "designation": e.get("designation") or e.get("position")})
            for i, dl in enumerate(dls):
                cell = (e.get("days") or {}).get(dl) or {}
                iso = dfd[i] if i < len(dfd) else f"{m}-{str(dl)[:2]}"
                st = _day_status(cell, iso, today_iso)
                if cell.get("leave") and st == "A":
                    st = "L"
                if st:
                    d[st] = d.get(st, 0) + 1
                d["days"][iso] = {"st": st,
                                  "ot": _f(cell.get("ot_hours")) if st else 0}
                d["worked_hours"] = round(
                    d["worked_hours"] + _f(cell.get("hours")), 2)
                if st:
                    d["ot_hours"] = round(
                        d["ot_hours"] + _f(cell.get("ot_hours")), 2)
            d["present_days"] = round(
                d["present_days"]
                + _f((e.get("totals") or {}).get("present_days_policy")), 2)
    return agg


# ---------------------------------------------------------------------------
# workflow (Draft → Verified → Approved → Locked, with unlock audit)
# ---------------------------------------------------------------------------
async def _status_doc(company_id: str, register: str, period: str) -> dict:
    doc = await db.cwr_status.find_one(
        {"company_id": company_id, "register": register, "period": period},
        {"_id": 0})
    return doc or {"company_id": company_id, "register": register,
                   "period": period, "status": "draft", "history": []}


def _locked(doc: dict) -> bool:
    return (doc or {}).get("status") in ("approved", "locked")


@router.get("/status")
async def get_status(company_id: Optional[str] = None, register: str = "a",
                     period: str = "",
                     authorization: Optional[str] = Header(None)):
    _admin, company_id = await _adm(authorization, company_id)
    return await _status_doc(company_id, register, period)


@router.post("/status")
async def set_status(payload: Dict[str, Any] = Body(default={}),
                     authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(authorization, payload.get("company_id"))
    register = _s(payload.get("register")).lower()
    period = _s(payload.get("period"))
    action = _s(payload.get("action")).lower()
    if register not in FORM_TITLES or not period:
        raise HTTPException(status_code=400, detail="register/period required")
    flow = {"prepare": "draft", "verify": "verified", "approve": "approved",
            "lock": "locked", "unlock": "draft"}
    if action not in flow:
        raise HTTPException(status_code=400, detail="Unknown action")
    doc = await _status_doc(company_id, register, period)
    if action in ("verify", "approve", "lock") and \
            doc.get("status") == "locked":
        raise HTTPException(status_code=409,
                            detail="Register is LOCKED — unlock it first.")
    who, at = admin.get("name") or admin.get("email"), now_iso()
    doc["status"] = flow[action]
    stamp = {"prepare": ("prepared_by", "prepared_at"),
             "verify": ("verified_by", "verified_at"),
             "approve": ("approved_by", "approved_at"),
             "lock": ("locked_by", "locked_at"),
             "unlock": ("unlocked_by", "unlocked_at")}[action]
    doc[stamp[0]], doc[stamp[1]] = who, at
    if action == "unlock":  # reopen clears downstream sign-offs
        for k in ("verified_by", "verified_at", "approved_by", "approved_at",
                  "locked_by", "locked_at"):
            doc.pop(k, None)
    doc.setdefault("history", []).append(
        {"at": at, "by": who, "action": action,
         "note": _s(payload.get("note"))})
    await db.cwr_status.update_one(
        {"company_id": company_id, "register": register, "period": period},
        {"$set": doc}, upsert=True)
    return {"ok": True, "status": doc["status"], "doc": doc}


# ---------------------------------------------------------------------------
# masters — Principal Employers / Work Orders / Employee mapping
# ---------------------------------------------------------------------------
@router.get("/principal-employers")
async def list_pes(company_id: Optional[str] = None,
                   authorization: Optional[str] = Header(None)):
    _a, company_id = await _adm(authorization, company_id)
    rows = await db.cwr_principal_employers.find(
        {"company_id": company_id}, {"_id": 0}).to_list(1000)
    rows.sort(key=lambda r: _norm(r.get("name")))
    return {"principal_employers": rows}


@router.post("/principal-employers")
async def save_pe(payload: Dict[str, Any] = Body(default={}),
                  authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(authorization, payload.get("company_id"))
    if not _s(payload.get("name")):
        raise HTTPException(status_code=400, detail="Name is required")
    doc = {k: _s(payload.get(k)) for k in
           ("name", "address", "representative", "registration_no",
            "licence_no", "status")}
    doc["status"] = doc["status"] or "active"
    pe_id = _s(payload.get("pe_id"))
    if pe_id:
        await db.cwr_principal_employers.update_one(
            {"company_id": company_id, "pe_id": pe_id}, {"$set": doc})
    else:
        pe_id = f"pe_{uuid.uuid4().hex[:10]}"
        doc.update({"pe_id": pe_id, "company_id": company_id,
                    "created_at": now_iso(),
                    "created_by": admin.get("name") or admin.get("email")})
        await db.cwr_principal_employers.insert_one(doc)
    return {"ok": True, "pe_id": pe_id}


@router.delete("/principal-employers/{pe_id}")
async def del_pe(pe_id: str, company_id: Optional[str] = None,
                 authorization: Optional[str] = Header(None)):
    _a, company_id = await _adm(authorization, company_id)
    await db.cwr_principal_employers.delete_one(
        {"company_id": company_id, "pe_id": pe_id})
    return {"ok": True}


@router.get("/work-orders")
async def list_wos(company_id: Optional[str] = None,
                   authorization: Optional[str] = Header(None)):
    _a, company_id = await _adm(authorization, company_id)
    rows = await db.cwr_work_orders.find(
        {"company_id": company_id}, {"_id": 0}).to_list(2000)
    rows.sort(key=lambda r: _norm(r.get("wo_number")))
    return {"work_orders": rows}


@router.post("/work-orders")
async def save_wo(payload: Dict[str, Any] = Body(default={}),
                  authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(authorization, payload.get("company_id"))
    if not _s(payload.get("wo_number")):
        raise HTTPException(status_code=400, detail="Work Order No. required")
    doc = {k: _s(payload.get(k)) for k in
           ("wo_number", "description", "contractor_id", "pe_id", "site",
            "start_date", "end_date", "status")}
    doc["status"] = doc["status"] or "active"
    wo_id = _s(payload.get("wo_id"))
    if wo_id:
        await db.cwr_work_orders.update_one(
            {"company_id": company_id, "wo_id": wo_id}, {"$set": doc})
    else:
        wo_id = f"wo_{uuid.uuid4().hex[:10]}"
        doc.update({"wo_id": wo_id, "company_id": company_id,
                    "created_at": now_iso(),
                    "created_by": admin.get("name") or admin.get("email")})
        await db.cwr_work_orders.insert_one(doc)
    return {"ok": True, "wo_id": wo_id}


@router.delete("/work-orders/{wo_id}")
async def del_wo(wo_id: str, company_id: Optional[str] = None,
                 authorization: Optional[str] = Header(None)):
    _a, company_id = await _adm(authorization, company_id)
    await db.cwr_work_orders.delete_one(
        {"company_id": company_id, "wo_id": wo_id})
    return {"ok": True}


@router.get("/employee-map")
async def list_map(company_id: Optional[str] = None,
                   authorization: Optional[str] = Header(None)):
    _a, company_id = await _adm(authorization, company_id)
    rows = await db.cwr_emp_map.find(
        {"company_id": company_id}, {"_id": 0}).to_list(100000)
    return {"mappings": rows}


@router.post("/employee-map")
async def save_map(payload: Dict[str, Any] = Body(default={}),
                   authorization: Optional[str] = Header(None)):
    """Bulk map employees → contractor / work order / site (Employee
    Master is NOT modified — mapping lives in cwr_emp_map)."""
    admin, company_id = await _adm(authorization, payload.get("company_id"))
    uids = [u for u in (payload.get("user_ids") or []) if _s(u)]
    if not uids:
        raise HTTPException(status_code=400, detail="user_ids required")
    doc = {k: _s(payload.get(k)) for k in
           ("contractor_id", "work_order_id", "pe_id", "site")}
    doc.update({"updated_at": now_iso(),
                "updated_by": admin.get("name") or admin.get("email")})
    for uid in uids:
        await db.cwr_emp_map.update_one(
            {"company_id": company_id, "user_id": uid},
            {"$set": {**doc, "company_id": company_id, "user_id": uid}},
            upsert=True)
    return {"ok": True, "mapped": len(uids)}


@router.delete("/employee-map/{user_id}")
async def del_map(user_id: str, company_id: Optional[str] = None,
                  authorization: Optional[str] = Header(None)):
    _a, company_id = await _adm(authorization, company_id)
    await db.cwr_emp_map.delete_one(
        {"company_id": company_id, "user_id": user_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# common filters
# ---------------------------------------------------------------------------
@router.get("/filters")
async def filters(company_id: Optional[str] = None,
                  authorization: Optional[str] = Header(None)):
    _a, company_id = await _adm(authorization, company_id)
    res = await _resolve(company_id)
    users = await db.users.find(
        {"company_id": company_id, "role": "employee"},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
         "department": 1, "employee_type": 1,
         "contractor_name": 1}).to_list(100000)
    sites = {_s(w.get("site")) for w in res["wos"].values()} | \
            {_s(m.get("site")) for m in res["maps"].values()}
    dh = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "deductions": 1})
    ded_heads = sorted(k for k, v in ((dh or {}).get("deductions") or
                                      {}).items() if v)
    return {
        "contractors": sorted(
            [{"contractor_id": c["contractor_id"], "name": c.get("name")}
             for c in res["ctrs"].values()], key=lambda x: _norm(x["name"])),
        "principal_employers": sorted(
            [{"pe_id": p["pe_id"], "name": p.get("name")}
             for p in res["pes"].values()], key=lambda x: _norm(x["name"])),
        "work_orders": sorted(
            [{"wo_id": w["wo_id"], "wo_number": w.get("wo_number"),
              "contractor_id": w.get("contractor_id"),
              "site": w.get("site")} for w in res["wos"].values()],
            key=lambda x: _norm(x["wo_number"])),
        "sites": sorted(sites - {""}),
        "departments": sorted({_s(u.get("department")) for u in users} - {""}),
        "employee_types": sorted({_s(u.get("employee_type"))
                                  for u in users} - {""}),
        "employees": sorted(
            [{"user_id": u["user_id"], "name": u.get("name"),
              "employee_code": u.get("employee_code")} for u in users],
            key=lambda x: str(x.get("employee_code") or "").zfill(8)),
        "deduction_categories": ["Advance", "Loan", "Fine",
                                 "Damage / Loss", "Other"] + ded_heads,
        "framework": FRAMEWORK,
    }


# ---------------------------------------------------------------------------
# Form C manual entries (blocked once the period is approved / locked)
# ---------------------------------------------------------------------------
@router.get("/form-c-entries")
async def list_c_entries(company_id: Optional[str] = None, month: str = "",
                         from_date: str = "", to_date: str = "",
                         authorization: Optional[str] = Header(None)):
    _a, company_id = await _adm(authorization, company_id)
    per = _period(month, from_date, to_date)
    q: Dict[str, Any] = {"company_id": company_id}
    if per["custom"]:
        q["date"] = {"$gte": per["from"], "$lte": per["to"]}
    else:
        q["wage_period"] = per["label"]
    rows = await db.cwr_form_c.find(q, {"_id": 0}).to_list(50000)
    rows.sort(key=lambda r: (_s(r.get("date")), _s(r.get("employee_code"))))
    return {"entries": rows, "period": per["label"]}


@router.post("/form-c-entries")
async def save_c_entry(payload: Dict[str, Any] = Body(default={}),
                       authorization: Optional[str] = Header(None)):
    admin, company_id = await _adm(authorization, payload.get("company_id"))
    d = _s(payload.get("date"))[:10] or date.today().isoformat()
    per = payload.get("wage_period") or d[:7]
    st = await _status_doc(company_id, "c", _s(per))
    if _locked(st):
        raise HTTPException(
            status_code=409,
            detail="Form C for this period is APPROVED/LOCKED — unlock to edit.")
    uid = _s(payload.get("user_id"))
    u = await db.users.find_one(
        {"company_id": company_id, "user_id": uid},
        {"_id": 0, "name": 1, "employee_code": 1})
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    doc = {
        "user_id": uid, "employee_code": u.get("employee_code"),
        "employee_name": u.get("name"), "wage_period": _s(per), "date": d,
        "dtype": _s(payload.get("dtype")) or "Other",
        "reason": _s(payload.get("reason")),
        "advance_amount": _f(payload.get("advance_amount")),
        "recovery_amount": _f(payload.get("recovery_amount")),
        "fine_amount": _f(payload.get("fine_amount")),
        "other_amount": _f(payload.get("other_amount")),
        "remarks": _s(payload.get("remarks")),
    }
    eid = _s(payload.get("entry_id"))
    who, at = admin.get("name") or admin.get("email"), now_iso()
    if eid:
        doc["updated_at"], doc["updated_by"] = at, who
        r = await db.cwr_form_c.update_one(
            {"company_id": company_id, "entry_id": eid},
            {"$set": doc, "$push": {"audit": {"at": at, "by": who,
                                              "action": "edit"}}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Entry not found")
    else:
        eid = f"cwrc_{uuid.uuid4().hex[:10]}"
        doc.update({"entry_id": eid, "company_id": company_id,
                    "created_at": at, "created_by": who,
                    "audit": [{"at": at, "by": who, "action": "create"}]})
        await db.cwr_form_c.insert_one(doc)
    return {"ok": True, "entry_id": eid}


@router.delete("/form-c-entries/{entry_id}")
async def del_c_entry(entry_id: str, company_id: Optional[str] = None,
                      authorization: Optional[str] = Header(None)):
    _a, company_id = await _adm(authorization, company_id)
    e = await db.cwr_form_c.find_one(
        {"company_id": company_id, "entry_id": entry_id}, {"_id": 0})
    if not e:
        raise HTTPException(status_code=404, detail="Entry not found")
    if _locked(await _status_doc(company_id, "c", _s(e.get("wage_period")))):
        raise HTTPException(status_code=409,
                            detail="Period APPROVED/LOCKED — unlock to edit.")
    await db.cwr_form_c.delete_one(
        {"company_id": company_id, "entry_id": entry_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# FORM BUILDERS — each returns (columns, rows, totals)
# ---------------------------------------------------------------------------
async def _form_a(company_id, per, flt, res):
    emps = await _emps(company_id, flt, res)
    rows = []
    for i, u in enumerate(emps, 1):
        c = u["_ctx"]
        rows.append({
            "sr": i, "employee_code": u.get("employee_code"),
            "name": u.get("name"), "father_name": _s(u.get("father_name")),
            "dob_age": (f"{_dmy(u.get('dob'))}"
                        f"{' / ' + _age(u.get('dob')) if _age(u.get('dob')) else ''}"),
            "gender": _s(u.get("gender")).title(),
            "doj": _dmy(u.get("doj")),
            "designation": _s(u.get("designation")),
            "department": _s(u.get("department")),
            "contractor": c["contractor_name"],
            "principal_employer": c["pe_name"],
            "work_location": c["site"],
            "employee_type": _s(u.get("employee_type")),
            "uan": _s(u.get("uan_no")), "esic_ip": _s(u.get("esi_ip_no")),
            "aadhaar": _mask_aadhaar(u.get("aadhaar_no")),
            "bank": " / ".join(x for x in (
                _first(u, "bank_account_no", "account_no",
                       "bank_account_name"),
                _first(u, "ifsc_code", "ifsc"),
                _s(u.get("bank_name"))) if x),
            "date_of_leaving": _dmy(u.get("exit_date")
                                    or u.get("resign_date")),
            "remarks": "",
        })
    cols = [("sr", "Sr."), ("employee_code", "Emp Code"),
            ("name", "Employee Name"),
            ("father_name", "Father's / Husband's Name"),
            ("dob_age", "DOB / Age"), ("gender", "Gender"),
            ("doj", "Date of Joining"),
            ("designation", "Designation / Nature of Work"),
            ("department", "Department"), ("contractor", "Contractor"),
            ("principal_employer", "Principal Employer"),
            ("work_location", "Work Location / Site"),
            ("employee_type", "Category"), ("uan", "UAN"),
            ("esic_ip", "ESIC IP No."), ("aadhaar", "Aadhaar (masked)"),
            ("bank", "Bank A/c / IFSC"),
            ("date_of_leaving", "Date of Leaving"), ("remarks", "Remarks")]
    return cols, rows, None


async def _form_b(company_id, per, flt, res):
    emps = await _emps(company_id, flt, res)
    att = await _att_summary(company_id, per)
    runs: Dict[str, dict] = {}
    for m in per["months"]:
        for uid, r in (await _run_rows(company_id, m)).items():
            d = runs.setdefault(uid, {})
            for k in ("present_days", "ot_hours", "ot_pay", "basic", "hra",
                      "conveyance", "medical", "special", "others",
                      "gross_paid", "pf_employee", "esic_employee", "pt",
                      "tds", "total_deduction", "net"):
                d[k] = round(_f(d.get(k)) + _f(r.get(k)), 2)
            dh = r.get("deduction_heads") or {}
            for hk, hv in dh.items():
                key = _norm(hk)
                if "ADV" in key or "LOAN" in key:
                    d["advance"] = round(_f(d.get("advance")) + _f(hv), 2)
                else:
                    d["other_ded"] = round(_f(d.get("other_ded")) + _f(hv), 2)
            d["other_ded"] = round(_f(d.get("other_ded"))
                                   + _f(r.get("other_deduction"))
                                   + _f(r.get("master_deduction")), 2)
    rows = []
    for i, u in enumerate(emps, 1):
        r = runs.get(u["user_id"]) or {}
        a = att.get(u["user_id"]) or {}
        gross = _f(r.get("gross_paid"))
        if not gross and not _f(r.get("present_days")) and not a:
            continue  # no wage / attendance record in the period
        other_allow = round(_f(r.get("conveyance")) + _f(r.get("medical"))
                            + _f(r.get("special")) + _f(r.get("others")), 2)
        rows.append({
            "sr": i, "employee_code": u.get("employee_code"),
            "name": u.get("name"), "designation": _s(u.get("designation")),
            "wage_period": per["label"],
            "days_worked": _f(r.get("present_days")) or _f(a.get("present_days")),
            "present_days": _f(a.get("present_days")) or _f(r.get("present_days")),
            "weekly_off": a.get("WO", 0), "paid_holidays": a.get("H", 0),
            "leave": a.get("L", 0),
            "basic": _f(r.get("basic")), "da_vda": 0,
            "hra": _f(r.get("hra")), "other_allowances": other_allow,
            "ot_hours": _f(r.get("ot_hours")) or _f(a.get("ot_hours")),
            "ot_amount": _f(r.get("ot_pay")), "gross": gross,
            "pf": _f(r.get("pf_employee")), "esi": _f(r.get("esic_employee")),
            "pt": _f(r.get("pt")), "other_statutory": _f(r.get("tds")),
            "advance_recovery": _f(r.get("advance")),
            "other_deductions": _f(r.get("other_ded")),
            "total_deductions": _f(r.get("total_deduction")),
            "net": _f(r.get("net")), "payment_date": "",
            "payment_mode": "Bank", "remarks": "",
        })
    for i, r in enumerate(rows, 1):
        r["sr"] = i
    cols = [("sr", "Sr."), ("employee_code", "Emp Code"),
            ("name", "Employee Name"), ("designation", "Designation"),
            ("wage_period", "Wage Period"),
            ("days_worked", "Days Worked"), ("present_days", "Present Days"),
            ("weekly_off", "Weekly Off"), ("paid_holidays", "Paid Holidays"),
            ("leave", "Leave"), ("basic", "Basic Wages"),
            ("da_vda", "DA / VDA"), ("hra", "HRA"),
            ("other_allowances", "Other Allowances"),
            ("ot_hours", "OT Hours"), ("ot_amount", "OT Amount"),
            ("gross", "Gross Wages"), ("pf", "PF"), ("esi", "ESI"),
            ("pt", "Prof. Tax"), ("other_statutory", "Other Statutory"),
            ("advance_recovery", "Advance / Loan Recovery"),
            ("other_deductions", "Other Deductions"),
            ("total_deductions", "Total Deductions"),
            ("net", "Net Wages Paid"), ("payment_date", "Payment Date"),
            ("payment_mode", "Mode"), ("remarks", "Remarks")]
    totals = {"name": "TOTAL"}
    for k in ("days_worked", "present_days", "weekly_off", "paid_holidays",
              "leave", "basic", "hra", "other_allowances", "ot_hours",
              "ot_amount", "gross", "pf", "esi", "pt", "other_statutory",
              "advance_recovery", "other_deductions", "total_deductions",
              "net"):
        totals[k] = round(sum(_f(r.get(k)) for r in rows), 2)
    return cols, rows, totals


async def _form_c(company_id, per, flt, res):
    emps = await _emps(company_id, flt, res)
    by_uid = {u["user_id"]: u for u in emps}
    rows: List[dict] = []
    # 1) Advance module — advances GIVEN in the period
    q_date = ({"$gte": per["from"], "$lte": per["to"]} if per["custom"]
              else {"$regex": f"^{per['months'][0]}"})
    if len(per["months"]) > 1 and not per["custom"]:
        q_date = {"$gte": f"{per['months'][0]}-01",
                  "$lte": f"{per['months'][-1]}-31"}
    async for a in db.advances.find(
            {"company_id": company_id, "advance_date": q_date}, {"_id": 0}):
        u = by_uid.get(a.get("user_id"))
        if not u:
            continue
        rows.append({
            "employee_code": u.get("employee_code"), "name": u.get("name"),
            "wage_period": per["label"],
            "date": _dmy(a.get("advance_date")),
            "dtype": f"Advance ({_s(a.get('advance_type')).title() or 'General'})",
            "reason": _s(a.get("purpose")),
            "advance_amount": _f(a.get("amount")), "recovery_amount": 0,
            "fine_amount": 0, "other_amount": 0,
            "balance": _f(a.get("remaining_balance")),
            "remarks": _s(a.get("remarks")), "source": "Advance Module"})
    # 2) Advance module — RECOVERIES in the period months
    async for t in db.advance_transactions.find(
            {"company_id": company_id,
             "salary_month": {"$in": per["months"]}}, {"_id": 0}):
        u = by_uid.get(t.get("user_id"))
        if not u:
            continue
        rows.append({
            "employee_code": u.get("employee_code"), "name": u.get("name"),
            "wage_period": per["label"],
            "date": _dmy(t.get("at")) or _dmy(f"{t.get('salary_month')}-01"),
            "dtype": "Advance / Loan Recovery",
            "reason": f"Recovery via {_s(t.get('process_type')).title()} salary",
            "advance_amount": 0, "recovery_amount": _f(t.get("amount")),
            "fine_amount": 0, "other_amount": 0,
            "balance": _f(t.get("remaining_after")),
            "remarks": _s(t.get("remarks")), "source": "Payroll"})
    # 3) manual register entries
    q: Dict[str, Any] = {"company_id": company_id}
    if per["custom"]:
        q["date"] = {"$gte": per["from"], "$lte": per["to"]}
    else:
        q["wage_period"] = {"$in": per["months"]}
    async for e in db.cwr_form_c.find(q, {"_id": 0}):
        u = by_uid.get(e.get("user_id"))
        if not u:
            continue
        rows.append({
            "employee_code": e.get("employee_code"),
            "name": e.get("employee_name"), "wage_period": per["label"],
            "date": _dmy(e.get("date")), "dtype": _s(e.get("dtype")),
            "reason": _s(e.get("reason")),
            "advance_amount": _f(e.get("advance_amount")),
            "recovery_amount": _f(e.get("recovery_amount")),
            "fine_amount": _f(e.get("fine_amount")),
            "other_amount": _f(e.get("other_amount")),
            "balance": "", "remarks": _s(e.get("remarks")),
            "source": "Manual", "entry_id": e.get("entry_id")})
    rows.sort(key=lambda r: (str(r.get("employee_code") or "").zfill(8),
                             _s(r.get("date"))[6:10] + _s(r.get("date"))[3:5]
                             + _s(r.get("date"))[0:2]))
    for i, r in enumerate(rows, 1):
        r["sr"] = i
        r["total_deduction"] = round(_f(r["recovery_amount"])
                                     + _f(r["fine_amount"])
                                     + _f(r["other_amount"]), 2)
    cols = [("sr", "Sr."), ("employee_code", "Emp Code"),
            ("name", "Employee Name"), ("wage_period", "Wage Period"),
            ("date", "Date"), ("dtype", "Type of Deduction"),
            ("reason", "Reason / Particulars"),
            ("advance_amount", "Advance / Loan Amt"),
            ("recovery_amount", "Recovery Amt"), ("fine_amount", "Fine Amt"),
            ("other_amount", "Other Deduction"),
            ("total_deduction", "Total Deduction"),
            ("balance", "Balance Adv / Loan"), ("source", "Source"),
            ("remarks", "Remarks")]
    totals = {"name": "TOTAL"}
    for k in ("advance_amount", "recovery_amount", "fine_amount",
              "other_amount", "total_deduction"):
        totals[k] = round(sum(_f(r.get(k)) for r in rows), 2)
    return cols, rows, totals


async def _form_d(company_id, per, flt, res):
    emps = await _emps(company_id, flt, res)
    att = await _att_summary(company_id, per)
    all_days = sorted({d for a in att.values() for d in a["days"]})
    if per["custom"]:
        all_days = [d for d in all_days if per["from"] <= d <= per["to"]]
    # Iter 687 (user request) — WO auto-fill: employee's week-off from the
    # Employee Master (weekly_off_days_override) wins; otherwise the firm's
    # attendance-policy weekly_off_days from the Firm Master.
    comp = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "attendance_policy": 1})
    firm_wo = {int(x) for x in ((comp or {}).get("attendance_policy") or
                                {}).get("weekly_off_days") or []}
    rows = []
    for i, u in enumerate(emps, 1):
        a = att.get(u["user_id"])
        if not a:
            continue
        _ov = u.get("weekly_off_days_override")
        wo_days = ({int(x) for x in _ov} if isinstance(_ov, list) and _ov
                   else firm_wo)
        row = {"sr": i, "employee_code": u.get("employee_code"),
               "name": u.get("name"),
               "designation": _s(u.get("designation"))}
        wo_fill = 0
        for d in all_days:
            st = (a["days"].get(d) or {}).get("st") or ""
            if not st and wo_days:
                try:
                    if datetime.strptime(d, "%Y-%m-%d").weekday() in wo_days:
                        st = "WO"
                        wo_fill += 1
                except ValueError:
                    pass
            row[d] = st
        row.update({
            "t_present": a.get("P", 0) + round(a.get("HD", 0) * 0.5, 1),
            "t_absent": a.get("A", 0), "t_wo": a.get("WO", 0) + wo_fill,
            "t_holiday": a.get("H", 0), "t_leave": a.get("L", 0),
            "t_paid_days": _f(a.get("present_days")),
            "t_hours": _f(a.get("worked_hours")),
            "t_ot": _f(a.get("ot_hours"))})
        rows.append(row)
    for i, r in enumerate(rows, 1):
        r["sr"] = i
    cols = ([("sr", "Sr."), ("employee_code", "Code"),
             ("name", "Employee Name"), ("designation", "Designation")]
            + [(d, d[8:10]) for d in all_days]
            + [("t_present", "Present"), ("t_absent", "Absent"),
               ("t_wo", "W/Off"), ("t_holiday", "Holiday"),
               ("t_leave", "Leave"), ("t_paid_days", "Paid Days"),
               ("t_hours", "Hours"), ("t_ot", "OT Hrs")])
    totals = {"name": "TOTAL"}
    for k in ("t_present", "t_absent", "t_wo", "t_holiday", "t_leave",
              "t_paid_days", "t_hours", "t_ot"):
        totals[k] = round(sum(_f(r.get(k)) for r in rows), 2)
    return cols, rows, totals


_BUILDERS = {"a": _form_a, "b": _form_b, "c": _form_c, "d": _form_d}


def _flt(contractor_id, work_order_id, principal_employer_id, site,
         department, employee_type, employee_ids, search):
    return {"contractor_id": _s(contractor_id),
            "work_order_id": _s(work_order_id),
            "principal_employer_id": _s(principal_employer_id),
            "site": _s(site), "department": _s(department),
            "employee_type": _s(employee_type),
            "employee_ids": _s(employee_ids), "search": _s(search)}


async def _subtitle(company_id, per, flt, res) -> str:
    c = await db.companies.find_one({"company_id": company_id},
                                    {"_id": 0, "name": 1, "logo_base64": 1})
    bits = [c.get("name") or "", f"Wage Period: {per['label']}"]
    if flt["contractor_id"]:
        ctr = res["ctrs"].get(flt["contractor_id"])
        if ctr:
            bits.append(f"Contractor: {ctr.get('name')}")
    if flt["work_order_id"]:
        wo = res["wos"].get(flt["work_order_id"])
        if wo:
            bits.append(f"WO: {wo.get('wo_number')}")
    if flt["site"]:
        bits.append(f"Site: {flt['site']}")
    return " · ".join(b for b in bits if b), c


@router.get("/register/{kind}")
async def register_json(kind: str, company_id: Optional[str] = None,
                        month: str = "", from_date: str = "",
                        to_date: str = "", contractor_id: str = "",
                        work_order_id: str = "",
                        principal_employer_id: str = "", site: str = "",
                        department: str = "", employee_type: str = "",
                        employee_ids: str = "", search: str = "",
                        token: Optional[str] = Query(None),
                        authorization: Optional[str] = Header(None)):
    authorization = authorization or (f"Bearer {token}" if token else None)
    fmt = ""
    for ext in ("xlsx", "pdf"):
        if kind.endswith(f".{ext}"):
            kind, fmt = kind[: -len(ext) - 1], ext
    kind = kind.lower().replace("form-", "")
    if kind not in _BUILDERS:
        raise HTTPException(status_code=404, detail="Unknown register")
    _admin, company_id = await _adm(authorization, company_id)
    per = _period(month, from_date, to_date)
    flt = _flt(contractor_id, work_order_id, principal_employer_id, site,
               department, employee_type, employee_ids, search)
    res = await _resolve(company_id)
    cols, rows, totals = await _BUILDERS[kind](company_id, per, flt, res)
    sub, comp = await _subtitle(company_id, per, flt, res)
    title = FORM_TITLES[kind]
    status = await _status_doc(company_id, kind, per["label"])
    # Iter 687 (user request) — Form C empty-state line.
    empty_note = ""
    if kind == "c" and not rows:
        try:
            _ml = datetime.strptime(per["months"][0], "%Y-%m").strftime("%B-%Y")
        except ValueError:
            _ml = per["label"]
        empty_note = (f"For the Month of {_ml} No Deduction has been done "
                      f"with Any Employee")
    if fmt:
        columns = [{"key": k, "label": lb} for k, lb in cols]
        form_line = (f"{FRAMEWORK} · Prepared: "
                     f"{status.get('prepared_by') or '—'} · Verified: "
                     f"{status.get('verified_by') or '—'} · Approved: "
                     f"{status.get('approved_by') or '—'} · Status: "
                     f"{(status.get('status') or 'draft').upper()}")
        gen = f"{sub} · Generated {datetime.now():%d-%m-%Y}"
        if fmt == "xlsx":
            # Iter 687 (user request) — Form B figures & Form D marks/S.No./
            # Emp Code CENTRED in Excel too.
            buf = register_xlsx(title, gen, columns, rows, totals,
                                form_line=form_line,
                                num_center=kind in ("b", "d"))
            mt = ("application/vnd.openxmlformats-officedocument"
                  ".spreadsheetml.sheet")
        else:
            buf = register_pdf(title, gen, columns, rows, totals,
                               comp.get("logo_base64"), form_line=form_line,
                               empty_note=empty_note or None)
            mt = "application/pdf"
        fn = f"{title.split('—')[0].strip().replace(' ', '_')}_{per['label'].replace(' ', '_')}.{fmt}"
        return StreamingResponse(buf, media_type=mt, headers={
            "Content-Disposition": f'attachment; filename="{fn}"'})
    return {"title": title, "subtitle": sub, "period": per["label"],
            "framework": FRAMEWORK, "empty_note": empty_note,
            "columns": [{"key": k, "label": lb} for k, lb in cols],
            "rows": rows, "totals": totals, "status": status}
