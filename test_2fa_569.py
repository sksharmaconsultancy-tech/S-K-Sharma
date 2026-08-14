"""Iter 569 — 2FA flow test. Uses direct-DB otp_hash swap to a known code
(OTP is hashed at rest; this simulates reading the email)."""
import requests, hashlib, os, sys
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
B = "http://localhost:8001/api"
mongo = MongoClient(os.environ["MONGO_URL"])
db = mongo[os.environ.get("DB_NAME", "test_database")]

P = F = 0
def check(name, ok, extra=""):
    global P, F
    P += ok; F += (not ok)
    print(f"{'✅' if ok else '❌'} {name} {extra}")

def hsh(c): return hashlib.sha256(c.encode()).hexdigest()

# 1) Super admin login → must return twofa_required, NOT session_token
r = requests.post(f"{B}/auth/admin-password-login",
                  json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"})
d = r.json()
check("login returns 200", r.status_code == 200, str(r.status_code))
check("twofa_required=True", d.get("twofa_required") is True)
check("NO session_token in response", "session_token" not in d)
check("pending_token present", bool(d.get("pending_token")))
check("masked email", "*" in (d.get("masked_email") or ""), d.get("masked_email"))
check("method defaults email", d.get("method") == "email")
check("no OTP leaked in response", not any("otp" == k.lower() or (isinstance(v, str) and len(v) == 6 and v.isdigit()) for k, v in d.items()), str(list(d.keys())))
pt = d["pending_token"]

# pending doc must store a HASH, not the code
row = db.twofa_pending.find_one({"pending_id": pt})
check("pending stored", bool(row))
check("otp stored hashed (64 hex)", len(row.get("otp_hash") or "") == 64)

# 2) wrong OTP x2 → attempts increment
r2 = requests.post(f"{B}/auth/2fa/verify", json={"pending_token": pt, "otp": "000000"})
check("wrong OTP rejected 401", r2.status_code == 401, r2.json().get("detail", ""))
r2b = requests.post(f"{B}/auth/2fa/verify", json={"pending_token": pt, "otp": "111111"})
row = db.twofa_pending.find_one({"pending_id": pt})
check("attempts == 2", row.get("attempts") == 2, str(row.get("attempts")))

# 3) resend cooldown (just created → 429)
r3 = requests.post(f"{B}/auth/2fa/resend", json={"pending_token": pt})
check("resend within cooldown → 429", r3.status_code == 429, r3.json().get("detail", ""))

# 4) hash-swap to known code and verify
db.twofa_pending.update_one({"pending_id": pt}, {"$set": {"otp_hash": hsh("123456")}})
r4 = requests.post(f"{B}/auth/2fa/verify", json={"pending_token": pt, "otp": "123456"})
d4 = r4.json()
check("correct OTP → 200", r4.status_code == 200, str(r4.status_code))
check("session_token issued", bool(d4.get("session_token")))
tok = d4.get("session_token")
H = {"Authorization": f"Bearer {tok}"}
me = requests.get(f"{B}/auth/2fa/my-security", headers=H)
check("session works (my-security 200)", me.status_code == 200)
check("one-time: pending deleted", db.twofa_pending.find_one({"pending_id": pt}) is None)
r5 = requests.post(f"{B}/auth/2fa/verify", json={"pending_token": pt, "otp": "123456"})
check("replay blocked (401)", r5.status_code == 401)

# 5) max attempts → blocked
r6 = requests.post(f"{B}/auth/admin-password-login",
                   json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"})
pt2 = r6.json()["pending_token"]
last = None
for i in range(5):
    last = requests.post(f"{B}/auth/2fa/verify", json={"pending_token": pt2, "otp": "999999"})
check("5th wrong attempt → 429 blocked", last.status_code == 429, last.json().get("detail", ""))
db.twofa_pending.update_one({"pending_id": pt2}, {"$set": {"otp_hash": hsh("123456")}})
r7 = requests.post(f"{B}/auth/2fa/verify", json={"pending_token": pt2, "otp": "123456"})
check("blocked pending rejects even correct OTP", r7.status_code == 429, str(r7.status_code))
db.twofa_pending.delete_one({"pending_id": pt2})

# 6) security settings GET/PUT (super admin)
r8 = requests.get(f"{B}/admin/security-settings/2fa", headers=H)
d8 = r8.json()
check("settings GET 200", r8.status_code == 200)
check("email_configured true", d8.get("email_configured") is True)
check("defaults: 6/5min/30s/5att", d8.get("otp_length") == 6 and d8.get("otp_validity_min") == 5
      and d8.get("resend_cooldown_sec") == 30 and d8.get("max_attempts") == 5)
check("trusted device default OFF", d8.get("trusted_device_enabled") is False)
r9 = requests.put(f"{B}/admin/security-settings/2fa", headers=H,
                  json={"sms_config": {"provider": "twilio", "twilio_sid": "AC123", "twilio_token": "tk", "twilio_from": "+1555"}})
check("settings PUT 200", r9.status_code == 200)
d9 = requests.get(f"{B}/admin/security-settings/2fa", headers=H).json()
check("secrets masked in GET", d9["sms_config"]["twilio_token"] == "••••••••", d9["sms_config"]["twilio_token"])
# masked resubmit keeps stored value
requests.put(f"{B}/admin/security-settings/2fa", headers=H, json={"sms_config": d9["sms_config"]})
raw = db.security_settings.find_one({"key": "2fa"})
check("masked resubmit keeps secret", raw["sms_config"]["twilio_token"] == "tk")
# revert sms config
requests.put(f"{B}/admin/security-settings/2fa", headers=H,
             json={"sms_config": {"provider": "", "twilio_sid": "", "twilio_token": "", "twilio_from": ""}})
db.security_settings.update_one({"key": "2fa"}, {"$set": {"sms_config.twilio_token": "", "sms_config.twilio_sid": ""}})

# 7) my-security shape
d10 = requests.get(f"{B}/auth/2fa/my-security", headers=H).json()
check("my-security: required True", d10.get("twofa_required") is True)
check("my-security: masked + sessions", "*" in d10.get("masked_email", "") and d10.get("active_sessions", 0) >= 1)

# 8) audit events in users-log
d11 = requests.get(f"{B}/admin/users-log", headers=H,
                   params={"search": "OTP_VERIFICATION", "from_date": "2026-06-01"}).json()
acts = {e["action"].split(" via")[0] for e in d11["events"]}
check("audit OTP_VERIFICATION_SUCCESS logged", any("OTP_VERIFICATION_SUCCESS" in a for a in acts), str(list(acts))[:120])
check("audit OTP_VERIFICATION_FAILED logged", any("OTP_VERIFICATION_FAILED" in a for a in acts))
d12 = requests.get(f"{B}/admin/users-log", headers=H,
                   params={"search": "OTP_SENT", "from_date": "2026-06-01"}).json()
check("audit OTP_SENT_EMAIL logged", any("OTP_SENT_EMAIL" in (e.get("action") or "") for e in d12["events"]))

# 9) company_admin (non-2FA role) login unaffected
r13 = requests.post(f"{B}/auth/admin-password-login",
                    json={"email": "admin@kankani.local", "password": "wrongpass"})
check("company_admin wrong pw → 401 (flow intact)", r13.status_code in (401, 403), str(r13.status_code))

# 10) resend with unconfigured method → friendly error
r14 = requests.post(f"{B}/auth/admin-password-login",
                    json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"})
pt3 = r14.json().get("pending_token")
db.twofa_pending.update_one({"pending_id": pt3}, {"$set": {"resend_available_at": None}})
r15 = requests.post(f"{B}/auth/2fa/resend", json={"pending_token": pt3, "method": "whatsapp"})
check("whatsapp not configured → 400 friendly", r15.status_code == 400, r15.json().get("detail", "")[:60])
db.twofa_pending.delete_one({"pending_id": pt3})

print(f"\n===== {P} passed, {F} failed =====")
sys.exit(1 if F else 0)
