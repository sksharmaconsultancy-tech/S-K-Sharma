#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 500)
#
# NEW IN 500 — EMPLOYEE-WISE CTC MODULE (all 3 phases):
#
#   PHASE 1 — MASTERS (Salary Process → CTC Management):
#     • Company Salary Mode per firm: Gross Only / CTC Only / Mixed —
#       existing Gross firms need to change NOTHING.
#     • CTC Structure Master with a dynamic formula builder:
#       components = Earnings / Employer Contributions / Employee
#       Deductions, each computed as % of Basic/Gross/CTC (with wage caps
#       like PF 15,000 & ESIC 21,000), Fixed ₹, or Balance.
#     • 3 auto-seeded default templates per firm: Standard Office CTC,
#       Compliance/Labour CTC, Flexible/Custom (blank builder).
#     • Live "Preview Breakup" — enter any Monthly CTC and see Basic, HRA,
#       employer PF/ESIC/Gratuity/Bonus, deductions and Net instantly
#       (Gross + Employer always = CTC to the rupee).
#
#   PHASE 2 — EMPLOYEE ASSIGNMENT + SALARY PROCESSING:
#     • Employee Register tab: assign Gross or CTC mode per employee with
#       Monthly CTC, structure, effective date + reason. Full revision
#       history (old/new CTC, difference, approved-by) is kept.
#     • Compliance Salary Process now understands CTC employees: their
#       gross is derived automatically from the CTC structure
#       (gross = CTC − employer cost) and then EVERYTHING runs exactly as
#       before — proration, PF, ESIC, PT, OT. Gross-mode employees are
#       processed 100% UNCHANGED (backward compatible).
#
#   PHASE 3 — REPORTS, PAYSLIPS & DASHBOARD:
#     • CTC dashboard cards: CTC employees, Total Monthly/Annual CTC,
#       Employer Cost, Net Payout, Avg CTC + per-structure distribution.
#     • Employee CTC Register + Revision History grids with the universal
#       PDF/Excel export buttons.
#     • YEARLY PROJECTION (appraisal report): per employee — projected
#       annual cost (CTC / Gross × 12) vs ACTUAL paid + employer statutory
#       cost YTD from the FY's Compliance runs (Apr–Mar), with months
#       paid, variance and % of annual used + TOTAL footer + PDF export.
#     • ONE-CLICK INCREMENT LETTER: in Revision History, the 📄 Letter
#       button generates a Salary Increment / Revision letter PDF on the
#       firm letterhead — OLD vs NEW CTC breakup side-by-side (Basic, HRA,
#       employer PF/ESIC…), increase amount + %, reason, effective date,
#       employee acknowledgement + authorised signatory.
#     • Payslips of CTC employees get a "CTC ANNEXURE" section showing
#       employer contributions + Monthly CTC (Gross + Employer).
#
# INCLUDES Iter 499 (group filter fix, Priority Tasks, Factory & Boiler
# Annual Return, smarter menu search) and everything before.
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
echo -n "   Server Version badge shows 500 (must say OK): "
grep -q 'APP_ITERATION = "500"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   CTC module backend (must say OK): "
[ -f $APP_DIR/backend/routes/ctc_module.py ] && grep -q 'ctc_router' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   CTC Management screen + menu entry (must say OK): "
[ -f $APP_DIR/frontend/app/ctc-management.tsx ] && grep -q 'ctc-management' $APP_DIR/frontend/src/components/AdminWebShell.tsx && echo "OK" || echo "MISSING!"
echo -n "   CTC hook in Compliance Salary engine (must say OK): "
grep -q 'CTC MODE (additive)' $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   Payslip CTC Annexure (must say OK): "
grep -q 'CTC ANNEXURE' $APP_DIR/backend/utils/payslip_pdf.py && echo "OK" || echo "MISSING!"
echo -n "   Yearly CTC Projection report (must say OK): "
grep -q 'yearly-projection' $APP_DIR/backend/routes/ctc_module.py && grep -q 'ctc_yearly_projection' $APP_DIR/frontend/app/ctc-management.tsx && echo "OK" || echo "MISSING!"
echo -n "   Increment Letter PDF (must say OK): "
[ -f $APP_DIR/backend/utils/ctc_increment_letter.py ] && grep -q 'increment-letter' $APP_DIR/frontend/app/ctc-management.tsx && echo "OK" || echo "MISSING!"
echo -n "   Iter 499 features still present (must say OK): "
[ -f $APP_DIR/backend/routes/factory_returns.py ] && grep -q 'flatNavDeep' $APP_DIR/frontend/src/components/AdminWebShell.tsx && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 500 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 500'."
echo "   2. Menu: Salary Process → CTC Management. Pick a firm →"
echo "      3 default templates appear (Standard Office / Compliance /"
echo "      Flexible). Set the Company Salary Mode chips."
echo "   3. Open a template → Preview Breakup with e.g. 30000 → Basic,"
echo "      HRA, Employer PF/ESIC, Net; Gross + Employer = CTC exactly."
echo "   4. Employee Register tab → pencil icon → switch an employee to"
echo "      CTC, enter Monthly CTC + structure → Save. Revision History"
echo "      tab records the change."
echo "   5. Run the Compliance Salary for that month — the CTC employee's"
echo "      gross auto-derives from CTC; all other employees unchanged."
echo "   6. That employee's payslip now ends with the CTC ANNEXURE table."
echo "   7. CTC Management → 'Yearly Projection' tab → pick FY → per-"
echo "      employee projected annual vs actual paid + employer cost YTD"
echo "      with variance & totals; PDF button exports the grid."
echo "   8. Revision History tab → 📄 Letter icon on any revision →"
echo "      downloads the Increment Letter PDF (old vs new CTC breakup"
echo "      on the firm letterhead, increase % and signatory block)."
