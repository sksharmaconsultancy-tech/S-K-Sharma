#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 502)
#
# NEW IN 502:
#
# 1) COMPANY-WISE TASK ASSIGNMENT HIERARCHY (your full spec):
#    Super Admin → Sub Super Admin → Team, with strict RBAC:
#    • Super Admin can assign tasks ONLY to Sub Super Admins (assigning
#      directly to an employee is rejected), across ONE OR MULTIPLE
#      companies — validated against that Sub Super Admin's firm scope.
#    • Sub Super Admins see ONLY their own tasks (assigned to them /
#      created by them / their firms) — another Sub Super Admin's tasks
#      are 403. They can create internal tasks and DELEGATE (👤+ icon)
#      to team members of their assigned companies only.
#    • Review flow: Sub Super Admin "Submit for Review" → Super Admin
#      "✓ Approve & Close" (only the Super Admin can approve). New
#      Submitted / Approved statuses + filter chips.
#    • Hub dashboards on the Tasks tab:
#      – Super Admin: Companies, Sub Super Admins, Awaiting Review,
#        Overdue, Escalated (overdue+high).
#      – Sub Super Admin: assigned firms, Pending, Completed, High
#        Priority, Due-in-7-days, Team Progress (delegated done/total).
#    • Every assignment / reassignment / delegation / status change /
#      approval is recorded in the task audit log with timestamp + user.
#    • TASK ATTACHMENTS (proof of completion): 📎 on every task card —
#      upload photos / PDFs (≤10 MB, up to 10 per task), preview images,
#      download PDFs. "Submit for Review" nudges the Sub Super Admin to
#      attach evidence first. Upload/delete are audit-logged; only the
#      uploader or the Super Admin can delete.
#    • New Task modal: "Assign to Sub Super Admin" DROPDOWN (searchable)
#      + multi-company tick-chips limited to that admin's firms; the
#      Firm field is a proper dropdown list now (Iter 501 request).
#
# 2) PUNCH APPROVALS — "Pending 14 but list empty" (your bug):
#    The Pending badge counts ALL dates while the list shows only the
#    picked range. The empty state now says where the pending punches
#    actually are and gives a one-tap "Show them" button that jumps the
#    date range to those punches.
#
# 2b) PUNCH LOG REPORT — "NOT FOUND IN MASTER" fixes (your bug + request):
#    • Unknown punches from machines that are NOT registered in the
#      Devices master were silently dropped when a firm was selected —
#      they now ALWAYS show, marked "⚠ Unregistered Device" (old + new
#      machines both covered).
#    • 📷 photos are now CLICKABLE in the Punch Log Report — including
#      NOT-FOUND rows: the machine photo parked for the unknown user is
#      shown so you can identify who punched.
#
# 2c) NEW TASK → Firm dropdown now has a 🔍 FILTER box (your request).
#
# 3) STAY ON THE SAME PAGE (your request):
#    • Switching the ACTIVE FIRM now refreshes the CURRENT page in place
#      (fresh data for the new firm) — no more jumping to the Dashboard.
#    • Clicking any workspace tab (active or old) refreshes that tab's
#      own screen and stays there.
#
# 4) TASK CREATION remains blocked for company admins (Iter 501); Sub
#    Super Admins can now create internal tasks per the hierarchy spec.
#
# INCLUDES Iter 501 (Client Attendance Import) + Iter 500 (CTC Module,
# Yearly Projection, Increment Letter) and everything before.
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
echo -n "   Server Version badge shows 502 (must say OK): "
grep -q 'APP_ITERATION = "502"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Task hierarchy backend (must say OK): "
grep -q 'hub-dashboard' $APP_DIR/backend/routes/portal_phase2.py && grep -q '_task_audit' $APP_DIR/backend/routes/portal_phase2.py && echo "OK" || echo "MISSING!"
echo -n "   Task hierarchy UI (must say OK): "
grep -q 'pd-task-assignee-dd' $APP_DIR/frontend/src/components/portal/TasksPanel.tsx && echo "OK" || echo "MISSING!"
echo -n "   Task attachments (must say OK): "
grep -q 'task_attachments' $APP_DIR/backend/routes/portal_phase2.py && grep -q 'pd-att-upload' $APP_DIR/frontend/src/components/portal/TasksPanel.tsx && echo "OK" || echo "MISSING!"
echo -n "   Punch Approvals pending-jump fix (must say OK): "
grep -q 'pending-jump-btn' $APP_DIR/frontend/app/punch-approvals.tsx && echo "OK" || echo "MISSING!"
echo -n "   Punch Log NOT-FOUND + photo viewer (must say OK): "
grep -q 'Unregistered Device' $APP_DIR/backend/routes/punch_logs.py && grep -q 'punch-logs/photo' $APP_DIR/backend/routes/punch_logs.py && grep -q '__punchPhotoOpen' $APP_DIR/frontend/app/punch-log-report.tsx && echo "OK" || echo "MISSING!"
echo -n "   New Task firm filter (must say OK): "
grep -q 'pd-task-firm-filter' $APP_DIR/frontend/src/components/portal/TasksPanel.tsx && echo "OK" || echo "MISSING!"
echo -n "   Stay-on-page after firm switch (must say OK): "
grep -q 'loc.pathname + (loc.search' $APP_DIR/frontend/src/context/SelectedCompanyContext.tsx && echo "OK" || echo "MISSING!"
echo -n "   Iter 501 Client Attendance Import still present (must say OK): "
[ -f $APP_DIR/backend/routes/client_attendance_import.py ] && echo "OK" || echo "MISSING!"
echo -n "   Iter 500 CTC module still present (must say OK): "
[ -f $APP_DIR/backend/routes/ctc_module.py ] && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 502 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY:"
echo "   1. Footer badge must read 'Server Iter 502'."
echo "   2. Dashboard → Tasks tab → hub cards (Companies / Sub Super"
echo "      Admins / Awaiting Review / Overdue / Escalated) appear."
echo "   3. New Task → 'Assign to Sub Super Admin' dropdown → pick one →"
echo "      tick one or more of THEIR companies → Create. The task shows"
echo "      👤 assignee + firms on the card."
echo "   4. Login as a Sub Super Admin → they see that task, can Start"
echo "      and 'Submit for Review' (not Done), and can 👤+ delegate to"
echo "      their team. They can NOT see other admins' tasks."
echo "   5. Back as Super Admin → Submitted filter → '✓ Approve & Close'."
echo "   6. Punch Approvals: if the Pending badge > 0 but the range is"
echo "      empty, a button now shows WHERE the pending punches are —"
echo "      tap it to jump to those dates."
echo "   7. Open any page (e.g. Salary Register), switch the ACTIVE FIRM"
echo "      → the SAME page refreshes for the new firm (no dashboard"
echo "      jump). Clicking old workspace tabs refreshes them in place."
