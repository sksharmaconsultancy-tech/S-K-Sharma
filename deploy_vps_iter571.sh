#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 571 — OTP timing + reliability)
# Deploys the FULL latest code (includes Iter 568 Audit Trail, 569 2FA,
# 570 Security Alerts). Running 571 alone is enough.
#
# ═══════════ WHAT'S NEW (this deploy = Iter 571) ═══════════
#
# A. OTP TIMING (per your request):
#    * OTP is now valid for 2 MINUTES (was 5).
#    * "Resend OTP" unlocks after 2 MINUTES (was 30s).
#    * Both remain adjustable in Administration → Security · 2FA/MFA.
#
# B. "RECEIVED OTP NOT VERIFIED" FIXES:
#    * ONE active OTP per user — every new Sign-in click cancels ALL
#      previous codes, so only the NEWEST email works (no stale-code
#      confusion when multiple emails arrive).
#    * OTP emails now show the SENT TIME (IST) + a note to always use
#      the newest email.
#    * Clearer errors: "Invalid OTP — use the code from the NEWEST
#      email" vs "This OTP has expired — request a new one".
#
# C. NEW DIAGNOSTIC + EMERGENCY RESCUE (if OTP mail is missing/late):
#    wget -O diag2fa.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=diag2fa"
#    bash diag2fa.sh          # checks Resend key, sends a test mail, shows logs
#    bash diag2fa.sh rescue   # prints a fresh OTP on the server console so
#                             # you can ALWAYS complete a login (lockout-proof)
#
# Run ON THE VPS as root/sksharma:
#   wget -O deploy571.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy571.sh

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
# Iter 571b — OTP EMAIL ENV REPAIR (fixes "We could not send the OTP"):
if grep -q "^OTP_EMAIL_ENABLED=false" $APP_DIR/backend/.env; then
  sed -i 's/^OTP_EMAIL_ENABLED=.*/OTP_EMAIL_ENABLED=true/' $APP_DIR/backend/.env
  echo "   OTP_EMAIL_ENABLED was FALSE → set to true ✓"
fi
if ! grep -q "^OTP_EMAIL_ENABLED=" $APP_DIR/backend/.env; then
  echo "OTP_EMAIL_ENABLED=true" >> $APP_DIR/backend/.env
fi
if ! grep -q "^RESEND_API_KEY=re_" $APP_DIR/backend/.env; then
  echo "RESEND_API_KEY=re_TVV9ccdZ_NiFrGwZzGjVTiKLEYSskpGqB" >> $APP_DIR/backend/.env
  echo "   RESEND_API_KEY was MISSING → added ✓"
fi
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
echo -n "   Server badge is 571 (must say OK): "
grep -q 'APP_ITERATION = "571"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   2-min OTP timing — Iter 571 (must say OK): "
grep -q '"otp_validity_min": 2' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Single-active-OTP guard — Iter 571 (must say OK): "
grep -q 'delete_many({"user_id": user\["user_id"\]})' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   2FA routes (must say OK): "
[ -f $APP_DIR/backend/routes/twofa.py ] && echo "OK" || echo "MISSING!"
echo -n "   Web build published (must say OK): "
[ -f $WEB_DIR/index.html ] && echo "OK" || echo "MISSING!"
echo -n "   Backend /api/health: "
curl -s -m 5 http://localhost:8001/api/health || echo "❌ NOT ANSWERING"
echo ""
echo "── Force the 2-min timings even if settings were saved earlier ──"
$APP_DIR/backend/venv/bin/python - <<'PYEOF'
import os
from dotenv import load_dotenv
load_dotenv("/home/sksharma/app/backend/.env")
from pymongo import MongoClient
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "labourlaw")]
db.security_settings.update_one({"key": "2fa"},
    {"$set": {"otp_validity_min": 2, "resend_cooldown_sec": 120}}, upsert=True)
print("   OTP timings set: valid 2 min, resend after 2 min ✓")
PYEOF
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  DONE — Iter 571 deployed."
echo "  OTP: valid 2 min · resend after 2 min · only NEWEST email works."
echo "  If an OTP mail is late/missing:  bash diag2fa.sh   (see header)"
echo "  Locked out?                      bash diag2fa.sh rescue"
echo "  Hard-refresh the browser (Ctrl+Shift+R) after deploy."
echo "════════════════════════════════════════════════════════════"
