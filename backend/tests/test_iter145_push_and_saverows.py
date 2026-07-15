"""Iter 145 — Web Push endpoints + Compliance Save-Rows P0 fix regression tests.

Coverage
--------
1. GET /api/push/vapid-public-key returns a public_key without auth.
2. POST /api/push/subscribe upserts into db.push_subscriptions.
3. POST /api/push/unsubscribe removes it.
4. Push hooks are try/except-guarded — leave PATCH, employee approval and
   manual-punch endpoints still return normally (endpoint contract check).
5. P0 FIX: POST /api/admin/compliance-salary-runs/{run_id}/save-rows
   persists row edits (other_deduction, present_days), 400s when row
   user_id set mismatches, and 400s on finalized runs.

Fixture cleanup restores every mutated row to its original value so this
test can be re-run indefinitely against the live preview.
"""
import copy
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
ADMIN_PASSWORD = "sharma123"
EXISTING_RUN_ID = "csrun_be5f1dd4daef"


# -------------------------- fixtures -----------------------------------
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(api):
    r = api.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok, f"no token in response: {r.text}"
    return tok


@pytest.fixture(scope="module")
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------------------- 1) Push endpoints ------------------------------
class TestPushEndpoints:
    def test_vapid_public_key_public(self, api):
        r = api.get(f"{BASE_URL}/api/push/vapid-public-key", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "public_key" in body and isinstance(body["public_key"], str) and len(body["public_key"]) > 40

    def test_subscribe_and_unsubscribe(self, api, auth):
        endpoint = f"https://fcm.googleapis.com/fcm/send/TEST_iter145_{uuid.uuid4().hex[:8]}"
        payload = {
            "endpoint": endpoint,
            "keys": {"p256dh": "BFakeP256dhKeyForTestingOnly_" + "A" * 60,
                     "auth": "FakeAuthTokenForTesting=="},
            "ua": "pytest-iter145",
        }
        # Subscribe
        r = api.post(f"{BASE_URL}/api/push/subscribe", json=payload,
                     headers=auth, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

        # Unsubscribe
        r = api.post(f"{BASE_URL}/api/push/unsubscribe",
                     json={"endpoint": endpoint}, headers=auth, timeout=10)
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_subscribe_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/push/subscribe",
                     json={"endpoint": "https://x/y", "keys": {"p256dh": "a", "auth": "b"}},
                     timeout=10)
        # Any non-2xx acceptable; must not upsert without a token
        assert r.status_code in (400, 401, 403, 422), r.status_code


# ---------------------- 2) Push hook safety ----------------------------
class TestPushHookSafety:
    """The push hooks are wrapped in try/except — verify the base endpoints
    still respond normally even though pywebpush cannot actually deliver
    (no real subscriptions in preview)."""

    def test_leave_patch_still_returns(self, api, auth):
        # Approving a random non-existent leave should 404, not 500 —
        # proving the push hook doesn't break error handling either.
        r = api.patch(f"{BASE_URL}/api/leaves/NOT_A_REAL_LEAVE_ID",
                      json={"status": "approved"}, headers=auth, timeout=10)
        assert r.status_code in (400, 404), f"unexpected {r.status_code}: {r.text}"

    def test_admin_approve_employee_endpoint_reachable(self, api, auth):
        # No such request id → 404, not 500.
        r = api.patch(
            f"{BASE_URL}/api/admin/approve-employee/NO_SUCH_REQ_ID",
            json={"decision": "approved"}, headers=auth, timeout=10,
        )
        assert r.status_code in (400, 404, 405, 422), f"{r.status_code}: {r.text}"

    def test_manual_punch_endpoint_reachable(self, api, auth):
        # Empty body → 400/422 (validation). Endpoint must not 500.
        r = api.post(f"{BASE_URL}/api/admin/attendance/manual-punch",
                     json={}, headers=auth, timeout=10)
        assert r.status_code in (400, 422), f"{r.status_code}: {r.text}"


# ---------------------- 3) Save-rows P0 fix ----------------------------
@pytest.fixture(scope="module")
def original_run(api, auth):
    r = api.get(f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}",
                headers=auth, timeout=15)
    assert r.status_code == 200, r.text
    run = r.json().get("run") or {}
    assert run.get("rows"), "run has no rows"
    if run.get("finalized"):
        pytest.skip("run is finalized — save-rows test cannot mutate it safely")
    return copy.deepcopy(run)


class TestSaveRows:
    def test_persist_edits_and_restore(self, api, auth, original_run):
        rows = copy.deepcopy(original_run["rows"])
        target = rows[0]
        original_od = target.get("other_deduction", 0) or 0
        original_pd = target.get("present_days", 0) or 0
        target["other_deduction"] = float(original_od) + 123
        target["present_days"] = float(original_pd) + 1 if original_pd < 27 else float(original_pd) - 1

        try:
            r = api.post(
                f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/save-rows",
                json={"rows": rows, "totals": original_run.get("totals") or {}},
                headers=auth, timeout=30,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("ok") is True
            assert "draft_saved_at" in body

            # Re-GET and verify persistence
            r2 = api.get(f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}",
                         headers=auth, timeout=15)
            assert r2.status_code == 200
            fresh_rows = r2.json()["run"]["rows"]
            fresh_target = next(x for x in fresh_rows if x["user_id"] == target["user_id"])
            assert abs(float(fresh_target["other_deduction"]) - target["other_deduction"]) < 0.01
            assert abs(float(fresh_target["present_days"]) - target["present_days"]) < 0.01
        finally:
            # Restore — MANDATORY per test brief
            r = api.post(
                f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/save-rows",
                json={"rows": original_run["rows"], "totals": original_run.get("totals") or {}},
                headers=auth, timeout=30,
            )
            assert r.status_code == 200, f"RESTORE FAILED: {r.text}"

    def test_row_set_mismatch_400(self, api, auth, original_run):
        rows = copy.deepcopy(original_run["rows"])[:5]  # trimmed set
        r = api.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/save-rows",
            json={"rows": rows}, headers=auth, timeout=15,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        assert "row set" in r.text.lower() or "match" in r.text.lower()

    def test_empty_rows_400(self, api, auth):
        r = api.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/save-rows",
            json={"rows": []}, headers=auth, timeout=15,
        )
        assert r.status_code == 400, r.text

    def test_finalized_run_400(self, api, auth, original_run):
        """Finalize the run momentarily, verify 400, then unlock."""
        # Finalize
        r = api.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/finalize",
            headers=auth, timeout=15,
        )
        assert r.status_code == 200, r.text
        try:
            r2 = api.post(
                f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/save-rows",
                json={"rows": copy.deepcopy(original_run["rows"])},
                headers=auth, timeout=15,
            )
            assert r2.status_code == 400
            assert "finalized" in r2.text.lower()
        finally:
            # Unlock (super_admin path — immediate)
            api.post(
                f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}/unlock-request",
                json={"reason": "iter145 test unlock"}, headers=auth, timeout=15,
            )
            time.sleep(0.3)
            check = api.get(
                f"{BASE_URL}/api/admin/compliance-salary-runs/{EXISTING_RUN_ID}",
                headers=auth, timeout=10,
            )
            assert check.status_code == 200
            assert check.json()["run"].get("finalized") in (False, None), \
                "FAILED TO UNLOCK — manual cleanup required"
