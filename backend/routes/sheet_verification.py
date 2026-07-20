"""Iter 153 — Handwritten Attendance Sheet Verification (OCR reconciliation).

Flow
----
1. POST /api/admin/sheet-verification/ocr    — upload the handwritten sheet
   (photos/PDF) → LLM-OCR extracts rows {code, name, in, out, signature}.
2. POST /api/admin/sheet-verification/match  — match rows to employees +
   system punches (±tolerance min) → verdict per employee, saved as an
   MIS run in db.sheet_verifications.
3. POST /api/admin/sheet-verification/apply  — per-employee action:
     • "fix"   → apply sheet times to system punches.
                 Super/Company admin: applied DIRECTLY (audit-logged).
                 SUB-ADMIN: queued in db.sheet_fix_requests → SUPER ADMIN
                 approves via GET/PATCH /api/admin/sheet-fix-requests.
     • "leave" → keep the existing system punch (row marked resolved).

Verdicts: MATCHED · TIME_MISMATCH · NOT_IN_SYSTEM · NOT_ON_SHEET ·
UNMATCHED_ROW (+ no_signature flag).
"""
import difflib
import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    logger,
)

router = APIRouter(prefix="/api/admin", tags=["sheet-verification"])

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _mins(hhmm: Optional[str]) -> Optional[int]:
    m = _HHMM.match((hhmm or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _can_touch(admin: dict, company_id: str) -> bool:
    if admin["role"] == "super_admin":
        return True
    if admin["role"] == "company_admin":
        return admin.get("company_id") == company_id
    if admin["role"] == "sub_admin":
        from server import sub_admin_can_touch_company
        return sub_admin_can_touch_company(admin, company_id)
    return False


# ---------------------------------------------------------------------------
# 1. OCR extraction of the handwritten sheet
# ---------------------------------------------------------------------------
@router.post("/sheet-verification/ocr")
async def sheet_ocr(payload: Dict[str, Any] = Body(...),
                    authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])

    from routes.ocr import _strip_data_url, _pdf_to_image_b64, MAX_PAGES
    image_pages: List[str] = []
    for page in (payload.get("pages") or [])[:MAX_PAGES]:
        if not isinstance(page, dict):
            continue
        b64 = _strip_data_url(page.get("document_base64") or "")
        if not b64:
            continue
        mime = (page.get("mime_type") or "image/jpeg").lower()
        if "pdf" in mime:
            image_pages.extend(_pdf_to_image_b64(b64))
        else:
            image_pages.append(b64)
    image_pages = image_pages[:MAX_PAGES]
    if not image_pages:
        raise HTTPException(status_code=400, detail="No sheet pages uploaded")

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="EMERGENT_LLM_KEY is not configured")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"emergentintegrations not available: {exc}")

    system_prompt = (
        "You are an expert at reading HANDWRITTEN Indian factory attendance "
        "registers / muster rolls. Extract EVERY employee row from the sheet. "
        "Times may be written like 9, 9.15, 09:15, 9-15 — normalise all times "
        "to 24-hour HH:MM (assume factory context: IN 05:00–14:00 is morning, "
        "OUT after IN; e.g. '6' after an 09:00 IN means 18:00). "
        "Respond with STRICT JSON ONLY (no code fences):\n"
        "{\n"
        '  "rows": [ {"code": "employee code or null", "name": "as written",'
        ' "in_time": "HH:MM or null", "out_time": "HH:MM or null",'
        ' "ot_hours": number or null, "signature_present": true|false } ],\n'
        '  "sheet_date": "YYYY-MM-DD if written on the sheet else null",\n'
        '  "confidence": "high|medium|low"\n'
        "}"
    )
    chat = LlmChat(
        api_key=api_key,
        session_id=f"sheetocr-{admin['user_id']}",
        system_message=system_prompt,
    ).with_model("openai", "gpt-5.4")
    try:
        response = await chat.send_message(UserMessage(
            text="Extract all attendance rows from this handwritten sheet.",
            file_contents=[ImageContent(image_base64=b) for b in image_pages],
        ))
    except Exception as exc:  # noqa: BLE001
        logger.exception("[sheet-ocr] LLM call failed")
        raise HTTPException(status_code=502, detail=f"Sheet OCR failed: {exc}")

    text = (response or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|```$", "", text.strip(), flags=re.M).strip()
    try:
        data = json.loads(text)
    except ValueError:
        raise HTTPException(status_code=502, detail="Sheet OCR returned unreadable output — try a clearer photo.")

    rows = []
    for r in (data.get("rows") or []):
        if not isinstance(r, dict):
            continue
        it, ot_ = (r.get("in_time") or "").strip(), (r.get("out_time") or "").strip()
        rows.append({
            "code": str(r.get("code") or "").strip() or None,
            "name": str(r.get("name") or "").strip(),
            "in_time": it if _HHMM.match(it) else None,
            "out_time": ot_ if _HHMM.match(ot_) else None,
            "ot_hours": r.get("ot_hours"),
            "signature_present": bool(r.get("signature_present")),
        })
    return {"ok": True, "rows": rows,
            "sheet_date": data.get("sheet_date"),
            "confidence": data.get("confidence")}


# ---------------------------------------------------------------------------
# 2. Match against system punches → MIS run
# ---------------------------------------------------------------------------
@router.post("/sheet-verification/match")
async def sheet_match(payload: Dict[str, Any] = Body(...),
                      authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    company_id = payload.get("company_id") or admin.get("company_id")
    date = str(payload.get("date") or "").strip()
    tol = int(payload.get("tolerance_min") or 15)
    sheet_rows = payload.get("rows") or []
    if not company_id or not _can_touch(admin, company_id):
        raise HTTPException(status_code=403, detail="No access to this firm")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    if not sheet_rows:
        raise HTTPException(status_code=400, detail="No sheet rows to match")

    emps = await db.users.find(
        {"company_id": company_id, "role": "employee", "disabled": {"$ne": True}},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "father_name": 1},
    ).to_list(3000)
    by_code = {str(e.get("employee_code") or "").strip().lower(): e
               for e in emps if e.get("employee_code")}
    recs = await db.attendance.find(
        {"company_id": company_id, "date": date, "status": {"$ne": "rejected"},
         "kind": {"$in": ["in", "out"]}},
        {"_id": 0, "user_id": 1, "kind": 1, "at": 1, "record_id": 1},
    ).sort([("at", 1)]).to_list(20000)
    sys_by_user: Dict[str, Dict[str, str]] = {}
    for r in recs:
        hh = str(r.get("at") or "")[11:16]
        d = sys_by_user.setdefault(r["user_id"], {})
        if r["kind"] == "in" and "in" not in d:
            d["in"] = hh
        elif r["kind"] == "out":
            d["out"] = hh  # keep the LAST out

    def _match_emp(row) -> Optional[dict]:
        c = str(row.get("code") or "").strip().lower()
        if c and c in by_code:
            return by_code[c]
        nm = (row.get("name") or "").strip().lower()
        if not nm:
            return None
        best, best_r = None, 0.0
        for e in emps:
            r_ = difflib.SequenceMatcher(None, nm, (e.get("name") or "").lower()).ratio()
            if r_ > best_r:
                best, best_r = e, r_
        return best if best_r >= 0.75 else None

    out_rows: List[dict] = []
    matched_uids: set = set()
    for row in sheet_rows:
        emp = _match_emp(row)
        sys = sys_by_user.get(emp["user_id"]) if emp else None
        verdict = "UNMATCHED_ROW"
        d_in = d_out = None
        if emp:
            matched_uids.add(emp["user_id"])
            s_in, s_out = row.get("in_time"), row.get("out_time")
            y_in, y_out = (sys or {}).get("in"), (sys or {}).get("out")
            if not sys or (not y_in and not y_out):
                verdict = "NOT_IN_SYSTEM"
            else:
                mi, mo = _mins(s_in), _mins(s_out)
                yi, yo = _mins(y_in), _mins(y_out)
                d_in = abs(mi - yi) if (mi is not None and yi is not None) else None
                d_out = abs(mo - yo) if (mo is not None and yo is not None) else None
                bad = ((d_in is not None and d_in > tol) or
                       (d_out is not None and d_out > tol) or
                       (mi is not None and yi is None) or
                       (mo is not None and yo is None))
                verdict = "TIME_MISMATCH" if bad else "MATCHED"
        out_rows.append({
            "sheet": row,
            "user_id": emp["user_id"] if emp else None,
            "employee_code": (emp or {}).get("employee_code"),
            "name": (emp or {}).get("name") or row.get("name"),
            "system_in": (sys or {}).get("in"),
            "system_out": (sys or {}).get("out"),
            "delta_in_min": d_in, "delta_out_min": d_out,
            "verdict": verdict,
            "no_signature": not row.get("signature_present"),
            "resolution": None,  # fixed | left | pending_approval
        })
    # Employees punched in the system but missing from the sheet.
    for uid, sys in sys_by_user.items():
        if uid in matched_uids:
            continue
        e = next((x for x in emps if x["user_id"] == uid), None)
        if not e:
            continue
        out_rows.append({
            "sheet": None, "user_id": uid,
            "employee_code": e.get("employee_code"), "name": e.get("name"),
            "system_in": sys.get("in"), "system_out": sys.get("out"),
            "delta_in_min": None, "delta_out_min": None,
            "verdict": "NOT_ON_SHEET", "no_signature": True, "resolution": None,
        })

    summary = {}
    for r in out_rows:
        summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1
    run = {
        "run_id": f"shv_{uuid.uuid4().hex[:10]}",
        "company_id": company_id, "date": date, "tolerance_min": tol,
        "rows": out_rows, "summary": summary,
        "created_by": admin["user_id"], "created_by_role": admin["role"],
        "created_at": now_iso(),
    }
    await db.sheet_verifications.insert_one(dict(run))
    run.pop("_id", None)
    return {"ok": True, "run": run}


@router.get("/sheet-verification/runs")
async def sheet_runs(company_id: Optional[str] = Query(None),
                     authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    q: Dict[str, Any] = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif company_id:
        q["company_id"] = company_id
    runs = await db.sheet_verifications.find(
        q, {"_id": 0, "rows": 0}).sort([("created_at", -1)]).to_list(50)
    return {"runs": runs}


@router.get("/sheet-verification/runs/{run_id}")
async def sheet_run_detail(run_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    run = await db.sheet_verifications.find_one({"run_id": run_id}, {"_id": 0})
    if not run or not _can_touch(admin, run["company_id"]):
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run": run}


# ---------------------------------------------------------------------------
# 3. Per-employee action: FIX with OCR sheet time / LEAVE existing punch
# ---------------------------------------------------------------------------
async def _apply_sheet_fix(actor: dict, company_id: str, date: str,
                           user_id: str, sheet_in: Optional[str],
                           sheet_out: Optional[str]) -> List[str]:
    """Write the sheet times into the system punches. Existing punch of the
    kind → time edited (audit fields set); missing → manual punch created.
    Returns a list of human-readable change notes."""
    notes: List[str] = []
    reason = "Handwritten Sheet Verification (OCR)"
    for kind, hhmm in (("in", sheet_in), ("out", sheet_out)):
        if not hhmm or not _HHMM.match(hhmm):
            continue
        new_at = f"{date}T{hhmm}:00Z"
        rec = await db.attendance.find_one(
            {"company_id": company_id, "user_id": user_id, "date": date,
             "kind": kind, "status": {"$ne": "rejected"}},
            {"_id": 0, "record_id": 1, "at": 1, "original_at": 1},
            sort=[("at", 1 if kind == "in" else -1)],
        )
        if rec:
            if str(rec.get("at") or "")[11:16] == hhmm:
                continue  # already identical
            await db.attendance.update_one(
                {"record_id": rec["record_id"]},
                {"$set": {
                    "at": new_at,
                    "original_at": rec.get("original_at") or rec.get("at"),
                    "edited_at": now_iso(), "edited_by": actor["user_id"],
                    "edit_reason": reason,
                }})
            notes.append(f"{kind.upper()} {str(rec.get('at') or '')[11:16]} → {hhmm}")
        else:
            await db.attendance.insert_one({
                "record_id": f"att_{uuid.uuid4().hex[:12]}",
                "user_id": user_id, "company_id": company_id,
                "date": date, "kind": kind, "at": new_at,
                "source": "manual_admin", "status": "approved",
                "approved_by": actor["user_id"], "manual_reason": reason,
                "created_by": actor["user_id"], "created_at": now_iso(),
            })
            notes.append(f"{kind.upper()} created {hhmm}")
    return notes


async def _set_row_resolution(run_id: str, user_id: Optional[str],
                              sheet_name: Optional[str], resolution: str):
    run = await db.sheet_verifications.find_one({"run_id": run_id}, {"_id": 0, "rows": 1})
    if not run:
        return
    rows = run.get("rows") or []
    for r in rows:
        if (user_id and r.get("user_id") == user_id) or \
           (not user_id and r.get("sheet") and (r["sheet"].get("name") == sheet_name)):
            r["resolution"] = resolution
    await db.sheet_verifications.update_one({"run_id": run_id}, {"$set": {"rows": rows}})


@router.post("/sheet-verification/apply")
async def sheet_apply(payload: Dict[str, Any] = Body(...),
                      authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    run_id = payload.get("run_id")
    user_id = payload.get("user_id")
    action = payload.get("action")  # fix | leave
    if action not in ("fix", "leave"):
        raise HTTPException(status_code=400, detail="action must be 'fix' or 'leave'")
    run = await db.sheet_verifications.find_one({"run_id": run_id}, {"_id": 0})
    if not run or not _can_touch(admin, run["company_id"]):
        raise HTTPException(status_code=404, detail="Run not found")
    row = next((r for r in run.get("rows", []) if r.get("user_id") == user_id), None)
    if not row:
        raise HTTPException(status_code=404, detail="Employee row not found in this run")

    if action == "leave":
        await _set_row_resolution(run_id, user_id, None, "left")
        return {"ok": True, "resolution": "left"}

    sheet = row.get("sheet") or {}
    s_in, s_out = sheet.get("in_time"), sheet.get("out_time")
    if not s_in and not s_out:
        raise HTTPException(status_code=400, detail="Sheet has no times for this employee — nothing to apply")

    # SUB-ADMIN fixes need SUPER ADMIN approval.
    if admin["role"] == "sub_admin":
        req = {
            "request_id": f"sfr_{uuid.uuid4().hex[:10]}",
            "run_id": run_id, "company_id": run["company_id"],
            "date": run["date"], "user_id": user_id,
            "employee_name": row.get("name"),
            "employee_code": row.get("employee_code"),
            "sheet_in": s_in, "sheet_out": s_out,
            "system_in": row.get("system_in"), "system_out": row.get("system_out"),
            "status": "pending",
            "requested_by": admin["user_id"], "requested_by_name": admin.get("name"),
            "requested_at": now_iso(),
        }
        await db.sheet_fix_requests.insert_one(dict(req))
        await _set_row_resolution(run_id, user_id, None, "pending_approval")
        return {"ok": True, "resolution": "pending_approval",
                "message": "Sent to Super Admin for approval."}

    notes = await _apply_sheet_fix(admin, run["company_id"], run["date"],
                                   user_id, s_in, s_out)
    await _set_row_resolution(run_id, user_id, None, "fixed")
    return {"ok": True, "resolution": "fixed", "changes": notes}


# ---------------------------------------------------------------------------
# 4. Super Admin approval queue for sub-admin fixes
# ---------------------------------------------------------------------------
@router.get("/sheet-fix-requests")
async def list_sheet_fix_requests(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    q: Dict[str, Any] = {"status": "pending"}
    if admin["role"] == "sub_admin":
        q["requested_by"] = admin["user_id"]
    reqs = await db.sheet_fix_requests.find(q, {"_id": 0}).sort(
        [("requested_at", -1)]).to_list(200)
    return {"requests": reqs}


@router.patch("/sheet-fix-requests/{request_id}")
async def decide_sheet_fix(request_id: str,
                           payload: Dict[str, Any] = Body(...),
                           authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    decision = payload.get("decision")
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be approve|reject")
    req = await db.sheet_fix_requests.find_one({"request_id": request_id}, {"_id": 0})
    if not req or req.get("status") != "pending":
        raise HTTPException(status_code=404, detail="Pending request not found")
    changes: List[str] = []
    if decision == "approve":
        changes = await _apply_sheet_fix(
            admin, req["company_id"], req["date"], req["user_id"],
            req.get("sheet_in"), req.get("sheet_out"))
        await _set_row_resolution(req["run_id"], req["user_id"], None, "fixed")
    else:
        await _set_row_resolution(req["run_id"], req["user_id"], None, "left")
    await db.sheet_fix_requests.update_one(
        {"request_id": request_id},
        {"$set": {"status": "approved" if decision == "approve" else "rejected",
                  "decided_by": admin["user_id"], "decided_at": now_iso(),
                  "changes": changes}})
    return {"ok": True, "status": decision, "changes": changes}
