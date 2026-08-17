"""Iter 590 tests — AI direct navigation + permission gate."""
import sys, uuid, datetime as dtm
import requests
from pymongo import MongoClient

BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
SA = {"Authorization": "Bearer smoketok_581_cdba55cd"}
db = MongoClient("mongodb://localhost:27017")["test_database"]
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(("PASS" if cond else "FAIL") + f": {name} {'' if cond else extra}")


def cmd(headers, text):
    return requests.post(f"{BASE}/admin/ai-assistant/command", headers=headers,
                         json={"text": text, "company_id": CID}, timeout=120).json()


def mk_sub(perms):
    uid = f"user_t590_{uuid.uuid4().hex[:6]}"
    db.users.insert_one({"user_id": uid, "role": "sub_admin", "name": f"T590 {uid[-4:]}",
                         "email": f"{uid}@t.co", "active": True,
                         "sub_admin_company_scope": "restricted",
                         "sub_admin_company_ids": [CID],
                         "sub_admin_permissions": perms,
                         "created_at": dtm.datetime.utcnow().isoformat()})
    tok = f"t590_{uuid.uuid4().hex[:8]}"
    db.user_sessions.insert_one({"session_token": tok, "user_id": uid,
                                 "created_at": dtm.datetime.utcnow().isoformat(),
                                 "expires_at": "2027-01-01T00:00:00+00:00"})
    return uid, {"Authorization": f"Bearer {tok}"}


# 1. direct navigation (English + Hinglish) → auto, no button-only
j = cmd(SA, "Open Employee Master")
check("'Open Employee Master' → auto navigate /admin",
      (j.get("action") or {}).get("auto") is True
      and (j["action"]["route"].startswith("/admin")), str(j)[:200])
j = cmd(SA, "employee master kholo")
check("Hinglish 'employee master kholo' → auto navigate",
      (j.get("action") or {}).get("auto") is True, str(j)[:200])

# 2. PF report navigation
j = cmd(SA, "PF report kholo")
check("'PF report kholo' → /pf-reports auto",
      (j.get("action") or {}).get("auto") is True
      and "/pf-reports" in (j.get("action") or {}).get("route", ""), str(j)[:200])

# 3. firm + month context
j = cmd(SA, "Open July attendance for Kankani Enterprises")
a = j.get("action") or {}
check("firm+month navigation carries context",
      a.get("auto") and a.get("company_id") == CID
      and "month=2026-07" in a.get("route", "") and "company_id=" in a.get("route", ""),
      str(j)[:250])

# 4. ambiguous 'open salary' → clarification, no navigation
j = cmd(SA, "open salary")
check("ambiguous 'open salary' asks which page (no action)",
      j.get("action") is None and "salary" in (j.get("reply") or "").lower(), str(j)[:200])

# 5. sub-admin WITHOUT punch_approvals:view → denied
uid1, H1 = mk_sub(["employees:view"])
j = cmd(H1, "open attendance report")
check("sub-admin w/o permission → denied, no navigation",
      j.get("action") is None and "permission" in (j.get("reply") or "").lower(), str(j)[:200])
# but employees screen allowed
j = cmd(H1, "open employee master")
check("same sub-admin CAN open Employee Master",
      (j.get("action") or {}).get("auto") is True, str(j)[:200])

# 6. sub-admin (non-super) → Firm Master denied
j = cmd(H1, "open firm master")
check("Firm Master denied for sub-admin",
      j.get("action") is None and "permission" in (j.get("reply") or "").lower(), str(j)[:200])

# 7. sensitive action still requires confirm (NOT auto)
j = cmd(SA, "set salary of code 50 to 15000")
a = j.get("action") or {}
check("sensitive salary change still confirm_api (not auto)",
      a.get("type") == "confirm_api" and not a.get("auto"), str(j)[:250])

# 8. safe report download still auto (regression)
j = cmd(SA, "download bank sheet for July")
a = j.get("action") or {}
check("report download still auto", a.get("type") == "download" and a.get("auto") is True,
      str(j)[:200])

# cleanup
db.users.delete_one({"user_id": uid1})
db.user_sessions.delete_many({"user_id": uid1})
db.activity_log.delete_many({"user_id": uid1})
db.ai_chat_history.delete_many({"user_id": uid1})

print(f"\n=== {ok} passed, {fail} failed ===")
sys.exit(1 if fail else 0)
