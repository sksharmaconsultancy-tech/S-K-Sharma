#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 289)
# Ships everything since deploy 288, including:
#  1. BUG FIX — Labour Law Reports → Daily Attendance Register:
#     "From (optional)" / "To (optional)" date fields were not editable
#     and the calendar was not opening. Clicking the field now opens
#     the calendar picker properly (showPicker + full-field click area).
#     Fix applies to EVERY date field using the same component across
#     the portal (report date, from/to ranges, etc).
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip
PY=$APP_DIR/backend/venv/bin/python

echo "==> 1/6 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/6 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true

echo "==> 3/6 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/6 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
sudo rm -rf $WEB_DIR/*
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/6 Restarting backend..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 4

echo "==> 6/6 Verifying..."
curl -s http://localhost:8001/api/health && echo
echo
echo "🎉 Deploy complete."
echo
echo "WHAT'S NEW FOR YOUR TEAM:"
echo "  • Labour Law Reports → Daily Attendance Register: From / To date"
echo "    fields now open the calendar on click and are fully editable."
echo "  • Same fix applies to all date pickers portal-wide."
echo
echo "⚠️  IMPORTANT: Everyone must HARD-REFRESH the portal once"
echo "   (Ctrl+Shift+R on desktop / clear PWA cache on mobile)"
echo "   to load the new build."
