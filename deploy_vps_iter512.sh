#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 512) — VENDOR SDK DIRECT-PULL CHANNEL
#
# WHY 512: NEW FEATURE — VENDOR SDK DIRECT-PULL CHANNEL (your request).
# The existing ADMS/iClock push connectivity is 100% UNCHANGED — this is
# purely ADDITIVE:
#
#   • Plug-in SDK adapter framework (backend/sdk_adapters/) — adding a
#     vendor later = dropping one file in, zero core changes.
#   • WORKING NOW (real server→device pull over TCP 4370):
#       ZKTeco Standalone SDK, eSSL Legacy, FingerTec, Ronald Jack,
#       BioMax, Realtime T&A (all speak the ZK standalone protocol).
#   • PLUG-IN SLOTS visible in the vendor list (adapter pending):
#       Suprema, Nitgen, Virdi, Anviz, BioEnable, Matrix Legacy,
#       Hikvision, Dahua.
#   • Devices get a Connection Mode: "Push (ADMS)" — default, unchanged —
#     or "Direct (SDK Pull)" with Device IP, Port, Comm Key fields.
#   • Per device: "Test connection" (live device info) and "Pull punches"
#     buttons + optional AUTO-PULL every N minutes (server-side scheduler).
#   • Pulled punches go through the SAME pipeline as ADMS pushes: bio_code
#     matching, IN/OUT alternation, 5-min duplicate rule, contractor
#     gates — every report works identically.
#   • Device Sync dashboard shows SDK-pull machines with last-pull status.
#   • Requires the new `pyzk` python package (installed by this script via
#     requirements.txt).
#
# NOTE for direct pull: the machine must be REACHABLE from the VPS —
# port-forward the device port (usually 4370) on the site router, or use
# a static/DDNS IP. The UI shows this hint too.
#
# Also includes Iter 511 (PWA blank-page self-heal) and Iter 510
# (deploy diagnostics + rollback-safe publish).
#
# Run ON THE VPS as root/sksharma:
#   wget -O deploy512.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy512.sh

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
echo "--- Backend last 25 log lines ---"
sudo tail -25 /var/log/supervisor/sksharma-backend*.log 2>/dev/null || sudo journalctl -u sksharma-backend -n 25 --no-pager 2>/dev/null || echo "(no backend logs found)"
echo "--- Backend health (localhost:8001) ---"
curl -s -m 5 http://localhost:8001/api/health && echo " <-- backend answers ✅" || echo "❌ BACKEND NOT ANSWERING — this is why the portal won't open"
echo "--- Nginx ---"
sudo nginx -t 2>&1 | tail -1
systemctl is-active nginx && echo "nginx active ✅" || echo "❌ nginx NOT active"
echo "--- Web folder ---"
ls -la $WEB_DIR/index.html 2>/dev/null || echo "❌ $WEB_DIR/index.html MISSING — broken previous deploy"
ls $WEB_DIR/_expo/static/js/web/ 2>/dev/null | head -3 || echo "❌ built JS bundles MISSING"
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
    && echo "   Swap ON ✅" || echo "   (swap setup failed — continuing, build may still work)"
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
$PIP install openpyxl -q || true

echo "==> 6/9 Restarting backend FIRST (portal comes back before the build)..."
sudo supervisorctl stop sksharma-backend 2>/dev/null || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend 2>/dev/null || sudo systemctl restart sksharma-backend 2>/dev/null || true
sleep 4
HEALTH=$(curl -s -m 8 http://localhost:8001/api/health)
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
  echo "❌ WEB BUILD FAILED — the current live portal folder was NOT touched,"
  echo "   so whatever was working before is still being served."
  echo "   Re-run this script once; if it fails again send me the build error above."
  exit 1
fi
echo "   Build OK ✅ ($(du -sh dist | cut -f1))"

echo "==> 8/9 Publishing new build (with rollback safety)..."
sudo mkdir -p $WEB_DIR
sudo rm -rf ${WEB_DIR}.prev
sudo cp -r $WEB_DIR ${WEB_DIR}.prev 2>/dev/null || true
# clean publish: remove old hashed bundles so the folder can't mix versions
sudo find $WEB_DIR -mindepth 1 -maxdepth 1 ! -name '.well-known' -exec rm -rf {} +
sudo cp -r dist/* $WEB_DIR/
sudo cp public/sw.js $WEB_DIR/sw.js 2>/dev/null || true
sudo nginx -t && sudo systemctl reload nginx

echo "==> 9/9 Verification..."
echo -n "   Server badge is 512 (must say OK): "
grep -q 'APP_ITERATION = "512"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   PWA cache bumped to v7 (must say OK): "
grep -q 'sks-pwa-v7' $WEB_DIR/sw.js && echo "OK" || echo "MISSING!"
echo -n "   Blank-page self-heal in built HTML (must say OK): "
grep -q 'sks-selfheal-count' $WEB_DIR/index.html && echo "OK" || echo "MISSING!"
echo -n "   SDK adapter framework (must say OK): "
[ -f $APP_DIR/backend/sdk_adapters/zk_family.py ] && echo "OK" || echo "MISSING!"
echo -n "   SDK pull endpoints (must say OK): "
grep -q 'sdk_auto_pull_loop' $APP_DIR/backend/routes/biometric_sdk.py && echo "OK" || echo "MISSING!"
echo -n "   pyzk installed (must say OK): "
$APP_DIR/backend/venv/bin/python -c "import zk" 2>/dev/null && echo "OK" || echo "MISSING! run: $APP_DIR/backend/venv/bin/pip install pyzk"
echo -n "   SDK UI in built web output (must say OK): "
grep -rq 'd-connmode-sdk' $WEB_DIR/_expo/static/js/web/ && echo "OK" || echo "MISSING!"
echo -n "   Web build published (must say OK): "
[ -f $WEB_DIR/index.html ] && echo "OK" || echo "MISSING!"
echo -n "   Backend /api/health: "
curl -s -m 5 http://localhost:8001/api/health || echo "❌ NOT ANSWERING"
echo ""
echo -n "   Portal responds through nginx: "
CODE=$(curl -s -m 8 -o /dev/null -w "%{http_code}" http://localhost/ )
echo "HTTP $CODE $( [ "$CODE" = "200" ] && echo '✅' || echo '❌' )"
echo ""
echo "✅ Deploy Iter 512 complete!"
echo ""
echo "   ON EACH DEVICE (important — clears the stuck screen):"
echo "   • Desktop browser: hard-refresh once (Ctrl+Shift+R)."
echo "   • Phone PWA: close the app fully (swipe away) and reopen TWICE."
echo "     The new v6 service worker auto-deletes the old cached shell."
echo ""
echo "   VERIFY: footer badge must read 'Server Iter 512'."
echo "   If the portal STILL does not open, run this script again and send"
echo "   me the whole 'STEP 0 — DIAGNOSTICS' block from the top."
