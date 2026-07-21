"""Iter 232 — ATTENDANCE DOCTOR (user request: "Total Duty Hours blank").

Two tools that only READ or repair ATTENDANCE punches — payroll, salary
runs, leave and master data are never touched:

  * GET  /api/admin/attendance-doctor
        Per employee-day diagnosis: raw punches (ALL statuses) → pairing
        result → duty computation → EXACT reason a day is blank
        (pending approval / missing IN / missing OUT / pairing failed /
        weekly off / no punches).

  * POST /api/admin/attendance-doctor/repair
        "Auto Repair Attendance": re-runs the Iter-231 machine-punch
        normalisation over the punches ALREADY stored for a month —
        pairing-aware bounce handling, same-kind run collapse and
        cross-midnight re-dating. Noise punches are marked
        ``status="auto_ignored"`` (reversible — never deleted) and night
        OUTs are re-dated to the day the shift started. Manual / mobile
        app punches are NEVER modified. ``preview=true`` returns the
        proposed changes without applying them.
"""
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from server import db, get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api/admin/attendance-doctor", tags=["attendance-doctor"])

MACHINE_SRC = ("import", "zkteco", "bio", "excel")


def _is_machine(src: str) -> bool:
    s = str(src or "")
    return any(s.startswith(p) for p in MACHINE_SRC)


def _dt(p: Dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(p["at"]).replace("Z", "+00:00"))


async def _auth(authorization: Optional[str], company_id: str):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    if user["role"] == "company_admin" and user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not your firm")
    return user


def _pair_day(punches: List[Dict[str, Any]]):
    """Mirror of the grid's pairing: chronological IN→OUT pairs. Returns
    (pairs, unpaired, duty_minutes). ``punches`` = approved only, already
    cross-midnight stitched."""
    pairs, unpaired = [], []
    open_in: Optional[Dict[str, Any]] = None
    for p in sorted(punches, key=_dt):
        if p["kind"] == "in":
            if open_in is not None:
                unpaired.append(open_in)
            open_in = p
        else:
            if open_in is None:
                unpaired.append(p)
            else:
                pairs.append((open_in, p))
                open_in = None
    if open_in is not None:
        unpaired.append(open_in)
    duty_min = sum(int((_dt(b) - _dt(a)).total_seconds() // 60) for a, b in pairs)
    return pairs, unpaired, duty_min


def _stitch(by_day: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    """Same shape as server.stitch_cross_day_ot (kept local to avoid a
    circular import of the 20k-line module's private helpers)."""
    from server import stitch_cross_day_ot
    return stitch_cross_day_ot(by_day)


@router.get("")
async def attendance_doctor(
    company_id: str,
    month: str,
    user_id: Optional[str] = None,
    only_problem_days: bool = True,
    authorization: Optional[str] = Header(None),
):
    """Diagnose why days are blank in the IN/OUT sheet / Duty HRS."""
    await _auth(authorization, company_id)
    if len(month) != 7:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    q_users: Dict[str, Any] = {"company_id": company_id, "role": "employee"}
    if user_id:
        q_users["user_id"] = user_id
    employees = await db.users.find(
        q_users, {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "bio_code": 1},
    ).sort([("employee_code", 1)]).to_list(4000)
    uids = [e["user_id"] for e in employees]
    emp_by_id = {e["user_id"]: e for e in employees}

    date_from, date_to = f"{month}-01", f"{month}-31"
    all_by_user_day: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    async for p in db.attendance.find(
        {"user_id": {"$in": uids}, "date": {"$gte": date_from, "$lte": date_to}},
        {"_id": 0, "user_id": 1, "date": 1, "kind": 1, "at": 1, "source": 1, "status": 1},
    ).sort([("user_id", 1), ("at", 1)]):
        all_by_user_day[p["user_id"]][p["date"]].append(p)

    out_rows: List[Dict[str, Any]] = []
    for uid, days in all_by_user_day.items():
        emp = emp_by_id.get(uid) or {}
        approved_by_day = {
            d: [p for p in ps if p.get("status") == "approved"]
            for d, ps in days.items()
        }
        stitched = _stitch({d: ps for d, ps in approved_by_day.items() if ps})
        for d in sorted(days.keys()):
            raw = days[d]
            appr = stitched.get(d, [])
            pairs, unpaired, duty_min = _pair_day(appr)
            reasons: List[str] = []
            pending = [p for p in raw if p.get("status") == "pending"]
            ignored = [p for p in raw if p.get("status") == "auto_ignored"]
            if not raw:
                reasons.append("no_punches")
            elif not appr and pending:
                reasons.append("pending_approval")
            elif not appr:
                reasons.append("no_approved_punches")
            if unpaired:
                for p in unpaired:
                    reasons.append("missing_out" if p["kind"] == "in" else "missing_in")
            duty_blank = bool(unpaired) or not pairs
            if only_problem_days and not duty_blank and not pending:
                continue
            out_rows.append({
                "user_id": uid,
                "employee_code": emp.get("employee_code"),
                "name": emp.get("name"),
                "bio_code": emp.get("bio_code"),
                "date": d,
                "punches": [
                    {"time": str(p["at"])[11:16], "date": p["date"],
                     "kind": p["kind"], "source": p.get("source"),
                     "status": p.get("status")}
                    for p in sorted(raw, key=_dt)
                ],
                "pairs": [
                    {"in": str(a["at"])[11:16], "out": str(b["at"])[11:16],
                     "minutes": int((_dt(b) - _dt(a)).total_seconds() // 60)}
                    for a, b in pairs
                ],
                "duty_minutes": duty_min if not duty_blank else 0,
                "duty_hhmm": (f"{duty_min // 60:02d}:{duty_min % 60:02d}"
                              if (pairs and not unpaired) else None),
                "duty_blank": duty_blank,
                "reasons": sorted(set(reasons)) or (["ok"] if not duty_blank else ["pairing_failed"]),
                "pending_count": len(pending),
                "ignored_count": len(ignored),
            })
    out_rows.sort(key=lambda r: (str(r.get("employee_code") or ""), r["date"]))
    return {"month": month, "rows": out_rows, "total_problem_days": sum(1 for r in out_rows if r["duty_blank"])}


class RepairBody(BaseModel):
    company_id: str
    month: str
    user_id: Optional[str] = None
    preview: bool = True


@router.post("/repair")
async def auto_repair_attendance(
    body: RepairBody,
    authorization: Optional[str] = Header(None),
):
    """Auto Repair: normalise APPROVED MACHINE punches of the month with
    the Iter-231 rules. Changes: (a) noise punches → status
    ``auto_ignored`` (reversible), (b) cross-midnight night OUTs re-dated
    to the shift's start day. Manual / mobile punches untouched."""
    admin = await _auth(authorization, body.company_id)
    q_users: Dict[str, Any] = {"company_id": body.company_id, "role": "employee"}
    if body.user_id:
        q_users["user_id"] = body.user_id
    uids = [u["user_id"] async for u in db.users.find(q_users, {"_id": 0, "user_id": 1})]
    date_from, date_to = f"{body.month}-01", f"{body.month}-31"
    by_user: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    async for p in db.attendance.find(
        {"user_id": {"$in": uids}, "date": {"$gte": date_from, "$lte": date_to},
         "status": "approved"},
        {"_id": 0, "attendance_id": 1, "user_id": 1, "date": 1, "kind": 1,
         "at": 1, "source": 1},
    ).sort([("user_id", 1), ("at", 1)]):
        by_user[p["user_id"]].append(p)

    ignore_ids: List[str] = []
    redate: List[Dict[str, Any]] = []
    changes: List[Dict[str, Any]] = []

    for uid, plist in by_user.items():
        # Only machine punches are normalised; manual/app punches pass
        # through untouched but participate in the sequence context.
        seq = sorted(plist, key=_dt)
        kept: List[Dict[str, Any]] = []
        for i, p in enumerate(seq):
            if not _is_machine(p.get("source")):
                kept.append(p)
                continue
            prev = kept[-1] if kept else None
            nxt = seq[i + 1] if i + 1 < len(seq) else None
            # Rule 1 (iter 231) — quick IN ≤15 min after an OUT: keep only
            # when it PAIRS with the next punch being an OUT within 16 h.
            if (
                p["kind"] == "in" and prev is not None and prev["kind"] == "out"
                and 0 <= (_dt(p) - _dt(prev)).total_seconds() <= 15 * 60
            ):
                pairs_next = (
                    nxt is not None and nxt["kind"] == "out"
                    and 0 < (_dt(nxt) - _dt(p)).total_seconds() <= 16 * 3600
                )
                if not pairs_next:
                    ignore_ids.append(p.get("attendance_id"))
                    changes.append({"user_id": uid, "date": p["date"],
                                    "at": p["at"], "kind": p["kind"],
                                    "action": "ignore_noise_in"})
                    continue
            # Rule 2 — same-kind run handling: consecutive INs → keep the
            # first (unless ≥6 h apart = new session); consecutive OUTs →
            # keep the LAST (drop the earlier one).
            if prev is not None and prev["kind"] == p["kind"]:
                gap = (_dt(p) - _dt(prev)).total_seconds()
                if p["kind"] == "in" and gap < 6 * 3600:
                    ignore_ids.append(p.get("attendance_id"))
                    changes.append({"user_id": uid, "date": p["date"],
                                    "at": p["at"], "kind": p["kind"],
                                    "action": "ignore_duplicate_in"})
                    continue
                if p["kind"] == "out" and gap < 6 * 3600 and _is_machine(prev.get("source")):
                    ignore_ids.append(prev.get("attendance_id"))
                    changes.append({"user_id": uid, "date": prev["date"],
                                    "at": prev["at"], "kind": prev["kind"],
                                    "action": "ignore_duplicate_out"})
                    kept[-1] = p
                    continue
            # Rule 3 — cross-midnight: a morning OUT (<12:00) directly
            # after the previous day's IN (≤16 h) belongs to that day.
            if (
                p["kind"] == "out" and _dt(p).hour < 12
                and prev is not None and prev["kind"] == "in"
                and prev["date"] < p["date"]
                and 0 < (_dt(p) - _dt(prev)).total_seconds() <= 16 * 3600
            ):
                redate.append({"attendance_id": p.get("attendance_id"),
                               "new_date": prev["date"]})
                changes.append({"user_id": uid, "date": p["date"],
                                "at": p["at"], "kind": p["kind"],
                                "action": f"redate_to_{prev['date']}"})
                p = {**p, "date": prev["date"]}
            kept.append(p)

    result = {
        "ok": True, "preview": body.preview,
        "to_ignore": len(ignore_ids), "to_redate": len(redate),
        "changes": changes[:300],
    }
    if body.preview:
        return result
    now_iso = datetime.utcnow().isoformat()
    tag = f"autorepair_{admin['user_id']}_{now_iso[:19]}"
    if ignore_ids:
        await db.attendance.update_many(
            {"attendance_id": {"$in": [i for i in ignore_ids if i]}},
            {"$set": {"status": "auto_ignored", "repair_tag": tag}})
    for r in redate:
        if r["attendance_id"]:
            await db.attendance.update_one(
                {"attendance_id": r["attendance_id"]},
                {"$set": {"date": r["new_date"], "repair_tag": tag}})
    result["applied_tag"] = tag
    return result


@router.post("/repair/undo")
async def undo_repair(
    body: RepairBody,
    authorization: Optional[str] = Header(None),
):
    """Undo ALL auto-repairs for the firm+month (restores auto_ignored →
    approved; re-dated punches keep their corrected date — re-run repair
    after undo if needed)."""
    await _auth(authorization, body.company_id)
    uids = [u["user_id"] async for u in db.users.find(
        {"company_id": body.company_id}, {"_id": 0, "user_id": 1})]
    r = await db.attendance.update_many(
        {"user_id": {"$in": uids}, "status": "auto_ignored",
         "date": {"$gte": f"{body.month}-01", "$lte": f"{body.month}-31"}},
        {"$set": {"status": "approved"}, "$unset": {"repair_tag": ""}})
    return {"ok": True, "restored": r.modified_count}
