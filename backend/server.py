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
import asyncio

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

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
# Session lifetime: effectively "never expires" so users stay signed in
# across app opens. If a user wants to sign out they can tap "Sign out".
SESSION_TTL_DAYS = 3650

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
        # Iter 203 (user request) — Half-Day Threshold Rule: worked hrs
        # below the half-day threshold → ALL hrs to OT (0 Present); between
        # threshold and full day → ½ Present Day + remaining hrs to OT.
        # Duty HRS counts ONLY present-day hours.
        "halfday_threshold_rule": _flag("halfday_threshold_rule"),
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

    return {
        "shifts": shifts,
        "weekly_off_days": sorted(days),
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
    shift auto-detected from the first IN punch). Honours BOTH controls:
    the top-level ``shift_mode`` and the Policy Master sub-point
    ``shift_type`` (rotational / open)."""
    p = policy or {}
    if str(p.get("shift_mode") or "").lower() == "open":
        return True
    return str(
        (p.get("policy_master") or {}).get("shift_type") or ""
    ).lower() in ("rotational", "open")


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
    are treated as missing punches. Same for orphan OUTs at the start.
    """
    ps = sorted(
        (p for p in (day_punches or []) if p.get("at") and p.get("kind") in ("in", "out")),
        key=lambda p: p["at"],
    )
    if not ps:
        return False
    open_in = False
    for p in ps:
        k = (p.get("kind") or "").lower()
        if k == "in":
            if open_in:
                return True  # IN → IN without OUT between
            open_in = True
        elif k == "out":
            if not open_in:
                return True  # OUT without preceding IN
            open_in = False
    return open_in  # trailing unclosed IN




def stitch_cross_day_ot(
    punches_by_day: Dict[str, List[dict]],
    max_hours: int = 16,
) -> Dict[str, List[dict]]:
    """Iter 77y — Cross-day OT punch pairing.

    Night-shift OT frequently ends AFTER midnight on the biometric device.
    Example (Sanjeev Kumar, bio 32)::

        01-Jun IN 08:00, OUT 19:58, OT-In 20:08   (unpaired trailing IN)
        02-Jun OT-Out 07:58                       (unpaired leading OUT)

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
        if bal <= 0 or last_kind != "in":
            continue
        next_dk = day_keys[i + 1]
        nxt = out_map.get(next_dk) or []
        if not nxt:
            continue
        nxt_sorted = sorted(nxt, key=lambda p: p.get("at") or "")
        first = nxt_sorted[0]
        if (first.get("kind") or "").lower() != "out":
            continue
        try:
            in_at = _dt.fromisoformat(str(cur_sorted[-1]["at"]).replace("Z", "+00:00"))
            out_at = _dt.fromisoformat(str(first["at"]).replace("Z", "+00:00"))
            if out_at <= in_at or (out_at - in_at) > _td(hours=max_hours):
                continue
        except Exception:
            continue
        moved = dict(first)
        moved["date"] = dk
        moved["_cross_day"] = True
        out_map[dk] = cur_sorted + [moved]
        out_map[next_dk] = nxt_sorted[1:]
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

    # Multi-pair day → second pair (and beyond) is OT.
    if len(pairs) >= 2:
        ot_in = pairs[1][0]
        ot_out = pairs[-1][1]
        return reg_in, reg_out, ot_in, ot_out

    # Single-pair day → arithmetic OT split if the shift is over-length.
    total_min = (reg_out - reg_in).total_seconds() / 60.0
    if split_after_minutes > 0 and total_min > split_after_minutes:
        boundary = reg_in + _td(minutes=split_after_minutes)
        return reg_in, boundary, boundary, reg_out
    return reg_in, reg_out, None, None


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
    if exp_dt < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")
    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
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
    await db.attendance.create_index([("user_id", 1), ("date", -1)])
    await db.leaves.create_index("user_id")
    await db.payslips.create_index([("employee_user_id", 1), ("month", -1)])
    await db.tickets.create_index("user_id")
    await db.notifications.create_index("created_at")


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
    await db.users.update_many(
        {"role": "super_admin", "email": {"$nin": list(SUPER_ADMIN_EMAILS)}},
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
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
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


@api.get("/admin/attendance/flagged")
async def list_flagged_punches(
    company_id: Optional[str] = None,
    limit: int = 100,
    authorization: Optional[str] = Header(None),
):
    """Return recent punches flagged by face-match. company_admin sees
    their company only; super_admin can filter with ?company_id=."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    q: dict = {"identity_flagged": True}
    if user["role"] == "company_admin":
        q["company_id"] = user.get("company_id")
    elif user["role"] == "super_admin" and company_id and company_id != "all":
        q["company_id"] = company_id
    limit = max(1, min(500, int(limit or 100)))
    recs = await db.attendance.find(
        q, {"_id": 0, "selfie_base64": 0, "device_info": 0}
    ).sort("at", -1).to_list(limit)
    # Attach user + company name for display
    uids = list({r.get("user_id") for r in recs if r.get("user_id")})
    users = await db.users.find(
        {"user_id": {"$in": uids}},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "company_id": 1},
    ).to_list(1000) if uids else []
    u_by_id = {u["user_id"]: u for u in users}
    cids = list({u.get("company_id") for u in users if u.get("company_id")})
    companies = await db.companies.find(
        {"company_id": {"$in": cids}}, {"_id": 0, "company_id": 1, "name": 1},
    ).to_list(500) if cids else []
    c_by_id = {c["company_id"]: c["name"] for c in companies}
    for r in recs:
        u = u_by_id.get(r.get("user_id"), {})
        r["user_name"] = u.get("name")
        r["employee_code"] = u.get("employee_code")
        r["company_name"] = c_by_id.get(u.get("company_id"))
    return {"flagged": recs, "count": len(recs)}


# ---------------------------------------------------------------------------
# Iter 64 — Location Audit
# ---------------------------------------------------------------------------
def _compute_location_status(rec: dict) -> str:
    """Back-fill helper: derive location_status for older records that were
    saved before the field existed."""
    if rec.get("location_status"):
        return rec["location_status"]
    if rec.get("gps_verified") is False:
        return "no-gps"
    if rec.get("outside_geofence") is True:
        return "outside"
    return "inside"


@api.get("/admin/attendance/location-audit")
async def list_location_audit(
    company_id: Optional[str] = Query(None),
    company_ids: Optional[List[str]] = Query(
        None, description="Cross-firm filter. Ignored for company_admin.",
    ),
    user_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD (inclusive)"),
    location_status: Optional[str] = Query(
        None,
        description="inside | outside | no-gps. Omit for all.",
    ),
    limit: int = Query(200, ge=1, le=1000),
    authorization: Optional[str] = Header(None),
):
    """Location Audit: filterable list of punches with per-row status.

    Never returns selfie_base64 in the list view to keep payloads light —
    the client fetches the selfie separately from ``/admin/attendance/{id}/selfie``
    if it wants to display the thumbnail.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])

    q: dict = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif company_ids:
        clean = [c for c in company_ids if c]
        if clean:
            q["company_id"] = {"$in": clean}
    elif company_id:
        q["company_id"] = company_id

    if user_id:
        q["user_id"] = user_id
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["date"] = rng
    if location_status in ("inside", "outside", "no-gps"):
        # Newer records have the field set; older ones require the derived
        # equivalent so we still surface them in the audit view.
        if location_status == "inside":
            q["$or"] = [
                {"location_status": "inside"},
                {
                    "location_status": {"$exists": False},
                    "gps_verified": {"$ne": False},
                    "outside_geofence": {"$ne": True},
                },
            ]
        elif location_status == "outside":
            q["$or"] = [
                {"location_status": "outside"},
                {
                    "location_status": {"$exists": False},
                    "outside_geofence": True,
                },
            ]
        elif location_status == "no-gps":
            q["$or"] = [
                {"location_status": "no-gps"},
                {
                    "location_status": {"$exists": False},
                    "gps_verified": False,
                },
            ]

    recs = (
        await db.attendance.find(
            q, {"_id": 0, "selfie_base64": 0, "device_info": 0},
        )
        .sort("at", -1)
        .to_list(limit)
    )

    for r in recs:
        r["location_status"] = _compute_location_status(r)

    # Enrich with user + company names.
    uids = list({r.get("user_id") for r in recs if r.get("user_id")})
    users = (
        await db.users.find(
            {"user_id": {"$in": uids}},
            {
                "_id": 0, "user_id": 1, "name": 1,
                "employee_code": 1, "company_id": 1,
            },
        ).to_list(len(uids))
        if uids
        else []
    )
    u_by_id = {u["user_id"]: u for u in users}
    cids = list({u.get("company_id") for u in users if u.get("company_id")})
    companies = (
        await db.companies.find(
            {"company_id": {"$in": cids}},
            {"_id": 0, "company_id": 1, "name": 1},
        ).to_list(len(cids))
        if cids
        else []
    )
    c_by_id = {c["company_id"]: c["name"] for c in companies}
    for r in recs:
        u = u_by_id.get(r.get("user_id"), {})
        r["user_name"] = u.get("name")
        r["employee_code"] = u.get("employee_code")
        r["company_name"] = c_by_id.get(u.get("company_id"))

    # Aggregate summary counts for the header.
    summary = {"inside": 0, "outside": 0, "no-gps": 0}
    for r in recs:
        s = r.get("location_status") or "no-gps"
        if s in summary:
            summary[s] += 1

    return {"records": recs, "count": len(recs), "summary": summary}


@api.get("/admin/attendance/location-audit.xlsx")
async def download_location_audit_xlsx(
    company_id: Optional[str] = Query(None),
    company_ids: Optional[List[str]] = Query(None),
    user_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    location_status: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Native Excel export of the Location Audit view."""
    from utils.report_xlsx import build_rows_xlsx
    from fastapi.responses import Response
    data = await list_location_audit(
        company_id=company_id,
        company_ids=company_ids,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        location_status=location_status,
        limit=1000,
        authorization=authorization,
    )
    # Project the columns for the sheet.
    rows: List[Dict[str, Any]] = []
    for r in data["records"]:
        rows.append({
            "date": r.get("date"),
            "time": (r.get("at") or "").split("T")[-1].split(".")[0] if r.get("at") else "",
            "company_name": r.get("company_name") or "",
            "employee_code": r.get("employee_code") or "",
            "employee_name": r.get("user_name") or "",
            "kind": ("IN" if r.get("kind") == "in" else "OUT"),
            "location_status": r.get("location_status"),
            "distance_m": r.get("distance_m"),
            "latitude": r.get("latitude"),
            "longitude": r.get("longitude"),
            "biometric_method": r.get("biometric_method"),
            "source": r.get("source"),
            "status": r.get("status"),
            "outside_note": r.get("outside_note") or "",
        })
    xlsx = build_rows_xlsx(
        columns=[
            "date", "time", "company_name", "employee_code", "employee_name",
            "kind", "location_status", "distance_m", "latitude", "longitude",
            "biometric_method", "source", "status", "outside_note",
        ],
        rows=rows,
        sheet_name="Location Audit",
        title="Attendance — Location Audit",
        subtitle=(
            f"Inside {data['summary']['inside']} · "
            f"Outside {data['summary']['outside']} · "
            f"No-GPS {data['summary']['no-gps']} · "
            f"Total {data['count']}"
        ),
    )
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="LocationAudit.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@api.patch("/admin/attendance/{record_id}/clear-flag")
async def clear_flag(
    record_id: str,
    authorization: Optional[str] = Header(None),
):
    """Admin clears the identity_flagged bit after manual review."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    rec = await db.attendance.find_one({"record_id": record_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Punch not found")
    if user["role"] == "company_admin" and rec.get("company_id") != user.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your company")
    await db.attendance.update_one(
        {"record_id": record_id},
        {"$set": {
            "identity_flagged": False,
            "identity_reviewed_by": user["user_id"],
            "identity_reviewed_at": now_iso(),
        }},
    )
    return {"ok": True}


@api.get("/admin/attendance/{record_id}/selfie")
async def get_punch_selfie(
    record_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return the base64 selfie captured on a specific punch. Admin-only."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    rec = await db.attendance.find_one(
        {"record_id": record_id},
        {"_id": 0, "selfie_base64": 1, "company_id": 1},
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Punch not found")
    if user["role"] == "company_admin" and rec.get("company_id") != user.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your company")
    return {"selfie_base64": rec.get("selfie_base64")}


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
# DEV mode: return the OTP in the API response so users can test without
# Twilio / email provider. In production, swap to real SMS/email send.
OTP_DEV_MODE = os.getenv("OTP_DEV_MODE", "1") == "1"


def _hash_otp(code: str) -> str:
    return _hashlib.sha256(code.encode()).hexdigest()


def _norm_identifier(identifier: str, channel: str) -> str:
    ident = identifier.strip()
    if channel == "email":
        return ident.lower()
    # phone: strip spaces / dashes / parens
    return "".join(c for c in ident if c.isdigit() or c == "+")


async def _send_otp_email(to_email: str, code: str) -> dict:
    """Send an OTP code to a user via Resend. Returns {delivered, email_id, error}."""
    subject = f"Your S.K. Sharma & Co. login code: {code}"
    text = (
        f"Your S.K. Sharma & Co. login code is: {code}\n\n"
        f"This code is valid for {OTP_TTL_MINUTES} minutes and can only be used once.\n"
        "If you didn't request this, you can safely ignore this email.\n\n"
        "— S.K. Sharma & Co."
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
        <div style="font-size:20px;font-weight:700;margin-top:2px;">Your login code</div>
      </div>
      <div style="padding:24px;">
        <p style="margin:0 0 16px 0;color:#333;font-size:14px;line-height:20px;">
          Use the code below to sign in to the S.K. Sharma & Co. app. It expires in
          <strong>{OTP_TTL_MINUTES} minutes</strong>.
        </p>
        <div style="text-align:center;padding:8px 0 16px 0;">{boxes}</div>
        <p style="margin:0;color:#888;font-size:12px;line-height:18px;">
          Didn&apos;t request this? You can safely ignore this email — no one can access your account without this code.
        </p>
      </div>
      <div style="background:#F7F7F5;padding:12px 24px;color:#999;font-size:12px;">
        This is an automated email from the S.K. Sharma & Co. app.
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
        async with httpx.AsyncClient(timeout=10.0) as hc:
            r = await hc.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": f"S.K. Sharma & Co. <{from_email}>",
                    "to": [to_email],
                    "subject": subject,
                    "text": text,
                    "html": html,
                },
            )
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
    logger.info(f"[OTP] {payload.channel} {ident} -> {code} (expires {expires_at.isoformat()})")

    resp: dict = {"ok": True, "expires_in": OTP_TTL_MINUTES * 60}

    # Actually deliver the OTP
    delivery: dict = {"delivered": False, "email_id": None, "error": None}
    if payload.channel == "email":
        delivery = await _send_otp_email(ident, code)
    else:
        # SMS delivery not wired yet — keep it in logs so ops can trace,
        # and rely on dev_code in the response.
        delivery["error"] = "sms_not_configured"

    resp["delivered"] = delivery["delivered"]
    if delivery.get("email_id"):
        resp["email_id"] = delivery["email_id"]
    if delivery.get("error"):
        resp["delivery_error"] = delivery["error"]

    # In DEV mode (or if delivery failed) we still return the code so testing
    # can proceed without being locked out. Once you verify a custom domain
    # in Resend and set OTP_DEV_MODE=0, this fallback disappears.
    if OTP_DEV_MODE or not delivery["delivered"]:
        resp["dev_code"] = code
        resp["dev_note"] = (
            "Delivered via email"
            if delivery["delivered"]
            else "Email delivery failed — showing code here so you can still sign in. Check /var/log for details."
        )
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
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
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

    token = f"emp_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
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
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    await db.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": expires,
        "created_at": datetime.now(timezone.utc),
        "auth_method": method,
    })
    return token


@api.post("/auth/admin-pin-login")
async def admin_pin_login(payload: AdminPinLoginRequest):
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
async def admin_password_login(payload: AdminPasswordLoginRequest):
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
    existing = await db.users.find_one({"phone": phone}, {"_id": 0, "role": 1, "approval_status": 1})
    if existing:
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




@api.get("/attendance/policy/saved-list")
async def attendance_policy_saved_list(
    authorization: Optional[str] = Header(None),
):
    """Iter 200 (user request) — firms that already have a saved attendance
    policy, shown at the bottom of the Policy Master screen."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    q: Dict[str, Any] = {"attendance_policy": {"$ne": None}}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    out = []
    async for c in db.companies.find(
        q, {"_id": 0, "company_id": 1, "name": 1,
            "attendance_policy.policy_variant": 1,
            "attendance_policy.full_day_hours": 1,
            "attendance_policy.updated_at": 1,
            "attendance_policy.report_settings.default_view": 1},
    ).sort("name", 1):
        ap = c.get("attendance_policy") or {}
        if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, c["company_id"]):
            continue
        out.append({
            "company_id": c["company_id"],
            "name": c.get("name"),
            "policy_variant": ap.get("policy_variant"),
            "full_day_hours": ap.get("full_day_hours"),
            "default_report": (ap.get("report_settings") or {}).get("default_view"),
            "updated_at": ap.get("updated_at"),
        })
    return {"firms": out}


@api.get("/attendance/policy/presets")
async def list_attendance_policy_presets(
    authorization: Optional[str] = Header(None),
):
    """Available policy presets per business type. Company admins use this to
    pick / reset to a preset from the Attendance Policy screen."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "company_admin", "sub_admin"])
    # Enrich with the human label taken from BUSINESS_CATEGORIES
    # Iter 200 (user directive) — Textile Policy 1/2 & the Hospital preset
    # are RETIRED from the picker: all attendance policy is now managed
    # dynamically from this screen. (Engine support for firms already saved
    # on those variants is unchanged.)
    presets: List[dict] = []
    for cat in BUSINESS_CATEGORIES:
        key = cat["key"]
        if key == "hospital":
            continue
        presets.append({
            "business_category": key,
            "label": cat["label"],
            "policy": _policy_for_category(key),
        })
    return {
        "weekday_labels": _WEEKDAY_LABELS,
        "presets": presets,
    }


@api.get("/attendance/policy")
async def get_attendance_policy(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Returns the effective attendance policy for the caller's company (or a
    specific `company_id` when called by a super admin). If the company has
    no policy on file yet, the preset for its business type is returned so
    the UI always has something to display."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    if user["role"] in ("super_admin", "sub_admin"):
        if not company_id:
            raise HTTPException(status_code=400, detail="Please pass ?company_id=")
        if user["role"] == "sub_admin" and not sub_admin_can_touch_company(user, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
        company = await db.companies.find_one({"company_id": company_id}, {"_id": 0})
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
    else:
        company = await _get_own_company(user)
    policy = company.get("attendance_policy") or _policy_for_category(
        company.get("business_category"), company.get("business_subcategory")
    )
    # `punch_approval_required` lives on the company doc (not the policy blob)
    # because it gates the punch endpoint. We surface it alongside the policy
    # so the Attendance Policy screen can render a single unified form.
    policy = dict(policy)  # avoid mutating cached preset
    policy["punch_approval_required"] = bool(company.get("punch_approval_required", True))
    # Iter 96 — normalise legacy policy shape to the modern keys the UI (and
    # other consumers) read, so nobody crashes on undefined numeric fields.
    _wd = policy.get("workday_hours")
    policy.setdefault("grace_minutes_late", policy.get("grace_minutes", 10))
    policy.setdefault("full_day_hours", _wd if _wd is not None else 8)
    policy.setdefault("half_day_hours", 4)
    policy.setdefault("break_hours", 0)
    policy.setdefault("overtime_threshold_hours", _wd if _wd is not None else 8)
    policy.setdefault("overtime_multiplier", 1)
    policy.setdefault("standard_working_hours", _wd if _wd is not None else 8)
    policy.setdefault("duty_hours_rounding_minutes", 0)
    policy.setdefault("week_off_min_working_hours", 0)
    policy.setdefault("weekly_off_days", [])
    policy.setdefault("shifts", [])
    # Iter 200 — Report Settings default: every report enabled, In/Out first.
    _rs = policy.get("report_settings") if isinstance(policy.get("report_settings"), dict) else {}
    _rs_en = _rs.get("enabled") if isinstance(_rs.get("enabled"), dict) else {}
    policy["report_settings"] = {
        "enabled": {k: bool(_rs_en.get(k, True))
                    for k in ("inout", "ot", "hours", "salary", "inout_salary")},
        "default_view": _rs.get("default_view") or "inout",
    }
    policy.setdefault("salary_allowed", "both")
    policy.setdefault("weekoff_rotation_basis", False)
    # Iter 200/201 — backfill new Policy Master sub-point flags for firms
    # whose policy was saved before these options existed.
    _pm_bf = policy.get("policy_master")
    if isinstance(_pm_bf, dict):
        for _k in ("attendance_by_duty_hours", "weekoff_present_add_ot",
                   "holiday_present_add_ot", "compliance_present_8hr",
                   "halfday_threshold_rule"):
            _pm_bf.setdefault(_k, False)
    # "Default preset" here means: no admin has explicitly saved / overridden
    # the policy yet. Because we auto-attach a preset on company creation,
    # the presence of `attendance_policy` alone isn't a good signal — we
    # instead look for the touch-timestamp that PATCH/reset sets.
    is_default = company.get("attendance_policy_updated_at") is None
    return {
        "company_id": company["company_id"],
        "business_category": company.get("business_category"),
        "business_subcategory": company.get("business_subcategory"),
        "weekday_labels": _WEEKDAY_LABELS,
        "policy": policy,
        "is_default_preset": is_default,
    }


@api.patch("/attendance/policy")
async def update_attendance_policy(
    payload: dict = Body(...),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Update the attendance policy for the caller's company (or a specified
    `company_id` when called by a super admin)."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    if user["role"] in ("super_admin", "sub_admin"):
        if not company_id:
            raise HTTPException(status_code=400, detail="Please pass ?company_id=")
        if user["role"] == "sub_admin" and not sub_admin_can_touch_company(user, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    else:
        company_id = user.get("company_id")
        if not company_id:
            raise HTTPException(status_code=400, detail="You are not linked to any company")
    # Support both { policy: {...} } and a flat body containing the fields.
    raw_policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else payload
    # Extract the company-level `punch_approval_required` toggle before
    # validating the policy blob (validator would otherwise reject it as an
    # unknown key on the shift/hours schema).
    approval_flag = raw_policy.pop("punch_approval_required", None) if isinstance(raw_policy, dict) else None
    # Iter 104 — support PARTIAL updates (e.g. Firm Master's Policy 1/2
    # picker sends only {policy_variant}). Merge the incoming fields onto
    # the firm's existing policy (or its category preset) before validating.
    if isinstance(raw_policy, dict):
        co = await db.companies.find_one(
            {"company_id": company_id},
            {"_id": 0, "attendance_policy": 1, "business_category": 1, "business_subcategory": 1})
        if not co:
            raise HTTPException(status_code=404, detail="Company not found")
        base = co.get("attendance_policy") or {}
        preset = _policy_for_category(
            co.get("business_category"), co.get("business_subcategory")) or {}
        # Legacy firms may hold an old-schema policy without `shifts` —
        # backfill missing required fields from the category preset.
        merged = {**preset, **{k: v for k, v in base.items() if v not in (None, "", [])}, **raw_policy}
        raw_policy = merged
    clean = _validate_policy(raw_policy)
    updates: dict = {
        "attendance_policy": clean,
        "attendance_policy_updated_at": now_iso(),
        "attendance_policy_updated_by": user["user_id"],
    }
    if approval_flag is not None:
        updates["punch_approval_required"] = bool(approval_flag)
    r = await db.companies.update_one(
        {"company_id": company_id},
        {"$set": updates},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    # Return the full policy blob (including the toggle) so the client can
    # rehydrate its form without an extra GET.
    resp_policy = dict(clean)
    if approval_flag is not None:
        resp_policy["punch_approval_required"] = bool(approval_flag)
    else:
        # Include current value from DB for consistency
        cur = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "punch_approval_required": 1})
        resp_policy["punch_approval_required"] = bool((cur or {}).get("punch_approval_required", True))
    return {"ok": True, "policy": resp_policy}


@api.post("/attendance/policy/reset")
async def reset_attendance_policy(
    payload: dict = Body(default={}),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Reset the company's attendance policy to a preset. If `business_category`
    is passed in the body, that preset is used; otherwise falls back to the
    company's own business_category preset."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    if user["role"] in ("super_admin", "sub_admin"):
        if not company_id:
            raise HTTPException(status_code=400, detail="Please pass ?company_id=")
        if user["role"] == "sub_admin" and not sub_admin_can_touch_company(user, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    else:
        company_id = user.get("company_id")
        if not company_id:
            raise HTTPException(status_code=400, detail="You are not linked to any company")
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    override_cat = (payload or {}).get("business_category")
    if override_cat and override_cat not in _BUSINESS_CATEGORY_MAP:
        raise HTTPException(status_code=400, detail="Unknown business category")
    preset_key = override_cat or company.get("business_category")
    preset = _policy_for_category(preset_key)
    await db.companies.update_one(
        {"company_id": company_id},
        {"$set": {
            "attendance_policy": preset,
            "attendance_policy_updated_at": now_iso(),
            "attendance_policy_updated_by": user["user_id"],
        }},
    )
    return {"ok": True, "policy": preset, "reset_to": preset_key or "other"}


@api.get("/attendance/textile/compute-day")
async def attendance_textile_compute_day(
    date: str = Query(..., description="YYYY-MM-DD"),
    user_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Compute a single day's textile duty summary for one employee.

    Returns duty hours, present days (0 / 0.5 / 1), OT minutes and whether
    week-off / holiday transformations kicked in. Admin-only.

    Args:
        date: The calendar date in YYYY-MM-DD (UTC).
        user_id: Employee to compute for. Company admins are scoped to
            their own company; super admins may pass any user_id.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    emp = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Employee not in your company")
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    company = None
    if emp.get("company_id"):
        company = await db.companies.find_one(
            {"company_id": emp["company_id"]}, {"_id": 0}
        )
    policy = (company or {}).get("attendance_policy") or _policy_for_category(
        (company or {}).get("business_category")
    )
    punches = await db.attendance.find(
        {"user_id": user_id, "date": date},
        {"_id": 0, "kind": 1, "at": 1},
    ).sort("at", 1).to_list(500)
    # Iter 77c — Honour per-employee shift override (manual or auto-by-first-punch)
    shifts_by_id, shifts_list = await load_shift_masters_map()
    # Iter 204 — approved daily shift assignment wins.
    _dso = await load_daily_shift_overrides(emp.get("company_id") or "", date, date)
    resolved_shift = _dso.get((user_id, date)) or resolve_shift_for_user(
        emp, punches, shifts_by_id, shifts_list,
        firm_shift_open=_is_shift_open(policy))
    policy = apply_resolved_shift_to_policy(policy, resolved_shift)
    policy = apply_employee_policy_override(policy, emp)
    summary = compute_textile_day(punches, policy, emp, d.weekday())
    return {
        "user_id": user_id,
        "date": date,
        "policy_variant": policy.get("policy_variant"),
        "resolved_shift": {
            "shift_id": (resolved_shift or {}).get("shift_id"),
            "name": (resolved_shift or {}).get("name"),
            "start": (resolved_shift or {}).get("start"),
            "end": (resolved_shift or {}).get("end"),
        } if resolved_shift else None,
        "punch_count": len(punches),
        **summary,
    }


# ---------------------------------------------------------------------------
# Company registration requests (from prospective client firms)
# ---------------------------------------------------------------------------
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
    # Iter 114 — process-flow gate: employee app punching is allowed only
    # when the firm's Bio Matrix Attendance is ON. Firms that have never
    # configured their Salary Process (both toggles off / no firm master)
    # keep legacy behaviour (punching allowed).
    fm = await db.firm_masters.find_one(
        {"company_id": user["company_id"]}, {"_id": 0, "salary_process": 1},
    )
    sp = (fm or {}).get("salary_process") or {}
    configured = bool(sp.get("online_salary")) or bool(sp.get("offline_salary"))
    company["attendance_punching_enabled"] = (
        True if not configured else bool(sp.get("bio_matrix_attendance"))
    )
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
    await db.branches.delete_one({"branch_id": branch_id})
    return {"ok": True}


@api.get("/companies")
async def list_companies(authorization: Optional[str] = Header(None)):
    """List all companies with quick stats.

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
    companies = await db.companies.find(query, {"_id": 0}).to_list(500)
    # Firm Master list is ALWAYS alphabetical by firm name (user directive).
    companies.sort(key=lambda c: (c.get("name") or "").strip().upper())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = []
    for c in companies:
        cid = c["company_id"]
        employees = await db.users.count_documents({"company_id": cid, "role": "employee"})
        present = len(await db.attendance.distinct(
            "user_id", {"company_id": cid, "date": today, "kind": "in"}
        ))
        pending_leaves = await db.leaves.count_documents(
            {"company_id": cid, "status": "pending"}
        )
        c["stats"] = {
            "employees": employees,
            "present_today": present,
            "pending_leaves": pending_leaves,
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
            clash = await db.users.find_one({"phone": phone, "user_id": {"$ne": target["user_id"]}}, {"_id": 0, "user_id": 1})
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


async def _dup_employee_with_orphan_heal(
    phone: Optional[str], email: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Return an existing EMPLOYEE user that blocks this phone/email — after
    auto-healing orphans. An orphan is an employee whose ``company_id`` points
    to a firm that no longer exists (force-deleted): such stale records are
    removed (with their sessions) so the phone/email can be reused when the
    same people are re-imported. Employees of a LIVE firm still block.

    User report (Iter 134): after Force Delete of a firm from Company Master,
    re-importing the same employees said "phone / email already registered"
    because stale user docs survived on the production DB."""
    or_q: List[Dict[str, Any]] = []
    if phone:
        or_q.append({"phone": phone})
    if email:
        or_q.append({"email": email})
    if not or_q:
        return None
    stale_ids: List[str] = []
    blocker: Optional[Dict[str, Any]] = None
    async for u in db.users.find(
        {"$or": or_q, "role": "employee"},
        {"_id": 0, "user_id": 1, "name": 1, "company_id": 1, "employee_code": 1},
    ):
        live = None
        if u.get("company_id"):
            live = await db.companies.find_one(
                {"company_id": u["company_id"]}, {"_id": 0, "company_id": 1})
        if live:
            blocker = blocker or u
        else:
            stale_ids.append(u["user_id"])
    if stale_ids:
        await db.users.delete_many({"user_id": {"$in": stale_ids}})
        await db.user_sessions.delete_many({"user_id": {"$in": stale_ids}})
        logger.info(
            "[dup-heal] removed %d orphan employee record(s) for phone=%s email=%s "
            "(firms already deleted)", len(stale_ids), phone, email)
    return blocker


# ---------------------------------------------------------------------------
# Delete employees (super_admin or company_admin scoped)
# ---------------------------------------------------------------------------
@api.post("/admin/employees")
async def admin_create_employee(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Admin-facing employee creation.

    Called from the web portal "Add Employee" form.  Creates an
    already-approved employee under the caller's firm (or an explicit
    ``company_id`` for super/sub-admins).  A temp 6-digit PIN is
    generated and returned so the admin can share it with the new
    hire; ``pin_must_change=True`` forces the employee to reset it on
    first login.

    Required fields: ``name`` and either ``phone`` or ``email``.
    Optional fields cover the entire master sheet — designation,
    department, employee_code, DOJ, salary, statutory IDs, etc.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Employee name is required")

    phone = _normalise_phone(str(payload.get("phone") or ""))
    email = (str(payload.get("email") or "").strip().lower()) or None
    # Iter 246 (user rollback) — Mobile is mandatory again for new
    # employees so they can log in.
    if not phone and not email:
        raise HTTPException(
            status_code=400,
            detail="Provide at least a phone number or email so the employee can log in.",
        )

    # Resolve company_id
    if admin["role"] == "company_admin":
        cid = admin.get("company_id")
    else:
        cid = payload.get("company_id") or admin.get("company_id")
    if not cid:
        raise HTTPException(
            status_code=400,
            detail="Company is required — pick a firm before adding an employee.",
        )
    company = await db.companies.find_one({"company_id": cid}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Duplicate checks — ONLY employee records block (user directive: an
    # Employer/Firm-Master mobile can also be registered as an Employee).
    # Orphans (employees of a force-deleted firm) are auto-healed so the
    # same phone/email can be re-registered.
    if phone:
        if await _dup_employee_with_orphan_heal(phone, None):
            raise HTTPException(
                status_code=409,
                detail="This phone number is already registered.",
            )
    if email:
        if await _dup_employee_with_orphan_heal(None, email):
            raise HTTPException(
                status_code=409,
                detail="This email is already registered.",
            )

    # Auto-generated temp PIN — admin can share with the new hire.
    import secrets as _secrets
    temp_pin = f"{_secrets.randbelow(1_000_000):06d}"

    # Iter 164 — On/Off-roll gated by Firm Master 'Offline Salary': when
    # the firm has Offline Salary DISABLED, the employee joins On-roll
    # directly regardless of what the form sent.
    _onroll_in = payload.get("is_onroll")
    _onroll_val = True if _onroll_in is None else bool(_onroll_in)
    if _onroll_val is False and not await _firm_offline_salary_enabled(cid):
        _onroll_val = True

    # Copy over allowed employee master fields.
    doc: Dict[str, Any] = {
        "user_id": f"user_{uuid.uuid4().hex[:12]}",
        "email": email,
        "phone": phone,
        "name": name,
        "picture": None,
        "role": "employee",
        "company_id": cid,
        "employee_code": (str(payload.get("employee_code") or "").strip() or None),
        # Iter 94 — Bio Code (device enrolment no.) settable at creation
        # so Add form matches the master-sheet columns.
        "bio_code": (str(payload.get("bio_code") or "").strip() or None),
        # Iter 142 — per-employee OT flag (None = default allowed).
        "ot_applicable": (bool(payload.get("ot_applicable"))
                          if payload.get("ot_applicable") is not None else None),
        "father_name": payload.get("father_name") or None,
        "mother_name": payload.get("mother_name") or None,
        "gender": payload.get("gender") or None,
        "dob": payload.get("dob") or None,
        "doj": payload.get("doj") or None,
        "designation": payload.get("designation") or None,
        "department": payload.get("department") or None,
        "employee_type": payload.get("employee_type") or None,
        "employee_group": payload.get("employee_group") or None,
        "is_onroll": _onroll_val,
        "shift_start": payload.get("shift_start") or None,
        "shift_end": payload.get("shift_end") or None,
        "salary_mode": payload.get("salary_mode") or None,
        # Iter 94 — separate rate basis for the Compliance salary part.
        "compliance_salary_mode": payload.get("compliance_salary_mode") or None,
        "salary_monthly": payload.get("salary_monthly"),
        "compliance_gross": payload.get("compliance_gross"),
        # Iter 126g — Compliance Basic + PF Basic (EPF ceiling rule).
        "compliance_basic": payload.get("compliance_basic"),
        "pf_basic": payload.get("pf_basic"),
        # Iter 126i — VPF (Voluntary PF)
        "vpf_enabled": bool(payload.get("vpf_enabled") or False),
        "vpf_amount": payload.get("vpf_amount"),
        "actual_salary_allowances": payload.get("actual_salary_allowances") or [],
        "actual_salary_deductions": payload.get("actual_salary_deductions") or [],
        # Iter 91 — fixed Actual structure saved from the Add form
        # (same shape as the Employee Master Salary Update modal).
        "salary_structure_actual": payload.get("salary_structure_actual") or [],
        "compliance_salary_allowances": payload.get("compliance_salary_allowances") or [],
        "compliance_salary_deductions": payload.get("compliance_salary_deductions") or [],
        # Iter 137 — interlinked compliance structure (single source of truth)
        "salary_structure_compliance": build_compliance_structure(
            payload.get("compliance_basic"),
            payload.get("compliance_salary_allowances") or [],
            payload.get("compliance_salary_mode"),
        ),
        "half_day_hrs": payload.get("half_day_hrs"),
        "full_day_hrs": payload.get("full_day_hrs"),
        # Statutory identifiers
        "uan_no": payload.get("uan_no") or None,
        "pf_no": payload.get("pf_no") or None,
        "esi_ip_no": payload.get("esi_ip_no") or None,
        "pan_no": payload.get("pan_no") or None,
        "pan_name": payload.get("pan_name") or None,
        "aadhaar_no": payload.get("aadhaar_no") or None,
        "bank_name": payload.get("bank_name") or None,
        "bank_account": payload.get("bank_account") or None,
        "bank_ifsc": payload.get("bank_ifsc") or None,
        "upi_id": payload.get("upi_id") or None,
        "blood_group": payload.get("blood_group") or None,
        "marital_status": payload.get("marital_status") or None,
        "spouse_name": payload.get("spouse_name") or None,
        "pay_mode": payload.get("pay_mode") or "Bank",
        "address": (str(payload.get("address") or "").strip() or None),
        # Iter 159 — structured location (PIN auto-lookup on the form).
        "pincode": (str(payload.get("pincode") or "").strip() or None),
        "district": (str(payload.get("district") or "").strip() or None),
        "state": (str(payload.get("state") or "").strip() or None),
        # Iter 109 — extra master fields: addresses, emergency & family
        "permanent_address": (str(payload.get("permanent_address") or "").strip() or None),
        "emergency_contact_name": (str(payload.get("emergency_contact_name") or "").strip() or None),
        "emergency_contact_phone": (str(payload.get("emergency_contact_phone") or "").strip() or None),
        "family_members": [
            {"name": str(f.get("name") or "").strip(),
             "relation": str(f.get("relation") or "").strip(),
             "dob": str(f.get("dob") or "").strip()}
            for f in (payload.get("family_members") or [])
            if isinstance(f, dict) and str(f.get("name") or "").strip()
        ],
        # Admin creation → already approved, already onboarded.
        "onboarded": True,
        "onboarded_at": now_iso(),
        "approval_status": "approved",
        "approval_requested_at": now_iso(),
        "approved_at": now_iso(),
        "approved_by": admin.get("user_id"),
        "has_pin": True,
        "pin_hash": _hash_pin(temp_pin),
        "pin_must_change": True,
        "pin_set_at": now_iso(),
        "created_at": now_iso(),
        "created_by_admin": admin.get("user_id"),
    }
    # Auto-assign employee_code if the admin left it blank.
    if not doc["employee_code"]:
        try:
            code = await _next_employee_code(cid)
            if code:
                doc["employee_code"] = code
        except Exception:
            pass

    # Iter 95e — Shift comes from the Shift Master ONLY (no free-typed
    # in/out times on the Add form). ``shift_id`` lands on the employee's
    # attendance_policy_override so the grids resolve it; the master's
    # start/end are mirrored onto shift_start/shift_end for display.
    _shift_id = str(payload.get("shift_id") or "").strip()
    if _shift_id:
        _shift = await db.shift_masters.find_one(
            {"shift_id": _shift_id}, {"_id": 0, "shift_id": 1, "start": 1, "end": 1},
        )
        if not _shift:
            raise HTTPException(status_code=400, detail="Unknown shift — pick one from the Shift Master")
        doc["attendance_policy_override"] = {"shift_id": _shift_id}
        doc["shift_start"] = _shift.get("start")
        doc["shift_end"] = _shift.get("end")

    # Iter 75 — Auto-inherit group policy if the employee was tagged with
    # a known group. Preserves any explicit policy fields already on the
    # doc (per-employee overrides win).
    if doc.get("employee_group"):
        merged = await _apply_group_policy_on_create(
            cid,
            doc["employee_group"],
            existing_policy=doc.get("employee_policy"),
        )
        if merged:
            doc["employee_policy"] = merged
            # Mirror to legacy fields the payroll loop still reads.
            if merged.get("fullday_hours") is not None and doc.get("full_day_hrs") is None:
                doc["full_day_hrs"] = float(merged["fullday_hours"])
            if merged.get("halfday_hours") is not None and doc.get("half_day_hrs") is None:
                doc["half_day_hrs"] = float(merged["halfday_hours"])

    await db.users.insert_one(doc)
    logger.info(
        f"[ADMIN CREATE EMPLOYEE] {name} ({phone or email}) → company={cid} by {admin.get('email')}"
    )
    # Iter 103 — automated email trigger
    try:
        from routes.email_notifications import fire_email_event
        await fire_email_event("employee_joined", company_id=cid,
                               employee_user_id=doc["user_id"],
                               details=f"Employee code {doc.get('employee_code') or ''}")
    except Exception:
        pass
    return {
        "ok": True,
        "user_id": doc["user_id"],
        "employee_code": doc.get("employee_code"),
        "temp_pin": temp_pin,
        "message": (
            f"Employee added. Share the temp PIN {temp_pin} with them — "
            "they will be forced to change it on first login."
        ),
    }


@api.post("/admin/employees/bulk-import")
async def admin_employees_bulk_import(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """CSV bulk-import — creates many employees in one call.

    Payload:
      * ``company_id`` (required for super/sub-admin; auto-forced for
        company-admin).
      * ``rows``       — list of dicts, each row matches the same schema
        as ``POST /admin/employees`` (``name`` + ``phone`` OR ``email``
        required).

    Behaviour:
      * Idempotent per-phone/email: rows that duplicate an existing user
        are reported as ``skipped_duplicates`` (not created).
      * Each new user gets an auto-assigned employee code and a random
        6-digit temp PIN with ``pin_must_change=True`` (same rule as
        the single Add-Employee endpoint).
      * Rows missing required fields are reported in ``errors`` with a
        row number and reason — the rest of the import still succeeds.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    if admin["role"] == "company_admin":
        cid = admin.get("company_id")
    else:
        cid = payload.get("company_id")
    if not cid:
        raise HTTPException(status_code=400, detail="company_id is required")
    company = await db.companies.find_one({"company_id": cid}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    rows = payload.get("rows") or []
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail="`rows` must be a non-empty list")

    # User directive — when a CSV row has no Allowance/Deduction columns,
    # set them up from the heads ENABLED in the Firm Master company policy
    # (Sections 5 & 6). Amounts start at 0 and are edited later per employee.
    _fm_policy = await db.firm_masters.find_one(
        {"company_id": cid}, {"_id": 0, "allowances": 1, "deductions": 1}) or {}
    policy_allow_lines = [{"head": h, "amount": 0.0}
                          for h, on in (_fm_policy.get("allowances") or {}).items() if on]
    policy_ded_lines = [{"head": h, "amount": 0.0}
                        for h, on in (_fm_policy.get("deductions") or {}).items() if on]

    import secrets as _secrets

    # Iter 125 — friendly header aliases so the CSV can use the firm's own
    # column names (EMPLOYEE PFNO, Name As Per Pan Card, Mobile1 …).
    _ALIASES: Dict[str, str] = {
        "employee pfno": "pf_no", "pf no": "pf_no", "pfno": "pf_no",
        "uan no": "uan_no", "uan": "uan_no",
        "employee esino": "esi_ip_no", "esi no": "esi_ip_no", "esino": "esi_ip_no",
        "employee name": "name",
        "employee father name": "father_name", "father name": "father_name",
        "emp type": "employee_type", "emp_type": "employee_type",
        "emp group": "employee_type", "emp_group": "employee_type",
        "employee group": "employee_type", "group": "employee_type",
        "marital status": "marital_status",
        "employee basic": "basic_salary", "basic": "basic_salary",
        "pf basic": "pf_basic",
        "conv": "conveyance",
        "over time": "over_time", "overtime": "over_time",
        "gross pay": "compliance_gross",
        "present add": "present_address", "present address": "present_address",
        "permanent add": "permanent_address", "permanent address": "permanent_address",
        "panno": "pan_no", "pan no": "pan_no", "pan": "pan_no",
        "name as per pan card": "name_as_per_pan", "name as per pan": "name_as_per_pan",
        "aadhar card no": "aadhaar_no", "aadhaar no": "aadhaar_no", "aadhar no": "aadhaar_no",
        "name on aadhar card": "name_as_per_aadhar", "name as per aadhar": "name_as_per_aadhar",
        "bank name": "bank_name",
        "bank address": "bank_address",
        "account no": "bank_account", "account number": "bank_account",
        "name on bank ac": "account_holder", "name on bank a/c": "account_holder",
        "name on bank account": "account_holder",
        "ifsc code": "bank_ifsc", "ifsc": "bank_ifsc",
        "mobile1": "phone", "mobile 1": "phone", "mobile": "phone",
        "mobile2": "phone2", "mobile 2": "phone2",
        "pay mode": "pay_mode",
        "pay basis": "pay_basis",
        "resign date": "resign_date",
        "basic salary actual": "salary_monthly",
    }

    def _norm_key(k: str) -> str:
        return re.sub(r"\s+", " ", str(k or "").strip().lower())

    def _normalise_row(raw_row: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in raw_row.items():
            nk = _norm_key(k)
            out[_ALIASES.get(nk, nk.replace(" ", "_"))] = v
        return out

    def _num(v: Any) -> Optional[float]:
        try:
            s = str(v).replace(",", "").strip()
            return float(s) if s else None
        except Exception:
            return None

    def _parse_salary_lines(raw: Any) -> List[Dict[str, Any]]:
        """Iter 74 — Parse ``HRA:2000|Convey:500|SpecialAllow:1000`` into
        the same ``[{head, amount}]`` list shape used by the single-add
        endpoint. Silently drops malformed / empty entries; a caller can
        pass ``None`` / empty string safely."""
        if raw is None:
            return []
        # Accept either a pre-parsed list (JSON) or a pipe-separated
        # string produced by the CSV.
        if isinstance(raw, list):
            out: List[Dict[str, Any]] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                head = str(item.get("head") or "").strip()
                try:
                    amount = float(item.get("amount") or 0)
                except Exception:
                    continue
                if head and amount:
                    out.append({"head": head, "amount": amount})
            return out
        text = str(raw or "").strip()
        if not text:
            return []
        # Support pipe OR semicolon as separator to be user-friendly.
        parts = [p.strip() for p in text.replace(";", "|").split("|") if p.strip()]
        out2: List[Dict[str, Any]] = []
        for part in parts:
            if ":" not in part:
                continue
            head, amt = part.split(":", 1)
            head = head.strip()
            try:
                amount = float(str(amt).replace(",", "").strip())
            except Exception:
                continue
            if head and amount:
                out2.append({"head": head, "amount": amount})
        return out2

    created: List[Dict[str, Any]] = []
    skipped_duplicates: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for idx, r in enumerate(rows, start=1):
        try:
            r = _normalise_row(r)
            name = str(r.get("name") or "").strip()
            if not name:
                errors.append({"row": idx, "reason": "name is required"})
                continue
            phone = _normalise_phone(str(r.get("phone") or ""))
            email = (str(r.get("email") or "").strip().lower()) or None
            if not phone and not email:
                errors.append({"row": idx, "reason": "phone or email required"})
                continue
            # Duplicate check — only EMPLOYEE records block; an employer/
            # admin using the same mobile is allowed (user directive).
            # Orphans (employees of a force-deleted firm) are auto-healed
            # so re-importing the same people succeeds.
            dup = await _dup_employee_with_orphan_heal(phone, email)
            if dup:
                # Tell the admin WHICH firm already holds this phone/email so
                # duplicate skips are self-explanatory in the import log.
                _dup_firm = await db.companies.find_one(
                    {"company_id": dup.get("company_id")}, {"_id": 0, "name": 1})
                _firm_label = (_dup_firm or {}).get("name") or dup.get("company_id") or "?"
                skipped_duplicates.append({
                    "row": idx,
                    "name": name,
                    "reason": (
                        f"phone / email already registered — {dup.get('name') or 'employee'}"
                        + (f" (code {dup.get('employee_code')})" if dup.get("employee_code") else "")
                        + f" in firm '{_firm_label}'"
                    ),
                    "existing_user_id": dup["user_id"],
                })
                continue
            temp_pin = f"{_secrets.randbelow(1_000_000):06d}"
            doc: Dict[str, Any] = {
                "user_id": f"user_{uuid.uuid4().hex[:12]}",
                "email": email,
                "phone": phone,
                "name": name,
                "picture": None,
                "role": "employee",
                "company_id": cid,
                "employee_code": (str(r.get("employee_code") or "").strip() or None),
                "father_name": r.get("father_name") or None,
                "gender": r.get("gender") or None,
                "dob": r.get("dob") or None,
                "doj": r.get("doj") or None,
                "designation": r.get("designation") or None,
                "department": r.get("department") or None,
                "employee_type": r.get("employee_type") or None,
                # Employee Group merged into Employee Type (user directive) —
                # the CSV no longer has an employee_group column; mirror type.
                "employee_group": r.get("employee_type") or None,
                "is_onroll": r.get("is_onroll") if r.get("is_onroll") is not None else True,
                "salary_mode": (
                    str(r.get("pay_basis") or "").strip().lower()
                    if str(r.get("pay_basis") or "").strip().lower() in ("daily", "monthly")
                    else (r.get("salary_mode") or "monthly")),
                "salary_monthly": _num(r.get("salary_monthly")),
                "compliance_gross": _num(r.get("compliance_gross")),
                # Iter 125 — extended master fields from the firm's own
                # bulk-import format.
                "marital_status": r.get("marital_status") or None,
                "basic_salary": _num(r.get("basic_salary")),
                # Iter 137 (user directive) — the import columns ARE the
                # Compliance salary: EMPLOYEE BASIC → Compliance Basic,
                # HRA/CONV → Compliance allowance heads, Gross Pay →
                # Compliance Gross (Basic + Allowances).
                "compliance_basic": _num(r.get("basic_salary")),
                "pf_basic": _num(r.get("pf_basic")),
                "hra": _num(r.get("hra")),
                "conveyance": _num(r.get("conveyance")),
                "over_time": _num(r.get("over_time")),
                "present_address": r.get("present_address") or None,
                "permanent_address": r.get("permanent_address") or None,
                "name_as_per_pan": r.get("name_as_per_pan") or None,
                "name_as_per_aadhar": r.get("name_as_per_aadhar") or None,
                "bank_address": r.get("bank_address") or None,
                "account_holder": r.get("account_holder") or None,
                "phone2": (_normalise_phone(str(r.get("phone2") or "")) or None),
                "pay_mode": r.get("pay_mode") or None,
                "pay_basis": r.get("pay_basis") or None,
                "resign_date": r.get("resign_date") or None,
                "uan_no": r.get("uan_no") or None,
                "pf_no": r.get("pf_no") or None,
                "esi_ip_no": r.get("esi_ip_no") or None,
                "pan_no": r.get("pan_no") or None,
                "aadhaar_no": r.get("aadhaar_no") or None,
                "bank_name": r.get("bank_name") or None,
                "bank_account": r.get("bank_account") or None,
                "bank_ifsc": r.get("bank_ifsc") or None,
                "address": r.get("address") or r.get("present_address") or None,
                # Iter 74 — allowance / deduction line-items via
                # `HRA:2000|Convey:500` style CSV columns. When the CSV has
                # none, DEFAULT to the heads enabled in the Firm Master
                # company policy (user directive).
                "actual_salary_allowances": (
                    _parse_salary_lines(r.get("actual_allowances") or r.get("allowances"))
                    or [dict(x) for x in policy_allow_lines]),
                "actual_salary_deductions": (
                    _parse_salary_lines(r.get("actual_deductions") or r.get("deductions"))
                    or [dict(x) for x in policy_ded_lines]),
                "compliance_salary_allowances": (
                    _parse_salary_lines(r.get("compliance_allowances"))
                    # Iter 137 (user directive) — HRA / CONV import columns
                    # are Compliance-salary allowance heads.
                    or [ln for ln in [
                        {"head": "HRA", "amount": _num(r.get("hra")) or 0},
                        {"head": "CONV.", "amount": _num(r.get("conveyance")) or 0},
                    ] if ln["amount"] > 0]),
                "compliance_salary_deductions": _parse_salary_lines(r.get("compliance_deductions")),
                "onboarded": True,
                "onboarded_at": now_iso(),
                "approval_status": "approved",
                "approval_requested_at": now_iso(),
                "approved_at": now_iso(),
                "approved_by": admin.get("user_id"),
                "has_pin": True,
                "pin_hash": _hash_pin(temp_pin),
                "pin_must_change": True,
                "pin_set_at": now_iso(),
                "created_at": now_iso(),
                "created_by_admin": admin.get("user_id"),
                "bulk_imported": True,
            }
            if not doc["employee_code"]:
                try:
                    code = await _next_employee_code(cid)
                    if code:
                        doc["employee_code"] = code
                except Exception:
                    pass
            # Iter 137 — interlinked compliance structure + linked Gross
            # (= Compliance Basic + Σ allowance lines).
            doc["salary_structure_compliance"] = build_compliance_structure(
                doc.get("compliance_basic"),
                doc.get("compliance_salary_allowances"),
                doc.get("salary_mode"),
            )
            _cg = compliance_gross_total(
                doc.get("compliance_basic"), doc.get("compliance_salary_allowances"))
            if _cg > 0:
                doc["compliance_gross"] = _cg
            # Iter 75 — Inherit group policy when the CSV row provides
            # an `employee_group` matching an existing template.
            if doc.get("employee_group"):
                merged = await _apply_group_policy_on_create(
                    cid, doc["employee_group"], existing_policy=doc.get("employee_policy"),
                )
                if merged:
                    doc["employee_policy"] = merged
                    if merged.get("fullday_hours") is not None:
                        doc["full_day_hrs"] = float(merged["fullday_hours"])
                    if merged.get("halfday_hours") is not None:
                        doc["half_day_hrs"] = float(merged["halfday_hours"])
            await db.users.insert_one(doc)
            created.append({
                "row": idx,
                "name": name,
                "user_id": doc["user_id"],
                "employee_code": doc.get("employee_code"),
                "temp_pin": temp_pin,
            })
        except Exception as ex:
            errors.append({"row": idx, "reason": str(ex)})

    logger.info(
        f"[ADMIN BULK IMPORT] cid={cid} created={len(created)} skipped={len(skipped_duplicates)} errors={len(errors)}"
    )
    return {
        "ok": True,
        "created_count": len(created),
        "skipped_count": len(skipped_duplicates),
        "error_count": len(errors),
        "created": created,
        "skipped_duplicates": skipped_duplicates,
        "errors": errors,
    }


@api.get("/admin/employees/bulk-import-template.xlsx")
async def admin_bulk_import_template(
    authorization: Optional[str] = Header(None),
):
    """Excel (.xlsx) bulk-import template. Iter 132 (user directive):
    switched from CSV to Excel because CSV editors mangle numeric fields
    (leading zeros in UAN/ESI/account numbers, dates). Every cell is
    TEXT-formatted so Excel never converts values."""
    from fastapi.responses import Response
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    # Iter 125 — template matches the firm's own bulk-import format.
    # Iter 132 — "Emp Type" renamed to "Emp Group" (General Master Groups).
    columns = [
        "EMPLOYEE PFNO", "UAN_NO", "EMPLOYEE ESINO",
        "EMPLOYEE NAME", "EMPLOYEE FATHER NAME",
        "Designation", "Department", "Emp Group", "Gender", "Marital Status",
        "DOB", "DOJ",
        "EMPLOYEE BASIC", "PF_BASIC", "HRA", "CONV", "OVER_TIME", "Gross Pay",
        "Present Add", "Permanent Add",
        "PANNo", "Name As Per Pan Card",
        "Aadhar Card No", "Name On Aadhar Card",
        "Bank Name", "Bank Address", "Account No", "Name On Bank Ac", "IFSC Code",
        "Mobile1", "Mobile2",
        "Pay Mode", "Pay Basis", "Resign Date",
        "Basic Salary Actual",
    ]
    sample = [
        "DL/PF/12345", "123456789012", "1122334455",
        "Ramesh Kumar", "Suresh Kumar",
        "Machine Operator", "Weaving", "Worker", "Male", "Married",
        "1990-05-14", "2024-04-01",
        "12000", "12000", "3000", "1500", "0", "18000",
        "House 12 Karol Bagh New Delhi", "Village Rampur UP",
        "ABCDE1234F", "RAMESH KUMAR",
        "123412341234", "RAMESH KUMAR",
        "HDFC Bank", "Karol Bagh Branch New Delhi", "1234567890", "RAMESH KUMAR", "HDFC0001234",
        "+919812345678", "+919812300000",
        "Bank", "Monthly", "",
        "22000",
    ]
    wb = Workbook()
    ws = wb.active
    ws.title = "Employees"
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="1D4ED8")
    for i, col in enumerate(columns, start=1):
        c = ws.cell(row=1, column=i, value=col)
        c.font = hdr_font
        c.fill = hdr_fill
        ws.column_dimensions[get_column_letter(i)].width = max(12, min(28, len(col) + 4))
    for i, val in enumerate(sample, start=1):
        c = ws.cell(row=2, column=i, value=val)
        c.number_format = "@"  # TEXT — preserves leading zeros / long numbers
    # Pre-format 500 blank rows as TEXT so pasted data is never mangled.
    for r in range(3, 503):
        for i in range(1, len(columns) + 1):
            ws.cell(row=r, column=i).number_format = "@"
    buf = io.BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="employee_bulk_import_template.xlsx"',
        },
    )


class BulkImportParseBody(BaseModel):
    file_base64: str
    filename: Optional[str] = None


@api.post("/admin/employees/bulk-import-parse")
async def admin_bulk_import_parse(
    payload: BulkImportParseBody,
    authorization: Optional[str] = Header(None),
):
    """Parse an uploaded Excel (.xlsx/.xls) bulk-import file server-side and
    return {headers, rows} of STRINGS — numeric cells are stringified
    losslessly (no scientific notation / trailing .0), dates become
    YYYY-MM-DD. Iter 132 (user directive: Excel instead of CSV)."""
    import base64 as _b64
    from openpyxl import load_workbook
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    try:
        blob = _b64.b64decode(payload.file_base64 or "", validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file encoding")
    if not blob:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        wb = load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Could not read the Excel file — please upload a .xlsx made from the template.",
        )
    ws = wb.worksheets[0]

    def cell_str(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d")
        if isinstance(v, float):
            if v.is_integer():
                return str(int(v))
            return repr(v)
        return str(v).strip()

    headers: List[str] = []
    rows: List[Dict[str, str]] = []
    for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
        if r_idx == 0:
            headers = [cell_str(v) for v in row]
            while headers and not headers[-1]:
                headers.pop()
            continue
        vals = [cell_str(v) for v in row[: len(headers)]]
        if not any(vals):
            continue  # skip fully blank rows
        rows.append({headers[i]: (vals[i] if i < len(vals) else "") for i in range(len(headers)) if headers[i]})
    wb.close()
    if not headers:
        raise HTTPException(status_code=400, detail="No header row found in the Excel file")
    return {"headers": [h for h in headers if h], "rows": rows, "rows_count": len(rows)}


@api.delete("/admin/employees/{user_id}")
async def delete_employee(user_id: str,
                          authorization: Optional[str] = Header(None)):
    """Remove an employee (and their attendance, leaves, tickets, payslips).

    - Super admin can delete any employee.
    - Company admin can only delete employees in their own company.
    - Super admins cannot be deleted via this endpoint (safety guard).
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    if target.get("role") == "super_admin":
        raise HTTPException(status_code=403, detail="Super admin accounts cannot be deleted")
    if admin["role"] == "company_admin":
        if not admin.get("company_id") or target.get("company_id") != admin["company_id"]:
            raise HTTPException(status_code=403, detail="Not allowed to delete employees outside your company")
    if admin.get("user_id") == user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    cascade = {}
    for col in ("attendance", "leaves", "tickets", "payslips", "notifications", "user_sessions"):
        r = await db[col].delete_many({"user_id": user_id})
        cascade[col] = r.deleted_count
    await db.users.delete_one({"user_id": user_id})
    logger.info(f"[DELETE employee] {user_id} by {admin.get('email')} cascade={cascade}")
    return {"ok": True, "cascade": cascade}


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


@api.get("/attendance/worksites")
async def my_worksites(authorization: Optional[str] = Header(None)):
    """Iter 176 — worksites for the guided punch flow: the firm's main
    office plus all active branches (id, name, coords, radius). Available
    to any logged-in employee of the firm."""
    user = await get_user_from_token(authorization)
    if not user.get("company_id"):
        raise HTTPException(status_code=400, detail="No company assigned")
    company = await db.companies.find_one(
        {"company_id": user["company_id"]},
        {"_id": 0, "name": 1, "office_lat": 1, "office_lng": 1, "geofence_radius_m": 1},
    )
    sites: List[dict] = []
    if company and company.get("office_lat") is not None:
        sites.append({
            "worksite_id": "main",
            "name": f"{company.get('name') or 'Main Office'} (Main Office)",
            "office_lat": company["office_lat"],
            "office_lng": company["office_lng"],
            "geofence_radius_m": company.get("geofence_radius_m") or 200,
        })
    async for b in db.branches.find(
        {"company_id": user["company_id"], "active": {"$ne": False}},
        {"_id": 0, "branch_id": 1, "name": 1, "office_lat": 1,
         "office_lng": 1, "geofence_radius_m": 1},
    ):
        sites.append({
            "worksite_id": b["branch_id"],
            "name": b.get("name") or "Branch",
            "office_lat": b["office_lat"],
            "office_lng": b["office_lng"],
            "geofence_radius_m": b.get("geofence_radius_m") or 200,
        })
    return {"worksites": sites}


@api.post("/attendance/punch")
async def punch(payload: AttendancePunch, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    if not user.get("company_id"):
        raise HTTPException(status_code=400, detail="No company assigned. Contact admin.")
    company = await db.companies.find_one({"company_id": user["company_id"]}, {"_id": 0})
    if not company:
        raise HTTPException(status_code=400, detail="Company not found")

    # Offline-sync idempotency (Phase 2): if this exact queued punch was
    # already accepted (same client_dedupe_id), return it instead of making
    # a duplicate. Keeps retries / multi-tab sync safe.
    if payload.client_dedupe_id:
        dup = await db.attendance.find_one(
            {"user_id": user["user_id"], "client_dedupe_id": payload.client_dedupe_id},
            {"_id": 0, "status": 1, "attendance_status": 1, "distance_m": 1})
        if dup:
            return {"ok": True, "duplicate": True,
                    "status": dup.get("status"),
                    "attendance_status": dup.get("attendance_status"),
                    "distance_m": dup.get("distance_m", 0),
                    "approval_required": dup.get("status") == "pending"}

    # Live-in staff (e.g. resort housekeeping who sleep on premises) are
    # ALWAYS inside the resort, but they can still be off-duty. For them
    # we bypass the geofence hard-reject entirely — the shift schedule +
    # daily roster handle who's actually working. Face-match (if enabled)
    # still applies so identity is verified.
    is_live_in = bool(user.get("is_live_in"))

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Iter 99 — GEOFENCE IS MANDATORY IN EVERY CONDITION (user rule).
    # ------------------------------------------------------------------
    # The old Iter 57 "no-GPS manual" bypass is REMOVED. Every punch —
    # auto (geofence), manual face or manual fingerprint — must carry GPS
    # coordinates and pass the geofence check. The only exception is
    # live-in staff (always on premises by definition).
    #
    # Iter 64 — GPS punching gating (kept for the punch *mode*):
    # ``gps_allowed`` = firm allows GPS punching AND user opted in. When
    # False the punch is in MANUAL BIOMETRIC mode: selfie + device
    # biometric are required — but the geofence check still applies.
    firm_loc_allow = bool(company.get("location_punching_enabled") is True)
    user_gps_opt = bool(user.get("gps_punch_enabled") is True)
    gps_allowed = firm_loc_allow and user_gps_opt
    manual_mode = not gps_allowed

    if manual_mode and not is_live_in:
        if not payload.selfie_base64:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Face selfie is required for manual punching. "
                    "Please capture a selfie and try again."
                ),
            )
        if payload.biometric_method not in ("fingerprint", "face"):
            raise HTTPException(
                status_code=400,
                detail="Device biometric (fingerprint/face) is required.",
            )

    # Only live-in staff may punch without coordinates.
    no_gps_manual = (
        payload.latitude is None
        or payload.longitude is None
    ) and is_live_in

    if no_gps_manual:
        dist = 0.0
        closest = None
        radius = company.get("geofence_radius_m") or 200
        outside = False   # live-in staff are on premises by definition
    else:
        if payload.latitude is None or payload.longitude is None:
            # Iter 99 — geofence verification is mandatory for every punch.
            raise HTTPException(
                status_code=400,
                detail=(
                    "Location is required — geofence verification is "
                    "mandatory for every punch. Please enable GPS/Location "
                    "and try again."
                ),
            )
        dist, closest = await _resolve_geofence(company, payload.latitude, payload.longitude)
        radius = closest.get("geofence_radius_m", 200) if closest else (
            company.get("geofence_radius_m") or 200
        )
        if not closest:
            # Firm has not configured any geofence (no office coords and no
            # branches) — nothing to verify against. Record the coords and
            # allow; admins should configure the geofence in Companies.
            outside = False
        else:
            outside = dist > radius
        if is_live_in:
            outside = False  # never treat live-in staff as outside


    # Load today's punches once — needed for both geofence AND toggle checks.
    # This lets an employee punch IN → OUT → IN → OUT ... any number of times
    # per day (each entry/exit is logged as a separate record), while still
    # rejecting double-IN or double-OUT which would corrupt the log.
    # Rejected punches are ignored for the last-kind check.
    # Iter 144 — "today" follows IST wall-clock (punch storage convention).
    # Phase 2 (offline sync): a punch queued offline carries its ORIGINAL
    # capture time (client_punch_at, real UTC ISO). Honour it so the punch
    # lands on the correct date/time even if it syncs hours/days later.
    punch_at_iso = None
    if payload.offline and payload.client_punch_at:
        try:
            _cap = datetime.fromisoformat(payload.client_punch_at.replace("Z", "+00:00"))
            if _cap.tzinfo is None:
                _cap = _cap.replace(tzinfo=timezone.utc)
            # Convert to IST wall-clock labelled UTC (storage convention).
            _cap_ist = _cap.astimezone(IST_TZ).replace(tzinfo=timezone.utc)
            # Sanity: reject future times / older than 7 days (clock tampering).
            _now = ist_wallclock_now()
            if _now - timedelta(days=7) <= _cap_ist <= _now + timedelta(minutes=10):
                punch_at_iso = _cap_ist.isoformat()
        except Exception:
            punch_at_iso = None
    today = (punch_at_iso[:10] if punch_at_iso
             else ist_wallclock_now().strftime("%Y-%m-%d"))
    today_recs = await db.attendance.find(
        {"user_id": user["user_id"], "date": today,
         "status": {"$ne": "rejected"}},
        {"_id": 0, "kind": 1, "at": 1, "status": 1},
    ).sort("at", 1).to_list(200)
    last_kind = today_recs[-1].get("kind") if today_recs else None

    # -----------------------------------------------------------------------
    # Auto-punch debounce (20 minutes)
    # -----------------------------------------------------------------------
    # When the geofence background task fires an auto-punch we don't want a
    # brief GPS jitter (employee stepped outside for a moment, or the phone
    # briefly lost signal) to record a spurious OUT (or a duplicate IN). Any
    # auto-source punch within `_AUTO_PUNCH_DEBOUNCE_MIN` minutes of the last
    # recorded punch — regardless of kind — is treated as a no-op and returns
    # the previous record so the client can update its local state cleanly.
    _AUTO_PUNCH_DEBOUNCE_MIN = 20  # minutes
    _incoming_src = (payload.source or "manual").lower()
    _is_auto = "auto" in _incoming_src or "geofence" in _incoming_src
    if _is_auto and today_recs:
        last = today_recs[-1]
        try:
            last_at = datetime.fromisoformat((last.get("at") or "").replace("Z", "+00:00"))
        except Exception:
            last_at = None
        if last_at is not None:
            # Iter 144 — compare in wall-clock space (punches are stored as
            # IST wall-clock labelled UTC).
            elapsed = (ist_wallclock_now() - last_at).total_seconds() / 60.0
            if elapsed < _AUTO_PUNCH_DEBOUNCE_MIN:
                logger.info(
                    "[punch] Debouncing auto punch for user=%s (%.1f min since last %s at %s)",
                    user["user_id"], elapsed, last.get("kind"), last.get("at"),
                )
                # Return the previous record so the client stays in sync
                # without surfacing an error to the user.
                return {
                    "ok": True,
                    "debounced": True,
                    "reason": "auto_punch_debounce",
                    "cooldown_minutes_remaining": round(_AUTO_PUNCH_DEBOUNCE_MIN - elapsed, 1),
                    "last_punch": {
                        "kind": last.get("kind"),
                        "at": last.get("at"),
                        "status": last.get("status") or "approved",
                    },
                }

    # Iter 68 — GEOFENCE IS ON BY DEFAULT.
    #
    # Phase-1 geofence POLICY: resolve the effective mode (strict / flexible
    # / field / remote / emergency) for this employee and let it drive the
    # accept / reject / approval decision. Default = strict, which keeps the
    # original behaviour intact for firms that don't configure a policy.
    from routes.geo_policy import resolve_geo_policy, evaluate_geo_punch
    _pol = await resolve_geo_policy(user, company)
    pol_mode = _pol["mode"]
    pol_settings = _pol["settings"]
    pol_decision = evaluate_geo_punch(
        pol_mode, pol_settings,
        outside=bool(outside), dist=float(dist), radius=float(radius),
        lat=payload.latitude, lng=payload.longitude,
        has_selfie=bool(payload.selfie_base64),
        reason=payload.reason, is_live_in=is_live_in,
    )
    # A non-strict mode may permit an outside punch — in that case we skip
    # the legacy hard-reject and let the record carry the policy status.
    policy_allows_outside = bool(pol_decision["allow"]) and pol_mode != "strict"

    # If the policy explicitly rejects (strict-outside, remote-outside,
    # missing reason/selfie for flexible/emergency) surface that message.
    if outside and not pol_decision["allow"]:
        raise HTTPException(status_code=400, detail=pol_decision["reject_reason"])

    # Iter 68 punch policy:
    #   • Outside the geofence → HARD REJECT (strict mode only).
    #   • Inside the geofence  → allow.  Auto-punches ("geofence-auto"
    #     source) are always marked "needs_approval" so the employer
    #     signs off before they count.  Manual punches from within the
    #     geofence go through directly (unchanged behaviour).
    #
    # A firm can OPT-OUT of strict rejection by setting
    # ``companies.reject_outside_geofence = False`` in Firm Settings.
    strict_outside = (company.get("reject_outside_geofence") is not False) \
        and not policy_allows_outside
    outside_note: Optional[str] = None
    if outside:
        loc_name = (closest or {}).get("name") or "office"
        # Fire an admin-notification anyway so employer sees the attempt.
        async def _fire_reject_notif(cid: str, uid: str, ename: str, ecode: Optional[str],
                                     kind_val: str, loc: str, d: int, r: int) -> None:
            try:
                admins = await db.users.find(
                    {"$or": [
                        {"role": "super_admin"},
                        {"role": "sub_admin"},
                        {"role": "company_admin", "company_id": cid},
                    ]},
                    {"_id": 0, "user_id": 1},
                ).to_list(500)
                if not admins:
                    return
                emp_label = ename + (f" ({ecode})" if ecode else "")
                kind_lbl = "PUNCH IN" if kind_val == "in" else "PUNCH OUT"
                subject = f"Punch attempted outside geofence · {emp_label}"
                body = (
                    f"{emp_label} tried to {kind_lbl} while {d} m outside "
                    f"the '{loc}' geofence (allowed {r} m).  The punch was "
                    f"rejected by policy.  You may adjust attendance manually "
                    f"from the Attendance Review screen if required."
                )
                now = now_iso()
                docs = [{
                    "message_id": f"msg_{uuid.uuid4().hex[:12]}",
                    "company_id": cid,
                    "from_user_id": uid,
                    "from_name": "Attendance system",
                    "to_user_id": a["user_id"],
                    "subject": subject,
                    "body": body,
                    "kind": "system",
                    "category": "geofence_reject",
                    "read": False,
                    "created_at": now,
                    "updated_at": now,
                } for a in admins]
                if docs:
                    await db.messages.insert_many(docs)
            except Exception:
                logger.exception("[iter68] geofence-reject notif failed")

        if strict_outside:
            asyncio.create_task(
                _fire_reject_notif(
                    company.get("company_id") or "",
                    user["user_id"],
                    user.get("name") or user.get("employee_code") or "Employee",
                    user.get("employee_code"),
                    payload.kind,
                    loc_name,
                    int(dist),
                    int(radius),
                ),
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f"You are {int(dist)}m outside the {loc_name} geofence "
                    f"(allowed {int(radius)}m).  Please move within the "
                    f"designated location to punch."
                ),
            )
        # Firm opted out of strict rejection → allow but flag + notify.
        if payload.kind == "in":
            outside_note = (
                f"punched-in {int(dist)}m from {loc_name} — pending admin review"
            )
            _ = True  # outside_needs_approval — now always True via Iter 86 rule
        else:
            if last_kind != "in":
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "You haven't punched in today (or already punched out). "
                        "Move closer to the office to punch in first."
                    ),
                )
            outside_note = f"punched-out {int(dist)}m from {loc_name}"
            _ = True  # outside_needs_approval — now always True via Iter 86 rule

    # Iter 68 — Auto-punches (source="geofence-auto") always need employer
    # approval — enforced further down by ``needs_approval`` which folds
    # in ``is_auto_source``.

    # Toggle idempotency for INSIDE-geofence punches: prevent double-IN and
    # double-OUT (which would break shift pairing). Auto-punch retries and
    # rapid double-taps in the UI must be no-ops rather than duplicate rows.
    if not outside:
        if payload.kind == "in" and last_kind == "in":
            raise HTTPException(
                status_code=400,
                detail="You are already punched in. Punch out before punching in again.",
            )
        if payload.kind == "out" and last_kind != "in":
            raise HTTPException(
                status_code=400,
                detail="You are not currently punched in. Punch in before punching out.",
            )

    record_id = f"att_{uuid.uuid4().hex[:12]}"
    # Iter 64 — location_status: "inside" / "outside" / "no-gps". This is the
    # single field UIs display as a coloured pill without needing to compute
    # anything from distance/radius/gps_verified.
    if no_gps_manual:
        location_status = "no-gps"
    elif outside:
        location_status = "outside"
    else:
        location_status = "inside"
    record = {
        "record_id": record_id,
        "user_id": user["user_id"],
        "company_id": user["company_id"],
        "branch_id": (closest or {}).get("branch_id"),
        "branch_name": (closest or {}).get("name"),
        "date": today,
        "kind": payload.kind,
        "at": (punch_at_iso or ist_wallclock_iso()),
        "synced_at": (ist_wallclock_iso() if payload.offline else None),
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "distance_m": round(dist, 1),
        "biometric_method": payload.biometric_method,
        "selfie_base64": payload.selfie_base64,
        "device_info": payload.device_info,
        "source": ("manual-nogps" if no_gps_manual else (payload.source or "manual")),
        "outside_geofence": bool(outside),
        "gps_verified": (not no_gps_manual),
        "location_status": location_status,
        # Iter 176 — guided punch workflow: employee-selected worksite.
        "worksite_id": payload.worksite_id or (closest or {}).get("branch_id"),
        "worksite_name": payload.worksite_name or (closest or {}).get("name"),
        # Phase-1 geofence policy metadata (audit + reporting).
        "policy_mode": pol_mode,
        "policy_source": _pol["source"],
        "punch_reason": (payload.reason or None),
        "gps_accuracy_m": payload.gps_accuracy_m,
        "battery_level": payload.battery_level,
        "mock_location": bool(payload.mock_location) if payload.mock_location is not None else None,
        # Offline sync metadata (Phase 2).
        "offline_punch": bool(payload.offline) if payload.offline is not None else False,
        "client_dedupe_id": payload.client_dedupe_id,
        "client_punch_at": payload.client_punch_at,
    }
    # Determine approval status. Auto punches (geofence enter/exit background
    # trigger) land as "pending" when the firm has punch_approval_required=True.
    # Iter 86 — Approval rules simplified per user request:
    #   "Approval Process Only for Manually Punch Update and VIA APP."
    #
    # This endpoint (`/api/attendance/punch`) is only ever hit by the
    # MOBILE APP - biometric hardware webhooks and ZK .dat imports both
    # bypass it. So every punch that reaches here is by definition a
    # "VIA APP" punch and must go through the admin approval queue,
    # regardless of source flavour (`manual`, `manual-nogps`,
    # `geofence-auto`, etc.).
    #
    # Outside-geofence punches still keep their extra "always approve"
    # gate so the Iter 64 audit contract holds even if a firm ever
    # decides to relax the app-approval requirement in the future.
    src = (record.get("source") or "manual").lower()
    _ = "auto" in src or "geofence" in src  # kept for audit reason text (unused after Iter 86)
    # Field mode auto-approves; every other app punch still needs approval.
    field_auto = bool(pol_decision.get("auto_approve")) and pol_mode == "field"
    # Phase 3 — fake/mock GPS flagged punches ALWAYS need manual approval,
    # even in auto-approving Field mode.
    if record.get("mock_location"):
        field_auto = False
    needs_approval = not field_auto
    record["status"] = "pending" if needs_approval else "approved"
    # Expanded status workflow (Phase 1) — richer value for badges/reports;
    # `status` stays pending/approved/rejected for backward compatibility.
    record["attendance_status"] = (
        "approved" if field_auto else pol_decision.get("attendance_status")
        or "pending_manager_approval"
    )
    record["original_at"] = record["at"]  # immutable original punch time
    if not needs_approval:
        # Manual / instantly-approved punches carry a synthetic decision so
        # audit trails remain uniform across the collection.
        record["decision_at"] = record["at"]
        record["decision_by"] = user["user_id"]
        if field_auto:
            record["decision_reason"] = "auto-approved (field-employee geofence policy)"
        elif src == "manual-nogps":
            record["decision_reason"] = (
                "auto-approved (manual biometric punch — GPS off)"
            )
        elif src == "manual":
            record["decision_reason"] = "auto-approved (manual punch)"
        else:
            record["decision_reason"] = "auto-approved (approval disabled)"
    if outside and outside_note:
        # Iter 64 — apply the note to BOTH IN and OUT outside-punches now
        # that IN is also allowed (with flagged approval).
        record["outside_note"] = outside_note

    # Optional face-match verification (per-company toggle).
    # - Auto-enrol if no reference photo yet (never blocks the punch).
    # - Compare against the profile photo. Flag on mismatch; never block.
    identity: dict = {"enabled": bool(company.get("face_match_enabled"))}
    if identity["enabled"] and payload.selfie_base64:
        fresh_user = await db.users.find_one(
            {"user_id": user["user_id"]},
            {"_id": 0, "profile_photo_base64": 1},
        ) or {}
        ref = fresh_user.get("profile_photo_base64")
        if not ref:
            # First-time enrolment — save selfie as the reference.
            await db.users.update_one(
                {"user_id": user["user_id"]},
                {"$set": {
                    "profile_photo_base64": payload.selfie_base64,
                    "profile_photo_updated_at": now_iso(),
                    "profile_photo_auto_enrolled": True,
                }},
            )
            record["identity_enrolled"] = True
            record["identity_flagged"] = False
            identity["enrolled"] = True
        else:
            match_result = await _compare_faces(ref, payload.selfie_base64)
            record["identity_match_ok"] = bool(match_result.get("ok"))
            record["identity_match"] = match_result.get("match")
            record["identity_confidence"] = match_result.get("confidence") or 0.0
            record["identity_reason"] = match_result.get("reason")
            # Flag if the model confidently says NOT a match.
            record["identity_flagged"] = (
                match_result.get("ok") is True
                and match_result.get("match") is False
            )
            identity.update({
                "ok": match_result.get("ok"),
                "match": match_result.get("match"),
                "confidence": match_result.get("confidence"),
                "reason": match_result.get("reason"),
                "flagged": record["identity_flagged"],
            })

    # Iter 175 — contractual employees: stamp contractor for the report
    # (app punches are already pending, so no status change here).
    await apply_contractual_gate(record)
    await db.attendance.insert_one(record)
    record.pop("_id", None)
    # Iter 99 — personal punch notification with the joined firm's name.
    # Works the same for IN and OUT, all sources (manual / auto / first-login).
    try:
        _ist = timezone(timedelta(hours=5, minutes=30))
        _hhmm = datetime.now(_ist).strftime("%H:%M")
        _firm = company.get("name") or ""
        _kind_lbl = "IN" if record.get("kind") == "in" else "OUT"
        await db.notifications.insert_one({
            "notification_id": f"n_{uuid.uuid4().hex[:10]}",
            "company_id": user.get("company_id"),
            "audience": "user",
            "target_user_id": user["user_id"],
            "type": "punch.self",
            "title": f"Punch {_kind_lbl} — {_firm}",
            "body": (
                f"You punched {_kind_lbl} at {_hhmm} · {_firm}"
                + (" (awaiting admin approval)" if record.get("status") == "pending" else "")
            ),
            "created_at": now_iso(),
            "created_by": "system",
        })
        # Iter 103 — automated email trigger (punch_in / punch_out)
        try:
            from routes.email_notifications import fire_email_event
            await fire_email_event(
                "punch_in" if record.get("kind") == "in" else "punch_out",
                company_id=user.get("company_id"),
                employee_user_id=user["user_id"],
                details=f"Punch {_kind_lbl} at {_hhmm}")
        except Exception:
            pass
    except Exception:
        pass

    # Iter 77n — Real-time broadcast to admin dashboards + employee app.
    try:
        from utils.ws_broker import broker as _ws
        _ev = {
            "type": "punch.created",
            "user_id": user["user_id"],
            "employee_name": user.get("name"),
            "employee_code": user.get("employee_code"),
            "date": record.get("date"),
            "at": record.get("at"),
            "kind": record.get("kind"),
            "source": record.get("source") or "mobile",
            "status": record.get("status"),
        }
        await _ws.broadcast_firm(user.get("company_id") or "", _ev)
        await _ws.broadcast_user(user["user_id"], _ev)
    except Exception:
        pass
    # Iter 204 — Instant Shift Exception: if this IN punch clearly doesn't
    # match the employee's assigned shift (and no approved daily assignment
    # exists for today), prompt the PWA to raise a Shift Change Request.
    _shift_mismatch = None
    try:
        _sc_cfg = (company.get("attendance_policy") or {}).get("shift_change") or {}
        if _sc_cfg.get("enabled") and _sc_cfg.get("instant_exception", True) \
                and record.get("kind") == "in" and user.get("shift_start"):
            _today = record.get("date")
            _has_override = await db.daily_shift_assignments.find_one(
                {"user_id": user["user_id"], "date": _today}, {"_id": 1})
            if not _has_override:
                _ist2 = timezone(timedelta(hours=5, minutes=30))
                _now_min = datetime.now(_ist2).hour * 60 + datetime.now(_ist2).minute
                _sh, _sm = int(user["shift_start"][:2]), int(user["shift_start"][3:5])
                _start_min = _sh * 60 + _sm
                _diff = min(abs(_now_min - _start_min), 1440 - abs(_now_min - _start_min))
                if _diff > 120:  # > 2 hours away from assigned shift start
                    _shift_mismatch = {
                        "detected": True,
                        "assigned_shift": {
                            "name": user.get("shift_name"),
                            "start": user.get("shift_start"),
                            "end": user.get("shift_end"),
                        },
                        "message": ("Your punch does not match your assigned shift. "
                                    "Do you want to submit a Shift Change Request?"),
                    }
    except Exception:
        pass

    return {
        "ok": True,
        "record_id": record_id,
        "distance_m": round(dist, 1),
        "branch_id": (closest or {}).get("branch_id"),
        "branch_name": (closest or {}).get("name"),
        "outside_geofence": bool(outside),
        "identity": identity,
        "status": record["status"],
        "approval_required": needs_approval,
        "shift_mismatch": _shift_mismatch,
    }


@api.get("/attendance/first-punch-status")
async def first_punch_status(authorization: Optional[str] = Header(None)):
    """Iter 99 — after an employee registers (QR / joining form) and logs
    in for the FIRST time, the app auto-triggers their first Punch IN.
    Pending = employee with ZERO attendance records ever."""
    user = await get_user_from_token(authorization)
    if user.get("role") != "employee" or not user.get("company_id"):
        return {"first_punch_pending": False}
    existing = await db.attendance.count_documents(
        {"user_id": user["user_id"]}, limit=1,
    )
    return {"first_punch_pending": existing == 0}


@api.get("/attendance/today")
async def attendance_today(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    records = await db.attendance.find(
        {"user_id": user["user_id"], "date": today},
        {"_id": 0, "selfie_base64": 0},
    ).sort("at", 1).to_list(50)
    # Iter 64 — back-fill location_status for older records.
    for r in records:
        if not r.get("location_status"):
            r["location_status"] = _compute_location_status(r)
    return {"date": today, "records": records}


# ---------------------------------------------------------------------------
# Iter 94 — Geofence-exit alert.  When an on-duty employee walks OUT of the
# office geofence while auto punch-out is OFF (device toggle off or firm
# auto-punch disabled), the mobile app calls this endpoint.  We notify the
# firm's admins AND the super admin so they can mark a Half Day or punch
# the employee OUT manually from Punch Approvals.
# ---------------------------------------------------------------------------
@api.post("/attendance/geofence-exit-alert")
async def geofence_exit_alert(
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    if user.get("role") != "employee":
        raise HTTPException(status_code=403, detail="Employees only")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Only alert when the employee is actually ON DUTY (open IN punch).
    records = await db.attendance.find(
        {"user_id": user["user_id"], "date": today},
        {"_id": 0, "kind": 1, "at": 1},
    ).sort("at", 1).to_list(50)
    last = records[-1] if records else None
    if not last or last.get("kind") != "in":
        return {"ok": False, "skipped": "not_on_duty"}

    # One alert per employee per day.
    existing = await db.geofence_alerts.find_one(
        {"user_id": user["user_id"], "date": today}, {"_id": 0},
    )
    if existing:
        return {"ok": True, "deduped": True}

    ist = timezone(timedelta(hours=5, minutes=30))
    hhmm = datetime.now(ist).strftime("%H:%M")
    name = user.get("name") or "Employee"
    code = user.get("employee_code")
    who = f"{name} ({code})" if code else name

    await db.geofence_alerts.insert_one({
        "alert_id": f"gfa_{uuid.uuid4().hex[:10]}",
        "user_id": user["user_id"],
        "company_id": user.get("company_id"),
        "date": today,
        "at": now_iso(),
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
    })

    title = "Employee out of geofence"
    body = (
        f"{who} left the office geofence at {hhmm} while still punched IN "
        f"(auto punch-out is OFF). You may mark a Half Day or punch them "
        f"OUT from Punch Approvals / Manage Punches."
    )
    base = {
        "title": title,
        "body": body,
        "type": "geofence_alert",
        "employee_user_id": user["user_id"],
        "created_at": now_iso(),
        "created_by": "system",
    }
    # 1) Firm-scoped → visible to that firm's admins only.
    # 2) Global + super_admins audience → visible to super admins only.
    await db.notifications.insert_many([
        {**base, "notification_id": f"n_{uuid.uuid4().hex[:10]}",
         "company_id": user.get("company_id"), "audience": "admins"},
        {**base, "notification_id": f"n_{uuid.uuid4().hex[:10]}",
         "company_id": None, "audience": "super_admins"},
    ])
    logger.info("[geofence-alert] %s out of fence (company=%s)",
                user["user_id"], user.get("company_id"))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Attendance approvals — Approve / Reject / Adjust for AUTO punches when the
# firm has punch_approval_required = True (default).
# ---------------------------------------------------------------------------
class PunchDecision(BaseModel):
    action: Literal["approve", "reject", "adjust"]
    # Required for "adjust" — the corrected wall-clock time. Accepts either a
    # full ISO timestamp or "HH:MM" (interpreted against the record's own date).
    adjusted_time: Optional[str] = None
    reason: Optional[str] = None


def _parse_adjust_time(record: dict, raw: str) -> str:
    """Normalise an admin-supplied adjustment time. Accepts:
      - full ISO ("2026-06-15T09:12:00+00:00")
      - "HH:MM" — combined with the record's `date` in UTC.
    Returns an ISO 8601 string. Raises HTTPException(400) on bad input.
    """
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Please enter the corrected punch time.")
    # HH:MM shorthand
    if re.fullmatch(r"[0-2][0-9]:[0-5][0-9]", raw):
        base_date = record.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            dt = datetime.fromisoformat(f"{base_date}T{raw}:00+00:00")
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid time '{raw}' — use HH:MM (24-hour).")
        return dt.isoformat()
    # Full ISO
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=f"'{raw}' isn’t a valid time. Use HH:MM or a full ISO timestamp.",
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@api.get("/attendance/pending-punches")
async def list_pending_punches(
    company_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    include_decided: bool = Query(False),
    authorization: Optional[str] = Header(None),
):
    """Attendance approval queue for admins. Super admins see all pending
    punches (optionally filtered by ?company_id=); company admins are always
    scoped to their own company. Set ?include_decided=true to also return
    the last N records that were already approved/rejected (audit view)."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "company_admin", "sub_admin"])
    q: dict = {}
    if user["role"] == "company_admin":
        q["company_id"] = user["company_id"]
    elif company_id:
        q["company_id"] = company_id
    if not include_decided:
        q["status"] = "pending"
    else:
        q["status"] = {"$in": ["pending", "approved", "rejected"]}
    records = await db.attendance.find(
        q, {"_id": 0, "selfie_base64": 0}
    ).sort("at", -1).to_list(limit)
    # Attach a compact user summary so the UI doesn't need N follow-up calls
    user_ids = list({r.get("user_id") for r in records if r.get("user_id")})
    users = {}
    if user_ids:
        async for u in db.users.find(
            {"user_id": {"$in": user_ids}},
            {"_id": 0, "user_id": 1, "name": 1, "father_name": 1, "employee_code": 1, "designation": 1, "profile_photo_base64": 1},
        ):
            users[u["user_id"]] = u
    for r in records:
        u = users.get(r.get("user_id")) or {}
        r["employee"] = {
            "user_id": u.get("user_id"),
            "name": u.get("name"),
            "father_name": u.get("father_name"),
            "employee_code": u.get("employee_code"),
            "designation": u.get("designation"),
            "profile_photo_base64": u.get("profile_photo_base64"),
        }
    pending_count = sum(1 for r in records if (r.get("status") or "") == "pending")
    return {"records": records, "pending_count": pending_count}


@api.post("/attendance/punches/{record_id}/decision")
async def decide_punch(
    record_id: str,
    payload: PunchDecision,
    authorization: Optional[str] = Header(None),
):
    """Approve / Reject / Adjust a pending auto-punch."""
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "company_admin", "sub_admin"])
    rec = await db.attendance.find_one({"record_id": record_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Punch not found")
    if user["role"] == "company_admin" and rec.get("company_id") != user.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this punch")
    if (rec.get("status") or "approved") != "pending":
        # Super admins can retroactively edit any punch (rare, but useful when
        # the admin realises later that yesterday's approved punch is wrong).
        # Company admins can only act on pending punches.
        if user.get("role") != "super_admin":
            raise HTTPException(
                status_code=400,
                detail=f"This punch was already {(rec.get('status') or 'approved')}. Only a super admin can change a decided punch.",
            )
    updates: dict = {
        "decision_by": user["user_id"],
        "decision_at": now_iso(),
        "decision_reason": (payload.reason or "").strip() or None,
    }
    if payload.action == "approve":
        updates["status"] = "approved"
    elif payload.action == "reject":
        # Reject requires a reason so the audit trail is meaningful.
        if not updates["decision_reason"]:
            raise HTTPException(status_code=400, detail="Please provide a short reason for rejecting this punch.")
        updates["status"] = "rejected"
    elif payload.action == "adjust":
        # Adjust = approve with a corrected time. Iter 83-final — Also
        # update the canonical ``at`` field so downstream views (grid,
        # OT report, IN/OUT sheet) pick up the adjusted time. The
        # ORIGINAL punch time is preserved on ``original_at`` for audit.
        if not payload.adjusted_time:
            raise HTTPException(status_code=400, detail="Adjustment time is required to save an adjusted punch.")
        new_iso = _parse_adjust_time(rec, payload.adjusted_time)
        updates["status"] = "approved"
        updates["adjusted_at"] = new_iso
        updates["adjusted_by"] = user["user_id"]
        if not rec.get("original_at"):
            updates["original_at"] = rec.get("at")
        updates["at"] = new_iso
        updates.setdefault("decision_reason", None)
        if not updates["decision_reason"]:
            updates["decision_reason"] = "Time adjusted by admin"
    r = await db.attendance.update_one({"record_id": record_id}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Punch disappeared during update")
    updated = await db.attendance.find_one({"record_id": record_id}, {"_id": 0, "selfie_base64": 0})
    return {"ok": True, "record": updated}


@api.get("/attendance/history")
async def attendance_history(
    days: int = Query(30, le=90),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    records = await db.attendance.find(
        {"user_id": user["user_id"], "date": {"$gte": since}},
        {"_id": 0, "selfie_base64": 0},
    ).sort("at", -1).to_list(1000)
    # Iter 64 — surface location_status for the employee-side history UI.
    for r in records:
        if not r.get("location_status"):
            r["location_status"] = _compute_location_status(r)
    return {"records": records}


@api.get("/attendance/{record_id}/selfie")
async def get_my_punch_selfie(
    record_id: str,
    authorization: Optional[str] = Header(None),
):
    """Iter 97 — employee self-access to the selfie captured on their OWN
    punch. Strictly scoped: the attendance record's user_id must match the
    requesting token's user_id."""
    user = await get_user_from_token(authorization)
    rec = await db.attendance.find_one(
        {"record_id": record_id},
        {"_id": 0, "selfie_base64": 1, "user_id": 1},
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Punch not found")
    if rec.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your punch")
    return {"selfie_base64": rec.get("selfie_base64")}


@api.get("/attendance/my-month")
async def my_month_attendance(
    month: str = Query(..., description="YYYY-MM"),
    authorization: Optional[str] = Header(None),
):
    """Employee self-service month view. Computed with the SAME policy
    pipeline as the admin Attendance Grid (bounce-merge, dedup, OT cap,
    weekly-off rules, shift/policy overrides) so the attendance data an
    employee sees always matches their assigned attendance policy."""
    user = await get_user_from_token(authorization)
    company_id = user.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="No firm linked to your account")
    if not re.match(r"^\d{4}-\d{2}$", month or ""):
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    data = await _compute_monthly_grid_data(
        company_id=company_id, month=month, only_user_id=user["user_id"],
    )
    row = next(
        (r for r in (data.get("employees") or []) if r.get("user_id") == user["user_id"]),
        None,
    )
    # Effective weekly-off days (firm policy + per-employee override) so the
    # client can mark week-offs even on days without punches.
    comp = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "attendance_policy": 1},
    )
    pol = (comp or {}).get("attendance_policy") or {}
    emp_doc = await db.users.find_one(
        {"user_id": user["user_id"]}, {"_id": 0, "attendance_policy_override": 1},
    )
    eff = apply_employee_policy_override(dict(pol), emp_doc or {})
    weekly_off_days = list(eff.get("weekly_off_days") or [])
    weekly_set = set(weekly_off_days)

    labels = data.get("day_labels") or []
    full_dates = data.get("day_full_dates") or []
    days: Dict[str, Any] = {}
    totals: Dict[str, Any] = {}
    if row:
        for idx, lbl in enumerate(labels):
            c = dict((row.get("days") or {}).get(lbl) or {})
            c.pop("salary", None)  # attendance-only view (no pay data here)
            # Grid cells only carry present/weekly_off on cleanly-paired
            # punch days — normalise so EVERY cell has both fields.
            if "present" not in c:
                c["present"] = 0.0
            if "weekly_off" not in c:
                try:
                    wd = datetime.strptime(full_dates[idx], "%Y-%m-%d").weekday()
                except (ValueError, IndexError):
                    wd = -1
                c["weekly_off"] = wd in weekly_set
            days[lbl] = c
        totals = dict(row.get("totals") or {})
        totals.pop("salary_total", None)
    return {
        "month": data.get("month"),
        "day_labels": labels,
        "day_full_dates": full_dates,
        "weekday_labels": data.get("weekday_labels"),
        "full_day_hours": data.get("full_day_hours"),
        "weekly_off_days": weekly_off_days,
        "days": days,
        "totals": totals,
    }


def _effective_at(rec: dict) -> Optional[str]:
    """Effective punch timestamp for hour computations. Prefers admin-adjusted
    time (set via the approvals flow) and falls back to the original."""
    return rec.get("adjusted_at") or rec.get("at")


def _is_countable(rec: dict) -> bool:
    """True if a punch should be counted toward working hours / attendance
    reports. Legacy records without a `status` field are treated as approved
    for backward-compat."""
    st = (rec.get("status") or "approved").lower()
    return st == "approved"


def _compute_day_hours(records: list) -> tuple[float, Optional[str], Optional[str], bool]:
    """Given all attendance records for a single (user, date), compute total
    duty hours by pairing consecutive IN/OUT punches in chronological order.

    Returns: (hours, first_in_iso, last_out_iso, still_in)
    Pending / rejected punches are excluded so admin decisions correctly
    influence reports and dashboards.
    """
    if not records:
        return (0.0, None, None, False)
    # Filter to countable records first, then order by effective time.
    countable = [r for r in records if _is_countable(r)]
    recs = sorted(countable, key=lambda r: _effective_at(r) or "")
    total_seconds = 0.0
    open_in: Optional[datetime] = None
    first_in: Optional[str] = None
    last_out: Optional[str] = None
    for r in recs:
        kind = (r.get("kind") or "").lower()
        at = _effective_at(r)
        try:
            dt = datetime.fromisoformat((at or "").replace("Z", "+00:00"))
        except Exception:
            continue
        if kind == "in":
            if open_in is None:
                open_in = dt
                if first_in is None:
                    first_in = at
        elif kind == "out":
            last_out = at
            if open_in is not None:
                total_seconds += max(0.0, (dt - open_in).total_seconds())
                open_in = None
    still_in = open_in is not None
    hours = round(total_seconds / 3600.0, 2)
    return (hours, first_in, last_out, still_in)


@api.get("/attendance/summary")
async def attendance_summary(
    days: int = Query(7, ge=1, le=90),
    authorization: Optional[str] = Header(None),
):
    """Return per-day duty hours for the last N days for the current user,
    plus total hours worked till today (all-time) and window total."""
    user = await get_user_from_token(authorization)
    since_dt = datetime.now(timezone.utc) - timedelta(days=days - 1)
    since_str = since_dt.strftime("%Y-%m-%d")
    recs = await db.attendance.find(
        {"user_id": user["user_id"], "date": {"$gte": since_str}},
        {"_id": 0, "selfie_base64": 0},
    ).sort("at", 1).to_list(5000)
    by_date: dict[str, list] = {}
    for r in recs:
        by_date.setdefault(r.get("date"), []).append(r)

    days_out: list[dict] = []
    for i in range(days - 1, -1, -1):
        d = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        hrs, fin, lout, still = _compute_day_hours(by_date.get(d) or [])
        days_out.append({
            "date": d,
            "hours": hrs,
            "first_in": fin,
            "last_out": lout,
            "still_in": still,
            "punches": len(by_date.get(d) or []),
        })

    # User directive — the employee-facing duty widget must follow the Firm
    # Master attendance policy. Overlay per-day HOURS from the same grid
    # pipeline the admin Grid View / payroll uses (bounce-merge, dedup, OT
    # cap, shift overrides, missing-punch = 0). first_in/last_out/still_in
    # stay raw so the "currently punched-in" indicator keeps working.
    if user.get("company_id"):
        try:
            to_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            pdata = await _compute_monthly_grid_data(
                company_id=user["company_id"],
                month=since_str[:7],
                from_date=since_str,
                to_date=to_str,
                only_user_id=user["user_id"],
            )
            prow = next(
                (r for r in (pdata.get("employees") or [])
                 if r.get("user_id") == user["user_id"]),
                None,
            )
            if prow:
                cells = prow.get("days") or {}
                labels = pdata.get("day_labels") or []
                dates = pdata.get("day_full_dates") or []
                by_full_date = {
                    dates[i]: cells.get(labels[i]) or {}
                    for i in range(min(len(labels), len(dates)))
                }
                for row in days_out:
                    cell = by_full_date.get(row["date"])
                    if cell is not None and not row.get("still_in"):
                        row["hours"] = float(cell.get("hours") or 0.0)
        except Exception:
            logger.exception("policy overlay failed for /attendance/summary")
    window_total = round(sum(d["hours"] for d in days_out), 2)

    # All-time total — compute across ALL of the user's attendance in one pass
    all_recs = await db.attendance.find(
        {"user_id": user["user_id"]},
        {"_id": 0, "selfie_base64": 0, "device_info": 0},
    ).sort("at", 1).to_list(50000)
    all_by_date: dict[str, list] = {}
    for r in all_recs:
        all_by_date.setdefault(r.get("date"), []).append(r)
    total_all = 0.0
    for d, rs in all_by_date.items():
        h, _, _, _ = _compute_day_hours(rs)
        total_all += h
    total_all = round(total_all, 2)

    return {
        "days": days_out,
        "window_total_hours": window_total,
        "total_hours_till_today": total_all,
    }


@api.get("/admin/attendance/today")
async def admin_attendance_today(
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """List employees who punched IN today, with their first-in / last-out and
    duty hours so far. Scoped to the caller's company for company_admin; super
    admin may pass ?company_id=... to filter."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    scope_company: Optional[str] = None
    if user["role"] == "company_admin":
        scope_company = user.get("company_id")
    elif user["role"] == "super_admin" and company_id and company_id != "all":
        scope_company = company_id

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    q: dict = {"date": today}
    if scope_company:
        q["company_id"] = scope_company
    recs = await db.attendance.find(
        q, {"_id": 0, "selfie_base64": 0, "device_info": 0}
    ).sort("at", 1).to_list(20000)

    # Group by user
    by_user: dict[str, list] = {}
    for r in recs:
        by_user.setdefault(r["user_id"], []).append(r)

    if not by_user:
        return {"date": today, "present": []}

    users = await db.users.find(
        {"user_id": {"$in": list(by_user.keys())}},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "company_id": 1},
    ).to_list(20000)
    users_by_id = {u["user_id"]: u for u in users}

    # Fetch company names for a small map (super admin cross-company view)
    company_ids = list({u.get("company_id") for u in users if u.get("company_id")})
    companies = []
    if company_ids:
        companies = await db.companies.find(
            {"company_id": {"$in": company_ids}}, {"_id": 0, "company_id": 1, "name": 1}
        ).to_list(1000)
    company_names = {c["company_id"]: c["name"] for c in companies}

    present: list[dict] = []
    for uid, rs in by_user.items():
        hrs, fin, lout, still = _compute_day_hours(rs)
        u = users_by_id.get(uid, {})
        # Trim each punch to just the fields the timeline UI needs. Explicit
        # allow-list so we never leak selfies / device_info by accident.
        timeline = [
            {
                "at": r.get("at"),
                "kind": r.get("kind"),
                "source": r.get("source"),
                "latitude": r.get("latitude"),
                "longitude": r.get("longitude"),
                "outside_note": r.get("outside_note"),
                "branch_id": r.get("branch_id"),
                "branch_name": r.get("branch_name"),
                "approved_by": r.get("approved_by"),
            }
            for r in rs
        ]
        present.append({
            "user_id": uid,
            "name": u.get("name") or "Unknown",
            "employee_code": u.get("employee_code"),
            "company_id": u.get("company_id"),
            "company_name": company_names.get(u.get("company_id")),
            "first_in": fin,
            "last_out": lout,
            "still_in": still,
            "hours": hrs,
            "punches": len(rs),
            "timeline": timeline,
        })
    # Order by first_in ascending
    present.sort(key=lambda p: p.get("first_in") or "")
    return {"date": today, "present": present}


# ---------------------------------------------------------------------------
# Employee location ping (used by "present but not punched" report)
# ---------------------------------------------------------------------------
@api.post("/me/location-ping")
async def me_location_ping(
    payload: LocationPing,
    authorization: Optional[str] = Header(None),
):
    """Persist the caller's latest known GPS location on their user record.
    Idempotent — called by the mobile app when the attendance screen loads
    or when a location update is available. The location is NOT stored in a
    log, only the most recent value is kept (privacy-respecting).
    """
    user = await get_user_from_token(authorization)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "last_location_lat": payload.latitude,
            "last_location_lng": payload.longitude,
            "last_location_at": now_iso(),
        }},
    )
    return {"ok": True}


@api.get("/admin/attendance/present-not-punched")
async def admin_present_not_punched(
    company_id: Optional[str] = None,
    max_age_minutes: int = Query(60, ge=1, le=1440),
    authorization: Optional[str] = Header(None),
):
    """List employees whose LAST KNOWN location is INSIDE the office
    geofence for their company but who have NOT punched-in (or have not
    punched-out) today.

    - Only recent location pings (within `max_age_minutes`) are considered.
    - Company admins see their own company; super admins can filter by
      `company_id`.

    Response contains two lists: `not_punched_in` and `not_punched_out`.
    Each row includes distance-from-office (m), last-seen timestamp, and
    employee identity so the employer can review + approve.
    """
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])

    scope_company: Optional[str] = None
    if user["role"] == "company_admin":
        scope_company = user.get("company_id")
    elif user["role"] == "super_admin" and company_id and company_id != "all":
        scope_company = company_id

    # Load candidate companies + build a fast lookup
    company_query: dict = {}
    if scope_company:
        company_query["company_id"] = scope_company
    companies = await db.companies.find(
        company_query,
        {"_id": 0, "company_id": 1, "name": 1, "office_lat": 1,
         "office_lng": 1, "geofence_radius_m": 1},
    ).to_list(1000)
    if not companies:
        return {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "not_punched_in": [], "not_punched_out": []}
    companies_by_id = {c["company_id"]: c for c in companies}

    # Load users we care about — only employees with a location ping
    user_query: dict = {
        "role": "employee",
        "last_location_lat": {"$ne": None, "$exists": True},
        "last_location_lng": {"$ne": None, "$exists": True},
    }
    if scope_company:
        user_query["company_id"] = scope_company
    else:
        user_query["company_id"] = {"$in": list(companies_by_id.keys())}

    employees = await db.users.find(
        user_query,
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "phone": 1,
         "employee_code": 1, "company_id": 1, "last_location_lat": 1,
         "last_location_lng": 1, "last_location_at": 1,
         "onboarded": 1, "approval_status": 1, "exit_date": 1},
    ).to_list(20000)

    # Filter to onboarded + approved + not exited employees
    def _eligible(e: dict) -> bool:
        if not e.get("onboarded"):
            return False
        if (e.get("approval_status") or "approved") != "approved":
            return False
        if e.get("exit_date"):
            try:
                if e["exit_date"] <= datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                    return False
            except Exception:
                pass
        return True

    employees = [e for e in employees if _eligible(e)]

    if not employees:
        return {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "not_punched_in": [], "not_punched_out": []}

    # Compute today's attendance state per user in scope
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user_ids = [e["user_id"] for e in employees]
    att = await db.attendance.find(
        {"user_id": {"$in": user_ids}, "date": today},
        {"_id": 0, "user_id": 1, "kind": 1, "at": 1},
    ).sort("at", 1).to_list(20000)
    by_user: dict[str, list] = {}
    for r in att:
        by_user.setdefault(r["user_id"], []).append(r)

    threshold = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

    not_in: list[dict] = []
    not_out: list[dict] = []

    for e in employees:
        comp = companies_by_id.get(e.get("company_id"))
        if not comp:
            continue
        # Recency check
        last_at = e.get("last_location_at")
        try:
            if isinstance(last_at, str):
                last_dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            else:
                last_dt = last_at
        except Exception:
            last_dt = None
        if not last_dt:
            continue
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        if last_dt < threshold:
            continue
        # Distance check
        dist = haversine_m(
            e["last_location_lat"], e["last_location_lng"],
            comp.get("office_lat") or 0.0, comp.get("office_lng") or 0.0,
        )
        radius = comp.get("geofence_radius_m") or 200
        if dist > radius:
            continue

        recs = by_user.get(e["user_id"], [])
        has_in = any((r.get("kind") == "in") for r in recs)
        has_out_after_in = False
        # "has punched out for the current in" — latest kind is "out"
        if recs:
            has_out_after_in = recs[-1].get("kind") == "out"

        row = {
            "user_id": e["user_id"],
            "name": e.get("name") or "Unknown",
            "employee_code": e.get("employee_code"),
            "email": e.get("email"),
            "phone": e.get("phone"),
            "company_id": e.get("company_id"),
            "company_name": comp.get("name"),
            "distance_m": round(dist, 1),
            "geofence_radius_m": radius,
            "last_seen_at": (
                last_dt.isoformat() if hasattr(last_dt, "isoformat") else last_at
            ),
            "last_location_lat": e["last_location_lat"],
            "last_location_lng": e["last_location_lng"],
            "punches_today": len(recs),
        }

        if not has_in:
            not_in.append(row)
        elif not has_out_after_in:
            # Punched in but has not punched out yet
            not_out.append(row)

    not_in.sort(key=lambda r: r.get("distance_m") or 0)
    not_out.sort(key=lambda r: r.get("distance_m") or 0)

    return {
        "date": today,
        "not_punched_in": not_in,
        "not_punched_out": not_out,
    }


@api.post("/admin/attendance/approve-punch")
async def admin_approve_punch(
    payload: AdminApprovePunch,
    authorization: Optional[str] = Header(None),
):
    """Employer creates a punch on behalf of an employee. The employee must
    (a) belong to the employer's company, and (b) currently sit inside the
    office geofence (based on their last-known location). Records the
    creator + optional note for audit."""
    admin_user = await get_user_from_token(authorization)
    require_role(admin_user, ["company_admin", "super_admin", "sub_admin"])

    emp = await db.users.find_one({"user_id": payload.user_id}, {"_id": 0})
    if not emp or emp.get("role") != "employee":
        raise HTTPException(status_code=404, detail="Employee not found")

    # Scope: company admins can only act on their own employees
    if admin_user["role"] == "company_admin":
        if emp.get("company_id") != admin_user.get("company_id"):
            raise HTTPException(status_code=403, detail="Employee not in your company")

    comp = await db.companies.find_one({"company_id": emp.get("company_id")}, {"_id": 0})
    if not comp:
        raise HTTPException(status_code=400, detail="Employee has no company assigned")

    lat = emp.get("last_location_lat")
    lng = emp.get("last_location_lng")
    if lat is None or lng is None:
        raise HTTPException(
            status_code=400,
            detail="Employee has not shared their location recently. Ask them to open the app.",
        )
    dist = haversine_m(lat, lng, comp.get("office_lat") or 0.0, comp.get("office_lng") or 0.0)
    radius = comp.get("geofence_radius_m") or 200
    if dist > radius:
        raise HTTPException(
            status_code=400,
            detail=f"Employee is {int(dist)}m from office (allowed {int(radius)}m).",
        )

    # Idempotency (toggle style): allow multiple IN→OUT cycles per day, but
    # never a double-IN or double-OUT (would corrupt shift pairing).
    today = ist_wallclock_now().strftime("%Y-%m-%d")  # Iter 144 — wall-clock
    recs = await db.attendance.find(
        {"user_id": emp["user_id"], "date": today},
        {"_id": 0, "kind": 1, "at": 1},
    ).sort("at", 1).to_list(200)
    last_kind = recs[-1].get("kind") if recs else None
    if payload.kind == "in" and last_kind == "in":
        raise HTTPException(status_code=400, detail="Employee is already punched-in.")
    if payload.kind == "out" and last_kind != "in":
        raise HTTPException(status_code=400, detail="Employee is not currently punched-in.")

    record_id = f"att_{uuid.uuid4().hex[:12]}"
    record = {
        "record_id": record_id,
        "user_id": emp["user_id"],
        "company_id": emp["company_id"],
        "date": today,
        "kind": payload.kind,
        "at": ist_wallclock_iso(),
        "latitude": lat,
        "longitude": lng,
        "distance_m": round(dist, 1),
        "biometric_method": "fingerprint",  # not physically captured
        "selfie_base64": None,
        "device_info": None,
        "source": "admin_approved",
        "approved_by_user_id": admin_user["user_id"],
        "approved_by_name": admin_user.get("name") or admin_user.get("email"),
        "approver_note": (payload.note or "").strip() or None,
    }
    await db.attendance.insert_one(record)
    logger.info(
        f"[ADMIN PUNCH] {admin_user.get('email')} → punched {payload.kind} for "
        f"{emp.get('name')} ({emp.get('employee_code')}) — {int(dist)}m from office",
    )
    # Iter 145 — web-push the punch confirmation to the employee.
    try:
        from routes.web_push import push_to_user
        _k = "IN" if payload.kind == "in" else "OUT"
        await push_to_user(
            emp["user_id"], f"Punch {_k} approved",
            f"Your employer recorded a Punch {_k} for you at "
            f"{ist_wallclock_now().strftime('%I:%M %p')}.",
            url="/attendance", tag=f"punch_{record_id}")
    except Exception:
        pass
    return {"ok": True, "record_id": record_id, "distance_m": round(dist, 1)}


# ---------------------------------------------------------------------------
# Server-side shift auto-close
#
# If an employee punched IN but never punched OUT — because they force-quit
# the app, ran out of battery, or simply stopped using their phone — the
# background auto-punch task can't fire. This job scans for such
# "orphan" open shifts and closes them server-side so payroll doesn't
# skip the day and the admin's Present-Today view doesn't stay pinned on
# stale users.
#
# Two triggers close a shift:
#   1. Elapsed hours since IN >= AUTO_CLOSE_MAX_HOURS (default 12h)
#   2. Last-known GPS ping is outside the branch geofence for
#      >= AUTO_CLOSE_STALE_MINUTES (default 30 min) AND that ping is
#      more recent than the IN timestamp.
#
# Records are stamped with source="server_auto_close" plus a note so
# admins can distinguish auto-closed shifts from genuine punches.
# ---------------------------------------------------------------------------

AUTO_CLOSE_MAX_HOURS = float(os.getenv("AUTO_CLOSE_MAX_HOURS", "12"))
AUTO_CLOSE_STALE_MINUTES = int(os.getenv("AUTO_CLOSE_STALE_MINUTES", "30"))
AUTO_CLOSE_TICK_SECONDS = int(os.getenv("AUTO_CLOSE_TICK_SECONDS", "600"))  # 10 min


async def _auto_close_open_shifts() -> dict:
    """Scan today (UTC) for open IN punches with no matching OUT, and
    auto-close them where policy applies. Returns a summary dict.
    Idempotent — running twice in a row does nothing the second time."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_utc = datetime.now(timezone.utc)
    closed: list[dict] = []

    # Group today's punches by user
    pipeline = [
        {"$match": {"date": today}},
        {"$sort": {"at": 1}},
        {"$group": {
            "_id": "$user_id",
            "records": {"$push": {
                "kind": "$kind",
                "at": "$at",
                "company_id": "$company_id",
                "branch_id": "$branch_id",
            }},
        }},
    ]
    grouped = await db.attendance.aggregate(pipeline).to_list(5000)

    for g in grouped:
        recs = g.get("records") or []
        if not recs or recs[-1].get("kind") != "in":
            continue  # not an open shift

        last_in = recs[-1]
        try:
            last_in_at = datetime.fromisoformat(last_in["at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if last_in_at.tzinfo is None:
            last_in_at = last_in_at.replace(tzinfo=timezone.utc)

        elapsed_h = (now_utc - last_in_at).total_seconds() / 3600.0

        user_id = g["_id"]
        emp = await db.users.find_one(
            {"user_id": user_id},
            {"_id": 0, "user_id": 1, "company_id": 1, "role": 1,
             "last_location_lat": 1, "last_location_lng": 1,
             "last_location_at": 1},
        )
        if not emp or emp.get("role") != "employee":
            continue

        should_close = False
        reason = ""

        if elapsed_h >= AUTO_CLOSE_MAX_HOURS:
            should_close = True
            reason = f"open shift exceeded {AUTO_CLOSE_MAX_HOURS:g}h"

        # Geofence check (only if we haven't already decided to close)
        if not should_close:
            lat = emp.get("last_location_lat")
            lng = emp.get("last_location_lng")
            last_ping_at = emp.get("last_location_at")
            if lat is not None and lng is not None and last_ping_at:
                try:
                    ping_dt = datetime.fromisoformat(str(last_ping_at).replace("Z", "+00:00"))
                    if ping_dt.tzinfo is None:
                        ping_dt = ping_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    ping_dt = None
                if ping_dt and ping_dt > last_in_at:
                    company = await db.companies.find_one(
                        {"company_id": emp.get("company_id")}, {"_id": 0},
                    )
                    if company:
                        dist, closest = await _resolve_geofence(company, lat, lng)
                        radius = (closest or {}).get("geofence_radius_m") or (
                            company.get("geofence_radius_m") or 200
                        )
                        stale_min = (now_utc - ping_dt).total_seconds() / 60.0
                        if dist > radius and stale_min >= AUTO_CLOSE_STALE_MINUTES:
                            should_close = True
                            reason = (
                                f"left geofence {int(dist)}m and no ping for "
                                f"{int(stale_min)} min"
                            )

        if not should_close:
            continue

        record_id = f"att_{uuid.uuid4().hex[:12]}"
        out_at = now_utc if elapsed_h < AUTO_CLOSE_MAX_HOURS else (
            last_in_at + timedelta(hours=AUTO_CLOSE_MAX_HOURS)
        )
        record = {
            "record_id": record_id,
            "user_id": user_id,
            "company_id": emp.get("company_id"),
            "branch_id": last_in.get("branch_id"),
            "date": today,
            "kind": "out",
            "at": out_at.isoformat(),
            "latitude": emp.get("last_location_lat"),
            "longitude": emp.get("last_location_lng"),
            "source": "server_auto_close",
            "outside_note": f"auto-closed: {reason}",
            "auto_closed": True,
        }
        await db.attendance.insert_one(record)
        closed.append({
            "user_id": user_id,
            "record_id": record_id,
            "reason": reason,
            "elapsed_hours": round(elapsed_h, 2),
        })

    return {"scanned": len(grouped), "closed": len(closed), "records": closed}


@api.post("/admin/attendance/auto-close")
async def admin_trigger_auto_close(authorization: Optional[str] = Header(None)):
    """On-demand trigger of the auto-close job. Only super_admin and
    company_admin can invoke — useful for manual verification / testing."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    summary = await _auto_close_open_shifts()
    return {"ok": True, **summary}


@api.get("/admin/attendance/open-shifts")
async def list_open_shifts(
    authorization: Optional[str] = Header(None),
    company_id: Optional[str] = None,
):
    """Return employees who have punched IN today but never punched OUT.
    Useful for admins to see who might need a manual close."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_utc = datetime.now(timezone.utc)

    # Scope filter
    match_q: dict = {"date": today}
    if user["role"] == "company_admin":
        match_q["company_id"] = user.get("company_id")
    elif user["role"] == "super_admin" and company_id and company_id != "all":
        match_q["company_id"] = company_id

    pipeline = [
        {"$match": match_q},
        {"$sort": {"at": 1}},
        {"$group": {
            "_id": "$user_id",
            "records": {"$push": {
                "kind": "$kind",
                "at": "$at",
                "source": "$source",
            }},
            "company_id": {"$last": "$company_id"},
        }},
    ]
    grouped = await db.attendance.aggregate(pipeline).to_list(5000)

    open_shifts: list[dict] = []
    uids: list[str] = []
    for g in grouped:
        recs = g.get("records") or []
        if not recs or recs[-1].get("kind") != "in":
            continue
        uids.append(g["_id"])
        try:
            last_in_at = datetime.fromisoformat(recs[-1]["at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if last_in_at.tzinfo is None:
            last_in_at = last_in_at.replace(tzinfo=timezone.utc)
        elapsed_h = (now_utc - last_in_at).total_seconds() / 3600.0
        open_shifts.append({
            "user_id": g["_id"],
            "company_id": g.get("company_id"),
            "last_in_at": recs[-1]["at"],
            "elapsed_hours": round(elapsed_h, 2),
            "punch_count": len(recs),
            "will_auto_close": elapsed_h >= AUTO_CLOSE_MAX_HOURS,
        })

    if uids:
        users = await db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
             "company_id": 1, "last_location_lat": 1, "last_location_lng": 1,
             "last_location_at": 1},
        ).to_list(1000)
        u_by_id = {u["user_id"]: u for u in users}
        cids = list({u.get("company_id") for u in users if u.get("company_id")})
        companies = await db.companies.find(
            {"company_id": {"$in": cids}},
            {"_id": 0, "company_id": 1, "name": 1},
        ).to_list(500) if cids else []
        c_by_id = {c["company_id"]: c["name"] for c in companies}
        for s in open_shifts:
            u = u_by_id.get(s["user_id"], {})
            s["name"] = u.get("name")
            s["employee_code"] = u.get("employee_code")
            s["company_name"] = c_by_id.get(u.get("company_id"))
            s["last_location_lat"] = u.get("last_location_lat")
            s["last_location_lng"] = u.get("last_location_lng")
            s["last_location_at"] = u.get("last_location_at")

    # Sort: longest open first
    open_shifts.sort(key=lambda x: x["elapsed_hours"], reverse=True)
    return {
        "open_shifts": open_shifts,
        "count": len(open_shifts),
        "auto_close_after_hours": AUTO_CLOSE_MAX_HOURS,
    }


# ---------------------------------------------------------------------------
# Daily roster (resort / hospitality use case)
# Live-in staff can't rely on geofence auto-punch. The supervisor uses
# the roster to (a) see everyone's punch state at a glance and (b)
# batch-record IN/OUT punches or absences without visiting each
# employee's row separately.
# ---------------------------------------------------------------------------


class RosterMark(BaseModel):
    user_id: str
    action: Literal["in", "out", "absent"]


class RosterMarkRequest(BaseModel):
    marks: List[RosterMark]
    note: Optional[str] = None


@api.get("/admin/attendance/roster")
async def get_daily_roster(
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Everyone in scope + their current punch state today. Used by
    the supervisor to mark present/absent for live-in staff whose
    phones may never leave the premises."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scope_filter: dict = {"role": "employee"}
    if admin["role"] == "company_admin":
        scope_filter["company_id"] = admin.get("company_id")
    elif admin["role"] == "super_admin" and company_id and company_id != "all":
        scope_filter["company_id"] = company_id

    users = await db.users.find(
        scope_filter,
        {
            "_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
            "company_id": 1, "shift_start": 1, "shift_end": 1,
            "is_live_in": 1, "onboarded": 1, "approval_status": 1,
            "exit_date": 1,
        },
    ).sort("name", 1).to_list(20000)

    # Drop inactive / unapproved employees from the roster surface.
    users = [
        u for u in users
        if u.get("onboarded")
        and (u.get("approval_status") or "approved") == "approved"
        and not (u.get("exit_date") and u["exit_date"] <= today)
    ]

    if not users:
        return {"date": today, "roster": [], "count": 0}

    uids = [u["user_id"] for u in users]
    recs = await db.attendance.find(
        {"user_id": {"$in": uids}, "date": today},
        {"_id": 0, "user_id": 1, "kind": 1, "at": 1, "source": 1},
    ).sort("at", 1).to_list(50000)
    by_user: dict[str, list[dict]] = {}
    for r in recs:
        by_user.setdefault(r["user_id"], []).append(r)

    roster = []
    for u in users:
        rs = by_user.get(u["user_id"], [])
        last = rs[-1] if rs else None
        first_in = next((x["at"] for x in rs if x["kind"] == "in"), None)
        last_out = None
        for x in reversed(rs):
            if x["kind"] == "out":
                last_out = x["at"]
                break
        state = (
            "in" if last and last["kind"] == "in"
            else "done" if rs
            else "absent"
        )
        roster.append({
            "user_id": u["user_id"],
            "name": u.get("name"),
            "employee_code": u.get("employee_code"),
            "is_live_in": bool(u.get("is_live_in")),
            "shift_start": u.get("shift_start"),
            "shift_end": u.get("shift_end"),
            "first_in": first_in,
            "last_out": last_out,
            "punch_count": len(rs),
            "state": state,
        })
    return {"date": today, "roster": roster, "count": len(roster)}


@api.post("/admin/attendance/roster/mark")
async def batch_roster_mark(
    payload: RosterMarkRequest,
    authorization: Optional[str] = Header(None),
):
    """Bulk record IN/OUT punches for a set of employees. Reuses
    `approve-punch` guard logic. Skipping rows that would create a
    double-IN / double-OUT is silent — we return per-row results."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin", "sub_admin"])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results = []
    for m in payload.marks:
        emp = await db.users.find_one(
            {"user_id": m.user_id},
            {"_id": 0, "user_id": 1, "company_id": 1, "role": 1},
        )
        if not emp or emp.get("role") != "employee":
            results.append({"user_id": m.user_id, "ok": False, "detail": "not found"})
            continue
        if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
            results.append({"user_id": m.user_id, "ok": False, "detail": "not your company"})
            continue

        if m.action == "absent":
            # Persist an explicit "absent" record so the employee sees the
            # roster decision in their own Today / History screens. Idempotent
            # per user+date — repeated marks just refresh the metadata.
            existing = await db.attendance.find_one(
                {"user_id": m.user_id, "date": today, "kind": "absent"},
                {"_id": 0, "record_id": 1},
            )
            if existing:
                await db.attendance.update_one(
                    {"record_id": existing["record_id"]},
                    {"$set": {
                        "at": now_iso(),
                        "approved_by": admin["user_id"],
                        "roster_note": payload.note,
                    }},
                )
                results.append({
                    "user_id": m.user_id, "ok": True, "action": "absent",
                    "record_id": existing["record_id"], "updated": True,
                })
                continue
            record_id = f"att_{uuid.uuid4().hex[:12]}"
            record = {
                "record_id": record_id,
                "user_id": m.user_id,
                "company_id": emp.get("company_id"),
                "date": today,
                "kind": "absent",
                "at": now_iso(),
                "source": "roster",
                "status": "approved",
                "approved_by": admin["user_id"],
                "roster_note": payload.note,
            }
            await db.attendance.insert_one(record)
            results.append({
                "user_id": m.user_id, "ok": True, "action": "absent",
                "record_id": record_id,
            })
            continue

        # Toggle idempotency check — only among non-absent records
        rs = await db.attendance.find(
            {"user_id": m.user_id, "date": today, "kind": {"$in": ["in", "out"]}},
            {"_id": 0, "kind": 1, "at": 1},
        ).sort("at", 1).to_list(200)
        last_kind = rs[-1].get("kind") if rs else None
        if m.action == "in" and last_kind == "in":
            results.append({"user_id": m.user_id, "ok": False, "detail": "already in"})
            continue
        if m.action == "out" and last_kind != "in":
            results.append({"user_id": m.user_id, "ok": False, "detail": "not currently in"})
            continue

        # If an "absent" record exists for today, marking IN should retract it
        # so the employee's day flips from Absent → Present cleanly.
        if m.action == "in":
            await db.attendance.delete_many(
                {"user_id": m.user_id, "date": today, "kind": "absent"}
            )

        record_id = f"att_{uuid.uuid4().hex[:12]}"
        record = {
            "record_id": record_id,
            "user_id": m.user_id,
            "company_id": emp.get("company_id"),
            "date": today,
            "kind": m.action,
            "at": now_iso(),
            "source": "roster",
            "status": "approved",  # roster punches are pre-approved by admin
            "approved_by": admin["user_id"],
            "roster_note": payload.note,
        }
        await db.attendance.insert_one(record)
        results.append({
            "user_id": m.user_id,
            "ok": True,
            "action": m.action,
            "record_id": record_id,
        })
    return {"results": results, "count": len(results)}


# ---------------------------------------------------------------------------
# In-app messaging
# Admin (company_admin or super_admin) composes announcements or DMs; each
# message stores a `recipient_user_ids` list plus a `read_by` list to power
# unread badges. One-way for now — employees can only read.
# ---------------------------------------------------------------------------

class MessageAttachment(BaseModel):
    """Iter 74 — single attachment on an in-app message.

    ``base64`` may include the ``data:...;base64,`` prefix (the API
    strips it before storage). Server enforces max size ≤ 5 MB and
    max 3 attachments per message.
    """
    filename: str
    mime_type: str
    base64: str
    size_bytes: Optional[int] = None


class MessageCreate(BaseModel):
    subject: str
    body: str
    # Choose one of the following two recipient modes:
    broadcast: bool = False  # send to all employees in the caller's scope
    recipient_user_ids: Optional[List[str]] = None  # explicit multi-select
    # Optional company override for super_admin. Ignored for company_admin.
    company_id: Optional[str] = None
    # Iter 74 — optional attachments (images / PDF), max 3 × 5 MB each.
    attachments: Optional[List[MessageAttachment]] = None




# ---------------------------------------------------------------------------
# Payslips
# ---------------------------------------------------------------------------
def _last_completed_month(now: datetime) -> str:
    """Return 'YYYY-MM' of the month that just completed (i.e. previous month)."""
    if now.month == 1:
        return f"{now.year - 1}-12"
    return f"{now.year}-{now.month - 1:02d}"


def _parse_any_date(val: Any) -> Optional[datetime]:
    """Iter 170 — tolerant date parser for exit/leaving dates that may be
    stored as YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY or YYYY/MM/DD."""
    s = str(val or "").strip()[:10].replace("/", "-")
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        pass
    try:
        d, m, y = s.split("-")
        if len(y) == 4:
            return datetime(int(y), int(m), int(d))
    except Exception:
        pass
    return None


def _month_is_after_exit(user: dict, month_str: str) -> bool:
    """Iter 166/170 — True when the employee is resigned/exited and must be
    excluded from salary processing (user directive: applies to BOTH the
    Compliance and the Actual salary process).

    Rules:
      * exit/leaving date BEFORE the 1st of the run month → excluded;
      * exit date DURING the run month → still payable (final settlement);
      * marked resigned/exited (employment_status) with NO parseable date,
        or an unreadable exit date → excluded entirely (can't determine
        the month, so never show them in a salary run).
    """
    ed = (user.get("exit_date") or user.get("resign_date")
          or user.get("date_of_leaving") or user.get("leaving_date"))
    status_resigned = str(user.get("employment_status") or "").strip().lower() in (
        "exited", "resigned", "terminated", "inactive", "left")
    if not ed:
        return status_resigned  # marked resigned without a date → exclude
    dt = _parse_any_date(ed)
    if dt is None:
        return True  # exit marker present but unreadable → exclude
    try:
        y, m = int(month_str[:4]), int(month_str[5:7])
        return dt < datetime(y, m, 1)
    except Exception:
        return True


def _month_is_before_doj(user: dict, month_str: str) -> bool:
    """Return True when the given 'YYYY-MM' precedes the employee's DOJ.

    We compare using month-end. If DOJ is inside the run month, the employee
    is INCLUDED (their attendance count will already be zero for the days
    before joining). If DOJ falls in a later month, the employee is EXCLUDED.
    """
    doj = user.get("doj")
    if not doj:
        return False  # no DOJ set — can't exclude
    try:
        # Parse both dates
        y, m = int(month_str[:4]), int(month_str[5:7])
        # Month end = the 28th of the next month (safe upper bound so that
        # a DOJ on the 31st of the run month still classifies as "in").
        if m == 12:
            end_of_run = datetime(y + 1, 1, 1)
        else:
            end_of_run = datetime(y, m + 1, 1)
        doj_dt = datetime.fromisoformat(doj[:10])
        return doj_dt >= end_of_run
    except Exception:
        return False


def _month_is_complete(month_str: str, now: Optional[datetime] = None) -> bool:
    """Return True when the 'YYYY-MM' month is entirely in the past."""
    now = now or datetime.now(timezone.utc)
    try:
        y, m = int(month_str[:4]), int(month_str[5:7])
    except Exception:
        return False
    if y < now.year:
        return True
    if y > now.year:
        return False
    return m < now.month


def _payslip_is_processed(slip: dict) -> bool:
    """True when a payslip has been genuinely PROCESSED (pushed from a
    salary run OR marked paid), not just auto-created as pending."""
    if not slip:
        return False
    if slip.get("salary_run_id") or slip.get("compliance_salary_run_id"):
        return True
    return (slip.get("status") or "").lower() == "paid"


@api.get("/salary/monthly")
async def salary_monthly(authorization: Optional[str] = Header(None)):
    """Show the employee their per-month salary status for the last 6 months.

    Iter 57 rules (user request):
      1. Do NOT auto-create pending payslips for months BEFORE the employee's
         date of joining (DOJ).
      2. Only return payslips for months that are FULLY COMPLETE (past) AND
         where the payslip has been actually PROCESSED (pushed from a salary
         run or marked "paid"). Auto-pending slips are never shown here.
    """
    user = await get_user_from_token(authorization)
    salary = user.get("salary_monthly")

    now = datetime.now(timezone.utc)
    months: List[str] = []
    y, m = now.year, now.month
    for _ in range(6):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        months.append(f"{y}-{m:02d}")

    # Skip pre-DOJ months entirely.
    months = [mo for mo in months if not _month_is_before_doj(user, mo)]

    if salary and salary > 0:
        for month in months:
            existing = await db.payslips.find_one({
                "employee_user_id": user["user_id"],
                "month": month,
            })
            if not existing:
                await db.payslips.insert_one({
                    "slip_id": f"ps_{uuid.uuid4().hex[:12]}",
                    "employee_user_id": user["user_id"],
                    "company_id": user.get("company_id"),
                    "month": month,
                    "gross": float(salary),
                    "deductions": 0.0,
                    "net": float(salary),
                    "status": "pending",
                    "pdf_base64": None,
                    "created_at": now_iso(),
                    "created_by": "system_auto",
                })

    raw_slips = await db.payslips.find(
        {"employee_user_id": user["user_id"], "month": {"$in": months}},
        {"_id": 0},
    ).sort("month", -1).to_list(60)

    # Only surface PROCESSED slips for COMPLETED months.
    slips = [
        s for s in raw_slips
        if _month_is_complete(s.get("month", ""), now) and _payslip_is_processed(s)
    ]

    current_month = f"{now.year}-{now.month:02d}"
    return {
        "salary_monthly": salary,
        "current_month": current_month,
        "history": slips,
    }




# ---------------------------------------------------------------------------
# Iter 74 — Employee self-service payslip PDF + ID Card
# ---------------------------------------------------------------------------
@api.get("/me/payslips/{slip_id}.pdf")
async def me_download_payslip_pdf(
    slip_id: str,
    authorization: Optional[str] = Header(None),
):
    """Employee downloads their OWN payslip PDF for a given slip_id.

    The payslip must belong to the logged-in employee and must be
    PROCESSED (linked to a salary run or marked paid). We rebuild the
    PDF on-the-fly from the salary-run row so we always get the latest
    template layout even if the stored ``pdf_base64`` is stale.
    """
    from fastapi.responses import Response
    from utils.payslip_pdf import build_payslip_pdf as _build_ps_pdf

    user = await get_user_from_token(authorization)
    slip = await db.payslips.find_one({"slip_id": slip_id}, {"_id": 0})
    if not slip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    if slip.get("employee_user_id") != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Not your payslip")
    if not _payslip_is_processed(slip):
        raise HTTPException(
            status_code=400,
            detail="Payslip is still pending — please try again once your salary is processed.",
        )

    company = await db.companies.find_one(
        {"company_id": user.get("company_id")}, {"_id": 0},
    ) or {}
    month = slip.get("month") or ""

    # Prefer a fresh rebuild off the linked salary run for full detail.
    run_row: Optional[Dict[str, Any]] = None
    run_days: Optional[int] = None
    run_id = slip.get("salary_run_id") or slip.get("compliance_salary_run_id")
    if run_id:
        run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0}) \
            or await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
        if run:
            run_days = run.get("month_days")
            for row in (run.get("rows") or []):
                if row.get("user_id") == user.get("user_id"):
                    run_row = row
                    break

    if not run_row:
        # Fallback synthetic row using the payslip totals.
        run_row = {
            "user_id": user.get("user_id"),
            "name": user.get("name"),
            "gross": float(slip.get("gross") or 0),
            "deductions": float(slip.get("deductions") or 0),
            "net": float(slip.get("net") or 0),
        }

    pdf_bytes = _build_ps_pdf(
        employee=user,
        company=company,
        row={**run_row, "month_days": run_days},
        month=month,
    )
    fname = f"Payslip_{(user.get('employee_code') or user.get('user_id') or 'me')}_{month}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@api.get("/me/payslips/year-summary")
async def me_payslips_year_summary(
    fy: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 74 — Aggregate the employee's last 12 processed payslips.

    Returns totals + a month-wise list ready to render in the mobile
    Payslip History browser. Only PROCESSED (salary-run-linked OR paid)
    slips are counted.
    """
    user = await get_user_from_token(authorization)
    now = datetime.now(timezone.utc)
    # Build the 12-month window ending at last completed month.
    months: List[str] = []
    for i in range(1, 13):
        y = now.year
        m = now.month - i
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y}-{m:02d}")

    raw = await db.payslips.find(
        {
            "employee_user_id": user["user_id"],
            "month": {"$in": months},
        },
        {"_id": 0},
    ).sort("month", -1).to_list(60)
    slips = [s for s in raw if _payslip_is_processed(s)]

    total_gross = sum(float(s.get("gross") or 0) for s in slips)
    total_deductions = sum(float(s.get("deductions") or 0) for s in slips)
    total_net = sum(float(s.get("net") or 0) for s in slips)
    paid_count = sum(1 for s in slips if (s.get("status") or "").lower() == "paid")

    return {
        "window_months": months,
        "totals": {
            "gross": round(total_gross, 2),
            "deductions": round(total_deductions, 2),
            "net": round(total_net, 2),
            "count": len(slips),
            "paid_count": paid_count,
        },
        "history": slips,
    }


@api.get("/me/id-card")
async def me_id_card(authorization: Optional[str] = Header(None)):
    """Iter 74 — Employee ID Card payload.

    Returns the small data blob the mobile UI needs to render a
    photo-ID-style card:
      * name, employee_code, designation, department, doj
      * company name + code + logo (if any)
      * `qr_payload` — canonical string to be encoded into the QR:
        ``SKSCO|<company_code>|<employee_code>|<user_id>``
        Scanners at the biometric turnstile can parse this to look up
        the employee record.
    """
    user = await get_user_from_token(authorization)
    company = None
    if user.get("company_id"):
        company = await db.companies.find_one(
            {"company_id": user["company_id"]},
            {"_id": 0, "name": 1, "company_code": 1, "logo_base64": 1, "address": 1},
        )
    emp_code = user.get("employee_code") or ""
    comp_code = (company or {}).get("company_code") or ""
    qr_payload = f"SKSCO|{comp_code}|{emp_code}|{user.get('user_id') or ''}"
    return {
        "employee": {
            "user_id": user.get("user_id"),
            "name": user.get("name"),
            "employee_code": emp_code,
            "designation": user.get("designation"),
            "department": user.get("department"),
            "doj": user.get("doj"),
            "phone": user.get("phone"),
            "email": user.get("email"),
            "picture": user.get("picture"),  # base64 or URL
            "blood_group": user.get("blood_group"),
            # Iter 85 — Address is now shown on the downloadable ID card.
            "address": user.get("address"),
        },
        "company": company or {},
        "qr_payload": qr_payload,
        "generated_at": now_iso(),
    }



# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@api.get("/admin/payroll")
async def admin_payroll(
    month: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(pending|paid)$"),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """List payslips across employees, scoped to the admin's company."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    q: dict = {}
    if user["role"] == "company_admin":
        q["company_id"] = user.get("company_id")
    elif company_id:
        q["company_id"] = company_id
    if month:
        q["month"] = month
    if status:
        q["status"] = status
    slips = await db.payslips.find(q, {"_id": 0}).sort([("month", -1), ("employee_user_id", 1)]).to_list(2000)
    # Attach employee names
    user_ids = list({s["employee_user_id"] for s in slips})
    users = await db.users.find({"user_id": {"$in": user_ids}}, {"_id": 0, "user_id": 1, "name": 1, "email": 1}).to_list(2000)
    umap = {u["user_id"]: u for u in users}
    for s in slips:
        emp = umap.get(s["employee_user_id"])
        if emp:
            s["employee_name"] = emp.get("name")
            s["employee_email"] = emp.get("email")
    return {"payslips": slips}


@api.get("/admin/payroll/run")
async def admin_payroll_run(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Compute a lightweight monthly payroll run for every eligible
    employee in scope. See `_compute_payroll_run` for details."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    return await _compute_payroll_run(user, year, month, company_id)


async def _compute_payroll_run(
    user: dict, year: int, month: int, company_id: Optional[str],
) -> dict:
    """Extracted so it can be reused by the email-report endpoint. The
    caller must have already validated the acting user's role.

    Returns {year, month, month_key, days_in_month, off_days_total,
    rows[], totals{}, attendance[]} where `attendance` is a per-employee
    day-by-day punch summary (used to build the punch-sheet CSV/PDF).
    """
    scope_company: Optional[str] = None
    if user["role"] == "company_admin":
        scope_company = user.get("company_id")
    elif user["role"] == "super_admin" and company_id and company_id != "all":
        scope_company = company_id

    user_q: dict = {"role": "employee"}
    if scope_company:
        user_q["company_id"] = scope_company
    employees = await db.users.find(
        user_q,
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "employee_code": 1,
         "company_id": 1, "salary_monthly": 1, "onboarded": 1,
         "approval_status": 1, "exit_date": 1, "join_date": 1,
         "employee_policy": 1, "full_day_hrs": 1, "half_day_hrs": 1},
    ).to_list(20000)
    def _eligible(e: dict) -> bool:
        if not e.get("onboarded"):
            return False
        if (e.get("approval_status") or "approved") != "approved":
            return False
        if e.get("exit_date") and e["exit_date"] < f"{year}-{month:02d}-01":
            return False
        return True
    employees = [e for e in employees if _eligible(e)]
    if not employees:
        return {
            "year": year, "month": month,
            "month_key": f"{year}-{month:02d}",
            "days_in_month": 0,
            "off_days_total": 0,
            "rows": [],
            "attendance": [],
            "totals": {"employees": 0, "gross_total": 0, "total_hours": 0},
        }

    # Month window
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    days_in_month = (end - start).days
    today = datetime.now(timezone.utc)
    last_visible_day = days_in_month
    if year == today.year and month == today.month:
        last_visible_day = today.day
    off_days_all = sum(
        1 for d in range(1, days_in_month + 1)
        if datetime(year, month, d).weekday() == 6
    )

    # Fetch attendance in one query
    user_ids = [e["user_id"] for e in employees]
    month_key = f"{year}-{month:02d}"
    att = await db.attendance.find(
        {"user_id": {"$in": user_ids}, "date": {"$regex": f"^{month_key}-"}},
        {"_id": 0, "user_id": 1, "date": 1, "kind": 1, "at": 1},
    ).sort("at", 1).to_list(200000)
    by_user: dict[str, list] = {}
    for r in att:
        by_user.setdefault(r["user_id"], []).append(r)

    rows = []
    total_gross = 0.0
    total_hours = 0.0
    attendance_by_user: dict[str, dict[str, dict]] = {}
    for e in employees:
        policy = _get_policy_from_user(e)
        recs = by_user.get(e["user_id"], [])
        # Bucket by date, sorted
        by_date: dict[str, list] = {}
        for r in recs:
            by_date.setdefault(r["date"], []).append(r)

        # Per-day attendance: full / half / present via hours thresholds
        fullday_hrs = float(policy.get("fullday_hours") or e.get("full_day_hrs") or 6)
        halfday_hrs = float(policy.get("halfday_hours") or e.get("half_day_hrs") or 3)
        full_day_salary_flag = bool(policy.get("full_day_salary"))

        present_dates: set[str] = set()
        half_day_dates: set[str] = set()
        total_secs = 0
        # Track first-IN / last-OUT / minutes per day for punch-sheet reports
        per_day: dict[str, dict] = {}
        for date_str, day_recs in by_date.items():
            day_recs.sort(key=lambda x: x["at"])
            has_in = False
            open_in: Optional[str] = None
            day_secs = 0
            first_in: Optional[str] = None
            last_out: Optional[str] = None
            for r in day_recs:
                if r["kind"] == "in":
                    has_in = True
                    open_in = r["at"]
                    if first_in is None:
                        first_in = r["at"]
                elif r["kind"] == "out" and open_in:
                    last_out = r["at"]
                    try:
                        t1 = datetime.fromisoformat(open_in.replace("Z", "+00:00"))
                        t2 = datetime.fromisoformat(r["at"].replace("Z", "+00:00"))
                        day_secs += max(0, int((t2 - t1).total_seconds()))
                    except Exception:
                        pass
                    open_in = None
                elif r["kind"] == "out":
                    last_out = r["at"]
            total_secs += day_secs
            per_day[date_str] = {
                "first_in": first_in,
                "last_out": last_out,
                "minutes": int(day_secs / 60),
                "punches": len(day_recs),
            }
            hrs = day_secs / 3600.0
            if has_in:
                if full_day_salary_flag:
                    present_dates.add(date_str)  # always full when flag on
                elif hrs >= fullday_hrs or day_secs == 0:
                    # No punch-out yet → treat as attended (full day pending)
                    present_dates.add(date_str)
                elif hrs >= halfday_hrs:
                    half_day_dates.add(date_str)
                else:
                    # Attended but below half-day threshold → still count as
                    # attended for the "present" tally, but half-value pay
                    half_day_dates.add(date_str)
        present_days = len(present_dates)
        half_days = len(half_day_dates)
        hours = round(total_secs / 3600.0, 2)

        weekly_off_dow = (policy.get("weekly_off") if policy.get("weekly_off") is not None else 6)
        try:
            weekly_off_dow = int(weekly_off_dow)
        except Exception:
            weekly_off_dow = 6
        # Python weekday: 0=Mon..6=Sun. The UI stores 0=Sun..6=Sat.
        # Convert UI → Python: (ui + 6) % 7
        py_weekly_off = (weekly_off_dow + 6) % 7

        absent_days = 0
        off_days = 0
        join_str = e.get("join_date") or ""
        for d in range(1, last_visible_day + 1):
            date_str = f"{month_key}-{d:02d}"
            if join_str and date_str < join_str:
                continue
            wk = datetime(year, month, d).weekday()
            if wk == py_weekly_off:
                off_days += 1
                continue
            if date_str not in present_dates and date_str not in half_day_dates:
                absent_days += 1

        # Optional weekly-off pay: if the flag is on AND the employee
        # accumulated at least `week_off_min_hours` total hours in the
        # month, we treat weekly-off days as paid days too (added to
        # working denominator and to numerator).
        paid_off_days = 0
        min_hrs = float(policy.get("week_off_min_hours") or 0)
        if policy.get("weekly_off_attendance") and hours >= min_hrs:
            paid_off_days = off_days

        # Effective "attendance-equivalent" numerator
        # full days = 1.0, half days = 0.5, paid off days = 1.0
        attendance_units = present_days + 0.5 * half_days + paid_off_days
        # Denominator: full working days (present+half+absent) + paid_off_days
        working_days = present_days + half_days + absent_days
        denom = working_days + paid_off_days

        base_salary = float(policy.get("salary") or 0)
        base_gross = 0.0
        if base_salary > 0 and denom > 0:
            base_gross = round(base_salary * attendance_units / denom, 2)

        # Attendance-bonus tiers (cumulative). Only Salary 1 + Day 1 are
        # mandatory; Salary 2/3 optional.
        tier_bonus = 0.0
        tiers = []
        for i in (1, 2, 3):
            s_v = float(policy.get(f"salary_{i}") or 0)
            d_v = int(policy.get(f"day_{i}") or 0)
            unlocked = present_days >= d_v > 0 and s_v > 0
            tiers.append({"i": i, "salary": s_v, "day": d_v, "unlocked": unlocked})
            if unlocked:
                tier_bonus += s_v

        # OT pay (only if the flag is on): pay any hours beyond the
        # expected monthly hours at hourly rate = base / (working_days *
        # working_hours). Simplistic MVP.
        ot_pay = 0.0
        if policy.get("ot_allow"):
            working_hours_per_day = float(policy.get("working_hours") or 8)
            expected_hours = present_days * working_hours_per_day
            ot_hours = max(0.0, hours - expected_hours)
            if base_salary > 0 and working_hours_per_day > 0 and (working_days or 0) > 0:
                hourly_rate = base_salary / (working_days * working_hours_per_day)
                ot_pay = round(ot_hours * hourly_rate, 2)

        gross = round(base_gross + tier_bonus + ot_pay, 2)

        rows.append({
            "user_id": e["user_id"],
            "name": e.get("name") or "Unknown",
            "employee_code": e.get("employee_code"),
            "email": e.get("email"),
            "company_id": e.get("company_id"),
            "present_days": present_days,
            "half_days": half_days,
            "absent_days": absent_days,
            "off_days": off_days,
            "paid_off_days": paid_off_days,
            "days_in_month": days_in_month,
            "working_days": working_days,
            "total_hours": hours,
            "salary_monthly": base_salary if base_salary > 0 else None,
            "base_gross": base_gross,
            "tier_bonus": round(tier_bonus, 2),
            "ot_pay": ot_pay,
            "tiers": tiers,
            "gross": gross,
            "policy_confirmed": bool(policy.get("policy_confirmed")),
        })
        total_gross += gross
        total_hours += hours
        attendance_by_user[e["user_id"]] = per_day

    rows.sort(key=lambda r: (r.get("name") or "").lower())

    # Build a flat attendance list (day-by-day) for the punch-sheet report
    attendance: list[dict] = []
    for row in rows:
        uid = row["user_id"]
        pd = attendance_by_user.get(uid, {})
        for d in range(1, days_in_month + 1):
            date_str = f"{month_key}-{d:02d}"
            info = pd.get(date_str, {})
            attendance.append({
                "user_id": uid,
                "name": row["name"],
                "employee_code": row.get("employee_code"),
                "date": date_str,
                "first_in": info.get("first_in"),
                "last_out": info.get("last_out"),
                "minutes": info.get("minutes", 0),
                "punches": info.get("punches", 0),
            })

    return {
        "year": year,
        "month": month,
        "month_key": month_key,
        "days_in_month": days_in_month,
        "off_days_total": off_days_all,
        "rows": rows,
        "attendance": attendance,
        "totals": {
            "employees": len(rows),
            "gross_total": round(total_gross, 2),
            "total_hours": round(total_hours, 2),
        },
    }


@api.get("/admin/employees")
async def list_employees(
    company_id: Optional[str] = Query(None),
    company_ids: Optional[List[str]] = Query(
        None,
        description="Optional list of company_ids for cross-firm fetch. Ignored for company_admin. Overrides company_id when provided.",
    ),
    employee_type: Optional[str] = Query(
        None,
        description="Filter by exact employee_type (case-insensitive). Pass 'unset' to list employees with no type.",
    ),
    is_onroll: Optional[bool] = Query(
        None,
        description="True → only on-roll, False → only off-roll, omit → both.",
    ),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    q: dict = {}
    if user["role"] == "company_admin":
        q["company_id"] = user.get("company_id")
    elif company_ids:
        # Cross-firm mode. Super/Sub-admin can hit any set of firms.
        cleaned = [c for c in company_ids if c]
        if cleaned:
            q["company_id"] = {"$in": cleaned}
    elif company_id:
        q["company_id"] = company_id
    # Iter 133 (user bug) — sub-admins with a restricted company scope must
    # NEVER see other firms' employees, regardless of query params.
    if user["role"] == "sub_admin":
        q = apply_sub_admin_company_scope(user, q)
    # Employee grouping filters
    if employee_type is not None:
        et = employee_type.strip()
        if et.lower() == "unset":
            q["$or"] = [
                {"employee_type": {"$exists": False}},
                {"employee_type": None},
                {"employee_type": ""},
            ]
        elif et:
            # Title-case matches stored form; also match legacy raw form.
            title = et.title()
            q["employee_type"] = {"$in": [title, et, et.lower(), et.upper()]}
    if is_onroll is not None:
        if is_onroll:
            # Treat missing field as on-roll (default)
            q.setdefault("$and", []).append(
                {"$or": [{"is_onroll": True}, {"is_onroll": {"$exists": False}}, {"is_onroll": None}]}
            )
        else:
            q["is_onroll"] = False
    # Iter 68 — Restrict to actual employees only.  Prior to this the
    # endpoint returned every user in the firm including the Company Admin
    # (which surfaced on the Bulk Employee Correction screen as "Sharma
    # Associates Admin" etc.).
    q["role"] = "employee"
    users = await db.users.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    users = [_redact_user(u) for u in users]
    return {"employees": users}


@api.get("/admin/employee-types")
async def list_employee_types(
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Autocomplete source for the Employee Type field. Returns the distinct
    non-empty types already in use within the caller's scope, plus their
    usage counts so the UI can rank suggestions.
    """
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "sub_admin", "super_admin"])
    match: dict = {
        "employee_type": {"$exists": True, "$nin": [None, ""]},
        # Iter 169 (user bug) — group counts must reflect ACTIVE employees
        # only; resigned/exited/disabled staff inflated the numbers.
        "disabled": {"$ne": True},
        "employment_status": {"$not": {"$regex": "^(exited|resigned|terminated|inactive|left)$", "$options": "i"}},
        "$and": [
            {"$or": [{"exit_date": {"$in": [None, ""]}},
                     {"exit_date": {"$exists": False}}]},
            {"$or": [{"resign_date": {"$in": [None, ""]}},
                     {"resign_date": {"$exists": False}}]},
            {"$or": [{"date_of_leaving": {"$in": [None, ""]}},
                     {"date_of_leaving": {"$exists": False}}]},
            {"$or": [{"leaving_date": {"$in": [None, ""]}},
                     {"leaving_date": {"$exists": False}}]},
        ],
    }
    if user["role"] == "company_admin":
        match["company_id"] = user.get("company_id")
    elif company_id:
        match["company_id"] = company_id
    pipeline = [
        {"$match": match},
        {"$group": {"_id": {"$toUpper": {"$trim": {"input": "$employee_type"}}},
                    "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": 100},
    ]
    counts: dict = {}
    async for row in db.users.aggregate(pipeline):
        counts[row["_id"]] = int(row["count"])
    # Iter 129k (user directive) — the Employee Type options come from the
    # General Masters "group" list (global + firm scope), merged with live
    # usage counts. Case-insensitive so STAFF/Staff can never split.
    m_q: dict = {"type": "group"}
    scope_cid = match.get("company_id")
    if scope_cid:
        m_q["company_id"] = {"$in": [scope_cid, "__global__", None]}
    names: dict = {}
    async for m in db.masters.find(m_q, {"_id": 0, "name": 1}):
        nm = (m.get("name") or "").strip().upper()
        if nm:
            names[nm] = counts.get(nm, 0)
    for nm, c in counts.items():
        names.setdefault(nm, c)
    types = [{"name": n, "count": c} for n, c in names.items()]
    types.sort(key=lambda t: (-t["count"], t["name"]))
    return {"types": types}


# ---------------------------------------------------------------------------
# Retroactive punch management (company_admin + super_admin) — Iteration 52
# ---------------------------------------------------------------------------
# Existing decision endpoint only lets the admin approve / reject / adjust a
# *pending* auto-punch. Employer often needs to ADD an entirely new manual
# punch for a past date (e.g. employee forgot to biometric-clock in) OR
# DELETE an obviously-wrong record. Company admins are capped at a 90-day
# lookback for safety; super_admin has no range restriction.
_PUNCH_EDIT_LOOKBACK_DAYS = 90


class ManualPunchCreate(BaseModel):
    user_id: str
    kind: Literal["in", "out"]
    at: str  # ISO 8601 with timezone (or "YYYY-MM-DD HH:MM")
    reason: str  # mandatory audit note


class ManualPunchEdit(BaseModel):
    """Any field left None is unchanged."""
    at: Optional[str] = None
    kind: Optional[Literal["in", "out"]] = None
    reason: str  # mandatory audit note on every edit


# ---------------------------------------------------------------------------
# Iter 175 — Contractual employees (Firm Master Policy 2 contractors).
# Their punches NEVER land directly in attendance: machine/auto-approved
# punches are forced to "pending" so the company approves/rejects them
# first (Contractor Punch approvals). Once approved they flow into the
# attendance policy computation exactly like any other punch.
# ---------------------------------------------------------------------------
async def apply_contractual_gate(record: dict, user_doc: Optional[dict] = None) -> dict:
    u = user_doc
    if u is None or "is_contractual" not in u:
        u = await db.users.find_one(
            {"user_id": record.get("user_id")},
            {"_id": 0, "is_contractual": 1, "contractor_name": 1},
        ) or {}
    if not u.get("is_contractual"):
        return record
    record["is_contractual"] = True
    record.setdefault("contractor_name", u.get("contractor_name"))
    # Only demote punches that were AUTO-approved by a machine/system —
    # punches created directly by an admin stay approved (that IS the
    # company's approval).
    if (record.get("status") == "approved"
            and str(record.get("decision_by") or "").startswith("system:")):
        record["status"] = "pending"
        record["decision_by"] = None
        record["decision_at"] = None
        record["decision_reason"] = None
        record["pending_reason"] = "contractual_employee"
    return record


def _parse_manual_at(raw: str) -> datetime:
    """Accept 'YYYY-MM-DDTHH:MM' / 'YYYY-MM-DD HH:MM' / full ISO w/ tz. Falls
    back to UTC when no timezone is supplied."""
    s = (raw or "").strip()
    if not s:
        raise HTTPException(status_code=400, detail="Time is required")
    s = s.replace("Z", "+00:00")
    # Insert 'T' if missing between date and time
    if len(s) >= 16 and s[10] == " ":
        s = s[:10] + "T" + s[11:]
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid time '{raw}'. Use YYYY-MM-DDTHH:MM.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _enforce_lookback(admin: dict, when: datetime) -> None:
    """Company admins can only edit punches from the last 90 days."""
    if admin.get("role") == "super_admin":
        return
    now = datetime.now(timezone.utc)
    if when > now + timedelta(minutes=5):
        raise HTTPException(
            status_code=400,
            detail="Punch time cannot be in the future.",
        )
    if (now - when).days > _PUNCH_EDIT_LOOKBACK_DAYS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Employer can only edit punches within the last "
                f"{_PUNCH_EDIT_LOOKBACK_DAYS} days. Ask a super admin for older records."
            ),
        )


async def _log_punch_audit(
    action: str,
    admin: dict,
    record_id: str,
    before: Optional[dict],
    after: Optional[dict],
    reason: str,
) -> None:
    """Append to the attendance_audit_log collection. Kept lightweight —
    we deliberately drop base64 blobs to keep the log small."""
    def _clean(d: Optional[dict]) -> Optional[dict]:
        if not d:
            return d
        out = {k: v for k, v in d.items() if k not in ("_id", "selfie_base64", "photo_base64")}
        return out
    try:
        await db.attendance_audit_log.insert_one({
            "audit_id": f"aal_{uuid.uuid4().hex[:12]}",
            "record_id": record_id,
            "action": action,  # "create" | "edit" | "delete"
            "actor_user_id": admin.get("user_id"),
            "actor_role": admin.get("role"),
            "reason": reason,
            "at": now_iso(),
            "before": _clean(before),
            "after": _clean(after),
        })
    except Exception:
        logger.exception("[punch_audit] failed to persist audit row")


@api.get("/admin/attendance/day-status/{company_id}")
async def attendance_day_status(
    company_id: str,
    from_date: str = Query(...),
    to_date: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Iter 94 — Per-employee punch status for a date (or range, max 31
    days). Powers the Punch Approvals source tabs:
      • Updated       → rows where a punch was EDITED (app/web portal)
      • Auto-Punches  → rows where BOTH In & Out punches exist
      • Manual Entries→ rows with MISSING In / Out / Both (fill manually)
    Every active employee × date combo is returned; the client filters.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorised for this company")
    f = (from_date or "").strip()
    t = (to_date or "").strip() or f
    if t < f:
        t = f
    try:
        d0 = datetime.strptime(f, "%Y-%m-%d").date()
        d1 = datetime.strptime(t, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")
    if (d1 - d0).days > 31:
        raise HTTPException(status_code=400, detail="Range too large — max 31 days")

    emps = await db.users.find(
        {"company_id": company_id, "role": "employee",
         "disabled": {"$ne": True}, "exit_date": None},
        {"_id": 0, "user_id": 1, "name": 1, "father_name": 1,
         "designation": 1, "employee_code": 1,
         "shift_start": 1, "shift_end": 1, "attendance_policy_override": 1},
    ).to_list(2000)
    # Iter 95g — resolve each employee's shift times (Shift Master override
    # first, then the mirrored shift_start/shift_end strings) so the Manual
    # Entries tab can offer a one-tap "Fill from shift" for missing punches.
    _shift_docs = await db.shift_masters.find(
        {}, {"_id": 0, "shift_id": 1, "start": 1, "end": 1},
    ).to_list(200)
    _shifts_by_id = {s["shift_id"]: s for s in _shift_docs}
    # Iter 94 — NIGHT-SHIFT aware: fetch one day EITHER side of the range
    # so an 8pm→8am shift pairs its next-morning OUT (and a morning OUT
    # already owned by the previous night's IN isn't double-counted).
    f_minus = (d0 - timedelta(days=1)).strftime("%Y-%m-%d")
    t_plus = (d1 + timedelta(days=1)).strftime("%Y-%m-%d")
    recs = await db.attendance.find(
        {"company_id": company_id, "date": {"$gte": f_minus, "$lte": t_plus},
         "status": {"$ne": "rejected"}},
        {"_id": 0, "record_id": 1, "user_id": 1, "date": 1, "kind": 1,
         "at": 1, "edited_at": 1, "source": 1, "status": 1,
         "edit_reason": 1, "edited_by": 1, "original_at": 1},
    ).to_list(40000)

    # Iter 111 — resolve the editing admin's name for the Updated tab.
    _editor_ids = {r.get("edited_by") for r in recs if r.get("edited_by")}
    _editor_names: Dict[str, str] = {}
    if _editor_ids:
        async for u in db.users.find(
            {"user_id": {"$in": list(_editor_ids)}}, {"_id": 0, "user_id": 1, "name": 1},
        ):
            _editor_names[u["user_id"]] = u.get("name") or u["user_id"]

    def _at_dt(r: dict) -> Optional[datetime]:
        try:
            dt = datetime.fromisoformat((r.get("at") or "").replace("Z", "+00:00"))
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except Exception:
            return None

    def _cell(r: Optional[dict]) -> Optional[dict]:
        if not r:
            return None
        hhmm = ""
        dt = _at_dt(r)
        if dt:
            hhmm = dt.strftime("%H:%M")
        # Iter 111 — original (pre-edit) time for the Updated tab audit view.
        orig_hhmm = None
        if r.get("original_at"):
            try:
                odt = datetime.fromisoformat((r["original_at"] or "").replace("Z", "+00:00"))
                orig_hhmm = (odt.replace(tzinfo=None) if odt.tzinfo else odt).strftime("%H:%M")
            except Exception:
                orig_hhmm = None
        return {
            "record_id": r["record_id"], "at": r.get("at"), "hhmm": hhmm,
            "date": r.get("date"),
            "edited": bool(r.get("edited_at")), "source": r.get("source"),
            "status": r.get("status"),
            "edit_reason": r.get("edit_reason"),
            "edited_by_name": _editor_names.get(r.get("edited_by") or ""),
            "original_hhmm": orig_hhmm,
        }

    by_user: Dict[str, list] = {}
    for r in recs:
        dt = _at_dt(r)
        if dt is None:
            continue
        r["_dt"] = dt
        by_user.setdefault(r["user_id"], []).append(r)
    for lst in by_user.values():
        lst.sort(key=lambda p: p["_dt"])

    dates = []
    cur = d0
    while cur <= d1:
        dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    rows = []
    for e in sorted(emps, key=lambda x: (x.get("name") or "")):
        _ov = e.get("attendance_policy_override") or {}
        _sh = _shifts_by_id.get(_ov.get("shift_id")) or {}
        _shift_start = _sh.get("start") or e.get("shift_start")
        _shift_end = _sh.get("end") or e.get("shift_end")
        ps = by_user.get(e["user_id"], [])
        consumed: set = set()
        # Chronological shift pairing: an IN owns the first un-consumed OUT
        # within the next 24h — even if the OUT lands on the NEXT date
        # (night shift). Process day f-1 first so its next-morning OUT
        # doesn't get misattributed to the first requested day.
        day_pairs: Dict[str, dict] = {}
        for d in [f_minus] + dates:
            first_in = next(
                (p for p in ps
                 if p["date"] == d and p.get("kind") == "in"
                 and p["record_id"] not in consumed),
                None,
            )
            out_rec = None
            if first_in:
                consumed.add(first_in["record_id"])
                limit = first_in["_dt"] + timedelta(hours=24)
                out_rec = next(
                    (p for p in ps
                     if p.get("kind") == "out"
                     and p["record_id"] not in consumed
                     and p["_dt"] > first_in["_dt"] and p["_dt"] <= limit),
                    None,
                )
                if out_rec:
                    consumed.add(out_rec["record_id"])
            else:
                # Orphan OUT (no IN that day and not owned by a previous IN)
                outs = [p for p in ps
                        if p["date"] == d and p.get("kind") == "out"
                        and p["record_id"] not in consumed]
                if outs:
                    out_rec = outs[-1]
                    consumed.add(out_rec["record_id"])
            # Iter 210 — SECOND pair = OT window (e.g. duty 08:00-20:00 then
            # OT-In 20:07 → OT-Out 07:59 next morning). Surfaced as its own
            # OT In / OT Out columns on the Punch Approvals tables.
            # Iter 212 — OT only applies to MORNING-shift employees (first
            # punch before 12:00). Evening/night first punches get no OT
            # pair (user rule).
            ot_in_rec = ot_out_rec = None
            if first_in and out_rec and first_in["_dt"].hour < 12:
                ot_in_rec = next(
                    (p for p in ps
                     if p["date"] == d and p.get("kind") == "in"
                     and p["record_id"] not in consumed
                     and p["_dt"] > out_rec["_dt"]),
                    None,
                )
                if ot_in_rec:
                    consumed.add(ot_in_rec["record_id"])
                    limit2 = ot_in_rec["_dt"] + timedelta(hours=24)
                    ot_out_rec = next(
                        (p for p in ps
                         if p.get("kind") == "out"
                         and p["record_id"] not in consumed
                         and p["_dt"] > ot_in_rec["_dt"] and p["_dt"] <= limit2),
                        None,
                    )
                    if ot_out_rec:
                        consumed.add(ot_out_rec["record_id"])
                else:
                    # Iter 211 — OT-Out WITHOUT an OT-In (employee forgot
                    # the OT-In punch): a second un-consumed OUT later the
                    # same day surfaces as a one-sided OT pair so the admin
                    # can fill the missing OT-In from Punch Approvals.
                    ot_out_rec = next(
                        (p for p in ps
                         if p["date"] == d and p.get("kind") == "out"
                         and p["record_id"] not in consumed
                         and p["_dt"] > out_rec["_dt"]),
                        None,
                    )
                    if ot_out_rec:
                        consumed.add(ot_out_rec["record_id"])
            day_pairs[d] = {"in": first_in, "out": out_rec,
                            "ot_in": ot_in_rec, "ot_out": ot_out_rec}
        for d in dates:
            pr = day_pairs.get(d) or {}
            first_in, out_rec = pr.get("in"), pr.get("out")
            edited_any = bool(
                (first_in and first_in.get("edited_at")) or
                (out_rec and out_rec.get("edited_at"))
            )
            rows.append({
                "key": f"{e['user_id']}|{d}",
                "user_id": e["user_id"],
                "date": d,
                "name": e.get("name"),
                "father_name": e.get("father_name"),
                "designation": e.get("designation"),
                "employee_code": e.get("employee_code"),
                "in": _cell(first_in),
                "out": _cell(out_rec),
                "ot_in": _cell(pr.get("ot_in")),
                "ot_out": _cell(pr.get("ot_out")),
                "updated": edited_any,
                "shift_start": _shift_start,
                "shift_end": _shift_end,
            })
    return {"rows": rows, "from_date": f, "to_date": t, "shifts": _shift_docs}


# ---------------------------------------------------------------------------
# Iter 94 — ADDITIONAL DUTY HRS / AMOUNT (Punch Approvals option).
# Admin can grant extra duty hours or a flat ₹ amount per employee per day
# (only meaningful for days where BOTH punches are complete). Extra HOURS
# flow into the monthly attendance grid (duty totals → P Days); extra
# AMOUNTS are added to "Oth.Allo" during the Actual Salary Process.
# ---------------------------------------------------------------------------
@api.get("/admin/attendance/extra-duty/{company_id}")
async def list_extra_duty(
    company_id: str,
    from_date: str = Query(...),
    to_date: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorised for this company")
    f = (from_date or "").strip()
    t = (to_date or "").strip() or f
    entries = await db.extra_duty_entries.find(
        {"company_id": company_id, "date": {"$gte": f, "$lte": t}},
        {"_id": 0},
    ).to_list(5000)
    return {"entries": entries}


@api.post("/admin/attendance/extra-duty")
async def upsert_extra_duty(
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    user_id = str(payload.get("user_id") or "").strip()
    date_s = str(payload.get("date") or "").strip()
    if not user_id or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_s):
        raise HTTPException(status_code=400, detail="user_id and date (YYYY-MM-DD) required")
    emp = await db.users.find_one(
        {"user_id": user_id, "role": "employee"},
        {"_id": 0, "user_id": 1, "company_id": 1},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and admin.get("company_id") != emp.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this employee")
    try:
        extra_hours = round(float(payload.get("extra_hours") or 0.0), 2)
        extra_amount = round(float(payload.get("extra_amount") or 0.0), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="extra_hours / extra_amount must be numbers")
    if extra_amount < 0:
        raise HTTPException(status_code=400, detail="Amount cannot be negative")
    key = {"user_id": user_id, "date": date_s}
    if extra_hours == 0 and extra_amount == 0:
        await db.extra_duty_entries.delete_one(key)
        return {"ok": True, "deleted": True}
    entry = {
        **key,
        "company_id": emp.get("company_id"),
        "extra_hours": extra_hours,
        "extra_amount": extra_amount,
        "note": str(payload.get("note") or "").strip() or None,
        "updated_by": admin["user_id"],
        "updated_at": now_iso(),
    }
    await db.extra_duty_entries.update_one(
        key, {"$set": entry, "$setOnInsert": {"entry_id": f"xd_{uuid.uuid4().hex[:10]}"}},
        upsert=True,
    )
    saved = await db.extra_duty_entries.find_one(key, {"_id": 0})
    return {"ok": True, "entry": saved}


@api.post("/admin/attendance/manual-punch")
async def create_manual_punch(
    payload: ManualPunchCreate,
    authorization: Optional[str] = Header(None),
):
    """Insert a back-dated IN / OUT punch for an employee. The punch is
    auto-approved (`status=approved`) with source=`manual_admin` so
    payroll picks it up immediately.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A short reason is required for audit.")
    emp = await db.users.find_one(
        {"user_id": payload.user_id},
        {"_id": 0, "user_id": 1, "company_id": 1, "role": 1, "name": 1},
    )
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Employee not in your company")

    when = _parse_manual_at(payload.at)
    _enforce_lookback(admin, when)

    record_id = f"att_{uuid.uuid4().hex[:12]}"
    record = {
        "record_id": record_id,
        "user_id": payload.user_id,
        "company_id": emp.get("company_id"),
        "date": when.strftime("%Y-%m-%d"),
        "kind": payload.kind,
        "at": when.isoformat().replace("+00:00", "Z"),
        "source": "manual_admin",
        "status": "approved",
        "approved_by": admin["user_id"],
        "manual_reason": reason,
        "created_by": admin["user_id"],
        "created_at": now_iso(),
    }
    await db.attendance.insert_one(record)
    await _log_punch_audit("create", admin, record_id, None, record, reason)
    # Iter 145 — web-push the manual punch approval to the employee.
    try:
        from routes.web_push import push_to_user
        _k = "IN" if payload.kind == "in" else "OUT"
        await push_to_user(
            payload.user_id, f"Punch {_k} added by employer",
            f"A Punch {_k} was recorded for you on {record['date']} ({reason}).",
            url="/attendance", tag=f"punch_{record_id}")
    except Exception:
        pass
    return {"ok": True, "record": {k: v for k, v in record.items() if k != "_id"}}


@api.patch("/admin/attendance/{record_id}")
async def edit_attendance_record(
    record_id: str,
    payload: ManualPunchEdit,
    authorization: Optional[str] = Header(None),
):
    """Edit an existing attendance record's time and/or kind. Reason is
    mandatory for audit."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A short reason is required for audit.")
    rec = await db.attendance.find_one({"record_id": record_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Punch not found")
    if admin["role"] == "company_admin" and rec.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this punch")

    # Guard the ORIGINAL date against lookback for company_admin
    try:
        orig_when = datetime.fromisoformat((rec.get("at") or "").replace("Z", "+00:00"))
        if orig_when.tzinfo is None:
            orig_when = orig_when.replace(tzinfo=timezone.utc)
    except Exception:
        orig_when = datetime.now(timezone.utc)
    _enforce_lookback(admin, orig_when)

    updates: dict = {
        "edited_by": admin["user_id"],
        "edited_at": now_iso(),
        "edit_reason": reason,
        # Iter 94 — per user request, punch edits made by a Company or
        # Super Admin are DIRECTLY linked to Employee Attendance In/Out.
        # The editing admin IS the approver, so the record stays approved
        # and flows straight into the Attendance Report / payroll. Full
        # audit trail retained via attendance_audit_log + edited_* fields.
        "status": "approved",
        "decision_by": admin["user_id"],
        "decision_at": now_iso(),
        "decision_reason": f"Edited by {admin.get('role')}: {reason}",
    }
    if payload.at:
        new_when = _parse_manual_at(payload.at)
        _enforce_lookback(admin, new_when)
        updates["at"] = new_when.isoformat().replace("+00:00", "Z")
        updates["date"] = new_when.strftime("%Y-%m-%d")
        # Preserve original ISO for audit trail
        if not rec.get("original_at"):
            updates["original_at"] = rec.get("at")
    if payload.kind:
        updates["kind"] = payload.kind

    r = await db.attendance.update_one({"record_id": record_id}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Punch disappeared during update")
    new_rec = await db.attendance.find_one(
        {"record_id": record_id}, {"_id": 0, "selfie_base64": 0}
    )
    await _log_punch_audit("edit", admin, record_id, rec, new_rec, reason)
    return {"ok": True, "record": new_rec}


@api.delete("/admin/attendance/{record_id}")
async def delete_attendance_record(
    record_id: str,
    reason: str = Query(..., min_length=1, description="Audit reason (required)"),
    authorization: Optional[str] = Header(None),
):
    """Hard-delete an attendance record. Restricted to 90-day lookback for
    company_admin. Original row is captured in the audit log."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A short reason is required for audit.")
    rec = await db.attendance.find_one({"record_id": record_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Punch not found")
    if admin["role"] == "company_admin" and rec.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this punch")
    try:
        orig_when = datetime.fromisoformat((rec.get("at") or "").replace("Z", "+00:00"))
        if orig_when.tzinfo is None:
            orig_when = orig_when.replace(tzinfo=timezone.utc)
    except Exception:
        orig_when = datetime.now(timezone.utc)
    _enforce_lookback(admin, orig_when)

    await db.attendance.delete_one({"record_id": record_id})
    await _log_punch_audit("delete", admin, record_id, rec, None, reason)
    return {"ok": True, "deleted_record_id": record_id}


@api.get("/admin/attendance/manual-log/{company_id}")
async def manual_punch_log(
    company_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 113 — quick log of admin-created Individual/Manual punches
    (source=manual_admin) for the Punch Approvals review panel, enriched
    with employee + creating-admin names so each entry can be audited or
    undone (DELETE /admin/attendance/{record_id})."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="You can only view your own firm")
    if admin["role"] == "sub_admin" and not sub_admin_can_touch_company(admin, company_id):
        raise HTTPException(status_code=403, detail="Firm not in your scope")
    q: dict = {"company_id": company_id, "source": "manual_admin"}
    if from_date or to_date:
        rng: dict = {}
        if from_date:
            rng["$gte"] = from_date
        if to_date:
            rng["$lte"] = to_date
        q["date"] = rng
    recs = await db.attendance.find(
        q,
        {"_id": 0, "record_id": 1, "user_id": 1, "date": 1, "kind": 1,
         "at": 1, "manual_reason": 1, "created_by": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(300)
    uids = {r["user_id"] for r in recs} | {r.get("created_by") for r in recs if r.get("created_by")}
    names: Dict[str, dict] = {}
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": list(uids)}},
            {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1},
        ):
            names[u["user_id"]] = u
    for r in recs:
        emp = names.get(r["user_id"]) or {}
        r["employee_name"] = emp.get("name") or r["user_id"]
        r["employee_code"] = emp.get("employee_code")
        r["created_by_name"] = (names.get(r.get("created_by") or "") or {}).get("name")
        r["hhmm"] = (r.get("at") or "")[11:16]
    return {"records": recs, "count": len(recs)}


@api.get("/admin/attendance/{record_id}/audit")
async def get_attendance_audit(
    record_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return the audit trail for a single attendance record. Company
    admins are scoped to their own company via the current record's
    company_id (or via any historical audit row that references it)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    # Attempt to fetch the current record (may be deleted — that's fine)
    rec = await db.attendance.find_one({"record_id": record_id}, {"_id": 0})
    if rec and admin["role"] == "company_admin":
        if rec.get("company_id") != admin.get("company_id"):
            raise HTTPException(status_code=403, detail="Not authorised for this punch")
    rows = await db.attendance_audit_log.find(
        {"record_id": record_id}, {"_id": 0}
    ).sort("at", 1).to_list(200)
    return {"record_id": record_id, "audit": rows, "record": rec}


@api.get("/admin/attendance/history")
async def list_attendance_history(
    user_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD (inclusive)"),
    limit: int = Query(500, ge=1, le=2000),
    authorization: Optional[str] = Header(None),
):
    """Admin-facing history search used by the Back-date Punch editor.
    Company admins are always scoped to their own company."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    q: dict = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif company_id:
        q["company_id"] = company_id
    if user_id:
        q["user_id"] = user_id
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["date"] = rng
    rows = await db.attendance.find(
        q, {"_id": 0, "selfie_base64": 0}
    ).sort("at", -1).to_list(limit)
    return {"records": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Monthly payroll email reports (attendance / salary / combined)
# ---------------------------------------------------------------------------
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
        {"_id": 0, "name": 1},
    ):
        nm = (m.get("name") or "").strip().upper()
        if nm and nm not in have:
            cnt = await db.users.count_documents({
                "company_id": target_cid,
                "role": "employee",
                "employee_group": {"$regex": f"^{re.escape(nm)}$", "$options": "i"},
            })
            groups.append({"name": nm, "member_count": cnt, "company_id": target_cid})
            have.add(nm)
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
# ---------------------------------------------------------------------------
class SalaryRunCreate(BaseModel):
    """Body for POST /api/admin/salary-runs.

    * ``month`` — YYYY-MM (e.g. "2026-06")
    * ``month_days`` — optional override; defaults to actual days in month
    * ``employee_type`` — optional filter (e.g. "Staff"). Pass "unset" for
      employees without a type. Omit or "all" for no filter.
    * ``is_onroll`` — True → only on-roll, False → only off-roll, null → both.
    * ``run_type`` — Iter 77j: "compliance" (default) or "off_roll". Off-roll
      forces ``is_onroll=False``, skips tier bonuses, and no statutory
      deductions (pure days × rate).
    * ``deductions`` — optional overrides (only ``ot_multiplier`` is honoured
      in the base process; statutory PF/ESIC/TDS are handled in the separate
      Compliance Salary Process).
    """
    month: str
    company_id: Optional[str] = None
    month_days: Optional[int] = None
    employee_type: Optional[str] = None
    is_onroll: Optional[bool] = None
    run_type: Optional[Literal["compliance", "off_roll"]] = "compliance"
    deductions: Optional[Dict[str, float]] = None


async def _compute_salary_run(
    admin: dict,
    payload: SalaryRunCreate,
) -> dict:
    """Shared compute path used by both the initial create and re-process
    endpoints. Returns the fully-computed run doc ready to be inserted /
    updated in Mongo."""
    from utils.salary_run import (
        actual_days_in_month, parse_month, compute_present_days_and_ot,
        compute_salary_row,
    )
    try:
        year, mon = parse_month(payload.month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    default_days = actual_days_in_month(year, mon)
    month_days = payload.month_days if payload.month_days else default_days
    if not (1 <= int(month_days) <= 31):
        raise HTTPException(status_code=400, detail="month_days must be 1..31")

    # ---- Scope employees ----
    q: dict = {"role": "employee"}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif payload.company_id:
        q["company_id"] = payload.company_id
    if payload.employee_type is not None:
        et = payload.employee_type.strip()
        if et.lower() == "unset":
            q["$or"] = [
                {"employee_type": {"$exists": False}},
                {"employee_type": None},
                {"employee_type": ""},
            ]
        elif et and et.lower() != "all":
            title = et.title()
            q["employee_type"] = {"$in": [title, et, et.lower(), et.upper()]}
    if payload.is_onroll is not None:
        if payload.is_onroll:
            q.setdefault("$and", []).append({
                "$or": [
                    {"is_onroll": True},
                    {"is_onroll": {"$exists": False}},
                    {"is_onroll": None},
                ]
            })
        else:
            q["is_onroll"] = False

    # Iter 77j - Off-roll runs FORCE the is_onroll=False filter regardless
    # of what the caller passed in the payload.
    run_type = (getattr(payload, "run_type", None) or "compliance").lower()
    if run_type == "off_roll":
        q["is_onroll"] = False
        if "$and" in q:
            q["$and"] = [
                clause for clause in q["$and"]
                if not (isinstance(clause, dict) and "$or" in clause and any(
                    ("is_onroll" in (sub or {})) for sub in (clause.get("$or") or [])
                ))
            ]
            if not q["$and"]:
                q.pop("$and", None)

    employees = await db.users.find(q, {"_id": 0}).to_list(2000)

    # Iter 57 — Exclude employees whose date-of-joining is AFTER the run's
    # month end. Payslips must never be generated for pre-DOJ months.
    employees = [e for e in employees if not _month_is_before_doj(e, payload.month)
                 and not _month_is_after_exit(e, payload.month)
                 and e.get("disabled") is not True]  # Iter 166/168

    # ---- Load attendance for the month once (indexed by user_id) ----
    date_from = f"{year:04d}-{mon:02d}-01"
    date_to = f"{year:04d}-{mon:02d}-{default_days:02d}"
    attendance_by_user: dict = {}
    if employees:
        user_ids = [e["user_id"] for e in employees]
        async for r in db.attendance.find(
            {
                "user_id": {"$in": user_ids},
                "date": {"$gte": date_from, "$lte": date_to},
            },
            {"_id": 0, "user_id": 1, "kind": 1, "at": 1, "date": 1},
        ):
            attendance_by_user.setdefault(r["user_id"], []).append(r)

    # ---- Load company policies (for full_day_hours / half_day_hours) ----
    company_ids = list({e.get("company_id") for e in employees if e.get("company_id")})
    company_policies: dict = {}
    if company_ids:
        async for c in db.companies.find(
            {"company_id": {"$in": company_ids}},
            {
                "_id": 0, "company_id": 1, "attendance_policy": 1, "name": 1,
                # Iter 85 — include compliance_policy so enabled_allowances
                # toggles can be applied when computing rows.
                "compliance_policy": 1,
            },
        ):
            company_policies[c["company_id"]] = c

    # Iter 142 — Firm Master OT gate → stamp firm_ot_allowed on each
    # company's attendance policy so per-day OT math can honor it.
    if company_ids:
        async for _fm in db.firm_masters.find(
            {"company_id": {"$in": company_ids}},
            {"_id": 0, "company_id": 1, "salary_process.ot_allowed": 1},
        ):
            _v = (_fm.get("salary_process") or {}).get("ot_allowed")
            if _v is not None and _fm["company_id"] in company_policies:
                _ap = dict(company_policies[_fm["company_id"]].get("attendance_policy") or {})
                _ap["firm_ot_allowed"] = bool(_v)
                company_policies[_fm["company_id"]]["attendance_policy"] = _ap

    rows = []
    # Iter 200 — Holiday Master dates per firm + per-employee Offline
    # Salary gate (users.offline_salary_enabled = False → excluded from
    # the offline/actual salary run).
    _holidays_by_cid2: Dict[str, list] = {}
    for _cid2_ in {e.get("company_id") for e in employees if e.get("company_id")}:
        _holidays_by_cid2[_cid2_] = sorted(await holiday_dates_for_company(_cid2_))
    for emp in employees:
        # Iter 200 (user request) — per-employee "Offline Salary: Yes/No":
        # excluded employees are skipped in offline/off-roll salary runs.
        if run_type == "off_roll" and emp.get("offline_salary_enabled") is False:
            continue
        emp = dict(emp)
        emp.pop("pin_hash", None)
        emp.pop("password_hash", None)
        emp.pop("temp_pin_plaintext", None)
        emp.pop("temp_password_plaintext", None)
        pol = emp.get("employee_policy") or {}
        company_doc = company_policies.get(emp.get("company_id")) or {}
        # Merge full/half day hours from the company policy so per-day OT
        # math is consistent across textile / non-textile firms.
        att_pol = company_doc.get("attendance_policy") or {}
        merged_pol = {**att_pol, **pol}  # user policy fields win
        merged_pol["_holiday_dates"] = _holidays_by_cid2.get(emp.get("company_id")) or []
        # Iter 142 — per-employee OT flag (override wins over legacy flag).
        _ov = emp.get("attendance_policy_override") or {}
        _emp_ot = _ov.get("ot_allowed", emp.get("ot_applicable"))
        if _emp_ot is not None:
            merged_pol["ot_allowed"] = bool(_emp_ot)
        att_rows = attendance_by_user.get(emp["user_id"], [])
        stats = compute_present_days_and_ot(att_rows, merged_pol)
        # Iter 77j — Off-roll simplified compute: force salary_mode=daily
        # and clear tier bonus fields so the row is a pure days × rate.
        if run_type == "off_roll":
            simple_pol = dict(merged_pol)
            simple_pol["salary_mode"] = "daily"
            for lvl in (1, 2, 3):
                simple_pol[f"salary_{lvl}"] = 0.0
                simple_pol[f"day_{lvl}"] = 999.0
            row = compute_salary_row(
                emp, simple_pol, int(month_days), stats, payload.deductions,
            )
            # Strip statutory columns that don't apply.
            row["run_type"] = "off_roll"
        else:
            row = compute_salary_row(
                emp, merged_pol, int(month_days), stats, payload.deductions,
            )
            row["run_type"] = "compliance"
        row["company_id"] = emp.get("company_id")
        row["company_name"] = company_doc.get("name")
        rows.append(row)

    totals = {
        k: round(sum(r.get(k, 0.0) or 0.0 for r in rows), 2)
        for k in ("base_pay", "bonus", "ot_pay", "gross", "advance", "total_deduction", "net")
    }

    return {
        "month": payload.month,
        "year": year,
        "month_number": mon,
        "month_days": int(month_days),
        "default_month_days": default_days,
        "company_id": q.get("company_id"),
        "employee_type": payload.employee_type,
        "is_onroll_filter": payload.is_onroll,
        "run_type": run_type,   # Iter 77j
        "deductions_cfg": payload.deductions or {},
        "employees_count": len(rows),
        "rows": rows,
        "totals": totals,
        "generated_by": admin["user_id"],
        "generated_at": now_iso(),
    }


@api.post("/admin/salary-runs")
async def create_salary_run(
    payload: SalaryRunCreate,
    authorization: Optional[str] = Header(None),
):
    """Compute + persist a new monthly salary run. Rows are computed
    server-side using each employee's policy, attendance, and the
    configured deductions.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    require_permission(admin, "salary_process:write")
    await require_employer_permission(admin, "salary_process:write", db)
    # Iter 200 (user request) — Attendance Policy "Salary Allowed" gate:
    # actual / compliance / both. Off-roll (actual) runs require "actual"
    # or "both"; compliance runs require "compliance" or "both".
    _gate_cid = getattr(payload, "company_id", None) or admin.get("company_id")
    if _gate_cid:
        _co = await db.companies.find_one(
            {"company_id": _gate_cid}, {"_id": 0, "attendance_policy.salary_allowed": 1})
        _sa = ((_co or {}).get("attendance_policy") or {}).get("salary_allowed") or "both"
        _rt = (getattr(payload, "run_type", None) or "compliance")
        if _rt == "off_roll" and _sa == "compliance":
            raise HTTPException(status_code=400, detail=(
                "Actual/Offline salary runs are not allowed for this firm — "
                "Attendance Policy → Salary Allowed is set to Compliance only."))
        if _rt != "off_roll" and _sa == "actual":
            raise HTTPException(status_code=400, detail=(
                "Compliance salary runs are not allowed for this firm — "
                "Attendance Policy → Salary Allowed is set to Actual only."))
    run = await _compute_salary_run(admin, payload)
    run["run_id"] = f"srun_{uuid.uuid4().hex[:12]}"
    await db.salary_runs.insert_one(run)
    # Iter 77n — real-time broadcast of salary-run created event.
    try:
        from utils.ws_broker import broker as _ws
        await _ws.broadcast_firm(run.get("company_id") or "", {
            "type": "salary.run.created",
            "run_id": run["run_id"],
            "month": run.get("month"),
            "run_type": run.get("run_type"),
            "employees_count": run.get("employees_count"),
        })
    except Exception:
        pass
    return {"ok": True, "run": {k: v for k, v in run.items() if k != "_id"}}


@api.get("/admin/salary-runs")
async def list_salary_runs(
    company_id: Optional[str] = Query(None),
    company_ids: Optional[List[str]] = Query(
        None, description="Cross-firm filter. Ignored for company_admin."
    ),
    month: Optional[str] = Query(None),
    fy_start_year: Optional[int] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """List salary runs with optional filters. Company admins are scoped
    to their own company. Sub-admins have super-admin-like scope."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    q: dict = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif company_ids:
        cleaned = [c for c in company_ids if c]
        if cleaned:
            q["company_id"] = {"$in": cleaned}
    elif company_id:
        q["company_id"] = company_id
    if month:
        q["month"] = month
    # Financial year filter (Apr Y → Mar Y+1)
    if fy_start_year is not None:
        y = int(fy_start_year)
        q["month"] = q.get("month") or {"$gte": f"{y}-04", "$lte": f"{y + 1}-03"}
    runs = await db.salary_runs.find(
        q,
        {
            "_id": 0,
            # Skip the heavy rows on the list view — clients fetch details
            # separately via GET /admin/salary-runs/{run_id}.
            "rows": 0,
        },
    ).sort("generated_at", -1).to_list(500)
    # Iter 85 — Enrich each run with the display names of the users who
    # generated / finalized it. This lets "Past Runs" show an audit
    # trail (date+time+admin) without extra client requests.
    uids: set = set()
    for r in runs:
        for k in ("generated_by", "finalized_by", "updated_by"):
            v = r.get(k)
            if v:
                uids.add(v)
    name_by_uid: dict = {}
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": list(uids)}},
            {"_id": 0, "user_id": 1, "name": 1, "role": 1},
        ):
            name_by_uid[u["user_id"]] = {
                "name": u.get("name") or "—",
                "role": u.get("role") or "",
            }
    for r in runs:
        for src_key, name_key, role_key in (
            ("generated_by", "generated_by_name", "generated_by_role"),
            ("finalized_by", "finalized_by_name", "finalized_by_role"),
            ("updated_by", "updated_by_name", "updated_by_role"),
        ):
            uid = r.get(src_key)
            if uid and uid in name_by_uid:
                r[name_key] = name_by_uid[uid]["name"]
                r[role_key] = name_by_uid[uid]["role"]
    return {"runs": runs}


@api.get("/admin/salary-runs/{run_id}")
async def get_salary_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    return {"run": run}


# Iter 68 — Salary Register PDF (Form 27(1)) — landscape A4 register with
# per-employee earnings + deductions, matching the reference sample the
# user uploaded (DEV KRIPA LABOUR.pdf).
@api.get("/admin/salary-runs/{run_id}/register-form27.pdf")
async def download_salary_register_pdf(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    from fastapi.responses import Response
    from utils.salary_register_pdf import build_salary_register_pdf
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    company = await db.companies.find_one({"company_id": run.get("company_id")}, {"_id": 0}) or {}
    xlsx_bytes = build_salary_register_pdf(
        company=company,
        month=run.get("month") or "",
        month_days=int(run.get("month_days") or 30),
        rows=run.get("rows") or run.get("lines") or [],
        totals=run.get("totals") or {},
        payment_date=run.get("payment_date"),
    )
    fname = f"SalaryRegister_Form27_{(company.get('name') or 'firm').replace(' ', '_')}_{run.get('month') or ''}.pdf"
    return Response(
        content=xlsx_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# Iter 68 — Salary Certificate PDF (per employee, HR / bank use).
@api.get("/admin/employees/{user_id}/salary-certificate.pdf")
async def download_salary_certificate_pdf(
    user_id: str,
    month: Optional[str] = None,
    signatory_name: Optional[str] = None,
    signatory_role: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    from fastapi.responses import Response
    from utils.salary_certificate import build_salary_certificate_pdf
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    emp = await db.users.find_one({"user_id": user_id, "role": "employee"}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and emp.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this employee")
    company = await db.companies.find_one(
        {"company_id": emp.get("company_id")}, {"_id": 0},
    ) or {}
    policy = company.get("compliance_policy") or {}
    ref_month = month or (datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m"))
    pdf_bytes = build_salary_certificate_pdf(
        employee=emp,
        company=company,
        policy=policy,
        month=ref_month,
        signatory_name=signatory_name,
        signatory_role=signatory_role,
    )
    fname = f"SalaryCertificate_{(emp.get('name') or 'employee').replace(' ', '_')}_{ref_month}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.post("/admin/salary-runs/{run_id}/reprocess")
async def reprocess_salary_run(
    run_id: str,
    payload: Optional[SalaryRunCreate] = None,
    authorization: Optional[str] = Header(None),
):
    """Re-compute an existing salary run. If a body is supplied it may
    override month_days, filters, deductions etc. Otherwise we reuse the
    previously-stored parameters."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "salary_process:write", db)
    existing = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and existing.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    if payload is None:
        payload = SalaryRunCreate(
            month=existing["month"],
            company_id=existing.get("company_id"),
            month_days=existing.get("month_days"),
            employee_type=existing.get("employee_type"),
            is_onroll=existing.get("is_onroll_filter"),
            deductions=existing.get("deductions_cfg"),
        )
    run = await _compute_salary_run(admin, payload)
    run["run_id"] = run_id
    run["reprocessed_from_at"] = existing.get("generated_at")
    await db.salary_runs.replace_one({"run_id": run_id}, run)
    # Iter 77n — broadcast reprocess event.
    try:
        from utils.ws_broker import broker as _ws
        await _ws.broadcast_firm(run.get("company_id") or "", {
            "type": "salary.run.updated",
            "run_id": run_id,
            "month": run.get("month"),
            "run_type": run.get("run_type"),
            "employees_count": run.get("employees_count"),
        })
    except Exception:
        pass
    return {"ok": True, "run": {k: v for k, v in run.items() if k != "_id"}}


def _sort_export_rows(rows: list, sort_by: Optional[str]) -> list:
    """Iter 98 — optional report sorting for salary/compliance exports.
    ``sort_by``: name | code | net | gross (net/gross sort descending)."""
    if not sort_by or not rows:
        return rows

    def _code_key(r):
        c = str(r.get("employee_code") or "").strip()
        try:
            return (0, float(c), "")
        except ValueError:
            return (1, 0.0, c.lower())

    keymap = {
        "name": lambda r: (r.get("name") or "").lower(),
        "code": _code_key,
        "net": lambda r: -float(
            r.get("net") if r.get("net") is not None else (r.get("net_pay") or 0.0)
        ),
        "gross": lambda r: -float(
            r.get("gross") if r.get("gross") is not None else (r.get("total_gross") or 0.0)
        ),
    }
    fn = keymap.get(str(sort_by).lower())
    return sorted(rows, key=fn) if fn else rows



@api.get("/admin/salary-runs/{run_id}/export.csv")
async def export_salary_run_csv(
    run_id: str,
    sort_by: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    from utils.salary_run import to_csv
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    csv_str = to_csv(_sort_export_rows(run.get("rows") or [], sort_by))
    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="SalaryRun_{run.get("month")}_{run_id}.csv"',
        },
    )


@api.get("/admin/salary-runs/{run_id}/export.xlsx")
async def export_salary_run_xlsx(
    run_id: str,
    sort_by: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 64 — native Excel export for Salary runs.

    Same columns as the CSV, plus:
      • Bold header with brand-tinted fill and frozen top row.
      • Numeric columns typed as numbers with ``#,##0.00`` format so
        Excel opens them locale-safe.
      • Auto-computed TOTAL row for every numeric column.
    """
    from utils.salary_run import CSV_COLUMNS
    from utils.report_xlsx import build_rows_xlsx
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    company_name = "S.K. Sharma & Co."
    if run.get("company_id"):
        c = await db.companies.find_one(
            {"company_id": run["company_id"]}, {"_id": 0, "name": 1}
        )
        if c and c.get("name"):
            company_name = c["name"]
    xlsx_bytes = build_rows_xlsx(
        columns=CSV_COLUMNS,
        rows=_sort_export_rows(run.get("rows") or [], sort_by),
        sheet_name="Salary Run",
        title=f"Salary Run — {company_name}",
        subtitle=f"Month: {run.get('month')} · Employees: {len(run.get('rows') or [])}",
    )
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="SalaryRun_{run.get("month")}_{run_id}.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/admin/salary-runs/{run_id}/register.pdf")
async def export_salary_register_pdf(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    from utils.salary_run import build_salary_register_pdf
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    company_name = "S.K. Sharma & Co."
    if run.get("company_id"):
        c = await db.companies.find_one({"company_id": run["company_id"]}, {"_id": 0, "name": 1})
        if c and c.get("name"):
            company_name = c["name"]
    pdf_bytes = build_salary_register_pdf(run, company_name=company_name)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="SalaryRegister_{run.get("month")}_{run_id}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/admin/salary-runs/{run_id}/payslips.pdf")
async def download_bulk_payslips_pdf(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """Combined multi-page PDF — one payslip page per employee in the run.

    Uses the same layout as the single-employee payslip so bulk downloads
    stay visually identical to what employees see in-app.
    """
    from fastapi.responses import Response
    from utils.payslip_pdf import build_bulk_payslip_pdf
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    company = await db.companies.find_one(
        {"company_id": run.get("company_id")}, {"_id": 0},
    ) or {}
    # Enrich rows with employee master data for the payslip header.
    rows = run.get("rows") or []
    uids = [r.get("user_id") for r in rows if r.get("user_id")]
    emps_map: Dict[str, Dict[str, Any]] = {}
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
             "designation": 1, "department": 1, "doj": 1,
             "uan_no": 1, "pf_no": 1, "esi_ip_no": 1, "pan_no": 1,
             "bank_name": 1, "bank_account": 1, "bank_ifsc": 1},
        ):
            emps_map[u["user_id"]] = u
    entries: List[Dict[str, Any]] = []
    for r in rows:
        emp = emps_map.get(r.get("user_id") or "") or {"name": r.get("name")}
        entries.append({"employee": emp, "row": {**r, "month_days": run.get("month_days")}})
    pdf_bytes = build_bulk_payslip_pdf(
        company=company, month=run.get("month") or "", entries=entries,
    )
    fname = (
        f"Payslips_{(company.get('name') or 'firm').replace(' ', '_')}_"
        f"{run.get('month') or ''}.pdf"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.get("/admin/salary-runs/{run_id}/payslips.zip")
async def download_bulk_payslips_zip(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """ZIP archive containing one PDF per employee.

    File naming inside the ZIP: ``<EmployeeCode>_<Name>_<Month>.pdf``.
    """
    from fastapi.responses import Response
    from utils.payslip_pdf import build_payslip_pdf
    import zipfile

    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    company = await db.companies.find_one(
        {"company_id": run.get("company_id")}, {"_id": 0},
    ) or {}

    rows = run.get("rows") or []
    uids = [r.get("user_id") for r in rows if r.get("user_id")]
    emps_map: Dict[str, Dict[str, Any]] = {}
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
             "designation": 1, "department": 1, "doj": 1,
             "uan_no": 1, "pf_no": 1, "esi_ip_no": 1, "pan_no": 1,
             "bank_name": 1, "bank_account": 1, "bank_ifsc": 1},
        ):
            emps_map[u["user_id"]] = u

    month = run.get("month") or ""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            uid = r.get("user_id")
            if not uid:
                continue
            emp = emps_map.get(uid) or {"name": r.get("name")}
            pdf_bytes = build_payslip_pdf(
                employee=emp,
                company=company,
                row={**r, "month_days": run.get("month_days")},
                month=month,
            )
            safe_code = (emp.get("employee_code") or uid).replace("/", "_")
            safe_name = (emp.get("name") or "employee").replace("/", "_").replace(" ", "_")
            zf.writestr(f"{safe_code}_{safe_name}_{month}.pdf", pdf_bytes)
    fname = (
        f"Payslips_{(company.get('name') or 'firm').replace(' ', '_')}_{month}.zip"
    )
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ---------------------------------------------------------------------------
# Iter 230 (user request) — Employee Report payslips: download or e-mail a
# payslip per employee (or for ALL employees) by firm + month, without
# needing the run_id. Resolution order: latest COMPLIANCE run for the
# month (statutory payslip), else latest ACTUAL salary run (mapped).
# ---------------------------------------------------------------------------
def _actual_row_to_payslip(r: dict, month_days: Any) -> dict:
    """Map an Actual-salary row onto the payslip-PDF field names."""
    epf = float(r.get("epf") or 0)
    esi = float(r.get("esi") or 0)
    adv = float(r.get("adv") or 0)
    tds = float(r.get("tds") or 0)
    return {
        **r,
        "month_days": month_days,
        "present_days": r.get("p_days"),
        "ot_hours": r.get("p_hours"),
        "basic": r.get("basic_salary"),
        "ot_pay": r.get("w_basic_salary"),
        "other_earning": r.get("oth_allo"),
        "gross": r.get("total_gross"),
        "pf_employee": epf,
        "esic_employee": esi,
        "tds": tds,
        "advance": adv,
        "total_deduction": epf + esi + adv + tds,
        "net": r.get("net_pay"),
    }


async def _payslip_rows_for_month(company_id: str, month: str):
    """(rows, month_days, source) for the latest processed run of a month."""
    crun = await db.compliance_salary_runs.find_one(
        {"company_id": company_id, "month": month}, {"_id": 0},
        sort=[("created_at", -1)])
    if crun and (crun.get("rows") or []):
        return (crun.get("rows") or [], crun.get("month_days"), "compliance")
    arun = await db.salary_runs.find_one(
        {"company_id": company_id, "month": month, "run_type": "actual"},
        {"_id": 0}, sort=[("created_at", -1)])
    if arun and (arun.get("rows") or []):
        rows = [_actual_row_to_payslip(r, arun.get("month_days"))
                for r in (arun.get("rows") or [])]
        return (rows, arun.get("month_days"), "actual")
    return ([], None, None)


_PAYSLIP_EMP_PROJ = {
    "_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "email": 1,
    "designation": 1, "department": 1, "doj": 1, "uan_no": 1, "pf_no": 1,
    "esi_ip_no": 1, "pan_no": 1, "bank_name": 1, "bank_account": 1,
    "bank_ifsc": 1,
}


@api.get("/admin/employee-payslip.pdf")
async def admin_employee_payslip_pdf(
    company_id: str, user_id: str, month: str,
    authorization: Optional[str] = Header(None),
):
    """Payslip PDF for ONE employee by firm + month (no run_id needed)."""
    from fastapi.responses import Response
    from utils.payslip_pdf import build_payslip_pdf
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not your firm")
    rows, month_days, src = await _payslip_rows_for_month(company_id, month)
    row = next((r for r in rows if r.get("user_id") == user_id), None)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="No processed salary found for this employee & month — "
                   "run the Salary Process first.")
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0}) or {}
    emp = await db.users.find_one({"user_id": user_id}, _PAYSLIP_EMP_PROJ) or {}
    pdf = build_payslip_pdf(
        employee=emp, company=company,
        row={**row, "month_days": month_days}, month=month)
    fn = f"Payslip_{(emp.get('employee_code') or user_id)}_{month}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@api.get("/admin/payslips-month.zip")
async def admin_payslips_month_zip(
    company_id: str, month: str,
    authorization: Optional[str] = Header(None),
):
    """ZIP of payslip PDFs for ALL employees of a firm + month."""
    import zipfile
    from fastapi.responses import Response
    from utils.payslip_pdf import build_payslip_pdf
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not your firm")
    rows, month_days, src = await _payslip_rows_for_month(company_id, month)
    if not rows:
        raise HTTPException(status_code=404,
                            detail="No processed salary run found for this month.")
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0}) or {}
    uids = [r.get("user_id") for r in rows if r.get("user_id")]
    emps: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find({"user_id": {"$in": uids}}, _PAYSLIP_EMP_PROJ):
        emps[u["user_id"]] = u
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            uid = r.get("user_id")
            if not uid:
                continue
            emp = emps.get(uid) or {"name": r.get("name")}
            pdf = build_payslip_pdf(
                employee=emp, company=company,
                row={**r, "month_days": month_days}, month=month)
            code = str(emp.get("employee_code") or uid).replace("/", "_")
            nm = str(emp.get("name") or "employee").replace("/", "_").replace(" ", "_")
            zf.writestr(f"{code}_{nm}_{month}.pdf", pdf)
    fn = f"Payslips_{(company.get('name') or 'firm').replace(' ', '_')}_{month}.zip"
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


class PayslipEmailBody(BaseModel):
    company_id: str
    month: str
    user_id: Optional[str] = None  # None → all employees in the run


@api.post("/admin/payslips/email")
async def admin_email_payslips(
    body: PayslipEmailBody,
    authorization: Optional[str] = Header(None),
):
    """E-mail payslip PDFs to employees' e-mail from the Employee Master.
    ``user_id`` set → one employee; omitted → every employee in the run."""
    import base64
    from utils.iter60_features import _send_email_with_attachment
    from utils.payslip_pdf import build_payslip_pdf
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != body.company_id:
        raise HTTPException(status_code=403, detail="Not your firm")
    rows, month_days, src = await _payslip_rows_for_month(body.company_id, body.month)
    if body.user_id:
        rows = [r for r in rows if r.get("user_id") == body.user_id]
    if not rows:
        raise HTTPException(status_code=404,
                            detail="No processed salary found for this month.")
    company = await db.companies.find_one(
        {"company_id": body.company_id}, {"_id": 0}) or {}
    uids = [r.get("user_id") for r in rows if r.get("user_id")]
    emps: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find({"user_id": {"$in": uids}}, _PAYSLIP_EMP_PROJ):
        emps[u["user_id"]] = u
    sent, no_email, failed = [], [], []
    for r in rows:
        uid = r.get("user_id")
        emp = emps.get(uid) or {}
        email = str(emp.get("email") or "").strip()
        if not email or "@" not in email:
            no_email.append(emp.get("name") or r.get("name") or uid)
            continue
        try:
            pdf = build_payslip_pdf(
                employee=emp, company=company,
                row={**r, "month_days": month_days}, month=body.month)
            res = await _send_email_with_attachment(
                to_emails=[email],
                subject=f"Payslip — {body.month} — {company.get('name') or ''}",
                text_body=(
                    f"Dear {emp.get('name') or ''},\n\n"
                    f"Please find attached your payslip for {body.month}.\n\n"
                    f"— {company.get('name') or 'S.K. Sharma & Co.'}"),
                attachments=[{
                    "filename": f"Payslip_{emp.get('employee_code') or uid}_{body.month}.pdf",
                    "content": base64.b64encode(pdf).decode(),
                }])
            (sent if res.get("delivered") else failed).append(
                emp.get("name") or uid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("payslip email to %s failed: %s", email, exc)
            failed.append(emp.get("name") or uid)
    return {"ok": True, "sent": len(sent), "no_email": no_email,
            "failed": failed, "source": src}



# ---------------------------------------------------------------------------
# Iter 77z-final — Off-Roll Simple Slip endpoints
# ---------------------------------------------------------------------------
# The Off-Roll slip is a minimal 4-field PDF for contract/temp employees
# (Name / Days / Rate / Amount) — no compliance / statutory columns.
# Available in two flavours:
#   • single-employee PDF: GET .../off-roll-slip/{user_id}
#   • bulk ZIP archive:    GET .../off-roll-slips.zip
# ---------------------------------------------------------------------------


@api.get("/admin/salary-runs/{run_id}/off-roll-slip/{user_id}")
async def download_off_roll_slip_pdf(
    run_id: str,
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return the Off-Roll Simple Slip PDF for a single employee.

    Only rows tagged ``run_type == "off_roll"`` are eligible. Company
    admins may only download slips for their own firm.
    """
    from fastapi.responses import Response
    from utils.off_roll_slip_pdf import build_off_roll_slip_pdf

    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if run.get("run_type") != "off_roll":
        raise HTTPException(
            status_code=400,
            detail="Off-Roll slips are only available for off-roll salary runs.",
        )
    row = next((r for r in (run.get("rows") or []) if r.get("user_id") == user_id), None)
    if not row:
        raise HTTPException(status_code=404, detail="Employee row not found in this run")
    company = await db.companies.find_one(
        {"company_id": run.get("company_id")}, {"_id": 0, "name": 1},
    ) or {}
    period_label = run.get("month") or ""
    pdf_bytes = build_off_roll_slip_pdf(
        company_name=company.get("name") or "Company",
        period_label=period_label,
        row=row,
    )
    safe_code = (row.get("employee_code") or user_id).replace("/", "_")
    safe_name = (row.get("name") or "employee").replace("/", "_").replace(" ", "_")
    fname = f"OffRollSlip_{safe_code}_{safe_name}_{period_label}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.get("/admin/salary-runs/{run_id}/off-roll-slips.zip")
async def download_bulk_off_roll_slips_zip(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return a ZIP archive of Off-Roll Simple Slip PDFs — one per row."""
    from fastapi.responses import Response
    from utils.off_roll_slip_pdf import build_off_roll_slip_pdf
    import zipfile

    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "salary_process:read", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if run.get("run_type") != "off_roll":
        raise HTTPException(
            status_code=400,
            detail="Off-Roll slips are only available for off-roll salary runs.",
        )
    company = await db.companies.find_one(
        {"company_id": run.get("company_id")}, {"_id": 0, "name": 1},
    ) or {}
    period_label = run.get("month") or ""
    rows = run.get("rows") or []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            if not r.get("user_id"):
                continue
            pdf_bytes = build_off_roll_slip_pdf(
                company_name=company.get("name") or "Company",
                period_label=period_label,
                row=r,
            )
            safe_code = (r.get("employee_code") or r.get("user_id")).replace("/", "_")
            safe_name = (r.get("name") or "employee").replace("/", "_").replace(" ", "_")
            zf.writestr(
                f"OffRollSlip_{safe_code}_{safe_name}_{period_label}.pdf",
                pdf_bytes,
            )
    fname = (
        f"OffRollSlips_{(company.get('name') or 'firm').replace(' ', '_')}_{period_label}.zip"
    )
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )



@api.get("/admin/reports/annual.xlsx")
async def download_annual_report_xlsx(
    fy: str = Query(..., description="Financial year e.g. 2025-26"),
    company_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Multi-sheet Annual Report XLSX for one firm and one FY.

    Sheets: Summary · Salary (per-employee) · Attendance · PF & ESIC.
    Company-admins are scoped to their own firm; super/sub-admin must
    pass ``company_id`` explicitly.
    """
    from fastapi.responses import Response
    from utils.annual_report import build_annual_report_xlsx

    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin":
        cid = admin.get("company_id")
    else:
        cid = company_id
    if not cid:
        raise HTTPException(
            status_code=400,
            detail="company_id is required — pick a firm before downloading the annual report.",
        )
    company = await db.companies.find_one({"company_id": cid}, {"_id": 0}) or {}
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    xlsx_bytes = await build_annual_report_xlsx(
        db,
        company_id=cid,
        fy=fy,
        company_name=company.get("name") or "Company",
    )
    fname = (
        f"AnnualReport_{(company.get('name') or 'firm').replace(' ', '_')}_FY{fy}.xlsx"
    )
    return Response(
        content=xlsx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@api.post("/admin/salary-runs/{run_id}/generate-payslips")
async def generate_payslips_from_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """Push a computed salary run into per-employee payslip records so the
    Employee Payslips screen picks them up. Idempotent per (user_id,
    month) — re-running replaces the previous slip for that month."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "salary_process:write", db)
    run = await db.salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    month = run["month"]
    created = 0
    skipped_pre_doj = 0
    for r in (run.get("rows") or []):
        uid = r.get("user_id")
        if not uid:
            continue
        # Iter 57 safety: never generate a payslip for a month before the
        # employee's date-of-joining, even if the row somehow slipped through
        # the compute filter.
        emp = await db.users.find_one({"user_id": uid}, {"_id": 0, "doj": 1})
        if emp and _month_is_before_doj(emp, month):
            skipped_pre_doj += 1
            continue
        # Replace any existing slip for this employee+month
        await db.payslips.delete_many({"employee_user_id": uid, "month": month})
        slip = {
            "slip_id": f"slp_{uuid.uuid4().hex[:12]}",
            "employee_user_id": uid,
            "company_id": r.get("company_id") or run.get("company_id"),
            "month": month,
            "gross": r.get("gross", 0.0),
            "deductions": r.get("total_deduction", 0.0),
            "net": r.get("net", 0.0),
            "status": "paid",
            "generated_by": admin["user_id"],
            "generated_at": now_iso(),
            "salary_run_id": run_id,
            "breakup": {
                "base_pay": r.get("base_pay"),
                "bonus": r.get("bonus"),
                "ot_pay": r.get("ot_pay"),
                "advance": r.get("advance"),
                "present_days": r.get("present_days"),
                "half_days": r.get("half_days"),
                "ot_hours": r.get("ot_hours"),
                "month_days": r.get("month_days"),
            },
        }
        await db.payslips.insert_one(slip)
        created += 1
    await db.salary_runs.update_one(
        {"run_id": run_id},
        {"$set": {"payslips_generated_at": now_iso(), "payslips_count": created}},
    )

    # Iter 61: fire payslip auto-email if the company has enabled it.
    # This is best-effort and does not block/fail the payslip generation.
    email_summary: Optional[Dict[str, Any]] = None
    try:
        email_hook = getattr(app.state, "email_payslips_for_run", None)
        if email_hook is not None:
            email_summary = await email_hook(db, run_id, dry_run=False)
    except Exception:  # noqa: BLE001
        logger.exception("Payslip auto-email hook failed")
    return {
        "ok": True,
        "payslips_count": created,
        "skipped_pre_doj": skipped_pre_doj,
        "email_summary": email_summary,
    }


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


@api.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Compliance Salary Runs (web portal) — Iteration 56
# Dedicated statutory-side payroll (PF / ESIC / PT / TDS). Runs beside
# the base salary process — completely separate persistence + payslips.
# ---------------------------------------------------------------------------
def _policy2_biometric_stats(att_rows: List[dict], policy: dict, emp_full: dict) -> dict:
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
    by_day = stitch_cross_day_ot(by_day)
    present = 0.0
    duty_min = 0.0
    for date_key, punches in by_day.items():
        try:
            wd = datetime.strptime(date_key, "%Y-%m-%d").weekday()
        except (ValueError, TypeError):
            continue
        punches = dedupe_same_machine_punches(punches, 15)
        punches = merge_out_in_bounces(punches, 60)
        if has_unpaired_punches(punches):
            continue
        s = compute_textile_day(punches, policy, emp_full, wd)
        present += float(s.get("present_days") or 0)
        duty_min += float(s.get("duty_minutes") or 0)
    return {
        "present_days": int(present),
        "half_days": 0,
        "effective_present": round(present, 2),
        "duty_hours": round(duty_min / 60.0, 2),
        "ot_hours": 0.0,
    }


class ComplianceSalaryRunCreate(BaseModel):
    """Body for POST /api/admin/compliance-salary-runs.

    * ``month`` — YYYY-MM (e.g. "2026-06")
    * ``month_days`` — optional override; defaults to actual days in month
    * ``employee_type`` — optional filter (e.g. "Staff"). Pass "unset" for
      employees without a type. Omit or "all" for no filter.
    * ``is_onroll`` — True → only on-roll, False → only off-roll, null → both.
    * ``structure_pct`` — optional company-wide salary-structure percentages
      overriding the module defaults. Recognised keys: basic, hra,
      conveyance, medical, special, others.
    * ``statutory_cfg`` — optional overrides for statutory rates. Keys:
      pf_percent_employee, pf_wage_cap, pf_percent_employer_epf,
      pf_percent_employer_eps, esic_percent_employee, esic_percent_employer,
      esic_gross_threshold, stat_wage_floor_pct.
    """
    month: str
    company_id: Optional[str] = None
    month_days: Optional[int] = None
    employee_type: Optional[str] = None
    is_onroll: Optional[bool] = None
    structure_pct: Optional[Dict[str, float]] = None
    statutory_cfg: Optional[Dict[str, float]] = None
    # Iter 101 — import Present Days + Other Deductions from the imported
    # salary sheet (file upload / Gmail attachment) instead of biometric.
    use_imported_sheet: Optional[bool] = False


async def _compute_compliance_run(
    admin: dict,
    payload: ComplianceSalaryRunCreate,
) -> dict:
    """Shared compute path for compliance salary runs. Mirrors the base
    salary run pipeline (same attendance stats + policy merge) but uses
    ``utils.compliance_salary.compute_compliance_row`` for the payroll
    line items."""
    from utils.salary_run import (
        actual_days_in_month, parse_month, compute_present_days_and_ot,
    )
    from utils.compliance_salary import compute_compliance_row
    try:
        year, mon = parse_month(payload.month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    default_days = actual_days_in_month(year, mon)
    month_days = payload.month_days if payload.month_days else default_days
    if not (1 <= int(month_days) <= 31):
        raise HTTPException(status_code=400, detail="month_days must be 1..31")

    # ---- Scope employees ----
    q: dict = {"role": "employee"}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif payload.company_id:
        q["company_id"] = payload.company_id
    if payload.employee_type is not None:
        et = payload.employee_type.strip()
        if et.lower() == "unset":
            q["$or"] = [
                {"employee_type": {"$exists": False}},
                {"employee_type": None},
                {"employee_type": ""},
            ]
        elif et and et.lower() != "all":
            title = et.title()
            q["employee_type"] = {"$in": [title, et, et.lower(), et.upper()]}
    # Iter 164 (user directive) — Compliance Salary Process is STRICTLY
    # ON-ROLL: off-roll employees are excluded from compliance runs no
    # matter what filter the caller sent. The dedicated off-roll run type
    # (Iter 77j) is the only exception.
    run_type = (getattr(payload, "run_type", None) or "compliance").lower()
    if run_type == "off_roll":
        q["is_onroll"] = False
    else:
        q.pop("is_onroll", None)
        q.setdefault("$and", []).append({
            "$or": [
                {"is_onroll": True},
                {"is_onroll": {"$exists": False}},
                {"is_onroll": None},
            ]
        })

    employees = await db.users.find(q, {"_id": 0}).to_list(2000)

    # Iter 167 — "Resigned this month" summary: capture who gets auto-
    # excluded because they resigned/exited before the run month starts,
    # so the Compliance Salary screen can show the list.
    excluded_resigned = [
        {"user_id": e.get("user_id"), "name": e.get("name"),
         "employee_code": e.get("employee_code"),
         "exit_date": str(e.get("exit_date") or e.get("resign_date") or "")[:10]}
        for e in employees if _month_is_after_exit(e, payload.month)
    ]
    excluded_resigned.sort(key=lambda x: (x.get("name") or "").lower())

    # Iter 57 — Exclude employees whose date-of-joining is AFTER the run's
    # month end. Payslips must never be generated for pre-DOJ months.
    employees = [e for e in employees if not _month_is_before_doj(e, payload.month)
                 and not _month_is_after_exit(e, payload.month)
                 and e.get("disabled") is not True]  # Iter 166/168

    # Iter 127f/g — statutory config precedence: global Standard Compliance
    # Settings < firm-specific overrides (Firm Master) < per-run cfg.
    from routes.compliance_settings import (
        get_standard_compliance_cfg,
        get_firm_statutory_overrides,
    )
    _std_cfg = await get_standard_compliance_cfg(on_date=f"{payload.month}-31")
    _firm_over = await get_firm_statutory_overrides(payload.company_id)
    effective_statutory = {**_std_cfg, **_firm_over, **(payload.statutory_cfg or {})}


    # ---- Load attendance for the month once (indexed by user_id) ----
    date_from = f"{year:04d}-{mon:02d}-01"
    date_to = f"{year:04d}-{mon:02d}-{default_days:02d}"
    attendance_by_user: dict = {}
    if employees:
        user_ids = [e["user_id"] for e in employees]
        async for r in db.attendance.find(
            {
                "user_id": {"$in": user_ids},
                "date": {"$gte": date_from, "$lte": date_to},
            },
            {"_id": 0, "user_id": 1, "kind": 1, "at": 1, "date": 1,
             "status": 1, "source": 1},
        ):
            attendance_by_user.setdefault(r["user_id"], []).append(r)

    # Iter 101 — Imported salary sheet: manual Present Days + Other
    # Deductions (uploaded file / Gmail attachment) override the biometric
    # attendance for this run.
    am_entries: dict = {}
    if payload.use_imported_sheet:
        _am_q: dict = {"month": payload.month}
        if q.get("company_id"):
            _am_q["company_id"] = q["company_id"]
        async for e in db.compliance_import_entries.find(_am_q, {"_id": 0}):
            am_entries[e["user_id"]] = e

    # Iter 216 (user request) — Compliance Present Days are FETCHED from
    # the Attendance Report grid (the exact same source the Actual Salary
    # Process uses) so the compliance run always matches the report.
    # Imported-sheet runs keep their own source.
    grid_by_user_c: Dict[str, Any] = {}
    if not payload.use_imported_sheet:
        # Iter 217 — resolve grids for EVERY firm in scope (not just the
        # payload's company_id) so super-admin runs without an explicit
        # firm filter still auto-fetch from the Attendance Report.
        for _cidg in {e.get("company_id") for e in employees if e.get("company_id")}:
            try:
                _grid_c = await _compute_monthly_grid_data(_cidg, payload.month)
                for gr in _grid_c.get("employees") or _grid_c.get("rows") or []:
                    grid_by_user_c[gr["user_id"]] = gr
            except HTTPException:
                continue

    # ---- Load company policies (for full_day_hours / half_day_hours) ----
    company_ids = list({e.get("company_id") for e in employees if e.get("company_id")})
    company_policies: dict = {}
    if company_ids:
        async for c in db.companies.find(
            {"company_id": {"$in": company_ids}},
            {
                "_id": 0, "company_id": 1, "attendance_policy": 1, "name": 1,
                # Iter 85 — include compliance_policy so enabled_allowances
                # toggles can be applied when computing rows.
                "compliance_policy": 1,
            },
        ):
            company_policies[c["company_id"]] = c

    # Iter 98 — Firm Master EPF / ESI "Applicable" flags gate the statutory
    # calculation firm-wide. When OFF (or the firm has no Firm Master
    # record), PF / ESIC are NOT calculated for that firm's employees.
    firm_stat_flags: dict = {}
    if company_ids:
        async for fm in db.firm_masters.find(
            {"company_id": {"$in": company_ids}},
            {"_id": 0, "company_id": 1, "epf": 1, "esi": 1,
             "salary_process.ot_allowed": 1, "allowances": 1, "deductions": 1},
        ):
            _fm_allow = fm.get("allowances") or {}
            _fm_ded = fm.get("deductions") or {}
            # Iter 171 (user request) — Firm Master Allowances/Deductions
            # toggles drive the Compliance Salary columns. A mask of None
            # means the firm never configured that catalog (show defaults).
            _amap = {"HRA": "hra", "CONV.": "conveyance",
                     "MEDICAL ALLOWANCES": "medical", "OTH. ALLOW.": "special",
                     "OTHER MISC.ALLOWANCE": "others"}
            allow_mask = {h for lbl, h in _amap.items() if _fm_allow.get(lbl)}
            _pf_col = bool(_fm_ded.get("PF")) or bool((fm.get("epf") or {}).get("applicable"))
            _esi_col = bool(_fm_ded.get("ESI")) or bool((fm.get("esi") or {}).get("applicable"))
            ded_mask = set()
            if _pf_col:
                ded_mask.add("pf")
            if _esi_col:
                ded_mask.add("esi")
            if _fm_ded.get("PT"):
                ded_mask.add("pt")
            if _fm_ded.get("TDS") or _fm_ded.get("I. TAX"):
                ded_mask.add("tds")
            firm_stat_flags[fm["company_id"]] = {
                "pf": bool((fm.get("epf") or {}).get("applicable")),
                "esic": bool((fm.get("esi") or {}).get("applicable")),
                "allow_mask": allow_mask if allow_mask else None,
                "ded_mask": ded_mask if any(bool(v) for v in _fm_ded.values()) else None,
            }
            # Iter 142 — Firm Master OT gate for compliance-salary rows.
            _v = (fm.get("salary_process") or {}).get("ot_allowed")
            if _v is not None and fm["company_id"] in company_policies:
                _ap = dict(company_policies[fm["company_id"]].get("attendance_policy") or {})
                _ap["firm_ot_allowed"] = bool(_v)
                company_policies[fm["company_id"]]["attendance_policy"] = _ap

    rows = []
    # Iter 200 — Holiday Master dates per firm (for holiday_present_add_ot).
    _holidays_by_cid: Dict[str, list] = {}
    for _cid_ in {e.get("company_id") for e in employees if e.get("company_id")}:
        _holidays_by_cid[_cid_] = sorted(await holiday_dates_for_company(_cid_))
    for emp in employees:
        emp = dict(emp)
        emp.pop("pin_hash", None)
        emp.pop("password_hash", None)
        emp.pop("temp_pin_plaintext", None)
        emp.pop("temp_password_plaintext", None)
        pol = emp.get("employee_policy") or {}
        company_doc = company_policies.get(emp.get("company_id")) or {}
        att_pol = company_doc.get("attendance_policy") or {}
        merged_pol = {**att_pol, **pol}
        merged_pol["_holiday_dates"] = _holidays_by_cid.get(emp.get("company_id")) or []
        # Iter 142 — per-employee OT flag (override wins over legacy flag).
        _emp_ot = (emp.get("attendance_policy_override") or {}).get(
            "ot_allowed", emp.get("ot_applicable"))
        if _emp_ot is not None:
            merged_pol["ot_allowed"] = bool(_emp_ot)
        att_rows = attendance_by_user.get(emp["user_id"], [])
        _pm_202 = (att_pol.get("policy_master") or {})
        if (att_pol.get("policy_variant") or "").strip() == "policy_2":
            # Iter 129c — Textile Policy 2: Present Days auto-synced from
            # biometrics via the grid's textile pipeline (8 hrs = 1 day).
            stats = _policy2_biometric_stats(att_rows, merged_pol, emp)
        else:
            # Iter 202 — "Count Present Day @ 8 HRS" sub-point: compliance
            # runs count 1 Present Day per 8 worked hrs (extra hrs → OT)
            # when the firm's Salary Allowed includes Compliance.
            if _pm_202.get("compliance_present_8hr") and \
                    (att_pol.get("salary_allowed") or "both") in ("compliance", "both"):
                merged_pol["_present_day_hours_override"] = 8.0
            stats = compute_present_days_and_ot(att_rows, merged_pol)
        # Iter 216 (user request) — override with the Attendance Report's
        # Present Days + OT so the Compliance Salary run always agrees
        # with the report (and the Actual process). Applies to policy_2
        # firms too.
        # Iter 219 — "Count Present Day @ 8 HRS" now ALSO direct-syncs
        # from the Attendance Report grid (same punch pipeline as the
        # report): per day, 8+ worked hrs = 1 Present Day with the extra
        # hrs → OT; the Half-Day Threshold Rule is honoured (½ day, rest
        # → OT); week-off / holiday sub-points mirror the grid compute.
        _g_c = grid_by_user_c.get(emp["user_id"])
        _c8_on = bool(_pm_202.get("compliance_present_8hr")) and \
            (att_pol.get("salary_allowed") or "both") in ("compliance", "both")
        if _g_c and _c8_on:
            _half_h8 = float(merged_pol.get("half_day_hours") or 4.0)
            _hd_rule8 = bool(_pm_202.get("halfday_threshold_rule"))
            _pd8 = 0.0
            _half8 = 0
            _duty8 = 0.0
            _ot8 = 0.0
            for _dcell in (_g_c.get("days") or {}).values():
                _dcell = _dcell or {}
                _w = float(_dcell.get("hours") or _dcell.get("raw_hours") or 0.0)
                if _w <= 0:
                    continue
                if _dcell.get("weekly_off") and _pm_202.get("weekoff_present_add_ot"):
                    _ot8 += _w
                    continue
                if _dcell.get("holiday") and _pm_202.get("holiday_present_add_ot"):
                    _pd8 += 1.0
                    _ot8 += _w
                    continue
                if _w >= 8.0:
                    _pd8 += 1.0
                    _duty8 += 8.0
                    _ot8 += _w - 8.0
                elif _hd_rule8 and _w >= _half_h8:
                    _half8 += 1
                    _duty8 += _half_h8
                    _ot8 += _w - _half_h8
                elif _hd_rule8:
                    _ot8 += _w
                else:
                    if _w >= _half_h8:
                        _half8 += 1
                    _duty8 += _w
            if merged_pol.get("ot_allowed") is False or \
                    merged_pol.get("firm_ot_allowed") is False:
                _ot8 = 0.0
            _eff8 = _pd8 + 0.5 * _half8
            stats = {
                "present_days": round(_eff8 * 2) / 2.0,
                "half_days": _half8,
                "absent_days": 0,
                "duty_hours": round(_duty8, 2),
                "ot_hours": round(_ot8, 2),
                "effective_present": _eff8,
            }
        elif _g_c and not _c8_on:
            _t_c = _g_c.get("totals") or {}
            _pd_c = _t_c.get("present_days_policy")
            if _pd_c is None:
                _pd_c = _t_c.get("total_days_computed")
            if _pd_c is not None:
                _pd_cf = float(_pd_c or 0.0)
                stats = dict(stats)
                # Iter 219 — keep half days (26.5) instead of int().
                stats["present_days"] = round(_pd_cf * 2) / 2.0
                stats["effective_present"] = _pd_cf
                stats["half_days"] = 0
                stats["duty_hours"] = float(
                    _t_c.get("duty_hours")
                    or _t_c.get("hours")
                    or stats.get("duty_hours")
                    or 0.0
                )
                stats["ot_hours"] = float(_t_c.get("ot_hours") or 0.0)
        _am = am_entries.get(emp["user_id"]) if payload.use_imported_sheet else None
        if payload.use_imported_sheet:
            # Imported sheet wins: present days from the uploaded/email
            # salary sheet (0 when the employee has no row).
            # Iter 219 — half days (e.g. 18.5) are kept, not truncated.
            _pd = float((_am or {}).get("present_days") or 0)
            _fdh = float(merged_pol.get("full_day_hours") or 8.0)
            stats = {
                "present_days": round(_pd * 2) / 2.0,
                "half_days": 0,
                "effective_present": _pd,
                "duty_hours": round(_pd * _fdh, 2),
                "ot_hours": 0.0,
            }
        _ff = firm_stat_flags.get(emp.get("company_id")) or {"pf": False, "esic": False}
        # Iter 178 — state-wise PT from the firm's compliance policy.
        _fcp = (company_doc.get("compliance_policy") or {}) if company_doc else {}
        row = compute_compliance_row(
            emp, merged_pol, int(month_days), stats,
            company_structure_pct=payload.structure_pct,
            statutory_cfg=effective_statutory,
            firm_pf_enabled=_ff["pf"],
            firm_esic_enabled=_ff["esic"],
            firm_pt={"state": _fcp.get("pt_state"), "slabs": _fcp.get("pt_slabs")},
        )
        # Iter 100 — Attendance Master "Other Deduction" (Advance/TDS etc.)
        if _am and float(_am.get("deduction_amount") or 0) > 0:
            _ded = round(float(_am.get("deduction_amount") or 0), 2)
            row["other_deduction_head"] = _am.get("deduction_head") or "Other"
            row["other_deduction"] = _ded
            row["total_deduction"] = round(float(row.get("total_deduction") or 0) + _ded, 2)
            row["net"] = round(float(row.get("net") or 0) - _ded, 2)
        row["company_id"] = emp.get("company_id")
        row["company_name"] = company_doc.get("name")
        # Iter 85 — Apply the firm's Compliance-Allowances toggles.
        # Iter 171 — ALSO honour the Firm Master Allowances catalog: when
        # the firm configured allowances there, the two masks intersect.
        # Basic is always kept (statutory floor). Any allowance head that
        # is switched OFF is zeroed out so it doesn't inflate
        # Total Gross / statutory bases.
        firm_comp_policy = company_doc.get("compliance_policy") or {}
        enabled = firm_comp_policy.get("enabled_allowances")
        _pol_set = ({str(x).lower() for x in enabled}
                    if enabled and isinstance(enabled, list) else None)
        _fm_masks = firm_stat_flags.get(emp.get("company_id")) or {}
        _fm_set = _fm_masks.get("allow_mask")
        if _pol_set is not None and _fm_set is not None:
            enabled_set = _pol_set & set(_fm_set)
        elif _pol_set is not None:
            enabled_set = _pol_set
        elif _fm_set is not None:
            enabled_set = set(_fm_set)
        else:
            enabled_set = None
        if enabled_set is not None:
            enabled_set.add("basic")  # always
            for head in ("hra", "conveyance", "medical", "special", "others"):
                if head not in enabled_set:
                    row[head] = 0.0
            # Recompute gross-derived fields to reflect the trimmed heads
            heads_sum = float(
                (row.get("basic") or 0)
                + (row.get("hra") or 0)
                + (row.get("conveyance") or 0)
                + (row.get("medical") or 0)
                + (row.get("special") or 0)
                + (row.get("others") or 0)
            )
            row["monthly_gross"] = round(heads_sum, 2)
            row["enabled_allowances"] = sorted(enabled_set)

        # Iter 171 — Firm Master DEDUCTIONS catalog drives the deduction
        # columns. PF/ESI stay governed by statutory applicability; PT and
        # TDS are zeroed (and removed from Total Ded. / added back to Net)
        # when the firm switched them OFF.
        _ded_set = _fm_masks.get("ded_mask")
        if _ded_set is not None:
            _removed = 0.0
            for _dk in ("pt", "tds"):
                if _dk not in _ded_set and float(row.get(_dk) or 0):
                    _removed += float(row[_dk])
                    row[_dk] = 0.0
            if _removed:
                row["total_deduction"] = round(
                    float(row.get("total_deduction") or 0) - _removed, 2)
                row["net"] = round(float(row.get("net") or 0) + _removed, 2)
            row["enabled_deductions"] = sorted(_ded_set)

        # Iter 85 — DOJ / Exit-date cap for Compliance Salary. Same idea
        # as Actual Salary: cap present_days at the number of days the
        # employee was actually on the rolls this month.
        try:
            doj = str(emp.get("doj") or "")
            exit_date = str(emp.get("exit_date") or "")
            month_start = f"{year:04d}-{mon:02d}-01"
            month_end = f"{year:04d}-{mon:02d}-{default_days:02d}"
            cap = int(month_days)
            if doj and month_start <= doj <= month_end:
                cap = min(cap, month_days - int(doj.split("-")[2]) + 1)
            if exit_date and month_start <= exit_date <= month_end:
                cap = min(cap, int(exit_date.split("-")[2]))
            cap = max(0, cap)
            if row.get("present_days", 0) > cap:
                row["present_days"] = cap
            row["max_p_days"] = cap
        except (ValueError, IndexError):
            row.setdefault("max_p_days", int(month_days))
        rows.append(row)

    totals = {
        k: round(sum(r.get(k, 0.0) or 0.0 for r in rows), 2)
        for k in (
            "basic", "hra", "conveyance", "medical", "special", "others",
            "monthly_gross", "gross_paid", "ot_pay",
            "pf_wages", "pf_employee", "pf_employer_epf", "pf_employer_eps", "pf_employer_total",
            "esic_wage_base", "esic_employee", "esic_employer",
            "pt", "tds",
            "total_deduction", "net",
        )
    }

    return {
        "month": payload.month,
        "year": year,
        "month_number": mon,
        "month_days": int(month_days),
        "default_month_days": default_days,
        "company_id": q.get("company_id"),
        "employee_type": payload.employee_type,
        "is_onroll_filter": payload.is_onroll,
        "structure_pct": payload.structure_pct or {},
        "statutory_cfg": payload.statutory_cfg or {},
        "employees_count": len(rows),
        "rows": rows,
        # Iter 167 — resigned staff auto-excluded from this run.
        "excluded_resigned": excluded_resigned,
        "excluded_resigned_count": len(excluded_resigned),
        "attendance_source": "imported_sheet" if payload.use_imported_sheet else "biometric",

        "totals": totals,
        "generated_by": admin["user_id"],
        "generated_at": now_iso(),
    }


async def _firm_offline_salary_enabled(company_id: Optional[str]) -> bool:
    """Iter 164 — True when the firm's Firm Master has 'Offline Salary'
    (salary_process.offline_salary) enabled. Off-roll employees are only
    allowed in such firms; everywhere else employees are always On-roll."""
    if not company_id:
        return False
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "salary_process": 1},
    )
    return bool(((fm or {}).get("salary_process") or {}).get("offline_salary"))


async def _firm_biometric_attendance_enabled(company_id: Optional[str]) -> bool:
    """Iter 165 — True when the firm's Firm Master has 'Bio Matrix
    Attendance' (salary_process.bio_matrix_attendance) enabled. Gates the
    per-employee fingerprint verification requirement."""
    if not company_id:
        return False
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "salary_process": 1},
    )
    return bool(((fm or {}).get("salary_process") or {}).get("bio_matrix_attendance"))


async def _require_firm_salary_permission(company_id: Optional[str], kind: str) -> None:
    """Iter 98 — Firm Master 'Salary Process Settings' gating.

    * ``kind='online'``  → Compliance Salary requires ``salary_process.online_salary``.
    * ``kind='offline'`` → Salary Process (Actual) requires ``salary_process.offline_salary``.

    Raises 403 "You are not permitted for this" when the flag is OFF (or the
    firm was never configured). Skipped when no single firm is in scope
    (e.g. super-admin without a company filter).
    """
    if not company_id:
        return
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "salary_process": 1},
    )
    sp = (fm or {}).get("salary_process") or {}
    allowed = sp.get("online_salary") if kind == "online" else sp.get("offline_salary")
    if not allowed:
        label = (
            "Online Salary (Compliance Salary)" if kind == "online"
            else "Offline Salary (Salary Process Actual)"
        )
        raise HTTPException(
            status_code=403,
            detail=(
                f"You are not permitted for this — {label} is not enabled for "
                "this firm. Enable it in Firm Master → Salary Process Settings."
            ),
        )


@api.post("/admin/compliance-salary-runs")
async def create_compliance_salary_run(
    payload: ComplianceSalaryRunCreate,
    authorization: Optional[str] = Header(None),
):
    """Compute + persist a new compliance salary run (PF/ESIC/PT/TDS)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    # Iter 62 — Compliance is OPT-IN for company admins. Super Admin must
    # explicitly enable compliance_salary:write on the firm's access rights.
    await require_employer_permission(admin, "compliance_salary:write", db)
    # Iter 98 — Firm Master gate: Online Salary must be enabled for the firm.
    _gate_cid = (
        admin.get("company_id") if admin["role"] == "company_admin"
        else payload.company_id
    )
    await _require_firm_salary_permission(_gate_cid, "online")
    # Iter 129f (user directive) — a FINALIZED month can never be processed
    # again. Iter 257 (user bug): the block is scoped to the SAME employee
    # group — finalizing STAFF must not stop LABOUR from being processed.
    _grp0 = (payload.employee_type or "").strip()
    _fin_q: Dict[str, Any] = {"month": payload.month, "finalized": True}
    if payload.company_id:
        _fin_q["company_id"] = payload.company_id
    _fin_q["employee_type"] = (
        {"$regex": f"^{re.escape(_grp0)}$", "$options": "i"} if _grp0
        else {"$in": [None, ""]}
    )
    if await db.compliance_salary_runs.find_one(_fin_q, {"_id": 1}):
        raise HTTPException(
            status_code=409,
            detail="This month's Compliance salary is already FINALIZED for this "
                   "employee group — it cannot be processed again. Use Unlock "
                   "Request to de-finalize first.",
        )
    run = await _compute_compliance_run(admin, payload)
    run["run_id"] = f"csrun_{uuid.uuid4().hex[:12]}"
    # Advance Management — auto-deduct active advance EMIs / single-shot
    # recoveries into the rows (idempotent per month+process).
    from routes.advances import apply_advance_recovery
    _adv_total = await apply_advance_recovery(
        payload.company_id, payload.month, "compliance", run["run_id"], run["rows"])
    if _adv_total or any(r.get("advance_recovery") for r in run["rows"]):
        t = run.get("totals") or {}
        t["advance_recovery"] = round(sum(float(r.get("advance_recovery") or 0) for r in run["rows"]), 2)
        t["total_deduction"] = round(sum(float(r.get("total_deduction") or 0) for r in run["rows"]), 2)
        t["net"] = round(sum(float(r.get("net") or 0) for r in run["rows"]), 2)
        run["totals"] = t
    # Iter 174 (user directive) — REPLACE old data: a fresh process for the
    # same firm + month + employee group deletes the previous draft run(s)
    # so only the newest data exists (finalized runs are already blocked
    # above and are never touched).
    _grp = (payload.employee_type or "").strip()
    await db.compliance_salary_runs.delete_many({
        "month": payload.month,
        "company_id": payload.company_id,
        "employee_type": (
            {"$regex": f"^{re.escape(_grp)}$", "$options": "i"} if _grp
            else {"$in": [None, ""]}
        ),
        "finalized": {"$ne": True},
    })
    await db.compliance_salary_runs.insert_one(run)
    # Iter 182 — audit trail
    from routes.salary_audit import write_salary_audit
    await write_salary_audit(admin, "process", run,
                             f"Processed {len(run.get('rows') or [])} employees")
    return {"ok": True, "run": {k: v for k, v in run.items() if k != "_id"}}


@api.get("/admin/compliance-salary-runs")
async def list_compliance_salary_runs(
    company_id: Optional[str] = Query(None),
    company_ids: Optional[List[str]] = Query(
        None, description="Cross-firm filter. Ignored for company_admin."
    ),
    month: Optional[str] = Query(None),
    fy_start_year: Optional[int] = Query(None),
    finalized_only: bool = Query(
        False, description="Iter 174 — only FINALIZED runs (Automation screens), "
                           "deduped to the newest run per firm+month+group."),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    # Iter 62 — Compliance is OPT-IN for company admins.
    await require_employer_permission(admin, "compliance_salary:read", db)
    q: dict = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif company_ids:
        cleaned = [c for c in company_ids if c]
        if cleaned:
            q["company_id"] = {"$in": cleaned}
    elif company_id:
        q["company_id"] = company_id
    if month:
        q["month"] = month
    if fy_start_year is not None:
        y = int(fy_start_year)
        q["month"] = q.get("month") or {"$gte": f"{y}-04", "$lte": f"{y + 1}-03"}
    if finalized_only:
        q["finalized"] = True
    runs = await db.compliance_salary_runs.find(
        q, {"_id": 0, "rows": 0},
    ).sort("generated_at", -1).to_list(500)
    if finalized_only:
        # Keep only the NEWEST run per firm + month + employee group so
        # replaced/reprocessed data never shows alongside the old copy.
        seen: set = set()
        deduped = []
        for r in runs:
            key = (r.get("company_id"), r.get("month"), r.get("employee_type"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
        runs = deduped
    # Iter 85 — Enrich with generator/finalizer names for audit display.
    uids: set = set()
    for r in runs:
        for k in ("generated_by", "finalized_by", "updated_by"):
            v = r.get(k)
            if v:
                uids.add(v)
    name_by_uid: dict = {}
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": list(uids)}},
            {"_id": 0, "user_id": 1, "name": 1, "role": 1},
        ):
            name_by_uid[u["user_id"]] = {
                "name": u.get("name") or "—",
                "role": u.get("role") or "",
            }
    for r in runs:
        for src_key, name_key, role_key in (
            ("generated_by", "generated_by_name", "generated_by_role"),
            ("finalized_by", "finalized_by_name", "finalized_by_role"),
            ("updated_by", "updated_by_name", "updated_by_role"),
        ):
            uid = r.get(src_key)
            if uid and uid in name_by_uid:
                r[name_key] = name_by_uid[uid]["name"]
                r[role_key] = name_by_uid[uid]["role"]
    return {"runs": runs}


@api.get("/admin/compliance-salary-runs/{run_id}")
async def get_compliance_salary_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    return {"run": run}


@api.post("/admin/compliance-salary-runs/{run_id}/save-rows")
async def save_compliance_run_rows(
    run_id: str,
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """Iter 145 — P0 fix: persist grid edits (Present Days, Others, Other
    Deduction and their recomputed row values) made in the Compliance
    Salary sheet. Previously "Save as Draft" saved NOTHING — every edit
    was client-side only and vanished when the run was reopened."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "compliance_salary:write", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if run.get("finalized"):
        raise HTTPException(status_code=400, detail="Run is finalized (read-only). Unlock it first.")

    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=400, detail="rows list is required")
    # Sanity: the incoming rows must match the run's employees (no adding /
    # dropping rows through this endpoint).
    existing_ids = {r.get("user_id") for r in (run.get("rows") or [])}
    incoming_ids = {r.get("user_id") for r in rows}
    if incoming_ids != existing_ids:
        raise HTTPException(status_code=400, detail="Row set does not match this run — reload and retry.")

    updates: Dict[str, Any] = {
        "rows": rows,
        "draft_saved_at": now_iso(),
        "draft_saved_by": admin["user_id"],
    }
    totals = payload.get("totals")
    if isinstance(totals, dict) and totals:
        updates["totals"] = totals
    await db.compliance_salary_runs.update_one({"run_id": run_id}, {"$set": updates})
    # Iter 182 — audit trail
    from routes.salary_audit import write_salary_audit
    await write_salary_audit(admin, "save_rows", run,
                             f"Saved draft edits for {len(rows)} rows")
    return {"ok": True, "draft_saved_at": updates["draft_saved_at"]}


@api.post("/admin/compliance-salary-runs/{run_id}/finalize")
async def finalize_compliance_salary_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """Iter 91 — Save/Finalize a compliance salary run. Marks the run as
    finalized (read-only): reprocessing is blocked until unfinalized."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "compliance_salary:write", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if run.get("finalized"):
        return {"ok": True, "already_finalized": True,
                "finalized_at": run.get("finalized_at")}
    stamp = {
        "finalized": True,
        "finalized_at": now_iso(),
        "finalized_by": admin["user_id"],
    }
    await db.compliance_salary_runs.update_one({"run_id": run_id}, {"$set": stamp})
    logger.info("[compliance-run] finalized run=%s by %s", run_id, admin["user_id"])
    # Iter 182 — audit trail
    from routes.salary_audit import write_salary_audit
    await write_salary_audit(admin, "finalize", run, "Run finalized (locked)")
    # Iter 103 — automated email trigger
    try:
        from routes.email_notifications import fire_email_event
        await fire_email_event("salary_finalized", company_id=run.get("company_id"),
                               details=f"Compliance Salary {run.get('month')}")
    except Exception:
        pass
    return {"ok": True, **stamp}


@api.post("/admin/compliance-salary-runs/{run_id}/unlock-request")
async def request_compliance_run_unlock(
    run_id: str,
    payload: Dict[str, Any] = Body(default={}),
    authorization: Optional[str] = Header(None),
):
    """Iter 126h — a FINALIZED run is locked for everyone. Sub admins /
    employers must raise an unlock request that the Super Admin approves
    before any change is possible. Super admin unlock is immediate."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "compliance_salary:write", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if not run.get("finalized"):
        return {"ok": True, "already_unlocked": True}
    reason = (payload.get("reason") or "").strip()
    if admin["role"] == "super_admin":
        await db.compliance_salary_runs.update_one(
            {"run_id": run_id},
            {"$set": {
                "finalized": False,
                "unlocked_at": now_iso(),
                "unlocked_by": admin["user_id"],
                "unlock_reason": reason or "Super admin unlock",
            }},
        )
        logger.info("[compliance-run] unlocked run=%s by super admin %s", run_id, admin["user_id"])
        return {"ok": True, "unlocked": True}
    dup = await db.salary_unlock_requests.find_one(
        {"run_id": run_id, "status": "pending"}, {"_id": 0, "req_id": 1})
    if dup:
        return {"ok": True, "pending": True, "req_id": dup["req_id"],
                "message": "An unlock request is already pending approval."}
    req = {
        "req_id": f"sur_{uuid.uuid4().hex[:12]}",
        "run_id": run_id,
        "run_type": "compliance",
        "company_id": run.get("company_id"),
        "month": run.get("month"),
        "reason": reason,
        "requested_by": admin["user_id"],
        "requested_by_name": admin.get("name") or admin.get("email") or "",
        "requested_by_role": admin["role"],
        "status": "pending",
        "created_at": now_iso(),
    }
    await db.salary_unlock_requests.insert_one(req)
    req.pop("_id", None)
    return {"ok": True, "pending": True, "req_id": req["req_id"],
            "message": "Unlock request sent to the Super Admin for approval."}


@api.get("/admin/salary-unlock-requests")
async def list_salary_unlock_requests(
    status: Optional[str] = None,
    run_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 126h — pending finalized-salary unlock requests. Super admin
    sees all; requesters see their own (to show 'pending' state)."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if run_id:
        q["run_id"] = run_id
    if admin["role"] != "super_admin":
        q["requested_by"] = admin["user_id"]
    rows = await db.salary_unlock_requests.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(200)
    return {"requests": rows}


@api.post("/admin/salary-unlock-requests/{req_id}/decide")
async def decide_salary_unlock_request(
    req_id: str,
    payload: Dict[str, Any] = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Iter 126h — Super Admin (only) approves/rejects an unlock request.
    Approval unfinalizes the run so changes become possible again."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    req = await db.salary_unlock_requests.find_one({"req_id": req_id}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Unlock request not found")
    if req.get("status") != "pending":
        raise HTTPException(status_code=409, detail="Request already decided")
    approve = bool(payload.get("approve"))
    note = (payload.get("note") or "").strip()
    await db.salary_unlock_requests.update_one(
        {"req_id": req_id},
        {"$set": {
            "status": "approved" if approve else "rejected",
            "decided_by": admin["user_id"],
            "decided_at": now_iso(),
            "decision_note": note,
        }},
    )
    if approve:
        await db.compliance_salary_runs.update_one(
            {"run_id": req["run_id"]},
            {"$set": {
                "finalized": False,
                "unlocked_at": now_iso(),
                "unlocked_by": admin["user_id"],
                "unlock_reason": req.get("reason") or "Approved unlock request",
            }},
        )
        logger.info("[compliance-run] unlock APPROVED run=%s req=%s", req["run_id"], req_id)
        # Iter 182 — audit trail
        from routes.salary_audit import write_salary_audit
        run_doc = await db.compliance_salary_runs.find_one(
            {"run_id": req["run_id"]}, {"_id": 0, "run_id": 1, "company_id": 1,
                                        "company_name": 1, "month": 1})
        await write_salary_audit(admin, "unlock", run_doc or {"run_id": req["run_id"]},
                                 f"Unlock approved — {note or 'no note'}")
    return {"ok": True, "approved": approve}


@api.post("/admin/compliance-salary-runs/{run_id}/reprocess")
async def reprocess_compliance_salary_run(
    run_id: str,
    payload: Optional[ComplianceSalaryRunCreate] = None,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:write", db)
    existing = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and existing.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    if existing.get("finalized"):
        raise HTTPException(
            status_code=409,
            detail="Run is finalized and read-only. Unfinalize it first to reprocess.",
        )
    # Iter 98 — Firm Master gate: Online Salary must be enabled for the firm.
    await _require_firm_salary_permission(existing.get("company_id"), "online")

    if payload is None:
        payload = ComplianceSalaryRunCreate(
            month=existing["month"],
            company_id=existing.get("company_id"),
            month_days=existing.get("month_days"),
            employee_type=existing.get("employee_type"),
            is_onroll=existing.get("is_onroll_filter"),
            structure_pct=existing.get("structure_pct"),
            statutory_cfg=existing.get("statutory_cfg"),
        )
    run = await _compute_compliance_run(admin, payload)
    run["run_id"] = run_id
    run["reprocessed_from_at"] = existing.get("generated_at")
    # Advance Management — re-apply (idempotent) advance deductions so the
    # reprocessed sheet still shows the recovery lines.
    from routes.advances import apply_advance_recovery
    _adv_total = await apply_advance_recovery(
        existing.get("company_id"), existing["month"], "compliance", run_id, run["rows"])
    if _adv_total or any(r.get("advance_recovery") for r in run["rows"]):
        t = run.get("totals") or {}
        t["advance_recovery"] = round(sum(float(r.get("advance_recovery") or 0) for r in run["rows"]), 2)
        t["total_deduction"] = round(sum(float(r.get("total_deduction") or 0) for r in run["rows"]), 2)
        t["net"] = round(sum(float(r.get("net") or 0) for r in run["rows"]), 2)
        run["totals"] = t
    await db.compliance_salary_runs.replace_one({"run_id": run_id}, run)
    return {"ok": True, "run": {k: v for k, v in run.items() if k != "_id"}}


@api.get("/admin/compliance-salary-runs/{run_id}/export.csv")
async def export_compliance_salary_run_csv(
    run_id: str,
    sort_by: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    from utils.compliance_salary import to_csv
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    csv_str = to_csv(_sort_export_rows(run.get("rows") or [], sort_by))
    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="ComplianceSalary_{run.get("month")}_{run_id}.csv"',
        },
    )


@api.get("/admin/compliance-salary-runs/{run_id}/export.xlsx")
async def export_compliance_salary_run_xlsx(
    run_id: str,
    sort_by: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 64 — native Excel export for Compliance Salary runs."""
    from utils.compliance_salary import CSV_COLUMNS
    from utils.report_xlsx import build_rows_xlsx
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")
    company_name = "S.K. Sharma & Co."
    if run.get("company_id"):
        c = await db.companies.find_one(
            {"company_id": run["company_id"]}, {"_id": 0, "name": 1}
        )
        if c and c.get("name"):
            company_name = c["name"]
    xlsx_bytes = build_rows_xlsx(
        columns=CSV_COLUMNS,
        rows=_sort_export_rows(run.get("rows") or [], sort_by),
        sheet_name="Compliance",
        title=f"Compliance Salary — {company_name}",
        subtitle=f"Month: {run.get('month')} · Employees: {len(run.get('rows') or [])}",
    )
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="ComplianceSalary_{run.get("month")}_{run_id}.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/admin/compliance-salary-runs/{run_id}/register.pdf")
async def export_compliance_salary_register_pdf(
    run_id: str,
    variant: int = 1,
    authorization: Optional[str] = Header(None),
):
    from utils.compliance_salary import (
        build_compliance_register_pdf,
        build_compliance_register_pdf_v2,
    )
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    company_name = "S.K. Sharma & Co."
    firm_info: Dict[str, Any] = {}
    if run.get("company_id"):
        c = await db.companies.find_one(
            {"company_id": run["company_id"]}, {"_id": 0, "name": 1, "address": 1},
        )
        if c and c.get("name"):
            company_name = c["name"]
        fm = await db.firm_masters.find_one(
            {"company_id": run["company_id"]},
            {"_id": 0, "epf": 1, "esi": 1, "registered_address": 1},
        )
        # Iter 137 (user directive) — the register shows the firm's
        # REGISTERED address from the Firm Master, NOT the geofence
        # office address. Falls back to the company address only when
        # no registered address has been filled in.
        ra = (fm or {}).get("registered_address") or {}
        reg_addr = ", ".join(str(x).strip() for x in [
            ra.get("address1"), ra.get("address2"), ra.get("city"),
            ra.get("state"), ra.get("pin_code"),
        ] if x and str(x).strip())
        firm_info["address"] = reg_addr or ((c or {}).get("address") or "")
        firm_info["pf_code"] = ((fm or {}).get("epf") or {}).get("epf_no") or ""
        firm_info["esi_code"] = ((fm or {}).get("esi") or {}).get("esi_no") or ""
    builder = build_compliance_register_pdf_v2 if int(variant or 1) == 2 else build_compliance_register_pdf
    if int(variant or 1) == 2:
        # Iter 162 — apply the ONE-TIME saved register layout (columns /
        # order / headings / widths / rows-per-page / row height).
        _lay = await db.app_settings.find_one(
            {"key": "compliance_register_layout"}, {"_id": 0, "layout": 1})
        pdf_bytes = builder(run, company_name=company_name, firm=firm_info,
                            layout=(_lay or {}).get("layout"))
    else:
        pdf_bytes = builder(run, company_name=company_name, firm=firm_info)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="ComplianceSalaryRegister_{run.get("month")}_{run_id}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/admin/compliance-salary-runs/{run_id}/pf-ecr.txt")
async def download_pf_ecr(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """PF ECR (Electronic Challan cum Return) text file for one month.

    Layout (hash-separated, no header): ``UAN#NAME#GROSS#EPF_WAGES#
    EPS_WAGES#EDLI_WAGES#EPF_CONTRIB#EPS_CONTRIB#EPF_EPS_DIFF#NCP#REFUND``.
    Uploaded on the EPFO Unified Portal ▸ ECR & Return.
    """
    from fastapi.responses import Response
    from utils.statutory_bulk import build_pf_ecr_txt
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    rows = run.get("rows") or run.get("lines") or []
    # Enrich with user master fields (UAN) if not already on the row.
    uids = [r.get("user_id") for r in rows if r.get("user_id") and not r.get("uan_no")]
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "uan_no": 1},
        ):
            for r in rows:
                if r.get("user_id") == u["user_id"]:
                    r["uan_no"] = u.get("uan_no")
    body = build_pf_ecr_txt(rows)
    fname = f"PF_ECR_{run.get('month')}.txt"
    return Response(
        content=body,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/admin/compliance-salary-runs/{run_id}/esic-mc.csv")
async def download_esic_mc(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """ESIC Monthly Contribution CSV for the ESIC Insurance Portal."""
    from fastapi.responses import Response
    from utils.statutory_bulk import build_esic_mc_csv
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    rows = run.get("rows") or run.get("lines") or []
    uids = [r.get("user_id") for r in rows if r.get("user_id") and not r.get("esi_ip_no")]
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "esi_ip_no": 1},
        ):
            for r in rows:
                if r.get("user_id") == u["user_id"]:
                    r["esi_ip_no"] = u.get("esi_ip_no")
    body = build_esic_mc_csv(rows)
    fname = f"ESIC_MC_{run.get('month')}.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/admin/compliance-salary-runs/{run_id}/esic-ip-reg.csv")
async def download_esic_ip_reg(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """ESIC Insured-Person Registration CSV (only new joiners).

    Includes only employees that DO NOT yet have an ``esi_ip_no`` in
    the master.  Once the portal returns an IP number for each row the
    operator should update the employee master so the row falls off
    subsequent monthly files.
    """
    from fastapi.responses import Response
    from utils.statutory_bulk import build_esic_ip_reg_csv
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    rows = run.get("rows") or run.get("lines") or []
    # Enrich with the full employee master so we have DOB, addresses, PAN…
    uids = [r.get("user_id") for r in rows if r.get("user_id")]
    if uids:
        async for u in db.users.find(
            {"user_id": {"$in": uids}},
            {"_id": 0, "user_id": 1, "esi_ip_no": 1, "dob": 1, "doj": 1,
             "gender": 1, "father_name": 1, "aadhaar_no": 1, "pan_no": 1,
             "phone": 1, "address": 1, "permanent_address": 1,
             "bank_ifsc": 1, "marital_status": 1},
        ):
            for r in rows:
                if r.get("user_id") == u["user_id"]:
                    for k, v in u.items():
                        r.setdefault(k, v)
    body = build_esic_ip_reg_csv(rows)
    fname = f"ESIC_IP_Registration_{run.get('month')}.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
        },
    )


@api.post("/admin/compliance-salary-runs/{run_id}/generate-payslips")
async def generate_compliance_payslips_from_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """Push a compliance run into per-employee compliance-payslip records.
    Stored separately (kind='compliance') so the base + compliance payslips
    don't collide."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    await require_employer_permission(admin, "compliance_salary:write", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised for this run")

    month = run["month"]
    created = 0
    skipped_pre_doj = 0
    for r in (run.get("rows") or []):
        uid = r.get("user_id")
        if not uid:
            continue
        # Iter 57 — never generate a compliance payslip for a month before DOJ.
        emp = await db.users.find_one({"user_id": uid}, {"_id": 0, "doj": 1})
        if emp and _month_is_before_doj(emp, month):
            skipped_pre_doj += 1
            continue
        # Replace existing compliance slip for this employee+month
        await db.payslips.delete_many({
            "employee_user_id": uid, "month": month, "kind": "compliance",
        })
        slip = {
            "slip_id": f"cslp_{uuid.uuid4().hex[:12]}",
            "kind": "compliance",
            "employee_user_id": uid,
            "company_id": r.get("company_id") or run.get("company_id"),
            "month": month,
            "gross": r.get("gross_paid", 0.0),
            "deductions": r.get("total_deduction", 0.0),
            "net": r.get("net", 0.0),
            "status": "paid",
            "generated_by": admin["user_id"],
            "generated_at": now_iso(),
            "compliance_salary_run_id": run_id,
            "breakup": {
                "basic": r.get("basic"),
                "hra": r.get("hra"),
                "conveyance": r.get("conveyance"),
                "medical": r.get("medical"),
                "special": r.get("special"),
                "others": r.get("others"),
                "ot_pay": r.get("ot_pay"),
                "stat_wage_base": r.get("stat_wage_base"),
                "pf_wages": r.get("pf_wages"),
                "pf_employee": r.get("pf_employee"),
                "pf_employer_total": r.get("pf_employer_total"),
                "esic_wage_base": r.get("esic_wage_base"),
                "esic_employee": r.get("esic_employee"),
                "esic_employer": r.get("esic_employer"),
                "pt_state": r.get("pt_state"),
                "pt": r.get("pt"),
                "tds": r.get("tds"),
                "present_days": r.get("present_days"),
                "half_days": r.get("half_days"),
                "month_days": r.get("month_days"),
            },
        }
        await db.payslips.insert_one(slip)
        created += 1
    await db.compliance_salary_runs.update_one(
        {"run_id": run_id},
        {"$set": {"payslips_generated_at": now_iso(), "payslips_count": created}},
    )
    return {"ok": True, "payslips_count": created, "skipped_pre_doj": skipped_pre_doj}


# ---------------------------------------------------------------------------
# Sub-admins (delegated super-admin accounts) — Iter 57
# ---------------------------------------------------------------------------
# A super_admin can create sub_admin accounts to delegate portions of the
# Super Admin portal. Sub-admins log in with the same email + password
# (or phone + password) flow as company admins. On login they receive
# `role: "sub_admin"` and their configured permission list + company scope.
# The frontend uses these to build the filtered nav and gate routes.

class SubAdminCreate(BaseModel):
    """Super admin creates a sub-admin. Password is set at creation and
    must be shared with the sub-admin out-of-band (or via the temp-cred flow)."""
    name: str
    email: str
    phone: Optional[str] = None
    password: str
    pin: Optional[str] = None  # Iter 220 — optional separate 6-digit login PIN
    permissions: List[str] = []
    company_scope: Literal["all", "restricted"] = "all"
    company_ids: List[str] = []  # only used when scope=="restricted"
    menu_rights: dict = {}  # Iter 93 — {route: bool}; missing == allowed


class SubAdminUpdate(BaseModel):
    """Any field left as None is unchanged. To change password use the
    dedicated reset endpoint below."""
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    pin: Optional[str] = None  # Iter 220 — set/replace the 6-digit login PIN
    permissions: Optional[List[str]] = None
    company_scope: Optional[Literal["all", "restricted"]] = None
    company_ids: Optional[List[str]] = None
    disabled: Optional[bool] = None
    # Iter 93 — per-sidebar-button visibility {route: bool}; missing == allowed
    menu_rights: Optional[dict] = None


def _validate_sub_admin_permissions(perms: List[str]) -> List[str]:
    """Filter & de-dupe against the known permission keys."""
    if not perms:
        return []
    known = set(SUB_ADMIN_PERMISSION_KEYS)
    return sorted({p for p in perms if p in known})


def _clean_mobile_or_400(raw: Optional[str]) -> Optional[str]:
    """Iter 220 — Mobile-field hygiene: reject emails typed/saved into the
    Mobile No. box and keep only phone characters."""
    p = (raw or "").strip()
    if not p:
        return None
    if "@" in p:
        raise HTTPException(
            status_code=400,
            detail="Mobile No. cannot be an email id — enter a phone number "
                   "(the email goes in the Email field).",
        )
    cleaned = re.sub(r"[^\d+]", "", p)
    if len(re.sub(r"[^\d]", "", cleaned)) < 10:
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit mobile number")
    return cleaned


def _validate_pin_or_400(raw: Optional[str]) -> Optional[str]:
    """Iter 220 — 6-digit PIN validation (returns the clean PIN or None)."""
    p = (raw or "").strip()
    if not p:
        return None
    if not re.fullmatch(r"\d{6}", p):
        raise HTTPException(status_code=400, detail="PIN must be exactly 6 digits")
    return p


def _sanitise_sub_admin(doc: dict) -> dict:
    """Strip sensitive fields before returning a sub-admin to the client."""
    if not doc:
        return doc
    out = {k: v for k, v in doc.items() if k not in (
        "password_hash", "pin_hash",
        "temp_pin_plaintext", "temp_password_plaintext",
    )}
    return out


@api.get("/admin/sub-admin-permission-keys")
async def sub_admin_permission_keys(
    authorization: Optional[str] = Header(None),
):
    """Return the canonical permission-key list so the frontend can render
    checkboxes without hardcoding the list."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    return {"permissions": SUB_ADMIN_PERMISSION_KEYS}


@api.get("/admin/sub-admins")
async def list_sub_admins(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    docs = await db.users.find(
        {"role": "sub_admin"},
        {"_id": 0},
    ).sort("created_at", -1).to_list(500)
    return {"sub_admins": [_sanitise_sub_admin(d) for d in docs]}


@api.post("/admin/sub-admins")
async def create_sub_admin(
    payload: SubAdminCreate,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    name = (payload.name or "").strip()
    email = (payload.email or "").strip().lower()
    phone = _clean_mobile_or_400(payload.phone)
    pin = _validate_pin_or_400(payload.pin)
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required for login")
    if not payload.password or len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    # Uniqueness — reuse the same rules as normal users.
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail=f"A user with email {email} already exists")
    if phone and await db.users.find_one({"phone_e164": phone}):
        raise HTTPException(status_code=409, detail=f"A user with phone {phone} already exists")

    perms = _validate_sub_admin_permissions(payload.permissions or [])
    scope = payload.company_scope or "all"
    company_ids: List[str] = []
    if scope == "restricted":
        company_ids = [c for c in (payload.company_ids or []) if c]
        if not company_ids:
            raise HTTPException(
                status_code=400,
                detail="Restricted scope needs at least one company_id",
            )

    user_id = f"sub_{uuid.uuid4().hex[:12]}"
    doc = {
        "user_id": user_id,
        "role": "sub_admin",
        "name": name,
        "email": email,
        "phone_e164": phone,
        # Iter 220 — mirror into ``phone`` (normalized) so phone + PIN /
        # phone + password logins find the account.
        "phone": _normalise_phone(phone) if phone else None,
        "password_hash": _hash_password(payload.password),
        "password_must_change": True,
        "sub_admin_permissions": perms,
        "sub_admin_company_scope": scope,
        "sub_admin_company_ids": company_ids,
        "menu_rights": {
            str(k): bool(v)
            for k, v in (payload.menu_rights or {}).items()
            if isinstance(k, str) and k.startswith("/")
        },
        "disabled": False,
        "created_at": now_iso(),
        "created_by": admin["user_id"],
        "onboarded": True,
        "approval_status": "approved",
    }
    if pin:
        # Iter 220 — separate 6-digit PIN credential (optional).
        doc["pin_hash"] = _hash_pin(pin)
    await db.users.insert_one(doc)

    from utils.welcome_email import send_admin_welcome_email
    await send_admin_welcome_email(
        name=name, email=email, role_label="Sub Admin",
        password=payload.password,
    )
    return {"ok": True, "sub_admin": _sanitise_sub_admin({k: v for k, v in doc.items() if k != "_id"})}


@api.get("/admin/sub-admins/{user_id}")
async def get_sub_admin(user_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    doc = await db.users.find_one({"user_id": user_id, "role": "sub_admin"}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Sub-admin not found")
    return {"sub_admin": _sanitise_sub_admin(doc)}


@api.patch("/admin/sub-admins/{user_id}")
async def update_sub_admin(
    user_id: str,
    payload: SubAdminUpdate,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    existing = await db.users.find_one({"user_id": user_id, "role": "sub_admin"}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Sub-admin not found")

    updates: dict = {}
    fset = payload.model_fields_set
    if "name" in fset and payload.name is not None:
        n = payload.name.strip()
        if not n:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        updates["name"] = n
    if "email" in fset and payload.email is not None:
        e = payload.email.strip().lower()
        if e and "@" not in e:
            raise HTTPException(status_code=400, detail="Invalid email")
        if e and e != existing.get("email"):
            if await db.users.find_one({"email": e, "user_id": {"$ne": user_id}}):
                raise HTTPException(status_code=409, detail="Email already used")
        updates["email"] = e or None
    if "phone" in fset:
        p = _clean_mobile_or_400(payload.phone)
        if p and p != existing.get("phone_e164"):
            if await db.users.find_one({"phone_e164": p, "user_id": {"$ne": user_id}}):
                raise HTTPException(status_code=409, detail="Phone already used")
        updates["phone_e164"] = p
        updates["phone"] = _normalise_phone(p) if p else None
    if "pin" in fset and payload.pin is not None:
        # Iter 220 — set/replace the separate 6-digit PIN credential.
        _pin = _validate_pin_or_400(payload.pin)
        if _pin:
            updates["pin_hash"] = _hash_pin(_pin)
            updates["pin_fail_count"] = 0
            updates["pin_locked_until"] = None
    if "permissions" in fset and payload.permissions is not None:
        updates["sub_admin_permissions"] = _validate_sub_admin_permissions(payload.permissions)
    if "company_scope" in fset and payload.company_scope is not None:
        updates["sub_admin_company_scope"] = payload.company_scope
    if "company_ids" in fset and payload.company_ids is not None:
        updates["sub_admin_company_ids"] = [c for c in payload.company_ids if c]
    if "disabled" in fset and payload.disabled is not None:
        updates["disabled"] = bool(payload.disabled)
        if payload.disabled:
            updates["disabled_reason"] = "manual"
        else:
            # Iter 157 — re-enable resets the inactivity clock so the
            # auto-disable job doesn't flag the account again immediately.
            updates["disabled_reason"] = None
            updates["auto_disabled_at"] = None
            updates["inactivity_warned_for"] = None
            updates["reactivated_at"] = now_iso()
    if "menu_rights" in fset and payload.menu_rights is not None:
        updates["menu_rights"] = {
            str(k): bool(v)
            for k, v in payload.menu_rights.items()
            if isinstance(k, str) and k.startswith("/")
        }

    resolved_scope = updates.get("sub_admin_company_scope", existing.get("sub_admin_company_scope", "all"))
    resolved_ids = updates.get("sub_admin_company_ids", existing.get("sub_admin_company_ids", []))
    if resolved_scope == "restricted" and not resolved_ids:
        raise HTTPException(status_code=400, detail="Restricted scope needs at least one company_id")

    if updates:
        updates["updated_at"] = now_iso()
        await db.users.update_one({"user_id": user_id}, {"$set": updates})

    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return {"ok": True, "sub_admin": _sanitise_sub_admin(fresh)}


@api.post("/admin/sub-admins/{user_id}/reset-password")
async def reset_sub_admin_password(
    user_id: str,
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    new_pw = (payload or {}).get("password", "")
    if not new_pw or len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    existing = await db.users.find_one({"user_id": user_id, "role": "sub_admin"}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Sub-admin not found")
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "password_hash": _hash_password(new_pw),
            "password_must_change": True,
            "password_fail_count": 0,
            "password_locked_until": None,
            "password_reset_at": now_iso(),
            "password_reset_by": admin["user_id"],
        }},
    )
    return {"ok": True}


@api.delete("/admin/sub-admins/{user_id}")
async def delete_sub_admin(user_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    existing = await db.users.find_one({"user_id": user_id, "role": "sub_admin"}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Sub-admin not found")
    await db.user_sessions.delete_many({"user_id": user_id})
    await db.users.delete_one({"user_id": user_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Employer portal credentials (EPFO / ESIC / SSO Shram Suvidha) — Iter 58
# ---------------------------------------------------------------------------
# Company admins (and super admins) can store the credentials the firm uses
# on the government labour portals so we can later drive Chrome automation
# to upload ECR + ESIC challans on their behalf. Passwords are encrypted
# at rest with Fernet (see utils/portal_creds).

class PortalCredUpdate(BaseModel):
    """Update a single portal entry. All fields optional — omit to leave
    that portal untouched. Pass ``clear_password=True`` to WIPE a stored
    password. A non-empty ``password`` string sets a new one."""
    portal: Literal["epfo", "esic", "shram_suvidha"]
    username: Optional[str] = None
    password: Optional[str] = None
    notes: Optional[str] = None
    clear_password: Optional[bool] = None


def _company_scope_check(user: dict, company_id: str) -> None:
    """Auth guard shared by portal-cred endpoints. Super admin sees all;
    company admin only their own company; sub_admins with 'companies:write'
    + matching company scope."""
    role = user.get("role")
    if role == "super_admin":
        return
    if role == "company_admin":
        if user.get("company_id") == company_id:
            return
        raise HTTPException(status_code=403, detail="Not authorised for this company")
    if role == "sub_admin":
        if not sub_admin_can_touch_company(user, company_id):
            raise HTTPException(status_code=403, detail="Not authorised for this company")
        if "companies:write" in (user.get("sub_admin_permissions") or []):
            return
        raise HTTPException(status_code=403, detail="Missing 'companies:write' permission")
    raise HTTPException(status_code=403, detail="Forbidden")


@api.get("/admin/companies/{company_id}/portal-credentials")
async def get_portal_credentials(
    company_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return the masked credentials for a company. Passwords are never
    returned in plaintext — only ``has_password: bool``."""
    from utils.portal_creds import sanitise_stored, PORTAL_KEYS, PORTAL_LABELS
    user = await get_user_from_token(authorization)
    _company_scope_check(user, company_id)
    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "portal_credentials": 1},
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return {
        "company_id": company_id,
        "company_name": company.get("name"),
        "portals": sanitise_stored(company.get("portal_credentials") or {}),
        "known_portals": PORTAL_KEYS,
        "portal_labels": PORTAL_LABELS,
    }


@api.patch("/admin/companies/{company_id}/portal-credentials")
async def update_portal_credentials(
    company_id: str,
    payload: PortalCredUpdate,
    authorization: Optional[str] = Header(None),
):
    """Update a single portal's username / password / notes."""
    from utils.portal_creds import (
        encrypt_password, sanitise_stored,
        PORTAL_KEYS, PORTAL_LABELS,
    )
    user = await get_user_from_token(authorization)
    _company_scope_check(user, company_id)
    if payload.portal not in PORTAL_KEYS:
        raise HTTPException(status_code=400, detail="Unknown portal")
    # Include a required field ("name") in the projection so we never get
    # back an empty {} which would falsely trigger the "not found" branch.
    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "portal_credentials": 1},
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    existing = (company.get("portal_credentials") or {}).get(payload.portal) or {}
    updates = dict(existing)
    if payload.username is not None:
        updates["username"] = payload.username.strip()[:200]
    if payload.notes is not None:
        updates["notes"] = payload.notes.strip()[:400]
    if payload.clear_password:
        updates.pop("password_cipher", None)
    elif payload.password is not None and payload.password != "":
        if len(payload.password) > 400:
            raise HTTPException(status_code=400, detail="Password too long")
        updates["password_cipher"] = encrypt_password(payload.password)
    updates["updated_at"] = now_iso()
    updates["updated_by"] = user["user_id"]

    await db.companies.update_one(
        {"company_id": company_id},
        {"$set": {f"portal_credentials.{payload.portal}": updates}},
    )
    fresh = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "portal_credentials": 1},
    )
    return {
        "ok": True,
        "company_id": company_id,
        "company_name": (fresh or {}).get("name"),
        "portals": sanitise_stored((fresh or {}).get("portal_credentials") or {}),
        "portal_labels": PORTAL_LABELS,
    }


# ---------------------------------------------------------------------------
# Employer (Company Admin) access rights — Iter 58
# ---------------------------------------------------------------------------
# Super admin decides which parts of the Company Admin portal each firm's
# admins can access. Stored as `employer_permissions: [str]` on the
# companies doc. An empty / missing list means "all features enabled"
# (backward-compatible for existing firms).

class EmployerAccessUpdate(BaseModel):
    """Replace the entire employer_permissions array on a company. Pass
    ``permissions=None`` to signal 'all features' (empty array wipes to
    zero features, so please be intentional)."""
    permissions: Optional[List[str]] = None
    # Iter 93 — per-sidebar-button visibility map {route: bool}. Missing
    # route == allowed. Pass {} to allow everything again.
    menu_rights: Optional[dict] = None


def _validate_employer_permissions(perms: Optional[List[str]]) -> List[str]:
    if not perms:
        return []
    known = set(EMPLOYER_PERMISSION_KEYS)
    return sorted({p for p in perms if p in known})


@api.get("/admin/employer-permission-keys")
async def employer_permission_keys(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    return {"permissions": EMPLOYER_PERMISSION_KEYS}


@api.get("/admin/companies/{company_id}/access-rights")
async def get_employer_access_rights(
    company_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return the current employer_permissions for a company. Super admin
    can read for any company; company admin sees only their own; sub_admin
    with 'companies:read' + matching scope."""
    user = await get_user_from_token(authorization)
    _company_scope_check(user, company_id)  # write scope; read is stricter than needed but safe
    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "employer_permissions": 1, "employer_menu_rights": 1},
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    perms = company.get("employer_permissions")
    return {
        "company_id": company_id,
        "company_name": company.get("name"),
        "permissions": perms or [],
        "all_features_enabled": not perms,   # empty array == everything on
        "known_permissions": EMPLOYER_PERMISSION_KEYS,
        # Iter 93 — per-sidebar-button gating. Missing key == allowed.
        "menu_rights": company.get("employer_menu_rights") or {},
    }


@api.patch("/admin/companies/{company_id}/access-rights")
async def set_employer_access_rights(
    company_id: str,
    payload: EmployerAccessUpdate,
    authorization: Optional[str] = Header(None),
):
    """Super admin only — replace the employer_permissions array. Pass
    ``permissions=None`` to reset the field to 'all features enabled'."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "name": 1})
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if payload.permissions is None:
        await db.companies.update_one(
            {"company_id": company_id},
            {"$unset": {"employer_permissions": ""}, "$set": {"employer_permissions_updated_at": now_iso()}},
        )
        perms: List[str] = []
    else:
        perms = _validate_employer_permissions(payload.permissions)
        await db.companies.update_one(
            {"company_id": company_id},
            {"$set": {
                "employer_permissions": perms,
                "employer_permissions_updated_at": now_iso(),
                "employer_permissions_updated_by": admin["user_id"],
            }},
        )
    # Iter 93 — per-sidebar-button map. Only touched when the client sends it.
    if payload.menu_rights is not None:
        clean = {
            str(k): bool(v)
            for k, v in payload.menu_rights.items()
            if isinstance(k, str) and k.startswith("/")
        }
        await db.companies.update_one(
            {"company_id": company_id},
            {"$set": {"employer_menu_rights": clean}},
        )
    fresh = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "employer_menu_rights": 1},
    )
    return {
        "ok": True,
        "company_id": company_id,
        "company_name": company.get("name"),
        "permissions": perms,
        "all_features_enabled": not perms,
        "menu_rights": (fresh or {}).get("employer_menu_rights") or {},
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
    grp = await db.masters.find_one(
        {"master_id": group_id, "type": "group",
         "company_id": {"$in": [company_id, "__global__"]}},
        {"_id": 0, "member_user_ids": 1, "name": 1},
    )
    if grp is not None:
        ids = list(grp.get("member_user_ids") or [])
        if ids:
            return ids
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
    grp_name = egp.get("name") or egp.get("group_name")
    if not grp_name:
        return []
    ids = await db.users.find(
        {"company_id": company_id, "employee_group": grp_name},
        {"_id": 0, "user_id": 1},
    ).to_list(4000)
    return [u["user_id"] for u in ids]


# ---------------------------------------------------------------------------
# Iter 68 — Monthly attendance reports (Working Hours + IN/OUT sheet)
# ---------------------------------------------------------------------------

async def _monthly_report_impl(
    company_id: str,
    month: str,
    admin: dict,
    variant: str,   # "hours" | "inout"
    group_id: Optional[str] = None,
):
    """Shared plumbing for both monthly attendance reports.

    Loads employees + all raw punches for the requested month, groups by
    user_id + date and hands off to the correct XLSX builder.
    """
    from fastapi.responses import Response
    # Super Admin, Sub-Admin (with scope) or Company Admin of the firm.
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    if admin.get("role") == "sub_admin":
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    if admin.get("role") == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="You can only export your own firm")

    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "attendance_policy": 1})
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    # Iter 200 (user request) — Report Settings live on the firm's attendance
    # policy. A disabled report type cannot be exported for that firm.
    _rs_key = "inout" if variant.startswith("inout") else "hours"
    _rs = ((company.get("attendance_policy") or {}).get("report_settings") or {})
    _rs_en = _rs.get("enabled") or {}
    if _rs_key in _rs_en and not _rs_en.get(_rs_key):
        _lbl = "In/Out" if _rs_key == "inout" else "Hours Only"
        raise HTTPException(
            status_code=403,
            detail=f"The {_lbl} report is disabled for this firm "
                   "(Attendance Policy → Report Settings).")
    try:
        y, m = int(month[:4]), int(month[5:7])
        if m < 1 or m > 12:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")

    # All four variants (XLSX + PDF twins) are grid-based now, so the
    # employee/punch loading happens inside ``_compute_monthly_grid_data``
    # with the full Firm Master policy pipeline applied.
    if variant == "inout":
        # Iter 77x — Grid View XLSX (multi-row per employee).
        # Reuses the exact grid-compute pipeline the Grid View screen uses
        # (via ``_compute_monthly_grid_data``) so the Excel mirrors what
        # admins see on-screen: bounce-merge, dedup, OT cap, cross-day OT
        # pairing, weekly-off rules — all applied upstream.
        from utils.monthly_attendance import build_grid_view_xlsx
        grid = await _compute_monthly_grid_data(
            company_id=company_id,
            month=month,
            group_id=group_id,
            from_date=None,
            to_date=None,
        )
        xlsx_bytes = build_grid_view_xlsx(grid)
        variant_slug = "GridView"
    elif variant == "inout_pdf":
        # Policy-aligned (user directive): PDF twins now consume the SAME
        # grid pipeline as the XLSX/Grid View so all attendance reports
        # follow the Firm Master attendance policy.
        from utils.monthly_attendance_pdf import build_monthly_inout_pdf
        grid = await _compute_monthly_grid_data(
            company_id=company_id,
            month=month,
            group_id=group_id,
            from_date=None,
            to_date=None,
        )
        pdf_bytes = build_monthly_inout_pdf(grid)
        company_slug = (company.get("name") or "company").replace(" ", "_")
        filename = f"MonthlyAttendance_InOut_{company_slug}_{month}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    elif variant == "ot":
        # Iter 203 (user request) — OT Duty HRS report: day-wise OT ONLY.
        from utils.monthly_attendance import build_ot_only_grid_xlsx
        grid = await _compute_monthly_grid_data(
            company_id=company_id,
            month=month,
            group_id=group_id,
            from_date=None,
            to_date=None,
        )
        xlsx_bytes = build_ot_only_grid_xlsx(grid)
        variant_slug = "OTDutyHRS"
    elif variant == "ot_pdf":
        from utils.monthly_attendance_pdf import build_monthly_ot_pdf
        grid = await _compute_monthly_grid_data(
            company_id=company_id,
            month=month,
            group_id=group_id,
            from_date=None,
            to_date=None,
        )
        pdf_bytes = build_monthly_ot_pdf(grid)
        company_slug = (company.get("name") or "company").replace(" ", "_")
        filename = f"MonthlyAttendance_OTDutyHRS_{company_slug}_{month}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    elif variant == "hours_pdf":
        from utils.monthly_attendance_pdf import build_monthly_hours_pdf
        grid = await _compute_monthly_grid_data(
            company_id=company_id,
            month=month,
            group_id=group_id,
            from_date=None,
            to_date=None,
        )
        pdf_bytes = build_monthly_hours_pdf(grid)
        company_slug = (company.get("name") or "company").replace(" ", "_")
        filename = f"MonthlyAttendance_Hours_{company_slug}_{month}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        # Iter 77z — Hours Only sheet routed through grid compute so each
        # day cell combines Duty + OT (both included in the totals).
        from utils.monthly_attendance import build_hours_only_grid_xlsx
        grid = await _compute_monthly_grid_data(
            company_id=company_id,
            month=month,
            group_id=group_id,
            from_date=None,
            to_date=None,
        )
        xlsx_bytes = build_hours_only_grid_xlsx(grid)
        variant_slug = "Hours"
    company_slug = (company.get("name") or "company").replace(" ", "_")
    filename = f"MonthlyAttendance_{variant_slug}_{company_slug}_{month}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api.get("/admin/attendance/monthly-hours/{company_id}/{month}.xlsx")
async def monthly_attendance_hours(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Monthly working-hours matrix (mirrors the user's reference sheet)."""
    admin = await get_user_from_token(authorization)
    return await _monthly_report_impl(company_id, month, admin, "hours", group_id)


@api.get("/admin/attendance/monthly-ot/{company_id}/{month}.xlsx")
async def monthly_attendance_ot(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 203 — OT Duty HRS report (day-wise OT only, policy-computed)."""
    admin = await get_user_from_token(authorization)
    return await _monthly_report_impl(company_id, month, admin, "ot", group_id)


@api.get("/admin/attendance/monthly-ot/{company_id}/{month}.pdf")
async def monthly_attendance_ot_pdf(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    return await _monthly_report_impl(company_id, month, admin, "ot_pdf", group_id)


@api.get("/admin/attendance/monthly-inout/{company_id}/{month}.xlsx")
async def monthly_attendance_inout(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Monthly IN / OUT + Working Hours matrix — same layout, richer cells."""
    admin = await get_user_from_token(authorization)
    return await _monthly_report_impl(company_id, month, admin, "inout", group_id)


@api.get("/admin/attendance/monthly-inout/{company_id}/{month}.pdf")
async def monthly_attendance_inout_pdf(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 77 - Landscape A4 PDF twin of the IN / OUT XLSX. Same numbers,
    print-ready."""
    admin = await get_user_from_token(authorization)
    return await _monthly_report_impl(company_id, month, admin, "inout_pdf", group_id)


@api.get("/admin/attendance/monthly-hours/{company_id}/{month}.pdf")
async def monthly_attendance_hours_pdf(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Iter 77 - Landscape A4 PDF twin of the Working Hours XLSX."""
    admin = await get_user_from_token(authorization)
    return await _monthly_report_impl(company_id, month, admin, "hours_pdf", group_id)


# ---------------------------------------------------------------------------
# Iter 111 — DAILY-BASIS attendance report (single date, one row/employee)
# ---------------------------------------------------------------------------
async def _daily_report_impl(company_id: str, date_s: str, admin: dict, fmt: str,
                             group_id: Optional[str] = None):
    from fastapi.responses import Response
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    if admin.get("role") == "sub_admin":
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    if admin.get("role") == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="You can only export your own firm")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_s or ""):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    grid = await _compute_monthly_grid_data(
        company_id=company_id,
        month=date_s[:7],
        group_id=group_id,
        from_date=date_s,
        to_date=date_s,
    )
    company_slug = (((grid.get("company") or {}).get("name")) or "company").replace(" ", "_")
    if fmt == "pdf":
        from utils.daily_attendance import build_daily_pdf
        content = build_daily_pdf(grid, date_s)
        media = "application/pdf"
    else:
        from utils.daily_attendance import build_daily_xlsx
        content = build_daily_xlsx(grid, date_s)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    filename = f"DailyAttendance_{company_slug}_{date_s}.{fmt}"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api.get("/admin/attendance/daily/{company_id}/{date_s}.xlsx")
async def daily_attendance_xlsx(
    company_id: str,
    date_s: str,
    group_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Daily-basis attendance report (Excel) — one row per employee."""
    admin = await get_user_from_token(authorization)
    return await _daily_report_impl(company_id, date_s, admin, "xlsx", group_id)


@api.get("/admin/attendance/daily/{company_id}/{date_s}.pdf")
async def daily_attendance_pdf(
    company_id: str,
    date_s: str,
    group_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Daily-basis attendance report (PDF) — one row per employee."""
    admin = await get_user_from_token(authorization)
    return await _daily_report_impl(company_id, date_s, admin, "pdf", group_id)


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
    return await _compute_monthly_grid_data(
        company_id=company_id,
        month=month,
        group_id=group_id,
        from_date=from_date,
        to_date=to_date,
    )


async def _compute_monthly_grid_data(
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
        {"_id": 0, "company_id": 1, "name": 1, "attendance_policy": 1},
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
        },
    ).sort([("employee_code", 1), ("name", 1)]).to_list(4000)
    employees = [e for e in employees if not _month_is_before_doj(e, month)]

    # ----- Punches for those employees in the target window -------------
    punches_by_user_day: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    if employees:
        user_ids = [e["user_id"] for e in employees]
        async for r in db.attendance.find(
            # Iter 83-final — Per user rule: only APPROVED punches count
            # toward the attendance grid / IN-OUT sheet. Pending punches
            # are held until an admin reviews them, and rejected ones are
            # never counted. ``manual_admin`` inserts and admin PATCH
            # edits already set ``status="approved"`` automatically so
            # they're included seamlessly.
            {"user_id": {"$in": user_ids},
             "date": {"$gte": date_from, "$lte": date_to},
             "status": "approved"},
            {"_id": 0, "user_id": 1, "date": 1, "kind": 1, "at": 1, "source": 1},
        ).sort([("user_id", 1), ("at", 1)]):
            uid = r["user_id"]
            punches_by_user_day.setdefault(uid, {}).setdefault(r["date"], []).append(r)
        # Iter 77y — Stitch cross-day OT (night-shift OUT punches that
        # land on the next calendar day get moved back to the day the
        # session started so the OT window can be paired correctly).
        for _uid_key in list(punches_by_user_day.keys()):
            punches_by_user_day[_uid_key] = stitch_cross_day_ot(
                punches_by_user_day[_uid_key],
            )

    # ----- Working-hour thresholds for OT calculation --------------------
    pol = company.get("attendance_policy") or {}
    pol = await inject_firm_ot_flag(dict(pol), company.get("company_id"))
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
            # Iter 77s — Drop same-machine same-kind duplicate punches
            # within 15 minutes so double-taps on the biometric device
            # don't inflate the hour count.
            day_punches = dedupe_same_machine_punches(day_punches, 15)
            # Iter 77w — Merge OUT->IN "bounces" (device stutter within
            # 60 seconds) so they are treated as one continuous session.
            day_punches = merge_out_in_bounces(day_punches, 60)
            if not day_punches:
                days_cell[key] = {
                    "in": None, "out": None, "ot_in": None, "ot_out": None,
                    "hours": 0.0, "duty_hours": 0.0, "raw_hours": 0.0, "ot_hours": 0.0,
                    "sources": [], "punches": 0,
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
                    "punches": len(day_punches),
                    "anomaly": True,
                    "anomaly_reason": "missing_punch",
                }
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
            weekday = datetime(yy, mm, dd).weekday()
            _is_holiday_day = date_key_iso in _holiday_dates
            summary = compute_textile_day(
                day_punches, eff_policy, emp_full, weekday,
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
            if _pm_8hr_reports:
                standard_h = min(standard_h, 8.0)
            # Iter 77z-fix — PAIR-BASED time & hour derivation.
            #   • Regular duty comes from the FIRST paired IN→OUT.
            #   • OT comes from the SECOND paired IN→OUT (or arithmetic
            #     fallback for single-pair long shifts).
            #   • Display timestamps (``in`` / ``out``) reflect the
            #     regular pair, NOT the raw last-OUT (which for cross-day
            #     shifts would show the next-morning punch).
            reg_in_dt, reg_out_dt, ot_in_dt, ot_out_dt = split_regular_ot_times(
                day_punches, standard_h * 60.0,
            )
            # Iter 77z-final — Apply the firm's rounding policy
            # (``duty_hours_rounding_minutes``: 0/5/10/15/30) to BOTH
            # duty and OT windows so the grid + downloads reflect the
            # rounded numbers admins configured.
            _round_step = int(eff_policy.get("duty_hours_rounding_minutes") or 0)
            duty_only_hrs = 0.0
            if reg_in_dt and reg_out_dt:
                _duty_min = (reg_out_dt - reg_in_dt).total_seconds() / 60.0
                _duty_min = _round_minutes(_duty_min, _round_step)
                duty_only_hrs = round(_duty_min / 60.0, 2)
            ot_hrs = 0.0
            if ot_in_dt and ot_out_dt:
                _ot_min = (ot_out_dt - ot_in_dt).total_seconds() / 60.0
                _ot_min = _round_minutes(_ot_min, _round_step)
                ot_hrs = round(_ot_min / 60.0, 2)
            # Cap regular duty at the shift length. Any spillover joins OT.
            if duty_only_hrs > standard_h:
                _spill = round(duty_only_hrs - standard_h, 2)
                ot_hrs = round(ot_hrs + _spill, 2)
                duty_only_hrs = standard_h
            # If OT is disabled for this employee OR firm-wide, don't surface OT.
            if not eff_policy.get("ot_allowed", True) or eff_policy.get("firm_ot_allowed") is False:
                ot_hrs = 0.0
            # Minimum-OT grace: < 1 hour rounds to 0.
            if ot_hrs > 0 and ot_hrs < 1.0:
                ot_hrs = 0.0
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
            if _pm_8hr_reports and (duty_only_hrs + ot_hrs) >= 8.0:
                _day_present = max(_day_present, 1.0)
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
                "sources": seen,
                "present": _day_present,
                "weekly_off": bool(summary.get("is_weekly_off")),
                "holiday": _is_holiday_day,
                # Iter 94 — day-wise earned salary (basic-rate based).
                "salary": day_sal,
            }
            if day_sal > 0:
                total_salary += day_sal
                day_salary_totals[key] = round(day_salary_totals.get(key, 0.0) + day_sal, 2)
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
        total_hours = round(total_hours_min / 60.0, 4)
        total_ot_hours = round(total_ot_min / 60.0, 4)
        total_duty_only = round(total_duty_only_min / 60.0, 4)
        _div_min = int(round((8.0 if _pm_8hr_reports else emp_daily_hrs) * 60))
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
        {"_id": 0, "company_id": 1, "name": 1, "attendance_policy": 1},
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
        },
    ).sort([("employee_code", 1), ("name", 1)]).to_list(4000)

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
    for _uid_k in list(punches_by_user_day.keys()):
        punches_by_user_day[_uid_k] = stitch_cross_day_ot(
            punches_by_user_day[_uid_k],
        )

    pol = company.get("attendance_policy") or {}
    pol = await inject_firm_ot_flag(dict(pol), company.get("company_id"))
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
            # Iter 77s — same 15-min dedup for the OT report so numbers match.
            day_punches = dedupe_same_machine_punches(day_punches, 15)
            # Iter 77w — Bounce-merge OUT→IN within 60s (device stutter)
            day_punches = merge_out_in_bounces(day_punches, 60)
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
            # Iter 77z-fix — Pair-based duty/OT derivation (matches grid).
            reg_in_dt, reg_out_dt, ot_in_dt, ot_out_dt = split_regular_ot_times(
                day_punches, standard_h * 60.0,
            )
            _round_step = int(eff_policy.get("duty_hours_rounding_minutes") or 0)
            duty_only = 0.0
            if reg_in_dt and reg_out_dt:
                _duty_min = (reg_out_dt - reg_in_dt).total_seconds() / 60.0
                _duty_min = _round_minutes(_duty_min, _round_step)
                duty_only = round(_duty_min / 60.0, 2)
            ot = 0.0
            if ot_in_dt and ot_out_dt:
                _ot_min = (ot_out_dt - ot_in_dt).total_seconds() / 60.0
                _ot_min = _round_minutes(_ot_min, _round_step)
                ot = round(_ot_min / 60.0, 2)
            # Cap duty at shift length; spillover joins OT.
            if duty_only > standard_h:
                ot = round(ot + (duty_only - standard_h), 2)
                duty_only = standard_h
            # Honor per-employee AND firm-wide OT-allowed flags.
            if not eff_policy.get("ot_allowed", True) or eff_policy.get("firm_ot_allowed") is False:
                ot = 0.0
            # Minimum OT grace (< 1h ignored).
            if 0 < ot < 1.0:
                ot = 0.0
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


async def _generate_attendance_sheet_impl(
    company_id: str, month: str, admin: dict, group_id: Optional[str] = None,
):
    from utils.master_sheet import build_master_sheet_xlsx
    from fastapi.responses import Response
    require_super_admin_strict(admin)
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
        {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1, "doj": 1, "department": 1},
    ).to_list(2000)
    # Skip pre-DOJ (Iter 57 rule) so the master sheet mirrors the compliance run.
    employees = [e for e in employees if not _month_is_before_doj(e, month)]

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
    authorization: Optional[str] = Header(None),
):
    """Generate the prefilled attendance sheet XLSX for a company + month,
    optionally filtered by Employee Group."""
    admin = await get_user_from_token(authorization)
    return await _generate_attendance_sheet_impl(company_id, month, admin, group_id)


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
    require_super_admin_strict(admin)
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
    require_super_admin_strict(admin)
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
# Employee Masters (Group / Department / Designation) — Iter 59
# ---------------------------------------------------------------------------
# Single polymorphic collection `masters` with fields:
#   master_id: str (uuid)
#   type: "group" | "department" | "designation"
#   company_id: str (scoped per firm — super admin selects the firm)
#   name: str
#   member_user_ids: List[str]  (for `group` type, optional otherwise)
#   created_at, updated_at, created_by
_MASTER_TYPES = ("group", "department", "designation", "allowance", "deduction", "holiday")


class MasterUpsert(BaseModel):
    type: str
    company_id: str
    name: str
    member_user_ids: Optional[List[str]] = None
    # Iter 200 — Holiday Master entries carry a calendar date (YYYY-MM-DD).
    date: Optional[str] = None


@api.get("/admin/masters")
async def list_masters(
    type: str,
    company_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if type not in _MASTER_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {_MASTER_TYPES}")
    q: Dict[str, Any] = {"type": type}
    if admin["role"] == "company_admin":
        # Company admin sees THEIR firm's masters + any globally-scoped ones.
        q["company_id"] = {"$in": [admin.get("company_id"), "__global__", None]}
    elif company_id and company_id != "__global__":
        q["company_id"] = {"$in": [company_id, "__global__", None]}
    # else: super/sub admin without a firm filter -> ALL firms + globals.
    # Iter 244 (user bug) — INTERLINK: groups that exist only on employee
    # records (e.g. created during Bulk Employee Import) are auto-registered
    # into the Group Master here, so they show up in the General Masters
    # screen and every Group dropdown across the app.
    if type == "group":
        try:
            u_match: Dict[str, Any] = {
                "role": "employee",
                "employee_type": {"$exists": True, "$nin": [None, ""]},
            }
            if admin["role"] == "company_admin":
                u_match["company_id"] = admin.get("company_id")
            elif company_id and company_id != "__global__":
                u_match["company_id"] = company_id
            existing_names = {
                (m.get("name") or "").strip().upper()
                async for m in db.masters.find({"type": "group"}, {"_id": 0, "name": 1})
            }
            async for row in db.users.aggregate([
                {"$match": u_match},
                {"$group": {"_id": {
                    "cid": "$company_id",
                    "name": {"$toUpper": {"$trim": {"input": "$employee_type"}}},
                }}},
                {"$limit": 500},
            ]):
                nm = (row["_id"].get("name") or "").strip()
                u_cid = row["_id"].get("cid")
                if not nm or not u_cid or nm in existing_names:
                    continue
                await db.masters.insert_one({
                    "master_id": f"mst_{uuid.uuid4().hex[:12]}",
                    "type": "group",
                    "company_id": u_cid,
                    "name": nm,
                    "member_user_ids": [],
                    "date": None,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "created_by": admin["user_id"],
                    "scope": "firm",
                    "auto_registered": "bulk_import_interlink",
                })
                existing_names.add(nm)
        except Exception as _e:
            logging.warning(f"group-master interlink failed: {_e}")
    items = await db.masters.find(q, {"_id": 0}).sort("name", 1).to_list(2000)
    return {"items": items}


@api.post("/admin/masters")
async def create_master(
    payload: MasterUpsert,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if payload.type not in _MASTER_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {_MASTER_TYPES}")
    # Iter 108 — company admins may auto-register masters, but ONLY for
    # their own firm (they cannot create global masters).
    if admin.get("role") == "company_admin":
        if (payload.company_id or "").strip() in ("", "__global__") or \
                payload.company_id != admin.get("company_id"):
            raise HTTPException(status_code=403, detail="You can only add masters for your own firm")
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    # Iter 129j (user directive) — ALL master names (Departments,
    # Designations, Employee Types/Groups, Allowances, Deductions) are
    # stored in CAPITAL LETTERS, so duplicates can never differ by case.
    name = name.upper()
    # Iter 77 - Support GLOBAL masters (available across every firm).
    is_global = (payload.company_id or "").strip() in ("", "__global__")
    # Iter 113 — company admins may add entries ONLY to their own firm
    # (lets manually-typed Designation/Department values persist into the
    # dropdown from the Add-Employee form).
    if admin.get("role") == "company_admin":
        if is_global or payload.company_id != admin.get("company_id"):
            raise HTTPException(status_code=403, detail="You can only add masters for your own firm")
    if is_global:
        target_cid = "__global__"
    else:
        company = await db.companies.find_one(
            {"company_id": payload.company_id}, {"_id": 0, "company_id": 1}
        )
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        target_cid = payload.company_id
    # Iter 139 (user request) — HARD duplicate stop:
    #  • GROUPS are used across the whole master → same name may not exist
    #    in ANY scope (any firm or global).
    #  • Other types: a firm entry may not duplicate its own firm's or a
    #    global one; a GLOBAL entry may not duplicate ANY existing scope.
    dup_q: Dict[str, Any] = {
        "type": payload.type,
        "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
    }
    if payload.type != "group" and not is_global:
        dup_q["company_id"] = {"$in": [target_cid, "__global__", None]}
    if payload.type == "holiday":
        # Same holiday name may repeat on different dates (yearly festivals).
        dup_q["date"] = (payload.date or "").strip()[:10]
    dup = await db.masters.find_one(dup_q, {"_id": 0, "master_id": 1})
    if dup:
        raise HTTPException(status_code=409, detail=f"A {payload.type} named '{name}' already exists")
    master_id = f"mst_{uuid.uuid4().hex[:12]}"
    # Iter 200 — Holiday Master needs a valid date.
    _hol_date = None
    if payload.type == "holiday":
        _hol_date = (payload.date or "").strip()[:10]
        try:
            datetime.strptime(_hol_date, "%Y-%m-%d")
        except Exception:
            raise HTTPException(status_code=400, detail="Holiday requires a valid date (YYYY-MM-DD)")
    doc = {
        "master_id": master_id,
        "type": payload.type,
        "company_id": target_cid,
        "name": name,
        "member_user_ids": list(payload.member_user_ids or []) if payload.type == "group" else [],
        "date": _hol_date,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": admin["user_id"],
        "scope": "global" if is_global else "firm",
    }
    await db.masters.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.patch("/admin/masters/{master_id}")
async def update_master(
    master_id: str,
    payload: MasterUpsert,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    existing = await db.masters.find_one({"master_id": master_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Master not found")
    updates: Dict[str, Any] = {"updated_at": now_iso()}
    if payload.name is not None:
        name = payload.name.strip().upper()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        # Iter 139 (user request) — renames must not create duplicates
        # either (same rules as create; excludes this master itself).
        dup_q: Dict[str, Any] = {
            "type": existing.get("type"),
            "master_id": {"$ne": master_id},
            "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
        }
        if existing.get("type") != "group" and existing.get("company_id") not in ("__global__", None):
            dup_q["company_id"] = {"$in": [existing.get("company_id"), "__global__", None]}
        if await db.masters.find_one(dup_q, {"_id": 0, "master_id": 1}):
            raise HTTPException(
                status_code=409,
                detail=f"A {existing.get('type')} named '{name}' already exists")
        updates["name"] = name
    if payload.type == "group" and payload.member_user_ids is not None:
        updates["member_user_ids"] = list(payload.member_user_ids or [])
    await db.masters.update_one({"master_id": master_id}, {"$set": updates})
    merged = {**existing, **updates}
    merged.pop("_id", None)
    return merged


@api.delete("/admin/masters/{master_id}")
async def delete_master(
    master_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    r = await db.masters.delete_one({"master_id": master_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Master not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Firm-wise Compliance Policy — Iter 59
# ---------------------------------------------------------------------------
# Stored inline on the `companies` doc under `compliance_policy` so it
# overrides the global defaults defined in utils/compliance_salary.py.
# Schema (all fields optional — omit to inherit global):
#   pf_employee_rate, pf_employer_rate, pf_admin_rate, pf_wage_cap,
#   esic_employee_rate, esic_employer_rate, esic_wage_threshold,
#   tds_regime ("old" | "new"), pt_slabs (list of {upto, amount})


class CompliancePolicyPayload(BaseModel):
    pf_employee_rate: Optional[float] = None
    pf_employer_rate: Optional[float] = None
    pf_admin_rate: Optional[float] = None
    pf_wage_cap: Optional[float] = None
    esic_employee_rate: Optional[float] = None
    esic_employer_rate: Optional[float] = None
    esic_wage_threshold: Optional[float] = None
    tds_regime: Optional[str] = None
    pt_slabs: Optional[List[Dict[str, Any]]] = None
    # Iter 178 — state-wise PT: firm's PT state auto-applies statutory slabs.
    pt_state: Optional[str] = None
    apply_pf: Optional[bool] = None
    apply_esic: Optional[bool] = None
    apply_pt: Optional[bool] = None
    apply_tds: Optional[bool] = None
    # Iter 68 — Salary-structure defaults for the compliance run.  Moved from
    # the Compliance Salary screen (which was editable) to a single Firm
    # Settings surface.  Percentages of monthly gross.
    basic_pct: Optional[float] = None
    hra_pct: Optional[float] = None
    conveyance_pct: Optional[float] = None
    medical_pct: Optional[float] = None
    special_pct: Optional[float] = None
    others_pct: Optional[float] = None
    stat_wage_floor_pct: Optional[float] = None
    # Iter 85 — Firm toggle for percentage-based bifurcation.
    # When True: admins enter Compliance Gross ₹ per employee, and the
    # system auto-bifurcates into Basic/HRA/Conveyance/etc using the
    # firm's percentages below.
    # When False: admins must enter each Basic/HRA/etc amount manually
    # on the Employee Master (percentages are ignored).
    allow_percent_bifurcation: Optional[bool] = None
    # Iter 85 — Firm-level allowance selection. Basic is ALWAYS on and
    # cannot be disabled (statutory requirement). The others (HRA,
    # Conveyance, Medical, Special, Others) are opt-in per firm.
    # Compliance Salary Process only shows / applies the enabled heads.
    enabled_allowances: Optional[List[str]] = None  # e.g. ["basic","hra","conveyance"]
    notes: Optional[str] = None


@api.get("/admin/pt-states")
async def list_pt_states(authorization: Optional[str] = Header(None)):
    """Iter 178 — state-wise Professional Tax slab catalogue (monthly
    gross → monthly PT). Used by the firm Compliance Policy screen."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    from utils.compliance_salary import PT_STATE_SLABS
    return {"states": [
        {"state": s, "slabs": slabs, "has_pt": bool(slabs)}
        for s, slabs in sorted(PT_STATE_SLABS.items())
    ]}


@api.get("/admin/companies/{company_id}/compliance-policy")
async def get_company_compliance_policy(
    company_id: str,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorised")
    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "compliance_policy": 1, "name": 1}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {
        "company_id": company_id,
        "name": company.get("name"),
        "policy": company.get("compliance_policy") or {},
    }


@api.put("/admin/companies/{company_id}/compliance-policy")
async def set_company_compliance_policy(
    company_id: str,
    payload: CompliancePolicyPayload,
    authorization: Optional[str] = Header(None),
):
    """Web-only endpoint (Super Admin) to set firm-level Compliance policy
    overrides. Any fields left null inherit the global defaults. Merges with
    the existing stored policy so partial PUTs don't wipe unrelated fields."""
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "company_id": 1, "compliance_policy": 1}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    existing = company.get("compliance_policy") or {}
    incoming = {k: v for k, v in payload.dict().items() if v is not None}
    policy = {**existing, **incoming}
    policy["updated_at"] = now_iso()
    policy["updated_by"] = admin["user_id"]
    await db.companies.update_one(
        {"company_id": company_id}, {"$set": {"compliance_policy": policy}}
    )
    return {"ok": True, "policy": policy}


@api.get("/admin/compliance-salary-runs/{run_id}/ecr.txt")
async def download_ecr_file(run_id: str, authorization: Optional[str] = Header(None)):
    """Download the EPFO ECR (Electronic Challan return) text file for a
    compliance salary run. Super admin uploads this to unifiedportal-emp.epfindia.gov.in.
    Supports optional ?group_id= filter to only include employees in that
    Employee Group."""
    from utils.master_sheet import build_ecr_text
    from fastapi.responses import Response
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    await require_employer_permission(admin, "compliance_salary:read", db)
    run = await db.compliance_salary_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Compliance salary run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised")
    txt = build_ecr_text(run)
    return Response(
        content=txt,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="ECR_{run.get("month")}.txt"'},
    )


# ---------------------------------------------------------------------------
# Statutory Bonus Calculation — Iter 59
# ---------------------------------------------------------------------------
# Payment of Bonus Act, 1965 (Indian labour law):
#   • Eligibility: employees whose Basic+DA ≤ eligibility_cap (default ₹21,000)
#   • Bonus payable = rate% × min(actual Basic+DA, wage_ceiling) × months_worked
#   • Statutory min rate 8.33 %, max 20 %
#   • Wage ceiling default ₹7,000 (or state minimum wage, whichever is higher)
#   • Applied per Financial Year (Apr → Mar in India), must be paid within 8
#     months of FY close.
#
# Rules are stored per-firm at companies.bonus_policy so they can be updated
# any time and re-processed. Runs are stored in `bonus_runs`.


def _fy_bounds(fy_start_year: int) -> tuple[str, str]:
    """Return ('YYYY-04-01', 'YYYY+1-03-31') for a given FY start year."""
    return f"{fy_start_year:04d}-04-01", f"{fy_start_year + 1:04d}-03-31"


def _default_bonus_policy() -> Dict[str, Any]:
    return {
        "rate_percent": 8.33,        # statutory minimum
        "wage_ceiling": 7000.0,      # ₹7,000 per month
        "eligibility_cap": 21000.0,  # employees earning ≤ this Basic+DA are eligible
        "basic_percent_of_gross": 50.0,  # if we only have gross, take 50% as basic (labour code)
        "min_months_worked": 1,      # must have worked at least 1 month in FY
    }


class BonusPolicyPayload(BaseModel):
    rate_percent: Optional[float] = None
    wage_ceiling: Optional[float] = None
    eligibility_cap: Optional[float] = None
    basic_percent_of_gross: Optional[float] = None
    min_months_worked: Optional[int] = None
    notes: Optional[str] = None


@api.get("/admin/companies/{company_id}/bonus-policy")
async def get_bonus_policy(
    company_id: str, authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    if admin["role"] == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorised")
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "bonus_policy": 1, "name": 1})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    policy = {**_default_bonus_policy(), **(company.get("bonus_policy") or {})}
    return {"company_id": company_id, "name": company.get("name"), "policy": policy}


@api.put("/admin/companies/{company_id}/bonus-policy")
async def set_bonus_policy(
    company_id: str,
    payload: BonusPolicyPayload,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_super_admin_strict(admin)
    company = await db.companies.find_one({"company_id": company_id}, {"_id": 0, "company_id": 1})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    existing = (await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "bonus_policy": 1}
    )) or {}
    policy = {**_default_bonus_policy(), **(existing.get("bonus_policy") or {})}
    for k, v in payload.dict().items():
        if v is not None:
            policy[k] = v
    # Enforce statutory bounds
    if policy["rate_percent"] < 8.33:
        policy["rate_percent"] = 8.33
    if policy["rate_percent"] > 20.0:
        policy["rate_percent"] = 20.0
    policy["updated_at"] = now_iso()
    policy["updated_by"] = admin["user_id"]
    await db.companies.update_one(
        {"company_id": company_id}, {"$set": {"bonus_policy": policy}}
    )
    return {"ok": True, "policy": policy}


class BonusRunRequest(BaseModel):
    company_id: str
    fy_start_year: int          # e.g. 2025 → FY 2025-26 (Apr 2025 – Mar 2026)
    group_id: Optional[str] = None


async def _compute_bonus_run(
    company_id: str, fy_start_year: int, group_id: Optional[str], admin: dict,
) -> Dict[str, Any]:
    company = await db.companies.find_one(
        {"company_id": company_id}, {"_id": 0, "name": 1, "bonus_policy": 1}
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    policy = {**_default_bonus_policy(), **(company.get("bonus_policy") or {})}

    date_from, date_to = _fy_bounds(fy_start_year)
    fy_label = f"{fy_start_year}-{str(fy_start_year + 1)[-2:]}"

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
        {
            "_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
            "doj": 1, "exit_date": 1,
            "salary_monthly": 1, "basic_salary": 1,
            "salary_mode": 1, "salary_structure_actual": 1,
        },
    ).to_list(5000)

    rows: List[Dict[str, Any]] = []
    from datetime import date as _date

    def _parse_date(s: str) -> Optional[_date]:
        if not s:
            return None
        try:
            return _date.fromisoformat(s[:10])
        except Exception:
            return None

    fy_start = _date.fromisoformat(date_from)
    fy_end = _date.fromisoformat(date_to)

    for e in employees:
        doj = _parse_date(e.get("doj") or "")
        exit_d = _parse_date(e.get("exit_date") or "")

        # Effective months worked inside the FY window
        eff_start = max(doj, fy_start) if doj else fy_start
        eff_end = min(exit_d, fy_end) if exit_d else fy_end
        if eff_start > eff_end:
            continue
        months_worked = (
            (eff_end.year - eff_start.year) * 12
            + (eff_end.month - eff_start.month)
            + 1
        )
        months_worked = max(0, min(12, months_worked))
        if months_worked < int(policy.get("min_months_worked") or 1):
            continue

        gross = float(e.get("salary_monthly") or 0)
        basic = float(e.get("basic_salary") or 0)
        # Iter 95 — resolve the Basic rate from salary_structure_actual
        # (same priority as the salary grids). Daily / hourly rates are
        # converted to a monthly equivalent (× 26 days / × 8h × 26 days)
        # so bonus math works for Kankani-style daily-rated workers.
        _mode = str(e.get("salary_mode") or "monthly").lower()
        for _r in (e.get("salary_structure_actual") or []):
            if isinstance(_r, dict) and str(_r.get("head", "")).strip().lower().startswith("basic"):
                if float(_r.get("amount") or 0) > 0:
                    basic = float(_r.get("amount") or 0)
                    _rt = str(_r.get("rate_type") or "").strip().lower()
                    if _rt in ("monthly", "daily", "hourly"):
                        _mode = _rt
                break
        if _mode == "daily":
            basic = round(basic * 26.0, 2)
        elif _mode == "hourly":
            basic = round(basic * 8.0 * 26.0, 2)
        if gross <= 0 and basic > 0:
            gross = basic
        if basic <= 0 and gross > 0:
            basic = round(gross * float(policy.get("basic_percent_of_gross") or 50.0) / 100.0, 2)

        eligibility_cap = float(policy.get("eligibility_cap") or 21000.0)
        wage_ceiling = float(policy.get("wage_ceiling") or 7000.0)
        rate = float(policy.get("rate_percent") or 8.33)

        # Not eligible if Basic+DA exceeds cap (we treat basic == Basic+DA proxy)
        eligible = basic <= eligibility_cap
        bonus_wage_base = min(basic, wage_ceiling)
        bonus_amount = round(bonus_wage_base * (rate / 100.0) * months_worked, 2) if eligible else 0.0

        rows.append({
            "user_id": e.get("user_id"),
            "employee_code": e.get("employee_code") or "",
            "name": e.get("name") or "",
            "doj": e.get("doj") or "",
            "exit_date": e.get("exit_date") or "",
            "gross_monthly": gross,
            "basic_monthly": basic,
            "months_worked": months_worked,
            "eligible": eligible,
            "wage_base_used": bonus_wage_base,
            "rate_percent": rate,
            "bonus_amount": bonus_amount,
        })

    total_bonus = round(sum(r["bonus_amount"] for r in rows), 2)
    eligible_count = sum(1 for r in rows if r["eligible"])

    return {
        "company_id": company_id,
        "company_name": company.get("name"),
        "fy_start_year": fy_start_year,
        "fy_label": fy_label,
        "date_from": date_from,
        "date_to": date_to,
        "group_id": group_id or None,
        "group_name": grp_name or None,
        "policy_used": policy,
        "rows": rows,
        "total_employees": len(rows),
        "eligible_count": eligible_count,
        "total_bonus": total_bonus,
    }


@api.post("/admin/bonus-runs/preview")
async def preview_bonus_run(
    payload: BonusRunRequest, authorization: Optional[str] = Header(None),
):
    """Compute bonus for a company + FY without persisting."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    return await _compute_bonus_run(
        payload.company_id, payload.fy_start_year, payload.group_id, admin
    )


@api.post("/admin/bonus-runs")
async def create_bonus_run(
    payload: BonusRunRequest, authorization: Optional[str] = Header(None),
):
    """Compute + persist a bonus run so it can be referenced/downloaded later."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    result = await _compute_bonus_run(
        payload.company_id, payload.fy_start_year, payload.group_id, admin
    )
    run_id = f"br_{uuid.uuid4().hex[:12]}"
    doc = {
        "run_id": run_id,
        "created_at": now_iso(),
        "created_by": admin["user_id"],
        **result,
    }
    await db.bonus_runs.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.get("/admin/bonus-runs")
async def list_bonus_runs(
    company_id: Optional[str] = None,
    company_ids: Optional[List[str]] = Query(
        None, description="Cross-firm filter. Ignored for company_admin."
    ),
    fy_start_year: Optional[int] = None,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    q: Dict[str, Any] = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif company_ids:
        cleaned = [c for c in company_ids if c]
        if cleaned:
            q["company_id"] = {"$in": cleaned}
    elif company_id:
        q["company_id"] = company_id
    if fy_start_year is not None:
        q["fy_start_year"] = int(fy_start_year)
    items = await db.bonus_runs.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    # Strip rows for listing view
    for it in items:
        it.pop("rows", None)
    return {"items": items}


@api.get("/admin/bonus-runs/{run_id}")
async def get_bonus_run(run_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    run = await db.bonus_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Bonus run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised")
    return run


@api.get("/admin/bonus-runs/{run_id}/report.xlsx")
async def download_bonus_report(
    run_id: str, authorization: Optional[str] = Header(None),
):
    """Download the Bonus Report as XLSX."""
    from fastapi.responses import Response
    from openpyxl import Workbook
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    run = await db.bonus_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Bonus run not found")
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not authorised")

    wb = Workbook()
    ws = wb.active
    ws.title = f"Bonus {run.get('fy_label') or ''}"[:30] or "Bonus"

    ws.append([f"Statutory Bonus — {run.get('company_name') or ''}"])
    ws.append([f"Financial Year: FY {run.get('fy_label') or ''}"])
    ws.append([f"Period: {run.get('date_from')} → {run.get('date_to')}"])
    if run.get("group_name"):
        ws.append([f"Employee Group: {run.get('group_name')}"])
    policy = run.get("policy_used") or {}
    ws.append([
        f"Rate {policy.get('rate_percent')}%  ·  Wage ceiling ₹{policy.get('wage_ceiling')}  ·  Eligibility cap ₹{policy.get('eligibility_cap')}"
    ])
    ws.append([])

    headers = [
        "Emp Code", "Name", "DOJ", "Exit Date",
        "Gross (Monthly)", "Basic (Monthly)", "Months Worked",
        "Eligible", "Wage Base Used", "Rate %", "Bonus (₹)",
    ]
    ws.append(headers)
    for r in run.get("rows") or []:
        ws.append([
            r.get("employee_code"), r.get("name"),
            r.get("doj"), r.get("exit_date"),
            r.get("gross_monthly"), r.get("basic_monthly"),
            r.get("months_worked"),
            "Yes" if r.get("eligible") else "No",
            r.get("wage_base_used"), r.get("rate_percent"),
            r.get("bonus_amount"),
        ])
    ws.append([])
    ws.append([
        "TOTAL", "", "", "", "", "", "", "",
        "", "", run.get("total_bonus") or 0,
    ])

    # Column widths
    widths = [12, 26, 12, 12, 14, 14, 14, 10, 14, 10, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

    import io as _io
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"BonusReport_{(run.get('company_name') or 'company').replace(' ', '_')}_FY{run.get('fy_label')}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


def _actual_salary_row_compute(row: dict, month_days: int, ot_basis: str = "basic") -> dict:
    """Apply the payroll formulas (Iter 84 + Iter 85 pt 6 — salary_mode-aware).

    Interpretation of ``basic`` varies by ``salary_mode`` on the row:

    • ``monthly`` (default) — ``basic`` is the FULL MONTHLY rate.
        Basic Salary   = basic × (p_days   / month_days)
        W.Basic Salary = basic × (p_hours) / (month_days × duty_hrs)

    • ``daily``   — ``basic`` is the DAILY rate.
        Basic Salary   = basic × p_days
        W.Basic Salary = basic × p_hours / duty_hrs

    • ``hourly``  — ``basic`` is the HOURLY rate.
        Basic Salary   = basic × p_hours
        W.Basic Salary = basic × p_hours   (same — no additional pro-rating)

    Downstream: EPF / ESI are NOT calculated here (Iter 91). They are
    FETCHED from the latest Compliance Salary run for the same month +
    firm and injected into the row; when the compliance process hasn't
    run yet both stay 0. Net = Gross − (EPF + ESI + Adv + TDS).
    """
    basic = float(row.get("basic") or 0.0)
    duty_hrs = float(row.get("duty_hrs") or 0.0)
    p_days = float(row.get("p_days") or 0.0)
    p_hours = float(row.get("p_hours") or 0.0)
    oth_allo = float(row.get("oth_allo") or 0.0)
    adv = float(row.get("adv") or 0.0)
    tds = float(row.get("tds") or 0.0)
    salary_mode = str(row.get("salary_mode") or "monthly").lower()

    md = max(1, int(month_days or 30))

    # Iter 98 — OT (W.Basic) rate basis. Firm Master → Salary Process
    # Settings → "OT Calculation On" (basic | gross). "gross" folds the
    # Other Allowances into the per-hour OT rate; "basic" (default) keeps
    # the historical behaviour.
    if str(ot_basis or "basic").lower() == "gross":
        if salary_mode == "daily":
            ot_rate = basic + (oth_allo / md)
        elif salary_mode == "hourly":
            ot_rate = basic + (oth_allo / (md * duty_hrs) if duty_hrs > 0 else 0.0)
        else:  # monthly
            ot_rate = basic + oth_allo
    else:
        ot_rate = basic

    if salary_mode == "daily":
        # basic = DAILY rate. Whole days → Basic Sal, extra hours → W.Basic.
        basic_salary = basic * p_days
        w_basic_salary = (ot_rate * p_hours / duty_hrs) if duty_hrs > 0 else 0.0
    elif salary_mode == "hourly":
        # basic = HOURLY rate. Whole days convert to hours (p_days ×
        # duty_hrs) → Basic Sal; the extra hours land in W.Basic.
        basic_salary = basic * (p_days * duty_hrs)
        w_basic_salary = ot_rate * p_hours
    else:  # monthly
        basic_salary = basic * (p_days / md) if md > 0 else 0.0
        denom_hours = md * duty_hrs
        w_basic_salary = (ot_rate * p_hours / denom_hours) if denom_hours > 0 else 0.0

    # Iter 91 — Total Gross = Basic Sal + W.Basic Sal + Oth.Allo (per user).
    # Iter 230 (user request) — manual OT AMOUNT override: when the admin
    # edits the W.Basic (OT) cell, the typed amount wins over the
    # hours-based computation until P Hours is edited again.
    if row.get("w_basic_override") is not None:
        w_basic_salary = float(row.get("w_basic_override") or 0.0)
    total_gross = basic_salary + w_basic_salary + oth_allo
    # Iter 91 — EPF/ESI come from the Compliance run (already on the row).
    epf = float(row.get("epf") or 0.0)
    esi = float(row.get("esi") or 0.0)
    net_pay = total_gross - (epf + esi + adv + tds)

    row["basic_salary"] = round(basic_salary, 2)
    row["w_basic_salary"] = round(w_basic_salary, 2)
    row["total_gross"] = round(total_gross, 2)
    row["epf"] = round(epf, 2)
    row["esi"] = round(esi, 2)
    row["net_pay"] = round(net_pay, 2)
    return row


def _actual_salary_totals(rows: list) -> dict:
    keys = (
        "basic_salary", "w_basic_salary", "total_gross",
        "epf", "esi", "adv", "tds", "net_pay",
    )
    return {k: round(sum((r.get(k) or 0.0) for r in rows), 2) for k in keys}


class ActualSalaryProcessBody(BaseModel):
    """Body for POST /api/admin/actual-salary-process."""
    month: str
    company_id: Optional[str] = None
    month_days: Optional[int] = None
    attendance_source: Literal["biometric", "manual"] = "biometric"
    employee_type: Optional[str] = None
    group_id: Optional[str] = None
    is_onroll: Optional[bool] = None


class ActualSalaryRowPatchBody(BaseModel):
    user_id: str
    basic: Optional[float] = None
    duty_hrs: Optional[float] = None
    p_days: Optional[float] = None
    p_hours: Optional[float] = None
    oth_allo: Optional[float] = None
    # Iter 230 — manual OT amount (W.Basic) override.
    w_basic: Optional[float] = None
    adv: Optional[float] = None
    tds: Optional[float] = None


@api.post("/admin/actual-salary-process")
async def create_actual_salary_process(
    payload: ActualSalaryProcessBody,
    authorization: Optional[str] = Header(None),
):
    """Compute + persist a new Actual Salary Process run."""
    from utils.salary_run import actual_days_in_month, parse_month
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    require_permission(admin, "salary_process:write")

    try:
        year, mon = parse_month(payload.month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    default_days = actual_days_in_month(year, mon)
    month_days = int(payload.month_days or default_days)
    if not (1 <= month_days <= 31):
        raise HTTPException(status_code=400, detail="month_days must be 1..31")

    # Scope
    if admin["role"] == "company_admin":
        company_id = admin.get("company_id")
    else:
        company_id = payload.company_id
    # Iter 98 — Firm Master gate: Offline Salary must be enabled for the firm.
    await _require_firm_salary_permission(company_id, "offline")

    # Iter 218 (user request) — "Count Present Day @ 8 HRS" firm gate:
    # when this Attendance Policy sub-point is ON (and Salary Allowed
    # includes Compliance), ON-ROLL employees are paid via the Compliance
    # Salary Process ONLY (attendance direct-syncs there @ 8 HRS = 1 day).
    # The Actual Salary Process is limited to OFF-ROLL employees.
    _firm_ap_a: dict = {}
    if company_id:
        _cdoc_a = await db.companies.find_one(
            {"company_id": company_id}, {"_id": 0, "attendance_policy": 1})
        _firm_ap_a = (_cdoc_a or {}).get("attendance_policy") or {}
    _c8_active = bool(
        (_firm_ap_a.get("policy_master") or {}).get("compliance_present_8hr")
        and (_firm_ap_a.get("salary_allowed") or "both") in ("compliance", "both")
    )
    if _c8_active and payload.is_onroll is True:
        raise HTTPException(
            status_code=400,
            detail="\"Count Present Day @ 8 HRS\" is ON in this firm's Attendance "
                   "Policy — On-roll employees are paid via the Compliance Salary "
                   "Process only (attendance syncs there directly). The Actual "
                   "Salary Process is allowed for Off-roll employees only.",
        )
    # Iter 129f (user directive) — a FINALIZED month can never be processed
    # again. Unlock (de-finalize) the run first.
    _fin_q: Dict[str, Any] = {"month": payload.month, "finalized": True}
    if company_id:
        _fin_q["company_id"] = company_id
    if await db.salary_runs.find_one(_fin_q, {"_id": 1}):
        raise HTTPException(
            status_code=409,
            detail="This month's Actual salary is already FINALIZED for this firm — "
                   "it cannot be processed again. Unlock (de-finalize) it first.",
        )

    # Iter 98 — OT calculation basis (basic | gross) from Firm Master →
    # Salary Process Settings. Stored on the run so row edits re-compute
    # with the same basis.
    _ot_basis = "basic"
    if company_id:
        _fm_sp = await db.firm_masters.find_one(
            {"company_id": company_id}, {"_id": 0, "salary_process": 1},
        )
        _ot_basis = str(
            ((_fm_sp or {}).get("salary_process") or {}).get("ot_calc_basis")
            or "basic"
        ).lower()

    q: dict = {"role": "employee"}
    if company_id:
        q["company_id"] = company_id
    if payload.employee_type is not None:
        et = payload.employee_type.strip()
        if et.lower() == "unset":
            q["$or"] = [
                {"employee_type": {"$exists": False}},
                {"employee_type": None},
                {"employee_type": ""},
            ]
        elif et and et.lower() != "all":
            title = et.title()
            q["employee_type"] = {"$in": [title, et, et.lower(), et.upper()]}
    if payload.is_onroll is not None:
        if payload.is_onroll:
            q.setdefault("$and", []).append({
                "$or": [
                    {"is_onroll": True},
                    {"is_onroll": {"$exists": False}},
                    {"is_onroll": None},
                ]
            })
        else:
            q["is_onroll"] = False

    employees = await db.users.find(
        q, {"_id": 0}
    ).sort([("employee_code", 1), ("name", 1)]).to_list(4000)
    employees = [e for e in employees if not _month_is_before_doj(e, payload.month)
                 and not _month_is_after_exit(e, payload.month)
                 and e.get("disabled") is not True]  # Iter 166/168

    # Iter 85 — Exclude resigned/left employees. An employee whose
    # ``exit_date`` is on or before the LAST day of the run month has
    # already left the company and must not appear in the Actual Salary
    # Process (matches the semantics of the offboarded flow).
    def _still_active(u: dict) -> bool:
        ed = u.get("exit_date")
        if not ed:
            return True
        try:
            return str(ed) > f"{year:04d}-{mon:02d}-{default_days:02d}"
        except Exception:
            return True
    employees = [e for e in employees if _still_active(e)]

    # Iter 218 — 8-HR compliance-counting firms: Actual Salary Process
    # excludes ON-ROLL employees (they are paid via Compliance only).
    if _c8_active:
        employees = [e for e in employees if e.get("is_onroll") is False]
        if not employees:
            raise HTTPException(
                status_code=400,
                detail="\"Count Present Day @ 8 HRS\" is ON in this firm's "
                       "Attendance Policy — On-roll employees are paid via the "
                       "Compliance Salary Process only. No Off-roll employees "
                       "matched this filter for the Actual Salary Process.",
            )

    # Group filter (optional)
    if payload.group_id:
        grp_uids = await _resolve_group_employee_ids(company_id or "", payload.group_id)
        if grp_uids is not None:
            employees = [e for e in employees if e.get("user_id") in set(grp_uids)]

    # Biometric grid data (P Days + P Hours) — only if source=biometric
    grid_by_user: Dict[str, Any] = {}
    if payload.attendance_source == "biometric" and company_id:
        try:
            grid = await _compute_monthly_grid_data(
                company_id, payload.month, group_id=payload.group_id
            )
            # NOTE: the grid compute returns its rows under "employees".
            for gr in grid.get("employees") or grid.get("rows") or []:
                grid_by_user[gr["user_id"]] = gr
        except HTTPException:
            grid_by_user = {}

    # Iter 91 — PF / ESI are FETCHED from the latest Compliance Salary run
    # for the same month + firm (not calculated here). If the compliance
    # process hasn't run yet, both stay 0.
    compliance_by_user: Dict[str, Any] = {}
    if company_id:
        comp_run = await db.compliance_salary_runs.find_one(
            {"month": payload.month, "company_id": company_id},
            {"_id": 0, "rows": 1},
            sort=[("generated_at", -1)],
        )
        for cr in ((comp_run or {}).get("rows") or []):
            compliance_by_user[cr.get("user_id")] = {
                "epf": float(cr.get("pf_employee") or 0.0),
                "esi": float(cr.get("esic_employee") or 0.0),
            }

    # Iter 94 — Additional Duty AMOUNTS (Punch Approvals → Extra Duty).
    # Month's per-day ₹ grants are summed into the Oth.Allo column.
    extra_amt_by_user: Dict[str, float] = {}
    if company_id:
        _xd_rows = await db.extra_duty_entries.find(
            {"company_id": company_id,
             "date": {"$gte": f"{payload.month}-01", "$lte": f"{payload.month}-31"}},
            {"_id": 0, "user_id": 1, "extra_amount": 1},
        ).to_list(10000)
        for en in _xd_rows:
            amt = float(en.get("extra_amount") or 0.0)
            if amt > 0:
                extra_amt_by_user[en["user_id"]] = extra_amt_by_user.get(en["user_id"], 0.0) + amt

    # Iter 217 (user request) — Duty HRS = the EMPLOYEE MASTER's per-day
    # Daily Working HRS. Same resolution as the Attendance Report grid:
    # employee override → assigned shift's length → firm policy → 8.
    # (``_firm_ap_a`` was loaded above for the Iter 218 8-HR gate.)
    _shifts_by_id_a, _ = await load_shift_masters_map()
    _firm_daily_a = float(
        _firm_ap_a.get("standard_working_hours")
        or _firm_ap_a.get("full_day_hours")
        or 8.0
    )

    rows: List[dict] = []
    for emp in employees:
        pol = emp.get("employee_policy") or {}
        # Iter 217 — Duty HRS from the Employee Master (attendance policy
        # override), falling back to the assigned shift, then the firm.
        _ov_ap = emp.get("attendance_policy_override") or {}
        emp_daily_hrs = float(_ov_ap.get("standard_working_hours") or 0)
        if emp_daily_hrs <= 0:
            _sh_a = _shifts_by_id_a.get(_ov_ap.get("shift_id")) if _ov_ap.get("shift_id") else None
            _sh_hrs_a = _shift_duration_hours(_sh_a) if _sh_a else None
            emp_daily_hrs = float(_sh_hrs_a or _firm_daily_a or 8.0)
        basic = float(emp.get("salary_monthly") or pol.get("salary") or 0.0)
        emp_salary_mode = emp.get("salary_mode") or "monthly"
        # Iter 91 — Basic Salary comes from the UPDATED Employee Master
        # (Salary Update modal) when a Basic row exists: its amount and
        # rate basis (monthly / daily / hourly) override salary_monthly.
        _struct = [r for r in (emp.get("salary_structure_actual") or []) if isinstance(r, dict)]
        _basic_row = next(
            (r for r in _struct
             if str(r.get("head", "")).strip().lower().startswith("basic")),
            None,
        )
        if _basic_row and float(_basic_row.get("amount") or 0.0) > 0:
            basic = float(_basic_row.get("amount") or 0.0)
            _rt = str(_basic_row.get("rate_type") or "").strip().lower()
            if _rt in ("monthly", "daily", "hourly"):
                emp_salary_mode = _rt
        # Master allowances pre-fill the Oth.Allo column.
        _allow_total = sum(
            float(r.get("amount") or 0.0)
            for r in (emp.get("actual_salary_allowances") or [])
            if isinstance(r, dict)
        )

        p_days = 0.0
        p_hours = 0.0
        if payload.attendance_source == "biometric":
            g = grid_by_user.get(emp["user_id"]) or {}
            t = g.get("totals") or {}
            # Iter 85 — Per user request: P Days = whole-day count
            # (total_days_int), P Hours = remainder (total_extra_hrs).
            # Iter 216 — prefer the report's "Present Days"
            # (present_days_policy) so half-days (26.5) are kept in
            # per-day policy mode; division mode values are identical.
            # Falls back to legacy present_days / hours when the newer
            # split fields are missing.
            _pd_pref = t.get("present_days_policy")
            if _pd_pref is None:
                _pd_pref = t.get("total_days_computed")
            if _pd_pref is None:
                _pd_pref = t.get("total_days_int")
            p_days = float(_pd_pref if _pd_pref is not None else t.get("present_days") or 0.0)
            p_hours = float(t.get("total_extra_hrs") if t.get("total_extra_hrs") is not None else t.get("hours") or 0.0)

        # Iter 85 — DOJ / Exit-date working-days cap. If the employee
        # joined mid-month or resigned mid-month, cap the maximum
        # allowable P Days to only the days they were actually on the
        # rolls that month. This runs regardless of attendance source
        # (biometric or manual) so admins can't accidentally overpay.
        max_days = month_days
        doj = str(emp.get("doj") or "")
        exit_date = str(emp.get("exit_date") or "")
        month_start = f"{year:04d}-{mon:02d}-01"
        month_end = f"{year:04d}-{mon:02d}-{default_days:02d}"
        try:
            if doj and month_start <= doj <= month_end:
                # DOJ in current month → available days = month_days - DOJ.day + 1
                doj_day = int(doj.split("-")[2])
                max_days = min(max_days, month_days - doj_day + 1)
            if exit_date and month_start <= exit_date <= month_end:
                # Exit in current month → available days = exit.day
                exit_day = int(exit_date.split("-")[2])
                max_days = min(max_days, exit_day)
        except (ValueError, IndexError):
            pass  # invalid date format — fall back to full month_days
        max_days = max(0, max_days)
        p_days = min(p_days, float(max_days))
        # Iter 93 — P Days only in half-day steps (.0 or .5), no other decimals.
        p_days = round(p_days * 2) / 2

        row = {
            "user_id": emp["user_id"],
            "employee_code": emp.get("employee_code"),
            "name": emp.get("name"),
            "father_name": emp.get("father_name"),
            "designation": emp.get("designation"),
            "department": emp.get("department"),
            "employee_type": emp.get("employee_type"),
            "doj": emp.get("doj"),
            "exit_date": emp.get("exit_date"),
            "is_onroll": bool(emp.get("is_onroll", True)),
            "salary_mode": emp_salary_mode,
            "duty_hrs": round(emp_daily_hrs, 2),
            "basic": round(basic, 2),
            "p_days": round(p_days, 2),
            "p_hours": round(p_hours, 2),
            # Iter 85 — Persist the DOJ/exit-derived cap so the frontend
            # can enforce the same limit when admins edit rows inline.
            "max_p_days": int(max_days),
            "oth_allo": round(_allow_total + extra_amt_by_user.get(emp["user_id"], 0.0), 2),
            "adv": 0.0,
            "tds": 0.0,
            # Iter 91 — injected from the compliance run (0 if not processed)
            "epf": (compliance_by_user.get(emp["user_id"]) or {}).get("epf", 0.0),
            "esi": (compliance_by_user.get(emp["user_id"]) or {}).get("esi", 0.0),
        }
        rows.append(_actual_salary_row_compute(row, month_days, ot_basis=_ot_basis))

    # Advance Management — auto-deduct active advance EMIs / single-shot
    # recoveries into rows BEFORE totals (idempotent per month+process).
    _actual_run_id = f"asal_{uuid.uuid4().hex[:12]}"
    from routes.advances import apply_advance_recovery
    await apply_advance_recovery(company_id, payload.month, "actual", _actual_run_id, rows)

    totals = _actual_salary_totals(rows)

    run = {
        "run_id": _actual_run_id,
        "run_type": "actual",
        "month": payload.month,
        "year": year,
        "month_number": mon,
        "month_days": month_days,
        "default_month_days": default_days,
        "attendance_source": payload.attendance_source,
        "company_id": company_id,
        "employee_type": payload.employee_type,
        "is_onroll_filter": payload.is_onroll,
        "group_id": payload.group_id,
        "rows": rows,
        "totals": totals,
        "employees_count": len(rows),
        "finalized": False,
        "ot_calc_basis": _ot_basis,
        "generated_by": admin["user_id"],
        "generated_at": now_iso(),
    }
    await db.salary_runs.insert_one(run)

    # Live sync so the "Past Runs" list refreshes.
    try:
        from utils.ws_broker import broker as _ws
        await _ws.broadcast_firm(company_id or "", {
            "type": "salary.run.created",
            "run_id": run["run_id"],
            "month": run["month"],
            "run_type": "actual",
            "employees_count": run["employees_count"],
        })
    except Exception:
        pass

    return {"ok": True, "run": {k: v for k, v in run.items() if k != "_id"}}


@api.patch("/admin/actual-salary-process/{run_id}/row")
async def patch_actual_salary_row(
    run_id: str,
    body: ActualSalaryRowPatchBody,
    authorization: Optional[str] = Header(None),
):
    """Inline-edit a single row (auto-save). Iter 85 (P Days unlock):
    P Days & P Hours are now ALWAYS editable regardless of the run's
    ``attendance_source``. Biometric-derived values are simply the
    initial defaults — admins can override any row inline until the
    run is finalized. The DOJ / exit-date cap still caps p_days."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    require_permission(admin, "salary_process:write")

    run = await db.salary_runs.find_one(
        {"run_id": run_id, "run_type": "actual"}, {"_id": 0}
    )
    if not run:
        raise HTTPException(status_code=404, detail="Actual salary run not found")
    if run.get("finalized"):
        raise HTTPException(status_code=409, detail="Run is finalized and read-only")

    # Company admin can only touch their own firm's run.
    if admin["role"] == "company_admin" and run.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Cross-company edit blocked")

    rows = list(run.get("rows") or [])
    # Iter 85 — src_lock removed. P Days & P Hours are always editable
    # (see body-parse block below).
    idx = next((i for i, r in enumerate(rows) if r.get("user_id") == body.user_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Employee row not found in run")
    row = dict(rows[idx])

    # Iter 217 (user request) — Basic Salary is NOT editable in the Actual
    # Salary Process; it is always fetched from the Employee Master's
    # Actual Salary (Basic row). ``basic`` was removed from the PATCH body.
    if body.duty_hrs is not None:
        row["duty_hrs"] = float(body.duty_hrs)
    if body.oth_allo is not None:
        row["oth_allo"] = float(body.oth_allo)
    # Iter 230 (user request) — OT amount (W.Basic) manual override.
    if body.w_basic is not None:
        row["w_basic_override"] = float(body.w_basic)
    if body.adv is not None:
        row["adv"] = float(body.adv)
    if body.tds is not None:
        row["tds"] = float(body.tds)
    # Iter 85 — P Days & P Hours are now ALWAYS editable regardless of
    # the run's attendance source. Biometric-derived values are just the
    # initial defaults; admins can override any row inline. The DOJ /
    # exit-date cap stored on the row still limits the maximum.
    if body.p_days is not None:
        cap = float(row.get("max_p_days") or run.get("month_days") or 31)
        row["p_days"] = min(float(body.p_days), cap)
    if body.p_hours is not None:
        row["p_hours"] = float(body.p_hours)
        # editing hours re-enables the hours-based OT computation
        row.pop("w_basic_override", None)

    row = _actual_salary_row_compute(
        row, int(run.get("month_days") or 30),
        ot_basis=str(run.get("ot_calc_basis") or "basic"),
    )
    rows[idx] = row

    totals = _actual_salary_totals(rows)
    await db.salary_runs.update_one(
        {"run_id": run_id},
        {"$set": {
            "rows": rows,
            "totals": totals,
            "updated_at": now_iso(),
            "updated_by": admin["user_id"],
        }},
    )
    return {"ok": True, "row": row, "totals": totals}


@api.post("/admin/actual-salary-process/{run_id}/finalize")
async def finalize_actual_salary_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
):
    """Freeze the run — subsequent PATCH calls return 409."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    require_permission(admin, "salary_process:write")

    existing = await db.salary_runs.find_one(
        {"run_id": run_id, "run_type": "actual"}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Actual salary run not found")
    if admin["role"] == "company_admin" and existing.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Cross-company action blocked")

    await db.salary_runs.update_one(
        {"run_id": run_id},
        {"$set": {
            "finalized": True,
            "finalized_at": now_iso(),
            "finalized_by": admin["user_id"],
        }},
    )
    # Iter 103 — automated email trigger
    try:
        from routes.email_notifications import fire_email_event
        await fire_email_event("salary_finalized", company_id=existing.get("company_id"),
                               details=f"Actual Salary {existing.get('month')}")
    except Exception:
        pass
    return {"ok": True}


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



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
        if raw and len(raw) < 200_000:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    cid = cid or data.get("company_id")
                    parts = []
                    for k, v in data.items():
                        if any(s in k.lower() for s in _ACT_SENSITIVE):
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
        await db.activity_log.insert_one({
            "at": now_iso(),
            "actor_id": (actor or {}).get("user_id"),
            "actor_name": (actor or {}).get("name"),
            "actor_role": (actor or {}).get("role"),
            "company_id": cid or (actor or {}).get("company_id"),
            "method": method,
            "path": path[:300],
            "action": f"{verb} {path[4:][:200]}",
            "status": response.status_code,
            "details": summary[:400],
            "ip": ((request.headers.get("x-forwarded-for")
                    or (request.client.host if request.client else "") or "")
                   .split(",")[0].strip()),
        })
    except Exception:
        logger.warning("[activity-log] failed to record", exc_info=True)
    return response


# Iter 85 (fix) — register the API router LAST so every @api.* decorator
# defined anywhere in this module gets attached to the FastAPI app.
app.include_router(api)


# Iter 86 — Modularization: include extracted route modules AFTER the
# monolithic `api` router.  Each `routes/*.py` module declares its own
# `APIRouter(prefix="/api")` and pulls shared helpers (`db`,
# `get_user_from_token`, `require_role`) from this file by name — safe
# because those names are already bound by the time we get here.
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
from routes.portal_generation import router as portal_generation_router  # noqa: E402
from routes.employee_salary import router as employee_salary_router  # noqa: E402
from routes.master_data_report import router as master_data_report_router  # noqa: E402
from routes.employee_profile import router as employee_profile_router  # noqa: E402
from routes.compliance_reports import router as compliance_reports_router  # noqa: E402
from routes.employee_kyc import router as employee_kyc_router  # noqa: E402
from routes.ocr import router as ocr_router  # noqa: E402
from routes.challans import router as challans_router  # noqa: E402
from routes.biometric_devices import router as biometric_devices_router  # noqa: E402
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


from utils.rpa_worker import maybe_start as maybe_start_rpa_worker  # noqa: E402

app.include_router(reports_extra_router)
app.include_router(tickets_router)
app.include_router(notifications_router)
app.include_router(gmail_mailbox_router)
app.include_router(attendance_master_router)
app.include_router(leaves_router)
app.include_router(payslips_router)
app.include_router(attendance_policy_router)
app.include_router(compliance_docs_router)
app.include_router(shift_masters_router)
app.include_router(messages_router)
app.include_router(firm_master_router)
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
from routes.portal_rpa import router as portal_rpa_router  # noqa: E402
app.include_router(portal_rpa_router)
from routes.uan_esic_import import router as uan_esic_import_router  # noqa: E402
app.include_router(uan_esic_import_router)
app.include_router(compliance_settings_router)
from routes.report_formats import router as report_formats_router  # noqa: E402
app.include_router(report_formats_router)
from routes.punch_import import router as punch_import_router  # noqa: E402
app.include_router(punch_import_router)
from routes.contractor_punches import router as contractor_punches_router  # noqa: E402
app.include_router(contractor_punches_router)
from routes.labour_reports import router as labour_reports_router  # noqa: E402
app.include_router(labour_reports_router)
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

# Iter 89 — Optional background RPA worker for EPFO/ESIC UAN/ESIC
# generation jobs. No-op unless RPA_WORKER_ENABLED=1 in backend/.env.
maybe_start_rpa_worker(app, db)


@app.on_event("shutdown")
async def shutdown():
    client.close()
