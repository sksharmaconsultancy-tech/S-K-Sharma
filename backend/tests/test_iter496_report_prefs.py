"""Iter 496 — Universal Report Table engine: /api/report-prefs/{key} tests."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
EMAIL = "sksharmaconsultancy@gmail.com"
PASSWORD = "sharma123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": EMAIL, "password": PASSWORD}, timeout=20)
    assert r.status_code == 200, f"login {r.status_code}: {r.text[:200]}"
    j = r.json()
    tok = j.get("session_token") or j.get("token") or j.get("access_token")
    assert tok, f"no token in {j}"
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---- Auth required --------------------------------------------------------
def test_get_prefs_requires_auth():
    r = requests.get(f"{BASE_URL}/api/report-prefs/punch_log", timeout=15)
    assert r.status_code == 401


def test_put_prefs_requires_auth():
    r = requests.put(f"{BASE_URL}/api/report-prefs/punch_log",
                     json={"w": {}, "hide": [], "t": 0}, timeout=15)
    assert r.status_code == 401


# ---- Upsert + read --------------------------------------------------------
def test_put_then_get_persists(headers):
    payload = {"w": {"employee_code": 88, "name": 220}, "hide": ["bio_code"], "t": int(time.time() * 1000)}
    r = requests.put(f"{BASE_URL}/api/report-prefs/punch_log", json=payload, headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True

    g = requests.get(f"{BASE_URL}/api/report-prefs/punch_log", headers=headers, timeout=15)
    assert g.status_code == 200, g.text
    prefs = g.json().get("prefs")
    assert prefs is not None
    assert prefs["w"]["employee_code"] == 88
    assert prefs["w"]["name"] == 220
    assert prefs["hide"] == ["bio_code"]
    assert prefs["t"] == payload["t"]


def test_upsert_overwrites(headers):
    payload = {"w": {"name": 250}, "hide": [], "t": int(time.time() * 1000) + 1000}
    r = requests.put(f"{BASE_URL}/api/report-prefs/ot_report", json=payload, headers=headers, timeout=15)
    assert r.status_code == 200
    g = requests.get(f"{BASE_URL}/api/report-prefs/ot_report", headers=headers, timeout=15)
    assert g.status_code == 200
    prefs = g.json().get("prefs")
    assert prefs["w"]["name"] == 250
    assert prefs["hide"] == []


def test_unknown_key_returns_null(headers):
    g = requests.get(f"{BASE_URL}/api/report-prefs/never_saved_zzz_iter496", headers=headers, timeout=15)
    assert g.status_code == 200
    assert g.json().get("prefs") is None


# ---- Related report endpoints reachable (smoke) --------------------------
def test_punch_log_endpoint(headers):
    r = requests.get(f"{BASE_URL}/api/admin/punch-logs?from_date=2026-07-01&to_date=2026-07-31",
                     headers=headers, timeout=30)
    # Endpoint should respond 200 (rows may be empty)
    assert r.status_code == 200, r.text[:200]
    j = r.json()
    assert "rows" in j
