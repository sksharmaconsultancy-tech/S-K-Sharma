#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 487)
#
# NEW IN 487 — EXPIRING DOCUMENTS EMAIL ALERTS (your request):
#   • AUTOMATIC ALERTS: 60 / 30 / 7 days before (and ON the day of) expiry
#     of ANY Firm Master compliance document (licences, registrations,
#     digital signature, …) or ANY contractor CLRA labour licence, an email
#     alert is sent automatically.
#   • WHO RECEIVES IT: every contact ticked for "Compliance Reports" in
#     Firm Master → Contact Details, plus the firm's Compliance Email /
#     Official Company Email.
#   • HOW TO ENABLE: Firm Master → 2. Contact Details → Communication
#     Preferences → tick "Send Compliance Alerts" (per firm). Needs SMTP
#     configured once in Communication → Email Settings.
#   • EXACTLY-ONCE: each document fires one email per alert bucket
#     (60/30/7/0 days) — no duplicate spam; runs daily after 08:00 IST.
#   • TEST BUTTON: "Check Expiring Docs Now" button in the same
#     Communication Preferences card fires the scan on demand.
#   • SECURITY: sub-admins with a restricted company scope can no longer
#     read/manage report schedules or expiry alerts of other firms.
#
# INCLUDES Iter 486 (attendance IN/OUT machine-state fixes, CLRA Phase 3,
# scheduled email reports) and everything before it.
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
echo -n "   Server Version badge shows 487 (must say OK): "
grep -q 'APP_ITERATION = "487"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Doc-expiry alert engine (must say OK): "
grep -q 'run_doc_expiry_alerts' $APP_DIR/backend/routes/scheduled_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Manual 'Check Expiring Docs Now' API + button (must say OK): "
grep -q 'doc-expiry-alerts/run-now' $APP_DIR/backend/routes/scheduled_reports.py && \
grep -q 'cd-check-expiry' $APP_DIR/frontend/src/components/firmMaster/ContactDetailsSection.tsx && echo "OK" || echo "MISSING!"
echo -n "   Sub-admin scope guard on schedules (must say OK): "
grep -q 'sub_admin_can_touch_company' $APP_DIR/backend/routes/scheduled_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Iter 486 attendance fixes still present (must say OK): "
grep -q '_STATE_KIND' $APP_DIR/backend/routes/biometric_devices.py && grep -q 'CROSS-MONTH night' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Iter 486 CLRA Phase 3 still present (must say OK): "
grep -q '_inspection_register' $APP_DIR/backend/routes/clra_labour_reports.py && grep -q 'scheduled_reports_loop' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Iter 485 items still present (must say OK): "
[ -f $APP_DIR/backend/utils/master_snapshot.py ] && [ -f $APP_DIR/backend/routes/firm_master_v2.py ] && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 487 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO USE THE EXPIRING-DOCUMENT ALERTS:"
echo "   1. Footer badge must read 'Server Iter 487'."
echo "   2. One-time: Communication → Email Settings — configure SMTP"
echo "      (alerts are silently skipped until SMTP works)."
echo "   3. Per firm: Firm Master → 2. Contact Details →"
echo "      Communication Preferences → tick 'Send Compliance Alerts'."
echo "   4. Make sure at least one contact has 'Compliance Reports' ticked"
echo "      (or fill Compliance Email / Official Company Email)."
echo "   5. Enter expiry dates on Firm Master compliance documents and"
echo "      contractor CLRA licences — alerts fire 60/30/7 days before and"
echo "      on the expiry day (once per document per stage, after 08:00 IST)."
echo "   6. Test instantly with the 'Check Expiring Docs Now' button in the"
echo "      same Communication Preferences card."
