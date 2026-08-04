#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 482)
#
# NEW IN 482 — "BOTH PUNCHES AVAILABLE BUT SHOWING MISSING" (user bug):
#   ROOT CAUSE: employee APP (mobile) punches wait in PENDING status until
#   an admin approves them (your Iter 83 rule) — the grid counts ONLY
#   approved punches, so a pending App OUT leaves the day as "missing OUT"
#   even though the Repair modal shows both punches.
#   FIX: the Repair Punches modal now TAGS pending punches with an amber
#   "PENDING — tap to approve" button. One tap approves the punch and the
#   IN/OUT pair completes instantly. (Bulk approvals remain in the
#   Punch Approvals screen.)
#
# NEW IN 481 — PUNCH DATA REPAIR (user request):
#   • 5-MINUTE DUPLICATE FILTER: punches from the SAME machine within
#     5 minutes are ignored — both at ingestion (new punches are skipped
#     the moment the machine pushes them) AND at display/salary compute
#     (existing stored duplicates are dropped on the fly, no data loss).
#   • ALTERNATION REPAIR: when a day's machine punches are all "IN" (the
#     double-punching corrupted the IN/OUT flip), the day is re-paired
#     automatically: first punch IN, next OUT, and so on.
#   • NIGHT-SHIFT AUTO-PAIRING: an early-morning punch (before 08:00)
#     following yesterday's unpaired IN is treated as that night shift's
#     OUT and pulled back to the previous day — no more "missing OUT" on
#     the night-duty rows and no stray "missing IN" the next morning.
#   • Applies everywhere: Attendance Grid, Daily Report, OT matrix,
#     salary day-counting, attendance doctor.
#
# NEW IN 480 — CLRA / LABOUR CODE PHASE 2 (user spec — statutory field
# enhancements + new statutory registers):
#   • WAGE REGISTER (FORM B): allowances split (Conveyance / Medical /
#     Special / Others), deductions split (PF / ESIC / PT / TDS /
#     Adv-Other), Bank A/c + IFSC column. Periodic + FORM heading kept.
#   • GRATUITY REGISTER: Total Service, Eligible Service, Wage Definition,
#     Last Drawn Wages, Gratuity Amount, Exempt / Taxable split (₹20 L
#     u/s 10(10)), Payment Date column.
#   • NEW in Report Hub → CLRA / Labour Code (Excel + PDF + Email):
#       PF REGISTER  — UAN, PF/EPS wages, EPF-EE, VPF, EPS-ER, EPF-ER,
#                      EDLI wages + 0.5%, NCP days, DOJ/DOE/Rejoin
#       ESIC REGISTER — IP, wages, 0.75% / 3.25%, Contribution Period,
#                      Benefit Period, TIC status
#       LWF REGISTER  — built-in slabs for 16 states (Maharashtra,
#                      Gujarat, Karnataka, TN, MP, Delhi, Haryana, Punjab,
#                      WB, AP, Telangana, Kerala, Goa, ...); firm state
#                      from Company/Firm Master; contribution-month aware
#       LEAVE REGISTER (EL LEDGER) — Opening, Days Worked (FY), Earned
#                      (1/20 days), Availed, Encashed, Carry-Fwd, Closing
#   • DAILY ATTENDANCE REGISTER (Labour Reports): + Contractor, Shift,
#     Punch Source, Late Minutes, Early-Out Minutes columns.
#
# NEW IN 479 — CLRA / LABOUR CODE PHASE 1 (user spec):
#   • CONTRACTOR MASTER (Masters → Contractor Master): full statutory
#     contractor records — licence no./issue/expiry, PAN, GSTIN, EPF/ESIC
#     codes, security deposit, max labour permitted, agreement window,
#     status — with live active-labour counts and licence/agreement
#     expiry warnings. Names already typed in Firm Master are auto-imported.
#   • REPORT HUB → new "CLRA / Labour Code" group with 6 registers
#     (Excel + PDF + Email): Contractor Register, Principal Employer
#     Register, Contract Labour Register, Professional Tax Register,
#     Employee Rejoin History, Compliance Dashboard.
#
# NEW IN 479 — DAILY REPORT PDF REDESIGN (user request):
#   • Renamed "Daily Report"; company name on 2nd row; date on the RIGHT.
#   • Removed Verified / Verified By / Remarks columns; Emp Code → BIO CODE.
#   • Summary block moved to the BOTTOM of every page + Page numbers.
#   • NEW "Only Present" filter (a single punch counts as present) on the
#     screen and all exports.
#
# NEW IN 479 — UX (user requests):
#   • "Rejoin Employee (Rehire)" button now also beside the Exit / Left
#     date in the employee sheet for resigned employees.
#   • Firm picker is always a DROPDOWN LIST (no more chip overflow).
# NEW IN 478 — EDITABLE REGISTER HEADINGS FROM THE PORTAL:
#   • Report Hub → open any Government Register → "Edit heading" pencil
#     (Super Admin): change the FORM heading lines right on the portal —
#     screen, PDF and Excel all use the saved text instantly. "Reset to
#     default" restores the built-in FORM B / FORM C text. No deploy
#     needed for future heading changes (per state / inspector wording).
#
# INCLUDES everything up to Iter 476 (Firm Master sticky unsaved-changes
# banner, ADMS port-80 nginx guarantee, Employee Rejoin module, biometric
# month-fetch, daily/monthly rate engine, ESIC wage-base, ECR runner v10).
# + NEW IN THIS RELEASE:
#
# Iter 477 — GOVERNMENT REGISTERS: FORM heading RESTORED + PERIODIC
#   (user request):
#   • Statutory FORM heading is back on ALL 5 Government Registers
#     (web view + PDF + Excel):
#       Wage Register      → FORM B — WAGE REGISTER
#       Fine / Deduction / Advance → FORM C — REGISTER OF LOANS/RECOVERIES
#       Gratuity Register  → [Under the Payment of Gratuity Act, 1972]
#     with the "[Ease of Compliance to Maintain Registers under various
#     Labour Laws Rules, 2017]" rule line under the FORM line.
#     The "There is No … in this Month of (…)" empty line stays.
#   • "Month wise / Periodic" (From Month → To Month) now available on ALL
#     FIVE registers (was Fine only): Wage & Deduction aggregate every
#     month in the range per employee; Gratuity picks Basic from the
#     latest processed month in the range.
#
# Iter 477 — COMPLIANCE SALARY PROCESS grid (user requests):
#   • OT Hrs column SHIFTED to sit right after Present Days (was between
#     OT Amt* and Gross). Totals row + section bands realigned.
#   • ESIC Leave column is now READ-ONLY — days are fetched from the ESIC
#     Leave Master (approved entries) at process time. When the ESIC Leave
#     module is linked, the master value is authoritative (0 when no
#     approved entry — manual typing removed).
#   • Server version badge now shows "Server Iter 477".
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/8 Downloading latest code bundle (~10 MB, retries enabled)..."
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

echo "==> 2/8 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 3/8 Installing backend deps..."
if ! command -v soffice >/dev/null 2>&1; then
  echo "   Installing LibreOffice Calc (one-time, ~2-4 min)..."
  sudo apt-get update -qq && sudo apt-get install -y --no-install-recommends libreoffice-calc >/dev/null 2>&1 || \
    echo "   ⚠ LibreOffice install failed — ESIC .xls will use the fallback writer"
fi
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP show emergentintegrations >/dev/null 2>&1 || \
  $PIP install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q

echo "==> 4/8 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/8 Restarting backend service..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend

echo "==> 6/8 Nginx upload limits (Iter 458)..."
sudo tee /etc/nginx/conf.d/sks-upload.conf >/dev/null <<'NGINX'
client_max_body_size 100M;
proxy_read_timeout 300s;
proxy_send_timeout 300s;
NGINX

echo "==> 6b/8 Nginx ADMS port-80 guarantee (Iter 476 — BIOFACE 301 fix)..."
sudo tee /etc/nginx/conf.d/sks-adms.conf >/dev/null <<'NGINX'
# Iter 476 — ZKTeco / BIOFACE ADMS push protocol.
# Machines speak PLAIN HTTP on port 80 and CANNOT follow 301 redirects.
server {
    listen 80;
    server_name _;
    location /iclock/ {
        proxy_pass http://127.0.0.1:8001/api/iclock/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 90s;
    }
    location /api/iclock/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 90s;
    }
    location / { return 404; }
}
NGINX
if grep -rqs "listen 80 default_server\|listen 80.*default_server" /etc/nginx/sites-enabled/ 2>/dev/null; then
  echo "   ⚠ NOTE: an existing nginx site declares 'default_server' on port 80."
  echo "     If machines still get 301s, add the /iclock/ location from"
  echo "     /etc/nginx/conf.d/sks-adms.conf into that site's port-80 block."
fi

echo "==> 7/8 Reloading nginx..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 8/8 Health check + verification..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"
echo -n "   Server Version badge shows 482 (must say OK): "
grep -q 'APP_ITERATION = "482"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Govt Registers FORM heading restored (Iter 477) (must say OK): "
grep -q 'FORM B — WAGE REGISTER' $APP_DIR/backend/routes/govt_audit_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Wage/Deduction/Gratuity periodic month range (Iter 477) (must say OK): "
grep -q 'Iter 477' $APP_DIR/backend/routes/govt_audit_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Periodic toggle on ALL 5 registers in Report Hub (must say OK): "
grep -q '"wage-register",' $APP_DIR/frontend/app/reports-center.tsx && echo "OK" || echo "MISSING!"
echo -n "   OT Hrs column after Present Days (Iter 477) (must say OK): "
grep -q 'OT Hrs shifted right after' $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   ESIC Leave read-only from ESIC Leave Master (Iter 477) (must say OK): "
grep -q '_esic_on' $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   Firm Master sticky unsaved-changes banner (Iter 476) (must say OK): "
grep -q 'dirtyBanner' $APP_DIR/frontend/app/firm-master.tsx && echo "OK" || echo "MISSING!"
echo -n "   ADMS port-80 nginx guarantee (Iter 476) (must say OK): "
grep -q 'iclock' /etc/nginx/conf.d/sks-adms.conf 2>/dev/null && echo "OK" || echo "MISSING!"
echo -n "   Employee Rejoin (Rehire) module (Iter 475) (must say OK): "
[ -f $APP_DIR/backend/routes/employee_rejoin.py ] && echo "OK" || echo "MISSING!"
echo -n "   Pending-punch approve in Repair modal (Iter 482) (must say OK): "
grep -q 'PENDING' $APP_DIR/frontend/src/components/PunchRepairModal.tsx && echo "OK" || echo "MISSING!"
echo -n "   5-min duplicate filter + night-shift pairing (Iter 481) (must say OK): "
grep -q 'dedupe_close_punches' $APP_DIR/backend/server.py && grep -q 'duplicate_within_5min_ignored' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   Phase 2 registers PF/ESIC/LWF/Leave (Iter 480) (must say OK): "
grep -q '_lwf_register' $APP_DIR/backend/routes/clra_labour_reports.py && grep -q '_pf_register' $APP_DIR/backend/routes/clra_labour_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Wage Register Form B statutory columns (Iter 480) (must say OK): "
grep -q 'Bank A/c / IFSC' $APP_DIR/backend/routes/govt_audit_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Gratuity Register exempt/taxable split (Iter 480) (must say OK): "
grep -q 'Exempt Amount' $APP_DIR/backend/routes/govt_audit_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Daily Attendance Register extra columns (Iter 480) (must say OK): "
grep -q 'Early Out Min' $APP_DIR/backend/routes/labour_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Contractor Master module (Iter 479) (must say OK): "
[ -f $APP_DIR/backend/routes/contractors.py ] && [ -f $APP_DIR/frontend/app/contractor-master.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   CLRA / Labour Code registers (Iter 479) (must say OK): "
grep -q 'clra-reports' $APP_DIR/backend/routes/clra_labour_reports.py && grep -q 'CLRA / Labour Code' $APP_DIR/frontend/app/reports-center.tsx && echo "OK" || echo "MISSING!"
echo -n "   Daily Report PDF redesign + Only Present (Iter 479) (must say OK): "
grep -q 'Bio Code' $APP_DIR/backend/routes/daily_verification.py && grep -q 'present_only' $APP_DIR/backend/routes/daily_verification.py && echo "OK" || echo "MISSING!"
echo -n "   Rejoin button in Exit/Left sheet + Firm dropdown (Iter 479) (must say OK): "
grep -q 'admin-rejoin-btn' $APP_DIR/frontend/app/admin.tsx && [ -f $APP_DIR/frontend/src/components/FirmDropdown.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Editable register headings API (Iter 478) (must say OK): "
grep -q 'govt_heading_save' $APP_DIR/backend/routes/govt_audit_reports.py && grep -q 'rc-edit-heading' $APP_DIR/frontend/app/reports-center.tsx && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 482 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Portal footer badge must read 'Server Iter 482'."
echo "   2. Reports → Report Hub → Wage Register: FORM B heading shows on"
echo "      screen + PDF/Excel; 'Month wise / Periodic' toggle available"
echo "      on ALL five Government Registers (From Month → To Month)."
echo "   3. Compliance Salary Process: OT Hrs column now sits right after"
echo "      Present Days; ESIC Leave column is read-only and fills from"
echo "      approved ESIC Leave Master entries when you (re)process."
echo "   4. Report Hub → Wage Register → 'Edit heading' pencil (top-right"
echo "      of the heading): change the FORM lines, Save — the register,"
echo "      PDF and Excel all pick it up instantly. Reset restores default."
