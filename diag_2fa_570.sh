#!/bin/bash
# S.K. Sharma & Co. — 2FA OTP EMAIL DIAGNOSTIC + RESCUE (Iter 570)
#
# Use when "OTP not received" at Super Admin login.
#
#   bash diag2fa.sh          → run all delivery checks + send a test email
#   bash diag2fa.sh rescue   → EMERGENCY LOGIN: prints a fresh OTP for the
#                              newest pending 2FA challenge so you can
#                              finish the login from the browser.
#
# Fetch on the VPS with:
#   wget -O diag2fa.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=diag2fa"

APP_DIR=/home/sksharma/app
ENV_FILE=$APP_DIR/backend/.env
PY=$APP_DIR/backend/venv/bin/python
[ -x "$PY" ] || PY=python3

if [ "$1" = "rescue" ]; then
  echo "══════════ EMERGENCY 2FA RESCUE ══════════"
  echo "1) In the browser, enter your email+password and press Sign in"
  echo "   (this creates a fresh pending challenge), THEN run this."
  echo ""
  $PY - <<'EOF'
import os, sys, hashlib, secrets
sys.path.insert(0, "/home/sksharma/app/backend")
from dotenv import load_dotenv
load_dotenv("/home/sksharma/app/backend/.env")
from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "labourlaw")]
row = db.twofa_pending.find_one(sort=[("created_at", -1)])
if not row:
    print("❌ No pending 2FA challenge found. Sign in from the browser FIRST, then rerun.")
    sys.exit(1)
user = db.users.find_one({"user_id": row["user_id"]}, {"email": 1, "name": 1})
code = str(secrets.randbelow(1000000)).zfill(6)
db.twofa_pending.update_one(
    {"_id": row["_id"]},
    {"$set": {"otp_hash": hashlib.sha256(code.encode()).hexdigest(),
              "attempts": 0, "blocked": False}})
print(f"✅ Rescue OTP for {(user or {}).get('email')}: >>> {code} <<<")
print("   Enter it on the OTP screen within its validity window.")
EOF
  exit 0
fi

echo "══════════ 2FA OTP EMAIL DIAGNOSTIC ══════════"

echo "==> 1/5 Backend .env email configuration:"
if grep -q "^RESEND_API_KEY=re_" $ENV_FILE 2>/dev/null; then
  echo "   RESEND_API_KEY: PRESENT ✓"
else
  echo "   RESEND_API_KEY: ❌ MISSING — OTP emails CANNOT send!"
  echo "   Fix: add RESEND_API_KEY=re_xxx to $ENV_FILE and restart backend."
fi
grep "^OTP_EMAIL_ENABLED" $ENV_FILE 2>/dev/null || echo "   OTP_EMAIL_ENABLED: (not set → defaults to true ✓)"
grep "^RESEND_FROM_EMAIL" $ENV_FILE 2>/dev/null || echo "   RESEND_FROM_EMAIL: (not set → onboarding@resend.dev)"
if grep -q "^RESEND_FROM_EMAIL=onboarding@resend.dev" $ENV_FILE 2>/dev/null || ! grep -q "^RESEND_FROM_EMAIL" $ENV_FILE 2>/dev/null; then
  echo "   ⚠️  NOTE: Resend's test sender (onboarding@resend.dev) can ONLY"
  echo "      deliver to the email that owns the Resend account. Other"
  echo "      admins' emails will FAIL until you verify your own domain"
  echo "      at resend.com/domains and set RESEND_FROM_EMAIL."
fi

echo "==> 2/5 Recent OTP/2FA delivery logs (backend):"
journalctl -u sksharma-backend -n 400 --no-pager 2>/dev/null | grep -iE "resend|2fa|otp" | tail -12 \
  || grep -iE "resend|2fa|otp" /var/log/supervisor/backend*.log 2>/dev/null | tail -12 \
  || echo "   (no matching log lines found — check your backend service logs)"

echo "==> 3/5 Live Resend API test (sends a real test email to the Super Admin):"
$PY - <<'EOF'
import os, sys
sys.path.insert(0, "/home/sksharma/app/backend")
from dotenv import load_dotenv
load_dotenv("/home/sksharma/app/backend/.env")
import requests
from pymongo import MongoClient
key = os.getenv("RESEND_API_KEY", "").strip()
if not key:
    print("   ❌ skipped — no RESEND_API_KEY"); sys.exit(0)
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "labourlaw")]
sa = db.users.find_one({"role": "super_admin", "email": {"$nin": [None, ""]}}, {"email": 1})
to = (sa or {}).get("email") or "sksharmaconsultancy@gmail.com"
frm = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev").strip()
r = requests.post("https://api.resend.com/emails",
                  headers={"Authorization": f"Bearer {key}"},
                  json={"from": f"S.K. Sharma & Co. <{frm}>", "to": [to],
                        "subject": "2FA diagnostic test email",
                        "text": "If you can read this, OTP email delivery works."},
                  timeout=15)
print(f"   To: {to} → HTTP {r.status_code}: {r.text[:200]}")
if r.status_code < 300:
    print("   ✅ Resend accepted the email — CHECK INBOX **AND SPAM/JUNK** folder!")
else:
    print("   ❌ Resend rejected it — the error above is the root cause.")
EOF

echo "==> 4/5 Pending 2FA challenges in DB (should clear after each login):"
$PY - <<'EOF'
import os, sys
sys.path.insert(0, "/home/sksharma/app/backend")
from dotenv import load_dotenv
load_dotenv("/home/sksharma/app/backend/.env")
from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "labourlaw")]
n = db.twofa_pending.count_documents({})
print(f"   twofa_pending rows: {n}")
for r in db.twofa_pending.find(sort=[("created_at", -1)]).limit(3):
    print(f"   • user={r.get('user_id')} method={r.get('method')} attempts={r.get('attempts')} blocked={r.get('blocked')} created={r.get('created_at')}")
EOF

echo "==> 5/5 Verdict guide:"
echo "   • Test email arrived in INBOX      → OTP works; original mail was likely in SPAM."
echo "   • Test email arrived in SPAM       → mark 'Not spam'; for permanent fix verify a"
echo "     domain at resend.com/domains and set RESEND_FROM_EMAIL=no-reply@yourdomain."
echo "   • HTTP 4xx from Resend             → key invalid OR test-sender restriction (see 1/5 note)."
echo "   • Locked out RIGHT NOW?            → bash diag2fa.sh rescue"
echo "══════════════════════════════════════════════"
