"""Iteration 36 backend tests — /api/admin/attendance/today per-employee timeline.

Feature under test: The admin "Present Today" endpoint now returns a
`timeline` array per employee containing every IN/OUT punch for the
current day with an allow-listed set of fields. It must:

  * Preserve chronological order (asc by `at`).
  * Include: at, kind, source, latitude, longitude, outside_note,
    branch_id, branch_name, approved_by.
  * STRIP: selfie_base64, device_info.
  * Keep aggregate fields unchanged (first_in, last_out, still_in,
    hours, punches).
  * Respect scoping:
      - super_admin without company_id → all companies.
      - super_admin with ?company_id=<id> → only that company.
      - super_admin with ?company_id=all → all companies.
      - company_admin → only own company (no leakage).
      - employee → 403.

Runs against the public preview URL. Seeds ephemeral IT36_* rows and
cleans them up. Does NOT touch the real super_admin doc.
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
CREATED_BRANCH_IDS: list[str] = []


# --------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------
@pytest.fixture(scope="session")
def mongo():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    yield db
    # Teardown
    if CREATED_ATTENDANCE_IDS:
        db.attendance.delete_many({"record_id": {"$in": CREATED_ATTENDANCE_IDS}})
    if CREATED_USER_IDS:
        db.attendance.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
        db.user_sessions.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
        db.users.delete_many({"user_id": {"$in": CREATED_USER_IDS}})
    if CREATED_COMPANY_IDS:
        db.companies.delete_many({"company_id": {"$in": CREATED_COMPANY_IDS}})
    if CREATED_BRANCH_IDS:
        db.branches.delete_many({"branch_id": {"$in": CREATED_BRANCH_IDS}})
    if CREATED_SESSION_TOKENS:
        db.user_sessions.delete_many({"session_token": {"$in": CREATED_SESSION_TOKENS}})
    client.close()


@pytest.fixture(scope="session")
def sess():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def _seed_company(mongo, name_suffix=""):
    company_id = f"co_it36_{uuid.uuid4().hex[:8]}"
    doc = {
        "company_id": company_id,
        "name": f"IT36 Co {name_suffix} {RUN_HEX}",
        "address": "Test Address",
        "city": "Bengaluru",
        "state": "KA",
        "office_lat": 13.0,
        "office_lng": 77.6,
        "geofence_radius_m": 200,
        "company_code": f"IT36{uuid.uuid4().hex[:4].upper()}",
        "compliance_enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo.companies.insert_one(doc)
    CREATED_COMPANY_IDS.append(company_id)
    return doc


def _seed_branch(mongo, company_id, name):
    branch_id = f"br_it36_{uuid.uuid4().hex[:8]}"
    mongo.branches.insert_one({
        "branch_id": branch_id,
        "company_id": company_id,
        "name": name,
        "office_lat": 13.0,
        "office_lng": 77.6,
        "geofence_radius_m": 200,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    CREATED_BRANCH_IDS.append(branch_id)
    return branch_id


def _seed_user(mongo, role, company_id):
    user_id = f"user_it36_{uuid.uuid4().hex[:10]}"
    phone = f"+91888{uuid.uuid4().int % 10000000:07d}"
    email = f"it36_{uuid.uuid4().hex[:8]}@test.local"
    doc = {
        "user_id": user_id,
        "email": email,
        "phone": phone,
        "name": f"IT36 {role} {RUN_HEX}",
        "role": role,
        "company_id": company_id,
        "employee_code": f"IT36{uuid.uuid4().hex[:3].upper()}",
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
    token = f"tk_it36_{uuid.uuid4().hex}"
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


def _insert_attendance(
    mongo, user_id, company_id, kind, at_dt,
    *, source="manual", branch_id=None, branch_name=None,
    outside_note=None, approved_by=None,
    selfie_base64=None, device_info=None,
    latitude=13.0, longitude=77.6,
):
    rec_id = f"att_it36_{uuid.uuid4().hex[:12]}"
    d = at_dt.strftime("%Y-%m-%d")
    doc = {
        "record_id": rec_id,
        "user_id": user_id,
        "company_id": company_id,
        "date": d,
        "kind": kind,
        "at": at_dt.isoformat().replace("+00:00", "Z"),
        "latitude": latitude,
        "longitude": longitude,
        "distance_m": 0.0,
        "biometric_method": "fingerprint",
        "source": source,
        "outside_geofence": False,
    }
    if branch_id is not None:
        doc["branch_id"] = branch_id
    if branch_name is not None:
        doc["branch_name"] = branch_name
    if outside_note is not None:
        doc["outside_note"] = outside_note
    if approved_by is not None:
        doc["approved_by"] = approved_by
    if selfie_base64 is not None:
        doc["selfie_base64"] = selfie_base64
    if device_info is not None:
        doc["device_info"] = device_info
    mongo.attendance.insert_one(doc)
    CREATED_ATTENDANCE_IDS.append(rec_id)
    return doc


def _flatten_present(body):
    return {p["user_id"]: p for p in (body.get("present") or [])}


# --------------------------------------------------------------------
# 1) Response shape: timeline array with allow-listed fields; no leaks
# --------------------------------------------------------------------
class TestTimelineShape:
    def test_timeline_has_allowlisted_fields_and_no_leaks(self, sess, mongo):
        comp = _seed_company(mongo, "shape")
        admin = _seed_user(mongo, "company_admin", comp["company_id"])
        admin_tok = _seed_session(mongo, admin["user_id"])
        emp = _seed_user(mongo, "employee", comp["company_id"])
        branch_id = _seed_branch(mongo, comp["company_id"], "HQ Branch IT36")

        base = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
        # Insert one IN with selfie_base64 + device_info + all optional fields;
        # then one OUT lacking those. We must confirm the response strips
        # selfies/device_info regardless.
        _insert_attendance(
            mongo, emp["user_id"], comp["company_id"], "in", base,
            source="manual", branch_id=branch_id, branch_name="HQ Branch IT36",
            outside_note=None, approved_by=None,
            selfie_base64="A" * 32, device_info={"model": "iPhone15", "os": "iOS17"},
        )
        _insert_attendance(
            mongo, emp["user_id"], comp["company_id"], "out",
            base + timedelta(hours=2),
            source="approved", branch_id=branch_id, branch_name="HQ Branch IT36",
            outside_note="Client visit", approved_by=admin["user_id"],
            selfie_base64="B" * 32, device_info={"model": "iPhone15"},
        )

        r = sess.get(f"{API}/admin/attendance/today", headers=_auth(admin_tok))
        assert r.status_code == 200, r.text
        body = r.json()
        present = _flatten_present(body)
        me = present.get(emp["user_id"])
        assert me is not None, f"employee missing: {body}"

        # timeline exists and has 2 entries
        tl = me.get("timeline")
        assert isinstance(tl, list), me
        assert len(tl) == 2, tl

        allowed = {
            "at", "kind", "source", "latitude", "longitude",
            "outside_note", "branch_id", "branch_name", "approved_by",
        }
        for entry in tl:
            # Must not leak selfies / device info
            assert "selfie_base64" not in entry, entry
            assert "device_info" not in entry, entry
            # user_id / company_id / record_id / date should NOT be in the
            # trimmed per-punch dict (redundant — grouped at parent level).
            extra = set(entry.keys()) - allowed
            assert not extra, f"unexpected keys leaked in timeline entry: {extra}"

        # spot-check field values
        e_in, e_out = tl[0], tl[1]
        assert e_in["kind"] == "in"
        assert e_out["kind"] == "out"
        assert e_in["source"] == "manual"
        assert e_out["source"] == "approved"
        assert e_in["branch_id"] == branch_id
        assert e_in["branch_name"] == "HQ Branch IT36"
        assert e_out["outside_note"] == "Client visit"
        assert e_out["approved_by"] == admin["user_id"]
        # lat/lng preserved
        assert e_in["latitude"] == 13.0 and e_in["longitude"] == 77.6

    def test_top_level_no_selfie_or_device_info(self, sess, mongo):
        """Belt & suspenders: JSON body serialized as text must not contain
        the strings 'selfie_base64' or 'device_info' anywhere."""
        comp = _seed_company(mongo, "leakstr")
        admin = _seed_user(mongo, "company_admin", comp["company_id"])
        admin_tok = _seed_session(mongo, admin["user_id"])
        emp = _seed_user(mongo, "employee", comp["company_id"])

        base = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
        _insert_attendance(
            mongo, emp["user_id"], comp["company_id"], "in", base,
            selfie_base64="LEAKED_SELFIE_STRING_ZZ", device_info={"leak_marker": "YES"},
        )

        r = sess.get(f"{API}/admin/attendance/today", headers=_auth(admin_tok))
        assert r.status_code == 200
        raw = r.text
        assert "selfie_base64" not in raw, "selfie_base64 key leaked"
        assert "LEAKED_SELFIE_STRING_ZZ" not in raw, "selfie value leaked"
        assert "device_info" not in raw, "device_info key leaked"
        assert "leak_marker" not in raw, "device_info payload leaked"


# --------------------------------------------------------------------
# 2) Aggregate fields unchanged
# --------------------------------------------------------------------
class TestAggregatesUnchanged:
    def test_aggregate_fields_present_and_correct(self, sess, mongo):
        comp = _seed_company(mongo, "agg")
        admin = _seed_user(mongo, "company_admin", comp["company_id"])
        admin_tok = _seed_session(mongo, admin["user_id"])
        emp = _seed_user(mongo, "employee", comp["company_id"])

        base = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
        # 2 pairs = 4h total: 09:00-11:00, 14:00-16:00
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "in", base)
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "out",
                           base + timedelta(hours=2))
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "in",
                           base + timedelta(hours=5))
        _insert_attendance(mongo, emp["user_id"], comp["company_id"], "out",
                           base + timedelta(hours=7))

        r = sess.get(f"{API}/admin/attendance/today", headers=_auth(admin_tok))
        assert r.status_code == 200, r.text
        me = _flatten_present(r.json()).get(emp["user_id"])
        assert me is not None
        # Aggregates
        for key in ("first_in", "last_out", "still_in", "hours", "punches"):
            assert key in me, f"missing aggregate {key}"
        assert me["punches"] == 4
        assert me["hours"] == 4.0
        assert me["still_in"] is False
        assert me["first_in"] < me["last_out"]


# --------------------------------------------------------------------
# 3) IN → OUT → IN → OUT chronological order, all 4 records
# --------------------------------------------------------------------
class TestChronologicalOrder:
    def test_four_records_ordered_asc(self, sess, mongo):
        comp = _seed_company(mongo, "chrono")
        admin = _seed_user(mongo, "company_admin", comp["company_id"])
        admin_tok = _seed_session(mongo, admin["user_id"])
        emp = _seed_user(mongo, "employee", comp["company_id"])

        base = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
        pairs = [
            ("in", base),
            ("out", base + timedelta(hours=2)),
            ("in", base + timedelta(hours=5)),
            ("out", base + timedelta(hours=7)),
        ]
        # Insert OUT OF ORDER to prove the endpoint sorts by 'at' asc, not
        # insertion order.
        for kind, at in reversed(pairs):
            _insert_attendance(mongo, emp["user_id"], comp["company_id"], kind, at)

        r = sess.get(f"{API}/admin/attendance/today", headers=_auth(admin_tok))
        assert r.status_code == 200, r.text
        me = _flatten_present(r.json()).get(emp["user_id"])
        assert me is not None
        tl = me["timeline"]
        assert len(tl) == 4, tl
        kinds = [e["kind"] for e in tl]
        assert kinds == ["in", "out", "in", "out"], kinds
        ats = [e["at"] for e in tl]
        assert ats == sorted(ats), f"timeline not chronological: {ats}"


# --------------------------------------------------------------------
# 4) super_admin: ?company_id filter vs cross-company
# --------------------------------------------------------------------
class TestSuperAdminScoping:
    """Uses an ephemeral super_admin (NOT the real sksharmaconsultancy@)."""
    def _mk_super(self, mongo):
        # Attach super_admin to a company that will NOT have attendance,
        # so we can differentiate scoped vs cross-company results.
        comp_sa = _seed_company(mongo, "sa_home")
        sa = _seed_user(mongo, "super_admin", comp_sa["company_id"])
        sa_tok = _seed_session(mongo, sa["user_id"])
        return sa, sa_tok

    def test_super_admin_no_filter_returns_all_companies(self, sess, mongo):
        sa, sa_tok = self._mk_super(mongo)
        comp_a = _seed_company(mongo, "sa_A")
        comp_b = _seed_company(mongo, "sa_B")
        emp_a = _seed_user(mongo, "employee", comp_a["company_id"])
        emp_b = _seed_user(mongo, "employee", comp_b["company_id"])
        base = datetime.now(timezone.utc).replace(hour=11, minute=0, second=0, microsecond=0)
        _insert_attendance(mongo, emp_a["user_id"], comp_a["company_id"], "in", base)
        _insert_attendance(mongo, emp_b["user_id"], comp_b["company_id"], "in",
                           base + timedelta(minutes=5))

        # No company_id
        r1 = sess.get(f"{API}/admin/attendance/today", headers=_auth(sa_tok))
        assert r1.status_code == 200, r1.text
        ids1 = set(_flatten_present(r1.json()).keys())
        assert emp_a["user_id"] in ids1, ids1
        assert emp_b["user_id"] in ids1, ids1

        # company_id=all
        r2 = sess.get(f"{API}/admin/attendance/today?company_id=all",
                      headers=_auth(sa_tok))
        assert r2.status_code == 200, r2.text
        ids2 = set(_flatten_present(r2.json()).keys())
        assert emp_a["user_id"] in ids2
        assert emp_b["user_id"] in ids2

    def test_super_admin_with_company_id_filters(self, sess, mongo):
        sa, sa_tok = self._mk_super(mongo)
        comp_a = _seed_company(mongo, "sa_flt_A")
        comp_b = _seed_company(mongo, "sa_flt_B")
        emp_a = _seed_user(mongo, "employee", comp_a["company_id"])
        emp_b = _seed_user(mongo, "employee", comp_b["company_id"])
        base = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
        _insert_attendance(mongo, emp_a["user_id"], comp_a["company_id"], "in", base)
        _insert_attendance(mongo, emp_b["user_id"], comp_b["company_id"], "in",
                           base + timedelta(minutes=5))

        r = sess.get(
            f"{API}/admin/attendance/today",
            headers=_auth(sa_tok),
            params={"company_id": comp_a["company_id"]},
        )
        assert r.status_code == 200, r.text
        pres = _flatten_present(r.json())
        assert emp_a["user_id"] in pres
        assert emp_b["user_id"] not in pres, "cross-company leaked in filtered result"
        # And every returned row belongs to comp_a
        for uid, row in pres.items():
            assert row.get("company_id") == comp_a["company_id"], row


# --------------------------------------------------------------------
# 5) company_admin: only own company, no cross-company leakage
# --------------------------------------------------------------------
class TestCompanyAdminScoping:
    def test_company_admin_cannot_see_other_company(self, sess, mongo):
        comp_a = _seed_company(mongo, "ca_A")
        comp_b = _seed_company(mongo, "ca_B")
        admin_a = _seed_user(mongo, "company_admin", comp_a["company_id"])
        admin_a_tok = _seed_session(mongo, admin_a["user_id"])
        emp_a = _seed_user(mongo, "employee", comp_a["company_id"])
        emp_b = _seed_user(mongo, "employee", comp_b["company_id"])

        base = datetime.now(timezone.utc).replace(hour=13, minute=0, second=0, microsecond=0)
        _insert_attendance(mongo, emp_a["user_id"], comp_a["company_id"], "in", base)
        _insert_attendance(mongo, emp_b["user_id"], comp_b["company_id"], "in",
                           base + timedelta(minutes=5))

        r = sess.get(f"{API}/admin/attendance/today", headers=_auth(admin_a_tok))
        assert r.status_code == 200, r.text
        pres = _flatten_present(r.json())
        assert emp_a["user_id"] in pres
        assert emp_b["user_id"] not in pres, "cross-company leakage for company_admin"

    def test_company_admin_ignores_company_id_query_param(self, sess, mongo):
        """Even if a company_admin tries to pass company_id=<other>, the
        scope must be forced to their own company."""
        comp_a = _seed_company(mongo, "ca_ign_A")
        comp_b = _seed_company(mongo, "ca_ign_B")
        admin_a = _seed_user(mongo, "company_admin", comp_a["company_id"])
        admin_a_tok = _seed_session(mongo, admin_a["user_id"])
        emp_a = _seed_user(mongo, "employee", comp_a["company_id"])
        emp_b = _seed_user(mongo, "employee", comp_b["company_id"])
        base = datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0)
        _insert_attendance(mongo, emp_a["user_id"], comp_a["company_id"], "in", base)
        _insert_attendance(mongo, emp_b["user_id"], comp_b["company_id"], "in",
                           base + timedelta(minutes=5))

        r = sess.get(
            f"{API}/admin/attendance/today",
            headers=_auth(admin_a_tok),
            params={"company_id": comp_b["company_id"]},
        )
        assert r.status_code == 200, r.text
        pres = _flatten_present(r.json())
        # Own emp visible, other emp NOT visible regardless of query param
        assert emp_a["user_id"] in pres
        assert emp_b["user_id"] not in pres


# --------------------------------------------------------------------
# 6) Employee role → 403
# --------------------------------------------------------------------
class TestEmployeeForbidden:
    def test_employee_gets_403(self, sess, mongo):
        comp = _seed_company(mongo, "emp_fbd")
        emp = _seed_user(mongo, "employee", comp["company_id"])
        emp_tok = _seed_session(mongo, emp["user_id"])
        r = sess.get(f"{API}/admin/attendance/today", headers=_auth(emp_tok))
        assert r.status_code == 403, r.text
