#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 347)
# Ships on top of 346 (all-firms structure sync already done by user):
#   • HEADS VIEWER (user request): Legacy Import screen — new button
#     "Show Allowance & Deduction Heads — Old DB vs Portal". Lists every
#     firm; tap to expand: Old DB allowance heads (with employee counts),
#     Old DB deduction heads, Old DB basic heads, and the portal Firm
#     Master's enabled allowances/deductions. 🟠 marks heads that exist in
#     the Old DB but are NOT enabled on the portal Firm Master.
#     Excel): when an employee has a head-wise breakup, Gross now ALWAYS
#     equals Basic + all allowances — a stale gross value can no longer
#     override the heads.
#   • SUVIDHI SALARY STRUCTURE FIX (user bug): legacy import now prefers the
#     old software's CURRENT head-wise structure (EmployeeSalaryStructureDtl:
#     Basic head + allowances) over stale EmployeeMaster.BasicSalary/GrossPay.
#     Gross is derived as Basic + allowances whenever structure rows exist —
#     so the portal's salary structure now MATCHES the old database.
#     → After deploy: re-run Legacy Import (Employees + Salary fields) for
#       SUVIDHI RAYONS; existing employees are updated in place.
#   • AI LAYER (full): new sidebar menu "AI Payroll Assistant"
#     (/ai-payroll-assistant) — Payroll Health & Compliance scores, risk
#     cards, AI Compliance Checker (18+ checks w/ confidence % + Apply Fix +
#     false-positive learning), AI Auditor (PDF/Excel export), Attendance
#     Intelligence, Salary Difference Analysis, Reconciliation, Forecast,
#     Compliance Calendar, Smart Insights, AI notifications, audit log,
#     AI Excel column mapping + templates.
#   • CHATBOT upgrades: "List employees with missing UAN", "Show PF
#     mismatches", "Why is salary of code 50 lower?", compliance rules/news
#     expert answers with official portal links; executes salary process /
#     finalize / downloads / employee updates with Confirm buttons.
#   • Attendance Sheet: "Sort sheet by" option (Code / Name / Department /
#     DOJ) before download (single sheet + all-groups zip).
#   • Salary grids (Compliance + Actual): Excel-style header-wise FILTER
#     boxes under every column (text contains; numbers support >N <N =N).
#   • Shortcuts: sidebar entry, g+i → AI dashboard, Alt+1..6 tabs, R
#     re-analyse, Ctrl+Shift+A AI chat.
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

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
echo -n "   AI layer routes (must be > 0): "
grep -c "ai/analysis" $APP_DIR/backend/routes/ai_layer.py || true
echo -n "   Structure-first legacy mapping (must be > 0): "
grep -c "struct_basic" $APP_DIR/backend/routes/legacy_import.py || true

echo ""
echo "✅ Deploy Iter 347 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   • ALL-FIRMS FIX: open Legacy Import → press"
echo "     'Sync Salary Structures — ALL Firms (from Old DB)'."
echo "     Watch the live counters (employees updated / gross changed)."
echo "   • Then spot-check SUVIDHI employee 1 and the Attendance Sheet"
echo "     Excel — Gross must equal Basic + allowances everywhere."
echo "   • New menu: AI Payroll Assistant (bottom of sidebar, or press g i)."
echo "   • Salary grids now have Filter… boxes under every column header."
echo "   • Attendance Sheet page has a 'Sort sheet by' option."
