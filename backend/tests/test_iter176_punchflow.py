"""Iter 176 — Guided punch workflow backend tests.

Covers:
  * GET /api/attendance/worksites (employee token) returns 'main' with correct coords.
  * POST /api/company/branches (super admin) → branch appears in worksites list → DELETE cleans up.
  * POST /api/attendance/punch persists worksite_id/worksite_name on the record.
  * Geofence still enforced (far-away coords rejected).
"""
import os
import time
import requests
import pytest

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"

EMP_CODE = "TNF40186C"
EMP_PIN_LAST4 = "2750"
COMPANY_ID = "cmp_527fecdd7c"
OFFICE_LAT = 25.3463
OFFICE_LNG = 74.6408


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def emp_token():
    r = requests.post(
        f"{BASE}/auth/emp-code-login",
        json={"employee_code": EMP_CODE, "phone_last4": EMP_PIN_LAST4},
        timeout=15,
    )
    assert r.status_code == 200, f"emp login failed: {r.status_code} {r.text}"
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok, r.text
    return tok


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE}/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok, r.text
    return tok


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------- worksites endpoint ----------
class TestWorksites:
    def test_worksites_returns_main(self, emp_token):
        r = requests.get(f"{BASE}/attendance/worksites", headers=_auth(emp_token), timeout=15)
        assert r.status_code == 200, r.text
        sites = r.json().get("worksites", [])
        assert isinstance(sites, list) and len(sites) >= 1
        main = next((s for s in sites if s["worksite_id"] == "main"), None)
        assert main is not None, sites
        assert abs(main["office_lat"] - OFFICE_LAT) < 0.001
        assert abs(main["office_lng"] - OFFICE_LNG) < 0.001
        assert main.get("geofence_radius_m", 0) >= 100

    def test_branch_add_appears_and_deletes(self, emp_token, admin_token):
        # add a test branch
        payload = {
            "company_id": COMPANY_ID,
            "name": f"TEST_iter176_branch_{int(time.time())}",
            "office_lat": 25.4,
            "office_lng": 74.7,
            "geofence_radius_m": 150,
            "address": "TEST branch",
        }
        r = requests.post(
            f"{BASE}/company/branches", json=payload,
            headers=_auth(admin_token), timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        branch = body.get("branch") or body
        branch_id = branch.get("branch_id") or branch.get("id")
        assert branch_id, body
        try:
            # employee worksites should now include the new branch
            r2 = requests.get(
                f"{BASE}/attendance/worksites", headers=_auth(emp_token), timeout=15,
            )
            assert r2.status_code == 200
            ids = [s["worksite_id"] for s in r2.json().get("worksites", [])]
            assert branch_id in ids, f"branch {branch_id} missing: {ids}"
        finally:
            d = requests.delete(
                f"{BASE}/company/branches/{branch_id}",
                headers=_auth(admin_token), timeout=15,
            )
            assert d.status_code in (200, 204), d.text


# ---------- punch persistence + geofence ----------
class TestPunchWorksite:
    _created_record_id = None

    def test_punch_far_away_rejected(self, emp_token):
        r = requests.post(
            f"{BASE}/attendance/punch",
            headers=_auth(emp_token),
            json={
                "kind": "in",
                "latitude": 26.9,
                "longitude": 75.8,
                "biometric_method": "face",
                "selfie_base64": "iVBORw0KGgo=",  # tiny stub
                "device_info": "web",
                "worksite_name": "TEST_far",
            },
            timeout=15,
        )
        assert r.status_code in (400, 403, 422), (
            f"far-away punch should be rejected, got {r.status_code}: {r.text}"
        )

    def test_punch_inside_stores_worksite(self, emp_token):
        # Pick kind opposite of last punch (test may run twice).
        t0 = requests.get(f"{BASE}/attendance/today", headers=_auth(emp_token), timeout=15)
        recs0 = (t0.json().get("records") or []) if t0.status_code == 200 else []
        last = recs0[-1] if recs0 else None
        kind = "out" if (last and last.get("kind") == "in") else "in"
        r = requests.post(
            f"{BASE}/attendance/punch",
            headers=_auth(emp_token),
            json={
                "kind": kind,
                "latitude": OFFICE_LAT,
                "longitude": OFFICE_LNG,
                "biometric_method": "face",
                # 1x1 white PNG base64 — needed since backend enforces selfie
                "selfie_base64": (
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQV"
                    "R42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
                ),
                "device_info": "web",
                "worksite_name": "Main Office (TEST_iter176)",
                "source": "manual",
            },
            timeout=20,
        )
        # accept 200 OR 400 if firm-side rule blocks (log for triage)
        assert r.status_code == 200, f"punch failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True or body.get("status") in ("pending", "approved")
        # verify the worksite_name got persisted by querying today
        t = requests.get(f"{BASE}/attendance/today", headers=_auth(emp_token), timeout=15)
        assert t.status_code == 200, t.text
        recs = t.json().get("records", [])
        assert recs, "no records after punch"
        latest = recs[-1]
        assert latest.get("worksite_name") == "Main Office (TEST_iter176)", (
            f"worksite_name not persisted: {latest}"
        )
        # Save for cleanup
        TestPunchWorksite._created_record_id = latest.get("record_id")


# ---------- cleanup (best-effort) ----------
def test_cleanup_today(emp_token, admin_token):
    """Best-effort cleanup: delete today's TEST records for TNF40186C."""
    t = requests.get(f"{BASE}/attendance/today", headers=_auth(emp_token), timeout=15)
    if t.status_code != 200:
        pytest.skip("today unreadable")
    for rec in t.json().get("records", []):
        if "TEST_iter176" in (rec.get("worksite_name") or ""):
            rid = rec.get("record_id")
            if rid:
                d = requests.delete(
                    f"{BASE}/admin/attendance/{rid}",
                    params={"reason": "iter176-test-cleanup"},
                    headers=_auth(admin_token), timeout=10,
                )
                assert d.status_code in (200, 204, 404), d.text
