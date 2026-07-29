"""Iter 367 — SALARY COMPLIANCE PROCESS (AI).

Acts as a Senior Payroll & Compliance Expert (Indian payroll laws):
takes the employee's payroll inputs (auto-filled READ-ONLY from portal
data, or entered manually), calculates the monthly salary step by step
and returns Employee Details, Attendance Summary, Earnings/Deductions
tables, Employer Contributions, Gross/Net, Payslip Summary, Compliance
Checklist, Payroll Journal Entries and Notes/Assumptions.

STRICTLY ADDITIVE: does NOT modify the Import Excel / Freeze Salary
process or any salary run data — it only reads.
"""
import json
import os
import re
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import db, get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api/admin/ai-salary-compliance",
                   tags=["ai-salary-compliance"])
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

SYSTEM_PROMPT = """Act as a Senior Payroll and Compliance Expert with expertise in Indian payroll laws. Calculate the monthly salary for the employee using the provided payroll inputs and explain each calculation step. Follow all applicable statutory compliance rules (EPF Act, ESI Act, state Professional Tax, LWF, Income Tax TDS, Payment of Bonus Act, Minimum Wages Act).

Calculation Requirements:
- Calculate prorated salary based on attendance and LOP.
- Calculate Gross Earnings.
- Calculate employee deductions (PF, ESI, PT, TDS, LWF, loans, and other deductions).
- Calculate employer contributions separately (EPF 12% split 8.33% EPS capped ₹1,250 + 3.67% EPF, EDLI 0.5%, PF admin 0.5%, ESI 3.25%).
- Calculate Total Deductions and Net Salary Payable.
- Display all calculation formulas used.
- Generate a detailed salary breakup and a payslip summary.
- Highlight any compliance issues, validation errors, or missing information.
- Provide payroll journal entries for accounting.
- Clearly state any assumptions where data is incomplete.

Output Format (use EXACTLY these numbered section headers, in this order):
1. EMPLOYEE DETAILS
2. ATTENDANCE SUMMARY
3. EARNINGS TABLE
4. DEDUCTIONS TABLE
5. EMPLOYER CONTRIBUTIONS
6. GROSS SALARY
7. TOTAL DEDUCTIONS
8. NET SALARY
9. PAYSLIP SUMMARY
10. COMPLIANCE CHECKLIST
11. PAYROLL JOURNAL ENTRIES
12. NOTES AND ASSUMPTIONS

Formatting rules: PLAIN TEXT only — no markdown symbols (#, *, |, backticks). Align table columns with spaces, label every amount with ₹, show each formula on its own line like "Prorated Basic = 15000 x 26/30 = ₹13,000".
CRITICAL TABLE RULES:
- EVERY table (Earnings, Deductions, Employer Contributions, Journal Entries) MUST have a "Sr. No." as the FIRST column (1, 2, 3, …).
- The employee's allowance heads and deduction heads are provided as ordered lists — use those head names EXACTLY as given and in EXACTLY the same order. DO NOT rename, re-sort, re-group or merge them into generic buckets.
- DO NOT filter out or omit any provided head — include every allowance/deduction head in the tables exactly as given, even when its amount is 0.
- If rate_basis is "daily", Basic and allowances are PER-DAY rates: Monthly amount = rate x Present Days (show this formula)."""

_IN_FIELDS = ["employee_name", "employee_id", "payroll_month",
              "basic", "rate_basis", "allowances", "deductions",
              "working_days", "present_days", "paid_leave", "lop",
              "ot_hours",
              "incentives", "bonus", "arrears", "reimbursements",
              "loan_recovery",
              "pf_eligible", "esi_eligible", "pt_state", "tds_amount",
              "lwf_applicable", "notes"]


async def _adm(authorization, company_id=None):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    return admin, company_id


def _f(v) -> float:
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


@router.get("/employee-inputs")
async def employee_inputs(company_id: str, employee_code: str, month: str,
                          authorization: Optional[str] = Header(None)):
    """READ-ONLY prefill of the calculator from portal data."""
    _admin, cid = await _adm(authorization, company_id)
    cid = cid or company_id
    code = employee_code.strip()
    u = await db.users.find_one(
        {"company_id": cid, "role": "employee",
         "employee_code": {"$in": [code, code.lstrip("0"), code.zfill(2),
                                   code.zfill(3)]}},
        {"_id": 0})
    if not u:
        raise HTTPException(status_code=404,
                            detail=f"Employee code {code} not found")
    comp = await db.companies.find_one(
        {"company_id": cid}, {"_id": 0, "name": 1, "state": 1, "address": 1})
    # FIRM-WISE dynamic heads — taken EXACTLY as configured on the Firm
    # Master, in the SAME order (no re-sorting / re-grouping).
    fm = await db.firm_masters.find_one(
        {"company_id": cid}, {"_id": 0, "allowances": 1, "deductions": 1})
    emp_amt = {str(a.get("head") or "").strip().lower(): _f(a.get("amount"))
               for a in u.get("compliance_salary_allowances") or []}
    allowances = []
    for head, enabled in dict((fm or {}).get("allowances") or {}).items():
        if enabled:
            allowances.append({"sr": len(allowances) + 1, "head": head,
                               "amount": emp_amt.get(head.lower(), 0.0)})
    # employee heads not present on the firm list — appended in their own
    # original order (still no re-grouping).
    firm_heads = {a["head"].lower() for a in allowances}
    for a in u.get("compliance_salary_allowances") or []:
        h = str(a.get("head") or "").strip()
        if h and h.lower() not in firm_heads:
            allowances.append({"sr": len(allowances) + 1, "head": h,
                               "amount": _f(a.get("amount"))})
    deductions = []
    for head, enabled in dict((fm or {}).get("deductions") or {}).items():
        if enabled:
            deductions.append({"sr": len(deductions) + 1, "head": head,
                               "amount": 0.0})
    # attendance / imported entries for the month (READ-ONLY)
    y, m = int(month[:4]), int(month[5:7])
    cal_days = [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30,
                31, 31, 30, 31, 30, 31][m - 1]
    present = ot_hours = loan = 0.0
    ent = await db.compliance_import_entries.find_one(
        {"company_id": cid, "month": month, "user_id": u["user_id"]},
        {"_id": 0})
    if ent:
        present = _f(ent.get("present_days"))
        ot_hours = _f(ent.get("ot_hours"))
        loan = _f(ent.get("deduction_amount"))
    else:
        run = await db.compliance_salary_runs.find_one(
            {"company_id": cid, "month": month}, {"_id": 0, "rows": 1},
            sort=[("generated_at", -1)])
        for r in (run or {}).get("rows") or []:
            if r.get("user_id") == u["user_id"]:
                present = _f(r.get("present_days") or r.get("paid_days"))
                ot_hours = _f(r.get("ot_hours"))
                break
    state = str((comp or {}).get("state")
                or (comp or {}).get("address") or "").strip()
    # Basic fallback for daily-rated workers: read the Actual structure's
    # Basic row (READ-ONLY — nothing is modified).
    basic = _f(u.get("compliance_basic") or u.get("basic_salary"))
    rate_basis = "monthly"
    if not basic:
        for r0 in u.get("salary_structure_actual") or []:
            if isinstance(r0, dict) and str(r0.get("head") or "") \
                    .lower().startswith("basic"):
                basic = _f(r0.get("amount"))
                rate_basis = str(r0.get("rate_type") or "monthly")
                break
    if not basic and _f(u.get("salary_monthly")):
        basic = _f(u.get("salary_monthly"))
    gross_est = _f(u.get("compliance_gross")) or (
        (basic if rate_basis == "monthly" else basic * cal_days)
        + sum(a["amount"] for a in allowances))
    return {"inputs": {
        "employee_name": u.get("name"),
        "employee_id": u.get("employee_code"),
        "payroll_month": month,
        "basic": basic,
        "rate_basis": rate_basis,
        "allowances": allowances,
        "deductions": deductions,
        "working_days": cal_days, "present_days": present or cal_days,
        "paid_leave": 0, "lop": max(cal_days - (present or cal_days), 0),
        "ot_hours": ot_hours,
        "incentives": 0, "bonus": 0, "arrears": 0, "reimbursements": 0,
        "loan_recovery": loan,
        "pf_eligible": "Yes" if (u.get("uan_no") or u.get("pf_no")
                                 or gross_est <= 15000) else "No",
        "esi_eligible": "Yes" if (u.get("esi_ip_no")
                                  or (gross_est and gross_est <= 21000))
        else "No",
        "pt_state": state or "Rajasthan",
        "tds_amount": 0, "lwf_applicable": "Yes" if state else "Yes",
        "notes": (f"UAN: {u.get('uan_no') or '—'} · "
                  f"ESIC IP: {u.get('esi_ip_no') or '—'} · "
                  f"Company: {(comp or {}).get('name')}")},
        "company_name": (comp or {}).get("name")}


@router.post("/calculate")
async def calculate(body: dict = Body(...),
                    authorization: Optional[str] = Header(None)):
    _admin, forced_cid = await _adm(authorization, body.get("company_id"))
    cid = forced_cid or body.get("company_id")
    code = str(body.get("employee_code") or "").strip()
    month = str(body.get("month") or "").strip()
    raw = body.get("inputs") or {}
    if cid and code and re.fullmatch(r"20\d{2}-\d{2}", month):
        return await _calculate_engine(cid, code, month, raw)
    return await _calculate_ai_only(raw)


def _tbl(title: str, rows, total_label="TOTAL") -> str:
    """Fixed-width table: Sr. No. FIRST column, footer total aligned
    under the Amount heading (user request)."""
    out = [title, "-" * 52,
           f"{'Sr.':<5}{'Particulars':<32}{'Amount (₹)':>15}",
           "-" * 52]
    total = 0.0
    sr = 0
    for head, amt in rows:
        sr += 1
        total += float(amt)
        out.append(f"{sr:<5}{str(head)[:31]:<32}{float(amt):>15,.2f}")
    out.append("-" * 52)
    out.append(f"{'':<5}{total_label:<32}{total:>15,.2f}")
    out.append("")
    return "\n".join(out)


async def _calculate_engine(cid: str, code: str, month: str,
                            raw: dict) -> dict:
    """DETERMINISTIC: uses the SAME compute_compliance_row engine and the
    firm's Compliance Salary Policy as the Salary Process — deductions &
    net match the portal exactly. AI only writes checklist/journal/notes."""
    from utils.compliance_salary import (DEFAULT_STATUTORY_CFG,
                                         compute_compliance_row)
    u = await db.users.find_one(
        {"company_id": cid, "role": "employee",
         "employee_code": {"$in": [code, code.lstrip("0"), code.zfill(2),
                                   code.zfill(3)]}}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404,
                            detail=f"Employee code {code} not found")
    comp = await db.companies.find_one({"company_id": cid}, {"_id": 0})
    fm = await db.firm_masters.find_one({"company_id": cid}, {"_id": 0})
    fcp = (comp or {}).get("compliance_policy") or {}
    fded = (fm or {}).get("deductions") or {}
    firm_pf = bool(((fm or {}).get("epf") or {}).get("applicable")) \
        or bool(fded.get("PF"))
    firm_esic = bool(((fm or {}).get("esi") or {}).get("applicable")) \
        or bool(fded.get("ESI"))
    statutory = {k: fcp[k] for k in DEFAULT_STATUTORY_CFG if k in fcp}
    y, m = int(month[:4]), int(month[5:7])
    month_days = [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30,
                  31, 31, 30, 31, 30, 31][m - 1]
    present = _f(raw.get("present_days")) or month_days
    ot_hours = _f(raw.get("ot_hours"))
    stats = {"present_days": present, "effective_present": present,
             "half_days": 0, "duty_hours": 0.0, "ot_hours": ot_hours}
    policy = dict(u.get("employee_policy") or {})
    if _f(raw.get("tds_amount")):
        u = {**u, "tds_monthly": _f(raw.get("tds_amount"))}
    row = compute_compliance_row(
        u, policy, month_days, stats, statutory_cfg=statutory,
        firm_pf_enabled=firm_pf, firm_esic_enabled=firm_esic,
        firm_pt={"state": fcp.get("pt_state"), "slabs": fcp.get("pt_slabs")})

    inc, bon = _f(raw.get("incentives")), _f(raw.get("bonus"))
    arr, reim = _f(raw.get("arrears")), _f(raw.get("reimbursements"))
    loan = _f(raw.get("loan_recovery"))
    earn_rows = [("BASIC (earned)", row["basic"])]
    for k, lb in (("hra", "HRA"), ("conveyance", "CONVEYANCE"),
                  ("medical", "MEDICAL"), ("special", "SPECIAL ALLOWANCE"),
                  ("others", "OTHER ALLOWANCES")):
        if _f(row.get(k)):
            earn_rows.append((lb, row[k]))
    if _f(row.get("ot_pay")):
        earn_rows.append((f"OVERTIME ({row['ot_hours']} hrs)",
                          row["ot_pay"]))
    for lb, v in (("INCENTIVES", inc), ("BONUS", bon), ("ARREARS", arr),
                  ("REIMBURSEMENTS", reim)):
        if v:
            earn_rows.append((lb, v))
    gross = round(_f(row.get("gross_paid")) + inc + bon + arr + reim, 2)

    ded_rows = []
    if _f(row.get("pf_employee")):
        ded_rows.append((f"PF EMPLOYEE (12% of {row['pf_wages']:,.0f})",
                         row["pf_employee"]))
    if _f(row.get("vpf_amount")):
        ded_rows.append(("VPF", row["vpf_amount"]))
    if _f(row.get("esic_employee")):
        ded_rows.append(("ESIC EMPLOYEE (0.75%)", row["esic_employee"]))
    if _f(row.get("pt")):
        ded_rows.append((f"PROFESSIONAL TAX ({row.get('pt_state') or ''})",
                         row["pt"]))
    if _f(row.get("tds")):
        ded_rows.append(("TDS", row["tds"]))
    if _f(row.get("master_deduction")):
        ded_rows.append(("OTHER DEDUCTIONS (master)",
                         row["master_deduction"]))
    if loan:
        ded_rows.append(("LOAN / ADVANCE RECOVERY", loan))
    total_ded = round(sum(_f(a) for _h, a in ded_rows), 2)
    net = round(gross - total_ded, 2)

    cfg = dict(DEFAULT_STATUTORY_CFG)
    for k, v in statutory.items():
        if not isinstance(v, str):
            cfg[k] = _f(v)
    pfw = _f(row.get("pf_wages"))
    er_rows = []
    if _f(row.get("pf_employer_total")):
        er_rows += [("EPF EMPLOYER 3.67%", row["pf_employer_epf"]),
                    ("EPS EMPLOYER 8.33%", row["pf_employer_eps"]),
                    ("EDLI 0.50%", round(pfw * cfg["pf_edli_percent"]
                                         / 100, 2)),
                    ("PF ADMIN 0.50%", round(pfw * cfg["pf_admin_percent"]
                                             / 100, 2))]
    if _f(row.get("esic_employer")):
        er_rows.append(("ESIC EMPLOYER 3.25%", row["esic_employer"]))

    hdr = (f"1. EMPLOYEE DETAILS\n{'-' * 52}\n"
           f"Name          : {u.get('name')}\n"
           f"Employee Code : {u.get('employee_code')}\n"
           f"Company       : {(comp or {}).get('name')}\n"
           f"Month         : {month}\n"
           f"Rate          : {row['rate']:,.2f} ({row['salary_mode']})\n"
           f"UAN           : {u.get('uan_no') or '—'}   "
           f"ESIC IP: {u.get('esi_ip_no') or '—'}\n\n"
           f"2. ATTENDANCE SUMMARY\n{'-' * 52}\n"
           f"Month Days: {month_days}   Present: {row['present_days']}   "
           f"OT Hours: {row['ot_hours']}\n")
    body_txt = (
        hdr + "\n" + _tbl("3. EARNINGS TABLE", earn_rows, "GROSS EARNINGS")
        + _tbl("4. DEDUCTIONS TABLE", ded_rows, "TOTAL DEDUCTIONS")
        + _tbl("5. EMPLOYER CONTRIBUTIONS (not deducted from employee)",
               er_rows, "TOTAL EMPLOYER COST")
        + f"6. GROSS SALARY      : ₹{gross:>13,.2f}\n"
        + f"7. TOTAL DEDUCTIONS  : ₹{total_ded:>13,.2f}\n"
        + f"8. NET SALARY PAYABLE: ₹{net:>13,.2f}\n\n"
        + f"9. PAYSLIP SUMMARY\n{'-' * 52}\n"
        + f"{u.get('name')} · {month} · Gross ₹{gross:,.2f} − "
        + f"Deductions ₹{total_ded:,.2f} = NET ₹{net:,.2f}\n"
        + "(Computed by the portal's Compliance Salary engine — same "
        + "policy, rates,\n rounding and PF/ESIC/PT rules as your Salary "
        + "Process.)\n")

    ai_txt = ""
    if EMERGENT_LLM_KEY:
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            chat = LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"ai-salcomp-{uuid.uuid4().hex[:8]}",
                system_message=(
                    "You are a Senior Indian Payroll Compliance Expert. "
                    "The salary is ALREADY calculated by the firm's "
                    "compliance engine — do NOT recalculate or change any "
                    "number. Produce ONLY these plain-text sections (no "
                    "markdown; every table MUST start with a Sr. No. "
                    "column): 10. COMPLIANCE CHECKLIST (point-wise PF/ESIC/"
                    "PT/TDS/LWF/minimum-wage checks with OK or ISSUE), "
                    "11. PAYROLL JOURNAL ENTRIES (Sr., Account, Debit, "
                    "Credit — salary payable, PF/ESIC payable incl. "
                    "employer share, PT, TDS), 12. NOTES AND ASSUMPTIONS."),
            ).with_model("openai", "gpt-5.4")
            resp = await chat.send_message(UserMessage(
                text=body_txt + "\nEmployer contributions total: ₹"
                + f"{sum(_f(a) for _h, a in er_rows):,.2f}"))
            ai_txt = "\n" + re.sub(r"[*#`|]", "", str(resp))
        except Exception as e:  # noqa: BLE001
            ai_txt = ("\n10. COMPLIANCE CHECKLIST\n(AI unavailable: "
                      + str(e)[:120] + ")\n")
    await db.ai_salary_compliance_log.insert_one({
        "at": __import__("datetime").datetime.utcnow().isoformat(),
        "employee": u.get("name"), "month": month, "mode": "engine"})
    return {"result": body_txt + ai_txt, "engine": True,
            "row": {"gross": gross, "total_deduction": total_ded,
                    "net": net}}


async def _calculate_ai_only(raw: dict) -> dict:
    inputs = {k: raw.get(k) for k in _IN_FIELDS if raw.get(k)
              not in (None, "")}
    if not _f(inputs.get("basic")) and not (inputs.get("allowances")):
        raise HTTPException(
            status_code=400,
            detail="Basic Salary (or at least one allowance) is required")
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail="AI key not configured")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(api_key=EMERGENT_LLM_KEY,
                       session_id=f"ai-salcomp-{uuid.uuid4().hex[:8]}",
                       system_message=SYSTEM_PROMPT
                       ).with_model("openai", "gpt-5.4")
        resp = await chat.send_message(UserMessage(
            text="Input Details (JSON):\n" + json.dumps(inputs, indent=1)))
        text = re.sub(r"[*#`|]", "", str(resp))
        await db.ai_salary_compliance_log.insert_one({
            "at": __import__("datetime").datetime.utcnow().isoformat(),
            "employee": inputs.get("employee_name"),
            "month": inputs.get("payroll_month")})
        return {"result": text, "inputs_used": inputs}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"AI failed: {e}")
