"""Iter 497 — POST /api/report-export/pdf tests.

Covers:
* 401 when no auth
* 400 when columns list empty
* 200 application/pdf with valid banded columns + footer
* 400 when too many columns (>80)
* Content starts with %PDF header
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
PDF_URL = f"{BASE_URL}/api/report-export/pdf"

ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
ADMIN_PASS = "sharma123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    tok = r.json().get("session_token")
    assert tok
    return tok


@pytest.fixture
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# --- 401 unauthenticated ------------------------------------------------
def test_pdf_requires_auth():
    r = requests.post(PDF_URL, json={"title": "T", "columns": [{"label": "A"}], "rows": []}, timeout=30)
    assert r.status_code in (401, 403), f"Expected 401/403 got {r.status_code}: {r.text[:200]}"


# --- 400 empty columns --------------------------------------------------
def test_pdf_empty_columns_returns_400(auth_headers):
    r = requests.post(PDF_URL, headers=auth_headers, json={"title": "T", "columns": [], "rows": []}, timeout=30)
    assert r.status_code == 400
    assert "columns" in r.text.lower() or "No columns" in r.text


# --- 400 too many columns ----------------------------------------------
def test_pdf_too_many_columns_returns_400(auth_headers):
    cols = [{"label": f"c{i}", "align": "left", "width": 60} for i in range(90)]
    r = requests.post(PDF_URL, headers=auth_headers, json={"title": "T", "columns": cols, "rows": [["x"] * 90]}, timeout=30)
    assert r.status_code == 400
    assert "Too many columns" in r.text or "max" in r.text.lower()


# --- 200 simple PDF -----------------------------------------------------
def test_pdf_basic_generation(auth_headers):
    body = {
        "title": "TEST Simple Report",
        "subtitle": "unit test",
        "columns": [
            {"label": "Sr", "align": "center", "width": 40},
            {"label": "Name", "align": "left", "width": 200},
            {"label": "Amount", "align": "right", "width": 100},
        ],
        "rows": [
            [1, "John Doe", "1000.00"],
            [2, "Jane Smith", "2500.50"],
        ],
        "footer": ["TOTAL", "", "3500.50"],
    }
    r = requests.post(PDF_URL, headers=auth_headers, json=body, timeout=60)
    assert r.status_code == 200, r.text[:300]
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:4] == b"%PDF", "Response is not a valid PDF"
    assert len(r.content) > 500
    # Filename should be present
    cd = r.headers.get("content-disposition", "")
    assert "TEST" in cd or "Report" in cd


# --- 200 banded PDF (salary-register shape) -----------------------------
def test_pdf_banded_headers_generation(auth_headers):
    body = {
        "title": "TEST Salary Register — Kankani",
        "subtitle": "Jul FY 2026-27",
        "columns": [
            {"label": "Sr", "align": "center", "width": 40, "band": {"label": "Employee", "color": "#1E3A8A"}},
            {"label": "Code", "align": "left", "width": 80, "band": {"label": "Employee", "color": "#1E3A8A"}},
            {"label": "Name", "align": "left", "width": 200, "band": {"label": "Employee", "color": "#1E3A8A"}},
            {"label": "Days", "align": "right", "width": 60, "band": {"label": "Attendance", "color": "#059669"}},
            {"label": "OT", "align": "right", "width": 60, "band": {"label": "Attendance", "color": "#059669"}},
            {"label": "Basic", "align": "right", "width": 100, "band": {"label": "Earnings", "color": "#B45309"}},
            {"label": "HRA", "align": "right", "width": 100, "band": {"label": "Earnings", "color": "#B45309"}},
            {"label": "Net", "align": "right", "width": 110, "band": {"label": "Earnings", "color": "#B45309"}},
        ],
        "rows": [
            [i, f"K{i:03d}", f"Employee {i}", 26, 4, "15000", "4500", "18500"] for i in range(1, 19)
        ],
        "footer": ["TOTAL", "", "", "468", "72", "270000", "81000", "333000"],
    }
    r = requests.post(PDF_URL, headers=auth_headers, json=body, timeout=60)
    assert r.status_code == 200, r.text[:300]
    assert r.content[:4] == b"%PDF"
    assert len(r.content) > 1000


# --- 200 handles long text wrapping -------------------------------------
def test_pdf_long_text_wraps(auth_headers):
    long = "This is a very long employee name that must wrap using Paragraph in the PDF so that it does not truncate or overlap the neighbouring column"
    body = {
        "title": "TEST Long Text",
        "columns": [
            {"label": "Sr", "align": "center", "width": 40},
            {"label": "Notes", "align": "left", "width": 220},
        ],
        "rows": [[i, long] for i in range(1, 6)],
    }
    r = requests.post(PDF_URL, headers=auth_headers, json=body, timeout=60)
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"
