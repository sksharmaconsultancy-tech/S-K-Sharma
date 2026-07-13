"""Iter 96 - Verifies:
1. Super Admin password-login works (sksharma / sharma123)
2. POST /api/admin/employee-credentials sets login_id + pin + password on a real employee
3. Employee can log in via POST /api/auth/pin-login  {login_id, pin}
4. Employee can log in via POST /api/auth/employee-password-login {login_id, password}
5. /companies/lookup/{code} returns Kankani company info for the signup pre-fill
"""

import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

SUPER_LOGIN = "sksharma"
SUPER_PASSWORD = "sharma123"
COMPANY_ID = "cmp_527fecdd7c"
COMPANY_CODE = "KEPS"

TEST_LOGIN_ID = f"TESTIter96{int(time.time())}"[:24]
TEST_PIN = "912837"
TEST_PASSWORD = "TestPass!96"


@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{API}/auth/admin-password-login",
                      json={"email": SUPER_LOGIN, "password": SUPER_PASSWORD},
                      timeout=30)
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token")
    assert tok, "no session_token in super-admin login"
    return tok


@pytest.fixture(scope="module")
def employee_user_id(super_token):
    """Fetch a real Kankani employee to use as the target of credential updates."""
    r = requests.get(f"{API}/admin/employees",
                     params={"company_id": COMPANY_ID, "limit": 5},
                     headers={"Authorization": f"Bearer {super_token}"},
                     timeout=30)
    assert r.status_code == 200, r.text
    payload = r.json()
    rows = payload.get("items") or payload.get("employees") or payload if isinstance(payload, list) else payload.get("items") or []
    if not rows and isinstance(payload, dict):
        # Try common alternate shapes
        for k in ("data", "results", "employees"):
            if isinstance(payload.get(k), list):
                rows = payload[k]
                break
    assert rows, f"no employees returned: {payload}"
    for u in rows:
        uid = u.get("user_id")
        if uid:
            return uid
    pytest.fail("no user_id found in employees list")


class TestInstallEntryFlow:
    def test_super_admin_login(self, super_token):
        assert isinstance(super_token, str) and len(super_token) > 20

    def test_company_lookup_public(self):
        r = requests.get(f"{API}/companies/lookup/{COMPANY_CODE}", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("company_id") == COMPANY_ID
        assert d.get("company_code") == COMPANY_CODE
        assert d.get("name")

    def test_company_lookup_bad_code(self):
        r = requests.get(f"{API}/companies/lookup/NOSUCH_XYZ", timeout=15)
        assert r.status_code == 404

    def test_set_credentials_and_verify_logins(self, super_token, employee_user_id):
        # 1) Admin sets login_id + pin + password
        body = {
            "user_id": employee_user_id,
            "login_id": TEST_LOGIN_ID,
            "pin": TEST_PIN,
            "password": TEST_PASSWORD,
        }
        r = requests.post(f"{API}/admin/employee-credentials", json=body,
                          headers={"Authorization": f"Bearer {super_token}"},
                          timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert d.get("login_id") == TEST_LOGIN_ID
        assert d.get("has_pin") is True
        assert d.get("has_password") is True

        # 2) Employee logs in with username + PIN
        r2 = requests.post(f"{API}/auth/pin-login",
                           json={"login_id": TEST_LOGIN_ID, "pin": TEST_PIN},
                           timeout=20)
        assert r2.status_code == 200, r2.text
        j2 = r2.json()
        assert j2.get("session_token")
        assert j2.get("user", {}).get("user_id") == employee_user_id

        # 3) Employee logs in with username + password
        r3 = requests.post(f"{API}/auth/employee-password-login",
                           json={"login_id": TEST_LOGIN_ID, "password": TEST_PASSWORD},
                           timeout=20)
        assert r3.status_code == 200, r3.text
        j3 = r3.json()
        assert j3.get("session_token")
        assert j3.get("user", {}).get("user_id") == employee_user_id

        # 4) Wrong password rejected
        r4 = requests.post(f"{API}/auth/employee-password-login",
                           json={"login_id": TEST_LOGIN_ID, "password": "WrongPw!123"},
                           timeout=20)
        assert r4.status_code in (401, 403)

    def test_duplicate_username_rejected(self, super_token, employee_user_id):
        # Fetch another employee to try to reuse login_id
        r = requests.get(f"{API}/admin/employees",
                        params={"company_id": COMPANY_ID, "limit": 10},
                        headers={"Authorization": f"Bearer {super_token}"},
                        timeout=30)
        assert r.status_code == 200
        payload = r.json()
        rows = payload.get("items") or payload.get("employees") or []
        if isinstance(payload, list):
            rows = payload
        other = None
        for u in rows:
            if u.get("user_id") and u["user_id"] != employee_user_id:
                other = u["user_id"]; break
        if not other:
            pytest.skip("no second employee available")
        r2 = requests.post(f"{API}/admin/employee-credentials",
                           json={"user_id": other, "login_id": TEST_LOGIN_ID},
                           headers={"Authorization": f"Bearer {super_token}"},
                           timeout=20)
        assert r2.status_code == 409, r2.text
