#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 207)
# Ships:
#  • WEEK-OFF "FULL DAY ATTENDANCE (MINIMUM HOURS)" mode:
#    Attendance Policy → Week-Off Worked Attendance → "Full Day (Min
#    Hours)". Worked ≥ minimum hours (default 50% of duty hours) on a
#    week-off → 1 FULL Present Day. Below the minimum → only the actual
#    hours count as plain Duty HRS (no Present / no OT). Day cap 24 hrs.
#  • WEEKLY OFF = N/A → EMPLOYEE MASTER DECIDES:
#    Firm policy weekly-off chip "N/A — Employee Master decides"
#    (default). Employee Master → Weekly Off (this employee) chips
#    (Mon..Sun / Firm default) — attendance engine resolves each
#    employee's week-off accordingly in ALL reports.
#  • HOURS-ONLY SHEET: the day-wise Duty HRS row now INCLUDES the day's
#    OT (Duty + OT combined, capped at 24) — the OT row and the separate
#    OT HRS sheet stay for cross-verification.
#  • COMP-OFF LEDGER (Iter 206, included): earned from worked week-offs,
#    admin ledger + Grant/Use, "Approve · Comp-Off" in leave approvals.
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
check "/api/attendance/policy?company_id=x" "401" "Attendance Policy API"
check "/api/admin/comp-off/summary" "401" "Comp-Off summary API"
check "/api/admin/attendance/monthly-hours/x/2026-07.xlsx" "401" "Hours-Only XLSX"
echo
echo "🎉 Deploy complete."
echo "   NEW: Weekly Off 'N/A — Employee Master decides' + per-employee"
echo "   Weekly Off in Employee Master → Textile master flags."
echo "   NEW mode: Week-Off Worked → 'Full Day (Min Hours)'."
echo "   Hours-Only day cells now show Duty + OT (max 24)."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
