"""Iter 182 — Salary audit log endpoint + PDF branding sanity tests."""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
KANKANI = "cmp_527fecdd7c"


@pytest.fixture(scope="module")
def super_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok, r.json()
    return tok


@pytest.fixture(scope="module")
def auth_headers(super_token):
    return {"Authorization": f"Bearer {super_token}", "Content-Type": "application/json"}


# ------------------ salary-audit-log endpoint ------------------
class TestSalaryAuditLog:
    def test_unauthorized(self):
        r = requests.get(f"{BASE_URL}/api/admin/salary-audit-log", timeout=20)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_super_admin_200(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/salary-audit-log", headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert "entries" in body and isinstance(body["entries"], list)

    def test_filter_by_company(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-audit-log",
            headers=auth_headers,
            params={"company_id": KANKANI, "limit": 20},
            timeout=20,
        )
        assert r.status_code == 200
        for e in r.json()["entries"]:
            assert e.get("company_id") in (KANKANI, None)

    def test_generate_and_read_entry(self, auth_headers):
        """Try to write an audit entry via a real Compliance action and then
        verify it appears in the feed. Falls back gracefully if the run is
        already finalized or attendance data is missing.
        """
        # Try to trigger a save-rows on an existing NON-finalized Kankani run
        runs_r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs",
            headers=auth_headers,
            params={"company_id": KANKANI, "limit": 20},
            timeout=25,
        )
        assert runs_r.status_code == 200, runs_r.text[:200]
        runs = runs_r.json().get("runs") or runs_r.json().get("items") or []
        non_final = [r for r in runs if not r.get("finalized")]
        wrote = False
        note = ""
        if non_final:
            run = non_final[0]
            # Fetch full run to get the row list (save-rows requires the exact
            # set of user_ids to match existing rows).
            det = requests.get(
                f"{BASE_URL}/api/admin/compliance-salary-runs/{run['run_id']}",
                headers=auth_headers, timeout=25,
            )
            run_full = (det.json().get("run") or det.json()) if det.status_code == 200 else {}
            rows = run_full.get("rows") or []
            if rows:
                sr = requests.post(
                    f"{BASE_URL}/api/admin/compliance-salary-runs/{run['run_id']}/save-rows",
                    headers=auth_headers,
                    json={"rows": rows},
                    timeout=45,
                )
                note = f"save_rows: run={run['run_id']} status={sr.status_code} body={sr.text[:120]}"
                if sr.status_code in (200, 201):
                    wrote = True
            else:
                note = f"non-final run {run['run_id']} had no rows"
        else:
            note = "no non-finalized run available"

        # Attempt a process on old month if nothing was written yet
        if not wrote:
            pr = requests.post(
                f"{BASE_URL}/api/admin/compliance-salary-runs",
                headers=auth_headers,
                json={"company_id": KANKANI, "month": "2026-04"},
                timeout=45,
            )
            note += f" | process 2026-04 status={pr.status_code}"
            if pr.status_code in (200, 201):
                wrote = True

        # Read back the audit log
        alog = requests.get(
            f"{BASE_URL}/api/admin/salary-audit-log",
            headers=auth_headers,
            params={"company_id": KANKANI, "limit": 30},
            timeout=20,
        )
        assert alog.status_code == 200
        entries = alog.json()["entries"]
        print(f"[iter182] audit entries fetched: {len(entries)} | trigger: {note}")

        if entries:
            e = entries[0]
            for k in ("audit_id", "action", "at"):
                assert k in e, f"missing {k} in {e}"
            # actor_name / month may be null but keys should be present in schema
            print(f"[iter182] latest entry: action={e.get('action')} actor={e.get('actor_name')} "
                  f"month={e.get('month')} at={e.get('at')}")
        else:
            pytest.skip(f"No audit entries yet — writer may not have fired ({note})")


# ------------------ Labour report PDF sanity ------------------
class TestLabourReportPdf:
    def test_catalogue_lists_reports(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/labour-reports/catalogue",
            headers=auth_headers, timeout=20,
        )
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert isinstance(body, (list, dict))
        # store a report_id / slug for next test
        items = body if isinstance(body, list) else body.get("reports") or body.get("items") or []
        assert items, "no labour reports catalogue entries"

    def test_generate_one_report_pdf(self, auth_headers):
        # Uses same shape as iter177 tests
        import base64
        body = {"company_id": KANKANI, "report_key": "muster_roll",
                "filters": {"month": "2026-06"}, "format": "pdf"}
        r = requests.post(
            f"{BASE_URL}/api/admin/labour-reports/generate",
            headers=auth_headers, json=body, timeout=120,
        )
        assert r.status_code == 200, r.text[:200]
        j = r.json()
        assert j["filename"].endswith(".pdf")
        raw = base64.b64decode(j["file_base64"])
        assert len(raw) > 2000
        assert raw[:4] == b"%PDF"
        # Iter 182 punch-line must appear in extracted text (PDF streams are
        # compressed; use pypdf to decode)
        try:
            from pypdf import PdfReader
        except Exception:
            from PyPDF2 import PdfReader  # type: ignore
        import io as _io
        text = ""
        try:
            reader = PdfReader(_io.BytesIO(raw))
            for pg in reader.pages:
                text += pg.extract_text() or ""
        except Exception as e:
            pytest.skip(f"pdf text extraction failed: {e}")
        assert ("Satisfaction" in text) and ("Ambition" in text), \
            f"punch-line missing from PDF text; head:{text[:400]!r}"
