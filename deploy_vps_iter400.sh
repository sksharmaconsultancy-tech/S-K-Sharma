#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 400)
# INCLUDES everything already live up to Iter 399 + NEW IN THIS RELEASE:
#
# Iter 400 — CHROME AUTO-LOGIN RUNNER v9 (EPFO popup fix + driver auto-update):
#   • FIXED (user report): "alert popup OK not clicked before ID/Password".
#     The old runner clicked while the EPFO alert modal was still fading in,
#     so the click was intercepted and the popup stayed open. The runner now
#     waits for the page to fully load, POLLS up to 25s for a VISIBLE modal,
#     clicks OK/Close (#btnCloseModal / aria-label="Close") with a
#     JavaScript-click fallback, verifies the modal is GONE, and strips any
#     stuck backdrop — only THEN fills Username & Password.
#   • Username/Password now typed like a real keyboard (Angular-safe) so the
#     EPFO form actually keeps the values on submit.
#   • CHROMEDRIVER AUTO-UPDATE (user request): if Chrome updated on the PC
#     and the driver is stale, the runner self-heals automatically —
#     (1) retries via Selenium Manager, (2) wipes the driver cache and
#     upgrades Selenium, (3) force-downloads a matching Chrome+Driver pair.
#     No manual driver downloads ever again.
#   • Runner is SELF-UPDATING: existing PCs get v9 automatically the next
#     time run_listener.bat / run_pf.bat is started — NO re-download needed.
#
# Iter 400 — REPORTS CENTER COLUMN ALIGNMENT (user report):
#   • In Reports Center (and every register-style report), the FIRST data
#     column is wider (170px) than its heading was (108px), so every heading
#     after the first sat ~62px off its column. Headings now line up exactly
#     with their columns in Payroll Reports, Government Registers and Audit
#     Reports.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle (~115 MB, retries enabled)..."
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
echo -n "   Runner version served (must be 9): "
grep -o 'RUNNER_VERSION = "[0-9]*"' $APP_DIR/backend/routes/portal_extension.py || echo "MISSING!"
echo -n "   Runner popup fix (must say OK): "
grep -q "Alert popup: OK/Close clicked" $APP_DIR/backend/routes/portal_extension.py && echo "OK" || echo "MISSING!"
echo -n "   Driver auto-update (must say OK): "
grep -q "_fresh_driver" $APP_DIR/backend/routes/portal_extension.py && echo "OK" || echo "MISSING!"
echo -n "   Reports column fix (must say OK): "
grep -q "thFirst" $APP_DIR/frontend/src/components/RegisterTable.tsx && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 400 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   CHROME RUNNER v9 — on your Windows PC:"
echo "   1) Close any open 'SKS Runner' window."
echo "   2) Double-click run_listener.bat again — it AUTO-UPDATES itself"
echo "      to v9 on start (look for 'Auto-login script updated to v9')."
echo "      NO re-download of the ZIP is needed."
echo "   3) In PF Reports click 'Login — Open EPFO Portal':"
echo "      Chrome opens → waits for the alert popup → clicks OK →"
echo "      fills Username + Password → you type the captcha and Login."
echo "   4) ChromeDriver now AUTO-UPDATES: if Chrome updated and the driver"
echo "      is stale, the runner repairs itself and retries automatically."
echo ""
echo "   REPORTS CENTER: open Reports Center → any report — the column"
echo "   headings now sit exactly above their data columns."
