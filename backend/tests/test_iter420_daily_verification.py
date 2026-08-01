"""Iter 420 tests — Daily In/Out & OT Verification + bulk-correction bio_code gate
+ firm-master auto-flag."""
import os
import pytest
import requests
from datetime import date as _date

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY = "cmp_527fecdd7c"
ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
ADMIN_PW = "sharma123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PW}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture
def h(token):
    return {"Authorization": f"Bearer {token}"}


TODAY = _date.today().isoformat()


class TestDailyVerification:
    def test_json_report(self, h):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/daily-verification",
            params={"company_id": COMPANY, "date": TODAY, "limit": 50},
            headers=h, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "summary" in d and "rows" in d and "filter_options" in d
        assert d["summary"].get("total_employees", 0) >= 1
        assert isinstance(d["filter_options"].get("machines"), list)
        # capture a row for verify test
        assert len(d["rows"]) > 0
        pytest.first_row = d["rows"][0]
        pytest.summary = d["summary"]

    def test_verify_upsert(self, h):
        row = getattr(pytest, "first_row", None)
        assert row, "requires prior JSON test"
        r = requests.post(
            f"{BASE_URL}/api/admin/reports/daily-verification/verify",
            json={"company_id": COMPANY, "date": TODAY,
                  "user_id": row["user_id"], "verified": True,
                  "remarks": "TEST_iter420"},
            headers=h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("verified") is True
        # verify persisted
        r2 = requests.get(
            f"{BASE_URL}/api/admin/reports/daily-verification",
            params={"company_id": COMPANY, "date": TODAY, "limit": 200,
                    "q": row["employee_code"]}, headers=h, timeout=30)
        assert r2.status_code == 200
        matched = [x for x in r2.json()["rows"] if x["user_id"] == row["user_id"]]
        assert matched and matched[0]["verified"] is True
        assert "TEST_iter420" in matched[0].get("remarks", "")

    def test_verify_undo(self, h):
        row = getattr(pytest, "first_row", None)
        r = requests.post(
            f"{BASE_URL}/api/admin/reports/daily-verification/verify",
            json={"company_id": COMPANY, "date": TODAY,
                  "user_id": row["user_id"], "verified": False, "remarks": ""},
            headers=h, timeout=15)
        assert r.status_code == 200
        assert r.json().get("verified") is False

    def test_drilldown(self, h):
        row = getattr(pytest, "first_row", None)
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/daily-verification/employee",
            params={"company_id": COMPANY, "date": TODAY, "user_id": row["user_id"]},
            headers=h, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "timeline" in d and "history" in d and "employee" in d
        assert len(d["history"]) == 7

    def test_exports(self, h):
        for ext, mime in [("xlsx", "spreadsheet"), ("csv", "csv"),
                          ("pdf", "pdf")]:
            r = requests.get(
                f"{BASE_URL}/api/admin/reports/daily-verification.{ext}",
                params={"company_id": COMPANY, "date": TODAY,
                        "orientation": "landscape"},
                headers=h, timeout=60)
            assert r.status_code == 200, f"{ext}: {r.text[:200]}"
            assert mime in r.headers.get("content-type", "").lower()
            assert len(r.content) > 100

    def test_pdf_portrait(self, h):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/daily-verification.pdf",
            params={"company_id": COMPANY, "date": TODAY,
                    "orientation": "portrait"}, headers=h, timeout=60)
        assert r.status_code == 200
        assert len(r.content) > 100

    def test_exceptions_only(self, h):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/daily-verification",
            params={"company_id": COMPANY, "date": TODAY,
                    "exceptions_only": "true", "limit": 500},
            headers=h, timeout=30)
        assert r.status_code == 200
        for row in r.json()["rows"]:
            assert row["exception"] is True


class TestBulkCorrectionBioCodeGate:
    def test_bio_code_present_when_flag_on(self, h):
        r = requests.get(
            f"{BASE_URL}/api/admin/employees/bulk-correction-fields",
            params={"company_id": COMPANY, "mode": "compliance"},
            headers=h, timeout=20)
        assert r.status_code == 200, r.text
        fields = r.json().get("fields") or r.json().get("columns") or []
        keys = {f.get("key") if isinstance(f, dict) else f for f in fields}
        assert "bio_code" in keys, f"bio_code missing from: {keys}"


class TestFirmMasterAutoFlag:
    def _fetch_company_flag(self, h):
        # Read via a public-ish endpoint — use companies feed
        r = requests.get(f"{BASE_URL}/api/companies", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        for c in r.json().get("companies", r.json() if isinstance(r.json(), list) else []):
            if c.get("company_id") == COMPANY:
                return (((c.get("attendance_policy") or {}).get("policy_master") or {})
                        .get("compliance_present_8hr"))
        return None

    def test_auto_set_when_offline_disabled(self, h):
        # Need to get existing firm-master and PATCH with the merged payload
        cur = requests.get(f"{BASE_URL}/api/admin/firm-master/{COMPANY}",
                           headers=h, timeout=15)
        assert cur.status_code == 200, cur.text
        master = cur.json().get("master") or cur.json()
        sp = dict(master.get("salary_process") or {})
        sp["offline_salary"] = False
        sp["bio_matrix_attendance"] = False

        r = requests.patch(
            f"{BASE_URL}/api/admin/firm-master/{COMPANY}",
            json={"salary_process": sp},
            headers=h, timeout=20)
        assert r.status_code in (200, 204), r.text

        flag = self._fetch_company_flag(h)
        assert flag is True, f"expected auto-True, got {flag}"

        # RESTORE original state: offline_salary=true, bio_matrix_attendance=false
        sp2 = dict(sp)
        sp2["offline_salary"] = True
        sp2["bio_matrix_attendance"] = False
        rest = requests.patch(
            f"{BASE_URL}/api/admin/firm-master/{COMPANY}",
            json={"salary_process": sp2},
            headers=h, timeout=20)
        assert rest.status_code in (200, 204), rest.text


class TestPunchLogRegression:
    def test_punch_log_still_loads(self, h):
        r = requests.get(
            f"{BASE_URL}/api/admin/punch-logs",
            params={"company_id": COMPANY, "date": TODAY, "limit": 10},
            headers=h, timeout=30)
        assert r.status_code == 200, r.text
