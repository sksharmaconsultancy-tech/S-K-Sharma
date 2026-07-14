"""Iter 95 — HR Letters + Bonus Registers + Annual Returns backend tests."""
import os
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"
FY = 2025
YEAR = 2025


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def sample_employee(headers):
    r = requests.get(
        f"{BASE}/api/admin/employees",
        params={"company_id": COMPANY_ID, "limit": 200},
        headers=headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    users = data.get("employees") or data.get("users") or data.get("items") or data
    assert users, f"No employees found: {data}"
    # Find code 50 preferred
    for u in users:
        if str(u.get("employee_code")) == "50":
            return u
    return users[0]


# -------------------- HR Letters --------------------

class TestHRLetterTemplates:
    @pytest.mark.parametrize("ltype", ["appointment", "offer", "warning", "termination"])
    def test_template(self, headers, sample_employee, ltype):
        r = requests.get(
            f"{BASE}/api/admin/hr-letters/template/{ltype}",
            params={"company_id": COMPANY_ID, "user_id": sample_employee["user_id"]},
            headers=headers, timeout=30,
        )
        assert r.status_code == 200, f"{ltype}: {r.status_code} {r.text}"
        d = r.json()
        assert d["letter_type"] == ltype
        assert d["subject"].strip()
        assert d["body"].strip()
        # Employee name should appear in body
        assert (sample_employee.get("name") or "").split()[0] in d["body"]

    def test_template_invalid_type(self, headers, sample_employee):
        r = requests.get(
            f"{BASE}/api/admin/hr-letters/template/foobar",
            params={"company_id": COMPANY_ID, "user_id": sample_employee["user_id"]},
            headers=headers, timeout=30,
        )
        assert r.status_code == 400


class TestHRLetterCRUD:
    letter_id = None

    def test_create(self, headers, sample_employee):
        # Get template first
        tpl = requests.get(
            f"{BASE}/api/admin/hr-letters/template/appointment",
            params={"company_id": COMPANY_ID, "user_id": sample_employee["user_id"]},
            headers=headers, timeout=30,
        ).json()
        r = requests.post(
            f"{BASE}/api/admin/hr-letters",
            json={
                "company_id": COMPANY_ID,
                "user_id": sample_employee["user_id"],
                "letter_type": "appointment",
                "subject": tpl["subject"],
                "body": tpl["body"] + "\n\nTEST_ITER95",
            },
            headers=headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        letter = r.json()["letter"]
        assert letter["ref_no"].startswith("KEPS/APT/")
        assert letter["letter_id"].startswith("ltr_")
        TestHRLetterCRUD.letter_id = letter["letter_id"]

    def test_register_lists_created(self, headers):
        r = requests.get(
            f"{BASE}/api/admin/hr-letters",
            params={"company_id": COMPANY_ID}, headers=headers, timeout=30,
        )
        assert r.status_code == 200
        ids = [x["letter_id"] for x in r.json().get("letters", [])]
        assert TestHRLetterCRUD.letter_id in ids

    def test_pdf_bytes(self, headers):
        r = requests.get(
            f"{BASE}/api/admin/hr-letters/{TestHRLetterCRUD.letter_id}/pdf",
            headers=headers, timeout=30,
        )
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"

    def test_delete(self, headers):
        r = requests.delete(
            f"{BASE}/api/admin/hr-letters/{TestHRLetterCRUD.letter_id}",
            headers=headers, timeout=30,
        )
        assert r.status_code == 200
        # Verify gone
        r2 = requests.get(
            f"{BASE}/api/admin/hr-letters/{TestHRLetterCRUD.letter_id}/pdf",
            headers=headers, timeout=30,
        )
        assert r2.status_code == 404


# -------------------- Bonus Financials --------------------

class TestBonusFinancials:
    def test_put_and_get(self, headers):
        payload = {
            "company_id": COMPANY_ID,
            "fy_start_year": FY,
            "gross_profit": 5000000.0,
            "depreciation": 200000.0,
            "development_rebate": 100000.0,
            "direct_tax": 300000.0,
            "other_sums": 50000.0,
            "allocable_percent": 60.0,
            "payment_date": "31-10-2025",
            "nature_of_industry": "Textile Manufacturing",
            "employer_name": "Prakash Kankani",
            "set_on_off_rows": [
                {"year": "2023-24", "allocable_surplus": 100000, "bonus_payable": 80000,
                 "set_on": 20000, "set_off": 0},
                {"year": "2024-25", "allocable_surplus": 120000, "bonus_payable": 110000,
                 "set_on": 10000, "set_off": 0},
            ],
        }
        r = requests.put(
            f"{BASE}/api/admin/bonus-registers/financials",
            json=payload, headers=headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        fin = r.json()["financials"]
        assert fin["gross_profit"] == 5000000.0
        assert len(fin["set_on_off_rows"]) == 2

        # GET
        r2 = requests.get(
            f"{BASE}/api/admin/bonus-registers/financials",
            params={"company_id": COMPANY_ID, "fy_start_year": FY},
            headers=headers, timeout=30,
        )
        assert r2.status_code == 200
        fin2 = r2.json()["financials"]
        assert fin2["gross_profit"] == 5000000.0
        assert fin2["nature_of_industry"] == "Textile Manufacturing"


# -------------------- Bonus PDF forms --------------------

@pytest.mark.parametrize("form", ["form-a", "form-b", "form-c", "form-d"])
def test_bonus_form_pdf(headers, form):
    r = requests.get(
        f"{BASE}/api/admin/bonus-registers/{form}.pdf",
        params={"company_id": COMPANY_ID, "fy_start_year": FY},
        headers=headers, timeout=90,
    )
    assert r.status_code == 200, f"{form}: {r.status_code} {r.text[:300]}"
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:4] == b"%PDF"


# -------------------- Annual Returns --------------------

@pytest.mark.parametrize("path", ["equal-remuneration", "ismw"])
def test_annual_return_pdf(headers, path):
    r = requests.get(
        f"{BASE}/api/admin/annual-returns/{path}.pdf",
        params={"company_id": COMPANY_ID, "year": YEAR},
        headers=headers, timeout=60,
    )
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:300]}"
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:4] == b"%PDF"


# -------------------- Bonus run preview (fix verification) --------------------

def test_bonus_run_preview_total(headers):
    r = requests.post(
        f"{BASE}/api/admin/bonus-runs/preview",
        json={"company_id": COMPANY_ID, "fy_start_year": FY},
        headers=headers, timeout=120,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    total = float(d.get("total_bonus") or 0)
    assert total > 0, f"total_bonus should be > 0, got {total}"
    # Should be ~727708 (rate-fix)
    assert 700000 < total < 800000, f"total_bonus expected ~727708 got {total}"
