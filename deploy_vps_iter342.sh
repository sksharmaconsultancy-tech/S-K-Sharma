#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 342)
# Ships (everything since deploy 341):
#   • OFFLINE LEGACY SALARY IMPORT FIX (user: "Still Not Getting Offline
#     Salary Record From Old Database"):
#       - SalaryTransoff rows whose month is stored ONLY in MonthYear
#         ('Feb 2019' / '02-2019' / '201902' etc.) were silently skipped
#         because the importer read FirstDayOfMonth only. The importer now
#         derives the month from EITHER column in any known format.
#       - Legacy column names are matched case-insensitively and a schema
#         mismatch on the offline table no longer aborts the whole import
#         (falls back to a filter-free query, skips deleted rows in code).
#       - Non-numeric / blank EmpCode values no longer crash a row.
#       - NEW diagnostic counters in the import job report:
#         offline_skipped_no_month / online_skipped_no_month — if offline
#         rows are still missing, this number tells us exactly why.
#   • After deploy: re-run Legacy Import for the affected firm(s) with
#     "Offline Salary" ticked, then use "Publish months to ACTUAL Salary
#     Process" to see them under Actual Salary past runs.
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip
PY=$APP_DIR/backend/venv/bin/python

echo "==> 1/7 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

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
$PIP show qrcode >/dev/null 2>&1 || $PIP install qrcode -q
$PIP show emergentintegrations >/dev/null 2>&1 || \
  $PIP install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q

echo "==> 4/7 Restarting backend service..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend

echo "==> 5/7 Reloading nginx..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 6/7 Health check..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — check: journalctl -u sksharma-backend -n 50"

echo "==> 7/7 Verify new code..."
echo -n "   Offline month fallback in importer (must be > 0): "
grep -c "_month_key_any" $APP_DIR/backend/routes/legacy_import.py || true
echo -n "   Skip diagnostics in importer (must be > 0): "
grep -c "skipped_no_month" $APP_DIR/backend/routes/legacy_import.py || true

echo ""
echo "✅ Deploy Iter 342 complete! (backend-only — no web rebuild needed)"
echo "   NEXT STEPS to get the offline records:"
echo "   1. Login as Super Admin → Legacy Import."
echo "   2. Select the firm(s) → tick 'Offline Salary' → Import."
echo "   3. Check the job report: offline_rows should now be > 0."
echo "      (If offline_skipped_no_month > 0, send me that number.)"
echo "   4. Open the firm → Legacy Salary → 'Publish months to ACTUAL"
echo "      Salary Process' to see them under Actual Salary."
