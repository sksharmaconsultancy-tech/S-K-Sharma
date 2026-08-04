"""Iter 485 backend tests — Firm Master v2 (ERP redesign), sub-admin
scope regression, and Compliance Master Snapshot lifecycle."""
import os
import uuid
import pytest
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
COMPANY_ID = "cmp_527fecdd7c"  # Kankani Enterprises
TEST_MONTH = "2026-06"
SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PWD = "sharma123"


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient("mongodb://localhost:27017")
    yield client["test_database"]
    client.close()


@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{API}/auth/admin-password-login",
                      json={"email": SUPER_EMAIL, "password": SUPER_PWD}, timeout=15)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def hdr(super_token):
    return {"Authorization": f"Bearer {super_token}"}


# --------------------------------------------------- BACKEND 1: Login
class TestLogin:
    def test_login_success(self, super_token):
        assert super_token
        assert isinstance(super_token, str) and len(super_token) > 8


# --------------------------------------------------- BACKEND 2: GET firm-master (general seeded)
class TestFirmMasterGeneral:
    def test_general_section_seeded(self, hdr):
        r = requests.get(f"{API}/admin/firm-master/{COMPANY_ID}", headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "master" in data
        gen = data["master"].get("general") or {}
        assert gen.get("company_name"), "general.company_name empty"
        # currency & timezone must default to India
        assert gen.get("currency") == "INR"
        assert gen.get("timezone") == "Asia/Kolkata"
        assert "company_status" in gen
        # company_code should have some value (KEPS per seed)
        assert gen.get("company_code")


# --------------------------------------------------- BACKEND 3: PATCH firm-master validation
class TestFirmMasterValidation:
    def test_future_start_date_rejected(self, hdr):
        payload = {"general": {"company_name": "Kankani Enterprises",
                               "firm_start_date": "2099-01-01"}}
        r = requests.patch(f"{API}/admin/firm-master/{COMPANY_ID}",
                           headers=hdr, json=payload, timeout=15)
        assert r.status_code == 400, f"Expected 400 got {r.status_code}: {r.text}"
        assert "future" in r.text.lower()

    def test_duplicate_company_code_rejected(self, hdr, mongo):
        # Find some OTHER firm's code
        other = mongo.companies.find_one(
            {"company_id": {"$ne": COMPANY_ID}, "company_code": {"$exists": True, "$ne": None}},
            {"_id": 0, "company_code": 1, "name": 1})
        if not other:
            pytest.skip("No other firm with company_code to clash against")
        clash_code = other["company_code"]
        payload = {"general": {"company_name": "Kankani Enterprises",
                               "company_code": clash_code}}
        r = requests.patch(f"{API}/admin/firm-master/{COMPANY_ID}",
                           headers=hdr, json=payload, timeout=15)
        assert r.status_code == 400, f"Expected 400 got {r.status_code}: {r.text}"
        assert "already used" in r.text.lower() or "clash" in r.text.lower() or clash_code.lower() in r.text.lower()


# --------------------------------------------------- BACKEND 4: Contacts
class TestContacts:
    def test_get_contacts(self, hdr):
        r = requests.get(f"{API}/admin/firm-master/{COMPANY_ID}/contacts",
                         headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "contacts" in j and isinstance(j["contacts"], list)
        assert "contact_types" in j

    def test_put_two_contacts_ok(self, hdr, mongo):
        # snapshot existing so we restore
        original = list(mongo.company_contacts.find({"company_id": COMPANY_ID}))
        payload = {"contacts": [
            {"contact_type": "primary", "name": "TEST Primary",
             "designation": "Owner", "mobile": "9000000001",
             "email": "test_primary_iter485@example.com",
             "country_code": "+91", "sort_order": 0,
             "recipient_permissions": {"payroll_reports": True}},
            {"contact_type": "hr", "name": "TEST HR",
             "designation": "HR Head", "mobile": "9000000002",
             "email": "test_hr_iter485@example.com",
             "country_code": "+91", "sort_order": 1,
             "recipient_permissions": {"attendance_alerts": True}},
        ]}
        r = requests.put(f"{API}/admin/firm-master/{COMPANY_ID}/contacts",
                         headers=hdr, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("ok") is True
        assert len(j.get("contacts", [])) == 2
        # RESTORE
        mongo.company_contacts.delete_many({"company_id": COMPANY_ID})
        if original:
            for d in original:
                d.pop("_id", None)
            mongo.company_contacts.insert_many(original)

    def test_put_duplicate_email_rejected(self, hdr, mongo):
        original = list(mongo.company_contacts.find({"company_id": COMPANY_ID}))
        payload = {"contacts": [
            {"contact_type": "primary", "name": "A",
             "mobile": "9000000010",
             "email": "dupe_iter485@example.com",
             "country_code": "+91", "sort_order": 0,
             "recipient_permissions": {}},
            {"contact_type": "hr", "name": "B",
             "mobile": "9000000011",
             "email": "dupe_iter485@example.com",
             "country_code": "+91", "sort_order": 1,
             "recipient_permissions": {}},
        ]}
        r = requests.put(f"{API}/admin/firm-master/{COMPANY_ID}/contacts",
                         headers=hdr, json=payload, timeout=15)
        assert r.status_code == 400, f"Expected 400 got {r.status_code}: {r.text}"
        assert "duplicate" in r.text.lower() or "unique" in r.text.lower()
        # restore any accidental change
        mongo.company_contacts.delete_many(
            {"company_id": COMPANY_ID,
             "email": {"$in": ["dupe_iter485@example.com"]}})


# --------------------------------------------------- BACKEND 5: Audit + Export
class TestAuditExport:
    def test_audit_list(self, hdr):
        r = requests.get(f"{API}/admin/firm-master/{COMPANY_ID}/audit",
                         headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        assert "entries" in r.json()
        assert isinstance(r.json()["entries"], list)

    def test_export(self, hdr):
        r = requests.get(f"{API}/admin/firm-master/{COMPANY_ID}/export",
                         headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "firm_master" in j
        assert "contacts" in j
        assert "company" in j
        assert "exported_at" in j


# --------------------------------------------------- BACKEND 6: Master snapshot lifecycle
class TestMasterSnapshotLifecycle:
    """Full lifecycle test on TEST_MONTH 2026-06. Cleanup mandatory."""

    @classmethod
    def _cleanup_month(cls, mongo):
        mongo.compliance_salary_runs.delete_many(
            {"company_id": COMPANY_ID, "month": TEST_MONTH})
        mongo.compliance_master_snapshots.delete_many(
            {"company_id": COMPANY_ID, "month": TEST_MONTH})

    def test_full_lifecycle(self, hdr, mongo):
        # Pre-clean any leftover
        self._cleanup_month(mongo)

        # Pick a STAFF employee under Kankani to mutate
        emp = mongo.users.find_one(
            {"role": "employee", "company_id": COMPANY_ID,
             "employee_type": {"$in": ["Staff", "STAFF", "staff"]}},
            {"_id": 0, "user_id": 1, "compliance_gross": 1,
             "basic_master": 1, "gross_master": 1})
        if not emp:
            pytest.skip("No STAFF employee under Kankani for snapshot test")
        user_id = emp["user_id"]
        original_compliance_gross = emp.get("compliance_gross")

        try:
            # (a) POST generate -> master_snapshot created v1
            r = requests.post(f"{API}/admin/compliance-salary-runs",
                              headers=hdr,
                              json={"month": TEST_MONTH,
                                    "company_id": COMPANY_ID,
                                    "employee_type": "STAFF"},
                              timeout=90)
            assert r.status_code == 200, f"generate: {r.status_code} {r.text[:500]}"
            run = r.json().get("run") or r.json()
            run_id = run["run_id"]
            snap = run.get("master_snapshot") or {}
            assert snap.get("created") is True, f"snapshot.created expected True, got {snap}"
            assert snap.get("version") == 1, f"expected v1 got {snap.get('version')}"

            # capture the employee's row values pre-mutation
            rows = run.get("rows") or []
            emp_row_pre = next((r for r in rows if r.get("user_id") == user_id), None)
            assert emp_row_pre, f"employee {user_id} not in run rows"
            gross_pre = emp_row_pre.get("gross_master") or emp_row_pre.get("gross")
            basic_pre = emp_row_pre.get("basic_master") or emp_row_pre.get("basic")

            # (b) mutate live compliance_gross
            mongo.users.update_one({"user_id": user_id},
                                   {"$set": {"compliance_gross": 99999}})

            # (c) reprocess — must remain frozen
            r2 = requests.post(f"{API}/admin/compliance-salary-runs/{run_id}/reprocess",
                               headers=hdr, timeout=90)
            assert r2.status_code == 200, r2.text[:400]
            run2 = r2.json().get("run") or r2.json()
            row2 = next((r for r in (run2.get("rows") or []) if r.get("user_id") == user_id), None)
            assert row2
            gross_post = row2.get("gross_master") or row2.get("gross")
            basic_post = row2.get("basic_master") or row2.get("basic")
            assert gross_post == gross_pre, f"gross changed on reprocess: {gross_pre} → {gross_post}"
            assert basic_post == basic_pre, f"basic changed on reprocess: {basic_pre} → {basic_post}"

            # (d) delete + regenerate — still frozen
            r3 = requests.delete(f"{API}/admin/compliance-salary-runs/{run_id}",
                                 headers=hdr, timeout=30)
            assert r3.status_code in (200, 204), r3.text[:400]
            r4 = requests.post(f"{API}/admin/compliance-salary-runs",
                               headers=hdr,
                               json={"month": TEST_MONTH,
                                     "company_id": COMPANY_ID,
                                     "employee_type": "STAFF"},
                               timeout=90)
            assert r4.status_code == 200, r4.text[:400]
            run3 = r4.json().get("run") or r4.json()
            run_id2 = run3["run_id"]
            snap3 = run3.get("master_snapshot") or {}
            assert snap3.get("used") is True or snap3.get("version") == 1, \
                f"expected snapshot.used=True/v1 got {snap3}"
            row3 = next((r for r in (run3.get("rows") or []) if r.get("user_id") == user_id), None)
            assert row3
            assert (row3.get("gross_master") or row3.get("gross")) == gross_pre, \
                "gross changed after delete+regenerate"

            # (e) refresh-master-snapshot -> v2
            r5 = requests.post(
                f"{API}/admin/compliance-salary-runs/{run_id2}/refresh-master-snapshot",
                headers=hdr, json={"reason": "test iter485"}, timeout=90)
            assert r5.status_code == 200, r5.text[:400]
            j5 = r5.json()
            snap5 = j5.get("snapshot") or {}
            assert snap5.get("old_version") == 1
            assert snap5.get("new_version") == 2

            # (f) master-snapshot-info -> exists version 2
            r6 = requests.get(
                f"{API}/admin/compliance-salary-runs/{run_id2}/master-snapshot-info",
                headers=hdr, timeout=15)
            assert r6.status_code == 200, r6.text[:400]
            j6 = r6.json()
            assert j6.get("exists") is True
            assert j6.get("version") == 2

        finally:
            # CLEANUP: restore employee & purge test-month artifacts
            if original_compliance_gross is None:
                mongo.users.update_one({"user_id": user_id},
                                       {"$unset": {"compliance_gross": ""}})
            else:
                mongo.users.update_one({"user_id": user_id},
                                       {"$set": {"compliance_gross": original_compliance_gross}})
            self._cleanup_month(mongo)


# --------------------------------------------------- BACKEND 7: sub-admin scope
class TestSubAdminScopeFix:
    def test_restricted_sub_admin_cannot_see_kankani(self, hdr, mongo):
        # Find some OTHER firm id (NOT Kankani)
        other = mongo.companies.find_one(
            {"company_id": {"$ne": COMPANY_ID}}, {"_id": 0, "company_id": 1})
        if not other:
            pytest.skip("Need at least one other firm for scope test")
        other_id = other["company_id"]

        sub_uid = f"user_test485_{uuid.uuid4().hex[:6]}"
        sub_token = f"tok_test485_{uuid.uuid4().hex[:10]}"
        try:
            mongo.users.insert_one({
                "user_id": sub_uid,
                "email": f"{sub_uid}@test.local",
                "role": "sub_admin",
                "name": "TEST Sub Admin iter485",
                "sub_admin_company_scope": "restricted",
                "sub_admin_company_ids": [other_id],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            mongo.user_sessions.insert_one({
                "session_token": sub_token,
                "user_id": sub_uid,
                "expires_at": (datetime.now(timezone.utc)).replace(year=2099).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            sub_hdr = {"Authorization": f"Bearer {sub_token}"}

            # With ?company_id=Kankani -> should be empty (or blocked)
            r1 = requests.get(f"{API}/admin/attendance/today?company_id={COMPANY_ID}",
                              headers=sub_hdr, timeout=20)
            assert r1.status_code in (200, 403), r1.text[:400]
            if r1.status_code == 200:
                j1 = r1.json()
                present = j1.get("present") or j1.get("employees") or []
                # None of them should belong to COMPANY_ID (Kankani)
                bad = [p for p in present if p.get("company_id") == COMPANY_ID]
                assert not bad, f"Sub-admin restricted to {other_id} but saw Kankani rows: {len(bad)}"

            # Without ?company_id → only allowed firm rows
            r2 = requests.get(f"{API}/admin/attendance/today", headers=sub_hdr, timeout=20)
            assert r2.status_code == 200, r2.text[:400]
            j2 = r2.json()
            present2 = j2.get("present") or j2.get("employees") or []
            bad2 = [p for p in present2 if p.get("company_id") == COMPANY_ID]
            assert not bad2, f"Sub-admin without company_id filter still leaked Kankani rows: {len(bad2)}"
        finally:
            mongo.users.delete_one({"user_id": sub_uid})
            mongo.user_sessions.delete_many({"session_token": sub_token})


# --------------------------------------------------- BACKEND 8: regression
class TestRegression:
    def test_version_iter485(self, hdr):
        r = requests.get(f"{API}/version", timeout=10)
        assert r.status_code == 200
        j = r.json()
        # Accept iteration key or version string containing 485
        v = j.get("iteration") or j.get("version") or ""
        assert "485" in str(v), f"expected iteration 485, got {j}"

    def test_compliance_run_list(self, hdr):
        r = requests.get(f"{API}/admin/compliance-salary-runs",
                         headers=hdr, timeout=20)
        assert r.status_code == 200, r.text[:400]

    def test_attendance_today_super(self, hdr):
        r = requests.get(f"{API}/admin/attendance/today", headers=hdr, timeout=20)
        assert r.status_code == 200, r.text[:400]
