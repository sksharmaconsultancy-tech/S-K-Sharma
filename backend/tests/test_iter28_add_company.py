"""Iteration 28 — Verify Add Company (submit-company) flow still succeeds via API.

Focus: the ScrollView wrapper fix in /app/frontend/app/companies.tsx should not have
affected the API contract. We validate the endpoint the modal calls (POST /companies)
plus the edit (PATCH) as super_admin.
"""
import os
import uuid
import time

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # allow fallback for test collection but tests should skip if missing
    BASE_URL = "https://emplo-connect-1.preview.emergentagent.com"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"


@pytest.fixture(scope="module")
def super_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/otp/request",
               json={"channel": "email", "identifier": SUPER_EMAIL})
    assert r.status_code == 200, f"OTP request failed: {r.status_code} {r.text}"
    j = r.json()
    code = j.get("dev_code") or j.get("code")
    assert code, f"OTP dev-mode did not return code: {j}"
    r2 = s.post(f"{BASE_URL}/api/auth/otp/verify",
                json={"channel": "email", "identifier": SUPER_EMAIL, "code": code})
    assert r2.status_code == 200, f"OTP verify failed: {r2.status_code} {r2.text}"
    tok = r2.json().get("session_token") or r2.json().get("access_token") or r2.json().get("token")
    assert tok, f"No token in verify response: {r2.json()}"
    s.headers.update({"Authorization": f"Bearer {tok}"})
    # confirm role
    me_resp = s.get(f"{BASE_URL}/api/auth/me").json()
    me = me_resp.get("user", me_resp)
    assert me.get("role") == "super_admin", f"Expected super_admin, got {me.get('role')}"
    yield s


@pytest.fixture(scope="module")
def ephemeral_company_ids():
    ids = []
    yield ids


def test_create_company_via_modal_payload(super_session, ephemeral_company_ids):
    """Simulate the exact payload the sheet's Save button sends."""
    suffix = uuid.uuid4().hex[:4].upper()
    code = f"IT28{suffix}"
    payload = {
        "name": f"TEST_iter28_{suffix}",
        "address": "Bangalore, KA",
        "office_lat": 12.9716,
        "office_lng": 77.5946,
        "geofence_radius_m": 200,
        "compliance_enabled": True,
        "company_code": code,
    }
    r = super_session.post(f"{BASE_URL}/api/companies", json=payload)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("name") == payload["name"]
    assert body.get("company_code") == code
    assert body.get("office_lat") == pytest.approx(12.9716, abs=1e-4)
    ephemeral_company_ids.append(body["company_id"])


def test_created_company_appears_in_list(super_session, ephemeral_company_ids):
    assert ephemeral_company_ids, "prior test should have created a company"
    r = super_session.get(f"{BASE_URL}/api/companies")
    assert r.status_code == 200
    ids = [c["company_id"] for c in r.json().get("companies", [])]
    assert ephemeral_company_ids[0] in ids


def test_edit_company_via_modal_payload(super_session, ephemeral_company_ids):
    cid = ephemeral_company_ids[0]
    payload = {
        "name": f"TEST_iter28_edited_{cid[-4:]}",
        "address": "Bangalore Edited",
        "office_lat": 12.9716,
        "office_lng": 77.5946,
        "geofence_radius_m": 250,
        "compliance_enabled": False,
    }
    r = super_session.patch(f"{BASE_URL}/api/companies/{cid}", json=payload)
    assert r.status_code == 200, f"PATCH failed {r.status_code}: {r.text}"
    body = r.json()
    assert body["geofence_radius_m"] == 250
    assert body["compliance_enabled"] is False


def test_cleanup_delete_company(super_session, ephemeral_company_ids):
    for cid in ephemeral_company_ids:
        r = super_session.delete(f"{BASE_URL}/api/companies/{cid}?force=true")
        assert r.status_code in (200, 204), f"Delete failed {r.status_code}: {r.text}"
