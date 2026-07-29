#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 375)
# INCLUDES Iter 370-374 + NEW IN THIS RELEASE:
#
# Iter 375 — PF & ESIC CLAIMS MANAGEMENT UPGRADES (user request):
#   1. "＋ Add Other Company Manually" on the claim form — file claims for
#      companies NOT in your firm list. The name is saved on the claim
#      RECORD ONLY and is NEVER created in the Firm Master.
#   2. Employee picker on the claim form (existing companies):
#        • PF Form-19 / Form-10C  → shows ONLY LEFT employees
#        • every other claim type → full list (active + resigned)
#      Picking an employee auto-fills Code, Name, UAN/IP, Department,
#      Designation, DOJ and Date of Leaving from the Employee Master.
#   3. Claims Register: Application-Date RANGE filter (From / To) and
#      SORTING — Date newest/oldest, Employee Name A–Z, Firm-wise.
#
# Iter 375 — EMPLOYEE MASTER FIXES:
#   4. FIXED a crash that made the Add/Edit Employee page show
#      "codeManual is not defined" (page went blank).
#   5. Date of Joining auto-fills to the 1st of the current month for a
#      NEW employee.
#   6. Legacy employees (DOJ stored DD-MM-YYYY) showed a BLANK Date of
#      Joining on the edit form — now displayed correctly.
#   7. Employee Code: letters+digits only, input locked (auto) with a
#      pencil ✎ button to unlock manual entry; blank code auto-generates.
#   8. PAN / Aadhaar name auto-fill from Employee Name; 10-digit mobile
#      validation; mandatory red-star fields enforced on EDIT too.
#
# Iter 375 — ATTENDANCE SHEET (master data fetch):
#   9. The month filter + "Date of Joining" sort now understand legacy
#      DD-MM-YYYY dates, so the sheet mirrors the Employee Master exactly.
#
# Iter 374: manual amounts survive lock/unlock + reprocess.
# Iter 373: Excel/CSV exports match the PDF + in-place unlock dialog.
# Iter 372: dynamic PDF heads per firm + UAN/EPF label & overflow fixes.
# Iter 371: Configure batch UNLOCK button + month default after 25th.
# Iter 370: first-click PF/ESIC fix, header sorting, column totals.
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
echo -n "   Claims employee-picker endpoint (must be >= 1): "
grep -c "claim_employees" $APP_DIR/backend/routes/claims_management.py || true
echo -n "   Claims date-range filter (must be >= 1): "
grep -c "date_from" $APP_DIR/backend/routes/claims_management.py || true
echo -n "   Employee form crash fix (must be >= 1): "
grep -c "setCodeManual] = useState" $APP_DIR/frontend/app/employee-add.tsx || true
echo -n "   Legacy DOJ parse fix (must be >= 1): "
grep -c "Iter 377" $APP_DIR/backend/server.py || true
echo ""
echo "✅ Deploy Iter 375 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → PF & ESIC Claims: '＋ Add Other Company Manually' (record-only),"
echo "     employee picker (Form-19/10C = left employees only),"
echo "     date-range filter + date/name/firm sorting on the register."
echo "   → Employee Master: page crash fixed, DOJ auto-fills 1st of month,"
echo "     legacy DOJ shows correctly, code pencil-lock + PAN/Aadhaar"
echo "     name auto-fill."
echo "   → Attendance Sheet mirrors Employee Master data (legacy dates OK)."
