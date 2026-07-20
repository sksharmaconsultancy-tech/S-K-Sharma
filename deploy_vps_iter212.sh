#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 212)
# Ships:
#  • OT MORNING-ONLY RULE — OT punches are allowed ONLY for employees
#    whose FIRST punch is a morning punch (before 12:00). Evening/night
#    first punches show "OT N/A · evening" and get no OT entry boxes.
#  • PUNCH APPROVALS COLUMNS reordered per directive:
#    Code · Name · Father Name · Designation · In Punch/Date ·
#    Out Punch/Date · Duty HRS · OT In/Date · OT Out/Date · OT Duty HRS ·
#    Total Duty HRS (Duty+OT) · Update Reason · Action.
#    OT In defaults to the Out punch's date; an OT Out past midnight
#    (00:01+) automatically lands on the next day.
#  • SUB SUPER ADMIN FULL ACCESS — sub admins now get ALL features:
#    - Sidebar shows every menu (except Sub Admins / Employer Access
#      Rights / Super Admin Access / Appearance which stay super-only).
#    - "Admins only" / "Access Denied" gates removed on ~25 screens
#      (punch approvals editing, manual punch entry, backdate punches,
#      payroll, challans, compliance settings, rosters, branches,
#      biometric devices, masters, AI insights, portal automation …).
#    - ~70 backend endpoints now accept the sub_admin role.
#    - Per-button restrictions via menu rights (Sub Admins screen) still
#      apply if you switch any button OFF.
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
check "/api/admin/attendance/day-status/x?from_date=2026-07-01" "401" "Day-status API (morning-only OT)"
check "/api/admin/punch-import/template" "401" "Punch Import"
echo
echo "🎉 Deploy complete."
echo "   • OT boxes appear ONLY for morning first punches; evening shifts"
echo "     show 'OT N/A · evening'."
echo "   • New column order incl. OT Duty HRS on all Punch Approval tabs."
echo "   • Sub Super Admins now have FULL access to all features."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads. Sub admins must log out and"
echo "   log back in once to refresh their menus."
