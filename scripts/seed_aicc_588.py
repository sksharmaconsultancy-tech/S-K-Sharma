"""Iter 588 — seed sub_admin + test employee + salary edit approval for AICC tests."""
import os, sys, uuid, time, hashlib, requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')
db = MongoClient(os.environ['MONGO_URL'])[os.environ.get('DB_NAME', 'test_database')]

CID = 'cmp_527fecdd7c'
SUB_ID = f'user_aicc588_sub_{uuid.uuid4().hex[:6]}'
EMP_ID = f'user_aicc588_emp_{uuid.uuid4().hex[:6]}'
SUB_TOKEN = f'aicc588subtok_{uuid.uuid4().hex[:10]}'

now = int(time.time())

# create sub_admin
db.users.insert_one({
    'user_id': SUB_ID,
    'email': f'aicc588sub_{uuid.uuid4().hex[:4]}@test.local',
    'name': 'AICC588 SubAdmin',
    'role': 'sub_admin',
    'sub_admin_company_scope': 'restricted',
    'sub_admin_company_ids': [CID],
    'sub_admin_permissions': ['employees:view','employees:edit','salary_process:view','salary_process:edit'],
    'menu_rights': {},
    'created_at': now,
})

# session
db.user_sessions.insert_one({
    'session_token': SUB_TOKEN,
    'user_id': SUB_ID,
    'role': 'sub_admin',
    'created_at': now,
    'expires_at': now + 3600 * 12,
})

# create test employee
db.users.insert_one({
    'user_id': EMP_ID,
    'employee_code': f'AICCT{uuid.uuid4().hex[:4].upper()}',
    'name': 'AICC588 Test Employee',
    'role': 'employee',
    'company_id': CID,
    'salary_monthly': 10000,
    'created_at': now,
})

print(f'SUB_ID={SUB_ID}')
print(f'EMP_ID={EMP_ID}')
print(f'SUB_TOKEN={SUB_TOKEN}')

# Now call salary PATCH as sub_admin
BASE = os.environ.get('BACKEND_URL', 'http://localhost:8001')
r = requests.patch(
    f'{BASE}/api/admin/employees/{EMP_ID}/salary',
    json={'salary_monthly': 13000},
    headers={'Authorization': f'Bearer {SUB_TOKEN}', 'Content-Type': 'application/json'},
    timeout=30,
)
print(f'PATCH status: {r.status_code}')
print(f'PATCH body: {r.text[:500]}')
try:
    body = r.json()
    approval_id = body.get('approval_id')
    print(f'APPROVAL_ID={approval_id}')
except Exception as e:
    print(f'json err: {e}')

# save to a file for cleanup
with open('/tmp/aicc588_seed.txt', 'w') as f:
    f.write(f'{SUB_ID}\n{EMP_ID}\n{SUB_TOKEN}\n')
    try:
        f.write(f'{approval_id}\n')
    except Exception:
        pass
