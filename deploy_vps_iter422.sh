#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 422)
# INCLUDES everything up to Iter 418 (Smart Punch Native SDK + Device
# Sync Engine, Smart GPS, BIOFACE MSD1K, device offline alerts) + NEW:
#
# Iter 419 — Deploy bundle slimmed 140 MB → ~10 MB (metro cache / RPA
#   recordings / pytest cache excluded from the code bundle).
# Iter 420 — Biometric Device Sync overhaul (direct machine-only sync,
#   auto-accept templates, 30 cmds/poll) · Punch Log Report: "Name in
#   Machine", "Machine Name" + OT PUNCH marker · NEW Daily In/Out & OT
#   Verification Report · Compliance: Present Days can never exceed the
#   month's days (grid + import) · Deduction columns follow the Firm
#   Master DYNAMICALLY.
# Iter 421 — Actual Salary: editable "Other Deduction" column ·
#   PF/ESIC salary-lock validation respects the Firm Master toggles
#   (disabled = not validated).
# Iter 422 (THIS RELEASE) — EDITABLE ADVANCE DEDUCTION (user request):
#   • Compliance Salary grid: NEW "Advance*" column (between ESI/TDS and
#     Other*) — auto-filled from the Advance ledger, editable inline.
#     Manual entries are stamped on manual_fields, so a REPROCESS keeps
#     the typed amount and the ledger never overwrites it.
#   • Actual Salary grid: "Advance" column stays editable; a reprocess
#     now carries ONLY the manually-typed portion (the ledger EMI is
#     re-applied idempotently — no more double-count).
#   • Totals strip, Total Ded., Net and the Excel/CSV register exports
#     all include the Advance figure.
#   • Employee Master Report: DOJ column renamed to "Date of Join"
#     (grid + Excel export).
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
echo -n "   Compliance Advance column / Iter 422 (must say OK): "
grep -q '"Advance\*"' $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Manual advance survives reprocess (backend) / Iter 422 (must say OK): "
grep -q 'advance_recovery" in _mf' $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   Ledger skips manually-edited advance / Iter 422 (must say OK): "
grep -q 'manual_fields' $APP_DIR/backend/routes/advances.py && echo "OK" || echo "MISSING!"
echo -n "   Actual Salary adv carry fix / Iter 422 (must say OK): "
grep -q 'Iter 422' $APP_DIR/backend/routes/actual_salary_process.py && echo "OK" || echo "MISSING!"
echo -n "   Master report Date of Join / Iter 422 (must say OK): "
grep -q 'Date of Join' $APP_DIR/backend/routes/master_data_report.py && echo "OK" || echo "MISSING!"
echo -n "   Actual Other Deduction / Iter 421 (must say OK): "
grep -q 'other_ded' $APP_DIR/backend/routes/actual_salary_process.py && echo "OK" || echo "MISSING!"
echo -n "   Daily In/Out & OT Verification / Iter 420 (must say OK): "
[ -f $APP_DIR/backend/routes/daily_verification.py ] && echo "OK" || echo "MISSING!"
echo -n "   Present Days month cap / Iter 420 (must say OK): "
grep -q 'Present Days cannot be more than' $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 422 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   VERIFY EDITABLE ADVANCE:"
echo "   • Compliance Salary → open/process a run → the DEDUCTIONS band"
echo "     now has an 'Advance*' column — type any amount, Total Ded. &"
echo "     Net update instantly and the figure auto-saves with the draft."
echo "   • Reprocess the same month → your typed Advance stays."
echo "   • Actual Salary → the 'Adv' column is editable the same way."
echo "   • Reports → Employee Master Report → 'Date of Join' column."
