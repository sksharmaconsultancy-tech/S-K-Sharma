"""Iteration 27 — Phase D tests (Bank details in KYC + geofence-auto punch source
+ nested company on /auth/me).

Coverage:
  1. KYC GET returns bank fields (initially null)
  2. KYC PATCH bank fields — happy path (digit strip, IFSC upper, clear w/ "")
  3. KYC PATCH bank fields — validation (short account num, bad IFSC)
  4. AttendancePunch model accepts source (manual default / geofence-auto)
  5. _enrich_user_with_company: /auth/me returns nested `company` block for
     employee with company containing office_lat/lng/geofence_radius_m.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
_mc = MongoClient(MONGO_URL)
db = _mc[DB_NAME]

RUN_ID = f"IT27{uuid.uuid4().hex[:6]}"
PHONE_STAMP = f"{int(uuid.uuid4().hex[:6], 16) % 100000:05d}"


def _hdr(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _make_phone(n: int) -> str:
    tail = f"{n:04d}"
    return f"+919{PHONE_STAMP}{tail}"


@pytest.fixture(scope="module")
def cleanup():
    yield
    db.companies.delete_many({"name": {"$regex": f"^{RUN_ID}"}})
    db.users.delete_many({"name": {"$regex": f"^{RUN_ID}"}})
    db.users.delete_many({"phone": {"$regex": f"^\\+919{PHONE_STAMP}"}})
    db.user_sessions.delete_many({"auth_method": "test_iter27"})
    db.attendance.delete_many({"user_id": {"$regex": r"^usr_.*"}, "source": "geofence-auto"})


@pytest.fixture(scope="module")
def employee_ctx(cleanup):
    """Create company + approved employee. Return (token, user_id, company_id)."""
    prefix = f"B{RUN_ID[:4]}"
    cid = f"cmp_{uuid.uuid4().hex[:10]}"
    db.companies.insert_one({
        "company_id": cid,
        "company_code": prefix,
        "name": f"{RUN_ID} Bank Co",
        "address": "Test Address, Blr",
        "office_lat": 12.9716,
        "office_lng": 77.5946,
        "geofence_radius_m": 200,
        "compliance_enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    phone = _make_phone(1)
    r = requests.post(
        f"{API}/auth/employee-signup",
        json={"phone": phone, "pin": "482913", "company_code": prefix,
              "name": f"{RUN_ID} BankEmp"},
    )
    assert r.status_code == 200, r.text
    db.users.update_one({"phone": phone}, {"$set": {"approval_status": "approved"}})

    r = requests.post(f"{API}/auth/pin-login", json={"phone": phone, "pin": "482913"})
    assert r.status_code == 200, r.text
    tok = r.json()["session_token"]
    uid = r.json()["user"]["user_id"]
    yield tok, uid, cid


# --------------------- KYC bank details ---------------------------------------
class TestKycBankDetails:
    def test_get_initial_bank_fields_null(self, employee_ctx):
        tok, _, _ = employee_ctx
        r = requests.get(f"{API}/me/kyc", headers=_hdr(tok))
        assert r.status_code == 200
        kyc = r.json().get("kyc", {})
        for k in ("bank_account_number", "bank_name", "ifsc_code", "name_as_per_bank"):
            assert kyc.get(k) in (None, ""), f"{k} expected null/absent, got {kyc.get(k)!r}"

    def test_bank_account_strips_spaces_and_persists(self, employee_ctx):
        tok, _, _ = employee_ctx
        raw = "0123 45678 9012"
        expected = "0123456789012"  # 13 digits
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"bank_account_number": raw})
        assert r.status_code == 200, r.text
        assert r.json()["kyc"]["bank_account_number"] == expected
        # Verify persistence via GET
        r2 = requests.get(f"{API}/me/kyc", headers=_hdr(tok))
        assert r2.json()["kyc"]["bank_account_number"] == expected

    def test_bank_name_stored(self, employee_ctx):
        tok, _, _ = employee_ctx
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"bank_name": "State Bank of India"})
        assert r.status_code == 200
        assert r.json()["kyc"]["bank_name"] == "State Bank of India"

    def test_ifsc_uppercased(self, employee_ctx):
        tok, _, _ = employee_ctx
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"ifsc_code": "sbin0001234"})
        assert r.status_code == 200
        assert r.json()["kyc"]["ifsc_code"] == "SBIN0001234"

    def test_name_as_per_bank_stored(self, employee_ctx):
        tok, _, _ = employee_ctx
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"name_as_per_bank": "John Q Public"})
        assert r.status_code == 200
        assert r.json()["kyc"]["name_as_per_bank"] == "John Q Public"

    def test_empty_string_clears_bank_fields(self, employee_ctx):
        tok, _, _ = employee_ctx
        for field in ("bank_account_number", "bank_name", "ifsc_code", "name_as_per_bank"):
            r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok), json={field: ""})
            assert r.status_code == 200, f"{field}: {r.text}"
            assert r.json()["kyc"][field] is None, f"{field} not cleared"

    # -------------- validation --------------
    def test_bank_account_too_short(self, employee_ctx):
        tok, _, _ = employee_ctx
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"bank_account_number": "12345"})
        assert r.status_code == 400
        assert "6" in r.json().get("detail", "") and "20" in r.json().get("detail", "")

    def test_ifsc_bad(self, employee_ctx):
        tok, _, _ = employee_ctx
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"ifsc_code": "INVALID"})
        assert r.status_code == 400
        assert "AAAA0XXXXXX" in r.json().get("detail", "")


# --------------------- AttendancePunch source ---------------------------------
class TestPunchSource:
    def test_punch_default_source_manual(self, employee_ctx):
        tok, uid, _ = employee_ctx
        # Punch inside the geofence (exact office coords)
        r = requests.post(f"{API}/attendance/punch", headers=_hdr(tok),
                          json={"kind": "in", "latitude": 12.9716, "longitude": 77.5946,
                                "biometric_method": "fingerprint"})
        assert r.status_code == 200, r.text
        rid = r.json()["record_id"]
        rec = db.attendance.find_one({"record_id": rid})
        assert rec is not None
        assert rec.get("source") == "manual"

    def test_punch_source_geofence_auto(self, employee_ctx):
        tok, uid, _ = employee_ctx
        r = requests.post(f"{API}/attendance/punch", headers=_hdr(tok),
                          json={"kind": "out", "latitude": 12.9716,
                                "longitude": 77.5946, "source": "geofence-auto",
                                "biometric_method": "face"})
        assert r.status_code == 200, r.text
        rid = r.json()["record_id"]
        rec = db.attendance.find_one({"record_id": rid})
        assert rec.get("source") == "geofence-auto"

    def test_punch_outside_geofence_still_400(self, employee_ctx):
        tok, _, _ = employee_ctx
        # far away point
        r = requests.post(f"{API}/attendance/punch", headers=_hdr(tok),
                          json={"kind": "in", "latitude": 20.0, "longitude": 80.0,
                                "source": "geofence-auto",
                                "biometric_method": "face"})
        assert r.status_code == 400
        assert "geofence" in r.json().get("detail", "").lower() or "outside" in r.json().get("detail", "").lower()


# --------------------- /auth/me nested company --------------------------------
class TestAuthMeCompany:
    def test_employee_me_includes_company_block(self, employee_ctx):
        tok, _, cid = employee_ctx
        r = requests.get(f"{API}/auth/me", headers=_hdr(tok))
        assert r.status_code == 200, r.text
        user = r.json()["user"]
        assert "company" in user, f"missing nested company: keys={list(user.keys())}"
        comp = user["company"]
        assert comp["company_id"] == cid
        assert comp["office_lat"] == 12.9716
        assert comp["office_lng"] == 77.5946
        assert comp["geofence_radius_m"] == 200
        assert comp.get("name", "").startswith(RUN_ID)
        assert comp.get("address")
