"""Iter 99 - Punch policy + notifications + leave balance verification.

Tests the mandatory-geofence punch endpoint, personal punch notifications,
first-punch-status, and CL/PL leave balance endpoint.

Seeds a TEST_ firm and TEST_ employees directly in MongoDB (with pre-baked
session tokens) so we don't need to run the auth/OTP flow.  All created
docs are prefixed with TEST_ (or the test-only company id) so cleanup is
easy.
"""

import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or \
           os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

_mc = MongoClient(MONGO_URL)
db = _mc[DB_NAME]

# Test company (fits geofence around office lat/lng)
TEST_CID = "cmp_iter99test"
OFFICE_LAT = 25.3450
OFFICE_LNG = 74.6350
RADIUS_M = 200

INSIDE = (25.3451, 74.6351)          # ~15 m from office
OUTSIDE = (25.3900, 74.6800)         # ~5+ km away


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _mk_token(uid: str) -> str:
    tok = "TEST_" + uuid.uuid4().hex
    db.user_sessions.insert_one({
        "session_token": tok,
        "user_id": uid,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "created_at": _now_iso(),
        "auth_method": "test",
    })
    return tok


def _mk_user(*, is_live_in=False, gps_enabled=True, name="TEST_Emp"):
    uid = "TEST_user_" + uuid.uuid4().hex[:8]
    db.users.insert_one({
        "user_id": uid,
        "name": name,
        "role": "employee",
        "employee_code": f"TEST_{uid[-4:]}",
        "company_id": TEST_CID,
        "gps_punch_enabled": gps_enabled,
        "is_live_in": is_live_in,
        "pin_hash": "TESTNOOP",
        "created_at": _now_iso(),
    })
    return uid, _mk_token(uid)


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module", autouse=True)
def seed():
    # ------- Clean any previous run
    db.companies.delete_many({"company_id": TEST_CID})
    db.firm_masters.delete_many({"company_id": TEST_CID})
    db.users.delete_many({"company_id": TEST_CID})
    db.attendance.delete_many({"company_id": TEST_CID})
    db.leaves.delete_many({"company_id": TEST_CID})
    db.notifications.delete_many({"company_id": TEST_CID})
    db.user_sessions.delete_many({"session_token": {"$regex": "^TEST_"}})

    # ------- Firm (geofence enforced, gps enabled)
    db.companies.insert_one({
        "company_id": TEST_CID,
        "name": "TEST_Iter99_Firm",
        "code": "TEST99",
        "office_lat": OFFICE_LAT,
        "office_lng": OFFICE_LNG,
        "geofence_radius_m": RADIUS_M,
        "location_punching_enabled": True,
        "reject_outside_geofence": True,
        "face_match_enabled": False,
        "created_at": _now_iso(),
    })
    # ------- Firm master with leave policy
    db.firm_masters.insert_one({
        "company_id": TEST_CID,
        "leave_policy": {
            "cl_pl_applicable": True,
            "cl_day_limit": 7,
            "pl_day_limit": 15,
        },
    })

    yield

    # ------- Cleanup
    db.companies.delete_many({"company_id": TEST_CID})
    db.firm_masters.delete_many({"company_id": TEST_CID})
    db.users.delete_many({"company_id": TEST_CID})
    db.attendance.delete_many({"company_id": TEST_CID})
    db.leaves.delete_many({"company_id": TEST_CID})
    db.notifications.delete_many({"company_id": TEST_CID})
    db.user_sessions.delete_many({"session_token": {"$regex": "^TEST_"}})


# ============================================================================
# Punch policy matrix (Iter 99)
# ============================================================================
class TestPunchPolicy:

    def test_a_punch_in_without_coords_rejected(self, api_client):
        uid, tok = _mk_user(name="TEST_EmpA")
        r = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={"kind": "in", "biometric_method": "face"},
        )
        assert r.status_code == 400, r.text
        assert "location" in r.text.lower() or "geofence" in r.text.lower(), r.text

    def test_b_punch_in_inside_fence_ok(self, api_client):
        uid, tok = _mk_user(name="TEST_EmpB")
        r = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={
                "kind": "in", "biometric_method": "face",
                "latitude": INSIDE[0], "longitude": INSIDE[1],
                "source": "manual",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert data.get("outside_geofence") is False
        assert data.get("record_id")

        # Verify persistence
        att = db.attendance.find_one({"record_id": data["record_id"]}, {"_id": 0})
        assert att is not None
        assert att["user_id"] == uid
        assert att["kind"] == "in"

    def test_c_punch_out_outside_fence_rejected(self, api_client):
        uid, tok = _mk_user(name="TEST_EmpC")
        # first punch IN inside
        r_in = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={"kind": "in", "biometric_method": "face",
                  "latitude": INSIDE[0], "longitude": INSIDE[1]},
        )
        assert r_in.status_code == 200, r_in.text
        # then punch OUT ~5km away
        r_out = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={"kind": "out", "biometric_method": "face",
                  "latitude": OUTSIDE[0], "longitude": OUTSIDE[1]},
        )
        assert r_out.status_code == 400, r_out.text
        assert "outside" in r_out.text.lower() or "geofence" in r_out.text.lower()

    def test_d1_manual_mode_no_selfie_rejected(self, api_client):
        # Manual mode: user gps_punch_enabled=False
        uid, tok = _mk_user(name="TEST_EmpD1", gps_enabled=False)
        r = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={"kind": "in", "biometric_method": "face",
                  "latitude": INSIDE[0], "longitude": INSIDE[1]},
        )
        assert r.status_code == 400, r.text
        assert "selfie" in r.text.lower(), r.text

    def test_d2_manual_mode_with_selfie_and_coords_ok(self, api_client):
        uid, tok = _mk_user(name="TEST_EmpD2", gps_enabled=False)
        r = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={
                "kind": "in", "biometric_method": "face",
                "selfie_base64": "data:image/png;base64,iVBORw0KGgo=",
                "latitude": INSIDE[0], "longitude": INSIDE[1],
                "source": "manual-nogps",
            },
        )
        assert r.status_code == 200, r.text

    def test_d3_manual_mode_with_selfie_no_coords_rejected(self, api_client):
        uid, tok = _mk_user(name="TEST_EmpD3", gps_enabled=False)
        r = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={
                "kind": "in", "biometric_method": "face",
                "selfie_base64": "data:image/png;base64,iVBORw0KGgo=",
            },
        )
        assert r.status_code == 400, r.text
        assert "location" in r.text.lower() or "geofence" in r.text.lower(), r.text

    def test_e_live_in_no_coords_ok(self, api_client):
        uid, tok = _mk_user(name="TEST_EmpE", is_live_in=True)
        r = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={"kind": "in", "biometric_method": "face"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True


# ============================================================================
# Personal punch notification
# ============================================================================
class TestPunchNotification:

    def test_notification_created_and_visible(self, api_client):
        uid, tok = _mk_user(name="TEST_NotifOwner")
        r = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={"kind": "in", "biometric_method": "face",
                  "latitude": INSIDE[0], "longitude": INSIDE[1]},
        )
        assert r.status_code == 200, r.text

        # DB check
        notif = db.notifications.find_one(
            {"audience": "user", "target_user_id": uid},
            {"_id": 0},
        )
        assert notif is not None, "expected user-audience notification in DB"
        assert notif.get("title", "").startswith("Punch IN"), notif.get("title")
        assert "TEST_Iter99_Firm" in (notif.get("title") or "")

        # GET /notifications returns it for owner
        g = api_client.get(f"{API}/notifications",
                           headers={"Authorization": f"Bearer {tok}"})
        assert g.status_code == 200, g.text
        items = g.json().get("notifications", [])
        got = [n for n in items if n.get("target_user_id") == uid]
        assert got, "employee did not see own punch notification"

        # Another employee (same firm) must NOT see it
        _, other_tok = _mk_user(name="TEST_Bystander")
        g2 = api_client.get(f"{API}/notifications",
                            headers={"Authorization": f"Bearer {other_tok}"})
        assert g2.status_code == 200
        leaked = [n for n in g2.json().get("notifications", [])
                  if n.get("target_user_id") == uid]
        assert not leaked, "another employee saw personal notification"


# ============================================================================
# first-punch-status
# ============================================================================
class TestFirstPunchStatus:

    def test_pending_for_new_employee_then_false(self, api_client):
        uid, tok = _mk_user(name="TEST_FirstPunch")
        r1 = api_client.get(f"{API}/attendance/first-punch-status",
                            headers={"Authorization": f"Bearer {tok}"})
        assert r1.status_code == 200, r1.text
        assert r1.json().get("first_punch_pending") is True

        # Do a punch
        p = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={"kind": "in", "biometric_method": "face",
                  "latitude": INSIDE[0], "longitude": INSIDE[1]},
        )
        assert p.status_code == 200, p.text

        r2 = api_client.get(f"{API}/attendance/first-punch-status",
                            headers={"Authorization": f"Bearer {tok}"})
        assert r2.status_code == 200
        assert r2.json().get("first_punch_pending") is False

    def test_admin_returns_false(self, api_client):
        # Seed an admin user
        uid = "TEST_admin_" + uuid.uuid4().hex[:6]
        db.users.insert_one({
            "user_id": uid, "role": "company_admin",
            "company_id": TEST_CID, "name": "TEST_Admin",
            "created_at": _now_iso(),
        })
        tok = _mk_token(uid)
        r = api_client.get(f"{API}/attendance/first-punch-status",
                           headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        assert r.json().get("first_punch_pending") is False


# ============================================================================
# Leave balance
# ============================================================================
class TestLeaveBalance:

    def test_balance_with_approved_casual(self, api_client):
        uid, tok = _mk_user(name="TEST_LeaveEmp")
        # Seed one approved 2-day casual leave in current year
        year = datetime.utcnow().year
        db.leaves.insert_one({
            "leave_id": "TEST_lv_" + uuid.uuid4().hex[:8],
            "user_id": uid,
            "company_id": TEST_CID,
            "leave_type": "casual",
            "from_date": f"{year}-03-10",
            "to_date": f"{year}-03-11",
            "status": "approved",
            "created_at": _now_iso(),
        })
        r = api_client.get(f"{API}/leaves/balance",
                           headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("year") == year
        assert data.get("cl_pl_applicable") is True
        assert data.get("cl_allowed") == 7
        assert data.get("pl_allowed") == 15
        assert data.get("cl_taken") == 2
        assert data.get("cl_balance") == 5
        assert data.get("pl_taken") == 0
        assert data.get("pl_balance") == 15


# ============================================================================
# Regression: double-IN
# ============================================================================
class TestRegression:

    def test_double_in_rejected(self, api_client):
        uid, tok = _mk_user(name="TEST_DoubleIn")
        r1 = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={"kind": "in", "biometric_method": "face",
                  "latitude": INSIDE[0], "longitude": INSIDE[1]},
        )
        assert r1.status_code == 200, r1.text
        r2 = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={"kind": "in", "biometric_method": "face",
                  "latitude": INSIDE[0], "longitude": INSIDE[1]},
        )
        assert r2.status_code == 400, r2.text
        assert "already punched in" in r2.text.lower()

    def test_geofence_auto_source_inside_ok(self, api_client):
        uid, tok = _mk_user(name="TEST_AutoSrc")
        r = api_client.post(f"{API}/attendance/punch",
            headers={"Authorization": f"Bearer {tok}"},
            json={"kind": "in", "biometric_method": "face",
                  "latitude": INSIDE[0], "longitude": INSIDE[1],
                  "source": "geofence-auto"},
        )
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True
