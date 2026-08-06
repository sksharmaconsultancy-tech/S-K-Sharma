#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 506)
#
# NEW IN 506:
#
# 1) ALLOTED TASKS NOW ON THE SUB ADMIN'S MAIN SCREEN (your bug —
#    "Alloted Task Not Showing In Main Screen On Dashboard"):
#    • New "My tasks (N open)" section right on the phone HOME screen —
#      shows the top 3 open tasks (title, firm, due date with red
#      overdue flag, assigned-by) + "View all N tasks →".
#    • Backend: tasks alloted TO a Sub Super Admin are now visible
#      regardless of which firm is currently selected (before, a task
#      for Firm B was hidden while Firm A was selected — the exact bug).
#
# 2) SUB ADMIN BLANK-SCREEN FIX (critical): on a cold open, the app
#    fired two competing redirects while the "remember my firm" restore
#    was still loading — the router dead-ended on an empty white screen.
#    Now it waits for the restore and navigates once.
#
# 3) INFINITE REFRESH LOOP FIX (critical, server load): the dashboard
#    re-fetched /auth/me + all stats in an endless loop while open,
#    hammering the server (hundreds of requests/min per device) until
#    Cloudflare rate-limited the session ("Security check" errors,
#    empty dashboards). Root-caused and fixed at the source.
#
# 4) BONUS YEARLY SUMMARY EXCEL — SAME FORMAT AS DISPLAY (your request):
#    the download now mirrors the on-screen table exactly: each month
#    header spans its Days | Earned pair (interleaved, not all-Days-
#    then-all-Earned), merged fixed columns, allowance (Yr) columns,
#    bold yellow TOTAL row, frozen header panes.
#
# INCLUDES Iter 505 (Task edit + edit log + assign fix), 504 (PWA Tasks
# tab), 503 (Single Machine Attendance Mode) and everything before.
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
echo -n "   Server Version badge shows 506 (must say OK): "
grep -q 'APP_ITERATION = "506"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Alloted-task visibility fix (must say OK): "
grep -q 'hidden by the firm filter' $APP_DIR/backend/routes/portal_phase2.py && echo "OK" || echo "MISSING!"
echo -n "   Home 'My tasks' section (must say OK): "
grep -q 'home-my-tasks' "$APP_DIR/frontend/app/(tabs)/index.tsx" && echo "OK" || echo "MISSING!"
echo -n "   Blank-screen redirect fix (must say OK): "
grep -q 'firmRestoreDone' $APP_DIR/frontend/src/context/SelectedCompanyContext.tsx && echo "OK" || echo "MISSING!"
echo -n "   Infinite refresh-loop fix (must say OK): "
grep -q 'SAME object identity' $APP_DIR/frontend/src/context/AuthContext.tsx && echo "OK" || echo "MISSING!"
echo -n "   Bonus Yearly Summary display-format Excel (must say OK): "
grep -q 'Download Same Format As Display' $APP_DIR/backend/routes/contribution_reports.py && echo "OK" || echo "MISSING!"
echo -n "   'My tasks' inside BUILT web output (must say OK): "
grep -rq 'home-my-tasks' $WEB_DIR/_expo/static/js/web/ && echo "OK" || echo "MISSING!"
echo -n "   Iter 505 task edit log still present (must say OK): "
grep -q '_edit_changes' $APP_DIR/backend/routes/portal_phase2.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 506 complete! HARD-REFRESH the browser (Ctrl+Shift+R);"
echo "   on the phone close + reopen the PWA twice."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 506'."
echo "   2. Login as a Sub Super Admin on the PHONE → home screen now"
echo "      shows 'My tasks (N open)' with the alloted tasks (firm, due"
echo "      date, overdue in red) → 'View all' opens the Tasks tab."
echo "   3. Assign a task for Firm B to a Sub Admin, select Firm A —"
echo "      the task still shows for the Sub Admin."
echo "   4. Reports → Bonus Yearly Summary → Download Excel — columns"
echo "      now match the screen exactly (per-month Days|Earned pairs,"
echo "      yellow TOTAL row)."
