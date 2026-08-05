#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 498)
#
# NEW IN 498 — ONE-SHOT PUNCH REPAIR (your report: "While updating punch
# on click on Employee Date we are updating both punch but system allow
# only one punch in one time — please allow us to rectify full attendance
# In time and Out time in single punch repair"):
#
#   • Tap any day cell on the Attendance Grid (IN/OUT report) → the
#     Repair Punches window now has a big blue button:
#        ⚡ Fix IN + OUT Together (one save)
#   • Enter the IN time AND the OUT time side by side → ONE "Save IN+OUT"
#     click repairs the whole day:
#        – existing IN / OUT punches are UPDATED to the new times
#        – missing IN / OUT punches are CREATED automatically
#   • OT PUNCH REPAIR TOO (your follow-up request): tap "Also repair OT
#     punch" inside the same form to enter OT In / OT Out — the 2nd
#     IN→OUT pair is fixed in the SAME single save (existing OT punches
#     pre-filled; missing ones created).
#   • Existing times are pre-filled so you only change what's wrong.
#   • NIGHT SHIFT aware: if the OUT time is earlier than the IN time the
#     OUT is automatically saved on the NEXT day (with a clear 🌙 note
#     before you save).
#   • You can also fill only ONE of the two fields — the other punch is
#     left untouched. Full audit trail preserved (reason required).
#   • The old Add IN / Add OUT / per-punch edit / delete buttons still
#     work exactly as before.
#
# INCLUDES Iter 497 (report engine phase 2+3 + screen-matching PDF) and
# everything before.
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
echo -n "   Server Version badge shows 498 (must say OK): "
grep -q 'APP_ITERATION = "498"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   One-shot IN+OUT repair (must say OK): "
grep -q 'saveBoth' $APP_DIR/frontend/src/components/PunchRepairModal.tsx && grep -q 'Fix IN + OUT Together' $APP_DIR/frontend/src/components/PunchRepairModal.tsx && echo "OK" || echo "MISSING!"
echo -n "   OT punch repair in the same save (must say OK): "
grep -q 'repair-otin-time' $APP_DIR/frontend/src/components/PunchRepairModal.tsx && echo "OK" || echo "MISSING!"
echo -n "   Night-shift OUT-next-day logic (must say OK): "
grep -q 'outIsNextDay' $APP_DIR/frontend/src/components/PunchRepairModal.tsx && echo "OK" || echo "MISSING!"
echo -n "   Iter 497 report engine + PDF still present (must say OK): "
grep -q 'reportKey="salary_register"' $APP_DIR/frontend/app/salary-register.tsx && [ -f $APP_DIR/backend/routes/report_export.py ] && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 498 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 498'."
echo "   2. Attendance Report (IN/OUT) → tap any employee's day cell →"
echo "      blue '⚡ Fix IN + OUT Together (one save)' button on top."
echo "   3. Enter IN 09:00 and OUT 18:15 → Save IN + OUT → BOTH punches"
echo "      are fixed in one go and the grid refreshes instantly."
echo "   4. Tap 'Also repair OT punch' in the same form → enter OT In /"
echo "      OT Out → all four punches saved together."
echo "   5. Try OUT 02:00 with IN 21:00 → the 🌙 note shows the OUT will"
echo "      be saved on the next day (night shift)."
