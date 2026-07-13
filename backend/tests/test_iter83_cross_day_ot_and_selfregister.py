"""Iter 83 — Backend tests

Covers:
1. Cross-day OT stitching (primary bug — Sanjeev Kumar, bio 32 scenario).
   Punches:
     - 2026-06-01 08:00 IN
     - 2026-06-01 19:58 OUT
     - 2026-06-01 20:08 IN (OT-in)
     - 2026-06-02 07:58 OUT (OT-out — next day)
   Expect monthly-grid[2026-06-01] to have ot_in="20:08", ot_out="07:58",
   ot_hours ~ 11.83; ot-report JSON row for 01-Jun likewise; ot-report
   XLSX returns valid xlsx bytes.

2. Grid-view XLSX endpoint (`monthly-inout/{cid}/{month}.xlsx`) returns
   valid xlsx.

3. Hours-only XLSX endpoint (`monthly-hours/{cid}/{month}.xlsx`) returns
   valid xlsx.

4. Phone self-register auto-heal:
   - Create firm+admin with a unique phone as super-admin.
   - Force-delete the firm (`DELETE /companies/{cid}?force=true`).
   - Call self-register with the same phone → should succeed (200).
   - Repeat with the same phone (now pending) → 409 "pending".

5. Regression sanity: monthly-grid returns 200 for a real firm; OTP login
   for super_admin works.

All temp firms/users are prefixed with `Iter83-` / `TEST_Iter83_` so
`python3 /app/scripts/cleanup_test_data.py --apply` can remove them.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# xlsx files are zip archives — first 2 bytes = "PK"
XLSX_MAGIC = b"PK"


# ------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def super_token(http):
    r = http.post(
        f"{API}/auth/otp/request",
        json={"identifier": SUPER_EMAIL, "channel": "email"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    code = r.json().get("dev_code") or r.json().get("code")
    assert code, r.json()
    r2 = http.post(
        f"{API}/auth/otp/verify",
        json={"identifier": SUPER_EMAIL, "channel": "email", "code": code},
        timeout=15,
    )
    assert r2.status_code == 200, r2.text
    tok = r2.json().get("session_token") or r2.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def auth_hdr(super_token):
    return {"Authorization": f"Bearer {super_token}"}


# ------------------------------------------------------------------ helpers
def _uniq_phone() -> str:
    # +9198XXXXXXXX
    return f"+9198{uuid.uuid4().int % 100_000_000:08d}"


def _uniq_email(prefix: str = "iter83") -> str:
    return f"{prefix}.{uuid.uuid4().hex[:8]}@test.local"


def _create_firm(http, auth_hdr, name_prefix="Iter83-CDO"):
    unique = uuid.uuid4().hex[:6]
    payload = {
        "name": f"{name_prefix}-{unique}",
        "code": f"IT83{unique[:4].upper()}",
        "business_category": "industry",
        "business_subcategory": "Textile",
        "policy_variant": "policy_1",
        "office_lat": 28.6139,
        "office_lng": 77.2090,
    }
    r = http.post(f"{API}/companies", json=payload, headers=auth_hdr, timeout=20)
    assert r.status_code in (200, 201), r.text
    body = r.json()
    cid = body.get("company_id") or (body.get("company") or {}).get("company_id")
    assert cid
    return cid


def _create_employee(http, auth_hdr, cid: str, *, name_suffix="EMP",
                     bio_code: str | None = None, ot_allowed: bool = True):
    phone = _uniq_phone()
    payload = {
        "name": f"TEST_Iter83_{name_suffix}",
        "phone": phone,
        "company_id": cid,
        "employee_code": f"T83{uuid.uuid4().hex[:4].upper()}",
        "doj": "2020-01-01",
    }
    if bio_code:
        payload["bio_code"] = bio_code
    r = http.post(f"{API}/admin/employees", json=payload,
                  headers=auth_hdr, timeout=20)
    assert r.status_code in (200, 201), r.text
    body = r.json()
    uid = body.get("user_id") or (body.get("employee") or {}).get("user_id")
    assert uid
    # ot_allowed override
    ov = http.put(
        f"{API}/admin/employees/{uid}/attendance-policy-override",
        json={"ot_allowed": ot_allowed}, headers=auth_hdr, timeout=15,
    )
    assert ov.status_code == 200, ov.text
    return uid


def _manual_punch(http, auth_hdr, uid: str, at_iso: str, kind: str):
    r = http.post(
        f"{API}/admin/attendance/manual-punch",
        json={"user_id": uid, "at": at_iso, "kind": kind,
              "reason": "iter83 cross-day seed"},
        headers=auth_hdr, timeout=15,
    )
    assert r.status_code == 200, f"{kind} {at_iso} → {r.status_code} {r.text}"


# ==================================================================
# PART 1 — Cross-day OT (primary bug)
# ==================================================================
@pytest.fixture(scope="module")
def cross_day_env(http, auth_hdr):
    cid = _create_firm(http, auth_hdr, name_prefix="Iter83-CDO")
    uid = _create_employee(http, auth_hdr, cid,
                           name_suffix="Sanjeev32", bio_code="32",
                           ot_allowed=True)
    # 2026-06-01 08:00 IN, 19:58 OUT, 20:08 IN (OT), then 2026-06-02 07:58 OUT
    _manual_punch(http, auth_hdr, uid, "2026-06-01T08:00:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-01T19:58:00Z", "out")
    _manual_punch(http, auth_hdr, uid, "2026-06-01T20:08:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-02T07:58:00Z", "out")
    return {"cid": cid, "uid": uid}


class TestCrossDayOT:
    def test_monthly_grid_pairs_cross_day_ot(self, http, auth_hdr, cross_day_env):
        cid = cross_day_env["cid"]
        uid = cross_day_env["uid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-06",
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Find our employee row
        employees = body.get("employees") or body.get("rows") or []
        my_row = None
        for e in employees:
            if (e.get("user_id") == uid
                    or (e.get("employee") or {}).get("user_id") == uid):
                my_row = e
                break
        assert my_row is not None, f"Employee row not found in grid: {body!r}"

        # Locate day cell for 2026-06-01
        days = my_row.get("days") or my_row.get("cells") or {}
        # 'days' can be dict keyed by date or list of {date,...}
        cell = None
        if isinstance(days, dict):
            cell = days.get("2026-06-01") or days.get("01") or days.get(1)
        elif isinstance(days, list):
            for d in days:
                if str(d.get("date") or d.get("day") or "") in (
                    "2026-06-01", "01", 1,
                ):
                    cell = d
                    break
        assert cell is not None, (
            f"01-Jun cell missing. days keys/type: "
            f"{list(days.keys()) if isinstance(days, dict) else type(days)}"
        )

        # Cross-day OT assertions
        assert cell.get("ot_in") == "20:08", (
            f"ot_in expected 20:08, got {cell.get('ot_in')} — cell={cell!r}"
        )
        assert cell.get("ot_out") == "07:58", (
            f"ot_out expected 07:58, got {cell.get('ot_out')} — cell={cell!r}"
        )
        ot_hrs = cell.get("ot_hours") or cell.get("ot") or 0
        assert float(ot_hrs) > 10, (
            f"ot_hours expected > 10, got {ot_hrs}. cell={cell!r}"
        )
        # Should be ~ 11h50m = 11.833
        assert 11.5 <= float(ot_hrs) <= 12.2, (
            f"ot_hours expected ~11.83, got {ot_hrs}"
        )

    def test_ot_report_json_has_cross_day_row(self, http, auth_hdr,
                                                cross_day_env):
        cid = cross_day_env["cid"]
        uid = cross_day_env["uid"]
        r = http.get(
            f"{API}/admin/attendance/ot-report/{cid}/2026-06",
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        rows = body.get("rows") or []
        my_rows = [row for row in rows if row.get("user_id") == uid]
        assert my_rows, (
            f"No OT rows found for uid={uid}. body.count={body.get('count')} "
            f"total rows={len(rows)}"
        )
        # Locate 2026-06-01 row
        jun1 = None
        for row in my_rows:
            if row.get("date") in ("2026-06-01", "01-Jun-2026", "01/06/2026"):
                jun1 = row
                break
        assert jun1 is not None, (
            f"01-Jun OT row missing. my_rows dates: "
            f"{[r.get('date') for r in my_rows]}"
        )
        assert jun1.get("ot_in") == "20:08", jun1
        assert jun1.get("ot_out") == "07:58", jun1
        ot_hrs = float(jun1.get("ot_hours") or 0)
        assert 11.5 <= ot_hrs <= 12.2, f"ot_hours ~11.83 expected, got {ot_hrs}"

    def test_ot_report_xlsx_valid(self, http, auth_hdr, cross_day_env):
        cid = cross_day_env["cid"]
        r = http.get(
            f"{API}/admin/attendance/ot-report/{cid}/2026-06/xlsx",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        assert "spreadsheetml.sheet" in (r.headers.get("Content-Type") or "")
        assert r.content[:2] == XLSX_MAGIC, "Not a valid xlsx (missing PK header)"
        assert len(r.content) > 500, f"xlsx too small: {len(r.content)}"


# ==================================================================
# PART 2 — Grid-view + Hours-only XLSX endpoints
# ==================================================================
class TestMonthlyXlsxEndpoints:
    def test_monthly_inout_xlsx(self, http, auth_hdr, cross_day_env):
        cid = cross_day_env["cid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-inout/{cid}/2026-06.xlsx",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        assert "spreadsheetml.sheet" in (r.headers.get("Content-Type") or "")
        assert r.content[:2] == XLSX_MAGIC
        assert len(r.content) > 500

    def test_monthly_hours_xlsx(self, http, auth_hdr, cross_day_env):
        cid = cross_day_env["cid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-hours/{cid}/2026-06.xlsx",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        assert "spreadsheetml.sheet" in (r.headers.get("Content-Type") or "")
        assert r.content[:2] == XLSX_MAGIC
        assert len(r.content) > 500


# ==================================================================
# PART 3 — Phone self-register auto-heal (force-delete cascade)
# ==================================================================
def _make_selfreg_payload(phone: str, prefix="Iter83-SR"):
    unique = uuid.uuid4().hex[:6]
    return {
        "company_name": f"{prefix}-{unique}",
        "address": "12 QA Street",
        "city": "Delhi",
        "state": "DL",
        "contact_name": "TEST_Iter83_Owner",
        "contact_mobile": phone,
        "contact_email": _uniq_email("iter83sr"),
        "nature_of_business": "Textile",
        "business_category": "industry",
        "business_subcategory": "Textile",
        "pin": "482715",
        "office_lat": 28.6139,
        "office_lng": 77.2090,
        "geofence_radius_m": 200,
        "employee_count": 10,
    }


class TestSelfRegisterPhoneAutoHeal:
    def test_force_delete_then_selfregister_ok(self, http, auth_hdr):
        # 1. Create firm + admin with a fresh unique phone (test-idempotent)
        phone = _uniq_phone()
        unique = uuid.uuid4().hex[:6]
        create_payload = {
            "name": f"Iter83-SR-A-{unique}",
            "code": f"IT83SR{unique[:3].upper()}",
            "business_category": "industry",
            "business_subcategory": "Textile",
            "policy_variant": "policy_1",
            "office_lat": 28.6139,
            "office_lng": 77.2090,
            "admin_phone": phone,
            "admin_email": _uniq_email("iter83admin"),
            "admin_name": "TEST_Iter83_Admin",
        }
        r = http.post(f"{API}/companies", json=create_payload,
                      headers=auth_hdr, timeout=20)
        assert r.status_code in (200, 201), r.text
        cid = r.json().get("company_id") or (
            r.json().get("company") or {}
        ).get("company_id")
        assert cid

        # 2. Force-delete the firm (cascade users)
        rd = http.delete(f"{API}/companies/{cid}?force=true",
                          headers=auth_hdr, timeout=20)
        assert rd.status_code in (200, 204), f"{rd.status_code} {rd.text}"

        # 3. Self-register with the same phone → 200
        payload = _make_selfreg_payload(phone, prefix="Iter83-SR-Reuse")
        r2 = http.post(f"{API}/auth/company-register", json=payload,
                        timeout=20)
        assert r2.status_code == 200, (
            f"Self-register after force-delete should succeed, got "
            f"{r2.status_code} {r2.text}"
        )
        body = r2.json()
        assert body.get("ok") is True and body.get("request_id"), body
        req_id = body["request_id"]

        # 4. Second self-register w/ same phone → 409 pending
        payload2 = _make_selfreg_payload(phone, prefix="Iter83-SR-Dup")
        r3 = http.post(f"{API}/auth/company-register", json=payload2,
                        timeout=20)
        assert r3.status_code == 409, (
            f"Expected 409 for pending dup, got {r3.status_code} {r3.text}"
        )
        assert "pending" in r3.text.lower(), r3.text

        # Clean the pending request via super-admin reject so future runs
        # of this test are idempotent (best-effort — cleanup script also
        # catches this via Iter83- prefix).
        try:
            http.patch(
                f"{API}/company-requests/{req_id}",
                json={"action": "reject", "reason": "iter83 cleanup"},
                headers=auth_hdr, timeout=15,
            )
        except Exception:
            pass


# ==================================================================
# PART 4 — Regression: monthly-grid & super-admin OTP login
# ==================================================================
class TestRegressionSanity:
    def test_super_admin_otp_login(self, super_token):
        # Fixture already exercised OTP request+verify; assert token present
        assert super_token and isinstance(super_token, str) and len(super_token) > 8

    def test_monthly_grid_real_firm_returns_200(self, http, auth_hdr,
                                                  cross_day_env):
        # Use the seeded firm (guaranteed to exist) as the "real firm"
        # for the regression sanity check.
        cid = cross_day_env["cid"]
        r2 = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-06",
            headers=auth_hdr, timeout=25,
        )
        assert r2.status_code == 200, f"{r2.status_code} {r2.text[:200]}"
        body = r2.json()
        assert isinstance(body.get("employees") or body.get("rows"), list)
