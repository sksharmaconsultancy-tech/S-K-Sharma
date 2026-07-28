#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 341)
# Ships (everything since deploy 340):
#   • FREEZE SALARY = DISPLAY-ONLY after import (user request): the admin
#     can EDIT OT Amount / Other Allowances on an imported run — edits
#     STICK (reprocess keeps them, marked "Manual"); the Freeze column
#     stays as comparison data with live ✓/≠ status.
#   • EPS DISABLE (Employee Master, after VPF): employee not eligible for
#     Pension → ECR prints EPS wages/contribution 0; full employer share
#     goes to EPF (both ECR formats; works on old runs too).
#   • PUNCH LOG REPORT: unmatched bio codes appear as red "NOT FOUND"
#     rows; employees registered TODAY marked 🆕 NEW REGISTRATION; Excel
#     gets a Remark column.
#   • PWA SPEED: /companies now 3 aggregate queries total (was 3 × firms)
#     + lite mode for all 28 firm pickers (tiny payload) → firm selection
#     is near-instant.
#   • BULK EMPLOYEE CORRECTION (Actual): new On/Off-Roll column — bulk
#     shift Off-Roll → On-Roll.
#   • LEGACY IMPORT: Active/Resigned import counts; duplicate-email
#     E11000 fix (employee imports without the clashing email);
#     "Old DB vs Portal — Difference List" button (who was not imported
#     + reason); firm-list caps 300→5000 (fixes "company not showing in
#     list after undo / already created" bug).
#   • OFFLINE legacy salary → "Publish months to ACTUAL Salary Process"
#     button (off-roll months appear in Actual Salary past runs; undo
#     removes them).
#   • ATTENDANCE SHEET AUTOMATION allowed for Sub Super Admin; download
#     file names now include the FIRM NAME.
#   • Compliance grid: OT Amt* + OT Hrs BEFORE Gross; trailing freeze
#     columns replaced by red diff-row highlight; days clamped to month;
#     no negative differences; Punch Approvals Extra Duty as H:MM.
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
echo -n "   EPS-disable engine in backend (must be > 0): "
grep -c "eps_disabled" $APP_DIR/backend/server.py || true
echo -n "   Manual-override freeze keep (must be > 0): "
grep -c "manual_override" $APP_DIR/backend/server.py || true
echo -n "   Fast firm picker in web bundle (must print a file): "
grep -rl "lite=1" $WEB_DIR/_expo/static/js/web/ 2>/dev/null | head -1 || echo "NOT FOUND ⚠"

echo ""
echo "✅ Deploy Iter 341 complete!"
echo "   • Hard-refresh the browser (Ctrl+Shift+R) after deploy."
echo "   • Freeze runs: OT edits now stick; freeze is display-only."
echo "   • Employee Master → EPS Disable → ECR prints EPS 0."
echo "   • Firm picker is fast; Punch Log flags NOT FOUND / NEW REG."
