"""Iteration 33 backend tests — payroll run, employee policy CRUD, payroll
email report, profile-photo, and gross formula sanity.

Runs against the public preview URL. Cleans up ephemeral rows only.
Does NOT touch the real super_admin's pin_hash / pin_must_change / lockout.
"""
from __future__ import annotations
import os
import base64
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "https://emplo-connect-1.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

RUN_HEX = uuid.uuid4().hex[:6].upper()

CREATED_USER_IDS: list[str] = []
CREATED_COMPANY_IDS: list[str] = []
CREATED_SESSION_TOKENS: list[str] = []
CREATED_ATTENDANCE_USER_IDS: list[str] = []


@pytest.fixture(scope="session")
def mongo():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    # Teardown
    if CREATED_ATTENDANCE_USER_IDS:
        db.attendance.delete_many({"user_id": {"$in": CREATED_ATTENDANCE_USER_IDS}})
    if CREATED_USER_IDS:
        db.attendance.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
        db.user_sessions.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
        db.users.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
    if CREATED_COMPANY_IDS:
        db.companies.delete_many({"company_id": {"$in": CREATED_COMPANY_IDS}})
    if CREATED_SESSION_TOKENS:
        db.user_sessions.delete_many({"session_token": {"$in": CREATED_SESSION_TOKENS}})
    client.close()


@pytest.fixture(scope="session")
def sess():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------- Helpers ----------------
def _seed_company(mongo, name_suffix=""):
    company_id = f"co_it33_{uuid.uuid4().hex[:8]}"
    doc = {
        "company_id": company_id,
        "name": f"IT33 Co {RUN_HEX}{name_suffix}",
        "address": "Test Addr",
        "city": "Delhi", "state": "DL",
        "office_lat": 28.6139, "office_lng": 77.209,
        "geofence_radius_m": 200,
        "company_code": f"I3{uuid.uuid4().hex[:4].upper()}",
        "compliance_enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo.companies.insert_one(doc)
    CREATED_COMPANY_IDS.append(company_id)
    return doc


def _seed_user(mongo, role, company_id, *, email=None, policy=None, salary_monthly=None, no_email=False):
    user_id = f"user_it33_{uuid.uuid4().hex[:10]}"
    doc = {
        "user_id": user_id,
        "email": None if no_email else (email or f"it33_{uuid.uuid4().hex[:6]}@test.local"),
        "phone": f"+91999{uuid.uuid4().int % 10000000:07d}",
        "name": f"IT33 {role} {RUN_HEX}",
        "role": role,
        "company_id": company_id,
        "employee_code": f"I3{RUN_HEX[:2]}{uuid.uuid4().hex[:4].upper()}",
        "onboarded": True,
        "approval_status": "approved",
        "has_pin": False,
        "pin_must_change": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if policy is not None:
        doc["employee_policy"] = policy
    if salary_monthly is not None:
        doc["salary_monthly"] = salary_monthly
    mongo.users.insert_one(doc)
    CREATED_USER_IDS.append(user_id)
    return doc


def _seed_session(mongo, user_id):
    token = f"tk_it33_{uuid.uuid4().hex}"
    mongo.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "auth_method": "test",
    })
    CREATED_SESSION_TOKENS.append(token)
    return token


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _insert_punch(mongo, user_id, date_str, kind, hour=9):
    rid = f"att_it33_{uuid.uuid4().hex[:12]}"
    at = f"{date_str}T{hour:02d}:00:00+00:00"
    mongo.attendance.insert_one({
        "record_id": rid,
        "user_id": user_id,
        "date": date_str,
        "kind": kind,
        "at": at,
        "source": "manual",
    })


# ================================================================
# 1) GET /api/admin/payroll/run — scoping + row shape
# ================================================================
class TestPayrollRun:
    def test_super_admin_all_and_scoped(self, sess, mongo):
        # Two companies, employees in each
        c1 = _seed_company(mongo, "-A")
        c2 = _seed_company(mongo, "-B")
        e1 = _seed_user(mongo, "employee", c1["company_id"],
                        policy={"salary": 20000, "salary_1": 1000, "day_1": 1},
                        salary_monthly=20000)
        e2 = _seed_user(mongo, "employee", c2["company_id"],
                        policy={"salary": 25000, "salary_1": 1500, "day_1": 1},
                        salary_monthly=25000)

        sa = mongo.users.find_one({"role": "super_admin"}, {"user_id": 1, "_id": 0})
        assert sa, "no super_admin present in DB"
        sa_token = _seed_session(mongo, sa["user_id"])

        # Super admin, no company_id → both companies visible
        r = sess.get(f"{API}/admin/payroll/run?year=2025&month=11",
                     headers=_auth(sa_token))
        assert r.status_code == 200, r.text
        body = r.json()
        uids = {row["user_id"] for row in body["rows"]}
        assert e1["user_id"] in uids and e2["user_id"] in uids

        # Super admin with company_id → scoped
        r2 = sess.get(f"{API}/admin/payroll/run?year=2025&month=11&company_id={c1['company_id']}",
                      headers=_auth(sa_token))
        assert r2.status_code == 200
        uids2 = {row["user_id"] for row in r2.json()["rows"]}
        assert e1["user_id"] in uids2 and e2["user_id"] not in uids2

    def test_company_admin_forced_scope(self, sess, mongo):
        c1 = _seed_company(mongo, "-CA1")
        c2 = _seed_company(mongo, "-CA2")
        ca = _seed_user(mongo, "company_admin", c1["company_id"])
        e_own = _seed_user(mongo, "employee", c1["company_id"],
                           policy={"salary": 10000, "salary_1": 500, "day_1": 1},
                           salary_monthly=10000)
        e_other = _seed_user(mongo, "employee", c2["company_id"],
                             policy={"salary": 10000, "salary_1": 500, "day_1": 1},
                             salary_monthly=10000)
        tok = _seed_session(mongo, ca["user_id"])

        # No company_id → own
        r = sess.get(f"{API}/admin/payroll/run?year=2025&month=11",
                     headers=_auth(tok))
        assert r.status_code == 200
        uids = {row["user_id"] for row in r.json()["rows"]}
        assert e_own["user_id"] in uids
        assert e_other["user_id"] not in uids

        # Even if passing another company_id → still forced to own
        r2 = sess.get(f"{API}/admin/payroll/run?year=2025&month=11&company_id={c2['company_id']}",
                      headers=_auth(tok))
        assert r2.status_code == 200
        uids2 = {row["user_id"] for row in r2.json()["rows"]}
        assert e_other["user_id"] not in uids2

    def test_row_shape(self, sess, mongo):
        c = _seed_company(mongo, "-SHAPE")
        e = _seed_user(mongo, "employee", c["company_id"],
                       policy={"salary": 10000, "salary_1": 500, "day_1": 1},
                       salary_monthly=10000)
        sa = mongo.users.find_one({"role": "super_admin"}, {"user_id": 1, "_id": 0})
        tok = _seed_session(mongo, sa["user_id"])
        r = sess.get(f"{API}/admin/payroll/run?year=2025&month=11&company_id={c['company_id']}",
                     headers=_auth(tok))
        assert r.status_code == 200
        row = next(x for x in r.json()["rows"] if x["user_id"] == e["user_id"])
        for k in ("present_days", "half_days", "absent_days", "off_days",
                  "working_days", "total_hours", "base_gross", "tier_bonus",
                  "ot_pay", "gross", "tiers", "policy_confirmed"):
            assert k in row, f"missing key {k}"
        assert isinstance(row["tiers"], list)


# ================================================================
# 2) GET/PATCH /api/admin/employees/{id}/policy
# ================================================================
class TestEmployeePolicy:
    def test_get_defaults_for_fresh_employee(self, sess, mongo):
        c = _seed_company(mongo, "-POL")
        e = _seed_user(mongo, "employee", c["company_id"])
        sa = mongo.users.find_one({"role": "super_admin"}, {"user_id": 1, "_id": 0})
        tok = _seed_session(mongo, sa["user_id"])
        r = sess.get(f"{API}/admin/employees/{e['user_id']}/policy",
                     headers=_auth(tok))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user_id"] == e["user_id"]
        p = body["policy"]
        assert p["salary"] == 0 or p["salary"] == 0.0
        assert p["salary_1"] == 0.0 or p["salary_1"] == 0
        assert p["day_1"] == 0
        assert p["policy_confirmed"] is False

    def test_patch_missing_salary1_400(self, sess, mongo):
        c = _seed_company(mongo, "-POL2")
        e = _seed_user(mongo, "employee", c["company_id"])
        sa = mongo.users.find_one({"role": "super_admin"}, {"user_id": 1, "_id": 0})
        tok = _seed_session(mongo, sa["user_id"])
        r = sess.patch(f"{API}/admin/employees/{e['user_id']}/policy",
                       json={"salary": 10000}, headers=_auth(tok))
        assert r.status_code == 400
        assert "Salary 1" in (r.json().get("detail") or "")
        assert "Day 1" in (r.json().get("detail") or "")

    def test_patch_salary2_without_day2_400(self, sess, mongo):
        c = _seed_company(mongo, "-POL3")
        e = _seed_user(mongo, "employee", c["company_id"])
        sa = mongo.users.find_one({"role": "super_admin"}, {"user_id": 1, "_id": 0})
        tok = _seed_session(mongo, sa["user_id"])
        r = sess.patch(f"{API}/admin/employees/{e['user_id']}/policy",
                       json={"salary_1": 500, "day_1": 20, "salary_2": 500, "day_2": 0},
                       headers=_auth(tok))
        assert r.status_code == 400
        detail = r.json().get("detail") or ""
        assert "Day 2" in detail and "Salary 2" in detail

    def test_patch_valid_tier1_then_get(self, sess, mongo):
        c = _seed_company(mongo, "-POL4")
        e = _seed_user(mongo, "employee", c["company_id"])
        sa = mongo.users.find_one({"role": "super_admin"}, {"user_id": 1, "_id": 0})
        tok = _seed_session(mongo, sa["user_id"])
        r = sess.patch(f"{API}/admin/employees/{e['user_id']}/policy",
                       json={"salary": 30000, "salary_1": 500, "day_1": 20},
                       headers=_auth(tok))
        assert r.status_code == 200, r.text
        p = r.json()["policy"]
        assert p["policy_confirmed"] is True
        assert p["salary_1"] == 500
        assert p["day_1"] == 20

        # GET reflects
        r2 = sess.get(f"{API}/admin/employees/{e['user_id']}/policy",
                      headers=_auth(tok))
        assert r2.status_code == 200
        p2 = r2.json()["policy"]
        assert p2["salary"] == 30000
        assert p2["salary_1"] == 500
        assert p2["day_1"] == 20
        assert p2["policy_confirmed"] is True

    def test_company_admin_cross_company_403(self, sess, mongo):
        c1 = _seed_company(mongo, "-POLA")
        c2 = _seed_company(mongo, "-POLB")
        ca = _seed_user(mongo, "company_admin", c1["company_id"])
        e_other = _seed_user(mongo, "employee", c2["company_id"])
        tok = _seed_session(mongo, ca["user_id"])
        r = sess.patch(f"{API}/admin/employees/{e_other['user_id']}/policy",
                       json={"salary_1": 500, "day_1": 20}, headers=_auth(tok))
        assert r.status_code == 403


# ================================================================
# 3) POST /api/admin/payroll/email-report
# ================================================================
class TestPayrollEmailReport:
    def test_empty_scope_400(self, sess, mongo):
        # Create a company but no employees, use its company_admin
        c = _seed_company(mongo, "-EMPTY")
        ca = _seed_user(mongo, "company_admin", c["company_id"])
        tok = _seed_session(mongo, ca["user_id"])
        r = sess.post(f"{API}/admin/payroll/email-report",
                      json={"year": 2025, "month": 11,
                            "report_kind": "combined", "recipients": "self"},
                      headers=_auth(tok))
        assert r.status_code == 400
        assert "No employees in scope" in (r.json().get("detail") or "")

    def test_self_admin_no_email(self, sess, mongo):
        """Admin without email — verify response shape. Currently backend
        SKIPS the send instead of appending a delivered=false stub."""
        c = _seed_company(mongo, "-NOEMAIL")
        ca = _seed_user(mongo, "company_admin", c["company_id"], no_email=True)
        _ = _seed_user(mongo, "employee", c["company_id"],
                       policy={"salary": 10000, "salary_1": 500, "day_1": 1},
                       salary_monthly=10000)
        tok = _seed_session(mongo, ca["user_id"])
        r = sess.post(f"{API}/admin/payroll/email-report",
                      json={"year": 2025, "month": 11,
                            "report_kind": "combined", "recipients": "self"},
                      headers=_auth(tok))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["report_kind"] == "combined"
        assert body["recipients"] == "self"
        # delivered + failed == len(sends)
        assert body["delivered"] + body["failed"] == len(body["sends"])
        # Currently: sends is empty (admin has no email, employee scope not iterated)
        # If backend adds a stub in future, admin entry should be delivered=false
        for s in body["sends"]:
            if s.get("role") == "admin":
                assert s.get("delivered") is False

    def test_recipients_employees_one_per_emp(self, sess, mongo):
        c = _seed_company(mongo, "-EMPS")
        ca = _seed_user(mongo, "company_admin", c["company_id"])
        e1 = _seed_user(mongo, "employee", c["company_id"],
                        policy={"salary": 10000, "salary_1": 500, "day_1": 1},
                        salary_monthly=10000)
        e2 = _seed_user(mongo, "employee", c["company_id"],
                        policy={"salary": 12000, "salary_1": 500, "day_1": 1},
                        salary_monthly=12000)
        tok = _seed_session(mongo, ca["user_id"])
        r = sess.post(f"{API}/admin/payroll/email-report",
                      json={"year": 2025, "month": 11,
                            "report_kind": "salary", "recipients": "employees"},
                      headers=_auth(tok))
        assert r.status_code == 200, r.text
        body = r.json()
        # One send per employee
        emp_sends = [s for s in body["sends"] if s.get("role") == "employee"]
        emp_uids = {s.get("user_id") for s in emp_sends}
        assert e1["user_id"] in emp_uids
        assert e2["user_id"] in emp_uids
        assert len(emp_sends) >= 2
        assert body["delivered"] + body["failed"] == len(body["sends"])


# ================================================================
# 4) POST/DELETE /api/me/profile-photo
# ================================================================
class TestProfilePhoto:
    def test_set_overwrite_delete(self, sess, mongo):
        c = _seed_company(mongo, "-PHOTO")
        u = _seed_user(mongo, "employee", c["company_id"])
        tok = _seed_session(mongo, u["user_id"])
        b64 = base64.b64encode(b"hello world " * 20).decode("ascii")
        data_url = f"data:image/jpeg;base64,{b64}"

        r = sess.post(f"{API}/me/profile-photo",
                      json={"photo_base64": data_url},
                      headers=_auth(tok))
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # Verify persisted
        doc = mongo.users.find_one({"user_id": u["user_id"]}, {"profile_photo_base64": 1})
        assert doc.get("profile_photo_base64") == data_url

        # Overwrite
        b64b = base64.b64encode(b"new content " * 20).decode("ascii")
        data_url2 = f"data:image/png;base64,{b64b}"
        r2 = sess.post(f"{API}/me/profile-photo",
                       json={"photo_base64": data_url2},
                       headers=_auth(tok))
        assert r2.status_code == 200
        doc2 = mongo.users.find_one({"user_id": u["user_id"]}, {"profile_photo_base64": 1})
        assert doc2.get("profile_photo_base64") == data_url2
        assert doc2.get("profile_photo_base64") != data_url

        # Delete
        r3 = sess.delete(f"{API}/me/profile-photo", headers=_auth(tok))
        assert r3.status_code == 200
        doc3 = mongo.users.find_one({"user_id": u["user_id"]}, {"profile_photo_base64": 1})
        assert not doc3.get("profile_photo_base64")

    def test_oversized_413(self, sess, mongo):
        c = _seed_company(mongo, "-PHOTO2")
        u = _seed_user(mongo, "employee", c["company_id"])
        tok = _seed_session(mongo, u["user_id"])
        # >4.5MB payload
        big = "A" * 5_000_000
        r = sess.post(f"{API}/me/profile-photo",
                      json={"photo_base64": big},
                      headers=_auth(tok))
        assert r.status_code == 413, r.status_code


# ================================================================
# 5) Payroll gross formula sanity — Nov 2025
# ================================================================
class TestPayrollGrossFormula:
    def test_gross_formula(self, sess, mongo):
        """Seed employee with policy.salary=30000, salary_1=2000, day_1=20.
        Insert 22 IN punches on distinct Nov 2025 dates (Mon–Sat only).
        Expected: base_gross = 30000 * 22 / working_days, tier_bonus=2000,
        gross = base_gross + 2000.
        """
        c = _seed_company(mongo, "-FORMULA")
        e = _seed_user(mongo, "employee", c["company_id"],
                       policy={"salary": 30000, "salary_1": 2000, "day_1": 20,
                               "weekly_off": 0},  # Sunday (UI 0=Sun)
                       salary_monthly=30000)
        CREATED_ATTENDANCE_USER_IDS.append(e["user_id"])
        # Nov 2025: 30 days. Sundays: 2,9,16,23,30 → 5 Sundays. Non-Sunday: 25.
        sundays = {2, 9, 16, 23, 30}
        chosen = [d for d in range(1, 31) if d not in sundays][:22]
        assert len(chosen) == 22
        for d in chosen:
            _insert_punch(mongo, e["user_id"], f"2025-11-{d:02d}", "in", 9)

        sa = mongo.users.find_one({"role": "super_admin"}, {"user_id": 1, "_id": 0})
        tok = _seed_session(mongo, sa["user_id"])
        r = sess.get(f"{API}/admin/payroll/run?year=2025&month=11&company_id={c['company_id']}",
                     headers=_auth(tok))
        assert r.status_code == 200, r.text
        row = next(x for x in r.json()["rows"] if x["user_id"] == e["user_id"])
        assert row["present_days"] == 22, row
        assert row["off_days"] == 5, row
        # working_days = present + half + absent = 22 + 0 + 3
        assert row["working_days"] == 25, row
        expected_base = round(30000 * 22 / 25, 2)
        assert abs(row["base_gross"] - expected_base) < 0.5, row
        assert row["tier_bonus"] == 2000, row
        assert abs(row["gross"] - (expected_base + 2000)) < 0.5, row
