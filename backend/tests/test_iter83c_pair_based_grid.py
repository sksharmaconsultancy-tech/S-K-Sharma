"""Iter 83c — Backend retest for the PAIR-BASED grid & OT derivation rewrite.

The 83b split_regular_ot_times helper was correct; the callers now consume its
output for BOTH display timestamps AND numeric hour calculations.

Covers:
 A) Sanjeev multi-day (PRIMARY): out=reg_out, ot_hours=pair-duration, next-day
    normal punches preserved.
 B) Single-pair long shift (14h continuous): 12h anomaly cap is gone,
    arithmetic fallback produces ot_in/ot_out/ot_hours.
 C) Unpaired-punches → anomaly (regression).
 D) Two-pair happy day (regression, full_day_hours=8).
 E) Approval — live-firm company_admin collision auto-rejects the request.
 F) Approval — super_admin phone collision auto-rejects, super_admin untouched.
 G) Regression: real production firm monthly-grid still returns 200.

Cleanup prefix: `Iter83c-` and `TEST_Iter83c_`.
"""
from __future__ import annotations

import os
import sys
import uuid
import asyncio

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
PROD_FIRM = "cmp_cb39e488a0"


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


def _uniq_email(prefix: str = "iter83c") -> str:
    return f"{prefix}.{uuid.uuid4().hex[:8]}@test.local"


def _create_firm(http, auth_hdr, name_prefix="Iter83c-OT", *, full_day_hours=None):
    unique = uuid.uuid4().hex[:6]
    payload = {
        "name": f"{name_prefix}-{unique}",
        "code": f"I83C{unique[:4].upper()}",
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
    if full_day_hours is not None:
        # Firm-level default (used by the grid engine for standard_h).
        async def _patch():
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            dbn = os.environ.get("DB_NAME", "test_database")
            db = client[dbn]
            await db.companies.update_one(
                {"company_id": cid},
                {"$set": {
                    "attendance_policy.full_day_hours": float(full_day_hours),
                    "attendance_policy.standard_working_hours": float(full_day_hours),
                }},
            )
            client.close()
        asyncio.get_event_loop().run_until_complete(_patch())
    return cid


def _create_employee(http, auth_hdr, cid, *, name_suffix="EMP",
                     bio_code=None, ot_allowed=True, full_day_hours=None):
    phone = _uniq_phone()
    payload = {
        "name": f"TEST_Iter83c_{name_suffix}",
        "phone": phone,
        "company_id": cid,
        "employee_code": f"T83C{uuid.uuid4().hex[:4].upper()}",
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
    override = {"ot_allowed": ot_allowed}
    if full_day_hours is not None:
        override["full_day_hours"] = full_day_hours
    ov = http.put(
        f"{API}/admin/employees/{uid}/attendance-policy-override",
        json=override, headers=auth_hdr, timeout=15,
    )
    assert ov.status_code == 200, ov.text
    return uid


def _manual_punch(http, auth_hdr, uid, at_iso, kind):
    r = http.post(
        f"{API}/admin/attendance/manual-punch",
        json={"user_id": uid, "at": at_iso, "kind": kind,
              "reason": "iter83c seed"},
        headers=auth_hdr, timeout=15,
    )
    assert r.status_code == 200, f"{kind} {at_iso} → {r.status_code} {r.text}"


def _find_row(body, uid):
    rows = body.get("employees") or body.get("rows") or []
    for e in rows:
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
                date_str, date_str[-2:], str(int(date_str[-2:])),
            ):
                return d
    return None


# ==================================================================
# A) Sanjeev multi-day (PRIMARY)
# ==================================================================
@pytest.fixture(scope="module")
def sanjeev_env(http, auth_hdr):
    cid = _create_firm(http, auth_hdr, name_prefix="Iter83c-Sanjeev",
                       full_day_hours=12)
    uid = _create_employee(http, auth_hdr, cid,
                           name_suffix="Sanjeev32", bio_code="32",
                           ot_allowed=True, full_day_hours=12)
    # 2026-06-01
    _manual_punch(http, auth_hdr, uid, "2026-06-01T08:00:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-01T19:58:00Z", "out")
    _manual_punch(http, auth_hdr, uid, "2026-06-01T20:08:00Z", "in")
    # 2026-06-02  (07:58 OUT will stitch back to 06-01)
    _manual_punch(http, auth_hdr, uid, "2026-06-02T07:58:00Z", "out")
    _manual_punch(http, auth_hdr, uid, "2026-06-02T08:02:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-02T19:57:00Z", "out")
    return {"cid": cid, "uid": uid}


class TestA_Sanjeev:
    def test_day01_pair_derivation(self, http, auth_hdr, sanjeev_env):
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{sanjeev_env['cid']}/2026-06",
            headers=auth_hdr, timeout=25,
        )
        assert r.status_code == 200, r.text
        row = _find_row(r.json(), sanjeev_env["uid"])
        assert row, "employee row missing"
        cell = _find_cell(row, "2026-06-01")
        assert cell, "01-Jun cell missing"

        assert cell.get("in") == "08:00", cell
        assert cell.get("out") == "19:58", f"out must be reg_out 19:58, got {cell.get('out')} — cell={cell!r}"
        assert cell.get("ot_in") == "20:08", cell
        assert cell.get("ot_out") == "07:58", cell
        duty = float(cell.get("duty_hours") or 0)
        ot = float(cell.get("ot_hours") or 0)
        hours = float(cell.get("hours") or 0)
        assert 11.8 <= duty <= 12.1, f"duty_hours ~11.97/12 expected, got {duty}"
        assert 11.5 <= ot <= 12.2, f"ot_hours ~11.83 expected, got {ot}"
        assert 23.5 <= hours <= 24.1, f"hours ~23.8 expected, got {hours}"

    def test_day02_not_blank(self, http, auth_hdr, sanjeev_env):
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{sanjeev_env['cid']}/2026-06",
            headers=auth_hdr, timeout=25,
        )
        assert r.status_code == 200, r.text
        row = _find_row(r.json(), sanjeev_env["uid"])
        cell = _find_cell(row, "2026-06-02")
        assert cell, "02-Jun cell missing (regression!)"
        assert cell.get("in") == "08:02", f"day02 in expected 08:02, got {cell.get('in')} — cell={cell!r}"
        assert cell.get("out") == "19:57", f"day02 out expected 19:57, got {cell.get('out')} — cell={cell!r}"
        assert not cell.get("ot_in"), f"day02 ot_in should be None, got {cell.get('ot_in')}"
        assert not cell.get("ot_out"), f"day02 ot_out should be None, got {cell.get('ot_out')}"
        duty = float(cell.get("duty_hours") or 0)
        ot = float(cell.get("ot_hours") or 0)
        hours = float(cell.get("hours") or 0)
        assert 11.7 <= duty <= 12.1, f"day02 duty ~11.92 expected, got {duty}"
        assert ot == 0.0, f"day02 ot_hours should be 0, got {ot}"
        assert 11.7 <= hours <= 12.1, f"day02 hours ~11.92 expected, got {hours}"

    def test_ot_report_only_day01(self, http, auth_hdr, sanjeev_env):
        r = http.get(
            f"{API}/admin/attendance/ot-report/{sanjeev_env['cid']}/2026-06",
            headers=auth_hdr, timeout=25,
        )
        assert r.status_code == 200, r.text
        rows = r.json().get("rows") or []
        mine = [x for x in rows if x.get("user_id") == sanjeev_env["uid"]]
        assert mine, f"no OT rows for Sanjeev. rows_count={len(rows)}"
        # Must include day-01 row
        d1 = next(
            (x for x in mine if x.get("date") in
             ("2026-06-01", "01-Jun-2026", "01/06/2026")), None,
        )
        assert d1 is not None, f"01-Jun OT row missing. dates={[x.get('date') for x in mine]}"
        assert d1.get("ot_in") == "20:08", d1
        assert d1.get("ot_out") == "07:58", d1
        oh = float(d1.get("ot_hours") or 0)
        assert 11.5 <= oh <= 12.2, f"day01 ot_hours ~11.83 expected, got {oh}"
        # Must NOT include day-02
        d2 = next(
            (x for x in mine if x.get("date") in
             ("2026-06-02", "02-Jun-2026", "02/06/2026")), None,
        )
        assert d2 is None, f"day02 OT row must NOT exist, got {d2!r}"


# ==================================================================
# B) Single-pair long shift (14h)
# ==================================================================
@pytest.fixture(scope="module")
def single_pair_env(http, auth_hdr, sanjeev_env):
    cid = sanjeev_env["cid"]
    uid = _create_employee(http, auth_hdr, cid,
                           name_suffix="SinglePair14h",
                           ot_allowed=True, full_day_hours=12)
    _manual_punch(http, auth_hdr, uid, "2026-06-10T08:00:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-10T22:00:00Z", "out")
    return {"cid": cid, "uid": uid}


class TestB_SinglePairLong:
    def test_arithmetic_fallback_split(self, http, auth_hdr, single_pair_env):
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{single_pair_env['cid']}/2026-06",
            headers=auth_hdr, timeout=25,
        )
        assert r.status_code == 200, r.text
        row = _find_row(r.json(), single_pair_env["uid"])
        assert row, "employee row missing"
        cell = _find_cell(row, "2026-06-10")
        assert cell, "10-Jun cell missing"

        assert cell.get("in") == "08:00", cell
        assert cell.get("out") == "20:00", f"reg_out at 12h boundary should be 20:00, got {cell.get('out')} — cell={cell!r}"
        assert cell.get("ot_in") == "20:00", cell
        assert cell.get("ot_out") == "22:00", cell
        duty = float(cell.get("duty_hours") or 0)
        ot = float(cell.get("ot_hours") or 0)
        hours = float(cell.get("hours") or 0)
        assert abs(duty - 12.0) < 0.2, f"duty ~12 expected, got {duty}"
        assert abs(ot - 2.0) < 0.2, f"ot ~2 expected, got {ot}"
        assert abs(hours - 14.0) < 0.2, f"hours ~14 expected, got {hours}"


# ==================================================================
# C) Unpaired punches → anomaly (regression)
# ==================================================================
@pytest.fixture(scope="module")
def anomaly_env(http, auth_hdr, sanjeev_env):
    cid = sanjeev_env["cid"]
    uid = _create_employee(http, auth_hdr, cid,
                           name_suffix="AnomalyMissing",
                           ot_allowed=True)
    _manual_punch(http, auth_hdr, uid, "2026-06-05T08:00:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-05T15:00:00Z", "in")
    return {"cid": cid, "uid": uid}


class TestC_Anomaly:
    def test_grid_marks_missing_punch(self, http, auth_hdr, anomaly_env):
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{anomaly_env['cid']}/2026-06",
            headers=auth_hdr, timeout=25,
        )
        assert r.status_code == 200, r.text
        row = _find_row(r.json(), anomaly_env["uid"])
        assert row
        cell = _find_cell(row, "2026-06-05")
        assert cell, "05-Jun cell missing"
        assert cell.get("anomaly") is True, f"anomaly flag missing. cell={cell!r}"
        assert cell.get("anomaly_reason") == "missing_punch", cell
        assert float(cell.get("hours") or 0) == 0, cell
        assert float(cell.get("duty_hours") or 0) == 0, cell
        assert float(cell.get("ot_hours") or 0) == 0, cell


# ==================================================================
# D) Two-pair happy day (full_day_hours=8)
# ==================================================================
@pytest.fixture(scope="module")
def happy2_env(http, auth_hdr, sanjeev_env):
    cid = sanjeev_env["cid"]
    uid = _create_employee(http, auth_hdr, cid,
                           name_suffix="Happy2Pair8h",
                           ot_allowed=True, full_day_hours=8)
    _manual_punch(http, auth_hdr, uid, "2026-06-11T08:00:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-11T16:00:00Z", "out")
    _manual_punch(http, auth_hdr, uid, "2026-06-11T16:30:00Z", "in")
    _manual_punch(http, auth_hdr, uid, "2026-06-11T20:00:00Z", "out")
    return {"cid": cid, "uid": uid}


class TestD_TwoPairHappy:
    def test_grid_two_pair(self, http, auth_hdr, happy2_env):
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{happy2_env['cid']}/2026-06",
            headers=auth_hdr, timeout=25,
        )
        assert r.status_code == 200, r.text
        row = _find_row(r.json(), happy2_env["uid"])
        cell = _find_cell(row, "2026-06-11")
        assert cell, "11-Jun cell missing"
        assert cell.get("in") == "08:00", cell
        assert cell.get("out") == "16:00", f"out should be reg_out 16:00, got {cell.get('out')} — cell={cell!r}"
        assert cell.get("ot_in") == "16:30", cell
        assert cell.get("ot_out") == "20:00", cell
        duty = float(cell.get("duty_hours") or 0)
        ot = float(cell.get("ot_hours") or 0)
        assert abs(duty - 8.0) < 0.2, f"duty ~8, got {duty}"
        assert abs(ot - 3.5) < 0.2, f"ot ~3.5, got {ot}"


# ==================================================================
# E) Approval — live-firm company_admin collision
# ==================================================================
class TestE_ApprovalLiveCollision:
    def test_approve_with_existing_live_admin_auto_rejects(
            self, http, auth_hdr, sanjeev_env):
        """Create firm+admin with phone P → insert pending self_register with
        same P → PATCH approve → 409 AND request.status == 'rejected'.
        """
        # 1) create a fresh test firm + company_admin user via /companies
        target_phone = "+919111100001"
        # First, purge any leftover users/requests with this phone (defensive)
        async def _pre_purge():
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            dbn = os.environ.get("DB_NAME", "test_database")
            db = client[dbn]
            await db.users.delete_many(
                {"phone": target_phone, "role": {"$ne": "super_admin"}}
            )
            await db.company_requests.delete_many(
                {"contact_mobile": target_phone}
            )
            client.close()
        asyncio.get_event_loop().run_until_complete(_pre_purge())

        unique = uuid.uuid4().hex[:5]
        firm_payload = {
            "name": f"Iter83c-LiveAdmin-{unique}",
            "code": f"I83CL{unique[:3].upper()}",
            "business_category": "industry",
            "business_subcategory": "Textile",
            "policy_variant": "policy_1",
            "office_lat": 28.6139,
            "office_lng": 77.2090,
            # admin contact
            "admin_name": "TEST_Iter83c_LiveAdmin",
            "admin_phone": target_phone,
            "admin_email": _uniq_email("iter83cadm"),
        }
        r = http.post(f"{API}/companies", json=firm_payload,
                      headers=auth_hdr, timeout=25)
        assert r.status_code in (200, 201), f"create firm: {r.status_code} {r.text}"
        firm_body = r.json()
        firm_cid = (
            firm_body.get("company_id")
            or (firm_body.get("company") or {}).get("company_id")
        )
        assert firm_cid

        # Ensure the admin user with this phone exists — if create-firm
        # didn't auto-create it, create it via /admin/employees promoted.
        async def _ensure_admin():
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            dbn = os.environ.get("DB_NAME", "test_database")
            db = client[dbn]
            u = await db.users.find_one({"phone": target_phone})
            if not u:
                await db.users.insert_one({
                    "user_id": f"user_{uuid.uuid4().hex[:12]}",
                    "email": firm_payload["admin_email"],
                    "phone": target_phone,
                    "name": "TEST_Iter83c_LiveAdmin",
                    "role": "company_admin",
                    "company_id": firm_cid,
                    "employee_code": "ADMIN",
                    "onboarded": True,
                    "approval_status": "approved",
                    "has_pin": True,
                    "pin_hash": "$2b$12$placeholderhash",
                })
            client.close()
        asyncio.get_event_loop().run_until_complete(_ensure_admin())

        # 2) directly insert a pending self_register with same phone
        async def _insert_pending():
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            dbn = os.environ.get("DB_NAME", "test_database")
            db = client[dbn]
            req_id = f"req_{uuid.uuid4().hex[:12]}"
            await db.company_requests.insert_one({
                "request_id": req_id,
                "kind": "self_register",
                "status": "pending",
                "company_name": f"Iter83c-Dup-{uuid.uuid4().hex[:5]}",
                "address": "12 QA Street",
                "city": "Delhi",
                "state": "DL",
                "contact_name": "TEST_Iter83c_DupApplicant",
                "contact_mobile": target_phone,
                "contact_email": _uniq_email("iter83cdup"),
                "nature_of_business": "Textile",
                "business_category": "industry",
                "business_subcategory": "Textile",
                "admin_pin_hash": "$2b$12$placeholderhash",
                "office_lat": 28.6139,
                "office_lng": 77.2090,
                "geofence_radius_m": 200,
                "employee_count": 10,
                "created_at": "2026-01-01T00:00:00Z",
            })
            client.close()
            return req_id
        req_id = asyncio.get_event_loop().run_until_complete(_insert_pending())

        # 3) PATCH approve → 409
        r = http.patch(f"{API}/company-requests/{req_id}",
                       json={"status": "approved"},
                       headers=auth_hdr, timeout=20)
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
        assert "already registered as company admin" in r.text.lower(), r.text

        # 4) DB shows status == rejected with admin_note
        async def _fetch():
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            dbn = os.environ.get("DB_NAME", "test_database")
            db = client[dbn]
            doc = await db.company_requests.find_one(
                {"request_id": req_id}, {"_id": 0},
            )
            client.close()
            return doc
        doc = asyncio.get_event_loop().run_until_complete(_fetch())
        assert doc is not None, "request should still exist in DB"
        assert doc.get("status") == "rejected", (
            f"status should be 'rejected', got {doc.get('status')!r}. doc={doc!r}"
        )
        assert doc.get("admin_note"), f"admin_note missing. doc={doc!r}"
        assert "company admin" in (doc.get("admin_note") or "").lower(), doc


# ==================================================================
# F) Approval — super_admin phone collision
# ==================================================================
class TestF_ApprovalSuperAdmin:
    def test_approve_with_super_admin_phone_auto_rejects(
            self, http, auth_hdr):
        # Insert a pending self_register with the super_admin phone
        async def _insert():
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            dbn = os.environ.get("DB_NAME", "test_database")
            db = client[dbn]
            req_id = f"req_{uuid.uuid4().hex[:12]}"
            await db.company_requests.insert_one({
                "request_id": req_id,
                "kind": "self_register",
                "status": "pending",
                "company_name": f"Iter83c-SuperDup-{uuid.uuid4().hex[:5]}",
                "address": "12 QA Street",
                "city": "Delhi",
                "state": "DL",
                "contact_name": "TEST_Iter83c_SuperDup",
                "contact_mobile": SUPER_PHONE,
                "contact_email": _uniq_email("iter83csuper"),
                "nature_of_business": "Textile",
                "business_category": "industry",
                "business_subcategory": "Textile",
                "admin_pin_hash": "$2b$12$placeholderhash",
                "office_lat": 28.6139,
                "office_lng": 77.2090,
                "geofence_radius_m": 200,
                "employee_count": 10,
                "created_at": "2026-01-01T00:00:00Z",
            })
            client.close()
            return req_id
        req_id = asyncio.get_event_loop().run_until_complete(_insert())

        r = http.patch(f"{API}/company-requests/{req_id}",
                       json={"status": "approved"},
                       headers=auth_hdr, timeout=20)
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
        assert "super admin" in r.text.lower(), r.text

        # DB — status rejected
        async def _fetch():
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(os.environ["MONGO_URL"])
            dbn = os.environ.get("DB_NAME", "test_database")
            db = client[dbn]
            doc = await db.company_requests.find_one(
                {"request_id": req_id}, {"_id": 0},
            )
            client.close()
            return doc
        doc = asyncio.get_event_loop().run_until_complete(_fetch())
        assert doc.get("status") == "rejected", (
            f"status should be 'rejected', got {doc.get('status')!r}. doc={doc!r}"
        )
        assert "super admin" in (doc.get("admin_note") or "").lower(), doc

        # Super admin still exists (probe via OTP)
        probe = http.post(
            f"{API}/auth/otp/request",
            json={"identifier": SUPER_EMAIL, "channel": "email"},
            timeout=15,
        )
        assert probe.status_code == 200, (
            f"super_admin should still be usable; probe={probe.status_code} {probe.text}"
        )


# ==================================================================
# G) Regression: real firm still returns 200
# ==================================================================
class TestG_ProductionFirmRegression:
    def test_prod_firm_monthly_grid(self, http, auth_hdr):
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{PROD_FIRM}/2026-06",
            headers=auth_hdr, timeout=25,
        )
        assert r.status_code == 200, f"prod firm grid: {r.status_code} {r.text[:400]}"
        body = r.json()
        assert isinstance(body.get("employees") or body.get("rows"), list), body
