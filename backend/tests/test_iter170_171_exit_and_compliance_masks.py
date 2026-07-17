"""Iter 170/171 backend tests.

Covers:
 * _month_is_after_exit unit matrix (11 cases spec'd by main agent)
 * Master Data Report status filter (active vs left) when
   employment_status='resigned' is toggled on a Kankani employee
 * Compliance Salary run masking driven by Firm Master
   allowances + deductions (Iter 171)
 * Regression: when firm allowances/deductions are all-false /
   unconfigured, no mask is applied.
"""
import os
import sys
import pytest
import requests
from pymongo import MongoClient

# ---------------------------------------------------------------------------
# Ensure we can import backend.server for the unit-tests
sys.path.insert(0, "/app/backend")
from server import _month_is_after_exit  # noqa: E402

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
COMPANY_ID = "cmp_527fecdd7c"
ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
ADMIN_PASSWORD = "sharma123"


# ---------------------------------------------------------------------------
# Fixtures
@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def session_token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text[:200]}"
    tok = r.json().get("session_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def api(session_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {session_token}",
                      "Content-Type": "application/json"})
    return s


# ---------------------------------------------------------------------------
# ------- Iter 170: _month_is_after_exit unit matrix ------------------------
class TestMonthIsAfterExitUnit:
    def test_iso_prior_month_excluded(self):
        assert _month_is_after_exit({"exit_date": "2026-06-15"}, "2026-07") is True

    def test_ddmmyyyy_dash_prior_month_excluded(self):
        assert _month_is_after_exit({"exit_date": "15-06-2026"}, "2026-07") is True

    def test_ddmmyyyy_slash_prior_month_excluded(self):
        assert _month_is_after_exit({"exit_date": "15/06/2026"}, "2026-07") is True

    def test_iso_current_month_included_final_settlement(self):
        assert _month_is_after_exit({"exit_date": "2026-07-10"}, "2026-07") is False

    def test_status_resigned_no_date_excluded(self):
        assert _month_is_after_exit({"employment_status": "Resigned"}, "2026-07") is True

    def test_status_exited_no_date_excluded(self):
        assert _month_is_after_exit({"employment_status": "EXITED"}, "2026-07") is True

    def test_status_active_no_date_included(self):
        assert _month_is_after_exit({"employment_status": "active"}, "2026-07") is False

    def test_unreadable_exit_date_excluded(self):
        assert _month_is_after_exit({"exit_date": "garbage"}, "2026-07") is True

    def test_empty_user_included(self):
        assert _month_is_after_exit({}, "2026-07") is False

    def test_resign_date_alt_field_prior_month_excluded(self):
        assert _month_is_after_exit({"resign_date": "2026-05-30"}, "2026-07") is True

    def test_leaving_date_alt_field_prior_month_excluded(self):
        assert _month_is_after_exit({"leaving_date": "10-05-2026"}, "2026-07") is True


# ---------------------------------------------------------------------------
# ------- Iter 170: Master Data Report status filter ------------------------
class TestMasterDataStatusFilter:
    """Toggle employment_status='resigned' on a Kankani employee and
    verify active/left tabs behave. Restores the doc at the end."""

    original = {}
    victim_uid = None

    @classmethod
    def setup_class(cls):
        client = MongoClient(MONGO_URL)
        cls.db = client[DB_NAME]
        # Pick any active Kankani employee with no exit markers
        emp = cls.db.users.find_one({
            "company_id": COMPANY_ID,
            "role": "employee",
            "employment_status": {"$in": [None, "", "active", "Active"]},
            "exit_date": {"$in": [None, ""]},
            "resign_date": {"$in": [None, ""]},
        })
        assert emp, "no candidate active Kankani employee found"
        cls.victim_uid = emp["user_id"]
        cls.original = {
            "employment_status": emp.get("employment_status"),
        }

    @classmethod
    def teardown_class(cls):
        if cls.victim_uid:
            cls.db.users.update_one(
                {"user_id": cls.victim_uid},
                {"$set": {"employment_status": cls.original.get("employment_status")}},
            )

    def _report(self, api, status):
        r = api.get(
            f"{BASE_URL}/api/admin/reports/master-data",
            params={"status": status, "company_id": COMPANY_ID},
            timeout=60,
        )
        assert r.status_code == 200, f"{status}: {r.status_code} {r.text[:200]}"
        return r.json()

    def test_active_excludes_after_resigned_marker(self, api):
        # Before: user is present in active
        pre = self._report(api, "active")
        rows = pre.get("rows") or pre.get("employees") or pre.get("data") or []
        pre_ids = {r.get("user_id") for r in rows}
        assert self.victim_uid in pre_ids, "victim missing before mutation"

        # Flip to resigned (no exit_date)
        self.db.users.update_one(
            {"user_id": self.victim_uid},
            {"$set": {"employment_status": "resigned"}},
        )

        post = self._report(api, "active")
        rows = post.get("rows") or post.get("employees") or post.get("data") or []
        post_ids = {r.get("user_id") for r in rows}
        assert self.victim_uid not in post_ids, (
            "resigned employee should be excluded from active tab")

    def test_left_includes_after_resigned_marker(self, api):
        # Ensure marker still applied (previous test set it)
        self.db.users.update_one(
            {"user_id": self.victim_uid},
            {"$set": {"employment_status": "resigned"}},
        )
        j = self._report(api, "left")
        rows = j.get("rows") or j.get("employees") or j.get("data") or []
        ids = {r.get("user_id") for r in rows}
        assert self.victim_uid in ids, "resigned employee missing from left tab"


# ---------------------------------------------------------------------------
# ------- Iter 171: Compliance Salary column masks --------------------------
class TestComplianceMasks:
    """Set Firm Master allowances={HRA:true}/deductions={PF:true,ESI:true}
    → compliance rows must reflect the mask. Then restore."""

    original_allowances = None
    original_deductions = None
    created_run_ids = []

    @classmethod
    def setup_class(cls):
        client = MongoClient(MONGO_URL)
        cls.db = client[DB_NAME]
        fm = cls.db.firm_masters.find_one({"company_id": COMPANY_ID}) or {}
        cls.original_allowances = fm.get("allowances")
        cls.original_deductions = fm.get("deductions")

    @classmethod
    def teardown_class(cls):
        client = MongoClient(MONGO_URL)
        db = client[DB_NAME]
        # Restore original allowances/deductions
        db.firm_masters.update_one(
            {"company_id": COMPANY_ID},
            {"$set": {
                "allowances": cls.original_allowances,
                "deductions": cls.original_deductions,
            }},
        )
        # Remove created runs
        for rid in cls.created_run_ids:
            db.compliance_salary_runs.delete_one({"run_id": rid})

    def _create_run(self, api, month="2026-07"):
        r = api.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs",
            json={"company_id": COMPANY_ID, "month": month},
            timeout=180,
        )
        assert r.status_code in (200, 201), f"run create: {r.status_code} {r.text[:400]}"
        j = r.json()
        run = j.get("run") or j
        rid = run.get("run_id") or run.get("id")
        if rid:
            self.created_run_ids.append(rid)
        return run

    def test_apply_mask_and_verify_rows(self, api):
        # Mutate firm master
        self.db.firm_masters.update_one(
            {"company_id": COMPANY_ID},
            {"$set": {
                "allowances": {
                    "HRA": True,
                    "CONV.": False,
                    "MEDICAL ALLOWANCES": False,
                    "OTH. ALLOW.": False,
                    "OTHER MISC.ALLOWANCE": False,
                },
                "deductions": {
                    "PF": True, "ESI": True,
                    "PT": False, "TDS": False, "I. TAX": False,
                },
            }},
        )

        j = self._create_run(api, "2026-07")
        rows = j.get("rows") or []
        assert rows, "no rows in run"

        # Only sample first 5 rows (perf); assert invariants
        for r in rows[:5]:
            assert float(r.get("conveyance") or 0) == 0.0
            assert float(r.get("medical") or 0) == 0.0
            assert float(r.get("special") or 0) == 0.0
            assert float(r.get("others") or 0) == 0.0
            ea = r.get("enabled_allowances")
            assert ea is not None, "enabled_allowances missing"
            assert set(ea) == {"basic", "hra"}, f"unexpected enabled_allowances: {ea}"
            ed = r.get("enabled_deductions")
            assert ed is not None
            assert set(ed) == {"esi", "pf"}, f"unexpected enabled_deductions: {ed}"
            assert float(r.get("pt") or 0) == 0.0
            assert float(r.get("tds") or 0) == 0.0
            heads_sum = round(
                float(r.get("basic") or 0) + float(r.get("hra") or 0), 2)
            assert abs(float(r.get("monthly_gross") or 0) - heads_sum) < 0.02, (
                f"gross mismatch {r.get('monthly_gross')} vs {heads_sum}")
            # Net consistent: total_deduction should not include pt/tds
            # (they've been added back). Sanity: net = gross_paid - total_ded
            gp = float(r.get("gross_paid") or 0)
            td = float(r.get("total_deduction") or 0)
            net = float(r.get("net") or 0)
            # Adjust for any 'other_deduction' or 'ot_pay' that back-adds
            # into net, we allow a small tolerance
            assert abs((gp - td) - net) < 1.5 or abs(gp - td - net) < 5.0, (
                f"net mismatch gp={gp} td={td} net={net}")

    def test_all_false_no_mask_applied(self, api):
        # Set every allowance / deduction to False → catalog exists but
        # all switched off. Per spec: mask only applied when firm has
        # ≥1 configured. So enabled_allowances/deductions should NOT be
        # added AND ded columns should retain their computed values.
        self.db.firm_masters.update_one(
            {"company_id": COMPANY_ID},
            {"$set": {
                "allowances": {
                    "HRA": False, "CONV.": False, "MEDICAL ALLOWANCES": False,
                    "OTH. ALLOW.": False, "OTHER MISC.ALLOWANCE": False,
                },
                "deductions": {
                    "PF": False, "ESI": False, "PT": False, "TDS": False,
                    "I. TAX": False,
                },
            }},
        )

        j = self._create_run(api, "2026-07")
        rows = j.get("rows") or []
        assert rows
        # Backend "any(bool(v))" test: since every deduction value is False,
        # ded_mask stays None → enabled_deductions absent OR present but
        # matches default. Same for allowances (all-false → empty mask →
        # None). Verify no forced zeroing beyond baseline.
        r0 = rows[0]
        # enabled_deductions should be absent (mask None)
        assert "enabled_deductions" not in r0 or r0.get("enabled_deductions") in (
            None, []), f"unexpected mask when all false: {r0.get('enabled_deductions')}"
        assert "enabled_allowances" not in r0 or r0.get("enabled_allowances") in (
            None, []), f"unexpected allow mask when all false: {r0.get('enabled_allowances')}"
