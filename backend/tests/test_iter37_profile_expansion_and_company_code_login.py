"""Iteration 37 — Employee profile-edit expansion + company_code admin login.

Covers:
  • POST /api/me/profile-edit — new fields (designation, present/permanent
    address, family_members). Empty-name rows stripped, invalid DOB → 400,
    identical list does not create a delta, role/company gating.
  • GET  /api/me/profile-edit — returns new fields in ``changes``.
  • GET  /api/admin/profile-edits — employee doc includes new fields.
  • PATCH /api/admin/profile-edits/{id} — approved requests apply new
    fields; family_members list replaces existing; empty list clears it.
  • PATCH /api/admin/user-role — admin direct edit (skips approval) writes
    new fields; company_admin cross-company blocked; super_admin unrestricted.
  • POST /api/auth/admin-pin-login — new company_code flow (case-insensitive,
    picks earliest-created admin with pin_hash, wrong-PIN counter + lockout,
    unknown code → 404, company w/o active PIN admin → 403). Legacy
    identifier path and identifier+company_code precedence preserved.

All rows seeded with IT37_* prefix and torn down at module scope.
"""
import os
import uuid
from datetime import datetime, timezone

import bcrypt
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
_mc = MongoClient(MONGO_URL)
db = _mc[DB_NAME]

RUN_ID = f"IT37{uuid.uuid4().hex[:6]}"


def _hdr(t: str) -> dict:
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt(rounds=4)).decode()


def _mk_session(user_id: str) -> str:
    tok = f"tok_{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": tok,
        "user_id": user_id,
        "auth_method": "test_seed_iter37",
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc).replace(year=2099),
    })
    return tok


def _phone(n: int) -> str:
    # deterministic per run to avoid collisions with other iterations
    stamp = RUN_ID[-5:]
    return f"+9199{stamp}{n:03d}"


@pytest.fixture(scope="module")
def ctx():
    now = datetime.now(timezone.utc).isoformat()
    prefix_a = f"IT37A{RUN_ID[-2:]}"[:8].upper()
    prefix_b = f"IT37B{RUN_ID[-2:]}"[:8].upper()
    prefix_c = f"IT37C{RUN_ID[-2:]}"[:8].upper()  # for "no active-PIN admin"
    cid_a = f"cmp_it37a_{uuid.uuid4().hex[:8]}"
    cid_b = f"cmp_it37b_{uuid.uuid4().hex[:8]}"
    cid_c = f"cmp_it37c_{uuid.uuid4().hex[:8]}"

    db.companies.insert_many([
        {"company_id": cid_a, "company_code": prefix_a, "name": f"IT37_CoA_{RUN_ID}",
         "created_at": now},
        {"company_id": cid_b, "company_code": prefix_b, "name": f"IT37_CoB_{RUN_ID}",
         "created_at": now},
        {"company_id": cid_c, "company_code": prefix_c, "name": f"IT37_CoC_{RUN_ID}",
         "created_at": now},
    ])

    # Employee in A (via signup so PIN flow works)
    phone_a = _phone(1)
    r = requests.post(f"{API}/auth/employee-signup", json={
        "phone": phone_a, "pin": "918273", "company_code": prefix_a,
        "name": f"IT37_EmpA_{RUN_ID}", "father_name": "OldFatherA",
        "dob": "1990-01-15", "doj": "2020-06-01",
    }, timeout=20)
    assert r.status_code == 200, r.text
    uid_a = r.json()["user_id"]
    # Seed baseline profile so delta detection works
    db.users.update_one({"user_id": uid_a}, {"$set": {
        "father_name": "OldFatherA",
        "dob": "1990-01-15",
        "doj": "2020-06-01",
        "designation": "Clerk",
        "present_address": "House 1, Old Town",
        "permanent_address": "House 1, Old Town",
        "family_members": [
            {"name": "Original Spouse", "relation": "spouse", "dob": "1992-02-02",
             "occupation": None, "contact": None},
        ],
        "approval_status": "approved",
    }})
    r = requests.post(f"{API}/auth/pin-login", json={"phone": phone_a, "pin": "918273"}, timeout=20)
    assert r.status_code == 200, r.text
    tok_a = r.json()["session_token"]

    # Company Admin A — primary (earliest created, has pin_hash)
    adm_a_uid = f"usr_it37_adm_a_{uuid.uuid4().hex[:8]}"
    adm_a_pin = "471928"
    db.users.insert_one({
        "user_id": adm_a_uid,
        "role": "company_admin",
        "company_id": cid_a,
        "name": f"IT37_AdmA_Primary_{RUN_ID}",
        "email": f"it37_adma_{RUN_ID.lower()}@test.local",
        "pin_hash": _hash_pin(adm_a_pin),
        "pin_must_change": False,
        "pin_fail_count": 0,
        "pin_locked_until": None,
        "approval_status": "approved",
        "onboarded": True,
        "created_at": datetime(2021, 1, 1, tzinfo=timezone.utc),  # earliest
    })
    adm_a_tok = _mk_session(adm_a_uid)

    # Company Admin A — secondary (later, ALSO has pin_hash — must NOT be picked)
    adm_a2_uid = f"usr_it37_adm_a2_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "user_id": adm_a2_uid,
        "role": "company_admin",
        "company_id": cid_a,
        "name": f"IT37_AdmA_Secondary_{RUN_ID}",
        "email": f"it37_adma2_{RUN_ID.lower()}@test.local",
        "pin_hash": _hash_pin("999888"),
        "pin_fail_count": 0,
        "approval_status": "approved",
        "onboarded": True,
        "created_at": datetime(2024, 6, 1, tzinfo=timezone.utc),  # later
    })

    # Company B — admin (later, but only admin so wins for its own code)
    adm_b_uid = f"usr_it37_adm_b_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "user_id": adm_b_uid,
        "role": "company_admin",
        "company_id": cid_b,
        "name": f"IT37_AdmB_{RUN_ID}",
        "email": f"it37_admb_{RUN_ID.lower()}@test.local",
        "pin_hash": _hash_pin("246810"),
        "pin_fail_count": 0,
        "approval_status": "approved",
        "onboarded": True,
        "created_at": now,
    })

    # Employee in B (no auth needed — used for cross-company checks)
    uid_b = f"usr_it37_emp_b_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "user_id": uid_b,
        "role": "employee",
        "company_id": cid_b,
        "name": f"IT37_EmpB_{RUN_ID}",
        "approval_status": "approved",
        "created_at": now,
    })

    # Company C — admin with NO pin_hash (should trigger 403 on company_code login)
    adm_c_uid = f"usr_it37_adm_c_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "user_id": adm_c_uid,
        "role": "company_admin",
        "company_id": cid_c,
        "name": f"IT37_AdmC_NoPin_{RUN_ID}",
        "email": f"it37_admc_{RUN_ID.lower()}@test.local",
        "approval_status": "approved",
        "onboarded": True,
        "created_at": now,
    })

    # Super admin (throwaway — do NOT touch real sksharmaconsultancy)
    sadm_uid = f"usr_it37_super_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "user_id": sadm_uid,
        "role": "super_admin",
        "company_id": None,
        "name": f"IT37_Super_{RUN_ID}",
        "email": f"it37_super_{RUN_ID.lower()}@test.local",
        "approval_status": "approved",
        "onboarded": True,
        "created_at": now,
    })
    sadm_tok = _mk_session(sadm_uid)

    data = {
        "prefix_a": prefix_a, "prefix_b": prefix_b, "prefix_c": prefix_c,
        "cid_a": cid_a, "cid_b": cid_b, "cid_c": cid_c,
        "uid_a": uid_a, "uid_b": uid_b, "tok_a": tok_a,
        "adm_a_uid": adm_a_uid, "adm_a2_uid": adm_a2_uid, "adm_a_pin": adm_a_pin,
        "adm_a_tok": adm_a_tok, "adm_a_email": f"it37_adma_{RUN_ID.lower()}@test.local",
        "adm_b_uid": adm_b_uid, "adm_c_uid": adm_c_uid,
        "sadm_uid": sadm_uid, "sadm_tok": sadm_tok,
    }
    yield data

    # Cleanup — remove all IT37_* rows
    uids = [uid_a, uid_b, adm_a_uid, adm_a2_uid, adm_b_uid, adm_c_uid, sadm_uid]
    db.profile_edit_requests.delete_many({"user_id": {"$in": uids}})
    db.user_sessions.delete_many({"user_id": {"$in": uids}})
    db.users.delete_many({"user_id": {"$in": uids}})
    db.companies.delete_many({"company_id": {"$in": [cid_a, cid_b, cid_c]}})


# -----------------------------------------------------------------------------
# Feature 1: profile-edit new fields
# -----------------------------------------------------------------------------
class TestProfileEditNewFields:
    def test_role_gate_company_admin_forbidden(self, ctx):
        r = requests.post(f"{API}/me/profile-edit", headers=_hdr(ctx["adm_a_tok"]),
                          json={"designation": "Manager"}, timeout=20)
        assert r.status_code == 403, r.text

    def test_super_admin_forbidden(self, ctx):
        r = requests.post(f"{API}/me/profile-edit", headers=_hdr(ctx["sadm_tok"]),
                          json={"designation": "Whatever"}, timeout=20)
        assert r.status_code == 403, r.text

    def test_empty_family_name_rows_stripped(self, ctx):
        # Two rows submitted — one has blank name → server drops it, one valid
        r = requests.post(f"{API}/me/profile-edit", headers=_hdr(ctx["tok_a"]), json={
            "family_members": [
                {"name": "  ", "relation": "brother"},
                {"name": "Ravi", "relation": "brother", "dob": "1995-05-05"},
            ],
        }, timeout=20)
        assert r.status_code == 200, r.text
        req = r.json()["request"]
        fam = req["changes"].get("family_members")
        assert isinstance(fam, list)
        assert len(fam) == 1
        assert fam[0]["name"] == "Ravi"
        assert fam[0]["dob"] == "1995-05-05"

    def test_invalid_family_dob_400(self, ctx):
        r = requests.post(f"{API}/me/profile-edit", headers=_hdr(ctx["tok_a"]), json={
            "family_members": [
                {"name": "BadDob", "relation": "child", "dob": "05/05/2010"},
            ],
        }, timeout=20)
        assert r.status_code == 400, r.text
        assert "yyyy-mm-dd" in r.text.lower() or "invalid" in r.text.lower()

    def test_nothing_to_update_when_family_identical(self, ctx):
        # Clear any pending request first so this doesn't just replace
        db.profile_edit_requests.delete_many({"user_id": ctx["uid_a"], "status": "pending"})
        # Submit the exact same family list as what's on the user
        r = requests.post(f"{API}/me/profile-edit", headers=_hdr(ctx["tok_a"]), json={
            "family_members": [
                {"name": "Original Spouse", "relation": "spouse", "dob": "1992-02-02"},
            ],
        }, timeout=20)
        assert r.status_code == 400, r.text
        assert "nothing" in r.text.lower() or "match" in r.text.lower()

    def test_submit_full_expansion_produces_delta(self, ctx):
        db.profile_edit_requests.delete_many({"user_id": ctx["uid_a"], "status": "pending"})
        r = requests.post(f"{API}/me/profile-edit", headers=_hdr(ctx["tok_a"]), json={
            "designation": "Senior Accountant",
            "present_address": "House 42, New Colony, Delhi",
            "permanent_address": "Village Rampur, UP",
            "family_members": [
                {"name": "Sita", "relation": "spouse", "dob": "1993-04-04",
                 "occupation": "Teacher", "contact": "+919812345678"},
                {"name": "Aarav", "relation": "son", "dob": "2016-07-07"},
            ],
            "note": "Please approve address change",
        }, timeout=20)
        assert r.status_code == 200, r.text
        req = r.json()["request"]
        changes = req["changes"]
        assert changes["designation"] == "Senior Accountant"
        assert changes["present_address"] == "House 42, New Colony, Delhi"
        assert changes["permanent_address"] == "Village Rampur, UP"
        fam = changes["family_members"]
        assert len(fam) == 2
        names = {m["name"] for m in fam}
        assert names == {"Sita", "Aarav"}
        # note stored
        assert req.get("note") == "Please approve address change"

    def test_get_my_profile_edit_returns_new_fields(self, ctx):
        r = requests.get(f"{API}/me/profile-edit", headers=_hdr(ctx["tok_a"]), timeout=20)
        assert r.status_code == 200, r.text
        req = r.json()["request"]
        assert req is not None
        assert "designation" in req["changes"]
        assert "family_members" in req["changes"]


# -----------------------------------------------------------------------------
# Feature 2: admin review — BEFORE→AFTER via employee doc + approval applies new fields
# -----------------------------------------------------------------------------
class TestAdminProfileEditReview:
    def test_admin_list_includes_new_fields_on_employee_doc(self, ctx):
        r = requests.get(f"{API}/admin/profile-edits?status=pending",
                         headers=_hdr(ctx["adm_a_tok"]), timeout=20)
        assert r.status_code == 200, r.text
        items = r.json()["requests"]
        target = next(it for it in items if it["user_id"] == ctx["uid_a"])
        emp = target["employee"]
        assert emp is not None
        for k in ("designation", "present_address", "permanent_address", "family_members"):
            assert k in emp, f"employee doc missing {k}"
        # Sanity: BEFORE values should still be the seeded originals
        assert emp["designation"] == "Clerk"
        assert emp["permanent_address"] == "House 1, Old Town"
        assert isinstance(emp["family_members"], list)
        assert emp["family_members"][0]["name"] == "Original Spouse"

    def test_approve_applies_new_fields(self, ctx):
        pending = db.profile_edit_requests.find_one(
            {"user_id": ctx["uid_a"], "status": "pending"}
        )
        assert pending is not None
        r = requests.patch(
            f"{API}/admin/profile-edits/{pending['request_id']}",
            headers=_hdr(ctx["adm_a_tok"]),
            json={"status": "approved"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json()["request"]["status"] == "approved"
        # Verify user doc updated
        u = db.users.find_one({"user_id": ctx["uid_a"]}, {"_id": 0})
        assert u["designation"] == "Senior Accountant"
        assert u["present_address"] == "House 42, New Colony, Delhi"
        assert u["permanent_address"] == "Village Rampur, UP"
        fam = u["family_members"]
        assert isinstance(fam, list) and len(fam) == 2
        assert {m["name"] for m in fam} == {"Sita", "Aarav"}

    def test_approve_empty_family_list_clears(self, ctx):
        # Submit a new request that clears family_members (empty list)
        db.profile_edit_requests.delete_many({"user_id": ctx["uid_a"], "status": "pending"})
        r = requests.post(f"{API}/me/profile-edit", headers=_hdr(ctx["tok_a"]), json={
            "family_members": [],
        }, timeout=20)
        assert r.status_code == 200, r.text
        req_id = r.json()["request"]["request_id"]
        # Verify delta captured the empty list
        stored = db.profile_edit_requests.find_one({"request_id": req_id})
        assert stored["changes"].get("family_members") == []

        r = requests.patch(
            f"{API}/admin/profile-edits/{req_id}",
            headers=_hdr(ctx["adm_a_tok"]),
            json={"status": "approved"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        u = db.users.find_one({"user_id": ctx["uid_a"]}, {"_id": 0})
        assert u.get("family_members") == []


# -----------------------------------------------------------------------------
# Feature 3: PATCH /admin/user-role direct edits new fields (no approval)
# -----------------------------------------------------------------------------
class TestUserRoleDirectEdit:
    def test_company_admin_edits_own_company_new_fields(self, ctx):
        r = requests.patch(f"{API}/admin/user-role", headers=_hdr(ctx["adm_a_tok"]), json={
            "user_id": ctx["uid_a"],
            "name": f"IT37_EmpA_Renamed_{RUN_ID}",
            "designation": "Head Accountant",
            "present_address": "Direct-edit present address",
            "permanent_address": "Direct-edit permanent address",
            "family_members": [
                {"name": "Direct Family Member", "relation": "mother", "dob": "1965-11-11"},
            ],
        }, timeout=20)
        assert r.status_code == 200, r.text
        # Verify persisted immediately
        u = db.users.find_one({"user_id": ctx["uid_a"]}, {"_id": 0})
        assert u["name"] == f"IT37_EmpA_Renamed_{RUN_ID}"
        assert u["designation"] == "Head Accountant"
        assert u["present_address"] == "Direct-edit present address"
        assert u["permanent_address"] == "Direct-edit permanent address"
        assert len(u["family_members"]) == 1
        assert u["family_members"][0]["name"] == "Direct Family Member"

    def test_company_admin_cross_company_forbidden(self, ctx):
        # Admin A tries to edit employee in company B
        r = requests.patch(f"{API}/admin/user-role", headers=_hdr(ctx["adm_a_tok"]), json={
            "user_id": ctx["uid_b"],
            "designation": "Should-Not-Apply",
        }, timeout=20)
        assert r.status_code == 403, r.text

    def test_super_admin_can_edit_any_company(self, ctx):
        r = requests.patch(f"{API}/admin/user-role", headers=_hdr(ctx["sadm_tok"]), json={
            "user_id": ctx["uid_b"],
            "designation": "Cross-Company Set By Super",
            "present_address": "Set by super admin",
        }, timeout=20)
        assert r.status_code == 200, r.text
        u = db.users.find_one({"user_id": ctx["uid_b"]}, {"_id": 0})
        assert u["designation"] == "Cross-Company Set By Super"
        assert u["present_address"] == "Set by super admin"

    def test_user_role_invalid_family_dob_400(self, ctx):
        r = requests.patch(f"{API}/admin/user-role", headers=_hdr(ctx["sadm_tok"]), json={
            "user_id": ctx["uid_a"],
            "family_members": [{"name": "BadDob", "dob": "31-12-2000"}],
        }, timeout=20)
        assert r.status_code == 400, r.text


# -----------------------------------------------------------------------------
# Feature 4: admin-pin-login — company_code path
# -----------------------------------------------------------------------------
class TestAdminPinLoginCompanyCode:
    def test_company_code_uppercase_success(self, ctx):
        r = requests.post(f"{API}/auth/admin-pin-login", json={
            "company_code": ctx["prefix_a"], "pin": ctx["adm_a_pin"],
        }, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        # Must resolve to PRIMARY (earliest-created) admin, not secondary
        assert body["user"]["user_id"] == ctx["adm_a_uid"]
        assert body["user"]["role"] == "company_admin"
        assert body["session_token"]

    def test_company_code_lowercase_success(self, ctx):
        # Case-insensitive: backend uppercases on the way in
        r = requests.post(f"{API}/auth/admin-pin-login", json={
            "company_code": ctx["prefix_a"].lower(),
            "pin": ctx["adm_a_pin"],
        }, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["user_id"] == ctx["adm_a_uid"]

    def test_company_code_unknown_404(self, ctx):
        r = requests.post(f"{API}/auth/admin-pin-login", json={
            "company_code": "NOSUCH99", "pin": "123123",
        }, timeout=20)
        assert r.status_code == 404, r.text

    def test_company_code_no_active_pin_admin_403(self, ctx):
        # Company C has an admin without pin_hash → 403 with clear message
        r = requests.post(f"{API}/auth/admin-pin-login", json={
            "company_code": ctx["prefix_c"], "pin": "654321",
        }, timeout=20)
        assert r.status_code == 403, r.text
        assert "pin" in r.text.lower()

    def test_wrong_pin_increments_fails_and_locks_at_5(self, ctx):
        # Reset fail count so we know exactly what happens
        db.users.update_one({"user_id": ctx["adm_b_uid"]},
                            {"$set": {"pin_fail_count": 0, "pin_locked_until": None}})
        # 4 wrong attempts → 401 each, counter increments
        for i in range(4):
            r = requests.post(f"{API}/auth/admin-pin-login", json={
                "company_code": ctx["prefix_b"], "pin": "000001",
            }, timeout=20)
            assert r.status_code == 401, f"attempt {i+1}: {r.status_code} {r.text}"
        u = db.users.find_one({"user_id": ctx["adm_b_uid"]}, {"_id": 0})
        assert u.get("pin_fail_count") == 4, "counter=%s" % u.get("pin_fail_count")

        # 5th wrong attempt → locks
        r = requests.post(f"{API}/auth/admin-pin-login", json={
            "company_code": ctx["prefix_b"], "pin": "000001",
        }, timeout=20)
        assert r.status_code == 401, r.text
        u = db.users.find_one({"user_id": ctx["adm_b_uid"]}, {"_id": 0})
        assert u.get("pin_locked_until") is not None
        # counter should reset to 0 after lock is applied
        assert u.get("pin_fail_count") == 0

        # 6th attempt should be blocked with 429
        r = requests.post(f"{API}/auth/admin-pin-login", json={
            "company_code": ctx["prefix_b"], "pin": "246810",  # even correct pin
        }, timeout=20)
        assert r.status_code == 429, r.text

        # Clean up lockout for future tests
        db.users.update_one({"user_id": ctx["adm_b_uid"]},
                            {"$set": {"pin_fail_count": 0, "pin_locked_until": None}})


# -----------------------------------------------------------------------------
# Feature 5: admin-pin-login — legacy identifier path & precedence
# -----------------------------------------------------------------------------
class TestAdminPinLoginLegacy:
    def test_identifier_email_still_works(self, ctx):
        r = requests.post(f"{API}/auth/admin-pin-login", json={
            "identifier": ctx["adm_a_email"], "pin": ctx["adm_a_pin"],
        }, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["user_id"] == ctx["adm_a_uid"]

    def test_neither_identifier_nor_code_400(self, ctx):
        r = requests.post(f"{API}/auth/admin-pin-login", json={"pin": ctx["adm_a_pin"]},
                          timeout=20)
        assert r.status_code == 400, r.text

    def test_both_identifier_and_company_code_identifier_wins(self, ctx):
        # identifier belongs to Admin A; company_code points to Company B.
        # Server must use identifier first → login as Admin A (not B).
        r = requests.post(f"{API}/auth/admin-pin-login", json={
            "identifier": ctx["adm_a_email"],
            "company_code": ctx["prefix_b"],
            "pin": ctx["adm_a_pin"],
        }, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["user_id"] == ctx["adm_a_uid"]

    def test_pin_wrong_length_400(self, ctx):
        r = requests.post(f"{API}/auth/admin-pin-login", json={
            "company_code": ctx["prefix_a"], "pin": "12",
        }, timeout=20)
        assert r.status_code == 400, r.text
