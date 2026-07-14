"""Iter 24 backend tests — Phase B: Duty hours summary + Present-today.

Endpoints under test:
  GET /api/attendance/summary?days=7
  GET /api/admin/attendance/today?company_id=<optional>

Seeds ephemeral company + ephemeral employees + user_sessions + attendance
records via pymongo. Cleans everything up. Never touches super_admin.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient


BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL missing in environment")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_for_day(days_ago: int, hh: int, mm: int = 0) -> tuple[str, str]:
    """Return (yyyy-mm-dd, iso timestamp) for `days_ago` days ago at hh:mm UTC."""
    now = datetime.now(timezone.utc)
    d = now - timedelta(days=days_ago)
    dt = d.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return dt.strftime("%Y-%m-%d"), dt.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


TAG = f"iter24_{uuid.uuid4().hex[:6]}"
COMPANY_ID = f"cmp_{TAG}"
COMPANY_CODE = f"IT24{uuid.uuid4().hex[:4].upper()}"
EMP_A_ID = f"usr_{TAG}_a"
EMP_B_ID = f"usr_{TAG}_b"
EMP_C_ID = f"usr_{TAG}_c"  # never punches → should NOT be in present-today
CO_ADMIN_ID = f"usr_{TAG}_ca"


@pytest.fixture(scope="module", autouse=True)
def seed(mongo):
    # Company
    mongo.companies.insert_one({
        "company_id": COMPANY_ID,
        "company_code": COMPANY_CODE,
        "name": f"TEST_{TAG}_Co",
        "address": "TEST HQ",
        "office_lat": 28.61,
        "office_lng": 77.23,
        "geofence_radius_m": 200,
        "created_at": _now_iso(),
    })
    common = {
        "company_id": COMPANY_ID,
        "role": "employee",
        "onboarded": True,
        "approval_status": "approved",
        "created_at": _now_iso(),
    }
    mongo.users.insert_many([
        {"user_id": EMP_A_ID, "name": f"TEST_{TAG}_Alice",
         "email": f"{TAG}_a@x.com", "phone": None,
         "employee_code": "E001", **common},
        {"user_id": EMP_B_ID, "name": f"TEST_{TAG}_Bob",
         "email": f"{TAG}_b@x.com", "phone": None,
         "employee_code": "E002", **common},
        {"user_id": EMP_C_ID, "name": f"TEST_{TAG}_Carol",
         "email": f"{TAG}_c@x.com", "phone": None,
         "employee_code": "E003", **common},
        {"user_id": CO_ADMIN_ID, "name": f"TEST_{TAG}_CoAdmin",
         "email": f"{TAG}_ca@x.com", "phone": None,
         "employee_code": None, "company_id": COMPANY_ID,
         "role": "company_admin", "onboarded": True,
         "approval_status": "approved", "created_at": _now_iso()},
    ])

    # Sessions — reuse the same shape server issues
    def _mk_session(uid: str) -> str:
        tok = f"iter24_{uuid.uuid4().hex}{uuid.uuid4().hex}"
        mongo.user_sessions.insert_one({
            "session_token": tok,
            "user_id": uid,
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
            "created_at": datetime.now(timezone.utc),
            "auth_method": "iter24_seed",
        })
        return tok

    tokens = {
        "a": _mk_session(EMP_A_ID),
        "b": _mk_session(EMP_B_ID),
        "c": _mk_session(EMP_C_ID),
        "ca": _mk_session(CO_ADMIN_ID),
    }

    # -----------------------------------------------------------------
    # Attendance seed for EMP_A:
    #   today (days_ago=0):  IN 09:00, OUT 12:00, IN 13:00, OUT 17:00  → 8h
    #   2 days ago:          IN 09:00, OUT 13:00                       → 4h
    #   4 days ago:          IN 10:00 (no out)                          → still_in, 0h
    #   older_than_window (10 days ago): IN 09:00 OUT 11:00              → 2h all-time only
    # EMP_B: today IN at 08:30 only (still_in), included in present-today.
    # EMP_C: no attendance (control — must NOT appear in present-today).
    # -----------------------------------------------------------------
    attendance_docs = []

    def _rec(uid: str, days_ago: int, hh: int, mm: int, kind: str):
        date, at = _iso_for_day(days_ago, hh, mm)
        attendance_docs.append({
            "record_id": f"att_{uuid.uuid4().hex[:12]}",
            "user_id": uid,
            "company_id": COMPANY_ID,
            "date": date,
            "kind": kind,
            "at": at,
            "latitude": 28.61,
            "longitude": 77.23,
            "distance_m": 5.0,
        })

    # EMP_A today — 8 hours (two closed sessions): 09-12 (3h) + 13-18 (5h) = 8h
    _rec(EMP_A_ID, 0, 9, 0, "in")
    _rec(EMP_A_ID, 0, 12, 0, "out")
    _rec(EMP_A_ID, 0, 13, 0, "in")
    _rec(EMP_A_ID, 0, 18, 0, "out")
    # EMP_A 2 days ago — 4 hours
    _rec(EMP_A_ID, 2, 9, 0, "in")
    _rec(EMP_A_ID, 2, 13, 0, "out")
    # EMP_A 4 days ago — still_in (unmatched IN)
    _rec(EMP_A_ID, 4, 10, 0, "in")
    # EMP_A 10 days ago — outside 7d window, 2h all-time only
    _rec(EMP_A_ID, 10, 9, 0, "in")
    _rec(EMP_A_ID, 10, 11, 0, "out")

    # EMP_B today — still_in (only IN)
    _rec(EMP_B_ID, 0, 8, 30, "in")

    mongo.attendance.insert_many(attendance_docs)

    yield tokens

    # Cleanup
    mongo.attendance.delete_many({"company_id": COMPANY_ID})
    mongo.user_sessions.delete_many({"auth_method": "iter24_seed"})
    mongo.users.delete_many({"user_id": {"$in": [
        EMP_A_ID, EMP_B_ID, EMP_C_ID, CO_ADMIN_ID
    ]}})
    mongo.companies.delete_many({"company_id": COMPANY_ID})


# ---------------------------------------------------------------------------
# GET /api/attendance/summary
# ---------------------------------------------------------------------------
class TestAttendanceSummary:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/attendance/summary?days=7", timeout=15)
        assert r.status_code in (401, 403), r.text

    def test_default_shape(self, seed):
        h = {"Authorization": f"Bearer {seed['a']}"}
        r = requests.get(f"{BASE_URL}/api/attendance/summary?days=7",
                         headers=h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) >= {"days", "window_total_hours",
                                    "total_hours_till_today"}
        assert isinstance(body["days"], list)
        assert len(body["days"]) == 7, f"expected 7 days got {len(body['days'])}"

        # oldest → newest
        dates = [d["date"] for d in body["days"]]
        assert dates == sorted(dates), f"days not oldest→newest: {dates}"

        # Each entry has the right keys/types
        for d in body["days"]:
            assert set(d.keys()) >= {"date", "hours", "first_in",
                                      "last_out", "still_in", "punches"}
            assert isinstance(d["hours"], (int, float))
            assert isinstance(d["still_in"], bool)
            assert isinstance(d["punches"], int)

    def test_today_hours_and_pairing(self, seed):
        h = {"Authorization": f"Bearer {seed['a']}"}
        r = requests.get(f"{BASE_URL}/api/attendance/summary?days=7",
                         headers=h, timeout=15).json()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = next(d for d in r["days"] if d["date"] == today)
        assert row["punches"] == 4
        assert row["still_in"] is False
        assert abs(row["hours"] - 8.0) <= 0.05, f"expected ~8h got {row['hours']}"

    def test_still_in_day_hours_zero(self, seed):
        h = {"Authorization": f"Bearer {seed['a']}"}
        r = requests.get(f"{BASE_URL}/api/attendance/summary?days=7",
                         headers=h, timeout=15).json()
        target_date = (datetime.now(timezone.utc) - timedelta(days=4)) \
            .strftime("%Y-%m-%d")
        row = next(d for d in r["days"] if d["date"] == target_date)
        assert row["still_in"] is True
        assert row["punches"] == 1
        assert row["hours"] == 0, \
            f"unmatched IN should not add hours, got {row['hours']}"

    def test_missing_days_zero(self, seed):
        h = {"Authorization": f"Bearer {seed['a']}"}
        r = requests.get(f"{BASE_URL}/api/attendance/summary?days=7",
                         headers=h, timeout=15).json()
        # Day 1 ago has no records for EMP_A → hours=0, punches=0
        target = (datetime.now(timezone.utc) - timedelta(days=1)) \
            .strftime("%Y-%m-%d")
        row = next(d for d in r["days"] if d["date"] == target)
        assert row["hours"] == 0
        assert row["punches"] == 0
        assert row["first_in"] is None
        assert row["last_out"] is None
        assert row["still_in"] is False

    def test_window_total_equals_sum_days(self, seed):
        h = {"Authorization": f"Bearer {seed['a']}"}
        r = requests.get(f"{BASE_URL}/api/attendance/summary?days=7",
                         headers=h, timeout=15).json()
        s = sum(d["hours"] for d in r["days"])
        assert abs(r["window_total_hours"] - s) <= 0.1, \
            f"window total {r['window_total_hours']} != sum {s}"
        # Window has 8h (today) + 4h (2 days ago) = 12h
        assert abs(r["window_total_hours"] - 12.0) <= 0.1

    def test_total_till_today_includes_old(self, seed):
        h = {"Authorization": f"Bearer {seed['a']}"}
        r = requests.get(f"{BASE_URL}/api/attendance/summary?days=7",
                         headers=h, timeout=15).json()
        # 8h today + 4h (2d) + 2h (10d, outside window) = 14h
        assert abs(r["total_hours_till_today"] - 14.0) <= 0.1, \
            f"expected ~14h total got {r['total_hours_till_today']}"
        # And it MUST be >= window_total
        assert r["total_hours_till_today"] >= r["window_total_hours"] - 0.01


# ---------------------------------------------------------------------------
# GET /api/admin/attendance/today
# ---------------------------------------------------------------------------
class TestAdminAttendanceToday:
    def test_requires_admin_role(self, seed):
        # Regular employee should be forbidden
        h = {"Authorization": f"Bearer {seed['a']}"}
        r = requests.get(f"{BASE_URL}/api/admin/attendance/today",
                         headers=h, timeout=15)
        assert r.status_code in (401, 403), r.text

    def test_unauth(self):
        r = requests.get(f"{BASE_URL}/api/admin/attendance/today", timeout=15)
        assert r.status_code in (401, 403)

    def test_company_admin_scope(self, seed):
        h = {"Authorization": f"Bearer {seed['ca']}"}
        r = requests.get(f"{BASE_URL}/api/admin/attendance/today",
                         headers=h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "date" in body and "present" in body
        # Force-scoped to caller's company; only EMP_A + EMP_B punched today
        ids = {p["user_id"] for p in body["present"]}
        assert EMP_A_ID in ids
        assert EMP_B_ID in ids
        assert EMP_C_ID not in ids, "Carol didn't punch, must not appear"

        # Rows ordered by first_in ascending
        firsts = [p["first_in"] for p in body["present"] if p.get("first_in")]
        assert firsts == sorted(firsts), f"not sorted asc: {firsts}"

        # Verify per-row fields
        alice = next(p for p in body["present"] if p["user_id"] == EMP_A_ID)
        assert alice["still_in"] is False
        assert abs(alice["hours"] - 8.0) <= 0.05
        assert alice["punches"] == 4
        assert alice["employee_code"] == "E001"
        assert alice["company_id"] == COMPANY_ID
        assert alice["company_name"] == f"TEST_{TAG}_Co"
        assert alice["first_in"] and alice["last_out"]

        bob = next(p for p in body["present"] if p["user_id"] == EMP_B_ID)
        assert bob["still_in"] is True
        assert bob["hours"] == 0
        assert bob["last_out"] is None

    def test_company_admin_cannot_escape_scope(self, seed):
        """Even if company_admin passes ?company_id=other_id, server forces own."""
        h = {"Authorization": f"Bearer {seed['ca']}"}
        r_own = requests.get(
            f"{BASE_URL}/api/admin/attendance/today?company_id=cmp_bogus_xyz",
            headers=h, timeout=15).json()
        # Should still return only OUR company's punches (or none if the
        # bogus id somehow won). We seeded EMP_A+B punches today.
        ids = {p["user_id"] for p in r_own["present"]}
        assert EMP_A_ID in ids and EMP_B_ID in ids, \
            f"company_admin scope escape? got {ids}"
