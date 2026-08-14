"""Iter 568 — Detailed Audit Trail helpers.

Shared between the `_activity_logger` middleware in server.py (which
records every mutating request) and routes/reports_extra.py (which
serves the Users Log Report).

Provides:
  * AUDIT_RESOURCES — path-pattern → (collection, id_field, module)
    map used by the middleware to pre-fetch the OLD document before an
    UPDATE/DELETE so field-level old→new diffs can be recorded.
  * derive_module(path) — human module name from an API path.
  * compute_changes(old_doc, body) — field-level diff list.
  * snapshot(doc) — sanitized snapshot of a doc (for DELETE logging).
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

SENSITIVE = ("pin", "password", "token", "otp", "captcha", "secret",
             "hmac", "api_key")

# Path regex → (collection, id_query_field, module).  First group of the
# regex is the record id.  Order matters — first match wins.
AUDIT_RESOURCES: List[Tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"^/api/admin/employees/([A-Za-z0-9_\-]+)"), "users", "user_id", "Employee"),
    (re.compile(r"^/api/employees/([A-Za-z0-9_\-]+)"), "users", "user_id", "Employee"),
    (re.compile(r"^/api/admin/sub-admins/([A-Za-z0-9_\-]+)"), "users", "user_id", "User Management"),
    (re.compile(r"^/api/admin/company-staff/([A-Za-z0-9_\-]+)"), "users", "user_id", "User Management"),
    (re.compile(r"^/api/admin/attendance/([A-Za-z0-9_\-]+)$"), "attendance", "record_id", "Attendance"),
    (re.compile(r"^/api/companies/([A-Za-z0-9_\-]+)$"), "companies", "company_id", "Firm Settings"),
    (re.compile(r"^/api/admin/firm-master/([A-Za-z0-9_\-]+)"), "firm_masters", "company_id", "Firm Settings"),
    (re.compile(r"^/api/admin/advances/([A-Za-z0-9_\-]+)"), "advances", "advance_id", "Advances"),
    (re.compile(r"^/api/(?:admin/)?leaves/([A-Za-z0-9_\-]+)"), "leaves", "leave_id", "Leave"),
    (re.compile(r"^/api/admin/shift-masters/([A-Za-z0-9_\-]+)"), "shift_masters", "shift_id", "Shift"),
    (re.compile(r"^/api/admin/masters/([A-Za-z0-9_\-]+)"), "masters", "master_id", "Masters"),
    (re.compile(r"^/api/admin/employee-groups/([A-Za-z0-9_\-]+)"), "employee_groups", "group_id", "Employee"),
    (re.compile(r"^/api/admin/punch-api/clients/([A-Za-z0-9_\-]+)"), "api_clients", "client_id", "Punching API"),
]

_LABEL_FIELDS = ("name", "full_name", "employee_name", "title", "label",
                 "user_id", "record_id", "company_id")

# Keyword → module (checked in order on the URL path).
_MODULE_KEYWORDS = [
    ("login", "Auth"), ("auth", "Auth"),
    ("employee", "Employee"), ("bulk-import", "Employee"), ("kyc", "Employee"),
    ("attendance", "Attendance"), ("punch", "Attendance"), ("shift", "Attendance"),
    ("biometric", "Attendance"), ("geo", "Attendance"), ("comp-off", "Attendance"),
    ("salary", "Payroll"), ("payroll", "Payroll"), ("payslip", "Payroll"),
    ("advance", "Payroll"), ("bonus", "Payroll"), ("arrear", "Payroll"),
    ("form16", "Payroll"), ("ctc", "Payroll"), ("bank-transfer", "Payroll"),
    ("compliance", "Compliance"), ("challan", "Compliance"), ("register", "Compliance"),
    ("clra", "Compliance"), ("factory", "Compliance"), ("returns", "Compliance"),
    ("pf", "Compliance"), ("esic", "Compliance"), ("uan", "Compliance"),
    ("leave", "Leave"),
    ("compan", "Firm Settings"), ("firm", "Firm Settings"), ("settings", "Settings"),
    ("config", "Settings"), ("masters", "Masters"), ("policy", "Settings"),
    ("sub-admin", "User Management"), ("super-admin", "User Management"),
    ("staff", "User Management"), ("roles", "User Management"), ("rights", "User Management"),
    ("users", "User Management"), ("access", "User Management"),
    ("report", "Reports"), ("export", "Reports"), ("download", "Reports"),
    ("whatsapp", "Messaging"), ("email", "Messaging"), ("message", "Messaging"),
    ("notification", "Messaging"),
    ("document", "Documents"), ("backup", "System"), ("portal", "Portal"),
    ("ticket", "Tickets"), ("claim", "Claims"), ("contractor", "Contractors"),
]


def derive_module(path: str) -> str:
    p = (path or "").lower()
    for kw, mod in _MODULE_KEYWORDS:
        if kw in p:
            return mod
    return "Other"


def match_resource(path: str):
    """Returns (collection, id_field, record_id, module) or None."""
    for rx, coll, id_field, module in AUDIT_RESOURCES:
        m = rx.match(path)
        if m:
            return coll, id_field, m.group(1), module
    return None


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(s in k for s in SENSITIVE)


def _fmt(v: Any, limit: int = 300) -> str:
    """Stringify a value for display (truncated)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float, str)):
        return str(v)[:limit]
    try:
        return json.dumps(v, default=str, ensure_ascii=False)[:limit]
    except (TypeError, ValueError):
        return str(v)[:limit]


def compute_changes(old_doc: Optional[dict], body: Any,
                    max_fields: int = 40) -> List[Dict[str, str]]:
    """Field-level diff between the stored document and the request body.

    Only fields PRESENT IN THE BODY are compared (a PUT/PATCH payload is
    the source of truth for what the user intended to change).
    Sensitive fields are redacted; unchanged fields are skipped.
    """
    if not isinstance(body, dict):
        return []
    old_doc = old_doc or {}
    changes: List[Dict[str, str]] = []
    for k, new_v in body.items():
        if k in ("_id", "company_id", "user_id"):
            continue
        old_v = old_doc.get(k)
        if _is_sensitive(k):
            if old_v != new_v:
                changes.append({"field": k, "old": "•••", "new": "••• (changed)"})
            continue
        old_s, new_s = _fmt(old_v), _fmt(new_v)
        if old_s == new_s:
            continue
        changes.append({"field": k, "old": old_s, "new": new_s})
        if len(changes) >= max_fields:
            break
    return changes


def snapshot(doc: Optional[dict], max_fields: int = 30) -> Dict[str, str]:
    """Sanitized flat snapshot of a document (used for DELETE / CREATE)."""
    if not isinstance(doc, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in doc.items():
        if k == "_id" or _is_sensitive(k):
            continue
        s = _fmt(v, 120)
        if s:
            out[k] = s
        if len(out) >= max_fields:
            break
    return out


def record_label(doc: Optional[dict]) -> str:
    for f in _LABEL_FIELDS:
        v = (doc or {}).get(f)
        if v and isinstance(v, str):
            return v[:80]
    return ""
