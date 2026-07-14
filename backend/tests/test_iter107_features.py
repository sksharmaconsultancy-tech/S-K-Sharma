"""Iter 107 backend tests
  1) admin-password-login with email / mobile (multiple formats) — sub_admin
  2) super_admin email login regression
  3) pincode lookup (valid, invalid, cached)
  4) firm-master GET category auto-fill + PATCH start_date persistence
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or os.environ["EXPO_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

SUB_EMAIL = "testsub@sksharma.co"
SUB_PASSWORD = "subadmin123"
SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PASSWORD = "sharma123"
CITY_CARE_ID = "cmp_987f0d7da5"


# --- Auth ---------------------------------------------------------------

class TestAdminPasswordLogin:
    """Iter 107 — mobile-number login for sub/super admins"""

    @pytest.mark.parametrize("ident", [
        SUB_EMAIL,
        "+919000000555",
        "9000000555",
        "09000000555",
    ])
    def test_sub_admin_login_identifiers(self, ident):
        r = requests.post(f"{API}/auth/admin-password-login",
                          json={"email": ident, "password": SUB_PASSWORD}, timeout=15)
        assert r.status_code == 200, f"{ident} -> {r.status_code} {r.text}"
        body = r.json()
        assert body.get("session_token")
        assert body["user"]["role"] == "sub_admin"
        assert body["user"]["user_id"] == "sub_623b8a106846"

    def test_sub_admin_wrong_password(self):
        r = requests.post(f"{API}/auth/admin-password-login",
                          json={"email": "+919000000555", "password": "nope"}, timeout=15)
        assert r.status_code in (401, 429), f"got {r.status_code} {r.text}"

    def test_super_admin_email_login_regression(self):
        r = requests.post(f"{API}/auth/admin-password-login",
                          json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["role"] == "super_admin"


# --- Pincode lookup -----------------------------------------------------

class TestPincodeLookup:
    def test_valid_pin(self):
        r = requests.get(f"{API}/pincode/311001", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert data.get("state") == "Rajasthan"
        assert data.get("district") == "Bhilwara"

    def test_invalid_pin_length(self):
        r = requests.get(f"{API}/pincode/12345", timeout=15)
        assert r.status_code == 400

    def test_cache_returns_same_data(self):
        r1 = requests.get(f"{API}/pincode/311001", timeout=15).json()
        r2 = requests.get(f"{API}/pincode/311001", timeout=15).json()
        assert r1 == r2
        assert r2.get("state") == "Rajasthan"


# --- Firm-master --------------------------------------------------------

@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{API}/auth/admin-password-login",
                      json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD}, timeout=15)
    r.raise_for_status()
    return r.json()["session_token"]


class TestFirmMaster:
    def test_category_auto_fills_hospital(self, super_token):
        r = requests.get(f"{API}/admin/firm-master/{CITY_CARE_ID}",
                         headers={"Authorization": f"Bearer {super_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        master = r.json().get("master") or r.json()
        header = master.get("header", {}) or {}
        assert (header.get("category") or "").lower().startswith("hospital"), header

    def test_start_date_patch_persists(self, super_token):
        headers = {"Authorization": f"Bearer {super_token}"}
        # fetch current
        cur = requests.get(f"{API}/admin/firm-master/{CITY_CARE_ID}", headers=headers, timeout=15).json()
        cur_master = cur.get("master") or cur
        cur_header = cur_master.get("header", {}) or {}
        cur_header["start_date"] = "2024-04-01"
        # PATCH
        r = requests.patch(f"{API}/admin/firm-master/{CITY_CARE_ID}",
                           headers=headers, json={"header": cur_header}, timeout=15)
        assert r.status_code in (200, 204), r.text
        # verify persistence via GET
        again = requests.get(f"{API}/admin/firm-master/{CITY_CARE_ID}", headers=headers, timeout=15).json()
        again_master = again.get("master") or again
        assert again_master["header"].get("start_date") == "2024-04-01", again_master["header"]


# --- Regression: employee pin login + join-qr etc. ----------------------

class TestRegression:
    def test_employee_pin_login(self):
        r = requests.post(f"{API}/auth/pin-login",
                          json={"phone": "+919000000101", "pin": "654321"}, timeout=15)
        assert r.status_code == 200, r.text
        u = r.json()["user"]
        assert u["role"] == "employee"
