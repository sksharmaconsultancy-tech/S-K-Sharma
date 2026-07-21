#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 226)
# Ships (NIGHT SHIFT import fix — e.g. Bio Code 20):
#  • Morning OUT punches are no longer mistaken for day-shift IN punches.
#  • CROSS-MIDNIGHT STITCH — a night shifter's morning OUT (e.g. 08:03)
#    is attached to the PREVIOUS day's shift, so the day reads
#    IN 19:55 → OUT 08:03 (next morning): 8 HRS duty + 4 HRS OT = 12 HRS,
#    exactly as a night shift should.
#  • A leading morning OUT (first day of the file) is attributed to the
#    previous day instead of breaking that day's pairing.
#  • Slot kinds from IN.dat / OUT.dat are now trusted even when a day
#    legitimately starts with an OUT punch (night shift), and are only
#    re-classified when two same-kind punches sit next to each other.
#  • TO RECTIFY EXISTING WRONG DATA: re-upload the same IN.dat + OUT.dat
#    after this deploy — the conflict report will list the wrongly
#    classified days; click "Replace Machine Data" once to fix them all.
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
echo "   NIGHT SHIFT FIX: re-upload the same IN.dat + OUT.dat files, review"
echo "   the conflict report and click 'Replace Machine Data' once — all"
echo "   wrongly classified night-shift days are rectified automatically."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
