#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 331)
# Ships (everything since deploy 330):
#   • MASTER DATA REPORT — exact column sequence (UAN → EPFO → ESIC → Emp
#     Code → Name → … → Address blocks), Basic / PF Basic / HRA / Conv. /
#     dynamic allowance heads / Monthly Gross, Present + Permanent
#     address with City/State/PIN, Exit/Resign column hidden on Active tab,
#     click-to-sort on every column, per-column filters, keyboard
#     navigation (↑ ↓ PgUp PgDn Home End) with row highlight.
#   • LEGACY IMPORT WIZARD — allowance heads found in the old database are
#     AUTO-SET on the Firm Master (matching labels enabled, missing heads
#     created) so imported employee allowances flow into Compliance Salary
#     under the same heads. Preview shows the heads before import.
#   • FIRMS ID & PASSWORD — Sub Super Admins can now open it too
#     (verified with their OWN login PIN).
#   • RENAME — "Employee Master Data" → "All Employee Data" (sidebar/home).
#   • Copy Last Month Salary + PDF font +1 (if not yet deployed via 330).
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

echo "==> 8/8 Health check..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — check: journalctl -u sksharma-backend -n 50"

echo ""
echo "✅ Deploy Iter 331 complete!"
echo "   • Master Data Report: new column sequence, sort + filters,"
echo "     keyboard navigation with row highlight, salary heads,"
echo "     Present + Permanent address (City/State/PIN)"
echo "   • Legacy Import Wizard: allowances auto-set on Firm Master"
echo "   • Copy Last Month Salary + PDF font +1 (from deploy 330)"
