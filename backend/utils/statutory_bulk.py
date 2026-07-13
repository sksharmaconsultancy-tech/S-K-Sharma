"""Statutory bulk file generators — Iter 70.

Two portal-ready files produced from a compliance salary run:

  1. **PF ECR (Electronic Challan cum Return)** — text file the employer
     uploads on the EPFO Unified Portal each month.  Layout is 11
     hash-separated fields per employee, one row per line, no header.

     Field order (as documented by EPFO):
       1  UAN                 (12 digits, mandatory)
       2  MEMBER_NAME         (upper-case, no #)
       3  GROSS_WAGES         (statutory gross for the month)
       4  EPF_WAGES           (capped at Rs 15,000 unless voluntary)
       5  EPS_WAGES           (capped at Rs 15,000)
       6  EDLI_WAGES          (capped at Rs 15,000)
       7  EPF_CONTRIBUTION    (12% of EPF_WAGES)
       8  EPS_CONTRIBUTION    (employer 8.33% of EPS_WAGES)
       9  EPF_EPS_DIFF        (employer diff — EPF_EMPLOYER - EPS_EMPLOYER)
       10 NCP_DAYS            (non-contributory / LOP days for the month)
       11 REFUND_ADVANCES     (usually 0 unless a specific case applies)

  2. **ESIC MC (Monthly Contribution) CSV** — the ESIC Insurance Portal
     accepts a CSV with 6 columns and no header rows: IP number,
     employee name, days worked in the wage period, monthly wages,
     reason code (7 = "leave", "0" if regular), and last working day if
     the IP has exited.  This module keeps things minimal — regular
     employees only, blank exit date, reason code = 0.

Both builders take the enriched ``rows`` list produced by
``compliance_salary._compute_row_for_user()``.  No DB access.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List

_PF_CAP = 15000  # Rs — statutory EPF wage ceiling.


def _clean_name(name: str) -> str:
    """EPFO ECR names must be ASCII upper-case and cannot contain '#'."""
    if not name:
        return ""
    s = "".join(ch for ch in str(name) if ord(ch) < 128)
    s = s.replace("#", " ").strip().upper()
    return " ".join(s.split())


def _to_int_rupees(v: Any) -> int:
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def build_pf_ecr_txt(rows: List[Dict[str, Any]]) -> bytes:
    """Return the PF ECR file bytes (no header, LF-terminated lines).

    Rows without a UAN or with ``pf_applicable=False`` are skipped —
    they are not part of the EPFO filing for the month.
    """
    lines: List[str] = []
    for r in rows:
        if not r.get("pf_applicable"):
            continue
        uan = (str(r.get("uan_no") or "")).strip()
        if not uan or not uan.isdigit() or len(uan) < 12:
            # ECR schema mandates a 12-digit UAN.  Employees without a
            # UAN are traditionally filed manually — skip in bulk.
            continue
        name = _clean_name(r.get("name") or "")
        gross = _to_int_rupees(r.get("gross_paid") or r.get("monthly_gross"))
        pf_wages = min(_to_int_rupees(r.get("pf_wages")), _PF_CAP)
        eps_wages = pf_wages
        edli_wages = pf_wages
        epf_contrib = _to_int_rupees(r.get("pf_employee"))
        eps_contrib = _to_int_rupees(r.get("pf_employer_eps"))
        # EPFO expects the employer's EPF contribution net of the EPS
        # portion (i.e. the "EPF_EPS_DIFF" column).  If the compliance
        # engine stored the total employer contribution separately we
        # compute the diff on the fly.
        empr_epf = _to_int_rupees(r.get("pf_employer_epf"))
        epf_eps_diff = max(empr_epf, 0)
        ncp_days = _to_int_rupees(
            (r.get("month_days") or 0)
            - (r.get("present_days") or 0)
            - 0.5 * (r.get("half_days") or 0)
        )
        refund_adv = 0
        lines.append(
            "#".join(
                str(x)
                for x in [
                    uan, name, gross, pf_wages, eps_wages, edli_wages,
                    epf_contrib, eps_contrib, epf_eps_diff,
                    max(ncp_days, 0), refund_adv,
                ]
            )
        )
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


# --------------------------------------------------------------------------- 
# ESIC CSV — Monthly Contribution + IP Registration
# --------------------------------------------------------------------------- 
ESIC_MC_COLUMNS = [
    "IP Number", "IP Name", "No of Days for which wages paid/payable",
    "Total Monthly Wages", "Reason Code for Zero workings days (numeric only)",
    "Last Working Day",
]

# ESIC IP registration CSV — used to on-board new insured persons.
# The portal expects a fixed 17-column layout; the schema below is the
# most recent one published on the ESIC Employers Portal (v2 template).
ESIC_IP_REG_COLUMNS = [
    "Employee's Name",
    "Relationship with Employee",
    "Relationship Name",
    "Date of Birth (DD/MM/YYYY)",
    "Gender",
    "Marital Status",
    "Aadhaar Number",
    "PAN",
    "Mobile Number",
    "Nominee's Name",
    "Relationship with Nominee",
    "Nominee's DOB (DD/MM/YYYY)",
    "Present Address",
    "Permanent Address",
    "Date of Appointment (DD/MM/YYYY)",
    "Monthly Wages",
    "Bank IFSC",
]


def build_esic_mc_csv(rows: List[Dict[str, Any]]) -> bytes:
    """ESIC monthly contribution CSV.

    Rows are filtered to ``esic_applicable=True`` and must carry an ESI
    IP number.  ``No of Days`` = present + 0.5×half days rounded down;
    ``Reason Code`` = 0 unless zero days worked (7 = leave).
    """
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    w.writerow(ESIC_MC_COLUMNS)
    for r in rows:
        if not r.get("esic_applicable"):
            continue
        ip_no = (str(r.get("esi_ip_no") or "")).strip()
        if not ip_no:
            continue
        days = int(
            (r.get("present_days") or 0) + 0.5 * (r.get("half_days") or 0)
        )
        wages = _to_int_rupees(
            r.get("esic_wage_base") or r.get("gross_paid") or r.get("monthly_gross")
        )
        reason_code = 0 if days > 0 else 7
        w.writerow([
            ip_no,
            _clean_name(r.get("name") or ""),
            days,
            wages,
            reason_code,
            "",   # Last working day — blank unless the IP has exited
        ])
    return buf.getvalue().encode("utf-8")


def build_esic_ip_reg_csv(rows: List[Dict[str, Any]]) -> bytes:
    """ESIC insured-person registration CSV (v2 template).

    Fills what the payroll master knows (name, DOB, gender, PAN, mobile,
    address, DOJ, wage, bank IFSC).  Unknown / not-in-master fields
    are left blank so the operator can complete them on the portal.
    """
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    w.writerow(ESIC_IP_REG_COLUMNS)
    for r in rows:
        # Only include rows that don't yet have an IP number — those
        # are the ones needing registration.
        if (str(r.get("esi_ip_no") or "")).strip():
            continue
        if not r.get("esic_applicable"):
            continue
        dob = r.get("dob") or ""
        doj = r.get("doj") or ""
        # ISO → DD/MM/YYYY for the ESIC portal expectations.
        def _fmt(d: str) -> str:
            try:
                y, m, dd = d.split("-")
                return f"{dd}/{m}/{y}"
            except Exception:
                return ""
        w.writerow([
            _clean_name(r.get("name") or ""),
            (r.get("relation") or "Father"),
            _clean_name(r.get("father_name") or ""),
            _fmt(dob),
            (r.get("gender") or "").capitalize() or "Male",
            (r.get("marital_status") or "Unmarried"),
            (str(r.get("aadhaar_no") or "")),
            (str(r.get("pan_no") or "")),
            (str(r.get("phone") or "")).replace("+91", "").strip(),
            _clean_name(r.get("nominee_name") or r.get("father_name") or ""),
            (r.get("nominee_relation") or "Father"),
            _fmt(r.get("nominee_dob") or dob),
            (r.get("present_address") or r.get("address") or ""),
            (r.get("permanent_address") or r.get("address") or ""),
            _fmt(doj),
            _to_int_rupees(r.get("monthly_gross") or r.get("gross_paid")),
            (r.get("bank_ifsc") or ""),
        ])
    return buf.getvalue().encode("utf-8")
