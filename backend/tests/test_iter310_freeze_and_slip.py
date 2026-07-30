"""Iter 310 backend tests — Freeze Salary + Employee Detail Slip.

Run:
  pytest /app/backend/tests/test_iter310_freeze_and_slip.py -v \
      --junitxml=/app/test_reports/pytest/iter310.xml
"""
import base64
import io
import os
import time
from datetime import datetime

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_BACKEND_URL",
                          "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
COMPANY_ID = "cmp_527fecdd7c"     # Kankani Enterprises
MONTH = "2026-06"                 # June 2026 (30 days)
CODE_DAILY = "50"                 # SURENDRA SINGH, daily 745
CODE_MONTHLY = "212"              # MADAN KEER, monthly 39000
USER_ID_DAILY = "user_44cd6f561da0"   # per prompt

# Mongo direct — used for OT branch toggling + verification
_mongo = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
_db = _mongo[os.environ.get("DB_NAME", "test_database")]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(f"{API}/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com",
                            "password": "sharma123"}, timeout=15)
    assert r.status_code == 200, f"admin login failed {r.status_code}: {r.text[:200]}"
    data = r.json()
    tok = data.get("token") or data.get("session_token")
    assert tok, f"no token in response: {data}"
    return tok


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _csv_b64(rows: list) -> str:
    """rows: list of dicts with Emp Code / Present Days / Gross Earning."""
    lines = ["Emp Code,Present Days,Gross Earning"]
    for r in rows:
        lines.append(f"{r['code']},{r['pd']},{r['ge']}")
    return base64.b64encode("\n".join(lines).encode()).decode()


def _upload(hdr, rows) -> dict:
    payload = {"company_id": COMPANY_ID, "month": MONTH,
               "filename": "iter310_test.csv",
               "content_base64": _csv_b64(rows)}
    r = requests.post(f"{API}/admin/compliance-import/upload",
                      json=payload, headers=hdr, timeout=30)
    assert r.status_code == 200, f"import upload failed {r.status_code}: {r.text[:300]}"
    j = r.json()
    assert j.get("matched") >= 1, f"no matched rows: {j}"
    return j


def _process(hdr) -> dict:
    r = requests.post(f"{API}/admin/compliance-salary-runs",
                      json={"month": MONTH, "company_id": COMPANY_ID,
                            "use_imported_sheet": True},
                      headers=hdr, timeout=60)
    assert r.status_code == 200, f"process failed {r.status_code}: {r.text[:400]}"
    return r.json()["run"]


def _row(run, code):
    for r in run.get("rows") or []:
        if str(r.get("employee_code")) == str(code):
            return r
    return None


# ---------------------------------------------------------------------------
# Freeze Salary
# ---------------------------------------------------------------------------
class TestFreezeHappyPath:
    """OT-allowed branch: Overtime allocation."""

    def test_1_upload_and_process(self, hdr):
        # daily 745 * 26 pd = 19370 calc; import 25000 → diff 5630
        # monthly 39000 / 30 * 26 = 33800 calc; import 40000 → diff 6200
        _upload(hdr, [
            {"code": CODE_DAILY,   "pd": 26, "ge": 25000},
            {"code": CODE_MONTHLY, "pd": 26, "ge": 40000},
        ])
        # Ensure ot_allowed=true (Kankani default per prompt)
        _db.firm_masters.update_one(
            {"company_id": COMPANY_ID},
            {"$set": {"salary_process.ot_allowed": True,
                      "salary_process.online_salary": True}},
        )
        run = _process(hdr)

        assert run.get("frozen") is True, "run.frozen missing"
        assert run.get("frozen_at"), "frozen_at missing"
        snap_id = run.get("freeze_snapshot_id")
        assert snap_id and snap_id.startswith("frz_"), f"snapshot id bad: {snap_id}"

        for code in (CODE_DAILY, CODE_MONTHLY):
            r = _row(run, code)
            assert r, f"row for {code} not found"
            assert r["imported_gross"] > 0
            assert r["calculated_gross"] > 0
            assert r["difference"] > 0, f"expected positive diff for {code}: {r}"
            assert r["difference_allocation_head"] == "Overtime", \
                f"expected Overtime, got {r['difference_allocation_head']}"
            assert abs(r["gross_paid"] - r["imported_gross"]) < 0.01
            assert abs(r["net"] - (r["gross_paid"]
                                   - float(r.get("total_deduction") or 0))) < 0.01

        # totals include imported/calculated/difference
        t = run.get("totals") or {}
        for k in ("imported_gross", "calculated_gross", "difference"):
            assert k in t, f"totals missing {k}"
            assert t[k] > 0, f"totals.{k} not >0: {t[k]}"

        # snapshot persisted
        snap = _db.freeze_salary_snapshots.find_one({"snapshot_id": snap_id})
        assert snap, f"snapshot {snap_id} not persisted"
        assert snap.get("run_id") == run["run_id"]
        snap_codes = {str(r.get("employee_code")) for r in (snap.get("rows") or [])}
        assert CODE_DAILY in snap_codes and CODE_MONTHLY in snap_codes


class TestFreezeOtOffBranch:
    """When ot_allowed=false, diff must go to 'others' (Other Allowances)."""

    def test_ot_off_allocates_to_others(self, hdr):
        _upload(hdr, [{"code": CODE_DAILY, "pd": 26, "ge": 25000}])
        _db.firm_masters.update_one(
            {"company_id": COMPANY_ID},
            {"$set": {"salary_process.ot_allowed": False}},
        )
        try:
            run = _process(hdr)
            r = _row(run, CODE_DAILY)
            assert r, "row for code 50 not found"
            assert r["difference"] > 0
            assert r["difference_allocation_head"] == "Other Allowances", \
                f"expected 'Other Allowances', got {r['difference_allocation_head']}"
            assert r["others"] >= r["difference"] - 0.01, \
                f"others not raised: others={r['others']} diff={r['difference']}"
            assert abs(r["gross_paid"] - r["imported_gross"]) < 0.01
            # ot_pay should not have been increased
            assert (r.get("ot_pay") or 0) == 0 or \
                (r.get("ot_pay") or 0) < r["difference"], \
                f"ot_pay unexpectedly increased: {r.get('ot_pay')}"
        finally:
            # RESTORE ot_allowed=true (per prompt)
            _db.firm_masters.update_one(
                {"company_id": COMPANY_ID},
                {"$set": {"salary_process.ot_allowed": True}},
            )


class TestFreezeNegativeDiff:
    """Iter 339b/340/344 — imported gross BELOW the sheet-days calc no
    longer produces a negative Difference: Compliance Days are auto-derived
    (shrunk, floored) from the imported gross, the small positive remainder
    routes to OT/Other and the FINAL gross equals the freeze gross exactly."""

    def test_negative_diff_non_destructive(self, hdr):
        # daily 745*26 = 19370; import 10000 → days shrink to match 10000
        _upload(hdr, [{"code": CODE_DAILY, "pd": 26, "ge": 10000}])
        # OT restore already done
        _db.firm_masters.update_one(
            {"company_id": COMPANY_ID},
            {"$set": {"salary_process.ot_allowed": True}},
        )
        run = _process(hdr)
        r = _row(run, CODE_DAILY)
        assert r, "row for code 50 not found"
        # days-shrink guarantees the calc never overshoots the import
        assert r["difference"] >= 0, \
            f"expected non-negative diff (days auto-shrink), got {r['difference']}"
        # any remainder is allocated to OT (firm OT allowed)
        if r["difference"] >= 1:
            assert r["difference_allocation_head"] == "Overtime", \
                f"expected Overtime head, got {r['difference_allocation_head']}"
        # FINAL gross must equal the imported freeze gross exactly (Iter 344)
        assert abs(r["gross_paid"] - r["imported_gross"]) < 0.01, \
            f"gross must equal import: gp={r['gross_paid']} imp={r['imported_gross']}"


# ---------------------------------------------------------------------------
# Employee Detail Slip
# ---------------------------------------------------------------------------
class TestDetailSlip:
    def test_list_employees_sorted_numeric(self, hdr):
        r = requests.get(
            f"{API}/admin/employee-detail-slip/employees",
            params={"company_id": COMPANY_ID}, headers=hdr, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        j = r.json()
        emps = j.get("employees") or []
        assert len(emps) >= 100, f"expected ~127, got {len(emps)}"
        # verify numeric sort of codes
        codes = [str(e.get("employee_code") or "") for e in emps if
                 str(e.get("employee_code") or "").isdigit()]
        assert codes == sorted(codes, key=int), "employees not sorted by numeric code"

    def test_detail_sections(self, hdr):
        r = requests.get(f"{API}/admin/employee-detail-slip/{USER_ID_DAILY}",
                         headers=hdr, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        j = r.json()
        titles = [s["title"] for s in j.get("sections") or []]
        for want in ("Personal Information", "Employment Details",
                     "Statutory / KYC", "Bank Details",
                     "Salary Information", "Additional Details"):
            assert want in titles, f"section missing: {want}"
        assert "attendance_fytd" in j and "leaves_fytd" in j
        pc = j.get("profile_completion")
        assert isinstance(pc, int) and 0 <= pc <= 100, f"profile_completion={pc}"
        # Mother Name was a Phase-2 placeholder at Iter 310; it is now a
        # real editable field — just assert it is present in the section.
        personal = next(s for s in j["sections"]
                        if s["title"] == "Personal Information")
        assert any(f["label"] == "Mother Name" for f in personal["fields"]), \
            "Mother Name field missing from Personal Information"

    def test_pdf_export(self, hdr):
        r = requests.get(
            f"{API}/admin/employee-detail-slip/{USER_ID_DAILY}/slip.pdf",
            headers={"Authorization": hdr["Authorization"]}, timeout=45)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        assert r.headers.get("content-type", "").startswith("application/pdf"), \
            f"content-type={r.headers.get('content-type')}"
        assert r.content[:4] == b"%PDF", "not a valid PDF (missing %PDF header)"
        assert len(r.content) > 2000, f"pdf too small: {len(r.content)}"

    def test_xlsx_export(self, hdr):
        r = requests.get(
            f"{API}/admin/employee-detail-slip/{USER_ID_DAILY}/slip.xlsx",
            headers={"Authorization": hdr["Authorization"]}, timeout=45)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        ct = r.headers.get("content-type", "")
        assert "spreadsheetml" in ct or "excel" in ct, f"content-type={ct}"
        # xlsx are zip archives; PK\x03\x04 magic
        assert r.content[:2] == b"PK", "not a valid xlsx (missing PK header)"

    def test_email_send(self, hdr):
        r = requests.post(
            f"{API}/admin/employee-detail-slip/{USER_ID_DAILY}/email",
            json={"to": "delivered@resend.dev"},
            headers=hdr, timeout=60)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        j = r.json()
        assert j.get("ok") is True, f"ok not true: {j}"

    def test_email_invalid_recipient(self, hdr):
        r = requests.post(
            f"{API}/admin/employee-detail-slip/{USER_ID_DAILY}/email",
            json={"to": "not-an-email"},
            headers=hdr, timeout=15)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
def test_zz_cleanup(hdr):
    """Delete draft runs, import entries, freeze snapshots created above."""
    # 1) Draft runs for the test month + firm
    dr = _db.compliance_salary_runs.delete_many({
        "month": MONTH, "company_id": COMPANY_ID,
        "finalized": {"$ne": True},
    })
    # 2) Import entries
    di = _db.compliance_import_entries.delete_many({
        "company_id": COMPANY_ID, "month": MONTH})
    # 3) Freeze snapshots for the test month
    ds = _db.freeze_salary_snapshots.delete_many({
        "company_id": COMPANY_ID, "month": MONTH})
    # 4) Ensure ot_allowed restored
    _db.firm_masters.update_one(
        {"company_id": COMPANY_ID},
        {"$set": {"salary_process.ot_allowed": True}})
    print(f"cleanup: runs={dr.deleted_count} imports={di.deleted_count} "
          f"snaps={ds.deleted_count}")
