"""Iter 68 backend tests — Admin Employee Add form + Salary Register/Certificate PDFs.

Under test:
  1. POST /api/admin/employees — new admin-facing employee creation.
     - happy path (super_admin creates in a company)
     - duplicate phone → 409
     - duplicate email → 409
     - missing name → 400
     - missing both phone AND email → 400
     - employee_code auto-assigned in <COMPANY_CODE><NNNN> format
     - temp_pin is 6 digits, pin_must_change=true
     - approval_status=approved (auto-approved)
     - GET /api/admin/employees lists the new employee
     - company_admin cannot inject a different company_id
  2. GET /api/admin/salary-runs/{run_id}/register-form27.pdf → PDF bytes
  3. GET /api/admin/employees/{user_id}/salary-certificate.pdf → PDF bytes
     - company_admin cannot fetch certificate for employee outside their firm (403)
  4. Regression — GET /api/admin/employees excludes company_admin accounts (role="employee" only).

Runs against the public preview URL. Super-admin session obtained via OTP
dev-code flow (email = sksharmaconsultancy@gmail.com). Company-admin session
obtained via admin PIN login (SKSCO1 / +919810000001 / 387908) — this login
does NOT touch pin_hash or pin_must_change.

All created test employees are DELETEd at teardown via
DELETE /api/admin/employees/{user_id}.
"""
from __future__ import annotations
import os
import re
import uuid
from typing import Optional

import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "https://emplo-connect-1.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
SKSCO_ADMIN_PHONE = "+919810000001"
SKSCO_ADMIN_PIN = "387908"

RUN_SUFFIX = uuid.uuid4().hex[:6].upper()

CREATED_USER_IDS: list[str] = []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def sess():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _otp_login(sess, identifier: str, channel: str = "email") -> str:
    r = sess.post(f"{API}/auth/otp/request",
                  json={"identifier": identifier, "channel": channel})
    assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    code = body.get("dev_code") or body.get("code")
    assert code, f"No dev code in response: {body}"
    r = sess.post(f"{API}/auth/otp/verify",
                  json={"identifier": identifier, "channel": channel, "code": code})
    assert r.status_code == 200, f"otp/verify failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    return body.get("session_token") or body.get("token")


@pytest.fixture(scope="session")
def super_token(sess) -> str:
    return _otp_login(sess, SUPER_ADMIN_EMAIL, "email")


@pytest.fixture(scope="session")
def sksco_admin_token(sess) -> tuple[str, str]:
    """Admin PIN login for S.K. Sharma & Co. Returns (token, company_id).
    Does not alter pin_hash / pin_must_change.
    """
    r = sess.post(f"{API}/auth/admin-pin-login",
                  json={"identifier": SKSCO_ADMIN_PHONE, "pin": SKSCO_ADMIN_PIN})
    assert r.status_code == 200, f"admin-pin-login failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    token = body["session_token"]
    company_id = body["user"].get("company_id")
    assert company_id, f"Company admin has no company_id: {body['user']}"
    return token, company_id


@pytest.fixture(scope="session")
def sksco_company(sess, super_token) -> dict:
    """Fetch S.K. Sharma & Co. company doc (code=SKSCO1)."""
    r = sess.get(f"{API}/companies", headers=_auth(super_token))
    assert r.status_code == 200, f"companies list failed: {r.status_code} {r.text[:200]}"
    items = r.json()
    if isinstance(items, dict):
        items = items.get("companies") or items.get("items") or []
    for c in items:
        if (c.get("company_code") or "").upper() == "SKSCO1":
            return c
    pytest.skip("SKSCO1 company not found in this environment")


@pytest.fixture(scope="session")
def other_company(sess, super_token) -> Optional[dict]:
    """Any company whose code is NOT SKSCO1 (for cross-firm 403 test)."""
    r = sess.get(f"{API}/companies", headers=_auth(super_token))
    if r.status_code != 200:
        return None
    items = r.json()
    if isinstance(items, dict):
        items = items.get("companies") or items.get("items") or []
    for c in items:
        if (c.get("company_code") or "").upper() != "SKSCO1":
            return c
    return None


# Session-wide cleanup — deletes any employees we created via the API.
@pytest.fixture(scope="session", autouse=True)
def _cleanup(sess, super_token):
    yield
    for uid in list(CREATED_USER_IDS):
        try:
            sess.delete(f"{API}/admin/employees/{uid}", headers=_auth(super_token))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 1. POST /admin/employees — happy path + validation
# ---------------------------------------------------------------------------
class TestAdminCreateEmployee:
    def test_super_admin_creates_employee_happy_path(
        self, sess, super_token, sksco_company
    ):
        phone = f"+91999{RUN_SUFFIX[:2]}00001{RUN_SUFFIX[2:4]}"[:14]
        email = f"test_it68_{RUN_SUFFIX}_happy@example.com".lower()
        payload = {
            "name": f"TEST Iter68 Happy {RUN_SUFFIX}",
            "phone": phone,
            "email": email,
            "company_id": sksco_company["company_id"],
            "designation": "QA Engineer",
            "department": "Engineering",
            "salary_mode": "monthly",
            "salary_monthly": 45000,
        }
        r = sess.post(f"{API}/admin/employees",
                      json=payload, headers=_auth(super_token))
        assert r.status_code == 200, f"create failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("user_id"), "user_id missing"
        assert body.get("employee_code"), "employee_code missing"
        assert body.get("temp_pin"), "temp_pin missing"
        assert re.fullmatch(r"\d{6}", body["temp_pin"]), \
            f"temp_pin not 6 digits: {body['temp_pin']}"
        # Format check: <COMPANY_CODE><NNNN>
        code = body["employee_code"]
        assert code.upper().startswith("SKSCO1"), \
            f"employee_code prefix wrong: {code}"
        assert re.fullmatch(r"SKSCO1\d{4}", code.upper()), \
            f"employee_code shape wrong: {code}"
        CREATED_USER_IDS.append(body["user_id"])

        # Verify via GET /admin/employees
        r2 = sess.get(f"{API}/admin/employees",
                      params={"company_id": sksco_company["company_id"]},
                      headers=_auth(super_token))
        assert r2.status_code == 200
        emps = r2.json().get("employees") or []
        found = next((e for e in emps if e.get("user_id") == body["user_id"]), None)
        assert found, "newly-created employee not returned in list"
        assert found.get("role") == "employee"
        assert found.get("approval_status") == "approved", \
            f"approval_status should be 'approved', got {found.get('approval_status')}"
        assert found.get("pin_must_change") is True
        assert found.get("has_pin") is True
        # Sensitive fields must be redacted
        assert "pin_hash" not in found, "pin_hash leaked in list response"

    def test_duplicate_phone_returns_409(self, sess, super_token, sksco_company):
        phone = f"+91888{RUN_SUFFIX}77"[:14]
        payload = {
            "name": f"TEST Iter68 DupPhone1 {RUN_SUFFIX}",
            "phone": phone,
            "company_id": sksco_company["company_id"],
        }
        r1 = sess.post(f"{API}/admin/employees",
                       json=payload, headers=_auth(super_token))
        assert r1.status_code == 200, f"first create failed: {r1.status_code} {r1.text[:200]}"
        CREATED_USER_IDS.append(r1.json()["user_id"])

        payload2 = {
            "name": f"TEST Iter68 DupPhone2 {RUN_SUFFIX}",
            "phone": phone,
            "email": f"dup_it68_{RUN_SUFFIX}@example.com",
            "company_id": sksco_company["company_id"],
        }
        r2 = sess.post(f"{API}/admin/employees",
                       json=payload2, headers=_auth(super_token))
        assert r2.status_code == 409, \
            f"expected 409 on duplicate phone, got {r2.status_code} {r2.text[:200]}"

    def test_duplicate_email_returns_409(self, sess, super_token, sksco_company):
        email = f"dup_email_it68_{RUN_SUFFIX}@example.com".lower()
        payload = {
            "name": f"TEST Iter68 DupEmail1 {RUN_SUFFIX}",
            "email": email,
            "phone": f"+91777{RUN_SUFFIX}11"[:14],
            "company_id": sksco_company["company_id"],
        }
        r1 = sess.post(f"{API}/admin/employees",
                       json=payload, headers=_auth(super_token))
        assert r1.status_code == 200, f"first create failed: {r1.status_code} {r1.text[:200]}"
        CREATED_USER_IDS.append(r1.json()["user_id"])

        payload2 = {
            "name": f"TEST Iter68 DupEmail2 {RUN_SUFFIX}",
            "email": email,
            "phone": f"+91777{RUN_SUFFIX}22"[:14],
            "company_id": sksco_company["company_id"],
        }
        r2 = sess.post(f"{API}/admin/employees",
                       json=payload2, headers=_auth(super_token))
        assert r2.status_code == 409, \
            f"expected 409 on duplicate email, got {r2.status_code} {r2.text[:200]}"

    def test_missing_name_returns_400(self, sess, super_token, sksco_company):
        r = sess.post(f"{API}/admin/employees",
                      json={
                          "phone": f"+91555{RUN_SUFFIX}00"[:14],
                          "company_id": sksco_company["company_id"],
                      },
                      headers=_auth(super_token))
        assert r.status_code == 400, \
            f"expected 400 for missing name, got {r.status_code} {r.text[:200]}"

    def test_missing_phone_and_email_returns_400(
        self, sess, super_token, sksco_company
    ):
        r = sess.post(f"{API}/admin/employees",
                      json={
                          "name": f"TEST Iter68 NoContact {RUN_SUFFIX}",
                          "company_id": sksco_company["company_id"],
                      },
                      headers=_auth(super_token))
        assert r.status_code == 400, \
            f"expected 400 for missing phone/email, got {r.status_code} {r.text[:200]}"

    def test_company_admin_cannot_inject_foreign_company_id(
        self, sess, sksco_admin_token, other_company
    ):
        if not other_company:
            pytest.skip("Need a non-SKSCO1 company to test cross-firm injection")
        token, sksco_cid = sksco_admin_token
        payload = {
            "name": f"TEST Iter68 Foreign {RUN_SUFFIX}",
            "phone": f"+91666{RUN_SUFFIX}33"[:14],
            # Attempt to inject a different company_id — server should ignore it.
            "company_id": other_company["company_id"],
        }
        r = sess.post(f"{API}/admin/employees",
                      json=payload, headers=_auth(token))
        assert r.status_code == 200, \
            f"company_admin create failed: {r.status_code} {r.text[:200]}"
        uid = r.json()["user_id"]
        CREATED_USER_IDS.append(uid)

        # Fetch to verify the server forced company_admin's own company_id
        r2 = sess.get(f"{API}/admin/employees",
                      headers=_auth(token))
        assert r2.status_code == 200
        emps = r2.json().get("employees") or []
        found = next((e for e in emps if e.get("user_id") == uid), None)
        assert found, "employee not visible to its own company_admin"
        assert found.get("company_id") == sksco_cid, \
            f"company_admin should be locked to their firm — got {found.get('company_id')}"


# ---------------------------------------------------------------------------
# 2. Regression — GET /admin/employees excludes non-employee accounts
# ---------------------------------------------------------------------------
class TestAdminEmployeesRoleFilter:
    def test_list_only_returns_role_employee(self, sess, sksco_admin_token):
        token, cid = sksco_admin_token
        r = sess.get(f"{API}/admin/employees", headers=_auth(token))
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        emps = r.json().get("employees") or []
        # every returned account must be role=employee
        offenders = [e for e in emps if e.get("role") != "employee"]
        assert not offenders, \
            f"non-employee accounts leaked into /admin/employees: " \
            f"{[(o.get('name'), o.get('role')) for o in offenders[:5]]}"


# ---------------------------------------------------------------------------
# 3. GET /admin/salary-runs/{run_id}/register-form27.pdf
# ---------------------------------------------------------------------------
class TestSalaryRegisterPdf:
    def test_download_register_pdf(self, sess, super_token):
        # Find any existing salary run
        r = sess.get(f"{API}/admin/salary-runs", headers=_auth(super_token))
        assert r.status_code == 200, f"list salary-runs failed: {r.status_code} {r.text[:200]}"
        body = r.json()
        runs = body.get("runs") if isinstance(body, dict) else body
        if not runs:
            pytest.skip("No salary runs in the environment to download PDF for")
        run_id = runs[0].get("run_id")
        assert run_id, f"run without run_id: {runs[0]}"

        r2 = sess.get(f"{API}/admin/salary-runs/{run_id}/register-form27.pdf",
                      headers=_auth(super_token))
        assert r2.status_code == 200, \
            f"register pdf failed: {r2.status_code} {r2.text[:200]}"
        assert r2.headers.get("content-type", "").startswith("application/pdf"), \
            f"unexpected content-type: {r2.headers.get('content-type')}"
        cd = r2.headers.get("content-disposition", "")
        assert "attachment" in cd.lower(), f"content-disposition missing: {cd}"
        assert r2.content[:5] == b"%PDF-", \
            f"body is not a PDF: first bytes={r2.content[:16]!r}"
        assert len(r2.content) > 1024, \
            f"PDF suspiciously small: {len(r2.content)} bytes"

    def test_register_pdf_404_for_bogus_run(self, sess, super_token):
        r = sess.get(f"{API}/admin/salary-runs/srun_does_not_exist/register-form27.pdf",
                     headers=_auth(super_token))
        assert r.status_code == 404, \
            f"expected 404 for bogus run, got {r.status_code}"


# ---------------------------------------------------------------------------
# 4. GET /admin/employees/{user_id}/salary-certificate.pdf
# ---------------------------------------------------------------------------
class TestSalaryCertificatePdf:
    def test_download_salary_certificate(self, sess, super_token, sksco_company):
        r = sess.get(f"{API}/admin/employees",
                     params={"company_id": sksco_company["company_id"]},
                     headers=_auth(super_token))
        assert r.status_code == 200
        emps = r.json().get("employees") or []
        if not emps:
            pytest.skip("No employees in SKSCO1 to test salary certificate")
        emp = emps[0]
        uid = emp["user_id"]

        r2 = sess.get(f"{API}/admin/employees/{uid}/salary-certificate.pdf",
                      headers=_auth(super_token))
        assert r2.status_code == 200, \
            f"certificate pdf failed: {r2.status_code} {r2.text[:200]}"
        assert r2.headers.get("content-type", "").startswith("application/pdf")
        assert r2.content[:5] == b"%PDF-", \
            f"body is not a PDF: first bytes={r2.content[:16]!r}"
        assert len(r2.content) > 1024, \
            f"PDF suspiciously small: {len(r2.content)} bytes"

    def test_certificate_with_query_params(self, sess, super_token, sksco_company):
        r = sess.get(f"{API}/admin/employees",
                     params={"company_id": sksco_company["company_id"]},
                     headers=_auth(super_token))
        emps = r.json().get("employees") or []
        if not emps:
            pytest.skip("No employees available")
        uid = emps[0]["user_id"]
        r2 = sess.get(
            f"{API}/admin/employees/{uid}/salary-certificate.pdf",
            params={
                "month": "2025-12",
                "signatory_name": "QA Signer",
                "signatory_role": "HR Manager",
            },
            headers=_auth(super_token),
        )
        assert r2.status_code == 200
        assert r2.content[:5] == b"%PDF-"

    def test_certificate_404_for_bogus_user(self, sess, super_token):
        r = sess.get(f"{API}/admin/employees/user_does_not_exist/salary-certificate.pdf",
                     headers=_auth(super_token))
        assert r.status_code == 404

    def test_company_admin_blocked_for_foreign_employee(
        self, sess, super_token, sksco_admin_token, other_company
    ):
        """company_admin from SKSCO1 cannot download certificate of an
        employee in a different firm → 403."""
        if not other_company:
            pytest.skip("Need a non-SKSCO1 company for cross-firm test")
        # pick an employee from the "other" firm via super_admin — seed one
        # temporarily if the firm has none.
        r = sess.get(f"{API}/admin/employees",
                     params={"company_id": other_company["company_id"]},
                     headers=_auth(super_token))
        assert r.status_code == 200
        emps = r.json().get("employees") or []
        if emps:
            foreign_uid = emps[0]["user_id"]
        else:
            seed = sess.post(
                f"{API}/admin/employees",
                json={
                    "name": f"TEST Iter68 Foreign Seed {RUN_SUFFIX}",
                    "phone": f"+9155{RUN_SUFFIX[:2]}{RUN_SUFFIX[2:6]}22"[:14],
                    "company_id": other_company["company_id"],
                },
                headers=_auth(super_token),
            )
            assert seed.status_code == 200, \
                f"seed failed: {seed.status_code} {seed.text[:200]}"
            foreign_uid = seed.json()["user_id"]
            CREATED_USER_IDS.append(foreign_uid)

        sksco_token, _ = sksco_admin_token
        r2 = sess.get(f"{API}/admin/employees/{foreign_uid}/salary-certificate.pdf",
                      headers=_auth(sksco_token))
        assert r2.status_code == 403, \
            f"expected 403 for cross-firm cert, got {r2.status_code} {r2.text[:200]}"


# ---------------------------------------------------------------------------
# 5. Auth guard — endpoints reject employee tokens / no-auth
# ---------------------------------------------------------------------------
class TestAuthGuards:
    def test_create_employee_requires_auth(self, sess):
        r = sess.post(f"{API}/admin/employees",
                      json={"name": "x", "phone": "+911111111111"})
        assert r.status_code in (401, 403), \
            f"expected 401/403 without auth, got {r.status_code}"

    def test_register_pdf_requires_auth(self, sess):
        r = sess.get(f"{API}/admin/salary-runs/xyz/register-form27.pdf")
        assert r.status_code in (401, 403)

    def test_certificate_pdf_requires_auth(self, sess):
        r = sess.get(f"{API}/admin/employees/xyz/salary-certificate.pdf")
        assert r.status_code in (401, 403)
