"""Iter 199 — Geofence Monitor + Fake-GPS punch + Proposals Convert to Customer.

Covers 4 BACKEND scenarios for the workspace preview:
  1. Seed flagged attendance rows -> GET /api/admin/geofence/monitor
  2. GET /api/admin/geofence/report?type={mock,offline,csv,invalid}
  3. POST /api/attendance/punch as TEST50 with mock_location -> forced pending
  4. Proposals convert (happy path + already_converted + 409 dup + cleanup)
"""
import os
import csv
import io
import uuid
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PWD = "sharma123"
COMPANY_ID = "cmp_527fecdd7c"  # Kankani

TEST_TAG = "ITER199_"


@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": SUPER_EMAIL, "password": SUPER_PWD}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def super_headers(super_token):
    return {"Authorization": f"Bearer {super_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def kankani_user_id(db):
    u = db.users.find_one({"company_id": COMPANY_ID}, {"user_id": 1})
    assert u, "No Kankani employee found"
    return u["user_id"]


# ---------------------------------------------------------------------------
# BACKEND 1 + 2 — Geofence monitor + reports
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def seed_flagged(db, kankani_user_id):
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(IST).strftime("%Y-%m-%d")
    now_iso = datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S")
    docs = [
        {"record_id": f"{TEST_TAG}offline_{uuid.uuid4().hex[:6]}",
         "user_id": kankani_user_id, "company_id": COMPANY_ID,
         "date": today, "kind": "in", "at": now_iso,
         "offline_punch": True, "synced_at": now_iso,
         "client_punch_at": now_iso, "gps_verified": True,
         "policy_mode": "field", "status": "pending",
         "worksite_name": "TEST_OFFLINE"},
        {"record_id": f"{TEST_TAG}mock_{uuid.uuid4().hex[:6]}",
         "user_id": kankani_user_id, "company_id": COMPANY_ID,
         "date": today, "kind": "in", "at": now_iso,
         "mock_location": True, "gps_accuracy_m": 5.0,
         "policy_mode": "field", "status": "pending",
         "worksite_name": "TEST_MOCK"},
        {"record_id": f"{TEST_TAG}outside_{uuid.uuid4().hex[:6]}",
         "user_id": kankani_user_id, "company_id": COMPANY_ID,
         "date": today, "kind": "in", "at": now_iso,
         "outside_geofence": True, "distance_m": 500.0,
         "policy_mode": "strict", "status": "pending",
         "worksite_name": "TEST_OUTSIDE"},
    ]
    db.attendance.insert_many(docs)
    yield [d["record_id"] for d in docs]
    db.attendance.delete_many({"record_id": {"$regex": f"^{TEST_TAG}"}})


class TestGeofenceMonitor:
    def test_monitor_counts(self, super_headers, seed_flagged):
        r = requests.get(
            f"{BASE_URL}/api/admin/geofence/monitor",
            params={"company_id": COMPANY_ID}, headers=super_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        c = data["counts"]
        assert c["offline"] >= 1, f"offline count too low: {c}"
        assert c["mock"] >= 1, f"mock count too low: {c}"
        assert c["outside"] >= 1, f"outside count too low: {c}"
        assert c["flagged"] >= 3, f"flagged count too low: {c}"
        # recent_flagged has name/code
        recents = data.get("recent_flagged") or []
        assert recents, "recent_flagged empty"
        assert any("employee_name" in r_ for r_ in recents)
        assert any("employee_code" in r_ for r_ in recents)

    def test_report_mock_only(self, super_headers, seed_flagged):
        r = requests.get(
            f"{BASE_URL}/api/admin/geofence/report",
            params={"type": "mock", "company_id": COMPANY_ID},
            headers=super_headers, timeout=20)
        assert r.status_code == 200, r.text
        for row in r.json()["rows"]:
            assert row["mock_location"] is True

    def test_report_offline_has_sync_meta(self, super_headers, seed_flagged):
        r = requests.get(
            f"{BASE_URL}/api/admin/geofence/report",
            params={"type": "offline", "company_id": COMPANY_ID},
            headers=super_headers, timeout=20)
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        assert rows, "offline rows empty"
        for row in rows:
            assert row["offline_punch"] is True
            assert row["captured_at"], "captured_at missing"
            assert row["synced_at"], "synced_at missing"

    def test_report_csv(self, super_headers, seed_flagged):
        r = requests.get(
            f"{BASE_URL}/api/admin/geofence/report",
            params={"type": "mock", "company_id": COMPANY_ID, "format": "csv"},
            headers=super_headers, timeout=20)
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", ""), r.headers
        rdr = csv.reader(io.StringIO(r.text))
        rows = list(rdr)
        assert len(rows) >= 2, "csv missing header or data"
        header = rows[0]
        assert "date" in header and "employee_code" in header and "mock_location" in header

    def test_report_invalid_type(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/geofence/report",
            params={"type": "bogus", "company_id": COMPANY_ID},
            headers=super_headers, timeout=15)
        assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# BACKEND 3 — Fake-GPS forces manual approval even in Field mode
# ---------------------------------------------------------------------------
class TestFakeGPSPunch:
    @pytest.fixture(scope="class")
    def emp_token(self):
        r = requests.post(f"{BASE_URL}/api/auth/pin-login",
                          json={"login_id": "TEST50", "pin": "123456"}, timeout=15)
        assert r.status_code == 200, r.text
        return r.json()["session_token"]

    @pytest.fixture(scope="class", autouse=True)
    def cleanup(self, db):
        yield
        db.attendance.delete_many({"$or": [
            {"punch_reason": {"$regex": f"^{TEST_TAG}"}},
            {"worksite_name": {"$regex": f"^{TEST_TAG}"}},
        ]})

    def test_mock_location_forces_pending(self, db, emp_token):
        # Ensure no pre-existing punch for TEST50 today (previous run leftovers)
        from datetime import datetime, timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        today = datetime.now(IST).strftime("%Y-%m-%d")
        u = db.users.find_one({"login_id": "TEST50"}) or db.users.find_one({"employee_code": "50"})
        if u:
            db.attendance.delete_many({"user_id": u["user_id"], "date": today})
        # tiny 1x1 selfie
        selfie = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0"
            "C8AAAAASUVORK5CYII=")
        payload = {
            "kind": "in",
            "latitude": 25.3463, "longitude": 74.6408,
            "biometric_method": "face",
            "selfie_base64": selfie,
            "mock_location": True, "gps_accuracy_m": 8.0,
            "reason": f"{TEST_TAG}fake_gps_pytest",
            "worksite_name": f"{TEST_TAG}worksite",
        }
        r = requests.post(f"{BASE_URL}/api/attendance/punch", json=payload,
                          headers={"Authorization": f"Bearer {emp_token}"}, timeout=25)
        assert r.status_code == 200, r.text
        rj = r.json()
        # Force manual approval on Field mode when mock_location=True
        assert rj.get("status") == "pending" or rj.get("attendance_status") == "pending" \
            or (rj.get("record") or {}).get("status") == "pending", \
            f"expected pending status, got: {rj}"

        # Verify record persisted with mock_location=True
        row = db.attendance.find_one({"punch_reason": f"{TEST_TAG}fake_gps_pytest"})
        if not row:
            row = db.attendance.find_one({"worksite_name": f"{TEST_TAG}worksite"})
        assert row, f"punch not persisted; response={rj}"
        assert row.get("mock_location") is True, "mock_location flag not stored"
        assert row.get("status") == "pending", f"row status={row.get('status')}"


# ---------------------------------------------------------------------------
# BACKEND 4 — Proposals convert (happy + idempotent + 409 dup)
# ---------------------------------------------------------------------------
class TestProposalConvert:
    @pytest.fixture(scope="class")
    def created(self, db, super_headers):
        created = {"proposals": [], "companies": [], "agreements": []}
        yield created
        # cleanup
        for pid in created["proposals"]:
            db.proposals.delete_one({"proposal_id": pid})
        for cid in created["companies"]:
            db.companies.delete_one({"company_id": cid})
        for aid in created["agreements"]:
            db.client_agreements.delete_one({"agreement_id": aid})

    def _create_proposal(self, super_headers, client_name: str) -> dict:
        payload = {
            "company_id": COMPANY_ID,
            "client": {
                "company_name": client_name,
                "contact_person": "Test Contact",
                "email": "test@convert.example",
                "mobile": "+919999999999",
                "gst": "07AAACT9999Q1ZK",
                "pan": "ABCPT9999Q",
            },
            "services": ["salary_processing", "epf"],
            "pricing": {"one_time": 5000, "monthly": 2000, "billing_months": 12},
            "proposal_types": ["Payroll + Compliance"],
        }
        r = requests.post(f"{BASE_URL}/api/admin/proposals", json=payload,
                          headers=super_headers, timeout=20)
        assert r.status_code == 200, r.text
        return r.json()["proposal"]

    def test_convert_flow(self, db, super_headers, created):
        # Use unique names to avoid collision if a previous run left the firm
        uniq = uuid.uuid4().hex[:6].upper()
        name1 = f"TA Convert Test Ltd {uniq}"
        p1 = self._create_proposal(super_headers, name1)
        created["proposals"].append(p1["proposal_id"])

        # first convert
        r = requests.post(
            f"{BASE_URL}/api/admin/proposals/{p1['proposal_id']}/convert",
            json={"company_id": COMPANY_ID}, headers=super_headers, timeout=20)
        assert r.status_code == 200, r.text
        conv = r.json()
        assert conv["ok"] is True
        assert conv.get("company_id"), conv
        assert conv.get("company_code"), conv
        assert conv.get("agreement_id"), conv
        created["companies"].append(conv["company_id"])
        created["agreements"].append(conv["agreement_id"])

        # verify companies doc
        firm = db.companies.find_one({"company_id": conv["company_id"]})
        assert firm, "firm not created"
        assert firm.get("source") == "proposal_conversion"
        assert firm.get("contact_person") == "Test Contact"
        assert firm.get("gst_no") == "07AAACT9999Q1ZK"
        assert firm.get("name") == name1

        # verify agreement
        agr = db.client_agreements.find_one({"agreement_id": conv["agreement_id"]})
        assert agr, "agreement not created"
        assert agr.get("status") == "active"
        assert "salary_processing" in (agr.get("services") or [])

        # verify proposal marked converted
        prop = db.proposals.find_one({"proposal_id": p1["proposal_id"]})
        assert prop.get("status") == "converted"
        assert prop.get("converted_company_id") == conv["company_id"]

        # idempotent — 2nd convert returns already_converted
        r2 = requests.post(
            f"{BASE_URL}/api/admin/proposals/{p1['proposal_id']}/convert",
            json={"company_id": COMPANY_ID}, headers=super_headers, timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json().get("already_converted") is True

        # 2nd proposal same client name -> 409 on convert
        p2 = self._create_proposal(super_headers, name1)
        created["proposals"].append(p2["proposal_id"])
        r3 = requests.post(
            f"{BASE_URL}/api/admin/proposals/{p2['proposal_id']}/convert",
            json={"company_id": COMPANY_ID}, headers=super_headers, timeout=15)
        assert r3.status_code == 409, r3.text
