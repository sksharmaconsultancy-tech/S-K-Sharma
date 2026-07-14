"""Iteration 35 backend tests — multiple IN/OUT punches per day.

Bug fix under test: `POST /api/attendance/punch` and
`POST /api/admin/attendance/approve-punch` must allow multiple IN→OUT
cycles per day (each entry/exit logged as a separate row), while still
rejecting double-IN, double-OUT, and OUT-before-IN.

Also validates that `_compute_day_hours` (used by /attendance/summary and
/admin/attendance/today) and `_compute_payroll_run` correctly pair
multiple IN/OUT cycles when summing hours.

Runs against the public preview URL. Cleans up all ephemeral rows.
Does NOT touch the real super_admin doc.
"""
from __future__ import annotations
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "EXPO_BACKEND_URL",
    os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
    or "https://emplo-connect-1.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

RUN_HEX = uuid.uuid4().hex[:6].upper()
CREATED_USER_IDS: list[str] = []
CREATED_COMPANY_IDS: list[str] = []
CREATED_SESSION_TOKENS: list[str] = []
CREATED_ATTENDANCE_IDS: list[str] = []

# Company office coordinates as specified in the review request
OFFICE_LAT = 13.0
OFFICE_LNG = 77.6
OFFICE_RADIUS = 200  # meters
# Inside geofence — same point (0m from office)
INSIDE_LAT, INSIDE_LNG = 13.0, 77.6
# Outside geofence — ~11km away (0.1 deg latitude offset)
OUTSIDE_LAT, OUTSIDE_LNG = 13.1, 77.6


@pytest.fixture(scope="session")
def mongo():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    # Teardown — remove everything we created
    if CREATED_ATTENDANCE_IDS:
        db.attendance.delete_many({"record_id": {"$in": CREATED_ATTENDANCE_IDS}})
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


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _seed_company(mongo, lat=OFFICE_LAT, lng=OFFICE_LNG, radius=OFFICE_RADIUS):
    company_id = f"co_it35_{uuid.uuid4().hex[:8]}"
    doc = {
        "company_id": company_id,
        "name": f"IT35 Test Co {RUN_HEX}",
        "address": "Test Address",
        "city": "Bengaluru",
        "state": "KA",
        "office_lat": lat,
        "office_lng": lng,
        "geofence_radius_m": radius,
        "company_code": f"IT35{uuid.uuid4().hex[:4].upper()}",
        "compliance_enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo.companies.insert_one(doc)
    CREATED_COMPANY_IDS.append(company_id)
    return doc


def _seed_user(mongo, role, company_id, *, salary=30000):
    user_id = f"user_it35_{uuid.uuid4().hex[:10]}"
    phone = f"+91999{uuid.uuid4().int % 10000000:07d}"
    email = f"it35_{uuid.uuid4().hex[:8]}@test.local"
    doc = {
        "user_id": user_id,
        "email": email,
        "phone": phone,
        "name": f"IT35 {role} {RUN_HEX}",
        "role": role,
        "company_id": company_id,
        "employee_code": f"IT35{RUN_HEX[:2]}{uuid.uuid4().hex[:3].upper()}",
        "onboarded": True,
        "approval_status": "approved",
        "has_pin": False,
        "pin_must_change": False,
        "salary_monthly": salary,
        "full_day_hrs": 6,
        "half_day_hrs": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo.users.insert_one(doc)
    CREATED_USER_IDS.append(user_id)
    return doc


def _seed_session(mongo, user_id):
    token = f"tk_it35_{uuid.uuid4().hex}"
    expires = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    mongo.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": expires,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "auth_method": "test",
    })
    CREATED_SESSION_TOKENS.append(token)
    return token


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _insert_attendance(mongo, user_id, company_id, kind, at_dt, *, date_str=None):
    """Directly insert an attendance record with a controlled timestamp,
    so we can validate hour-aggregation logic without waiting real-time."""
    rec_id = f"att_it35_{uuid.uuid4().hex[:12]}"
    d = date_str or at_dt.strftime("%Y-%m-%d")
    doc = {
        "record_id": rec_id,
        "user_id": user_id,
        "company_id": company_id,
        "date": d,
        "kind": kind,
        "at": at_dt.isoformat().replace("+00:00", "Z"),
        "latitude": INSIDE_LAT,
        "longitude": INSIDE_LNG,
        "distance_m": 0.0,
        "biometric_method": "fingerprint",
        "source": "manual",
        "outside_geofence": False,
    }
    mongo.attendance.insert_one(doc)
    CREATED_ATTENDANCE_IDS.append(rec_id)
    return doc


# ==================================================================
# 1) POST /api/attendance/punch — multi IN/OUT cycles
# ==================================================================
class TestEmployeeMultiPunch:
    def _mk(self, mongo):
        comp = _seed_company(mongo)
        emp = _seed_user(mongo, "employee", comp["company_id"])
        tok = _seed_session(mongo, emp["user_id"])
        return comp, emp, tok

    def test_multiple_in_out_cycles_produce_separate_rows(self, sess, mongo):
        """IN → OUT → IN → OUT must yield 4 attendance rows (multi-cycle log)."""
        comp, emp, tok = self._mk(mongo)
        base = {
            "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
            "biometric_method": "fingerprint",
        }
        # Cycle 1: IN → OUT
        r1 = sess.post(f"{API}/attendance/punch", headers=_auth(tok),
                       json={**base, "kind": "in"})
        assert r1.status_code == 200, r1.text
        r2 = sess.post(f"{API}/attendance/punch", headers=_auth(tok),
                       json={**base, "kind": "out"})
        assert r2.status_code == 200, r2.text
        # Cycle 2: IN → OUT
        r3 = sess.post(f"{API}/attendance/punch", headers=_auth(tok),
                       json={**base, "kind": "in"})
        assert r3.status_code == 200, r3.text
        r4 = sess.post(f"{API}/attendance/punch", headers=_auth(tok),
                       json={**base, "kind": "out"})
        assert r4.status_code == 200, r4.text

        # Verify 4 records exist in DB for today
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        recs = list(mongo.attendance.find(
            {"user_id": emp["user_id"], "date": today}, {"_id": 0}
        ).sort("at", 1))
        assert len(recs) == 4, f"expected 4 punches, got {len(recs)}: {recs}"
        kinds = [r["kind"] for r in recs]
        assert kinds == ["in", "out", "in", "out"], kinds
        # Records should be strictly ordered by 'at'
        ats = [r["at"] for r in recs]
        assert ats == sorted(ats), f"records not chronologically ordered: {ats}"

    def test_double_in_inside_returns_400(self, sess, mongo):
        comp, emp, tok = self._mk(mongo)
        base = {
            "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
            "biometric_method": "fingerprint",
        }
        r1 = sess.post(f"{API}/attendance/punch", headers=_auth(tok),
                       json={**base, "kind": "in"})
        assert r1.status_code == 200, r1.text
        r2 = sess.post(f"{API}/attendance/punch", headers=_auth(tok),
                       json={**base, "kind": "in"})
        assert r2.status_code == 400, r2.text
        detail = (r2.json().get("detail") or "").lower()
        assert "already punched in" in detail, detail

    def test_double_out_inside_returns_400(self, sess, mongo):
        comp, emp, tok = self._mk(mongo)
        base = {
            "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
            "biometric_method": "fingerprint",
        }
        r1 = sess.post(f"{API}/attendance/punch", headers=_auth(tok),
                       json={**base, "kind": "in"})
        assert r1.status_code == 200
        r2 = sess.post(f"{API}/attendance/punch", headers=_auth(tok),
                       json={**base, "kind": "out"})
        assert r2.status_code == 200
        r3 = sess.post(f"{API}/attendance/punch", headers=_auth(tok),
                       json={**base, "kind": "out"})
        assert r3.status_code == 400, r3.text
        detail = (r3.json().get("detail") or "").lower()
        assert "not currently punched in" in detail, detail

    def test_out_before_in_inside_returns_400(self, sess, mongo):
        comp, emp, tok = self._mk(mongo)
        # First punch of the day is OUT (no prior IN) inside geofence
        r = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "out",
            "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
            "biometric_method": "fingerprint",
        })
        assert r.status_code == 400, r.text
        detail = (r.json().get("detail") or "").lower()
        assert "not currently punched in" in detail, detail

    def test_out_before_in_outside_returns_400(self, sess, mongo):
        comp, emp, tok = self._mk(mongo)
        # OUT from outside without prior IN
        r = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "out",
            "latitude": OUTSIDE_LAT, "longitude": OUTSIDE_LNG,
            "biometric_method": "fingerprint",
        })
        assert r.status_code == 400, r.text
        detail = (r.json().get("detail") or "").lower()
        assert "haven't punched in" in detail or "punch in first" in detail, detail

    def test_double_out_from_outside_returns_400(self, sess, mongo):
        """After IN→OUT, a second OUT from OUTSIDE the geofence must also be blocked."""
        comp, emp, tok = self._mk(mongo)
        base_in = {
            "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
            "biometric_method": "fingerprint",
        }
        r1 = sess.post(f"{API}/attendance/punch", headers=_auth(tok),
                       json={**base_in, "kind": "in"})
        assert r1.status_code == 200
        r2 = sess.post(f"{API}/attendance/punch", headers=_auth(tok),
                       json={**base_in, "kind": "out"})
        assert r2.status_code == 200
        # Now second OUT from outside — last_kind is "out" so must reject
        r3 = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "out",
            "latitude": OUTSIDE_LAT, "longitude": OUTSIDE_LNG,
            "biometric_method": "fingerprint",
        })
        assert r3.status_code == 400, r3.text

    def test_in_from_outside_still_blocked(self, sess, mongo):
        """IN from outside geofence must still be rejected (no fraud)."""
        comp, emp, tok = self._mk(mongo)
        r = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "in",
            "latitude": OUTSIDE_LAT, "longitude": OUTSIDE_LNG,
            "biometric_method": "fingerprint",
        })
        assert r.status_code == 400, r.text
        detail = (r.json().get("detail") or "").lower()
        assert "geofence" in detail or "outside" in detail, detail


# ==================================================================
# 2) GET /api/attendance/today — returns all punches ordered ascending
# ==================================================================
class TestAttendanceTodayReturnsAllPunches:
    def test_returns_all_punches_ordered_asc(self, sess, mongo):
        comp = _seed_company(mongo)
        emp = _seed_user(mongo, "employee", comp["company_id"])
        tok = _seed_session(mongo, emp["user_id"])
        base = {
            "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
            "biometric_method": "fingerprint",
        }
        for k in ["in", "out", "in", "out"]:
            r = sess.post(f"{API}/attendance/punch", headers=_auth(tok),
                          json={**base, "kind": k})
            assert r.status_code == 200, r.text

        r = sess.get(f"{API}/attendance/today", headers=_auth(tok))
        assert r.status_code == 200, r.text
        body = r.json()
        recs = body.get("records") or []
        assert len(recs) == 4, f"expected 4 records, got {len(recs)}"
        assert [x["kind"] for x in recs] == ["in", "out", "in", "out"]
        ats = [x["at"] for x in recs]
        assert ats == sorted(ats), "records not ordered ascending by 'at'"


# ==================================================================
# 3) GET /api/admin/attendance/today — aggregation across pairs
# ==================================================================
class TestAdminAttendanceTodayAggregation:
    def test_first_in_last_out_total_hours_still_in_false(self, sess, mongo):
        comp = _seed_company(mongo)
        admin = _seed_user(mongo, "company_admin", comp["company_id"])
        admin_tok = _seed_session(mongo, admin["user_id"])
        emp = _seed_user(mongo, "employee", comp["company_id"])

        # Insert 2 IN/OUT pairs today with controlled timestamps
        # Block 1: 09:00–11:00 (2h), Block 2: 14:00–16:00 (2h) → total 4h
        today_dt = datetime.now(timezone.utc).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "in",
                           today_dt)
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "out",
                           today_dt + timedelta(hours=2))
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "in",
                           today_dt + timedelta(hours=5))
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "out",
                           today_dt + timedelta(hours=7))

        r = sess.get(f"{API}/admin/attendance/today", headers=_auth(admin_tok))
        assert r.status_code == 200, r.text
        body = r.json()
        present = body.get("present") or []
        me = next((p for p in present if p["user_id"] == emp["user_id"]), None)
        assert me is not None, f"employee not in present list: {present}"
        assert me["punches"] == 4, me
        assert me["hours"] == 4.0, me
        assert me["still_in"] is False, me
        # first_in equals first record; last_out equals last record
        assert me["first_in"] is not None and me["last_out"] is not None
        assert me["first_in"] < me["last_out"]

    def test_still_in_true_when_last_punch_is_in(self, sess, mongo):
        comp = _seed_company(mongo)
        admin = _seed_user(mongo, "company_admin", comp["company_id"])
        admin_tok = _seed_session(mongo, admin["user_id"])
        emp = _seed_user(mongo, "employee", comp["company_id"])

        today_dt = datetime.now(timezone.utc).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "in",
                           today_dt)
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "out",
                           today_dt + timedelta(hours=2))
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "in",
                           today_dt + timedelta(hours=5))
        # No closing OUT — still on-shift

        r = sess.get(f"{API}/admin/attendance/today", headers=_auth(admin_tok))
        assert r.status_code == 200
        me = next((p for p in r.json()["present"] if p["user_id"] == emp["user_id"]), None)
        assert me is not None
        assert me["still_in"] is True, me
        assert me["punches"] == 3, me
        # Only the closed pair counts (2h); open IN doesn't yet add hours
        assert me["hours"] == 2.0, me


# ==================================================================
# 4) GET /api/attendance/summary — _compute_day_hours across pairs
# ==================================================================
class TestAttendanceSummaryMultiPair:
    def test_summary_sums_multi_pairs(self, sess, mongo):
        comp = _seed_company(mongo)
        emp = _seed_user(mongo, "employee", comp["company_id"])
        tok = _seed_session(mongo, emp["user_id"])

        today_dt = datetime.now(timezone.utc).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        # 2h + 2h = 4h today
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "in",
                           today_dt)
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "out",
                           today_dt + timedelta(hours=2))
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "in",
                           today_dt + timedelta(hours=5))
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "out",
                           today_dt + timedelta(hours=7))

        r = sess.get(f"{API}/attendance/summary?days=1", headers=_auth(tok))
        assert r.status_code == 200, r.text
        body = r.json()
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day = next((d for d in body["days"] if d["date"] == today_str), None)
        assert day is not None, body
        assert day["punches"] == 4, day
        assert day["hours"] == 4.0, day
        assert day["still_in"] is False, day


# ==================================================================
# 5) GET /api/admin/payroll/run — sums hours from multi-cycle days
# ==================================================================
class TestPayrollRunMultiPunch:
    def test_payroll_sums_two_blocks_same_day(self, sess, mongo):
        comp = _seed_company(mongo)
        admin = _seed_user(mongo, "company_admin", comp["company_id"])
        admin_tok = _seed_session(mongo, admin["user_id"])
        emp = _seed_user(mongo, "employee", comp["company_id"])

        # Two 2-hour blocks on today = 4h total; verify payroll shows 4h
        today = datetime.now(timezone.utc).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "in",
                           today)
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "out",
                           today + timedelta(hours=2))
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "in",
                           today + timedelta(hours=5))
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "out",
                           today + timedelta(hours=7))

        now = datetime.now(timezone.utc)
        r = sess.get(
            f"{API}/admin/payroll/run",
            headers=_auth(admin_tok),
            params={"year": now.year, "month": now.month},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        row = next((x for x in body["rows"] if x["user_id"] == emp["user_id"]), None)
        assert row is not None, body
        assert row["total_hours"] == 4.0, row

        # And the flat attendance list must report punches=4 for today
        today_str = now.strftime("%Y-%m-%d")
        att = next((a for a in body["attendance"]
                    if a["user_id"] == emp["user_id"] and a["date"] == today_str), None)
        assert att is not None
        assert att["punches"] == 4, att
        assert att["minutes"] == 240, att  # 4h == 240min


# ==================================================================
# 6) POST /api/admin/attendance/approve-punch — toggle idempotency,
#    allow multiple cycles
# ==================================================================
class TestAdminApprovePunchMultiCycle:
    def _mk(self, mongo):
        comp = _seed_company(mongo)
        admin = _seed_user(mongo, "company_admin", comp["company_id"])
        admin_tok = _seed_session(mongo, admin["user_id"])
        emp = _seed_user(mongo, "employee", comp["company_id"])
        # Place employee inside geofence
        mongo.users.update_one(
            {"user_id": emp["user_id"]},
            {"$set": {
                "last_location_lat": comp["office_lat"],
                "last_location_lng": comp["office_lng"],
                "last_location_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        return comp, admin, admin_tok, emp

    def test_admin_allows_multiple_in_out_cycles(self, sess, mongo):
        comp, admin, admin_tok, emp = self._mk(mongo)
        # IN → OUT → IN → OUT all via admin
        for kind in ["in", "out", "in", "out"]:
            r = sess.post(
                f"{API}/admin/attendance/approve-punch",
                headers=_auth(admin_tok),
                json={"user_id": emp["user_id"], "kind": kind},
            )
            assert r.status_code == 200, (kind, r.text)
            CREATED_ATTENDANCE_IDS.append(r.json()["record_id"])
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        recs = list(mongo.attendance.find(
            {"user_id": emp["user_id"], "date": today}
        ).sort("at", 1))
        assert len(recs) == 4
        assert [r["kind"] for r in recs] == ["in", "out", "in", "out"]

    def test_admin_double_in_blocked_after_close(self, sess, mongo):
        """After IN→OUT, admin CAN do another IN. But not a third IN
        immediately after the second IN."""
        comp, admin, admin_tok, emp = self._mk(mongo)
        r1 = sess.post(f"{API}/admin/attendance/approve-punch",
                       headers=_auth(admin_tok),
                       json={"user_id": emp["user_id"], "kind": "in"})
        assert r1.status_code == 200
        CREATED_ATTENDANCE_IDS.append(r1.json()["record_id"])
        r2 = sess.post(f"{API}/admin/attendance/approve-punch",
                       headers=_auth(admin_tok),
                       json={"user_id": emp["user_id"], "kind": "out"})
        assert r2.status_code == 200
        CREATED_ATTENDANCE_IDS.append(r2.json()["record_id"])
        # Second IN — should be ALLOWED (cycle 2 opening)
        r3 = sess.post(f"{API}/admin/attendance/approve-punch",
                       headers=_auth(admin_tok),
                       json={"user_id": emp["user_id"], "kind": "in"})
        assert r3.status_code == 200, r3.text
        CREATED_ATTENDANCE_IDS.append(r3.json()["record_id"])
        # Third IN back-to-back — must be blocked
        r4 = sess.post(f"{API}/admin/attendance/approve-punch",
                       headers=_auth(admin_tok),
                       json={"user_id": emp["user_id"], "kind": "in"})
        assert r4.status_code == 400, r4.text
        assert "already" in (r4.json().get("detail") or "").lower()

    def test_admin_out_before_in_blocked(self, sess, mongo):
        comp, admin, admin_tok, emp = self._mk(mongo)
        r = sess.post(f"{API}/admin/attendance/approve-punch",
                      headers=_auth(admin_tok),
                      json={"user_id": emp["user_id"], "kind": "out"})
        assert r.status_code == 400, r.text
        assert "not currently punched-in" in (r.json().get("detail") or "").lower()
