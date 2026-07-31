"""Shared report-sorting helpers (moved out of server.py in Iter 409).

``_sort_export_rows`` is used by both the Actual (legacy) salary-run
exports and the Compliance salary-run exports.
"""
from typing import Optional


def _sort_export_rows(rows: list, sort_by: Optional[str]) -> list:
    """Iter 98 — optional report sorting for salary/compliance exports.
    ``sort_by``: name | code | net | gross (net/gross sort descending)."""
    if not sort_by or not rows:
        return rows

    def _code_key(r):
        c = str(r.get("employee_code") or "").strip()
        try:
            return (0, float(c), "")
        except ValueError:
            return (1, 0.0, c.lower())

    keymap = {
        "name": lambda r: (r.get("name") or "").lower(),
        "code": _code_key,
        "net": lambda r: -float(
            r.get("net") if r.get("net") is not None else (r.get("net_pay") or 0.0)
        ),
        "gross": lambda r: -float(
            r.get("gross") if r.get("gross") is not None else (r.get("total_gross") or 0.0)
        ),
    }
    fn = keymap.get(str(sort_by).lower())
    return sorted(rows, key=fn) if fn else rows
