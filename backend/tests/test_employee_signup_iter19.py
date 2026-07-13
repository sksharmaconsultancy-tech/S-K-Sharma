"""Iter 19 — Employee signup optional `address` field regression.

Verifies:
1. Employee signup with a real address stores it on the user doc (via GET /me).
2. Employee signup omitting address still works (backward compat).
3. Empty string address is treated as null in DB.
4. Company register regression works.
5. Company lookup regression works.

Uses a throwaway super_admin seeded via pymongo to avoid touching the real
super admin's PIN.
"""
from __future__ import annotations

import os
import time
import uuid
import hashlib
import pytest
import requests
from pymongo import MongoClient


BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL missing")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


def _hash_pin(pin: str) -> str:
    # backend uses bcrypt but for lookup we don't need to log in as this admin.
    # We just need a valid record with a PIN we can login with. Match server logic:
    # server uses passlib bcrypt. Simpler: create user then hit login? Skipping.
    return hashlib.sha256(pin.encode()).hexdigest()


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def throwaway_admin(mongo):
    """Seed a throwaway super_admin via pymongo to obtain a valid session for
    admin-only checks — but we mostly only need public endpoints, so this is
    a minimal placeholder. We do NOT touch the primary super_admin."""
    yield None


@pytest.fixture
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------------------------------------------------------------------
# Test company creation via seed (bypass admin-only endpoints)
# ---------------------------------------------------------------------------
TEST_CODE = f"TEST{uuid.uuid4().hex[:6].upper()}"
TEST_COMPANY_ID = f"cmp_test_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module", autouse=True)
def seed_and_cleanup(mongo):
    mongo.companies.insert_one({
        "company_id": TEST_COMPANY_ID,
        "company_code": TEST_CODE,
        "name": "TEST_Iter19_Co",
        "address": "TEST HQ",
        "office_lat": 28.61,
        "office_lng": 77.23,
        "geofence_radius_m": 200,
        "compliance_enabled": True,
        "created_at": "2026-01-01T00:00:00Z",
    })
    yield
    # cleanup
    mongo.companies.delete_many({"company_code": TEST_CODE})
    mongo.users.delete_many({"phone": {"$regex": r"^\+9188"}})
    mongo.users.delete_many({"name": {"$regex": r"^TEST_"}})


# ---------------------------------------------------------------------------
# Company lookup regression
# ---------------------------------------------------------------------------
class TestCompanyLookup:
    def test_lookup_valid_code(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/companies/lookup/{TEST_CODE}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("name") == "TEST_Iter19_Co"
        assert d.get("company_id") == TEST_COMPANY_ID

    def test_lookup_invalid_code_404(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/companies/lookup/NOPE_XYZ")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Employee signup — the main test target
# ---------------------------------------------------------------------------
def _phone(suffix: str) -> str:
    return f"+9188{suffix}"


class TestEmployeeSignupAddress:
    def test_signup_with_address_persists(self, api_client, mongo):
        phone = _phone("00000001")
        payload = {
            "phone": phone,
            "pin": "482913",
            "company_code": TEST_CODE,
            "name": "TEST_Alpha",
            "email": f"test_iter19_{uuid.uuid4().hex[:6]}@x.com",
            "address": "12 MG Road, New Delhi",
        }
        r = api_client.post(f"{BASE_URL}/api/auth/employee-signup", json=payload)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        user = mongo.users.find_one({"phone": phone}, {"_id": 0, "address": 1, "approval_status": 1})
        assert user is not None
        assert user["address"] == "12 MG Road, New Delhi"
        assert user["approval_status"] == "pending"

    def test_signup_without_address_backward_compat(self, api_client, mongo):
        phone = _phone("00000002")
        payload = {
            "phone": phone,
            "pin": "482913",
            "company_code": TEST_CODE,
            "name": "TEST_Bravo",
            "email": f"test_iter19_{uuid.uuid4().hex[:6]}@x.com",
        }
        r = api_client.post(f"{BASE_URL}/api/auth/employee-signup", json=payload)
        assert r.status_code == 200, r.text
        user = mongo.users.find_one({"phone": phone}, {"_id": 0, "address": 1})
        assert user is not None
        # None is expected (no address key or explicit None)
        assert user.get("address") in (None, "")

    def test_signup_empty_address_becomes_null(self, api_client, mongo):
        phone = _phone("00000003")
        payload = {
            "phone": phone,
            "pin": "482913",
            "company_code": TEST_CODE,
            "name": "TEST_Charlie",
            "email": f"test_iter19_{uuid.uuid4().hex[:6]}@x.com",
            "address": "",
        }
        r = api_client.post(f"{BASE_URL}/api/auth/employee-signup", json=payload)
        assert r.status_code == 200, r.text
        user = mongo.users.find_one({"phone": phone}, {"_id": 0, "address": 1})
        assert user is not None
        assert user.get("address") is None

    def test_signup_whitespace_address_becomes_null(self, api_client, mongo):
        phone = _phone("00000004")
        payload = {
            "phone": phone,
            "pin": "482913",
            "company_code": TEST_CODE,
            "name": "TEST_Delta",
            "email": f"test_iter19_{uuid.uuid4().hex[:6]}@x.com",
            "address": "   ",
        }
        r = api_client.post(f"{BASE_URL}/api/auth/employee-signup", json=payload)
        assert r.status_code == 200, r.text
        user = mongo.users.find_one({"phone": phone}, {"_id": 0, "address": 1})
        assert user.get("address") is None

    def test_signup_invalid_company_code_404(self, api_client):
        payload = {
            "phone": _phone("00000005"),
            "pin": "482913",
            "company_code": "ZZZZZZ",
            "name": "TEST_Nope",
        }
        r = api_client.post(f"{BASE_URL}/api/auth/employee-signup", json=payload)
        assert r.status_code == 404

    def test_signup_duplicate_phone_409(self, api_client):
        phone = _phone("00000006")
        payload = {
            "phone": phone,
            "pin": "482913",
            "company_code": TEST_CODE,
            "name": "TEST_Dup",
            "email": f"test_iter19_{uuid.uuid4().hex[:6]}@x.com",
        }
        r1 = api_client.post(f"{BASE_URL}/api/auth/employee-signup", json=payload)
        assert r1.status_code == 200, r1.text
        # second attempt with same phone but different email should still 409
        payload["email"] = f"test_iter19_{uuid.uuid4().hex[:6]}@x.com"
        r2 = api_client.post(f"{BASE_URL}/api/auth/employee-signup", json=payload)
        assert r2.status_code == 409


# ---------------------------------------------------------------------------
# Company register regression — public endpoint
# ---------------------------------------------------------------------------
class TestCompanyRegisterRegression:
    def test_company_register_request(self, api_client, mongo):
        # This endpoint creates a *request* (New Company Request), no auth needed.
        payload = {
            "company_name": "TEST_Iter19_NewCo",
            "address": "TEST 42 Baker St",
            "city": "Delhi",
            "state": "DL",
            "contact_name": "TEST_QA",
            "contact_mobile": "+919888100001",
            "contact_email": "qa+iter19@test.com",
            "nature_of_business": "Consulting",
            "pin": "482913",
            "office_lat": 28.61,
            "office_lng": 77.23,
            "geofence_radius_m": 200,
            "employee_count": 25,
            "notes": "Iter19 regression",
        }
        r = api_client.post(f"{BASE_URL}/api/auth/company-register", json=payload)
        # We just want it to not 500. 200/201 OK. Some deployments may reject
        # duplicates — treat 409 as also fine.
        assert r.status_code in (200, 201, 409), r.text
        if r.status_code in (200, 201):
            data = r.json()
            # Expect at minimum a boolean ok / message.
            assert isinstance(data, dict)
        # cleanup
        mongo.company_requests.delete_many({"company_name": "TEST_Iter19_NewCo"})
        mongo.users.delete_many({"phone": "+919888100001"})
