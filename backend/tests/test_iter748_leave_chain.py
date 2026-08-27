"""Iter 748 — E2E: Leave approvals via Org Reporting Chain.

Flow: workflow saved with reporting_chain levels → employee's leave →
approver auto-resolved from employee's reporting chain → sequential
approve → leave finalized. Skip-note when chain role missing. Cleanup.
"""
import asyncio
import hashlib
import os
import sys
import uuid
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
B = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
FAIL = []


def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, extra)
    if not cond:
        FAIL.append(name)


r = requests.post(f"{B}/auth/admin-password-login",
                  json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"})
j = r.json()
if j.get("twofa_required"):
    db.twofa_pending.update_one({"pending_id": j["pending_token"]},
                                {"$set": {"otp_hash": hashlib.sha256(b"123456").hexdigest()}})
    j = requests.post(f"{B}/auth/2fa/verify",
                      json={"pending_token": j["pending_token"], "otp": "123456"}).json()
H = {"Authorization": f"Bearer {j['session_token']}"}

emp = db.users.find_one({"company_id": CID, "role": "employee", "active": {"$ne": False}})
mgr = db.users.find_one({"company_id": CID, "role": "employee",
                         "user_id": {"$ne": emp["user_id"]}})
hrm = db.users.find_one({"company_id": CID, "role": "employee",
                         "user_id": {"$nin": [emp["user_id"], mgr["user_id"]]}})

# 1. save workflow with chain levels
r = requests.post(f"{B}/admin/approval-workflows", headers=H, json={
    "company_id": CID, "module": "leave", "enabled": True,
    "levels": [{"approver_type": "reporting_chain", "chain_role": "primary_manager"},
               {"approver_type": "reporting_chain", "chain_role": "hr_manager"}]})
check("workflow saved", r.status_code == 200, r.text[:150])
wf = db.approval_workflows.find_one({"company_id": CID, "module": "leave"})
check("chain levels stored", wf and wf["levels"][0].get("chain_role") == "primary_manager"
      and "chain" in (wf["levels"][0].get("role_name") or ""))
# bad chain_role rejected
r = requests.post(f"{B}/admin/approval-workflows", headers=H, json={
    "company_id": CID, "module": "leave", "enabled": True,
    "levels": [{"approver_type": "reporting_chain", "chain_role": "boss"}]})
check("bad chain_role 400", r.status_code == 400)

# 2. set employee chain: primary_manager only (hr_manager missing → skip note)
r = requests.post(f"{B}/org/reporting/{emp['user_id']}", headers=H,
                  json={"company_id": CID, "primary_manager": mgr["user_id"]})
check("chain set", r.status_code == 200)
db.org_defaults.delete_many({"company_id": CID})

# 3. employee creates leave → simulate via direct engine call (employee
#    session banana OTP-bound hai; create_leave path uses same engine)
lid = f"lv_test_{uuid.uuid4().hex[:8]}"
db.leaves.insert_one({"leave_id": lid, "user_id": emp["user_id"], "company_id": CID,
                      "user_name": emp.get("name"), "leave_type": "casual",
                      "from_date": "2026-08-10", "to_date": "2026-08-11",
                      "status": "pending", "workflow_routed": True})


async def make_request():
    import server  # noqa: F401
    from routes.approvals_engine import create_approval_request, get_active_workflow
    wf2 = await get_active_workflow(CID, "leave")
    return await create_approval_request(
        company_id=CID, module="leave", record_id=lid,
        title="TEST leave chain", summary={"days": 2, "leave_type": "casual"},
        requested_by={"user_id": emp["user_id"], "name": emp.get("name")},
        workflow=wf2)

sys.path.insert(0, "/app/backend")
req = asyncio.get_event_loop().run_until_complete(make_request())
lv1 = req["levels"][0]
check("L1 resolved to manager", lv1.get("user_id") == mgr["user_id"]
      and lv1.get("approver_type") == "reporting_chain",
      f"L1={lv1.get('role_name')}")
check("HR level skipped (not set)", len(req["levels"]) == 1
      and any("chain me ye role set nahi" in (h.get("remarks") or "")
              for h in req["history"]))

# manager can action own level, random employee cannot
from routes.approvals_engine import _user_can_action_level  # noqa: E402
check("manager can action", _user_can_action_level(
    {"role": "employee", "user_id": mgr["user_id"]}, lv1))
check("other emp cannot", not _user_can_action_level(
    {"role": "employee", "user_id": hrm["user_id"]}, lv1))

# 4. with org_defaults hr_manager set → 2 levels; approve both → leave approved
db.approval_requests.delete_one({"request_id": req["request_id"]})
requests.post(f"{B}/org/defaults", headers=H,
              json={"company_id": CID, "hr_manager": hrm["user_id"]})
req = asyncio.get_event_loop().run_until_complete(make_request())
check("2 levels resolved", len(req["levels"]) == 2
      and req["levels"][1].get("user_id") == hrm["user_id"],
      f"L2={req['levels'][1].get('role_name') if len(req['levels']) > 1 else None}")
rid = req["request_id"]
r = requests.post(f"{B}/admin/approval-requests/{rid}/action", headers=H,
                  json={"action": "approve", "remarks": "ok L1", "company_id": CID})
check("L1 approve", r.status_code == 200, r.text[:120])
cur = db.approval_requests.find_one({"request_id": rid})
check("moved to L2", cur["status"] == "pending" and cur["current_level"] == 2)
r = requests.post(f"{B}/admin/approval-requests/{rid}/action", headers=H,
                  json={"action": "approve", "remarks": "ok L2", "company_id": CID})
check("L2 approve", r.status_code == 200)
cur = db.approval_requests.find_one({"request_id": rid})
lv = db.leaves.find_one({"leave_id": lid})
check("request approved", cur["status"] == "approved")
check("leave finalized approved", lv and lv["status"] == "approved",
      f"leave status={lv and lv.get('status')}")

# CLEANUP
db.approval_requests.delete_many({"record_id": lid})
db.leaves.delete_one({"leave_id": lid})
db.approval_workflows.delete_many({"company_id": CID, "module": "leave"})
db.org_defaults.delete_many({"company_id": CID})
db.users.update_one({"user_id": emp["user_id"]}, {"$unset": {"reporting_chain": 1}})
print("cleaned up")
print("RESULT:", "ALL PASS" if not FAIL else f"FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
