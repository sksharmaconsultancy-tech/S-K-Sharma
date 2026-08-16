"""Iter 583 — tests: policy versioning + explicit reprocess + configurable
duplicate-punch window."""
import datetime as dtm
import sys
import uuid

import requests
from pymongo import MongoClient

BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
AH = {"Authorization": "Bearer smoketok_581_cdba55cd"}
db = MongoClient("mongodb://localhost:27017")["test_database"]
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"PASS: {name}")
    else:
        fail += 1
        print(f"FAIL: {name} {extra}")


# ── 1. Policy versioning: GET has version; PATCH bumps it
r = requests.get(f"{BASE}/attendance/policy?company_id={CID}", headers=AH)
pol = r.json()["policy"]
v0 = int(pol.get("policy_version") or 1)
check("GET policy has policy_version + dedup backfill",
      "policy_version" in pol and "dedup_window_minutes" in pol, str(list(pol.keys()))[:150])
pol["dedup_window_minutes"] = 10
r = requests.patch(f"{BASE}/attendance/policy?company_id={CID}", json={"policy": pol}, headers=AH)
p2 = r.json()["policy"]
check("PATCH bumps version", int(p2.get("policy_version") or 0) == v0 + 1,
      f"v0={v0} new={p2.get('policy_version')}")
check("dedup_window_minutes saved = 10", p2.get("dedup_window_minutes") == 10,
      str(p2.get("dedup_window_minutes")))
ver = int(p2["policy_version"])

# ── 2. Punch stamped with policy_version + duplicate window via zk-push
uid = "user_44cd6f561da0"
db.attendance.delete_many({"user_id": uid})
db.users.update_one({"user_id": uid},
                    {"$set": {"doj": (dtm.date.today() - dtm.timedelta(days=2)).strftime("%d-%m-%Y")},
                     "$unset": {"aadhar_number": "", "aadhaar_no": "", "bank_account_number": "",
                                "bank_account": "", "ifsc_code": "", "bank_ifsc": "",
                                "pan_number": "", "pan_no": ""}})
# gate window anchored recently → HELD
db.companies.update_one({"company_id": CID},
                        {"$set": {"attendance_policy.onboarding_gate.enabled": True,
                                  "attendance_policy.onboarding_gate.enabled_at": dtm.datetime.utcnow().isoformat(),
                                  "attendance_policy.zk_secret": "testsecret583"}})
bio = db.users.find_one({"user_id": uid}, {"bio_code": 1}) or {}
if not bio.get("bio_code"):
    db.users.update_one({"user_id": uid}, {"$set": {"bio_code": "9950"}})
bc = (bio.get("bio_code") or "9950")
now = dtm.datetime.now().replace(microsecond=0)
body = {"company_id": CID, "device_secret": "testsecret583",
        "punches": [{"bio_code": str(bc), "at": now.isoformat(), "kind": "in"}]}
r = requests.post(f"{BASE}/biometric/zk-push", json=body)
check("zk push accepted", r.status_code == 200 and r.json().get("accepted") == 1, r.text[:200])
rec = db.attendance.find_one({"user_id": uid}, sort=[("created_at", -1)])
check("punch HELD + policy_version stamped",
      rec and rec.get("status") == "held" and rec.get("policy_version") == ver,
      str({k: rec.get(k) for k in ("status", "policy_version")} if rec else None))

# duplicate within 10-min window
body["punches"] = [{"bio_code": str(bc), "at": (now + dtm.timedelta(minutes=4)).isoformat(), "kind": "out"}]
r = requests.post(f"{BASE}/biometric/zk-push", json=body)
dup = db.attendance.find_one({"user_id": uid, "status": "duplicate"})
check("2nd punch within window marked duplicate", bool(dup),
      str([x.get("status") for x in db.attendance.find({"user_id": uid})]))
# punch outside window → not duplicate (held again)
body["punches"] = [{"bio_code": str(bc), "at": (now + dtm.timedelta(minutes=25)).isoformat(), "kind": "out"}]
r = requests.post(f"{BASE}/biometric/zk-push", json=body)
n_held = db.attendance.count_documents({"user_id": uid, "status": "held"})
check("punch outside window stored held (not duplicate)", n_held == 2, f"held={n_held}")

# ── 3. Create a BLOCKED punch (backdate anchor), then reprocess
db.companies.update_one({"company_id": CID},
                        {"$set": {"attendance_policy.onboarding_gate.enabled_at": "2020-01-01T00:00:00"}})
db.users.update_one({"user_id": uid}, {"$set": {"doj": "01-01-2020"}})
body["punches"] = [{"bio_code": str(bc), "at": (now + dtm.timedelta(hours=3)).isoformat(), "kind": "out"}]
r = requests.post(f"{BASE}/biometric/zk-push", json=body)
blk = db.attendance.find_one({"user_id": uid, "status": "blocked"})
check("blocked punch created", bool(blk))

# Reprocess with data still missing → blocked stays blocked, held → blocked (window over)
r = requests.post(f"{BASE}/admin/attendance-eligibility/reprocess?company_id={CID}",
                  json={}, headers=AH)
j = r.json()
check("reprocess (data missing) ok", r.status_code == 200 and j.get("total", 0) >= 3, r.text[:200])
check("held moved to blocked after window expiry", j.get("blocked", 0) >= 1, str(j))

# Complete the data → reprocess without reason must FAIL (blocked would release)
db.users.update_one({"user_id": uid}, {"$set": {
    "aadhar_number": "234123412346", "bank_account_number": "12345678901",
    "ifsc_code": "SBIN0001234", "pan_number": "ABCDE1234F"}})
r = requests.post(f"{BASE}/admin/attendance-eligibility/reprocess?company_id={CID}",
                  json={}, headers=AH)
check("reprocess releasing blocked w/o reason → 400", r.status_code == 400,
      f"{r.status_code} {r.text[:150]}")
r = requests.post(f"{BASE}/admin/attendance-eligibility/reprocess?company_id={CID}",
                  json={"reason": "Docs verified during audit"}, headers=AH)
j = r.json()
check("reprocess with reason releases all", r.status_code == 200 and j.get("released", 0) >= 3, r.text[:200])
rel = db.attendance.find_one({"user_id": uid, "eligibility_status": "RELEASED"})
check("released record has version + reason",
      rel and rel.get("policy_version") == ver and rel.get("release_reason"),
      str({k: (rel or {}).get(k) for k in ("policy_version", "release_reason")}))
log = db.eligibility_release_log.find_one({"action": "reprocess", "company_id": CID}, sort=[("at", -1)])
check("reprocess audit log written", bool(log) and log.get("policy_version") == ver, str(log)[:150])

# cleanup
db.attendance.delete_many({"user_id": uid})
db.users.update_one({"user_id": uid}, {"$set": {"doj": "01-12-2018"},
                    "$unset": {"aadhar_number": "", "bank_account_number": "",
                               "ifsc_code": "", "pan_number": ""}})
db.companies.update_one({"company_id": CID},
                        {"$set": {"attendance_policy.onboarding_gate.enabled_at": dtm.datetime.utcnow().isoformat()},
                         "$unset": {"attendance_policy.zk_secret": ""}})

print(f"\n=== {ok} passed, {fail} failed ===")
sys.exit(1 if fail else 0)
