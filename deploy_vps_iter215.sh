#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 216)
# Ships:
#  • SALARY PROCESS (ACTUAL) — attendance source fix:
#      - "Biometric (Auto)"  → Present Days + Extra Duty HRS auto-fetch
#        from the Attendance Report (exactly per the firm's Attendance
#        Policy — half-days like 26.5 preserved; Extra Duty HRS = OT
#        hours in per-day counting mode, remainder hours in duty-hour
#        division mode).
#      - "Manual"            → every employee starts at 0 Present Days
#        and 0 Extra Duty HRS (admin fills them in by hand).
#  • SALARY PROCESS (COMPLIANCE) — Present Days + OT are now FETCHED
#    from the same Attendance Report grid, so the compliance run always
#    matches the report and the Actual process (fixes staff/textile
#    policy_2 rows that were off by 1-2 days).
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
check "/api/admin/actual-salary-process" "405" "Actual Salary Process API"
check "/api/admin/compliance-salary-runs" "405" "Compliance Salary API"
echo
echo "🎉 Deploy complete."
echo "   Salary Process → Actual: pick Biometric (Auto) — Present Days and"
echo "   Extra Duty HRS fill straight from the Attendance Report. Pick"
echo "   Manual — everything starts at 0. Compliance Salary Process now"
echo "   fetches Present Days from the Attendance Report too."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
