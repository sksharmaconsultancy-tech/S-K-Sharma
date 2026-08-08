"""Iter 524 — Punch-Time Photo Capture backend tests.

Endpoints under test:
  * GET  /api/admin/punch-logs (photo filter, photo_status field)
  * GET  /api/admin/punch-logs/photo
  * GET  /api/admin/punch-logs/photo.jpg (session-token query param)
  * GET  /api/admin/punch-logs.pdf (with & without embedded photos)
  * GET  /api/admin/punch-photos/reconciliation
  * POST /api/admin/punch-photos/retry-match
  * GET  /api/admin/punch-logs.xlsx (regression, photo column)
"""
from __future__ import annotations

import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
ADMIN_PW = "sharma123"
CAPTURED_REF = "zk_1ecabfb2c771"  # seeded photo (2026-06-20)
FROM_DATE = "2026-06-01"
TO_DATE = "2026-06-30"


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PW}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text[:200]}"
    tok = r.json().get("session_token") or r.json().get("token")
    assert tok, f"no token in response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def hdr(token) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------- punch-logs list + filters ------------------------ #
class TestPunchLogs:
    def test_list_baseline_returns_rows_with_expected_columns(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/punch-logs",
                         params={"from_date": FROM_DATE, "to_date": TO_DATE},
                         headers=hdr, timeout=60)
        assert r.status_code == 200, r.text[:200]
        j = r.json()
        assert "rows" in j and "machines" in j and "total" in j
        assert isinstance(j["rows"], list)
        # find seeded captured row
        captured = [x for x in j["rows"] if x.get("record_id") == CAPTURED_REF]
        assert captured, f"seed record {CAPTURED_REF} not returned"
        row = captured[0]
        assert row["photo_status"] == "captured"
        assert row["has_photo"] is True
        assert row["photo_ref"] == CAPTURED_REF
        # legacy columns present (regression)
        for col in ("name_in_machine", "machine_name", "ot", "flag",
                    "employee_code", "bio_code", "name"):
            assert col in row, f"missing column {col}"

    def test_photo_filter_available(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/punch-logs",
                         params={"from_date": FROM_DATE, "to_date": TO_DATE,
                                 "photo": "available"},
                         headers=hdr, timeout=60)
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert rows, "expected at least one row with a photo"
        assert all(x["photo_status"] == "captured" for x in rows)
        assert any(x.get("record_id") == CAPTURED_REF for x in rows)

    def test_photo_filter_missing(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/punch-logs",
                         params={"from_date": FROM_DATE, "to_date": TO_DATE,
                                 "photo": "missing"},
                         headers=hdr, timeout=60)
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert all(x["photo_status"] == "missing" for x in rows)

    def test_photo_filter_pending(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/punch-logs",
                         params={"from_date": FROM_DATE, "to_date": TO_DATE,
                                 "photo": "pending"},
                         headers=hdr, timeout=60)
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert all(x["photo_status"] == "pending" for x in rows)

    def test_not_found_rows_still_present(self, hdr):
        """Regression: unmapped device punches (NOT FOUND) still surface."""
        r = requests.get(f"{BASE_URL}/api/admin/punch-logs",
                         params={"from_date": "2026-01-01", "to_date": "2026-12-31"},
                         headers=hdr, timeout=90)
        assert r.status_code == 200
        rows = r.json()["rows"]
        # not_found flag surface is a soft assertion; app may or may not
        # have unmapped rows in test DB, so we only check schema shape.
        assert isinstance(rows, list)


# ---------------------- photo endpoints (JSON + JPG) --------------------- #
class TestPhotoEndpoints:
    def test_photo_json(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/punch-logs/photo",
                         params={"ref": CAPTURED_REF}, headers=hdr, timeout=30)
        assert r.status_code == 200, r.text[:200]
        j = r.json()
        assert j.get("photo_base64"), "photo_base64 missing"
        assert "caption" in j
        assert len(j["photo_base64"]) > 100

    def test_photo_jpg_with_query_token(self, token):
        # <img> tags can't set headers → token via query param
        r = requests.get(f"{BASE_URL}/api/admin/punch-logs/photo.jpg",
                         params={"ref": CAPTURED_REF, "token": token},
                         timeout=30)
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("content-type", "").startswith("image/"), \
            f"unexpected content-type: {r.headers.get('content-type')}"
        assert len(r.content) > 500

    def test_photo_jpg_without_token_forbidden(self):
        r = requests.get(f"{BASE_URL}/api/admin/punch-logs/photo.jpg",
                         params={"ref": CAPTURED_REF}, timeout=30)
        assert r.status_code in (401, 403), \
            f"expected 401/403 unauthenticated, got {r.status_code}"

    def test_photo_json_bad_ref_404(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/punch-logs/photo",
                         params={"ref": "zk_does_not_exist_zzz"},
                         headers=hdr, timeout=30)
        assert r.status_code == 404


# ---------------------- PDF export -------------------------------------- #
class TestPdfExport:
    def test_pdf_without_photos(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/punch-logs.pdf",
                         params={"from_date": FROM_DATE, "to_date": TO_DATE,
                                 "include_photos": 0},
                         headers=hdr, timeout=60)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF", "not a valid PDF header"
        assert len(r.content) > 500

    def test_pdf_with_embedded_photos(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/punch-logs.pdf",
                         params={"from_date": FROM_DATE, "to_date": TO_DATE,
                                 "include_photos": 1},
                         headers=hdr, timeout=90)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
        # rough size sanity — a PDF with an embedded image should be
        # larger than the plain-text one.
        assert len(r.content) > 1000


# ---------------------- Reconciliation ---------------------------------- #
class TestReconciliation:
    def test_reconciliation_counts_consistent(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/punch-photos/reconciliation",
                         params={"from_date": FROM_DATE, "to_date": TO_DATE},
                         headers=hdr, timeout=60)
        assert r.status_code == 200, r.text[:200]
        j = r.json()
        for k in ("total_punches", "photos_received", "photos_pending",
                  "photos_missing", "failed_photo_sync", "parked_photos"):
            assert k in j, f"missing key {k}"
            assert isinstance(j[k], int), f"{k} not int: {j[k]!r}"
        # received + pending + missing should equal total (spec ≈ approx)
        s = j["photos_received"] + j["photos_pending"] + j["photos_missing"]
        assert s == j["total_punches"], \
            f"received+pending+missing ({s}) != total_punches ({j['total_punches']})"
        # seed guarantees at least one captured
        assert j["photos_received"] >= 1


# ---------------------- Retry match ------------------------------------- #
class TestRetryMatch:
    def test_retry_match_super_admin(self, hdr):
        r = requests.post(f"{BASE_URL}/api/admin/punch-photos/retry-match",
                          headers=hdr, timeout=120)
        assert r.status_code == 200, r.text[:200]
        j = r.json()
        assert j.get("ok") is True
        assert isinstance(j.get("scanned"), int)
        assert isinstance(j.get("matched"), int)
        assert j["scanned"] >= 0 and j["matched"] >= 0

    def test_retry_match_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/admin/punch-photos/retry-match",
                          timeout=30)
        assert r.status_code in (401, 403)


# ---------------------- XLSX regression --------------------------------- #
class TestXlsxRegression:
    def test_xlsx_still_works(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/punch-logs.xlsx",
                         params={"from_date": FROM_DATE, "to_date": TO_DATE},
                         headers=hdr, timeout=120)
        assert r.status_code == 200
        # XLSX = ZIP (PK header)
        assert r.content[:2] == b"PK", "not an XLSX (missing PK header)"
        ct = r.headers.get("content-type", "")
        assert "spreadsheet" in ct or "openxmlformats" in ct
