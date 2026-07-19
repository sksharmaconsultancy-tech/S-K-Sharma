"""Iter (Geofence Phase 2) — offline attendance punching backend tests.

Coverage:
 1. GET /api/attendance/my-geo-policy honours firm master
    ``offline_geofence_enabled`` and defaults to False.
 2. POST /api/attendance/punch with offline=True + client_punch_at ~2h ago
    stores the record at that (IST-wall-clock-labelled) time.
 3. Same POST re-sent (same client_dedupe_id) is idempotent — duplicate:True
    and NO second attendance row.
 4. offline=True but client_punch_at 30 days in past falls outside sanity
    window → punch is stored at server-now (client_punch_at ignored).

Cleanup: all TEST punches inserted are removed, and the firm's
``offline_geofence_enabled`` flag is restored to its original value.
"""
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_BACKEND_URL",
                          "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

COMPANY_ID = "cmp_527fecdd7c"          # Kankani
EMP_LOGIN_ID = "TEST50"
EMP_PIN = "123456"
EMP_USER_ID = "user_44cd6f561da0"

# 1x1 transparent PNG (data URL) — good enough for selfie payload
DUMMY_SELFIE = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
    "nGNgAAIAAAUAAeImBZsAAAAASUVORK5CYII="
)

IST_OFFSET = timedelta(hours=5, minutes=30)


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def emp_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/pin-login",
        json={"login_id": EMP_LOGIN_ID, "pin": EMP_PIN},
        timeout=15,
    )
    assert r.status_code == 200, f"Employee login failed: {r.status_code} {r.text}"
    tok = r.json().get("session_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def emp_headers(emp_token):
    return {"Authorization": f"Bearer {emp_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def firm_office(mongo):
    """Ensure the employee has gps_punch_enabled=True and return office coords."""
    firm = mongo.companies.find_one({"company_id": COMPANY_ID},
                                    {"_id": 0, "office_lat": 1, "office_lng": 1,
                                     "geofence_radius_m": 1,
                                     "offline_geofence_enabled": 1,
                                     "location_punching_enabled": 1})
    assert firm and firm.get("office_lat") and firm.get("office_lng"), "Firm missing office coords"
    orig_offline = firm.get("offline_geofence_enabled")
    # Enable GPS opt-in for the test employee (so we bypass manual-selfie gate).
    orig_user = mongo.users.find_one({"user_id": EMP_USER_ID},
                                     {"_id": 0, "gps_punch_enabled": 1}) or {}
    mongo.users.update_one({"user_id": EMP_USER_ID},
                           {"$set": {"gps_punch_enabled": True}})
    yield firm
    # restore original firm flag and user opt-in
    mongo.companies.update_one({"company_id": COMPANY_ID},
                               {"$set": {"offline_geofence_enabled": bool(orig_offline)
                                          if orig_offline is not None else False}})
    if orig_user.get("gps_punch_enabled") is None:
        mongo.users.update_one({"user_id": EMP_USER_ID},
                               {"$unset": {"gps_punch_enabled": ""}})
    else:
        mongo.users.update_one({"user_id": EMP_USER_ID},
                               {"$set": {"gps_punch_enabled": bool(orig_user["gps_punch_enabled"])}})


@pytest.fixture(autouse=True)
def cleanup_test_punches(mongo):
    """Delete any punches created with test dedupe ids at the end of each test."""
    yield
    mongo.attendance.delete_many(
        {"client_dedupe_id": {"$regex": "^ITERGP2_"}}
    )


# ---------------------------------------------------------------------------
# BACKEND 1: my-geo-policy honours offline_geofence_enabled
# ---------------------------------------------------------------------------
class TestMyGeoPolicy:
    def test_default_off(self, mongo, emp_headers, firm_office):
        mongo.companies.update_one({"company_id": COMPANY_ID},
                                   {"$set": {"offline_geofence_enabled": False}})
        r = requests.get(f"{BASE_URL}/api/attendance/my-geo-policy",
                         headers=emp_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "offline_punch_enabled" in body
        assert body["offline_punch_enabled"] is False
        assert body.get("mode") in ("strict", "flexible", "field", "remote", "emergency")

    def test_toggle_on(self, mongo, emp_headers, firm_office):
        mongo.companies.update_one({"company_id": COMPANY_ID},
                                   {"$set": {"offline_geofence_enabled": True}})
        r = requests.get(f"{BASE_URL}/api/attendance/my-geo-policy",
                         headers=emp_headers, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("offline_punch_enabled") is True
        # Restore so downstream tests aren't perturbed.
        mongo.companies.update_one({"company_id": COMPANY_ID},
                                   {"$set": {"offline_geofence_enabled": False}})


# ---------------------------------------------------------------------------
# BACKEND 2 & 3: offline punch honours client_punch_at + idempotent on dedupe
# ---------------------------------------------------------------------------
class TestOfflinePunchIdempotent:
    def test_offline_punch_uses_client_punch_at(self, mongo, emp_headers, firm_office):
        # 2 hours ago (UTC) — inside sanity window (7 days back → 10 min future).
        capture_utc = datetime.now(timezone.utc) - timedelta(hours=2)
        capture_iso = capture_utc.isoformat().replace("+00:00", "Z")
        dedupe = f"ITERGP2_dedupe_2h_{int(time.time())}"

        payload = {
            "kind": "in",
            "latitude": firm_office["office_lat"],
            "longitude": firm_office["office_lng"],
            "biometric_method": "face",
            "selfie_base64": DUMMY_SELFIE,
            "offline": True,
            "client_dedupe_id": dedupe,
            "client_punch_at": capture_iso,
        }
        r = requests.post(f"{BASE_URL}/api/attendance/punch",
                          headers=emp_headers, json=payload, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        # Not marked duplicate on first insert.
        assert not body.get("duplicate")

        # Verify record persisted with client_punch_at + IST-wall-clock at.
        rec = mongo.attendance.find_one(
            {"user_id": EMP_USER_ID, "client_dedupe_id": dedupe},
            {"_id": 0},
        )
        assert rec is not None, "attendance record not persisted"
        assert rec.get("offline_punch") is True
        assert rec.get("client_dedupe_id") == dedupe
        assert rec.get("client_punch_at") == capture_iso
        assert rec.get("synced_at"), "synced_at should be set for offline punches"

        # `at` stores IST-wall-clock labelled UTC (see server.py convention).
        # Expected: capture_utc + 05:30 as naive-in-UTC-string.
        expected_ist = (capture_utc + IST_OFFSET).replace(tzinfo=timezone.utc)
        at_dt = datetime.fromisoformat(rec["at"].replace("Z", "+00:00"))
        if at_dt.tzinfo is None:
            at_dt = at_dt.replace(tzinfo=timezone.utc)
        # Allow 2 min drift for processing time.
        diff = abs((at_dt - expected_ist).total_seconds())
        assert diff < 120, (
            f"`at` ({rec['at']}) did not follow client_punch_at (IST expected "
            f"{expected_ist.isoformat()}); diff={diff}s"
        )
        # `date` derives from the (IST-labelled) `at`, not server now.
        assert rec["date"] == expected_ist.strftime("%Y-%m-%d"), (
            f"date {rec['date']} != expected {expected_ist:%Y-%m-%d} "
            f"(server may have used now)"
        )

        # ------- BACKEND 3: repeat with same dedupe → duplicate:True, no new row.
        pre_count = mongo.attendance.count_documents(
            {"user_id": EMP_USER_ID, "client_dedupe_id": dedupe})
        r2 = requests.post(f"{BASE_URL}/api/attendance/punch",
                           headers=emp_headers, json=payload, timeout=20)
        assert r2.status_code == 200, r2.text
        b2 = r2.json()
        assert b2.get("duplicate") is True, f"expected duplicate=True, got {b2}"
        post_count = mongo.attendance.count_documents(
            {"user_id": EMP_USER_ID, "client_dedupe_id": dedupe})
        assert post_count == pre_count == 1, (
            f"duplicate insert! pre={pre_count} post={post_count}")


# ---------------------------------------------------------------------------
# BACKEND 4: sanity window — 30 days old client_punch_at falls back to now
# ---------------------------------------------------------------------------
class TestOfflinePunchStaleFallback:
    def test_30_days_old_falls_back_to_server_now(self, mongo, emp_headers, firm_office):
        capture_utc = datetime.now(timezone.utc) - timedelta(days=30)
        capture_iso = capture_utc.isoformat().replace("+00:00", "Z")
        dedupe = f"ITERGP2_dedupe_30d_{int(time.time())}"

        payload = {
            "kind": "in",
            "latitude": firm_office["office_lat"],
            "longitude": firm_office["office_lng"],
            "biometric_method": "face",
            "selfie_base64": DUMMY_SELFIE,
            "offline": True,
            "client_dedupe_id": dedupe,
            "client_punch_at": capture_iso,
        }
        r = requests.post(f"{BASE_URL}/api/attendance/punch",
                          headers=emp_headers, json=payload, timeout=20)
        assert r.status_code == 200, r.text
        rec = mongo.attendance.find_one(
            {"user_id": EMP_USER_ID, "client_dedupe_id": dedupe}, {"_id": 0})
        assert rec is not None
        assert rec.get("offline_punch") is True
        # `at` should be near IST-wall-clock now (server rejected stale capture).
        server_ist_now = datetime.now(timezone.utc) + IST_OFFSET
        at_dt = datetime.fromisoformat(rec["at"].replace("Z", "+00:00"))
        if at_dt.tzinfo is None:
            at_dt = at_dt.replace(tzinfo=timezone.utc)
        server_ist_now = server_ist_now.replace(tzinfo=at_dt.tzinfo)
        diff = abs((at_dt - server_ist_now).total_seconds())
        assert diff < 300, (
            f"stale capture time was NOT rejected — `at`={rec['at']} vs server-now "
            f"IST {server_ist_now.isoformat()} (diff={diff}s)")
        # date should be today's IST wall-clock, NOT 30 days ago.
        assert rec["date"] == server_ist_now.strftime("%Y-%m-%d"), (
            f"date {rec['date']} should reflect server-now, not 30 days ago")
