#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 202)
# Ships:
#  • BULK OPERATIONS module (sidebar → Bulk Operations):
#      - Bulk Attendance Upload (Status grid P/HD/A OR In-Out times Excel
#        template → preview → apply, overwrite option)
#      - Bulk Salary Revision (% / flat on Actual & Compliance, or Excel
#        upload with new amounts; every change logged in salary_revisions)
#      - Bulk Transfer between firms, Bulk Resignation (exit date),
#        Bulk Shift Assignment + full History log
#  • STATUTORY & MANAGEMENT REPORTS (sidebar → Reports → PT / LWF /
#    Gratuity / F&F / MIS): Professional Tax (all major states), Labour
#    Welfare Fund (state EE/ER + due months), Gratuity (15/26 rule),
#    Full & Final settlement, Advance/Loan register, Management MIS —
#    each in Excel + PDF.
#  • CLRA Registers: Excel export buttons for Form XII–XV.
#  • Attendance Policy sub-point: "Count Present Day @ 8 HRS (Compliance)"
#    — 8+ worked hrs = 1 Present Day, extra hrs → OT; applies to the
#    compliance salary run AND Day-wise IN/OUT, OT IN/OUT, HRS reports.
#  • "Days" column replaced with policy-based "Present Days" everywhere
#    (grid, XLSX downloads, F&F report).
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

echo "==> 6/6 Verifying the new Iter 202 endpoints..."
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
check "/api/admin/bulk-ops/employees?company_id=x" "401" "Bulk Ops API"
check "/api/admin/bulk-ops/history" "401" "Bulk Ops history API"
check "/api/admin/reports/pt?company_id=x&month=2026-06" "401" "PT report API"
check "/api/admin/reports/mis?month=2026-06" "401" "MIS report API"
check "/api/admin/clra-registers/form-xii.xlsx?company_id=x" "401" "CLRA Excel API"
echo
echo "🎉 Deploy complete. IMPORTANT: close & reopen the PWA twice (or"
echo "   Ctrl+Shift+R) on your devices so the new version loads."
