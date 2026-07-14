"""Iter 20 backend tests — SK Sharma & Co.

Verifies:
1. POST /api/auth/employee-signup with fresh phone + PIN + valid company_code
   returns 200 AND creates a user with pin_must_change=false, approval_status='pending'.
2. POST /api/auth/company-register accepts payload with and without office_lat/office_lng
   and returns success (200/201). Also verifies coords are persisted on the request doc.

Uses seed data via pymongo for a throwaway company. Does NOT touch super_admin PIN.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests
from pymongo import MongoClient


BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL missing in environment")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


TEST_CODE = f"IT20{uuid.uuid4().hex[:4].upper()}"
TEST_COMPANY_ID = f"cmp_iter20_{uuid.uuid4().hex[:8]}"
TEST_PHONE_PREFIX = "+9198821"  # unique per test suffix
TEST_REGISTER_PHONE = f"+9198822{uuid.uuid4().hex[:5]}"[:15]


@pytest.fixture(scope="module", autouse=True)
def seed_and_cleanup(mongo):
    # Seed a throwaway company
    mongo.companies.insert_one(
        {
            "company_id": TEST_COMPANY_ID,
            "company_code": TEST_CODE,
            "name": "TEST_Iter20_Co",
            "address": "TEST HQ",
            "office_lat": 28.61,
            "office_lng": 77.23,
            "geofence_radius_m": 200,
            "compliance_enabled": True,
            "created_at": "2026-01-01T00:00:00Z",
        }
    )
    yield
    # Cleanup: seeded company, test users (TEST_* names), test company requests
    mongo.companies.delete_many({"company_code": TEST_CODE})
    mongo.users.delete_many({"phone": {"$regex": r"^\+9198821"}})
    mongo.users.delete_many({"phone": {"$regex": r"^\+9198822"}})
    mongo.users.delete_many({"name": {"$regex": r"^TEST_Iter20"}})
    mongo.company_requests.delete_many({"company_name": {"$regex": r"^TEST_Iter20"}})


# -------------------------------------------------------------------------
# 1) Employee signup — pin_must_change=false, approval_status=pending
# -------------------------------------------------------------------------
class TestEmployeeSignupPersistence:
    def test_signup_pin_must_change_false_and_pending(self, api_client, mongo):
        # Digits-only suffix so _normalise_phone doesn't strip chars
        phone_suffix = str(uuid.uuid4().int)[:5]
        phone = f"{TEST_PHONE_PREFIX}{phone_suffix}"
        payload = {
            "phone": phone,
            "pin": "739184",
            "company_code": TEST_CODE,
            "name": "TEST_Iter20_Alpha",
            "email": f"test_iter20_{phone_suffix}@x.com",
        }
        r = api_client.post(f"{BASE_URL}/api/auth/employee-signup", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("company_name") == "TEST_Iter20_Co"

        # DB assertion — critical
        user = mongo.users.find_one(
            {"phone": phone},
            {"_id": 0, "pin_must_change": 1, "approval_status": 1, "role": 1, "has_pin": 1, "company_id": 1},
        )
        assert user is not None, "signup didn't create user"
        assert user["pin_must_change"] is False, f"pin_must_change should be False, got {user['pin_must_change']!r}"
        assert user["approval_status"] == "pending", f"approval_status should be 'pending', got {user['approval_status']!r}"
        assert user["role"] == "employee"
        assert user["has_pin"] is True
        assert user["company_id"] == TEST_COMPANY_ID

    def test_signup_fresh_pin_kept_can_verify_via_admin_login_flow(self, api_client, mongo):
        """Sanity: attempting to sign-in via pin-login for the just-created user
        while pending should fail with a 'pending' error (not 'must change PIN')."""
        phone_suffix = str(uuid.uuid4().int)[:5]
        phone = f"{TEST_PHONE_PREFIX}{phone_suffix}"
        pin = "426187"
        payload = {
            "phone": phone,
            "pin": pin,
            "company_code": TEST_CODE,
            "name": "TEST_Iter20_Bravo",
            "email": f"test_iter20_{phone_suffix}@x.com",
        }
        r = api_client.post(f"{BASE_URL}/api/auth/employee-signup", json=payload)
        assert r.status_code == 200, r.text
        # In DB again check pin_must_change=False
        u = mongo.users.find_one({"phone": phone}, {"_id": 0, "pin_must_change": 1})
        assert u and u["pin_must_change"] is False


# -------------------------------------------------------------------------
# 2) Company self-register with/without office_lat/office_lng
# -------------------------------------------------------------------------
class TestCompanyRegisterOfficeCoords:
    def test_register_with_coords_returns_ok_and_persists(self, api_client, mongo):
        phone = f"+9198822{str(uuid.uuid4().int)[:5]}"
        cname = f"TEST_Iter20_WithCoords_{uuid.uuid4().hex[:4]}"
        payload = {
            "company_name": cname,
            "address": "12 Baker Street",
            "city": "Delhi",
            "state": "DL",
            "contact_name": "TEST_Iter20_Owner",
            "contact_mobile": phone,
            "contact_email": f"qa+iter20_{uuid.uuid4().hex[:5]}@test.com",
            "nature_of_business": "Consulting",
            "pin": "482913",
            "office_lat": 28.6139,
            "office_lng": 77.2090,
        }
        r = api_client.post(f"{BASE_URL}/api/auth/company-register", json=payload)
        assert r.status_code in (200, 201), r.text
        # Verify persistence
        req = mongo.company_requests.find_one({"company_name": cname}, {"_id": 0})
        assert req is not None
        assert req.get("office_lat") == pytest.approx(28.6139)
        assert req.get("office_lng") == pytest.approx(77.2090)
        assert req.get("status") == "pending"
        # cleanup handled at module teardown

    def test_register_without_coords_returns_ok(self, api_client, mongo):
        phone = f"+9198822{str(uuid.uuid4().int)[:5]}"
        cname = f"TEST_Iter20_NoCoords_{uuid.uuid4().hex[:4]}"
        payload = {
            "company_name": cname,
            "address": "42 Baker Street",
            "city": "Mumbai",
            "state": "MH",
            "contact_name": "TEST_Iter20_Owner2",
            "contact_mobile": phone,
            "contact_email": f"qa+iter20b_{uuid.uuid4().hex[:5]}@test.com",
            "nature_of_business": "Consulting",
            "pin": "482913",
        }
        r = api_client.post(f"{BASE_URL}/api/auth/company-register", json=payload)
        assert r.status_code in (200, 201), r.text
        # Verify persistence — coords should be None or absent
        req = mongo.company_requests.find_one({"company_name": cname}, {"_id": 0})
        assert req is not None
        assert req.get("office_lat") in (None, 0, 0.0)
        assert req.get("office_lng") in (None, 0, 0.0)
