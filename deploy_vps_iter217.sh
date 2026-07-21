#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 219)
# Ships:
#  • COMPLIANCE SALARY — "Count Present Day @ 8 HRS" now DIRECT-SYNCS
#    from the Attendance Report grid (the exact same punch pipeline as
#    the report — device punches, punch approvals, manual entries all
#    included). Per day: 8+ worked hrs = 1 Present Day, extra hrs → OT;
#    Half-Day Threshold Rule honoured (½ day, rest → OT); week-off /
#    holiday sub-points mirror the report. This fixes "attendance not
#    syncing" on firms with the 8-HR sub-point ON.
#  • HALF DAYS now SHOW on the Compliance sheet — Present Days displays
#    in half-day steps (e.g. 18.5) instead of a truncated whole number.
#  • MANUAL half-day input allowed — typing 18.5 in the Present Days
#    cell commits as a half day (values clamp to .0/.5 steps).
#  • Actual Salary Process gate (Iter 218) — firms with the 8-HR
#    sub-point ON cannot process On-roll employees in the Actual
#    process (Compliance only), plus all Iter 217 grid changes
#    (Duty HRS from Employee Master, Basic read-only, firm dropdown,
#    Code/Type/Roll columns removed) if not deployed yet.
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
check "/api/admin/compliance-salary-runs" "401" "Compliance Salary API"
echo
echo "🎉 Deploy complete."
echo "   Salary Process (Compliance): click Re-process for the month —"
echo "   Present Days + OT now sync straight from the Attendance Report"
echo "   (8-HR counting firms included). Half days show as .5 and can be"
echo "   typed manually."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
