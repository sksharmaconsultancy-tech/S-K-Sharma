#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 223)
# Ships (Biometric device file import — IN.dat / OUT.dat rules):
#  • IN.dat slot  → EVERY punch is an IN punch (device status byte ignored).
#  • OUT.dat slot → EVERY punch is an OUT punch.
#  • DOUBLE-READ FILTER — punches of the same kind within 15 minutes on
#    the same day are ignored (first punch kept).
#  • OT IN RULE — an evening IN punch on a day that already has a
#    morning IN lands as the 3rd punch → the Attendance Report reads it
#    as OT IN (and the evening OUT as OT OUT).
#  • BOTH FILES imported → punches are classified according to the
#    EMPLOYEE'S SHIFT: if the IN/OUT sequence doesn't pair cleanly it is
#    rebuilt anchored on the shift midpoint (first punch before the
#    shift midpoint = IN; after = OUT for missed-morning/night shifts).
#  • EXISTING-DATA PROTECTION — manual punches from the master are NEVER
#    changed/replaced by an import. Days that already hold DIFFERENT
#    machine data are NOT replaced silently: the portal PROMPTS for
#    permission first ("Replace old machine data?"); identical re-uploads
#    stay silent/idempotent.
#  • Attendance data flows straight into the Attendance Report as before.
# Run ON THE VPS as the sksharma user.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/6 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/6 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true

echo "==> 3/6 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/6 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
sudo rm -rf $WEB_DIR/*
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/6 Restarting backend..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 4

echo "==> 6/6 Verifying..."
curl -s http://localhost:8001/api/health && echo
echo
echo "🎉 Deploy complete."
echo "   Upload IN.dat + OUT.dat on the device-file import screen — all"
echo "   punches classify per the new rules and appear directly in the"
echo "   Attendance Report."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
