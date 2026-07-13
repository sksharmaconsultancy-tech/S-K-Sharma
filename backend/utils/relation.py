"""Relation-aware name display (user directive).

In reports, the "Father Name" value follows Indian statutory convention:
  * Female + Unmarried  -> "D/O <father name>"  (Daughter of)
  * Female + Married    -> spouse name ONLY (fallback father name if blank)
  * Everyone else       -> father name as-is
"""
from typing import Any, Dict


def father_or_spouse_display(u: Dict[str, Any]) -> str:
    gender = (u.get("gender") or "").strip().lower()
    ms = (u.get("marital_status") or "").strip().lower()
    father = (u.get("father_name") or "").strip()
    spouse = (u.get("spouse_name") or "").strip()
    if gender == "female":
        if ms == "married":
            return spouse or father
        return f"D/O {father}" if father else ""
    return father
