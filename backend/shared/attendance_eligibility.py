"""Iter 581 — Attendance Policy Based Employee Onboarding & Attendance
Eligibility — the CENTRAL VALIDATION ENGINE.

Every raw punch (PWA app, biometric ADMS/iClock, vendor Punch API, ZK
push) passes through this ONE engine before it is stored. Raw punches
are NEVER deleted; instead each record carries an eligibility state:

  * ACTIVE   — onboarding data complete → punch counts normally.
  * HELD     — mandatory data missing but still inside the Permission-Days
               window → punch stored with status "held" (excluded from
               attendance / hours / payroll until released).
  * BLOCKED  — mandatory data missing AND the permission window is over →
               punch stored with status "blocked" (HR may still release
               manually with a MANDATORY reason).
  * RELEASED — a held/blocked punch approved by HR (or auto-released on
               data completion) → legacy status restored so it counts.
  * REJECTED — HR rejected the held/blocked punch → status "rejected".

Config lives inside the firm's Attendance Policy blob:
``companies.attendance_policy.onboarding_gate`` — see _validate_policy
in server.py. The permission window starts at the LATER of the
employee's joining date (users.doj) and the date the gate was enabled,
so switching the gate on for an existing workforce grants everyone the
full window instead of instantly blocking them.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

REQUIREMENT_LABELS = {
    "aadhaar": "Aadhaar number",
    "bank": "Bank account & IFSC",
    "pan": "PAN number",
    "photo": "Profile photo",
}

# Fields the engine needs from the employee document. profile photo is
# checked separately (base64 blobs are too heavy to project per punch).
USER_PROJECTION = {
    "_id": 0, "user_id": 1, "company_id": 1, "role": 1, "name": 1,
    "employee_code": 1, "doj": 1, "created_at": 1,
    "aadhar_number": 1, "pan_number": 1,
    "bank_account_number": 1, "bank_account": 1,
    "ifsc_code": 1, "bank_ifsc": 1,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def gate_from_company(company: Optional[dict]) -> Dict[str, Any]:
    """Effective onboarding-gate config for a firm (safe defaults)."""
    og = ((company or {}).get("attendance_policy") or {}).get("onboarding_gate") or {}
    try:
        days = int(og.get("permission_days", 7) or 0)
    except (TypeError, ValueError):
        days = 7
    return {
        "enabled": bool(og.get("enabled")),
        "require_aadhaar": bool(og.get("require_aadhaar", True)),
        "require_bank": bool(og.get("require_bank", True)),
        "require_pan": bool(og.get("require_pan", False)),
        "require_photo": bool(og.get("require_photo", True)),
        "permission_days": max(0, min(90, days)),
        "auto_release": bool(og.get("auto_release", True)),
        "enabled_at": og.get("enabled_at"),
    }


def _filled(v: Any) -> bool:
    return bool(str(v or "").strip())


def missing_requirements(user_doc: dict, gate: dict,
                         has_photo: Optional[bool] = None) -> List[str]:
    """List of missing mandatory onboarding items for one employee."""
    missing: List[str] = []
    if gate.get("require_aadhaar") and not _filled(user_doc.get("aadhar_number")):
        missing.append("aadhaar")
    if gate.get("require_bank"):
        acct = _filled(user_doc.get("bank_account_number")) or _filled(user_doc.get("bank_account"))
        ifsc = _filled(user_doc.get("ifsc_code")) or _filled(user_doc.get("bank_ifsc"))
        if not (acct and ifsc):
            missing.append("bank")
    if gate.get("require_pan") and not _filled(user_doc.get("pan_number")):
        missing.append("pan")
    if gate.get("require_photo"):
        hp = has_photo if has_photo is not None else _filled(user_doc.get("profile_photo_base64"))
        if not hp:
            missing.append("photo")
    return missing


def _parse_date_any(v: Any) -> Optional[date]:
    s = str(v or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        return None


def window_start(user_doc: dict, gate: dict) -> Optional[date]:
    """Permission window starts at the LATER of joining date and the day
    the gate was enabled (existing workforce gets the full window)."""
    doj = _parse_date_any(user_doc.get("doj")) or _parse_date_any(user_doc.get("created_at"))
    enabled_at = _parse_date_any(gate.get("enabled_at"))
    cands = [d for d in (doj, enabled_at) if d]
    return max(cands) if cands else None


def classify(gate: dict, missing: List[str], user_doc: dict,
             punch_date: str) -> Dict[str, Any]:
    """ACTIVE / HELD / BLOCKED decision for one punch."""
    out: Dict[str, Any] = {
        "gate_enabled": bool(gate.get("enabled")),
        "eligibility": "ACTIVE",
        "missing": list(missing),
        "missing_labels": [REQUIREMENT_LABELS.get(m, m) for m in missing],
        "permission_days": int(gate.get("permission_days", 7) or 0),
        "auto_release": bool(gate.get("auto_release", True)),
        "days_left": None,
        "deadline": None,
    }
    if not out["gate_enabled"] or not missing:
        return out
    start = window_start(user_doc, gate)
    pd = _parse_date_any(punch_date) or date.today()
    if start is None:
        # No joining date on file — be lenient, hold instead of block.
        out["eligibility"] = "HELD"
        out["days_left"] = out["permission_days"]
        return out
    deadline = start + timedelta(days=out["permission_days"])
    out["deadline"] = deadline.isoformat()
    out["days_left"] = max(0, (deadline - pd).days)
    out["eligibility"] = "HELD" if pd < deadline else "BLOCKED"
    return out


async def has_profile_photo(db, user_id: str) -> bool:
    n = await db.users.count_documents(
        {"user_id": user_id, "profile_photo_base64": {"$nin": [None, ""]}},
        limit=1)
    return n > 0


async def evaluate_for_punch(db, user_id: str, company: Optional[dict] = None,
                             company_id: Optional[str] = None,
                             punch_date: Optional[str] = None) -> Dict[str, Any]:
    """Full async evaluation for a single punch about to be stored."""
    if company is None:
        company = await db.companies.find_one(
            {"company_id": company_id},
            {"_id": 0, "attendance_policy.onboarding_gate": 1}) or {}
    gate = gate_from_company(company)
    if not gate["enabled"]:
        return {"gate_enabled": False, "eligibility": "ACTIVE", "missing": [],
                "missing_labels": [], "auto_release": False,
                "permission_days": 0, "days_left": None, "deadline": None}
    u = await db.users.find_one({"user_id": user_id}, USER_PROJECTION) or {}
    if (u.get("role") or "employee") != "employee":
        return {"gate_enabled": True, "eligibility": "ACTIVE", "missing": [],
                "missing_labels": [], "auto_release": gate["auto_release"],
                "permission_days": gate["permission_days"],
                "days_left": None, "deadline": None}
    hp = await has_profile_photo(db, user_id) if gate["require_photo"] else None
    missing = missing_requirements(u, gate, has_photo=hp)
    return classify(gate, missing, u, punch_date or date.today().isoformat())


def apply_to_record(record: dict, ev: Optional[dict]) -> dict:
    """Stamp eligibility on a punch record ABOUT TO BE INSERTED. The raw
    punch is always stored — held/blocked records simply carry a
    non-counting legacy status until HR releases them."""
    if not ev or not ev.get("gate_enabled"):
        return record
    elig = ev.get("eligibility") or "ACTIVE"
    record["eligibility_status"] = elig
    if elig == "ACTIVE":
        return record
    record["eligibility_missing"] = ev.get("missing") or []
    record["eligibility_deadline"] = ev.get("deadline")
    # Snapshot the status the punch WOULD have had, so a release restores
    # the original workflow (approved vs pending-approval).
    record["pre_hold_status"] = record.get("status") or "approved"
    record["status"] = "held" if elig == "HELD" else "blocked"
    record["pending_reason"] = "onboarding_incomplete"
    record["held_at"] = _now_iso()
    return record


async def bulk_apply(db, company_id: str, records: List[dict]) -> None:
    """Batch variant for machine/API ingest paths (vendor Punch API, ZK
    push). Loads the gate + all involved employees ONCE, then stamps each
    record in place before insertion."""
    if not records:
        return
    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "attendance_policy.onboarding_gate": 1}) or {}
    gate = gate_from_company(company)
    if not gate["enabled"]:
        return
    uids = list({r.get("user_id") for r in records if r.get("user_id")})
    docs = {u["user_id"]: u async for u in db.users.find(
        {"user_id": {"$in": uids}}, USER_PROJECTION)}
    with_photo: set = set()
    if gate["require_photo"]:
        with_photo = set(await db.users.distinct(
            "user_id",
            {"user_id": {"$in": uids},
             "profile_photo_base64": {"$nin": [None, ""]}}))
    for rec in records:
        u = docs.get(rec.get("user_id"))
        if not u or (u.get("role") or "employee") != "employee":
            continue
        if (rec.get("status") or "approved") not in ("approved", "pending"):
            continue  # exceptions / duplicates never enter the gate
        missing = missing_requirements(
            u, gate,
            has_photo=(u["user_id"] in with_photo) if gate["require_photo"] else None)
        ev = classify(gate, missing, u, rec.get("date") or "")
        apply_to_record(rec, ev)


async def auto_release_held(db, user_id: str,
                            released_by: str = "system:auto-release",
                            reason: str = "Auto-released — onboarding data completed") -> int:
    """Release every HELD punch of one employee (BLOCKED punches are NEVER
    auto-released; HR must release them manually with a reason)."""
    n = 0
    async for r in db.attendance.find(
            {"user_id": user_id, "status": "held"},
            {"_id": 0, "record_id": 1, "pre_hold_status": 1}):
        await db.attendance.update_one(
            {"record_id": r["record_id"], "status": "held"},
            {"$set": {
                "status": r.get("pre_hold_status") or "approved",
                "eligibility_status": "RELEASED",
                "released_at": _now_iso(),
                "released_by": released_by,
                "release_reason": reason,
            }})
        n += 1
    return n


async def auto_release_if_complete(db, user_id: str) -> int:
    """Called after any KYC/photo update (and lazily on the next ACTIVE
    punch): if the firm's gate has auto-release ON and the employee's data
    is now complete, release all their HELD punches."""
    u = await db.users.find_one({"user_id": user_id}, USER_PROJECTION) or {}
    if not u or (u.get("role") or "employee") != "employee" or not u.get("company_id"):
        return 0
    company = await db.companies.find_one(
        {"company_id": u["company_id"]},
        {"_id": 0, "attendance_policy.onboarding_gate": 1}) or {}
    gate = gate_from_company(company)
    if not (gate["enabled"] and gate["auto_release"]):
        return 0
    hp = await has_profile_photo(db, user_id) if gate["require_photo"] else None
    if missing_requirements(u, gate, has_photo=hp):
        return 0
    n = await auto_release_held(db, user_id)
    if n:
        try:
            await db.notifications.insert_one({
                "notification_id": f"n_{uuid.uuid4().hex[:10]}",
                "company_id": u.get("company_id"),
                "audience": "user",
                "target_user_id": user_id,
                "type": "attendance.released",
                "title": "Attendance released",
                "body": (f"Your onboarding data is complete — {n} held "
                         f"punch{'es' if n != 1 else ''} were released and "
                         f"now count toward your attendance."),
                "created_at": _now_iso(),
                "created_by": "system",
            })
        except Exception:
            pass
    return n
