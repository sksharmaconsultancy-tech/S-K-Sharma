"""Iter 81 backend tests — three related fixes:

Fix 1 (Iter 77s) — Same-machine duplicate-punch dedup (15 min).
    `dedupe_same_machine_punches` drops any punch whose (kind, source)
    signature matches a kept punch AND is within 15 min of it.
    Applied inside `monthly_attendance_grid_json` and
    `_build_ot_report_rows`.

Fix 2 (Iter 77t) — Row totals `duty_hours` now INCLUDES OT.
    `totals.duty_hours` == `totals.hours` on the monthly-grid response.

Fix 3 (Iter 77s) — New `totals.duty_hours` field is present on every row
    (schema backward-compat check).

Every temp firm/user is prefixed with Iter81- / TEST_Iter81_. Clean up
via `python3 /app/scripts/cleanup_test_data.py --apply`.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
import requests

# Direct MongoDB access — needed to seed punches with custom `source`
# values (the manual-punch endpoint hard-codes source="manual_admin").
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


# ------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def super_token(http):
    r = http.post(
        f"{API}/auth/otp/request",
        json={"identifier": SUPER_EMAIL, "channel": "email"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    code = r.json().get("dev_code")
    assert code, r.json()
    r2 = http.post(
        f"{API}/auth/otp/verify",
        json={"identifier": SUPER_EMAIL, "channel": "email", "code": code},
        timeout=15,
    )
    assert r2.status_code == 200, r2.text
    tok = r2.json().get("session_token") or r2.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def auth_hdr(super_token):
    return {"Authorization": f"Bearer {super_token}"}


# ------------------------------------------------------------------ helpers
def _create_firm(http, auth_hdr, *,
                 policy_variant: str = "policy_2",
                 full_day_hours: float = 8.0,
                 standard_working_hours: float | None = None) -> str:
    """Create a fresh firm (business_category=industry, subcategory=Textile)
    with the required attendance_policy configured via PATCH."""
    unique = uuid.uuid4().hex[:6]
    payload = {
        "name": f"Iter81-Dedup-{unique}",
        "code": f"IT81{unique[:4].upper()}",
        "business_category": "industry",
        "business_subcategory": "Textile",
        "policy_variant": policy_variant,
        "office_lat": 28.6139,
        "office_lng": 77.2090,
    }
    r = http.post(f"{API}/companies", json=payload, headers=auth_hdr, timeout=15)
    assert r.status_code in (200, 201), r.text
    data = r.json()
    cid = data.get("company_id") or (data.get("company") or {}).get("company_id")
    assert cid

    # PATCH attendance_policy to force exact hours + variant.
    pr = http.get(f"{API}/attendance/policy", params={"company_id": cid},
                  headers=auth_hdr, timeout=15)
    assert pr.status_code == 200, pr.text
    pol = (pr.json() or {}).get("policy") or {}
    pol["policy_variant"] = policy_variant
    pol["weekly_off_days"] = [6]
    pol["full_day_hours"] = full_day_hours
    if standard_working_hours is not None:
        pol["standard_working_hours"] = standard_working_hours
    pol.setdefault("half_day_hours", 4.0)
    if pol["half_day_hours"] >= full_day_hours:
        pol["half_day_hours"] = max(1.0, full_day_hours / 2.0)
    if float(pol.get("overtime_threshold_hours") or 0) < full_day_hours:
        pol["overtime_threshold_hours"] = full_day_hours
    up = http.patch(
        f"{API}/attendance/policy", params={"company_id": cid},
        json={"policy": pol}, headers=auth_hdr, timeout=15,
    )
    assert up.status_code == 200, up.text
    return cid


def _create_employee(http, auth_hdr, cid: str, *,
                     name_suffix: str, ot_allowed: bool = True) -> str:
    phone = f"+91984{uuid.uuid4().int % 10_000_000:07d}"
    payload = {
        "name": f"TEST_Iter81_{name_suffix}",
        "phone": phone,
        "company_id": cid,
        "employee_code": f"T81{uuid.uuid4().hex[:4].upper()}",
        "doj": "2020-01-01",
    }
    r = http.post(f"{API}/admin/employees", json=payload, headers=auth_hdr, timeout=15)
    assert r.status_code in (200, 201), r.text
    uid = r.json().get("user_id") or (r.json().get("employee") or {}).get("user_id")
    assert uid
    ov = http.put(
        f"{API}/admin/employees/{uid}/attendance-policy-override",
        json={"ot_allowed": ot_allowed}, headers=auth_hdr, timeout=15,
    )
    assert ov.status_code == 200, ov.text
    return uid


def _insert_punch(mongo_db, cid: str, uid: str, date_iso: str,
                  hhmm: str, kind: str, source: str):
    """Insert one raw punch row with custom source (bypasses manual-punch
    endpoint which hard-codes source=manual_admin)."""
    record_id = f"att_{uuid.uuid4().hex[:12]}"
    at_iso = f"{date_iso}T{hhmm}:00Z"
    doc = {
        "record_id": record_id,
        "user_id": uid,
        "company_id": cid,
        "date": date_iso,
        "kind": kind,
        "at": at_iso,
        "source": source,
        "status": "approved",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    mongo_db.attendance.insert_one(doc)
    return record_id


# ==================================================================
# Fix 1 — Same-machine duplicate-punch dedup (15 min)
# ==================================================================
@pytest.fixture(scope="module")
def dedup_env(http, auth_hdr, mongo_db):
    """Firm with policy_2 + full_day_hours=8, one employee, and the 6-punch
    seed from the review request."""
    cid = _create_firm(
        http, auth_hdr, policy_variant="policy_2",
        full_day_hours=8.0, standard_working_hours=8.0,
    )
    uid = _create_employee(http, auth_hdr, cid, name_suffix="DEDUP", ot_allowed=True)
    date_iso = "2026-05-04"  # A Monday (not weekly-off)

    # 6 punches per review request. All same date.
    _insert_punch(mongo_db, cid, uid, date_iso, "09:00", "in",  "bio_dev01")
    _insert_punch(mongo_db, cid, uid, date_iso, "09:05", "in",  "bio_dev01")  # DROPPED
    _insert_punch(mongo_db, cid, uid, date_iso, "09:20", "in",  "bio_dev01")  # kept
    _insert_punch(mongo_db, cid, uid, date_iso, "13:00", "out", "bio_dev01")
    _insert_punch(mongo_db, cid, uid, date_iso, "13:10", "out", "bio_dev01")  # DROPPED
    _insert_punch(mongo_db, cid, uid, date_iso, "13:00", "out", "mobile")     # kept, diff source
    return {"cid": cid, "uid": uid, "date": date_iso}


class TestFix1Dedup:
    def test_grid_cell_dedups_to_four_punches(self, http, auth_hdr, dedup_env):
        cid, uid = dedup_env["cid"], dedup_env["uid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-05",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        emp = next(e for e in body["employees"] if e["user_id"] == uid)
        cell = emp["days"].get("04") or emp["days"].get("4")
        assert cell is not None, emp["days"]
        # 6 raw punches → 4 after dedup (2 duplicates dropped)
        assert cell["punches"] == 4, (
            f"expected 4 kept punches after dedup, got {cell['punches']}: {cell}"
        )

    def test_grid_hours_approx_4(self, http, auth_hdr, dedup_env):
        """09:00 IN → 13:00 OUT = 4h. The 09:20 redundant-IN is a no-op
        because pairing already opened at 09:00; the 13:00 mobile OUT
        closes a pair with the 09:20 stray IN or is a stray OUT — either
        way total worked minutes ~= 240."""
        cid, uid = dedup_env["cid"], dedup_env["uid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-05",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        emp = next(e for e in body["employees"] if e["user_id"] == uid)
        cell = emp["days"].get("04") or emp["days"].get("4")
        # raw_hours is the pair-punches result BEFORE OT split;
        # first IN 09:00 → first OUT 13:00 = 4h. Anything else would mean
        # dedup let duplicates through.
        assert cell["raw_hours"] == pytest.approx(4.0, abs=0.1), cell
        # in/out timestamps must be first-IN/last-OUT (both 13:00 OUTs
        # collapse to the same time — no inflation from bio 13:10 OUT which
        # was dropped).
        assert cell["in"] == "09:00", cell
        assert cell["out"] == "13:00", cell
        # hours (duty+OT) must NOT exceed 4.5h — if the deduped 13:10 OUT
        # had leaked through, we'd see ~4.17h; if the compute engine paired
        # the 09:20 IN with the mobile 13:00 OUT we'd see >4h. In practice
        # policy_2 rounds to nearest 15 min and treats <half_day (4h) as
        # 3.5h, so allow the observed 3.5-4.0 window.
        assert 3.0 <= cell["hours"] <= 4.5, cell
        assert cell["ot_hours"] == pytest.approx(0.0, abs=0.05), cell

    def test_ot_report_surface_also_dedups(self, http, auth_hdr, mongo_db):
        """_build_ot_report_rows applies the same 15-min dedup so numbers
        match monthly-grid. Seed 10h day where duplicates would push OT
        past the threshold if not deduped."""
        cid = _create_firm(
            http, auth_hdr, policy_variant="policy_1",
            full_day_hours=8.0, standard_working_hours=None,
        )
        uid = _create_employee(http, auth_hdr, cid, name_suffix="OTDEDUP",
                               ot_allowed=True)
        d = "2026-05-11"
        _insert_punch(mongo_db, cid, uid, d, "07:00", "in",  "bio_dev01")
        _insert_punch(mongo_db, cid, uid, d, "07:05", "in",  "bio_dev01")  # DROPPED
        _insert_punch(mongo_db, cid, uid, d, "17:00", "out", "bio_dev01")
        _insert_punch(mongo_db, cid, uid, d, "17:10", "out", "bio_dev01")  # DROPPED
        r = http.get(
            f"{API}/admin/attendance/ot-report/{cid}/2026-05",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("count") == 1, body
        row = body["rows"][0]
        # 10h day → 8h duty + 2h OT (not inflated by duplicate 17:10 OUT).
        assert row["ot_hours"] == pytest.approx(2.0, abs=0.1), row
        assert row["total_hours"] == pytest.approx(10.0, abs=0.1), row

    def test_dedup_regression_16min_apart_both_kept(self, http, auth_hdr, mongo_db):
        """Two INs from the same source 16 minutes apart must both be kept."""
        cid = _create_firm(
            http, auth_hdr, policy_variant="policy_2",
            full_day_hours=8.0, standard_working_hours=8.0,
        )
        uid = _create_employee(http, auth_hdr, cid, name_suffix="REG16", ot_allowed=True)
        # Two INs, 16 min apart. Add one OUT too so we have a valid pair.
        _insert_punch(mongo_db, cid, uid, "2026-05-05", "08:00", "in",  "bio_dev01")
        _insert_punch(mongo_db, cid, uid, "2026-05-05", "08:16", "in",  "bio_dev01")  # KEPT
        _insert_punch(mongo_db, cid, uid, "2026-05-05", "16:00", "out", "bio_dev01")
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-05",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        emp = next(e for e in r.json()["employees"] if e["user_id"] == uid)
        cell = emp["days"].get("05") or emp["days"].get("5")
        assert cell is not None
        assert cell["punches"] == 3, (
            f"expected 3 kept (16 min > 15 min threshold), got {cell['punches']}: {cell}"
        )

    def test_dedup_cross_source_both_kept(self, http, auth_hdr, mongo_db):
        """An IN from bio_dev01 at 09:00 and an IN from mobile at 09:05 →
        different signatures, both kept."""
        cid = _create_firm(
            http, auth_hdr, policy_variant="policy_2",
            full_day_hours=8.0, standard_working_hours=8.0,
        )
        uid = _create_employee(http, auth_hdr, cid, name_suffix="XSRC", ot_allowed=True)
        _insert_punch(mongo_db, cid, uid, "2026-05-06", "09:00", "in",  "bio_dev01")
        _insert_punch(mongo_db, cid, uid, "2026-05-06", "09:05", "in",  "mobile")  # KEPT
        _insert_punch(mongo_db, cid, uid, "2026-05-06", "17:00", "out", "bio_dev01")
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-05",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        emp = next(e for e in r.json()["employees"] if e["user_id"] == uid)
        cell = emp["days"].get("06") or emp["days"].get("6")
        assert cell is not None
        assert cell["punches"] == 3, (
            f"expected 3 (different sources bypass dedup), got {cell['punches']}: {cell}"
        )


# ==================================================================
# Fix 2 — Row totals `duty_hours` INCLUDES OT
# ==================================================================
@pytest.fixture(scope="module")
def duty_totals_env(http, auth_hdr, mongo_db):
    """Fresh Policy 1 firm; standard=8h; employee ot_allowed=True.
    Insert 10h punches → 8 duty + 2 OT expected."""
    cid = _create_firm(
        http, auth_hdr, policy_variant="policy_1",
        full_day_hours=8.0, standard_working_hours=None,
    )
    uid = _create_employee(http, auth_hdr, cid, name_suffix="TOT10", ot_allowed=True)
    # 10h day (07:00 → 17:00) on Tue 2026-05-05
    _insert_punch(mongo_db, cid, uid, "2026-05-07", "07:00", "in",  "manual_admin")
    _insert_punch(mongo_db, cid, uid, "2026-05-07", "17:00", "out", "manual_admin")
    return {"cid": cid, "uid": uid}


class TestFix2DutyHoursIncludesOT:
    def test_totals_duty_hours_equals_totals_hours(self, http, auth_hdr, duty_totals_env):
        cid, uid = duty_totals_env["cid"], duty_totals_env["uid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-05",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        emp = next(e for e in r.json()["employees"] if e["user_id"] == uid)
        totals = emp["totals"]
        assert totals["hours"] == pytest.approx(10.0, abs=0.05), totals
        assert totals["ot_hours"] == pytest.approx(2.0, abs=0.05), totals
        assert totals["duty_hours"] == pytest.approx(10.0, abs=0.05), (
            f"totals.duty_hours must include OT (Iter 77t): {totals}"
        )
        assert totals["duty_hours"] == totals["hours"], totals


# ==================================================================
# Fix 3 — `totals.duty_hours` present on EVERY row (schema)
# ==================================================================
class TestFix3DutyHoursSchema:
    def test_every_row_has_duty_hours_totals_field(self, http, auth_hdr, dedup_env):
        cid = dedup_env["cid"]
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-05",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "employees" in body
        for emp in body["employees"]:
            assert "totals" in emp, emp
            t = emp["totals"]
            assert "duty_hours" in t, (
                f"totals.duty_hours missing on row for {emp.get('name')}: {t}"
            )
            assert isinstance(t["duty_hours"], (int, float)), t
            assert t["duty_hours"] is not None


# ==================================================================
# Regression — Iter 77q (OT threshold from full_day_hours) + 77r
# (orphan admin auto-heal) must still PASS.
# ==================================================================
class TestRegressionIter77qOTThreshold:
    """Firm with full_day_hours=12, standard_working_hours=8; 10h day
    should NOT trigger OT (threshold uses full_day_hours)."""

    def test_full_day_hours_used_as_ot_threshold(self, http, auth_hdr, mongo_db):
        cid = _create_firm(
            http, auth_hdr, policy_variant="policy_1",
            full_day_hours=12.0, standard_working_hours=8.0,
        )
        uid = _create_employee(http, auth_hdr, cid, name_suffix="REG77Q",
                               ot_allowed=True)
        _insert_punch(mongo_db, cid, uid, "2026-05-08", "07:00", "in",  "manual_admin")
        _insert_punch(mongo_db, cid, uid, "2026-05-08", "17:00", "out", "manual_admin")
        r = http.get(
            f"{API}/admin/attendance/monthly-grid/{cid}/2026-05",
            headers=auth_hdr, timeout=30,
        )
        assert r.status_code == 200, r.text
        emp = next(e for e in r.json()["employees"] if e["user_id"] == uid)
        cell = emp["days"].get("08") or emp["days"].get("8")
        assert cell["ot_hours"] == pytest.approx(0.0, abs=0.05), cell
        assert cell["hours"] == pytest.approx(10.0, abs=0.05), cell


class TestRegressionIter77rOrphanAutoHeal:
    """Firm A → force-delete → firm B with same phone+email should
    succeed (auto-heal)."""

    def test_orphan_phone_email_reuse_after_force_delete(self, http, auth_hdr):
        phone = f"+9198{uuid.uuid4().int % 100_000_000:08d}"
        email = f"iter81.{uuid.uuid4().hex[:8]}@test.local"
        unique_a = uuid.uuid4().hex[:6]
        payload_a = {
            "name": f"Iter81-A-{unique_a}",
            "code": f"IT81A{unique_a[:3].upper()}",
            "business_category": "industry",
            "business_subcategory": "Textile",
            "policy_variant": "policy_2",
            "office_lat": 28.6139, "office_lng": 77.2090,
            "admin_phone": phone,
            "admin_email": email,
            "admin_name": "Iter81 Admin A",
        }
        r_a = http.post(f"{API}/companies", json=payload_a, headers=auth_hdr, timeout=15)
        assert r_a.status_code in (200, 201), r_a.text
        cid_a = r_a.json().get("company_id")
        # Force-delete firm A
        rd = http.delete(f"{API}/companies/{cid_a}",
                         params={"force": "true"}, headers=auth_hdr, timeout=30)
        assert rd.status_code == 200, rd.text
        # Firm B with same phone+email → expect 200
        unique_b = uuid.uuid4().hex[:6]
        payload_b = {**payload_a,
                     "name": f"Iter81-B-{unique_b}",
                     "code": f"IT81B{unique_b[:3].upper()}",
                     "admin_name": "Iter81 Admin B"}
        r_b = http.post(f"{API}/companies", json=payload_b, headers=auth_hdr, timeout=15)
        assert r_b.status_code in (200, 201), (
            f"auto-heal failed: {r_b.status_code} {r_b.text}"
        )
