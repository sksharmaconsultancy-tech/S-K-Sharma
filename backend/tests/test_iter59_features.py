"""
Iter 59 backend regression tests
Covers:
- Attendance sheet alias & new endpoint + group filter
- Employee Masters CRUD (group / department / designation)
- Firm-wise Compliance Policy override (super_admin only)
- Bonus policy clamping
- Bonus preview computation (correctness against spec)
- Bonus XLSX report download
- Sub-admin role gates for bonus + /admin/employees
- Resend integration (POST /auth/otp/request returns delivered + email_id)
"""

import os
import uuid
import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")


# ---------- helpers ---------------------------------------------------------

def _login_super_admin() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": "sksharmaconsultancy@gmail.com", "channel": "email"},
        timeout=15,
    )
    r.raise_for_status()
    code = r.json().get("dev_code")
    assert code, f"No dev_code in OTP request response: {r.text}"
    v = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": "sksharmaconsultancy@gmail.com", "channel": "email", "code": code},
        timeout=15,
    )
    v.raise_for_status()
    tok = v.json().get("session_token") or v.json().get("token")
    assert tok
    return tok


def _login_otp(identifier: str, channel: str = "email") -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": identifier, "channel": channel},
        timeout=15,
    )
    r.raise_for_status()
    code = r.json().get("dev_code")
    assert code
    v = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": identifier, "channel": channel, "code": code},
        timeout=15,
    )
    v.raise_for_status()
    return v.json().get("session_token") or v.json()["token"]


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- fixtures --------------------------------------------------------

@pytest.fixture(scope="module")
def super_token() -> str:
    return _login_super_admin()


@pytest.fixture(scope="module")
def sksco_company_id(super_token) -> str:
    r = requests.get(f"{BASE_URL}/api/companies", headers=_h(super_token), timeout=15)
    r.raise_for_status()
    body = r.json()
    items = (body.get("companies") if isinstance(body, dict) else body) or []
    for c in items:
        if c.get("company_code") == "SKSCO1" or c.get("code") == "SKSCO1":
            return c["company_id"]
    # fallback: first company
    assert items, "No companies present in DB"
    return items[0]["company_id"]


@pytest.fixture(scope="module")
def sample_employee(super_token, sksco_company_id):
    """Return first employee of SKSCO1 (creates one lightweight test employee if
    there are none). Cleanup happens at module teardown."""
    r = requests.get(
        f"{BASE_URL}/api/admin/employees?company_id={sksco_company_id}",
        headers=_h(super_token), timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    if isinstance(body, list):
        items = body
    else:
        items = body.get("employees") or body.get("items") or []
    if items:
        return items[0], False
    # No employee — create a throwaway one via signup
    email = f"TEST_iter59_{uuid.uuid4().hex[:6]}@sksharma.local"
    sig = requests.post(
        f"{BASE_URL}/api/employee/signup",
        json={
            "email": email, "name": "TEST_iter59_emp",
            "phone": f"+9199{uuid.uuid4().int % 100000000:08d}",
            "company_id": sksco_company_id,
            "password": "Test@12345",
        },
        timeout=15,
    )
    if sig.status_code >= 400:
        pytest.skip(f"Cannot seed employee: {sig.status_code} {sig.text[:200]}")
    data = sig.json()
    return data, True


# ---------- Resend integration ---------------------------------------------

class TestResendIntegration:
    def test_otp_email_delivered(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/otp/request",
            json={"identifier": "sksharmaconsultancy@gmail.com", "channel": "email"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        # New RESEND key must be valid
        assert data.get("delivered") is True, f"Resend delivery failed: {data}"
        assert data.get("email_id"), f"No email_id returned: {data}"


# ---------- Attendance Sheet aliases ---------------------------------------

class TestAttendanceSheet:
    def test_legacy_master_sheet_alias(self, super_token, sksco_company_id):
        r = requests.get(
            f"{BASE_URL}/api/admin/master-sheet/{sksco_company_id}/2025-01.xlsx",
            headers=_h(super_token), timeout=30,
        )
        assert r.status_code == 200, f"Legacy alias returned {r.status_code}: {r.text[:200]}"
        assert "spreadsheetml.sheet" in r.headers.get("content-type", "")
        assert len(r.content) > 0

    def test_new_attendance_sheet_endpoint(self, super_token, sksco_company_id):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance-sheet/{sksco_company_id}/2025-01.xlsx",
            headers=_h(super_token), timeout=30,
        )
        assert r.status_code == 200, r.text[:200]
        assert "spreadsheetml.sheet" in r.headers.get("content-type", "")
        assert len(r.content) > 0

    def test_attendance_sheet_with_group_filter(self, super_token, sksco_company_id, sample_employee):
        emp, _ = sample_employee
        emp_uid = emp.get("user_id") or emp.get("id")
        assert emp_uid, f"No user_id in employee doc: {emp}"

        # Create a group containing just this one employee
        grp_name = f"TEST_iter59_grp_{uuid.uuid4().hex[:6]}"
        c = requests.post(
            f"{BASE_URL}/api/admin/masters",
            headers=_h(super_token), timeout=15,
            json={"type": "group", "company_id": sksco_company_id, "name": grp_name,
                  "member_user_ids": [emp_uid]},
        )
        assert c.status_code == 200, c.text
        gid = c.json()["master_id"]
        try:
            r = requests.get(
                f"{BASE_URL}/api/admin/attendance-sheet/{sksco_company_id}/2025-01.xlsx"
                f"?group_id={gid}",
                headers=_h(super_token), timeout=30,
            )
            assert r.status_code == 200, r.text[:200]
            assert len(r.content) > 0
            # Also verify a bogus group_id yields an empty (but valid) sheet
            r2 = requests.get(
                f"{BASE_URL}/api/admin/attendance-sheet/{sksco_company_id}/2025-01.xlsx"
                f"?group_id=mst_doesnotexist",
                headers=_h(super_token), timeout=30,
            )
            assert r2.status_code == 200
        finally:
            requests.delete(f"{BASE_URL}/api/admin/masters/{gid}", headers=_h(super_token), timeout=15)


# ---------- Masters CRUD ---------------------------------------------------

class TestMastersCRUD:
    @pytest.mark.parametrize("mtype", ["group", "department", "designation"])
    def test_create_list(self, super_token, sksco_company_id, mtype):
        name = f"TEST_iter59_{mtype}_{uuid.uuid4().hex[:6]}"
        c = requests.post(
            f"{BASE_URL}/api/admin/masters",
            headers=_h(super_token), timeout=15,
            json={"type": mtype, "company_id": sksco_company_id, "name": name},
        )
        assert c.status_code == 200, c.text
        mid = c.json()["master_id"]
        try:
            g = requests.get(
                f"{BASE_URL}/api/admin/masters?type={mtype}&company_id={sksco_company_id}",
                headers=_h(super_token), timeout=15,
            )
            assert g.status_code == 200
            names = [it["name"] for it in g.json()["items"]]
            assert name in names
        finally:
            requests.delete(f"{BASE_URL}/api/admin/masters/{mid}", headers=_h(super_token), timeout=15)

    def test_duplicate_returns_409(self, super_token, sksco_company_id):
        name = f"TEST_iter59_dup_{uuid.uuid4().hex[:6]}"
        c = requests.post(
            f"{BASE_URL}/api/admin/masters",
            headers=_h(super_token), timeout=15,
            json={"type": "department", "company_id": sksco_company_id, "name": name},
        )
        assert c.status_code == 200
        mid = c.json()["master_id"]
        try:
            d = requests.post(
                f"{BASE_URL}/api/admin/masters",
                headers=_h(super_token), timeout=15,
                json={"type": "department", "company_id": sksco_company_id, "name": name},
            )
            assert d.status_code == 409, f"Expected 409, got {d.status_code}: {d.text}"
        finally:
            requests.delete(f"{BASE_URL}/api/admin/masters/{mid}", headers=_h(super_token), timeout=15)

    def test_patch_group_updates_name_and_members(self, super_token, sksco_company_id, sample_employee):
        emp, _ = sample_employee
        emp_uid = emp.get("user_id") or emp.get("id")
        name = f"TEST_iter59_grp_{uuid.uuid4().hex[:6]}"
        c = requests.post(
            f"{BASE_URL}/api/admin/masters",
            headers=_h(super_token), timeout=15,
            json={"type": "group", "company_id": sksco_company_id, "name": name,
                  "member_user_ids": []},
        )
        assert c.status_code == 200, c.text
        mid = c.json()["master_id"]
        try:
            new_name = name + "_v2"
            p = requests.patch(
                f"{BASE_URL}/api/admin/masters/{mid}",
                headers=_h(super_token), timeout=15,
                json={"type": "group", "company_id": sksco_company_id,
                      "name": new_name, "member_user_ids": [emp_uid]},
            )
            assert p.status_code == 200, p.text
            j = p.json()
            assert j["name"] == new_name
            assert emp_uid in j["member_user_ids"]
        finally:
            requests.delete(f"{BASE_URL}/api/admin/masters/{mid}", headers=_h(super_token), timeout=15)

    def test_delete_returns_ok(self, super_token, sksco_company_id):
        c = requests.post(
            f"{BASE_URL}/api/admin/masters",
            headers=_h(super_token), timeout=15,
            json={"type": "designation", "company_id": sksco_company_id,
                  "name": f"TEST_del_{uuid.uuid4().hex[:6]}"},
        )
        assert c.status_code == 200
        mid = c.json()["master_id"]
        d = requests.delete(f"{BASE_URL}/api/admin/masters/{mid}", headers=_h(super_token), timeout=15)
        assert d.status_code == 200
        assert d.json().get("ok") is True


# ---------- Firm-wise Compliance Policy ------------------------------------

class TestCompliancePolicyFirmwide:
    def test_put_get_roundtrip(self, super_token, sksco_company_id):
        payload = {"pf_employee_rate": 12.0, "esic_employer_rate": 3.25,
                   "tds_regime": "new", "notes": "TEST_iter59"}
        p = requests.put(
            f"{BASE_URL}/api/admin/companies/{sksco_company_id}/compliance-policy",
            headers=_h(super_token), timeout=15, json=payload,
        )
        assert p.status_code == 200, p.text
        g = requests.get(
            f"{BASE_URL}/api/admin/companies/{sksco_company_id}/compliance-policy",
            headers=_h(super_token), timeout=15,
        )
        assert g.status_code == 200
        pol = g.json()["policy"]
        assert pol.get("pf_employee_rate") == 12.0
        assert pol.get("esic_employer_rate") == 3.25
        assert pol.get("tds_regime") == "new"

    def test_sub_admin_cannot_put(self, super_token, sksco_company_id):
        """Create a sub_admin without compliance write perm and confirm PUT → 403."""
        email = f"TEST_iter59_sub_{uuid.uuid4().hex[:6]}@sksharma.local"
        c = requests.post(
            f"{BASE_URL}/api/admin/sub-admins",
            headers=_h(super_token), timeout=15,
            json={"name": "TEST sub", "email": email,
                  "permissions": [], "password": "SubTest@123"},
        )
        if c.status_code >= 400:
            pytest.skip(f"Cannot create sub-admin: {c.status_code} {c.text[:200]}")
        sub_uid = c.json().get("user_id") or c.json().get("id")
        try:
            sub_tok = _login_otp(email, "email")
            r = requests.put(
                f"{BASE_URL}/api/admin/companies/{sksco_company_id}/compliance-policy",
                headers=_h(sub_tok), timeout=15,
                json={"pf_employee_rate": 12.0},
            )
            assert r.status_code == 403, f"Expected 403 for sub_admin PUT, got {r.status_code}: {r.text[:200]}"
        finally:
            if sub_uid:
                requests.delete(f"{BASE_URL}/api/admin/sub-admins/{sub_uid}",
                                headers=_h(super_token), timeout=15)


# ---------- Bonus policy + preview -----------------------------------------

class TestBonusPolicyAndRun:
    def test_rate_clamped_high(self, super_token, sksco_company_id):
        r = requests.put(
            f"{BASE_URL}/api/admin/companies/{sksco_company_id}/bonus-policy",
            headers=_h(super_token), timeout=15,
            json={"rate_percent": 25.0},
        )
        assert r.status_code == 200, r.text
        assert r.json()["policy"]["rate_percent"] == 20.0

    def test_rate_clamped_low(self, super_token, sksco_company_id):
        r = requests.put(
            f"{BASE_URL}/api/admin/companies/{sksco_company_id}/bonus-policy",
            headers=_h(super_token), timeout=15,
            json={"rate_percent": 5.0},
        )
        assert r.status_code == 200
        assert r.json()["policy"]["rate_percent"] == 8.33

    def test_bonus_preview_returns_rows(self, super_token, sksco_company_id):
        # ensure default policy
        requests.put(
            f"{BASE_URL}/api/admin/companies/{sksco_company_id}/bonus-policy",
            headers=_h(super_token), timeout=15,
            json={"rate_percent": 8.33, "wage_ceiling": 7000.0, "eligibility_cap": 21000.0},
        )
        r = requests.post(
            f"{BASE_URL}/api/admin/bonus-runs/preview",
            headers=_h(super_token), timeout=30,
            json={"company_id": sksco_company_id, "fy_start_year": 2025},
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert "rows" in j
        assert "total_bonus" in j
        assert j["fy_label"] == "2025-26"

    def test_bonus_amount_formula_eligible(self, super_token, sksco_company_id, sample_employee):
        """Update an existing employee to basic=10000, doj=2020-01-01 and
        verify preview returns 6997.2 (7000*0.0833*12)."""
        emp, _ = sample_employee
        emp_uid = emp.get("user_id") or emp.get("id")
        assert emp_uid, "No employee available"
        # remember original salary to restore after test
        orig_basic = emp.get("basic_salary")
        orig_salary = emp.get("salary_monthly")
        orig_doj = emp.get("doj")

        # Set basic_salary=10000 and doj=2020-01-01 via user-role PATCH
        pr = requests.patch(
            f"{BASE_URL}/api/admin/user-role",
            headers=_h(super_token), timeout=15,
            json={"user_id": emp_uid, "basic_salary": 10000, "salary_monthly": 20000,
                  "doj": "2020-01-01"},
        )
        # Some deployments require role field — try again if 422
        if pr.status_code >= 400:
            pr = requests.patch(
                f"{BASE_URL}/api/admin/user-role",
                headers=_h(super_token), timeout=15,
                json={"user_id": emp_uid, "role": "employee",
                      "basic_salary": 10000, "salary_monthly": 20000, "doj": "2020-01-01"},
            )
        assert pr.status_code == 200, pr.text

        # Isolate via group
        grp_name = f"TEST_iter59_bonusgrp_{uuid.uuid4().hex[:6]}"
        g = requests.post(
            f"{BASE_URL}/api/admin/masters",
            headers=_h(super_token), timeout=15,
            json={"type": "group", "company_id": sksco_company_id, "name": grp_name,
                  "member_user_ids": [emp_uid]},
        )
        assert g.status_code == 200
        gid = g.json()["master_id"]
        try:
            r = requests.post(
                f"{BASE_URL}/api/admin/bonus-runs/preview",
                headers=_h(super_token), timeout=30,
                json={"company_id": sksco_company_id, "fy_start_year": 2025, "group_id": gid},
            )
            assert r.status_code == 200, r.text
            rows = r.json()["rows"]
            assert len(rows) == 1, f"Expected 1 row (isolated by group), got {rows}"
            row = rows[0]
            assert row["eligible"] is True
            assert row["months_worked"] == 12
            # 7000 * 0.0833 * 12 = 6997.2 (server rounds bonus_amount to 2dp)
            assert abs(row["bonus_amount"] - 6997.2) < 0.05, f"bonus_amount={row['bonus_amount']}"

            # Now update salary above cap (basic_salary is not updatable via
            # /admin/user-role, so set salary_monthly high enough that
            # basic = 50% of gross > 21000 cap).
            pr2 = requests.patch(
                f"{BASE_URL}/api/admin/user-role",
                headers=_h(super_token), timeout=15,
                json={"user_id": emp_uid, "salary_monthly": 60000},
            )
            assert pr2.status_code == 200, pr2.text
            r2 = requests.post(
                f"{BASE_URL}/api/admin/bonus-runs/preview",
                headers=_h(super_token), timeout=30,
                json={"company_id": sksco_company_id, "fy_start_year": 2025, "group_id": gid},
            )
            assert r2.status_code == 200
            row2 = r2.json()["rows"][0]
            assert row2["eligible"] is False
            assert row2["bonus_amount"] == 0.0
        finally:
            requests.delete(f"{BASE_URL}/api/admin/masters/{gid}",
                            headers=_h(super_token), timeout=15)
            # Restore original salary/doj
            restore = {"user_id": emp_uid}
            if orig_basic is not None:
                restore["basic_salary"] = orig_basic
            if orig_salary is not None:
                restore["salary_monthly"] = orig_salary
            if orig_doj:
                restore["doj"] = orig_doj
            requests.patch(f"{BASE_URL}/api/admin/user-role",
                           headers=_h(super_token), timeout=15, json=restore)

    def test_bonus_xlsx_download(self, super_token, sksco_company_id):
        # Create a run then download the XLSX
        c = requests.post(
            f"{BASE_URL}/api/admin/bonus-runs",
            headers=_h(super_token), timeout=30,
            json={"company_id": sksco_company_id, "fy_start_year": 2025},
        )
        assert c.status_code == 200, c.text
        rid = c.json()["run_id"]
        d = requests.get(
            f"{BASE_URL}/api/admin/bonus-runs/{rid}/report.xlsx",
            headers=_h(super_token), timeout=30,
        )
        assert d.status_code == 200, d.text[:200]
        assert "spreadsheetml.sheet" in d.headers.get("content-type", "")
        assert len(d.content) > 0


# ---------- Sub-admin role gates -------------------------------------------

class TestSubAdminGates:
    def test_sub_admin_can_call_bonus_runs(self, super_token, sksco_company_id):
        email = f"TEST_iter59_bsub_{uuid.uuid4().hex[:6]}@sksharma.local"
        c = requests.post(
            f"{BASE_URL}/api/admin/sub-admins",
            headers=_h(super_token), timeout=15,
            json={"name": "TEST bonus sub", "email": email,
                  "permissions": [], "password": "SubTest@123"},
        )
        if c.status_code >= 400:
            pytest.skip(f"Cannot create sub-admin: {c.status_code} {c.text[:200]}")
        sub_uid = c.json().get("user_id") or c.json().get("id")
        try:
            sub_tok = _login_otp(email, "email")
            r = requests.post(
                f"{BASE_URL}/api/admin/bonus-runs",
                headers=_h(sub_tok), timeout=30,
                json={"company_id": sksco_company_id, "fy_start_year": 2025},
            )
            assert r.status_code == 200, f"sub_admin should be allowed on POST bonus-runs, got {r.status_code}: {r.text[:200]}"
        finally:
            if sub_uid:
                requests.delete(f"{BASE_URL}/api/admin/sub-admins/{sub_uid}",
                                headers=_h(super_token), timeout=15)

    def test_sub_admin_can_list_employees(self, super_token, sksco_company_id):
        email = f"TEST_iter59_esub_{uuid.uuid4().hex[:6]}@sksharma.local"
        c = requests.post(
            f"{BASE_URL}/api/admin/sub-admins",
            headers=_h(super_token), timeout=15,
            json={"name": "TEST emp sub", "email": email,
                  "permissions": [], "password": "SubTest@123"},
        )
        if c.status_code >= 400:
            pytest.skip(f"Cannot create sub-admin: {c.status_code} {c.text[:200]}")
        sub_uid = c.json().get("user_id") or c.json().get("id")
        try:
            sub_tok = _login_otp(email, "email")
            r = requests.get(
                f"{BASE_URL}/api/admin/employees?company_id={sksco_company_id}",
                headers=_h(sub_tok), timeout=15,
            )
            assert r.status_code == 200, f"sub_admin should be allowed on /admin/employees, got {r.status_code}"
        finally:
            if sub_uid:
                requests.delete(f"{BASE_URL}/api/admin/sub-admins/{sub_uid}",
                                headers=_h(super_token), timeout=15)
