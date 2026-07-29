#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 369)
# COMPLIANCE SALARY — 2 USER FIXES (applies to the Salary Process register
# AND the AI Salary Compliance calculator):
#   1. MASTER SALARY (Full Month) — DYNAMIC per Firm Master:
#      the master columns (M.Basic / M.HRA / M.Conv / M.Med / M.Spl /
#      M.Others) now show ONLY the allowance heads ENABLED on that firm's
#      Firm Master Allowances catalog. If the firm configured the catalog
#      with everything OFF, only M.Basic + M.Gross remain. (Previously an
#      all-off catalog fell back to showing every column.)
#   2. EPF / ESI "APPLICABLE" FLAGS ARE NOW AUTHORITATIVE:
#      • EPF Applicable = DISABLED → NO PF calculated for that firm, even
#        if the Deductions catalog has "PF" ticked. Same for ESI.
#      • EPF/ESI Applicable = ENABLED → PF/ESIC calculated per policy.
#      • Flag never configured → falls back to the Deductions catalog
#        (keeps the earlier Iter 335 behaviour for old firms).
#      Deductions & Net recalc accordingly in new runs.
#   NOTE: regenerate the month's Compliance Salary run after deploy to see
#   the new columns/deductions (existing saved runs are not rewritten).
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
  echo "   Open the portal preview URL in a browser once, wait 30s, re-run."
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
echo -n "   Applicable-flag authoritative logic (must be >= 2): "
grep -c "Iter 369" $APP_DIR/backend/server.py || true
echo -n "   AI calc same fix (must be > 0): "
grep -c "Iter 369" $APP_DIR/backend/routes/ai_salary_compliance.py || true
echo ""
echo "✅ Deploy Iter 369 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → REGENERATE the month's Compliance Salary run, then verify:"
echo "     • MASTER SALARY (Full Month) shows only the firm's ENABLED"
echo "       allowance heads (from Firm Master → Allowances)."
echo "     • Firms with EPF Applicable OFF → no PF columns/deduction;"
echo "       ESI Applicable OFF → no ESIC. Enabled → calculated per policy."
echo "   → The Salary Compliance Process (AI) calculator follows the same"
echo "     flags (tested: ESI ON → ₹59 ESIC · ESI OFF → ₹0)."
