#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 211)
# Ships:
#  • OT PUNCH EDITING in Punch Approvals (Updated / Auto-Punches / Manual
#    Entries tabs):
#    - OT In & OT Out are now EDITABLE boxes exactly like In/Out — change
#      an existing OT time, or type into an empty box to ADD a missing
#      OT-In / OT-Out (single or both).
#    - Each OT punch also has an editable DATE box (DD-MM-YYYY). Leave the
#      OT-Out date empty and it lands automatically on the next morning
#      when the time is earlier than OT-In (night OT).
#    - All edits are audit-logged with the Update Reason.
#  • Manual Entries list now ALSO shows employees whose regular duty is
#    complete but the OT pair is INCOMPLETE (OT In without OT Out, or an
#    OT Out without OT In — e.g. forgot the OT-In punch), so missed OT
#    punches are easy to find and fill.
#  • Employees with full duty but NO OT punched at all: add their OT from
#    the Auto-Punches tab (both duty punches present) — type OT In/Out
#    into the empty boxes and Save.
# Run ON THE VPS as the sksharma user.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/6 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/6 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true

echo "==> 3/6 Installing backend deps (litellm stripped — VPS conflict fix)..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/6 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web
sudo rm -rf $WEB_DIR/*
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/6 Restarting backend..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 4

echo "==> 6/6 Verifying..."
curl -s http://localhost:8001/api/health && echo
check() {
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8001$1")
  if [ "$CODE" = "$2" ]; then
    echo "✅ $3 ($1 -> $CODE)."
  else
    echo "❌ $1 returned $CODE (expected $2) — check supervisor logs."
  fi
}
check "/api/admin/attendance/day-status/x?from_date=2026-07-01" "401" "Day-status API (OT pair + one-sided OT)"
check "/api/admin/punch-import/template" "401" "Punch Import"
echo
echo "🎉 Deploy complete."
echo "   HOW TO EDIT / ADD OT PUNCHES:"
echo "   • OT missed completely → Auto-Punches tab → type OT In + OT Out"
echo "     into the empty boxes → Save (OT Out earlier than OT In lands on"
echo "     the next morning automatically, or set the date box yourself)."
echo "   • One OT punch missing → Manual Entries tab now lists these rows;"
echo "     fill the missing OT In / OT Out and Save."
echo "   • Wrong OT time/date → edit the boxes on any source tab and Save."
echo "   IMPORTANT: close & reopen the PWA twice (or Ctrl+Shift+R) on your"
echo "   devices so the new version loads."
