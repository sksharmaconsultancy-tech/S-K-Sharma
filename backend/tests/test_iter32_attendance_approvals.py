"""Iteration 32 backend tests — admin-pin-login clarity, location-ping,
present-not-punched, approve-punch.

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
CREATED_REQUEST_IDS: list[str] = []
CREATED_SESSION_TOKENS: list[str] = []
CREATED_ATTENDANCE_IDS: list[str] = []


@pytest.fixture(scope="session")
def mongo():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    # Teardown — remove everything we created
    if CREATED_ATTENDANCE_IDS:
        db.attendance.delete_many({"record_id": {"$in": CREATED_ATTENDANCE_IDS}})
    # Any attendance for our test users too (belt-and-braces)
    if CREATED_USER_IDS:
        db.attendance.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
        db.user_sessions.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
        db.users.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
    if CREATED_COMPANY_IDS:
        db.companies.delete_many({"company_id": {"$in": CREATED_COMPANY_IDS}})
    if CREATED_REQUEST_IDS:
        db.company_requests.delete_many({"request_id": {"$in": CREATED_REQUEST_IDS}})
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
def _seed_company(mongo, lat=28.6139, lng=77.209, radius=200):
    company_id = f"co_it32_{uuid.uuid4().hex[:8]}"
    doc = {
        "company_id": company_id,
        "name": f"IT32 Test Co {RUN_HEX}",
        "address": "Test Address",
        "city": "Delhi",
        "state": "DL",
        "office_lat": lat,
        "office_lng": lng,
        "geofence_radius_m": radius,
        "company_code": f"IT{uuid.uuid4().hex[:6].upper()}",
        "compliance_enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo.companies.insert_one(doc)
    CREATED_COMPANY_IDS.append(company_id)
    return doc


def _seed_user(mongo, role, company_id, *, phone=None, email=None, code=None):
    user_id = f"user_it32_{uuid.uuid4().hex[:10]}"
    phone = phone or f"+91999{uuid.uuid4().int % 10000000:07d}"
    email = email or f"it32_{uuid.uuid4().hex[:8]}@test.local"
    doc = {
        "user_id": user_id,
        "email": email,
        "phone": phone,
        "name": f"IT32 {role} {RUN_HEX}",
        "role": role,
        "company_id": company_id,
        "employee_code": code or f"IT32{RUN_HEX[:2]}0001",
        "onboarded": True,
        "approval_status": "approved",
        "has_pin": False,
        "pin_must_change": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo.users.insert_one(doc)
    CREATED_USER_IDS.append(user_id)
    return doc


def _seed_session(mongo, user_id):
    token = f"tk_it32_{uuid.uuid4().hex}"
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


# ==================================================================
# 1) Admin-pin-login clarity for pending / rejected / approved
# ==================================================================
class TestAdminPinLoginClarity:
    """Login-clarity for pending/rejected company registrations."""

    def test_pending_returns_403_with_company_name(self, sess, mongo):
        pin = "753186"
        phone = f"+91999{uuid.uuid4().int % 10000000:07d}"
        email = f"it32pending_{uuid.uuid4().hex[:6]}@test.local"
        cname = f"IT32 Pending Ltd {RUN_HEX}"

        r = sess.post(f"{API}/auth/company-register", json={
            "company_name": cname,
            "address": "1 Test Rd", "city": "Delhi", "state": "DL",
            "contact_name": "Pending Admin", "contact_mobile": phone,
            "contact_email": email, "nature_of_business": "IT",
            "pin": pin,
        })
        assert r.status_code == 200, r.text
        req_id = r.json()["request_id"]
        CREATED_REQUEST_IDS.append(req_id)

        # Attempt admin-pin-login — should be 403 with "awaiting approval"
        r2 = sess.post(f"{API}/auth/admin-pin-login", json={
            "identifier": email, "pin": pin,
        })
        assert r2.status_code == 403, f"expected 403, got {r2.status_code}: {r2.text}"
        detail = (r2.json().get("detail") or "").lower()
        assert "awaiting approval" in detail, detail
        assert cname.lower() in detail, detail

        # Retry via phone identifier — same 403
        r3 = sess.post(f"{API}/auth/admin-pin-login", json={
            "identifier": phone, "pin": pin,
        })
        assert r3.status_code == 403, r3.text
        assert "awaiting approval" in (r3.json().get("detail") or "").lower()

        # Store for the rejected-flow test
        pytest.iter32_pending = {
            "pin": pin, "phone": phone, "email": email,
            "cname": cname, "req_id": req_id,
        }

    def test_rejected_returns_403_with_reason(self, sess, mongo):
        state = pytest.iter32_pending
        # Reject the request as super_admin.
        # Grab a super_admin session by seeding one (do NOT touch the real one).
        sa = mongo.users.find_one({"role": "super_admin"}, {"_id": 0, "user_id": 1})
        assert sa, "no super_admin in DB"
        sa_token = _seed_session(mongo, sa["user_id"])

        r = sess.patch(
            f"{API}/company-requests/{state['req_id']}",
            headers=_auth(sa_token),
            json={"status": "rejected", "admin_note": "Duplicate applicant"},
        )
        assert r.status_code == 200, r.text

        # Retry login → 403 rejected + reason
        r2 = sess.post(f"{API}/auth/admin-pin-login", json={
            "identifier": state["email"], "pin": state["pin"],
        })
        assert r2.status_code == 403, r2.text
        detail = (r2.json().get("detail") or "").lower()
        assert "rejected" in detail, detail
        assert "duplicate applicant" in detail, detail

    def test_approved_returns_session_token(self, sess, mongo):
        pin = "852741"
        phone = f"+91999{uuid.uuid4().int % 10000000:07d}"
        email = f"it32approve_{uuid.uuid4().hex[:6]}@test.local"
        cname = f"IT32 Approve Co {RUN_HEX}"

        r = sess.post(f"{API}/auth/company-register", json={
            "company_name": cname,
            "address": "2 Test Rd", "city": "Delhi", "state": "DL",
            "contact_name": "Approve Admin", "contact_mobile": phone,
            "contact_email": email, "nature_of_business": "IT",
            "pin": pin,
        })
        assert r.status_code == 200, r.text
        req_id = r.json()["request_id"]
        CREATED_REQUEST_IDS.append(req_id)

        sa = mongo.users.find_one({"role": "super_admin"}, {"_id": 0, "user_id": 1})
        sa_token = _seed_session(mongo, sa["user_id"])
        r2 = sess.patch(
            f"{API}/company-requests/{req_id}",
            headers=_auth(sa_token),
            json={"status": "approved"},
        )
        assert r2.status_code == 200, r2.text
        body = r2.json()
        # Track the provisioned user + company for cleanup
        if body.get("admin_user_id"):
            CREATED_USER_IDS.append(body["admin_user_id"])
        if body.get("company_id"):
            CREATED_COMPANY_IDS.append(body["company_id"])

        # Now login → 200 + session_token
        r3 = sess.post(f"{API}/auth/admin-pin-login", json={
            "identifier": email, "pin": pin,
        })
        assert r3.status_code == 200, r3.text
        rb = r3.json()
        assert "session_token" in rb, rb
        assert rb.get("user", {}).get("role") == "company_admin"


# ==================================================================
# 2) POST /me/location-ping
# ==================================================================
class TestLocationPing:
    def test_ping_persists_on_user(self, sess, mongo):
        comp = _seed_company(mongo, lat=28.6139, lng=77.2090)
        emp = _seed_user(mongo, "employee", comp["company_id"])
        tok = _seed_session(mongo, emp["user_id"])

        r = sess.post(f"{API}/me/location-ping",
                      headers=_auth(tok),
                      json={"latitude": 28.6139, "longitude": 77.2090})
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

        fresh = mongo.users.find_one({"user_id": emp["user_id"]}, {"_id": 0})
        assert fresh["last_location_lat"] == 28.6139
        assert fresh["last_location_lng"] == 77.2090
        assert fresh.get("last_location_at")


# ==================================================================
# 3) GET /admin/attendance/present-not-punched
# ==================================================================
class TestPresentNotPunched:
    def _mk_scenario(self, mongo):
        comp = _seed_company(mongo, lat=28.6139, lng=77.2090, radius=200)
        admin = _seed_user(mongo, "company_admin", comp["company_id"])
        admin_tok = _seed_session(mongo, admin["user_id"])
        emp = _seed_user(mongo, "employee", comp["company_id"])
        return comp, admin, admin_tok, emp

    def _set_location(self, mongo, user_id, lat, lng, minutes_ago=0):
        at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
        mongo.users.update_one({"user_id": user_id},
                               {"$set": {"last_location_lat": lat,
                                         "last_location_lng": lng,
                                         "last_location_at": at}})

    def test_inside_geofence_not_punched(self, sess, mongo):
        comp, admin, admin_tok, emp = self._mk_scenario(mongo)
        self._set_location(mongo, emp["user_id"], comp["office_lat"], comp["office_lng"])

        r = sess.get(f"{API}/admin/attendance/present-not-punched",
                     headers=_auth(admin_tok))
        assert r.status_code == 200, r.text
        body = r.json()
        ids = [x["user_id"] for x in body["not_punched_in"]]
        assert emp["user_id"] in ids, body

    def test_outside_geofence_hidden(self, sess, mongo):
        comp, admin, admin_tok, emp = self._mk_scenario(mongo)
        # 10 km away
        self._set_location(mongo, emp["user_id"], comp["office_lat"] + 0.1, comp["office_lng"] + 0.1)
        r = sess.get(f"{API}/admin/attendance/present-not-punched",
                     headers=_auth(admin_tok))
        assert r.status_code == 200
        body = r.json()
        ids = [x["user_id"] for x in body["not_punched_in"] + body["not_punched_out"]]
        assert emp["user_id"] not in ids

    def test_stale_ping_hidden(self, sess, mongo):
        comp, admin, admin_tok, emp = self._mk_scenario(mongo)
        self._set_location(mongo, emp["user_id"], comp["office_lat"], comp["office_lng"], minutes_ago=90)
        r = sess.get(f"{API}/admin/attendance/present-not-punched",
                     headers=_auth(admin_tok))
        assert r.status_code == 200
        body = r.json()
        ids = [x["user_id"] for x in body["not_punched_in"] + body["not_punched_out"]]
        assert emp["user_id"] not in ids

    def test_transitions_in_and_out(self, sess, mongo):
        comp, admin, admin_tok, emp = self._mk_scenario(mongo)
        emp_tok = _seed_session(mongo, emp["user_id"])
        self._set_location(mongo, emp["user_id"], comp["office_lat"], comp["office_lng"])

        # not_punched_in
        r = sess.get(f"{API}/admin/attendance/present-not-punched",
                     headers=_auth(admin_tok))
        body = r.json()
        assert emp["user_id"] in [x["user_id"] for x in body["not_punched_in"]]

        # Punch in via employee
        rp = sess.post(f"{API}/attendance/punch", headers=_auth(emp_tok), json={
            "kind": "in", "latitude": comp["office_lat"], "longitude": comp["office_lng"],
            "biometric_method": "fingerprint",
        })
        assert rp.status_code == 200, rp.text

        r2 = sess.get(f"{API}/admin/attendance/present-not-punched",
                      headers=_auth(admin_tok))
        b2 = r2.json()
        assert emp["user_id"] not in [x["user_id"] for x in b2["not_punched_in"]]
        assert emp["user_id"] in [x["user_id"] for x in b2["not_punched_out"]]

        # Punch out
        rp2 = sess.post(f"{API}/attendance/punch", headers=_auth(emp_tok), json={
            "kind": "out", "latitude": comp["office_lat"], "longitude": comp["office_lng"],
            "biometric_method": "fingerprint",
        })
        assert rp2.status_code == 200, rp2.text

        r3 = sess.get(f"{API}/admin/attendance/present-not-punched",
                      headers=_auth(admin_tok))
        b3 = r3.json()
        ids = [x["user_id"] for x in b3["not_punched_in"] + b3["not_punched_out"]]
        assert emp["user_id"] not in ids

    def test_super_admin_company_id_scoping(self, sess, mongo):
        comp_a = _seed_company(mongo)
        comp_b = _seed_company(mongo)
        emp_a = _seed_user(mongo, "employee", comp_a["company_id"])
        emp_b = _seed_user(mongo, "employee", comp_b["company_id"])
        # In-geofence for both
        self._set_location(mongo, emp_a["user_id"], comp_a["office_lat"], comp_a["office_lng"])
        self._set_location(mongo, emp_b["user_id"], comp_b["office_lat"], comp_b["office_lng"])
        sa = mongo.users.find_one({"role": "super_admin"}, {"_id": 0, "user_id": 1})
        sa_tok = _seed_session(mongo, sa["user_id"])

        r = sess.get(f"{API}/admin/attendance/present-not-punched",
                     headers=_auth(sa_tok),
                     params={"company_id": comp_a["company_id"]})
        assert r.status_code == 200
        ids = [x["user_id"] for x in r.json()["not_punched_in"]]
        assert emp_a["user_id"] in ids
        assert emp_b["user_id"] not in ids

    def test_max_age_bounds(self, sess, mongo):
        sa = mongo.users.find_one({"role": "super_admin"}, {"_id": 0, "user_id": 1})
        sa_tok = _seed_session(mongo, sa["user_id"])
        # invalid — 0
        r = sess.get(f"{API}/admin/attendance/present-not-punched",
                     headers=_auth(sa_tok), params={"max_age_minutes": 0})
        assert r.status_code == 422
        # invalid — 2000
        r = sess.get(f"{API}/admin/attendance/present-not-punched",
                     headers=_auth(sa_tok), params={"max_age_minutes": 2000})
        assert r.status_code == 422
        # valid
        r = sess.get(f"{API}/admin/attendance/present-not-punched",
                     headers=_auth(sa_tok), params={"max_age_minutes": 30})
        assert r.status_code == 200


# ==================================================================
# 4) POST /admin/attendance/approve-punch
# ==================================================================
class TestAdminApprovePunch:
    def _mk(self, mongo, *, inside=True):
        comp = _seed_company(mongo, lat=28.6139, lng=77.2090, radius=200)
        admin = _seed_user(mongo, "company_admin", comp["company_id"])
        admin_tok = _seed_session(mongo, admin["user_id"])
        emp = _seed_user(mongo, "employee", comp["company_id"])
        if inside:
            mongo.users.update_one({"user_id": emp["user_id"]},
                                   {"$set": {
                                       "last_location_lat": comp["office_lat"],
                                       "last_location_lng": comp["office_lng"],
                                       "last_location_at": datetime.now(timezone.utc).isoformat(),
                                   }})
        return comp, admin, admin_tok, emp

    def test_approve_in_inside_geofence(self, sess, mongo):
        comp, admin, admin_tok, emp = self._mk(mongo)
        r = sess.post(f"{API}/admin/attendance/approve-punch",
                      headers=_auth(admin_tok),
                      json={"user_id": emp["user_id"], "kind": "in", "note": "geofence auto"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        rec_id = body.get("record_id")
        CREATED_ATTENDANCE_IDS.append(rec_id)

        att = mongo.attendance.find_one({"record_id": rec_id}, {"_id": 0})
        assert att["source"] == "admin_approved"
        assert att["approved_by_user_id"] == admin["user_id"]
        assert att["approved_by_name"] in (admin["name"], admin.get("email"))

    def test_double_in_400(self, sess, mongo):
        comp, admin, admin_tok, emp = self._mk(mongo)
        r1 = sess.post(f"{API}/admin/attendance/approve-punch",
                       headers=_auth(admin_tok),
                       json={"user_id": emp["user_id"], "kind": "in"})
        assert r1.status_code == 200
        CREATED_ATTENDANCE_IDS.append(r1.json()["record_id"])
        r2 = sess.post(f"{API}/admin/attendance/approve-punch",
                       headers=_auth(admin_tok),
                       json={"user_id": emp["user_id"], "kind": "in"})
        assert r2.status_code == 400, r2.text
        assert "already" in (r2.json().get("detail") or "").lower()

    def test_out_without_in_400(self, sess, mongo):
        comp, admin, admin_tok, emp = self._mk(mongo)
        r = sess.post(f"{API}/admin/attendance/approve-punch",
                      headers=_auth(admin_tok),
                      json={"user_id": emp["user_id"], "kind": "out"})
        assert r.status_code == 400, r.text
        assert "not currently punched-in" in (r.json().get("detail") or "").lower()

    def test_approve_out_after_in(self, sess, mongo):
        comp, admin, admin_tok, emp = self._mk(mongo)
        r1 = sess.post(f"{API}/admin/attendance/approve-punch",
                       headers=_auth(admin_tok),
                       json={"user_id": emp["user_id"], "kind": "in"})
        assert r1.status_code == 200
        CREATED_ATTENDANCE_IDS.append(r1.json()["record_id"])
        r2 = sess.post(f"{API}/admin/attendance/approve-punch",
                       headers=_auth(admin_tok),
                       json={"user_id": emp["user_id"], "kind": "out"})
        assert r2.status_code == 200, r2.text
        CREATED_ATTENDANCE_IDS.append(r2.json()["record_id"])

    def test_cross_company_403(self, sess, mongo):
        comp_a = _seed_company(mongo)
        comp_b = _seed_company(mongo)
        admin_a = _seed_user(mongo, "company_admin", comp_a["company_id"])
        admin_a_tok = _seed_session(mongo, admin_a["user_id"])
        emp_b = _seed_user(mongo, "employee", comp_b["company_id"])
        mongo.users.update_one({"user_id": emp_b["user_id"]},
                               {"$set": {
                                   "last_location_lat": comp_b["office_lat"],
                                   "last_location_lng": comp_b["office_lng"],
                                   "last_location_at": datetime.now(timezone.utc).isoformat(),
                               }})
        r = sess.post(f"{API}/admin/attendance/approve-punch",
                      headers=_auth(admin_a_tok),
                      json={"user_id": emp_b["user_id"], "kind": "in"})
        assert r.status_code == 403, r.text

    def test_no_location_400(self, sess, mongo):
        comp, admin, admin_tok, emp = self._mk(mongo, inside=False)
        # emp has no last_location_lat/lng
        r = sess.post(f"{API}/admin/attendance/approve-punch",
                      headers=_auth(admin_tok),
                      json={"user_id": emp["user_id"], "kind": "in"})
        assert r.status_code == 400, r.text
        assert "location" in (r.json().get("detail") or "").lower()

    def test_outside_geofence_400_with_distance(self, sess, mongo):
        comp, admin, admin_tok, emp = self._mk(mongo, inside=False)
        # Set location 5 km away
        mongo.users.update_one({"user_id": emp["user_id"]},
                               {"$set": {
                                   "last_location_lat": comp["office_lat"] + 0.05,
                                   "last_location_lng": comp["office_lng"] + 0.05,
                                   "last_location_at": datetime.now(timezone.utc).isoformat(),
                               }})
        r = sess.post(f"{API}/admin/attendance/approve-punch",
                      headers=_auth(admin_tok),
                      json={"user_id": emp["user_id"], "kind": "in"})
        assert r.status_code == 400, r.text
        detail = (r.json().get("detail") or "").lower()
        assert "from office" in detail or "allowed" in detail


# ==================================================================
# 5) AttendancePunch.source enum still accepts all three values
# ==================================================================
class TestAttendancePunchSourceEnum:
    def test_all_three_sources_accepted(self, sess, mongo):
        comp = _seed_company(mongo)
        emp = _seed_user(mongo, "employee", comp["company_id"])
        tok = _seed_session(mongo, emp["user_id"])
        # manual (default via omit)
        r = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "in", "latitude": comp["office_lat"], "longitude": comp["office_lng"],
            "biometric_method": "fingerprint",
        })
        assert r.status_code == 200, r.text
        # geofence-auto: since already punched in, out is next
        r2 = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "out", "latitude": comp["office_lat"], "longitude": comp["office_lng"],
            "biometric_method": "fingerprint", "source": "geofence-auto",
        })
        assert r2.status_code == 200, r2.text
        # admin_approved via direct enum acceptance — the endpoint doesn't gate it,
        # but Pydantic model must accept the literal. We can validate by seeing the model
        # accepts the payload (invalid enum would 422). Use a new day-simulation? Since
        # we can't easily punch twice IN, just verify 422 is NOT the response for value.
        r3 = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "in", "latitude": comp["office_lat"], "longitude": comp["office_lng"],
            "biometric_method": "fingerprint", "source": "admin_approved",
        })
        # It'll be 400 (already punched in) not 422 — proving enum accepts admin_approved
        assert r3.status_code != 422, r3.text

        # And a bad value → 422
        r4 = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "in", "latitude": comp["office_lat"], "longitude": comp["office_lng"],
            "biometric_method": "fingerprint", "source": "bogus",
        })
        assert r4.status_code == 422, r4.text
