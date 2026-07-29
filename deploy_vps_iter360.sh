#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 360)
# NEW PREMIUM MODULE: ✨ AI UNIVERSAL PAYROLL IMPORT
#   Sidebar → Payroll → "AI Universal Import" (/ai-universal-import)
#   Upload ANY payroll Excel/CSV → press "Analyze with AI" → done.
#
#   THE WIZARD (Microsoft-365 style, 5 steps):
#   1. UPLOAD — any Attendance Register, Salary Register, Employee
#      Master, PF/ESIC Wage Sheet, OT/Leave/Bank/Bonus/Arrear/Increment/
#      Contractor sheet or ANY custom Excel — no fixed format needed.
#   2. AI ANALYSIS —
#      · FILE TYPE auto-identified (top-3 candidates with confidence
#        when unsure — one click to pick)
#      · COMPANY auto-detected from the sheet text & matched to your
#        portal firms (fuzzy matching with % confidence)
#      · PAYROLL PERIOD auto-detected ("June 2026", "06/2026", filename…)
#      · SMART COLUMN RECOGNITION — "Emp Name" = "Worker Name" =
#        "Labour Name" → Employee Name. Rules first (fast, repeatable),
#        GPT only for leftovers. Below-90% confidence rows highlighted
#        amber for one-click confirmation. NO MANUAL MAPPING.
#   3. VALIDATION + AI SUGGESTIONS —
#      · EMPLOYEE MATCHING by Code → UAN → ESIC → Aadhaar → PAN →
#        Mobile → Name+DOB → fuzzy name, each with a confidence score;
#        unmatched rows offered as NEW employees.
#      · 20+ CHECKS: duplicate UAN/ESIC/Aadhaar/code/bank in file,
#        invalid UAN/ESIC/PAN/IFSC formats, negative salary/OT, present
#        days > calendar days, below minimum wage, PF/ESIC eligibility,
#        missing dept/designation…
#      · AI CORRECTION ENGINE: "Missing UAN → use from Employee Master",
#        "Gross differs >50% from last month — verify", nearest-name
#        suggestions, missing IFSC filled from master.
#      · "EXPLAIN ISSUES WITH AI" — plain-English explanation + how to
#        fix each error (GPT).
#   4. PREVIEW & ONE-CLICK IMPORT — valid/warning/error/new/updated
#      filters; choose targets: Employee Master (create+update),
#      Attendance+Salary (Freeze Sheet), Leave, Bonus/Arrear/Increment.
#      Error rows are skipped automatically. No duplicate imports
#      (a job can only be committed once).
#   5. AUTO PAYROLL + COMPLIANCE — right after import the month is
#      processed through your existing Compliance Salary engine
#      (Basic/HRA/PF/ESIC/PT/TDS/Net, Freeze-Salary allocation rules),
#      then an AI COMPLIANCE CHECK runs (PF deducted but UAN missing →
#      "ECR will reject", ESIC above ₹21k, negative net…) and one-click
#      buttons generate: PF ECR TXT · Payslips · Salary Register ·
#      PF/ESIC Challans · Bank Transfer File · Compliance Report.
#
#   SMART LEARNING — every import teaches the AI that client's format
#   (header fingerprint). Next month the same file is recognised
#   INSTANTLY (no AI call, 99% confidence, "learned" badge).
#   DASHBOARD — success rate, employees added/updated, payroll runs,
#   validation errors, templates learned, recent import history.
#   SECURITY — admin-only, immutable audit log of every upload/
#   validation/import, parsed temp rows deleted after processing.
#   PERFORMANCE — imports run in the background with a live progress
#   bar; files up to 25 MB.
#
#   Backend:  /app/backend/routes/ai_universal_import.py
#   Frontend: /app/frontend/app/ai-universal-import.tsx
#   Also ships Iter 359: PF & ESIC Claims Management (see deploy359).
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
echo -n "   AI Universal Import routes (must be > 0): "
grep -c "ai-import" $APP_DIR/backend/routes/ai_universal_import.py || true
echo -n "   AI import router registered (must be = 1): "
grep -c "ai_uimport_router" $APP_DIR/backend/server.py || true
echo -n "   Claims module (Iter 359, must be > 0): "
grep -c "pf_esic_claims" $APP_DIR/backend/routes/claims_management.py || true
echo -n "   AI Import UI (must be > 0): "
grep -c "Analyze with AI" $APP_DIR/frontend/app/ai-universal-import.tsx || true
echo ""
echo "✅ Deploy Iter 360 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   • NEW: Sidebar → Payroll → '✨ AI Universal Import'."
echo "   • Try it: upload ANY client salary/attendance Excel and press"
echo "     'Analyze with AI' — file type, company, month and every column"
echo "     are detected automatically. Confirm anything amber, Validate,"
echo "     then 'Import Now'."
echo "   • Auto Payroll ON by default: the month is processed through the"
echo "     Compliance Salary engine right after import, followed by the AI"
echo "     Compliance Check and one-click PF ECR / Payslips / Challans /"
echo "     Bank File buttons."
echo "   • The module LEARNS each client's format — the same file next"
echo "     month is recognised instantly (see 'Learned Templates' tab)."
echo "   • Also included: Iter 359 PF & ESIC Claims Management"
echo "     (Sidebar → Compliance → 'PF & ESIC Claims')."
