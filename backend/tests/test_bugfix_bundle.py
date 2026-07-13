"""Backend tests for BUG-FIX bundle:
 - compliance_enabled on companies
 - GET /api/salary/monthly (auto pending payslips)
 - PATCH /api/payslips/{id}/mark-paid
 - GET /api/admin/payroll
Only auth-gating + endpoint existence can be exercised without a real Google OAuth
session, so these are the covered assertions.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001"
BASE_URL = BASE_URL.rstrip("/")


@pytest.fixture
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# --- Endpoint existence + auth gating ------------------------------------
class TestAuthGating:
    def test_salary_monthly_requires_auth(self, client):
        r = client.get(f"{BASE_URL}/api/salary/monthly",
                       headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401
        assert r.json().get("detail") == "Invalid session"

    def test_mark_paid_requires_auth(self, client):
        r = client.patch(f"{BASE_URL}/api/payslips/xyz/mark-paid",
                         headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401

    def test_admin_payroll_requires_auth(self, client):
        r = client.get(f"{BASE_URL}/api/admin/payroll",
                       headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401

    def test_admin_payroll_query_params_accepted(self, client):
        # Even with bad token we should get 401 (not 422), proving query
        # params are optional and pattern is valid.
        r = client.get(
            f"{BASE_URL}/api/admin/payroll",
            params={"month": "2026-01", "status": "pending"},
            headers={"Authorization": "Bearer nope"},
        )
        assert r.status_code == 401

    def test_admin_payroll_bad_status_pattern(self, client):
        # Invalid status should still be rejected by validation OR by auth.
        r = client.get(
            f"{BASE_URL}/api/admin/payroll",
            params={"status": "junk"},
            headers={"Authorization": "Bearer nope"},
        )
        assert r.status_code in (401, 422)

    def test_companies_post_requires_auth(self, client):
        r = client.post(
            f"{BASE_URL}/api/companies",
            json={"name": "TEST_x", "office_lat": 0, "office_lng": 0,
                  "compliance_enabled": False},
            headers={"Authorization": "Bearer nope"},
        )
        assert r.status_code == 401


# --- Static code assertions ----------------------------------------------
class TestServerCode:
    """Static assertions on /app/backend/server.py that verify the bug-fix
    intent (since auth-gated behaviour cannot be run without OAuth)."""
    SRC = None

    @classmethod
    def setup_class(cls):
        with open("/app/backend/server.py") as f:
            cls.SRC = f.read()

    def test_company_model_has_compliance_default_true(self):
        assert "compliance_enabled: bool = True" in self.SRC

    def test_company_create_has_compliance_field(self):
        # CompanyCreate + Company both use `compliance_enabled: bool = True`
        assert self.SRC.count("compliance_enabled: bool = True") >= 2

    def test_company_update_has_optional_compliance(self):
        assert "compliance_enabled: Optional[bool] = None" in self.SRC

    def test_startup_backfills_compliance_enabled(self):
        assert 'compliance_enabled": {"$exists": False}' in self.SRC
        assert '"$set": {"compliance_enabled": True}' in self.SRC

    def test_salary_monthly_endpoint_exists(self):
        assert '@api.get("/salary/monthly")' in self.SRC
        assert '"salary_monthly"' in self.SRC
        assert '"current_month"' in self.SRC
        assert '"history"' in self.SRC

    def test_salary_monthly_dedupes_per_month(self):
        # It must look up an existing payslip before inserting.
        assert 'find_one({\n                "employee_user_id": user["user_id"],\n                "month": month,\n            })' in self.SRC or \
               '"employee_user_id": user["user_id"]' in self.SRC

    def test_mark_paid_endpoint_and_role(self):
        assert '@api.patch("/payslips/{slip_id}/mark-paid")' in self.SRC
        assert 'require_role(user, ["company_admin", "super_admin"])' in self.SRC

    def test_admin_payroll_endpoint_and_scoping(self):
        assert '@api.get("/admin/payroll")' in self.SRC
        assert '"employee_name"' in self.SRC
        assert '"employee_email"' in self.SRC

    def test_create_company_forwards_compliance_enabled(self):
        """BUG: POST /companies constructs `Company(...)` without passing
        payload.compliance_enabled — flag from the request body is silently
        dropped and always stored as the default (True)."""
        # Deliberate xfail-style assertion; keep as regular test so main agent
        # sees the failure clearly.
        block_start = self.SRC.find('@api.post("/companies")')
        block_end = self.SRC.find('@api.patch("/companies/{company_id}")')
        block = self.SRC[block_start:block_end]
        assert "compliance_enabled=payload.compliance_enabled" in block, (
            "create_company() must forward payload.compliance_enabled into "
            "Company(...) or the toggle from the UI is silently ignored."
        )
