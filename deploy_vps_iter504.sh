#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 504)
#
# NEW IN 504 — PWA TASK MANAGEMENT, NOW IMPOSSIBLE TO MISS (your bug:
# "Still Not Showing Task Management Option in PWA of Super Admin"):
#
# 1) NEW "TASKS" TAB in the PWA bottom bar (admins only) — Task
#    Management is now ONE TAP away on every screen of the phone app.
# 2) Big "Tasks · Task Management" TILE at the very top of the mobile
#    home screen (first card, purple icon).
# 3) "Task Management" + "Portal Dashboard" quick actions (from 503)
#    remain in the Quick Actions list.
# 4) PWA CACHE FIX — root cause of "not showing" after deploy: on slow
#    connections the installed PWA served the CACHED OLD app shell
#    (service worker 3.5s network race). The service-worker cache
#    version is bumped (v4 → v5) so every phone auto-purges the stale
#    shell on next open and downloads the new one.
#
# INCLUDES Iter 503 (Single Machine Attendance Mode + first PWA task
# links), Iter 502 (Task Hierarchy + attachments), Iter 501 (Client
# Attendance Import), Iter 500 (CTC Module) and everything before.
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
# PWA service worker + manifests live in /public — copy them explicitly
# so the cache-version bump (v5) reaches every installed PWA.
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
echo -n "   Server Version badge shows 504 (must say OK): "
grep -q 'APP_ITERATION = "504"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   PWA Tasks bottom tab (must say OK): "
[ -f "$APP_DIR/frontend/app/(tabs)/tasks.tsx" ] && echo "OK" || echo "MISSING!"
echo -n "   Home Task Management tile (must say OK): "
grep -q 'bento-tasks' "$APP_DIR/frontend/app/(tabs)/index.tsx" && echo "OK" || echo "MISSING!"
echo -n "   Service-worker cache bumped to v5 (must say OK): "
grep -q 'sks-pwa-v5' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   Tasks tab in the BUILT web output (must say OK): "
grep -rq 'tasks-tab-screen' $WEB_DIR/_expo/static/js/web/ && echo "OK" || echo "MISSING!"
echo -n "   Iter 503 Single Machine engine still present (must say OK): "
grep -q '_single_machine_normalize' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 504 complete!"
echo ""
echo "   ON YOUR PHONE (important — this busts the old cached app):"
echo "   1. CLOSE the PWA fully (swipe it away from recent apps)."
echo "   2. Open it again, wait for it to load, close it once more,"
echo "      then open again. (First open downloads the new version in"
echo "      the background; second open runs it.)"
echo "   3. You should now see:"
echo "      • A 'Tasks' tab in the BOTTOM BAR."
echo "      • A big 'Tasks · Task Management' tile at the top of Home."
echo "      • 'Task Management' in Quick Actions."
echo "   If it STILL shows the old screen: uninstall the PWA icon and"
echo "   re-add it from the browser (Add to Home Screen) once."
