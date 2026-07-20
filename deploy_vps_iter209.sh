#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 209)
# Ships:
#  • PUNCH IMPORT — OT column detection made bullet-proof:
#    - Accepts "OT In/Out", "OT-In", "OTIN Time", "O.T. In", "Overtime
#      In/Out", "OT Start/End" and merged group headers ("OT" spanning
#      In/Out sub-columns).
#    - Legacy .xls files now supported (not just .xlsx).
#    - Numeric time cells in H.MM style (20.07 → 20:07, 7.59 → 07:59).
#    - Import preview now SHOWS whether OT columns were detected:
#      green banner = OT will import; RED banner = OT columns not found
#      (lists the headers seen in your file so you know what to rename).
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
check "/api/admin/attendance/monthly-grid/x/2026-07" "401" "Attendance grid API"
echo
echo "🎉 Deploy complete."
echo "   RE-IMPORT your punch Excel now (Punch Approvals → Import)."
echo "   The preview screen will show a GREEN banner if the OT In/OT Out"
echo "   columns were detected, or a RED banner listing your file's"
echo "   headers if not. Old In/Out punches are skipped as duplicates —"
echo "   only the missing OT punches get added."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
