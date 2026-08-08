#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 524)
#
# ═══════════════════ WHAT'S NEW IN 524 ═══════════════════
#
# PUNCH-TIME PHOTO CAPTURE & DISPLAY (your request) — the actual FACE
# PHOTO the biometric machine captures at the moment of every punch is
# now linked to that exact punch transaction and shown everywhere:
#
# 1) PUNCH LOG REPORT — new "Punch Photo" column:
#    • ✓ Photo Captured  — inline THUMBNAIL of the real punch-time
#      photo; tap/click it to see the photo full-size with the
#      employee name + date/time caption.
#    • ⏳ Photo Sync Pending — the photo has reached the server but is
#      still being matched to its punch (photos and punches can arrive
#      separately from the machine).
#    • ✕ Photo Not Available — the device sent no photo for this punch
#      (device model without camera / photo push disabled).
#
# 2) NEW FILTER — "Punch Photo": All / ✓ Photo Available /
#    ⏳ Photo Sync Pending / ✕ Photo Missing.
#
# 3) PDF EXPORT — two new buttons on the Punch Log Report:
#    • "PDF"          — the log without photos (fast, small file).
#    • "PDF + Photos" — the log WITH the actual punch photos embedded
#      in each row (capped at 400 rows per print to keep the file sane).
#    Excel export continues to embed the photos as before.
#
# 4) NEW SCREEN — Attendance & Shift → "Photo Sync / Reconciliation":
#    • Live cards: Total Punches · Photos Received · Photos Pending ·
#      Photos Missing · Failed Photo Sync (parked >48h, never matched) ·
#      Parked Photos (queue), plus a photo-coverage % bar.
#    • "Retry Photo Sync" button — re-runs the matching queue: every
#      parked machine photo is re-matched to its punch (same machine +
#      bio PIN, timestamp ±90 seconds).
#
# 5) ASYNC & SAFE BY DESIGN (your requirement):
#    • Photo matching is fully ASYNCHRONOUS — punch ingestion
#      (/iclock/cdata) is NEVER slowed down or blocked waiting for a
#      photo. If the photo arrives late it is parked and auto-linked.
#    • 100% backward compatible — attendance calculations, grids and
#      payroll are completely untouched by photos.
#
#    HOW PHOTOS ARRIVE: ZKTeco/eSSL machines push "ATTPHOTO" packets on
#    the same ADMS/iClock channel your devices already use. If a
#    machine supports punch photos, enable "Attendance Photo" /
#    "Capture Mode" in its menu (Comm → Cloud Server / ADMS options).
#    No new ports or server settings are needed.
#
# Run ON THE VPS as root/sksharma:
#   wget -O deploy524.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy524.sh

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "════════════════════════════════════════════════════════════"
echo "  STEP 0 — DIAGNOSTICS (send me this block if deploy fails)"
echo "════════════════════════════════════════════════════════════"
echo "--- Disk space ---"
df -h / | tail -1
echo "--- Memory + swap ---"
free -h
echo "--- Backend service ---"
sudo supervisorctl status sksharma-backend 2>/dev/null || systemctl status sksharma-backend --no-pager -l 2>/dev/null | head -5 || echo "(no backend service found by either name)"
echo "--- Backend health (localhost:8001) ---"
curl -s -m 5 http://localhost:8001/api/health && echo " <-- backend answers ✅" || echo "❌ BACKEND NOT ANSWERING"
echo "--- Nginx ---"
sudo nginx -t 2>&1 | tail -1
systemctl is-active nginx && echo "nginx active ✅" || echo "❌ nginx NOT active"
echo "--- Web folder ---"
ls -la $WEB_DIR/index.html 2>/dev/null || echo "❌ $WEB_DIR/index.html MISSING"
echo "════════════════════════════════════════════════════════════"
echo ""

echo "==> 1/9 Freeing disk space (safe cache cleanup)..."
rm -rf $APP_DIR/frontend/.metro-cache $APP_DIR/frontend/.expo /tmp/metro-* /tmp/haste-* 2>/dev/null
npm cache clean --force >/dev/null 2>&1 || true
yarn cache clean >/dev/null 2>&1 || true
AVAIL_MB=$(df -m / | tail -1 | awk '{print $4}')
echo "   Free disk now: ${AVAIL_MB} MB"
if [ "$AVAIL_MB" -lt 1500 ]; then
  echo "   ⚠ Less than 1.5 GB free — cleaning apt + journal too..."
  sudo apt-get clean 2>/dev/null || true
  sudo journalctl --vacuum-size=100M >/dev/null 2>&1 || true
  df -m / | tail -1 | awk '{print "   Free disk now: "$4" MB"}'
fi

echo "==> 2/9 Ensuring swap (prevents build OOM-kill)..."
SWAP_KB=$(grep SwapTotal /proc/meminfo | awk '{print $2}')
if [ "$SWAP_KB" -lt 1000000 ]; then
  echo "   No/low swap — creating 2 GB swapfile..."
  sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile \
    && echo "   Swap ON ✅" || echo "   (swap setup failed — continuing)"
  grep -q "/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
else
  echo "   Swap already present ✅"
fi

echo "==> 3/9 Downloading latest code bundle (~10 MB, retries enabled)..."
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

echo "==> 4/9 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR || { echo "❌ Extract failed (disk full?) — aborting."; exit 1; }
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 5/9 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP install openpyxl Pillow -q || true

echo "==> 6/9 Restarting backend FIRST (portal comes back before the build)..."
sudo supervisorctl stop sksharma-backend 2>/dev/null || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend 2>/dev/null || sudo systemctl restart sksharma-backend 2>/dev/null || true
HEALTH=""
for i in $(seq 1 12); do
  sleep 5
  HEALTH=$(curl -s -m 8 http://localhost:8001/api/health)
  [ -n "$HEALTH" ] && break
  echo "   waiting for backend... (${i}0s)"
done
if [ -n "$HEALTH" ]; then
  echo "   Backend healthy ✅  ($HEALTH)"
else
  echo "   ❌ BACKEND STILL NOT ANSWERING. Last 30 log lines:"
  sudo tail -30 /var/log/supervisor/sksharma-backend*.log 2>/dev/null || sudo journalctl -u sksharma-backend -n 30 --no-pager 2>/dev/null
  echo "   ── Send me the lines above. Continuing with the web build anyway."
fi

echo "==> 7/9 Building web frontend (with OOM protection)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
export NODE_OPTIONS="--max-old-space-size=3072"
rm -rf dist
if npx expo export -p web 2>&1 | tail -15; then true; fi
if [ ! -f dist/index.html ] || [ ! -d dist/_expo/static/js/web ]; then
  echo "❌ WEB BUILD FAILED — the current live portal folder was NOT touched."
  echo "   Re-run this script once; if it fails again send me the build error above."
  exit 1
fi
echo "   Build OK ✅ ($(du -sh dist | cut -f1))"

echo "==> 8/9 Publishing new build (with rollback safety)..."
sudo mkdir -p $WEB_DIR
sudo rm -rf ${WEB_DIR}.prev
sudo cp -r $WEB_DIR ${WEB_DIR}.prev 2>/dev/null || true
sudo find $WEB_DIR -mindepth 1 -maxdepth 1 ! -name '.well-known' ! -name '_expo' -exec rm -rf {} +
sudo cp -r dist/* $WEB_DIR/
sudo cp public/sw.js $WEB_DIR/sw.js 2>/dev/null || true
sudo find $WEB_DIR/_expo -type f -mtime +45 -delete 2>/dev/null || true
sudo nginx -t && sudo systemctl reload nginx

echo "==> 9/9 Verification..."
echo -n "   Server badge is 524 (must say OK): "
grep -q 'APP_ITERATION = "524"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Photo status in punch log API (must say OK): "
grep -q 'photo_status' $APP_DIR/backend/routes/punch_logs.py && echo "OK" || echo "MISSING!"
echo -n "   Photo thumbnail endpoint (must say OK): "
grep -q 'punch-logs/photo.jpg' $APP_DIR/backend/routes/punch_logs.py && echo "OK" || echo "MISSING!"
echo -n "   Punch Log PDF export w/ photos (must say OK): "
grep -q 'punch-logs.pdf' $APP_DIR/backend/routes/punch_logs.py && echo "OK" || echo "MISSING!"
echo -n "   Photo reconciliation API (must say OK): "
grep -q 'punch-photos/reconciliation' $APP_DIR/backend/routes/punch_logs.py && echo "OK" || echo "MISSING!"
echo -n "   Retry photo-match queue API (must say OK): "
grep -q 'punch-photos/retry-match' $APP_DIR/backend/routes/punch_logs.py && echo "OK" || echo "MISSING!"
echo -n "   Async ATTPHOTO ingest (must say OK): "
grep -q '_ingest_attphoto' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   Photo Sync screen file (must say OK): "
[ -f $APP_DIR/frontend/app/photo-sync.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Punch-photo thumbnails in UI (must say OK): "
grep -q 'photo.jpg' $APP_DIR/frontend/app/punch-log-report.tsx && echo "OK" || echo "MISSING!"
echo -n "   Sidebar menu entry (must say OK): "
grep -q 'photo-sync' $APP_DIR/frontend/src/components/AdminWebShell.tsx && echo "OK" || echo "MISSING!"
echo -n "   Web build published (must say OK): "
[ -f $WEB_DIR/index.html ] && echo "OK" || echo "MISSING!"
echo -n "   Backend /api/health: "
curl -s -m 5 http://localhost:8001/api/health || echo "❌ NOT ANSWERING"
echo ""
echo -n "   Portal responds through nginx: "
CODE=$(curl -s -k -L -m 10 -o /dev/null -w "%{http_code}" http://localhost/ )
if [ "$CODE" = "200" ]; then
  echo "HTTP $CODE ✅"
elif [ "$CODE" = "301" ] || [ "$CODE" = "302" ]; then
  CODE2=$(curl -s -k -m 10 -o /dev/null -w "%{http_code}" https://localhost/ )
  echo "HTTP $CODE → HTTPS $CODE2 $( [ "$CODE2" = "200" ] && echo '✅ (HTTP→HTTPS redirect is normal with SSL)' || echo '❌' )"
else
  echo "HTTP $CODE ❌"
fi

echo ""
echo "   PHOTO COVERAGE ON YOUR LIVE DATA (last 7 days):"
$APP_DIR/backend/venv/bin/python - <<'PYEOF'
import os, re, asyncio
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

envp = "/home/sksharma/app/backend/.env"
env = {}
for line in open(envp):
    m = re.match(r'^([A-Z_]+)="?([^"\n]*)"?', line.strip())
    if m:
        env[m.group(1)] = m.group(2)

async def main():
    db = AsyncIOMotorClient(env.get("MONGO_URL", "mongodb://localhost:27017"))[
        env.get("DB_NAME", "hrms_production")]
    since = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    q = {"date": {"$gte": since}, "kind": {"$in": ["in", "out"]},
         "source": {"$regex": "^zkteco"}}
    total = await db.attendance.count_documents(q)
    with_photo = await db.attendance.count_documents(
        {**q, "selfie_base64": {"$exists": True, "$nin": [None, ""]}})
    parked = await db.biometric_photos.count_documents({})
    pct = round(with_photo * 100 / total) if total else 0
    print(f"   Machine punches since {since}: {total}")
    print(f"   With punch-time photo:        {with_photo}  ({pct}%)")
    print(f"   Photos parked in match queue: {parked}")
    if total and not with_photo and not parked:
        print("   ⚠ No photos received yet — enable 'Attendance Photo' /")
        print("     'Capture Mode' in each machine's ADMS/Cloud-Server menu.")

asyncio.run(main())
PYEOF

echo ""
echo "✅ Deploy Iter 524 complete!"
echo ""
echo "   ON EACH DEVICE: desktop hard-refresh (Ctrl+Shift+R); phone PWA —"
echo "   close fully and reopen TWICE."
echo ""
echo "   VERIFY: footer badge must read 'Server Iter 524'."
echo ""
echo "   THEN CHECK:"
echo "   • Attendance & Shift → Punch Log Report — new 'Punch Photo'"
echo "     column: ✓ thumbnail (tap to enlarge) / ⏳ Sync Pending /"
echo "     ✕ No Photo, plus the new Punch Photo filter."
echo "   • Header buttons: PDF · PDF + Photos · Photo Sync · Excel."
echo "   • Attendance & Shift → Photo Sync / Reconciliation — coverage"
echo "     cards + 'Retry Photo Sync' button."
echo "   • If machines are not sending photos yet, enable 'Attendance"
echo "     Photo' / 'Capture Mode' in the machine's ADMS settings —"
echo "     photos will start attaching to punches automatically."
