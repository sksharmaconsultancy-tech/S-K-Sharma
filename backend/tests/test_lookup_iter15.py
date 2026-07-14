"""Iter 15 — Verify public GET /api/companies/lookup/{code} endpoint contract.

Cases:
  * Valid code (unauthenticated) => 200 with {company_id, name, company_code}
  * Unknown code (unauthenticated) => 404 with friendly 'not recognised' detail
  * Regression: /api/companies/by-code/{code} still requires auth => 401
"""
from __future__ import annotations
import os
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient


for env_path in [Path("/app/backend/.env"), Path("/app/frontend/.env")]:
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v.strip('"').strip("'"))

BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "Public backend URL not configured"

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_ADMIN_PIN = "246810"


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(api):
    r = api.post(
        f"{BASE_URL}/api/auth/admin-pin-login",
        json={"identifier": SUPER_ADMIN_EMAIL, "pin": SUPER_ADMIN_PIN},
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def seeded_company(api, admin_token, db):
    """Get an existing company or seed one for the test run."""
    r = api.get(
        f"{BASE_URL}/api/companies",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    companies = r.json().get("companies", [])
    created = False
    if companies:
        comp = companies[0]
    else:
        cr = api.post(
            f"{BASE_URL}/api/companies",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "name": "TEST_Iter15_Company",
                "address": "Bengaluru",
                "office_lat": 12.9716,
                "office_lng": 77.5946,
                "geofence_radius_m": 200,
            },
        )
        assert cr.status_code in (200, 201), cr.text
        comp = cr.json()
        created = True

    yield comp

    if created:
        cid = comp.get("company_id")
        if cid:
            api.delete(
                f"{BASE_URL}/api/companies/{cid}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )


class TestPublicLookup:
    def test_valid_code_unauthenticated_returns_200(self, seeded_company):
        code = seeded_company["company_code"]
        # NOTE: fresh requests session with no auth header
        r = requests.get(f"{BASE_URL}/api/companies/lookup/{code}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("company_id") == seeded_company["company_id"]
        assert body.get("name") == seeded_company["name"]
        assert body.get("company_code") == code
        # Ensure no sensitive fields leak
        assert "office_lat" not in body
        assert "office_lng" not in body
        assert "_id" not in body

    def test_lowercase_code_is_normalised(self, seeded_company):
        code = seeded_company["company_code"].lower()
        r = requests.get(f"{BASE_URL}/api/companies/lookup/{code}")
        assert r.status_code == 200, r.text
        assert r.json()["company_code"] == seeded_company["company_code"]

    def test_unknown_code_returns_404(self):
        r = requests.get(f"{BASE_URL}/api/companies/lookup/ZZZZZZ_NOPE")
        assert r.status_code == 404
        detail = r.json().get("detail", "").lower()
        assert "not recognised" in detail or "not recognized" in detail

    def test_by_code_still_requires_auth(self, seeded_company):
        code = seeded_company["company_code"]
        r = requests.get(f"{BASE_URL}/api/companies/by-code/{code}")
        assert r.status_code in (401, 403), (
            f"by-code should be auth-protected but returned {r.status_code}: {r.text}"
        )
