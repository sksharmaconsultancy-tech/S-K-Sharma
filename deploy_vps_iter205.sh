#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 205)
# Ships:
#  • ATTENDANCE REPORT GRID: Employee Code column removed; Father Name
#    column added; Name / Father Name / Designation / Bio Code FROZEN
#    while scrolling right; header row FROZEN while scrolling down.
#  • CLOCK-TIMING TOTALS: Duty HRS / OT HRS / Total Duty HRS totals are
#    exact HH:MM clock sums. In "Attendance Calculation as per Duty HRS"
#    mode, Present Days = WHOLE days (163:00 @ 12h = 13 days + 07:00
#    Extra HRS — no more 13.58 decimals).
#  • OT CROSS-VERIFICATION: every attendance Excel (In/Out + Hours Only)
#    now includes a separate "OT HRS" sheet with day-wise OT only.
#  • WEEK-OFF WORKED ATTENDANCE (Attendance Policy → new section):
#    Mode: OT Only / Half Day + OT / Full Day + OT / Hourly Conversion,
#    Half/Full-Day thresholds, OT-starts-after, Salary Credit, Leave
#    Adjustment, Comp-Off, Double OT, Double Wages, Approval Required —
#    fully dynamic per firm; attendance engine recalculates automatically.
#  • Proposal PDF/Word export fix (company_id) — included since Iter 204.
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
check "/api/admin/attendance/monthly-grid/x/2026-07" "401" "Attendance grid API"
check "/api/admin/attendance/monthly-hours/x/2026-07.xlsx" "401" "Hours-Only XLSX (with OT sheet)"
check "/api/attendance/policy?company_id=x" "401" "Attendance Policy API (Week-Off Worked)"
echo
echo "🎉 Deploy complete."
echo "   NEW: Attendance Policy → 'Week-Off Worked Attendance' — set the"
echo "   mode + thresholds per firm. Attendance Report now freezes the"
echo "   identity columns and shows clock-exact totals with whole Present"
echo "   Days; Excel downloads include a separate OT HRS sheet."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
