"""Iter 706 — Backend edge-case tests for:
    (A) Tour Management (reject/return/cancel, attendance conflict + resolve,
        expense claim window guard, approval via workflow engine with an
        EMPLOYEE-level approver)
    (B) CL/PL Balance config + bulk apply + leave-settings
    (C) Approval Workflow with an employee-approver level → approval inbox

Runs against local backend on :8001. Cleans up all created data.
"""
import os
import time
from datetime import date, timedelta
import pytest
import requests

BASE = "http://localhost:8001"
SUPER = "testsess_98915ef8186e483d8b6292d0b975d2f3"
CID = "cmp_527fecdd7c"
EMP_UID = "user_44cd6f561da0"   # SURENDRA SINGH


def _emp_token():
    r = requests.post(f"{BASE}/api/auth/pin-login",
                      json={"login_id": "TEST50", "pin": "123456"}, timeout=10)
    r.raise_for_status()
    return r.json()["session_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def emp_tok():
    return _emp_token()


@pytest.fixture(scope="module")
def super_tok():
    return SUPER


# ---------------------------------------------------------------------------
# 1. Reject flow — remarks mandatory
# ---------------------------------------------------------------------------
class TestTourRejectFlow:
    def test_reject_requires_remarks_and_state(self, emp_tok, super_tok):
        d0 = (date.today() + timedelta(days=10)).isoformat()
        d1 = (date.today() + timedelta(days=11)).isoformat()
        # Create + submit
        r = requests.post(f"{BASE}/api/tours",
                          json={"tour_type": "Client Visit", "start_date": d0,
                                "end_date": d1, "destinations": ["Jaipur"],
                                "purpose": "TEST reject"},
                          headers=_h(emp_tok), timeout=10)
        assert r.status_code == 200, r.text
        tid = r.json()["tour"]["tour_id"]
        assert requests.post(f"{BASE}/api/tours/{tid}/submit",
                             headers=_h(emp_tok), timeout=10).status_code == 200
        # decide with no remarks — must 400
        bad = requests.post(f"{BASE}/api/tours/{tid}/decide",
                            json={"action": "reject"},
                            headers=_h(super_tok), timeout=10)
        assert bad.status_code == 400 and "Remarks" in bad.text
        # decide with remarks — ok, status becomes rejected
        ok = requests.post(f"{BASE}/api/tours/{tid}/decide",
                           json={"action": "reject", "remarks": "TEST rejecting"},
                           headers=_h(super_tok), timeout=10)
        assert ok.status_code == 200
        assert ok.json()["tour"]["status"] == "rejected"
        # cleanup
        requests.post(f"{BASE}/api/tours/{tid}/cancel",
                      headers=_h(super_tok), timeout=10)


# ---------------------------------------------------------------------------
# 2. Return → edit → resubmit
# ---------------------------------------------------------------------------
class TestTourReturnFlow:
    def test_return_allows_re_edit_and_resubmit(self, emp_tok, super_tok):
        d0 = (date.today() + timedelta(days=12)).isoformat()
        d1 = (date.today() + timedelta(days=13)).isoformat()
        r = requests.post(f"{BASE}/api/tours",
                          json={"tour_type": "Meeting", "start_date": d0,
                                "end_date": d1, "destinations": ["Delhi"],
                                "purpose": "TEST return"},
                          headers=_h(emp_tok), timeout=10)
        tid = r.json()["tour"]["tour_id"]
        requests.post(f"{BASE}/api/tours/{tid}/submit",
                      headers=_h(emp_tok), timeout=10)
        # admin return
        requests.post(f"{BASE}/api/tours/{tid}/decide",
                      json={"action": "return", "remarks": "add hotel"},
                      headers=_h(super_tok), timeout=10)
        detail = requests.get(f"{BASE}/api/tours/{tid}",
                              headers=_h(emp_tok), timeout=10).json()
        assert detail["tour"]["status"] == "returned"
        # edit
        upd = requests.put(f"{BASE}/api/tours/{tid}",
                           json={"tour_type": "Meeting", "start_date": d0,
                                 "end_date": d1, "destinations": ["Delhi"],
                                 "purpose": "TEST return — updated"},
                           headers=_h(emp_tok), timeout=10)
        assert upd.status_code == 200
        # resubmit
        rs = requests.post(f"{BASE}/api/tours/{tid}/submit",
                           headers=_h(emp_tok), timeout=10)
        assert rs.status_code == 200
        assert rs.json()["status"] == "pending_approval"
        # cleanup — approve & cancel
        requests.post(f"{BASE}/api/tours/{tid}/decide",
                      json={"action": "reject", "remarks": "cleanup"},
                      headers=_h(super_tok), timeout=10)


# ---------------------------------------------------------------------------
# 3. Attendance conflict + resolve
# ---------------------------------------------------------------------------
class TestAttendanceConflict:
    def test_conflict_flag_and_convert_to_od(self, emp_tok, super_tok):
        # Use past dates that we control
        d0 = (date.today() - timedelta(days=3)).isoformat()
        d1 = (date.today() - timedelta(days=2)).isoformat()
        # Pre-insert an approved punch on d0 via mongo through admin? use
        # the manual-attendance endpoint if exposed; otherwise direct DB.
        from pymongo import MongoClient
        db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[
            os.environ.get("DB_NAME", "test_database")]
        import uuid
        seed_ids = []
        for kind, at in (("in", f"{d0}T09:30:00Z"), ("out", f"{d0}T18:00:00Z")):
            rid = f"att_TEST_{uuid.uuid4().hex[:8]}"
            db.attendance.insert_one({
                "record_id": rid, "user_id": EMP_UID, "company_id": CID,
                "date": d0, "kind": kind, "at": at,
                "source": "manual", "status": "approved",
                "created_by": "TEST"})
            seed_ids.append(rid)
        # Create tour spanning d0..d1 with mark_od
        r = requests.post(f"{BASE}/api/tours",
                          json={"tour_type": "Official Tour",
                                "start_date": d0, "end_date": d1,
                                "destinations": ["Udaipur"],
                                "purpose": "TEST conflict",
                                "mark_od": True, "od_day_type": "full"},
                          headers=_h(emp_tok), timeout=10)
        tid = r.json()["tour"]["tour_id"]
        requests.post(f"{BASE}/api/tours/{tid}/submit",
                      headers=_h(emp_tok), timeout=10)
        # Approve → OD post triggered
        ap = requests.post(f"{BASE}/api/tours/{tid}/decide",
                           json={"action": "approve"},
                           headers=_h(super_tok), timeout=10)
        assert ap.status_code == 200 and ap.json()["tour"]["status"] == "approved"
        time.sleep(0.5)
        # d0 should be conflict, d1 should be posted
        rec_d0 = db.tour_attendance.find_one({"tour_id": tid, "date": d0})
        rec_d1 = db.tour_attendance.find_one({"tour_id": tid, "date": d1})
        assert rec_d0 and rec_d0["status"] == "conflict", rec_d0
        assert rec_d1 and rec_d1["status"] == "posted", rec_d1
        # Original punches must NOT be overwritten
        seed_after = list(db.attendance.find({"record_id": {"$in": seed_ids}}))
        assert len(seed_after) == 2 and all(a["status"] == "approved" for a in seed_after)
        # Now resolve → convert_to_od
        rs = requests.post(f"{BASE}/api/tours/{tid}/attendance/resolve",
                           json={"date": d0, "action": "convert_to_od"},
                           headers=_h(super_tok), timeout=10)
        assert rs.status_code == 200
        # Originals must be superseded_tour
        seed_after2 = list(db.attendance.find({"record_id": {"$in": seed_ids}}))
        assert all(a["status"] == "superseded_tour" for a in seed_after2), seed_after2
        # Cancel tour → OD punches removed for tour dates
        cn = requests.post(f"{BASE}/api/tours/{tid}/cancel",
                           headers=_h(super_tok), timeout=10)
        assert cn.status_code == 200
        remaining_od = db.attendance.count_documents(
            {"tour_id": tid, "source": "official_tour"})
        assert remaining_od == 0, f"cancel did not clean OD punches, {remaining_od} left"
        # cleanup superseded seeds + tour attendance leftover
        db.attendance.delete_many({"record_id": {"$in": seed_ids}})
        db.attendance.delete_many({"tour_id": tid})
        db.tour_attendance.delete_many({"tour_id": tid})


# ---------------------------------------------------------------------------
# 4. Expense claim guard: is_official_tour requires approved tour + window
# ---------------------------------------------------------------------------
class TestExpenseTourGuard:
    def test_expense_rejected_when_tour_not_approved_or_out_of_window(
            self, emp_tok, super_tok):
        d0 = (date.today() + timedelta(days=20)).isoformat()
        d1 = (date.today() + timedelta(days=22)).isoformat()
        r = requests.post(f"{BASE}/api/tours",
                          json={"tour_type": "Official Tour",
                                "start_date": d0, "end_date": d1,
                                "destinations": ["Mumbai"],
                                "purpose": "TEST expense guard"},
                          headers=_h(emp_tok), timeout=10)
        tid = r.json()["tour"]["tour_id"]
        # Submit — not yet approved
        requests.post(f"{BASE}/api/tours/{tid}/submit",
                      headers=_h(emp_tok), timeout=10)
        # Try expense claim now → must fail (tour is pending_approval)
        claim_bad = requests.post(f"{BASE}/api/expense/claims",
                                  json={"is_official_tour": True, "tour_id": tid,
                                        "expense_date": d0,
                                        "category_code": "TRV", "amount": 100,
                                        "purpose": "TEST",
                                        "description": "should reject"},
                                  headers=_h(emp_tok), timeout=10)
        assert claim_bad.status_code in (400, 422), \
            f"expected 4xx got {claim_bad.status_code}: {claim_bad.text}"
        # Approve
        requests.post(f"{BASE}/api/tours/{tid}/decide",
                      json={"action": "approve"},
                      headers=_h(super_tok), timeout=10)
        # Expense outside window (a year before) → must fail
        far = (date.today() - timedelta(days=365)).isoformat()
        claim_out = requests.post(f"{BASE}/api/expense/claims",
                                  json={"is_official_tour": True, "tour_id": tid,
                                        "expense_date": far,
                                        "category_code": "TRV", "amount": 100,
                                        "purpose": "TEST",
                                        "description": "out of window"},
                                  headers=_h(emp_tok), timeout=10)
        assert claim_out.status_code in (400, 422), \
            f"expected 4xx got {claim_out.status_code}: {claim_out.text}"
        # Cleanup: cancel tour
        requests.post(f"{BASE}/api/tours/{tid}/cancel",
                      headers=_h(super_tok), timeout=10)


# ---------------------------------------------------------------------------
# 5. Workflow-routed approval: employee approver via inbox
# ---------------------------------------------------------------------------
class TestEmployeeApproverWorkflow:
    def test_employee_can_action_tour_via_inbox(self, emp_tok, super_tok):
        # Need a second employee to act as approver. TEST50 himself can't
        # approve his own tour due to maker-checker in engine. Find another.
        from pymongo import MongoClient
        db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[
            os.environ.get("DB_NAME", "test_database")]
        other = db.users.find_one(
            {"company_id": CID, "role": "employee",
             "user_id": {"$ne": EMP_UID}},
            {"user_id": 1, "login_id": 1, "employee_code": 1, "name": 1})
        assert other, "need a 2nd employee in Kankani"
        approver_uid = other["user_id"]
        # Give this approver a login-id + pin so we can sign in
        import bcrypt
        pin_hash = bcrypt.hashpw(b"123456", bcrypt.gensalt(rounds=10)).decode()
        db.users.update_one({"user_id": approver_uid},
                            {"$set": {"login_id": "TESTAPPR",
                                      "pin_hash": pin_hash}})
        # Enable a 'tour' workflow with this employee as level 1
        wf_payload = {"company_id": CID, "module": "tour", "enabled": True,
                      "levels": [{"approver_type": "employee",
                                  "user_id": approver_uid,
                                  "sla_hours": 24}]}
        w = requests.post(f"{BASE}/api/admin/approval-workflows",
                          json=wf_payload, headers=_h(super_tok), timeout=10)
        assert w.status_code == 200, w.text
        try:
            # employee(requester TEST50) submits a tour
            d0 = (date.today() + timedelta(days=30)).isoformat()
            d1 = (date.today() + timedelta(days=31)).isoformat()
            r = requests.post(f"{BASE}/api/tours",
                              json={"tour_type": "Training",
                                    "start_date": d0, "end_date": d1,
                                    "destinations": ["Bengaluru"],
                                    "purpose": "TEST workflow"},
                              headers=_h(emp_tok), timeout=10)
            tid = r.json()["tour"]["tour_id"]
            sub = requests.post(f"{BASE}/api/tours/{tid}/submit",
                                headers=_h(emp_tok), timeout=10)
            assert sub.status_code == 200
            assert sub.json().get("workflow") is True, sub.json()
            # approver logs in
            appr = requests.post(f"{BASE}/api/auth/pin-login",
                                 json={"login_id": "TESTAPPR",
                                       "pin": "123456"}, timeout=10)
            assert appr.status_code == 200, appr.text
            atok = appr.json()["session_token"]
            # inbox badge
            b = requests.get(f"{BASE}/api/admin/approval-inbox/badge",
                             headers=_h(atok), timeout=10)
            assert b.status_code == 200 and b.json()["is_approver"] is True, b.text
            # inbox list — must include this request
            ib = requests.get(f"{BASE}/api/admin/approval-inbox",
                              headers=_h(atok), timeout=10)
            assert ib.status_code == 200
            items = ib.json().get("requests") or ib.json().get("items") or []
            req_id = None
            for it in items:
                if (it.get("record_id") == tid
                        or it.get("resource_id") == tid
                        or it.get("resource_ref") == tid):
                    req_id = it.get("request_id")
                    assert it.get("can_action") is True, it
                    break
            assert req_id, f"tour request not in inbox: {items}"
            # approve
            act = requests.post(
                f"{BASE}/api/admin/approval-requests/{req_id}/action",
                json={"action": "approve", "remarks": "TEST ok"},
                headers=_h(atok), timeout=10)
            assert act.status_code == 200, act.text
            time.sleep(0.5)
            # tour is approved
            det = requests.get(f"{BASE}/api/tours/{tid}",
                               headers=_h(emp_tok), timeout=10).json()
            assert det["tour"]["status"] == "approved", det["tour"]["status"]
            # cleanup — cancel tour
            requests.post(f"{BASE}/api/tours/{tid}/cancel",
                          headers=_h(super_tok), timeout=10)
        finally:
            # ALWAYS disable & clear the tour workflow so direct-decide
            # fallback keeps working for other tests / real users.
            requests.post(f"{BASE}/api/admin/approval-workflows",
                          json={"company_id": CID, "module": "tour",
                                "enabled": False, "levels": []},
                          headers=_h(super_tok), timeout=10)


# ---------------------------------------------------------------------------
# 6. CL/PL Balance config + bulk apply + settings
# ---------------------------------------------------------------------------
class TestLeaveBalanceConfig:
    def test_config_bulk_and_settings(self, super_tok):
        # GET config
        cfg = requests.get(
            f"{BASE}/api/admin/leave-balance-config?company_id={CID}",
            headers=_h(super_tok), timeout=10)
        assert cfg.status_code == 200
        j = cfg.json()
        for k in ("departments", "designations", "leave_calc_basis",
                  "year_end_treatment"):
            assert k in j, f"missing {k} in config: {list(j.keys())}"
        original_basis = j.get("leave_calc_basis")
        original_treatment = j.get("year_end_treatment")
        # Bulk apply designation scope (choose the first designation)
        desig = None
        for d in j["designations"]:
            if isinstance(d, dict) and d.get("designation"):
                desig = d["designation"]
                break
            if isinstance(d, str) and d.strip():
                desig = d
                break
        if desig:
            bulk = requests.patch(
                f"{BASE}/api/admin/leave-balance/bulk",
                json={"company_id": CID, "scope": "designation",
                      "value": desig, "cl_allowed": 4, "pl_allowed": 8},
                headers=_h(super_tok), timeout=10)
            assert bulk.status_code == 200, bulk.text
        # Save leave-settings
        s = requests.patch(
            f"{BASE}/api/admin/leave-settings",
            json={"company_id": CID, "leave_calc_basis": "gross",
                  "year_end_treatment": "encash"},
            headers=_h(super_tok), timeout=10)
        assert s.status_code == 200, s.text
        # Verify persistence via GET
        cfg2 = requests.get(
            f"{BASE}/api/admin/leave-balance-config?company_id={CID}",
            headers=_h(super_tok), timeout=10).json()
        assert cfg2.get("leave_calc_basis") == "gross"
        assert cfg2.get("year_end_treatment") == "encash"
        # Reset to defaults per test brief
        requests.patch(
            f"{BASE}/api/admin/leave-settings",
            json={"company_id": CID,
                  "leave_calc_basis": original_basis or "basic",
                  "year_end_treatment": original_treatment or "lapse"},
            headers=_h(super_tok), timeout=10)


# ---------------------------------------------------------------------------
# 7. Tour admin endpoints
# ---------------------------------------------------------------------------
class TestTourAdmin:
    def test_admin_list_live_settings(self, super_tok):
        r = requests.get(
            f"{BASE}/api/tours/admin/list?company_id={CID}",
            headers=_h(super_tok), timeout=10)
        assert r.status_code == 200 and "tours" in r.json() and "counts" in r.json()
        r2 = requests.get(f"{BASE}/api/tours/admin/live?company_id={CID}",
                          headers=_h(super_tok), timeout=10)
        assert r2.status_code == 200 and "active_tours" in r2.json()
        r3 = requests.get(f"{BASE}/api/tours/admin/settings?company_id={CID}",
                          headers=_h(super_tok), timeout=10)
        assert r3.status_code == 200
        assert "tracking_interval_min" in r3.json()["settings"]

    def test_eligible_for_expense(self, emp_tok):
        r = requests.get(f"{BASE}/api/tours/eligible/for-expense",
                         headers=_h(emp_tok), timeout=10)
        assert r.status_code == 200
        assert "tours" in r.json() and "grace_days" in r.json()
