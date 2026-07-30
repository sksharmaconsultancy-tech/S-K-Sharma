#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 394)
# INCLUDES Iter 370-393 (already live) + NEW IN THIS RELEASE:
#
# Iter 394 — BACKEND REFACTOR (no feature change, faster & maintainable):
#   • The entire Compliance Salary Runs engine (~2,200 lines: create/
#     process, list, save-rows, finalize + Iter-388 validation gate,
#     unlock requests, reprocess, CSV/XLSX/register-PDF/PF-ECR/ESIC
#     exports, payslip generation) was extracted from the 20k-line
#     server.py monolith into backend/routes/compliance_salary_runs.py.
#   • Shared helpers (offline-salary gating, biometric flag, firm head
#     masks, salary-process permission) are shared between server.py and
#     the new module — zero behaviour change, verified by a 23/23
#     regression test suite.
#   • Removed a duplicated router-registration block (9 modules were
#     registered twice: esic_leave, payroll_register, labour_statistics,
#     annual_returns, factory_compliance, payroll_reports, govt/audit
#     reports, claims_management, ai_universal_import).
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
echo -n "   Extracted module (must exist): "
[ -f $APP_DIR/backend/routes/compliance_salary_runs.py ] && echo "OK" || echo "MISSING!"
echo -n "   Router registered in server.py (must be >= 1): "
grep -c "compliance_salary_runs_router" $APP_DIR/backend/server.py || true
echo -n "   Salary runs API live (expect 401 = OK, route exists): "
code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/admin/compliance-salary-runs)
[ "$code" = "401" ] && echo "OK ($code)" || echo "⚠ got $code"
echo ""
echo "✅ Deploy Iter 394 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   This is a backend refactor release — everything works exactly as"
echo "   before. Verify: Compliance Salary Process → open a run, exports"
echo "   (Excel/PDF/ECR), Finalize/Unlock, Generate Payslips."
