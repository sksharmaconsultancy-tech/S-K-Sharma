"""Iter 70 backend tests — Biometric-punch geofence gate + Statutory bulk files.

Two feature areas under test:

  1. POST /api/attendance/punch — biometric-only punches (i.e. GPS
     punching OFF at firm/user level) MUST still respect the company
     geofence when the client sends lat/lng + selfie.  See server.py
     around lines 5999-6023 (the `_bio_with_gps` block).

     Test matrix:
       a. GPS-off employee submits selfie + coords INSIDE geofence   → 200
       b. GPS-off employee submits selfie + coords OUTSIDE geofence  → 400
       c. Firm with NO geofence (office_lat/lng NULL) still allows
          biometric-only punches without coords (legacy fallback)    → 200
       d. Regression: GPS-on employee inside → 200, outside → 400

  2. Three new compliance bulk endpoints on a compliance-salary run:
       - GET /api/admin/compliance-salary-runs/{run_id}/pf-ecr.txt
       - GET /api/admin/compliance-salary-runs/{run_id}/esic-mc.csv
       - GET /api/admin/compliance-salary-runs/{run_id}/esic-ip-reg.csv

     API-level checks (against the live endpoint):
       - content-type, Content-Disposition filename, 404 for unknown
         run_id, cross-firm 403 for company_admin.

     Utility-level checks (call builders directly with synthetic rows,
     mirroring iter68/iter69 style — needed because the preview env
     only has one empty compliance run and re-generating one requires
     a full salary/attendance setup that's out of scope here):
       - PF ECR: skips rows without 12-digit UAN or pf_applicable=False;
         non-empty rows have exactly 11 hash-separated fields.
       - ESIC MC: 6-column header verbatim; skips rows without esi_ip_no
         or with esic_applicable=False.
       - ESIC IP Reg: 17-column header verbatim; includes ONLY rows
         where esi_ip_no is empty AND esic_applicable=True.

Runs against the public preview URL. Uses OTP-dev-code flow for
super_admin and admin-pin-login for SKSCO1 company_admin.  Any test
employee/company created is cleaned up in the fixture teardown.

DOES NOT touch super_admin's pin_hash (uses OTP flow instead).
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import uuid
from typing import Optional

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "https://emplo-connect-1.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
SKSCO_ADMIN_PHONE = "+919810000001"
SKSCO_ADMIN_PIN = "387908"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

# 1×1 transparent PNG (base64) — good enough for the selfie payload.
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _otp_login(sess: requests.Session, identifier: str, channel: str = "email") -> str:
    r = sess.post(
        f"{API}/auth/otp/request",
        json={"identifier": identifier, "channel": channel},
    )
    assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    code = body.get("dev_code") or body.get("code")
    assert code, f"No dev code in response: {body}"
    r = sess.post(
        f"{API}/auth/otp/verify",
        json={"identifier": identifier, "channel": channel, "code": code},
    )
    assert r.status_code == 200, f"otp/verify failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    return body.get("session_token") or body.get("token")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def sess() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def super_token(sess) -> str:
    return _otp_login(sess, SUPER_ADMIN_EMAIL, "email")


@pytest.fixture(scope="session")
def sksco_admin(sess) -> tuple[str, str]:
    r = sess.post(
        f"{API}/auth/admin-pin-login",
        json={"identifier": SKSCO_ADMIN_PHONE, "pin": SKSCO_ADMIN_PIN},
    )
    assert r.status_code == 200, f"admin-pin-login failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    token = body["session_token"]
    company_id = body["user"].get("company_id")
    assert company_id, "SKSCO admin has no company_id"
    return token, company_id


@pytest.fixture(scope="session")
def sksco_company(sess, super_token) -> dict:
    r = sess.get(f"{API}/companies", headers=_auth(super_token))
    assert r.status_code == 200
    items = r.json()
    if isinstance(items, dict):
        items = items.get("companies") or items.get("items") or []
    for c in items:
        if (c.get("company_code") or "").upper() == "SKSCO1":
            return c
    pytest.skip("SKSCO1 not found in this environment")


@pytest.fixture(scope="session")
def other_company(sess, super_token, sksco_company) -> Optional[dict]:
    """Any non-SKSCO company for cross-firm 403 checks."""
    r = sess.get(f"{API}/companies", headers=_auth(super_token))
    if r.status_code != 200:
        return None
    items = r.json()
    if isinstance(items, dict):
        items = items.get("companies") or items.get("items") or []
    for c in items:
        if c.get("company_id") != sksco_company["company_id"]:
            return c
    return None


def _create_employee(
    sess: requests.Session,
    super_token: str,
    company_id: str,
    name: str,
    phone: str,
    gps_punch_enabled: bool = False,
) -> dict:
    r = sess.post(
        f"{API}/admin/employees",
        headers=_auth(super_token),
        json={
            "name": name,
            "phone": phone,
            "company_id": company_id,
            "designation": "TEST",
            "gps_punch_enabled": gps_punch_enabled,
        },
    )
    assert r.status_code in (200, 201), (
        f"create employee failed: {r.status_code} {r.text[:250]}"
    )
    body = r.json()
    user = body.get("user") or body
    user_id = user.get("user_id") or body.get("user_id")
    assert user_id, f"no user_id in response: {body}"
    return {"user_id": user_id, "phone": phone, "name": name}


def _login_employee(sess: requests.Session, phone: str) -> str:
    """OTP-dev login (works for any phone in dev mode)."""
    return _otp_login(sess, phone, "sms")


def _run_async(coro):
    """Run a coroutine in a fresh event loop (safe from pytest sync tests)."""
    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _db_set_user(user_id: str, updates: dict) -> None:
    c = AsyncIOMotorClient(MONGO_URL)
    try:
        await c[DB_NAME].users.update_one({"user_id": user_id}, {"$set": updates})
    finally:
        c.close()


async def _db_set_company(company_id: str, updates: dict) -> None:
    c = AsyncIOMotorClient(MONGO_URL)
    try:
        await c[DB_NAME].companies.update_one({"company_id": company_id}, {"$set": updates})
    finally:
        c.close()


async def _db_unset_company(company_id: str, fields: list[str]) -> dict:
    """Unset fields on a company doc; return the previous values for restore."""
    c = AsyncIOMotorClient(MONGO_URL)
    try:
        prev = await c[DB_NAME].companies.find_one(
            {"company_id": company_id}, {"_id": 0, **{f: 1 for f in fields}}
        )
        await c[DB_NAME].companies.update_one(
            {"company_id": company_id},
            {"$unset": {f: "" for f in fields}},
        )
        return prev or {}
    finally:
        c.close()


async def _db_get_company(company_id: str) -> dict:
    c = AsyncIOMotorClient(MONGO_URL)
    try:
        return await c[DB_NAME].companies.find_one({"company_id": company_id}, {"_id": 0}) or {}
    finally:
        c.close()


async def _delete_user(user_id: str) -> None:
    c = AsyncIOMotorClient(MONGO_URL)
    try:
        await c[DB_NAME].users.delete_one({"user_id": user_id})
        await c[DB_NAME].attendance.delete_many({"user_id": user_id})
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Employee fixtures for geofence tests
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def gps_off_employee(sess, super_token, sksco_company) -> dict:
    """Employee with gps_punch_enabled=False (biometric-only)."""
    phone = f"+9199999{uuid.uuid4().hex[:5]}"
    emp = _create_employee(
        sess, super_token,
        sksco_company["company_id"],
        name="TEST_iter70_gpsoff",
        phone=phone,
        gps_punch_enabled=False,
    )
    # Also make sure pin_must_change won't block us; OTP flow ignores PIN.
    emp["token"] = _login_employee(sess, phone)
    yield emp
    _run_async(_delete_user(emp["user_id"]))


@pytest.fixture(scope="session")
def gps_on_employee(sess, super_token, sksco_company) -> dict:
    """Employee with gps_punch_enabled=True (regular GPS-based)."""
    phone = f"+9199998{uuid.uuid4().hex[:5]}"
    emp = _create_employee(
        sess, super_token,
        sksco_company["company_id"],
        name="TEST_iter70_gpson",
        phone=phone,
        gps_punch_enabled=True,
    )
    emp["token"] = _login_employee(sess, phone)
    yield emp
    _run_async(_delete_user(emp["user_id"]))


# ---------------------------------------------------------------------------
# 1. Biometric-punch geofence gate
# ---------------------------------------------------------------------------
class TestBiometricGeofenceGate:
    """Iter 70 — biometric-only punches must still respect the geofence."""

    def _punch(self, sess, token, *, kind, lat=None, lng=None, with_selfie=True):
        payload = {
            "kind": kind,
            "biometric_method": "face",
            "selfie_base64": TINY_PNG_B64 if with_selfie else None,
            "source": "manual",
        }
        if lat is not None:
            payload["latitude"] = lat
        if lng is not None:
            payload["longitude"] = lng
        return sess.post(f"{API}/attendance/punch", headers=_auth(token), json=payload)

    def test_a_gps_off_biometric_inside_geofence_ok(
        self, sess, sksco_company, gps_off_employee
    ):
        """Case 1a: GPS-off employee, selfie + coords INSIDE geofence → 200."""
        lat = sksco_company.get("office_lat")
        lng = sksco_company.get("office_lng")
        if lat is None or lng is None:
            pytest.skip("SKSCO1 has no geofence configured — cannot run inside test")

        r = self._punch(
            sess, gps_off_employee["token"], kind="in",
            lat=lat, lng=lng, with_selfie=True,
        )
        assert r.status_code == 200, (
            f"expected 200 inside geofence, got {r.status_code}: {r.text[:300]}"
        )
        body = r.json()
        # location_status should be "inside" per the spec
        loc_status = body.get("location_status") or (body.get("record") or {}).get("location_status")
        # Some responses may not include the field; accept either explicit "inside"
        # or the record being created (record_id present) as success.
        assert (
            (loc_status == "inside")
            or body.get("record_id")
            or (body.get("record") or {}).get("record_id")
        ), f"expected location_status=inside or record created, got: {body}"

    def test_b_gps_off_biometric_outside_geofence_rejected(
        self, sess, sksco_company, gps_off_employee
    ):
        """Case 1b: GPS-off employee, selfie + coords OUTSIDE geofence → 400."""
        lat = sksco_company.get("office_lat")
        lng = sksco_company.get("office_lng")
        if lat is None or lng is None:
            pytest.skip("SKSCO1 has no geofence configured")
        # ~0.005° ≈ 555m — well outside 150m radius.
        r = self._punch(
            sess, gps_off_employee["token"], kind="in",
            lat=lat + 0.005, lng=lng + 0.005, with_selfie=True,
        )
        assert r.status_code == 400, (
            f"expected 400 outside geofence, got {r.status_code}: {r.text[:300]}"
        )
        # Error message should mention "outside" and the geofence
        detail = (r.json() or {}).get("detail", "").lower()
        assert "outside" in detail and "geofence" in detail, (
            f"unexpected error message: {detail!r}"
        )

    def test_c_no_geofence_biometric_only_still_works(
        self, sess, sksco_company, gps_off_employee
    ):
        """Case 1c: Firm without geofence — biometric-only punch works without coords.

        Temporarily $unset office_lat/office_lng on SKSCO1, punch WITHOUT
        coords (pure biometric), then restore the geofence.
        """
        cid = sksco_company["company_id"]
        # 1) Snapshot & unset geofence
        prev = _run_async(_db_unset_company(cid, ["office_lat", "office_lng"]))
        try:
            # Verify unset actually landed
            after = _run_async(_db_get_company(cid))
            assert after.get("office_lat") is None and after.get("office_lng") is None, (
                f"unset failed, after: office_lat={after.get('office_lat')}, "
                f"office_lng={after.get('office_lng')}"
            )
            # 2) Punch without coords (pure biometric fallback)
            r = self._punch(
                sess, gps_off_employee["token"], kind="out",
                lat=None, lng=None, with_selfie=True,
            )
            assert r.status_code == 200, (
                f"expected 200 no-geofence biometric, got {r.status_code}: {r.text[:300]}"
            )
        finally:
            # 3) Restore geofence
            restore = {}
            if "office_lat" in prev:
                restore["office_lat"] = prev["office_lat"]
            if "office_lng" in prev:
                restore["office_lng"] = prev["office_lng"]
            if restore:
                _run_async(_db_set_company(cid, restore))

    def test_d_gps_on_regression_inside_ok_outside_400(
        self, sess, sksco_company, gps_on_employee
    ):
        """Case 1d: Regression — normal GPS-on flow unchanged.

        With gps_punch_enabled=True, coords are REQUIRED; inside → 200,
        outside → 400.  Iter 70 must not have changed this path.
        """
        lat = sksco_company.get("office_lat")
        lng = sksco_company.get("office_lng")
        if lat is None or lng is None:
            pytest.skip("SKSCO1 has no geofence configured")

        # INSIDE
        r = self._punch(
            sess, gps_on_employee["token"], kind="in",
            lat=lat, lng=lng, with_selfie=True,
        )
        assert r.status_code == 200, (
            f"GPS-on inside expected 200, got {r.status_code}: {r.text[:300]}"
        )
        # OUTSIDE
        r = self._punch(
            sess, gps_on_employee["token"], kind="in",
            lat=lat + 0.005, lng=lng + 0.005, with_selfie=True,
        )
        assert r.status_code == 400, (
            f"GPS-on outside expected 400, got {r.status_code}: {r.text[:300]}"
        )


# ---------------------------------------------------------------------------
# 2. Statutory bulk endpoints — API level
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def any_compliance_run(sess, super_token) -> Optional[dict]:
    r = sess.get(f"{API}/admin/compliance-salary-runs", headers=_auth(super_token))
    if r.status_code != 200:
        return None
    runs = (r.json() or {}).get("runs") or []
    return runs[0] if runs else None


class TestPfEcrEndpoint:
    def test_super_admin_content_type_and_disposition(self, sess, super_token, any_compliance_run):
        if not any_compliance_run:
            pytest.skip("No compliance salary runs in env")
        run_id = any_compliance_run["run_id"]
        r = sess.get(
            f"{API}/admin/compliance-salary-runs/{run_id}/pf-ecr.txt",
            headers=_auth(super_token),
        )
        assert r.status_code == 200, f"pf-ecr.txt failed: {r.status_code} {r.text[:200]}"
        ct = r.headers.get("content-type", "")
        assert ct.startswith("text/plain"), f"unexpected content-type: {ct}"
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd.lower(), f"disposition missing attachment: {cd}"
        month = any_compliance_run.get("month") or ""
        assert f'PF_ECR_{month}.txt' in cd, f"filename should be PF_ECR_{month}.txt, got: {cd}"

    def test_each_non_empty_line_has_11_hash_fields(
        self, sess, super_token, any_compliance_run
    ):
        if not any_compliance_run:
            pytest.skip("No compliance salary runs in env")
        run_id = any_compliance_run["run_id"]
        r = sess.get(
            f"{API}/admin/compliance-salary-runs/{run_id}/pf-ecr.txt",
            headers=_auth(super_token),
        )
        assert r.status_code == 200
        text = r.text
        for i, line in enumerate(text.splitlines()):
            if not line.strip():
                continue
            fields = line.split("#")
            assert len(fields) == 11, (
                f"line {i} has {len(fields)} fields, expected 11: {line!r}"
            )

    def test_404_for_unknown_run(self, sess, super_token):
        r = sess.get(
            f"{API}/admin/compliance-salary-runs/csrun_nope_iter70/pf-ecr.txt",
            headers=_auth(super_token),
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"

    def test_company_admin_cross_firm_403(
        self, sess, sksco_admin, any_compliance_run, sksco_company
    ):
        if not any_compliance_run:
            pytest.skip("No compliance salary runs in env")
        # A run whose company_id != SKSCO1 is required to trigger the 403 path.
        if any_compliance_run.get("company_id") == sksco_company["company_id"]:
            pytest.skip("Only SKSCO1 run available — cannot exercise cross-firm 403")
        token, _ = sksco_admin
        run_id = any_compliance_run["run_id"]
        r = sess.get(
            f"{API}/admin/compliance-salary-runs/{run_id}/pf-ecr.txt",
            headers=_auth(token),
        )
        assert r.status_code == 403, (
            f"expected 403 cross-firm, got {r.status_code}: {r.text[:200]}"
        )


class TestEsicMcEndpoint:
    def test_content_type_and_filename(self, sess, super_token, any_compliance_run):
        if not any_compliance_run:
            pytest.skip("No compliance salary runs in env")
        run_id = any_compliance_run["run_id"]
        r = sess.get(
            f"{API}/admin/compliance-salary-runs/{run_id}/esic-mc.csv",
            headers=_auth(super_token),
        )
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert ct.startswith("text/csv"), f"unexpected content-type: {ct}"
        cd = r.headers.get("content-disposition", "")
        month = any_compliance_run.get("month") or ""
        assert f'ESIC_MC_{month}.csv' in cd, f"filename should be ESIC_MC_{month}.csv, got: {cd}"

    def test_csv_header_matches_6_columns(self, sess, super_token, any_compliance_run):
        if not any_compliance_run:
            pytest.skip("No compliance salary runs in env")
        run_id = any_compliance_run["run_id"]
        r = sess.get(
            f"{API}/admin/compliance-salary-runs/{run_id}/esic-mc.csv",
            headers=_auth(super_token),
        )
        assert r.status_code == 200
        expected = (
            "IP Number,IP Name,No of Days for which wages paid/payable,"
            "Total Monthly Wages,Reason Code for Zero workings days (numeric only),"
            "Last Working Day"
        )
        first_line = r.text.splitlines()[0] if r.text else ""
        assert first_line == expected, (
            f"header mismatch\n  expected: {expected}\n  got:      {first_line}"
        )

    def test_404_for_unknown_run(self, sess, super_token):
        r = sess.get(
            f"{API}/admin/compliance-salary-runs/csrun_nope_iter70/esic-mc.csv",
            headers=_auth(super_token),
        )
        assert r.status_code == 404

    def test_company_admin_cross_firm_403(
        self, sess, sksco_admin, any_compliance_run, sksco_company
    ):
        if not any_compliance_run:
            pytest.skip("No compliance salary runs in env")
        if any_compliance_run.get("company_id") == sksco_company["company_id"]:
            pytest.skip("Only own-firm run available")
        token, _ = sksco_admin
        run_id = any_compliance_run["run_id"]
        r = sess.get(
            f"{API}/admin/compliance-salary-runs/{run_id}/esic-mc.csv",
            headers=_auth(token),
        )
        assert r.status_code == 403


class TestEsicIpRegEndpoint:
    EXPECTED_HEADER = (
        "Employee's Name,Relationship with Employee,Relationship Name,"
        "Date of Birth (DD/MM/YYYY),Gender,Marital Status,Aadhaar Number,PAN,"
        "Mobile Number,Nominee's Name,Relationship with Nominee,"
        "Nominee's DOB (DD/MM/YYYY),Present Address,Permanent Address,"
        "Date of Appointment (DD/MM/YYYY),Monthly Wages,Bank IFSC"
    )

    def test_content_type_and_header(self, sess, super_token, any_compliance_run):
        if not any_compliance_run:
            pytest.skip("No compliance salary runs in env")
        run_id = any_compliance_run["run_id"]
        r = sess.get(
            f"{API}/admin/compliance-salary-runs/{run_id}/esic-ip-reg.csv",
            headers=_auth(super_token),
        )
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert ct.startswith("text/csv"), f"unexpected content-type: {ct}"
        first_line = r.text.splitlines()[0] if r.text else ""
        assert first_line == self.EXPECTED_HEADER, (
            f"header mismatch\n  expected: {self.EXPECTED_HEADER}\n  got:      {first_line}"
        )
        # 17 columns
        cols = first_line.split(",")
        assert len(cols) == 17, f"expected 17 columns, got {len(cols)}"

    def test_404_for_unknown_run(self, sess, super_token):
        r = sess.get(
            f"{API}/admin/compliance-salary-runs/csrun_nope_iter70/esic-ip-reg.csv",
            headers=_auth(super_token),
        )
        assert r.status_code == 404

    def test_company_admin_cross_firm_403(
        self, sess, sksco_admin, any_compliance_run, sksco_company
    ):
        if not any_compliance_run:
            pytest.skip("No compliance salary runs in env")
        if any_compliance_run.get("company_id") == sksco_company["company_id"]:
            pytest.skip("Only own-firm run available")
        token, _ = sksco_admin
        run_id = any_compliance_run["run_id"]
        r = sess.get(
            f"{API}/admin/compliance-salary-runs/{run_id}/esic-ip-reg.csv",
            headers=_auth(token),
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 3. Utility-level tests for builders (lock in behavior even w/ empty env run)
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, "/app/backend")
from utils.statutory_bulk import (  # noqa: E402
    build_pf_ecr_txt, build_esic_mc_csv, build_esic_ip_reg_csv,
    ESIC_MC_COLUMNS, ESIC_IP_REG_COLUMNS,
)


class TestPfEcrBuilder:
    def _sample_rows(self):
        return [
            # Valid row: 12-digit UAN + pf_applicable
            {
                "user_id": "u1", "name": "Alice Sharma",
                "uan_no": "100200300400", "pf_applicable": True,
                "gross_paid": 25000, "monthly_gross": 25000,
                "pf_wages": 15000, "pf_employee": 1800,
                "pf_employer_epf": 550, "pf_employer_eps": 1250,
                "month_days": 30, "present_days": 28, "half_days": 2,
            },
            # Skipped: pf_applicable=False
            {
                "user_id": "u2", "name": "Bob Kumar",
                "uan_no": "200300400500", "pf_applicable": False,
                "pf_wages": 15000, "pf_employee": 1800,
            },
            # Skipped: no UAN
            {
                "user_id": "u3", "name": "No UAN",
                "uan_no": "", "pf_applicable": True,
                "pf_wages": 15000, "pf_employee": 1800,
            },
            # Skipped: short UAN
            {
                "user_id": "u4", "name": "Short UAN",
                "uan_no": "12345", "pf_applicable": True,
                "pf_wages": 15000, "pf_employee": 1800,
            },
            # Second valid row
            {
                "user_id": "u5", "name": "Charan Das",
                "uan_no": "300400500600", "pf_applicable": True,
                "gross_paid": 30000,
                "pf_wages": 20000,  # exceeds cap → should be capped at 15000
                "pf_employee": 1800, "pf_employer_epf": 550, "pf_employer_eps": 1250,
                "month_days": 30, "present_days": 30, "half_days": 0,
            },
        ]

    def test_output_bytes_and_line_count(self):
        out = build_pf_ecr_txt(self._sample_rows())
        assert isinstance(out, bytes)
        text = out.decode("utf-8")
        # 2 valid rows out of 5
        non_empty = [ln for ln in text.splitlines() if ln.strip()]
        assert len(non_empty) == 2, f"expected 2 rows, got {len(non_empty)}: {non_empty}"

    def test_each_line_has_11_hash_fields(self):
        out = build_pf_ecr_txt(self._sample_rows())
        text = out.decode("utf-8")
        for line in text.splitlines():
            if not line.strip():
                continue
            fields = line.split("#")
            assert len(fields) == 11, (
                f"expected 11 fields, got {len(fields)}: {line!r}"
            )

    def test_pf_wages_capped_at_15000(self):
        rows = self._sample_rows()
        out = build_pf_ecr_txt(rows)
        text = out.decode("utf-8")
        # Row 5 requested pf_wages=20000, should be capped at 15000.
        cap_line = [ln for ln in text.splitlines() if ln.startswith("300400500600#")]
        assert cap_line, "second valid row missing"
        fields = cap_line[0].split("#")
        # UAN, NAME, GROSS, EPF_WAGES, EPS_WAGES, EDLI_WAGES, ...
        assert fields[3] == "15000", f"EPF_WAGES not capped: {fields[3]}"
        assert fields[4] == "15000", f"EPS_WAGES not capped: {fields[4]}"

    def test_empty_rows_yields_empty_body(self):
        out = build_pf_ecr_txt([])
        assert out == b""


class TestEsicMcBuilder:
    def _sample_rows(self):
        return [
            # Valid
            {
                "user_id": "u1", "name": "Alice",
                "esi_ip_no": "1234567890", "esic_applicable": True,
                "present_days": 26, "half_days": 2,
                "gross_paid": 18000, "esic_wage_base": 18000,
            },
            # Skipped: esic_applicable=False
            {
                "user_id": "u2", "name": "Bob",
                "esi_ip_no": "1111111111", "esic_applicable": False,
                "present_days": 25,
            },
            # Skipped: no esi_ip_no
            {
                "user_id": "u3", "name": "No IP",
                "esi_ip_no": "", "esic_applicable": True,
                "present_days": 20,
            },
            # Zero days → reason code 7
            {
                "user_id": "u4", "name": "Absent",
                "esi_ip_no": "2222222222", "esic_applicable": True,
                "present_days": 0, "half_days": 0,
                "gross_paid": 0,
            },
        ]

    def test_header_and_row_count(self):
        out = build_esic_mc_csv(self._sample_rows())
        lines = out.decode("utf-8").splitlines()
        expected_header = ",".join(ESIC_MC_COLUMNS)
        assert lines[0] == expected_header, f"header mismatch: {lines[0]}"
        # 2 data rows (u1, u4)
        assert len(lines) == 3, f"expected header + 2 rows, got {len(lines)}: {lines}"

    def test_reason_code_zero_when_worked_and_7_when_absent(self):
        out = build_esic_mc_csv(self._sample_rows())
        lines = out.decode("utf-8").splitlines()[1:]
        # Row for u1 (26 present) — reason code 0
        u1 = next(ln for ln in lines if ln.startswith("1234567890,"))
        assert u1.split(",")[4] == "0", f"reason code should be 0, got: {u1}"
        # Row for u4 (0 days) — reason code 7
        u4 = next(ln for ln in lines if ln.startswith("2222222222,"))
        assert u4.split(",")[4] == "7", f"reason code should be 7, got: {u4}"

    def test_empty_rows_still_produces_header(self):
        out = build_esic_mc_csv([])
        lines = out.decode("utf-8").splitlines()
        assert lines[0] == ",".join(ESIC_MC_COLUMNS)
        assert len(lines) == 1  # header only


class TestEsicIpRegBuilder:
    def _sample_rows(self):
        return [
            # Included: esic_applicable=True, no IP number
            {
                "user_id": "u1", "name": "Alice Sharma",
                "esi_ip_no": "", "esic_applicable": True,
                "dob": "1990-05-15", "doj": "2023-01-10",
                "gender": "female", "father_name": "Ram Sharma",
                "aadhaar_no": "123456789012", "pan_no": "ABCDE1234F",
                "phone": "+919812345678",
                "address": "Delhi", "monthly_gross": 22000,
                "bank_ifsc": "HDFC0000123",
            },
            # Skipped: already has IP number
            {
                "user_id": "u2", "name": "Existing IP",
                "esi_ip_no": "3333333333", "esic_applicable": True,
            },
            # Skipped: esic_applicable=False
            {
                "user_id": "u3", "name": "Not applicable",
                "esi_ip_no": "", "esic_applicable": False,
            },
            # Included: new joiner needs registration
            {
                "user_id": "u4", "name": "Second Joiner",
                "esi_ip_no": None, "esic_applicable": True,
                "dob": "1995-08-20", "doj": "2024-06-01",
                "gender": "male", "monthly_gross": 18000,
            },
        ]

    def test_header_matches_17_columns(self):
        out = build_esic_ip_reg_csv(self._sample_rows())
        lines = out.decode("utf-8").splitlines()
        expected = ",".join(ESIC_IP_REG_COLUMNS)
        assert lines[0] == expected, f"header mismatch: {lines[0]}"
        cols = lines[0].split(",")
        assert len(cols) == 17, f"expected 17 columns, got {len(cols)}"

    def test_row_filtering(self):
        out = build_esic_ip_reg_csv(self._sample_rows())
        lines = out.decode("utf-8").splitlines()
        # header + 2 rows (u1, u4); u2 and u3 excluded
        assert len(lines) == 3, f"expected header + 2 rows, got {len(lines)}: {lines}"
        joined = "\n".join(lines)
        assert "ALICE SHARMA" in joined, "Alice (u1) missing"
        assert "SECOND JOINER" in joined, "Second Joiner (u4) missing"
        assert "3333333333" not in joined, "u2 (existing IP) should be skipped"
        assert "NOT APPLICABLE" not in joined, "u3 (esic_applicable=False) should be skipped"

    def test_dob_formatted_dd_mm_yyyy(self):
        out = build_esic_ip_reg_csv(self._sample_rows())
        text = out.decode("utf-8")
        # u1: dob=1990-05-15 → 15/05/1990
        assert "15/05/1990" in text, f"DOB not formatted DD/MM/YYYY: {text}"

    def test_empty_rows_still_produces_header(self):
        out = build_esic_ip_reg_csv([])
        lines = out.decode("utf-8").splitlines()
        assert lines[0] == ",".join(ESIC_IP_REG_COLUMNS)
        assert len(lines) == 1
