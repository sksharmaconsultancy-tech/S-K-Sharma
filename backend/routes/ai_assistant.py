"""AI Payroll Assistant — natural-language + voice command engine.

POST /api/admin/ai-assistant/command
    Body {text, company_id?} → parses the operator's command with an LLM
    (Emergent universal key, gpt-5.4) into a structured intent, resolves
    entities (firm name → company_id, month), answers data questions
    directly from Mongo and returns an optional executable *action* the
    frontend can run after user confirmation:
      { type: "navigate", route }
      { type: "confirm_api", method, endpoint, body, label, navigate_after }

GET /api/admin/ai-assistant/history — last 30 exchanges for this user.
"""
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Header, HTTPException
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
}

SYSTEM_PROMPT = """You are the AI command parser for an Indian payroll & attendance web portal (S.K. Sharma & Co.).
Parse the operator's command into STRICT JSON (no markdown, no prose) with this schema:
{
  "intent": "process_payroll" | "attendance_summary" | "pending_approvals" | "employee_search" | "navigate" | "answer",
  "salary_type": "actual" | "compliance" | "ot" | "arrear" | null,
  "month": "YYYY-MM" | null,
  "firm_name": string | null,
  "employee_query": string | null,
  "screen": one of [%SCREENS%] | null,
  "reply": short helpful sentence in the SAME language the user wrote in (English or Hindi)
}
Rules:
- "Process July payroll" → intent=process_payroll, salary_type=actual, month resolved to the CURRENT YEAR (today is %TODAY%). If the month is in the future relative to today, use the previous year.
- "compliance salary", "PF salary" → salary_type=compliance. "overtime/OT salary" → ot. "arrear" → arrear.
- Attendance questions ("who is present today", "aaj kitne log aaye") → attendance_summary.
- "pending approvals" → pending_approvals.
- "find employee Ramesh", "show Suresh's details" → employee_search with employee_query.
- "open X" / "go to X" / "show X screen" → navigate with the best matching screen key.
- Anything else (greetings, general payroll/compliance questions) → answer, and put your best short answer in reply.
Return ONLY the JSON object."""


class CommandBody(BaseModel):
    text: str
    company_id: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _fallback_parse(text: str) -> dict:
    """Regex fallback when the LLM is unreachable — covers the core commands."""
    t = text.lower()
    out: dict = {"intent": "answer", "salary_type": None, "month": None,
                 "firm_name": None, "employee_query": None, "screen": None,
                 "reply": "Sorry, I couldn't reach the AI service. Try a simple command like 'Process July payroll'."}
    month = None
    for name, num in MONTHS.items():
        if name in t or name[:3] in re.findall(r"[a-z]{3,}", t):
            today = datetime.now()
            year = today.year if num <= today.month else today.year - 1
            month = f"{year}-{num:02d}"
            break
    if "payroll" in t or "salary" in t and ("process" in t or "run" in t):
        out.update({"intent": "process_payroll", "salary_type": "actual",
                    "month": month, "reply": "Processing payroll."})
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
    # Strip accidental code fences
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
        c = await db.companies.find_one({"company_id": cid}, {"_id": 0, "company_id": 1, "name": 1})
        return c
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

    if intent == "process_payroll":
        month = parsed.get("month")
        stype = parsed.get("salary_type") or "actual"
        if not month:
            reply = "Which month should I process? e.g. \"Process July 2026 payroll\"."
        elif not cid:
            reply = f"Which firm should I process {month} payroll for? Say the firm name or select one from the top bar."
        else:
            mon_label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
            if stype == "actual":
                action = {
                    "type": "confirm_api",
                    "method": "POST",
                    "endpoint": "/admin/salary-runs",
                    "body": {"month": month, "company_id": cid},
                    "label": f"Run {mon_label} Actual Payroll — {firm_label}",
                    "navigate_after": "/salary-run",
                }
                reply = (f"Ready to process **{mon_label} Actual Payroll** for "
                         f"**{firm_label}**. Press Confirm below to run it.")
            else:
                route = {"compliance": "/compliance-salary-run",
                         "ot": "/ot-salary-run",
                         "arrear": "/arrear-salary-run"}[stype]
                action = {"type": "navigate", "route": route,
                          "label": f"Open {stype.title()} Salary Process"}
                reply = (f"I've prepared the {stype.title()} Salary screen for "
                         f"{mon_label} — {firm_label}. Open it below and press Process.")

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
        action = {"type": "navigate", "route": "/attendance-grid", "label": "Open Attendance Report"}

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
        action = {"type": "navigate", "route": "/approval-inbox", "label": "Open Approval Inbox"}

    elif intent == "employee_search":
        term = (parsed.get("employee_query") or "").strip()
        if term:
            eq2: dict = {"role": "employee", "$or": [
                {"name": {"$regex": re.escape(term), "$options": "i"}},
                {"employee_code": {"$regex": f"^{re.escape(term)}", "$options": "i"}},
            ]}
            if admin["role"] == "company_admin":
                eq2["company_id"] = admin.get("company_id")
            elif cid:
                eq2["company_id"] = cid
            rows = await db.users.find(eq2, {"_id": 0, "name": 1, "employee_code": 1,
                                             "designation": 1, "company_id": 1}).to_list(5)
            if rows:
                lines = [f"• {r.get('name')} (Code {r.get('employee_code')}"
                         f"{', ' + r['designation'] if r.get('designation') else ''})"
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
            reply = reply or "I couldn't find that screen. Try 'open attendance report' or 'open salary process'."

    # ---- persist chat history ----
    try:
        await db.ai_chat_history.insert_many([
            {"user_id": admin["user_id"], "who": "user", "text": text, "at": _now_iso()},
            {"user_id": admin["user_id"], "who": "assistant", "text": reply,
             "action": action, "intent": intent, "at": _now_iso()},
        ])
    except Exception:
        pass

    return {"reply": reply, "intent": intent, "action": action}


@router.get("/admin/ai-assistant/history")
async def ai_history(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    rows = await db.ai_chat_history.find(
        {"user_id": admin["user_id"]}, {"_id": 0}
    ).sort("at", -1).to_list(30)
    return {"messages": list(reversed(rows))}
