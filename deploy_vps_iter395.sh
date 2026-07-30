#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 395)
# INCLUDES Iter 370-394 (already live) + NEW IN THIS RELEASE:
#
# Iter 395 — WHATSAPP BUSINESS INTEGRATION MODULE (Meta Cloud API):
#   • Administration → WhatsApp Configuration: per-firm encrypted
#     credentials (Phone Number ID, WABA, Access Token, webhook tokens),
#     queue settings (retries, daily limit, attachment cap, auto-delete
#     logs) and 25+ automatic-notification toggles.
#   • Communication → WhatsApp Communication (Center): Dashboard KPIs
#     (sent/delivered/read/failed/pending/success %), Send Message
#     (template or custom text, single/department/entire-firm targeting,
#     preview, schedule), Salary Slips (queue payslip PDFs for a month),
#     History (status pills, retry/cancel/delete), Scheduler
#     (once/daily/weekly/monthly), Delivery Reports (Excel/PDF).
#   • Communication → WhatsApp Templates: 30 ready-made templates
#     (salary slip, attendance, leave, birthday, PF/ESIC, festival …)
#     with {{EmployeeName}}-style variables, preview + custom templates.
#   • Menu shortcuts: Payroll → "Send Salary Slips (WhatsApp)",
#     Attendance & Shift → "WhatsApp Alerts", Compliance →
#     "Notification Center".
#   • Automatic events wired in: new-employee Welcome, Salary Processed
#     + Payslip PDF on Generate Payslips, Leave Approved/Rejected, plus
#     daily scans (birthday, anniversary, absent today, continuous
#     absence, holiday reminder, document reminders).
#   • Chatbot: employees WhatsApp the business number with SALARY /
#     ATTENDANCE / LEAVE / PF / ESIC / HOLIDAY / PROFILE / BANK / HELP
#     and get instant auto-replies. Webhook: /api/whatsapp/webhook
#     (delivery read-receipts tracked automatically).
#   • Background queue worker (20s) with retry/backoff + daily limits.
#   • PENDING-CONFIG mode: until you enter Meta credentials, messages
#     queue and can be retried after setup — nothing breaks.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle (~115 MB, retries enabled)..."
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
echo -n "   WhatsApp engine (must exist): "
[ -f $APP_DIR/backend/utils/whatsapp_engine.py ] && echo "OK" || echo "MISSING!"
echo -n "   WhatsApp routes (must exist): "
[ -f $APP_DIR/backend/routes/whatsapp_center.py ] && echo "OK" || echo "MISSING!"
echo -n "   WhatsApp screens (must be 3): "
ls $APP_DIR/frontend/app/whatsapp-*.tsx 2>/dev/null | wc -l
echo -n "   Webhook live (expect 403 = OK, route exists): "
code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:8001/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=x")
[ "$code" = "403" ] && echo "OK ($code)" || echo "⚠ got $code"
echo ""
echo "✅ Deploy Iter 395 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo "   1) Administration → WhatsApp Configuration: enter your Meta Cloud"
echo "      API credentials (Phone Number ID, WABA ID, Permanent Token),"
echo "      set a Webhook Verify Token, enable WhatsApp, Test Connection."
echo "   2) In Meta App Dashboard → WhatsApp → Configuration set Callback"
echo "      URL: https://YOUR-DOMAIN/api/whatsapp/webhook + your verify"
echo "      token, subscribe to the 'messages' field."
echo "   3) Communication → WhatsApp Templates → Seed Defaults (30 ready)."
echo "   4) Communication → WhatsApp Communication → send a test message."
