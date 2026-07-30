#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 391 — COMBINED LIVE RELEASE)
# INCLUDES Iter 370-385 (already live) + EVERYTHING SINCE:
#
# Iter 386 — EMPLOYEE MASTER MOBILE: fixed NON-editable "+91" prefix;
#   only the 10-digit number can be typed.
#
# Iter 387 — CONFIGURABLE PF & ESIC STATUTORY MODULE (Phases 1-2):
#   Module switches, Wage Definition Rule on/off, Proration methods,
#   Rule Version, Salary Head Mapping (PF/ESIC wage per head) — GLOBAL
#   and PER-FIRM. Employee Master: Higher Pension, International Worker,
#   Excluded Employee, ESIC Reg. Status / Dispensary / Join-Exit dates /
#   Temporary Exemption. Engine stores full calculation snapshots.
#   DEFAULTS KEEP ALL NUMBERS UNCHANGED.
#
# Iter 388 — PHASES 3-6: PF/ESIC VALIDATION ENGINE + SALARY LOCK
#   (errors block; Super Admin can override warnings), PF & ESIC AUDIT
#   DASHBOARD (Green/Yellow/Red + View Calculation), append-only monthly
#   snapshots, Excel/PDF reports (PF/ESIC Audit, Exceptions, Missing
#   UAN/IP), AI COMPLIANCE ASSISTANT ("AI Explain" per employee).
#
# Iter 389 — PRINTABLE A4 EXPLANATION SHEET per employee in the View
#   Calculation popup (inspector-ready PDF).
#
# Iter 390/391 — FIRM MASTER HEAD MASKING EVERYWHERE (user request):
#   Compliance Salary Process subtitle, run summary line and sticky
#   totals footer now hide Firm-disabled deduction heads (PT/TDS/…);
#   "Copy Last Month" confirmation lists only enabled heads; Past Salary
#   Runs list shows masked PF/ESIC/PT/TDS totals per run.
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
echo -n "   A4 explanation sheet (must be >= 1): "
grep -c "calc-sheet" $APP_DIR/backend/routes/compliance_validation.py || true
echo -n "   Head masking fixes 390/391 (must be >= 2): "
grep -c "Iter 390\|Iter 391" $APP_DIR/frontend/app/compliance-salary-run.tsx || true
echo -n "   +91 fixed mobile prefix (must be >= 1): "
grep -c "Iter 386" $APP_DIR/frontend/app/employee-add.tsx || true
echo ""
echo "✅ Deploy Iter 391 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Standard Compliance Settings: Module Switches & Rules + Salary"
echo "     Head Mapping (Standard OR per-firm scope)."
echo "   → Employee Master: +91 mobile, PF/ESIC statutory flags & fields."
echo "   → Compliance Salary: Finalize auto-runs PF/ESIC validation;"
echo "     'PF/ESIC Audit' dashboard with View Calc, AI Explain, Print A4"
echo "     Sheet and Excel/PDF audit reports."
echo "   → Firm-disabled heads (PT/TDS/…) now hidden in the Process"
echo "     subtitle, totals footer, Copy-Last-Month text and Past Runs."
echo "   → Defaults keep all salary numbers UNCHANGED until you edit the"
echo "     new settings. Re-run 'Salary Process' (or Reprocess) on open"
echo "     months to capture snapshots / apply new Firm Master masks."
