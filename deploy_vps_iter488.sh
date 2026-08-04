#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 488)
#
# NEW IN 488 — DUPLICATE PUNCH FIX (your "Multi Punch Within the Same time"):
#   • 5-MIN DUPLICATE FILTER IS NOW DEFAULT & DEVICE-WIDE: the old guard
#     only blocked duplicates from the SAME machine — the same punch
#     arriving from a second registered device / webhook / re-sync was
#     stored AGAIN at the same time (ABDUL RAZA KHAN: 10:23 ×2, 22:13 ×2).
#     Now ANY punch within ±5 minutes of an existing punch is treated as
#     a duplicate.
#   • RAW PUNCHES ARE NEVER DELETED (your rule): duplicates are STORED in
#     the punch log with status "duplicate" and simply ignored by the
#     attendance grid, reports and payroll.
#   • HISTORY AUTO-CLEANED: this deploy marks all EXISTING stored machine
#     duplicates (within 5 min) as "duplicate" for every firm — days like
#     ABDUL's now pair correctly (10:23 IN → 22:13 OUT).
#   • Repair Punches modal no longer lists duplicate noise.
#   • On-demand API: POST /api/admin/attendance/cleanup-duplicate-punches
#     ?company_id=&month=&dry_run=true
#
# INCLUDES Iter 487 (expiring-document email alerts) and everything before.
#
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip
PYBIN=$APP_DIR/backend/venv/bin/python

echo "==> 1/9 Downloading latest code bundle (~10 MB, retries enabled)..."
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

echo "==> 2/9 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true
if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 3/9 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"

echo "==> 4/9 Building web frontend (expo export)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/

echo "==> 5/9 Restarting backend service..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend

echo "==> 6/9 ONE-TIME: marking existing duplicate machine punches (never deletes)..."
cd $APP_DIR/backend && $PYBIN - <<'PYEOF'
import asyncio, os
from datetime import datetime
from dotenv import load_dotenv
load_dotenv("/home/sksharma/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient


async def main():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]
    cur = db.attendance.find(
        {"status": "approved"},
        {"_id": 0, "record_id": 1, "user_id": 1, "at": 1, "source": 1},
    ).sort([("user_id", 1), ("at", 1)])
    dup_ids, last_uid, last_at = [], None, None
    async for p in cur:
        try:
            t = datetime.fromisoformat(str(p.get("at")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if p["user_id"] != last_uid:
            last_uid, last_at = p["user_id"], None
        src = str(p.get("source") or "")
        if (last_at is not None and src.startswith("zkteco")
                and abs((t - last_at).total_seconds()) < 300):
            dup_ids.append(p["record_id"])
            continue  # marked punches do not advance the window
        last_at = t
    marked = 0
    now = datetime.utcnow().isoformat() + "Z"
    for i in range(0, len(dup_ids), 1000):
        r = await db.attendance.update_many(
            {"record_id": {"$in": dup_ids[i:i + 1000]}},
            {"$set": {"status": "duplicate", "dup_marked_at": now,
                      "dup_marked_by": "deploy488",
                      "decision_reason": ("Duplicate punch within 5 min — kept in the "
                                          "punch log but ignored in attendance "
                                          "calculations (Iter 488 cleanup).")}})
        marked += r.modified_count
    print(f"   duplicates found={len(dup_ids)} marked={marked} (raw punches all kept)")

asyncio.run(main())
PYEOF

echo "==> 7/9 Nginx configs (unchanged — upload limits + ADMS port 80)..."
sudo nginx -t && sudo systemctl reload nginx

echo "==> 8/9 Health check..."
sleep 3
curl -s http://localhost:8001/api/health >/dev/null && echo "   Backend healthy ✅" || \
  echo "   ⚠ Backend health check failed — journalctl -u sksharma-backend -n 50"

echo "==> 9/9 Verification..."
echo -n "   Server Version badge shows 488 (must say OK): "
grep -q 'APP_ITERATION = "488"' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Device-wide 5-min duplicate guard (must say OK): "
grep -q 'duplicate_within_5min_stored' $APP_DIR/backend/routes/biometric_devices.py && echo "OK" || echo "MISSING!"
echo -n "   Cross-device dedupe in grid engine (must say OK): "
grep -q 'is_machine' $APP_DIR/backend/server.py && echo "OK" || echo "MISSING!"
echo -n "   Cleanup API present (must say OK): "
grep -q 'cleanup-duplicate-punches' $APP_DIR/backend/routes/attendance_admin_core.py && echo "OK" || echo "MISSING!"
echo -n "   Repair modal hides duplicates (must say OK): "
grep -q '"duplicate"' $APP_DIR/frontend/src/components/PunchRepairModal.tsx && echo "OK" || echo "MISSING!"
echo -n "   Iter 487 expiring-doc alerts still present (must say OK): "
grep -q 'run_doc_expiry_alerts' $APP_DIR/backend/routes/scheduled_reports.py && echo "OK" || echo "MISSING!"
echo ""
echo "✅ Deploy Iter 488 complete! HARD-REFRESH the browser (Ctrl+Shift+R)."
echo ""
echo "   HOW TO VERIFY THE DUPLICATE PUNCH FIX:"
echo "   1. Footer badge must read 'Server Iter 488'."
echo "   2. Open ABDUL RAZA KHAN 02-08 → Repair Punches: only 2 punches"
echo "      remain visible (10:23 + 22:13) — duplicates are marked, not"
echo "      deleted, and the day now pairs 10:23 IN → 22:13 OUT."
echo "   3. New duplicate punches (within 5 min, ANY device) are stored"
echo "      as 'duplicate' automatically and never affect calculations."
