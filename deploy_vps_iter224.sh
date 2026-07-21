#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 227/228)
# Ships:
#  1. "WRONG DATA MINUTES" FIX (machine .dat import):
#     • Stray double punches (a 2nd IN 1-2 hrs after arrival, a 2nd OUT
#       before the real exit) NO LONGER flip the whole day's IN/OUT kinds.
#       Days like IN 08:25 → OUT 20:17 now read 11.87 HRS instead of 1.4.
#     • Cross-machine bounce: a worker hitting the OUT machine and the IN
#       machine within 15 minutes no longer voids the day (e.g. OUT 07:59
#       + IN 08:03 → the stray punch is ignored, day counts normally).
#     • Night-exit on the wrong machine: a night shifter pressing the IN
#       terminal on the way out in the morning is detected and counted as
#       that night shift's OUT.
#     • Phantom 22-24 hr "night shifts" created by double-punch noise are
#       eliminated; genuinely ambiguous days stay flagged (red) for manual
#       correction — no guessing, per your rule.
#  2. SHIFT ROTATIONAL / OPEN policy option:
#     • Attendance Policy → new "Shift Mode" selector (Fixed vs
#       Open/Rotational). Also linked to Policy Master sub-point
#       "Shift Type" (rotational / open) — either control activates it.
#     • Open mode: every day, each employee's shift is auto-detected from
#       their FIRST IN punch (nearest shift start time in Shift Master).
#       Duty HRS + OT are computed on the detected shift — no per-employee
#       shift assignment needed.
#  TO RECTIFY EXISTING WRONG DATA: re-upload the same IN.dat + OUT.dat
#  after this deploy — review the conflict report and click
#  "Replace Machine Data" once.
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
echo "   WRONG-MINUTES FIX: re-upload the same IN.dat + OUT.dat files, review"
echo "   the conflict report and click 'Replace Machine Data' once — all"
echo "   wrongly paired days (fake 1-2 HR days, phantom 24 HR days,"
echo "   voided 0 HR days) are rectified automatically."
echo "   ROTATIONAL SHIFTS: open Attendance Policy → Shift Mode →"
echo "   'Open / Rotational' and Save. Make sure all rotation shifts exist"
echo "   in Shift Master."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
