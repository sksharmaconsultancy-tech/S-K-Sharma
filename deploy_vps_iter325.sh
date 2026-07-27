#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 325)
# Ships (everything since deploy 314):
#   • RPA MAX SPEED — all human-pace delays removed; FAST is the only speed
#   • MANUAL CONTROL — click with your mouse + type with your keyboard
#     directly on the live portal view (works while running or paused)
#   • FULL SCREEN button on the live portal view
#   • EPFO: dashboard "Employee Enrollment Campaign" warning auto-OK
#   • ESIC: Employer Login URL flow + Angular-safe ID/Password typing
#   • PC Runner v5 (mandatory firm selection)
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip
PY=$APP_DIR/backend/venv/bin/python

echo "==> 1/8 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

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
$PIP show qrcode >/dev/null 2>&1 || $PIP install qrcode -q
$PIP show emergentintegrations >/dev/null 2>&1 || \
  $PIP install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q

echo "==> 4/8 Google Chrome + Playwright browsers (RPA engine)..."
if ! command -v google-chrome-stable >/dev/null 2>&1 && [ ! -x /opt/google/chrome/chrome ]; then
  echo "   Installing Google Chrome stable..."
  wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  sudo apt-get install -y /tmp/chrome.deb >/dev/null 2>&1 || sudo dpkg -i /tmp/chrome.deb || \
    echo "   (Chrome install failed — RPA will fall back to bundled Chromium)"
else
  echo "   Google Chrome already installed ✅"
fi
$PIP show playwright >/dev/null 2>&1 || $PIP install playwright -q
$PY -m playwright install chromium >/dev/null 2>&1 || echo "   (chromium download skipped)"
sudo $PY -m playwright install-deps chromium >/dev/null 2>&1 || true

echo "==> 5/8 Building web frontend (expo export — split routes)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/
sudo find $WEB_DIR/_expo/static/js/web -name "*.js" -mtime +30 -delete 2>/dev/null || true

echo "==> 6/8 Precompressing assets (gzip -9)..."
sudo find $WEB_DIR -type f \( -name "*.js" -o -name "*.css" -o -name "*.html" -o -name "*.json" -o -name "*.svg" -o -name "*.ttf" \) \
  -exec gzip -9 -kf {} \;

echo "==> 7/8 nginx gzip check (idempotent)..."
SITE_CONF=$(grep -rl "root $WEB_DIR" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | head -1)
if [ -n "$SITE_CONF" ] && ! grep -q "sks-gzip-fix" "$SITE_CONF"; then
  sudo cp "$SITE_CONF" "$SITE_CONF.bak-gzip"
  sudo sed -i "0,\|root $WEB_DIR;|s||root $WEB_DIR;\n    # sks-gzip-fix — serve precompressed assets + on-the-fly gzip\n    gzip on;\n    gzip_static on;\n    gzip_vary on;\n    gzip_comp_level 6;\n    gzip_min_length 1024;\n    gzip_proxied any;\n    gzip_types text/plain text/css application/json application/javascript text/javascript application/xml image/svg+xml font/ttf;|" "$SITE_CONF"
  if sudo nginx -t 2>/dev/null; then sudo systemctl reload nginx; echo "   nginx gzip enabled ✅"
  else sudo mv "$SITE_CONF.bak-gzip" "$SITE_CONF"; echo "   nginx patch skipped (config test failed)"; fi
else
  echo "   nginx gzip already configured — skipped"
fi

echo "==> 8/8 Restarting backend + verifying..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 5
curl -s http://localhost:8001/api/health && echo
for EP in "/api/rpa/catalog" "/api/rpa/settings" "/api/rpa/session/x/interact"; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001$EP")
  echo "   $EP → HTTP $CODE (401/400/403/405 = alive, auth required)"
done

echo
echo "🎉 Deploy 325 complete."
echo
echo "WHAT'S NEW SINCE DEPLOY 320:"
echo
echo "📊 ATTENDANCE"
echo "  • Attendance Report (Grid) + Attendance Sheet + all XLSX/PDF exports"
echo "    now show ACTIVE employees only (mid-month leavers still included)."
echo "  • 'Attendance Master Sheet' added to the sidebar (Attendance & Shift)"
echo "    — sheet now carries Designation + Employee Group so it imports"
echo "    straight into Salary Compliance / Salary Actual."
echo
echo "🧾 COMPLIANCE SALARY REGISTER"
echo "  • Format 1: new shaded MASTER SALARY & ALLOWANCES band, 15 mm rows,"
echo "    centred whole-rupee figures (no .00), wider signature column."
echo "  • Format 2: UAN No. / EPF No. / ESIC No. columns, no .00, no blank"
echo "    last page."
echo "  • NEW: PDF Sort by (Name/Code/Designation/Department) + Group by"
echo "    (Employee Group/Department/Designation) with per-group SUB-TOTALS"
echo "    — selectors on the Compliance Salary run screen, both formats."
echo "  • Signature block right-aligned on the summary page."
echo
echo "🏢 FIRMS"
echo "  • List of Firms → full Firm Master data in an Excel-style grid,"
echo "    tap-any-cell-to-copy + 'Export Excel' download."
echo "  • Firms ID & Password → Excel-sheet view (S.No, Firm, City, PF Code,"
echo "    PF Login/Password, ESIC Code, ESIC Login/Password), copy per cell,"
echo "    show/hide passwords."
echo
echo "👥 EMPLOYEES"
echo "  • Bulk Employee Correction: Active/Resigned filter fixed, Group"
echo "    filter always available, firm dropdown type-to-search."
echo "  • Bulk Import: Present Add / City / State / Pin Code fully mapped."
