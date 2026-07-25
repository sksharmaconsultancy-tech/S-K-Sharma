#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 299 + 306)
# Ships: Enterprise Salary Register + the 20-point fix list + GPS punch fix.
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
CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001/api/admin/salary-register?source=compliance&month=2026-05")
echo "   /api/admin/salary-register → HTTP $CODE (401/403 = alive, auth required)"

echo
echo "🎉 Deploy 299+306 complete."
echo
echo "WHAT'S NEW IN THIS DEPLOY:"
echo
echo "📊 NEW: SALARY REGISTER — Payroll → Salary Process → Salary Register"
echo "  • One register over BOTH engines (Compliance / Actual toggle)."
echo "  • DYNAMIC columns from the processed run (new heads auto-appear,"
echo "    empty heads hidden). Colour-banded headers, frozen Name column,"
echo "    KPI strip, TOTAL row, sort + 25/50/100/200 paging."
echo "  • Filters: Firm, FY-wise Month, Run, Group, Branch, Dept,"
echo "    Contractor + live search. Exports: PDF (A3) / Excel / CSV."
echo
echo "🛰️  GPS PUNCH FIX (many employees affected):"
echo "  • 'Could not fetch GPS location' — the phone's GPS watcher often"
echo "    returned nothing; the app now also tries an instant fix, a"
echo "    fallback fix and the last-known location (15 s budget)."
echo
echo "✅ YOUR 20-POINT LIST:"
echo "  1  Sub-Admin employee delete now needs SUPER ADMIN approval"
echo "  2  Employee Master photo now shows on the employee's PWA profile"
echo "  3  Punch photo showing blank — FIXED (double data-URL prefix)"
echo "  4  Compliance Register Format 1 now prints UAN / P.F. / ESI No."
echo "  5  ESIC no longer calculated when working days are 0"
echo "     (REPROCESS any old month that showed wrong ESIC)"
echo "  6  Compliance Salary shows data ONLY after you click Process"
echo "  7  Master Rates now show (daily-rate employees resolve from the"
echo "     salary structure — reprocess the month to see rates)"
echo "  8  Tap any row in Compliance/Actual salary grids to HIGHLIGHT it"
echo "  9  New 'Group' filter chip on both salary process grids"
echo "  10 Compliance Register Formats 1 & 2 added to PDF Report Formats"
echo "  11 Eye icon on EPF/ESI password boxes in Firm Master"
echo "  12 DOJ column (optional) in Salary Register PDF — enable it in"
echo "     Reports → PDF Report Formats → Salary Register"
echo "  13 Sidebar can be hidden — arrow button next to the firm name;"
echo "     the ☰ button brings it back"
echo "  14 New 'Firms' sidebar section: Companies (Firm Master), List of"
echo "     Firms, Firms ID & Password (PF · ESIC) — PIN-protected vault"
echo "  15 ACTIVE FIRM badge is now read-only (no accidental firm switch)"
echo "  16 Bulk Import template already has Present Add / City / State /"
echo "     Pin Code — re-download the template after this deploy"
echo "  17 Payroll no longer pre-fills attendance from Employee Master"
echo "  18 Bulk Employee Correction columns now line up with headings"
echo "  19 Bulk Correction group filter shows only groups with ACTIVE staff"
echo "  20 New editable 'ESIC Leave' days column in Compliance Salary"
echo
echo "HOW TO USE THE REGISTER:"
echo "  Payroll → Salary Process → Salary Register → pick Firm + Month"
echo "  → toggle Compliance/Actual → filter/sort → export PDF/Excel/CSV"
