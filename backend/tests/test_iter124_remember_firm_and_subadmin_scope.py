"""
Iter 124 backend regression tests.

Two features tested:
1. Remember last firm — GET/PATCH /api/me/last-company (super + sub admin;
   employee-role token = 403).
2. Sub-admin "Not your firm" fix — sub admin now behaves like super admin
   across all firms in sub_admin_company_scope for:
      * GET /api/admin/challans?company_id=...
      * GET /api/admin/firm-master/{company_id}
      * GET /api/admin/employees/{uid}/kyc
      * GET /api/admin/employees/{uid}/salary
      * GET /api/admin/leave-report?company_id=...&year=...
   Plus super-admin regression on same endpoints.
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PASS = "sharma123"
SUB_EMAIL = "testsub@sksharma.co"
SUB_PASS = "testsub123"

KANKANI_COMPANY_ID = "cmp_527fecdd7c"
EMPLOYEE_UID = "user_94e190f2843e"

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
def employee_token():
    r = requests.post(f"{BASE_URL}/api/auth/pin-login",
                      json={"phone": "+919000000101", "pin": "654321"}, timeout=30)
    if r.status_code == 200:
        return r.json().get("session_token")
    return None


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------- Feature 1: Remember last firm ----------
class TestLastCompanySuperAdmin:
    def test_patch_and_get_persists(self, super_token):
        r = requests.patch(f"{BASE_URL}/api/me/last-company",
                           json={"company_id": KANKANI_COMPANY_ID},
                           headers=_hdr(super_token), timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("company_id") == KANKANI_COMPANY_ID

        r2 = requests.get(f"{BASE_URL}/api/me/last-company",
                          headers=_hdr(super_token), timeout=30)
        assert r2.status_code == 200, r2.text[:300]
        assert r2.json().get("company_id") == KANKANI_COMPANY_ID

    def test_patch_null_clears(self, super_token):
        r = requests.patch(f"{BASE_URL}/api/me/last-company",
                           json={"company_id": None},
                           headers=_hdr(super_token), timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("company_id") is None

        r2 = requests.get(f"{BASE_URL}/api/me/last-company",
                          headers=_hdr(super_token), timeout=30)
        assert r2.status_code == 200
        assert r2.json().get("company_id") in (None, "")


class TestLastCompanySubAdmin:
    def test_patch_and_get_persists(self, sub_token):
        r = requests.patch(f"{BASE_URL}/api/me/last-company",
                           json={"company_id": KANKANI_COMPANY_ID},
                           headers=_hdr(sub_token), timeout=30)
        assert r.status_code == 200, r.text[:300]

        r2 = requests.get(f"{BASE_URL}/api/me/last-company",
                          headers=_hdr(sub_token), timeout=30)
        assert r2.status_code == 200
        assert r2.json().get("company_id") == KANKANI_COMPANY_ID


class TestLastCompanyEmployeeForbidden:
    def test_employee_get_forbidden(self, employee_token):
        if not employee_token:
            pytest.skip("no employee token")
        r = requests.get(f"{BASE_URL}/api/me/last-company",
                         headers=_hdr(employee_token), timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}: {r.text[:200]}"

    def test_employee_patch_forbidden(self, employee_token):
        if not employee_token:
            pytest.skip("no employee token")
        r = requests.patch(f"{BASE_URL}/api/me/last-company",
                           json={"company_id": KANKANI_COMPANY_ID},
                           headers=_hdr(employee_token), timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}: {r.text[:200]}"


# ---------- Feature 2: Sub-admin "Not your firm" fix ----------
class TestSubAdminNotYourFirmFix:
    """Sub admin (scope=all) must 200 on all firm-scoped endpoints."""

    def test_challans_list(self, sub_token):
        r = requests.get(f"{BASE_URL}/api/admin/challans",
                         params={"company_id": KANKANI_COMPANY_ID},
                         headers=_hdr(sub_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_firm_master_get(self, sub_token):
        r = requests.get(f"{BASE_URL}/api/admin/firm-master/{KANKANI_COMPANY_ID}",
                         headers=_hdr(sub_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        j = r.json()
        assert j.get("company_id") == KANKANI_COMPANY_ID or j.get("_id") is None

    def test_employee_kyc(self, sub_token):
        r = requests.get(f"{BASE_URL}/api/admin/employees/{EMPLOYEE_UID}/kyc",
                         headers=_hdr(sub_token), timeout=30)
        # Endpoint may return 200 for existing employee or 404 if uid was purged.
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_employee_salary(self, sub_token):
        r = requests.get(f"{BASE_URL}/api/admin/employees/{EMPLOYEE_UID}/salary",
                         headers=_hdr(sub_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_leave_report(self, sub_token):
        r = requests.get(f"{BASE_URL}/api/admin/leave-report",
                         params={"company_id": KANKANI_COMPANY_ID, "year": 2026},
                         headers=_hdr(sub_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"


class TestSuperAdminRegression:
    """Super admin must still 200 on same endpoints."""

    def test_challans_list(self, super_token):
        r = requests.get(f"{BASE_URL}/api/admin/challans",
                         params={"company_id": KANKANI_COMPANY_ID},
                         headers=_hdr(super_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_firm_master_get(self, super_token):
        r = requests.get(f"{BASE_URL}/api/admin/firm-master/{KANKANI_COMPANY_ID}",
                         headers=_hdr(super_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_employee_kyc(self, super_token):
        r = requests.get(f"{BASE_URL}/api/admin/employees/{EMPLOYEE_UID}/kyc",
                         headers=_hdr(super_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_employee_salary(self, super_token):
        r = requests.get(f"{BASE_URL}/api/admin/employees/{EMPLOYEE_UID}/salary",
                         headers=_hdr(super_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_leave_report(self, super_token):
        r = requests.get(f"{BASE_URL}/api/admin/leave-report",
                         params={"company_id": KANKANI_COMPANY_ID, "year": 2026},
                         headers=_hdr(super_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
