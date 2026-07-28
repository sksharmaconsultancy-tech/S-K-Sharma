"""Iter 359 — PF & ESIC Claims Management System backend tests."""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL",
                          "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PASS = "sharma123"
KANKANI_ID = "cmp_527fecdd7c"
EMP_CODE = "50"

created_ids = []


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": SUPER_EMAIL, "password": SUPER_PASS},
                      timeout=15)
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_meta(h):
    r = requests.get(f"{BASE_URL}/api/admin/claims/meta", headers=h, timeout=15)
    assert r.status_code == 200
    d = r.json()
    for key in ("pf_types", "esic_types", "pf_statuses", "esic_statuses", "doc_checklist"):
        assert key in d
    assert "Final Settlement (Form-19)" in d["pf_types"]
    assert "Sickness Benefit" in d["esic_types"]
    assert "pf" in d["doc_checklist"] and "esic" in d["doc_checklist"]


def test_create_pf_claim_existing_company_autofill(h):
    payload = {
        "claim_kind": "pf",
        "company_id": KANKANI_ID,
        "status": "Pending",
        "data": {
            "employee_code": EMP_CODE,
            "claim_type": "Final Settlement (Form-19)",
            "claim_amount": 50000,
            "application_date": "2026-01-15",
        },
        "documents": {"Form (signed)": True, "Aadhaar": True},
    }
    r = requests.post(f"{BASE_URL}/api/admin/claims", headers=h, json=payload, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["claim_no"].startswith("CLM-PF-")
    assert len(d["claim_no"].split("-")[-1]) == 5
    assert "ai_flags" in d
    assert isinstance(d["doc_score"], int)
    assert d["expected_settlement"]
    created_ids.append(d["claim_id"])

    # GET to verify data persisted + autofill
    lr = requests.get(f"{BASE_URL}/api/admin/claims?claim_kind=pf&q={EMP_CODE}",
                      headers=h, timeout=15)
    assert lr.status_code == 200
    claims = lr.json()["claims"]
    match = [c for c in claims if c["claim_id"] == d["claim_id"]]
    assert match, "created claim not returned in list"
    c = match[0]
    # autofill from Employee Master
    assert c["data"].get("employee_name"), "employee_name should auto-fill"
    assert "SURENDRA" in (c["data"].get("employee_name") or "").upper()


def test_create_external_company_claim(h):
    payload = {
        "claim_kind": "pf",
        "status": "Pending",
        "data": {
            "company_name": "TEST_XYZ External Ltd",
            "employee_code": "EXT001",
            "employee_name": "TEST_External Employee",
            "claim_type": "Final Settlement (Form-19)",
            "claim_amount": 12000,
            "uan": "123456789012",
        },
        "documents": {"Form (signed)": True},
    }
    r = requests.post(f"{BASE_URL}/api/admin/claims", headers=h, json=payload, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    created_ids.append(d["claim_id"])
    # verify stored with company_id="external"
    lr = requests.get(f"{BASE_URL}/api/admin/claims?claim_kind=pf",
                      headers=h, timeout=15)
    row = next((c for c in lr.json()["claims"] if c["claim_id"] == d["claim_id"]), None)
    assert row is not None
    assert row["company_id"] == "external"
    assert row["data"]["company_name"] == "TEST_XYZ External Ltd"


def test_ai_flag_form10c_over_10yrs(h):
    payload = {
        "claim_kind": "pf",
        "company_id": KANKANI_ID,
        "status": "Pending",
        "data": {
            "employee_code": "TEST_10C_EMP",
            "employee_name": "TEST_LongService",
            "claim_type": "Pension Withdrawal (Form-10C)",
            "doj": "2010-01-01",
            "dol": "2025-01-01",
            "uan": "123456789012",
            "claim_amount": 20000,
        },
    }
    r = requests.post(f"{BASE_URL}/api/admin/claims", headers=h, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    created_ids.append(d["claim_id"])
    flags = " ".join(d["ai_flags"]).lower()
    assert "form-10d" in flags or "10+ yrs" in flags or "10-d" in flags, \
        f"expected Form-10D eligibility flag, got {d['ai_flags']}"


def test_ai_flag_invalid_uan(h):
    payload = {
        "claim_kind": "pf",
        "company_id": KANKANI_ID,
        "status": "Pending",
        "data": {
            "employee_code": "TEST_BADUAN",
            "employee_name": "TEST_BadUAN",
            "claim_type": "Final Settlement (Form-19)",
            "uan": "123",
            "claim_amount": 5000,
            "dol": "2026-01-01",
            "doj": "2024-01-01",
        },
    }
    r = requests.post(f"{BASE_URL}/api/admin/claims", headers=h, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    created_ids.append(d["claim_id"])
    flags = " ".join(d["ai_flags"]).lower()
    assert "uan" in flags and ("invalid" in flags or "12 digits" in flags), \
        f"expected invalid UAN flag, got {d['ai_flags']}"


def test_duplicate_detection(h):
    # File same claim_type + employee_code + company again → dup flag
    payload = {
        "claim_kind": "pf",
        "company_id": KANKANI_ID,
        "status": "Pending",
        "data": {
            "employee_code": EMP_CODE,
            "claim_type": "Final Settlement (Form-19)",
            "claim_amount": 60000,
            "uan": "123456789012",
        },
    }
    r = requests.post(f"{BASE_URL}/api/admin/claims", headers=h, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    created_ids.append(d["claim_id"])
    flags = " ".join(d["ai_flags"]).lower()
    assert "duplicate" in flags, f"expected duplicate flag, got {d['ai_flags']}"


def test_status_update_settled_timeline(h):
    assert created_ids, "need a created claim"
    cid = created_ids[0]
    payload = {
        "claim_id": cid,
        "claim_kind": "pf",
        "company_id": KANKANI_ID,
        "status": "Settled",
        "data": {"payment_reference": "TEST_UTR123"},
    }
    r = requests.post(f"{BASE_URL}/api/admin/claims", headers=h, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    # verify
    lr = requests.get(f"{BASE_URL}/api/admin/claims?claim_kind=pf",
                      headers=h, timeout=15)
    row = next((c for c in lr.json()["claims"] if c["claim_id"] == cid), None)
    assert row is not None
    assert row["status"] == "Settled"
    assert row["data"].get("settlement_date"), "settlement_date must auto-set"
    tl = row.get("timeline") or []
    assert any(t.get("status") == "Settled" for t in tl), "timeline missing Settled entry"


def test_list_with_filters(h):
    r = requests.get(f"{BASE_URL}/api/admin/claims?claim_kind=pf&status=Settled",
                     headers=h, timeout=15)
    assert r.status_code == 200
    assert all(c["status"] == "Settled" for c in r.json()["claims"])


def test_dashboard(h):
    r = requests.get(f"{BASE_URL}/api/admin/claims/dashboard", headers=h, timeout=15)
    assert r.status_code == 200
    d = r.json()
    for k in ("total_pf", "total_esic", "pending", "approved", "rejected",
              "settled", "claim_amount", "settlement_amount",
              "avg_processing_days", "due_today", "due_week", "due_month"):
        assert k in d, f"missing dashboard field {k}"
    assert d["total_pf"] >= len([i for i in created_ids])


def test_reminders(h):
    r = requests.get(f"{BASE_URL}/api/admin/claims/reminders", headers=h, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "due" in d and "count" in d
    assert isinstance(d["due"], list)


def test_pf_register_report_json(h):
    r = requests.get(f"{BASE_URL}/api/admin/claims/report/pf-register",
                     headers=h, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["title"]
    assert isinstance(d["columns"], list) and len(d["columns"]) > 0
    assert isinstance(d["rows"], list)


def test_pf_register_xlsx(h):
    r = requests.get(f"{BASE_URL}/api/admin/claims/report/pf-register.xlsx",
                     headers=h, timeout=30)
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "spreadsheet" in ct or "octet" in ct
    assert len(r.content) > 500


def test_pf_register_pdf(h):
    r = requests.get(f"{BASE_URL}/api/admin/claims/report/pf-register.pdf",
                     headers=h, timeout=30)
    assert r.status_code == 200
    assert "pdf" in r.headers.get("content-type", "")
    assert r.content[:4] == b"%PDF"


def test_delete_claim_and_404(h):
    # delete all created + verify one comes back as 404
    for cid in created_ids:
        r = requests.delete(f"{BASE_URL}/api/admin/claims/{cid}",
                            headers=h, timeout=15)
        assert r.status_code == 200, f"delete failed for {cid}: {r.text}"
    r = requests.delete(f"{BASE_URL}/api/admin/claims/{created_ids[0]}",
                        headers=h, timeout=15)
    assert r.status_code == 404
