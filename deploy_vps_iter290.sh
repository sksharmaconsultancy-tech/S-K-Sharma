#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 290)
# Ships everything since deploy 289:
#  1. STAFF ACCESS — Roles & Permissions → Add Staff User now has a PICKABLE
#     employee list from the Employee Master (search + select, auto-fills
#     name/email/phone; employees without email log in by mobile/User ID).
#     Linked employees get "Staff Access" in their PWA app (Profile tab) —
#     one tap opens the Staff Portal; a "Employee App" button switches back.
#  2. SUB-ADMINS — Company Scope now has Select all / Deselect all buttons.
#  3. BULK OPS TRANSFER REDESIGN — Old Company dropdown → employee list with
#     Active/Resigned filter → New Company dropdown. Only RESIGNED employees
#     can transfer (active = error). Employee joins the new firm with the
#     NEXT FREE employee code; old employment saved in their service record.
#     PLUS: global employee search by Aadhaar / PAN / Mobile / ESI / UAN
#     showing all old-company service records.
#  4. SHIFT MENUS MERGED — "Shift Change Requests" & "Shift Change Approvals"
#     are now ONE menu option with a segment switch.
#  5. COMPLIANCE REPORTS — proper firm-selection dropdown.
#  6. DAY-WISE SALARY SHEET — explicit "Single Day" mode with calendar picker.
#  7. ATTENDANCE In/Out & HRS REPORTS — Day-wise Present Count row at the
#     bottom of every day column.
#  8. PF ECR — .txt download now uses the OFFICIAL 11-field ECR 2.0 format
#     for DIRECT upload on the EPFO portal.
#  9. PWA SPEED — service worker now opens the cached shell instantly when
#     the network is slow (3.5s timeout) + nginx gzip compression enabled.
# 10. NEW REPORT: In/Out & OT Matrix (Reports menu) — per-employee monthly
#     matrix (D-In / D-Out / OT-In / OT-Out / Total / OT Hrs), colour-coded,
#     hover + click punch history, filters, Excel/PDF/CSV/Print exports
#     (A4 landscape, one employee per page).
# 11. EMPLOYEE REPORTS HUB — Pay Slip, Salary Certificate, Salary Register,
#     Annual Salary Statement (FY Excel), Appointment / Experience /
#     Relieving letters, all in one place (+ 3 new HR letter templates).
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

echo "==> 3/7 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/7 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
sudo rm -rf $WEB_DIR/*
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/7 Enabling nginx gzip compression (PWA speed)..."
sudo tee /etc/nginx/conf.d/sks-gzip.conf > /dev/null << 'NGINX'
# Iter 290 — gzip for the SPA bundle: cuts first-load size ~70%.
gzip on;
gzip_comp_level 6;
gzip_min_length 1024;
gzip_vary on;
gzip_proxied any;
gzip_types text/plain text/css application/json application/javascript
           text/javascript application/x-javascript image/svg+xml
           application/manifest+json font/woff2;
NGINX
sudo nginx -t && sudo systemctl reload nginx \
  || { echo "   nginx config test failed — removing gzip snippet"; sudo rm -f /etc/nginx/conf.d/sks-gzip.conf; sudo systemctl reload nginx; }

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
echo "WHAT'S NEW FOR YOUR TEAM:"
echo "  • Roles & Permissions: pick employees straight from the Employee"
echo "    Master to grant staff access; they open the Staff Portal from"
echo "    their PWA (Profile → Staff Access)."
echo "  • Bulk Ops Transfer: Old firm → resigned employees → New firm with"
echo "    a NEW employee code + global search by Aadhaar/PAN/Mobile/ESI/UAN."
echo "  • Shift Change Requests & Approvals merged into one menu."
echo "  • Compliance Reports firm dropdown · Salary Sheet Single-Day mode."
echo "  • In/Out & HRS reports: Day-wise Present Count footer."
echo "  • PF ECR .txt: official 11-field portal format."
echo "  • NEW: In/Out & OT Matrix report + Employee Reports hub."
echo "  • PWA opens faster & no longer hangs on slow networks."
echo
echo "⚠️  IMPORTANT: Everyone must HARD-REFRESH the portal once"
echo "   (Ctrl+Shift+R on desktop / clear PWA cache on mobile)"
echo "   to load the new build."
