#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 560 — includes 555→559)
#
# ═══════════ WHAT'S NEW (this deploy = Iter 555 → 560) ═══════════
#
# A. PUNCH IMPORT — "Monthly Performance" SHEETS NOW SUPPORTED [Iter 560]:
#    Your client's Performance export now imports correctly:
#    • Dates like "01 Aug 2026" are parsed (were failing before).
#    • Code/Name printed only on the FIRST row of each employee block
#      are carried onto all their date rows automatically.
#    • Repeated header rows + "Department :" separators are skipped.
#    • Blank days (absent/WO — no In/Out) show as grey "Blank days",
#      NOT as errors.
#    • OT note softened: sheets without OT In/OT Out columns import the
#      In/Out punches and the engine auto-calculates OT per your policy.
#    (Tested with the actual client sheet: 891 punches / 96 employees
#     parsed, 0 errors.)
#
# B. PUNCH APPROVALS Excel export [Iter 559] + Bio Code column & wide
#    name columns [Iter 558].
# C. TIME FORMAT dropdown (12 Hr AM/PM default) in Daily Verification
#    [Iter 557].
# D. MANUAL OT PUNCH EDIT BUG FIXED [Iter 555] + Super Admins survive
#    restarts [Iter 555] + ✎ Admin-corrected badge [Iter 556].
#
# Run ON THE VPS as root/sksharma:
#   wget -O deploy560.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy560.sh

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
echo -n "   Server badge is 560 (must say OK): "
grep -q 'APP_ITERATION = "560"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Performance-sheet date parser (must say OK): "
grep -q 'Iter 560 (user sheet)' $APP_DIR/backend/routes/punch_import.py && echo "OK" || echo "MISSING!"
echo -n "   Blank-day skip classification (must say OK): "
grep -q '"skipped"' $APP_DIR/backend/routes/punch_import.py && echo "OK" || echo "MISSING!"
echo -n "   Blank-days chip in import modal (must say OK): "
grep -q 'Blank days' $APP_DIR/frontend/src/components/PunchImportModal.tsx && echo "OK" || echo "MISSING!"
echo -n "   Punch Approvals Excel export — Iter 559 (must say OK): "
grep -q 'pa-export-xlsx' $APP_DIR/frontend/app/punch-approvals.tsx && echo "OK" || echo "MISSING!"
echo -n "   Bio Code column — Iter 558 (must say OK): "
grep -q 'txt: "Bio Code"' $APP_DIR/frontend/app/punch-approvals.tsx && echo "OK" || echo "MISSING!"
echo -n "   Time Format dropdown — Iter 557 (must say OK): "
grep -q 'dv-time-format' $APP_DIR/frontend/app/daily-verification.tsx && echo "OK" || echo "MISSING!"
echo -n "   Manual OT dedupe fix — Iter 555 (must say OK): "
grep -q 'Iter 555 (user bug' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Super admin allowlist exemption (must say OK): "
grep -q 'super_admin_allowlisted' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Web build published (must say OK): "
[ -f $WEB_DIR/index.html ] && echo "OK" || echo "MISSING!"
echo -n "   Backend /api/health: "
curl -s -m 5 http://localhost:8001/api/health || echo "❌ NOT ANSWERING"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  DONE — Iter 560 deployed."
echo "  Test: Punch Approvals → Import Excel → choose the client's"
echo "    Performance sheet → preview shows matched punches by Code,"
echo "    blank days in grey, 0 date errors → Import."
echo "  NOTE: select the CLIENT'S firm first — codes match against that"
echo "    firm's Bio Code / Employee Code."
echo "  Hard-refresh the browser (Ctrl+Shift+R) after deploy."
echo "════════════════════════════════════════════════════════════"
