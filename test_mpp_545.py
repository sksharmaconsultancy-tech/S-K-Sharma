"""Iter 545 — spec test suite for Multiple Punch & Maximum Punch policy.

Runs Tests A–H from the user spec against the real API + report endpoints,
using a TEMPORARY firm + employee (cleaned up afterwards).
"""
import requests, sys, uuid, pymongo
from datetime import datetime, timedelta, timezone

BASE = "http://localhost:8001/api"
db = pymongo.MongoClient("mongodb://localhost:27017")["test_database"]

CID = "cmp_test_mpp545"
UID = "user_test_mpp545"
ADMIN_UID = "user_test_mpp545_admin"
TOK = f"tok_mpp_{uuid.uuid4().hex[:8]}"
ATOK = f"tok_mppa_{uuid.uuid4().hex[:8]}"

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail and not cond else ""))

def cleanup():
    db.companies.delete_many({"company_id": CID})
    db.users.delete_many({"company_id": CID})
    db.user_sessions.delete_many({"session_token": {"$in": [TOK, ATOK]}})
    db.attendance.delete_many({"company_id": CID})
    db.punch_exceptions.delete_many({"company_id": CID})

def setup(policy_master):
    cleanup()
    db.companies.insert_one({
        "company_id": CID, "name": "MPP Test Firm", "company_code": "MPP",
        "auto_approve_mobile_punches": True,
        "attendance_policy": {"full_day_hours": 8.0, "policy_master": policy_master},
    })
    db.users.insert_one({
        "user_id": UID, "company_id": CID, "role": "employee",
        "name": "Test Emp", "employee_code": "T1", "is_live_in": True,
        "onboarding_status": "approved",
    })
    db.users.insert_one({
        "user_id": ADMIN_UID, "company_id": CID, "role": "company_admin",
        "name": "Test Admin",
    })
    exp = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    db.user_sessions.insert_many([
        {"session_token": TOK, "user_id": UID, "expires_at": exp},
        {"session_token": ATOK, "user_id": ADMIN_UID, "expires_at": exp},
    ])

H = {"Authorization": f"Bearer {TOK}"}
AH = {"Authorization": f"Bearer {ATOK}"}

def punch(kind):
    r = requests.post(f"{BASE}/attendance/punch", headers=H,
                      json={"kind": kind, "source": "manual",
                            "biometric_method": "face"})
    return r.status_code, (r.json().get("detail") if r.status_code != 200 else r.json())

def clear_punches():
    db.attendance.delete_many({"company_id": CID})
    db.punch_exceptions.delete_many({"company_id": CID})

# ================= Test A: multiple=YES max=4, IN OUT IN OUT valid =========
print("\n== Test A: multiple=YES, max=4 → IN OUT IN OUT all accepted ==")
setup({"multiple_punch_allowed": True, "maximum_punches_per_day": 4,
       "extra_punch_action": "reject", "invalid_sequence_action": "reject"})
codes = [punch(k)[0] for k in ("in", "out", "in", "out")]
check("A: 4 punches accepted", codes == [200, 200, 200, 200], str(codes))

# ================= Test B: 5th punch rejected ==============================
print("\n== Test B: 5th punch rejected with limit message ==")
c, d = punch("in")
check("B: 5th punch HTTP 400", c == 400, f"{c} {d}")
check("B: message mentions maximum 4", "maximum 4" in str(d), str(d))
exc = list(db.punch_exceptions.find({"company_id": CID}))
check("B: exception logged (max_punch_limit)",
      len(exc) == 1 and exc[0]["exception_type"] == "max_punch_limit"
      and exc[0]["max_punches_allowed"] == 4 and exc[0]["existing_punch_count"] == 4,
      str([(e['exception_type'], e.get('max_punches_allowed')) for e in exc]))

# ================= Test C+D: multiple=NO ===================================
print("\n== Test C/D: multiple=NO → IN OUT ok, 3rd punch rejected ==")
setup({"multiple_punch_allowed": False, "maximum_punches_per_day": 4,
       "extra_punch_action": "reject", "invalid_sequence_action": "reject"})
codes = [punch(k)[0] for k in ("in", "out")]
check("C: IN OUT accepted", codes == [200, 200], str(codes))
c, d = punch("in")
check("D: 3rd punch rejected", c == 400, f"{c} {d}")
check("D: message says multiple not allowed", "Multiple punches are not allowed" in str(d), str(d))
exc = list(db.punch_exceptions.find({"company_id": CID}))
check("D: exception multiple_punch_not_allowed",
      len(exc) == 1 and exc[0]["exception_type"] == "multiple_punch_not_allowed", str(exc[:1]))

# ================= Test E: IN → IN invalid ================================
print("\n== Test E: duplicate IN rejected ==")
setup({"multiple_punch_allowed": True, "maximum_punches_per_day": 6,
       "extra_punch_action": "reject", "invalid_sequence_action": "reject"})
punch("in")
c, d = punch("in")
check("E: second IN HTTP 400", c == 400, f"{c} {d}")
check("E: invalid sequence message", "Invalid punch sequence" in str(d), str(d))
exc = list(db.punch_exceptions.find({"company_id": CID}))
check("E: exception duplicate_in", any(e["exception_type"] == "duplicate_in" for e in exc), str(exc))

# ================= Test F: OUT first invalid ==============================
print("\n== Test F: OUT without IN rejected ==")
clear_punches()
c, d = punch("out")
check("F: OUT first HTTP 400", c == 400, f"{c} {d}")
exc = list(db.punch_exceptions.find({"company_id": CID}))
check("F: exception missing_in", any(e["exception_type"] == "missing_in" for e in exc), str(exc))

# ============ extra_punch_action = exception → punch stored ===============
print("\n== Extra: extra_punch_action=exception stores attempt as EXCEPTION punch ==")
setup({"multiple_punch_allowed": True, "maximum_punches_per_day": 2,
       "extra_punch_action": "exception", "invalid_sequence_action": "reject"})
punch("in"); punch("out")
c, d = punch("in")
check("X: 3rd punch still 400", c == 400, f"{c} {d}")
stored = list(db.attendance.find({"company_id": CID, "status": "exception"}))
check("X: attempt stored with status=exception",
      len(stored) == 1 and stored[0].get("exception_type") == "max_punch_limit", str(len(stored)))

# ================= Tests G & H: duty/break/OT math (report) ================
print("\n== Test G: 9-13 + 14-18 → Duty 8:00, Break 1:00, OT 0:00 ==")
setup({"multiple_punch_allowed": True, "maximum_punches_per_day": 6,
       "extra_punch_action": "reject", "invalid_sequence_action": "reject"})
D = "2026-06-15"
def seed(times_kinds):
    for t, k in times_kinds:
        db.attendance.insert_one({
            "record_id": f"att_{uuid.uuid4().hex[:12]}", "user_id": UID,
            "company_id": CID, "date": D, "kind": k, "at": f"{D}T{t}:00",
            "source": "manual_admin", "status": "approved",
        })
seed([("09:00", "in"), ("13:00", "out"), ("14:00", "in"), ("18:00", "out")])
r = requests.get(f"{BASE}/admin/multi-punch/report",
                 headers=AH, params={"company_id": CID, "month": "2026-06"})
rows = r.json().get("rows", [])
row = rows[0] if rows else {}
check("G: report row returned", len(rows) == 1, f"{r.status_code} {len(rows)}")
check("G: duty 08:00", row.get("duty_hhmm") == "08:00", str(row.get("duty_hhmm")))
check("G: break 01:00", row.get("break_hhmm") == "01:00", str(row.get("break_hhmm")))
check("G: OT 00:00", row.get("ot_hhmm") == "00:00", str(row.get("ot_hhmm")))
check("G: punches 4/6", row.get("punch_count") == 4 and row.get("max_allowed") == 6,
      f"{row.get('punch_count')}/{row.get('max_allowed')}")

print("\n== Test H: + 19-21 pair (6 punches, max 6) → Duty 8:00, OT 2:00 ==")
seed([("19:00", "in"), ("21:00", "out")])
r = requests.get(f"{BASE}/admin/multi-punch/report",
                 headers=AH, params={"company_id": CID, "month": "2026-06"})
row = (r.json().get("rows") or [{}])[0]
check("H: duty 08:00", row.get("duty_hhmm") == "08:00", str(row.get("duty_hhmm")))
check("H: OT 02:00", row.get("ot_hhmm") == "02:00", str(row.get("ot_hhmm")))
check("H: limit_reached pill (6/6)", row.get("limit_reached") is True and row.get("punch_count") == 6,
      f"{row.get('punch_count')}/{row.get('max_allowed')}")

# ================= Exceptions endpoint =====================================
print("\n== Exceptions endpoint ==")
db.punch_exceptions.insert_one({
    "exception_id": "pex_test1", "company_id": CID, "user_id": UID,
    "employee_code": "T1", "name": "Test Emp", "date": D, "at": f"{D}T19:30:00",
    "kind": "in", "exception_type": "max_punch_limit", "reason": "test",
    "max_punches_allowed": 6, "existing_punch_count": 6, "source": "manual",
    "created_at": "2026-06-15T19:30:00Z",
})
r = requests.get(f"{BASE}/admin/multi-punch/exceptions",
                 headers=AH, params={"company_id": CID, "month": "2026-06"})
check("Exceptions listed", r.status_code == 200 and r.json().get("total") == 1,
      f"{r.status_code} {r.json().get('total')}")

# ============ Legacy firm (no max saved) → unlimited =======================
print("\n== Legacy: firm without maximum_punches_per_day → unlimited ==")
setup({"multiple_punch_allowed": True})  # legacy policy_master, no new fields
codes = [punch(k)[0] for k in ("in", "out", "in", "out", "in", "out")]
check("Legacy: 6 punches all accepted (no limit)", codes == [200] * 6, str(codes))

cleanup()
print(f"\n{'='*50}\nPASSED {len(PASS)}  FAILED {len(FAIL)}")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL SPEC TESTS PASSED ✅")
