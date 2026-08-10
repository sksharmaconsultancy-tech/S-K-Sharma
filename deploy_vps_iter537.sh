#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 537)
#
# ═══════════════ WHAT'S NEW SINCE 532 (this deploy) ═══════════════
#
# A. MONTHLY PAYROLL REPORT (user request, Iter 537):
#    1. PERFORMANCE FIX — opening the report no longer hangs/slows:
#       • typing in Search / Month fired one heavy report computation
#         per KEYSTROKE → now debounced (600 ms) with stale-response
#         guard, so only the final query hits the server.
#       • the ~8,000-cell grid re-rendered on every keystroke → now
#         memoised, it re-renders only when the data changes.
#    3. MONTH SELECTOR now defaults to the LAST salary-FINALIZED
#       month (never the current month) — resolved live per firm.
#    2. DAY CELLS show HOURS per the firm's ATTENDANCE POLICY instead
#       of P/A codes: "8+4" = Duty HRS + OT HRS (when the policy has an
#       OT threshold) or plain duty hours otherwise. Absent = "-",
#       WO/HO/CL/PL/EL/SL/ESIC codes stay. Legend + Excel + PDF match.
#
# B. ATTENDANCE FIX (user report, Iter 537): day cells 1-31 now come
#    STRAIGHT from the firm's Attendance-Policy engine — Duty HRS
#    (capped at the policy full-day hours) + OT HRS beyond the policy
#    threshold, e.g. 11 worked hrs @ 8-hr policy = "8+3". Previously
#    firms without a specific policy field saw raw total hours ("11").
#
# C. MONTH STEPPER (Iter 537): small ‹ › buttons beside the month box
#    on the Monthly Payroll Report jump between the months that HAVE a
#    salary run (e.g. Mar → Jun → Jul), skipping empty months.
#
# C. EMPLOYEE MASTER — ACTUAL SALARY simplified (user request, 536):
#    the "Allowances — Actual Salary" and "Deductions — Actual Salary"
#    blocks were REMOVED. Actual Salary keeps ONLY: Basic Salary,
#    Salary 1 + Days 1, Salary 2 + Days 2, Salary 3 + Days 3.
#    Saving an employee clears any previously stored actual-salary
#    allowance/deduction heads. Compliance Salary blocks unchanged.
#
# D. USER MANUAL (user requests, Iter 533/534):
#    1. TWO NEW SECTIONS with real screenshots — "4. Add New Firm
#       (Firm Master Setup)" and "6. Add New Employee" (25 pages now).
#    2. Cover: "Software Version" removed; Product By + Prepared By
#       (Ankit Sharma) moved to the BOTTOM of the cover; punch line
#       "Your Satisfaction is our First Ambition" placed in the PAGE
#       CENTRE of the cover and centred in every page footer.
#
# Run ON THE VPS as root/sksharma:
#   wget -O deploy537.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy537.sh

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
echo -n "   Server badge is 532 (must say OK): "
grep -q 'APP_ITERATION = "537"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   User Manual API + screen (must say OK): "
[ -f $APP_DIR/backend/routes/user_manual.py ] && [ -f $APP_DIR/frontend/app/user-manual.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Corrected manual screenshots bundled (must say 23): "
ls $APP_DIR/backend/assets/manual/*.png 2>/dev/null | wc -l
echo -n "   NEW Add Firm / Add Employee screenshots (must say OK): "
[ -f $APP_DIR/backend/assets/manual/firm_add.png ] && [ -f $APP_DIR/backend/assets/manual/employee_add.png ] && echo "OK" || echo "MISSING!"
echo -n "   Monthly Payroll day cells = HRS per policy (must say OK): "
grep -q 'att_mode' $APP_DIR/backend/routes/monthly_payroll_report.py && echo "OK" || echo "MISSING!"
echo -n "   Monthly Payroll debounce perf fix (must say OK): "
grep -q 'debounced' $APP_DIR/frontend/app/monthly-payroll-report.tsx || grep -q 'DEBOUNCE' $APP_DIR/frontend/app/monthly-payroll-report.tsx && echo "OK" || echo "MISSING!"
echo -n "   Cover shows 'Prepared By Ankit Sharma' (must say OK): "
grep -q 'Ankit Sharma' $APP_DIR/backend/routes/user_manual.py && echo "OK" || echo "MISSING!"
echo -n "   Footer punch line present (must say OK): "
grep -q 'Your Satisfaction is our First Ambition' $APP_DIR/backend/routes/user_manual.py && echo "OK" || echo "MISSING!"
echo -n "   What's New page removed (must say OK): "
grep -q "What's New — Recent Payroll Updates" $APP_DIR/backend/routes/user_manual.py && echo "STILL PRESENT!" || echo "OK"
echo -n "   Refresh-screenshots button removed (must say OK): "
grep -q "Re-capturing screenshots" $APP_DIR/frontend/app/user-manual.tsx && echo "STILL PRESENT!" || echo "OK"
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
echo "══════════════ DONE (Iter 537) ══════════════"
echo "After deploy: hard-refresh the portal (Ctrl+Shift+R), open"
echo "Administration → User Manual (PDF) → Generate & Open PDF and"
echo "verify: correct screenshots under each heading, new cover page,"
echo "punch line in every footer, no What's New page, no Refresh button."
