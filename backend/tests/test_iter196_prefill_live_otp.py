"""Iter 196 — Statutory Registration LIVE VIEW / OTP / PREFILL / BULK regression.

Covers the new endpoints added this iteration:
- GET /api/admin/statutory/{portal}/employee/{user_id}/prefill
- POST /api/admin/statutory/uan/bulk (one-click Register on Portal path)
- GET /api/admin/portal-automation/jobs/{job_id}/live
- POST /api/admin/portal-automation/jobs/{job_id}/otp
"""
import os
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://emplo-connect-1.preview.emergentagent.com",
).rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
_mongo = MongoClient(MONGO_URL)[DB_NAME]


# ---------- fixtures ---------- #
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def hdr(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


_created_reg_ids: list = []
_touched_uids: list = []
_touched_users_orig: dict = {}


def _snap_user(uid):
    if uid in _touched_users_orig:
        return
    u = _mongo.users.find_one({"user_id": uid},
                              {"_id": 0, "aadhaar_no": 1, "uan_no": 1, "esi_ip_no": 1}) or {}
    _touched_users_orig[uid] = {k: u.get(k) for k in ("aadhaar_no", "uan_no", "esi_ip_no")}


def _pick_ready(hdr_, portal):
    r = requests.get(
        f"{BASE_URL}/api/admin/statutory/{portal}/eligible",
        params={"company_id": COMPANY_ID}, headers=hdr_, timeout=60,
    )
    for e in r.json().get("employees", []):
        if e.get("ready") and not e.get("duplicate") and not e.get("open_registration"):
            return e
    return None


# ---------- 1. PREFILL ---------- #
class TestPrefill:
    def test_esic_prefill_returns_all_sections(self, hdr):
        emp = _pick_ready(hdr, "esic")
        if not emp:
            pytest.skip("no ESIC-eligible employee")
        r = requests.get(
            f"{BASE_URL}/api/admin/statutory/esic/employee/{emp['user_id']}/prefill",
            headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert j["employee"]["user_id"] == emp["user_id"]
        assert "snapshot" in j and isinstance(j["snapshot"], dict)
        assert "validation" in j and "ok" in j["validation"]
        assert "duplicate" in j
        assert "registration" in j  # can be None
        assert "settings" in j
        # employee block sanity
        assert j["employee"].get("company_id") == COMPANY_ID
        assert j["employee"].get("company_name")  # Kankani Enterprises

    def test_uan_prefill(self, hdr):
        emp = _pick_ready(hdr, "uan")
        if not emp:
            pytest.skip("no UAN-eligible employee")
        r = requests.get(
            f"{BASE_URL}/api/admin/statutory/uan/employee/{emp['user_id']}/prefill",
            headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert j["snapshot"]
        assert j["validation"]

    def test_prefill_bad_portal_400(self, hdr):
        emp = _pick_ready(hdr, "esic")
        if not emp:
            pytest.skip("no employee")
        r = requests.get(
            f"{BASE_URL}/api/admin/statutory/foo/employee/{emp['user_id']}/prefill",
            headers=hdr, timeout=30,
        )
        assert r.status_code == 400

    def test_prefill_unauth_401_or_403(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/statutory/esic/employee/user_xxxx/prefill",
            timeout=30,
        )
        assert r.status_code in (401, 403)


# ---------- 2. UAN BULK -> queued -> live ---------- #
class TestBulkAndLive:
    reg_id = None
    job_id = None
    user_id = None

    def test_1_uan_bulk_one_employee_queued(self, hdr):
        emp = _pick_ready(hdr, "uan")
        if not emp:
            pytest.skip("no UAN-eligible employee")
        TestBulkAndLive.user_id = emp["user_id"]
        _snap_user(emp["user_id"])
        r = requests.post(
            f"{BASE_URL}/api/admin/statutory/uan/bulk",
            json={"employee_user_ids": [emp["user_id"]]},
            headers=hdr, timeout=60,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["total"] == 1
        assert len(j["results"]) == 1
        result = j["results"][0]
        # Kankani HAS EPFO creds -> queued (or pending_approval if setting flipped)
        assert result["status"] in ("queued", "pending_approval", "action_required"), result
        # fetch reg id
        reg = _mongo.statutory_registrations.find_one(
            {"employee_user_id": emp["user_id"], "portal": "uan"},
            {"_id": 0, "reg_id": 1, "rpa_job_id": 1, "status": 1},
            sort=[("created_at", -1)],
        )
        assert reg, "registration not created"
        TestBulkAndLive.reg_id = reg["reg_id"]
        TestBulkAndLive.job_id = reg.get("rpa_job_id")
        _created_reg_ids.append(reg["reg_id"])

    def test_2_detail_has_rpa_job_id(self, hdr):
        assert self.reg_id
        r = requests.get(
            f"{BASE_URL}/api/admin/statutory/registrations/{self.reg_id}",
            headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["registration"].get("rpa_job_id") or j.get("rpa_job") is not None
        if j["registration"].get("rpa_job_id"):
            TestBulkAndLive.job_id = j["registration"]["rpa_job_id"]

    def test_3_live_endpoint_shape(self, hdr):
        if not self.job_id:
            pytest.skip("no rpa_job_id created (manual mode)")
        r = requests.get(
            f"{BASE_URL}/api/admin/portal-automation/jobs/{self.job_id}/live",
            headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert j["job_id"] == self.job_id
        assert "status" in j
        assert "steps" in j and isinstance(j["steps"], list)
        # live_frame_base64 may be None initially; that's OK
        assert "live_frame_base64" in j

    def test_4_live_404_for_unknown_job(self, hdr):
        r = requests.get(
            f"{BASE_URL}/api/admin/portal-automation/jobs/does_not_exist_zzz/live",
            headers=hdr, timeout=30,
        )
        assert r.status_code == 404


# ---------- 3. OTP endpoint against a fake awaiting_otp job ---------- #
class TestOtpEndpoint:
    fake_job_id = "TEST_JOB_iter196_otp"

    def setup_method(self):
        _mongo.portal_automation_jobs.delete_many({"job_id": self.fake_job_id})
        _mongo.portal_automation_jobs.insert_one({
            "job_id": self.fake_job_id,
            "company_id": COMPANY_ID,
            "status": "awaiting_otp",
            "action_type": "generate_esic",
            "employee_user_id": "u_fake",
            "employee_snapshot": {"name": "TEST OTP EMP"},
            "steps": [{"at": "2026-01-01T00:00:00Z", "note": "waiting for OTP"}],
        })

    def teardown_method(self):
        _mongo.portal_automation_jobs.delete_many({"job_id": self.fake_job_id})

    def test_otp_success(self, hdr):
        r = requests.post(
            f"{BASE_URL}/api/admin/portal-automation/jobs/{self.fake_job_id}/otp",
            json={"code": "123456"}, headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        doc = _mongo.portal_automation_jobs.find_one({"job_id": self.fake_job_id},
                                                    {"_id": 0, "otp_input": 1})
        assert doc.get("otp_input") == "123456"

    def test_otp_bad_code_400(self, hdr):
        r = requests.post(
            f"{BASE_URL}/api/admin/portal-automation/jobs/{self.fake_job_id}/otp",
            json={"code": "ab"}, headers=hdr, timeout=30,
        )
        assert r.status_code == 400
        assert "digit" in r.text.lower() or "otp" in r.text.lower()

    def test_otp_wrong_status_400(self, hdr):
        # flip status
        _mongo.portal_automation_jobs.update_one(
            {"job_id": self.fake_job_id}, {"$set": {"status": "queued"}})
        r = requests.post(
            f"{BASE_URL}/api/admin/portal-automation/jobs/{self.fake_job_id}/otp",
            json={"code": "123456"}, headers=hdr, timeout=30,
        )
        assert r.status_code == 400
        assert "waiting" in r.text.lower() or "otp" in r.text.lower()

    def test_otp_unknown_job_404(self, hdr):
        r = requests.post(
            f"{BASE_URL}/api/admin/portal-automation/jobs/unknown_zzz/otp",
            json={"code": "123456"}, headers=hdr, timeout=30,
        )
        assert r.status_code == 404


# ---------- 4. Live endpoint 403 for foreign company_admin (best-effort) ---------- #
class TestLiveForbidden:
    def test_403_for_foreign_company_admin(self, hdr):
        # find any company_admin whose company differs from COMPANY_ID
        other_admin = _mongo.users.find_one(
            {"role": "company_admin", "company_id": {"$ne": COMPANY_ID}, "password_hash": {"$exists": True}},
            {"_id": 0, "user_id": 1, "email": 1, "company_id": 1},
        )
        if not other_admin:
            pytest.skip("no foreign company_admin available")
        # We can't easily log in as them, so just skip - this is a best-effort check.
        pytest.skip("Cannot obtain foreign company_admin token in this env")


# ---------- cleanup ---------- #
def test_zzz_cleanup(hdr):
    for rid in _created_reg_ids:
        reg = _mongo.statutory_registrations.find_one({"reg_id": rid})
        if reg and reg.get("rpa_job_id"):
            _mongo.portal_automation_jobs.delete_many({"job_id": reg["rpa_job_id"]})
        _mongo.statutory_registrations.delete_one({"reg_id": rid})
    for uid, orig in _touched_users_orig.items():
        update_set = {}
        for key in ("aadhaar_no", "uan_no", "esi_ip_no"):
            if orig.get(key) is None:
                _mongo.users.update_one({"user_id": uid}, {"$unset": {key: ""}})
            else:
                update_set[key] = orig[key]
        if update_set:
            _mongo.users.update_one({"user_id": uid}, {"$set": update_set})
    _mongo.portal_automation_jobs.delete_many({"job_id": {"$regex": "^TEST_JOB_"}})
    print(f"Cleanup removed {len(_created_reg_ids)} regs, restored {len(_touched_users_orig)} users")
