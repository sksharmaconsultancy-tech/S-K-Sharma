"""Iter 765 setup + tests helpers.

- creates test creds for user_83f0e0c387bb via /api/admin/employee-credentials
- sets email in Mongo
- enables offline_salary on Kankani firm (patch full firm object)
- has a cleanup() that restores everything
- has a get_token() helper for super admin sessions

Run: python3 /app/test_reports/helpers/iter765_setup.py <setup|cleanup>
"""
import os, sys, json, requests, datetime
sys.path.insert(0, os.path.dirname(__file__))
from login_super_admin import login  # noqa: E402
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')
BASE = os.environ.get('EXPO_PUBLIC_BACKEND_URL', 'https://emplo-connect-1.preview.emergentagent.com').rstrip('/')
MONGO = os.environ['MONGO_URL']
DB = os.environ.get('DB_NAME', 'test_database')

USER_ID = "user_83f0e0c387bb"
FIRM_ID = "cmp_527fecdd7c"
TEST_EMAIL = "mahaveer.test@example.com"
TEST_LOGIN = "mahaveer.test"
TEST_PIN = "246810"
TEST_PASS = "TestPass@765"


def _client():
    return MongoClient(MONGO)[DB]


def setup():
    token = login()
    print(f"[setup] super token: {token[:20]}...")
    h = {"Authorization": f"Bearer {token}"}

    # 1) create credentials
    r = requests.post(f"{BASE}/api/admin/employee-credentials",
                      headers=h,
                      json={
                        "user_id": USER_ID,
                        "login_id": TEST_LOGIN,
                        "pin": TEST_PIN,
                        "password": TEST_PASS,
                        "must_change": False,
                      }, timeout=30)
    print(f"[setup] employee-credentials => {r.status_code} {r.text[:180]}")

    # 2) set email in Mongo
    db = _client()
    db.users.update_one({"user_id": USER_ID}, {"$set": {"email": TEST_EMAIL}})
    u = db.users.find_one({"user_id": USER_ID}, {"login_id": 1, "email": 1, "has_pin": 1, "password_hash": 1})
    print(f"[setup] user snapshot: {u}")

    # 3) enable offline_salary — first fetch full firm obj, then PATCH merged salary_process
    fr = requests.get(f"{BASE}/api/admin/firm-master/{FIRM_ID}", headers=h, timeout=30)
    fm = fr.json()
    sp = dict(fm.get("salary_process") or {})
    prev_sp = dict(sp)
    sp.update({"offline_salary": True})
    r2 = requests.patch(f"{BASE}/api/admin/firm-master/{FIRM_ID}", headers=h,
                        json={"salary_process": sp}, timeout=30)
    print(f"[setup] firm-master patch => {r2.status_code} sp={sp}")

    # store prev_sp for cleanup
    with open("/tmp/iter765_prev_sp.json", "w") as f:
        json.dump(prev_sp, f)
    print(f"[setup] prev_sp saved: {prev_sp}")
    return token


def cleanup():
    token = login()
    h = {"Authorization": f"Bearer {token}"}
    db = _client()

    # 1) unset creds on user
    db.users.update_one({"user_id": USER_ID}, {
        "$unset": {"login_id": "", "pin_hash": "", "has_pin": "",
                   "password_hash": "", "password_must_change": "",
                   "must_change_password": "", "email": "",
                   "attendance_policy_override": ""}
    })
    print(f"[cleanup] user unset done")

    # 2) delete user_sessions for that user
    n = db.user_sessions.delete_many({"user_id": USER_ID}).deleted_count
    print(f"[cleanup] deleted {n} sessions")

    # 3) restore firm salary_process
    try:
        with open("/tmp/iter765_prev_sp.json", "r") as f:
            prev_sp = json.load(f)
    except Exception:
        prev_sp = {}
    # per review request: attendance_source=null, offline_salary=false, bio_matrix=false, dummy_shift=false
    restore_sp = dict(prev_sp)
    restore_sp["offline_salary"] = False
    restore_sp["bio_matrix_attendance"] = False
    restore_sp["dummy_shift_report"] = False
    restore_sp["attendance_source"] = None
    r = requests.patch(f"{BASE}/api/admin/firm-master/{FIRM_ID}", headers=h,
                       json={"salary_process": restore_sp}, timeout=30)
    print(f"[cleanup] firm patched => {r.status_code}")

    # 4) delete test accidents + linked ESIC leaves + leaves
    accs = list(db.accidents.find({"user_id": USER_ID, "accident_date": "2026-06-10"}))
    print(f"[cleanup] found {len(accs)} test accidents")
    for a in accs:
        aid = a.get("accident_id") or a.get("_id")
        # esic_leaves linked to this accident
        e_del = db.esic_leaves.delete_many({"accident_id": aid}).deleted_count
        # leaves linked
        l_del = db.leaves.delete_many({"$or": [
            {"linked_accident_id": aid},
            {"source_accident_id": aid},
            {"accident_id": aid},
        ]}).deleted_count
        # actual accident
        db.accidents.delete_one({"_id": a["_id"]})
        print(f"[cleanup]   accident {aid}: esic={e_del} leaves={l_del}")

    # 5) delete any attendance records created for user today (auto-punch on login)
    today = datetime.date.today().isoformat()
    a_del = db.attendance.delete_many({"user_id": USER_ID, "date": today}).deleted_count
    print(f"[cleanup] deleted {a_del} today attendance rows")

    # 6) verify final
    u = db.users.find_one({"user_id": USER_ID}, {"login_id": 1, "email": 1, "has_pin": 1, "password_hash": 1, "attendance_policy_override": 1})
    print(f"[cleanup] final user: {u}")
    fm = requests.get(f"{BASE}/api/admin/firm-master/{FIRM_ID}", headers=h, timeout=30).json()
    print(f"[cleanup] final firm sp: {fm.get('salary_process')}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        cleanup()
    else:
        setup()
