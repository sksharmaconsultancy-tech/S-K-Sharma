"""Iter-48 — Two fixes to verify:

1. Auto-punch debounce (20 minutes): rapid geofence-auto punches within 20
   minutes must be silently no-ops (`debounced: true`) and not create a new
   attendance row.
2. Super-admin retroactive edit: super_admin can approve/reject/adjust an
   already-decided (approved/rejected) punch; company_admin cannot.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio


# --------------------------------------------------------------------------- #
#  Environment
# --------------------------------------------------------------------------- #
def _load_backend_url() -> str:
    env_file = Path("/app/frontend/.env")
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("EXPO_PUBLIC_BACKEND_URL"):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            if val:
                return val.rstrip("/")
    return os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")


def _load_env(key: str, path: str = "/app/backend/.env") -> str:
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get(key, "")


BASE_URL = _load_backend_url()
MONGO_URL = _load_env("MONGO_URL")
DB_NAME = _load_env("DB_NAME")
assert BASE_URL and MONGO_URL and DB_NAME, "Missing env"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _otp_login(api, identifier: str, channel: str = "email"):
    r = api.post(f"{BASE_URL}/api/auth/otp/request",
                 json={"identifier": identifier, "channel": channel})
    assert r.status_code == 200, r.text
    code = r.json().get("dev_code") or r.json().get("code")
    r = api.post(f"{BASE_URL}/api/auth/otp/verify",
                 json={"identifier": identifier, "channel": channel, "code": code})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def sa_headers(api):
    body = _otp_login(api, SUPER_ADMIN_EMAIL)
    return {"Authorization": f"Bearer {body['session_token']}"}


def _mk_company(api, sa_headers, prefix="TEST_Iter48Co"):
    suffix = uuid.uuid4().hex[:6]
    phone = f"+91777{uuid.uuid4().int % 10_000_000:07d}"
    r = api.post(f"{BASE_URL}/api/companies", json={
        "name": f"{prefix} {suffix}",
        "address": "1 Debounce Rd",
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
    return {
        "company_id": cid,
        "headers": {"Authorization": f"Bearer {rl.json()['session_token']}"},
        "phone": phone,
        "admin_user_id": admin_user_id,
    }


@pytest.fixture
def company(api, sa_headers):
    ctx = _mk_company(api, sa_headers)
    yield ctx
    api.delete(f"{BASE_URL}/api/companies/{ctx['company_id']}", headers=sa_headers)


def _punch(api, headers, kind, source, lat=12.9, lng=77.5):
    return api.post(f"{BASE_URL}/api/attendance/punch", json={
        "kind": kind,
        "latitude": lat,
        "longitude": lng,
        "biometric_method": "fingerprint",
        "source": source,
    }, headers=headers)


def _count_today(mongo_records, user_id):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return sum(1 for r in mongo_records
               if r.get("user_id") == user_id and r.get("date") == today)


# --------------------------------------------------------------------------- #
#  Fix 1 — Auto-punch debounce (20 minutes)
# --------------------------------------------------------------------------- #
class TestAutoPunchDebounce:
    """Backend items 1-5."""

    def _fetch_today_docs(self, user_id):
        async def _run():
            client = AsyncIOMotorClient(MONGO_URL)
            db = client[DB_NAME]
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            docs = await db.attendance.find(
                {"user_id": user_id, "date": today}, {"_id": 0}
            ).to_list(500)
            client.close()
            return docs
        return asyncio.run(_run())

    def _update_at(self, record_id, minutes_ago):
        async def _run():
            client = AsyncIOMotorClient(MONGO_URL)
            db = client[DB_NAME]
            new_iso = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
            r = await db.attendance.update_one(
                {"record_id": record_id},
                {"$set": {"at": new_iso, "original_at": new_iso}},
            )
            client.close()
            return r.modified_count
        return asyncio.run(_run())

    # Item 2 — first geofence-auto IN creates a pending record, no debounce
    def test_02_first_auto_in_not_debounced(self, api, company):
        h = company["headers"]
        r = _punch(api, h, "in", "geofence-auto")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "pending", body
        assert not body.get("debounced"), body

    # Item 3 — rapid auto OUT within 20 min → debounced, no new record
    def test_03_rapid_auto_out_is_debounced(self, api, company):
        h = company["headers"]
        uid = company["admin_user_id"]

        r1 = _punch(api, h, "in", "geofence-auto")
        assert r1.status_code == 200, r1.text
        assert r1.json()["status"] == "pending"

        docs_before = self._fetch_today_docs(uid)
        count_before = len(docs_before)

        r2 = _punch(api, h, "out", "geofence-auto")
        assert r2.status_code == 200, f"expected 200 debounce, got {r2.status_code}: {r2.text}"
        body = r2.json()
        assert body.get("debounced") is True, body
        assert body.get("reason") == "auto_punch_debounce", body
        assert isinstance(body.get("cooldown_minutes_remaining"), (int, float)), body
        assert body["cooldown_minutes_remaining"] > 0, body
        assert body.get("last_punch", {}).get("kind") == "in", body

        docs_after = self._fetch_today_docs(uid)
        assert len(docs_after) == count_before, (
            f"debounce should not insert; before={count_before} after={len(docs_after)}"
        )

    # Item 4 — manual source overrides debounce (never returns debounced: true)
    def test_04_manual_never_debounced(self, api, company):
        h = company["headers"]
        r1 = _punch(api, h, "in", "geofence-auto")
        assert r1.status_code == 200

        r2 = _punch(api, h, "out", "manual")
        # Either success (200 approved) OR a business-rule 400, but NOT
        # a debounce short-circuit.
        if r2.status_code == 200:
            body = r2.json()
            assert body.get("debounced") is not True, body
        else:
            # 400 due to kind rules is acceptable; body won't have `debounced`
            assert '"debounced": true' not in r2.text.lower()

    # Item 5 — after 25 min the auto punch flows normally
    def test_05_after_25min_flows_normally(self, api, company):
        h = company["headers"]
        uid = company["admin_user_id"]

        r1 = _punch(api, h, "in", "geofence-auto")
        assert r1.status_code == 200
        rid_first = r1.json()["record_id"]

        # Age the record 25 minutes back
        mod = self._update_at(rid_first, minutes_ago=25)
        assert mod == 1

        docs_before = self._fetch_today_docs(uid)

        r2 = _punch(api, h, "out", "geofence-auto")
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert not body.get("debounced"), body
        assert body.get("status") in ("pending", "approved"), body

        docs_after = self._fetch_today_docs(uid)
        assert len(docs_after) == len(docs_before) + 1, (
            f"expected new insert; before={len(docs_before)} after={len(docs_after)}"
        )


# --------------------------------------------------------------------------- #
#  Fix 2 — Super-admin retroactive edit on decided punches
# --------------------------------------------------------------------------- #
class TestSuperAdminRetroEdit:
    """Backend items 6-10."""

    def _make_pending(self, api, headers, kind="in"):
        r = _punch(api, headers, kind, "geofence-auto")
        assert r.status_code == 200, r.text
        return r.json()["record_id"]

    # Item 6 — create pending, approve as super_admin succeeds
    # Item 7 — company_admin cannot change already-approved; super_admin can
    def test_06_07_super_admin_can_reapprove(self, api, company, sa_headers):
        h_admin = company["headers"]
        rid = self._make_pending(api, h_admin)

        # Approve as super_admin (Item 6)
        r_first = api.post(
            f"{BASE_URL}/api/attendance/punches/{rid}/decision",
            json={"action": "approve"}, headers=sa_headers,
        )
        assert r_first.status_code == 200, r_first.text
        assert r_first.json()["record"]["status"] == "approved"

        # Item 7a — company_admin gets 400 with specific phrasing
        r_ca = api.post(
            f"{BASE_URL}/api/attendance/punches/{rid}/decision",
            json={"action": "approve"}, headers=h_admin,
        )
        assert r_ca.status_code == 400, r_ca.text
        low = r_ca.text.lower()
        assert "already" in low, r_ca.text
        assert "only a super admin can change a decided punch" in low, r_ca.text

        # Item 7b — super_admin can re-approve; decision_by/at update
        old = r_first.json()["record"]
        old_decision_by = old.get("decision_by")
        old_decision_at = old.get("decision_at")

        # Re-approve as super_admin (this should always succeed even
        # though status is already approved)
        r_second = api.post(
            f"{BASE_URL}/api/attendance/punches/{rid}/decision",
            json={"action": "approve"}, headers=sa_headers,
        )
        assert r_second.status_code == 200, r_second.text
        rec = r_second.json()["record"]
        assert rec["status"] == "approved"
        assert rec.get("decision_by") == old_decision_by  # both are the super_admin here
        # decision_at should have advanced OR remained (both same second acceptable)
        assert rec.get("decision_at") >= old_decision_at, (old_decision_at, rec.get("decision_at"))

    # Item 8 — reject as super_admin without reason → 400
    # Item 9 — reject as super_admin with reason → 200 rejected
    def test_08_09_super_admin_reject_without_reason(self, api, company, sa_headers):
        h_admin = company["headers"]
        rid = self._make_pending(api, h_admin)

        # First decide it (approve) so that we test the "decided" branch
        r0 = api.post(
            f"{BASE_URL}/api/attendance/punches/{rid}/decision",
            json={"action": "approve"}, headers=sa_headers,
        )
        assert r0.status_code == 200, r0.text

        # 8 — reject with no reason
        r1 = api.post(
            f"{BASE_URL}/api/attendance/punches/{rid}/decision",
            json={"action": "reject"}, headers=sa_headers,
        )
        assert r1.status_code == 400, r1.text
        assert "reason" in r1.text.lower(), r1.text

        # 9 — reject with reason
        r2 = api.post(
            f"{BASE_URL}/api/attendance/punches/{rid}/decision",
            json={"action": "reject", "reason": "Off-site override"},
            headers=sa_headers,
        )
        assert r2.status_code == 200, r2.text
        rec = r2.json()["record"]
        assert rec["status"] == "rejected", rec
        assert rec["decision_reason"] == "Off-site override"

    # Item 10 — adjust as super_admin without adjusted_time → 400; with → 200
    def test_10_super_admin_adjust(self, api, company, sa_headers):
        h_admin = company["headers"]
        rid = self._make_pending(api, h_admin)

        # Decide it first (approve) so it's already decided
        r0 = api.post(
            f"{BASE_URL}/api/attendance/punches/{rid}/decision",
            json={"action": "approve"}, headers=sa_headers,
        )
        assert r0.status_code == 200

        # Adjust with no time
        r1 = api.post(
            f"{BASE_URL}/api/attendance/punches/{rid}/decision",
            json={"action": "adjust"}, headers=sa_headers,
        )
        assert r1.status_code == 400, r1.text

        # Adjust with valid time
        r2 = api.post(
            f"{BASE_URL}/api/attendance/punches/{rid}/decision",
            json={"action": "adjust", "adjusted_time": "10:30"},
            headers=sa_headers,
        )
        assert r2.status_code == 200, r2.text
        rec = r2.json()["record"]
        assert rec.get("adjusted_at"), rec
        assert "T10:30:00" in rec["adjusted_at"], rec["adjusted_at"]
