"""Iter 739 — BRANCH-WISE LICENSES & STATUTORY COMPLIANCE backend tests.

Covers all statutory endpoints appended to /api/admin/branch-master/*:
  - GET  /statutory/catalog
  - POST /statutory/catalog (add custom type)
  - PATCH /statutory/catalog (deactivate)
  - POST /statutory/warn-days (validation + set + reset)
  - POST /{branch}/licenses (full fields, no_expiry, expiring, expired, invalid dates)
  - PATCH /licenses/{doc_id} (field edit + attachment replace history)
  - Renewal via replace_same_type (old row → status=replaced, kept in list)
  - GET  /{branch}/compliance-summary (PF/ESIC/PT applicable, LWF NOT applicable)
  - GET  /{branch}/dashboard (statutory_docs counts)
  - GET  /statutory/register?fmt=xlsx (PK magic bytes)
  - REGRESSION: Iter737 endpoints
Cleanup at teardown: drops all test branches, docs, audit rows, catalog customs,
resets warn_days to 60 (default).
"""
import os
import sys
import base64
import datetime as dt
import pytest
import requests

sys.path.insert(0, "/app/test_reports/helpers")
from login_super_admin import login as _super_login  # type: ignore

BASE = os.environ.get('EXPO_PUBLIC_BACKEND_URL',
                      'https://emplo-connect-1.preview.emergentagent.com').rstrip('/')
API = f"{BASE}/api"
CID = "cmp_527fecdd7c"

# 1x1 transparent png (tiny base64)
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0"
    "C8AAAAASUVORK5CYII="
)


@pytest.fixture(scope="module")
def token():
    return _super_login()


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def state():
    return {
        "branches": [],
        "docs": [],
        "custom_catalog": [],  # (category, doc_type) added by test
        "toggled_catalog": [],  # (category, doc_type) deactivated by test
    }


def teardown_module(module):  # noqa
    from pymongo import MongoClient
    from dotenv import load_dotenv
    load_dotenv('/app/backend/.env')
    db = MongoClient(os.environ['MONGO_URL'])[os.environ.get('DB_NAME', 'test_database')]
    st = getattr(module, "_state", None) or {}
    for bid in st.get("branches", []):
        db.branch_documents.delete_many({"branch_id": bid})
        db.branch_audit.delete_many({"branch_id": bid})
        db.branches.delete_one({"branch_id": bid})
    # remove custom/override catalog entries created by tests
    for cat, dt_ in st.get("custom_catalog", []):
        db.statutory_doc_master.delete_one({"category": cat, "doc_type": dt_})
    for cat, dt_ in st.get("toggled_catalog", []):
        # only delete if it was a BUILT-IN we toggled (record exists purely to
        # store 'active: false'); safe to drop → catalog defaults back to true
        db.statutory_doc_master.delete_one({"category": cat, "doc_type": dt_})
    # reset warn days
    db.companies.update_one({"company_id": CID},
                            {"$set": {"statutory_alert_days": 60}})


@pytest.fixture(scope="module", autouse=True)
def _stash(request, state):
    yield
    setattr(sys.modules[__name__], "_state", state)


# ═══════════════════ 1. STATUTORY CATALOG ═══════════════════
class TestCatalog:
    def test_catalog_has_15_categories_pf_has_8(self, h):
        r = requests.get(f"{API}/admin/branch-master/statutory/catalog",
                         params={"company_id": CID}, headers=h, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        cats = data["categories"]
        assert len(cats) == 15, f"expected 15 categories, got {len(cats)}"
        assert "warn_days" in data
        pf = next((c for c in cats if c["category"] == "EPFO / PF"), None)
        assert pf is not None, "EPFO / PF missing"
        assert len(pf["types"]) == 8, f"PF should have 8 types, got {len(pf['types'])}"
        # all types active by default
        assert all(t["active"] for t in pf["types"])

    def test_catalog_add_custom(self, h, state):
        r = requests.post(f"{API}/admin/branch-master/statutory/catalog",
                          json={"category": "EPFO / PF",
                                "doc_type": "TEST_Custom_PF_Doc",
                                "state": "Rajasthan"},
                          headers=h, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True
        state["custom_catalog"].append(("EPFO / PF", "TEST_Custom_PF_Doc"))
        # verify shown in catalog with custom:true
        cat = requests.get(f"{API}/admin/branch-master/statutory/catalog",
                           params={"company_id": CID}, headers=h, timeout=30).json()
        pf = next(c for c in cat["categories"] if c["category"] == "EPFO / PF")
        custom = next((t for t in pf["types"]
                       if t["doc_type"] == "TEST_Custom_PF_Doc"), None)
        assert custom is not None and custom.get("custom") is True

    def test_catalog_add_missing_field_400(self, h):
        r = requests.post(f"{API}/admin/branch-master/statutory/catalog",
                          json={"category": "EPFO / PF"}, headers=h, timeout=30)
        assert r.status_code == 400

    def test_catalog_deactivate_builtin_type(self, h, state):
        # deactivate a built-in ESIC type; verify active:false in catalog
        target = "ESIC Other Document"
        r = requests.patch(f"{API}/admin/branch-master/statutory/catalog",
                           json={"category": "ESIC",
                                 "doc_type": target, "active": False},
                           headers=h, timeout=30)
        assert r.status_code == 200, r.text
        state["toggled_catalog"].append(("ESIC", target))
        cat = requests.get(f"{API}/admin/branch-master/statutory/catalog",
                           params={"company_id": CID}, headers=h, timeout=30).json()
        esic = next(c for c in cat["categories"] if c["category"] == "ESIC")
        row = next((t for t in esic["types"] if t["doc_type"] == target), None)
        assert row is not None
        assert row["active"] is False, "deactivate did not persist"

    def test_catalog_delete_method_not_allowed(self, h):
        r = requests.delete(f"{API}/admin/branch-master/statutory/catalog",
                            headers=h, timeout=30)
        assert r.status_code == 405, f"expected 405 got {r.status_code}"


# ═══════════════════ 2. WARN DAYS ═══════════════════
class TestWarnDays:
    def test_warn_days_bad_value_400(self, h):
        r = requests.post(f"{API}/admin/branch-master/statutory/warn-days",
                          json={"company_id": CID, "days": 45},
                          headers=h, timeout=30)
        assert r.status_code == 400
        assert "30" in r.json()["detail"]

    def test_warn_days_set_30(self, h):
        r = requests.post(f"{API}/admin/branch-master/statutory/warn-days",
                          json={"company_id": CID, "days": 30},
                          headers=h, timeout=30)
        assert r.status_code == 200
        assert r.json()["days"] == 30
        # catalog should reflect
        cat = requests.get(f"{API}/admin/branch-master/statutory/catalog",
                           params={"company_id": CID}, headers=h, timeout=30).json()
        assert cat["warn_days"] == 30

    def test_warn_days_reset_60(self, h):
        r = requests.post(f"{API}/admin/branch-master/statutory/warn-days",
                          json={"company_id": CID, "days": 60},
                          headers=h, timeout=30)
        assert r.status_code == 200
        assert r.json()["days"] == 60


# ═══════════════════ 3. BRANCH + LICENSES ═══════════════════
@pytest.fixture(scope="module")
def branch_id(h, state):
    """Create one test branch for license flows and PATCH compliance flags."""
    r = requests.post(f"{API}/admin/branch-master/create",
                      json={"company_id": CID,
                            "name": "TEST_BR_Iter739_Statutory",
                            "code": "TEST739A", "branch_type": "Branch",
                            "state": "Rajasthan"},
                      headers=h, timeout=30)
    assert r.status_code == 200, r.text
    bid = r.json()["branch"]["branch_id"]
    state["branches"].append(bid)
    # set compliance flags: PF/ESIC/PT applicable, LWF NOT applicable
    p = requests.patch(f"{API}/admin/branch-master/{bid}",
                       json={"compliance_config": {
                           "pf_applicable": True, "esic_applicable": True,
                           "pt_applicable": True, "lwf_applicable": False}},
                       headers=h, timeout=30)
    assert p.status_code == 200, p.text
    return bid


class TestLicenses:
    def test_license_full_no_expiry_active(self, h, branch_id, state):
        payload = {
            "category": "EPFO / PF", "doc_type": "PF Registration Certificate",
            "doc_name": "TEST PF Cert", "doc_number": "TEST-PF-A1",
            "establishment_code": "RJ/BHL/12345",
            "issuing_authority": "EPFO Bhilwara",
            "state": "Rajasthan", "effective_from": "2020-01-01",
            "no_expiry": True, "applicable": True,
            "remarks": "TEST iter739",
            "file_base64": _TINY_PNG_B64, "file_name": "pf_cert.png",
        }
        r = requests.post(f"{API}/admin/branch-master/{branch_id}/licenses",
                          json=payload, headers=h, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()["document"]
        assert d["no_expiry"] is True
        assert d["applicable"] is True
        assert d["doc_number"] == "TEST-PF-A1"
        state["docs"].append(d["doc_id"])
        # verify list marks it as active
        lst = requests.get(f"{API}/admin/branch-master/{branch_id}/licenses",
                           headers=h, timeout=30).json()
        me = next(x for x in lst["documents"] if x["doc_id"] == d["doc_id"])
        assert me["expiry_status"] == "active"
        assert me["has_file"] is True

    def test_license_expiry_before_effective_400(self, h, branch_id):
        r = requests.post(f"{API}/admin/branch-master/{branch_id}/licenses",
                         json={"category": "ESIC",
                               "doc_type": "ESIC Registration Certificate",
                               "effective_from": "2022-01-01",
                               "expiry_date": "2021-06-01"},
                         headers=h, timeout=30)
        assert r.status_code == 400
        assert "expiry" in r.json()["detail"].lower()

    def test_license_expiring_soon(self, h, branch_id, state):
        # warn_days is 60 (reset above). Use date 20 days from today (< 60).
        target = (dt.date.today() + dt.timedelta(days=20)).isoformat()
        r = requests.post(f"{API}/admin/branch-master/{branch_id}/licenses",
                         json={"category": "ESIC",
                               "doc_type": "ESIC Registration Certificate",
                               "doc_number": "TEST-ESIC-EXP",
                               "effective_from": "2020-01-01",
                               "expiry_date": target},
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text
        state["docs"].append(r.json()["document"]["doc_id"])
        lst = requests.get(f"{API}/admin/branch-master/{branch_id}/licenses",
                           headers=h, timeout=30).json()
        me = next(x for x in lst["documents"] if x.get("doc_number") == "TEST-ESIC-EXP")
        assert me["expiry_status"] == "expiring_soon"

    def test_license_expired(self, h, branch_id, state):
        r = requests.post(f"{API}/admin/branch-master/{branch_id}/licenses",
                         json={"category": "Professional Tax (PT)",
                               "doc_type": "PT Registration Certificate",
                               "doc_number": "TEST-PT-EXP",
                               "effective_from": "2010-01-01",
                               "expiry_date": "2015-01-01"},
                         headers=h, timeout=30)
        assert r.status_code == 200
        state["docs"].append(r.json()["document"]["doc_id"])
        lst = requests.get(f"{API}/admin/branch-master/{branch_id}/licenses",
                           headers=h, timeout=30).json()
        me = next(x for x in lst["documents"] if x.get("doc_number") == "TEST-PT-EXP")
        assert me["expiry_status"] == "expired"

    def test_license_patch_edit_and_replace_attachment(self, h, branch_id, state):
        # target the PF doc created above
        doc_id = state["docs"][0]
        # edit doc_number + replace attachment
        big_b64 = base64.b64encode(b"replacement-file-content").decode()
        r = requests.patch(f"{API}/admin/branch-master/licenses/{doc_id}",
                           json={"doc_number": "TEST-PF-A1-V2",
                                 "file_base64": big_b64,
                                 "file_name": "pf_cert_v2.png"},
                           headers=h, timeout=30)
        assert r.status_code == 200, r.text
        fresh = r.json()["document"]
        assert fresh["doc_number"] == "TEST-PF-A1-V2"
        assert fresh["file_name"] == "pf_cert_v2.png"
        hist = fresh.get("attachment_history") or []
        assert len(hist) >= 1, "attachment_history not written"
        assert hist[-1]["file_name"] == "pf_cert.png", \
            "old file_name should be recorded in history"
        # verify branch_audit rows exist for this branch (edit + attachment)
        from pymongo import MongoClient
        from dotenv import load_dotenv
        load_dotenv('/app/backend/.env')
        db = MongoClient(os.environ['MONGO_URL'])[
            os.environ.get('DB_NAME', 'test_database')]
        cnt = db.branch_audit.count_documents({"branch_id": branch_id,
                                               "action": "license_update"})
        assert cnt >= 1

    def test_license_renewal_replace_same_type(self, h, branch_id, state):
        # renew PF (same category+doc_type) → old row remains as status=replaced
        r = requests.post(f"{API}/admin/branch-master/{branch_id}/licenses",
                         json={"category": "EPFO / PF",
                               "doc_type": "PF Registration Certificate",
                               "doc_number": "TEST-PF-RENEW",
                               "effective_from": "2024-01-01",
                               "no_expiry": True,
                               "replace_same_type": True},
                         headers=h, timeout=30)
        assert r.status_code == 200
        state["docs"].append(r.json()["document"]["doc_id"])
        lst = requests.get(f"{API}/admin/branch-master/{branch_id}/licenses",
                           headers=h, timeout=30).json()["documents"]
        pf_rows = [d for d in lst
                   if d.get("category") == "EPFO / PF"
                   and d.get("doc_type") == "PF Registration Certificate"]
        # both should be present: renewed + replaced
        statuses = [d.get("status") for d in pf_rows]
        assert "active" in statuses, f"missing active row: {statuses}"
        assert "replaced" in statuses, f"missing replaced row (history lost): {statuses}"
        # renewed row has correct doc_number
        active = next(d for d in pf_rows if d.get("status") == "active")
        assert active["doc_number"] == "TEST-PF-RENEW"


# ═══════════════════ 4. COMPLIANCE SUMMARY + DASHBOARD ═══════════════════
class TestComplianceSummary:
    def test_summary_rows_and_alerts(self, h, branch_id):
        r = requests.get(f"{API}/admin/branch-master/{branch_id}/compliance-summary",
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        rows = {row["compliance"]: row for row in j["compliances"]}
        # PF, ESIC, PT applicable=True; LWF applicable=False
        assert rows["PF"]["applicable"] is True
        assert rows["ESIC"]["applicable"] is True
        assert rows["PT"]["applicable"] is True
        assert rows["LWF"]["applicable"] is False
        assert rows["LWF"]["registration"] == "not_applicable"
        # Alerts: no LWF alert since not applicable
        assert all("LWF" not in a for a in j["alerts"]), \
            f"LWF alert should NOT appear when not applicable: {j['alerts']}"
        # PF is present + no expiry → active. PT expired must produce EXPIRED alert.
        assert rows["PF"]["registration"] == "active"
        assert rows["PT"]["registration"] == "expired"
        assert any("EXPIRED" in a for a in j["alerts"])

    def test_dashboard_has_statutory_counts(self, h, branch_id):
        r = requests.get(f"{API}/admin/branch-master/{branch_id}/dashboard",
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "statutory_docs" in d
        assert isinstance(d["statutory_docs"], dict)
        # PF (active), ESIC (expiring_soon), PT (expired) → at least 1 of each
        assert d["statutory_docs"].get("expired", 0) >= 1
        assert d["statutory_docs"].get("expiring_soon", 0) >= 1


# ═══════════════════ 5. REGISTER XLSX ═══════════════════
class TestRegisterXlsx:
    def test_register_xlsx(self, h):
        r = requests.get(f"{API}/admin/branch-master/statutory/register",
                         params={"company_id": CID, "fmt": "xlsx"},
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text
        # xlsx (zip) magic bytes = PK
        assert r.content[:2] == b"PK"
        # content-type
        ct = r.headers.get("content-type", "")
        assert "spreadsheet" in ct or "openxmlformats" in ct


# ═══════════════════ 6. REGRESSION — Iter 737 endpoints ═══════════════════
class TestRegression737:
    def test_branch_list(self, h):
        r = requests.get(f"{API}/admin/branch-master/list",
                         params={"company_id": CID}, headers=h, timeout=30)
        assert r.status_code == 200
        assert "branches" in r.json()

    def test_legacy_branches_list(self, h):
        r = requests.get(f"{API}/company/branches",
                         params={"company_id": CID}, headers=h, timeout=30)
        assert r.status_code == 200
        assert "branches" in r.json()

    def test_legacy_branches_create_and_delete(self, h, state):
        # Legacy create: name + gps only
        r = requests.post(f"{API}/company/branches",
                          json={"company_id": CID,
                                "name": "TEST_LEGACY_Iter739",
                                "office_lat": 25.35, "office_lng": 74.63,
                                "geofence_radius_m": 200},
                          headers=h, timeout=30)
        assert r.status_code == 200, r.text
        bid = r.json()["branch"]["branch_id"]
        state["branches"].append(bid)  # will be cleaned in teardown
        # branch with no employees/attendance/transfers → hard delete OK
        d = requests.delete(f"{API}/company/branches/{bid}", headers=h, timeout=30)
        assert d.status_code == 200
        # cleanup — remove from tracker (already deleted)
        state["branches"].remove(bid)

    def test_legacy_documents_endpoint(self, h, branch_id):
        # add a legacy doc so we can also verify counts endpoint works
        r = requests.get(f"{API}/admin/branch-master/{branch_id}/documents",
                         headers=h, timeout=30)
        assert r.status_code == 200
        assert "documents" in r.json()

    def test_delete_branch_with_only_docs_cascades(self, h, state):
        # Create a fresh branch, attach one license doc, then DELETE via legacy.
        # Per spec: docs-only branches delete fine (docs cascade). 200 expected.
        r = requests.post(f"{API}/admin/branch-master/create",
                          json={"company_id": CID,
                                "name": "TEST_BR_Iter739_DocsOnly",
                                "code": "TEST739D"}, headers=h, timeout=30)
        assert r.status_code == 200
        bid = r.json()["branch"]["branch_id"]
        state["branches"].append(bid)
        # add a doc
        dr = requests.post(f"{API}/admin/branch-master/{bid}/licenses",
                          json={"category": "EPFO / PF",
                                "doc_type": "PF Registration Certificate",
                                "no_expiry": True, "doc_number": "TEST-CASCADE"},
                          headers=h, timeout=30)
        assert dr.status_code == 200
        # legacy delete should succeed (cascade docs)
        dl = requests.delete(f"{API}/company/branches/{bid}", headers=h, timeout=30)
        assert dl.status_code == 200, f"docs-only branch should delete, got {dl.status_code}: {dl.text}"
        state["branches"].remove(bid)
