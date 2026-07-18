"""Iter 195 — Process Command Center readiness endpoint tests."""
import os
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL")
            or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
KANKANI = "cmp_527fecdd7c"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}"}


def test_readiness_ok(hdr):
    r = requests.get(
        f"{BASE_URL}/api/admin/salary-process/readiness",
        params={"company_id": KANKANI, "month": "2026-06"}, headers=hdr, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["company_id"] == KANKANI
    assert body["month"] == "2026-06"
    assert isinstance(body["compliance_pct"], (int, float))
    k = body["kpis"]
    assert k["total_employees"] >= 100  # Kankani has ~126
    assert "pf_eligible" in k and "esic_eligible" in k
    assert "pt_applicable" in k
    assert "compliance_errors" in k
    assert "salary_processed" in k and "compliance" in k["salary_processed"]
    assert "challans" in k
    checks = body["checks"]
    assert len(checks) == 11
    keys = {c["key"] for c in checks}
    assert keys == {"attendance","salary_structure","uan","esic_ip","aadhaar","pan","bank",
                    "wage_def","duplicates","contractor","documents"}
    for c in checks:
        for f in ("ok","passed","total","note","na","label"):
            assert f in c


def test_readiness_missing_month(hdr):
    r = requests.get(f"{BASE_URL}/api/admin/salary-process/readiness",
                     params={"company_id": KANKANI}, headers=hdr, timeout=30)
    assert r.status_code == 400


def test_readiness_bad_month(hdr):
    r = requests.get(f"{BASE_URL}/api/admin/salary-process/readiness",
                     params={"company_id": KANKANI, "month": "2026-6"}, headers=hdr, timeout=30)
    assert r.status_code == 400


def test_readiness_missing_company(hdr):
    r = requests.get(f"{BASE_URL}/api/admin/salary-process/readiness",
                     params={"month": "2026-06"}, headers=hdr, timeout=30)
    assert r.status_code == 400


def test_readiness_unauthorized():
    r = requests.get(f"{BASE_URL}/api/admin/salary-process/readiness",
                     params={"company_id": KANKANI, "month": "2026-06"}, timeout=30)
    assert r.status_code in (401, 403)
