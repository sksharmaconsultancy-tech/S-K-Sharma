#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 551)
#
# ═══════════ WHAT'S NEW SINCE 550 (this deploy) ═══════════
#
# A. FORM 16 MODULE — PHASE 1 (user spec):
#    New menu: Payroll → Salary Process → "TDS · Form 16".
#    • Dashboard cards: employees with FY payroll, TDS applicable,
#      Form 16 Ready / Pending / Generated; FY selector (2024-25 /
#      2025-26 / 2026-27); employee search.
#    • AUTO DATA: consolidates finalized payroll April→March from the
#      Compliance Salary runs (fallback Actual Salary runs) — monthly
#      salary + monthly TDS, annual totals. Nothing re-entered.
#    • TAX CONFIGURATION MASTER (API): FY-wise NEW-regime slabs,
#      standard deduction (₹75,000), rebate 87A (≤12L → up to 60,000),
#      cess 4% — fully configurable, nothing hard-coded.
#    • READINESS CHECK: PAN missing/invalid + no-payroll are CRITICAL
#      (generation blocked); missing employer TAN is warned.
#    • EXTRA HEADS AT GENERATION TIME (user request): per-employee
#      "＋" button → add Other Income heads (adds to taxable) and
#      Deduction heads (reduces taxable) not present in the masters —
#      then generate & print.
#    • OUTPUT: statutory-style A4 PDF (Part A monthly salary/TDS
#      summary + Part B full tax computation), single download and
#      Bulk ZIP; generation history with version + audit log; role
#      restricted (Super/Sub/Company Admin).
#    Phase 2 (next): TDS-return reconciliation, TRACES Part A lock,
#    Employee Self-Service Form 16, email delivery, charts.
#
# B. SOFTWARE FEATURES LIST — SEPARATE PDF (user request):
#    User Manual screen now has an amber "Software Features List (PDF)"
#    button — downloads the full 130-feature module-wise catalogue as
#    a landscape A4 PDF (for the manual / website).
#
#    HOW TO CHECK: Payroll → Salary Process → TDS · Form 16 → pick FY
#    2025-26 → Select All Ready → Generate → download PDF/ZIP.
#    User Manual → "Software Features List (PDF)".
#
# Run ON THE VPS as root/sksharma:
#   wget -O deploy551.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy551.sh

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
echo -n "   Server badge is 551 (must say OK): "
grep -q 'APP_ITERATION = "551"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
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
echo -n "   Merged IN/OUT + OT sheet (must say OK): "
grep -q 'Iter 548' $APP_DIR/frontend/app/attendance-grid.tsx && echo "OK" || echo "MISSING!"
echo -n "   6-row Excel export (must say OK): "
grep -q 'Tot-Hrs' $APP_DIR/backend/utils/monthly_attendance.py && echo "OK" || echo "MISSING!"
echo -n "   6-line PDF day cell (must say OK): "
grep -q 'Iter 549' $APP_DIR/backend/utils/monthly_attendance_pdf.py && echo "OK" || echo "MISSING!"
echo -n "   +OT intra-pair display (must say OK): "
grep -q 'Iter 550' $APP_DIR/frontend/app/attendance-grid.tsx && echo "OK" || echo "MISSING!"
echo -n "   Form 16 backend (must say OK): "
[ -f $APP_DIR/backend/routes/form16.py ] && echo "OK" || echo "MISSING!"
echo -n "   Form 16 screen (must say OK): "
[ -f $APP_DIR/frontend/app/form16.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Features List PDF (must say OK): "
[ -f $APP_DIR/backend/routes/features_pdf.py ] && [ -f $APP_DIR/USER_MANUAL_FEATURES.md ] && echo "OK" || echo "MISSING!"
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
echo "══════════════ DONE (Iter 551) ══════════════"
echo "After deploy: hard-refresh the portal (Ctrl+Shift+R)."
echo "CHECK 1: Payroll → Salary Process → TDS · Form 16 → FY 2025-26."
echo "CHECK 2: User Manual → Software Features List (PDF) button."
