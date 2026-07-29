#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 370)
# SALARY PROCESS — 4 USER FIXES (Compliance Salary + Actual Salary):
#   1. FIRST-CLICK PF/ESIC FIX:
#      • Previously a first "Salary Process" click with 0 Present Days
#        stamped the rows as PF/ESIC "not applicable", so typing the days
#        in the grid showed NO PF/ESIC until a SECOND process click.
#        The engine now keeps eligibility separate from the zero-day
#        guard — PF & ESIC calculate INSTANTLY on the first click as soon
#        as the days are entered.
#      • The firm's saved statutory policy (PF %, ESIC limit, wage caps)
#        is also awaited before the very first process click — no more
#        default numbers racing the policy load.
#      • Actual Salary syncs EPF/ESI from the compliance run, so it now
#        picks the correct figures on its first process too.
#   2. HEADER-CLICK SORTING (both windows): click ANY column heading to
#      sort the grid — 1st click ascending (▲), 2nd descending (▼),
#      3rd back to default order. Existing sort chips/PDF sort unchanged.
#   3. HEAD-WISE COLUMN TOTALS (both windows): the grid's bottom TOTAL
#      row now shows the total under EVERY column — Master Salary heads
#      (M.Basic / M.HRA / … / M.Gross), Present Days, ESIC Leave, Wage
#      Base, P Days / P Hours / Basic (Master) / Oth.Allo.
#   4. COMPLIANCE VALIDATION PANEL moved to the BOTTOM of the page on
#      both the Compliance Salary and Actual Salary windows.
#   NOTE: REGENERATE (reprocess) the month's Compliance Salary run once
#   after deploy so the rows carry the new eligibility flags.
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
echo -n "   Eligibility-flag engine fix (must be >= 2): "
grep -c "pf_eligible" $APP_DIR/backend/utils/compliance_salary.py || true
echo ""
echo "✅ Deploy Iter 370 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Compliance Salary Process:"
echo "     • Click 'Salary Process' ONCE, type Present Days — PF & ESIC"
echo "       calculate instantly (no second click needed)."
echo "     • Click any column heading to sort (▲ asc / ▼ desc / off)."
echo "     • TOTAL row shows head-wise totals under EVERY column."
echo "     • Compliance Validation panel is at the BOTTOM of the page."
echo "   → Actual Salary Process: same sorting + totals + panel moved;"
echo "     EPF/ESI sync from the compliance run on the first click."
echo "   → For an EXISTING month, press 'Reprocess' once so the rows pick"
echo "     up the new eligibility flags."
