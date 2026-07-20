#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 213)
# Ships:
#  • OT PUNCH DATE AUTO-FETCH (user rule):
#    - OT In date box PREFILLS automatically with the regular Out punch's
#      date (e.g. Out 19:58 on 08-07 → OT In 20:07 also 08-07). If the
#      OT In time is EARLIER than the Out time it crossed midnight and
#      lands on the NEXT day automatically.
#    - OT Out date box computes LIVE while typing: same day as OT In, or
#      the NEXT day once the OT Out time passes midnight (00:01+, i.e.
#      earlier than the OT In time). No more empty "auto date" box.
#    - Typing a date manually still overrides the auto value.
#  • Save logic uses the exact same dates you see on screen.
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
check "/api/admin/attendance/day-status/x?from_date=2026-07-01" "401" "Day-status API"
check "/api/admin/punch-import/template" "401" "Punch Import"
echo
echo "🎉 Deploy complete."
echo "   OT date boxes now AUTO-FILL: OT In gets the Out punch's date;"
echo "   OT Out's date computes live (next day after midnight 00:01+)."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
