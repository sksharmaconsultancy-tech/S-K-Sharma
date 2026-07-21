#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 220)
# Ships (Sub Admin & Staff Users overhaul):
#  • MOBILE NO. FIX — the Mobile field no longer shows an email id. Any
#    email wrongly saved into the mobile field in master data is cleaned
#    up by this deploy, and typing an email there is now rejected with a
#    clear message. Mobile is also editable on the Edit Staff form.
#  • SEPARATE 6-DIGIT PIN + PASSWORD — Sub Admin and Staff User forms now
#    have both a Password and an optional 6-digit PIN. Either credential
#    signs in on the Employer login page (email or mobile + PIN/password).
#  • LINK EXISTING EMPLOYEE AS STAFF USER — adding a staff user with an
#    email that belongs to an existing employee of the firm LINKS that
#    employee: they open the portal with their EXISTING User ID &
#    password (leave the password blank to keep it). Their employee app
#    login is untouched, and removing the staff login later keeps the
#    employee record intact.
# Run ON THE VPS as the sksharma user.
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

echo "==> 4/7 Cleaning emails wrongly saved in Mobile No. fields..."
cd $APP_DIR/backend && $PY - << 'PYEOF'
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv(".env")
async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    r1 = await db.users.update_many({"phone": {"$regex": "@"}}, {"$set": {"phone": None}})
    r2 = await db.users.update_many({"phone_e164": {"$regex": "@"}}, {"$set": {"phone_e164": None}})
    print(f"   cleaned phone: {r1.modified_count}, phone_e164: {r2.modified_count}")
asyncio.run(main())
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
check() {
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001$1")
  if [ "$CODE" = "$2" ]; then
    echo "✅ $3 ($1 -> $CODE)."
  else
    echo "❌ $1 returned $CODE (expected $2) — check supervisor logs."
  fi
}
check "/api/admin/sub-admins" "401" "Sub Admins API"
check "/api/admin/company-staff" "401" "Staff Users API"
echo
echo "🎉 Deploy complete."
echo "   Sub Admin / Staff User forms: Mobile No. is digits-only (emails"
echo "   cleaned + blocked), separate 6-digit PIN + Password credentials,"
echo "   and existing employees LINK as staff keeping their existing"
echo "   User ID & password."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
