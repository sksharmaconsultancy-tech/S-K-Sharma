"""
Backend tests for the new in-app messaging endpoints (iter41).
Endpoints under test:
  POST   /api/messages
  GET    /api/messages/inbox
  GET    /api/messages/unread-count
  GET    /api/messages/sent
  POST   /api/messages/{id}/read
  GET    /api/messages/recipients

Seeds two throwaway companies (IT41_A, IT41_B) with company_admins and
employees, plus a throwaway super_admin. Teardown removes every doc whose
_id/user_id/company_id/message_id begins with IT41_ or was created for one
of these users.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

# ---------- Mongo helpers ----------
_mc = MongoClient(MONGO_URL)
_db = _mc[DB_NAME]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mk_user(role: str, company_id: str | None, tag: str) -> dict:
    uid = f"IT41_user_{tag}_{uuid.uuid4().hex[:6]}"
    return {
        "user_id": uid,
        "email": f"IT41_{tag}_{uid[-6:]}@it41.test",
        "phone": None,
        "name": f"IT41 {tag}",
        "picture": None,
        "role": role,
        "company_id": company_id,
        "department": None,
        "position": None,
        "employee_code": f"IT41_{tag.upper()}",
        "onboarded": True,
        "created_at": _now_iso(),
    }


def _mk_session(user_id: str) -> str:
    token = f"IT41_tok_{uuid.uuid4().hex}"
    _db.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "created_at": datetime.now(timezone.utc),
        "auth_method": "test_seed",
    })
    return token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- Session-wide seed fixture ----------
@pytest.fixture(scope="module")
def seed():
    # Companies
    _suffix = uuid.uuid4().hex[:6]
    comp_a = {"company_id": "IT41_COMP_A", "name": "IT41 Company A",
              "company_code": f"IT41A{_suffix}", "created_at": _now_iso()}
    comp_b = {"company_id": "IT41_COMP_B", "name": "IT41 Company B",
              "company_code": f"IT41B{_suffix}", "created_at": _now_iso()}
    _db.companies.insert_many([comp_a, comp_b])

    # Users
    admin_a = _mk_user("company_admin", "IT41_COMP_A", "adminA")
    admin_b = _mk_user("company_admin", "IT41_COMP_B", "adminB")
    super_admin = _mk_user("super_admin", None, "super")
    emp_a1 = _mk_user("employee", "IT41_COMP_A", "empA1")
    emp_a2 = _mk_user("employee", "IT41_COMP_A", "empA2")
    emp_b1 = _mk_user("employee", "IT41_COMP_B", "empB1")
    emp_b2 = _mk_user("employee", "IT41_COMP_B", "empB2")
    # Non-employee in company A (should NEVER be a broadcast recipient)
    other_admin_a = _mk_user("company_admin", "IT41_COMP_A", "adminA2")

    users = [admin_a, admin_b, super_admin, emp_a1, emp_a2, emp_b1, emp_b2, other_admin_a]
    _db.users.insert_many(users)

    # Sessions
    tokens = {u["user_id"]: _mk_session(u["user_id"]) for u in users}

    ctx = {
        "admin_a": admin_a,
        "admin_b": admin_b,
        "super_admin": super_admin,
        "emp_a1": emp_a1,
        "emp_a2": emp_a2,
        "emp_b1": emp_b1,
        "emp_b2": emp_b2,
        "other_admin_a": other_admin_a,
        "tokens": tokens,
    }
    yield ctx

    # ----- Teardown: remove ONLY IT41_ artefacts -----
    _db.companies.delete_many({"company_id": {"$regex": "^IT41_"}})
    _db.users.delete_many({"user_id": {"$regex": "^IT41_"}})
    _db.user_sessions.delete_many({"session_token": {"$regex": "^IT41_tok_"}})
    _db.user_sessions.delete_many({"user_id": {"$regex": "^IT41_"}})
    _db.messages.delete_many({"sender_user_id": {"$regex": "^IT41_"}})


# =============================================================================
# 1. Validation errors on POST /api/messages
# =============================================================================
class TestSendValidation:
    def test_empty_subject_returns_400(self, seed):
        tok = seed["tokens"][seed["admin_a"]["user_id"]]
        r = requests.post(f"{BASE_URL}/api/messages",
                          headers=_auth(tok),
                          json={"subject": "  ", "body": "hi", "broadcast": True})
        assert r.status_code == 400, r.text

    def test_empty_body_returns_400(self, seed):
        tok = seed["tokens"][seed["admin_a"]["user_id"]]
        r = requests.post(f"{BASE_URL}/api/messages",
                          headers=_auth(tok),
                          json={"subject": "hi", "body": "", "broadcast": True})
        assert r.status_code == 400, r.text

    def test_no_broadcast_no_recipients_returns_400(self, seed):
        tok = seed["tokens"][seed["admin_a"]["user_id"]]
        r = requests.post(f"{BASE_URL}/api/messages",
                          headers=_auth(tok),
                          json={"subject": "hi", "body": "hello"})
        assert r.status_code == 400, r.text

    def test_employee_cannot_send_403(self, seed):
        tok = seed["tokens"][seed["emp_a1"]["user_id"]]
        r = requests.post(f"{BASE_URL}/api/messages",
                          headers=_auth(tok),
                          json={"subject": "hi", "body": "hello", "broadcast": True})
        assert r.status_code == 403, r.text


# =============================================================================
# 2. Broadcast behavior
# =============================================================================
class TestBroadcast:
    def test_company_admin_broadcast_includes_only_own_employees(self, seed):
        tok = seed["tokens"][seed["admin_a"]["user_id"]]
        r = requests.post(f"{BASE_URL}/api/messages",
                          headers=_auth(tok),
                          json={"subject": "TEST bcastA", "body": "hello A",
                                "broadcast": True})
        assert r.status_code == 200, r.text
        msg = r.json()["message"]
        recips = set(msg["recipient_user_ids"])
        # both employees of A, and NOT admin_a, NOT other_admin_a, NOT B emps
        assert seed["emp_a1"]["user_id"] in recips
        assert seed["emp_a2"]["user_id"] in recips
        assert seed["emp_b1"]["user_id"] not in recips
        assert seed["emp_b2"]["user_id"] not in recips
        assert seed["admin_a"]["user_id"] not in recips
        assert seed["other_admin_a"]["user_id"] not in recips
        assert seed["super_admin"]["user_id"] not in recips
        assert msg["is_broadcast"] is True
        assert msg["recipient_count"] == len(recips)

    def test_super_admin_broadcast_no_company_id_reaches_all_companies(self, seed):
        tok = seed["tokens"][seed["super_admin"]["user_id"]]
        r = requests.post(f"{BASE_URL}/api/messages",
                          headers=_auth(tok),
                          json={"subject": "TEST bcastGlobal", "body": "global",
                                "broadcast": True})
        assert r.status_code == 200, r.text
        recips = set(r.json()["message"]["recipient_user_ids"])
        # employees from BOTH companies must be present
        for uid in (seed["emp_a1"]["user_id"], seed["emp_a2"]["user_id"],
                    seed["emp_b1"]["user_id"], seed["emp_b2"]["user_id"]):
            assert uid in recips, f"missing {uid} in global broadcast"
        # non-employees must NOT be present
        assert seed["admin_a"]["user_id"] not in recips
        assert seed["admin_b"]["user_id"] not in recips
        assert seed["super_admin"]["user_id"] not in recips

    def test_super_admin_broadcast_scoped_to_company_id(self, seed):
        tok = seed["tokens"][seed["super_admin"]["user_id"]]
        r = requests.post(f"{BASE_URL}/api/messages",
                          headers=_auth(tok),
                          json={"subject": "TEST bcastB", "body": "only B",
                                "broadcast": True, "company_id": "IT41_COMP_B"})
        assert r.status_code == 200, r.text
        recips = set(r.json()["message"]["recipient_user_ids"])
        assert seed["emp_b1"]["user_id"] in recips
        assert seed["emp_b2"]["user_id"] in recips
        assert seed["emp_a1"]["user_id"] not in recips
        assert seed["emp_a2"]["user_id"] not in recips


# =============================================================================
# 3. Explicit multi-select recipients (scope filtering)
# =============================================================================
class TestExplicitRecipients:
    def test_company_admin_filters_out_of_scope_silently(self, seed):
        tok = seed["tokens"][seed["admin_a"]["user_id"]]
        r = requests.post(
            f"{BASE_URL}/api/messages",
            headers=_auth(tok),
            json={
                "subject": "TEST explicit mix",
                "body": "mixed",
                "recipient_user_ids": [
                    seed["emp_a1"]["user_id"],   # in scope
                    seed["emp_b1"]["user_id"],   # out of scope -> filtered
                    seed["emp_a2"]["user_id"],   # in scope
                ],
            },
        )
        assert r.status_code == 200, r.text
        recips = set(r.json()["message"]["recipient_user_ids"])
        assert recips == {seed["emp_a1"]["user_id"], seed["emp_a2"]["user_id"]}

    def test_company_admin_all_out_of_scope_returns_400(self, seed):
        tok = seed["tokens"][seed["admin_a"]["user_id"]]
        r = requests.post(
            f"{BASE_URL}/api/messages",
            headers=_auth(tok),
            json={
                "subject": "TEST oos only",
                "body": "should reject",
                "recipient_user_ids": [seed["emp_b1"]["user_id"],
                                       seed["emp_b2"]["user_id"]],
            },
        )
        assert r.status_code == 400, r.text


# =============================================================================
# 4. Inbox / read / unread-count
# =============================================================================
class TestInboxRead:
    def test_inbox_contains_message_no_readby_field(self, seed):
        # send a fresh directed message
        stok = seed["tokens"][seed["admin_a"]["user_id"]]
        subj = f"TEST inbox {uuid.uuid4().hex[:6]}"
        r = requests.post(f"{BASE_URL}/api/messages",
                          headers=_auth(stok),
                          json={"subject": subj, "body": "for inbox",
                                "recipient_user_ids": [seed["emp_a1"]["user_id"]]})
        assert r.status_code == 200
        mid = r.json()["message"]["message_id"]

        # employee inbox
        etok = seed["tokens"][seed["emp_a1"]["user_id"]]
        r = requests.get(f"{BASE_URL}/api/messages/inbox", headers=_auth(etok))
        assert r.status_code == 200
        items = r.json()["messages"]
        mine = [m for m in items if m["message_id"] == mid]
        assert len(mine) == 1
        m = mine[0]
        assert m["read"] is False
        assert "read_by" not in m, "read_by must not leak in /inbox items"
        assert m["subject"] == subj

    def test_non_recipient_does_not_see_message(self, seed):
        stok = seed["tokens"][seed["admin_a"]["user_id"]]
        subj = f"TEST hidden {uuid.uuid4().hex[:6]}"
        r = requests.post(f"{BASE_URL}/api/messages",
                          headers=_auth(stok),
                          json={"subject": subj, "body": "hidden",
                                "recipient_user_ids": [seed["emp_a1"]["user_id"]]})
        assert r.status_code == 200

        etok = seed["tokens"][seed["emp_a2"]["user_id"]]  # not a recipient
        r = requests.get(f"{BASE_URL}/api/messages/inbox", headers=_auth(etok))
        assert r.status_code == 200
        assert all(m["subject"] != subj for m in r.json()["messages"])

    def test_mark_read_flow_and_idempotent(self, seed):
        stok = seed["tokens"][seed["admin_a"]["user_id"]]
        r = requests.post(f"{BASE_URL}/api/messages",
                          headers=_auth(stok),
                          json={"subject": "TEST read1", "body": "hi",
                                "recipient_user_ids": [seed["emp_a1"]["user_id"]]})
        mid = r.json()["message"]["message_id"]

        etok = seed["tokens"][seed["emp_a1"]["user_id"]]
        # unread-count before
        uc_before = requests.get(f"{BASE_URL}/api/messages/unread-count",
                                 headers=_auth(etok)).json()["unread"]

        # mark read
        r = requests.post(f"{BASE_URL}/api/messages/{mid}/read",
                          headers=_auth(etok))
        assert r.status_code == 200

        # unread-count decrements
        uc_after = requests.get(f"{BASE_URL}/api/messages/unread-count",
                                headers=_auth(etok)).json()["unread"]
        assert uc_after == uc_before - 1

        # idempotency — 2nd call still 200, read_by has only one entry for user
        r = requests.post(f"{BASE_URL}/api/messages/{mid}/read",
                          headers=_auth(etok))
        assert r.status_code == 200
        doc = _db.messages.find_one({"message_id": mid}, {"_id": 0, "read_by": 1})
        assert doc["read_by"].count(seed["emp_a1"]["user_id"]) == 1

        # inbox now shows read=true
        r = requests.get(f"{BASE_URL}/api/messages/inbox", headers=_auth(etok))
        m = next(x for x in r.json()["messages"] if x["message_id"] == mid)
        assert m["read"] is True

    def test_mark_read_non_recipient_403(self, seed):
        stok = seed["tokens"][seed["admin_a"]["user_id"]]
        r = requests.post(f"{BASE_URL}/api/messages",
                          headers=_auth(stok),
                          json={"subject": "TEST 403", "body": "hi",
                                "recipient_user_ids": [seed["emp_a1"]["user_id"]]})
        mid = r.json()["message"]["message_id"]

        etok = seed["tokens"][seed["emp_a2"]["user_id"]]
        r = requests.post(f"{BASE_URL}/api/messages/{mid}/read",
                          headers=_auth(etok))
        assert r.status_code == 403

    def test_mark_read_unknown_id_404(self, seed):
        etok = seed["tokens"][seed["emp_a1"]["user_id"]]
        r = requests.post(f"{BASE_URL}/api/messages/msg_does_not_exist/read",
                          headers=_auth(etok))
        assert r.status_code == 404


# =============================================================================
# 5. Sent messages (admin outbox)
# =============================================================================
class TestSent:
    def test_sent_only_shows_callers_messages_with_counts(self, seed):
        stok_a = seed["tokens"][seed["admin_a"]["user_id"]]
        # send by admin_a
        r = requests.post(f"{BASE_URL}/api/messages",
                          headers=_auth(stok_a),
                          json={"subject": "TEST sent A", "body": "x",
                                "recipient_user_ids": [seed["emp_a1"]["user_id"],
                                                       seed["emp_a2"]["user_id"]]})
        assert r.status_code == 200
        mid = r.json()["message"]["message_id"]

        # emp_a1 marks read
        etok = seed["tokens"][seed["emp_a1"]["user_id"]]
        requests.post(f"{BASE_URL}/api/messages/{mid}/read", headers=_auth(etok))

        r = requests.get(f"{BASE_URL}/api/messages/sent", headers=_auth(stok_a))
        assert r.status_code == 200
        msgs = r.json()["messages"]
        found = next((m for m in msgs if m["message_id"] == mid), None)
        assert found is not None
        assert found["recipient_count"] == 2
        assert found["read_count"] == 1
        # admin_a must not see admin_b's outbox
        assert all(m["sender_user_id"] == seed["admin_a"]["user_id"] for m in msgs)

    def test_sent_forbidden_for_employee(self, seed):
        etok = seed["tokens"][seed["emp_a1"]["user_id"]]
        r = requests.get(f"{BASE_URL}/api/messages/sent", headers=_auth(etok))
        assert r.status_code == 403


# =============================================================================
# 6. Recipients directory
# =============================================================================
class TestRecipientsList:
    def test_company_admin_sees_only_own_employees(self, seed):
        tok = seed["tokens"][seed["admin_a"]["user_id"]]
        r = requests.get(f"{BASE_URL}/api/messages/recipients", headers=_auth(tok))
        assert r.status_code == 200
        ids = {u["user_id"] for u in r.json()["employees"]}
        assert seed["emp_a1"]["user_id"] in ids
        assert seed["emp_a2"]["user_id"] in ids
        assert seed["emp_b1"]["user_id"] not in ids
        assert seed["emp_b2"]["user_id"] not in ids
        # non-employees excluded
        assert seed["admin_a"]["user_id"] not in ids
        assert seed["other_admin_a"]["user_id"] not in ids

    def test_company_admin_cannot_cross_company_via_query(self, seed):
        tok = seed["tokens"][seed["admin_a"]["user_id"]]
        r = requests.get(f"{BASE_URL}/api/messages/recipients?company_id=IT41_COMP_B",
                         headers=_auth(tok))
        assert r.status_code == 200
        ids = {u["user_id"] for u in r.json()["employees"]}
        assert seed["emp_b1"]["user_id"] not in ids
        assert seed["emp_b2"]["user_id"] not in ids

    def test_super_admin_can_filter_by_company_id(self, seed):
        tok = seed["tokens"][seed["super_admin"]["user_id"]]
        r = requests.get(f"{BASE_URL}/api/messages/recipients?company_id=IT41_COMP_A",
                         headers=_auth(tok))
        assert r.status_code == 200
        ids = {u["user_id"] for u in r.json()["employees"]}
        assert seed["emp_a1"]["user_id"] in ids
        assert seed["emp_b1"]["user_id"] not in ids

    def test_q_substring_case_insensitive_on_name(self, seed):
        tok = seed["tokens"][seed["admin_a"]["user_id"]]
        # emp_a1 name is "IT41 empA1" — search 'EMPA1' (uppercase)
        r = requests.get(f"{BASE_URL}/api/messages/recipients?q=EMPA1",
                         headers=_auth(tok))
        assert r.status_code == 200
        ids = {u["user_id"] for u in r.json()["employees"]}
        assert seed["emp_a1"]["user_id"] in ids
        assert seed["emp_a2"]["user_id"] not in ids

    def test_q_substring_on_employee_code(self, seed):
        tok = seed["tokens"][seed["admin_a"]["user_id"]]
        # employee_code "IT41_EMPA2" — search fragment
        r = requests.get(f"{BASE_URL}/api/messages/recipients?q=empa2",
                         headers=_auth(tok))
        assert r.status_code == 200
        ids = {u["user_id"] for u in r.json()["employees"]}
        assert seed["emp_a2"]["user_id"] in ids
