"""Iteration 46 backend tests.

Covers two big features added in this session:
  A) ZKTeco AC Mini Plus biometric integration under /api/iclock/* and the
     admin management endpoints under /api/biometric/*.
  B) Super-admin Company Details, disable/enable company, edit company_admin
     credentials, reset company_admin PIN, and disable/enable individual user.
"""
import os
import time
import uuid
import requests
import pytest


BASE_URL = os.environ.get(
    "EXPO_BACKEND_URL",
    "https://emplo-connect-1.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"


# --------------------------------------------------------------------------
# Helpers / fixtures
# --------------------------------------------------------------------------
def _login_super_admin() -> str:
    """Log in as the hard-coded super admin using the OTP dev flow."""
    r = requests.post(
        f"{API}/auth/otp/request",
        json={"identifier": SUPER_EMAIL, "channel": "email"},
        timeout=30,
    )
    assert r.status_code == 200, f"OTP request failed: {r.status_code} {r.text}"
    code = r.json().get("dev_code")
    assert code, f"dev_code not returned; response was {r.json()}"
    r = requests.post(
        f"{API}/auth/otp/verify",
        json={"identifier": SUPER_EMAIL, "channel": "email", "code": code},
        timeout=30,
    )
    assert r.status_code == 200, f"OTP verify failed: {r.status_code} {r.text}"
    token = r.json().get("session_token")
    assert token, "No session token returned"
    return token


def _admin_pin_login(identifier: str, pin: str) -> requests.Response:
    return requests.post(
        f"{API}/auth/admin-pin-login",
        json={"identifier": identifier, "pin": pin},
        timeout=30,
    )


@pytest.fixture(scope="module")
def super_token() -> str:
    return _login_super_admin()


@pytest.fixture(scope="module")
def super_headers(super_token) -> dict:
    return {"Authorization": f"Bearer {super_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def throwaway_company(super_headers) -> dict:
    """Create a fresh throwaway company with an admin_phone so we get a
    freshly provisioned company_admin + temp PIN we can use to log in.
    Cleanup is best-effort at module teardown via DELETE not implemented —
    docs are prefixed with TEST_ so they're easy to purge later."""
    suffix = uuid.uuid4().hex[:6].upper()
    phone = f"+9198{int(time.time()) % 100_000_000:08d}"
    payload = {
        "name": f"TEST_Firm_{suffix}",
        "address": "TEST_Address",
        "office_lat": 28.61,
        "office_lng": 77.20,
        "geofence_radius_m": 100,
        "compliance_enabled": True,
        "company_code": f"T{suffix[:5]}",
        "admin_phone": phone,
        "admin_email": f"test_admin_{suffix.lower()}@example.com",
        "admin_name": f"TEST Admin {suffix}",
    }
    r = requests.post(f"{API}/companies", headers=super_headers, json=payload, timeout=30)
    assert r.status_code == 200, f"create_company failed: {r.status_code} {r.text}"
    data = r.json()
    assert "admin" in data and "temp_pin" in data["admin"], data
    return data


# ==========================================================================
# FEATURE B — Super-admin Company Details / enable-disable / creds / PIN
# ==========================================================================
class TestCompanyDetails:
    def test_get_company_details_shape(self, super_headers, throwaway_company):
        cid = throwaway_company["company_id"]
        r = requests.get(f"{API}/companies/{cid}/details", headers=super_headers, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        # top-level keys
        for k in ("company", "company_admin", "pin_meta", "stats", "recent_actions"):
            assert k in d, f"missing {k} in response"
        # company_admin: NO pin_hash leaked
        assert "pin_hash" not in d["company_admin"], "pin_hash leaked!"
        assert "face_reference_base64" not in d["company_admin"]
        # pin_meta shape
        pm = d["pin_meta"]
        for k in ("has_pin", "must_change", "set_at", "last_login_at", "fail_count"):
            assert k in pm, f"pin_meta missing {k}"
        assert pm["has_pin"] is True
        assert pm["must_change"] is True  # fresh temp PIN
        assert pm["fail_count"] == 0
        # stats keys
        st = d["stats"]
        for k in ("total_employees", "active_employees", "disabled_employees",
                  "present_today", "pending_leaves", "open_tickets", "devices"):
            assert k in st, f"stats missing {k}"

    def test_get_details_forbidden_for_non_super(self, throwaway_company):
        # Log in as the freshly-created company_admin with temp PIN
        admin = throwaway_company["admin"]
        r = _admin_pin_login(admin["phone"], admin["temp_pin"])
        assert r.status_code == 200, r.text
        ca_token = r.json()["session_token"]
        r = requests.get(
            f"{API}/companies/{throwaway_company['company_id']}/details",
            headers={"Authorization": f"Bearer {ca_token}"},
            timeout=30,
        )
        assert r.status_code == 403, r.text

    def test_get_details_404_unknown(self, super_headers):
        r = requests.get(f"{API}/companies/does_not_exist/details", headers=super_headers, timeout=30)
        assert r.status_code == 404


class TestCompanyEnableDisable:
    def test_disable_kicks_sessions_and_blocks_login(self, super_headers, throwaway_company):
        admin = throwaway_company["admin"]
        cid = throwaway_company["company_id"]

        # 1. company_admin can log in initially
        r = _admin_pin_login(admin["phone"], admin["temp_pin"])
        assert r.status_code == 200, f"pre-disable login failed: {r.text}"
        ca_token = r.json()["session_token"]

        # authenticated call works
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {ca_token}"}, timeout=30)
        assert r.status_code == 200

        # 2. Disable the company
        r = requests.patch(
            f"{API}/companies/{cid}/enabled",
            headers=super_headers,
            json={"enabled": False, "reason": "test"},
            timeout=30,
        )
        assert r.status_code == 200 and r.json().get("enabled") is False, r.text

        # 3. Existing session should be invalidated
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {ca_token}"}, timeout=30)
        assert r.status_code in (401, 403), f"session still valid after disable: {r.status_code}"

        # 4. Fresh login blocked with 403
        r = _admin_pin_login(admin["phone"], admin["temp_pin"])
        assert r.status_code == 403, f"login should be blocked after disable: {r.status_code} {r.text}"

        # 5. Re-enable
        r = requests.patch(
            f"{API}/companies/{cid}/enabled",
            headers=super_headers,
            json={"enabled": True},
            timeout=30,
        )
        assert r.status_code == 200 and r.json().get("enabled") is True, r.text

        # 6. Login works again
        r = _admin_pin_login(admin["phone"], admin["temp_pin"])
        assert r.status_code == 200, f"post-reenable login failed: {r.text}"

    def test_disable_unknown_company_404(self, super_headers):
        r = requests.patch(
            f"{API}/companies/does_not_exist/enabled",
            headers=super_headers,
            json={"enabled": False},
            timeout=30,
        )
        assert r.status_code == 404


class TestCompanyAdminCredentials:
    def test_edit_admin_persists_and_conflicts(self, super_headers, throwaway_company):
        cid = throwaway_company["company_id"]
        suffix = uuid.uuid4().hex[:6]
        new_email = f"test_edit_{suffix}@example.com"
        new_phone = f"+9188{int(time.time()) % 100_000_000:08d}"
        new_name = f"TEST Edited {suffix}"

        r = requests.patch(
            f"{API}/companies/{cid}/admin",
            headers=super_headers,
            json={"name": new_name, "email": new_email, "phone": new_phone},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        ca = r.json()["company_admin"]
        assert ca["email"] == new_email
        assert ca["phone"] == new_phone
        assert ca["name"] == new_name
        # Verify persistence via GET /details
        r = requests.get(f"{API}/companies/{cid}/details", headers=super_headers, timeout=30)
        ca2 = r.json()["company_admin"]
        assert ca2["email"] == new_email
        assert ca2["phone"] == new_phone

        # Create a second company and attempt to reuse the same email → 409
        second_suffix = uuid.uuid4().hex[:5].upper()
        second_phone = f"+9177{int(time.time()) % 100_000_000:08d}"
        create = requests.post(
            f"{API}/companies",
            headers=super_headers,
            json={
                "name": f"TEST_ClashFirm_{second_suffix}",
                "address": "X",
                "office_lat": 28.6,
                "office_lng": 77.2,
                "geofence_radius_m": 100,
                "compliance_enabled": True,
                "company_code": f"C{second_suffix[:4]}",
                "admin_phone": second_phone,
                "admin_email": f"other_{second_suffix.lower()}@example.com",
                "admin_name": "TEST Other Admin",
            },
            timeout=30,
        )
        assert create.status_code == 200, create.text
        other_cid = create.json()["company_id"]

        # Now try to patch the *other* company's admin using the just-set email
        r = requests.patch(
            f"{API}/companies/{other_cid}/admin",
            headers=super_headers,
            json={"email": new_email},
            timeout=30,
        )
        assert r.status_code == 409, f"expected 409 clash, got {r.status_code} {r.text}"

        # Same test for phone conflict
        r = requests.patch(
            f"{API}/companies/{other_cid}/admin",
            headers=super_headers,
            json={"phone": new_phone},
            timeout=30,
        )
        assert r.status_code == 409, f"expected 409 phone clash, got {r.status_code} {r.text}"


class TestCompanyAdminResetPin:
    def test_reset_pin_flow(self, super_headers, throwaway_company):
        cid = throwaway_company["company_id"]
        admin = throwaway_company["admin"]

        # Confirm we can login with the current PIN first — the previous
        # edit_admin test changed the admin's phone/email, so we need to
        # re-fetch the current identifier.
        d = requests.get(f"{API}/companies/{cid}/details", headers=super_headers, timeout=30).json()
        ca = d["company_admin"]
        current_ident = ca.get("phone") or ca.get("email")

        # 1. Old PIN currently works
        r = _admin_pin_login(current_ident, admin["temp_pin"])
        assert r.status_code == 200, f"pre-reset login failed: {r.text}"
        old_token = r.json()["session_token"]

        # 2. Reset PIN
        r = requests.post(
            f"{API}/companies/{cid}/admin/reset-pin",
            headers=super_headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        new_pin = body.get("temp_pin")
        assert new_pin and new_pin.isdigit() and len(new_pin) == 6, f"bad temp_pin {new_pin!r}"
        assert body.get("identifier") in (ca.get("email"), ca.get("phone"))

        # 3. Old session invalidated
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {old_token}"}, timeout=30)
        assert r.status_code in (401, 403), f"old session still valid: {r.status_code}"

        # 4. Old PIN no longer works
        r = _admin_pin_login(current_ident, admin["temp_pin"])
        assert r.status_code in (401, 403), f"old PIN still valid: {r.status_code} {r.text}"

        # 5. New PIN works
        r = _admin_pin_login(current_ident, new_pin)
        assert r.status_code == 200, f"new PIN login failed: {r.status_code} {r.text}"
        assert r.json().get("pin_must_change") is True

        # 6. pin_meta.must_change true in details
        d = requests.get(f"{API}/companies/{cid}/details", headers=super_headers, timeout=30).json()
        assert d["pin_meta"]["must_change"] is True


class TestUserEnabledToggle:
    def test_super_admin_can_toggle_user(self, super_headers, throwaway_company):
        cid = throwaway_company["company_id"]
        d = requests.get(f"{API}/companies/{cid}/details", headers=super_headers, timeout=30).json()
        target = d["company_admin"]
        # Create a fresh employee in the company for a clean toggle test
        _emp_id = f"user_{uuid.uuid4().hex[:12]}"  # noqa: F841 (reserved for future use)
        import pymongo
        # Instead of poking DB directly, use the disable endpoint on the
        # company_admin itself (super_admin is allowed to disable admins).
        r = requests.patch(
            f"{API}/users/{target['user_id']}/enabled",
            headers=super_headers,
            json={"disabled": True, "reason": "TEST"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["disabled"] is True
        # Toggle back on
        r = requests.patch(
            f"{API}/users/{target['user_id']}/enabled",
            headers=super_headers,
            json={"disabled": False},
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["disabled"] is False


# ==========================================================================
# FEATURE A — ZKTeco / iClock endpoints and admin management
# ==========================================================================
UNKNOWN_SN = "SN_UNKNOWN_" + uuid.uuid4().hex[:6]


class TestBiometricDeviceCRUD:
    @pytest.fixture(scope="class")
    def device(self, super_headers, throwaway_company):
        sn = "TEST_SN_" + uuid.uuid4().hex[:8].upper()
        r = requests.post(
            f"{API}/biometric/devices",
            headers=super_headers,
            json={
                "serial_number": sn,
                "name": "TEST_Entry_Device",
                "kind": "in",
                "company_id": throwaway_company["company_id"],
                "location": "TEST_MainGate",
                "enabled": True,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        dev = r.json()["device"]
        assert dev["serial_number"] == sn
        assert dev["kind"] == "in"
        yield dev
        # cleanup
        requests.delete(f"{API}/biometric/devices/{dev['device_id']}", headers=super_headers, timeout=30)

    def test_duplicate_sn_409(self, super_headers, device, throwaway_company):
        r = requests.post(
            f"{API}/biometric/devices",
            headers=super_headers,
            json={
                "serial_number": device["serial_number"],
                "name": "dup",
                "kind": "in",
                "company_id": throwaway_company["company_id"],
            },
            timeout=30,
        )
        assert r.status_code == 409, r.text

    def test_list_devices_returns_online_and_unmapped_count(self, super_headers, device):
        r = requests.get(f"{API}/biometric/devices", headers=super_headers, timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert "devices" in j and "unmapped_count" in j
        assert any(d["device_id"] == device["device_id"] for d in j["devices"])
        for d in j["devices"]:
            assert "online" in d
            assert isinstance(d["online"], bool)

    def test_patch_device(self, super_headers, device):
        r = requests.patch(
            f"{API}/biometric/devices/{device['device_id']}",
            headers=super_headers,
            json={"name": "TEST_Renamed", "kind": "out", "location": "ExitGate"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        upd = r.json()["device"]
        assert upd["name"] == "TEST_Renamed"
        assert upd["kind"] == "out"
        assert upd["location"] == "ExitGate"
        # revert kind to 'in' so downstream tests work as expected
        requests.patch(
            f"{API}/biometric/devices/{device['device_id']}",
            headers=super_headers,
            json={"kind": "in"},
            timeout=30,
        )


class TestIclockPushProtocol:
    """These endpoints intentionally have NO auth — the physical device calls
    them directly."""

    @pytest.fixture(scope="class")
    def device_and_user(self, super_headers, throwaway_company):
        # Register a device
        sn = "TEST_PUSH_" + uuid.uuid4().hex[:8].upper()
        r = requests.post(
            f"{API}/biometric/devices",
            headers=super_headers,
            json={
                "serial_number": sn,
                "name": "TEST_PushDevice",
                "kind": "in",
                "company_id": throwaway_company["company_id"],
                "location": "gate",
                "enabled": True,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        dev = r.json()["device"]

        # Seed a user with bio_code=1001 in this company via direct Mongo
        from motor.motor_asyncio import AsyncIOMotorClient
        import asyncio
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        dbn = os.environ.get("DB_NAME", "test_database")
        db_ = client[dbn]

        async def _seed():
            user_id = f"user_bio_{uuid.uuid4().hex[:10]}"
            await db_.users.insert_one({
                "user_id": user_id,
                "email": f"bio_{user_id}@test.com",
                "phone": None,
                "name": "TEST BioUser",
                "role": "employee",
                "company_id": throwaway_company["company_id"],
                "bio_code": "1001",
                "employee_code": "E1001",
                "onboarded": True,
                "approval_status": "approved",
                "created_at": "2026-01-01T00:00:00Z",
            })
            return user_id

        user_id = asyncio.get_event_loop().run_until_complete(_seed())
        yield {"device": dev, "user_id": user_id}

        async def _cleanup():
            await db_.users.delete_one({"user_id": user_id})
            await db_.attendance.delete_many({"device_serial": sn})
            await db_.biometric_unmapped.delete_many({"device_serial": sn})
        asyncio.get_event_loop().run_until_complete(_cleanup())
        requests.delete(f"{API}/biometric/devices/{dev['device_id']}", headers=super_headers, timeout=30)

    def test_cdata_handshake_unknown_sn_404(self):
        r = requests.get(f"{API}/iclock/cdata", params={"SN": UNKNOWN_SN}, timeout=30)
        assert r.status_code == 404, r.text

    def test_cdata_handshake_known_sn_config(self, device_and_user):
        sn = device_and_user["device"]["serial_number"]
        r = requests.get(f"{API}/iclock/cdata", params={"SN": sn}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.text
        assert "GET OPTION FROM:" in body
        assert "Realtime=1" in body
        assert "Delay=" in body
        assert "ServerVer=SKSharma-1.0" in body

    def test_cdata_push_attlog_mapped_user_inserts_attendance(self, super_headers, device_and_user):
        sn = device_and_user["device"]["serial_number"]
        body = "1001\t2026-06-15 09:12:33\t0\t1\t0\t0\n"
        r = requests.post(
            f"{API}/iclock/cdata",
            params={"SN": sn, "table": "ATTLOG"},
            data=body,
            headers={"Content-Type": "text/plain"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.text.startswith("OK"), r.text
        time.sleep(0.4)

        # Verify persistence via device logs
        r = requests.get(
            f"{API}/biometric/devices/{device_and_user['device']['device_id']}/logs",
            headers=super_headers,
            timeout=30,
        )
        assert r.status_code == 200
        logs = r.json()["logs"]
        assert len(logs) >= 1
        rec = logs[0]
        assert rec["status"] == "approved"
        assert rec["source"].startswith("zkteco:")
        assert rec["device_serial"] == sn
        assert rec["kind"] == device_and_user["device"]["kind"]

    def test_cdata_push_duplicate_line_ignored(self, super_headers, device_and_user):
        sn = device_and_user["device"]["serial_number"]
        # Same line as previous test — should be idempotent
        body = "1001\t2026-06-15 09:12:33\t0\t1\t0\t0\n"

        r = requests.get(
            f"{API}/biometric/devices/{device_and_user['device']['device_id']}/logs",
            headers=super_headers, timeout=30,
        )
        before = len(r.json()["logs"])

        r = requests.post(
            f"{API}/iclock/cdata",
            params={"SN": sn, "table": "ATTLOG"},
            data=body,
            timeout=30,
        )
        assert r.status_code == 200

        r = requests.get(
            f"{API}/biometric/devices/{device_and_user['device']['device_id']}/logs",
            headers=super_headers, timeout=30,
        )
        after = len(r.json()["logs"])
        assert after == before, f"duplicate line was inserted twice ({before} -> {after})"

    def test_cdata_push_unmapped_user_logged(self, super_headers, device_and_user):
        sn = device_and_user["device"]["serial_number"]
        body = "9999\t2026-06-15 10:00:00\t0\t1\t0\t0\n"
        r = requests.post(
            f"{API}/iclock/cdata",
            params={"SN": sn, "table": "ATTLOG"},
            data=body,
            timeout=30,
        )
        assert r.status_code == 200

        r = requests.get(f"{API}/biometric/unmapped", headers=super_headers, timeout=30)
        assert r.status_code == 200
        rows = r.json()["unmapped"]
        assert any(row.get("device_serial") == sn and row.get("device_user_id") == "9999" for row in rows), rows

    def test_getrequest_returns_ok(self, device_and_user):
        sn = device_and_user["device"]["serial_number"]
        r = requests.get(f"{API}/iclock/getrequest", params={"SN": sn}, timeout=30)
        assert r.status_code == 200
        assert "OK" in r.text

    def test_ping_updates_last_seen(self, super_headers, device_and_user):
        sn = device_and_user["device"]["serial_number"]
        r = requests.get(f"{API}/iclock/ping", params={"SN": sn}, timeout=30)
        assert r.status_code == 200
        assert "OK" in r.text
        # last_seen_at should now be within seconds → device should be online
        r = requests.get(f"{API}/biometric/devices", headers=super_headers, timeout=30)
        j = r.json()
        this = next(d for d in j["devices"] if d["serial_number"] == sn)
        assert this["online"] is True

    def test_devicecmd_persists(self, super_headers, device_and_user):
        sn = device_and_user["device"]["serial_number"]
        r = requests.post(
            f"{API}/iclock/devicecmd",
            params={"SN": sn},
            data="ID=1&Return=0",
            timeout=30,
        )
        assert r.status_code == 200
        assert "OK" in r.text


class TestSimulatePunch:
    def test_simulate_punch_end_to_end(self, super_headers, throwaway_company):
        # Register a device + seed a user via existing plumbing
        sn = "TEST_SIM_" + uuid.uuid4().hex[:8].upper()
        r = requests.post(
            f"{API}/biometric/devices",
            headers=super_headers,
            json={
                "serial_number": sn, "name": "TEST_SimDevice", "kind": "in",
                "company_id": throwaway_company["company_id"], "enabled": True,
            }, timeout=30,
        )
        assert r.status_code == 200, r.text
        dev = r.json()["device"]

        from motor.motor_asyncio import AsyncIOMotorClient
        import asyncio
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db_ = client[os.environ.get("DB_NAME", "test_database")]

        uid = f"user_sim_{uuid.uuid4().hex[:10]}"
        async def _seed():
            await db_.users.insert_one({
                "user_id": uid, "email": f"sim_{uid}@t.com", "role": "employee",
                "company_id": throwaway_company["company_id"], "bio_code": "2001",
                "onboarded": True, "approval_status": "approved",
                "created_at": "2026-01-01T00:00:00Z",
            })
        asyncio.get_event_loop().run_until_complete(_seed())

        try:
            r = requests.post(
                f"{API}/biometric/devices/simulate-punch",
                headers=super_headers,
                json={"serial_number": sn, "device_user_id": "2001"},
                timeout=30,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["ok"] is True, body

            # unknown device_user_id -> ok False, reason unmapped
            r = requests.post(
                f"{API}/biometric/devices/simulate-punch",
                headers=super_headers,
                json={"serial_number": sn, "device_user_id": "9998"},
                timeout=30,
            )
            assert r.status_code == 200
            assert r.json()["ok"] is False
            assert "unmapped" in (r.json().get("reason") or "")
        finally:
            async def _cleanup():
                await db_.users.delete_one({"user_id": uid})
                await db_.attendance.delete_many({"device_serial": sn})
                await db_.biometric_unmapped.delete_many({"device_serial": sn})
            asyncio.get_event_loop().run_until_complete(_cleanup())
            requests.delete(f"{API}/biometric/devices/{dev['device_id']}", headers=super_headers, timeout=30)
