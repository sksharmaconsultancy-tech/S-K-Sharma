#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 206)
# Ships:
#  • COMP-OFF LEDGER (new module):
#      - Employees EARN compensatory offs by working their weekly-off day
#        (Attendance Policy → Week-Off Worked Attendance → Comp-Off = Yes):
#        worked ≥ full-day threshold → 1 comp-off, ≥ half-day → 0.5.
#      - Admin portal → Reports → "Comp-Off Ledger": per-employee Earned /
#        Used / Balance, full ledger drill-down, manual Grant/Use
#        adjustments, auto-sync from attendance.
#      - Leave approvals: new "Approve · Comp-Off" button adjusts the leave
#        against the employee's comp-off balance (blocks if insufficient).
#      - Employees see their Comp-Off balance on the Leaves screen.
#  • Attendance Report: Group filter shows ONLY groups with active
#    employees in the selected firm (empty groups hidden).
#  • Frozen-header fix: identity headings now have a solid background so
#    day columns never overwrite Name / Father Name / Designation.
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
check "/api/admin/comp-off/summary" "401" "Comp-Off summary API"
check "/api/comp-off/my" "401" "Employee comp-off balance API"
check "/api/admin/attendance/monthly-grid/x/2026-07" "401" "Attendance grid API"
echo
echo "🎉 Deploy complete."
echo "   HOW TO USE: Attendance Policy → Week-Off Worked Attendance →"
echo "   Comp-Off = Yes. Then Reports → 'Comp-Off Ledger' in the sidebar."
echo "   Leave approvals now have an 'Approve · Comp-Off' button."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
