#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 486)
#
# NEW IN 486 — ATTENDANCE ENGINE FIXES (your "Still Facing Issue" bug):
#   • MACHINE IN/OUT KEYS NOW HONOURED: ZKTeco/BIOFACE send a punch-state
#     (0=In, 1=Out, 2/3=Break, 4/5=OT) that was previously IGNORED — every
#     punch took the device's configured kind (default IN), producing
#     endless "missing OUT" days. Devices set to "Both" now use the
#     machine's own state first (alternation as fallback); fixed-direction
#     devices honour explicit Check-Out/Break/OT keys.
#   • ALL SOURCES EQUAL: a day whose punches ALL landed as IN (or all OUT)
#     is now repaired earliest=IN → latest=OUT across Machine + App +
#     Manual + Import together (previously machine-only).
#   • CROSS-MONTH NIGHT SHIFTS: the grid loads ±1 day around the month so
#     an OUT at 01:10 on the 1st pairs with the previous month's last-day
#     IN (no more orphan "missing IN" on day 1).
#   • REPAIR MODAL: approving a pending punch now refreshes the grid
#     INSTANTLY (no page reload).
#   • NEW DIAGNOSTIC API: /api/admin/attendance/grid-debug?user_id=&date=
#     shows every stored punch (all statuses), what the engine kept, the
#     selected IN/OUT and the EXACT reason an OUT is "missing" (e.g. the
#     App OUT is still PENDING → approve it or switch on Firm Master →
#     Approval Workflow → Auto-approve Mobile App Punches).
#
# NEW IN 486 — CLRA REPORTS PHASE 3 (final phase):
#   • INSPECTION REGISTER — add/list/delete inspection entries right in
#     the Report Hub; exports to Excel/PDF like every register.
#   • DIGITAL DOCUMENT REGISTER — every firm compliance document +
#     contractor licence with live VALID / EXPIRING SOON / EXPIRED status.
#   • SCHEDULED EMAIL REPORTS — schedule any CLRA register (daily/weekly/
#     monthly, IST) to be emailed automatically as PDF/Excel to chosen
#     recipients. "Send now" test button. Uses your SMTP settings.
#   • CLRA vs LABOUR CODE MODE — Firm Master → 7. Compliance Settings:
#     every register heading cites either the CLRA Act 1970 or the new
#     Labour Codes (OSH 2020 / Wages 2019). Formats unchanged.
#   • MASTER SNAPSHOT BADGE — Compliance Salary header now shows
#     "🔒 MASTER SNAPSHOT v1 — frozen DD-MM-YYYY".
#
# INCLUDES Iter 485 (Firm Master ERP redesign, sub-admin scope fix,
# Master Data Snapshot) and everything before it.
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
echo -n "   Server Version badge shows 486 (must say OK): "
grep -q 'APP_ITERATION = "486"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Machine punch-state honoured (must say OK): "
grep -q '_STATE_KIND' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   All-source same-kind repair + cross-month stitch (must say OK): "
grep -q 'CROSS-MONTH night' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Grid-debug diagnostic API (must say OK): "
grep -q 'grid-debug' $APP_DIR/backend/routes/attendance_admin_core.py && echo "OK" || echo "MISSING!"
echo -n "   Inspection + Document registers (must say OK): "
grep -q '_inspection_register' $APP_DIR/backend/routes/clra_labour_reports.py && grep -q '_document_register' $APP_DIR/backend/routes/clra_labour_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Scheduled email reports engine (must say OK): "
[ -f $APP_DIR/backend/routes/scheduled_reports.py ] && grep -q 'scheduled_reports_loop' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   CLRA vs Labour Code mode (must say OK): "
grep -q 'compliance_act_line' $APP_DIR/backend/routes/clra_labour_reports.py && grep -q 'fm-compliance-mode' $APP_DIR/frontend/app/firm-master.tsx && echo "OK" || echo "MISSING!"
echo -n "   Snapshot badge on salary header (must say OK): "
grep -q 'snapshot-badge' $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Iter 485 items still present (must say OK): "
[ -f $APP_DIR/backend/utils/master_snapshot.py ] && [ -f $APP_DIR/backend/routes/firm_master_v2.py ] && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 486 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY THE ATTENDANCE FIX:"
echo "   1. Footer badge must read 'Server Iter 486'."
echo "   2. Biometric Devices → set gate machines to 'Both IN/OUT' if one"
echo "      machine records both directions. New punches then follow the"
echo "      machine's own IN/OUT keys."
echo "   3. Grid: days where all punches were IN now pair earliest→latest;"
echo "      night OUT on the 1st pairs with the previous month's last day."
echo "   4. If an OUT still shows missing: open the Repair modal — a"
echo "      PENDING App punch needs approval (or switch ON Firm Master →"
echo "      Approval Workflow → Auto-approve Mobile App Punches, then Save)."
echo "   5. Report Hub → CLRA group → new Inspection Register (with ➕ Add"
echo "      Entry) and Digital Document Register; 'Scheduled Email Reports'"
echo "      panel on top (needs SMTP configured in Email Settings)."
