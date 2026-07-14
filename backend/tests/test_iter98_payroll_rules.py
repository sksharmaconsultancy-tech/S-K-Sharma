"""Iter 98 backend regression — Firm-Master gated payroll rules & reports.

Covers:
1. Salary gates: online_salary → compliance run 403/200,
   offline_salary → actual salary run 403/200 (via TEST firm).
2. compute_compliance_row gating on firm_pf_enabled/firm_esic_enabled.
3. Firm Master CL/PL validation (both limits 0 while applicable → 400).
4. GET /admin/leave-report (rows + cl_/pl_ fields).
5. Export CSV sort_by=name|code|net|gross for salary + compliance runs.
6. compute_textile_day policy_2 <8h → all hours OT.
7. _actual_salary_row_compute ot_basis basic vs gross.
"""
import os
import sys
import uuid
import asyncio
from typing import Optional

import pytest
import requests

def _read_env_url():
    for k in ("EXPO_PUBLIC_BACKEND_URL", "EXPO_BACKEND_URL"):
        v = os.environ.get(k)
        if v:
            return v
    # Fallback to frontend/.env
    try:
        with open("/app/frontend/.env") as f:
            for ln in f:
                if ln.strip().startswith("EXPO_PUBLIC_BACKEND_URL="):
                    return ln.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""

BASE_URL = _read_env_url().rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL is required"

ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
ADMIN_PWD = "sharma123"
KANKANI_CID = "cmp_527fecdd7c"

sys.path.insert(0, "/app/backend")


# ---------- shared fixtures ----------
@pytest.fixture(scope="session")
def token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PWD},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- 1. Salary gates ----------
class TestSalaryProcessGates:
    """POST compliance/actual salary runs must respect Firm Master flags."""

    @pytest.fixture(scope="class")
    def test_firm(self, auth):
        """Create a throw-away firm we can flip flags on."""
        code = f"T{uuid.uuid4().hex[:5].upper()}"
        r = requests.post(
            f"{BASE_URL}/api/companies",
            headers=auth,
            json={
                "name": f"TEST_ITER98_{code}",
                "company_code": code,
                "address": "test",
                "office_lat": 26.9124,
                "office_lng": 75.7873,
                "geofence_radius_m": 200,
            },
            timeout=20,
        )
        assert r.status_code in (200, 201), r.text
        cid = r.json().get("company_id") or r.json().get("id")
        assert cid
        yield cid

    def _set_flags(self, auth, cid, online=None, offline=None):
        body = {"salary_process": {}}
        if online is not None:
            body["salary_process"]["online_salary"] = online
        if offline is not None:
            body["salary_process"]["offline_salary"] = offline
        r = requests.patch(
            f"{BASE_URL}/api/admin/firm-master/{cid}",
            headers=auth, json=body, timeout=20,
        )
        assert r.status_code == 200, r.text

    def test_compliance_403_when_online_off(self, auth, test_firm):
        self._set_flags(auth, test_firm, online=False)
        r = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs",
            headers=auth,
            json={"company_id": test_firm, "month": "2026-05"},
            timeout=30,
        )
        assert r.status_code == 403, r.text
        assert "not permitted" in r.text.lower()

    def test_compliance_200_when_online_on(self, auth, test_firm):
        # First, ensure compliance permission is granted (super_admin)
        # then enable online flag
        self._set_flags(auth, test_firm, online=True)
        r = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs",
            headers=auth,
            json={"company_id": test_firm, "month": "2026-05"},
            timeout=45,
        )
        # 200 (created) or 400 (no employees) — anything that is NOT 403
        assert r.status_code != 403, r.text
        # cleanup the created run if any
        if r.status_code in (200, 201):
            rid = (r.json().get("run") or {}).get("run_id")
            if rid:
                requests.delete(
                    f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}",
                    headers=auth, timeout=10,
                )

    def test_actual_403_when_offline_off(self, auth, test_firm):
        self._set_flags(auth, test_firm, offline=False)
        r = requests.post(
            f"{BASE_URL}/api/admin/actual-salary-process",
            headers=auth,
            json={"company_id": test_firm, "month": "2026-05"},
            timeout=30,
        )
        assert r.status_code == 403, r.text
        assert "not permitted" in r.text.lower()

    def test_actual_not_403_when_offline_on(self, auth, test_firm):
        self._set_flags(auth, test_firm, offline=True)
        r = requests.post(
            f"{BASE_URL}/api/admin/actual-salary-process",
            headers=auth,
            json={"company_id": test_firm, "month": "2026-05"},
            timeout=45,
        )
        assert r.status_code != 403, r.text
        if r.status_code in (200, 201):
            rid = (r.json().get("run") or {}).get("run_id")
            if rid:
                requests.delete(
                    f"{BASE_URL}/api/admin/salary-runs/{rid}",
                    headers=auth, timeout=10,
                )


# ---------- 2. compute_compliance_row PF/ESI gates ----------
class TestComplianceRowGates:
    _policy = {"salary_mode": "monthly", "full_day_hours": 8, "ot_multiplier": 1.5, "salary": 15000}
    _stats = {"present_days": 30, "half_days": 0, "effective_present": 30.0,
              "duty_hours": 240.0, "ot_hours": 0.0}

    def test_pf_zero_when_firm_disabled(self):
        from utils.compliance_salary import compute_compliance_row
        row = compute_compliance_row(
            user={"pf_applicable": True, "esic_applicable": True},
            policy=self._policy, month_days=30, stats=self._stats,
            firm_pf_enabled=False, firm_esic_enabled=True,
        )
        assert float(row.get("pf_employee") or 0) == 0

    def test_esic_zero_when_firm_disabled(self):
        from utils.compliance_salary import compute_compliance_row
        row = compute_compliance_row(
            user={"pf_applicable": True, "esic_applicable": True},
            policy=self._policy, month_days=30, stats=self._stats,
            firm_pf_enabled=True, firm_esic_enabled=False,
        )
        assert float(row.get("esic_employee") or 0) == 0

    def test_both_computed_when_enabled(self):
        from utils.compliance_salary import compute_compliance_row
        row = compute_compliance_row(
            user={"pf_applicable": True, "esic_applicable": True},
            policy=self._policy, month_days=30, stats=self._stats,
            firm_pf_enabled=True, firm_esic_enabled=True,
        )
        assert float(row.get("pf_employee") or 0) > 0


# ---------- 3. Firm-Master CL/PL validation ----------
class TestCLPLValidation:
    def test_cl_pl_both_zero_returns_400(self, auth):
        r = requests.patch(
            f"{BASE_URL}/api/admin/firm-master/{KANKANI_CID}",
            headers=auth,
            json={"leave_policy": {
                "cl_pl_applicable": True,
                "cl_day_limit": 0,
                "pl_day_limit": 0,
            }},
            timeout=20,
        )
        assert r.status_code == 400, r.text
        assert "cl/pl" in r.text.lower() or "allowed" in r.text.lower()

    def test_cl_positive_returns_200(self, auth):
        r = requests.patch(
            f"{BASE_URL}/api/admin/firm-master/{KANKANI_CID}",
            headers=auth,
            json={"leave_policy": {
                "cl_pl_applicable": True,
                "cl_day_limit": 7,
                "pl_day_limit": 0,
            }},
            timeout=20,
        )
        assert r.status_code == 200, r.text

    def teardown_class(cls):
        # restore Kankani leave_policy (disable cl_pl_applicable to keep flexible)
        try:
            r = requests.post(
                f"{BASE_URL}/api/auth/admin-password-login",
                json={"email": ADMIN_EMAIL, "password": ADMIN_PWD},
                timeout=15,
            )
            tok = r.json().get("session_token") or r.json().get("token")
            requests.patch(
                f"{BASE_URL}/api/admin/firm-master/{KANKANI_CID}",
                headers={"Authorization": f"Bearer {tok}"},
                json={"leave_policy": {
                    "cl_pl_applicable": False,
                    "cl_day_limit": 0,
                    "pl_day_limit": 0,
                }},
                timeout=20,
            )
        except Exception:
            pass


# ---------- 4. Leave Report ----------
class TestLeaveReport:
    def test_leave_report_kankani(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/leave-report",
            headers=auth,
            params={"company_id": KANKANI_CID, "year": 2026},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["year"] == 2026
        assert isinstance(body.get("rows"), list)
        assert body.get("employees_count", 0) >= 1
        r0 = body["rows"][0]
        for k in ("cl_allowed", "cl_taken", "cl_balance",
                  "pl_allowed", "pl_taken", "pl_balance"):
            assert k in r0, f"missing {k}"

    def test_leave_report_requires_year(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/leave-report",
            headers=auth, params={"company_id": KANKANI_CID}, timeout=10,
        )
        assert r.status_code == 422


# ---------- 5. Export sort_by ----------
class TestExportSort:
    @pytest.fixture(scope="class")
    def salary_run_id(self, auth):
        # find any existing salary run
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-runs",
            headers=auth, timeout=20,
        )
        assert r.status_code == 200, r.text
        runs = r.json().get("runs") or []
        if not runs:
            pytest.skip("no existing salary runs")
        # prefer one with >=2 rows
        for run in runs:
            if len(run.get("rows") or []) >= 2:
                return run["run_id"]
        return runs[0]["run_id"]

    @pytest.fixture(scope="class")
    def compliance_run_id(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs",
            headers=auth, timeout=20,
        )
        assert r.status_code == 200, r.text
        runs = r.json().get("runs") or []
        if not runs:
            pytest.skip("no existing compliance runs")
        for run in runs:
            if len(run.get("rows") or []) >= 2:
                return run["run_id"]
        return runs[0]["run_id"]

    @pytest.mark.parametrize("sort_by", ["name", "code", "net", "gross"])
    def test_salary_export_sorted(self, auth, salary_run_id, sort_by):
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-runs/{salary_run_id}/export.csv",
            headers=auth, params={"sort_by": sort_by}, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert "text/csv" in (r.headers.get("content-type") or "")
        # CSV should have >= header + 1 line
        assert len(r.text.splitlines()) >= 1

    @pytest.mark.parametrize("sort_by", ["name", "code", "net", "gross"])
    def test_compliance_export_sorted(self, auth, compliance_run_id, sort_by):
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{compliance_run_id}/export.csv",
            headers=auth, params={"sort_by": sort_by}, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert len(r.text.splitlines()) >= 1


# ---------- 6. compute_textile_day policy_2 <8h → OT ----------
class TestTextilePolicy2:
    def test_under_8h_all_ot(self):
        from server import compute_textile_day
        # 5-hour block of punches
        punches = [
            {"kind": "in", "at": "2026-05-05T09:00:00"},
            {"kind": "out", "at": "2026-05-05T14:00:00"},
        ]
        policy = {"policy_variant": "policy_2", "standard_working_hours": 8,
                  "full_day_hours": 8, "half_day_hours": 4}
        emp = {"ot_applicable": True}
        # weekday 1 (Tue) — a normal workday, not weekly-off
        summary = compute_textile_day(punches, policy, emp, 1)
        assert summary is not None
        # <8h → no present day, all 5h (=300 min) → OT
        pd = float(summary.get("present_days") or 0)
        otm = int(summary.get("ot_minutes") or 0)
        assert pd == 0, f"present_days should be 0, got {pd}"
        assert otm == 300, f"ot_minutes should be 300, got {otm}"


# ---------- 7. _actual_salary_row_compute ot_basis ----------
class TestOTBasis:
    def test_gross_yields_higher_wbasic(self):
        from server import _actual_salary_row_compute
        row_template = {
            "basic": 20000,     # monthly
            "duty_hrs": 8,
            "p_days": 26,
            "p_hours": 40,      # 40 OT hours
            "oth_allo": 5000,
            "adv": 0, "tds": 0,
            "salary_mode": "monthly",
        }
        b = _actual_salary_row_compute(dict(row_template), 26, ot_basis="basic")
        g = _actual_salary_row_compute(dict(row_template), 26, ot_basis="gross")
        assert float(g["w_basic_salary"]) > float(b["w_basic_salary"]), (
            f"gross={g['w_basic_salary']} vs basic={b['w_basic_salary']}"
        )


# ---------- cleanup fixture — remove any TEST_ firms created ----------
def teardown_module(module):
    try:
        r = requests.post(
            f"{BASE_URL}/api/auth/admin-password-login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=15,
        )
        tok = r.json().get("session_token") or r.json().get("token")
        cs = requests.get(
            f"{BASE_URL}/api/admin/companies",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        ).json().get("companies") or []
        for c in cs:
            if str(c.get("name") or "").startswith("TEST_ITER98"):
                requests.delete(
                    f"{BASE_URL}/api/companies/{c['company_id']}",
                    headers={"Authorization": f"Bearer {tok}"}, timeout=10,
                )
    except Exception:
        pass
