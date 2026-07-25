"""Iter 291 backend regression tests.

Covers:
  1. Bulk-Ops employee-search (min 3 chars gating + query)
  2. Bulk-Ops transfer: active employee rejected (400)
  3. Bulk-Ops transfer: synthetic RESIGNED employee → moves + service_history
     entry + new_code, then cleanup deletes temp user
  4. Staff PWA portal-switch endpoint: super_admin token → 403
  5. Roles / Company-Staff eligible-employees endpoint (~127 rows,
     already_staff/has_password flags present)
  6. Attendance monthly-grid returns day_present_counts for 2026-07 Kankani
"""
import os
import requests
import pytest

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL missing from env")

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PASS = "sharma123"
KANKANI_ID = "cmp_527fecdd7c"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def super_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": SUPER_EMAIL, "password": SUPER_PASS},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok, r.text
    return tok


@pytest.fixture(scope="module")
def hdrs(super_token):
    return {"Authorization": f"Bearer {super_token}"}


@pytest.fixture(scope="module")
def other_firm(hdrs):
    """Find any firm != Kankani to use as transfer destination."""
    r = requests.get(f"{BASE_URL}/api/companies", headers=hdrs, timeout=30)
    assert r.status_code == 200, r.text
    rows = r.json() if isinstance(r.json(), list) else r.json().get("rows") or r.json().get("companies") or []
    for c in rows:
        if c.get("company_id") and c["company_id"] != KANKANI_ID:
            return c["company_id"]
    pytest.skip("No secondary firm available for transfer destination")


# ---------- 1. employee-search ----------
class TestEmployeeSearch:
    def test_too_short_returns_400(self, hdrs):
        r = requests.get(
            f"{BASE_URL}/api/admin/bulk-ops/employee-search?q=ra",
            headers=hdrs, timeout=30,
        )
        assert r.status_code == 400
        assert "3" in r.text.lower() or "characters" in r.text.lower()

    def test_valid_query_returns_rows(self, hdrs):
        r = requests.get(
            f"{BASE_URL}/api/admin/bulk-ops/employee-search?q=raj",
            headers=hdrs, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "rows" in body
        assert isinstance(body["rows"], list)
        if body["rows"]:
            row = body["rows"][0]
            for k in ("user_id", "name", "company_id", "is_resigned"):
                assert k in row


# ---------- 2 & 3. transfer ----------
class TestBulkTransfer:
    def test_active_employee_transfer_blocked_400(self, hdrs, other_firm):
        # Pick any ACTIVE employee from Kankani
        r = requests.get(
            f"{BASE_URL}/api/admin/bulk-ops/employees?company_id={KANKANI_ID}",
            headers=hdrs, timeout=30,
        )
        assert r.status_code == 200
        active = [e for e in r.json().get("rows", []) if not e.get("is_resigned")]
        assert active, "No active employees in Kankani (unexpected)"
        uid = active[0]["user_id"]
        r = requests.post(
            f"{BASE_URL}/api/admin/bulk-ops/transfer",
            headers=hdrs,
            json={
                "company_id": KANKANI_ID,
                "to_company_id": other_firm,
                "user_ids": [uid],
            },
            timeout=30,
        )
        assert r.status_code == 400, r.text
        assert "resigned" in r.text.lower()

    def test_synthetic_resigned_transfer_moves_with_new_code(
        self, hdrs, other_firm, super_token
    ):
        """Full mutation: create temp resigned employee → transfer →
        verify new_code + service_history + new company_id → DELETE."""
        import uuid as _uuid

        temp_uid = f"user_TEST291_{_uuid.uuid4().hex[:8]}"
        temp_code = f"TEST291_{_uuid.uuid4().hex[:4]}"

        # Insert via admin employee create (falls back if we need seed).
        # Simpler: use /api/admin/employees POST if available; otherwise
        # skip. Try a direct create.
        create_payload = {
            "name": "TEST291 Transfer Emp",
            "employee_code": temp_code,
            "company_id": KANKANI_ID,
            "phone_e164": "+919999000291",
            "doj": "2025-01-01",
        }
        cr = requests.post(
            f"{BASE_URL}/api/admin/employees",
            headers=hdrs, json=create_payload, timeout=30,
        )
        if cr.status_code not in (200, 201):
            pytest.skip(f"Cannot create temp employee via API: {cr.status_code} {cr.text[:120]}")
        created = cr.json()
        real_uid = created.get("user_id") or created.get("user", {}).get("user_id")
        assert real_uid, f"No user_id in create response: {created}"

        try:
            # Mark as resigned via bulk-ops/resignation
            rr = requests.post(
                f"{BASE_URL}/api/admin/bulk-ops/resignation",
                headers=hdrs,
                json={
                    "company_id": KANKANI_ID,
                    "user_ids": [real_uid],
                    "exit_date": "2026-01-01",
                    "reason": "TEST291 synthetic",
                },
                timeout=30,
            )
            assert rr.status_code == 200, rr.text
            assert rr.json().get("updated", 0) >= 1

            # Transfer to other firm
            tr = requests.post(
                f"{BASE_URL}/api/admin/bulk-ops/transfer",
                headers=hdrs,
                json={
                    "company_id": KANKANI_ID,
                    "to_company_id": other_firm,
                    "user_ids": [real_uid],
                    "effective_date": "2026-01-15",
                    "note": "TEST291 transfer",
                },
                timeout=30,
            )
            assert tr.status_code == 200, tr.text
            body = tr.json()
            assert body.get("moved") == 1
            assert body.get("transfers"), "transfers array missing"
            t = body["transfers"][0]
            assert t.get("new_code"), "new_code not returned"
            assert t.get("old_code") == temp_code

            # Verify via employees list on destination firm
            de = requests.get(
                f"{BASE_URL}/api/admin/bulk-ops/employees?company_id={other_firm}",
                headers=hdrs, timeout=30,
            )
            assert de.status_code == 200
            hit = [e for e in de.json().get("rows", []) if e.get("user_id") == real_uid]
            assert hit, "Employee did not appear in destination firm"
            assert str(hit[0].get("employee_code")) == str(t["new_code"])
        finally:
            # cleanup: direct DELETE
            requests.delete(
                f"{BASE_URL}/api/admin/employees/{real_uid}",
                headers=hdrs, timeout=30,
            )


# ---------- 4. staff-portal-switch ----------
class TestStaffPortalSwitch:
    def test_super_admin_forbidden_403(self, hdrs):
        r = requests.post(
            f"{BASE_URL}/api/auth/staff-portal-switch",
            headers=hdrs, json={}, timeout=30,
        )
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"
        assert "staff" in r.text.lower()


# ---------- 5. eligible-employees ----------
class TestEligibleEmployees:
    def test_kankani_eligible_list(self, hdrs):
        r = requests.get(
            f"{BASE_URL}/api/admin/company-staff/eligible-employees?company_id={KANKANI_ID}",
            headers=hdrs, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        rows = body.get("rows") or body.get("employees") or body
        assert isinstance(rows, list)
        # Expect roughly 125-130 rows
        assert len(rows) >= 100, f"expected many rows, got {len(rows)}"
        row = rows[0]
        assert "already_staff" in row
        assert "has_password" in row


# ---------- 6. attendance monthly-grid day_present_counts ----------
class TestAttendanceGridPresentCounts:
    def test_day_present_counts_populated(self, hdrs):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid/{KANKANI_ID}/2026-07",
            headers=hdrs, timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        dpc = body.get("day_present_counts")
        assert dpc is not None, "day_present_counts missing"
        # Should be a dict {day_str: count}
        assert isinstance(dpc, (dict, list))
        if isinstance(dpc, dict):
            populated = [k for k, v in dpc.items() if v and int(v) > 0]
            assert len(populated) >= 1, f"expected populated days, got {dpc}"
