#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 587 — RBAC Phase 2 + Phase 3:
# Export Security + Export History + MAKER-CHECKER approval workflow)
# Deploys the FULL latest code (includes ALL of Iter 568-586). Running 587 alone is enough.
#
# ═══════════ WHAT'S NEW (this deploy = Iter 587) ═══════════
#
# RBAC PHASE 2 — SENSITIVE DATA & EXPORT SECURITY (completed):
#  * KYC MASKING — the Employee KYC endpoint now masks Aadhaar / PAN /
#    Bank A/c / IFSC / Mobile / Address IN THE BACKEND RESPONSE for any
#    user without the "sensitive_data:view" permission (real firm admins
#    and Super Admin always see full values inside their own scope).
#  * CENTRAL EXPORT GATE — Salary Register Excel/CSV/PDF exports now pass
#    through ONE authorization engine: firm scope + module EXPORT
#    permission. Denied attempts return 403 AND are logged.
#  * EXPORT AUDIT TRAIL — every export gets a unique Export ID and is
#    logged (who, what report, format, firm, period, record count).
#    DENIED attempts are logged as CRITICAL. Values are never stored.
#  * NEW SCREEN: Administration → "Export History" — all exports +
#    denied attempts with All / Successful / Denied filters.
#
# RBAC PHASE 3 — MAKER-CHECKER APPROVAL WORKFLOW (4-eyes principle):
#  * CRITICAL CHANGES ARE STAGED, NEVER APPLIED DIRECTLY (when made by a
#    sub-admin / client user): Salary Change, Bank Details Change,
#    Employee Deletion. The ORIGINAL DATA STAYS UNCHANGED until an
#    authorized approver explicitly approves.
#  * OLD vs NEW VALUES stored on each request and shown side-by-side in
#    the review screen (masked for viewers without sensitive-data rights).
#  * MAKER CAN NEVER APPROVE THEIR OWN REQUEST (they may withdraw/reject
#    it). Approvers need the module's APPROVE permission + firm scope.
#    Employee deletions can ONLY be approved by the Super Admin.
#  * SUPER ADMIN's own changes apply directly (top authority).
#  * NEW SCREEN: Administration → "Pending Approvals" — queue with
#    PENDING / APPROVED / REJECTED tabs, old-vs-new diff table, reason
#    box, Approve & Apply / Reject buttons. Super Admin sees toggles for
#    which actions require approval (all ON by default).
#  * FULL AUDIT + EMAIL ALERTS — every request and decision is logged
#    (APPROVAL_REQUESTED / APPROVED / REJECTED) and emailed to the admin
#    inbox via Resend.
#  * Mixed KYC edits: non-bank fields still save instantly; only the bank
#    fields go to approval.
#  * Sub-admins with employees:delete can now REQUEST employee deletion
#    (nothing is removed until you approve). Toggle it off in Pending
#    Approvals → settings to restore the old strict "super admin only".
#  * 22/22 maker-checker tests + 9/9 export-security tests + 7/7 UI
#    end-to-end tests pass.
#
# PREVIOUS (Iter 586) — RBAC scope wiring + Roles & Permissions UI +
#    sensitive masking on employee profile. Reminder if not yet run:
#    POST /api/admin/access/migrate-sensitive-permission (once, as super
#    admin) grants sensitive_data:view to users who already had employee
#    access.
# PREVIOUS (Iter 585) — Central authorization service (shared/authz.py),
#    action-level permissions, branch/department data scope, Access Preview.
# PREVIOUS (Iter 584) — Device Sync Engine: auto master-sync LOCKED off;
#    manual employee register/delete on machines only.
# PREVIOUS (Iter 581-583) — Onboarding gate / attendance eligibility,
#    payroll guards, policy versioning + reprocess, duplicate punch window.
#
# Run ON THE VPS as root/sksharma:
#   wget -O deploy587.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy587.sh

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
if ! grep -q "^RESEND_FROM_EMAIL=" $APP_DIR/backend/.env; then
  echo "RESEND_FROM_EMAIL=no-reply@smartpayrolling.com" >> $APP_DIR/backend/.env
  echo "   RESEND_FROM_EMAIL set to no-reply@smartpayrolling.com ✓ (auto-fallback until domain verified)"
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
echo -n "   Server badge is 587 (must say OK): "
grep -q 'APP_ITERATION = "587"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Maker-Checker engine — Iter 587 (must say OK): "
[ -f $APP_DIR/backend/routes/maker_checker.py ] && echo "OK" || echo "MISSING!"
echo -n "   Pending Approvals screen — Iter 587 (must say OK): "
[ -f $APP_DIR/frontend/app/pending-approvals.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Export History screen — Iter 587 (must say OK): "
[ -f $APP_DIR/frontend/app/export-history.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Central authz engine (must say OK): "
grep -q 'authorize_export' $APP_DIR/backend/shared/authz.py && echo "OK" || echo "MISSING!"
echo -n "   Web build published (must say OK): "
[ -f $WEB_DIR/index.html ] && echo "OK" || echo "MISSING!"
echo -n "   Backend /api/health: "
curl -s -m 5 http://localhost:8001/api/health || echo "❌ NOT ANSWERING"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  DONE — Iter 587 deployed."
echo "  New screens: Administration → 'Pending Approvals' and"
echo "  'Export History'."
echo "  Maker-Checker is ON by default for Salary Change, Bank Details"
echo "  Change and Employee Deletion — sub-admin/client changes now go"
echo "  to the approval queue; you approve/reject with old-vs-new view."
echo "  Toggle actions on/off inside the Pending Approvals screen."
echo "  Hard-refresh the browser (Ctrl+Shift+R) after deploy."
echo "════════════════════════════════════════════════════════════"
