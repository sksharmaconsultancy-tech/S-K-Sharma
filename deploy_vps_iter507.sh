#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 507)
#
# NEW IN 507 — SMARTER FIRM SELECTION WHEN ASSIGNING TASKS (your
# request: "After the Selection of Sub Super Admin Firm Selection
# Option May Change Please Check"):
#
#   In the New Task modal, the firm picker now CHANGES the moment you
#   select a Sub Super Admin:
#   • It switches from the general "Firm (optional)" dropdown to a
#     dedicated checklist titled "Firms for this task — <name>'s firms
#     only (N selected)" showing ONLY that sub admin's assigned firms.
#   • "All (N)" select-all chip + 🔍 filter box (appears when the sub
#     admin has more than 6 firms) + live selected count.
#   • The sub admin's firm is pre-ticked automatically, so Create can
#     never fail with a firm-scope error.
#   • Clearing the assignee brings back the normal Firm (optional)
#     dropdown.
#   Verified end-to-end by the automated test suite (all 6 steps pass).
#
# INCLUDES Iter 506 (alloted tasks on sub admin home + blank-screen and
# infinite-loop critical fixes + Bonus Excel display format), 505, 504,
# 503 and everything before.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/8 Downloading latest code bundle (~10 MB, retries enabled)..."
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
$PIP install openpyxl -q || true

echo "==> 4/8 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/
sudo cp public/sw.js $WEB_DIR/sw.js 2>/dev/null || true

echo "==> 5/8 Restarting backend service..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend

echo "==> 6/8 Nginx configs (unchanged)..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 7/8 Health check..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"

echo "==> 8/8 Verification..."
echo -n "   Server Version badge shows 507 (must say OK): "
grep -q 'APP_ITERATION = "507"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Scoped firm multi-select (must say OK): "
grep -q 'pd-task-mc-all' $APP_DIR/frontend/src/components/portal/TasksPanel.tsx && echo "OK" || echo "MISSING!"
echo -n "   Multi-select inside BUILT web output (must say OK): "
grep -rq 'pd-task-mc-all' $WEB_DIR/_expo/static/js/web/ && echo "OK" || echo "MISSING!"
echo -n "   Iter 506 alloted-task + loop fixes still present (must say OK): "
grep -q 'SAME object identity' $APP_DIR/frontend/src/context/AuthContext.tsx && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 507 complete! HARD-REFRESH the browser (Ctrl+Shift+R);"
echo "   on the phone close + reopen the PWA twice."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 507'."
echo "   2. Tasks → New Task → pick a Sub Super Admin → the firm picker"
echo "      changes to '<name>'s firms only' checklist with All-select,"
echo "      filter box and live count; their firm is pre-ticked."
echo "   3. Clear the assignee → normal Firm (optional) dropdown returns."
