"""Iter 101 — Compliance Salary sheet import (replaces the Attendance
Master link).

The Compliance Salary Process no longer reads the Masters → Attendance
Master screen. Instead the admin imports a salary sheet — SAME columns
as the Attendance Master format (PF No / UAN / ESIC No / Emp ID / Name /
Present Days / Deduction Head / Deduction Amount / Gross Earning) — from
either:
  * a manually uploaded Excel/CSV file, or
  * an Excel/CSV attachment picked from the Super Admin Gmail mailbox.

Imported rows persist in ``compliance_import_entries`` keyed by
(company_id, month, user_id) and are consumed by the compliance salary
run when ``use_imported_sheet`` is set.

Endpoints:
  * GET  /admin/compliance-import/status?company_id&month
  * POST /admin/compliance-import/upload      {company_id, month, filename, content_base64}
  * GET  /gmail/spreadsheet-attachments        (super_admin, Gmail connected)
  * POST /admin/compliance-import/from-gmail  {company_id, month, message_id, attachment_id, filename}
"""
import base64
import io
import re
from typing import Optional

import httpx
import pandas as pd
from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
)
from routes.gmail_mailbox import _access_token, _hdr, GMAIL_API  # noqa: E402

router = APIRouter(prefix="/api", tags=["compliance-import"])


# ---------------------------------------------------------------------------
# Sheet parsing (Attendance Master column format)
# ---------------------------------------------------------------------------
def _norm_header(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


HEADER_MAP = {
    "code": {"empid", "employeecode", "empcode", "code", "empno", "employeeid", "employeeno"},
    "pf_no": {"pfno", "pfnumber"},
    "uan_no": {"uan", "uanno", "uannumber"},
    "esic_no": {"esicno", "esic", "esiipno", "ipno", "esino", "esicipno"},
    "name": {"name", "employeename", "empname"},
    "present_days": {"presentdays", "present", "presentday", "payabledays", "days", "presentdaysmanual"},
    "deduction_head": {"deductionhead", "otherdeductionhead", "dedhead", "deductionshead"},
    "deduction_amount": {"deductionamount", "advancededuction", "otherdeduction", "dedamount", "advance", "deduction"},
    "gross_earning": {"grossearning", "gross", "grossearnings", "grossearned"},
}


def _to_num(v) -> float:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0.0
        s = str(v).replace(",", "").strip()
        if not s or s.lower() in ("nan", "none", "-"):
            return 0.0
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _cell_str(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    # Excel often stores codes/UANs as floats ("50.0")
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    return s


def _parse_sheet(content: bytes, filename: str) -> list:
    """Parse xls/xlsx/csv bytes → list of normalized row dicts."""
    name = (filename or "").lower()
    try:
        if name.endswith(".csv"):
            raw = pd.read_csv(io.BytesIO(content), header=None, dtype=object)
        elif name.endswith(".xls"):
            raw = pd.read_excel(io.BytesIO(content), header=None, dtype=object, engine="xlrd")
        else:
            raw = pd.read_excel(io.BytesIO(content), header=None, dtype=object, engine="openpyxl")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read the file: {e}")

    # Locate the header row: first row (within the top 12) that matches
    # at least 2 known column headers.
    header_row = None
    col_idx: dict = {}
    for i in range(min(12, len(raw))):
        cells = [_norm_header(c) for c in raw.iloc[i].tolist()]
        found: dict = {}
        for j, cell in enumerate(cells):
            if not cell:
                continue
            for field, aliases in HEADER_MAP.items():
                if field not in found and cell in aliases:
                    found[field] = j
        if len(found) >= 2:
            header_row = i
            col_idx = found
            break
    if header_row is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not find the header row. The sheet must use the "
                "Attendance Master format (PF No, UAN, ESIC No, Emp ID, Name, "
                "Present Days, Deduction Head, Deduction Amount, Gross Earning)."
            ),
        )

    rows = []
    for i in range(header_row + 1, len(raw)):
        r = raw.iloc[i]
        row = {}
        for field, j in col_idx.items():
            v = r.iloc[j] if j < len(r) else None
            if field in ("present_days", "deduction_amount", "gross_earning"):
                row[field] = _to_num(v)
            else:
                row[field] = _cell_str(v)
        # Skip fully empty / total rows
        if not any([row.get("code"), row.get("uan_no"), row.get("pf_no"),
                    row.get("esic_no"), row.get("name")]):
            continue
        if _norm_header(row.get("name")).startswith("total"):
            continue
        row["_row_no"] = i + 1
        rows.append(row)
    return rows


async def _store_import(admin: dict, company_id: str, month: str,
                        rows: list, source: str, filename: str) -> dict:
    """Match parsed rows to the firm's employees and persist them."""
    if not company_id or not month:
        raise HTTPException(status_code=400, detail="company_id and month are required")
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "name": 1})
    if not company:
        raise HTTPException(status_code=404, detail="Firm not found")

    by_code: dict = {}
    by_uan: dict = {}
    by_pf: dict = {}
    by_esic: dict = {}
    by_name: dict = {}
    async for u in db.users.find(
        {"role": "employee", "company_id": company_id},
        {"_id": 0, "user_id": 1, "employee_code": 1, "uan_no": 1,
         "pf_no": 1, "esi_ip_no": 1, "name": 1},
    ):
        code = _cell_str(u.get("employee_code")).lstrip("0") or _cell_str(u.get("employee_code"))
        if code:
            by_code[code.lower()] = u["user_id"]
        if u.get("uan_no"):
            by_uan[re.sub(r"\D", "", str(u["uan_no"]))] = u["user_id"]
        if u.get("pf_no"):
            by_pf[_norm_header(u["pf_no"])] = u["user_id"]
        if u.get("esi_ip_no"):
            by_esic[re.sub(r"\D", "", str(u["esi_ip_no"]))] = u["user_id"]
        if u.get("name"):
            by_name[str(u["name"]).strip().lower()] = u["user_id"]

    matched = []
    unmatched = []
    seen: set = set()
    for row in rows:
        uid = None
        code = _cell_str(row.get("code")).lstrip("0") or _cell_str(row.get("code"))
        if code:
            uid = by_code.get(code.lower())
        if not uid and row.get("uan_no"):
            uid = by_uan.get(re.sub(r"\D", "", row["uan_no"]))
        if not uid and row.get("pf_no"):
            uid = by_pf.get(_norm_header(row["pf_no"]))
        if not uid and row.get("esic_no"):
            uid = by_esic.get(re.sub(r"\D", "", row["esic_no"]))
        if not uid and row.get("name"):
            uid = by_name.get(row["name"].strip().lower())
        if not uid:
            unmatched.append({
                "row": row.get("_row_no"),
                "code": row.get("code"),
                "name": row.get("name"),
                "reason": "No matching employee in this firm",
            })
            continue
        if uid in seen:
            continue
        seen.add(uid)
        matched.append({
            "company_id": company_id,
            "month": month,
            "user_id": uid,
            "present_days": float(row.get("present_days") or 0),
            "deduction_head": row.get("deduction_head") or "",
            "deduction_amount": float(row.get("deduction_amount") or 0),
            "gross_earning": float(row.get("gross_earning") or 0),
        })

    # Replace the whole (firm, month) set on every import.
    await db.compliance_import_entries.delete_many({"company_id": company_id, "month": month})
    if matched:
        stamp = {"source": source, "filename": filename,
                 "imported_at": now_iso(), "imported_by": admin["user_id"]}
        for m in matched:
            m.update(stamp)
        await db.compliance_import_entries.insert_many(matched)

    return {
        "ok": True,
        "company_name": company.get("name"),
        "total_rows": len(rows),
        "matched": len(matched),
        "unmatched": unmatched[:50],
        "unmatched_count": len(unmatched),
        "source": source,
        "filename": filename,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/admin/compliance-import/status")
async def compliance_import_status(
    company_id: str = Query(...),
    month: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    count = await db.compliance_import_entries.count_documents(
        {"company_id": company_id, "month": month})
    latest = await db.compliance_import_entries.find_one(
        {"company_id": company_id, "month": month},
        {"_id": 0, "source": 1, "filename": 1, "imported_at": 1},
        sort=[("imported_at", -1)],
    )
    return {
        "count": count,
        "source": (latest or {}).get("source"),
        "filename": (latest or {}).get("filename"),
        "imported_at": (latest or {}).get("imported_at"),
    }


@router.post("/admin/compliance-import/upload")
async def compliance_import_upload(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    company_id = payload.get("company_id")
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    month = payload.get("month")
    filename = payload.get("filename") or "sheet.xlsx"
    b64 = payload.get("content_base64") or ""
    if not b64:
        raise HTTPException(status_code=400, detail="content_base64 is required")
    try:
        content = base64.b64decode(b64)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid base64 content")
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 8 MB)")
    rows = _parse_sheet(content, filename)
    return await _store_import(admin, company_id, month, rows, "file", filename)


@router.get("/gmail/spreadsheet-attachments")
async def gmail_spreadsheet_attachments(authorization: Optional[str] = Header(None)):
    """Recent Gmail messages that carry an Excel/CSV attachment."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin"])
    token = await _access_token(user["user_id"])
    q = "has:attachment (filename:xls OR filename:xlsx OR filename:csv)"
    async with httpx.AsyncClient(timeout=30) as cx:
        r = await cx.get(f"{GMAIL_API}/messages",
                         params={"q": q, "maxResults": 15},
                         headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Gmail search failed: {r.text[:200]}")
        ids = [m["id"] for m in (r.json().get("messages") or [])]
        out = []
        for mid in ids:
            d = await cx.get(f"{GMAIL_API}/messages/{mid}",
                             params={"format": "full"},
                             headers={"Authorization": f"Bearer {token}"})
            if d.status_code != 200:
                continue
            m = d.json()
            hs = (m.get("payload") or {}).get("headers") or []
            atts = []

            def walk(p):
                fn = (p.get("filename") or "").strip()
                body = p.get("body") or {}
                if fn and body.get("attachmentId") and \
                        fn.lower().endswith((".xls", ".xlsx", ".csv")):
                    atts.append({
                        "attachment_id": body["attachmentId"],
                        "filename": fn,
                        "size": body.get("size"),
                    })
                for part in p.get("parts") or []:
                    walk(part)

            walk(m.get("payload") or {})
            if atts:
                out.append({
                    "message_id": mid,
                    "subject": _hdr(hs, "Subject"),
                    "from": _hdr(hs, "From"),
                    "date": _hdr(hs, "Date"),
                    "attachments": atts,
                })
    return {"messages": out}


@router.post("/admin/compliance-import/from-gmail")
async def compliance_import_from_gmail(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    company_id = payload.get("company_id")
    month = payload.get("month")
    message_id = payload.get("message_id")
    attachment_id = payload.get("attachment_id")
    filename = payload.get("filename") or "sheet.xlsx"
    if not message_id or not attachment_id:
        raise HTTPException(status_code=400, detail="message_id and attachment_id are required")
    token = await _access_token(admin["user_id"])
    async with httpx.AsyncClient(timeout=30) as cx:
        r = await cx.get(
            f"{GMAIL_API}/messages/{message_id}/attachments/{attachment_id}",
            headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Gmail attachment fetch failed: {r.text[:200]}")
    data = r.json().get("data") or ""
    try:
        content = base64.urlsafe_b64decode(data + "==")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Could not decode the attachment")
    rows = _parse_sheet(content, filename)
    return await _store_import(admin, company_id, month, rows, "email", filename)
