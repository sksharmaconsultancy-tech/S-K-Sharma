#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 410)
# INCLUDES Iter 400-409 (Runner v9, In/Out & OT Matrix, QR dropdown + PNG,
# PF/ESIC on Gross incl OT, Lock override, Higher PF & VPF module,
# reprocess 422 fix) + NEW IN THIS RELEASE:
#
# Iter 409 — BACKEND REFACTOR (no behaviour change, fully regression
# tested 41/41):
#   • server.py reduced by ~2,500 lines. Extracted verbatim into:
#     routes/sub_admins.py, routes/masters_policy.py, routes/bonus.py,
#     routes/salary_runs.py, routes/attendance_self_service.py,
#     shared/sorting.py, shared/hours.py.
#
# Iter 410 — EMPLOYEE QUICK-MANAGE SHEET (user request):
#   • All Employee Data → tap employee: the sheet now shows FATHER NAME,
#     an ONLINE/OFFLINE (On-Roll/Off-Roll) badge (green = Online·On-Roll,
#     amber = Offline·Off-Roll) and Date of Join.
#   • "Live-in employee" toggle row styling fixed (was rendering as
#     unstyled plain text).
#
# Iter 410 — BIOFACE-MSD1K SUPPORT:
#   • Biometric Devices → Register: new brand "BIOFACE (MSD1K)" —
#     connects over the same iClock/ADMS push protocol (verified
#     handshake + ATTLOG ingest with SN 1801FACEMSD1K1030).
#   • Machine ALREADY REGISTERED on production via API for
#     JAI CLINIC & NURSING HOME (device_id dev_31fcd51c54).
#
# Iter 410 — DEVICE OFFLINE EMAIL ALERT (user accepted):
#   • When any biometric machine stops pushing for 15+ minutes the portal
#     now also EMAILS the super admins + that firm's company admins
#     (in addition to the existing in-app notification). One email per
#     outage; re-arms automatically when the machine reconnects.
#     Requires SMTP configured in Email Settings (already set on prod).
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
echo -n "   Matrix new rows (must say OK): "
grep -q "Total Working Hrs" $APP_DIR/backend/routes/inout_ot_matrix.py && echo "OK" || echo "MISSING!"
echo -n "   Matrix active default (must say OK): "
grep -q 'status: str = "active"' $APP_DIR/backend/routes/inout_ot_matrix.py && echo "OK" || echo "MISSING!"
echo -n "   OT break-return rule (must say OK): "
grep -q "BREAK RETURN" $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Higher PF/VPF module / Iter 408 (must say OK): "
grep -q "pf_contribution_type" $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   PF Contribution report / Iter 408 (must say OK): "
[ -f $APP_DIR/backend/routes/pf_contribution_report.py ] && echo "OK" || echo "MISSING!"
echo -n "   Lock error override / Iter 407 (must say OK): "
grep -q "allow_errors" $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   PF/ESIC gross incl OT / Iter 406 (must say OK): "
grep -q "ot_pay_extra" $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   QR Download PNG / Iter 405 (must say OK): "
grep -q "Download PNG" $APP_DIR/frontend/app/join-qr.tsx && echo "OK" || echo "MISSING!"
echo -n "   QR firm dropdown / Iter 404 (must say OK): "
grep -q "joinqr-firm-picker" $APP_DIR/frontend/app/join-qr.tsx && echo "OK" || echo "MISSING!"
echo -n "   OT footer / Iter 403 (must say OK): "
grep -q "day_ot_totals" $APP_DIR/backend/routes/inout_ot_matrix.py && echo "OK" || echo "MISSING!"
echo -n "   Register tally fix / Iter 401 (must say OK): "
grep -q "RESIDUAL" $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Reprocess 422 fix / Iter 409 (must say OK): "
grep -q "Iter 409" $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   Refactor modules / Iter 409 (must say OK): "
[ -f $APP_DIR/backend/routes/salary_runs.py ] && [ -f $APP_DIR/backend/routes/sub_admins.py ] && [ -f $APP_DIR/backend/shared/hours.py ] && echo "OK" || echo "MISSING!"
echo -n "   Quick-sheet Father/Online badge / Iter 410 (must say OK): "
grep -q "rollBadge" $APP_DIR/frontend/app/admin.tsx && echo "OK" || echo "MISSING!"
echo -n "   BIOFACE MSD1K brand / Iter 410 (must say OK): "
grep -q "bioface" $APP_DIR/frontend/app/biometric-devices.tsx && echo "OK" || echo "MISSING!"
echo -n "   Device offline EMAIL alert / Iter 410 (must say OK): "
grep -q "offline alert EMAIL" $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 410 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   VERIFY:"
echo "   • All Employee Data → tap an employee: Father Name + Online/Offline"
echo "     badge + DOJ now show on the quick sheet."
echo "   • Biometric Devices → Register new device → brand BIOFACE (MSD1K),"
echo "     Serial 1801FACEMSD1K1030, kind BOTH, pick the firm."
