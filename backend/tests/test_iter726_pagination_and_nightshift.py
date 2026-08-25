"""Iter 726 backend tests — pagination, single-employee fast path,
night-shift missing-punch bug fix, and stitch_cross_day_ot regression.

Run:
    pytest /app/backend/tests/test_iter726_pagination_and_nightshift.py -v \
        --tb=short --junitxml=/app/test_reports/pytest/iter726.xml
"""
import os
import sys
import hashlib
import pytest
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") if os.environ.get("EXPO_PUBLIC_BACKEND_URL") else None
# Prefer preview URL from frontend .env
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("EXPO_PUBLIC_BACKEND_URL"):
                BASE_URL = line.strip().split("=", 1)[1].strip().strip('"').rstrip("/")
                break

KANKANI_CID = "cmp_527fecdd7c"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "test_database")


# ---------- auth fixtures ----------
@pytest.fixture(scope="session")
def admin_token():
    """Login super admin via password + 2FA (swap OTP hash in Mongo)."""
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/admin-password-login",
               json={"email": "sksharmaconsultancy@gmail.com",
                     "password": "sharma123"}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    if body.get("session_token"):
        return body["session_token"]
    pending = body.get("pending_token")
    assert pending, f"expected pending_token in {body}"
    db = MongoClient(MONGO_URL)[DB_NAME]
    db.twofa_pending.update_one(
        {"pending_id": pending},
        {"$set": {"otp_hash": hashlib.sha256(b"123456").hexdigest()}},
    )
    r2 = s.post(f"{BASE_URL}/api/auth/2fa/verify",
                json={"pending_token": pending, "otp": "123456"}, timeout=30)
    assert r2.status_code == 200, f"2fa verify failed: {r2.status_code} {r2.text[:200]}"
    tok = r2.json().get("session_token")
    assert tok, r2.json()
    return tok


@pytest.fixture
def auth_hdr(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _cur_month():
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


# ==================== BACKEND 1: Monthly grid pagination ====================
class TestMonthlyGridPagination:
    def test_skip0_limit5(self, auth_hdr):
        m = _cur_month()
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid/{KANKANI_CID}/{m}",
            params={"skip": 0, "limit": 5}, headers=auth_hdr, timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "total_rows" in d, "total_rows missing from paginated response"
        assert d.get("skip") == 0
        assert len(d.get("employees", [])) == 5, \
            f"expected 5 rows, got {len(d.get('employees', []))}"
        # firm should be ~127
        assert d["total_rows"] >= 100, f"total_rows unexpectedly low: {d['total_rows']}"

    def test_skip5_limit5_no_overlap(self, auth_hdr):
        m = _cur_month()
        r1 = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid/{KANKANI_CID}/{m}",
            params={"skip": 0, "limit": 5}, headers=auth_hdr, timeout=90)
        r2 = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid/{KANKANI_CID}/{m}",
            params={"skip": 5, "limit": 5}, headers=auth_hdr, timeout=90)
        assert r1.status_code == 200 and r2.status_code == 200
        ids1 = [e["user_id"] for e in r1.json()["employees"]]
        ids2 = [e["user_id"] for e in r2.json()["employees"]]
        assert len(ids2) == 5
        assert r2.json().get("skip") == 5
        assert set(ids1).isdisjoint(set(ids2)), \
            f"overlap between skip=0 and skip=5 pages: {set(ids1) & set(ids2)}"

    def test_no_limit_returns_all_and_no_total_rows(self, auth_hdr):
        m = _cur_month()
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid/{KANKANI_CID}/{m}",
            headers=auth_hdr, timeout=120)
        assert r.status_code == 200
        d = r.json()
        assert "total_rows" not in d, "total_rows must NOT appear when limit is absent (back-compat)"
        assert "skip" not in d
        assert len(d.get("employees", [])) >= 100, \
            f"expected ~127 rows, got {len(d.get('employees', []))}"


# ==================== BACKEND 2: Single-employee fast path ====================
class TestEmployeesFastPath:
    def test_full_list_returns_all(self, auth_hdr):
        r = requests.get(f"{BASE_URL}/api/admin/employees",
                         params={"company_id": KANKANI_CID},
                         headers=auth_hdr, timeout=60)
        assert r.status_code == 200
        emps = r.json().get("employees", [])
        assert len(emps) >= 100, f"expected ~127 employees, got {len(emps)}"
        # cache a user_id for the next test
        TestEmployeesFastPath._sample_uid = emps[0]["user_id"]

    def test_single_user_id_returns_one(self, auth_hdr):
        uid = getattr(TestEmployeesFastPath, "_sample_uid", None)
        assert uid, "prior test did not populate sample uid"
        r = requests.get(f"{BASE_URL}/api/admin/employees",
                         params={"user_id": uid},
                         headers=auth_hdr, timeout=30)
        assert r.status_code == 200
        emps = r.json().get("employees", [])
        assert len(emps) == 1, f"expected 1 employee for user_id={uid}, got {len(emps)}"
        assert emps[0]["user_id"] == uid


# ==================== BACKEND 3: Night-shift + stitch ====================
# These import the server functions directly.
class TestNightShiftMissingPunch:
    def _iso(self, dt):
        return dt.replace(tzinfo=timezone.utc).isoformat()

    def test_open_night_shift_recent_in_not_flagged(self):
        from server import has_unpaired_punches
        # lone IN 2h ago (well within 16h window) → NOT missing
        recent = datetime.now(timezone.utc) - timedelta(hours=2)
        punches = [{"at": recent.isoformat(), "kind": "in"}]
        assert has_unpaired_punches(punches) is False, \
            "recent open night-shift IN must NOT be flagged missing"

    def test_stale_open_in_still_flagged(self):
        from server import has_unpaired_punches
        stale = datetime.now(timezone.utc) - timedelta(days=6)
        punches = [{"at": stale.isoformat(), "kind": "in"}]
        assert has_unpaired_punches(punches) is True, \
            "6-day-old lone IN must STILL flag Missing Punch"

    def test_normal_in_out_same_day_not_flagged(self):
        from server import has_unpaired_punches
        base = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)
        punches = [
            {"at": base.isoformat(), "kind": "in"},
            {"at": (base + timedelta(hours=8)).isoformat(), "kind": "out"},
        ]
        assert has_unpaired_punches(punches) is False

    def test_in_in_double_punch_old_day_flagged(self):
        from server import has_unpaired_punches
        base = datetime(2025, 12, 1, 9, 0, tzinfo=timezone.utc)
        punches = [
            {"at": base.isoformat(), "kind": "in"},
            {"at": (base + timedelta(hours=1)).isoformat(), "kind": "in"},
        ]
        assert has_unpaired_punches(punches) is True

    def test_stitch_echo_within_30min_consumed(self):
        from server import stitch_cross_day_ot
        # day1 has an open IN at 21:00; day2 has OUT 05:00 + echo OUT 05:08
        d1 = "2026-01-05"
        d2 = "2026-01-06"
        pbd = {
            d1: [{"at": "2026-01-05T21:00:00+00:00", "kind": "in"}],
            d2: [
                {"at": "2026-01-06T05:00:00+00:00", "kind": "out"},
                {"at": "2026-01-06T05:08:00+00:00", "kind": "out"},
            ],
        }
        # stitch mutates or returns dict — support both patterns.
        try:
            result = stitch_cross_day_ot(pbd)
        except TypeError:
            result = stitch_cross_day_ot(pbd, {})
        out = result if isinstance(result, dict) else pbd
        day1 = out.get(d1, [])
        day2 = out.get(d2, [])
        d1_outs = [p for p in day1 if (p.get("kind") or "").lower() == "out"]
        assert len(d1_outs) >= 1, f"day1 must gain the 05:00 OUT: {day1}"
        assert len(day2) == 0, \
            f"day2 must be EMPTY after echo consumption, got {day2}"

    def test_stitch_regression_four_night_shifts(self):
        from server import stitch_cross_day_ot, has_unpaired_punches
        # Four consecutive night shifts 21:00 -> 05:00
        pbd = {}
        base = datetime(2026, 1, 10, tzinfo=timezone.utc)
        for i in range(4):
            d_in = (base + timedelta(days=i)).strftime("%Y-%m-%d")
            d_out = (base + timedelta(days=i + 1)).strftime("%Y-%m-%d")
            pbd.setdefault(d_in, []).append(
                {"at": f"{d_in}T21:00:00+00:00", "kind": "in"})
            pbd.setdefault(d_out, []).append(
                {"at": f"{d_out}T05:00:00+00:00", "kind": "out"})
        try:
            result = stitch_cross_day_ot(pbd)
        except TypeError:
            result = stitch_cross_day_ot(pbd, {})
        out = result if isinstance(result, dict) else pbd
        # Every day should now be a clean in-out pair or empty (last OUT).
        for dk, plist in out.items():
            assert not has_unpaired_punches(plist), \
                f"day {dk} unexpectedly flagged missing after stitch: {plist}"


# ==================== dedupe_close_punches sanity ====================
def test_dedupe_close_punches_import():
    from server import dedupe_close_punches
    base = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)
    dkey = "2026-01-10"
    pbd = {
        dkey: [
            {"at": base.isoformat(), "kind": "in", "source": "zkteco"},
            {"at": (base + timedelta(seconds=30)).isoformat(), "kind": "in", "source": "zkteco"},
        ]
    }
    out = dedupe_close_punches(pbd, window_min=5)
    assert isinstance(out, dict)
    assert len(out.get(dkey, [])) <= len(pbd[dkey])
