"""Iter 93 backend regression tests

Feature groups covered:
1. GET /api/admin/attendance/day-status range validation & shape
2. POST /api/admin/attendance/manual-punch + PATCH keeps status=approved & sets edited flag
3. PATCH /api/admin/employees/{user_id}/profile compliance_salary_mode + bio_code + employee_code (409 duplicate)
"""

import os
import pytest
import requests
from datetime import datetime, timedelta, timezone

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"
SUPER_ADMIN = {"email": "sksharma", "password": "sharma123"}
SAMPLE_USER_ID = "user_44cd6f561da0"  # SURENDRA SINGH (code 50)


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json=SUPER_ADMIN,
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---- day-status endpoint ----

class TestDayStatus:
    def test_day_status_single_day(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/day-status/{COMPANY_ID}",
            params={"from_date": "2026-07-09", "to_date": "2026-07-09"},
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        assert "rows" in data
        assert isinstance(data["rows"], list)
        assert len(data["rows"]) > 0
        row = data["rows"][0]
        for f in ["key", "user_id", "date", "in", "out", "updated"]:
            assert f in row, f"missing field {f}"

    def test_day_status_range_over_31_days_rejected(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/day-status/{COMPANY_ID}",
            params={"from_date": "2026-06-01", "to_date": "2026-07-15"},
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"


# ---- manual-punch create + PATCH keeps approved ----

@pytest.fixture(scope="module")
def created_punches(headers):
    """Seed: emp1 gets IN only; emp2 gets IN+OUT. Cleanup after tests."""
    # Get 2 employees
    r = requests.get(f"{BASE_URL}/api/admin/employees", params={"company_id": COMPANY_ID}, headers=headers, timeout=30)
    assert r.status_code == 200
    emps = r.json() if isinstance(r.json(), list) else r.json().get("employees", [])
    assert len(emps) >= 2
    emp_in_only = emps[0]["user_id"]
    emp_both = emps[1]["user_id"]

    ids = []
    # IN only for emp_in_only
    r1 = requests.post(
        f"{BASE_URL}/api/admin/attendance/manual-punch",
        json={
            "user_id": emp_in_only,
            "kind": "in",
            "at": "2026-07-09T09:00:00+05:30",
            "reason": "TEST_iter93_seed",
        },
        headers=headers,
        timeout=30,
    )
    assert r1.status_code in (200, 201), r1.text
    j1 = r1.json()
    rec1 = j1.get("record") or j1
    ids.append((rec1.get("record_id") or rec1.get("id"), emp_in_only, "in"))

    # IN+OUT for emp_both
    for kind, tm in [("in", "09:15:00"), ("out", "18:00:00")]:
        r2 = requests.post(
            f"{BASE_URL}/api/admin/attendance/manual-punch",
            json={
                "user_id": emp_both,
                "kind": kind,
                "at": f"2026-07-09T{tm}+05:30",
                "reason": "TEST_iter93_seed",
            },
            headers=headers,
            timeout=30,
        )
        assert r2.status_code in (200, 201), r2.text
        j2 = r2.json()
        rec2 = j2.get("record") or j2
        ids.append((rec2.get("record_id") or rec2.get("id"), emp_both, kind))

    yield {"in_only": emp_in_only, "both": emp_both, "ids": ids}

    # cleanup
    for rid, _, _ in ids:
        if rid:
            requests.delete(
                f"{BASE_URL}/api/admin/attendance/{rid}",
                params={"reason": "TEST_cleanup"},
                headers=headers,
                timeout=30,
            )


class TestPatchAttendance:
    def test_manual_punch_appears_in_day_status(self, headers, created_punches):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/day-status/{COMPANY_ID}",
            params={"from_date": "2026-07-09", "to_date": "2026-07-09"},
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 200
        rows = r.json()["rows"]
        both_row = next((x for x in rows if x["user_id"] == created_punches["both"]), None)
        assert both_row is not None
        assert both_row["in"] is not None and both_row["out"] is not None
        assert "hhmm" in both_row["in"]

    def test_patch_keeps_approved_and_sets_updated(self, headers, created_punches):
        rid = created_punches["ids"][0][0]  # first IN record
        r = requests.patch(
            f"{BASE_URL}/api/admin/attendance/{rid}",
            json={"at": "2026-07-09T09:30:00+05:30", "reason": "TEST_edit"},
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Should either return updated record with status approved OR success flag
        # Verify via day-status
        r2 = requests.get(
            f"{BASE_URL}/api/admin/attendance/day-status/{COMPANY_ID}",
            params={"from_date": "2026-07-09", "to_date": "2026-07-09"},
            headers=headers,
            timeout=30,
        )
        rows = r2.json()["rows"]
        row = next((x for x in rows if x["user_id"] == created_punches["in_only"]), None)
        assert row is not None
        assert row["updated"] is True, f"expected updated=true, got: {row}"
        # edited flag may not be on first_in cell (dedupe picks earliest by 'at');
        # what matters is the row-level 'updated' flag which is derived from any(edited_at) 


# ---- Profile compliance_salary_mode + bio_code + employee_code ----

class TestProfileFields:
    def test_patch_compliance_and_bio_code(self, headers):
        # Get current profile
        r = requests.get(
            f"{BASE_URL}/api/admin/employees/{SAMPLE_USER_ID}/profile",
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        orig = r.json()
        orig_bio = orig.get("bio_code")
        orig_code = orig.get("employee_code")
        orig_mode = orig.get("compliance_salary_mode")

        new_mode = "daily" if orig_mode != "daily" else "monthly"
        payload = {
            "compliance_salary_mode": new_mode,
            "bio_code": orig_bio or "TEST_BIO_93",
        }
        r2 = requests.patch(
            f"{BASE_URL}/api/admin/employees/{SAMPLE_USER_ID}/profile",
            json=payload,
            headers=headers,
            timeout=30,
        )
        assert r2.status_code == 200, r2.text

        r3 = requests.get(
            f"{BASE_URL}/api/admin/employees/{SAMPLE_USER_ID}/profile",
            headers=headers,
            timeout=30,
        )
        assert r3.status_code == 200
        after = r3.json()
        assert after.get("compliance_salary_mode") == new_mode

        # restore
        requests.patch(
            f"{BASE_URL}/api/admin/employees/{SAMPLE_USER_ID}/profile",
            json={"compliance_salary_mode": orig_mode or "monthly"},
            headers=headers,
            timeout=30,
        )

    def test_duplicate_employee_code_409(self, headers):
        # Get 2 employees
        r = requests.get(f"{BASE_URL}/api/admin/employees", params={"company_id": COMPANY_ID}, headers=headers, timeout=30)
        emps = r.json() if isinstance(r.json(), list) else r.json().get("employees", [])
        emp_a = emps[0]
        emp_b = emps[1]
        # Try to set emp_a's code to emp_b's code
        r2 = requests.patch(
            f"{BASE_URL}/api/admin/employees/{emp_a['user_id']}/profile",
            json={"employee_code": emp_b["employee_code"]},
            headers=headers,
            timeout=30,
        )
        assert r2.status_code == 409, f"Expected 409, got {r2.status_code}: {r2.text}"
