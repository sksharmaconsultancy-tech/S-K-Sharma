"""Iter 190 — Regression tests for
  * GET  /api/admin/kyc-tracker           (new)
  * PATCH /api/admin/employees/{uid}/kyc  (dl_valid_upto / passport_valid_upto)
  * Refactored employee document endpoints (routes/employee_documents.py)
"""
import base64
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
KANKANI = "cmp_527fecdd7c"


# --------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
                      timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def super_headers(super_token):
    return {"Authorization": f"Bearer {super_token}"}


@pytest.fixture(scope="module")
def test50_uid(super_headers):
    """Locate SURENDRA SINGH (code 50) — used for KYC + document tests."""
    r = requests.get(f"{BASE_URL}/api/admin/employees",
                     params={"company_id": KANKANI},
                     headers=super_headers, timeout=30)
    assert r.status_code == 200
    data = r.json()
    # normalise possible shapes
    emps = data.get("employees") if isinstance(data, dict) else data
    if isinstance(emps, dict) and "items" in emps:
        emps = emps["items"]
    assert emps, "no employees returned"
    match = next((e for e in emps if str(e.get("employee_code")) == "50"), None)
    assert match, "employee code 50 not found"
    return match["user_id"]


@pytest.fixture(scope="module")
def emp_token():
    """PIN-login as TEST50 (Username TEST50, PIN 123456)."""
    r = requests.post(f"{BASE_URL}/api/auth/pin-login",
                      json={"login_id": "TEST50", "pin": "123456"},
                      timeout=30)
    if r.status_code != 200:
        # Some builds expect username field name
        r = requests.post(f"{BASE_URL}/api/auth/pin-login",
                          json={"username": "TEST50", "pin": "123456"},
                          timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("session_token") or j.get("token")


# --------------------------------------------------------------------------- KYC tracker
class TestKycTracker:
    def test_kyc_tracker_all_firms(self, super_headers):
        r = requests.get(f"{BASE_URL}/api/admin/kyc-tracker",
                         headers=super_headers, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "summary" in j and "employees" in j
        s = j["summary"]
        for k in ("total", "complete", "incomplete", "missing_aadhaar",
                  "missing_pan", "missing_bank", "expiring", "expired"):
            assert k in s, f"missing summary key {k}"
            assert isinstance(s[k], int)
        assert s["total"] == len(j["employees"])
        assert s["total"] > 0

    def test_kyc_tracker_kankani_scope(self, super_headers):
        r = requests.get(f"{BASE_URL}/api/admin/kyc-tracker",
                         params={"company_id": KANKANI},
                         headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        # Kankani ~125 employees — verify 100 <= total <= 200 to be lenient
        assert 100 <= j["summary"]["total"] <= 200, f"unexpected total {j['summary']['total']}"
        for e in j["employees"]:
            assert e["company_id"] == KANKANI


# --------------------------------------------------------------------------- KYC PATCH — expiry fields
class TestKycExpiryPatch:
    def test_patch_dl_valid_upto_iso_marks_expired(self, super_headers, test50_uid):
        # 2026-05-01 is in the past (container date Jul 2026) → status=expired
        r = requests.patch(f"{BASE_URL}/api/admin/employees/{test50_uid}/kyc",
                           json={"dl_valid_upto": "2026-05-01"},
                           headers=super_headers, timeout=30)
        assert r.status_code == 200, r.text
        # PATCH response echo omits expiry keys (see employee_kyc.py `keys` list) — minor
        assert "dl_valid_upto" in r.json().get("updated_keys", [])

        r2 = requests.get(f"{BASE_URL}/api/admin/kyc-tracker",
                          params={"company_id": KANKANI},
                          headers=super_headers, timeout=30)
        emp = next((e for e in r2.json()["employees"] if e["user_id"] == test50_uid), None)
        assert emp is not None
        assert emp["dl_valid_upto"] == "2026-05-01"
        assert emp["status"] == "expired", f"expected expired, got {emp['status']}"
        assert "dl_valid_upto" in emp["expired_docs"]

    def test_patch_ddmmyyyy_format_accepted(self, super_headers, test50_uid):
        r = requests.patch(f"{BASE_URL}/api/admin/employees/{test50_uid}/kyc",
                           json={"dl_valid_upto": "15-06-2026"},
                           headers=super_headers, timeout=30)
        assert r.status_code == 200, r.text
        assert "dl_valid_upto" in r.json().get("updated_keys", [])
        # Verify via kyc-tracker (real read path)
        r2 = requests.get(f"{BASE_URL}/api/admin/kyc-tracker",
                          params={"company_id": KANKANI},
                          headers=super_headers, timeout=30)
        emp = next((e for e in r2.json()["employees"] if e["user_id"] == test50_uid), None)
        assert emp is not None
        assert emp["dl_valid_upto"] == "2026-06-15", f"got {emp['dl_valid_upto']}"

    def test_patch_invalid_date_rejected(self, super_headers, test50_uid):
        r = requests.patch(f"{BASE_URL}/api/admin/employees/{test50_uid}/kyc",
                           json={"dl_valid_upto": "notadate"},
                           headers=super_headers, timeout=30)
        assert r.status_code == 400, r.text

    def test_patch_empty_string_clears(self, super_headers, test50_uid):
        r = requests.patch(f"{BASE_URL}/api/admin/employees/{test50_uid}/kyc",
                           json={"dl_valid_upto": "", "passport_valid_upto": ""},
                           headers=super_headers, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["kyc"].get("dl_valid_upto") is None
        # verify via kyc-tracker
        r2 = requests.get(f"{BASE_URL}/api/admin/kyc-tracker",
                          params={"company_id": KANKANI},
                          headers=super_headers, timeout=30)
        emp = next((e for e in r2.json()["employees"] if e["user_id"] == test50_uid), None)
        assert emp is not None
        assert emp["dl_valid_upto"] is None


# --------------------------------------------------------------------------- Refactored document endpoints
# 1x1 transparent PNG
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


class TestEmployeeDocuments:
    doc_id: str | None = None

    def test_list_documents_initial(self, super_headers, test50_uid):
        r = requests.get(f"{BASE_URL}/api/admin/employees/{test50_uid}/documents",
                         headers=super_headers, timeout=30)
        assert r.status_code == 200
        assert "documents" in r.json()

    def test_upload_aadhaar_doc(self, super_headers, test50_uid):
        payload = {
            "category": "aadhaar",
            "mime_type": "image/png",
            "base64": TINY_PNG_B64,
            "filename": "TEST_iter190_aadhaar.png",
        }
        r = requests.post(f"{BASE_URL}/api/admin/employees/{test50_uid}/documents",
                          json=payload, headers=super_headers, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        doc_id = j["document"]["doc_id"]
        assert doc_id
        TestEmployeeDocuments.doc_id = doc_id

    def test_get_doc_inline_returns_png(self, super_headers, test50_uid):
        assert TestEmployeeDocuments.doc_id, "prior upload didn't run"
        r = requests.get(
            f"{BASE_URL}/api/admin/employees/{test50_uid}/documents/{TestEmployeeDocuments.doc_id}",
            params={"inline": "true"},
            headers=super_headers, timeout=30)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/png")
        assert len(r.content) > 0

    def test_kyc_tracker_picks_up_uploaded_aadhaar(self, super_headers, test50_uid):
        r = requests.get(f"{BASE_URL}/api/admin/kyc-tracker",
                         params={"company_id": KANKANI},
                         headers=super_headers, timeout=30)
        emp = next((e for e in r.json()["employees"] if e["user_id"] == test50_uid), None)
        assert emp is not None
        assert "aadhaar" in emp["uploaded_docs"], f"expected aadhaar in uploaded_docs: {emp['uploaded_docs']}"

    def test_master_pdf_returns_pdf(self, super_headers, test50_uid):
        r = requests.get(f"{BASE_URL}/api/admin/employees/{test50_uid}/master-pdf",
                         headers=super_headers, timeout=60)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_me_documents_as_employee(self, emp_token):
        assert emp_token, "employee login failed"
        r = requests.get(f"{BASE_URL}/api/me/documents",
                         headers={"Authorization": f"Bearer {emp_token}"},
                         timeout=30)
        assert r.status_code == 200
        assert "documents" in r.json()

    def test_delete_uploaded_doc_cleanup(self, super_headers, test50_uid):
        assert TestEmployeeDocuments.doc_id, "no doc to delete"
        r = requests.delete(
            f"{BASE_URL}/api/admin/employees/{test50_uid}/documents/{TestEmployeeDocuments.doc_id}",
            headers=super_headers, timeout=30)
        assert r.status_code == 200, r.text
        # Verify gone
        r2 = requests.get(
            f"{BASE_URL}/api/admin/employees/{test50_uid}/documents/{TestEmployeeDocuments.doc_id}",
            headers=super_headers, timeout=30)
        assert r2.status_code == 404
