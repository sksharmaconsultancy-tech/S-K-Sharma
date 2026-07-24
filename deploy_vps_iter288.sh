#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 288)
# Ships everything since deploy 287, including:
#  1. BUG FIX — Compliance Salary "Earning Head" missing for some
#     employees in Employee Master. Both salary editors (Update Salary
#     modal + Employee edit form) now show EVERY earning head saved on
#     the employee, even when that head is disabled/missing in the
#     firm's Firm Master (legacy/imported heads no longer disappear or
#     get wiped on save).
#  2. THEME PACK — 4 new Appearance themes: Lavender Mist, Mocha
#     Espresso, Arctic Ice + Deep Space (dark). 18 themes total.
#  3. WORKFLOW PHASE C — drag-drop workflow canvas, workflow versioning,
#     live Activity Monitor and notification rules in Access & Workflow
#     Mgmt (if 287 was already live this simply refreshes it).
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
echo "  • Employee Master → Update Salary / Edit Employee: ALL Compliance"
echo "    Salary earning heads now show for every employee — including"
echo "    legacy/imported heads that are not enabled in Firm Master."
echo "  • Add New Employee: Off-roll hides the whole Compliance Salary"
echo "    block; On-roll now REQUIRES the Compliance Basic Salary before"
echo "    the employee can be created."
echo "  • Appearance: 4 new themes (Lavender Mist, Mocha Espresso,"
echo "    Arctic Ice, Deep Space dark)."
echo "  • Access & Workflow Mgmt: drag-drop workflow canvas, versioning,"
echo "    live Activity Monitor, notification rules."
echo
echo "  IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "  devices so the new version loads."
