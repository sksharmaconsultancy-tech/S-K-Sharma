"""Iter 763: Refresh Master snapshot + Firm Master dummy_shift_report + inout-ot-matrix exact dummy window.

Notes on data model discovered during exploration:
- GET /api/admin/compliance-salary-runs/{run_id} returns {'run': {..., 'rows': [...]}}
- GET /api/admin/firm-master/{cmp} returns {'master': {..., 'salary_process': {...}}}
- GET /api/admin/reports/inout-ot-matrix returns {'employees': [{'days': {dd: cell}, ...}], 'dummy_mode': bool}
- June 2026 has almost no attendance rows — the exact-dummy-window verification uses July 2026
  which is the live populated month for Kankani (1921 attendance rows) while the refresh-master
  snapshot verification uses the June 2026 run per the review request.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')

BASE_URL = None
with open('/app/frontend/.env') as _fh:
    for _line in _fh:
        if _line.startswith('EXPO_PUBLIC_BACKEND_URL='):
            BASE_URL = _line.strip().split('=', 1)[1].rstrip('/')
assert BASE_URL, 'EXPO_PUBLIC_BACKEND_URL missing'

MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']

CMP = 'cmp_527fecdd7c'
RUN_ID = 'csrun_f94d21e689b2'
EMP = 'user_83f0e0c387bb'
SA_USER_ID = 'user_67791559822a'


@pytest.fixture(scope='module')
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope='module')
def token(db):
    tok = 'test763_' + secrets.token_hex(8)
    db.user_sessions.insert_one({
        'session_token': tok,
        'user_id': SA_USER_ID,
        'expires_at': datetime.now(timezone.utc) + timedelta(hours=12),
        'created_at': datetime.now(timezone.utc),
    })
    yield tok
    db.user_sessions.delete_one({'session_token': tok})


@pytest.fixture(scope='module')
def s(token):
    sess = requests.Session()
    sess.headers.update({'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    return sess


def _get_run_rows(s):
    r = s.get(f'{BASE_URL}/api/admin/compliance-salary-runs/{RUN_ID}', timeout=30)
    assert r.status_code == 200, f'GET run failed {r.status_code}: {r.text[:300]}'
    run = (r.json() or {}).get('run') or {}
    return run.get('rows') or []


def _find_row(rows, uid):
    return next((r for r in rows if r.get('user_id') == uid), None)


# --------------------------- Refresh Master Snapshot ---------------------------
def test_01_baseline_row(s):
    rows = _get_run_rows(s)
    row = _find_row(rows, EMP)
    assert row is not None
    print('BASELINE:', {k: row.get(k) for k in ('rate', 'present_days', 'basic', 'net')})


def test_02_refresh_master_pulls_new_rate_1600(s, db):
    r0 = db.users.update_one({'user_id': EMP}, {'$set': {'salary_structure_actual.0.amount': 1600.0}})
    assert r0.matched_count == 1
    r = s.post(f'{BASE_URL}/api/admin/compliance-salary-runs/{RUN_ID}/refresh-master-snapshot', timeout=60)
    assert r.status_code == 200, f'refresh {r.status_code}: {r.text[:300]}'
    row = _find_row(_get_run_rows(s), EMP)
    print('AFTER 1600:', {k: row.get(k) for k in ('rate', 'present_days', 'basic', 'net')})
    assert float(row['rate']) == 1600.0
    assert abs(float(row['basic']) - 15360.0) < 0.5
    assert abs(float(row['net']) - 24844.0) < 1.5
    assert float(row['present_days']) == 24.0, 'attendance days must be preserved'


def test_03_restore_rate_and_verify_1500(s, db):
    r0 = db.users.update_one({'user_id': EMP}, {'$set': {'salary_structure_actual.0.amount': 1500.0}})
    assert r0.matched_count == 1
    r = s.post(f'{BASE_URL}/api/admin/compliance-salary-runs/{RUN_ID}/refresh-master-snapshot', timeout=60)
    assert r.status_code == 200
    row = _find_row(_get_run_rows(s), EMP)
    print('RESTORED:', {k: row.get(k) for k in ('rate', 'present_days', 'basic', 'net')})
    assert float(row['rate']) == 1500.0
    assert abs(float(row['basic']) - 14400.0) < 0.5
    assert abs(float(row['net']) - 23292.0) < 1.5
    assert float(row['present_days']) == 24.0


# --------------------------- Firm Master toggle ---------------------------
@pytest.fixture(scope='module')
def initial_sp(s):
    r = s.get(f'{BASE_URL}/api/admin/firm-master/{CMP}', timeout=30)
    assert r.status_code == 200
    sp = ((r.json() or {}).get('master') or {}).get('salary_process') or {}
    print('INITIAL salary_process:', sp)
    return sp


def test_04_firm_master_has_dummy_shift_report_field(initial_sp):
    assert 'dummy_shift_report' in initial_sp, f'missing dummy_shift_report; got={list(initial_sp.keys())}'


def test_05_toggle_on_and_shift_options_dummy_allowed(s, initial_sp):
    merged = dict(initial_sp)
    merged.update({'offline_salary': True, 'bio_matrix_attendance': True, 'dummy_shift_report': True})
    r = s.patch(f'{BASE_URL}/api/admin/firm-master/{CMP}', json={'salary_process': merged}, timeout=30)
    assert r.status_code == 200, f'PATCH failed {r.status_code}: {r.text[:300]}'
    sp2 = ((s.get(f'{BASE_URL}/api/admin/firm-master/{CMP}').json() or {}).get('master') or {}).get('salary_process') or {}
    assert sp2.get('dummy_shift_report') is True
    assert sp2.get('offline_salary') is True
    assert sp2.get('bio_matrix_attendance') is True

    r3 = s.get(f'{BASE_URL}/api/admin/labour-reports/shift-options', params={'company_id': CMP}, timeout=30)
    assert r3.status_code == 200
    js = r3.json()
    print('shift-options:', {'dummy_allowed': js.get('dummy_allowed'), 'dummy_shifts_assigned': js.get('dummy_shifts_assigned')})
    assert js.get('dummy_allowed') is True, 'firm toggle should force dummy_allowed True'


def test_06_inout_ot_matrix_exact_dummy_window(s):
    # July 2026 has real attendance to verify present cells
    r = s.get(f'{BASE_URL}/api/admin/reports/inout-ot-matrix',
              params={'company_id': CMP, 'month': '2026-07', 'dummy': 1}, timeout=60)
    assert r.status_code == 200, f'matrix {r.status_code}: {r.text[:300]}'
    js = r.json()
    assert js.get('dummy_mode') is True
    emps = js.get('employees') or []
    assert emps, 'no employees returned'
    s2 = [e for e in emps if e.get('dummy_shift') == 'SHIFT 2']
    assert s2, 'no SHIFT 2 employees'

    present_seen = 0
    absent_seen = 0
    wo_seen = 0
    non_exact_present = []
    non_blank_absent = []

    for e in s2:
        for dnum, cell in (e.get('days') or {}).items():
            flag = cell.get('flag') or ''
            d_in = cell.get('d_in')
            d_out = cell.get('d_out')
            total = cell.get('total')
            if flag in ('weekly_off', 'holiday'):
                wo_seen += 1
                continue
            if d_in == '-' and d_out == '-':
                absent_seen += 1
                continue
            # present day cell
            if not (d_in == '07:00' and d_out == '15:00' and total in ('08:00', '8:00')):
                non_exact_present.append((e['user_id'], dnum, d_in, d_out, total))
            else:
                present_seen += 1

    print(f'present_exact={present_seen} absent_blank={absent_seen} wo/h={wo_seen} bad_present={len(non_exact_present)}')
    if non_exact_present:
        print('BAD present sample:', non_exact_present[:5])
    assert not non_exact_present, f'non-exact present cells: {non_exact_present[:5]}'
    assert present_seen >= 10, f'expected many exact present cells got {present_seen}'
    # Multiple employees should have identical times — verify by picking two
    if len(s2) >= 2:
        e1, e2 = s2[0], s2[1]
        for dnum in list((e1.get('days') or {}).keys())[:5]:
            c1 = e1['days'][dnum]; c2 = e2['days'].get(dnum, {})
            if c1.get('d_in') == '07:00' and c2.get('d_in') == '07:00':
                assert c1.get('d_out') == c2.get('d_out') == '15:00'


# --------------------------- Cleanup ---------------------------
def test_99_cleanup_firm_toggles(s, initial_sp):
    merged = dict(initial_sp)
    merged.update({'offline_salary': False, 'bio_matrix_attendance': False, 'dummy_shift_report': False})
    r = s.patch(f'{BASE_URL}/api/admin/firm-master/{CMP}', json={'salary_process': merged}, timeout=30)
    assert r.status_code == 200
    sp2 = ((s.get(f'{BASE_URL}/api/admin/firm-master/{CMP}').json() or {}).get('master') or {}).get('salary_process') or {}
    assert sp2.get('dummy_shift_report') is False
    assert sp2.get('offline_salary') is False
    assert sp2.get('bio_matrix_attendance') is False
    print('CLEANUP OK salary_process=', sp2)
