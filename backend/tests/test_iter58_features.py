"""Backend tests for Iteration 58 — Payslip DOJ/month-complete rules,
Portal Credentials, Employer Access Rights, Master Sheet Automation, and
sub-admin permission enforcement on /admin/salary-runs.

Runs against the public preview URL (EXPO_PUBLIC_BACKEND_URL). Uses OTP
dev-mode for super admin login and PIN/password login for company_admin.
"""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timezone

import openpyxl
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL / EXPO_BACKEND_URL must be set"
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _otp_login(identifier: str, channel: str = "email") -> str:
    r = requests.post(f"{API}/auth/otp/request", json={"identifier": identifier, "channel": channel}, timeout=30)
    r.raise_for_status()
    code = r.json().get("dev_code") or r.json().get("code")
    assert code, f"No dev OTP code: {r.text}"
    r2 = requests.post(
        f"{API}/auth/otp/verify",
        json={"identifier": identifier, "channel": channel, "code": code},
        timeout=30,
    )
    r2.raise_for_status()
    j = r2.json()
    tok = j.get("token") or j.get("access_token") or j.get("session_token")
    assert tok, f"No token: {r2.text}"
    return tok


def _password_login(email: str, password: str) -> tuple[str, dict]:
    r = requests.post(
        f"{API}/auth/admin-password-login",
        json={"email": email, "password": password},
        timeout=30,
    )
    r.raise_for_status()
    j = r.json()
    return j["session_token"], j.get("user") or {}


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def super_token() -> str:
    return _otp_login("sksharmaconsultancy@gmail.com", "email")


@pytest.fixture(scope="module")
def super_headers(super_token: str) -> dict:
    return _hdr(super_token)


@pytest.fixture(scope="module")
def sksco_company_id(super_headers) -> str:
    r = requests.get(f"{API}/companies", headers=super_headers, timeout=30)
    r.raise_for_status()
    d = r.json()
    comps = d if isinstance(d, list) else d.get("companies") or d.get("items") or []
    for c in comps:
        if (c.get("company_code") or c.get("code") or "").upper() == "SKSCO1":
            return c["company_id"]
    return comps[0]["company_id"]


@pytest.fixture(scope="module")
def second_company_id(super_headers, sksco_company_id) -> str:
    """Return a *different* company id (for cross-company auth checks)."""
    r = requests.get(f"{API}/companies", headers=super_headers, timeout=30)
    r.raise_for_status()
    d = r.json()
    comps = d if isinstance(d, list) else d.get("companies") or d.get("items") or []
    for c in comps:
        if c.get("company_id") != sksco_company_id:
            return c["company_id"]
    pytest.skip("Need at least 2 companies for cross-company auth test")


@pytest.fixture(scope="module")
def sksco_employees(super_headers, sksco_company_id) -> list:
    r = requests.get(
        f"{API}/admin/employees",
        headers=super_headers,
        params={"company_id": sksco_company_id},
        timeout=30,
    )
    r.raise_for_status()
    d = r.json()
    users = d if isinstance(d, list) else d.get("employees") or d.get("users") or d.get("items") or []
    return [u for u in users if u.get("role") == "employee" and u.get("company_id") == sksco_company_id]


@pytest.fixture(scope="module")
def sksco_admin_token(super_headers, sksco_company_id) -> str:
    """Log in as the S.K. Sharma & Co. company_admin via email+password."""
    tok, user = _password_login("admin.skscoltd@sksharma.local", "zmwy4249")
    # If password already changed, this test will need to skip password
    # login and use PIN — for now assume dev-mode temp password still valid.
    assert user.get("role") in ("company_admin", "super_admin"), user
    return tok


# =============================================================================
# 1) PAYSLIP DOJ RULE
# =============================================================================
class TestPayslipDojRule:
    def test_pre_doj_employee_excluded_from_salary_run(
        self, super_headers, sksco_company_id, sksco_employees
    ):
        if not sksco_employees:
            pytest.skip("No employees in target company")
        emp = sksco_employees[0]
        original_doj = emp.get("doj")

        # Patch DOJ far in the future via /admin/user-role
        r = requests.patch(
            f"{API}/admin/user-role",
            headers=super_headers,
            json={"user_id": emp["user_id"], "doj": "2027-01-01"},
            timeout=30,
        )
        assert r.status_code in (200, 204), r.text

        try:
            r = requests.post(
                f"{API}/admin/salary-runs",
                headers=super_headers,
                json={"company_id": sksco_company_id, "month": "2026-12"},
                timeout=60,
            )
            assert r.status_code == 200, r.text
            run = r.json().get("run") or {}
            row_ids = {row.get("employee_user_id") or row.get("user_id") for row in (run.get("rows") or [])}
            assert emp["user_id"] not in row_ids, "pre-DOJ employee wrongly included in run.rows"
        finally:
            if original_doj:
                requests.patch(
                    f"{API}/admin/user-role",
                    headers=super_headers,
                    json={"user_id": emp["user_id"], "doj": original_doj},
                    timeout=30,
                )


# =============================================================================
# 2) MONTH-COMPLETE + PROCESSED-ONLY RULE
# =============================================================================
class TestPayslipMonthCompleteAndProcessed:
    def test_current_month_slip_not_returned_and_pending_hidden(
        self, super_headers, sksco_employees
    ):
        if not sksco_employees:
            pytest.skip("No employees in target company")
        # Pick a fresh test employee via OTP login (avoid super_admin token)
        target = sksco_employees[0]

        now = datetime.now(timezone.utc)
        current_month = f"{now.year}-{now.month:02d}"
        y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        past_month = f"{y}-{m:02d}"

        # Seed: create a paid current-month slip and a paid past-month slip
        for mo in (current_month, past_month):
            r = requests.post(
                f"{API}/payslips",
                headers=super_headers,
                json={
                    "employee_user_id": target["user_id"],
                    "month": mo,
                    "gross": 20000,
                    "deductions": 0,
                    "net": 20000,
                },
                timeout=30,
            )
            assert r.status_code == 200, r.text

        # Seed a pending slip for another past month directly is not exposed,
        # so we rely on /salary/monthly to auto-create pending slips and
        # confirm they are filtered out.
        emp_tok = _otp_login(target.get("email") or f"seed_{uuid.uuid4().hex[:6]}@t.co", "email") \
            if target.get("email") else None
        if not emp_tok:
            # Use super admin — but /payslips uses user_id from token, so we
            # cannot fetch that employee's list without their token.
            pytest.skip("Employee has no email — cannot login via OTP")

        r = requests.get(f"{API}/payslips", headers=_hdr(emp_tok), timeout=30)
        assert r.status_code == 200, r.text
        slips = r.json().get("payslips") or []
        months_returned = {s["month"] for s in slips}
        assert current_month not in months_returned, "current-month slip must NOT be returned"
        # past_month may or may not be present depending on how far back it is
        # but if it's present, it must be status=paid (not pending)
        for s in slips:
            assert s.get("status") == "paid", f"non-paid slip surfaced: {s}"


# =============================================================================
# 3) GENERATE-PAYSLIPS SAFETY
# =============================================================================
class TestGeneratePayslipsSafety:
    def test_generate_payslips_returns_skipped_pre_doj(
        self, super_headers, sksco_company_id, sksco_employees
    ):
        if not sksco_employees:
            pytest.skip("No employees available")
        emp = sksco_employees[0]
        original_doj = emp.get("doj")

        # Set DOJ before the run month, create run, then set DOJ AFTER the
        # month so generate-payslips detects a pre-DOJ row.
        requests.patch(
            f"{API}/admin/user-role",
            headers=super_headers,
            json={"user_id": emp["user_id"], "doj": "2020-01-01"},
            timeout=30,
        )
        r = requests.post(
            f"{API}/admin/salary-runs",
            headers=super_headers,
            json={"company_id": sksco_company_id, "month": "2026-11"},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        run = r.json().get("run") or {}
        run_id = run.get("run_id")
        assert run_id

        # Now flip DOJ so it's after the run month
        requests.patch(
            f"{API}/admin/user-role",
            headers=super_headers,
            json={"user_id": emp["user_id"], "doj": "2027-06-01"},
            timeout=30,
        )
        try:
            r = requests.post(
                f"{API}/admin/salary-runs/{run_id}/generate-payslips",
                headers=super_headers,
                timeout=60,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert "payslips_count" in body
            assert "skipped_pre_doj" in body
            assert body["skipped_pre_doj"] >= 1, body
        finally:
            if original_doj:
                requests.patch(
                    f"{API}/admin/user-role",
                    headers=super_headers,
                    json={"user_id": emp["user_id"], "doj": original_doj},
                    timeout=30,
                )


# =============================================================================
# 4) PORTAL CREDENTIALS
# =============================================================================
class TestPortalCredentials:
    def test_patch_and_get_hides_plaintext(self, super_headers, sksco_company_id):
        r = requests.patch(
            f"{API}/admin/companies/{sksco_company_id}/portal-credentials",
            headers=super_headers,
            json={"portal": "epfo", "username": "testuser", "password": "secret123"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert "secret123" not in r.text, "plaintext leaked in PATCH response"

        r = requests.get(
            f"{API}/admin/companies/{sksco_company_id}/portal-credentials",
            headers=super_headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "secret123" not in r.text, "plaintext leaked in GET response"
        epfo = (body.get("portals") or {}).get("epfo") or {}
        assert epfo.get("has_password") is True, epfo
        assert epfo.get("username") == "testuser", epfo

    def test_clear_password_removes_has_password_flag(self, super_headers, sksco_company_id):
        r = requests.patch(
            f"{API}/admin/companies/{sksco_company_id}/portal-credentials",
            headers=super_headers,
            json={"portal": "epfo", "clear_password": True},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        r = requests.get(
            f"{API}/admin/companies/{sksco_company_id}/portal-credentials",
            headers=super_headers,
            timeout=30,
        )
        assert r.status_code == 200
        epfo = (r.json().get("portals") or {}).get("epfo") or {}
        assert epfo.get("has_password") is False, epfo

    def test_cross_company_admin_denied(
        self, sksco_admin_token, second_company_id
    ):
        r = requests.get(
            f"{API}/admin/companies/{second_company_id}/portal-credentials",
            headers=_hdr(sksco_admin_token),
            timeout=30,
        )
        assert r.status_code == 403, r.text


# =============================================================================
# 5) EMPLOYER ACCESS RIGHTS
# =============================================================================
class TestEmployerAccessRights:
    def test_permission_keys_list(self, super_headers):
        r = requests.get(f"{API}/admin/employer-permission-keys", headers=super_headers, timeout=30)
        assert r.status_code == 200, r.text
        perms = r.json().get("permissions") or []
        assert isinstance(perms, list) and perms, perms
        # Spot-check a few expected keys
        for k in ("employees:read", "employees:write", "portal_credentials:read"):
            assert k in perms, f"missing canonical key {k}"

    def test_get_defaults_all_features_enabled(self, super_headers, second_company_id):
        # Ensure any leftover state is wiped
        requests.patch(
            f"{API}/admin/companies/{second_company_id}/access-rights",
            headers=super_headers, json={"permissions": None}, timeout=30,
        )
        r = requests.get(
            f"{API}/admin/companies/{second_company_id}/access-rights",
            headers=super_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("permissions") == []
        assert body.get("all_features_enabled") is True

    def test_patch_and_authme_reflects_permissions(
        self, super_headers, sksco_company_id, sksco_admin_token
    ):
        try:
            r = requests.patch(
                f"{API}/admin/companies/{sksco_company_id}/access-rights",
                headers=super_headers,
                json={"permissions": ["employees:read", "employees:write"]},
                timeout=30,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert sorted(body.get("permissions") or []) == ["employees:read", "employees:write"]

            # Reload as company_admin and check /auth/me
            r = requests.get(f"{API}/auth/me", headers=_hdr(sksco_admin_token), timeout=30)
            assert r.status_code == 200, r.text
            me = r.json()
            emp_perms = me.get("employer_permissions") or (me.get("user") or {}).get("employer_permissions")
            assert sorted(emp_perms or []) == ["employees:read", "employees:write"], me
        finally:
            # Reset
            requests.patch(
                f"{API}/admin/companies/{sksco_company_id}/access-rights",
                headers=super_headers, json={"permissions": None}, timeout=30,
            )

    def test_reset_via_null(self, super_headers, sksco_company_id):
        # First set some, then null it
        requests.patch(
            f"{API}/admin/companies/{sksco_company_id}/access-rights",
            headers=super_headers, json={"permissions": ["messages:read"]}, timeout=30,
        )
        r = requests.patch(
            f"{API}/admin/companies/{sksco_company_id}/access-rights",
            headers=super_headers, json={"permissions": None}, timeout=30,
        )
        assert r.status_code == 200
        r = requests.get(
            f"{API}/admin/companies/{sksco_company_id}/access-rights",
            headers=super_headers, timeout=30,
        )
        body = r.json()
        assert body.get("all_features_enabled") is True

    def test_only_super_admin_can_patch(self, sksco_admin_token, sksco_company_id):
        r = requests.patch(
            f"{API}/admin/companies/{sksco_company_id}/access-rights",
            headers=_hdr(sksco_admin_token),
            json={"permissions": ["messages:read"]},
            timeout=30,
        )
        assert r.status_code == 403, r.text


# =============================================================================
# 6) MASTER SHEET AUTOMATION
# =============================================================================
class TestMasterSheet:
    def test_generate_master_sheet_xlsx(self, super_headers, sksco_company_id):
        r = requests.get(
            f"{API}/admin/master-sheet/{sksco_company_id}/2026-06.xlsx",
            headers=super_headers, timeout=60,
        )
        assert r.status_code == 200, r.text[:300]
        assert "spreadsheetml.sheet" in r.headers.get("content-type", ""), r.headers
        assert len(r.content) > 500, "master sheet body too small"

    def test_upload_returns_mis_report_with_canonical_matches(self, super_headers):
        # Build a small XLSX in memory with fuzzy headers
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["EmpCode", "Full Name", "GROSS", "Advance", "TDS"])
        ws.append(["EMP001", "John Doe", 25000, 500, 200])
        ws.append(["EMP002", "Jane Smith", 30000, 0, 0])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        r = requests.post(
            f"{API}/admin/master-sheet/upload",
            headers={"Authorization": super_headers["Authorization"]},
            files={"file": ("test.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        for k in ("mis_report", "row_count", "headers", "body_preview", "body"):
            assert k in body, f"missing key {k} in upload response"
        matches = body["mis_report"].get("matches") or []
        # matches is a LIST of {canonical, matched_header, confidence, ...}
        by_canonical = {m.get("canonical"): m for m in matches if isinstance(m, dict)}
        for req in ("employee_code", "name", "gross_salary"):
            assert req in by_canonical, f"missing canonical {req}: {by_canonical.keys()}"
            assert (by_canonical[req].get("confidence") or 0) >= 65, by_canonical[req]

    def test_apply_mapping_imports_rows(
        self, super_headers, sksco_company_id, sksco_employees
    ):
        if not sksco_employees:
            pytest.skip("No employees to import against")
        emp = sksco_employees[0]
        emp_code = emp.get("employee_code") or ""
        if not emp_code:
            pytest.skip("Employee has no employee_code")
        headers = ["EmpCode", "Full Name", "GROSS"]
        body_rows = [[emp_code, emp.get("name") or "", 27777.0]]
        r = requests.post(
            f"{API}/admin/master-sheet/apply-mapping",
            headers=super_headers,
            json={
                "company_id": sksco_company_id,
                "month": "2026-06",
                "headers": headers,
                "body": body_rows,
                "mapping": {"employee_code": 0, "name": 1, "gross_salary": 2},
            },
            timeout=60,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("imported", "unmatched_count", "unmatched"):
            assert k in j, f"missing key {k}"
        assert j["imported"] >= 1, j


# =============================================================================
# 7) ECR / ESIC DOWNLOADS
# =============================================================================
class TestComplianceDownloads:
    @pytest.fixture(scope="class")
    def compliance_run_id(self, super_headers, sksco_company_id) -> str:
        # List first — reuse an existing run if present
        r = requests.get(
            f"{API}/admin/compliance-salary-runs",
            headers=super_headers,
            params={"company_id": sksco_company_id},
            timeout=30,
        )
        if r.status_code == 200:
            d = r.json()
            runs = d if isinstance(d, list) else d.get("compliance_runs") or d.get("runs") or d.get("items") or []
            if runs:
                return runs[0].get("run_id") or runs[0].get("id")
        # Create a fresh one
        r = requests.post(
            f"{API}/admin/compliance-salary-runs",
            headers=super_headers,
            json={"company_id": sksco_company_id, "month": "2026-06"},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:400]
        run = r.json().get("run") or {}
        return run.get("run_id")

    def test_ecr_download(self, super_headers, compliance_run_id):
        r = requests.get(
            f"{API}/admin/compliance-salary-runs/{compliance_run_id}/ecr.txt",
            headers=super_headers, timeout=30,
        )
        assert r.status_code == 200, r.text[:400]
        assert "text/plain" in r.headers.get("content-type", "")
        assert len(r.content) > 0

    def test_esic_download(self, super_headers, compliance_run_id):
        r = requests.get(
            f"{API}/admin/compliance-salary-runs/{compliance_run_id}/esic.xlsx",
            headers=super_headers, timeout=30,
        )
        assert r.status_code == 200, r.text[:400]
        assert "spreadsheetml.sheet" in r.headers.get("content-type", "")
        assert len(r.content) > 0


# =============================================================================
# 8) SUB-ADMIN PERMISSION ENFORCEMENT
# =============================================================================
class TestSubAdminPermissionEnforcement:
    @pytest.fixture(scope="class")
    def sub_admin_with_perm(self, super_headers):
        email = f"test_sub_with_{uuid.uuid4().hex[:6]}@sksharma.local"
        password = "TestPass!234"
        r = requests.post(
            f"{API}/admin/sub-admins",
            headers=super_headers,
            json={
                "name": "SubWith",
                "email": email,
                "password": password,
                "permissions": ["salary_process:write"],
                "company_scope": "all",
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        yield email, password, r.json().get("sub_admin", {}).get("user_id")
        # Cleanup
        uid = r.json().get("sub_admin", {}).get("user_id")
        if uid:
            requests.delete(f"{API}/admin/sub-admins/{uid}", headers=super_headers, timeout=15)

    @pytest.fixture(scope="class")
    def sub_admin_without_perm(self, super_headers):
        email = f"test_sub_without_{uuid.uuid4().hex[:6]}@sksharma.local"
        password = "TestPass!234"
        r = requests.post(
            f"{API}/admin/sub-admins",
            headers=super_headers,
            json={
                "name": "SubWithout",
                "email": email,
                "password": password,
                "permissions": ["employees:read"],
                "company_scope": "all",
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        yield email, password, r.json().get("sub_admin", {}).get("user_id")
        uid = r.json().get("sub_admin", {}).get("user_id")
        if uid:
            requests.delete(f"{API}/admin/sub-admins/{uid}", headers=super_headers, timeout=15)

    def test_sub_admin_with_permission_can_create_salary_run(
        self, sub_admin_with_perm, sksco_company_id
    ):
        email, password, _uid = sub_admin_with_perm
        tok, _ = _password_login(email, password)
        r = requests.post(
            f"{API}/admin/salary-runs",
            headers=_hdr(tok),
            json={"company_id": sksco_company_id, "month": "2026-10"},
            timeout=60,
        )
        assert r.status_code == 200, f"WITH-perm sub_admin got {r.status_code}: {r.text[:400]}"

    def test_sub_admin_without_permission_denied(
        self, sub_admin_without_perm, sksco_company_id
    ):
        email, password, _uid = sub_admin_without_perm
        tok, _ = _password_login(email, password)
        r = requests.post(
            f"{API}/admin/salary-runs",
            headers=_hdr(tok),
            json={"company_id": sksco_company_id, "month": "2026-10"},
            timeout=60,
        )
        assert r.status_code == 403, r.text[:400]
        assert "salary_process:write" in r.text, f"error detail missing perm name: {r.text}"
