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
    await _adm(authorization)
    raw = body.get("inputs") or {}
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
