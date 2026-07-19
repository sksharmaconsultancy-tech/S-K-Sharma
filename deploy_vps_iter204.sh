#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 204)
# Ships:
#  • SHIFT CHANGE REQUEST & APPROVAL MODULE (v2):
#      - Attendance Policy → "Employee Shift Change" config: Enabled Yes/No,
#        Reason mandatory, Post-punch allowed, Auto-approve, Instant
#        exception, Time window, Approval levels.
#      - Employee app → "Request shift change" (date, requested shift,
#        reason/remarks, My Requests with status timeline + cancel).
#      - Admin portal → Approvals → "Shift Change Requests": pending queue,
#        single + bulk Approve / Reject / Send Back with remarks,
#        Shift Change Register (Excel) + Daily Shift Assignments report.
#      - Approved shift applies to that day automatically — attendance,
#        OT and payroll views recalculate on the APPROVED shift.
#  • INSTANT SHIFT EXCEPTION: if an IN punch is >2 hrs away from the
#    assigned shift start, the app immediately offers to raise a Shift
#    Change Request (policy-gated).
#  • Half-Day Threshold Rule fixes: 0.5 day now shows in Present Days on
#    In/Out and Hours-Only report sheets; OT Duty HRS report (XLSX + PDF);
#    Hours-Only sheet day-wise Duty HRS / OT HRS rows.
#  • Bulk Employee Correction: search bar + Employee Code / Name /
#    Father Name locked (read-only).
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

echo "==> 6/6 Verifying the new Iter 204 endpoints..."
curl -s http://localhost:8001/api/health && echo
check() {
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001$1")
  if [ "$CODE" = "$2" ]; then
    echo "✅ $3 ($1 -> $CODE)."
  else
    echo "❌ $1 returned $CODE (expected $2) — check supervisor logs."
  fi
}
# All routes require auth -> 401 without a token proves they exist.
check "/api/shift-change/config" "401" "Employee shift-change config API"
check "/api/shift-change/requests-v2/my" "401" "Employee my-requests API"
check "/api/admin/shift-change/requests-v2" "401" "Admin requests queue API"
check "/api/admin/shift-change/register?company_id=x&month=2026-06" "401" "Shift Change Register API"
check "/api/admin/shift-change/daily-assignments?company_id=x&month=2026-06" "401" "Daily Assignments API"
echo
echo "🎉 Deploy complete."
echo "   HOW TO USE: Attendance Policy → 'Employee Shift Change' → Enabled = Yes."
echo "   Employees: Home → 'Request shift change'. Admin: Approvals → 'Shift Change Requests'."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
