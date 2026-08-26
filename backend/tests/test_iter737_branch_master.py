"""Iter 737 — BRANCH MASTER backend tests.

Covers /api/admin/branch-master/* (list/create/detail/patch/dashboard/
employees/employees-export/transfer/history/employee-history/documents)
+ DELETE-PROTECTION on /api/company/branches/{id}.
"""
import os
import sys
import base64
import pytest
import requests

sys.path.insert(0, os.path.dirname(__file__))
# reuse existing helper directly (login super admin via 2FA swap)
sys.path.insert(0, "/app/test_reports/helpers")
from login_super_admin import login as _super_login  # type: ignore

BASE = os.environ.get('EXPO_PUBLIC_BACKEND_URL',
                      'https://emplo-connect-1.preview.emergentagent.com').rstrip('/')
API = f"{BASE}/api"
CID = "cmp_527fecdd7c"

# --------------- fixtures ----------------
@pytest.fixture(scope="module")
def token():
    return _super_login()


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def created_ids():
    # tracked for cleanup at end of module
    return {"branches": [], "docs": [], "transfers": [], "user_ids_transferred": []}


# --------------- module cleanup ----------------
def teardown_module(module):  # noqa
    """Best-effort cleanup: remove test branches, transfer docs and doc records,
    and revert any transferred users' home_branch_id."""
    from pymongo import MongoClient
    from dotenv import load_dotenv
    load_dotenv('/app/backend/.env')
    db = MongoClient(os.environ['MONGO_URL'])[os.environ.get('DB_NAME', 'test_database')]
    tracked = getattr(module, "_created_ids", None) or {}
    for bid in tracked.get("branches", []):
        db.branches.delete_one({"branch_id": bid})
        db.branch_documents.delete_many({"branch_id": bid})
        db.branch_transfers.delete_many({"$or": [{"prev_branch_id": bid}, {"new_branch_id": bid}]})
        db.branch_audit.delete_many({"branch_id": bid})
    # revert real Kankani users transferred during tests
    for uid in tracked.get("user_ids_transferred", []):
        db.users.update_one({"user_id": uid}, {"$set": {"home_branch_id": None}})
        db.branch_transfers.delete_many({"user_id": uid})


# ============ BRANCH LIST ============
class TestBranchList:
    def test_list_ok(self, h, request):
        r = requests.get(f"{API}/admin/branch-master/list",
                         params={"company_id": CID}, headers=h, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "branches" in data and isinstance(data["branches"], list)
        assert "branch_types" in data
        # summary fields on each row
        for b in data["branches"]:
            for k in ("emp_count", "present_today", "absent_today", "active_employees"):
                assert k in b, f"missing {k}"
        request.config._branches = data["branches"]  # stash for later tests

    def test_list_filter_status_active(self, h):
        r = requests.get(f"{API}/admin/branch-master/list",
                         params={"company_id": CID, "status": "active"}, headers=h, timeout=30)
        assert r.status_code == 200
        assert all(bool(b.get("active", True)) for b in r.json()["branches"])

    def test_list_filter_search_nomatch(self, h):
        r = requests.get(f"{API}/admin/branch-master/list",
                         params={"company_id": CID,
                                 "search": "zzz_no_match_xyz123"},
                         headers=h, timeout=30)
        assert r.status_code == 200
        assert r.json()["branches"] == []


# ============ CREATE + VALIDATION ============
class TestBranchCreate:
    def test_create_ok_cross_midnight_default_true(self, h, created_ids):
        payload = {
            "company_id": CID, "name": "TEST_BR_Iter737_Main",
            "code": "TEST737A", "branch_type": "Branch",
            "city": "Bhilwara", "state": "Rajasthan", "pin_code": "311001",
            "office_lat": 25.35, "office_lng": 74.63,
        }
        r = requests.post(f"{API}/admin/branch-master/create",
                          json=payload, headers=h, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        b = body["branch"]
        assert b["name"] == "TEST_BR_Iter737_Main"
        assert b["code"] == "TEST737A"
        # cross_midnight default ON
        assert (b.get("attendance_config") or {}).get("cross_midnight") is True
        created_ids["branches"].append(b["branch_id"])

    def test_create_dup_code_409(self, h, created_ids):
        # first insert to occupy the code
        r1 = requests.post(f"{API}/admin/branch-master/create",
                           json={"company_id": CID, "name": "TEST_BR_dup_seed", "code": "TEST737B"},
                           headers=h, timeout=30)
        assert r1.status_code == 200
        created_ids["branches"].append(r1.json()["branch"]["branch_id"])
        # duplicate in same firm
        r2 = requests.post(f"{API}/admin/branch-master/create",
                           json={"company_id": CID, "name": "TEST_BR_dup2", "code": "TEST737B"},
                           headers=h, timeout=30)
        assert r2.status_code == 409, r2.text

    def test_create_bad_pin_400(self, h):
        r = requests.post(f"{API}/admin/branch-master/create",
                          json={"company_id": CID, "name": "TEST_BR_badpin", "pin_code": "12"},
                          headers=h, timeout=30)
        assert r.status_code == 400
        assert "6 digit" in r.json()["detail"].lower()

    def test_create_missing_name_400(self, h):
        r = requests.post(f"{API}/admin/branch-master/create",
                          json={"company_id": CID, "name": ""},
                          headers=h, timeout=30)
        assert r.status_code == 400

    def test_create_no_gps_ok(self, h, created_ids):
        r = requests.post(f"{API}/admin/branch-master/create",
                          json={"company_id": CID, "name": "TEST_BR_nogps",
                                "code": "TEST737C"},
                          headers=h, timeout=30)
        assert r.status_code == 200
        created_ids["branches"].append(r.json()["branch"]["branch_id"])


# ============ DETAIL + PATCH (nested merge + audit) ============
class TestBranchPatch:
    def test_patch_nested_merge_and_audit(self, h, created_ids):
        bid = created_ids["branches"][0]
        # 1st patch — set PF section
        r1 = requests.patch(f"{API}/admin/branch-master/{bid}",
                            json={"compliance_config": {"pf_applicable": True,
                                                        "pf_code": "PF-TEST"}},
                            headers=h, timeout=30)
        assert r1.status_code == 200
        # 2nd patch — set ESIC section (should MERGE, PF must remain)
        r2 = requests.patch(f"{API}/admin/branch-master/{bid}",
                            json={"compliance_config": {"esic_applicable": True}},
                            headers=h, timeout=30)
        assert r2.status_code == 200
        cc = r2.json()["branch"]["compliance_config"]
        assert cc.get("pf_applicable") is True, "PF setting was overwritten (merge fail)"
        assert cc.get("pf_code") == "PF-TEST"
        assert cc.get("esic_applicable") is True
        # audit trail written
        d = requests.get(f"{API}/admin/branch-master/{bid}", headers=h, timeout=30).json()
        assert len(d["audit"]) >= 2

    def test_patch_bad_pin_400(self, h, created_ids):
        bid = created_ids["branches"][0]
        r = requests.patch(f"{API}/admin/branch-master/{bid}",
                           json={"pin_code": "abcd"}, headers=h, timeout=30)
        assert r.status_code == 400


# ============ DASHBOARD ============
class TestBranchDashboard:
    def test_dashboard_ok(self, h, created_ids):
        bid = created_ids["branches"][0]
        r = requests.get(f"{API}/admin/branch-master/{bid}/dashboard",
                         headers=h, timeout=30)
        assert r.status_code == 200
        d = r.json()
        for k in ("total_employees", "active_employees", "present_today",
                  "absent_today", "on_leave", "pending_approvals",
                  "open_fnf", "new_joiners", "exits", "payroll_status"):
            assert k in d, f"missing {k}"


# ============ EMPLOYEES + EXPORT ============
class TestBranchEmployees:
    def test_empty_employees(self, h, created_ids):
        bid = created_ids["branches"][0]
        r = requests.get(f"{API}/admin/branch-master/{bid}/employees",
                         headers=h, timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert j["total"] == 0 and j["employees"] == []

    def test_employees_export_xlsx(self, h, created_ids):
        bid = created_ids["branches"][0]
        r = requests.get(f"{API}/admin/branch-master/{bid}/employees-export",
                         headers=h, timeout=30)
        assert r.status_code == 200
        # xlsx magic bytes = PK zip
        assert r.content[:2] == b"PK"


# ============ TRANSFER + HISTORY ============
class TestBranchTransfer:
    def test_transfer_needs_fields(self, h):
        r = requests.post(f"{API}/admin/branch-master/transfer",
                          json={"user_ids": []}, headers=h, timeout=30)
        assert r.status_code == 400

    def test_bulk_transfer_and_history(self, h, created_ids):
        # pick 2 real Kankani employees; they will be reverted in teardown
        from pymongo import MongoClient
        from dotenv import load_dotenv
        load_dotenv('/app/backend/.env')
        db = MongoClient(os.environ['MONGO_URL'])[os.environ.get('DB_NAME', 'test_database')]
        emps = list(db.users.find({"company_id": CID, "role": "employee"},
                                  {"_id": 0, "user_id": 1}).limit(2))
        assert len(emps) == 2, "need 2 employees for transfer test"
        uids = [e["user_id"] for e in emps]
        target = created_ids["branches"][0]
        r = requests.post(f"{API}/admin/branch-master/transfer",
                          json={"user_ids": uids, "new_branch_id": target,
                                "effective_date": "2020-01-01",
                                "reason": "TEST_iter737"},
                          headers=h, timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert j["created"] == 2
        created_ids["user_ids_transferred"].extend(uids)
        # history endpoint
        h_r = requests.get(f"{API}/admin/branch-master/{target}/history",
                           headers=h, timeout=30)
        assert h_r.status_code == 200
        hist = h_r.json()["history"]
        assert len(hist) >= 2
        assert any(x["direction"] == "IN" for x in hist)
        # employee-history timeline
        e_r = requests.get(f"{API}/admin/branch-master/employee-history/{uids[0]}",
                           headers=h, timeout=30)
        assert e_r.status_code == 200
        tl = e_r.json()["timeline"]
        # should have at least 2 entries (before + after transfer)
        assert len(tl) >= 2


# ============ DOCUMENTS ============
class TestBranchDocuments:
    def test_doc_bad_expiry_400(self, h, created_ids):
        bid = created_ids["branches"][0]
        r = requests.post(f"{API}/admin/branch-master/{bid}/documents",
                          json={"doc_type": "PF Registration",
                                "issue_date": "2020-01-01",
                                "expiry_date": "2019-01-01"},
                          headers=h, timeout=30)
        assert r.status_code == 400

    def test_doc_add_and_list_expiry_status(self, h, created_ids):
        bid = created_ids["branches"][0]
        # active
        r1 = requests.post(f"{API}/admin/branch-master/{bid}/documents",
                           json={"doc_type": "PF Registration", "doc_number": "TEST-PF-01",
                                 "issue_date": "2020-01-01", "expiry_date": "2099-01-01"},
                           headers=h, timeout=30)
        assert r1.status_code == 200
        # expired
        r2 = requests.post(f"{API}/admin/branch-master/{bid}/documents",
                           json={"doc_type": "ESIC Registration", "doc_number": "TEST-ESIC-01",
                                 "expiry_date": "2010-01-01"},
                           headers=h, timeout=30)
        assert r2.status_code == 200
        lst = requests.get(f"{API}/admin/branch-master/{bid}/documents",
                           headers=h, timeout=30).json()["documents"]
        by_num = {d["doc_number"]: d for d in lst if d.get("doc_number")}
        assert by_num["TEST-PF-01"]["expiry_status"] == "active"
        assert by_num["TEST-ESIC-01"]["expiry_status"] == "expired"

    def test_doc_replace_same_type(self, h, created_ids):
        bid = created_ids["branches"][0]
        # replacing existing PF doc
        r = requests.post(f"{API}/admin/branch-master/{bid}/documents",
                          json={"doc_type": "PF Registration", "doc_number": "TEST-PF-02",
                                "replace_same_type": True,
                                "expiry_date": "2099-06-01"},
                          headers=h, timeout=30)
        assert r.status_code == 200
        lst = requests.get(f"{API}/admin/branch-master/{bid}/documents",
                           headers=h, timeout=30).json()["documents"]
        # active list only shows non-deleted; but replaced ones may show status=replaced
        active_pf = [d for d in lst if d["doc_type"] == "PF Registration"
                     and d.get("status") == "active"]
        assert len(active_pf) == 1
        assert active_pf[0]["doc_number"] == "TEST-PF-02"

    def test_doc_soft_delete(self, h, created_ids):
        bid = created_ids["branches"][0]
        docs = requests.get(f"{API}/admin/branch-master/{bid}/documents",
                            headers=h, timeout=30).json()["documents"]
        assert docs, "need at least 1 doc to delete"
        did = docs[0]["doc_id"]
        r = requests.delete(f"{API}/admin/branch-master/documents/{did}",
                            headers=h, timeout=30)
        assert r.status_code == 200
        # not visible in list
        lst2 = requests.get(f"{API}/admin/branch-master/{bid}/documents",
                            headers=h, timeout=30).json()["documents"]
        assert not any(d["doc_id"] == did for d in lst2)


# ============ DELETE PROTECTION (existing endpoint) ============
class TestDeleteProtection:
    def test_delete_branch_with_transfers_returns_409(self, h, created_ids):
        # branch 0 has transfers now
        bid = created_ids["branches"][0]
        r = requests.delete(f"{API}/company/branches/{bid}", headers=h, timeout=30)
        assert r.status_code == 409
        assert "DEACTIVATE" in r.json()["detail"]

    def test_delete_branch_without_deps_ok(self, h, created_ids):
        # branch 2 (TEST737C) has no employees/attendance/transfers -> should hard-delete
        bid = created_ids["branches"][2]
        r = requests.delete(f"{API}/company/branches/{bid}", headers=h, timeout=30)
        assert r.status_code == 200
        # remove from cleanup tracker
        created_ids["branches"].remove(bid)


# ============ REGRESSION: legacy branches endpoint + related ============
class TestRegression:
    def test_legacy_list_branches(self, h):
        r = requests.get(f"{API}/company/branches",
                         params={"company_id": CID}, headers=h, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "branches" in data

    def test_legacy_create_and_patch_branch(self, h, created_ids):
        # Legacy BranchCreate schema requires name + office_lat + office_lng
        r = requests.post(f"{API}/company/branches",
                          json={"company_id": CID, "name": "TEST_LEGACY_Iter737",
                                "office_lat": 25.35, "office_lng": 74.63,
                                "geofence_radius_m": 200},
                          headers=h, timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()["branch"]
        created_ids["branches"].append(b["branch_id"])
        # legacy patch — only fields in BranchUpdate schema (name/address/lat/lng/radius/active)
        r2 = requests.patch(f"{API}/company/branches/{b['branch_id']}",
                            json={"address": "Bhilwara"}, headers=h, timeout=30)
        assert r2.status_code == 200
        assert r2.json()["branch"].get("address") == "Bhilwara"

    def test_compliance_salary_list(self, h):
        r = requests.get(f"{API}/admin/compliance-salary/runs",
                         params={"company_id": CID}, headers=h, timeout=30)
        # 200 or 404 both acceptable; must not 500
        assert r.status_code in (200, 404, 400), r.text

    def test_fnf_register(self, h):
        r = requests.get(f"{API}/admin/fnf/register",
                         params={"company_id": CID}, headers=h, timeout=30)
        assert r.status_code in (200, 404, 400), r.text


# ---- store created_ids on module for teardown ----
@pytest.fixture(scope="module", autouse=True)
def _stash(request, created_ids):
    yield
    setattr(sys.modules[__name__], "_created_ids", created_ids)
