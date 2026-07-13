"""Iteration 54 — Salary Runs (base salary process, no PF/ESIC/TDS).

Validates that:
  - POST /api/admin/salary-runs returns rows/totals WITHOUT pf/esi/tds keys
  - Legacy body keys pf_percent/esi_percent/tds_percent are silently ignored
  - Reprocess / CSV / PDF / generate-payslips all conform to the new schema
  - PATCH /api/admin/user-role accepts advance_balance and it flows through
    into a subsequent salary run row and net calculation.
"""
import os
import io
import csv
import uuid
import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "https://emplo-connect-1.preview.emergentagent.com"
).rstrip("/")

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
FORBIDDEN_KEYS = {"pf", "esi", "tds", "pf_amount", "esi_amount", "tds_amount"}


# --------------------------------------------------------------------------- helpers
def _otp_login(identifier: str, channel: str = "email") -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": identifier, "channel": channel},
        timeout=30,
    )
    assert r.status_code == 200, f"otp/request failed: {r.status_code} {r.text}"
    dev_code = r.json().get("dev_code")
    assert dev_code, f"No dev_code in response: {r.json()}"

    r2 = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": identifier, "channel": channel, "code": dev_code},
        timeout=30,
    )
    assert r2.status_code == 200, f"otp/verify failed: {r2.status_code} {r2.text}"
    j = r2.json()
    tok = j.get("session_token") or j.get("token")
    assert tok, f"No session_token/token in verify response: {j}"
    return tok


@pytest.fixture(scope="session")
def super_token() -> str:
    return _otp_login(SUPER_ADMIN_EMAIL, "email")


@pytest.fixture(scope="session")
def auth_headers(super_token):
    return {"Authorization": f"Bearer {super_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def a_company_id(auth_headers) -> str:
    """Get any existing company id — we'll target it for the salary run."""
    r = requests.get(f"{BASE_URL}/api/companies", headers=auth_headers, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    comps = j.get("companies") or j.get("items") or (j if isinstance(j, list) else [])
    assert comps, "No companies found in DB — cannot run salary tests"
    # Prefer S.K. Sharma & Co. if present
    for c in comps:
        if "sharma" in (c.get("name") or "").lower():
            return c["company_id"]
    return comps[0]["company_id"]


@pytest.fixture(scope="session")
def an_employee(auth_headers, a_company_id) -> dict:
    """Find any user with role=employee in the DB.

    Falls back to creating a fresh employee via OTP+PATCH if none exist.
    """
    # Search across all companies for an actual employee
    r = requests.get(f"{BASE_URL}/api/companies", headers=auth_headers, timeout=30)
    j = r.json() if r.status_code == 200 else {}
    comps = j.get("companies") or j.get("items") or (j if isinstance(j, list) else [])
    for c in comps:
        cid = c.get("company_id")
        if not cid:
            continue
        rr = requests.get(
            f"{BASE_URL}/api/admin/employees",
            headers=auth_headers,
            params={"company_id": cid},
            timeout=30,
        )
        if rr.status_code != 200:
            continue
        emps = rr.json().get("employees") or rr.json().get("items") or []
        emps = [e for e in emps if (e.get("role") or "employee") == "employee"]
        if emps:
            # Overwrite a_company_id via mutable attach for downstream
            emps[0]["_company_id"] = cid
            return emps[0]

    # Seed via OTP → super_admin PATCH role=employee, company_id
    phone = f"+9199{uuid.uuid4().hex[:8]}"
    r1 = requests.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": phone, "channel": "sms"},
        timeout=30,
    )
    assert r1.status_code == 200, r1.text
    code = r1.json()["dev_code"]
    r2 = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": phone, "channel": "sms", "code": code},
        timeout=30,
    )
    assert r2.status_code == 200, r2.text
    new_user = r2.json()["user"]
    new_uid = new_user["user_id"]
    # Attach to a company as employee with a salary
    r3 = requests.patch(
        f"{BASE_URL}/api/admin/user-role",
        headers=auth_headers,
        json={
            "user_id": new_uid,
            "role": "employee",
            "company_id": a_company_id,
            "salary_monthly": 30000,
            "name": f"TEST_iter54_{new_uid[:6]}",
        },
        timeout=30,
    )
    assert r3.status_code == 200, r3.text
    new_user["_company_id"] = a_company_id
    return new_user


# --------------------------------------------------------------------------- schema tests
class TestSalaryRunSchema:
    """Verify rows/totals have NO PF/ESI/TDS keys."""

    def test_create_salary_run_no_pf_esi_tds(self, auth_headers, a_company_id):
        payload = {
            "month": "2026-01",
            "company_id": a_company_id,
            # Legacy keys – must be silently ignored
            "deductions": {
                "ot_multiplier": 1.5,
                "pf_percent": 12,
                "esi_percent": 0.75,
                "tds_percent": 10,
            },
        }
        r = requests.post(
            f"{BASE_URL}/api/admin/salary-runs",
            headers=auth_headers,
            json=payload,
            timeout=60,
        )
        assert r.status_code == 200, r.text
        run = r.json()["run"]

        # totals whitelist
        expected = {"base_pay", "bonus", "ot_pay", "gross", "advance", "total_deduction", "net"}
        assert set(run["totals"].keys()) == expected, (
            f"totals keys mismatch: got {set(run['totals'].keys())}"
        )
        for r_ in run["rows"]:
            for bad in FORBIDDEN_KEYS:
                assert bad not in r_, f"forbidden key '{bad}' present in row: {r_}"
        # Save id for later tests via test_state file
        with open("/tmp/iter54_run_id.txt", "w") as f:
            f.write(run["run_id"])
        with open("/tmp/iter54_month.txt", "w") as f:
            f.write(run["month"])

    def test_list_salary_runs_no_forbidden_keys(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-runs", headers=auth_headers, timeout=30
        )
        assert r.status_code == 200, r.text
        runs = r.json().get("runs") or []
        assert isinstance(runs, list)
        for run in runs:
            for bad in FORBIDDEN_KEYS:
                assert bad not in (run.get("totals") or {}), f"totals has {bad}"

    def test_reprocess_no_forbidden_keys(self, auth_headers):
        with open("/tmp/iter54_run_id.txt") as f:
            run_id = f.read().strip()
        r = requests.post(
            f"{BASE_URL}/api/admin/salary-runs/{run_id}/reprocess",
            headers=auth_headers,
            json={"month": "2026-01", "deductions": {"ot_multiplier": 2.0, "pf_percent": 12}},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        run = r.json()["run"]
        assert set(run["totals"].keys()) == {
            "base_pay", "bonus", "ot_pay", "gross", "advance", "total_deduction", "net"
        }
        for r_ in run["rows"]:
            for bad in FORBIDDEN_KEYS:
                assert bad not in r_


# --------------------------------------------------------------------------- exports
class TestExports:
    def test_csv_export(self, auth_headers):
        with open("/tmp/iter54_run_id.txt") as f:
            run_id = f.read().strip()
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-runs/{run_id}/export.csv",
            headers=auth_headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        ct = r.headers.get("content-type", "")
        assert "text/csv" in ct, f"bad content-type: {ct}"

        reader = csv.reader(io.StringIO(r.text))
        header_row = next(reader)
        lower_cols = {c.strip().lower() for c in header_row}
        for bad in ("pf", "esi", "tds", "pf_amount", "esi_amount", "tds_amount"):
            assert bad not in lower_cols, f"CSV header contains forbidden col: {bad}"

    def test_pdf_export(self, auth_headers):
        with open("/tmp/iter54_run_id.txt") as f:
            run_id = f.read().strip()
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-runs/{run_id}/register.pdf",
            headers=auth_headers,
            timeout=60,
        )
        assert r.status_code == 200, r.text
        assert "application/pdf" in r.headers.get("content-type", "")
        assert len(r.content) > 500, "PDF bytes too small"
        assert r.content[:4] == b"%PDF", "Not a valid PDF header"


# --------------------------------------------------------------------------- payslips
class TestGeneratePayslips:
    def test_generate_payslips_breakup_clean(self, auth_headers):
        with open("/tmp/iter54_run_id.txt") as f:
            run_id = f.read().strip()
        with open("/tmp/iter54_month.txt") as f:
            month = f.read().strip()
        r = requests.post(
            f"{BASE_URL}/api/admin/salary-runs/{run_id}/generate-payslips",
            headers=auth_headers,
            timeout=60,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("ok") is True
        assert isinstance(j.get("payslips_count"), int)

        # Fetch payslips and verify breakup has no forbidden keys
        r2 = requests.get(
            f"{BASE_URL}/api/admin/payslips",
            headers=auth_headers,
            params={"month": month},
            timeout=30,
        )
        # This endpoint may not exist — degrade gracefully if 404
        if r2.status_code == 200:
            slips = r2.json().get("payslips") or r2.json().get("items") or []
            for s in slips[:5]:
                b = s.get("breakup") or {}
                for bad in FORBIDDEN_KEYS:
                    assert bad not in b, f"breakup contains {bad}: {b}"


# --------------------------------------------------------------------------- advance_balance
class TestAdvanceBalance:
    def test_patch_advance_balance_flows_into_run(self, auth_headers, an_employee, a_company_id):
        uid = an_employee["user_id"]
        target_company = an_employee.get("_company_id") or a_company_id
        r = requests.patch(
            f"{BASE_URL}/api/admin/user-role",
            headers=auth_headers,
            json={"user_id": uid, "advance_balance": 500},
            timeout=30,
        )
        assert r.status_code == 200, r.text

        # Verify persistence via GET /admin/employees
        r2 = requests.get(
            f"{BASE_URL}/api/admin/employees",
            headers=auth_headers,
            params={"company_id": target_company},
            timeout=30,
        )
        assert r2.status_code == 200
        emps = r2.json().get("employees") or r2.json().get("items") or []
        me = next((e for e in emps if e["user_id"] == uid), None)
        assert me is not None, "Target employee not returned"
        assert float(me.get("advance_balance") or 0) == 500.0, (
            f"advance_balance not persisted; got {me.get('advance_balance')}"
        )

        # Run salary and verify row.advance = 500 and net = gross - 500
        r3 = requests.post(
            f"{BASE_URL}/api/admin/salary-runs",
            headers=auth_headers,
            json={"month": "2026-01", "company_id": target_company},
            timeout=60,
        )
        assert r3.status_code == 200, r3.text
        run = r3.json()["run"]
        row = next((x for x in run["rows"] if x["user_id"] == uid), None)
        if row is None:
            # Fallback: run without company_id filter (super admin -> all)
            r3b = requests.post(
                f"{BASE_URL}/api/admin/salary-runs",
                headers=auth_headers,
                json={"month": "2026-01"},
                timeout=60,
            )
            assert r3b.status_code == 200, r3b.text
            run = r3b.json()["run"]
            row = next((x for x in run["rows"] if x["user_id"] == uid), None)
        assert row is not None, f"Employee {uid} not in salary run (company={target_company})"
        assert row["advance"] == 500.0, f"advance not applied: {row}"
        assert row["total_deduction"] == 500.0, f"total_deduction != 500: {row}"
        # gross - 500 == net
        assert abs(row["net"] - (row["gross"] - 500.0)) < 0.01, f"Net math wrong: {row}"

        # Cleanup — reset advance_balance to 0 so we don't pollute other runs
        requests.patch(
            f"{BASE_URL}/api/admin/user-role",
            headers=auth_headers,
            json={"user_id": uid, "advance_balance": 0},
            timeout=30,
        )
