"""AI Payroll Assistant v2 — execution engine + purified data Q&A (Iter 345).

POST /api/admin/ai-assistant/command
    Parses the operator's command (English / Hindi / Hinglish) with an LLM
    into a structured intent, resolves entities (firm, month, employee) and
    returns a reply plus an optional *action*:
      { type: "navigate",   route, label }
      { type: "confirm_api", method, endpoint, body, label, danger?,
        success_note?, navigate_after? }        ← user must press Confirm
      { type: "download",   endpoint, label, filename, auto: true }  ← safe,
        runs immediately (report downloads)

Executable work:
  • Process Actual / Compliance salary for a firm + month (confirm)
  • Finalize & Lock a salary run (confirm, danger)
  • Download Salary Register PDF, Bank Sheet XLSX, Attendance Sheet XLSX,
    PF ECR — auto-run (safe)
  • Email attendance / salary report (confirm)
  • Update employee phone / monthly salary, mark resigned / active (confirm)
Data Q&A (purified — always firm-scoped, labelled and from the live DB):
  salary totals, ESIC eligible count, absent list, present count,
  employee counts, top paid, run status.

POST /api/admin/ai-assistant/employee-status — confirm-gated executor used
    by the assistant to mark an employee resigned / active.
GET  /api/admin/ai-assistant/history — last 30 exchanges for this user.
"""
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel

from server import db, get_user_from_token, require_role  # noqa: E402

load_dotenv()

router = APIRouter(prefix="/api", tags=["ai-assistant"])
logger = logging.getLogger("ai-assistant")

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

# Screen catalog the AI can navigate to (key → route + label).
SCREENS = {
    "dashboard": ("/portal-dashboard", "Dashboard"),
    "employee_master": ("/admin", "Employee Master"),
    "add_employee": ("/employee-add", "Add New Employee"),
    "attendance_report": ("/attendance-grid", "Attendance Report"),
    "inout_matrix": ("/inout-ot-matrix", "In/Out & OT Matrix"),
    "salary_run": ("/salary-run", "Actual Salary Process"),
    "compliance_salary": ("/compliance-salary-run", "Compliance Salary Process"),
    "ot_salary": ("/ot-salary-run", "OT Salary Process"),
    "arrear_salary": ("/arrear-salary-run", "Arrear Salary Process"),
    "advances": ("/advances", "Advance Management"),
    "bonus": ("/bonus-run", "Bonus Process"),
    "bank_sheet": ("/bank-sheet", "Bank Sheet"),
    "pf_reports": ("/pf-reports?kind=pf", "PF Reports"),
    "esic_reports": ("/pf-reports?kind=esic", "ESIC Reports"),
    "challans": ("/challans", "PF / ESIC Challans"),
    "labour_reports": ("/labour-reports", "Labour Law Reports"),
    "reports": ("/reports?tab=salary", "Salary Reports"),
    "employee_reports": ("/employee-reports", "Employee Reports Hub"),
    "payslips": ("/employee-reports", "Pay Slips"),
    "devices": ("/biometric-devices", "Biometric Devices"),
    "companies": ("/companies", "Firm Master"),
    "approvals": ("/approval-inbox", "Approval Inbox"),
    "punch_approvals": ("/punch-approvals", "Punch Approvals"),
    "shift_change": ("/shift-change-admin", "Shift Change Requests"),
    "kyc": ("/kyc-tracker", "KYC Tracker"),
    "masters": ("/masters", "General Masters"),
    "notifications": ("/notifications", "Notifications"),
    "day_salary_sheet": ("/salary-day-sheet", "Day-wise Salary Sheet"),
    "daily_present": ("/daily-present-report", "Day-wise Present Count"),
    "ai_dashboard": ("/ai-payroll-assistant", "AI Payroll Assistant"),
}

SYSTEM_PROMPT = """You are the AI command parser for an Indian payroll & attendance web portal (S.K. Sharma & Co.).
The operator may write in English, Hindi or Hinglish (e.g. "Kankani ka June salary process karo").
Parse the command into STRICT JSON (no markdown, no prose) with this schema:
{
  "intent": "process_salary" | "finalize_salary" | "report" | "email_report" | "employee_search" | "employee_update" | "bulk_salary_change" | "data_query" | "compliance_info" | "attendance_summary" | "pending_approvals" | "navigate" | "answer",
  "salary_type": "actual" | "compliance" | "ot" | "arrear" | null,
  "report": "salary_register" | "bank_sheet" | "attendance_sheet" | "pf_ecr" | null,
  "metric": "salary_total" | "esic_eligible" | "absent_list" | "present_count" | "employee_count" | "top_paid" | "run_status" | "missing_data" | "pf_mismatch" | "why_salary" | null,
  "month": "YYYY-MM" | null,
  "date": "YYYY-MM-DD" | null,
  "firm_name": string | null,
  "employee_query": string | null,
  "field": "phone" | "salary" | "status" | null,
  "value": string | null,
  "department": string | null,
  "percent": number | null,
  "amount": number | null,
  "screen": one of [%SCREENS%] | null,
  "reply": short helpful sentence in the SAME language the user wrote in (English or Hindi)
}
Rules (today is %TODAY%):
- "Process July payroll/salary" → intent=process_salary, salary_type=actual unless the user says compliance/PF (→compliance), overtime/OT (→ot) or arrear (→arrear). Resolve month to the CURRENT YEAR; if that lands in the future, use the previous year.
- "Finalize/lock June salary" → finalize_salary (same salary_type rules; null if unspecified).
- "Download/give/generate salary register / bank sheet / attendance sheet / PF ECR" → intent=report with the matching report key, plus month.
- "Email/send the attendance sheet / salary report (to client)" → email_report with report + month/date.
- Data questions → data_query with the right metric:
  * "total net/gross salary of X in June", "June ki salary kitni thi" → salary_total
  * "how many ESIC eligible" → esic_eligible
  * "who is absent today/yesterday" → absent_list with date
  * "how many present today" → present_count with date
  * "how many employees / active / resigned" → employee_count
  * "highest paid employees" → top_paid
  * "is June salary finalized?" → run_status
  * "list employees with missing UAN / ESIC number / Aadhaar / bank details" → missing_data with the field name in value ("uan"|"esic"|"aadhaar"|"bank")
  * "show PF mismatches / PF errors" → pf_mismatch
  * "why is Rajesh's salary lower (this month)?" → why_salary with employee_query (and month if named)
- "find employee Ramesh", "show Suresh's details" → employee_search with employee_query.
- "change Ramesh's phone to 98xxx", "set salary of code 50 to 15000", "mark Ramesh resigned/active" → employee_update with employee_query, field (phone|salary|status) and value (for status: "resigned" or "active").
- BULK salary commands — "increase salary of ALL employees (in <X> department) by 5%", "sabki salary 500 rupaye badhao", "reduce Production dept salaries by 10%" → bulk_salary_change with department (null = whole firm) and percent (NEGATIVE for decrease/reduce) OR amount (flat ₹, negative for decrease). NEVER use employee_update for more than one employee.
- "open X" / "go to X" → navigate with the best screen key.
- Questions about PF/EPF/ESIC/PT/TDS/labour-law RULES, rates, wage limits, due dates, latest NEWS, circulars, notifications or amendments (e.g. "PF ki latest notification kya hai", "what is the ESIC wage limit rule", "any new labour code update?") → compliance_info, and put the TOPIC in employee_query (e.g. "pf", "esic", "labour_code", "pt", "tds", "minimum_wages").
- Anything else (greetings, general payroll/PF/ESIC law questions) → answer, with your best short answer in reply.
- Relative dates: "today"=%TODAY%, "yesterday"=the day before. If a month is named without a year, use the current year (or previous year if in the future).
Return ONLY the JSON object."""


class CommandBody(BaseModel):
    text: str
    company_id: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _money(n: Any) -> str:
    try:
        return f"₹{round(float(n or 0)):,}".replace(",", ",")
    except Exception:
        return "₹0"


def _mon_label(month: str) -> str:
    try:
        return datetime.strptime(month, "%Y-%m").strftime("%B %Y")
    except Exception:
        return month


def _tget(totals: Optional[dict], *keys: str) -> float:
    totals = totals or {}
    for k in keys:
        v = totals.get(k)
        if isinstance(v, (int, float)) and v:
            return float(v)
    return 0.0


def _fallback_parse(text: str) -> dict:
    """Regex fallback when the LLM is unreachable — covers core commands."""
    t = text.lower()
    out: dict = {"intent": "answer", "salary_type": None, "report": None,
                 "metric": None, "month": None, "date": None,
                 "firm_name": None, "employee_query": None, "field": None,
                 "value": None, "screen": None,
                 "reply": "Sorry, I couldn't reach the AI service. Try a simple command like 'Process July payroll'."}
    month = None
    for name, num in MONTHS.items():
        if name in t or name[:3] in re.findall(r"[a-z]{3,}", t):
            today = datetime.now()
            year = today.year if num <= today.month else today.year - 1
            month = f"{year}-{num:02d}"
            break
    if ("payroll" in t or "salary" in t) and ("process" in t or "run" in t or "karo" in t):
        out.update({"intent": "process_salary",
                    "salary_type": "compliance" if "compliance" in t or "pf" in t else "actual",
                    "month": month, "reply": "Processing payroll."})
    elif "bank sheet" in t or "register" in t or "ecr" in t or "attendance sheet" in t:
        rep = ("bank_sheet" if "bank" in t else
               "pf_ecr" if "ecr" in t else
               "attendance_sheet" if "attendance" in t else "salary_register")
        out.update({"intent": "report", "report": rep, "month": month,
                    "reply": "Preparing the report."})
    elif "absent" in t:
        out.update({"intent": "data_query", "metric": "absent_list",
                    "reply": "Checking absentees."})
    elif "attendance" in t or "present" in t:
        out.update({"intent": "attendance_summary", "reply": "Checking attendance."})
    elif "approval" in t:
        out.update({"intent": "pending_approvals", "reply": "Checking approvals."})
    return out


async def _llm_parse(text: str) -> dict:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    prompt = SYSTEM_PROMPT.replace(
        "%SCREENS%", ", ".join(f'"{k}"' for k in SCREENS.keys())
    ).replace("%TODAY%", datetime.now().strftime("%Y-%m-%d"))
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"ai-cmd-{uuid.uuid4().hex[:8]}",
        system_message=prompt,
    ).with_model("openai", "gpt-5.4")
    resp = await chat.send_message(UserMessage(text=text))
    raw = str(resp).strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON in LLM reply: {raw[:200]}")
    return json.loads(m.group(0))


async def _resolve_company(admin: dict, firm_name: Optional[str],
                           fallback_company_id: Optional[str]):
    """Resolve firm scope: explicit name in command > frontend-selected firm.
    Company admins are always locked to their own firm."""
    if admin["role"] == "company_admin":
        cid = admin.get("company_id")
        return await db.companies.find_one(
            {"company_id": cid}, {"_id": 0, "company_id": 1, "name": 1})
    if firm_name:
        c = await db.companies.find_one(
            {"name": {"$regex": re.escape(firm_name.strip()), "$options": "i"}},
            {"_id": 0, "company_id": 1, "name": 1})
        if c:
            return c
    if fallback_company_id:
        return await db.companies.find_one(
            {"company_id": fallback_company_id}, {"_id": 0, "company_id": 1, "name": 1})
    return None


async def _latest_run(collection, cid: str, month: str) -> Optional[dict]:
    return await collection.find_one(
        {"company_id": cid, "month": month},
        {"_id": 0, "rows": 0}, sort=[("generated_at", -1)])


_RESIGNED_STATUSES = ["exited", "resigned", "terminated", "inactive", "left"]


def _resigned_query() -> dict:
    return {"$or": [
        {"exit_date": {"$nin": [None, ""]}},
        {"resign_date": {"$nin": [None, ""]}},
        {"employment_status": {"$in": _RESIGNED_STATUSES}},
        {"active": False},
    ]}


async def _find_employees(admin: dict, cid: Optional[str], term: str,
                          limit: int = 6) -> List[dict]:
    # "code 50" / "emp 50" / "employee no 50" → "50" (testing feedback).
    term = re.sub(r"^(?:employee|emp|code|worker|no\.?)\s+(?:no\.?\s*|code\s*)?",
                  "", term.strip(), flags=re.IGNORECASE).strip() or term.strip()
    q: dict = {"role": "employee", "$or": [
        {"name": {"$regex": re.escape(term), "$options": "i"}},
        {"employee_code": {"$regex": f"^{re.escape(term)}$", "$options": "i"}},
    ]}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif cid:
        q["company_id"] = cid
    return await db.users.find(q, {
        "_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "phone": 1,
        "designation": 1, "company_id": 1, "salary_monthly": 1,
        "exit_date": 1, "employment_status": 1,
    }).to_list(limit)


# ---------------------------------------------------------------------------
# Intent handlers — each returns (reply, action)
# ---------------------------------------------------------------------------

async def _h_process_salary(parsed, admin, cid, firm_label):
    month = parsed.get("month")
    stype = parsed.get("salary_type") or "actual"
    if not month:
        return ("Which month should I process? e.g. \"Process July 2026 payroll\".", None)
    if not cid:
        return (f"Which firm should I process {_mon_label(month)} payroll for? "
                "Say the firm name or select one from the top bar.", None)
    mon = _mon_label(month)
    if stype in ("actual", "compliance"):
        coll = db.salary_runs if stype == "actual" else db.compliance_salary_runs
        run = await _latest_run(coll, cid, month)
        if run and run.get("finalized"):
            return (f"{mon} {stype.title()} salary for {firm_label} is already "
                    "FINALIZED (locked). Use an Unlock Request to change it.", {
                        "type": "navigate",
                        "route": "/salary-run" if stype == "actual" else "/compliance-salary-run",
                        "label": "Open Salary Screen"})
        endpoint = "/admin/salary-runs" if stype == "actual" else "/admin/compliance-salary-runs"
        route = "/salary-run" if stype == "actual" else "/compliance-salary-run"
        verb = "REPROCESS" if run else "Process"
        return (f"Ready to {verb} **{mon} {stype.title()} Salary** for **{firm_label}**"
                + (" (an existing draft will be updated — entered days/edits are kept)" if run else "")
                + ". Press Confirm to run it.", {
                    "type": "confirm_api", "method": "POST", "endpoint": endpoint,
                    "body": {"month": month, "company_id": cid},
                    "label": f"{verb} {mon} {stype.title()} Salary — {firm_label}",
                    "success_note": f"✅ {mon} {stype.title()} salary processed for {firm_label}.",
                    "navigate_after": route})
    route = "/ot-salary-run" if stype == "ot" else "/arrear-salary-run"
    return (f"{stype.upper()} salary needs extra inputs (rates / period) — I've "
            f"prepared the screen for {mon} · {firm_label}. Open it and press Process.",
            {"type": "navigate", "route": route, "label": f"Open {stype.title()} Salary Process"})


async def _h_finalize_salary(parsed, admin, cid, firm_label):
    month = parsed.get("month")
    stype = parsed.get("salary_type")
    if not month:
        return ("Which month should I finalize? e.g. \"Finalize June compliance salary\".", None)
    if not cid:
        return ("Which firm? Say the firm name or pick one from the top bar.", None)
    mon = _mon_label(month)
    comp = await _latest_run(db.compliance_salary_runs, cid, month)
    act = await _latest_run(db.salary_runs, cid, month)
    if stype == "compliance" or (stype is None and comp and not act):
        run = comp
        if not run:
            return (f"No Compliance salary run exists for {mon} — {firm_label}. "
                    "Process it first.", None)
        if run.get("finalized"):
            return (f"{mon} Compliance salary for {firm_label} is already FINALIZED.", None)
        return (f"Finalize & LOCK **{mon} Compliance Salary** for **{firm_label}** "
                f"({run.get('employees_count')} employees, Net {_money(_tget(run.get('totals'), 'net'))})? "
                "Nobody can change it afterwards without Super Admin unlock.", {
                    "type": "confirm_api", "method": "POST",
                    "endpoint": f"/admin/compliance-salary-runs/{run['run_id']}/finalize",
                    "body": {}, "danger": True,
                    "label": f"Finalize & Lock {mon} Compliance — {firm_label}",
                    "success_note": f"🔒 {mon} Compliance salary finalized & locked for {firm_label}."})
    if stype == "actual" or (stype is None and act and not comp):
        run = act
        if not run:
            return (f"No Actual salary run exists for {mon} — {firm_label}. Process it first.", None)
        if run.get("finalized"):
            return (f"{mon} Actual salary for {firm_label} is already FINALIZED.", None)
        return (f"Finalize & LOCK **{mon} Actual Salary** for **{firm_label}** "
                f"({run.get('employees_count')} employees)?", {
                    "type": "confirm_api", "method": "POST",
                    "endpoint": f"/admin/actual-salary-process/{run['run_id']}/finalize",
                    "body": {}, "danger": True,
                    "label": f"Finalize & Lock {mon} Actual — {firm_label}",
                    "success_note": f"🔒 {mon} Actual salary finalized & locked for {firm_label}."})
    if comp and act:
        return (f"Both Actual and Compliance runs exist for {mon} — {firm_label}. "
                "Which one should I finalize? Say \"finalize June compliance salary\" "
                "or \"finalize June actual salary\".", None)
    return (f"No salary run found for {mon} — {firm_label}. Process it first.", None)


async def _h_report(parsed, admin, cid, firm_label):
    rep = parsed.get("report")
    month = parsed.get("month") or datetime.now().strftime("%Y-%m")
    if not cid:
        return ("Which firm's report do you need? Say the firm name or select one "
                "from the top bar.", None)
    mon = _mon_label(month)
    if rep == "bank_sheet":
        return (f"⬇ Downloading the **Bank Sheet** for {mon} — {firm_label}.", {
            "type": "download", "auto": True,
            "endpoint": f"/admin/bank-sheet.xlsx?month={month}&company_id={cid}",
            "label": f"Bank Sheet {mon} — {firm_label}",
            "filename": f"bank-sheet-{firm_label}-{month}.xlsx"})
    if rep == "attendance_sheet":
        return (f"⬇ Downloading the **Attendance Sheet** for {mon} — {firm_label}.", {
            "type": "download", "auto": True,
            "endpoint": f"/admin/attendance-sheet/{cid}/{month}.xlsx",
            "label": f"Attendance Sheet {mon} — {firm_label}",
            "filename": f"attendance-sheet-{firm_label}-{month}.xlsx"})
    if rep in ("salary_register", "pf_ecr"):
        comp = await _latest_run(db.compliance_salary_runs, cid, month)
        if rep == "pf_ecr":
            if not comp:
                return (f"No Compliance salary run for {mon} — {firm_label}; the PF ECR "
                        "is generated from it. Process the compliance salary first.", None)
            return (f"⬇ Downloading the **PF ECR** for {mon} — {firm_label}.", {
                "type": "download", "auto": True,
                "endpoint": f"/admin/compliance-salary-runs/{comp['run_id']}/pf-ecr.txt",
                "label": f"PF ECR {mon} — {firm_label}",
                "filename": f"pf-ecr-{firm_label}-{month}.txt"})
        if comp:
            return (f"⬇ Downloading the **Salary Register (Compliance)** for {mon} — {firm_label}.", {
                "type": "download", "auto": True,
                "endpoint": f"/admin/compliance-salary-runs/{comp['run_id']}/register.pdf",
                "label": f"Salary Register {mon} — {firm_label}",
                "filename": f"salary-register-{firm_label}-{month}.pdf"})
        act = await _latest_run(db.salary_runs, cid, month)
        if act:
            return (f"⬇ Downloading the **Salary Register (Actual)** for {mon} — {firm_label}.", {
                "type": "download", "auto": True,
                "endpoint": f"/admin/salary-runs/{act['run_id']}/register.pdf",
                "label": f"Salary Register {mon} — {firm_label}",
                "filename": f"salary-register-{firm_label}-{month}.pdf"})
        return (f"No salary run exists for {mon} — {firm_label}. Process the salary "
                "first, then ask me for the register again.", None)
    return ("Which report do you need — salary register, bank sheet, attendance "
            "sheet or PF ECR?", None)


async def _h_email_report(parsed, admin, cid, firm_label):
    rep = parsed.get("report") or "attendance_sheet"
    month = parsed.get("month")
    date = parsed.get("date")
    if not cid:
        return ("Which firm's report should I email? Say the firm name.", None)
    if rep == "attendance_sheet" and not month:
        d = date or datetime.now().strftime("%Y-%m-%d")
        return (f"Email the **Daily Attendance Report** ({d}) for **{firm_label}** to "
                "the configured client recipients?", {
                    "type": "confirm_api", "method": "POST",
                    "endpoint": "/admin/email-triggers/daily-attendance/send-now",
                    "body": {"company_id": cid, "date": d},
                    "label": f"Email Daily Attendance ({d}) — {firm_label}",
                    "success_note": f"📧 Daily attendance report emailed for {firm_label}."})
    month = month or datetime.now().strftime("%Y-%m")
    y, m = month.split("-")
    kind = "salary" if rep in ("salary_register", "bank_sheet") else "attendance"
    return (f"Email the **{_mon_label(month)} {kind.title()} Report** for "
            f"**{firm_label}** to your email?", {
                "type": "confirm_api", "method": "POST",
                "endpoint": "/admin/payroll/email-report",
                "body": {"year": int(y), "month": int(m), "company_id": cid,
                         "report_kind": kind, "recipients": "self"},
                "label": f"Email {_mon_label(month)} {kind.title()} Report — {firm_label}",
                "success_note": f"📧 {_mon_label(month)} {kind} report sent to your email."})


async def _h_employee_update(parsed, admin, cid, firm_label):
    term = (parsed.get("employee_query") or "").strip()
    field = parsed.get("field")
    value = (parsed.get("value") or "").strip()
    if not term:
        return ("Which employee? Give the name or employee code, e.g. "
                "\"mark employee 50 resigned\".", None)
    rows = await _find_employees(admin, cid, term)
    if not rows:
        return (f"No employee matching \"{term}\" found"
                f"{' in ' + firm_label if cid else ''}.", None)
    if len(rows) > 1:
        lines = [f"• {r.get('name')} (Code {r.get('employee_code')})" for r in rows]
        return ("I found multiple employees — please repeat the command with the "
                "employee CODE:\n" + "\n".join(lines), None)
    emp = rows[0]
    who = f"{emp.get('name')} (Code {emp.get('employee_code')})"
    if field == "status" and value.lower() in ("resigned", "active"):
        status = value.lower()
        verb = "Mark RESIGNED" if status == "resigned" else "Mark ACTIVE (re-join)"
        return (f"{verb}: **{who}** — {firm_label}?", {
            "type": "confirm_api", "method": "POST",
            "endpoint": "/admin/ai-assistant/employee-status",
            "body": {"user_id": emp["user_id"], "status": status},
            "danger": status == "resigned",
            "label": f"{verb} — {emp.get('name')}",
            "success_note": f"✅ {who} marked {status.upper()}.",
            "navigate_after": "/admin"})
    if field == "phone" and value:
        return (f"Update phone of **{who}** from "
                f"{emp.get('phone') or '—'} to **{value}**?", {
                    "type": "confirm_api", "method": "PATCH",
                    "endpoint": f"/employees/{emp['user_id']}/profile",
                    "body": {"phone": value},
                    "label": f"Update phone — {emp.get('name')}",
                    "success_note": f"✅ Phone updated for {who}."})
    if field == "salary" and value:
        try:
            amt = float(re.sub(r"[^\d.]", "", value))
        except ValueError:
            return (f"I couldn't read the salary amount \"{value}\".", None)
        return (f"Update monthly salary of **{who}** from "
                f"{_money(emp.get('salary_monthly'))} to **{_money(amt)}**?", {
                    "type": "confirm_api", "method": "PATCH",
                    "endpoint": f"/employees/{emp['user_id']}/profile",
                    "body": {"salary_monthly": amt}, "danger": True,
                    "label": f"Set salary {_money(amt)} — {emp.get('name')}",
                    "success_note": f"✅ Salary updated to {_money(amt)} for {who}."})
    return ("Tell me what to change — phone, salary, or status (resigned/active). "
            "e.g. \"set salary of code 50 to 15000\".", None)


async def _h_data_query(parsed, admin, cid, firm_label, company):
    metric = parsed.get("metric")
    month = parsed.get("month")
    date = parsed.get("date")

    if metric == "salary_total":
        if not cid:
            return ("Which firm? e.g. \"What was Kankani's total net salary in June?\"", None)
        month = month or datetime.now().strftime("%Y-%m")
        mon = _mon_label(month)
        comp = await _latest_run(db.compliance_salary_runs, cid, month)
        act = await _latest_run(db.salary_runs, cid, month)
        if not comp and not act:
            return (f"No salary run found for {mon} — {firm_label}. "
                    f"Say \"Process {mon.split()[0]} compliance salary\" to create one.", None)
        lines = [f"📊 {mon} — {firm_label}"]
        if comp:
            t = comp.get("totals") or {}
            lines.append(
                f"• Compliance Salary ({'FINALIZED 🔒' if comp.get('finalized') else 'Draft'}): "
                f"{comp.get('employees_count')} employees — "
                f"Gross {_money(_tget(t, 'gross_paid', 'monthly_gross', 'gross'))} · "
                f"Net {_money(_tget(t, 'net'))} · PF {_money(_tget(t, 'pf_employee'))} · "
                f"ESIC {_money(_tget(t, 'esic_employee'))}")
        if act:
            t = act.get("totals") or {}
            lines.append(
                f"• Actual Salary ({'FINALIZED 🔒' if act.get('finalized') else 'Draft'}): "
                f"{act.get('employees_count')} employees — "
                f"Gross {_money(_tget(t, 'total_gross', 'gross', 'gross_paid'))} · "
                f"Net {_money(_tget(t, 'net_pay', 'net', 'total_net'))}")
        return ("\n".join(lines), None)

    if metric == "esic_eligible":
        month = month or datetime.now().strftime("%Y-%m")
        if cid:
            comp = await db.compliance_salary_runs.find_one(
                {"company_id": cid, "month": month}, {"_id": 0, "rows": 1, "finalized": 1},
                sort=[("generated_at", -1)])
            if comp and comp.get("rows"):
                n = sum(1 for r in comp["rows"] if (r.get("esic_employee") or 0) > 0)
                return (f"🏥 {_mon_label(month)} — {firm_label}: **{n}** of "
                        f"{len(comp['rows'])} employees are ESIC eligible "
                        f"(from the {'finalized' if comp.get('finalized') else 'draft'} compliance run).",
                        None)
        q: dict = {"role": "employee", "active": {"$ne": False},
                   "compliance_gross": {"$gt": 0, "$lte": 21000}}
        if cid:
            q["company_id"] = cid
        n = await db.users.count_documents(q)
        return (f"🏥 **{n}** employees have Compliance Gross ≤ ₹21,000 (ESIC wage limit)"
                f"{' at ' + firm_label if cid else ' across all firms'}. "
                "Process the compliance salary for an exact month-wise figure.", None)

    if metric in ("absent_list", "present_count"):
        d = date or datetime.now().strftime("%Y-%m-%d")
        aq: dict = {"date": d, "kind": "in"}
        if cid:
            aq["company_id"] = cid
        present_ids = await db.attendance.distinct("user_id", aq)
        eq: dict = {"role": "employee", "active": {"$ne": False},
                    "employment_status": {"$nin": _RESIGNED_STATUSES},
                    "$or": [{"exit_date": {"$in": [None, ""]}},
                            {"exit_date": {"$exists": False}}]}
        if cid:
            eq["company_id"] = cid
        if metric == "present_count":
            total = await db.users.count_documents(eq)
            return (f"📅 {d}: **{len(present_ids)}** of {total} active employees punched IN"
                    f"{' at ' + firm_label if cid else ''}.",
                    {"type": "navigate", "route": "/attendance-grid",
                     "label": "Open Attendance Report"})
        eq["user_id"] = {"$nin": list(present_ids)}
        absent = await db.users.find(
            eq, {"_id": 0, "name": 1, "employee_code": 1}).sort("name", 1).to_list(200)
        if not absent:
            return (f"🎉 {d}: nobody is absent{' at ' + firm_label if cid else ''} — "
                    "everyone has punched IN.", None)
        head = [f"• {r.get('name')} (Code {r.get('employee_code')})" for r in absent[:15]]
        more = f"\n…and {len(absent) - 15} more." if len(absent) > 15 else ""
        return (f"🚫 {d} — {len(absent)} absent{' at ' + firm_label if cid else ''} "
                f"(no IN punch):\n" + "\n".join(head) + more,
                {"type": "navigate", "route": "/attendance-grid",
                 "label": "Open Attendance Report"})

    if metric == "employee_count":
        q: dict = {"role": "employee"}
        if cid:
            q["company_id"] = cid
        total = await db.users.count_documents(q)
        resigned = await db.users.count_documents({**q, **_resigned_query()})
        return (f"👥 {'Firm ' + firm_label if cid else 'All firms'}: **{total}** employees — "
                f"{total - resigned} ACTIVE · {resigned} RESIGNED/EXITED.",
                {"type": "navigate", "route": "/admin", "label": "Open Employee Master"})

    if metric == "top_paid":
        if not cid:
            return ("Which firm? e.g. \"top paid employees of Kankani in June\".", None)
        month = month or datetime.now().strftime("%Y-%m")
        for coll, netk in ((db.compliance_salary_runs, ("net",)),
                           (db.salary_runs, ("net_pay", "net"))):
            run = await coll.find_one({"company_id": cid, "month": month},
                                      {"_id": 0, "rows": 1}, sort=[("generated_at", -1)])
            if run and run.get("rows"):
                rows = sorted(run["rows"],
                              key=lambda r: max((r.get(k) or 0) for k in netk),
                              reverse=True)[:5]
                lines = [f"{i + 1}. {r.get('name')} (Code {r.get('employee_code')}) — "
                         f"Net {_money(max((r.get(k) or 0) for k in netk))}"
                         for i, r in enumerate(rows)]
                return (f"🏆 Top paid — {_mon_label(month)}, {firm_label}:\n"
                        + "\n".join(lines), None)
        return (f"No salary run found for {_mon_label(month)} — {firm_label}.", None)

    if metric == "run_status":
        if not cid:
            return ("Which firm? e.g. \"Is Kankani's June salary finalized?\"", None)
        month = month or datetime.now().strftime("%Y-%m")
        mon = _mon_label(month)
        comp = await _latest_run(db.compliance_salary_runs, cid, month)
        act = await _latest_run(db.salary_runs, cid, month)
        if not comp and not act:
            return (f"No salary run exists yet for {mon} — {firm_label}.", None)
        lines = [f"📋 {mon} — {firm_label}:"]
        if comp:
            lines.append(f"• Compliance: {'FINALIZED 🔒' if comp.get('finalized') else 'Draft (editable)'}"
                         f" · {comp.get('employees_count')} employees")
        if act:
            lines.append(f"• Actual: {'FINALIZED 🔒' if act.get('finalized') else 'Draft (editable)'}"
                         f" · {act.get('employees_count')} employees")
        return ("\n".join(lines), None)

    if metric == "missing_data":
        fld = (parsed.get("value") or "").lower()
        fmap = {
            "uan": ({"uan_no": {"$in": [None, ""]}}, "UAN"),
            "esic": ({"esi_ip_no": {"$in": [None, ""]}}, "ESIC IP number"),
            "aadhaar": ({"$and": [{"aadhaar_no": {"$in": [None, ""]}},
                                  {"aadhar_number": {"$in": [None, ""]}}]}, "Aadhaar"),
            "bank": ({"$or": [{"bank_account": {"$in": [None, ""]}},
                              {"bank_ifsc": {"$in": [None, ""]}}]}, "bank details"),
        }
        sub, label = fmap.get(fld) or fmap["uan"]
        q: dict = {"role": "employee", "active": {"$ne": False},
                   "employment_status": {"$nin": _RESIGNED_STATUSES}, **sub}
        if cid:
            q["company_id"] = cid
        rows = await db.users.find(q, {"_id": 0, "name": 1, "employee_code": 1}) \
            .sort("name", 1).to_list(300)
        if not rows:
            return (f"✅ No active employee is missing {label}"
                    f"{' at ' + firm_label if cid else ''}.", None)
        head = [f"• {r.get('name')} (Code {r.get('employee_code')})" for r in rows[:15]]
        more = f"\n…and {len(rows) - 15} more." if len(rows) > 15 else ""
        return (f"📋 {len(rows)} employee(s) missing {label}"
                f"{' at ' + firm_label if cid else ''}:\n" + "\n".join(head) + more,
                {"type": "navigate", "route": "/ai-payroll-assistant",
                 "label": "Open AI Payroll Assistant"})

    if metric == "pf_mismatch":
        if not cid:
            return ("Which firm? e.g. \"show PF mismatches for Kankani\".", None)
        month = month or datetime.now().strftime("%Y-%m")
        ana = await db.ai_analyses.find_one({"company_id": cid, "month": month}, {"_id": 0})
        if not ana:
            from routes.ai_layer import _analyze
            ana = await _analyze(admin, cid, month)
        pf = [f for f in ana.get("findings", []) if f["code"].startswith(("pf_", "missing_pf", "missing_uan"))]
        if not pf:
            return (f"✅ No PF issues found for {_mon_label(month)} — {firm_label}.", None)
        head = [f"• {f['issue']}{' — ' + f['employee'] if f.get('employee') else ''} ({f['confidence']}%)"
                for f in pf[:12]]
        more = f"\n…and {len(pf) - 12} more." if len(pf) > 12 else ""
        return (f"🔍 {len(pf)} PF issue(s) — {_mon_label(month)}, {firm_label}:\n"
                + "\n".join(head) + more,
                {"type": "navigate", "route": "/ai-payroll-assistant",
                 "label": "Open AI Payroll Assistant"})

    if metric == "why_salary":
        term = (parsed.get("employee_query") or "").strip()
        if not cid or not term:
            return ("Tell me the firm and employee, e.g. \"Why is Ramesh's salary lower this month?\"", None)
        month = month or datetime.now().strftime("%Y-%m")
        rows = await _find_employees(admin, cid, term, limit=2)
        if not rows:
            return (f"No employee matching \"{term}\" found at {firm_label}.", None)
        emp = rows[0]
        y, m = map(int, month.split("-"))
        pm = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
        async def _row(mon):  # noqa: E306
            run = await db.compliance_salary_runs.find_one(
                {"company_id": cid, "month": mon}, {"_id": 0, "rows": 1},
                sort=[("generated_at", -1)])
            return next((r for r in (run or {}).get("rows", [])
                         if r.get("user_id") == emp["user_id"]), None)
        cur, prv = await _row(month), await _row(pm)
        if not cur:
            return (f"{emp.get('name')} is not in the {_mon_label(month)} compliance run.", None)
        if not prv:
            return (f"{emp.get('name')} — {_mon_label(month)}: Net {_money(cur.get('net'))} "
                    f"({cur.get('present_days'):g} days). No {_mon_label(pm)} run to compare.", None)
        nd = round((cur.get("net") or 0) - (prv.get("net") or 0))
        reasons = []
        dd = (cur.get("present_days") or 0) - (prv.get("present_days") or 0)
        if abs(dd) >= 0.5:
            reasons.append(f"Present days {'+' if dd > 0 else ''}{dd:g} "
                           f"({prv.get('present_days'):g} → {cur.get('present_days'):g})")
        for k, lbl in (("ot_pay", "OT"), ("others", "Other allowances"),
                       ("total_deduction", "Deductions"), ("monthly_gross", "Gross rate")):
            d2 = round((cur.get(k) or 0) - (prv.get(k) or 0))
            if abs(d2) >= 1:
                reasons.append(f"{lbl} {'+' if d2 > 0 else ''}{_money(d2)}")
        return (f"💡 {emp.get('name')} (Code {emp.get('employee_code')}) — "
                f"{_mon_label(month)} Net {_money(cur.get('net'))} vs {_mon_label(pm)} "
                f"{_money(prv.get('net'))} → {'+' if nd >= 0 else ''}{_money(nd)}.\n"
                f"Reasons: {' · '.join(reasons) or 'no material component changes'}.", None)

    return (None, None)  # let generic answer flow


# Official portals for compliance news / notifications, by topic.
_PORTALS = {
    "pf": ("https://www.epfindia.gov.in/site_en/index.php", "EPFO Official Portal"),
    "esic": ("https://www.esic.gov.in/", "ESIC Official Portal"),
    "labour_code": ("https://labour.gov.in/", "Ministry of Labour & Employment"),
    "pt": ("https://labour.gov.in/", "Ministry of Labour & Employment"),
    "tds": ("https://incometaxindia.gov.in/", "Income Tax Department"),
    "minimum_wages": ("https://labour.gov.in/", "Ministry of Labour & Employment"),
}

_EXPERT_PROMPT = """You are a senior Indian payroll & labour-law compliance expert advising a payroll consultancy (S.K. Sharma & Co.).
Answer the operator's question about PF/EPF, ESIC, Professional Tax, TDS, minimum wages, labour codes, due dates, rates, wage ceilings, circulars/notifications and rule changes.
Rules:
- Reply in the SAME language the user wrote in (English or Hindi).
- Be CONCISE and practical: current rates/limits, effective dates, who it applies to, and what the employer must do.
- Use short bullet points (• ) — max 8 lines.
- Today is %TODAY%. If asked about "latest" news/notifications, state the most recent changes you know WITH their effective dates, and clearly add that the very latest circulars should be verified on the official portal.
- Never invent circular numbers or dates you are not sure of."""


async def _h_compliance_info(text: str, topic: Optional[str]):
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"ai-rules-{uuid.uuid4().hex[:8]}",
        system_message=_EXPERT_PROMPT.replace("%TODAY%", datetime.now().strftime("%Y-%m-%d")),
    ).with_model("openai", "gpt-5.4")
    resp = await chat.send_message(UserMessage(text=text))
    reply = str(resp).strip()
    url, label = _PORTALS.get((topic or "").lower(), _PORTALS["labour_code"])
    return (reply, {"type": "link", "url": url, "label": f"Verify on {label}"})


# ---------------------------------------------------------------------------


@router.post("/admin/ai-assistant/command")
async def ai_command(body: CommandBody, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty command")

    try:
        parsed = await _llm_parse(text)
    except Exception as e:
        logger.warning("[ai-assistant] LLM parse failed: %s", e)
        parsed = _fallback_parse(text)

    intent = parsed.get("intent") or "answer"
    reply = parsed.get("reply") or ""
    action = None

    company = await _resolve_company(admin, parsed.get("firm_name"), body.company_id)
    cid = company.get("company_id") if company else None
    firm_label = company.get("name") if company else "the selected firm"

    try:
        if intent == "process_salary":
            reply, action = await _h_process_salary(parsed, admin, cid, firm_label)

        elif intent == "finalize_salary":
            reply, action = await _h_finalize_salary(parsed, admin, cid, firm_label)

        elif intent == "report":
            reply, action = await _h_report(parsed, admin, cid, firm_label)

        elif intent == "email_report":
            reply, action = await _h_email_report(parsed, admin, cid, firm_label)

        elif intent == "employee_update":
            reply, action = await _h_employee_update(parsed, admin, cid, firm_label)

        elif intent == "bulk_salary_change":
            # Iter 589 — spec §16: bulk changes get a PREVIEW and can never
            # execute automatically. authorize() inside raises 403 when the
            # user lacks salary edit rights or firm scope.
            if not cid:
                reply = "Which firm should I apply this bulk change to? Please name the firm."
            else:
                from routes.ai_bulk_actions import build_bulk_salary_preview
                pct = parsed.get("percent")
                amt = parsed.get("amount")
                if pct is None and amt is None:
                    reply = "By how much? e.g. \"increase by 5%\" or \"increase by ₹500\"."
                else:
                    pv = await build_bulk_salary_preview(
                        admin, cid, parsed.get("department"),
                        pct=float(pct) if pct is not None else None,
                        amount=float(amt) if amt is not None else None)
                    reply = (
                        "⚠️ Bulk Salary Change Preview\n"
                        f"Firm: {pv.get('firm_name') or firm_label}\n"
                        + (f"Department: {pv['department']}\n" if pv.get("department") else "")
                        + f"Change: {pv['change_label']}\n"
                        f"Employees affected: {pv['employees_affected']}\n"
                        f"Current payroll: {_money(pv['current_payroll'])}\n"
                        f"Estimated new payroll: {_money(pv['new_payroll'])}\n"
                        f"Difference: {'+' if pv['difference'] >= 0 else ''}{_money(pv['difference'])}\n"
                        "e.g. " + "; ".join(pv["sample"][:3]))
                    action = {"type": "confirm_api", "method": "POST",
                              "endpoint": "/admin/ai-bulk/salary/execute",
                              "body": {"preview_id": pv["preview_id"]},
                              "label": ("Confirm & Execute" if admin["role"] == "super_admin"
                                        else "Send for Approval"),
                              "danger": True,
                              "success_note": (f"✅ Bulk change applied to "
                                               f"{pv['employees_affected']} employees.")}

        elif intent == "data_query":
            r2, a2 = await _h_data_query(parsed, admin, cid, firm_label, company)
            if r2 is not None:
                reply, action = r2, a2

        elif intent == "compliance_info":
            reply, action = await _h_compliance_info(text, parsed.get("employee_query"))

        elif intent == "attendance_summary":
            today = datetime.now().strftime("%Y-%m-%d")
            q: dict = {"date": today, "kind": "in"}
            if cid:
                q["company_id"] = cid
            present = len(await db.attendance.distinct("user_id", q))
            eq: dict = {"role": "employee", "active": {"$ne": False}}
            if cid:
                eq["company_id"] = cid
            total = await db.users.count_documents(eq)
            reply = (f"Today ({today}) — {present} of {total} employees have punched IN"
                     f"{' at ' + firm_label if company else ''}.")
            action = {"type": "navigate", "route": "/attendance-grid",
                      "label": "Open Attendance Report"}

        elif intent == "pending_approvals":
            pq: dict = {"status": "pending"}
            if cid:
                pq["company_id"] = cid
            punches = await db.attendance.count_documents(pq)
            sq: dict = {"status": "pending"}
            if cid:
                sq["company_id"] = cid
            shifts = await db.shift_change_requests.count_documents(sq)
            reply = (f"Pending approvals — Punches: {punches}, Shift changes: {shifts}"
                     f"{' for ' + firm_label if company else ''}.")
            action = {"type": "navigate", "route": "/approval-inbox",
                      "label": "Open Approval Inbox"}

        elif intent == "employee_search":
            term = (parsed.get("employee_query") or "").strip()
            if term:
                rows = await _find_employees(admin, cid, term, limit=5)
                if rows:
                    lines = [f"• {r.get('name')} (Code {r.get('employee_code')}"
                             f"{', ' + r['designation'] if r.get('designation') else ''}"
                             f"{', 📱 ' + r['phone'] if r.get('phone') else ''})"
                             for r in rows]
                    reply = "Found:\n" + "\n".join(lines)
                else:
                    reply = f"No employee matching \"{term}\" found."
            action = {"type": "navigate", "route": "/admin", "label": "Open Employee Master"}

        elif intent == "navigate":
            key = parsed.get("screen")
            if key in SCREENS:
                route, label = SCREENS[key]
                action = {"type": "navigate", "route": route, "label": f"Open {label}"}
                reply = reply or f"Opening {label}."
            else:
                reply = reply or ("I couldn't find that screen. Try 'open attendance "
                                  "report' or 'open salary process'.")
    except Exception as e:  # noqa: BLE001 — the assistant must never 500
        logger.exception("[ai-assistant] handler failed")
        reply = f"Something went wrong while preparing that: {str(e)[:150]}"
        action = None

    # ---- persist chat history ----
    try:
        await db.ai_chat_history.insert_many([
            {"user_id": admin["user_id"], "who": "user", "text": text, "at": _now_iso()},
            {"user_id": admin["user_id"], "who": "assistant", "text": reply,
             "action": action, "intent": intent, "at": _now_iso()},
        ])
    except Exception:
        pass
    # Iter 588 — AI Command Center: immutable audit row for every AI command
    # (alongside employee/salary/export events in the Users Log Report).
    try:
        import uuid as _uuid
        await db.activity_log.insert_one({
            "log_id": f"al_{_uuid.uuid4().hex[:12]}",
            "user_id": admin["user_id"], "user_name": admin.get("name"),
            "role": admin["role"], "action": "AI_COMMAND", "module": "ai_assistant",
            "severity": "INFO",
            "detail": {"command": text[:500], "intent": intent,
                       "company_id": cid,
                       "action_type": (action or {}).get("type"),
                       "action_label": (action or {}).get("label")},
            "at": _now_iso(),
        })
    except Exception:
        pass

    return {"reply": reply, "intent": intent, "action": action}


@router.post("/admin/ai-assistant/employee-status")
async def ai_employee_status(payload: Dict[str, Any] = Body(...),
                             authorization: Optional[str] = Header(None)):
    """Confirm-gated executor: mark an employee RESIGNED or ACTIVE.
    Sets/clears exit_date + resign_date + employment_status consistently."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    user_id = payload.get("user_id")
    status = str(payload.get("status") or "").lower()
    if status not in ("resigned", "active"):
        raise HTTPException(status_code=400, detail="status must be 'resigned' or 'active'")
    emp = await db.users.find_one({"user_id": user_id, "role": "employee"},
                                  {"_id": 0, "user_id": 1, "company_id": 1, "name": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Cross-company action blocked")
    if status == "resigned":
        updates = {"employment_status": "resigned",
                   "exit_date": payload.get("exit_date") or datetime.now().strftime("%Y-%m-%d")}
    else:
        updates = {"employment_status": None, "exit_date": None,
                   "resign_date": None, "active": True}
    await db.users.update_one({"user_id": user_id}, {"$set": updates})
    logger.info("[ai-assistant] %s marked %s by %s", user_id, status, admin["user_id"])
    return {"ok": True, "user_id": user_id, "status": status}


@router.get("/admin/ai-assistant/history")
async def ai_history(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    rows = await db.ai_chat_history.find(
        {"user_id": admin["user_id"]}, {"_id": 0}
    ).sort("at", -1).to_list(30)
    return {"messages": list(reversed(rows))}
