"""Iter 80 — Backend tests for two bug fixes:

Bug 1 (Iter 77q): OT threshold in monthly-grid + _build_ot_report_rows now
prefers `full_day_hours` over `standard_working_hours`. Firms like
KANKANI ENTERPRISES with full_day_hours=12 and standard_working_hours=8
should trigger OT only past 12 hours, not 8.

Bug 2 (Iter 77r): create_company now auto-heals orphaned phone/email
records whose company_id points to a deleted firm (role in
company_admin/sub_admin/employee). Live users and super_admins still
block with 409.

All temp firms/users are prefixed with Iter80- / TEST_Iter80_ for
cleanup via scripts/cleanup_test_data.py --apply.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

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
    code = r.json().get("dev_code")
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
def _create_firm(http, auth_hdr, name_prefix: str, *,
                 full_day_hours: float, standard_working_hours: float | None):
    """Create a fresh Policy 1 firm with given attendance_policy overrides."""
    unique = uuid.uuid4().hex[:6]
    payload = {
        "name": f"{name_prefix}-{unique}",
        "code": f"IT80{unique[:4].upper()}",
        "business_category": "industry",
        "business_subcategory": "Textile",
        "policy_variant": "policy_1",
        "office_lat": 28.6139,
        "office_lng": 77.2090,
    }
    r = http.post(f"{API}/companies", json=payload, headers=auth_hdr, timeout=15)
    assert r.status_code in (200, 201), r.text
    data = r.json()
    cid = data.get("company_id") or (data.get("company") or {}).get("company_id")
    assert cid

    # PATCH attendance_policy so full_day_hours + standard_working_hours are exact.
    pr = http.get(f"{API}/attendance/policy", params={"company_id": cid},
                  headers=auth_hdr, timeout=15)
    assert pr.status_code == 200, pr.text
    pol = (pr.json() or {}).get("policy") or {}
    pol["policy_variant"] = "policy_1"
    pol["weekly_off_days"] = [6]
    pol["full_day_hours"] = full_day_hours
    if standard_working_hours is not None:
        pol["standard_working_hours"] = standard_working_hours
    # half_day_hours must remain < full_day_hours
    pol.setdefault("half_day_hours", 4.0)
    if pol["half_day_hours"] >= full_day_hours:
        pol["half_day_hours"] = max(1.0, full_day_hours / 2.0)
    # overtime_threshold_hours must be >= full_day_hours per validator
    if float(pol.get("overtime_threshold_hours") or 0) < full_day_hours:
        pol["overtime_threshold_hours"] = full_day_hours
    up = http.patch(
        f"{API}/attendance/policy", params={"company_id": cid},
        json={"policy": pol}, headers=auth_hdr, timeout=15,
    )
    assert up.status_code == 200, up.text
    return cid


def _create_employee(http, auth_hdr, cid: str, *, name_suffix: str,
                     ot_allowed: bool = True):
    phone = f"+91983{uuid.uuid4().int % 10_000_000:07d}"
    payload = {
        "name": f"TEST_Iter80_{name_suffix}",
        "phone": phone,
        "company_id": cid,
        "employee_code": f"T80{uuid.uuid4().hex[:4].upper()}",
        "doj": "2020-01-01",
    }
    r = http.post(f"{API}/admin/employees", json=payload, headers=auth_hdr, timeout=15)
    assert r.status_code in (200, 201), r.text
    uid = r.json().get("user_id") or (r.json().get("employee") or {}).get("user_id")
    assert uid
    # Set attendance policy override → ot_allowed
    ov = http.put(
        f"{API}/admin/employees/{uid}/attendance-policy-override",
        json={"ot_allowed": ot_allowed}, headers=auth_hdr, timeout=15,
    )
    assert ov.status_code == 200, ov.text
    return uid


def _punch(http, auth_hdr, uid: str, date_iso: str, hh_in: str, hh_out: str):
    for kind, t in (("in", hh_in), ("out", hh_out)):
        rp = http.post(
            f"{API}/admin/attendance/manual-punch",
            json={"user_id": uid, "at": f"{date_iso}T{t}Z", "kind": kind,
                  "reason": "iter80 seed"},
            headers=auth_hdr, timeout=15,
        )
        assert rp.status_code == 200, f"{kind} {t} → {rp.status_code} {rp.text}"


# ==================================================================
# PART 1 — Bug 1 (Iter 77q): OT threshold uses full_day_hours
# ==================================================================
@pytest.fixture(scope="module")
def kank_env(http, auth_hdr):
    """KANKANI-like firm: full_day_hours=12, standard_working_hours=8."""
    cid = _create_firm(
        http, auth_hdr, "Iter80-KANK",
        full_day_hours=12.0, standard_working_hours=8.0,
    )
    uid = _create_employee(http, auth_hdr, cid, name_suffix="KANK", ot_allowed=True)
    # Day 1: 10h (2026-06-01 Mon) — should NOT trip OT (< 12h)
    # Day 2: 14h (2026-06-02 Tue) — 2h OT past the 12h threshold
    _punch(http, auth_hdr, uid, "2026-06-01", "07:00:00", "17:00:00")  # 10h
    _punch(http, auth_hdr, uid, "2026-06-02", "06:00:00", "20:00:00")  # 14h
    return {"cid": cid, "uid": uid}


class TestBug1KankaniThreshold:
    """KANKANI-style firm: full_day_hours=12, standard_working_hours=8.
    OT should trigger only past 12h, not 8h."""

    def test_monthly_grid_10h_no_ot(self, http, auth_hdr, kank_env):
        cid = kank_env["cid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-06",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        emp = next(e for e in body["employees"] if e["user_id"] == kank_env["uid"])
        days = emp["days"]
        # Find cell for 2026-06-01 (day-of-month = 1, indexed by day integer)
        cell_10h = days.get("01") or days.get("1") or days.get(1)
        assert cell_10h is not None, days
        assert cell_10h["ot_hours"] == pytest.approx(0.0), cell_10h
        assert cell_10h["duty_hours"] == pytest.approx(10.0, abs=0.05), cell_10h
        assert cell_10h["hours"] == pytest.approx(10.0, abs=0.05), cell_10h

    def test_monthly_grid_14h_shows_2h_ot(self, http, auth_hdr, kank_env):
        cid = kank_env["cid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-06",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        emp = next(e for e in body["employees"] if e["user_id"] == kank_env["uid"])
        days = emp["days"]
        cell_14h = days.get("02") or days.get("2") or days.get(2)
        assert cell_14h is not None, days
        assert cell_14h["ot_hours"] == pytest.approx(2.0, abs=0.05), cell_14h
        assert cell_14h["duty_hours"] == pytest.approx(12.0, abs=0.05), cell_14h
        assert cell_14h["hours"] == pytest.approx(14.0, abs=0.05), cell_14h
        assert cell_14h["ot_in"] is not None, cell_14h
        assert cell_14h["ot_out"] is not None, cell_14h

    def test_ot_report_only_14h_day(self, http, auth_hdr, kank_env):
        cid = kank_env["cid"]
        r = http.get(
            f"{API}/admin/attendance/ot-report/{cid}/2026-06",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Only 14h day should have OT, count == 1
        assert body.get("count") == 1, body
        row = body["rows"][0]
        assert row["date"] == "2026-06-02", row
        assert row["duty_hours"] == pytest.approx(12.0, abs=0.05), row
        assert row["ot_hours"] == pytest.approx(2.0, abs=0.05), row
        assert row["total_hours"] == pytest.approx(14.0, abs=0.05), row


# ==================================================================
# PART 1B — Second firm with only full_day_hours=8 (no override)
# ==================================================================
@pytest.fixture(scope="module")
def policy1_env(http, auth_hdr):
    """Fresh firm with full_day_hours=8 (no standard_working_hours
    override). 10h day should still trigger 2h OT."""
    cid = _create_firm(
        http, auth_hdr, "Iter80-Policy1",
        full_day_hours=8.0, standard_working_hours=None,
    )
    uid = _create_employee(http, auth_hdr, cid, name_suffix="P1", ot_allowed=True)
    _punch(http, auth_hdr, uid, "2026-06-03", "07:00:00", "17:00:00")  # 10h
    return {"cid": cid, "uid": uid}


class TestBug1Policy1BaselineStillWorks:
    def test_policy1_10h_shows_2h_ot(self, http, auth_hdr, policy1_env):
        cid = policy1_env["cid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-06",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        emp = next(e for e in body["employees"] if e["user_id"] == policy1_env["uid"])
        days = emp["days"]
        cell = days.get("03") or days.get("3") or days.get(3)
        assert cell is not None, days
        assert cell["ot_hours"] == pytest.approx(2.0, abs=0.05), cell
        assert cell["duty_hours"] == pytest.approx(8.0, abs=0.05), cell
        assert cell["hours"] == pytest.approx(10.0, abs=0.05), cell

    def test_policy1_ot_report_shows_row(self, http, auth_hdr, policy1_env):
        cid = policy1_env["cid"]
        r = http.get(
            f"{API}/admin/attendance/ot-report/{cid}/2026-06",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("count") == 1, body
        row = body["rows"][0]
        assert row["ot_hours"] == pytest.approx(2.0, abs=0.05), row


# ==================================================================
# PART 2 — Bug 2 (Iter 77r): orphan phone/email auto-heal
# ==================================================================
def _pick_unique_phone(suffix: str) -> str:
    """Deterministic unique phone per test run."""
    return f"+9198{uuid.uuid4().int % 100_000_000:08d}"


def _pick_unique_email() -> str:
    return f"iter80.{uuid.uuid4().hex[:8]}@test.local"


class TestBug2OrphanAdminAutoHeal:
    def test_orphan_phone_and_email_auto_heal_on_reuse(self, http, auth_hdr):
        phone = _pick_unique_phone("A")
        email = _pick_unique_email()
        unique_a = uuid.uuid4().hex[:6]

        # Step 1: Create firm A with admin_phone + admin_email
        payload_a = {
            "name": f"Iter80-A-{unique_a}",
            "code": f"IT80A{unique_a[:3].upper()}",
            "business_category": "industry",
            "business_subcategory": "Textile",
            "policy_variant": "policy_2",
            "office_lat": 28.6139, "office_lng": 77.2090,
            "admin_phone": phone,
            "admin_email": email,
            "admin_name": "Iter80 Admin A",
        }
        r_a = http.post(f"{API}/companies", json=payload_a,
                        headers=auth_hdr, timeout=15)
        assert r_a.status_code in (200, 201), r_a.text
        cid_a = r_a.json().get("company_id")
        assert cid_a
        admin_a = r_a.json().get("admin") or {}
        assert admin_a.get("phone") == phone

        # Verify admin user linked to firm A
        # (uses users list endpoint through admin employees — skip direct
        # user query, we'll re-check via login later)

        # Step 2: Force-delete firm A
        rd = http.delete(
            f"{API}/companies/{cid_a}",
            params={"force": "true"}, headers=auth_hdr, timeout=30,
        )
        assert rd.status_code == 200, rd.text

        # Step 3: Create firm B with SAME phone + email → expect 200 auto-heal
        unique_b = uuid.uuid4().hex[:6]
        payload_b = {
            "name": f"Iter80-B-{unique_b}",
            "code": f"IT80B{unique_b[:3].upper()}",
            "business_category": "industry",
"business_subcategory": "Textile",
            "policy_variant": "policy_2",
            "office_lat": 28.6139, "office_lng": 77.2090,
            "admin_phone": phone,
            "admin_email": email,
            "admin_name": "Iter80 Admin B",
        }
        r_b = http.post(f"{API}/companies", json=payload_b,
                        headers=auth_hdr, timeout=15)
        assert r_b.status_code in (200, 201), (
            f"Auto-heal failed for firm B: {r_b.status_code} {r_b.text}"
        )
        cid_b = r_b.json().get("company_id")
        assert cid_b
        assert cid_b != cid_a
        admin_b = r_b.json().get("admin") or {}
        assert admin_b.get("phone") == phone, admin_b
        new_temp_pin = admin_b.get("temp_pin")
        assert new_temp_pin, admin_b

        # Step 4: Verify the NEW admin can log in with the new temp PIN, and
        # that /auth/me reports company_id=firm B.
        # Attempt PIN login via /api/auth/admin-pin-login (or similar). Use
        # generic PIN flow.
        r_login = http.post(
            f"{API}/auth/admin-pin-login",
            json={"identifier": phone, "pin": new_temp_pin},
            timeout=15,
        )
        # If the endpoint requires must_change first, it may return 200 with
        # a flag OR 403 pin_must_change. Either way we assert not 401.
        assert r_login.status_code in (200, 201, 403), (
            r_login.status_code, r_login.text,
        )
        if r_login.status_code == 200:
            tok = r_login.json().get("session_token") or r_login.json().get("token")
            if tok:
                r_me = http.get(f"{API}/auth/me",
                                headers={"Authorization": f"Bearer {tok}"},
                                timeout=15)
                if r_me.status_code == 200:
                    me = r_me.json().get("user") or r_me.json()
                    assert me.get("company_id") == cid_b, me

    def test_live_firm_admin_phone_reuse_returns_409(self, http, auth_hdr):
        """Firm C alive with phone P → creating firm D with phone P
        must be blocked with 409."""
        phone_c = _pick_unique_phone("C")
        email_c = _pick_unique_email()
        unique_c = uuid.uuid4().hex[:6]
        payload_c = {
            "name": f"Iter80-C-{unique_c}",
            "code": f"IT80C{unique_c[:3].upper()}",
            "business_category": "industry",
"business_subcategory": "Textile",
            "policy_variant": "policy_2",
            "office_lat": 28.6139, "office_lng": 77.2090,
            "admin_phone": phone_c,
            "admin_email": email_c,
            "admin_name": "Iter80 Admin C",
        }
        r_c = http.post(f"{API}/companies", json=payload_c,
                        headers=auth_hdr, timeout=15)
        assert r_c.status_code in (200, 201), r_c.text

        # Now try to reuse phone_c on firm D — should be blocked
        unique_d = uuid.uuid4().hex[:6]
        payload_d = {
            "name": f"Iter80-D-{unique_d}",
            "code": f"IT80D{unique_d[:3].upper()}",
            "business_category": "industry",
"business_subcategory": "Textile",
            "policy_variant": "policy_2",
            "office_lat": 28.6139, "office_lng": 77.2090,
            "admin_phone": phone_c,
            "admin_email": _pick_unique_email(),
            "admin_name": "Iter80 Admin D",
        }
        r_d = http.post(f"{API}/companies", json=payload_d,
                        headers=auth_hdr, timeout=15)
        assert r_d.status_code == 409, (
            f"Expected 409 for live-firm phone reuse, got: "
            f"{r_d.status_code} {r_d.text}"
        )
        assert "already" in r_d.text.lower() or "exists" in r_d.text.lower(), r_d.text

    def test_live_firm_admin_email_reuse_returns_409(self, http, auth_hdr):
        """Firm E alive with email X → creating firm F with SAME email
        (different phone) must be blocked with 409."""
        phone_e = _pick_unique_phone("E")
        email_e = _pick_unique_email()
        unique_e = uuid.uuid4().hex[:6]
        payload_e = {
            "name": f"Iter80-E-{unique_e}",
            "code": f"IT80E{unique_e[:3].upper()}",
            "business_category": "industry",
"business_subcategory": "Textile",
            "policy_variant": "policy_2",
            "office_lat": 28.6139, "office_lng": 77.2090,
            "admin_phone": phone_e,
            "admin_email": email_e,
            "admin_name": "Iter80 Admin E",
        }
        r_e = http.post(f"{API}/companies", json=payload_e,
                        headers=auth_hdr, timeout=15)
        assert r_e.status_code in (200, 201), r_e.text

        unique_f = uuid.uuid4().hex[:6]
        payload_f = {
            "name": f"Iter80-F-{unique_f}",
            "code": f"IT80F{unique_f[:3].upper()}",
            "business_category": "industry",
"business_subcategory": "Textile",
            "policy_variant": "policy_2",
            "office_lat": 28.6139, "office_lng": 77.2090,
            "admin_phone": _pick_unique_phone("F"),
            "admin_email": email_e,       # reuse of LIVE email
            "admin_name": "Iter80 Admin F",
        }
        r_f = http.post(f"{API}/companies", json=payload_f,
                        headers=auth_hdr, timeout=15)
        assert r_f.status_code == 409, (
            f"Expected 409 for live-firm email reuse, got: "
            f"{r_f.status_code} {r_f.text}"
        )

    def test_super_admin_phone_is_never_auto_healed(self, http, auth_hdr):
        """Regression: even if the super_admin's company_id happens to
        point to a deleted firm, we MUST NOT delete the super_admin
        record. Verify by attempting to reuse the known super_admin
        email — must return 409.

        We use the seeded super-admin email
        (sksharmaconsultancy@gmail.com) which is guaranteed to exist and
        have role=super_admin.
        """
        unique = uuid.uuid4().hex[:6]
        payload = {
            "name": f"Iter80-SA-{unique}",
            "code": f"IT80S{unique[:3].upper()}",
            "business_category": "industry",
"business_subcategory": "Textile",
            "policy_variant": "policy_2",
            "office_lat": 28.6139, "office_lng": 77.2090,
            "admin_phone": _pick_unique_phone("SA"),
            "admin_email": SUPER_EMAIL,   # super_admin email
            "admin_name": "Should Not Be Created",
        }
        r = http.post(f"{API}/companies", json=payload,
                      headers=auth_hdr, timeout=15)
        assert r.status_code == 409, (
            f"Expected 409 for super_admin email reuse, got: "
            f"{r.status_code} {r.text}"
        )
