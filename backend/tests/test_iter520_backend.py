"""Iter 520 backend tests — payroll reports, attendance policy OT engine,
sync dashboard machine_only extensions, ESIC leave reason, challan
statuses, factory return FORM 23, regressions."""
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict

import pytest
import requests
from pymongo import MongoClient

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL",
                      "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
MONGO = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DBN = os.environ.get("DB_NAME", "test_database")

_mongo = MongoClient(MONGO)
mdb = _mongo[DBN]


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{API}/auth/admin-password-login", json={
        "email": "sksharmaconsultancy@gmail.com",
        "password": "sharma123"}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="session")
def H(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def cid():
    # Use existing Kankani firm from test_credentials.md
    return "cmp_527fecdd7c"


@pytest.fixture(scope="session")
def test_fixtures(cid):
    """Create isolated test company + employee + punches; cleanup after."""
    tag = f"TEST_iter520_{uuid.uuid4().hex[:6]}"
    test_cid = f"cmp_test_{uuid.uuid4().hex[:8]}"
    test_uid = f"user_test_{uuid.uuid4().hex[:8]}"
    bio = f"9{uuid.uuid4().hex[:4]}"

    mdb.companies.insert_one({
        "company_id": test_cid, "name": f"{tag} Factory",
        "active": True,
        "attendance_policy": {"full_day_hours": 8.0,
                              "weekly_off_days": [6]},
    })
    mdb.users.insert_one({
        "user_id": test_uid, "role": "employee", "company_id": test_cid,
        "employee_code": "T1", "name": f"{tag} Emp", "bio_code": bio,
        "approval_status": "approved", "is_onroll": True,
        "gender": "M", "doj": "2024-01-01",
        "test_tag": tag,
    })
    # Day 1: 2026-06-01 (Mon) 09:00-13:00 + 14:00-18:00 (worked 8h, no OT)
    # Day 2: 2026-06-02 (Tue) 09:00-13:00 + 14:00-19:00 (worked 9h, OT 1h)
    # Day 3: 2026-06-07 (Sun) NO punch (weekly off)
    _punches = [
        ("2026-06-01", "09:00:00", "in"),
        ("2026-06-01", "13:00:00", "out"),
        ("2026-06-01", "14:00:00", "in"),
        ("2026-06-01", "18:00:00", "out"),
        ("2026-06-02", "09:00:00", "in"),
        ("2026-06-02", "13:00:00", "out"),
        ("2026-06-02", "14:00:00", "in"),
        ("2026-06-02", "19:00:00", "out"),
    ]
    for d, tm, kind in _punches:
        at_iso = f"{d}T{tm}"
        mdb.attendance.insert_one({
            "attendance_id": f"att_{uuid.uuid4().hex[:10]}",
            "user_id": test_uid, "company_id": test_cid,
            "date": d, "at": at_iso, "kind": kind, "type": kind,
            "timestamp": at_iso,
            "status": "approved", "source": "test_iter520",
            "test_tag": tag,
        })
    # Sync-dashboard fixtures: unregistered device punch + machine-only user
    mdb.biometric_unmapped.insert_one({
        "device_user_id": f"UP{uuid.uuid4().hex[:4]}",
        "device_serial": f"UNREG_{uuid.uuid4().hex[:6]}",
        "at": "2026-06-15T10:00:00", "test_tag": tag,
    })
    mdb.biometric_machine_users.insert_one({
        "pin": f"MU{uuid.uuid4().hex[:4]}",
        "name": f"{tag} MachineUser",
        "device_serial": f"DEV_{uuid.uuid4().hex[:6]}",
        "company_id": test_cid, "test_tag": tag,
    })
    yield {"tag": tag, "cid": test_cid, "uid": test_uid, "bio": bio}
    # Cleanup
    for col in ("companies", "users", "attendance",
                "biometric_unmapped", "biometric_machine_users",
                "esic_leaves", "challan_summaries"):
        mdb[col].delete_many({"test_tag": tag})
    mdb.companies.delete_many({"company_id": test_cid})
    mdb.users.delete_many({"company_id": test_cid})
    mdb.attendance.delete_many({"company_id": test_cid})


# ---- Regression ----------------------------------------------------------
def test_version():
    r = requests.get(f"{API}/version", timeout=15)
    assert r.status_code == 200
    assert r.json().get("iteration") == "520"


def test_punch_logs_regression(H):
    r = requests.get(f"{API}/admin/punch-logs?from_date=&to_date=",
                     headers=H, timeout=30)
    assert r.status_code == 200, r.text


# ---- 1. last-finalized-month --------------------------------------------
def test_last_finalized_month(H, cid):
    r = requests.get(
        f"{API}/admin/payroll-reports/last-finalized-month?company_id={cid}",
        headers=H, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "month" in j and "finalized" in j
    assert isinstance(j["finalized"], bool)
    assert len(j["month"]) == 7 and j["month"][4] == "-"


# ---- 2. Salary Comparison periodic --------------------------------------
def test_salary_comparison_periodic(H, cid):
    q = (f"?company_id={cid}&month=2026-05&month_b=2026-01"
         "&month_to=2026-06&month_b_to=2026-02")
    r = requests.get(f"{API}/admin/payroll-reports/salary-comparison{q}",
                     headers=H, timeout=45)
    assert r.status_code == 200, r.text
    j = r.json()
    # subtitle exactly '2026-01→2026-02 vs 2026-05→2026-06'
    assert j.get("subtitle") == "2026-01→2026-02 vs 2026-05→2026-06", j.get("subtitle")
    labels = [c["label"] for c in j.get("columns") or []]
    assert any("2026-01→2026-02" in lb for lb in labels), labels
    assert any("2026-05→2026-06" in lb for lb in labels), labels

    for ext in ("xlsx", "pdf"):
        r2 = requests.get(
            f"{API}/admin/payroll-reports/salary-comparison.{ext}{q}",
            headers=H, timeout=60)
        assert r2.status_code == 200, f"{ext}: {r2.status_code} {r2.text[:200]}"
        assert len(r2.content) > 100


# ---- 3. Salary Revision dynamic allowance columns -----------------------
def test_salary_revision_dynamic_cols(H, cid):
    r = requests.get(
        f"{API}/admin/payroll-reports/salary-revision?company_id={cid}"
        f"&fy_start_year=2026&month=2026-05",
        headers=H, timeout=45)
    assert r.status_code == 200, r.text
    j = r.json()
    labels = [c["label"] for c in j.get("columns") or []]
    # base columns must exist
    assert "Old Gross" in labels and "New Gross" in labels
    # if firm_masters has allowances, Old/New pairs appear
    fm = mdb.firm_masters.find_one({"company_id": cid}, {"allowances": 1})
    heads = [k for k, v in ((fm or {}).get("allowances") or {}).items()
             if v and str(k).upper().replace(" ", "") not in
             ("OVERTIME", "OVER-TIME")]
    for h in heads:
        assert f"{h} Old" in labels, f"missing '{h} Old' in {labels}"
        assert f"{h} New" in labels, f"missing '{h} New' in {labels}"


# ---- 4. In/Out & OT Matrix policy block ---------------------------------
def test_inout_ot_matrix_policy(H, cid):
    r = requests.get(
        f"{API}/admin/reports/inout-ot-matrix?company_id={cid}&month=2026-06",
        headers=H, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    line = ((j.get("policy") or {}).get("line") or "")
    assert line.startswith("Firm Attendance Policy"), f"policy line: {line!r}"

    for ext in ("xlsx", "pdf"):
        r2 = requests.get(
            f"{API}/admin/reports/inout-ot-matrix.{ext}?company_id={cid}"
            f"&month=2026-06", headers=H, timeout=90)
        # If no employees match filters, endpoint returns 404 — accept it
        assert r2.status_code in (200, 404), r2.status_code
        if r2.status_code == 200:
            assert len(r2.content) > 100


# ---- 5. Attendance engine — OT only after full-day worked hours ---------
def test_attendance_policy_ot_engine(H, test_fixtures):
    tcid = test_fixtures["cid"]
    r = requests.get(
        f"{API}/admin/attendance/monthly-grid/{tcid}/2026-06",
        headers=H, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    emps = j.get("employees") or []
    ours = next((e for e in emps if e.get("user_id") == test_fixtures["uid"]),
                None)
    assert ours is not None, f"test employee missing from grid; got {len(emps)} emps"
    days = ours.get("days") or {}
    # day labels — try both '01' and 1
    def _day(dl):
        for k in (dl, dl.lstrip("0"), int(dl)):
            if k in days:
                return days[k]
        # fuzzy find by prefix
        for k, v in days.items():
            if str(k).startswith(dl[:2]):
                return v
        return {}

    d1 = _day("01")
    d2 = _day("02")
    d7 = _day("07")
    assert d1, f"day 01 missing; keys={list(days)[:8]}"
    ot1 = float(d1.get("ot_hours") or 0)
    dh1 = float(d1.get("duty_hours") or 0)
    # Core assertion: no phantom OT from lunch on 8h-worked day
    assert ot1 == 0, f"Day1 OT should be 0 but got {ot1}; cell={d1}"
    assert 7.5 <= dh1 <= 8.5, f"Day1 duty_hours ~8, got {dh1}; cell={d1}"

    ot2 = float(d2.get("ot_hours") or 0)
    dh2 = float(d2.get("duty_hours") or 0)
    assert 0.5 <= ot2 <= 1.5, f"Day2 OT expected ~1h, got {ot2}; cell={d2}"
    assert 7.5 <= dh2 <= 8.5, f"Day2 duty ~8h, got {dh2}; cell={d2}"

    # Sunday (07) with no punches → weekly_off flag
    assert bool(d7.get("weekly_off")) is True, \
        f"Day07 (Sun) should be weekly_off=True; cell={d7}"


# ---- 6. Sync Dashboard machine_only extensions --------------------------
def test_sync_dashboard_machine_only(H, test_fixtures):
    tcid = test_fixtures["cid"]
    r = requests.get(
        f"{API}/admin/attendance-sync-dashboard?month=2026-06"
        f"&company_id={tcid}&preset=month", headers=H, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    mo = j.get("machine_only") or []
    # (a) row with company='⚠ Unregistered Device'
    assert any(r.get("company") == "⚠ Unregistered Device" for r in mo), \
        f"no unregistered-device row; sample: {mo[:2]}"
    # (b) row from biometric_machine_users with punch_count=0, name_in_machine
    zero = [r for r in mo if r.get("punch_count") == 0]
    assert zero, f"no zero-punch machine_only rows; sample: {mo[:3]}"
    assert any("never punched" in (r.get("remark") or "").lower()
               for r in zero), f"remark missing 'never punched'; {zero[:2]}"
    assert any(r.get("name_in_machine") for r in zero), \
        f"name_in_machine missing; {zero[:2]}"


# ---- 7. Challan summary PATCH status ------------------------------------
def test_challan_status_patch(H, cid):
    month = "2026-05"
    # Set pf_status = failed
    r = requests.patch(f"{API}/admin/challan-summary/{cid}/{month}",
                       headers=H, json={"pf_status": "failed"}, timeout=30)
    assert r.status_code == 200, r.text

    r2 = requests.get(f"{API}/admin/challan-summary?month={month}",
                      headers=H, timeout=30)
    assert r2.status_code == 200
    row = next((x for x in r2.json().get("rows", [])
                if x.get("company_id") == cid), None)
    assert row is not None
    assert row.get("pf_status") == "failed", row

    # Invalid value → 400
    r3 = requests.patch(f"{API}/admin/challan-summary/{cid}/{month}",
                        headers=H, json={"pf_status": "xyz"}, timeout=30)
    assert r3.status_code == 400, r3.status_code

    # Cleanup — restore to pending
    requests.patch(f"{API}/admin/challan-summary/{cid}/{month}",
                   headers=H, json={"pf_status": "pending"}, timeout=30)


# ---- 8. ESIC Leave reason / reason_other --------------------------------
def test_esic_leave_reason(H, cid):
    # find an active employee in the firm
    u = mdb.users.find_one({"company_id": cid, "role": "employee"},
                           {"user_id": 1})
    if not u:
        pytest.skip("no employee in firm")
    tag = f"TEST_iter520_esl_{uuid.uuid4().hex[:6]}"
    created_ids = []
    try:
        # backdated to satisfy allow_backdated default (30 days)
        today = date.today()
        f_d = today.isoformat()
        t_d = today.isoformat()
        payload = {"company_id": cid, "user_id": u["user_id"],
                   "from_date": f_d, "to_date": t_d,
                   "reason": "Maternity Benefit",
                   "remarks": tag}
        r = requests.post(f"{API}/admin/esic-leave", headers=H,
                          json=payload, timeout=30)
        assert r.status_code == 200, r.text
        eid = r.json()["entry"]["entry_id"]
        created_ids.append(eid)
        assert r.json()["entry"].get("reason") == "Maternity Benefit"

        # Other + reason_other
        payload2 = dict(payload, reason="Other (Specify)",
                        reason_other="Custom cause XYZ")
        r2 = requests.post(f"{API}/admin/esic-leave", headers=H,
                           json=payload2, timeout=30)
        assert r2.status_code == 200, r2.text
        e2 = r2.json()["entry"]
        created_ids.append(e2["entry_id"])
        assert e2.get("reason") == "Other (Specify)"
        assert e2.get("reason_other") == "Custom cause XYZ"

        # List shows reason
        r3 = requests.get(
            f"{API}/admin/esic-leave?company_id={cid}", headers=H, timeout=30)
        assert r3.status_code == 200
        entries = r3.json().get("entries") or []
        ours = [e for e in entries if e.get("entry_id") in created_ids]
        assert len(ours) == 2, ours
        assert any(e.get("reason") == "Maternity Benefit" for e in ours)
        assert any(e.get("reason_other") == "Custom cause XYZ" for e in ours)
    finally:
        for eid in created_ids:
            requests.delete(f"{API}/admin/esic-leave/{eid}",
                            headers=H, timeout=30)


# ---- 9. Factory Return FORM 23 PDF + PUT form23 -------------------------
def test_form23_pdf_and_details(H, cid):
    # PUT details with form23
    body = {"form23": {"application_no": "123", "area": "Mandal"}}
    r = requests.put(f"{API}/admin/factory-return/details/{cid}",
                     headers=H, json=body, timeout=30)
    assert r.status_code == 200, r.text

    r2 = requests.get(f"{API}/admin/factory-return/details/{cid}",
                      headers=H, timeout=30)
    assert r2.status_code == 200
    f23 = (r2.json().get("details") or {}).get("form23") or {}
    assert f23.get("application_no") == "123"
    assert f23.get("area") == "Mandal"

    # PDF
    r3 = requests.get(f"{API}/admin/factory-return/{cid}/2026/form23.pdf",
                      headers=H, timeout=90)
    assert r3.status_code == 200, r3.text[:300]
    assert "application/pdf" in r3.headers.get("content-type", "")
    assert len(r3.content) > 500
