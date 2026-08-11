"""Iter 545 — Configurable MULTIPLE PUNCH & MAXIMUM PUNCH policy (user spec).

Shared validation helpers used by EVERY punch ingest path (mobile/PWA app
punch, biometric machine sync). Manual admin punches intentionally bypass
these checks (existing audit-logged correction workflow, spec Case 7).

Policy resolution hierarchy (existing convention preserved):
    employee ``attendance_policy_override`` → firm
    ``attendance_policy.policy_master`` → system default.

Backward compatibility: firms that have NEVER saved the new policy fields
have no ``maximum_punches_per_day`` in their stored policy_master → the
limit resolves to 0 (= unlimited, exact legacy behaviour). Once the firm
saves its Attendance Policy the sanitiser writes the default (4) and
enforcement starts — historical attendance is never recalculated.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

# Punches with these statuses count toward the daily punch limit. Noise
# statuses (rejected / duplicate / auto_ignored / exception) never count.
COUNTED_STATUSES = ("approved", "pending")


def resolve_punch_policy(user: Optional[dict], company: Optional[dict]) -> Dict[str, Any]:
    """Effective punch policy for one employee."""
    pm = ((company or {}).get("attendance_policy") or {}).get("policy_master") or {}
    ov = (user or {}).get("attendance_policy_override") or {}

    def pick(key: str, default):
        v = ov.get(key)
        if v is None:
            v = pm.get(key)
        return default if v is None else v

    multiple = bool(pick("multiple_punch_allowed", True))
    try:
        max_p = int(pick("maximum_punches_per_day", 0) or 0)
    except (TypeError, ValueError):
        max_p = 0
    if max_p and max_p < 2:
        max_p = 2
    # Multiple Punch = NO → exactly one IN → OUT cycle (2 punches).
    effective_max = 2 if not multiple else max_p  # 0 = unlimited (legacy)
    extra = str(pick("extra_punch_action", "reject") or "reject").lower()
    if extra not in ("reject", "exception"):
        extra = "reject"
    inval = str(pick("invalid_sequence_action", "reject") or "reject").lower()
    if inval not in ("reject", "exception"):
        inval = "reject"
    return {
        "multiple_punch_allowed": multiple,
        "maximum_punches_per_day": max_p,
        "effective_max": effective_max,
        "extra_punch_action": extra,
        "invalid_sequence_action": inval,
        "punch_sequence": "in_out_alternate",
    }


def counted_punches(recs: List[dict]) -> List[dict]:
    """The punches of a day that count toward the limit."""
    return [
        r for r in (recs or [])
        if (r.get("status") or "approved") in COUNTED_STATUSES
        and r.get("kind") in ("in", "out")
    ]


async def log_punch_exception(
    db, *,
    user: dict,
    company_id: Optional[str],
    date: str,
    at: str,
    kind: str,
    exception_type: str,
    reason: str,
    policy: Dict[str, Any],
    existing_count: int,
    source: str,
    device_serial: Optional[str] = None,
) -> None:
    """Record a rejected/exception punch attempt in the Punch Exception Log
    (Attendance Exception Report). Never raises."""
    try:
        await db.punch_exceptions.insert_one({
            "exception_id": f"pex_{uuid.uuid4().hex[:12]}",
            "company_id": company_id,
            "user_id": (user or {}).get("user_id"),
            "employee_code": (user or {}).get("employee_code"),
            "name": (user or {}).get("name"),
            "date": date,
            "at": at,
            "kind": kind,
            "exception_type": exception_type,
            "reason": reason,
            "policy_applied": {
                "multiple_punch_allowed": policy.get("multiple_punch_allowed"),
                "maximum_punches_per_day": policy.get("maximum_punches_per_day"),
                "extra_punch_action": policy.get("extra_punch_action"),
                "invalid_sequence_action": policy.get("invalid_sequence_action"),
            },
            "max_punches_allowed": policy.get("effective_max") or None,
            "existing_punch_count": existing_count,
            "source": source,
            "device_serial": device_serial,
            "created_at": datetime.utcnow().isoformat() + "Z",
        })
    except Exception:
        pass
