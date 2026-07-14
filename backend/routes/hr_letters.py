"""Iter 95 — HR Letters module.

Generate Appointment / Offer / Warning / Termination letters on the firm's
letterhead, auto-filled from Employee Master + Firm Master, editable before
saving. Every saved letter lands in a per-employee letter register
(``db.hr_letters``) and can be re-downloaded as PDF anytime.

Endpoints:
  * GET    /api/admin/hr-letters/template/{letter_type}   — pre-filled draft
  * POST   /api/admin/hr-letters                          — save a letter
  * GET    /api/admin/hr-letters                          — register / history
  * DELETE /api/admin/hr-letters/{letter_id}              — remove from register
  * GET    /api/admin/hr-letters/{letter_id}/pdf          — letterhead PDF
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    sub_admin_can_touch_company,
    _send_email_with_attachments,
)

router = APIRouter(prefix="/api", tags=["hr-letters"])

LETTER_TYPES = {
    "appointment": "Appointment Letter",
    "offer": "Offer Letter",
    "warning": "Warning Letter",
    "termination": "Termination Letter",
}
ABBR = {"appointment": "APT", "offer": "OFR", "warning": "WRN", "termination": "TRM"}


async def _check_scope(admin: dict, company_id: str) -> None:
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin.get("role") == "sub_admin" and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm not in your scope")
    if admin.get("role") == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="You can only access your own firm")


def _today_dmy() -> str:
    return datetime.now(timezone.utc).strftime("%d-%m-%Y")


def _salary_text(emp: dict) -> str:
    """Resolve pay rate the same way the day-wise salary grid does: the
    Basic row on salary_structure_actual overrides salary_monthly."""
    basic = float(emp.get("salary_monthly") or 0.0)
    mode = str(emp.get("salary_mode") or "monthly").lower()
    for r in (emp.get("salary_structure_actual") or []):
        if isinstance(r, dict) and str(r.get("head", "")).strip().lower().startswith("basic"):
            if float(r.get("amount") or 0.0) > 0:
                basic = float(r.get("amount") or 0.0)
                rt = str(r.get("rate_type") or "").strip().lower()
                if rt in ("monthly", "daily", "hourly"):
                    mode = rt
            break
    if basic <= 0:
        return "[SALARY AMOUNT]"
    unit = {"monthly": "per month", "daily": "per day", "hourly": "per hour"}.get(mode, "per month")
    return f"Rs. {basic:,.0f}/- {unit}"


def _company_addr(company: dict) -> str:
    parts = [company.get("address"), company.get("city"), company.get("state")]
    return ", ".join([p for p in parts if p])


def _build_template(letter_type: str, emp: dict, company: dict) -> dict:
    name = emp.get("name") or "[EMPLOYEE NAME]"
    father = emp.get("father_name") or ""
    desig = emp.get("designation") or emp.get("position") or "[DESIGNATION]"
    doj = emp.get("doj") or "[DATE OF JOINING]"
    salary = _salary_text(emp)
    cname = company.get("name") or "[FIRM NAME]"
    today = _today_dmy()

    if letter_type == "offer":
        subject = f"Offer of Employment - {desig}"
        body = (
            f"Dear {name},\n\n"
            f"With reference to your application and the subsequent interview you had with us, "
            f"we are pleased to offer you employment with {cname} on the following terms:\n\n"
            f"1. Designation: You will be engaged as \"{desig}\".\n"
            f"2. Remuneration: You will be paid {salary}, subject to statutory deductions "
            f"(PF / ESI / Professional Tax, as applicable).\n"
            f"3. Date of Joining: You are requested to join duty on or before {doj}. "
            f"This offer stands withdrawn if you fail to report by that date.\n"
            f"4. Working Hours: You will observe the working hours, weekly off and shift "
            f"schedule notified by the management from time to time.\n"
            f"5. Verification: This offer is subject to verification of your documents, "
            f"credentials and antecedents being found satisfactory.\n\n"
            f"Kindly sign and return the duplicate copy of this letter as a token of your "
            f"acceptance of the above terms.\n\n"
            f"We look forward to a long and mutually rewarding association with you."
        )
    elif letter_type == "appointment":
        subject = f"Letter of Appointment - {desig}"
        body = (
            f"Dear {name},\n\n"
            f"Further to your application and subsequent discussions, we are pleased to "
            f"appoint you in the services of {cname} on the following terms and conditions:\n\n"
            f"1. Designation: You are appointed as \"{desig}\" with effect from {doj}.\n"
            f"2. Remuneration: You will be paid {salary}, subject to statutory deductions "
            f"(PF / ESI / Professional Tax, as applicable).\n"
            f"3. Probation: You will be on probation for a period of six (6) months from the "
            f"date of joining. On satisfactory completion, your services will be confirmed in "
            f"writing. The management may extend the probation period at its discretion.\n"
            f"4. Duties: You shall diligently perform the duties assigned to you and any other "
            f"work entrusted to you by the management from time to time.\n"
            f"5. Attendance & Leave: You will be governed by the attendance policy, working "
            f"hours, weekly off and leave rules of the establishment.\n"
            f"6. Termination: During probation, either party may terminate this appointment "
            f"with seven (7) days' notice. After confirmation, one (1) month's notice or "
            f"salary in lieu thereof shall apply on either side.\n"
            f"7. Conduct: You shall observe the rules of conduct and discipline of the "
            f"establishment. Any act of misconduct shall render you liable to disciplinary "
            f"action, including termination of service.\n\n"
            f"Please sign and return the duplicate copy of this letter as a token of your "
            f"acceptance of the above terms and conditions.\n\n"
            f"We welcome you to {cname} and wish you a successful career with us."
        )
    elif letter_type == "warning":
        subject = "Warning Letter"
        body = (
            f"Dear {name},\n\n"
            f"It has been brought to the notice of the management that on [DATE OF INCIDENT] "
            f"you were found [DESCRIBE THE MISCONDUCT / IRREGULARITY — e.g. absent from duty "
            f"without intimation / negligent in performing assigned duties / violating safety "
            f"instructions].\n\n"
            f"Such conduct amounts to misconduct under the service rules of the establishment "
            f"and cannot be tolerated. You are hereby warned to be careful in future and to "
            f"ensure that such conduct is not repeated.\n\n"
            f"Please note that if any such act or omission is repeated, the management shall "
            f"be constrained to take strict disciplinary action against you, which may include "
            f"termination of your services, without any further notice.\n\n"
            f"You are advised to submit your written explanation, if any, within three (3) "
            f"days of receipt of this letter.\n\n"
            f"This letter is being placed in your service record."
        )
    else:  # termination
        subject = "Termination of Employment"
        body = (
            f"Dear {name},\n\n"
            f"This is with reference to your employment as \"{desig}\" with {cname}.\n\n"
            f"The management regrets to inform you that your services are terminated with "
            f"effect from [LAST WORKING DATE] on account of [REASON — e.g. continued "
            f"unauthorised absence / repeated misconduct despite warnings / redundancy of "
            f"the post].\n\n"
            f"Your full and final settlement, including salary up to the last working day and "
            f"other statutory dues (if any), will be processed as per the rules of the "
            f"establishment and applicable law. You are requested to hand over all company "
            f"property, documents and materials in your possession to the undersigned.\n\n"
            f"On completion of the handover, your dues shall be released and a service "
            f"certificate will be issued to you on request.\n\n"
            f"We wish you success in your future endeavours."
        )
    return {
        "subject": subject,
        "body": body,
        "issued_date": today,
        "salutation_to": name,
    }


@router.get("/admin/hr-letters/template/{letter_type}")
async def hr_letter_template(
    letter_type: str,
    company_id: str = Query(...),
    user_id: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check_scope(admin, company_id)
    if letter_type not in LETTER_TYPES:
        raise HTTPException(status_code=400, detail="Unknown letter type")
    emp = await db.users.find_one(
        {"user_id": user_id, "company_id": company_id},
        {"_id": 0, "user_id": 1, "name": 1, "father_name": 1, "designation": 1,
         "position": 1, "doj": 1, "address": 1, "employee_code": 1,
         "salary_monthly": 1, "salary_mode": 1, "salary_structure_actual": 1},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found in this firm")
    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "address": 1, "city": 1, "state": 1, "company_code": 1},
    )
    if not company:
        raise HTTPException(status_code=404, detail="Firm not found")
    tpl = _build_template(letter_type, emp, company)
    return {
        "letter_type": letter_type,
        "letter_type_label": LETTER_TYPES[letter_type],
        **tpl,
        "employee": {
            "user_id": emp["user_id"],
            "name": emp.get("name"),
            "father_name": emp.get("father_name"),
            "designation": emp.get("designation") or emp.get("position"),
            "employee_code": emp.get("employee_code"),
            "address": emp.get("address"),
        },
        "company": {
            "name": company.get("name"),
            "address": _company_addr(company),
            "company_code": company.get("company_code"),
        },
    }


class LetterCreate(BaseModel):
    company_id: str
    user_id: str
    letter_type: str
    subject: str
    body: str
    issued_date: Optional[str] = None  # DD-MM-YYYY


@router.post("/admin/hr-letters")
async def hr_letter_create(payload: LetterCreate, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    await _check_scope(admin, payload.company_id)
    if payload.letter_type not in LETTER_TYPES:
        raise HTTPException(status_code=400, detail="Unknown letter type")
    if not payload.subject.strip() or not payload.body.strip():
        raise HTTPException(status_code=400, detail="Subject and body are required")
    emp = await db.users.find_one(
        {"user_id": payload.user_id, "company_id": payload.company_id},
        {"_id": 0, "name": 1, "father_name": 1, "designation": 1, "position": 1,
         "employee_code": 1, "address": 1},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found in this firm")
    company = await db.companies.find_one(
        {"company_id": payload.company_id},
        {"_id": 0, "name": 1, "address": 1, "city": 1, "state": 1, "company_code": 1},
    )
    seq = await db.hr_letters.count_documents(
        {"company_id": payload.company_id, "letter_type": payload.letter_type},
    ) + 1
    year = datetime.now(timezone.utc).year
    ref_no = f"{(company or {}).get('company_code') or 'FIRM'}/{ABBR[payload.letter_type]}/{year}/{seq:03d}"
    letter = {
        "letter_id": f"ltr_{uuid.uuid4().hex[:12]}",
        "company_id": payload.company_id,
        "user_id": payload.user_id,
        "letter_type": payload.letter_type,
        "letter_type_label": LETTER_TYPES[payload.letter_type],
        "ref_no": ref_no,
        "subject": payload.subject.strip(),
        "body": payload.body.strip(),
        "issued_date": (payload.issued_date or _today_dmy()).strip(),
        "employee_name": emp.get("name"),
        "employee_code": emp.get("employee_code"),
        "designation": emp.get("designation") or emp.get("position"),
        "created_by": admin.get("user_id"),
        "created_by_name": admin.get("name"),
        "created_at": now_iso(),
    }
    await db.hr_letters.insert_one({**letter})
    letter.pop("_id", None)
    return {"letter": letter}


@router.get("/admin/hr-letters")
async def hr_letter_register(
    company_id: str = Query(...),
    user_id: Optional[str] = Query(None),
    letter_type: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    await _check_scope(admin, company_id)
    q: dict = {"company_id": company_id}
    if user_id:
        q["user_id"] = user_id
    if letter_type and letter_type in LETTER_TYPES:
        q["letter_type"] = letter_type
    letters = await db.hr_letters.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"letters": letters}


@router.delete("/admin/hr-letters/{letter_id}")
async def hr_letter_delete(letter_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    letter = await db.hr_letters.find_one({"letter_id": letter_id}, {"_id": 0, "company_id": 1})
    if not letter:
        raise HTTPException(status_code=404, detail="Letter not found")
    await _check_scope(admin, letter["company_id"])
    await db.hr_letters.delete_one({"letter_id": letter_id})
    return {"deleted": True}


# ---------------------------------------------------------------------------
# PDF generation (fpdf2, latin-1 sanitised)
# ---------------------------------------------------------------------------

def _s(txt: str) -> str:
    """fpdf core fonts are latin-1 only; replace anything outside it."""
    return (txt or "").replace("\u2018", "'").replace("\u2019", "'") \
        .replace("\u201c", '"').replace("\u201d", '"') \
        .replace("\u2013", "-").replace("\u2014", "-") \
        .replace("\u20b9", "Rs.").encode("latin-1", "replace").decode("latin-1")


def _render_letter_page(pdf, letter: dict, company: dict, emp: dict) -> None:
    """Render one letter onto the CURRENT page of ``pdf``."""
    # ----- Letterhead -----
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, _s(company.get("name") or ""), align="C", new_x="LMARGIN", new_y="NEXT")
    addr = _company_addr(company)
    if addr:
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 5, _s(addr), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)
    pdf.set_draw_color(30, 30, 30)
    pdf.set_line_width(0.5)
    pdf.line(18, pdf.get_y(), 192, pdf.get_y())
    pdf.ln(6)

    # ----- Ref / Date -----
    pdf.set_font("Helvetica", "", 10.5)
    pdf.cell(120, 6, _s(f"Ref. No.: {letter.get('ref_no') or '-'}"))
    pdf.cell(0, 6, _s(f"Date: {letter.get('issued_date') or ''}"), align="R",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ----- To block -----
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(0, 6, "To,", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10.5)
    to_lines = [emp.get("name") or letter.get("employee_name") or ""]
    if emp.get("father_name"):
        to_lines.append(f"S/o {emp['father_name']}")
    desig = emp.get("designation") or emp.get("position") or letter.get("designation")
    code = emp.get("employee_code") or letter.get("employee_code")
    meta = " | ".join([p for p in [
        f"Emp. Code: {code}" if code else "",
        desig or "",
    ] if p])
    if meta:
        to_lines.append(meta)
    if emp.get("address"):
        to_lines.append(emp["address"])
    for ln in to_lines:
        pdf.cell(0, 5.5, _s(ln), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # ----- Subject -----
    pdf.set_font("Helvetica", "B", 11)
    pdf.multi_cell(0, 6, _s(f"Subject: {letter.get('subject') or ''}"))
    pdf.set_x(pdf.l_margin)
    pdf.ln(3)

    # ----- Body -----
    pdf.set_font("Helvetica", "", 10.5)
    pdf.multi_cell(0, 5.8, _s(letter.get("body") or ""))
    pdf.set_x(pdf.l_margin)
    pdf.ln(10)

    # ----- Signature block -----
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(0, 6, _s(f"For {company.get('name') or ''}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(14)
    pdf.cell(0, 6, "Authorised Signatory", new_x="LMARGIN", new_y="NEXT")


def _letter_pdf_bytes(letter: dict, company: dict, emp: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.add_page()
    pdf.set_margins(18, 16, 18)
    _render_letter_page(pdf, letter, company, emp)
    return bytes(pdf.output())


@router.get("/admin/hr-letters/{letter_id}/pdf")
async def hr_letter_pdf(letter_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    letter = await db.hr_letters.find_one({"letter_id": letter_id}, {"_id": 0})
    if not letter:
        raise HTTPException(status_code=404, detail="Letter not found")
    await _check_scope(admin, letter["company_id"])
    company = await db.companies.find_one(
        {"company_id": letter["company_id"]},
        {"_id": 0, "name": 1, "address": 1, "city": 1, "state": 1},
    ) or {}
    emp = await db.users.find_one(
        {"user_id": letter["user_id"]},
        {"_id": 0, "name": 1, "father_name": 1, "designation": 1, "position": 1,
         "employee_code": 1, "address": 1},
    ) or {}
    pdf = _letter_pdf_bytes(letter, company, emp)
    fname = f"{letter['letter_type_label'].replace(' ', '_')}_{(letter.get('employee_code') or 'emp')}_{letter['issued_date']}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


class LetterEmailPayload(BaseModel):
    to_email: Optional[str] = None  # override; defaults to employee's email


class BulkLetterPayload(BaseModel):
    company_id: str
    letter_type: str
    issued_date: Optional[str] = None    # DD-MM-YYYY
    send_email: bool = False             # email employees that have an address
    skip_existing: bool = True           # don't duplicate same-type letters


@router.post("/admin/hr-letters/bulk")
async def hr_letter_bulk(payload: BulkLetterPayload, authorization: Optional[str] = Header(None)):
    """Iter 95d — Generate (and optionally email) letters of one type for
    ALL employees of the firm in one click. Uses the standard template
    auto-filled per employee; letters land in the register like manual ones."""
    admin = await get_user_from_token(authorization)
    await _check_scope(admin, payload.company_id)
    if payload.letter_type not in LETTER_TYPES:
        raise HTTPException(status_code=400, detail="Unknown letter type")
    company = await db.companies.find_one(
        {"company_id": payload.company_id},
        {"_id": 0, "name": 1, "address": 1, "city": 1, "state": 1, "company_code": 1},
    )
    if not company:
        raise HTTPException(status_code=404, detail="Firm not found")
    employees = await db.users.find(
        {"role": "employee", "company_id": payload.company_id},
        {"_id": 0, "user_id": 1, "name": 1, "father_name": 1, "designation": 1,
         "position": 1, "doj": 1, "address": 1, "employee_code": 1, "email": 1,
         "salary_monthly": 1, "salary_mode": 1, "salary_structure_actual": 1},
    ).to_list(5000)

    existing_uids: set = set()
    if payload.skip_existing:
        cur = db.hr_letters.find(
            {"company_id": payload.company_id, "letter_type": payload.letter_type},
            {"_id": 0, "user_id": 1},
        )
        existing_uids = {d["user_id"] async for d in cur}

    seq = await db.hr_letters.count_documents(
        {"company_id": payload.company_id, "letter_type": payload.letter_type},
    )
    year = datetime.now(timezone.utc).year
    issued = (payload.issued_date or _today_dmy()).strip()
    code = company.get("company_code") or "FIRM"

    import base64 as _b64
    created = skipped = emailed = email_failed = no_email = 0
    for emp in employees:
        if emp["user_id"] in existing_uids:
            skipped += 1
            continue
        tpl = _build_template(payload.letter_type, emp, company)
        seq += 1
        letter = {
            "letter_id": f"ltr_{uuid.uuid4().hex[:12]}",
            "company_id": payload.company_id,
            "user_id": emp["user_id"],
            "letter_type": payload.letter_type,
            "letter_type_label": LETTER_TYPES[payload.letter_type],
            "ref_no": f"{code}/{ABBR[payload.letter_type]}/{year}/{seq:03d}",
            "subject": tpl["subject"],
            "body": tpl["body"],
            "issued_date": issued,
            "employee_name": emp.get("name"),
            "employee_code": emp.get("employee_code"),
            "designation": emp.get("designation") or emp.get("position"),
            "created_by": admin.get("user_id"),
            "created_by_name": admin.get("name"),
            "created_at": now_iso(),
            "bulk": True,
        }
        await db.hr_letters.insert_one({**letter})
        created += 1
        if payload.send_email:
            to_email = (emp.get("email") or "").strip()
            if not to_email or "@" not in to_email:
                no_email += 1
                continue
            pdf = _letter_pdf_bytes(letter, company, emp)
            fname = f"{letter['letter_type_label'].replace(' ', '_')}_{(emp.get('employee_code') or 'emp')}_{issued}.pdf"
            text = (
                f"Dear {emp.get('name') or ''},\n\nPlease find attached your "
                f"{letter['letter_type_label'].lower()} (Ref: {letter['ref_no']}) "
                f"dated {issued} from {company.get('name') or ''}.\n\n"
                f"Regards,\n{company.get('name') or ''}"
            )
            result = await _send_email_with_attachments(
                to_email=to_email,
                subject=f"{letter['letter_type_label']} — {company.get('name') or ''}",
                text=text,
                html=text.replace("\n", "<br/>"),
                attachments=[{
                    "filename": fname,
                    "content": _b64.b64encode(pdf).decode("ascii"),
                    "content_type": "application/pdf",
                }],
            )
            if result.get("delivered"):
                emailed += 1
                await db.hr_letters.update_one(
                    {"letter_id": letter["letter_id"]},
                    {"$set": {"emailed_to": to_email, "emailed_at": now_iso(),
                              "email_delivered": True}},
                )
            else:
                email_failed += 1

    return {
        "created": created,
        "skipped_existing": skipped,
        "emailed": emailed,
        "email_failed": email_failed,
        "no_email": no_email,
        "total_employees": len(employees),
    }


@router.get("/admin/hr-letters/bulk.pdf")
async def hr_letter_bulk_pdf(
    company_id: str = Query(...),
    letter_type: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    """Combined printable PDF — every saved letter of this type, one per
    page — so firms can print the whole batch in one go."""
    admin = await get_user_from_token(authorization)
    await _check_scope(admin, company_id)
    if letter_type not in LETTER_TYPES:
        raise HTTPException(status_code=400, detail="Unknown letter type")
    letters = await db.hr_letters.find(
        {"company_id": company_id, "letter_type": letter_type}, {"_id": 0},
    ).sort("employee_code", 1).to_list(2000)
    if not letters:
        raise HTTPException(status_code=404, detail="No letters of this type in the register")
    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "address": 1, "city": 1, "state": 1},
    ) or {}
    emps = {u["user_id"]: u for u in await db.users.find(
        {"user_id": {"$in": [l["user_id"] for l in letters]}},
        {"_id": 0, "user_id": 1, "name": 1, "father_name": 1, "designation": 1,
         "position": 1, "employee_code": 1, "address": 1},
    ).to_list(5000)}

    from fpdf import FPDF
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=22)
    for letter in letters:
        pdf.add_page()
        pdf.set_margins(18, 16, 18)
        _render_letter_page(pdf, letter, company, emps.get(letter["user_id"], {}))
    fname = f"{LETTER_TYPES[letter_type].replace(' ', '_')}s_ALL_{_today_dmy()}.pdf"
    return Response(
        content=bytes(pdf.output()),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/admin/hr-letters/{letter_id}/email")
async def hr_letter_email(
    letter_id: str,
    payload: LetterEmailPayload,
    authorization: Optional[str] = Header(None),
):
    """Iter 95c — Email the letter PDF to the employee (Resend). Optional
    ``to_email`` override for firms where employees have no email on file."""
    admin = await get_user_from_token(authorization)
    letter = await db.hr_letters.find_one({"letter_id": letter_id}, {"_id": 0})
    if not letter:
        raise HTTPException(status_code=404, detail="Letter not found")
    await _check_scope(admin, letter["company_id"])
    company = await db.companies.find_one(
        {"company_id": letter["company_id"]},
        {"_id": 0, "name": 1, "address": 1, "city": 1, "state": 1},
    ) or {}
    emp = await db.users.find_one(
        {"user_id": letter["user_id"]},
        {"_id": 0, "name": 1, "father_name": 1, "designation": 1, "position": 1,
         "employee_code": 1, "address": 1, "email": 1},
    ) or {}
    to_email = (payload.to_email or "").strip() or (emp.get("email") or "").strip()
    if not to_email or "@" not in to_email:
        raise HTTPException(
            status_code=400,
            detail="Employee has no email on file. Add one in the Employee "
                   "Master or type a recipient email.",
        )
    import base64 as _b64
    pdf = _letter_pdf_bytes(letter, company, emp)
    fname = f"{letter['letter_type_label'].replace(' ', '_')}_{(letter.get('employee_code') or 'emp')}_{letter['issued_date']}.pdf"
    subject = f"{letter['letter_type_label']} — {company.get('name') or ''}"
    text = (
        f"Dear {emp.get('name') or letter.get('employee_name') or ''},\n\n"
        f"Please find attached your {letter['letter_type_label'].lower()} "
        f"(Ref: {letter.get('ref_no')}) dated {letter.get('issued_date')} "
        f"from {company.get('name') or ''}.\n\n"
        f"Regards,\n{company.get('name') or ''}"
    )
    html = text.replace("\n", "<br/>")
    result = await _send_email_with_attachments(
        to_email=to_email,
        subject=subject,
        text=text,
        html=html,
        attachments=[{
            "filename": fname,
            "content": _b64.b64encode(pdf).decode("ascii"),
            "content_type": "application/pdf",
        }],
    )
    await db.hr_letters.update_one(
        {"letter_id": letter_id},
        {"$set": {
            "emailed_to": to_email,
            "emailed_at": now_iso(),
            "email_delivered": bool(result.get("delivered")),
            "email_error": result.get("error"),
        }},
    )
    if not result.get("delivered"):
        raise HTTPException(
            status_code=502,
            detail=f"Email could not be delivered: {result.get('error')}",
        )
    return {"delivered": True, "to_email": to_email}
