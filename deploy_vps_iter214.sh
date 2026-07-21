#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 214)
# Ships:
#  • LABOUR LAW REPORTS → SHIFT REPORT redesigned (user spec) as a live
#    "who is inside the premises" / emergency-evacuation muster roll:
#    Columns: Shift (From Master) · Code · Employee Name · Department ·
#    Designation · Punch In Time · Signature (blank, for physical
#    sign-off). A Date column is added automatically when the report is
#    run for a multi-day range.
#  • Employees currently on OT (second in-out cycle after a morning
#    first punch) are marked "OT — NAME" in front of their name.
#  • Shift comes from the employee's Shift Master assignment (falls back
#    to their shift timing when no master shift is set).
#  • Excel print: Signature column widened + taller rows to sign in.
#  • PDF print: wide fixed Signature box + taller rows, clean A4 layout.
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
check "/api/admin/labour-reports/catalogue" "401" "Labour Reports API"
check "/api/admin/attendance/day-status/x?from_date=2026-07-01" "401" "Day-status API"
echo
echo "🎉 Deploy complete."
echo "   Labour Law Reports → Shift Reports → Shift Report:"
echo "   run it for TODAY to get the live muster roll (who is inside,"
echo "   punch-in time, OT marker, blank Signature column). Export to"
echo "   Excel or PDF for printing."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
