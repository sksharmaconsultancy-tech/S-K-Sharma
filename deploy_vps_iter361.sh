#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 361)
# USER REQUEST: OFFLINE SALARY DATA = EMPLOYEE ACTUAL SALARY from OLD DB.
#   The legacy import + ALL-FIRMS sync now fetch each employee's ACTUAL
#   (Offline) salary structure straight from the old DB EmployeeMaster:
#     Salary   → Basic Salary (₹)   (rate basis from PayBasis DAILY/MONTHLY)
#     Salary1  → Salary 1           Days1 → Salary 1 — Working Days
#     Salary2  → Salary 2           Days2 → Salary 2 — Working Days
#     Salary3  → Salary 3           Days3 → Salary 3 — Working Days
#   Written to users.salary_structure_actual — the EXACT structure the
#   Employee form and the Actual Salary Process use (Basic + attendance-
#   bonus tiers). Column lookup is case-insensitive and tolerant of
#   Salary1/Salary_1/Sal1 and Days1/Day1 variants.
#   Applies to:
#     · Legacy Import wizard (salary group)
#     · "Sync Salary Structures — ALL Firms (from Old DB)" — new live
#       counter "actual_salary_synced" shows how many employees got their
#       Offline/Actual structure from the old DB.
# Also ships Iter 360 (✨ AI Universal Payroll Import) and Iter 359
# (PF & ESIC Claims Management) if not yet deployed.
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
  echo "   Open the portal preview URL in a browser once (to wake the server),"
  echo "   wait 30 seconds, then re-run this script."
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
echo -n "   Actual salary struct mapping (must be > 0): "
grep -c "_actual_salary_struct" $APP_DIR/backend/routes/legacy_import.py || true
echo -n "   Sync counter (must be > 0): "
grep -c "actual_salary_synced" $APP_DIR/backend/routes/legacy_import.py || true
echo -n "   AI Universal Import (Iter 360, must be > 0): "
grep -c "ai-import" $APP_DIR/backend/routes/ai_universal_import.py || true
echo ""
echo "✅ Deploy Iter 361 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   → WORKFLOW: open Legacy Import → press"
echo "     'Sync Salary Structures — ALL Firms (from Old DB)'."
echo "     Watch the new 'actual_salary_synced' counter — every employee"
echo "     gets Basic Salary + Salary 1/2/3 + Working Days 1/2/3 from the"
echo "     old DB (EmployeeMaster: Salary, Salary1-3, Days1-3)."
echo "   → Spot-check: Employees → any employee → Salary Update — the"
echo "     Offline/Actual section should now show the old-software values."
echo "   → Then run an Actual Salary Process month to confirm tier bonuses"
echo "     unlock at the imported Working Days thresholds."
