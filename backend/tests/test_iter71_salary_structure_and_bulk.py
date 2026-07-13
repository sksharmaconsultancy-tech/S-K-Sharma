"""Iter 71 backend tests.

Coverage:
  1. POST /api/admin/employees — new salary-structure arrays are persisted:
       actual_salary_allowances, actual_salary_deductions,
       compliance_salary_allowances, compliance_salary_deductions
     a. Full payload → arrays match after GET /admin/employees.
     b. Payload omits the arrays → each stored as [].
  2. POST /api/admin/employees/bulk-import — CSV bulk-import.
     a. 3 unique rows → all created with auto employee_code + 6-digit temp_pin.
     b. Re-import same rows → all 3 skipped_duplicates.
     c. Row missing name → error mentions "name".
     d. Row missing phone AND email → error mentions "phone or email".
     e. Super-admin without company_id → 400.
     f. Company-admin sending a different company_id → import forced to own firm.
     g. Empty rows=[] → 400 "rows must be a non-empty list".
  3. GET /api/admin/employees/bulk-import-template.csv — content-type,
     Content-Disposition, and required header columns.

All created users are prefixed TEST_iter71_ and cleaned up via
DELETE /admin/employees/{user_id} in a session-wide fixture.

Uses OTP dev_code flow for super_admin (does not touch super_admin's pin_hash)
and admin-pin-login (SKSCO1 / +919810000001 / 387908) for company-admin (which
does NOT modify pin_hash or pin_must_change).
"""
from __future__ import annotations
import os
import re
import uuid
from typing import Optional, Tuple

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

RUN_ID = uuid.uuid4().hex[:6].upper()

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
    assert r.status_code == 200, f"otp/request: {r.status_code} {r.text[:200]}"
    body = r.json()
    code = body.get("dev_code") or body.get("code")
    assert code, f"No dev code: {body}"
    r = sess.post(f"{API}/auth/otp/verify",
                  json={"identifier": identifier, "channel": channel, "code": code})
    assert r.status_code == 200, f"otp/verify: {r.status_code} {r.text[:200]}"
    body = r.json()
    return body.get("session_token") or body.get("token")


@pytest.fixture(scope="session")
def super_token(sess) -> str:
    return _otp_login(sess, SUPER_ADMIN_EMAIL, "email")


@pytest.fixture(scope="session")
def sksco_admin(sess) -> Tuple[str, str]:
    """Admin PIN login for S.K. Sharma & Co. Returns (token, company_id).

    Does NOT alter pin_hash or pin_must_change.
    """
    r = sess.post(f"{API}/auth/admin-pin-login",
                  json={"identifier": SKSCO_ADMIN_PHONE, "pin": SKSCO_ADMIN_PIN})
    assert r.status_code == 200, f"admin-pin-login: {r.status_code} {r.text[:200]}"
    body = r.json()
    token = body["session_token"]
    company_id = body["user"].get("company_id")
    assert company_id, f"No company_id on admin: {body['user']}"
    return token, company_id


@pytest.fixture(scope="session")
def sksco_company(sess, super_token) -> dict:
    r = sess.get(f"{API}/companies", headers=_auth(super_token))
    assert r.status_code == 200, r.text[:200]
    items = r.json()
    if isinstance(items, dict):
        items = items.get("companies") or items.get("items") or []
    for c in items:
        if (c.get("company_code") or "").upper() == "SKSCO1":
            return c
    pytest.skip("SKSCO1 company not present in this env")


@pytest.fixture(scope="session")
def other_company(sess, super_token) -> Optional[dict]:
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


@pytest.fixture(scope="session", autouse=True)
def _cleanup(sess, super_token):
    yield
    for uid in list(CREATED_USER_IDS):
        try:
            sess.delete(f"{API}/admin/employees/{uid}", headers=_auth(super_token))
        except Exception:
            pass


def _remember(user_id: str):
    if user_id:
        CREATED_USER_IDS.append(user_id)


def _fresh_phone(seed: str) -> str:
    """Return a unique test phone. seed picks a 4-digit slot."""
    n = (abs(hash(seed + RUN_ID)) % 10000)
    return f"+9199{RUN_ID[:2]}{n:06d}"[:14]


def _fresh_email(seed: str) -> str:
    return f"test_iter71_{RUN_ID.lower()}_{seed}@example.com"


# ---------------------------------------------------------------------------
# 1. POST /admin/employees — salary structure arrays
# ---------------------------------------------------------------------------
class TestSalaryStructureArrays:
    def test_a_full_arrays_persist(self, sess, super_token, sksco_company):
        payload = {
            "name": f"TEST_iter71_SalStruct_{RUN_ID}",
            "phone": _fresh_phone("salstruct"),
            "email": _fresh_email("salstruct"),
            "company_id": sksco_company["company_id"],
            "designation": "Test",
            "salary_monthly": 30000,
            "compliance_gross": 25000,
            "actual_salary_allowances": [
                {"head": "HRA", "amount": 5000},
                {"head": "Conveyance", "amount": 1600},
            ],
            "actual_salary_deductions": [
                {"head": "Loan", "amount": 1000},
            ],
            "compliance_salary_allowances": [
                {"head": "Basic", "amount": 15000},
                {"head": "DA", "amount": 3000},
            ],
            "compliance_salary_deductions": [
                {"head": "PF", "amount": 1800},
                {"head": "ESI", "amount": 187},
            ],
        }
        r = sess.post(f"{API}/admin/employees", json=payload,
                      headers=_auth(super_token))
        assert r.status_code == 200, f"create: {r.status_code} {r.text[:300]}"
        body = r.json()
        assert body.get("ok") is True
        uid = body["user_id"]
        _remember(uid)

        # Fetch via GET /admin/employees and verify arrays
        r2 = sess.get(f"{API}/admin/employees",
                      params={"company_id": sksco_company["company_id"]},
                      headers=_auth(super_token))
        assert r2.status_code == 200, r2.text[:200]
        emps = r2.json().get("employees") or []
        found = next((e for e in emps if e.get("user_id") == uid), None)
        assert found, "newly-created employee not returned"
        for key in ("actual_salary_allowances", "actual_salary_deductions",
                    "compliance_salary_allowances", "compliance_salary_deductions"):
            got = found.get(key)
            exp = payload[key]
            assert isinstance(got, list), f"{key} not a list: {type(got)}"
            assert len(got) == len(exp), f"{key} length mismatch: {got}"
            # Compare head+amount tuples (order preserved as sent)
            got_pairs = [(row.get("head"), row.get("amount")) for row in got]
            exp_pairs = [(row["head"], row["amount"]) for row in exp]
            assert got_pairs == exp_pairs, f"{key} content mismatch: got={got_pairs} exp={exp_pairs}"

    def test_b_omitted_arrays_default_to_empty(self, sess, super_token, sksco_company):
        payload = {
            "name": f"TEST_iter71_NoArrays_{RUN_ID}",
            "phone": _fresh_phone("noarrays"),
            "email": _fresh_email("noarrays"),
            "company_id": sksco_company["company_id"],
        }
        r = sess.post(f"{API}/admin/employees", json=payload,
                      headers=_auth(super_token))
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        uid = body["user_id"]
        _remember(uid)

        r2 = sess.get(f"{API}/admin/employees",
                      params={"company_id": sksco_company["company_id"]},
                      headers=_auth(super_token))
        assert r2.status_code == 200
        emps = r2.json().get("employees") or []
        found = next((e for e in emps if e.get("user_id") == uid), None)
        assert found, "newly-created employee not returned"
        for key in ("actual_salary_allowances", "actual_salary_deductions",
                    "compliance_salary_allowances", "compliance_salary_deductions"):
            got = found.get(key)
            assert got == [], f"{key} should default to [], got {got!r}"


# ---------------------------------------------------------------------------
# 2. POST /admin/employees/bulk-import
# ---------------------------------------------------------------------------
def _bulk_rows(seed_tag: str) -> list[dict]:
    """Three unique valid rows."""
    rows = []
    for i in range(3):
        rows.append({
            "name": f"TEST_iter71_Bulk_{seed_tag}_{i}_{RUN_ID}",
            "phone": _fresh_phone(f"{seed_tag}_{i}"),
            "email": _fresh_email(f"{seed_tag}_{i}"),
            "designation": "Operator",
            "department": "Weaving",
            "salary_mode": "monthly",
            "salary_monthly": 20000 + i * 500,
        })
    return rows


class TestBulkImport:
    def test_a_three_unique_rows_created(self, sess, super_token, sksco_company):
        rows = _bulk_rows("unique")
        r = sess.post(
            f"{API}/admin/employees/bulk-import",
            json={"company_id": sksco_company["company_id"], "rows": rows},
            headers=_auth(super_token),
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body.get("ok") is True
        assert body.get("created_count") == 3, body
        assert body.get("skipped_count") == 0, body
        assert body.get("error_count") == 0, body
        created = body.get("created") or []
        assert len(created) == 3
        for row in created:
            assert row.get("user_id"), row
            assert row.get("employee_code"), f"missing auto employee_code: {row}"
            tp = row.get("temp_pin")
            assert tp and re.fullmatch(r"\d{6}", tp), f"temp_pin not 6-digit: {tp}"
            _remember(row["user_id"])

        # Verify via GET /admin/employees
        r2 = sess.get(f"{API}/admin/employees",
                      params={"company_id": sksco_company["company_id"]},
                      headers=_auth(super_token))
        assert r2.status_code == 200
        emps = r2.json().get("employees") or []
        emp_ids = {e.get("user_id") for e in emps}
        for row in created:
            assert row["user_id"] in emp_ids, f"user_id not in list: {row['user_id']}"

        # Stash rows for the next test (dup re-import)
        TestBulkImport._first_rows = rows  # type: ignore[attr-defined]

    def test_b_reimport_marks_duplicates(self, sess, super_token, sksco_company):
        rows = getattr(TestBulkImport, "_first_rows", None)
        if not rows:
            pytest.skip("test_a did not run; no rows to re-import")
        r = sess.post(
            f"{API}/admin/employees/bulk-import",
            json={"company_id": sksco_company["company_id"], "rows": rows},
            headers=_auth(super_token),
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body.get("created_count") == 0, body
        assert body.get("skipped_count") == 3, body
        assert body.get("error_count") == 0, body
        skipped = body.get("skipped_duplicates") or []
        assert len(skipped) == 3
        for s in skipped:
            assert s.get("existing_user_id"), s

    def test_c_missing_name_reported_in_errors(self, sess, super_token, sksco_company):
        rows = [
            # row 1 — missing name
            {"phone": _fresh_phone("noname"), "email": _fresh_email("noname_1")},
            # row 2 — valid
            {
                "name": f"TEST_iter71_ValidAlongBad_{RUN_ID}",
                "phone": _fresh_phone("valid_along"),
                "email": _fresh_email("valid_along"),
            },
        ]
        r = sess.post(
            f"{API}/admin/employees/bulk-import",
            json={"company_id": sksco_company["company_id"], "rows": rows},
            headers=_auth(super_token),
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body.get("created_count") == 1, body
        assert body.get("error_count") == 1, body
        errs = body.get("errors") or []
        assert len(errs) == 1
        assert "name" in (errs[0].get("reason") or "").lower(), errs
        # Track the valid one for cleanup
        for row in (body.get("created") or []):
            _remember(row["user_id"])

    def test_d_missing_phone_and_email_error(self, sess, super_token, sksco_company):
        rows = [
            {"name": f"TEST_iter71_NoContact_{RUN_ID}"},
        ]
        r = sess.post(
            f"{API}/admin/employees/bulk-import",
            json={"company_id": sksco_company["company_id"], "rows": rows},
            headers=_auth(super_token),
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body.get("created_count") == 0, body
        assert body.get("error_count") == 1, body
        errs = body.get("errors") or []
        reason = (errs[0].get("reason") or "").lower()
        assert "phone" in reason and "email" in reason, errs

    def test_e_super_admin_without_company_id_returns_400(self, sess, super_token):
        rows = [{
            "name": f"TEST_iter71_NoCid_{RUN_ID}",
            "phone": _fresh_phone("nocid"),
        }]
        r = sess.post(f"{API}/admin/employees/bulk-import",
                      json={"rows": rows}, headers=_auth(super_token))
        assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"

    def test_f_company_admin_forced_to_own_firm(
        self, sess, sksco_admin, other_company, super_token
    ):
        token, own_cid = sksco_admin
        # Try to send a different company_id in the payload
        target_cid = own_cid
        if other_company and other_company.get("company_id"):
            target_cid = other_company["company_id"]
        assert target_cid, "no company to try"
        row_email = _fresh_email("forced")
        row_phone = _fresh_phone("forced")
        rows = [{
            "name": f"TEST_iter71_ForcedFirm_{RUN_ID}",
            "phone": row_phone,
            "email": row_email,
        }]
        r = sess.post(
            f"{API}/admin/employees/bulk-import",
            json={"company_id": target_cid, "rows": rows},
            headers=_auth(token),
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body.get("created_count") == 1, body
        uid = body["created"][0]["user_id"]
        _remember(uid)
        # Verify the created user's company_id equals the ADMIN's own_cid,
        # NOT what we sent.
        r2 = sess.get(f"{API}/admin/employees",
                      params={"company_id": own_cid},
                      headers=_auth(super_token))
        assert r2.status_code == 200
        emps = r2.json().get("employees") or []
        found = next((e for e in emps if e.get("user_id") == uid), None)
        assert found, f"created employee not in own firm's list (uid={uid})"
        assert found.get("company_id") == own_cid, \
            f"expected company_id={own_cid}, got {found.get('company_id')}"
        # And confirm they're NOT in the other firm's list
        if other_company and other_company["company_id"] != own_cid:
            r3 = sess.get(f"{API}/admin/employees",
                          params={"company_id": other_company["company_id"]},
                          headers=_auth(super_token))
            assert r3.status_code == 200
            other_ids = {e.get("user_id") for e in (r3.json().get("employees") or [])}
            assert uid not in other_ids, \
                "employee leaked to the foreign firm the admin tried to target"

    def test_g_empty_rows_returns_400(self, sess, super_token, sksco_company):
        r = sess.post(
            f"{API}/admin/employees/bulk-import",
            json={"company_id": sksco_company["company_id"], "rows": []},
            headers=_auth(super_token),
        )
        assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"
        # Detail should mention "rows" and "non-empty"
        detail = (r.json().get("detail") or "").lower()
        assert "rows" in detail and "non-empty" in detail, detail


# ---------------------------------------------------------------------------
# 3. GET /admin/employees/bulk-import-template.csv
# ---------------------------------------------------------------------------
REQUIRED_CSV_COLUMNS = [
    "name", "phone", "email", "designation", "department",
    "salary_monthly", "compliance_gross",
    "uan_no", "pf_no", "esi_ip_no",
    "pan_no", "aadhaar_no",
    "bank_name", "bank_account", "bank_ifsc",
]


class TestBulkImportTemplate:
    def test_super_admin_download_ok(self, sess, super_token):
        r = sess.get(f"{API}/admin/employees/bulk-import-template.csv",
                     headers=_auth(super_token))
        assert r.status_code == 200, r.text[:200]
        ctype = r.headers.get("content-type") or r.headers.get("Content-Type") or ""
        assert "text/csv" in ctype.lower(), f"content-type={ctype!r}"
        cdisp = (r.headers.get("content-disposition")
                 or r.headers.get("Content-Disposition") or "").lower()
        assert ".csv" in cdisp, f"content-disposition={cdisp!r}"
        body = r.text
        lines = [ln for ln in body.splitlines() if ln.strip()]
        assert lines, "empty CSV body"
        header = [c.strip().lower() for c in lines[0].split(",")]
        for col in REQUIRED_CSV_COLUMNS:
            assert col in header, f"missing required column: {col} — got {header}"

    def test_company_admin_download_ok(self, sess, sksco_admin):
        token, _ = sksco_admin
        r = sess.get(f"{API}/admin/employees/bulk-import-template.csv",
                     headers=_auth(token))
        assert r.status_code == 200, r.text[:200]
        ctype = r.headers.get("content-type") or r.headers.get("Content-Type") or ""
        assert "text/csv" in ctype.lower(), f"content-type={ctype!r}"
