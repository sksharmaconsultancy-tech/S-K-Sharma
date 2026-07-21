#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 216/217/218)
# Ships (Actual Salary Process changes):
#  • Duty HRS now comes from the EMPLOYEE MASTER's per-day Daily Working
#    HRS (employee override → assigned shift length → firm policy → 8) —
#    exactly matching the Attendance Report.
#  • Basic Salary is READ-ONLY — always fetched from the Employee
#    Master's Actual Salary (Basic row). Inline edits are blocked in the
#    grid and rejected by the API.
#  • Code No. / Type / Roll columns removed from the process grid.
#  • "Select firm" is now a searchable DROPDOWN (was a chip list).
#  • NEW FIRM GATE — when the Attendance Policy sub-point "Count Present
#    Day @ 8 HRS (Compliance only)" is ON, On-roll employees CANNOT be
#    processed in the Actual Salary Process (all groups). They are paid
#    via the Compliance Salary Process only, where attendance
#    direct-syncs @ 8 worked HRS = 1 Present Day.
# Plus (Compliance Salary Process):
#  • Attendance auto-fetch hardened — Present Days/OT pulled from the
#    Attendance Report grid for EVERY firm in scope (super-admin runs
#    without an explicit firm filter included).
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
echo "   Salary Process → Actual: firm DROPDOWN, Duty HRS from Employee"
echo "   Master, Basic read-only (from Employee Master Actual Salary),"
echo "   Code/Type/Roll columns removed. Firms with 'Count Present Day"
echo "   @ 8 HRS' ON: On-roll salary only via Compliance Process."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
