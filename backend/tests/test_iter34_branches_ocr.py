"""
Iteration 34 backend tests — Multi-branch CRUD + geofence integration + OCR ID proof.

- Seeds ephemeral company/users/branches directly in Mongo (super_admin PIN NOT touched)
- Uses public EXPO_PUBLIC_BACKEND_URL for HTTP calls
- Cleans up on teardown
"""
import base64
import os
import sys
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

TAG = f"IT34{uuid.uuid4().hex[:6]}"


def _iso(dt):
    return dt.isoformat()


@pytest.fixture(scope="module")
def db():
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


@pytest.fixture(scope="module")
def seed(db):
    """Seed 2 companies, admins + employee, sessions. Return handles."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=1)

    c1_id = f"cmp_{TAG}_A"
    c2_id = f"cmp_{TAG}_B"
    db.companies.insert_many([
        {
            "company_id": c1_id,
            "name": f"{TAG} Alpha",
            "company_code": f"{TAG[:6]}A",
            "office_lat": 12.9,
            "office_lng": 77.6,
            "geofence_radius_m": 200,
            "created_at": _iso(now),
        },
        {
            "company_id": c2_id,
            "name": f"{TAG} Bravo",
            "company_code": f"{TAG[:6]}B",
            "office_lat": 15.0,
            "office_lng": 74.0,
            "geofence_radius_m": 200,
            "created_at": _iso(now),
        },
    ])

    users = [
        # super admin (ephemeral, NOT the real one)
        {"user_id": f"u_{TAG}_su", "name": f"{TAG} SU", "role": "super_admin",
         "email": f"{TAG.lower()}_su@test.local", "created_at": _iso(now)},
        # company_admin for A
        {"user_id": f"u_{TAG}_caA", "name": f"{TAG} CA-A", "role": "company_admin",
         "email": f"{TAG.lower()}_caa@test.local", "company_id": c1_id,
         "employee_code": f"{TAG[:6]}A0001", "created_at": _iso(now)},
        # company_admin for B
        {"user_id": f"u_{TAG}_caB", "name": f"{TAG} CA-B", "role": "company_admin",
         "email": f"{TAG.lower()}_cab@test.local", "company_id": c2_id,
         "employee_code": f"{TAG[:6]}B0001", "created_at": _iso(now)},
        # employee for A
        {"user_id": f"u_{TAG}_empA", "name": f"{TAG} EmpA", "role": "employee",
         "email": f"{TAG.lower()}_empa@test.local", "company_id": c1_id,
         "employee_code": f"{TAG[:6]}A0002", "created_at": _iso(now)},
    ]
    db.users.insert_many(users)

    tokens = {}
    session_docs = []
    for u in users:
        tok = f"tok_{TAG}_{u['user_id']}"
        tokens[u["user_id"]] = tok
        session_docs.append({
            "session_token": tok,
            "user_id": u["user_id"],
            "expires_at": exp,
            "created_at": _iso(now),
        })
    db.user_sessions.insert_many(session_docs)

    handles = {
        "c1": c1_id,
        "c2": c2_id,
        "su": tokens[f"u_{TAG}_su"],
        "caA": tokens[f"u_{TAG}_caA"],
        "caB": tokens[f"u_{TAG}_caB"],
        "empA": tokens[f"u_{TAG}_empA"],
        "empA_user_id": f"u_{TAG}_empA",
    }
    yield handles

    # ---- cleanup ----
    db.branches.delete_many({"company_id": {"$in": [c1_id, c2_id]}})
    db.attendance.delete_many({"company_id": {"$in": [c1_id, c2_id]}})
    db.user_sessions.delete_many({"session_token": {"$in": list(tokens.values())}})
    db.users.delete_many({"user_id": {"$in": [u["user_id"] for u in users]}})
    db.companies.delete_many({"company_id": {"$in": [c1_id, c2_id]}})


def H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Branches CRUD
# ---------------------------------------------------------------------------
class TestBranches:
    def test_list_as_company_admin_only_own(self, seed):
        # Precondition: create one branch in each company via super_admin
        r = requests.post(f"{API}/company/branches",
                          json={"company_id": seed["c1"], "name": f"{TAG}-A-b1",
                                "office_lat": 12.91, "office_lng": 77.61,
                                "geofence_radius_m": 250},
                          headers=H(seed["su"]))
        assert r.status_code == 200, r.text
        seed["_brA1"] = r.json()["branch"]["branch_id"]
        r = requests.post(f"{API}/company/branches",
                          json={"company_id": seed["c2"], "name": f"{TAG}-B-b1",
                                "office_lat": 15.01, "office_lng": 74.01,
                                "geofence_radius_m": 250},
                          headers=H(seed["su"]))
        assert r.status_code == 200, r.text
        seed["_brB1"] = r.json()["branch"]["branch_id"]

        # company_admin A → only their own
        r = requests.get(f"{API}/company/branches", headers=H(seed["caA"]))
        assert r.status_code == 200
        cids = {b["company_id"] for b in r.json()["branches"]}
        assert cids == {seed["c1"]}, cids

    def test_list_as_super_admin_all_and_filtered(self, seed):
        r = requests.get(f"{API}/company/branches", headers=H(seed["su"]))
        assert r.status_code == 200
        all_cids = {b["company_id"] for b in r.json()["branches"]}
        assert seed["c1"] in all_cids and seed["c2"] in all_cids

        r = requests.get(f"{API}/company/branches",
                         params={"company_id": seed["c1"]}, headers=H(seed["su"]))
        assert r.status_code == 200
        assert all(b["company_id"] == seed["c1"] for b in r.json()["branches"])

    def test_post_company_admin_own_company(self, seed):
        r = requests.post(f"{API}/company/branches",
                          json={"name": f"{TAG}-A-b2",
                                "office_lat": 12.92, "office_lng": 77.62,
                                "geofence_radius_m": 300},
                          headers=H(seed["caA"]))
        assert r.status_code == 200, r.text
        b = r.json()["branch"]
        assert b["company_id"] == seed["c1"]
        assert b["geofence_radius_m"] == 300
        seed["_brA2"] = b["branch_id"]

    def test_post_super_admin_requires_company_id(self, seed):
        r = requests.post(f"{API}/company/branches",
                          json={"name": f"{TAG}-nocid",
                                "office_lat": 12.9, "office_lng": 77.6},
                          headers=H(seed["su"]))
        assert r.status_code == 400, r.text
        assert "company_id" in r.text.lower()

    def test_patch_merge(self, seed):
        r = requests.patch(f"{API}/company/branches/{seed['_brA2']}",
                           json={"geofence_radius_m": 500, "name": f"{TAG}-A-b2R"},
                           headers=H(seed["caA"]))
        assert r.status_code == 200, r.text
        assert r.json()["branch"]["geofence_radius_m"] == 500
        assert r.json()["branch"]["name"] == f"{TAG}-A-b2R"

    def test_patch_cross_company_403(self, seed):
        # company_admin A editing company B's branch
        r = requests.patch(f"{API}/company/branches/{seed['_brB1']}",
                           json={"name": "hijack"}, headers=H(seed["caA"]))
        assert r.status_code == 403, r.text

    def test_delete_cross_company_403(self, seed):
        r = requests.delete(f"{API}/company/branches/{seed['_brB1']}",
                            headers=H(seed["caA"]))
        assert r.status_code == 403

    def test_delete_success(self, seed):
        r = requests.delete(f"{API}/company/branches/{seed['_brA2']}",
                            headers=H(seed["caA"]))
        assert r.status_code == 200, r.text
        # Verify gone
        r = requests.patch(f"{API}/company/branches/{seed['_brA2']}",
                           json={"name": "x"}, headers=H(seed["caA"]))
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Multi-branch geofence in /attendance/punch
# ---------------------------------------------------------------------------
class TestPunchMultiBranch:
    def test_setup_branch_and_punch_inside(self, seed, db):
        # Insert a branch at 13.0/77.7 radius 300 for company A
        branch_id = f"br_{TAG}_geo"
        db.branches.insert_one({
            "branch_id": branch_id,
            "company_id": seed["c1"],
            "name": f"{TAG}-A-geo-branch",
            "office_lat": 13.0,
            "office_lng": 77.7,
            "geofence_radius_m": 300,
            "active": True,
            "created_at": _iso(datetime.now(timezone.utc)),
        })
        seed["_geo_branch_id"] = branch_id

        r = requests.post(f"{API}/attendance/punch",
                          json={"kind": "in", "latitude": 13.0, "longitude": 77.7,
                                "biometric_method": "fingerprint"},
                          headers=H(seed["empA"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["branch_id"] == branch_id, body
        assert body["branch_name"] == f"{TAG}-A-geo-branch", body
        seed["_att_record_id"] = body["record_id"]

    def test_attendance_record_has_branch_id(self, seed, db):
        rec = db.attendance.find_one({"record_id": seed["_att_record_id"]})
        assert rec is not None
        assert rec["branch_id"] == seed["_geo_branch_id"]

    def test_punch_outside_all_geofences(self, seed):
        r = requests.post(f"{API}/attendance/punch",
                          json={"kind": "in", "latitude": 14.0, "longitude": 78.0,
                                "biometric_method": "fingerprint"},
                          headers=H(seed["empA"]))
        assert r.status_code == 400, r.text
        assert "geofence" in r.text.lower() or "outside" in r.text.lower()


# ---------------------------------------------------------------------------
# OCR endpoint
# ---------------------------------------------------------------------------
# a tiny valid JPEG (~1x1 red pixel) — used only for the "no 500" contract check
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


class TestOcrIdProof:
    def test_missing_image_base64(self, seed):
        # empty string triggers explicit 400
        r = requests.post(f"{API}/me/ocr-id-proof",
                          json={"image_base64": "", "doc_type": "aadhaar"},
                          headers=H(seed["empA"]))
        assert r.status_code == 400, r.text

    def test_image_too_large(self, seed):
        big = "A" * 6_500_000  # >6M chars, decodes to >4.5MB
        r = requests.post(f"{API}/me/ocr-id-proof",
                          json={"image_base64": big, "doc_type": "aadhaar"},
                          headers=H(seed["empA"]))
        assert r.status_code == 413, r.text

    def test_valid_tiny_jpeg_no_500(self, seed):
        # REAL Gemini call fires. Accept 200 (ok:true or ok:false) or 502
        # (upstream error). Never a 500.
        r = requests.post(
            f"{API}/me/ocr-id-proof",
            json={"image_base64": f"data:image/jpeg;base64,{_TINY_JPEG_B64}",
                  "doc_type": "aadhaar"},
            headers=H(seed["empA"]),
            timeout=90,
        )
        assert r.status_code in (200, 502), f"{r.status_code}: {r.text}"
        # On 200 the app must return JSON. On 502 the response may pass
        # through Cloudflare and be re-wrapped as text/html (edge behaviour).
        if r.status_code == 200:
            assert r.headers.get("Content-Type", "").startswith("application/json")
            body = r.json()
            assert "ok" in body
            if body.get("ok"):
                assert "parsed" in body
            else:
                assert "raw" in body or "detail" in body
