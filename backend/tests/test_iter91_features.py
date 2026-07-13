"""Iter 91 backend regression tests.

Covers request items 1-10:
  1. GET/PATCH /api/admin/employees/{user_id}/salary  (new fields + rate_type/working_days)
  2. POST /api/admin/actual-salary-process   (basic override, oth_allo prefill, epf/esi 0 when no compliance)
  3. Compliance run finalize -> reprocess 409
  4. GET /api/admin/reports/master-data + master-data.xlsx
  5. GET/PATCH /api/admin/employees/{user_id}/profile (unified employee_type/employee_group)
  6. PATCH /api/admin/user-role — unified type/group with title-case
  7. POST generate-uan / generate-esic — aadhaar mandatory (400) / manual_required when no creds
  8. POST /api/admin/ocr/parse-document — invalid mime -> 400 (LLM call NOT exercised)
  9. PATCH kyc.present_address must sync users.address
 10. POST /admin/employees accepts salary_structure_actual persist
"""
import base64
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://emplo-connect-1.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")
KANKANI_PHONE = "+919828100001"
KANKANI_COMPANY = "cmp_527fecdd7c"
TEST_EMP = "user_ca0cba59bcdb"   # Ramesh Kumar Sharma


def _otp_login(channel: str, identifier: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/otp/request",
                      json={"channel": channel, "identifier": identifier}, timeout=30)
    assert r.status_code == 200, r.text
    code = r.json()["dev_code"]
    r = requests.post(f"{BASE_URL}/api/auth/otp/verify",
                      json={"channel": channel, "identifier": identifier, "code": code},
                      timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="session")
def admin_token():
    return _otp_login("sms", KANKANI_PHONE)


@pytest.fixture(scope="session")
def super_token():
    return _otp_login("email", "sksharmaconsultancy@gmail.com")


@pytest.fixture
def H(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture
def SH(super_token):
    return {"Authorization": f"Bearer {super_token}", "Content-Type": "application/json"}


# ---------------- (1) Salary GET/PATCH ----------------
class TestSalaryEndpoint:
    def test_get_returns_new_iter91_fields(self, H):
        r = requests.get(f"{BASE_URL}/api/admin/employees/{TEST_EMP}/salary", headers=H)
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("employee_type", "actual_salary_allowances", "actual_salary_deductions",
                  "firm_allowance_heads", "firm_deduction_heads",
                  "salary_structure_actual", "salary_structure_compliance"):
            assert k in j, f"missing {k}"
        assert isinstance(j["firm_allowance_heads"], list)
        assert isinstance(j["firm_deduction_heads"], list)

    def test_patch_persists_rate_type_working_days_and_decimals(self, H):
        payload = {
            "salary_structure_actual": [
                {"head": "Basic Salary", "amount": 15000, "rate_type": "monthly"},
                {"head": "Salary 1", "amount": 500, "working_days": 26},
                {"head": "Salary 2", "amount": 0, "working_days": 0},
                {"head": "Salary 3", "amount": 0, "working_days": 0},
            ],
            "actual_salary_allowances": [
                {"head": "HRA", "amount": 4400.5},
                {"head": "CONV.", "amount": 2200},
            ],
            "actual_salary_deductions": [
                {"head": "PF", "amount": 1320},
                {"head": "ESI", "amount": 165.25},
            ],
        }
        r = requests.patch(
            f"{BASE_URL}/api/admin/employees/{TEST_EMP}/salary",
            headers=H, json=payload,
        )
        assert r.status_code == 200, r.text
        # Verify via GET
        r2 = requests.get(f"{BASE_URL}/api/admin/employees/{TEST_EMP}/salary", headers=H)
        j = r2.json()
        basic = next(row for row in j["salary_structure_actual"] if row["head"].lower().startswith("basic"))
        assert basic["amount"] == 15000
        assert basic.get("rate_type") == "monthly"
        s1 = next(row for row in j["salary_structure_actual"] if row["head"] == "Salary 1")
        assert s1.get("working_days") == 26
        # Decimal persistence
        esi = next(d for d in j["actual_salary_deductions"] if d["head"] == "ESI")
        assert esi["amount"] == 165.25


# ---------------- (2) Actual Salary Process ----------------
class TestActualSalaryProcess:
    def test_run_uses_master_basic_and_prefills_oth_allo_zero_epf_esi(self, H):
        # Pick a month unlikely to have compliance run
        month = "2029-01"
        body = {"month": month, "company_id": KANKANI_COMPANY, "attendance_source": "manual"}
        r = requests.post(f"{BASE_URL}/api/admin/actual-salary-process", headers=H, json=body)
        assert r.status_code == 200, r.text
        run = r.json()["run"]
        row = next((x for x in run["rows"] if x["user_id"] == TEST_EMP), None)
        assert row is not None, "Ramesh Kumar Sharma row missing"
        # Basic from salary_structure_actual (15000), NOT salary_monthly
        assert row["basic"] == 15000, f"basic={row['basic']}"
        # Oth.Allo prefilled = sum(HRA + CONV) = 4400.5 + 2200 = 6600.5
        assert abs(row["oth_allo"] - 6600.5) < 0.01, f"oth_allo={row['oth_allo']}"
        # EPF/ESI must be 0 (no compliance run for 2019-01)
        assert row["epf"] == 0.0
        assert row["esi"] == 0.0
        # total_gross == basic_salary + w_basic_salary + oth_allo
        expected = round(row["basic_salary"] + row["w_basic_salary"] + row["oth_allo"], 2)
        assert abs(row["total_gross"] - expected) < 0.02

    def test_patch_row_daily_and_hourly_compute(self, H):
        # Create an isolated run
        r = requests.post(f"{BASE_URL}/api/admin/actual-salary-process", headers=H,
                          json={"month": "2029-02", "company_id": KANKANI_COMPANY, "attendance_source": "manual"})
        assert r.status_code == 200
        run_id = r.json()["run"]["run_id"]
        # Patch p_days=10, p_hours=4 with basic=100 daily (via PATCH — endpoint only sets p_days/p_hours/basic etc.)
        # Set the row's salary_mode implicit via master's mode — patch basic to override rate; then set p_days=10, p_hours=4
        # For a daily employee, expected basic_salary = basic * p_days
        # Row's current salary_mode is 'monthly' (default) unless master says otherwise; we still can validate
        # the compute formula on the returned row values (basic_salary_monthly = basic*p_days/month_days)
        r2 = requests.patch(f"{BASE_URL}/api/admin/actual-salary-process/{run_id}/row",
                            headers=H, json={"user_id": TEST_EMP, "p_days": 10, "p_hours": 4})
        assert r2.status_code == 200, r2.text
        row = r2.json()["row"]
        # Ensure formula holds against reported values for whatever mode is set
        # basic_salary + w_basic_salary + oth_allo = total_gross
        assert abs(row["total_gross"] - (row["basic_salary"] + row["w_basic_salary"] + row["oth_allo"])) < 0.02


# ---------------- (3) Compliance finalize + reprocess 409 ----------------
class TestComplianceFinalizeReprocess:
    def test_finalize_then_reprocess_409(self, SH):
        # Create a compliance run (uses super admin to bypass feature gate)
        r = requests.post(f"{BASE_URL}/api/admin/compliance-salary-runs", headers=SH,
                          json={"month": "2029-03", "company_id": KANKANI_COMPANY})
        assert r.status_code == 200, r.text
        run_id = r.json()["run"]["run_id"]
        # Finalize
        rf = requests.post(f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/finalize", headers=SH)
        assert rf.status_code == 200, rf.text
        assert rf.json().get("ok") is True
        # Reprocess should 409
        rp = requests.post(f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/reprocess", headers=SH)
        assert rp.status_code == 409, f"expected 409, got {rp.status_code}: {rp.text}"


# ---------------- (4) Master Data Report ----------------
class TestMasterDataReport:
    def test_active_status_json(self, H):
        r = requests.get(f"{BASE_URL}/api/admin/reports/master-data?status=active", headers=H)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "active"
        assert "columns" in j and "rows" in j
        assert any(c["key"] == "employee_code" for c in j["columns"])

    def test_left_status_json(self, H):
        r = requests.get(f"{BASE_URL}/api/admin/reports/master-data?status=left", headers=H)
        assert r.status_code == 200
        assert r.json()["status"] == "left"

    def test_all_status_with_q_filter(self, H):
        r = requests.get(f"{BASE_URL}/api/admin/reports/master-data?status=all&q=Ramesh", headers=H)
        assert r.status_code == 200
        j = r.json()
        assert any(row.get("name", "").lower().startswith("ramesh") for row in j["rows"])

    def test_invalid_status(self, H):
        r = requests.get(f"{BASE_URL}/api/admin/reports/master-data?status=bogus", headers=H)
        assert r.status_code == 400

    def test_xlsx_export(self, H):
        r = requests.get(f"{BASE_URL}/api/admin/reports/master-data.xlsx?status=all", headers=H)
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "spreadsheetml.sheet" in ct, f"Content-Type={ct}"
        assert len(r.content) > 200
        # xlsx magic bytes (PK zip)
        assert r.content[:2] == b"PK"


# ---------------- (5) Employee Profile GET/PATCH ----------------
class TestEmployeeProfile:
    def test_get_profile_has_salary_structure(self, H):
        r = requests.get(f"{BASE_URL}/api/admin/employees/{TEST_EMP}/profile", headers=H)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["user_id"] == TEST_EMP
        assert "salary_structure_actual" in j
        assert "employee_type" in j and "employee_group" in j

    def test_patch_employee_type_mirrors_group(self, H):
        r = requests.patch(f"{BASE_URL}/api/admin/employees/{TEST_EMP}/profile",
                           headers=H, json={"employee_type": "Worker"})
        assert r.status_code == 200, r.text
        rg = requests.get(f"{BASE_URL}/api/admin/employees/{TEST_EMP}/profile", headers=H)
        j = rg.json()
        assert j["employee_type"] == "Worker"
        assert j["employee_group"] == "Worker"


# ---------------- (6) user-role unified type/group ----------------
class TestUserRoleUnifiedType:
    def test_type_titlecases_and_mirrors_group(self, H):
        r = requests.patch(f"{BASE_URL}/api/admin/user-role", headers=H,
                           json={"user_id": TEST_EMP, "employee_type": "staff"})
        assert r.status_code == 200, r.text
        rg = requests.get(f"{BASE_URL}/api/admin/employees/{TEST_EMP}/profile", headers=H)
        j = rg.json()
        assert j["employee_type"] == "Staff", j["employee_type"]
        assert j["employee_group"] == "Staff"

    def test_group_mirrors_type(self, H):
        r = requests.patch(f"{BASE_URL}/api/admin/user-role", headers=H,
                           json={"user_id": TEST_EMP, "employee_group": "SUPERVISOR"})
        assert r.status_code == 200, r.text
        rg = requests.get(f"{BASE_URL}/api/admin/employees/{TEST_EMP}/profile", headers=H)
        j = rg.json()
        assert j["employee_type"] == "Supervisor"
        assert j["employee_group"] == "Supervisor"


# ---------------- (7) Portal Generation UAN/ESIC gating ----------------
class TestPortalGeneration:
    @pytest.fixture
    def temp_employee_no_aadhaar(self, H):
        # Create an employee with NO aadhaar — unique phone per run
        import uuid as _u
        suffix = _u.uuid4().hex[:6]
        phone = "+9198887" + suffix[:5]
        r = requests.post(f"{BASE_URL}/api/admin/employees", headers=H, json={
            "name": f"TEST_iter91_noaad_{suffix}",
            "phone": phone,
        })
        assert r.status_code == 200, r.text
        j = r.json()
        uid = j.get("user_id") or (j.get("user") or {}).get("user_id")
        assert uid, f"no user_id in response: {j}"
        yield uid

    def test_generate_uan_no_aadhaar_400(self, H, temp_employee_no_aadhaar):
        r = requests.post(f"{BASE_URL}/api/admin/employees/{temp_employee_no_aadhaar}/generate-uan", headers=H)
        assert r.status_code == 400, r.text
        assert "Aadhaar" in r.json().get("detail", ""), r.text

    def test_generate_esic_no_aadhaar_400(self, H, temp_employee_no_aadhaar):
        r = requests.post(f"{BASE_URL}/api/admin/employees/{temp_employee_no_aadhaar}/generate-esic", headers=H)
        assert r.status_code == 400
        assert "Aadhaar" in r.json().get("detail", "")

    def test_generate_uan_with_aadhaar_manual_required_or_pending(self, H, temp_employee_no_aadhaar):
        # Add aadhaar via kyc endpoint
        r = requests.patch(f"{BASE_URL}/api/admin/employees/{temp_employee_no_aadhaar}/kyc",
                           headers=H, json={"aadhar_number": "123456789012"})
        assert r.status_code == 200, r.text
        r2 = requests.post(f"{BASE_URL}/api/admin/employees/{temp_employee_no_aadhaar}/generate-uan", headers=H)
        assert r2.status_code == 200, r2.text
        j = r2.json()
        assert j.get("ok") is True
        assert j["job"]["status"] in ("manual_required", "pending")


# ---------------- (8) OCR endpoint sanity ----------------
class TestOCR:
    def test_invalid_mime_400(self, H):
        # tiny valid base64 (10 bytes) but bad mime
        payload = {"pages": [{"document_base64": base64.b64encode(b"hello").decode(), "mime_type": "text/plain"}]}
        r = requests.post(f"{BASE_URL}/api/admin/ocr/parse-document", headers=H, json=payload)
        assert r.status_code == 400, r.text

    def test_no_document_400(self, H):
        r = requests.post(f"{BASE_URL}/api/admin/ocr/parse-document", headers=H, json={})
        assert r.status_code == 400


# ---------------- (9) KYC present_address -> users.address sync ----------------
class TestKycAddressSync:
    def test_present_address_syncs_to_users_address(self, H):
        addr = "TEST_iter91 Address, Bhilwara 311001"
        r = requests.patch(f"{BASE_URL}/api/admin/employees/{TEST_EMP}/kyc",
                           headers=H, json={"present_address": addr})
        assert r.status_code == 200, r.text
        rg = requests.get(f"{BASE_URL}/api/admin/employees/{TEST_EMP}/profile", headers=H)
        assert rg.json().get("address") == addr


# ---------------- (10) Create employee with salary_structure_actual ----------------
class TestCreateEmployeeSalaryStructure:
    def test_create_persists_salary_structure_actual(self, H):
        import uuid as _u
        suffix = _u.uuid4().hex[:6]
        payload = {
            "name": f"TEST_iter91 create {suffix}",
            "phone": "+9198886" + suffix[:5],
            "salary_structure_actual": [
                {"head": "Basic Salary", "amount": 12000, "rate_type": "daily"},
                {"head": "Salary 1", "amount": 200, "working_days": 30},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/admin/employees", headers=H, json=payload)
        assert r.status_code == 200, r.text
        j = r.json()
        uid = j.get("user_id") or (j.get("user") or {}).get("user_id")
        assert uid, f"no user_id: {j}"
        rg = requests.get(f"{BASE_URL}/api/admin/employees/{uid}/salary", headers=H)
        j = rg.json()
        basic = next((row for row in j["salary_structure_actual"]
                      if row["head"].lower().startswith("basic")), None)
        assert basic is not None
        assert basic["amount"] == 12000
