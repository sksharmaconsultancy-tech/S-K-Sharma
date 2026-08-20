"""Iter 645 — INCENTIVE / custom allowance columns inside BOTH PDF register
formats. Reuses the iter644 firm scenario; asserts both PDFs build and the
INCENTIVE column + amounts appear, with OTHER showing the remainder."""
import asyncio
import io
import sys

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

MONTH = "2026-07"
CID = "cmp_test_iter645"


async def cleanup(db):
    for col in ("companies", "firm_masters", "users",
                "compliance_salary_runs", "compliance_master_snapshots"):
        await getattr(db, col).delete_many({"company_id": CID})


async def main():
    import server  # noqa: F401
    from routes.compliance_salary_runs import (
        _create_compliance_salary_run_core, ComplianceSalaryRunCreate, db)
    from utils.compliance_salary import (
        build_compliance_register_pdf, build_compliance_register_pdf_v2)

    await cleanup(db)
    await db.companies.insert_one({
        "company_id": CID, "name": "TEST FIRM ITER645", "active": True,
        "company_code": "T645"})
    await db.firm_masters.insert_one({
        "company_id": CID,
        "salary_process": {"online_salary": True,
                           "days_calc_method": "fixed",
                           "days_calc_fixed": 26},
        "allowances": {"HRA": True, "CONV.": True, "INCENTIVE": True,
                       "OTHER MISC.ALLOWANCE": True, "OVER TIME": False},
        "deductions": {"PF": True, "ESI": True, "TDS": True},
        "epf": {"applicable": True}, "esi": {"applicable": True},
        "updated_at": "2026-06-01T00:00:00Z", "updated_by": "test",
    })
    await db.users.insert_one({
        "user_id": "user_test645", "role": "employee", "company_id": CID,
        "name": "Test Emp 645", "employee_type": "STAFF", "active": True,
        "status": "active", "compliance_basic": 9000,
        "compliance_salary_allowances": [
            {"head": "HRA", "amount": 3600},
            {"head": "INCENTIVE", "amount": 2000},
            {"head": "OTHER MISC.ALLOWANCE", "amount": 440},
        ],
    })
    admin = {"user_id": "user_admin_test", "role": "super_admin",
             "name": "Test Admin", "company_id": None}
    resp = await _create_compliance_salary_run_core(
        ComplianceSalaryRunCreate(month=MONTH, company_id=CID,
                                  month_days=26, present_days_all=26), admin)
    run = resp["run"]

    def pdf_text(data: bytes) -> str:
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)

    # ---- Format 1 ----
    pdf1 = build_compliance_register_pdf(run, firm={"name": "TEST FIRM ITER645"})
    t1 = pdf_text(pdf1)
    assert "INCENTIVE" in t1, "Format 1 missing INCENTIVE column"
    assert "2000" in t1, "Format 1 missing INCENTIVE amount 2000"
    assert "440" in t1, "Format 1 missing OTHER remainder 440"
    print(f"Format 1 OK ({len(pdf1)} bytes) — INCENTIVE column + 2000 + remainder 440 present")

    # ---- Format 2 (amounts are comma-formatted here) ----
    pdf2 = build_compliance_register_pdf_v2(run, firm={"name": "TEST FIRM ITER645"})
    t2 = pdf_text(pdf2)
    assert "INCENTIVE" in t2, "Format 2 missing INCENTIVE column"
    assert "2,000" in t2 or "2000" in t2, "Format 2 missing INCENTIVE amount"
    assert "440" in t2, "Format 2 missing OTHER remainder 440"
    print(f"Format 2 OK ({len(pdf2)} bytes) — INCENTIVE column + 2,000 + remainder 440 present")

    # ---- No-labels regression: firm without custom heads still builds ----
    for r in run["rows"]:
        r.pop("allowance_head_labels", None)
        r.pop("allowance_heads", None)
        r.pop("allowance_heads_master", None)
    pdf3 = build_compliance_register_pdf(run, firm={})
    pdf4 = build_compliance_register_pdf_v2(run, firm={})
    assert len(pdf3) > 500 and len(pdf4) > 500
    print("Regression OK — registers still build without allowance labels")

    await cleanup(db)
    print("ALL PDF CHECKS PASSED ✅")


asyncio.run(main())
