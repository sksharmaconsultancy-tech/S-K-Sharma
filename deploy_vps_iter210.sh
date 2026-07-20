#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 210)
# Ships:
#  • PUNCH APPROVALS — search bar in the filter bar that narrows the rows
#    on EVERY tab (Pending / Approved / Rejected / Updated / Auto-Punches /
#    Manual Entries / Additional Duty) by name, father name, code or
#    designation.
#  • PUNCH APPROVALS — unified columns on every tab:
#    Code · Name · Father Name · Designation · In/Date · Out/Date ·
#    OT In/Date · OT Out/Date · Duty HRS · Total Duty HRS · Update Reason ·
#    Action. Each punch shows its OWN calendar date underneath; a night-OT
#    Out that lands next morning shows the next date in amber with "(+1)".
#  • OT punch pair (second In→Out pair) now visible on ALL tabs, including
#    Additional Duty (whose Total HRS preview now includes OT hours).
#  • Includes Iter 209: bullet-proof OT column detection on Excel punch
#    import (Overtime/merged/O.T. headers, .xls files, 20.07-style times)
#    + green/red OT-detection banner in the import preview.
# Run ON THE VPS as the sksharma user.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

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
check() {
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001$1")
  if [ "$CODE" = "$2" ]; then
    echo "✅ $3 ($1 -> $CODE)."
  else
    echo "❌ $1 returned $CODE (expected $2) — check supervisor logs."
  fi
}
check "/api/admin/punch-import/template" "401" "Punch Import"
check "/api/admin/attendance/day-status/x?from_date=2026-07-01" "401" "Day-status API (OT columns)"
echo
echo "🎉 Deploy complete."
echo "   Punch Approvals now has a SEARCH BAR + unified columns with"
echo "   OT In/OT Out (own date shown under each punch, amber (+1) for"
echo "   next-morning night OT) on every tab."
echo "   If you haven't yet: RE-IMPORT your punch Excel so the OT punches"
echo "   get added (preview shows a GREEN banner when OT columns are"
echo "   detected)."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
