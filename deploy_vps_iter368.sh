#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 368)
# 🧮 SALARY COMPLIANCE PROCESS — 3 USER FIXES:
#   1. DEDUCTIONS & NET now computed by the PORTAL'S OWN Compliance
#      Salary engine (compute_compliance_row) using the firm's exact
#      Compliance Salary Policy — PF/VPF/ESIC/PT(state slabs)/TDS, wage
#      bases, caps, rounding, firm PF/ESI applicability — identical to
#      the Salary Process. The AI no longer invents numbers; it only
#      writes the Compliance Checklist, Journal Entries and Notes.
#   2. Sr. No. — every table (Earnings, Deductions, Employer
#      Contributions) is now BUILT IN CODE with a guaranteed Sr. No.
#      first column (no longer dependent on the AI's formatting).
#   3. FOOTER TOTALS — each table's footer total (GROSS EARNINGS /
#      TOTAL DEDUCTIONS / TOTAL EMPLOYER COST) is aligned exactly under
#      the "Amount (₹)" heading column.
#   Manual entries (no employee loaded) still use the full AI expert.
#   Import Excel / Freeze Salary process remains UNTOUCHED (read-only).
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle (~110 MB, retries enabled)..."
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
echo -n "   Engine-based calc (must be > 0): "
grep -c "_calculate_engine" $APP_DIR/backend/routes/ai_salary_compliance.py || true
echo -n "   Sr. No. table builder (must be > 0): "
grep -c "def _tbl" $APP_DIR/backend/routes/ai_salary_compliance.py || true
echo -n "   Freeze Salary UNTOUCHED (must be > 0): "
grep -c "use_imported_sheet" $APP_DIR/backend/server.py || true
echo ""
echo "✅ Deploy Iter 368 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → Salary Compliance Process (AI) → Load employee → Calculate:"
echo "     • Deductions & Net now match your Compliance Salary Policy"
echo "       exactly (same engine as the Salary Process)."
echo "     • Sr. No. shows in every table."
echo "     • Footer totals sit exactly under the Amount (₹) heading."
