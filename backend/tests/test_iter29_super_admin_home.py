"""Iteration 29 — Backend regression for the Home dashboard hide-for-super-admin fix.

Frontend change (no backend edits): index.tsx now skips fetching
/api/attendance/summary?days=7 when the logged-in user is super_admin, and hides
DutyHoursSection, bento-history tile, and 'Attendance history' ActionRow.

Backend contract must be unchanged. This test ensures:
  1. /api/attendance/summary?days=7 still works for a fresh employee OTP session.
  2. super_admin OTP still works and /api/auth/me still returns role=super_admin
     (regression — do NOT touch the super_admin PIN).
"""
import os
import uuid
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://emplo-connect-1.preview.emergentagent.com"

API = f"{BASE_URL}/api"
SUPER_EMAIL = "sksharmaconsultancy@gmail.com"


def _otp_login(identifier: str, channel: str = "email"):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/otp/request",
               json={"channel": channel, "identifier": identifier}, timeout=15)
    assert r.status_code == 200, f"otp request failed: {r.status_code} {r.text}"
    code = r.json().get("dev_code") or r.json().get("code")
    assert code, f"no dev_code returned: {r.json()}"
    r2 = s.post(f"{API}/auth/otp/verify",
                json={"channel": channel, "identifier": identifier, "code": code},
                timeout=15)
    assert r2.status_code == 200, f"otp verify failed: {r2.status_code} {r2.text}"
    tok = r2.json().get("session_token") or r2.json().get("access_token")
    assert tok, r2.json()
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s, tok


# ---- super_admin regression -----------------------------------------------
class TestSuperAdminAuthRegression:
    def test_super_admin_otp_login_still_works(self):
        s, tok = _otp_login(SUPER_EMAIL)
        me = s.get(f"{API}/auth/me", timeout=15).json()
        user = me.get("user", me)
        assert user.get("role") == "super_admin", f"got {user.get('role')}"

    def test_attendance_summary_still_available_for_super_admin(self):
        """Even though the frontend now skips this call for super_admin,
        the endpoint itself must still respond 200 (contract unchanged)."""
        s, _ = _otp_login(SUPER_EMAIL)
        r = s.get(f"{API}/attendance/summary?days=7", timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "days" in body and isinstance(body["days"], list)
        assert "window_total_hours" in body
        assert "total_hours_till_today" in body


# ---- employee regression (endpoint must still work) -----------------------
class TestEmployeeAttendanceSummary:
    def test_fresh_employee_can_call_summary(self):
        ident = f"qa.iter29.{uuid.uuid4().hex[:6]}@test.com"
        s, _ = _otp_login(ident)
        me = s.get(f"{API}/auth/me", timeout=15).json()
        user = me.get("user", me)
        assert user.get("role") == "employee", f"expected employee, got {user.get('role')}"
        r = s.get(f"{API}/attendance/summary?days=7", timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body.get("days"), list)
        # days=7 -> 7 buckets
        assert len(body["days"]) == 7
