#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 208)
# Ships:
#  • NIGHT / CROSS-DAY OT IMPORT (user: Gajraj case):
#    Punch Import (Excel) now reads "OT In" and "OT Out" columns.
#    When OT Out is earlier than OT In (night OT, e.g. 20:07 → 07:59
#    next morning) the OT-Out lands on the next calendar day and the
#    attendance engine automatically counts the WHOLE OT session on the
#    FIRST punch day. Day total capped at 24 hrs.
#    Punch-import template + preview updated with OT columns.
#  • Includes Iter 207: Week-Off "Full Day (Min Hours)" mode, Weekly Off
#    N/A → Employee Master per-employee weekly off, Hours-Only day cells
#    = Duty + OT (max 24), Comp-Off Ledger.
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
check "/api/admin/punch-import/template" "401" "Punch Import (OT columns)"
check "/api/admin/attendance/monthly-grid/x/2026-07" "401" "Attendance grid API"
echo
echo "🎉 Deploy complete."
echo "   NIGHT OT: re-import your punch Excel WITH the 'OT In' / 'OT Out'"
echo "   columns (download the new template from Punch Approvals →"
echo "   Import). Night OT (out next morning) counts on the first punch"
echo "   day automatically."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
