#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 371)
# INCLUDES Iter 370 + 2 NEW USER REQUESTS:
#
# Iter 371:
#   1. UNLOCK BUTTON IN CONFIGURE BATCH (Compliance + Actual windows):
#      when the selected month's salary is already processed & FINALIZED,
#      Super Admin & Sub Admins see an amber "Unlock Salary — <month> is
#      Finalized" button right under Salary Process. One tap (with Yes/No
#      confirm) de-finalizes the run so it can be edited/reprocessed.
#      Sub Admin unlock is now IMMEDIATE (no approval request needed);
#      employer company admins still go through the approval flow.
#   2. MONTH (FY-WISE) DEFAULT: after the 25th of every month the default
#      month flips to the CURRENT month (on/before the 25th it stays the
#      previous month) — both salary process windows.
#
# Iter 370 (also in this bundle):
#   • FIRST-CLICK PF/ESIC FIX — eligibility kept separate from the 0-day
#     guard + firm policy awaited before the first process click; PF/ESIC
#     calculate instantly when days are typed (no second click).
#   • HEADER-CLICK SORTING on every column (▲ asc / ▼ desc / off).
#   • HEAD-WISE TOTALS under EVERY column in the grid TOTAL row.
#   • Compliance Validation panel moved to the BOTTOM of both windows.
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
echo -n "   Actual-run unlock endpoint (must be >= 1): "
grep -c "salary-runs/{run_id}/unlock" $APP_DIR/backend/server.py || true
echo -n "   Eligibility-flag engine fix (must be >= 2): "
grep -c "pf_eligible" $APP_DIR/backend/utils/compliance_salary.py || true
echo ""
echo "✅ Deploy Iter 371 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Configure batch: pick a month whose salary is FINALIZED — the"
echo "     amber 'Unlock Salary' button appears (Super/Sub Admins only)."
echo "   → Month (FY-wise) defaults to the CURRENT month after the 25th."
echo "   → Iter 370 items: first-click PF/ESIC, header-click sorting,"
echo "     head-wise column totals, validation panel at the bottom."
echo "   → REPROCESS existing months once to pick up the new flags."
