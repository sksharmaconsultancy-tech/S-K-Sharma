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
    c = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "state": 1}) or {}
    fm = await db.firm_masters.find_one(
        {"company_id": company_id},
        {"_id": 0, "registered_address": 1}) or {}
    state = (c.get("state")
             or (fm.get("registered_address") or {}).get("state") or "")
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


# ---------------------------------------------------------------------------
# 7. PF Register (Iter 480 — Phase 2, user spec)
# ---------------------------------------------------------------------------

async def _pf_register(company_id, month, ctx=None):
    rows_by_uid = await _run_rows(company_id, month)
    users = {u["user_id"]: u for u in await _users(company_id)}
    out = []
    for uid, r in rows_by_uid.items():
        if not (_f(r.get("pf_employee")) or _f(r.get("pf_wages"))):
            continue
        u = users.get(uid) or {}
        pf_w = _f(r.get("pf_wages"))
        eps_w = 0 if r.get("eps_disabled") else min(pf_w, 15000)
        edli_w = min(pf_w, 15000)
        ncp = max(_f(r.get("month_days")) - _f(r.get("present_days")), 0)
        hist = []  # rejoin date from users master
        out.append({
            "employee_code": u.get("employee_code") or r.get("employee_code"),
            "name": u.get("name") or r.get("name"),
            "uan": r.get("uan_no") or u.get("uan_no") or "",
            "pf_no": r.get("pf_no") or u.get("pf_no") or "",
            "pf_wages": pf_w, "eps_wages": eps_w,
            "epf_ee": _f(r.get("pf_employee")),
            "vpf": _f(r.get("vpf_amount")),
            "eps_er": _f(r.get("pf_employer_eps")),
            "epf_er": _f(r.get("pf_employer_epf")),
            "er_total": _f(r.get("pf_employer_total")),
            "edli_wages": edli_w,
            "edli": round(edli_w * 0.005, 2),
            "ncp_days": int(round(ncp)),
            "doj": u.get("doj") or "",
            "doe": u.get("exit_date") or u.get("resign_date") or "",
            "rejoin": (u.get("rejoin_date") or
                       (hist and hist[-1].get("rejoin_date")) or "")})
    out.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("uan", "UAN"), ("pf_no", "PF No."),
            ("pf_wages", "PF Wages"), ("eps_wages", "EPS Wages"),
            ("epf_ee", "EPF Contribution (EE)"), ("vpf", "VPF"),
            ("eps_er", "EPS Contribution (ER)"),
            ("epf_er", "EPF Contribution (ER)"),
            ("er_total", "Employer Total"),
            ("edli_wages", "EDLI Wages"), ("edli", "EDLI (0.5%)"),
            ("ncp_days", "NCP Days"), ("doj", "DOJ"), ("doe", "DOE"),
            ("rejoin", "Rejoin Date")]
    totals = {"name": "TOTAL"}
    for k in ("pf_wages", "epf_ee", "vpf", "eps_er", "epf_er", "er_total",
              "edli"):
        totals[k] = round(sum(r[k] for r in out), 2)
    return "PF Register", cols, out, totals


# ---------------------------------------------------------------------------
# 8. ESIC Register (Iter 480 — Phase 2, user spec)
# ---------------------------------------------------------------------------

def _esic_periods(month: str):
    y, m = int(month[:4]), int(month[5:7])
    if 4 <= m <= 9:
        return (f"Apr {y} – Sep {y}", f"Jan {y + 1} – Jun {y + 1}")
    start_y = y if m >= 10 else y - 1
    return (f"Oct {start_y} – Mar {start_y + 1}",
            f"Jul {start_y + 1} – Dec {start_y + 1}")


async def _esic_register(company_id, month, ctx=None):
    rows_by_uid = await _run_rows(company_id, month)
    users = {u["user_id"]: u for u in await _users(company_id)}
    cp, bp = _esic_periods(month)
    out = []
    for uid, r in rows_by_uid.items():
        if not (_f(r.get("esic_employee")) or _f(r.get("esic_employer"))):
            continue
        u = users.get(uid) or {}
        out.append({
            "employee_code": u.get("employee_code") or r.get("employee_code"),
            "name": u.get("name") or r.get("name"),
            "esic_ip": r.get("esi_ip_no") or u.get("esi_ip_no") or "",
            "days": _f(r.get("present_days")),
            "esic_wages": _f(r.get("esic_wage_base"))
            or _f(r.get("gross_paid")),
            "ee": _f(r.get("esic_employee")),
            "er": _f(r.get("esic_employer")),
            "total": round(_f(r.get("esic_employee"))
                           + _f(r.get("esic_employer")), 2),
            "cp": cp, "bp": bp,
            "tic": "TIC" if not (r.get("esi_ip_no")
                                 or u.get("esi_ip_no")) else "Regular IP"})
    out.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("esic_ip", "ESIC IP"), ("days", "Days"),
            ("esic_wages", "ESIC Wages"),
            ("ee", "Employee Contribution (0.75%)"),
            ("er", "Employer Contribution (3.25%)"), ("total", "Total"),
            ("cp", "Contribution Period"), ("bp", "Benefit Period"),
            ("tic", "TIC Status")]
    totals = {"name": "TOTAL"}
    for k in ("ee", "er", "total"):
        totals[k] = round(sum(r[k] for r in out), 2)
    return "ESIC Register", cols, out, totals


# ---------------------------------------------------------------------------
# 9. LWF Register (Iter 480 — Phase 2, user: "build for other states";
#    Rajasthan has no LWF Act)
# ---------------------------------------------------------------------------

_LWF_SLABS = {
    # state → EE ₹, ER ₹, contribution months (calendar month numbers)
    "maharashtra": (12, 36, [6, 12]),
    "gujarat": (6, 12, [6, 12]),
    "karnataka": (20, 40, [12]),
    "tamil nadu": (10, 20, [12]),
    "madhya pradesh": (10, 30, [6, 12]),
    "delhi": (0.75, 2.25, [6, 12]),
    "haryana": (31, 62, list(range(1, 13))),
    "punjab": (5, 20, list(range(1, 13))),
    "chandigarh": (5, 20, list(range(1, 13))),
    "west bengal": (3, 15, [6, 12]),
    "andhra pradesh": (30, 70, [12]),
    "telangana": (2, 5, [12]),
    "kerala": (45, 45, list(range(1, 13))),
    "goa": (60, 180, [6, 12]),
    "chhattisgarh": (15, 45, [6, 12]),
    "odisha": (10, 20, [6, 12]),
}
_LWF_DUE = {6: "15 July", 12: "15 January"}


async def _lwf_register(company_id, month, ctx=None):
    c = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "state": 1}) or {}
    fm = await db.firm_masters.find_one(
        {"company_id": company_id},
        {"_id": 0, "registered_address": 1}) or {}
    state = str(c.get("state")
                or (fm.get("registered_address") or {}).get("state")
                or "").strip()
    slab = _LWF_SLABS.get(state.lower())
    title = f"Labour Welfare Fund Register — {state or 'State not set'}"
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("state", "State"), ("month", "Month"),
            ("ee", "Employee Share"), ("er", "Employer Share"),
            ("total", "Total"), ("due", "Due Date"),
            ("challan", "Challan No.")]
    if not slab:
        return (f"{title} (LWF NOT APPLICABLE)", cols, [], None)
    ee, er, due_months = slab
    m = int(month[5:7])
    if m not in due_months:
        nxt = min([x for x in due_months if x >= m] or [due_months[0]])
        return (f"{title} — {_mlabel(month)} is not a contribution month "
                f"(next: month {nxt:02d})", cols, [], None)
    rows_by_uid = await _run_rows(company_id, month)
    users = {u["user_id"]: u for u in await _users(company_id)}
    due = _LWF_DUE.get(m, "As per state rules")
    out = []
    ids = rows_by_uid.keys() or [
        u["user_id"] for u in users.values() if u.get("active")]
    for uid in ids:
        u = users.get(uid) or {}
        out.append({"employee_code": u.get("employee_code"),
                    "name": u.get("name"), "state": state,
                    "month": _mlabel(month), "ee": ee, "er": er,
                    "total": round(ee + er, 2), "due": due, "challan": ""})
    out.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
    totals = {"name": "TOTAL",
              "ee": round(sum(r["ee"] for r in out), 2),
              "er": round(sum(r["er"] for r in out), 2),
              "total": round(sum(r["total"] for r in out), 2)}
    return title, cols, out, totals


# ---------------------------------------------------------------------------
# 10. Leave Register (Iter 480 — Phase 2, user spec): EL ledger for the
#     financial year up to the selected month.
#       Earned  = 1 EL per 20 days worked (Factories Act s.79 style)
#       Availed = approved leaves in the FY window
#       Closing = Opening + Earned − Availed − Encashed
# ---------------------------------------------------------------------------

async def _leave_register(company_id, month, ctx=None):
    y, m = int(month[:4]), int(month[5:7])
    fy_start = f"{y if m >= 4 else y - 1}-04"
    months = []
    cy, cm = int(fy_start[:4]), 4
    while f"{cy:04d}-{cm:02d}" <= month:
        months.append(f"{cy:04d}-{cm:02d}")
        cm += 1
        if cm > 12:
            cm, cy = 1, cy + 1
    days_worked: Dict[str, float] = {}
    for mo in months:
        for uid, r in (await _run_rows(company_id, mo)).items():
            days_worked[uid] = days_worked.get(uid, 0) \
                + _f(r.get("present_days"))
    availed: Dict[str, float] = {}
    async for lv in db.leaves.find(
            {"company_id": company_id, "status": "approved",
             "from_date": {"$gte": f"{fy_start}-01",
                           "$lte": f"{month}-31"}},
            {"_id": 0, "user_id": 1, "from_date": 1, "to_date": 1}):
        d1, d2 = _dt(lv.get("from_date")), _dt(lv.get("to_date"))
        n = ((d2 - d1).days + 1) if d1 and d2 else 1
        availed[lv["user_id"]] = availed.get(lv["user_id"], 0) + n
    opening: Dict[str, float] = {}
    async for _u in db.users.find(
            {"company_id": company_id, "role": "employee"},
            {"_id": 0, "user_id": 1, "leave_opening_balance": 1}):
        opening[_u["user_id"]] = _f(_u.get("leave_opening_balance"))
    users = {u["user_id"]: u for u in await _users(company_id)}
    out = []
    for uid in set(list(days_worked) + list(availed)):
        u = users.get(uid) or {}
        op = opening.get(uid, 0)
        earned = int(days_worked.get(uid, 0) // 20)
        av = availed.get(uid, 0)
        closing = round(op + earned - av, 1)
        out.append({"employee_code": u.get("employee_code"),
                    "name": u.get("name"), "opening": op,
                    "days_worked": round(days_worked.get(uid, 0), 1),
                    "earned": earned, "availed": av, "encashed": 0,
                    "carry_forward": max(closing, 0), "closing": closing})
    out.sort(key=lambda r: str(r.get("employee_code") or "").zfill(8))
    cols = [("employee_code", "Emp Code"), ("name", "Employee Name"),
            ("opening", "Opening Balance"),
            ("days_worked", "Days Worked (FY)"),
            ("earned", "Earned (1/20 days)"), ("availed", "Availed"),
            ("encashed", "Encashed"), ("carry_forward", "Carry Forward"),
            ("closing", "Closing Balance")]
    return (f"Leave Register (EL Ledger — FY from {fy_start})",
            cols, out, None)


# ---------------------------------------------------------------------------
# Iter 486 (Phase 3) — Inspection Register + Digital Document Register
# ---------------------------------------------------------------------------

async def _inspection_register(company_id, month, ctx=None):
    """Cumulative register of statutory inspections (entries maintained via
    the Report Hub's ➕ Inspection Entry form)."""
    rows = []
    async for e in db.clra_inspections.find(
            {"company_id": company_id}, {"_id": 0}).sort("date", -1):
        rows.append({
            "date": e.get("date") or "",
            "inspector": e.get("inspector_name") or "",
            "designation": e.get("designation") or "",
            "authority": e.get("authority") or "",
            "observations": e.get("observations") or "",
            "action_taken": e.get("action_taken") or "",
            "status": (e.get("status") or "open").upper(),
        })
    cols = [("date", "Date of Inspection"),
            ("inspector", "Name of Inspector"),
            ("designation", "Designation"),
            ("authority", "Authority / Department"),
            ("observations", "Observations / Remarks"),
            ("action_taken", "Action Taken"),
            ("status", "Status")]
    return ("Inspection Register", cols, rows, None)


async def _document_register(company_id, month, ctx=None):
    """Every statutory document the firm holds (Firm Master compliance
    documents + contractor licences) with live validity status."""
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=60)).isoformat()

    def _status(num, exp):
        if not (num or "").strip():
            return "MISSING"
        if exp and exp < today:
            return "EXPIRED"
        if exp and exp <= soon:
            return "EXPIRING SOON"
        return "VALID"

    rows = []
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "compliance_docs": 1}) or {}
    for d in fm.get("compliance_docs") or []:
        num = d.get("number") or ""
        exp = str(d.get("expiry_date") or "")[:10] or None
        rows.append({
            "holder": "FIRM",
            "doc": d.get("description") or "",
            "number": num,
            "issue_date": str(d.get("issue_date") or "")[:10],
            "expiry_date": exp or "—",
            "status": _status(num, exp),
        })
    async for c in db.contractors.find(
            {"company_id": company_id}, {"_id": 0}):
        exp = str(c.get("licence_expiry_date") or "")[:10] or None
        rows.append({
            "holder": f"CONTRACTOR — {c.get('name') or ''}",
            "doc": "CLRA Labour Licence",
            "number": c.get("licence_no") or "",
            "issue_date": str(c.get("licence_issue_date") or "")[:10],
            "expiry_date": exp or "—",
            "status": _status(c.get("licence_no"), exp),
        })
    cols = [("holder", "Holder"),
            ("doc", "Document"),
            ("number", "Number"),
            ("issue_date", "Issue Date"),
            ("expiry_date", "Expiry Date"),
            ("status", "Status")]
    totals = {"holder": "TOTAL DOCUMENTS", "doc": str(len(rows)),
              "status": (f"{sum(1 for r in rows if r['status'] == 'EXPIRED')} expired · "
                         f"{sum(1 for r in rows if r['status'] == 'EXPIRING SOON')} expiring")}
    return ("Digital Document Register", cols, rows, totals)


_CLRA = {
    "contractor-register": _contractor_register,
    "principal-employer": _principal_employer,
    "contract-labour-register": _contract_labour,
    "pt-register": _pt_register,
    "pf-register": _pf_register,
    "esic-register": _esic_register,
    "lwf-register": _lwf_register,
    "leave-register": _leave_register,
    "rejoin-history": _rejoin_history,
    "compliance-dashboard": _compliance_dashboard,
    "inspection-register": _inspection_register,
    "document-register": _document_register,
}
_TITLES = {
    "contractor-register": "Contractor Register",
    "principal-employer": "Principal Employer Register",
    "contract-labour-register": "Contract Labour Register",
    "pt-register": "Professional Tax Register",
    "pf-register": "PF Register",
    "esic-register": "ESIC Register",
    "lwf-register": "Labour Welfare Fund Register",
    "leave-register": "Leave Register (EL Ledger)",
    "rejoin-history": "Employee Rejoin History",
    "compliance-dashboard": "Compliance Dashboard",
    "inspection-register": "Inspection Register",
    "document-register": "Digital Document Register",
}


# ---------------------------------------------------------------------------
# Iter 486 (Phase 3) — CLRA vs Labour Code mode: the firm setting decides
# which Act every register cites in its heading (format unchanged).
# ---------------------------------------------------------------------------
async def compliance_act_line(company_id: str) -> str:
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "settings": 1}) or {}
    mode = str((fm.get("settings") or {}).get("compliance_mode") or "clra")
    if mode == "labour_code":
        return ("Under the Occupational Safety, Health & Working Conditions "
                "Code, 2020 and the Code on Wages, 2019")
    return "Under the Contract Labour (Regulation & Abolition) Act, 1970 & Rules"


@router.get("/list")
async def clra_list(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    return {"reports": [{"kind": k, "title": t}
                        for k, t in _TITLES.items()]}


# ---- Iter 486 — Inspection entries CRUD (declared BEFORE /{kind}) --------
@router.get("/inspections")
async def inspections_list(company_id: Optional[str] = None,
                           authorization: Optional[str] = Header(None)):
    company_id = await _adm(authorization, company_id)
    rows = await db.clra_inspections.find(
        {"company_id": company_id}, {"_id": 0}).sort("date", -1).to_list(500)
    return {"inspections": rows}


@router.post("/inspections")
async def inspections_add(payload: dict,
                          company_id: Optional[str] = None,
                          authorization: Optional[str] = Header(None)):
    import uuid as _uuid
    company_id = await _adm(authorization, company_id or payload.get("company_id"))
    if not (payload.get("date") or "").strip():
        raise HTTPException(status_code=400, detail="Inspection date is required")
    if not (payload.get("inspector_name") or "").strip():
        raise HTTPException(status_code=400, detail="Inspector name is required")
    doc = {
        "inspection_id": payload.get("inspection_id") or f"insp_{_uuid.uuid4().hex[:10]}",
        "company_id": company_id,
        "date": str(payload.get("date"))[:10],
        "inspector_name": (payload.get("inspector_name") or "").strip(),
        "designation": (payload.get("designation") or "").strip(),
        "authority": (payload.get("authority") or "").strip(),
        "observations": (payload.get("observations") or "").strip(),
        "action_taken": (payload.get("action_taken") or "").strip(),
        "status": (payload.get("status") or "open").lower(),
        "updated_at": datetime.now().isoformat(),
    }
    await db.clra_inspections.update_one(
        {"company_id": company_id, "inspection_id": doc["inspection_id"]},
        {"$set": doc}, upsert=True)
    return {"ok": True, "inspection": doc}


@router.delete("/inspections/{inspection_id}")
async def inspections_delete(inspection_id: str,
                             company_id: Optional[str] = None,
                             authorization: Optional[str] = Header(None)):
    company_id = await _adm(authorization, company_id)
    r = await db.clra_inspections.delete_one(
        {"company_id": company_id, "inspection_id": inspection_id})
    return {"ok": True, "deleted": r.deleted_count}


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
    return {"title": title,
            "subtitle": f"{_mlabel(month)} · {await compliance_act_line(company_id)}",
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
           f"{await compliance_act_line(company_id)} · "
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
    fn = fn.encode("ascii", "ignore").decode().replace("\u2014", "-")
    return StreamingResponse(buf, media_type=mt, headers={
        "Content-Disposition": f'attachment; filename="{fn}"'})
