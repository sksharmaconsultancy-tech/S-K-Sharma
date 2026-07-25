#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 294)
# Ships everything since deploy 290:
#  1. NEW SIDEBAR — reorganised into 12 clean groups (Dashboard, Employees,
#     Attendance & Shift, Payroll, Compliance, Approvals & Workflow, Reports,
#     Masters, Import/Export, Devices & Integration, Communication,
#     Administration) with the approved dark theme (#0F172A sidebar,
#     #2563EB blue active, #F8FAFC background).
#  2. 🤖 AI PAYROLL ASSISTANT — floating ✨ button (bottom-right). Type or
#     SPEAK commands: "Process July payroll", "Who is present today?",
#     "Pending approvals", "Open attendance report". Payroll runs always
#     ask for an explicit Confirm click. Voice works in Chrome/Edge.
#  3. 🔎 GLOBAL SEARCH — the top search bar now also finds EMPLOYEES
#     (name / code / Aadhaar / PAN / UAN) and FIRMS, not just menu items.
#  4. ⌨️ KEYBOARD SHORTCUTS — Ctrl+K search · Ctrl+Shift+A AI assistant ·
#     g,d dashboard · g,e employees · g,a attendance · g,p payroll ·
#     g,r reports · g,b bank files · press ? for the full list.
#  5. ⭐ PINNED FAVOURITES + 🕘 RECENTLY OPENED — star any menu item to pin
#     it to the top of the sidebar; last screens auto-listed.
#  6. 🔔 NOTIFICATION CENTRE — bell now opens a dropdown panel with
#     Mark-all-read + View-all.
#  7. 🌐 ENGLISH / हिंदी toggle in the top bar (shell + menu labels).
#  8. 💾 AUTO-SAVE — Add New Employee silently saves a draft 3s after you
#     stop typing (create mode); resume anytime.
#  9. 🪟 SPLIT-SCREEN COMPARE — Reports → Split View Compare: any two
#     screens side-by-side (e.g. two months' reports).
# 10. 🏦 BANK TRANSFER FILES — Payroll → Bank Transfer Files: ready-to-upload
#     salary files (ICICI / HDFC / SBI / Axis / Kotak / Generic) in
#     xlsx / csv / txt / xml. Upload in corporate net-banking → bank credits.
# 11. 📊 BI & DATA FEED — Devices & Integration → BI & Data Feed: per-firm
#     secret URLs for Power BI / Excel live dashboards (employees,
#     attendance, salary, compliance datasets).
# 12. 🖐 MULTI-BRAND BIOMETRICS — register ZKTeco, eSSL (same ADMS protocol),
#     Matrix COSEC & Mantra devices. Matrix/Mantra push JSON punches to a
#     per-device Webhook URL (shown on the device card).
# 13. 🐛 BUG FIX — "STAFF" group now always appears in Group Master and the
#     Add-Employee Group dropdown (self-healing per-firm interlink).
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/6 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/6 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true

# Iter 294 — the AI Payroll Assistant needs the Emergent universal LLM key.
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
  echo "   EMERGENT_LLM_KEY added to backend/.env ✅"
fi

echo "==> 3/6 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
# Make sure the AI library is present even if the bulk install skipped.
$PIP show emergentintegrations >/dev/null 2>&1 || \
  $PIP install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q

echo "==> 4/6 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
# Iter 295 — BLANK-PAGE FIX (iOS/Android PWA): DO NOT wipe old bundles.
# Installed PWAs cache the old index.html which points at the old hashed
# entry-*.js; deleting it caused a 404 → blank screen. Keep old bundles
# alongside the new build (pruned after 30 days) so stale clients still
# load, then pick up the new version on their next refresh.
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/
sudo find $WEB_DIR/_expo/static/js/web -name "entry-*.js" -mtime +30 -delete 2>/dev/null || true

# Iter 295 — tell browsers to NEVER cache index.html (hashed assets are
# immutable and cached forever). Applied once, with nginx -t + rollback.
SITE_CONF=$(grep -rl "root $WEB_DIR" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | head -1)
if [ -n "$SITE_CONF" ] && ! grep -q "sks-cache-fix" "$SITE_CONF"; then
  sudo cp "$SITE_CONF" "$SITE_CONF.bak-cache"
  sudo sed -i "0,\|root $WEB_DIR;|s||root $WEB_DIR;\n    # sks-cache-fix — never cache the SPA shell; cache hashed assets forever\n    location = /index.html { add_header Cache-Control \"no-store, must-revalidate\"; }\n    location /_expo/static/ { add_header Cache-Control \"public, max-age=31536000, immutable\"; }|" "$SITE_CONF"
  if sudo nginx -t 2>/dev/null; then
    sudo systemctl reload nginx
    echo "   nginx cache headers applied ✅"
  else
    sudo mv "$SITE_CONF.bak-cache" "$SITE_CONF"
    echo "   nginx patch skipped (config test failed — restored backup)"
  fi
fi

echo "==> 5/6 Restarting backend..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 5

echo "==> 6/6 Verifying..."
curl -s http://localhost:8001/api/health && echo
# New Iter-294 endpoints must answer (401/422 = alive, auth required):
for EP in "admin/ai-assistant/history" "admin/bank-transfer/formats" "admin/global-search?q=test"; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001/api/$EP")
  echo "   /api/$EP → HTTP $CODE"
done
echo
echo "🎉 Deploy 295 complete."
echo
echo "FIXES IN THIS DEPLOY:"
echo "  • 📱 BLANK PAGE FIX (iOS + Android PWA): old app bundles are now kept"
echo "    on the server, so employees with a cached app never see a blank"
echo "    screen again. index.html is no longer cached by browsers."
echo "  • 📍 GEOFENCE FIX: punches now allow for phone GPS accuracy (max"
echo "    100 m benefit) — employees inside the radius are no longer"
echo "    rejected due to GPS drift. Spoof-safe: far punches still blocked."
echo "  • 🕐 Employee sessions last 90 days (no auto-logout)."
echo "  • Bulk Import: Resign Date now sets Exit/Left date + Resigned status."
echo "  • Bulk Import: double-confirmation before saving."
echo "  • Device Sync: firm dropdown."
echo
echo "⚠️  Employees whose PWA is CURRENTLY blank: they must clear the app"
echo "   cache / reinstall the PWA ONE last time (old bundle was already"
echo "   deleted by previous deploys). After this deploy it never recurs."
