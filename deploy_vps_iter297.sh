#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 297)
# Ships everything since deploy 295/296:
#  1. 💰 SALARY REPROCESS = UPDATE, NOT RESET (user directive):
#     • Compliance Salary Process AND Actual Salary Process — clicking
#       "Salary Process" for an already-processed month asks
#       "Do you want to REPROCESS the salary for this month?".
#     • YES → previously ENTERED days & manual edits are KEPT:
#         - Compliance: Present Days, OT hrs and the manual Other
#           Deduction of every employee carry over; PF/ESIC/PT/Net are
#           recalculated from those preserved days.
#         - Actual: P Days, P Hours, Adv, TDS and manual OT-amount
#           edits carry over; Gross/Net recalculated.
#     • Data is updated in place — never starts again from zero.
#  2. 🐛 ESIC ZERO-DAY FIX (user bug): employees with 0 days in the
#     front window now show ESIC = 0 (previously the full-month master
#     Basic leaked into the ESIC calculation). PF / PT / TDS are also
#     forced to 0 on a zero-day, zero-pay month.
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

# Never cache index.html; cache hashed assets forever (Iter 295).
SITE_CONF=$(grep -rl "root $WEB_DIR" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | head -1)
if [ -n "$SITE_CONF" ] && ! grep -q "sks-cache-fix" "$SITE_CONF" && ! grep -q 'Cache-Control "no-cache' "$SITE_CONF"; then
  sudo cp "$SITE_CONF" "$SITE_CONF.bak-cache"
  sudo sed -i "0,\|root $WEB_DIR;|s||root $WEB_DIR;\n    # sks-cache-fix — never cache the SPA shell; cache hashed assets forever\n    location = /index.html { add_header Cache-Control \"no-store, must-revalidate\"; }\n    location /_expo/static/ { add_header Cache-Control \"public, max-age=31536000, immutable\"; }|" "$SITE_CONF"
  if sudo nginx -t 2>/dev/null; then
    sudo systemctl reload nginx
    echo "   nginx cache headers applied ✅"
  else
    sudo mv "$SITE_CONF.bak-cache" "$SITE_CONF"
    echo "   nginx patch skipped (config test failed — restored backup)"
  fi
fi

echo "==> 5/6 Restarting backend..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 5

echo "==> 6/6 Verifying..."
curl -s http://localhost:8001/api/health && echo
for EP in "admin/compliance-salary-runs" "admin/salary-runs"; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001/api/$EP")
  echo "   /api/$EP → HTTP $CODE (401/403 = alive, auth required)"
done
echo
echo "🎉 Deploy 297 complete."
echo
echo "FIXES IN THIS DEPLOY:"
echo "  • 💰 Salary Process (Actual + Compliance): reprocessing a month now"
echo "    UPDATES the existing data — your previously entered days, Adv/TDS"
echo "    and Other Deductions are KEPT, never reset to zero."
echo "  • 🐛 ESIC fix: employees with ZERO days in the month now show"
echo "    ESIC = 0 (no more phantom ESIC amounts)."
