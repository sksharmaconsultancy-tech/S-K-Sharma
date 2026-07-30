#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 382)
# INCLUDES Iter 370-381 + NEW IN THIS RELEASE:
#
# Iter 382 — PF & ESIC CLAIMS FORM CHANGES (user request):
#   1. New PF claim types: Pension (Form-10D), Death Claim
#      (Form-20 / 5-IF) and Composite Claim Form filing entry.
#   2. Removed fields: Department, Designation, Acknowledgement /
#      Ref No., Payment Reference (NEFT/UTR).
#   3. "Handled By (Executive)" auto-fills with the logged-in user's
#      name (still editable).
#   4. All dates (Application, Follow-up, Settlement, DOJ, DOL) are now
#      typed and shown as DD-MM-YYYY (stored internally as ISO so the
#      register date-range filter, sorting and reminders keep working).
#   5. New fields: UAN Password and Mobile No. (Mobile auto-fills from
#      the Employee Master when an employee is picked).
#   6. Attached Files: prominent "Upload Document" button (PDF/JPG/PNG,
#      max 10 MB, auto-ticks the checklist).
#
# Iter 381: payslips follow Firm Master heads.
# Iter 380: "Mismatch only" filter chip on compliance grid.
# Iter 379: grid column order Sr → UAN → ESIC → Name + highlights.
# Iter 378: PDF/Excel/CSV of OLD runs follow Firm Master heads.
# Iter 377: grid shows only Firm-Master-enabled heads.
# Iter 376: claim file attachments + PF wage-base floor rule.
# Iter 375: claims filters/employee picker; Employee Master fixes.
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
echo -n "   New PF claim types (must be >= 1): "
grep -c "Composite Claim Form" $APP_DIR/backend/routes/claims_management.py || true
echo -n "   Claims form changes (must be >= 2): "
grep -c "Iter 382" $APP_DIR/frontend/app/claims-management.tsx || true
echo -n "   Payslip firm-head masking (must be >= 1): "
grep -c "Iter 381" $APP_DIR/backend/utils/payslip_pdf.py || true
echo ""
echo "✅ Deploy Iter 382 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Claims form: Form-10D / Form-20/5-IF / Composite Claim types,"
echo "     Dept/Desg/Ack/Payment-Ref removed, Executive auto-fill,"
echo "     DD-MM-YYYY dates, UAN Password + Mobile No., Upload Document."
echo "   → Iter 375-381 items included."
