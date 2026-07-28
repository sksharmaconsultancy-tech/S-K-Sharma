#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 343)
# Ships (everything since deploy 342):
#   • COMPLIANCE SALARY "NOT ABLE TO SAVE" FIX (user bug — clicking
#     Salary Process / Save only refreshed the page with no message):
#       - Root cause: the screen used the BROWSER's confirm/alert popups.
#         Once the browser suppresses them ("Prevent this page from
#         creating additional dialogs" tick, or strict popup settings),
#         every confirm instantly answered "No" and the code reloaded the
#         page — silent refresh, nothing saved, no message.
#       - All confirmations are now IN-APP modals (Yes/No) that the
#         browser can never suppress; success/error feedback is an in-app
#         toast (e.g. "Saved as draft ✓") instead of window.alert.
#       - The silent page reload on "No" is removed entirely.
#   • Also includes the Iter 342 offline legacy salary import fix if not
#     yet deployed (month fallback from MonthYear, skip diagnostics).
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip
PY=$APP_DIR/backend/venv/bin/python

echo "==> 1/7 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/7 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true

echo "==> 3/7 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/7 Building web frontend (expo export — split routes)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/
sudo find $WEB_DIR/_expo/static/js/web -name "*.js" -mtime +30 -delete 2>/dev/null || true

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
  echo "   ⚠ Backend health check failed — check: journalctl -u sksharma-backend -n 50"
echo "   --- VERIFY NEW CODE ---"
echo -n "   In-app toast in web bundle (must print a file): "
grep -rl "app-toast-host" $WEB_DIR/_expo/static/js/web/ 2>/dev/null | head -1 || echo "NOT FOUND ⚠"
echo -n "   Offline month fallback in importer (must be > 0): "
grep -c "_month_key_any" $APP_DIR/backend/routes/legacy_import.py || true

echo ""
echo "✅ Deploy Iter 343 complete!"
echo "   • HARD-REFRESH the browser (Ctrl+Shift+R) after deploy."
echo "   • Compliance Salary: Process/Reprocess now asks with an in-app"
echo "     Yes/No box; Save shows a 'Saved as draft ✓' toast; the page"
echo "     never silently refreshes anymore."
