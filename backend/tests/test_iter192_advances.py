"""Iter 192 — Employee Advance Management System backend regression.

Covers:
- Create advance validation
- Actual salary sync + idempotency
- Compliance run with 'both' source (mirror when net>0, capped when net=0)
- Actions: skip_month, pause/resume, EMI edit, recover_full fnf, delete-after-recovery blocked, waive requires remarks
- Aggregations: list summary, dashboard, reports (register/outstanding/monthly_recovery/recovery_history) + xlsx
- ESS: /me/advances via employee password login (fallback pin login)
- Cleanup ALL test-created records
"""
import os
import time
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
ADMIN_PW = "sharma123"
COMPANY_ID = "cmp_527fecdd7c"
MAHAVEER_UID = "user_83f0e0c387bb"
MONTH = "2026-07"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/admin-password-login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PW}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def H(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# Shared state between ordered tests
STATE = {}


def _seed_attendance(db):
    """Seed ~10 approved punch pairs in 2026-07 for MAHAVEER."""
    docs = []
    for d in range(1, 11):
        date = f"2026-07-{d:02d}"
        docs.append({
            "attendance_id": f"att_advtest_{uuid.uuid4().hex[:8]}",
            "user_id": MAHAVEER_UID, "company_id": COMPANY_ID,
            "date": date, "kind": "in",
            "at": f"{date}T03:30:00+00:00",
            "status": "approved", "source": "advance-test-seed",
        })
        docs.append({
            "attendance_id": f"att_advtest_{uuid.uuid4().hex[:8]}",
            "user_id": MAHAVEER_UID, "company_id": COMPANY_ID,
            "date": date, "kind": "out",
            "at": f"{date}T12:30:00+00:00",
            "status": "approved", "source": "advance-test-seed",
        })
    if docs:
        db.attendance.insert_many(docs)


# ---------- Tests ----------

class TestAdvanceCreate:
    def test_amount_zero_400(self, H):
        r = requests.post(f"{API}/admin/advances", headers=H, json={
            "user_id": MAHAVEER_UID, "advance_date": "2026-07-01",
            "amount": 0, "recovery_type": "emi", "emi_amount": 500,
            "start_month": MONTH, "recovery_source": "both",
        })
        assert r.status_code == 400, r.text

    def test_emi_gt_amount_400(self, H):
        r = requests.post(f"{API}/admin/advances", headers=H, json={
            "user_id": MAHAVEER_UID, "advance_date": "2026-07-01",
            "amount": 1000, "recovery_type": "emi", "emi_amount": 2000,
            "start_month": MONTH, "recovery_source": "both",
        })
        assert r.status_code == 400

    def test_create_ok(self, H):
        r = requests.post(f"{API}/admin/advances", headers=H, json={
            "user_id": MAHAVEER_UID, "advance_date": "2026-07-01",
            "advance_type": "Salary Advance",
            "amount": 24000, "recovery_type": "emi", "emi_amount": 2000,
            "start_month": MONTH, "recovery_source": "both",
            "priority": "normal", "payment_mode": "Bank",
        })
        assert r.status_code == 200, r.text
        adv = r.json()["advance"]
        assert adv["voucher_no"].startswith("ADV-")
        assert adv["installments"] == 12
        assert adv["end_month"] == "2027-06"
        assert adv["status"] in ("active", "scheduled")
        assert adv["remaining_balance"] == 24000
        STATE["advance_id"] = adv["advance_id"]
        STATE["voucher_no"] = adv["voucher_no"]


class TestActualSalarySync:
    def test_seed_attendance(self, db):
        # cleanup any pre-existing seed
        db.attendance.delete_many({"source": "advance-test-seed"})
        _seed_attendance(db)
        cnt = db.attendance.count_documents({"source": "advance-test-seed"})
        assert cnt == 20

    def test_actual_salary_run(self, H):
        # Ensure no stale run
        r = requests.post(f"{API}/admin/actual-salary-process", headers=H,
                          json={"month": MONTH, "company_id": COMPANY_ID}, timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        # Find MAHAVEER row
        rows = data.get("rows") or data.get("run", {}).get("rows") or []
        mrow = next((row for row in rows if row.get("user_id") == MAHAVEER_UID), None)
        assert mrow is not None, f"No MAHAVEER row in run: keys={list(data.keys())}"
        assert round(float(mrow.get("adv") or 0), 2) == 2000.0, f"adv={mrow.get('adv')}"
        assert round(float(mrow.get("advance_recovery") or 0), 2) == 2000.0
        STATE["actual_net_first"] = mrow.get("net_pay")

    def test_advance_recovered_2000(self, H):
        r = requests.get(f"{API}/admin/advances/{STATE['advance_id']}", headers=H)
        assert r.status_code == 200
        adv = r.json()["advance"]
        txns = r.json()["transactions"]
        assert round(float(adv["recovered_total"]), 2) == 2000.0
        assert round(float(adv["remaining_balance"]), 2) == 22000.0
        applied = [t for t in txns if t.get("balance_applied") and t.get("salary_month") == MONTH
                   and t.get("process_type") == "actual"]
        assert len(applied) == 1, f"expected 1 actual applied txn, got {len(applied)}"

    def test_actual_rerun_idempotent(self, H):
        r = requests.post(f"{API}/admin/actual-salary-process", headers=H,
                          json={"month": MONTH, "company_id": COMPANY_ID}, timeout=90)
        assert r.status_code == 200
        rows = r.json().get("rows") or r.json().get("run", {}).get("rows") or []
        mrow = next((row for row in rows if row.get("user_id") == MAHAVEER_UID), None)
        assert mrow is not None
        assert round(float(mrow.get("adv") or 0), 2) == 2000.0

        # Verify: still recovered 2000, remaining 22000, exactly one applied txn
        g = requests.get(f"{API}/admin/advances/{STATE['advance_id']}", headers=H)
        adv = g.json()["advance"]
        txns = g.json()["transactions"]
        assert round(float(adv["recovered_total"]), 2) == 2000.0
        assert round(float(adv["remaining_balance"]), 2) == 22000.0
        applied = [t for t in txns
                   if t.get("balance_applied") and t.get("salary_month") == MONTH
                   and t.get("process_type") == "actual"]
        assert len(applied) == 1


class TestComplianceMirror:
    def test_compliance_run(self, H, db):
        r = requests.post(f"{API}/admin/compliance-salary-runs", headers=H,
                          json={"month": MONTH, "company_id": COMPANY_ID}, timeout=90)
        assert r.status_code in (200, 201), r.text
        # Balance MUST NOT change from compliance run
        g = requests.get(f"{API}/admin/advances/{STATE['advance_id']}", headers=H)
        adv = g.json()["advance"]
        assert round(float(adv["remaining_balance"]), 2) == 22000.0
        assert round(float(adv["recovered_total"]), 2) == 2000.0

        # Mirror txn may or may not exist depending on compliance net > 0
        # But if it does, balance_applied must be False
        txns = g.json()["transactions"]
        compliance_txns = [t for t in txns if t.get("process_type") == "compliance"
                           and t.get("salary_month") == MONTH]
        for t in compliance_txns:
            assert t.get("balance_applied") is False, "Compliance mirror should never apply balance"


class TestActions:
    def test_skip_month_without_remarks_400(self, H):
        r = requests.post(f"{API}/admin/advances/{STATE['advance_id']}/action",
                          headers=H, json={"action": "skip_month", "month": "2026-08"})
        assert r.status_code == 400

    def test_skip_month_ok(self, H):
        r = requests.post(f"{API}/admin/advances/{STATE['advance_id']}/action",
                          headers=H, json={"action": "skip_month", "month": "2026-08",
                                           "remarks": "Diwali festival"})
        assert r.status_code == 200
        assert "2026-08" in r.json()["advance"]["skip_months"]

    def test_pause(self, H):
        r = requests.post(f"{API}/admin/advances/{STATE['advance_id']}/action",
                          headers=H, json={"action": "pause", "remarks": "audit hold"})
        assert r.status_code == 200
        assert r.json()["advance"]["status"] == "on_hold"

    def test_resume(self, H):
        r = requests.post(f"{API}/admin/advances/{STATE['advance_id']}/action",
                          headers=H, json={"action": "resume"})
        assert r.status_code == 200
        assert r.json()["advance"]["status"] == "active"

    def test_patch_emi_over_remaining_400(self, H):
        r = requests.patch(f"{API}/admin/advances/{STATE['advance_id']}",
                           headers=H, json={"emi_amount": 999999})
        assert r.status_code == 400

    def test_patch_emi_ok(self, H):
        r = requests.patch(f"{API}/admin/advances/{STATE['advance_id']}",
                           headers=H, json={"emi_amount": 2500})
        assert r.status_code == 200
        assert float(r.json()["advance"]["emi_amount"]) == 2500

    def test_delete_after_recovery_blocked(self, H):
        r = requests.delete(f"{API}/admin/advances/{STATE['advance_id']}", headers=H)
        assert r.status_code == 400

    def test_waive_requires_remarks(self, H):
        # spin up a fresh advance for waive test
        r = requests.post(f"{API}/admin/advances", headers=H, json={
            "user_id": MAHAVEER_UID, "advance_date": "2026-07-01",
            "amount": 500, "recovery_type": "single",
            "start_month": "2027-01", "recovery_source": "actual",
        })
        assert r.status_code == 200
        aid = r.json()["advance"]["advance_id"]
        STATE["waive_advance_id"] = aid
        r = requests.post(f"{API}/admin/advances/{aid}/action", headers=H,
                          json={"action": "waive"})
        assert r.status_code == 400
        r = requests.post(f"{API}/admin/advances/{aid}/action", headers=H,
                          json={"action": "waive", "remarks": "goodwill"})
        assert r.status_code == 200
        assert r.json()["advance"]["status"] == "waived"

    def test_recover_full_fnf(self, H):
        r = requests.post(f"{API}/admin/advances/{STATE['advance_id']}/action",
                          headers=H, json={"action": "recover_full", "mode": "fnf",
                                           "remarks": "FnF settlement"})
        assert r.status_code == 200
        adv = r.json()["advance"]
        assert adv["status"] == "closed"
        assert round(float(adv["remaining_balance"]), 2) == 0.0


class TestAggregations:
    def test_list_summary(self, H):
        r = requests.get(f"{API}/admin/advances?company_id={COMPANY_ID}", headers=H)
        assert r.status_code == 200
        js = r.json()
        assert "advances" in js and "summary" in js
        summary = js["summary"]
        for k in ("active", "on_hold", "closed", "outstanding", "recovered", "employees"):
            assert k in summary

    def test_dashboard(self, H):
        r = requests.get(f"{API}/admin/advances/dashboard?company_id={COMPANY_ID}", headers=H)
        assert r.status_code == 200
        js = r.json()
        for k in ("kpis", "trend", "by_department", "by_contractor", "by_type"):
            assert k in js

    @pytest.mark.parametrize("kind", ["register", "outstanding", "monthly_recovery", "recovery_history"])
    def test_reports_json(self, H, kind):
        params = f"?kind={kind}&company_id={COMPANY_ID}"
        if kind == "monthly_recovery":
            params += f"&month={MONTH}"
        r = requests.get(f"{API}/admin/advances/reports{params}", headers=H)
        assert r.status_code == 200, r.text
        js = r.json()
        assert "columns" in js and "rows" in js

    def test_report_xlsx(self, H):
        r = requests.get(f"{API}/admin/advances/reports?kind=register&company_id={COMPANY_ID}&format=xlsx",
                         headers=H)
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "spreadsheetml" in ct or "openxmlformats" in ct, f"content-type={ct}"


class TestESS:
    def test_my_advances(self, H):
        # Login employee TEST50 via password
        r = requests.post(f"{API}/auth/employee-password-login",
                          json={"login_id": "TEST50", "password": "123456"}, timeout=15)
        if r.status_code != 200:
            r = requests.post(f"{API}/auth/pin-login",
                              json={"login_id": "TEST50", "pin": "123456"}, timeout=15)
        assert r.status_code == 200, f"employee login failed: {r.status_code} {r.text}"
        tok = r.json().get("session_token") or r.json().get("token")
        assert tok, r.text
        emp_uid = r.json()["user"]["user_id"]
        STATE["test50_uid"] = emp_uid

        # Create an advance for TEST50 as admin
        cr = requests.post(f"{API}/admin/advances", headers=H, json={
            "user_id": emp_uid, "advance_date": "2026-07-01",
            "amount": 6000, "recovery_type": "emi", "emi_amount": 1000,
            "start_month": "2027-01", "recovery_source": "actual",
        })
        assert cr.status_code == 200, cr.text
        STATE["test50_advance_id"] = cr.json()["advance"]["advance_id"]

        # Employee ESS
        er = requests.get(f"{API}/me/advances",
                         headers={"Authorization": f"Bearer {tok}"})
        assert er.status_code == 200, er.text
        js = er.json()
        assert "advances" in js and "summary" in js
        assert len(js["advances"]) >= 1
        first = js["advances"][0]
        assert "schedule" in first
        assert "transactions" in first


# ---- Final cleanup (module teardown) ----
@pytest.fixture(scope="module", autouse=True)
def _final_cleanup(db, admin_token):
    yield
    H = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    # Delete advances + txns created here
    aids = [STATE.get("advance_id"), STATE.get("waive_advance_id"), STATE.get("test50_advance_id")]
    aids = [a for a in aids if a]
    if aids:
        db.advance_transactions.delete_many({"advance_id": {"$in": aids}})
        db.advances.delete_many({"advance_id": {"$in": aids}})
    # Also nuke anything left over from this test session with the seed marker
    db.attendance.delete_many({"source": "advance-test-seed"})
    # Salary runs for 2026-07 cmp_527fecdd7c
    db.salary_runs.delete_many({"month": MONTH, "company_id": COMPANY_ID})
    db.compliance_salary_runs.delete_many({"month": MONTH, "company_id": COMPANY_ID})
    # Reset voucher counter
    db.counters.delete_one({"_id": "advance_voucher"})
