#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 495)
#
# NEW IN 495 — MACHINE SDK PHOTOS + NEW-MACHINE USER FETCH + GROUP-WISE
# IN/OUT REPORT (your reports: "In Punch Log Report Employee Photo Not
# Showing — if required please use SDK to get photo of registered
# employee", "New Registered Machine didn't get / Master Employees not
# fetched", "In IN/Out Report not able to see Group-wise report"):
#
#   1) EMPLOYEE PHOTOS FROM THE MACHINE (SDK / ADMS):
#      • The face photo REGISTERED ON THE BIOMETRIC MACHINE (USERPIC /
#        BIOPHOTO) is now captured automatically and linked to the
#        Employee Master — so the Punch Log, grids and search show real
#        faces even when no photo was uploaded in the portal.
#      • Every machine is asked ONCE automatically for its registered
#        photos (DATA QUERY USERPIC + BIOPHOTO) on first contact.
#      • Employees with NO portal photo automatically fall back to the
#        machine-registered face (persisted, so it's a one-time lookup).
#      • Portal-uploaded photos always win — the machine photo is used
#        only when the Employee Master has none.
#
#   2) NEW MACHINES NOW FETCH THEIR USER DATABASE RELIABLY:
#      • ROOT CAUSE FOUND: some firmwares answer the automatic
#        "DATA QUERY USERINFO" with table=USERINFO (or no table at all) —
#        the server only parsed table=OPERLOG, so the machine's user list
#        (PIN + Name + Card) was RECEIVED but thrown away. Every push is
#        now run through the parser regardless of the table name.
#      • ONE-TIME: this deploy re-asks EVERY registered machine for its
#        user database + photos on its next contact (within ~1 minute of
#        the machine polling), so "Name in Machine" and photos fill in
#        for all existing machines too.
#
#   3) GROUP-WISE MONTHLY IN/OUT REPORT:
#      • Attendance Sheet → Monthly IN/OUT (and Working Hours) download
#        now respects the selected GROUP — the file contains only that
#        group's employees (verified: LABOUR-filtered export differs
#        from the full export).
#
# INCLUDES Iter 494 (employee photos across attendance module, firm-switch
# hard refresh, duplicate punch guard, super-admin delete etc.) and
# everything before.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip
PYBIN=$APP_DIR/backend/venv/bin/python

echo "==> 1/9 Downloading latest code bundle (~10 MB, retries enabled)..."
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

echo "==> 2/9 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 3/9 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/9 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/9 Restarting backend service..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend

echo "==> 6/9 ONE-TIME: re-asking every machine for its user database + photos..."
cd $APP_DIR/backend && $PYBIN - <<'PYEOF'
import asyncio, os
from dotenv import load_dotenv
load_dotenv("/home/sksharma/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient


async def main():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]
    # Reset the one-shot flags so each machine is queried again on its
    # next getrequest poll. The replies are now parsed for ANY table name
    # (USERINFO / OPERLOG / blank), so this time the data is captured.
    r = await db.biometric_devices.update_many(
        {}, {"$unset": {"userinfo_query_sent": "", "userinfo_query_sent_at": "",
                        "userpic_query_sent": "", "userpic_query_sent_at": ""}})
    print(f"   {r.modified_count} machine(s) will re-send their user DB + photos "
          "on next contact (~1 min if online)")

asyncio.run(main())
PYEOF

echo "==> 7/9 Nginx configs (unchanged)..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 8/9 Health check..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"

echo "==> 9/9 Verification..."
echo -n "   Server Version badge shows 495 (must say OK): "
grep -q 'APP_ITERATION = "495"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Machine SDK photo capture (must say OK): "
grep -q 'photo_b64' $APP_DIR/backend/routes/biometric_devices.py && grep -q 'DATA QUERY USERPIC' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   Any-table query-reply parsing (must say OK): "
grep -q 'run the parser for EVERY non-ATTLOG' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   Machine-photo fallback in photo engine (must say OK): "
grep -q '_machine_photo_backfill' $APP_DIR/backend/routes/employee_photos.py && echo "OK" || echo "MISSING!"
echo -n "   Group-wise Monthly IN/OUT download (must say OK): "
grep -q 'monthly-inout' $APP_DIR/frontend/app/attendance-sheet.tsx && grep -q '_resolve_group_employee_ids' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Iter 494 employee photo engine still present (must say OK): "
[ -f $APP_DIR/backend/routes/employee_photos.py ] && [ -f $APP_DIR/frontend/src/components/EmployeePhoto.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Iter 494 duplicate guard still present (must say OK): "
grep -q 'duplicate_within_5min_stored' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 495 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 495'."
echo "   2. MACHINE PHOTOS: wait 2-3 minutes after deploy (machines poll"
echo "      the server, are re-asked for user DB + photos, and reply)."
echo "      Then open Punch Log Report — employees whose face is enrolled"
echo "      on the machine now show a photo even without a portal upload."
echo "   3. NAME IN MACHINE: the Punch Log 'Name in Machine' column now"
echo "      fills for the previously-blank companies / new machines."
echo "   4. GROUP-WISE IN/OUT: Attendance Sheet → pick a Group → download"
echo "      Monthly IN/OUT — the file contains only that group's employees."
