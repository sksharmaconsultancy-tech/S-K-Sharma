"""Iter 399 — pure date / payroll-month helpers (no DB, no FastAPI).

Moved out of routes/attendance_core.py so every module can import them
directly (`from shared.dates import ...`) without going through
server.py's namespace."""
from datetime import datetime, timezone
from typing import Any, Optional


def _last_completed_month(now: datetime) -> str:
    """Return 'YYYY-MM' of the month that just completed (i.e. previous month)."""
    if now.month == 1:
        return f"{now.year - 1}-12"
    return f"{now.year}-{now.month - 1:02d}"


def _parse_any_date(val: Any) -> Optional[datetime]:
    """Iter 170 — tolerant date parser for exit/leaving dates that may be
    stored as YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY or YYYY/MM/DD."""
    s = str(val or "").strip()[:10].replace("/", "-")
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        pass
    try:
        d, m, y = s.split("-")
        if len(y) == 4:
            return datetime(int(y), int(m), int(d))
    except Exception:
        pass
    return None


def _month_is_after_exit(user: dict, month_str: str) -> bool:
    """Iter 166/170 — True when the employee is resigned/exited and must be
    excluded from salary processing (user directive: applies to BOTH the
    Compliance and the Actual salary process).

    Rules:
      * exit/leaving date BEFORE the 1st of the run month → excluded;
      * exit date DURING the run month → still payable (final settlement);
      * marked resigned/exited (employment_status) with NO parseable date,
        or an unreadable exit date → excluded entirely (can't determine
        the month, so never show them in a salary run).
    """
    ed = (user.get("exit_date") or user.get("resign_date")
          or user.get("date_of_leaving") or user.get("leaving_date"))
    status_resigned = str(user.get("employment_status") or "").strip().lower() in (
        "exited", "resigned", "terminated", "inactive", "left")
    if not ed:
        return status_resigned  # marked resigned without a date → exclude
    dt = _parse_any_date(ed)
    if dt is None:
        return True  # exit marker present but unreadable → exclude
    try:
        y, m = int(month_str[:4]), int(month_str[5:7])
        return dt < datetime(y, m, 1)
    except Exception:
        return True


def _employee_inactive_for_report(user: dict, month_str: str) -> bool:
    """Iter 321 (user request) — attendance reports show ACTIVE employees
    only. Excluded when flagged disabled / active=False, or resigned/exited
    BEFORE the report month. An exit DURING the report month still shows
    (they worked part of it)."""
    if user.get("disabled") is True or user.get("active") is False:
        return True
    return _month_is_after_exit(user, month_str)


def _month_is_before_doj(user: dict, month_str: str) -> bool:
    """Return True when the given 'YYYY-MM' precedes the employee's DOJ.

    We compare using month-end. If DOJ is inside the run month, the employee
    is INCLUDED (their attendance count will already be zero for the days
    before joining). If DOJ falls in a later month, the employee is EXCLUDED.
    """
    doj = user.get("doj")
    if not doj:
        return False  # no DOJ set — can't exclude
    try:
        # Parse both dates
        y, m = int(month_str[:4]), int(month_str[5:7])
        # Month end = the 28th of the next month (safe upper bound so that
        # a DOJ on the 31st of the run month still classifies as "in").
        if m == 12:
            end_of_run = datetime(y + 1, 1, 1)
        else:
            end_of_run = datetime(y, m + 1, 1)
        # Iter 377 — legacy imports store DOJ as DD-MM-YYYY; use the
        # tolerant parser so those employees are filtered correctly too.
        doj_dt = _parse_any_date(doj)
        if doj_dt is None:
            return False
        return doj_dt >= end_of_run
    except Exception:
        return False


def _month_is_complete(month_str: str, now: Optional[datetime] = None) -> bool:
    """Return True when the 'YYYY-MM' month is entirely in the past."""
    now = now or datetime.now(timezone.utc)
    try:
        y, m = int(month_str[:4]), int(month_str[5:7])
    except Exception:
        return False
    if y < now.year:
        return True
    if y > now.year:
        return False
    return m < now.month


def _payslip_is_processed(slip: dict) -> bool:
    """True when a payslip has been genuinely PROCESSED (pushed from a
    salary run OR marked paid), not just auto-created as pending."""
    if not slip:
        return False
    if slip.get("salary_run_id") or slip.get("compliance_salary_run_id"):
        return True
    return (slip.get("status") or "").lower() == "paid"


