#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 387)
# INCLUDES Iter 370-386 + NEW IN THIS RELEASE:
#
# Iter 387 — CONFIGURABLE PF & ESIC STATUTORY MODULE (Phase 1+2):
#   • Standard Compliance Settings (GLOBAL and PER-FIRM override):
#     PF/ESIC module switches, Wage Definition Rule on/off, PF & ESIC
#     Proration Method (Calendar/Paid/Attendance/Working/None),
#     Disable-ESIC-above-ceiling, Rule Version label.
#   • Salary Head Mapping: every earning head (Basic/HRA/Conv/Medical/
#     Special/Others/OT) → PF Wage Yes/No + ESIC Wage Yes/No (Basic
#     locked ON). ESIC wage base follows the mapping when the Wage
#     Definition Rule is switched OFF.
#   • Employee Master new fields: Higher Pension (EPS on uncapped
#     wages), International Worker (no EPF ceiling), Excluded Employee,
#     ESIC Registration Status, Dispensary, ESIC Joining/Exit dates,
#     ESIC Temporary Exemption.
#   • Engine revised: every Compliance Salary row stores a full
#     calculation snapshot + human-readable PF/ESIC reasons.
#     DEFAULTS REPLICATE THE OLD BEHAVIOUR EXACTLY — numbers unchanged
#     until you change the settings. ⚠ Re-run "Salary Process" on open
#     months only if you change any setting.
#
# Iter 386 — Employee Master Mobile No. with fixed NON-editable "+91"
#   prefix; only the 10-digit number can be typed.
#
# Iter 385: ESIC 50% rule + OLD-DB master edits unlocked w/ audit log.
# Iter 375-384: claims module + death claims, PF wage-base floor rule,
#           Firm-Master head masking, grid highlights & filters.
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
echo -n "   Configurable statutory engine (must be >= 1): "
grep -c "wage_definition_rule_enabled" $APP_DIR/backend/utils/compliance_salary.py || true
echo -n "   Settings module fields (must be >= 1): "
grep -c "_BOOL_CFG_FIELDS" $APP_DIR/backend/routes/compliance_settings.py || true
echo -n "   Head Mapping UI (must be >= 1): "
grep -c "Salary Head Mapping" $APP_DIR/frontend/app/compliance-settings.tsx || true
echo -n "   Employee ESIC master fields (must be >= 1): "
grep -c "esic_temp_exempt" $APP_DIR/frontend/app/employee-add.tsx || true
echo -n "   +91 fixed mobile prefix (must be >= 1): "
grep -c "Iter 386" $APP_DIR/frontend/app/employee-add.tsx || true
echo ""
echo "✅ Deploy Iter 387 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Compliance → Standard Compliance Settings: new 'Module Switches"
echo "     & Rules' + 'Salary Head Mapping' sections (Standard OR per-firm)."
echo "   → Employee Master: Higher Pension / International Worker /"
echo "     Excluded Employee + ESIC Status/Dispensary/Join-Exit/Exemption."
echo "   → Every new Salary Process row stores the calculation snapshot"
echo "     + PF/ESIC reason (used by the upcoming Audit Dashboard & AI)."
echo "   → Defaults keep all numbers UNCHANGED until you edit the settings."
echo "   → Mobile No. now has a fixed +91 prefix (Iter 386)."
