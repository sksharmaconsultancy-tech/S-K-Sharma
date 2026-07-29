"""Iter 360 — AI UNIVERSAL PAYROLL IMPORT.

Upload ANY Excel/CSV payroll file → AI identifies the file type, company,
period and columns → matches employees → validates → suggests corrections
→ one-click import → auto payroll process (reuses the existing compliance
salary engine via ``use_imported_sheet``) → compliance generation links.

Collections:
  ai_import_jobs       {job_id, status, step, filename, analysis, summary...}
  ai_import_rows       {job_id, chunk, rows[]}          (500 rows / chunk)
  ai_universal_templates {fingerprint, company_id, mapping, file_type...}
  ai_import_audit      (immutable append-only log)

Endpoints (prefix /api/admin/ai-import):
  POST /analyze     {filename, content_base64, company_id?}
  POST /validate    {job_id, company_id, month, file_type, mapping}
  POST /commit      {job_id, targets[], create_new_employees, auto_payroll}
  GET  /job/{job_id}
  GET  /dashboard
  GET  /templates   · DELETE /templates/{fingerprint}
  GET  /compliance-check?company_id&month
  POST /explain     {question | issues[]}
"""
import asyncio
import base64
import difflib
import hashlib
import io
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Body, Header, HTTPException

from server import db, get_user_from_token, require_role  # noqa: E402

logger = logging.getLogger("ai_universal_import")
router = APIRouter(prefix="/api/admin/ai-import", tags=["ai-universal-import"])
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# ---------------------------------------------------------------------------
# Canonical fields + deterministic header hints
# ---------------------------------------------------------------------------
FIELD_HINTS: Dict[str, List[str]] = {
    "employee_code": ["emp code", "empcode", "emp id", "empid", "emp no",
                      "empno", "employee code", "employee id", "employee no",
                      "code", "sr no code", "token no", "ticket no"],
    "name": ["employee name", "emp name", "worker name", "labour name",
             "name of employee", "name of worker", "staff name", "name"],
    "father_name": ["father", "husband", "guardian"],
    "uan_no": ["uan"],
    "pf_no": ["pf no", "pf number", "pf a/c", "epf no", "pf account"],
    "esi_ip_no": ["esic no", "esi no", "ip no", "esic number", "insurance no",
                  "ip number", "esic ip"],
    "aadhaar_no": ["aadhaar", "aadhar", "adhar", "uid"],
    "pan_no": ["pan"],
    "phone": ["mobile", "phone", "contact"],
    "dob": ["date of birth", "dob", "birth date"],
    "doj": ["date of joining", "doj", "joining date", "join date",
            "appointment date"],
    "dol": ["date of leaving", "dol", "leaving date", "exit date",
            "resign date", "relieving"],
    "department": ["department", "dept"],
    "designation": ["designation", "post", "trade", "category of work"],
    "employee_type": ["employee type", "category", "worker type", "grade",
                      "staff/labour", "emp type"],
    "gender": ["gender", "sex", "male/female"],
    "bank_account": ["account no", "a/c no", "bank account", "acc no",
                     "account number", "bank a/c"],
    "bank_ifsc": ["ifsc"],
    "bank_name": ["bank name"],
    "present_days": ["present days", "present", "payable days", "paid days",
                     "days worked", "working days", "attendance", "p days",
                     "no of days", "days paid", "duty"],
    "ot_hours": ["ot hours", "overtime", "ot hrs", "o.t", "extra hours",
                 "ot"],
    "gross_earning": ["gross earning", "gross salary", "gross wages",
                      "total earning", "gross pay", "total wages",
                      "total salary", "gross amount", "gross"],
    "basic": ["basic"],
    "da": ["da", "dearness"],
    "hra": ["hra", "house rent"],
    "conveyance": ["conveyance", "conv", "transport"],
    "medical": ["medical"],
    "special": ["special allow"],
    "other_allowance": ["other allow", "misc allow", "oth allow",
                        "other earning"],
    "deduction_head": ["deduction head", "ded head"],
    "deduction_amount": ["deduction amount", "advance", "ded amount",
                         "other deduction", "recovery", "loan", "deduction"],
    "tds": ["tds", "income tax", "it deduction"],
    "pf_employee": ["pf deduction", "epf deduction", "pf employee",
                    "pf contribution", "pf amt", "pf amount"],
    "esic_employee": ["esic deduction", "esi deduction", "esic employee",
                      "esic contribution", "esi amount"],
    "pf_wages": ["pf wages", "epf wages", "pf gross", "pf basic"],
    "esic_wages": ["esic wages", "esi wages", "esic gross"],
    "net_salary": ["net salary", "net pay", "net amount", "take home",
                   "net payable", "amount payable", "net wages", "net"],
    "salary_monthly": ["monthly salary", "salary pm", "rate pm",
                       "monthly rate", "salary per month", "fixed salary"],
    "rate_daily": ["daily rate", "rate per day", "wage rate", "day rate",
                   "per day", "rate pd", "daily wage", "rate"],
    "leave_days": ["leave days", "leaves", "leave taken", "cl", "el", "sl",
                   "leave"],
    "leave_type": ["leave type"],
    "leave_from": ["leave from", "from date"],
    "leave_to": ["leave to", "to date"],
    "bonus_amount": ["bonus amount", "bonus payable", "bonus"],
    "arrear_amount": ["arrear", "arrears", "difference amount"],
    "increment_amount": ["increment", "revised salary", "new salary"],
    "month": ["month", "wage month", "salary month", "period"],
    "remarks": ["remarks", "notes", "comment"],
}
CANON_FIELDS = list(FIELD_HINTS.keys())
NUM_FIELDS = {"present_days", "ot_hours", "gross_earning", "basic", "da",
              "hra", "conveyance", "medical", "special", "other_allowance",
              "deduction_amount", "tds", "pf_employee", "esic_employee",
              "pf_wages", "esic_wages", "net_salary", "salary_monthly",
              "rate_daily", "leave_days", "bonus_amount", "arrear_amount",
              "increment_amount"}

FILE_TYPES = {
    "attendance_register": ("Attendance Register",
                            ["present_days", "employee_code"]),
    "salary_register": ("Salary Register", ["gross_earning", "net_salary"]),
    "employee_master": ("Employee Master", ["doj", "father_name",
                                            "designation"]),
    "pf_wage_sheet": ("PF Wage Sheet", ["uan_no", "pf_wages"]),
    "esic_wage_sheet": ("ESIC Wage Sheet", ["esi_ip_no", "esic_wages"]),
    "ot_register": ("OT Register", ["ot_hours"]),
    "leave_register": ("Leave Register", ["leave_days"]),
    "bank_salary_sheet": ("Bank Salary Sheet", ["bank_account", "bank_ifsc"]),
    "contract_labour_register": ("Contract Labour Register",
                                 ["rate_daily", "present_days"]),
    "bonus_register": ("Bonus Register", ["bonus_amount"]),
    "arrear_sheet": ("Arrear Sheet", ["arrear_amount"]),
    "increment_sheet": ("Increment Sheet", ["increment_amount"]),
    "contractor_wage_sheet": ("Contractor Wage Sheet",
                              ["rate_daily", "gross_earning"]),
    "custom": ("Custom Excel Format", []),
}
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
CHUNK = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _adm(authorization, company_id=None):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    return admin, company_id


async def _audit(admin: dict, job_id: str, action: str, detail: str = ""):
    await db.ai_import_audit.insert_one({
        "at": _now(), "job_id": job_id, "action": action, "detail": detail,
        "by": admin.get("name") or admin.get("email"),
        "by_id": admin.get("user_id")})


def _cell(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    return s


def _num(v) -> float:
    try:
        s = str(v).replace(",", "").strip()
        if not s or s.lower() in ("nan", "none", "-", ""):
            return 0.0
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", str(h or "").lower()).strip()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _read_frame(content: bytes, filename: str) -> pd.DataFrame:
    name = (filename or "").lower()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(io.BytesIO(content), header=None, dtype=object)
        if name.endswith(".xls"):
            return pd.read_excel(io.BytesIO(content), header=None,
                                 dtype=object, engine="xlrd")
        return pd.read_excel(io.BytesIO(content), header=None, dtype=object,
                             engine="openpyxl")
    except Exception as e:
        raise HTTPException(status_code=400,
                            detail=f"Could not read the file: {e}")


def _find_header_row(raw: pd.DataFrame) -> int:
    """Header row = row (within top 15) with the most recognisable headers."""
    best, best_n = 0, -1
    for i in range(min(15, len(raw))):
        cells = [_norm(c) for c in raw.iloc[i].tolist()]
        n = 0
        for cell in cells:
            if not cell:
                continue
            for hints in FIELD_HINTS.values():
                if any(h in cell for h in hints):
                    n += 1
                    break
        if n > best_n:
            best, best_n = i, n
    if best_n < 2:
        raise HTTPException(
            status_code=400,
            detail="Could not locate a header row — the sheet does not look "
                   "like a payroll/attendance file.")
    return best


def _rule_map(headers: List[str]) -> Dict[str, dict]:
    """Deterministic keyword mapping. Longest-hint match wins."""
    mapping: Dict[str, dict] = {}
    used_fields: set = set()
    scored = []
    for h in headers:
        hl = _norm(h)
        if not hl:
            continue
        best_f, best_len = None, 0
        for field, hints in FIELD_HINTS.items():
            for k in hints:
                if (hl == k or hl.replace(" ", "") == k.replace(" ", "")
                        or re.search(rf"\b{re.escape(k)}\b", hl)) \
                        and len(k) > best_len:
                    best_f, best_len = field, len(k)
        if best_f:
            scored.append((best_len, h, best_f))
    for _ln, h, f in sorted(scored, reverse=True):
        if f in used_fields:
            continue
        mapping[h] = {"field": f, "confidence": 95, "source": "rules"}
        used_fields.add(f)
    return mapping


def _detect_period(raw: pd.DataFrame, header_row: int,
                   filename: str) -> Optional[str]:
    """Scan top rows + filename for 'June 2026' / '06/2026' / '2026-06'."""
    texts = [filename or ""]
    for i in range(min(header_row + 2, len(raw))):
        texts.extend(_cell(c) for c in raw.iloc[i].tolist())
    for t in texts:
        tl = t.lower()
        m = re.search(r"(20\d{2})[-/\.](0?[1-9]|1[0-2])(?!\d)", tl)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}"
        m = re.search(r"(0?[1-9]|1[0-2])[-/\.](20\d{2})", tl)
        if m:
            return f"{m.group(2)}-{int(m.group(1)):02d}"
        for name, num in MONTHS.items():
            m = re.search(rf"\b{name}[a-z]*[,\s\-\.']*(20\d{{2}})", tl)
            if m:
                return f"{m.group(1)}-{num:02d}"
    return None


def _guess_file_type(fields: set, filename: str) -> List[dict]:
    """Score every file type by signature fields + filename keywords."""
    fn = _norm(filename)
    scores = []
    for kind, (title, sig) in FILE_TYPES.items():
        if kind == "custom":
            continue
        s = 0
        for f in sig:
            if f in fields:
                s += 40
        for w in title.lower().split():
            if w in fn and w not in ("register", "sheet"):
                s += 25
        # generic boosts
        if kind == "salary_register" and {"gross_earning",
                                          "present_days"} <= fields:
            s += 20
        if kind == "attendance_register" and "gross_earning" not in fields \
                and "present_days" in fields:
            s += 25
        if kind == "employee_master" and len(
                fields & {"father_name", "dob", "doj", "aadhaar_no",
                          "pan_no", "bank_account"}) >= 3:
            s += 30
        scores.append({"kind": kind, "title": title,
                       "confidence": min(s, 98)})
    scores.sort(key=lambda x: -x["confidence"])
    return scores[:3]


async def _llm_assist(headers: List[str], unmapped: List[str],
                      sample_rows: List[dict], top_text: str,
                      company_names: List[str]) -> dict:
    """One LLM call: file type + company + period + leftover columns."""
    if not EMERGENT_LLM_KEY:
        return {}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"ai-uimport-{uuid.uuid4().hex[:8]}",
            system_message=(
                "You analyse Indian payroll Excel files. Reply STRICT JSON "
                "only, no markdown. Keys: file_type (one of "
                + ", ".join(FILE_TYPES) + "), file_type_confidence (0-100), "
                "company_name (string or null — match against the provided "
                "portal company list if possible, else the name printed on "
                "the sheet), month (YYYY-MM or null), mapping (object header→"
                "canonical field or null; canonical fields: "
                + ", ".join(CANON_FIELDS) + ")."),
        ).with_model("openai", "gpt-5.4")
        payload = {
            "headers": headers, "unmapped_headers": unmapped,
            "sheet_top_text": top_text[:800],
            "sample_rows": sample_rows[:5],
            "portal_companies": company_names[:60],
        }
        resp = await chat.send_message(UserMessage(text=json.dumps(payload)))
        m = re.search(r"\{.*\}", str(resp), re.DOTALL)
        return json.loads(m.group(0)) if m else {}
    except Exception as e:  # noqa: BLE001
        logger.warning("[ai-import] LLM assist failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# STEP 1-4: ANALYZE
# ---------------------------------------------------------------------------
@router.post("/analyze")
async def analyze(body: dict = Body(...),
                  authorization: Optional[str] = Header(None)):
    admin, forced_cid = await _adm(authorization, body.get("company_id"))
    filename = body.get("filename") or "sheet.xlsx"
    b64 = body.get("content_base64") or ""
    if not b64:
        raise HTTPException(status_code=400,
                            detail="content_base64 is required")
    try:
        content = base64.b64decode(b64)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid base64 content")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400,
                            detail="File too large (max 25 MB)")

    raw = _read_frame(content, filename)
    header_row = _find_header_row(raw)
    headers = [_cell(c) for c in raw.iloc[header_row].tolist()]
    headers = [h for h in headers if h]
    header_idx = {j: _cell(c) for j, c in
                  enumerate(raw.iloc[header_row].tolist()) if _cell(c)}

    # rows
    rows: List[dict] = []
    for i in range(header_row + 1, len(raw)):
        r = raw.iloc[i]
        row = {}
        empty = True
        for j, h in header_idx.items():
            v = _cell(r.iloc[j]) if j < len(r) else ""
            row[h] = v
            if v:
                empty = False
        if empty or _norm(list(row.values())[0]).startswith("total") or \
                _norm(row.get("name") or "").startswith("total"):
            continue
        row["_row_no"] = i + 1
        rows.append(row)
    if not rows:
        raise HTTPException(status_code=400, detail="No data rows found")

    # SMART LEARNING — template fingerprint
    fp = hashlib.sha1("|".join(sorted(_norm(h) for h in headers))
                      .encode()).hexdigest()[:16]
    tpl = await db.ai_universal_templates.find_one(
        {"fingerprint": fp}, {"_id": 0})

    mapping = _rule_map(headers)
    unmapped = [h for h in headers if h not in mapping]
    if tpl:
        for h, f in (tpl.get("mapping") or {}).items():
            if h in headers and f in CANON_FIELDS:
                mapping[h] = {"field": f, "confidence": 99,
                              "source": "learned"}
        unmapped = [h for h in headers if h not in mapping]

    fields = {m["field"] for m in mapping.values()}
    top_text = " ".join(
        _cell(c) for i in range(min(header_row, 6))
        for c in raw.iloc[i].tolist() if _cell(c))
    period = _detect_period(raw, header_row, filename)
    candidates = _guess_file_type(fields, filename)

    # companies for matching
    comp_q: Dict[str, Any] = {}
    if forced_cid:
        comp_q["company_id"] = forced_cid
    companies = await db.companies.find(
        comp_q, {"_id": 0, "company_id": 1, "name": 1}).to_list(200)

    # LLM assist — file type confirmation, company, period, leftovers
    llm = {}
    need_llm = (unmapped or not period
                or not candidates or candidates[0]["confidence"] < 80)
    if need_llm and not tpl:
        llm = await _llm_assist(headers, unmapped, rows[:5], top_text,
                                [c["name"] for c in companies])
    for h, f in (llm.get("mapping") or {}).items():
        if h in headers and f in CANON_FIELDS and h not in mapping:
            mapping[h] = {"field": f, "confidence": 80, "source": "ai"}
    unmapped = [h for h in headers if h not in mapping]

    if tpl and tpl.get("file_type"):
        candidates = [{"kind": tpl["file_type"],
                       "title": FILE_TYPES.get(tpl["file_type"],
                                               ("Custom",))[0],
                       "confidence": 99}] + [
            c for c in candidates if c["kind"] != tpl["file_type"]][:2]
    elif llm.get("file_type") in FILE_TYPES:
        lc = int(llm.get("file_type_confidence") or 75)
        candidates = [{"kind": llm["file_type"],
                       "title": FILE_TYPES[llm["file_type"]][0],
                       "confidence": max(lc, (candidates[0]["confidence"]
                                              if candidates else 0))}] + [
            c for c in candidates if c["kind"] != llm["file_type"]][:2]
    if not candidates:
        candidates = [{"kind": "custom", "title": "Custom Excel Format",
                       "confidence": 50}]

    # STEP 2 — company identification
    comp_matches: List[dict] = []
    detected_name = (llm.get("company_name")
                     or (tpl or {}).get("company_name") or "")
    hay = (_norm(detected_name) + " " + _norm(top_text) + " "
           + _norm(filename))
    for c in companies:
        cn = _norm(c["name"])
        ratio = difflib.SequenceMatcher(None, cn, _norm(detected_name)
                                        or cn[:0]).ratio()
        score = 0
        if cn and cn in hay:
            score = 95
        elif detected_name and ratio > 0.75:
            score = int(ratio * 100)
        elif any(w in hay for w in cn.split() if len(w) > 4):
            score = 60
        if score:
            comp_matches.append({"company_id": c["company_id"],
                                 "name": c["name"], "confidence": score})
    comp_matches.sort(key=lambda x: -x["confidence"])
    if forced_cid:
        comp_matches = [{"company_id": forced_cid,
                         "name": next((c["name"] for c in companies
                                       if c["company_id"] == forced_cid),
                                      forced_cid),
                         "confidence": 100}]
    period = period or (llm.get("month")
                        if re.fullmatch(r"20\d{2}-\d{2}",
                                        str(llm.get("month") or ""))
                        else None)

    # persist job + rows
    job_id = f"aij_{uuid.uuid4().hex[:12]}"
    for c0 in range(0, len(rows), CHUNK):
        await db.ai_import_rows.insert_one(
            {"job_id": job_id, "chunk": c0 // CHUNK,
             "rows": rows[c0:c0 + CHUNK]})
    analysis = {
        "headers": headers, "header_row": header_row + 1,
        "fingerprint": fp, "learned_template": bool(tpl),
        "file_type_candidates": candidates,
        "company_matches": comp_matches[:5],
        "detected_company_name": detected_name or None,
        "period": period,
        "mapping": mapping, "unmapped": unmapped,
        "total_rows": len(rows),
    }
    await db.ai_import_jobs.insert_one({
        "job_id": job_id, "status": "analyzed", "filename": filename,
        "created_at": _now(), "created_by": admin["user_id"],
        "by_name": admin.get("name") or admin.get("email"),
        "analysis": analysis, "file_size": len(content)})
    await _audit(admin, job_id,
                 "upload+analyze", f"{filename} ({len(rows)} rows)")
    return {"job_id": job_id, **analysis, "sample_rows": rows[:8]}


# ---------------------------------------------------------------------------
# STEP 5-7: VALIDATE (matching + validation + corrections)
# ---------------------------------------------------------------------------
def _digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


async def _load_rows(job_id: str) -> List[dict]:
    rows: List[dict] = []
    async for ch in db.ai_import_rows.find(
            {"job_id": job_id}, {"_id": 0}).sort("chunk", 1):
        rows.extend(ch["rows"])
    return rows


def _canon_row(row: dict, mapping: Dict[str, str]) -> dict:
    out: Dict[str, Any] = {"_row_no": row.get("_row_no")}
    for h, f in mapping.items():
        v = row.get(h, "")
        out[f] = _num(v) if f in NUM_FIELDS else _cell(v)
    return out


async def _prev_month_gross(company_id: str, month: str) -> Dict[str, float]:
    y, m = int(month[:4]), int(month[5:7])
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    run = await db.compliance_salary_runs.find_one(
        {"company_id": company_id, "month": f"{y}-{m:02d}"},
        {"_id": 0, "rows.employee_code": 1, "rows.gross_paid": 1},
        sort=[("generated_at", -1)])
    return {str(r.get("employee_code")): float(r.get("gross_paid") or 0)
            for r in (run or {}).get("rows") or []}


@router.post("/validate")
async def validate(body: dict = Body(...),
                   authorization: Optional[str] = Header(None)):
    admin, cid = await _adm(authorization, body.get("company_id"))
    job_id = body.get("job_id")
    month = body.get("month") or ""
    file_type = body.get("file_type") or "custom"
    mapping: Dict[str, str] = {
        h: (m["field"] if isinstance(m, dict) else m)
        for h, m in (body.get("mapping") or {}).items()
        if (m["field"] if isinstance(m, dict) else m) in CANON_FIELDS}
    job = await db.ai_import_jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not cid:
        raise HTTPException(status_code=400, detail="company_id is required")
    if not re.fullmatch(r"20\d{2}-\d{2}", month):
        raise HTTPException(status_code=400,
                            detail="month must be YYYY-MM")

    raw_rows = await _load_rows(job_id)
    rows = [_canon_row(r, mapping) for r in raw_rows]

    # ---- employee master lookup indices ----
    emp_by: Dict[str, Dict[str, dict]] = {k: {} for k in (
        "code", "uan", "esic", "aadhaar", "pan", "mobile", "name")}
    masters: List[dict] = []
    async for u in db.users.find(
            {"role": "employee", "company_id": cid},
            {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
             "uan_no": 1, "esi_ip_no": 1, "aadhaar_no": 1, "pan_no": 1,
             "phone": 1, "dob": 1, "father_name": 1, "department": 1,
             "designation": 1, "bank_account": 1, "bank_ifsc": 1,
             "active": 1}):
        masters.append(u)
        code = _cell(u.get("employee_code")).lstrip("0") \
            or _cell(u.get("employee_code"))
        if code:
            emp_by["code"][code.lower()] = u
        for key, fld in (("uan", "uan_no"), ("esic", "esi_ip_no"),
                         ("aadhaar", "aadhaar_no"), ("mobile", "phone")):
            d = _digits(u.get(fld))
            if d:
                emp_by[key][d[-10:] if key == "mobile" else d] = u
        if u.get("pan_no"):
            emp_by["pan"][str(u["pan_no"]).upper().strip()] = u
        if u.get("name"):
            emp_by["name"][_norm(u["name"])] = u
    master_names = list(emp_by["name"].keys())
    prev_gross = await _prev_month_gross(cid, month)
    comp = await db.companies.find_one(
        {"company_id": cid},
        {"_id": 0, "name": 1, "compliance_policy": 1})
    min_wage = float(((comp or {}).get("compliance_policy") or {})
                     .get("minimum_wage_daily") or 0)
    y, m = int(month[:4]), int(month[5:7])
    cal_days = [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30,
                31, 31, 30, 31, 30, 31][m - 1]

    # ---- per-row matching + validation + corrections ----
    dup_track: Dict[str, Dict[str, int]] = {
        "uan_no": {}, "esi_ip_no": {}, "aadhaar_no": {},
        "employee_code": {}, "bank_account": {}}
    for r in rows:
        for f in dup_track:
            v = _cell(r.get(f))
            if v:
                dup_track[f][v] = dup_track[f].get(v, 0) + 1

    out_rows: List[dict] = []
    counts = {"total": len(rows), "valid": 0, "warning": 0, "error": 0,
              "new_employees": 0, "updated_employees": 0}
    for r in rows:
        issues: List[dict] = []
        fixes: List[str] = []
        match, m_via, m_conf = None, "", 0
        code = _cell(r.get("employee_code")).lstrip("0") \
            or _cell(r.get("employee_code"))
        if code and code.lower() in emp_by["code"]:
            match, m_via, m_conf = emp_by["code"][code.lower()], "code", 100
        if not match and _digits(r.get("uan_no")):
            match = emp_by["uan"].get(_digits(r.get("uan_no")))
            if match:
                m_via, m_conf = "uan", 98
        if not match and _digits(r.get("esi_ip_no")):
            match = emp_by["esic"].get(_digits(r.get("esi_ip_no")))
            if match:
                m_via, m_conf = "esic", 98
        if not match and _digits(r.get("aadhaar_no")):
            match = emp_by["aadhaar"].get(_digits(r.get("aadhaar_no")))
            if match:
                m_via, m_conf = "aadhaar", 97
        if not match and _cell(r.get("pan_no")):
            match = emp_by["pan"].get(_cell(r.get("pan_no")).upper())
            if match:
                m_via, m_conf = "pan", 96
        if not match and _digits(r.get("phone")):
            match = emp_by["mobile"].get(_digits(r.get("phone"))[-10:])
            if match:
                m_via, m_conf = "mobile", 90
        nm = _norm(r.get("name"))
        if not match and nm:
            u = emp_by["name"].get(nm)
            if u and (not r.get("dob") or _cell(r.get("dob"))
                      == _cell(u.get("dob"))):
                match, m_via, m_conf = u, "name", 85
            elif master_names:
                near = difflib.get_close_matches(nm, master_names, 1, 0.86)
                if near:
                    match = emp_by["name"][near[0]]
                    m_via, m_conf = "fuzzy-name", 75
                    fixes.append(
                        f"Name '{r.get('name')}' ≈ existing employee "
                        f"'{match['name']}' — verify before import")

        # ---------- validations ----------
        def add(sev, msg):
            issues.append({"severity": sev, "msg": msg})

        if not nm and not code:
            add("error", "Row has no employee name or code")
        for f, label, ln in (("uan_no", "UAN", (12,)),
                             ("esi_ip_no", "ESIC number", (10, 17)),
                             ("aadhaar_no", "Aadhaar", (12,))):
            d = _digits(r.get(f))
            if d and len(d) not in ln:
                add("error", f"Invalid {label} '{r.get(f)}' "
                    f"(needs {'/'.join(map(str, ln))} digits)")
        if _cell(r.get("pan_no")) and not re.fullmatch(
                r"[A-Z]{5}\d{4}[A-Z]", _cell(r.get("pan_no")).upper()):
            add("error", f"Invalid PAN format '{r.get('pan_no')}'")
        if _cell(r.get("bank_ifsc")) and not re.fullmatch(
                r"[A-Z]{4}0[A-Z0-9]{6}",
                _cell(r.get("bank_ifsc")).upper()):
            add("error", f"Invalid IFSC '{r.get('bank_ifsc')}'")
        if _cell(r.get("bank_account")) and not re.fullmatch(
                r"\d{6,20}", _digits(r.get("bank_account"))):
            add("warning", "Bank account number looks invalid")
        for f, label in (("gross_earning", "Gross"),
                         ("net_salary", "Net salary"),
                         ("ot_hours", "OT hours"),
                         ("present_days", "Present days")):
            if float(r.get(f) or 0) < 0:
                add("error", f"Negative {label}")
        if float(r.get("present_days") or 0) > cal_days:
            add("error", f"Present days {r.get('present_days')} exceed "
                f"calendar days ({cal_days})")
        for f in dup_track:
            v = _cell(r.get(f))
            if v and dup_track[f][v] > 1:
                sev = "warning" if f == "bank_account" else "error"
                add(sev, f"Duplicate {f.replace('_', ' ')} '{v}' appears "
                    f"{dup_track[f][v]}× in this file")
        gross = float(r.get("gross_earning") or 0)
        days = float(r.get("present_days") or 0)
        if min_wage and days > 0 and gross > 0 \
                and gross / days < min_wage:
            add("warning", f"Daily wage ₹{gross / days:.0f} is below the "
                f"minimum wage ₹{min_wage:.0f}")
        if not _cell(r.get("department")) and not (
                match or {}).get("department"):
            add("warning", "Missing department")
        if not _cell(r.get("designation")) and not (
                match or {}).get("designation"):
            add("warning", "Missing designation")
        # statutory eligibility
        uan = _digits(r.get("uan_no")) or _digits((match or {}).get("uan_no"))
        esic = _digits(r.get("esi_ip_no")) \
            or _digits((match or {}).get("esi_ip_no"))
        if gross and gross <= 15000 and not uan:
            add("warning", "PF-eligible (gross ≤ ₹15,000) but no UAN")
        if gross and gross <= 21000 and not esic:
            add("warning", "ESIC-eligible (gross ≤ ₹21,000) but no ESIC no.")
        if gross > 21000 and float(r.get("esic_employee") or 0) > 0:
            add("warning", "ESIC deducted but gross exceeds ₹21,000 "
                "threshold")

        # ---------- AI correction engine ----------
        if match:
            if not _digits(r.get("uan_no")) and match.get("uan_no"):
                fixes.append(f"Missing UAN → use {match['uan_no']} "
                             "from Employee Master")
            if not _digits(r.get("esi_ip_no")) and match.get("esi_ip_no"):
                fixes.append(f"Missing ESIC no → use {match['esi_ip_no']} "
                             "from Employee Master")
            if not _cell(r.get("bank_ifsc")) and match.get("bank_ifsc"):
                fixes.append(f"Missing IFSC → use {match['bank_ifsc']} "
                             "from Employee Master")
            pg = prev_gross.get(_cell(match.get("employee_code")))
            if pg and gross and abs(gross - pg) / max(pg, 1) > 0.5:
                fixes.append(f"Gross ₹{gross:.0f} differs >50% from last "
                             f"month ₹{pg:.0f} — verify")
        elif nm or code:
            fixes.append("No portal match — will be created as a NEW "
                         "employee if enabled")

        sev = ("error" if any(i["severity"] == "error" for i in issues)
               else "warning" if issues or fixes else "valid")
        counts[sev if sev != "valid" else "valid"] += 1
        if match:
            counts["updated_employees"] += 1
        else:
            counts["new_employees"] += 1
        out_rows.append({
            **r, "_status": sev, "_issues": issues, "_fixes": fixes,
            "_match": ({"user_id": match["user_id"],
                        "name": match.get("name"),
                        "employee_code": match.get("employee_code"),
                        "via": m_via, "confidence": m_conf}
                       if match else None)})

    # persist validated rows + job meta
    await db.ai_import_rows.delete_many({"job_id": job_id})
    for c0 in range(0, len(out_rows), CHUNK):
        await db.ai_import_rows.insert_one(
            {"job_id": job_id, "chunk": c0 // CHUNK,
             "rows": out_rows[c0:c0 + CHUNK]})
    await db.ai_import_jobs.update_one({"job_id": job_id}, {"$set": {
        "status": "validated", "company_id": cid, "month": month,
        "file_type": file_type, "final_mapping": mapping,
        "summary": counts, "validated_at": _now()}})
    await _audit(admin, job_id, "validate",
                 f"{counts['valid']} valid / {counts['warning']} warning / "
                 f"{counts['error']} error")
    return {"job_id": job_id, "summary": counts,
            "rows": out_rows[:400],
            "truncated": len(out_rows) > 400}


# ---------------------------------------------------------------------------
# STEP 9-11: COMMIT (background) + auto payroll
# ---------------------------------------------------------------------------
async def _commit_job(job_id: str, admin: dict, targets: List[str],
                      create_new: bool, auto_payroll: bool):
    job = await db.ai_import_jobs.find_one({"job_id": job_id}, {"_id": 0})
    cid, month = job["company_id"], job["month"]
    rows = await _load_rows(job_id)
    usable = [r for r in rows if r.get("_status") != "error"]
    res = {"employees_created": 0, "employees_updated": 0,
           "entries_written": 0, "leaves_written": 0, "extras_written": 0,
           "skipped_errors": len(rows) - len(usable)}

    async def prog(pct, note):
        await db.ai_import_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"progress": pct, "progress_note": note}})

    try:
        await prog(5, "Starting import…")
        # -- Employee Master --
        emp_field_keys = ["name", "father_name", "uan_no", "pf_no",
                          "esi_ip_no", "aadhaar_no", "pan_no", "phone",
                          "dob", "doj", "department", "designation",
                          "gender", "bank_account", "bank_ifsc",
                          "bank_name", "employee_type"]
        if "employee_master" in targets:
            n = 0
            for r in usable:
                n += 1
                if n % 500 == 0:
                    await prog(5 + int(25 * n / max(len(usable), 1)),
                               f"Employee Master… {n}/{len(usable)}")
                upd = {k: r[k] for k in emp_field_keys
                       if _cell(r.get(k))}
                if r.get("salary_monthly"):
                    upd["salary_monthly"] = float(r["salary_monthly"])
                    upd["compliance_salary_mode"] = "monthly"
                elif r.get("rate_daily"):
                    upd["salary_daily"] = float(r["rate_daily"])
                if r.get("_match"):
                    if upd:
                        upd["last_corrected_at"] = _now()
                        upd["last_corrected_by"] = admin["user_id"]
                        await db.users.update_one(
                            {"user_id": r["_match"]["user_id"]},
                            {"$set": upd})
                        res["employees_updated"] += 1
                elif create_new and (upd.get("name")
                                     or r.get("employee_code")):
                    code = _cell(r.get("employee_code"))
                    if not code:
                        mx = 0
                        async for u in db.users.find(
                                {"company_id": cid, "role": "employee"},
                                {"_id": 0, "employee_code": 1}):
                            try:
                                mx = max(mx, int(
                                    _digits(u.get("employee_code"))))
                            except ValueError:
                                pass
                        code = str(mx + 1)
                    doc = {"user_id": f"user_{uuid.uuid4().hex[:12]}",
                           "role": "employee", "company_id": cid,
                           "employee_code": code, "active": True,
                           "is_onroll": True, "onboarded": False,
                           "approval_status": "approved",
                           "created_at": _now(),
                           "imported_from": "ai_universal_import",
                           **upd}
                    await db.users.insert_one(doc)
                    r["_match"] = {"user_id": doc["user_id"],
                                   "employee_code": code,
                                   "name": doc.get("name"),
                                   "via": "created", "confidence": 100}
                    res["employees_created"] += 1
        await prog(35, "Employee Master done")

        # -- Attendance / Salary / OT → compliance_import_entries --
        if "attendance_salary" in targets:
            entries = []
            for r in usable:
                mt = r.get("_match")
                if not mt:
                    continue
                entries.append({
                    "company_id": cid, "month": month,
                    "user_id": mt["user_id"],
                    "present_days": float(r.get("present_days") or 0),
                    "deduction_head": _cell(r.get("deduction_head")),
                    "deduction_amount": float(
                        r.get("deduction_amount") or 0),
                    "gross_earning": float(r.get("gross_earning") or 0),
                    "tds": float(r.get("tds") or 0),
                    "other_less": 0.0,
                    "ot_hours": float(r.get("ot_hours") or 0),
                    "source": "ai_universal_import",
                    "filename": job.get("filename"),
                    "imported_at": _now(),
                    "imported_by": admin["user_id"]})
            if entries:
                await db.compliance_import_entries.delete_many(
                    {"company_id": cid, "month": month})
                await db.compliance_import_entries.insert_many(entries)
                res["entries_written"] = len(entries)
        await prog(55, "Attendance/Salary entries written")

        # -- Leave --
        if "leave" in targets:
            for r in usable:
                mt = r.get("_match")
                if not mt or not (r.get("leave_days")
                                  or r.get("leave_from")):
                    continue
                await db.leaves.insert_one({
                    "leave_id": f"lv_{uuid.uuid4().hex[:10]}",
                    "company_id": cid, "user_id": mt["user_id"],
                    "employee_code": mt.get("employee_code"),
                    "name": mt.get("name"),
                    "leave_type": _cell(r.get("leave_type")) or "EL",
                    "from_date": _cell(r.get("leave_from")) or None,
                    "to_date": _cell(r.get("leave_to")) or None,
                    "days": float(r.get("leave_days") or 0),
                    "month": month, "status": "approved",
                    "source": "ai_universal_import",
                    "created_at": _now(),
                    "created_by": admin["user_id"]})
                res["leaves_written"] += 1
        # -- Bonus / Arrear / Increment extras --
        if "extras" in targets:
            for r in usable:
                mt = r.get("_match")
                kinds = [("bonus", r.get("bonus_amount")),
                         ("arrear", r.get("arrear_amount")),
                         ("increment", r.get("increment_amount"))]
                for kind, amt in kinds:
                    if not mt or not amt:
                        continue
                    await db.ai_imported_extras.insert_one({
                        "extra_id": f"aix_{uuid.uuid4().hex[:10]}",
                        "kind": kind, "company_id": cid, "month": month,
                        "user_id": mt["user_id"],
                        "employee_code": mt.get("employee_code"),
                        "name": mt.get("name"), "amount": float(amt),
                        "source_job": job_id, "created_at": _now()})
                    res["extras_written"] += 1
        await prog(70, "Module imports done")

        # -- SMART LEARNING: remember template --
        analysis = job.get("analysis") or {}
        comp = await db.companies.find_one(
            {"company_id": cid}, {"_id": 0, "name": 1})
        await db.ai_universal_templates.update_one(
            {"fingerprint": analysis.get("fingerprint")},
            {"$set": {"fingerprint": analysis.get("fingerprint"),
                      "mapping": job.get("final_mapping") or {},
                      "file_type": job.get("file_type"),
                      "company_id": cid,
                      "company_name": (comp or {}).get("name"),
                      "filename": job.get("filename"),
                      "updated_at": _now()},
             "$inc": {"uses": 1}}, upsert=True)

        # -- STEP 11: AUTO PAYROLL PROCESS --
        payroll = None
        if auto_payroll and res["entries_written"]:
            await prog(80, "Processing payroll (PF/ESIC/PT/TDS)…")
            try:
                from server import (_create_compliance_salary_run_core,
                                    ComplianceSalaryRunCreate)
                resp = await _create_compliance_salary_run_core(
                    ComplianceSalaryRunCreate(
                        month=month, company_id=cid,
                        use_imported_sheet=True), admin)
                run = resp.get("run") or {}
                payroll = {"ok": True, "run_id": run.get("run_id"),
                           "employees": run.get("employees_count"),
                           "totals": run.get("totals")}
            except HTTPException as ex:
                payroll = {"ok": False, "error": str(ex.detail)}
            except Exception as ex:  # noqa: BLE001
                payroll = {"ok": False, "error": str(ex)[:300]}
        await db.ai_import_jobs.update_one({"job_id": job_id}, {"$set": {
            "status": "imported", "progress": 100,
            "progress_note": "Done", "result": res,
            "payroll": payroll, "imported_at": _now()}})
        await _audit(admin, job_id, "commit",
                     json.dumps(res)[:300])
        # SECURITY — temp parsed rows removed after successful processing
        await db.ai_import_rows.delete_many({"job_id": job_id})
    except Exception as e:  # noqa: BLE001
        logger.exception("[ai-import] commit failed")
        await db.ai_import_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "failed", "error": str(e)[:400]}})


@router.post("/commit")
async def commit(body: dict = Body(...),
                 authorization: Optional[str] = Header(None)):
    admin, _cid = await _adm(authorization)
    job_id = body.get("job_id")
    job = await db.ai_import_jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") == "imported":
        raise HTTPException(status_code=409,
                            detail="This job was already imported "
                                   "(no duplicate imports)")
    if job.get("status") not in ("validated", "failed"):
        raise HTTPException(status_code=400,
                            detail="Run validation first")
    targets = body.get("targets") or ["employee_master", "attendance_salary"]
    await db.ai_import_jobs.update_one(
        {"job_id": job_id},
        {"$set": {"status": "importing", "progress": 1,
                  "progress_note": "Queued…", "targets": targets}})
    asyncio.create_task(_commit_job(
        job_id, admin, targets,
        bool(body.get("create_new_employees", True)),
        bool(body.get("auto_payroll", True))))
    return {"ok": True, "job_id": job_id, "status": "importing"}


@router.get("/job/{job_id}")
async def job_status(job_id: str,
                     authorization: Optional[str] = Header(None)):
    await _adm(authorization)
    job = await db.ai_import_jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ---------------------------------------------------------------------------
# STEP 12-13: COMPLIANCE CHECK + artifact links
# ---------------------------------------------------------------------------
@router.get("/compliance-check")
async def compliance_check(company_id: str, month: str,
                           authorization: Optional[str] = Header(None)):
    _admin, cid = await _adm(authorization, company_id)
    run = await db.compliance_salary_runs.find_one(
        {"company_id": cid or company_id, "month": month}, {"_id": 0},
        sort=[("generated_at", -1)])
    if not run:
        return {"run": None, "issues": [],
                "note": "No compliance salary run for this month yet."}
    issues: List[dict] = []
    for r in run.get("rows") or []:
        nm = f"{r.get('employee_code')} {r.get('name')}"
        if float(r.get("pf_employee") or 0) > 0:
            u = await db.users.find_one(
                {"user_id": r.get("user_id")}, {"_id": 0, "uan_no": 1})
            if not _digits((u or {}).get("uan_no")):
                issues.append({"severity": "error",
                               "msg": f"{nm}: PF deducted but UAN missing "
                                      "— ECR will reject"})
        if float(r.get("esic_employee") or 0) > 0:
            u = await db.users.find_one(
                {"user_id": r.get("user_id")}, {"_id": 0, "esi_ip_no": 1})
            if not _digits((u or {}).get("esi_ip_no")):
                issues.append({"severity": "error",
                               "msg": f"{nm}: ESIC deducted but IP number "
                                      "missing"})
        pfw = float(r.get("pf_wages") or 0)
        if float(r.get("pf_employee") or 0) > 0 and pfw > 15000:
            issues.append({"severity": "warning",
                           "msg": f"{nm}: PF wages ₹{pfw:.0f} above the "
                                  "₹15,000 cap — verify VPF intent"})
        gp = float(r.get("gross_paid") or 0)
        if float(r.get("esic_employee") or 0) > 0 and gp > 21000:
            issues.append({"severity": "warning",
                           "msg": f"{nm}: ESIC deducted on gross "
                                  f"₹{gp:.0f} > ₹21,000"})
        if float(r.get("net") or 0) < 0:
            issues.append({"severity": "error",
                           "msg": f"{nm}: NEGATIVE net salary"})
    rid = run.get("run_id")
    return {
        "run": {"run_id": rid, "month": run.get("month"),
                "employees": run.get("employees_count"),
                "totals": run.get("totals"),
                "finalized": run.get("finalized")},
        "issues": issues[:100], "issue_count": len(issues),
        "artifacts": [
            {"label": "PF ECR TXT", "kind": "download",
             "path": f"/admin/compliance-salary-runs/{rid}/pf-ecr.txt"},
            {"label": "Generate Payslips", "kind": "action",
             "path": f"/admin/compliance-salary-runs/{rid}"
                     "/generate-payslips"},
            {"label": "Salary Register", "kind": "screen",
             "path": "/salary-register"},
            {"label": "PF / ESIC Challans", "kind": "screen",
             "path": "/challans"},
            {"label": "Bank Transfer File", "kind": "screen",
             "path": "/bank-transfer"},
            {"label": "Compliance Report", "kind": "screen",
             "path": "/reports?tab=compliance"},
        ]}


# ---------------------------------------------------------------------------
# STEP 14: DASHBOARD · templates · AI explain
# ---------------------------------------------------------------------------
@router.get("/dashboard")
async def dashboard(authorization: Optional[str] = Header(None)):
    _admin, cid = await _adm(authorization)
    q: Dict[str, Any] = {}
    if cid:
        q["company_id"] = cid
    jobs = await db.ai_import_jobs.find(
        q, {"_id": 0, "analysis": 0}).sort(
        "created_at", -1).to_list(200)
    total = len(jobs)
    done = sum(1 for j in jobs if j.get("status") == "imported")
    created = sum((j.get("result") or {}).get("employees_created", 0)
                  for j in jobs)
    updated = sum((j.get("result") or {}).get("employees_updated", 0)
                  for j in jobs)
    payroll_ok = sum(1 for j in jobs
                     if (j.get("payroll") or {}).get("ok"))
    errors = sum((j.get("summary") or {}).get("error", 0) for j in jobs)
    tpl_count = await db.ai_universal_templates.count_documents({})
    return {"total_jobs": total, "imported_jobs": done,
            "success_rate": round(done * 100 / total) if total else 0,
            "employees_added": created, "employees_updated": updated,
            "payroll_runs": payroll_ok, "validation_errors": errors,
            "templates_learned": tpl_count,
            "recent_jobs": jobs[:25]}


@router.get("/templates")
async def templates(authorization: Optional[str] = Header(None)):
    await _adm(authorization)
    rows = await db.ai_universal_templates.find(
        {}, {"_id": 0}).sort("updated_at", -1).to_list(100)
    return {"templates": rows}


@router.delete("/templates/{fingerprint}")
async def template_delete(fingerprint: str,
                          authorization: Optional[str] = Header(None)):
    await _adm(authorization)
    await db.ai_universal_templates.delete_one({"fingerprint": fingerprint})
    return {"ok": True}


@router.post("/explain")
async def explain(body: dict = Body(...),
                  authorization: Optional[str] = Header(None)):
    """AI assistant — explain validation issues in plain English."""
    await _adm(authorization)
    q = (body.get("question") or "").strip()
    issues = body.get("issues") or []
    if not q and not issues:
        raise HTTPException(status_code=400,
                            detail="question or issues required")
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail="AI key not configured")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"ai-explain-{uuid.uuid4().hex[:8]}",
            system_message=(
                "You are a friendly Indian payroll compliance expert inside "
                "an HR portal. Explain validation errors in simple plain "
                "English, tell the user exactly HOW to fix each one (PF/EPFO"
                ", ESIC, minimum wages, bank formats). Be concise — short "
                "bullet points, no markdown headers."),
        ).with_model("openai", "gpt-5.4")
        text = q or ("Explain these payroll import issues and how to fix "
                     "them:\n" + "\n".join(
                         f"- {i.get('msg', i)}" if isinstance(i, dict)
                         else f"- {i}" for i in issues[:25]))
        resp = await chat.send_message(UserMessage(text=text))
        return {"answer": str(resp)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"AI failed: {e}")
