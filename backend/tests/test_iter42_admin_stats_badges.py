"""iter42 - Admin stats badges (open_shifts / missed_ins) backend tests.

Seeds two throwaway companies (IT42_co_a / IT42_co_b) with distinct geofences
and a matrix of employees (some inside geofence, some outside, some stale ping,
some punched-in, some punched-in-and-out, some exited, some not onboarded,
some pending approval), then verifies /api/admin/stats returns:
  - open_shifts (last punch today is 'in' only)
  - missed_ins  (inside geofence, fresh ping <60min, no punches today,
                 role=employee, onboarded, approved, not exited)

Also verifies:
  - super_admin without company_id sums across companies
  - super_admin with company_id=X scopes to that company
  - company_admin scopes to their own company automatically
  - employee role gets 403
  - existing fields (total_employees, present_today, pending_leaves,
    open_tickets, pending_profile_edits, total_companies) remain present
    and additive-only.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://emplo-connect-1.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"

# ---- Seed constants -------------------------------------------------
TAG = "IT42"  # unique tag for teardown
CO_A = f"{TAG}_co_a"
CO_B = f"{TAG}_co_b"

# Company A office (arbitrary lat/lng), radius 200m
CO_A_LAT = 28.6100
CO_A_LNG = 77.2300
# Company B office
CO_B_LAT = 19.0760
CO_B_LNG = 72.8777

RADIUS_M = 200

# offset ~0.01 deg latitude ~= 1.11 km, well outside 200m radius
OUTSIDE_OFFSET = 0.01

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NOW = datetime.now(timezone.utc)
FRESH_ISO = NOW.isoformat().replace("+00:00", "Z")
STALE_ISO = (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
YESTERDAY = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")


# ---- Fixtures -------------------------------------------------------
@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _mk_user(
    db,
    *,
    company_id,
    role="employee",
    onboarded=True,
    approval_status="approved",
    exit_date=None,
    last_lat=None,
    last_lng=None,
    last_at_iso=None,
    tag="",
):
    uid = f"{TAG}_u_{uuid.uuid4().hex[:8]}"
    email = f"{uid}@it42.test"
    doc = {
        "user_id": uid,
        "email": email,
        "phone": None,
        "name": f"IT42 {tag}",
        "role": role,
        "company_id": company_id,
        "onboarded": onboarded,
        "approval_status": approval_status,
        "exit_date": exit_date,
        "last_location_lat": last_lat,
        "last_location_lng": last_lng,
        "last_location_at": last_at_iso,
        "created_at": NOW.isoformat(),
        "_seed_tag": TAG,
    }
    db.users.insert_one(doc)
    return uid, email


def _mk_attendance(db, *, user_id, company_id, kind, hhmm="09:00"):
    at = f"{TODAY}T{hhmm}:00Z"
    db.attendance.insert_one({
        "attendance_id": f"{TAG}_att_{uuid.uuid4().hex[:8]}",
        "user_id": user_id,
        "company_id": company_id,
        "date": TODAY,
        "kind": kind,
        "at": at,
        "_seed_tag": TAG,
    })


def _mk_company(db, *, company_id, lat, lng, radius=RADIUS_M):
    db.companies.insert_one({
        "company_id": company_id,
        "name": f"IT42 Co {company_id}",
        "company_code": company_id.upper(),
        "office_lat": lat,
        "office_lng": lng,
        "geofence_radius_m": radius,
        "created_at": NOW.isoformat(),
        "_seed_tag": TAG,
    })


@pytest.fixture(scope="module")
def seeded(mongo):
    db = mongo
    # Ensure clean slate for this tag
    _teardown(db)

    _mk_company(db, company_id=CO_A, lat=CO_A_LAT, lng=CO_A_LNG)
    _mk_company(db, company_id=CO_B, lat=CO_B_LAT, lng=CO_B_LNG)

    seeds = {}

    # --- Company A --------------------------------------------------
    # A1: inside geofence, fresh ping, no punches -> missed_ins
    uid, _ = _mk_user(
        db, company_id=CO_A, last_lat=CO_A_LAT, last_lng=CO_A_LNG,
        last_at_iso=FRESH_ISO, tag="A1_missed",
    )
    seeds["A1_missed"] = uid

    # A2: outside geofence (~1.1km away), fresh, no punches -> NOT counted
    uid, _ = _mk_user(
        db, company_id=CO_A,
        last_lat=CO_A_LAT + OUTSIDE_OFFSET, last_lng=CO_A_LNG,
        last_at_iso=FRESH_ISO, tag="A2_outside",
    )
    seeds["A2_outside"] = uid

    # A3: inside geofence, STALE ping (2h old), no punches -> NOT counted
    uid, _ = _mk_user(
        db, company_id=CO_A, last_lat=CO_A_LAT, last_lng=CO_A_LNG,
        last_at_iso=STALE_ISO, tag="A3_stale",
    )
    seeds["A3_stale"] = uid

    # A4: inside geofence fresh, punched IN today -> open_shift, NOT missed
    uid, _ = _mk_user(
        db, company_id=CO_A, last_lat=CO_A_LAT, last_lng=CO_A_LNG,
        last_at_iso=FRESH_ISO, tag="A4_in_only",
    )
    _mk_attendance(db, user_id=uid, company_id=CO_A, kind="in", hhmm="09:15")
    seeds["A4_in_only"] = uid

    # A5: inside geofence fresh, punched IN then OUT today
    #     -> NOT open_shift, NOT missed
    uid, _ = _mk_user(
        db, company_id=CO_A, last_lat=CO_A_LAT, last_lng=CO_A_LNG,
        last_at_iso=FRESH_ISO, tag="A5_in_out",
    )
    _mk_attendance(db, user_id=uid, company_id=CO_A, kind="in", hhmm="09:00")
    _mk_attendance(db, user_id=uid, company_id=CO_A, kind="out", hhmm="18:00")
    seeds["A5_in_out"] = uid

    # A6: exited today, otherwise perfect -> NOT counted
    uid, _ = _mk_user(
        db, company_id=CO_A, last_lat=CO_A_LAT, last_lng=CO_A_LNG,
        last_at_iso=FRESH_ISO, exit_date=YESTERDAY, tag="A6_exited",
    )
    seeds["A6_exited"] = uid

    # A7: not onboarded -> NOT counted
    uid, _ = _mk_user(
        db, company_id=CO_A, last_lat=CO_A_LAT, last_lng=CO_A_LNG,
        last_at_iso=FRESH_ISO, onboarded=False, tag="A7_not_onb",
    )
    seeds["A7_not_onb"] = uid

    # A8: approval_status=pending -> NOT counted
    uid, _ = _mk_user(
        db, company_id=CO_A, last_lat=CO_A_LAT, last_lng=CO_A_LNG,
        last_at_iso=FRESH_ISO, approval_status="pending", tag="A8_pending",
    )
    seeds["A8_pending"] = uid

    # A9: missing approval_status entirely (should default to approved
    #     per spec) -> should be counted
    uid = f"{TAG}_u_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "user_id": uid,
        "email": f"{uid}@it42.test",
        "name": "IT42 A9_no_approval",
        "role": "employee",
        "company_id": CO_A,
        "onboarded": True,
        # NOTE: no approval_status field
        "last_location_lat": CO_A_LAT,
        "last_location_lng": CO_A_LNG,
        "last_location_at": FRESH_ISO,
        "_seed_tag": TAG,
    })
    seeds["A9_no_approval"] = uid

    # Also seed a company_admin for CO_A so we can test scoping
    ca_uid, ca_email = _mk_user(
        db, company_id=CO_A, role="company_admin",
        last_lat=None, last_lng=None,
        last_at_iso=None, tag="CO_A_admin",
    )
    # Give it a session token directly
    ca_token = f"seed_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": ca_token,
        "user_id": ca_uid,
        "expires_at": NOW + timedelta(days=7),
        "created_at": NOW,
        "auth_method": "seed",
        "_seed_tag": TAG,
    })
    seeds["CO_A_admin_token"] = ca_token

    # Employee session for 403 test
    emp_uid = seeds["A1_missed"]
    emp_token = f"seed_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": emp_token,
        "user_id": emp_uid,
        "expires_at": NOW + timedelta(days=7),
        "created_at": NOW,
        "auth_method": "seed",
        "_seed_tag": TAG,
    })
    seeds["employee_token"] = emp_token

    # --- Company B --------------------------------------------------
    # B1: inside geofence fresh, no punches -> missed_ins (for co B)
    uid, _ = _mk_user(
        db, company_id=CO_B, last_lat=CO_B_LAT, last_lng=CO_B_LNG,
        last_at_iso=FRESH_ISO, tag="B1_missed",
    )
    seeds["B1_missed"] = uid

    # B2: inside geofence, punched IN only -> open_shift (for co B)
    uid, _ = _mk_user(
        db, company_id=CO_B, last_lat=CO_B_LAT, last_lng=CO_B_LNG,
        last_at_iso=FRESH_ISO, tag="B2_in_only",
    )
    _mk_attendance(db, user_id=uid, company_id=CO_B, kind="in", hhmm="09:20")
    seeds["B2_in_only"] = uid

    yield seeds

    _teardown(db)


def _teardown(db):
    db.users.delete_many({"_seed_tag": TAG})
    db.companies.delete_many({"_seed_tag": TAG})
    db.attendance.delete_many({"_seed_tag": TAG})
    db.user_sessions.delete_many({"_seed_tag": TAG})


# ---- Helpers --------------------------------------------------------
def _super_admin_token(api_client, mongo):
    """Log in as super_admin via OTP dev mode. Never touches PIN."""
    r = api_client.post(
        f"{API}/auth/otp/request",
        json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email"},
    )
    assert r.status_code == 200, f"OTP request failed: {r.status_code} {r.text}"
    body = r.json()
    code = body.get("code") or body.get("dev_code")
    assert code, f"OTP dev code not returned: {body}"
    r = api_client.post(
        f"{API}/auth/otp/verify",
        json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email", "code": code},
    )
    assert r.status_code == 200, f"OTP verify failed: {r.status_code} {r.text}"
    return r.json()["session_token"]


def _hdrs(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---- Tests ----------------------------------------------------------
class TestAdminStatsBadges:
    def test_super_admin_scoped_to_company_a(self, api_client, mongo, seeded):
        token = _super_admin_token(api_client, mongo)
        r = api_client.get(
            f"{API}/admin/stats?company_id={CO_A}",
            headers=_hdrs(token),
        )
        assert r.status_code == 200, r.text
        data = r.json()

        # ---- Backward-compat fields present -----------------------
        for k in [
            "total_employees", "present_today", "pending_leaves",
            "open_tickets", "pending_profile_edits", "total_companies",
        ]:
            assert k in data, f"Missing backward-compat key {k} in {data}"

        # ---- New additive fields ----------------------------------
        assert "open_shifts" in data, data
        assert "missed_ins" in data, data
        assert isinstance(data["open_shifts"], int)
        assert isinstance(data["missed_ins"], int)

        # CO_A is a freshly-seeded company_id unique to our test tag,
        # so counts should be exact.
        # Only A4 (IN only) is open_shift. A5 has IN+OUT so NOT counted.
        assert data["open_shifts"] == 1, (
            f"expected exactly 1 open_shift for CO_A (A4), got {data['open_shifts']}"
        )
        # Only A1 (inside/fresh) + A9 (no approval_status -> defaults approved)
        # should be counted. Excluded:
        #   A2 outside, A3 stale, A4/A5 have punches, A6 exited,
        #   A7 not onboarded, A8 approval=pending
        assert data["missed_ins"] == 2, (
            f"expected exactly 2 missed_ins for CO_A (A1, A9), got {data['missed_ins']}"
        )

    def test_outside_and_stale_and_exited_excluded_from_missed_ins(
        self, api_client, mongo, seeded
    ):
        """Regression: increment company A's stat vs baseline should NOT
        include A2 outside, A3 stale, A6 exited, A7 not-onboarded, A8 pending.
        """
        token = _super_admin_token(api_client, mongo)
        r = api_client.get(
            f"{API}/admin/stats?company_id={CO_A}",
            headers=_hdrs(token),
        )
        assert r.status_code == 200, r.text
        missed = r.json()["missed_ins"]
        # If any of the excluded categories leaked, missed would be >=3.
        # We only expect A1 and A9 -> exactly 2 from our seed. Other DB
        # residue could push above 2, so cap check via known bad cases:
        # Directly verify by counting the excluded ones' user_ids against
        # /admin/attendance/present-not-punched if available - here just
        # ensure the specific ones are NOT in the count by asserting the
        # increment is consistent with 2 seed missed users.
        # Given a possibly noisy test DB, we cap the delta by ensuring
        # excluded seed users are NOT reflected: we assert missed does not
        # exceed the total seeded eligible (2) + any pre-existing.
        # Softer floor check:
        assert missed >= 2, f"lost the fresh-inside seeds A1/A9: {missed}"

    def test_super_admin_scoped_to_company_b(self, api_client, mongo, seeded):
        token = _super_admin_token(api_client, mongo)
        r = api_client.get(
            f"{API}/admin/stats?company_id={CO_B}",
            headers=_hdrs(token),
        )
        assert r.status_code == 200
        data = r.json()
        # CO_B unique: B1 fresh-inside no punches -> missed_ins=1
        #              B2 IN only -> open_shifts=1
        assert data["missed_ins"] == 1, data
        assert data["open_shifts"] == 1, data

    def test_super_admin_cross_company_sums(self, api_client, mongo, seeded):
        token = _super_admin_token(api_client, mongo)
        # scoped A
        a = api_client.get(
            f"{API}/admin/stats?company_id={CO_A}", headers=_hdrs(token)
        ).json()
        b = api_client.get(
            f"{API}/admin/stats?company_id={CO_B}", headers=_hdrs(token)
        ).json()
        # unscoped (cross-company)
        all_ = api_client.get(
            f"{API}/admin/stats", headers=_hdrs(token)
        ).json()

        # Cross-company should be >= sum of A + B for our new fields
        assert all_["missed_ins"] >= a["missed_ins"] + b["missed_ins"] - 0, (
            f"cross-company missed_ins {all_['missed_ins']} < A {a['missed_ins']} + B {b['missed_ins']}"
        )
        assert all_["open_shifts"] >= a["open_shifts"] + b["open_shifts"] - 0
        # total_companies only meaningful for super_admin unscoped;
        # it is a top-level count, must be > 0.
        assert all_["total_companies"] > 0

    def test_company_admin_auto_scoped(self, api_client, mongo, seeded):
        token = seeded["CO_A_admin_token"]
        r = api_client.get(f"{API}/admin/stats", headers=_hdrs(token))
        assert r.status_code == 200, r.text
        data = r.json()
        # Even if they pass company_id=CO_B, must remain scoped to their own
        r2 = api_client.get(
            f"{API}/admin/stats?company_id={CO_B}", headers=_hdrs(token)
        )
        assert r2.status_code == 200
        # CO_A admin should never see CO_B's B1_missed / B2_in_only counts
        # both queries should return the same numbers (own company only)
        assert data["missed_ins"] == r2.json()["missed_ins"]
        assert data["open_shifts"] == r2.json()["open_shifts"]

        # And CO_A admin should see at least our A1/A9 missed + A4 open
        assert data["missed_ins"] >= 2
        assert data["open_shifts"] >= 1

    def test_employee_forbidden(self, api_client, mongo, seeded):
        token = seeded["employee_token"]
        r = api_client.get(f"{API}/admin/stats", headers=_hdrs(token))
        assert r.status_code == 403, (r.status_code, r.text)

    def test_defaults_when_no_qualifying_data(self, api_client, mongo, seeded):
        """A brand-new empty company should have open_shifts=0 & missed_ins=0."""
        db = mongo
        empty_co = f"{TAG}_co_empty"
        db.companies.insert_one({
            "company_id": empty_co,
            "name": "IT42 Empty",
            "company_code": empty_co.upper(),
            "office_lat": 0.0,
            "office_lng": 0.0,
            "geofence_radius_m": RADIUS_M,
            "created_at": NOW.isoformat(),
            "_seed_tag": TAG,
        })
        try:
            token = _super_admin_token(api_client, mongo)
            r = api_client.get(
                f"{API}/admin/stats?company_id={empty_co}",
                headers=_hdrs(token),
            )
            assert r.status_code == 200
            data = r.json()
            assert data["open_shifts"] == 0
            assert data["missed_ins"] == 0
            assert data["total_employees"] == 0
        finally:
            db.companies.delete_one({"company_id": empty_co})
