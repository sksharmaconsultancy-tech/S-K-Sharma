#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 339)
# Ships (everything since deploy 338):
#   • ONE-TIME FREEZE IMPORT (user request — "Present Days showing 0"):
#     when the imported salary sheet carries a GROSS but NO attendance
#     days, Compliance Days are AUTO-DERIVED from the gross (Attendance +
#     Gross Validation behaviour) even when the firm hasn't picked a Days
#     Calculation Method — a single import now fills Days, recalculates
#     Basic/HRA/Conv + PF/ESIC/PT on those days and matches Freeze vs
#     Gross (✓ Matched); only the remaining difference goes to OT/Other.
#   • DAILY-RATED FIX: per-day gross probe (full-month compute) so days
#     derive correctly for daily-rated workers too (previously 0).
#   • NO NEGATIVE SALARY FIGURES (user request — BHERU LAL TELI −117):
#     derived days now round DOWN (half/full step) so the calculated
#     gross NEVER exceeds the imported freeze gross; rows whose sheet
#     days overshoot the imported gross auto-derive days from the gross —
#     the Difference column is always ≥ 0 (remainder → OT / Other).
# Previous (338):
#   • Import Freeze gross → ACTUAL Salary (Firm Master toggle) with OT /
#     Oth.Allo / Basic-adjust allocation + ❄ Freeze badge on the grid.
#   • Days Calculation Method points show when "Online Salary →
#     Compliance Salary Process" is enabled; workflow text per method.
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip
PY=$APP_DIR/backend/venv/bin/python

echo "==> 1/8 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/8 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 3/8 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP show qrcode >/dev/null 2>&1 || $PIP install qrcode -q
$PIP show emergentintegrations >/dev/null 2>&1 || \
  $PIP install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q

echo "==> 4/8 Google Chrome + Playwright browsers (RPA engine)..."
if ! command -v google-chrome-stable >/dev/null 2>&1 && [ ! -x /opt/google/chrome/chrome ]; then
  echo "   Installing Google Chrome stable..."
  wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  sudo apt-get install -y /tmp/chrome.deb >/dev/null 2>&1 || sudo dpkg -i /tmp/chrome.deb || \
    echo "   (Chrome install failed — RPA will fall back to bundled Chromium)"
else
  echo "   Google Chrome already installed ✅"
fi
$PIP show playwright >/dev/null 2>&1 || $PIP install playwright -q
$PY -m playwright install chromium >/dev/null 2>&1 || echo "   (chromium download skipped)"
sudo $PY -m playwright install-deps chromium >/dev/null 2>&1 || true

echo "==> 5/8 Building web frontend (expo export — split routes)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/
sudo find $WEB_DIR/_expo/static/js/web -name "*.js" -mtime +30 -delete 2>/dev/null || true

echo "==> 6/8 Restarting backend service..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend

echo "==> 7/8 Reloading nginx..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 8/8 Health check + verification..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — check: journalctl -u sksharma-backend -n 50"
echo "   --- VERIFY NEW CODE ---"
echo -n "   days_calc_method in backend (must be > 0): "
grep -c "days_calc_method" $APP_DIR/backend/server.py || true
echo -n "   Days Calc UI in web bundle (must print a file): "
grep -rl "Days Calculation Method" $WEB_DIR/_expo/static/js/web/ 2>/dev/null | head -1 || echo "NOT FOUND ⚠"

echo ""
echo "✅ Deploy Iter 339 complete!"
echo "   • Freeze import is now ONE-TIME: gross-only sheets auto-derive"
echo "     Compliance Days, salary + PF/ESIC recalculated, Freeze vs Gross"
echo "     matched (✓) — re-import or Reprocess the month to see it."
echo "   • Hard-refresh the browser (Ctrl+Shift+R) after deploy."
