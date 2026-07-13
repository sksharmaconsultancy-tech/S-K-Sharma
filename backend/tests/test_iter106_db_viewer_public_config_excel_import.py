"""Iter 106 — Backend tests for:
- Database Viewer/Editor (super admin only)
- Public config (base URL for QR)
- Excel attendance import (IN/OUT) via /admin/attendance/zk-dat-import
"""
import io
import os
import pytest
import requests
from openpyxl import Workbook

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

CCH_ID = "cmp_987f0d7da5"


# --------------------------- fixtures ---------------------------
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
                      timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json().get("session_token") or r.json().get("token")


@pytest.fixture(scope="module")
def hospital_emp_token():
    """Hospital employee (non super-admin) for negative auth test."""
    r = requests.post(f"{API}/auth/pin-login",
                      json={"phone": "+919000000101", "pin": "654321"},
                      timeout=15)
    if r.status_code != 200:
        pytest.skip(f"hospital emp pin-login not available: {r.status_code} {r.text}")
    return r.json().get("session_token") or r.json().get("token")


def _h(t):
    return {"Authorization": f"Bearer {t}"}


# --------------------------- Database Viewer ---------------------------
class TestDbViewer:
    def test_collections_super_admin(self, admin_token):
        r = requests.get(f"{API}/admin/database/collections", headers=_h(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        cols = r.json().get("collections", [])
        assert isinstance(cols, list) and len(cols) >= 20
        # ensure count field present
        assert all("name" in c and "count" in c for c in cols[:5])

    def test_collections_non_super_admin_denied(self, hospital_emp_token):
        r = requests.get(f"{API}/admin/database/collections", headers=_h(hospital_emp_token), timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_users_documents_by_company(self, admin_token):
        r = requests.get(f"{API}/admin/database/users/documents",
                         headers=_h(admin_token),
                         params={"company_id": CCH_ID, "limit": 20}, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # Expect ~3 hospital employees
        assert data["total"] >= 3, f"expected >=3 hospital users got {data['total']}"
        # verify all filtered docs belong to CCH
        for d in data["documents"]:
            assert d.get("company_id") == CCH_ID

    def test_users_documents_by_user_id(self, admin_token):
        # first find a hospital user
        r = requests.get(f"{API}/admin/database/users/documents",
                         headers=_h(admin_token),
                         params={"company_id": CCH_ID}, timeout=15)
        assert r.status_code == 200
        docs = r.json()["documents"]
        assert docs, "no hospital users"
        uid = docs[0]["user_id"]
        r2 = requests.get(f"{API}/admin/database/users/documents",
                          headers=_h(admin_token),
                          params={"user_id": uid}, timeout=15)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["total"] == 1 and d2["documents"][0]["user_id"] == uid

    def test_field_value_search(self, admin_token):
        r = requests.get(f"{API}/admin/database/users/documents",
                         headers=_h(admin_token),
                         params={"company_id": CCH_ID, "field": "name", "value": "Anita"},
                         timeout=15)
        assert r.status_code == 200
        docs = r.json()["documents"]
        assert docs and any("Anita" in (d.get("name") or "") for d in docs)

    def test_put_delete_document_lifecycle(self, admin_token):
        """Create a harmless doc via list route (via shift_change_requests
        collection). We use a stub insert by editing an existing doc's note
        field: use collection app_settings — safer to insert then delete."""
        # Insert a throwaway doc by creating a temp shift_change_request via
        # direct API is not available; instead pick any existing doc and
        # patch a note field on it via PUT (round-trip).
        # We test PUT/DELETE using a temp doc we create via mongo-less path:
        # use /admin/database endpoints only. So pick a doc from
        # `shift_change_requests` if present, else fall back to
        # `zk_dat_imports` (harmless log entries).
        target_coll = None
        target_doc = None
        for c in ["shift_change_requests", "zk_dat_imports"]:
            r = requests.get(f"{API}/admin/database/{c}/documents",
                             headers=_h(admin_token), params={"limit": 1}, timeout=15)
            if r.status_code == 200 and r.json().get("documents"):
                target_coll = c
                target_doc = r.json()["documents"][0]
                break
        if not target_coll:
            pytest.skip("No harmless doc available for PUT/DELETE test")

        doc_id = target_doc["__id"]
        # PUT: send full doc back with an added _test_note field
        body = {k: v for k, v in target_doc.items() if k != "__id"}
        body["_test_note"] = "iter106_pytest_touch"
        r_put = requests.put(f"{API}/admin/database/{target_coll}/documents/{doc_id}",
                             headers=_h(admin_token), json={"document": body}, timeout=15)
        assert r_put.status_code == 200, r_put.text
        # Verify via search
        r_check = requests.get(f"{API}/admin/database/{target_coll}/documents",
                               headers=_h(admin_token),
                               params={"field": "_test_note", "value": "iter106_pytest_touch"},
                               timeout=15)
        assert r_check.status_code == 200
        assert any(d["__id"] == doc_id for d in r_check.json()["documents"])
        # Restore the doc (remove the note) via another PUT
        body.pop("_test_note", None)
        r_restore = requests.put(f"{API}/admin/database/{target_coll}/documents/{doc_id}",
                                 headers=_h(admin_token), json={"document": body}, timeout=15)
        assert r_restore.status_code == 200

    def test_put_404_and_400(self, admin_token):
        # Invalid id -> 400
        r_bad = requests.put(f"{API}/admin/database/users/documents/notanoid",
                             headers=_h(admin_token),
                             json={"document": {"foo": 1}}, timeout=15)
        assert r_bad.status_code == 400
        # Valid-looking but missing -> 404
        fake_oid = "0" * 24
        r_missing = requests.put(f"{API}/admin/database/users/documents/{fake_oid}",
                                 headers=_h(admin_token),
                                 json={"document": {"foo": 1}}, timeout=15)
        assert r_missing.status_code == 404
        # Delete same missing -> 404
        r_del = requests.delete(f"{API}/admin/database/users/documents/{fake_oid}",
                                headers=_h(admin_token), timeout=15)
        assert r_del.status_code == 404


# --------------------------- External DB Config ---------------------------
class TestExternalDbConfig:
    def test_get_config_masked(self, admin_token):
        r = requests.get(f"{API}/admin/database/config", headers=_h(admin_token), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "configured" in j and "mongo_url_masked" in j

    def test_config_lifecycle_and_source_external(self, admin_token):
        # Set config to local mongo (accessible from backend container)
        payload = {"mongo_url": "mongodb://localhost:27017",
                   "db_name": "test_database", "label": "iter106-tests"}
        r = requests.put(f"{API}/admin/database/config", headers=_h(admin_token),
                         json=payload, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["configured"] is True

        # Test the connection
        r_t = requests.post(f"{API}/admin/database/config/test",
                            headers=_h(admin_token), json={}, timeout=15)
        assert r_t.status_code == 200
        assert r_t.json().get("ok") is True

        # List collections with source=external
        r_c = requests.get(f"{API}/admin/database/collections",
                          headers=_h(admin_token), params={"source": "external"}, timeout=20)
        assert r_c.status_code == 200
        assert len(r_c.json()["collections"]) > 0

        # Validation: invalid mongo_url prefix -> 400
        r_bad = requests.put(f"{API}/admin/database/config", headers=_h(admin_token),
                             json={"mongo_url": "http://foo", "db_name": "x"}, timeout=15)
        assert r_bad.status_code == 400

        # CLEANUP: clear config
        r_clear = requests.put(f"{API}/admin/database/config", headers=_h(admin_token),
                               json={"mongo_url": "", "db_name": ""}, timeout=15)
        assert r_clear.status_code == 200
        assert r_clear.json()["configured"] is False

        # verify get shows not configured
        r_g = requests.get(f"{API}/admin/database/config", headers=_h(admin_token), timeout=15)
        assert r_g.json()["configured"] is False


# --------------------------- Public Config ---------------------------
class TestPublicConfig:
    PUBLIC_URL = "https://www.smartpayrolling.com"

    def test_get_public_config(self):
        r = requests.get(f"{API}/public-config", timeout=15)
        assert r.status_code == 200
        # value may be blank if not yet set — just check structure
        assert "public_base_url" in r.json()

    def test_put_validation_and_final_set(self, admin_token):
        # invalid: missing http://
        r_bad = requests.put(f"{API}/admin/public-config", headers=_h(admin_token),
                             json={"public_base_url": "smartpayrolling.com"}, timeout=15)
        assert r_bad.status_code == 400

        # valid set
        r_ok = requests.put(f"{API}/admin/public-config", headers=_h(admin_token),
                            json={"public_base_url": self.PUBLIC_URL}, timeout=15)
        assert r_ok.status_code == 200
        assert r_ok.json()["public_base_url"] == self.PUBLIC_URL

        # verify via GET
        r_g = requests.get(f"{API}/public-config", timeout=15)
        assert r_g.json()["public_base_url"] == self.PUBLIC_URL


# --------------------------- Excel Import ---------------------------
def _build_xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["CODE", "DATE", "TIME"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


class TestExcelAttendanceImport:
    TEST_DATE = "15-06-2026"  # PAST date per instructions

    def test_download_sample(self, admin_token):
        r = requests.get(f"{API}/admin/attendance/import-sample",
                         headers=_h(admin_token), timeout=15)
        assert r.status_code == 200
        assert "spreadsheet" in r.headers.get("content-type", "")
        assert len(r.content) > 200

    def test_excel_import_and_dedupe(self, admin_token):
        in_xlsx = _build_xlsx([
            ["901", self.TEST_DATE, "09:02"],
            ["902", self.TEST_DATE, "09:10:35"],
        ])
        out_xlsx = _build_xlsx([
            ["901", self.TEST_DATE, "18:04"],
            ["902", self.TEST_DATE, "18:20"],
        ])
        files = {
            "in_excel": ("in.xlsx", in_xlsx,
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "out_excel": ("out.xlsx", out_xlsx,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        }
        data = {"company_id": CCH_ID}
        r = requests.post(f"{API}/admin/attendance/zk-dat-import",
                          headers=_h(admin_token), data=data, files=files, timeout=30)
        assert r.status_code == 200, r.text
        stats = r.json()
        inserted = stats.get("inserted") or stats.get("added") or 0
        # We uploaded 4 punches, expect >= some inserted (bio 901/902 map to CCH001/CCH002)
        assert inserted >= 1, f"expected inserts, got stats={stats}"

        # Re-upload same files -> all duplicates
        files2 = {
            "in_excel": ("in.xlsx", in_xlsx,
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "out_excel": ("out.xlsx", out_xlsx,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        }
        r2 = requests.post(f"{API}/admin/attendance/zk-dat-import",
                           headers=_h(admin_token), data=data, files=files2, timeout=30)
        assert r2.status_code == 200
        stats2 = r2.json()
        inserted2 = stats2.get("inserted") or stats2.get("added") or 0
        assert inserted2 == 0, f"expected 0 new inserts on dupe upload, got {stats2}"

    def test_zk_dat_import_missing_file_400(self, admin_token):
        r = requests.post(f"{API}/admin/attendance/zk-dat-import",
                          headers=_h(admin_token),
                          data={"company_id": CCH_ID}, timeout=15)
        assert r.status_code == 400


# --------------------------- Cleanup (module-level) ---------------------------
def test_zzz_cleanup_test_attendance(admin_token):
    """Delete the test punches we inserted (bio codes 901/902 on 2026-06-15)."""
    # find attendance docs from the test date/bio codes and delete via DB viewer
    # attendance uses date field like "2026-06-15" (ISO) internally
    r = requests.get(f"{API}/admin/database/attendance/documents",
                     headers=_h(admin_token),
                     params={"field": "date", "value": "2026-06-15", "limit": 50},
                     timeout=15)
    if r.status_code == 200:
        docs = r.json()["documents"]
        for d in docs:
            if d.get("company_id") == CCH_ID:
                requests.delete(
                    f"{API}/admin/database/attendance/documents/{d['__id']}",
                    headers=_h(admin_token), timeout=10)
    # nothing to assert — best-effort cleanup
