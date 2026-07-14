"""
Iteration 50 — Employee Master PDF + Scan Documents.

Covers the new endpoints:

* GET  /api/admin/employees/{uid}/master-pdf         (PDF stream + snapshot row)
* GET  /api/admin/employees/master-pdf/bulk          (concatenated PDF)
* POST /api/admin/employees/{uid}/documents          (upload scan doc)
* GET  /api/admin/employees/{uid}/documents          (list, no base64)
* GET  /api/admin/employees/{uid}/documents/{doc_id} (single doc, base64 or bytes)
* DELETE ...                                          (delete doc)

Access-control regressions:
* An employee role token cannot access any of the above (401/403).
* A company_admin cannot access a user_id belonging to a different company (403).

And re-runs the iter49 secure-fields regression assertion:
* GET /api/auth/me + GET /api/admin/employees never expose
  temp_pin_plaintext / temp_password_plaintext / pin_hash / password_hash /
  face_reference_base64.
"""
from __future__ import annotations

import base64
import io
import os
import time
import uuid
from pathlib import Path

import pytest
import requests


# ---------------------------------------------------------------------------
# BASE URL — use frontend/.env exactly like previous iteration tests
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break

assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be defined"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"

# 1x1 PNG (67 bytes)
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+"
    "M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
# Minimal PDF header — enough to pass base64 validation; not a valid PDF.
TINY_PDF_B64 = base64.b64encode(b"%PDF-1.4\n%tiny").decode("ascii")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    return s


def _otp_login(api: requests.Session, identifier: str, channel: str = "email") -> str:
    r = api.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": identifier, "channel": channel},
    )
    assert r.status_code == 200, r.text
    code = r.json().get("code") or r.json().get("dev_code")
    assert code, f"OTP dev-code missing: {r.json()}"
    r = api.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": identifier, "channel": channel, "code": code},
    )
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token")
    assert tok
    return tok


@pytest.fixture(scope="session")
def super_token(api):
    return _otp_login(api, SUPER_ADMIN_EMAIL, "email")


@pytest.fixture(scope="session")
def sh(super_token):
    return {"Authorization": f"Bearer {super_token}",
            "Content-Type": "application/json"}


def _rand() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture(scope="session")
def scoped_company(api, sh):
    """Two companies + one employee in each — for cross-company scope tests."""
    suf = _rand()
    payload_a = {
        "name": f"TEST_Iter50_A_{suf}",
        "address": "QA-A",
        "office_lat": 12.0,
        "office_lng": 77.0,
        "geofence_radius_m": 100,
        "compliance_enabled": True,
        "admin_phone": f"+9195{int(time.time()) % 10000000:07d}",
        "admin_email": f"iter50_admin_a_{suf}@example.com",
        "admin_name": f"QA A Admin {suf}",
    }
    r = api.post(f"{BASE_URL}/api/companies", json=payload_a, headers=sh)
    assert r.status_code == 200, r.text
    a = r.json()

    suf2 = _rand()
    payload_b = {
        "name": f"TEST_Iter50_B_{suf2}",
        "address": "QA-B",
        "office_lat": 12.5,
        "office_lng": 77.5,
        "geofence_radius_m": 100,
        "compliance_enabled": True,
        "admin_phone": f"+9196{int(time.time()) % 10000000:07d}",
        "admin_email": f"iter50_admin_b_{suf2}@example.com",
        "admin_name": f"QA B Admin {suf2}",
    }
    r = api.post(f"{BASE_URL}/api/companies", json=payload_b, headers=sh)
    assert r.status_code == 200, r.text
    b = r.json()

    # Employee in company A
    emp_a = api.post(
        f"{BASE_URL}/api/auth/employee-signup",
        json={"company_code": a["company_code"],
              "name": "QA EMP A",
              "phone": f"+9194{int(time.time()) % 10000000:07d}",
              "pin": "294857",
              "email": f"iter50_emp_a_{suf}@example.com",
              "position": "Tester"},
    )
    assert emp_a.status_code in (200, 201), emp_a.text
    emp_a_uid = emp_a.json()["user_id"]

    # Employee in company B
    emp_b = api.post(
        f"{BASE_URL}/api/auth/employee-signup",
        json={"company_code": b["company_code"],
              "name": "QA EMP B",
              "phone": f"+9193{int(time.time()) % 10000000:07d}",
              "pin": "819273",
              "email": f"iter50_emp_b_{suf2}@example.com",
              "position": "Tester"},
    )
    assert emp_b.status_code in (200, 201), emp_b.text
    emp_b_uid = emp_b.json()["user_id"]

    # Approve both (so admin panel can find them)
    for uid in (emp_a_uid, emp_b_uid):
        api.patch(f"{BASE_URL}/api/admin/approve-employee",
                  json={"user_id": uid, "action": "approve"},
                  headers=sh)

    yield {
        "company_a": a, "company_b": b,
        "emp_a_uid": emp_a_uid, "emp_b_uid": emp_b_uid,
        "admin_a_email": payload_a["admin_email"],
        "admin_a_phone": payload_a["admin_phone"],
        "emp_a_email": f"iter50_emp_a_{suf}@example.com",
    }

    for cid in (a.get("company_id"), b.get("company_id")):
        try:
            api.delete(f"{BASE_URL}/api/companies/{cid}", headers=sh)
        except Exception:
            pass


@pytest.fixture(scope="session")
def employee_token(api, scoped_company):
    """Log in as the employee in company A (via OTP)."""
    return _otp_login(api, scoped_company["emp_a_email"], "email")


@pytest.fixture(scope="session")
def company_a_admin_token(api, sh, scoped_company):
    """Log in as company A's admin using their temp_pin (pin_must_change=True is OK)."""
    cid = scoped_company["company_a"]["company_id"]
    d = api.get(f"{BASE_URL}/api/companies/{cid}/details", headers=sh).json()
    temp_pin = (d.get("temp_credentials") or {}).get("temp_pin")
    if not temp_pin:
        pytest.skip("No temp_pin available for company A admin — cannot test cross-scope")
    r = api.post(f"{BASE_URL}/api/auth/admin-pin-login",
                 json={"identifier": scoped_company["admin_a_phone"], "pin": temp_pin})
    if r.status_code != 200:
        pytest.skip(f"admin-pin-login failed: {r.status_code} {r.text[:200]}")
    return r.json()["session_token"]


# ===========================================================================
# 1. Employee Master PDF (single)
# ===========================================================================
class TestMasterPdfSingle:
    def test_returns_pdf_stream(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        r = api.get(f"{BASE_URL}/api/admin/employees/{uid}/master-pdf", headers=sh)
        assert r.status_code == 200, r.text[:300]
        assert r.headers.get("content-type", "").startswith("application/pdf"), r.headers
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd.lower()
        assert ".pdf" in cd.lower()
        assert r.content.startswith(b"%PDF"), r.content[:20]
        assert len(r.content) > 2000, f"PDF suspiciously small: {len(r.content)} bytes"

    def test_inline_true_returns_inline_disposition(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        r = api.get(f"{BASE_URL}/api/admin/employees/{uid}/master-pdf?inline=true",
                    headers=sh)
        assert r.status_code == 200
        assert "inline" in r.headers.get("content-disposition", "").lower()

    def test_404_for_unknown_employee(self, api, sh):
        r = api.get(f"{BASE_URL}/api/admin/employees/unknown_xyz_123/master-pdf",
                    headers=sh)
        assert r.status_code == 404, r.text


# ===========================================================================
# 2. Bulk Master PDF
# ===========================================================================
class TestMasterPdfBulk:
    def test_super_admin_bulk_all(self, api, sh):
        r = api.get(f"{BASE_URL}/api/admin/employees/master-pdf/bulk", headers=sh)
        assert r.status_code == 200, r.text[:300]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content.startswith(b"%PDF")
        assert len(r.content) > 2000

    def test_super_admin_bulk_filtered_by_company(self, api, sh, scoped_company):
        cid = scoped_company["company_a"]["company_id"]
        r = api.get(
            f"{BASE_URL}/api/admin/employees/master-pdf/bulk?company_id={cid}",
            headers=sh,
        )
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")


# ===========================================================================
# 3. Documents CRUD
# ===========================================================================
class TestDocumentsCrud:
    def test_upload_png_ok(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        r = api.post(
            f"{BASE_URL}/api/admin/employees/{uid}/documents",
            json={
                "category": "aadhaar",
                "filename": "aadhaar.png",
                "mime_type": "image/png",
                "base64": TINY_PNG_B64,
            },
            headers=sh,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        doc = body["document"]
        # base64 must NOT be in the create response either
        assert "base64" not in doc
        assert doc["category"] == "aadhaar"
        assert doc["mime_type"] == "image/png"
        assert doc["size_bytes"] > 0
        assert doc["uploaded_by"]
        assert doc["uploaded_at"]
        pytest.iter50_doc_id = doc["doc_id"]

    def test_upload_pdf_ok(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        r = api.post(
            f"{BASE_URL}/api/admin/employees/{uid}/documents",
            json={
                "category": "offer_letter",
                "custom_label": "Offer Nov 2024",
                "filename": "offer.pdf",
                "mime_type": "application/pdf",
                "base64": TINY_PDF_B64,
            },
            headers=sh,
        )
        assert r.status_code == 200, r.text
        assert r.json()["document"]["custom_label"] == "Offer Nov 2024"

    def test_reject_invalid_category(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        r = api.post(
            f"{BASE_URL}/api/admin/employees/{uid}/documents",
            json={
                "category": "top_secret",
                "mime_type": "image/png",
                "base64": TINY_PNG_B64,
            },
            headers=sh,
        )
        assert r.status_code == 400, r.text

    def test_reject_invalid_mime(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        r = api.post(
            f"{BASE_URL}/api/admin/employees/{uid}/documents",
            json={
                "category": "aadhaar",
                "mime_type": "application/exe",
                "base64": TINY_PNG_B64,
            },
            headers=sh,
        )
        assert r.status_code == 400, r.text

    def test_reject_bad_base64(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        r = api.post(
            f"{BASE_URL}/api/admin/employees/{uid}/documents",
            json={
                "category": "aadhaar",
                "mime_type": "image/png",
                "base64": "@@@not-base64!!!",
            },
            headers=sh,
        )
        assert r.status_code == 400, r.text

    def test_reject_too_large(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        oversize = "A" * (16 * 1024 * 1024)  # 16 MB > 15 MB MAX_DOC_BASE64_LEN
        r = api.post(
            f"{BASE_URL}/api/admin/employees/{uid}/documents",
            json={
                "category": "aadhaar",
                "mime_type": "image/png",
                "base64": oversize,
            },
            headers=sh,
        )
        assert r.status_code == 413, f"{r.status_code} {r.text[:200]}"

    def test_list_docs_has_no_base64(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        r = api.get(f"{BASE_URL}/api/admin/employees/{uid}/documents", headers=sh)
        assert r.status_code == 200, r.text
        body = r.json()
        docs = body.get("documents", [])
        assert isinstance(docs, list)
        assert len(docs) >= 2, docs  # png + pdf from earlier tests
        for d in docs:
            assert "base64" not in d, f"LEAK — base64 in list response: {d}"
            assert d.get("size_bytes") is not None
            assert d.get("category") in {
                "aadhaar", "pan", "passport", "driving_license",
                "bank_passbook", "educational_certificate", "experience_letter",
                "offer_letter", "signed_contract", "photo", "other",
            }

    def test_get_single_doc_returns_base64_json(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        doc_id = getattr(pytest, "iter50_doc_id", None)
        assert doc_id
        r = api.get(
            f"{BASE_URL}/api/admin/employees/{uid}/documents/{doc_id}",
            headers=sh,
        )
        assert r.status_code == 200, r.text
        d = r.json()["document"]
        assert d["doc_id"] == doc_id
        assert d.get("base64"), "single-doc GET should return base64"

    def test_get_single_doc_inline_returns_bytes(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        doc_id = getattr(pytest, "iter50_doc_id", None)
        assert doc_id
        r = api.get(
            f"{BASE_URL}/api/admin/employees/{uid}/documents/{doc_id}?inline=true",
            headers=sh,
        )
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("content-type", "").startswith("image/png"), r.headers
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n", "PNG magic bytes missing"

    def test_delete_removes_doc(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        doc_id = getattr(pytest, "iter50_doc_id", None)
        assert doc_id
        r = api.delete(
            f"{BASE_URL}/api/admin/employees/{uid}/documents/{doc_id}",
            headers=sh,
        )
        assert r.status_code == 200, r.text
        # Subsequent GET returns 404
        r = api.get(
            f"{BASE_URL}/api/admin/employees/{uid}/documents/{doc_id}",
            headers=sh,
        )
        assert r.status_code == 404, r.text


# ===========================================================================
# 4. Access-control matrix
# ===========================================================================
class TestAccessControl:
    def test_employee_cannot_get_master_pdf(self, api, employee_token, scoped_company):
        uid = scoped_company["emp_a_uid"]
        r = api.get(
            f"{BASE_URL}/api/admin/employees/{uid}/master-pdf",
            headers={"Authorization": f"Bearer {employee_token}"},
        )
        assert r.status_code in (401, 403), r.status_code

    def test_employee_cannot_list_documents(self, api, employee_token, scoped_company):
        uid = scoped_company["emp_a_uid"]
        r = api.get(
            f"{BASE_URL}/api/admin/employees/{uid}/documents",
            headers={"Authorization": f"Bearer {employee_token}"},
        )
        assert r.status_code in (401, 403), r.status_code

    def test_employee_cannot_upload_document(self, api, employee_token, scoped_company):
        uid = scoped_company["emp_a_uid"]
        r = api.post(
            f"{BASE_URL}/api/admin/employees/{uid}/documents",
            json={"category": "aadhaar",
                  "mime_type": "image/png",
                  "base64": TINY_PNG_B64},
            headers={"Authorization": f"Bearer {employee_token}",
                     "Content-Type": "application/json"},
        )
        assert r.status_code in (401, 403), r.status_code

    def test_no_auth_is_rejected(self, api, scoped_company):
        uid = scoped_company["emp_a_uid"]
        r = api.get(f"{BASE_URL}/api/admin/employees/{uid}/master-pdf")
        assert r.status_code in (401, 403), r.status_code

    def test_company_admin_cannot_cross_scope(self, api, company_a_admin_token,
                                              scoped_company):
        # Admin A tries to access employee B (different company) — must be 403
        emp_b_uid = scoped_company["emp_b_uid"]
        r = api.get(
            f"{BASE_URL}/api/admin/employees/{emp_b_uid}/master-pdf",
            headers={"Authorization": f"Bearer {company_a_admin_token}"},
        )
        assert r.status_code == 403, f"{r.status_code} {r.text[:200]}"

        r = api.get(
            f"{BASE_URL}/api/admin/employees/{emp_b_uid}/documents",
            headers={"Authorization": f"Bearer {company_a_admin_token}"},
        )
        assert r.status_code == 403


# ===========================================================================
# 5. Regression — iter49 secure-fields must not leak
# ===========================================================================
class TestSecureFieldsRegression:
    SENSITIVE = {
        "temp_pin_plaintext", "temp_password_plaintext",
        "pin_hash", "password_hash", "face_reference_base64",
    }

    def test_auth_me_no_sensitive(self, api, super_token):
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {super_token}"})
        assert r.status_code == 200, r.text
        blob = str(r.json())
        for field in self.SENSITIVE:
            assert field not in blob, f"LEAK: {field} in /auth/me"

    def test_admin_employees_no_sensitive(self, api, sh):
        r = api.get(f"{BASE_URL}/api/admin/employees", headers=sh)
        assert r.status_code == 200, r.text
        blob = str(r.json())
        for field in self.SENSITIVE:
            assert field not in blob, f"LEAK: {field} in /admin/employees"


# ===========================================================================
# 6. Snapshot persistence
# ===========================================================================
class TestSnapshotPersistence:
    """We can't touch Mongo directly here, but we can indirectly verify the
    single-download endpoint keeps working repeatedly (idempotent + persists
    fresh copies each call — see server.py line ~8102)."""

    def test_repeated_downloads_stay_pdf(self, api, sh, scoped_company):
        uid = scoped_company["emp_a_uid"]
        sizes = []
        for _ in range(2):
            r = api.get(
                f"{BASE_URL}/api/admin/employees/{uid}/master-pdf",
                headers=sh,
            )
            assert r.status_code == 200
            assert r.content.startswith(b"%PDF")
            sizes.append(len(r.content))
        assert min(sizes) > 2000
