"""Iter 360 — AI UNIVERSAL PAYROLL IMPORT — backend integration tests."""
import base64
import io
import os
import time

import pytest
import requests
from openpyxl import Workbook

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"
MONTH = "2026-06"
ADMIN = {"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"}


# ---------------- fixtures ----------------
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def token(api):
    r = api.post(f"{BASE_URL}/api/auth/admin-password-login", json=ADMIN, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text[:300]}"
    tok = r.json().get("session_token")
    assert tok, "no session token"
    return tok


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def xlsx_bytes():
    wb = Workbook()
    ws = wb.active
    ws.append(["KANKANI ENTERPRISES"])
    ws.append(["Salary Sheet for June 2026"])
    ws.append(["Emp Code", "Worker Name", "UAN", "Present Days", "O.T Hours",
               "Gross Earning", "Advance", "Net Payable"])
    ws.append(["50", "SURENDRA SINGH", "", "26", "10", "21000", "500", "20500"])
    ws.append(["65", "TEST WORKER TWO", "123456789012", "31", "0", "15000", "0", "15000"])
    ws.append(["999", "BRAND NEW GUY", "1234", "-2", "5", "-100", "0", "0"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture(scope="module")
def state():
    return {}


# ---------------- tests ----------------
class TestAIUniversalImport:
    def test_01_analyze(self, api, auth, xlsx_bytes, state):
        b64 = base64.b64encode(xlsx_bytes).decode()
        r = api.post(f"{BASE_URL}/api/admin/ai-import/analyze",
                     json={"filename": "Kankani Salary June 2026.xlsx",
                           "content_base64": b64}, headers=auth, timeout=90)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert d.get("job_id"), "job_id missing"
        state["job_id"] = d["job_id"]
        cands = d.get("file_type_candidates") or []
        assert cands and cands[0]["kind"] == "salary_register", f"top candidate: {cands}"
        cms = d.get("company_matches") or []
        assert cms and cms[0]["company_id"] == COMPANY_ID and cms[0]["confidence"] >= 90, f"company matches {cms}"
        assert d.get("period") == MONTH, f"period {d.get('period')}"
        mp = d.get("mapping") or {}
        assert len(mp) >= 8, f"mapping has {len(mp)} entries, expected >=8"
        state["mapping"] = {h: v["field"] for h, v in mp.items()}
        state["learned_first"] = d.get("learned_template", False)

    def test_02_validate(self, api, auth, state):
        r = api.post(f"{BASE_URL}/api/admin/ai-import/validate",
                     json={"job_id": state["job_id"], "company_id": COMPANY_ID,
                           "month": MONTH, "file_type": "salary_register",
                           "mapping": state["mapping"]}, headers=auth, timeout=60)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        s = d.get("summary") or {}
        assert s.get("total") == 3, f"total {s}"
        assert s.get("error") == 2, f"errors {s}"
        assert s.get("warning") == 1, f"warnings {s}"
        rows = d.get("rows") or []
        # row 5: present days 31 exceeds cal days 30
        pd_msgs = [i["msg"] for r0 in rows for i in r0.get("_issues", [])
                   if "Present days" in i["msg"] and "31" in i["msg"]]
        assert pd_msgs, "no present-days-exceed error"
        # row 6: invalid UAN + negative gross
        r6 = next((r0 for r0 in rows if r0.get("_row_no") == 6), None)
        assert r6, "row 6 missing"
        r6_msgs = [i["msg"] for i in r6.get("_issues", [])]
        assert any("UAN" in m and "1234" in m for m in r6_msgs), f"row6 msgs {r6_msgs}"
        assert any("Negative" in m for m in r6_msgs), f"row6 msgs {r6_msgs}"
        # row 4 matched via code
        r4 = next((r0 for r0 in rows if r0.get("_row_no") == 4), None)
        assert r4 and r4.get("_match") and r4["_match"]["via"] == "code", f"row4 match {r4 and r4.get('_match')}"

    def test_03_commit_and_poll(self, api, auth, state):
        r = api.post(f"{BASE_URL}/api/admin/ai-import/commit",
                     json={"job_id": state["job_id"],
                           "targets": ["attendance_salary"],
                           "create_new_employees": False,
                           "auto_payroll": True}, headers=auth, timeout=60)
        assert r.status_code == 200, r.text[:500]
        # poll
        deadline = time.time() + 90
        job = None
        while time.time() < deadline:
            jr = api.get(f"{BASE_URL}/api/admin/ai-import/job/{state['job_id']}",
                         headers=auth, timeout=30)
            assert jr.status_code == 200
            job = jr.json()
            if job.get("status") in ("imported", "failed"):
                break
            time.sleep(2)
        assert job and job.get("status") == "imported", f"final job status {job and job.get('status')} err={job and job.get('error')}"
        res = job.get("result") or {}
        assert res.get("entries_written") == 1, f"entries_written {res}"
        assert res.get("skipped_errors") == 2, f"skipped_errors {res}"
        payroll = job.get("payroll") or {}
        assert payroll.get("ok") is True, f"payroll {payroll}"
        assert payroll.get("run_id"), f"no run_id: {payroll}"
        state["run_id"] = payroll["run_id"]

    def test_04_duplicate_commit_guard(self, api, auth, state):
        r = api.post(f"{BASE_URL}/api/admin/ai-import/commit",
                     json={"job_id": state["job_id"],
                           "targets": ["attendance_salary"]},
                     headers=auth, timeout=30)
        assert r.status_code == 409, f"expected 409, got {r.status_code} {r.text[:200]}"

    def test_05_compliance_check(self, api, auth):
        r = api.get(f"{BASE_URL}/api/admin/ai-import/compliance-check",
                    params={"company_id": COMPANY_ID, "month": MONTH},
                    headers=auth, timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("run") and d["run"].get("run_id"), "no run"
        assert "issues" in d
        arts = d.get("artifacts") or []
        assert len(arts) == 6, f"artifacts count {len(arts)}"

    def test_06_dashboard(self, api, auth):
        r = api.get(f"{BASE_URL}/api/admin/ai-import/dashboard",
                    headers=auth, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("templates_learned", 0) >= 1, f"templates_learned {d.get('templates_learned')}"
        assert d.get("total_jobs", 0) >= 1

    def test_07_templates(self, api, auth):
        r = api.get(f"{BASE_URL}/api/admin/ai-import/templates",
                    headers=auth, timeout=30)
        assert r.status_code == 200
        tpls = r.json().get("templates") or []
        assert len(tpls) >= 1, "no learned templates"

    def test_08_reanalyze_learned(self, api, auth, xlsx_bytes, state):
        b64 = base64.b64encode(xlsx_bytes).decode()
        r = api.post(f"{BASE_URL}/api/admin/ai-import/analyze",
                     json={"filename": "Kankani Salary June 2026.xlsx",
                           "content_base64": b64}, headers=auth, timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d.get("learned_template") is True, "learned_template should be True on re-analyze"
        # at least one mapping entry should have source=learned
        sources = [v.get("source") for v in (d.get("mapping") or {}).values()]
        assert "learned" in sources, f"no learned source in mapping: {sources}"
        state["reanalyze_job_id"] = d["job_id"]

    def test_09_explain(self, api, auth):
        r = api.post(f"{BASE_URL}/api/admin/ai-import/explain",
                     json={"issues": [{"msg": "Invalid UAN 1234 (needs 12 digits)"}]},
                     headers=auth, timeout=90)
        assert r.status_code == 200, r.text[:400]
        ans = r.json().get("answer") or ""
        assert isinstance(ans, str) and len(ans) > 10, f"weak answer: {ans[:200]}"


# ---------------- cleanup ----------------
@pytest.fixture(scope="module", autouse=True)
def cleanup(request, api, token):
    yield
    try:
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]

        async def do():
            await db.compliance_salary_runs.delete_many(
                {"company_id": COMPANY_ID, "month": MONTH,
                 "attendance_source": "imported_sheet"})
            await db.compliance_import_entries.delete_many(
                {"source": "ai_universal_import"})
            await db.ai_import_jobs.delete_many({})
            await db.ai_universal_templates.delete_many({})
            await db.ai_import_audit.delete_many({})
            await db.ai_import_rows.delete_many({})
            await db.users.delete_many({"imported_from": "ai_universal_import"})
            await db.ai_imported_extras.delete_many({})
        asyncio.get_event_loop().run_until_complete(do())
        print("[cleanup] done")
    except Exception as e:
        print(f"[cleanup] failed: {e}")
