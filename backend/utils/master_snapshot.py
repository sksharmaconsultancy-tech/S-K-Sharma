"""Iter 485 — Compliance Salary Process: MASTER DATA SNAPSHOT engine.

Enterprise payroll behaviour (SAP/Oracle/Workday style): the first salary
generation of a firm + month + employee-group FREEZES every salary-related
Employee Master value into ``db.compliance_master_snapshots``. Reprocess and
Delete + Generate-Again read the snapshot instead of the live master, so
historical payroll never changes because HR edited the Employee Master.
Dynamic data (attendance / OT / leave / advances / imported sheets) keeps
refreshing normally — only master values are frozen.

Storage — one document PER EMPLOYEE (scales to 100k+ employees, appendable):
    { snap_key, company_id, month, run_type, employee_type_key,
      user_id, employee_code, version, active, data{...frozen fields...},
      created_at, created_by, created_by_name, source, reason }

Versioning: "Refresh Master Snapshot" (super-admin only) deactivates the
current version and writes version+1 — previous versions are never deleted,
giving a complete history + audit trail.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Every Employee-Master field that participates in the compliance salary
# calculation, statutory logic, registers, payslips or exports. Frozen at
# first generation. Anything NOT in this list (attendance policy overrides,
# device mappings, photos, auth) stays live.
FROZEN_MASTER_FIELDS: List[str] = [
    # identity / classification
    "name", "employee_code", "father_name", "spouse_name", "gender",
    "marital_status", "designation", "department", "branch_name",
    "contractor_name", "employee_type", "employee_group", "grade",
    "category", "cost_center", "shift", "wage_type", "is_onroll",
    "company_id",
    # dates that gate month inclusion / proration
    "doj", "date_of_joining", "exit_date", "resign_date", "disabled",
    # salary basis / structure
    "salary_mode", "salary_monthly", "salary_daily", "rate", "ctc",
    "compliance_gross", "compliance_basic", "compliance_salary_mode",
    "salary_structure_compliance", "salary_structure_actual",
    "compliance_salary_allowances", "structure_pct",
    "basic_amount", "da_amount", "hra_amount", "conv_amount",
    "medical_amount", "special_amount", "others_amount",
    "category_rate", "skill_level",
    # PF
    "pf_basic", "pf_applicable", "excluded_employee",
    "pf_contribution_type", "vpf_amount", "vpf_percent", "vpf_enabled",
    "higher_pf_from", "higher_pf_to", "higher_pf_wage", "higher_pension",
    "eps_disabled", "intl_worker", "uan_no", "pf_no",
    # ESIC
    "esi_ip_no", "esic_applicable", "esi_applicable",
    # other statutory
    "pt_applicable", "tds_applicable", "bonus_applicable",
    "gratuity_applicable", "lwf_applicable",
    # bank
    "bank_name", "bank_account_no", "account_number", "bank_ifsc",
    "ifsc", "bank_branch", "payment_mode",
]

_INDEX_READY = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def snapshot_scope_key(company_id: str, month: str, run_type: str,
                       employee_type: Optional[str]) -> Dict[str, Any]:
    """Query key for one payroll scope (firm + month + run type + group)."""
    et = (employee_type or "").strip().lower() or "__all__"
    return {
        "company_id": company_id,
        "month": month,
        "run_type": (run_type or "compliance").lower(),
        "employee_type_key": et,
    }


async def _ensure_index(db) -> None:
    global _INDEX_READY
    if _INDEX_READY:
        return
    try:
        await db.compliance_master_snapshots.create_index(
            [("company_id", 1), ("month", 1), ("run_type", 1),
             ("employee_type_key", 1), ("active", 1), ("user_id", 1)],
            name="cms_scope_active_user",
        )
        _INDEX_READY = True
    except Exception:
        pass


def freeze_fields(emp: Dict[str, Any]) -> Dict[str, Any]:
    """Copy ONLY the frozen fields that exist on the employee doc."""
    return {f: emp[f] for f in FROZEN_MASTER_FIELDS if f in emp}


def overlay_snapshot(emp: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """Return the employee dict with every FROZEN field taken from the
    snapshot — fields absent at snapshot time are REMOVED so later master
    additions can never leak into a frozen month."""
    out = dict(emp)
    for f in FROZEN_MASTER_FIELDS:
        if f in data:
            out[f] = data[f]
        else:
            out.pop(f, None)
    return out


async def load_master_snapshot(db, company_id: str, month: str,
                               run_type: str, employee_type: Optional[str],
                               ) -> Dict[str, Dict[str, Any]]:
    """Active snapshot for the scope → {user_id: doc} (ONE indexed query)."""
    key = snapshot_scope_key(company_id, month, run_type, employee_type)
    out: Dict[str, Dict[str, Any]] = {}
    async for d in db.compliance_master_snapshots.find(
            {**key, "active": True}, {"_id": 0}):
        out[d["user_id"]] = d
    return out


async def create_master_snapshot(db, company_id: str, month: str,
                                 run_type: str, employee_type: Optional[str],
                                 employees: List[Dict[str, Any]],
                                 admin: Dict[str, Any],
                                 source: str = "first_generate",
                                 reason: Optional[str] = None,
                                 version: int = 1) -> int:
    """Insert snapshot docs (one per employee) for the scope."""
    await _ensure_index(db)
    key = snapshot_scope_key(company_id, month, run_type, employee_type)
    now = _now_iso()
    docs = []
    for e in employees:
        if not e.get("user_id"):
            continue
        docs.append({
            **key,
            "snapshot_id": f"cms_{uuid.uuid4().hex[:12]}",
            "user_id": e["user_id"],
            "employee_code": e.get("employee_code"),
            "version": version,
            "active": True,
            "data": freeze_fields(e),
            "created_at": now,
            "created_by": admin.get("user_id"),
            "created_by_name": admin.get("name") or admin.get("email"),
            "source": source,
            "reason": reason,
        })
    if docs:
        await db.compliance_master_snapshots.insert_many(docs)
    return len(docs)


async def append_new_employees(db, company_id: str, month: str,
                               run_type: str, employee_type: Optional[str],
                               employees: List[Dict[str, Any]],
                               admin: Dict[str, Any],
                               version: int) -> int:
    """New joiners after the snapshot exists: freeze THEM once and append
    to the CURRENT active version (spec: read master once, append)."""
    if not employees:
        return 0
    return await create_master_snapshot(
        db, company_id, month, run_type, employee_type, employees, admin,
        source="append_new_employee", version=version)


async def refresh_master_snapshot(db, company_id: str, month: str,
                                  run_type: str, employee_type: Optional[str],
                                  employees: List[Dict[str, Any]],
                                  admin: Dict[str, Any],
                                  reason: Optional[str]) -> Dict[str, Any]:
    """SUPER-ADMIN ONLY escape hatch: deactivate the current version and
    write version+1 from the live Employee Master. Old versions are kept
    forever (complete history)."""
    key = snapshot_scope_key(company_id, month, run_type, employee_type)
    cur = await db.compliance_master_snapshots.find_one(
        {**key, "active": True}, {"_id": 0, "version": 1},
        sort=[("version", -1)])
    old_v = int((cur or {}).get("version") or 0)
    now = _now_iso()
    await db.compliance_master_snapshots.update_many(
        {**key, "active": True},
        {"$set": {"active": False, "superseded_at": now,
                  "superseded_by": admin.get("user_id")}})
    n = await create_master_snapshot(
        db, company_id, month, run_type, employee_type, employees, admin,
        source="refresh_master", reason=reason, version=old_v + 1)
    return {"old_version": old_v, "new_version": old_v + 1, "employees": n}
