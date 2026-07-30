"""Iter 388 — PF & ESIC Validation Engine + Audit Dashboard + Reports + AI (Phases 3-6).

Direct DB access is used to fabricate synthetic runs so we never touch a real
Kankani finalized run. All synthetic data (runs + snapshots) is cleaned up.
"""
import os
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"
ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
ADMIN_PASSWORD = "sharma123"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

_mc = MongoClient(MONGO_URL)
_db = _mc[DB_NAME]


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json().get("token") or r.json().get("session_token")


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------- Real-run validate (Phase 3) ----------------
class TestValidateEndpoint:
    """Uses a real (non-finalized) run for month 2026-04 — cleaned up after."""

    _run_id = None

    def test_create_and_validate(self, hdr):
        r = requests.post(f"{BASE_URL}/api/admin/compliance-salary-runs",
                          headers=hdr,
                          json={"month": "2026-04", "company_id": COMPANY_ID},
                          timeout=180)
        assert r.status_code in (200, 201), r.text
        body = r.json()
        run = body.get("run") if isinstance(body.get("run"), dict) else body
        run_id = run.get("run_id") or body.get("run_id")
        assert run_id, body
        TestValidateEndpoint._run_id = run_id

        v = requests.get(f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/validate",
                         headers=hdr, timeout=60)
        assert v.status_code == 200, v.text
        j = v.json()
        for k in ("ok", "errors_count", "warnings_count",
                  "employees_flagged", "rows", "global_issues"):
            assert k in j, f"missing key {k}: {list(j)}"
        assert isinstance(j["rows"], list)
        # Each row should have issues[] with code/level/message/suggestion
        for row in j["rows"][:3]:
            assert "issues" in row and isinstance(row["issues"], list)
            for iss in row["issues"]:
                for kk in ("code", "level", "message", "suggestion"):
                    assert kk in iss

    def test_audit_dashboard(self, hdr):
        rid = TestValidateEndpoint._run_id
        assert rid
        r = requests.get(f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}/audit-dashboard",
                         headers=hdr, timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("summary", "rule_version", "rows", "run_id"):
            assert k in j
        for k in ("ok", "warning", "error", "total"):
            assert k in j["summary"]
        if j["rows"]:
            row = j["rows"][0]
            for k in ("status", "reason", "issues",
                      "pf_reason", "esic_reason", "calc_snapshot"):
                assert k in row, f"missing {k}"

    @pytest.mark.parametrize("kind,fmt", [
        ("pf", "xlsx"), ("pf", "pdf"),
        ("esic", "xlsx"), ("esic", "pdf"),
        ("exceptions", "xlsx"), ("exceptions", "pdf"),
    ])
    def test_audit_export_all_combos(self, hdr, kind, fmt):
        rid = TestValidateEndpoint._run_id
        assert rid
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}/audit-export",
            params={"kind": kind, "format": fmt}, headers=hdr, timeout=90)
        assert r.status_code == 200, f"{kind}/{fmt} -> {r.status_code}: {r.text[:200]}"
        assert len(r.content) > 500, f"{kind}/{fmt} content too small: {len(r.content)}"
        ct = r.headers.get("content-type", "")
        if fmt == "xlsx":
            assert "spreadsheet" in ct or "excel" in ct, ct
        else:
            assert "pdf" in ct, ct

    def test_ai_explain_one_employee(self, hdr):
        rid = TestValidateEndpoint._run_id
        assert rid
        run = _db.compliance_salary_runs.find_one({"run_id": rid}, {"rows": 1})
        assert run and run.get("rows"), "run has no rows"
        uid = run["rows"][0]["user_id"]
        r = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}/ai-explain/{uid}",
            headers=hdr, timeout=90)
        assert r.status_code == 200, f"AI explain failed: {r.status_code} {r.text[:200]}"
        j = r.json()
        assert j.get("explanation"), j
        txt = j["explanation"]
        # Should contain the numbered sections
        assert "1." in txt and "2." in txt, txt[:400]

    def test_zzz_cleanup_real_run(self, hdr):
        rid = TestValidateEndpoint._run_id
        if not rid:
            return
        d = requests.delete(f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}",
                            headers=hdr, timeout=30)
        assert d.status_code in (200, 204), d.text
        # ensure no snapshot doc exists for this run (should NOT — never finalized)
        assert _db.compliance_monthly_snapshots.count_documents({"run_id": rid}) == 0


# ---------------- Synthetic-run finalize gates (Phase 3+4) ----------------
class TestFinalizeGates:
    """Uses direct-Mongo synthetic runs so we can force error / warning / clean cases."""

    def _mk_run(self, tag, rows, statutory=None):
        rid = f"csr_TEST388_{tag}_{uuid.uuid4().hex[:6]}"
        stat = statutory or {
            "pf_wage_cap": 15000, "esic_gross_threshold": 21000,
            "wage_definition_rule_enabled": True,
            "esic_disable_above_ceiling": True,
            "rule_version": "TEST v1",
            "head_mapping": {
                "basic": {"pf": True, "esic": True},
                "hra": {"pf": False, "esic": True},
                "conveyance": {"pf": False, "esic": True},
                "medical": {"pf": False, "esic": True},
                "special": {"pf": True, "esic": True},
                "others": {"pf": True, "esic": True},
                "ot": {"pf": False, "esic": True},
            },
        }
        doc = {
            "run_id": rid,
            "month": "2026-04",
            "company_id": COMPANY_ID,
            "finalized": False,
            "statutory_effective": stat,
            "rows": rows,
            "generated_at": "2026-04-01T00:00:00Z",
            "_TEST_ITER388": True,
        }
        _db.compliance_salary_runs.insert_one(doc)
        return rid

    def _cleanup(self, rid):
        _db.compliance_salary_runs.delete_many({"run_id": rid})
        _db.compliance_monthly_snapshots.delete_many({"run_id": rid})

    def test_finalize_blocks_on_error(self, hdr):
        # pf_applicable True + pf_employee=0 with gross>0 => PF_ZERO error
        rows = [{
            "user_id": "TESTUSER_err1",
            "employee_code": "T-E1",
            "name": "TEST Error Employee",
            "gross_paid": 20000, "present_days": 26,
            "pf_applicable": True, "pf_employee": 0, "pf_wages": 15000,
            "pf_basic": 15000, "compliance_basic": 15000,
            "esic_applicable": False, "esic_employee": 0, "esic_wage_base": 0,
            "uan_no": "100000000001",
        }]
        rid = self._mk_run("err", rows)
        try:
            r = requests.post(
                f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}/finalize",
                headers=hdr, json={}, timeout=60)
            assert r.status_code == 422, f"expected 422 got {r.status_code}: {r.text[:250]}"
            j = r.json()
            det = j.get("detail") or {}
            assert "validation" in det, det
            assert det["validation"]["errors_count"] >= 1
            # Not finalized
            run_after = _db.compliance_salary_runs.find_one({"run_id": rid}, {"finalized": 1})
            assert not run_after.get("finalized")
            # No snapshot written
            assert _db.compliance_monthly_snapshots.count_documents({"run_id": rid}) == 0
        finally:
            self._cleanup(rid)

    def test_finalize_warning_only_then_override(self, hdr):
        # higher_pension True + eps_disabled True (or eps=0) with pf_employee>0
        # => PF_HIGHER_PENSION_MISMATCH warning (level=warning), NO errors.
        rows = [{
            "user_id": "TESTUSER_warn1",
            "employee_code": "T-W1",
            "name": "TEST Warning Employee",
            "gross_paid": 20000, "present_days": 26,
            "pf_applicable": True, "pf_employee": 1800,
            "pf_wages": 15000, "pf_basic": 15000, "compliance_basic": 15000,
            "pf_employer_epf": 1800, "pf_employer_eps": 0,
            "higher_pension": True, "eps_disabled": True,
            "esic_applicable": False, "esic_employee": 0, "esic_wage_base": 0,
            "uan_no": "100000000002",
        }]
        rid = self._mk_run("warn", rows)
        try:
            # First call w/o override -> 409 can_override True (super_admin)
            r = requests.post(
                f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}/finalize",
                headers=hdr, json={}, timeout=60)
            assert r.status_code == 409, f"expected 409 got {r.status_code}: {r.text[:250]}"
            det = r.json().get("detail") or {}
            assert det.get("can_override") is True
            assert det["validation"]["errors_count"] == 0
            assert det["validation"]["warnings_count"] >= 1

            # Now with allow_warnings=True as super_admin -> 200
            r2 = requests.post(
                f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}/finalize",
                headers=hdr, json={"allow_warnings": True}, timeout=60)
            assert r2.status_code == 200, f"override lock failed: {r2.status_code} {r2.text[:250]}"

            # Verify DB stamp
            run_after = _db.compliance_salary_runs.find_one({"run_id": rid})
            assert run_after.get("finalized") is True
            lv = run_after.get("lock_validation") or {}
            assert lv.get("warnings_overridden") is True
            assert lv.get("errors_count") == 0
            assert lv.get("warnings_count") >= 1

            # Snapshot must exist
            snap = _db.compliance_monthly_snapshots.find_one({"run_id": rid})
            assert snap is not None, "monthly snapshot not written"
            assert snap.get("company_id") == COMPANY_ID
            assert snap.get("month") == "2026-04"
            assert isinstance(snap.get("rows"), list) and len(snap["rows"]) >= 1
            assert snap.get("locked_by")  # non-empty
        finally:
            self._cleanup(rid)

    def test_finalize_clean_run_succeeds_with_snapshot(self, hdr):
        # Fully clean row (no PF/ESIC issues, no master mismatch)
        rows = [{
            "user_id": "TESTUSER_clean1",
            "employee_code": "T-C1",
            "name": "TEST Clean Employee",
            "gross_paid": 20000, "present_days": 26,
            "pf_applicable": False, "pf_employee": 0, "pf_wages": 0,
            "pf_basic": 0, "compliance_basic": 0,
            "esic_applicable": False, "esic_employee": 0, "esic_wage_base": 0,
        }]
        rid = self._mk_run("clean", rows)
        try:
            r = requests.post(
                f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}/finalize",
                headers=hdr, json={}, timeout=60)
            assert r.status_code == 200, f"clean finalize failed: {r.status_code} {r.text[:250]}"
            snap = _db.compliance_monthly_snapshots.find_one({"run_id": rid})
            assert snap is not None
        finally:
            self._cleanup(rid)


# ---------------- Missing IDs report (Phase 5) ----------------
class TestMissingIdsReport:
    @pytest.mark.parametrize("which,fmt", [
        ("uan", "xlsx"), ("uan", "pdf"),
        ("ip", "xlsx"), ("ip", "pdf"),
    ])
    def test_missing_ids(self, hdr, which, fmt):
        r = requests.get(f"{BASE_URL}/api/admin/compliance-reports/missing-ids",
                         params={"which": which, "company_id": COMPANY_ID, "format": fmt},
                         headers=hdr, timeout=60)
        assert r.status_code == 200, f"{which}/{fmt} -> {r.status_code}: {r.text[:200]}"
        assert len(r.content) > 400, len(r.content)
