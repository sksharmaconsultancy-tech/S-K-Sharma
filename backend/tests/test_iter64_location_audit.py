"""Iter 64 backend tests — Location Tracking & Audit.

Under test:
  1. POST /api/attendance/punch — new behaviour:
     (a) firm.location_punching_enabled=False OR user.gps_punch_enabled=False
         → punch with selfie+biometric_method is allowed even without lat/lng.
         Record: source='manual-nogps', location_status='no-gps',
                 gps_verified=False.
     (b) both flags True →
         - inside-geofence → location_status='inside', status='approved'.
         - outside-geofence IN → allowed (no longer 400) with
           location_status='outside', status='pending', outside_note set.
         - outside-geofence OUT → same treatment (pending + note).
     (c) firm.reject_outside_geofence=True → outside IN → 400.

  2. GET /api/admin/attendance/location-audit — filters + response shape.
  3. GET /api/admin/attendance/location-audit.xlsx — bytes + headers.
  4. PATCH /api/companies/{cid} — accepts reject_outside_geofence.
  5. GET /api/attendance/today and /history return location_status.

Runs against the public preview URL. Uses direct MongoDB seeding for the
employee fixture (bypasses OTP/PIN) — same pattern as iter35/iter36. Real
super_admin uses OTP dev-code flow.

Cleanup: everything seeded is deleted at session teardown.
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

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"

RUN_HEX = uuid.uuid4().hex[:6].upper()

OFFICE_LAT = 13.0
OFFICE_LNG = 77.6
OFFICE_RADIUS = 200
INSIDE_LAT, INSIDE_LNG = 13.0, 77.6                 # 0m
OUTSIDE_LAT, OUTSIDE_LNG = 13.10, 77.6              # ~11km

CREATED_USER_IDS: list[str] = []
CREATED_COMPANY_IDS: list[str] = []
CREATED_ATTENDANCE_IDS: list[str] = []
CREATED_SESSION_TOKENS: list[str] = []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def mongo():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
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


def _otp_login(sess, identifier, channel="email"):
    r = sess.post(f"{API}/auth/otp/request",
                  json={"identifier": identifier, "channel": channel})
    assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    code = body.get("dev_code") or body.get("code")
    assert code, f"No dev code in response: {body}"
    r = sess.post(f"{API}/auth/otp/verify",
                  json={"identifier": identifier, "channel": channel, "code": code})
    assert r.status_code == 200, f"otp/verify failed: {r.status_code} {r.text[:200]}"
    return r.json().get("session_token") or r.json().get("token")


@pytest.fixture(scope="session")
def super_token(sess):
    return _otp_login(sess, SUPER_ADMIN_EMAIL, "email")


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Seed helpers (direct mongo — no PIN mutation of real accounts)
# ---------------------------------------------------------------------------
def _seed_company(mongo, *, location_punching_enabled=False,
                  reject_outside_geofence=False):
    company_id = f"co_it64_{uuid.uuid4().hex[:8]}"
    doc = {
        "company_id": company_id,
        "name": f"IT64 Test Co {RUN_HEX} {uuid.uuid4().hex[:3]}",
        "address": "Test Address",
        "city": "Bengaluru",
        "state": "KA",
        "office_lat": OFFICE_LAT,
        "office_lng": OFFICE_LNG,
        "geofence_radius_m": OFFICE_RADIUS,
        "company_code": f"IT64{uuid.uuid4().hex[:4].upper()}",
        "location_punching_enabled": bool(location_punching_enabled),
        "reject_outside_geofence": bool(reject_outside_geofence),
        "punch_approval_required": False,
        "auto_punch_enabled": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo.companies.insert_one(doc)
    CREATED_COMPANY_IDS.append(company_id)
    return doc


def _seed_user(mongo, company_id, *, gps_punch_enabled=False):
    user_id = f"user_it64_{uuid.uuid4().hex[:10]}"
    email = f"it64_{uuid.uuid4().hex[:8]}@test.local"
    phone = f"+91999{uuid.uuid4().int % 10000000:07d}"
    doc = {
        "user_id": user_id,
        "email": email,
        "phone": phone,
        "name": f"IT64 Emp {RUN_HEX}",
        "role": "employee",
        "company_id": company_id,
        "employee_code": f"IT64{uuid.uuid4().hex[:3].upper()}",
        "onboarded": True,
        "approval_status": "approved",
        "gps_punch_enabled": bool(gps_punch_enabled),
        "auto_punch_enabled": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo.users.insert_one(doc)
    CREATED_USER_IDS.append(user_id)
    return doc


def _seed_session(mongo, user_id):
    token = f"tk_it64_{uuid.uuid4().hex}"
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


def _mk(mongo, *, loc_enabled=False, gps_opt=False, reject_outside=False):
    c = _seed_company(mongo,
                      location_punching_enabled=loc_enabled,
                      reject_outside_geofence=reject_outside)
    u = _seed_user(mongo, c["company_id"], gps_punch_enabled=gps_opt)
    t = _seed_session(mongo, u["user_id"])
    return c, u, t


# ===========================================================================
# 1) POST /api/attendance/punch — location_status + outside policy
# ===========================================================================
class TestPunchLocationStatus:
    def test_a_no_gps_manual_when_firm_off(self, sess, mongo):
        """Firm.location_punching_enabled=False → punch allowed with just
        selfie+biometric; record location_status='no-gps',
        source='manual-nogps', gps_verified=False."""
        c, u, tok = _mk(mongo, loc_enabled=False, gps_opt=False)
        r = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "in",
            "biometric_method": "fingerprint",
            "selfie_base64": "AAAA" * 8,
            # Note: send lat/lng anyway — server MUST ignore them.
            "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
        })
        assert r.status_code == 200, r.text
        rec = mongo.attendance.find_one({"user_id": u["user_id"]},
                                        sort=[("at", -1)])
        assert rec is not None
        CREATED_ATTENDANCE_IDS.append(rec["record_id"])
        assert rec.get("source") == "manual-nogps", rec
        assert rec.get("location_status") == "no-gps", rec
        assert rec.get("gps_verified") is False, rec
        # Server ignored the client-sent coordinates.
        assert rec.get("latitude") is None
        assert rec.get("longitude") is None

    def test_a_missing_selfie_rejected_when_firm_off(self, sess, mongo):
        c, u, tok = _mk(mongo, loc_enabled=False, gps_opt=False)
        r = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "in",
            "biometric_method": "fingerprint",
            # no selfie
        })
        assert r.status_code == 400, r.text
        assert "selfie" in r.text.lower()

    def test_a_no_gps_when_user_opt_off(self, sess, mongo):
        """Firm ON, but user gps_punch_enabled=False → still no-gps mode."""
        c, u, tok = _mk(mongo, loc_enabled=True, gps_opt=False)
        r = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "in",
            "biometric_method": "face",
            "selfie_base64": "BBBB" * 8,
            "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
        })
        assert r.status_code == 200, r.text
        rec = mongo.attendance.find_one({"user_id": u["user_id"]},
                                        sort=[("at", -1)])
        CREATED_ATTENDANCE_IDS.append(rec["record_id"])
        assert rec["location_status"] == "no-gps"
        assert rec["source"] == "manual-nogps"
        assert rec["gps_verified"] is False

    def test_b_inside_when_both_flags_on(self, sess, mongo):
        c, u, tok = _mk(mongo, loc_enabled=True, gps_opt=True)
        r = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "in",
            "biometric_method": "fingerprint",
            "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
        })
        assert r.status_code == 200, r.text
        rec = mongo.attendance.find_one({"user_id": u["user_id"]},
                                        sort=[("at", -1)])
        CREATED_ATTENDANCE_IDS.append(rec["record_id"])
        assert rec["location_status"] == "inside", rec
        assert rec.get("gps_verified") is True
        assert rec.get("status") in ("approved", None) or rec["status"] == "approved"
        assert not rec.get("outside_note")

    def test_b_outside_in_allowed_but_pending(self, sess, mongo):
        """Outside-IN no longer rejected — should land with status='pending'
        and outside_note populated."""
        c, u, tok = _mk(mongo, loc_enabled=True, gps_opt=True,
                        reject_outside=False)
        r = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "in",
            "biometric_method": "fingerprint",
            "latitude": OUTSIDE_LAT, "longitude": OUTSIDE_LNG,
        })
        assert r.status_code == 200, r.text
        rec = mongo.attendance.find_one({"user_id": u["user_id"]},
                                        sort=[("at", -1)])
        CREATED_ATTENDANCE_IDS.append(rec["record_id"])
        assert rec["location_status"] == "outside", rec
        assert rec.get("outside_geofence") is True
        assert rec.get("status") == "pending", rec
        assert rec.get("outside_note"), rec
        assert "pending admin review" in (rec.get("outside_note") or "").lower()

    def test_c_outside_in_rejected_when_strict(self, sess, mongo):
        """firm.reject_outside_geofence=True → outside-IN → 400."""
        c, u, tok = _mk(mongo, loc_enabled=True, gps_opt=True,
                        reject_outside=True)
        r = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
            "kind": "in",
            "biometric_method": "fingerprint",
            "latitude": OUTSIDE_LAT, "longitude": OUTSIDE_LNG,
        })
        assert r.status_code == 400, r.text
        assert "geofence" in r.text.lower() or "outside" in r.text.lower()


# ===========================================================================
# 4) PATCH /api/companies/{cid} — reject_outside_geofence field
# ===========================================================================
class TestCompanyPatch:
    def test_patch_reject_outside_flag(self, sess, mongo, super_token):
        c, _, _ = _mk(mongo, loc_enabled=True, gps_opt=False)
        r = sess.patch(
            f"{API}/companies/{c['company_id']}",
            headers=_auth(super_token),
            json={"reject_outside_geofence": True},
        )
        assert r.status_code == 200, r.text
        doc = mongo.companies.find_one({"company_id": c["company_id"]})
        assert doc.get("reject_outside_geofence") is True

        # Toggle back off.
        r = sess.patch(
            f"{API}/companies/{c['company_id']}",
            headers=_auth(super_token),
            json={"reject_outside_geofence": False},
        )
        assert r.status_code == 200, r.text
        doc = mongo.companies.find_one({"company_id": c["company_id"]})
        assert doc.get("reject_outside_geofence") is False


# ===========================================================================
# 2) GET /api/admin/attendance/location-audit
# ===========================================================================
@pytest.fixture(scope="module")
def audit_seed(mongo):
    """Seed 3 attendance rows for one company: inside, outside, no-gps,
    plus one older 'legacy' row without location_status (backfill test)."""
    c = _seed_company(mongo, location_punching_enabled=True)
    u = _seed_user(mongo, c["company_id"], gps_punch_enabled=True)
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    def _ins(kind, at, extra):
        rid = f"att_it64_{uuid.uuid4().hex[:12]}"
        doc = {
            "record_id": rid,
            "user_id": u["user_id"],
            "company_id": c["company_id"],
            "date": today,
            "kind": kind,
            "at": at.isoformat().replace("+00:00", "Z"),
            "biometric_method": "fingerprint",
            "source": "manual",
            "status": "approved",
        }
        doc.update(extra)
        mongo.attendance.insert_one(doc)
        CREATED_ATTENDANCE_IDS.append(rid)
        return rid

    ids = {
        "inside": _ins("in", now - timedelta(minutes=30), {
            "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
            "distance_m": 0.0, "outside_geofence": False,
            "gps_verified": True, "location_status": "inside",
        }),
        "outside": _ins("in", now - timedelta(minutes=20), {
            "latitude": OUTSIDE_LAT, "longitude": OUTSIDE_LNG,
            "distance_m": 11100.0, "outside_geofence": True,
            "gps_verified": True, "location_status": "outside",
            "status": "pending",
            "outside_note": "punched-in 11100m from office — pending admin review",
        }),
        "nogps": _ins("in", now - timedelta(minutes=10), {
            "distance_m": 0.0, "outside_geofence": False,
            "gps_verified": False, "source": "manual-nogps",
            "location_status": "no-gps",
        }),
        # LEGACY row — no location_status; gps_verified=True, outside=False
        "legacy_inside": _ins("out", now - timedelta(minutes=5), {
            "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
            "distance_m": 0.0, "outside_geofence": False,
            "gps_verified": True,
            # NO location_status key set
        }),
    }
    return {"company": c, "user": u, "ids": ids}


class TestLocationAudit:
    def test_list_returns_records_summary(self, sess, super_token, audit_seed):
        cid = audit_seed["company"]["company_id"]
        r = sess.get(
            f"{API}/admin/attendance/location-audit",
            headers=_auth(super_token),
            params={"company_id": cid},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "records" in body and "count" in body and "summary" in body
        assert set(body["summary"].keys()) >= {"inside", "outside", "no-gps"}
        # We seeded 4 rows for this cid; count must be at least 4.
        assert body["count"] >= 4
        # Summary counts sum equals count (or close — filter may pick more if
        # leftover rows exist; we assert lower-bounds).
        s = body["summary"]
        assert s["inside"] >= 1
        assert s["outside"] >= 1
        assert s["no-gps"] >= 1

    def test_records_include_enriched_fields_no_selfie(self, sess, super_token,
                                                       audit_seed):
        cid = audit_seed["company"]["company_id"]
        r = sess.get(
            f"{API}/admin/attendance/location-audit",
            headers=_auth(super_token),
            params={"company_id": cid},
        )
        recs = r.json()["records"]
        assert len(recs) > 0
        for rec in recs:
            assert "location_status" in rec
            assert "user_name" in rec
            assert "company_name" in rec
            assert "employee_code" in rec
            # selfie MUST NOT appear in list view
            assert "selfie_base64" not in rec, "list must strip selfie_base64"
        # At least one record with outside_note.
        assert any(rec.get("outside_note") for rec in recs)

    def test_filter_location_status_outside(self, sess, super_token, audit_seed):
        cid = audit_seed["company"]["company_id"]
        r = sess.get(
            f"{API}/admin/attendance/location-audit",
            headers=_auth(super_token),
            params={"company_id": cid, "location_status": "outside"},
        )
        assert r.status_code == 200
        recs = r.json()["records"]
        assert len(recs) >= 1
        for rec in recs:
            assert rec["location_status"] == "outside", rec

    def test_filter_location_status_nogps(self, sess, super_token, audit_seed):
        cid = audit_seed["company"]["company_id"]
        r = sess.get(
            f"{API}/admin/attendance/location-audit",
            headers=_auth(super_token),
            params={"company_id": cid, "location_status": "no-gps"},
        )
        assert r.status_code == 200
        recs = r.json()["records"]
        assert len(recs) >= 1
        for rec in recs:
            assert rec["location_status"] == "no-gps"

    def test_filter_inside_includes_legacy_backfilled(self, sess, super_token,
                                                     audit_seed):
        """Legacy row without location_status should be surfaced under
        'inside' via _compute_location_status."""
        cid = audit_seed["company"]["company_id"]
        legacy_id = audit_seed["ids"]["legacy_inside"]
        r = sess.get(
            f"{API}/admin/attendance/location-audit",
            headers=_auth(super_token),
            params={"company_id": cid, "location_status": "inside"},
        )
        assert r.status_code == 200
        rec_ids = [rec.get("record_id") for rec in r.json()["records"]]
        assert legacy_id in rec_ids, (
            f"legacy row {legacy_id} not backfilled into 'inside' filter"
        )

    def test_filter_by_user_id(self, sess, super_token, audit_seed):
        uid = audit_seed["user"]["user_id"]
        r = sess.get(
            f"{API}/admin/attendance/location-audit",
            headers=_auth(super_token),
            params={"user_id": uid},
        )
        assert r.status_code == 200
        for rec in r.json()["records"]:
            assert rec["user_id"] == uid

    def test_filter_company_ids_multi(self, sess, super_token, audit_seed):
        cid = audit_seed["company"]["company_id"]
        # Repeated param – Requests handles list values as repeated keys.
        r = sess.get(
            f"{API}/admin/attendance/location-audit",
            headers=_auth(super_token),
            params=[("company_ids", cid), ("company_ids", "co_nonexistent")],
        )
        assert r.status_code == 200
        assert r.json()["count"] >= 4

    def test_employee_role_forbidden(self, sess, mongo, audit_seed):
        emp_tok = _seed_session(mongo, audit_seed["user"]["user_id"])
        r = sess.get(
            f"{API}/admin/attendance/location-audit",
            headers=_auth(emp_tok),
        )
        assert r.status_code == 403, r.text


# ===========================================================================
# 3) GET /api/admin/attendance/location-audit.xlsx
# ===========================================================================
class TestLocationAuditXlsx:
    def test_xlsx_returns_bytes_and_headers(self, sess, super_token, audit_seed):
        cid = audit_seed["company"]["company_id"]
        r = sess.get(
            f"{API}/admin/attendance/location-audit.xlsx",
            headers=_auth(super_token),
            params={"company_id": cid},
        )
        assert r.status_code == 200, r.text
        ct = r.headers.get("content-type", "")
        assert "spreadsheetml" in ct or "excel" in ct.lower() or ct.startswith(
            "application/vnd.openxmlformats"
        ), ct
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd.lower()
        assert "LocationAudit.xlsx" in cd, cd
        # Non-trivial XLSX bytes (PK zip signature 'PK\x03\x04').
        assert len(r.content) > 200
        assert r.content[:2] == b"PK"


# ===========================================================================
# 5) /api/attendance/today and /history include location_status
# ===========================================================================
class TestEmployeeSelfHistoryHasLocationStatus:
    def test_today_and_history_include_location_status(self, sess, mongo):
        c, u, tok = _mk(mongo, loc_enabled=True, gps_opt=True)
        # Punch IN inside then OUT inside to have 2 rows.
        for kind in ("in", "out"):
            r = sess.post(f"{API}/attendance/punch", headers=_auth(tok), json={
                "kind": kind,
                "biometric_method": "fingerprint",
                "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
            })
            assert r.status_code == 200, r.text
        # Also insert a legacy record without location_status.
        rid = f"att_it64_{uuid.uuid4().hex[:12]}"
        mongo.attendance.insert_one({
            "record_id": rid,
            "user_id": u["user_id"],
            "company_id": c["company_id"],
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "kind": "in",
            "at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "latitude": INSIDE_LAT, "longitude": INSIDE_LNG,
            "distance_m": 0.0, "outside_geofence": False, "gps_verified": True,
            "biometric_method": "fingerprint", "source": "manual",
            "status": "approved",
        })
        CREATED_ATTENDANCE_IDS.append(rid)

        r = sess.get(f"{API}/attendance/today", headers=_auth(tok))
        assert r.status_code == 200, r.text
        body = r.json()
        entries = body.get("entries") or body.get("records") or []
        assert len(entries) >= 1
        for e in entries:
            assert "location_status" in e, e
            assert e["location_status"] in ("inside", "outside", "no-gps")

        r = sess.get(f"{API}/attendance/history", headers=_auth(tok))
        assert r.status_code == 200, r.text
        body = r.json()
        recs = body.get("records") or body.get("entries") or []
        assert len(recs) >= 1
        for rec in recs:
            assert "location_status" in rec, rec
