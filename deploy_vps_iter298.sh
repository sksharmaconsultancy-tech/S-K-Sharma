#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 298)
# Ships everything since deploy 297:
#  1. 🗂️ LEGACY IMPORT WIZARD — HEAD MAPPING OVERRIDE (user request):
#     • Import/Export → Legacy Import Wizard → "Head Mapping" chart is
#       now EDITABLE: tap any row to change where an old head settles
#       (e.g. move GrossPay somewhere else) or set SKIP to not import
#       that head at all. Changed rows show an amber CHANGED / red
#       SKIPPED badge; one-tap "Reset all changes to default".
#  2. ✅ DOUBLE CONFIRMATION BEFORE IMPORT (user request):
#     • Pressing Start Import now asks TWICE:
#       (1/2) "Verify Head Mapping" — lists every head you changed
#             (or confirms all heads are on the default mapping).
#       (2/2) "Final Confirmation" — data is written only after this.
#  3. 🔗 MASTERS INTERLINK (from 297 bundle, now active): Employee Type /
#     Department / Designation values found in the legacy data are
#     auto-registered into the mapped firm's General Masters (Groups
#     created for Employee Types) so they appear in every dropdown.
#  4. 🔍 LEGACY vs CURRENT comparison report (Import/Export menu):
#     spot-check migrated data — every employee's old salary history
#     side-by-side with the new portal's master & payroll, amber flag
#     when master Basic differs from the last legacy Basic, month-wise
#     drill-down (Legacy Online / Offline / Compliance / Actual).
#  5. 🐛 IMPORT ERROR FIX: "Input should be a valid dictionary" pydantic
#     error on Preview/Start Import — request body was double-encoded.
#  6. 🗂️ SALARY-HISTORY HEADS editable too (user request): the ONLINE
#     (SalaryTrans) and OFFLINE (SalaryTransoff) sections of the Head
#     Mapping chart are now row-by-row editable — remap any history head
#     (Days, Basic, EPF, ESI, TDS, Less heads, Net…) or SKIP it.
#  7. 📊 PUBLISH OLD MONTHS INTO COMPLIANCE SALARY PROCESS (user request):
#     Legacy Salary Records → "Publish months to Compliance Salary
#     Process" — SELECT the months you want (per-month ticks + ALL MONTHS
#     option); each becomes an UNLOCKED draft compliance run (months
#     already processed are SKIPPED, never overwritten). Check the data in
#     Compliance Salary Process + all its reports (register PDF, Excel,
#     PF ECR, ESIC), then press "Data checked & OK → Lock all published
#     legacy months" to finalize.
#     Guard: salary publish/import only allowed for firms whose Employee
#     Master is already imported.
#  8. 🧮 MASTER SALARY per month (user request): published months carry the
#     month's MASTER (full-month) salary too — Basic master taken from the
#     old software's rate column, other heads pro-rated to a full month —
#     so calculations/screens show rate vs earned correctly.
#  9. 🏢 CREATE NEW FIRM from legacy (user request, A-ONE MOTOR'S case):
#     in the wizard's firm picker choose "➕ Create NEW firm in Firm
#     Master" — a PREVIEW first shows everything that will be created
#     (name, address, emails, EPF/ESI numbers + portal LOGIN credentials,
#     bank, PAN/TAN/GST, owner/contact — all read from the legacy
#     FirmMaster), then the firm is created during Start Import with all
#     those settings filled into its Firm Master.
# 10. ↩️ UNDO IMPORT (user request): imported firms now show an "Undo"
#     button — removes the employees CREATED by that import, its legacy
#     salary history and published legacy months, and unlocks the firm so
#     it can be re-imported into the right (or newly created) firm.
# Prerequisite: the legacy SQL container (sks-mssql) must be running —
# it was set up earlier with legacy_setup.sh. Nothing else changes.
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

# AI Payroll Assistant needs the Emergent universal LLM key.
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
  echo "   EMERGENT_LLM_KEY added to backend/.env ✅"
fi

echo "==> 3/6 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP show emergentintegrations >/dev/null 2>&1 || \
  $PIP install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q

echo "==> 4/6 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
# BLANK-PAGE FIX (Iter 295): DO NOT wipe old bundles — installed PWAs
# with a cached index.html still find their old entry-*.js. Old bundles
# are pruned only after 30 days.
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/
sudo find $WEB_DIR/_expo/static/js/web -name "entry-*.js" -mtime +30 -delete 2>/dev/null || true

# Never cache index.html; cache hashed assets forever (Iter 295).
SITE_CONF=$(grep -rl "root $WEB_DIR" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | head -1)
if [ -n "$SITE_CONF" ] && ! grep -q "sks-cache-fix" "$SITE_CONF" && ! grep -q 'Cache-Control "no-cache' "$SITE_CONF"; then
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
CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001/api/admin/legacy-import/firms")
echo "   /api/admin/legacy-import/firms → HTTP $CODE (401/403 = alive, auth required; 503 = legacy SQL container not running)"
if ! sudo docker ps --format '{{.Names}}' 2>/dev/null | grep -q sks-mssql; then
  echo "   ⚠️  Legacy SQL container (sks-mssql) is NOT running — start it with:"
  echo "       sudo docker start sks-mssql"
fi
echo
echo "🎉 Deploy 298 complete."
echo
echo "WHAT'S NEW IN THIS DEPLOY:"
echo "  • 🗂️ Legacy Import Wizard — the Head Mapping chart is now EDITABLE:"
echo "    tap any row to change where an old head settles in this portal,"
echo "    or set SKIP to leave it out. Changed rows show a CHANGED/SKIPPED"
echo "    badge and can be reset to default in one tap."
echo "  • ✅ Start Import now asks for confirmation TWICE — first it shows"
echo "    every head you changed so you can verify nothing lands in the"
echo "    wrong place, then a final confirmation before anything is written."
echo "  • 🔗 Employee Type / Department / Designation from the old data are"
echo "    auto-created in the firm's General Masters (Types become Groups)"
echo "    so they appear in all dropdowns after import."
echo "  • 🔍 NEW report: Import/Export → 'Legacy vs Current' — after the"
echo "    import, spot-check every employee: old salary history next to the"
echo "    new master & payroll, mismatch flags, month-wise drill-down."
echo "  • 🐛 FIXED: the 'Input should be a valid dictionary' error when you"
echo "    pressed Preview / Start Import."
echo "  • 🗂️ Salary-history heads (Online & Offline) are now editable in the"
echo "    Head Mapping chart too — remap or SKIP any of them before import."
echo "  • 📊 Legacy Salary Records → PUBLISH old ONLINE months into the"
echo "    Compliance Salary Process — pick the months (or ALL MONTHS) →"
echo "    drafts created → check data & reports → 'Lock all published"
echo "    legacy months'. Salary publish requires the firm's Employee"
echo "    Master to be imported first."
echo "  • 🧮 Published months now include MASTER (full-month) salary heads."
echo "  • 🏢 Firm picker → '➕ Create NEW firm in Firm Master' — preview of"
echo "    all settings from the legacy FirmMaster (address, EPF/ESI numbers"
echo "    + portal logins, bank, PAN/GST, owner) before you confirm; firm is"
echo "    created on Start Import. Fixes the A-ONE MOTOR'S case."
echo "  • ↩️ 'Undo' button on already-imported firms — removes that import"
echo "    (created employees, salary history, published months) and unlocks"
echo "    the firm for re-import."
echo "  • 📅 FY-WISE period selection: Compliance Salary Process & Reports"
echo "    month pickers now select by Financial Year (Apr→Mar, 20 FYs back)"
echo "    so old legacy months/periods are reachable."
echo "  • 🏷️ Legacy Salary Records: firm list shows ONLY successfully"
echo "    imported firms, with '✓ SALARY IMPORTED (n)' and '🔒 LOCKED'"
echo "    highlight badges."
echo "  • 👥 Wizard firm rows now show OLD-DB counts: Active / Resigned /"
echo "    Total — counted exactly the way the import works (latest year"
echo "    record per employee) so numbers match what gets imported."
echo "  • 🔍 COMPARISON RECORD (firm-wise grouping): after Preview press"
echo "    'Compare Records' — shows every MATCHED name (with field-by-field"
echo "    old → new differences) and lets you tick REPLACE or keep each one;"
echo "    unticked names stay untouched, NEW employees import regardless."
echo
echo "HOW TO IMPORT:"
echo "  1. Import / Export → Legacy Import Wizard"
echo "  2. Tick the old firms and map each to a portal firm"
echo "  3. Open 'Head Mapping' — verify / change / skip heads as needed"
echo "  4. Preview → Start Import → confirm twice → done"
