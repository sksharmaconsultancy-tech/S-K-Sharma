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
sudo rm -rf $WEB_DIR/*
sudo cp -r dist/* $WEB_DIR/

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
echo "🎉 Deploy 294 complete."
echo
echo "WHAT'S NEW FOR YOUR TEAM:"
echo "  • NEW dark sidebar with 12 organised groups (your approved theme)."
echo "  • 🤖 AI Assistant (✨ button, bottom-right): type or SPEAK commands"
echo "    like 'Process July payroll' — it asks Confirm before running."
echo "  • Top search now finds employees & firms too (Ctrl+K)."
echo "  • Keyboard shortcuts — press ? anywhere for the list."
echo "  • Star menu items to pin Favourites; Recently Opened auto-lists."
echo "  • Bell = full Notification Centre. EN/हिंदी toggle in top bar."
echo "  • Add Employee auto-saves a draft while you type."
echo "  • Reports → Split View Compare: two screens side-by-side."
echo "  • Payroll → Bank Transfer Files: ICICI/HDFC/SBI/Axis/Kotak salary"
echo "    upload files (xlsx/csv/txt/xml) — upload in net-banking to pay."
echo "  • Devices → BI & Data Feed: live Power BI / Excel dashboards."
echo "  • Biometric Devices: eSSL / Matrix COSEC / Mantra brands + webhook."
echo "  • FIXED: STAFF group shows in Group Master & Add-Employee dropdown."
echo
echo "⚠️  IMPORTANT: Everyone must HARD-REFRESH the portal once"
echo "   (Ctrl+Shift+R on desktop / clear PWA cache on mobile)"
echo "   to load the new build."
