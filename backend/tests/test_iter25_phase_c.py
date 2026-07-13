"""Iteration 25 — Phase C tests.

Backend coverage:
  1. Employee code generation (COMPANY_CODE + 4 digits)
  2. Company create/update accepts company_code
  3. KYC endpoints (GET / PATCH /api/me/kyc) — happy path + validation + auth
"""
import os
import re
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
_mc = MongoClient(MONGO_URL)
db = _mc[DB_NAME]

RUN_ID = f"IT25{uuid.uuid4().hex[:6]}"
# 4-digit phone suffix pool unique per run (digits-only after normalisation)
PHONE_STAMP = f"{int(uuid.uuid4().hex[:6], 16) % 100000:05d}"  # 5 digits


# ---------- fixtures ----------------------------------------------------------
@pytest.fixture(scope="module")
def super_admin_token():
    """Insert a session for the seeded super_admin without touching PIN fields."""
    sa = db.users.find_one({"email": "sksharmaconsultancy@gmail.com"})
    assert sa, "super_admin seed missing"
    token = f"testiter25_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": token,
        "user_id": sa["user_id"],
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "created_at": datetime.now(timezone.utc),
        "auth_method": "test_seed",
    })
    yield token
    db.user_sessions.delete_one({"session_token": token})


@pytest.fixture(scope="module")
def cleanup():
    yield
    # remove everything created by this run
    db.companies.delete_many({"name": {"$regex": f"^{RUN_ID}"}})
    db.users.delete_many({"name": {"$regex": f"^{RUN_ID}"}})
    db.users.delete_many({"phone": {"$regex": f"^\\+919{PHONE_STAMP}"}})
    db.user_sessions.delete_many({"auth_method": "test_seed"})


# ---------- helpers -----------------------------------------------------------
def _hdr(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _make_phone(n: int) -> str:
    # Deterministic per-run, digits only after +91. 10 digits total.
    tail = f"{n:04d}"
    return f"+919{PHONE_STAMP}{tail}"  # +91 + 9 + 5 digits + 4 digits = 10 subscriber digits


# ---------- Employee-code generation -----------------------------------------
class TestEmployeeCodeGeneration:
    def test_post_company_persists_company_code(self, super_admin_token, cleanup):
        """This isolates the critical bug: CompanyCreate model has no company_code field,
        so POST /api/companies falls back to a random 6-hex code instead of using 'SKS'.
        """
        payload = {
            "name": f"{RUN_ID} PostCodeCo",
            "office_lat": 12.9, "office_lng": 77.6,
            "company_code": "SKS",
        }
        r = requests.post(f"{API}/companies", headers=_hdr(super_admin_token), json=payload)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c.get("company_code") == "SKS", (
            f"POST /companies did NOT persist company_code='SKS' — got {c.get('company_code')!r}. "
            "BUG: CompanyCreate model is missing `company_code` field AND create_company() "
            "does not pass it to Company(...)."
        )

    def test_sequential_codes_and_patch(self, super_admin_token, cleanup):
        """Uses PATCH (which DOES accept company_code) to set the prefix after create."""
        # Use run-unique prefix to avoid collision with SKS company created in
        # `test_post_company_persists_company_code` (which now DOES persist SKS
        # after the iter-26 backend fix).
        prefix = f"IT26{RUN_ID[-2:]}".upper()
        # Create company then PATCH company_code to SKS (workaround for POST bug)
        r = requests.post(f"{API}/companies", headers=_hdr(super_admin_token),
                          json={"name": f"{RUN_ID} SeqCo", "office_lat": 12.9, "office_lng": 77.6})
        assert r.status_code == 200
        cid = r.json()["company_id"]
        r = requests.patch(f"{API}/companies/{cid}", headers=_hdr(super_admin_token),
                           json={"company_code": prefix})
        assert r.status_code == 200
        assert r.json()["company_code"] == prefix

        # Employee 1 -> {prefix}0001
        p1 = _make_phone(101)
        r = requests.post(f"{API}/auth/employee-signup",
                         json={"phone": p1, "pin": "918273", "company_code": prefix,
                               "name": f"{RUN_ID} Emp One"})
        assert r.status_code == 200, r.text
        assert db.users.find_one({"phone": p1})["employee_code"] == f"{prefix}0001"

        # Employee 2 -> {prefix}0002
        p2 = _make_phone(102)
        r = requests.post(f"{API}/auth/employee-signup",
                         json={"phone": p2, "pin": "819273", "company_code": prefix,
                               "name": f"{RUN_ID} Emp Two"})
        assert r.status_code == 200
        assert db.users.find_one({"phone": p2})["employee_code"] == f"{prefix}0002"

        # Legacy hyphenated code should NOT collide/interfere
        db.users.insert_one({
            "user_id": f"legacy_{uuid.uuid4().hex[:8]}",
            "phone": _make_phone(9998), "name": f"{RUN_ID} Legacy",
            "email": None, "role": "employee", "company_id": cid,
            "employee_code": f"{prefix}-1234",
            "approval_status": "approved", "onboarded": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # Employee 3 -> {prefix}0003 (legacy skipped)
        p3 = _make_phone(103)
        r = requests.post(f"{API}/auth/employee-signup",
                         json={"phone": p3, "pin": "192837", "company_code": prefix,
                               "name": f"{RUN_ID} Emp Three"})
        assert r.status_code == 200
        assert db.users.find_one({"phone": p3})["employee_code"] == f"{prefix}0003"

        # PATCH prefix -> new unique prefix
        new_prefix = f"AC{RUN_ID[:3]}"
        r = requests.patch(f"{API}/companies/{cid}", headers=_hdr(super_admin_token),
                           json={"company_code": new_prefix})
        assert r.status_code == 200
        assert r.json()["company_code"] == new_prefix

        # Employee 4 -> {new_prefix}0001 (fresh sequence)
        p4 = _make_phone(104)
        r = requests.post(f"{API}/auth/employee-signup",
                         json={"phone": p4, "pin": "273819", "company_code": new_prefix,
                               "name": f"{RUN_ID} Emp Four"})
        assert r.status_code == 200
        assert db.users.find_one({"phone": p4})["employee_code"] == f"{new_prefix}0001"

        # Existing users keep their codes
        assert db.users.find_one({"phone": p1})["employee_code"] == f"{prefix}0001"
        assert db.users.find_one({"phone": p2})["employee_code"] == f"{prefix}0002"


# ---------- CompanyUpdate accepts various fields ------------------------------
class TestCompanyUpdate:
    def test_patch_accepts_multiple_fields(self, super_admin_token, cleanup):
        r = requests.post(f"{API}/companies", headers=_hdr(super_admin_token),
                          json={"name": f"{RUN_ID} Upd Co",
                                "office_lat": 10.0, "office_lng": 20.0,
                                "company_code": f"UP{RUN_ID[:3]}"})
        assert r.status_code == 200
        cid = r.json()["company_id"]

        r = requests.patch(f"{API}/companies/{cid}", headers=_hdr(super_admin_token),
                           json={"name": f"{RUN_ID} Upd Co v2",
                                 "address": "Blr", "office_lat": 12.34, "office_lng": 56.78,
                                 "geofence_radius_m": 500, "compliance_enabled": False,
                                 "company_code": f"XZ{RUN_ID[:3]}"})
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == f"{RUN_ID} Upd Co v2"
        assert body["company_code"] == f"XZ{RUN_ID[:3]}"
        assert body["office_lat"] == 12.34


# ---------- KYC endpoints -----------------------------------------------------
@pytest.fixture(scope="module")
def employee_ctx(super_admin_token, cleanup):
    """Create + approve + sign in an ephemeral employee. Returns (token, user_id).

    Note: uses direct pymongo insert for company because POST /companies is
    currently ignoring `company_code` (see TestEmployeeCodeGeneration).
    """
    prefix = f"KY{RUN_ID[:4]}"
    cid = f"cmp_{uuid.uuid4().hex[:10]}"
    db.companies.insert_one({
        "company_id": cid,
        "company_code": prefix,
        "name": f"{RUN_ID} Kyc Co",
        "office_lat": 1.0, "office_lng": 1.0,
        "geofence_radius_m": 200, "compliance_enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    phone = _make_phone(555)
    r = requests.post(f"{API}/auth/employee-signup",
                      json={"phone": phone, "pin": "426857", "company_code": prefix,
                            "name": f"{RUN_ID} Kyc Emp"})
    assert r.status_code == 200

    # Approve
    db.users.update_one({"phone": phone}, {"$set": {"approval_status": "approved"}})

    r = requests.post(f"{API}/auth/pin-login", json={"phone": phone, "pin": "426857"})
    assert r.status_code == 200, f"pin-login: {r.status_code} {r.text}"
    tok = r.json()["session_token"]
    uid = r.json()["user"]["user_id"]
    yield tok, uid


class TestKyc:
    def test_get_initial_kyc(self, employee_ctx):
        tok, _ = employee_ctx
        r = requests.get(f"{API}/me/kyc", headers=_hdr(tok))
        assert r.status_code == 200
        kyc = r.json().get("kyc", {})
        # All fields either absent or null in the fresh doc
        for k in ("aadhar_number", "name_as_per_aadhar", "pan_number",
                  "name_as_per_pan", "dl_number", "kyc_updated_at"):
            assert kyc.get(k) in (None, "", ), f"{k} expected null/absent"

    def test_patch_happy_path(self, employee_ctx):
        tok, _ = employee_ctx
        # Aadhaar
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"aadhar_number": "123412341234"})
        assert r.status_code == 200, r.text
        assert r.json()["kyc"]["aadhar_number"] == "123412341234"

        # name_as_per_aadhar
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"name_as_per_aadhar": "John Q Public"})
        assert r.status_code == 200
        assert r.json()["kyc"]["name_as_per_aadhar"] == "John Q Public"

        # PAN — lowercase input, must uppercase server-side
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"pan_number": "abcde1234f"})
        assert r.status_code == 200
        assert r.json()["kyc"]["pan_number"] == "ABCDE1234F"

        # DL with lowercase + inner space (kept)
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"dl_number": "dl14 20110012345"})
        assert r.status_code == 200
        assert r.json()["kyc"]["dl_number"].startswith("DL14")

        # kyc_updated_at set
        assert r.json()["kyc"].get("kyc_updated_at")

        # Clear a field with ""
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok), json={"pan_number": ""})
        assert r.status_code == 200
        assert r.json()["kyc"]["pan_number"] is None

    def test_patch_validation_aadhar_short(self, employee_ctx):
        tok, _ = employee_ctx
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"aadhar_number": "1234"})
        assert r.status_code == 400
        assert "12 digits" in r.json().get("detail", "")

    def test_patch_validation_pan_bad(self, employee_ctx):
        tok, _ = employee_ctx
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"pan_number": "INVALID"})
        assert r.status_code == 400
        assert "ABCDE1234F" in r.json().get("detail", "")

    def test_patch_validation_dl_short(self, employee_ctx):
        tok, _ = employee_ctx
        r = requests.patch(f"{API}/me/kyc", headers=_hdr(tok),
                           json={"dl_number": "AB"})
        assert r.status_code == 400
        assert "5" in r.json().get("detail", "")

    def test_no_auth_returns_401(self):
        r = requests.get(f"{API}/me/kyc")
        assert r.status_code in (401, 403)
        r = requests.patch(f"{API}/me/kyc", json={"aadhar_number": "123412341234"})
        assert r.status_code in (401, 403)
