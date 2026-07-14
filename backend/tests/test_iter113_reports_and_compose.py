"""Iter 113 — Backend tests for:
 - Employee Master new fields (blood_group, marital_status, pan_name, upi_id)
 - Alphabetical firm sorting
 - PF/ESI Contribution Sheet (month-wise + yearly + xlsx)
 - Bonus Yearly Summary (+ xlsx)
 - Master Data Report (new columns)
 - Compose notification (all_companies + attachments)
 - Gmail status (no crash when nothing configured)
 - Compliance salary run: father_name/designation/uan_no/esi_ip_no keys present
"""
import base64
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
                      timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# --------------------------- Employee Master new fields ---------------------------
class TestEmployeeMasterNewFields:
    created_user_id = None

    def test_create_employee_with_new_fields(self, hdr):
        phone = "+9199" + str(int(time.time()) % 100000000).zfill(8)
        payload = {
            "company_id": COMPANY_ID,
            "name": f"TEST NF {uuid.uuid4().hex[:5]}",
            "phone": phone,
            "email": f"test_nf_{uuid.uuid4().hex[:6]}@example.com",
            "employee_code": f"TNF{uuid.uuid4().hex[:6].upper()}",
            "blood_group": "B+",
            "marital_status": "Married",
            "pan_name": "TEST NAME",
            "upi_id": "test@upi",
            "designation": "Tester",
            "father_name": "TEST FATHER",
        }
        r = requests.post(f"{BASE_URL}/api/admin/employees", json=payload, headers=hdr, timeout=15)
        assert r.status_code in (200, 201), f"{r.status_code}: {r.text[:400]}"
        data = r.json()
        # Common patterns for id key
        uid = data.get("user_id") or (data.get("user") or {}).get("user_id") or data.get("id")
        assert uid, f"No user_id in response: {data}"
        TestEmployeeMasterNewFields.created_user_id = uid

    def test_profile_returns_new_fields(self, hdr):
        uid = TestEmployeeMasterNewFields.created_user_id
        assert uid, "Need created uid"
        r = requests.get(f"{BASE_URL}/api/admin/employees/{uid}/profile", headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        prof = r.json()
        # profile shape varies — flatten
        emp = prof.get("user") or prof.get("employee") or prof
        # search deeply
        blob = str(prof)
        assert "B+" in blob, f"blood_group missing: {blob[:300]}"
        assert "Married" in blob, f"marital_status missing"
        assert "TEST NAME" in blob, f"pan_name missing"
        assert "test@upi" in blob, f"upi_id missing"

    def test_patch_profile_persists(self, hdr):
        uid = TestEmployeeMasterNewFields.created_user_id
        r = requests.patch(f"{BASE_URL}/api/admin/employees/{uid}/profile",
                           json={"blood_group": "O-"}, headers=hdr, timeout=15)
        assert r.status_code in (200, 204), r.text
        r2 = requests.get(f"{BASE_URL}/api/admin/employees/{uid}/profile", headers=hdr, timeout=15)
        assert r2.status_code == 200
        assert "O-" in str(r2.json())


# --------------------------- Firms alphabetical ---------------------------
class TestFirmsSorted:
    def test_firms_alphabetical(self, hdr):
        r = requests.get(f"{BASE_URL}/api/companies", headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        payload = r.json()
        arr = payload if isinstance(payload, list) else (payload.get("companies") or payload.get("items") or [])
        names = [c.get("name") or "" for c in arr]
        assert names, "No companies returned"
        assert names == sorted(names, key=lambda s: s.lower()), f"Not sorted: {names}"


# --------------------------- Contribution reports ---------------------------
class TestContribution:
    def test_pf_monthly(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/reports/contribution",
                         params={"kind": "pf", "company_id": COMPANY_ID, "month": "2026-06"},
                         headers=hdr, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("run_found") is True, d
        assert "columns" in d and "totals" in d
        assert d["kind"] == "pf"

    def test_esi_monthly(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/reports/contribution",
                         params={"kind": "esi", "company_id": COMPANY_ID, "month": "2026-06"},
                         headers=hdr, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["kind"] == "esi"

    def test_bad_kind_400(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/reports/contribution",
                         params={"kind": "xx", "company_id": COMPANY_ID, "month": "2026-06"},
                         headers=hdr, timeout=15)
        assert r.status_code == 400

    def test_xlsx(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/reports/contribution.xlsx",
                         params={"kind": "pf", "company_id": COMPANY_ID, "month": "2026-06"},
                         headers=hdr, timeout=30)
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers.get("content-type", ""), r.headers

    def test_yearly(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/reports/contribution-yearly",
                         params={"kind": "pf", "company_id": COMPANY_ID, "fy_start_year": 2026},
                         headers=hdr, timeout=25)
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["months"]) == 12
        assert d["months"][0]["label"].startswith("Apr")
        assert d["months"][-1]["label"].startswith("Mar")
        assert "2026-06" in d["months_covered"]


# --------------------------- Bonus Yearly Summary ---------------------------
class TestBonusYearly:
    def test_bonus_json(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/reports/bonus-yearly-summary",
                         params={"company_id": COMPANY_ID, "fy_start_year": 2026},
                         headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "months" in d and "heads" in d and "rows" in d
        # each row should carry father_name/doj keys (may be empty string)
        if d["rows"]:
            r0 = d["rows"][0]
            assert "father_name" in r0
            assert "doj" in r0
            assert "monthly" in r0

    def test_bonus_xlsx(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/reports/bonus-yearly-summary.xlsx",
                         params={"company_id": COMPANY_ID, "fy_start_year": 2026},
                         headers=hdr, timeout=30)
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers.get("content-type", "")


# --------------------------- Master Data Report ---------------------------
class TestMasterData:
    def test_new_columns(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/reports/master-data", headers=hdr, timeout=20)
        assert r.status_code == 200, r.text
        blob = r.json()
        cols_blob = str(blob).lower()
        # Accept either header list or embedded row keys
        for needle in ("blood group", "marital status", "name as per pan", "upi id"):
            assert needle in cols_blob, f"Column '{needle}' missing"


# --------------------------- Compose notifications ---------------------------
class TestCompose:
    def test_compose_all_firms_inapp_only(self, hdr):
        payload = {
            "all_companies": True,
            "all_employees": True,
            "send_email": False,
            "send_inapp": True,
            "subject": "TEST_broadcast",
            "message": "TEST body via automated test",
        }
        r = requests.post(f"{BASE_URL}/api/admin/notifications/compose",
                          json=payload, headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["all_companies"] is True
        assert d["targets"] > 0
        assert d["inapp_sent"] > 0

    def test_compose_with_attachment_no_email(self, hdr):
        payload = {
            "all_companies": True,
            "all_employees": True,
            "send_email": False,
            "send_inapp": True,
            "subject": "TEST_attach",
            "message": "TEST body with attachment",
            "attachments": [
                {"filename": "t.txt", "mime": "text/plain",
                 "content_base64": base64.b64encode(b"hello").decode()},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/admin/notifications/compose",
                          json=payload, headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["attachments"] == 1


# --------------------------- Gmail status (no crash) ---------------------------
class TestGmail:
    def test_status_no_500(self, hdr):
        r = requests.get(f"{BASE_URL}/api/gmail/status", headers=hdr, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("connected") is False


# --------------------------- Compliance Salary Run new fields ---------------------------
class TestComplianceSalaryRun:
    def test_new_run_includes_new_keys(self, hdr):
        r = requests.post(f"{BASE_URL}/api/admin/compliance-salary-runs",
                          json={"month": "2026-06", "company_id": COMPANY_ID},
                          headers=hdr, timeout=60)
        assert r.status_code in (200, 201), f"{r.status_code}: {r.text[:400]}"
        data = r.json()
        rows = data.get("rows") or (data.get("run") or {}).get("rows") or []
        if not rows:
            # fetch latest run
            r2 = requests.get(f"{BASE_URL}/api/admin/compliance-salary-runs",
                              params={"month": "2026-06", "company_id": COMPANY_ID},
                              headers=hdr, timeout=15)
            if r2.status_code == 200:
                jd = r2.json()
                runs = jd.get("runs") or jd if isinstance(jd, list) else []
                if runs:
                    rows = runs[0].get("rows") or []
        assert rows, f"No rows in new run: {str(data)[:300]}"
        r0 = rows[0]
        for k in ("father_name", "designation", "uan_no", "esi_ip_no"):
            assert k in r0, f"Missing '{k}' in row keys: {list(r0.keys())}"
