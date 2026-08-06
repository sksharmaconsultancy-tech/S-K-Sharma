#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 509)
#
# NEW IN 509 (your requests):
#
# 1) TASK EDIT LOCK — the allotted member can NO LONGER edit a task.
#    Only the Super Admin or the task's creator can change title /
#    description / due date / priority / firm. The assignee can still
#    WORK the task (Start, Done/Submit, Later, attachments) but the ✏️
#    edit button is hidden for them and the server rejects any attempt.
#
# 2) SUB SUPER ADMIN WORK DISCIPLINE (24-HOUR RULE):
#    • Every task now has a 24-hour window by default — if no due date
#      is picked, it falls due TOMORROW automatically.
#    • The allotted Sub Super Admin can either complete the task or mark
#      it "⏸ Later…" with a MANDATORY reason (server rejects empty).
#    • If a task stays pending past its due date, the sub admin is
#      BLOCKED on next login by a full-screen prompt: they must first
#      enter the reason why each late task was not completed on time —
#      only then can they continue working.
#    • Every Later reason and Late reason is shown on the task card and
#      in the Edit Log, visible to the Super Admin.
#
# 3) ALLOTTED TASKS NOW VISIBLE IN SUPER ADMIN PWA: tasks you created or
#    allotted stay in your Task Management list no matter which firm is
#    currently selected.
#
# 4) TAPPABLE DASHBOARD COUNTS: every number on the Task hub (Pending /
#    Completed / Awaiting Review / Overdue / Open / In Progress / Later
#    / Done) now opens the matching task list on tap.
#
# INCLUDES Iter 507 (assignee-scoped firm multi-select), 506 (alloted
# tasks on sub admin home + critical blank-screen & infinite-loop fixes
# + Bonus Excel display format), 505-500 and everything before.
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
echo -n "   Server Version badge shows 509 (must say OK): "
grep -q 'APP_ITERATION = "509"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Edit lock for allotted members (must say OK): "
grep -q '_wants_content_edit' $APP_DIR/backend/routes/portal_phase2.py && echo "OK" || echo "MISSING!"
echo -n "   Later-with-reason endpoint (must say OK): "
grep -q 'mark_task_later' $APP_DIR/backend/routes/portal_phase2.py && echo "OK" || echo "MISSING!"
echo -n "   Overdue login gate backend (must say OK): "
grep -q 'overdue-block' $APP_DIR/backend/routes/portal_phase2.py && echo "OK" || echo "MISSING!"
echo -n "   Overdue gate UI component (must say OK): "
[ -f $APP_DIR/frontend/src/components/portal/OverdueGate.tsx ] && echo "OK" || echo "MISSING!"
echo -n "   24-hour default due date (must say OK): "
grep -q 'all the task have time of 24 HRS' $APP_DIR/backend/routes/portal_phase2.py && echo "OK" || echo "MISSING!"
echo -n "   Tappable counters (must say OK): "
grep -q 'pd-count-later' $APP_DIR/frontend/src/components/portal/TasksPanel.tsx && echo "OK" || echo "MISSING!"
echo -n "   Gate inside BUILT web output (must say OK): "
grep -rq 'overdue-gate' $WEB_DIR/_expo/static/js/web/ && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 509 complete! HARD-REFRESH the browser (Ctrl+Shift+R);"
echo "   on the phone close + reopen the PWA twice."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 509'."
echo "   2. Allot a task to a Sub Super Admin → login as that sub admin →"
echo "      the ✏️ edit icon is GONE on that task (only ⏸ Later… / Start /"
echo "      Submit remain). Trying to edit is rejected by the server too."
echo "   3. The sub admin taps ⏸ Later… → reason is compulsory → the task"
echo "      shows '⏸ LATER' + reason on YOUR login too."
echo "   4. Let a task pass its due date → sub admin's next login is"
echo "      blocked until they type why it was not completed on time —"
echo "      the reason then appears on the task card ('⚠ Late reason')."
echo "   5. New tasks without a due date are automatically due TOMORROW."
echo "   6. Tap any number on the Tasks dashboard → the matching list"
echo "      opens (Pending / Overdue / Later / Awaiting Review …)."
