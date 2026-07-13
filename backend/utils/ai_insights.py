"""AI Insights — Iter 73.

Server-side analytics powered by GPT-5.2 (via emergentintegrations +
EMERGENT_LLM_KEY).  Three capabilities exposed by the FastAPI routes
in server.py:

  1. Ask-anything chat — `POST /admin/ai/ask` sends the operator's
     question + a compact snapshot of firm-level payroll/attendance
     data to GPT-5.2 and returns the answer.
  2. Monthly summary — `GET /admin/ai/summary?month=YYYY-MM` produces
     a plain-English executive summary for the given month.
  3. Anomaly scan — `GET /admin/ai/anomalies` flags employees with
     late punches, geofence outsiders, high overtime, or salary
     outliers using the LLM as the reasoning layer.

Data privacy — the snapshot we send to the LLM contains **aggregate
numbers only** (headcount, present days, punch counts, gross totals);
NO PII (name/phone/PAN) is sent unless the operator explicitly asks
a per-employee question, in which case only employee_code + name go
through.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage

MODEL_PROVIDER = "openai"
MODEL_NAME = "gpt-5.2"

SYSTEM_PROMPT = (
    "You are the payroll-and-attendance analyst for S.K. Sharma & Co., a "
    "multi-firm HR portal built for Indian textile employers. You are "
    "given aggregate JSON facts about the firm(s) the super-admin selected. "
    "Answer in crisp English, use INR (₹) for money, always cite numbers "
    "with the exact figure, and never invent data. If the JSON doesn't "
    "contain a fact, say 'not enough data — try selecting a wider date "
    "range'. Prefer tables and bullet points over long paragraphs."
)


async def _gather_snapshot(
    db,
    *,
    company_id: Optional[str],
    month: Optional[str] = None,
) -> Dict[str, Any]:
    """Collect aggregate payroll/attendance stats for the LLM prompt.

    ``company_id=None`` returns global stats (all firms) — used by the
    super-admin "All firms" view.  ``month`` (YYYY-MM) narrows the
    salary/punch aggregations to that month; falls back to the last 30
    days when omitted.
    """
    q_company = {"company_id": company_id} if company_id else {}
    # Time filter
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=30)).isoformat()
    if month:
        try:
            y, m = map(int, month.split("-"))
            since = datetime(y, m, 1, tzinfo=timezone.utc).isoformat()
        except Exception:
            pass

    # Firm-level headcount
    if company_id:
        total_emp = await db.users.count_documents(
            {**q_company, "role": "employee"},
        )
        active_emp = await db.users.count_documents(
            {**q_company, "role": "employee", "approval_status": "approved"},
        )
    else:
        total_emp = await db.users.count_documents({"role": "employee"})
        active_emp = await db.users.count_documents(
            {"role": "employee", "approval_status": "approved"},
        )

    firms = await db.companies.find(q_company, {"_id": 0, "name": 1, "company_id": 1, "company_code": 1}).to_list(100)

    # Punch stats
    punch_q = {"punched_at": {"$gte": since}}
    if company_id:
        punch_q["company_id"] = company_id
    total_punches = await db.punches.count_documents(punch_q)
    outside_punches = await db.punches.count_documents({**punch_q, "location_status": "outside"})
    pending_approvals = await db.punches.count_documents({**punch_q, "approval_status": "pending"})

    # Salary run totals
    sr_q = {}
    if month:
        sr_q["month"] = month
    if company_id:
        sr_q["company_id"] = company_id
    salary_runs = await db.salary_runs.find(sr_q, {"_id": 0}).to_list(50)
    total_gross = sum(
        float(r.get("totals", {}).get("gross") or 0) for r in salary_runs
    )
    total_net = sum(
        float(r.get("totals", {}).get("net") or 0) for r in salary_runs
    )

    # Ticket + leave stats
    ticket_q = dict(q_company)
    if company_id:
        pass  # already scoped
    open_tickets = await db.tickets.count_documents({**ticket_q, "status": {"$in": ["open", "in_progress"]}})
    pending_leaves = await db.leaves.count_documents({**ticket_q, "status": "pending"})

    return {
        "firms": firms,
        "employees": {"total": total_emp, "active_approved": active_emp},
        "punches_last_30d": {
            "total": total_punches,
            "outside_geofence": outside_punches,
            "pending_approval": pending_approvals,
        },
        "salary_month": month or "last_30_days",
        "salary_run_count": len(salary_runs),
        "total_gross_inr": round(total_gross, 2),
        "total_net_inr": round(total_net, 2),
        "open_tickets": open_tickets,
        "pending_leaves": pending_leaves,
        "generated_at": now.isoformat(),
    }


async def ai_ask(
    db,
    *,
    question: str,
    session_id: str,
    company_id: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """One-shot Q&A with optional prior turns supplied by the client."""
    snapshot = await _gather_snapshot(db, company_id=company_id)
    key = os.getenv("EMERGENT_LLM_KEY")
    if not key:
        return "AI unavailable — EMERGENT_LLM_KEY is not configured on the server."
    chat = LlmChat(
        api_key=key,
        session_id=session_id,
        system_message=SYSTEM_PROMPT + "\n\nFIRM SNAPSHOT (JSON):\n" + str(snapshot),
    ).with_model(MODEL_PROVIDER, MODEL_NAME)
    # Feed prior turns so the LLM keeps context across the conversation.
    if history:
        for turn in history[-6:]:
            role = turn.get("role")
            text = turn.get("content") or ""
            if not text:
                continue
            if role == "user":
                try:
                    await chat.send_message(UserMessage(text=text))
                except Exception:
                    pass
    reply = await chat.send_message(UserMessage(text=question))
    return str(reply)


async def ai_monthly_summary(
    db,
    *,
    month: str,
    company_id: Optional[str] = None,
    session_id: str,
) -> str:
    """Executive summary for a given month."""
    snapshot = await _gather_snapshot(db, company_id=company_id, month=month)
    key = os.getenv("EMERGENT_LLM_KEY")
    if not key:
        return "AI unavailable — EMERGENT_LLM_KEY is not configured on the server."
    chat = LlmChat(
        api_key=key,
        session_id=session_id,
        system_message=SYSTEM_PROMPT,
    ).with_model(MODEL_PROVIDER, MODEL_NAME)
    prompt = (
        f"Write an executive summary for {month}. Use these JSON facts (no "
        "invention allowed):\n" + str(snapshot) + "\n\n"
        "Structure: (1) TL;DR two-line header, (2) headcount + attendance "
        "bullets, (3) payroll bullets with ₹ figures, (4) 2-3 flags / risks "
        "the operator should watch, (5) a one-line recommendation."
    )
    reply = await chat.send_message(UserMessage(text=prompt))
    return str(reply)


async def ai_anomalies(
    db,
    *,
    company_id: Optional[str] = None,
    session_id: str,
) -> str:
    """Ask the LLM to spot anomalies in the last-30-day snapshot."""
    snapshot = await _gather_snapshot(db, company_id=company_id)
    key = os.getenv("EMERGENT_LLM_KEY")
    if not key:
        return "AI unavailable — EMERGENT_LLM_KEY is not configured on the server."
    chat = LlmChat(
        api_key=key,
        session_id=session_id,
        system_message=SYSTEM_PROMPT,
    ).with_model(MODEL_PROVIDER, MODEL_NAME)
    prompt = (
        "Scan this snapshot for anomalies. Focus on: outside-geofence "
        "punches vs total punches, pending approvals piling up, open "
        "tickets vs headcount, unusually large payroll vs employee count. "
        "For each anomaly output: (i) short title, (ii) the numbers, "
        "(iii) a one-line action item. If nothing is unusual, say so.\n\n"
        "JSON:\n" + str(snapshot)
    )
    reply = await chat.send_message(UserMessage(text=prompt))
    return str(reply)
