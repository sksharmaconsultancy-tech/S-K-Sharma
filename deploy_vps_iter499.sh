#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 499)
#
# NEW IN 499 — FOUR ITEMS:
#
#   1) GROUP-WISE ATTENDANCE REPORT FIX (your report: "click on any group —
#      all groups select by default"):
#      ROOT CAUSE FOUND: the group list API returned Masters groups WITHOUT
#      an id, so every chip carried an empty id — clicking any chip
#      matched ALL chips and the filter was never applied. Every group now
#      carries a proper id end-to-end. Clicking LABOUR/STAFF now filters
#      the grid to exactly that group's employees.
#
#   2) PRIORITY TASKS ON THE DASHBOARD (your enhancement request):
#      A compact "⚡ Priority Tasks" strip at the TOP of the existing
#      dashboard (nothing else moved or changed): 🔴 Overdue, 🟠 High
#      priority, ⚠ Due today + 📅 today's statutory schedule. Max 8 rows,
#      completed/low-priority never shown. Tap a row → opens the existing
#      Tasks / Calendar tab. Auto-refreshes when you return to Overview.
#
#   3) FACTORY & BOILER ANNUAL RETURN (Compliance → Statutory Returns):
#      Government-style annual return computed from your existing payroll +
#      attendance with a UNIFIED DATA LAYER:
#        • Combined (default) / Current DB only / Legacy (imported) only
#        • current + imported legacy months merged WITHOUT duplication
#          (current data wins; legacy records stay READ-ONLY)
#        • Factory particulars editor (license no, occupier, manager,
#          nature of manufacturing, district/state, welfare facilities,
#          accident statistics per year) saved on the Firm
#        • Auto-calculated: avg daily employment, max employment,
#          male/female, contract labour, man-days, wages, OT hours/amount,
#          leave with wages + department-wise & category-wise summaries
#        • Exports: Factory Return PDF (Form-style), Boiler Return PDF,
#          Excel workbook + every grid also has the universal PDF button.
#
#   4) SMARTER MENU SEARCH (your request: "points, subpoints and reports
#      also search"): the top search box now matches SUB-POINTS (searching
#      a section like "compliance" lists everything inside it, with the
#      section path shown) AND the inner reports of the Report Hub
#      (Wage Register, Form D, CLRA forms…) — clicking a report opens the
#      Report Hub with that exact report pre-selected.
#
# INCLUDES Iter 498 (one-shot IN+OUT+OT punch repair) and everything before.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/8 Downloading latest code bundle (~10 MB, retries enabled)..."
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

echo "==> 2/8 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 3/8 Installing backend deps (openpyxl needed for the new Excel)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP install openpyxl -q || true

echo "==> 4/8 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/8 Restarting backend service..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend

echo "==> 6/8 Nginx configs (unchanged)..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 7/8 Health check..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"

echo "==> 8/8 Verification..."
echo -n "   Server Version badge shows 499 (must say OK): "
grep -q 'APP_ITERATION = "499"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Group filter root-cause fix (must say OK): "
grep -q 'byname:' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Priority Tasks strip (must say OK): "
[ -f $APP_DIR/frontend/src/components/portal/PriorityTasks.tsx ] && grep -q 'portal-tasks/priority' $APP_DIR/backend/routes/portal_phase2.py && echo "OK" || echo "MISSING!"
echo -n "   Factory & Boiler Annual Return (must say OK): "
[ -f $APP_DIR/backend/routes/factory_returns.py ] && [ -f $APP_DIR/frontend/app/factory-annual-return.tsx ] && grep -q 'factory_returns_router' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Menu search — subpoints + reports (must say OK): "
grep -q 'flatNavDeep' $APP_DIR/frontend/src/components/AdminWebShell.tsx && echo "OK" || echo "MISSING!"
echo -n "   Iter 498 one-shot punch repair still present (must say OK): "
grep -q 'Fix IN + OUT Together' $APP_DIR/frontend/src/components/PunchRepairModal.tsx && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 499 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 499'."
echo "   2. GROUPS: Attendance Report → click LABOUR → only LABOUR"
echo "      employees; click STAFF → only STAFF; All restores everyone."
echo "   3. DASHBOARD: '⚡ Priority Tasks' strip at the top with your"
echo "      overdue/high tasks — tap a row to jump to Tasks."
echo "   4. Compliance → 'Factory & Boiler Annual Return' → pick firm +"
echo "      year → fill particulars via Edit → download Factory PDF,"
echo "      Boiler PDF or Excel. Switch Combined/Current/Legacy source."
echo "   5. SEARCH: type 'wage' in the top search — Report Hub reports"
echo "      appear too; type 'compliance' — all sub-points listed."
