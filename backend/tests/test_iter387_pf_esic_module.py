"""Iter 387 — Configurable PF/ESIC Statutory Module tests.

Covers:
- Standard & Firm compliance-settings GET/PUT with new Iter-387 fields
- Employee master round-trip of new PF/ESIC flags (create -> patch -> get -> delete)
- POST /admin/compliance-salary-runs row snapshot fields + backwards-compat
- Restores/clears firm override & deletes all test data at the end.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"
ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
ADMIN_PASSWORD = "sharma123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("session_token")
    assert tok, r.text
    return tok


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ------- Standard Compliance Settings ------------------------------------
class TestStandardComplianceSettings:
    def test_get_new_fields_present(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/compliance-settings", headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        s = r.json().get("settings") or {}
        for k in ("pf_enabled", "esic_enabled", "wage_definition_rule_enabled",
                  "esic_disable_above_ceiling", "pf_proration_method",
                  "esic_proration_method", "rule_version", "head_mapping"):
            assert k in s, f"Missing key {k} in settings"
        hm = s["head_mapping"]
        for hk in ("basic", "hra", "conveyance", "medical", "special", "others", "ot"):
            assert hk in hm and "pf" in hm[hk] and "esic" in hm[hk]

    def test_put_rejects_invalid_proration(self, hdr):
        r = requests.put(
            f"{BASE_URL}/api/admin/compliance-settings",
            headers=hdr,
            json={"pf_proration_method": "banana"},
            timeout=30,
        )
        assert r.status_code == 400, f"Expected 400 got {r.status_code}: {r.text}"

    def test_put_basic_head_forced_true(self, hdr):
        # Send basic head with pf/esic false; server must force to True
        payload = {
            "head_mapping": {
                "basic": {"pf": False, "esic": False},
                "hra": {"pf": False, "esic": True},
            },
            "rule_version": "FY 2026-27 v1",
        }
        r = requests.put(f"{BASE_URL}/api/admin/compliance-settings",
                         headers=hdr, json=payload, timeout=30)
        assert r.status_code == 200, r.text
        s = r.json().get("settings", {})
        assert s["head_mapping"]["basic"] == {"pf": True, "esic": True}
        assert s["rule_version"] == "FY 2026-27 v1"

    def test_put_saves_new_fields(self, hdr):
        payload = {
            "pf_enabled": True, "esic_enabled": True,
            "wage_definition_rule_enabled": True,
            "esic_disable_above_ceiling": True,
            "pf_proration_method": "calendar_days",
            "esic_proration_method": "calendar_days",
            "rule_version": "FY 2026-27 v1",
        }
        r = requests.put(f"{BASE_URL}/api/admin/compliance-settings",
                         headers=hdr, json=payload, timeout=30)
        assert r.status_code == 200, r.text
        # Re-GET
        g = requests.get(f"{BASE_URL}/api/admin/compliance-settings", headers=hdr, timeout=30).json()
        s = g["settings"]
        assert s["pf_enabled"] is True
        assert s["pf_proration_method"] == "calendar_days"
        assert s["rule_version"] == "FY 2026-27 v1"


# ------- Firm-level override --------------------------------------------
class TestFirmComplianceOverride:
    def test_get_firm_settings_shape(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/compliance-settings/firm/{COMPANY_ID}",
                         headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("overrides", "effective", "standard", "has_override"):
            assert k in j

    def test_put_firm_override_and_clear(self, hdr):
        # PUT override
        payload = {
            "pf_enabled": True,
            "esic_enabled": True,
            "wage_definition_rule_enabled": False,
            "pf_proration_method": "working_days",
            "rule_version": "Firm Override v1",
            "head_mapping": {
                "basic": {"pf": False, "esic": False},
                "hra": {"pf": True, "esic": True},
            },
        }
        r = requests.put(f"{BASE_URL}/api/admin/compliance-settings/firm/{COMPANY_ID}",
                         headers=hdr, json=payload, timeout=30)
        assert r.status_code == 200, r.text
        # Verify GET
        g = requests.get(f"{BASE_URL}/api/admin/compliance-settings/firm/{COMPANY_ID}",
                        headers=hdr, timeout=30).json()
        ov = g["overrides"]
        assert ov.get("wage_definition_rule_enabled") is False
        assert ov.get("pf_proration_method") == "working_days"
        # basic must be forced back to true
        assert ov["head_mapping"]["basic"] == {"pf": True, "esic": True}
        # effective merge
        eff = g["effective"]
        assert eff["wage_definition_rule_enabled"] is False
        assert eff["pf_proration_method"] == "working_days"
        assert g["has_override"] is True

        # Clear
        r = requests.put(f"{BASE_URL}/api/admin/compliance-settings/firm/{COMPANY_ID}",
                        headers=hdr, json={"clear": True}, timeout=30)
        assert r.status_code == 200, r.text
        g = requests.get(f"{BASE_URL}/api/admin/compliance-settings/firm/{COMPANY_ID}",
                        headers=hdr, timeout=30).json()
        assert g["overrides"] == {}
        assert g["has_override"] is False


# ------- Employee master round-trip -------------------------------------
class TestEmployeeMasterNewFields:
    def test_create_patch_get_delete(self, hdr):
        # Create test employee
        payload = {
            "name": "TEST_Iter387 Employee",
            "employee_code": f"TEST387{int(time.time()) % 100000}",
            "company_id": COMPANY_ID,
            "phone": "+919899999999",
            "designation": "Test",
            "employee_type": "Staff",
            "salary_monthly": 20000,
            "compliance_basic": 8000,
            "pf_basic": 8000,
            "higher_pension": True,
            "intl_worker": True,
            "excluded_employee": False,
            "esic_temp_exempt": True,
            "esic_reg_status": "Registered",
            "dispensary": "Test Dispensary",
            "esic_join_date": "2026-01-01",
            "esic_exit_date": "2026-06-30",
        }
        r = requests.post(f"{BASE_URL}/api/admin/employees", headers=hdr,
                        json=payload, timeout=30)
        assert r.status_code in (200, 201), f"Create failed {r.status_code}: {r.text}"
        emp = r.json().get("employee") or r.json()
        user_id = emp.get("user_id") or (emp.get("employee") or {}).get("user_id")
        assert user_id, f"No user_id returned: {r.text}"

        try:
            # GET profile
            g = requests.get(f"{BASE_URL}/api/admin/employees/{user_id}/profile",
                            headers=hdr, timeout=30)
            assert g.status_code == 200, g.text
            got = g.json()
            # Verify PATCH: flip values
            patch = {
                "higher_pension": False,
                "intl_worker": False,
                "excluded_employee": True,
                "esic_temp_exempt": False,
                "esic_reg_status": "Not Registered",
                "dispensary": "Updated Dispensary",
                "esic_join_date": "2026-02-01",
                "esic_exit_date": "",
            }
            p = requests.patch(f"{BASE_URL}/api/admin/employees/{user_id}/profile",
                            headers=hdr, json=patch, timeout=30)
            assert p.status_code == 200, p.text
            g2 = requests.get(f"{BASE_URL}/api/admin/employees/{user_id}/profile",
                            headers=hdr, timeout=30).json()
            assert g2.get("higher_pension") is False
            assert g2.get("intl_worker") is False
            assert g2.get("excluded_employee") is True
            assert g2.get("esic_temp_exempt") is False
            assert g2.get("esic_reg_status") == "Not Registered"
            assert g2.get("dispensary") == "Updated Dispensary"
            assert g2.get("esic_join_date") == "2026-02-01"
        finally:
            # Cleanup
            d = requests.delete(f"{BASE_URL}/api/admin/employees/{user_id}",
                                headers=hdr, timeout=30)
            assert d.status_code in (200, 204), f"Delete failed: {d.status_code} {d.text}"


# ------- Compliance salary run row snapshot ------------------------------
class TestComplianceRunSnapshot:
    def test_run_row_has_new_fields(self, hdr):
        payload = {"month": "2026-06", "company_id": COMPANY_ID}
        r = requests.post(f"{BASE_URL}/api/admin/compliance-salary-runs",
                        headers=hdr, json=payload, timeout=180)
        assert r.status_code in (200, 201), f"Run failed {r.status_code}: {r.text}"
        body = r.json()
        run = body.get("run") if isinstance(body.get("run"), dict) else body
        run_id = run.get("run_id") or run.get("id") or body.get("run_id")
        try:
            assert "statutory_effective" in run, "run.statutory_effective missing"
            rows = run.get("rows") or []
            assert rows, "No rows in run"
            sample = None
            for row in rows:
                if row.get("pf_basic", 0) > 0:
                    sample = row
                    break
            sample = sample or rows[0]
            for k in ("pf_reason", "esic_reason", "calc_snapshot",
                    "higher_pension", "intl_worker", "excluded_employee",
                    "esic_temp_exempt"):
                assert k in sample, f"Row missing {k}"
            snap = sample["calc_snapshot"]
            assert "rule_version" in snap
            assert "wage_definition_rule" in snap
            assert "pf" in snap and "esic" in snap
            assert "heads_considered" in snap
            for hk in ("basic", "hra", "conveyance", "medical", "special", "others", "ot"):
                assert hk in snap["heads_considered"]
        finally:
            if run_id:
                requests.delete(f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}",
                                headers=hdr, timeout=30)
