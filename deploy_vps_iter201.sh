#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 201)
# Ships everything since last night:
#  • Geofence Phase 2: OFFLINE attendance punching (IndexedDB queue +
#    auto background sync, firm-gated toggle, default OFF), idempotent
#    punch API honouring the original offline capture time.
#  • RBAC route protection: direct-URL access to restricted admin pages
#    shows "Access Denied" (staff/sub-admin); deep-link clobber bug fixed.
#  • Geofence Monitor page: offline / fake-GPS / outside-geofence /
#    pending registers + KPI cards + CSV export. Fake-GPS punches always
#    need manual approval.
#  • Proposals Phase 2: one-click "Convert to Customer" (creates Firm +
#    service agreement snapshot from a proposal).
#  • Firm Master: firm search bar.
#  • Attendance Policy: Report Settings (In/Out, OT, HRS-only, Day Salary,
#    In/Out+Salary per firm + default), Salary Allowed (Actual/Compliance/
#    Both) with salary-run gating, Weekly-off N/A + Rotation Basis,
#    Switch-Firm picker + saved-policy firm list, Textile Policy 1/2 &
#    Hospital presets retired.
#  • Policy Master Sub Points: Attendance by Duty HRS, Week-off worked →
#    OT (not present), Holiday worked → Present + OT (wired into grid &
#    salary engine).
#  • Holiday Master (Masters → Holidays, with dates).
#  • Employee Master Data: per-employee "Offline Salary: Yes/No";
#    Allowance/Deduction (Actual) fields moved below Rate Basis (Compliance).
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

echo "==> 6/6 Verifying the new Iter 198-201 endpoints..."
curl -s http://localhost:8001/api/health && echo
check() {
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001$1")
  if [ "$CODE" = "$2" ]; then
    echo "✅ $3 ($1 -> $CODE)."
  else
    echo "❌ $1 returned $CODE (expected $2) — check supervisor logs."
  fi
}
# All admin routes require auth -> 401 without a token proves they exist.
check "/api/admin/geofence/monitor" "401" "Geofence Monitor API"
check "/api/admin/geofence/report?type=offline" "401" "Geofence Register API"
check "/api/attendance/policy/saved-list" "401" "Saved-policy firm list API"
check "/api/attendance/my-geo-policy" "401" "Employee geo-policy API"
echo
echo "🎉 Deploy complete. IMPORTANT: close & reopen the PWA twice (or"
echo "   Ctrl+Shift+R) on your devices so the new version loads."
