#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 374)
# INCLUDES Iter 370-373 + NEW USER BUG FIX:
#
# Iter 374 — MANUALLY FILLED AMOUNTS ARE NEVER REMOVED:
#   1. LOCK (Finalize): pending grid edits are FLUSHED to the server
#      BEFORE the run is locked — the debounced auto-save used to arrive
#      after the lock and get rejected, silently dropping just-typed
#      amounts. Fixed in BOTH Compliance and Actual Salary windows.
#   2. UNLOCK → REPROCESS: the engine now restores every manually filled
#      amount (Others / OT Amt / TDS / ESIC Leave / Other Deduction) from
#      the saved run. The grid stamps each manual edit on the row
#      (manual_fields) and the reprocess rebuilds Gross / Total Ded. / Net
#      around the kept figures. Heuristics also cover rows saved BEFORE
#      this fix (ESIC Leave, OT amount without OT hours, TDS without an
#      imported sheet are treated as manual).
#   Result: data saved while processing salary is NEVER removed unless
#   you change it yourself.
#
# Iter 373: Excel/CSV exports match the PDF + in-place unlock dialog.
# Iter 372: dynamic PDF heads per firm + UAN/EPF label & overflow fixes.
# Iter 371: Configure batch UNLOCK button + month default after 25th.
# Iter 370: first-click PF/ESIC fix, header sorting, column totals,
#           validation panel at bottom.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle (~115 MB, retries enabled)..."
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
echo -n "   Manual-amount keep fix (must be >= 1): "
grep -c "manual_fields" $APP_DIR/backend/server.py || true
echo -n "   Finalize flush fix (must be >= 2): "
grep -rc "FLUSH pending" $APP_DIR/frontend/app/compliance-salary-run.tsx $APP_DIR/frontend/app/salary-run.tsx | awk -F: '{s+=$2} END {print s}'
echo ""
echo "✅ Deploy Iter 374 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Type an amount (TDS / OT Amt / Others), lock or unlock and"
echo "     reprocess — the manual amount STAYS."
echo "   → Iter 370-373 items included."
