"""Iter 397 regression suite.

Covers:
  (A) Pure refactor verification for extracted modules:
      - routes/attendance_policy_api.py
      - routes/attendance_reports_api.py
      - routes/attendance_location_api.py
      - routes/employees_admin.py  (full create/delete cycle)
      - routes/actual_salary_process.py
  (B) New Iter 397 one-click portal login plumbing:
      - POST /api/admin/portal-automation/launch-token
      - GET  /api/portal-ext/get-login
      - GET  /api/portal-ext/runner-script
      - GET  /api/admin/portal-automation/runner-download
  (C) Global regression: login, compliance-salary-runs, whatsapp dashboard,
      openapi path count.
"""
from __future__ import annotations

import base64
import io
import os
import time
import uuid
import zipfile

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
CID = "cmp_527fecdd7c"  # Kankani Enterprises


# --------------------------------------------------------------------------- session
@pytest.fixture(scope="session")
def token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("session_token")
    assert tok, "session_token missing"
    return tok


@pytest.fixture(scope="session")
def sess(token) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


# --------------------------------------------------------------------------- Attendance policy
class TestAttendancePolicy:
    def test_policy_get(self, sess):
        r = sess.get(f"{BASE_URL}/api/attendance/policy?company_id={CID}", timeout=30)
        assert r.status_code == 200, r.text[:200]
        assert isinstance(r.json(), dict)

    def test_policy_presets(self, sess):
        r = sess.get(f"{BASE_URL}/api/attendance/policy/presets", timeout=30)
        assert r.status_code == 200
        data = r.json()
        # dict or list — just be non-empty
        assert data, f"presets empty: {data}"

    def test_policy_saved_list(self, sess):
        r = sess.get(f"{BASE_URL}/api/attendance/policy/saved-list?company_id={CID}", timeout=30)
        assert r.status_code == 200

    def test_policy_patch_roundtrip(self, sess):
        # Get original
        r0 = sess.get(f"{BASE_URL}/api/attendance/policy?company_id={CID}", timeout=30)
        assert r0.status_code == 200
        raw = r0.json() or {}
        # Nested under `policy`
        pol = raw.get("policy") or {}
        orig_val = pol.get("grace_minutes_late", 10)
        new_val = 15 if orig_val != 15 else 20
        # PATCH change (company_id is a Query param, not body)
        r1 = sess.patch(
            f"{BASE_URL}/api/attendance/policy?company_id={CID}",
            json={"grace_minutes_late": new_val},
            timeout=30,
        )
        assert r1.status_code == 200, r1.text[:200]
        # Verify persisted
        r2 = sess.get(f"{BASE_URL}/api/attendance/policy?company_id={CID}", timeout=30)
        assert (r2.json().get("policy") or {}).get("grace_minutes_late") == new_val
        # Restore
        r3 = sess.patch(
            f"{BASE_URL}/api/attendance/policy?company_id={CID}",
            json={"grace_minutes_late": orig_val},
            timeout=30,
        )
        assert r3.status_code == 200
        r4 = sess.get(f"{BASE_URL}/api/attendance/policy?company_id={CID}", timeout=30)
        assert (r4.json().get("policy") or {}).get("grace_minutes_late") == orig_val


# --------------------------------------------------------------------------- Attendance reports (exports)
MONTH = "2026-07"
DAILY_DATE = "2026-07-15"


@pytest.mark.parametrize(
    "path,ext,magic",
    [
        (f"/api/admin/attendance/monthly-hours/{CID}/{MONTH}.xlsx", "xlsx", b"PK"),
        (f"/api/admin/attendance/monthly-hours/{CID}/{MONTH}.pdf", "pdf", b"%PDF"),
        (f"/api/admin/attendance/monthly-ot/{CID}/{MONTH}.xlsx", "xlsx", b"PK"),
        (f"/api/admin/attendance/monthly-ot/{CID}/{MONTH}.pdf", "pdf", b"%PDF"),
        (f"/api/admin/attendance/monthly-inout/{CID}/{MONTH}.xlsx", "xlsx", b"PK"),
        (f"/api/admin/attendance/monthly-inout/{CID}/{MONTH}.pdf", "pdf", b"%PDF"),
        (f"/api/admin/attendance/daily/{CID}/{DAILY_DATE}.xlsx", "xlsx", b"PK"),
        (f"/api/admin/attendance/daily/{CID}/{DAILY_DATE}.pdf", "pdf", b"%PDF"),
    ],
)
class TestAttendanceReportsExports:
    def test_export(self, sess, path, ext, magic):
        r = sess.get(f"{BASE_URL}{path}", timeout=60)
        assert r.status_code == 200, f"{path} → {r.status_code} {r.text[:200]}"
        body = r.content
        assert body.startswith(magic), f"{path} bad magic: {body[:8]!r}"
        assert len(body) > 200, f"{path} too small: {len(body)}"


# --------------------------------------------------------------------------- Attendance location
class TestAttendanceLocation:
    def test_flagged(self, sess):
        r = sess.get(f"{BASE_URL}/api/admin/attendance/flagged?company_id={CID}", timeout=30)
        assert r.status_code == 200, r.text[:200]

    def test_location_audit_json(self, sess):
        r = sess.get(f"{BASE_URL}/api/admin/attendance/location-audit?company_id={CID}", timeout=30)
        assert r.status_code == 200

    def test_location_audit_xlsx(self, sess):
        r = sess.get(f"{BASE_URL}/api/admin/attendance/location-audit.xlsx?company_id={CID}", timeout=60)
        assert r.status_code == 200
        assert r.content.startswith(b"PK")
        assert len(r.content) > 200

    def test_history_uses_compute_location_status(self, sess):
        # Regression — this route imports _compute_location_status from attendance_location_api
        r = sess.get(f"{BASE_URL}/api/admin/attendance/history?company_id={CID}&limit=5", timeout=30)
        assert r.status_code == 200, r.text[:200]


# --------------------------------------------------------------------------- Employees admin full cycle
class TestEmployeesAdmin:
    _created_user_id: str | None = None
    _created_phone: str | None = None

    def test_create_employee(self, sess):
        # Unique 10-digit phone starting with 9
        phone10 = "9" + str(int(time.time() * 1000))[-9:]
        TestEmployeesAdmin._created_phone = phone10
        payload = {
            "company_id": CID,
            "name": "REFACTOR TEST EMP",
            "phone": phone10,
            "father_name": "Test Father",
            "gender": "M",
            "dob": "1990-01-01",
            "doj": "2026-01-01",
            "department": "TEST",
            "designation": "Tester",
            "employee_type": "Staff",
        }
        r = sess.post(f"{BASE_URL}/api/admin/employees", json=payload, timeout=60)
        assert r.status_code == 200, f"create failed {r.status_code}: {r.text[:400]}"
        data = r.json()
        uid = data.get("user_id") or (data.get("employee") or {}).get("user_id")
        assert uid, f"no user_id in create response: {data}"
        TestEmployeesAdmin._created_user_id = uid
        # employee_code auto-assigned (may be inside "employee" nested)
        emp_code = data.get("employee_code") or (data.get("employee") or {}).get("employee_code")
        assert emp_code, f"auto employee_code missing: {data}"

    def test_verify_employee_in_list(self, sess):
        assert TestEmployeesAdmin._created_user_id, "no created uid"
        r = sess.get(f"{BASE_URL}/api/admin/employees?company_id={CID}", timeout=60)
        assert r.status_code == 200
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("employees") or rows.get("items") or rows.get("rows") or []
        uids = [e.get("user_id") for e in rows if isinstance(e, dict)]
        assert TestEmployeesAdmin._created_user_id in uids, "created employee not in list"

    def test_delete_employee(self, sess):
        uid = TestEmployeesAdmin._created_user_id
        assert uid
        r = sess.delete(f"{BASE_URL}/api/admin/employees/{uid}", timeout=60)
        assert r.status_code == 200, r.text[:200]

    def test_verify_deleted(self, sess):
        uid = TestEmployeesAdmin._created_user_id
        r = sess.get(f"{BASE_URL}/api/admin/employees?company_id={CID}", timeout=60)
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("employees") or rows.get("items") or rows.get("rows") or []
        uids = [e.get("user_id") for e in rows if isinstance(e, dict)]
        assert uid not in uids, "employee still present after delete"


# --------------------------------------------------------------------------- Bulk import
class TestBulkImport:
    def test_template_xlsx(self, sess):
        r = sess.get(f"{BASE_URL}/api/admin/employees/bulk-import-template.xlsx", timeout=30)
        assert r.status_code == 200
        assert r.content.startswith(b"PK")
        assert len(r.content) > 500

    def test_bulk_import_parse(self, sess):
        # Build a small valid xlsx in memory
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Name", "Phone", "Department"])
        ws.append(["Alpha Beta", "9000000001", "TEST"])
        buf = io.BytesIO()
        wb.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        r = sess.post(
            f"{BASE_URL}/api/admin/employees/bulk-import-parse",
            json={"file_base64": b64, "filename": "t.xlsx"},
            timeout=60,
        )
        # 200 expected, but if 4xx must be clean not 500
        assert r.status_code < 500, f"bulk-import-parse 5xx: {r.status_code} {r.text[:300]}"
        if r.status_code == 200:
            data = r.json()
            assert "headers" in data and "rows" in data


# --------------------------------------------------------------------------- Actual salary regression
class TestActualSalary:
    def test_branches_list(self, sess):
        r = sess.get(f"{BASE_URL}/api/admin/branches?company_id={CID}", timeout=30)
        assert r.status_code == 200

    def test_actual_salary_process_empty_payload(self, sess):
        r = sess.post(
            f"{BASE_URL}/api/admin/actual-salary-process",
            json={},
            timeout=30,
        )
        # Missing payload → clean 4xx, not 500
        assert 400 <= r.status_code < 500, f"expected 4xx got {r.status_code}: {r.text[:200]}"


# --------------------------------------------------------------------------- NEW portal login endpoints (Iter 397)
class TestPortalLoginPlumbing:
    _launch_token: str | None = None

    def test_launch_token_requires_auth(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/portal-automation/launch-token?company_id={CID}",
            timeout=30,
        )
        assert r.status_code == 401, f"expected 401 without auth, got {r.status_code}"

    def test_launch_token_ok(self, sess):
        r = sess.post(
            f"{BASE_URL}/api/admin/portal-automation/launch-token?company_id={CID}",
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert data.get("ok") is True
        tok = data.get("token")
        assert isinstance(tok, str) and len(tok) > 20
        TestPortalLoginPlumbing._launch_token = tok

    def test_get_login_with_valid_token(self):
        tok = TestPortalLoginPlumbing._launch_token
        assert tok
        r = requests.get(
            f"{BASE_URL}/api/portal-ext/get-login",
            params={"token": tok, "portal": "epfo"},
            timeout=30,
        )
        # 200 with placeholders is fine; 412 (no login saved) is also acceptable per code path
        assert r.status_code in (200, 412), f"got {r.status_code}: {r.text[:200]}"
        if r.status_code == 200:
            data = r.json()
            assert data.get("ok") is True
            assert "user_id" in data and "password" in data

    def test_get_login_invalid_token(self):
        r = requests.get(
            f"{BASE_URL}/api/portal-ext/get-login",
            params={"token": "WRONG_INVALID_TOKEN_XYZ", "portal": "epfo"},
            timeout=30,
        )
        assert r.status_code == 401


# --------------------------------------------------------------------------- Runner download & script
class TestRunner:
    _pc_token: str | None = None

    def test_runner_download_requires_auth(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/portal-automation/runner-download",
            params={"api_base": "https://x.example.com", "company_id": CID},
            timeout=30,
        )
        assert r.status_code == 401

    def test_runner_download_zip_contains_listener(self, sess):
        r = sess.get(
            f"{BASE_URL}/api/admin/portal-automation/runner-download",
            params={"api_base": "https://x.example.com", "company_id": CID},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:200]
        assert r.content.startswith(b"PK")
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        assert "run_listener.bat" in names, f"missing run_listener.bat: {names}"
        assert "sks_launcher.py" in names
        assert "config.json" in names
        cfg = zf.read("config.json").decode()
        assert "token" in cfg
        # Extract embedded token for runner-script test
        import json as _json
        TestRunner._pc_token = _json.loads(cfg).get("token")

    def test_runner_script(self):
        tok = TestRunner._pc_token
        assert tok, "no pc runner token"
        r = requests.get(
            f"{BASE_URL}/api/portal-ext/runner-script",
            params={"token": tok},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert data.get("version") == "6", f"version={data.get('version')}"
        code = data.get("code") or ""
        assert "listen" in code.lower(), "runner code missing 'listen'"
        assert "btnCloseModal" in code, "runner code missing 'btnCloseModal'"

    def test_runner_script_invalid_token(self):
        r = requests.get(
            f"{BASE_URL}/api/portal-ext/runner-script",
            params={"token": "WRONG"},
            timeout=30,
        )
        assert r.status_code == 401


# --------------------------------------------------------------------------- Global regression
class TestGlobalRegression:
    def test_compliance_salary_runs(self, sess):
        r = sess.get(f"{BASE_URL}/api/admin/compliance-salary-runs?limit=1", timeout=30)
        assert r.status_code == 200

    def test_whatsapp_dashboard(self, sess):
        r = sess.get(f"{BASE_URL}/api/admin/whatsapp/dashboard?company_id={CID}", timeout=30)
        assert r.status_code == 200

    def test_openapi_path_count(self):
        # openapi is only served internally on port 8001 (ingress strips
        # non-/api paths). We fetch it from inside the pod.
        try:
            r = requests.get("http://localhost:8001/openapi.json", timeout=30)
        except Exception as e:
            pytest.skip(f"openapi not reachable internally: {e}")
        assert r.status_code == 200
        paths = r.json().get("paths") or {}
        # Expected ~696 per problem statement. Allow small drift (695-700)
        # to accommodate the 2 new Iter-397 aliases (launch-token + get-login).
        assert 690 <= len(paths) <= 705, f"openapi path count = {len(paths)} (expected ~696)"
