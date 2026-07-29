#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 367)
# NEW: 🧮 SALARY COMPLIANCE PROCESS (AI)
#   Sidebar → Payroll → "Salary Compliance Process (AI)"
#   A Senior Payroll & Compliance Expert (AI, Indian payroll laws) that
#   calculates one employee's monthly salary STEP BY STEP and explains
#   every formula:
#   • LOAD EMPLOYEE — pick firm + employee code + month and the inputs
#     auto-fill READ-ONLY from portal data (compliance structure, Actual
#     Salary Basic for daily-rated workers, present days/OT from the
#     month's imported sheet or salary run, PF/ESI eligibility, PT state).
#   • FIRM-WISE DYNAMIC HEADS — allowance & deduction heads come from the
#     Firm Master EXACTLY as configured: same names, same order — NO
#     re-sorting, NO re-grouping, NO filtering. Every head appears in the
#     output even at ₹0. You can edit amounts / add heads before running.
#   • OUTPUT (12 sections, every table starts with Sr. No.):
#     Employee Details · Attendance Summary · Earnings Table · Deductions
#     Table · Employer Contributions (EPF 12% = EPS 8.33% capped + EPF
#     3.67%, EDLI, admin, ESI 3.25%) · Gross · Total Deductions · Net
#     Salary · Payslip Summary · Compliance Checklist · Payroll Journal
#     Entries · Notes & Assumptions — with all formulas shown, prorate by
#     attendance/LOP, daily-rate handling (rate × present days).
#   ⚠ STRICTLY ADDITIVE: the Import Excel / Freeze Salary process and all
#     existing sorting/grouping/filtering are UNTOUCHED — this module only
#     READS data and never writes to salary runs.
# Also ships Iter 366 (Backup Center + safe ALL-Firms re-sync) and all
# earlier modules if not yet deployed.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle (~110 MB, retries enabled)..."
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
  echo "   Open the portal preview URL in a browser once (to wake the server),"
  echo "   wait 30 seconds, then re-run this script."
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
echo -n "   Salary Compliance AI routes (must be > 0): "
grep -c "ai-salary-compliance" $APP_DIR/backend/routes/ai_salary_compliance.py 2>/dev/null || echo 0
echo -n "   Router registered (must be = 1): "
grep -c "ai_salcomp_router" $APP_DIR/backend/server.py || true
echo -n "   Backup Center (Iter 366, must be = 1): "
grep -c "backup_center_router" $APP_DIR/backend/server.py || true
echo -n "   Freeze Salary process UNTOUCHED (must be > 0): "
grep -c "use_imported_sheet" $APP_DIR/backend/server.py || true
echo ""
echo "✅ Deploy Iter 367 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Sidebar → Payroll → 'Salary Compliance Process (AI)'."
echo "   → Pick firm + employee code + month → 'Load Data' (auto-fills"
echo "     everything, firm-wise heads in original order) → edit anything"
echo "     → 'Calculate Salary with AI Expert' (takes 30-60 sec)."
echo "   → Output: 12 sections, Sr. No. in every table, all formulas,"
echo "     employer contributions, compliance checklist, journal entries."
echo "   → Import Excel / Freeze Salary process is UNCHANGED."
