"""Iter 741 — COMMON ACCIDENT MASTER (ESIC + Factory & Boilers).

ONE accident record feeds both statutory tracks (spec: single entry, no
duplicate data). ESIC (Form 11 register / Form 12 report) and Factory &
Boilers (state-configurable report) have INDEPENDENT status tracking.
Collection: ``accidents``. Existing ESIC Leave / Factory Compliance /
portal automation untouched.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import db, get_user_from_token, require_role, now_iso  # noqa: E402

router = APIRouter(prefix="/api/admin/accidents", tags=["accidents"])
_ROLES = ["super_admin", "sub_admin", "company_admin"]

_FIELDS = ("accident_date", "accident_time", "reporting_datetime", "user_id",
           "employee_name", "employee_code", "esic_ip_number", "uan", "doj",
           "department", "designation", "branch_id", "branch_name",
           "factory_name", "shift", "location", "accident_type",
           "injury_nature", "body_part", "cause", "description", "witnesses",
           "first_aid", "doctor_hospital", "hospitalised", "fatal",
           "leave_days", "remarks",
           "esic_applicable", "fnb_applicable")

_FNB_FIELDS = ("factory_regn_no", "factory_address", "district",
               "occupier_name", "occupier_contact", "manager_name",
               "manager_contact", "jurisdiction", "location_in_factory",
               "section", "machine", "machine_id", "work_process",
               "immediate_cause", "root_cause", "dangerous_occurrence",
               "persons_injured", "fatalities", "medical_treatment",
               "hospital", "witness_details", "corrective_action",
               "preventive_action", "inspector_details", "fnb_remarks")


async def _gate(authorization, company_id):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ROLES)
    cid = admin.get("company_id") if admin["role"] == "company_admin" else company_id
    if not cid:
        raise HTTPException(status_code=400, detail="company_id required")
    return admin, cid


async def _next_no(cid: str) -> str:
    year = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).year
    n = await db.accidents.count_documents({"company_id": cid,
                                            "accident_no": {"$regex": f"^ACC-{year}-"}})
    return f"ACC-{year}-{n + 1:03d}"


@router.get("")
async def acc_list(company_id: Optional[str] = Query(None),
                   q: Optional[str] = Query(None),
                   status: Optional[str] = Query(None),
                   fatal: Optional[str] = Query(None),
                   authorization: Optional[str] = Header(None)):
    _, cid = await _gate(authorization, company_id)
    rows = await db.accidents.find({"company_id": cid}, {"_id": 0, "documents": 0}) \
        .sort("accident_date", -1).to_list(500)
    if q:
        s = q.strip().lower()
        rows = [r for r in rows if s in (r.get("employee_name") or "").lower()
                or s in (r.get("accident_no") or "").lower()]
    if fatal in ("yes", "no"):
        rows = [r for r in rows if bool(r.get("fatal")) == (fatal == "yes")]
    if status:
        rows = [r for r in rows
                if (r.get("esic_status") or {}).get("submission_status") == status
                or (r.get("fnb_status") or {}).get("submission_status") == status]
    d = {"total": len(rows),
         "esic_applicable": sum(1 for r in rows if r.get("esic_applicable")),
         "fnb_applicable": sum(1 for r in rows if r.get("fnb_applicable")),
         "both": sum(1 for r in rows if r.get("esic_applicable") and r.get("fnb_applicable")),
         "fatal": sum(1 for r in rows if r.get("fatal")),
         "esic_pending": sum(1 for r in rows if r.get("esic_applicable")
                             and (r.get("esic_status") or {}).get("submission_status") != "submitted"),
         "esic_submitted": sum(1 for r in rows if (r.get("esic_status") or {}).get("submission_status") == "submitted"),
         "fnb_pending": sum(1 for r in rows if r.get("fnb_applicable")
                            and (r.get("fnb_status") or {}).get("submission_status") != "filed"),
         "fnb_filed": sum(1 for r in rows if (r.get("fnb_status") or {}).get("submission_status") == "filed")}
    return {"accidents": rows, "dashboard": d}


@router.post("")
async def acc_create(body: Dict[str, Any] = Body(...),
                     authorization: Optional[str] = Header(None)):
    admin, cid = await _gate(authorization, body.get("company_id"))
    if not str(body.get("employee_name") or "").strip() and not body.get("user_id"):
        raise HTTPException(status_code=400, detail="Employee is required")
    if not body.get("accident_date"):
        raise HTTPException(status_code=400, detail="Accident date is required")
    doc: Dict[str, Any] = {"accident_id": f"acc_{uuid.uuid4().hex[:10]}",
                           "company_id": cid,
                           "accident_no": await _next_no(cid),
                           "esic_status": {"form11_generated": False, "form12_generated": False,
                                           "submission_status": "pending", "ack_no": None,
                                           "submission_date": None},
                           "fnb_status": {"register_status": "pending", "report_generated": False,
                                          "submission_status": "pending", "ref_no": None,
                                          "submission_date": None},
                           "created_at": now_iso(),
                           "created_by_name": admin.get("name") or admin.get("email")}
    for k in _FIELDS:
        if k in body:
            doc[k] = body[k]
    doc["fnb"] = {k: body.get("fnb", {}).get(k) for k in _FNB_FIELDS} if body.get("fnb") else {}
    # auto-fill from employee master (enter once — reuse everywhere)
    if body.get("user_id"):
        u = await db.users.find_one({"user_id": body["user_id"]}, {"_id": 0})
        if u:
            doc.setdefault("employee_name", u.get("name"))
            doc.setdefault("employee_code", u.get("employee_code"))
            doc.setdefault("esic_ip_number", u.get("esic_number") or u.get("esi_number"))
            doc.setdefault("uan", u.get("uan") or u.get("pf_uan"))
            doc.setdefault("doj", u.get("doj") or u.get("date_of_joining"))
            doc.setdefault("department", u.get("department"))
            doc.setdefault("designation", u.get("designation"))
            doc.setdefault("branch_name", u.get("branch_name"))
    await db.accidents.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "accident": doc}


@router.patch("/{accident_id}")
async def acc_patch(accident_id: str, body: Dict[str, Any] = Body(...),
                    authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, _ROLES)
    a = await db.accidents.find_one({"accident_id": accident_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Accident not found")
    patch: Dict[str, Any] = {k: body[k] for k in _FIELDS if k in body}
    if "fnb" in body and isinstance(body["fnb"], dict):
        merged = dict(a.get("fnb") or {})
        merged.update({k: body["fnb"].get(k) for k in _FNB_FIELDS if k in body["fnb"]})
        patch["fnb"] = merged
    # independent status tracks
    for track in ("esic_status", "fnb_status"):
        if track in body and isinstance(body[track], dict):
            merged = dict(a.get(track) or {})
            merged.update(body[track])
            patch[track] = merged
    patch["updated_at"] = now_iso()
    patch["updated_by_name"] = admin.get("name") or admin.get("email")
    await db.accidents.update_one({"accident_id": accident_id}, {"$set": patch})
    fresh = await db.accidents.find_one({"accident_id": accident_id}, {"_id": 0})
    return {"ok": True, "accident": fresh}


@router.get("/{accident_id}/report")
async def acc_report(accident_id: str, kind: str = Query("form12"),
                     authorization: Optional[str] = Header(None)):
    """PDF: kind=form12 (ESIC Employer's Accident Report) or kind=fnb
    (Factory & Boilers accident report — generic all-state format with the
    firm's state noted; format configurable later per authority)."""
    import io
    from fastapi.responses import Response
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as _canvas
    admin = await get_user_from_token(authorization)
    require_role(admin, _ROLES)
    a = await db.accidents.find_one({"accident_id": accident_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Accident not found")
    comp = await db.companies.find_one({"company_id": a["company_id"]}, {"_id": 0}) or {}
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    y = H - 20 * mm
    fnb = a.get("fnb") or {}
    title = ("EMPLOYER'S REPORT OF ACCIDENT — ESI ACT, 1948 (Regulation 68 / Form 12)"
             if kind == "form12" else
             "REPORT OF ACCIDENT — FACTORIES ACT, 1948 (Factory & Boilers Authority)")
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(W / 2, y, comp.get("name") or "")
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(W / 2, y, title)
    y -= 10 * mm
    rows = [("Accident No.", a.get("accident_no")),
            ("Accident Date / Time", f"{a.get('accident_date') or ''}  {a.get('accident_time') or ''}"),
            ("Employee", f"{a.get('employee_name') or ''} ({a.get('employee_code') or ''})"),
            ("ESIC IP No. / UAN", f"{a.get('esic_ip_number') or '-'} / {a.get('uan') or '-'}"),
            ("DOJ / Department / Designation",
             f"{a.get('doj') or '-'} / {a.get('department') or '-'} / {a.get('designation') or '-'}"),
            ("Branch / Factory", f"{a.get('branch_name') or '-'} {a.get('factory_name') or ''}"),
            ("Shift / Location", f"{a.get('shift') or '-'} / {a.get('location') or '-'}"),
            ("Accident Type / Fatal", f"{a.get('accident_type') or '-'} / {'FATAL' if a.get('fatal') else 'Non-Fatal'}"),
            ("Nature of Injury / Body Part", f"{a.get('injury_nature') or '-'} / {a.get('body_part') or '-'}"),
            ("Cause", a.get("cause")),
            ("Description", a.get("description")),
            ("Witnesses", a.get("witnesses")),
            ("First Aid / Doctor / Hospital", f"{a.get('first_aid') or '-'} / {a.get('doctor_hospital') or '-'}"),
            ("Hospitalised / Leave days", f"{'Yes' if a.get('hospitalised') else 'No'} / {a.get('leave_days') or '-'}")]
    if kind == "fnb":
        rows += [("Factory Regn / License No.", fnb.get("factory_regn_no")),
                 ("Occupier", f"{fnb.get('occupier_name') or '-'} ({fnb.get('occupier_contact') or '-'})"),
                 ("Manager", f"{fnb.get('manager_name') or '-'} ({fnb.get('manager_contact') or '-'})"),
                 ("Section / Machine", f"{fnb.get('section') or '-'} / {fnb.get('machine') or '-'} {fnb.get('machine_id') or ''}"),
                 ("Work / Process", fnb.get("work_process")),
                 ("Immediate Cause", fnb.get("immediate_cause")),
                 ("Root Cause", fnb.get("root_cause")),
                 ("Dangerous Occurrence", "Yes" if fnb.get("dangerous_occurrence") else "No"),
                 ("Persons Injured / Fatalities", f"{fnb.get('persons_injured') or 0} / {fnb.get('fatalities') or 0}"),
                 ("Corrective Action", fnb.get("corrective_action")),
                 ("Preventive Action", fnb.get("preventive_action"))]
    c.setFont("Helvetica", 9)
    for label, val in rows:
        if y < 30 * mm:
            c.showPage()
            y = H - 20 * mm
            c.setFont("Helvetica", 9)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(20 * mm, y, f"{label}:")
        c.setFont("Helvetica", 9)
        txt = str(val or "-")
        c.drawString(78 * mm, y, txt[:95])
        y -= 6.2 * mm
    y -= 8 * mm
    c.drawString(20 * mm, y, "Signature of Employer / Manager: ____________________     Date: __________")
    c.save()
    # mark generated flags
    flag = {"esic_status.form12_generated": True} if kind == "form12" \
        else {"fnb_status.report_generated": True}
    await db.accidents.update_one({"accident_id": accident_id}, {"$set": flag})
    fname = f"{a.get('accident_no')}_{'ESIC_Form12' if kind == 'form12' else 'Factory_Boilers_Report'}.pdf"
    return Response(content=buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/register/export")
async def acc_register_export(company_id: Optional[str] = Query(None),
                              authorization: Optional[str] = Header(None)):
    import io
    from fastapi.responses import Response
    from openpyxl import Workbook
    from openpyxl.styles import Font
    _, cid = await _gate(authorization, company_id)
    rows = await db.accidents.find({"company_id": cid}, {"_id": 0}) \
        .sort("accident_date", 1).to_list(1000)
    wb = Workbook()
    ws = wb.active
    ws.title = "Accident Register"
    ws.append(["Accident No.", "Date", "Employee", "Code", "IP No.",
               "Department", "Branch", "Type", "Injury", "Fatal",
               "ESIC Applicable", "ESIC Status", "ESIC Ack",
               "F&B Applicable", "F&B Status", "F&B Ref"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        es, fs = r.get("esic_status") or {}, r.get("fnb_status") or {}
        ws.append([r.get("accident_no"), r.get("accident_date"),
                   r.get("employee_name"), r.get("employee_code"),
                   r.get("esic_ip_number"), r.get("department"),
                   r.get("branch_name"), r.get("accident_type"),
                   r.get("injury_nature"), "FATAL" if r.get("fatal") else "Non-Fatal",
                   "Yes" if r.get("esic_applicable") else "No",
                   es.get("submission_status"), es.get("ack_no"),
                   "Yes" if r.get("fnb_applicable") else "No",
                   fs.get("submission_status"), fs.get("ref_no")])
    out = io.BytesIO()
    wb.save(out)
    return Response(content=out.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="Accident_Register.xlsx"'})
