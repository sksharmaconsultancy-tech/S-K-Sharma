"""Iter 417 — Backend tests for Smart Punch GPS Diagnostics."""
import os
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://emplo-connect-1.preview.emergentagent.com",
).rstrip("/")

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
KANKANI_ID = "cmp_527fecdd7c"


@pytest.fixture(scope="module")
def emp_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/pin-login",
        json={"login_id": "TEST50", "pin": "123456"},
        timeout=15,
    )
    assert r.status_code == 200, f"emp login failed {r.status_code} {r.text}"
    j = r.json()
    tok = j.get("session_token") or j.get("token") or j.get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def super_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed {r.status_code} {r.text}"
    j = r.json()
    tok = j.get("session_token") or j.get("token") or j.get("access_token")
    assert tok
    return tok


# ------- POST /api/gps-diagnostics ------------------------------------------
class TestGpsDiagnosticsPost:
    def _post(self, token, payload):
        return requests.post(
            f"{BASE_URL}/api/gps-diagnostics",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=15,
        )

    def test_post_success(self, emp_token):
        r = self._post(emp_token, {
            "outcome": "success",
            "latitude": 26.9124, "longitude": 75.7873, "accuracy": 8.5,
            "retry_count": 0, "mock_location": False, "context": "punch",
            "platform": "web", "gps_enabled": True,
            "permission_status": "granted",
        })
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

    def test_post_weak(self, emp_token):
        r = self._post(emp_token, {
            "outcome": "weak", "latitude": 26.91, "longitude": 75.78,
            "accuracy": 120.0, "retry_count": 2, "context": "punch",
        })
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_post_failed(self, emp_token):
        r = self._post(emp_token, {
            "outcome": "failed", "retry_count": 4,
            "failure_reason": "PERMISSION_DENIED",
            "permission_status": "denied", "gps_enabled": False,
            "mock_location": False, "context": "punch",
        })
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_post_unauthenticated(self):
        r = requests.post(
            f"{BASE_URL}/api/gps-diagnostics",
            json={"outcome": "success"},
            timeout=15,
        )
        assert r.status_code == 401, f"expected 401, got {r.status_code}"


# ------- GET /api/admin/gps-diagnostics -------------------------------------
class TestGpsDiagnosticsList:
    def _get(self, token, **params):
        return requests.get(
            f"{BASE_URL}/api/admin/gps-diagnostics",
            headers={"Authorization": f"Bearer {token}"},
            params=params, timeout=15,
        )

    def test_list_super_admin(self, super_token):
        r = self._get(super_token)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "rows" in d and isinstance(d["rows"], list)
        assert "counts" in d
        for k in ("success", "weak", "failed"):
            assert k in d["counts"]
        assert "success_rate" in d
        assert isinstance(d["success_rate"], (int, float))

    def test_filter_outcome_failed(self, super_token):
        r = self._get(super_token, outcome="failed")
        assert r.status_code == 200
        for row in r.json()["rows"]:
            assert row.get("outcome") == "failed"

    def test_filter_date_today(self, super_token):
        r = self._get(super_token, date=TODAY)
        assert r.status_code == 200
        for row in r.json()["rows"]:
            assert row.get("date") == TODAY

    def test_filter_company_id(self, super_token):
        r = self._get(super_token, company_id=KANKANI_ID)
        assert r.status_code == 200
        for row in r.json()["rows"]:
            assert row.get("company_id") == KANKANI_ID

    def test_list_requires_admin(self, emp_token):
        r = self._get(emp_token)
        # Should be forbidden (require_role)
        assert r.status_code in (401, 403), \
            f"expected 401/403 for emp on admin ep, got {r.status_code}"


# ------- GET /api/admin/gps-diagnostics.xlsx --------------------------------
class TestGpsDiagnosticsXlsx:
    def test_xlsx_super_admin(self, super_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/gps-diagnostics.xlsx",
            headers={"Authorization": f"Bearer {super_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]
        ct = r.headers.get("content-type", "")
        assert "spreadsheetml.sheet" in ct or "officedocument" in ct
        # xlsx = zip magic PK\x03\x04
        assert r.content[:2] == b"PK"


# ------- Regression --------------------------------------------------------
class TestAttendanceRegression:
    def test_attendance_today(self, emp_token):
        r = requests.get(
            f"{BASE_URL}/api/attendance/today",
            headers={"Authorization": f"Bearer {emp_token}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text

    def test_attendance_summary(self, emp_token):
        r = requests.get(
            f"{BASE_URL}/api/attendance/summary",
            headers={"Authorization": f"Bearer {emp_token}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
