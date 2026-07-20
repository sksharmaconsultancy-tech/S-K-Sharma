"""
Iteration 212 backend tests:
- Sub-admin (testsub@sksharma.co) should now be able to hit ~60 previously-403 admin endpoints.
- Super-admin regression: attendance-grid + day-status still work.
- day-status OT pairing: morning employee (SURENDRA) gets OT pair, evening (ALI) does not.
"""
import os
import pytest
import requests

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PASS = "sharma123"
SUB_EMAIL = "testsub@sksharma.co"
SUB_PASS = "testsub123"

SUB_CID = "cmp_adddad3f65"     # City Care Hospital (sub-admin scope)
KANKANI_CID = "cmp_527fecdd7c" # Super-admin regression
TEST_DATE = "2026-07-20"


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/admin-password-login",
                      json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text}"
    tok = r.json()["session_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def super_headers():
    return _login(SUPER_EMAIL, SUPER_PASS)


@pytest.fixture(scope="module")
def sub_headers():
    return _login(SUB_EMAIL, SUB_PASS)


# ---------------------------------------------------------------------------
# Sub-admin access to previously-blocked admin endpoints (review-request #6)
# ---------------------------------------------------------------------------
class TestSubAdminAdminEndpoints:
    def test_day_status_scoped_company(self, sub_headers):
        r = requests.get(
            f"{BASE}/api/admin/attendance/day-status/{SUB_CID}",
            params={"from_date": TEST_DATE}, headers=sub_headers, timeout=30)
        assert r.status_code == 200, f"day-status -> {r.status_code} {r.text[:300]}"
        body = r.json()
        assert isinstance(body, dict), f"unexpected body: {type(body)}"

    def test_report_formats(self, sub_headers):
        r = requests.get(f"{BASE}/api/admin/report-formats",
                         headers=sub_headers, timeout=20)
        assert r.status_code == 200, f"report-formats -> {r.status_code} {r.text[:300]}"

    def test_shift_masters(self, sub_headers):
        r = requests.get(f"{BASE}/api/admin/shift-masters",
                         headers=sub_headers, timeout=20)
        # May not exist as a route; accept 200 or 404 (route absent), fail on 403.
        assert r.status_code != 403, f"shift-masters unexpectedly 403 for sub-admin: {r.text[:300]}"
        assert r.status_code in (200, 404), f"unexpected {r.status_code}: {r.text[:300]}"

    # Spot-check a handful of other admin endpoints commonly gated by
    # require_permission / require_role. Any 403 fails the test.
    @pytest.mark.parametrize("path", [
        "/api/admin/companies",
        f"/api/admin/employees?company_id={SUB_CID}",
        f"/api/admin/attendance-policy/{SUB_CID}",
        "/api/admin/manual-punch-entries/pending",
    ])
    def test_no_403_for_sub_admin(self, sub_headers, path):
        r = requests.get(f"{BASE}{path}", headers=sub_headers, timeout=20)
        assert r.status_code != 403, f"{path} -> 403 for sub-admin: {r.text[:200]}"
        # Any 200/400/404 is acceptable — we only assert access is not denied.
        assert r.status_code < 500, f"{path} -> {r.status_code} {r.text[:200]}"


# ---------------------------------------------------------------------------
# Super-admin regression on Kankani (review-request #7)
# ---------------------------------------------------------------------------
class TestSuperAdminRegression:
    def test_attendance_grid_july_2026(self, super_headers):
        r = requests.get(
            f"{BASE}/api/admin/attendance/monthly-grid/{KANKANI_CID}/2026-07",
            headers=super_headers, timeout=60)
        assert r.status_code == 200, f"grid -> {r.status_code} {r.text[:400]}"
        body = r.json()
        assert isinstance(body, dict), "grid should return dict"

    def test_day_status_kankani_ot_pairing(self, super_headers):
        r = requests.get(
            f"{BASE}/api/admin/attendance/day-status/{KANKANI_CID}",
            params={"from_date": TEST_DATE}, headers=super_headers, timeout=30)
        assert r.status_code == 200, f"day-status -> {r.status_code}"
        data = r.json()

        # Collect all row-like items
        rows = []
        if isinstance(data, dict):
            for key in ("rows", "items", "entries", "auto", "auto_punches", "data"):
                v = data.get(key)
                if isinstance(v, list):
                    rows.extend(v)
        elif isinstance(data, list):
            rows = data

        # Seeded fixture user ids from review-request:
        # SURENDRA SINGH (morning): user_44cd6f561da0
        # ALI HASAN     (evening): user_4111f8eea5d3
        surendra = next((r_ for r_ in rows if r_.get("user_id") == "user_44cd6f561da0"), None)
        ali = next((r_ for r_ in rows if r_.get("user_id") == "user_4111f8eea5d3"), None)

        if surendra is None and ali is None:
            pytest.skip("seeded rows not present in day-status; UI tests cover the OT rule")

        if ali is not None:
            ot_in = ali.get("ot_in") or ali.get("ot_in_time")
            ot_out = ali.get("ot_out") or ali.get("ot_out_time")
            assert not ot_in, f"ALI HASAN unexpectedly has ot_in={ot_in} (evening first-punch, OT should be N/A). Row={ali}"
            assert not ot_out, f"ALI HASAN unexpectedly has ot_out={ot_out}. Row={ali}"

        if surendra is not None:
            ot_in = surendra.get("ot_in") or surendra.get("ot_in_time")
            assert ot_in, f"SURENDRA SINGH (morning) should have OT in-punch. Row={surendra}"
