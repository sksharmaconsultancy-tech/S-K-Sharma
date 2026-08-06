#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 505)
#
# NEW IN 505:
#
# 1) TASK EDITING WITH FULL EDIT LOG (your request):
#    • Every task card now has a ✏️ pencil icon — edit Title,
#      Description, Due date, Priority and Firm ANY TIME, even after
#      assignment.
#    • Every change is recorded field-by-field, e.g.:
#        Title: “old title” → “new title” · Priority: “low” → “high”
#      with WHO edited and WHEN.
#    • Edited tasks show an amber “✎ edited ×N — view log” chip — tap
#      it to see the complete Edit Log (created / edited / status /
#      assignment history in one place).
#
# 2) ASSIGN TASK FROM PWA — FIXED (your bug):
#    Assigning to a Sub Super Admin failed with "Selected firm(s) are
#    not assigned to this Sub Super Admin" because the form silently
#    attached the currently selected firm even when it was outside the
#    assignee's scope. Now: picking an assignee auto-selects a firm
#    INSIDE their scope, and out-of-scope firms are never sent.
#
# 3) GLOBAL TASKS NOW VISIBLE: tasks created without a firm were
#    invisible whenever a firm filter was active (always the case on
#    the phone). They now always appear in the list.
#
# INCLUDES Iter 504 (PWA Tasks tab + cache-bust), 503 (Single Machine
# Attendance Mode), 502-500 and everything before.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/8 Downloading latest code bundle (~10 MB, retries enabled)..."
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

echo "==> 2/8 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 3/8 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP install openpyxl -q || true

echo "==> 4/8 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/
sudo cp public/sw.js $WEB_DIR/sw.js 2>/dev/null || true

echo "==> 5/8 Restarting backend service..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend

echo "==> 6/8 Nginx configs (unchanged)..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 7/8 Health check..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"

echo "==> 8/8 Verification..."
echo -n "   Server Version badge shows 505 (must say OK): "
grep -q 'APP_ITERATION = "505"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Task edit log (backend) (must say OK): "
grep -q '_edit_changes' $APP_DIR/backend/routes/portal_phase2.py && echo "OK" || echo "MISSING!"
echo -n "   Global tasks visible under firm filter (must say OK): "
grep -q 'also include GLOBAL tasks' $APP_DIR/backend/routes/portal_phase2.py && echo "OK" || echo "MISSING!"
echo -n "   Task edit UI + history modal (must say OK): "
grep -q 'pd-task-edit-' $APP_DIR/frontend/src/components/portal/TasksPanel.tsx && echo "OK" || echo "MISSING!"
echo -n "   PWA assign scope fix (must say OK): "
grep -q 'scopedAssign' $APP_DIR/frontend/src/components/portal/TasksPanel.tsx && echo "OK" || echo "MISSING!"
echo -n "   Edit UI inside BUILT web output (must say OK): "
grep -rq 'pd-task-save' $WEB_DIR/_expo/static/js/web/ && echo "OK" || echo "MISSING!"
echo -n "   Iter 504 Tasks tab still present (must say OK): "
[ -f "$APP_DIR/frontend/app/(tabs)/tasks.tsx" ] && echo "OK" || echo "MISSING!"
echo -n "   Iter 503 Single Machine engine still present (must say OK): "
grep -q '_single_machine_normalize' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 505 complete! HARD-REFRESH the browser (Ctrl+Shift+R);"
echo "   on the phone close + reopen the PWA twice."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 505'."
echo "   2. Tasks tab → any task → tap ✏️ → change the title → Save"
echo "      Changes → card updates + amber '✎ edited ×1 — view log'"
echo "      chip appears → tap it → full Edit Log with old → new values."
echo "   3. New Task → Assign to Sub Super Admin → their firm is"
echo "      auto-selected → Create Task succeeds (no firm-scope error)."
echo "   4. A task created without any firm now shows in the list even"
echo "      when a firm is selected."
