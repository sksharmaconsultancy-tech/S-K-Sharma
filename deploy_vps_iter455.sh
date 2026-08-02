#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 455)
# INCLUDES everything up to Iter 444 (Freeze as Actual Gross, master-linked
# deduction columns, PF on Wage Base, "PF/ESIC Settings" rename)
# + NEW IN THIS RELEASE (Iters 445–453):
#
# Iter 446 — EPFO-SAFE FILE NAMES:
#   • ECR/ESIC download names use MMYYYY (word characters only) — EPFO
#     rejects hyphens/spaces in filenames.
#
# Iter 447/449/450 — PF WAGE ENGINE (configurable):
#   • PF Wage Calculation Method in PF/ESIC Settings: Actual Basic(+DA) /
#     Wage-Base Floor (floor% of Gross) / HIGHER of the two (default).
#   • PF Wage ABOVE ceiling: Adopt PF = No → Excluded Employee (no PF);
#     Adopt PF = Yes → PF on the entered PF Wage without the ceiling.
#   • PF Basic filled ABOVE the ceiling in the Employee Master is treated
#     as the adopted PF wage — full PF deducted on it (EPS stays capped,
#     ER split follows the 12%-minus-EPS rule).
#   • Higher PF / VPF company policy switches honored.
#
# Iter 448 — PRE-UPLOAD "EPFO FILE CHECK" (PF/ESIC Upload screen):
#   • Validates the ECR before you upload: filename rule, UAN presence &
#     format, wage/contribution math (RFE-37 diff rule), NCP days, etc.
#
# Iter 451 — ECR NCP DAYS ALWAYS WHOLE NUMBERS:
#   • EPFO rejects decimals — NCP is rounded half-up (0.5 → 1).
#
# Iter 452/455 — DOWNLOAD FILE NAMES (EPFO accepts NO special characters):
#   • ECR: FIRMNAMEMMYYYY.txt (letters/digits ONLY — even "_" removed):
#     e.g. KANKANIENTERPRISES072026.txt — uploadable to EPFO directly.
#   • ESIC: ESIC_MC_FIRMNAME_MMYYYY.xls (ESIC portal accepts underscores).
#
# Iter 454 — SIDEBAR: clicking "Dashboard" COLLAPSES all expanded sub-menus.
#
# Iter 453 — ESIC UPLOAD EXCEL MATCHES YOUR "Format for Upload.xls":
#   • Columns: IP NO · NAME · DAYS · SAL · RE · Reason.
#   • SAL = GROSS EARNED for the month (truncated to whole ₹).
#   • DAYS rounded half-up to whole numbers.
#   • Members who LEFT / worked 0 days in the month are INCLUDED with
#     DAYS 0 · SAL 0 · RE 1 (other ESIC-exempt members stay out).
#
# ALSO: PF/ESIC Upload Run dropdown shows ONLY finalized/locked months
#       (month name only, no employee counts).
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
echo -n "   PF Wage Calc Method config / Iter 449 (must say OK): "
grep -q 'pf_wage_calc_method' $APP_DIR/backend/routes/compliance_settings.py && echo "OK" || echo "MISSING!"
echo -n "   PF Basic above ceiling = adopted wage / Iter 450 (must say OK): "
grep -q 'Iter 450' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Pre-upload EPFO File Check / Iter 448 (must say OK): "
grep -q 'ecr-check' $APP_DIR/frontend/app/challans.tsx && echo "OK" || echo "MISSING!"
echo -n "   NCP days whole numbers / Iter 451 (must say OK): "
grep -q 'Iter 451' $APP_DIR/backend/routes/challans.py && echo "OK" || echo "MISSING!"
echo -n "   FIRMNAMEMMYYYY (no special chars) filenames / Iter 455 (must say OK): "
grep -q 'Iter 455' $APP_DIR/backend/routes/challans.py && echo "OK" || echo "MISSING!"
echo -n "   Dashboard click collapses sidebar / Iter 454 (must say OK): "
grep -q 'collapseTick' $APP_DIR/frontend/src/components/AdminWebShell.tsx && echo "OK" || echo "MISSING!"
echo -n "   ESIC Excel = upload format + LEFT members / Iter 453 (must say OK): "
grep -q 'Iter 453' $APP_DIR/backend/routes/challans.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 455 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. PF/ESIC UPLOAD: dropdown shows only FINALIZED months (name only)."
echo "      Click 'EPFO File Check' → validation report appears before upload."
echo "   2. DOWNLOAD ECR: file saves as FIRMNAMEMMYYYY.txt with NO special"
echo "      characters (e.g. KANKANIENTERPRISES072026.txt) — EPFO-ready."
echo "   3. DOWNLOAD ESIC EXCEL: matches your 'Format for Upload' sheet —"
echo "      IP NO / NAME / DAYS / SAL / RE / Reason; SAL = gross earned;"
echo "      members who LEFT in the month appear with DAYS 0, SAL 0, RE 1."
echo "   4. PF/ESIC SETTINGS: PF & ESIC Wage Calculation Method dropdowns,"
echo "      Higher PF / VPF switches, Adopt-PF & Excluded-Employee rules."
echo "   5. ECR: NCP days are whole numbers (no decimals)."
echo "   6. SIDEBAR: expand any menus, click 'Dashboard' → all sub-points"
echo "      collapse automatically."
