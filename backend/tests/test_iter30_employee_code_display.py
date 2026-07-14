"""Iteration 30 — Backend smoke: `employee_code` is returned by /auth/me and /auth/pin-login.

Frontend shows "ID: <employee_code>" below the employee name on Home + Profile tabs.
Backend must expose the field on both endpoints so the UI can render it.
"""
import os
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

RUN_ID = f"IT30{uuid.uuid4().hex[:6]}"
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


@pytest.fixture(scope="module")
def approved_employee(cleanup):
    """Create ephemeral company + approved employee, return (token, user_doc)."""
    prefix = f"IT30{RUN_ID[-2:]}".upper()
    cid = f"cmp_{uuid.uuid4().hex[:10]}"
    db.companies.insert_one({
        "company_id": cid,
        "company_code": prefix,
        "name": f"{RUN_ID} EmpCodeCo",
        "office_lat": 12.9, "office_lng": 77.6,
        "geofence_radius_m": 200, "compliance_enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    phone = _make_phone(1)
    r = requests.post(
        f"{API}/auth/employee-signup",
        json={
            "phone": phone,
            "pin": "426857",
            "company_code": prefix,
            "name": f"{RUN_ID} EmpTest",
        },
    )
    assert r.status_code == 200, r.text

    # Approve so pin-login succeeds
    db.users.update_one({"phone": phone}, {"$set": {"approval_status": "approved"}})

    r = requests.post(f"{API}/auth/pin-login", json={"phone": phone, "pin": "426857"})
    assert r.status_code == 200, f"pin-login: {r.status_code} {r.text}"
    body = r.json()
    token = body["session_token"]
    user = body["user"]
    yield {"token": token, "user": user, "prefix": prefix, "phone": phone, "cid": cid}


class TestEmployeeCodeInAuth:
    def test_pin_login_returns_employee_code(self, approved_employee):
        user = approved_employee["user"]
        prefix = approved_employee["prefix"]
        assert "employee_code" in user, "user object missing employee_code key"
        assert user["employee_code"] == f"{prefix}0001", (
            f"expected {prefix}0001 got {user.get('employee_code')!r}"
        )
        assert user.get("role") == "employee"

    def test_auth_me_returns_employee_code(self, approved_employee):
        tok = approved_employee["token"]
        prefix = approved_employee["prefix"]
        r = requests.get(f"{API}/auth/me", headers=_hdr(tok))
        assert r.status_code == 200, r.text
        u = r.json()["user"]
        assert u.get("employee_code") == f"{prefix}0001"
        assert u.get("role") == "employee"

    def test_super_admin_me_has_employee_code_marker(self, approved_employee):
        """Super admin should have role != employee — frontend uses this to hide
        the ID line. We just make sure /auth/me works and role is super_admin."""
        sa = db.users.find_one({"email": "sksharmaconsultancy@gmail.com"})
        assert sa, "super_admin seed missing"
        # Create a temp session so we don't touch the real login
        token = f"testiter30_{uuid.uuid4().hex}{uuid.uuid4().hex}"
        db.user_sessions.insert_one({
            "session_token": token,
            "user_id": sa["user_id"],
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
            "created_at": datetime.now(timezone.utc),
            "auth_method": "test_seed",
        })
        try:
            r = requests.get(f"{API}/auth/me", headers=_hdr(token))
            assert r.status_code == 200
            u = r.json()["user"]
            assert u.get("role") == "super_admin"
        finally:
            db.user_sessions.delete_one({"session_token": token})
