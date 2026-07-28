"""Iter 357 backend tests — Labour Statistics, Annual Returns, Factory Compliance."""
import os
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"
MONTH = "2026-07"
FY = 2026


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE}/api/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
                      timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def hdrs(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- AUTH GATING ----------
class TestAuthGating:
    def test_labour_stats_no_auth_401(self):
        r = requests.get(f"{BASE}/api/admin/labour-stats/dashboard?company_id={COMPANY_ID}", timeout=15)
        assert r.status_code == 401

    def test_annual_returns_no_auth_401(self):
        r = requests.get(f"{BASE}/api/admin/annual-returns/list", timeout=15)
        assert r.status_code == 401

    def test_factory_no_auth_401(self):
        r = requests.get(f"{BASE}/api/admin/factory/kinds", timeout=15)
        assert r.status_code == 401


# ---------- LABOUR STATISTICS ----------
class TestLabourStats:
    def test_dashboard(self, hdrs):
        r = requests.get(f"{BASE}/api/admin/labour-stats/dashboard",
                         params={"company_id": COMPANY_ID, "month": MONTH},
                         headers=hdrs, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("kpis", "insights", "department_strength", "age_distribution"):
            assert k in j, f"missing {k}"
        assert "total_employees" in j["kpis"]
        assert isinstance(j["insights"], list) and len(j["insights"]) >= 1

    @pytest.mark.parametrize("kind", ["department", "category", "monthly-return", "welfare"])
    def test_registers_json(self, hdrs, kind):
        r = requests.get(f"{BASE}/api/admin/labour-stats/{kind}",
                         params={"company_id": COMPANY_ID, "month": MONTH},
                         headers=hdrs, timeout=45)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "columns" in j and "rows" in j
        assert isinstance(j["columns"], list) and len(j["columns"]) >= 2
        assert isinstance(j["rows"], list)

    def test_turnover(self, hdrs):
        r = requests.get(f"{BASE}/api/admin/labour-stats/turnover",
                         params={"company_id": COMPANY_ID, "fy_start_year": FY},
                         headers=hdrs, timeout=45)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "rows" in j and "department_attrition" in j
        assert j["fy_start_year"] == FY

    def test_department_xlsx(self, hdrs):
        r = requests.get(f"{BASE}/api/admin/labour-stats/department.xlsx",
                         params={"company_id": COMPANY_ID, "month": MONTH},
                         headers=hdrs, timeout=60)
        assert r.status_code == 200, r.text
        assert "spreadsheet" in r.headers.get("content-type", "").lower()
        assert len(r.content) > 500

    def test_department_pdf(self, hdrs):
        r = requests.get(f"{BASE}/api/admin/labour-stats/department.pdf",
                         params={"company_id": COMPANY_ID, "month": MONTH},
                         headers=hdrs, timeout=60)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"


# ---------- ANNUAL RETURNS ----------
class TestAnnualReturns:
    def test_list(self, hdrs):
        r = requests.get(f"{BASE}/api/admin/annual-returns/list", headers=hdrs, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert len(j["returns"]) == 8

    def test_dashboard(self, hdrs):
        r = requests.get(f"{BASE}/api/admin/annual-returns/dashboard",
                         params={"company_id": COMPANY_ID, "fy_start_year": FY},
                         headers=hdrs, timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "compliance_pct" in j and "validations" in j and "returns" in j
        assert len(j["returns"]) == 8

    @pytest.mark.parametrize("kind", ["minimum-wages", "payment-of-wages", "bonus",
                                       "equal-remuneration", "employment-statistics",
                                       "social-security", "lwf", "pt"])
    def test_returns_json(self, hdrs, kind):
        r = requests.get(f"{BASE}/api/admin/annual-returns/{kind}",
                         params={"company_id": COMPANY_ID, "fy_start_year": FY},
                         headers=hdrs, timeout=60)
        assert r.status_code == 200, f"{kind}: {r.text[:200]}"
        j = r.json()
        assert "columns" in j and "rows" in j
        assert isinstance(j["columns"], list)

    def test_bonus_xlsx(self, hdrs):
        r = requests.get(f"{BASE}/api/admin/annual-returns/bonus.xlsx",
                         params={"company_id": COMPANY_ID, "fy_start_year": FY},
                         headers=hdrs, timeout=60)
        assert r.status_code == 200
        assert len(r.content) > 500

    def test_pow_pdf(self, hdrs):
        r = requests.get(f"{BASE}/api/admin/annual-returns/payment-of-wages.pdf",
                         params={"company_id": COMPANY_ID, "fy_start_year": FY},
                         headers=hdrs, timeout=60)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"


# ---------- FACTORY & BOILERS ----------
class TestFactoryCompliance:
    def test_kinds(self, hdrs):
        r = requests.get(f"{BASE}/api/admin/factory/kinds", headers=hdrs, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "masters" in j and "computed" in j
        computed_kinds = [c["kind"] for c in j["computed"]]
        assert "present-absent" in computed_kinds
        assert len(j["masters"]) >= 10

    def test_dashboard(self, hdrs):
        r = requests.get(f"{BASE}/api/admin/factory/dashboard",
                         params={"company_id": COMPANY_ID}, headers=hdrs, timeout=15)
        assert r.status_code == 200
        j = r.json()
        for k in ("compliance_pct", "risk_pct", "alerts"):
            assert k in j

    @pytest.mark.parametrize("kind,params", [
        ("daily-attendance", {}),
        ("present-absent", {"month": MONTH}),
        ("muster-roll", {}),
        ("working-hours", {"month": MONTH}),
        ("strength", {}),
    ])
    def test_computed_registers(self, hdrs, kind, params):
        p = dict(params, company_id=COMPANY_ID)
        r = requests.get(f"{BASE}/api/admin/factory/register/{kind}",
                         params=p, headers=hdrs, timeout=60)
        assert r.status_code == 200, f"{kind}: {r.text[:200]}"
        j = r.json()
        assert "columns" in j and "rows" in j

    def test_present_absent_row_count(self, hdrs):
        r = requests.get(f"{BASE}/api/admin/factory/register/present-absent",
                         params={"company_id": COMPANY_ID, "month": MONTH},
                         headers=hdrs, timeout=60)
        assert r.status_code == 200
        rows = r.json().get("rows", [])
        # Test credentials mention 127 employees for Kankani
        assert len(rows) >= 100, f"expected >=100 rows for employee-wise report, got {len(rows)}"

    def test_crud_license_record_and_dashboard_alert(self, hdrs):
        # CREATE
        payload = {"company_id": COMPANY_ID, "kind": "license",
                   "data": {"license_no": "TEST_LIC_357",
                            "license_type": "Factory Act",
                            "validity": "2026-08-01",
                            "remarks": "iter357 backend test"}}
        r = requests.post(f"{BASE}/api/admin/factory/records", json=payload,
                          headers=hdrs, timeout=30)
        assert r.status_code == 200, r.text
        rid = r.json()["record_id"]
        try:
            # LIST includes it
            r2 = requests.get(f"{BASE}/api/admin/factory/records",
                              params={"kind": "license", "company_id": COMPANY_ID},
                              headers=hdrs, timeout=15)
            assert r2.status_code == 200
            recs = r2.json()["records"]
            assert any(x["record_id"] == rid for x in recs)

            # REGISTER includes it
            r3 = requests.get(f"{BASE}/api/admin/factory/register/license",
                              params={"company_id": COMPANY_ID}, headers=hdrs, timeout=15)
            assert r3.status_code == 200
            assert any(row.get("license_no") == "TEST_LIC_357"
                       for row in r3.json()["rows"])

            # Dashboard alert (validity 2026-08-01 is <=45 days out or past → DUE SOON/OVERDUE)
            r4 = requests.get(f"{BASE}/api/admin/factory/dashboard",
                              params={"company_id": COMPANY_ID}, headers=hdrs, timeout=15)
            assert r4.status_code == 200
            alerts = r4.json().get("alerts", [])
            match = [a for a in alerts if a.get("ref") == "TEST_LIC_357"]
            assert match, f"no alert for TEST_LIC_357; alerts={alerts[:5]}"
            assert match[0]["status"] in ("DUE SOON", "OVERDUE")
        finally:
            # DELETE
            rd = requests.delete(f"{BASE}/api/admin/factory/records/{rid}",
                                 headers=hdrs, timeout=15)
            assert rd.status_code == 200

    def test_strength_pdf(self, hdrs):
        r = requests.get(f"{BASE}/api/admin/factory/register/strength.pdf",
                         params={"company_id": COMPANY_ID}, headers=hdrs, timeout=60)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"
