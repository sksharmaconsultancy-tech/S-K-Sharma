"""Iter 508 — Portal task workflow (overdue-gate, Later, super-admin bypass).

Verifies backend endpoints requested in review E:
  • GET /admin/portal-tasks?status=overdue   -> returns overdue task
  • POST /admin/portal-tasks/{id}/later      -> requires reason (400 without)
  • POST /admin/portal-tasks/{id}/overdue-reason -> records reason
  • Task audit contains "marked_later" and "overdue_reason" actions
  • Super-admin sees tasks it created even when firm scope differs (bypass)
"""
import os
import pytest
import requests

BASE = os.environ["EXPO_BACKEND_URL"] if "EXPO_BACKEND_URL" in os.environ else \
       "https://emplo-connect-1.preview.emergentagent.com"
BASE = BASE.rstrip("/")

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PASS  = "sharma123"
SUB_EMAIL   = "testsub@sksharma.co"
SUB_PASS    = "testsub123"

OVERDUE_TASK = "task_416d0b067fd4"   # overdue, gate test
LATER_TASK   = "task_bf2434002b99"   # to be marked Later
SUB_USER_ID  = "sub_623b8a106846"


# ---------- fixtures ----------
def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/admin-password-login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def super_token(): return _login(SUPER_EMAIL, SUPER_PASS)


@pytest.fixture(scope="module")
def sub_token(): return _login(SUB_EMAIL, SUB_PASS)


def _h(tok): return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- 1. status=overdue filter ----------
class TestOverdueFilter:
    def test_overdue_filter_returns_overdue_task(self, super_token):
        r = requests.get(f"{BASE}/api/admin/portal-tasks?status=overdue",
                         headers=_h(super_token), timeout=30)
        assert r.status_code == 200
        ids = [t["task_id"] for t in r.json().get("tasks", [])]
        assert OVERDUE_TASK in ids, f"expected {OVERDUE_TASK} in overdue list, got {ids[:5]}"


# ---------- 2. super-admin firm bypass (allotted tasks) ----------
class TestSuperAdminFirmBypass:
    def test_super_admin_sees_city_care_task_from_other_firm(self, super_token):
        # Even though selected firm may be Kankani, both seed tasks live on
        # City Care Hospital.  The bypass must still return them.
        r = requests.get(f"{BASE}/api/admin/portal-tasks?status=all",
                         headers=_h(super_token), timeout=30)
        assert r.status_code == 200
        ids = {t["task_id"] for t in r.json().get("tasks", [])}
        assert OVERDUE_TASK in ids
        assert LATER_TASK  in ids


# ---------- 3. Mark Later requires reason ----------
class TestMarkLater:
    def test_later_rejects_empty_reason(self, sub_token):
        r = requests.post(f"{BASE}/api/admin/portal-tasks/{LATER_TASK}/later",
                          json={"reason": "  "}, headers=_h(sub_token), timeout=30)
        assert r.status_code == 400, r.text

    def test_later_with_reason_succeeds(self, sub_token, super_token):
        r = requests.post(f"{BASE}/api/admin/portal-tasks/{LATER_TASK}/later",
                          json={"reason": "Awaiting client data"},
                          headers=_h(sub_token), timeout=30)
        assert r.status_code == 200, r.text
        # verify persisted status = later
        g = requests.get(f"{BASE}/api/admin/portal-tasks?status=all",
                        headers=_h(super_token), timeout=30)
        task = next((t for t in g.json()["tasks"] if t["task_id"] == LATER_TASK), None)
        assert task, "later task missing from list"
        assert task.get("status") == "later"
        assert (task.get("later_reason") or "").lower().startswith("awaiting")


# ---------- 4. Overdue-reason submission clears block ----------
class TestOverdueReasonFlow:
    def test_sub_sees_overdue_block(self, sub_token):
        r = requests.get(f"{BASE}/api/admin/portal-tasks/overdue-block",
                         headers=_h(sub_token), timeout=30)
        assert r.status_code == 200, r.text
        ids = [t["task_id"] for t in r.json().get("tasks", [])]
        # The overdue task should currently block the sub admin
        assert OVERDUE_TASK in ids

    def test_submit_overdue_reason_clears(self, sub_token):
        r = requests.post(f"{BASE}/api/admin/portal-tasks/{OVERDUE_TASK}/overdue-reason",
                          json={"reason": "Client GST creds pending — iter508 test"},
                          headers=_h(sub_token), timeout=30)
        assert r.status_code == 200, r.text
        # re-check overdue-block — task must be gone
        r2 = requests.get(f"{BASE}/api/admin/portal-tasks/overdue-block",
                          headers=_h(sub_token), timeout=30)
        assert r2.status_code == 200
        ids = [t["task_id"] for t in r2.json().get("tasks", [])]
        assert OVERDUE_TASK not in ids, f"still blocking after ack: {ids}"


# ---------- 5. audit trail contains actions ----------
class TestAuditTrail:
    def _audit(self, tok, tid):
        r = requests.get(f"{BASE}/api/admin/portal-tasks/{tid}/audit",
                         headers=_h(tok), timeout=30)
        assert r.status_code == 200, r.text
        return r.json()

    def test_later_task_audit_has_marked_later(self, super_token):
        data = self._audit(super_token, LATER_TASK)
        actions = [e.get("action") for e in data.get("entries", data.get("audit", []))]
        assert "marked_later" in actions, f"actions={actions}"

    def test_overdue_task_audit_has_overdue_reason(self, super_token):
        data = self._audit(super_token, OVERDUE_TASK)
        actions = [e.get("action") for e in data.get("entries", data.get("audit", []))]
        assert "overdue_reason" in actions, f"actions={actions}"


# ---------- 6. 24-hour default due date ----------
class TestDefaultDueDate:
    task_id_created = None

    def test_create_task_defaults_due_tomorrow(self, super_token):
        import datetime
        r = requests.post(f"{BASE}/api/admin/portal-tasks",
                          json={"title": "TEST_iter508_defaultdue"},
                          headers=_h(super_token), timeout=30)
        assert r.status_code in (200, 201), r.text
        body = r.json()
        tid = body.get("task_id") or body.get("id") or body.get("task", {}).get("task_id")
        assert tid, f"no task_id in {body}"
        TestDefaultDueDate.task_id_created = tid
        due = body.get("due_date") or body.get("task", {}).get("due_date")
        assert due, f"no due_date returned: {body}"
        # due date should be within +1 to +2 days from today
        today = datetime.date.today()
        due_d = datetime.date.fromisoformat(due[:10])
        assert 0 < (due_d - today).days <= 2, f"due {due} not ~24h from today"

    def test_cleanup_created_task(self, super_token):
        tid = TestDefaultDueDate.task_id_created
        if not tid: pytest.skip("nothing to clean")
        r = requests.delete(f"{BASE}/api/admin/portal-tasks/{tid}",
                            headers=_h(super_token), timeout=30)
        assert r.status_code in (200, 204), r.text
