"""Statutory Registration module — EPF UAN + ESIC IP generation.

One unified engine for both government-portal registrations:

  * ESIC IP Registration  (portal="esic")  → users.esi_ip_no
  * EPF UAN Generation    (portal="uan")   → users.uan_no (+ pf_member_id)

Features: eligibility rules (configurable wage ceilings), Aadhaar/PAN/KYC
validation, duplicate detection (existing number on file OR another employee
with the same Aadhaar), registration queue with HR approval workflow,
bulk registration, RPA queueing (portal_automation_jobs), link-existing-
number instead of re-registering, retry for failed runs, per-registration
audit history, Form-1 / Form-11 PDF generation and dashboard analytics.

Collections:
  * statutory_registrations — one row per registration attempt (full history)
  * registration_settings   — per-company eligibility rules
"""
import base64
import io
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    require_permission,
    sub_admin_can_touch_company,
    now_iso,
    logger,
)

router = APIRouter(prefix="/api/admin/statutory", tags=["statutory-registration"])

# portal → RPA action + employee field the number is written to
PORTALS: Dict[str, Dict[str, str]] = {
    "esic": {"action": "generate_esic", "field": "esi_ip_no", "label": "ESIC IP",
             "portal_key": "esic"},
    "uan": {"action": "generate_uan", "field": "uan_no", "label": "PF UAN",
            "portal_key": "epfo"},
}

DEFAULT_SETTINGS = {
    "esic_wage_ceiling": 21000,     # ESIC Act — ₹21,000/month gross
    "esic_wage_ceiling_disabled": 25000,
    "pf_wage_ceiling": 15000,       # EPF mandatory ceiling
    "pf_cover_all": True,           # firm covers every employee regardless of wage
    "require_approval": False,      # HR approval step before queueing RPA
}

_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

SNAP_FIELDS = [
    "name", "father_name", "mother_name", "dob", "gender", "marital_status",
    "aadhaar_no", "pan_no", "phone", "email", "doj", "employee_code",
    "present_address", "address", "salary_monthly", "bank_account_name",
    "department", "designation",
]


def _portal_or_400(portal: str) -> Dict[str, str]:
    p = PORTALS.get((portal or "").lower())
    if not p:
        raise HTTPException(status_code=400, detail="portal must be 'esic' or 'uan'")
    return p


async def _admin_or_403(authorization: Optional[str], write: bool = False) -> Dict[str, Any]:
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    require_permission(admin, "registrations:write" if write else "registrations:read")
    return admin


def _company_query(admin: Dict[str, Any], company_id: Optional[str]) -> Dict[str, Any]:
    """Build the company scope portion of a Mongo query for the caller."""
    if admin["role"] == "company_admin":
        return {"company_id": admin.get("company_id")}
    if admin["role"] == "sub_admin":
        if company_id:
            if not sub_admin_can_touch_company(admin, company_id):
                raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
            return {"company_id": company_id}
        scope = admin.get("sub_admin_company_scope") or "all"
        if scope != "all":
            return {"company_id": {"$in": admin.get("sub_admin_company_ids") or []}}
        return {}
    # super_admin
    return {"company_id": company_id} if company_id else {}


async def get_settings(company_id: Optional[str]) -> Dict[str, Any]:
    doc = await db.registration_settings.find_one(
        {"company_id": company_id or "_default"}, {"_id": 0}) or {}
    out = dict(DEFAULT_SETTINGS)
    out.update({k: v for k, v in doc.items() if k in DEFAULT_SETTINGS})
    return out


def _snapshot(emp: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    snap = {k: emp.get(k) for k in SNAP_FIELDS}
    # legacy field aliases
    snap["aadhaar_no"] = snap.get("aadhaar_no") or emp.get("aadhar_number")
    snap["pan_no"] = snap.get("pan_no") or emp.get("pan_number")
    for k, v in (overrides or {}).items():
        if k in SNAP_FIELDS and v not in (None, ""):
            snap[k] = v
    return snap


def validate_snapshot(portal: str, snap: Dict[str, Any],
                      settings: Dict[str, Any]) -> Dict[str, Any]:
    """Blocking issues + advisory warnings + eligibility for a snapshot."""
    issues: List[str] = []
    warnings: List[str] = []

    aadhaar = re.sub(r"\D", "", str(snap.get("aadhaar_no") or ""))
    if len(aadhaar) != 12:
        issues.append("Aadhaar number missing or not 12 digits")
    if not (snap.get("name") or "").strip():
        issues.append("Employee name missing")
    if not (snap.get("dob") or "").strip():
        issues.append("Date of birth missing")
    if not (snap.get("doj") or "").strip():
        issues.append("Date of joining missing")

    pan = (snap.get("pan_no") or "").strip().upper()
    if pan and not _PAN_RE.match(pan):
        warnings.append("PAN format looks invalid (AAAAA9999A)")
    elif not pan and portal == "uan":
        warnings.append("PAN missing — recommended for EPF KYC")
    if not (snap.get("father_name") or "").strip():
        warnings.append("Father/Husband name missing")
    if not (snap.get("gender") or "").strip():
        warnings.append("Gender missing")
    addr = (snap.get("present_address") or snap.get("address") or "").strip()
    if not addr:
        warnings.append("Address missing — required on the portal form")
    phone = re.sub(r"\D", "", str(snap.get("phone") or ""))
    if len(phone) < 10:
        warnings.append("Mobile number missing/incomplete")

    wage = 0.0
    try:
        wage = float(snap.get("salary_monthly") or 0)
    except (TypeError, ValueError):
        wage = 0.0
    if portal == "esic":
        ceiling = float(settings.get("esic_wage_ceiling") or 21000)
        eligible = wage > 0 and wage <= ceiling
        elig_note = (
            f"Gross ₹{wage:,.0f} ≤ ESIC ceiling ₹{ceiling:,.0f}" if eligible
            else (f"Gross ₹{wage:,.0f} exceeds ESIC ceiling ₹{ceiling:,.0f}"
                  if wage > 0 else "Monthly salary not set — eligibility unknown")
        )
    else:
        ceiling = float(settings.get("pf_wage_ceiling") or 15000)
        cover_all = bool(settings.get("pf_cover_all", True))
        eligible = cover_all or (wage > 0 and wage <= ceiling)
        elig_note = (
            "Firm covers all employees under EPF" if cover_all and not (0 < wage <= ceiling)
            else (f"Gross ₹{wage:,.0f} ≤ EPF ceiling ₹{ceiling:,.0f}" if eligible
                  else f"Gross ₹{wage:,.0f} exceeds EPF ceiling ₹{ceiling:,.0f} (voluntary only)")
        )
    if not eligible:
        warnings.append(f"Not mandatorily eligible: {elig_note}")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "eligible": eligible,
        "eligibility_note": elig_note,
        "wage": wage,
    }


async def _duplicate_check(portal_cfg: Dict[str, str], emp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Existing number on this employee OR another employee (same company)
    sharing the Aadhaar already has the number → return it for linking."""
    field = portal_cfg["field"]
    own = (emp.get(field) or "").strip()
    if own:
        return {"kind": "own", "value": own,
                "note": f"Employee already has {portal_cfg['label']} {own} on file."}
    aadhaar = re.sub(r"\D", "", str(emp.get("aadhaar_no") or emp.get("aadhar_number") or ""))
    if len(aadhaar) == 12:
        other = await db.users.find_one(
            {"aadhaar_no": {"$in": [aadhaar, emp.get("aadhaar_no")]},
             "user_id": {"$ne": emp["user_id"]},
             field: {"$nin": [None, ""]}},
            {"_id": 0, "name": 1, "employee_code": 1, field: 1},
        )
        if other:
            return {"kind": "aadhaar_match", "value": other.get(field),
                    "note": (f"Same Aadhaar as {other.get('name')} "
                             f"({other.get('employee_code') or '—'}) who already has "
                             f"{portal_cfg['label']} {other.get(field)} — link it instead "
                             "of registering again.")}
    return None


def _hist(admin: Optional[Dict[str, Any]], action: str, note: str = "") -> Dict[str, Any]:
    return {
        "at": now_iso(),
        "by": (admin or {}).get("user_id") or "system",
        "by_name": (admin or {}).get("name") or "System",
        "action": action,
        "note": note,
    }


async def _notify(company_id: Optional[str], title: str, body: str) -> None:
    try:
        await db.notifications.insert_one({
            "notification_id": f"n_{uuid.uuid4().hex[:10]}",
            "title": title, "body": body, "audience": "admins",
            "company_id": company_id, "created_at": now_iso(),
            "created_by": "Statutory Registration",
        })
    except Exception:  # noqa: BLE001
        pass


async def _load_emp_scoped(user_id: str, admin: Dict[str, Any]) -> Dict[str, Any]:
    emp = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "pin_hash": 0, "password_hash": 0, "face_reference_base64": 0},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's employee")
    if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, emp.get("company_id")):
        raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    return emp


# ---------------------------------------------------------------------------
# RPA queueing (shared with portal_generation.py Employee-Master buttons)
# ---------------------------------------------------------------------------

async def _portal_creds_present(company_id: str, portal_key: str) -> bool:
    master = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "portal_logins": 1, "epf": 1, "esi": 1})
    if not master:
        return False
    sec = master.get("epf" if portal_key == "epfo" else "esi") or {}
    pfx = "epf" if portal_key == "epfo" else "esi"
    if (sec.get(f"{pfx}_user_id") or "").strip() and (sec.get(f"{pfx}_password") or "").strip():
        return True
    label = "PF LOGIN" if portal_key == "epfo" else "ESI Login"
    for row in (master.get("portal_logins") or []):
        if row.get("login_type") == label:
            return bool((row.get("user_name") or "").strip()
                        and (row.get("password") or "").strip())
    return False


async def queue_rpa_job(*, portal: str, admin: Dict[str, Any], emp: Dict[str, Any],
                        reg: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a portal_automation_jobs row for a registration and link it."""
    cfg = PORTALS[portal]
    creds = await _portal_creds_present(emp.get("company_id"), cfg["portal_key"])
    job_id = f"paj_{uuid.uuid4().hex[:12]}"
    snap = dict(reg["snapshot"])
    snap["family_members"] = reg.get("family_members") or []
    snap["nominee"] = reg.get("nominee") or {}
    snap["dispensary"] = reg.get("dispensary") or ""
    job = {
        "job_id": job_id,
        "portal": cfg["portal_key"],
        "action_type": cfg["action"],
        "company_id": emp.get("company_id"),
        "employee_user_id": emp["user_id"],
        "employee_snapshot": snap,
        "reg_id": reg["reg_id"],
        "status": "pending" if creds else "manual_required",
        "steps": [] if creds else [{
            "at": now_iso(),
            "note": ("Portal credentials missing on Firm Master — automation "
                     "skipped. Complete manually and use Manual Complete."),
        }],
        "created_by": admin["user_id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.portal_automation_jobs.insert_one(job)
    new_status = "queued" if creds else "action_required"
    await db.statutory_registrations.update_one(
        {"reg_id": reg["reg_id"]},
        {"$set": {"status": new_status, "rpa_job_id": job_id,
                  "last_error": (None if creds else
                                 "Portal credentials missing on Firm Master"),
                  "updated_at": now_iso()},
         "$push": {"history": _hist(admin, "queued" if creds else "action_required",
                                    "RPA job queued" if creds else
                                    "Credentials missing — manual completion needed")}},
    )
    job.pop("_id", None)
    return {"job": job, "creds_present": creds}


async def create_registration(*, portal: str, admin: Dict[str, Any],
                              emp: Dict[str, Any],
                              overrides: Optional[Dict[str, Any]] = None,
                              family_members: Optional[List[Dict[str, Any]]] = None,
                              nominee: Optional[Dict[str, Any]] = None,
                              dispensary: str = "",
                              source: str = "module") -> Dict[str, Any]:
    """Create (or return the open) registration for an employee."""
    cfg = PORTALS[portal]
    open_reg = await db.statutory_registrations.find_one(
        {"portal": portal, "employee_user_id": emp["user_id"],
         "status": {"$in": ["draft", "pending_approval", "queued",
                            "submitted", "action_required"]}},
        {"_id": 0},
    )
    if open_reg:
        return {"reg": open_reg, "existing": True}

    settings = await get_settings(emp.get("company_id"))
    snap = _snapshot(emp, overrides)
    validation = validate_snapshot(portal, snap, settings)
    dup = await _duplicate_check(cfg, emp)
    reg = {
        "reg_id": f"esr_{uuid.uuid4().hex[:12]}",
        "portal": portal,
        "company_id": emp.get("company_id"),
        "employee_user_id": emp["user_id"],
        "employee_name": emp.get("name"),
        "employee_code": emp.get("employee_code"),
        "snapshot": snap,
        "family_members": family_members or [],
        "nominee": nominee or {},
        "dispensary": dispensary or "",
        "status": "existing_found" if dup else "draft",
        "validation": validation,
        "duplicate": dup,
        "value": None,
        "rpa_job_id": None,
        "last_error": None,
        "source": source,
        "history": [_hist(admin, "created",
                          dup["note"] if dup else f"Draft created ({source})")],
        "created_by": admin["user_id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.statutory_registrations.insert_one(reg)
    reg.pop("_id", None)
    return {"reg": reg, "existing": False}


async def link_existing_value(*, portal: str, admin: Dict[str, Any],
                              emp: Dict[str, Any], value: str,
                              reg_id: Optional[str] = None) -> Dict[str, Any]:
    cfg = PORTALS[portal]
    digits = re.sub(r"\D", "", value or "")
    if portal == "uan" and len(digits) != 12:
        raise HTTPException(status_code=400, detail="UAN must be exactly 12 digits")
    if portal == "esic" and not (10 <= len(digits) <= 17):
        raise HTTPException(status_code=400, detail="ESIC IP number should be 10-17 digits")
    field = cfg["field"]
    await db.users.update_one(
        {"user_id": emp["user_id"]},
        {"$set": {field: digits, f"{field}_updated_at": now_iso(),
                  f"{field}_source": "linked_existing"}},
    )
    if reg_id:
        await db.statutory_registrations.update_one(
            {"reg_id": reg_id},
            {"$set": {"status": "linked_existing", "value": digits,
                      "completed_at": now_iso(), "updated_at": now_iso()},
             "$push": {"history": _hist(admin, "linked_existing",
                                        f"Existing {cfg['label']} {digits} linked — "
                                        "no new registration created")}},
        )
    else:
        reg = {
            "reg_id": f"esr_{uuid.uuid4().hex[:12]}",
            "portal": portal, "company_id": emp.get("company_id"),
            "employee_user_id": emp["user_id"], "employee_name": emp.get("name"),
            "employee_code": emp.get("employee_code"),
            "snapshot": _snapshot(emp), "family_members": [], "nominee": {},
            "dispensary": "", "status": "linked_existing",
            "validation": None, "duplicate": None, "value": digits,
            "rpa_job_id": None, "last_error": None, "source": "link_existing",
            "history": [_hist(admin, "linked_existing",
                              f"Existing {cfg['label']} {digits} linked directly")],
            "created_by": admin["user_id"], "created_at": now_iso(),
            "completed_at": now_iso(), "updated_at": now_iso(),
        }
        await db.statutory_registrations.insert_one(reg)
    logger.info("[statutory] linked existing %s=%s for emp=%s", field, digits, emp["user_id"])
    return {"field": field, "value": digits}


# ---------------------------------------------------------------------------
# ESIC monthly alerts — called from the Compliance Salary process so HR is
# flagged every month about (a) eligible employees still missing an IP
# number and (b) IP holders whose gross crossed the wage ceiling (exit due
# at the end of the contribution period).
# ---------------------------------------------------------------------------

async def scan_esic_alerts(company_id: Optional[str], month: str,
                           rows: List[Dict[str, Any]]) -> None:
    """Upsert an esic_alerts doc for (company, month) from salary-run rows.
    Never raises — salary processing must not fail because of alerting."""
    try:
        user_ids = [r.get("user_id") for r in rows if r.get("user_id")]
        if not user_ids:
            return
        settings = await get_settings(company_id)
        ceiling = float(settings.get("esic_wage_ceiling") or 21000)
        users: Dict[str, Dict[str, Any]] = {}
        async for u in db.users.find(
                {"user_id": {"$in": user_ids}},
                {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "esi_ip_no": 1}):
            users[u["user_id"]] = u

        needs_registration: List[Dict[str, Any]] = []
        ceiling_crossed: List[Dict[str, Any]] = []
        for r in rows:
            u = users.get(r.get("user_id") or "")
            if not u:
                continue
            gross = float(r.get("monthly_gross") or r.get("gross_master") or 0)
            has_ip = bool((u.get("esi_ip_no") or "").strip())
            entry = {"user_id": u["user_id"], "name": u.get("name"),
                     "employee_code": u.get("employee_code"),
                     "gross": round(gross, 2)}
            if not has_ip and 0 < gross <= ceiling:
                needs_registration.append(entry)
            elif has_ip and gross > ceiling:
                ceiling_crossed.append(entry)

        prev = await db.esic_alerts.find_one(
            {"company_id": company_id, "month": month}, {"_id": 0}) or {}
        await db.esic_alerts.update_one(
            {"company_id": company_id, "month": month},
            {"$set": {"company_id": company_id, "month": month,
                      "ceiling": ceiling,
                      "needs_registration": needs_registration,
                      "ceiling_crossed": ceiling_crossed,
                      "generated_at": now_iso()}},
            upsert=True,
        )
        counts_changed = (
            len(prev.get("needs_registration") or []) != len(needs_registration)
            or len(prev.get("ceiling_crossed") or []) != len(ceiling_crossed)
        )
        if (needs_registration or ceiling_crossed) and counts_changed:
            parts = []
            if needs_registration:
                parts.append(f"{len(needs_registration)} eligible employee(s) still "
                             "missing an ESIC IP number")
            if ceiling_crossed:
                parts.append(f"{len(ceiling_crossed)} IP holder(s) crossed the "
                             f"₹{ceiling:,.0f} wage ceiling (exit due at contribution period end)")
            await _notify(company_id, f"ESIC Alerts — {month}",
                          "Salary run flagged: " + "; ".join(parts) +
                          ". Review them on the Statutory Registration screen.")
        logger.info("[statutory] esic alerts %s/%s: missing=%s crossed=%s",
                    company_id, month, len(needs_registration), len(ceiling_crossed))
    except Exception as exc:  # noqa: BLE001 — alerting must never break payroll
        logger.warning("[statutory] esic alert scan failed: %s", exc)


@router.get("/esic/alerts")
async def esic_alerts(company_id: Optional[str] = Query(None),
                      authorization: Optional[str] = Header(None)):
    admin = await _admin_or_403(authorization)
    q = _company_query(admin, company_id)
    rows = await db.esic_alerts.find(q, {"_id": 0}).sort("month", -1).to_list(6)
    return {"ok": True, "alerts": rows}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.get("/settings")
async def read_settings(company_id: Optional[str] = Query(None),
                        authorization: Optional[str] = Header(None)):
    admin = await _admin_or_403(authorization)
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    return {"ok": True, "company_id": company_id,
            "settings": await get_settings(company_id)}


@router.put("/settings")
async def write_settings(payload: Dict[str, Any] = Body(...),
                         authorization: Optional[str] = Header(None)):
    admin = await _admin_or_403(authorization, write=True)
    company_id = payload.get("company_id")
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    updates = {k: payload[k] for k in DEFAULT_SETTINGS if k in payload}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid settings provided")
    await db.registration_settings.update_one(
        {"company_id": company_id or "_default"},
        {"$set": {**updates, "updated_at": now_iso(), "updated_by": admin["user_id"]}},
        upsert=True,
    )
    return {"ok": True, "settings": await get_settings(company_id)}


# ---------------------------------------------------------------------------
# Dashboard + eligible employees
# ---------------------------------------------------------------------------

@router.get("/{portal}/dashboard")
async def dashboard(portal: str, company_id: Optional[str] = Query(None),
                    authorization: Optional[str] = Header(None)):
    cfg = _portal_or_400(portal)
    admin = await _admin_or_403(authorization)
    scope = _company_query(admin, company_id)
    settings = await get_settings(scope.get("company_id")
                                  if isinstance(scope.get("company_id"), str) else None)

    emp_q = {"role": "employee", **scope}
    total = await db.users.count_documents(emp_q)
    have = await db.users.count_documents({**emp_q, cfg["field"]: {"$nin": [None, ""]}})

    # eligible-without-number (payroll integration flag)
    missing_eligible = 0
    async for e in db.users.find(
            {**emp_q, cfg["field"]: {"$in": [None, ""]}},
            {"_id": 0, "salary_monthly": 1}):
        try:
            wage = float(e.get("salary_monthly") or 0)
        except (TypeError, ValueError):
            wage = 0.0
        if portal == "esic":
            if 0 < wage <= float(settings["esic_wage_ceiling"]):
                missing_eligible += 1
        else:
            if settings.get("pf_cover_all") or (0 < wage <= float(settings["pf_wage_ceiling"])):
                missing_eligible += 1

    counts: Dict[str, int] = {}
    async for row in db.statutory_registrations.aggregate([
            {"$match": {"portal": portal, **scope}},
            {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]

    in_progress = sum(counts.get(s, 0) for s in ("queued", "submitted"))
    return {
        "ok": True,
        "kpis": {
            "total_employees": total,
            "registered": have,
            "coverage_pct": round(have * 100.0 / total, 1) if total else 0,
            "eligible_missing": missing_eligible,
            "in_progress": in_progress,
            "pending_approval": counts.get("pending_approval", 0),
            "action_required": counts.get("action_required", 0)
            + counts.get("existing_found", 0),
            "failed": counts.get("failed", 0),
            "generated": counts.get("generated", 0) + counts.get("linked_existing", 0),
            "draft": counts.get("draft", 0),
        },
        "status_counts": counts,
        "settings": settings,
    }


@router.get("/{portal}/eligible")
async def eligible_employees(portal: str, company_id: Optional[str] = Query(None),
                             authorization: Optional[str] = Header(None)):
    cfg = _portal_or_400(portal)
    admin = await _admin_or_403(authorization)
    scope = _company_query(admin, company_id)
    settings = await get_settings(scope.get("company_id")
                                  if isinstance(scope.get("company_id"), str) else None)

    # open registrations keyed by employee for quick status chips
    open_by_emp: Dict[str, Dict[str, Any]] = {}
    async for r in db.statutory_registrations.find(
            {"portal": portal, **scope,
             "status": {"$nin": ["rejected"]}},
            {"_id": 0, "reg_id": 1, "employee_user_id": 1, "status": 1}):
        open_by_emp.setdefault(r["employee_user_id"], r)

    comp_names: Dict[str, str] = {}
    async for c in db.companies.find({}, {"_id": 0, "company_id": 1, "name": 1}):
        comp_names[c.get("company_id") or ""] = c.get("name") or ""

    out: List[Dict[str, Any]] = []
    async for e in db.users.find(
            {"role": "employee", **scope, cfg["field"]: {"$in": [None, ""]}},
            {"_id": 0, "pin_hash": 0, "password_hash": 0, "face_reference_base64": 0}):
        snap = _snapshot(e)
        v = validate_snapshot(portal, snap, settings)
        dup = await _duplicate_check(cfg, e)
        reg = open_by_emp.get(e["user_id"])
        out.append({
            "user_id": e["user_id"],
            "name": e.get("name"),
            "employee_code": e.get("employee_code"),
            "company_id": e.get("company_id"),
            "company_name": comp_names.get(e.get("company_id") or "", ""),
            "department": e.get("department"),
            "designation": e.get("designation"),
            "aadhaar_ok": not any("Aadhaar" in i for i in v["issues"]),
            "wage": v["wage"],
            "eligible": v["eligible"],
            "eligibility_note": v["eligibility_note"],
            "ready": v["ok"] and not dup,
            "issues": v["issues"],
            "warnings": v["warnings"],
            "duplicate": dup,
            "open_registration": reg,
        })
    out.sort(key=lambda r: ((0 if r["ready"] else 1), r["name"] or ""))
    return {"ok": True, "employees": out, "settings": settings}


# ---------------------------------------------------------------------------
# Registration CRUD + workflow
# ---------------------------------------------------------------------------

@router.get("/{portal}/employee/{user_id}/prefill")
async def registration_prefill(portal: str, user_id: str,
                               authorization: Optional[str] = Header(None)):
    """Everything the full-page registration form needs in ONE call:
    employee snapshot, live validation, duplicate info, the open
    registration (family/nominee/dispensary) and eligibility settings."""
    cfg = _portal_or_400(portal)
    admin = await _admin_or_403(authorization)
    emp = await _load_emp_scoped(user_id, admin)
    settings = await get_settings(emp.get("company_id"))
    snap = _snapshot(emp)
    open_reg = await db.statutory_registrations.find_one(
        {"portal": portal, "employee_user_id": user_id,
         "status": {"$nin": ["generated", "linked_existing", "rejected"]}},
        {"_id": 0}, sort=[("updated_at", -1)],
    )
    if open_reg and open_reg.get("snapshot"):
        snap = {**snap, **{k: v for k, v in open_reg["snapshot"].items()
                           if v not in (None, "")}}
    company = await db.companies.find_one(
        {"company_id": emp.get("company_id")}, {"_id": 0, "name": 1}) or {}
    return {
        "ok": True,
        "employee": {
            "user_id": emp["user_id"], "name": emp.get("name"),
            "employee_code": emp.get("employee_code"),
            "company_id": emp.get("company_id"),
            "company_name": company.get("name") or "",
            "current_value": emp.get(cfg["field"]) or "",
        },
        "snapshot": snap,
        "validation": validate_snapshot(portal, snap, settings),
        "duplicate": await _duplicate_check(cfg, emp),
        "registration": open_reg,
        "settings": settings,
    }


@router.get("/{portal}/registrations")
async def list_registrations(portal: str,
                             company_id: Optional[str] = Query(None),
                             status: Optional[str] = Query(None),
                             authorization: Optional[str] = Header(None)):
    _portal_or_400(portal)
    admin = await _admin_or_403(authorization)
    q: Dict[str, Any] = {"portal": portal, **_company_query(admin, company_id)}
    if status and status != "all":
        q["status"] = status
    rows = await db.statutory_registrations.find(
        q, {"_id": 0, "history": 0, "snapshot": 0},
    ).sort("updated_at", -1).to_list(500)
    return {"ok": True, "registrations": rows}


@router.get("/registrations/{reg_id}")
async def registration_detail(reg_id: str,
                              authorization: Optional[str] = Header(None)):
    admin = await _admin_or_403(authorization)
    reg = await db.statutory_registrations.find_one({"reg_id": reg_id}, {"_id": 0})
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    _company_guard(admin, reg.get("company_id"))
    job = None
    if reg.get("rpa_job_id"):
        job = await db.portal_automation_jobs.find_one(
            {"job_id": reg["rpa_job_id"]},
            {"_id": 0, "status": 1, "steps": 1, "manual_reason": 1, "error": 1})
        # strip heavy screenshots except the last one
        steps = (job or {}).get("steps") or []
        for s in steps[:-1]:
            s.pop("screenshot_base64", None)
    return {"ok": True, "registration": reg, "rpa_job": job}


def _company_guard(admin: Dict[str, Any], company_id: Optional[str]) -> None:
    if admin["role"] == "company_admin" and company_id != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm's registration")
    if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")


@router.post("/{portal}/registrations")
async def create_registration_ep(portal: str,
                                 payload: Dict[str, Any] = Body(...),
                                 authorization: Optional[str] = Header(None)):
    _portal_or_400(portal)
    admin = await _admin_or_403(authorization, write=True)
    emp = await _load_emp_scoped(payload.get("employee_user_id") or "", admin)
    res = await create_registration(
        portal=portal, admin=admin, emp=emp,
        overrides=payload.get("overrides"),
        family_members=payload.get("family_members"),
        nominee=payload.get("nominee"),
        dispensary=payload.get("dispensary") or "",
    )
    return {"ok": True, "registration": res["reg"], "already_open": res["existing"]}


@router.put("/registrations/{reg_id}")
async def update_registration(reg_id: str,
                              payload: Dict[str, Any] = Body(...),
                              authorization: Optional[str] = Header(None)):
    admin = await _admin_or_403(authorization, write=True)
    reg = await db.statutory_registrations.find_one({"reg_id": reg_id}, {"_id": 0})
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    _company_guard(admin, reg.get("company_id"))
    if reg["status"] not in ("draft", "failed", "action_required", "existing_found", "rejected"):
        raise HTTPException(status_code=400,
                            detail=f"Cannot edit a registration in '{reg['status']}' state")
    updates: Dict[str, Any] = {}
    if isinstance(payload.get("family_members"), list):
        updates["family_members"] = payload["family_members"]
    if isinstance(payload.get("nominee"), dict):
        updates["nominee"] = payload["nominee"]
    if "dispensary" in payload:
        updates["dispensary"] = str(payload.get("dispensary") or "")
    if isinstance(payload.get("overrides"), dict):
        snap = dict(reg["snapshot"])
        for k, v in payload["overrides"].items():
            if k in SNAP_FIELDS:
                snap[k] = v
        updates["snapshot"] = snap
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    snap = updates.get("snapshot", reg["snapshot"])
    settings = await get_settings(reg.get("company_id"))
    updates["validation"] = validate_snapshot(reg["portal"], snap, settings)
    updates["updated_at"] = now_iso()
    if reg["status"] in ("failed", "action_required", "rejected", "existing_found"):
        updates["status"] = "draft"
    await db.statutory_registrations.update_one(
        {"reg_id": reg_id},
        {"$set": updates, "$push": {"history": _hist(admin, "updated", "Details edited")}},
    )
    fresh = await db.statutory_registrations.find_one({"reg_id": reg_id}, {"_id": 0})
    return {"ok": True, "registration": fresh}


@router.post("/registrations/{reg_id}/submit")
async def submit_registration(reg_id: str,
                              authorization: Optional[str] = Header(None)):
    """Validate, then either queue directly or move to HR approval."""
    admin = await _admin_or_403(authorization, write=True)
    reg = await db.statutory_registrations.find_one({"reg_id": reg_id}, {"_id": 0})
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    _company_guard(admin, reg.get("company_id"))
    if reg["status"] not in ("draft", "failed", "action_required", "rejected", "existing_found"):
        raise HTTPException(status_code=400,
                            detail=f"Cannot submit from '{reg['status']}' state")
    settings = await get_settings(reg.get("company_id"))
    v = validate_snapshot(reg["portal"], reg["snapshot"], settings)
    if not v["ok"]:
        raise HTTPException(status_code=422, detail="; ".join(v["issues"]))
    emp = await _load_emp_scoped(reg["employee_user_id"], admin)
    dup = await _duplicate_check(PORTALS[reg["portal"]], emp)
    if dup:
        await db.statutory_registrations.update_one(
            {"reg_id": reg_id},
            {"$set": {"status": "existing_found", "duplicate": dup,
                      "validation": v, "updated_at": now_iso()},
             "$push": {"history": _hist(admin, "existing_found", dup["note"])}})
        return {"ok": False, "status": "existing_found", "duplicate": dup,
                "message": dup["note"]}

    needs_approval = bool(settings.get("require_approval")) or bool(admin.get("is_company_staff"))
    if needs_approval:
        await db.statutory_registrations.update_one(
            {"reg_id": reg_id},
            {"$set": {"status": "pending_approval", "validation": v,
                      "updated_at": now_iso()},
             "$push": {"history": _hist(admin, "submitted", "Sent for HR approval")}})
        return {"ok": True, "status": "pending_approval",
                "message": "Sent for HR approval."}
    await db.statutory_registrations.update_one(
        {"reg_id": reg_id}, {"$set": {"validation": v, "updated_at": now_iso()}})
    q = await queue_rpa_job(portal=reg["portal"], admin=admin, emp=emp,
                            reg={**reg, "validation": v})
    return {"ok": True,
            "status": "queued" if q["creds_present"] else "action_required",
            "message": ("Registration queued — the RPA worker will run it on the portal."
                        if q["creds_present"] else
                        "Queued in MANUAL mode — portal credentials missing on Firm Master.")}


@router.post("/registrations/{reg_id}/approve")
async def approve_registration(reg_id: str,
                               payload: Dict[str, Any] = Body(default={}),
                               authorization: Optional[str] = Header(None)):
    admin = await _admin_or_403(authorization, write=True)
    if admin.get("is_company_staff"):
        raise HTTPException(status_code=403, detail="Approval needs an admin account")
    reg = await db.statutory_registrations.find_one({"reg_id": reg_id}, {"_id": 0})
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    _company_guard(admin, reg.get("company_id"))
    if reg["status"] != "pending_approval":
        raise HTTPException(status_code=400, detail="Registration is not pending approval")
    emp = await _load_emp_scoped(reg["employee_user_id"], admin)
    await db.statutory_registrations.update_one(
        {"reg_id": reg_id},
        {"$push": {"history": _hist(admin, "approved",
                                    payload.get("note") or "Approved by HR")}})
    q = await queue_rpa_job(portal=reg["portal"], admin=admin, emp=emp, reg=reg)
    return {"ok": True,
            "status": "queued" if q["creds_present"] else "action_required",
            "message": "Approved and queued for portal automation."}


@router.post("/registrations/{reg_id}/reject")
async def reject_registration(reg_id: str,
                              payload: Dict[str, Any] = Body(default={}),
                              authorization: Optional[str] = Header(None)):
    admin = await _admin_or_403(authorization, write=True)
    reg = await db.statutory_registrations.find_one({"reg_id": reg_id}, {"_id": 0})
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    _company_guard(admin, reg.get("company_id"))
    if reg["status"] != "pending_approval":
        raise HTTPException(status_code=400, detail="Registration is not pending approval")
    note = payload.get("note") or "Rejected"
    await db.statutory_registrations.update_one(
        {"reg_id": reg_id},
        {"$set": {"status": "rejected", "updated_at": now_iso()},
         "$push": {"history": _hist(admin, "rejected", note)}})
    return {"ok": True, "status": "rejected"}


@router.post("/registrations/{reg_id}/retry")
async def retry_registration(reg_id: str,
                             authorization: Optional[str] = Header(None)):
    admin = await _admin_or_403(authorization, write=True)
    reg = await db.statutory_registrations.find_one({"reg_id": reg_id}, {"_id": 0})
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    _company_guard(admin, reg.get("company_id"))
    if reg["status"] not in ("failed", "action_required"):
        raise HTTPException(status_code=400, detail="Only failed runs can be retried")
    emp = await _load_emp_scoped(reg["employee_user_id"], admin)
    await db.statutory_registrations.update_one(
        {"reg_id": reg_id},
        {"$push": {"history": _hist(admin, "retry", "Re-queued after failure")}})
    q = await queue_rpa_job(portal=reg["portal"], admin=admin, emp=emp, reg=reg)
    return {"ok": True,
            "status": "queued" if q["creds_present"] else "action_required",
            "message": "Retry queued." if q["creds_present"] else
                       "Portal credentials still missing on Firm Master."}


@router.post("/registrations/{reg_id}/link-existing")
async def link_existing_ep(reg_id: str,
                           payload: Dict[str, Any] = Body(...),
                           authorization: Optional[str] = Header(None)):
    admin = await _admin_or_403(authorization, write=True)
    reg = await db.statutory_registrations.find_one({"reg_id": reg_id}, {"_id": 0})
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    _company_guard(admin, reg.get("company_id"))
    if reg["status"] in ("generated", "linked_existing"):
        raise HTTPException(status_code=400, detail="Registration is already completed")
    emp = await _load_emp_scoped(reg["employee_user_id"], admin)
    res = await link_existing_value(portal=reg["portal"], admin=admin, emp=emp,
                                    value=payload.get("value") or "", reg_id=reg_id)
    return {"ok": True, **res}


@router.post("/{portal}/bulk")
async def bulk_register(portal: str,
                        payload: Dict[str, Any] = Body(...),
                        authorization: Optional[str] = Header(None)):
    """Create + submit registrations for many employees in one shot."""
    _portal_or_400(portal)
    admin = await _admin_or_403(authorization, write=True)
    ids = payload.get("employee_user_ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="employee_user_ids is required")
    if len(ids) > 200:
        raise HTTPException(status_code=400, detail="Max 200 employees per bulk run")

    results: List[Dict[str, Any]] = []
    for uid in ids:
        try:
            emp = await _load_emp_scoped(uid, admin)
            res = await create_registration(portal=portal, admin=admin, emp=emp,
                                            source="bulk")
            reg = res["reg"]
            if reg["status"] == "existing_found":
                results.append({"user_id": uid, "name": emp.get("name"),
                                "status": "existing_found",
                                "note": (reg.get("duplicate") or {}).get("note")})
                continue
            if not (reg.get("validation") or {}).get("ok"):
                results.append({"user_id": uid, "name": emp.get("name"),
                                "status": "draft",
                                "note": "; ".join((reg.get("validation") or {}).get("issues") or
                                                  ["Validation incomplete"])})
                continue
            settings = await get_settings(emp.get("company_id"))
            if settings.get("require_approval") or admin.get("is_company_staff"):
                await db.statutory_registrations.update_one(
                    {"reg_id": reg["reg_id"]},
                    {"$set": {"status": "pending_approval", "updated_at": now_iso()},
                     "$push": {"history": _hist(admin, "submitted", "Bulk — sent for approval")}})
                results.append({"user_id": uid, "name": emp.get("name"),
                                "status": "pending_approval"})
            else:
                q = await queue_rpa_job(portal=portal, admin=admin, emp=emp, reg=reg)
                results.append({"user_id": uid, "name": emp.get("name"),
                                "status": "queued" if q["creds_present"] else "action_required"})
        except HTTPException as he:
            results.append({"user_id": uid, "status": "error", "note": str(he.detail)})
    queued = sum(1 for r in results if r["status"] in ("queued", "pending_approval"))
    logger.info("[statutory] bulk %s: %s/%s queued by %s",
                portal, queued, len(ids), admin["user_id"])
    return {"ok": True, "results": results, "queued": queued, "total": len(ids)}


# ---------------------------------------------------------------------------
# Document generation — ESIC Form-1 / EPF Form-11 style declaration PDF
# ---------------------------------------------------------------------------

@router.get("/registrations/{reg_id}/form")
async def registration_form_pdf(reg_id: str,
                                authorization: Optional[str] = Header(None)):
    admin = await _admin_or_403(authorization)
    reg = await db.statutory_registrations.find_one({"reg_id": reg_id}, {"_id": 0})
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    _company_guard(admin, reg.get("company_id"))

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdf_canvas

    company = await db.companies.find_one(
        {"company_id": reg.get("company_id")}, {"_id": 0, "name": 1}) or {}
    snap = reg.get("snapshot") or {}
    is_esic = reg["portal"] == "esic"
    title = ("ESIC — DECLARATION FORM (FORM-1)" if is_esic
             else "EPF — NEW MEMBER DECLARATION (FORM-11)")

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    y = H - 20 * mm
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(W / 2, y, title)
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawCentredString(W / 2, y, "(System generated by Payroll Portal — for portal submission reference)")
    y -= 10 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, f"Employer / Establishment: {company.get('name') or ''}")
    y -= 8 * mm

    rows = [
        ("Employee Name", snap.get("name") or ""),
        ("Employee Code", snap.get("employee_code") or ""),
        ("Father's / Husband's Name", snap.get("father_name") or ""),
        ("Date of Birth", snap.get("dob") or ""),
        ("Gender", (snap.get("gender") or "").title()),
        ("Marital Status", (snap.get("marital_status") or "").title()),
        ("Aadhaar Number", snap.get("aadhaar_no") or ""),
        ("PAN", snap.get("pan_no") or ""),
        ("Mobile", snap.get("phone") or ""),
        ("Email", snap.get("email") or ""),
        ("Date of Appointment", snap.get("doj") or ""),
        ("Monthly Wages (Gross)", f"Rs. {snap.get('salary_monthly') or ''}"),
        ("Present Address", snap.get("present_address") or snap.get("address") or ""),
        ("Bank A/c Name", snap.get("bank_account_name") or ""),
    ]
    if is_esic and reg.get("dispensary"):
        rows.append(("Dispensary / IMP", reg.get("dispensary")))
    if reg.get("value"):
        rows.append((("ESIC Insurance No." if is_esic else "UAN"), reg["value"]))

    c.setFont("Helvetica", 10)
    for label, value in rows:
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(20 * mm, y, f"{label}:")
        c.setFont("Helvetica", 9.5)
        c.drawString(75 * mm, y, str(value)[:80])
        y -= 6.5 * mm

    fam = reg.get("family_members") or []
    if fam:
        y -= 4 * mm
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(20 * mm, y, "Family Particulars" + (" (for ESIC medical benefit)" if is_esic else " / Nominees"))
        y -= 7 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20 * mm, y, "Name")
        c.drawString(75 * mm, y, "Relation")
        c.drawString(110 * mm, y, "DOB")
        c.drawString(140 * mm, y, "Residing with IP")
        y -= 5.5 * mm
        c.setFont("Helvetica", 9)
        for m in fam[:12]:
            c.drawString(20 * mm, y, str(m.get("name") or "")[:34])
            c.drawString(75 * mm, y, str(m.get("relation") or "")[:20])
            c.drawString(110 * mm, y, str(m.get("dob") or ""))
            c.drawString(140 * mm, y, "Yes" if m.get("residing", True) else "No")
            y -= 5.5 * mm

    nominee = reg.get("nominee") or {}
    if nominee.get("name"):
        y -= 4 * mm
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(20 * mm, y, "Nominee")
        y -= 6.5 * mm
        c.setFont("Helvetica", 9.5)
        c.drawString(20 * mm, y,
                     f"{nominee.get('name')} ({nominee.get('relation') or ''})  "
                     f"{nominee.get('phone') or ''}")
        y -= 6 * mm

    y = max(y - 14 * mm, 40 * mm)
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y,
                 "I hereby declare that the particulars given above are true to the best of my knowledge.")
    y -= 16 * mm
    c.line(20 * mm, y, 75 * mm, y)
    c.line(120 * mm, y, 180 * mm, y)
    c.setFont("Helvetica", 8.5)
    c.drawString(20 * mm, y - 4 * mm, "Signature / Thumb impression of employee")
    c.drawString(120 * mm, y - 4 * mm, "Signature of employer / authorised signatory")
    c.showPage()
    c.save()

    pdf_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    fname = (f"{'ESIC_Form1' if is_esic else 'EPF_Form11'}_"
             f"{(snap.get('employee_code') or reg['employee_user_id'])}.pdf")
    return {"ok": True, "file_name": fname, "pdf_base64": pdf_b64}
