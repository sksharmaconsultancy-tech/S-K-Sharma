"""
Iter 74 backend tests — three new features:

  1) CSV Bulk-Import allowance/deduction columns
  2) Employee self-service payslip PDF + year-summary + id-card
  3) In-app message attachments

Only tests the NEW/CHANGED endpoints per the review request. Uses the
OTP dev-code flow — the super_admin PIN is NEVER touched.
"""

import base64
import os
import random
import string
import uuid

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") \
    or os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL not set in env")

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _otp_login(identifier: str, channel: str = "email") -> str:
    """Return an auth token via the OTP dev-code flow."""
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": identifier, "channel": channel},
        timeout=30,
    )
    assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text}"
    code = r.json().get("dev_code")
    assert code, f"dev_code missing in response: {r.json()}"
    r2 = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": identifier, "channel": channel, "code": code},
        timeout=30,
    )
    assert r2.status_code == 200, f"otp/verify failed: {r2.status_code} {r2.text}"
    j = r2.json()
    token = j.get("session_token") or j.get("token") or j.get("access_token")
    assert token, f"no token: {j}"
    return token


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _rand_code(prefix: str = "T") -> str:
    return prefix + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))


# 1x1 transparent PNG
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
TINY_PNG_B64 = base64.b64encode(_TINY_PNG).decode()


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def super_token() -> str:
    return _otp_login(SUPER_EMAIL, "email")


@pytest.fixture(scope="module")
def emp_token_and_id() -> tuple:
    """A fresh employee-role OTP user for self-service tests."""
    email = f"qa.iter74.{uuid.uuid4().hex[:8]}@test.com"
    tok = _otp_login(email, "email")
    me = requests.get(f"{BASE_URL}/api/auth/me", headers=_hdr(tok), timeout=15).json()
    return tok, me.get("user_id"), email


@pytest.fixture(scope="module")
def unrelated_emp_token() -> str:
    email = f"qa.iter74.other.{uuid.uuid4().hex[:8]}@test.com"
    return _otp_login(email, "email")


@pytest.fixture(scope="module")
def throwaway_company(super_token: str) -> dict:
    """Create a throwaway company for the bulk-import tests."""
    payload = {
        "name": f"Iter74 QA Co {uuid.uuid4().hex[:6]}",
        "address": "127 Test Rd",
        "office_lat": 28.6,
        "office_lng": 77.2,
        "geofence_radius_m": 250,
        "compliance_enabled": True,
        "company_code": _rand_code("I74"),
    }
    r = requests.post(
        f"{BASE_URL}/api/companies", json=payload, headers=_hdr(super_token), timeout=30,
    )
    assert r.status_code == 200, f"create company: {r.status_code} {r.text}"
    body = r.json()
    company = body.get("company") or body
    assert company.get("company_id"), body
    return company


# ---------------------------------------------------------------------------
# FEATURE 1 — CSV Bulk-Import allowance/deduction columns
# ---------------------------------------------------------------------------
class TestBulkImportAllowanceColumns:

    def test_bulk_import_with_allowances_and_deductions(
        self, super_token, throwaway_company,
    ):
        cid = throwaway_company["company_id"]
        # Randomise phones so re-runs don't collide with 'duplicate' skips.
        suffix_a = "".join(random.choices(string.digits, k=5))
        suffix_b = "".join(random.choices(string.digits, k=5))
        phone_a = f"+9198100{suffix_a}"
        phone_b = f"+9198100{suffix_b}"

        rows = [
            {
                "name": "Test A",
                "phone": phone_a,
                "actual_allowances": "HRA:2000|Convey:500",
                "actual_deductions": "Advance:500",
                "compliance_allowances": "HRA:1500",
                "compliance_deductions": "PF:1800|ESI:135",
            },
            {"name": "Test B", "phone": phone_b},
        ]
        r = requests.post(
            f"{BASE_URL}/api/admin/employees/bulk-import",
            json={"company_id": cid, "rows": rows},
            headers=_hdr(super_token), timeout=45,
        )
        assert r.status_code == 200, f"bulk-import: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("created_count") == 2, body
        # capture user_ids for verification
        created = {c["name"]: c for c in body["created"]}
        assert "Test A" in created and "Test B" in created

        # Fetch and verify persisted allowance shapes
        r2 = requests.get(
            f"{BASE_URL}/api/admin/employees?company_id={cid}",
            headers=_hdr(super_token), timeout=30,
        )
        assert r2.status_code == 200, r2.text
        emps = {e["user_id"]: e for e in r2.json()["employees"]}
        a = emps[created["Test A"]["user_id"]]
        b = emps[created["Test B"]["user_id"]]

        assert a["actual_salary_allowances"] == [
            {"head": "HRA", "amount": 2000.0},
            {"head": "Convey", "amount": 500.0},
        ], a["actual_salary_allowances"]
        assert a["actual_salary_deductions"] == [
            {"head": "Advance", "amount": 500.0},
        ], a["actual_salary_deductions"]
        assert a["compliance_salary_allowances"] == [
            {"head": "HRA", "amount": 1500.0},
        ]
        assert a["compliance_salary_deductions"] == [
            {"head": "PF", "amount": 1800.0},
            {"head": "ESI", "amount": 135.0},
        ]

        # Row B — arrays should be empty (silent skip)
        assert b.get("actual_salary_allowances") in ([], None)
        assert b.get("actual_salary_deductions") in ([], None)
        assert b.get("compliance_salary_allowances") in ([], None)
        assert b.get("compliance_salary_deductions") in ([], None)

    def test_bulk_import_template_has_27_columns_with_new_headers(self, super_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/employees/bulk-import-template.csv",
            headers=_hdr(super_token), timeout=15,
        )
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "").lower()
        first_line = r.text.splitlines()[0]
        cols = [c.strip() for c in first_line.split(",")]
        assert len(cols) == 27, f"expected 27 columns, got {len(cols)}: {cols}"
        for h in (
            "actual_allowances", "actual_deductions",
            "compliance_allowances", "compliance_deductions",
        ):
            assert h in cols, f"missing header {h!r}"

    def test_bulk_import_malformed_amount_is_silently_dropped(
        self, super_token, throwaway_company,
    ):
        cid = throwaway_company["company_id"]
        suffix = "".join(random.choices(string.digits, k=6))
        phone = f"+91981{suffix}"
        rows = [{
            "name": "Test Malformed",
            "phone": phone,
            "actual_allowances": "HRA:abc|Convey:500",
        }]
        r = requests.post(
            f"{BASE_URL}/api/admin/employees/bulk-import",
            json={"company_id": cid, "rows": rows},
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("created_count") == 1, body
        uid = body["created"][0]["user_id"]
        # fetch the created employee
        r2 = requests.get(
            f"{BASE_URL}/api/admin/employees?company_id={cid}",
            headers=_hdr(super_token), timeout=30,
        )
        emp = next(e for e in r2.json()["employees"] if e["user_id"] == uid)
        assert emp["actual_salary_allowances"] == [
            {"head": "Convey", "amount": 500.0},
        ], emp["actual_salary_allowances"]


# ---------------------------------------------------------------------------
# FEATURE 2 — Employee self-service Payslip PDF + Year Summary + ID Card
# ---------------------------------------------------------------------------
class TestEmployeeSelfService:

    def test_id_card_endpoint(self, emp_token_and_id):
        tok, _uid_hint, _ = emp_token_and_id
        r = requests.get(f"{BASE_URL}/api/me/id-card", headers=_hdr(tok), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        # Employee block
        assert "employee" in j and "company" in j
        uid = j["employee"].get("user_id")
        assert uid and uid.startswith("user_"), j["employee"]
        # QR payload shape
        qr = j.get("qr_payload") or ""
        assert qr.startswith("SKSCO|"), qr
        parts = qr.split("|")
        assert len(parts) == 4, qr
        assert parts[3] == uid, qr
        assert "generated_at" in j

    def test_year_summary_shape(self, emp_token_and_id):
        tok, _, _ = emp_token_and_id
        r = requests.get(
            f"{BASE_URL}/api/me/payslips/year-summary",
            headers=_hdr(tok), timeout=15,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert isinstance(j.get("window_months"), list) and len(j["window_months"]) == 12
        for mo in j["window_months"]:
            assert len(mo) == 7 and mo[4] == "-", mo
        totals = j.get("totals") or {}
        for k in ("gross", "deductions", "net", "count", "paid_count"):
            assert k in totals, f"missing totals.{k}"
        assert isinstance(j.get("history"), list)

    def test_payslip_pdf_requires_auth(self):
        r = requests.get(
            f"{BASE_URL}/api/me/payslips/ps_does_not_exist.pdf", timeout=15,
        )
        assert r.status_code == 401, f"expected 401 no token, got {r.status_code}"

    def test_payslip_pdf_404_when_missing(self, emp_token_and_id):
        tok, _, _ = emp_token_and_id
        r = requests.get(
            f"{BASE_URL}/api/me/payslips/ps_does_not_exist_xyz.pdf",
            headers=_hdr(tok), timeout=15,
        )
        assert r.status_code == 404, r.text

    def test_payslip_pdf_403_when_not_your_slip(
        self, super_token, throwaway_company, unrelated_emp_token,
    ):
        """super_admin creates a paid payslip for a bulk-imported employee, then
        an UNRELATED employee tries to fetch — must be 403."""
        cid = throwaway_company["company_id"]
        # Create a fresh employee via bulk-import to own the payslip
        phone = f"+91981{''.join(random.choices(string.digits, k=6))}"
        r = requests.post(
            f"{BASE_URL}/api/admin/employees/bulk-import",
            json={"company_id": cid, "rows": [{"name": "Slip Owner", "phone": phone}]},
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        owner_uid = r.json()["created"][0]["user_id"]

        # Create a paid payslip (create_payslip sets status='paid' → _payslip_is_processed=True)
        month = "2025-06"  # completed past month
        r2 = requests.post(
            f"{BASE_URL}/api/payslips",
            json={
                "employee_user_id": owner_uid,
                "month": month,
                "gross": 30000.0,
                "deductions": 3000.0,
                "net": 27000.0,
            },
            headers=_hdr(super_token), timeout=15,
        )
        assert r2.status_code == 200, r2.text
        slip_id = r2.json()["slip_id"]

        # Unrelated employee attempts fetch → 403
        r3 = requests.get(
            f"{BASE_URL}/api/me/payslips/{slip_id}.pdf",
            headers=_hdr(unrelated_emp_token), timeout=15,
        )
        assert r3.status_code == 403, f"expected 403, got {r3.status_code}: {r3.text[:200]}"


# ---------------------------------------------------------------------------
# FEATURE 3 — In-App Message attachments
# ---------------------------------------------------------------------------
class TestMessageAttachments:

    @pytest.fixture(scope="class")
    def recipient(self, super_token):
        """A fresh employee attached to a fresh company (so super_admin can
        pick them as a recipient)."""
        # Create a company + employee for a clean scope
        payload = {
            "name": f"Iter74 Msg Co {uuid.uuid4().hex[:6]}",
            "office_lat": 28.6, "office_lng": 77.2,
            "geofence_radius_m": 250,
            "compliance_enabled": True,
            "company_code": _rand_code("M74"),
        }
        r = requests.post(
            f"{BASE_URL}/api/companies", json=payload,
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        company = r.json().get("company") or r.json()
        cid = company["company_id"]
        # Add employee
        suffix = "".join(random.choices(string.digits, k=6))
        phone = f"+91977{suffix}"
        r2 = requests.post(
            f"{BASE_URL}/api/admin/employees/bulk-import",
            json={"company_id": cid, "rows": [{"name": "Msg Recipient", "phone": phone}]},
            headers=_hdr(super_token), timeout=30,
        )
        assert r2.status_code == 200, r2.text
        return {
            "user_id": r2.json()["created"][0]["user_id"],
            "phone": phone,
            "company_id": cid,
        }

    @pytest.fixture(scope="class")
    def recipient_token(self, recipient):
        return _otp_login(recipient["phone"], "sms")

    def test_send_message_with_png_attachment(self, super_token, recipient):
        r = requests.post(
            f"{BASE_URL}/api/messages",
            json={
                "subject": "Iter74 attachment test",
                "body": "Please review the attached PNG.",
                "recipient_user_ids": [recipient["user_id"]],
                "company_id": recipient["company_id"],
                "attachments": [{
                    "filename": "pixel.png",
                    "mime_type": "image/png",
                    "base64": TINY_PNG_B64,
                }],
            },
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        m = r.json()["message"]
        assert m.get("attachment_count") == 1
        assert isinstance(m.get("attachments"), list) and len(m["attachments"]) == 1
        att = m["attachments"][0]
        assert "base64" not in att, "base64 must be stripped from response"
        assert att.get("mime_type") == "image/png"
        assert att.get("attachment_id")
        # Save on the class for downstream tests
        TestMessageAttachments._sent_msg = m

    def test_inbox_shows_attachment_metadata(self, recipient_token):
        r = requests.get(
            f"{BASE_URL}/api/messages/inbox",
            headers=_hdr(recipient_token), timeout=15,
        )
        assert r.status_code == 200, r.text
        msgs = r.json()["messages"]
        sent = TestMessageAttachments._sent_msg
        found = next((m for m in msgs if m["message_id"] == sent["message_id"]), None)
        assert found, "sent message not visible in recipient inbox"
        assert found.get("attachment_count") == 1
        assert isinstance(found.get("attachments"), list) and len(found["attachments"]) == 1
        assert "base64" not in found["attachments"][0]

    def test_download_attachment_recipient_ok(self, recipient_token):
        m = TestMessageAttachments._sent_msg
        aid = m["attachments"][0]["attachment_id"]
        r = requests.get(
            f"{BASE_URL}/api/messages/{m['message_id']}/attachments/{aid}",
            headers={"Authorization": f"Bearer {recipient_token}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("image/png")
        assert r.content == _TINY_PNG, "bytes must round-trip identically"

    def test_download_attachment_403_for_unrelated_user(self, unrelated_emp_token):
        m = TestMessageAttachments._sent_msg
        aid = m["attachments"][0]["attachment_id"]
        r = requests.get(
            f"{BASE_URL}/api/messages/{m['message_id']}/attachments/{aid}",
            headers={"Authorization": f"Bearer {unrelated_emp_token}"},
            timeout=15,
        )
        assert r.status_code == 403, r.text

    def test_reject_more_than_3_attachments(self, super_token, recipient):
        atts = [
            {"filename": f"p{i}.png", "mime_type": "image/png", "base64": TINY_PNG_B64}
            for i in range(4)
        ]
        r = requests.post(
            f"{BASE_URL}/api/messages",
            json={
                "subject": "x", "body": "y",
                "recipient_user_ids": [recipient["user_id"]],
                "company_id": recipient["company_id"],
                "attachments": atts,
            },
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 400, r.text
        assert "attachment" in r.text.lower()

    def test_reject_unsupported_mime(self, super_token, recipient):
        r = requests.post(
            f"{BASE_URL}/api/messages",
            json={
                "subject": "x", "body": "y",
                "recipient_user_ids": [recipient["user_id"]],
                "company_id": recipient["company_id"],
                "attachments": [{
                    "filename": "hello.txt",
                    "mime_type": "text/plain",
                    "base64": base64.b64encode(b"hello").decode(),
                }],
            },
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 400, r.text
        assert "text/plain" in r.text or "unsupported" in r.text.lower()

    def test_reject_oversized_attachment(self, super_token, recipient):
        # Build ~7 MB base64 body (>5 MB decoded).
        big_b64 = "A" * (7 * 1024 * 1024)  # 7,340,032 chars → ~5.5 MB decoded
        r = requests.post(
            f"{BASE_URL}/api/messages",
            json={
                "subject": "x", "body": "y",
                "recipient_user_ids": [recipient["user_id"]],
                "company_id": recipient["company_id"],
                "attachments": [{
                    "filename": "big.pdf",
                    "mime_type": "application/pdf",
                    "base64": big_b64,
                }],
            },
            headers=_hdr(super_token), timeout=60,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"
        assert "5" in r.text  # "5 MB" mentioned in the error detail

    def test_data_uri_prefix_is_stripped(self, super_token, recipient):
        prefixed = f"data:image/png;base64,{TINY_PNG_B64}"
        r = requests.post(
            f"{BASE_URL}/api/messages",
            json={
                "subject": "data-uri test",
                "body": "with prefix",
                "recipient_user_ids": [recipient["user_id"]],
                "company_id": recipient["company_id"],
                "attachments": [{
                    "filename": "pixel2.png",
                    "mime_type": "image/png",
                    "base64": prefixed,
                }],
            },
            headers=_hdr(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        m = r.json()["message"]
        assert m.get("attachment_count") == 1
