"""Salary Process readiness / compliance validation — Enterprise UI feed.

One endpoint that powers the "Process Command Center" (KPI cards, workflow
stepper and live validation panel) shown on top of the Compliance / Actual /
Arrear salary process screens. Everything is computed LIVE from the DB for
the selected company + month.

  GET /api/admin/salary-process/readiness?company_id=&month=YYYY-MM
"""
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    sub_admin_can_touch_company,
)

router = APIRouter(prefix="/api/admin", tags=["salary-readiness"])

_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


@router.get("/salary-process/readiness")
async def salary_process_readiness(
    company_id: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    if admin["role"] == "sub_admin" and company_id:
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")
    if not month or not re.match(r"^\d{4}-\d{2}$", month):
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")

    # ---- Eligibility rules (shared with the Statutory Registration module)
    from routes.statutory_registration import get_settings
    settings = await get_settings(company_id)
    esic_ceiling = float(settings.get("esic_wage_ceiling") or 21000)
    pf_ceiling = float(settings.get("pf_wage_ceiling") or 15000)
    pf_cover_all = bool(settings.get("pf_cover_all", True))

    # ---- Employee master scan (single pass)
    emps: List[Dict[str, Any]] = await db.users.find(
        {"role": "employee", "company_id": company_id},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "salary_monthly": 1,
         "salary_structure_actual": 1, "aadhaar_no": 1, "aadhar_number": 1,
         "pan_no": 1, "pan_number": 1, "bank_account_number": 1, "ifsc_code": 1,
         "uan_no": 1, "esi_ip_no": 1, "pf_no": 1, "pt_state": 1,
         "pt_amount_override": 1, "is_contractual": 1, "contractor_name": 1,
         "dob": 1, "doj": 1},
    ).to_list(20000)
    total = len(emps)

    def _wage(e: Dict[str, Any]) -> float:
        try:
            return float(e.get("salary_monthly") or 0)
        except (TypeError, ValueError):
            return 0.0

    aadhaar_ok = pan_ok = bank_ok = wage_ok = 0
    uan_have = esic_have = 0
    pf_eligible = esic_eligible = pt_applicable = 0
    contractual = contractual_ok = 0
    aadhaar_values: Counter = Counter()
    code_values: Counter = Counter()
    kyc_ok = 0
    for e in emps:
        aad = re.sub(r"\D", "", str(e.get("aadhaar_no") or e.get("aadhar_number") or ""))
        pan = (e.get("pan_no") or e.get("pan_number") or "").strip().upper()
        a_ok = len(aad) == 12
        p_ok = bool(pan and _PAN_RE.match(pan))
        b_ok = bool((e.get("bank_account_number") or "").strip()
                    and (e.get("ifsc_code") or "").strip())
        w = _wage(e)
        w_ok = w > 0 or bool(e.get("salary_structure_actual"))
        aadhaar_ok += a_ok
        pan_ok += p_ok
        bank_ok += b_ok
        wage_ok += w_ok
        if a_ok and p_ok and b_ok:
            kyc_ok += 1
        if a_ok:
            aadhaar_values[aad] += 1
        code = str(e.get("employee_code") or "").strip()
        if code:
            code_values[code] += 1
        has_uan = bool((e.get("uan_no") or "").strip())
        has_ip = bool((e.get("esi_ip_no") or "").strip())
        uan_have += has_uan
        esic_have += has_ip
        pf_el = pf_cover_all or (0 < w <= pf_ceiling)
        esic_el = 0 < w <= esic_ceiling
        pf_eligible += pf_el
        esic_eligible += esic_el
        if (e.get("pt_state") or "").strip() or e.get("pt_amount_override") is not None:
            pt_applicable += 1
        if e.get("is_contractual"):
            contractual += 1
            if (e.get("contractor_name") or "").strip():
                contractual_ok += 1

    dup_aadhaar = sum(c - 1 for c in aadhaar_values.values() if c > 1)
    dup_codes = sum(c - 1 for c in code_values.values() if c > 1)
    duplicates = dup_aadhaar + dup_codes

    # ---- Attendance presence for the month
    att_count = await db.attendance.count_documents(
        {"company_id": company_id, "date": {"$regex": f"^{month}"}})
    att_master = await db.attendance_master_entries.count_documents(
        {"company_id": company_id, "month": month})

    # ---- Runs for the month (KPI: salary processed / locked)
    comp_run = await db.compliance_salary_runs.find_one(
        {"company_id": company_id, "month": month},
        {"_id": 0, "employees_count": 1, "finalized": 1, "generated_at": 1},
        sort=[("generated_at", -1)],
    )
    actual_run = await db.actual_salary_runs.find_one(
        {"company_id": company_id, "month": month},
        {"_id": 0, "employees_count": 1, "finalized": 1},
        sort=[("generated_at", -1)],
    )

    # ---- Challans uploaded for the month
    pf_challan = await db.challans.count_documents(
        {"company_id": company_id, "month": month, "kind": {"$in": ["pf", "PF", "epf"]}})
    esic_challan = await db.challans.count_documents(
        {"company_id": company_id, "month": month, "kind": {"$in": ["esic", "ESIC", "esi"]}})

    def chk(key: str, label: str, passed: int, tot: int, note: str = "",
            invert: bool = False, na: bool = False) -> Dict[str, Any]:
        ok = na or (passed >= tot if not invert else passed == 0)
        return {"key": key, "label": label, "ok": bool(ok),
                "passed": passed, "total": tot, "note": note, "na": na}

    checks = [
        chk("attendance", "Attendance Completed",
            1 if (att_count or att_master) else 0, 1,
            (f"{att_count} punch records" + (f" · {att_master} master rows" if att_master else ""))
            if (att_count or att_master) else "No attendance data found for this month"),
        chk("salary_structure", "Salary Structure Available", wage_ok, total,
            f"{wage_ok}/{total} employees have a wage / structure"),
        chk("uan", "UAN Verified", uan_have, pf_eligible,
            f"{uan_have}/{pf_eligible} PF-eligible employees have a UAN"),
        chk("esic_ip", "ESIC IP Verified", esic_have if esic_eligible else 0,
            esic_eligible,
            (f"{esic_have}/{esic_eligible} ESIC-eligible employees have an IP number"
             if esic_eligible else "No ESIC-eligible employees"),
            na=esic_eligible == 0),
        chk("aadhaar", "Aadhaar Verified", aadhaar_ok, total,
            f"{aadhaar_ok}/{total} employees have a valid 12-digit Aadhaar"),
        chk("pan", "PAN Verified", pan_ok, total,
            f"{pan_ok}/{total} employees have a valid PAN"),
        chk("bank", "Bank Verified", bank_ok, total,
            f"{bank_ok}/{total} employees have A/c + IFSC on file"),
        chk("wage_def", "Wage Definition Validation", wage_ok, total,
            "Monthly wage / salary structure present on the Employee Master"),
        chk("duplicates", "Duplicate Employee Check", duplicates, 0,
            ("No duplicate Aadhaar / employee codes" if duplicates == 0 else
             f"{dup_aadhaar} duplicate Aadhaar, {dup_codes} duplicate employee codes"),
            invert=True),
        chk("contractor", "Contractor Validation",
            contractual_ok, contractual,
            (f"{contractual_ok}/{contractual} contractual employees mapped to a contractor"
             if contractual else "No contractual employees"),
            na=contractual == 0),
        chk("documents", "KYC Documents Complete", kyc_ok, total,
            f"{kyc_ok}/{total} employees have Aadhaar + PAN + Bank complete"),
    ]

    # Overall compliance % — countable checks weighted by their totals;
    # boolean-style checks (attendance / duplicates) count as 1 point.
    num = den = 0.0
    for c in checks:
        if c["na"]:
            continue
        if c["total"] and c["key"] != "duplicates":
            num += min(c["passed"], c["total"])
            den += c["total"]
        else:
            num += 1 if c["ok"] else 0
            den += 1
    pct = round(num * 100.0 / den, 1) if den else 0.0
    errors = sum(1 for c in checks if not c["ok"] and not c["na"])

    return {
        "ok": True,
        "company_id": company_id,
        "month": month,
        "compliance_pct": pct,
        "kpis": {
            "total_employees": total,
            "pf_eligible": pf_eligible,
            "esic_eligible": esic_eligible,
            "pt_applicable": pt_applicable,
            "uan_missing": max(pf_eligible - uan_have, 0),
            "esic_ip_missing": max(esic_eligible - esic_have, 0),
            "compliance_errors": errors,
            "salary_processed": {
                "compliance": bool(comp_run),
                "compliance_count": (comp_run or {}).get("employees_count") or 0,
                "compliance_finalized": bool((comp_run or {}).get("finalized")),
                "actual": bool(actual_run),
                "actual_count": (actual_run or {}).get("employees_count") or 0,
                "actual_finalized": bool((actual_run or {}).get("finalized")),
            },
            "challans": {
                "pf_uploaded": pf_challan > 0,
                "esic_uploaded": esic_challan > 0,
                "pending": (0 if pf_challan else 1) + (0 if esic_challan else 1),
            },
            "attendance_records": att_count,
        },
        "checks": checks,
    }
