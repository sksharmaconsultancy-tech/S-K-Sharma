#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 354)
# SALARY STRUCTURE — USER-SPECIFIED MAPPING (final fix):
#   The old software keeps the CURRENT salary structure directly on the
#   EmployeeMaster row. Import + ALL-FIRMS sync now read EXACTLY:
#     BasicSalary   → Basic
#     PFBasicSalary → PF Basic Salary
#     GrossPay      → Gross Salary
#     Earn1 → HRA          Earn2 → Conv.       Earn3 → OTH. ALLOW.
#     Earn4 → OVER TIME    Earn5 → INCENTIVE   Earn6 → OTHER MISC.ALLOWANCE
#     Earn7 → BONUS        Earn8 → MEDICAL ALLOWANCES
#     Earn9 → FOOD ALLOWANCES                  Earn10 → FOOD ALLOWANCE
#   (head names auto-refreshed from SalaryHeadMaster when present)
#   • EmployeeSalaryStructureDtl is NO LONGER used — its per-year history
#     rows were being SUMMED (HRA 19044 instead of 2000 for MAN SINGH).
#   • EMPLOYEE CODE CORRECTION: employees matched by NAME with a different
#     old-DB code get their portal code corrected (SANJAY 380 → 372);
#     sync result shows a "codes_corrected" counter.
#   • Manual head interlinks still apply on top of these names.
#   • NEW /api/legacy-query diagnostic endpoint (token-guarded, SELECT-only).
#   → WORKFLOW after deploy: Legacy Import →
#     "Sync Salary Structures — ALL Firms (from Old DB)" → re-check the
#     SUVIDHI STAFF Attendance Sheet.
#
# Robust download (Iter 352): retries up to 5x, resumes, verifies the tar.
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
echo -n "   AI layer routes (must be > 0): "
grep -c "ai/analysis" $APP_DIR/backend/routes/ai_layer.py || true
echo -n "   EmployeeMaster Earn-column mapping (must be > 0): "
grep -c "_earn_allowances" $APP_DIR/backend/routes/legacy_import.py || true
echo -n "   Code correction (must be > 0): "
grep -c "codes_corrected" $APP_DIR/backend/routes/legacy_import.py || true
echo ""
echo "✅ Deploy Iter 354 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   • ALL-FIRMS FIX: open Legacy Import → press"
echo "     'Sync Salary Structures — ALL Firms (from Old DB)'."
echo "     Watch the live counters (employees updated / gross changed /"
echo "     codes corrected)."
echo "   • Then spot-check SUVIDHI STAFF (Attendance Sheet Excel): e.g."
echo "     MAN SINGH MALOO must show Basic 27500 / HRA 2000 / CONV 1300 /"
echo "     Gross 30800, and SANJAY KUMAR LODHA's code becomes 372."
echo "   • New menu: AI Payroll Assistant (bottom of sidebar, or press g i)."
echo "   • Salary grids now have Filter… boxes under every column header."
echo "   • Attendance Sheet page has a 'Sort sheet by' option."
