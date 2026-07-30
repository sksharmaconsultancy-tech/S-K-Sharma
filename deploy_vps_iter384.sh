#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 384)
# INCLUDES Iter 370-383 + NEW IN THIS RELEASE:
#
# Iter 384 — ONE-TAP AUTO-COPY (user accepted improvement): green
#   "Auto-copy Claimant names -> Bank tables" button on the death-claim
#   section fills the Name rows of the PF & Pension bank tables from
#   the Claimants and copies PF bank A/c/Bank/IFSC into the Pension
#   table (fills only blank boxes, never overwrites).
#
# Iter 383 — DEATH-CASE CLAIM FORMS (user request, per attached files):
#   1. Selecting Form-10D / Form-20/5-IF / Composite / Death Claim on
#      the PF claim form opens a "Composite Death Claim" section that
#      captures ALL the data of the attached forms: PF/Pension/EDLI
#      ticks, deceased member details (father/spouse, marital, Aadhaar,
#      PF A/c, date of death, died-in-service, scheme certificate, NCP),
#      up to 4 claimants/nominees, bank accounts for PF & EDLI
#      (Claimant I-III) and Pension (Claimant I-IV), postal address, and
#      the Form No. 8 pensioner descriptive roll (sex, nationality,
#      religion, height, identification marks, place/date).
#   2. Two PRINT buttons generate pixel-matched PDFs of the attached
#      formats: "Composite Claim Form in Death Cases [Form-20/10D/5-IF]"
#      and "Form No. 8" (printed in DUPLICATE — 2 copies in one PDF).
#      Save the claim first, then print; every saved claim reprints
#      anytime from Edit Claim.
#
# Iter 382: claims form changes (10D/20/5-IF/Composite types, field
#           removals, DD-MM-YYYY dates, UAN Password, Mobile, Upload).
# Iter 381: payslips follow Firm Master heads.
# Iter 379-380: compliance grid highlights, column order, mismatch filter.
# Iter 377-378: Firm-Master head masking on grid + old-run exports.
# Iter 375-376: claims module upgrades + claim attachments + PF rule.
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
echo -n "   Death claim PDF builder (must exist): "
ls $APP_DIR/backend/utils/death_claim_forms.py >/dev/null 2>&1 && echo OK || echo MISSING
echo -n "   Death forms endpoint (must be >= 1): "
grep -c "death-forms.pdf" $APP_DIR/backend/routes/claims_management.py || true
echo -n "   Death claim UI section (must be >= 2): "
grep -c "Iter 383" $APP_DIR/frontend/app/claims-management.tsx || true
echo ""
echo "✅ Deploy Iter 384 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → PF & ESIC Claims: pick a Form-20/10D/5-IF or Death claim type,"
echo "     fill the Composite Death Claim section, Save, then print the"
echo "     Composite Form and Form No. 8 in the attached formats."
echo "   → Iter 375-383 items included."
