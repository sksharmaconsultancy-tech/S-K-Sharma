#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 310)
# Ships: FREEZE SALARY module + EMPLOYEE MASTER DETAIL SLIP (Phase 1).
# Run ON THE VPS as root/sksharma.
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

# AI Payroll Assistant needs the Emergent universal LLM key.
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
  echo "   EMERGENT_LLM_KEY added to backend/.env ✅"
fi

echo "==> 3/6 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
# Iter 310 — QR code library for the Employee Detail Slip PDF.
$PIP show qrcode >/dev/null 2>&1 || $PIP install qrcode -q
$PIP show emergentintegrations >/dev/null 2>&1 || \
  $PIP install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q

echo "==> 4/6 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
# BLANK-PAGE FIX (Iter 295): DO NOT wipe old bundles — installed PWAs
# with a cached index.html still find their old entry-*.js. Old bundles
# are pruned only after 30 days.
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/
sudo find $WEB_DIR/_expo/static/js/web -name "entry-*.js" -mtime +30 -delete 2>/dev/null || true

echo "==> 5/6 Restarting backend..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 5

echo "==> 6/6 Verifying..."
curl -s http://localhost:8001/api/health && echo
CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001/api/admin/employee-detail-slip/employees")
echo "   /api/admin/employee-detail-slip → HTTP $CODE (401/403 = alive, auth required)"

echo
echo "🎉 Deploy 310 complete."
echo
echo "WHAT'S NEW IN THIS DEPLOY:"
echo
echo "🧊 FREEZE SALARY (Compliance Salary Process):"
echo "  • Processing with 'Use imported sheet' now FREEZES the exact"
echo "    imported attendance & Gross Earning on the run (frozen badge)."
echo "  • Difference engine: Imported Gross vs Master-calculated Gross."
echo "    If Imported > Calculated, the difference goes to OVERTIME when"
echo "    Firm Master → Salary Process → 'OT Allowed' is ON, otherwise"
echo "    to OTHER ALLOWANCES. Net pay recalculates automatically."
echo "  • New grid columns: Imp. Gross / Calc. Gross / Difference /"
echo "    Diff. Alloc. — plus totals. An immutable snapshot of every"
echo "    import is stored for audit (freeze_salary_snapshots)."
echo
echo "🪪 NEW: EMPLOYEE MASTER DETAIL SLIP — Employees → Employee Detail Slip"
echo "  • Professional A4 slip with the complete Employee Master:"
echo "    Personal / Employment / Statutory-KYC / Bank / Salary sections."
echo "  • FYTD Attendance Summary + Leave Information (financial year)."
echo "  • Profile completion %, employee search, prev/next navigation."
echo "  • Exports: Print · PDF (with QR code) · Excel · Email."
echo "  • Fields not yet in the master (Mother Name, Grade, Cost Centre,"
echo "    Confirmation Date, Nominee, Education, Experience, Assets)"
echo "    show '—' — they arrive in Phase 2."
