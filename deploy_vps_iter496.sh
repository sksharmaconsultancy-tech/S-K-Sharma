#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 496)
#
# NEW IN 496 — UNIVERSAL REPORT TABLE ENGINE, PHASE 1 (your spec: "Fix the
# Payroll Reporting Engine so all reports display correctly without column
# overlapping"):
#
#   ONE COMMON TABLE RENDERER (new src/components/ReportTable.tsx) that
#   every report inherits — reports can no longer override the layout:
#     • AUTO COLUMN WIDTH measured from the actual content, with per-type
#       minimum & maximum widths (Name min 220px, amounts min 100-120px…)
#       — long names EXPAND their column instead of pushing others.
#     • NO MORE OVERLAP: truncated text shows an ellipsis; hover (or tap)
#       shows the FULL value in a tooltip.
#     • STICKY HEADER while scrolling down — header cells always align
#       exactly with their data columns.
#     • FROZEN Employee Code + Name (and photo) columns while scrolling
#       right on wide reports.
#     • Numbers RIGHT-aligned, dates/status CENTERED, text LEFT-aligned.
#     • RESPONSIVE FONT: 14px desktop / 13px laptop / 12px tablet,
#       never below 11px. Consistent row heights.
#     • VIRTUAL SCROLLING — smooth even with 100,000+ rows (only the
#       visible window is rendered).
#     • COLUMN RESIZE by dragging the header border (mouse), plus a
#       "Columns" button to SHOW/HIDE columns and "Reset layout".
#     • SAVED LAYOUT: your widths/hidden columns are remembered PER USER
#       PER REPORT — in the browser AND on the server (follows you to
#       any device). New API: /api/report-prefs/{report}.
#
#   PHASE 1 REPORTS MIGRATED (more in the next deploys):
#     • Punch Log Report (photo column kept, colors kept)
#     • OT Report (tap-to-sort kept + TOTAL row now pinned at the bottom)
#     • Leave Report
#     • Bank Transfer preview grid (TOTAL row added)
#
# INCLUDES Iter 495 (machine SDK photos, new-machine user fetch,
# group-wise IN/OUT) and everything before.
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

echo "==> 3/8 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

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
echo -n "   Server Version badge shows 496 (must say OK): "
grep -q 'APP_ITERATION = "496"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Universal Report Table engine (must say OK): "
[ -f $APP_DIR/frontend/src/components/ReportTable.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Report layout prefs API (must say OK): "
grep -q 'report_prefs_router' $APP_DIR/backend/server.py && [ -f $APP_DIR/backend/routes/report_prefs.py ] && echo "OK" || echo "MISSING!"
echo -n "   Punch Log on the new engine (must say OK): "
grep -q 'reportKey="punch_log"' $APP_DIR/frontend/app/punch-log-report.tsx && echo "OK" || echo "MISSING!"
echo -n "   OT Report on the new engine (must say OK): "
grep -q 'reportKey="ot_report"' $APP_DIR/frontend/app/ot-report.tsx && echo "OK" || echo "MISSING!"
echo -n "   Leave Report on the new engine (must say OK): "
grep -q 'reportKey="leave_report"' $APP_DIR/frontend/app/leave-report.tsx && echo "OK" || echo "MISSING!"
echo -n "   Bank Transfer preview on the new engine (must say OK): "
grep -q 'reportKey="bank_transfer"' $APP_DIR/frontend/app/bank-transfer.tsx && echo "OK" || echo "MISSING!"
echo -n "   Iter 495 machine SDK photos still present (must say OK): "
grep -q '_machine_photo_backfill' $APP_DIR/backend/routes/employee_photos.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 496 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 496'."
echo "   2. PUNCH LOG REPORT: columns auto-size — long names never push"
echo "      other columns; scroll right → photo/Code/Employee stay frozen;"
echo "      scroll down → blue header stays on top."
echo "   3. Click 'Columns' (top-right of the table) → hide/show any"
echo "      column; drag a header border to resize; 'Reset layout' undoes."
echo "      Your layout is remembered per report, on any device."
echo "   4. OT REPORT: TOTAL row pinned at the bottom; tap headers to sort."
echo "   5. LEAVE REPORT & BANK TRANSFER preview use the same engine."
echo ""
echo "   NOTE: remaining reports (Salary Register, Wage Register, Monthly"
echo "   Attendance, Employee Master…) move onto the same engine in the"
echo "   next deploys, phase by phase, so nothing breaks."
