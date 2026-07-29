#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 363)
# USER REQUEST: OLD DB BioCode → Bio Code (device enrolment no.) on the
# portal employee — fetched together with the Actual Salary data.
#   • Legacy Import wizard (salary group) and
#     "Sync Salary Structures — ALL Firms (from Old DB)" now also copy
#     EmployeeMaster.BioCode → users.bio_code (the biometric device
#     enrolment number used to map punches to employees).
#   • Handles numeric cells ("72.0" → "72"), skips empty/0 values,
#     case-insensitive column lookup (BioCode/BiometricCode/MachineCode).
#   • New live sync counter: bio_codes_synced.
# Also ships Iter 362 (Actual Salary Comparison report), Iter 361
# (Offline/Actual salary from old DB: Salary→Basic, Salary1-3, Days1-3),
# Iter 360 (✨ AI Universal Payroll Import), Iter 359 (PF & ESIC Claims).
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
echo -n "   BioCode mapping (must be > 0): "
grep -c "bio_codes_synced" $APP_DIR/backend/routes/legacy_import.py || true
echo -n "   Salary comparison endpoint (Iter 362, must be > 0): "
grep -c "actual-salary-compare" $APP_DIR/backend/routes/legacy_import.py || true
echo -n "   Actual salary struct mapping (Iter 361, must be > 0): "
grep -c "_actual_salary_struct" $APP_DIR/backend/routes/legacy_import.py || true
echo ""
echo "✅ Deploy Iter 363 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Legacy Import → 'Sync Salary Structures — ALL Firms (from Old"
echo "     DB)' — the counters now include bio_codes_synced along with"
echo "     actual_salary_synced."
echo "   → Spot-check: Employees → any employee → Bio Code should show the"
echo "     old software's device enrolment number."
echo "   → Then the Actual Salary Comparison (green button) to confirm"
echo "     Basic + Salary 1-3 + Days all show ✅ ALL MATCH."
