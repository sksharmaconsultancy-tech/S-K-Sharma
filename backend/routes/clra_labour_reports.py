"""Iter 479 — CLRA / Labour Code Registers (Phase 1, user spec).

NEW registers that did NOT exist (existing reports are reused, not
duplicated — Muster Roll / Attendance / Wage / OT / Bonus / Gratuity /
PF / ESIC / F&F all live in their own modules):

  contractor-register      — full statutory Contractor Register (from the
                             new Contractor Master, with licence/agreement
                             expiry status and live labour counts)
  principal-employer       — Principal Employer Register (Firm Master)
  contract-labour-register — CLRA employee register with contractor,
                             UAN/ESIC/Aadhaar/bank, DOJ/DOE/rejoin, status
  pt-register              — Professional Tax Register (month, slab, amount)
  rejoin-history           — Employee Rejoin History (service gaps, counts)
  compliance-dashboard     — headline compliance metrics + exceptions

  GET /api/admin/clra-reports/list | /{kind}[.xlsx|.pdf]  (month param)

Follows the same delegation/export pattern as govt_audit_reports so the
Report Hub picks these up with Excel / PDF / Email support.
"""
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from server import db, get_user_from_token, require_role  # noqa: E402
from utils.register_export import register_pdf, register_xlsx  # noqa: E402
from routes.labour_statistics import (_dt, _f, _users, _company,  # noqa: E402
                                      _run_rows)

router = APIRouter(prefix="/api/admin/clra-reports", tags=["clra-reports"])


async def _adm(authorization, company_id):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    return company_id


def _mlabel(month: str) -> str:
    try:
        return datetime(int(month[:4]), int(month[5:7]), 1).strftime("%B %Y")
    except (TypeError, ValueError):
        return str(month or "")


# ---------------------------------------------------------------------------
# 1. Contractor Register
# ---------------------------------------------------------------------------

async def _contractor_register(company_id, month, ctx=None):
    from routes.contractors import _active_labour_map, _renewal, \
        _seed_from_firm_master
    await _seed_from_firm_master(company_id)
    labour = await _active_labour_map(company_id)
    out = []
    async for c in db.contractors.find(
            {"company_id": company_id}, {"_id": 0}).sort("name", 1):
        c = _renewal(c)
        status = str(c.get("status") or "active").title()
        if c["licence_expired"]:
            status += " · LICENCE EXPIRED"
        elif c["licence_expiring_soon"]:
            status += " · Licence expiring soon"
        out.append({
            "code": c.get("code"), "name": c.get("name"),
            "address": c.get("address"), "mobile": c.get("mobile"),
            "email": c.get("email"), "pan": c.get("pan"),
            "gstin": c.get("gstin"), "epf_code": c.get("epf_code"),
            "esic_code": c.get("esic_code"),
            "licence_no": c.get("licence_no"),
            "licence_issue": c.get("licence_issue_date"),
            "licence_expiry": c.get("licence_expiry_date"),
            "deposit": _f(c.get("security_deposit")),
            "max_labour": int(_f(c.get("max_labour"))),
            "active_labour": labour.get(
                str(c.get("name") or "").strip().upper(), 0),
            "nature": c.get("nature_of_work"),
            "agreement_no": c.get("agreement_no"),
            "agreement_start": c.get("agreement_start"),
            "agreement_end": c.get("agreement_end"),
            "renewal_due": c.get("renewal_due_date"),
            "status": status})
    cols = [("code", "Code"), ("name", "Contractor Name"),
            ("address", "Address"), ("mobile", "Mobile"),
            ("email", "Email"), ("pan", "PAN"), ("gstin", "GSTIN"),
            ("epf_code", "EPF Code"), ("esic_code", "ESIC Code"),
            ("licence_no", "Labour Licence No."),
            ("licence_issue", "Licence Issue"),
            ("licence_expiry", "Licence Expiry"),
            ("deposit", "Security Deposit"),
            ("max_labour", "Max Labour"),
            ("active_labour", "Active Labour"),
            ("nature", "Nature of Work"),
            ("agreement_no", "Agreement No."),
            ("agreement_start", "Agreement Start"),
            ("agreement_end", "Agreement End"),
            ("renewal_due", "Renewal Due"),
            ("status", "Status")]
    return "Contractor Register", cols, out, None


# ---------------------------------------------------------------------------
# 2. Principal Employer Register
# ---------------------------------------------------------------------------

async def _principal_employer(company_id, month, ctx=None):
    c = await _company(company_id) or {}
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0}) or {}
    h = fm.get("header") or {}
    ra = fm.get("registered_address") or {}
    epf = fm.get("epf") or {}
    esi = fm.get("esi") or {}
    st = fm.get("settings") or {}
    cps = fm.get("contact_persons") or []
    occ = next((p.get("name") for p in cps
                if "occupier" in str(p.get("role") or "").lower()), "")
    emp = next((p.get("name") for p in cps
                if "employer" in str(p.get("role") or "").lower()), "")
    addr = ", ".join([str(ra.get(k) or "") for k in
                      ("address_1", "address_2", "city", "state",
                       "pin_code") if ra.get(k)]) or c.get("address") or ""
    n_ctr = await db.contractors.count_documents({"company_id": company_id})
    max_cl = sum([_f(x.get("max_labour"))
                  async for x in db.contractors.find(
                      {"company_id": company_id},
                      {"_id": 0, "max_labour": 1})])
    row = {
        "registration_no": st.get("clra_registration_no")
        or st.get("registration_no") or "",
        "establishment": fm.get("company_name") or c.get("name"),
        "address": addr,
        "occupier": occ, "employer": emp or c.get("name"),
        "factory_licence": st.get("factory_licence_no")
        or st.get("factory_licence") or "",
        "pan": st.get("pan") or (fm.get("bank") or {}).get("pan") or "",
        "gst": st.get("gstin") or st.get("gst") or "",
        "epf_code": epf.get("establishment_code") or epf.get("code") or "",
        "esic_code": esi.get("employer_code") or esi.get("code") or "",
        "max_contract_labour": int(max_cl),
        "contractors": n_ctr,
        "nature_of_industry": h.get("category")
        or c.get("nature_of_business") or "",
    }
    cols = [("registration_no", "Registration No."),
            ("establishment", "Establishment Name"),
            ("address", "Address"), ("occupier", "Occupier"),
            ("employer", "Employer"),
            ("factory_licence", "Factory Licence"),
            ("pan", "PAN"), ("gst", "GST"),
            ("epf_code", "EPF Code"), ("esic_code", "ESIC Code"),
            ("max_contract_labour", "Max Contract Labour"),
            ("contractors", "Registered Contractors"),
            ("nature_of_industry", "Nature of Industry")]
    return "Principal Employer Register", cols, [row], None


# ---------------------------------------------------------------------------
# 3. Contract Labour Register
# ---------------------------------------------------------------------------

async def _contract_labour(company_id, month, ctx=None):
    out = []
    async for u in db.users.find(
        {"company_id": company_id, "role": "employee",
         "contractor_name": {"$nin": [None, ""]}},
        {"_id": 0, "employee_code": 1, "name": 1, "contractor_name": 1,
         "skill_category": 1, "skill": 1, "employee_type": 1,
         "designation": 1, "uan_no": 1, "esi_ip_no": 1, "aadhaar": 1,
         "aadhaar_no": 1, "bank_account_no": 1, "bank_ifsc": 1,
         "doj": 1, "exit_date": 1, "resign_date": 1, "rejoin_date": 1,
         "employment_history": 1, "employment_status": 1, "active": 1},
    ):
        ctr = str(u.get("contractor_name") or "").strip()
        if not ctr:
            continue
        hist = u.get("employment_history") or []
        bank = ((u.get("bank_account_no") or "")
                and f"{u.get('bank_account_no')} / {u.get('bank_ifsc') or ''}")
        out.append({
            "employee_code": u.get("employee_code"),
            "name": u.get("name"),
            "contractor": ctr,
            "skill": u.get("skill_category") or u.get("skill") or "",
            "emp_type": u.get("employee_type") or "",
            "trade": u.get("designation") or "",
            "uan": u.get("uan_no") or "",
            "esic_ip": u.get("esi_ip_no") or "",
            "aadhaar": u.get("aadhaar") or u.get("aadhaar_no") or "",
            "bank": bank or "",
            "doj": u.get("doj") or "",
            "doe": u.get("exit_date") or u.get("resign_date") or "",
            "rejoin": u.get("rejoin_date")
            or (hist and (hist[-1].get("rejoin_date") or "")) or "",
            "status": str(u.get("employment_status")
                          or ("active" if u.get("active") else
                              "separated")).title()})
    out.sort(key=lambda r: (str(r["contractor"]).upper(),
                            str(r.get("employee_code") or "").zfill(8)))
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("contractor", "Contractor"), ("skill", "Skill Category"),
            ("emp_type", "Employment Type"), ("trade", "Trade/Designation"),
            ("uan", "UAN"), ("esic_ip", "ESIC IP"),
            ("aadhaar", "Aadhaar"), ("bank", "Bank A/c / IFSC"),
            ("doj", "DOJ"), ("doe", "DOE"), ("rejoin", "Rejoin Date"),
            ("status", "Current Status")]
    return "Contract Labour Register", cols, out, None


# ---------------------------------------------------------------------------
# 4. Professional Tax Register
# ---------------------------------------------------------------------------

async def _pt_register(company_id, month, ctx=None):
    c = await _company(company_id) or {}
    state = c.get("state") or ""
    rows_by_uid = await _run_rows(company_id, month)
    users = {u["user_id"]: u for u in await _users(company_id)}
    out = []
    for uid, r in rows_by_uid.items():
        pt = _f(r.get("pt"))
        if pt <= 0:
            continue
        u = users.get(uid) or {}
        gross = _f(r.get("gross_paid"))
        out.append({"employee_code": u.get("employee_code"),
                    "name": u.get("name"), "state": state,
                    "gross": gross,
                    "slab": f"Gross {gross:,.0f}",
                    "pt": pt, "month": _mlabel(month),
                    "challan": ""})
    out.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("state", "PT State"), ("gross", "Gross Wages"),
            ("slab", "PT Slab"), ("pt", "PT Amount"),
            ("month", "Month"), ("challan", "Challan No.")]
    totals = {"name": "TOTAL", "pt": round(sum(r["pt"] for r in out), 2)}
    return "Professional Tax Register", cols, out, totals


# ---------------------------------------------------------------------------
# 5. Employee Rejoin History
# ---------------------------------------------------------------------------

async def _rejoin_history(company_id, month, ctx=None):
    out = []
    async for u in db.users.find(
        {"company_id": company_id, "role": "employee",
         "employment_history.0": {"$exists": True}},
        {"_id": 0, "employee_code": 1, "name": 1, "doj": 1,
         "employment_history": 1, "employment_status": 1, "active": 1},
    ):
        hist = u.get("employment_history") or []
        last = hist[-1]
        prev_doj = last.get("doj") or ""
        prev_lwd = (last.get("exit_date") or last.get("lwd")
                    or last.get("resign_date") or "")
        rejoin = last.get("rejoin_date") or u.get("doj") or ""
        gap = ""
        d1, d2 = _dt(prev_lwd), _dt(rejoin)
        if d1 and d2:
            gap = max((d2 - d1).days, 0)
        out.append({"employee_code": u.get("employee_code"),
                    "name": u.get("name"),
                    "prev_doj": prev_doj, "prev_lwd": prev_lwd,
                    "rejoin": rejoin, "gap_days": gap,
                    "employments": len(hist) + 1,
                    "status": str(u.get("employment_status")
                                  or ("active" if u.get("active")
                                      else "separated")).title()})
    out.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("prev_doj", "Previous DOJ"), ("prev_lwd", "Previous LWD"),
            ("rejoin", "Rejoin Date"), ("gap_days", "Service Gap (days)"),
            ("employments", "Employment Count"),
            ("status", "Current Status")]
    return "Employee Rejoin History", cols, out, None


# ---------------------------------------------------------------------------
# 6. Compliance Dashboard
# ---------------------------------------------------------------------------

async def _compliance_dashboard(company_id, month, ctx=None):
    users = await db.users.find(
        {"company_id": company_id, "role": "employee"},
        {"_id": 0, "employee_code": 1, "active": 1, "employment_status": 1,
         "contractor_name": 1, "uan_no": 1, "esi_ip_no": 1, "doj": 1,
         "salary_monthly": 1, "compliance_gross": 1},
    ).to_list(200000)
    active = [u for u in users if u.get("active")
              or str(u.get("employment_status") or "") == "active"]
    contract = [u for u in active
                if str(u.get("contractor_name") or "").strip()]
    esic_elig = [u for u in active
                 if _f(u.get("compliance_gross")
                       or u.get("salary_monthly")) <= 21000]
    bonus_elig = [u for u in active
                  if _f(u.get("compliance_gross")
                        or u.get("salary_monthly")) <= 21000]
    today = date.today()
    grat_elig = [u for u in active if _dt(u.get("doj"))
                 and (today - _dt(u.get("doj"))).days >= 5 * 365]
    miss_uan = [u for u in active if not str(u.get("uan_no") or "").strip()]
    miss_esic = [u for u in esic_elig
                 if not str(u.get("esi_ip_no") or "").strip()]
    soon = (today + timedelta(days=60)).isoformat()
    lic_exp = await db.contractors.count_documents(
        {"company_id": company_id,
         "licence_expiry_date": {"$gt": "", "$lte": soon}})
    agr_exp = await db.contractors.count_documents(
        {"company_id": company_id,
         "agreement_end": {"$gt": "", "$lte": soon}})
    run = await db.compliance_salary_runs.find_one(
        {"company_id": company_id, "month": month}, {"_id": 0, "month": 1})
    rejoined = await db.users.count_documents(
        {"company_id": company_id,
         "employment_history.0": {"$exists": True}})

    def row(metric, value, status="OK", note=""):
        return {"metric": metric, "value": value,
                "status": status, "note": note}
    out = [
        row("Active Employees", len(active)),
        row("Active Contract Labour", len(contract)),
        row("PF Eligible (UAN present)",
            len([u for u in active if str(u.get("uan_no") or "").strip()])),
        row("ESIC Eligible (gross ≤ ₹21,000)", len(esic_elig)),
        row("Bonus Eligible (wages ≤ ₹21,000)", len(bonus_elig)),
        row("Gratuity Eligible (5+ yrs service)", len(grat_elig)),
        row("Rejoined Employees (with history)", rejoined),
        row("Missing UAN", len(miss_uan),
            "ATTENTION" if miss_uan else "OK",
            ", ".join(str(u.get("employee_code") or "") for u in
                      miss_uan[:10])),
        row("Missing ESIC IP (eligible staff)", len(miss_esic),
            "ATTENTION" if miss_esic else "OK",
            ", ".join(str(u.get("employee_code") or "") for u in
                      miss_esic[:10])),
        row("Contractor Licences expiring ≤60 days", lic_exp,
            "ATTENTION" if lic_exp else "OK"),
        row("Contractor Agreements expiring ≤60 days", agr_exp,
            "ATTENTION" if agr_exp else "OK"),
        row(f"Compliance Salary processed for {_mlabel(month)}",
            "YES" if run else "NO",
            "OK" if run else "PENDING"),
    ]
    cols = [("metric", "Compliance Metric"), ("value", "Value"),
            ("status", "Status"), ("note", "Details / Exceptions")]
    return "Compliance Dashboard", cols, out, None


_CLRA = {
    "contractor-register": _contractor_register,
    "principal-employer": _principal_employer,
    "contract-labour-register": _contract_labour,
    "pt-register": _pt_register,
    "rejoin-history": _rejoin_history,
    "compliance-dashboard": _compliance_dashboard,
}
_TITLES = {
    "contractor-register": "Contractor Register",
    "principal-employer": "Principal Employer Register",
    "contract-labour-register": "Contract Labour Register",
    "pt-register": "Professional Tax Register",
    "rejoin-history": "Employee Rejoin History",
    "compliance-dashboard": "Compliance Dashboard",
}


@router.get("/list")
async def clra_list(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    return {"reports": [{"kind": k, "title": t}
                        for k, t in _TITLES.items()]}


@router.get("/{kind}")
async def clra_json(kind: str, company_id: Optional[str] = None,
                    month: Optional[str] = None,
                    authorization: Optional[str] = Header(None)):
    for ext in ("xlsx", "pdf"):
        if kind.endswith(f".{ext}"):
            return await _clra_exp(kind[: -len(ext) - 1], company_id,
                                   month, authorization, ext)
    if kind not in _CLRA:
        raise HTTPException(status_code=404, detail="Unknown report")
    company_id = await _adm(authorization, company_id)
    month = month or date.today().strftime("%Y-%m")
    title, cols, rows, totals = await _CLRA[kind](company_id, month)
    return {"title": title, "subtitle": _mlabel(month),
            "columns": [{"key": k, "label": lb} for k, lb in cols],
            "rows": rows, "totals": totals}


async def _clra_exp(kind, company_id, month, authorization, fmt):
    if kind not in _CLRA:
        raise HTTPException(status_code=404, detail="Unknown report")
    company_id = await _adm(authorization, company_id)
    month = month or date.today().strftime("%Y-%m")
    c = await _company(company_id)
    title, cols, rows, totals = await _CLRA[kind](company_id, month)
    columns = [{"key": k, "label": lb} for k, lb in cols]
    sub = (f"{c.get('name')} · {_mlabel(month)} · "
           f"Generated {datetime.now():%d-%m-%Y}")
    if fmt == "xlsx":
        buf = register_xlsx(title, sub, columns, rows, totals)
        mt = ("application/vnd.openxmlformats-officedocument"
              ".spreadsheetml.sheet")
    else:
        buf = register_pdf(title, sub, columns, rows, totals,
                           c.get("logo_base64"))
        mt = "application/pdf"
    fn = f"{title.replace(' ', '_')}.{fmt}"
    return StreamingResponse(buf, media_type=mt, headers={
        "Content-Disposition": f'attachment; filename="{fn}"'})
