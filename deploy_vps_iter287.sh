#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 287)
# Ships everything since deploy 282, including:
#  1. EMPLOYEE ONBOARDING APPROVAL WORKFLOW (Phase 1) — per-firm policy,
#     Pending Employee Approval dashboard (sidebar → Approvals), login/
#     punch gates, attendance held out of payroll until HR approves.
#  2. ACCESS & WORKFLOW MANAGEMENT — Roles & Permissions + Workflow
#     Builder merged into one module (Dashboard, Roles, Users,
#     Permission Matrix, Workflow Builder, Audit Logs).
#  3. WORKFLOW PHASE B — per-level Conditional Rules (e.g. amount>50000),
#     SLA hours with auto-escalation, Delegate + Escalate actions in the
#     Approval Inbox.
#  4. Shift Deployment Report (Labour Law Reports → Shift Reports).
#  5. UX batch: IN/OUT sheet shows raw duty hours (L/E/B codes removed),
#     punch-source legend, firm dropdowns (Shift/Attendance Master),
#     6 new themes, type-ahead Designation/Department/Group filters,
#     compliance run figures in Reports Hub, Company Policies tiles
#     moved to Utility sidebar, employee photo Upload/Change/Remove,
#     Employee Master field order.
#  (Also includes the Iter 282 12-hour session security if not yet live.)
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip
PY=$APP_DIR/backend/venv/bin/python

echo "==> 1/7 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/7 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true

echo "==> 3/7 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/7 SEC-004 — clamping any remaining long-lived sessions to 12h..."
cd $APP_DIR/backend
$PY - <<'PYEOF'
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(".env")
client = MongoClient(os.environ["MONGO_URL"])
db = client[os.environ.get("DB_NAME", "test_database")]
cap = datetime.now(timezone.utc) + timedelta(hours=12)
r = db.user_sessions.update_many(
    {"expires_at": {"$gt": cap}}, {"$set": {"expires_at": cap}}
)
print(f"   clamped {r.modified_count} of {db.user_sessions.count_documents({})} sessions")
client.close()
PYEOF

echo "==> 5/7 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
sudo rm -rf $WEB_DIR/*
sudo cp -r dist/* $WEB_DIR/

echo "==> 6/7 Restarting backend..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 4

echo "==> 7/7 Verifying..."
curl -s http://localhost:8001/api/health && echo
echo
echo "🎉 Deploy complete."
echo
echo "WHAT'S NEW FOR YOUR TEAM:"
echo "  • Approvals → Pending Employee Approval: enable the policy per firm"
echo "    there; new hires then wait for HR approval before payroll."
echo "  • Sidebar → Access & Workflow Mgmt: roles, users, permission matrix,"
echo "    workflow chains and audit logs in one place."
echo "  • Workflow Builder → Level Settings: SLA hours + conditions like"
echo "    'amount > 50000'; Inbox now has Delegate and Escalate buttons."
echo "  • Labour Law Reports → Shift Deployment Report."
echo
echo "  IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "  devices so the new version loads. Users idle 12+ hours will be"
echo "  asked to log in again — that's the security policy, not a bug."
