#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script
# Iter 193 (RBAC Roles & Permissions + Approval Workflows)
# + Iter 194 (Statutory Registration: ESIC IP Part B + EPF UAN automation,
#   ESIC monthly salary-run alerts, Employee-Master button linking)
# + Iter 195 (Enterprise Process Command Center on Compliance / Actual /
#   Arrear salary process pages — KPI cards, workflow stepper, live
#   validation panel, sticky totals footer)
# Run ON THE VPS as the sksharma user.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/7 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true

echo "==> 3/7 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 3b/7 Installing Playwright Chromium for portal RPA (ESIC/EPFO automation)..."
PYBIN=$APP_DIR/backend/venv/bin/python
$PYBIN -m playwright install-deps chromium || true
$PYBIN -m playwright install chromium || echo "   (Chromium install failed — RPA jobs will fall to manual mode)"
grep -q "^RPA_WORKER_ENABLED=" $APP_DIR/backend/.env || echo "RPA_WORKER_ENABLED=1" >> $APP_DIR/backend/.env
sed -i 's/^RPA_WORKER_ENABLED=0/RPA_WORKER_ENABLED=1/' $APP_DIR/backend/.env

echo "==> 4/7 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
sudo rm -rf $WEB_DIR/*
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/7 Stopping backend + killing any orphaned process on port 8001..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2

echo "==> 6/7 Starting backend (supervisor)..."
sudo supervisorctl start sksharma-backend
sleep 4

echo "==> 7/7 Verifying..."
curl -s http://localhost:8001/api/health && echo
check() {
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001$1")
  if [ "$CODE" = "401" ]; then
    echo "✅ $2 live ($1 returns 401 as expected)."
  else
    echo "❌ $1 returned $CODE (expected 401) — check supervisor logs."
  fi
}
check "/api/admin/company-roles" "Iter 193 RBAC roles route"
check "/api/admin/approval-workflows" "Iter 193 approval workflow route"
check "/api/admin/statutory/esic/dashboard" "Iter 194 Statutory Registration route"
check "/api/admin/statutory/esic/alerts" "Iter 194 ESIC alerts route"
check "/api/admin/salary-process/readiness" "Iter 195 Process Command Center route"
echo
echo "Deploy complete."
echo "REMINDER: on your phone/PC, close and reopen the PWA TWICE (or clear"
echo "site data) so the service worker picks up the new build."
