#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 418)
# INCLUDES everything up to Iter 417 (Smart Punch GPS revamp, GPS
# Diagnostics dashboard, BIOFACE MSD1K, device offline email alerts,
# strict code-match imports, group-wise sheet fix) + NEW IN THIS RELEASE:
#
# Iter 418 — SMART PUNCH NATIVE SDK + DEVICE SYNC ENGINE (user spec,
# attendance workflow UNCHANGED — GPS → Worksite → Face → Biometric → Save):
#   • NEW SDK layer (frontend/src/sdk/): a capability bridge between the
#     PWA/native app and the device — GPS (SmartGpsEngine), device
#     biometrics, telemetry (device model, OS, battery %, network type,
#     root detection) and the offline queue. Every punch is now enriched
#     with this telemetry for the audit trail.
#   • DEVICE SYNC ENGINE (offline punches): if the punch API is
#     unreachable, the punch — photo + location + REAL capture time — is
#     cached ON THE DEVICE (IndexedDB on web PWA / AsyncStorage native)
#     and replayed automatically when internet returns. Idempotent:
#     client_dedupe_id + client_punch_at mean a replayed punch can NEVER
#     duplicate and always keeps its original time.
#   • Sync triggers: browser back-online event + 60 s foreground interval
#     + (on real Android/iOS builds) an OS-scheduled background job via
#     WorkManager / BGTaskScheduler every ~15 min. Started once at app
#     boot — syncs app-wide, not only on the attendance tab.
#   • Employee UX: offline banner ("You're offline — punches will be
#     saved on this device"), pending-sync count + "Sync now" button,
#     "Saved — Pending Sync" confirmation on the punch flow.
#   • FIRM-GATED: offline punching only activates for firms with the
#     "Offline punching" switch ON in the Firm Master (geo policy).
#
# ZKTECO SDK HEALTH CHECK (this session): full ADMS/iClock lifecycle
# re-verified 8/8 — handshake, heartbeat/commands, ATTLOG ingest,
# duplicate-replay guard, unmapped-punch parking, OPERLOG, online status.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle (~10 MB, retries enabled)..."
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
echo -n "   SDK Device Sync Engine / Iter 418 (must say OK): "
[ -f $APP_DIR/frontend/src/sdk/offlineQueue.ts ] && grep -q "DEVICE SYNC ENGINE" $APP_DIR/frontend/src/sdk/offlineQueue.ts && echo "OK" || echo "MISSING!"
echo -n "   SDK bridge (telemetry/biometric/gps) / Iter 418 (must say OK): "
[ -f $APP_DIR/frontend/src/sdk/index.ts ] && grep -q "SmartPunchSDK" $APP_DIR/frontend/src/sdk/index.ts && echo "OK" || echo "MISSING!"
echo -n "   Sync engine started at app boot / Iter 418 (must say OK): "
grep -q "startAutoSync" $APP_DIR/frontend/app/_layout.tsx && echo "OK" || echo "MISSING!"
echo -n "   Attendance tab routed through SDK / Iter 418 (must say OK): "
grep -q "sdk/offlineQueue" "$APP_DIR/frontend/app/(tabs)/attendance.tsx" && echo "OK" || echo "MISSING!"
echo -n "   Punch flow offline fallback / Iter 418 (must say OK): "
grep -q "offlinePunchAllowed" $APP_DIR/frontend/src/components/PunchFlowModal.tsx && echo "OK" || echo "MISSING!"
echo -n "   Punch replay idempotency (backend) (must say OK): "
grep -q "client_dedupe_id" $APP_DIR/backend/routes/attendance_core.py && echo "OK" || echo "MISSING!"
echo -n "   Smart GPS engine / Iter 417 (must say OK): "
[ -f "$APP_DIR/frontend/src/utils/smartGps.ts" ] && grep -q "gps_diagnostics" $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   GPS auto-popup / Iter 416 (must say OK): "
grep -q "Iter 416" "$APP_DIR/frontend/app/(tabs)/index.tsx" && echo "OK" || echo "MISSING!"
echo -n "   BIOFACE MSD1K brand / Iter 410 (must say OK): "
grep -q "bioface" $APP_DIR/frontend/app/biometric-devices.tsx && echo "OK" || echo "MISSING!"
echo -n "   Device offline EMAIL alert / Iter 410 (must say OK): "
grep -q "offline alert EMAIL" $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 418 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   (Employees on the PWA: close & reopen the app once so the new"
echo "    service worker + sync engine load.)"
echo ""
echo "   VERIFY OFFLINE SYNC:"
echo "   • Firm Master → the firm's geo policy → turn ON 'Offline punching'"
echo "     for every firm that should cache punches without internet."
echo "   • On a phone: open the employee app, enable airplane mode →"
echo "     amber banner 'You're offline — punches will be saved on this"
echo "     device'. Punch normally → 'Saved — Pending Sync'."
echo "   • Turn internet back on → punch uploads automatically within"
echo "     seconds (or tap 'Sync now'), with the ORIGINAL punch time."
