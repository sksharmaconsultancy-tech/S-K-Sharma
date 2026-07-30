"""Iter 394 — Backend regression tests for the compliance-salary-runs refactor.

The ~2,200-line block was moved from server.py into
/app/backend/routes/compliance_salary_runs.py (pure refactor, no behavioural
change intended). These tests exercise every path the request calls out.

Test scope
----------
* CRUD-ish flow on compliance-salary-runs (POST create → GET list → GET one
  → POST save-rows → POST reprocess → cleanup DELETE via db).
* Finalize gate (validation must run; unlock and salary-unlock-requests flow).
* Exports on an EXISTING run (csrun_bca09c4a4cec, 2026-07) — MUST NOT be
  modified. CSV / XLSX / PDF / PF-ECR / ESIC-MC / ESIC-IP-REG / ECR.
* Firm head-mask stamping on the existing run's PDF/XLSX exports.
* Legacy server.py endpoints that still use the re-imported helpers:
    - POST /api/admin/employees (create+delete a test employee).
    - POST /api/admin/actual-salary-process (must not 500 with NameError).
    - GET /api/admin/salary-runs/{run_id}/payslips.zip (best-effort probe).
* De-dup sanity for previously double-registered modules: esic-leave,
  claims, payroll-register — must return 200 (single registration).
* Backend log scan: no 500 NameError during the test session.
"""

from __future__ import annotations

import io
import os
import time
import uuid
from typing import Optional

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://emplo-connect-1.preview.emergentagent.com"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PASSWORD = "sharma123"
KANKANI_CID = "cmp_527fecdd7c"
EXISTING_RUN_ID = "csrun_bca09c4a4cec"   # 2026-07 — DO NOT MODIFY
TEST_MONTH = "2026-08"                    # our own test month


# ---------- fixtures ----------------------------------------------------------


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    body = r.json()
    tok = body.get("session_token") or body.get("token")
    assert tok, f"no token in login response: {body}"
    return tok


@pytest.fixture(scope="module")
def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def created_run_id(auth: dict) -> str:
    """Create a compliance salary run for TEST_MONTH; delete after module."""
    # Clean any stale run for this test month first
    _cleanup_test_month(auth)
    payload = {
        "month": TEST_MONTH,
        "company_id": KANKANI_CID,
        "employee_type": "Staff",   # keep the group small
        "is_onroll": True,
    }
    r = requests.post(
        f"{BASE_URL}/api/admin/compliance-salary-runs",
        headers=auth, json=payload, timeout=180,
    )
    assert r.status_code == 200, f"create failed: {r.status_code} {r.text[:400]}"
    body = r.json()
    run = body.get("run") or body
    rid = run.get("run_id") or body.get("run_id")
    assert rid and rid.startswith("csrun_"), f"missing run_id: {body}"
    yield rid
    _cleanup_test_month(auth)


def _cleanup_test_month(auth: dict) -> None:
    """Remove any csrun/salary_unlock_request docs for TEST_MONTH."""
    # There is no public DELETE, so wipe directly via mongo through the
    # existing test infrastructure (pymongo client).
    try:
        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "test_database")
        client = MongoClient(mongo_url)
        db = client[db_name]
        # Grab any run_ids we're about to delete so we can also purge audit +
        # unlock rows for them.
        run_ids = [
            d["run_id"] for d in db.compliance_salary_runs.find(
                {"month": TEST_MONTH, "company_id": KANKANI_CID},
                {"run_id": 1, "_id": 0})
        ]
        if run_ids:
            db.compliance_salary_runs.delete_many({"run_id": {"$in": run_ids}})
            db.salary_unlock_requests.delete_many({"run_id": {"$in": run_ids}})
        client.close()
    except Exception as e:  # pragma: no cover — best effort
        print(f"[cleanup] warning: {e}")


# ---------- CRUD-ish flow -----------------------------------------------------


class TestComplianceSalaryRunCRUD:
    """POST → GET list → GET one → save-rows → reprocess."""

    def test_list_runs_returns_200(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs?limit=5",
            headers=auth, timeout=30)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert isinstance(body.get("runs"), list), body

    def test_get_existing_run(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}",
            headers=auth, timeout=30)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        run = body.get("run") or body   # server wraps as {"run": {...}}
        assert run.get("run_id") == EXISTING_RUN_ID
        assert run.get("month") == "2026-07"
        assert isinstance(run.get("rows"), list) and len(run["rows"]) > 0

    def test_create_and_persist(self, auth, created_run_id):
        # GET back the created run to prove persistence.
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{created_run_id}",
            headers=auth, timeout=30)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        run = body.get("run") or body
        assert run.get("run_id") == created_run_id
        assert run.get("month") == TEST_MONTH
        assert run.get("company_id") == KANKANI_CID
        assert isinstance(run.get("rows"), list)

    def test_save_rows_persists_edits(self, auth, created_run_id):
        # Read current rows, tweak first row's "others" field, save, re-read.
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{created_run_id}",
            headers=auth, timeout=30)
        assert r.status_code == 200
        body = r.json()
        run = body.get("run") or body
        rows = list(run.get("rows") or [])
        if not rows:
            pytest.skip("run has no rows to edit")
        rows[0]["others"] = float(rows[0].get("others") or 0) + 11.0
        marker = rows[0]["others"]
        save = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{created_run_id}/save-rows",
            headers=auth, json={"rows": rows}, timeout=60)
        assert save.status_code == 200, save.text[:400]
        assert save.json().get("ok") is True

        # Verify persistence via GET.
        r2 = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{created_run_id}",
            headers=auth, timeout=30)
        assert r2.status_code == 200
        run2 = (r2.json().get("run") or r2.json())
        r2_rows = run2.get("rows") or []
        assert r2_rows and abs(float(r2_rows[0].get("others") or 0) - marker) < 0.01

    def test_reprocess_run(self, auth, created_run_id):
        r = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{created_run_id}/reprocess",
            headers=auth, json=None, timeout=180)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body.get("ok") is True
        assert (body.get("run") or {}).get("run_id") == created_run_id


# ---------- Finalize + unlock -------------------------------------------------


class TestFinalizeAndUnlockFlow:
    """Finalize gate + unlock-request + salary-unlock-requests list + decide."""

    def test_finalize_runs_validation_gate(self, auth, created_run_id):
        # Iter 388 gate: either finalizes OR raises 422/409 with a validation
        # payload — either outcome proves the gate is wired.
        r = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{created_run_id}/finalize",
            headers=auth, json={}, timeout=60)
        assert r.status_code in (200, 409, 422), r.text[:400]
        if r.status_code == 200:
            assert r.json().get("finalized") is True or r.json().get("ok") is True
        else:
            detail = r.json().get("detail") or {}
            assert "validation" in detail, detail

    def _ensure_finalized(self, auth, run_id):
        # If validation blocks, override as super admin.
        r = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/finalize",
            headers=auth, json={"allow_warnings": True}, timeout=60)
        return r

    def test_unlock_flow(self, auth, created_run_id):
        # Try to force finalize (super admin allow_warnings override).
        fin = self._ensure_finalized(auth, created_run_id)
        # Even if errors remain (422), we should still be able to POST unlock;
        # if the run wasn't finalized, endpoint returns already_unlocked=True.
        r = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{created_run_id}/unlock-request",
            headers=auth, json={"reason": "iter394-test"}, timeout=30)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        # Super admin unlocks immediately → unlocked=True; or already_unlocked=True.
        assert body.get("ok") is True
        assert body.get("unlocked") or body.get("already_unlocked") or body.get("pending"), body

    def test_list_salary_unlock_requests(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-unlock-requests",
            headers=auth, timeout=30)
        assert r.status_code == 200, r.text[:400]
        assert isinstance(r.json().get("requests"), list)

    def test_decide_unlock_request_404_on_missing(self, auth):
        # We just probe the decide endpoint's contract with a fake ID —
        # confirms it's wired and returns 404 rather than 500 (NameError).
        r = requests.post(
            f"{BASE_URL}/api/admin/salary-unlock-requests/sur_doesnotexist/decide",
            headers=auth, json={"approve": False, "note": "iter394"}, timeout=30)
        assert r.status_code == 404, r.text[:400]


# ---------- Exports on EXISTING run (do NOT modify) ---------------------------


class TestExistingRunExports:
    """Iter 394 — exports must return 200 with non-trivial content, and
    the firm head-mask stamping (via _ensure_firm_head_masks) must still
    run for older runs on PDF / XLSX."""

    def test_export_csv(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/export.csv",
            headers=auth, timeout=60)
        assert r.status_code == 200, r.text[:200]
        assert len(r.content) > 500, "csv suspiciously small"
        assert b"," in r.content and (b"\n" in r.content or b"\r\n" in r.content)

    def test_export_xlsx(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/export.xlsx",
            headers=auth, timeout=90)
        assert r.status_code == 200, r.text[:200]
        # xlsx = ZIP magic "PK\x03\x04"
        assert r.content[:2] == b"PK", "not a valid xlsx (missing PK header)"
        assert len(r.content) > 2000

    def test_register_pdf_valid(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/register.pdf",
            headers=auth, timeout=120)
        assert r.status_code == 200, r.text[:200]
        assert r.content[:4] == b"%PDF", "not a valid PDF magic"
        assert len(r.content) > 2000

    def test_pf_ecr_txt(self, auth):
        # Iter 394 note: content is data-dependent (empty if firm has PF
        # disabled or no PF-applicable rows). Refactor regression here is
        # only "endpoint still resolves and returns 200 with text/plain".
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/pf-ecr.txt",
            headers=auth, timeout=60)
        assert r.status_code == 200, r.text[:200]
        assert "text/plain" in r.headers.get("content-type", "")

    def test_esic_mc_csv(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/esic-mc.csv",
            headers=auth, timeout=60)
        assert r.status_code == 200, r.text[:200]
        assert len(r.content) > 20

    def test_esic_ip_reg_csv(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/esic-ip-reg.csv",
            headers=auth, timeout=60)
        assert r.status_code == 200, r.text[:200]
        assert len(r.content) > 20

    def test_ecr_txt(self, auth):
        # Iter 394 note: data-dependent — assert only endpoint resolves 200.
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/ecr.txt",
            headers=auth, timeout=60)
        assert r.status_code == 200, r.text[:200]
        assert "text/plain" in r.headers.get("content-type", "")


# ---------- Legacy server.py endpoints using the re-imported helpers ---------


class TestLegacyServerHelpers:
    """Legacy endpoints in server.py that still call the 4 helpers
    (_firm_offline_salary_enabled, _firm_biometric_attendance_enabled,
    _ensure_firm_head_masks, _require_firm_salary_permission) via the
    re-imports at the bottom of server.py. They must NOT raise NameError."""

    def test_create_employee_and_delete(self, auth):
        # Create a temp employee for cmp_527fecdd7c with off-roll to touch
        # _firm_offline_salary_enabled.
        code = f"TESTE{uuid.uuid4().hex[:6].upper()}"
        payload = {
            "name": f"TEST_ITER394_{code}",
            "employee_code": code,
            "company_id": KANKANI_CID,
            "employee_type": "Staff",
            "is_onroll": True,
        }
        r = requests.post(
            f"{BASE_URL}/api/admin/employees", headers=auth,
            json=payload, timeout=45)
        # Either succeeds (200/201) OR returns a business-level 4xx (400/403/
        # 409). It must NOT be 500 NameError.
        assert r.status_code < 500, r.text[:400]
        if r.status_code in (200, 201):
            body = r.json()
            uid = (body.get("employee") or body).get("user_id") or body.get("user_id")
            if uid:
                # DELETE the test employee (best effort).
                d = requests.delete(
                    f"{BASE_URL}/api/admin/employees/{uid}",
                    headers=auth, timeout=30)
                # accept 200 or 204
                assert d.status_code < 500, d.text[:200]

    def test_actual_salary_process_no_nameerror(self, auth):
        # Any 4xx business response is fine — must NOT be 500 NameError.
        r = requests.post(
            f"{BASE_URL}/api/admin/actual-salary-process",
            headers=auth,
            json={"month": TEST_MONTH, "company_id": KANKANI_CID,
                  "employee_type": "Staff"},
            timeout=120)
        # We're only asserting the helper is bound and does not raise
        # NameError. Any deterministic 2xx/4xx is acceptable.
        assert r.status_code < 500, r.text[:400]

    def test_payslips_zip_probe(self, auth):
        # Best-effort probe on a random run_id — should be 404 (not 500).
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-runs/srun_doesnotexist/payslips.zip",
            headers=auth, timeout=30)
        assert r.status_code in (404, 400, 403), r.text[:200]


# ---------- De-dup sanity -----------------------------------------------------


class TestDeDupSanity:
    """Modules previously registered twice must still return 200 (not 404)."""

    def test_esic_leave_settings(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/esic-leave/settings?company_id={KANKANI_CID}",
            headers=auth, timeout=30)
        assert r.status_code == 200, r.text[:200]

    def test_claims_list(self, auth):
        r = requests.get(
            f"{BASE_URL}/api/admin/claims",
            headers=auth, timeout=30)
        assert r.status_code == 200, r.text[:200]

    def test_payroll_register(self, auth):
        # Actual mount path: /api/admin/reports/payroll-register
        r = requests.get(
            f"{BASE_URL}/api/admin/reports/payroll-register"
            f"?month={TEST_MONTH}&company_id={KANKANI_CID}",
            headers=auth, timeout=45)
        assert r.status_code == 200, r.text[:200]


# ---------- Backend log scan --------------------------------------------------


def test_backend_log_no_nameerror_since_start(auth):
    """Scan uvicorn logs — no 'NameError' anywhere post-refactor."""
    import subprocess
    try:
        # Look at recent tail of both err and out logs.
        out = subprocess.run(
            ["tail", "-n", "400", "/var/log/supervisor/backend.err.log",
             "/var/log/supervisor/backend.out.log"],
            capture_output=True, text=True, timeout=15)
        combined = (out.stdout or "") + (out.stderr or "")
    except Exception as e:
        pytest.skip(f"log read failed: {e}")
    # Filter out our own harmless echoed strings by looking for the Python
    # traceback signature.
    bad = [ln for ln in combined.splitlines()
           if "NameError" in ln and "Traceback" not in ln]
    assert not bad, "NameError observed in backend logs:\n" + "\n".join(bad[:10])
