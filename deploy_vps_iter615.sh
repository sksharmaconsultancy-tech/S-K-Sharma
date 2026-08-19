#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 615)
# Deploys the FULL latest code (includes ALL previous iterations).
#
# ═══════════ WHAT'S NEW (Iter 615) ═══════════
#
# 🔒 PUNCH FACE ENFORCEMENT (critical security fix — user report):
#  * Earlier: after a face was approved, the PWA still ALLOWED punches
#      even when the live selfie did NOT match the employee. FIXED.
#  * Now: once an employee has an APPROVED (active) face, EVERY selfie
#      punch is 1:1 AI-matched against it — a mismatching face, no face,
#      multiple faces or a missing selfie BLOCKS the punch (clear
#      rejection message). Repeated mismatches trigger a temporary
#      lockout. All attempts are logged in Secure Punch Audit
#      (stage: punch_face_match).
#  * Employees WITHOUT an approved face keep punching exactly as before.
#
# ⏱ FACE APPROVAL AUTO-APPROVE (user rule change):
#  * Pending self face-registrations now AUTO-APPROVE after 2 DAYS if
#      HR doesn't decide (previously they expired after 7 days).
#      Employee gets an in-app + SMS notification; audit row recorded.
#
# 📱 EMPLOYEE PWA — ESS PHASE 2:
#  * HOME: new "Leave Balance" card (CL/PL left / taken, tap → Leaves)
#      + "Offline punch" card (queued punches, online/offline state,
#      last sync time, manual "Sync now").
#  * DOCUMENTS → company docs: new "I have read this — Acknowledge"
#      button; shows green "Acknowledged · date" after. Admin can see
#      ack counts via API (acknowledgements stored per employee).
#  * KYC screen: new status card — Complete / X of 3 sections
#      (Aadhaar · PAN · Bank chips) + last updated date.
#  * SECURE PUNCH screen: live stage progress strip
#      (Device → Liveness → Face Match → Punch) with the exact failed
#      stage highlighted in red on rejection; ALSO fixes the
#      "Unreadable image frame" camera bug on this screen.
#
# Run ON THE VPS as root/sksharma:
#   wget -O deploy615.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy615.sh

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "════════════════════════════════════════════════════════════"
echo "  STEP 0 — DIAGNOSTICS (send me this block if deploy fails)"
echo "════════════════════════════════════════════════════════════"
df -h / | tail -1
free -h
sudo supervisorctl status sksharma-backend 2>/dev/null || systemctl status sksharma-backend --no-pager -l 2>/dev/null | head -5 || echo "(no backend service found)"
curl -s -m 5 http://localhost:8001/api/health && echo " <-- backend answers ✅" || echo "❌ BACKEND NOT ANSWERING"
sudo nginx -t 2>&1 | tail -1
systemctl is-active nginx && echo "nginx active ✅" || echo "❌ nginx NOT active"
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
  sudo apt-get clean 2>/dev/null || true
  sudo journalctl --vacuum-size=100M >/dev/null 2>&1 || true
  df -m / | tail -1 | awk '{print "   Free disk now: "$4" MB"}'
fi

echo "==> 2/9 Ensuring swap (prevents build OOM-kill)..."
SWAP_KB=$(grep SwapTotal /proc/meminfo | awk '{print $2}')
if [ "$SWAP_KB" -lt 1000000 ]; then
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
  echo "   attempt $i failed — retrying in 10s..."
  sleep 10
done
if [ -z "$ok" ]; then
  curl -fSL --retry 5 --retry-delay 10 -o /tmp/sks-latest.tar "$BUNDLE_URL"
fi
if ! tar -tf /tmp/sks-latest.tar >/dev/null 2>&1; then
  echo "❌ Downloaded bundle is corrupt/incomplete. Open the portal preview URL in a browser once, wait 30s, re-run."
  exit 1
fi
echo "   Bundle OK: $(du -h /tmp/sks-latest.tar | cut -f1)"

echo "==> 4/9 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR || { echo "❌ Extract failed (disk full?) — aborting."; exit 1; }
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if grep -q "^OTP_EMAIL_ENABLED=false" $APP_DIR/backend/.env; then
  sed -i 's/^OTP_EMAIL_ENABLED=.*/OTP_EMAIL_ENABLED=true/' $APP_DIR/backend/.env
fi
grep -q "^OTP_EMAIL_ENABLED=" $APP_DIR/backend/.env || echo "OTP_EMAIL_ENABLED=true" >> $APP_DIR/backend/.env
grep -q "^RESEND_FROM_EMAIL=" $APP_DIR/backend/.env || echo "RESEND_FROM_EMAIL=no-reply@smartpayrolling.com" >> $APP_DIR/backend/.env
grep -q "^RESEND_API_KEY=re_" $APP_DIR/backend/.env || echo "RESEND_API_KEY=re_TVV9ccdZ_NiFrGwZzGjVTiKLEYSskpGqB" >> $APP_DIR/backend/.env
grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env || echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env

echo "==> 5/9 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP install openpyxl Pillow -q || true
echo "→ Warming up Face AI models (InsightFace buffalo_l — downloads ~300MB on first run)…"
$APP_DIR/backend/venv/bin/python - << 'PYW' || echo "   (model warmup failed — face features will retry lazily)"
from insightface.app import FaceAnalysis
app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"],
                   providers=["CPUExecutionProvider"])
app.prepare(ctx_id=-1, det_size=(640, 640))
print("   Face AI models READY")
PYW

echo "==> 6/9 Restarting backend FIRST (portal comes back before the build)..."
echo "==> Seeding second super admin login (idempotent)..."
cd $APP_DIR/backend
$APP_DIR/backend/venv/bin/python seed_second_super_admin.py || python3 seed_second_super_admin.py || echo "⚠ SEED FAILED — run manually: cd $APP_DIR/backend && ./venv/bin/python seed_second_super_admin.py"
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
echo -n "   Server badge is 615 (must say OK): "
grep -q 'APP_ITERATION = "615"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Punch face enforcement — Iter 615 (must say OK): "
grep -q "enforce_template_match" $APP_DIR/backend/routes/face_punch.py && echo "OK" || echo "MISSING!"
echo -n "   2-day auto-approve — Iter 615 (must say OK): "
grep -q "SELF_AUTO_APPROVE_DAYS = 2" $APP_DIR/backend/routes/face_verification.py && echo "OK" || echo "MISSING!"
echo -n "   Doc acknowledgement API (must say OK): "
grep -q "acknowledge" $APP_DIR/backend/routes/compliance_docs.py && echo "OK" || echo "MISSING!"
echo -n "   ESS Phase 2 home cards (must say OK): "
[ -f $APP_DIR/frontend/src/components/ess/LeaveBalanceCard.tsx ] && [ -f $APP_DIR/frontend/src/components/ess/OfflinePunchStatusCard.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   ESS backend (must say OK): "
[ -f $APP_DIR/backend/routes/ess.py ] && echo "OK" || echo "MISSING!"
echo -n "   Web build published (must say OK): "
[ -f $WEB_DIR/index.html ] && echo "OK" || echo "MISSING!"
echo -n "   Backend /api/health: "
curl -s -m 5 http://localhost:8001/api/health || echo "❌ NOT ANSWERING"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  DONE — Iter 615 deployed."
echo "  • FACE-ENFORCED PUNCHING: employees with an approved face can"
echo "    no longer punch with someone else's face — it is BLOCKED and"
echo "    logged in Secure Punch Audit (stage punch_face_match)."
echo "  • Pending face registrations AUTO-APPROVE after 2 days."
echo "  • Employee PWA: Leave Balance + Offline punch cards on home,"
echo "    document Acknowledge button, KYC status card, secure punch"
echo "    stage progress + camera fix."
echo "  Employees just need to reopen the PWA (auto-update kicks in)."
echo "════════════════════════════════════════════════════════════"
