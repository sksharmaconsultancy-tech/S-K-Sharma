#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 376)
# INCLUDES Iter 370-375 + NEW IN THIS RELEASE:
#
# Iter 376 — CLAIM DOCUMENT FILE ATTACHMENTS (user request):
#   1. Attach the ACTUAL scanned files (PDF / JPG / PNG, max 10 MB each)
#      to every PF/ESIC claim — Form-19 scan, cancelled cheque, Aadhaar,
#      medical certificates, etc. Pick the document type and press
#      "📎 Attach File" on the claim form (claim must be saved first).
#   2. Attaching auto-ticks the matching checklist item and logs a
#      timeline entry; deleting the last file un-ticks it.
#   3. View (opens in a new tab) / delete each file on the claim form;
#      attached files also listed in the Claims Register detail view.
#      → the claims register is now a complete DIGITAL FILE per employee.
#
# Iter 376 — PF WAGE BASE RULE (user confirmed):
#   4. "Wage base floor (% of gross)" now applies ONLY when the
#      employee's PF Basic is BELOW ₹15,000:
#        • PF Basic <  15,000 → PF wages = max(PF Basic, floor% × Gross
#          Earning), capped at ₹15,000.
#        • PF Basic >= 15,000 → floor ignored; PF calculated per the
#          ₹15,000 ceiling rule (pro-rated by attendance for monthly
#          staff).
#      Examples: Basic 8,000 + Gross 20,000 (50%) → wages 10,000;
#                Basic 8,000 + Gross 40,000 → wages 15,000 (capped);
#                Basic 18,000 → wages 15,000.
#      Applied in BOTH the backend engine and the live grid recompute.
#
# Iter 375: Claims — add-other-company (record only), employee picker
#           (Form-19/10C = left only), date-range + date/name/firm sort;
#           Employee Master crash fix + DOJ rules; attendance sheet
#           legacy-date fixes.
# Iter 370-374: salary lock/unlock, dynamic PDF/Excel heads, manual
#           amounts preserved, first-click PF/ESIC fix.
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
echo -n "   Claim file attachments API (must be >= 1): "
grep -c "upload_claim_document" $APP_DIR/backend/routes/claims_management.py || true
echo -n "   Claim attach UI (must be >= 1): "
grep -c "cl-attach-file" $APP_DIR/frontend/app/claims-management.tsx || true
echo -n "   New PF wage-base rule backend (must be >= 1): "
grep -c "Iter 376 (user rule, replaces Iter 254)" $APP_DIR/backend/utils/compliance_salary.py || true
echo -n "   New PF wage-base rule grid (must be >= 1): "
grep -c "Iter 376 (user rule, replaces Iter 254)" $APP_DIR/frontend/app/compliance-salary-run.tsx || true
echo ""
echo "✅ Deploy Iter 376 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → PF & ESIC Claims: save a claim, then 📎 Attach File (PDF/photo)"
echo "     per checklist document — view/delete inline, register shows"
echo "     the attached files too."
echo "   → PF wage base: floor % applies only when PF Basic < 15,000;"
echo "     PF Basic >= 15,000 → PF on 15,000 (ceiling rule)."
echo "   → All Iter 375 items included (claims filters, employee picker,"
echo "     Employee Master fixes, attendance sheet legacy dates)."
