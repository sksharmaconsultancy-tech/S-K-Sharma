"""Iter 306 regression: sub-admin delete approval, firm-credentials vault,
punch selfie prefix strip, employee photo -> profile sync,
compliance salary run rate/pf_no/esic_leave_days, register PDF variants.
"""
import os
import base64
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or \
    "https://emplo-connect-1.preview.emergentagent.com"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_ADMIN_PASSWORD = "sharma123"
SUPER_ADMIN_PIN = "246810"
SUB_ADMIN_EMAIL = "testsub@sksharma.co"
SUB_ADMIN_PASSWORD = "testsub123"
KANKANI_COMPANY_ID = "cmp_527fecdd7c"


def _login(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": email, "password": password},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def super_token():
    return _login(SUPER_ADMIN_EMAIL, SUPER_ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def sub_token():
    return _login(SUB_ADMIN_EMAIL, SUB_ADMIN_PASSWORD)


def H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# -------------------- Firm credentials vault --------------------
class TestFirmCredentials:
    def test_wrong_pin_returns_403(self, super_token):
        r = requests.post(f"{BASE_URL}/api/admin/firm-credentials",
                          json={"pin": "000000"}, headers=H(super_token), timeout=20)
        assert r.status_code == 403, r.text

    def test_correct_pin_returns_firms(self, super_token):
        r = requests.post(f"{BASE_URL}/api/admin/firm-credentials",
                          json={"pin": SUPER_ADMIN_PIN}, headers=H(super_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "firms" in data and isinstance(data["firms"], list)
        # find Kankani
        kank = next((f for f in data["firms"]
                     if f.get("company_id") == KANKANI_COMPANY_ID), None)
        assert kank is not None, "Kankani missing from vault list"
        # decrypted (or None) but NOT the mask string
        for key in ("epf_password", "esi_password"):
            v = kank.get(key)
            assert v is None or (isinstance(v, str) and not v.startswith("•")), \
                f"{key} appears masked: {v!r}"

    def test_company_admin_forbidden(self):
        # Try to login as company_admin from creds file; if unknown, skip
        try:
            tok = _login("admin@kankani.local", "Kankani@123")
        except Exception:
            pytest.skip("company_admin login not available")
        r = requests.post(f"{BASE_URL}/api/admin/firm-credentials",
                          json={"pin": SUPER_ADMIN_PIN}, headers=H(tok), timeout=20)
        assert r.status_code == 403


# -------------------- Sub-admin delete -> approval workflow --------------------
class TestSubAdminEmployeeDeleteApproval:
    _created_user_id = None
    _request_id = None

    def _create_throwaway_employee(self, super_token):
        payload = {
            "company_id": KANKANI_COMPANY_ID,
            "email": f"TEST_delflow_{uuid.uuid4().hex[:6]}@test.local",
            "name": "TEST_DELFLOW_EMP",
            "employee_code": f"TESTDEL{uuid.uuid4().hex[:4]}",
            "role": "employee",
            "designation": "Test",
        }
        r = requests.post(f"{BASE_URL}/api/admin/employees",
                          json=payload, headers=H(super_token), timeout=30)
        assert r.status_code in (200, 201), f"create emp failed: {r.status_code} {r.text}"
        data = r.json()
        uid = data.get("user_id") or (data.get("employee") or {}).get("user_id") or data.get("id")
        assert uid, f"no user_id in create response: {data}"
        return uid

    def test_sub_admin_delete_queues_request_not_delete(self, super_token, sub_token):
        uid = self._create_throwaway_employee(super_token)
        TestSubAdminEmployeeDeleteApproval._created_user_id = uid

        r = requests.delete(f"{BASE_URL}/api/admin/employees/{uid}",
                            headers=H(sub_token), timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("approval_required") is True, body
        assert body.get("request_id"), body
        TestSubAdminEmployeeDeleteApproval._request_id = body["request_id"]

        # employee should still exist (via GET user list)
        r2 = requests.get(f"{BASE_URL}/api/admin/employees?company_id={KANKANI_COMPANY_ID}",
                          headers=H(super_token), timeout=30)
        assert r2.status_code == 200
        emps = r2.json().get("employees") or r2.json().get("users") or []
        assert any(e.get("user_id") == uid for e in emps), \
            "employee was deleted but should be queued"

    def test_reject_leaves_employee_intact(self, super_token, sub_token):
        # queue another request, then reject
        uid = self._create_throwaway_employee(super_token)
        r = requests.delete(f"{BASE_URL}/api/admin/employees/{uid}",
                            headers=H(sub_token), timeout=20)
        assert r.status_code == 200
        req_id = r.json()["request_id"]
        rj = requests.post(f"{BASE_URL}/api/admin/deletion-requests/{req_id}/reject",
                           json={"reason": "test"}, headers=H(super_token), timeout=20)
        assert rj.status_code == 200, rj.text
        assert rj.json().get("status") == "rejected"
        # user still exists
        r2 = requests.get(f"{BASE_URL}/api/admin/employees?company_id={KANKANI_COMPANY_ID}",
                          headers=H(super_token), timeout=30)
        assert any(e.get("user_id") == uid for e in
                   (r2.json().get("employees") or r2.json().get("users") or []))
        # Approve to clean it up
        ra = requests.post(f"{BASE_URL}/api/admin/employees/{uid}",
                           headers=H(super_token), timeout=20)  # noqa: N806
        # cleanup via direct super-admin delete
        requests.delete(f"{BASE_URL}/api/admin/employees/{uid}",
                        headers=H(super_token), timeout=20)

    def test_super_admin_approve_deletes_employee(self, super_token):
        req_id = TestSubAdminEmployeeDeleteApproval._request_id
        uid = TestSubAdminEmployeeDeleteApproval._created_user_id
        assert req_id and uid
        ra = requests.post(f"{BASE_URL}/api/admin/deletion-requests/{req_id}/approve",
                           headers=H(super_token), timeout=30)
        assert ra.status_code == 200, ra.text
        assert ra.json().get("status") == "approved"
        # user must be gone
        r2 = requests.get(f"{BASE_URL}/api/admin/employees?company_id={KANKANI_COMPANY_ID}",
                          headers=H(super_token), timeout=30)
        emps = r2.json().get("employees") or r2.json().get("users") or []
        assert not any(e.get("user_id") == uid for e in emps), \
            "employee should be deleted after approval"


# -------------------- Compliance salary run row fields --------------------
class TestComplianceSalaryRun:
    def test_run_has_rates_pfno_esic_leave_days(self, super_token):
        r = requests.post(f"{BASE_URL}/api/admin/compliance-salary-runs",
                          json={"month": "2026-05", "company_id": KANKANI_COMPANY_ID},
                          headers=H(super_token), timeout=120)
        assert r.status_code == 200, r.text
        data = r.json()
        run = data.get("run") or data
        rows = run.get("rows") or data.get("rows") or []
        assert rows, f"no rows in run: {data.keys()}"

        # check pf_no + esic_leave_days on every row
        for row in rows:
            assert "pf_no" in row, f"pf_no missing in row: {list(row)[:20]}"
            assert "esic_leave_days" in row, \
                f"esic_leave_days missing: {list(row)[:20]}"
            assert (row.get("esic_leave_days") or 0) == 0

        # find code 50 (daily 745)
        emp50 = next((r for r in rows if str(r.get("employee_code")) == "50"), None)
        if emp50:
            assert (emp50.get("rate") or 0) > 0, \
                f"code 50 daily rate should be >0, got {emp50.get('rate')}"

        # esic guard: zero if present_days <= 0
        for row in rows:
            pd = row.get("present_days") or 0
            if pd <= 0:
                assert (row.get("esic_employee") or 0) == 0, \
                    f"row has esic on 0 days: {row.get('employee_code')}"


# -------------------- Punch selfie prefix strip --------------------
class TestPunchSelfieStrip:
    """Inject a synthetic attendance record with a data:image/png;base64,XXX
    selfie directly into Mongo, hit the admin & employee selfie endpoints,
    then clean up. This tests the READ-side prefix strip; write-side strip
    is verified by static code review (server.py:9271-9272)."""

    def test_admin_selfie_endpoint_strips_prefix(self, super_token):
        try:
            from pymongo import MongoClient
        except Exception:
            pytest.skip("pymongo not installed")
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "test_database")
        client = MongoClient(mongo_url)
        db = client[db_name]

        rid = f"testrec_{uuid.uuid4().hex[:10]}"
        prefixed = "data:image/png;base64," + _TINY_PNG
        db.attendance.insert_one({
            "record_id": rid,
            "user_id": "user_test_iter306",
            "company_id": KANKANI_COMPANY_ID,
            "selfie_base64": prefixed,
            "kind": "check_in",
            "status": "approved",
        })
        try:
            rs = requests.get(f"{BASE_URL}/api/admin/attendance/{rid}/selfie",
                              headers=H(super_token), timeout=30)
            assert rs.status_code == 200, rs.text
            b64 = rs.json().get("selfie_base64")
            assert b64 and not b64.startswith("data:"), \
                f"prefix not stripped on read: {b64[:30]!r}"
        finally:
            db.attendance.delete_one({"record_id": rid})
            client.close()


# -------------------- Employee photo document -> profile sync --------------------
_TINY_PNG = base64.b64encode(bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4"
    "89000000097048597300000B1300000B1301009A9C1800000010494441545847"
    "63F8FFFF3F03350080D80200D8010142CDDAEC0000000049454E44AE426082"
)).decode()


class TestEmployeePhotoSync:
    def test_photo_upload_syncs_profile_photo(self, super_token):
        # pick any Kankani employee
        rl = requests.get(f"{BASE_URL}/api/admin/employees?company_id={KANKANI_COMPANY_ID}",
                          headers=H(super_token), timeout=30)
        emps = rl.json().get("employees") or rl.json().get("users") or []
        target = next((e for e in emps if e.get("role") != "super_admin"), None)
        assert target
        uid = target["user_id"]

        payload = {
            "category": "photo",
            "mime_type": "image/png",
            "base64": _TINY_PNG,
            "filename": "test_photo.png",
        }
        r = requests.post(f"{BASE_URL}/api/admin/employees/{uid}/documents",
                          json=payload, headers=H(super_token), timeout=30)
        assert r.status_code == 200, r.text
        doc_id = (r.json().get("document") or {}).get("doc_id")
        # verify profile_photo_base64 populated
        gp = requests.get(f"{BASE_URL}/api/admin/users/{uid}/photo",
                          headers=H(super_token), timeout=20)
        assert gp.status_code == 200
        assert gp.json().get("photo_base64"), \
            "profile_photo_base64 not synced from photo document"
        # cleanup
        if doc_id:
            requests.delete(f"{BASE_URL}/api/admin/employees/{uid}/documents/{doc_id}",
                            headers=H(super_token), timeout=20)


# -------------------- Register PDFs (actual + compliance variants) --------------------
class TestRegisterPDFs:
    def _latest_run(self, super_token, endpoint, month="2026-05"):
        r = requests.get(f"{BASE_URL}{endpoint}?company_id={KANKANI_COMPANY_ID}&month={month}",
                         headers=H(super_token), timeout=30)
        assert r.status_code == 200, r.text
        runs = r.json().get("runs") or []
        return runs[0].get("run_id") if runs else None

    def test_actual_salary_register_pdf(self, super_token):
        rid = self._latest_run(super_token, "/api/admin/salary-runs", month="2026-06")
        if not rid:
            rid = self._latest_run(super_token, "/api/admin/salary-runs", month="2026-07")
        if not rid:
            pytest.skip("no actual salary run available")
        r = requests.get(f"{BASE_URL}/api/admin/salary-runs/{rid}/register.pdf",
                         headers=H(super_token), timeout=60)
        assert r.status_code == 200, r.text[:200]
        assert r.content[:4] == b"%PDF", "not a PDF"

    def test_compliance_register_pdf_variant_1(self, super_token):
        rid = self._latest_run(super_token, "/api/admin/compliance-salary-runs")
        if not rid:
            pytest.skip("no compliance run for 2026-05")
        r = requests.get(f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}/register.pdf?variant=1",
                         headers=H(super_token), timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:4] == b"%PDF"

    def test_compliance_register_pdf_variant_2(self, super_token):
        rid = self._latest_run(super_token, "/api/admin/compliance-salary-runs")
        if not rid:
            pytest.skip("no compliance run for 2026-05")
        r = requests.get(f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}/register.pdf?variant=2",
                         headers=H(super_token), timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:4] == b"%PDF"
