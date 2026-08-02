#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 444)
# INCLUDES everything up to Iter 442 (11-point report corrections, Name
# LEFT-aligned, Remove-without-UAN/ESIC toggle, Download/Mail Reports modal
# with PDF1/PDF2/CSV/Excel + firm-email picker, Reports Hub Download/Mail)
# + NEW IN THIS RELEASE:
#
# Iter 443 — FREEZE AS ACTUAL GROSS (user request):
#   • Firms with Days Calculation Method = "Freeze as Actual Gross" now pull
#     the ACTUAL Salary Process run of the SAME month straight into the
#     Compliance Salary Process:
#       Total Gross  → Freeze (imported) gross — taken AS-IS
#       Adv          → Advance Deduction column
#       TDS          → TDS Deduction column
#       Other Ded.*  → Other Deductions column
#   • Remaining functions unchanged: days derived from the gross, statutory
#     recalculated, difference → OT / Other Allowances, FREEZE badge shown.
#
# Iter 443 — MASTER-LINKED DEDUCTION COLUMNS (user request):
#   • The Compliance Salary grid now shows ONLY the deduction columns
#     enabled in the Firm Master — ADVANCE and OTH. DEDUC. toggles hide or
#     show the Advance* / Other* columns dynamically (PF / ESI / PT / TDS
#     already followed the master). Disabled heads are not applied either
#     (no hidden deductions in Total Ded. / Net). CSV/Excel exports match.
#
# Iter 443 — PF & ESIC ON WAGE BASE (user directive):
#   • Statutory PF is calculated on the WAGE BASE — max(Basic earned,
#     50% of Gross Earning) — capped at the ₹15,000 ceiling, for every
#     PF-applicable employee. Applicability chain: Firm Master EPF/ESI
#     "Applicable" first, then Employee Master PF/ESIC flags. Employee
#     Master PF Basic still gates applicability (blank/0 ⇒ no PF) and
#     lifts the base when higher. ESIC stays on the same wage base.
#
# Iter 444 — "Standard Compliance Settings" renamed to "PF/ESIC Settings".
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle (~10 MB, retries enabled)..."
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
echo -n "   Freeze as Actual Gross import / Iter 443 (must say OK): "
grep -q 'actual_salary_freeze' $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   Master-linked Advance/Other columns (backend) / Iter 443 (must say OK): "
grep -q 'ded_mask.add("advance")' $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   Master-linked Advance/Other columns (grid) / Iter 443 (must say OK): "
grep -q 'hasDed("advance")' $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   PF on Wage Base capped ₹15,000 / Iter 443 (must say OK): "
grep -q 'PF-applicable' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   PF/ESIC Settings rename / Iter 444 (must say OK): "
grep -q 'PF/ESIC Settings' $APP_DIR/frontend/app/compliance-settings.tsx && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 444 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. FREEZE AS ACTUAL GROSS: Firm Master → Payroll Settings → Days"
echo "      Calculation Method = 'Freeze as Actual Gross'. Process the ACTUAL"
echo "      salary for the month first, then run the Compliance Salary"
echo "      Process — Total Gross / Adv / TDS / Other Ded. are imported"
echo "      from the Actual run (FREEZE badge + Freeze Salary column shown)."
echo "   2. MASTER-LINKED COLUMNS: Firm Master → Deductions — toggle"
echo "      ADVANCE / OTH. DEDUC. / TDS OFF → the columns disappear from the"
echo "      Compliance grid (and exports); toggle ON → they come back."
echo "      NOTE: to import Adv / TDS / Other Ded. from the Actual salary,"
echo "      those heads must be ENABLED in the Firm Master."
echo "   3. PF/ESIC ON WAGE BASE: process any compliance salary — PF wages ="
echo "      max(Basic, 50% of Gross) capped at ₹15,000 (Firm + Employee"
echo "      Master applicability respected). ESIC on the same wage base."
echo "   4. 'PF/ESIC Settings' title on the old Standard Compliance page."
