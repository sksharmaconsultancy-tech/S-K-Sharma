"""Iter 165 — Fingerprint verification gating (admin-controlled per employee,
firm-master gated). Tests run against the deployed backend URL and mutate
Mongo directly for the firm-master flag; ALL mutations are restored.
"""
import os
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

COMPANY_ID = "cmp_527fecdd7c"
EMP_USER_ID = "user_44cd6f561da0"
EMP_LOGIN_ID = "TEST50"
EMP_PIN = "123456"


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def super_admin_token(api_client):
    r = api_client.post(f"{BASE_URL}/api/auth/admin-password-login",
                        json={"email": "sksharmaconsultancy@gmail.com",
                              "password": "sharma123"})
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token")
    assert tok, r.text
    return tok


@pytest.fixture(scope="module")
def employee_token(api_client):
    r = api_client.post(f"{BASE_URL}/api/auth/pin-login",
                        json={"login_id": EMP_LOGIN_ID, "pin": EMP_PIN})
    assert r.status_code == 200, r.text
    return r.json().get("session_token")


# ---- state helpers ----
def _set_firm_bio(mongo, enabled: bool):
    mongo.firm_masters.update_one(
        {"company_id": COMPANY_ID},
        {"$set": {"salary_process.bio_matrix_attendance": enabled}},
        upsert=True,
    )


def _get_firm_bio(mongo) -> bool:
    fm = mongo.firm_masters.find_one({"company_id": COMPANY_ID})
    return bool(((fm or {}).get("salary_process") or {}).get("bio_matrix_attendance"))


def _patch_role(api_client, tok, **body):
    body.setdefault("user_id", EMP_USER_ID)
    return api_client.patch(
        f"{BASE_URL}/api/admin/user-role",
        json=body,
        headers={"Authorization": f"Bearer {tok}"},
    )


# ---- module-scope cleanup: restore all state at the very end ----
@pytest.fixture(scope="module", autouse=True)
def _final_cleanup(mongo, api_client, super_admin_token):
    # snapshot initial firm_bio value (should be False)
    initial_bio = _get_firm_bio(mongo)
    yield
    # Restore firm bio
    _set_firm_bio(mongo, initial_bio)
    # Force fingerprint_required=false on user
    api_client.patch(
        f"{BASE_URL}/api/admin/user-role",
        json={"user_id": EMP_USER_ID, "fingerprint_required": False},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    # unset fingerprint enrolment fields
    mongo.users.update_one(
        {"user_id": EMP_USER_ID},
        {"$unset": {"fingerprint_enrolled_at": "", "fingerprint_device": ""}},
    )


# ---- Tests ----

class TestFingerprintGate:
    def test_01_initial_firm_bio_disabled(self, mongo):
        # Precondition (should be False per PRD)
        assert _get_firm_bio(mongo) is False, (
            "Precondition failed: firm bio_matrix_attendance expected False")

    def test_02_patch_fp_required_true_blocked_when_bio_disabled(
            self, api_client, super_admin_token, mongo):
        assert _get_firm_bio(mongo) is False
        r = _patch_role(api_client, super_admin_token, fingerprint_required=True)
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", "")
        assert "Fingerprint verification is not allowed" in detail, detail

    def test_03_patch_fp_required_false_allowed_when_bio_disabled(
            self, api_client, super_admin_token):
        r = _patch_role(api_client, super_admin_token, fingerprint_required=False)
        assert r.status_code == 200, r.text

    def test_04_flip_firm_bio_true_then_patch_true_ok(
            self, api_client, super_admin_token, mongo):
        _set_firm_bio(mongo, True)
        assert _get_firm_bio(mongo) is True
        r = _patch_role(api_client, super_admin_token, fingerprint_required=True)
        assert r.status_code == 200, r.text
        # Verify persisted
        u = mongo.users.find_one({"user_id": EMP_USER_ID})
        assert u.get("fingerprint_required") is True

    def test_05_employee_me_shows_effective_true(
            self, api_client, employee_token, mongo):
        # firm bio is True from previous test
        assert _get_firm_bio(mongo) is True
        r = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {employee_token}"})
        assert r.status_code == 200, r.text
        u = r.json().get("user") or {}
        assert u.get("firm_biometric_enabled") is True, u
        assert u.get("fingerprint_required") is True, u
        assert u.get("effective_fingerprint_required") is True, u

    def test_06_record_fingerprint_enrolled(
            self, api_client, employee_token, mongo):
        r = api_client.post(
            f"{BASE_URL}/api/me/fingerprint/enrolled",
            json={"device": "web-pwa"},
            headers={"Authorization": f"Bearer {employee_token}"})
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True
        u = mongo.users.find_one({"user_id": EMP_USER_ID})
        assert u.get("fingerprint_enrolled_at"), u
        assert u.get("fingerprint_device") == "web-pwa", u

    def test_07_flip_firm_bio_false_effective_flips_false(
            self, api_client, employee_token, mongo):
        _set_firm_bio(mongo, False)
        # user doc still has fingerprint_required=true
        u_doc = mongo.users.find_one({"user_id": EMP_USER_ID})
        assert u_doc.get("fingerprint_required") is True
        r = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {employee_token}"})
        assert r.status_code == 200, r.text
        u = r.json().get("user") or {}
        assert u.get("firm_biometric_enabled") is False, u
        # fingerprint_required user-flag stays True
        assert u.get("fingerprint_required") is True, u
        # but effective is False because firm flag is off
        assert u.get("effective_fingerprint_required") is False, u
