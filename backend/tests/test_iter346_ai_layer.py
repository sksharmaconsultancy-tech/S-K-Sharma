"""Iter 346 — AI Layer backend tests.

Covers:
 - GET  /api/admin/ai/analysis (fresh + refresh=1)
 - POST /api/admin/ai/feedback (false_positive → suppresses → restored)
 - POST /api/admin/ai/apply-fix (non-fixable finding returns applied:false + fix_route)
 - GET  /api/admin/ai/audit-report.xlsx | .pdf
 - GET  /api/admin/ai/salary-diff
 - POST /api/admin/ai/map-columns
 - GET  /api/admin/attendance-sheet/{cid}/{month}.xlsx?sort=...
 - POST /api/admin/ai-assistant/command  (missing_data / pf_mismatch / why_salary)
"""
import os

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
CID = "cmp_527fecdd7c"
MONTH = "2026-06"


@pytest.fixture(scope="session")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="session")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------- analysis
class TestAnalysis:
    def test_analysis_refresh(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/ai/analysis",
            params={"company_id": CID, "month": MONTH, "refresh": 1},
            headers=headers,
            timeout=120,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        # scores
        s = d.get("scores") or {}
        for k in ("payroll_health", "compliance_score", "risk_level",
                  "ai_alerts", "attendance_issues", "payroll_errors",
                  "pending_compliance"):
            assert k in s, f"scores missing {k}"
        # findings shape
        assert isinstance(d.get("findings"), list)
        if d["findings"]:
            f = d["findings"][0]
            for k in ("finding_id", "key", "code", "severity", "issue",
                      "reason", "impact", "fix", "confidence", "fixable"):
                assert k in f, f"finding missing {k}"
        # other sections
        assert isinstance(d.get("trends"), list) and len(d["trends"]) == 6
        assert isinstance(d.get("forecast"), dict)
        assert isinstance(d.get("reconciliation"), dict)
        assert isinstance(d.get("calendar"), list)
        assert isinstance(d.get("insights"), list)
        assert isinstance(d.get("recommendations"), list)
        # cache next
        r2 = requests.get(
            f"{BASE_URL}/api/admin/ai/analysis",
            params={"company_id": CID, "month": MONTH},
            headers=headers,
            timeout=30,
        )
        assert r2.status_code == 200


# ---------------------------------------------------------------- feedback
class TestFeedback:
    def test_feedback_suppresses_and_restores(self, headers):
        # baseline
        r = requests.get(
            f"{BASE_URL}/api/admin/ai/analysis",
            params={"company_id": CID, "month": MONTH, "refresh": 1},
            headers=headers,
            timeout=120,
        )
        d = r.json()
        if not d.get("findings"):
            pytest.skip("no findings to mark false-positive")
        key = d["findings"][0]["key"]
        base_supp = d.get("suppressed_count", 0)

        # mark false_positive
        fp = requests.post(
            f"{BASE_URL}/api/admin/ai/feedback",
            json={"company_id": CID, "finding_key": key, "verdict": "false_positive"},
            headers=headers,
            timeout=30,
        )
        assert fp.status_code == 200, fp.text
        assert fp.json().get("ok") is True

        # refresh and confirm suppression grew
        r2 = requests.get(
            f"{BASE_URL}/api/admin/ai/analysis",
            params={"company_id": CID, "month": MONTH, "refresh": 1},
            headers=headers,
            timeout=120,
        )
        d2 = r2.json()
        assert d2["suppressed_count"] > base_supp, \
            f"suppressed_count did not grow (base={base_supp}, new={d2['suppressed_count']})"
        # and finding with that key should no longer appear
        assert not any(f["key"] == key for f in d2.get("findings", [])), \
            "false-positive finding still present"

        # RESTORE — mark correct
        rr = requests.post(
            f"{BASE_URL}/api/admin/ai/feedback",
            json={"company_id": CID, "finding_key": key, "verdict": "correct"},
            headers=headers,
            timeout=30,
        )
        assert rr.status_code == 200


# ---------------------------------------------------------------- apply-fix
class TestApplyFix:
    def test_non_fixable_returns_fix_route(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/ai/analysis",
            params={"company_id": CID, "month": MONTH},
            headers=headers,
            timeout=120,
        )
        d = r.json()
        non_fix = next((f for f in d.get("findings", []) if not f.get("fixable")), None)
        if not non_fix:
            pytest.skip("no non-fixable finding available")
        af = requests.post(
            f"{BASE_URL}/api/admin/ai/apply-fix",
            json={"company_id": CID, "month": MONTH,
                  "finding_id": non_fix["finding_id"]},
            headers=headers,
            timeout=60,
        )
        assert af.status_code == 200, af.text
        body = af.json()
        assert body.get("applied") is False
        assert body.get("fix_route"), "missing fix_route in response"


# ---------------------------------------------------------------- exports
class TestAuditExports:
    def test_xlsx(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/ai/audit-report.xlsx",
            params={"company_id": CID, "month": MONTH},
            headers=headers,
            timeout=60,
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml"
        )
        assert r.content[:2] == b"PK", "not a valid xlsx (PK header missing)"
        assert len(r.content) > 3000

    def test_pdf(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/ai/audit-report.pdf",
            params={"company_id": CID, "month": MONTH},
            headers=headers,
            timeout=60,
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"


# ---------------------------------------------------------------- salary-diff
class TestSalaryDiff:
    def test_salary_diff(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/ai/salary-diff",
            params={"company_id": CID, "month": MONTH},
            headers=headers,
            timeout=60,
        )
        assert r.status_code == 200
        d = r.json()
        assert "summary" in d
        assert "rows" in d and isinstance(d["rows"], list)


# ---------------------------------------------------------------- map-columns
class TestMapColumns:
    def test_map(self, headers):
        r = requests.post(
            f"{BASE_URL}/api/admin/ai/map-columns",
            json={"headers": ["Worker Name", "Pay", "Punch In", "XYZ"]},
            headers=headers,
            timeout=90,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        m = d.get("mapping") or {}
        assert m.get("Worker Name", {}).get("field") == "name"
        assert m.get("Pay", {}).get("field") == "gross_salary"
        assert m.get("Punch In", {}).get("field") == "in_time"
        # XYZ should either be unmapped or llm-mapped
        xyz_in_map = "XYZ" in m
        xyz_in_unmapped = "XYZ" in (d.get("unmapped") or [])
        assert xyz_in_map or xyz_in_unmapped


# ---------------------------------------------------------------- attendance sheet sort
class TestAttendanceSheetSort:
    @pytest.mark.parametrize("q", [None, "name", "doj", "code", "department"])
    def test_sorted_xlsx(self, headers, q):
        params = {"sort": q} if q else {}
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance-sheet/{CID}/{MONTH}.xlsx",
            params=params, headers=headers, timeout=60,
        )
        assert r.status_code == 200, f"sort={q} → {r.status_code}"
        assert r.content[:2] == b"PK"


# ---------------------------------------------------------------- chatbot new metrics
class TestChatbotMetrics:
    def _cmd(self, headers, msg, timeout=120):
        return requests.post(
            f"{BASE_URL}/api/admin/ai-assistant/command",
            json={"company_id": CID, "text": msg},
            headers=headers, timeout=timeout,
        )

    def test_missing_uan(self, headers):
        r = self._cmd(headers, "List employees with missing UAN")
        assert r.status_code == 200, r.text
        d = r.json()
        # Reply should be a metric-style bubble; look for missing_data marker
        blob = str(d).lower()
        assert "uan" in blob
        # Should render a list of names — either 'names' list or reply text contains employee code style
        assert any(k in blob for k in ("missing", "names", "code"))

    def test_pf_mismatch(self, headers):
        r = self._cmd(headers, "Show PF mismatches")
        assert r.status_code == 200, r.text
        blob = str(r.json()).lower()
        assert "pf" in blob

    def test_why_salary(self, headers):
        # Note: LLM parses "code 50" as literal employee_query which
        # _find_employees() cannot resolve. Bare number or name work fine.
        r = self._cmd(headers, "Why is SURENDRA SINGH salary lower this month?",
                       timeout=150)
        assert r.status_code == 200, r.text
        blob = str(r.json()).lower()
        assert any(k in blob for k in ("vs", "reason", "net"))
