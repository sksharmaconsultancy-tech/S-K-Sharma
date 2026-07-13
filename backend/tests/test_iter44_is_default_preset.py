"""Iter-44 regression — is_default_preset semantics.

- Fresh company → GET policy → is_default_preset: true
- After PATCH → is_default_preset: false
- After POST /reset (from freshly-created new company) → is_default_preset: false
  (reset writes attendance_policy_updated_at, so this is intended)
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests


def _load_backend_url() -> str:
    env_file = Path("/app/frontend/.env")
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("EXPO_PUBLIC_BACKEND_URL"):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            if val:
                return val.rstrip("/")
    return os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")


BASE_URL = _load_backend_url()
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL missing"
SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def sa_headers(api):
    r = api.post(f"{BASE_URL}/api/auth/otp/request",
                 json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email"})
    assert r.status_code == 200, r.text
    code = r.json().get("dev_code") or r.json().get("code")
    r = api.post(f"{BASE_URL}/api/auth/otp/verify",
                 json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email", "code": code})
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def fresh_company_admin(api, sa_headers):
    """Create a company + throwaway admin. Yields the admin headers + company_id."""
    suffix = uuid.uuid4().hex[:6]
    phone = f"+91777{uuid.uuid4().int % 10_000_000:07d}"
    r = api.post(f"{BASE_URL}/api/companies", json={
        "name": f"TEST_DefPresetCo {suffix}",
        "address": "1 Preset Rd",
        "office_lat": 12.9, "office_lng": 77.5,
        "geofence_radius_m": 200, "compliance_enabled": True,
        "business_category": "industry",
        "business_subcategory": "Textile",
        "admin_phone": phone,
        "admin_name": "QA Admin",
    }, headers=sa_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    cid = body["company_id"]
    temp_pin = body["admin"]["temp_pin"]

    rl = api.post(f"{BASE_URL}/api/auth/admin-pin-login",
                  json={"identifier": phone, "pin": temp_pin})
    assert rl.status_code == 200, rl.text
    tok = rl.json()["session_token"]
    headers = {"Authorization": f"Bearer {tok}"}

    yield {"company_id": cid, "headers": headers}
    api.delete(f"{BASE_URL}/api/companies/{cid}", headers=sa_headers)


class TestIsDefaultPreset:
    """Verify is_default_preset uses attendance_policy_updated_at instead of
    just the presence of an auto-attached policy."""

    def test_fresh_company_reports_default_preset_true(self, api, fresh_company_admin):
        r = api.get(f"{BASE_URL}/api/attendance/policy",
                    headers=fresh_company_admin["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_default_preset"] is True, (
            "Freshly-created company should report is_default_preset=true "
            f"(admin has not customised yet). Got: {body}"
        )
        # Sanity — policy is still auto-populated from the preset
        assert body["policy"]["shifts"], "policy.shifts should be populated from preset"

    def test_after_patch_is_default_preset_false(self, api, fresh_company_admin):
        h = fresh_company_admin["headers"]
        cur = api.get(f"{BASE_URL}/api/attendance/policy", headers=h).json()["policy"]
        cur["grace_minutes_late"] = 20
        rp = api.patch(f"{BASE_URL}/api/attendance/policy",
                       json={"policy": cur}, headers=h)
        assert rp.status_code == 200, rp.text
        # GET again — should now be false
        r = api.get(f"{BASE_URL}/api/attendance/policy", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["is_default_preset"] is False, body
        assert body["policy"]["grace_minutes_late"] == 20

    def test_after_reset_is_default_preset_false(self, api, fresh_company_admin):
        """Reset also writes attendance_policy_updated_at, so post-reset the
        flag stays false. This is the intended (documented) behavior."""
        h = fresh_company_admin["headers"]
        r = api.post(f"{BASE_URL}/api/attendance/policy/reset", json={}, headers=h)
        assert r.status_code == 200, r.text
        r2 = api.get(f"{BASE_URL}/api/attendance/policy", headers=h)
        assert r2.status_code == 200
        body = r2.json()
        assert body["is_default_preset"] is False, (
            "Reset writes timestamp → is_default_preset should be false. "
            f"Got: {body}"
        )
