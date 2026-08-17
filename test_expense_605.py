"""Iter 605 — end-to-end backend test for the Expense Claims module
(Phases 2-4 APIs): employee dashboard/claims/edit/cancel/submit-dup,
admin approvals chain (manager→accounts→finance), payment (payroll mode),
reports, categories admin, payroll feed."""
import base64
import sys
import requests

BASE = "http://localhost:8001/api"
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        fail += 1
        print(f"  ❌ {name} {extra}")


def login_employee():
    r = requests.post(f"{BASE}/auth/pin-login",
                      json={"login_id": "TEST50", "pin": "123456"})
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


def login_admin():
    r = requests.post(f"{BASE}/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com",
                            "password": "sharma123"})
    assert r.status_code == 200, r.text
    j = r.json()
    if j.get("twofa_required"):
        # local test: recover the OTP by brute-forcing the sha256 hash
        import hashlib
        from pymongo import MongoClient
        row = MongoClient("mongodb://localhost:27017")["test_database"] \
            .twofa_pending.find_one({"pending_id": j["pending_token"]})
        target = row["otp_hash"]
        code = next(f"{i:06d}" for i in range(1000000)
                    if hashlib.sha256(f"{i:06d}".encode()).hexdigest() == target)
        r = requests.post(f"{BASE}/auth/2fa/verify",
                          json={"pending_token": j["pending_token"], "otp": code})
        assert r.status_code == 200, r.text
        j = r.json()
    return j.get("session_token") or j.get("token")


def H(t):
    return {"Authorization": f"Bearer {t}"}


emp = login_employee()
adm = login_admin()
print("Logins OK")

import time
RUN = str(int(time.time()))

# company of employee
me = requests.get(f"{BASE}/auth/me", headers=H(emp)).json()
cid = (me.get("user") or me).get("company_id")
print("employee company:", cid)

# 1. categories
r = requests.get(f"{BASE}/expense/categories", headers=H(emp))
check("categories list", r.status_code == 200 and len(r.json()["categories"]) > 20)
cat = r.json()["categories"][0]

# 2. create draft claim
body = {"expense_date": "2026-06-10", "category_id": cat["category_id"],
        "category_name": f"{cat['group']} · {cat['name']}", "vendor": "Test Hotel",
        "invoice_no": "INV-605", "amount": 1234.5, "gst_amount": 61.7,
        "payment_mode": "Cash", "description": "iter605 test claim",
        "client_txn_id": f"t605_{RUN}_1"}
r = requests.post(f"{BASE}/expense/claims", headers=H(emp), json=body)
check("create claim", r.status_code == 200, r.text[:200])
claim = r.json()["claim"]
cid1 = claim["claim_id"]

# idempotency
r = requests.post(f"{BASE}/expense/claims", headers=H(emp), json=body)
check("client_txn_id dedupe", r.json().get("deduped") is True)

# 3. GET single claim
r = requests.get(f"{BASE}/expense/claims/{cid1}", headers=H(emp))
check("get claim", r.status_code == 200 and r.json()["claim"]["vendor"] == "Test Hotel")

# 4. edit draft (PUT)
r = requests.put(f"{BASE}/expense/claims/{cid1}", headers=H(emp),
                 json={"vendor": "Edited Hotel", "amount": 1500})
check("edit draft", r.status_code == 200)
r = requests.get(f"{BASE}/expense/claims/{cid1}", headers=H(emp))
check("edit persisted", r.json()["claim"]["vendor"] == "Edited Hotel"
      and r.json()["claim"]["amount"] == 1500)

# 5. attachment (tiny png)
png = base64.b64encode(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")).decode()
r = requests.post(f"{BASE}/expense/claims/{cid1}/attachments", headers=H(emp),
                  json={"file_name": "r.png", "mime": "image/png", "data_b64": png})
check("attachment upload", r.status_code == 200)
doc_id = r.json()["doc_id"]
r = requests.get(f"{BASE}/expense/claims/{cid1}/attachments/{doc_id}", headers=H(emp))
check("attachment download", r.status_code == 200 and r.headers["content-type"].startswith("image/png"))

# 6. submit
r = requests.post(f"{BASE}/expense/claims/{cid1}/submit", headers=H(emp), json={})
check("submit", r.status_code == 200 and r.json()["status"] == "pending_manager")

# 7. duplicate detection — second claim same date+amount
body2 = dict(body, client_txn_id=f"t605_{RUN}_2", invoice_no="INV-606", amount=1500)
r = requests.post(f"{BASE}/expense/claims", headers=H(emp), json=body2)
cid2 = r.json()["claim"]["claim_id"]
r = requests.post(f"{BASE}/expense/claims/{cid2}/submit", headers=H(emp), json={})
check("duplicate 409", r.status_code == 409, r.text[:150])
r = requests.post(f"{BASE}/expense/claims/{cid2}/submit", headers=H(emp),
                  json={"confirm_duplicate": True})
check("duplicate confirmed submit", r.status_code == 200)

# 8. cancel the duplicate (pending_manager cancellable)
r = requests.post(f"{BASE}/expense/claims/{cid2}/cancel", headers=H(emp))
check("cancel pending claim", r.status_code == 200)

# 9. employee dashboard
r = requests.get(f"{BASE}/expense/dashboard", headers=H(emp))
check("dashboard", r.status_code == 200 and r.json()["total_claims"] >= 2)

# 10. approver queue (super admin, company scoped)
r = requests.get(f"{BASE}/expense/claims?scope=approvals&status=pending_manager&company_id={cid}",
                 headers=H(adm))
check("approvals queue", r.status_code == 200 and
      any(c["claim_id"] == cid1 for c in r.json()["claims"]), r.text[:200])

# 11. approval chain
for stage in ("pending_manager", "pending_accounts", "pending_finance"):
    r = requests.post(f"{BASE}/expense/claims/{cid1}/action", headers=H(adm),
                      json={"action": "approve", "remarks": f"ok at {stage}",
                            "approved_amount": 1450})
    check(f"approve at {stage}", r.status_code == 200, r.text[:150])
r = requests.get(f"{BASE}/expense/claims/{cid1}", headers=H(emp))
j = r.json()["claim"]
check("final approved", j["status"] == "approved" and j["approved_amount"] == 1450)

# 12. self-approval blocked — employee tries to act
r = requests.post(f"{BASE}/expense/claims/{cid1}/action", headers=H(emp),
                  json={"action": "approve"})
check("employee cannot approve", r.status_code in (403, 400))

# 13. payment via payroll
r = requests.post(f"{BASE}/expense/claims/{cid1}/payment", headers=H(adm),
                  json={"payment_mode": "payroll", "paid_amount": 1450,
                        "payment_date": "2026-06-15", "payment_reference": "PAYRUN"})
check("payment payroll", r.status_code == 200 and r.json()["status"] == "paid")

# 14. payroll feed
r = requests.get(f"{BASE}/expense/payroll-reimbursements?month=2026-06&company_id={cid}",
                 headers=H(adm))
check("payroll feed", r.status_code == 200 and
      any(p["amount"] == 1450 for p in r.json()["per_employee"]), r.text[:200])

# 15. reports
r = requests.get(f"{BASE}/expense/reports?month=2026-06&company_id={cid}", headers=H(adm))
j = r.json()
check("reports", r.status_code == 200 and j["total_claims"] >= 1
      and len(j["by_category"]) >= 1 and len(j["by_employee"]) >= 1, str(j)[:200])

# 16. categories admin — add + deactivate
r = requests.post(f"{BASE}/expense/categories", headers=H(adm),
                  json={"name": "Iter605 Test Cat", "group": "Other", "company_id": cid})
check("add category", r.status_code == 200)
new_cat = r.json()["category_id"]
r = requests.post(f"{BASE}/expense/categories", headers=H(adm),
                  json={"category_id": new_cat, "company_id": cid, "active": False})
check("deactivate category", r.status_code == 200)
r = requests.get(f"{BASE}/expense/categories?include_inactive=1&company_id={cid}", headers=H(adm))
check("include_inactive shows it",
      any(c["category_id"] == new_cat and not c["active"] for c in r.json()["categories"]))

# 17. audit trail
r = requests.get(f"{BASE}/expense/claims/{cid1}/audit", headers=H(emp))
check("audit trail", r.status_code == 200 and len(r.json()["audit"]) >= 4)

print(f"\nRESULT: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
