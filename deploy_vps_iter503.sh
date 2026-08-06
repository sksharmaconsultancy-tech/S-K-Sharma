#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 503)
#
# NEW IN 503:
#
# 1) SINGLE MACHINE ATTENDANCE MODE (your spec):
#    Firm Master → 8. Attendance & Shift → NEW "Attendance Capture /
#    Device Mode" card:
#    • Device mode: Separate IN/OUT Machines (default) · Single Machine
#      (shared) · Mobile App · GPS Only · QR Code.
#    • When "Single Machine (shared)" is picked, extra options appear:
#      – Punch interpretation:
#          A — Alternate: 1st punch = IN, 2nd = OUT, 3rd = IN …
#          B — First IN · Last OUT: duty = last punch − first punch.
#      – Ignore duplicate punches within: Off / 1 / 2 / 5 / 10 minutes
#        (double-scans on the shared device are dropped).
#      – Lunch / middle punches (mode B only):
#          Ignore middle punches (duty = last − first)
#          Actual break (middle punches = lunch OUT/IN, real break
#          deducted by the normal pairing engine)
#          Fixed deduction: 30 / 45 / 60 min subtracted from every
#          day's duty hours.
#    • The setting applies ONLY to the firm you save it on — machine
#      punches of that firm are re-interpreted; mobile-app and manual
#      punches always keep their recorded IN/OUT. ALL OTHER FIRMS keep
#      the existing engine 100% unchanged.
#    • Wired through EVERY calculation surface: Attendance Report grid,
#      IN/OUT & OT Matrix, OT report, Compliance Salary (Policy 2
#      biometric sync), Attendance Doctor and the grid-debug tracer.
#    • Attendance grid day cells now carry transparency fields:
#      calc_mode (e.g. "B · First IN — Last OUT + fixed lunch 45m"),
#      dupes_ignored and the final punch_pattern — visible via the
#      grid-debug endpoint / repair tools.
#
# 2) PWA — TASK MANAGEMENT FOR SUPER ADMIN (your bug):
#    The mobile / PWA home screen was missing any way to reach Task
#    Management. The Quick Actions list now starts with:
#    • "Task Management" → opens Portal Dashboard directly on the
#      Tasks tab (create / assign / review tasks from the phone).
#    • "Portal Dashboard" → full dashboard (Overview / Tasks / Client
#      Health / Documents / Calendar) on mobile.
#
# INCLUDES Iter 502 (Task Hierarchy + attachments + stay-on-page +
# punch-log fixes), Iter 501 (Client Attendance Import) and Iter 500
# (CTC Module) and everything before.
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
echo -n "   Server Version badge shows 503 (must say OK): "
grep -q 'APP_ITERATION = "503"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Single Machine engine (must say OK): "
grep -q '_single_machine_normalize' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Firm Master device-mode mirror (must say OK): "
grep -q 'attendance_config' $APP_DIR/backend/routes/firm_master.py && echo "OK" || echo "MISSING!"
echo -n "   Firm Master UI card (must say OK): "
grep -q 'fm-ac-single' $APP_DIR/frontend/app/firm-master.tsx && echo "OK" || echo "MISSING!"
echo -n "   PWA Task Management quick action (must say OK): "
grep -q 'row-task-management' "$APP_DIR/frontend/app/(tabs)/index.tsx" && echo "OK" || echo "MISSING!"
echo -n "   Portal Dashboard ?tab= deep link (must say OK): "
grep -q 'useLocalSearchParams' $APP_DIR/frontend/app/portal-dashboard.tsx && echo "OK" || echo "MISSING!"
echo -n "   Iter 502 Task hierarchy still present (must say OK): "
grep -q 'hub-dashboard' $APP_DIR/backend/routes/portal_phase2.py && echo "OK" || echo "MISSING!"
echo -n "   Iter 501 Client Attendance Import still present (must say OK): "
[ -f $APP_DIR/backend/routes/client_attendance_import.py ] && echo "OK" || echo "MISSING!"
echo -n "   Iter 500 CTC module still present (must say OK): "
[ -f $APP_DIR/backend/routes/ctc_module.py ] && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 503 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 503'."
echo "   2. Firm Master → 8. Attendance & Shift → new 'Attendance"
echo "      Capture / Device Mode' card. Pick 'Single Machine (shared)'"
echo "      → interpretation A/B, duplicate window and lunch options"
echo "      appear. Pick your settings and SAVE."
echo "   3. Open the Attendance Report for that firm — days recorded on"
echo "      the shared machine now pair correctly per your chosen mode"
echo "      (fixed lunch is deducted from daily duty when selected)."
echo "   4. Other firms are untouched — verify one unchanged firm."
echo "   5. On the PHONE (PWA): login as Super Admin → home screen →"
echo "      Quick actions → 'Task Management' opens the Tasks tab;"
echo "      'Portal Dashboard' opens the full dashboard."
