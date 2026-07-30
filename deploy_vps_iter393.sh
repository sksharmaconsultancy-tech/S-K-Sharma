#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 393)
# INCLUDES Iter 370-391 (already live) + NEW IN THIS RELEASE:
#
# Iter 392 — ATTENDANCE SYNCHRONIZATION DASHBOARD (new module):
#   Menu: Attendance & Shift → "Attendance Sync Dashboard" (also under
#   Reports), placed right after Attendance Report.
#   • KPI cards: Total/Machine-Registered/Active, New Joining, Machine &
#     Master Pending, Attendance Missing, Never Punched, Attendance %,
#     Machine/Master Sync %, Overall Health, Last Sync time.
#   • Section 1 New Joining (DOJ in range, colour-coded, first punch).
#   • Section 2 Registered in Machine but NOT in Master (unmapped
#     machine punches + suggested employee match).
#   • Section 3 Registered in Master but NOT in Machine.
#   • Section 4 In both but Attendance Missing (1/2/3/5/7/15/30-day
#     filter, leave-aware smart remarks, Never-Punched detection).
#   • Section 5 Continuous Absence buckets (3/5/7/15/30 days).
#   • Section 6 Attendance Health progress bars + machine online list.
#   • Section 7 Trends (daily punch % 14d, weekly joinings 8w).
#   • Rule-based Smart Analysis remarks on every row; row-click opens
#     the Employee Detail Slip. Per-section Excel/PDF/CSV exports.
#
# Iter 393 — FULL REPORT IN ONE FILE: header EXCEL / PDF buttons export
#   the ENTIRE dashboard (KPI summary + all 7 sections) as a SINGLE
#   Excel sheet with styled section bands, one combined PDF, or CSV.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle (~115 MB, retries enabled)..."
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

echo "==> 2/7 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 3/7 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP show emergentintegrations >/dev/null 2>&1 || \
  $PIP install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q

echo "==> 4/7 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/7 Restarting backend service..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend

echo "==> 6/7 Reloading nginx..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 7/7 Health check + verification..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"
echo -n "   Sync dashboard API (must exist): "
[ -f $APP_DIR/backend/routes/attendance_sync_dashboard.py ] && echo "OK" || echo "MISSING!"
echo -n "   Sync dashboard screen (must exist): "
[ -f $APP_DIR/frontend/app/attendance-sync-dashboard.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Full single-sheet export (must be >= 1): "
grep -c "Iter 393" $APP_DIR/backend/routes/attendance_sync_dashboard.py || true
echo -n "   Menu entry (must be >= 2): "
grep -c "attendance-sync-dashboard" $APP_DIR/frontend/src/components/AdminWebShell.tsx || true
echo ""
echo "✅ Deploy Iter 393 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Attendance & Shift → 'Attendance Sync Dashboard' (after"
echo "     Attendance Report): KPI cards, 7 reconciliation sections,"
echo "     smart remarks, health bars, trends."
echo "   → Header EXCEL / PDF buttons download the FULL report in one"
echo "     single sheet / one combined PDF; per-section exports too."
echo "   → Machines offline? The dashboard's Machine Synchronization"
echo "     list shows last-seen time and the reason per device."
