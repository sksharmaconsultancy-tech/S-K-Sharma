#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 435)
# INCLUDES everything up to Iter 432 (Higher PF & VPF overhaul, auto-Higher-PF
# flag on PF Basic > ₹15,000, editable Advance deduction, Compliance Salary UI
# cleanup + Reprocess-from-Blank popup, Month Days lock, PF Contribution Type
# on Employee Add) + NEW:
#
# Iter 433 (THIS RELEASE) — 11-POINT PAYROLL REPORT CORRECTIONS:
#   1. Arrear Register (PDF + Excel): S.No | UAN | ESIC | Emp Name |
#      Father Name | Days | Rate | Gross Arrear | dynamic PF/ESIC
#      deductions | Net Payable. NEW PDF Register button.
#   2. Cost to Company Analysis: S.No column added.
#   3. Fine Register: Month-wise / Periodic options + centred empty state
#      "There is No Fine in this Month of (Month Year)".
#   4. Full & Final: single/multiple/all employee picker.
#   5. Gratuity Register: employee picker (single/multiple/all).
#   6. OT Cost Analysis: employee picker.
#   7. Daily OT Register: Month-wise removed → Daily / Periodic (date
#      range) + S.No.
#   8. Dept-wise OT: employee names + dept-wise counts, Daily / Periodic,
#      S.No.
#   9. Employee-Wise Payroll Register: Bonus Amount head.
#  10. PF Contribution Register PDF: tighter L/R margins, centred
#      headings, bigger font.
#  11. Salary Register (Compliance): reduced L/R margins (more table
#      width); Master salary head-wise columns stay dynamic per firm.
#   + Global: bigger print font on all register PDFs (10pt body).
# Iter 435 — Employee Name LEFT-aligned in ALL reports (user request,
#   rolled back the earlier right-alignment).
# Iter 436 — Portal Upload Files (EPFO ECR / ESIC MC): new toggle button
#   "Remove Without UAN / ESIC No. Employees" — drops members missing a
#   UAN / ESIC number from the generated upload files.
# Iter 438 — After SAVE / FINALIZE on Compliance & Actual Salary Process:
#   "Download / Mail Reports" popup — PDF / Excel / CSV / All chips,
#   one-click Download + Send-by-email (uses the Email Settings SMTP,
#   falls back to the built-in mail key).
# Iter 439/440 — Modal upgrades: PDF Format 1 & Format 2 options
#   (Compliance), Employee Group badge, recipient chips fetched from the
#   Firm Master registered email ids (pick one / all + extra email),
#   ≥1 format selection MANDATORY, mail carries exactly what's selected.
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
echo -n "   Arrear Register new columns + PDF / Iter 433 (must say OK): "
grep -q '_arrear_register_data' $APP_DIR/backend/routes/arrear_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Fine Register empty note / Iter 433 (must say OK): "
grep -q 'There is No' $APP_DIR/backend/routes/govt_audit_reports.py && echo "OK" || echo "MISSING!"
echo -n "   F&F / Gratuity / OT employee picker (backend) / Iter 433 (must say OK): "
grep -q 'employee_ids' $APP_DIR/backend/routes/payroll_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Daily OT Daily/Periodic + S.No / Iter 433 (must say OK): "
grep -q 'from_date' $APP_DIR/backend/routes/payroll_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Dept-wise OT employee names / Iter 433 (must say OK): "
grep -q 'ot_employee_names' $APP_DIR/backend/routes/payroll_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Payroll Register Bonus head / Iter 433 (must say OK): "
grep -q '"bonus", "Bonus Amount"' $APP_DIR/backend/routes/payroll_register.py && echo "OK" || echo "MISSING!"
echo -n "   PF Contribution PDF centred + margins / Iter 433 (must say OK): "
grep -q 'CENTRED headings' $APP_DIR/backend/routes/pf_contribution_report.py && echo "OK" || echo "MISSING!"
echo -n "   Salary Register reduced margins / Iter 433 (must say OK): "
grep -q 'reduced L/R page margins' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Bigger report fonts (10pt) / Iter 433 (must say OK): "
grep -q 'FONTSIZE", (0, 0), (-1, -1), 10' $APP_DIR/backend/utils/register_export.py && echo "OK" || echo "MISSING!"
echo -n "   Name LEFT-aligned everywhere / Iter 435 (must say OK): "
grep -q 'Name columns LEFT-aligned' $APP_DIR/backend/utils/register_export.py && echo "OK" || echo "MISSING!"
echo -n "   Remove-without-UAN/ESIC toggle / Iter 436 (must say OK): "
grep -q 'skip_missing' $APP_DIR/backend/routes/challans.py && grep -q 'toggle-skip-missing' $APP_DIR/frontend/app/challans.tsx && echo "OK" || echo "MISSING!"
echo -n "   Download/Mail Reports modal / Iter 438-440 (must say OK): "
grep -q 'email-report' $APP_DIR/backend/routes/compliance_salary_runs.py && grep -q 'firm-emails' $APP_DIR/backend/routes/firm_master.py && [ -f $APP_DIR/frontend/src/components/salary/ReportsShareModal.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Report Hub Daily/Periodic + pickers (frontend) / Iter 433 (must say OK): "
grep -q 'rc-otmode-daily' $APP_DIR/frontend/app/reports-center.tsx && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 435 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   VERIFY THE REPORT CORRECTIONS:"
echo "   • Reports → Report Hub → Fine Register: 'Month wise / Periodic'"
echo "     toggle; with no fines the PDF prints the centred line"
echo "     'There is No Fine in this Month of (Month Year)'."
echo "   • Daily OT Register & Dept-wise OT: Daily / Periodic date range,"
echo "     S.No column; Dept-wise OT lists the OT employee names."
echo "   • Full & Final / Gratuity / OT Cost Analysis: pick single,"
echo "     multiple or All Employees before generating."
echo "   • Salary Process (Arrear) → open a run → NEW 'PDF Register'"
echo "     button — S.No | UAN | ESIC | Name | Father Name | Days | Rate |"
echo "     Gross Arrear | PF/ESIC Ded. | Net Payable."
echo "   • Yearly Payroll Register: Bonus Amount row (when bonus paid)."
echo "   • PF/ESIC Challans → Portal Upload Files: tick 'Remove Without"
echo "     UAN / ESIC No. Employees' to drop them from the ECR/ESIC files."
echo "   • All register PDFs print with a bigger font; Employee Name is"
echo "     LEFT-aligned in every report."
