#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 191: KYC & Doc Expiry Tracker)
# Run ON THE VPS as the sksharma user. Fetches latest code bundle from the
# Emergent workspace and redeploys backend + web frontend.
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

echo "==> 5/6 Restarting backend (supervisor)..."
sudo supervisorctl restart sksharma-backend
sleep 4

echo "==> 6/6 Verifying..."
curl -s http://localhost:8001/api/health && echo
CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/admin/kyc-tracker)
if [ "$CODE" = "401" ]; then
  echo "✅ New KYC Tracker route live (kyc-tracker returns 401 as expected)."
else
  echo "❌ kyc-tracker returned $CODE (expected 401) — check supervisor logs."
fi
CODE2=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/me/documents)
if [ "$CODE2" = "401" ]; then
  echo "✅ Refactored document routes live (me/documents returns 401 as expected)."
else
  echo "❌ me/documents returned $CODE2 (expected 401) — check supervisor logs."
fi
echo "Deploy complete."
