"""Iter 63 backend tests — Cross-firm multi-select for Reports Hub and
Bulk Employee Correction.

Endpoints under test:
  - GET  /api/admin/employees                 (company_ids[])
  - GET  /api/admin/salary-runs               (company_ids[])
  - GET  /api/admin/compliance-salary-runs    (company_ids[])
  - GET  /api/admin/bonus-runs                (company_ids[])
  - POST /api/admin/employees/bulk-correction (company_ids in body)

Also verifies:
  - Legacy single company_id=X still works for all 4 GETs and bulk-correction.
  - company_admin role: company_ids param is IGNORED (scoped to own firm).
  - Employee role: 403 on admin endpoints.
"""
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://emplo-connect-1.preview.emergentagent.com",
).rstrip("/")
SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"


def _extract_list(data, *keys):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _otp_login(api, identifier, channel="email"):
    r = api.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": identifier, "channel": channel},
    )
    assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    code = body.get("dev_code") or body.get("code")
    assert code, f"No dev code in response: {body}"
    r = api.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": identifier, "channel": channel, "code": code},
    )
    assert r.status_code == 200, f"otp/verify failed: {r.status_code} {r.text[:200]}"
    j = r.json()
    return j.get("session_token") or j.get("token")


@pytest.fixture(scope="session")
def super_token(api):
    return _otp_login(api, SUPER_ADMIN_EMAIL, "email")


@pytest.fixture(scope="session")
def super_headers(super_token):
    return {"Authorization": f"Bearer {super_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def companies(api, super_headers):
    """Return list of at least 2 real company_ids that have employees."""
    r = api.get(f"{BASE_URL}/api/companies", headers=super_headers)
    assert r.status_code == 200, r.text[:200]
    items = _extract_list(r.json(), "companies", "items")
    assert len(items) >= 2, f"need >=2 companies, got {len(items)}"
    # Pick two firms that both have at least 1 employee for stronger tests
    firms_with_emp = []
    for c in items:
        cid = c["company_id"]
        rr = api.get(
            f"{BASE_URL}/api/admin/employees?company_id={cid}",
            headers=super_headers,
        )
        if rr.status_code == 200 and _extract_list(rr.json(), "employees", "items"):
            firms_with_emp.append(cid)
        if len(firms_with_emp) >= 2:
            break
    # Fallback: just take first two if we didn't find two with employees
    if len(firms_with_emp) < 2:
        firms_with_emp = [c["company_id"] for c in items[:2]]
    return firms_with_emp


# ========================= P0 EMPLOYEES =========================
class TestEmployeesCrossFirm:
    """GET /api/admin/employees with company_ids[]"""

    def test_single_company_id_legacy(self, api, super_headers, companies):
        cid = companies[0]
        r = api.get(
            f"{BASE_URL}/api/admin/employees?company_id={cid}",
            headers=super_headers,
        )
        assert r.status_code == 200, r.text[:200]
        emps = _extract_list(r.json(), "employees", "items")
        # If empty, at least keys are valid — but for our chosen firms this shouldn't happen
        for e in emps:
            assert e.get("company_id") == cid, f"leak: {e.get('company_id')} != {cid}"

    def test_multi_company_ids_returns_union(self, api, super_headers, companies):
        c1, c2 = companies[0], companies[1]
        url = f"{BASE_URL}/api/admin/employees?company_ids={c1}&company_ids={c2}"
        r = api.get(url, headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        emps = _extract_list(r.json(), "employees", "items")
        assert emps, "expected employees from cross-firm fetch"
        firm_ids = {e.get("company_id") for e in emps}
        assert firm_ids.issubset({c1, c2}), f"leak: {firm_ids - {c1, c2}}"
        # Confirm both firms are actually present (each has at least 1 employee)
        assert c1 in firm_ids, f"{c1} missing from cross-firm result"
        assert c2 in firm_ids, f"{c2} missing from cross-firm result"

    def test_multi_company_ids_overrides_singular(self, api, super_headers, companies):
        c1, c2 = companies[0], companies[1]
        # company_id + company_ids together → company_ids wins
        url = (
            f"{BASE_URL}/api/admin/employees"
            f"?company_id=NON_EXISTENT&company_ids={c1}&company_ids={c2}"
        )
        r = api.get(url, headers=super_headers)
        assert r.status_code == 200
        emps = _extract_list(r.json(), "employees", "items")
        firm_ids = {e.get("company_id") for e in emps}
        assert firm_ids.issubset({c1, c2})


# ========================= SALARY RUNS =========================
class TestSalaryRunsCrossFirm:
    def test_single_company_id_legacy(self, api, super_headers, companies):
        cid = companies[0]
        r = api.get(
            f"{BASE_URL}/api/admin/salary-runs?company_id={cid}",
            headers=super_headers,
        )
        assert r.status_code == 200, r.text[:200]
        runs = _extract_list(r.json(), "runs", "items")
        for run in runs:
            assert run.get("company_id") == cid

    def test_multi_company_ids(self, api, super_headers, companies):
        c1, c2 = companies[0], companies[1]
        url = f"{BASE_URL}/api/admin/salary-runs?company_ids={c1}&company_ids={c2}"
        r = api.get(url, headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        runs = _extract_list(r.json(), "runs", "items")
        for run in runs:
            assert run.get("company_id") in {c1, c2}, f"leak: {run.get('company_id')}"


# ========================= COMPLIANCE SALARY RUNS =========================
class TestComplianceRunsCrossFirm:
    def test_single_company_id_legacy(self, api, super_headers, companies):
        cid = companies[0]
        r = api.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs?company_id={cid}",
            headers=super_headers,
        )
        # super_admin should always have compliance_salary:read
        assert r.status_code == 200, r.text[:200]
        runs = _extract_list(r.json(), "runs", "items")
        for run in runs:
            assert run.get("company_id") == cid

    def test_multi_company_ids(self, api, super_headers, companies):
        c1, c2 = companies[0], companies[1]
        url = (
            f"{BASE_URL}/api/admin/compliance-salary-runs"
            f"?company_ids={c1}&company_ids={c2}"
        )
        r = api.get(url, headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        runs = _extract_list(r.json(), "runs", "items")
        for run in runs:
            assert run.get("company_id") in {c1, c2}


# ========================= BONUS RUNS =========================
class TestBonusRunsCrossFirm:
    def test_single_company_id_legacy(self, api, super_headers, companies):
        cid = companies[0]
        r = api.get(
            f"{BASE_URL}/api/admin/bonus-runs?company_id={cid}",
            headers=super_headers,
        )
        assert r.status_code == 200, r.text[:200]
        items = _extract_list(r.json(), "items", "runs")
        for it in items:
            assert it.get("company_id") == cid

    def test_multi_company_ids(self, api, super_headers, companies):
        c1, c2 = companies[0], companies[1]
        url = f"{BASE_URL}/api/admin/bonus-runs?company_ids={c1}&company_ids={c2}"
        r = api.get(url, headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        items = _extract_list(r.json(), "items", "runs")
        for it in items:
            assert it.get("company_id") in {c1, c2}


# ========================= BULK CORRECTION (dry_run) =========================
class TestBulkCorrectionCrossFirm:
    """Uses dry_run=True to avoid mutating real employee data."""

    def _one_employee(self, api, headers, cid):
        r = api.get(
            f"{BASE_URL}/api/admin/employees?company_id={cid}",
            headers=headers,
        )
        if r.status_code != 200:
            return None
        lst = _extract_list(r.json(), "employees", "items")
        return lst[0] if lst else None

    def test_bulk_correction_single_company_id_legacy(
        self, api, super_headers, companies
    ):
        cid = companies[0]
        emp = self._one_employee(api, super_headers, cid)
        if not emp:
            pytest.skip(f"no employees in {cid}")
        payload = {
            "company_id": cid,
            "dry_run": True,
            "corrections": [
                {"user_id": emp["user_id"], "designation": "TEST_ITER63_DESIG"}
            ],
        }
        r = api.post(
            f"{BASE_URL}/api/admin/employees/bulk-correction",
            headers=super_headers,
            json=payload,
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body.get("applied_count") == 1, body
        assert body.get("dry_run") is True

    def test_bulk_correction_cross_firm(self, api, super_headers, companies):
        c1, c2 = companies[0], companies[1]
        e1 = self._one_employee(api, super_headers, c1)
        e2 = self._one_employee(api, super_headers, c2)
        if not e1 or not e2:
            pytest.skip("need one employee in each of two firms")
        payload = {
            "company_ids": [c1, c2],
            "dry_run": True,
            "corrections": [
                {"user_id": e1["user_id"], "designation": "TEST_ITER63_A"},
                {"user_id": e2["user_id"], "designation": "TEST_ITER63_B"},
            ],
        }
        r = api.post(
            f"{BASE_URL}/api/admin/employees/bulk-correction",
            headers=super_headers,
            json=payload,
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body.get("applied_count") == 2, body
        # Neither should be skipped
        assert body.get("skipped_count") == 0, body

    def test_bulk_correction_rejects_no_company(self, api, super_headers, companies):
        emp = self._one_employee(api, super_headers, companies[0])
        if not emp:
            pytest.skip("no employees")
        payload = {
            # neither company_id nor company_ids
            "dry_run": True,
            "corrections": [{"user_id": emp["user_id"], "designation": "X"}],
        }
        r = api.post(
            f"{BASE_URL}/api/admin/employees/bulk-correction",
            headers=super_headers,
            json=payload,
        )
        assert r.status_code == 400, r.text[:200]

    def test_bulk_correction_employee_outside_scope_is_skipped(
        self, api, super_headers, companies
    ):
        """Employee belonging to c2 should be skipped when only c1 is in scope."""
        c1, c2 = companies[0], companies[1]
        e2 = self._one_employee(api, super_headers, c2)
        if not e2:
            pytest.skip("no employees in c2")
        payload = {
            "company_ids": [c1],
            "dry_run": True,
            "corrections": [{"user_id": e2["user_id"], "designation": "X"}],
        }
        r = api.post(
            f"{BASE_URL}/api/admin/employees/bulk-correction",
            headers=super_headers,
            json=payload,
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body.get("skipped_count") == 1, body
        assert body.get("applied_count") == 0, body


# ========================= ROLE GUARDS =========================
class TestRoleGuards:
    """company_admin ignores company_ids; employee role gets 403."""

    @pytest.fixture(scope="class")
    def company_admin_token(self, api, super_headers, companies):
        """Login as a known company_admin from test_credentials.md and figure
        out which firm they belong to via /api/auth/me."""
        # Try known admin emails (from /app/memory/test_credentials.md)
        candidates = [
            "admin.skscoltd@sksharma.local",
            "admin.associates@sksharma.local",
            "admin.services@sksharma.local",
            "admin.consultancy@sksharma.local",
            "admin.allied@sksharma.local",
        ]
        token = None
        for email in candidates:
            try:
                token = _otp_login(api, email, "email")
                if token:
                    break
            except AssertionError:
                continue
        if not token:
            pytest.skip("could not OTP-login any known company_admin")
        r = api.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text[:200]
        me = r.json()
        # Extract role + company_id from various possible response shapes
        role = me.get("role") or (me.get("user") or {}).get("role")
        own_cid = me.get("company_id") or (me.get("user") or {}).get("company_id")
        if role != "company_admin" or not own_cid:
            pytest.skip(f"resolved user is not company_admin (role={role}, cid={own_cid})")
        return token, own_cid

    def test_company_admin_ignores_company_ids(
        self, api, company_admin_token, companies
    ):
        token, own_cid = company_admin_token
        other_cid = next((c for c in companies if c != own_cid), None)
        if not other_cid:
            pytest.skip("need another firm distinct from company_admin's own")
        hdrs = {"Authorization": f"Bearer {token}"}
        url = (
            f"{BASE_URL}/api/admin/employees"
            f"?company_ids={own_cid}&company_ids={other_cid}"
        )
        r = api.get(url, headers=hdrs)
        assert r.status_code == 200, r.text[:200]
        emps = _extract_list(r.json(), "employees", "items")
        # All employees must belong to own_cid (other firm silently dropped)
        for e in emps:
            assert e.get("company_id") == own_cid, (
                f"company_admin leaked cross-firm data: {e.get('company_id')} != {own_cid}"
            )

    def test_employee_role_gets_403(self, api):
        """A fresh employee OTP-login should get 403 on admin endpoints."""
        fake_email = f"qa.emp.iter63.{uuid.uuid4().hex[:8]}@test.com"
        try:
            token = _otp_login(api, fake_email, "email")
        except AssertionError as e:
            pytest.skip(f"could not obtain employee token: {e}")
        hdrs = {"Authorization": f"Bearer {token}"}
        r = api.get(f"{BASE_URL}/api/admin/employees", headers=hdrs)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:200]}"
        # Bulk-correction also should be blocked (requires super_admin/sub_admin)
        r = api.post(
            f"{BASE_URL}/api/admin/employees/bulk-correction",
            headers=hdrs,
            json={"company_id": "x", "corrections": [], "dry_run": True},
        )
        assert r.status_code == 403, r.text[:200]
