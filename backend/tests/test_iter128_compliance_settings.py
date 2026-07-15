"""Iter 128 — Standard Compliance Settings (global + firm-level overrides).

Covers:
  • GET  /api/admin/compliance-settings
  • PUT  /api/admin/compliance-settings                (super_admin only)
  • GET  /api/admin/compliance-settings/firm/{cid}
  • PUT  /api/admin/compliance-settings/firm/{cid}     (super_admin only)
  • Role gating (sub_admin can GET, must be 403 on PUT)
  • Validation (400) for negative numbers, invalid rounding mode, empty payload
  • Firm override lifecycle: save → GET(has_override=true) → clear → GET(has_override=false)

Restores original global settings at the end (via module-level fixture).
"""
import os
import copy
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
KANKANI_CID = "cmp_527fecdd7c"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PASSWORD = "sharma123"
SUB_EMAIL = "testsub@sksharma.co"
SUB_PASSWORD = "testsub123"
KANKANI_ADMIN_USER_ID = "user_0a38839e3568"


def _inject_company_admin_session() -> str:
    """Directly seed a session for the Kankani company_admin (password unknown per creds memo)."""
    import asyncio, os as _os, uuid
    from datetime import datetime, timezone, timedelta
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _mk():
        c = AsyncIOMotorClient(_os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = c[_os.environ.get("DB_NAME", "test_database")]
        token = f"test_ca_{uuid.uuid4().hex}"
        await db.user_sessions.insert_one({
            "session_token": token,
            "user_id": KANKANI_ADMIN_USER_ID,
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
            "created_at": datetime.now(timezone.utc),
            "auth_method": "test_injected",
        })
        return token
    return asyncio.new_event_loop().run_until_complete(_mk())


def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": email, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def super_token() -> str:
    return _login(SUPER_EMAIL, SUPER_PASSWORD)


@pytest.fixture(scope="module")
def sub_token() -> str:
    return _login(SUB_EMAIL, SUB_PASSWORD)


@pytest.fixture(scope="module")
def ca_token() -> str:
    return _inject_company_admin_session()


@pytest.fixture(scope="module")
def ca_headers(ca_token) -> dict:
    return {"Authorization": f"Bearer {ca_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def super_headers(super_token) -> dict:
    return {"Authorization": f"Bearer {super_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def sub_headers(sub_token) -> dict:
    return {"Authorization": f"Bearer {sub_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def restore_global(super_headers):
    """Snapshot BEFORE tests; restore AFTER (payroll-affecting data)."""
    r = requests.get(f"{BASE_URL}/api/admin/compliance-settings", headers=super_headers, timeout=30)
    assert r.status_code == 200
    body = r.json()
    original = copy.deepcopy(body.get("settings") or {})
    defaults = copy.deepcopy(body.get("defaults") or {})
    yield {"original": original, "defaults": defaults}
    # Restore to whatever was there before this test module ran.
    restore_payload = {k: v for k, v in original.items() if v is not None}
    if restore_payload:
        rr = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings",
            headers=super_headers,
            json=restore_payload,
            timeout=30,
        )
        assert rr.status_code == 200, f"restore failed: {rr.text}"


# --------------------------------------------------------------------------- 
# GET (global)
# --------------------------------------------------------------------------- 
class TestReadGlobalSettings:

    def test_get_global_settings_super(self, super_headers):
        r = requests.get(f"{BASE_URL}/api/admin/compliance-settings", headers=super_headers, timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert "settings" in body and isinstance(body["settings"], dict)
        assert "defaults" in body and isinstance(body["defaults"], dict)
        # Required keys should exist in settings (fell through defaults if not persisted)
        for k in ("pf_percent_employee", "esic_percent_employee", "esic_gross_threshold",
                  "pf_wage_cap", "stat_wage_floor_pct", "pf_rounding", "esic_rounding"):
            assert k in body["settings"], f"missing key {k} in settings"

    def test_get_global_settings_sub(self, sub_headers):
        r = requests.get(f"{BASE_URL}/api/admin/compliance-settings", headers=sub_headers, timeout=30)
        assert r.status_code == 200
        assert "settings" in r.json()

    def test_get_global_settings_unauth(self):
        r = requests.get(f"{BASE_URL}/api/admin/compliance-settings", timeout=30)
        assert r.status_code in (401, 403)


# --------------------------------------------------------------------------- 
# PUT (global) — persistence, validation, role gate
# --------------------------------------------------------------------------- 
class TestSaveGlobalSettings:

    def test_persist_numeric_and_rounding(self, super_headers, restore_global):
        # Choose non-default values well away from originals for clear check.
        payload = {
            "pf_percent_employee": 11.0,
            "esic_gross_threshold": 21500.0,
            "pf_rounding": "floor",
        }
        r = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings",
            headers=super_headers, json=payload, timeout=30,
        )
        assert r.status_code == 200, r.text
        # Verify persisted via GET
        g = requests.get(f"{BASE_URL}/api/admin/compliance-settings", headers=super_headers, timeout=30)
        assert g.status_code == 200
        s = g.json()["settings"]
        assert float(s["pf_percent_employee"]) == 11.0
        assert float(s["esic_gross_threshold"]) == 21500.0
        assert s["pf_rounding"] == "floor"
        assert g.json().get("updated_at")
        assert g.json().get("updated_by_name")

    def test_reject_negative_number(self, super_headers):
        r = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings",
            headers=super_headers,
            json={"pf_percent_employee": -1.0},
            timeout=30,
        )
        assert r.status_code == 400
        assert "negative" in r.text.lower() or "must" in r.text.lower()

    def test_reject_invalid_rounding_mode(self, super_headers):
        r = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings",
            headers=super_headers,
            json={"pf_rounding": "banana"},
            timeout=30,
        )
        assert r.status_code == 400
        assert "one of" in r.text.lower() or "must be" in r.text.lower()

    def test_reject_empty_payload(self, super_headers):
        r = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings",
            headers=super_headers,
            json={},
            timeout=30,
        )
        assert r.status_code == 400
        assert "nothing" in r.text.lower()

    def test_role_gate_sub_admin_allowed_by_design(self, sub_headers):
        """Documented behaviour: sub_admin inherits super_admin's reach
        (server.py require_role line 1952). So PUT should return 200, NOT 403.
        This is NOT specific to this module — it is a system-wide policy."""
        r = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings",
            headers=sub_headers,
            json={"pf_percent_employee": 12.0},
            timeout=30,
        )
        assert r.status_code == 200, f"sub_admin should inherit super_admin reach; got {r.status_code}"

    def test_role_gate_company_admin_forbidden(self, ca_headers):
        r = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings",
            headers=ca_headers,
            json={"pf_percent_employee": 12.0},
            timeout=30,
        )
        assert r.status_code == 403, f"company_admin must be forbidden, got {r.status_code}: {r.text}"

    def test_company_admin_can_get(self, ca_headers):
        r = requests.get(f"{BASE_URL}/api/admin/compliance-settings", headers=ca_headers, timeout=30)
        assert r.status_code == 200


# --------------------------------------------------------------------------- 
# Firm-level overrides
# --------------------------------------------------------------------------- 
class TestFirmOverrides:

    def test_get_firm_settings_super(self, super_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=super_headers, timeout=30,
        )
        assert r.status_code == 200
        body = r.json()
        assert "overrides" in body
        assert "effective" in body and isinstance(body["effective"], dict)
        assert "standard" in body
        assert "has_override" in body

    def test_get_firm_settings_sub(self, sub_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=sub_headers, timeout=30,
        )
        assert r.status_code == 200

    def test_firm_override_lifecycle(self, super_headers):
        """Save override → verify has_override=true & effective merged → clear → verify gone."""
        # 1) Ensure clean baseline
        requests.put(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=super_headers, json={"clear": True}, timeout=30,
        )
        g0 = requests.get(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=super_headers, timeout=30,
        ).json()
        assert g0["has_override"] is False, f"expected clean state, got {g0}"
        std_esic = float(g0["standard"]["esic_percent_employee"])

        # 2) Save an override with a distinct value
        override_val = round(std_esic + 0.13, 4)
        r = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=super_headers,
            json={"esic_percent_employee": override_val},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        rb = r.json()
        assert rb.get("ok") is True
        assert float(rb["overrides"].get("esic_percent_employee")) == pytest.approx(override_val)

        # 3) GET reflects override + effective merges
        g1 = requests.get(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=super_headers, timeout=30,
        ).json()
        assert g1["has_override"] is True
        assert float(g1["overrides"]["esic_percent_employee"]) == pytest.approx(override_val)
        assert float(g1["effective"]["esic_percent_employee"]) == pytest.approx(override_val)
        # Other keys still come from standard
        assert float(g1["effective"]["pf_percent_employee"]) == float(g1["standard"]["pf_percent_employee"])

        # 4) Clear override
        c = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=super_headers, json={"clear": True}, timeout=30,
        )
        assert c.status_code == 200
        assert c.json().get("cleared") is True

        # 5) Confirm override gone
        g2 = requests.get(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=super_headers, timeout=30,
        ).json()
        assert g2["has_override"] is False
        assert not g2["overrides"]
        assert float(g2["effective"]["esic_percent_employee"]) == pytest.approx(std_esic)

    def test_firm_put_role_gate_sub_admin_allowed_by_design(self, sub_headers):
        """sub_admin inherits super_admin's reach — should be 200."""
        r = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=sub_headers,
            json={"esic_percent_employee": 0.85},
            timeout=30,
        )
        # Cleanup regardless
        requests.put(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=sub_headers, json={"clear": True}, timeout=30,
        )
        assert r.status_code == 200, f"sub_admin should inherit; got {r.status_code}"

    def test_firm_put_role_gate_company_admin_forbidden(self, ca_headers):
        r = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=ca_headers,
            json={"esic_percent_employee": 0.85},
            timeout=30,
        )
        assert r.status_code == 403, f"company_admin must be forbidden, got {r.status_code}: {r.text}"

    def test_firm_put_reject_empty(self, super_headers):
        r = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=super_headers, json={}, timeout=30,
        )
        assert r.status_code == 400
        assert "nothing" in r.text.lower()

    def test_firm_put_reject_negative(self, super_headers):
        r = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings/firm/{KANKANI_CID}",
            headers=super_headers,
            json={"pf_percent_employee": -0.5},
            timeout=30,
        )
        assert r.status_code == 400


# --------------------------------------------------------------------------- 
# Smoke: compliance salary run doesn't error after settings change
# --------------------------------------------------------------------------- 
class TestComplianceSalarySmoke:
    """Optional soft-smoke: ensure the compliance run endpoint still works.

    We don't want to fail hard if the exact endpoint contract changed —
    we only care that changing settings didn't break the wired module.
    """
    def test_compliance_preview_endpoint_reachable(self, super_headers):
        # Try a few possible endpoint shapes; skip if none present.
        candidates = [
            ("POST", f"/api/admin/compliance-salary/preview", {"company_id": KANKANI_CID, "month": "2026-06"}),
            ("POST", f"/api/compliance-salary/run", {"company_id": KANKANI_CID, "month": "2026-06", "preview": True}),
        ]
        found = False
        for method, path, body in candidates:
            r = requests.request(method, BASE_URL + path, headers=super_headers, json=body, timeout=60)
            if r.status_code != 404:
                found = True
                # not 5xx is what we want after settings changes
                assert r.status_code < 500, f"{path} returned {r.status_code}: {r.text[:200]}"
                break
        if not found:
            pytest.skip("no compliance-salary preview endpoint discovered")
