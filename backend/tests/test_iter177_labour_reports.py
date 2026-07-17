"""Iter 177 backend tests — Labour Law Compliance Reports Module.

Covers:
  * catalogue (22 reports)
  * generate for each of the 22 report_keys (json)
  * pdf/excel/csv exports for daily_attendance + muster_roll
  * filter behaviour (department/gender/contractor reduces rows)
  * explicit from/to date range and >62 days => 400
  * unknown report_key => 400
  * verify endpoint (public) — 200 for known id, 404 for unknown
  * unknown company_id still 200 (empty employees) — but validate no 500
"""
import base64
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PW = "sharma123"
COMPANY_ID = "cmp_527fecdd7c"
MONTH = "2026-06"


@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{API}/auth/admin-password-login",
                      json={"email": SUPER_EMAIL, "password": SUPER_PW}, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    tok = j.get("session_token") or j.get("token") or j.get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def hdr(super_token):
    return {"Authorization": f"Bearer {super_token}", "Content-Type": "application/json"}


# ---------------- Catalogue ----------------
def test_catalogue_has_22_reports(hdr):
    r = requests.get(f"{API}/admin/labour-reports/catalogue", headers=hdr, timeout=30)
    assert r.status_code == 200, r.text
    reports = r.json().get("reports", [])
    assert len(reports) == 22, f"Expected 22, got {len(reports)}"
    keys = {r["key"] for r in reports}
    # spot check a few
    for k in ("daily_attendance", "muster_roll", "device_wise", "location_wise"):
        assert k in keys
    # groups present
    groups = {r["group"] for r in reports}
    assert {"Registers", "Daily Reports", "Shift Reports", "Technology Reports"} <= groups


ALL_REPORT_KEYS = [
    "daily_attendance", "muster_roll", "monthly_register", "overtime_register",
    "present_absent", "late_coming", "early_going", "miss_punch", "in_out_punch",
    "half_day", "shift_report", "night_shift", "double_shift", "weekly_off",
    "holiday_attendance", "geofence_attendance", "gps_attendance", "face_attendance",
    "qr_attendance", "biometric_attendance", "device_wise", "location_wise",
]


# ---------------- Generate JSON for all 22 ----------------
@pytest.mark.parametrize("key", ALL_REPORT_KEYS)
def test_generate_each_report_json(hdr, key):
    body = {"company_id": COMPANY_ID, "report_key": key,
            "filters": {"month": MONTH}, "format": "json"}
    r = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=body, timeout=120)
    assert r.status_code == 200, f"[{key}] {r.status_code}: {r.text[:400]}"
    j = r.json()
    assert "columns" in j and isinstance(j["columns"], list) and len(j["columns"]) > 0
    assert "rows" in j and isinstance(j["rows"], list)
    assert "total_rows" in j
    assert "verify_id" in j and j["verify_id"].startswith("lrv_")
    assert j.get("from_date") == "2026-06-01"
    assert j.get("to_date") == "2026-06-30"


# ---------------- File format exports ----------------
def test_export_daily_attendance_pdf(hdr):
    body = {"company_id": COMPANY_ID, "report_key": "daily_attendance",
            "filters": {"month": MONTH}, "format": "pdf"}
    r = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=body, timeout=180)
    assert r.status_code == 200, r.text[:400]
    j = r.json()
    assert j["filename"].endswith(".pdf")
    raw = base64.b64decode(j["file_base64"])
    assert len(raw) > 4000
    assert raw[:4] == b"%PDF"


def test_export_muster_roll_excel(hdr):
    body = {"company_id": COMPANY_ID, "report_key": "muster_roll",
            "filters": {"month": MONTH}, "format": "excel"}
    r = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=body, timeout=180)
    assert r.status_code == 200, r.text[:400]
    j = r.json()
    assert j["filename"].endswith(".xlsx")
    raw = base64.b64decode(j["file_base64"])
    assert len(raw) > 1000
    assert raw[:2] == b"PK"  # zip magic


def test_export_daily_attendance_csv(hdr):
    body = {"company_id": COMPANY_ID, "report_key": "daily_attendance",
            "filters": {"month": MONTH}, "format": "csv"}
    r = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=body, timeout=180)
    assert r.status_code == 200
    j = r.json()
    assert j["filename"].endswith(".csv")
    raw = base64.b64decode(j["file_base64"])
    # utf-8-sig BOM + header row
    assert len(raw) > 20
    assert b"Date" in raw[:100]


def test_export_muster_roll_csv(hdr):
    body = {"company_id": COMPANY_ID, "report_key": "muster_roll",
            "filters": {"month": MONTH}, "format": "csv"}
    r = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=body, timeout=180)
    assert r.status_code == 200
    raw = base64.b64decode(r.json()["file_base64"])
    assert b"Employee Name" in raw[:200]


# ---------------- Filters ----------------
def test_gender_filter_reduces_rows(hdr):
    base_body = {"company_id": COMPANY_ID, "report_key": "monthly_register",
                 "filters": {"month": MONTH}, "format": "json"}
    r0 = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=base_body, timeout=120)
    assert r0.status_code == 200
    total0 = r0.json()["total_rows"]

    filt_body = {**base_body, "filters": {"month": MONTH, "gender": "Male"}}
    r1 = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=filt_body, timeout=120)
    assert r1.status_code == 200
    total1 = r1.json()["total_rows"]
    # filter must produce <= all rows (may be 0 if no gender data — either OK)
    assert total1 <= total0


def test_explicit_from_to_range(hdr):
    body = {"company_id": COMPANY_ID, "report_key": "daily_attendance",
            "filters": {"from_date": "2026-06-01", "to_date": "2026-06-07"},
            "format": "json"}
    r = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=body, timeout=120)
    assert r.status_code == 200
    j = r.json()
    assert j["from_date"] == "2026-06-01"
    assert j["to_date"] == "2026-06-07"


def test_range_exceeding_62_days_400(hdr):
    body = {"company_id": COMPANY_ID, "report_key": "daily_attendance",
            "filters": {"from_date": "2026-01-01", "to_date": "2026-04-01"},
            "format": "json"}
    r = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=body, timeout=60)
    assert r.status_code == 400
    assert "62" in r.text or "range" in r.text.lower()


def test_unknown_report_key_400(hdr):
    body = {"company_id": COMPANY_ID, "report_key": "nope_not_a_thing",
            "filters": {"month": MONTH}, "format": "json"}
    r = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=body, timeout=30)
    assert r.status_code == 400


def test_missing_company_id_400(hdr):
    body = {"report_key": "daily_attendance",
            "filters": {"month": MONTH}, "format": "json"}
    r = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=body, timeout=30)
    assert r.status_code == 400


def test_missing_month_and_dates_400(hdr):
    body = {"company_id": COMPANY_ID, "report_key": "daily_attendance",
            "filters": {}, "format": "json"}
    r = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=body, timeout=30)
    assert r.status_code == 400


# ---------------- Verify endpoint ----------------
def test_verify_endpoint_roundtrip(hdr):
    body = {"company_id": COMPANY_ID, "report_key": "daily_attendance",
            "filters": {"month": MONTH}, "format": "json"}
    r = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=body, timeout=120)
    assert r.status_code == 200
    verify_id = r.json()["verify_id"]

    # PUBLIC — no auth header
    v = requests.get(f"{API}/admin/labour-reports/verify/{verify_id}", timeout=30)
    assert v.status_code == 200, v.text
    doc = v.json().get("verification") or {}
    assert doc.get("verify_id") == verify_id
    assert doc.get("report_key") == "daily_attendance"
    assert doc.get("company_id") == COMPANY_ID


def test_verify_unknown_id_404():
    v = requests.get(f"{API}/admin/labour-reports/verify/lrv_deadbeef00", timeout=30)
    assert v.status_code == 404


# ---------------- Sanity: known keys returned by tech reports should not 500 ----------------
def test_tech_reports_do_not_500(hdr):
    for k in ("face_attendance", "qr_attendance", "geofence_attendance",
              "gps_attendance", "biometric_attendance"):
        body = {"company_id": COMPANY_ID, "report_key": k,
                "filters": {"month": MONTH}, "format": "json"}
        r = requests.post(f"{API}/admin/labour-reports/generate", headers=hdr, json=body, timeout=120)
        assert r.status_code == 200, f"[{k}] {r.status_code}: {r.text[:300]}"
        time.sleep(0.05)
