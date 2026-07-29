#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 378)
# INCLUDES Iter 370-377 + NEW IN THIS RELEASE:
#
# Iter 378 — PDF / EXCEL / CSV EXPORTS OF OLD RUNS FOLLOW FIRM MASTER
# (user request): re-downloading the Compliance Salary Register (PDF),
# Excel or CSV of ANY old month — including "Copy Last Month" and
# legacy-imported runs — now shows ONLY the heads enabled in the Firm
# Master (e.g. Basic · HRA · Conv · Gross; Medical/Special/Others and
# PT/TDS columns are hidden when disabled), exactly matching the
# on-screen grid. New runs already followed this since Iter 372/373.
#
# Iter 377: Compliance Salary GRID shows only Firm-Master-enabled heads
#           (Master + Calculated columns), for all runs old & new.
# Iter 376: claim file attachments + PF wage-base floor rule
#           (< 15,000 → floor; >= 15,000 → PF on 15,000 ceiling).
# Iter 375: Claims filters/employee picker/add-other-company; Employee
#           Master crash fix + DOJ rules; attendance sheet legacy dates.
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
echo -n "   Old-run export mask helper (must be >= 4): "
grep -c "_ensure_firm_head_masks" $APP_DIR/backend/server.py || true
echo -n "   Firm Master grid mask fallback (must be >= 1): "
grep -c "fmMask" $APP_DIR/frontend/app/compliance-salary-run.tsx || true
echo -n "   Claim file attachments API (must be >= 1): "
grep -c "upload_claim_document" $APP_DIR/backend/routes/claims_management.py || true
echo -n "   New PF wage-base rule backend (must be >= 1): "
grep -c "Iter 376 (user rule, replaces Iter 254)" $APP_DIR/backend/utils/compliance_salary.py || true
echo ""
echo "✅ Deploy Iter 378 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → PDF/Excel/CSV of OLD compliance runs now show only the heads"
echo "     enabled in the Firm Master (matches the on-screen grid)."
echo "   → Iter 375-377 items included (claims, PF rule, grid masking)."
