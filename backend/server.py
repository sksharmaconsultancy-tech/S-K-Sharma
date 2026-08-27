"""LabourLawConnect - Backend API
Employee attendance, leaves, payroll, compliance, tickets, notifications.
Auth: Emergent-managed Google OAuth (session tokens).
"""
from fastapi import FastAPI, APIRouter, HTTPException, Header, Query, Body, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Optional, Literal, Tuple, Dict, Any
from pathlib import Path
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field
import os
import uuid
import logging
import math
import httpx
import bcrypt as _bcrypt
import secrets as _secrets
from pymongo.errors import DuplicateKeyError
import re
import csv
import io
import base64
import json
import time as _time_mod
import asyncio

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# Iter 399 — pure date/payroll-month helpers live in shared/dates.py.
from shared.dates import (  # noqa: E402
    _employee_inactive_for_report,  # noqa: F401
    _last_completed_month,  # noqa: F401
    _month_is_after_exit,  # noqa: F401
    _month_is_before_doj,  # noqa: F401
    _month_is_complete,  # noqa: F401
    _parse_any_date,  # noqa: F401
    _payslip_is_processed,  # noqa: F401
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("labourlaw")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="S.K. Sharma & Co. API")
api = APIRouter(prefix="/api")


# Iter 64 — Root-level (non-/api) health probe. Emergent's Kubernetes
# probes may hit the pod directly on the container port before the ingress
# rewrites, so expose "/health" both at the /api prefix and at the root.
@app.get("/health")
async def _root_health():
    return {"status": "ok"}


@app.get("/healthz")
async def _root_healthz():
    return {"status": "ok"}


EMERGENT_SESSION_DATA_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
# SEC-004 — Session lifetime: sessions expire after 12 hours of INACTIVITY.
# Every authenticated request slides the expiry forward another 12 hours
# (auto-extend while active), throttled to at most one DB write per
# 30 minutes per session to avoid write amplification.
SESSION_TTL_HOURS = 12
SESSION_SLIDE_THROTTLE_MINUTES = 30
# Iter 295 (user request: "do not auto-logout employee PWA") — EMPLOYEE
# sessions live 90 days (sliding) so workers stay signed in on their
# phones between shifts. Admin/staff portals keep the strict 12-hour
# window (SEC-004).
EMPLOYEE_SESSION_TTL_HOURS = 24 * 90


def _session_ttl_hours_for_role(role: Optional[str]) -> int:
    return EMPLOYEE_SESSION_TTL_HOURS if role == "employee" else SESSION_TTL_HOURS

# Only these emails can hold the super_admin role.
SUPER_ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv(
        "SUPER_ADMIN_EMAILS", "sksharmaconsultancy@gmail.com"
    ).split(",")
    if e.strip()
}

# Optional phone numbers (E.164) that map to a super admin account.
SUPER_ADMIN_PHONES = {
    p.strip()
    for p in os.getenv(
        "SUPER_ADMIN_PHONES", "+919680273960"
    ).split(",")
    if p.strip()
}


def _normalise_phone(raw: str) -> str:
    """Normalise a phone number to +CC...digits form. Assumes India if no +."""
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if not digits.startswith("+"):
        # Bare 10-digit numbers → assume India
        d = "".join(ch for ch in digits if ch.isdigit())
        if len(d) == 10:
            return f"+91{d}"
        if len(d) == 12 and d.startswith("91"):
            return f"+{d}"
        return f"+{d}"
    return digits


def _resolve_role_on_signup(email: str) -> str:
    return "super_admin" if email.lower() in SUPER_ADMIN_EMAILS else "employee"

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
Role = Literal["employee", "company_admin", "super_admin", "sub_admin"]


class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    role: Role = "employee"
    company_id: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    employee_code: Optional[str] = None
    created_at: str


class Company(BaseModel):
    company_id: str = Field(default_factory=lambda: f"cmp_{uuid.uuid4().hex[:10]}")
    company_code: str = Field(default_factory=lambda: uuid.uuid4().hex[:6].upper())
    name: str
    address: Optional[str] = None
    office_lat: float
    office_lng: float
    geofence_radius_m: int = 200
    compliance_enabled: bool = True
    # Business classification (dropdown-driven) — see BUSINESS_CATEGORIES.
    # `business_category` holds the top-level key (e.g. "industry", "hospital").
    # `business_subcategory` is only set when the parent category has sub-types
    # (currently: "industry" → Textile / Food / Polybag / etc.).
    business_category: Optional[str] = None
    business_subcategory: Optional[str] = None
    # Attendance policy tuned to the firm's business type. Auto-attached from
    # ATTENDANCE_POLICY_PRESETS on creation (based on business_category); can
    # be overridden per-company by the Company Admin or Super Admin from the
    # "Attendance Policy" screen.
    attendance_policy: Optional[dict] = None
    # If true (default), every AUTO punch (fired by the geofence enter/exit
    # background trigger) is created with status="pending" and shown to admins
    # under "Attendance approvals". Manual punches always land as "approved".
    punch_approval_required: bool = True
    # When True (default), the client is expected to fire background
    # `geofence-auto` punches on enter/exit and hide the manual "Punch"
    # button on the Attendance tab. When False, the auto-punch flow is
    # disabled and employees can tap the manual Punch In / Out button —
    # geofence + GPS-on are STILL enforced server-side. Individual
    # employees may override this via `users.auto_punch_enabled`
    # (None → inherit; True/False → force).
    auto_punch_enabled: bool = True
    # Iter 64 — Location-punching master switch. DEFAULTS TO FALSE (off).
    # When False, employees of this firm can punch WITHOUT GPS — they use
    # manual biometric (fingerprint + face selfie) only. When the Employer
    # explicitly enables this, individual employees still have to opt-in
    # via ``users.gps_punch_enabled`` (also default False) before GPS-based
    # punching is available to them. Auto-punch is implicitly disabled
    # when this flag is False, since background geofence needs GPS.
    location_punching_enabled: bool = True
    # Iter 64 — Strict-outside toggle. When True, IN-punches from OUTSIDE
    # the geofence are rejected outright (old behaviour). When False
    # (default), they are ALLOWED but flagged for admin approval, so
    # field employees / WFH staff can still close their shift.
    reject_outside_geofence: bool = True
    # Super-admin controlled soft-disable. When false, every user of this firm
    # is blocked from logging in and every device push is rejected — the data
    # itself is preserved so re-enabling instantly restores service.
    enabled: bool = True
    disabled_at: Optional[str] = None
    disabled_by: Optional[str] = None
    disabled_reason: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SessionExchange(BaseModel):
    session_id: str


class OtpRequest(BaseModel):
    identifier: str  # phone (E.164) or email
    channel: Literal["sms", "email"] = "sms"


class OtpVerify(BaseModel):
    identifier: str
    code: str
    channel: Literal["sms", "email"] = "sms"


class PinLoginRequest(BaseModel):
    # Employees can now log in with any of the following, all + PIN:
    #   • phone (preferred)
    #   • company_code + employee_code (legacy)
    #   • uan_no  (12-digit Universal Account Number for EPFO)
    #   • esi_ip_no  (ESIC Insurance Person number)
    #   • pf_no
    #   • login_id (username set by the employer)  [Iter 96l]
    company_code: Optional[str] = None
    employee_code: Optional[str] = None
    phone: Optional[str] = None
    uan_no: Optional[str] = None
    esi_ip_no: Optional[str] = None
    pf_no: Optional[str] = None
    login_id: Optional[str] = None
    pin: str


class EmployeeSignupRequest(BaseModel):
    phone: str
    pin: str
    company_code: str
    name: str
    # Iter 85 — Employee-provided proposed Employee Code (e.g. from their
    # offer letter). Employer approves the request on the admin panel and
    # can override this if it conflicts with an existing code.
    employee_code: Optional[str] = None
    father_name: Optional[str] = None
    dob: Optional[str] = None
    doj: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    salary_monthly: Optional[float] = None
    # Iter 68 — Two salary structures on the employee master.
    #  * ``compliance_gross`` → basis for the Compliance Salary Process
    #    (PF/ESIC/TDS/PT statutory calculations only).
    #  * ``salary_monthly``   → basis for the Actual/Base Salary Run.
    #  * ``salary_mode``      → per-employee payment cadence used to
    #    interpret biometric attendance ("daily" / "hourly" / "monthly").
    #  * ``actual_salary_allowances`` / ``actual_salary_deductions`` are
    #    reusable head amounts, e.g. ``[{"head": "Petrol", "amount": 500}]``.
    compliance_gross: Optional[float] = None
    salary_mode: Optional[str] = None  # "daily" | "hourly" | "monthly"
    actual_salary_allowances: Optional[List[Dict[str, Any]]] = None
    actual_salary_deductions: Optional[List[Dict[str, Any]]] = None
    half_day_hrs: Optional[float] = None
    full_day_hrs: Optional[float] = None
    email: Optional[str] = None
    address: Optional[str] = None


class EmployeePolicy(BaseModel):
    """Employer-defined salary/attendance policy for a single employee.
    All fields are optional so partial updates are safe."""
    salary: Optional[float] = None
    # Payment cadence: how the employee is remunerated.
    #  • "monthly" — fixed salary regardless of days (default; existing behaviour)
    #  • "daily"   — salary per present day (salary field ≡ daily rate)
    #  • "hourly"  — salary per duty-hour (salary field ≡ hourly rate)
    # Payroll picks up this field to decide how to compute the pay-run.
    salary_mode: Optional[Literal["monthly", "daily", "hourly"]] = None
    # Tiered attendance bonuses: `salary_N` is unlocked when
    # present_days >= `day_N`. Multiple tiers stack cumulatively.
    salary_1: Optional[float] = None
    day_1: Optional[int] = None
    salary_2: Optional[float] = None
    day_2: Optional[int] = None
    salary_3: Optional[float] = None
    day_3: Optional[int] = None
    shift_name: Optional[str] = None
    shift_dummy: Optional[str] = None
    dummy_weekly_off: Optional[int] = None  # 0=Sun..6=Sat
    working_hours: Optional[float] = None
    full_day_salary: Optional[bool] = None
    ot_allow: Optional[bool] = None
    fullday_hours: Optional[float] = None
    halfday_hours: Optional[float] = None
    cl_days: Optional[int] = None
    pl_days: Optional[int] = None
    weekly_off: Optional[int] = None  # 0=Sun..6=Sat
    week_off_min_hours: Optional[float] = None
    bio_code: Optional[str] = None
    weekly_off_attendance: Optional[bool] = None
    # Iter 85 — Compliance salary block (parallel to actual salary above).
    # * ``compliance_gross`` — monthly compliance CTC/gross figure for
    #   this employee. Independent of ``salary`` (actual pay).
    # * ``compliance_structure_source`` — "firm" (inherit percentages
    #   from the firm's compliance policy) or "custom" (use the values
    #   below stored on the employee).
    # * ``compliance_basic_pct`` .. ``compliance_others_pct`` — custom
    #   percentages when source == "custom".
    # * ``compliance_basic_amt`` .. ``compliance_others_amt`` — flat
    #   amounts entered directly (used when the firm disables percent
    #   bifurcation via ``allow_percent_bifurcation=False``).
    compliance_gross: Optional[float] = None
    compliance_structure_source: Optional[Literal["firm", "custom"]] = None
    compliance_basic_pct: Optional[float] = None
    compliance_hra_pct: Optional[float] = None
    compliance_conveyance_pct: Optional[float] = None
    compliance_medical_pct: Optional[float] = None
    compliance_special_pct: Optional[float] = None
    compliance_others_pct: Optional[float] = None
    compliance_basic_amt: Optional[float] = None
    compliance_hra_amt: Optional[float] = None
    compliance_conveyance_amt: Optional[float] = None
    compliance_medical_amt: Optional[float] = None
    compliance_special_amt: Optional[float] = None
    compliance_others_amt: Optional[float] = None


class PinChangeRequest(BaseModel):
    current_pin: str
    new_pin: str


class AdminPinResetRequest(BaseModel):
    user_id: str
    new_pin: Optional[str] = None  # if None, generate random 6-digit


class AdminPinLoginRequest(BaseModel):
    identifier: Optional[str] = None  # email or phone (legacy path)
    company_code: Optional[str] = None  # NEW — companies can also log in with their firm code
    pin: str


class AttendancePunch(BaseModel):
    kind: Literal["in", "out"]
    # Latitude/Longitude are OPTIONAL. When an employee has auto-punch
    # disabled (i.e. they operate in "manual biometric mode"), they may
    # punch without GPS — the app will send lat/lng = None and the server
    # will skip the geofence check. Face-match & fingerprint still apply.
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    biometric_method: Literal["fingerprint", "face"]
    selfie_base64: Optional[str] = None
    device_info: Optional[str] = None
    # Iter 602 — SECURE FACE PUNCH: id of a server-side verification
    # session (WebAuthn device auth + liveness + anti-spoof + 1:1 face
    # match). Required when the firm enables secure_face_punch_enabled.
    verification_session_id: Optional[str] = None
    # How the punch was triggered: "manual" (default), "manual-nogps"
    # (manual biometric punch with GPS turned off — audit-flagged),
    # "geofence-auto" (foreground/background geofence transition), or
    # "admin_approved" (created by the employer on the employee's behalf).
    source: Optional[
        Literal["manual", "manual-nogps", "geofence-auto", "admin_approved"]
    ] = "manual"
    # Iter 176 — guided punch workflow: worksite the employee selected
    # (main office or a branch). Stored on the record for reports.
    worksite_id: Optional[str] = None
    worksite_name: Optional[str] = None
    # Geofence-policy fields (Phase 1 — mode-driven punch).
    # reason: required for Flexible-outside / Emergency punches.
    reason: Optional[str] = None
    # Client-reported GPS accuracy in metres (for accuracy-threshold checks).
    gps_accuracy_m: Optional[float] = None
    # Optional device battery level 0-100 (audit only).
    battery_level: Optional[int] = None
    # Client hint that the OS reported a mock/fake location (fake-GPS check).
    mock_location: Optional[bool] = None
    # Optional extra photo for Emergency mode.
    photo_base64: Optional[str] = None
    # Offline sync (Phase 2): idempotency id + original capture time so a
    # queued offline punch keeps its real time and never duplicates on retry.
    offline: Optional[bool] = None
    client_dedupe_id: Optional[str] = None
    client_punch_at: Optional[str] = None


class LocationPing(BaseModel):
    """Employee's periodic location ping used by the "present but not
    punched" employer report. Stored on the user document, not in a log."""
    latitude: float
    longitude: float


class AdminApprovePunch(BaseModel):
    """Employer creates a punch on behalf of an employee whose location is
    inside the office geofence but who hasn't punched themselves."""
    user_id: str
    kind: Literal["in", "out"]
    note: Optional[str] = None


class LeaveCreate(BaseModel):
    leave_type: Literal["casual", "sick", "earned", "unpaid"]
    from_date: str
    to_date: str
    reason: str


class LeaveDecision(BaseModel):
    status: Literal["approved", "rejected"]
    comment: Optional[str] = None
    # Iter 206 — approve the leave adjusting it against the employee's
    # Comp-Off balance (creates a 'use' entry in comp_off_ledger).
    use_comp_off: Optional[bool] = False


class TicketAttachment(BaseModel):
    """Base64-encoded PDF or JPEG image attached to a ticket. Size and
    mime type are validated server-side to prevent abuse."""
    name: str
    mime: Literal["application/pdf", "image/jpeg", "image/jpg", "image/png"]
    data_base64: str  # raw base64 (no `data:...;base64,` prefix — stripped client-side)


class TicketCreate(BaseModel):
    category: Literal["hr", "payroll", "compliance", "it", "other"]
    subject: str
    description: str
    attachments: Optional[List[TicketAttachment]] = None


class TicketUpdate(BaseModel):
    status: Literal["open", "in_progress", "resolved", "closed"]
    admin_reply: Optional[str] = None


class PayslipCreate(BaseModel):
    employee_user_id: str
    month: str  # e.g. "2026-04"
    gross: float
    deductions: float
    net: float
    pdf_base64: Optional[str] = None


class ComplianceDocCreate(BaseModel):
    title: str
    category: Literal["pf", "esi", "gratuity", "minimum_wage", "policy", "other"]
    description: str
    content: Optional[str] = None
    pdf_base64: Optional[str] = None


class NotificationCreate(BaseModel):
    title: str
    body: str
    audience: Literal["all", "employees", "admins"] = "all"
    company_id: Optional[str] = None  # super_admin can target a company; None = all


class CompanyCreate(BaseModel):
    name: str
    address: Optional[str] = None
    office_lat: float
    office_lng: float
    geofence_radius_m: int = 200
    compliance_enabled: bool = True
    company_code: Optional[str] = None  # firm prefix used for employee codes
    business_category: Optional[str] = None
    business_subcategory: Optional[str] = None
    # Optional: create a company_admin login in one shot (Path B).
    # If admin_phone is provided, a company_admin user will be provisioned
    # with a random temp PIN (returned in the response) and pin_must_change=true.
    admin_phone: Optional[str] = None
    admin_name: Optional[str] = None
    admin_email: Optional[str] = None


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    office_lat: Optional[float] = None
    office_lng: Optional[float] = None
    geofence_radius_m: Optional[int] = None
    compliance_enabled: Optional[bool] = None
    company_code: Optional[str] = None  # firm prefix used when generating employee codes
    business_category: Optional[str] = None
    business_subcategory: Optional[str] = None
    punch_approval_required: Optional[bool] = None
    auto_punch_enabled: Optional[bool] = None
    location_punching_enabled: Optional[bool] = None
    reject_outside_geofence: Optional[bool] = None
    # Firm Master switch — when True, the employee PWA may queue punches
    # offline (IndexedDB) and sync them when back online.
    offline_geofence_enabled: Optional[bool] = None


class KycUpdate(BaseModel):
    """Employee self-service KYC update. All fields optional; blank strings clear."""
    aadhar_number: Optional[str] = None
    name_as_per_aadhar: Optional[str] = None
    pan_number: Optional[str] = None
    name_as_per_pan: Optional[str] = None
    dl_number: Optional[str] = None
    # Bank details
    bank_account_number: Optional[str] = None
    bank_name: Optional[str] = None
    pay_mode: Optional[str] = None
    ifsc_code: Optional[str] = None
    name_as_per_bank: Optional[str] = None


class FamilyMember(BaseModel):
    """One member in an employee's declared family. All fields optional
    except `name` — the UI validates at least name + relation before
    accepting a row."""
    name: str
    relation: Optional[str] = None
    dob: Optional[str] = None  # YYYY-MM-DD (optional)
    occupation: Optional[str] = None
    contact: Optional[str] = None
    # Iter 271 (user request) — per-member Aadhaar No. + Nominee tick.
    aadhaar_no: Optional[str] = None
    is_nominee: Optional[bool] = None
    aadhaar_no: Optional[str] = None  # Iter 151 — captured via Aadhaar OCR scan
    scan_doc_id: Optional[str] = None  # Iter 151b — stored scan copy reference


class ProfileEditRequest(BaseModel):
    """Employee-submitted profile change request. Company admin must
    approve before the values become live on the user record.

    Editable fields: Name, Father Name, DOB, DOJ, Designation, Present
    Address, Permanent Address, Family Members. At least one must be
    present (checked via delta after normalization).
    """
    name: Optional[str] = None
    father_name: Optional[str] = None
    dob: Optional[str] = None
    doj: Optional[str] = None
    designation: Optional[str] = None
    present_address: Optional[str] = None
    permanent_address: Optional[str] = None
    family_members: Optional[List[FamilyMember]] = None
    note: Optional[str] = None


class ProfileEditReview(BaseModel):
    status: Literal["approved", "rejected"]
    review_note: Optional[str] = None


class RoleUpdate(BaseModel):
    user_id: str
    role: Optional[Role] = None
    company_id: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    employee_code: Optional[str] = None
    name: Optional[str] = None
    father_name: Optional[str] = None
    dob: Optional[str] = None
    doj: Optional[str] = None
    designation: Optional[str] = None
    present_address: Optional[str] = None
    permanent_address: Optional[str] = None
    family_members: Optional[List[FamilyMember]] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    salary_monthly: Optional[float] = None
    half_day_hrs: Optional[float] = None
    full_day_hrs: Optional[float] = None
    exit_date: Optional[str] = None  # YYYY-MM-DD; empty string = clear
    # Iter 207 — per-employee Weekly Off days (0=Mon .. 6=Sun); None/[] =
    # follow firm policy. Used when firm Weekly Off is N/A.
    weekly_off_days_override: Optional[List[int]] = None
    # Resort / hospitality use-case: live-in staff are always physically
    # inside the premises so geofence-based auto-punch does not apply.
    # When True: (1) OUT punches from outside the fence are accepted
    # without an open-IN check, (2) auto-punch is disabled client-side,
    # (3) supervisor uses the daily roster to mark absences.
    is_live_in: Optional[bool] = None
    # Per-employee override for the company's `auto_punch_enabled` setting.
    # None → inherit company. True → force auto-punch on. False → force off
    # (this employee must punch manually, useful e.g. for supervisors).
    auto_punch_enabled: Optional[bool] = None
    # Iter 64 — Per-employee GPS punching opt-in. DEFAULT FALSE. Only when
    # explicitly True (AND the firm allows GPS via
    # ``companies.location_punching_enabled``) can this employee punch
    # using GPS/geofence. Otherwise they must use manual biometric
    # (fingerprint + face selfie). Optional on the update model so that
    # partial patches do not accidentally clobber the existing value.
    gps_punch_enabled: Optional[bool] = None
    # ---- Textile industry per-employee flags ----
    # Name of a shift from `attendance_policy.shifts` assigned to this
    # employee (e.g. "Day 7-7", "Night 8-8"). Purely informational for
    # now — used by the Employee Master PDF and future payroll logic.
    shift_preset_name: Optional[str] = None
    # Iter 215 — report-only Dummy Shift (fixed master list; requires the
    # firm policy flag dummy_shift_allowed). Used ONLY by the Dummy Shift
    # Report in Labour Law Reports.
    dummy_shift: Optional[str] = None
    # Policy 1: Overtime Applicable for this employee. When False, extra
    # hours beyond the shift are NOT counted as OT (still tracked but
    # payroll treats them as un-billed).
    ot_applicable: Optional[bool] = None
    # Policy 1: When True AND the employee worked on the company's
    # `weekly_off_days`, they get Full-Day Payment for that day.
    week_off_full_day: Optional[bool] = None
    # Policy 2: When True AND the employee worked on a week-off/govt
    # holiday, NO present day is credited — all duty hours become OT.
    week_off_govt_holiday_enabled: Optional[bool] = None

    # ---- Employee grouping / rolling ----
    # Free-form category label for grouping / filtering: "Staff", "Labour",
    # "Contractor", etc. Employer builds the vocabulary organically — the
    # /admin/employee-types endpoint returns the distinct list already in
    # use for autocomplete. Empty string clears.
    employee_type: Optional[str] = None
    # Iter 91 — "Employee Type" and "Group" are the SAME concept per user
    # direction. Either key may be sent; both users.employee_type and
    # users.employee_group are written with the same value.
    employee_group: Optional[str] = None
    # On-roll (payroll employee) vs Off-roll (contract / agency-deployed).
    # Purely for reporting / filtering — does not block punch or auth.
    is_onroll: Optional[bool] = None
    # Iter 200 (user request) — per-employee "Offline Salary: Yes/No".
    # False → excluded from offline/off-roll salary runs. Only settable
    # when the firm's Offline Salary is enabled in Firm Master.
    offline_salary_enabled: Optional[bool] = None
    # Iter 165 — admin-controlled fingerprint verification requirement
    # (Employee PWA). Only settable when the firm's Bio Matrix Attendance
    # is enabled in Firm Master.
    fingerprint_required: Optional[bool] = None
    # Iter 175 — Contractual employee (Firm Master Policy 2 contractors).
    # When is_contractual=True the employee is linked to one of the firm's
    # contractors (firm_masters.contractors) by name.
    is_contractual: Optional[bool] = None
    contractor_name: Optional[str] = None
    # Standing advance / salary loan balance for this employee. Deducted
    # from monthly gross by the Salary Process. Employer decreases the
    # balance on each pay-cycle to reflect repayment.
    advance_balance: Optional[float] = None

    # ---- Compliance Salary Process (statutory) ----
    # Per-employee overrides for the compliance run. All are optional;
    # missing values fall back to company/default policy.
    pf_applicable: Optional[bool] = None
    esic_applicable: Optional[bool] = None
    # Salary structure per employee — either explicit ₹ or as % of gross.
    basic_amount: Optional[float] = None
    hra_amount: Optional[float] = None
    conv_amount: Optional[float] = None
    medical_amount: Optional[float] = None
    special_amount: Optional[float] = None
    others_amount: Optional[float] = None
    # Professional Tax
    pt_state: Optional[str] = None
    pt_amount_override: Optional[float] = None
    # Manual monthly TDS in ₹.
    tds_amount: Optional[float] = None


class OnboardingSubmit(BaseModel):
    company_code: str
    name: str
    father_name: str
    dob: str  # YYYY-MM-DD
    doj: str  # YYYY-MM-DD
    shift_start: str  # HH:MM
    shift_end: str  # HH:MM
    salary_monthly: float
    half_day_hrs: float
    full_day_hrs: float


class CompanyRequestSubmit(BaseModel):
    contact_name: str
    contact_mobile: str
    contact_email: Optional[str] = None
    company_name: str
    address: Optional[str] = None
    employee_count: Optional[int] = None
    services_needed: Optional[str] = None
    notes: Optional[str] = None
    business_category: Optional[str] = None
    business_subcategory: Optional[str] = None


class CompanySelfRegister(BaseModel):
    """Employer self-registration — creates a pending company_request
    that carries the intended admin login (mobile + PIN). On approval by
    the super admin, both the Company AND the company_admin User are
    provisioned atomically.
    """
    company_name: str
    address: str
    city: str
    state: str
    contact_name: str  # Owner name
    contact_mobile: str
    contact_email: str
    nature_of_business: str
    business_category: Optional[str] = None
    business_subcategory: Optional[str] = None
    pin: str
    office_lat: Optional[float] = None
    office_lng: Optional[float] = None
    geofence_radius_m: Optional[int] = 200
    employee_count: Optional[int] = None
    notes: Optional[str] = None
    # Iter 89 — Optional firm logo captured at registration. Stored on
    # the company_request until approval, then mirrored to
    # ``companies.logo_base64`` + firm_masters.logo.
    logo_base64: Optional[str] = None
    logo_mime: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Business classification taxonomy shown in the "Firm Master" dropdown on both
# the super-admin "Create Company" screen and the employer self-registration
# screen. Extend BUSINESS_CATEGORIES freely — the public endpoint below serves
# whatever is defined here to both mobile and web clients.
BUSINESS_CATEGORIES: List[dict] = [
    {"key": "hospital", "label": "Hospital", "subcategories": []},
    {"key": "hotel_resort", "label": "Hotel / Resort", "subcategories": []},
    {
        "key": "industry",
        "label": "Industry",
        "subcategories": [
            "Textile",
            "Food & Beverage",
            "Polybag / Plastics",
            "Engineering",
            "Automobile Components",
            "Chemical",
            "Pharmaceutical",
            "Steel & Metal",
            "Cement",
            "Electronics & Electrical",
            "Paper & Packaging",
            "Leather",
            "Rubber",
            "Furniture / Wood",
            "Fertilizer",
            "Gems & Jewellery",
            "Printing & Publishing",
            "Ceramics & Tiles",
            "Glass",
            "Agro / Dairy",
            "Mining & Minerals",
            "Oil & Gas",
            "Marine / Seafood",
            "Handicrafts",
            "Other Industry",
        ],
    },
    {"key": "service_provider", "label": "Service Provider", "subcategories": []},
    {"key": "it_company", "label": "IT Company", "subcategories": []},
    {"key": "construction", "label": "Construction Company", "subcategories": []},
    {"key": "school", "label": "School / Education", "subcategories": []},
    {"key": "automobile", "label": "Automobile", "subcategories": []},
    {"key": "other", "label": "Other", "subcategories": []},
]

_BUSINESS_CATEGORY_MAP = {c["key"]: c for c in BUSINESS_CATEGORIES}


# ---------------------------------------------------------------------------
# Attendance Policy — per-firm settings tuned to the business type.
# Presets are auto-attached to a Company on creation (based on
# business_category); the Company Admin / Super Admin can override any of the
# fields from the "Attendance Policy" screen later.
# ---------------------------------------------------------------------------
# weekday_off uses 0=Mon ... 6=Sun (Python's weekday() convention)
_DEFAULT_POLICY: dict = {
    "shifts": [
        {"name": "General", "start": "09:00", "end": "18:00"},
    ],
    "weekly_off_days": [6],  # Sunday
    "grace_minutes_late": 10,
    "half_day_hours": 4.0,
    "full_day_hours": 8.0,
    "break_hours": 1.0,
    "overtime_threshold_hours": 9.0,
    "overtime_multiplier": 1.5,
    "night_shift_allowance_enabled": False,
    "night_shift_start": "22:00",
    "night_shift_end": "06:00",
    "notes": "",
}


def _pol(**overrides) -> dict:
    """Small helper to build a preset by overriding only the fields that
    differ from _DEFAULT_POLICY. Keeps the presets table below readable."""
    p = json.loads(json.dumps(_DEFAULT_POLICY))
    for k, v in overrides.items():
        p[k] = v
    return p


ATTENDANCE_POLICY_PRESETS: dict = {
    # Hospital — rotational shifts round the clock, no fixed weekly off,
    # night allowance enabled, OT after full 9 hrs at 1.5x.
    "hospital": _pol(
        shifts=[
            {"name": "Morning", "start": "07:00", "end": "15:00"},
            {"name": "Evening", "start": "15:00", "end": "23:00"},
            {"name": "Night",   "start": "23:00", "end": "07:00"},
        ],
        weekly_off_days=[],
        grace_minutes_late=5,
        half_day_hours=4.0,
        full_day_hours=8.0,
        break_hours=0.5,
        overtime_threshold_hours=8.0,
        overtime_multiplier=1.5,
        night_shift_allowance_enabled=True,
        notes="24×7 rotational — no fixed weekly off, night allowance paid.",
    ),
    # Hotel / Resort — hospitality, 3 shifts, no fixed weekly off, staff get
    # a compensatory off during the week; night allowance for overnight desk.
    "hotel_resort": _pol(
        shifts=[
            {"name": "Morning", "start": "07:00", "end": "15:00"},
            {"name": "Evening", "start": "15:00", "end": "23:00"},
            {"name": "Night",   "start": "23:00", "end": "07:00"},
        ],
        weekly_off_days=[],
        grace_minutes_late=10,
        half_day_hours=4.0,
        full_day_hours=8.0,
        break_hours=1.0,
        overtime_threshold_hours=9.0,
        overtime_multiplier=1.5,
        night_shift_allowance_enabled=True,
        notes="Rotational weekly-off — one compensatory day off per week.",
    ),
    # Industry (manufacturing) — 3 shifts, 6-day week (Sunday off), 1-hour
    # unpaid lunch, OT after 8 hrs at 2x per Factories Act practice.
    "industry": _pol(
        shifts=[
            {"name": "Shift A", "start": "06:00", "end": "14:00"},
            {"name": "Shift B", "start": "14:00", "end": "22:00"},
            {"name": "Shift C", "start": "22:00", "end": "06:00"},
        ],
        weekly_off_days=[6],
        grace_minutes_late=10,
        half_day_hours=4.0,
        full_day_hours=8.0,
        break_hours=1.0,
        overtime_threshold_hours=8.0,
        overtime_multiplier=2.0,
        night_shift_allowance_enabled=True,
        notes="Factories-Act aligned — OT paid at 2× beyond 8 hrs / day.",
    ),
    # Service Provider — 9-5 general shift, Sunday off, standard OT.
    "service_provider": _pol(
        shifts=[{"name": "General", "start": "09:30", "end": "18:30"}],
        weekly_off_days=[6],
        grace_minutes_late=15,
        overtime_threshold_hours=9.0,
        overtime_multiplier=1.5,
    ),
    # IT Company — 2-day weekend (Sat & Sun off), generous grace, OT rare.
    "it_company": _pol(
        shifts=[{"name": "General", "start": "10:00", "end": "19:00"}],
        weekly_off_days=[5, 6],
        grace_minutes_late=30,
        half_day_hours=4.0,
        full_day_hours=8.0,
        break_hours=1.0,
        overtime_threshold_hours=9.0,
        overtime_multiplier=1.0,
        notes="OT accounted only when explicitly approved.",
    ),
    # Construction — site work, no fixed weekly off, OT at 2× after 8 hrs.
    "construction": _pol(
        shifts=[{"name": "Day Shift", "start": "08:00", "end": "17:00"}],
        weekly_off_days=[],
        grace_minutes_late=15,
        half_day_hours=4.0,
        full_day_hours=8.0,
        break_hours=1.0,
        overtime_threshold_hours=8.0,
        overtime_multiplier=2.0,
        notes="Rotational off — one day compensatory per week.",
    ),
    # School — 6-hour teaching day, Sunday off, no OT (typically fixed pay).
    "school": _pol(
        shifts=[{"name": "School Hours", "start": "08:00", "end": "14:30"}],
        weekly_off_days=[6],
        grace_minutes_late=10,
        half_day_hours=3.0,
        full_day_hours=6.0,
        break_hours=0.5,
        overtime_threshold_hours=6.0,
        overtime_multiplier=1.0,
        notes="Fixed teaching hours — extra classes claimed separately.",
    ),
    # Automobile (workshop / dealership) — Sunday off, OT at 1.5× after 8 hrs.
    "automobile": _pol(
        shifts=[{"name": "Workshop", "start": "09:00", "end": "18:00"}],
        weekly_off_days=[6],
        grace_minutes_late=10,
        half_day_hours=4.0,
        full_day_hours=8.0,
        break_hours=1.0,
        overtime_threshold_hours=8.0,
        overtime_multiplier=1.5,
    ),
    # Textile industry — 12-hr rotational shifts common, per-employee OT
    # applicability, per-employee week-off full-day-payment. Two policy
    # variants selectable per company:
    #   • policy_1: Hourly + Daily calc; 24-hr duty allowed for OT-enabled
    #     employees starting evening shift; week-off day work → Full Day
    #     Payment (if employer allows and employee is flagged).
    #   • policy_2: 8 hrs = 1 Present Day; extra → OT. If a week-off /
    #     govt-holiday-enabled employee works on their off day, none of
    #     the hours count as a present day — everything becomes OT.
    "textile": _pol(
        shifts=[
            {"name": "Day 7-7",   "start": "07:00", "end": "19:00"},  # 12h
            {"name": "Day 8-8",   "start": "08:00", "end": "20:00"},  # 12h
            {"name": "Night 7-7", "start": "19:00", "end": "07:00"},  # 12h
            {"name": "Night 8-8", "start": "20:00", "end": "08:00"},  # 12h
            {"name": "General 9-5", "start": "09:00", "end": "17:00"},  # 8h
        ],
        weekly_off_days=[6],
        grace_minutes_late=10,
        half_day_hours=4.0,
        full_day_hours=8.0,
        break_hours=1.0,
        overtime_threshold_hours=8.0,
        overtime_multiplier=1.5,
        night_shift_allowance_enabled=True,
        # Textile-specific extensions
        policy_variant="policy_1",
        duty_hours_rounding_minutes=15,
        standard_working_hours=8.0,
        week_off_full_day_payment_default=False,
        notes="Textile industry — 12-hr rotational shifts, per-employee OT & week-off flags.",
    ),
    # Iter 86 — STANDARD attendance policy for all NON-TEXTILE firms.
    #
    # Consolidates the industry-neutral rules requested by S.K. Sharma
    # & Co. so hospital / hotel / IT / school / automobile / service-
    # provider firms all share ONE predictable baseline instead of
    # subtly different presets. Firms can still override any field on
    # the Attendance Policy screen; textile firms continue to use their
    # dedicated preset (12-hr rotational shifts + policy_variant math).
    #
    # Rule summary (also surfaced via the /api/attendance/standard-policy
    # endpoint so the admin UI can pretty-print it):
    #   * Shift: 09:00 - 18:00 (9-hour window, 1-hour unpaid break)
    #   * Weekly off: Sunday (weekday index 6)
    #   * Grace on late arrival: 10 minutes
    #   * Half day  : duty hours < 4.0
    #   * Full day  : duty hours >= 8.0
    #   * OT threshold: any duty hour BEYOND 8.0 counts as OT
    #   * OT multiplier: 1.5x (Factories-Act aligned)
    #   * Duty-hour rounding: 15 minutes (matches textile roll-up
    #                                     so payroll reports agree)
    #   * Night-shift allowance: OFF by default
    #   * Week-off / holiday work: counted as a FULL DAY (contrast with
    #                              textile Policy 2 which treats it as
    #                              OT-only unless flagged)
    "standard": _pol(
        shifts=[{"name": "General 9-6", "start": "09:00", "end": "18:00"}],
        weekly_off_days=[6],
        grace_minutes_late=10,
        half_day_hours=4.0,
        full_day_hours=8.0,
        break_hours=1.0,
        overtime_threshold_hours=8.0,
        overtime_multiplier=1.5,
        night_shift_allowance_enabled=False,
        duty_hours_rounding_minutes=15,
        standard_working_hours=8.0,
        notes=(
            "Standard non-textile policy — 9-6 shift, Sunday off, OT at 1.5x "
            "beyond 8 duty hours (Factories-Act aligned). Half day < 4h, "
            "Full day >= 8h. Week-off / holiday work counts as Full Day."
        ),
    ),
    # Fallback / generic — aliases to "standard" for consistency.
    "other": _pol(
        shifts=[{"name": "General 9-6", "start": "09:00", "end": "18:00"}],
        weekly_off_days=[6],
        grace_minutes_late=10,
        half_day_hours=4.0,
        full_day_hours=8.0,
        break_hours=1.0,
        overtime_threshold_hours=8.0,
        overtime_multiplier=1.5,
        duty_hours_rounding_minutes=15,
        standard_working_hours=8.0,
        notes="Alias of the STANDARD non-textile policy.",
    ),
}


async def inject_firm_ot_flag(policy: dict, company_id: Optional[str]) -> dict:
    """Iter 142 — Read the Firm Master's ``salary_process.ot_allowed`` gate
    and stamp it onto the attendance-policy dict as ``firm_ot_allowed``.
    Missing Firm Master / unset flag = allowed (legacy behaviour)."""
    if not company_id or not isinstance(policy, dict):
        return policy
    try:
        fm = await db.firm_masters.find_one(
            {"company_id": company_id},
            {"_id": 0, "salary_process.ot_allowed": 1},
        ) or {}
        v = (fm.get("salary_process") or {}).get("ot_allowed")
        if v is not None:
            policy["firm_ot_allowed"] = bool(v)
    except Exception:
        pass
    return policy


def _policy_for_category(
    category: Optional[str], subcategory: Optional[str] = None
) -> dict:
    """Returns a deep-copy of the preset that best matches the given
    category/subcategory. Subcategory takes precedence when it maps to a
    known preset (e.g. subcategory='Textile' on category='industry' picks
    the textile preset with 5 shifts).

    Iter 86 - Any non-textile category that ISN'T explicitly modelled
    falls back to the STANDARD preset (not the loose _DEFAULT_POLICY)
    so firms without a bespoke preset still get the same predictable
    9-6 / Sunday-off / OT>=8h rule bundle.
    """
    sub_key = (subcategory or "").strip().lower()
    if sub_key and sub_key in ATTENDANCE_POLICY_PRESETS:
        return json.loads(json.dumps(ATTENDANCE_POLICY_PRESETS[sub_key]))
    key = (category or "").strip().lower()
    preset = (
        ATTENDANCE_POLICY_PRESETS.get(key)
        or ATTENDANCE_POLICY_PRESETS.get("standard")
        or ATTENDANCE_POLICY_PRESETS.get("other")
    )
    return json.loads(json.dumps(preset))


class Shift(BaseModel):
    name: str
    start: str  # HH:MM 24-hour
    end: str    # HH:MM 24-hour


class AttendancePolicy(BaseModel):
    """Firm-level attendance rules. Editable from the Attendance Policy screen.
    Values here are used purely for tracking (OT / late / half-day) — payroll
    remains monthly-salary based per current design."""
    shifts: List[Shift] = Field(default_factory=list)
    weekly_off_days: List[int] = Field(default_factory=list)  # 0=Mon..6=Sun
    grace_minutes_late: int = 10
    half_day_hours: float = 4.0
    full_day_hours: float = 8.0
    break_hours: float = 1.0
    overtime_threshold_hours: float = 9.0
    overtime_multiplier: float = 1.5
    night_shift_allowance_enabled: bool = False
    night_shift_start: str = "22:00"
    night_shift_end: str = "06:00"
    notes: Optional[str] = ""

    # ---- Textile industry extensions ----
    # policy_variant only used when business_category == "textile":
    #  • "policy_1" — Hourly + Daily basis calc; OT-enabled employees may
    #    do a 24-hr duty if first-in is in evening; week-off Full-Day
    #    Payment gated by per-employee flag.
    #  • "policy_2" — 8-hr day = 1 Present Day. Extras → OT. If a
    #    week-off/govt-holiday-enabled employee works on their off day,
    #    NONE of the hours count as a present day — everything is OT.
    policy_variant: Optional[str] = None
    # Round duty hours to the nearest N minutes (5/10/15/30). 0 = no round.
    duty_hours_rounding_minutes: int = 0
    # Number of duty hours that equal 1 Present Day (Policy 2 uses this;
    # payroll may also use it in future).
    standard_working_hours: float = 8.0
    # Default value for the per-employee `week_off_full_day` flag when a
    # new employee is created under this company.
    week_off_full_day_payment_default: bool = False
    # Iter 77d — Minimum working hours on a week-off day for full-day
    # attendance credit. 0 = disabled (any positive work → full day for
    # legacy setups).
    week_off_min_working_hours: float = 0.0


def _validate_hhmm(v: str, field: str) -> str:
    v = (v or "").strip()
    if not re.fullmatch(r"[0-2][0-9]:[0-5][0-9]", v):
        raise HTTPException(status_code=400, detail=f"{field} must be in HH:MM 24-hour format")
    h, m = int(v[:2]), int(v[3:])
    if h > 23 or m > 59:
        raise HTTPException(status_code=400, detail=f"{field} '{v}' is not a valid time")
    return v


def _validate_policy(raw: dict) -> dict:
    """Runs sanity checks on a policy payload and returns the sanitised dict.
    Raises HTTPException(400) for any obvious mistake so the UI can surface a
    clean error message."""
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Invalid policy payload")
    shifts_raw = raw.get("shifts") or []
    if not isinstance(shifts_raw, list) or not shifts_raw:
        raise HTTPException(status_code=400, detail="At least one shift is required")
    shifts: List[dict] = []
    seen_names: set = set()
    for i, s in enumerate(shifts_raw):
        if not isinstance(s, dict):
            raise HTTPException(status_code=400, detail=f"Shift #{i+1} is malformed")
        name = (s.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail=f"Shift #{i+1} needs a name")
        if name.lower() in seen_names:
            raise HTTPException(status_code=400, detail=f"Duplicate shift name '{name}'")
        seen_names.add(name.lower())
        shifts.append({
            "name": name,
            "start": _validate_hhmm(s.get("start", ""), f"'{name}' start time"),
            "end":   _validate_hhmm(s.get("end", ""),   f"'{name}' end time"),
        })
    days_raw = raw.get("weekly_off_days") or []
    if not isinstance(days_raw, list):
        raise HTTPException(status_code=400, detail="weekly_off_days must be a list of 0-6 integers")
    days: List[int] = []
    for d in days_raw:
        try:
            di = int(d)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Invalid weekly-off day '{d}'")
        if di < 0 or di > 6:
            raise HTTPException(status_code=400, detail="weekly_off_days values must be between 0 (Mon) and 6 (Sun)")
        if di not in days:
            days.append(di)

    def _num(field: str, min_v: float, max_v: float, default: float) -> float:
        v = raw.get(field, default)
        try:
            fv = float(v)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{field} must be a number")
        if fv < min_v or fv > max_v:
            raise HTTPException(status_code=400, detail=f"{field} must be between {min_v} and {max_v}")
        return fv

    grace = int(_num("grace_minutes_late", 0, 120, 10))
    half_day = _num("half_day_hours", 0.5, 12.0, 4.0)
    full_day = _num("full_day_hours", 1.0, 16.0, 8.0)
    if full_day <= half_day:
        raise HTTPException(status_code=400, detail="Full-day hours must be greater than half-day hours")
    break_hrs = _num("break_hours", 0.0, 4.0, 1.0)
    ot_thr = _num("overtime_threshold_hours", full_day, 20.0, max(full_day, 8.0))
    ot_mult = _num("overtime_multiplier", 1.0, 4.0, 1.5)
    night_allow = bool(raw.get("night_shift_allowance_enabled", False))
    night_start = _validate_hhmm(raw.get("night_shift_start", "22:00"), "Night shift start")
    night_end = _validate_hhmm(raw.get("night_shift_end", "06:00"), "Night shift end")
    notes = (raw.get("notes") or "").strip()[:500]

    # ---- Textile-specific extensions (accepted for ALL categories to
    # avoid dropping fields when a firm's category is later changed) ----
    variant_raw = raw.get("policy_variant")
    if variant_raw not in (None, "", "policy_1", "policy_2"):
        raise HTTPException(
            status_code=400,
            detail="policy_variant must be 'policy_1', 'policy_2' or null",
        )
    variant = variant_raw or None
    # Iter 227 — Shift Mode: "fixed" (default; employee uses assigned shift)
    # or "open" (Rotational/Open — shift auto-detected daily from the
    # employee's FIRST IN punch; nearest shift-start wins).
    shift_mode = str(raw.get("shift_mode") or "fixed").strip().lower()
    if shift_mode not in ("fixed", "open"):
        raise HTTPException(
            status_code=400,
            detail="shift_mode must be 'fixed' or 'open'",
        )
    rounding_raw = raw.get("duty_hours_rounding_minutes", 0)
    try:
        rounding = int(rounding_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="duty_hours_rounding_minutes must be an integer")
    if rounding not in (0, 5, 10, 15, 30):
        raise HTTPException(
            status_code=400,
            detail="duty_hours_rounding_minutes must be 0, 5, 10, 15 or 30",
        )
    standard_working = _num("standard_working_hours", 1.0, 16.0, full_day)
    weekoff_full_default = bool(raw.get("week_off_full_day_payment_default", False))
    # Iter 77d - Firm-level min working hours on week-off day (0 disables).
    weekoff_min_hrs = _num("week_off_min_working_hours", 0.0, 16.0, 0.0)
    # Iter 131 (user directive) — OT Calculation config for Textile
    # Policy 2 firms. Iter 131b: EITHER % of Basic OR % of Gross — never
    # both. 0 = unused.
    ot_pct_basic = _num("ot_pct_basic", 0.0, 500.0, 0.0)
    ot_pct_gross = _num("ot_pct_gross", 0.0, 500.0, 0.0)
    if ot_pct_basic > 0 and ot_pct_gross > 0:
        raise HTTPException(
            status_code=400,
            detail="OT Calculation: choose EITHER % of Basic OR % of Gross — not both.",
        )

    # Iter 175 — Policy Master "Sub Points" (user-specified catalogue).
    # Free config block; sanitised to known keys with safe defaults.
    pm_raw = raw.get("policy_master") if isinstance(raw.get("policy_master"), dict) else {}
    def _choice(key: str, options: List[str], default: str) -> str:
        v = str(pm_raw.get(key) or default).strip().lower()
        return v if v in options else default
    def _flag(key: str, default: bool = False) -> bool:
        return bool(pm_raw.get(key, default))
    _punch_types = pm_raw.get("punch_types")
    if not isinstance(_punch_types, list):
        _punch_types = ["biometric", "mobile"]
    _punch_types = [p for p in ("biometric", "mobile", "manual", "gps")
                    if p in [str(x).lower() for x in _punch_types]]
    # Iter 545 — Maximum Punches Per Day: default 4, min 2, max 20.
    try:
        _max_punches_per_day = int(pm_raw.get("maximum_punches_per_day", 4) or 4)
    except (TypeError, ValueError):
        _max_punches_per_day = 4
    _max_punches_per_day = max(2, min(20, _max_punches_per_day))
    # Iter 711 (user request) — FIRM-DEFINED dummy shifts (name + in/out
    # time), saved under policy_master.dummy_shifts. Empty list → the
    # built-in 7 master shifts keep applying (backward compatible).
    _ds_raw = pm_raw.get("dummy_shifts")
    _dummy_shifts_clean: List[Dict[str, str]] = []
    if isinstance(_ds_raw, list):
        for _d in _ds_raw[:20]:
            if not isinstance(_d, dict):
                continue
            _dn = str(_d.get("name") or "").strip().upper()[:40]
            _m1 = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)",
                               str(_d.get("start") or "").strip())
            _m2 = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)",
                               str(_d.get("end") or "").strip())
            if not _dn or not _m1 or not _m2:
                continue
            if _dn in {x["name"] for x in _dummy_shifts_clean}:
                continue
            _dummy_shifts_clean.append({
                "name": _dn,
                "start": f"{int(_m1.group(1)):02d}:{_m1.group(2)}",
                "end": f"{int(_m2.group(1)):02d}:{_m2.group(2)}",
            })
    policy_master = {
        "attendance_basis": _choice("attendance_basis", ["monthly", "daily", "hourly"], "monthly"),
        "shift_type": _choice("shift_type", ["fixed", "rotational", "open"], "fixed"),
        "punch_types": _punch_types or ["biometric"],
        "contractor_assignment_required": _flag("contractor_assignment_required"),
        "site_wise_attendance": _flag("site_wise_attendance"),
        "client_wise_attendance": _flag("client_wise_attendance"),
        "multiple_punch_allowed": _flag("multiple_punch_allowed", True),
        "auto_shift_detection": _flag("auto_shift_detection"),
        "wfh_allowed": _flag("wfh_allowed"),
        "geofencing_required": _flag("geofencing_required", True),
        # Iter 215 — report-only Dummy Shifts: when ON, the Employee
        # Master shows a Dummy Shift picker and the Dummy Shift Report
        # becomes available in Labour Law Reports.
        "dummy_shift_allowed": _flag("dummy_shift_allowed"),
        # Iter 711 — the firm's own dummy shift definitions (see above).
        "dummy_shifts": _dummy_shifts_clean,
        # Iter 200 (user request) — dynamic attendance calculation points:
        # • attendance_by_duty_hours: Days = Total Duty HRS ÷ Daily Duty HRS
        #   (firm's full-day hours) instead of per-day present counting.
        # • weekoff_present_add_ot: worked on week-off → hours go to OT,
        #   day NOT counted present.
        # • holiday_present_add_ot: worked on a Holiday-Master day → day
        #   counts present AND hours also go to OT.
        "attendance_by_duty_hours": _flag("attendance_by_duty_hours"),
        "weekoff_present_add_ot": _flag("weekoff_present_add_ot"),
        "holiday_present_add_ot": _flag("holiday_present_add_ot"),
        # Iter 202 (user request) — Compliance Salary only: a day with 8+
        # working hrs counts as 1 Present Day (extra hrs → OT per policy).
        # Applies only when the firm's Salary Allowed includes Compliance.
        "compliance_present_8hr": _flag("compliance_present_8hr"),
        # Iter 270 (user request) — "OT Include in Existing Compliance
        # Salary" (Yes/No). Yes (default) → OT Duty HRS are paid inside the
        # Compliance Salary (OT pay in gross). No → OT HRS are kept OUT of
        # the Compliance Salary and auto-import into the separate OT Salary
        # Process instead (no double payment).
        "compliance_ot_include": _flag("compliance_ot_include", True),
        # Iter 203 (user request) — Half-Day Threshold Rule: worked hrs
        # below the half-day threshold → ALL hrs to OT (0 Present); between
        # threshold and full day → ½ Present Day + remaining hrs to OT.
        # Duty HRS counts ONLY present-day hours.
        "halfday_threshold_rule": _flag("halfday_threshold_rule"),
        # Iter 289 (user request) — per-firm OT rounding slab:
        # 0 = exact minutes, 30 = half-hour slabs (floor), 60 = full-hour
        # slabs (floor). Default 30.
        "ot_slab_minutes": (
            int(pm_raw.get("ot_slab_minutes"))
            if pm_raw.get("ot_slab_minutes") in (0, 30, 60, "0", "30", "60")
            else 30
        ),
        # Iter 545 (user spec) — Configurable Multiple Punch & Maximum
        # Punch policy. Enforced on NEW app + machine punches only;
        # historical attendance is never recalculated.
        "maximum_punches_per_day": _max_punches_per_day,
        "punch_sequence": "in_out_alternate",
        "extra_punch_action": _choice("extra_punch_action", ["reject", "exception"], "reject"),
        "invalid_sequence_action": _choice("invalid_sequence_action", ["reject", "exception"], "reject"),
    }

    # Iter 204 (user request) — Employee Shift Change Management config.
    sc_raw = raw.get("shift_change") if isinstance(raw.get("shift_change"), dict) else {}
    _sc_tw = str(sc_raw.get("time_window") or "any").strip().lower()
    if _sc_tw not in ("any", "prev_day", "before_shift_start", "within_2h"):
        _sc_tw = "any"
    _sc_lv = str(sc_raw.get("approval_levels") or "single").strip().lower()
    if _sc_lv not in ("single", "two_level"):
        _sc_lv = "single"
    shift_change_cfg = {
        "enabled": bool(sc_raw.get("enabled")),
        "reason_mandatory": bool(sc_raw.get("reason_mandatory", True)),
        "post_punch_allowed": bool(sc_raw.get("post_punch_allowed")),
        "auto_approve": bool(sc_raw.get("auto_approve")),
        # Instant Shift Exception: punch/shift mismatch prompts the employee
        # to raise a request straight from the punch screen (post-punch
        # allowed for this flow even when post_punch_allowed is off).
        "instant_exception": bool(sc_raw.get("instant_exception", True)),
        "time_window": _sc_tw,
        "approval_levels": _sc_lv,
    }

    # Iter 205 (user request) — Week-Off Worked Attendance: what happens
    # when an employee works on their weekly-off day. Fully dynamic per
    # firm; ``mode`` empty = module off (legacy week-off rules apply).
    wow_raw = raw.get("week_off_worked") if isinstance(raw.get("week_off_worked"), dict) else {}
    _wow_mode = str(wow_raw.get("mode") or "").strip().lower()
    if _wow_mode not in ("", "ot_only", "half_day_ot", "full_day_ot",
                         "full_day_min_hours", "hourly"):
        _wow_mode = ""
    def _wow_num(key: str, default: float) -> float:
        try:
            v = float(wow_raw.get(key) if wow_raw.get(key) is not None else default)
        except (TypeError, ValueError):
            v = default
        return max(0.0, min(24.0, v))
    week_off_worked_cfg = {
        "mode": _wow_mode,
        "half_day_threshold": _wow_num("half_day_threshold", 4.0),
        "full_day_threshold": _wow_num("full_day_threshold", 8.0),
        "ot_after": _wow_num("ot_after", 0.0),
        # Iter 207 — "Full Day Attendance (Minimum Hours)" mode:
        # 0 = auto (50% of the employee's daily duty hours).
        "min_hours": _wow_num("min_hours", 0.0),
        "salary_credit": bool(wow_raw.get("salary_credit", True)),
        "leave_adjustment": bool(wow_raw.get("leave_adjustment")),
        "comp_off": bool(wow_raw.get("comp_off")),
        "double_ot": bool(wow_raw.get("double_ot")),
        "double_wages": bool(wow_raw.get("double_wages")),
        "approval_required": bool(wow_raw.get("approval_required")),
    }

    # Iter 200 — Report Settings (user request): which attendance reports
    # (grid views + downloads) are enabled for this firm + the default view.
    _REPORT_KEYS = ("inout", "ot", "hours", "salary", "inout_salary")
    rs_raw = raw.get("report_settings") if isinstance(raw.get("report_settings"), dict) else {}
    rs_en_raw = rs_raw.get("enabled") if isinstance(rs_raw.get("enabled"), dict) else {}
    rs_enabled = {k: bool(rs_en_raw.get(k, True)) for k in _REPORT_KEYS}
    if not any(rs_enabled.values()):
        raise HTTPException(
            status_code=400,
            detail="Report Settings: enable at least one report type.")
    rs_default = str(rs_raw.get("default_view") or "inout").strip().lower()
    if rs_default not in _REPORT_KEYS or not rs_enabled.get(rs_default):
        rs_default = next(k for k in _REPORT_KEYS if rs_enabled[k])
    report_settings = {"enabled": rs_enabled, "default_view": rs_default}

    # Iter 201 (user request) — Weekly-off Rotation Basis: firm sets NO fixed
    # week-off day; each employee's own week-off override applies instead.
    weekoff_rotation = bool(raw.get("weekoff_rotation_basis"))
    if weekoff_rotation:
        days = set()

    # Iter 200 (user request) — Salary Allowed: which salary processes this
    # firm may run (actual / compliance / both). Attendance auto-transfers
    # into the allowed process(es).
    salary_allowed = str(raw.get("salary_allowed") or "both").strip().lower()
    if salary_allowed not in ("actual", "compliance", "both"):
        salary_allowed = "both"

    # Iter 583 — configurable duplicate-punch window: machine/API punches
    # within this window of an existing punch are STORED but marked
    # "duplicate" (never counted). 0 = detection off. Default 5 minutes
    # (the previous hardcoded Iter 481/488 behaviour).
    try:
        _dedup_min = int(raw.get("dedup_window_minutes", 5))
    except (TypeError, ValueError):
        _dedup_min = 5
    _dedup_min = max(0, min(120, _dedup_min))

    # Iter 581 (user spec) — Employee Onboarding Gate: mandatory onboarding
    # data (Aadhaar / Bank / PAN / Photo) + Permission Days window. Punches
    # from employees with missing data are stored but HELD (inside the
    # window) or BLOCKED (after it) by the central eligibility engine
    # (shared/attendance_eligibility.py). enabled_at anchors the window for
    # existing employees; re-enabling the gate restarts it.
    og_raw = raw.get("onboarding_gate") if isinstance(raw.get("onboarding_gate"), dict) else {}
    try:
        _og_days = int(og_raw.get("permission_days", 7) or 0)
    except (TypeError, ValueError):
        _og_days = 7
    _og_enabled = bool(og_raw.get("enabled"))
    onboarding_gate = {
        "enabled": _og_enabled,
        "require_aadhaar": bool(og_raw.get("require_aadhaar", True)),
        "require_bank": bool(og_raw.get("require_bank", True)),
        "require_pan": bool(og_raw.get("require_pan", False)),
        "require_photo": bool(og_raw.get("require_photo", True)),
        "permission_days": max(0, min(90, _og_days)),
        "auto_release": bool(og_raw.get("auto_release", True)),
        "enabled_at": ((og_raw.get("enabled_at") or now_iso()) if _og_enabled else None),
    }

    # Iter 741 — ALTERNATE / OCCURRENCE-BASED WEEKOFF rules (additive).
    # {"type":"fixed|occurrence|alternate",
    #  "occurrence": {"5":[2,4]},              # weekday -> occurrence list
    #  "alternate": {"weekdays":[6],"cycle_start":"YYYY-MM-DD","pattern":["off","work"]},
    #  "effective_from": "YYYY-MM-DD"|None, "effective_to": None, "active": true}
    wr_raw = raw.get("weekoff_rules") if isinstance(raw.get("weekoff_rules"), dict) else None
    weekoff_rules = None
    if wr_raw:
        wtype = str(wr_raw.get("type") or "fixed")
        if wtype not in ("fixed", "occurrence", "alternate"):
            raise HTTPException(status_code=400, detail="weekoff_rules.type must be fixed/occurrence/alternate")
        occ = {}
        for k, v in (wr_raw.get("occurrence") or {}).items():
            try:
                wd_k = int(k)
            except (TypeError, ValueError):
                continue
            if not 0 <= wd_k <= 6:
                continue
            if v == "all":
                occ[str(wd_k)] = "all"
            elif isinstance(v, list):
                occ[str(wd_k)] = sorted({int(x) for x in v if isinstance(x, (int, float)) and 1 <= int(x) <= 5})
        alt = wr_raw.get("alternate") or {}
        alt_clean = None
        if wtype == "alternate":
            cs = str(alt.get("cycle_start") or "")
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", cs):
                raise HTTPException(status_code=400, detail="alternate.cycle_start must be YYYY-MM-DD")
            pat = [str(p) for p in (alt.get("pattern") or ["off", "work"]) if p in ("off", "work")]
            if len(pat) < 2 or "off" not in pat:
                raise HTTPException(status_code=400, detail="alternate.pattern must contain off and work weeks")
            wds = [int(x) for x in (alt.get("weekdays") or []) if isinstance(x, (int, float)) and 0 <= int(x) <= 6]
            if not wds:
                raise HTTPException(status_code=400, detail="alternate.weekdays required")
            alt_clean = {"cycle_start": cs, "pattern": pat, "weekdays": sorted(set(wds))}
        ef, et = str(wr_raw.get("effective_from") or "") or None, str(wr_raw.get("effective_to") or "") or None
        if ef and et and et < ef:
            raise HTTPException(status_code=400, detail="weekoff_rules effective_to cannot be before effective_from")
        weekoff_rules = {"type": wtype, "occurrence": occ, "alternate": alt_clean,
                         "effective_from": ef, "effective_to": et,
                         "active": bool(wr_raw.get("active", True))}

    # Iter 745 — LATE PENALTY (Attendance-Policy based, user PRD).
    # Monthly counter ALWAYS resets each month (no carry-forward).
    # mode "every_n": every N chargeable lates = every_n_days cut.
    # mode "slabs":   chargeable-late count falls in a slab → that slab's
    #                 days (absolute, not cumulative; open-ended when to=None).
    lp_raw = raw.get("late_penalty") if isinstance(raw.get("late_penalty"), dict) else None
    late_penalty = None
    if lp_raw:
        def _lpi(key: str, lo: int, hi: int, dflt: int) -> int:
            try:
                v = int(float(lp_raw.get(key, dflt) if lp_raw.get(key) is not None else dflt))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"late_penalty.{key} must be a number")
            return max(lo, min(hi, v))
        _lp_mode = str(lp_raw.get("mode") or "every_n")
        if _lp_mode not in ("every_n", "slabs"):
            raise HTTPException(status_code=400, detail="late_penalty.mode must be 'every_n' or 'slabs'")
        try:
            _lp_end = float(lp_raw.get("every_n_days", 0.5) or 0.5)
        except (TypeError, ValueError):
            _lp_end = 0.5
        if _lp_end not in (0.25, 0.5, 1.0, 2.0):
            raise HTTPException(status_code=400, detail="late_penalty.every_n_days must be 0.25, 0.5, 1 or 2")
        _lp_slabs: List[dict] = []
        for s in (lp_raw.get("slabs") or []):
            if not isinstance(s, dict):
                continue
            try:
                _sf = int(float(s.get("from", 0)))
                _st_to = s.get("to")
                _st_to = None if _st_to in (None, "") else int(float(_st_to))
                _sd = float(s.get("days", 0))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="late_penalty.slabs values must be numbers")
            if _sf < 1 or (_st_to is not None and _st_to < _sf) or _sd < 0 or _sd > 31:
                raise HTTPException(status_code=400, detail=f"late_penalty slab {_sf}-{_st_to} is invalid")
            _lp_slabs.append({"from": _sf, "to": _st_to, "days": _sd})
        _lp_slabs.sort(key=lambda x: x["from"])
        if _lp_mode == "slabs" and bool(lp_raw.get("enabled")) and not _lp_slabs:
            raise HTTPException(status_code=400, detail="late_penalty: slab mode needs at least one slab")
        try:
            _lp_max = max(0.0, min(31.0, float(lp_raw.get("max_days", 0) or 0)))
        except (TypeError, ValueError):
            _lp_max = 0.0
        late_penalty = {
            "enabled": bool(lp_raw.get("enabled")),
            "grace_minutes": _lpi("grace_minutes", 0, 240, 0),
            "free_lates": _lpi("free_lates", 0, 31, 3),
            "mode": _lp_mode,
            "every_n": _lpi("every_n", 1, 31, 3),
            "every_n_days": _lp_end,
            "slabs": _lp_slabs,
            "max_days": _lp_max,
            "monthly_reset": True,
        }

    return {
        "shifts": shifts,
        "weekly_off_days": sorted(days),
        "weekoff_rules": weekoff_rules,
        # Iter 745 — Late Penalty (policy-based salary deduction).
        "late_penalty": late_penalty,
        "grace_minutes_late": grace,
        "half_day_hours": half_day,
        "full_day_hours": full_day,
        "break_hours": break_hrs,
        "overtime_threshold_hours": ot_thr,
        "overtime_multiplier": ot_mult,
        "night_shift_allowance_enabled": night_allow,
        "night_shift_start": night_start,
        "night_shift_end": night_end,
        "notes": notes,
        "policy_variant": variant,
        "shift_mode": shift_mode,
        "duty_hours_rounding_minutes": rounding,
        "standard_working_hours": standard_working,
        "week_off_full_day_payment_default": weekoff_full_default,
        # Iter 77d - Firm-level minimum working hours for week-off day.
        # When > 0 an employee working >= this many hours on a week-off
        # day earns a full-day attendance credit.
        "week_off_min_working_hours": weekoff_min_hrs,
        # Iter 131 — OT Calculation config (Textile Policy 2).
        "ot_pct_basic": ot_pct_basic,
        "ot_pct_gross": ot_pct_gross,
        # Iter 175 — Policy Master Sub Points.
        "policy_master": policy_master,
        # Iter 200 — per-firm report availability + default grid view.
        "report_settings": report_settings,
        # Iter 200 — allowed salary processes for this firm.
        "salary_allowed": salary_allowed,
        # Iter 204 — Employee Shift Change Management config.
        "shift_change": shift_change_cfg,
        # Iter 205 — Week-Off Worked Attendance config.
        "week_off_worked": week_off_worked_cfg,
        # Iter 581 — Employee Onboarding Gate (attendance eligibility).
        "onboarding_gate": onboarding_gate,
        # Iter 583 — configurable duplicate-punch window (minutes, 0 = off).
        "dedup_window_minutes": _dedup_min,
    }


def _round_minutes(mins: float, step: int) -> float:
    """Round a duty-minute value.

    * ``step == 0``  → no rounding.
    * ``step == 15`` → SPECIAL rule requested by user (Iter 77f):
        - 0-15 min inside the hour  → 00
        - 16-45 min inside the hour → 30
        - 46-59 min inside the hour → 60 (rolls to next hour)
      i.e. every duty duration snaps to :00 or :30 with a 15-minute
      tolerance around each full hour.
    * ``step == 30`` → round to nearest 30 minutes (half-up).
    * anything else → nearest ``step`` minutes (half-up).
    Half-way values round UP (banker's-rounding is confusing for payroll).
    """
    if not step or step <= 0:
        return mins
    if mins <= 0:
        return 0.0
    if step == 15:
        hours = int(mins // 60)
        rem = mins - hours * 60
        if rem <= 15:
            m = 0
        elif rem <= 45:
            m = 30
        else:
            hours += 1
            m = 0
        return hours * 60 + m
    return round(mins / step + 1e-9) * step


# ---------------------------------------------------------------------------
# Iter 77c — Shift resolution helpers.
# ---------------------------------------------------------------------------
# Per-employee ``attendance_policy_override`` may carry a ``shift_id`` and/or
# an ``auto_shift_by_first_punch`` flag pointing at the GLOBAL Shift Master
# catalogue. When present, the shift's ``end - start`` becomes the
# employee's effective *standard_working_hours* / *full_day_hours* for that
# day - this is the value the cap logic in ``compute_textile_day`` clamps
# against when OT is not allowed.

def _hhmm_to_min(v: Any) -> Optional[int]:
    try:
        h, m = str(v or "").split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _shift_duration_hours(shift: Optional[dict]) -> Optional[float]:
    """Return the duty duration (in hours) for a Shift Master entry.
    Handles the overnight case where end < start (e.g. 20:00 -> 08:00)."""
    if not shift:
        return None
    st = _hhmm_to_min(shift.get("start"))
    en = _hhmm_to_min(shift.get("end"))
    if st is None or en is None:
        return None
    dur = (en - st) if en >= st else (en + 24 * 60 - st)
    if dur <= 0:
        return None
    return dur / 60.0


def _is_shift_open(policy: Optional[dict]) -> bool:
    """Iter 227 — True when the firm runs OPEN / ROTATIONAL shifts (daily
    shift auto-detected from the first IN punch). Honours the top-level
    ``shift_mode``, the Policy Master sub-point ``shift_type``
    (rotational / open) AND — Iter 295 (user bug: toggle had no effect) —
    the Policy Master ``auto_shift_detection`` switch, so turning it ON in
    the Attendance Master enables detection even with a fixed shift type."""
    p = policy or {}
    if str(p.get("shift_mode") or "").lower() == "open":
        return True
    pm = p.get("policy_master") or {}
    if pm.get("auto_shift_detection") is True:
        return True
    return str(pm.get("shift_type") or "").lower() in ("rotational", "open")


def resolve_shift_for_user(
    user: dict,
    sorted_punches: List[dict],
    shifts_by_id: Optional[Dict[str, dict]] = None,
    shifts_list: Optional[List[dict]] = None,
    firm_shift_open: bool = False,
) -> Optional[dict]:
    """Resolve which shift applies to a single employee-day.

    Precedence:
      1. Firm Attendance Policy ``shift_mode == "open"`` (Iter 227) OR
         ``attendance_policy_override.auto_shift_by_first_punch``  →
         pick the shift whose START time is closest (circular distance)
         to the first IN punch of the day.
      2. ``attendance_policy_override.shift_id`` → straight lookup in
         ``shifts_by_id``.
      3. else → ``None`` (caller falls back to firm defaults).
    """
    ov = (user or {}).get("attendance_policy_override") or {}
    shifts_by_id = shifts_by_id or {}
    shifts_list = shifts_list or list(shifts_by_id.values())

    # 1) Auto by first-IN
    if (firm_shift_open or ov.get("auto_shift_by_first_punch")) and sorted_punches and shifts_list:
        first_in_min: Optional[int] = None
        for p in sorted_punches:
            if p.get("kind") == "in":
                try:
                    when = datetime.fromisoformat(
                        (p["at"] or "").replace("Z", "+00:00"),
                    )
                    first_in_min = when.hour * 60 + when.minute
                except Exception:
                    pass
                break
        if first_in_min is not None:
            def _dist(s: dict) -> int:
                st = _hhmm_to_min(s.get("start"))
                if st is None:
                    return 10 ** 9
                d = abs(first_in_min - st)
                return min(d, 24 * 60 - d)  # circular
            candidate = min(shifts_list, key=_dist)
            if _dist(candidate) < 10 ** 9:
                return candidate

    # 2) Manual assignment
    sid = ov.get("shift_id")
    if sid and sid in shifts_by_id:
        return shifts_by_id[sid]

    return None


def apply_resolved_shift_to_policy(
    policy: dict,
    resolved_shift: Optional[dict],
) -> dict:
    """Return a shallow copy of ``policy`` with the resolved shift's
    duration patched in as the standard / full-day hours. The half-day
    figure is preserved if the caller already set one; otherwise defaults
    to half of the shift duration."""
    hrs = _shift_duration_hours(resolved_shift)
    if hrs is None or hrs <= 0:
        return policy
    patched = dict(policy)
    patched["standard_working_hours"] = hrs
    patched["full_day_hours"] = hrs
    if not patched.get("half_day_hours"):
        patched["half_day_hours"] = round(hrs / 2.0, 2)
    return patched


async def load_daily_shift_overrides(
    company_id: str, date_from: str, date_to: str,
) -> Dict[tuple, dict]:
    """Iter 204 — approved Shift Change Requests write per-day shift
    assignments; the attendance engine gives them top precedence so
    attendance/OT/payroll views recompute on the APPROVED shift."""
    out: Dict[tuple, dict] = {}
    async for a in db.daily_shift_assignments.find(
            {"company_id": company_id, "date": {"$gte": date_from, "$lte": date_to}},
            {"_id": 0, "user_id": 1, "date": 1, "shift_id": 1,
             "name": 1, "start": 1, "end": 1}):
        out[(a["user_id"], a["date"])] = a
    return out


def apply_employee_policy_override(policy: dict, user: Optional[dict]) -> dict:
    """Iter 77z-final — Overlay employee-level ``attendance_policy_override``
    onto the firm-level (and shift-resolved) policy.

    Employees can override:
      • ``full_day_hours`` / ``standard_working_hours`` — daily working
        quota that decides the OT threshold on the Grid + OT report.
      • ``ot_allowed`` — per-employee OT toggle.
      • ``week_off_paid_when_absent`` — half/full paid weekly-off.
      • ``half_day_hours`` — half-day threshold.

    Falsy override values are ignored so the firm defaults survive when
    the override key is unset. Returns a NEW dict (shallow copy).
    """
    ov = (user or {}).get("attendance_policy_override") or {}
    # Iter 207 (user request) — per-employee Weekly Off from the Employee
    # Master. When set it REPLACES the firm's weekly_off_days for this
    # employee (used when the firm policy keeps Weekly Off = N/A).
    _wo_emp = (user or {}).get("weekly_off_days_override")
    _wo_patch = None
    if isinstance(_wo_emp, list) and len(_wo_emp) > 0:
        _wo_patch = [int(x) for x in _wo_emp
                     if isinstance(x, (int, float)) and 0 <= int(x) <= 6]
    # Iter 142 — legacy per-employee ``ot_applicable`` flag (set from the
    # Employee Master OT option) also gates OT when no explicit
    # attendance_policy_override.ot_allowed exists.
    _legacy_ot = (user or {}).get("ot_applicable")
    if not ov:
        if _legacy_ot is None and _wo_patch is None:
            return policy
        patched = dict(policy or {})
        if _legacy_ot is not None:
            patched["ot_allowed"] = bool(_legacy_ot)
        if _wo_patch is not None:
            patched["weekly_off_days"] = _wo_patch
        return patched
    patched = dict(policy or {})
    if _wo_patch is not None:
        patched["weekly_off_days"] = _wo_patch
    for key in (
        "full_day_hours",
        "standard_working_hours",
        "half_day_hours",
        "week_off_min_hours",
        # Iter 94 — per-employee Duty-HRS rounding step (0/5/10/15/30 min)
        # so "Individual Employee Wise Policy for Duty HRS" is honored.
        "duty_hours_rounding_minutes",
    ):
        val = ov.get(key)
        if val is not None and val != "":
            try:
                patched[key] = float(val)
            except (TypeError, ValueError):
                pass
    if "ot_allowed" in ov and ov.get("ot_allowed") is not None:
        patched["ot_allowed"] = bool(ov.get("ot_allowed"))
    elif _legacy_ot is not None:
        patched["ot_allowed"] = bool(_legacy_ot)
    if "week_off_paid_when_absent" in ov and ov.get("week_off_paid_when_absent") is not None:
        patched["week_off_paid_when_absent"] = bool(ov.get("week_off_paid_when_absent"))
    return patched




async def load_shift_masters_map() -> Tuple[Dict[str, dict], List[dict]]:
    """Fetch the global Shift Master catalogue once per request. Returns
    ``(by_id, list)``. Both are empty if the collection is empty."""
    docs = await db.shift_masters.find({}, {"_id": 0}).to_list(500)
    by_id = {d["shift_id"]: d for d in docs if d.get("shift_id")}
    return by_id, docs


def dedupe_rapid_punches(
    punches: List[dict],
    window_seconds: int = 30,
) -> List[dict]:
    """Iter 276 (user request) — "multiple punches within seconds":
    a worker double/triple-scanning the finger registers 2-3 punches a few
    seconds apart (sometimes with different IN/OUT direction), which breaks
    the IN/OUT sheet. Drop ANY punch — regardless of kind or source — that
    lands within ``window_seconds`` of the previously KEPT punch, keeping
    the FIRST punch of the burst (auto-rectify)."""
    if not punches:
        return []
    from datetime import timedelta as _td
    ordered = sorted(
        (p for p in punches if p.get("at")),
        key=lambda p: p["at"],
    )
    kept: List[dict] = []
    last_at: Optional[datetime] = None
    win = _td(seconds=max(1, int(window_seconds)))
    for p in ordered:
        try:
            at = datetime.fromisoformat(str(p["at"]).replace("Z", "+00:00"))
        except Exception:
            kept.append(p)
            continue
        if last_at is not None and (at - last_at) <= win:
            continue  # rapid duplicate — ignore
        last_at = at
        kept.append(p)
    return kept


def dedupe_same_machine_punches(
    punches: List[dict],
    threshold_min: int = 15,
) -> List[dict]:
    """Iter 77s — Drop duplicate punches from the same biometric machine
    that land within ``threshold_min`` minutes of each other.

    A "duplicate" here is a punch that:
      * has the same ``kind`` (in/out) as the previous kept punch, AND
      * comes from the SAME ``source`` string (e.g. "bio_dev01",
        "zk_adms", "mobile"), AND
      * is <= ``threshold_min`` minutes AFTER the previous kept punch.

    Chronologically sorted input is expected. Returns a NEW list; the
    input is not mutated.
    """
    if not punches:
        return []
    from datetime import timedelta as _td
    ordered = sorted(
        (p for p in punches if p.get("at")),
        key=lambda p: p["at"],
    )
    kept: List[dict] = []
    last_by_signature: Dict[Tuple[str, str], datetime] = {}
    seen_exact: set = set()
    thresh = _td(minutes=max(1, int(threshold_min)))
    for p in ordered:
        try:
            at = datetime.fromisoformat(str(p["at"]).replace("Z", "+00:00"))
        except Exception:
            kept.append(p)
            continue
        # Iter 95 — EXACT duplicate (same kind + same timestamp) is always
        # dropped regardless of source. Double .dat imports produced twin
        # punches with different import tags which broke IN/OUT pairing.
        exact_sig = ((p.get("kind") or "").lower(), at.isoformat())
        if exact_sig in seen_exact:
            continue
        seen_exact.add(exact_sig)
        sig = (
            (p.get("kind") or "").lower(),
            (p.get("source") or "").lower(),
        )
        last_at = last_by_signature.get(sig)
        if last_at is not None and (at - last_at) <= thresh:
            # Duplicate — skip.
            continue
        last_by_signature[sig] = at
        kept.append(p)
    return kept


def merge_out_in_bounces(
    punches: List[dict],
    min_gap_seconds: int = 60,
) -> List[dict]:
    """Iter 77w — Collapse "OUT then IN" bounces that happen within
    ``min_gap_seconds`` seconds. These are almost always ZKTeco device
    quirks where the machine registers a spurious OUT immediately
    before a real IN (e.g. worker re-scans finger). We drop BOTH the
    OUT and the following IN so the pair-punches loop sees the day as
    one continuous session.

    Anything with a real gap (>= min_gap_seconds) is left untouched —
    that's a genuine break between sessions and remains subject to the
    OT rules downstream.
    """
    if not punches or min_gap_seconds <= 0:
        return list(punches)
    from datetime import timedelta as _td
    ordered = sorted(
        (p for p in punches if p.get("at")),
        key=lambda p: p["at"],
    )
    kept: List[dict] = []
    thresh = _td(seconds=int(min_gap_seconds))
    i = 0
    while i < len(ordered):
        p = ordered[i]
        # Look ahead for an OUT->IN with tiny gap.
        if (
            (p.get("kind") or "").lower() == "out"
            and i + 1 < len(ordered)
            and (ordered[i + 1].get("kind") or "").lower() == "in"
        ):
            try:
                a1 = datetime.fromisoformat(str(p["at"]).replace("Z", "+00:00"))
                a2 = datetime.fromisoformat(
                    str(ordered[i + 1]["at"]).replace("Z", "+00:00"),
                )
                if (a2 - a1) <= thresh:
                    # Bounce - skip BOTH.
                    i += 2
                    continue
            except Exception:
                pass
        kept.append(p)
        i += 1
    return kept


def has_unpaired_punches(day_punches: List[dict]) -> bool:
    """Iter 77z-fix — Return True when a day's punches can NOT be cleanly
    paired into IN → OUT tuples (user rule: *"if any punch is missing
    between duty hours, do not calculate duty"*).

    Detection walks the chronologically sorted punches. Consecutive INs
    without an intervening OUT, or trailing INs without a closing OUT,
    are treated as missing punches.

    Iter 714 (user bug — "both punches available + manually repaired but
    day still shows Missing Punch"): OUT punches BEFORE the day's first IN
    are the tail of yesterday's night shift (or a stray/redundant manual
    OUT). ``_pair_punches`` already skips them safely — they must NOT zero
    out the day's valid IN → OUT pair any more. A day consisting ONLY of
    such leading OUTs (no IN at all) is still flagged as before.
    """
    ps = sorted(
        (p for p in (day_punches or []) if p.get("at") and p.get("kind") in ("in", "out")),
        key=lambda p: p["at"],
    )
    if not ps:
        return False
    open_in = False
    seen_in = False
    leading_out = False
    paired_min = 0
    last_out_at = None
    open_at = None
    last_in_at = None
    for p in ps:
        k = (p.get("kind") or "").lower()
        if k == "in":
            if open_in:
                return True  # IN → IN without OUT between
            open_in = True
            seen_in = True
            try:
                open_at = datetime.fromisoformat(str(p["at"]).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                open_at = None
            last_in_at = open_at
        elif k == "out":
            if not open_in:
                if seen_in:
                    return True  # OUT without preceding IN mid-day
                leading_out = True  # cross-day tail — tolerated
                continue
            open_in = False
            if open_at is not None:
                try:
                    _o = datetime.fromisoformat(str(p["at"]).replace("Z", "+00:00"))
                    if _o > open_at:
                        paired_min += int((_o - open_at).total_seconds() // 60)
                        last_out_at = _o
                except (ValueError, TypeError):
                    pass
            open_at = None
    if open_in:
        # Iter 716 (GAJRAM case) — a trailing stray IN within 30 min of the
        # day's last completed OUT, on a day already holding ≥8h of paired
        # duty, is a double-scan echo. _pair_punches ignores it for hours;
        # it must not flag the whole (complete) day as Missing Punch.
        if (last_out_at is not None and last_in_at is not None
                and paired_min >= 8 * 60
                and timedelta(0) <= (last_in_at - last_out_at) <= timedelta(minutes=30)):
            return False
        # Iter 726 (user bug — night-shift TODAY flagged "Missing Punch"):
        # an unclosed trailing IN whose timestamp is within the last 16
        # hours is a duty STILL IN PROGRESS (night shift / OT running —
        # the OUT will land tomorrow morning and cross-midnight stitching
        # will close the pair). Never alarm the admin for an open shift.
        if last_in_at is not None:
            try:
                _lin = last_in_at
                if _lin.tzinfo is None:
                    _lin = _lin.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - _lin) < timedelta(hours=16):
                    return False
            except (TypeError, ValueError):
                pass
        return True  # trailing unclosed IN
    return leading_out and not seen_in  # OUT-only day stays flagged




def _single_machine_normalize(
    punches_by_day: Dict[str, List[dict]],
    cfg: dict,
) -> Dict[str, List[dict]]:
    """Iter 503 — SINGLE MACHINE ATTENDANCE MODE (user spec, Message 148).

    When a firm runs ONE shared biometric device for both IN and OUT the
    stored punch kinds are unreliable (many devices report every punch as
    check-in). This branch re-interprets each employee-day's MACHINE
    punches per the firm's Firm Master → Attendance & Shift settings:

      • ``dup_window_min`` (0/1/2/5/10) — drop punch bursts within N min.
      • ``interpretation``:
          "alternate"  — 1st=IN, 2nd=OUT, 3rd=IN … (default, mode A)
          "first_last" — first punch=IN, last punch=OUT (mode B); middle
                         punches handled per ``lunch_mode``.
      • ``lunch_mode`` (mode B only):
          "ignore_middle" — middles dropped (duty = last − first)
          "actual_break"  — middles alternate OUT/IN (real break windows
                            are deducted by the normal pairing engine)
          "fixed"         — middles dropped; a fixed 30/45/60-min lunch
                            is deducted at the hours level (grid compute).

    Mobile-app / manual punches keep their explicit kinds untouched.
    Returns a NEW dict. The first kept machine punch of each day carries
    an ``_smm`` metadata dict (calc_mode / dupes_ignored / punch_pattern)
    that surfaces on the attendance-grid day cells for transparency.
    """
    from datetime import datetime as _dt
    try:
        window_min = int(cfg.get("dup_window_min", 5))
    except (TypeError, ValueError):
        window_min = 5
    interp = str(cfg.get("interpretation") or "alternate")
    lunch_mode = str(cfg.get("lunch_mode") or "ignore_middle")

    def _hhmm(p: dict) -> str:
        try:
            return _dt.fromisoformat(
                str(p.get("at")).replace("Z", "+00:00")).strftime("%H:%M")
        except (ValueError, TypeError):
            return "?"

    def _is_mach(p: dict) -> bool:
        return str(p.get("source") or "").startswith("zkteco")

    out: Dict[str, List[dict]] = {}
    last_at = None
    for dk in sorted(punches_by_day.keys()):
        kept: List[dict] = []
        dropped = 0
        for p in sorted(punches_by_day.get(dk) or [],
                        key=lambda x: x.get("at") or ""):
            try:
                t = _dt.fromisoformat(str(p.get("at")).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                kept.append(p)
                continue
            if (window_min > 0 and last_at is not None and _is_mach(p)
                    and abs((t - last_at).total_seconds()) < window_min * 60):
                dropped += 1
                continue  # duplicate burst on the shared device — drop
            kept.append(p)
            last_at = t

        machine = sorted((p for p in kept if _is_mach(p)),
                         key=lambda x: x.get("at") or "")
        middles_ignored = 0
        if machine:
            if interp == "first_last" and len(machine) >= 2:
                machine[0]["kind"] = "in"
                machine[-1]["kind"] = "out"
                middle = machine[1:-1]
                if lunch_mode == "actual_break":
                    for i, p in enumerate(middle):
                        p["kind"] = "out" if i % 2 == 0 else "in"
                else:  # ignore_middle / fixed — drop middle punches
                    middles_ignored = len(middle)
                    _mid_ids = {id(p) for p in middle}
                    kept = [p for p in kept if id(p) not in _mid_ids]
            else:  # alternate (mode A) — also covers 1-punch days
                for i, p in enumerate(machine):
                    p["kind"] = "in" if i % 2 == 0 else "out"
            final_machine = sorted((p for p in kept if _is_mach(p)),
                                   key=lambda x: x.get("at") or "")
            if final_machine:
                if interp == "first_last":
                    _mode = "B · First IN — Last OUT"
                    if lunch_mode == "actual_break":
                        _mode += " + actual break"
                    elif lunch_mode == "fixed":
                        _mode += f" + fixed lunch {int(cfg.get('lunch_fixed_min') or 30)}m"
                else:
                    _mode = "A · Alternate IN/OUT"
                final_machine[0]["_smm"] = {
                    "calc_mode": _mode,
                    "dupes_ignored": dropped,
                    "middles_ignored": middles_ignored,
                    "punch_pattern": " → ".join(
                        f"{_hhmm(p)} {(p.get('kind') or '?').upper()}"
                        for p in final_machine),
                }
        out[dk] = kept
    return out


def dedupe_close_punches(
    punches_by_day: Dict[str, List[dict]],
    window_min: int = 5,
    company_cfg: Optional[dict] = None,
) -> Dict[str, List[dict]]:
    """Iter 481 (user request) — repair stored machine-punch data:

    1. DROP duplicate punches within ``window_min`` minutes of the
       previous kept punch from the SAME machine/source (double-punching
       at the device used to flip the IN/OUT alternation).
    2. RE-KIND corrupted machine days: when a day's remaining MACHINE
       punches are all the same kind (all "in" or all "out") and there
       are 2+, re-assign alternately IN → OUT → IN … in time order.
       Mobile / manual punches keep their explicit kinds.

    Returns a NEW dict (does not mutate the input).

    Iter 503 — when the firm's ``attendance_config.device_mode`` is
    "single_machine" the SINGLE MACHINE MODE branch takes over entirely
    (all other firms keep this exact legacy behaviour, 100% unchanged).
    """
    _cfg = company_cfg or {}
    if str(_cfg.get("device_mode") or "") == "single_machine":
        return _single_machine_normalize(punches_by_day, _cfg)
    from datetime import datetime as _dt
    out: Dict[str, List[dict]] = {}
    last_at = None
    last_src = None
    for dk in sorted(punches_by_day.keys()):
        kept: List[dict] = []
        for p in sorted(punches_by_day.get(dk) or [],
                        key=lambda x: x.get("at") or ""):
            try:
                t = _dt.fromisoformat(str(p.get("at")).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                kept.append(p)
                continue
            src = str(p.get("source") or "")
            # Iter 488 (user: "Multi Punch Within the Same time — ignore
            # duplicates within 5 min by default") — machine punches are
            # now deduped against the previous kept punch from ANY source
            # (a second registered device produced same-time duplicates).
            # Non-machine punches keep the original same-source-only rule
            # so an admin's manual repair punch is never dropped.
            # Iter 555 (user bug — "Edit Manual OT In/Out → OT punch not
            # showing") — manual_admin punches are NEVER deduped: the
            # repair modal saves the OT IN 1 min after the duty OUT, so
            # when the duty OUT was also manually repaired the same-source
            # 5-min rule silently dropped the OT IN and the whole manual
            # OT session vanished (unpaired OT OUT is discarded).
            is_machine = src.startswith("zkteco")
            is_manual = src == "manual_admin"
            if (last_at is not None and not is_manual
                    and (is_machine or (src and src == last_src))
                    and abs((t - last_at).total_seconds()) < window_min * 60):
                continue  # duplicate burst — drop
            kept.append(p)
            last_at, last_src = t, src
        # Iter 486 (user bug) — the all-same-kind repair now covers EVERY
        # source (machine + app + manual + import) so a day whose punches
        # all landed as "in" (or all "out") is re-kinded earliest=IN →
        # latest=OUT regardless of which device/app recorded them.
        # Mixed-kind days keep their explicit kinds untouched.
        machine = [p for p in kept if (p.get("kind") or "").lower() in ("in", "out")]
        kinds = {(p.get("kind") or "").lower() for p in machine}
        if machine and (kinds <= {"in"} or kinds <= {"out"}):
            seq = sorted(machine, key=lambda x: x.get("at") or "")
            start = 0
            try:
                _t0 = _dt.fromisoformat(
                    str(seq[0].get("at")).replace("Z", "+00:00"))
                if _t0.hour < 8:
                    # Early-morning first punch = candidate NIGHT-SHIFT
                    # OUT (cross-day stitch pairs it to yesterday's IN).
                    seq[0]["kind"] = "out"
                    start = 1
            except (ValueError, TypeError):
                pass
            if len(seq) - start >= 2:
                for i, p in enumerate(seq[start:]):
                    p["kind"] = "in" if i % 2 == 0 else "out"
        out[dk] = kept
    return out


def stitch_cross_day_ot(
    punches_by_day: Dict[str, List[dict]],
    max_hours: int = 16,
    company_cfg: Optional[dict] = None,
) -> Dict[str, List[dict]]:
    """Iter 77y — Cross-day OT punch pairing.

    Night-shift OT frequently ends AFTER midnight on the biometric device.
    Example (Sanjeev Kumar, bio 32)::

        01-Jun IN 08:00, OUT 19:58, OT-In 20:08   (unpaired trailing IN)
        02-Jun OT-Out 07:58                       (unpaired leading OUT)

    Iter 715 (user spec — CROSS MIDNIGHT punching): this mapping is the
    firm-wide Cross Midnight behaviour, DEFAULT YES. Only an explicit
    ``attendance_config.cross_midnight = False`` switches it off.

    Left as-is, the per-day pair-punches loop can't pair the OT-In with
    the next-day OT-Out so the entire OT session is silently dropped.
    This helper walks the sorted day list and, when Day N ends with an
    unpaired IN AND Day N+1 starts with an OUT within ``max_hours``, MOVES
    the leading OUT into Day N (rewriting its ``date`` field). A
    ``_cross_day`` flag is set on the moved punch so the compute layer
    can skip the 12-hour anomaly cap that normally suppresses OT on days
    with abnormally high raw hours.

    Returns a NEW dict (does not mutate the input).
    """
    if company_cfg is not None and company_cfg.get("cross_midnight") is False:
        return dict(punches_by_day or {})
    if not punches_by_day:
        return {}
    from datetime import datetime as _dt, timedelta as _td
    day_keys = sorted(punches_by_day.keys())
    out_map: Dict[str, List[dict]] = {k: list(v or []) for k, v in punches_by_day.items()}
    for i, dk in enumerate(day_keys[:-1]):
        cur = out_map.get(dk) or []
        if not cur:
            continue
        cur_sorted = sorted(cur, key=lambda p: p.get("at") or "")
        # Balance-count IN/OUT to detect an unpaired trailing IN
        bal = 0
        for p in cur_sorted:
            k = (p.get("kind") or "").lower()
            if k == "in":
                bal += 1
            elif k == "out":
                bal = max(0, bal - 1)
        last_kind = (cur_sorted[-1].get("kind") or "").lower()
        # Iter 682 (user bug — night-shift "false missing punches"): tolerate
        # a stray DOUBLE-TAP tail. If the day ends IN→X where X is within
        # 3 minutes of that IN (device echo / alternation flip), the IN is
        # still the true trailing anchor for the cross-midnight stitch.
        anchor = cur_sorted[-1]
        if bal > 0 and last_kind != "in" and len(cur_sorted) >= 2:
            prev = cur_sorted[-2]
            if (prev.get("kind") or "").lower() == "in":
                try:
                    t_prev = _dt.fromisoformat(str(prev["at"]).replace("Z", "+00:00"))
                    t_last = _dt.fromisoformat(str(cur_sorted[-1]["at"]).replace("Z", "+00:00"))
                    if (t_last - t_prev) <= _td(minutes=3):
                        anchor, last_kind = prev, "in"
                except (ValueError, TypeError, KeyError):
                    pass
        else:
            anchor = cur_sorted[-1]
        if bal <= 0 or last_kind != "in":
            continue
        next_dk = day_keys[i + 1]
        nxt = out_map.get(next_dk) or []
        if not nxt:
            continue
        nxt_sorted = sorted(nxt, key=lambda p: p.get("at") or "")
        first = nxt_sorted[0]
        first_kind = (first.get("kind") or "").lower()
        # Iter 727 — remember whether the machine EXPLICITLY recorded the
        # next-day punch as OUT (vs a mislabelled IN we relabel below).
        # Guard (a) must only apply to relabel-steals, never to explicit
        # OUT punches (genuine overnight OT sessions).
        _explicit_out = first_kind == "out"
        # Iter 481 (user request) — a next-day EARLY-MORNING punch (before
        # 08:00) following an unpaired IN also counts as the night-shift
        # OUT even when the machine mislabelled it "in" (alternation
        # corruption). Re-kind it to "out" and pull it back.
        # Iter 682 — window widened to 11:00 (live case: morning OUT at
        # 08:03 was refused, leaving "missing OUT" + "missing IN" days).
        if first_kind != "out":
            _early_relabel = False
            if first_kind == "in":
                try:
                    _t = _dt.fromisoformat(
                        str(first["at"]).replace("Z", "+00:00"))
                    _early_relabel = _t.hour < 11
                except (ValueError, TypeError, KeyError):
                    pass
            if _early_relabel:
                # Iter 719 (user bug — ANSHUL YADAV): NEVER relabel-steal a
                # next-day morning IN that pairs CLEANLY within its own day
                # (e.g. a genuine day shift IN 08:01 → OUT 20:03). Stealing
                # it fabricated an OUT on the night day and left the day
                # shift with "missing IN".
                # Iter 729 (user bug — KAMESHVAR watchman): a "clean" next
                # day of only MINUTES (double walkout scan 08:00 + 08:11
                # re-kinded to IN→OUT by the alternation repair) is NOT a
                # real day shift — it must not block the steal. The clean
                # day now needs ≥2h of paired duty to be protected.
                _b2 = 0
                _clean = True
                _pm2 = 0
                _open2 = None
                for _p2 in nxt_sorted:
                    _k2 = (_p2.get("kind") or "").lower()
                    if _k2 == "in":
                        if _b2 > 0:
                            _clean = False
                            break
                        _b2 += 1
                        try:
                            _open2 = _dt.fromisoformat(str(_p2["at"]).replace("Z", "+00:00"))
                        except (ValueError, TypeError, KeyError):
                            _open2 = None
                    elif _k2 == "out":
                        if _b2 <= 0:
                            _clean = False
                            break
                        _b2 -= 1
                        if _open2 is not None:
                            try:
                                _c2 = _dt.fromisoformat(str(_p2["at"]).replace("Z", "+00:00"))
                                if _c2 > _open2:
                                    _pm2 += int((_c2 - _open2).total_seconds() // 60)
                            except (ValueError, TypeError, KeyError):
                                pass
                        _open2 = None
                if _clean and _b2 == 0 and len(nxt_sorted) >= 2 and _pm2 >= 120:
                    continue  # next day is a self-contained clean shift
            if not _early_relabel:
                continue
        try:
            in_at = _dt.fromisoformat(str(anchor["at"]).replace("Z", "+00:00"))
            out_at = _dt.fromisoformat(str(first["at"]).replace("Z", "+00:00"))
            if out_at <= in_at or (out_at - in_at) > _td(hours=max_hours):
                continue
        except Exception:
            continue
        # ------------------------------------------------------------------
        # Iter 716 (user bug — GAJRAM day showed 24:00 and the next day a
        # dash): the day already held a FULL session (07:58→19:58) and a
        # stray double-scan IN at 20:03 made the stitch steal the NEXT
        # morning's IN 07:56 as its OUT. Two guards:
        #  (a) STRAY ANCHOR — a trailing IN within 30 min of the day's
        #      last completed OUT, on a day that already holds ≥8h of
        #      paired duty, is a double-scan echo — never stitch on it.
        #  (b) TOTAL-DUTY CAP — never stitch a day beyond ``max_hours``
        #      of total paired duty (a 24-hour attendance day is bogus).
        # ------------------------------------------------------------------
        _paired_min = 0
        _last_out_at = None
        _open_at = None
        for p in cur_sorted:
            if p is anchor:
                continue
            _k2 = (p.get("kind") or "").lower()
            if _k2 == "in" and _open_at is None:
                try:
                    _open_at = _dt.fromisoformat(str(p["at"]).replace("Z", "+00:00"))
                except (ValueError, TypeError, KeyError):
                    _open_at = None
            elif _k2 == "out" and _open_at is not None:
                try:
                    _o = _dt.fromisoformat(str(p["at"]).replace("Z", "+00:00"))
                    if _o > _open_at:
                        _paired_min += int((_o - _open_at).total_seconds() // 60)
                        _last_out_at = _o
                except (ValueError, TypeError, KeyError):
                    pass
                _open_at = None
        # Iter 727 (user bug — "day duty + OT: OUT punch अगले दिन दिखता है"):
        # guard (a) wrongly blocked GENUINE night-OT sessions whose OT-IN
        # was punched within 30 min of the duty OUT (e.g. duty OUT 18:00 →
        # OT IN 18:10 → OT OUT 02:00 next day). It now applies ONLY when
        # the next-day candidate is a RELABELLED morning IN (the GAJRAM
        # echo-steal case) — an EXPLICIT machine OUT is always a real
        # session end and must stitch back.
        if (not _explicit_out and _last_out_at is not None
                and _paired_min >= 8 * 60
                and (in_at - _last_out_at) <= _td(minutes=30)):
            continue  # (a) stray double-scan anchor
        # Iter 720b (user bug — HITESH SINGH): genuine DOUBLE DUTY (day
        # 08:28→19:01 + night OT 21:34→06:53 ≈ 19.9h) must still stitch.
        # Iter 728 (user bug — AMIT KUMAR 02-08: duty 08:00→20:00 + OT
        # 20:01→08:00 next morning = 24h REAL double duty showed "missing
        # OUT"): the ~22h cap wrongly blocked genuine 24-hour duty. Like
        # guard (a), the cap now applies ONLY to RELABELLED morning INs
        # (fabrication risk) — an EXPLICIT machine/manual OUT is real
        # punch data and always stitches (session itself is already
        # limited to ``max_hours``).
        if (not _explicit_out
                and _paired_min + int((out_at - in_at).total_seconds() // 60) > (max_hours + 6) * 60):
            continue  # (b) total-duty cap (~22h) for relabel-steals only
        moved = dict(first)
        moved["date"] = dk
        moved["kind"] = "out"
        moved["_cross_day"] = True
        out_map[dk] = cur_sorted + [moved]
        _rest = nxt_sorted[1:]
        # Iter 726 (user bug — night-shift day 2 "Missing Punch" with a
        # lone morning OUT): a SECOND device / echo OUT within 30 min of
        # the moved OUT is the same walkout scan. Left behind it becomes
        # an OUT-only leftover that flags the whole next day as Missing
        # Punch. Consume such echo OUTs along with the stitch.
        while _rest:
            _nk = (_rest[0].get("kind") or "").lower()
            if _nk != "out":
                break
            try:
                _et = _dt.fromisoformat(str(_rest[0]["at"]).replace("Z", "+00:00"))
                if (_et - out_at) > _td(minutes=30):
                    break
            except (ValueError, TypeError, KeyError):
                break
            _rest = _rest[1:]  # echo OUT — drop with the stitch
        out_map[next_dk] = _rest
    return out_map




def split_regular_ot_times(
    day_punches: List[dict],
    split_after_minutes: float,
) -> Tuple[Optional[datetime], Optional[datetime], Optional[datetime], Optional[datetime]]:
    """Split a day's punches into (regular window, OT window).

    Iter 77y-fix — Uses explicit **OUT→IN pair boundaries** rather than
    arithmetic accumulation. Business rule:

      • Regular Duty = the FIRST IN → OUT pair.
      • OT           = the SECOND IN → OUT pair (and every subsequent
                       pair rolled into a single OT window).

    Fallback: if there is only ONE pair but its length exceeds
    ``split_after_minutes`` (i.e. no explicit OT-punch was recorded), we
    still surface an OT slice at the arithmetic threshold so employees
    that stayed past shift-end without re-punching are not missed.

    Returns ``(reg_in, reg_out, ot_in, ot_out)``. Any component may be
    ``None`` when no matching pair exists.
    """
    from datetime import timedelta as _td
    ps = sorted(
        (p for p in day_punches if p.get("at") and (p.get("kind") in ("in", "out"))),
        key=lambda p: p["at"],
    )

    # ------- Pair punches into (IN, OUT) tuples ---------------------------
    pairs: List[Tuple[datetime, datetime]] = []
    open_in: Optional[datetime] = None
    for p in ps:
        try:
            at = datetime.fromisoformat((p["at"] or "").replace("Z", "+00:00"))
        except Exception:
            continue
        kind = (p.get("kind") or "").lower()
        if kind == "in":
            # Consecutive INs → keep the earliest.
            if open_in is None:
                open_in = at
        elif kind == "out":
            if open_in is None:
                continue  # unpaired OUT — skip
            if at > open_in:
                pairs.append((open_in, at))
            open_in = None
    # Any trailing unpaired IN is intentionally discarded (missing OUT).

    if not pairs:
        return None, None, None, None

    reg_in, reg_out = pairs[0]

    # Iter 520 (user: "Set this report as per the FIRM ATTENDANCE POLICY")
    # — OT starts only after the policy's full-day WORKED hours.
    # Classification is by ACCUMULATED WORKED MINUTES across the day's
    # IN→OUT pairs (break gaps between pairs never count), so:
    #   • a lunch-break re-entry stays DUTY, never OT;
    #   • break time can no longer spill into OT (before: the merged
    #     regular WINDOW was wall-clock, so a 1-hr lunch inside an
    #     8-hr-worked day wrongly produced 1 hr OT);
    #   • a pair that crosses the quota is split at the exact crossing.
    if split_after_minutes > 0:
        quota = float(split_after_minutes)
        acc = 0.0
        reg_pairs: List[Tuple[datetime, datetime]] = []
        ot_pairs: List[Tuple[datetime, datetime]] = []
        for pin, pout in pairs:
            dur = (pout - pin).total_seconds() / 60.0
            if acc >= quota:
                ot_pairs.append((pin, pout))
            elif acc + dur <= quota:
                reg_pairs.append((pin, pout))
                acc += dur
            else:
                cut = pin + _td(minutes=quota - acc)
                reg_pairs.append((pin, cut))
                ot_pairs.append((cut, pout))
                acc = quota
        reg_in, reg_out = reg_pairs[0][0], reg_pairs[-1][1]
        if ot_pairs:
            return reg_in, reg_out, ot_pairs[0][0], ot_pairs[-1][1]
        return reg_in, reg_out, None, None

    # No quota configured — legacy rule: 1st pair regular, rest OT.
    if len(pairs) >= 2:
        return reg_in, reg_out, pairs[1][0], pairs[-1][1]
    return reg_in, reg_out, None, None


def dedupe_same_kind_punches(day_punches: List[dict],
                             window_min: float = 5.0) -> List[dict]:
    """Iter 538 (user rule, Punch-Sequence mode) — ignore duplicate punches
    of the SAME kind (in/out) within ``window_min`` minutes, regardless of
    which machine recorded them. Keeps the FIRST punch of each burst.
    Iter 555 — manual_admin punches (deliberate admin repairs) are never
    dropped."""
    out: List[dict] = []
    last: Dict[str, datetime] = {}
    for p in sorted(day_punches, key=lambda x: x.get("at") or ""):
        kind = (p.get("kind") or "").lower()
        try:
            at = datetime.fromisoformat(
                (p.get("at") or "").replace("Z", "+00:00"))
        except ValueError:
            out.append(p)
            continue
        prev = last.get(kind)
        if (prev is not None
                and str(p.get("source") or "") != "manual_admin"
                and (at - prev).total_seconds() < window_min * 60.0):
            continue
        last[kind] = at
        out.append(p)
    return out


def worked_minutes_in_window(
    day_punches: List[dict],
    w_from: Optional[datetime],
    w_to: Optional[datetime],
) -> float:
    """Iter 520 — SUM of paired IN→OUT durations clipped to
    ``[w_from, w_to]``. Unlike ``(w_to - w_from)`` this EXCLUDES the break
    gaps between pairs, so duty/OT hours follow the firm attendance
    policy's WORKED-hours rule instead of the wall-clock window."""
    if not w_from or not w_to or w_to <= w_from:
        return 0.0
    ps = sorted(
        (p for p in day_punches if p.get("at") and (p.get("kind") in ("in", "out"))),
        key=lambda p: p["at"],
    )
    total = 0.0
    open_in: Optional[datetime] = None
    for p in ps:
        try:
            at = datetime.fromisoformat((p["at"] or "").replace("Z", "+00:00"))
        except Exception:
            continue
        kind = (p.get("kind") or "").lower()
        if kind == "in":
            if open_in is None:
                open_in = at
        elif kind == "out":
            if open_in is not None and at > open_in:
                lo, hi = max(open_in, w_from), min(at, w_to)
                if hi > lo:
                    total += (hi - lo).total_seconds() / 60.0
            open_in = None
    return total


def compute_day_punch_metrics(
    day_punches: List[dict],
    shift_start: Optional[str] = None,
    shift_end: Optional[str] = None,
    grace_minutes: int = 0,
) -> dict:
    """Iter 236 — Attendance Engine Overhaul metrics for ONE employee-day.

    Returns a dict with:
      * ``break_minutes`` — total gap time between an OUT punch and the
        NEXT IN punch (time spent outside between paired sessions).
      * ``late_minutes``  — minutes the FIRST IN arrived after the shift
        start. 0 when arrival is within ``grace_minutes``; beyond grace
        the FULL lateness (from shift start) is counted.
      * ``early_minutes`` — minutes the LAST OUT left before shift end.

    Night shifts crossing midnight are handled with circular (±12 h)
    time-of-day distance so a 22:00–06:00 shift computes correctly.
    """
    ps = sorted(
        (p for p in day_punches if p.get("at") and (p.get("kind") in ("in", "out"))),
        key=lambda p: p["at"],
    )
    sessions: List[Tuple[datetime, datetime]] = []
    open_in: Optional[datetime] = None
    for p in ps:
        try:
            at = datetime.fromisoformat((p["at"] or "").replace("Z", "+00:00"))
        except Exception:
            continue
        kind = (p.get("kind") or "").lower()
        if kind == "in":
            if open_in is None:
                open_in = at
        elif kind == "out":
            if open_in is not None and at > open_in:
                sessions.append((open_in, at))
            open_in = None
    out = {"break_minutes": 0, "late_minutes": 0, "early_minutes": 0}
    if not sessions:
        return out
    # Break HRS = sum of OUT → next-IN gaps between consecutive sessions.
    br = 0.0
    for i in range(1, len(sessions)):
        gap = (sessions[i][0] - sessions[i - 1][1]).total_seconds() / 60.0
        if gap > 0:
            br += gap
    out["break_minutes"] = int(round(br))

    def _circ(diff: int) -> int:
        if diff > 720:
            diff -= 1440
        elif diff < -720:
            diff += 1440
        return diff

    st = _hhmm_to_min(shift_start)
    en = _hhmm_to_min(shift_end)
    first_in = sessions[0][0]
    last_out = sessions[-1][1]
    if st is not None:
        d = _circ((first_in.hour * 60 + first_in.minute) - st)
        if d > max(0, int(grace_minutes or 0)):
            out["late_minutes"] = d
    if en is not None:
        d = _circ(en - (last_out.hour * 60 + last_out.minute))
        if d > 0:
            out["early_minutes"] = d
    return out


def apply_weekoff_rules_for_date(policy: dict, user: dict, date_iso: str) -> dict:
    """Iter 741 — ALTERNATE / OCCURRENCE-BASED WEEKOFF (additive).

    Returns the policy unchanged when no active ``weekoff_rules`` apply
    (ZERO regression for fixed weekly off), otherwise a shallow copy whose
    ``weekly_off_days`` reflects THIS specific date:
      * occurrence — weekday off only on the configured 1st..5th occurrence
      * alternate  — weekday off only in "off" weeks of the repeating cycle
    Priority: an explicit per-employee ``weekly_off_days_override`` always
    wins (rules skipped). The attendance engine itself is untouched — it
    still just reads ``weekly_off_days``.
    """
    wr = (policy or {}).get("weekoff_rules") or None
    if not wr or not wr.get("active") or wr.get("type") == "fixed":
        return policy
    _ov = (user or {}).get("weekly_off_days_override")
    if isinstance(_ov, list) and len(_ov) > 0:
        return policy  # employee override has highest priority
    ef, et = wr.get("effective_from"), wr.get("effective_to")
    if (ef and date_iso < ef) or (et and date_iso > et):
        return policy
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return policy
    wd = d.weekday()
    off_days = set(policy.get("weekly_off_days") or [])
    if wr.get("type") == "occurrence":
        occ_map = wr.get("occurrence") or {}
        ruled = {int(k) for k in occ_map.keys()}
        occurrence_no = (d.day - 1) // 7 + 1
        new_off = {x for x in off_days if x not in ruled}  # non-ruled fixed days stay
        for k, v in occ_map.items():
            kwd = int(k)
            if kwd != wd:
                continue
            if v == "all" or (isinstance(v, list) and occurrence_no in v):
                new_off.add(kwd)
        if new_off == off_days:
            return policy
        patched = dict(policy)
        patched["weekly_off_days"] = sorted(new_off)
        return patched
    if wr.get("type") == "alternate":
        alt = wr.get("alternate") or {}
        try:
            cs = datetime.strptime(alt.get("cycle_start"), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return policy
        pat = alt.get("pattern") or ["off", "work"]
        wds = set(alt.get("weekdays") or [])
        week_idx = ((d - cs).days // 7) % len(pat) if d >= cs else None
        is_off_week = week_idx is not None and pat[week_idx] == "off"
        new_off = set(off_days)
        for x in wds:
            if is_off_week:
                new_off.add(x)
            else:
                new_off.discard(x)
        if new_off == off_days:
            return policy
        patched = dict(policy)
        patched["weekly_off_days"] = sorted(new_off)
        return patched
    return policy


def compute_textile_day(
    punches: List[dict],
    policy: dict,
    user: dict,
    day_weekday: int,
    is_holiday: bool = False,
) -> dict:
    """Compute the attendance summary for a single day under a textile
    policy. Returns a dict with:

    * ``duty_minutes`` – total on-duty minutes (rounded per policy).
    * ``present_days`` – 0.0 / 0.5 / 1.0 (Policy 2 may return 0 for a
      week-off day even when the employee actually worked).
    * ``ot_minutes`` – overtime minutes.
    * ``ot_applicable`` – whether the OT paid or just tracked.
    * ``full_day_pay_weekoff`` – True if Full Day Payment kicks in
      (Policy 1 only).
    * ``variant`` – ``"policy_1"`` | ``"policy_2"`` | ``None``.
    * ``notes`` – human-readable trail for debugging.

    Args:
        punches: List of attendance records for the day. Each must have
            ``kind`` ("in"|"out") and an ISO ``at``. Order-independent —
            we sort by ``at`` internally. Records with kind other than
            "in"/"out" are ignored.
        policy: The company's ``attendance_policy`` dict.
        user: The employee document (needs at least the textile flags).
        day_weekday: Python's ``date.weekday()`` (0=Mon .. 6=Sun) for
            the day being computed.
    """
    variant = (policy.get("policy_variant") or "").strip() or None
    weekly_offs = set(policy.get("weekly_off_days") or [])
    is_weekly_off = day_weekday in weekly_offs

    rounding = int(policy.get("duty_hours_rounding_minutes") or 0)
    standard_hrs = float(
        policy.get("standard_working_hours")
        or policy.get("full_day_hours")
        or 8.0
    )
    half_hrs = float(policy.get("half_day_hours") or 4.0)

    ot_applicable_user = user.get("ot_applicable")
    if ot_applicable_user is None:
        ot_applicable_user = True  # default ON
    # Iter 77 - Per-employee ATTENDANCE POLICY OVERRIDE can flip OT allowed.
    # ``attendance_policy_override.ot_allowed`` (bool) wins over the legacy
    # ``ot_applicable`` flag when it is set.
    _ov = user.get("attendance_policy_override") or {}
    if _ov.get("ot_allowed") is not None:
        ot_applicable_user = bool(_ov.get("ot_allowed"))
    # Iter 142 — Firm Master gate: when the firm's salary_process.ot_allowed
    # is OFF, NO employee of the firm accrues OT (per-employee flag ignored).
    if policy.get("firm_ot_allowed") is False:
        ot_applicable_user = False

    week_off_full_day_user = bool(user.get("week_off_full_day"))
    week_off_govt_holiday_user = bool(user.get("week_off_govt_holiday_enabled"))

    # Sort and pair up IN/OUT punches
    sorted_p = sorted(
        [p for p in (punches or []) if p.get("kind") in ("in", "out")],
        key=lambda p: p.get("at") or "",
    )
    total_min = 0.0
    open_in: Optional[datetime] = None
    for p in sorted_p:
        try:
            when = datetime.fromisoformat((p["at"] or "").replace("Z", "+00:00"))
        except Exception:
            continue
        if p["kind"] == "in":
            open_in = when
        elif p["kind"] == "out" and open_in is not None:
            delta = (when - open_in).total_seconds() / 60.0
            if delta > 0:
                total_min += delta
            open_in = None
    # Rounding
    total_min = _round_minutes(total_min, rounding)

    notes: List[str] = []
    duty_hrs = total_min / 60.0
    present_days = 0.0
    ot_min = 0.0
    full_day_pay_weekoff = False

    if variant == "policy_2":
        # 8 hrs = 1 present day. Extras → OT.
        # If week-off/govt holiday employee works on a weekly-off day →
        # no present day, ALL duty → OT.
        if is_weekly_off and week_off_govt_holiday_user and total_min > 0:
            present_days = 0.0
            ot_min = total_min
            notes.append("policy_2: worked on week-off/govt holiday → all OT")
        else:
            if duty_hrs >= standard_hrs:
                present_days = 1.0
                extra = duty_hrs - standard_hrs
                ot_min = max(0.0, extra * 60.0)
            else:
                # Iter 98 — user rule change: when total working hours are
                # LESS than the standard (8 hrs), no Half Day / Absent is
                # given — ALL worked hours are counted as OT hours instead.
                present_days = 0.0
                ot_min = total_min
                if total_min > 0:
                    notes.append("policy_2: under standard hours → all hours as OT")
            if not ot_applicable_user:
                ot_min = 0.0
                if duty_hrs > 0 and duty_hrs != standard_hrs:
                    notes.append("policy_2: OT hours ignored (ot not applicable)")
    elif variant == "policy_1":
        # Iter 77 - Under Policy 1, OT is ALWAYS folded into Total Duty Hours.
        # We no longer surface a separate ``ot_minutes``; the salary process
        # picks up the full duty figure and rates are applied per-hour so
        # there is no double-counting.
        # Iter 77 - OT cap rules (see :func:`compute_textile_day` docstring):
        # ``first_in_hour`` peek kept for future use (evening-shift bonuses).
        _first_in_hour: Optional[int] = None
        for p in sorted_p:
            if p["kind"] == "in":
                try:
                    _first_in_hour = datetime.fromisoformat(
                        (p["at"] or "").replace("Z", "+00:00")
                    ).hour
                except Exception:
                    _first_in_hour = None
                break
        # Iter 77 - OT cap rules:
        #   * OT ALLOWED  -> up to 24h (Day + Night combo). Anything beyond
        #     the 24h window is considered a NEW shift starting the next
        #     morning; the pair-and-cap loop above already ended before
        #     midnight so we simply cap at 24h here.
        #   * OT NOT allowed -> employee cannot exceed the standard shift
        #     hours; any extra minutes are dropped from the duty total.
        # Iter 78 — Week-off days are FREE from the standard-hours cap:
        # workers on their day off can put in more than a normal shift's
        # worth of hours (that's the whole point of the week-off min-hours
        # policy). OT ALLOWED still caps at 24h.
        max_hours = 24.0 if (ot_applicable_user or is_weekly_off) else standard_hrs

        # Cap duty hours by max_hours
        if duty_hrs > max_hours:
            notes.append(f"policy_1: duty capped at {max_hours}h (was {duty_hrs:.2f})")
            duty_hrs = max_hours
            total_min = duty_hrs * 60.0

        # OT is always merged into Total Duty Hours for Policy 1
        ot_min = 0.0

        # Iter 77d - Week-off policy enhancements:
        #   * Firm-level ``week_off_min_working_hours`` (float, default 0).
        #     When an employee works on a weekly-off day and their duty
        #     hours >= this threshold, they get a FULL DAY attendance
        #     regardless of ``week_off_full_day_user``. If threshold is 0
        #     (default), any positive duty triggers the legacy path.
        #   * Per-employee ``week_off_paid_when_absent`` (bool, override).
        #     Employees on paid-holiday scheme still get 1.0 present-day
        #     credit on their weekly-off day even if they don't punch.
        weekoff_min_hours = float(policy.get("week_off_min_working_hours") or 0.0)
        weekoff_paid_when_absent = bool(_ov.get("week_off_paid_when_absent"))

        if is_weekly_off and total_min > 0:
            # Employee actually worked on their week-off day.
            meets_min = duty_hrs >= weekoff_min_hours if weekoff_min_hours > 0 else True
            if meets_min:
                # New rule (Iter 77d): threshold reached → full-day
                # attendance & payment on the week-off day. This subsumes
                # the legacy ``week_off_full_day_user`` behaviour so
                # existing setups keep working.
                present_days = 1.0
                full_day_pay_weekoff = True
                if weekoff_min_hours > 0:
                    notes.append(
                        f"policy_1: week-off worked >= {weekoff_min_hours}h min "
                        f"({duty_hrs:.2f}h) -> full-day attendance"
                    )
                else:
                    notes.append("policy_1: week-off worked -> full-day payment (OT merged into duty)")
            elif week_off_full_day_user:
                # Below threshold but employee is on the legacy
                # "always full-day if works on week-off" scheme.
                present_days = 1.0
                full_day_pay_weekoff = True
                notes.append("policy_1: week-off worked (legacy full-day flag) -> full-day payment")
            else:
                # Below threshold and no full-day flag → count hours as
                # duty but no present credit.
                present_days = 0.0
                notes.append(
                    f"policy_1: week-off worked but under min "
                    f"({duty_hrs:.2f}h < {weekoff_min_hours}h) -> no present credit"
                )
        elif is_weekly_off and total_min == 0 and weekoff_paid_when_absent:
            # New rule (Iter 77d): paid holiday scheme - employee gets a
            # present day even without punching on their week-off.
            present_days = 1.0
            full_day_pay_weekoff = True
            notes.append("policy_1: week-off paid-when-absent -> full-day credit without punches")
        else:
            if duty_hrs >= standard_hrs:
                present_days = 1.0
            elif duty_hrs >= half_hrs:
                present_days = 0.5
            else:
                present_days = 0.0
            if duty_hrs > standard_hrs:
                notes.append(
                    f"policy_1: OT merged into duty ({duty_hrs:.2f}h total, "
                    f"{duty_hrs - standard_hrs:.2f}h beyond standard)"
                )
    else:
        # Non-textile fallback — mirror Policy 2's simple math without the
        # week-off transformation. Kept so this helper is safe to call
        # for any company.
        if duty_hrs >= standard_hrs:
            present_days = 1.0
            extra = duty_hrs - standard_hrs
            ot_min = max(0.0, extra * 60.0)
        elif duty_hrs >= half_hrs:
            present_days = 0.5
        if not ot_applicable_user:
            ot_min = 0.0

    # Iter 200 — Policy Master Sub Points (user directives):
    #   • Week-off worked + weekoff_present_add_ot → ALL hours go to OT,
    #     the day is NOT counted present ("if Week off Allowed Do not
    #     Count in Present").
    #   • Holiday-Master day worked + holiday_present_add_ot → the day
    #     counts PRESENT and the hours ALSO go to the OT column.
    _pm = policy.get("policy_master") or {}
    # Iter 205 (user request) — Week-Off Worked Attendance module: when a
    # mode is configured it takes precedence over the legacy week-off
    # sub-point below.
    _wow = policy.get("week_off_worked") or {}
    _wow_mode = str(_wow.get("mode") or "")
    if total_min > 0 and is_weekly_off and _wow_mode:
        _worked_h = total_min / 60.0
        _half_t = float(_wow.get("half_day_threshold") or 4.0)
        _full_t = float(_wow.get("full_day_threshold") or 8.0)
        _ot_after = float(_wow.get("ot_after") or 0.0)
        full_day_pay_weekoff = False
        if _wow_mode == "ot_only":
            present_days = 0.0
            ot_min = total_min if ot_applicable_user else 0.0
        elif _wow_mode == "half_day_ot":
            if _worked_h >= _half_t:
                present_days = 0.5
                _cut = _ot_after if _ot_after > 0 else _half_t
            else:
                present_days = 0.0
                _cut = 0.0
            ot_min = max(0.0, (_worked_h - _cut) * 60.0) if ot_applicable_user else 0.0
        elif _wow_mode == "full_day_ot":
            if _worked_h >= _full_t:
                present_days = 1.0
                full_day_pay_weekoff = True
                _cut = _ot_after if _ot_after > 0 else _full_t
            elif _worked_h >= _half_t:
                present_days = 0.5
                _cut = _half_t
            else:
                present_days = 0.0
                _cut = 0.0
            ot_min = max(0.0, (_worked_h - _cut) * 60.0) if ot_applicable_user else 0.0
        elif _wow_mode == "full_day_min_hours":
            # Iter 207 — Full Day Attendance (Minimum Hours) on week-off.
            _daily_h = float(policy.get("full_day_hours")
                             or policy.get("standard_working_hours") or 8.0)
            _min_h = float(_wow.get("min_hours") or 0.0) or (_daily_h * 0.5)
            if _worked_h >= _min_h:
                present_days = 1.0
                full_day_pay_weekoff = True
                _cut = _ot_after if _ot_after > 0 else _daily_h
                ot_min = max(0.0, (_worked_h - _cut) * 60.0) if ot_applicable_user else 0.0
            else:
                # Below minimum: hours stay plain duty — no present/OT.
                present_days = 0.0
                ot_min = 0.0
        elif _wow_mode == "hourly":
            # Hourly Conversion — hours stay plain duty; no present/OT.
            present_days = 0.0
            ot_min = 0.0
        if _wow.get("double_ot") and ot_min > 0:
            ot_min *= 2.0
        notes.append(f"week_off_worked: mode={_wow_mode} ({_worked_h:.2f}h)")
    elif total_min > 0 and is_weekly_off and _pm.get("weekoff_present_add_ot"):
        present_days = 0.0
        full_day_pay_weekoff = False
        ot_min = total_min if ot_applicable_user else 0.0
        notes.append("pm: week-off worked → hours to OT, not counted present")
    if total_min > 0 and is_holiday and _pm.get("holiday_present_add_ot"):
        present_days = max(present_days, 1.0)
        ot_min = total_min if ot_applicable_user else 0.0
        notes.append("pm: holiday worked → present day + hours to OT")

    return {
        "variant": variant,
        "duty_minutes": round(total_min, 2),
        "duty_hours": round(total_min / 60.0, 2),
        "present_days": present_days,
        "ot_minutes": round(ot_min, 2),
        "ot_hours": round(ot_min / 60.0, 2),
        "ot_applicable": bool(ot_applicable_user),
        "full_day_pay_weekoff": full_day_pay_weekoff,
        "is_weekly_off": is_weekly_off,
        "is_holiday": bool(is_holiday),
        "notes": notes,
    }


def _validate_business_category(
    category: Optional[str], subcategory: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    """Normalise & validate a (category, subcategory) pair against the master
    taxonomy. Returns the canonical (category_key, subcategory_label) tuple.
    Empty strings are treated as None so the caller can persist a clean value.
    """
    cat = (category or "").strip().lower() or None
    sub = (subcategory or "").strip() or None
    if cat is None:
        return None, None
    if cat not in _BUSINESS_CATEGORY_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown business category '{category}'. Please pick from the list.",
        )
    allowed_subs = _BUSINESS_CATEGORY_MAP[cat].get("subcategories") or []
    if allowed_subs:
        if not sub:
            raise HTTPException(
                status_code=400,
                detail=f"Please choose a sub-type under {_BUSINESS_CATEGORY_MAP[cat]['label']}.",
            )
        # Case-insensitive match; store the canonical label
        match = next((s for s in allowed_subs if s.lower() == sub.lower()), None)
        if not match:
            raise HTTPException(
                status_code=400,
                detail=f"'{sub}' is not a recognised sub-type under {_BUSINESS_CATEGORY_MAP[cat]['label']}.",
            )
        sub = match
    else:
        sub = None
    return cat, sub


def _business_category_label(
    category: Optional[str], subcategory: Optional[str]
) -> str:
    """Human-readable label like 'Industry — Textile' used in emails and
    the legacy nature_of_business text field."""
    if not category:
        return ""
    entry = _BUSINESS_CATEGORY_MAP.get(category)
    if not entry:
        return category
    return f"{entry['label']} — {subcategory}" if subcategory else entry["label"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def holiday_dates_for_company(company_id: Optional[str]) -> set:
    """YYYY-MM-DD dates from the Holiday Master (firm + global scope)."""
    out: set = set()
    async for m_ in db.masters.find(
        {"type": "holiday",
         "company_id": {"$in": [company_id, "__global__", None]}},
        {"_id": 0, "date": 1},
    ):
        if m_.get("date"):
            out.add(str(m_["date"])[:10])
    return out


# Iter 144 — project-wide PUNCH TIME convention: attendance `at` timestamps
# store IST WALL-CLOCK time labelled as UTC ("+00:00"). Machine punches
# (ADMS live + .dat/.TXT imports) and admin manual entries already follow
# this; app self-punches now do too, and every display (backend strftime,
# frontend verbatim slice) shows the stored clock without tz conversion.
IST_TZ = timezone(timedelta(hours=5, minutes=30))


def ist_wallclock_now() -> datetime:
    """Current IST wall-clock, labelled UTC (punch storage convention)."""
    return datetime.now(IST_TZ).replace(tzinfo=timezone.utc)


def ist_wallclock_iso() -> str:
    return ist_wallclock_now().isoformat()


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


async def get_user_from_token(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = session.get("expires_at")
    if isinstance(expires_at, str):
        exp_dt = datetime.fromisoformat(expires_at)
    else:
        exp_dt = expires_at
    if exp_dt.tzinfo is None:
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    now_utc = datetime.now(timezone.utc)
    if exp_dt < now_utc:
        raise HTTPException(status_code=401, detail="Session expired")
    user = await db.users.find_one(
        {"user_id": session["user_id"]},
        # Iter 307 (perf) — NEVER drag the base64 profile photo through
        # every authenticated request; endpoints that need it fetch it
        # explicitly (/auth/me, punch face-compare, photo endpoints).
        {"_id": 0, "profile_photo_base64": 0},
    )
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    # SEC-004 — SLIDING EXPIRY: any authenticated request extends the
    # session (auto-extend while active). Iter 295 — the window is ROLE
    # BASED: employees slide 90 days (PWA never auto-logs-out in normal
    # use); admin/staff sessions keep the strict 12-hour window. Writes
    # are throttled by SESSION_SLIDE_THROTTLE_MINUTES; sessions longer
    # than their role's TTL are clamped on first use. Conditional filter
    # on the old expires_at prevents duplicate concurrent writes.
    _full_ttl = timedelta(hours=_session_ttl_hours_for_role(user.get("role")))
    _remaining = exp_dt - now_utc
    if (_remaining < _full_ttl - timedelta(minutes=SESSION_SLIDE_THROTTLE_MINUTES)
            or _remaining > _full_ttl):
        await db.user_sessions.update_one(
            {"session_token": token, "expires_at": expires_at},
            {"$set": {"expires_at": now_utc + _full_ttl}},
        )
    # RBAC Phase 1 — company_staff (HR Manager / Payroll Manager / ...) are
    # NORMALIZED to a firm-scoped company_admin so every existing endpoint
    # keeps its company scoping. Their permission subset (from the
    # company_roles matrix) rides along and is enforced by
    # require_permission + frontend nav gating. Fail-safe: missing role
    # config → empty permissions (no access), never full access.
    if user.get("role") == "company_staff":
        crole = await db.company_roles.find_one(
            {"role_id": user.get("company_role_id") or "", "company_id": user.get("company_id")},
            {"_id": 0},
        )
        user["is_company_staff"] = True
        user["staff_role_name"] = (crole or {}).get("name") or "Staff"
        user["staff_permissions"] = (crole or {}).get("permissions") or []
        user["role"] = "company_admin"
    elif user.get("role") == "employee" and user.get("is_company_staff") \
            and str(session.get("auth_method") or "").startswith("staff_portal"):
        # Iter 220 — EMPLOYEE LINKED AS STAFF USER: the employee keeps
        # their existing account + credentials; when they sign in on the
        # ADMIN portal (session method staff_portal*) they are normalized
        # to a firm-scoped company_admin with their staff-role permission
        # subset. Their employee-app sessions are completely unaffected.
        crole = await db.company_roles.find_one(
            {"role_id": user.get("company_role_id") or "", "company_id": user.get("company_id")},
            {"_id": 0},
        )
        user["staff_role_name"] = (crole or {}).get("name") or "Staff"
        user["staff_permissions"] = (crole or {}).get("permissions") or []
        user["role"] = "company_admin"
    elif user.get("role") == "employee" and user.get("is_company_staff"):
        # Employee-app (PWA) session of a staff-linked employee — the role
        # stays "employee" so all PWA flows are unaffected, but the staff
        # role + permission subset ride along so the app can show the
        # "Staff Access" entry (Profile tab).
        crole = await db.company_roles.find_one(
            {"role_id": user.get("company_role_id") or "", "company_id": user.get("company_id")},
            {"_id": 0},
        )
        user["staff_role_name"] = (crole or {}).get("name") or "Staff"
        user["staff_permissions"] = (crole or {}).get("permissions") or []
    if user.get("role") != "super_admin":
        if user.get("disabled"):
            raise HTTPException(status_code=403, detail="Your account has been disabled. Please contact your admin.")
        if user.get("company_id"):
            company = await db.companies.find_one(
                {"company_id": user["company_id"]},
                {"_id": 0, "enabled": 1, "name": 1},
            )
            if company and company.get("enabled") is False:
                raise HTTPException(
                    status_code=403,
                    detail=f"Access to '{company.get('name') or 'this company'}' has been temporarily suspended. Please contact S.K. Sharma & Co.",
                )
    return user


# --------------------------------------------------------------------------- 
# Sub-admin permissions (Iter 57)
# --------------------------------------------------------------------------- 
# Sub-admins are delegated super-admin accounts created BY a super_admin.
# Each sub-admin carries a list of permission keys + a company scope
# (all-companies or a restricted subset). At the backend level, sub_admins
# have the same reach as super_admin (they can call all admin endpoints
# EXCEPT the sub-admin management endpoints themselves). Frontend enforces
# the UI-level restrictions based on the permissions list.
SUB_ADMIN_PERMISSION_KEYS: List[str] = [
    "companies:read", "companies:write",
    "company_requests:read", "company_requests:write",
    "employees:read", "employees:write",
    "attendance_policy:read", "attendance_policy:write",
    "punch_approvals:read", "punch_approvals:write",
    "biometric_devices:read", "biometric_devices:write",
    "attendance_review:read", "attendance_review:write",
    "salary_process:read", "salary_process:write",
    "compliance_salary:read", "compliance_salary:write",
    "messages:read", "messages:write",
    "tickets:read", "tickets:write",
]


# --------------------------------------------------------------------------- 
# Employer (company_admin) access rights (Iter 58)
# --------------------------------------------------------------------------- 
# Super admin can restrict which portions of the Company Admin portal each
# firm's admins can access. Stored on companies.employer_permissions[].
# Default (missing / empty list) → general features enabled (backward
# compat) EXCEPT opt-in features: compliance_salary + salary_process
# (Actual/Arrear payroll) which require an explicit grant (iter 62/125).
EMPLOYER_PERMISSION_KEYS: List[str] = [
    "employees:read", "employees:write",
    "attendance_policy:read", "attendance_policy:write",
    "punch_approvals:read", "punch_approvals:write",
    "biometric_devices:read", "biometric_devices:write",
    "attendance_review:read", "attendance_review:write",
    "salary_process:read", "salary_process:write",
    "compliance_salary:read", "compliance_salary:write",
    "messages:read", "messages:write",
    "tickets:read", "tickets:write",
    "portal_credentials:read", "portal_credentials:write",
]


def require_role(user: dict, roles: List[str]):
    role = user.get("role")
    # Sub-admins inherit super_admin's reach across the admin surface — so
    # any endpoint that admits `super_admin` also admits `sub_admin` (unless
    # the endpoint explicitly disallows it, e.g. the sub-admin management
    # endpoints themselves which reject sub_admin via role != "super_admin").
    if role == "sub_admin" and "super_admin" in roles:
        return
    if role not in roles:
        raise HTTPException(status_code=403, detail="Forbidden")


def require_super_admin_strict(user: dict):
    """Reject anything except a real super_admin. Used by the sub-admin
    management endpoints so a sub_admin can't elevate themselves or create
    other sub-admins."""
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only super admin can perform this action")


def require_permission(user: dict, permission: str):
    """Iter 57 — Fine-grained sub-admin permission gate.

    Rules:
      * super_admin  — always allowed (root of the admin hierarchy)
      * company_admin — always allowed within their own company (existing
        endpoints already scope company_admin themselves; this helper is
        primarily for the sub_admin role which does NOT have an intrinsic
        company scope).
      * sub_admin — allowed only if `permission` is in their
        ``sub_admin_permissions`` list. Denied otherwise.
      * employee — always denied.
    """
    role = user.get("role")
    if role == "super_admin":
        return
    if role == "company_admin":
        # RBAC Phase 1 — company_staff (normalized to company_admin) are
        # gated by their role's permission matrix. Real company_admins
        # keep free reign (unchanged behavior).
        if user.get("is_company_staff"):
            if permission in (user.get("staff_permissions") or []):
                return
            raise HTTPException(
                status_code=403,
                detail=f"Your role '{user.get('staff_role_name') or 'Staff'}' doesn't have the '{permission}' permission.",
            )
        return
    if role == "sub_admin":
        # Iter 212 — user directive: Sub Super Admins get ALL features
        # (deputy of the super admin). Per-button restrictions are still
        # possible via ``menu_rights`` on the Sub Admins screen; the
        # granular permission matrix no longer blocks API access.
        return
    raise HTTPException(status_code=403, detail="Forbidden")


async def require_employer_permission(user: dict, permission: str, db):
    """Iter 62 — OPT-IN gate for company_admin.

    Unlike ``require_permission`` which grants company_admin free reign,
    this helper enforces that the FIRM's ``employer_permissions`` array
    explicitly contains the given key. Currently used for compliance
    features (PF/ESIC/TDS) which must be hidden by default from the
    Employer Portal until the Super Admin flips the switch.

    Rules:
      * super_admin, sub_admin — always allowed
      * company_admin — allowed only when the firm's employer_permissions
        contains ``permission``
      * employee — denied
    """
    role = user.get("role")
    if role in ("super_admin", "sub_admin"):
        return
    if role != "company_admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    cid = user.get("company_id")
    if not cid:
        raise HTTPException(status_code=403, detail="No company scope on this admin")
    company = await db.companies.find_one(
        {"company_id": cid}, {"_id": 0, "employer_permissions": 1},
    ) or {}
    perms = set(company.get("employer_permissions") or [])
    if permission in perms:
        return
    raise HTTPException(
        status_code=403,
        detail=(
            f"Your firm doesn't have the '{permission}' feature enabled. "
            "Ask the Super Admin to enable it from the Employer Access Rights panel."
        ),
    )


def apply_sub_admin_company_scope(user: dict, query: dict) -> dict:
    """If ``user`` is a sub_admin with restricted company scope, add a
    ``company_id`` $in filter to the given Mongo query dict and return it.
    Otherwise return the query unchanged."""
    if user.get("role") == "sub_admin":
        scope = user.get("sub_admin_company_scope") or "all"
        if scope == "restricted":
            allowed = user.get("sub_admin_company_ids") or []
            # Force-restrict — an empty allow-list evaluates to a query that
            # matches nothing, which is the safe default.
            existing = query.get("company_id")
            if existing is None:
                query["company_id"] = {"$in": allowed}
            elif isinstance(existing, str):
                if existing not in allowed:
                    # Force impossible match
                    query["company_id"] = "__forbidden__"
            else:
                # already a dict / complex filter — intersect via $and
                query.setdefault("$and", []).append(
                    {"company_id": {"$in": allowed}}
                )
    return query


def sub_admin_can_touch_company(user: dict, company_id: Optional[str]) -> bool:
    """Return True if the sub-admin's company scope allows acting on the
    given company_id. Super_admin / company_admin are handled by their own
    scope rules — this helper is a sub_admin only guard.
    """
    if user.get("role") != "sub_admin":
        return True
    scope = user.get("sub_admin_company_scope") or "all"
    if scope == "all":
        return True
    if not company_id:
        return True  # global operations (e.g., system-wide list) — caller handles
    return company_id in (user.get("sub_admin_company_ids") or [])


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    """Iter 64 — Fast startup for Kubernetes health checks.

    Only lightweight index creation runs synchronously so uvicorn can
    accept traffic within a couple of seconds. Heavy backfills and the
    long-running auto-close loop are deferred to a background task.
    """
    async def _bg_backfill():
        # Let uvicorn bind and health-checks succeed before we begin the
        # heavier one-shot work below.
        await asyncio.sleep(2)
        # SEC-003 — encrypt any legacy plaintext portal passwords (idempotent).
        try:
            from routes.firm_master import migrate_portal_secrets
            await migrate_portal_secrets()
        except Exception:
            logger.exception("[startup] SEC-003 portal secret migration failed")
        # Iter 412b (user approved) — one-time cleanup: GLOBAL category
        # groups (LABOUR/STAFF/…) must not carry member lists; a stale
        # entry pointing at one firm's employee blanked every other firm's
        # group-wise report. Idempotent via migration_flags marker.
        try:
            flag = await db.migration_flags.find_one(
                {"_id": "iter412_global_group_member_wipe"})
            if not flag:
                r = await db.masters.update_many(
                    {"type": "group",
                     "company_id": {"$in": ["__global__", None]},
                     "member_user_ids.0": {"$exists": True}},
                    {"$set": {"member_user_ids": [],
                              "member_wipe_note": "iter412 stale-member cleanup"}},
                )
                await db.migration_flags.insert_one(
                    {"_id": "iter412_global_group_member_wipe",
                     "applied_at": now_iso(), "modified": r.modified_count})
                logger.info("[startup] iter412 global-group member wipe: %s doc(s)",
                            r.modified_count)
        except Exception:
            logger.exception("[startup] iter412 global-group cleanup failed")
        await _run_startup_backfill()

    # Only the small index creation on startup path (should complete in
    # <500ms on a warm cluster). Everything else is deferred.
    try:
        await _create_core_indexes()
    except Exception:
        logger.exception("[startup] core index creation failed")

    asyncio.create_task(_bg_backfill())
    asyncio.create_task(_bg_apply_textile_default())
    asyncio.create_task(_bg_enforce_geofence_defaults())

    async def _bg_speed_indexes():
        """Iter 523c — the Iter-521 'speed' indexes MUST build in the
        BACKGROUND: building them synchronously in startup blocked uvicorn
        from answering for minutes on the live VPS (large attendance /
        biometric_unmapped collections) and the deploy health-check
        reported 'BACKEND NOT ANSWERING'."""
        await asyncio.sleep(5)
        try:
            # grid punch load: user_id $in + date range, sorted (user_id, at)
            await db.attendance.create_index(
                [("user_id", 1), ("date", 1), ("at", 1)], background=True)
            # Iter 714 (user: Attendance Report slow) — the grid-cache dirty
            # probe sorts by created_at per firm on EVERY report open; with
            # no supporting index it collection-scanned large live VPS data.
            await db.attendance.create_index(
                [("company_id", 1), ("created_at", -1)], background=True)
            # Iter 722 (perf) — Employee List sorts by created_at per firm;
            # without this index large firms did an in-memory sort per open.
            await db.users.create_index(
                [("company_id", 1), ("role", 1), ("created_at", -1)],
                background=True)
            # punch-log NOT-FOUND rows + sync-dashboard machine_only group
            await db.biometric_unmapped.create_index(
                [("device_serial", 1), ("at", -1)], background=True)
            await db.biometric_unmapped.create_index(
                [("at", -1)], background=True)
            await db.biometric_unmapped.create_index(
                [("device_user_id", 1), ("device_serial", 1)], background=True)
            # machine-user harvest lookups (name-in-machine / never-punched)
            await db.biometric_machine_users.create_index(
                [("device_serial", 1), ("pin", 1)], background=True)
            await db.biometric_machine_users.create_index(
                "company_id", background=True)
            # biometric PIN → employee master matching
            await db.users.create_index(
                [("company_id", 1), ("bio_code", 1)], background=True)
            await db.biometric_devices.create_index(
                "serial_number", background=True)
            await db.holidays.create_index(
                [("company_id", 1), ("date", 1)], background=True)
            logger.info("[iter523] speed indexes ready")
        except Exception:
            logger.exception("[iter523] speed index build failed")
    asyncio.create_task(_bg_speed_indexes())
    # Iter 708 — warm the monthly attendance grid cache (instant reports).
    asyncio.create_task(_bg_warm_monthly_grid())

    # Iter 92 — monthly Master-Data email to firm admins (1st of month).
    try:
        from routes.master_data_report import monthly_master_data_email_loop
        asyncio.create_task(monthly_master_data_email_loop())
    except Exception:
        logger.exception("[startup] master-data email scheduler failed to start")

    # Iter 112 — every-morning Daily Attendance Report email (SMTP).
    try:
        from routes.email_notifications import daily_attendance_report_loop
        asyncio.create_task(daily_attendance_report_loop())
    except Exception:
        logger.exception("[startup] daily attendance report scheduler failed to start")

    # Iter 486 — CLRA Phase 3: scheduled register emails (daily/weekly/monthly).
    try:
        from routes.scheduled_reports import scheduled_reports_loop
        asyncio.create_task(scheduled_reports_loop())
    except Exception:
        logger.exception("[startup] scheduled reports loop failed to start")

    # Iter 146 — geofence punch reminder: web-push employees who are inside
    # the office geofence but haven't punched in yet (max 1/day, 10-min scan).
    try:
        from routes.web_push import punch_reminder_loop
        asyncio.create_task(punch_reminder_loop())
    except Exception:
        logger.exception("[startup] punch reminder loop failed to start")

    # Iter 157 — Sub Admin inactivity monitor: warn at 25 days without a
    # login, auto-disable at 30 days + notify every Super Admin.
    try:
        from routes.sub_admin_inactivity import inactivity_loop
        asyncio.create_task(inactivity_loop())
    except Exception:
        logger.exception("[startup] sub-admin inactivity loop failed to start")

    # Iter 259 — biometric machine OFFLINE alerts (admins + super admins).
    try:
        from routes.biometric_devices import device_offline_alert_loop
        asyncio.create_task(device_offline_alert_loop())
    except Exception:
        logger.exception("[startup] device offline alert loop failed to start")

    # Iter 674 — 🤖 Email Audit Agent poller (READ-ONLY, super admin).
    try:
        from routes.email_audit_agent import email_agent_loop
        asyncio.create_task(email_agent_loop())
    except Exception:
        logger.exception("[startup] email audit agent loop failed to start")

    # Iter 267 — ZKTeco multi-device sync engine worker (30s cadence).
    try:
        from routes.sync_engine import sync_engine_loop
        asyncio.create_task(sync_engine_loop())
    except Exception:
        logger.exception("[startup] sync engine loop failed to start")

    # Iter 512 — Direct SDK pull channel: auto-pull scheduler.
    try:
        from routes.biometric_sdk import sdk_auto_pull_loop
        asyncio.create_task(sdk_auto_pull_loop())
    except Exception:
        logger.exception("[startup] sdk auto-pull loop failed to start")


async def _bg_enforce_geofence_defaults():
    """Iter 68 — Enforce the new default: geofence ON + strict rejection
    across every firm.  Fields that were never set are seeded to True.
    Firms that have EXPLICITLY set the flag (True or False) are left
    alone so admins can still opt-out of strict rejection per firm.
    """
    try:
        result = await db.companies.update_many(
            {"location_punching_enabled": {"$exists": False}},
            {"$set": {"location_punching_enabled": True}},
        )
        result2 = await db.companies.update_many(
            {"reject_outside_geofence": {"$exists": False}},
            {"$set": {"reject_outside_geofence": True}},
        )
        touched = getattr(result, "modified_count", 0) + getattr(result2, "modified_count", 0)
        if touched:
            logger.info(
                "[iter68] Enforced geofence defaults on %d firm(s)", touched,
            )
    except Exception:
        logger.exception("[iter68] enforcing geofence defaults failed")


async def _bg_apply_textile_default():
    """Iter 68 — Apply Textile Preset #1 as the default attendance policy
    for every firm that hasn't set one yet.  Runs once on boot.  Firms
    that already have a policy (custom or preset-inherited) are untouched.
    """
    try:
        preset = ATTENDANCE_POLICY_PRESETS.get("Textile") or ATTENDANCE_POLICY_PRESETS.get("textile")
        if not preset:
            logger.info("[iter68] Textile preset not found; skipping default apply")
            return
        preset = json.loads(json.dumps(preset))
        # Only overwrite when there's no policy at all (safe default).
        res = await db.companies.update_many(
            {"$or": [
                {"attendance_policy": {"$exists": False}},
                {"attendance_policy": None},
                {"attendance_policy": {}},
            ]},
            {"$set": {
                "attendance_policy": preset,
                "attendance_policy_applied_preset": "Textile",
                "attendance_policy_applied_at": now_iso(),
            }},
        )
        if getattr(res, "modified_count", 0):
            logger.info(
                "[iter68] Applied Textile Preset #1 as default for %d firm(s)",
                res.modified_count,
            )
    except Exception:
        logger.exception("[iter68] applying Textile default failed")


async def _create_core_indexes():
    """Small, idempotent index creation. Runs synchronously on startup."""
    try:
        await db.users.drop_index("email_1")
    except Exception:
        pass
    await db.users.create_index(
        "email",
        unique=True,
        partialFilterExpression={"email": {"$type": "string"}},
    )
    await db.users.create_index("user_id", unique=True)
    await db.companies.create_index("company_code", unique=True)
    await db.otp_codes.create_index([("identifier", 1), ("channel", 1)], unique=True)
    await db.otp_codes.create_index("expires_at", expireAfterSeconds=0)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("user_id")
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    # Iter 247 — activity_log (full user action trail)
    await db.activity_log.create_index([("at", -1)])
    await db.activity_log.create_index("actor_id")
    await db.activity_log.create_index("company_id")
    # Iter 569 — 2FA/MFA
    await db.twofa_pending.create_index("pending_id", unique=True)
    await db.twofa_pending.create_index("expires_at", expireAfterSeconds=0)
    await db.trusted_devices.create_index([("user_id", 1), ("token_hash", 1)])
    # Iter 570 — security alerts (new-IP detection)
    await db.login_ips.create_index([("user_id", 1), ("ip", 1)], unique=True)
    # Iter 576 — MSG91 SMS logs (rate-limit lookups)
    await db.sms_log.create_index([("at_dt", -1)])
    await db.sms_log.create_index("mobile")
    await db.sms_log.create_index("company_id")
    await db.attendance.create_index([("user_id", 1), ("date", -1)])
    await db.leaves.create_index("user_id")
    await db.payslips.create_index([("employee_user_id", 1), ("month", -1)])
    await db.tickets.create_index("user_id")
    await db.notifications.create_index("created_at")
    # Iter 307 (user: "portal slow, lots of data") — indexes for every hot
    # query pattern. All idempotent; wrapped so a bad legacy collection
    # never blocks startup.
    try:
        await db.users.create_index([("company_id", 1), ("role", 1)])
        await db.users.create_index([("company_id", 1), ("employee_code", 1)])
        await db.attendance.create_index([("company_id", 1), ("date", -1)])
        await db.compliance_salary_runs.create_index(
            [("company_id", 1), ("month", -1), ("generated_at", -1)])
        await db.salary_runs.create_index(
            [("company_id", 1), ("month", -1), ("generated_at", -1)])
        await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
        await db.leaves.create_index([("company_id", 1), ("status", 1)])
        await db.employee_documents.create_index("user_id")
        await db.employee_documents.create_index([("company_id", 1), ("category", 1)])
        await db.firm_masters.create_index("company_id", unique=True)
        await db.deletion_requests.create_index([("status", 1), ("requested_at", -1)])
        await db.legacy_salary_history.create_index([("company_id", 1), ("month", 1)])
        await db.punch_logs.create_index([("company_id", 1), ("punched_at", -1)])
        await db.device_commands.create_index([("device_id", 1), ("status", 1)])
    except Exception as _idx_err:  # noqa: BLE001
        logger.warning(f"[startup] index creation warning: {_idx_err}")


async def _run_startup_backfill():
    """The rest of the previous synchronous startup, now deferred."""

    # --- Backfill for existing installs -----------------------------------
    # 1) Any company without a company_code -> generate one
    async for c in db.companies.find({"company_code": {"$exists": False}}, {"_id": 0, "company_id": 1}):
        code = uuid.uuid4().hex[:6].upper()
        await db.companies.update_one({"company_id": c["company_id"]}, {"$set": {"company_code": code}})
    # 2) Any user without an "onboarded" flag -> default based on role
    async for u in db.users.find({"onboarded": {"$exists": False}}, {"_id": 0, "user_id": 1, "role": 1}):
        await db.users.update_one(
            {"user_id": u["user_id"]},
            {"$set": {"onboarded": u.get("role") != "employee"}},
        )
    # 3) Any company without compliance_enabled -> default True
    await db.companies.update_many(
        {"compliance_enabled": {"$exists": False}},
        {"$set": {"compliance_enabled": True}},
    )
    # 4) Enforce super_admin allowlist:
    #    a. Promote configured emails to super_admin (and mark onboarded)
    await db.users.update_many(
        {"email": {"$in": list(SUPER_ADMIN_EMAILS)}, "role": {"$ne": "super_admin"}},
        {"$set": {"role": "super_admin", "onboarded": True}},
    )
    #    b. Demote any other super_admin back to employee (they can be re-elevated
    #       to company_admin manually by the true super_admin).
    #    Iter 555 (user request — "Create 2 More Super Admins") — accounts
    #    created through the Super Admin Rights screen carry
    #    ``super_admin_allowlisted: True`` and are EXEMPT from this sweep,
    #    otherwise every backend restart silently demoted them.
    await db.users.update_many(
        {"role": "super_admin", "email": {"$nin": list(SUPER_ADMIN_EMAILS)},
         "super_admin_allowlisted": {"$ne": True}},
        {"$set": {"role": "employee"}},
    )

    # 5) Seed the default super admin account if it doesn't exist.
    #    Sets both email and phone so admin can log in with either +
    #    a temp PIN which must be changed on first PIN login.
    primary_email = next(iter(SUPER_ADMIN_EMAILS), None)
    primary_phone = next(iter(SUPER_ADMIN_PHONES), None)
    if primary_email:
        existing = await db.users.find_one({"email": primary_email}, {"_id": 0})
        if not existing:
            temp_pin = _generate_temp_pin()
            while len(set(temp_pin)) == 1 or temp_pin in {"123456", "654321", "000000", "111111"}:
                temp_pin = _generate_temp_pin()
            user_doc = {
                "user_id": f"user_{uuid.uuid4().hex[:12]}",
                "email": primary_email,
                "phone": primary_phone,
                "name": "S.K. Sharma & Co. Admin",
                "picture": None,
                "role": "super_admin",
                "company_id": None,
                "department": None,
                "position": "Super Admin",
                "employee_code": "SUPERADMIN",
                "father_name": None,
                "dob": None,
                "doj": None,
                "shift_start": None,
                "shift_end": None,
                "salary_monthly": None,
                "half_day_hrs": None,
                "full_day_hrs": None,
                "onboarded": True,
                "approval_status": "approved",
                "has_pin": True,
                "pin_hash": _hash_pin(temp_pin),
                "pin_must_change": True,
                "pin_set_at": now_iso(),
                "created_at": now_iso(),
            }
            await db.users.insert_one(user_doc)
            logger.warning("=" * 60)
            logger.warning("SEEDED SUPER ADMIN ACCOUNT")
            logger.warning(f"  email: {primary_email}")
            logger.warning(f"  phone: {primary_phone}")
            logger.warning(f"  TEMP PIN: {temp_pin}  (must be changed on first login)")
            logger.warning("=" * 60)
            # Also persist the temp PIN to a one-shot file for the main agent
            try:
                Path("/app/memory").mkdir(parents=True, exist_ok=True)
                with open("/app/memory/superadmin_pin.txt", "w") as f:
                    f.write(
                        f"email: {primary_email}\n"
                        f"phone: {primary_phone}\n"
                        f"temp_pin: {temp_pin}\n"
                        f"note: This PIN must be changed on first login. "
                        "This file is written once by backend startup only if the account is missing.\n"
                    )
            except Exception:
                pass
        else:
            # Ensure phone is populated and role stays super_admin.
            upd: dict = {"role": "super_admin", "onboarded": True, "approval_status": "approved"}
            if primary_phone and existing.get("phone") != primary_phone:
                upd["phone"] = primary_phone
            await db.users.update_one({"email": primary_email}, {"$set": upd})

    # Seed 5 compliance docs on first run
    if await db.compliance_docs.count_documents({}) == 0:
        seeds = [
            {"title": "Provident Fund (PF) Rules 2026", "category": "pf",
             "description": "EPF contributions, withdrawal & KYC rules.",
             "content": "Employees contribute 12% of basic salary. Employer matches 12% (3.67% EPF + 8.33% EPS). Withdraw after 2 months of unemployment.",
             "pdf_base64": None},
            {"title": "Employee State Insurance (ESI)", "category": "esi",
             "description": "Medical coverage for employees earning up to Rs 21,000/month.",
             "content": "Employer: 3.25%; Employee: 0.75% of gross wages. Covers medical, sickness, maternity, disablement benefits.",
             "pdf_base64": None},
            {"title": "Gratuity Act", "category": "gratuity",
             "description": "Payment after 5+ years of continuous service.",
             "content": "Formula: (Last drawn salary * 15/26) * years of service. Max limit Rs 20 lakhs (tax-free).",
             "pdf_base64": None},
            {"title": "Minimum Wages 2026", "category": "minimum_wage",
             "description": "State-wise revised minimum wage rates.",
             "content": "Karnataka minimum wage (unskilled): Rs 15,423/month. Skilled: Rs 19,568/month. Effective April 2026.",
             "pdf_base64": None},
            {"title": "Code of Conduct", "category": "policy",
             "description": "Workplace ethics, harassment policy & grievance redressal.",
             "content": "Zero tolerance for discrimination. POSH complaints handled by Internal Committee within 90 days.",
             "pdf_base64": None},
        ]
        for s in seeds:
            s["doc_id"] = f"doc_{uuid.uuid4().hex[:10]}"
            s["created_at"] = now_iso()
            await db.compliance_docs.insert_one(s)

    # Kick off the periodic shift auto-close task. Runs in the background
    # for the lifetime of the process — closes any IN-without-OUT punches
    # that meet the elapsed-hours / geofence-stale criteria. Failures are
    # logged but never propagate (so a bad tick can't crash uvicorn).
    async def _auto_close_loop():
        # Small startup delay so index creation & backfills finish first.
        await asyncio.sleep(15)
        while True:
            try:
                summary = await _auto_close_open_shifts()
                if summary.get("closed"):
                    logger.info(
                        "[auto-close] closed=%d scanned=%d",
                        summary["closed"], summary["scanned"],
                    )
            except Exception:
                logger.exception("[auto-close] tick failed")
            await asyncio.sleep(AUTO_CLOSE_TICK_SECONDS)

    asyncio.create_task(_auto_close_loop())


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@api.post("/auth/session")
async def auth_session(payload: SessionExchange):
    """Exchange Emergent session_id for our own session_token."""
    async with httpx.AsyncClient(timeout=15) as hc:
        r = await hc.get(EMERGENT_SESSION_DATA_URL, headers={"X-Session-ID": payload.session_id})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session_id")
    data = r.json()
    email = data["email"]
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        # Update picture/name in case changed
        await db.users.update_one({"user_id": user_id},
                                  {"$set": {"name": data.get("name"), "picture": data.get("picture")}})
        role = existing["role"]
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        role = _resolve_role_on_signup(email)
        user_doc = {
            "user_id": user_id,
            "email": email,
            "name": data.get("name", email),
            "picture": data.get("picture"),
            "role": role,
            "company_id": None,  # super_admin assigns later
            "department": None,
            "position": None,
            "employee_code": None,
            "father_name": None,
            "dob": None,
            "doj": None,
            "shift_start": None,
            "shift_end": None,
            "salary_monthly": None,
            "half_day_hrs": None,
            "full_day_hrs": None,
            "onboarded": role != "employee",
            "created_at": now_iso(),
        }
        await db.users.insert_one(user_doc)

    token = data["session_token"]
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
    await db.user_sessions.update_one(
        {"session_token": token},
        {"$set": {
            "session_token": token,
            "user_id": user_id,
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return {"session_token": token, "user": user}


async def _enrich_user_with_company(user: dict) -> dict:
    """Attach company_name, offboarded and approval_pending flags to a user dict."""
    cid = user.get("company_id")
    company_auto_punch = True  # default
    company_loc_punch = False  # Iter 64 — GPS punching OFF by default
    if cid:
        c = await db.companies.find_one(
            {"company_id": cid},
            {
                "_id": 0,
                "name": 1,
                "office_lat": 1,
                "office_lng": 1,
                "geofence_radius_m": 1,
                "address": 1,
                "face_match_enabled": 1,
                "auto_punch_enabled": 1,
                "location_punching_enabled": 1,
                "employer_permissions": 1,
                "employer_menu_rights": 1,
                # Iter 85 — Include the firm logo so the frontend can
                # brand every screen with the company's own logo after
                # login (falls back to the SKS badge when absent).
                "logo_base64": 1,
                "company_code": 1,
            },
        )
        if c:
            company_auto_punch = bool(c.get("auto_punch_enabled", True))
            # Iter 64 — GPS punching defaults to OFF at the firm level.
            # Missing/unset value counts as OFF.
            company_loc_punch = bool(c.get("location_punching_enabled") is True)
            user["company_name"] = c.get("name")
            # Iter 58 — expose the firm's employer_permissions on the user
            # doc so AdminWebShell can filter the company_admin nav.
            user["employer_permissions"] = c.get("employer_permissions") or []
            # Iter 93 — per-sidebar-button gating map for AdminWebShell.
            # Only company_admins inherit the FIRM's menu rights; sub-admins
            # carry their OWN menu_rights on the user doc (set by super admin)
            # which must not be clobbered here.
            if user.get("role") != "sub_admin":
                user["menu_rights"] = c.get("employer_menu_rights") or {}
            # Nested company block used by mobile clients for geofence /
            # auto-punch computations. Kept intentionally small.
            user["company"] = {
                "company_id": cid,
                "name": c.get("name"),
                "address": c.get("address"),
                "office_lat": c.get("office_lat"),
                "office_lng": c.get("office_lng"),
                "geofence_radius_m": c.get("geofence_radius_m"),
                "face_match_enabled": bool(c.get("face_match_enabled")),
                "auto_punch_enabled": company_auto_punch,
                "location_punching_enabled": company_loc_punch,
                "employer_permissions": c.get("employer_permissions") or [],
            }
    # Effective auto-punch: per-employee override (None → inherit company).
    # Live-in staff never use auto-punch (their phone stays on-premises so
    # the geofence would fire spuriously).
    user_ap = user.get("auto_punch_enabled")
    if user.get("is_live_in"):
        user["effective_auto_punch"] = False
    elif user_ap is None:
        user["effective_auto_punch"] = company_auto_punch
    else:
        user["effective_auto_punch"] = bool(user_ap)

    # Iter 64 — Effective GPS-punch flag.
    #
    # Firm-level ``companies.location_punching_enabled`` is a hard cap: when
    # False, NO employee of the firm can use GPS. Otherwise, each employee
    # opts in via ``users.gps_punch_enabled`` (default False).
    #
    # ``effective_gps_punch`` = company_loc_punch AND user_gps_opt_in
    #
    # When False, the app must:
    #   • Hide any location/geofence UI.
    #   • Force manual biometric punch (fingerprint + face selfie).
    #   • Never send lat/lon on /attendance/punch.
    user_gps_opt = bool(user.get("gps_punch_enabled") is True)
    user["gps_punch_enabled"] = user_gps_opt
    user["effective_gps_punch"] = bool(company_loc_punch and user_gps_opt)

    # Iter 165 — Fingerprint verification (Employee PWA). Available only
    # when the firm's Bio Matrix Attendance is enabled in Firm Master;
    # required per-employee by the admin (users.fingerprint_required).
    firm_bio = False
    if cid and user.get("role") == "employee":
        try:
            fm = await db.firm_masters.find_one(
                {"company_id": cid}, {"_id": 0, "salary_process": 1})
            firm_bio = bool(((fm or {}).get("salary_process") or {})
                            .get("bio_matrix_attendance"))
        except Exception:
            firm_bio = False
    user["firm_biometric_enabled"] = firm_bio
    user["fingerprint_required"] = bool(user.get("fingerprint_required"))
    user["effective_fingerprint_required"] = bool(
        firm_bio and user.get("fingerprint_required"))
    # Auto-punch requires GPS. If effective GPS is off, auto-punch is off.
    if not user["effective_gps_punch"]:
        user["effective_auto_punch"] = False
    # Compute offboarded flag from exit_date (YYYY-MM-DD)
    ed = user.get("exit_date")
    if ed:
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            user["offboarded"] = str(ed) <= today
        except Exception:
            user["offboarded"] = False
    else:
        user["offboarded"] = False
    # Legacy users without approval_status are treated as approved so existing
    # accounts do not get locked out. Only new self-onboardings are pending.
    status = user.get("approval_status")
    if not status:
        status = "approved"
        user["approval_status"] = status
    user["approval_pending"] = (
        status == "pending" and user.get("role") == "employee" and bool(user.get("company_id"))
    )
    user["approval_rejected"] = status == "rejected" and user.get("role") == "employee"
    # Expose pin flags but never the hash itself
    user["has_pin"] = bool(user.get("pin_hash"))
    user["pin_must_change"] = bool(user.get("pin_must_change"))
    user.pop("pin_hash", None)
    # Password hash is stored in the same document but is a separate credential
    # for the web portal — must never leak in any user-shaped response.
    user["has_password"] = bool(user.get("password_hash"))
    user.pop("password_hash", None)
    # SECURITY: Never leak plaintext temp credentials from a user-shaped
    # payload. The Super Admin's ONLY authorised way to see these is via
    # GET /api/companies/{id}/details which explicitly pulls them from the
    # doc. Any other endpoint returning a user dict must be redacted.
    user.pop("temp_pin_plaintext", None)
    user.pop("temp_password_plaintext", None)
    # Face reference base64 is huge & sensitive — never ship it in user list
    # responses. Face match uses its own dedicated endpoint.
    user.pop("face_reference_base64", None)
    return user


def _redact_user(user: dict) -> dict:
    """Strip all sensitive fields from a raw user Mongo doc before returning
    it in any list / lookup endpoint. Mirrors the redactions performed in
    _enrich_user_with_company but is cheaper (no company lookup) and can be
    applied to each item in a bulk /admin/employees response.
    """
    if not user:
        return user
    user["has_password"] = bool(user.get("password_hash"))
    for k in (
        "pin_hash",
        "password_hash",
        "temp_pin_plaintext",
        "temp_password_plaintext",
        "face_reference_base64",
    ):
        user.pop(k, None)
    # Surface booleans the UI expects
    user["has_pin"] = bool(user.get("pin_must_change") is not None or user.get("pin_set_at"))
    return user


@api.get("/auth/me")
async def auth_me(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    # Iter 307 (perf) — the auth helper strips the heavy photo field;
    # /auth/me is the one place the PWA needs it (Profile screen).
    photo_doc = await db.users.find_one(
        {"user_id": user["user_id"]}, {"_id": 0, "profile_photo_base64": 1})
    user["profile_photo_base64"] = (photo_doc or {}).get("profile_photo_base64")
    user = await _enrich_user_with_company(user)
    return {"user": user}


@api.post("/me/fingerprint/enrolled")
async def record_fingerprint_enrollment(
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """Iter 165 — Employee PWA reports a successful device-fingerprint
    enrollment (WebAuthn on web / OS biometrics on native) so admins can
    see who has set it up. Device-local credential; nothing sensitive."""
    user = await get_user_from_token(authorization)
    device = str(payload.get("device") or "")[:80]
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"fingerprint_enrolled_at": now_iso(),
                  "fingerprint_device": device or None}})
    return {"ok": True}


def _normalise_aadhar(value: str) -> str:
    """Strip spaces / dashes and keep digits only. Returns cleaned string."""
    return "".join(c for c in (value or "") if c.isdigit())


def _normalise_pan(value: str) -> str:
    return (value or "").strip().upper()


def _validate_kyc(payload: "KycUpdate") -> dict:
    """Return normalised, per-field updates or raise HTTPException(400)."""
    updates: dict = {}
    if payload.aadhar_number is not None:
        v = _normalise_aadhar(payload.aadhar_number)
        if v == "":
            updates["aadhar_number"] = None
        else:
            if len(v) != 12:
                raise HTTPException(
                    status_code=400,
                    detail="Aadhaar number must be 12 digits.",
                )
            updates["aadhar_number"] = v
    if payload.name_as_per_aadhar is not None:
        updates["name_as_per_aadhar"] = payload.name_as_per_aadhar.strip() or None
    if payload.pan_number is not None:
        v = _normalise_pan(payload.pan_number)
        if v == "":
            updates["pan_number"] = None
        else:
            if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", v):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "PAN must be in the format ABCDE1234F "
                        "(5 letters, 4 digits, 1 letter)."
                    ),
                )
            updates["pan_number"] = v
    if payload.name_as_per_pan is not None:
        updates["name_as_per_pan"] = payload.name_as_per_pan.strip() or None
    if payload.dl_number is not None:
        v = (payload.dl_number or "").strip().upper()
        if v == "":
            updates["dl_number"] = None
        else:
            # Very loose format check — Indian DLs vary state-by-state.
            if not (5 <= len(v) <= 20):
                raise HTTPException(
                    status_code=400,
                    detail="Driving licence number looks invalid (5–20 chars).",
                )
            updates["dl_number"] = v
    # Bank details
    if payload.bank_account_number is not None:
        v = "".join(c for c in (payload.bank_account_number or "") if c.isdigit())
        if v == "":
            updates["bank_account_number"] = None
        else:
            # Indian bank account numbers are 9–18 digits; be lenient.
            if not (6 <= len(v) <= 20):
                raise HTTPException(
                    status_code=400,
                    detail="Bank account number must be 6–20 digits.",
                )
            updates["bank_account_number"] = v
    if payload.bank_name is not None:
        v = (payload.bank_name or "").strip()
        updates["bank_name"] = v if v else None
    if payload.pay_mode is not None:
        updates["pay_mode"] = (payload.pay_mode or "Bank").strip() or "Bank"
    if payload.ifsc_code is not None:
        v = (payload.ifsc_code or "").strip().upper().replace(" ", "")
        if v == "":
            updates["ifsc_code"] = None
        else:
            # IFSC format: 4 letters, "0", then 6 alphanumeric characters.
            if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", v):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "IFSC code must be in the format AAAA0XXXXXX "
                        "(4 letters, '0', then 6 letters/digits)."
                    ),
                )
            updates["ifsc_code"] = v
    if payload.name_as_per_bank is not None:
        v = (payload.name_as_per_bank or "").strip()
        updates["name_as_per_bank"] = v if v else None
    # Iter 169 — mirror KYC bank keys onto the employee's real Bank Details
    # fields (users.bank_account / users.bank_ifsc) used by the Employee
    # form, salary and payment reports.
    if updates.get("bank_account_number"):
        updates["bank_account"] = updates["bank_account_number"]
    if updates.get("ifsc_code"):
        updates["bank_ifsc"] = updates["ifsc_code"]
    return updates


@api.patch("/me/kyc")
async def update_own_kyc(
    payload: KycUpdate, authorization: Optional[str] = Header(None)
):
    """Employee (or any authenticated user) updates their own KYC fields:
    aadhar_number, name_as_per_aadhar, pan_number, name_as_per_pan, dl_number,
    bank_account_number, bank_name, ifsc_code, name_as_per_bank.

    Immutable-once-set policy (Iteration 53): Aadhaar and PAN numbers CANNOT
    be edited once a value has been persisted. This applies to every role —
    including super_admin, company_admin and the employee themselves. The
    ancillary "name_as_per_aadhar" / "name_as_per_pan" fields remain
    editable so typos in the display name can still be fixed.
    """
    user = await get_user_from_token(authorization)
    updates = _validate_kyc(payload)
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    # Enforce KYC immutability for the two identity numbers.
    existing = await db.users.find_one(
        {"user_id": user["user_id"]},
        {"_id": 0, "aadhar_number": 1, "pan_number": 1},
    ) or {}
    for locked_key, human in (("aadhar_number", "Aadhaar"), ("pan_number", "PAN")):
        if locked_key in updates and (existing.get(locked_key) or "").strip():
            new_val = (updates.get(locked_key) or "").strip()
            if new_val != (existing.get(locked_key) or "").strip():
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{human} number is locked after first save and "
                        "cannot be edited. Contact HR to correct it via a "
                        "formal KYC reset."
                    ),
                )
            # Same value — drop to avoid a no-op write
            updates.pop(locked_key, None)

    if not updates:
        # After the immutability trim, nothing meaningful left to persist.
        raise HTTPException(status_code=400, detail="Nothing to update")

    updates["kyc_updated_at"] = now_iso()
    await db.users.update_one(
        {"user_id": user["user_id"]}, {"$set": updates}
    )
    fresh = await db.users.find_one(
        {"user_id": user["user_id"]},
        {
            "_id": 0,
            "aadhar_number": 1,
            "name_as_per_aadhar": 1,
            "pan_number": 1,
            "name_as_per_pan": 1,
            "dl_number": 1,
            "bank_account_number": 1,
            "bank_name": 1,
            "ifsc_code": 1,
            "name_as_per_bank": 1,
            "kyc_updated_at": 1,
        },
    ) or {}
    return {"ok": True, "kyc": fresh}


@api.get("/me/kyc")
async def get_own_kyc(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    fresh = await db.users.find_one(
        {"user_id": user["user_id"]},
        {
            "_id": 0,
            "aadhar_number": 1,
            "name_as_per_aadhar": 1,
            "pan_number": 1,
            "name_as_per_pan": 1,
            "dl_number": 1,
            "bank_account_number": 1,
            "bank_name": 1,
            "ifsc_code": 1,
            "name_as_per_bank": 1,
            "kyc_updated_at": 1,
        },
    ) or {}
    return {"kyc": fresh}


# ---------------------------------------------------------------------------
# Employee Profile Edit — approval workflow
# ---------------------------------------------------------------------------
# Employees can submit changes to a small set of personal fields (Name,
# Father Name, DOB, DOJ). Changes DO NOT take effect until the company admin
# reviews and approves them. Rejected requests are dropped with an optional
# note. Only ONE pending request per user at a time — a new POST replaces the
# previous pending one.
# ---------------------------------------------------------------------------


def _valid_iso_date(v: str) -> bool:
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _diff_profile_fields(current: dict, proposed: dict) -> dict:
    """Return only the fields whose value changes; drop identical / empty."""
    out: dict = {}
    for k, v in proposed.items():
        if v is None:
            continue
        v_str = str(v).strip()
        if v_str == "":
            continue
        if str(current.get(k) or "").strip() == v_str:
            continue
        out[k] = v_str
    return out


@api.post("/me/profile-edit")
async def submit_profile_edit(
    payload: ProfileEditRequest,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    if user.get("role") != "employee":
        raise HTTPException(
            status_code=403,
            detail="Only employees can submit profile edits for approval.",
        )
    if not user.get("company_id"):
        raise HTTPException(
            status_code=400,
            detail="You need a company assigned before submitting edits.",
        )

    # Validate DOB/DOJ if provided
    if payload.dob and not _valid_iso_date(payload.dob):
        raise HTTPException(
            status_code=400,
            detail="Date of birth must be a valid date in YYYY-MM-DD format.",
        )
    if payload.doj and not _valid_iso_date(payload.doj):
        raise HTTPException(
            status_code=400,
            detail="Date of joining must be a valid date in YYYY-MM-DD format.",
        )

    # Normalize + validate family members (drop rows with empty name)
    proposed_family: Optional[List[dict]] = None
    if payload.family_members is not None:
        cleaned: list[dict] = []
        for fm in payload.family_members:
            nm = (fm.name or "").strip()
            if not nm:
                continue
            if fm.dob and not _valid_iso_date(fm.dob):
                raise HTTPException(
                    status_code=400,
                    detail=f"Family member '{nm}' has an invalid DOB — use YYYY-MM-DD.",
                )
            cleaned.append({
                "name": nm,
                "relation": (fm.relation or "").strip() or None,
                "dob": (fm.dob or "").strip() or None,
                "occupation": (fm.occupation or "").strip() or None,
                "contact": (fm.contact or "").strip() or None,
                "aadhaar_no": (fm.aadhaar_no or "").strip() or None,
                "scan_doc_id": (fm.scan_doc_id or "").strip() or None,
            })
        proposed_family = cleaned  # empty list means "clear all family members"

    fresh = await db.users.find_one(
        {"user_id": user["user_id"]},
        {
            "_id": 0,
            "name": 1,
            "father_name": 1,
            "dob": 1,
            "doj": 1,
            "designation": 1,
            "present_address": 1,
            "permanent_address": 1,
            "family_members": 1,
        },
    ) or {}
    proposed = {
        "name": payload.name,
        "father_name": payload.father_name,
        "dob": payload.dob,
        "doj": payload.doj,
        "designation": payload.designation,
        "present_address": payload.present_address,
        "permanent_address": payload.permanent_address,
    }
    delta = _diff_profile_fields(fresh, proposed)

    # Family members: compare as JSON so any addition/removal/change flags a diff.
    if proposed_family is not None:
        current_family = fresh.get("family_members") or []
        if json.dumps(current_family, sort_keys=True) != json.dumps(proposed_family, sort_keys=True):
            delta["family_members"] = proposed_family

    if not delta:
        raise HTTPException(
            status_code=400,
            detail="Nothing to update — the values you submitted match your current profile.",
        )

    # Replace any existing pending request from this user (one active at a time).
    await db.profile_edit_requests.delete_many(
        {"user_id": user["user_id"], "status": "pending"}
    )
    req = {
        "request_id": f"pedit_{_secrets.token_hex(6)}",
        "user_id": user["user_id"],
        "company_id": user.get("company_id"),
        "status": "pending",
        "submitted_at": now_iso(),
        "changes": delta,
        "note": (payload.note or "").strip() or None,
    }
    await db.profile_edit_requests.insert_one(req)
    return {"ok": True, "request": {k: v for k, v in req.items() if k != "_id"}}


@api.get("/me/profile-edit")
async def get_my_profile_edit(authorization: Optional[str] = Header(None)):
    """Return the current user's most recent profile-edit request (any status)."""
    user = await get_user_from_token(authorization)
    r = await db.profile_edit_requests.find_one(
        {"user_id": user["user_id"]},
        {"_id": 0},
        sort=[("submitted_at", -1)],
    )
    return {"request": r}


class ProfilePhotoPayload(BaseModel):
    """Base64-encoded JPEG/PNG data URL or raw base64. Kept small — capped
    at ~2MB on the client. Stored on the user document; no approval flow
    since a photo is personal + low-risk."""
    photo_base64: str


@api.post("/me/profile-photo")
async def set_my_profile_photo(
    payload: ProfilePhotoPayload,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    photo = (payload.photo_base64 or "").strip()
    if not photo:
        raise HTTPException(status_code=400, detail="photo_base64 is required")
    # Guard against oversized payloads to protect Mongo doc size (16MB).
    if len(photo) > 4_500_000:  # ~3.3MB decoded
        raise HTTPException(
            status_code=413,
            detail="Photo too large. Please pick a smaller image (< 2MB).",
        )
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "profile_photo_base64": photo,
            "profile_photo_updated_at": now_iso(),
        }},
    )
    return {"ok": True}


@api.delete("/me/profile-photo")
async def delete_my_profile_photo(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$unset": {"profile_photo_base64": "", "profile_photo_updated_at": ""}},
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# OCR ID proof (Gemini 3 Flash via emergentintegrations)
# ---------------------------------------------------------------------------
class OcrIdProofPayload(BaseModel):
    """Extract structured fields from an image of an Indian government ID.
    `image_base64` may be raw base64 or a `data:image/*;base64,...` URL.
    `doc_type` steers the prompt."""
    image_base64: str
    doc_type: Literal["aadhaar", "pan", "dl", "passbook", "auto"] = "auto"


def _strip_data_url(b64: str) -> tuple[str, str]:
    """Split a data URL into (mime, raw base64). If no data URL prefix, return
    default mime ('image/jpeg') and the raw string."""
    if b64.startswith("data:"):
        try:
            head, rest = b64.split(",", 1)
            mime = head.split(";")[0].replace("data:", "") or "image/jpeg"
            return mime, rest
        except Exception:
            return "image/jpeg", b64
    return "image/jpeg", b64


_OCR_PROMPT = {
    "aadhaar": (
        "This is an Indian Aadhaar card. Extract the following fields and "
        "return ONLY valid JSON (no markdown fences, no commentary):\n"
        "{\n"
        '  "doc_type": "aadhaar",\n'
        '  "aadhaar_number": string (12 digits, spaces allowed) or null,\n'
        '  "name": string or null,\n'
        '  "dob": string (DD-MM-YYYY) or null,\n'
        '  "gender": "M"|"F"|"O" or null,\n'
        '  "address": string or null\n'
        "}"
    ),
    "pan": (
        "This is an Indian PAN card. Extract these fields and return ONLY "
        "valid JSON (no markdown fences):\n"
        "{\n"
        '  "doc_type": "pan",\n'
        '  "pan_number": string (10 chars ABCDE1234F format) or null,\n'
        '  "name": string or null,\n'
        '  "father_name": string or null,\n'
        '  "dob": string (DD-MM-YYYY) or null\n'
        "}"
    ),
    "dl": (
        "This is an Indian Driving License. Extract these fields and return "
        "ONLY valid JSON (no markdown fences):\n"
        "{\n"
        '  "doc_type": "dl",\n'
        '  "dl_number": string or null,\n'
        '  "name": string or null,\n'
        '  "dob": string (DD-MM-YYYY) or null,\n'
        '  "issue_date": string (DD-MM-YYYY) or null,\n'
        '  "expiry_date": string (DD-MM-YYYY) or null,\n'
        '  "address": string or null\n'
        "}"
    ),
    "passbook": (
        "This is an Indian bank passbook or cancelled cheque. Extract these "
        "fields and return ONLY valid JSON (no markdown fences):\n"
        "{\n"
        '  "doc_type": "passbook",\n'
        '  "account_number": string or null,\n'
        '  "ifsc": string (format ABCD0123456) or null,\n'
        '  "bank_name": string or null,\n'
        '  "branch": string or null,\n'
        '  "account_holder": string or null\n'
        "}"
    ),
    "auto": (
        "This is an Indian identity or bank document (Aadhaar / PAN / "
        "Driving License / bank passbook). First classify it, then extract "
        "the standard fields. Return ONLY valid JSON (no markdown fences):\n"
        "{\n"
        '  "doc_type": "aadhaar"|"pan"|"dl"|"passbook"|"unknown",\n'
        '  "fields": { ...doc-appropriate fields... }\n'
        "}"
    ),
}


def _extract_json_from_text(text: str) -> dict:
    """Robust JSON extraction — strips markdown fences, isolates the first
    JSON object, falls back to an empty dict."""
    import json as _json
    if not text:
        return {}
    t = text.strip()
    # Strip ``` fences
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    # Find first { ... last }
    start = t.find("{")
    end = t.rfind("}")
    if start >= 0 and end > start:
        t = t[start : end + 1]
    try:
        return _json.loads(t)
    except Exception:
        return {}


@api.post("/me/ocr-id-proof")
async def me_ocr_id_proof(
    payload: OcrIdProofPayload,
    authorization: Optional[str] = Header(None),
):
    """Send the ID image to Gemini 3 Flash Preview via emergentintegrations
    and return the extracted fields. The image is not persisted server-side
    — it lives only in the request cycle."""
    user = await get_user_from_token(authorization)
    if not payload.image_base64:
        raise HTTPException(status_code=400, detail="image_base64 is required")
    api_key = os.getenv("EMERGENT_LLM_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OCR is not configured (missing EMERGENT_LLM_KEY on server).",
        )

    _mime, raw = _strip_data_url(payload.image_base64)
    if len(raw) > 6_000_000:  # ~4.5MB decoded
        raise HTTPException(
            status_code=413,
            detail="Image too large — please crop or pick a smaller photo.",
        )

    prompt = _OCR_PROMPT.get(payload.doc_type, _OCR_PROMPT["auto"])

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
    except Exception as exc:  # noqa: BLE001
        logger.exception("emergentintegrations unavailable")
        raise HTTPException(
            status_code=500,
            detail=f"OCR library unavailable: {exc}",
        )

    session_id = f"ocr-{user['user_id']}-{uuid.uuid4().hex[:6]}"
    chat = LlmChat(
        api_key=api_key,
        session_id=session_id,
        system_message=(
            "You are an OCR assistant that extracts structured data from "
            "Indian government-ID and bank-document photos. Always return "
            "valid JSON that matches the requested schema. Leave fields "
            "you cannot read confidently as null."
        ),
    ).with_model("gemini", "gemini-3-flash-preview")

    try:
        image_content = ImageContent(image_base64=raw)
        response = await chat.send_message(
            UserMessage(text=prompt, file_contents=[image_content]),
        )
    except Exception as exc:  # noqa: BLE001
        # Gemini errors (content policy, timeout, bad request, quota) should
        # surface as a graceful 200 with ok=false so the mobile client can
        # render a friendly message. The K8s/Cloudflare edge rewrites raw
        # backend 5xx to HTML, which mobile clients can't parse.
        logger.warning(f"[ocr] gemini error: {exc}")
        return {
            "ok": False,
            "parsed": None,
            "raw": None,
            "detail": f"Could not scan the document: {exc}",
        }

    raw_text = getattr(response, "text", None) or str(response)
    parsed = _extract_json_from_text(raw_text)
    if not parsed:
        return {"ok": False, "raw": raw_text[:800], "parsed": None,
                "detail": "Could not parse OCR response as JSON."}
    return {"ok": True, "parsed": parsed, "doc_type": payload.doc_type}


# ---------------------------------------------------------------------------
# Face-recognition identity match (Gemini 3 Flash via emergentintegrations)
# ---------------------------------------------------------------------------
async def _compare_faces(reference_b64: str, sample_b64: str) -> dict:
    """Ask Gemini 3 Flash whether two face photos belong to the same person.

    Never raises — returns a structured result with `ok` so callers can
    gracefully fall through on model / quota failures.

    Result shape::
        {
          "ok": bool,               # True = model returned a decision
          "match": Optional[bool],  # True/False, None if uncertain
          "confidence": float,      # 0.0–1.0
          "reason": str,            # short human-readable rationale
          "error": Optional[str],
        }
    """
    api_key = os.getenv("EMERGENT_LLM_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "match": None,
            "confidence": 0.0,
            "reason": "face-match not configured on server",
            "error": "missing EMERGENT_LLM_KEY",
        }

    _rm, ref_raw = _strip_data_url(reference_b64)
    _sm, samp_raw = _strip_data_url(sample_b64)
    if not ref_raw or not samp_raw:
        return {"ok": False, "match": None, "confidence": 0.0,
                "reason": "missing image", "error": "empty base64"}

    try:
        from emergentintegrations.llm.chat import (
            LlmChat,
            UserMessage,
            ImageContent,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("emergentintegrations unavailable")
        return {"ok": False, "match": None, "confidence": 0.0,
                "reason": "library unavailable", "error": str(exc)}

    session_id = f"face-{uuid.uuid4().hex[:8]}"
    chat = LlmChat(
        api_key=api_key,
        session_id=session_id,
        system_message=(
            "You are a face-verification assistant. Given two portrait "
            "photos, decide if they show the SAME person. Return ONLY "
            "valid JSON of the form: "
            '{"match": true|false, "confidence": 0.0-1.0, "reason": "short reason"}. '
            "Be conservative: if either face is not clearly visible, "
            "if there is severe occlusion (mask/heavy filter), or if "
            "you are genuinely uncertain, return match=false and note "
            "the reason. Do NOT add any surrounding prose."
        ),
    ).with_model("gemini", "gemini-3-flash-preview")

    prompt = (
        "IMAGE 1 = the enrolled reference photo of the employee.\n"
        "IMAGE 2 = a fresh selfie captured at punch-in/out.\n"
        "Respond with JSON only."
    )

    try:
        response = await chat.send_message(
            UserMessage(
                text=prompt,
                file_contents=[
                    ImageContent(image_base64=ref_raw),
                    ImageContent(image_base64=samp_raw),
                ],
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[face-match] gemini error: {exc}")
        return {"ok": False, "match": None, "confidence": 0.0,
                "reason": "model error", "error": str(exc)}

    raw_text = getattr(response, "text", None) or str(response)
    parsed = _extract_json_from_text(raw_text)
    if not parsed or "match" not in parsed:
        return {"ok": False, "match": None, "confidence": 0.0,
                "reason": "unparseable model output",
                "error": raw_text[:200]}
    try:
        conf = float(parsed.get("confidence") or 0.0)
    except Exception:
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    return {
        "ok": True,
        "match": bool(parsed.get("match")),
        "confidence": conf,
        "reason": str(parsed.get("reason") or "").strip()[:240],
        "error": None,
    }


class FaceMatchToggle(BaseModel):
    enabled: bool


@api.patch("/admin/companies/{company_id}/face-match")
async def set_company_face_match(
    company_id: str,
    payload: FaceMatchToggle,
    authorization: Optional[str] = Header(None),
):
    """Enable / disable face-match verification for a company.
    company_admin may only toggle their own company; super_admin any."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    if user["role"] == "company_admin" and user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not your company")
    r = await db.companies.update_one(
        {"company_id": company_id},
        {"$set": {"face_match_enabled": bool(payload.enabled)}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    fresh = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "company_id": 1, "name": 1, "face_match_enabled": 1},
    )
    return {"ok": True, "company": fresh}


# ---------------------------------------------------------------------------
# Iter 64 — Location-punching master switch (firm-level)
# ---------------------------------------------------------------------------
@api.patch("/admin/companies/{company_id}/location-punching")
async def set_company_location_punching(
    company_id: str,
    payload: FaceMatchToggle,  # reuse the {enabled: bool} shape
    authorization: Optional[str] = Header(None),
):
    """Enable / disable GPS-based punching for the whole firm.

    When OFF, employees of this firm can punch without location as long
    as they present BOTH the device biometric (fingerprint/face) AND a
    fresh face selfie. Auto-punch is implicitly disabled since it needs
    GPS to fire background transitions.

    Guardrails: super_admin can toggle any firm; company_admin only own.
    """
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    if user["role"] == "company_admin" and user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not your company")
    r = await db.companies.update_one(
        {"company_id": company_id},
        {"$set": {"location_punching_enabled": bool(payload.enabled)}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    fresh = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "company_id": 1, "name": 1, "location_punching_enabled": 1},
    )
    return {"ok": True, "company": fresh}


@api.get("/admin/users/{user_id}/photo")
async def get_user_profile_photo(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return the base64 profile photo of a user. Admin-only, scoped by
    company for company_admin."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    target = await db.users.find_one(
        {"user_id": user_id},
        {"_id": 0, "profile_photo_base64": 1, "company_id": 1},
    )
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if admin["role"] == "company_admin" and target.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your company")
    return {"photo_base64": target.get("profile_photo_base64")}


@api.get("/admin/profile-edits")
async def list_profile_edits(
    company_id: Optional[str] = None,
    status: Optional[str] = "pending",
    authorization: Optional[str] = Header(None),
):
    """List profile-edit requests. Scoped to caller company for company_admin;
    super_admin may filter by company_id."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    q: dict = {}
    if status and status != "all":
        q["status"] = status
    if user["role"] == "company_admin":
        q["company_id"] = user.get("company_id")
    elif user["role"] == "super_admin" and company_id and company_id != "all":
        q["company_id"] = company_id

    items = await db.profile_edit_requests.find(q, {"_id": 0}).sort(
        "submitted_at", -1
    ).to_list(500)

    if items:
        uids = list({i["user_id"] for i in items})
        users = await db.users.find(
            {"user_id": {"$in": uids}},
            {
                "_id": 0,
                "user_id": 1,
                "name": 1,
                "father_name": 1,
                "dob": 1,
                "doj": 1,
                "designation": 1,
                "present_address": 1,
                "permanent_address": 1,
                "family_members": 1,
                "employee_code": 1,
                "company_id": 1,
            },
        ).to_list(500)
        u_by_id = {u["user_id"]: u for u in users}
        for it in items:
            it["employee"] = u_by_id.get(it["user_id"])
    return {"requests": items}


@api.patch("/admin/profile-edits/{request_id}")
async def review_profile_edit(
    request_id: str,
    payload: ProfileEditReview,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    req = await db.profile_edit_requests.find_one({"request_id": request_id})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.get("status") != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Request is already {req.get('status')}.",
        )
    if (
        user["role"] == "company_admin"
        and req.get("company_id") != user.get("company_id")
    ):
        raise HTTPException(status_code=403, detail="Not your company")

    updates: dict = {
        "status": payload.status,
        "reviewed_by": user["user_id"],
        "reviewed_at": now_iso(),
        "review_note": (payload.review_note or "").strip() or None,
    }
    if payload.status == "approved":
        changes = req.get("changes") or {}
        # Only apply keys we allow — defensive against tampered docs.
        allowed = {
            "name",
            "father_name",
            "dob",
            "doj",
            "designation",
            "present_address",
            "permanent_address",
            "family_members",
        }
        # family_members is a list; treat empty list as intentional "clear"
        user_updates: dict = {}
        for k, v in changes.items():
            if k not in allowed:
                continue
            if k == "family_members":
                if isinstance(v, list):
                    user_updates[k] = v
                continue
            if v:
                user_updates[k] = v
        if user_updates:
            await db.users.update_one(
                {"user_id": req["user_id"]}, {"$set": user_updates}
            )
    await db.profile_edit_requests.update_one(
        {"request_id": request_id}, {"$set": updates}
    )
    fresh = await db.profile_edit_requests.find_one(
        {"request_id": request_id}, {"_id": 0}
    )
    return {"ok": True, "request": fresh}


@api.post("/auth/logout")
async def auth_logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}


# ---------------------------------------------------------------------------
# OTP-based Login (fallback for employees without a Google account)
# ---------------------------------------------------------------------------
import random as _random
import hashlib as _hashlib

OTP_TTL_MINUTES = 10
# SEC-001 fix (Iter 264): the one-time code must NEVER be returned in the
# API response — doing so let anyone request a code for any email (incl.
# super-admin) and log in. Dev echo now defaults OFF and, even when on,
# only a masked hint is ever returned (see otp_request). Set OTP_DEV_MODE=1
# in the environment ONLY for local testing.
OTP_DEV_MODE = os.getenv("OTP_DEV_MODE", "0") == "1"
# SEC-001: minimum seconds between OTP requests for the same identifier.
OTP_RESEND_COOLDOWN_SEC = 45


def _hash_otp(code: str) -> str:
    return _hashlib.sha256(code.encode()).hexdigest()


def _norm_identifier(identifier: str, channel: str) -> str:
    ident = identifier.strip()
    if channel == "email":
        return ident.lower()
    # phone: strip spaces / dashes / parens
    return "".join(c for c in ident if c.isdigit() or c == "+")


async def _send_otp_email(to_email: str, code: str, minutes: int = OTP_TTL_MINUTES) -> dict:
    """Send an OTP code to a user via Resend. Returns {delivered, email_id, error}."""
    subject = f"Your Smart Payroll Login Code: {code}"
    text = (
        f"Your Smart Payroll Login Code is: {code}\n\n"
        f"This code is valid for {minutes} minutes and can only be used once.\n"
        "Always use the code from the NEWEST email — older codes are cancelled.\n"
        "If you didn't request this, you can safely ignore this email.\n\n"
        "From S.K. Sharma & Co\n"
        "Your Trusted Compliance Partner"
    )
    # Big, easy-to-copy code with brand colours
    boxes = "".join(
        f"<span style='display:inline-block;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;"
        f"background:#F7F7F5;border:1px solid #E5E5E0;border-radius:8px;margin:0 4px;"
        f"padding:14px 18px;font-size:28px;font-weight:700;color:#1B3A6E;letter-spacing:2px;'>{d}</span>"
        for d in code
    )
    html = f"""
<!doctype html>
<html>
  <body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#FBFBF9;padding:24px;">
    <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #E5E5E0;">
      <div style="background:#1B3A6E;color:#fff;padding:18px 24px;">
        <div style="font-size:12px;letter-spacing:1.5px;color:#E39A2A;font-weight:700;">S.K. SHARMA &amp; CO.</div>
        <div style="font-size:20px;font-weight:700;margin-top:2px;">Your Smart Payroll Login Code</div>
      </div>
      <div style="padding:24px;">
        <p style="margin:0 0 16px 0;color:#333;font-size:14px;line-height:20px;">
          Use the code below to sign in to the Smart Payroll portal. It expires in
          <strong>{minutes} minutes</strong> —
          always use the code from the <strong>newest</strong> email.
        </p>
        <div style="text-align:center;padding:8px 0 16px 0;">{boxes}</div>
        <p style="margin:0;color:#888;font-size:12px;line-height:18px;">
          Didn&apos;t request this? You can safely ignore this email — no one can access your account without this code.
        </p>
      </div>
      <div style="background:#1B3A6E;padding:16px 24px;text-align:center;">
        <div style="font-size:16px;font-weight:800;color:#E39A2A;letter-spacing:0.6px;">From S.K. Sharma &amp; Co</div>
        <div style="font-size:13px;font-weight:700;color:#FFFFFF;font-style:italic;margin-top:3px;letter-spacing:0.4px;">Your Trusted Compliance Partner</div>
      </div>
    </div>
  </body>
</html>
"""

    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip()
    if not api_key or not to_email:
        return {"delivered": False, "email_id": None, "error": "missing_api_key_or_recipient"}
    # Kill-switch: OTP_EMAIL_ENABLED=false suppresses actual email delivery
    # (the dev_code is still returned in the API response so login flows
    # continue to work during development / testing).
    if os.getenv("OTP_EMAIL_ENABLED", "true").strip().lower() in ("false", "0", "no", "off"):
        return {"delivered": False, "email_id": None, "error": "otp_email_disabled_by_env"}
    try:
        async def _post(frm: str):
            async with httpx.AsyncClient(timeout=10.0) as hc:
                return await hc.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": f"S.K. Sharma & Co. <{frm}>",
                        "to": [to_email],
                        "subject": subject,
                        "text": text,
                        "html": html,
                    },
                )

        r = await _post(from_email)
        # Iter 574 — custom-domain sender not verified yet? Auto-retry with
        # Resend's test sender so login never breaks mid domain-setup.
        if (r.status_code >= 400 and from_email != "onboarding@resend.dev"
                and ("domain is not verified" in (r.text or "").lower()
                     or "not verified" in (r.text or "").lower())):
            logger.warning(f"[Resend] from-domain not verified yet ({from_email}) — retrying with onboarding@resend.dev")
            r = await _post("onboarding@resend.dev")
        if r.status_code < 300:
            data = {}
            try:
                data = r.json()
            except Exception:
                pass
            logger.info(f"[Resend OTP OK] id={data.get('id')} to={to_email}")
            return {"delivered": True, "email_id": data.get("id"), "error": None}
        snippet = r.text[:300] if r.text else ""
        logger.warning(f"[Resend OTP FAIL {r.status_code}] to={to_email} body={snippet}")
        return {"delivered": False, "email_id": None, "error": f"http_{r.status_code}: {snippet}"}
    except httpx.RequestError as exc:
        logger.warning(f"[Resend OTP network error] {exc}")
        return {"delivered": False, "email_id": None, "error": f"network: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Resend OTP unexpected error] {exc}")
        return {"delivered": False, "email_id": None, "error": f"unexpected: {exc}"}


@api.post("/auth/otp/request")
async def otp_request(payload: OtpRequest):
    ident = _norm_identifier(payload.identifier, payload.channel)
    if payload.channel == "sms":
        if not ident or len(ident.lstrip("+")) < 8:
            raise HTTPException(status_code=400, detail="Enter a valid phone number")
    else:
        if "@" not in ident or "." not in ident:
            raise HTTPException(status_code=400, detail="Enter a valid email")

    code = f"{_random.randint(0, 999999):06d}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)
    # SEC-001 fix: throttle resends per identifier to blunt code-guessing
    # and email/SMS flooding.
    prev = await db.otp_codes.find_one({"identifier": ident, "channel": payload.channel})
    if prev and prev.get("created_at"):
        prev_at = prev["created_at"]
        if isinstance(prev_at, str):
            try:
                prev_at = datetime.fromisoformat(prev_at)
            except ValueError:
                prev_at = None
        if prev_at is not None:
            if prev_at.tzinfo is None:
                prev_at = prev_at.replace(tzinfo=timezone.utc)
            wait = OTP_RESEND_COOLDOWN_SEC - (datetime.now(timezone.utc) - prev_at).total_seconds()
            if wait > 0:
                raise HTTPException(
                    status_code=429,
                    detail=f"Please wait {int(wait) + 1}s before requesting another code.",
                )
    await db.otp_codes.update_one(
        {"identifier": ident, "channel": payload.channel},
        {"$set": {
            "identifier": ident,
            "channel": payload.channel,
            "code_hash": _hash_otp(code),
            "expires_at": expires_at,
            "attempts": 0,
            "created_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    # SEC-001 fix: never log the plaintext code.
    logger.info(f"[OTP] issued {payload.channel} code for {ident} (expires {expires_at.isoformat()})")

    resp: dict = {"ok": True, "expires_in": OTP_TTL_MINUTES * 60}

    # Actually deliver the OTP
    delivery: dict = {"delivered": False, "email_id": None, "error": None}
    if payload.channel == "email":
        delivery = await _send_otp_email(ident, code)
    else:
        delivery["error"] = "sms_not_configured"

    resp["delivered"] = delivery["delivered"]
    if delivery.get("email_id"):
        resp["email_id"] = delivery["email_id"]
    if delivery.get("error"):
        resp["delivery_error"] = delivery["error"]

    # SEC-001 fix: the code is NEVER returned in the response. In opt-in
    # local dev mode we return only a masked hint (last 2 digits) so a
    # developer can cross-check the logs — never the full code.
    if OTP_DEV_MODE:
        resp["dev_hint"] = f"code ends in ...{code[-2:]}"
    return resp


@api.post("/auth/otp/verify")
async def otp_verify(payload: OtpVerify):
    ident = _norm_identifier(payload.identifier, payload.channel)
    code = payload.code.strip()
    logger.info(f"[OTP verify] {payload.channel} {ident} attempting code ending in ...{code[-2:] if len(code)>=2 else '??'}")
    if len(code) != 6 or not code.isdigit():
        logger.warning(f"[OTP verify] rejected format: len={len(code)} raw={code!r}")
        raise HTTPException(status_code=400, detail="Enter the 6-digit code")

    row = await db.otp_codes.find_one({"identifier": ident, "channel": payload.channel})
    if not row:
        logger.warning(f"[OTP verify] no active OTP row for {ident}/{payload.channel}")
        raise HTTPException(status_code=400, detail="Request a new code first")

    exp = row.get("expires_at")
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp)
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if not exp or exp < datetime.now(timezone.utc):
        await db.otp_codes.delete_one({"_id": row["_id"]})
        logger.warning(f"[OTP verify] expired code for {ident}")
        raise HTTPException(status_code=400, detail="Code expired. Request a new one.")

    attempts = int(row.get("attempts", 0))
    if attempts >= 5:
        await db.otp_codes.delete_one({"_id": row["_id"]})
        raise HTTPException(status_code=400, detail="Too many attempts. Request a new code.")

    if _hash_otp(code) != row["code_hash"]:
        await db.otp_codes.update_one({"_id": row["_id"]}, {"$inc": {"attempts": 1}})
        logger.warning(
            f"[OTP verify] MISMATCH for {ident}: submitted ends ...{code[-2:]}, "
            f"expected hash starts {row['code_hash'][:8]}, attempts={attempts+1}"
        )
        raise HTTPException(status_code=400, detail="Incorrect code")

    logger.info(f"[OTP verify] SUCCESS for {ident}")

    # Consume the OTP
    await db.otp_codes.delete_one({"_id": row["_id"]})

    # Find or create the user
    lookup_field = "email" if payload.channel == "email" else "phone"
    existing = await db.users.find_one({lookup_field: ident}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        display_name = existing.get("name") or ident
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        role = _resolve_role_on_signup(ident if payload.channel == "email" else "")
        # SEC-001 fix: never auto-create a privileged account through an
        # unauthenticated OTP flow. Admin accounts must be provisioned
        # explicitly. Only self-service employee accounts may be created.
        if role != "employee":
            logger.warning(
                f"[OTP verify] blocked privileged auto-provision for {ident} (role={role})")
            raise HTTPException(
                status_code=403,
                detail="This account must be set up by an administrator.",
            )
        display_name = ident if payload.channel == "email" else f"User {ident[-4:]}"
        user_doc = {
            "user_id": user_id,
            "email": ident if payload.channel == "email" else None,
            "phone": ident if payload.channel == "sms" else None,
            "name": display_name,
            "picture": None,
            "role": role,
            "company_id": None,
            "department": None,
            "position": None,
            "employee_code": None,
            "father_name": None,
            "dob": None,
            "doj": None,
            "shift_start": None,
            "shift_end": None,
            "salary_monthly": None,
            "half_day_hrs": None,
            "full_day_hrs": None,
            "onboarded": role != "employee",
            "created_at": now_iso(),
        }
        await db.users.insert_one(user_doc)

    token = f"otp_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
    await db.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": expires,
        "created_at": datetime.now(timezone.utc),
        "auth_method": "otp",
    })
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return {"session_token": token, "user": user}


# ---------------------------------------------------------------------------
# Iter 77 - Employee Code + Phone-Last-4 login gate.
# ---------------------------------------------------------------------------
# Bulk-imported employees (LAPL / KEPS) got auto-generated placeholder emails
# (``emp0004@lapl.local``) they never see, and SMS OTP delivery isn't wired
# yet. This lightweight gate lets them sign in with what they DO know:
#   1. Employee Code (printed on their ID card / attendance card)
#   2. Last 4 digits of their phone (shared secret with HR)
# We match on both fields, ignoring case / whitespace, and issue a session
# token. Rate-limited by per-employee attempt count to prevent brute force.

class EmpCodeLoginPayload(BaseModel):
    employee_code: str
    phone_last4: str  # phone last-4 OR the employee's 4-digit PIN (phoneless staff)
    pin: Optional[str] = None
    company_id: Optional[str] = None  # optional disambiguation when
                                      # multiple firms share codes


async def _maybe_first_login_punch(user: Dict[str, Any]) -> None:
    """Iter 96f — user rule: when a NEWLY-JOINED employee is approved, their
    FIRST app login auto-creates a Punch-IN at that moment. Every punch
    after that follows the normal app punching policy (geofence / biometric
    / approval queue). The ``first_login_punch_pending`` flag is set by
    /admin/approve-employee and consumed exactly once here."""
    if user.get("role") != "employee" or not user.get("first_login_punch_pending"):
        return
    if not user.get("company_id"):
        return
    # Consume the flag atomically so two parallel logins can't double-punch.
    res = await db.users.update_one(
        {"user_id": user["user_id"], "first_login_punch_pending": True},
        {"$unset": {"first_login_punch_pending": ""},
         "$set": {"first_login_punch_at": now_iso()}},
    )
    if res.modified_count != 1:
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing = await db.attendance.find_one(
        {"user_id": user["user_id"], "date": today, "status": {"$ne": "rejected"}},
        {"_id": 0, "record_id": 1},
    )
    if existing:
        return  # already punched today (e.g. via biometric device) — skip
    at = now_iso()
    await db.attendance.insert_one({
        "record_id": f"att_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "company_id": user["company_id"],
        "branch_id": None,
        "branch_name": None,
        "date": today,
        "kind": "in",
        "at": at,
        "original_at": at,
        "latitude": None,
        "longitude": None,
        "distance_m": 0.0,
        "biometric_method": None,
        "selfie_base64": None,
        "device_info": None,
        "source": "first-login-auto",
        "outside_geofence": False,
        "gps_verified": False,
        "location_status": "no-gps",
        "status": "approved",
        "decision_at": at,
        "decision_by": "system",
        "decision_reason": "Auto punch-in at first login after joining approval",
    })
    logger.info(
        "[first-login-punch] auto punch-in for %s (%s)",
        user.get("name"), user["user_id"],
    )


@api.post("/auth/emp-code-login")
async def emp_code_login(payload: EmpCodeLoginPayload):
    code = (payload.employee_code or "").strip().lstrip("0") or "0"
    # Also try the un-stripped form so codes like "0004" match "0004".
    code_variants = {code, (payload.employee_code or "").strip()}
    last4 = (payload.phone_last4 or "").strip()
    if not code or not last4.isdigit() or len(last4) != 4:
        raise HTTPException(
            status_code=400,
            detail="Enter your Employee Code + last 4 digits of your phone.",
        )

    # Build the query. We try both zero-padded and stripped variants to be
    # tolerant to how HR wrote the code in Excel vs. what the employee types.
    query: Dict[str, Any] = {
        "role": "employee",
        "employee_code": {"$in": list(code_variants)},
    }
    if payload.company_id:
        query["company_id"] = payload.company_id

    candidates = await db.users.find(query, {"_id": 0}).to_list(20)
    matches = [u for u in candidates if (u.get("phone") or "").replace(" ", "").endswith(last4)]

    # Iter 93 — Many imported workers have NO phone on file. For those,
    # accept their 4-digit PIN in place of the phone last-4 so they can
    # still sign in with just Employee Code + PIN.
    if not matches:
        pin_val = (payload.pin or last4).strip()
        matches = [
            u for u in candidates
            if not (u.get("phone") or "").strip()
            and u.get("pin_hash")
            and _verify_pin(pin_val, u["pin_hash"])
        ]

    if not matches:
        logger.warning(
            f"[emp-code-login] no match for code={code!r} last4={last4} "
            f"cid={payload.company_id!r} (candidates={len(candidates)})"
        )
        # Rate-limit: track failed attempts per (code + last4) tuple.
        await db.emp_login_attempts.update_one(
            {"code": code, "last4": last4},
            {
                "$inc": {"attempts": 1},
                "$setOnInsert": {"created_at": now_iso()},
                "$set": {"last_attempt_at": now_iso()},
            },
            upsert=True,
        )
        raise HTTPException(
            status_code=401,
            detail="Employee code + phone last 4 don't match. Contact HR if you moved firms or updated your phone.",
        )
    if len(matches) > 1:
        # Ambiguous - ask them to pick a firm explicitly.
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Multiple matches - specify company_id.",
                "candidates": [
                    {"user_id": u.get("user_id"), "company_id": u.get("company_id"),
                     "name": u.get("name")}
                    for u in matches
                ],
            },
        )

    user = matches[0]
    user_id = user["user_id"]

    # Success -> reset the rate-limit counter
    await db.emp_login_attempts.delete_many({"code": code, "last4": last4})

    # Iter 285 — onboarding approval gate (pending/hold/rejected staff).
    await _onboarding_login_gate(user)

    token = f"emp_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    # Iter 295 — employee PWA sessions live 90 days (no auto-logout).
    expires = datetime.now(timezone.utc) + timedelta(hours=EMPLOYEE_SESSION_TTL_HOURS)
    await db.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": expires,
        "created_at": datetime.now(timezone.utc),
        "auth_method": "emp_code",
    })
    logger.info(f"[emp-code-login] SUCCESS user_id={user_id} name={user.get('name')!r}")
    await _maybe_first_login_punch(user)
    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return {"session_token": token, "user": fresh}


# ---------------------------------------------------------------------------
# PIN-based login for employees
# ---------------------------------------------------------------------------
def _generate_temp_pin() -> str:
    """Generate a random 6-digit numeric PIN."""
    return f"{_secrets.randbelow(1000000):06d}"


def _hash_pin(pin: str) -> str:
    """bcrypt hash a PIN. Returns utf-8 string."""
    return _bcrypt.hashpw(pin.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_pin(pin: str, pin_hash: str) -> bool:
    try:
        return _bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("utf-8"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Admin password auth (web portal). PINs are optimised for mobile keypads;
# desktops use a full email + password login. We reuse bcrypt so the same
# hashing story applies to both credentials.
# ---------------------------------------------------------------------------
_MIN_PASSWORD_LEN = 8


def _hash_password(pw: str) -> str:
    return _bcrypt.hashpw(pw.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_password(pw: str, pw_hash: str) -> bool:
    try:
        return _bcrypt.checkpw(pw.encode("utf-8"), pw_hash.encode("utf-8"))
    except Exception:
        return False


def _validate_password_strength(pw: str) -> None:
    if not pw or len(pw) < _MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {_MIN_PASSWORD_LEN} characters",
        )
    has_letter = any(c.isalpha() for c in pw)
    has_digit = any(c.isdigit() for c in pw)
    if not (has_letter and has_digit):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one letter AND one digit",
        )


def _generate_temp_password() -> str:
    """Generates a friendly-to-type 10-char temp password: 6 alphanumeric +
    dash + 3 digits, e.g. Ax7Ky9-472. Avoids look-alike chars."""
    import string
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz"
    digits = "23456789"
    body = "".join(_secrets.choice(letters + digits) for _ in range(6))
    tail = "".join(_secrets.choice(digits) for _ in range(3))
    return f"{body}-{tail}"


async def _next_employee_code(company_id: str) -> Optional[str]:
    """Generate the next sequential employee code for a company using the
    format ``<COMPANY_CODE><NNNN>`` (e.g. ``SKS0001``). Legacy codes that do
    NOT match this exact pattern are ignored — they stay untouched but new
    codes will not collide with them.

    Returns None if the company (or its company_code) is missing.
    """
    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "company_code": 1}
    )
    if not company:
        return None
    prefix = ((company.get("company_code") or "") or "EMP").upper().strip()
    if not prefix:
        prefix = "EMP"
    pattern = f"^{re.escape(prefix)}\\d{{4}}$"
    cur = db.users.find(
        {"company_id": company_id, "employee_code": {"$regex": pattern}},
        {"_id": 0, "employee_code": 1},
    )
    max_n = 0
    async for u in cur:
        code = u.get("employee_code") or ""
        try:
            n = int(code[len(prefix):])
            if n > max_n:
                max_n = n
        except Exception:
            continue
    # Walk forward until we hit a free slot (handles the pathological case
    # where two racing signups pick the same slot — rare but safe).
    for i in range(max_n + 1, max_n + 30):
        if i > 9999:
            break
        candidate = f"{prefix}{i:04d}"
        exists = await db.users.find_one(
            {"company_id": company_id, "employee_code": candidate}, {"_id": 1}
        )
        if not exists:
            return candidate
    return None


def _validate_pin_format(pin: str) -> None:
    p = (pin or "").strip()
    if len(p) != 6 or not p.isdigit():
        raise HTTPException(status_code=400, detail="PIN must be exactly 6 digits")
    if len(set(p)) == 1:
        raise HTTPException(status_code=400, detail="PIN cannot be all the same digit")
    if p in {"123456", "654321", "000000", "111111"}:
        raise HTTPException(status_code=400, detail="Please choose a less obvious PIN")


async def _issue_session(user_id: str, method: str) -> str:
    token = f"{method}_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    # Iter 295 — role-based TTL: employees 90 days, admins 12 hours.
    _u = await db.users.find_one({"user_id": user_id}, {"_id": 0, "role": 1})
    expires = datetime.now(timezone.utc) + timedelta(
        hours=_session_ttl_hours_for_role((_u or {}).get("role")))
    await db.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": expires,
        "created_at": datetime.now(timezone.utc),
        "auth_method": method,
    })
    return token


# ---------------------------------------------------------------------------
# Iter 569 — 2FA/MFA for Super Admin & Sub (Super) Admin.
# Backend-enforced: valid credentials → temporary pre-auth challenge →
# OTP (hashed, 5-min, one-time, max attempts) → full session.
# OTP channels: Email (Resend, live), WhatsApp Cloud API and SMS
# (both pluggable — configured in Administration → Security 2FA).
# ---------------------------------------------------------------------------
import secrets as _twofa_secrets  # noqa: E402

_TWOFA_DEFAULTS = {
    "key": "2fa",
    # Iter 591 (user request) — OTP login applies to ALL portal users
    # managed under Access & Workflow Management: client admins and client
    # staff too, not just Super/Sub admins.
    "mandatory_roles": ["super_admin", "sub_admin", "company_admin", "company_staff"],
    "otp_length": 6,
    # Iter 571 — per user request: OTP valid 2 minutes, resend after 2 minutes.
    "otp_validity_min": 2,
    "resend_cooldown_sec": 120,
    "max_attempts": 5,
    "email_enabled": True,
    "whatsapp_enabled": True,
    "sms_enabled": True,
    "trusted_device_enabled": False,
    "trusted_days": 30,
    "security_alerts_enabled": True,
    # Iter 573 — OTP email routing. otp_email_via_smtp: deliver login OTPs
    # through the firm's own SMTP (Email Settings) so ANY recipient works.
    # fallback_to_admin_email: forward undeliverable OTPs to the Super
    # Admin inbox — OFF by default per user request (was flooding Gmail).
    "otp_email_via_smtp": False,
    "fallback_to_admin_email": False,
    "whatsapp_config": {"access_token": "", "phone_number_id": "", "template_name": ""},
    "sms_config": {"provider": "", "twilio_sid": "", "twilio_token": "", "twilio_from": "",
                   "msg91_authkey": "", "msg91_sender": "", "msg91_template_id": "",
                   "fast2sms_key": ""},
}
TWOFA_PENDING_TTL_MIN = 10  # window to complete OTP entry after password


async def _twofa_settings() -> dict:
    doc = await db.security_settings.find_one({"key": "2fa"}, {"_id": 0}) or {}
    st = {**_TWOFA_DEFAULTS, **doc}
    st["whatsapp_config"] = {**_TWOFA_DEFAULTS["whatsapp_config"], **(doc.get("whatsapp_config") or {})}
    st["sms_config"] = {**_TWOFA_DEFAULTS["sms_config"], **(doc.get("sms_config") or {})}
    # Super/sub admin 2FA is MANDATORY and cannot be switched off.
    for r in ("super_admin", "sub_admin"):
        if r not in st["mandatory_roles"]:
            st["mandatory_roles"].append(r)
    return st


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    name, dom = email.split("@", 1)
    return f"{name[0]}*****@{dom}"


def _mask_mobile(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    return f"******{digits[-4:]}" if len(digits) >= 4 else ""


def _twofa_channel_ready(method: str, st: dict) -> bool:
    if method == "email":
        return bool(st["email_enabled"] and (
            os.getenv("RESEND_API_KEY", "").strip() or st.get("otp_email_via_smtp")))
    if method == "whatsapp":
        wc = st["whatsapp_config"]
        return bool(st["whatsapp_enabled"] and wc.get("access_token") and wc.get("phone_number_id"))
    if method == "sms":
        sc = st["sms_config"]
        prov = (sc.get("provider") or "").lower()
        if not st["sms_enabled"]:
            return False
        if prov == "twilio":
            return bool(sc.get("twilio_sid") and sc.get("twilio_token") and sc.get("twilio_from"))
        if prov == "msg91":
            return bool(sc.get("msg91_authkey"))
        if prov == "fast2sms":
            return bool(sc.get("fast2sms_key"))
        return False
    return False


def _twofa_methods_for_user(user: dict, st: dict) -> list:
    out = []
    if user.get("email"):
        out.append({"method": "email", "target": _mask_email(user["email"]),
                    "configured": _twofa_channel_ready("email", st)})
    if user.get("phone"):
        out.append({"method": "whatsapp", "target": _mask_mobile(user["phone"]),
                    "configured": _twofa_channel_ready("whatsapp", st)})
        out.append({"method": "sms", "target": _mask_mobile(user["phone"]),
                    "configured": _twofa_channel_ready("sms", st)})
    return out


async def _twofa_send_code(user: dict, method: str, code: str, st: dict) -> dict:
    """Dispatch OTP over the requested channel. Returns {delivered, error}."""
    minutes = int(st["otp_validity_min"])
    if method == "email":
        if not st.get("email_enabled", True):
            return {"delivered": False, "error": "email_not_configured"}
        if not (user.get("email") or "").strip():
            return {"delivered": False, "error": "no_email_on_profile"}
        # Iter 573 — optional delivery via the firm's own SMTP (Email
        # Settings): works for EVERY recipient (no Resend test-mode limit).
        async def _try_smtp() -> bool:
            try:
                from routes.email_notifications import _get_settings as _smtp_get, _smtp_send
                smtp = await _smtp_get()
                if smtp and smtp.get("enabled") and smtp.get("username"):
                    await _smtp_send(
                        smtp, user["email"],
                        f"Your Smart Payroll Login Code: {code}",
                        (f"Your Smart Payroll Login Code is: {code}\n\n"
                         f"This code is valid for {minutes} minutes and can only be used once.\n"
                         "Always use the code from the NEWEST email — older codes are cancelled.\n\n"
                         "From S.K. Sharma & Co\n"
                         "Your Trusted Compliance Partner"))
                    return True
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[2FA smtp FAIL] {exc}")
            return False

        if st.get("otp_email_via_smtp"):
            if await _try_smtp():
                return {"delivered": True, "error": None, "note": "sent_via_smtp"}
            logger.warning("[2FA smtp] primary SMTP delivery failed/not configured — using Resend")
        if not os.getenv("RESEND_API_KEY", "").strip():
            # No Resend key — last chance: SMTP even if the toggle is off.
            if await _try_smtp():
                return {"delivered": True, "error": None, "note": "sent_via_smtp"}
            return {"delivered": False, "error": "email_not_configured"}
        r = await _send_otp_email(user["email"], code, minutes)
        if r["delivered"]:
            return {"delivered": True, "error": None}
        err = str(r.get("error") or "")
        # Resend TEST MODE only delivers to the account owner.
        if "only send testing emails" in err:
            # Iter 574 — auto-rescue: if the firm's SMTP is configured, use
            # it so the sub user still gets the OTP on their OWN email.
            if await _try_smtp():
                return {"delivered": True, "error": None, "note": "sent_via_smtp"}
            # Forward to the Super Admin inbox ONLY when explicitly enabled.
            if st.get("fallback_to_admin_email"):
                sa = await db.users.find_one(
                    {"role": "super_admin", "email": {"$nin": [None, ""]}}, {"email": 1})
                if sa and sa["email"].strip().lower() != user["email"].strip().lower():
                    r2 = await _send_otp_email(sa["email"], code, minutes)
                    if r2["delivered"]:
                        logger.warning(
                            f"[2FA] Resend test-mode: OTP for {user['email']} "
                            f"delivered to owner {sa['email']} instead")
                        return {"delivered": True, "error": None,
                                "note": f"sent_to_admin:{_mask_email(sa['email'])}"}
            return {"delivered": False, "error": "email_test_mode_restriction"}
        return {"delivered": False, "error": r.get("error")}
    msg = (f"Your Payroll Security OTP is {code}. This OTP is valid for "
           f"{minutes} minutes. Do not share this OTP with anyone.")
    phone = user.get("phone") or ""
    if method == "whatsapp":
        if not _twofa_channel_ready("whatsapp", st):
            return {"delivered": False, "error": "whatsapp_not_configured"}
        wc = st["whatsapp_config"]
        try:
            async with httpx.AsyncClient(timeout=15.0) as hc:
                r = await hc.post(
                    f"https://graph.facebook.com/v20.0/{wc['phone_number_id']}/messages",
                    headers={"Authorization": f"Bearer {wc['access_token']}",
                             "Content-Type": "application/json"},
                    json={"messaging_product": "whatsapp",
                          "to": phone.lstrip("+"),
                          "type": "text",
                          "text": {"body": msg}},
                )
            if r.status_code < 300:
                return {"delivered": True, "error": None}
            logger.warning(f"[2FA whatsapp FAIL {r.status_code}] {r.text[:200]}")
            return {"delivered": False, "error": f"whatsapp_http_{r.status_code}"}
        except Exception as exc:  # noqa: BLE001
            return {"delivered": False, "error": f"whatsapp_error: {exc}"}
    if method == "sms":
        # Iter 576 — MSG91 first (company-wise SMS Settings), then legacy
        # providers from Security 2FA settings.
        try:
            from shared.sms_service import send_otp_sms, get_sms_settings
            m91 = await get_sms_settings(db, user.get("company_id"))
            if m91["enabled"] and m91["otp_enabled"]:
                return await send_otp_sms(db, user, code, minutes)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[2FA msg91 FAIL] {exc}")
        if not _twofa_channel_ready("sms", st):
            return {"delivered": False, "error": "sms_not_configured"}
        sc = st["sms_config"]
        prov = (sc.get("provider") or "").lower()
        try:
            async with httpx.AsyncClient(timeout=15.0) as hc:
                if prov == "twilio":
                    r = await hc.post(
                        f"https://api.twilio.com/2010-04-01/Accounts/{sc['twilio_sid']}/Messages.json",
                        auth=(sc["twilio_sid"], sc["twilio_token"]),
                        data={"To": phone, "From": sc["twilio_from"], "Body": msg},
                    )
                elif prov == "msg91":
                    r = await hc.post(
                        "https://control.msg91.com/api/v5/flow/",
                        headers={"authkey": sc["msg91_authkey"],
                                 "Content-Type": "application/json"},
                        json={"template_id": sc.get("msg91_template_id") or "",
                              "sender": sc.get("msg91_sender") or "",
                              "recipients": [{"mobiles": phone.lstrip("+"),
                                              "otp": code}]},
                    )
                else:  # fast2sms
                    r = await hc.post(
                        "https://www.fast2sms.com/dev/bulkV2",
                        headers={"authorization": sc["fast2sms_key"]},
                        data={"route": "otp", "variables_values": code,
                              "numbers": "".join(c for c in phone if c.isdigit())[-10:]},
                    )
            if r.status_code < 300:
                return {"delivered": True, "error": None}
            logger.warning(f"[2FA sms FAIL {r.status_code}] {r.text[:200]}")
            return {"delivered": False, "error": f"sms_http_{r.status_code}"}
        except Exception as exc:  # noqa: BLE001
            return {"delivered": False, "error": f"sms_error: {exc}"}
    return {"delivered": False, "error": "unknown_method"}


def _req_ip(request: Request) -> str:
    return ((request.headers.get("x-forwarded-for")
             or (request.client.host if request.client else "") or "")
            .split(",")[0].strip())


async def _twofa_audit(user: dict, action: str, request: Optional[Request],
                       success: bool, details: str = "", method: str = ""):
    """Named security events feed the SAME Users Log Report (activity_log)."""
    try:
        await db.activity_log.insert_one({
            "at": now_iso(),
            "actor_id": (user or {}).get("user_id"),
            "actor_name": (user or {}).get("name"),
            "actor_role": (user or {}).get("role"),
            "company_id": (user or {}).get("company_id"),
            "method": "POST",
            "path": (request.url.path if request else "")[:300],
            "action": f"LOGIN {action}" + (f" via {method}" if method else ""),
            "status": 200 if success else 401,
            "success": success,
            "module": "Auth",
            "record_id": None,
            "record_label": (user or {}).get("name") or "",
            "changes": [],
            "old_values": None,
            "new_values": None,
            "details": details[:400],
            "device": ((request.headers.get("user-agent") if request else "") or "")[:200],
            "ip": _req_ip(request) if request else "",
        })
    except Exception:
        logger.warning("[2FA audit] failed to record", exc_info=True)


def _twofa_new_code(length: int) -> str:
    return str(_twofa_secrets.randbelow(10 ** length)).zfill(length)


# Iter 570 — proactive Security Alerts: email every Super Admin when a
# failed-OTP lockout happens or an admin signs in from a brand-new IP.
async def _send_security_alert(subject: str, lines: list, st: Optional[dict] = None):
    try:
        st = st or await _twofa_settings()
        if not st.get("security_alerts_enabled", True):
            return
        api_key = os.getenv("RESEND_API_KEY", "").strip()
        if not api_key:
            return
        from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip()
        recipients = []
        async for u in db.users.find(
                {"role": "super_admin", "email": {"$nin": [None, ""]}},
                {"email": 1}).limit(10):
            recipients.append(u["email"])
        if not recipients:
            return
        rows = "".join(
            f"<tr><td style='padding:4px 14px 4px 0;color:#64748b;font-size:13px;"
            f"white-space:nowrap'>{k}</td><td style='padding:4px 0;font-size:13px;"
            f"color:#0f172a'><strong>{v}</strong></td></tr>"
            for k, v in lines)
        html = (
            "<div style='font-family:Arial,sans-serif;max-width:520px;margin:0 auto;"
            "border:1px solid #e2e8f0;border-radius:10px;overflow:hidden'>"
            "<div style='background:#b91c1c;color:#fff;padding:14px 20px;font-size:15px;"
            f"font-weight:bold'>🔐 Security Alert — S.K. Sharma &amp; Co. Payroll</div>"
            f"<div style='padding:18px 20px'><table>{rows}</table>"
            "<p style='font-size:12px;color:#64748b;margin-top:14px'>Review the full "
            "trail in <strong>Reports → Users Log Report</strong>. If this was not "
            "expected, open <strong>Administration → Security · 2FA/MFA</strong> and "
            "use “Logout from all devices”.</p></div></div>")
        text = subject + "\n\n" + "\n".join(f"{k}: {v}" for k, v in lines)
        async with httpx.AsyncClient(timeout=10.0) as hc:
            r = await hc.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={"from": f"S.K. Sharma & Co. Security <{from_email}>",
                      "to": recipients, "subject": subject,
                      "text": text, "html": html})
        logger.info(f"[security-alert] '{subject}' → {len(recipients)} super admin(s) ({r.status_code})")
    except Exception:
        logger.warning("[security-alert] send failed", exc_info=True)


async def _security_check_new_ip(user: dict, request: Request):
    """Called after a successful Super/Sub admin login. Records the IP and
    alerts Super Admins the first time a brand-new IP is used."""
    try:
        ip = _req_ip(request)
        if not ip:
            return
        existing = await db.login_ips.find_one({"user_id": user["user_id"], "ip": ip})
        had_any = await db.login_ips.count_documents({"user_id": user["user_id"]}) > 0
        device = (request.headers.get("user-agent") or "")[:200]
        await db.login_ips.update_one(
            {"user_id": user["user_id"], "ip": ip},
            {"$set": {"last_seen": now_iso(), "device": device},
             "$setOnInsert": {"first_seen": now_iso()},
             "$inc": {"count": 1}},
            upsert=True)
        if existing is None and had_any:
            await _twofa_audit(user, "NEW_IP_LOGIN", request, True,
                               f"First login from IP {ip}")
            await _send_security_alert(
                f"⚠️ New IP login — {user.get('name') or user.get('email')}",
                [("Event", "Login from a NEW IP address"),
                 ("User", f"{user.get('name') or '—'} ({user.get('role') or '—'})"),
                 ("Email", user.get("email") or "—"),
                 ("IP Address", ip),
                 ("Device", device[:120] or "—"),
                 ("Time (UTC)", now_iso()[:19].replace("T", " "))])
    except Exception:
        logger.warning("[security-alert] new-ip check failed", exc_info=True)


async def _twofa_methods_async(user: dict, st: dict) -> list:
    """Methods list + MSG91 override: SMS shows 'configured' when the firm's
    MSG91 OTP channel (SMS Settings) is enabled, even without legacy config."""
    methods = _twofa_methods_for_user(user, st)
    try:
        from shared.sms_service import get_sms_settings as _g91
        m91 = await _g91(db, user.get("company_id"))
        if m91["enabled"] and m91["otp_enabled"] and m91["authkey"]:
            for m in methods:
                if m["method"] == "sms":
                    m["configured"] = True
    except Exception:
        pass
    return methods


async def _start_2fa_challenge(user: dict, request: Request, login_kind: str):
    """Called AFTER credentials verified. Returns the challenge response
    dict when 2FA is required, or None when login can proceed normally."""
    st = await _twofa_settings()
    required = user.get("role") in st["mandatory_roles"] or bool(user.get("twofa_enabled"))
    if not required:
        return None
    # Trusted-device bypass (only when the feature is switched ON).
    if st["trusted_device_enabled"]:
        dt = (request.headers.get("x-device-token") or "").strip()
        if dt:
            td = await db.trusted_devices.find_one({
                "user_id": user["user_id"],
                "token_hash": _hash_otp(dt),
                "revoked_at": None,
            })
            exp = (td or {}).get("expires_at")
            if isinstance(exp, str):
                try:
                    exp = datetime.fromisoformat(exp)
                except ValueError:
                    exp = None
            if exp is not None and exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if td and exp and exp > datetime.now(timezone.utc):
                await db.trusted_devices.update_one(
                    {"_id": td["_id"]},
                    {"$set": {"last_used_at": now_iso(), "ip_address": _req_ip(request)}})
                await _twofa_audit(user, "TRUSTED_DEVICE_LOGIN", request, True,
                                   f"device={td.get('device_name') or ''}")
                await _security_check_new_ip(user, request)
                return None
    methods = await _twofa_methods_async(user, st)
    configured = [m for m in methods if m["configured"]]
    preferred = user.get("twofa_method") or "email"
    method = next((m["method"] for m in configured if m["method"] == preferred),
                  (configured[0]["method"] if configured else "email"))
    code = _twofa_new_code(int(st["otp_length"]))
    now = datetime.now(timezone.utc)
    pending_id = f"2fa_{_twofa_secrets.token_hex(24)}"
    # Iter 571 — ONE active challenge per user: a new login invalidates all
    # previous pending OTPs (prevents "old email code" confusion).
    await db.twofa_pending.delete_many({"user_id": user["user_id"]})
    await db.twofa_pending.insert_one({
        "pending_id": pending_id,
        "user_id": user["user_id"],
        "login_kind": login_kind,
        "otp_hash": _hash_otp(code),
        "otp_expires_at": now + timedelta(minutes=int(st["otp_validity_min"])),
        "expires_at": now + timedelta(minutes=TWOFA_PENDING_TTL_MIN),
        "attempts": 0,
        "blocked": False,
        "method": method,
        "resend_available_at": now + timedelta(seconds=int(st["resend_cooldown_sec"])),
        "created_at": now,
        "ip": _req_ip(request),
        "device": (request.headers.get("user-agent") or "")[:200],
    })
    delivery = await _twofa_send_code(user, method, code, st)
    await _twofa_audit(user, "OTP_GENERATED", request, True, "6-digit OTP issued", method)
    await _twofa_audit(user, f"OTP_SENT_{method.upper()}", request,
                       bool(delivery["delivered"]),
                       delivery.get("error") or "delivered", method)
    resp = {
        "twofa_required": True,
        "pending_token": pending_id,
        "method": method,
        "methods": methods,
        "masked_email": _mask_email(user.get("email") or ""),
        "masked_mobile": _mask_mobile(user.get("phone") or ""),
        "otp_expires_in": int(st["otp_validity_min"]) * 60,
        "resend_cooldown": int(st["resend_cooldown_sec"]),
        "max_attempts": int(st["max_attempts"]),
        "trusted_device_enabled": bool(st["trusted_device_enabled"]),
        "delivered": delivery["delivered"],
    }
    if delivery.get("error"):
        resp["delivery_error"] = delivery["error"]
    if delivery.get("note"):
        resp["delivery_note"] = delivery["note"]
    if OTP_DEV_MODE:
        resp["dev_hint"] = f"code ends in ...{code[-2:]}"
    return resp


@api.post("/auth/admin-pin-login")
async def admin_pin_login(payload: AdminPinLoginRequest, request: Request):
    """Company/Super admins log in with one of:
      • email + 6-digit PIN
      • phone + 6-digit PIN
      • company_code + 6-digit PIN (resolves to the primary company_admin
        of that firm — useful for existing companies whose admins don't
        remember the exact email/phone they signed up with).

    Employees should use `/auth/pin-login` with company + employee code.
    """
    raw_ident = (payload.identifier or "").strip()
    raw_code = (payload.company_code or "").strip().upper()
    pin = (payload.pin or "").strip()

    if not raw_ident and not raw_code:
        raise HTTPException(
            status_code=400,
            detail="Provide either your registered mobile/email or your company code.",
        )
    if not pin:
        raise HTTPException(status_code=400, detail="PIN is required")
    if not pin.isdigit() or len(pin) != 6:
        raise HTTPException(status_code=400, detail="PIN must be 6 digits")

    # Try email/phone match first, then company_code
    user = None
    phone_norm: Optional[str] = None
    lookup_by = "identifier"
    if raw_ident:
        if "@" in raw_ident:
            user = await db.users.find_one({"email": raw_ident.lower()}, {"_id": 0})
        else:
            phone_norm = _normalise_phone(raw_ident)
            user = await db.users.find_one({"phone": phone_norm}, {"_id": 0})
            if not user:
                # Iter 93 — also accept the admin's User ID (login_id)
                user = await db.users.find_one(
                    {"login_id": {"$regex": f"^{re.escape(raw_ident)}$", "$options": "i"}},
                    {"_id": 0},
                )
    elif raw_code:
        lookup_by = "company_code"
        company = await db.companies.find_one(
            {"company_code": raw_code},
            {"_id": 0, "company_id": 1, "name": 1},
        )
        if not company:
            raise HTTPException(
                status_code=404,
                detail=f"No company found for code '{raw_code}'. Check the code and try again.",
            )
        # Prefer the earliest-created company_admin as the primary account
        # for this company (there is exactly one at self-registration time).
        candidates = await db.users.find(
            {"company_id": company["company_id"], "role": "company_admin"},
            {"_id": 0},
        ).sort("created_at", 1).to_list(50)
        # Only the ones with an active PIN can log in this way.
        user = next((u for u in candidates if u.get("pin_hash")), None)
        if not user:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Company '{company.get('name') or raw_code}' does not have "
                    "an active admin PIN yet. Sign in with your registered "
                    "email or mobile instead."
                ),
            )

    if not user or not user.get("pin_hash"):
        # If they logged in via email/phone AND there's a pending company_request,
        # give a clearer error so the admin doesn't think their PIN is wrong.
        if lookup_by == "identifier":
            req_query: dict = {}
            if "@" in raw_ident:
                req_query = {"contact_email": raw_ident.lower()}
            else:
                req_query = {"contact_mobile": phone_norm}
            pending_req = await db.company_requests.find_one(
                {**req_query, "status": {"$in": ["pending", "rejected"]}},
                {"_id": 0, "status": 1, "company_name": 1, "admin_note": 1},
            )
            if pending_req and pending_req.get("status") == "pending":
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Your company registration for '{pending_req.get('company_name','')}' "
                        "is still awaiting approval. You'll be able to sign in once a super admin approves it."
                    ),
                )
            if pending_req and pending_req.get("status") == "rejected":
                note = (pending_req.get("admin_note") or "").strip()
                suffix = f" Reason: {note}" if note else ""
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Your company registration was rejected. Please contact the super admin to re-apply.{suffix}"
                    ),
                )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _is_linked_staff = (
        user.get("role") == "employee" and bool(user.get("is_company_staff"))
    )
    if user.get("role") not in ("company_admin", "super_admin", "sub_admin", "company_staff") \
            and not _is_linked_staff:
        raise HTTPException(status_code=403, detail="This login is only for administrators")

    # Disabled-account guard (super admin bypasses)
    if user.get("role") != "super_admin":
        if user.get("disabled"):
            raise HTTPException(status_code=403, detail="Your account has been disabled. Please contact S.K. Sharma & Co.")
        if user.get("company_id"):
            company = await db.companies.find_one({"company_id": user["company_id"]}, {"_id": 0, "enabled": 1, "name": 1})
            if company and company.get("enabled") is False:
                raise HTTPException(status_code=403, detail=f"Access to '{company.get('name') or 'this company'}' has been temporarily suspended.")

    # Lockout guard (shared with employee flow)
    fails = int(user.get("pin_fail_count", 0))
    lock_until = user.get("pin_locked_until")
    if isinstance(lock_until, str):
        try:
            lock_until = datetime.fromisoformat(lock_until)
        except Exception:
            lock_until = None
    if lock_until and (lock_until.tzinfo is None):
        lock_until = lock_until.replace(tzinfo=timezone.utc)
    if lock_until and lock_until > datetime.now(timezone.utc):
        remaining = int((lock_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
        raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {remaining} minute(s).")

    if not _verify_pin(pin, user["pin_hash"]):
        fails += 1
        upd: dict = {"pin_fail_count": fails, "pin_last_fail_at": now_iso()}
        if fails >= 5:
            upd["pin_locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            upd["pin_fail_count"] = 0
            logger.warning(f"[PIN admin] LOCKED {user.get('email')} after 5 failed attempts")
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": upd})
        raise HTTPException(status_code=401, detail="Invalid credentials")

    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"pin_fail_count": 0, "pin_last_login_at": now_iso(), "pin_locked_until": None}},
    )
    # Iter 569 — 2FA gate for Super/Sub admins: no session until OTP verified.
    if not _is_linked_staff:
        _challenge = await _start_2fa_challenge(user, request, "pin")
        if _challenge is not None:
            return _challenge
    token = await _issue_session(
        user["user_id"],
        "staff_portal_pin" if _is_linked_staff else "pin",
    )
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    fresh = await _enrich_user_with_company(fresh)
    if _is_linked_staff:
        _crole = await db.company_roles.find_one(
            {"role_id": fresh.get("company_role_id") or "", "company_id": fresh.get("company_id")},
            {"_id": 0},
        )
        fresh["is_company_staff"] = True
        fresh["staff_role_name"] = (_crole or {}).get("name") or "Staff"
        fresh["staff_permissions"] = (_crole or {}).get("permissions") or []
        fresh["role"] = "company_admin"
    logger.info(f"[PIN admin] login OK for {user.get('email') or user.get('phone')}")
    return {
        "session_token": token,
        "user": fresh,
        "pin_must_change": bool(fresh.get("pin_must_change")),
    }


# ---------------------------------------------------------------------------
# Web-portal password login for admins (super_admin, company_admin).
# ---------------------------------------------------------------------------
class AdminPasswordLoginRequest(BaseModel):
    email: str
    password: str


class AdminSetPasswordRequest(BaseModel):
    current_password: Optional[str] = None  # required unless this is the first-time set / temp swap
    new_password: str


@api.post("/auth/admin-password-login")
async def admin_password_login(payload: AdminPasswordLoginRequest, request: Request):
    """Email OR User ID + password login for App & Web. Only company_admin,
    super_admin and sub_admin can use this — employees stay on the mobile
    PIN flow. Shares the same lockout logic as PIN login (5 attempts →
    15 minute cool-off).
    """
    ident = (payload.email or "").strip()
    pw = payload.password or ""
    if not ident or not pw:
        raise HTTPException(status_code=400, detail="Enter email / User ID and password")

    if "@" in ident:
        user = await db.users.find_one({"email": ident.lower()}, {"_id": 0})
    else:
        # Iter 107 — sub-admins/admins may log in with their MOBILE NUMBER
        # too (same password as the email login). Try phone first, then
        # the username-style login id (case-insensitive).
        user = None
        digits = re.sub(r"[^\d]", "", ident)
        if len(digits) >= 10:
            phone_norm = _normalise_phone(ident)
            user = await db.users.find_one({"phone": phone_norm}, {"_id": 0})
            if not user:
                # tolerate saved formats like "+91 96802 73960" / no +91
                user = await db.users.find_one(
                    {"phone": {"$regex": f"{digits[-10:]}$"},
                     "$or": [
                         {"role": {"$in": ["company_admin", "super_admin", "sub_admin", "company_staff"]}},
                         {"role": "employee", "is_company_staff": True},
                     ]},
                    {"_id": 0},
                )
        if not user:
            # Iter 93 — username-style login id, case-insensitive
            user = await db.users.find_one(
                {"login_id": {"$regex": f"^{re.escape(ident)}$", "$options": "i"}},
                {"_id": 0},
            )
    email = ident  # keep var name for the log lines below
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _is_linked_staff = (
        user.get("role") == "employee" and bool(user.get("is_company_staff"))
    )
    if user.get("role") not in ("company_admin", "super_admin", "sub_admin", "company_staff") \
            and not _is_linked_staff:
        raise HTTPException(status_code=403, detail="This login is only for administrators")
    if not user.get("password_hash"):
        raise HTTPException(
            status_code=403,
            detail="Password login is not set up on this account. Please use the PIN flow on the mobile app or ask the super admin to set a password.",
        )
    # Disabled-account / company guard
    if user.get("role") != "super_admin":
        if user.get("disabled"):
            raise HTTPException(status_code=403, detail="Your account has been disabled. Please contact S.K. Sharma & Co.")
        if user.get("company_id"):
            company = await db.companies.find_one({"company_id": user["company_id"]}, {"_id": 0, "enabled": 1, "name": 1})
            if company and company.get("enabled") is False:
                raise HTTPException(status_code=403, detail=f"Access to '{company.get('name') or 'this company'}' has been temporarily suspended.")

    # Password-specific lockout (mirrors PIN lockout so both credentials are equally hard to brute-force)
    fails = int(user.get("password_fail_count", 0))
    lock_until = user.get("password_locked_until")
    if isinstance(lock_until, str):
        try:
            lock_until = datetime.fromisoformat(lock_until)
        except Exception:
            lock_until = None
    if lock_until and (lock_until.tzinfo is None):
        lock_until = lock_until.replace(tzinfo=timezone.utc)
    if lock_until and lock_until > datetime.now(timezone.utc):
        remaining = int((lock_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
        raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {remaining} minute(s).")

    if not _verify_password(pw, user["password_hash"]):
        fails += 1
        upd: dict = {"password_fail_count": fails, "password_last_fail_at": now_iso()}
        if fails >= 5:
            upd["password_locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            upd["password_fail_count"] = 0
            logger.warning(f"[password admin] LOCKED {email} after 5 failed attempts")
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": upd})
        raise HTTPException(status_code=401, detail="Invalid credentials")

    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "password_fail_count": 0,
            "password_last_login_at": now_iso(),
            "password_locked_until": None,
        }},
    )
    # Iter 569 — 2FA gate for Super/Sub admins: no session until OTP verified.
    if not _is_linked_staff:
        _challenge = await _start_2fa_challenge(user, request, "password")
        if _challenge is not None:
            return _challenge
    token = await _issue_session(
        user["user_id"],
        "staff_portal" if _is_linked_staff else "password",
    )
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    fresh = await _enrich_user_with_company(fresh)
    # RBAC Phase 1 — normalize company_staff in the login response the same
    # way get_user_from_token does, so post-login routing works unchanged.
    if fresh.get("role") == "company_staff" or _is_linked_staff:
        crole = await db.company_roles.find_one(
            {"role_id": fresh.get("company_role_id") or "", "company_id": fresh.get("company_id")},
            {"_id": 0},
        )
        fresh["is_company_staff"] = True
        fresh["staff_role_name"] = (crole or {}).get("name") or "Staff"
        fresh["staff_permissions"] = (crole or {}).get("permissions") or []
        fresh["role"] = "company_admin"
    logger.info(f"[password admin] login OK for {email}")
    return {
        "session_token": token,
        "user": fresh,
        "password_must_change": bool(fresh.get("password_must_change")),
    }


@api.post("/auth/admin-set-password")
async def admin_set_password(
    payload: AdminSetPasswordRequest,
    authorization: Optional[str] = Header(None),
):
    """Authenticated admin sets or changes their own password. On first-time
    set the current password isn't required. On subsequent changes it is."""
    user = await get_user_from_token(authorization)
    if user.get("role") not in ("company_admin", "super_admin", "sub_admin"):
        raise HTTPException(status_code=403, detail="Only administrators can set a password")
    if user.get("password_hash"):
        if not payload.current_password:
            raise HTTPException(status_code=400, detail="Enter your current password to change it")
        if not _verify_password(payload.current_password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Current password is incorrect")
    _validate_password_strength(payload.new_password)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "password_hash": _hash_password(payload.new_password),
            "password_set_at": now_iso(),
            "password_set_by": user["user_id"],
            "password_must_change": False,
            "password_fail_count": 0,
            "password_locked_until": None,
            # Wipe the super-admin-visible plaintext now that the admin has
            # chosen their own password.
            "temp_password_plaintext": None,
        }},
    )
    return {"ok": True}


@api.post("/companies/{company_id}/admin/reset-password")
async def super_admin_reset_company_admin_password(
    company_id: str,
    authorization: Optional[str] = Header(None),
):
    """Super-admin rotates the primary company-admin's web-portal password.
    Returns the new temp password once (like the Reset PIN flow). The admin
    must change it on next successful login."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    target = await db.users.find_one(
        {"company_id": company_id, "role": "company_admin"},
        {"_id": 0, "user_id": 1, "email": 1},
        sort=[("created_at", 1)],
    )
    if not target:
        raise HTTPException(status_code=404, detail="No company admin found for this firm")
    if not target.get("email"):
        raise HTTPException(status_code=400, detail="Set the company admin's email first — password login is by email.")
    temp = _generate_temp_password()
    await db.users.update_one(
        {"user_id": target["user_id"]},
        {"$set": {
            "password_hash": _hash_password(temp),
            "password_set_at": now_iso(),
            "password_reset_by": admin["user_id"],
            "password_must_change": True,
            "password_fail_count": 0,
            "password_locked_until": None,
            "temp_password_plaintext": temp,
            "temp_credentials_generated_at": now_iso(),
        }},
    )
    await db.user_sessions.delete_many({"user_id": target["user_id"]})
    await _write_audit({
        "company_id": company_id,
        "action": "admin.password_reset",
        "actor_user_id": admin["user_id"],
        "actor_email": admin.get("email"),
        "target_user_id": target["user_id"],
    })
    return {
        "ok": True,
        "user_id": target["user_id"],
        "temp_password": temp,
        "email": target.get("email"),
    }


class ForgotPinRequest(BaseModel):
    identifier: str  # email of the admin


@api.post("/auth/forgot-pin")
async def forgot_pin(payload: ForgotPinRequest):
    """Self-service PIN recovery for admins.

    Accepts an email; if it matches a company_admin/super_admin with a
    known email, we generate a fresh 6-digit temp PIN, mark it
    `pin_must_change=true`, and email it to the admin. To avoid enumeration
    the response is always success-shaped even when the account doesn't
    exist. Rate-limited to once every 2 minutes per account.
    """
    ident = (payload.identifier or "").strip().lower()
    if not ident or "@" not in ident:
        raise HTTPException(status_code=400, detail="Enter a valid email address")

    user = await db.users.find_one({"email": ident}, {"_id": 0})
    resp = {"ok": True, "message": "If that email belongs to an administrator, a temporary PIN has been sent."}

    if not user or user.get("role") not in ("company_admin", "super_admin", "sub_admin"):
        # do not leak whether account exists
        return resp

    # Rate-limit: only allow one reset per 2 minutes
    last_reset = user.get("pin_forgot_at")
    if last_reset:
        try:
            when = datetime.fromisoformat(last_reset)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - when < timedelta(minutes=2):
                return resp
        except Exception:
            pass

    temp_pin = _generate_temp_pin()
    while len(set(temp_pin)) == 1 or temp_pin in {"123456", "654321", "000000", "111111"}:
        temp_pin = _generate_temp_pin()

    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "pin_hash": _hash_pin(temp_pin),
            "pin_must_change": True,
            "pin_fail_count": 0,
            "pin_locked_until": None,
            "has_pin": True,
            "pin_forgot_at": now_iso(),
        }},
    )
    # Email the temp PIN using the same Resend infra as OTP
    subject = "Your S.K. Sharma & Co. temporary admin PIN"
    text_body = (
        f"Your new temporary admin PIN is: {temp_pin}\n\n"
        "This PIN is valid until you sign in. On first sign-in you'll be prompted to choose a new personal PIN.\n"
        "If you didn't request this, you can safely ignore this email — the previous PIN has been invalidated for security.\n\n"
        "— S.K. Sharma & Co."
    )
    boxes = "".join(
        f"<span style='display:inline-block;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;"
        f"background:#F7F7F5;border:1px solid #E5E5E0;border-radius:8px;margin:0 4px;"
        f"padding:14px 18px;font-size:28px;font-weight:700;color:#1B3A6E;letter-spacing:2px;'>{d}</span>"
        for d in temp_pin
    )
    html_body = f"""
<!doctype html>
<html>
  <body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#FBFBF9;padding:24px;">
    <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #E5E5E0;">
      <div style="background:#1B3A6E;color:#fff;padding:18px 24px;">
        <div style="font-size:12px;letter-spacing:1.5px;color:#E39A2A;font-weight:700;">S.K. SHARMA &amp; CO.</div>
        <div style="font-size:20px;font-weight:700;margin-top:2px;">Temporary admin PIN</div>
      </div>
      <div style="padding:24px;">
        <p style="margin:0 0 16px 0;color:#333;font-size:14px;line-height:20px;">
          Use the code below to sign in. You&apos;ll be prompted to choose a new
          personal PIN on first login.
        </p>
        <div style="text-align:center;padding:8px 0 16px 0;">{boxes}</div>
        <p style="margin:0;color:#888;font-size:12px;line-height:18px;">
          If you didn&apos;t request this, ignore this email. The previous PIN has been invalidated for security.
        </p>
      </div>
      <div style="background:#F7F7F5;padding:12px 24px;color:#999;font-size:12px;">
        Automated notification from S.K. Sharma &amp; Co.
      </div>
    </div>
  </body>
</html>
"""
    # We reuse _try_send_admin_email but override recipient list
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip()
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as hc:
                r = await hc.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "from": f"S.K. Sharma & Co. <{from_email}>",
                        "to": [user["email"]],
                        "subject": subject,
                        "text": text_body,
                        "html": html_body,
                    },
                )
                if r.status_code < 300:
                    logger.info(f"[forgot-pin] emailed temp PIN to {user['email']}")
                else:
                    logger.warning(f"[forgot-pin] resend {r.status_code} for {user['email']}: {r.text[:200]}")
        except Exception as exc:
            logger.warning(f"[forgot-pin] resend error for {user['email']}: {exc}")
    else:
        logger.warning(f"[forgot-pin] no RESEND_API_KEY; temp PIN for {user['email']} is {temp_pin}")

    return resp

@api.post("/auth/pin-login")
async def pin_login(payload: PinLoginRequest):
    """Employees sign in with EITHER phone + PIN (preferred) OR
    company_code + employee_code + PIN (legacy).
    """
    pin = (payload.pin or "").strip()
    if not pin.isdigit() or len(pin) != 6:
        raise HTTPException(status_code=400, detail="PIN must be 6 digits")

    user = None
    ident_label = ""

    if payload.phone:
        phone_norm = _normalise_phone(payload.phone)
        if not phone_norm or len(phone_norm.lstrip("+")) < 8:
            raise HTTPException(status_code=400, detail="Enter a valid phone number")
        # User directive — the same mobile may belong to BOTH an employer
        # (admin) and an employee record; employee login prefers employee.
        user = (await db.users.find_one({"phone": phone_norm, "role": "employee"}, {"_id": 0})
                or await db.users.find_one({"phone": phone_norm}, {"_id": 0}))
        ident_label = phone_norm
    elif payload.uan_no:
        uan = payload.uan_no.strip()
        if not uan.isdigit() or len(uan) < 10:
            raise HTTPException(status_code=400, detail="Enter a valid UAN")
        user = await db.users.find_one({"uan_no": uan}, {"_id": 0})
        ident_label = f"UAN:{uan[:4]}***"
    elif payload.esi_ip_no:
        ipn = payload.esi_ip_no.strip()
        user = await db.users.find_one({"esi_ip_no": ipn}, {"_id": 0})
        ident_label = f"ESI:{ipn[:4]}***"
    elif payload.pf_no:
        pfn = payload.pf_no.strip()
        user = await db.users.find_one({"pf_no": pfn}, {"_id": 0})
        ident_label = f"PF:{pfn[:6]}***"
    elif payload.login_id:
        # Iter 96l — username set by the employer (case-insensitive)
        lid = payload.login_id.strip()
        user = await db.users.find_one(
            {"login_id": {"$regex": f"^{re.escape(lid)}$", "$options": "i"},
             "role": "employee"},
            {"_id": 0},
        )
        ident_label = f"user:{lid}"
    elif payload.company_code and payload.employee_code:
        cc = payload.company_code.strip().upper()
        ec = payload.employee_code.strip().upper()
        company = await db.companies.find_one({"company_code": cc}, {"_id": 0, "company_id": 1})
        if not company:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        user = await db.users.find_one(
            {"company_id": company["company_id"], "employee_code": ec},
            {"_id": 0},
        )
        ident_label = f"{ec}@{cc}"
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide phone, UAN, ESI IP, PF number, username, or company_code + employee_code — with PIN",
        )

    if not user or not user.get("pin_hash"):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Disabled-account / disabled-company guard
    if user.get("disabled"):
        raise HTTPException(status_code=403, detail="Your account has been disabled. Please contact your admin.")
    if user.get("company_id"):
        company = await db.companies.find_one({"company_id": user["company_id"]}, {"_id": 0, "enabled": 1, "name": 1})
        if company and company.get("enabled") is False:
            raise HTTPException(status_code=403, detail=f"Access to '{company.get('name') or 'this company'}' has been temporarily suspended.")

    # Lockout after too many recent failures
    fails = int(user.get("pin_fail_count", 0))
    lock_until = user.get("pin_locked_until")
    if isinstance(lock_until, str):
        try:
            lock_until = datetime.fromisoformat(lock_until)
        except Exception:
            lock_until = None
    if lock_until and (lock_until.tzinfo is None):
        lock_until = lock_until.replace(tzinfo=timezone.utc)
    if lock_until and lock_until > datetime.now(timezone.utc):
        remaining = int((lock_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
        raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {remaining} minute(s).")

    if not _verify_pin(pin, user["pin_hash"]):
        fails += 1
        upd: dict = {"pin_fail_count": fails, "pin_last_fail_at": now_iso()}
        if fails >= 5:
            upd["pin_locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            upd["pin_fail_count"] = 0
            logger.warning(f"[PIN] LOCKED {ident_label} after 5 failed attempts")
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": upd})
        logger.info(f"[PIN] wrong PIN for {ident_label} (fails={fails})")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.get("exit_date"):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if str(user["exit_date"]) <= today:
            raise HTTPException(status_code=403, detail="This account is no longer active. Contact your admin.")

    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"pin_fail_count": 0, "pin_last_login_at": now_iso(), "pin_locked_until": None}},
    )

    # Iter 285 — onboarding approval gate (pending/hold/rejected staff).
    await _onboarding_login_gate(user)

    token = await _issue_session(user["user_id"], "pin")
    await _maybe_first_login_punch(user)
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    fresh = await _enrich_user_with_company(fresh)
    logger.info(f"[PIN] login OK for {ident_label}")
    return {
        "session_token": token,
        "user": fresh,
        "pin_must_change": bool(fresh.get("pin_must_change")),
    }


@api.post("/auth/employee-signup")
async def employee_signup(payload: EmployeeSignupRequest):
    """One-shot employee self-registration:
    - phone (unique)
    - initial PIN (user picks; pin_must_change=false — the PIN they chose
      at signup is kept, so they can sign in immediately after approval)
    - company_code (must match an existing company)
    - basic profile details

    The account is created with approval_status='pending' — a company admin
    must approve before the employee can access the app.
    """
    phone = _normalise_phone(payload.phone)
    if not phone or len(phone.lstrip("+")) < 8:
        raise HTTPException(status_code=400, detail="Enter a valid phone number")
    pin = (payload.pin or "").strip()
    _validate_pin_format(pin)
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Full name is required")
    cc = (payload.company_code or "").strip().upper()
    if not cc:
        raise HTTPException(status_code=400, detail="Company code is required")

    company = await db.companies.find_one({"company_code": cc}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Company code not recognised. Please double-check with your admin.")

    # Duplicate phone → conflict, guide them to login instead
    existing = await db.users.find_one(
        {"phone": phone},
        {"_id": 0, "user_id": 1, "role": 1, "approval_status": 1})
    if existing:
        # Iter 617 (user bug) — a REJECTED signup must not block the mobile
        # number forever: purge the stale rejected account (and sessions)
        # so the employee can register afresh.
        if (existing.get("approval_status") == "rejected"
                and existing.get("role") in ("employee", None, "")):
            await db.users.delete_one({"user_id": existing["user_id"]})
            await db.user_sessions.delete_many({"user_id": existing["user_id"]})
            logger.info(
                "[employee-signup] purged rejected account %s so phone %s "
                "can re-register", existing.get("user_id"), phone)
        else:
            raise HTTPException(
                status_code=409,
                detail="An account with this phone number already exists. Please sign in instead.",
            )

    # Email optional; if provided, ensure not already taken by a different account
    email = (payload.email or "").strip().lower() or None
    if email:
        e_existing = await db.users.find_one({"email": email}, {"_id": 0})
        if e_existing:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user_doc = {
        "user_id": f"user_{uuid.uuid4().hex[:12]}",
        "email": email,
        "phone": phone,
        "name": name,
        "picture": None,
        "role": "employee",
        "company_id": company["company_id"],
        "department": None,
        "position": None,
        "employee_code": None,  # will be pre-assigned below if possible
        # Iter 85 — Employee's own proposed code, captured on the mobile
        # signup form. Admin reviews this on approval and can override
        # it. Kept separate from ``employee_code`` (which is the final,
        # collision-resolved code assigned by the system).
        "proposed_employee_code": (payload.employee_code or "").strip().upper() or None,
        "father_name": payload.father_name,
        "dob": payload.dob,
        "doj": payload.doj,
        "shift_start": payload.shift_start,
        "shift_end": payload.shift_end,
        "salary_monthly": payload.salary_monthly,
        "half_day_hrs": payload.half_day_hrs,
        "full_day_hrs": payload.full_day_hrs,
        "address": (payload.address or "").strip() or None,
        "onboarded": True,
        "onboarded_at": now_iso(),
        "approval_status": "pending",
        "approval_requested_at": now_iso(),
        "has_pin": True,
        "pin_hash": _hash_pin(pin),
        # Employee chose their own PIN — no forced change on first login.
        "pin_must_change": False,
        "pin_set_at": now_iso(),
        "created_at": now_iso(),
    }
    # Iter 85 — If the employee typed their own Employee Code on the
    # signup form we prefer that (uppercased) over the auto-assigned one
    # so their offer-letter code carries through to the admin approval
    # step. Admin can still override during approval.
    proposed = user_doc.get("proposed_employee_code")
    if proposed:
        user_doc["employee_code"] = proposed
    else:
        # Pre-assign a sequential employee_code (COMPANY_CODE + 4-digit)
        # so it's visible to the admin during approval and to the user
        # on first login.
        try:
            new_code = await _next_employee_code(company["company_id"])
            if new_code:
                user_doc["employee_code"] = new_code
        except Exception:
            # non-fatal — admin will still be able to assign one on approval
            pass
    await db.users.insert_one(user_doc)
    logger.info(f"[SIGNUP] employee phone={phone} company={cc} pending approval")
    return {
        "ok": True,
        "message": "Account created. Waiting for company admin to approve your account.",
        "user_id": user_doc["user_id"],
        "phone": phone,
        "company_name": company.get("name"),
    }




@api.post("/auth/pin-change")
async def pin_change(payload: PinChangeRequest, authorization: Optional[str] = Header(None)):
    """Authenticated user changes their own PIN."""
    user = await get_user_from_token(authorization)
    if not user.get("pin_hash"):
        raise HTTPException(status_code=400, detail="No PIN set on this account")
    if not _verify_pin(payload.current_pin, user["pin_hash"]):
        raise HTTPException(status_code=401, detail="Current PIN is incorrect")
    if (payload.current_pin or "").strip() == (payload.new_pin or "").strip():
        raise HTTPException(status_code=400, detail="New PIN must be different from current PIN")
    _validate_pin_format(payload.new_pin)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "pin_hash": _hash_pin(payload.new_pin.strip()),
            "pin_must_change": False,
            "pin_last_changed_at": now_iso(),
            "pin_fail_count": 0,
            "pin_locked_until": None,
            # Wipe the temp PIN plaintext now that the admin has picked their own
            "temp_pin_plaintext": None,
        }},
    )
    logger.info(f"[PIN] {user.get('employee_code')} changed their PIN")
    return {"ok": True}


@api.patch("/admin/employee-pin")
async def admin_reset_pin(payload: AdminPinResetRequest, authorization: Optional[str] = Header(None)):
    """Company/Super admin resets an employee's PIN. Returns the temp PIN once."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    target = await db.users.find_one({"user_id": payload.user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")

    if admin["role"] == "company_admin":
        if not admin.get("company_id") or target.get("company_id") != admin["company_id"]:
            raise HTTPException(status_code=403, detail="Not allowed to reset PINs outside your company")

    if payload.new_pin:
        _validate_pin_format(payload.new_pin)
        temp_pin = payload.new_pin.strip()
    else:
        temp_pin = _generate_temp_pin()
        while len(set(temp_pin)) == 1 or temp_pin in {"123456", "654321", "000000", "111111"}:
            temp_pin = _generate_temp_pin()

    await db.users.update_one(
        {"user_id": payload.user_id},
        {"$set": {
            "pin_hash": _hash_pin(temp_pin),
            "pin_must_change": True,
            "pin_set_at": now_iso(),
            "pin_reset_by": admin["user_id"],
            "pin_fail_count": 0,
            "pin_locked_until": None,
            "has_pin": True,
        }},
    )
    logger.info(f"[PIN] admin {admin.get('email')} reset PIN for user_id={payload.user_id}")
    return {"ok": True, "temp_pin": temp_pin, "user_id": payload.user_id}


# ---------------------------------------------------------------------------
# Iter 96l — Employer-managed employee login credentials.
# A company/super/sub admin can set a username (login_id) + PIN + password
# for an employee, who then logs in on the Employee login screen using
# username + PIN or username + password.
# ---------------------------------------------------------------------------
class EmployeeCredentialRequest(BaseModel):
    user_id: str
    login_id: Optional[str] = None       # username
    pin: Optional[str] = None            # 6-digit PIN
    password: Optional[str] = None       # min 8 chars, letter + digit
    must_change: bool = False            # force change at first login


@api.post("/admin/employee-credentials")
async def admin_set_employee_credentials(
    payload: EmployeeCredentialRequest,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    target = await db.users.find_one({"user_id": payload.user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    if (target.get("role") or "employee") != "employee":
        raise HTTPException(status_code=400, detail="Credentials can only be set for employees")
    if admin["role"] == "company_admin":
        if not admin.get("company_id") or target.get("company_id") != admin["company_id"]:
            raise HTTPException(status_code=403, detail="Not allowed to manage employees outside your company")
    if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, target.get("company_id")):
        raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")

    if not (payload.login_id or payload.pin or payload.password):
        raise HTTPException(status_code=400, detail="Provide a username, PIN and/or password to set")

    updates: Dict[str, Any] = {}

    if payload.login_id is not None:
        lid = payload.login_id.strip()
        if lid:
            if len(lid) < 3 or " " in lid:
                raise HTTPException(status_code=400, detail="Username must be at least 3 characters with no spaces")
            # Globally unique (login_id is also used for admin username login).
            clash = await db.users.find_one(
                {"login_id": {"$regex": f"^{re.escape(lid)}$", "$options": "i"},
                 "user_id": {"$ne": payload.user_id}},
                {"_id": 0, "user_id": 1},
            )
            if clash:
                raise HTTPException(status_code=409, detail="That username is already taken")
            updates["login_id"] = lid
        else:
            updates["login_id"] = None  # allow clearing

    if payload.pin:
        _validate_pin_format(payload.pin)
        updates.update({
            "pin_hash": _hash_pin(payload.pin.strip()),
            "has_pin": True,
            "pin_must_change": bool(payload.must_change),
            "pin_set_at": now_iso(),
            "pin_reset_by": admin["user_id"],
            "pin_fail_count": 0,
            "pin_locked_until": None,
        })

    if payload.password:
        _validate_password_strength(payload.password)
        updates.update({
            "password_hash": _hash_password(payload.password),
            "password_must_change": bool(payload.must_change),
            "password_set_at": now_iso(),
            "password_set_by": admin["user_id"],
            "password_fail_count": 0,
            "password_locked_until": None,
        })

    await db.users.update_one({"user_id": payload.user_id}, {"$set": updates})
    logger.info(
        "[creds] admin %s set employee credentials for %s (username=%s, pin=%s, password=%s)",
        admin.get("email"), payload.user_id,
        bool(payload.login_id), bool(payload.pin), bool(payload.password),
    )
    return {
        "ok": True,
        "user_id": payload.user_id,
        "login_id": updates.get("login_id", target.get("login_id")),
        "has_pin": bool(updates.get("has_pin", target.get("has_pin"))),
        "has_password": bool(updates.get("password_hash") or target.get("password_hash")),
    }


class EmployeePasswordLoginRequest(BaseModel):
    login_id: str
    password: str


@api.post("/auth/employee-password-login")
async def employee_password_login(payload: EmployeePasswordLoginRequest):
    """Employee logs in with the username + password their employer set."""
    lid = (payload.login_id or "").strip()
    pw = payload.password or ""
    if not lid or not pw:
        raise HTTPException(status_code=400, detail="Enter your username and password")

    user = await db.users.find_one(
        {"login_id": {"$regex": f"^{re.escape(lid)}$", "$options": "i"},
         "role": "employee"},
        {"_id": 0},
    )
    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.get("disabled"):
        raise HTTPException(status_code=403, detail="Your account has been disabled. Please contact your admin.")
    if user.get("company_id"):
        company = await db.companies.find_one({"company_id": user["company_id"]}, {"_id": 0, "enabled": 1, "name": 1})
        if company and company.get("enabled") is False:
            raise HTTPException(status_code=403, detail=f"Access to '{company.get('name') or 'this company'}' has been temporarily suspended.")

    fails = int(user.get("password_fail_count", 0))
    lock_until = user.get("password_locked_until")
    if isinstance(lock_until, str):
        try:
            lock_until = datetime.fromisoformat(lock_until)
        except Exception:
            lock_until = None
    if lock_until and (lock_until.tzinfo is None):
        lock_until = lock_until.replace(tzinfo=timezone.utc)
    if lock_until and lock_until > datetime.now(timezone.utc):
        remaining = int((lock_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
        raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {remaining} minute(s).")

    if not _verify_password(pw, user["password_hash"]):
        fails += 1
        upd: dict = {"password_fail_count": fails, "password_last_fail_at": now_iso()}
        if fails >= 5:
            upd["password_locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            upd["password_fail_count"] = 0
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": upd})
        raise HTTPException(status_code=401, detail="Invalid credentials")

    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"password_fail_count": 0, "password_last_login_at": now_iso(), "password_locked_until": None}},
    )
    token = await _issue_session(user["user_id"], "password")
    await _maybe_first_login_punch(user)
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    fresh = await _enrich_user_with_company(fresh)
    logger.info(f"[emp-password] login OK for user:{lid}")
    return {
        "session_token": token,
        "user": fresh,
        "password_must_change": bool(fresh.get("password_must_change")),
    }


@api.post("/auth/staff-portal-switch")
async def staff_portal_switch(authorization: Optional[str] = Header(None)):
    """Employee PWA → Staff portal in one tap. An employee who has been
    linked as a staff user (Roles & Permissions) exchanges their employee
    session for a staff-portal session — normalized to a firm-scoped
    company_admin with their role's permission subset. Their employee
    session token stays valid on the device so they can switch back."""
    user = await get_user_from_token(authorization)
    raw = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not (raw and raw.get("role") == "employee" and raw.get("is_company_staff")):
        raise HTTPException(status_code=403, detail="Your account has no staff access")
    token = await _issue_session(raw["user_id"], "staff_portal_switch")
    fresh = await _enrich_user_with_company(raw)
    crole = await db.company_roles.find_one(
        {"role_id": raw.get("company_role_id") or "", "company_id": raw.get("company_id")},
        {"_id": 0},
    )
    fresh["is_company_staff"] = True
    fresh["staff_role_name"] = (crole or {}).get("name") or "Staff"
    fresh["staff_permissions"] = (crole or {}).get("permissions") or []
    fresh["role"] = "company_admin"
    logger.info(f"[staff-portal-switch] {raw.get('employee_code') or raw['user_id']} switched to staff portal")
    return {"session_token": token, "user": fresh}


# ---------------------------------------------------------------------------
# Onboarding (Employee self-linking with company code)
# ---------------------------------------------------------------------------
@api.get("/companies/by-code/{code}")
async def find_company_by_code(code: str,
                               authorization: Optional[str] = Header(None)):
    """Preview company details from a code entered during onboarding."""
    await get_user_from_token(authorization)
    company = await db.companies.find_one(
        {"company_code": code.strip().upper()},
        {"_id": 0, "office_lat": 0, "office_lng": 0, "geofence_radius_m": 0},
    )
    if not company:
        raise HTTPException(status_code=404, detail="No company found for this code")
    return company


@api.get("/companies/lookup/{code}")
async def lookup_company_by_code(code: str):
    """PUBLIC company lookup used during employee self-signup (before auth).
    Returns minimal identifying info only.
    """
    company = await db.companies.find_one(
        {"company_code": code.strip().upper()},
        {"_id": 0, "company_id": 1, "name": 1, "company_code": 1},
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company code not recognised. Please double-check with your admin.")
    return company


@api.get("/business-categories")
async def list_business_categories():
    """PUBLIC — returns the Firm Master business-type taxonomy used by the
    Create Company and employer self-registration dropdowns. Available
    without auth so it can be loaded on the sign-up screen."""
    return {"categories": BUSINESS_CATEGORIES}


@api.get("/prospectus.pdf")
async def download_prospectus(fresh: bool = Query(False)):
    """PUBLIC — returns the ready-to-share consultancy prospectus PDF.
    Pass ?fresh=true to regenerate the PDF from source (useful after content
    edits) — otherwise the pre-generated artefact is streamed straight from
    disk. Suitable for sharing over WhatsApp / email as a signed link.
    """
    from fastapi.responses import FileResponse
    from utils.prospectus import (
        DEFAULT_OUTPUT as PROSPECTUS_PATH,
        generate_prospectus,
    )
    if fresh or not PROSPECTUS_PATH.exists():
        generate_prospectus()
    return FileResponse(
        str(PROSPECTUS_PATH),
        media_type="application/pdf",
        filename="SKS_Consultancy_Prospectus.pdf",
    )


# ---------------------------------------------------------------------------
# Attendance Policy (per company, tuned to business type)
# ---------------------------------------------------------------------------
_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


async def _get_own_company(user: dict) -> dict:
    """Resolves the company the given user administers. Super admins must
    pass `?company_id=` on the query string (validated in the endpoint)."""
    if not user.get("company_id"):
        raise HTTPException(status_code=400, detail="You are not linked to any company")
    company = await db.companies.find_one({"company_id": user["company_id"]}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


# ---------------------------------------------------------------------------
# Iter 76 — Global Shift Master (shared across every firm)
# ---------------------------------------------------------------------------
# The operator asked for a single catalogue of shifts (Day 7-7, Night 8-8,
# General 9-5, etc.) that every firm's Attendance Policy and every
# employee's per-person shift override can pick from. This keeps the
# vocabulary consistent across the 236+ employees / 2 firms without
# forcing us to duplicate the shift dicts on every company doc.


class ShiftMasterIn(BaseModel):
    name: str
    start: str  # HH:MM
    end: str    # HH:MM
    description: Optional[str] = None




def _format_company_request_email_html(req: dict) -> str:
    """HTML rendering of a new company registration request."""
    def esc(v):
        s = "" if v is None else str(v)
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    rows = [
        ("Contact person", req.get("contact_name")),
        ("Mobile", req.get("contact_mobile")),
        ("Email", req.get("contact_email") or "-"),
        ("Submitted by (app user)", req.get("submitted_by_email") or "-"),
        ("Company name", req.get("company_name")),
        ("Address", req.get("address") or "-"),
        ("Employees", req.get("employee_count") or "-"),
        ("Services needed", req.get("services_needed") or "-"),
        ("Notes", req.get("notes") or "-"),
        ("Submitted at", req.get("created_at")),
    ]
    table_rows = "".join(
        f"<tr>"
        f"<td style='padding:6px 12px;color:#666;font-size:13px;background:#F7F7F5;'>{esc(k)}</td>"
        f"<td style='padding:6px 12px;color:#1B3A6E;font-size:14px;font-weight:600;'>{esc(v)}</td>"
        f"</tr>"
        for k, v in rows
    )
    return f"""
<!doctype html>
<html>
  <body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#FBFBF9;padding:24px;">
    <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #E5E5E0;">
      <div style="background:#1B3A6E;color:#fff;padding:18px 24px;">
        <div style="font-size:12px;letter-spacing:1.5px;color:#E39A2A;font-weight:700;">S.K. SHARMA &amp; CO.</div>
        <div style="font-size:20px;font-weight:700;margin-top:2px;">New company registration request</div>
      </div>
      <div style="padding:20px 24px;">
        <p style="margin:0 0 12px 0;color:#333;font-size:14px;line-height:20px;">
          A prospective client has just submitted a company registration request via the mobile app.
          Reply to their contact within 24 hours to schedule an onboarding call.
        </p>
        <table style="width:100%;border-collapse:collapse;margin-top:12px;">
          {table_rows}
        </table>
      </div>
      <div style="background:#F7F7F5;padding:12px 24px;color:#999;font-size:12px;">
        This is an automated notification from the S.K. Sharma & Co. app.
      </div>
    </div>
  </body>
</html>
"""


def _format_company_request_email(req: dict) -> str:
    lines = [
        "New company registration request received in S.K. Sharma & Co. app",
        "",
        f"Contact person : {req.get('contact_name')}",
        f"Mobile         : {req.get('contact_mobile')}",
        f"Email          : {req.get('contact_email') or '-'}",
        f"Submitted by   : {req.get('submitted_by_email') or '-'}",
        "",
        f"Company name   : {req.get('company_name')}",
        f"Address        : {req.get('address') or '-'}",
        f"Employees      : {req.get('employee_count') or '-'}",
        f"Services       : {req.get('services_needed') or '-'}",
        f"Notes          : {req.get('notes') or '-'}",
        "",
        f"Submitted at   : {req.get('created_at')}",
        "",
        "Reply to this contact within 24 hours to schedule an onboarding call.",
    ]
    return "\n".join(lines)


async def _try_send_admin_email(subject: str, text_body: str, html_body: Optional[str] = None) -> dict:
    """Send an admin notification email using Resend.

    Returns a dict with keys: `delivered` (bool), `provider` (str),
    `email_id` (Optional[str]), `error` (Optional[str]).

    Failures are swallowed and logged so that the caller's request never
    fails because of an email hiccup.
    """
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip()
    to_env = os.getenv("RESEND_TO_EMAIL", "").strip()
    to_list = [e.strip() for e in to_env.split(",") if e.strip()] if to_env else list(SUPER_ADMIN_EMAILS)

    result: dict = {"delivered": False, "provider": "resend", "email_id": None, "error": None}

    if not api_key or not to_list:
        logger.info(f"[MAIL fallback / no-key] to={to_list} subject={subject!r}\n{text_body}")
        result["error"] = "missing_api_key_or_recipients"
        return result

    payload = {
        "from": f"S.K. Sharma & Co. <{from_email}>",
        "to": to_list,
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        payload["html"] = html_body

    try:
        async with httpx.AsyncClient(timeout=10.0) as hc:
            r = await hc.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if r.status_code < 300:
            data = {}
            try:
                data = r.json()
            except Exception:
                pass
            result["delivered"] = True
            result["email_id"] = data.get("id")
            logger.info(f"[Resend OK] id={data.get('id')} to={to_list} subject={subject!r}")
        else:
            snippet = r.text[:300] if r.text else ""
            logger.warning(f"[Resend FAIL {r.status_code}] to={to_list} subject={subject!r} body={snippet}")
            result["error"] = f"http_{r.status_code}: {snippet}"
    except httpx.RequestError as exc:
        logger.warning(f"[Resend network error] {exc}")
        result["error"] = f"network: {exc}"
    except Exception as exc:  # noqa: BLE001 — best-effort send
        logger.warning(f"[Resend unexpected error] {exc}")
        result["error"] = f"unexpected: {exc}"

    return result


@api.post("/company-requests")
async def create_company_request(payload: CompanyRequestSubmit,
                                 authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    if user.get("role") == "super_admin":
        raise HTTPException(status_code=400, detail="Super admins add companies directly, not via requests")
    req = payload.model_dump()
    # Normalise the Firm Master category if the client sent one
    if req.get("business_category") or req.get("business_subcategory"):
        bcat, bsub = _validate_business_category(
            req.get("business_category"), req.get("business_subcategory")
        )
        req["business_category"] = bcat
        req["business_subcategory"] = bsub
    req["request_id"] = f"cr_{uuid.uuid4().hex[:10]}"
    req["submitted_by_user_id"] = user["user_id"]
    req["submitted_by_email"] = user.get("email")
    req["status"] = "pending"
    req["created_at"] = now_iso()
    await db.company_requests.insert_one(req)

    subject = f"New company request: {payload.company_name}"
    body = _format_company_request_email(req)
    html_body = _format_company_request_email_html(req)
    mail = await _try_send_admin_email(subject, body, html_body)
    # Persist delivery outcome for auditability
    try:
        await db.company_requests.update_one(
            {"request_id": req["request_id"]},
            {"$set": {
                "email_delivered": mail.get("delivered", False),
                "email_provider": mail.get("provider"),
                "email_id": mail.get("email_id"),
                "email_error": mail.get("error"),
            }},
        )
    except Exception:
        pass
    return {
        "ok": True,
        "request_id": req["request_id"],
        "email_delivered": bool(mail.get("delivered")),
        "email_id": mail.get("email_id"),
        "admin_emails": list(SUPER_ADMIN_EMAILS),
    }


@api.get("/company-requests")
async def list_company_requests(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin"])
    items = await db.company_requests.find({}, {"_id": 0, "admin_pin_hash": 0}).sort("created_at", -1).to_list(500)
    return {"requests": items}


@api.post("/auth/company-register")
async def company_self_register(payload: CompanySelfRegister):
    """Public endpoint — an employer self-registers a new company + the
    admin's initial login credentials. The submission is queued as a
    pending company_request. On super_admin approval the actual Company
    and company_admin user are provisioned in one shot.
    """
    _validate_pin_format(payload.pin)
    phone = _normalise_phone(payload.contact_mobile)
    if not phone or len(phone.lstrip("+")) < 8:
        raise HTTPException(status_code=400, detail="Enter a valid mobile number")
    # Business category dropdown (Firm Master). If provided, derive the
    # `nature_of_business` text from the taxonomy so the legacy field stays
    # populated and readable in admin emails / lists.
    bcat, bsub = _validate_business_category(
        payload.business_category, payload.business_subcategory
    )
    nature_of_business = (payload.nature_of_business or "").strip()
    if bcat:
        # Overwrite the free-text with the canonical label like
        # "Industry — Textile" so downstream reads are consistent.
        nature_of_business = _business_category_label(bcat, bsub)
    for label, val in (
        ("Firm name", payload.company_name),
        ("Address", payload.address),
        ("City", payload.city),
        ("State", payload.state),
        ("Owner name", payload.contact_name),
        ("Nature of business", nature_of_business),
    ):
        if not (val or "").strip():
            raise HTTPException(status_code=400, detail=f"{label} is required")
    email = (payload.contact_email or "").strip().lower()
    if not email or "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address")

    # Duplicate phone → auto-heal orphans (Iter 77v, expanded Iter 77z).
    # If the phone is linked to a user whose company_id points to a deleted
    # firm — OR whose account has no company_id at all — remove the stale
    # user + sessions so the phone can be reused. We also handle the case
    # where the same phone is stored with a different normalisation prefix
    # (e.g. bare 10-digit "9876543210" vs the normalised "+919876543210").
    # Super_admin accounts are ALWAYS preserved.
    phone_variants = {phone}
    bare = phone.lstrip("+")
    phone_variants.add(bare)
    if bare.startswith("91") and len(bare) == 12:
        phone_variants.add(bare[2:])  # 10-digit form
    if len(bare) == 10:
        phone_variants.add(f"91{bare}")
        phone_variants.add(f"+91{bare}")

    existing_users = await db.users.find(
        {"phone": {"$in": list(phone_variants)}},
        {"_id": 0, "role": 1, "company_id": 1, "user_id": 1, "phone": 1, "email": 1},
    ).to_list(20)
    # ── Guard: never touch a super_admin. If the phone belongs to a
    # super_admin, guide them to use the admin panel to create the firm
    # (self-register is not the right path — they already have access).
    for existing_user in existing_users:
        if existing_user.get("role") == "super_admin":
            raise HTTPException(
                status_code=409,
                detail=(
                    "This mobile number is already linked to a Super Admin "
                    "account. Please sign in as Super Admin and use "
                    "'Create Company' from the admin panel to register a "
                    "new firm."
                ),
            )
    for existing_user in existing_users:
        _live_firm_self = None
        if existing_user.get("company_id"):
            _live_firm_self = await db.companies.find_one(
                {"company_id": existing_user.get("company_id")},
                {"_id": 0, "company_id": 1},
            )
        role_ = existing_user.get("role")
        # Auto-heal criteria (any of):
        #   • Linked firm no longer exists (force-deleted / rejected)
        #   • User has no linked firm at all (garbage / half-registered)
        #   • Role is not super_admin (i.e. safe to purge)
        if not _live_firm_self or role_ in ("company_admin", "sub_admin", "employee", None, ""):
            await db.users.delete_one({"user_id": existing_user.get("user_id")})
            await db.user_sessions.delete_many(
                {"user_id": existing_user.get("user_id")},
            )
            logger.info(
                "[self-register] auto-healed orphan user_id=%s phone=%s role=%s "
                "(was linked to firm=%s live=%s)",
                existing_user.get("user_id"), existing_user.get("phone"),
                role_, existing_user.get("company_id"), bool(_live_firm_self),
            )
        else:
            raise HTTPException(
                status_code=409,
                detail="An account with this mobile number already exists. Please sign in instead.",
            )
    # Also drop orphaned company_requests whose company has been deleted /
    # rejected long ago (best-effort auto-heal). We purge ALL non-pending
    # statuses so a fresh submission can go through cleanly.
    await db.company_requests.delete_many({
        "contact_mobile": {"$in": list(phone_variants)},
        "status": {"$nin": ["pending"]},
    })
    existing_req = await db.company_requests.find_one(
        {"contact_mobile": {"$in": list(phone_variants)}, "status": "pending"},
        {"_id": 0},
    )
    if existing_req:
        raise HTTPException(
            status_code=409,
            detail="A pending request with this mobile number is already awaiting approval.",
        )

    # Iter 93 — Duplicate EMAIL guard (same semantics as the phone guard
    # above). Previously a duplicate email sailed through registration and
    # exploded at approval time (DuplicateKeyError on users.email_1) —
    # leaving the request marked "approved" with NO firm provisioned.
    email_user = await db.users.find_one(
        {"email": email},
        {"_id": 0, "user_id": 1, "role": 1, "company_id": 1},
    )
    if email_user:
        if email_user.get("role") == "super_admin":
            raise HTTPException(
                status_code=409,
                detail=(
                    "This email belongs to a Super Admin account. Please sign "
                    "in as Super Admin and use 'Create Company' instead."
                ),
            )
        _live_firm_email = None
        if email_user.get("company_id"):
            _live_firm_email = await db.companies.find_one(
                {"company_id": email_user["company_id"]},
                {"_id": 0, "company_id": 1, "name": 1},
            )
        if _live_firm_email:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This email is already registered with "
                    f"'{_live_firm_email.get('name') or 'another firm'}'. "
                    "Please sign in instead, or use a different email for the new firm."
                ),
            )
        # Orphan (firm deleted / never linked) → auto-heal like the phone flow.
        await db.users.delete_one({"user_id": email_user["user_id"]})
        await db.user_sessions.delete_many({"user_id": email_user["user_id"]})
        logger.info(
            "[self-register] auto-healed orphan email user_id=%s email=%s",
            email_user["user_id"], email,
        )
    # Duplicate email on another PENDING request → block early too.
    email_req = await db.company_requests.find_one(
        {"contact_email": email, "status": "pending"},
        {"_id": 0, "request_id": 1},
    )
    if email_req:
        raise HTTPException(
            status_code=409,
            detail="A pending request with this email is already awaiting approval.",
        )

    req = {
        "request_id": f"req_{uuid.uuid4().hex[:12]}",
        "kind": "self_register",
        "contact_name": payload.contact_name.strip(),
        "contact_mobile": phone,
        "contact_email": email,
        "company_name": payload.company_name.strip(),
        "address": payload.address.strip(),
        "city": payload.city.strip(),
        "state": payload.state.strip(),
        "nature_of_business": nature_of_business,
        "business_category": bcat,
        "business_subcategory": bsub,
        "office_lat": payload.office_lat,
        "office_lng": payload.office_lng,
        "geofence_radius_m": payload.geofence_radius_m or 200,
        "employee_count": payload.employee_count,
        "notes": (payload.notes or "").strip() or None,
        "admin_pin_hash": _hash_pin(payload.pin),
        "status": "pending",
        # Iter 89 — Preserve the logo captured during self-registration.
        "logo_base64": payload.logo_base64,
        "logo_mime": payload.logo_mime,
        "created_at": now_iso(),
    }
    await db.company_requests.insert_one(req)
    logger.info(f"[COMPANY REG] pending: {req['company_name']} contact={phone}")

    # Notify super admin via email (best effort)
    try:
        subject = f"New company registration: {req['company_name']}"
        body = (
            f"A new employer has requested to register their company on the app.\n\n"
            f"Company: {req['company_name']}\n"
            f"Contact: {req['contact_name']} ({phone})\n"
            f"Email: {req['contact_email'] or '-'}\n"
            f"Address: {req['address']}\n\n"
            f"Approve or reject from the Admin panel."
        )
        await _try_send_admin_email(subject, body)
    except Exception:
        pass

    return {
        "ok": True,
        "request_id": req["request_id"],
        "message": "Registration submitted. A super admin will review your request shortly.",
    }


@api.patch("/company-requests/{request_id}")
async def decide_company_request(
    request_id: str,
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin"])
    status = payload.get("status")
    if status not in ("approved", "rejected", "pending"):
        raise HTTPException(status_code=400, detail="Invalid status")

    req = await db.company_requests.find_one({"request_id": request_id})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    result: dict = {}

    # Iter 86 - Idempotency guard: if this request was ALREADY approved
    # (and provisioned) or already rejected, a duplicate click from the
    # admin must NOT create another firm.  We simply return the earlier
    # result payload with the same status code so the UI still refreshes
    # correctly, without touching the database.  This fixes the bug
    # where rapidly tapping "Approve" created multiple copies of the
    # same firm.
    if req.get("status") == status and req.get("status") in ("approved", "rejected"):
        return {
            **{k: v for k, v in req.items() if k != "_id" and k != "admin_pin_hash"},
            "company_id": req.get("result_company_id"),
            "company_code": req.get("result_company_code"),
            "admin_user_id": req.get("result_admin_user_id"),
            "already_decided": True,
        }
    # Also guard the specific "approve when already approved" flow when
    # the earlier decision produced a company_id.  This handles the case
    # where the client is reissuing an approve on a partially-completed
    # doc (rare, but a belt-and-braces safety net).
    if status == "approved" and req.get("result_company_id"):
        return {
            **{k: v for k, v in req.items() if k != "_id" and k != "admin_pin_hash"},
            "company_id": req.get("result_company_id"),
            "company_code": req.get("result_company_code"),
            "admin_user_id": req.get("result_admin_user_id"),
            "already_decided": True,
        }

    # If approving a self_register request, provision Company + company_admin
    if status == "approved" and req.get("kind") == "self_register":
        # Iter 88 — Atomic CAS reservation to defeat the double-tap race.
        # Two concurrent PATCH calls (mobile double-tap / slow-network
        # retry) previously both saw status='pending', both bypassed the
        # Iter-86 idempotency guard above, both entered provisioning, and
        # the loser crashed on ``users.email_1`` DuplicateKeyError → the
        # bare ``HTTP 500`` the user saw in the app.
        #
        # We now atomically flip status pending → provisioning; whoever
        # loses the CAS waits briefly for the winner to finish, then
        # returns the same idempotent payload as the guard above.
        cas = await db.company_requests.update_one(
            {"request_id": request_id, "status": "pending"},
            {"$set": {"status": "provisioning",
                      "provisioning_started_at": now_iso(),
                      "provisioning_by": user["user_id"]}},
        )
        if cas.matched_count == 0:
            # Someone else already reserved / finished. Poll briefly for
            # the terminal state, then return the idempotent payload.
            for _ in range(25):  # up to ~5s
                snap = await db.company_requests.find_one(
                    {"request_id": request_id},
                    {"_id": 0, "admin_pin_hash": 0},
                )
                if snap and snap.get("status") in ("approved", "rejected"):
                    return {
                        **snap,
                        "company_id": snap.get("result_company_id"),
                        "company_code": snap.get("result_company_code"),
                        "admin_user_id": snap.get("result_admin_user_id"),
                        "already_decided": True,
                    }
                await asyncio.sleep(0.2)
            # Timed out — winner is still working. Return current snapshot
            # so the UI can retry safely; do NOT raise 500.
            snap = await db.company_requests.find_one(
                {"request_id": request_id},
                {"_id": 0, "admin_pin_hash": 0},
            ) or {}
            return {**snap, "already_decided": True,
                    "provisioning_in_progress": True}
        # Iter 77z-fix — Robust orphan handling at APPROVAL time. Same
        # semantics as ``company_self_register``:
        #   • super_admin phone → refuse approval with a clear message
        #   • orphan company_admin/employee (no live firm) → auto-purge
        #   • live-firm company_admin → auto-reject the request so it
        #     doesn't linger in the pending queue forever.
        # Iter 86 - Guard against missing/None `contact_mobile` on the
        # pending doc (was a KeyError → HTTP 500 in the mobile app).
        req_phone = req.get("contact_mobile") or ""
        if not req_phone:
            # Iter 88 — revert CAS reservation so admin can retry later
            await db.company_requests.update_one(
                {"request_id": request_id, "status": "provisioning"},
                {"$set": {"status": "pending"}, "$unset": {"provisioning_started_at": "", "provisioning_by": ""}},
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    "This request has no contact mobile on file — "
                    "cannot provision a company_admin. Please reject "
                    "or ask the applicant to resubmit."
                ),
            )
        _phone_variants = {req_phone}
        _bare = (req_phone or "").lstrip("+")
        _phone_variants.add(_bare)
        if _bare.startswith("91") and len(_bare) == 12:
            _phone_variants.add(_bare[2:])
        if len(_bare) == 10:
            _phone_variants.add(f"91{_bare}")
            _phone_variants.add(f"+91{_bare}")
        _existing = await db.users.find(
            {"phone": {"$in": list(_phone_variants)}},
            {"_id": 0, "user_id": 1, "role": 1, "company_id": 1, "email": 1},
        ).to_list(20)
        for _eu in _existing:
            if _eu.get("role") == "super_admin":
                # Auto-reject so admins aren't stuck retrying.
                await db.company_requests.update_one(
                    {"request_id": request_id},
                    {"$set": {
                        "status": "rejected",
                        "decided_by": user["user_id"],
                        "decided_at": now_iso(),
                        "admin_note": (
                            "Auto-rejected: phone is linked to a Super Admin "
                            "account. Please use 'Create Company' from the "
                            "admin panel instead."
                        ),
                    }},
                )
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This mobile number is already linked to a Super Admin "
                        "account. Request auto-rejected — please use "
                        "'Create Company' from the admin panel."
                    ),
                )
        # Auto-heal true orphans and detect live-firm collisions
        _has_live_collision = False
        _live_firm_name: Optional[str] = None
        for _eu in _existing:
            _live_firm = None
            if _eu.get("company_id"):
                _live_firm = await db.companies.find_one(
                    {"company_id": _eu.get("company_id")},
                    {"_id": 0, "name": 1},
                )
            if _live_firm:
                _has_live_collision = True
                _live_firm_name = _live_firm.get("name")
                break
            # Orphan (no live firm) → safe to purge
            await db.users.delete_one({"user_id": _eu.get("user_id")})
            await db.user_sessions.delete_many({"user_id": _eu.get("user_id")})
            logger.info(
                "[approval] auto-healed orphan user_id=%s phone=%s role=%s",
                _eu.get("user_id"), req_phone, _eu.get("role"),
            )
        if _has_live_collision:
            # Auto-reject the request so it stops blocking the queue.
            await db.company_requests.update_one(
                {"request_id": request_id},
                {"$set": {
                    "status": "rejected",
                    "decided_by": user["user_id"],
                    "decided_at": now_iso(),
                    "admin_note": (
                        "Auto-rejected: mobile number is already registered "
                        f"as company admin of '{_live_firm_name or 'another firm'}'. "
                        "Ask the applicant to sign in with their existing account."
                    ),
                }},
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Mobile number is already registered as company admin of "
                    f"'{_live_firm_name or 'another firm'}'. Request auto-rejected."
                ),
            )
        # Create company
        company_doc = {
            "company_id": f"co_{uuid.uuid4().hex[:10]}",
            "name": req["company_name"],
            "address": req.get("address", ""),
            "city": req.get("city"),
            "state": req.get("state"),
            "nature_of_business": req.get("nature_of_business"),
            "business_category": req.get("business_category"),
            "business_subcategory": req.get("business_subcategory"),
            "attendance_policy": _policy_for_category(
                req.get("business_category"), req.get("business_subcategory")
            ),
            "office_lat": req.get("office_lat") or 0.0,
            "office_lng": req.get("office_lng") or 0.0,
            "geofence_radius_m": req.get("geofence_radius_m") or 200,
            "company_code": uuid.uuid4().hex[:6].upper(),
            "compliance_enabled": True,
            # Iter 89 — Carry over the logo captured during self-registration
            # so it appears on the sidebar the moment the firm is approved.
            "logo_base64": req.get("logo_base64"),
            "logo_mime": req.get("logo_mime"),
            "logo_updated_at": now_iso() if req.get("logo_base64") else None,
            "created_at": now_iso(),
        }
        # Iter 88 — Retry once on the ultra-rare company_code hex
        # collision so it never bubbles up as HTTP 500 to the client.
        try:
            await db.companies.insert_one(company_doc)
        except DuplicateKeyError:
            company_doc["company_id"] = f"co_{uuid.uuid4().hex[:10]}"
            company_doc["company_code"] = uuid.uuid4().hex[:6].upper()
            await db.companies.insert_one(company_doc)
        # Create company_admin user with the PIN they registered with
        user_doc = {
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": req.get("contact_email"),
            "phone": req["contact_mobile"],
            "name": req["contact_name"],
            "picture": None,
            "role": "company_admin",
            "company_id": company_doc["company_id"],
            "employee_code": "ADMIN",
            "position": "Company Admin",
            "onboarded": True,
            "approval_status": "approved",
            "has_pin": True,
            "pin_hash": req["admin_pin_hash"],
            "pin_must_change": False,
            "pin_set_at": now_iso(),
            "created_at": now_iso(),
        }
        try:
            await db.users.insert_one(user_doc)
        except DuplicateKeyError:
            # Two very different situations land here:
            #   1. Iter 88 — concurrent PATCH double-tap: the OTHER call
            #      already created THIS request's admin (same phone).
            #      → idempotent success.
            #   2. Iter 93 — the request's EMAIL belongs to a different
            #      firm's account (registered before the duplicate-email
            #      guard existed). → clean 409 + reject, never a silent
            #      "approved with no firm".
            logger.warning(
                "[approval] DuplicateKeyError on users insert for request %s",
                request_id,
            )
            existing_user = await db.users.find_one(
                {"phone": user_doc.get("phone"), "role": "company_admin"},
                {"_id": 0},
            )
            if existing_user:
                # Same phone → genuine double-tap winner for THIS request.
                # Clean up the company we just created (orphan) if it
                # differs from the existing user's company.
                if existing_user.get("company_id") != company_doc["company_id"]:
                    await db.companies.delete_one({"company_id": company_doc["company_id"]})
                    winning_company = await db.companies.find_one(
                        {"company_id": existing_user.get("company_id")},
                        {"_id": 0},
                    ) or {}
                    result["company_id"] = winning_company.get("company_id")
                    result["company_code"] = winning_company.get("company_code")
                else:
                    result["company_id"] = company_doc["company_id"]
                    result["company_code"] = company_doc["company_code"]
                result["admin_user_id"] = existing_user.get("user_id")
                result["already_decided"] = True
            else:
                # Email conflict with ANOTHER account — reject cleanly.
                await db.companies.delete_one({"company_id": company_doc["company_id"]})
                email_owner = await db.users.find_one(
                    {"email": user_doc.get("email")},
                    {"_id": 0, "company_id": 1, "role": 1},
                )
                owner_firm = None
                if email_owner and email_owner.get("company_id"):
                    owner_firm = await db.companies.find_one(
                        {"company_id": email_owner["company_id"]},
                        {"_id": 0, "name": 1},
                    )
                await db.company_requests.update_one(
                    {"request_id": request_id},
                    {"$set": {
                        "status": "rejected",
                        "decided_at": now_iso(),
                        "decided_by": user["user_id"],
                        "reject_reason": (
                            "Email already registered"
                            + (f" with '{owner_firm['name']}'" if owner_firm else "")
                            + ". Ask the applicant to use a different email or sign in."
                        ),
                    },
                     "$unset": {"provisioning_started_at": "", "provisioning_by": ""}},
                )
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This email is already registered"
                        + (f" with '{owner_firm['name']}'" if owner_firm else " to another account")
                        + ". Request auto-rejected — ask the applicant to "
                        "re-submit with a different email."
                    ),
                )
        logger.info(f"[COMPANY REG] APPROVED: {req.get('company_name','?')} → company_id={company_doc['company_id']}, admin={req.get('contact_mobile','?')}")
        result.setdefault("company_id", company_doc["company_id"])
        result.setdefault("company_code", company_doc["company_code"])
        result.setdefault("admin_user_id", user_doc["user_id"])

    r = await db.company_requests.update_one(
        {"request_id": request_id},
        {"$set": {"status": status,
                  "decided_by": user["user_id"],
                  "decided_at": now_iso(),
                  "admin_note": payload.get("admin_note"),
                  # Iter 86 - Persist provisioning outputs on the request
                  # doc so that a repeat "Approve" click can be short-
                  # circuited by the idempotency guard above instead of
                  # creating a duplicate firm.
                  "result_company_id": result.get("company_id"),
                  "result_company_code": result.get("company_code"),
                  "result_admin_user_id": result.get("admin_user_id")}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Request not found")

    fresh = await db.company_requests.find_one({"request_id": request_id}, {"_id": 0, "admin_pin_hash": 0})
    return {**fresh, **result}


@api.post("/onboarding")
async def submit_onboarding(payload: OnboardingSubmit,
                            authorization: Optional[str] = Header(None)):
    """Employee submits their profile + company code to complete onboarding."""
    user = await get_user_from_token(authorization)
    if user.get("onboarded"):
        raise HTTPException(status_code=400, detail="You are already onboarded")

    code = payload.company_code.strip().upper()
    company = await db.companies.find_one({"company_code": code}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Invalid company code")

    if payload.half_day_hrs <= 0 or payload.full_day_hrs <= 0:
        raise HTTPException(status_code=400, detail="Working hours must be positive")
    if payload.half_day_hrs >= payload.full_day_hrs:
        raise HTTPException(
            status_code=400,
            detail="Half-day hours must be less than full-day hours",
        )
    if payload.salary_monthly < 0:
        raise HTTPException(status_code=400, detail="Salary cannot be negative")

    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "name": payload.name,
            "father_name": payload.father_name,
            "dob": payload.dob,
            "doj": payload.doj,
            "shift_start": payload.shift_start,
            "shift_end": payload.shift_end,
            "salary_monthly": payload.salary_monthly,
            "half_day_hrs": payload.half_day_hrs,
            "full_day_hrs": payload.full_day_hrs,
            "company_id": company["company_id"],
            "onboarded": True,
            "onboarded_at": now_iso(),
            # NEW: employee self-onboarding starts pending; company admin
            # must approve before the account is unlocked.
            "approval_status": "pending",
            "approval_requested_at": now_iso(),
            "approval_note": None,
            "approved_by": None,
            "approved_at": None,
        }},
    )
    updated = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    # Iter 145 — web-push alert to the firm's admins: new joining request.
    try:
        from routes.web_push import push_to_company_admins
        await push_to_company_admins(
            company["company_id"],
            "New joining request",
            f"{payload.name} has requested to join {company.get('name') or code}. Tap to review.",
            url="/admin", tag=f"join_{user['user_id']}")
    except Exception:
        pass
    return {"ok": True, "user": updated, "company": company}


# ---------------------------------------------------------------------------
# Employee approval workflow (company_admin / super_admin)
# ---------------------------------------------------------------------------
@api.get("/admin/pending-approvals")
async def list_pending_approvals(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    q: dict = {"role": "employee", "approval_status": "pending", "onboarded": True}
    if admin["role"] == "company_admin":
        if not admin.get("company_id"):
            raise HTTPException(status_code=400, detail="Admin has no company assigned")
        q["company_id"] = admin["company_id"]
    elif company_id:
        q["company_id"] = company_id
    users = await db.users.find(q, {"_id": 0}).sort("approval_requested_at", 1).to_list(1000)
    # Attach company_name for context
    company_ids = list({u["company_id"] for u in users if u.get("company_id")})
    cmap: dict = {}
    if company_ids:
        cs = await db.companies.find({"company_id": {"$in": company_ids}}, {"_id": 0, "company_id": 1, "name": 1}).to_list(1000)
        cmap = {c["company_id"]: c.get("name") for c in cs}
    for u in users:
        u["company_name"] = cmap.get(u.get("company_id"))
    return {"pending": users}


class ApprovalDecision(BaseModel):
    user_id: str
    action: str  # "approve" | "reject"
    note: Optional[str] = None


@api.patch("/admin/approve-employee")
async def decide_employee_approval(
    payload: ApprovalDecision,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    if payload.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    target = await db.users.find_one({"user_id": payload.user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Company admins can only decide on employees in their own company
    if admin["role"] == "company_admin":
        if not admin.get("company_id") or target.get("company_id") != admin["company_id"]:
            raise HTTPException(status_code=403, detail="Not allowed to decide on users outside your company")

    updates: dict
    temp_pin: Optional[str] = None
    if payload.action == "approve":
        updates = {
            "approval_status": "approved",
            "approved_by": admin["user_id"],
            "approved_at": now_iso(),
            "approval_note": payload.note,
        }
        # Iter 96f — newly-approved employees get an automatic Punch-IN at
        # the moment of their FIRST app login (consumed in
        # _maybe_first_login_punch); normal punching policy applies after.
        if (target.get("role") or "employee") == "employee":
            updates["first_login_punch_pending"] = True
        # Auto-generate a sequential employee_code (COMPANY_CODE + 4-digit
        # sequence, e.g. "SKS0007") if one isn't already set. Legacy codes
        # in older formats are left as-is.
        if not target.get("employee_code") and target.get("company_id"):
            new_code = await _next_employee_code(target["company_id"])
            if new_code:
                updates["employee_code"] = new_code

        # Generate a temp PIN if one isn't set yet, and force change on first login
        if not target.get("pin_hash"):
            temp_pin = _generate_temp_pin()
            while len(set(temp_pin)) == 1 or temp_pin in {"123456", "654321", "000000", "111111"}:
                temp_pin = _generate_temp_pin()
            updates["pin_hash"] = _hash_pin(temp_pin)
            updates["pin_must_change"] = True
            updates["pin_set_at"] = now_iso()
            updates["has_pin"] = True
    else:
        # Reject clears the company link so employee returns to register-choice
        updates = {
            "approval_status": "rejected",
            "approved_by": admin["user_id"],
            "approved_at": now_iso(),
            "approval_note": payload.note,
            "company_id": None,
            "onboarded": False,
        }

    await db.users.update_one({"user_id": payload.user_id}, {"$set": updates})
    resp = await db.users.find_one({"user_id": payload.user_id}, {"_id": 0})
    # Iter 145 — web-push the joining decision to the employee.
    try:
        from routes.web_push import push_to_user
        if payload.action == "approve":
            await push_to_user(
                payload.user_id, "Joining approved 🎉",
                "Your joining request has been approved. You can now log in and punch attendance.",
                url="/", tag="join_decision")
        else:
            await push_to_user(
                payload.user_id, "Joining request rejected",
                (payload.note or "Your joining request was rejected. Contact your employer for details."),
                url="/", tag="join_decision")
    except Exception:
        pass
    if temp_pin:
        # Return plaintext temp PIN once so admin can share it with the employee
        resp = {**resp, "temp_pin": temp_pin}
    return resp


# ---------------------------------------------------------------------------
# Company / Geofence
# ---------------------------------------------------------------------------
@api.get("/company")
async def get_company(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    if not user.get("company_id"):
        raise HTTPException(status_code=404, detail="No company assigned")
    company = await db.companies.find_one({"company_id": user["company_id"]}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    # Iter 265 — USER RULE: attendance punching in the employee PWA is
    # ALWAYS enabled, regardless of the firm's Bio Matrix Attendance /
    # Salary-Process configuration. (Previously this was gated so that
    # firms with Bio Matrix OFF disabled app punching; the owner wants
    # employees to always be able to punch from the app.) The actual
    # /attendance/punch endpoint still enforces GPS / geofence / biometric
    # rules, so this only controls whether the punch UI is shown.
    company["attendance_punching_enabled"] = True
    return company


@api.patch("/company")
async def update_company(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    if not user.get("company_id"):
        raise HTTPException(status_code=400, detail="No company")
    allowed = {
        "name", "address", "office_lat", "office_lng", "geofence_radius_m",
        # Attendance-mode toggle: when False, the mobile client hides the
        # background auto-punch flow and shows a manual Punch In/Out button.
        # Geofence + GPS-on remain enforced by /attendance/punch either way.
        "auto_punch_enabled",
        # Iter 64 — Location-punching master switch. When False, GPS is
        # optional at server level, and biometric-only punches are allowed
        # from the client (fingerprint + face selfie).
        "location_punching_enabled",
        # Iter 64 — Reject outside-geofence IN-punches (strict mode).
        "reject_outside_geofence",
        # Firm Master — allow offline punch queue + sync in the employee PWA.
        "offline_geofence_enabled",
        "punch_approval_required",
    }
    updates = {k: v for k, v in payload.items() if k in allowed}
    if updates:
        await db.companies.update_one({"company_id": user["company_id"]}, {"$set": updates})
    company = await db.companies.find_one({"company_id": user["company_id"]}, {"_id": 0})
    return company


# ---- Multi-company management (Super Admin only) --------------------------
class BranchCreate(BaseModel):
    name: str
    address: Optional[str] = None
    office_lat: float
    office_lng: float
    geofence_radius_m: Optional[int] = 200
    company_id: Optional[str] = None  # super_admin can pass explicitly


class BranchUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    office_lat: Optional[float] = None
    office_lng: Optional[float] = None
    geofence_radius_m: Optional[int] = None
    active: Optional[bool] = None


@api.get("/company/branches")
async def list_branches(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """List branches for a company. company_admin sees their own; super
    admin can pass `company_id` (else returns all)."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    q: dict = {}
    if user["role"] == "company_admin":
        q["company_id"] = user.get("company_id")
    elif company_id and company_id != "all":
        q["company_id"] = company_id
    branches = await db.branches.find(q, {"_id": 0}).sort("created_at", 1).to_list(500)
    return {"branches": branches}


@api.post("/company/branches")
async def create_branch(
    payload: BranchCreate,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])

    scope_cid = user.get("company_id") if user["role"] == "company_admin" else payload.company_id
    if not scope_cid:
        raise HTTPException(status_code=400, detail="company_id required")
    company = await db.companies.find_one({"company_id": scope_cid}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    branch_id = f"br_{uuid.uuid4().hex[:10]}"
    doc = {
        "branch_id": branch_id,
        "company_id": scope_cid,
        "name": payload.name.strip(),
        "address": (payload.address or "").strip() or None,
        "office_lat": payload.office_lat,
        "office_lng": payload.office_lng,
        "geofence_radius_m": payload.geofence_radius_m or 200,
        "active": True,
        "created_at": now_iso(),
        "created_by_user_id": user["user_id"],
    }
    await db.branches.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "branch": doc}


@api.patch("/company/branches/{branch_id}")
async def update_branch(
    branch_id: str,
    payload: BranchUpdate,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    b = await db.branches.find_one({"branch_id": branch_id}, {"_id": 0})
    if not b:
        raise HTTPException(status_code=404, detail="Branch not found")
    if user["role"] == "company_admin" and b.get("company_id") != user.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your branch")

    patch = payload.model_dump(exclude_none=True) if hasattr(payload, "model_dump") else payload.dict(exclude_none=True)  # type: ignore[attr-defined]
    if not patch:
        return {"ok": True, "branch": b}
    patch["updated_at"] = now_iso()
    await db.branches.update_one({"branch_id": branch_id}, {"$set": patch})
    fresh = await db.branches.find_one({"branch_id": branch_id}, {"_id": 0})
    return {"ok": True, "branch": fresh}


@api.delete("/company/branches/{branch_id}")
async def delete_branch(
    branch_id: str,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    b = await db.branches.find_one({"branch_id": branch_id}, {"_id": 0})
    if not b:
        raise HTTPException(status_code=404, detail="Branch not found")
    if user["role"] == "company_admin" and b.get("company_id") != user.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your branch")
    # Iter 737 — DELETE PROTECTION: branches with dependent records can only
    # be DEACTIVATED, never hard-deleted (history must survive).
    dep_emp = await db.users.count_documents({"home_branch_id": branch_id})
    dep_att = await db.attendance.count_documents({"branch_id": branch_id})
    dep_tr = await db.branch_transfers.count_documents(
        {"$or": [{"prev_branch_id": branch_id}, {"new_branch_id": branch_id}]})
    if dep_emp or dep_att or dep_tr:
        parts = []
        if dep_emp:
            parts.append(f"{dep_emp} employee(s)")
        if dep_att:
            parts.append(f"{dep_att} attendance record(s)")
        if dep_tr:
            parts.append(f"{dep_tr} transfer record(s)")
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: this branch has {', '.join(parts)}. "
                   "Use DEACTIVATE instead — history is preserved.")
    await db.branches.delete_one({"branch_id": branch_id})
    # cascade branch-owned master data (no dependents existed)
    await db.branch_documents.delete_many({"branch_id": branch_id})
    await db.branch_audit.delete_many({"branch_id": branch_id})
    return {"ok": True}


@api.get("/companies/{company_id}/logo")
async def company_logo(company_id: str, authorization: Optional[str] = Header(None)):
    """Iter 307 (perf) — on-demand firm logo (excluded from the list)."""
    user = await get_user_from_token(authorization)
    if user["role"] == "company_admin" and user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not your company")
    c = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "logo_base64": 1})
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"logo_base64": c.get("logo_base64")}


@api.get("/companies")
async def list_companies(authorization: Optional[str] = Header(None),
                         lite: Optional[int] = None):
    """List all companies with quick stats.

    Iter 342 (perf) — ``?lite=1`` returns ONLY picker fields (id, name,
    code, capability flags) and SKIPS the stats aggregation entirely.
    Used by the firm picker / context on every page load.

    Access:
      • super_admin — sees every firm.
      • sub_admin   — sees only firms in their `sub_admin_company_scope`.
                      A scope of "all" returns every firm; any other scope
                      ("restricted") returns only `sub_admin_company_ids`.
    """
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin"])
    query: dict = {}
    if user.get("role") == "sub_admin":
        scope = user.get("sub_admin_company_scope") or "all"
        # Iter 132 (user bug) — User Rights saves the scope as "restricted",
        # but this check previously looked for "limited", so restricted
        # sub-admins saw EVERY firm. Treat anything other than "all" as
        # restricted.
        if scope != "all":
            allowed = user.get("sub_admin_company_ids") or []
            if not allowed:
                return {"companies": []}
            query["company_id"] = {"$in": allowed}
    companies = await db.companies.find(
        # Iter 307 (perf) — the list is fetched by every picker/sidebar;
        # firm logos (base64, can be MBs across firms) are excluded here
        # and served on demand via GET /companies/{id}/logo.
        query,
        {"_id": 0, "company_id": 1, "name": 1, "company_code": 1,
         "location_punching_enabled": 1, "auto_punch_enabled": 1,
         "face_match_enabled": 1, "is_active": 1} if lite else {"_id": 0, "logo_base64": 0},
    ).to_list(2000)
    # Firm Master list is ALWAYS alphabetical by firm name (user directive).
    companies.sort(key=lambda c: (c.get("name") or "").strip().upper())
    if lite:
        return {"companies": companies}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Iter 342 (user perf issue — PWA firm selection slow): the loop below
    # used to fire 3 DB queries PER FIRM (employees / present / pending
    # leaves), i.e. 600+ round-trips with 200 firms. Replaced with THREE
    # aggregations across all firms.
    _cids = [c["company_id"] for c in companies]
    _emp_n: Dict[str, int] = {}
    async for g in db.users.aggregate([
        {"$match": {"company_id": {"$in": _cids}, "role": "employee"}},
        {"$group": {"_id": "$company_id", "n": {"$sum": 1}}},
    ]):
        _emp_n[g["_id"]] = g["n"]
    _pres_n: Dict[str, int] = {}
    async for g in db.attendance.aggregate([
        {"$match": {"company_id": {"$in": _cids}, "date": today, "kind": "in"}},
        {"$group": {"_id": {"c": "$company_id", "u": "$user_id"}}},
        {"$group": {"_id": "$_id.c", "n": {"$sum": 1}}},
    ]):
        _pres_n[g["_id"]] = g["n"]
    _leave_n: Dict[str, int] = {}
    async for g in db.leaves.aggregate([
        {"$match": {"company_id": {"$in": _cids}, "status": "pending"}},
        {"$group": {"_id": "$company_id", "n": {"$sum": 1}}},
    ]):
        _leave_n[g["_id"]] = g["n"]
    out = []
    for c in companies:
        cid = c["company_id"]
        c["stats"] = {
            "employees": _emp_n.get(cid, 0),
            "present_today": _pres_n.get(cid, 0),
            "pending_leaves": _leave_n.get(cid, 0),
        }
        out.append(c)
    return {"companies": out}


@api.post("/companies")
async def create_company(payload: CompanyCreate,
                         authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin"])

    # Normalise & validate the optional company_code (firm prefix used for
    # sequential employee codes). If omitted, the Company model's default
    # (random 6-hex) is used.
    company_code_override: Optional[str] = None
    if payload.company_code is not None:
        cc = (payload.company_code or "").strip().upper()
        if cc:
            if not re.fullmatch(r"[A-Z0-9]{2,8}", cc):
                raise HTTPException(
                    status_code=400,
                    detail="Company Code must be 2–8 letters or digits (A–Z, 0–9).",
                )
            company_code_override = cc

    kwargs = dict(
        name=payload.name,
        address=payload.address,
        office_lat=payload.office_lat,
        office_lng=payload.office_lng,
        geofence_radius_m=payload.geofence_radius_m,
        compliance_enabled=payload.compliance_enabled,
    )
    if company_code_override:
        kwargs["company_code"] = company_code_override
    # Business category dropdown (Firm Master)
    bcat, bsub = _validate_business_category(
        payload.business_category, payload.business_subcategory
    )
    if bcat:
        kwargs["business_category"] = bcat
        kwargs["business_subcategory"] = bsub
    # Auto-attach an attendance policy preset based on the picked business
    # type. The Company Admin can tweak it later from the "Attendance Policy"
    # screen. If no category is chosen, we still attach the generic default
    # so the screen has something to render.
    kwargs["attendance_policy"] = _policy_for_category(bcat, bsub)
    company = Company(**kwargs).model_dump()
    company["created_by"] = user["user_id"]
    try:
        await db.companies.insert_one(company)
    except DuplicateKeyError:
        # Look up the existing owner so the operator can find + delete
        # / rename it instead of guessing.
        existing = await db.companies.find_one(
            {"company_code": company.get("company_code")},
            {"_id": 0, "name": 1, "company_id": 1},
        )
        owner_hint = (
            f" — currently held by \"{existing.get('name')}\" (company_id={existing.get('company_id')})"
            if existing else ""
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Company Code '{company.get('company_code')}' is already in use"
                f"{owner_hint}. Delete or rename that firm first, then retry."
            ),
        )

    result: dict = {k: v for k, v in company.items() if k != "_id"}

    # Path B — Super Admin allots credentials in one shot.
    # If admin_phone is provided, provision a company_admin login with a
    # random temp PIN. Returns the plaintext temp PIN once so the super
    # admin can share it verbally / via email.
    if payload.admin_phone:
        admin_phone = _normalise_phone(payload.admin_phone)
        if not admin_phone or len(admin_phone.lstrip("+")) < 8:
            raise HTTPException(status_code=400, detail="Enter a valid admin mobile number")
        # Iter 77r — Auto-heal orphaned admin records: if the phone is
        # taken by a user whose company_id points to a firm that no
        # longer exists (force-deleted), remove that stale user so this
        # phone can be reused. Live users (belonging to an existing
        # firm) still block.
        existing = await db.users.find_one({"phone": admin_phone}, {"_id": 0, "role": 1, "company_id": 1, "user_id": 1})
        if existing:
            _live_firm = None
            if existing.get("company_id"):
                _live_firm = await db.companies.find_one(
                    {"company_id": existing.get("company_id")}, {"_id": 0, "company_id": 1},
                )
            if not _live_firm and existing.get("role") in ("company_admin", "sub_admin", "employee"):
                # Orphan record — safe to remove and continue.
                await db.users.delete_one({"user_id": existing.get("user_id")})
                await db.user_sessions.delete_many({"user_id": existing.get("user_id")})
                logger.info(
                    "[create-company] auto-healed orphan user for phone=%s (was linked to deleted firm=%s)",
                    admin_phone, existing.get("company_id"),
                )
            else:
                raise HTTPException(
                    status_code=409,
                    detail="A user with this admin mobile number already exists.",
                )
        admin_email = (payload.admin_email or "").strip().lower() or None
        if admin_email:
            existing_e = await db.users.find_one({"email": admin_email}, {"_id": 0, "role": 1, "company_id": 1, "user_id": 1})
            if existing_e:
                _live_firm_e = None
                if existing_e.get("company_id"):
                    _live_firm_e = await db.companies.find_one(
                        {"company_id": existing_e.get("company_id")}, {"_id": 0, "company_id": 1},
                    )
                if not _live_firm_e and existing_e.get("role") in ("company_admin", "sub_admin", "employee"):
                    await db.users.delete_one({"user_id": existing_e.get("user_id")})
                    await db.user_sessions.delete_many({"user_id": existing_e.get("user_id")})
                    logger.info(
                        "[create-company] auto-healed orphan email=%s (linked to deleted firm=%s)",
                        admin_email, existing_e.get("company_id"),
                    )
                else:
                    raise HTTPException(status_code=409, detail="A user with this admin email already exists.")

        temp_pin = _generate_temp_pin()
        while len(set(temp_pin)) == 1 or temp_pin in {"123456", "654321", "000000", "111111"}:
            temp_pin = _generate_temp_pin()

        # Web-portal temp password (only when we have an email — password login
        # is by email). Follows the same "reveal once, must change on first
        # login" pattern used elsewhere in the app.
        temp_password = _generate_temp_password() if admin_email else None

        admin_doc = {
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": admin_email,
            "phone": admin_phone,
            "name": (payload.admin_name or "").strip() or f"{payload.name} Admin",
            "picture": None,
            "role": "company_admin",
            "company_id": company["company_id"],
            "employee_code": "ADMIN",
            "position": "Company Admin",
            "onboarded": True,
            "approval_status": "approved",
            "has_pin": True,
            "pin_hash": _hash_pin(temp_pin),
            "pin_must_change": True,
            "pin_set_at": now_iso(),
            "pin_reset_by": user["user_id"],
            # Store the plaintext PIN alongside the hash so the super admin
            # can view it on the Company Details screen for as long as the
            # admin hasn't changed it. Cleared automatically on first change
            # (see /auth/change-pin and pin_must_change flip).
            "temp_pin_plaintext": temp_pin,
            "temp_credentials_generated_at": now_iso(),
            "created_at": now_iso(),
        }
        if temp_password:
            admin_doc["password_hash"] = _hash_password(temp_password)
            admin_doc["password_must_change"] = True
            admin_doc["password_set_at"] = now_iso()
            admin_doc["password_reset_by"] = user["user_id"]
            admin_doc["temp_password_plaintext"] = temp_password
        await db.users.insert_one(admin_doc)
        logger.info(f"[COMPANY B] created company {company['company_id']} with admin phone={admin_phone}")
        result["admin"] = {
            "user_id": admin_doc["user_id"],
            "phone": admin_phone,
            "email": admin_email,
            "name": admin_doc["name"],
            "temp_pin": temp_pin,
            "temp_password": temp_password,
        }

    return result


@api.patch("/companies/{company_id}")
async def edit_company(company_id: str, payload: CompanyUpdate,
                       authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin"])
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "company_code" in updates:
        cc = (updates.get("company_code") or "").strip().upper()
        if cc:
            if not re.fullmatch(r"[A-Z0-9]{2,8}", cc):
                raise HTTPException(
                    status_code=400,
                    detail="Company Code must be 2–8 letters or digits (A–Z, 0–9).",
                )
            updates["company_code"] = cc
        else:
            # Explicit blank — clear the override so the auto-generated one
            # remains untouched. Prevents accidental empty-string codes.
            del updates["company_code"]
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    # Business category (Firm Master dropdown). If either field is supplied,
    # normalise the pair via the validator. When category is cleared to empty,
    # we clear both stored fields so the company falls back to "unset".
    if "business_category" in updates or "business_subcategory" in updates:
        raw_cat = updates.pop("business_category", None)
        raw_sub = updates.pop("business_subcategory", None)
        if raw_cat in (None, ""):
            # Clear both when category is explicitly blanked
            updates["business_category"] = None
            updates["business_subcategory"] = None
        else:
            bcat, bsub = _validate_business_category(raw_cat, raw_sub)
            updates["business_category"] = bcat
            updates["business_subcategory"] = bsub
    try:
        r = await db.companies.update_one(
            {"company_id": company_id}, {"$set": updates}
        )
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Company Code '{updates.get('company_code')}' is already in use "
                "by another company. Please choose a different one."
            ),
        )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    return await db.companies.find_one({"company_id": company_id}, {"_id": 0})


async def delete_company_cascade(company_id: str, force: bool) -> Dict[str, Any]:
    """Cascade-delete a firm's ancillary data (and users when force=True),
    then the company doc itself. Shared by the direct super-admin delete and
    the approved sub-admin deletion request."""
    cascade_report: Dict[str, Any] = {}
    always_clean = (
        "attendance", "leaves", "tickets", "payslips",
        "notifications", "masters", "employee_master_pdfs",
        "user_sessions", "profile_edit_requests", "biometric_cmd_results",
        "messages", "automation_jobs", "biometric_unknown", "biometric_unmapped",
        "attendance_audit_log", "punches", "compliance_docs",
        "salary_runs", "compliance_salary_runs", "employee_documents",
        "biometric_devices", "punch_approvals", "shift_summaries",
        "company_requests", "company_documents", "bonus_runs",
        "compliance_salary_batches", "employee_policy", "branches",
        "company_audit_log",
        "employee_group_policies",
        # Iter 754 (user bug — deleted firm's EPFO login kept blocking the
        # same User ID on other firms): firm master + contacts must go too.
        "firm_masters", "company_contacts",
    )
    for col in always_clean:
        try:
            r = await db[col].delete_many({"company_id": company_id})
            cascade_report[col] = r.deleted_count
        except Exception:
            cascade_report[col] = "err"
    if force:
        try:
            r = await db.users.delete_many({"company_id": company_id})
            cascade_report["users"] = r.deleted_count
        except Exception:
            cascade_report["users"] = "err"
    await db.companies.delete_one({"company_id": company_id})
    return cascade_report


@api.delete("/companies/{company_id}")
async def delete_company(company_id: str,
                         force: bool = Query(False),
                         authorization: Optional[str] = Header(None)):
    """Delete a company. If `force=true`, cascade-delete all users,
    attendance records, leaves, tickets, payslips, notifications and OTP
    codes tied to that company. Otherwise reject when users are still linked.

    User directive (Iter 139) — ONLY the Super Admin may delete or
    force-delete a firm. Sub Admins are fully blocked (previously they
    could file a deletion request; that path is now disabled too).
    """
    user = await get_user_from_token(authorization)
    # Iter 139 (user directive) — STRICT super-admin only. NOTE:
    # require_role() auto-admits sub_admins wherever super_admin is
    # allowed, so the strict guard is required here.
    require_super_admin_strict(user)
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "name": 1})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    linked = await db.users.count_documents({"company_id": company_id})
    if linked > 0 and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{linked} employee(s) still linked to this company. "
                "Confirm again to cascade-delete them along with the company."
            ),
        )

    cascade_report = await delete_company_cascade(company_id, force)
    logger.info(f"[DELETE company] {company_id} ({company.get('name')}) by {user.get('email')} force={force} cascade={cascade_report}")
    return {"ok": True, "cascade": cascade_report, "company_name": company.get("name")}


# ===========================================================================
# Super-admin company details, enable/disable, and admin-credential editing.
# These power the "Company Details" screen where the super admin sees every
# field of a client firm, can pause access, and can rotate the company-admin's
# login (mobile / email / display name / PIN reset).
# ===========================================================================
class CompanyAdminUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class CompanyDisableRequest(BaseModel):
    enabled: bool
    reason: Optional[str] = None


class UserDisableRequest(BaseModel):
    disabled: bool
    reason: Optional[str] = None


@api.get("/companies/{company_id}/details")
async def super_admin_company_details(
    company_id: str,
    authorization: Optional[str] = Header(None),
):
    """Full profile view for the super admin — everything they might want to
    know about a client firm in one call: company doc + primary company-admin
    account + live stats. PIN itself is never returned (it is one-way hashed).
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    # Primary company-admin — pick the earliest-created if multiple exist.
    # We fetch pin_hash/password_hash separately below and never return them.
    company_admin = await db.users.find_one(
        {"company_id": company_id, "role": "company_admin"},
        {"_id": 0, "pin_hash": 0, "password_hash": 0, "face_reference_base64": 0},
        sort=[("created_at", 1)],
    )
    # Populate PIN meta the UI can render safely + temp credentials block.
    pin_meta = None
    temp_credentials = None
    if company_admin:
        pin_meta = {
            "has_pin": bool(company_admin.get("pin_hash") or company_admin.get("has_pin")),
            "must_change": bool(company_admin.get("pin_must_change")),
            "set_at": company_admin.get("pin_set_at"),
            "last_login_at": company_admin.get("pin_last_login_at"),
            "locked_until": company_admin.get("pin_locked_until"),
            "fail_count": int(company_admin.get("pin_fail_count", 0)),
            "reset_by": company_admin.get("pin_reset_by"),
        }
        # Belt-and-braces — the hashes are already excluded above.
        company_admin.pop("pin_hash", None)
        company_admin.pop("password_hash", None)
        # Temp credentials — visible ONLY while the admin still owes a change.
        # Wiped automatically the moment the admin picks their own PIN/password
        # via the change endpoints.
        temp_pin_pt = company_admin.pop("temp_pin_plaintext", None)
        temp_pw_pt = company_admin.pop("temp_password_plaintext", None)
        temp_credentials = {
            "identifier": company_admin.get("email") or company_admin.get("phone"),
            "email": company_admin.get("email"),
            "phone": company_admin.get("phone"),
            "temp_pin": temp_pin_pt if company_admin.get("pin_must_change") else None,
            "temp_password": temp_pw_pt if company_admin.get("password_must_change") else None,
            "generated_at": company_admin.get("temp_credentials_generated_at"),
            "pin_changed": (not company_admin.get("pin_must_change")) and pin_meta["has_pin"],
            "password_changed": (not company_admin.get("password_must_change"))
                and bool(pin_meta["has_pin"] and company_admin.get("email")),
        }

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Iter 75.2 — Exclude company_admin / sub_admin from the employee KPIs;
    # admins are workforce leaders, not headcount.
    total_employees = await db.users.count_documents(
        {"company_id": company_id, "role": "employee"}
    )
    active_employees = await db.users.count_documents(
        {
            "company_id": company_id,
            "role": "employee",
            "$or": [{"disabled": {"$ne": True}}, {"disabled": {"$exists": False}}],
        }
    )
    disabled_employees = total_employees - active_employees
    present_today = await db.attendance.count_documents(
        {"company_id": company_id, "date": today, "kind": "in", "status": {"$ne": "rejected"}}
    )
    pending_leaves = await db.leaves.count_documents(
        {"company_id": company_id, "status": "pending"}
    )
    open_tickets = await db.tickets.count_documents(
        {"company_id": company_id, "status": {"$in": ["open", "in_progress"]}}
    )
    devices = await db.biometric_devices.count_documents({"company_id": company_id})

    # Recent audit trail — last 10 super-admin actions touching this company.
    audit = await db.company_audit_log.find(
        {"company_id": company_id}, {"_id": 0}
    ).sort("at", -1).to_list(10) if "company_audit_log" in await db.list_collection_names() else []

    return {
        "company": company,
        "company_admin": company_admin,
        "pin_meta": pin_meta,
        "temp_credentials": temp_credentials,
        "stats": {
            "total_employees": total_employees,
            "active_employees": active_employees,
            "disabled_employees": disabled_employees,
            "present_today": present_today,
            "pending_leaves": pending_leaves,
            "open_tickets": open_tickets,
            "devices": devices,
        },
        "recent_actions": audit,
    }


async def _write_audit(entry: dict) -> None:
    """Append a small immutable audit record. Best-effort — never crashes the
    calling request."""
    try:
        entry.setdefault("at", now_iso())
        await db.company_audit_log.insert_one(entry)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[audit] failed to write: {e}")


@api.patch("/companies/{company_id}/enabled")
async def super_admin_toggle_company(
    company_id: str,
    payload: CompanyDisableRequest,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "name": 1})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    updates: dict = {"enabled": bool(payload.enabled)}
    if payload.enabled:
        updates["disabled_at"] = None
        updates["disabled_by"] = None
        updates["disabled_reason"] = None
    else:
        updates["disabled_at"] = now_iso()
        updates["disabled_by"] = admin["user_id"]
        updates["disabled_reason"] = (payload.reason or "").strip() or None
    await db.companies.update_one({"company_id": company_id}, {"$set": updates})
    # Wipe active sessions of every non-super-admin user in this company so
    # the change takes effect immediately rather than at next token refresh.
    if not payload.enabled:
        user_ids = [
            u["user_id"] async for u in db.users.find(
                {"company_id": company_id, "role": {"$ne": "super_admin"}},
                {"_id": 0, "user_id": 1},
            )
        ]
        if user_ids:
            await db.user_sessions.delete_many({"user_id": {"$in": user_ids}})
    await _write_audit({
        "company_id": company_id,
        "action": "company.enable" if payload.enabled else "company.disable",
        "actor_user_id": admin["user_id"],
        "actor_email": admin.get("email"),
        "reason": payload.reason,
    })
    return {"ok": True, "enabled": bool(payload.enabled), "company_id": company_id}


@api.patch("/companies/{company_id}/admin")
async def super_admin_update_company_admin(
    company_id: str,
    payload: CompanyAdminUpdate,
    authorization: Optional[str] = Header(None),
):
    """Update the primary company_admin's login identifiers — name, email or
    registered phone. PIN reset uses the dedicated endpoint below because it
    returns a one-time temp PIN in the response."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    target = await db.users.find_one(
        {"company_id": company_id, "role": "company_admin"},
        {"_id": 0}, sort=[("created_at", 1)],
    )
    if not target:
        raise HTTPException(status_code=404, detail="No company admin found for this firm")
    updates: dict = {}
    if payload.name is not None and payload.name.strip():
        updates["name"] = payload.name.strip()
    if payload.email is not None:
        email = payload.email.strip().lower() or None
        if email:
            # Basic e-mail sanity check
            if "@" not in email or "." not in email.split("@")[-1]:
                raise HTTPException(status_code=400, detail="Please enter a valid email address")
            clash = await db.users.find_one({"email": email, "user_id": {"$ne": target["user_id"]}}, {"_id": 0, "user_id": 1})
            if clash:
                raise HTTPException(status_code=409, detail="That email is already used by another account")
        updates["email"] = email
    if payload.phone is not None:
        phone = _normalise_phone(payload.phone) if payload.phone.strip() else None
        if phone and len(phone.lstrip("+")) < 8:
            raise HTTPException(status_code=400, detail="Please enter a valid mobile number")
        if phone:
            clash = await db.users.find_one(
                {"phone": phone, "user_id": {"$ne": target["user_id"]}},
                {"_id": 0, "user_id": 1, "role": 1, "exit_date": 1,
                 "resign_date": 1, "employment_status": 1, "active": 1})
            # Iter 295 — a resigned/left employee never blocks number reuse.
            if clash and clash.get("role") == "employee" and _employee_is_resigned(clash):
                await db.users.update_one(
                    {"user_id": clash["user_id"]},
                    {"$set": {"released_phone": phone, "identifier_released_at": now_iso()},
                     "$unset": {"phone": "", "phone_e164": ""}})
                clash = None
            if clash:
                raise HTTPException(status_code=409, detail="That mobile number is already used by another account")
        updates["phone"] = phone
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    updates["credentials_updated_by"] = admin["user_id"]
    updates["credentials_updated_at"] = now_iso()
    await db.users.update_one({"user_id": target["user_id"]}, {"$set": updates})
    await _write_audit({
        "company_id": company_id,
        "action": "admin.credentials_update",
        "actor_user_id": admin["user_id"],
        "actor_email": admin.get("email"),
        "target_user_id": target["user_id"],
        "changed": sorted(updates.keys()),
    })
    updated = await db.users.find_one(
        {"user_id": target["user_id"]},
        {"_id": 0, "pin_hash": 0, "face_reference_base64": 0},
    )
    return {"ok": True, "company_admin": updated}


@api.post("/companies/{company_id}/admin/reset-pin")
async def super_admin_reset_company_admin_pin(
    company_id: str,
    authorization: Optional[str] = Header(None),
):
    """Regenerate the primary company-admin's PIN and return the new temp PIN
    once so the super admin can hand it over. Forces pin_must_change on next
    login."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    target = await db.users.find_one(
        {"company_id": company_id, "role": "company_admin"},
        {"_id": 0, "user_id": 1, "email": 1, "phone": 1},
        sort=[("created_at", 1)],
    )
    if not target:
        raise HTTPException(status_code=404, detail="No company admin found for this firm")
    temp_pin = _generate_temp_pin()
    while len(set(temp_pin)) == 1 or temp_pin in {"123456", "654321", "000000", "111111"}:
        temp_pin = _generate_temp_pin()
    await db.users.update_one(
        {"user_id": target["user_id"]},
        {"$set": {
            "pin_hash": _hash_pin(temp_pin),
            "pin_must_change": True,
            "pin_set_at": now_iso(),
            "pin_reset_by": admin["user_id"],
            "pin_fail_count": 0,
            "pin_locked_until": None,
            "has_pin": True,
            # Keep the plaintext visible on the Company Details screen until
            # the admin actually changes their PIN.
            "temp_pin_plaintext": temp_pin,
            "temp_credentials_generated_at": now_iso(),
        }},
    )
    # Kill any live sessions this admin has so they must re-login with new PIN.
    await db.user_sessions.delete_many({"user_id": target["user_id"]})
    await _write_audit({
        "company_id": company_id,
        "action": "admin.pin_reset",
        "actor_user_id": admin["user_id"],
        "actor_email": admin.get("email"),
        "target_user_id": target["user_id"],
    })
    return {
        "ok": True,
        "user_id": target["user_id"],
        "temp_pin": temp_pin,
        "identifier": target.get("email") or target.get("phone"),
    }


@api.patch("/users/{user_id}/enabled")
async def super_admin_toggle_user(
    user_id: str,
    payload: UserDisableRequest,
    authorization: Optional[str] = Header(None),
):
    """Enable / disable an individual user. Company admin can toggle their
    own employees; super admin can toggle anyone (including company admins).
    Disabled users are blocked from logging in and existing sessions are
    invalidated so the change is immediate."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if admin["role"] == "company_admin":
        if target.get("company_id") != admin.get("company_id"):
            raise HTTPException(status_code=403, detail="Not authorised for this user")
        if target.get("role") in ("company_admin", "super_admin"):
            raise HTTPException(status_code=403, detail="Only a super admin can disable an admin account")
    if target.get("role") == "super_admin":
        raise HTTPException(status_code=400, detail="Super admins cannot be disabled")
    updates: dict = {"disabled": bool(payload.disabled)}
    if payload.disabled:
        updates["disabled_at"] = now_iso()
        updates["disabled_by"] = admin["user_id"]
        updates["disabled_reason"] = (payload.reason or "").strip() or None
    else:
        updates["disabled_at"] = None
        updates["disabled_by"] = None
        updates["disabled_reason"] = None
    await db.users.update_one({"user_id": user_id}, {"$set": updates})
    if payload.disabled:
        await db.user_sessions.delete_many({"user_id": user_id})
    await _write_audit({
        "company_id": target.get("company_id"),
        "action": "user.disable" if payload.disabled else "user.enable",
        "actor_user_id": admin["user_id"],
        "actor_email": admin.get("email"),
        "target_user_id": user_id,
        "reason": payload.reason,
    })
    return {"ok": True, "user_id": user_id, "disabled": bool(payload.disabled)}


def build_compliance_structure(basic: Any, allowances: Any, rate_type: Any = None) -> List[Dict[str, Any]]:
    """Iter 137 (user directive) — ONE interlinked source of truth for the
    Compliance salary. Rebuilds ``salary_structure_compliance`` from the
    Employee-Master Compliance Basic + firm-head allowance lines so every
    editor (Add/Edit form, Salary Update modal, Bulk Correction) stays in
    sync — ESIC eligibility & PF always read the SAME Basic head."""
    try:
        b = round(float(basic or 0), 2)
    except (TypeError, ValueError):
        b = 0.0
    rows: List[Dict[str, Any]] = []
    if b > 0:
        row: Dict[str, Any] = {"head": "Basic", "amount": b}
        rt = str(rate_type or "").strip().lower()
        if rt in ("monthly", "daily", "hourly"):
            row["rate_type"] = rt
        rows.append(row)
    for ln in (allowances if isinstance(allowances, list) else []):
        if not isinstance(ln, dict):
            continue
        h = str(ln.get("head") or "").strip()
        if not h:
            continue
        try:
            amt = round(float(ln.get("amount") or 0), 2)
        except (TypeError, ValueError):
            amt = 0.0
        rows.append({"head": h, "amount": amt})
    return rows


def compliance_gross_total(basic: Any, allowances: Any) -> float:
    """Linked Compliance Gross = Compliance Basic + Σ allowance lines."""
    try:
        total = float(basic or 0)
    except (TypeError, ValueError):
        total = 0.0
    for ln in (allowances if isinstance(allowances, list) else []):
        if isinstance(ln, dict):
            try:
                total += float(ln.get("amount") or 0)
            except (TypeError, ValueError):
                pass
    return round(total, 2)



# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------
async def _resolve_geofence(company: dict, lat: float, lng: float) -> tuple[float, dict]:
    """Find the closest office (main office + any branch) for the caller's
    company. Returns (distance_metres, closest_location_dict) where the
    location dict contains office_lat/office_lng/geofence_radius_m/name.

    Employees "float" across branches — as long as they're within the
    geofence of ANY branch (or the primary office), the punch is accepted.
    """
    candidates: list[dict] = []
    if company.get("office_lat") is not None and company.get("office_lng") is not None:
        candidates.append({
            "name": company.get("name") or "Main office",
            "kind": "main",
            "office_lat": company["office_lat"],
            "office_lng": company["office_lng"],
            "geofence_radius_m": company.get("geofence_radius_m") or 200,
        })
    async for b in db.branches.find(
        {"company_id": company["company_id"], "active": {"$ne": False}},
        {"_id": 0, "branch_id": 1, "name": 1, "office_lat": 1,
         "office_lng": 1, "geofence_radius_m": 1},
    ):
        candidates.append({
            "branch_id": b["branch_id"],
            "name": b.get("name") or "Branch",
            "kind": "branch",
            "office_lat": b["office_lat"],
            "office_lng": b["office_lng"],
            "geofence_radius_m": b.get("geofence_radius_m") or 200,
        })
    best_dist = math.inf
    best: dict = {}
    for loc in candidates:
        d = haversine_m(lat, lng, loc["office_lat"], loc["office_lng"])
        if d < best_dist:
            best_dist = d
            best = loc
    return (best_dist, best)


class PayrollEmailPayload(BaseModel):
    year: int
    month: int
    company_id: Optional[str] = None
    report_kind: Literal["attendance", "salary", "combined"] = "combined"
    recipients: Literal["self", "employees", "both"] = "self"
    user_ids: Optional[List[str]] = None  # limit to these employees


def _fmt_ist_time(iso: Optional[str]) -> str:
    """Preserved for backwards compatibility — delegates to reports.fmt_time."""
    from utils.reports import fmt_time as _ft
    return _ft(iso)


def _attendance_csv(data: dict) -> bytes:
    from utils.reports import attendance_csv as _ac
    return _ac(data)


def _salary_csv(data: dict) -> bytes:
    from utils.reports import salary_csv as _sc
    return _sc(data)


def _fmt_month_label(year: int, month: int) -> str:
    from utils.reports import fmt_month_label as _fm
    return _fm(year, month)


def _pdf_bytes(kind: str, data: dict, company_name: str) -> bytes:
    """Extracted to backend/utils/reports.py — this shim keeps in-file
    callers working without touching the rest of the module."""
    from utils.reports import pdf_bytes as _pb
    return _pb(kind, data, company_name)


async def _send_email_with_attachments(
    *, to_email: str, subject: str, text: str, html: str,
    attachments: list[dict],
) -> dict:
    """Wrap the Resend HTTP call with `attachments` support. Each
    attachment must be `{filename, content(base64), content_type}`."""
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip()
    if not api_key or not to_email:
        return {"delivered": False, "email_id": None, "error": "missing_api_key_or_recipient"}
    payload = {
        "from": f"S.K. Sharma & Co. <{from_email}>",
        "to": [to_email],
        "subject": subject,
        "text": text,
        "html": html,
    }
    if attachments:
        payload["attachments"] = attachments
    try:
        async with httpx.AsyncClient(timeout=30.0) as hc:
            r = await hc.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if r.status_code < 300:
            data = {}
            try:
                data = r.json()
            except Exception:
                pass
            return {"delivered": True, "email_id": data.get("id"), "error": None}
        snippet = r.text[:300] if r.text else ""
        return {"delivered": False, "email_id": None,
                "error": f"http_{r.status_code}: {snippet}"}
    except Exception as exc:  # noqa: BLE001
        return {"delivered": False, "email_id": None, "error": f"error: {exc}"}


@api.post("/admin/payroll/email-report")
async def admin_payroll_email_report(
    payload: PayrollEmailPayload,
    authorization: Optional[str] = Header(None),
):
    """Compute the monthly payroll run, then email CSV+PDF attachments to
    either the caller ("self"), each employee individually ("employees"),
    or both.

    Report kinds:
      • attendance — day-by-day punch sheet (In/Out per day)
      • salary     — Present/Absent/Off/Hours + Gross per employee
      • combined   — both

    When `recipients=employees`, each employee receives a report scoped to
    ONLY their own data (no cross-employee leaks)."""
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])

    data = await _compute_payroll_run(
        admin_user, payload.year, payload.month, payload.company_id,
    )
    if payload.user_ids:
        allowed = set(payload.user_ids)
        data["rows"] = [r for r in data["rows"] if r["user_id"] in allowed]
        data["attendance"] = [
            a for a in data["attendance"] if a["user_id"] in allowed
        ]
        data["totals"]["employees"] = len(data["rows"])

    if not data["rows"]:
        raise HTTPException(status_code=400,
                            detail="No employees in scope to email.")

    # Company name for header
    company_name = "S.K. Sharma & Co."
    if admin_user["role"] == "company_admin" and admin_user.get("company_id"):
        c = await db.companies.find_one(
            {"company_id": admin_user["company_id"]},
            {"_id": 0, "name": 1},
        )
        if c:
            company_name = c.get("name") or company_name
    elif payload.company_id and payload.company_id != "all":
        c = await db.companies.find_one(
            {"company_id": payload.company_id},
            {"_id": 0, "name": 1},
        )
        if c:
            company_name = c.get("name") or company_name

    label = _fmt_month_label(payload.year, payload.month)
    kind = payload.report_kind
    subject_map = {
        "attendance": f"Attendance sheet — {label}",
        "salary":     f"Salary summary — {label}",
        "combined":   f"Attendance + salary — {label}",
    }
    subject = subject_map[kind]
    text = (
        f"Monthly {kind} report for {label} attached.\n"
        f"Employees: {data['totals']['employees']}   "
        f"Total hours: {data['totals']['total_hours']:.2f}   "
        f"Gross total: {data['totals']['gross_total']:,.2f}"
    )
    html = f"""<div style='font-family: sans-serif'>
    <h2 style='color:#2b3d64'>{company_name}</h2>
    <h3>{subject}</h3>
    <p>Please find the {kind} report for <b>{label}</b> attached in
    both CSV (for Excel) and PDF formats.</p>
    <ul>
      <li><b>Employees:</b> {data['totals']['employees']}</li>
      <li><b>Total hours worked:</b> {data['totals']['total_hours']:.2f} h</li>
      <li><b>Total gross payable:</b> ₹{data['totals']['gross_total']:,.2f}</li>
    </ul>
    <p style='color:#666;font-size:12px'>Generated automatically from
    S.K. Sharma &amp; Co. B2B portal.</p>
    </div>"""

    sends: list[dict] = []

    def _b64(b: bytes) -> str:
        return base64.b64encode(b).decode("ascii")

    def _build_attachments(scoped: dict) -> list[dict]:
        atts: list[dict] = []
        month_tag = f"{scoped['year']}-{scoped['month']:02d}"
        if kind in ("attendance", "combined"):
            atts.append({
                "filename": f"attendance-{month_tag}.csv",
                "content": _b64(_attendance_csv(scoped)),
                "content_type": "text/csv",
            })
        if kind in ("salary", "combined"):
            atts.append({
                "filename": f"salary-{month_tag}.csv",
                "content": _b64(_salary_csv(scoped)),
                "content_type": "text/csv",
            })
        try:
            atts.append({
                "filename": f"{kind}-{month_tag}.pdf",
                "content": _b64(_pdf_bytes(kind, scoped, company_name)),
                "content_type": "application/pdf",
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[payroll-email] PDF gen failed: {exc}")
        return atts

    # Send-to-self
    if payload.recipients in ("self", "both"):
        to = (admin_user.get("email") or "").strip()
        if to:
            result = await _send_email_with_attachments(
                to_email=to, subject=subject, text=text, html=html,
                attachments=_build_attachments(data),
            )
            sends.append({"to": to, "role": "admin", **result})
        else:
            # Surface why the self-send was skipped so the UI can prompt
            # the admin to set an email on their account.
            sends.append({
                "to": None, "role": "admin",
                "delivered": False, "email_id": None,
                "error": "no_email_on_file",
            })

    # Send-to-each-employee: attach only that employee's slice
    if payload.recipients in ("employees", "both"):
        for row in data["rows"]:
            emp_email = (row.get("email") or "").strip()
            if not emp_email:
                sends.append({
                    "to": None, "user_id": row["user_id"], "role": "employee",
                    "delivered": False, "email_id": None,
                    "error": "no_email_on_file",
                })
                continue
            scoped = {
                **data,
                "rows": [row],
                "attendance": [
                    a for a in data["attendance"] if a["user_id"] == row["user_id"]
                ],
                "totals": {
                    "employees": 1,
                    "gross_total": row.get("gross", 0),
                    "total_hours": row.get("total_hours", 0),
                },
            }
            emp_subject = f"Your {kind} report — {label}"
            emp_html = html.replace(str(data['totals']['employees']), "1")
            result = await _send_email_with_attachments(
                to_email=emp_email, subject=emp_subject, text=text, html=emp_html,
                attachments=_build_attachments(scoped),
            )
            sends.append({
                "to": emp_email, "user_id": row["user_id"], "role": "employee",
                **result,
            })

    delivered = sum(1 for s in sends if s.get("delivered"))
    failed = len(sends) - delivered
    return {
        "ok": failed == 0,
        "delivered": delivered,
        "failed": failed,
        "sends": sends,
        "month_key": data["month_key"],
        "report_kind": kind,
        "recipients": payload.recipients,
    }


# ---------------------------------------------------------------------------
# Employee salary/attendance policy (employer-side per-employee configuration)
# ---------------------------------------------------------------------------
def _default_policy() -> dict:
    """Sensible defaults so /policy GET always returns a fully-populated
    document for the form to bind to."""
    return {
        "salary": 0.0,
        "salary_1": 0.0, "day_1": 0,
        "salary_2": 0.0, "day_2": 0,
        "salary_3": 0.0, "day_3": 0,
        "shift_name": None,
        "shift_dummy": None,
        "dummy_weekly_off": None,
        "working_hours": 8.0,
        "full_day_salary": False,
        "ot_allow": False,
        "fullday_hours": 6.0,
        "halfday_hours": 3.0,
        "cl_days": 13,
        "pl_days": 12,
        "weekly_off": 0,  # Sunday
        "week_off_min_hours": 0.0,
        "bio_code": None,
        "weekly_off_attendance": False,
        "policy_confirmed": False,
        "policy_confirmed_at": None,
        "policy_confirmed_by": None,
    }


def _get_policy_from_user(u: dict) -> dict:
    p = _default_policy()
    p.update(u.get("employee_policy") or {})
    # Fallback: use user-level salary_monthly if policy.salary is unset
    if (not p.get("salary")) and u.get("salary_monthly"):
        p["salary"] = float(u["salary_monthly"])
    return p


async def _load_scoped_employee(user_id: str, admin_user: dict) -> dict:
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not emp or emp.get("role") != "employee":
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin_user["role"] == "company_admin":
        if emp.get("company_id") != admin_user.get("company_id"):
            raise HTTPException(status_code=403, detail="Employee not in your company")
    return emp


@api.get("/admin/employees/{user_id}/policy")
async def get_employee_policy(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    require_permission(admin_user, "employees:read")
    emp = await _load_scoped_employee(user_id, admin_user)
    policy = _get_policy_from_user(emp)
    return {
        "user_id": emp["user_id"],
        "name": emp.get("name"),
        "employee_code": emp.get("employee_code"),
        "email": emp.get("email"),
        "join_date": emp.get("join_date"),
        # Iter 85 — expose company_id so the Employee Policy screen can
        # fetch the firm's compliance policy in the same load.
        "company_id": emp.get("company_id"),
        "policy": policy,
    }


@api.patch("/admin/employees/{user_id}/policy")
async def set_employee_policy(
    user_id: str,
    payload: EmployeePolicy,
    authorization: Optional[str] = Header(None),
):
    """Persist a policy patch. Any field passed in will be written; None
    values are ignored so the client can send partial updates. Setting any
    field flips `policy_confirmed=True` and stamps the caller as confirmer.
    Also mirrors `salary` into the legacy top-level `salary_monthly` so the
    existing payslip auto-creation loop keeps working."""
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    emp = await _load_scoped_employee(user_id, admin_user)

    patch = payload.model_dump(exclude_none=True) if hasattr(payload, "model_dump") else payload.dict(exclude_none=True)  # type: ignore[attr-defined]
    if not patch:
        return {"ok": True, "policy": _get_policy_from_user(emp)}

    # Merge on top of the existing policy so unlisted fields survive
    current_policy = emp.get("employee_policy") or _default_policy()
    new_policy = {**current_policy, **patch}

    # Mandatory validation: Salary 1 + Day 1 are required. Salary 2/3 are
    # optional. If Salary 2 or 3 is set, their respective Day threshold
    # must be set too.
    if (new_policy.get("salary_1") or 0) <= 0 or (new_policy.get("day_1") or 0) <= 0:
        raise HTTPException(
            status_code=400,
            detail="Salary 1 and Day 1 are mandatory (tier 1 attendance bonus).",
        )
    for i in (2, 3):
        s_key = f"salary_{i}"
        d_key = f"day_{i}"
        s_val = new_policy.get(s_key) or 0
        d_val = new_policy.get(d_key) or 0
        if s_val > 0 and d_val <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Day {i} is required when Salary {i} is set.",
            )
        if d_val > 0 and s_val <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Salary {i} is required when Day {i} is set.",
            )

    new_policy["policy_confirmed"] = True
    new_policy["policy_confirmed_at"] = now_iso()
    new_policy["policy_confirmed_by"] = admin_user.get("user_id")

    update_set: dict = {"employee_policy": new_policy}
    if "salary" in patch and patch["salary"] is not None:
        update_set["salary_monthly"] = float(patch["salary"])
    if "fullday_hours" in patch and patch["fullday_hours"] is not None:
        update_set["full_day_hrs"] = float(patch["fullday_hours"])
    if "halfday_hours" in patch and patch["halfday_hours"] is not None:
        update_set["half_day_hrs"] = float(patch["halfday_hours"])
    # Iter 85 — mirror compliance_gross into the top-level user field so
    # existing Compliance Salary Process code (which reads
    # ``user.compliance_gross``) keeps working unchanged.
    if "compliance_gross" in patch and patch["compliance_gross"] is not None:
        update_set["compliance_gross"] = float(patch["compliance_gross"])

    await db.users.update_one(
        {"user_id": emp["user_id"]},
        {"$set": update_set},
    )
    fresh = await db.users.find_one({"user_id": emp["user_id"]}, {"_id": 0})
    return {
        "ok": True,
        "user_id": emp["user_id"],
        "policy": _get_policy_from_user(fresh or emp),
    }


# ---------------------------------------------------------------------------
# Iter 77 - Per-employee ATTENDANCE POLICY override.
# ---------------------------------------------------------------------------
# Fields covered (all optional; None = inherit from group / firm):
#   * weekly_off_days     -> List[int] 0=Mon..6=Sun
#   * grace_minutes_late  -> int minutes
#   * half_day_hours      -> float hours
#   * full_day_hours      -> float hours
#   * overtime_threshold_hours -> float hours
#   * overtime_multiplier -> float
#   * duty_hours_rounding_minutes -> int (0/5/10/15/30)
#   * standard_working_hours -> float hours
#   * shift_id            -> Optional[str] (points to a shift_masters._id)
#   * night_shift_allowance_enabled -> bool
#   * night_shift_start / _end -> HH:MM
class EmployeeAttendancePolicyOverride(BaseModel):
    """Partial payload; only non-null fields are written on the employee."""
    weekly_off_days: Optional[List[int]] = None
    grace_minutes_late: Optional[int] = None
    half_day_hours: Optional[float] = None
    full_day_hours: Optional[float] = None
    overtime_threshold_hours: Optional[float] = None   # deprecated (Iter 77)
    overtime_multiplier: Optional[float] = None        # deprecated (Iter 77)
    ot_allowed: Optional[bool] = None                  # Iter 77 - single toggle
    duty_hours_rounding_minutes: Optional[int] = None  # firm-level; ignored per-employee (Iter 77)
    standard_working_hours: Optional[float] = None
    shift_id: Optional[str] = None
    auto_shift_by_first_punch: Optional[bool] = None  # Iter 77c
    week_off_paid_when_absent: Optional[bool] = None  # Iter 77d
    night_shift_allowance_enabled: Optional[bool] = None
    night_shift_start: Optional[str] = None
    night_shift_end: Optional[str] = None
    notes: Optional[str] = None


@api.get("/admin/employees/{user_id}/attendance-policy-override")
async def get_employee_attendance_policy_override(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    emp = await _load_scoped_employee(user_id, admin_user)
    override = emp.get("attendance_policy_override") or {}
    # For the UI include the current firm-level effective policy for reference.
    company = await db.companies.find_one(
        {"company_id": emp.get("company_id")},
        {"_id": 0, "attendance_policy": 1},
    )
    firm_policy = (company or {}).get("attendance_policy") or {}
    return {
        "user_id": emp["user_id"],
        "name": emp.get("name"),
        "employee_code": emp.get("employee_code"),
        "override": override,
        "firm_policy": firm_policy,
        "has_override": bool(override),
    }


@api.put("/admin/employees/{user_id}/attendance-policy-override")
async def set_employee_attendance_policy_override(
    user_id: str,
    payload: EmployeeAttendancePolicyOverride,
    authorization: Optional[str] = Header(None),
):
    """Save a per-employee attendance policy override. Only non-None fields
    from the payload are stored. Sending an empty body CLEARS the override
    (falls back to group/firm default)."""
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    require_permission(admin_user, "attendance_policy:write")
    emp = await _load_scoped_employee(user_id, admin_user)

    patch = payload.model_dump(exclude_none=True)
    if not patch:
        # Clear the override entirely.
        await db.users.update_one(
            {"user_id": emp["user_id"]},
            {"$unset": {"attendance_policy_override": ""}},
        )
        return {"ok": True, "cleared": True, "override": {}}

    # Basic validation
    if "weekly_off_days" in patch:
        wo = patch["weekly_off_days"] or []
        if any(d < 0 or d > 6 for d in wo):
            raise HTTPException(status_code=400, detail="weekly_off_days must be 0-6")
    if "half_day_hours" in patch and "full_day_hours" in patch:
        if patch["half_day_hours"] >= patch["full_day_hours"]:
            raise HTTPException(status_code=400, detail="half_day_hours must be less than full_day_hours")

    # Merge with the existing override so partial saves work.
    existing = emp.get("attendance_policy_override") or {}
    new_override = {**existing, **patch}
    new_override["updated_at"] = now_iso()
    new_override["updated_by"] = admin_user.get("user_id")

    await db.users.update_one(
        {"user_id": emp["user_id"]},
        {"$set": {"attendance_policy_override": new_override}},
    )
    return {"ok": True, "override": new_override}


@api.delete("/admin/employees/{user_id}/attendance-policy-override")
async def clear_employee_attendance_policy_override(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    """Explicit clear endpoint. Employee falls back to group / firm default."""
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    require_permission(admin_user, "attendance_policy:write")
    emp = await _load_scoped_employee(user_id, admin_user)
    await db.users.update_one(
        {"user_id": emp["user_id"]},
        {"$unset": {"attendance_policy_override": ""}},
    )
    return {"ok": True, "cleared": True}


# ---------------------------------------------------------------------------
# Iter 75 — Employee Group Policies (per-firm attendance/salary templates)
# ---------------------------------------------------------------------------
# A "group" is a per-firm named policy template (e.g. "Worker", "Staff",
# "Office"). Employees can be tagged with a `employee_group` name to
# auto-inherit the policy. When an admin edits a group policy they can
# opt to propagate the changes to every existing member of that group.
#
# NOTE: The group policy is MATERIALISED onto each employee's own
# `employee_policy` on assignment / propagation. This keeps the hot path
# for payroll & attendance (`_get_policy_from_user`) synchronous and
# avoids fanning out a second DB read per employee per pay-run.
#
# Effective policy resolution:
#   employee_policy (explicit override)  >  group_policy (materialised)  >  _default_policy()
#
# Fields intentionally NEVER overwritten during group propagation:
#   • `salary`         — employees usually have unique base pay.
#   • `bio_code`       — per-person biometric enrolment ID.
# Callers may opt in to overwriting salary via `?overwrite_salary=true`.


class EmployeeGroupPolicyIn(BaseModel):
    """Payload for creating / editing a group policy. `name` is required
    on create; every other field is optional and mirrors the same
    per-employee shape used by :class:`EmployeePolicy`."""
    name: Optional[str] = None
    description: Optional[str] = None
    company_id: Optional[str] = None  # super_admin can target any firm
    policy: Optional[Dict[str, Any]] = None


def _sanitise_group_policy(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Filter unknown keys and coerce numeric-ish fields. Keeps the doc
    compact and safe to write back on employees."""
    if not raw:
        return {}
    allowed = set(_default_policy().keys())
    out: Dict[str, Any] = {}
    for k, v in raw.items():
        if k in allowed and v is not None:
            out[k] = v
    return out


NON_PROPAGATED_KEYS = {"salary", "bio_code", "policy_confirmed",
                        "policy_confirmed_at", "policy_confirmed_by"}


async def _resolve_target_company(admin_user: dict, requested: Optional[str]) -> str:
    """Return the company_id the admin is allowed to operate on. Super
    admins may target any firm via `requested`; company admins may only
    operate on their own firm."""
    if admin_user.get("role") == "super_admin":
        cid = requested or admin_user.get("company_id")
        if not cid:
            raise HTTPException(
                status_code=400,
                detail="company_id is required for super_admin group edits.",
            )
        exists = await db.companies.find_one({"company_id": cid}, {"_id": 0, "company_id": 1})
        if not exists:
            raise HTTPException(status_code=404, detail="Company not found")
        return cid
    # Iter 124 — sub admins operate like super admins across ALL firms in
    # their assigned scope (they have no own company_id).
    if admin_user.get("role") == "sub_admin":
        cid = requested or admin_user.get("company_id")
        if not cid:
            raise HTTPException(status_code=400, detail="company_id is required.")
        if not sub_admin_can_touch_company(admin_user, cid):
            raise HTTPException(status_code=403, detail="Firm is outside your assigned scope")
        exists = await db.companies.find_one({"company_id": cid}, {"_id": 0, "company_id": 1})
        if not exists:
            raise HTTPException(status_code=404, detail="Company not found")
        return cid
    cid = admin_user.get("company_id")
    if not cid:
        raise HTTPException(status_code=403, detail="Admin is not scoped to a company.")
    # Iter 75.1 — reject cross-firm access attempts explicitly instead of
    # silently narrowing. Company / sub-admins can only operate on their
    # own firm; a mismatched `requested` cid is a permission error.
    if requested and requested != cid:
        raise HTTPException(status_code=403, detail="Not your firm")
    return cid


@api.get("/admin/employee-groups")
async def list_employee_groups(
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """List group policies for the caller's firm (or the specified firm
    when the caller is a super_admin). Also returns the current member
    count for each group so the UI can show badges."""
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    target_cid = await _resolve_target_company(admin_user, company_id)

    groups = await db.employee_group_policies.find(
        {"company_id": target_cid},
        {"_id": 0},
    ).sort("name", 1).to_list(500)

    # Attach member counts (case-insensitive match on `employee_group`).
    for g in groups:
        gname = g.get("name") or ""
        if gname:
            count = await db.users.count_documents({
                "company_id": target_cid,
                "role": "employee",
                "employee_group": {"$regex": f"^{gname}$", "$options": "i"},
            })
            g["member_count"] = count
        else:
            g["member_count"] = 0

    # Iter 129k (user directive) — every group-wise report/filter offers the
    # General Masters "group" (Employee Type) options too, merged in
    # case-insensitively.
    have = {(g.get("name") or "").strip().upper() for g in groups}
    async for m in db.masters.find(
        {"type": "group", "company_id": {"$in": [target_cid, "__global__", None]}},
        {"_id": 0, "name": 1, "master_id": 1},
    ):
        nm = (m.get("name") or "").strip().upper()
        if nm and nm not in have:
            cnt = await db.users.count_documents({
                "company_id": target_cid,
                "role": "employee",
                "employee_group": {"$regex": f"^{re.escape(nm)}$", "$options": "i"},
            })
            # Iter 499 (user bug: "click on any group — all groups select")
            # ROOT CAUSE: these merged Masters groups were returned WITHOUT a
            # group_id, so every chip carried ``undefined`` → clicking any
            # chip matched ALL chips and the filter param was never sent.
            groups.append({"group_id": m.get("master_id"),
                           "name": nm, "member_count": cnt,
                           "company_id": target_cid})
            have.add(nm)
    # Safety net — NEVER return a group without a usable id.
    for g in groups:
        if not g.get("group_id"):
            g["group_id"] = f"byname:{(g.get('name') or '').strip()}"
    groups.sort(key=lambda g: str(g.get("name") or ""))

    return {"groups": groups, "company_id": target_cid}


@api.post("/admin/employee-groups")
async def create_employee_group(
    payload: EmployeeGroupPolicyIn,
    authorization: Optional[str] = Header(None),
):
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required.")
    target_cid = await _resolve_target_company(admin_user, payload.company_id)

    existing = await db.employee_group_policies.find_one(
        {"company_id": target_cid,
         "name": {"$regex": f"^{name}$", "$options": "i"}},
        {"_id": 0, "group_id": 1},
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A group named '{name}' already exists in this firm.",
        )

    group_id = f"grp_{uuid.uuid4().hex[:12]}"
    doc = {
        "group_id": group_id,
        "company_id": target_cid,
        "name": name,
        "description": (payload.description or "").strip() or None,
        "policy": _sanitise_group_policy(payload.policy),
        "member_count": 0,
        "created_at": now_iso(),
        "created_by": admin_user["user_id"],
        "updated_at": now_iso(),
        "updated_by": admin_user["user_id"],
    }
    await db.employee_group_policies.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "group": doc}


@api.patch("/admin/employee-groups/{group_id}")
async def update_employee_group(
    group_id: str,
    payload: EmployeeGroupPolicyIn,
    propagate: bool = False,
    overwrite_salary: bool = False,
    authorization: Optional[str] = Header(None),
):
    """Edit a group policy. When `propagate=true` the new policy is
    materialised onto every existing member of the group. `salary` and
    `bio_code` are preserved on each employee unless `overwrite_salary`
    is also true (only affects the salary field)."""
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    group = await db.employee_group_policies.find_one({"group_id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    # Scope check
    if admin_user.get("role") != "super_admin":
        if group.get("company_id") != admin_user.get("company_id"):
            raise HTTPException(status_code=403, detail="Group not in your firm")

    updates: Dict[str, Any] = {}
    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Group name cannot be empty.")
        if new_name.lower() != (group.get("name") or "").lower():
            clash = await db.employee_group_policies.find_one({
                "company_id": group["company_id"],
                "name": {"$regex": f"^{new_name}$", "$options": "i"},
                "group_id": {"$ne": group_id},
            }, {"_id": 0, "group_id": 1})
            if clash:
                raise HTTPException(
                    status_code=409,
                    detail=f"Another group named '{new_name}' already exists.",
                )
        updates["name"] = new_name
    if payload.description is not None:
        updates["description"] = payload.description.strip() or None
    if payload.policy is not None:
        updates["policy"] = _sanitise_group_policy(payload.policy)

    if not updates:
        return {"ok": True, "group": group, "propagated_to": 0}

    updates["updated_at"] = now_iso()
    updates["updated_by"] = admin_user["user_id"]
    await db.employee_group_policies.update_one(
        {"group_id": group_id}, {"$set": updates}
    )
    fresh = await db.employee_group_policies.find_one({"group_id": group_id}, {"_id": 0})

    propagated = 0
    if propagate and fresh:
        propagated = await _propagate_group_policy(
            fresh,
            overwrite_salary=overwrite_salary,
            actor=admin_user,
            old_name=(group.get("name") or fresh.get("name") or ""),
        )
    return {"ok": True, "group": fresh, "propagated_to": propagated}


@api.post("/admin/employee-groups/{group_id}/apply")
async def apply_employee_group(
    group_id: str,
    overwrite_salary: bool = False,
    authorization: Optional[str] = Header(None),
):
    """Bulk "Push to members" action — re-syncs every employee in the
    group with the current template. Preserves individual salary unless
    `overwrite_salary=true`."""
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    group = await db.employee_group_policies.find_one({"group_id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if admin_user.get("role") != "super_admin":
        if group.get("company_id") != admin_user.get("company_id"):
            raise HTTPException(status_code=403, detail="Group not in your firm")
    count = await _propagate_group_policy(
        group,
        overwrite_salary=overwrite_salary,
        actor=admin_user,
        old_name=group.get("name") or "",
    )
    return {"ok": True, "propagated_to": count, "group_id": group_id}


@api.delete("/admin/employee-groups/{group_id}")
async def delete_employee_group(
    group_id: str,
    authorization: Optional[str] = Header(None),
):
    """Delete a group template. Members KEEP their materialised policy —
    they simply lose the group link (the `employee_group` label is left
    intact so admins can still find them)."""
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])
    group = await db.employee_group_policies.find_one({"group_id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if admin_user.get("role") != "super_admin":
        if group.get("company_id") != admin_user.get("company_id"):
            raise HTTPException(status_code=403, detail="Group not in your firm")
    await db.employee_group_policies.delete_one({"group_id": group_id})
    return {"ok": True, "deleted_group_id": group_id, "name": group.get("name")}


async def _propagate_group_policy(
    group: Dict[str, Any],
    *,
    overwrite_salary: bool,
    actor: Dict[str, Any],
    old_name: str,
) -> int:
    """Materialise ``group["policy"]`` onto every member of the group.
    Returns the number of employees updated. Called by both PATCH (with
    ``propagate=true``) and the dedicated ``/apply`` endpoint."""
    tpl = _sanitise_group_policy(group.get("policy"))
    if not tpl:
        return 0
    company_id = group["company_id"]
    # Members are matched by the CURRENT group name (case-insensitive) OR
    # the old name — so a rename during PATCH doesn't strand employees.
    name_current = group.get("name") or ""
    names_to_match = {n for n in (name_current, old_name) if n}
    if not names_to_match:
        return 0
    or_clauses = [
        {"employee_group": {"$regex": f"^{n}$", "$options": "i"}}
        for n in names_to_match
    ]
    members = await db.users.find(
        {"company_id": company_id, "role": "employee", "$or": or_clauses},
        {"_id": 0, "user_id": 1, "employee_policy": 1},
    ).to_list(5000)

    updated = 0
    for m in members:
        existing = m.get("employee_policy") or {}
        merged = {**existing, **tpl}
        # Keep individual salary + biometric enrolment unless explicitly opted-in.
        if not overwrite_salary and existing.get("salary") is not None:
            merged["salary"] = existing.get("salary")
        for k in NON_PROPAGATED_KEYS - ({"salary"} if overwrite_salary else set()):
            if k == "salary":
                continue
            if k in existing:
                merged[k] = existing[k]
        merged["policy_source"] = {
            "group_id": group.get("group_id"),
            "group_name": name_current,
            "propagated_at": now_iso(),
            "propagated_by": actor.get("user_id"),
        }
        # Also mirror the salary to legacy fields (payroll loop reads
        # `salary_monthly`).
        set_doc: Dict[str, Any] = {
            "employee_policy": merged,
            # Keep the label consistent with the (possibly renamed) group.
            "employee_group": name_current or existing.get("employee_group"),
        }
        if overwrite_salary and merged.get("salary") is not None:
            set_doc["salary_monthly"] = float(merged["salary"])
        if merged.get("fullday_hours") is not None:
            set_doc["full_day_hrs"] = float(merged["fullday_hours"])
        if merged.get("halfday_hours") is not None:
            set_doc["half_day_hrs"] = float(merged["halfday_hours"])
        r = await db.users.update_one(
            {"user_id": m["user_id"]}, {"$set": set_doc}
        )
        if r.modified_count:
            updated += 1
    # Refresh the group's cached member_count for the UI.
    total_members = await db.users.count_documents({
        "company_id": company_id,
        "role": "employee",
        "employee_group": {"$regex": f"^{name_current}$", "$options": "i"},
    })
    await db.employee_group_policies.update_one(
        {"group_id": group.get("group_id")},
        {"$set": {"member_count": total_members}},
    )
    return updated


async def _apply_group_policy_on_create(
    company_id: str,
    group_name: Optional[str],
    existing_policy: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Called during employee creation. If the employee is assigned to a
    group that exists for the firm, returns the merged policy dict
    (existing per-employee fields win). Returns None when no group is
    matched (caller keeps whatever policy was passed in)."""
    if not group_name:
        return None
    g = await db.employee_group_policies.find_one({
        "company_id": company_id,
        "name": {"$regex": f"^{group_name.strip()}$", "$options": "i"},
    }, {"_id": 0})
    if not g:
        return None
    tpl = _sanitise_group_policy(g.get("policy"))
    if not tpl:
        return None
    existing = existing_policy or {}
    # Employee-level explicit fields win; group fills the gaps.
    # A legitimate `0` is respected — only None / empty string count as "unset".
    merged: Dict[str, Any] = {**tpl}
    for k, v in existing.items():
        if v is None or v == "":
            continue
        merged[k] = v
    merged["policy_source"] = {
        "group_id": g.get("group_id"),
        "group_name": g.get("name"),
        "propagated_at": now_iso(),
        "propagated_by": "employee_create",
    }
    return merged




@api.patch("/admin/user-role")
async def update_user_role(payload: RoleUpdate, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])

    target = await db.users.find_one({"user_id": payload.user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    is_super = user.get("role") == "super_admin"
    is_sub = user.get("role") == "sub_admin"

    # Sub admins edit as per their granted user rights + firm scope.
    if is_sub:
        require_permission(user, "employees:write")
        if not sub_admin_can_touch_company(user, target.get("company_id")):
            raise HTTPException(
                status_code=403,
                detail="Employee's firm is outside your assigned scope",
            )
        if payload.role is not None and payload.role != target.get("role"):
            raise HTTPException(
                status_code=403,
                detail="Only Super Admin can change an employee's role.",
            )
        if payload.company_id is not None and payload.company_id != target.get("company_id"):
            raise HTTPException(
                status_code=403,
                detail="Only Super Admin can reassign an employee to another firm.",
            )
    # Company admins can only edit employees within their own company
    elif not is_super:
        my_company = user.get("company_id")
        if not my_company or target.get("company_id") != my_company:
            raise HTTPException(status_code=403, detail="Not allowed to edit users outside your company")
        # Iter 89 — Reject role / company reassignment attempts from
        # non-super admins EXPLICITLY (previously silently ignored). This
        # protects against any frontend that accidentally sends the field
        # via manual PATCH or curl, and makes the intent obvious in logs.
        if payload.role is not None and payload.role != target.get("role"):
            raise HTTPException(
                status_code=403,
                detail="Only Super Admin can change an employee's role.",
            )
        if payload.company_id is not None and payload.company_id != target.get("company_id"):
            raise HTTPException(
                status_code=403,
                detail="Only Super Admin can reassign an employee to another firm.",
            )

    updates: dict = {}

    # Only super_admin can change role or reassign company
    if is_super:
        if payload.role is not None:
            updates["role"] = payload.role
        if payload.company_id is not None:
            updates["company_id"] = payload.company_id
            updates["onboarded"] = True
            # Admin-assigned company implies approval
            updates["approval_status"] = "approved"
            updates["approved_by"] = user["user_id"]
            updates["approved_at"] = now_iso()

    for k in (
        "department", "position", "employee_code",
        "name", "father_name", "dob", "doj",
        "designation", "present_address", "permanent_address",
        "shift_start", "shift_end",
        "salary_monthly", "half_day_hrs", "full_day_hrs", "exit_date",
    ):
        val = getattr(payload, k)
        if val is not None:
            # Empty string on exit_date means clear it
            if k == "exit_date" and val == "":
                updates[k] = None
            else:
                updates[k] = val

    # is_live_in is a boolean — accept explicit True/False, ignore None
    if payload.is_live_in is not None:
        updates["is_live_in"] = bool(payload.is_live_in)

    # auto_punch_enabled tri-state: None → inherit company (stored as None),
    # True → force on, False → force off. We accept explicit None to clear.
    if hasattr(payload, "auto_punch_enabled"):
        val = getattr(payload, "auto_punch_enabled")
        if val is None:
            # Only clear if the field was explicitly present in the raw body.
            # Pydantic v2 exposes model_fields_set for this check.
            try:
                if "auto_punch_enabled" in payload.model_fields_set:
                    updates["auto_punch_enabled"] = None
            except Exception:
                pass
        else:
            updates["auto_punch_enabled"] = bool(val)

    # Iter 64 — Per-user GPS-punch opt-in. Boolean, default False. Store
    # explicitly so we can distinguish "never opted in" from "opted out".
    if hasattr(payload, "gps_punch_enabled"):
        val = getattr(payload, "gps_punch_enabled")
        if val is not None:
            updates["gps_punch_enabled"] = bool(val)

    # ---- Textile industry per-employee fields ----
    fset = getattr(payload, "model_fields_set", set())
    if "shift_preset_name" in fset:
        v = payload.shift_preset_name
        updates["shift_preset_name"] = (v or "").strip() or None
    if "dummy_shift" in fset:
        v = (payload.dummy_shift or "").strip()
        updates["dummy_shift"] = v or None
    if "ot_applicable" in fset:
        v = payload.ot_applicable
        updates["ot_applicable"] = None if v is None else bool(v)
    if "week_off_full_day" in fset:
        v = payload.week_off_full_day
        updates["week_off_full_day"] = None if v is None else bool(v)
    if "week_off_govt_holiday_enabled" in fset:
        v = payload.week_off_govt_holiday_enabled
        updates["week_off_govt_holiday_enabled"] = None if v is None else bool(v)
    # Iter 207 — per-employee Weekly Off (Employee Master decides when the
    # firm policy keeps Weekly Off = N/A). Empty list / None = firm default.
    if "weekly_off_days_override" in fset:
        v = payload.weekly_off_days_override
        updates["weekly_off_days_override"] = (
            sorted({int(x) for x in v if 0 <= int(x) <= 6}) if v else None
        )

    # ---- Employee grouping fields ----
    # Iter 91 — employee_type and employee_group are UNIFIED: whichever is
    # sent, both columns receive the same value so legacy filters keep
    # working while the UI shows a single "Employee Type / Group" field.
    if "employee_type" in fset or "employee_group" in fset:
        raw = payload.employee_type if "employee_type" in fset else payload.employee_group
        v = (raw or "").strip() if raw is not None else None
        # Cap length + normalise casing (CAPITALS — Iter 129j) so "staff"
        # and "STAFF" collapse into the same distinct suggestion later.
        if v:
            unified = v[:60].strip().upper()
            updates["employee_type"] = unified
            updates["employee_group"] = unified
        else:
            updates["employee_type"] = None
            updates["employee_group"] = None
    if "is_onroll" in fset:
        v = payload.is_onroll
        # Iter 164 — Off-roll requires the firm's 'Offline Salary' (Firm
        # Master → Salary Process Settings) to be enabled.
        if v is False and not await _firm_offline_salary_enabled(target.get("company_id")):
            raise HTTPException(
                status_code=400,
                detail=("Off-roll is not allowed — enable Offline Salary for "
                        "this firm in Firm Master first."))
        # Default treated as True everywhere the field is absent; store
        # explicit True/False so filtering with $eq works cleanly.
        updates["is_onroll"] = None if v is None else bool(v)
    # Iter 200 (user request) — per-employee Offline Salary Yes/No.
    if "offline_salary_enabled" in fset:
        v2 = payload.offline_salary_enabled
        if v2 is not None and not await _firm_offline_salary_enabled(target.get("company_id")):
            raise HTTPException(
                status_code=400,
                detail=("Offline Salary option is not available — enable "
                        "Offline Salary for this firm in Firm Master first."))
        updates["offline_salary_enabled"] = None if v2 is None else bool(v2)
    if "fingerprint_required" in fset and payload.fingerprint_required is not None:
        # Iter 165 — requiring fingerprint needs the firm's Bio Matrix
        # Attendance enabled (Firm Master → Salary Process Settings).
        if payload.fingerprint_required and not await _firm_biometric_attendance_enabled(
                target.get("company_id")):
            raise HTTPException(
                status_code=400,
                detail=("Fingerprint verification is not allowed — enable Bio "
                        "Matrix Attendance for this firm in Firm Master first."))
        updates["fingerprint_required"] = bool(payload.fingerprint_required)
    # Iter 175 — Contractual employee link (Firm Master Policy 2 contractors).
    if "is_contractual" in fset and payload.is_contractual is not None:
        updates["is_contractual"] = bool(payload.is_contractual)
        if not payload.is_contractual:
            updates["contractor_name"] = None
    if "contractor_name" in fset:
        _cn = (payload.contractor_name or "").strip()
        updates["contractor_name"] = _cn or None
    if "advance_balance" in fset:
        v = payload.advance_balance
        try:
            fv = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            fv = 0.0
        # Guard against negative / silly values — advance can only be >= 0.
        updates["advance_balance"] = max(0.0, min(fv, 10_000_000.0))

    # ---- Compliance Salary Process overrides ----
    if "pf_applicable" in fset:
        v = payload.pf_applicable
        updates["pf_applicable"] = None if v is None else bool(v)
    if "esic_applicable" in fset:
        v = payload.esic_applicable
        updates["esic_applicable"] = None if v is None else bool(v)
    for money_key in ("basic_amount", "hra_amount", "conv_amount",
                      "medical_amount", "special_amount", "others_amount",
                      "pt_amount_override", "tds_amount"):
        if money_key in fset:
            v = getattr(payload, money_key)
            if v is None:
                updates[money_key] = None
            else:
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    fv = 0.0
                updates[money_key] = max(0.0, min(fv, 10_000_000.0))
    if "pt_state" in fset:
        v = (payload.pt_state or "").strip()
        # Store as-is; frontend picks from a list of common states, empty
        # clears back to default (no PT).
        updates["pt_state"] = v[:60] if v else None

    # family_members is a list — validate DOB format for each row
    if payload.family_members is not None:
        cleaned: list[dict] = []
        for fm in payload.family_members:
            nm = (fm.name or "").strip()
            if not nm:
                continue
            if fm.dob and not _valid_iso_date(fm.dob):
                raise HTTPException(
                    status_code=400,
                    detail=f"Family member '{nm}' has an invalid DOB — use YYYY-MM-DD.",
                )
            cleaned.append({
                "name": nm,
                "relation": (fm.relation or "").strip() or None,
                "dob": (fm.dob or "").strip() or None,
                "occupation": (fm.occupation or "").strip() or None,
                "contact": (fm.contact or "").strip() or None,
                "aadhaar_no": (fm.aadhaar_no or "").strip() or None,
                "scan_doc_id": (fm.scan_doc_id or "").strip() or None,
            })
        updates["family_members"] = cleaned

    if not updates:
        return target

    r = await db.users.update_one({"user_id": payload.user_id}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    # Iter 114 — FULL MERGE of Employee Type & Employee Group: when the
    # unified group value CHANGES and a policy group template with that
    # name exists for the firm, materialise its policy onto this employee
    # (same semantics as group propagation: template wins, individual
    # salary + non-propagated keys preserved).
    new_group = updates.get("employee_group")
    if new_group and new_group != (target.get("employee_group") or ""):
        grp = await db.employee_group_policies.find_one(
            {"company_id": target.get("company_id"),
             "name": {"$regex": f"^{re.escape(new_group)}$", "$options": "i"}},
            {"_id": 0},
        )
        if grp:
            tpl = _sanitise_group_policy(grp.get("policy"))
            if tpl:
                fresh = await db.users.find_one(
                    {"user_id": payload.user_id}, {"_id": 0, "employee_policy": 1},
                )
                existing = (fresh or {}).get("employee_policy") or {}
                merged = {**existing, **tpl}
                if existing.get("salary") is not None:
                    merged["salary"] = existing.get("salary")
                for k in NON_PROPAGATED_KEYS:
                    if k != "salary" and k in existing:
                        merged[k] = existing[k]
                merged["policy_source"] = {
                    "group_id": grp.get("group_id"),
                    "group_name": grp.get("name"),
                    "propagated_at": now_iso(),
                    "propagated_by": user.get("user_id"),
                }
                set_doc: Dict[str, Any] = {"employee_policy": merged}
                if merged.get("fullday_hours") is not None:
                    set_doc["full_day_hrs"] = float(merged["fullday_hours"])
                if merged.get("halfday_hours") is not None:
                    set_doc["half_day_hrs"] = float(merged["halfday_hours"])
                await db.users.update_one({"user_id": payload.user_id}, {"$set": set_doc})

    return await db.users.find_one({"user_id": payload.user_id}, {"_id": 0})


@api.get("/admin/stats")
async def admin_stats(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    scope_filter: dict = {}
    if user["role"] == "company_admin":
        scope_filter["company_id"] = user.get("company_id")
    elif company_id:
        scope_filter["company_id"] = company_id
    # Iter 136 — sub-admins are stat-scoped to their assigned firms even
    # when no explicit company_id is passed.
    if user["role"] == "sub_admin":
        scope_filter = apply_sub_admin_company_scope(user, scope_filter)

    total_employees = await db.users.count_documents({**scope_filter, "role": "employee"})
    present_today = len(
        await db.attendance.distinct(
            "user_id", {**scope_filter, "date": today, "kind": "in"}
        )
    )
    pending_leaves = await db.leaves.count_documents({**scope_filter, "status": "pending"})
    open_tickets = await db.tickets.count_documents(
        {**scope_filter, "status": {"$in": ["open", "in_progress"]}}
    )
    pending_profile_edits = await db.profile_edit_requests.count_documents(
        {**scope_filter, "status": "pending"},
    )

    # Missed-punch counts (badges on admin action rows).
    #  - open_shifts: employees who punched IN today but never OUT.
    #  - missed_ins: employees currently INSIDE the office geofence
    #                (last-known location within radius, ping < 60 min old)
    #                who have not punched IN today.
    # Mirrors the logic in /admin/attendance/present-not-punched.
    open_shifts_count = 0
    missed_ins = 0
    try:
        # Bucket today's attendance by user
        recs = await db.attendance.find(
            {**scope_filter, "date": today},
            {"_id": 0, "user_id": 1, "kind": 1},
        ).sort("at", 1).to_list(20000)
        by_user: dict[str, list[str]] = {}
        for r in recs:
            by_user.setdefault(r["user_id"], []).append(r["kind"])
        for kinds in by_user.values():
            if kinds and kinds[-1] == "in":
                open_shifts_count += 1

        # Load scoped companies for radius/office lat-lng lookup
        comp_q: dict = {}
        if scope_filter.get("company_id"):
            comp_q["company_id"] = scope_filter["company_id"]
        companies_scoped = await db.companies.find(
            comp_q,
            {"_id": 0, "company_id": 1, "office_lat": 1,
             "office_lng": 1, "geofence_radius_m": 1},
        ).to_list(2000)
        comp_by_id = {c["company_id"]: c for c in companies_scoped}

        threshold = datetime.now(timezone.utc) - timedelta(minutes=60)
        scoped_users = await db.users.find(
            {**scope_filter,
             "role": "employee",
             "last_location_lat": {"$ne": None, "$exists": True},
             "last_location_lng": {"$ne": None, "$exists": True}},
            {"_id": 0, "user_id": 1, "company_id": 1,
             "last_location_lat": 1, "last_location_lng": 1,
             "last_location_at": 1,
             "onboarded": 1, "approval_status": 1, "exit_date": 1},
        ).to_list(20000)
        today_str = today
        for u in scoped_users:
            # Skip inactive / unapproved
            if not u.get("onboarded"):
                continue
            if (u.get("approval_status") or "approved") != "approved":
                continue
            ex = u.get("exit_date")
            if ex and ex <= today_str:
                continue
            # Skip employees who already punched IN
            if u["user_id"] in by_user:
                continue
            comp = comp_by_id.get(u.get("company_id"))
            if not comp:
                continue
            # Ping recency
            last_at = u.get("last_location_at")
            try:
                if isinstance(last_at, str):
                    last_dt = datetime.fromisoformat(
                        last_at.replace("Z", "+00:00")
                    )
                else:
                    last_dt = last_at
                if last_dt and last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
            except Exception:
                last_dt = None
            if not last_dt or last_dt < threshold:
                continue
            # Inside geofence radius
            dist = haversine_m(
                u.get("last_location_lat"), u.get("last_location_lng"),
                comp.get("office_lat") or 0.0, comp.get("office_lng") or 0.0,
            )
            radius = comp.get("geofence_radius_m") or 200
            if dist <= radius:
                missed_ins += 1
    except Exception:
        # Never let a bad count block the whole /admin/stats response.
        logger.exception("[admin_stats] missed-punch aggregation failed")

    total_companies = await db.companies.count_documents({}) if user["role"] == "super_admin" else 0
    return {
        "total_employees": total_employees,
        "present_today": present_today,
        "pending_leaves": pending_leaves,
        "open_tickets": open_tickets,
        "pending_profile_edits": pending_profile_edits,
        "open_shifts": open_shifts_count,
        "missed_ins": missed_ins,
        "total_companies": total_companies,
    }


# ---------------------------------------------------------------------------
# Employee Master PDF + Scan Documents — MOVED to routes/employee_documents.py
# during modularization. The shared scope helper below stays here because
# routes/employee_full_report.py (and the route module) import it from server.
# ---------------------------------------------------------------------------
async def _load_scoped_employee_any_role(user_id: str, admin_user: dict) -> dict:
    """Like _load_scoped_employee but allows non-employee roles too
    (e.g. Master PDF should also work for a company_admin's own record).
    """
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin_user["role"] == "company_admin":
        if emp.get("company_id") != admin_user.get("company_id"):
            raise HTTPException(status_code=403, detail="Employee not in your company")
    return emp


# ---------------------------------------------------------------------------
# Monthly Salary Runs (web portal) — Iteration 54
# Iter 409 — extracted to routes/salary_runs.py (registered below).
# ---------------------------------------------------------------------------

@api.get("/")
async def root():
    return {"app": "S.K. Sharma & Co.", "ok": True}


# Iter 64 — Lightweight liveness / readiness probes for Kubernetes.
# Return instantly without touching the database so deployment health
# checks pass the moment uvicorn is up. Both `/health` and `/healthz`
# are exposed so the platform's checker finds one regardless of the
# convention it uses.
@api.get("/health")
async def health():
    return {"status": "ok"}


# Iter 471 (user request) — SERVER VERSION badge: the portal footer shows
# which code iteration the server is running, so the user can instantly see
# whether their VPS has the latest deploy before testing.
# BUMP THIS on every release (keep in sync with the deploy script number).
APP_ITERATION = "760"


@api.get("/version")
async def app_version():
    return {"iteration": APP_ITERATION}


@api.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Compliance Salary Runs (web portal) — Iteration 56
# Dedicated statutory-side payroll (PF / ESIC / PT / TDS). Runs beside
# the base salary process — completely separate persistence + payslips.
# ---------------------------------------------------------------------------
def _policy2_biometric_stats(att_rows: List[dict], policy: dict, emp_full: dict,
                             company_cfg: Optional[dict] = None) -> dict:
    """Iter 129c — Textile *Policy 2* firms: auto-sync Present Days for the
    Compliance Salary run from the SAME biometric pipeline as the
    attendance grid (``compute_textile_day``: 8 hrs = 1 day, under-hours
    and week-off work → OT). Only APPROVED punches count, with the grid's
    dedupe / bounce-merge / cross-day stitching applied so numbers match.

    OT hours are intentionally returned as 0 — OT is paid via the separate
    OT Salary Process (user directive), keeping it OUT of the compliance
    gross to avoid double payment.
    """
    by_day: Dict[str, List[dict]] = {}
    for r in att_rows or []:
        st = r.get("status")
        if st and st != "approved":
            continue
        d = r.get("date")
        if d:
            by_day.setdefault(d, []).append(r)
    by_day = stitch_cross_day_ot(dedupe_close_punches(by_day, company_cfg=company_cfg),
                                 company_cfg=company_cfg)
    present = 0.0
    duty_min = 0.0
    for date_key, punches in by_day.items():
        try:
            wd = datetime.strptime(date_key, "%Y-%m-%d").weekday()
        except (ValueError, TypeError):
            continue
        punches = dedupe_rapid_punches(punches, 30)
        punches = dedupe_same_machine_punches(punches, 15)
        punches = merge_out_in_bounces(punches, 60)
        if has_unpaired_punches(punches):
            continue
        s = compute_textile_day(punches, apply_weekoff_rules_for_date(policy, emp_full, date_key), emp_full, wd)
        present += float(s.get("present_days") or 0)
        duty_min += float(s.get("duty_minutes") or 0)
    return {
        "present_days": int(present),
        "half_days": 0,
        "effective_present": round(present, 2),
        "duty_hours": round(duty_min / 60.0, 2),
        "ot_hours": 0.0,
    }



# ---------------------------------------------------------------------------
# Attendance Sheet Automation endpoints — Iter 58 (renamed from "master-sheet")
# ---------------------------------------------------------------------------
# The utility layer lives in utils/master_sheet.py (module name kept for
# backward compat). These endpoints wrap it for the Super Admin's monthly
# workflow:
#   • generate → produce the pre-populated XLSX for a company+month
#                (optionally filtered by Employee Group)
#   • upload   → parse client's returned XLSX and run column matching
#   • import   → apply a confirmed mapping and stage per-employee values
#   • ecr / esic → download EPFO / ESIC challan files for a compliance run
# NOTE: legacy `/admin/master-sheet/*` routes are preserved as aliases so
# any deep links / cached URLs keep working.


class MasterSheetImport(BaseModel):
    """Import staged rows keyed by canonical field names."""
    company_id: str
    month: str
    rows: List[Dict[str, Any]]


class MasterSheetMap(BaseModel):
    """Body for /attendance-sheet/apply-mapping. `mapping` is the confirmed
    canonical_field → source_column_index picked by the super admin."""
    company_id: str
    month: str
    headers: List[str]
    body: List[List[Any]]
    mapping: Dict[str, int]


async def _resolve_group_employee_ids(company_id: str, group_id: Optional[str]) -> Optional[List[str]]:
    """If group_id is provided, return the list of user_ids in that group.
    Returns None when no filter is required (group_id empty).

    Iter 77 - Groups can live in TWO different collections:
      1. Legacy ``db.masters`` (type=group, ``member_user_ids`` array)
      2. New   ``db.employee_group_policies`` (group_id + group_name; each
         employee stores the group name in ``users.employee_group``)
    We try masters first, fall back to employee_group_policies.
    """
    if not group_id:
        return None
    # Iter 499 — synthetic name-based ids (``byname:<NAME>``) from the
    # employee-groups list endpoint: match directly on the group name.
    if group_id.startswith("byname:"):
        nm = group_id[len("byname:"):].strip()
        if not nm:
            return []
        rx = {"$regex": f"^{re.escape(nm)}$", "$options": "i"}
        docs = await db.users.find(
            {"company_id": company_id, "role": "employee",
             "$or": [{"employee_group": rx}, {"employee_type": rx}]},
            {"_id": 0, "user_id": 1},
        ).to_list(4000)
        return [u["user_id"] for u in docs]
    grp = await db.masters.find_one(
        {"master_id": group_id, "type": "group",
         # Iter 412 (user bug: group-wise sheet blank) — legacy masters can
         # carry company_id None; include them like the list endpoints do.
         "company_id": {"$in": [company_id, "__global__", None]}},
        {"_id": 0, "member_user_ids": 1, "name": 1},
    )
    if grp is not None:
        ids = list(grp.get("member_user_ids") or [])
        if ids:
            # Iter 412 (user bug: group-wise sheet blank) — PROD ROOT CAUSE:
            # global "category" groups (LABOUR/STAFF…) can carry a stale
            # member list pointing at ANOTHER firm's employees. Keep only
            # members of THIS firm; if none remain, fall through to the
            # name-match below instead of returning a blank report.
            docs = await db.users.find(
                {"user_id": {"$in": ids}, "company_id": company_id,
                 "role": "employee"},
                {"_id": 0, "user_id": 1},
            ).to_list(4000)
            valid = [d["user_id"] for d in docs]
            if valid:
                return valid
        # Iter 101 — global/legacy master groups often have NO explicit
        # members; they are categories. Fall back to name-matching the
        # employees' employee_group / employee_type fields (e.g. the
        # "Staff" group matches employee_type="Staff").
        name = (grp.get("name") or "").strip()
        if not name:
            return []
        rx = {"$regex": f"^{re.escape(name)}$", "$options": "i"}
        users = await db.users.find(
            {"company_id": company_id, "role": "employee",
             "$or": [{"employee_group": rx}, {"employee_type": rx}]},
            {"_id": 0, "user_id": 1},
        ).to_list(4000)
        return [u["user_id"] for u in users]
    # Fallback to the Employee Group Policies system.
    egp = await db.employee_group_policies.find_one(
        {"group_id": group_id, "company_id": company_id},
        {"_id": 0, "name": 1, "group_name": 1},
    )
    if not egp:
        return []
    grp_name = (egp.get("name") or egp.get("group_name") or "").strip()
    if not grp_name:
        return []
    # Iter 412 (user bug: group-wise sheet blank) — match case-insensitively
    # on BOTH employee_group AND employee_type (legacy imports only fill
    # employee_type), exactly like the masters name-fallback above.
    rx = {"$regex": f"^{re.escape(grp_name)}$", "$options": "i"}
    ids = await db.users.find(
        {"company_id": company_id, "role": "employee",
         "$or": [{"employee_group": rx}, {"employee_type": rx}]},
        {"_id": 0, "user_id": 1},
    ).to_list(4000)
    return [u["user_id"] for u in ids]


# ---------------------------------------------------------------------------
# Iter 68 — Monthly attendance reports (Working Hours + IN/OUT sheet)
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Iter 77 - ZKTeco .dat biometric punch upload (Web Portal)
# ---------------------------------------------------------------------------
@api.get("/admin/attendance/import-sample")
async def attendance_import_sample(authorization: Optional[str] = Header(None)):
    """Sample Excel format for the IN/OUT attendance import."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    import io as _io
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "IN or OUT punches"
    ws.append(["CODE", "DATE", "TIME"])
    ws.append(["901", "10-07-2026", "09:02"])
    ws.append(["902", "10-07-2026", "09:10:35"])
    ws.append(["105", "11-07-2026", "18:04"])
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 12
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="attendance_import_sample.xlsx"'},
    )


@api.post("/admin/attendance/zk-dat-import")
async def upload_zk_dat(
    company_id: str = Form(...),
    from_date: Optional[str] = Form(None),
    to_date: Optional[str] = Form(None),
    in_file: Optional[UploadFile] = File(None),
    out_file: Optional[UploadFile] = File(None),
    combined_file: Optional[UploadFile] = File(None),
    in_excel: Optional[UploadFile] = File(None),
    out_excel: Optional[UploadFile] = File(None),
    # Iter 224 (user rule) — machine data already present is NOT replaced
    # without permission; the UI prompts and re-submits with "1".
    replace_existing: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
):
    """Upload ZKTeco ``.dat`` files (IN, OUT, or combined) AND/OR Excel
    sheets (IN punches separate, OUT punches separate — columns
    CODE | DATE | TIME) and ingest the punches into ``db.attendance``.
    Same idempotency guard as the CLI script - re-uploading is safe."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin.get("role") == "sub_admin":
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    if admin.get("role") == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="You can only import into your firm")

    if not (in_file or out_file or combined_file or in_excel or out_excel):
        raise HTTPException(
            status_code=400,
            detail="Upload at least one file (.dat IN/OUT/combined or Excel IN/OUT).",
        )
    if from_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", from_date):
        raise HTTPException(status_code=400, detail="from_date must be YYYY-MM-DD")
    if to_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", to_date):
        raise HTTPException(status_code=400, detail="to_date must be YYYY-MM-DD")

    from utils.zk_dat_import import (
        import_zk_dat_bytes, excel_punches_to_dat_text,
        is_genlog_dat, genlog_to_txt_text,
    )
    in_b = await in_file.read() if in_file else None
    out_b = await out_file.read() if out_file else None
    combo_b = await combined_file.read() if combined_file else None

    # Iter 139 — Binary GENLOG .DAT device backups are converted to the
    # tab-separated device .TXT shape up-front so the SAME text is both
    # imported and persisted (the "Refresh Bio" re-read needs re-parsable
    # text, not raw binary).
    def _bin2txt(b: Optional[bytes]) -> Optional[bytes]:
        if b and is_genlog_dat(b):
            return genlog_to_txt_text(b).encode("utf-8")
        return b
    in_b, out_b, combo_b = _bin2txt(in_b), _bin2txt(out_b), _bin2txt(combo_b)

    # Iter 106 — Excel IN/OUT sheets: converted into .dat-shaped text and
    # merged into the same pipeline (mapping, dedupe, range filter).
    def _merge(dat: Optional[bytes], xls_text: str) -> bytes:
        return ((dat.decode("utf-8", errors="replace") + "\n" if dat else "")
                + xls_text).encode("utf-8")
    try:
        if in_excel:
            in_b = _merge(in_b, excel_punches_to_dat_text(
                await in_excel.read(), in_excel.filename or ""))
        if out_excel:
            out_b = _merge(out_b, excel_punches_to_dat_text(
                await out_excel.read(), out_excel.filename or ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Excel parse error: {e}")

    stats = await import_zk_dat_bytes(
        db,
        company_id=company_id,
        in_bytes=in_b,
        out_bytes=out_b,
        combined_bytes=combo_b,
        from_date=from_date,
        to_date=to_date,
        source_tag=f"import:zk_web_{admin.get('user_id','')[:8]}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}",
        on_existing="replace" if str(replace_existing or "").strip() in ("1", "true", "yes") else "skip",
    )
    # Iter 93 — Persist the raw .dat content so the "Refresh Bio" button on
    # the Attendance Report can RE-READ old imports after bio-code fixes in
    # the Employee Master (previously-unmapped punches get recovered).
    _MAX_DAT_CHARS = 4_000_000  # ~4 MB per file, well under Mongo's 16 MB doc cap
    def _dec(b: Optional[bytes]) -> Optional[str]:
        if not b:
            return None
        return b.decode("utf-8", errors="replace")[:_MAX_DAT_CHARS]
    await db.zk_dat_imports.insert_one({
        "import_id": f"zkdat_{uuid.uuid4().hex[:12]}",
        "company_id": company_id,
        "uploaded_by": admin.get("user_id"),
        "uploaded_at": now_iso(),
        "from_date": from_date,
        "to_date": to_date,
        "source_tag": stats.get("source_tag"),
        "in_text": _dec(in_b),
        "out_text": _dec(out_b),
        "combined_text": _dec(combo_b),
        "last_stats": {k: v for k, v in stats.items() if k != "unmapped_bio_codes"},
    })
    logger.info(f"[zk-dat-import] cid={company_id} by={admin.get('user_id')} stats={stats}")
    # Iter 77n — real-time broadcast so admin dashboards on the firm
    # refresh their attendance grid the moment the import finishes.
    try:
        from utils.ws_broker import broker as _ws
        await _ws.broadcast_firm(company_id, {
            "type": "attendance.dat-imported",
            "from_date": from_date,
            "to_date": to_date,
            "inserted": stats.get("inserted") or stats.get("added"),
            "seen": stats.get("seen") or stats.get("total"),
            "by": admin.get("name") or admin.get("user_id"),
        })
    except Exception:
        pass
    return stats


# ---------------------------------------------------------------------------
# Iter 76 — JSON grid for the on-screen Monthly Attendance viewer.
# ---------------------------------------------------------------------------
def _classify_punch_source(src: Optional[str]) -> str:
    """Bucket the free-form `attendance.source` field into three UI badges:
    - "bio" : ZKTeco biometric device push
    - "app" : Mobile app punch (manual, geofence-auto, GPS-verified, etc.)
    - "sys" : Server / admin generated (auto-close, admin approved, roster)
    """
    s = (src or "").lower()
    if not s:
        return "app"
    if s.startswith("zkteco") or s.startswith("import") or "biometric" in s:
        return "bio"
    if s.startswith("admin") or "server" in s or "roster" in s or "system" in s:
        return "sys"
    # manual, manual-nogps, auto, geofence-auto, mobile, etc.
    return "app"


@api.get("/admin/attendance/monthly-grid/{company_id}/{month}")
async def monthly_attendance_grid_json(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    skip: int = 0,
    limit: Optional[int] = None,
    authorization: Optional[str] = Header(None),
):
    """Return the same per-employee x per-day punch data the XLSX endpoints
    use, but as JSON so the web portal can render a live grid.

    Query params:
      - ``from_date`` / ``to_date`` (YYYY-MM-DD): when BOTH are supplied,
        they override the ``{month}`` path parameter and the response spans
        the exact date range (useful for verifying mobile-app punches for a
        single day or arbitrary reporting window).

    Each day cell now includes ``sources`` (list of unique badges among
    ``"bio"``, ``"app"``, ``"sys"``) so the client can render Mobile vs
    Biometric provenance indicators.
    """
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    if admin.get("role") == "sub_admin":
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    if admin.get("role") == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="You can only view your own firm")
    data = await _compute_monthly_grid_data(
        company_id=company_id,
        month=month,
        group_id=group_id,
        from_date=from_date,
        to_date=to_date,
    )
    # Iter 726 (perf phase 2 — user spec): OPTIONAL server-side pagination.
    # The full grid stays cached (footer totals remain firm-wide); only the
    # employee rows are sliced so the first paint of a 5000-employee firm
    # ships a small payload and the rest streams in follow-up chunks.
    if limit is not None and limit > 0:
        _all_rows = data.get("employees") or []
        _skip = max(0, int(skip or 0))
        data["total_rows"] = len(_all_rows)
        data["skip"] = _skip
        data["employees"] = _all_rows[_skip:_skip + int(limit)]
    return data


# Iter 705 (user issue — Attendance Report slow even with 277 employees):
# the full month grid (punch pairing/dedup/stitching per employee) was
# recomputed on EVERY open of the Attendance Report / In-Out report /
# exports. Cache the computed grid per (company, month, filters) for a
# short TTL. The cache stores the JSON-serialised result and returns a
# fresh object on every hit, so callers can safely mutate what they get.
_MG_CACHE: Dict[str, Any] = {}
_MG_TTL_SEC = 90.0
_MG_STALE_MAX = 1800.0          # serve stale instantly up to 30 min old
_MG_REFRESHING: set = set()     # in-flight background refreshes


def invalidate_grid_cache(company_id: str) -> None:
    """Iter 710 — drop cached grids for a firm after ANY manual punch /
    OT repair so duty HRS recalculates immediately (user bug report)."""
    for k in list(_MG_CACHE.keys()):
        if k.startswith(f"{company_id}|"):
            _MG_CACHE.pop(k, None)


async def _mg_dirty(company_id: str, since_epoch: float) -> bool:
    """Cheap probe: was ANY attendance record inserted after the cache was
    built? Catches punch repairs / manual punches / OT additions / imports."""
    try:
        doc = await db.attendance.find_one(
            {"company_id": company_id}, {"_id": 0, "created_at": 1},
            sort=[("created_at", -1)])
        if not doc or not doc.get("created_at"):
            return False
        ts = datetime.fromisoformat(
            str(doc["created_at"]).replace("Z", "+00:00")).timestamp()
        return ts > since_epoch
    except Exception:
        return False


async def _compute_monthly_grid_data(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    _key = f"{company_id}|{month}|{group_id or ''}|{from_date or ''}|{to_date or ''}"

    def _kick_refresh() -> None:
        """Recompute this grid in the BACKGROUND (one in-flight per key)."""
        if _key in _MG_REFRESHING:
            return
        _MG_REFRESHING.add(_key)

        async def _refresh():
            try:
                d = await _compute_monthly_grid_data_impl(
                    company_id=company_id, month=month, group_id=group_id,
                    from_date=from_date, to_date=to_date)
                _MG_CACHE[_key] = (_time_mod.time(),
                                   json.dumps(d, default=str))
            except Exception:
                pass
            finally:
                _MG_REFRESHING.discard(_key)

        try:
            asyncio.create_task(_refresh())
        except Exception:
            _MG_REFRESHING.discard(_key)

    _hit = _MG_CACHE.get(_key)
    if _hit:
        _age = _time_mod.time() - _hit[0]
        if _age < _MG_STALE_MAX:
            # Iter 714 (user: "report taking too much time AGAIN") — the old
            # dirty-check WIPED the cache and forced a FULL synchronous
            # recompute whenever ANY new attendance row existed. On the live
            # VPS biometric punches stream in all day, so nearly every open
            # recomputed the whole grid on the spot. Now the report ALWAYS
            # opens instantly from cache (≤30 min old) and a background
            # refresh brings in the new punches for the next open. Manual
            # punch repairs still call invalidate_grid_cache() explicitly,
            # so corrections keep appearing immediately (Iter 710 fix).
            if _age >= _MG_TTL_SEC or await _mg_dirty(company_id, _hit[0]):
                _kick_refresh()
            return json.loads(_hit[1])
        _MG_CACHE.pop(_key, None)
    data = await _compute_monthly_grid_data_impl(
        company_id=company_id, month=month, group_id=group_id,
        from_date=from_date, to_date=to_date)
    try:
        _MG_CACHE[_key] = (_time_mod.time(), json.dumps(data, default=str))
        if len(_MG_CACHE) > 30:
            _oldest = min(_MG_CACHE, key=lambda k: _MG_CACHE[k][0])
            _MG_CACHE.pop(_oldest, None)
    except Exception:
        pass
    return data


# Iter 708 (user issue — "Monthly Attendance must open IMMEDIATELY"):
# warm the current-month grid cache for every active firm on startup and
# keep it fresh, so even the FIRST open after a backend restart serves from
# cache instead of computing 5000 employees on the spot.
async def _bg_warm_monthly_grid():
    await asyncio.sleep(20)          # let startup settle first
    while True:
        try:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            cids = await db.users.distinct("company_id", {"role": "employee"})
            for cid in cids:
                if not cid:
                    continue
                try:
                    await _compute_monthly_grid_data(company_id=cid, month=month)
                except Exception:
                    pass
                await asyncio.sleep(1)
        except Exception:
            pass
        await asyncio.sleep(600)     # refresh every 10 minutes


async def _compute_monthly_grid_data_impl(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    only_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Iter 77x — Extracted compute pipeline used by BOTH the JSON grid
    endpoint and the Grid-View XLSX endpoint. Caller is expected to have
    already performed authz checks. Runs the same bounce-merge, dedup,
    OT cap, weekly-off + cross-day-OT pairing logic that powers the
    on-screen Grid View so any Excel export matches 1:1.
    """
    from utils.monthly_attendance import _pair_punches  # reuse the pairing loop


    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "company_id": 1, "name": 1, "attendance_policy": 1,
         "attendance_config": 1},
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    # -------------------------------------------------------------------
    # Resolve the reporting window.
    #  * Custom range: both from_date and to_date supplied and valid.
    #  * Otherwise fall back to the whole {month}.
    # -------------------------------------------------------------------
    import calendar as _cal
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    range_mode = bool(
        from_date and to_date
        and date_re.match(from_date) and date_re.match(to_date)
    )
    if range_mode:
        try:
            d_from = datetime.strptime(from_date, "%Y-%m-%d").date()
            d_to = datetime.strptime(to_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="from_date / to_date must be YYYY-MM-DD") from exc
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        date_from = d_from.isoformat()
        date_to = d_to.isoformat()
        # Iterate day-by-day so we handle month boundaries + variable day counts.
        day_iter: List[Tuple[int, int, int]] = []
        cur = d_from
        while cur <= d_to:
            day_iter.append((cur.year, cur.month, cur.day))
            cur += timedelta(days=1)
        # For DOJ pre-filter we anchor to the FROM month.
        month = f"{d_from.year:04d}-{d_from.month:02d}"
    else:
        try:
            y, m = int(month[:4]), int(month[5:7])
            if m < 1 or m > 12:
                raise ValueError
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="month must be YYYY-MM") from exc
        days_in_month = _cal.monthrange(y, m)[1]
        date_from = f"{y:04d}-{m:02d}-01"
        date_to = f"{y:04d}-{m:02d}-{days_in_month:02d}"
        day_iter = [(y, m, d) for d in range(1, days_in_month + 1)]

    # Iter 204 — per-day APPROVED shift assignments (Shift Change module).
    _daily_shift_ovr = await load_daily_shift_overrides(company_id, date_from, date_to)

    # ----- Employees in scope --------------------------------------------
    query: Dict[str, Any] = {"role": "employee", "company_id": company_id}
    if only_user_id:
        # Employee self-view (/attendance/my-month) — compute for ONE user.
        query["user_id"] = only_user_id
    grp_uids = await _resolve_group_employee_ids(company_id, group_id)
    if grp_uids is not None:
        query["user_id"] = {"$in": grp_uids}
    employees = await db.users.find(
        query,
        {
            "_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
            "father_name": 1, "department": 1, "position": 1,
            "designation": 1, "doj": 1,
            "bio_code": 1, "employee_group": 1,
            "exit_date": 1, "resign_date": 1, "date_of_leaving": 1,
            "leaving_date": 1, "employment_status": 1, "disabled": 1, "active": 1,
        },
    ).sort([("employee_code", 1), ("name", 1)]).to_list(4000)
    employees = [e for e in employees if not _month_is_before_doj(e, month)]
    # Iter 321 (user request) — ACTIVE employees only on attendance reports
    # (grid + all XLSX/PDF exports). Self-view is exempt.
    if not only_user_id:
        employees = [e for e in employees if not _employee_inactive_for_report(e, month)]

    # ----- Punches for those employees in the target window -------------
    punches_by_user_day: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    if employees:
        user_ids = [e["user_id"] for e in employees]
        # Iter 486 (user bug — "Still Facing Issue") — CROSS-MONTH night
        # shifts: load ±1 day around the window so a night-shift OUT that
        # lands on the 1st can stitch back to the previous month's last
        # day (and the last day's OUT on the 1st of next month is found).
        # Out-of-range day keys are dropped again after stitching.
        _q_from = (datetime.strptime(date_from, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        _q_to = (datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        async for r in db.attendance.find(
            # Iter 83-final — Per user rule: only APPROVED punches count
            # toward the attendance grid / IN-OUT sheet. Pending punches
            # are held until an admin reviews them, and rejected ones are
            # never counted. ``manual_admin`` inserts and admin PATCH
            # edits already set ``status="approved"`` automatically so
            # they're included seamlessly.
            {"user_id": {"$in": user_ids},
             "date": {"$gte": _q_from, "$lte": _q_to},
             "status": "approved"},
            {"_id": 0, "user_id": 1, "date": 1, "kind": 1, "at": 1, "source": 1},
        ).sort([("user_id", 1), ("at", 1)]):
            uid = r["user_id"]
            punches_by_user_day.setdefault(uid, {}).setdefault(r["date"], []).append(r)
        # Iter 481 (user request) — drop 5-min duplicate machine punches
        # and repair corrupted IN/OUT alternation BEFORE cross-day stitch.
        # Iter 77y — Stitch cross-day OT (night-shift OUT punches that
        # land on the next calendar day get moved back to the day the
        # session started so the OT window can be paired correctly).
        for _uid_key in list(punches_by_user_day.keys()):
            _repaired = stitch_cross_day_ot(
                dedupe_close_punches(
                    punches_by_user_day[_uid_key],
                    company_cfg=company.get("attendance_config"),
                ),
                company_cfg=company.get("attendance_config"),
            )
            # Drop the ±1-day helper keys after stitching (Iter 486).
            punches_by_user_day[_uid_key] = {
                dk: v for dk, v in _repaired.items()
                if date_from <= dk <= date_to
            }

    # ----- Working-hour thresholds for OT calculation --------------------
    pol = company.get("attendance_policy") or {}
    pol = await inject_firm_ot_flag(dict(pol), company.get("company_id"))
    # Iter 503 — Single Machine Mode firm config (fixed-lunch hours hook).
    _smm_cfg = company.get("attendance_config") or {}
    _smm_fixed_lunch = (
        int(_smm_cfg.get("lunch_fixed_min") or 30)
        if (str(_smm_cfg.get("device_mode") or "") == "single_machine"
            and str(_smm_cfg.get("lunch_mode") or "") == "fixed")
        else 0
    )
    full_day_hours = float(pol.get("full_day_hours") or 8.0)
    # Iter 202 (user request) — "Count Present Day @ 8 HRS" sub-point:
    # when ON (and Salary Allowed includes Compliance), the Day-wise
    # IN/OUT, OT IN/OUT and HRS-Only reports split regular duty vs OT at
    # 8 hrs — 10 worked hrs show as 8 duty + 2 OT.
    _pm_8hr_reports = bool(
        (pol.get("policy_master") or {}).get("compliance_present_8hr")
        and (pol.get("salary_allowed") or "both") in ("compliance", "both")
    )
    # Iter 202 — firm-level Policy Master flags for the policy-based
    # "Present Days" column (user request: every report shows Present Days
    # calculated per the firm's attendance policy).
    _pm_firm = pol.get("policy_master") or {}
    # Iter 538 (user rule) — PUNCH-SEQUENCE mode rides on the existing
    # "Attendance Calculation as per Duty HRS" policy sub-point:
    #   • duplicate punches of the same kind within 5 min are ignored;
    #   • 1st IN → OUT pair = FULL Duty HRS (no arithmetic 8-hr split);
    #   • any punch AFTER that OUT = OT IN, its partner (incl. the
    #     next-morning OUT via cross-day stitching) = OT OUT;
    #   • Days = Total Duty HRS ÷ Daily Duty HRS (division mode below).
    _pm_seq_mode = bool(_pm_firm.get("attendance_by_duty_hours"))
    # Iter 200 — Holiday Master dates (for holiday_present_add_ot).
    _holiday_dates = await holiday_dates_for_company(company_id)
    # Iter 77e — Load the GLOBAL Shift Master catalogue once so we can
    # resolve per-employee shift overrides for every day compute.
    shifts_by_id, shifts_list = await load_shift_masters_map()
    # Pull the FULL employee doc for the compute helper (need override).
    if employees:
        full_emp_docs = await db.users.find(
            {"user_id": {"$in": [e["user_id"] for e in employees]}},
            {
                "_id": 0, "user_id": 1, "attendance_policy_override": 1,
                "ot_applicable": 1, "week_off_full_day": 1,
                "week_off_govt_holiday_enabled": 1,
                # Iter 207 — per-employee Weekly Off from Employee Master.
                "weekly_off_days_override": 1,
                # Iter 94 — salary fields for the day-wise salary report.
                "salary_monthly": 1, "salary_mode": 1,
                "salary_structure_actual": 1,
            },
        ).to_list(4000)
        full_emp_by_id = {u["user_id"]: u for u in full_emp_docs}
    else:
        full_emp_by_id = {}

    # ----- Weekday labels (+ optional date labels for range mode) --------
    weekday_short = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_labels: List[str] = []
    day_labels: List[str] = []
    day_full_dates: List[str] = []
    for (yy, mm, dd) in day_iter:
        weekday_labels.append(weekday_short[datetime(yy, mm, dd).weekday()])
        if range_mode:
            # Show DD when the whole range sits inside one month, else MM-DD
            same_month = day_iter[0][:2] == day_iter[-1][:2]
            day_labels.append(f"{dd:02d}" if same_month else f"{mm:02d}-{dd:02d}")
        else:
            day_labels.append(f"{dd:02d}")
        day_full_dates.append(f"{yy:04d}-{mm:02d}-{dd:02d}")

    # ----- Build per-employee day cells ----------------------------------
    rows: List[Dict[str, Any]] = []
    # Iter 94 — day-wise salary totals across all employees (bottom row)
    # + monthly divisor for monthly-rate employees.
    day_salary_totals: Dict[str, float] = {}
    # Iter 291 (user request) — day-wise PRESENT COUNT bottom row for the
    # In/Out and HRS reports.
    day_present_counts: Dict[str, int] = {}
    _md_divisor = _cal.monthrange(day_iter[0][0], day_iter[0][1])[1] if day_iter else 30
    # Iter 94 — Additional Duty HRS entries (Punch Approvals) keyed by
    # (user_id, YYYY-MM-DD); the hours merge into that day's duty.
    _extra_by_key: Dict[Tuple[str, str], float] = {}
    if day_iter:
        _xd_from = f"{day_iter[0][0]:04d}-{day_iter[0][1]:02d}-{day_iter[0][2]:02d}"
        _xd_to = f"{day_iter[-1][0]:04d}-{day_iter[-1][1]:02d}-{day_iter[-1][2]:02d}"
        _xd = await db.extra_duty_entries.find(
            {"company_id": company_id, "date": {"$gte": _xd_from, "$lte": _xd_to}},
            {"_id": 0, "user_id": 1, "date": 1, "extra_hours": 1},
        ).to_list(5000)
        for en in _xd:
            h = float(en.get("extra_hours") or 0.0)
            if h != 0:
                _extra_by_key[(en["user_id"], en["date"])] = h
    for e in employees:
        uid = e["user_id"]
        # Iter 77e - Merge lite-employee dict (from `employees` list) with
        # the full doc that carries `attendance_policy_override` so
        # compute_textile_day can honour per-employee cap + shift.
        emp_full = {**e, **full_emp_by_id.get(uid, {})}
        # Iter 77p — Resolve the DAILY WORKING HRS divisor for this
        # employee: override wins, else assigned shift's length, else
        # firm-level default. Used ONLY for the Days = Hours/Divisor
        # column at the row summary; does not affect the per-day compute.
        _ov = (emp_full.get("attendance_policy_override") or {})
        emp_daily_hrs = float(
            _ov.get("standard_working_hours")
            or 0
        )
        if emp_daily_hrs <= 0:
            # Fall back to assigned-shift duration if any, else firm.
            _shift = None
            if _ov.get("shift_id"):
                _shift = shifts_by_id.get(_ov.get("shift_id"))
            _sh_hrs = _shift_duration_hours(_shift) if _shift else None
            emp_daily_hrs = float(_sh_hrs or full_day_hours or 8.0)
        # Iter 520 — effective weekly-off weekday set for THIS employee
        # (per-employee override replaces the firm policy list) so days
        # WITHOUT punches can still be flagged Weekly Off / Holiday on
        # the grid + In/Out & OT Matrix (per the firm attendance policy).
        _wo_emp_lst = emp_full.get("weekly_off_days_override")
        if isinstance(_wo_emp_lst, list) and len(_wo_emp_lst) > 0:
            _emp_weekoffs = {int(x) for x in _wo_emp_lst
                             if isinstance(x, (int, float)) and 0 <= int(x) <= 6}
        else:
            _emp_weekoffs = {int(x) for x in (pol.get("weekly_off_days") or [])
                             if isinstance(x, (int, float)) and 0 <= int(x) <= 6}
        by_day = punches_by_user_day.get(uid, {})
        days_cell: Dict[str, Dict[str, Any]] = {}
        total_present_days = 0
        total_present_policy = 0.0  # Iter 202 — policy-based Present Days
        # Iter 205 — CLOCK-accurate totals: accumulate whole MINUTES so
        # monthly totals equal the exact sum of the displayed HH:MM cells
        # (no decimal-rounding drift).
        total_hours_min = 0
        total_ot_min = 0
        total_duty_only_min = 0   # Iter 77s — duty excluding OT
        # Iter 236 — Attendance Engine Overhaul summary accumulators.
        total_punches_cnt = 0
        total_break_min = 0
        total_net_min = 0
        total_late_min = 0
        total_early_min = 0
        # ---- Iter 94 — day-wise salary (mirrors _actual_salary_row_compute
        # rate resolution: Basic row on salary_structure_actual overrides
        # salary_monthly; rate_type overrides salary_mode). ---------------
        _sal_basic = float(emp_full.get("salary_monthly") or 0.0)
        _sal_mode = str(emp_full.get("salary_mode") or "monthly").lower()
        _sal_struct = [r for r in (emp_full.get("salary_structure_actual") or []) if isinstance(r, dict)]
        _sal_brow = next(
            (r for r in _sal_struct
             if str(r.get("head", "")).strip().lower().startswith("basic")),
            None,
        )
        if _sal_brow and float(_sal_brow.get("amount") or 0.0) > 0:
            _sal_basic = float(_sal_brow.get("amount") or 0.0)
            _rt = str(_sal_brow.get("rate_type") or "").strip().lower()
            if _rt in ("monthly", "daily", "hourly"):
                _sal_mode = _rt
        total_salary = 0.0
        for idx, (yy, mm, dd) in enumerate(day_iter):
            date_key_iso = f"{yy:04d}-{mm:02d}-{dd:02d}"
            key = day_labels[idx]  # what the frontend uses as dict key
            day_punches = by_day.get(date_key_iso) or []
            # Iter 276 (user request) — ignore multiple punches within
            # seconds (double-scans) and auto-rectify before any pairing.
            day_punches = dedupe_rapid_punches(day_punches, 30)
            # Iter 77s — Drop same-machine same-kind duplicate punches
            # within 15 minutes so double-taps on the biometric device
            # don't inflate the hour count.
            day_punches = dedupe_same_machine_punches(day_punches, 15)
            # Iter 77w — Merge OUT->IN "bounces" (device stutter within
            # 60 seconds) so they are treated as one continuous session.
            day_punches = merge_out_in_bounces(day_punches, 60)
            if _pm_seq_mode:
                # Iter 538 (user rule) — ignore same-kind duplicate
                # punches within 5 minutes across ALL machines.
                day_punches = dedupe_same_kind_punches(day_punches, 5)
            if not day_punches:
                days_cell[key] = {
                    "in": None, "out": None, "ot_in": None, "ot_out": None,
                    "hours": 0.0, "duty_hours": 0.0, "raw_hours": 0.0, "ot_hours": 0.0,
                    "sources": [], "punches": 0,
                    "break_hours": 0.0, "net_hours": 0.0,
                    "late_min": 0, "early_min": 0,
                    # Iter 520 — policy flags stamped on NO-PUNCH days too.
                    "weekly_off": datetime(yy, mm, dd).weekday() in _emp_weekoffs,
                    "holiday": date_key_iso in _holiday_dates,
                }
                continue
            # Iter 77z-fix — Skip days with UNPAIRED punches (user rule:
            # "if any punch is missing between duty hours, do not
            # calculate duty"). These are surfaced with an ``anomaly``
            # flag so the UI can highlight them.
            if has_unpaired_punches(day_punches):
                # Still expose the raw times so admins can see what got
                # recorded on the device (in/out shown as first/last
                # punch time-stamps for context).
                _ps_sorted = sorted(
                    day_punches, key=lambda p: p.get("at") or ""
                )
                _first = _ps_sorted[0] if _ps_sorted else None
                _last = _ps_sorted[-1] if _ps_sorted else None
                def _fmt(p):
                    if not p or not p.get("at"):
                        return None
                    return datetime.fromisoformat(
                        (p.get("at") or "").replace("Z", "+00:00")
                    ).strftime("%H:%M")
                days_cell[key] = {
                    "in": _fmt(_first) if _first and (_first.get("kind") == "in") else None,
                    "out": _fmt(_last) if _last and (_last.get("kind") == "out") else None,
                    "ot_in": None, "ot_out": None,
                    "hours": 0.0, "duty_hours": 0.0, "raw_hours": 0.0, "ot_hours": 0.0,
                    "sources": list({_classify_punch_source(p.get("source")) for p in day_punches}),
                    # Iter 556 — admin-corrected day indicator.
                    "manual": any(str(p.get("source") or "") == "manual_admin"
                                  for p in day_punches),
                    "punches": len(day_punches),
                    "break_hours": 0.0, "net_hours": 0.0,
                    "late_min": 0, "early_min": 0,
                    "anomaly": True,
                    "anomaly_reason": "missing_punch",
                    # Iter 520 — policy flags on anomaly days too.
                    "weekly_off": datetime(yy, mm, dd).weekday() in _emp_weekoffs,
                    "holiday": date_key_iso in _holiday_dates,
                }
                total_punches_cnt += len(day_punches)
                continue
            day_min, in_dt, out_dt = _pair_punches(day_punches)
            raw_hrs = round(day_min / 60.0, 2)
            # Iter 77e - Compute POLICY-ADJUSTED duty hours. This applies
            # the OT cap (shift-hours if OT off, 24h if OT on), OT-merge
            # for Policy 1, and the week-off min-hours full-day rule.
            resolved_shift = _daily_shift_ovr.get(
                (emp_full.get("user_id"), date_key_iso),
            ) or resolve_shift_for_user(
                emp_full, day_punches, shifts_by_id, shifts_list,
                firm_shift_open=_is_shift_open(pol),
            )
            eff_policy = apply_resolved_shift_to_policy(pol, resolved_shift)
            # Iter 77z-final — Overlay per-employee policy overrides so
            # full_day_hours / ot_allowed / week_off_* honor employee
            # settings (e.g. one employee running a 12h shift while the
            # firm default is 8h).
            eff_policy = apply_employee_policy_override(eff_policy, emp_full)
            # Iter 236 — Attendance Engine Overhaul: per-day punch metrics
            # (Break gaps between OUT→IN pairs, Late arrival vs shift
            # start with grace, Early Going vs shift end). Shift source
            # priority: daily override / resolved shift → the firm shift
            # whose START is nearest to the day's first IN punch (so
            # night-shift workers are measured against the night shift).
            _shift_src = resolved_shift or resolve_shift_for_user(
                emp_full, day_punches, None,
                pol.get("shifts") or [], firm_shift_open=True,
            ) or {}
            try:
                _grace_min = int(float(eff_policy.get("grace_minutes_late") or 0))
            except (TypeError, ValueError):
                _grace_min = 0
            _dm = compute_day_punch_metrics(
                day_punches,
                shift_start=(_shift_src or {}).get("start"),
                shift_end=(_shift_src or {}).get("end"),
                grace_minutes=_grace_min,
            )
            weekday = datetime(yy, mm, dd).weekday()
            _is_holiday_day = date_key_iso in _holiday_dates
            summary = compute_textile_day(
                day_punches,
                apply_weekoff_rules_for_date(eff_policy, emp_full, date_key_iso),
                emp_full, weekday,
                is_holiday=_is_holiday_day)
            # Iter 77q — OT trigger threshold. Priority:
            #   1. eff_policy.full_day_hours  (firm's "full day" = actual
            #      daily working quota. Firms with a 12-hour shift set
            #      full_day_hours=12 and standard_working_hours=8 to
            #      keep the legacy 8h reference — but OT should trigger
            #      only past the 12h daily working quota.)
            #   2. eff_policy.standard_working_hours (fallback for
            #      firms that didn't configure full_day_hours).
            #   3. 8.0 legacy default.
            # NOTE: When an employee has a resolved shift override,
            # ``apply_resolved_shift_to_policy`` sets both fields to
            # shift.end-shift.start so this priority still yields the
            # correct value.
            standard_h = float(
                eff_policy.get("full_day_hours")
                or eff_policy.get("standard_working_hours")
                or 8.0
            )
            # Iter 202 — 8-HR present-day sub-point: reports split at 8 hrs.
            # Iter 288 (user bug) — split at EXACTLY 8: firms whose full-day
            # hours are UNDER 8 were splitting duty/OT too early, so OT and
            # Present Days disagreed with the Compliance Salary run.
            # Iter 539 (user) — Punch-Sequence mode splits DYNAMICALLY at
            # the FIRM MASTER daily duty hours, even when the resolved
            # shift is longer (never a hardcoded 8).
            if _pm_seq_mode:
                standard_h = float(pol.get("full_day_hours")
                                   or pol.get("standard_working_hours")
                                   or standard_h)
            elif _pm_8hr_reports:
                standard_h = 8.0
            # Iter 77z-fix — PAIR-BASED time & hour derivation.
            #   • Regular duty comes from the FIRST paired IN→OUT.
            #   • OT comes from the SECOND paired IN→OUT (or arithmetic
            #     fallback for single-pair long shifts).
            #   • Display timestamps (``in`` / ``out``) reflect the
            #     regular pair, NOT the raw last-OUT (which for cross-day
            #     shifts would show the next-morning punch).
            reg_in_dt, reg_out_dt, ot_in_dt, ot_out_dt = split_regular_ot_times(
                # Iter 538 — Punch-Sequence mode: quota 0 keeps the 1st
                # IN→OUT pair as the FULL duty window and treats later
                # pairs (evening IN → next-morning OUT) as OT.
                day_punches, 0.0 if _pm_seq_mode else standard_h * 60.0,
            )
            # Iter 77z-final — Apply the firm's rounding policy
            # (``duty_hours_rounding_minutes``: 0/5/10/15/30) to BOTH
            # duty and OT windows so the grid + downloads reflect the
            # rounded numbers admins configured.
            _round_step = int(eff_policy.get("duty_hours_rounding_minutes") or 0)
            duty_only_hrs = 0.0
            if reg_in_dt and reg_out_dt:
                # Iter 520 — duty = WORKED minutes inside the regular
                # window (pair-sum; break gaps excluded) so break time
                # never spills into OT — per the firm-policy rule "OT
                # counts only beyond full-day WORKED hours".
                _duty_min = worked_minutes_in_window(day_punches, reg_in_dt, reg_out_dt)
                _duty_min = _round_minutes(_duty_min, _round_step)
                duty_only_hrs = round(_duty_min / 60.0, 2)
            # Iter 503 — SINGLE MACHINE MODE fixed-lunch deduction: the
            # shared device records only first-IN / last-OUT, so a fixed
            # 30/45/60-min lunch is deducted from the day's duty hours.
            if _smm_fixed_lunch and duty_only_hrs * 60.0 > _smm_fixed_lunch:
                duty_only_hrs = round(
                    (duty_only_hrs * 60.0 - _smm_fixed_lunch) / 60.0, 2)
            ot_hrs = 0.0
            if ot_in_dt and ot_out_dt:
                # Iter 521 (code review) — OT window also uses WORKED
                # minutes so a break during overtime never counts as OT.
                _ot_min = worked_minutes_in_window(day_punches, ot_in_dt, ot_out_dt)
                _ot_min = _round_minutes(_ot_min, _round_step)
                ot_hrs = round(_ot_min / 60.0, 2)
            # Cap regular duty at the shift length. Any spillover joins OT.
            # Iter 539 (user) — also in Punch-Sequence mode: the first
            # pair splits at the Firm Master daily duty hours (dynamic),
            # e.g. 12 worked hrs @ 8-hr policy = 8 duty + 4 OT. Punches
            # AFTER the OUT remain pure OT (sequence rule).
            if duty_only_hrs > standard_h:
                _spill = round(duty_only_hrs - standard_h, 2)
                ot_hrs = round(ot_hrs + _spill, 2)
                duty_only_hrs = standard_h
            # If OT is disabled for this employee OR firm-wide, don't surface OT.
            if not eff_policy.get("ot_allowed", True) or eff_policy.get("firm_ot_allowed") is False:
                ot_hrs = 0.0
            # Iter 289 (user request) — OT rounding per the firm's OT slab
            # setting: 0 = exact, 30 = half-hour slabs (floor), 60 = hour
            # slabs (floor). Example (slab 30): 8:34 → 8:00 duty + 0:30 OT.
            if ot_hrs > 0:
                _slab = _pm_firm.get("ot_slab_minutes")
                _slab = int(_slab) if _slab in (0, 30, 60) else 30
                if _slab:
                    ot_hrs = (int(round(ot_hrs * 60)) // _slab) * _slab / 60.0
            # Iter 77h — Daily Duty HRS on grid ALWAYS includes OT.
            hrs = round(duty_only_hrs + ot_hrs, 2)
            # Iter 94 — Additional Duty HRS granted from Punch Approvals.
            _extra_h = _extra_by_key.get((uid, date_key_iso), 0.0)
            if _extra_h:
                # Iter 111 — extra duty can also REDUCE hours (negative
                # grant); clamp at 0 so a day never goes negative.
                hrs = round(max(0.0, hrs + _extra_h), 2)
                duty_only_hrs = round(max(0.0, duty_only_hrs + _extra_h), 2)
            # Prefer pair-based display; fall back to raw only if the
            # split found nothing (shouldn't happen because unpaired days
            # are already routed to the anomaly branch above).
            _in_display = reg_in_dt or in_dt
            _out_display = reg_out_dt or out_dt
            # Iter 229 (user bug — "same minutes on IN and OUT") — when a
            # single-pair day was split ARITHMETICALLY for OT, the split
            # boundary (IN + shift hours, e.g. 19:55 → "07:55") is NOT a
            # real punch. Display the ACTUAL machine OUT (e.g. 08:03).
            # Explicit OT pairs (in/out/in/out) keep their real times.
            if ot_in_dt is not None and reg_out_dt is not None and ot_in_dt == reg_out_dt:
                _out_display = ot_out_dt or out_dt
            # Unique source badges present in this day's punches.
            seen: List[str] = []
            for p in day_punches:
                b = _classify_punch_source(p.get("source"))
                if b not in seen:
                    seen.append(b)
            day_sal = 0.0
            if _sal_basic > 0 and hrs > 0:
                if _sal_mode == "daily":
                    day_sal = _sal_basic * (hrs / emp_daily_hrs) if emp_daily_hrs > 0 else 0.0
                elif _sal_mode == "hourly":
                    day_sal = _sal_basic * hrs
                else:  # monthly
                    day_sal = ((_sal_basic / _md_divisor) * (hrs / emp_daily_hrs)
                               if emp_daily_hrs > 0 and _md_divisor > 0 else 0.0)
                day_sal = round(day_sal, 2)
            # Iter 200 — Policy Master Sub Points:
            #   • week-off worked + weekoff_present_add_ot → ALL hours to
            #     OT, day NOT counted present.
            #   • holiday worked + holiday_present_add_ot → day counts
            #     present AND hours go to the OT column.
            _pm_flags = eff_policy.get("policy_master") or {}
            _holiday_present_credit = False
            # Iter 202 — policy-based per-day Present credit.
            _day_present = float(summary.get("present_days") or 0.0)
            # Iter 288 (user bug — "present days showing wrong" with the
            # 8-HR sub-point ON): the rule now FULLY decides the day —
            # 8+ worked hrs = 1 Present Day; under 8 = ½ (≥ half-day
            # threshold) or 0 — exactly matching the Compliance Salary run
            # (Iter 219 sync) so the report and the salary always agree.
            if _pm_8hr_reports:
                _w8 = round(duty_only_hrs + ot_hrs, 2)
                if _w8 >= 8.0:
                    _day_present = 1.0
                elif _pm_flags.get("halfday_threshold_rule"):
                    pass  # the Half-Day Threshold block below decides ½ / 0
                elif _w8 >= float(eff_policy.get("half_day_hours") or 4.0):
                    _day_present = 0.5
                elif _w8 > 0:
                    _day_present = 0.0
            # Iter 203 — "Half-Day Threshold Rule" sub-point (user request):
            #   worked < half-day threshold  → 0 Present, ALL hrs → OT
            #   threshold ≤ worked < full    → ½ Present, duty = threshold
            #                                  hrs, remaining hrs → OT
            #   worked ≥ full day            → unchanged.
            # Duty HRS therefore counts ONLY present-day hours — OT is
            # never included in Duty HRS.
            if _pm_flags.get("halfday_threshold_rule") and hrs > 0:
                _half_h = float(eff_policy.get("half_day_hours") or 4.0)
                _worked = round(duty_only_hrs + ot_hrs, 2)
                if _worked < _half_h:
                    ot_hrs = _worked
                    duty_only_hrs = 0.0
                    _day_present = 0.0
                elif _worked < standard_h:
                    duty_only_hrs = _half_h
                    ot_hrs = round(_worked - _half_h, 2)
                    _day_present = 0.5
            # Iter 205 (user request) — Week-Off Worked Attendance: fully
            # dynamic handling of week-off-day work per firm policy.
            _wow = eff_policy.get("week_off_worked") or {}
            _wow_mode = str(_wow.get("mode") or "")
            if hrs > 0 and summary.get("is_weekly_off") and _wow_mode:
                _worked_w = round(duty_only_hrs + ot_hrs, 2)
                _half_t = float(_wow.get("half_day_threshold") or 4.0)
                _full_t = float(_wow.get("full_day_threshold") or 8.0)
                _ot_after = float(_wow.get("ot_after") or 0.0)
                if _wow_mode == "ot_only":
                    duty_only_hrs = 0.0
                    ot_hrs = _worked_w
                    _day_present = 0.0
                elif _wow_mode == "half_day_ot":
                    if _worked_w >= _half_t:
                        _day_present = 0.5
                        _cut = _ot_after if _ot_after > 0 else _half_t
                        duty_only_hrs = round(min(_worked_w, _cut), 2)
                        ot_hrs = round(max(0.0, _worked_w - duty_only_hrs), 2)
                    else:
                        _day_present = 0.0
                        duty_only_hrs = 0.0
                        ot_hrs = _worked_w
                elif _wow_mode == "full_day_ot":
                    if _worked_w >= _full_t:
                        _day_present = 1.0
                        _cut = _ot_after if _ot_after > 0 else _full_t
                        duty_only_hrs = round(min(_worked_w, _cut), 2)
                        ot_hrs = round(max(0.0, _worked_w - duty_only_hrs), 2)
                    elif _worked_w >= _half_t:
                        _day_present = 0.5
                        duty_only_hrs = round(min(_worked_w, _half_t), 2)
                        ot_hrs = round(max(0.0, _worked_w - duty_only_hrs), 2)
                    else:
                        _day_present = 0.0
                        duty_only_hrs = 0.0
                        ot_hrs = _worked_w
                elif _wow_mode == "full_day_min_hours":
                    # Iter 207 — Full Day Attendance (Minimum Hours):
                    # worked ≥ min hours (default 50% of daily duty hrs)
                    # → FULL present day; below the minimum the worked
                    # hours count only as plain DUTY HRS (no present/OT).
                    _min_h = float(_wow.get("min_hours") or 0.0) or (emp_daily_hrs * 0.5)
                    if _worked_w >= _min_h:
                        _day_present = 1.0
                        _cut = _ot_after if _ot_after > 0 else emp_daily_hrs
                        duty_only_hrs = round(min(_worked_w, _cut), 2)
                        ot_hrs = round(max(0.0, _worked_w - duty_only_hrs), 2)
                    else:
                        _day_present = 0.0
                        duty_only_hrs = _worked_w
                        ot_hrs = 0.0
                elif _wow_mode == "hourly":
                    # Hourly Conversion — worked hours stay plain DUTY hours
                    # (paid per hour); no present-day / OT credit.
                    duty_only_hrs = _worked_w
                    ot_hrs = 0.0
                    _day_present = 0.0
                if _wow.get("double_ot") and ot_hrs > 0:
                    ot_hrs = round(ot_hrs * 2.0, 2)
                hrs = round(duty_only_hrs + ot_hrs, 2)
            elif hrs > 0 and summary.get("is_weekly_off") and _pm_flags.get("weekoff_present_add_ot"):
                ot_hrs = round(duty_only_hrs + ot_hrs, 2)
                duty_only_hrs = 0.0
                _day_present = 0.0
            if hrs > 0 and _is_holiday_day and _pm_flags.get("holiday_present_add_ot"):
                ot_hrs = round(duty_only_hrs + ot_hrs, 2)
                duty_only_hrs = 0.0
                _holiday_present_credit = True
                _day_present = 1.0
            total_present_policy += _day_present
            days_cell[key] = {
                "in": _in_display.strftime("%H:%M") if _in_display else None,
                "out": _out_display.strftime("%H:%M") if _out_display else None,
                "ot_in": ot_in_dt.strftime("%H:%M") if ot_in_dt else None,
                "ot_out": ot_out_dt.strftime("%H:%M") if ot_out_dt else None,
                "hours": hrs,           # DUTY + OT combined (Total Duty HRS view)
                "duty_hours": duty_only_hrs,   # duty only (for reference)
                "raw_hours": raw_hrs,   # actual worked (IN/OUT view)
                "ot_hours": ot_hrs,     # separate OT (for OT report)
                "punches": len(day_punches),
                # Iter 236 — Attendance Engine Overhaul per-day metrics.
                "break_hours": round(_dm["break_minutes"] / 60.0, 2),
                "net_hours": raw_hrs,
                "late_min": _dm["late_minutes"],
                "early_min": _dm["early_minutes"],
                "sources": seen,
                # Iter 556 (user request) — "Manual punches protected"
                # badge: day contains admin-corrected (manual_admin)
                # punches, which the engine never deduplicates (Iter 555).
                "manual": any(str(p.get("source") or "") == "manual_admin"
                              for p in day_punches),
                "present": _day_present,
                "weekly_off": bool(summary.get("is_weekly_off")),
                "holiday": _is_holiday_day,
                # Iter 94 — day-wise earned salary (basic-rate based).
                "salary": day_sal,
            }
            # Iter 503 — Single Machine Mode transparency fields on the
            # day cell (calc mode / duplicate drops / punch pattern).
            _smm_meta = next(
                (p.get("_smm") for p in day_punches
                 if isinstance(p.get("_smm"), dict)), None)
            if _smm_meta:
                days_cell[key].update({
                    "calc_mode": _smm_meta.get("calc_mode"),
                    "dupes_ignored": _smm_meta.get("dupes_ignored"),
                    "punch_pattern": _smm_meta.get("punch_pattern"),
                })
            # Iter 236 — accumulate overhaul totals for the row summary.
            total_punches_cnt += len(day_punches)
            total_net_min += day_min
            total_break_min += _dm["break_minutes"]
            total_late_min += _dm["late_minutes"]
            total_early_min += _dm["early_minutes"]
            if day_sal > 0:
                total_salary += day_sal
                day_salary_totals[key] = round(day_salary_totals.get(key, 0.0) + day_sal, 2)
            # Iter 291 — day-wise Present Count footer (In/Out & HRS reports).
            if _day_present:
                day_present_counts[key] = day_present_counts.get(key, 0) + 1
            if hrs > 0:
                total_present_days += 1 if (duty_only_hrs > 0 or _holiday_present_credit) else 0
                total_hours_min += round(hrs * 60)
                total_ot_min += round(ot_hrs * 60)
                # User rule (Iter 83): ``totals.duty_hours`` = REGULAR
                # DUTY only (excludes OT). Frontend renders it as
                # "Total HRS" while ``totals.hours`` (duty + OT) is the
                # "Total Duty HRS" grand total.
                total_duty_only_min += round(duty_only_hrs * 60)
        # Iter 205 — clock-timing summary math (user request): totals are
        # exact HH:MM sums; division-mode "Present Days" is the WHOLE day
        # count (Total Duty HRS ÷ Daily HRS) with the remainder shown in
        # Extra HRS — never a decimal like 13.58.
        # Iter 289 ROLLBACK (user request) — "Total Duty HRS" is back to the
        # sum of the processed day figures (duty + OT as shown in the cells),
        # not the raw punch-schedule total.
        total_hours = round(total_hours_min / 60.0, 4)
        total_ot_hours = round(total_ot_min / 60.0, 4)
        total_duty_only = round(total_duty_only_min / 60.0, 4)
        _div_min = int(round(
            (8.0 if (_pm_8hr_reports and not _pm_seq_mode) else emp_daily_hrs)
            * 60))
        _division_mode = bool(
            _pm_firm.get("attendance_by_duty_hours")
            and not _pm_firm.get("halfday_threshold_rule")
            and _div_min > 0
        )
        if _division_mode:
            _days_whole = total_hours_min // _div_min
            _extra_min = total_hours_min - _days_whole * _div_min
        else:
            _days_whole = 0
            # Iter 216 (user report) — in per-day policy counting mode the
            # "Extra Duty HRS" are the OT hours beyond regular duty (what
            # the OT Hours Sheet shows), NOT a division remainder. This is
            # what auto-fills P HRS on the Actual Salary Process.
            _extra_min = total_ot_min
        rows.append({
            "user_id": uid,
            "employee_code": e.get("employee_code"),
            "name": e.get("name"),
            "father_name": e.get("father_name"),
            "department": e.get("department"),
            "position": e.get("position"),
            "designation": e.get("designation"),
            "doj": e.get("doj"),
            "bio_code": e.get("bio_code"),
            "employee_group": e.get("employee_group"),
            "days": days_cell,
            "totals": {
                "present_days": total_present_days,
                "hours": total_hours,
                "ot_hours": total_ot_hours,
                # Iter 77s — duty excluding OT (for the new "Total Duty HRS"
                # column on the HRS view).
                "duty_hours": total_duty_only,
                # Iter 77k/77p - TOTAL DAYS = Total Duty HRS / Daily Working HRS.
                # Divisor priority (highest first):
                #   1. Employee override standard_working_hours
                #   2. Firm-level standard_working_hours / full_day_hours
                # This mirrors the payroll compute so admins see the exact
                # day count that will be used on the salary run.
                # Iter 202 (user request) — "Present Days" replaces the old
                # hours÷divisor "Days" column EVERYWHERE. Value follows the
                # firm's Attendance Policy:
                #   • attendance_by_duty_hours sub-point ON → Total HRS ÷
                #     Daily Duty HRS (8 when the 8-HR sub-point is active).
                #   • otherwise → per-day policy present counting (week-off /
                #     holiday sub-points + 8-HR rule applied per day).
                "total_days_computed": (
                    int(_days_whole) if _division_mode
                    else round(total_present_policy, 2)
                ),
                "present_days_policy": (
                    int(_days_whole) if _division_mode
                    else round(total_present_policy, 2)
                ),
                # Iter 83 — Split the decimal days into whole-days +
                # remainder-hours per user request:
                #   Total Duty HRS 335.30 / Daily 12 = 27.94 days
                #     → total_days_int = 27
                #     → total_extra_hrs = 11.30
                # (Extra HRS = Total Duty HRS − total_days_int × Daily.)
                "total_days_int": (
                    int(_days_whole) if _division_mode
                    else int(total_present_policy)
                ),
                "total_extra_hrs": round(_extra_min / 60.0, 4),
                # Iter 236 — Attendance Engine Overhaul summary columns:
                # Total Punches, Break HRS, Net Working HRS (paired IN→OUT
                # time excluding breaks), Late Minutes, Early Going.
                "total_punches": total_punches_cnt,
                "break_hours": round(total_break_min / 60.0, 4),
                "net_hours": round(total_net_min / 60.0, 4),
                "late_minutes": total_late_min,
                "early_minutes": total_early_min,
                "shift_hours": emp_daily_hrs,
                # Iter 94 — employee-wise earned salary for the window.
                "salary_total": round(total_salary, 2),
            },
        })

    return {
        "company": {"company_id": company_id, "name": company.get("name")},
        "month": month,
        "range_mode": range_mode,
        "from_date": date_from,
        "to_date": date_to,
        "days_in_month": len(day_iter),
        "day_labels": day_labels,
        "day_full_dates": day_full_dates,
        "weekday_labels": weekday_labels,
        "full_day_hours": full_day_hours,
        "employees": rows,
        # Iter 94 — day-wise salary totals (bottom row) + grand total.
        "day_salary_totals": {k: round(v, 2) for k, v in day_salary_totals.items()},
        "salary_grand_total": round(sum(day_salary_totals.values()), 2),
        # Iter 291 — day-wise Present Count bottom row.
        "day_present_counts": day_present_counts,
    }


# ---------------------------------------------------------------------------
# Iter 77i - OT Report
# ---------------------------------------------------------------------------
# Filters the monthly grid rows down to only (employee x day) pairs where
# OT was clocked. Reuses the compute pipeline of monthly_attendance_grid_json
# via an internal helper so both surfaces stay in sync.
# ---------------------------------------------------------------------------

async def _build_ot_report_rows(
    company_id: str,
    month: str,
    admin: dict,
    group_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> Tuple[dict, List[Dict[str, Any]]]:
    """Return (company_doc, ot_rows) for the requested window.

    Each row in ``ot_rows`` corresponds to ONE employee-day where OT>0.
    """
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    if admin.get("role") == "sub_admin":
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    if admin.get("role") == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="You can only view your own firm")

    # We don't want to duplicate 150 lines from monthly_attendance_grid_json
    # so we replicate the minimum data-fetching + compute pipeline inline
    # below.
    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "company_id": 1, "name": 1, "attendance_policy": 1,
         "attendance_config": 1},
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    # Reporting window (same rules as monthly_attendance_grid_json)
    import calendar as _cal
    range_mode = bool(
        from_date and to_date
        and re.match(r"^\d{4}-\d{2}-\d{2}$", from_date or "")
        and re.match(r"^\d{4}-\d{2}-\d{2}$", to_date or "")
    )
    if range_mode:
        d_from = datetime.strptime(from_date, "%Y-%m-%d").date()
        d_to = datetime.strptime(to_date, "%Y-%m-%d").date()
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        date_from = d_from.isoformat()
        date_to = d_to.isoformat()
        day_iter = []
        cur = d_from
        while cur <= d_to:
            day_iter.append((cur.year, cur.month, cur.day))
            cur = cur + timedelta(days=1)
    else:
        try:
            y, m = [int(x) for x in month.split("-")]
        except Exception as exc:
            raise HTTPException(status_code=400, detail="month must be YYYY-MM") from exc
        days_in_month = _cal.monthrange(y, m)[1]
        date_from = f"{y:04d}-{m:02d}-01"
        date_to = f"{y:04d}-{m:02d}-{days_in_month:02d}"
        day_iter = [(y, m, d) for d in range(1, days_in_month + 1)]

    query: Dict[str, Any] = {"role": "employee", "company_id": company_id}
    grp_uids = await _resolve_group_employee_ids(company_id, group_id)
    if grp_uids is not None:
        query["user_id"] = {"$in": grp_uids}
    employees = await db.users.find(
        query,
        {
            "_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
            "designation": 1, "department": 1, "bio_code": 1,
            "exit_date": 1, "resign_date": 1, "date_of_leaving": 1,
            "leaving_date": 1, "employment_status": 1, "disabled": 1, "active": 1,
        },
    ).sort([("employee_code", 1), ("name", 1)]).to_list(4000)
    # Iter 321 — ACTIVE employees only (OT report window's from-month).
    employees = [e for e in employees
                 if not _employee_inactive_for_report(e, date_from[:7])]

    if not employees:
        return company, []

    user_ids = [e["user_id"] for e in employees]
    punches_by_user_day: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    async for r in db.attendance.find(
        # Iter 83-final — Approved-only, matching the grid pipeline rule.
        {"user_id": {"$in": user_ids},
         "date": {"$gte": date_from, "$lte": date_to},
         "status": "approved"},
        {"_id": 0, "user_id": 1, "date": 1, "kind": 1, "at": 1, "source": 1},
    ).sort([("user_id", 1), ("at", 1)]):
        punches_by_user_day.setdefault(r["user_id"], {}).setdefault(r["date"], []).append(r)
    # Iter 77y — Same cross-day OT stitching as the grid pipeline.
    # Iter 481 — plus 5-min duplicate/alternation repair.
    for _uid_k in list(punches_by_user_day.keys()):
        punches_by_user_day[_uid_k] = stitch_cross_day_ot(
            dedupe_close_punches(
                punches_by_user_day[_uid_k],
                company_cfg=company.get("attendance_config"),
            ),
            company_cfg=company.get("attendance_config"),
        )

    pol = company.get("attendance_policy") or {}
    pol = await inject_firm_ot_flag(dict(pol), company.get("company_id"))
    # Iter 538 — Punch-Sequence mode (same flag as the grid pipeline).
    _pm_seq_mode = bool((pol.get("policy_master") or {}).get("attendance_by_duty_hours"))
    # Iter 503 — Single Machine Mode fixed-lunch config (matches the grid).
    _smm_cfg_ot = company.get("attendance_config") or {}
    _smm_fixed_lunch_ot = (
        int(_smm_cfg_ot.get("lunch_fixed_min") or 30)
        if (str(_smm_cfg_ot.get("device_mode") or "") == "single_machine"
            and str(_smm_cfg_ot.get("lunch_mode") or "") == "fixed")
        else 0
    )
    shifts_by_id, shifts_list = await load_shift_masters_map()
    full_emp_docs = await db.users.find(
        {"user_id": {"$in": user_ids}},
        {"_id": 0, "user_id": 1, "attendance_policy_override": 1,
         "ot_applicable": 1, "week_off_full_day": 1,
         "week_off_govt_holiday_enabled": 1,
         "weekly_off_days_override": 1},
    ).to_list(4000)
    full_emp_by_id = {u["user_id"]: u for u in full_emp_docs}
    # Iter 204 — per-day APPROVED shift assignments (Shift Change module).
    _daily_shift_ovr = await load_daily_shift_overrides(company_id, date_from, date_to)

    from utils.monthly_attendance import _pair_punches as _pp
    weekday_short = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    ot_rows: List[Dict[str, Any]] = []
    for e in employees:
        uid = e["user_id"]
        emp_full = {**e, **full_emp_by_id.get(uid, {})}
        by_day = punches_by_user_day.get(uid, {})
        for (yy, mm, dd) in day_iter:
            date_key_iso = f"{yy:04d}-{mm:02d}-{dd:02d}"
            day_punches = by_day.get(date_key_iso) or []
            # Iter 276 — ignore multiple punches within seconds (double-scans).
            day_punches = dedupe_rapid_punches(day_punches, 30)
            # Iter 77s — same 15-min dedup for the OT report so numbers match.
            day_punches = dedupe_same_machine_punches(day_punches, 15)
            # Iter 77w — Bounce-merge OUT→IN within 60s (device stutter)
            day_punches = merge_out_in_bounces(day_punches, 60)
            if _pm_seq_mode:
                day_punches = dedupe_same_kind_punches(day_punches, 5)
            if not day_punches:
                continue
            # Iter 77z-fix — Anomaly days (unpaired punches) don't count OT.
            if has_unpaired_punches(day_punches):
                continue
            day_min, in_dt, out_dt = _pp(day_punches)
            resolved_shift = resolve_shift_for_user(
                emp_full, day_punches, shifts_by_id, shifts_list,
                firm_shift_open=_is_shift_open(pol),
            )
            eff_policy = apply_resolved_shift_to_policy(pol, resolved_shift)
            eff_policy = apply_employee_policy_override(eff_policy, emp_full)
            weekday = datetime(yy, mm, dd).weekday()
            standard_h = float(
                eff_policy.get("full_day_hours")
                or eff_policy.get("standard_working_hours")
                or 8.0
            )
            if _pm_seq_mode:
                # Iter 539 — split at the Firm Master daily duty hours.
                standard_h = float(pol.get("full_day_hours")
                                   or pol.get("standard_working_hours")
                                   or standard_h)
            # Iter 77z-fix — Pair-based duty/OT derivation (matches grid).
            reg_in_dt, reg_out_dt, ot_in_dt, ot_out_dt = split_regular_ot_times(
                day_punches, 0.0 if _pm_seq_mode else standard_h * 60.0,
            )
            _round_step = int(eff_policy.get("duty_hours_rounding_minutes") or 0)
            duty_only = 0.0
            if reg_in_dt and reg_out_dt:
                # Iter 521 (code review) — duty = WORKED minutes (pair-sum,
                # lunch/break gaps excluded), mirroring the grid so the OT
                # Report can never turn a lunch break into OT via the
                # shift-length spillover below.
                _duty_min = worked_minutes_in_window(day_punches, reg_in_dt, reg_out_dt)
                _duty_min = _round_minutes(_duty_min, _round_step)
                duty_only = round(_duty_min / 60.0, 2)
            # Iter 503 — Single Machine Mode fixed-lunch deduction.
            if _smm_fixed_lunch_ot and duty_only * 60.0 > _smm_fixed_lunch_ot:
                duty_only = round(
                    (duty_only * 60.0 - _smm_fixed_lunch_ot) / 60.0, 2)
            ot = 0.0
            if ot_in_dt and ot_out_dt:
                _ot_min = worked_minutes_in_window(day_punches, ot_in_dt, ot_out_dt)
                _ot_min = _round_minutes(_ot_min, _round_step)
                ot = round(_ot_min / 60.0, 2)
            # Cap duty at shift length; spillover joins OT.
            # Iter 539 — sequence mode splits at Firm Master duty hours.
            if duty_only > standard_h:
                ot = round(ot + (duty_only - standard_h), 2)
                duty_only = standard_h
            # Honor per-employee AND firm-wide OT-allowed flags.
            if not eff_policy.get("ot_allowed", True) or eff_policy.get("firm_ot_allowed") is False:
                ot = 0.0
            # Iter 289 (user request) — OT rounding per the firm's OT slab
            # setting (0 = exact / 30 / 60-minute slabs, floor).
            if ot > 0:
                _slab = (pol.get("policy_master") or {}).get("ot_slab_minutes")
                _slab = int(_slab) if _slab in (0, 30, 60) else 30
                if _slab:
                    ot = (int(round(ot * 60)) // _slab) * _slab / 60.0
            if ot <= 0:
                continue  # only OT days
            ot_rows.append({
                "user_id": uid,
                "employee_code": e.get("employee_code"),
                "name": e.get("name"),
                "designation": e.get("designation") or e.get("department"),
                "bio_code": e.get("bio_code"),
                "date": date_key_iso,
                "day_label": weekday_short[weekday],
                "in": reg_in_dt.strftime("%H:%M") if reg_in_dt else (in_dt.strftime("%H:%M") if in_dt else None),
                "out": reg_out_dt.strftime("%H:%M") if reg_out_dt else (out_dt.strftime("%H:%M") if out_dt else None),
                "ot_in": ot_in_dt.strftime("%H:%M") if ot_in_dt else None,
                "ot_out": ot_out_dt.strftime("%H:%M") if ot_out_dt else None,
                "duty_hours": duty_only,
                "ot_hours": ot,
                "total_hours": round(duty_only + ot, 2),
            })
    return company, ot_rows


@api.get("/admin/attendance/ot-report/{company_id}/{month}")
async def ot_report_json(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    company, rows = await _build_ot_report_rows(
        company_id, month, admin, group_id, from_date, to_date,
    )
    return {
        "company": {"company_id": company_id, "name": company.get("name")},
        "month": month,
        "from_date": from_date,
        "to_date": to_date,
        "count": len(rows),
        "rows": rows,
    }


@api.get("/admin/attendance/ot-report/{company_id}/{month}/xlsx")
async def ot_report_xlsx(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    from utils.ot_report_xlsx import build_ot_report_xlsx
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    company, rows = await _build_ot_report_rows(
        company_id, month, admin, group_id, from_date, to_date,
    )
    period_label = (
        f"{from_date} to {to_date}" if from_date and to_date else month
    )
    xls = build_ot_report_xlsx(
        company_name=company.get("name") or "",
        period_label=period_label,
        rows=rows,
    )
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", (company.get("name") or "OT"))[:40]
    fname = f"{safe_name}_OT_Report_{period_label.replace(' ', '')}.xlsx"
    return Response(
        content=xls,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


async def _master_rates_by_user(company_id: str):
    """Iter 334 (user request) — master salary per employee straight from
    the EMPLOYEE MASTER: Basic, HRA, Conv., every allowance enabled on the
    Firm Master (dynamic columns) and Gross. Returns (labels, rates)."""
    from routes.firm_master import ALLOWANCE_LABELS
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "allowances": 1})
    enabled = {k for k, v in ((fm or {}).get("allowances") or {}).items() if v}
    skip = {"HRA", "CONV.", "OVER TIME"}
    # Iter 730 (user bug — "Editable Allowances showing wrong in Excel"):
    # the fixed HRA / Conv. / OVER_TIME columns now follow the Firm-Master
    # Allowance catalog too. Firms WITHOUT a configured catalog keep every
    # column (backward compatible).
    _cat = (fm or {}).get("allowances") or {}
    if _cat:
        fixed_heads = {"hra": bool(_cat.get("HRA")),
                       "conv": bool(_cat.get("CONV.")),
                       "ot": bool(_cat.get("OVER TIME"))}
    else:
        fixed_heads = {"hra": True, "conv": True, "ot": True}
    # Fixed catalog order first, then custom heads alphabetically.
    labels = [x for x in ALLOWANCE_LABELS if x in enabled and x not in skip]
    labels += sorted(x for x in enabled
                     if x not in set(ALLOWANCE_LABELS) and x not in skip)
    label_by_lower = {x.lower(): x for x in labels}

    def _n(v) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    rates: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find(
        {"company_id": company_id, "role": "employee"},
        {"_id": 0, "user_id": 1, "compliance_basic": 1, "basic_salary": 1,
         "basic_amount": 1, "hra_amount": 1, "conv_amount": 1,
         "compliance_salary_allowances": 1, "salary_structure_compliance": 1,
         "salary_structure_actual": 1, "compliance_gross": 1,
         "salary_monthly": 1},
    ):
        basic = _n(u.get("compliance_basic")) or _n(u.get("basic_salary")) \
            or _n(u.get("basic_amount"))
        hra = _n(u.get("hra_amount"))
        conv = _n(u.get("conv_amount"))
        extra: Dict[str, float] = {}
        misc = 0.0
        allow_rows = list(u.get("compliance_salary_allowances") or [])
        for r0 in (u.get("salary_structure_compliance") or []):
            if not isinstance(r0, dict):
                continue
            h0 = str(r0.get("head") or "").strip()
            if "employer" in h0.lower():
                continue
            if h0.lower().startswith("basic"):
                if basic <= 0:
                    basic += _n(r0.get("amount"))
            else:
                allow_rows.append(r0)
        if basic <= 0:
            for r0 in (u.get("salary_structure_actual") or []):
                if isinstance(r0, dict) and str(r0.get("head") or "").strip().lower().startswith("basic"):
                    basic += _n(r0.get("amount"))
        for r0 in allow_rows:
            if not isinstance(r0, dict):
                continue
            head = str(r0.get("head") or "").strip()
            amt = _n(r0.get("amount"))
            if not head or amt <= 0:
                continue
            s = head.lower()
            if "hra" in s or "house" in s:
                hra += amt
            elif s.startswith("conv") or "travel" in s:
                conv += amt
            elif s in label_by_lower:
                lb = label_by_lower[s]
                extra[lb] = extra.get(lb, 0.0) + amt
            elif "medic" in s and "MEDICAL ALLOWANCES" in labels:
                extra["MEDICAL ALLOWANCES"] = extra.get("MEDICAL ALLOWANCES", 0.0) + amt
            elif "special" in s and "OTH. ALLOW." in labels:
                extra["OTH. ALLOW."] = extra.get("OTH. ALLOW.", 0.0) + amt
            elif "OTHER MISC.ALLOWANCE" in labels:
                extra["OTHER MISC.ALLOWANCE"] = extra.get("OTHER MISC.ALLOWANCE", 0.0) + amt
            else:
                misc += amt
        gross = _n(u.get("compliance_gross"))
        total = basic + hra + conv + sum(extra.values()) + misc
        # Iter 347 (user check: "Gross figures correct or not") — when the
        # employee HAS a head-wise breakup, the heads are the source of
        # truth: Gross must equal Basic + all allowances. A stale
        # compliance_gross (old-DB GrossPay) no longer wins over the heads.
        if total > 0 and abs(gross - total) > 0.5:
            gross = total
        if gross <= 0:
            gross = total if total > 0 else _n(u.get("salary_monthly"))
        if total > 0 or gross > 0:
            rates[u["user_id"]] = {
                "basic": basic, "hra": hra, "conv": conv,
                "extra": extra, "gross": round(gross, 2),
            }
    return labels, rates, fixed_heads


def _att_sheet_sort(employees: List[dict], sort_by: Optional[str]) -> List[dict]:
    """Iter 346 (user request) — sorting option before downloading the
    attendance sheet: code (numeric, default) / name / department /
    designation / doj."""
    def _code_num(e):
        try:
            return (0, float(str(e.get("employee_code") or "").strip() or 1e12), "")
        except ValueError:
            return (1, 0.0, str(e.get("employee_code") or ""))
    s = (sort_by or "code").lower()
    if s == "name":
        return sorted(employees, key=lambda e: str(e.get("name") or "").lower())
    if s == "department":
        return sorted(employees, key=lambda e: (
            str(e.get("department") or e.get("employee_type") or "").lower(),
            _code_num(e)))
    if s == "designation":
        # Iter 355 (user request) — sort by Designation, then employee code.
        return sorted(employees, key=lambda e: (
            str(e.get("designation") or e.get("position") or "").lower(),
            _code_num(e)))
    if s == "doj":
        # Iter 377 — DOJ may be stored DD-MM-YYYY (legacy import); parse it
        # so mixed formats still sort chronologically.
        def _doj_key(e):
            dt = _parse_any_date(e.get("doj"))
            return (dt.strftime("%Y-%m-%d") if dt else "9999-99-99",
                    _code_num(e))
        return sorted(employees, key=_doj_key)
    return sorted(employees, key=_code_num)


async def _generate_attendance_sheet_impl(
    company_id: str, month: str, admin: dict, group_id: Optional[str] = None,
    sort_by: Optional[str] = None,
):
    from utils.master_sheet import build_master_sheet_xlsx
    from fastapi.responses import Response
    # Iter 332 (user request) — Sub Super Admins can use the Attendance
    # Master Sheet too.
    require_role(admin, ["super_admin", "sub_admin"])
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "name": 1})
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    query: Dict[str, Any] = {"role": "employee", "company_id": company_id}
    grp_uids = await _resolve_group_employee_ids(company_id, group_id)
    grp_name = ""
    if grp_uids is not None:
        query["user_id"] = {"$in": grp_uids}
        grp = await db.masters.find_one(
            {"master_id": group_id, "type": "group"}, {"_id": 0, "name": 1}
        )
        grp_name = (grp or {}).get("name") or ""

    employees = await db.users.find(
        query,
        {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1, "doj": 1, "department": 1,
         "designation": 1, "position": 1, "employee_group": 1, "employee_type": 1,
         "pf_no": 1, "uan_no": 1, "esi_ip_no": 1, "father_name": 1,
         "exit_date": 1, "resign_date": 1, "date_of_leaving": 1,
         "leaving_date": 1, "employment_status": 1, "disabled": 1, "active": 1},
    ).to_list(2000)
    # Skip pre-DOJ (Iter 57 rule) so the master sheet mirrors the compliance run.
    employees = [e for e in employees if not _month_is_before_doj(e, month)]
    # Iter 321 — ACTIVE employees only on the Attendance Sheet.
    employees = [e for e in employees if not _employee_inactive_for_report(e, month)]
    # Iter 346 (user request) — apply the chosen sort order.
    employees = _att_sheet_sort(employees, sort_by)

    # Iter 334 (user request) — master salary columns (Basic / HRA / Conv. /
    # firm-enabled allowances / Gross Salary) from the EMPLOYEE MASTER.
    allowance_labels, rates_by_user, fixed_heads = await _master_rates_by_user(company_id)

    # Present-days snapshot for reference
    try:
        y, m = int(month[:4]), int(month[5:7])
    except ValueError:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    from utils.salary_run import actual_days_in_month
    days_in_month = actual_days_in_month(y, m)
    date_from = f"{y:04d}-{m:02d}-01"
    date_to = f"{y:04d}-{m:02d}-{days_in_month:02d}"
    days_by_user: Dict[str, int] = {}
    if employees:
        user_ids = [e["user_id"] for e in employees]
        async for r in db.attendance.find(
            {"user_id": {"$in": user_ids}, "date": {"$gte": date_from, "$lte": date_to},
             "kind": "in"},
            {"_id": 0, "user_id": 1, "date": 1},
        ):
            uid = r["user_id"]
            days_by_user[uid] = days_by_user.get(uid, 0) + 1

    xlsx_bytes = build_master_sheet_xlsx(
        company_name=company.get("name") or "S.K. Sharma & Co.",
        month=month,
        employees=employees,
        attendance_days_by_user=days_by_user,
        rates_by_user=rates_by_user,
        allowance_labels=allowance_labels,
        fixed_heads=fixed_heads,
    )
    company_slug = (company.get("name") or "company").replace(" ", "_")
    grp_slug = ("_" + grp_name.replace(" ", "-")) if grp_name else ""
    filename = f"AttendanceSheet_{company_slug}_{month}{grp_slug}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api.get("/admin/attendance-sheet/{company_id}/{month}.xlsx")
async def generate_attendance_sheet(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    sort: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Generate the prefilled attendance sheet XLSX for a company + month,
    optionally filtered by Employee Group and sorted (code/name/department/doj)."""
    admin = await get_user_from_token(authorization)
    return await _generate_attendance_sheet_impl(company_id, month, admin, group_id, sort)


@api.get("/admin/attendance-sheet/{company_id}/{month}/groups.zip")
async def generate_attendance_sheet_groups_zip(
    company_id: str,
    month: str,
    sort: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 334 (user request) — "All groups" download: one attendance
    sheet Excel PER GROUP, bundled into a single archive."""
    import zipfile
    from io import BytesIO
    from utils.master_sheet import build_master_sheet_xlsx
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "name": 1})
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    try:
        y, m = int(month[:4]), int(month[5:7])
    except ValueError:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")

    employees = await db.users.find(
        {"role": "employee", "company_id": company_id},
        {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1, "doj": 1, "department": 1,
         "designation": 1, "position": 1, "employee_group": 1, "employee_type": 1,
         "pf_no": 1, "uan_no": 1, "esi_ip_no": 1, "father_name": 1,
         "exit_date": 1, "resign_date": 1, "date_of_leaving": 1,
         "leaving_date": 1, "employment_status": 1, "disabled": 1, "active": 1},
    ).to_list(20000)
    employees = [e for e in employees if not _month_is_before_doj(e, month)]
    # ACTIVE employees only (Iter 321 rule).
    employees = [e for e in employees if not _employee_inactive_for_report(e, month)]

    allowance_labels, rates_by_user, fixed_heads = await _master_rates_by_user(company_id)

    from utils.salary_run import actual_days_in_month
    days_in_month = actual_days_in_month(y, m)
    days_by_user: Dict[str, int] = {}
    if employees:
        async for r in db.attendance.find(
            {"user_id": {"$in": [e["user_id"] for e in employees]},
             "date": {"$gte": f"{y:04d}-{m:02d}-01",
                      "$lte": f"{y:04d}-{m:02d}-{days_in_month:02d}"},
             "kind": "in"},
            {"_id": 0, "user_id": 1},
        ):
            days_by_user[r["user_id"]] = days_by_user.get(r["user_id"], 0) + 1

    # Split by Employee Group (Type); blanks land in UNGROUPED.
    groups: Dict[str, List[dict]] = {}
    for e in employees:
        g = str(e.get("employee_type") or e.get("employee_group") or "").strip().upper() or "UNGROUPED"
        groups.setdefault(g, []).append(e)

    company_name = company.get("name") or "S.K. Sharma & Co."
    company_slug = company_name.replace(" ", "_")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for g in sorted(groups):
            xb = build_master_sheet_xlsx(
                company_name=f"{company_name}  ·  {g}",
                month=month,
                employees=_att_sheet_sort(groups[g], sort or "name"),
                attendance_days_by_user=days_by_user,
                rates_by_user=rates_by_user,
                allowance_labels=allowance_labels,
                fixed_heads=fixed_heads,
            )
            zf.writestr(
                f"AttendanceSheet_{company_slug}_{month}_{g.replace(' ', '-')}.xlsx",
                xb)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="AttendanceSheets_{company_slug}_{month}_AllGroups.zip"'},
    )


@api.get("/admin/master-sheet/{company_id}/{month}.xlsx")
async def generate_master_sheet_legacy(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Legacy alias — kept for backward compatibility with cached URLs."""
    admin = await get_user_from_token(authorization)
    return await _generate_attendance_sheet_impl(company_id, month, admin, group_id)


async def _upload_attendance_sheet_impl(file: UploadFile, admin: dict):
    from utils.master_sheet import parse_uploaded_xlsx, match_columns
    require_role(admin, ["super_admin", "sub_admin"])  # Iter 332
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are accepted")
    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 15 MB)")
    try:
        headers, body = parse_uploaded_xlsx(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read the Excel file: {e}")
    if not headers:
        raise HTTPException(status_code=400, detail="Empty file — no headers detected")
    report = match_columns(headers)
    return {
        "ok": True,
        "row_count": len(body),
        "headers": headers,
        "body_preview": body[:20],
        "mis_report": report,
        "body": body,   # full body so /apply-mapping is stateless
    }


@api.post("/admin/attendance-sheet/upload")
async def upload_attendance_sheet(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None),
):
    """Accept any XLSX (our template OR a random format) and return an MIS
    report of column matches."""
    admin = await get_user_from_token(authorization)
    return await _upload_attendance_sheet_impl(file, admin)


@api.post("/admin/master-sheet/upload")
async def upload_master_sheet_legacy(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None),
):
    """Legacy alias."""
    admin = await get_user_from_token(authorization)
    return await _upload_attendance_sheet_impl(file, admin)


async def _apply_mapping_impl(payload: MasterSheetMap, admin: dict):
    from utils.master_sheet import import_rows_via_mapping
    require_role(admin, ["super_admin", "sub_admin"])  # Iter 332
    company = await db.companies.find_one({"company_id": payload.company_id}, {"_id": 0, "name": 1})
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    records = import_rows_via_mapping(payload.headers, payload.body, payload.mapping)

    # Match records to employees by employee_code (preferred) or by name.
    imported = 0
    unmatched: List[Dict[str, Any]] = []
    for rec in records:
        code = (rec.get("employee_code") or "").strip()
        name = (rec.get("name") or "").strip()
        query: Dict[str, Any] = {"company_id": payload.company_id, "role": "employee"}
        if code:
            query["employee_code"] = code
        elif name:
            query["name"] = name
        else:
            continue
        emp = await db.users.find_one(query, {"_id": 0, "user_id": 1})
        if not emp:
            unmatched.append({"code": code, "name": name})
            continue
        updates: Dict[str, Any] = {}
        if "gross_salary" in rec:
            updates["salary_monthly"] = float(rec["gross_salary"] or 0)
        if "advance" in rec:
            updates["advance_balance"] = max(0.0, float(rec["advance"] or 0))
        if "tds" in rec:
            updates["tds_amount"] = max(0.0, float(rec["tds"] or 0))
        if updates:
            updates["master_sheet_last_import"] = {
                "month": payload.month, "at": now_iso(), "by": admin["user_id"],
            }
            await db.users.update_one({"user_id": emp["user_id"]}, {"$set": updates})
            imported += 1
    return {
        "ok": True,
        "imported": imported,
        "unmatched_count": len(unmatched),
        "unmatched": unmatched[:50],
        "next": "Trigger a Compliance Salary Run for this month/company to see the updated numbers.",
    }


@api.post("/admin/attendance-sheet/apply-mapping")
async def apply_attendance_sheet_mapping(
    payload: MasterSheetMap,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    return await _apply_mapping_impl(payload, admin)


@api.post("/admin/master-sheet/apply-mapping")
async def apply_master_sheet_mapping_legacy(
    payload: MasterSheetMap,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    return await _apply_mapping_impl(payload, admin)



# ---------------------------------------------------------------------------
# Iter 60 — Bulk-import employees + Auto-email cron + Portal Automation jobs
# ---------------------------------------------------------------------------
# Loaded from a dedicated module to keep server.py from bloating further.
from utils.iter60_features import register_iter60_features  # noqa: E402

register_iter60_features(app, api, db, now_iso, get_user_from_token, require_role, require_super_admin_strict)


# ---------------------------------------------------------------------------
# Iter 61 — Multi-company Compliance Batch + Payslip Auto-Email
# ---------------------------------------------------------------------------
import sys as _sys  # noqa: E402
from utils.iter61_features import register_iter61_features  # noqa: E402

register_iter61_features(
    app, api, db, now_iso, get_user_from_token,
    require_role, require_super_admin_strict,
    server_module=_sys.modules[__name__],
)


# ---------------------------------------------------------------------------
# Iter 73 — AI Insights (GPT-5.2 via emergentintegrations)
# ---------------------------------------------------------------------------
# Super-admin only endpoints powering the "AI Insights" web page: chat Q&A,
# monthly executive summary, and anomaly scan. All routes require a real
# super_admin (not sub_admin) — the operator sees firm-wide data.
from utils.ai_insights import ai_ask, ai_monthly_summary, ai_anomalies  # noqa: E402


class _AiAskPayload(BaseModel):
    question: str
    session_id: Optional[str] = None
    company_id: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None


@api.post("/admin/ai/ask")
async def admin_ai_ask(
    payload: _AiAskPayload,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_super_admin_strict(user)
    q = (payload.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="question is required")
    sid = payload.session_id or f"ai-{user['user_id']}-{int(datetime.now(timezone.utc).timestamp())}"
    cid = payload.company_id if payload.company_id and payload.company_id != "all" else None
    try:
        reply = await ai_ask(
            db,
            question=q,
            session_id=sid,
            company_id=cid,
            history=payload.history,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"AI backend error: {exc}") from exc
    return {"reply": reply, "session_id": sid, "company_id": cid or "all"}


@api.get("/admin/ai/summary")
async def admin_ai_summary(
    month: str,
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_super_admin_strict(user)
    if not month or len(month) != 7 or month[4] != "-":
        raise HTTPException(status_code=400, detail="month must be in YYYY-MM format")
    cid = company_id if company_id and company_id != "all" else None
    sid = f"ai-sum-{user['user_id']}-{month}-{cid or 'all'}"
    try:
        reply = await ai_monthly_summary(db, month=month, company_id=cid, session_id=sid)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"AI backend error: {exc}") from exc
    return {"summary": reply, "month": month, "company_id": cid or "all"}


@api.get("/admin/ai/anomalies")
async def admin_ai_anomalies(
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_super_admin_strict(user)
    cid = company_id if company_id and company_id != "all" else None
    sid = f"ai-anom-{user['user_id']}-{cid or 'all'}-{int(datetime.now(timezone.utc).timestamp())}"
    try:
        reply = await ai_anomalies(db, company_id=cid, session_id=sid)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"AI backend error: {exc}") from exc
    return {"anomalies": reply, "company_id": cid or "all"}


@api.get("/admin/ai/firms")
async def admin_ai_firms(authorization: Optional[str] = Header(None)):
    """Small helper — returns the list of firms for the AI Insights dropdown."""
    user = await get_user_from_token(authorization)
    require_super_admin_strict(user)
    firms = await db.companies.find(
        {},
        {"_id": 0, "company_id": 1, "name": 1, "company_code": 1},
    ).sort("name", 1).to_list(500)
    return {"firms": firms}


# ---------------------------------------------------------------------------
# Iter 106 — Public base URL for QR links (joining / employee app /
# employer portal). The operator points this at their own VPS domain so
# every printed QR opens the self-hosted app.
# ---------------------------------------------------------------------------
@api.get("/public-config")
async def get_public_config():
    cfg = await db.app_settings.find_one({"key": "public_base_url"}, {"_id": 0})
    return {"public_base_url": (cfg or {}).get("value") or ""}


@api.put("/admin/public-config")
async def set_public_config(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin"])
    url = (payload.get("public_base_url") or "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    if not url:
        await db.app_settings.delete_one({"key": "public_base_url"})
        return {"ok": True, "public_base_url": ""}
    await db.app_settings.update_one(
        {"key": "public_base_url"},
        {"$set": {"key": "public_base_url", "value": url,
                  "updated_by": user["user_id"], "updated_at": now_iso()}},
        upsert=True)
    return {"ok": True, "public_base_url": url}


# Iter 85 (fix) — ``app.include_router(api)`` moved to the very end of
# this module so *all* @api.* decorators (including the new Actual
# Salary Process endpoints, WebSocket stats, ZK push webhook, etc.)
# get picked up. Registering the router earlier snapshots its routes
# and silently drops anything added below.


# ---------------------------------------------------------------------------
# Iter 77n - Real-time WebSocket + ZKTeco push webhook
# ---------------------------------------------------------------------------
# Live-sync channel used by both admin dashboards and the employee app.
# Clients open a ws to  /api/ws/live?token=<jwt>&firm=<cid>  and receive
# JSON events broadcast from event-emitting endpoints (create-punch,
# approve-leave, salary-run finalise, ZK push, etc.).  See
# /app/backend/utils/ws_broker.py and /app/frontend/src/hooks/useLiveSync.ts.

from fastapi import WebSocket, WebSocketDisconnect
from utils.ws_broker import broker as _ws_broker


async def _resolve_ws_user(token: Optional[str]) -> Optional[dict]:
    """Session token -> user doc. Returns ``None`` if invalid so the
    caller can close with a policy-violation code."""
    if not token:
        return None
    try:
        session = await db.user_sessions.find_one(
            {"session_token": token}, {"_id": 0},
        )
        if not session:
            return None
        expires_at = session.get("expires_at")
        if isinstance(expires_at, str):
            exp_dt = datetime.fromisoformat(expires_at)
        else:
            exp_dt = expires_at
        if exp_dt is not None and exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if exp_dt is not None and exp_dt < datetime.now(timezone.utc):
            return None
        return await db.users.find_one(
            {"user_id": session["user_id"]}, {"_id": 0},
        )
    except Exception:
        return None


@app.websocket("/api/ws/live")
async def ws_live(ws: WebSocket, token: Optional[str] = None, firm: Optional[str] = None):
    """Real-time channel.

    Query params:
      * ``token`` — bearer JWT (required)
      * ``firm``  — company_id to subscribe to. Employees don't need to
        pass this (they receive user-scoped events by default).
    """
    await ws.accept()
    user = await _resolve_ws_user(token)
    if not user:
        try:
            await ws.send_json({"type": "error", "message": "unauthorized"})
        finally:
            await ws.close(code=1008)
        return

    # Sub-admin can only subscribe to firms in their scope.
    firm_id = firm
    if firm_id and user.get("role") == "sub_admin":
        if not sub_admin_can_touch_company(user, firm_id):
            await ws.send_json({"type": "error", "message": "firm outside scope"})
            await ws.close(code=1008)
            return
    if firm_id and user.get("role") == "company_admin":
        if user.get("company_id") != firm_id:
            await ws.send_json({"type": "error", "message": "wrong firm"})
            await ws.close(code=1008)
            return
    # Employees are auto-scoped to THEIR firm regardless of the query param.
    if user.get("role") == "employee":
        firm_id = user.get("company_id")

    user_id = user.get("user_id")
    await _ws_broker.connect(ws, firm_id, user_id)

    # Send an initial ack so the client knows the subscription is live.
    try:
        await ws.send_json({
            "type": "ready",
            "firm": firm_id,
            "user_id": user_id,
            "role": user.get("role"),
            "server_time": now_iso(),
        })
        while True:
            # Passive listen; we don't expect messages from the client
            # but we drain to detect close.  A ping every 30s keeps NAT
            # / L7 proxies from timing out the socket.
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                # Client-initiated ping to keep-alive
                if msg == "ping":
                    await ws.send_json({"type": "pong", "server_time": now_iso()})
            except asyncio.TimeoutError:
                await ws.send_json({"type": "heartbeat", "server_time": now_iso()})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("ws loop crashed: %s", exc)
    finally:
        await _ws_broker.disconnect(ws, firm_id, user_id)


@api.get("/admin/ws/stats")
async def ws_stats(authorization: Optional[str] = Header(None)):
    """Debug endpoint — dumps active WS subscription counts. Super-admin only."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    return _ws_broker.stats()


# ---------------------------------------------------------------------------
# ZKTeco push webhook — /api/biometric/zk-push
# ---------------------------------------------------------------------------
# Many ZKTeco firmware versions can POST punch events to a configurable
# HTTP endpoint (CGI / "cloud push" mode). We accept a very forgiving
# payload shape so it works across firmware versions:
#
#   Preferred JSON body::
#       {
#         "device_secret": "…",              # required — matches
#                                             #  company.attendance_policy.zk_secret
#         "company_id":    "cmp_xxx",        # required
#         "punches": [
#           {"bio_code": "0004", "at": "2026-06-15T09:12:00+05:30", "kind": "in",
#            "verify_mode": "fp"},
#           …
#         ]
#       }
#
# Legacy ZK push modes (form-encoded, per-punch requests) can be routed
# through a lightweight middle-tier — see docs/zk_push.md.

class ZKPushBody(BaseModel):
    device_secret: str
    company_id: str
    punches: List[Dict[str, Any]] = []


@api.post("/biometric/zk-push")
async def zk_push_webhook(body: ZKPushBody):
    """Ingest punches from a ZKTeco biometric device."""
    company = await db.companies.find_one(
        {"company_id": body.company_id},
        {"_id": 0, "attendance_policy": 1, "name": 1},
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    expected = ((company.get("attendance_policy") or {}).get("zk_secret") or "").strip()
    if not expected or expected != (body.device_secret or "").strip():
        raise HTTPException(status_code=403, detail="Invalid device_secret")

    if not body.punches:
        return {"accepted": 0}

    # Resolve bio_code -> user_id via the users collection.
    bio_codes = list({str(p.get("bio_code") or "").strip() for p in body.punches if p.get("bio_code")})
    users = await db.users.find(
        {"company_id": body.company_id, "bio_code": {"$in": bio_codes}, "role": "employee"},
        {"_id": 0, "user_id": 1, "bio_code": 1, "name": 1},
    ).to_list(1000)
    by_bio = {str(u["bio_code"]): u for u in users if u.get("bio_code")}

    inserted = 0
    broadcast_events: List[Dict[str, Any]] = []
    # Iter 583 — configurable duplicate-punch window from the firm policy.
    try:
        _zk_dedup_min = int((company.get("attendance_policy") or {}).get("dedup_window_minutes", 5))
    except (TypeError, ValueError):
        _zk_dedup_min = 5
    for p in body.punches:
        bc = str(p.get("bio_code") or "").strip()
        u = by_bio.get(bc)
        if not u:
            continue
        try:
            at_dt = datetime.fromisoformat(str(p.get("at")).replace("Z", "+00:00"))
        except Exception:
            continue
        kind = (p.get("kind") or "").lower()
        if kind not in ("in", "out"):
            # ZK devices sometimes send integers (0=in, 1=out, ...). Coerce.
            if str(p.get("kind")).strip() in ("0", "0.0"):
                kind = "in"
            elif str(p.get("kind")).strip() in ("1", "1.0"):
                kind = "out"
            else:
                kind = "in"
        rec = {
            "attendance_id": f"att_{uuid.uuid4().hex[:10]}",
            "user_id": u["user_id"],
            "company_id": body.company_id,
            "date": at_dt.date().isoformat(),
            "at": at_dt.isoformat(),
            "kind": kind,
            "source": "zk_push",
            "status": "approved",
            "created_at": now_iso(),
            "raw": p,
        }
        # Iter 583 — duplicate-punch window: raw punch kept, marked duplicate.
        if _zk_dedup_min > 0:
            _dup = await db.attendance.find_one({
                "user_id": u["user_id"],
                "at": {"$gte": (at_dt - timedelta(minutes=_zk_dedup_min)).isoformat(),
                       "$lte": (at_dt + timedelta(minutes=_zk_dedup_min)).isoformat()},
                "status": {"$in": ["approved", "pending", "held", "blocked"]},
            }, {"_id": 1})
            if _dup:
                rec["status"] = "duplicate"
                rec["duplicate_reason"] = f"within_{_zk_dedup_min}min"
        # Iter 581 — central onboarding eligibility engine (may HOLD/BLOCK).
        try:
            from shared.attendance_eligibility import bulk_apply as _elig_bulk
            await _elig_bulk(db, body.company_id, [rec])
        except Exception:
            logger.exception("[iter581] zk_push eligibility check failed")
        try:
            await db.attendance.insert_one(rec)
            inserted += 1
            broadcast_events.append({
                "type": "punch.created",
                "user_id": u["user_id"],
                "employee_name": u.get("name"),
                "bio_code": bc,
                "date": rec["date"],
                "at": rec["at"],
                "kind": rec["kind"],
                "source": "zk_push",
            })
        except Exception as exc:
            logger.warning("zk push insert failed for %s: %s", bc, exc)

    # Fan out to the firm channel (best-effort, non-blocking).
    for ev in broadcast_events:
        try:
            await _ws_broker.broadcast_firm(body.company_id, ev)
        except Exception:
            pass

    return {"accepted": inserted, "seen": len(body.punches)}


# ==========================================================================
# Iter 84 — Actual Salary Process (new pipeline).
#
# Motivated by the redesigned 20-column inline-editable Actual Salary
# Process grid on the web portal. Formulas were agreed with the client:
#   Basic Salary    = Basic × (P Days / Month Days)
#   W.Basic Salary  = Basic × P Hours / (Month Days × Duty HRS)
#   Total Gross     = W.Basic Salary + Oth. Allo.
#   EPF             = 12% × Basic Salary
#   ESI             = 0.75% × Total Gross   (ONLY if Total Gross ≤ 21000)
#   Net Pay         = Total Gross − (EPF + ESI + Adv + TDS)
#
# Attendance Source:
#   • "biometric" → P Days & P Hours pulled from monthly-grid (read-only)
#   • "manual"    → P Days & P Hours default to 0, admin types them
#
# Runs are persisted in the ``salary_runs`` collection with
# ``run_type="actual"``. Rows can be inline-edited (auto-save) until the
# admin taps "Finalize", after which the run becomes read-only.
# ==========================================================================




app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Iter 307 (perf) — gzip every JSON response above 1 KB. Salary run /
# register payloads shrink ~10×, which is the single biggest win for the
# "portal feels slow with lots of data" report on slower connections.
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402
app.add_middleware(GZipMiddleware, minimum_size=1024)



@api.get("/pincode/{pin}")
async def pincode_lookup(pin: str):
    """Iter 107 — India PIN code → State / District auto-fill.
    Proxies api.postalpincode.in with a small Mongo cache."""
    pin = (pin or "").strip()
    if not re.match(r"^\d{6}$", pin):
        raise HTTPException(status_code=400, detail="PIN code must be 6 digits")
    cached = await db.pincode_cache.find_one({"pin": pin}, {"_id": 0})
    if cached:
        return cached["data"]
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"https://api.postalpincode.in/pincode/{pin}")
            payload = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail="PIN lookup service unreachable")
    offices = (payload[0].get("PostOffice") or []) if isinstance(payload, list) and payload else []
    if not offices:
        data = {"ok": False, "pin": pin, "state": "", "district": "", "post_offices": []}
    else:
        first = offices[0]
        data = {
            "ok": True,
            "pin": pin,
            "state": first.get("State") or "",
            "district": first.get("District") or "",
            "post_offices": [o.get("Name") for o in offices[:15]],
        }
    await db.pincode_cache.update_one(
        {"pin": pin}, {"$set": {"pin": pin, "data": data, "cached_at": now_iso()}}, upsert=True)
    return data


# ---------------------------------------------------------------------------
# Iter 109 — Employee DRAFTS: park a partially-filled Add-Employee form and
# resume it later; review-before-create flow deletes the draft on success.
# ---------------------------------------------------------------------------
def _draft_scope_ok(admin: dict, company_id: str) -> bool:
    if admin["role"] in ("super_admin",):
        return True
    if admin["role"] == "sub_admin":
        return sub_admin_can_touch_company(admin, company_id)
    return admin.get("company_id") == company_id


@api.get("/admin/employee-drafts")
async def list_employee_drafts(
    company_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if not _draft_scope_ok(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm not in your scope")
    drafts = [d async for d in db.employee_drafts.find(
        {"company_id": company_id}, {"_id": 0}).sort("updated_at", -1).limit(30)]
    return {"drafts": drafts}


@api.post("/admin/employee-drafts")
async def save_employee_draft(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    company_id = (payload.get("company_id") or "").strip()
    form = payload.get("form")
    if not company_id or not isinstance(form, dict):
        raise HTTPException(status_code=400, detail="company_id and form are required")
    if not _draft_scope_ok(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm not in your scope")
    draft_id = (payload.get("draft_id") or "").strip() or f"draft_{uuid.uuid4().hex[:12]}"
    await db.employee_drafts.update_one(
        {"draft_id": draft_id},
        {"$set": {
            "draft_id": draft_id, "company_id": company_id, "form": form,
            "label": (form.get("name") or "Unnamed draft")[:80],
            "saved_by": admin["user_id"], "updated_at": now_iso(),
        }},
        upsert=True)
    return {"ok": True, "draft_id": draft_id}


@api.delete("/admin/employee-drafts/{draft_id}")
async def delete_employee_draft(
    draft_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    d = await db.employee_drafts.find_one({"draft_id": draft_id}, {"_id": 0, "company_id": 1})
    if not d:
        raise HTTPException(status_code=404, detail="Draft not found")
    if not _draft_scope_ok(admin, d["company_id"]):
        raise HTTPException(status_code=403, detail="Firm not in your scope")
    await db.employee_drafts.delete_one({"draft_id": draft_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Iter 127 — GLOBAL AUDIT LOCK (Monthly Challan Summary).
# When a firm's Challan Summary remark contains "audit", every data-entry
# request (POST/PUT/PATCH/DELETE) that targets that firm is rejected with
# HTTP 423 until the Super Admin clears the remark. Employees keep punching
# attendance — the lock applies to admin / sub-admin / company-admin entry.
# ---------------------------------------------------------------------------
_audit_lock_cache: Dict[str, Any] = {"ids": frozenset(), "exp": 0.0}


def bust_audit_lock_cache() -> None:
    """Called by routes/challan_summary.py right after a remark changes."""
    _audit_lock_cache["exp"] = 0.0


async def _audit_locked_company_ids() -> frozenset:
    import time as _time
    if _time.time() >= _audit_lock_cache["exp"]:
        try:
            docs = await db.challan_summaries.find(
                {"is_audit": True}, {"_id": 0, "company_id": 1}).to_list(1000)
            _audit_lock_cache["ids"] = frozenset(
                d["company_id"] for d in docs if d.get("company_id"))
        except Exception:
            logger.exception("[audit-lock] failed to refresh locked-firm cache")
        _audit_lock_cache["exp"] = _time.time() + 20
    return _audit_lock_cache["ids"]


@app.middleware("http")
async def _audit_lock_guard(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and \
            request.url.path.startswith("/api"):
        try:
            locked = await _audit_locked_company_ids()
        except Exception:
            locked = frozenset()
        if locked:
            path = request.url.path
            # Sending a summary email is not data entry — always allowed.
            if path.endswith("/send-email"):
                return await call_next(request)
            target = None
            for cid in locked:
                if cid and cid in path:
                    target = cid
                    break
            if not target:
                qcid = request.query_params.get("company_id")
                if qcid and qcid in locked:
                    target = qcid
            if not target:
                try:
                    # Starlette's BaseHTTPMiddleware (_CachedRequest) caches
                    # the body read here and replays it downstream — safe.
                    body_bytes = await request.body()
                except Exception:
                    body_bytes = b""
                if body_bytes:
                    try:
                        data = json.loads(body_bytes)
                        if isinstance(data, dict) and data.get("company_id") in locked:
                            target = data.get("company_id")
                    except (ValueError, UnicodeDecodeError):
                        pass
            if target:
                actor = None
                try:
                    actor = await get_user_from_token(
                        request.headers.get("authorization"))
                except Exception:
                    actor = None
                role = (actor or {}).get("role")
                # Super Admin manages the lock; employees keep punching.
                if role not in ("super_admin", "employee"):
                    return JSONResponse(
                        status_code=423,
                        content={"detail": (
                            "This firm is under AUDIT lock — data entry is "
                            "disabled until the Super Admin removes the "
                            "Audit remark in the Monthly Challan Summary."
                        )},
                    )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Iter 247 (user request) — FULL user activity log. Every WRITE action
# (create/update/delete), login and report download by ANY logged-in user
# (super/sub/company admin or employee) is recorded in `activity_log`
# with date + time, actor, action and a sanitized payload summary.
# The Users Log Report reads this collection.
# ---------------------------------------------------------------------------
_ACT_SKIP = ("/temp-code-bundle", "/portal-rpa/frame", "/health", "/db-viewer")
_ACT_SENSITIVE = ("pin", "password", "token", "otp", "captcha", "secret")
_ACT_VERB = {"POST": "CREATE", "PUT": "UPDATE", "PATCH": "UPDATE", "DELETE": "DELETE"}

# Iter 568 — Detailed Audit Trail: field-level old→new diff support.
from shared.audit import (  # noqa: E402
    match_resource as _audit_match,
    compute_changes as _audit_changes,
    snapshot as _audit_snapshot,
    record_label as _audit_label,
    derive_module as _audit_module,
)


@app.middleware("http")
async def _activity_logger(request: Request, call_next):
    path = request.url.path
    method = request.method
    is_mut = method in ("POST", "PUT", "PATCH", "DELETE")
    is_dl = method == "GET" and any(
        s in path for s in (".xlsx", ".pdf", ".csv", ".txt", "/export", "/download"))
    should = path.startswith("/api") and (is_mut or is_dl) \
        and not any(s in path for s in _ACT_SKIP)
    raw = b""
    if should and is_mut:
        try:
            # Starlette caches the body and replays it downstream — safe.
            raw = await request.body()
        except Exception:
            raw = b""
    # Iter 568 — pre-fetch the OLD document for UPDATE/DELETE on known
    # resources so we can record field-level old→new value diffs.
    old_doc = None
    res_match = None
    if should and method in ("PUT", "PATCH", "DELETE"):
        try:
            res_match = _audit_match(path)
            if res_match:
                coll, id_field, rec_id, _mod = res_match
                old_doc = await db[coll].find_one({id_field: rec_id}, {"_id": 0})
        except Exception:
            old_doc = None
    response = await call_next(request)
    if not should:
        return response
    try:
        actor = None
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            tok = auth.split(" ", 1)[1].strip()
            sess = await db.user_sessions.find_one(
                {"session_token": tok}, {"_id": 0, "user_id": 1})
            if sess:
                actor = await db.users.find_one(
                    {"user_id": sess["user_id"]},
                    {"_id": 0, "user_id": 1, "name": 1, "role": 1, "company_id": 1})
        # Anonymous calls are only logged for login/auth endpoints.
        if not actor and "/auth/" not in path:
            return response
        # Login has no token yet — resolve the actor from the email/phone
        # in the (already-read) body so LOGIN rows show WHO logged in.
        if not actor and raw:
            try:
                _d = json.loads(raw)
                _ors = []
                if _d.get("email"):
                    _ors.append({"email": str(_d["email"]).strip().lower()})
                if _d.get("phone"):
                    _ors.append({"phone": str(_d["phone"]).strip()})
                if _ors:
                    actor = await db.users.find_one(
                        {"$or": _ors},
                        {"_id": 0, "user_id": 1, "name": 1, "role": 1, "company_id": 1})
            except (ValueError, UnicodeDecodeError):
                pass
        cid = request.query_params.get("company_id")
        summary = ""
        body_data = None
        if raw and len(raw) < 200_000:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    body_data = data
                    cid = cid or data.get("company_id")
                    parts = []
                    for k, v in data.items():
                        if any(s in k.lower() for s in _ACT_SENSITIVE):
                            continue
                        # Iter 572 — internal IDs are noise in the report
                        # (firm/user names are shown separately).
                        if k.lower() == "id" or k.lower().endswith("_id"):
                            continue
                        if isinstance(v, (str, int, float, bool)) and str(v).strip():
                            parts.append(f"{k}={str(v)[:40]}")
                        if len(parts) >= 8:
                            break
                    summary = ", ".join(parts)
            except (ValueError, UnicodeDecodeError):
                pass
        if is_dl:
            verb = "DOWNLOAD"
        elif "/auth/" in path:
            verb = "LOGIN" if "login" in path.lower() else "AUTH"
        else:
            verb = _ACT_VERB.get(method, method)
        # Iter 568 — Detailed Audit Trail extras: field-level diffs,
        # module, record label, device and success flag.
        ok = response.status_code < 400
        changes = []
        old_values = None
        new_values = None
        rec_id = None
        rec_label = ""
        module = _audit_module(path)
        if res_match:
            _coll, _idf, rec_id, module = res_match
        if ok and method in ("PUT", "PATCH") and old_doc is not None and body_data:
            changes = _audit_changes(old_doc, body_data)
            rec_label = _audit_label(old_doc)
        elif ok and method == "DELETE" and old_doc is not None:
            old_values = _audit_snapshot(old_doc)
            rec_label = _audit_label(old_doc)
        elif ok and method == "POST" and body_data and verb == "CREATE":
            new_values = _audit_snapshot(body_data)
            rec_label = _audit_label(body_data)
        cid = cid or (old_doc or {}).get("company_id")
        audit_doc = {
            "at": now_iso(),
            "actor_id": (actor or {}).get("user_id"),
            "actor_name": (actor or {}).get("name"),
            "actor_role": (actor or {}).get("role"),
            "company_id": cid or (actor or {}).get("company_id"),
            "method": method,
            "path": path[:300],
            "action": f"{verb} {path[4:][:200]}",
            "status": response.status_code,
            "success": ok,
            "module": module,
            "record_id": rec_id,
            "record_label": rec_label,
            "changes": changes,
            "old_values": old_values,
            "new_values": new_values,
            "details": summary[:400],
            "device": (request.headers.get("user-agent") or "")[:200],
            "ip": ((request.headers.get("x-forwarded-for")
                    or (request.client.host if request.client else "") or "")
                   .split(",")[0].strip()),
        }
        await db.activity_log.insert_one(dict(audit_doc))
        # Iter 580 — instant email alerts for critical activities.
        try:
            from routes.audit_notify import on_audit_event
            asyncio.create_task(on_audit_event(audit_doc))
        except Exception:
            pass
    except Exception:
        logger.warning("[activity-log] failed to record", exc_info=True)
    return response


# Iter 85 (fix) — register the API router LAST so every @api.* decorator
# defined anywhere in this module gets attached to the FastAPI app.
app.include_router(api)

# Iter 409 — Sub-admins / Masters + Compliance-Policy / Statutory Bonus
# extracted to their own modules. Two mobile/PIN helpers and the bonus
# compute function are imported back because other route modules still
# import them from server (company_roles.py, statutory_registers.py).
from routes.sub_admins import (  # noqa: E402
    router as sub_admins_router,
    _clean_mobile_or_400,  # noqa: F401
    _validate_pin_or_400,  # noqa: F401
)
app.include_router(sub_admins_router)
from routes.masters_policy import router as masters_policy_router  # noqa: E402
app.include_router(masters_policy_router)
from routes.bonus import (  # noqa: E402
    router as bonus_router,
    _compute_bonus_run,  # noqa: F401
)
app.include_router(bonus_router)
# Iter 417 — Smart Punch GPS diagnostics (device logs + admin dashboard).
from routes.gps_diagnostics import router as gps_diagnostics_router  # noqa: E402
app.include_router(gps_diagnostics_router)
# Iter 569 — 2FA/MFA for Super/Sub admin logins.
from routes.twofa import router as twofa_router  # noqa: E402
app.include_router(twofa_router)
# Iter 576 — MSG91 SMS notifications (Phase 1).
from routes.sms_notifications import router as sms_notifications_router  # noqa: E402
app.include_router(sms_notifications_router)
# Iter 580 — Audit & Activity email notifications.
from routes.audit_notify import router as audit_notify_router, daily_loop as _audit_daily_loop  # noqa: E402
app.include_router(audit_notify_router)
# Iter 581 — Onboarding-based attendance eligibility (HR release workflow).
from routes.attendance_eligibility import router as attendance_eligibility_router  # noqa: E402
app.include_router(attendance_eligibility_router)
# Iter 585 — RBAC Phase 1: Department Master, data scope, Access Preview.
from routes.rbac_phase1 import router as rbac_phase1_router  # noqa: E402app.include_router(rbac_phase1_router)
from routes.maker_checker import router as maker_checker_router, digest_loop as _mc_digest_loop  # noqa: E402
app.include_router(maker_checker_router)
# Iter 588 — AI Command Center (alerts / insights / activity).
from routes.ai_command_center import router as ai_cc_router  # noqa: E402
app.include_router(ai_cc_router)
# Iter 589 — AI bulk-action engine (preview → approval → execute).
from routes.ai_bulk_actions import router as ai_bulk_router  # noqa: E402
app.include_router(ai_bulk_router)


@app.on_event("startup")
async def _start_audit_daily_loop():
    asyncio.create_task(_audit_daily_loop())
    # Iter 587b — daily 09:00 IST digest of >24h pending approvals.
    asyncio.create_task(_mc_digest_loop())
# Iter 409 — Actual (legacy) Salary Runs extracted to routes/salary_runs.py.
# _payslip_rows_for_month is imported back because the WhatsApp engine
# accesses it as a server attribute (srv._payslip_rows_for_month).
# _sort_export_rows moved to shared/sorting.py; re-exported for any
# legacy `from server import _sort_export_rows` callers.
from routes.salary_runs import (  # noqa: E402
    router as salary_runs_router,
    _payslip_rows_for_month,  # noqa: F401
)
from shared.sorting import _sort_export_rows  # noqa: E402, F401
app.include_router(salary_runs_router)


# Iter 86 — Modularization: include extracted route modules AFTER the
# monolithic `api` router.  Each `routes/*.py` module declares its own
# `APIRouter(prefix="/api")` and pulls shared helpers (`db`,
# `get_user_from_token`, `require_role`) from this file by name — safe
# because those names are already bound by the time we get here.
# Iter 398/399 — Attendance split into three modules + shared/dates.py.
# Only the helpers server.py itself still calls are imported back here;
# every other route module now imports from shared.dates / the modules
# directly.
from routes.attendance_core import (  # noqa: E402
    router as attendance_core_router,
    _onboarding_login_gate,  # noqa: F401
)
app.include_router(attendance_core_router)
# Iter 409 — punch approvals + employee history/selfie/my-month/summary
# split out of attendance_core into their own module.
from routes.attendance_self_service import (  # noqa: E402
    router as attendance_self_service_router,
)
app.include_router(attendance_self_service_router)
from routes.attendance_admin_core import (  # noqa: E402
    router as attendance_admin_core_router,
    AUTO_CLOSE_TICK_SECONDS,  # noqa: F401
    _auto_close_open_shifts,  # noqa: F401
)
app.include_router(attendance_admin_core_router)
from routes.payroll_core import (  # noqa: E402
    router as payroll_core_router,
    _compute_payroll_run,  # noqa: F401
)
app.include_router(payroll_core_router)
from routes.reports_extra import router as reports_extra_router  # noqa: E402
from routes.tickets import router as tickets_router  # noqa: E402
from routes.notifications import router as notifications_router  # noqa: E402
from routes.gmail_mailbox import router as gmail_mailbox_router  # noqa: E402
from routes.attendance_master import router as attendance_master_router  # noqa: E402
from routes.leaves import router as leaves_router  # noqa: E402
from routes.payslips import router as payslips_router  # noqa: E402
from routes.attendance_policy import router as attendance_policy_router  # noqa: E402
from routes.compliance_docs import router as compliance_docs_router  # noqa: E402
from routes.shift_masters import router as shift_masters_router  # noqa: E402
from routes.messages import router as messages_router  # noqa: E402
from routes.firm_master import router as firm_master_router  # noqa: E402
from routes.firm_master_v2 import router as firm_master_v2_router  # noqa: E402
from routes.portal_generation import router as portal_generation_router  # noqa: E402
from routes.employee_salary import router as employee_salary_router  # noqa: E402
from routes.master_data_report import router as master_data_report_router  # noqa: E402
from routes.employee_profile import router as employee_profile_router  # noqa: E402
from routes.compliance_reports import router as compliance_reports_router  # noqa: E402
from routes.employee_kyc import router as employee_kyc_router  # noqa: E402
from routes.ocr import router as ocr_router  # noqa: E402
from routes.challans import router as challans_router  # noqa: E402
from routes.biometric_devices import router as biometric_devices_router  # noqa: E402
from routes.biometric_sdk import router as biometric_sdk_router  # noqa: E402
from routes.super_admins import router as super_admins_router  # noqa: E402
from routes.admin_credentials import router as admin_credentials_router  # noqa: E402
from routes.hr_letters import router as hr_letters_router  # noqa: E402
from routes.statutory_registers import router as statutory_registers_router  # noqa: E402
from routes.compliance_import import router as compliance_import_router  # noqa: E402
from routes.arrear_salary import router as arrear_salary_router  # noqa: E402
from routes.email_notifications import router as email_notifications_router  # noqa: E402
from routes.shift_change import router as shift_change_router  # noqa: E402
from routes.db_viewer import router as db_viewer_router  # noqa: E402
from routes.contribution_reports import router as contribution_reports_router  # noqa: E402
from routes.deletion_approvals import router as deletion_approvals_router  # noqa: E402
from routes.employee_full_report import router as employee_full_report_router  # noqa: E402
from routes.temp_bundle import router as temp_bundle_router  # noqa: E402
from routes.user_prefs import router as user_prefs_router  # noqa: E402
from routes.challan_summary import router as challan_summary_router  # noqa: E402
from routes.compliance_settings import router as compliance_settings_router  # noqa: E402
from routes.compliance_validation import router as compliance_validation_router  # noqa: E402
from routes.attendance_sync_dashboard import router as attendance_sync_dash_router  # noqa: E402


from utils.rpa_worker import maybe_start as maybe_start_rpa_worker  # noqa: E402

app.include_router(reports_extra_router)
from routes.policy_simulator import router as policy_simulator_router  # noqa: E402
app.include_router(policy_simulator_router)
app.include_router(tickets_router)
app.include_router(notifications_router)
app.include_router(gmail_mailbox_router)
from routes.email_audit_agent import router as email_audit_agent_router  # noqa: E402
app.include_router(email_audit_agent_router)
app.include_router(attendance_master_router)
app.include_router(leaves_router)
app.include_router(payslips_router)
app.include_router(attendance_policy_router)
app.include_router(compliance_docs_router)
app.include_router(shift_masters_router)
app.include_router(messages_router)
app.include_router(firm_master_router)
app.include_router(firm_master_v2_router)
app.include_router(portal_generation_router)
app.include_router(employee_salary_router)
app.include_router(master_data_report_router)
app.include_router(employee_profile_router)
app.include_router(compliance_reports_router)
app.include_router(employee_kyc_router)
app.include_router(ocr_router)
from routes.ocr import user_router as ocr_user_router  # noqa: E402
app.include_router(ocr_user_router)
app.include_router(challans_router)
app.include_router(biometric_devices_router)
app.include_router(biometric_sdk_router)
app.include_router(super_admins_router)
app.include_router(admin_credentials_router)
app.include_router(hr_letters_router)
app.include_router(statutory_registers_router)
app.include_router(compliance_import_router)
app.include_router(arrear_salary_router)
app.include_router(email_notifications_router)
app.include_router(shift_change_router)
app.include_router(db_viewer_router)
app.include_router(contribution_reports_router)
app.include_router(deletion_approvals_router)
app.include_router(employee_full_report_router)
app.include_router(temp_bundle_router)
app.include_router(user_prefs_router)
app.include_router(challan_summary_router)
from routes.ot_salary import router as ot_salary_router  # noqa: E402
app.include_router(ot_salary_router)
from routes.punch_logs import router as punch_logs_router  # noqa: E402
app.include_router(punch_logs_router)
from routes.employee_photos import router as employee_photos_router  # noqa: E402
app.include_router(employee_photos_router)

# Iter 496 — Universal Report Table engine: per-user saved layouts.
from routes.report_prefs import router as report_prefs_router  # noqa: E402
app.include_router(report_prefs_router)

# Iter 497 — Universal Report PDF export (screen-matching landscape PDFs).
from routes.report_export import router as report_export_router  # noqa: E402
app.include_router(report_export_router)

# Iter 499 — Factory & Boiler Annual Return (unified current+legacy data).
from routes.factory_returns import router as factory_returns_router  # noqa: E402
app.include_router(factory_returns_router)

# Iter 500 — CTC Management module Phase 1 (additive; Gross engine untouched).
from routes.ctc_module import router as ctc_router  # noqa: E402
app.include_router(ctc_router)
# Iter 501 — Client Attendance Import (attendance summary Excel; additive).
from routes.client_attendance_import import router as client_att_router  # noqa: E402
app.include_router(client_att_router)
from routes.web_push import router as web_push_router  # noqa: E402
app.include_router(web_push_router)
from routes.sheet_verification import router as sheet_verification_router  # noqa: E402
app.include_router(sheet_verification_router)
from routes.db_backup import router as db_backup_router  # noqa: E402
app.include_router(db_backup_router)
from routes.locations import router as locations_router  # noqa: E402
app.include_router(locations_router)
from routes.pf_reports import router as pf_reports_router  # noqa: E402
app.include_router(pf_reports_router)
from routes.attendance_doctor import router as attendance_doctor_router  # noqa: E402
app.include_router(attendance_doctor_router)
# Iter 545 — Multiple Punch Report + Punch Exception Log.
from routes.punch_policy_report import router as punch_policy_report_router  # noqa: E402
app.include_router(punch_policy_report_router)
# Iter 551 — Form 16 module (Phase 1) + Features List PDF.
from routes.form16 import router as form16_router  # noqa: E402
from routes.form16 import ess_router as form16_ess_router  # noqa: E402
app.include_router(form16_router)
app.include_router(form16_ess_router)
from routes.features_pdf import router as features_pdf_router  # noqa: E402
app.include_router(features_pdf_router)
from routes.portal_rpa import router as portal_rpa_router  # noqa: E402
app.include_router(portal_rpa_router)
from routes.uan_esic_import import router as uan_esic_import_router  # noqa: E402
app.include_router(uan_esic_import_router)
app.include_router(compliance_settings_router)
app.include_router(compliance_validation_router)
app.include_router(attendance_sync_dash_router)
# Iter 394 — Compliance Salary Runs extracted to its own module. The four
# helpers are imported back because legacy endpoints in this file still
# call them (offline-salary gating, biometric flag, head masks, firm
# salary permission).
from routes.compliance_salary_runs import (  # noqa: E402
    router as compliance_salary_runs_router,
    _ensure_firm_head_masks,  # noqa: F401
    _firm_biometric_attendance_enabled,  # noqa: F401
    _firm_offline_salary_enabled,  # noqa: F401
    _require_firm_salary_permission,  # noqa: F401
)
app.include_router(compliance_salary_runs_router)
# Iter 396 — Actual Salary Process extracted to its own module.
from routes.actual_salary_process import router as actual_salary_router  # noqa: E402
app.include_router(actual_salary_router)
# Iter 397 — Attendance policy + report-export APIs extracted.
from routes.attendance_policy_api import router as attendance_policy_router  # noqa: E402
app.include_router(attendance_policy_router)
from routes.attendance_reports_api import router as attendance_reports_router  # noqa: E402
app.include_router(attendance_reports_router)
# Iter 397 — Attendance location/flags APIs extracted. The status helper is
# imported back because the punch history endpoints in this file still use it.
from routes.attendance_location_api import (  # noqa: E402
    router as attendance_location_router,
    _compute_location_status,  # noqa: F401
)
app.include_router(attendance_location_router)
# Iter 397 — Employees admin (create / bulk-import / delete) extracted.
# Two helpers imported back: _employee_is_resigned is used by the admin
# reassignment endpoint above; delete_employee_record is imported lazily
# by routes/deletion_approvals.py via `from server import ...`.
from routes.employees_admin import (  # noqa: E402
    router as employees_admin_router,
    _employee_is_resigned,  # noqa: F401
    delete_employee_record,  # noqa: F401
)
app.include_router(employees_admin_router)
# Iter 475 — Employee Rejoin (rehire) module.
from routes.employee_rejoin import router as employee_rejoin_router  # noqa: E402
app.include_router(employee_rejoin_router)
# Iter 395 — WhatsApp Business Cloud API Notification Engine.
from routes.whatsapp_center import router as whatsapp_center_router  # noqa: E402
app.include_router(whatsapp_center_router)
from routes.report_formats import router as report_formats_router  # noqa: E402
app.include_router(report_formats_router)
from routes.punch_import import router as punch_import_router  # noqa: E402
app.include_router(punch_import_router)
from routes.contractor_punches import router as contractor_punches_router  # noqa: E402
app.include_router(contractor_punches_router)
from routes.labour_reports import router as labour_reports_router  # noqa: E402
app.include_router(labour_reports_router)
from routes.labour_cost import router as labour_cost_router  # noqa: E402
app.include_router(labour_cost_router)
from routes.portal_dashboard import router as portal_dashboard_router  # noqa: E402
app.include_router(portal_dashboard_router)
from routes.portal_phase2 import router as portal_phase2_router  # noqa: E402
app.include_router(portal_phase2_router)
from routes.salary_audit import router as salary_audit_router  # noqa: E402
app.include_router(salary_audit_router)
from routes.kyc_tracker import router as kyc_tracker_router  # noqa: E402
app.include_router(kyc_tracker_router)
from routes.employee_documents import router as employee_documents_router  # noqa: E402
app.include_router(employee_documents_router)
from routes.advances import router as advances_router  # noqa: E402
app.include_router(advances_router)
from routes.company_roles import router as company_roles_router  # noqa: E402
app.include_router(company_roles_router)
from routes.approvals_engine import router as approvals_engine_router  # noqa: E402
app.include_router(approvals_engine_router)

from routes.salary_readiness import router as salary_readiness_router  # noqa: E402
app.include_router(salary_readiness_router)

from routes.portal_extension import router as portal_extension_router  # noqa: E402
app.include_router(portal_extension_router)

from routes.clra_registers import router as clra_registers_router  # noqa: E402
app.include_router(clra_registers_router)

from routes.geo_policy import router as geo_policy_router  # noqa: E402
app.include_router(geo_policy_router)

from routes.geofence_reports import router as geofence_reports_router  # noqa: E402
app.include_router(geofence_reports_router)

from routes.proposals import router as proposals_router  # noqa: E402
app.include_router(proposals_router)

from routes.bulk_ops import router as bulk_ops_router  # noqa: E402
app.include_router(bulk_ops_router)

from routes.statutory_extra_reports import router as statutory_extra_reports_router  # noqa: E402
app.include_router(statutory_extra_reports_router)

from routes.shift_change_v2 import router as shift_change_v2_router  # noqa: E402
app.include_router(shift_change_v2_router)
from routes.comp_off import router as comp_off_router  # noqa: E402
app.include_router(comp_off_router)

# Iter 285 — Employee Onboarding Approval Workflow (Phase 1).
from routes.onboarding_approval import router as onboarding_approval_router  # noqa: E402
app.include_router(onboarding_approval_router)

# Iter 286 — Access & Workflow Management (Phase A).
from routes.access_management import router as access_management_router  # noqa: E402
app.include_router(access_management_router)

# Iter 267 — Real-Time ZKTeco Multi-Device Synchronization Engine (Phase 1).
from routes.sync_engine import router as sync_engine_router  # noqa: E402
app.include_router(sync_engine_router)

# Iter 292 — Monthly In/Out & OT Matrix report + Employee Reports hub.
from routes.inout_ot_matrix import router as inout_ot_matrix_router  # noqa: E402
app.include_router(inout_ot_matrix_router)
# Iter 521 (user request) — Present/Absent report per firm attendance policy.
from routes.present_absent_report import router as present_absent_router  # noqa: E402
app.include_router(present_absent_router)
from routes.present_absent_ot import router as present_absent_ot_router  # noqa: E402
app.include_router(present_absent_ot_router)
from routes.daily_verification import router as daily_verification_router  # noqa: E402
app.include_router(daily_verification_router)
from routes.pf_contribution_report import router as pf_contribution_router  # noqa: E402
app.include_router(pf_contribution_router)
from routes.employee_reports_hub import router as employee_reports_hub_router  # noqa: E402
app.include_router(employee_reports_hub_router)

# Iter 294 — AI Payroll Assistant (voice/NL commands) + Global Search.
from routes.ai_assistant import router as ai_assistant_router  # noqa: E402
from routes.ai_layer import router as ai_layer_router  # noqa: E402
app.include_router(ai_layer_router)
app.include_router(ai_assistant_router)
from routes.productivity import router as productivity_router  # noqa: E402
app.include_router(productivity_router)

# Iter 294 — Bank salary-transfer upload files + Power BI / Excel data feed.
from routes.bank_transfer_files import router as bank_transfer_router  # noqa: E402
app.include_router(bank_transfer_router)
from routes.bi_feed import router as bi_feed_router  # noqa: E402
app.include_router(bi_feed_router)

# Iter 299 — Legacy SQL Server Explorer (read-only browse before import).
from routes.legacy_explorer import router as legacy_explorer_router  # noqa: E402
app.include_router(legacy_explorer_router)

# Iter 300 — Legacy Import Wizard (firm mapping + head-wise selection).
from routes.legacy_import import router as legacy_import_router  # noqa: E402
app.include_router(legacy_import_router)

# Iter 305 — Enterprise Salary Register (dynamic heads, exports).
from routes.salary_register import router as salary_register_router  # noqa: E402
app.include_router(salary_register_router)

# Iter 310 — Employee Master Detail Slip (A4 slip, PDF/Excel/Email, QR).
from routes.employee_detail_slip import router as employee_detail_slip_router  # noqa: E402
app.include_router(employee_detail_slip_router)

# Iter 313 — ESIC Leave Module (certificates, approval, payroll link).
from routes.esic_leave import router as esic_leave_router  # noqa: E402
app.include_router(esic_leave_router)

# Iter 356 — Employee-Wise Yearly Payroll Register (Bonus-Register style).
from routes.payroll_register import router as payroll_register_router  # noqa: E402
app.include_router(payroll_register_router)

# Iter 357 — Phase B/C/D: Labour Statistics, Annual Returns, Factory & Boilers.
from routes.labour_statistics import router as labour_stats_router  # noqa: E402
app.include_router(labour_stats_router)
from routes.central_statistical import router as central_stats_router  # noqa: E402
app.include_router(central_stats_router)
from routes.manual_attendance import router as manual_att_router  # noqa: E402
app.include_router(manual_att_router)
from routes.annual_returns import router as annual_returns_router  # noqa: E402
app.include_router(annual_returns_router)
from routes.factory_compliance import router as factory_router  # noqa: E402
app.include_router(factory_router)

# Iter 358 — Payroll Reports section (comparison, revision, CTC, F&F …).
from routes.payroll_reports import router as payroll_reports_router  # noqa: E402
app.include_router(payroll_reports_router)
from routes.govt_audit_reports import govt_router, audit_router  # noqa: E402
from routes.contractors import router as contractors_router  # noqa: E402
from routes.clra_labour_reports import router as clra_reports_router  # noqa: E402
from routes.scheduled_reports import router as scheduled_reports_router  # noqa: E402
app.include_router(govt_router)
app.include_router(audit_router)
app.include_router(contractors_router)
app.include_router(clra_reports_router)
app.include_router(scheduled_reports_router)

# Iter 527 — Central Contractor Wage Registers (Form A–D).
from routes.central_wage_registers import router as cwr_router  # noqa: E402
app.include_router(cwr_router)

# Iter 529 — Monthly Payroll Attendance & Salary Report.
from routes.monthly_payroll_report import router as monthly_payroll_router  # noqa: E402
app.include_router(monthly_payroll_router)

# Iter 530 — Quick User Manual PDF (super admin only).
from routes.user_manual import router as user_manual_router  # noqa: E402
app.include_router(user_manual_router)

# Iter 359 — PF & ESIC Claims Management.
from routes.claims_management import router as claims_router  # noqa: E402
app.include_router(claims_router)

from routes.ai_universal_import import router as ai_uimport_router  # noqa: E402
app.include_router(ai_uimport_router)

from routes.backup_center import router as backup_center_router  # noqa: E402
app.include_router(backup_center_router)

from routes.ai_salary_compliance import router as ai_salcomp_router  # noqa: E402
app.include_router(ai_salcomp_router)

from routes.punch_push_api import router as punch_push_api_router  # noqa: E402
app.include_router(punch_push_api_router)

# Iter 601 — Face Verification (enrollment) + WebAuthn device lock.
from routes.face_verification import router as face_verification_router  # noqa: E402
app.include_router(face_verification_router)
from routes.webauthn_devices import router as webauthn_devices_router  # noqa: E402
app.include_router(webauthn_devices_router)
# Iter 602 — secure face-punch verification flow.
from routes.face_punch import router as face_punch_router  # noqa: E402
app.include_router(face_punch_router)
# Iter 604 — Expense Claims module (Phase 1).
from routes.expense_claims import router as expense_claims_router  # noqa: E402
app.include_router(expense_claims_router)
# Iter 706 — Official Tour Management (request → approval → GPS tracking →
# visits → expenses → OD attendance → payroll traceability via Tour ID).
from routes.tours import router as tours_router  # noqa: E402
app.include_router(tours_router)
# Iter 707 — Employee PWA centralized Pending Approval Center.
from routes.my_approvals import router as my_approvals_router  # noqa: E402
app.include_router(my_approvals_router)
# Iter 708 — Firm-wise PWA data lifecycle + screenshot protection.
from routes.pwa_data_mgmt import router as pwa_data_mgmt_router  # noqa: E402
app.include_router(pwa_data_mgmt_router)
# Iter 709 — READ-ONLY Payroll Charts & Analytics (no process changes).
from routes.analytics import router as analytics_router  # noqa: E402
app.include_router(analytics_router)

# Iter 610 — Employee Self-Service (ESS): profile, attendance+, shift,
# salary/PF/ESIC, unified requests, notification center.
from routes.ess import router as ess_router  # noqa: E402
app.include_router(ess_router)
# Iter 624 — Multi-branch architecture: branch management, home/authorized
# branches, temp assignments, transfers, cost allocation & dashboard.
from routes.branch_management import router as branch_mgmt_router  # noqa: E402
app.include_router(branch_mgmt_router)

# Iter 89 — Optional background RPA worker for EPFO/ESIC UAN/ESIC
# generation jobs. No-op unless RPA_WORKER_ENABLED=1 in backend/.env.
maybe_start_rpa_worker(app, db)

# Iter 395 — WhatsApp queue worker (always on; no-op until a firm enables
# WhatsApp in its configuration).
from utils.whatsapp_engine import maybe_start as maybe_start_wa_worker  # noqa: E402
maybe_start_wa_worker(app, db, logger)


@app.on_event("shutdown")
async def shutdown():
    client.close()



# Iter 730 — Gate Pass + Late Penalty + F&F Calculator (user request).
from routes.hr_extras import router as hr_extras_router  # noqa: E402
app.include_router(hr_extras_router)
from routes.org_structure import router as org_structure_router  # noqa: E402
app.include_router(org_structure_router)
from routes.ot_management import router as ot_management_router  # noqa: E402
app.include_router(ot_management_router)
from routes.hr_analytics import router as hr_analytics_router  # noqa: E402
app.include_router(hr_analytics_router)

# Iter 731 — Asset Management module (user spec).
from routes.asset_management import router as asset_mgmt_router  # noqa: E402
app.include_router(asset_mgmt_router)

# Iter 733 — Branch extras + state-wise statutory (user request).
from routes.branch_extras import router as branch_extras_router  # noqa: E402
app.include_router(branch_extras_router)

# Iter 737 — Branch Master (complete enhancement)
from routes.branch_master import router as branch_master_router  # noqa: E402
app.include_router(branch_master_router)

# Iter 741 — Probation→Confirmation + Weekoff preview + Accident Master
from routes.probation_weekoff import router as probation_weekoff_router  # noqa: E402
app.include_router(probation_weekoff_router)
from routes.accident_register import router as accident_register_router  # noqa: E402
app.include_router(accident_register_router)
