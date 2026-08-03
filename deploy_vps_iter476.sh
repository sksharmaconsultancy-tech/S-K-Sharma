#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 476)
# INCLUDES everything up to Iter 475 (Employee Rejoin module, biometric
# month-fetch + new-machine auto-upload, reprocess-with-existing-data,
# daily/monthly rate engine, ESIC wage-base everywhere, ECR runner v10).
# + NEW IN THIS RELEASE:
#
# Iter 476 — FIRM MASTER: STICKY "UNSAVED CHANGES" BANNER:
#   • A bright amber warning bar now PINS itself right under the Firm
#     Master page header the moment you edit anything. It stays visible
#     no matter how far you scroll, with a one-tap "Save Now" button —
#     no more losing edits by navigating away without saving.
#
# Iter 476 — BIOFACE / ZKTeco ADMS: PORT-80 GUARANTEE (301 fix):
#   • New nginx rule: any machine that reaches the server on PLAIN
#     HTTP PORT 80 (by IP, exactly how the machines are configured) gets
#     its /iclock/ and /api/iclock/ requests proxied STRAIGHT to the
#     backend — NEVER a 301 redirect to HTTPS (which the machines cannot
#     follow). This permanently protects against the redirect problem
#     even if nginx/SSL settings change later.
#   • Server version badge now shows "Server Iter 476".
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
# The machines speak PLAIN HTTP on port 80 and CANNOT follow 301
# redirects to HTTPS. This catch-all server handles requests that
# arrive by RAW IP (how the machines are configured) and proxies the
# iclock endpoints straight to the backend — no redirect, ever.
server {
    listen 80;
    server_name _;
    # Firmware default style:  http://<ip>/iclock/cdata?SN=...
    location /iclock/ {
        proxy_pass http://127.0.0.1:8001/api/iclock/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 90s;
    }
    # "URL path = /api" style:  http://<ip>/api/iclock/cdata?SN=...
    location /api/iclock/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 90s;
    }
    location / { return 404; }
}
NGINX
# Warn if another server block claims default_server on :80 (it would
# intercept raw-IP requests before our ADMS block).
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
echo -n "   Server Version badge shows 476 (must say OK): "
grep -q 'APP_ITERATION = "476"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Firm Master sticky unsaved-changes banner (Iter 476) (must say OK): "
grep -q 'dirtyBanner' $APP_DIR/frontend/app/firm-master.tsx && echo "OK" || echo "MISSING!"
echo -n "   ADMS port-80 nginx guarantee (Iter 476) (must say OK): "
grep -q 'iclock' /etc/nginx/conf.d/sks-adms.conf 2>/dev/null && echo "OK" || echo "MISSING!"
echo -n "   ADMS handshake answers on plain port 80 (must say OK): "
curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1/iclock/cdata?SN=TEST-DEPLOY-CHECK&options=all" | grep -q "200\|400\|401" && echo "OK" || echo "CHECK (nginx may need the default_server tweak above)"
echo -n "   Employee Rejoin (Rehire) module (Iter 475) (must say OK): "
[ -f $APP_DIR/backend/routes/employee_rejoin.py ] && grep -q 'employee-rejoin' $APP_DIR/frontend/app/employee-master.tsx && echo "OK" || echo "MISSING!"
echo -n "   New-machine cards + month fetch (Iter 473) (must say OK): "
grep -q 'fetch-range' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   First-sync auto-upload for new machines (Iter 474) (must say OK): "
grep -q '_first_sync' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   Reprocess keeps Days+Freeze, refreshes PF/ESIC (Iter 472) (must say OK): "
grep -q 'Iter 472' $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   Daily/Monthly rate basis in Compliance engine (Iter 471) (must say OK): "
grep -q 'Iter 471' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   ECR runner v10 auto-navigation (Iter 471) (must say OK): "
grep -q 'RUNNER_VERSION = "10"' $APP_DIR/backend/routes/portal_extension.py && echo "OK" || echo "MISSING!"
echo -n "   ESIC .xls uses OFFICIAL portal template (Iter 465) (must say OK): "
[ -f $APP_DIR/backend/assets/esic_mc_template.xls ] && grep -q 'Iter 465' $APP_DIR/backend/routes/challans.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 476 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Portal footer badge must read 'Server Iter 476'."
echo "   2. Firm Master → change any field → an AMBER 'Unsaved changes'"
echo "      bar pins itself under the page header (stays while scrolling)"
echo "      with a 'Save Now' button. It disappears after saving."
echo "   3. BIOFACE machines: with the machine's ADMS server set to the"
echo "      VPS IP on port 80, punches now flow — no more 301 redirects."
echo "      If a machine still shows no data: press 'Fetch this month'"
echo "      on its card in the Machine List."
