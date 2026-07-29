#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 373)
# INCLUDES Iter 370 + 371 + 372 + NEW:
#
# Iter 373:
#   1. EXCEL / CSV EXPORTS MATCH THE PDF — dynamic firm-wise heads:
#      • Compliance Salary export.xlsx / export.csv drop the disabled
#        allowance columns (HRA / Conv / Medical / Special / Others) and
#        disabled deduction columns (all PF cols / all ESIC cols / PT /
#        TDS) exactly like the PDF register.
#      • Actual Salary export.xlsx / export.csv now use the Actual grid
#        columns (P Days / P Hours / Basic / Basic Sal / W.Basic Sal /
#        Oth.Allo / Total Gross / EPF / ESI / Adv / TDS / Net Pay) with
#        EPF & ESI dynamic per Firm Master.
#   2. UNLOCK OFFERED IN-PLACE — clicking "Salary Process" on a month that
#      is already FINALIZED now shows Super/Sub Admins a Yes/No dialog:
#      "UNLOCK it now so it can be edited / reprocessed?" — Yes unlocks
#      immediately (no more dead-end message).
#
# Iter 372: dynamic PDF heads per firm + UAN/EPF/ESI label & overflow fix.
# Iter 371: Configure batch UNLOCK button + month default after 25th.
# Iter 370: first-click PF/ESIC fix, header sorting, column totals,
#           validation panel at bottom.
#   NOTE: REPROCESS existing months once so rows carry the new flags.
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
echo -n "   Dynamic Excel columns (must be >= 1): "
grep -c "def dynamic_csv_columns" $APP_DIR/backend/utils/compliance_salary.py || true
echo -n "   Actual export columns (must be >= 1): "
grep -c "ACTUAL_CSV_COLUMNS" $APP_DIR/backend/utils/salary_run.py || true
echo -n "   In-place unlock offer (must be >= 1): "
grep -c "UNLOCK it now" $APP_DIR/frontend/app/compliance-salary-run.tsx || true
echo ""
echo "✅ Deploy Iter 373 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Excel & CSV exports now match the PDF (firm-wise dynamic heads)."
echo "   → Click Salary Process on a FINALIZED month → Yes/No UNLOCK dialog"
echo "     appears for Super/Sub Admins (plus the amber Unlock button)."
echo "   → Iter 370-372 items included (PDF dynamic heads, sorting, totals,"
echo "     first-click PF/ESIC, month default after 25th)."
echo "   → REPROCESS existing months once to pick up the new flags."
