"""Iter 175 backend regression — contractor employees, contractual gate,
contractor-punch report + decide, policy_master sanitisation."""
import os
from datetime import datetime, timezone
import pytest
import requests

BASE = os.environ.get('EXPO_PUBLIC_BACKEND_URL', 'https://emplo-connect-1.preview.emergentagent.com').rstrip('/')
CID = 'cmp_527fecdd7c'
UID = 'user_44cd6f561da0'  # SURENDRA SINGH


@pytest.fixture(scope='session')
def tok():
    r = requests.post(f"{BASE}/api/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()['session_token']


@pytest.fixture(scope='session')
def H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# --- 1) Firm-master contractors persist -------------------------------------
def test_firm_contractors_present(H):
    r = requests.get(f"{BASE}/api/admin/firm-master/{CID}", headers=H, timeout=15)
    assert r.status_code == 200
    m = r.json()['master']
    names = [c.get('name') for c in (m.get('contractors') or [])]
    assert 'RAM PRASAD' in names and 'GOPAL SINGH' in names
    assert (m.get('settings') or {}).get('contractor_employees') is True
    # Kankani must keep offline_salary+bio_matrix OFF (unlock hint state).
    sp = m.get('salary_process') or {}
    assert sp.get('offline_salary') is False
    assert sp.get('bio_matrix_attendance') is False


# --- 2) user-role toggling is_contractual + contractor_name -----------------
def test_user_role_contractual_flow(H):
    # Set false first (clears contractor_name)
    r = requests.patch(f"{BASE}/api/admin/user-role",
                       headers=H, json={"user_id": UID, "is_contractual": False}, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{BASE}/api/admin/employees?company_id={CID}", headers=H, timeout=15)
    emp = next(e for e in r.json()['employees'] if e['user_id'] == UID)
    assert emp.get('is_contractual') in (False, None)
    assert not emp.get('contractor_name')
    # Restore: is_contractual true with RAM PRASAD
    r = requests.patch(f"{BASE}/api/admin/user-role", headers=H,
                       json={"user_id": UID, "is_contractual": True,
                             "contractor_name": "RAM PRASAD"}, timeout=15)
    assert r.status_code == 200
    r = requests.get(f"{BASE}/api/admin/employees?company_id={CID}", headers=H, timeout=15)
    emp = next(e for e in r.json()['employees'] if e['user_id'] == UID)
    assert emp.get('is_contractual') is True
    assert emp.get('contractor_name') == 'RAM PRASAD'


# --- 3) Policy master sanitisation ------------------------------------------
def test_policy_master_sanitisation(H):
    r = requests.patch(f"{BASE}/api/attendance/policy?company_id={CID}",
                       headers=H, json={"policy_master": {
                           "attendance_basis": "daily",
                           "shift_type": "rotational",
                           "punch_types": ["biometric", "gps", "junk"],
                           "contractor_assignment_required": True,
                           "attendance_basis_bad": True,
                       }}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    pm = (body.get('policy') or body).get('policy_master') or body.get('policy_master')
    assert pm is not None, body
    assert pm['attendance_basis'] == 'daily'
    assert pm['shift_type'] == 'rotational'
    assert 'biometric' in pm['punch_types'] and 'gps' in pm['punch_types']
    assert 'junk' not in pm['punch_types']
    assert pm.get('contractor_assignment_required') is True
    # Defaults exist for other flags
    assert 'multiple_punch_allowed' in pm
    assert 'geofencing_required' in pm

    # Bad basis + shift → falls back to defaults
    r2 = requests.patch(f"{BASE}/api/attendance/policy?company_id={CID}",
                        headers=H, json={"policy_master": {
                            "attendance_basis": "bogus",
                            "shift_type": "bogus",
                            "punch_types": [],
                        }}, timeout=15)
    assert r2.status_code == 200
    pm2 = ((r2.json().get('policy') or {}).get('policy_master')) or r2.json().get('policy_master')
    assert pm2['attendance_basis'] not in ('bogus',)
    assert pm2['shift_type'] not in ('bogus',)


# --- 4) Contractor punch report + decide (creates pending punch via gate) ---
@pytest.fixture()
def dated():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def test_contractor_punch_report_and_decide(H, dated):
    # Insert pending contractual punches directly (simulates ZKTeco gate result).
    from pymongo import MongoClient
    import uuid as _uuid
    mc = MongoClient('mongodb://localhost:27017').test_database
    created = []
    for kind, hh in (("in", "09:00:00"), ("out", "18:00:00")):
        rid = f"att_TEST175_{_uuid.uuid4().hex[:8]}"
        mc.attendance.insert_one({
            "record_id": rid, "user_id": UID, "company_id": CID,
            "date": dated, "kind": kind, "at": f"{dated}T{hh}Z",
            "source": "system:zkteco", "status": "pending",
            "contractor_name": "RAM PRASAD",
            "pending_reason": "contractual_employee",
        })
        created.append(rid)

    # Fetch report — expect pending row for our user
    r = requests.get(f"{BASE}/api/admin/contractor-punches?company_id={CID}&date={dated}",
                     headers=H, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['date'] == dated
    row = None
    for g in body['groups']:
        for x in g['rows']:
            if x['user_id'] == UID:
                row = x; row['_contractor'] = g['contractor']
    assert row is not None, f"no row for UID; body={body}"
    assert row['status'] == 'pending'

    # Change contractor for that individual day to GOPAL SINGH
    r = requests.post(f"{BASE}/api/admin/contractor-punches/decide", headers=H,
                      json={"company_id": CID, "user_id": UID, "date": dated,
                            "contractor_name": "GOPAL SINGH"}, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{BASE}/api/admin/contractor-punches?company_id={CID}&date={dated}",
                     headers=H, timeout=15)
    body2 = r.json()
    found_gopal = False
    for g in body2['groups']:
        if g['contractor'] == 'GOPAL SINGH':
            for x in g['rows']:
                if x['user_id'] == UID:
                    found_gopal = True
    assert found_gopal

    # Approve
    r = requests.post(f"{BASE}/api/admin/contractor-punches/decide", headers=H,
                      json={"company_id": CID, "user_id": UID, "date": dated,
                            "action": "approve"}, timeout=15)
    assert r.status_code == 200

    # Cleanup — delete the two records via direct admin delete endpoint if any,
    # else via /api/admin/attendance?record_id=…
    for rid in created:
        if not rid:
            continue
        mc.attendance.delete_one({"record_id": rid})
