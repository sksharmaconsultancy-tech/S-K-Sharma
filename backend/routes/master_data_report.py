"""Iter 91 — Route module: Master Data report (read-only).

Sidebar → Reports → Master Data. Three views over the EMPLOYEE master:

  * ``active`` — working right now (no exit/resign date on the master)
  * ``left``   — resign/exit date already set on the master
  * ``all``    — everything

Data is strictly READ-ONLY here (no edit endpoints) and can be exported
to Excel. Filters: free-text name/code search, Employee Type / Group,
firm (super admin), on-roll flag.

  GET /api/admin/reports/master-data?status=active|left|all&q=&employee_type=&company_id=&is_onroll=
  GET /api/admin/reports/master-data.xlsx?...same params...
"""
from io import BytesIO
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
)

router = APIRouter(prefix="/api/admin/reports", tags=["master-data-report"])

_COLUMNS = [
    ("employee_code", "Emp Code"),
    ("name", "Name"),
    ("father_name", "Father / Spouse Name"),
    ("gender", "Gender"),
    ("blood_group", "Blood Group"),
    ("marital_status", "Marital Status"),
    ("phone", "Phone"),
    ("designation", "Designation"),
    ("department", "Department"),
    ("employee_type", "Type / Group"),
    ("is_onroll", "On-roll"),
    ("doj", "DOJ"),
    ("exit_date", "Exit / Resign Date"),
    ("salary_monthly", "Monthly Gross"),
    ("uan_no", "UAN"),
    ("esi_ip_no", "ESIC IP"),
    ("pan_no", "PAN"),
    ("pan_name", "Name As Per PAN"),
    ("aadhaar_no", "Aadhaar"),
    ("bank_name", "Bank"),
    ("bank_account", "Account No"),
    ("bank_ifsc", "IFSC"),
    ("upi_id", "UPI ID"),
    ("address", "Address"),
    ("company_name", "Firm"),
]


async def _fetch_rows(
    admin: Dict[str, Any],
    status: str,
    q: Optional[str],
    employee_type: Optional[str],
    company_id: Optional[str],
    is_onroll: Optional[str],
) -> list:
    query: Dict[str, Any] = {"role": "employee"}
    if admin["role"] == "company_admin":
        query["company_id"] = admin.get("company_id")
    elif company_id:
        query["company_id"] = company_id

    if status == "active":
        query["$or"] = [{"exit_date": {"$in": [None, ""]}},
                        {"exit_date": {"$exists": False}}]
    elif status == "left":
        query["exit_date"] = {"$nin": [None, ""]}

    if employee_type:
        query["employee_type"] = employee_type
    if is_onroll in ("true", "false"):
        query["is_onroll"] = is_onroll == "true"
    if q:
        import re as _re
        rx = {"$regex": _re.escape(q.strip()), "$options": "i"}
        query["$and"] = [{"$or": [
            {"name": rx}, {"employee_code": rx}, {"phone": rx},
        ]}]

    users = await db.users.find(query, {"_id": 0}).sort("name", 1).to_list(5000)

    # Firm names for display
    cids = {u.get("company_id") for u in users if u.get("company_id")}
    names: Dict[str, str] = {}
    if cids:
        async for c in db.companies.find(
            {"company_id": {"$in": list(cids)}}, {"_id": 0, "company_id": 1, "name": 1},
        ):
            names[c["company_id"]] = c.get("name") or c["company_id"]

    rows = []
    from utils.relation import father_or_spouse_display
    for u in users:
        rows.append({
            **{k: u.get(k) for k, _ in _COLUMNS if k != "company_name"},
            # User directive — Female+Unmarried shows "D/O father", Female+
            # Married shows spouse name only.
            "father_name": father_or_spouse_display(u),
            "aadhaar_no": u.get("aadhaar_no") or u.get("aadhar_number"),
            "pan_no": u.get("pan_no") or u.get("pan_number"),
            "company_name": names.get(u.get("company_id") or "", u.get("company_id")),
            "user_id": u.get("user_id"),
        })
    return rows


def _parse_common(status: str) -> str:
    s = (status or "all").lower()
    if s not in ("active", "left", "all"):
        raise HTTPException(status_code=400, detail="status must be active | left | all")
    return s


@router.get("/master-data")
async def master_data_report(
    status: str = "all",
    q: Optional[str] = None,
    employee_type: Optional[str] = None,
    company_id: Optional[str] = None,
    is_onroll: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    s = _parse_common(status)
    rows = await _fetch_rows(admin, s, q, employee_type, company_id, is_onroll)
    return {
        "status": s,
        "count": len(rows),
        "columns": [{"key": k, "label": lbl} for k, lbl in _COLUMNS],
        "rows": rows,
    }


def _build_xlsx(rows: list, s: str) -> BytesIO:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = {"active": "Active Employees", "left": "Left Employees", "all": "All Employees"}[s]

    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="1E3A8A")
    for ci, (_, lbl) in enumerate(_COLUMNS, start=1):
        cell = ws.cell(row=1, column=ci, value=lbl)
        cell.font = hdr_font
        cell.fill = hdr_fill
    for ri, r in enumerate(rows, start=2):
        for ci, (k, _) in enumerate(_COLUMNS, start=1):
            v = r.get(k)
            if k == "is_onroll":
                v = "On-roll" if v is not False else "Off-roll"
            ws.cell(row=ri, column=ci, value=v if v is not None else "")
    for ci in range(1, len(_COLUMNS) + 1):
        ws.column_dimensions[ws.cell(row=1, column=ci).column_letter].width = 16

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


@router.get("/master-data.xlsx")
async def master_data_report_xlsx(
    status: str = "all",
    q: Optional[str] = None,
    employee_type: Optional[str] = None,
    company_id: Optional[str] = None,
    is_onroll: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    s = _parse_common(status)
    rows = await _fetch_rows(admin, s, q, employee_type, company_id, is_onroll)
    buf = _build_xlsx(rows, s)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="MasterData_{s}.xlsx"'},
    )


# ---------------------------------------------------------------------------
# Iter 92 — Monthly Master-Data e-mail (Resend)
# ---------------------------------------------------------------------------

async def _email_master_data_for_firm(company_id: str, month_label: str) -> dict:
    """Build the ALL-employees master xlsx for one firm and email it to
    the firm's company-admin emails (fallback RESEND_TO_EMAIL)."""
    import base64
    import os

    from utils.iter60_features import _send_email_with_attachment

    fake_admin = {"role": "super_admin"}
    rows = await _fetch_rows(fake_admin, "all", None, None, company_id, None)
    if not rows:
        return {"delivered": False, "error": "no_employees"}
    buf = _build_xlsx(rows, "all")

    admins = await db.users.find(
        {"role": "company_admin", "company_id": company_id, "email": {"$nin": [None, ""]}},
        {"_id": 0, "email": 1},
    ).to_list(20)
    emails = [a["email"] for a in admins if a.get("email")]
    fallback = os.getenv("RESEND_TO_EMAIL", "").strip()
    if not emails and fallback:
        emails = [fallback]
    if not emails:
        return {"delivered": False, "error": "no_recipient"}

    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "name": 1})
    firm = (company or {}).get("name") or company_id
    return await _send_email_with_attachment(
        to_emails=emails,
        subject=f"Monthly Master Data — {firm} — {month_label}",
        text_body=(
            f"Attached is the monthly Employee Master Data report for {firm} "
            f"({month_label}). {len(rows)} employee record(s). "
            "This is an automated read-only export."
        ),
        attachments=[{
            "filename": f"MasterData_{firm.replace(' ', '_')}_{month_label}.xlsx",
            "content": base64.b64encode(buf.getvalue()).decode(),
        }],
    )


@router.post("/master-data/email")
async def email_master_data_now(
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Send the Master Data Excel to the firm's admins right now."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin"])
    cid = admin.get("company_id") if admin["role"] == "company_admin" else company_id
    if not cid:
        raise HTTPException(status_code=400, detail="company_id is required")
    from datetime import datetime
    r = await _email_master_data_for_firm(cid, datetime.utcnow().strftime("%Y-%m"))
    if not r.get("delivered"):
        raise HTTPException(status_code=502, detail=f"Email failed: {r.get('error')}")
    return {"ok": True, **r}


async def monthly_master_data_email_loop():
    """Background task — on the 1st of every month, email each active
    firm's admins the Employee Master Data Excel. Idempotent via a
    system_flags marker per month."""
    import asyncio
    import logging
    from datetime import datetime

    log = logging.getLogger("master-data-email")
    while True:
        try:
            now = datetime.utcnow()
            month_label = now.strftime("%Y-%m")
            if now.day == 1:
                flag = await db.system_flags.find_one(
                    {"key": "master_data_email", "month": month_label},
                )
                if not flag:
                    firms = await db.companies.find({}, {"_id": 0, "company_id": 1}).to_list(200)
                    sent = 0
                    for f in firms:
                        try:
                            r = await _email_master_data_for_firm(f["company_id"], month_label)
                            if r.get("delivered"):
                                sent += 1
                        except Exception as exc:  # noqa: BLE001
                            log.warning("master-data email failed for %s: %s", f["company_id"], exc)
                    await db.system_flags.insert_one(
                        {"key": "master_data_email", "month": month_label,
                         "sent": sent, "at": now.isoformat()},
                    )
                    log.info("monthly master-data emails sent: %s firms", sent)
        except Exception as exc:  # noqa: BLE001
            log.warning("master-data email loop error: %s", exc)
        await asyncio.sleep(6 * 3600)  # check 4×/day
