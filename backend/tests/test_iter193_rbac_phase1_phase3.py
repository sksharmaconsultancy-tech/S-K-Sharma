"""Iter 193 — RBAC Phase 1 (Company Roles/Staff) + Phase 3 (Approval Workflow Engine).

Backend regression covering:
 - Company roles CRUD + catalog
 - Staff login normalization + permission gating
 - Staff CRUD (create/dup/weak-pw/reset/disable/delete)
 - Approval workflows (save/validate)
 - Advance -> pending_approval -> multi-level approve E2E
 - Reject/hold paths + maker-checker guard
 - Approval inbox counts + can_action flags
 - Cleanup of test-created data
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL") or "https://emplo-connect-1.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")

SUPER = {"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"}
STAFF_HR = {"email": "testhr@kankani.test", "password": "Hr@123456"}
KANKANI_ADMIN = {"email": "admin@kankani.local", "password": "Kankani@123"}
CID = "cmp_527fecdd7c"
SAMPLE_EMP = "user_83f0e0c387bb"


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text[:300]}"
    return r.json()["session_token"], r.json()["user"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# -------- fixtures --------
@pytest.fixture(scope="module")
def super_tok():
    tok, _ = _login(SUPER)
    return tok


@pytest.fixture(scope="module")
def staff_tok():
    tok, _ = _login(STAFF_HR)
    return tok


@pytest.fixture(scope="module")
def kankani_tok():
    tok, _ = _login(KANKANI_ADMIN)
    return tok


@pytest.fixture(scope="module")
def cleanup_state():
    # collect ids created during tests; module teardown will purge them
    return {"advance_ids": [], "request_ids": [], "staff_ids": [], "role_ids": []}


# =====================================================================
# PHASE 1: COMPANY ROLES
# =====================================================================
class TestPhase1CompanyRoles:
    def test_catalog_has_10_modules(self, super_tok):
        r = requests.get(f"{BASE_URL}/api/admin/company-roles/catalog", headers=_hdr(super_tok))
        assert r.status_code == 200
        cat = r.json()["catalog"]
        assert len(cat) == 10, f"expected 10 modules, got {len(cat)}"

    def test_list_roles_6_seeded_with_staff_counts(self, super_tok):
        r = requests.get(f"{BASE_URL}/api/admin/company-roles",
                         params={"company_id": CID}, headers=_hdr(super_tok))
        assert r.status_code == 200
        roles = r.json()["roles"]
        names = {x["name"] for x in roles}
        expected = {"HR Manager", "Payroll Manager", "Compliance Officer",
                    "Finance", "Attendance Manager", "Department Head"}
        assert expected.issubset(names), f"missing default roles: {expected - names}"
        hr = next(x for x in roles if x["name"] == "HR Manager")
        assert hr["staff_count"] >= 1, "HR Manager should have testhr assigned"

    def test_create_custom_role(self, super_tok, cleanup_state):
        payload = {"company_id": CID,
                   "name": f"TEST_Custom_{uuid.uuid4().hex[:6]}",
                   "permissions": ["employees:read"]}
        r = requests.post(f"{BASE_URL}/api/admin/company-roles",
                          json=payload, headers=_hdr(super_tok))
        assert r.status_code == 200, r.text
        rid = r.json()["role"]["role_id"]
        cleanup_state["role_ids"].append(rid)

    def test_patch_role_permissions(self, super_tok, cleanup_state):
        rid = cleanup_state["role_ids"][0]
        r = requests.patch(f"{BASE_URL}/api/admin/company-roles/{rid}",
                           json={"permissions": ["employees:read", "tickets:read"]},
                           headers=_hdr(super_tok))
        assert r.status_code == 200
        assert set(r.json()["role"]["permissions"]) == {"employees:read", "tickets:read"}

    def test_delete_blocked_if_staff_assigned(self, super_tok):
        r = requests.get(f"{BASE_URL}/api/admin/company-roles",
                         params={"company_id": CID}, headers=_hdr(super_tok))
        hr = next(x for x in r.json()["roles"] if x["name"] == "HR Manager")
        d = requests.delete(f"{BASE_URL}/api/admin/company-roles/{hr['role_id']}",
                            headers=_hdr(super_tok))
        assert d.status_code == 400, f"expected 400 blocked, got {d.status_code}"
        assert "staff" in d.text.lower()


# =====================================================================
# PHASE 1: STAFF LOGIN NORMALIZATION + PERMISSION GATING
# =====================================================================
class TestPhase1StaffLogin:
    def test_staff_login_normalized(self):
        r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                          json=STAFF_HR, timeout=20)
        assert r.status_code == 200
        u = r.json()["user"]
        assert u["role"] == "company_admin", f"role={u['role']}"
        assert u.get("is_company_staff") is True
        assert u.get("staff_role_name") == "HR Manager", f"staff_role_name={u.get('staff_role_name')}"
        assert u.get("company_id") == CID

    def test_me_endpoint_matches(self, staff_tok):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=_hdr(staff_tok))
        assert r.status_code == 200
        u = r.json().get("user") or r.json()
        assert u.get("is_company_staff") is True
        assert u.get("role") == "company_admin"
        assert u.get("staff_role_name") == "HR Manager"

    def test_staff_can_read_kyc_tracker(self, staff_tok):
        r = requests.get(f"{BASE_URL}/api/admin/kyc-tracker",
                         params={"company_id": CID}, headers=_hdr(staff_tok))
        assert r.status_code == 200, r.text[:200]
        # response could be dict with items or list
        data = r.json()
        items = data.get("items") or data.get("employees") or data if isinstance(data, list) else data.get("items", [])
        # loose check: it returned something without 403
        assert isinstance(data, (dict, list))

    def test_staff_denied_advances(self, staff_tok):
        r = requests.get(f"{BASE_URL}/api/admin/advances",
                         params={"company_id": CID}, headers=_hdr(staff_tok))
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"

    def test_staff_denied_company_roles(self, staff_tok):
        r = requests.get(f"{BASE_URL}/api/admin/company-roles",
                         params={"company_id": CID}, headers=_hdr(staff_tok))
        assert r.status_code == 403


# =====================================================================
# PHASE 1: STAFF CRUD
# =====================================================================
class TestPhase1StaffCRUD:
    def test_create_dup_weak_reset_disable_delete(self, super_tok, cleanup_state):
        # get HR role_id
        r = requests.get(f"{BASE_URL}/api/admin/company-roles",
                         params={"company_id": CID}, headers=_hdr(super_tok))
        hr = next(x for x in r.json()["roles"] if x["name"] == "HR Manager")
        email = f"TEST_staff_{uuid.uuid4().hex[:6]}@kankani.test"

        # create
        payload = {"company_id": CID, "name": "TEST Staff", "email": email,
                   "password": "Str0ng@Pass1", "role_id": hr["role_id"]}
        cr = requests.post(f"{BASE_URL}/api/admin/company-staff",
                           json=payload, headers=_hdr(super_tok))
        assert cr.status_code == 200, cr.text
        uid = cr.json()["staff"]["user_id"]
        cleanup_state["staff_ids"].append(uid)

        # dup -> 409
        dr = requests.post(f"{BASE_URL}/api/admin/company-staff",
                           json=payload, headers=_hdr(super_tok))
        assert dr.status_code == 409, f"dup expected 409, got {dr.status_code}"

        # weak pw
        weak = {**payload, "email": f"TEST_weak_{uuid.uuid4().hex[:6]}@kankani.test",
                "password": "abc"}
        wr = requests.post(f"{BASE_URL}/api/admin/company-staff",
                           json=weak, headers=_hdr(super_tok))
        assert wr.status_code == 400, f"weak pw expected 400, got {wr.status_code}"

        # login as new staff
        lr = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                           json={"email": email, "password": "Str0ng@Pass1"})
        assert lr.status_code == 200
        old_tok = lr.json()["session_token"]

        # reset password (should revoke sessions)
        rp = requests.patch(f"{BASE_URL}/api/admin/company-staff/{uid}",
                            json={"password": "N3wStr0ng@Pass"}, headers=_hdr(super_tok))
        assert rp.status_code == 200
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=_hdr(old_tok))
        assert me.status_code == 401, f"old session should be revoked, got {me.status_code}"

        # disable => blocks login
        dis = requests.patch(f"{BASE_URL}/api/admin/company-staff/{uid}",
                             json={"disabled": True}, headers=_hdr(super_tok))
        assert dis.status_code == 200
        blocked = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                                json={"email": email, "password": "N3wStr0ng@Pass"})
        assert blocked.status_code in (401, 403), f"disabled should block login, got {blocked.status_code}"

        # delete
        dl = requests.delete(f"{BASE_URL}/api/admin/company-staff/{uid}",
                             headers=_hdr(super_tok))
        assert dl.status_code == 200
        cleanup_state["staff_ids"].remove(uid)


# =====================================================================
# PHASE 3: APPROVAL WORKFLOW BUILDER
# =====================================================================
class TestPhase3Workflows:
    def test_list_workflows_shows_advance_L1_L2(self, super_tok):
        r = requests.get(f"{BASE_URL}/api/admin/approval-workflows",
                         params={"company_id": CID}, headers=_hdr(super_tok))
        assert r.status_code == 200
        d = r.json()
        wf = d["workflows"].get("advance")
        assert wf, "advance workflow missing"
        assert wf["enabled"] is True
        lvls = wf["levels"]
        assert len(lvls) == 2, f"expected 2 levels, got {len(lvls)}"
        assert lvls[0].get("role_name") == "HR Manager"
        assert lvls[1].get("approver_type") == "company_admin"

    def test_save_invalid_role_returns_404(self, super_tok):
        payload = {"company_id": CID, "module": "advance", "enabled": True,
                   "levels": [{"approver_type": "company_role", "role_id": "crole_bogus"}]}
        r = requests.post(f"{BASE_URL}/api/admin/approval-workflows",
                          json=payload, headers=_hdr(super_tok))
        assert r.status_code == 404, f"bad role expected 404, got {r.status_code}"

    def test_save_valid_workflow(self, super_tok):
        # refetch current and re-save (idempotent update) — ensures POST works
        r = requests.get(f"{BASE_URL}/api/admin/approval-workflows",
                         params={"company_id": CID}, headers=_hdr(super_tok))
        cur = r.json()["workflows"]["advance"]
        payload = {"company_id": CID, "module": "advance", "enabled": True,
                   "levels": [{"approver_type": l["approver_type"],
                               "role_id": l.get("role_id")} for l in cur["levels"]]}
        s = requests.post(f"{BASE_URL}/api/admin/approval-workflows",
                          json=payload, headers=_hdr(super_tok))
        assert s.status_code == 200, s.text


# =====================================================================
# PHASE 3: ADVANCE E2E APPROVAL FLOW
# =====================================================================
class TestPhase3AdvanceE2E:
    def _create_advance(self, tok, amount=5000, note="TEST_iter193"):
        payload = {
            "company_id": CID,
            "user_id": SAMPLE_EMP,
            "amount": amount,
            "recovery_type": "emi",
            "emi_amount": amount,  # single-shot EMI
            "installments": 1,
            "start_month": "2027-01",  # future => scheduled
            "advance_date": "2026-01-15",
            "reason": note,
        }
        r = requests.post(f"{BASE_URL}/api/admin/advances",
                          json=payload, headers=_hdr(tok))
        assert r.status_code in (200, 201), f"create advance failed: {r.status_code} {r.text[:300]}"
        return r.json()

    def test_approve_path_L1_HR_L2_CompanyAdmin(self, super_tok, staff_tok, kankani_tok, cleanup_state):
        # 1) super admin creates advance -> should go pending_approval
        created = self._create_advance(super_tok, amount=5000, note="TEST_iter193_approve")
        assert created.get("pending_approval") is True, f"expected pending_approval flag: {created}"
        adv = created.get("advance") or created
        adv_id = adv.get("advance_id")
        assert adv_id
        assert adv.get("status") == "pending_approval", f"status={adv.get('status')}"
        cleanup_state["advance_ids"].append(adv_id)

        # find approval request
        inbox = requests.get(f"{BASE_URL}/api/admin/approval-inbox",
                             params={"company_id": CID, "status": "pending"},
                             headers=_hdr(super_tok)).json()
        req = next((x for x in inbox["requests"] if x.get("record_id") == adv_id), None)
        assert req, "approval request not created"
        req_id = req["request_id"]
        cleanup_state["request_ids"].append(req_id)

        # 2) maker-checker: creator (super admin) tries to approve -> 403
        blk = requests.post(f"{BASE_URL}/api/admin/approval-requests/{req_id}/action",
                            json={"action": "approve"}, headers=_hdr(super_tok))
        assert blk.status_code == 403, f"maker-checker should block: {blk.status_code} {blk.text[:200]}"

        # 3) staff HR approves L1
        a1 = requests.post(f"{BASE_URL}/api/admin/approval-requests/{req_id}/action",
                           json={"action": "approve"}, headers=_hdr(staff_tok))
        assert a1.status_code == 200, a1.text
        assert a1.json()["request"]["current_level"] == 2
        assert a1.json()["request"]["status"] == "pending"

        # 4) company admin approves L2 (final)
        a2 = requests.post(f"{BASE_URL}/api/admin/approval-requests/{req_id}/action",
                           json={"action": "approve"}, headers=_hdr(kankani_tok))
        assert a2.status_code == 200, a2.text
        assert a2.json()["request"]["status"] == "approved"

        # 5) advance flipped to scheduled/active
        adv_after = requests.get(f"{BASE_URL}/api/admin/advances",
                                 params={"company_id": CID}, headers=_hdr(super_tok)).json()
        rows = adv_after.get("advances") or adv_after.get("items") or []
        this = next((x for x in rows if x.get("advance_id") == adv_id), None)
        assert this, "advance missing from listing"
        assert this.get("status") in ("scheduled", "active"), f"expected scheduled/active got {this.get('status')}"

    def test_reject_path_requires_remarks(self, super_tok, staff_tok, cleanup_state):
        created = self._create_advance(super_tok, amount=3000, note="TEST_iter193_reject")
        adv_id = (created.get("advance") or created).get("advance_id")
        cleanup_state["advance_ids"].append(adv_id)

        inbox = requests.get(f"{BASE_URL}/api/admin/approval-inbox",
                             params={"company_id": CID, "status": "pending"},
                             headers=_hdr(super_tok)).json()
        req = next(x for x in inbox["requests"] if x.get("record_id") == adv_id)
        req_id = req["request_id"]
        cleanup_state["request_ids"].append(req_id)

        # reject w/o remarks -> 400
        r1 = requests.post(f"{BASE_URL}/api/admin/approval-requests/{req_id}/action",
                           json={"action": "reject"}, headers=_hdr(staff_tok))
        assert r1.status_code == 400, f"reject no remarks expected 400, got {r1.status_code}"

        # reject w/ remarks
        r2 = requests.post(f"{BASE_URL}/api/admin/approval-requests/{req_id}/action",
                           json={"action": "reject", "remarks": "TEST reject"},
                           headers=_hdr(staff_tok))
        assert r2.status_code == 200
        assert r2.json()["request"]["status"] == "rejected"

        # advance status flipped to rejected
        adv_after = requests.get(f"{BASE_URL}/api/admin/advances",
                                 params={"company_id": CID}, headers=_hdr(super_tok)).json()
        rows = adv_after.get("advances") or adv_after.get("items") or []
        this = next(x for x in rows if x.get("advance_id") == adv_id)
        assert this.get("status") == "rejected"

    def test_hold_then_approve_continues(self, super_tok, staff_tok, kankani_tok, cleanup_state):
        created = self._create_advance(super_tok, amount=1500, note="TEST_iter193_hold")
        adv_id = (created.get("advance") or created).get("advance_id")
        cleanup_state["advance_ids"].append(adv_id)

        inbox = requests.get(f"{BASE_URL}/api/admin/approval-inbox",
                             params={"company_id": CID, "status": "pending"},
                             headers=_hdr(super_tok)).json()
        req = next(x for x in inbox["requests"] if x.get("record_id") == adv_id)
        req_id = req["request_id"]
        cleanup_state["request_ids"].append(req_id)

        # hold
        h = requests.post(f"{BASE_URL}/api/admin/approval-requests/{req_id}/action",
                          json={"action": "hold", "remarks": "checking"},
                          headers=_hdr(staff_tok))
        assert h.status_code == 200
        assert h.json()["request"]["status"] == "on_hold"

        # approve from on_hold at L1
        a1 = requests.post(f"{BASE_URL}/api/admin/approval-requests/{req_id}/action",
                           json={"action": "approve"}, headers=_hdr(staff_tok))
        assert a1.status_code == 200
        assert a1.json()["request"]["current_level"] == 2
        # L2 approve
        a2 = requests.post(f"{BASE_URL}/api/admin/approval-requests/{req_id}/action",
                           json={"action": "approve"}, headers=_hdr(kankani_tok))
        assert a2.status_code == 200
        assert a2.json()["request"]["status"] == "approved"


# =====================================================================
# PHASE 3: INBOX FLAGS
# =====================================================================
class TestPhase3Inbox:
    def test_counts_and_flags(self, super_tok, staff_tok):
        # super creates advance so requester != staff
        payload = {"company_id": CID, "user_id": SAMPLE_EMP, "amount": 2000,
                   "recovery_type": "emi", "emi_amount": 2000, "installments": 1,
                   "start_month": "2027-02",
                   "advance_date": "2026-01-15",
                   "reason": "TEST_iter193_inbox"}
        c = requests.post(f"{BASE_URL}/api/admin/advances",
                          json=payload, headers=_hdr(super_tok))
        assert c.status_code in (200, 201)
        adv_id = (c.json().get("advance") or c.json()).get("advance_id")

        # staff sees can_action=True (level 1 HR)
        staff_inbox = requests.get(f"{BASE_URL}/api/admin/approval-inbox",
                                   params={"company_id": CID, "status": "pending"},
                                   headers=_hdr(staff_tok)).json()
        assert "counts" in staff_inbox
        assert isinstance(staff_inbox["counts"].get("pending"), int)
        row = next((x for x in staff_inbox["requests"] if x.get("record_id") == adv_id), None)
        assert row, "row missing in staff inbox"
        assert row.get("can_action") is True, f"staff L1 should can_action: {row.get('can_action')}"
        assert row.get("pending_with") == "HR Manager"

        # super (requester) sees can_action=False due to maker-checker
        super_inbox = requests.get(f"{BASE_URL}/api/admin/approval-inbox",
                                   params={"company_id": CID, "status": "pending"},
                                   headers=_hdr(super_tok)).json()
        row2 = next(x for x in super_inbox["requests"] if x.get("record_id") == adv_id)
        assert row2.get("can_action") is False, "requester should NOT be able to action own request"

        # cleanup: reject to close
        req_id = row["request_id"]
        requests.post(f"{BASE_URL}/api/admin/approval-requests/{req_id}/action",
                      json={"action": "reject", "remarks": "test cleanup"},
                      headers=_hdr(staff_tok))
        # capture for teardown
        return adv_id, req_id


# =====================================================================
# CLEANUP
# =====================================================================
def test_zzz_cleanup(super_tok, cleanup_state):
    """Remove test-created advances/requests. Also clean any TEST_ advances."""
    # Delete all TEST_iter193 advances via /api/admin/advances/{id} DELETE
    adv_list = requests.get(f"{BASE_URL}/api/admin/advances",
                            params={"company_id": CID}, headers=_hdr(super_tok)).json()
    rows = adv_list.get("advances") or adv_list.get("items") or []
    ids_to_delete = set(cleanup_state.get("advance_ids", []))
    for r in rows:
        note = (r.get("reason") or "") + (r.get("note") or "")
        if "TEST_iter193" in note:
            ids_to_delete.add(r.get("advance_id"))
    deleted = 0
    for aid in ids_to_delete:
        d = requests.delete(f"{BASE_URL}/api/admin/advances/{aid}", headers=_hdr(super_tok))
        if d.status_code in (200, 204):
            deleted += 1
    print(f"[cleanup] advances deleted={deleted}")

    # Delete custom test roles
    for rid in cleanup_state.get("role_ids", []):
        requests.delete(f"{BASE_URL}/api/admin/company-roles/{rid}",
                        headers=_hdr(super_tok))

    # Delete leftover staff
    for uid in cleanup_state.get("staff_ids", []):
        requests.delete(f"{BASE_URL}/api/admin/company-staff/{uid}",
                        headers=_hdr(super_tok))
