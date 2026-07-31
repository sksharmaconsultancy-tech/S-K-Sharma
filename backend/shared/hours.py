"""Shared punch-hour helpers (moved out of routes/attendance_core.py in
Iter 409). Used by the employee self-service summary endpoints and the
admin working-hours reports."""
from datetime import datetime
from typing import Optional


def _effective_at(rec: dict) -> Optional[str]:
    """Effective punch timestamp for hour computations. Prefers admin-adjusted
    time (set via the approvals flow) and falls back to the original."""
    return rec.get("adjusted_at") or rec.get("at")


def _is_countable(rec: dict) -> bool:
    """True if a punch should be counted toward working hours / attendance
    reports. Legacy records without a `status` field are treated as approved
    for backward-compat."""
    st = (rec.get("status") or "approved").lower()
    return st == "approved"


def _compute_day_hours(records: list) -> tuple[float, Optional[str], Optional[str], bool]:
    """Given all attendance records for a single (user, date), compute total
    duty hours by pairing consecutive IN/OUT punches in chronological order.

    Returns: (hours, first_in_iso, last_out_iso, still_in)
    Pending / rejected punches are excluded so admin decisions correctly
    influence reports and dashboards.
    """
    if not records:
        return (0.0, None, None, False)
    # Filter to countable records first, then order by effective time.
    countable = [r for r in records if _is_countable(r)]
    recs = sorted(countable, key=lambda r: _effective_at(r) or "")
    total_seconds = 0.0
    open_in: Optional[datetime] = None
    first_in: Optional[str] = None
    last_out: Optional[str] = None
    for r in recs:
        kind = (r.get("kind") or "").lower()
        at = _effective_at(r)
        try:
            dt = datetime.fromisoformat((at or "").replace("Z", "+00:00"))
        except Exception:
            continue
        if kind == "in":
            if open_in is None:
                open_in = dt
                if first_in is None:
                    first_in = at
        elif kind == "out":
            last_out = at
            if open_in is not None:
                total_seconds += max(0.0, (dt - open_in).total_seconds())
                open_in = None
    still_in = open_in is not None
    hours = round(total_seconds / 3600.0, 2)
    return (hours, first_in, last_out, still_in)
