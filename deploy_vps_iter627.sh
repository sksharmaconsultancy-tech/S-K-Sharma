#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 627)
# Deploys the FULL latest code (includes ALL previous iterations).
#
# ═══════════ WHAT'S NEW (Iter 627) ═══════════
#
# 📊 SHIFT DEPLOYMENT REPORT — SUMMARY ONLY OPTION (user request):
#  * New "Data" choice on the Shift Deployment Report: FULL DATA
#    (unchanged — every employee row) or SUMMARY ONLY.
#  * SUMMARY ONLY prints NO individual employee rows — instead TWO
#    sections one after another:
#      ▶ DEPARTMENT WISE SUMMARY  then  ▶ DESIGNATION WISE SUMMARY
#    Each group row shows: Deployed (headcount), Present & Half-Day
#    (day counts), Hours, OT Hrs and Cost — plus a GRAND TOTAL row
#    per section.
#  * The on-screen preview AND the PDF / Excel / CSV downloads all
#    follow the selected mode; the report heading reads
#    "Shift Deployment Report — Summary Only".
#  * Full Data mode with Department/Designation grouping is untouched.
#
# (All Iter 618-626 features also included: Daily-Rated engine with
#  mid-month rate revisions + calc_detail audit, Multi-Branch
#  architecture with cost allocation & Branch Dashboard, Format 2
#  UAN/EPF wrap fix, PF/ESIC proration locked to Month Days, keyboard
#  shortcuts Phase 3, Excel-style salary grid cells.)
#
# Run ON THE VPS as root/sksharma:
#   wget -O deploy627.sh "https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=script"
#   bash deploy627.sh

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
echo -n "   Server badge is 627 (must say OK): "
grep -q 'APP_ITERATION = "627"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Shift Deployment Summary Only — Iter 627 (must say OK): "
grep -q '_summary_only' $APP_DIR/backend/routes/labour_reports.py && echo "OK" || echo "MISSING!"
echo -n "   Summary toggle UI — Iter 627 (must say OK): "
grep -q 'lr-data-summary' $APP_DIR/frontend/app/labour-reports.tsx && echo "OK" || echo "MISSING!"
echo -n "   Daily rate revisions — Iter 626 (must say OK): "
grep -q "_apply_daily_rate_revisions" $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   calc_detail audit — Iter 626 (must say OK): "
grep -q '"calc_detail"' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Multi-branch module — Iter 624 (must say OK): "
grep -q "branch_mgmt_router" $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Punch branch authorization — Iter 624 (must say OK): "
grep -q "_branch_punch_gate" $APP_DIR/backend/routes/attendance_core.py && echo "OK" || echo "MISSING!"
echo -n "   Branch screens — Iter 624 (must say OK): "
[ -f $APP_DIR/frontend/app/branch-management.tsx ] && [ -f $APP_DIR/frontend/app/branch-dashboard.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   Format 2 UAN/EPF wrap fix — Iter 623 (must say OK): "
grep -q 'idcell2' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   PF/ESIC proration LOCKED to Month Days — Iter 622 (must say OK): "
grep -q 'pf_proration_method = "calendar_days"' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   PF proration badge — Iter 621 (must say OK): "
grep -q "pf-proration-badge" $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   PF proration mirror in grid — Iter 620 (must say OK): "
grep -q "pfProrationFactor" $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Shortcuts Phase 3 — custom keys engine (must say OK): "
grep -q "applyOverride" $APP_DIR/frontend/src/utils/shortcuts.ts && echo "OK" || echo "MISSING!"
echo -n "   Shortcuts Phase 3 — Employee Master Alt+N (must say OK): "
grep -q '"employee-master"' $APP_DIR/frontend/app/admin.tsx && echo "OK" || echo "MISSING!"
echo -n "   Excel-style grid cells — Iter 618 (must say OK): "
grep -q "EditableGridCell" $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Arrow-key data-integrity guard (must say OK): "
grep -q "dirtyRef" $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   No-autosave + copy-verbatim (must say OK): "
grep -q "markGridDirty" $APP_DIR/frontend/app/compliance-salary-run.tsx && echo "OK" || echo "MISSING!"
echo -n "   Import ADVANCE→Advance col (must say OK): "
grep -q "actual_other_ded" $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   DOJ/DOL calendar window + audit (must say OK): "
grep -q "pay_days_audit" $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   Photo crop step in PWA (must say OK): "
grep -q "CropModal" $APP_DIR/frontend/app/profile-photo.tsx && echo "OK" || echo "MISSING!"
echo -n "   Punch face enforcement — Iter 615 (must say OK): "
grep -q "enforce_template_match" $APP_DIR/backend/routes/face_punch.py && echo "OK" || echo "MISSING!"
echo -n "   Web build published (must say OK): "
[ -f $WEB_DIR/index.html ] && echo "OK" || echo "MISSING!"
echo -n "   Backend /api/health: "
curl -s -m 5 http://localhost:8001/api/health || echo "❌ NOT ANSWERING"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  DONE — Iter 627 deployed."
echo "  • NEW (627): Shift Deployment Report now has a Data option —"
echo "    Full Data (all employee rows) or SUMMARY ONLY: Department-"
echo "    wise + Designation-wise totals (Deployed / Present / Half"
echo "    Day / Hours / OT / Cost) — screen, PDF, Excel & CSV."
echo "  • MULTI-BRANCH: Branches screen → ⚙ opens Branch Management"
echo "    (extended fields, employee home/authorized branches, temp"
echo "    assignments, transfers) and the Branch Dashboard with"
echo "    cost allocation. One payroll record per employee always."
echo "  • PF & ESIC now ALWAYS divide by the Month Days entered on the"
echo "    salary sheet — for ALL firms. Old method settings (÷26 etc.)"
echo "    are ignored; the options are removed from Compliance Settings."
echo "  • REPROCESS any sheet that showed ÷26 PF figures: PF becomes"
echo "    12% of the earned Wage Base (e.g. LAL CHAND 4333 → 520)."
echo "  • SHORTCUTS: press ? in the portal for the full list; click ✎"
echo "    on any row to set your own keys; Reset restores defaults."
echo "  • Alt+N = new record on Employee Master / Advances / Claims;"
echo "    Ctrl+S saves employee forms; Ctrl+F finds an employee."
echo "  • SALARY GRID (618): arrows only move between cells — they can"
echo "    never change a payroll figure. Type to edit,"
echo "    Enter commits + moves down, Escape cancels."
echo "  • Untouched cells are never marked as manual overrides."
echo "  Admins just need to hard-refresh the portal once (Ctrl+F5)."
echo "════════════════════════════════════════════════════════════"
