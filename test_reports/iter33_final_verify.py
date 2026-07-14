"""Iteration 33 final verification (v2) — checkpoints 1,2,3,6,11,12 (backend)."""
import os, sys, json, uuid, time
from datetime import datetime, timezone
import requests
from pymongo import MongoClient

BASE = "https://emplo-connect-1.preview.emergentagent.com"
API = f"{BASE}/api"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

client = MongoClient(MONGO_URL)
db = client[DB_NAME]

TAG = f"iF33W{uuid.uuid4().hex[:5]}"
results = {}

def rec(name, ok, note):
    results[name] = {"pass": bool(ok), "note": note}
    print(("PASS" if ok else "FAIL"), name, "-", note)

def phone(k):
    return f"+91{8000000000 + (uuid.uuid4().int % 100000000):010d}"

# ============ Checkpoints 1,2,3 ============
try:
    email1 = f"cr_{TAG}@test.local"
    comp1 = f"IT33Fin Co {TAG}"
    pin = "112233"

    r = requests.post(f"{API}/auth/company-register", json={
        "company_name": comp1, "address": "T", "city": "Delhi", "state": "DL",
        "contact_name": "Admin One", "contact_mobile": phone(1), "contact_email": email1,
        "nature_of_business": "Consulting", "pin": pin,
    }, timeout=30)
    print("reg1:", r.status_code, r.text[:200])
    assert r.status_code in (200, 201)
    req_id = r.json().get("request_id")
    print("req1_id:", req_id)

    # CP1
    r1 = requests.post(f"{API}/auth/admin-pin-login", json={"identifier": email1, "pin": pin}, timeout=15)
    body1 = r1.text.lower()
    ck1 = r1.status_code == 403 and "awaiting approval" in body1 and comp1.lower() in body1
    rec("cp1_awaiting_approval", ck1, f"status={r1.status_code} snippet={r1.text[:180]}")

    # CP2: reject via mongo (endpoint requires super_admin auth)
    db.company_requests.update_one({"request_id": req_id}, {"$set": {
        "status": "rejected", "admin_note": "Not eligible IT33FIN",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }})
    r2 = requests.post(f"{API}/auth/admin-pin-login", json={"identifier": email1, "pin": pin}, timeout=15)
    body2 = r2.text.lower()
    ck2 = r2.status_code == 403 and "rejected" in body2 and "not eligible it33fin" in body2
    rec("cp2_rejected_note", ck2, f"status={r2.status_code} snippet={r2.text[:220]}")

    # CP3: fresh company_request → approve → login
    email3 = f"cr3_{TAG}@test.local"
    comp3 = f"IT33FinX Co {TAG}"
    ph3 = phone(3)
    r4 = requests.post(f"{API}/auth/company-register", json={
        "company_name": comp3, "address": "T", "city": "Delhi", "state": "DL",
        "contact_name": "Admin Three", "contact_mobile": ph3, "contact_email": email3,
        "nature_of_business": "Consulting", "pin": pin,
    }, timeout=30)
    doc3 = r4.json()
    req_id3 = doc3.get("request_id")
    # Seed super_admin session
    sa = db.users.find_one({"email": "sksharmaconsultancy@gmail.com"})
    sa_tok = f"tk_{TAG}_sa_{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": sa_tok, "user_id": sa["user_id"],
        "expires_at": "2099-12-31T00:00:00+00:00",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "auth_method": "test",
    })
    hdrs = {"Authorization": f"Bearer {sa_tok}"}
    r5 = requests.patch(f"{API}/company-requests/{req_id3}", json={"status": "approved"}, headers=hdrs, timeout=30)
    print("approve:", r5.status_code, r5.text[:220])
    time.sleep(1)
    r6 = requests.post(f"{API}/auth/admin-pin-login", json={"identifier": email3, "pin": pin}, timeout=15)
    try:
        j6 = r6.json()
    except Exception:
        j6 = {}
    ck3 = r6.status_code == 200 and j6.get("session_token") and (j6.get("user", {}) or {}).get("role") == "company_admin"
    rec("cp3_post_approval_login", ck3, f"status={r6.status_code} role={(j6.get('user',{})or{}).get('role')} tok?{bool(j6.get('session_token'))}")

except Exception as e:
    rec("cp1_2_3_exception", False, f"{type(e).__name__}: {e}")

# ============ Checkpoint 6 — present-not-punched + approve-punch source=admin_approved ============
try:
    co_id = f"co_{TAG}_p6_{uuid.uuid4().hex[:5]}"
    db.companies.insert_one({
        "company_id": co_id, "name": f"IT33 P6 {TAG}",
        "address": "T", "city": "Delhi", "state": "DL",
        "office_lat": 28.6139, "office_lng": 77.209,
        "geofence_radius_m": 200, "company_code": "P6XX",
        "compliance_enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    ca_id = f"user_{TAG}_p6ca_{uuid.uuid4().hex[:5]}"
    db.users.insert_one({
        "user_id": ca_id, "email": f"p6ca_{TAG}@test.local",
        "name": "P6 CA", "role": "company_admin", "company_id": co_id,
        "onboarded": True, "approval_status": "approved", "pin_must_change": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    ca_tok = f"tk_{TAG}_p6ca_{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": ca_tok, "user_id": ca_id,
        "expires_at": "2099-12-31T00:00:00+00:00",
        "created_at": datetime.now(timezone.utc).isoformat(), "auth_method": "test",
    })
    emp_id = f"user_{TAG}_p6e_{uuid.uuid4().hex[:5]}"
    db.users.insert_one({
        "user_id": emp_id, "email": f"p6e_{TAG}@test.local",
        "name": "P6 Emp", "role": "employee", "company_id": co_id,
        "employee_code": "P6XX0001",
        "onboarded": True, "approval_status": "approved", "pin_must_change": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    emp_tok = f"tk_{TAG}_p6e_{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": emp_tok, "user_id": emp_id,
        "expires_at": "2099-12-31T00:00:00+00:00",
        "created_at": datetime.now(timezone.utc).isoformat(), "auth_method": "test",
    })
    ehdr = {"Authorization": f"Bearer {emp_tok}"}
    cahdr = {"Authorization": f"Bearer {ca_tok}"}

    rp = requests.post(f"{API}/me/location-ping", json={"latitude": 28.6139, "longitude": 77.209}, headers=ehdr, timeout=15)
    print("location-ping:", rp.status_code, rp.text[:200])

    rr = requests.get(f"{API}/admin/attendance/present-not-punched", headers=cahdr, timeout=15)
    print("present-not-punched:", rr.status_code, rr.text[:400])
    arr = rr.json().get("not_punched_in", []) if rr.status_code == 200 else []
    ok_list = any((x.get("user_id") == emp_id) for x in arr)
    rec("cp6_present_not_punched_list", ok_list, f"status={rr.status_code} count={len(arr)}")

    ra = requests.post(f"{API}/admin/attendance/approve-punch",
                       json={"user_id": emp_id, "kind": "in"},
                       headers=cahdr, timeout=15)
    print("approve-punch:", ra.status_code, ra.text[:200])
    src_ok = False
    if ra.status_code == 200:
        today = datetime.now(timezone.utc).date().isoformat()
        att = db.attendance.find_one({"user_id": emp_id, "date": today, "kind": "in"})
        src_ok = bool(att) and att.get("source") == "admin_approved"
    rec("cp6_approve_punch_source_admin_approved", src_ok, f"status={ra.status_code}")
except Exception as e:
    rec("cp6_exception", False, f"{type(e).__name__}: {e}")

# ============ Checkpoint 11 — Tier bonus payroll (Nov 2025) ============
try:
    co11 = f"co_{TAG}_p11_{uuid.uuid4().hex[:5]}"
    db.companies.insert_one({
        "company_id": co11, "name": f"IT33 P11 {TAG}",
        "address": "T", "city": "Delhi", "state": "DL",
        "office_lat": 28.6139, "office_lng": 77.209,
        "geofence_radius_m": 200, "company_code": "P1XX",
        "compliance_enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    ca11 = f"user_{TAG}_p11ca_{uuid.uuid4().hex[:5]}"
    db.users.insert_one({
        "user_id": ca11, "email": f"p11ca_{TAG}@test.local",
        "name": "P11 CA", "role": "company_admin", "company_id": co11,
        "onboarded": True, "approval_status": "approved", "pin_must_change": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    ca11_tok = f"tk_{TAG}_p11ca_{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": ca11_tok, "user_id": ca11,
        "expires_at": "2099-12-31T00:00:00+00:00",
        "created_at": datetime.now(timezone.utc).isoformat(), "auth_method": "test",
    })
    e11 = f"user_{TAG}_p11e_{uuid.uuid4().hex[:5]}"
    db.users.insert_one({
        "user_id": e11, "email": f"p11e_{TAG}@test.local",
        "name": "P11 Emp", "role": "employee", "company_id": co11,
        "employee_code": "P1XX0001",
        "join_date": "2025-11-01",
        "employee_policy": {"salary": 30000, "salary_1": 2000, "day_1": 20, "policy_confirmed": True},
        "salary_monthly": 30000,
        "onboarded": True, "approval_status": "approved", "pin_must_change": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    sundays = {2, 9, 16, 23, 30}
    days = [d for d in range(1, 31) if d not in sundays][:22]
    for d in days:
        db.attendance.insert_one({
            "record_id": f"att_{TAG}_p11_{d}_{uuid.uuid4().hex[:6]}",
            "user_id": e11, "date": f"2025-11-{d:02d}",
            "kind": "in", "at": f"2025-11-{d:02d}T09:00:00+00:00",
            "source": "manual",
        })
    ch = {"Authorization": f"Bearer {ca11_tok}"}
    pr = requests.get(f"{API}/admin/payroll/run", params={"year": 2025, "month": 11}, headers=ch, timeout=30)
    ok11 = False; me = None
    if pr.status_code == 200:
        rows = (pr.json().get("rows") or [])
        me = next((r for r in rows if r.get("user_id") == e11), None)
        if me:
            bg = me.get("base_gross"); tb = me.get("tier_bonus"); gr = me.get("gross")
            ok11 = abs((bg or 0) - 26400) < 1 and abs((tb or 0) - 2000) < 1 and abs((gr or 0) - 28400) < 1
    rec("cp11_tier_bonus_payroll", ok11,
        f"status={pr.status_code} base={me and me.get('base_gross')} tier={me and me.get('tier_bonus')} gross={me and me.get('gross')}")
except Exception as e:
    rec("cp11_exception", False, f"{type(e).__name__}: {e}")

# ============ Checkpoint 12 — Email report ============
try:
    ch = {"Authorization": f"Bearer {ca11_tok}"}
    r12 = requests.post(f"{API}/admin/payroll/email-report",
                        json={"year": 2025, "month": 11, "report_kind": "combined", "recipients": "self"},
                        headers=ch, timeout=45)
    print("email-report main:", r12.status_code, r12.text[:400])
    ok_send = r12.status_code == 200 and "sends" in r12.text
    rec("cp12_email_report_no_500", ok_send, f"main={r12.status_code}")

    # Empty scope: use user_ids=[bogus] to force empty
    r12b = requests.post(f"{API}/admin/payroll/email-report",
                         json={"year": 2025, "month": 11, "report_kind": "combined",
                               "recipients": "employees", "user_ids": ["user_bogus_none"]},
                         headers=ch, timeout=30)
    print("email empty scope:", r12b.status_code, r12b.text[:300])
    ok_empty = r12b.status_code == 400 and "No employees" in r12b.text
    rec("cp12_email_empty_scope_400", ok_empty, f"status={r12b.status_code}")
except Exception as e:
    rec("cp12_exception", False, f"{type(e).__name__}: {e}")

# ============ Cleanup ============
try:
    # Delete extra approved company/user created via approval flow
    for eml in [f"cr_{TAG}@test.local", f"cr3_{TAG}@test.local"]:
        u = db.users.find_one({"email": eml})
        if u:
            db.user_sessions.delete_many({"user_id": u.get("user_id")})
            db.users.delete_one({"user_id": u.get("user_id")})
            if u.get("company_id"):
                db.companies.delete_one({"company_id": u.get("company_id")})
    n_att = db.attendance.delete_many({"record_id": {"$regex": f"^att_{TAG}_"}}).deleted_count
    n_ses = db.user_sessions.delete_many({"session_token": {"$regex": f"^tk_{TAG}_"}}).deleted_count
    n_usr = db.users.delete_many({"user_id": {"$regex": f"^user_{TAG}_"}}).deleted_count
    n_co = db.companies.delete_many({"company_id": {"$regex": f"^co_{TAG}_"}}).deleted_count
    n_cr = db.company_requests.delete_many({"contact_email": {"$regex": f"^cr[3]?_{TAG}@"}}).deleted_count
    print("cleanup:", {"attendance": n_att, "sessions": n_ses, "users": n_usr, "companies": n_co, "company_requests": n_cr})
except Exception as e:
    print("cleanup exception:", e)

sa = db.users.find_one({"email": "sksharmaconsultancy@gmail.com"})
print("super_admin final:", {k: sa.get(k) for k in ("role", "pin_must_change", "pin_fail_count", "pin_locked_until")} if sa else None)

print("\n=== SUMMARY ===")
print(json.dumps(results, indent=2))
with open("/app/test_reports/iter33_final_backend_results.json", "w") as f:
    json.dump(results, f, indent=2)
