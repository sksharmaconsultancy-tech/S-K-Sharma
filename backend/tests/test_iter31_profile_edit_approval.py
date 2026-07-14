"""Iteration 31 — Profile edit + company_admin approval workflow.

Endpoints under test:
  POST   /api/me/profile-edit                   (employee only)
  GET    /api/me/profile-edit
  GET    /api/admin/profile-edits?status=pending
  PATCH  /api/admin/profile-edits/{request_id}
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
_mc = MongoClient(MONGO_URL)
db = _mc[DB_NAME]

RUN_ID = f"IT31{uuid.uuid4().hex[:6]}"
PHONE_STAMP = f"{int(uuid.uuid4().hex[:6], 16) % 100000:05d}"


def _hdr(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _phone(n: int) -> str:
    return f"+919{PHONE_STAMP}{n:04d}"


def _mk_session(user_id: str, role: str) -> str:
    tok = f"tok_{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": tok,
        "user_id": user_id,
        "role": role,
        "auth_method": "test_seed_iter31",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": datetime.now(timezone.utc).replace(year=2099).isoformat(),
    })
    return tok


@pytest.fixture(scope="module")
def scenario():
    """Seed: two companies (A,B), one employee in A + one in B + one company_admin
    for A + one super_admin session (created via db seed - not touching hard-coded
    super_admin_email account)."""
    prefix_a = f"IA{RUN_ID[-3:]}".upper()[:8]
    prefix_b = f"IB{RUN_ID[-3:]}".upper()[:8]
    cid_a = f"cmp_{uuid.uuid4().hex[:10]}"
    cid_b = f"cmp_{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()
    db.companies.insert_many([
        {"company_id": cid_a, "company_code": prefix_a, "name": f"{RUN_ID} CoA",
         "created_at": now},
        {"company_id": cid_b, "company_code": prefix_b, "name": f"{RUN_ID} CoB",
         "created_at": now},
    ])

    # Employee in A - use signup path
    phone_a = _phone(1)
    r = requests.post(f"{API}/auth/employee-signup", json={
        "phone": phone_a, "pin": "111222", "company_code": prefix_a,
        "name": f"{RUN_ID} EmpA", "father_name": "OldFatherA",
        "dob": "1990-01-15", "doj": "2020-06-01",
    })
    assert r.status_code == 200, r.text
    uid_a = r.json()["user_id"]
    # Also stamp father/dob/doj since signup body does not persist them
    db.users.update_one({"user_id": uid_a}, {"$set": {
        "father_name": "OldFatherA", "dob": "1990-01-15", "doj": "2020-06-01",
        "approval_status": "approved",
    }})
    r = requests.post(f"{API}/auth/pin-login", json={"phone": phone_a, "pin": "111222"})
    assert r.status_code == 200, r.text
    tok_a = r.json()["session_token"]

    # Employee in B
    phone_b = _phone(2)
    r = requests.post(f"{API}/auth/employee-signup", json={
        "phone": phone_b, "pin": "111222", "company_code": prefix_b,
        "name": f"{RUN_ID} EmpB", "father_name": "OldFatherB",
        "dob": "1991-02-20", "doj": "2021-06-01",
    })
    assert r.status_code == 200, r.text
    uid_b = r.json()["user_id"]
    db.users.update_one({"user_id": uid_b}, {"$set": {
        "father_name": "OldFatherB", "dob": "1991-02-20", "doj": "2021-06-01",
    }})
    db.users.update_one({"user_id": uid_b}, {"$set": {"approval_status": "approved"}})
    r = requests.post(f"{API}/auth/pin-login", json={"phone": phone_b, "pin": "111222"})
    assert r.status_code == 200, r.text
    tok_b = r.json()["session_token"]

    # Company admin for A (seed a synthetic session)
    adm_a_uid = f"usr_{uuid.uuid4().hex[:10]}"
    db.users.insert_one({
        "user_id": adm_a_uid,
        "role": "company_admin",
        "company_id": cid_a,
        "name": f"{RUN_ID} AdmA",
        "email": f"{RUN_ID.lower()}_adma@test.local",
        "approval_status": "approved",
        "onboarded": True,
        "created_at": now,
    })
    adm_a_tok = _mk_session(adm_a_uid, "company_admin")

    # Super_admin session (do NOT touch real super_admin user's PIN — seed a fake one)
    sadm_uid = f"usr_{uuid.uuid4().hex[:10]}"
    db.users.insert_one({
        "user_id": sadm_uid,
        "role": "super_admin",
        "company_id": None,
        "name": f"{RUN_ID} SuperAdm",
        "email": f"{RUN_ID.lower()}_super@test.local",
        "approval_status": "approved",
        "onboarded": True,
        "created_at": now,
    })
    sadm_tok = _mk_session(sadm_uid, "super_admin")

    ctx = {
        "cid_a": cid_a, "cid_b": cid_b,
        "prefix_a": prefix_a, "prefix_b": prefix_b,
        "uid_a": uid_a, "uid_b": uid_b,
        "tok_a": tok_a, "tok_b": tok_b,
        "adm_a_uid": adm_a_uid, "adm_a_tok": adm_a_tok,
        "sadm_uid": sadm_uid, "sadm_tok": sadm_tok,
    }
    yield ctx

    # Cleanup
    db.profile_edit_requests.delete_many({"user_id": {"$in": [uid_a, uid_b]}})
    db.user_sessions.delete_many({"user_id": {"$in": [uid_a, uid_b, adm_a_uid, sadm_uid]}})
    db.users.delete_many({"user_id": {"$in": [uid_a, uid_b, adm_a_uid, sadm_uid]}})
    db.companies.delete_many({"company_id": {"$in": [cid_a, cid_b]}})


# --------- POST /me/profile-edit ---------

class TestSubmit:
    def test_role_gate_admin_403(self, scenario):
        r = requests.post(
            f"{API}/me/profile-edit",
            headers=_hdr(scenario["adm_a_tok"]),
            json={"name": "New Adm Name"},
        )
        assert r.status_code == 403, r.text

    def test_bad_dob_rejected(self, scenario):
        r = requests.post(
            f"{API}/me/profile-edit",
            headers=_hdr(scenario["tok_a"]),
            json={"dob": "15-01-1990"},  # not YYYY-MM-DD
        )
        assert r.status_code == 400, r.text
        assert "birth" in r.text.lower() or "date" in r.text.lower()

    def test_bad_doj_rejected(self, scenario):
        r = requests.post(
            f"{API}/me/profile-edit",
            headers=_hdr(scenario["tok_a"]),
            json={"doj": "2020/06/01"},
        )
        assert r.status_code == 400, r.text

    def test_nothing_to_update(self, scenario):
        # Submit values IDENTICAL to live doc — expect 400
        r = requests.post(
            f"{API}/me/profile-edit",
            headers=_hdr(scenario["tok_a"]),
            json={
                "name": f"{RUN_ID} EmpA",
                "father_name": "OldFatherA",
                "dob": "1990-01-15",
                "doj": "2020-06-01",
            },
        )
        assert r.status_code == 400, r.text
        assert "nothing" in r.text.lower() or "match" in r.text.lower()

    def test_submit_creates_pending_with_diff_only(self, scenario):
        r = requests.post(
            f"{API}/me/profile-edit",
            headers=_hdr(scenario["tok_a"]),
            json={
                "name": f"{RUN_ID} EmpANew",
                "father_name": "OldFatherA",  # unchanged — should NOT be in diff
                "dob": "1990-01-15",           # unchanged
                "doj": "2021-01-01",           # changed
                "note": "please approve",
            },
        )
        assert r.status_code == 200, r.text
        req = r.json()["request"]
        assert req["status"] == "pending"
        assert req["user_id"] == scenario["uid_a"]
        assert req["company_id"] == scenario["cid_a"]
        assert set(req["changes"].keys()) == {"name", "doj"}
        assert req["changes"]["name"] == f"{RUN_ID} EmpANew"
        assert req["changes"]["doj"] == "2021-01-01"
        assert req["note"] == "please approve"
        # Verify persisted in DB
        found = db.profile_edit_requests.find_one({"request_id": req["request_id"]})
        assert found is not None

    def test_second_submit_replaces_pending(self, scenario):
        # First submit was above. Now submit again with different values.
        before = list(db.profile_edit_requests.find({
            "user_id": scenario["uid_a"], "status": "pending",
        }))
        assert len(before) == 1

        r = requests.post(
            f"{API}/me/profile-edit",
            headers=_hdr(scenario["tok_a"]),
            json={"name": f"{RUN_ID} EmpAFinal"},
        )
        assert r.status_code == 200, r.text
        after = list(db.profile_edit_requests.find({
            "user_id": scenario["uid_a"], "status": "pending",
        }))
        assert len(after) == 1
        # request_id changed
        assert after[0]["request_id"] != before[0]["request_id"]
        assert after[0]["changes"] == {"name": f"{RUN_ID} EmpAFinal"}


# --------- GET /me/profile-edit ---------

class TestGetMine:
    def test_returns_latest(self, scenario):
        r = requests.get(f"{API}/me/profile-edit", headers=_hdr(scenario["tok_a"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["request"] is not None
        assert body["request"]["status"] == "pending"

    def test_returns_null_for_untouched_user(self, scenario):
        r = requests.get(f"{API}/me/profile-edit", headers=_hdr(scenario["tok_b"]))
        assert r.status_code == 200, r.text
        assert r.json()["request"] is None


# --------- GET /admin/profile-edits ---------

class TestAdminList:
    def test_company_admin_scoped_to_own_company(self, scenario):
        r = requests.get(
            f"{API}/admin/profile-edits?status=pending",
            headers=_hdr(scenario["adm_a_tok"]),
        )
        assert r.status_code == 200, r.text
        items = r.json()["requests"]
        # Should include EmpA's pending request; must NOT include EmpB's (if any).
        assert any(it["user_id"] == scenario["uid_a"] for it in items)
        assert all(it.get("company_id") == scenario["cid_a"] for it in items)

    def test_response_annotated_with_employee(self, scenario):
        r = requests.get(
            f"{API}/admin/profile-edits?status=pending",
            headers=_hdr(scenario["adm_a_tok"]),
        )
        assert r.status_code == 200
        items = r.json()["requests"]
        target = next(it for it in items if it["user_id"] == scenario["uid_a"])
        emp = target["employee"]
        assert emp is not None
        for k in ("name", "father_name", "dob", "doj", "employee_code"):
            assert k in emp, f"missing {k} in employee"

    def test_super_admin_no_scope_returns_all(self, scenario):
        # Create a pending request for EmpB too so we have two companies represented.
        requests.post(
            f"{API}/me/profile-edit",
            headers=_hdr(scenario["tok_b"]),
            json={"name": f"{RUN_ID} EmpBRenamed"},
        )
        r = requests.get(
            f"{API}/admin/profile-edits?status=pending",
            headers=_hdr(scenario["sadm_tok"]),
        )
        assert r.status_code == 200, r.text
        items = r.json()["requests"]
        cids = {it.get("company_id") for it in items}
        assert scenario["cid_a"] in cids
        assert scenario["cid_b"] in cids

    def test_super_admin_scoped_to_company(self, scenario):
        r = requests.get(
            f"{API}/admin/profile-edits?status=pending&company_id={scenario['cid_b']}",
            headers=_hdr(scenario["sadm_tok"]),
        )
        assert r.status_code == 200
        items = r.json()["requests"]
        assert all(it.get("company_id") == scenario["cid_b"] for it in items)
        assert any(it["user_id"] == scenario["uid_b"] for it in items)


# --------- PATCH /admin/profile-edits/{id} ---------

class TestReview:
    def _find_pending(self, uid):
        return db.profile_edit_requests.find_one({"user_id": uid, "status": "pending"})

    def test_reject_forbidden_cross_company(self, scenario):
        # EmpB's request exists (from super-admin test), reviewed by admin of A → 403
        pending_b = self._find_pending(scenario["uid_b"])
        assert pending_b is not None
        r = requests.patch(
            f"{API}/admin/profile-edits/{pending_b['request_id']}",
            headers=_hdr(scenario["adm_a_tok"]),
            json={"status": "rejected", "review_note": "not my scope"},
        )
        assert r.status_code == 403, r.text

    def test_approve_applies_changes_to_user(self, scenario):
        pending_a = self._find_pending(scenario["uid_a"])
        assert pending_a is not None
        expected_name = pending_a["changes"].get("name")
        assert expected_name  # should be EmpAFinal from earlier test
        r = requests.patch(
            f"{API}/admin/profile-edits/{pending_a['request_id']}",
            headers=_hdr(scenario["adm_a_tok"]),
            json={"status": "approved"},
        )
        assert r.status_code == 200, r.text
        req = r.json()["request"]
        assert req["status"] == "approved"
        # user doc updated
        u = db.users.find_one({"user_id": scenario["uid_a"]}, {"_id": 0})
        assert u["name"] == expected_name

    def test_second_review_returns_400(self, scenario):
        # find the just-approved one via GET (any status) via admin? use DB
        approved = db.profile_edit_requests.find_one({
            "user_id": scenario["uid_a"], "status": "approved",
        })
        assert approved is not None
        r = requests.patch(
            f"{API}/admin/profile-edits/{approved['request_id']}",
            headers=_hdr(scenario["adm_a_tok"]),
            json={"status": "rejected"},
        )
        assert r.status_code == 400, r.text
        assert "already" in r.text.lower()

    def test_reject_leaves_user_untouched(self, scenario):
        # Submit a new pending request for A
        r = requests.post(
            f"{API}/me/profile-edit",
            headers=_hdr(scenario["tok_a"]),
            json={"father_name": "TryChangeFather"},
        )
        assert r.status_code == 200, r.text
        pending = self._find_pending(scenario["uid_a"])
        # snapshot father before
        before = db.users.find_one({"user_id": scenario["uid_a"]}, {"_id": 0})
        r = requests.patch(
            f"{API}/admin/profile-edits/{pending['request_id']}",
            headers=_hdr(scenario["adm_a_tok"]),
            json={"status": "rejected", "review_note": "no doc attached"},
        )
        assert r.status_code == 200, r.text
        after = db.users.find_one({"user_id": scenario["uid_a"]}, {"_id": 0})
        assert after.get("father_name") == before.get("father_name")


# --------- GET after approval regression ---------

class TestPostApproval:
    def test_employee_get_shows_latest_approved(self, scenario):
        r = requests.get(f"{API}/me/profile-edit", headers=_hdr(scenario["tok_a"]))
        assert r.status_code == 200
        body = r.json()
        assert body["request"] is not None
        # latest should be the just-rejected one (submitted_at is newer)
        assert body["request"]["status"] in {"rejected", "approved"}

    def test_auth_me_reflects_approved_name(self, scenario):
        r = requests.get(f"{API}/auth/me", headers=_hdr(scenario["tok_a"]))
        assert r.status_code == 200, r.text
        u = r.json().get("user") or r.json()
        assert u.get("name") == f"{RUN_ID} EmpAFinal"
