#!/bin/bash
# S.K. Sharma & Co. — DAILY MONGODB BACKUP SETUP (Iter 365)
# Run this ONCE on the VPS — it installs an automatic daily backup system:
#   • Every night at 2:00 AM: full mongodump of the live portal database
#     (compressed .gz archive) into /home/sksharma/backups/
#   • Also snapshots backend/.env alongside each backup.
#   • Rotation: keeps the last 14 daily backups + the 1st-of-month backup
#     for 6 months. Older files are deleted automatically.
#   • Log at /home/sksharma/backups/backup.log
#   • Restore Actual Salary anytime:
#       bash /home/sksharma/app/restore_actual_salary_from_backup.sh \
#            /home/sksharma/backups/mongo_YYYY-MM-DD.gz
#   • FULL restore (disaster recovery):
#       mongorestore --uri="<MONGO_URL>" --archive=<file>.gz --gzip --drop
set -e

BK_DIR=/home/sksharma/backups
APP_DIR=/home/sksharma/app
SCRIPT=/home/sksharma/backup_mongo_daily.sh

echo "==> 1/4 Creating backup folder $BK_DIR ..."
mkdir -p "$BK_DIR"

echo "==> 2/4 Writing the daily backup script $SCRIPT ..."
cat > "$SCRIPT" << 'EOS'
#!/bin/bash
# Daily MongoDB backup — installed by deploy_vps_iter365.sh
BK_DIR=/home/sksharma/backups
APP_DIR=/home/sksharma/app
LOG=$BK_DIR/backup.log
STAMP=$(date +%F)
MONGO_URL=$(grep '^MONGO_URL=' $APP_DIR/backend/.env | cut -d= -f2- | tr -d '"' | tr -d "'")
DB_NAME=$(grep '^DB_NAME=' $APP_DIR/backend/.env | cut -d= -f2 | tr -d '"' | tr -d "'")
DB_NAME=${DB_NAME:-test_database}
OUT=$BK_DIR/mongo_${STAMP}.gz

echo "[$(date '+%F %T')] backup started db=$DB_NAME" >> $LOG
if mongodump --uri="$MONGO_URL" --db="$DB_NAME" --archive="$OUT" --gzip >> $LOG 2>&1; then
  cp $APP_DIR/backend/.env $BK_DIR/env_${STAMP}.bak 2>/dev/null || true
  SIZE=$(du -h "$OUT" | cut -f1)
  echo "[$(date '+%F %T')] backup OK -> $OUT ($SIZE)" >> $LOG
else
  echo "[$(date '+%F %T')] ❌ BACKUP FAILED" >> $LOG
  exit 1
fi

# --- rotation: keep last 14 daily; keep 1st-of-month for 6 months ---
find $BK_DIR -name "mongo_*.gz"    -mtime +14  ! -name "mongo_*-01.gz" -delete
find $BK_DIR -name "mongo_*-01.gz" -mtime +185 -delete
find $BK_DIR -name "env_*.bak"     -mtime +14  -delete
EOS
chmod +x "$SCRIPT"

echo "==> 3/4 Installing cron job (daily at 02:00) ..."
( crontab -l 2>/dev/null | grep -v backup_mongo_daily.sh ; \
  echo "0 2 * * * /bin/bash $SCRIPT" ) | crontab -
echo "   Installed:"
crontab -l | grep backup_mongo_daily.sh

echo "==> 4/4 Running the FIRST backup right now to verify ..."
bash "$SCRIPT"
echo ""
ls -lh $BK_DIR/mongo_*.gz | tail -3
tail -2 $BK_DIR/backup.log
echo ""
echo "✅ Daily backup system is ACTIVE."
echo "   • Backups: /home/sksharma/backups/mongo_YYYY-MM-DD.gz (2 AM daily)"
echo "   • Keeps 14 daily + 1st-of-month for 6 months, auto-cleanup"
echo "   • Check anytime:  tail /home/sksharma/backups/backup.log"
echo "   • Restore only Actual Salary from a backup:"
echo "       bash $APP_DIR/restore_actual_salary_from_backup.sh $BK_DIR/mongo_YYYY-MM-DD.gz"
