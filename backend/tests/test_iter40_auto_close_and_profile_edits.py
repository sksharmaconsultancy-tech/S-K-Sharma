"""Iteration 40 backend tests.

Two features under test:

(A) Missed-punch auto-close:
    - GET  /api/admin/attendance/open-shifts
    - POST /api/admin/attendance/auto-close
    - Env: AUTO_CLOSE_MAX_HOURS (default 12), AUTO_CLOSE_STALE_MINUTES (default 30)

(B) Profile-edit visibility for both admin roles:
    - GET  /api/admin/stats → returns pending_profile_edits (int).
    - GET  /api/admin/profile-edits → super_admin no-filter returns cross-company.

All seed data is prefixed IT40_ so teardown is trivial. The real
super_admin (sksharmaconsultancy@gmail.com) is NOT modified: we mint a
throwaway super_admin instead so pin_hash etc. remain untouched.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

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

RUN = uuid.uuid4().hex[:6].upper()

CREATED_USER_IDS: list[str] = []
CREATED_COMPANY_IDS: list[str] = []
CREATED_SESSION_TOKENS: list[str] = []
CREATED_ATTENDANCE_IDS: list[str] = []
CREATED_PROFILE_EDIT_IDS: list[str] = []


# --------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------
@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]

    # Snapshot the real super_admin PIN fields BEFORE we run so we can
    # verify at teardown that none of them changed. We do NOT modify these.
    real = db.users.find_one(
        {"email": "sksharmaconsultancy@gmail.com"},
        {"_id": 0, "pin_hash": 1, "pin_must_change": 1,
         "pin_fail_count": 1, "pin_locked_until": 1},
    )
    snapshot = dict(real) if real else None

    yield db

    # Teardown
    if CREATED_ATTENDANCE_IDS:
        db.attendance.delete_many({"record_id": {"$in": CREATED_ATTENDANCE_IDS}})
    if CREATED_USER_IDS:
        db.attendance.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
        db.profile_edit_requests.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
        db.user_sessions.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
        db.users.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
    if CREATED_PROFILE_EDIT_IDS:
        db.profile_edit_requests.delete_many(
            {"request_id": {"$in": CREATED_PROFILE_EDIT_IDS}}
        )
    if CREATED_COMPANY_IDS:
        db.companies.delete_many({"company_id": {"$in": CREATED_COMPANY_IDS}})
    if CREATED_SESSION_TOKENS:
        db.user_sessions.delete_many({"session_token": {"$in": CREATED_SESSION_TOKENS}})

    # Verify real super_admin PIN fields are unchanged.
    if snapshot is not None:
        post = db.users.find_one(
            {"email": "sksharmaconsultancy@gmail.com"},
            {"_id": 0, "pin_hash": 1, "pin_must_change": 1,
             "pin_fail_count": 1, "pin_locked_until": 1},
        )
        assert post == snapshot, (
            "FATAL: super_admin PIN fields changed during test run! "
            f"before={snapshot} after={post}"
        )

    client.close()


@pytest.fixture(scope="module")
def sess():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# --------------------------------------------------------------------
# Seed helpers
# --------------------------------------------------------------------
def _seed_company(mongo, tag: str, office_lat=13.0, office_lng=77.6, radius=200):
    cid = f"co_it40_{uuid.uuid4().hex[:8]}"
    doc = {
        "company_id": cid,
        "name": f"IT40 {tag} {RUN}",
        "address": "Test Address",
        "city": "Bengaluru",
        "state": "KA",
        "office_lat": office_lat,
        "office_lng": office_lng,
        "geofence_radius_m": radius,
        "company_code": f"IT40{uuid.uuid4().hex[:4].upper()}",
        "compliance_enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo.companies.insert_one(doc)
    CREATED_COMPANY_IDS.append(cid)
    return doc


def _seed_user(
    mongo,
    role: str,
    company_id: Optional[str],
    *,
    last_location_lat: Optional[float] = None,
    last_location_lng: Optional[float] = None,
    last_location_at: Optional[str] = None,
    tag: str = "",
):
    uid = f"user_it40_{uuid.uuid4().hex[:10]}"
    doc = {
        "user_id": uid,
        "email": f"it40_{uuid.uuid4().hex[:8]}@test.local",
        "phone": None,
        "name": f"IT40 {role} {tag} {RUN}",
        "role": role,
        "company_id": company_id,
        "employee_code": f"IT40{uuid.uuid4().hex[:3].upper()}",
        "onboarded": True,
        "approval_status": "approved",
        "has_pin": False,
        "pin_must_change": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if last_location_lat is not None:
        doc["last_location_lat"] = last_location_lat
    if last_location_lng is not None:
        doc["last_location_lng"] = last_location_lng
    if last_location_at is not None:
        doc["last_location_at"] = last_location_at
    mongo.users.insert_one(doc)
    CREATED_USER_IDS.append(uid)
    return doc


def _seed_session(mongo, user_id: str) -> str:
    token = f"tk_it40_{uuid.uuid4().hex}"
    mongo.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "auth_method": "test",
    })
    CREATED_SESSION_TOKENS.append(token)
    return token


def _insert_att(mongo, user_id, company_id, kind, at_dt, *, source="manual",
                date_override: Optional[str] = None):
    """`date` defaults to today's UTC date (matches auto-close/open-shifts
    filter) so seeded 13h-ago punches remain scan-eligible even across
    the UTC midnight boundary."""
    rec_id = f"att_it40_{uuid.uuid4().hex[:12]}"
    date_str = date_override or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    doc = {
        "record_id": rec_id,
        "user_id": user_id,
        "company_id": company_id,
        "date": date_str,
        "kind": kind,
        "at": at_dt.isoformat().replace("+00:00", "Z"),
        "latitude": 13.0,
        "longitude": 77.6,
        "distance_m": 0.0,
        "source": source,
        "outside_geofence": False,
    }
    mongo.attendance.insert_one(doc)
    CREATED_ATTENDANCE_IDS.append(rec_id)
    return doc


def _seed_profile_edit(mongo, user_id: str, company_id: str, status="pending"):
    req_id = f"pe_it40_{uuid.uuid4().hex[:12]}"
    mongo.profile_edit_requests.insert_one({
        "request_id": req_id,
        "user_id": user_id,
        "company_id": company_id,
        "status": status,
        "changes": {"designation": f"IT40 Designation {RUN}"},
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    })
    CREATED_PROFILE_EDIT_IDS.append(req_id)
    return req_id


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


# --------------------------------------------------------------------
# Module-scoped scenario builder — shared by many tests.
# --------------------------------------------------------------------
@pytest.fixture(scope="module")
def scenario(mongo):
    """Build a fully populated multi-company scenario once and reuse."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")  # noqa: F841

    co1 = _seed_company(mongo, "CoOne")
    co2 = _seed_company(mongo, "CoTwo")

    # Throwaway super_admin (do NOT touch real one).
    su = _seed_user(mongo, "super_admin", None, tag="SU")
    su_tok = _seed_session(mongo, su["user_id"])

    # Company_admin per company.
    ca1 = _seed_user(mongo, "company_admin", co1["company_id"], tag="CA1")
    ca1_tok = _seed_session(mongo, ca1["user_id"])
    ca2 = _seed_user(mongo, "company_admin", co2["company_id"], tag="CA2")
    ca2_tok = _seed_session(mongo, ca2["user_id"])

    # Employees in co1 with different attendance shapes:
    # A: IN 13h ago (no OUT) → open shift, will_auto_close=True
    emp_a = _seed_user(mongo, "employee", co1["company_id"], tag="A")
    _insert_att(mongo, emp_a["user_id"], co1["company_id"], "in",
                now - timedelta(hours=13))

    # B: IN 5h ago (no OUT), no last_location → open shift, will NOT close
    emp_b = _seed_user(mongo, "employee", co1["company_id"], tag="B")
    _insert_att(mongo, emp_b["user_id"], co1["company_id"], "in",
                now - timedelta(hours=5))

    # C: IN then OUT (both today) → NOT an open shift
    emp_c = _seed_user(mongo, "employee", co1["company_id"], tag="C")
    _insert_att(mongo, emp_c["user_id"], co1["company_id"], "in",
                now - timedelta(hours=4))
    _insert_att(mongo, emp_c["user_id"], co1["company_id"], "out",
                now - timedelta(hours=1))

    # D: IN 3h ago, geofence-stale ping 45 min ago far from office (0,0)
    stale_at = (now - timedelta(minutes=45)).isoformat().replace("+00:00", "Z")
    emp_d = _seed_user(
        mongo, "employee", co1["company_id"], tag="D",
        last_location_lat=0.0, last_location_lng=0.0,
        last_location_at=stale_at,
    )
    _insert_att(mongo, emp_d["user_id"], co1["company_id"], "in",
                now - timedelta(hours=3))

    # E (co2): IN 13h ago — for cross-company checks
    emp_e = _seed_user(mongo, "employee", co2["company_id"], tag="E")
    _insert_att(mongo, emp_e["user_id"], co2["company_id"], "in",
                now - timedelta(hours=13))

    # Profile edit requests: 2 pending in co1, 2 pending in co2.
    pe1a = _seed_profile_edit(mongo, emp_a["user_id"], co1["company_id"])
    pe1b = _seed_profile_edit(mongo, emp_b["user_id"], co1["company_id"])
    pe2a = _seed_profile_edit(mongo, emp_e["user_id"], co2["company_id"])
    # One approved (should NOT count as pending).
    _seed_profile_edit(mongo, emp_c["user_id"], co1["company_id"], status="approved")

    return {
        "now": now,
        "co1": co1, "co2": co2,
        "su_tok": su_tok,
        "ca1_tok": ca1_tok, "ca2_tok": ca2_tok,
        "emp_a": emp_a, "emp_b": emp_b, "emp_c": emp_c,
        "emp_d": emp_d, "emp_e": emp_e,
        "emp_a_tok": _seed_session(mongo, emp_a["user_id"]),
        "pe1a": pe1a, "pe1b": pe1b, "pe2a": pe2a,
    }


# ====================================================================
# 1) GET /admin/attendance/open-shifts
# ====================================================================
class TestOpenShiftsList:
    def test_super_admin_sees_all_open_shifts(self, sess, scenario):
        r = sess.get(f"{API}/admin/attendance/open-shifts",
                     headers=_auth(scenario["su_tok"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "open_shifts" in body
        assert isinstance(body["open_shifts"], list)
        assert body.get("auto_close_after_hours") is not None
        # Our seeded open shifts: A, B, D (co1) + E (co2). C is closed → not present.
        uids = {s["user_id"] for s in body["open_shifts"]}
        assert scenario["emp_a"]["user_id"] in uids
        assert scenario["emp_b"]["user_id"] in uids
        assert scenario["emp_d"]["user_id"] in uids
        assert scenario["emp_e"]["user_id"] in uids
        assert scenario["emp_c"]["user_id"] not in uids

    def test_shape_required_fields_present(self, sess, scenario):
        r = sess.get(f"{API}/admin/attendance/open-shifts",
                     headers=_auth(scenario["su_tok"]))
        assert r.status_code == 200
        target = next(s for s in r.json()["open_shifts"]
                      if s["user_id"] == scenario["emp_a"]["user_id"])
        for key in ("user_id", "name", "employee_code", "company_name",
                    "last_in_at", "elapsed_hours", "punch_count",
                    "will_auto_close",
                    "last_location_lat", "last_location_lng",
                    "last_location_at"):
            assert key in target, f"Missing key: {key} in {target}"
        assert target["employee_code"] == scenario["emp_a"]["employee_code"]
        assert target["company_name"] == scenario["co1"]["name"]
        assert target["will_auto_close"] is True  # 13h > 12h
        assert target["elapsed_hours"] >= 12.0

    def test_company_admin_scoped_to_own_company(self, sess, scenario):
        r = sess.get(f"{API}/admin/attendance/open-shifts",
                     headers=_auth(scenario["ca1_tok"]))
        assert r.status_code == 200
        uids = {s["user_id"] for s in r.json()["open_shifts"]}
        assert scenario["emp_a"]["user_id"] in uids
        assert scenario["emp_e"]["user_id"] not in uids  # emp_e is co2

    def test_super_admin_can_filter_by_company_id(self, sess, scenario):
        r = sess.get(
            f"{API}/admin/attendance/open-shifts",
            params={"company_id": scenario["co2"]["company_id"]},
            headers=_auth(scenario["su_tok"]),
        )
        assert r.status_code == 200
        uids = {s["user_id"] for s in r.json()["open_shifts"]}
        assert scenario["emp_e"]["user_id"] in uids
        assert scenario["emp_a"]["user_id"] not in uids
        assert scenario["emp_b"]["user_id"] not in uids

    def test_closed_shifts_not_in_list(self, sess, scenario):
        # emp_c has IN+OUT today — must NOT appear anywhere
        r = sess.get(f"{API}/admin/attendance/open-shifts",
                     headers=_auth(scenario["su_tok"]))
        uids = {s["user_id"] for s in r.json()["open_shifts"]}
        assert scenario["emp_c"]["user_id"] not in uids

    def test_employee_role_gets_403(self, sess, scenario):
        r = sess.get(f"{API}/admin/attendance/open-shifts",
                     headers=_auth(scenario["emp_a_tok"]))
        assert r.status_code == 403


# ====================================================================
# 2) POST /admin/attendance/auto-close
# ====================================================================
class TestAutoClose:
    """These tests intentionally run AFTER TestOpenShiftsList so the
    open-shifts list assertions still see the un-closed state."""

    def test_employee_role_gets_403(self, sess, scenario):
        r = sess.post(f"{API}/admin/attendance/auto-close",
                      headers=_auth(scenario["emp_a_tok"]))
        assert r.status_code == 403

    def test_auto_close_closes_stale_and_geofence_shifts(
        self, sess, scenario, mongo
    ):
        r = sess.post(f"{API}/admin/attendance/auto-close",
                      headers=_auth(scenario["su_tok"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert "scanned" in body and "closed" in body and "records" in body
        assert body["closed"] >= 1

        closed_uids = {rec["user_id"] for rec in body["records"]}
        # Elapsed > 12h shifts (emp_a co1, emp_e co2) should close.
        assert scenario["emp_a"]["user_id"] in closed_uids
        assert scenario["emp_e"]["user_id"] in closed_uids
        # Geofence-stale (emp_d) should close.
        assert scenario["emp_d"]["user_id"] in closed_uids
        # emp_b: 5h elapsed, no location → must NOT close.
        assert scenario["emp_b"]["user_id"] not in closed_uids

        # Verify OUT records persisted with proper flags.
        out_a = mongo.attendance.find_one(
            {"user_id": scenario["emp_a"]["user_id"], "kind": "out"},
            {"_id": 0},
        )
        assert out_a is not None, "auto-close did not insert OUT for emp_a"
        assert out_a.get("source") == "server_auto_close"
        assert out_a.get("auto_closed") is True
        assert (out_a.get("outside_note") or "").startswith("auto-closed:")
        assert out_a.get("at")  # plausible timestamp exists

        out_d = mongo.attendance.find_one(
            {"user_id": scenario["emp_d"]["user_id"], "kind": "out"},
            {"_id": 0},
        )
        assert out_d is not None
        assert out_d.get("source") == "server_auto_close"
        assert (out_d.get("outside_note") or "").startswith("auto-closed:")

        # Track auto-close records for cleanup
        for uid_key in ("emp_a", "emp_d", "emp_e"):
            uid = scenario[uid_key]["user_id"]
            rec = mongo.attendance.find_one(
                {"user_id": uid, "source": "server_auto_close"},
                {"_id": 0, "record_id": 1},
            )
            if rec and rec.get("record_id"):
                CREATED_ATTENDANCE_IDS.append(rec["record_id"])

    def test_auto_close_is_idempotent(self, sess, scenario):
        r = sess.post(f"{API}/admin/attendance/auto-close",
                      headers=_auth(scenario["su_tok"]))
        assert r.status_code == 200
        body = r.json()
        # Second run should close nothing (all already closed or ineligible).
        assert body["closed"] == 0

    def test_shift_below_threshold_and_no_location_left_open(
        self, sess, scenario, mongo
    ):
        # emp_b had IN 5h ago and no location — must still be OPEN.
        rec = mongo.attendance.find_one(
            {"user_id": scenario["emp_b"]["user_id"], "kind": "out"},
            {"_id": 0},
        )
        assert rec is None, (
            "emp_b should still be open (elapsed < 12h and no location ping) "
            f"but found OUT rec: {rec}"
        )
        # And it should still show up in open-shifts.
        r = sess.get(f"{API}/admin/attendance/open-shifts",
                     headers=_auth(scenario["ca1_tok"]))
        assert r.status_code == 200
        uids = {s["user_id"] for s in r.json()["open_shifts"]}
        assert scenario["emp_b"]["user_id"] in uids


# ====================================================================
# 3) /admin/stats.pending_profile_edits
# ====================================================================
class TestAdminStatsPendingProfileEdits:
    def test_super_admin_no_filter_totals_cross_company(self, sess, scenario):
        r = sess.get(f"{API}/admin/stats", headers=_auth(scenario["su_tok"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "pending_profile_edits" in body
        assert isinstance(body["pending_profile_edits"], int)
        # 2 pending in co1 (pe1a, pe1b) + 1 pending in co2 (pe2a) = at least 3.
        assert body["pending_profile_edits"] >= 3

    def test_super_admin_with_company_id_scopes(self, sess, scenario):
        r = sess.get(
            f"{API}/admin/stats",
            params={"company_id": scenario["co1"]["company_id"]},
            headers=_auth(scenario["su_tok"]),
        )
        assert r.status_code == 200
        # Only co1 pending count → exactly the two we seeded for co1.
        assert r.json()["pending_profile_edits"] == 2

    def test_company_admin_scoped_to_own_company(self, sess, scenario):
        r = sess.get(f"{API}/admin/stats", headers=_auth(scenario["ca1_tok"]))
        assert r.status_code == 200
        assert r.json()["pending_profile_edits"] == 2

        r2 = sess.get(f"{API}/admin/stats", headers=_auth(scenario["ca2_tok"]))
        assert r2.status_code == 200
        assert r2.json()["pending_profile_edits"] == 1

    def test_employee_role_gets_403(self, sess, scenario):
        r = sess.get(f"{API}/admin/stats", headers=_auth(scenario["emp_a_tok"]))
        assert r.status_code == 403


# ====================================================================
# 4) /admin/profile-edits regression — super_admin cross-company
# ====================================================================
class TestProfileEditsList:
    def test_super_admin_no_filter_lists_all_companies(self, sess, scenario):
        r = sess.get(f"{API}/admin/profile-edits",
                     headers=_auth(scenario["su_tok"]))
        assert r.status_code == 200, r.text
        items = r.json().get("requests") or []
        ids = {i["request_id"] for i in items}
        # Both co1 and co2 pending requests must be present.
        assert scenario["pe1a"] in ids
        assert scenario["pe1b"] in ids
        assert scenario["pe2a"] in ids
        # Different company_ids should be represented
        cids = {i.get("company_id") for i in items
                if i["request_id"] in {scenario["pe1a"], scenario["pe2a"]}}
        assert scenario["co1"]["company_id"] in cids
        assert scenario["co2"]["company_id"] in cids

    def test_company_admin_only_sees_own_company(self, sess, scenario):
        r = sess.get(f"{API}/admin/profile-edits",
                     headers=_auth(scenario["ca1_tok"]))
        assert r.status_code == 200
        items = r.json().get("requests") or []
        ids = {i["request_id"] for i in items}
        assert scenario["pe1a"] in ids
        assert scenario["pe1b"] in ids
        assert scenario["pe2a"] not in ids
        # Sanity: no request from a different company leaked in.
        for it in items:
            assert it.get("company_id") == scenario["co1"]["company_id"]
