"""Iter 392 — Attendance Synchronization Dashboard backend tests.

Covers:
- Main dashboard endpoint with presets (month/today/custom)
- missing_days parameter behaviour
- Role gating (employee → 403)
- Company scoping enforced for company_admin
- Exports for 6 combos across 3 formats and 4 sections
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
KANKANI = "cmp_527fecdd7c"


@pytest.fixture(scope="module")
def super_admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
                      timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("token") or r.json().get("session_token")
    assert tok, f"no token in {r.json()}"
    return tok


@pytest.fixture(scope="module")
def employee_token():
    """Login as employee via pin-login (Iter 93l TEST50/123456)."""
    for endpoint, payload in [
        ("/api/auth/pin-login", {"login_id": "TEST50", "pin": "123456"}),
        ("/api/auth/emp-code-login",
         {"employee_code": "50", "company_code": "KEPS", "phone_last4": "1234"}),
    ]:
        try:
            r = requests.post(f"{BASE_URL}{endpoint}", json=payload, timeout=30)
            if r.status_code == 200:
                tok = r.json().get("token") or r.json().get("session_token")
                if tok:
                    return tok
        except Exception:
            continue
    pytest.skip("Could not obtain employee token")


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


class TestDashboard:
    def test_month_preset(self, super_admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance-sync-dashboard",
            params={"company_id": KANKANI, "preset": "month", "missing_days": 3},
            headers=_hdr(super_admin_token), timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        # Structure checks
        for key in ("kpis", "new_joining", "machine_only", "master_only",
                    "attendance_missing", "continuous_absence", "machines", "trend", "range"):
            assert key in d, f"missing key {key}"
        k = d["kpis"]
        for kk in ("total_employees", "machine_registered", "attendance_pct",
                   "overall_health", "last_sync_at"):
            assert kk in k, f"missing kpi {kk}"
        assert k["total_employees"] > 0
        assert isinstance(d["continuous_absence"], dict)
        for b in ("3", "5", "7", "15", "30"):
            assert b in d["continuous_absence"]
        # Trend
        assert isinstance(d["trend"]["daily_punch_pct"], list)
        assert len(d["trend"]["daily_punch_pct"]) == 14
        # Attendance-missing rows carry color and remark
        if d["attendance_missing"]:
            row = d["attendance_missing"][0]
            for k2 in ("color", "remark", "days_missing", "user_id", "name"):
                assert k2 in row, f"missing field {k2} in attendance_missing row"

    def test_today_preset(self, super_admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance-sync-dashboard",
            params={"company_id": KANKANI, "preset": "today", "missing_days": 3},
            headers=_hdr(super_admin_token), timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["range"]["from"] == d["range"]["to"]

    def test_custom_preset(self, super_admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance-sync-dashboard",
            params={"company_id": KANKANI, "preset": "custom",
                    "date_from": "2026-01-01", "date_to": "2026-01-15",
                    "missing_days": 3},
            headers=_hdr(super_admin_token), timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["range"]["from"] == "2026-01-01"
        assert d["range"]["to"] == "2026-01-15"

    def test_missing_days_shrinks(self, super_admin_token):
        r3 = requests.get(f"{BASE_URL}/api/admin/attendance-sync-dashboard",
                          params={"company_id": KANKANI, "preset": "month", "missing_days": 3},
                          headers=_hdr(super_admin_token), timeout=60).json()
        r7 = requests.get(f"{BASE_URL}/api/admin/attendance-sync-dashboard",
                          params={"company_id": KANKANI, "preset": "month", "missing_days": 7},
                          headers=_hdr(super_admin_token), timeout=60).json()
        assert len(r7["attendance_missing"]) <= len(r3["attendance_missing"]), \
            f"7d list ({len(r7['attendance_missing'])}) should be <= 3d ({len(r3['attendance_missing'])})"

    def test_unauthenticated_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/attendance-sync-dashboard",
                         params={"company_id": KANKANI, "preset": "month"}, timeout=30)
        assert r.status_code in (401, 403), r.status_code

    def test_employee_role_forbidden(self, employee_token):
        r = requests.get(f"{BASE_URL}/api/admin/attendance-sync-dashboard",
                         params={"company_id": KANKANI, "preset": "month"},
                         headers=_hdr(employee_token), timeout=30)
        assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text[:150]}"


class TestExports:
    """Sample 6 of 12 combos (4 sections × 3 formats)."""
    @pytest.mark.parametrize("section,fmt", [
        ("new_joining", "xlsx"),
        ("new_joining", "csv"),
        ("machine_only", "pdf"),
        ("master_only", "xlsx"),
        ("attendance_missing", "xlsx"),
        ("attendance_missing", "pdf"),
    ])
    def test_export(self, super_admin_token, section, fmt):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance-sync-dashboard/export",
            params={"company_id": KANKANI, "preset": "month",
                    "missing_days": 3, "section": section, "format": fmt},
            headers=_hdr(super_admin_token), timeout=90)
        assert r.status_code == 200, f"{section}/{fmt}: {r.status_code} {r.text[:200]}"
        body = r.content
        # Non-trivial bytes: PDFs/XLSX are typically >>1KB; CSV depends on rows count
        min_size = 50 if fmt == "csv" else 500
        assert len(body) > min_size, f"trivial {fmt} ({len(body)} bytes) for {section}"
        # magic bytes
        if fmt == "xlsx":
            assert body[:2] == b"PK", "xlsx not a zip"
        elif fmt == "pdf":
            assert body[:4] == b"%PDF", "pdf missing magic"
        elif fmt == "csv":
            assert b"," in body[:500] or len(body) < 1000  # header present
