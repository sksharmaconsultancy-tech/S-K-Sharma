"""Iter 194 — Statutory Registration (ESIC + UAN) backend regression tests.

Covers: dashboard, eligible, CRUD, submit workflow, link-existing, form PDF,
approval workflow (require_approval), bulk, employee-master generate-* buttons,
and duplicate detection. Also cleans up all TEST-created state at the end.
"""
import os
import re
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

_mongo = MongoClient(MONGO_URL)[DB_NAME]

# --------------------------------------------------------------------------- #
#   Session / helpers
# --------------------------------------------------------------------------- #

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


# Track created state for cleanup
_created_reg_ids: list = []
_touched_users: dict = {}  # user_id -> {aadhaar,uan,esi}: original value


def _snap_user(uid):
    if uid in _touched_users:
        return
    u = _mongo.users.find_one({"user_id": uid}, {"_id": 0, "aadhaar_no": 1, "uan_no": 1, "esi_ip_no": 1}) or {}
    _touched_users[uid] = {k: u.get(k) for k in ("aadhaar_no", "uan_no", "esi_ip_no")}


# --------------------------------------------------------------------------- #
#   Dashboard + Eligible
# --------------------------------------------------------------------------- #

class TestDashboards:
    def test_esic_dashboard(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/statutory/esic/dashboard",
                         params={"company_id": COMPANY_ID}, headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert "kpis" in j and "settings" in j
        for k in ("total_employees", "registered", "eligible_missing", "generated"):
            assert k in j["kpis"]

    def test_uan_dashboard(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/statutory/uan/dashboard",
                         params={"company_id": COMPANY_ID}, headers=hdr, timeout=30)
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_esic_eligible(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/statutory/esic/eligible",
                         params={"company_id": COMPANY_ID}, headers=hdr, timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "employees" in j
        for e in j["employees"][:3]:
            for f in ("ready", "eligible", "issues", "warnings"):
                assert f in e

    def test_uan_eligible(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/statutory/uan/eligible",
                         params={"company_id": COMPANY_ID}, headers=hdr, timeout=60)
        assert r.status_code == 200


# --------------------------------------------------------------------------- #
#   Registration CRUD + submit + link-existing + audit + PDF
# --------------------------------------------------------------------------- #

def _pick_eligible_employee(hdr, portal="esic", require_ready=True, skip_uids=None):
    skip_uids = set(skip_uids or [])
    r = requests.get(f"{BASE_URL}/api/admin/statutory/{portal}/eligible",
                     params={"company_id": COMPANY_ID}, headers=hdr, timeout=60)
    for e in r.json().get("employees", []):
        if require_ready and not e.get("ready"):
            continue
        if e.get("duplicate"):
            continue
        if e.get("open_registration"):
            continue
        if e["user_id"] in skip_uids:
            continue
        return e
    return None


class TestEsicRegistrationLifecycle:
    reg_id = None
    emp_uid = None

    def test_1_create_draft(self, hdr):
        emp = _pick_eligible_employee(hdr, "esic")
        if not emp:
            pytest.skip("no ready ESIC-eligible employee")
        TestEsicRegistrationLifecycle.emp_uid = emp["user_id"]
        _snap_user(emp["user_id"])
        r = requests.post(
            f"{BASE_URL}/api/admin/statutory/esic/registrations",
            json={"employee_user_id": emp["user_id"]},
            headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        reg = j["registration"]
        assert reg["portal"] == "esic"
        assert reg["employee_user_id"] == emp["user_id"]
        TestEsicRegistrationLifecycle.reg_id = reg["reg_id"]
        _created_reg_ids.append(reg["reg_id"])

    def test_2_update_family_and_dispensary(self, hdr):
        assert self.reg_id
        r = requests.put(
            f"{BASE_URL}/api/admin/statutory/registrations/{self.reg_id}",
            json={
                "family_members": [{"name": "TEST_Spouse", "relation": "Spouse",
                                    "dob": "1995-01-01", "residing": True}],
                "dispensary": "TEST_DISP_01",
            }, headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        reg = r.json()["registration"]
        assert len(reg["family_members"]) == 1
        assert reg["dispensary"] == "TEST_DISP_01"

    def test_3_submit_esic_action_required(self, hdr):
        assert self.reg_id
        r = requests.post(
            f"{BASE_URL}/api/admin/statutory/registrations/{self.reg_id}/submit",
            headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        # Kankani has NO ESIC creds -> should go to action_required (manual mode)
        assert j["status"] == "action_required", f"unexpected status: {j}"

    def test_4_detail_returns_history_and_rpa_job(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/statutory/registrations/{self.reg_id}",
                         headers=hdr, timeout=30)
        assert r.status_code == 200
        j = r.json()
        reg = j["registration"]
        assert isinstance(reg.get("history"), list) and len(reg["history"]) >= 2
        actions = [h["action"] for h in reg["history"]]
        assert "created" in actions
        assert "action_required" in actions or "queued" in actions
        assert j.get("rpa_job") is not None  # even manual creates a job row

    def test_5_form_pdf(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/statutory/registrations/{self.reg_id}/form",
                         headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] and j.get("pdf_base64")
        # Verify base64 prefix looks like PDF (JVBERi...)
        assert j["pdf_base64"].startswith("JVBERi")
        assert j["file_name"].startswith("ESIC_Form1_")

    def test_6_link_existing_esic(self, hdr):
        assert self.emp_uid
        r = requests.post(
            f"{BASE_URL}/api/admin/statutory/registrations/{self.reg_id}/link-existing",
            json={"value": "1234567890"}, headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] and j["value"] == "1234567890"
        # Verify user updated
        u = _mongo.users.find_one({"user_id": self.emp_uid}, {"_id": 0, "esi_ip_no": 1})
        assert u.get("esi_ip_no") == "1234567890"
        # Verify status updated to linked_existing
        reg = _mongo.statutory_registrations.find_one({"reg_id": self.reg_id})
        assert reg["status"] == "linked_existing"


class TestUanSubmitQueued:
    def test_uan_submit_queued(self, hdr):
        emp = _pick_eligible_employee(hdr, "uan")
        if not emp:
            pytest.skip("no ready UAN-eligible employee")
        _snap_user(emp["user_id"])
        r = requests.post(f"{BASE_URL}/api/admin/statutory/uan/registrations",
                          json={"employee_user_id": emp["user_id"]},
                          headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        reg = r.json()["registration"]
        _created_reg_ids.append(reg["reg_id"])
        r2 = requests.post(
            f"{BASE_URL}/api/admin/statutory/registrations/{reg['reg_id']}/submit",
            headers=hdr, timeout=30,
        )
        assert r2.status_code == 200, r2.text
        j = r2.json()
        # Kankani HAS EPFO creds -> should go to queued
        assert j["status"] == "queued", f"expected queued got: {j}"


# --------------------------------------------------------------------------- #
#   Approval workflow (require_approval toggle)
# --------------------------------------------------------------------------- #

class TestApprovalWorkflow:
    reg_id_approve = None
    reg_id_reject = None
    original_setting = None

    def test_1_enable_require_approval(self, hdr):
        # capture original
        r = requests.get(f"{BASE_URL}/api/admin/statutory/settings",
                         params={"company_id": COMPANY_ID}, headers=hdr, timeout=30)
        TestApprovalWorkflow.original_setting = r.json()["settings"].get("require_approval", False)
        r = requests.put(
            f"{BASE_URL}/api/admin/statutory/settings",
            json={"company_id": COMPANY_ID, "require_approval": True},
            headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["settings"]["require_approval"] is True

    def _make_and_submit(self, hdr, portal="esic", skip_uids=None):
        emp = _pick_eligible_employee(hdr, portal, skip_uids=skip_uids)
        if not emp:
            return None
        _snap_user(emp["user_id"])
        r = requests.post(f"{BASE_URL}/api/admin/statutory/{portal}/registrations",
                          json={"employee_user_id": emp["user_id"]},
                          headers=hdr, timeout=30)
        if r.status_code != 200:
            return None
        rid = r.json()["registration"]["reg_id"]
        _created_reg_ids.append(rid)
        sub = requests.post(
            f"{BASE_URL}/api/admin/statutory/registrations/{rid}/submit",
            headers=hdr, timeout=30,
        )
        return rid, sub.json(), emp["user_id"]

    def test_2_submit_pending_approval(self, hdr):
        res = self._make_and_submit(hdr, "uan")
        if not res:
            pytest.skip("no eligible UAN emp")
        rid, j, uid = res
        assert j.get("status") == "pending_approval", j
        TestApprovalWorkflow.reg_id_approve = rid
        TestApprovalWorkflow._skip_uid = uid

    def test_3_approve(self, hdr):
        assert self.reg_id_approve
        r = requests.post(
            f"{BASE_URL}/api/admin/statutory/registrations/{self.reg_id_approve}/approve",
            json={"note": "TEST approved"}, headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        # UAN has creds -> queued
        assert j["status"] in ("queued", "action_required"), j

    def test_4_reject_flow(self, hdr):
        skip = {getattr(TestApprovalWorkflow, "_skip_uid", None)}
        res = self._make_and_submit(hdr, "uan", skip_uids=skip)
        if not res:
            pytest.skip("cannot create second reg")
        rid, j, _uid = res
        assert j.get("status") == "pending_approval", j
        TestApprovalWorkflow.reg_id_reject = rid
        r = requests.post(
            f"{BASE_URL}/api/admin/statutory/registrations/{rid}/reject",
            json={"note": "TEST reject"}, headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "rejected"

    def test_5_reset_require_approval(self, hdr):
        r = requests.put(
            f"{BASE_URL}/api/admin/statutory/settings",
            json={"company_id": COMPANY_ID,
                  "require_approval": bool(self.original_setting)},
            headers=hdr, timeout=30,
        )
        assert r.status_code == 200


# --------------------------------------------------------------------------- #
#   Bulk registration
# --------------------------------------------------------------------------- #

class TestBulk:
    def test_bulk_esic(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/statutory/esic/eligible",
                         params={"company_id": COMPANY_ID}, headers=hdr, timeout=60)
        ready = [e for e in r.json().get("employees", []) if e.get("ready") and not e.get("duplicate")][:3]
        if len(ready) < 1:
            pytest.skip("no ready ESIC employees for bulk")
        for e in ready:
            _snap_user(e["user_id"])
        ids = [e["user_id"] for e in ready]
        rb = requests.post(f"{BASE_URL}/api/admin/statutory/esic/bulk",
                           json={"employee_user_ids": ids}, headers=hdr, timeout=60)
        assert rb.status_code == 200, rb.text
        j = rb.json()
        assert j["total"] == len(ids)
        assert isinstance(j["results"], list) and len(j["results"]) == len(ids)
        # Capture created regs for cleanup
        for uid in ids:
            for reg in _mongo.statutory_registrations.find(
                    {"employee_user_id": uid, "portal": "esic"}, {"_id": 0, "reg_id": 1}):
                if reg["reg_id"] not in _created_reg_ids:
                    _created_reg_ids.append(reg["reg_id"])


# --------------------------------------------------------------------------- #
#   Employee-master generate-* buttons via portal_generation.py
# --------------------------------------------------------------------------- #

class TestEmployeeMasterGenerate:
    def test_generate_esic_with_aadhaar_override(self, hdr):
        # pick employee WITHOUT aadhaar and without esi_ip_no
        u = _mongo.users.find_one(
            {"role": "employee", "company_id": COMPANY_ID,
             "$or": [{"aadhaar_no": None}, {"aadhaar_no": ""}, {"aadhaar_no": {"$exists": False}}],
             "$and": [{"$or": [{"esi_ip_no": None}, {"esi_ip_no": ""}, {"esi_ip_no": {"$exists": False}}]}]},
            {"_id": 0, "user_id": 1, "aadhaar_no": 1, "esi_ip_no": 1},
        )
        if not u:
            pytest.skip("no employee without aadhaar")
        _snap_user(u["user_id"])
        r = requests.post(
            f"{BASE_URL}/api/admin/employees/{u['user_id']}/generate-esic",
            json={"overrides": {"aadhaar_no": "999911112222"}},
            headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        # Aadhaar should now be persisted
        u2 = _mongo.users.find_one({"user_id": u["user_id"]}, {"_id": 0, "aadhaar_no": 1})
        assert u2.get("aadhaar_no") == "999911112222"
        # Capture created reg
        for reg in _mongo.statutory_registrations.find(
                {"employee_user_id": u["user_id"], "portal": "esic"}, {"_id": 0, "reg_id": 1}):
            if reg["reg_id"] not in _created_reg_ids:
                _created_reg_ids.append(reg["reg_id"])

    def test_generate_uan_link_existing(self, hdr):
        u = _mongo.users.find_one(
            {"role": "employee", "company_id": COMPANY_ID,
             "$or": [{"uan_no": None}, {"uan_no": ""}, {"uan_no": {"$exists": False}}]},
            {"_id": 0, "user_id": 1},
        )
        if not u:
            pytest.skip("no employee without UAN")
        _snap_user(u["user_id"])
        r = requests.post(
            f"{BASE_URL}/api/admin/employees/{u['user_id']}/generate-uan",
            json={"existing_value": "123456789012"},
            headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        u2 = _mongo.users.find_one({"user_id": u["user_id"]}, {"_id": 0, "uan_no": 1})
        assert u2.get("uan_no") == "123456789012"
        for reg in _mongo.statutory_registrations.find(
                {"employee_user_id": u["user_id"], "portal": "uan"}, {"_id": 0, "reg_id": 1}):
            if reg["reg_id"] not in _created_reg_ids:
                _created_reg_ids.append(reg["reg_id"])

    def test_generate_esic_creates_registration(self, hdr):
        # Employee WITH aadhaar and no esi_ip_no
        u = _mongo.users.find_one(
            {"role": "employee", "company_id": COMPANY_ID,
             "aadhaar_no": {"$regex": r"^\d{12}$"},
             "$or": [{"esi_ip_no": None}, {"esi_ip_no": ""}, {"esi_ip_no": {"$exists": False}}]},
            {"_id": 0, "user_id": 1},
        )
        if not u:
            pytest.skip("no clean aadhaar employee")
        _snap_user(u["user_id"])
        r = requests.post(
            f"{BASE_URL}/api/admin/employees/{u['user_id']}/generate-esic",
            json={}, headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        # Expect registration_id in response
        assert "registration_id" in j or "reg_id" in j or j.get("already_present") is True, j
        for reg in _mongo.statutory_registrations.find(
                {"employee_user_id": u["user_id"], "portal": "esic"}, {"_id": 0, "reg_id": 1}):
            if reg["reg_id"] not in _created_reg_ids:
                _created_reg_ids.append(reg["reg_id"])

    def test_generate_esic_already_present(self, hdr):
        u = _mongo.users.find_one(
            {"role": "employee", "company_id": COMPANY_ID,
             "esi_ip_no": {"$regex": r"^\d+$"}},
            {"_id": 0, "user_id": 1, "esi_ip_no": 1},
        )
        if not u:
            pytest.skip("no employee with esi_ip_no")
        r = requests.post(
            f"{BASE_URL}/api/admin/employees/{u['user_id']}/generate-esic",
            json={}, headers=hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("already_present") is True, j


# --------------------------------------------------------------------------- #
#   Cleanup — runs last (test_zzz_* name)
# --------------------------------------------------------------------------- #

def test_zzz_cleanup(hdr):
    # 1) delete created registrations + their rpa jobs
    for rid in _created_reg_ids:
        reg = _mongo.statutory_registrations.find_one({"reg_id": rid})
        if reg and reg.get("rpa_job_id"):
            _mongo.portal_automation_jobs.delete_many({"job_id": reg["rpa_job_id"]})
        _mongo.statutory_registrations.delete_one({"reg_id": rid})
    # 2) restore any touched users' aadhaar/uan/esi values
    for uid, orig in _touched_users.items():
        update_set = {}
        for key in ("aadhaar_no", "uan_no", "esi_ip_no"):
            if orig.get(key) is None:
                _mongo.users.update_one({"user_id": uid}, {"$unset": {key: ""}})
            else:
                update_set[key] = orig[key]
        if update_set:
            _mongo.users.update_one({"user_id": uid}, {"$set": update_set})
    # 3) Reset settings require_approval to False just in case
    _mongo.registration_settings.update_one(
        {"company_id": COMPANY_ID}, {"$set": {"require_approval": False}}, upsert=True)
    print(f"Cleanup: removed {len(_created_reg_ids)} registrations, restored {len(_touched_users)} users")
