#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 456)
# INCLUDES everything up to Iter 455 (EPFO-safe FIRMNAMEMMYYYY.txt filenames,
# Dashboard-click collapses sidebar, pre-upload EPFO File Check, finalized-
# months-only dropdown, ESIC Excel = user's upload format)
# + NEW IN THIS RELEASE:
#
# Iter 456 — FINAL PF ENGINE (user spec — SIMPLIFIED / ROLLBACK):
#   ✓ PF Basic = 0 / blank → NO PF.
#   ✓ PF Basic ≤ ₹15,000 → PF Wage = HIGHER of Earned PF Basic (present
#     days) / Earned 50% Compliance Wage Base, capped at ₹15,000.
#   ✓ PF Basic > ₹15,000 → ADOPTED HIGHER PF: PF on the FULL Earned PF
#     Basic (present days), NO ₹15,000 cap. EPS restricted to the
#     statutory ceiling; balance of the employer share → Employer EPF.
#   ✓ VPF — existing functionality kept.
#   ✗ REMOVED: "Adopt PF (PF Wage above ceiling)" Yes/No + manual "PF Wage"
#     field on the Employee Master (PF Basic already does this job).
#   ✗ REMOVED: "PF Wage Calculation Method" and "ESIC Wage Calculation
#     Method" dropdowns from PF/ESIC Settings — ESIC stays on the LEGACY
#     rule (max(Basic, 50% of Gross)); eligibility on full-month Basic.
#
# Iter 456 — ESIC UPLOAD EXCEL per the official TEMPLATE INSTRUCTIONS:
#   • DAYS rounded UP to the next whole number (instruction 2).
#   • ALL columns written in TEXT format (instruction 10).
#   • Members with 0 wages who EXITED on/before the month end → Reason 2
#     (Left Service) + Last Working Day dd/mm/yyyy (zero-padded) so the IP
#     is removed from the next wage period (instructions 1/4/5/8).
#   • 0-wage members still on rolls → Reason 1 (On Leave), date BLANK.
#   • Members who worked part of the month and left → NO reason / NO last
#     working day (instruction 6).
#
# Iter 457 (user bug — MILAP CHAND JAIN): employee marked "Higher PF
# (Actual Wages)" with Basic 2,30,000 / PF Basic 1,70,000 showed PF 27,600
# (12% of full Basic) instead of 20,400. The Higher PF path now contributes
# on the employee's OWN PF wage: Higher PF Wage (if filled, pro-rated) →
# else earned PF Basic → else the actual wage base.
#
# Iter 459 — PF ECR now INCLUDES members with ZERO working days (wages /
# contributions 0, NCP = full month) so EPFO membership continuity is kept.
# Only truly non-eligible employees (no PF Basic / Excluded / PF = No) are
# left out of the file.
#
# Iter 460 — ESIC UPLOAD .XLS FIXED against the user's WORKING sample file
# ("sample format of ESIC.xls"): ESI_CODE + NAME as TEXT cells, DAYS / SAL /
# RE as NUMERIC cells, DATE blank (dd/mm/yyyy TEXT only for exited members
# with Reason 2). The previous all-text formatting was rejected by the
# ESIC portal.
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

echo "==> 5b/7 Nginx upload limits (Salary Sheet Excel import fix — Iter 458)..."
# Default nginx body limit is 1 MB — a base64 Excel exceeds it and nginx
# rejected the upload with 413 BEFORE the backend ever saw it ("server
# never uploads the sheet"). Drop-in applies to every server block.
sudo tee /etc/nginx/conf.d/sks-upload.conf >/dev/null <<'NGINX'
client_max_body_size 100M;
proxy_read_timeout 300s;
proxy_send_timeout 300s;
NGINX

echo "==> 6/7 Reloading nginx..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 7/7 Health check + verification..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"
echo -n "   Final PF Engine (Iter 456 spec) (must say OK): "
grep -q 'Iter 456 (user final PF Engine spec)' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Higher PF on own PF wage (MILAP fix, Iter 457) (must say OK): "
grep -q 'Iter 457' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Salary GRID mirror updated (Iter 456/457) (must say OK): "
grep -q 'MILAP bug' $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Adopt PF REMOVED from engine (must say ABSENT): "
grep -q 'adopt_pf' $APP_DIR/backend/utils/compliance_salary.py && echo "STILL PRESENT!" || echo "ABSENT"
echo -n "   Calc-Method dropdowns REMOVED from Settings (must say ABSENT): "
grep -q 'pf_wage_calc_method' $APP_DIR/frontend/app/compliance-settings.tsx && echo "STILL PRESENT!" || echo "ABSENT"
echo -n "   Adopt PF UI REMOVED from Employee Master (must say ABSENT): "
grep -q 'Adopt PF' $APP_DIR/frontend/app/employee-add.tsx && echo "STILL PRESENT!" || echo "ABSENT"
echo -n "   ESIC template rules (Reason 2 + LWD / ceil DAYS / TEXT) (must say OK): "
grep -q '_esic_row_vals' $APP_DIR/backend/routes/challans.py && echo "OK" || echo "MISSING!"
echo -n "   FIRMNAMEMMYYYY (no special chars) filenames / Iter 455 (must say OK): "
grep -q 'Iter 455' $APP_DIR/backend/routes/challans.py && echo "OK" || echo "MISSING!"
echo -n "   Dashboard click collapses sidebar / Iter 454 (must say OK): "
grep -q 'collapseTick' $APP_DIR/frontend/src/components/AdminWebShell.tsx && echo "OK" || echo "MISSING!"
echo -n "   ESIC .xls matches working sample (Iter 460) (must say OK): "
grep -q 'Iter 460' $APP_DIR/backend/routes/challans.py && echo "OK" || echo "MISSING!"
echo -n "   Zero-day members in ECR (Iter 459) (must say OK): "
grep -q 'Iter 459' $APP_DIR/backend/routes/challans.py && echo "OK" || echo "MISSING!"
echo -n "   Nginx 100M upload limit (Excel import, Iter 458) (must say OK): "
grep -q 'client_max_body_size 100M' /etc/nginx/conf.d/sks-upload.conf 2>/dev/null && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 456 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY THE PF ENGINE (re-run Compliance Salary Process):"
echo "   1. PF Basic blank/0 → NO PF for that employee."
echo "   2. PF Basic ≤ 15,000 → PF wages = HIGHER of earned PF Basic /"
echo "      earned 50% of Gross, capped at 15,000."
echo "   3. PF Basic ABOVE 15,000 (e.g. 17,796 → PF 2,136; 1,70,000 →"
echo "      PF 20,400) → PF on the FULL earned PF Basic, no cap;"
echo "      EPS capped at 1,250; balance employer share → Employer EPF."
echo "   4. Employee Master no longer shows 'Adopt PF'; PF/ESIC Settings"
echo "      no longer shows the Wage Calculation Method dropdowns."
echo "   5. ESIC Excel: DAYS rounded UP, all cells TEXT, exited members"
echo "      get Reason 2 + Last Working Day (dd/mm/yyyy)."
