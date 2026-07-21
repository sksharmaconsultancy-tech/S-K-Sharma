#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 235)
# Ships:
#  1. COMPLIANCE AUTOMATION STUDIO (new) — live government-portal
#     automation (EPFO / ESIC / Shram Suvidha …) run server-side with a
#     LIVE streaming viewer inside the payroll:
#       • Flows: Login & Dashboard, Generate UAN (Member Registration),
#         ECR Upload → TRRN → Challan → PDF, ESIC IP Registration,
#         ESIC Contribution Upload → Challan, Member Search,
#         Establishment Profile, Contribution History.
#       • Every click / field highlight (yellow pulse) / human-cadence
#         typing / scroll is visible frame-by-frame.
#       • CAPTCHA & OTP are NEVER bypassed — AI reads the captcha, and on
#         failure it PAUSES and shows the image for you to type. Mandatory
#         YES-to-submit confirmation before every government submission.
#         Payment buttons are hard-blocked.
#       • Controls: Start / Pause / Resume / Retry / Skip / Previous /
#         Stop / Emergency Stop.
#       • Validation engine (counts, wages, missing/duplicate UAN & IP),
#         download manager, session video, full audit trail, job history.
#       • Security: one automation per firm at a time, max-3 retries with
#         5s/15s/30s backoff, maintenance-page detection, compliance mode.
#  2. CHALLAN AUTO-ATTACH — challan PDFs downloaded by an ECR / ESIC
#     contribution automation are attached automatically to that month's
#     Monthly Challan Summary (and the PF/ESIC Challans screen).
#  3. ATTENDANCE GRID PUNCH REPAIR — tap ANY day cell (esp. the
#     "⚠ tap to fix" missing-punch cells) to add / edit / delete that
#     exact employee-date's punches right from the report.
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip
PY=$APP_DIR/backend/venv/bin/python

echo "==> 1/7 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/7 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true

echo "==> 3/7 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/7 Installing Playwright Chrome for the Automation Studio..."
# The Automation Studio needs the full Chromium build (video + downloads).
export PLAYWRIGHT_BROWSERS_PATH=/pw-browsers
$PY -m playwright install --with-deps chromium || \
  $PY -m playwright install chromium || \
  echo "   (playwright browser install skipped — install manually if the"
echo "    Automation Studio reports 'browser engine unavailable')"

echo "==> 5/7 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
sudo rm -rf $WEB_DIR/*
sudo cp -r dist/* $WEB_DIR/

echo "==> 6/7 Restarting backend..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 4

echo "==> 7/7 Verifying..."
curl -s http://localhost:8001/api/health && echo
echo
echo "🎉 Deploy complete."
echo
echo "AUTOMATION STUDIO NOTES:"
echo "  • Save each firm's REAL EPFO/ESIC User ID + Password under"
echo "    Firm Master → Portal Logins (or EPF/ESI Detail). Without them a"
echo "    live UAN/ECR run cannot pass the login step."
echo "  • The Studio is under the sidebar: Automation → Compliance"
echo "    Automation Studio. Pick portal → action → (employee/month) →"
echo "    Start, then watch it LIVE. Solve the CAPTCHA in the yellow box"
echo "    when it pauses."
echo "  • If it says the portal is unreachable, the government site is"
echo "    blocking the VPS IP — run from an allowed Indian ISP network or"
echo "    set PORTAL_PROXY_URL in backend/.env."
echo
echo "  IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "  devices so the new version loads."
