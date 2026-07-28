"""Iter 356 — Employee-Wise Yearly Payroll Register backend tests."""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"
FY = 2026


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok, f"no token in response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── JSON base ─────────────────────────────────────────────────────────────────
class TestPayrollRegisterJSON:
    def test_base_json(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/payroll-register",
            params={"company_id": COMPANY_ID, "fy_start_year": FY, "limit": 5},
            headers=headers, timeout=60,
        )
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        # shape
        assert d["total_employees"] > 0, f"no employees: {d}"
        assert len(d["months"]) == 12, f"expected 12 months got {len(d['months'])}"
        assert d["months"][0]["key"] == f"{FY}-04"
        assert d["months"][-1]["key"] == f"{FY + 1}-03"
        assert isinstance(d["heads"], list) and len(d["heads"]) >= 5
        assert isinstance(d["rows"], list) and len(d["rows"]) <= 5
        # months_covered should contain runs Apr..Jul 2026
        expected = {f"{FY}-04", f"{FY}-05", f"{FY}-06", f"{FY}-07"}
        got = set(d["months_covered"])
        assert expected.issubset(got), f"missing coverage. expected superset of {expected}, got {got}"
        # rows shape
        row = d["rows"][0]
        for k in ("sr", "user_id", "employee_code", "name", "months", "totals", "flags"):
            assert k in row, f"row missing {k}"
        # grand totals present
        assert "grand" in d
        assert d["grand"].get("gross", 0) >= 0

    # ── pagination ───────────────────────────────────────────────────────────
    def test_pagination(self, headers):
        r1 = requests.get(
            f"{BASE_URL}/api/admin/reports/payroll-register",
            params={"company_id": COMPANY_ID, "fy_start_year": FY, "skip": 0, "limit": 5},
            headers=headers, timeout=60,
        )
        r2 = requests.get(
            f"{BASE_URL}/api/admin/reports/payroll-register",
            params={"company_id": COMPANY_ID, "fy_start_year": FY, "skip": 5, "limit": 5},
            headers=headers, timeout=60,
        )
        assert r1.status_code == 200 and r2.status_code == 200
        ids1 = [row["user_id"] for row in r1.json()["rows"]]
        ids2 = [row["user_id"] for row in r2.json()["rows"]]
        assert ids1 and ids2, "empty pages"
        assert set(ids1).isdisjoint(set(ids2)), f"pagination overlap: {ids1} vs {ids2}"

    # ── filters ──────────────────────────────────────────────────────────────
    def test_status_active_filter(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/payroll-register",
            params={"company_id": COMPANY_ID, "fy_start_year": FY,
                    "status": "active", "limit": 10},
            headers=headers, timeout=60,
        )
        assert r.status_code == 200, r.text[:200]
        assert r.json()["total_employees"] >= 0

    def test_department_filter(self, headers):
        # first find any dept name from the data
        base = requests.get(
            f"{BASE_URL}/api/admin/reports/payroll-register",
            params={"company_id": COMPANY_ID, "fy_start_year": FY, "limit": 25},
            headers=headers, timeout=60,
        ).json()
        depts = {row.get("department") for row in base["rows"] if row.get("department")}
        if not depts:
            pytest.skip("no departments in data to test filter")
        dept = next(iter(depts))
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/payroll-register",
            params={"company_id": COMPANY_ID, "fy_start_year": FY,
                    "department": dept, "limit": 25},
            headers=headers, timeout=60,
        )
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert rows, "department filter returned no rows"
        for row in rows:
            assert dept.lower() in str(row.get("department") or "").lower(), \
                f"unexpected dept {row.get('department')} for filter {dept}"

    # ── multi-FY ─────────────────────────────────────────────────────────────
    def test_multi_fy_months(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/payroll-register",
            params={"company_id": COMPANY_ID, "fy_start_year": FY,
                    "fy_years": 2, "limit": 3},
            headers=headers, timeout=60,
        )
        assert r.status_code == 200
        assert len(r.json()["months"]) == 24

    # ── auth ─────────────────────────────────────────────────────────────────
    def test_auth_required(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/payroll-register",
            params={"company_id": COMPANY_ID, "fy_start_year": FY},
            timeout=30,
        )
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"


# ── exports ───────────────────────────────────────────────────────────────────
class TestPayrollRegisterExports:
    def test_xlsx(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/payroll-register.xlsx",
            params={"company_id": COMPANY_ID, "fy_start_year": FY},
            headers=headers, timeout=120,
        )
        assert r.status_code == 200, r.text[:200]
        ct = r.headers.get("content-type", "")
        assert "spreadsheet" in ct, f"unexpected ct: {ct}"
        assert len(r.content) > 20_000, f"xlsx too small: {len(r.content)}"
        assert r.content[:2] == b"PK", "not a zip/xlsx"

    def test_pdf(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/payroll-register.pdf",
            params={"company_id": COMPANY_ID, "fy_start_year": FY},
            headers=headers, timeout=180,
        )
        assert r.status_code == 200, r.text[:200]
        ct = r.headers.get("content-type", "")
        assert "pdf" in ct, f"unexpected ct: {ct}"
        assert len(r.content) > 50_000, f"pdf too small: {len(r.content)}"
        assert r.content[:4] == b"%PDF", "not a PDF"
