#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 340)
# Ships (everything since deploy 339):
#   • COMPLIANCE GRID (user requests):
#     – OT Amt* column moved BEFORE Gross; NEW "OT Hrs" column next to it.
#     – OT Hrs auto-derived: OT Amt ÷ (per-hour rate × OT multiplier);
#       rate follows Firm Master "OT Calculation On" (Basic | Gross).
#     – OT Hrs LOCKED on imported (Freeze) runs; MANUALLY editable on
#       normal runs when Firm Master Overtime is allowed (hours × rate
#       lands in OT Amt, Gross/Net recalculated live).
#     – Trailing "FREEZE SALARY (IMPORTED)" columns removed — rows where
#       Gross ≠ Freeze are HIGHLIGHTED in red instead.
#     – Present Days can NEVER exceed the month's days (sheet, reprocess,
#       derivation and manual entry all clamped).
#     – No negative Difference anywhere (incl. "Freeze as Actual Gross"
#       exact-days mode — floor at 2 decimals).
#   • PUNCH APPROVALS → Additional Duty: "Extra Duty" is entered as TIME
#     (H:MM, auto-colon while typing) instead of numeric HRS/MIN.
# Previous (339): one-time Freeze import (auto days derivation +
#   daily-rated fix + round-DOWN days), Firm Master points gated on
#   Online Salary toggle.
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
echo -n "   OT-hours engine in backend (must be > 0): "
grep -c "ot_hourly_rate" $APP_DIR/backend/server.py || true
echo -n "   OT Hrs column in web bundle (must print a file): "
grep -rl "OT Hrs" $WEB_DIR/_expo/static/js/web/ 2>/dev/null | head -1 || echo "NOT FOUND ⚠"

echo ""
echo "✅ Deploy Iter 340 complete!"
echo "   • Compliance grid: OT Amt + OT Hrs before Gross, freeze columns"
echo "     replaced by red row highlight, days clamped, no negatives."
echo "   • Punch Approvals: Extra Duty entered as TIME (H:MM)."
echo "   • Hard-refresh the browser (Ctrl+Shift+R) after deploy."
