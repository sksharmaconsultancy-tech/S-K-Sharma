"""Iter 86 - Route module: Attendance policy metadata.

Exposes the STANDARD non-textile attendance policy so the admin UI
can pretty-print the rules that apply firm-wide when a firm hasn't
overridden them.

Endpoints:
  * GET /api/attendance/standard-policy - returns the standard preset
                                          + a human-readable summary
                                          for on-screen display.
  * GET /api/attendance/policy-presets  - full preset catalogue
                                          (all categories, incl.
                                          textile) for reference.
"""
from typing import Optional

from fastapi import APIRouter, Header

from server import (  # noqa: E402
    get_user_from_token,
    ATTENDANCE_POLICY_PRESETS,
)

router = APIRouter(prefix="/api", tags=["attendance-policy"])


_STANDARD_SUMMARY = {
    "title": "Standard Attendance Policy (Non-Textile Firms)",
    "applies_to": (
        "Every firm category EXCEPT Textile. Textile firms follow their "
        "own 12-hr rotational-shift policy variant."
    ),
    "rules": [
        {"label": "Shift", "value": "09:00 — 18:00 (9-hour window, 1 hr unpaid break)"},
        {"label": "Weekly off", "value": "Sunday"},
        {"label": "Grace on late arrival", "value": "10 minutes"},
        {"label": "Half day", "value": "Duty hours < 4.0"},
        {"label": "Full day", "value": "Duty hours ≥ 8.0"},
        {"label": "OT threshold", "value": "Any duty hour BEYOND 8.0 counts as OT"},
        {"label": "OT multiplier", "value": "1.5× (Factories-Act aligned)"},
        {"label": "Duty-hour rounding", "value": "15 minutes"},
        {"label": "Night-shift allowance", "value": "Off (enable per firm if applicable)"},
        {
            "label": "Week-off / holiday work",
            "value": "Counted as a FULL DAY (all hours contribute to Present Days)",
        },
    ],
    "override": (
        "Any single rule can be overridden per-firm on the Attendance "
        "Policy screen, or per-employee via attendance_policy_override."
    ),
}


@router.get("/attendance/standard-policy")
async def get_standard_policy(authorization: Optional[str] = Header(None)):
    """Return the STANDARD non-textile attendance policy preset + a
    human-readable summary."""
    await get_user_from_token(authorization)  # any authenticated user may read
    preset = ATTENDANCE_POLICY_PRESETS.get("standard") or {}
    return {
        "summary": _STANDARD_SUMMARY,
        "preset": preset,
    }


@router.get("/attendance/policy-presets")
async def list_policy_presets(authorization: Optional[str] = Header(None)):
    """Return the full catalogue of policy presets (textile + non-
    textile) so the admin UI can show the effective rules per
    category."""
    await get_user_from_token(authorization)
    return {
        "presets": {k: v for k, v in ATTENDANCE_POLICY_PRESETS.items()},
        "standard_summary": _STANDARD_SUMMARY,
    }
