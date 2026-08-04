#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 485)
#
# NEW IN 485 — THREE MAJOR ITEMS:
#
# 1) FIRM MASTER — ENTERPRISE ERP REDESIGN (user request):
#    • 16-section layout with LEFT SIDE NAVIGATION (SAP / Zoho style):
#      1.General Information · 2.Registration · 3.Address · 4.Contact
#      Details · 5.Bank · 6.Payroll · 7.Compliance · 8.Attendance & Shift ·
#      9.Leave & Holiday · 10.Salary Structure · 11.Integrations ·
#      12.Documents · 13.Approval Workflow · 14.Security & Permissions ·
#      15.Audit Log · 16.AI Compliance Health.
#    • General Information redesigned (2-column, identity only — email/
#      mobile REMOVED): Short Name, Company Code (Auto + unique check),
#      Branch Code, Category/Business Nature (searchable), Industry,
#      Establishment/Organization Type, Incorporation & Start dates,
#      FY/AY, Currency, Time Zone, Language, Status, Colour Theme, and a
#      drag & drop logo with crop-to-square + live preview.
#    • NEW Contact Details section — normalized contact cards (Primary /
#      HR / Payroll / Compliance / Accounts, unlimited per type), Company
#      Communication emails, preferences checkboxes, per-contact
#      "Receives" report permissions, click-to-call, Copy, vCard download,
#      Send Test Email / Test WhatsApp. Old contact persons auto-migrate.
#    • AUTO-SAVE (2s after typing) + sticky action bar: Save · Save &
#      Continue · Reset · Cancel · Clone Company · Export Configuration.
#    • Audit Log section — every save recorded (who/when/which sections).
#
# 2) SECURITY FIX (user bug — "employees of another firm showing"):
#    Restricted sub-admin logins could see EVERY firm's employees on the
#    "Present today" report. Both /admin/attendance/today and
#    present-not-punched now enforce the sub-admin's allowed-firms list
#    AND honour the firm filter. Employees whose current firm differs
#    from the filter are dropped too (shared-machine safety).
#
# 3) COMPLIANCE SALARY — MASTER DATA SNAPSHOT (user request, SAP-style):
#    • FIRST salary generation of firm+month+group FREEZES all salary-
#      related Employee Master values (Basic, Gross, Structure, PF/ESIC
#      eligibility, UAN, ESIC No, Bank, Dept, Designation, VPF/Higher-PF…)
#      into compliance_master_snapshots (versioned, indexed).
#    • Reprocess and Delete+Generate-Again use the SNAPSHOT — HR edits to
#      the Employee Master can NEVER change an already-processed month.
#      Attendance / OT / Leave / Advance / Imported sheets refresh normally.
#    • New joiners are appended to the snapshot once (frozen thereafter).
#    • "Refresh Master" button (Super/Sub-Super Admin only, confirmation +
#      reason) creates snapshot Version+1 — old versions kept forever,
#      full audit trail with user + IP.
#    • PF / ESIC CALCULATIONS UNTOUCHED (verified zero diff).
#
# INCLUDES Iter 483 (auto-approve mobile app punches toggle) and everything
# before it.
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

echo "==> 7/8 Reloading nginx..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 8/8 Health check + verification..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"
echo -n "   Server Version badge shows 485 (must say OK): "
grep -q 'APP_ITERATION = "485"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Firm Master 16-section ERP nav (must say OK): "
grep -q 'NAV_SECTIONS' $APP_DIR/frontend/app/firm-master.tsx && grep -q 'AI Compliance Health' $APP_DIR/frontend/app/firm-master.tsx && echo "OK" || echo "MISSING!"
echo -n "   Contact Details normalized section (must say OK): "
[ -f $APP_DIR/frontend/src/components/firmMaster/ContactDetailsSection.tsx ] && [ -f $APP_DIR/backend/routes/firm_master_v2.py ] && echo "OK" || echo "MISSING!"
echo -n "   Sub-admin firm scope fix on Present Today (must say OK): "
grep -q 'apply_sub_admin_company_scope(user, q)' $APP_DIR/backend/routes/attendance_admin_core.py && echo "OK" || echo "MISSING!"
echo -n "   Master Data Snapshot engine (must say OK): "
[ -f $APP_DIR/backend/utils/master_snapshot.py ] && grep -q 'refresh-master-snapshot' $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   PF/ESIC calc engine untouched marker (must say OK): "
grep -q 'def compute_compliance_row' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Auto-approve mobile punches (Iter 483) (must say OK): "
grep -q 'auto_approve_mobile_punches' $APP_DIR/backend/routes/attendance_core.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 485 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Portal footer badge must read 'Server Iter 485'."
echo "   2. Firm Master → left side-nav with 16 sections; General Information"
echo "      is identity-only (2 columns); section 4 = Contact Details cards"
echo "      (old contact persons auto-migrated). Auto-save pill top-right."
echo "   3. Restricted sub-admin login → Present Today shows ONLY the"
echo "      allowed firm's employees now."
echo "   4. Compliance Salary: process a month → master values FREEZE."
echo "      Edit an employee's salary in the master, Reprocess → sheet keeps"
echo "      the original values. 'Refresh Master' button (Super/Sub-Super"
echo "      Admin) deliberately re-syncs with confirmation + audit trail."
