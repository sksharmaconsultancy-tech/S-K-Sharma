"""Iter 479 backend tests — Contractor Master, CLRA Reports, Daily Verification.

Covers:
- Contractor CRUD + duplicate check
- 6 CLRA reports (JSON + xlsx + pdf)
- Email-report endpoint (graceful)
- Daily Verification 'present_only' filter
- Daily Verification PDF (landscape/portrait) content checks
"""
import os
import io
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
COMPANY_ID = "cmp_527fecdd7c"
MONTH = "2026-07"
DATE = "2026-07-15"

CLRA_KINDS = [
    "contractor-register",
    "principal-employer",
    "contract-labour-register",
    "pt-register",
    "rejoin-history",
    "compliance-dashboard",
]


@pytest.fixture(scope="session")
def token():
    r = requests.post(
        f"{API}/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = (data.get("session_token") or data.get("token")
           or data.get("access_token")
           or (data.get("session") or {}).get("token"))
    assert tok, f"no token in login response: {data}"
    return tok


@pytest.fixture(scope="session")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- Contractor CRUD ----------

class TestContractorMaster:
    def test_list_contractors(self, headers):
        r = requests.get(
            f"{API}/admin/contractors",
            params={"company_id": COMPANY_ID}, headers=headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "contractors" in data
        assert isinstance(data["contractors"], list)
        if data["contractors"]:
            c = data["contractors"][0]
            for key in ("contractor_id", "name", "current_active_labour",
                        "licence_expired", "licence_expiring_soon"):
                assert key in c, f"missing '{key}' in contractor row"

    def test_create_update_delete_contractor(self, headers):
        # Cleanup any leftover from previous run
        r0 = requests.get(f"{API}/admin/contractors",
                          params={"company_id": COMPANY_ID}, headers=headers, timeout=30)
        for c in r0.json().get("contractors", []):
            if c.get("name") == "TEST CONTRACTOR X":
                requests.delete(
                    f"{API}/admin/contractors/{c['contractor_id']}",
                    params={"company_id": COMPANY_ID}, headers=headers, timeout=30)

        # POST create
        payload = {
            "company_id": COMPANY_ID,
            "name": "TEST CONTRACTOR X",
            "licence_no": "LIC123",
            "licence_expiry_date": "2026-09-01",
            "max_labour": 10,
        }
        r = requests.post(f"{API}/admin/contractors", json=payload, headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        ctr = body.get("contractor") or {}
        cid = ctr.get("contractor_id")
        assert cid and cid.startswith("ctr_"), f"bad contractor_id: {cid}"

        # Duplicate must 400
        r_dup = requests.post(f"{API}/admin/contractors", json=payload, headers=headers, timeout=30)
        assert r_dup.status_code == 400, f"duplicate should be 400 not {r_dup.status_code}: {r_dup.text}"

        # PUT update mobile
        r_upd = requests.put(
            f"{API}/admin/contractors/{cid}",
            json={"company_id": COMPANY_ID, "mobile": "9998887770"},
            headers=headers, timeout=30,
        )
        assert r_upd.status_code == 200, r_upd.text
        assert r_upd.json().get("ok") is True

        # Verify update via GET list
        r_list = requests.get(f"{API}/admin/contractors",
                              params={"company_id": COMPANY_ID},
                              headers=headers, timeout=30)
        found = [c for c in r_list.json().get("contractors", []) if c.get("contractor_id") == cid]
        assert found, "contractor missing after update"
        assert found[0].get("mobile") == "9998887770", f"mobile not updated: {found[0]}"

        # DELETE
        r_del = requests.delete(
            f"{API}/admin/contractors/{cid}",
            params={"company_id": COMPANY_ID}, headers=headers, timeout=30,
        )
        assert r_del.status_code == 200, r_del.text
        assert r_del.json().get("ok") is True

        # verify deletion
        r_list2 = requests.get(f"{API}/admin/contractors",
                               params={"company_id": COMPANY_ID},
                               headers=headers, timeout=30)
        assert not any(c.get("contractor_id") == cid for c in r_list2.json().get("contractors", []))


# ---------- CLRA Reports ----------

class TestClraReports:
    def test_list_returns_six_kinds(self, headers):
        r = requests.get(f"{API}/admin/clra-reports/list", headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        kinds = [x["kind"] for x in data.get("reports", [])]
        for k in CLRA_KINDS:
            assert k in kinds, f"missing kind {k} in {kinds}"

    @pytest.mark.parametrize("kind", CLRA_KINDS)
    def test_json_report(self, headers, kind):
        r = requests.get(
            f"{API}/admin/clra-reports/{kind}",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=headers, timeout=60,
        )
        assert r.status_code == 200, f"{kind}: {r.status_code} {r.text[:400]}"
        d = r.json()
        assert "title" in d and "columns" in d and "rows" in d
        assert isinstance(d["columns"], list) and len(d["columns"]) > 0
        assert isinstance(d["rows"], list)

    @pytest.mark.parametrize("kind", CLRA_KINDS)
    def test_xlsx_export(self, headers, kind):
        r = requests.get(
            f"{API}/admin/clra-reports/{kind}.xlsx",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=headers, timeout=60,
        )
        assert r.status_code == 200, f"{kind}.xlsx: {r.status_code} {r.text[:400]}"
        assert len(r.content) > 100
        # XLSX = zip signature PK\x03\x04
        assert r.content[:2] == b"PK", f"{kind}.xlsx not a zip/xlsx"

    @pytest.mark.parametrize("kind", CLRA_KINDS)
    def test_pdf_export(self, headers, kind):
        r = requests.get(
            f"{API}/admin/clra-reports/{kind}.pdf",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=headers, timeout=60,
        )
        assert r.status_code == 200, f"{kind}.pdf: {r.status_code} {r.text[:400]}"
        assert r.content[:4] == b"%PDF", f"{kind}.pdf not a pdf"

    def test_email_report_no_crash(self, headers):
        r = requests.post(
            f"{API}/admin/payroll-reports/email-report",
            json={
                "kind": "contractor-register",
                "group": "clra",
                "company_id": COMPANY_ID,
                "month": MONTH,
                "formats": ["pdf"],
            },
            headers=headers, timeout=60,
        )
        # Must NOT be 500 (report generation crash). 200 (ok) or 4xx graceful
        # config error are both acceptable.
        assert r.status_code != 500, f"email-report crashed: {r.status_code} {r.text[:400]}"
        assert r.status_code in (200, 400, 401, 403, 422), f"unexpected code {r.status_code}: {r.text[:200]}"


# ---------- Daily Verification ----------

class TestDailyVerification:
    def test_daily_verification_full_vs_present_only(self, headers):
        r_full = requests.get(
            f"{API}/admin/reports/daily-verification",
            params={"company_id": COMPANY_ID, "date": DATE},
            headers=headers, timeout=60,
        )
        assert r_full.status_code == 200, r_full.text
        full_total = r_full.json().get("total_rows", 0)

        r_p = requests.get(
            f"{API}/admin/reports/daily-verification",
            params={"company_id": COMPANY_ID, "date": DATE, "present_only": "true"},
            headers=headers, timeout=60,
        )
        assert r_p.status_code == 200, r_p.text
        present_total = r_p.json().get("total_rows", 0)
        assert present_total < full_total, (
            f"present_only filter did not reduce rows: full={full_total} present={present_total}"
        )
        # spec expects ~46; assert reasonable non-zero
        assert present_total > 0, "present_only returned 0 rows"

    @pytest.mark.parametrize("orientation", ["landscape", "portrait"])
    def test_daily_verification_pdf(self, headers, orientation):
        r = requests.get(
            f"{API}/admin/reports/daily-verification.pdf",
            params={"company_id": COMPANY_ID, "date": DATE, "orientation": orientation},
            headers=headers, timeout=90,
        )
        assert r.status_code == 200, r.text[:400]
        assert r.content[:4] == b"%PDF", "response not a PDF"
        # Extract text with pypdf or pdfminer if available
        text = _extract_pdf_text(r.content)
        assert text, f"could not extract text from {orientation} PDF"
        for must in ("Daily Report", "Bio Code", "Page 1", "Total"):
            assert must in text, f"[{orientation}] missing '{must}' in PDF text (len={len(text)})"
        for must_not in ("Verified By", "Remarks"):
            assert must_not not in text, f"[{orientation}] PDF should not contain '{must_not}'"


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            return ""
    try:
        r = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((p.extract_text() or "") for p in r.pages)
    except Exception:
        return ""
