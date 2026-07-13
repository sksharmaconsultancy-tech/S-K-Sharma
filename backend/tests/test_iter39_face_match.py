"""
Iteration 39 backend tests — Face-recognition identity match on punch selfies.

Scope (all endpoints under /api):
- PATCH /admin/companies/{id}/face-match  (company_admin own only; super_admin any)
- GET  /auth/me  → user.company.face_match_enabled reflects toggle
- POST /attendance/punch  face-match behaviour
    * toggle OFF → identity.enabled == False, no identity_* on record
    * toggle ON, no selfie → identity.enabled == True, no identity_* on record
    * toggle ON, selfie, NO profile photo → auto-enrol, identity_enrolled=True,
      identity_flagged=False, NO gemini call (never blocks)
    * toggle ON, selfie, HAS profile photo → identity_match_ok/match/confidence/
      reason populated; identity_flagged == (ok AND match=False); NEVER blocks
- GET  /admin/attendance/flagged  → strips selfie_base64/device_info, attaches
  user_name/employee_code/company_name; scoped by role
- PATCH /admin/attendance/{id}/clear-flag  → cross-company 403
- GET  /admin/attendance/{id}/selfie  → returns selfie; cross-company 403; 404
- GET  /admin/users/{id}/photo  → returns profile photo; cross-company 403; 404
- Employee (role gate) → 403 on all admin endpoints

Seed hygiene: prefix all data with IT39_. Cleaned up on teardown. The real super
admin (sksharmaconsultancy@gmail.com) PIN fields are NEVER touched.

To avoid burning EMERGENT_LLM_KEY budget on Gemini calls, the "match=False" flow
is verified by direct DB insertion of a flagged record (option (b) in the review
request). The "toggle ON + selfie + has profile photo" endpoint contract is
verified with a single real call using two tiny identical JPEGs — we assert the
shape of the response, not model semantics.
"""
import base64
import os
import uuid
from datetime import datetime, timezone, timedelta

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

TAG = f"IT39_{uuid.uuid4().hex[:6]}"

# Tiny 1x1 JPEG (used only to confirm response contract; may or may not be
# accepted by Gemini). Same bytes used for both reference and sample so a
# semantic response is likely "match=True" and identity_flagged=False.
_TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsL"
    "DBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/"
    "2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QA"
    "HwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUF"
    "BAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1"
    "dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
    "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9k="
)


def H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _iso(dt):
    return dt.isoformat()


# -------- fixtures --------
@pytest.fixture(scope="module")
def db():
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


@pytest.fixture(scope="module")
def sa_pin_snapshot(db):
    """Snapshot the real super_admin PIN fields BEFORE tests, and re-assert
    after teardown that they are untouched. Belt-and-braces per credentials
    memo."""
    sa = db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}) or {}
    snap = {k: sa.get(k) for k in ("pin_hash", "pin_must_change",
                                     "pin_fail_count", "pin_locked_until")}
    yield snap
    sa2 = db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}) or {}
    for k, v in snap.items():
        assert sa2.get(k) == v, f"Super-admin field {k} was mutated by tests!"


@pytest.fixture(scope="module")
def seed(db, sa_pin_snapshot):
    """Seed 2 companies, super_admin/company_admins/employees, sessions."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=1)

    c1_id = f"cmp_{TAG}_A"
    c2_id = f"cmp_{TAG}_B"
    db.companies.insert_many([
        {
            "company_id": c1_id, "name": f"{TAG} Alpha",
            "company_code": f"{TAG[:6]}A", "office_lat": 12.9,
            "office_lng": 77.6, "geofence_radius_m": 500,
            "face_match_enabled": False, "created_at": _iso(now),
        },
        {
            "company_id": c2_id, "name": f"{TAG} Bravo",
            "company_code": f"{TAG[:6]}B", "office_lat": 15.0,
            "office_lng": 74.0, "geofence_radius_m": 500,
            "face_match_enabled": False, "created_at": _iso(now),
        },
    ])

    users = [
        {"user_id": f"u_{TAG}_su", "name": f"{TAG} SU", "role": "super_admin",
         "email": f"{TAG.lower()}_su@test.local", "created_at": _iso(now)},
        {"user_id": f"u_{TAG}_caA", "name": f"{TAG} CA-A",
         "role": "company_admin", "email": f"{TAG.lower()}_caa@test.local",
         "company_id": c1_id, "employee_code": f"{TAG[:6]}A0001",
         "created_at": _iso(now)},
        {"user_id": f"u_{TAG}_caB", "name": f"{TAG} CA-B",
         "role": "company_admin", "email": f"{TAG.lower()}_cab@test.local",
         "company_id": c2_id, "employee_code": f"{TAG[:6]}B0001",
         "created_at": _iso(now)},
        {"user_id": f"u_{TAG}_empA", "name": f"{TAG} EmpA", "role": "employee",
         "email": f"{TAG.lower()}_empa@test.local", "company_id": c1_id,
         "employee_code": f"{TAG[:6]}A0002", "created_at": _iso(now)},
        {"user_id": f"u_{TAG}_empA2", "name": f"{TAG} EmpA2", "role": "employee",
         "email": f"{TAG.lower()}_empa2@test.local", "company_id": c1_id,
         "employee_code": f"{TAG[:6]}A0003", "created_at": _iso(now)},
        {"user_id": f"u_{TAG}_empA3", "name": f"{TAG} EmpA3", "role": "employee",
         "email": f"{TAG.lower()}_empa3@test.local", "company_id": c1_id,
         "employee_code": f"{TAG[:6]}A0004", "created_at": _iso(now)},
        {"user_id": f"u_{TAG}_empA4", "name": f"{TAG} EmpA4", "role": "employee",
         "email": f"{TAG.lower()}_empa4@test.local", "company_id": c1_id,
         "employee_code": f"{TAG[:6]}A0005", "created_at": _iso(now)},
        {"user_id": f"u_{TAG}_empB", "name": f"{TAG} EmpB", "role": "employee",
         "email": f"{TAG.lower()}_empb@test.local", "company_id": c2_id,
         "employee_code": f"{TAG[:6]}B0002", "created_at": _iso(now)},
    ]
    db.users.insert_many(users)

    tokens = {}
    session_docs = []
    for u in users:
        tok = f"tok_{TAG}_{u['user_id']}"
        tokens[u["user_id"]] = tok
        session_docs.append({
            "session_token": tok, "user_id": u["user_id"],
            "expires_at": exp, "created_at": _iso(now),
        })
    db.user_sessions.insert_many(session_docs)

    handles = {
        "c1": c1_id, "c2": c2_id,
        "su": tokens[f"u_{TAG}_su"],
        "caA": tokens[f"u_{TAG}_caA"],
        "caB": tokens[f"u_{TAG}_caB"],
        "empA": tokens[f"u_{TAG}_empA"],
        "empA2": tokens[f"u_{TAG}_empA2"],
        "empA3": tokens[f"u_{TAG}_empA3"],
        "empA4": tokens[f"u_{TAG}_empA4"],
        "empB": tokens[f"u_{TAG}_empB"],
        "empA_uid": f"u_{TAG}_empA",
        "empA2_uid": f"u_{TAG}_empA2",
        "empA3_uid": f"u_{TAG}_empA3",
        "empA4_uid": f"u_{TAG}_empA4",
        "empB_uid": f"u_{TAG}_empB",
        "user_ids": [u["user_id"] for u in users],
        "tokens": list(tokens.values()),
    }
    yield handles

    # ---- cleanup ----
    db.attendance.delete_many({"company_id": {"$in": [c1_id, c2_id]}})
    db.user_sessions.delete_many({"session_token": {"$in": handles["tokens"]}})
    db.users.delete_many({"user_id": {"$in": handles["user_ids"]}})
    db.companies.delete_many({"company_id": {"$in": [c1_id, c2_id]}})


# ---------------------------------------------------------------------------
# 1. Toggle endpoint + RBAC
# ---------------------------------------------------------------------------
class TestFaceMatchToggle:
    def test_super_admin_can_toggle_any(self, seed, db):
        r = requests.patch(f"{API}/admin/companies/{seed['c1']}/face-match",
                           json={"enabled": True}, headers=H(seed["su"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["company"]["face_match_enabled"] is True
        # Verify in DB
        c = db.companies.find_one({"company_id": seed["c1"]})
        assert c["face_match_enabled"] is True

    def test_company_admin_can_toggle_own(self, seed, db):
        # caA enables for c1 (still True)
        r = requests.patch(f"{API}/admin/companies/{seed['c1']}/face-match",
                           json={"enabled": True}, headers=H(seed["caA"]))
        assert r.status_code == 200, r.text
        assert r.json()["company"]["face_match_enabled"] is True

    def test_company_admin_cannot_toggle_other(self, seed):
        # caA tries to toggle c2
        r = requests.patch(f"{API}/admin/companies/{seed['c2']}/face-match",
                           json={"enabled": True}, headers=H(seed["caA"]))
        assert r.status_code == 403, r.text

    def test_employee_forbidden(self, seed):
        r = requests.patch(f"{API}/admin/companies/{seed['c1']}/face-match",
                           json={"enabled": True}, headers=H(seed["empA"]))
        assert r.status_code == 403, r.text

    def test_unknown_company_404(self, seed):
        r = requests.patch(f"{API}/admin/companies/does_not_exist/face-match",
                           json={"enabled": True}, headers=H(seed["su"]))
        assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# 2. GET /auth/me reflects flag
# ---------------------------------------------------------------------------
class TestAuthMeReflects:
    def test_me_shows_face_match_enabled_true(self, seed):
        r = requests.get(f"{API}/auth/me", headers=H(seed["caA"]))
        assert r.status_code == 200, r.text
        u = r.json()["user"]
        assert u.get("company", {}).get("face_match_enabled") is True

    def test_me_shows_face_match_enabled_false(self, seed):
        # c2 was never enabled
        r = requests.get(f"{API}/auth/me", headers=H(seed["caB"]))
        assert r.status_code == 200, r.text
        u = r.json()["user"]
        assert u.get("company", {}).get("face_match_enabled") is False


# ---------------------------------------------------------------------------
# 3. Punch behaviour under each toggle state
# ---------------------------------------------------------------------------
class TestPunchIdentity:
    def test_toggle_OFF_no_identity_fields(self, seed, db):
        # empB in c2 (face_match_enabled=False), send with selfie
        r = requests.post(f"{API}/attendance/punch",
                          json={"kind": "in", "latitude": 15.0,
                                "longitude": 74.0,
                                "biometric_method": "face",
                                "selfie_base64": _TINY_JPEG_B64},
                          headers=H(seed["empB"]), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["identity"]["enabled"] is False
        # record has NO identity_* fields
        rec = db.attendance.find_one({"record_id": body["record_id"]})
        for k in ("identity_flagged", "identity_match_ok", "identity_match",
                  "identity_confidence", "identity_reason", "identity_enrolled"):
            assert k not in rec, f"unexpected {k} on OFF-toggle record: {rec.get(k)}"

    def test_toggle_ON_no_selfie_skipped(self, seed, db):
        # empA in c1 (ON), no selfie in payload
        r = requests.post(f"{API}/attendance/punch",
                          json={"kind": "in", "latitude": 12.9,
                                "longitude": 77.6,
                                "biometric_method": "fingerprint"},
                          headers=H(seed["empA"]), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["identity"]["enabled"] is True
        # record must not have identity_* set
        rec = db.attendance.find_one({"record_id": body["record_id"]})
        for k in ("identity_flagged", "identity_match_ok", "identity_match",
                  "identity_confidence", "identity_reason", "identity_enrolled"):
            assert k not in rec, f"unexpected {k} when no selfie: {rec.get(k)}"

    def test_toggle_ON_selfie_no_profile_photo_auto_enrols(self, seed, db):
        # empA2 in c1, no profile_photo_base64 yet
        uid = seed["empA2_uid"]
        before = db.users.find_one({"user_id": uid})
        assert not before.get("profile_photo_base64")
        r = requests.post(f"{API}/attendance/punch",
                          json={"kind": "in", "latitude": 12.9,
                                "longitude": 77.6,
                                "biometric_method": "face",
                                "selfie_base64": _TINY_JPEG_B64},
                          headers=H(seed["empA2"]), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["identity"]["enabled"] is True
        assert body["identity"].get("enrolled") is True
        # user now has profile_photo_base64 and auto_enrolled flag
        after = db.users.find_one({"user_id": uid})
        assert after.get("profile_photo_base64") == _TINY_JPEG_B64
        assert after.get("profile_photo_auto_enrolled") is True
        # attendance record: identity_enrolled=True, identity_flagged=False,
        # no identity_match_ok field (skipped Gemini)
        rec = db.attendance.find_one({"record_id": body["record_id"]})
        assert rec.get("identity_enrolled") is True
        assert rec.get("identity_flagged") is False
        assert "identity_match_ok" not in rec
        assert "identity_confidence" not in rec

    def test_toggle_ON_selfie_with_profile_photo_populates_fields(self, seed, db):
        """Real Gemini call fires here. We assert the CONTRACT (fields present,
        types correct, identity_flagged equals ok AND match==False). Semantic
        correctness of the model is out of scope."""
        uid = seed["empA3_uid"]
        # Pre-seed profile photo
        db.users.update_one({"user_id": uid},
                            {"$set": {"profile_photo_base64": _TINY_JPEG_B64,
                                      "profile_photo_updated_at": _iso(datetime.now(timezone.utc))}})
        r = requests.post(f"{API}/attendance/punch",
                          json={"kind": "in", "latitude": 12.9,
                                "longitude": 77.6,
                                "biometric_method": "face",
                                "selfie_base64": _TINY_JPEG_B64},
                          headers=H(seed["empA3"]), timeout=90)
        # Punch must NEVER be blocked by face-match — always 200.
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["identity"]["enabled"] is True
        rec = db.attendance.find_one({"record_id": body["record_id"]})
        # All four identity fields must be populated on the record
        assert "identity_match_ok" in rec
        assert "identity_match" in rec  # may be True/False/None
        assert "identity_confidence" in rec
        assert "identity_reason" in rec
        assert isinstance(rec["identity_match_ok"], bool)
        conf = rec["identity_confidence"]
        assert isinstance(conf, (int, float))
        assert 0.0 <= float(conf) <= 1.0
        # identity_flagged must equal (ok is True AND match is False)
        expected_flag = (
            rec["identity_match_ok"] is True and rec["identity_match"] is False
        )
        assert rec.get("identity_flagged") is expected_flag, (
            f"identity_flagged={rec.get('identity_flagged')}, "
            f"ok={rec['identity_match_ok']}, match={rec['identity_match']}"
        )

    def test_punch_never_blocked_by_face_match(self, seed, db):
        """Even if we simulate mismatch (via DB) the raw endpoint stays 200.
        Using empA4 with a real Gemini call — endpoint MUST return 200 whether
        the model says match=True or match=False."""
        uid = seed["empA4_uid"]
        db.users.update_one({"user_id": uid},
                            {"$set": {"profile_photo_base64": _TINY_JPEG_B64}})
        r = requests.post(f"{API}/attendance/punch",
                          json={"kind": "in", "latitude": 12.9,
                                "longitude": 77.6,
                                "biometric_method": "face",
                                "selfie_base64": _TINY_JPEG_B64},
                          headers=H(seed["empA4"]), timeout=90)
        assert r.status_code == 200, r.text
        # record was still inserted regardless of outcome
        assert db.attendance.find_one({"record_id": r.json()["record_id"]}) is not None


# ---------------------------------------------------------------------------
# 4. Admin endpoints — flagged list / clear-flag / selfie / photo
# Uses direct DB insert to deterministically create a flagged record.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def flagged_records(db, seed):
    """Seed one flagged attendance record per company (c1 and c2)."""
    now_str = _iso(datetime.now(timezone.utc))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rec_a = {
        "record_id": f"att_{TAG}_flagA",
        "user_id": seed["empA_uid"],
        "company_id": seed["c1"],
        "branch_id": None, "branch_name": None,
        "date": today, "kind": "in", "at": now_str,
        "latitude": 12.9, "longitude": 77.6, "distance_m": 5.0,
        "biometric_method": "face",
        "selfie_base64": "SEEDED_SELFIE_A",
        "device_info": "device-A", "source": "manual",
        "outside_geofence": False,
        "identity_match_ok": True, "identity_match": False,
        "identity_confidence": 0.72,
        "identity_reason": "different jawline",
        "identity_flagged": True,
    }
    rec_b = {
        "record_id": f"att_{TAG}_flagB",
        "user_id": seed["empB_uid"],
        "company_id": seed["c2"],
        "branch_id": None, "branch_name": None,
        "date": today, "kind": "in", "at": now_str,
        "latitude": 15.0, "longitude": 74.0, "distance_m": 3.0,
        "biometric_method": "face",
        "selfie_base64": "SEEDED_SELFIE_B",
        "device_info": "device-B", "source": "manual",
        "outside_geofence": False,
        "identity_match_ok": True, "identity_match": False,
        "identity_confidence": 0.31,
        "identity_reason": "mismatch",
        "identity_flagged": True,
    }
    db.attendance.insert_many([rec_a, rec_b])
    yield {"a": rec_a["record_id"], "b": rec_b["record_id"]}
    db.attendance.delete_many({"record_id": {"$in": [rec_a["record_id"], rec_b["record_id"]]}})


class TestFlaggedList:
    def test_company_admin_only_own_scope(self, seed, flagged_records):
        r = requests.get(f"{API}/admin/attendance/flagged",
                         headers=H(seed["caA"]))
        assert r.status_code == 200, r.text
        body = r.json()
        recs = body["flagged"]
        rec_ids = {x["record_id"] for x in recs}
        assert flagged_records["a"] in rec_ids
        assert flagged_records["b"] not in rec_ids
        # All returned records are for c1 only
        for x in recs:
            assert x.get("company_id") == seed["c1"]
            # selfie_base64 and device_info STRIPPED
            assert "selfie_base64" not in x, x
            assert "device_info" not in x, x
        # Enriched user + company display fields
        target = next(x for x in recs if x["record_id"] == flagged_records["a"])
        assert target.get("user_name")
        assert target.get("employee_code")
        assert target.get("company_name")

    def test_super_admin_sees_all_and_filter(self, seed, flagged_records):
        r = requests.get(f"{API}/admin/attendance/flagged",
                         headers=H(seed["su"]))
        assert r.status_code == 200
        rec_ids = {x["record_id"] for x in r.json()["flagged"]}
        assert flagged_records["a"] in rec_ids
        assert flagged_records["b"] in rec_ids
        # Filter to c2
        r = requests.get(f"{API}/admin/attendance/flagged",
                         params={"company_id": seed["c2"]},
                         headers=H(seed["su"]))
        assert r.status_code == 200
        rec_ids = {x["record_id"] for x in r.json()["flagged"]}
        assert flagged_records["b"] in rec_ids
        assert flagged_records["a"] not in rec_ids

    def test_employee_forbidden(self, seed):
        r = requests.get(f"{API}/admin/attendance/flagged",
                         headers=H(seed["empA"]))
        assert r.status_code == 403, r.text


class TestClearFlag:
    def test_cross_company_forbidden(self, seed, flagged_records):
        # caA clearing c2's record
        r = requests.patch(
            f"{API}/admin/attendance/{flagged_records['b']}/clear-flag",
            headers=H(seed["caA"]))
        assert r.status_code == 403, r.text

    def test_unknown_record_404(self, seed):
        r = requests.patch(
            f"{API}/admin/attendance/att_does_not_exist/clear-flag",
            headers=H(seed["su"]))
        assert r.status_code == 404, r.text

    def test_employee_forbidden(self, seed, flagged_records):
        r = requests.patch(
            f"{API}/admin/attendance/{flagged_records['a']}/clear-flag",
            headers=H(seed["empA"]))
        assert r.status_code == 403, r.text

    def test_own_company_clears_and_records_reviewer(self, seed, flagged_records, db):
        r = requests.patch(
            f"{API}/admin/attendance/{flagged_records['a']}/clear-flag",
            headers=H(seed["caA"]))
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        rec = db.attendance.find_one({"record_id": flagged_records["a"]})
        assert rec["identity_flagged"] is False
        assert rec.get("identity_reviewed_by") == seed["empA_uid"].replace("empA", "caA") or True
        # Actually reviewer must equal caA user_id
        assert rec.get("identity_reviewed_by") == f"u_{TAG}_caA"
        assert rec.get("identity_reviewed_at")


class TestGetSelfie:
    def test_own_company_returns_selfie(self, seed, flagged_records):
        r = requests.get(
            f"{API}/admin/attendance/{flagged_records['a']}/selfie",
            headers=H(seed["caA"]))
        assert r.status_code == 200, r.text
        assert r.json()["selfie_base64"] == "SEEDED_SELFIE_A"

    def test_cross_company_forbidden(self, seed, flagged_records):
        r = requests.get(
            f"{API}/admin/attendance/{flagged_records['b']}/selfie",
            headers=H(seed["caA"]))
        assert r.status_code == 403, r.text

    def test_unknown_record_404(self, seed):
        r = requests.get(
            f"{API}/admin/attendance/att_nope/selfie",
            headers=H(seed["su"]))
        assert r.status_code == 404, r.text

    def test_employee_forbidden(self, seed, flagged_records):
        r = requests.get(
            f"{API}/admin/attendance/{flagged_records['a']}/selfie",
            headers=H(seed["empA"]))
        assert r.status_code == 403, r.text


class TestGetUserPhoto:
    def test_own_company_returns_photo(self, seed, db):
        # empA3 was seeded with _TINY_JPEG_B64 in the punch test above; if the
        # test order changes, ensure it is present now.
        db.users.update_one({"user_id": seed["empA3_uid"]},
                            {"$set": {"profile_photo_base64": _TINY_JPEG_B64}})
        r = requests.get(f"{API}/admin/users/{seed['empA3_uid']}/photo",
                         headers=H(seed["caA"]))
        assert r.status_code == 200, r.text
        assert r.json()["photo_base64"] == _TINY_JPEG_B64

    def test_cross_company_forbidden(self, seed):
        r = requests.get(f"{API}/admin/users/{seed['empB_uid']}/photo",
                         headers=H(seed["caA"]))
        assert r.status_code == 403, r.text

    def test_unknown_user_404(self, seed):
        r = requests.get(f"{API}/admin/users/u_nope_it39/photo",
                         headers=H(seed["su"]))
        assert r.status_code == 404, r.text

    def test_employee_forbidden(self, seed):
        r = requests.get(f"{API}/admin/users/{seed['empA_uid']}/photo",
                         headers=H(seed["empA"]))
        assert r.status_code == 403, r.text
