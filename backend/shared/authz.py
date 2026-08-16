"""Iter 585 — CENTRAL AUTHORIZATION SERVICE (RBAC Phase 1).

The SINGLE source of truth for authorization in emplo-connect-1:

    USER → ROLE → FIRM SCOPE → BRANCH SCOPE → DEPARTMENT SCOPE
         → MODULE → ACTION (view/add/edit/delete/export/approve)
         → ALLOW or HTTP 403

Every protected module (Employee, Attendance, Salary, PF, ESIC, Reports and
all future modules) must call ``authorize()`` / ``scope_filter()`` /
``assert_employee_in_scope()`` from here instead of writing its own checks.

Backward compatibility (nobody loses access):
  * legacy ``module:read``  → VIEW + EXPORT   (read already allowed report
    downloads in the existing endpoints)
  * legacy ``module:write`` → ADD + EDIT + DELETE + APPROVE (write already
    allowed deletes and approvals in the existing endpoints)
  * new granular grants use ``module:view`` … ``module:approve`` and take
    effect alongside the legacy keys.
  * users WITHOUT a branch_scope / department_scope doc default to ALL
    (existing behaviour preserved).
"""
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

ACTIONS = ["view", "add", "edit", "delete", "export", "approve"]

# Legacy expansion — preserves every user's current effective access.
_LEGACY = {"read": ["view", "export"],
           "write": ["add", "edit", "delete", "approve"]}


def _expand(perms: List[str]) -> set:
    """Expand a raw permission list (legacy + granular) into module:action."""
    out: set = set()
    for p in perms or []:
        if ":" not in p:
            continue
        mod, act = p.rsplit(":", 1)
        for a in _LEGACY.get(act, [act] if act in ACTIONS else []):
            out.add(f"{mod}:{a}")
        if act not in _LEGACY and act not in ACTIONS:
            out.add(p)  # unknown/custom key kept verbatim (e.g. sensitive_data:view later)
    return out


def _user_perms(user: dict) -> Optional[set]:
    """Raw permission set for the roles that carry one. ``None`` means the
    role is not permission-gated (real company_admin / super_admin)."""
    role = user.get("role")
    if role == "sub_admin":
        return _expand(user.get("sub_admin_permissions") or [])
    if role == "company_admin" and user.get("is_company_staff"):
        return _expand(user.get("staff_permissions") or [])
    return None


# ── Scope helpers ──────────────────────────────────────────────────────────
def firm_ok(user: dict, company_id: Optional[str]) -> bool:
    role = user.get("role")
    if role == "super_admin":
        return True
    if role == "sub_admin":
        if (user.get("sub_admin_company_scope") or "all") == "all":
            return True
        return (not company_id) or company_id in (user.get("sub_admin_company_ids") or [])
    if role in ("company_admin", "employee", "company_staff"):
        return bool(company_id) and company_id == user.get("company_id")
    return False


def _scope_ids(user: dict, key: str) -> Optional[List[str]]:
    """None → ALL. List → restricted to these ids. Missing doc → ALL
    (backward compatible)."""
    sc = user.get(key)
    if not isinstance(sc, dict) or sc.get("all", True):
        return None
    return [str(x) for x in (sc.get("ids") or [])]


def branch_ids(user: dict) -> Optional[List[str]]:
    if user.get("role") == "super_admin":
        return None
    return _scope_ids(user, "branch_scope")


def department_ids(user: dict) -> Optional[List[str]]:
    if user.get("role") == "super_admin":
        return None
    return _scope_ids(user, "department_scope")


def scope_filter(user: dict, field_branch: str = "branch_id",
                 field_dept: str = "department_id") -> Dict[str, Any]:
    """Mongo filter fragment enforcing the user's branch/department scope.
    Merge into every employee-based query — records without the field are
    excluded when a restriction exists (server-side, never frontend)."""
    q: Dict[str, Any] = {}
    b = branch_ids(user)
    if b is not None:
        q[field_branch] = {"$in": b}
    d = department_ids(user)
    if d is not None:
        q[field_dept] = {"$in": d}
    return q


async def scoped_user_id_set(db, user: dict):
    """None → unrestricted. Otherwise the set of employee user_ids inside
    the user's branch/department scope — for filtering salary/report rows
    that don't carry branch/department fields directly."""
    q = scope_filter(user)
    if not q:
        return None
    ids = await db.users.distinct("user_id", {"role": "employee", **q})
    return set(ids)


def employee_in_scope(user: dict, emp: dict) -> bool:
    """ID-manipulation protection for a single employee document."""
    if user.get("role") == "super_admin":
        return True
    if user.get("role") == "employee":
        return emp.get("user_id") == user.get("user_id")
    if not firm_ok(user, emp.get("company_id")):
        return False
    b = branch_ids(user)
    if b is not None and str(emp.get("branch_id") or "") not in b:
        return False
    d = department_ids(user)
    if d is not None and str(emp.get("department_id") or "") not in d:
        return False
    return True


def assert_employee_in_scope(user: dict, emp: dict) -> None:
    if not employee_in_scope(user, emp):
        raise HTTPException(status_code=403,
                            detail="Forbidden — record is outside your "
                                   "firm/branch/department scope")


# ── The central check ──────────────────────────────────────────────────────
def has_permission(user: dict, module: str, action: str) -> bool:
    if user.get("role") == "super_admin":
        return True
    perms = _user_perms(user)
    if perms is None:  # real company_admin — full access inside own firm
        return user.get("role") == "company_admin"
    return f"{module}:{action}" in perms


def authorize(user: dict, module: str, action: str,
              company_id: Optional[str] = None,
              branch_id: Optional[str] = None,
              department_id: Optional[str] = None,
              employee: Optional[dict] = None) -> None:
    """Single centralized check. Raises HTTP 403 on the FIRST failed layer:
    role → firm scope → branch scope → department scope → module:action."""
    role = user.get("role")
    if role == "super_admin":
        return
    if role == "employee":
        raise HTTPException(status_code=403, detail="Forbidden")
    if action not in ACTIONS:
        raise HTTPException(status_code=403, detail=f"Unknown action '{action}'")
    if company_id is not None and not firm_ok(user, company_id):
        raise HTTPException(status_code=403,
                            detail="Forbidden — firm is outside your scope")
    if branch_id is not None:
        b = branch_ids(user)
        if b is not None and str(branch_id) not in b:
            raise HTTPException(status_code=403,
                                detail="Forbidden — branch is outside your scope")
    if department_id is not None:
        d = department_ids(user)
        if d is not None and str(department_id) not in d:
            raise HTTPException(status_code=403,
                                detail="Forbidden — department is outside your scope")
    if employee is not None:
        assert_employee_in_scope(user, employee)
    if not has_permission(user, module, action):
        raise HTTPException(status_code=403,
                            detail=f"Forbidden — you lack {module}:{action} permission")


# ── Access Preview (effective access, same engine, read-only) ──────────────
async def get_effective_access(db, target: dict,
                               modules: List[str]) -> Dict[str, Any]:
    """Effective access for a user — used by Access Preview. Uses the exact
    same evaluation functions that protect the APIs (no duplicate logic)."""
    role = target.get("role")
    # firms
    if role == "super_admin":
        firm_mode, firm_ids = "ALL_FIRMS", None
    elif role == "sub_admin":
        if (target.get("sub_admin_company_scope") or "all") == "all":
            firm_mode, firm_ids = "ALL_FIRMS", None
        else:
            firm_mode, firm_ids = "RESTRICTED_FIRMS", (target.get("sub_admin_company_ids") or [])
    elif role in ("company_admin",):
        firm_mode, firm_ids = "OWN_FIRM", [target.get("company_id")]
    else:
        firm_mode, firm_ids = "OWN_RECORD", [target.get("company_id")]
    fq = {} if firm_ids is None else {"company_id": {"$in": [f for f in firm_ids if f]}}
    firms = await db.companies.find(fq, {"_id": 0, "company_id": 1, "name": 1}).to_list(500)

    b = branch_ids(target)
    d = department_ids(target)
    matrix: Dict[str, Dict[str, bool]] = {}
    for m in modules:
        matrix[m] = {a: has_permission(target, m, a) for a in ACTIONS}

    # effective employee count (server-side scoped — same filter the APIs use)
    if role == "employee":
        emp_q: Dict[str, Any] = {"user_id": target.get("user_id")}
    else:
        emp_q = {"role": "employee", **({} if firm_ids is None else
                                        {"company_id": {"$in": [f for f in firm_ids if f]}}),
                 **scope_filter(target)}
    emp_count = await db.users.count_documents(emp_q)
    return {
        "user": {"user_id": target.get("user_id"), "name": target.get("name"),
                 "email": target.get("email"), "role": role,
                 "twofa_enabled": bool(target.get("twofa_enabled")),
                 "last_login_at": target.get("last_login_at"),
                 "created_at": target.get("created_at")},
        "firm_scope": {"mode": firm_mode, "firms": firms},
        "branch_scope": {"mode": "ALL_BRANCHES" if b is None else "SELECTED_BRANCHES",
                         "branch_ids": b},
        "department_scope": {"mode": "ALL_DEPARTMENTS" if d is None else "SELECTED_DEPARTMENTS",
                             "department_ids": d},
        "matrix": matrix,
        "sensitive_data_view": can_view_sensitive(target),
        "counts": {"firms": len(firms), "employees": emp_count},
    }


# ── Iter 586 — SENSITIVE FIELD MASKING (RBAC Phase 2 core) ─────────────────
# Central classification: field → number of trailing chars kept visible.
SENSITIVE_KEYS = {
    "aadhar_number": 4, "aadhaar_no": 4, "pan_number": 4, "pan_no": 4,
    "bank_account_number": 4, "bank_account": 4, "ifsc_code": 4,
    "bank_ifsc": 4, "uan_number": 4, "uan": 4, "esic_number": 4,
    "esic_ip_number": 4, "phone": 4, "mobile": 4, "alternate_mobile": 4,
    "emergency_contact": 4, "personal_email": 3,
    "address": 0, "permanent_address": 0, "current_address": 0,
    "present_address": 0,
}


def can_view_sensitive(user: dict) -> bool:
    role = user.get("role")
    if role == "super_admin":
        return True
    if role == "company_admin" and not user.get("is_company_staff"):
        return True  # real firm admin — unrestricted inside own firm
    perms = _user_perms(user) or set()
    return "sensitive_data:view" in perms


def _mask(v: Any, keep: int) -> str:
    s = str(v)
    if keep <= 0 or len(s) <= keep:
        return "XXXX"
    return "X" * (len(s) - keep) + s[-keep:]


async def apply_sensitive_masking(db, user: dict, doc: dict,
                                  employee_id: Optional[str] = None,
                                  module: str = "employees") -> dict:
    """Central masking service. If the user lacks sensitive_data:view the
    BACKEND RESPONSE ITSELF carries only masked values (never frontend
    JS masking). Authorized unmasked access emits a SENSITIVE_DATA_VIEWED
    audit event (deduped per user+employee+day; never stores the values)."""
    present = [k for k in SENSITIVE_KEYS if doc.get(k)]
    if not present:
        return doc
    if can_view_sensitive(user):
        try:
            from datetime import datetime, timezone
            day = datetime.now(timezone.utc).date().isoformat()
            dedup = {"action": "SENSITIVE_DATA_VIEWED",
                     "user_id": user.get("user_id"),
                     "detail.employee_id": employee_id,
                     "detail.day": day}
            if not await db.activity_log.find_one(dedup, {"_id": 1}):
                import uuid as _uuid
                await db.activity_log.insert_one({
                    "log_id": f"al_{_uuid.uuid4().hex[:12]}",
                    "user_id": user.get("user_id"),
                    "user_name": user.get("name"),
                    "role": user.get("role"),
                    "action": "SENSITIVE_DATA_VIEWED",
                    "module": module,
                    "severity": "INFO",
                    "detail": {"employee_id": employee_id, "day": day,
                               "fields": present},  # field NAMES only
                    "at": datetime.now(timezone.utc).isoformat(),
                })
        except Exception:
            pass
        return doc
    for k in present:
        doc[k] = _mask(doc[k], SENSITIVE_KEYS[k])
    doc["sensitive_masked"] = True
    return doc


# ── Iter 587 — EXPORT SECURITY & LOGGING (central engine) ──────────────────
async def log_export(db, user: dict, *, report: str, module: str,
                     fmt: str, company_id: Optional[str] = None,
                     period: Optional[str] = None, records: int = 0,
                     sensitive: bool = False, status: str = "SUCCESS",
                     reason: Optional[str] = None) -> str:
    """Create a DATA_EXPORT / EXPORT_DENIED audit row with a unique Export
    ID. Super Admin exports are logged too. Never stores actual values."""
    import uuid as _uuid
    from datetime import datetime, timezone
    export_id = f"EXP-{datetime.now(timezone.utc).year}-{_uuid.uuid4().hex[:8].upper()}"
    try:
        await db.activity_log.insert_one({
            "log_id": f"al_{_uuid.uuid4().hex[:12]}",
            "user_id": user.get("user_id"), "user_name": user.get("name"),
            "role": user.get("role"),
            "action": "DATA_EXPORT" if status == "SUCCESS" else "EXPORT_DENIED",
            "module": module,
            "severity": "INFO" if status == "SUCCESS" else "CRITICAL",
            "detail": {"export_id": export_id, "report": report,
                       "format": fmt, "company_id": company_id,
                       "period": period, "records": records,
                       "sensitive_included": sensitive, "reason": reason},
            "at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass
    return export_id


async def authorize_export(db, user: dict, *, module: str, report: str,
                           fmt: str, company_id: Optional[str] = None,
                           period: Optional[str] = None) -> None:
    """Central export gate: firm scope + module EXPORT permission. Denied
    attempts are logged (EXPORT_DENIED) then rejected with 403."""
    try:
        if company_id is not None and not firm_ok(user, company_id):
            raise HTTPException(status_code=403,
                                detail="Forbidden — firm outside your scope")
        if not has_permission(user, module, "export"):
            raise HTTPException(status_code=403,
                                detail=f"Forbidden — you lack {module}:export permission")
    except HTTPException as e:
        await log_export(db, user, report=report, module=module, fmt=fmt,
                         company_id=company_id, period=period,
                         status="DENIED", reason=e.detail)
        raise
