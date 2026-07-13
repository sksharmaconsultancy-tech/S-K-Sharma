"""Iter 60 backend tests — bulk-correction, bulk-import, attendance-email cron,
portal automation, FY filters and sub_admin READ access."""
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com"
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
    r = api.post(f"{BASE_URL}/api/auth/otp/request", json={"identifier": identifier, "channel": channel})
    assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    code = body.get("dev_code") or body.get("code")
    assert code, f"No dev code in response: {body}"
    r = api.post(f"{BASE_URL}/api/auth/otp/verify", json={"identifier": identifier, "channel": channel, "code": code})
    assert r.status_code == 200, f"otp/verify failed: {r.status_code} {r.text[:200]}"
    return r.json().get("session_token") or r.json().get("token")


@pytest.fixture(scope="session")
def super_token(api):
    return _otp_login(api, SUPER_ADMIN_EMAIL, "email")


@pytest.fixture(scope="session")
def super_headers(super_token):
    return {"Authorization": f"Bearer {super_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def company_id(api, super_headers):
    r = api.get(f"{BASE_URL}/api/companies", headers=super_headers)
    assert r.status_code == 200, r.text[:200]
    items = _extract_list(r.json(), "companies", "items")
    assert items, "no companies found"
    for c in items:
        if c.get("company_code") == "SKSCO1" or c.get("code") == "SKSCO1":
            return c["company_id"]
    # Prefer one that has employees
    for c in items:
        r = api.get(f"{BASE_URL}/api/admin/employees?company_id={c['company_id']}&limit=1", headers=super_headers)
        if r.status_code == 200 and _extract_list(r.json(), "employees", "items"):
            return c["company_id"]
    return items[0]["company_id"]


def _first_employee(api, headers, cid):
    r = api.get(f"{BASE_URL}/api/admin/employees?company_id={cid}&limit=5", headers=headers)
    if r.status_code != 200:
        return None
    lst = _extract_list(r.json(), "employees", "items")
    return lst[0] if lst else None


# ========== P0 Bulk-correction fields ==========
class TestBulkCorrectionFields:
    def test_fields_list(self, api, super_headers):
        r = api.get(f"{BASE_URL}/api/admin/employees/bulk-correction-fields", headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        fields = r.json().get("fields") or []
        assert len(fields) >= 18, f"expected >=18 fields got {len(fields)}"
        keys = {f["key"] for f in fields}
        for req in ("designation", "uan_no", "esi_ip_no", "employee_group_id", "active"):
            assert req in keys, f"missing required field {req}"


# ========== P0 Bulk-correction dry-run ==========
class TestBulkCorrectionDryRun:
    def test_dry_run_would_update(self, api, super_headers, company_id):
        emp = _first_employee(api, super_headers, company_id)
        if not emp:
            pytest.skip("no employees")
        uid = emp["user_id"]
        original_desig = emp.get("designation")
        payload = {
            "company_id": company_id,
            "dry_run": True,
            "corrections": [{
                "user_id": uid,
                "designation": "TEST_DryRun_Desig",
                "uan_no": "TEST_UAN_777",
            }],
        }
        r = api.post(f"{BASE_URL}/api/admin/employees/bulk-correction", json=payload, headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body.get("dry_run") is True
        applied = body.get("applied") or []
        assert applied, f"expected applied: {body}"
        assert "would_update" in applied[0], f"missing would_update: {applied[0]}"
        assert applied[0]["would_update"].get("designation") == "TEST_DryRun_Desig"
        # Refetch employee - designation should NOT match
        emp2 = _first_employee(api, super_headers, company_id)
        # Find same emp
        if emp2 and emp2.get("user_id") == uid:
            assert emp2.get("designation") == original_desig, "dry_run leaked a real write"


# ========== P0 Bulk-correction real + skipped ==========
class TestBulkCorrectionReal:
    def test_real_update_and_skipped(self, api, super_headers, company_id):
        emp = _first_employee(api, super_headers, company_id)
        if not emp:
            pytest.skip("no employees")
        uid = emp["user_id"]
        test_desig = f"QA_D_{uuid.uuid4().hex[:5]}"
        payload = {
            "company_id": company_id,
            "dry_run": False,
            "corrections": [
                {"user_id": uid, "designation": test_desig},
                {"user_id": "user_doesnotexist_zzz", "name": "Ghost"},
                {"user_id": uid},  # empty patch
            ],
        }
        r = api.post(f"{BASE_URL}/api/admin/employees/bulk-correction", json=payload, headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        skipped = body.get("skipped") or []
        reasons = {s.get("reason") for s in skipped}
        assert "not_found" in reasons, f"expected not_found: {skipped}"
        assert "no_changes" in reasons, f"expected no_changes: {skipped}"
        # Verify persistence
        r = api.get(f"{BASE_URL}/api/admin/employees?company_id={company_id}&limit=100", headers=super_headers)
        emps = _extract_list(r.json(), "employees", "items")
        me = next((e for e in emps if e.get("user_id") == uid), None)
        assert me, "cannot find updated employee"
        assert me.get("designation") == test_desig, f"desig not persisted: {me.get('designation')}"


# ========== P0 Bulk-correction group cascade ==========
class TestBulkCorrectionGroupCascade:
    def test_group_cascade(self, api, super_headers, company_id):
        emp = _first_employee(api, super_headers, company_id)
        if not emp:
            pytest.skip("no employees")
        uid = emp["user_id"]

        g1_name = f"QAGrp1_{uuid.uuid4().hex[:5]}"
        g2_name = f"QAGrp2_{uuid.uuid4().hex[:5]}"
        r1 = api.post(f"{BASE_URL}/api/admin/masters",
                      json={"type": "group", "company_id": company_id, "name": g1_name},
                      headers=super_headers)
        r2 = api.post(f"{BASE_URL}/api/admin/masters",
                      json={"type": "group", "company_id": company_id, "name": g2_name},
                      headers=super_headers)
        assert r1.status_code in (200, 201), f"g1 create: {r1.status_code} {r1.text[:150]}"
        assert r2.status_code in (200, 201), f"g2 create: {r2.status_code} {r2.text[:150]}"
        g1_id = r1.json().get("master_id")
        g2_id = r2.json().get("master_id")

        # Move to g1
        r = api.post(f"{BASE_URL}/api/admin/employees/bulk-correction",
                     json={"company_id": company_id, "dry_run": False,
                           "corrections": [{"user_id": uid, "employee_group_id": g1_id}]},
                     headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        # Move to g2
        r = api.post(f"{BASE_URL}/api/admin/employees/bulk-correction",
                     json={"company_id": company_id, "dry_run": False,
                           "corrections": [{"user_id": uid, "employee_group_id": g2_id}]},
                     headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        # Verify
        r = api.get(f"{BASE_URL}/api/admin/masters?company_id={company_id}&type=group",
                    headers=super_headers)
        items = _extract_list(r.json(), "items", "masters")
        g1 = next((x for x in items if x.get("master_id") == g1_id), {})
        g2 = next((x for x in items if x.get("master_id") == g2_id), {})
        assert uid in (g2.get("member_user_ids") or []), f"user not in g2: {g2}"
        assert uid not in (g1.get("member_user_ids") or []), f"user still in g1: {g1}"


# ========== P0 Bulk-correction 403 for company_admin ==========
class TestBulkCorrectionForbidden:
    def test_company_admin_forbidden(self, api, super_headers, company_id):
        r = api.post(f"{BASE_URL}/api/auth/admin-password-login",
                     json={"email": "admin.skscoltd@sksharma.local", "password": "zmwy4249"})
        if r.status_code != 200:
            pytest.skip(f"company admin login unavailable: {r.status_code} {r.text[:200]}")
        body = r.json()
        tok = body.get("session_token") or body.get("token")
        if not tok:
            # Sometimes returns pin_must_change etc without token
            pytest.skip(f"no token from company admin login: {body}")
        r = api.post(f"{BASE_URL}/api/admin/employees/bulk-correction",
                     json={"company_id": company_id, "dry_run": True,
                           "corrections": [{"user_id": "x"}]},
                     headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:200]}"


# ========== P0 Bulk-import employees ==========
class TestBulkImport:
    def test_bulk_import(self, api, super_headers, company_id):
        emp = _first_employee(api, super_headers, company_id)
        existing_code = emp.get("employee_code") if emp and emp.get("employee_code") else None

        new_code = f"QA_{uuid.uuid4().hex[:5].upper()}"
        new_group = f"QAImpGrp_{uuid.uuid4().hex[:5]}"
        new_dept = f"QAImpDept_{uuid.uuid4().hex[:5]}"
        new_desig = f"QAImpDesig_{uuid.uuid4().hex[:5]}"

        headers_list = ["Emp Code", "Name", "Group", "Department", "Designation", "Gross Salary"]
        body = []
        if existing_code:
            body.append([existing_code, "TEST_UPDATE_NAME", new_group, new_dept, new_desig, 25000])
        body.append([new_code, f"QA New {new_code}", new_group, new_dept, new_desig, 32000])
        mapping = {"employee_code": 0, "name": 1, "employee_group": 2,
                   "department": 3, "designation": 4, "gross_salary": 5}

        payload = {
            "company_id": company_id, "month": "2025-12",
            "headers": headers_list, "body": body, "mapping": mapping, "dry_run": False,
        }
        r = api.post(f"{BASE_URL}/api/admin/attendance-sheet/bulk-import-employees",
                     json=payload, headers=super_headers)
        assert r.status_code == 200, f"bulk-import: {r.status_code} {r.text[:300]}"
        b = r.json()
        assert b.get("ok") is True
        if existing_code:
            assert any(x.get("name") == "TEST_UPDATE_NAME" for x in (b.get("updated") or [])), \
                f"existing not updated: {b.get('updated')}"
        created = b.get("created") or []
        new_user = next((c for c in created if c.get("employee_code") == new_code), None)
        assert new_user, f"new not created: {created}"

        # Verify new user properties via listing
        r = api.get(f"{BASE_URL}/api/admin/employees?company_id={company_id}&limit=500",
                    headers=super_headers)
        emps = _extract_list(r.json(), "employees", "items")
        me = next((e for e in emps if e.get("user_id") == new_user["user_id"]), None)
        if me:
            assert me.get("approved") is False, f"approved: {me.get('approved')}"
            assert me.get("pin_must_change") is True, f"pin_must_change: {me.get('pin_must_change')}"
            assert me.get("role") == "employee"

        # Verify new masters
        r = api.get(f"{BASE_URL}/api/admin/masters?company_id={company_id}&type=group",
                    headers=super_headers)
        items = _extract_list(r.json(), "items", "masters")
        assert any(m.get("name") == new_group for m in items), "group master not created"


# ========== P0 Attendance email config ==========
class TestAttendanceEmailConfig:
    def test_config_filters_invalid(self, api, super_headers, company_id):
        payload = {"recipients": ["good@example.com", "also-good@x.co", "bad-no-at", ""],
                   "enabled": True}
        r = api.put(f"{BASE_URL}/api/admin/companies/{company_id}/attendance-email-config",
                    json=payload, headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        recips = r.json().get("recipients") or []
        assert "good@example.com" in recips
        assert "also-good@x.co" in recips
        assert "bad-no-at" not in recips
        assert "" not in recips


# ========== P0 Attendance email trigger dry-run ==========
class TestAttendanceEmailTrigger:
    def test_trigger_dry_run(self, api, super_headers, company_id):
        r = api.post(
            f"{BASE_URL}/api/admin/attendance-email/trigger-now?dry_run=true&company_id={company_id}",
            headers=super_headers,
        )
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert "results" in body
        results = body.get("results") or []
        for res in results:
            assert not res.get("delivered"), f"unexpected delivered: {res}"
            if "dry_run" in res:
                assert res["dry_run"] is True


# ========== P1 Portal automation ==========
class TestPortalAutomation:
    def test_create_and_poll(self, api, super_headers, company_id):
        r = api.get(f"{BASE_URL}/api/admin/compliance-salary-runs?company_id={company_id}&limit=1",
                    headers=super_headers)
        if r.status_code != 200:
            pytest.skip(f"compliance-salary-runs {r.status_code}")
        items = _extract_list(r.json(), "runs", "items")
        if not items:
            pytest.skip("no compliance salary runs")
        run_id = items[0]["run_id"]

        r = api.post(f"{BASE_URL}/api/admin/portal-automation/jobs",
                     json={"portal": "epfo", "company_id": company_id,
                           "compliance_salary_run_id": run_id},
                     headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        job = r.json()
        assert job.get("status") == "queued", f"initial status: {job.get('status')}"
        job_id = job["job_id"]

        final = "queued"
        steps_seen = 0
        for _ in range(10):
            time.sleep(3)
            r = api.get(f"{BASE_URL}/api/admin/portal-automation/jobs/{job_id}",
                        headers=super_headers)
            if r.status_code == 200:
                j = r.json()
                final = j.get("status")
                steps_seen = len(j.get("steps") or [])
                if final != "queued":
                    break
        assert final in ("running", "completed_login", "paused_captcha", "failed"), \
            f"status did not progress: {final}"
        # steps populated (unless failed early)
        if final != "failed":
            assert steps_seen > 0, "expected steps[] populated"


# ========== P0 FY filter ==========
class TestFYFilter:
    def test_salary_runs_fy(self, api, super_headers):
        r = api.get(f"{BASE_URL}/api/admin/salary-runs?fy_start_year=2025", headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        items = _extract_list(r.json(), "runs", "items")
        for it in items:
            m = it.get("month") or ""
            if not m:
                continue
            assert "2025-04" <= m <= "2026-03", f"salary month out of FY: {m}"

    def test_compliance_runs_fy(self, api, super_headers):
        r = api.get(f"{BASE_URL}/api/admin/compliance-salary-runs?fy_start_year=2025",
                    headers=super_headers)
        assert r.status_code == 200, r.text[:200]
        items = _extract_list(r.json(), "runs", "items")
        for it in items:
            m = it.get("month") or ""
            if not m:
                continue
            assert "2025-04" <= m <= "2026-03", f"compliance month out of FY: {m}"


# ========== P0 Sub-admin READ access ==========
class TestSubAdminRead:
    @pytest.fixture(scope="class")
    def sub_admin_token(self, api, request):
        # Get super headers manually (class-scoped)
        super_tok = _otp_login(api, SUPER_ADMIN_EMAIL, "email")
        super_h = {"Authorization": f"Bearer {super_tok}", "Content-Type": "application/json"}
        email = f"qa.sub.{uuid.uuid4().hex[:6]}@test.local"
        r = api.post(f"{BASE_URL}/api/admin/sub-admins",
                     json={"name": "QA Sub", "email": email, "password": "Testpass1!",
                           "sub_admin_company_scope": "all",
                           "sub_admin_permissions": ["salary_process:read"]},
                     headers=super_h)
        if r.status_code not in (200, 201):
            pytest.skip(f"cannot create sub-admin: {r.status_code} {r.text[:200]}")
        # OTP login as the sub_admin to get a token
        return _otp_login(api, email, "email")

    def test_salary_runs(self, api, sub_admin_token):
        h = {"Authorization": f"Bearer {sub_admin_token}"}
        r = api.get(f"{BASE_URL}/api/admin/salary-runs", headers=h)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"

    def test_salary_run_detail_and_exports(self, api, sub_admin_token):
        h = {"Authorization": f"Bearer {sub_admin_token}"}
        # Need a run_id from super
        super_tok = _otp_login(api, SUPER_ADMIN_EMAIL, "email")
        r = api.get(f"{BASE_URL}/api/admin/salary-runs",
                    headers={"Authorization": f"Bearer {super_tok}"})
        items = _extract_list(r.json(), "runs", "items")
        if not items:
            pytest.skip("no salary runs")
        run_id = items[0]["run_id"]
        r = api.get(f"{BASE_URL}/api/admin/salary-runs/{run_id}", headers=h)
        assert r.status_code == 200, f"detail {r.status_code}: {r.text[:200]}"
        r = api.get(f"{BASE_URL}/api/admin/salary-runs/{run_id}/export.csv", headers=h)
        assert r.status_code == 200, f"csv {r.status_code}: {r.text[:200]}"
        r = api.get(f"{BASE_URL}/api/admin/salary-runs/{run_id}/register.pdf", headers=h)
        assert r.status_code == 200, f"pdf {r.status_code}: {r.text[:200]}"

    def test_compliance(self, api, sub_admin_token):
        h = {"Authorization": f"Bearer {sub_admin_token}"}
        r = api.get(f"{BASE_URL}/api/admin/compliance-salary-runs", headers=h)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        super_tok = _otp_login(api, SUPER_ADMIN_EMAIL, "email")
        r2 = api.get(f"{BASE_URL}/api/admin/compliance-salary-runs",
                     headers={"Authorization": f"Bearer {super_tok}"})
        items = _extract_list(r2.json(), "runs", "items")
        if items:
            run_id = items[0]["run_id"]
            r = api.get(f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/ecr.txt", headers=h)
            assert r.status_code == 200, f"ecr {r.status_code}: {r.text[:200]}"

    def test_bonus(self, api, sub_admin_token):
        h = {"Authorization": f"Bearer {sub_admin_token}"}
        r = api.get(f"{BASE_URL}/api/admin/bonus-runs", headers=h)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        super_tok = _otp_login(api, SUPER_ADMIN_EMAIL, "email")
        r2 = api.get(f"{BASE_URL}/api/admin/bonus-runs",
                     headers={"Authorization": f"Bearer {super_tok}"})
        items = _extract_list(r2.json(), "items", "runs")
        if items:
            run_id = items[0]["run_id"]
            r = api.get(f"{BASE_URL}/api/admin/bonus-runs/{run_id}/report.xlsx", headers=h)
            assert r.status_code == 200, f"xlsx {r.status_code}: {r.text[:200]}"
