"""Iter-43 backend tests — Feature 1 (Business Type dropdown on Firm Master)
and Feature 2 (Attendance Policy per business type).

These tests hit the public preview URL (EXPO_PUBLIC_BACKEND_URL) so we exercise
exactly what the mobile client does. The suite is intentionally lightweight:
one class per feature, focused on happy-paths + a few edge cases the spec
called out.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def _load_backend_url() -> str:
    """Pull EXPO_PUBLIC_BACKEND_URL out of frontend/.env — the public preview
    URL end-users hit."""
    env_file = Path("/app/frontend/.env")
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("EXPO_PUBLIC_BACKEND_URL"):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            if val:
                return val.rstrip("/")
    return os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")


BASE_URL = _load_backend_url()
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL missing in /app/frontend/.env"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def api():
    """Shared requests session with JSON default header."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def super_admin_token(api) -> str:
    """OTP-based session token for the hard-coded super admin. OTP dev mode is
    on so /auth/otp/request returns the code back in the response — no email
    round-trip needed. This flow does NOT touch pin_hash, so the guard in
    test_credentials.md is respected."""
    r = api.post(f"{BASE_URL}/api/auth/otp/request", json={
        "identifier": SUPER_ADMIN_EMAIL, "channel": "email"
    })
    assert r.status_code == 200, r.text
    body = r.json()
    code = body.get("dev_code") or body.get("code")
    assert code, f"Expected dev_code in OTP response: {body}"

    r = api.post(f"{BASE_URL}/api/auth/otp/verify", json={
        "identifier": SUPER_ADMIN_EMAIL, "channel": "email", "code": code
    })
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token")
    assert tok, "No session_token in OTP verify response"
    user = r.json().get("user") or {}
    assert user.get("role") == "super_admin", f"Wrong role: {user}"
    return tok


@pytest.fixture
def sa_headers(super_admin_token) -> dict:
    return {"Authorization": f"Bearer {super_admin_token}"}


# --------------------------------------------------------------------------- #
# Feature 1 — Firm Master "Business Type" dropdown
# --------------------------------------------------------------------------- #
INDUSTRY_SUBS_EXPECTED = {
    "Textile", "Food & Beverage", "Polybag / Plastics", "Engineering",
    "Automobile Components", "Chemical", "Pharmaceutical", "Steel & Metal",
    "Cement", "Electronics & Electrical", "Paper & Packaging", "Leather",
    "Rubber", "Furniture / Wood", "Fertilizer", "Gems & Jewellery",
    "Printing & Publishing", "Ceramics & Tiles", "Glass", "Agro / Dairy",
    "Mining & Minerals", "Oil & Gas", "Marine / Seafood", "Handicrafts",
    "Other Industry",
}


class TestBusinessCategories:
    """Feature 1 — public taxonomy + create/update company with business_category."""

    def test_public_business_categories(self, api):
        r = api.get(f"{BASE_URL}/api/business-categories")
        assert r.status_code == 200, r.text
        data = r.json()
        cats = data.get("categories")
        assert isinstance(cats, list), "categories must be a list"
        assert len(cats) == 9, f"Expected 9 categories, got {len(cats)}"

        industry = next((c for c in cats if c["key"] == "industry"), None)
        assert industry is not None
        subs = set(industry.get("subcategories") or [])
        assert len(subs) == 25, f"Industry should have 25 sub-types, got {len(subs)}"
        missing = INDUSTRY_SUBS_EXPECTED - subs
        assert not missing, f"Missing industry sub-types: {missing}"

    def test_create_company_industry_textile(self, api, sa_headers):
        suffix = uuid.uuid4().hex[:6]
        payload = {
            "name": f"TEST_Textile Ltd {suffix}",
            "address": "1 Textile Rd",
            "office_lat": 12.9, "office_lng": 77.5,
            "geofence_radius_m": 200,
            "compliance_enabled": True,
            "business_category": "industry",
            "business_subcategory": "Textile",
        }
        r = api.post(f"{BASE_URL}/api/companies", json=payload, headers=sa_headers)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["business_category"] == "industry"
        assert c["business_subcategory"] == "Textile"
        pol = c.get("attendance_policy")
        assert pol, "attendance_policy must be auto-attached"
        shift_names = [s["name"] for s in pol["shifts"]]
        assert shift_names == ["Shift A", "Shift B", "Shift C"], shift_names
        # cleanup
        api.delete(f"{BASE_URL}/api/companies/{c['company_id']}", headers=sa_headers)

    def test_create_company_hospital(self, api, sa_headers):
        suffix = uuid.uuid4().hex[:6]
        r = api.post(f"{BASE_URL}/api/companies", json={
            "name": f"TEST_Hospital {suffix}",
            "address": "1 Hospital Rd",
            "office_lat": 12.9, "office_lng": 77.5,
            "geofence_radius_m": 200, "compliance_enabled": True,
            "business_category": "hospital",
        }, headers=sa_headers)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["business_category"] == "hospital"
        assert c.get("business_subcategory") in (None, "")
        pol = c["attendance_policy"]
        assert len(pol["shifts"]) == 3
        assert pol["weekly_off_days"] == []
        assert pol["night_shift_allowance_enabled"] is True
        api.delete(f"{BASE_URL}/api/companies/{c['company_id']}", headers=sa_headers)

    def test_industry_without_subtype_rejected(self, api, sa_headers):
        r = api.post(f"{BASE_URL}/api/companies", json={
            "name": "TEST_IndustryNoSub",
            "address": "x",
            "office_lat": 0, "office_lng": 0,
            "geofence_radius_m": 200, "compliance_enabled": True,
            "business_category": "industry",
        }, headers=sa_headers)
        assert r.status_code == 400, r.text
        detail = (r.json().get("detail") or "").lower()
        assert "sub-type" in detail or "sub type" in detail, detail

    def test_invalid_category_rejected(self, api, sa_headers):
        r = api.post(f"{BASE_URL}/api/companies", json={
            "name": "TEST_Invalid",
            "address": "x", "office_lat": 0, "office_lng": 0,
            "geofence_radius_m": 200, "compliance_enabled": True,
            "business_category": "invalid_key",
        }, headers=sa_headers)
        assert r.status_code == 400, r.text

    def test_patch_company_category(self, api, sa_headers):
        suffix = uuid.uuid4().hex[:6]
        r = api.post(f"{BASE_URL}/api/companies", json={
            "name": f"TEST_PatchCo {suffix}", "address": "x",
            "office_lat": 0, "office_lng": 0,
            "geofence_radius_m": 200, "compliance_enabled": True,
            "business_category": "it_company",
        }, headers=sa_headers)
        assert r.status_code == 200, r.text
        cid = r.json()["company_id"]
        r2 = api.patch(f"{BASE_URL}/api/companies/{cid}", json={
            "business_category": "school",
        }, headers=sa_headers)
        assert r2.status_code == 200, r2.text
        # verify persisted
        r3 = api.get(f"{BASE_URL}/api/companies", headers=sa_headers)
        assert r3.status_code == 200
        found = next((x for x in r3.json().get("companies", []) if x["company_id"] == cid), None)
        assert found and found["business_category"] == "school"
        api.delete(f"{BASE_URL}/api/companies/{cid}", headers=sa_headers)

    def test_company_register_backcompat_nature_only(self, api):
        """Public /api/auth/company-register should still accept a plain
        `nature_of_business` string when the new dropdown fields are omitted."""
        suffix = uuid.uuid4().hex[:6]
        phone = f"+91999{uuid.uuid4().int % 10_000_000:07d}"
        r = api.post(f"{BASE_URL}/api/auth/company-register", json={
            "company_name": f"TEST_BackCompat {suffix}",
            "address": "1 Legacy Rd",
            "city": "Bangalore",
            "state": "Karnataka",
            "contact_name": "QA Owner",
            "contact_mobile": phone,
            "contact_email": f"qa_{suffix}@test.com",
            "nature_of_business": "Some Legacy Textile Mill",
            "pin": "482910",
            "employee_count": 10,
        })
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True


# --------------------------------------------------------------------------- #
# Feature 2 — Attendance Policy
# --------------------------------------------------------------------------- #
@pytest.fixture
def company_admin_ctx(api, sa_headers):
    """Provisions a fresh company + company_admin (via Path B on POST
    /companies with admin_phone), yields the context, then cleans up. Using a
    throwaway admin avoids ever touching the real super-admin PIN."""
    suffix = uuid.uuid4().hex[:6]
    phone = f"+91888{uuid.uuid4().int % 10_000_000:07d}"
    r = api.post(f"{BASE_URL}/api/companies", json={
        "name": f"TEST_PolicyCo {suffix}",
        "address": "1 Policy Rd",
        "office_lat": 12.9, "office_lng": 77.5,
        "geofence_radius_m": 200, "compliance_enabled": True,
        "business_category": "industry",
        "business_subcategory": "Textile",
        "admin_phone": phone,
        "admin_name": "QA Admin",
    }, headers=sa_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    admin = body["admin"]
    temp_pin = admin["temp_pin"]

    # Login as company_admin via PIN
    rl = api.post(f"{BASE_URL}/api/auth/admin-pin-login", json={
        "identifier": admin["phone"], "pin": temp_pin,
    })
    assert rl.status_code == 200, rl.text
    admin_token = rl.json().get("session_token")
    assert admin_token, rl.text

    ctx = {
        "company_id": body["company_id"],
        "admin_user_id": admin["user_id"],
        "admin_token": admin_token,
        "admin_headers": {"Authorization": f"Bearer {admin_token}"},
    }
    yield ctx
    # cleanup — delete company (cascades users in most flows; if not, still ok)
    api.delete(f"{BASE_URL}/api/companies/{ctx['company_id']}", headers=sa_headers)


class TestAttendancePolicy:

    def test_policy_presets_list(self, api, sa_headers):
        r = api.get(f"{BASE_URL}/api/attendance/policy/presets", headers=sa_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        presets = body.get("presets") or []
        assert len(presets) == 9, f"Expected 9 presets, got {len(presets)}"
        assert body.get("weekday_labels") == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        # Sanity: each preset has a policy with shifts
        for p in presets:
            assert "policy" in p and p["policy"].get("shifts")

    def test_super_admin_get_policy_requires_company_id(self, api, sa_headers):
        r = api.get(f"{BASE_URL}/api/attendance/policy", headers=sa_headers)
        assert r.status_code == 400, r.text

    def test_super_admin_get_policy_with_company_id(self, api, sa_headers, company_admin_ctx):
        cid = company_admin_ctx["company_id"]
        r = api.get(
            f"{BASE_URL}/api/attendance/policy",
            params={"company_id": cid}, headers=sa_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["company_id"] == cid
        pol = body["policy"]
        for key in ["shifts", "weekly_off_days", "grace_minutes_late",
                    "half_day_hours", "full_day_hours", "break_hours",
                    "overtime_threshold_hours", "overtime_multiplier",
                    "night_shift_allowance_enabled", "night_shift_start",
                    "night_shift_end"]:
            assert key in pol, f"Missing key {key} in policy"

    def test_company_admin_get_own_policy(self, api, company_admin_ctx):
        r = api.get(f"{BASE_URL}/api/attendance/policy",
                    headers=company_admin_ctx["admin_headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["company_id"] == company_admin_ctx["company_id"]
        assert "is_default_preset" in body
        assert body["business_category"] == "industry"

    def test_patch_policy_grace(self, api, company_admin_ctx):
        headers = company_admin_ctx["admin_headers"]
        # Read current policy
        cur = api.get(f"{BASE_URL}/api/attendance/policy", headers=headers).json()["policy"]
        cur["grace_minutes_late"] = 15
        r = api.patch(f"{BASE_URL}/api/attendance/policy",
                      json={"policy": cur}, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["policy"]["grace_minutes_late"] == 15
        # verify persisted
        again = api.get(f"{BASE_URL}/api/attendance/policy", headers=headers).json()
        assert again["policy"]["grace_minutes_late"] == 15

    def test_patch_policy_duplicate_shift_names(self, api, company_admin_ctx):
        headers = company_admin_ctx["admin_headers"]
        cur = api.get(f"{BASE_URL}/api/attendance/policy", headers=headers).json()["policy"]
        cur["shifts"] = [
            {"name": "Shift A", "start": "06:00", "end": "14:00"},
            {"name": "Shift A", "start": "14:00", "end": "22:00"},
        ]
        r = api.patch(f"{BASE_URL}/api/attendance/policy",
                      json={"policy": cur}, headers=headers)
        assert r.status_code == 400, r.text
        assert "duplicate" in (r.json().get("detail") or "").lower()

    def test_patch_policy_halfday_ge_fullday(self, api, company_admin_ctx):
        headers = company_admin_ctx["admin_headers"]
        cur = api.get(f"{BASE_URL}/api/attendance/policy", headers=headers).json()["policy"]
        cur["half_day_hours"] = 8.0
        cur["full_day_hours"] = 8.0
        r = api.patch(f"{BASE_URL}/api/attendance/policy",
                      json={"policy": cur}, headers=headers)
        assert r.status_code == 400, r.text

    def test_patch_policy_bad_hhmm(self, api, company_admin_ctx):
        headers = company_admin_ctx["admin_headers"]
        cur = api.get(f"{BASE_URL}/api/attendance/policy", headers=headers).json()["policy"]
        cur["shifts"] = [{"name": "General", "start": "25:00", "end": "18:00"}]
        r = api.patch(f"{BASE_URL}/api/attendance/policy",
                      json={"policy": cur}, headers=headers)
        assert r.status_code == 400, r.text

    def test_reset_policy_restores_preset(self, api, company_admin_ctx):
        headers = company_admin_ctx["admin_headers"]
        # First, mutate grace
        cur = api.get(f"{BASE_URL}/api/attendance/policy", headers=headers).json()["policy"]
        cur["grace_minutes_late"] = 42
        api.patch(f"{BASE_URL}/api/attendance/policy", json={"policy": cur}, headers=headers)
        # Now reset
        r = api.post(f"{BASE_URL}/api/attendance/policy/reset", json={}, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        pol = body["policy"]
        # Industry preset expected values (see ATTENDANCE_POLICY_PRESETS)
        assert pol["grace_minutes_late"] == 10
        assert [s["name"] for s in pol["shifts"]] == ["Shift A", "Shift B", "Shift C"]
        assert pol["overtime_multiplier"] == 2.0
        assert pol["overtime_threshold_hours"] == 8.0
        assert pol["night_shift_allowance_enabled"] is True
        assert pol["weekly_off_days"] == [6]
