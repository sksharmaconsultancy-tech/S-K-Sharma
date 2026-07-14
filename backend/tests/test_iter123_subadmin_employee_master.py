"""
Iter 123 regression: Sub-admin permissions for Employee Master endpoints.

Tests:
- Sub admin (testsub@sksharma.co) 200s on:
  GET  /admin/employees/{uid}/policy
  PATCH /admin/user-role  (department only)
  GET  /admin/employees/{uid}/documents
  GET  /admin/employees/{uid}/master-pdf
  GET  /admin/employees/{uid}/attendance-policy-override
- Sub admin negatives (role/company_id change) -> 403
- Super admin regression: all endpoints still 200
- Employee token: 403 on same admin endpoints
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PASS = "sharma123"
SUB_EMAIL = "testsub@sksharma.co"
SUB_PASS = "testsub123"

# Known Kankani employee for scoped tests
KANKANI_COMPANY_ID = "cmp_527fecdd7c"


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": SUPER_EMAIL, "password": SUPER_PASS}, timeout=30)
    assert r.status_code == 200, f"super login failed: {r.status_code} {r.text[:200]}"
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def sub_token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": SUB_EMAIL, "password": SUB_PASS}, timeout=30)
    assert r.status_code == 200, f"sub login failed: {r.status_code} {r.text[:200]}"
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def sample_employee(super_token):
    """Grab one Kankani employee for testing."""
    hdr = {"Authorization": f"Bearer {super_token}"}
    r = requests.get(f"{BASE_URL}/api/admin/employees",
                     params={"company_id": KANKANI_COMPANY_ID, "limit": 5},
                     headers=hdr, timeout=30)
    assert r.status_code == 200, f"employees list failed: {r.status_code} {r.text[:200]}"
    j = r.json()
    items = j if isinstance(j, list) else j.get("items") or j.get("employees") or []
    assert items, f"no employees returned: {j}"
    emp = items[0]
    uid = emp.get("user_id") or emp.get("id")
    assert uid, f"no user_id: {emp}"
    return {"user_id": uid, "company_id": emp.get("company_id") or KANKANI_COMPANY_ID}


@pytest.fixture(scope="module")
def employee_token():
    """Employee-role session for negative-403 checks. Uses CCH001 nurse."""
    r = requests.post(f"{BASE_URL}/api/auth/pin-login",
                      json={"phone": "+919000000101", "pin": "654321"},
                      timeout=30)
    if r.status_code == 200:
        return r.json().get("session_token")
    return None


# ---------- Sub-admin positive cases ----------
class TestSubAdminPositive:
    def test_get_policy(self, sub_token, sample_employee):
        h = {"Authorization": f"Bearer {sub_token}"}
        r = requests.get(f"{BASE_URL}/api/admin/employees/{sample_employee['user_id']}/policy",
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert isinstance(r.json(), dict)

    def test_patch_user_role_department(self, sub_token, sample_employee):
        h = {"Authorization": f"Bearer {sub_token}"}
        payload = {"user_id": sample_employee["user_id"], "department": "QA-Test-Iter123"}
        r = requests.patch(f"{BASE_URL}/api/admin/user-role", json=payload, headers=h, timeout=30)
        assert r.status_code == 200, r.text[:300]

    def test_get_documents(self, sub_token, sample_employee):
        h = {"Authorization": f"Bearer {sub_token}"}
        r = requests.get(f"{BASE_URL}/api/admin/employees/{sample_employee['user_id']}/documents",
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text[:300]

    def test_get_master_pdf(self, sub_token, sample_employee):
        h = {"Authorization": f"Bearer {sub_token}"}
        r = requests.get(f"{BASE_URL}/api/admin/employees/{sample_employee['user_id']}/master-pdf",
                         headers=h, timeout=60)
        assert r.status_code == 200, r.text[:300]
        # Content-Type PDF or bytes start with %PDF
        ct = r.headers.get("content-type", "")
        assert "pdf" in ct.lower() or r.content[:4] == b"%PDF", f"not a PDF: ct={ct} head={r.content[:8]!r}"

    def test_get_attendance_policy_override(self, sub_token, sample_employee):
        h = {"Authorization": f"Bearer {sub_token}"}
        r = requests.get(
            f"{BASE_URL}/api/admin/employees/{sample_employee['user_id']}/attendance-policy-override",
            headers=h, timeout=30)
        assert r.status_code == 200, r.text[:300]


# ---------- Sub-admin negative cases ----------
class TestSubAdminNegative:
    def test_role_change_forbidden(self, sub_token, sample_employee):
        h = {"Authorization": f"Bearer {sub_token}"}
        payload = {"user_id": sample_employee["user_id"], "role": "company_admin"}
        r = requests.patch(f"{BASE_URL}/api/admin/user-role", json=payload, headers=h, timeout=30)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:300]}"
        # Message should reference super-admin gating
        msg = (r.json().get("detail") or "").lower() if r.headers.get("content-type", "").startswith("application/json") else ""
        assert "super" in msg or "role" in msg, f"unexpected detail: {msg}"

    def test_company_reassign_forbidden(self, sub_token, sample_employee):
        h = {"Authorization": f"Bearer {sub_token}"}
        payload = {"user_id": sample_employee["user_id"], "company_id": "cmp_987f0d7da5"}
        r = requests.patch(f"{BASE_URL}/api/admin/user-role", json=payload, headers=h, timeout=30)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:300]}"


# ---------- Super-admin regression ----------
class TestSuperAdminRegression:
    def test_get_policy(self, super_token, sample_employee):
        h = {"Authorization": f"Bearer {super_token}"}
        r = requests.get(f"{BASE_URL}/api/admin/employees/{sample_employee['user_id']}/policy",
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text[:300]

    def test_patch_user_role_department(self, super_token, sample_employee):
        h = {"Authorization": f"Bearer {super_token}"}
        payload = {"user_id": sample_employee["user_id"], "department": "QA-Super-Iter123"}
        r = requests.patch(f"{BASE_URL}/api/admin/user-role", json=payload, headers=h, timeout=30)
        assert r.status_code == 200, r.text[:300]

    def test_get_documents(self, super_token, sample_employee):
        h = {"Authorization": f"Bearer {super_token}"}
        r = requests.get(f"{BASE_URL}/api/admin/employees/{sample_employee['user_id']}/documents",
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text[:300]

    def test_get_master_pdf(self, super_token, sample_employee):
        h = {"Authorization": f"Bearer {super_token}"}
        r = requests.get(f"{BASE_URL}/api/admin/employees/{sample_employee['user_id']}/master-pdf",
                         headers=h, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:4] == b"%PDF"

    def test_master_pdf_bulk(self, super_token, sample_employee):
        h = {"Authorization": f"Bearer {super_token}"}
        r = requests.get(f"{BASE_URL}/api/admin/employees/master-pdf/bulk",
                         params={"company_id": sample_employee["company_id"]},
                         headers=h, timeout=120)
        assert r.status_code == 200, f"bulk pdf status {r.status_code}: {r.text[:200]}"
        assert r.content[:4] == b"%PDF", f"not pdf bytes: {r.content[:8]!r}"

    def test_attendance_policy_override(self, super_token, sample_employee):
        h = {"Authorization": f"Bearer {super_token}"}
        r = requests.get(
            f"{BASE_URL}/api/admin/employees/{sample_employee['user_id']}/attendance-policy-override",
            headers=h, timeout=30)
        assert r.status_code == 200, r.text[:300]


# ---------- Employee-token negatives ----------
class TestEmployeeTokenNegative:
    def test_policy_forbidden(self, employee_token, sample_employee):
        if not employee_token:
            pytest.skip("no employee token available")
        h = {"Authorization": f"Bearer {employee_token}"}
        r = requests.get(f"{BASE_URL}/api/admin/employees/{sample_employee['user_id']}/policy",
                         headers=h, timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}: {r.text[:200]}"

    def test_user_role_forbidden(self, employee_token, sample_employee):
        if not employee_token:
            pytest.skip("no employee token available")
        h = {"Authorization": f"Bearer {employee_token}"}
        r = requests.patch(f"{BASE_URL}/api/admin/user-role",
                           json={"user_id": sample_employee["user_id"], "department": "hack"},
                           headers=h, timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}: {r.text[:200]}"

    def test_master_pdf_forbidden(self, employee_token, sample_employee):
        if not employee_token:
            pytest.skip("no employee token available")
        h = {"Authorization": f"Bearer {employee_token}"}
        r = requests.get(f"{BASE_URL}/api/admin/employees/{sample_employee['user_id']}/master-pdf",
                         headers=h, timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}: {r.text[:200]}"
