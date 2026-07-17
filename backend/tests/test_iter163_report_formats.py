"""Iter 163 — Backend tests for Utilities → PDF Report Formats.

Covers:
  - Super-admin password login → session_token
  - GET /api/admin/report-formats list (4 reports)
  - GET /api/admin/report-formats/{id} for tabular & fixed reports
  - PUT save + apply to ecr.pdf / esic-challan.pdf (pdfminer text extraction)
  - DELETE reset + verify default title/columns come back
  - Validation errors (empty columns, bad orientation, unknown id)
  - Cleanup: DELETE all saved formats at the end
"""
import io
import os
import pytest
import requests
from pdfminer.high_level import extract_text

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PASSWORD = "sharma123"
COMPANY_ID = "cmp_527fecdd7c"
MONTH = "2026-07"


@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{API}/auth/admin-password-login",
                      json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD},
                      timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("session_token")
    assert tok, "no session_token in login response"
    return tok


@pytest.fixture(scope="module")
def hdr(super_token):
    return {"Authorization": f"Bearer {super_token}"}


@pytest.fixture(scope="module", autouse=True)
def _cleanup(hdr):
    # Ensure clean state before + after
    for rid in ("pf_ecr", "pf_challan", "esic_contribution", "esic_challan"):
        requests.delete(f"{API}/admin/report-formats/{rid}", headers=hdr, timeout=30)
    yield
    for rid in ("pf_ecr", "pf_challan", "esic_contribution", "esic_challan"):
        requests.delete(f"{API}/admin/report-formats/{rid}", headers=hdr, timeout=30)


# ---------------- list & get ----------------
class TestListAndGet:
    def test_list_returns_4_reports(self, hdr):
        r = requests.get(f"{API}/admin/report-formats", headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        items = r.json().get("reports") or []
        ids = {it["report_id"] for it in items}
        assert ids == {"pf_ecr", "pf_challan", "esic_contribution", "esic_challan"}, ids
        # fields
        for it in items:
            assert "label" in it and "group" in it and "has_columns" in it
            assert "saved" in it
        # has_columns per spec
        by_id = {it["report_id"]: it for it in items}
        assert by_id["pf_ecr"]["has_columns"] is True
        assert by_id["esic_contribution"]["has_columns"] is True
        assert by_id["pf_challan"]["has_columns"] is False
        assert by_id["esic_challan"]["has_columns"] is False
        assert by_id["pf_ecr"]["group"] == "PF Reports"
        assert by_id["esic_contribution"]["group"] == "ESIC Reports"

    def test_list_forbidden_without_auth(self):
        r = requests.get(f"{API}/admin/report-formats", timeout=30)
        assert r.status_code in (401, 403), r.status_code

    def test_get_pf_ecr_catalog(self, hdr):
        r = requests.get(f"{API}/admin/report-formats/pf_ecr", headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["report_id"] == "pf_ecr"
        assert isinstance(d["catalog"], list) and len(d["catalog"]) == 12
        # ensure known columns present
        keys = [c["key"] for c in d["catalog"]]
        for k in ("sl", "uan", "name", "epf_wages", "refund"):
            assert k in keys
        assert d["defaults"]["orientation"] == "landscape"
        assert "PROVIDENT FUND" in d["defaults"]["title"].upper()

    def test_get_pf_challan_no_catalog(self, hdr):
        r = requests.get(f"{API}/admin/report-formats/pf_challan", headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["catalog"] is None

    def test_get_unknown_report_404(self, hdr):
        r = requests.get(f"{API}/admin/report-formats/does_not_exist", headers=hdr, timeout=30)
        assert r.status_code == 404


# ---------------- PUT + PDF apply ----------------
class TestPutAndApply:
    def test_put_pf_ecr_applies_to_ecr_pdf(self, hdr):
        payload = {
            "columns": [
                {"key": "sl"},
                {"key": "uan", "heading": "UAN Number"},
                {"key": "name"},
                {"key": "epf_wages", "width": 30},
            ],
            "orientation": "portrait",
            "font_size": 9,
            "title": "CUSTOM EPFO TITLE",
        }
        r = requests.put(f"{API}/admin/report-formats/pf_ecr", headers=hdr,
                         json=payload, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # Download PDF
        url = f"{API}/admin/pf-reports/ecr.pdf"
        pr = requests.get(url, headers=hdr,
                          params={"company_id": COMPANY_ID,
                                  "month_from": MONTH, "month_to": MONTH},
                          timeout=90)
        assert pr.status_code == 200, f"pdf status {pr.status_code}: {pr.text[:200]}"
        assert pr.content[:4] == b"%PDF", "not a PDF"
        text = extract_text(io.BytesIO(pr.content))
        assert "CUSTOM EPFO TITLE" in text, f"custom title missing. sample: {text[:400]}"
        assert "UAN Number" in text, "renamed UAN heading missing"
        assert "Refunds" not in text, "excluded 'Refunds' column still present"

    def test_put_esic_challan_applies(self, hdr):
        r = requests.put(f"{API}/admin/report-formats/esic_challan", headers=hdr,
                         json={"title": "CUSTOM ESIC TITLE", "font_size": 10},
                         timeout=30)
        assert r.status_code == 200, r.text
        pr = requests.get(f"{API}/admin/pf-reports/esic-challan.pdf", headers=hdr,
                          params={"company_id": COMPANY_ID,
                                  "month_from": MONTH, "month_to": MONTH},
                          timeout=90)
        assert pr.status_code == 200, f"pdf status {pr.status_code}: {pr.text[:200]}"
        assert pr.content[:4] == b"%PDF"
        text = extract_text(io.BytesIO(pr.content))
        assert "CUSTOM ESIC TITLE" in text, f"custom title missing. sample: {text[:400]}"


# ---------------- DELETE / reset ----------------
class TestReset:
    def test_delete_pf_ecr_restores_default(self, hdr):
        # Ensure a saved format is in place (idempotent PUT)
        requests.put(f"{API}/admin/report-formats/pf_ecr", headers=hdr,
                     json={"title": "TMP", "columns": [{"key": "sl"}]}, timeout=30)
        r = requests.delete(f"{API}/admin/report-formats/pf_ecr", headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        # GET should show saved False
        g = requests.get(f"{API}/admin/report-formats/pf_ecr", headers=hdr, timeout=30).json()
        assert g.get("format") in (None, {}), g

        pr = requests.get(f"{API}/admin/pf-reports/ecr.pdf", headers=hdr,
                          params={"company_id": COMPANY_ID,
                                  "month_from": MONTH, "month_to": MONTH},
                          timeout=90)
        assert pr.status_code == 200, pr.text[:200]
        text = extract_text(io.BytesIO(pr.content))
        assert "EMPLOYEE'S PROVIDENT FUND ORGANISATION" in text, \
            f"default title missing. sample: {text[:400]}"
        assert "Refunds" in text, "default 'Refunds' column missing after reset"

    def test_delete_esic_challan_restores_default(self, hdr):
        requests.delete(f"{API}/admin/report-formats/esic_challan", headers=hdr, timeout=30)
        pr = requests.get(f"{API}/admin/pf-reports/esic-challan.pdf", headers=hdr,
                          params={"company_id": COMPANY_ID,
                                  "month_from": MONTH, "month_to": MONTH},
                          timeout=90)
        assert pr.status_code == 200
        text = extract_text(io.BytesIO(pr.content))
        assert "CUSTOM ESIC TITLE" not in text, "custom title still present after DELETE"


# ---------------- Validation ----------------
class TestValidation:
    def test_put_empty_columns_400(self, hdr):
        r = requests.put(f"{API}/admin/report-formats/pf_ecr", headers=hdr,
                         json={"columns": []}, timeout=30)
        assert r.status_code == 400, r.status_code

    def test_put_bad_orientation_400(self, hdr):
        r = requests.put(f"{API}/admin/report-formats/pf_ecr", headers=hdr,
                         json={"orientation": "diagonal",
                               "columns": [{"key": "sl"}]}, timeout=30)
        assert r.status_code == 400, r.status_code

    def test_put_unknown_report_404(self, hdr):
        r = requests.put(f"{API}/admin/report-formats/no_such", headers=hdr,
                         json={"title": "x"}, timeout=30)
        assert r.status_code == 404, r.status_code
