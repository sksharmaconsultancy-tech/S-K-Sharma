#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 469)
# INCLUDES everything up to Iter 468 (Final PF Engine, Workspace Tabs,
# ESIC .xls on the OFFICIAL portal template + LibreOffice launder,
# ESIC "Total Monthly Wages" = WAGE BASE — Iter 467)
# + NEW IN THIS RELEASE:
#
# Iter 469 — UPLOAD THE DOWNLOADED ATTENDANCE SHEET AS-IS (user request):
#   • The system's own "Download Attendance Sheet" Excel (EM_PFNO / UAN_NO /
#     EM_ESINO / EM_CODE / EM_NAME / … / Basic / HRA / Conv. / <dynamic
#     allowance heads> / Gross Salary / Present Days / OVER_TIME / Adv /
#     TDS / Other Less / Employee Salary) now uploads DIRECTLY into the
#     Compliance Salary Process — no column mismatch.
#   • "Employee Salary" (the earned gross the client fills) is the FREEZE
#     gross — previously the master "Gross Salary" column was picked by
#     mistake, so the imported gross was wrong.
#   • DYNAMIC heads handled: the firm's extra allowance columns are
#     accepted; sheet columns matching an ENABLED Firm-Master deduction
#     head (UNIFORM / CLUB / CANTEEN / …) import into that head's own
#     dynamic deduction column on the run.
#   • FIXED: the AUTO-REPROCESS right after every sheet import (Iter 335)
#     had been silently failing ("Auto-process failed: cannot import
#     name…") — the salary now processes automatically on import again.
#
# Iter 470 — ESIC WAGES = WAGE BASE EVERYWHERE (user: "still showing
#   monthly gross"):
#   • The ON-SCREEN ESIC portal preview (before auto upload) also showed
#     Monthly Gross — now shows the ESIC WAGE BASE like the file.
#   • OLD runs processed before the wage-base field existed no longer fall
#     back to gross: the wage base is derived from the row itself
#     (esic_wage_base → stat_wage_base → max(Basic earned, 50% × Gross)),
#     so NO reprocess is needed — just re-download the ESIC Excel.
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
# Iter 468 — LibreOffice re-writes the ESIC .xls so its OLE structure
# matches a genuine Excel 97-2003 file.
if ! command -v soffice >/dev/null 2>&1; then
  echo "   Installing LibreOffice Calc (one-time, ~2-4 min)..."
  sudo apt-get update -qq && sudo apt-get install -y --no-install-recommends libreoffice-calc >/dev/null 2>&1 || \
    echo "   ⚠ LibreOffice install failed — ESIC .xls will use the fallback writer"
fi
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

echo "==> 5b/7 Nginx upload limits (Salary Sheet Excel import — Iter 458)..."
sudo tee /etc/nginx/conf.d/sks-upload.conf >/dev/null <<'NGINX'
client_max_body_size 100M;
proxy_read_timeout 300s;
proxy_send_timeout 300s;
NGINX

echo "==> 6/7 Reloading nginx..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 7/7 Health check + verification..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"
echo -n "   Attendance-Sheet upload accepted as-is (Iter 469) (must say OK): "
grep -q 'Iter 469' $APP_DIR/backend/routes/compliance_import.py && echo "OK" || echo "MISSING!"
echo -n "   ESIC wages = WAGE BASE in file + preview + old runs (Iter 470) (must say OK): "
grep -q '_esic_wages' $APP_DIR/backend/routes/challans.py && echo "OK" || echo "MISSING!"
echo -n "   Auto-reprocess after import FIXED (Iter 469) (must say OK): "
grep -q 'from routes.compliance_salary_runs import' $APP_DIR/backend/routes/compliance_import.py && echo "OK" || echo "MISSING!"
echo -n "   Dynamic deduction-head columns on the run (Iter 469) (must say OK): "
grep -q 'custom_deductions' $APP_DIR/backend/routes/compliance_salary_runs.py && echo "OK" || echo "MISSING!"
echo -n "   ESIC wages = WAGE BASE (Iter 467) + LibreOffice launder (Iter 468) (must say OK): "
grep -q 'Iter 468' $APP_DIR/backend/routes/challans.py && command -v soffice >/dev/null && echo "OK" || echo "MISSING!"
echo -n "   ESIC .xls uses OFFICIAL portal template (Iter 465) (must say OK): "
[ -f $APP_DIR/backend/assets/esic_mc_template.xls ] && grep -q 'Iter 465' $APP_DIR/backend/routes/challans.py && echo "OK" || echo "MISSING!"
echo -n "   Final PF Engine (Iter 456 spec) (must say OK): "
grep -q 'Iter 456 (user final PF Engine spec)' $APP_DIR/backend/utils/compliance_salary.py && echo "OK" || echo "MISSING!"
echo -n "   Workspace tabs + sync + locking (Iter 461) (must say OK): "
grep -q 'WorkspaceTabs' $APP_DIR/frontend/src/components/AdminWebShell.tsx && echo "OK" || echo "MISSING!"
echo -n "   Nginx 100M upload limit (Iter 458) (must say OK): "
grep -q 'client_max_body_size 100M' /etc/nginx/conf.d/sks-upload.conf 2>/dev/null && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 469 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Attendance Master → Download Attendance Sheet → fill Present"
echo "      Days / Employee Salary / Adv / TDS / Other Less → Compliance"
echo "      Salary Process → Import Sheet → uploads with NO column error"
echo "      and the salary auto-processes."
echo "   2. The run's Freeze/Imported Gross = the 'Employee Salary' column"
echo "      you typed (NOT the master Gross Salary)."
echo "   3. Compliance Salary → ESIC Upload Excel → 'Total Monthly Wages'"
echo "      now shows the ESIC WAGE BASE (max of Basic / 50% of Gross)."
