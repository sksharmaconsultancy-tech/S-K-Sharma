"""Iter 109 backend tests — Employee Master new fields, drafts CRUD, master PDF."""
import io
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
COMPANY_ID = "cmp_527fecdd7c"  # Kankani Enterprises


@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{API}/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"}, timeout=20)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("session_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def headers(super_token):
    return {"Authorization": f"Bearer {super_token}"}


# ---------- Create employee with FULL master payload (Iter 109) ----------
class TestCreateEmployeeFullMaster:
    created_user_id = None
    unique_suffix = uuid.uuid4().hex[:6]

    def test_01_create_with_new_fields(self, headers):
        mobile = f"+9199{uuid.uuid4().int % 100000000:08d}"
        payload = {
            "company_id": COMPANY_ID,
            "name": f"TEST IT109 {self.unique_suffix}",
            "phone": mobile,
            "designation": "Weaver",
            "employee_group": "Labour",
            "is_onroll": True,
            "pay_mode": "Cash",
            "salary_mode": "Monthly",
            "compliance_salary_mode": "Monthly",
            "salary_monthly": 20000,
            "compliance_gross": 15000,
            "compliance_salary_allowances": [
                {"name": "HRA", "value": 4400.5},
                {"name": "CONV.", "value": 2200},
            ],
            "compliance_salary_deductions": [
                {"name": "PF", "value": 1320},
                {"name": "ESI", "value": 165.25},
            ],
            "address": "Present Addr Bhilwara",
            "permanent_address": "Permanent Village Xyz, Rajasthan",
            "emergency_contact_name": "Sita Devi",
            "emergency_contact_phone": "+919999999999",
            "family_members": [
                {"name": "Ram Kumar", "relation": "Father", "dob": "1960-05-10"},
                {"name": "Gita", "relation": "Spouse", "dob": "1985-08-22"},
            ],
        }
        r = requests.post(f"{API}/admin/employees", json=payload, headers=headers, timeout=30)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
        data = r.json()
        # Support various response shapes
        uid = (data.get("employee") or {}).get("user_id") or data.get("user_id") or data.get("user", {}).get("user_id")
        assert uid, f"No user_id in response: {data}"
        TestCreateEmployeeFullMaster.created_user_id = uid

    def test_02_get_profile_reflects_new_fields(self, headers):
        uid = TestCreateEmployeeFullMaster.created_user_id
        assert uid
        r = requests.get(f"{API}/admin/employees/{uid}/profile", headers=headers, timeout=15)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p.get("pay_mode") == "Cash", f"pay_mode not persisted: {p.get('pay_mode')}"
        assert p.get("permanent_address") == "Permanent Village Xyz, Rajasthan"
        assert p.get("emergency_contact_name") == "Sita Devi"
        assert p.get("emergency_contact_phone") == "+919999999999"
        fams = p.get("family_members") or []
        assert len(fams) == 2, f"family_members len: {fams}"
        names = {(f or {}).get("name") for f in fams}
        assert "Ram Kumar" in names and "Gita" in names
        ca = p.get("compliance_salary_allowances") or []
        assert any((a or {}).get("name") == "HRA" for a in ca)
        cd = p.get("compliance_salary_deductions") or []
        assert any((d or {}).get("name") == "PF" for d in cd)

    def test_03_patch_profile_updates_new_fields(self, headers):
        uid = TestCreateEmployeeFullMaster.created_user_id
        assert uid
        patch = {
            "pay_mode": "Bank",
            "compliance_salary_deductions": [
                {"name": "PF", "value": 1500},
                {"name": "ADVANCE", "value": 500},
            ],
            "family_members": [
                {"name": "Ram Kumar Sr", "relation": "Father", "dob": "1960-05-10"},
            ],
            "permanent_address": "Updated Permanent Address",
        }
        r = requests.patch(f"{API}/admin/employees/{uid}/profile", json=patch, headers=headers, timeout=20)
        assert r.status_code == 200, r.text

        g = requests.get(f"{API}/admin/employees/{uid}/profile", headers=headers, timeout=15).json()
        assert g.get("pay_mode") == "Bank"
        assert g.get("permanent_address") == "Updated Permanent Address"
        fams = g.get("family_members") or []
        assert len(fams) == 1 and fams[0].get("name") == "Ram Kumar Sr"
        cd = g.get("compliance_salary_deductions") or []
        names = {(d or {}).get("name") for d in cd}
        assert names == {"PF", "ADVANCE"}, f"deductions not replaced: {cd}"

    def test_04_master_pdf_contains_new_sections(self, headers):
        uid = TestCreateEmployeeFullMaster.created_user_id
        assert uid
        r = requests.get(f"{API}/admin/employees/{uid}/master-pdf", headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        ct = r.headers.get("content-type", "")
        assert "pdf" in ct.lower() or r.content[:4] == b"%PDF", f"Not a PDF: {ct}"
        # Extract text
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader  # type: ignore
        text = ""
        try:
            reader = PdfReader(io.BytesIO(r.content))
            for pg in reader.pages:
                text += pg.extract_text() or ""
        except Exception as e:
            pytest.fail(f"PDF parsing failed: {e}")
        low = text.lower()
        required = ["designation", "salary details", "pay mode", "family details",
                    "emergency", "permanent", "pf no", "esi ip"]
        missing = [k for k in required if k not in low]
        assert not missing, f"PDF missing sections: {missing}. Text excerpt: {text[:500]}"
        # Should include the family name we saved (after patch it was "Ram Kumar Sr")
        assert "Ram Kumar Sr" in text or "ram kumar sr" in low, "Family member name missing from PDF"

    def test_99_cleanup(self, headers):
        uid = TestCreateEmployeeFullMaster.created_user_id
        if not uid:
            return
        # Best effort cleanup — direct DB via delete endpoint if exists
        r = requests.delete(f"{API}/admin/employees/{uid}", headers=headers, timeout=15)
        # Accept 200/204/404
        assert r.status_code in (200, 204, 404, 405), f"cleanup: {r.status_code} {r.text}"


# ---------- Employee drafts CRUD ----------
class TestEmployeeDrafts:
    draft_id = None

    def test_01_create_draft(self, headers):
        r = requests.post(f"{API}/admin/employee-drafts",
                          json={"company_id": COMPANY_ID, "form": {"name": "TEST_DRAFT X"}},
                          headers=headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert d.get("draft_id")
        TestEmployeeDrafts.draft_id = d["draft_id"]

    def test_02_list_shows_draft(self, headers):
        r = requests.get(f"{API}/admin/employee-drafts?company_id={COMPANY_ID}", headers=headers, timeout=15)
        assert r.status_code == 200, r.text
        drafts = r.json().get("drafts", [])
        ids = {d.get("draft_id") for d in drafts}
        assert TestEmployeeDrafts.draft_id in ids

    def test_03_update_draft_same_id(self, headers):
        did = TestEmployeeDrafts.draft_id
        r = requests.post(f"{API}/admin/employee-drafts",
                          json={"draft_id": did, "company_id": COMPANY_ID,
                                "form": {"name": "TEST_DRAFT X UPDATED"}},
                          headers=headers, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("draft_id") == did
        # Verify label updated
        lst = requests.get(f"{API}/admin/employee-drafts?company_id={COMPANY_ID}", headers=headers, timeout=15).json()
        for d in lst.get("drafts", []):
            if d.get("draft_id") == did:
                assert "UPDATED" in (d.get("label") or ""), f"label: {d.get('label')}"
                break
        else:
            pytest.fail("draft not found after update")

    def test_04_company_admin_scope_403(self):
        """Kankani company admin should NOT be able to list drafts for another firm."""
        # Log in as Kankani company admin via OTP
        r_otp = requests.post(f"{API}/auth/otp/request",
                              json={"channel": "sms", "identifier": "+919828100001"}, timeout=15)
        if r_otp.status_code != 200:
            pytest.skip(f"OTP request failed: {r_otp.status_code}")
        code = r_otp.json().get("dev_code")
        if not code:
            pytest.skip("no dev_code returned")
        r_v = requests.post(f"{API}/auth/otp/verify",
                            json={"channel": "sms", "identifier": "+919828100001", "code": code}, timeout=15)
        if r_v.status_code != 200:
            pytest.skip(f"OTP verify failed: {r_v.status_code}")
        ca_tok = r_v.json().get("token") or r_v.json().get("session_token")
        assert ca_tok
        ca_h = {"Authorization": f"Bearer {ca_tok}"}

        # Try to list some other company's drafts (use a fake id)
        r = requests.get(f"{API}/admin/employee-drafts?company_id=cmp_deadbeef00",
                         headers=ca_h, timeout=15)
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"

        # own scope should succeed
        r2 = requests.get(f"{API}/admin/employee-drafts?company_id={COMPANY_ID}",
                          headers=ca_h, timeout=15)
        assert r2.status_code == 200, r2.text

    def test_05_delete_draft(self, headers):
        did = TestEmployeeDrafts.draft_id
        r = requests.delete(f"{API}/admin/employee-drafts/{did}", headers=headers, timeout=15)
        assert r.status_code == 200, r.text
        # Verify gone
        lst = requests.get(f"{API}/admin/employee-drafts?company_id={COMPANY_ID}", headers=headers, timeout=15).json()
        ids = {d.get("draft_id") for d in lst.get("drafts", [])}
        assert did not in ids
