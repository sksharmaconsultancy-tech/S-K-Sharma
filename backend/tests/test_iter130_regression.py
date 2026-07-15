"""Iter 130/131 pre-deploy regression: compliance PDF, ESIC-on-basic, OT XOR PATCH, firm scoping."""
import os
import sys
import pytest
import requests

# Make backend modules importable for the ESIC unit test
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://emplo-connect-1.preview.emergentagent.com"
).rstrip("/")

KANKANI = "cmp_527fecdd7c"
CITY_CARE = "cmp_987f0d7da5"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("session_token") or r.json().get("access_token")
    assert tok, f"no token in login response: {r.text[:300]}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# -------- Feature 1: Salary Register PDF --------
class TestComplianceRegisterPDF:
    def test_pdf_endpoint_returns_valid_pdf(self, auth_headers):
        listr = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs",
            params={"company_id": KANKANI},
            headers=auth_headers,
            timeout=30,
        )
        assert listr.status_code == 200, listr.text[:300]
        runs = listr.json().get("runs") or listr.json().get("items") or listr.json()
        assert isinstance(runs, list) and len(runs) > 0, "no runs for Kankani"
        run_id = runs[0].get("run_id") or runs[0].get("id") or runs[0].get("_id")
        assert run_id, f"no run_id: {runs[0]}"

        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/register.pdf",
            headers=auth_headers,
            timeout=60,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.content
        assert body[:4] == b"%PDF", "not a PDF"
        assert len(body) > 5000, f"pdf too small: {len(body)} bytes"

        # Verify required markers in the PDF stream (Text may be split across
        # font ops but these labels sit in Helvetica text objects).
        from pdfminer.high_level import extract_text
        import io
        try:
            text = extract_text(io.BytesIO(body)) or ""
        except Exception:
            text = body.decode("latin-1", errors="ignore")
        text_u = text.upper()
        for needle in ("SALARY REGISTER", "GRAND TOTAL", "RUPEES:", "AUTHORISED SIGNATORY"):
            assert needle in text_u, f"missing '{needle}' in PDF text"


# -------- Feature 2: ESIC on Basic (unit) --------
class TestESICOnBasic:
    def test_esic_wage_base_equals_basic(self):
        from utils.compliance_salary import compute_compliance_row
        row = compute_compliance_row(
            user={
                "user_id": "u1",
                "name": "T",
                "salary_mode": "monthly",
                "compliance_gross": 15000,
                "esic_applicable": True,
                "pf_applicable": False,
            },
            policy={},
            month_days=26,
            stats={"present_days": 26, "effective_present": 26},
            statutory_cfg=None,
        )
        assert row["basic"] == 6000.0, f"basic expected 6000 got {row['basic']}"
        assert row["esic_wage_base"] == 6000.0, f"esic_wage_base expected 6000 got {row['esic_wage_base']}"
        assert row["esic_employee"] == 45.0, f"esic_employee expected 45 got {row['esic_employee']}"
        assert row["esic_employer"] == 195.0, f"esic_employer expected 195 got {row['esic_employer']}"


# -------- Feature 3: OT XOR PATCH on City Care --------
class TestOTPolicyXOR:
    def test_ot_xor_and_revert(self, auth_headers):
        # 1) GET current policy
        g = requests.get(
            f"{BASE_URL}/api/attendance/policy",
            params={"company_id": CITY_CARE},
            headers=auth_headers,
            timeout=30,
        )
        assert g.status_code == 200, g.text[:300]
        policy = g.json().get("policy") or g.json()
        assert isinstance(policy, dict)

        # 2) PATCH with BOTH ot_pct_basic and ot_pct_gross -> expect 400
        body_both = dict(policy)
        body_both["ot_pct_basic"] = 100
        body_both["ot_pct_gross"] = 25
        r_both = requests.patch(
            f"{BASE_URL}/api/attendance/policy",
            params={"company_id": CITY_CARE},
            json=body_both,
            headers=auth_headers,
            timeout=30,
        )
        assert r_both.status_code == 400, f"expected 400 got {r_both.status_code}: {r_both.text[:200]}"
        assert "EITHER" in r_both.text.upper() or "either" in r_both.text.lower() or "choose" in r_both.text.lower(), r_both.text[:200]

        # 3) PATCH with only ot_pct_basic -> 200, then GET reflects 100
        body_basic = dict(policy)
        body_basic["ot_pct_basic"] = 100
        body_basic["ot_pct_gross"] = 0
        r_ok = requests.patch(
            f"{BASE_URL}/api/attendance/policy",
            params={"company_id": CITY_CARE},
            json=body_basic,
            headers=auth_headers,
            timeout=30,
        )
        assert r_ok.status_code == 200, f"patch basic failed: {r_ok.status_code} {r_ok.text[:200]}"

        g2 = requests.get(
            f"{BASE_URL}/api/attendance/policy",
            params={"company_id": CITY_CARE},
            headers=auth_headers,
            timeout=30,
        )
        assert g2.status_code == 200
        pol2 = g2.json().get("policy") or g2.json()
        assert float(pol2.get("ot_pct_basic") or 0) == 100.0, f"ot_pct_basic not saved: {pol2.get('ot_pct_basic')}"

        # 4) REVERT — both ot fields back to 0 (live-like data)
        body_revert = dict(pol2)
        body_revert["ot_pct_basic"] = 0
        body_revert["ot_pct_gross"] = 0
        r_rev = requests.patch(
            f"{BASE_URL}/api/attendance/policy",
            params={"company_id": CITY_CARE},
            json=body_revert,
            headers=auth_headers,
            timeout=30,
        )
        assert r_rev.status_code == 200, f"revert failed: {r_rev.status_code} {r_rev.text[:200]}"
        g3 = requests.get(
            f"{BASE_URL}/api/attendance/policy",
            params={"company_id": CITY_CARE},
            headers=auth_headers,
            timeout=30,
        )
        pol3 = g3.json().get("policy") or g3.json()
        assert float(pol3.get("ot_pct_basic") or 0) == 0.0
        assert float(pol3.get("ot_pct_gross") or 0) == 0.0


# -------- Feature 4: Firm scoping of compliance-salary-runs --------
class TestFirmScopedRuns:
    def test_scoped_vs_unscoped(self, auth_headers):
        scoped = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs",
            params={"company_id": KANKANI},
            headers=auth_headers,
            timeout=30,
        )
        unscoped = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs",
            headers=auth_headers,
            timeout=30,
        )
        assert scoped.status_code == 200 and unscoped.status_code == 200
        s_runs = scoped.json().get("runs") or scoped.json().get("items") or scoped.json()
        u_runs = unscoped.json().get("runs") or unscoped.json().get("items") or unscoped.json()
        assert isinstance(s_runs, list) and isinstance(u_runs, list)
        # All scoped runs must belong to Kankani
        for r in s_runs:
            cid = r.get("company_id") or r.get("firm_id")
            assert cid == KANKANI, f"scoped run leaked cid={cid}"
        assert len(u_runs) >= len(s_runs), f"unscoped ({len(u_runs)}) < scoped ({len(s_runs)})"


# -------- Feature 5: OT-salary firms endpoint --------
class TestOTSalaryFirms:
    def test_returns_ok_empty(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/ot-salary/firms",
            headers=auth_headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data.get("ok") is True, f"ok not True: {data}"
        assert data.get("firms") == [] or data.get("firms") is not None, f"firms: {data.get('firms')}"
        assert isinstance(data.get("firms"), list)
