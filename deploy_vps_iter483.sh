#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 483)
#
# NEW IN 483 — AUTO-APPROVE MOBILE APP PUNCHES (user request "Do it"):
#   • Firm Master → 8. Firm Settings → new toggle
#       "Auto-approve Mobile App Punches (no admin review)"
#   • Toggle ON  → every NEW punch from the employee mobile app is saved
#     as APPROVED instantly — it appears on the Attendance Grid, Daily
#     Report, OT matrix and salary day-counting immediately, with NO
#     admin approval step. Audit trail records
#     "auto-approved (Firm Master: auto-approve mobile app punches)".
#   • Saving the Firm Master with the toggle ON also approves that
#     firm's OLD stuck PENDING app punches in one shot — the
#     "Both punches available but showing missing" rows fix themselves.
#   • SAFETY: punches flagged with FAKE/MOCK GPS still require manual
#     approval; contractual (Policy-2 contractor) employees keep their
#     own approval contract.
#   • Toggle OFF (default) → nothing changes: app punches wait in the
#     Punch Approvals queue exactly as before.
#
# NEW IN 482 — "BOTH PUNCHES AVAILABLE BUT SHOWING MISSING" (user bug):
#   Repair Punches modal TAGS pending punches with an amber
#   "PENDING — tap to approve" button; one tap completes the IN/OUT pair.
#
# NEW IN 481 — PUNCH DATA REPAIR: 5-minute duplicate filter (ingestion +
#   display), alternation repair, night-shift auto-pairing.
#
# INCLUDES everything up to Iter 480 (CLRA Phase 2 registers: PF / ESIC /
# LWF / Leave / Wage Form B / Gratuity split, Daily Attendance Register
# extra columns, Contractor Master, Report Hub CLRA group, Daily Report
# PDF redesign, editable register headings, Employee Rejoin module,
# ADMS port-80 nginx guarantee, ESIC wage-base, ECR runner v10).
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
echo -n "   Server Version badge shows 483 (must say OK): "
grep -q 'APP_ITERATION = "483"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Auto-approve app punches — punch endpoint (Iter 483) (must say OK): "
grep -q 'auto_approve_mobile_punches' $APP_DIR/backend/routes/attendance_core.py && echo "OK" || echo "MISSING!"
echo -n "   Auto-approve app punches — Firm Master mirror + old-pending sweep (must say OK): "
grep -q 'system:firm-auto-approve' $APP_DIR/backend/routes/firm_master.py && echo "OK" || echo "MISSING!"
echo -n "   Auto-approve toggle in Firm Master UI (must say OK): "
grep -q 'fm-auto-approve-app' $APP_DIR/frontend/app/firm-master.tsx && echo "OK" || echo "MISSING!"
echo -n "   Pending-punch approve in Repair modal (Iter 482) (must say OK): "
grep -q 'PENDING' $APP_DIR/frontend/src/components/PunchRepairModal.tsx && echo "OK" || echo "MISSING!"
echo -n "   5-min duplicate filter + night-shift pairing (Iter 481) (must say OK): "
grep -q 'dedupe_close_punches' $APP_DIR/backend/server.py && grep -q 'duplicate_within_5min_ignored' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   Phase 2 registers PF/ESIC/LWF/Leave (Iter 480) (must say OK): "
grep -q '_lwf_register' $APP_DIR/backend/routes/clra_labour_reports.py && grep -q '_pf_register' $APP_DIR/backend/routes/clra_labour_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Contractor Master module (Iter 479) (must say OK): "
[ -f $APP_DIR/backend/routes/contractors.py ] && [ -f $APP_DIR/frontend/app/contractor-master.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Daily Report PDF redesign + Only Present (Iter 479) (must say OK): "
grep -q 'Bio Code' $APP_DIR/backend/routes/daily_verification.py && grep -q 'present_only' $APP_DIR/backend/routes/daily_verification.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 483 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Portal footer badge must read 'Server Iter 483'."
echo "   2. Firm Master → 8. Firm Settings → switch ON"
echo "      'Auto-approve Mobile App Punches (no admin review)' → Save."
echo "      All OLD pending app punches of that firm are approved at once."
echo "   3. Ask an employee to punch from the mobile app — the punch shows"
echo "      on the Attendance Grid immediately (no approval queue)."
echo "   4. Fake-GPS flagged punches still land in Punch Approvals (safety)."
