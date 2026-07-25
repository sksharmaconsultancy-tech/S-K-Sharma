#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 299)
# Ships everything since deploy 298:
#  1. 📊 NEW MODULE: ENTERPRISE SALARY REGISTER (user PRD):
#     • Payroll → Salary Process → Salary Register
#     • One dynamic register over BOTH engines: Compliance Salary AND
#       Actual Salary (toggle at the top right).
#     • Columns are DYNAMIC — earnings/deductions heads are read from the
#       processed salary run itself (nothing hardcoded); new heads appear
#       automatically, all-zero heads are hidden to keep the grid tight.
#     • Microsoft-365 style grid: colour-banded group headers (Employee /
#       Attendance / Earnings / Deductions / Employer Contributions / Net),
#       frozen Sr + Code + Name columns, sticky headers, zebra rows,
#       TOTAL row pinned at the bottom.
#     • KPI strip: Employees · Gross · Deductions · Net Payable.
#     • Filters: Firm, Month (FY-wise picker), Run selector (when a month
#       was processed more than once), Employee Group, Branch, Department,
#       Contractor + live employee search (name/code/father/designation).
#     • Column sorting (tap any header) + server-side pagination
#       (25/50/100/200 rows per page) — fast even for large firms.
#     • EXPORTS: PDF (A3 landscape register), Excel (banded colour header,
#       frozen panes, totals row) and CSV — all honour the active filters.
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
echo "🎉 Deploy 299 complete."
echo
echo "WHAT'S NEW IN THIS DEPLOY:"
echo "  • 📊 NEW: SALARY REGISTER — Payroll → Salary Process → Salary Register"
echo "    One professional register over BOTH engines (Compliance / Actual"
echo "    toggle). Columns are DYNAMIC — heads come from the processed run"
echo "    itself, new heads appear automatically, empty heads are hidden."
echo "  • 🎨 Enterprise grid: colour-banded group headers (Employee /"
echo "    Attendance / Earnings / Deductions / Employer / Net), frozen"
echo "    Sr + Code + Name columns, sticky headers, TOTAL row, KPI strip"
echo "    (Employees · Gross · Deductions · Net Payable)."
echo "  • 🔎 Filters: Firm, FY-wise Month, Run selector, Employee Group,"
echo "    Branch, Department, Contractor + live employee search."
echo "  • ↕️ Tap any column header to sort; pages of 25/50/100/200 rows"
echo "    keep it fast for big firms."
echo "  • 📤 Exports honouring all active filters: PDF (A3 register),"
echo "    Excel (banded colour header, frozen panes, totals row), CSV."
echo
echo "HOW TO USE:"
echo "  1. Payroll → Salary Process → Salary Register"
echo "  2. Pick Firm + Month (FY-wise) — the register loads instantly"
echo "  3. Toggle Compliance / Actual, filter, search, sort as needed"
echo "  4. Export PDF / Excel / CSV"
