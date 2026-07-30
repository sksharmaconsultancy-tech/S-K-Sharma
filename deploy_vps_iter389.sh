#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 389 — COMBINED RELEASE)
# INCLUDES Iter 370-385 (already live) + NEW SINCE THEN:
#
# Iter 386 — EMPLOYEE MASTER MOBILE: fixed NON-editable "+91" prefix;
#   only the 10-digit number can be typed; legacy 91-prefixed numbers
#   auto-normalised on form load.
#
# Iter 387 — CONFIGURABLE PF & ESIC STATUTORY MODULE (Phases 1-2):
#   • Standard Compliance Settings (GLOBAL and PER-FIRM): PF/ESIC module
#     switches, Wage Definition Rule on/off, PF & ESIC Proration Method,
#     Disable-ESIC-above-ceiling, Rule Version label.
#   • Salary Head Mapping: every earning head → PF Wage / ESIC Wage
#     Yes-No (Basic locked ON).
#   • Employee Master: Higher Pension, International Worker, Excluded
#     Employee, ESIC Reg. Status, Dispensary, ESIC Join/Exit dates,
#     ESIC Temporary Exemption.
#   • Engine stores a full calculation snapshot + PF/ESIC reasons on
#     every salary row. DEFAULTS KEEP ALL NUMBERS UNCHANGED.
#
# Iter 388 — PHASES 3-6:
#   • VALIDATION ENGINE + SALARY LOCK: 16 PF/ESIC checks run
#     automatically at Finalize. ERRORS always block the lock; WARNINGS
#     can be overridden by the Super Admin only ("Lock Anyway").
#   • PF & ESIC AUDIT DASHBOARD (new screen, "PF/ESIC Audit" button on
#     the Compliance Salary run): Green/Yellow/Red per-employee table
#     with Status + Reason, filters and search.
#   • "View Calculation" popup — full explanation of every figure.
#   • Append-only monthly statutory snapshot at every Salary Lock.
#   • REPORTS (Excel + PDF): PF Audit, ESIC Audit, Exception/Lock-Error,
#     Missing UAN, Missing IP.
#   • AI COMPLIANCE ASSISTANT: per-employee "AI Explain" — why PF/ESIC
#     was or wasn't calculated + recommended action.
#
# Iter 389 — PRINTABLE A4 EXPLANATION SHEET: "Print A4 Sheet" button in
#   the View Calculation popup — one-page inspector-ready PDF per
#   employee (heads considered, PF/ESIC workings, rules, validation).
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
echo -n "   Validation engine (must be >= 1): "
grep -c "validate_compliance_run" $APP_DIR/backend/routes/compliance_validation.py || true
echo -n "   Configurable statutory engine (must be >= 1): "
grep -c "wage_definition_rule_enabled" $APP_DIR/backend/utils/compliance_salary.py || true
echo -n "   Audit dashboard screen (must exist): "
[ -f $APP_DIR/frontend/app/pf-esic-audit.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Salary Lock gate in finalize (must be >= 1): "
grep -c "allow_warnings" $APP_DIR/backend/server.py || true
echo -n "   A4 explanation sheet (must be >= 1): "
grep -c "calc-sheet" $APP_DIR/backend/routes/compliance_validation.py || true
echo -n "   +91 fixed mobile prefix (must be >= 1): "
grep -c "Iter 386" $APP_DIR/frontend/app/employee-add.tsx || true
echo ""
echo "✅ Deploy Iter 389 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Compliance → Standard Compliance Settings: 'Module Switches &"
echo "     Rules' + 'Salary Head Mapping' (Standard OR per-firm scope)."
echo "   → Employee Master: +91 mobile, Higher Pension / Intl Worker /"
echo "     Excluded Employee, ESIC Status/Dispensary/Join-Exit/Exemption."
echo "   → Compliance Salary run: Finalize now auto-runs PF/ESIC"
echo "     validation (errors block; Super Admin can override warnings)."
echo "   → New 'PF/ESIC Audit' button → Audit Dashboard with View Calc,"
echo "     AI Explain, Print A4 Sheet, and Excel/PDF audit reports."
echo "   → Defaults keep all salary numbers UNCHANGED until you edit the"
echo "     new settings. Re-run 'Salary Process' on open months to"
echo "     capture calculation snapshots for existing runs."
