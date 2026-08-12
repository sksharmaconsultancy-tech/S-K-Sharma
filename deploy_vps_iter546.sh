#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 546)
#
# ═══════════ WHAT'S NEW SINCE 545 (this deploy) ═══════════
#
# A. NIGHT-OT REPAIR FIX (user bug — VINIT LODI 08-Aug):
#    "OT punch not showing in OT IN/OUT" + "Repair Punch — OT Out
#     punch is not showing".
#
#    Root cause: the Repair Punches window loaded ONLY the tapped
#    date. A night/OT session ends the NEXT MORNING, so its OUT punch
#    lives on the next date and was INVISIBLE in the repair window —
#    admins then edited the wrong punch (e.g. "IN 20:00 → 08:00",
#    which kept kind IN), breaking the cross-day OT stitch and the
#    OT IN/OUT columns.
#
#    Fix: when a day ends with an UNPAIRED trailing IN, the repair
#    window now also shows the NEXT day's first morning punch
#    (before 12:00) with its real next-day date in amber:
#      • if it is the OT OUT — it prefills the "OT Out" field and
#        saves/pairs correctly (cross-midnight aware);
#      • if its IN/OUT direction is wrong (like VINIT's 08:00 punch
#        saved as IN) — the admin can now SEE it, tap the pencil and
#        flip IN → OUT in one step.
#
#    HOW TO REPAIR VINIT LODI (09-Aug) AFTER THIS DEPLOY:
#      Attendance Report → VINIT LODI → tap 09 Aug cell →
#      1. the 08:00 punch (patched earlier) → pencil → set kind = OUT
#         (it is the OT OUT of 08-Aug night OT);
#      2. the 20:00 punch → pencil → set kind = IN (it is the real
#         evening duty IN of 09-Aug).
#      Day 08 then shows Duty + OT (20:05 → 08:00), day 09 pairs with
#      the 10-Aug morning OUT, and OT IN/OUT columns fill in
#      Punch Approvals + In/Out & OT Matrix automatically.
#
# Run ON THE VPS as root/sksharma:
#   wget -O deploy546.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy546.sh

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "════════════════════════════════════════════════════════════"
echo "  STEP 0 — DIAGNOSTICS (send me this block if deploy fails)"
echo "════════════════════════════════════════════════════════════"
echo "--- Disk space ---"
df -h / | tail -1
echo "--- Memory + swap ---"
free -h
echo "--- Backend service ---"
sudo supervisorctl status sksharma-backend 2>/dev/null || systemctl status sksharma-backend --no-pager -l 2>/dev/null | head -5 || echo "(no backend service found by either name)"
echo "--- Backend health (localhost:8001) ---"
curl -s -m 5 http://localhost:8001/api/health && echo " <-- backend answers ✅" || echo "❌ BACKEND NOT ANSWERING"
echo "--- Nginx ---"
sudo nginx -t 2>&1 | tail -1
systemctl is-active nginx && echo "nginx active ✅" || echo "❌ nginx NOT active"
echo "--- Web folder ---"
ls -la $WEB_DIR/index.html 2>/dev/null || echo "❌ $WEB_DIR/index.html MISSING"
echo "════════════════════════════════════════════════════════════"
echo ""

echo "==> 1/9 Freeing disk space (safe cache cleanup)..."
rm -rf $APP_DIR/frontend/.metro-cache $APP_DIR/frontend/.expo /tmp/metro-* /tmp/haste-* 2>/dev/null
npm cache clean --force >/dev/null 2>&1 || true
yarn cache clean >/dev/null 2>&1 || true
AVAIL_MB=$(df -m / | tail -1 | awk '{print $4}')
echo "   Free disk now: ${AVAIL_MB} MB"
if [ "$AVAIL_MB" -lt 1500 ]; then
  echo "   ⚠ Less than 1.5 GB free — cleaning apt + journal too..."
  sudo apt-get clean 2>/dev/null || true
  sudo journalctl --vacuum-size=100M >/dev/null 2>&1 || true
  df -m / | tail -1 | awk '{print "   Free disk now: "$4" MB"}'
fi

echo "==> 2/9 Ensuring swap (prevents build OOM-kill)..."
SWAP_KB=$(grep SwapTotal /proc/meminfo | awk '{print $2}')
if [ "$SWAP_KB" -lt 1000000 ]; then
  echo "   No/low swap — creating 2 GB swapfile..."
  sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile \
    && echo "   Swap ON ✅" || echo "   (swap setup failed — continuing)"
  grep -q "/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
else
  echo "   Swap already present ✅"
fi

echo "==> 3/9 Downloading latest code bundle (~10 MB, retries enabled)..."
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

echo "==> 4/9 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR || { echo "❌ Extract failed (disk full?) — aborting."; exit 1; }
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 5/9 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP install openpyxl Pillow -q || true

echo "==> 6/9 Restarting backend FIRST (portal comes back before the build)..."
sudo supervisorctl stop sksharma-backend 2>/dev/null || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend 2>/dev/null || sudo systemctl restart sksharma-backend 2>/dev/null || true
HEALTH=""
for i in $(seq 1 12); do
  sleep 5
  HEALTH=$(curl -s -m 8 http://localhost:8001/api/health)
  [ -n "$HEALTH" ] && break
  echo "   waiting for backend... (${i}0s)"
done
if [ -n "$HEALTH" ]; then
  echo "   Backend healthy ✅  ($HEALTH)"
else
  echo "   ❌ BACKEND STILL NOT ANSWERING. Last 30 log lines:"
  sudo tail -30 /var/log/supervisor/sksharma-backend*.log 2>/dev/null || sudo journalctl -u sksharma-backend -n 30 --no-pager 2>/dev/null
  echo "   ── Send me the lines above. Continuing with the web build anyway."
fi

echo "==> 7/9 Building web frontend (with OOM protection)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
export NODE_OPTIONS="--max-old-space-size=3072"
rm -rf dist
if npx expo export -p web 2>&1 | tail -15; then true; fi
if [ ! -f dist/index.html ] || [ ! -d dist/_expo/static/js/web ]; then
  echo "❌ WEB BUILD FAILED — the current live portal folder was NOT touched."
  echo "   Re-run this script once; if it fails again send me the build error above."
  exit 1
fi
echo "   Build OK ✅ ($(du -sh dist | cut -f1))"

echo "==> 8/9 Publishing new build (with rollback safety)..."
sudo mkdir -p $WEB_DIR
sudo rm -rf ${WEB_DIR}.prev
sudo cp -r $WEB_DIR ${WEB_DIR}.prev 2>/dev/null || true
sudo find $WEB_DIR -mindepth 1 -maxdepth 1 ! -name '.well-known' ! -name '_expo' -exec rm -rf {} +
sudo cp -r dist/* $WEB_DIR/
sudo cp public/sw.js $WEB_DIR/sw.js 2>/dev/null || true
sudo find $WEB_DIR/_expo -type f -mtime +45 -delete 2>/dev/null || true
sudo nginx -t && sudo systemctl reload nginx

echo "==> 9/9 Verification..."
echo -n "   Server badge is 546 (must say OK): "
grep -q 'APP_ITERATION = "546"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   OT punch fix (Iter 544, must say OK): "
grep -q 'Iter 544' $APP_DIR/frontend/src/components/PunchRepairModal.tsx && echo "OK" || echo "MISSING!"
echo -n "   Punch policy module (must say OK): "
[ -f $APP_DIR/backend/utils/punch_policy.py ] && echo "OK" || echo "MISSING!"
echo -n "   Multi-punch report API (must say OK): "
[ -f $APP_DIR/backend/routes/punch_policy_report.py ] && echo "OK" || echo "MISSING!"
echo -n "   Multi-punch report screen (must say OK): "
[ -f $APP_DIR/frontend/app/multi-punch-report.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Policy UI punch section (must say OK): "
grep -q 'ATTENDANCE PUNCH POLICY' $APP_DIR/frontend/app/attendance-policy.tsx && echo "OK" || echo "MISSING!"
echo -n "   Night-OT repair window fix (must say OK): "
grep -q 'Iter 546' $APP_DIR/frontend/src/components/PunchRepairModal.tsx && echo "OK" || echo "MISSING!"
echo -n "   App punch enforcement (must say OK): "
grep -q 'resolve_punch_policy' $APP_DIR/backend/routes/attendance_core.py && echo "OK" || echo "MISSING!"
echo -n "   Machine punch enforcement (must say OK): "
grep -q 'resolve_punch_policy' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   Web build published (must say OK): "
[ -f $WEB_DIR/index.html ] && echo "OK" || echo "MISSING!"
echo -n "   Backend /api/health: "
curl -s -m 5 http://localhost:8001/api/health || echo "❌ NOT ANSWERING"
echo ""
echo -n "   Portal responds through nginx: "
CODE=$(curl -s -k -L -m 10 -o /dev/null -w "%{http_code}" http://localhost/ )
if [ "$CODE" = "200" ]; then
  echo "HTTP $CODE ✅"
else
  echo "HTTP $CODE ❌ — previous build kept at ${WEB_DIR}.prev"
fi
echo ""
echo "══════════════ DONE (Iter 546) ══════════════"
echo "After deploy: hard-refresh the portal (Ctrl+Shift+R)."
echo "NIGHT-OT FIX CHECK: Attendance Report → VINIT LODI → tap 08 Aug —"
echo "the repair window must now also show the NEXT-morning punch"
echo "(amber 09-08 date). Repair VINIT: on 09 Aug set the 08:00 punch"
echo "kind = OUT and the 20:00 punch kind = IN — OT then shows"
echo "everywhere (grid, OT IN/OUT, Punch Approvals)."
