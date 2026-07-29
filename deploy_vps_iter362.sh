#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 362)
# NEW: 📊 ACTUAL SALARY COMPARISON — OLD DB vs PORTAL (audit report)
#   Legacy Import screen → green button
#   "Actual Salary Comparison — Old DB vs Portal (Basic + Salary 1-3 + Days)"
#   • Per mapped firm: every employee's OLD DB values (EmployeeMaster
#     Salary / Salary1-3 / Days1-3) side-by-side with the PORTAL's
#     salary_structure_actual (Basic + Salary 1/2/3 + Working Days).
#   • Status per employee: 🟢 MATCH · 🟠 DIFF (lists exactly which fields
#     mismatch) · 🔴 NOT IN PORTAL (no code/name match).
#   • Firm summary counters + expandable list showing ONLY the problem
#     rows (Old vs Portal values line by line).
#   • Excel + PDF export of the FULL comparison (all firms, all
#     employees, Old/Portal columns for all 7 fields + mismatch list).
#   → Use this BEFORE/AFTER "Sync Salary Structures — ALL Firms" to
#     audit that every employee's Offline/Actual salary matches the old
#     software.
# Also ships Iter 361 (Offline/Actual salary fetched from old DB:
# Salary→Basic, Salary1-3→Salary 1/2/3, Days1-3→Working Days) and
# Iter 360 (✨ AI Universal Payroll Import) + Iter 359 (PF & ESIC Claims).
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle (~110 MB, retries enabled)..."
rm -f /tmp/sks-latest.tar
ok=""
for i in 1 2 3 4 5; do
  if wget -c -T 60 -t 1 --show-progress -q -O /tmp/sks-latest.tar "$BUNDLE_URL"; then
    ok=1; break
  fi
  echo "   attempt $i failed — retrying in 10s (server may be waking up)..."
  sleep 10
done
if [ -z "$ok" ]; then
  echo "   wget failed 5x — trying curl..."
  curl -fSL --retry 5 --retry-delay 10 -o /tmp/sks-latest.tar "$BUNDLE_URL"
fi
if ! tar -tf /tmp/sks-latest.tar >/dev/null 2>&1; then
  echo "❌ Downloaded bundle is corrupt/incomplete ($(du -h /tmp/sks-latest.tar | cut -f1))."
  echo "   Open the portal preview URL in a browser once (to wake the server),"
  echo "   wait 30 seconds, then re-run this script."
  exit 1
fi
echo "   Bundle OK: $(du -h /tmp/sks-latest.tar | cut -f1)"

echo "==> 2/7 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 3/7 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP show emergentintegrations >/dev/null 2>&1 || \
  $PIP install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q

echo "==> 4/7 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/7 Restarting backend service..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend

echo "==> 6/7 Reloading nginx..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 7/7 Health check + verification..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"
echo -n "   Salary comparison endpoint (must be > 0): "
grep -c "actual-salary-compare" $APP_DIR/backend/routes/legacy_import.py || true
echo -n "   Actual salary struct mapping (Iter 361, must be > 0): "
grep -c "_actual_salary_struct" $APP_DIR/backend/routes/legacy_import.py || true
echo -n "   Comparison UI button (must be > 0): "
grep -c "li-actual-salary-compare" $APP_DIR/frontend/app/legacy-import.tsx || true
echo ""
echo "✅ Deploy Iter 362 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   WORKFLOW:"
echo "   1. Legacy Import → GREEN button 'Actual Salary Comparison — Old DB"
echo "      vs Portal' → see 🟢/🟠/🔴 counts per firm (BEFORE the sync,"
echo "      expect many 🟠 DIFF)."
echo "   2. Press 'Sync Salary Structures — ALL Firms (from Old DB)' —"
echo "      watch the actual_salary_synced counter."
echo "   3. Press the comparison button again — firms should now show"
echo "      '✅ ALL MATCH'. Use ⬇ Excel / ⬇ PDF for the full audit sheet."
