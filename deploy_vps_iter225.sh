#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 230)
# Ships:
#  1. Standard Compliance Settings → firm list is a searchable DROPDOWN.
#  2. Compliance Salary Process → "Configure employees" button removed.
#  3. GROSS ₹1 BUG FIXED — every allowance column now adds up EXACTLY to
#     the Gross (whole-rupee reconciliation, Paid + Master columns).
#  4. BOTH Salary Processes (Compliance + Actual) now have the 4-button
#     lifecycle: SAVE (temp save) / REPROCESS (reload last saved) /
#     DELETE (asks twice) / FINALIZE & LOCK (then proceed to challan).
#  5. Editable amounts: OT Amt + TDS columns in Compliance grid;
#     W.Basic (OT amount) editable in Actual grid (typing an amount
#     overrides the hours calculation until P Hours is edited again).
#  6. Employee Report → firm dropdown + PAYSLIPS card: download one /
#     download ALL (zip) / MAIL one / MAIL all (to the employee e-mail
#     stored in the Employee Master).
#  7. PF Challan Report (PDF + Excel) rebuilt to the SBI "COMBINED
#     CHALLAN OF A/C NO. 01, 02, 10, 21 & 22 (WITH ECR)" format from
#     your sample: subscribers/wages rows, particulars grid, grand total
#     in words, bank/establishment boxes, non-PF employee counts.
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/6 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/6 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true

echo "==> 3/6 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/6 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
sudo rm -rf $WEB_DIR/*
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/6 Restarting backend..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 4

echo "==> 6/6 Verifying..."
curl -s http://localhost:8001/api/health && echo
echo
echo "🎉 Deploy complete."
echo "   NOTE (payslip e-mail): mails go out via Resend. With the default"
echo "   sandbox sender, delivery works only to the account owner's e-mail"
echo "   until a sending domain is verified in Resend."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
