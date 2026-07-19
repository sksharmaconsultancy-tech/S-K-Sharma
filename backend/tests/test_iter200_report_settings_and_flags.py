"""Iter 200 backend tests — report settings, policy flags, holiday master,
salary_allowed gate, employee offline_salary toggle, saved-list & presets.

Cleanup is best-effort; each test restores what it changed.
"""
import os
import copy
from typing import Any, Dict

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or \
           os.environ.get("EXPO_BACKEND_URL")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"
BASE_URL = BASE_URL.rstrip("/")

CID = "cmp_527fecdd7c"
TEST_USER_ID = "user_44cd6f561da0"  # TEST50 (SURENDRA SINGH)
ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
ADMIN_PASS = "sharma123"


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=30,
    )
    assert r.status_code == 200, f"login {r.status_code}: {r.text[:200]}"
    tok = r.json().get("token") or r.json().get("session_token") or r.json().get("access_token")
    assert tok, r.text
    return tok


@pytest.fixture(scope="module")
def headers(token) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------- helpers ----------------
def _get_policy(headers) -> Dict[str, Any]:
    r = requests.get(f"{BASE_URL}/api/attendance/policy",
                     params={"company_id": CID}, headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _patch_policy(headers, policy: Dict[str, Any]):
    r = requests.patch(f"{BASE_URL}/api/attendance/policy",
                       params={"company_id": CID},
                       json={"policy": policy}, headers=headers, timeout=30)
    return r


# ---------------- Backend 1 ----------------
class TestReportSettingsGate:
    def test_1a_policy_shape(self, headers):
        # Force _validate_policy to backfill by doing a no-op PATCH first;
        # the review request expects GET to expose the 3 new policy_master
        # flags after any save cycle.
        data = _get_policy(headers)
        p_now = data["policy"]
        rr = _patch_policy(headers, p_now)
        assert rr.status_code == 200, rr.text
        data = _get_policy(headers)
        p = data["policy"]
        rs = p.get("report_settings")
        assert isinstance(rs, dict)
        en = rs.get("enabled") or {}
        for k in ("inout", "ot", "hours", "salary", "inout_salary"):
            assert k in en, f"missing report_settings.enabled.{k}"
            assert en[k] is True, f"default {k} should be True"
        assert rs.get("default_view") in ("inout", "ot", "hours", "salary", "inout_salary")
        assert p.get("salary_allowed", "both") in ("actual", "compliance", "both")
        pm = p.get("policy_master") or {}
        for k in ("attendance_by_duty_hours", "weekoff_present_add_ot", "holiday_present_add_ot"):
            assert k in pm, f"policy_master missing {k}"

    def test_1b_disable_hours_and_export_403(self, headers):
        data = _get_policy(headers)
        original = copy.deepcopy(data["policy"])
        modified = copy.deepcopy(original)
        modified["report_settings"]["enabled"]["hours"] = False
        modified["report_settings"]["default_view"] = "inout"
        r = _patch_policy(headers, modified)
        assert r.status_code == 200, f"patch: {r.status_code} {r.text[:200]}"
        try:
            # Verify persisted
            check = _get_policy(headers)
            assert check["policy"]["report_settings"]["enabled"]["hours"] is False
            assert check["policy"]["report_settings"]["default_view"] == "inout"
            # hours export -> 403
            r2 = requests.get(
                f"{BASE_URL}/api/admin/attendance/monthly-hours/{CID}/2026-07.xlsx",
                headers=headers, timeout=30)
            assert r2.status_code == 403, f"expected 403, got {r2.status_code} {r2.text[:200]}"
            assert "disabled" in r2.text.lower() or "hours" in r2.text.lower()
            # inout export -> 200
            r3 = requests.get(
                f"{BASE_URL}/api/admin/attendance/monthly-inout/{CID}/2026-07.xlsx",
                headers=headers, timeout=60)
            assert r3.status_code == 200, f"inout xlsx {r3.status_code}: {r3.text[:200]}"
        finally:
            # Restore
            rr = _patch_policy(headers, original)
            assert rr.status_code == 200


# ---------------- Backend 2 ----------------
@pytest.fixture(scope="module")
def holiday_master(headers):
    # First test creation w/ bad payload rejected
    r_bad = requests.post(
        f"{BASE_URL}/api/admin/masters",
        json={"type": "holiday", "company_id": "__global__", "name": "TEST HOLIDAY NODATE"},
        headers=headers, timeout=30,
    )
    assert r_bad.status_code == 400, f"expected 400 no-date, got {r_bad.status_code} {r_bad.text[:200]}"

    r = requests.post(
        f"{BASE_URL}/api/admin/masters",
        json={"type": "holiday", "company_id": "__global__",
              "name": "TEST HOLIDAY", "date": "2026-07-15"},
        headers=headers, timeout=30,
    )
    assert r.status_code in (200, 201), f"create holiday {r.status_code} {r.text[:200]}"
    body = r.json()
    assert body.get("date") == "2026-07-15"
    assert body.get("type") == "holiday"
    mid = body.get("master_id")
    yield mid
    # cleanup
    requests.delete(f"{BASE_URL}/api/admin/masters/{mid}", headers=headers, timeout=30)


class TestHolidayMaster:
    def test_2_holiday_created_and_listed(self, headers, holiday_master):
        assert holiday_master
        r = requests.get(f"{BASE_URL}/api/admin/masters",
                         params={"type": "holiday"}, headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        rows = body if isinstance(body, list) else (body.get("masters") or body.get("items") or [])
        assert any(m.get("master_id") == holiday_master for m in rows), \
            f"holiday not in list; sample={rows[:2]}"


# ---------------- Backend 3 ----------------
class TestPolicyMasterFlags:
    def test_3_flags_seed_grid_and_cleanup(self, headers, holiday_master):
        # Seed punches via Mongo directly (attendance import isn't a public endpoint)
        import subprocess
        original = _get_policy(headers)["policy"]
        modified = copy.deepcopy(original)
        pm = modified.setdefault("policy_master", {})
        pm["holiday_present_add_ot"] = True
        pm["weekoff_present_add_ot"] = True
        # Also make sure sunday is a weekly_off
        modified["weekly_off_days"] = sorted(set(list(modified.get("weekly_off_days") or []) + [6]))
        r = _patch_policy(headers, modified)
        assert r.status_code == 200, r.text

        # Verify GET reflects
        check = _get_policy(headers)["policy"]
        assert check["policy_master"]["holiday_present_add_ot"] is True
        assert check["policy_master"]["weekoff_present_add_ot"] is True

        # Seed punches via mongosh (matching existing schema: at stored
        # as ISO string, real UTC — 09:00 IST = 03:30Z, 17:00 IST = 11:30Z)
        seed = (
            f"db.attendance.deleteMany({{user_id:'{TEST_USER_ID}', _iter200_test:true}});"
            f"db.attendance.insertMany(["
            f"{{record_id:'att_it200_h_in', user_id:'{TEST_USER_ID}', company_id:'{CID}',"
            f" date:'2026-07-15', kind:'in', at:'2026-07-15T03:30:00Z',"
            f" source:'iter200_test', status:'approved', _iter200_test:true}},"
            f"{{record_id:'att_it200_h_out', user_id:'{TEST_USER_ID}', company_id:'{CID}',"
            f" date:'2026-07-15', kind:'out', at:'2026-07-15T11:30:00Z',"
            f" source:'iter200_test', status:'approved', _iter200_test:true}},"
            f"{{record_id:'att_it200_w_in', user_id:'{TEST_USER_ID}', company_id:'{CID}',"
            f" date:'2026-07-12', kind:'in', at:'2026-07-12T03:30:00Z',"
            f" source:'iter200_test', status:'approved', _iter200_test:true}},"
            f"{{record_id:'att_it200_w_out', user_id:'{TEST_USER_ID}', company_id:'{CID}',"
            f" date:'2026-07-12', kind:'out', at:'2026-07-12T11:30:00Z',"
            f" source:'iter200_test', status:'approved', _iter200_test:true}}"
            f"])"
        )
        p = subprocess.run(["mongosh", "--quiet", "test_database", "--eval", seed],
                           capture_output=True, text=True, timeout=30)
        assert p.returncode == 0, p.stderr

        try:
            r2 = requests.get(
                f"{BASE_URL}/api/admin/attendance/monthly-grid/{CID}/2026-07",
                headers=headers, timeout=90,
            )
            assert r2.status_code == 200, f"grid {r2.status_code} {r2.text[:200]}"
            body = r2.json()
            # locate our employee
            rows = body.get("rows") or body.get("employees") or body.get("data") or []
            if isinstance(rows, dict):
                rows = rows.get("rows") or []
            row = next((r for r in rows
                        if (r.get("user_id") == TEST_USER_ID
                            or r.get("employee_id") == TEST_USER_ID)), None)
            assert row is not None, f"TEST50 row missing in grid; keys={list(body.keys())[:6]}"
            days = row.get("days") or row.get("cells") or {}
            if isinstance(days, list):
                days_map = {(d.get("date") or d.get("day")): d for d in days}
            else:
                days_map = days
            hol_cell = days_map.get("2026-07-15") or days_map.get("15") or days_map.get(15)
            assert hol_cell, f"holiday cell missing; sample={list(days_map)[:5]}"
            print("HOLIDAY CELL:", hol_cell)
            # Expect OT > 0 and duty ~0 and holiday flag true, employee counts as present
            ot_h = float(hol_cell.get("ot_hours") or hol_cell.get("ot") or 0)
            duty_h = float(hol_cell.get("duty_hours") or hol_cell.get("duty") or 0)
            assert ot_h > 0, f"holiday ot_hours not > 0: {ot_h}"
            assert duty_h == 0, f"holiday duty_hours not 0: {duty_h}"
            assert hol_cell.get("holiday") is True or hol_cell.get("is_holiday") is True

            wk_cell = days_map.get("2026-07-12") or days_map.get("12") or days_map.get(12)
            assert wk_cell, f"weekoff cell missing"
            print("WEEKOFF CELL:", wk_cell)
            wk_ot = float(wk_cell.get("ot_hours") or wk_cell.get("ot") or 0)
            wk_duty = float(wk_cell.get("duty_hours") or wk_cell.get("duty") or 0)
            assert wk_ot > 0, f"weekoff ot_hours not > 0: {wk_ot}"
            assert wk_duty == 0, f"weekoff duty_hours not 0: {wk_duty}"
        finally:
            # Cleanup punches
            subprocess.run(["mongosh", "--quiet", "test_database", "--eval",
                            "db.attendance.deleteMany({_iter200_test:true})"],
                           capture_output=True, text=True, timeout=30)
            # Restore policy
            rr = _patch_policy(headers, original)
            assert rr.status_code == 200


# ---------------- Backend 4 ----------------
class TestSalaryAllowedGate:
    def test_4_gate(self, headers):
        original = _get_policy(headers)["policy"]
        try:
            # set compliance
            mod = copy.deepcopy(original)
            mod["salary_allowed"] = "compliance"
            assert _patch_policy(headers, mod).status_code == 200
            r = requests.post(f"{BASE_URL}/api/admin/salary-runs",
                              json={"company_id": CID, "month": "2026-06", "run_type": "off_roll"},
                              headers=headers, timeout=60)
            assert r.status_code == 400, f"compliance-only should block off_roll, got {r.status_code} {r.text[:200]}"
            assert "compliance" in r.text.lower()

            # set actual
            mod["salary_allowed"] = "actual"
            assert _patch_policy(headers, mod).status_code == 200
            r2 = requests.post(f"{BASE_URL}/api/admin/salary-runs",
                               json={"company_id": CID, "month": "2026-06",
                                     "run_type": "compliance"},
                               headers=headers, timeout=60)
            assert r2.status_code == 400, f"actual-only should block compliance, got {r2.status_code} {r2.text[:200]}"
            assert "actual" in r2.text.lower()

            # Restore + create OK
            mod["salary_allowed"] = "both"
            assert _patch_policy(headers, mod).status_code == 200
            r3 = requests.post(f"{BASE_URL}/api/admin/salary-runs",
                               json={"company_id": CID, "month": "2026-06",
                                     "run_type": "compliance"},
                               headers=headers, timeout=120)
            assert r3.status_code in (200, 201), f"both should allow, got {r3.status_code} {r3.text[:200]}"
            # cleanup created run
            run_id = ((r3.json().get("run") or {}).get("run_id")) if r3.ok else None
            if run_id:
                requests.delete(f"{BASE_URL}/api/admin/salary-runs/{run_id}",
                                headers=headers, timeout=30)
        finally:
            _patch_policy(headers, original)


# ---------------- Backend 5 ----------------
class TestOfflineSalaryToggle:
    def test_5_employee_offline_toggle(self, headers):
        # Read current firm master
        import subprocess, json as _json
        p = subprocess.run(["mongosh", "--quiet", "test_database", "--eval",
                            f"JSON.stringify(db.firm_masters.findOne("
                            f"{{company_id:'{CID}'}}, {{_id:0, salary_process:1}}))"],
                           capture_output=True, text=True, timeout=30)
        assert p.returncode == 0, p.stderr
        raw = p.stdout.strip().split("\n")[-1]
        try:
            orig_fm = _json.loads(raw)
        except Exception:
            orig_fm = None
        orig_offline = bool(((orig_fm or {}).get("salary_process") or {}).get("offline_salary"))
        # Read employee original offline_salary_enabled
        p2 = subprocess.run(["mongosh", "--quiet", "test_database", "--eval",
                             f"JSON.stringify(db.users.findOne("
                             f"{{user_id:'{TEST_USER_ID}'}}, {{_id:0, offline_salary_enabled:1}}))"],
                            capture_output=True, text=True, timeout=30)
        raw2 = p2.stdout.strip().split("\n")[-1]
        try:
            orig_emp = _json.loads(raw2)
        except Exception:
            orig_emp = {}
        orig_emp_flag = orig_emp.get("offline_salary_enabled")

        # Force firm OFF
        subprocess.run(["mongosh", "--quiet", "test_database", "--eval",
                        f"db.firm_masters.updateOne("
                        f"{{company_id:'{CID}'}},"
                        f"{{$set:{{'salary_process.offline_salary':false}}}}, {{upsert:true}})"],
                       capture_output=True, text=True, timeout=30)
        try:
            r_bad = requests.patch(
                f"{BASE_URL}/api/admin/user-role",
                json={"user_id": TEST_USER_ID, "offline_salary_enabled": False},
                headers=headers, timeout=30)
            assert r_bad.status_code == 400, f"expected 400 firm-off, got {r_bad.status_code} {r_bad.text[:200]}"
            assert "offline salary" in r_bad.text.lower()

            # Enable firm flag
            subprocess.run(["mongosh", "--quiet", "test_database", "--eval",
                            f"db.firm_masters.updateOne("
                            f"{{company_id:'{CID}'}},"
                            f"{{$set:{{'salary_process.offline_salary':true}}}})"],
                           capture_output=True, text=True, timeout=30)
            r_ok = requests.patch(
                f"{BASE_URL}/api/admin/user-role",
                json={"user_id": TEST_USER_ID, "offline_salary_enabled": False},
                headers=headers, timeout=30)
            assert r_ok.status_code == 200, f"patch: {r_ok.status_code} {r_ok.text[:200]}"
            # Verify persistence
            p3 = subprocess.run(["mongosh", "--quiet", "test_database", "--eval",
                                 f"JSON.stringify(db.users.findOne("
                                 f"{{user_id:'{TEST_USER_ID}'}}, {{_id:0, offline_salary_enabled:1}}))"],
                                capture_output=True, text=True, timeout=30)
            row = _json.loads(p3.stdout.strip().split("\n")[-1])
            assert row.get("offline_salary_enabled") is False, row
        finally:
            # Restore employee flag
            val_expr = "null" if orig_emp_flag is None else str(orig_emp_flag).lower()
            subprocess.run(["mongosh", "--quiet", "test_database", "--eval",
                            f"db.users.updateOne("
                            f"{{user_id:'{TEST_USER_ID}'}},"
                            f"{{$set:{{offline_salary_enabled:{val_expr}}}}})"],
                           capture_output=True, text=True, timeout=30)
            # Restore firm flag
            fv = "true" if orig_offline else "false"
            subprocess.run(["mongosh", "--quiet", "test_database", "--eval",
                            f"db.firm_masters.updateOne("
                            f"{{company_id:'{CID}'}},"
                            f"{{$set:{{'salary_process.offline_salary':{fv}}}}})"],
                           capture_output=True, text=True, timeout=30)


# ---------------- Backend 6 ----------------
class TestSavedListAndPresets:
    def test_6a_saved_list(self, headers):
        r = requests.get(f"{BASE_URL}/api/attendance/policy/saved-list",
                         headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        firms = body.get("firms")
        assert isinstance(firms, list)
        # kankani should have a policy (default preset is auto-attached but only
        # returned when attendance_policy is not None — should be true here)
        # Just assert list came back; kankani may or may not appear if never saved.
        # Ensure required keys exist for each entry
        for entry in firms[:5]:
            assert "company_id" in entry and "name" in entry

    def test_6b_presets_no_hospital_no_textile_sub(self, headers):
        r = requests.get(f"{BASE_URL}/api/attendance/policy/presets",
                         headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        presets = r.json().get("presets") if isinstance(r.json(), dict) else r.json()
        assert isinstance(presets, list)
        cats = [(p.get("business_category") or p.get("key")) for p in presets]
        assert "hospital" not in cats, f"hospital preset still present: {cats}"
        # No 'textile' preset with sub 1/2 keys
        for p in presets:
            sub = (p.get("business_subcategory") or p.get("sub") or "").lower()
            variant = (p.get("policy_variant") or "").lower()
            assert "textile_1" not in variant and "textile_2" not in variant, \
                f"textile sub-preset present: {p}"
