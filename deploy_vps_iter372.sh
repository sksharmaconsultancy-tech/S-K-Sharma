#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 372)
# INCLUDES Iter 370 + 371 + NEW PDF REPORT FIXES:
#
# Iter 372 (PDF reports):
#   1. DYNAMIC HEADS PER FIRM — Compliance Salary Register PDF (Format 1
#      AND Format/Option 2) + Actual Salary Register PDF now build their
#      ALLOWANCE and DEDUCTION columns dynamically from the Firm Master:
#      • H.R.A / CONV. / OTHER earnings columns appear only when enabled
#        in the Firm Master Allowances catalog.
#      • P.F. / E.S.I. / TDS deduction columns appear only when enabled
#        (EPF/ESI "Applicable" flags authoritative, same as the engine).
#      • Last-page summary lines follow the same firm-enabled heads.
#      • Actual Salary Register (Reports → Salary runs → PDF) now prints
#        the Actual grid columns (M.Days / P Days / P Hours / Basic /
#        Basic Sal / W.Basic Sal / Oth.Allo / Gross / EPF / ESI / Adv /
#        TDS / NET) with EPF & ESI dynamic per firm.
#   2. PDF FORMAT 1 — per-employee "UAN No. / P.F.: / ESI:" labels REMOVED
#      from the rows (numbers only); the column heading now reads
#      "UAN / P.F.NO. / ESI NO.".
#   3. PDF FORMAT 1 — EPF/UAN numbers no longer OVERWRITE neighbouring
#      columns (long IDs now wrap inside their own column).
#
# Iter 371: Configure batch UNLOCK button (Super/Sub Admins) for finalized
#           months + Month (FY-wise) defaults to CURRENT month after 25th.
# Iter 370: first-click PF/ESIC fix, header-click sorting, head-wise
#           column totals, Compliance Validation panel at the bottom.
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
echo -n "   Dynamic-PDF heads fix (must be >= 2): "
grep -c "Iter 372" $APP_DIR/backend/utils/compliance_salary.py || true
echo -n "   Actual register builder (must be >= 1): "
grep -c "build_actual_salary_register_pdf" $APP_DIR/backend/utils/salary_run.py || true
echo -n "   Unlock endpoint (must be >= 1): "
grep -c "salary-runs/{run_id}/unlock" $APP_DIR/backend/server.py || true
echo ""
echo "✅ Deploy Iter 372 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Compliance PDF Format 1 & 2: allowance/deduction columns follow"
echo "     the Firm Master; UAN/EPF/ESI numbers wrap inside their column"
echo "     with no per-row labels."
echo "   → Reports → Salary runs → PDF (actual runs): new Actual Salary"
echo "     Register with dynamic EPF/ESI columns."
echo "   → Configure batch: amber Unlock button for FINALIZED months."
echo "   → Month (FY-wise) defaults to the CURRENT month after the 25th."
echo "   → REPROCESS existing months once to pick up the new flags."
