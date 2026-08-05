#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 497)
#
# NEW IN 497 — UNIVERSAL REPORT ENGINE PHASE 2 + 3 + SCREEN-MATCHING PDF:
#
#   1) BANDED (GROUPED) HEADERS in the Universal Report Table — colored
#      group bands (Employee / Attendance / Earnings / Deductions / Net)
#      stay frozen on top together with the column header row.
#
#   2) MORE REPORTS MOVED ONTO THE ENGINE (no more overlapping columns,
#      auto widths, sticky Code+Name, tooltips, saved layouts):
#        • SALARY REGISTER (full banded rebuild — Layout Editor widths
#          respected; server sort kept; TOTAL row pinned at the bottom)
#        • BANK SHEET (TOTAL NET PAYABLE pinned)
#        • DAY-WISE SALARY SHEET (grand totals pinned)
#        • PF CONTRIBUTION SHEET — monthly + yearly
#        • ESIC CONTRIBUTION SHEET — monthly + yearly
#
#   3) UNIVERSAL "PDF" BUTTON on every migrated report:
#      exports EXACTLY what you see on screen — your visible columns, your
#      column order and widths — as a clean LANDSCAPE PDF:
#        • header (and group bands) repeated on EVERY page
#        • long text wraps — nothing truncated, nothing overlapping
#        • numbers right-aligned, totals row highlighted
#        • auto page size (A4 → Legal → A3 → A2 for very wide reports)
#      New endpoint: POST /api/report-export/pdf (auth-protected).
#
# INCLUDES Iter 496 (engine phase 1: Punch Log, OT, Leave, Bank Transfer)
# and Iter 495 (machine SDK photos) and everything before.
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
echo -n "   Server Version badge shows 497 (must say OK): "
grep -q 'APP_ITERATION = "497"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Banded headers in the engine (must say OK): "
grep -q 'bandSegs' $APP_DIR/frontend/src/components/ReportTable.tsx && echo "OK" || echo "MISSING!"
echo -n "   Universal PDF export endpoint (must say OK): "
[ -f $APP_DIR/backend/routes/report_export.py ] && [ -f $APP_DIR/backend/utils/report_pdf.py ] && grep -q 'report_export_router' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Salary Register on the engine (must say OK): "
grep -q 'reportKey="salary_register"' $APP_DIR/frontend/app/salary-register.tsx && echo "OK" || echo "MISSING!"
echo -n "   Bank Sheet on the engine (must say OK): "
grep -q 'reportKey="bank_sheet"' $APP_DIR/frontend/app/bank-sheet.tsx && echo "OK" || echo "MISSING!"
echo -n "   Day-wise Salary Sheet on the engine (must say OK): "
grep -q 'reportKey="salary_day_sheet"' $APP_DIR/frontend/app/salary-day-sheet.tsx && echo "OK" || echo "MISSING!"
echo -n "   PF/ESIC sheets on the engine (must say OK): "
grep -q 'contrib_' $APP_DIR/frontend/app/contribution-sheets.tsx && echo "OK" || echo "MISSING!"
echo -n "   Iter 496 engine phase-1 screens still present (must say OK): "
grep -q 'reportKey="punch_log"' $APP_DIR/frontend/app/punch-log-report.tsx && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 497 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 497'."
echo "   2. SALARY REGISTER: colored group bands + column headers stay"
echo "      frozen on top; Sr/Code/Name frozen on the left; TOTAL row"
echo "      pinned at the bottom; long designations show '…' (hover for"
echo "      the full text)."
echo "   3. Click the small red 'PDF' button in the table toolbar (next to"
echo "      'Columns') on Salary Register / Bank Sheet / Day-wise Salary"
echo "      Sheet / PF / ESIC — the PDF matches the screen exactly, with"
echo "      the header repeated on every page and no cut columns."
echo "   4. Hide a column via 'Columns' then export PDF — the hidden"
echo "      column stays out of the PDF too (screen = print = PDF)."
