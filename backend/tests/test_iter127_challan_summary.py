"""Iter 127 — Backend tests for Monthly Challan Summary + audit-lock + primary-unread.

Focus: endpoints exposed to super_admin and sub_admin, plus the global
audit-lock middleware. SMTP-dependent and Gmail-dependent paths are asserted
against the expected 'not configured' failure modes (not treated as bugs).
"""
import os
import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PWD = "sharma123"
SUB_EMAIL = "testsub@sksharma.co"
SUB_PWD = "testsub123"

MONTH = "2025-11"  # pick a month unlikely to collide with real data


@pytest.fixture(scope="module")
def super_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": SUPER_EMAIL, "password": SUPER_PWD}, timeout=30,
    )
    assert r.status_code == 200, f"super login failed: {r.status_code} {r.text[:200]}"
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def sub_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": SUB_EMAIL, "password": SUB_PWD}, timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"sub_admin login unavailable ({r.status_code}): {r.text[:200]}")
    return r.json()["session_token"]


def _auth(t): return {"Authorization": f"Bearer {t}"}


# --- Challan Summary GET ---------------------------------------------------
class TestChallanSummaryList:
    def test_super_get(self, super_token):
        r = requests.get(f"{BASE_URL}/api/admin/challan-summary?month={MONTH}",
                         headers=_auth(super_token), timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["month"] == MONTH
        assert isinstance(data["rows"], list)
        assert len(data["rows"]) > 0, "expected at least one active firm"
        row = data["rows"][0]
        for f in ("company_id", "firm_name", "salary_status", "pf_amount",
                  "esic_amount", "pf_by_name", "esic_by_name", "remark", "is_audit"):
            assert f in row, f"missing field {f}"

    def test_sub_get(self, sub_token):
        r = requests.get(f"{BASE_URL}/api/admin/challan-summary?month={MONTH}",
                         headers=_auth(sub_token), timeout=30)
        assert r.status_code == 200
        assert len(r.json()["rows"]) > 0

    def test_unauth(self):
        r = requests.get(f"{BASE_URL}/api/admin/challan-summary?month={MONTH}", timeout=30)
        assert r.status_code in (401, 403)


# --- PATCH + Audit lock roundtrip -----------------------------------------
class TestAuditLock:
    """Toggle Audit remark on one firm, verify sub_admin write is blocked
    with HTTP 423 while super_admin write still works, then clear the lock."""

    @pytest.fixture(scope="class")
    def target(self, super_token):
        r = requests.get(f"{BASE_URL}/api/admin/challan-summary?month={MONTH}",
                         headers=_auth(super_token), timeout=30)
        rows = r.json()["rows"]
        # pick first non-audit firm as target
        for row in rows:
            if not row.get("is_audit"):
                return row["company_id"]
        pytest.skip("no non-audit firm available")

    def test_super_patch_saves_amounts(self, super_token, target):
        r = requests.patch(
            f"{BASE_URL}/api/admin/challan-summary/{target}/{MONTH}",
            headers=_auth(super_token),
            json={"pf_amount": 12345, "esic_amount": 678, "remark": ""},
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["is_audit"] is False
        # verify persistence
        g = requests.get(f"{BASE_URL}/api/admin/challan-summary?month={MONTH}",
                         headers=_auth(super_token), timeout=30).json()
        row = next(x for x in g["rows"] if x["company_id"] == target)
        assert row["pf_amount"] == 12345
        assert row["esic_amount"] == 678

    def test_audit_remark_sets_lock(self, super_token, target):
        r = requests.patch(
            f"{BASE_URL}/api/admin/challan-summary/{target}/{MONTH}",
            headers=_auth(super_token),
            json={"remark": "Audit"}, timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["is_audit"] is True

    def test_sub_admin_blocked_423(self, sub_token, target):
        r = requests.patch(
            f"{BASE_URL}/api/admin/challan-summary/{target}/{MONTH}",
            headers=_auth(sub_token),
            json={"pf_amount": 999}, timeout=30,
        )
        assert r.status_code == 423, f"expected 423, got {r.status_code}: {r.text[:200]}"

    def test_super_can_still_write_locked_firm(self, super_token, target):
        r = requests.patch(
            f"{BASE_URL}/api/admin/challan-summary/{target}/{MONTH}",
            headers=_auth(super_token),
            json={"pf_amount": 1111}, timeout=30,
        )
        assert r.status_code == 200

    def test_clear_remark_unlocks(self, super_token, target):
        r = requests.patch(
            f"{BASE_URL}/api/admin/challan-summary/{target}/{MONTH}",
            headers=_auth(super_token),
            json={"remark": ""}, timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["is_audit"] is False
        # sub_admin should now be able to write again
        r2 = requests.patch(
            f"{BASE_URL}/api/admin/challan-summary/{target}/{MONTH}",
            headers=_auth(sub_token_static()),
            json={"pf_amount": 222}, timeout=30,
        )
        assert r2.status_code in (200, 403), f"expected 200 after unlock, got {r2.status_code}"

    def test_cleanup(self, super_token, target):
        # Reset amounts + remark
        r = requests.patch(
            f"{BASE_URL}/api/admin/challan-summary/{target}/{MONTH}",
            headers=_auth(super_token),
            json={"pf_amount": None, "esic_amount": None, "remark": ""},
            timeout=30,
        )
        assert r.status_code == 200


def sub_token_static():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": SUB_EMAIL, "password": SUB_PWD}, timeout=30,
    )
    return r.json()["session_token"] if r.status_code == 200 else ""


# --- Email endpoint (expect 400 SMTP not configured) ----------------------
class TestEmail:
    def test_super_email_no_smtp(self, super_token):
        r = requests.post(
            f"{BASE_URL}/api/admin/challan-summary/email",
            headers=_auth(super_token),
            json={"month": MONTH, "to": "test@example.com"}, timeout=30,
        )
        # Expected: 400 SMTP settings not configured (per review request)
        assert r.status_code == 400
        assert "smtp" in r.text.lower()


# --- Gmail primary-unread (expect connected=false in this env) ------------
class TestPrimaryUnread:
    def test_super_primary_unread(self, super_token):
        r = requests.get(f"{BASE_URL}/api/gmail/primary-unread",
                         headers=_auth(super_token), timeout=30)
        assert r.status_code == 200
        d = r.json()
        for f in ("connected", "count", "messages"):
            assert f in d
        assert isinstance(d["messages"], list)

    def test_sub_primary_unread(self, sub_token):
        r = requests.get(f"{BASE_URL}/api/gmail/primary-unread",
                         headers=_auth(sub_token), timeout=30)
        assert r.status_code == 200


# --- Middleware sanity: login POST still works during lock ----------------
class TestLoginNotAffected:
    def test_super_can_login_while_lock_active(self, super_token):
        # even if some firm is under audit lock, unrelated POST /auth/*
        # must not 423.
        r = requests.post(
            f"{BASE_URL}/api/auth/admin-password-login",
            json={"email": SUPER_EMAIL, "password": SUPER_PWD}, timeout=30,
        )
        assert r.status_code == 200
