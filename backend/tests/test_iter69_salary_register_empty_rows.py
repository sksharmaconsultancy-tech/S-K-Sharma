"""Iter 69 regression — verify build_salary_register_pdf handles empty rows.

The reader-side wiring (server.py:10679) was fixed to prefer
run['rows'] over run['lines'], and the writer-side (utils/salary_register_pdf.py)
was hardened with an empty-rows guard so ReportLab no longer raises
'must have at least a row and column' when a salary run has zero employees.

This test invokes the builder directly with rows=[] to prove the guard is
effective without needing to seed an empty run in Mongo.
"""
import sys
sys.path.insert(0, "/app/backend")

from utils.salary_register_pdf import build_salary_register_pdf


def test_build_salary_register_pdf_with_empty_rows():
    """Empty rows must render a placeholder PDF, not raise."""
    pdf = build_salary_register_pdf(
        company={
            "name": "Empty Firm Ltd",
            "address": "1 Test Rd",
            "pf_code": "PF/EMPTY/001",
            "esic_code": "ESIC/EMPTY/001",
        },
        month="2025-12",
        month_days=31,
        rows=[],
        totals={},
        payment_date=None,
    )
    assert isinstance(pdf, bytes), "builder must return bytes"
    assert pdf[:5] == b"%PDF-", f"invalid PDF header: {pdf[:16]!r}"
    assert len(pdf) > 1024, f"PDF suspiciously small: {len(pdf)} bytes"


def test_build_salary_register_pdf_with_one_row():
    """Happy-path sanity check: single row still renders."""
    pdf = build_salary_register_pdf(
        company={
            "name": "Sample Firm",
            "address": "2 Sample Rd",
            "pf_code": "PF/S/001",
            "esic_code": "ESIC/S/001",
        },
        month="2025-12",
        month_days=31,
        rows=[{
            "name": "QA User",
            "father_name": "QA Sr",
            "pf_no": "PF001",
            "esi_ip_no": "ESI001",
            "designation": "Tester",
            "present_days": 26,
            "duty_hours": 8,
            "basic": 20000,
            "hra": 5000,
            "conveyance": 1000,
            "ot_pay": 500,
            "gross": 26500,
            "gross_paid": 26500,
            "pf_employee": 1800,
            "esic_employee": 200,
            "advance": 0,
            "other_deduction": 0,
            "tds": 0,
            "total_deduction": 2000,
            "net": 24500,
        }],
        totals={
            "basic": 20000, "hra": 5000, "conveyance": 1000, "ot_pay": 500,
            "gross": 26500, "pf_employee": 1800, "esic_employee": 200,
            "advance": 0, "other_deduction": 0, "tds": 0,
            "total_deduction": 2000, "net": 24500,
        },
        payment_date="2026-01-05",
    )
    assert isinstance(pdf, bytes)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1024
