#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 359)
# NEW MODULE: PF & ESIC CLAIMS MANAGEMENT SYSTEM
#   Sidebar → Compliance → "PF & ESIC Claims" (/claims-management)
#   • CLAIMS REGISTER — full lifecycle: Pending → Submitted → (Verified)
#     → Under Process → Approved / Rejected → Settled, with a complete
#     status TIMELINE (who changed what, when) per claim.
#   • 16 PF claim types (Form-19, Form-10C, Form-31, Transfer, Higher
#     Pension, Death/Nominee, KYC/Bank/Name/DOB corrections, Joint
#     Declaration...) and 11 ESIC benefit types (Sickness, Maternity,
#     Disablement, Dependants, Funeral, Medical Reimbursement, ABVKY...).
#   • FILE CLAIMS FOR ANY COMPANY — existing portal firms (employee data
#     auto-fills from Employee Master by employee code: name, UAN, IP,
#     dept, DOJ/DOL) OR "External / Other Company" with a free-text
#     company name (for outside consultancy clients).
#   • DOCUMENT CHECKLIST per claim kind (PF: signed form, cheque, Aadhaar,
#     PAN, KYC, Date-of-Exit, Joint Declaration · ESIC: claim form,
#     medical certificate, hospital papers, employer certificate...) with
#     one-tap received ticks — uploads logged into the timeline.
#   • SMART AI FEATURES:
#       - Claim Eligibility Checker (10+yrs service → Form-10D not 10C,
#         <6 months → no pension withdrawal, <5yrs → TDS warning w/ 15G,
#         ESIC Sickness → checks 9-month contribution history from
#         portal salary runs, invalid UAN/IP format detection)
#       - Document Completeness Score (0–100%) per claim
#       - Expected Settlement Date (learned from your own settled-claim
#         history; sensible defaults until history builds up)
#       - Duplicate Claim Detection (same employee + type + company open
#         claim → warning with the existing claim number)
#   • FOLLOW-UP REMINDER ENGINE — every open claim auto-gets a +7 day
#     follow-up date; "Follow-up Reminders" tab lists everything due.
#   • DASHBOARD — PF/ESIC counts, pending/approved/rejected/settled,
#     total claim ₹ vs settled ₹, average processing days, follow-ups
#     due today / 7 days / 30 days.
#   • REPORTS + EXPORTS — PF Claims Register, ESIC Claims Register,
#     Pending / Approved / Rejected Claims, Settlement Register — each
#     as on-screen table + Excel + PDF (company logo on PDF).
#   Backend: /app/backend/routes/claims_management.py (Mongo collection
#   pf_esic_claims). Frontend: /app/frontend/app/claims-management.tsx.
#
# Robust download (Iter 352): retries up to 5x, resumes, verifies the tar.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle (~110 MB, retries enabled)..."
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
  echo "   Open the portal preview URL in a browser once (to wake the server),"
  echo "   wait 30 seconds, then re-run this script."
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
echo -n "   Claims backend routes (must be > 0): "
grep -c "pf_esic_claims" $APP_DIR/backend/routes/claims_management.py || true
echo -n "   Claims router registered (must be = 1): "
grep -c "claims_router" $APP_DIR/backend/server.py || true
echo -n "   Claims UI screen (must be > 0): "
grep -c "Claims Management" $APP_DIR/frontend/app/claims-management.tsx || true
echo ""
echo "✅ Deploy Iter 359 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   • NEW: Sidebar → Compliance → 'PF & ESIC Claims'."
echo "   • Dashboard tab shows PF/ESIC totals, amounts, avg processing days."
echo "   • 'New Claim' tab: pick a portal firm (employee code auto-fills"
echo "     from Employee Master) OR '🌐 External / Other Company' and type"
echo "     the company name — for outside clients."
echo "   • Tick the document checklist → Save → see the Smart AI panel:"
echo "     eligibility warnings, document score %, expected settlement date,"
echo "     duplicate-claim alerts."
echo "   • 'Follow-up Reminders' tab lists claims due for follow-up."
echo "   • 'Reports' tab: PF/ESIC Registers, Pending/Approved/Rejected,"
echo "     Settlement Register — Excel + PDF export buttons top-right."
