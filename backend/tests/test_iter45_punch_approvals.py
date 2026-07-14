"""Iter-45 — Attendance approval process (Approve / Reject / Adjust).

Covers items 1-14 of the review request.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests


def _load_backend_url() -> str:
    env_file = Path("/app/frontend/.env")
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("EXPO_PUBLIC_BACKEND_URL"):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            if val:
                return val.rstrip("/")
    return os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")


BASE_URL = _load_backend_url()
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL missing"
SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"


# ---------------- fixtures ---------------- #
@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def sa_headers(api):
    r = api.post(f"{BASE_URL}/api/auth/otp/request",
                 json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email"})
    assert r.status_code == 200, r.text
    code = r.json().get("dev_code") or r.json().get("code")
    r = api.post(f"{BASE_URL}/api/auth/otp/verify",
                 json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email", "code": code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['session_token']}"}


def _mk_company(api, sa_headers, name_prefix="TEST_ApprovalCo"):
    suffix = uuid.uuid4().hex[:6]
    phone = f"+91777{uuid.uuid4().int % 10_000_000:07d}"
    r = api.post(f"{BASE_URL}/api/companies", json={
        "name": f"{name_prefix} {suffix}",
        "address": "1 Approval Rd",
        "office_lat": 12.9,
        "office_lng": 77.5,
        "geofence_radius_m": 500,
        "compliance_enabled": True,
        "business_category": "industry",
        "business_subcategory": "Textile",
        "admin_phone": phone,
        "admin_name": "QA Admin",
    }, headers=sa_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    cid = body["company_id"]
    temp_pin = body["admin"]["temp_pin"]
    admin_user_id = body["admin"]["user_id"]

    rl = api.post(f"{BASE_URL}/api/auth/admin-pin-login",
                  json={"identifier": phone, "pin": temp_pin})
    assert rl.status_code == 200, rl.text
    headers = {"Authorization": f"Bearer {rl.json()['session_token']}"}
    return {"company_id": cid, "headers": headers, "phone": phone,
            "admin_user_id": admin_user_id}


@pytest.fixture
def company_a(api, sa_headers):
    ctx = _mk_company(api, sa_headers, "TEST_ApprovalCoA")
    yield ctx
    api.delete(f"{BASE_URL}/api/companies/{ctx['company_id']}", headers=sa_headers)


@pytest.fixture
def company_b(api, sa_headers):
    ctx = _mk_company(api, sa_headers, "TEST_ApprovalCoB")
    yield ctx
    api.delete(f"{BASE_URL}/api/companies/{ctx['company_id']}", headers=sa_headers)


# Small helper — hit /attendance/punch as the admin themselves (self-punch works
# since admin is also a user).
def _punch(api, headers, kind, source, lat=12.9, lng=77.5):
    r = api.post(f"{BASE_URL}/api/attendance/punch", json={
        "kind": kind,
        "latitude": lat,
        "longitude": lng,
        "biometric_method": "fingerprint",
        "source": source,
    }, headers=headers)
    return r


# ============================================================================
#  1-2: punch source drives approval status
# ============================================================================
class TestPunchStatusOnCreate:

    def test_auto_source_creates_pending(self, api, company_a):
        h = company_a["headers"]
        r = _punch(api, h, "in", "geofence-auto")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "pending", body
        assert body["approval_required"] is True, body

        # DB / GET verification via pending-punches
        rid = body["record_id"]
        pr = api.get(f"{BASE_URL}/api/attendance/pending-punches", headers=h)
        assert pr.status_code == 200
        recs = pr.json()["records"]
        match = next((x for x in recs if x["record_id"] == rid), None)
        assert match, f"record {rid} not in pending list"
        assert match["status"] == "pending"
        assert match["original_at"] == match["at"]

    def test_manual_source_creates_approved(self, api, company_a):
        h = company_a["headers"]
        r = _punch(api, h, "in", "manual")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "approved", body
        assert body["approval_required"] is False, body


# ============================================================================
#  3-4: list pending / include decided
# ============================================================================
class TestPendingList:

    def test_pending_returns_only_pending_by_default(self, api, company_a):
        h = company_a["headers"]
        _punch(api, h, "in", "geofence-auto")   # pending
        _punch(api, h, "out", "manual")         # approved (excluded)
        r = api.get(f"{BASE_URL}/api/attendance/pending-punches", headers=h)
        assert r.status_code == 200
        recs = r.json()["records"]
        assert recs, "expected at least one pending record"
        for x in recs:
            assert x["status"] == "pending"
        # Each row has employee mini-object
        first = recs[0]
        assert "employee" in first
        assert first["employee"]["name"], first["employee"]

    def test_include_decided_returns_all(self, api, company_a):
        h = company_a["headers"]
        _punch(api, h, "in", "geofence-auto")  # pending
        _punch(api, h, "out", "manual")        # approved
        r = api.get(f"{BASE_URL}/api/attendance/pending-punches?include_decided=true", headers=h)
        assert r.status_code == 200
        recs = r.json()["records"]
        statuses = {x["status"] for x in recs}
        assert "pending" in statuses, statuses
        assert "approved" in statuses, statuses


# ============================================================================
#  5-12: decision endpoint
# ============================================================================
class TestDecideEndpoint:

    def _new_pending(self, api, h, kind="in"):
        r = _punch(api, h, kind, "geofence-auto")
        assert r.status_code == 200
        return r.json()["record_id"]

    def test_approve_sets_approved(self, api, company_a):
        h = company_a["headers"]
        rid = self._new_pending(api, h)
        r = api.post(f"{BASE_URL}/api/attendance/punches/{rid}/decision",
                     json={"action": "approve"}, headers=h)
        assert r.status_code == 200, r.text
        rec = r.json()["record"]
        assert rec["status"] == "approved"
        assert rec.get("decision_by") == company_a["admin_user_id"]
        assert rec.get("decision_at")

    def test_reject_without_reason_400(self, api, company_a):
        h = company_a["headers"]
        rid = self._new_pending(api, h)
        r = api.post(f"{BASE_URL}/api/attendance/punches/{rid}/decision",
                     json={"action": "reject"}, headers=h)
        assert r.status_code == 400, r.text
        assert "reason" in r.text.lower()

    def test_reject_with_reason_ok(self, api, company_a):
        h = company_a["headers"]
        rid = self._new_pending(api, h)
        r = api.post(f"{BASE_URL}/api/attendance/punches/{rid}/decision",
                     json={"action": "reject", "reason": "Not on-site"}, headers=h)
        assert r.status_code == 200, r.text
        rec = r.json()["record"]
        assert rec["status"] == "rejected"
        assert rec["decision_reason"] == "Not on-site"

    def test_adjust_missing_time_400(self, api, company_a):
        h = company_a["headers"]
        rid = self._new_pending(api, h)
        r = api.post(f"{BASE_URL}/api/attendance/punches/{rid}/decision",
                     json={"action": "adjust"}, headers=h)
        assert r.status_code == 400, r.text

    def test_adjust_valid_hhmm(self, api, company_a):
        h = company_a["headers"]
        rid = self._new_pending(api, h)
        r = api.post(f"{BASE_URL}/api/attendance/punches/{rid}/decision",
                     json={"action": "adjust", "adjusted_time": "09:15"}, headers=h)
        assert r.status_code == 200, r.text
        rec = r.json()["record"]
        assert rec["status"] == "approved"
        assert rec.get("adjusted_at"), rec
        # HH:MM 09:15 rendered against the record's date, ends in T09:15:00
        assert "T09:15:00" in rec["adjusted_at"], rec["adjusted_at"]
        assert rec["decision_reason"] == "Time adjusted by admin"

    def test_adjust_invalid_hhmm_400(self, api, company_a):
        h = company_a["headers"]
        rid = self._new_pending(api, h)
        r = api.post(f"{BASE_URL}/api/attendance/punches/{rid}/decision",
                     json={"action": "adjust", "adjusted_time": "25:00"}, headers=h)
        assert r.status_code == 400, r.text

    def test_retry_after_decided_400(self, api, company_a):
        h = company_a["headers"]
        rid = self._new_pending(api, h)
        r1 = api.post(f"{BASE_URL}/api/attendance/punches/{rid}/decision",
                      json={"action": "approve"}, headers=h)
        assert r1.status_code == 200
        r2 = api.post(f"{BASE_URL}/api/attendance/punches/{rid}/decision",
                      json={"action": "approve"}, headers=h)
        assert r2.status_code == 400, r2.text
        assert "already" in r2.text.lower()

    def test_cross_company_forbidden(self, api, company_a, company_b):
        # Punch made by company A admin, decided by company B admin → 403
        r = _punch(api, company_a["headers"], "in", "geofence-auto")
        assert r.status_code == 200
        rid = r.json()["record_id"]
        r2 = api.post(f"{BASE_URL}/api/attendance/punches/{rid}/decision",
                      json={"action": "approve"}, headers=company_b["headers"])
        assert r2.status_code == 403, r2.text


# ============================================================================
#  13: policy toggle
# ============================================================================
class TestPolicyToggle:

    def test_get_policy_includes_flag_default_true(self, api, company_a):
        h = company_a["headers"]
        r = api.get(f"{BASE_URL}/api/attendance/policy", headers=h)
        assert r.status_code == 200
        pol = r.json()["policy"]
        assert pol.get("punch_approval_required") is True, pol

    def test_patch_disables_and_new_auto_punch_is_approved(self, api, company_a):
        h = company_a["headers"]
        cur = api.get(f"{BASE_URL}/api/attendance/policy", headers=h).json()["policy"]
        cur["punch_approval_required"] = False
        rp = api.patch(f"{BASE_URL}/api/attendance/policy",
                       json={"policy": cur}, headers=h)
        assert rp.status_code == 200, rp.text
        pol_after = rp.json()["policy"]
        assert pol_after.get("punch_approval_required") is False, pol_after

        # Now an auto-source punch should be approved directly
        r = _punch(api, h, "in", "geofence-auto")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "approved", body
        assert body["approval_required"] is False, body


# ============================================================================
#  14: _compute_day_hours regression via /attendance/summary
# ============================================================================
class TestComputeDayHoursRegression:
    """Insert attendance docs directly? We only have HTTP — use the admin's own
    punches (they count against admin's own summary). Trick: use manual (approved)
    for IN 09:00 + OUT 18:00 and geofence-auto for the 20:00 pending IN."""

    def _iso_today(self, hh, mm=0):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{today}T{hh:02d}:{mm:02d}:00+00:00"

    def test_pending_excluded_and_adjusted_used(self, api, company_a):
        h = company_a["headers"]
        # 3 punches — but we cannot set the `at` via API. Instead insert
        # via the punch endpoint (real-time) and then use the ADJUST flow
        # to control effective times.

        # 1. First IN — we'll adjust to 09:00
        r_in = _punch(api, h, "in", "geofence-auto")
        assert r_in.status_code == 200
        rid_in = r_in.json()["record_id"]
        ra = api.post(f"{BASE_URL}/api/attendance/punches/{rid_in}/decision",
                      json={"action": "adjust", "adjusted_time": "09:00"}, headers=h)
        assert ra.status_code == 200

        # 2. First OUT — we'll adjust to 18:00
        r_out = _punch(api, h, "out", "geofence-auto")
        assert r_out.status_code == 200
        rid_out = r_out.json()["record_id"]
        ra2 = api.post(f"{BASE_URL}/api/attendance/punches/{rid_out}/decision",
                       json={"action": "adjust", "adjusted_time": "18:00"}, headers=h)
        assert ra2.status_code == 200

        # 3. Extra pending IN (should be excluded)
        r_extra = _punch(api, h, "in", "geofence-auto")
        assert r_extra.status_code == 200

        # /attendance/summary — days=1 today only
        rs = api.get(f"{BASE_URL}/api/attendance/summary?days=1", headers=h)
        assert rs.status_code == 200, rs.text
        body = rs.json()
        days = body.get("days") or body.get("daily") or []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = next((d for d in days if d.get("date") == today), None)
        assert row, f"today row missing: {body}"
        assert row["hours"] == 9.0, row  # 09:00 -> 18:00 = 9h, pending excluded

        # Now adjust the OUT to 17:30 → hours should become 8.5
        # But it's already decided (approved via adjust). We can't re-decide.
        # Instead create a fresh scenario in a NEW company (isolated).
        # Skipping - covered separately below in test_adjusted_at_reduces_hours

    def test_adjusted_out_reduces_hours_to_8_5(self, api, company_b):
        """Fresh company_b scenario: IN adjusted 09:00, OUT adjusted 17:30 → 8.5h."""
        h = company_b["headers"]
        # IN
        r_in = _punch(api, h, "in", "geofence-auto")
        assert r_in.status_code == 200
        rid_in = r_in.json()["record_id"]
        ra = api.post(f"{BASE_URL}/api/attendance/punches/{rid_in}/decision",
                      json={"action": "adjust", "adjusted_time": "09:00"}, headers=h)
        assert ra.status_code == 200
        # OUT — adjust to 17:30
        r_out = _punch(api, h, "out", "geofence-auto")
        assert r_out.status_code == 200
        rid_out = r_out.json()["record_id"]
        ra2 = api.post(f"{BASE_URL}/api/attendance/punches/{rid_out}/decision",
                       json={"action": "adjust", "adjusted_time": "17:30"}, headers=h)
        assert ra2.status_code == 200
        rs = api.get(f"{BASE_URL}/api/attendance/summary?days=1", headers=h)
        assert rs.status_code == 200
        days = rs.json()["days"]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = next((d for d in days if d.get("date") == today), None)
        assert row and row["hours"] == 8.5, row
