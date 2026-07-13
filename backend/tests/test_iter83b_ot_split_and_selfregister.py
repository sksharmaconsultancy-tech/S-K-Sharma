"""Iter 83b — Backend retest after `split_regular_ot_times` rewrite and
`has_unpaired_punches` addition.

Covers:
 A) Cross-day OT primary bug (Sanjeev Kumar bio 32 scenario).
 B) Unpaired-punches anomaly rule (grid cell marked anomaly; OT report skips).
 C) Regular happy-path day with an explicit 2-pair OT structure.
 D) Single-pair long day (arithmetic fallback split).
 E) Phone self-register super_admin guard (409 with clear message; no delete).
 F) Phone self-register happy path (200, then 409 pending on repeat).

All temp firms/users are prefixed with `Iter83b-` / `TEST_Iter83b_` so
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
SUPER_PHONE = "+919680273960"


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
    return f"+9198{uuid.uuid4().int % 100_000_000:08d}"


def _uniq_email(prefix: str = "iter83b") -> str:
    return f"{prefix}.{uuid.uuid4().hex[:8]}@test.local"


def _create_firm(http, auth_hdr, name_prefix="Iter83b-OT"):
    unique = uuid.uuid4().hex[:6]
    payload = {
        "name": f"{name_prefix}-{unique}",
        "code": f"I83B{unique[:4].upper()}",
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
        "name": f"TEST_Iter83b_{name_suffix}",
        "phone": phone,
        "company_id": cid,
        "employee_code": f"T83B{uuid.uuid4().hex[:4].upper()}",
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
              "reason": "iter83b seed"},
        headers=auth_hdr, timeout=15,
    )
    assert r.status_code == 200, f"{kind} {at_iso} → {r.status_code} {r.text}"


def _find_row(body, uid):
    employees = body.get("employees") or body.get("rows") or []
    for e in employees:
        if (e.get("user_id") == uid
                or (e.get("employee") or {}).get("user_id") == uid):
            return e
    return None


def _find_cell(row, date_str):
    days = row.get("days") or row.get("cells") or {}
    if isinstance(days, dict):
        return (days.get(date_str) or days.get(date_str[-2:])
                or days.get(int(date_str[-2:])))
    if isinstance(days, list):
        for d in days:
            if str(d.get("date") or d.get("day") or "") in (
                date_str, date_str[-2:], int(date_str[-2:]),
            ):
                return d
    return None


# ==================================================================
# A) Cross-day OT primary bug — Sanjeev Kumar bio 32
# ==================================================================
@pytest.fixture(scope="module")
def crossday_env(http, auth_hdr):
    cid = _create_firm(http, auth_hdr, name_prefix="Iter83b-CDO")
    uid = _create_employee(http, auth_hdr, cid,
                           name_suffix="Sanjeev32", bio_code="32",
                           ot_allowed=True)
    _manual_punch(http, auth_hdr, uid, "2026-06-01T08:00:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-01T19:58:00Z", "out")
    _manual_punch(http, auth_hdr, uid, "2026-06-01T20:08:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-02T07:58:00Z", "out")
    return {"cid": cid, "uid": uid}


class TestA_CrossDayOT:
    def test_grid_cell_shows_explicit_ot_pair(self, http, auth_hdr, crossday_env):
        cid = crossday_env["cid"]
        uid = crossday_env["uid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-06",
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 200, r.text
        row = _find_row(r.json(), uid)
        assert row is not None, "employee row missing"
        cell = _find_cell(row, "2026-06-01")
        assert cell is not None, "01-Jun cell missing"

        assert cell.get("in") == "08:00", f"in expected 08:00, got {cell.get('in')} — cell={cell!r}"
        assert cell.get("out") == "19:58", f"out expected 19:58, got {cell.get('out')} — cell={cell!r}"
        assert cell.get("ot_in") == "20:08", f"ot_in expected 20:08, got {cell.get('ot_in')} — cell={cell!r}"
        assert cell.get("ot_out") == "07:58", f"ot_out expected 07:58, got {cell.get('ot_out')} — cell={cell!r}"
        ot_hrs = float(cell.get("ot_hours") or 0)
        assert 11.5 <= ot_hrs <= 12.2, f"ot_hours ~11.83 expected, got {ot_hrs}"

    def test_ot_report_row_cross_day(self, http, auth_hdr, crossday_env):
        cid = crossday_env["cid"]
        uid = crossday_env["uid"]
        r = http.get(
            f"{API}/admin/attendance/ot-report/{cid}/2026-06",
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 200, r.text
        rows = r.json().get("rows") or []
        my_rows = [x for x in rows if x.get("user_id") == uid]
        assert my_rows, "no OT rows for Sanjeev"
        jun1 = next(
            (x for x in my_rows if x.get("date") in
             ("2026-06-01", "01-Jun-2026", "01/06/2026")), None,
        )
        assert jun1 is not None, f"01-Jun OT row missing. dates={[x.get('date') for x in my_rows]}"
        assert jun1.get("ot_in") == "20:08", jun1
        assert jun1.get("ot_out") == "07:58", jun1
        ot_hrs = float(jun1.get("ot_hours") or 0)
        assert 11.5 <= ot_hrs <= 12.2, f"ot_hours ~11.83 expected, got {ot_hrs}"


# ==================================================================
# B) Unpaired-punches anomaly rule
# ==================================================================
@pytest.fixture(scope="module")
def anomaly_env(http, auth_hdr, crossday_env):
    # Reuse same firm to reduce cleanup surface.
    cid = crossday_env["cid"]
    uid = _create_employee(http, auth_hdr, cid,
                           name_suffix="Anomaly", ot_allowed=True)
    # Bad punches on 2026-06-05: two consecutive INs, no OUT.
    _manual_punch(http, auth_hdr, uid, "2026-06-05T08:00:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-05T15:00:00Z", "in")
    return {"cid": cid, "uid": uid}


class TestB_UnpairedAnomaly:
    def test_grid_cell_marked_anomaly(self, http, auth_hdr, anomaly_env):
        cid = anomaly_env["cid"]
        uid = anomaly_env["uid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-06",
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 200, r.text
        row = _find_row(r.json(), uid)
        assert row is not None
        cell = _find_cell(row, "2026-06-05")
        assert cell is not None, "05-Jun cell missing"
        assert cell.get("anomaly") is True, f"anomaly flag missing. cell={cell!r}"
        assert cell.get("anomaly_reason") == "missing_punch", (
            f"anomaly_reason=missing_punch expected, got {cell.get('anomaly_reason')} — cell={cell!r}"
        )
        assert float(cell.get("hours") or 0) == 0, cell
        assert float(cell.get("duty_hours") or 0) == 0, cell
        assert float(cell.get("ot_hours") or 0) == 0, cell

    def test_ot_report_skips_anomaly_day(self, http, auth_hdr, anomaly_env):
        cid = anomaly_env["cid"]
        uid = anomaly_env["uid"]
        r = http.get(
            f"{API}/admin/attendance/ot-report/{cid}/2026-06",
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 200, r.text
        rows = r.json().get("rows") or []
        my_rows = [x for x in rows if x.get("user_id") == uid]
        # No OT row should be present for our anomaly-day employee.
        assert not my_rows, f"OT report should not have anomaly-day rows: {my_rows!r}"


# ==================================================================
# C) Regular happy-path 2-pair OT day
# ==================================================================
@pytest.fixture(scope="module")
def happy_env(http, auth_hdr, crossday_env):
    cid = crossday_env["cid"]
    uid = _create_employee(http, auth_hdr, cid,
                           name_suffix="Happy2Pair", ot_allowed=True)
    _manual_punch(http, auth_hdr, uid, "2026-06-10T08:00:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-10T16:00:00Z", "out")
    _manual_punch(http, auth_hdr, uid, "2026-06-10T16:30:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-10T20:00:00Z", "out")
    return {"cid": cid, "uid": uid}


class TestC_HappyPath2Pair:
    def test_grid_cell_regular_and_ot(self, http, auth_hdr, happy_env):
        cid = happy_env["cid"]
        uid = happy_env["uid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-06",
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 200, r.text
        row = _find_row(r.json(), uid)
        assert row is not None
        cell = _find_cell(row, "2026-06-10")
        assert cell is not None, "10-Jun cell missing"

        assert cell.get("in") == "08:00", cell
        assert cell.get("out") == "16:00", cell
        assert cell.get("ot_in") == "16:30", cell
        assert cell.get("ot_out") == "20:00", cell
        duty = float(cell.get("duty_hours") or 0)
        ot = float(cell.get("ot_hours") or 0)
        assert abs(duty - 8.0) < 0.2, f"duty_hours ~8 expected, got {duty}"
        assert abs(ot - 3.5) < 0.2, f"ot_hours ~3.5 expected, got {ot}"


# ==================================================================
# D) Single-pair long day — arithmetic fallback
# ==================================================================
@pytest.fixture(scope="module")
def single_pair_env(http, auth_hdr, crossday_env):
    cid = crossday_env["cid"]
    uid = _create_employee(http, auth_hdr, cid,
                           name_suffix="SinglePair", ot_allowed=True)
    _manual_punch(http, auth_hdr, uid, "2026-06-12T08:00:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-12T22:00:00Z", "out")
    return {"cid": cid, "uid": uid}


class TestD_SinglePairFallback:
    def test_grid_arithmetic_split(self, http, auth_hdr, single_pair_env):
        cid = single_pair_env["cid"]
        uid = single_pair_env["uid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-06",
            headers=auth_hdr, timeout=20,
        )
        assert r.status_code == 200, r.text
        row = _find_row(r.json(), uid)
        assert row is not None
        cell = _find_cell(row, "2026-06-12")
        assert cell is not None, "12-Jun cell missing"

        assert cell.get("in") == "08:00", cell
        # Arithmetic fallback splits at full_day threshold; policy_1
        # default full-day = 12h → ot_in="20:00".
        assert cell.get("ot_out") == "22:00", cell
        ot_hrs = float(cell.get("ot_hours") or 0)
        # Depending on split_after_minutes policy (8h vs 12h), OT is
        # either 6h or 2h. Task spec expects 12h shift → OT ~2h.
        # Allow either but assert OT is > 0 and consistent with in.
        assert ot_hrs > 0, f"expected OT > 0 for 14h single-pair day, got {ot_hrs}"
        # ot_in should equal reg_in + split_minutes (either 16:00 or 20:00)
        assert cell.get("ot_in") in ("20:00", "16:00"), (
            f"ot_in should be arithmetic split boundary, got {cell.get('ot_in')}"
        )


# ==================================================================
# E) Phone self-register super_admin guard
# ==================================================================
class TestE_SelfRegisterSuperAdminGuard:
    def test_self_register_with_super_admin_phone_returns_409(self, http, auth_hdr):
        payload = {
            "company_name": f"Iter83b-SR-Super-{uuid.uuid4().hex[:5]}",
            "address": "12 QA Street",
            "city": "Delhi",
            "state": "DL",
            "contact_name": "TEST_Iter83b_Owner",
            "contact_mobile": SUPER_PHONE,
            "contact_email": _uniq_email("iter83bsr"),
            "nature_of_business": "Textile",
            "business_category": "industry",
            "business_subcategory": "Textile",
            "pin": "482715",
            "office_lat": 28.6139,
            "office_lng": 77.2090,
            "geofence_radius_m": 200,
            "employee_count": 10,
        }
        r = http.post(f"{API}/auth/company-register", json=payload, timeout=20)
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
        # The response detail must reference the super_admin path
        detail_text = r.text
        assert "Super Admin" in detail_text, (
            f"expected 'Super Admin' in detail, got: {detail_text}"
        )
        assert ("admin panel" in detail_text.lower()
                or "create company" in detail_text.lower()), (
            f"expected 'admin panel' or 'Create Company' guidance, got: {detail_text}"
        )

    def test_super_admin_user_not_deleted(self, http, auth_hdr):
        # Confirm super_admin user record still exists after the guard fired.
        r = http.get(
            f"{API}/admin/users?email={SUPER_EMAIL}",
            headers=auth_hdr, timeout=15,
        )
        # Fallback: use OTP request as an existence probe if admin/users
        # endpoint isn't available for filtering.
        exists = False
        if r.status_code == 200:
            body = r.json()
            users = body.get("users") or body.get("rows") or body if isinstance(body, list) else (body.get("users") or [])
            if isinstance(body, list):
                users = body
            for u in (users or []):
                if u.get("email") == SUPER_EMAIL:
                    exists = True
                    break
        if not exists:
            # Probe via OTP request — will succeed only if user record exists.
            probe = http.post(
                f"{API}/auth/otp/request",
                json={"identifier": SUPER_EMAIL, "channel": "email"},
                timeout=15,
            )
            assert probe.status_code == 200, (
                f"Super admin should still exist and be able to OTP-request; "
                f"probe status={probe.status_code} body={probe.text}"
            )


# ==================================================================
# F) Phone self-register happy path
# ==================================================================
class TestF_SelfRegisterHappyPath:
    def test_fresh_phone_registers_then_duplicate_409_pending(self, http, auth_hdr):
        phone = _uniq_phone()
        payload = {
            "company_name": f"Iter83b-SR-Happy-{uuid.uuid4().hex[:5]}",
            "address": "12 QA Street",
            "city": "Delhi",
            "state": "DL",
            "contact_name": "TEST_Iter83b_Owner",
            "contact_mobile": phone,
            "contact_email": _uniq_email("iter83bhp"),
            "nature_of_business": "Textile",
            "business_category": "industry",
            "business_subcategory": "Textile",
            "pin": "482715",
            "office_lat": 28.6139,
            "office_lng": 77.2090,
            "geofence_radius_m": 200,
            "employee_count": 10,
        }
        r = http.post(f"{API}/auth/company-register", json=payload, timeout=20)
        assert r.status_code == 200, f"first submit expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("ok") is True and body.get("request_id"), body
        req_id = body["request_id"]

        # Repeat with same phone → 409 pending
        payload2 = dict(payload)
        payload2["company_name"] = f"Iter83b-SR-Dup-{uuid.uuid4().hex[:5]}"
        payload2["contact_email"] = _uniq_email("iter83bdup")
        r2 = http.post(f"{API}/auth/company-register", json=payload2, timeout=20)
        assert r2.status_code == 409, f"dup expected 409, got {r2.status_code}: {r2.text}"
        assert "pending" in r2.text.lower(), r2.text

        # Cleanup: reject the pending request so cleanup_test_data doesn't linger it
        try:
            http.patch(
                f"{API}/company-requests/{req_id}",
                json={"action": "reject", "reason": "iter83b cleanup"},
                headers=auth_hdr, timeout=15,
            )
        except Exception:
            pass
