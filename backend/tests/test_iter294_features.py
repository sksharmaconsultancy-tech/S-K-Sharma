"""Iter 294 backend regression — AI assistant, global search, group STAFF fix,
bank transfer, BI feed, biometric multi-brand + webhook."""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
KANKANI = "cmp_527fecdd7c"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
                      timeout=20)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("session_token")
    assert tok, f"No session_token: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def hdrs(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ---------- AI Assistant ----------
class TestAIAssistant:
    def test_process_payroll_command(self, hdrs):
        r = requests.post(f"{BASE_URL}/api/admin/ai-assistant/command",
                          json={"text": "Process June 2026 payroll for Kankani"},
                          headers=hdrs, timeout=45)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data.get("intent") == "process_payroll", data
        action = data.get("action")
        assert action, "no action returned"
        assert action.get("type") == "confirm_api", action

    def test_attendance_summary(self, hdrs):
        r = requests.post(f"{BASE_URL}/api/admin/ai-assistant/command",
                          json={"text": "who is present today", "company_id": KANKANI},
                          headers=hdrs, timeout=45)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data.get("intent") == "attendance_summary", data

    def test_pending_approvals(self, hdrs):
        r = requests.post(f"{BASE_URL}/api/admin/ai-assistant/command",
                          json={"text": "pending approvals", "company_id": KANKANI},
                          headers=hdrs, timeout=45)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("intent") == "pending_approvals"

    def test_navigate_attendance_report(self, hdrs):
        r = requests.post(f"{BASE_URL}/api/admin/ai-assistant/command",
                          json={"text": "open attendance report"},
                          headers=hdrs, timeout=45)
        assert r.status_code == 200
        data = r.json()
        assert data.get("intent") == "navigate"
        action = data.get("action") or {}
        assert action.get("type") == "navigate"
        assert "attendance" in (action.get("route") or "")

    def test_history(self, hdrs):
        r = requests.get(f"{BASE_URL}/api/admin/ai-assistant/history", headers=hdrs, timeout=15)
        assert r.status_code == 200
        assert "messages" in r.json()


# ---------- Global Search ----------
class TestGlobalSearch:
    def test_search_suren(self, hdrs):
        r = requests.get(f"{BASE_URL}/api/admin/global-search",
                         params={"q": "suren"}, headers=hdrs, timeout=15)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "employees" in data
        emps = data["employees"]
        assert len(emps) >= 1, "expected SURENDRA SINGH match"
        assert any("SUREN" in (e.get("name") or "").upper() for e in emps)
        assert all("firm_name" in e for e in emps)

    def test_short_query_rejected(self, hdrs):
        r = requests.get(f"{BASE_URL}/api/admin/global-search",
                         params={"q": "s"}, headers=hdrs, timeout=15)
        assert r.status_code == 422, r.status_code


# ---------- Group Master STAFF fix ----------
class TestGroupMaster:
    def test_staff_group_present(self, hdrs):
        r = requests.get(f"{BASE_URL}/api/admin/masters",
                         params={"type": "group", "company_id": KANKANI},
                         headers=hdrs, timeout=15)
        assert r.status_code == 200, r.text[:300]
        payload = r.json()
        rows = payload if isinstance(payload, list) else payload.get("rows") or payload.get("items") or []
        names = [ (row.get("name") or row.get("label") or "").upper() for row in rows ]
        assert any("STAFF" == n for n in names), f"STAFF group missing. Got: {names}"


# ---------- Bank Transfer ----------
class TestBankTransfer:
    def test_formats(self, hdrs):
        r = requests.get(f"{BASE_URL}/api/admin/bank-transfer/formats", headers=hdrs, timeout=15)
        assert r.status_code == 200
        data = r.json()
        banks = data.get("banks") or []
        assert len(banks) == 6, f"expected 6 banks got {len(banks)}"
        keys = {b["key"] for b in banks}
        assert keys == {"icici", "hdfc", "sbi", "axis", "kotak", "generic"}, keys
        assert set(data.get("file_types") or []) == {"xlsx", "csv", "txt", "xml"}

    def test_file_download(self, hdrs):
        # try several months to find a compliance run
        for month in ["2026-07", "2026-06", "2026-05", "2026-04", "2026-03", "2026-02", "2026-01"]:
            r = requests.get(f"{BASE_URL}/api/admin/bank-transfer/file",
                             params={"month": month, "bank": "icici", "fmt": "csv",
                                     "company_id": KANKANI},
                             headers=hdrs, timeout=30)
            if r.status_code == 200:
                assert "attachment" in r.headers.get("content-disposition", "").lower()
                assert len(r.content) > 20
                return
        # None found — verify last response is a friendly 404
        assert r.status_code == 404, f"expected 404 friendly error, got {r.status_code} {r.text[:200]}"
        assert "compliance" in r.text.lower() or "payable" in r.text.lower()


# ---------- BI Feed ----------
class TestBIFeed:
    _key = None

    def test_rotate_key(self, hdrs):
        r = requests.post(f"{BASE_URL}/api/admin/bi-feed/rotate-key",
                          json={"company_id": KANKANI}, headers=hdrs, timeout=15)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data.get("ok") is True
        key = data.get("key")
        assert key and key.startswith("bif_")
        TestBIFeed._key = key

    def test_employees_no_pii(self):
        assert TestBIFeed._key, "run test_rotate_key first"
        r = requests.get(f"{BASE_URL}/api/bi-feed/employees",
                         params={"key": TestBIFeed._key}, timeout=20)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        rows = data.get("rows") or []
        assert len(rows) > 0
        for row in rows[:5]:
            for banned in ("aadhaar", "pan", "bank_account", "account_no"):
                assert banned not in row, f"BI feed exposes {banned}: {row}"

    def test_attendance_feed(self):
        assert TestBIFeed._key
        r = requests.get(f"{BASE_URL}/api/bi-feed/attendance",
                         params={"key": TestBIFeed._key, "month": "2026-07"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert "rows" in r.json()

    def test_invalid_key(self):
        r = requests.get(f"{BASE_URL}/api/bi-feed/employees",
                         params={"key": "bif_invalidkey_xxxxxx"}, timeout=15)
        assert r.status_code == 401


# ---------- Biometric multi-brand + webhook ----------
class TestBiometric:
    _device_id = None
    _webhook_key = None

    def test_register_matrix_device(self, hdrs):
        payload = {
            "serial_number": f"TEST_MATRIX_{int(time.time())}",
            "name": "TEST Matrix device (iter294)",
            "kind": "both",
            "company_id": KANKANI,
            "brand": "matrix",
            "enabled": True,
        }
        r = requests.post(f"{BASE_URL}/api/biometric/devices",
                          json=payload, headers=hdrs, timeout=15)
        assert r.status_code == 200, r.text[:400]
        d = r.json().get("device") or {}
        assert d.get("brand") == "matrix", f"brand not persisted: {d}"
        assert d.get("webhook_key"), "webhook_key missing"
        TestBiometric._device_id = d["device_id"]
        TestBiometric._webhook_key = d["webhook_key"]

    def test_webhook_ingest_punch(self):
        assert TestBiometric._webhook_key
        body = {"punches": [
            {"user_id": "72", "timestamp": "2026-07-25 09:00:00", "direction": "in"}
        ]}
        r = requests.post(f"{BASE_URL}/api/device-webhook/{TestBiometric._webhook_key}",
                          json=body, timeout=15)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        # first push should be inserted (or duplicate if run twice)
        assert data.get("inserted", 0) + data.get("skipped", 0) >= 1

    def test_webhook_duplicate_skipped(self):
        assert TestBiometric._webhook_key
        body = {"punches": [
            {"user_id": "72", "timestamp": "2026-07-25 09:00:00", "direction": "in"}
        ]}
        r = requests.post(f"{BASE_URL}/api/device-webhook/{TestBiometric._webhook_key}",
                          json=body, timeout=15)
        assert r.status_code == 200
        # This resend should be skipped as duplicate
        assert r.json().get("skipped", 0) >= 1

    def test_webhook_invalid_key(self):
        r = requests.post(f"{BASE_URL}/api/device-webhook/notavalidkey123",
                          json={"punches": []}, timeout=15)
        assert r.status_code == 404

    def test_regenerate_webhook_key(self, hdrs):
        assert TestBiometric._device_id
        r = requests.post(
            f"{BASE_URL}/api/biometric/devices/{TestBiometric._device_id}/regenerate-webhook-key",
            headers=hdrs, timeout=15)
        assert r.status_code == 200, r.text[:300]
        new_key = r.json().get("webhook_key")
        assert new_key and new_key != TestBiometric._webhook_key

    def test_zzz_cleanup_device(self, hdrs):
        """Runs last (zzz prefix) — deletes the test device + punch row."""
        if TestBiometric._device_id:
            r = requests.delete(
                f"{BASE_URL}/api/biometric/devices/{TestBiometric._device_id}",
                headers=hdrs, timeout=15)
            assert r.status_code in (200, 204), r.text[:200]
        # Clean up the attendance row we inserted via webhook (safety)
        # This is best-effort — direct DB access not available from tests.
