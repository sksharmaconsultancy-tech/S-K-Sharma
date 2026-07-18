#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 197)
# Ships: Test page reworked — NO browser tab. It now offers "Automated
# Chrome Login": a self-updating PC runner (Selenium + auto ChromeDriver)
# that opens its OWN controlled Chrome window, fills ESIC/EPFO User ID +
# Password (fetched live) and reads the captcha via AI. Also a Chrome
# extension option. New backend: routes/portal_extension.py
# (token-gated creds + captcha solve + runner/extension zip generators).
# Run ON THE VPS as the sksharma user.
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

echo "==> 3/6 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/6 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
sudo rm -rf $WEB_DIR/*
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/6 Restarting backend..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 4

echo "==> 6/6 Verifying new automated-login endpoints..."
curl -s http://localhost:8001/api/health && echo
check() {
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001$1")
  if [ "$CODE" = "$2" ]; then
    echo "✅ $3 ($1 -> $CODE)."
  else
    echo "❌ $1 returned $CODE (expected $2) — check supervisor logs."
  fi
}
# runner/extension downloads require admin auth -> 401 without a token.
check "/api/admin/portal-automation/runner-download?api_base=https://x.y" "401" "PC runner download route"
check "/api/admin/portal-automation/extension-download?api_base=https://x.y" "401" "Chrome extension download route"
# token-gated creds -> 401 with an invalid token.
check "/api/portal-ext/creds?token=bad&portal=esic" "401" "Extension creds route"
echo
echo "Deploy complete."
echo "REMINDER: on your phone/PC, close and reopen the PWA TWICE (or clear"
echo "site data) so the service worker picks up the new build — otherwise you"
echo "will keep seeing the OLD 'Open in New Tab' screen."
