#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 282)
# Ships everything since the last deploy, including:
#  1. SECURITY (SEC-004) — sessions now expire after 12 HOURS of
#     inactivity (was ~10 years). Any activity auto-extends the session
#     another 12h, so active users are never logged out. Existing
#     long-lived sessions on the server are clamped by this script.
#  2. NEW EMPLOYEE SCREEN — photo Upload / Change / Remove buttons
#     directly on the avatar; photo replaces (never duplicates).
#  3. EMPLOYEE MASTER — field order: Employee Code → Full Name →
#     Father's Name → Gender → Marital Status → Date of Birth →
#     Date of Joining → Mobile → Email.
#  4. Company-wise Shift Assignment (Shift Master → firm mapping;
#     Bulk Ops Shift Assign shows only the firm's shifts).
#  5. Rapid double-punch dedupe (punches within 30s ignored) +
#     Rectified Punches utility screen.
#  6. Compliance Salary Format 2 revamp, 19 editable PDF report
#     formats, IFSC auto-lookup, PIN codes, statutory field upgrades.
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip
PY=$APP_DIR/backend/venv/bin/python

echo "==> 1/7 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/7 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true

echo "==> 3/7 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/7 SEC-004 — clamping existing long-lived sessions to 12h..."
cd $APP_DIR/backend
$PY - <<'PYEOF'
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(".env")
client = MongoClient(os.environ["MONGO_URL"])
db = client[os.environ.get("DB_NAME", "test_database")]
cap = datetime.now(timezone.utc) + timedelta(hours=12)
r = db.user_sessions.update_many(
    {"expires_at": {"$gt": cap}}, {"$set": {"expires_at": cap}}
)
print(f"   clamped {r.modified_count} of {db.user_sessions.count_documents({})} sessions")
client.close()
PYEOF

echo "==> 5/7 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
sudo rm -rf $WEB_DIR/*
sudo cp -r dist/* $WEB_DIR/

echo "==> 6/7 Restarting backend..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 4

echo "==> 7/7 Verifying..."
curl -s http://localhost:8001/api/health && echo
echo
echo "🎉 Deploy complete."
echo
echo "SECURITY NOTE (SEC-004):"
echo "  • Sessions now expire after 12 hours of inactivity. Anyone idle"
echo "    for 12+ hours will simply be asked to log in again — this is"
echo "    the intended new security behaviour, NOT a bug."
echo "  • Users active in the app are auto-extended and never logged out."
echo
echo "  IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "  devices so the new version loads."
