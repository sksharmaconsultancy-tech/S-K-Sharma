#!/bin/bash
# S.K. Sharma & Co. — RESTORE ACTUAL SALARY from a MongoDB backup (Iter 364)
#
# Restores ONLY the ``salary_structure_actual`` field (Basic + Salary 1-3 +
# Working Days) on every employee, from a mongodump backup taken BEFORE the
# Iter 361 "Sync Salary Structures" overwrote it. NOTHING ELSE is touched —
# attendance, claims, salary runs, bio codes, all other employee fields stay
# exactly as they are now.
#
# USAGE (on the VPS):
#   bash restore_actual_salary_from_backup.sh /path/to/backup
#
#   /path/to/backup can be:
#     • a mongodump DIRECTORY  (contains <dbname>/users.bson)
#     • a .gz / .archive file  (mongodump --archive --gzip)
set -e

BACKUP="$1"
APP_DIR=/home/sksharma/app
TMP_DB="sks_restore_tmp"

if [ -z "$BACKUP" ] || [ ! -e "$BACKUP" ]; then
  echo "Usage: bash $0 /path/to/mongodump-backup(-dir-or-.gz)"
  exit 1
fi

DB_NAME=$(grep '^DB_NAME=' $APP_DIR/backend/.env | cut -d= -f2 | tr -d '"' | tr -d "'")
MONGO_URL=$(grep '^MONGO_URL=' $APP_DIR/backend/.env | cut -d= -f2- | tr -d '"' | tr -d "'")
DB_NAME=${DB_NAME:-test_database}
echo "==> Live DB: $DB_NAME"

echo "==> 1/3 Restoring the backup's 'users' collection into temp DB '$TMP_DB'..."
mongosh "$MONGO_URL" --quiet --eval "db.getSiblingDB('$TMP_DB').dropDatabase()" >/dev/null 2>&1 || true
if [ -d "$BACKUP" ]; then
  # dump directory — find the users.bson inside it
  USERS_BSON=$(find "$BACKUP" -name "users.bson" | head -1)
  if [ -z "$USERS_BSON" ]; then
    echo "❌ users.bson not found inside $BACKUP"; exit 1
  fi
  SRC_DB=$(basename "$(dirname "$USERS_BSON")")
  mongorestore --uri="$MONGO_URL" --nsFrom="$SRC_DB.users" --nsTo="$TMP_DB.users" \
    --dir="$(dirname "$USERS_BSON")" --quiet
else
  mongorestore --uri="$MONGO_URL" --archive="$BACKUP" --gzip \
    --nsInclude="*.users" --nsFrom='$prefix$.users' --nsTo="$TMP_DB.users" --quiet 2>/dev/null || \
  mongorestore --uri="$MONGO_URL" --archive="$BACKUP" \
    --nsInclude="*.users" --nsFrom='$prefix$.users' --nsTo="$TMP_DB.users" --quiet
fi

echo "==> 2/3 Restoring salary_structure_actual on live employees..."
$APP_DIR/backend/venv/bin/python - "$MONGO_URL" "$DB_NAME" "$TMP_DB" << 'PYEOF'
import sys
from pymongo import MongoClient

mongo_url, dbname, tmpdb = sys.argv[1], sys.argv[2], sys.argv[3]
cli = MongoClient(mongo_url)
live = cli[dbname].users
bak = cli[tmpdb].users

n_bak = bak.count_documents({})
if not n_bak:
    print("❌ Temp restore is empty — wrong backup path?")
    sys.exit(1)
print(f"   Backup users found: {n_bak}")

restored = cleared = missing = same = 0
for b in bak.find({"role": "employee"},
                  {"user_id": 1, "salary_structure_actual": 1}):
    uid = b.get("user_id")
    if not uid:
        continue
    cur = live.find_one({"user_id": uid},
                        {"_id": 0, "salary_structure_actual": 1})
    if cur is None:
        missing += 1
        continue
    old_val = b.get("salary_structure_actual")
    if cur.get("salary_structure_actual") == old_val:
        same += 1
        continue
    if old_val is None:
        live.update_one({"user_id": uid},
                        {"$unset": {"salary_structure_actual": ""},
                         "$set": {"actual_salary_restored_at":
                                  __import__("datetime").datetime.utcnow()
                                  .isoformat()}})
        cleared += 1
    else:
        live.update_one({"user_id": uid},
                        {"$set": {"salary_structure_actual": old_val,
                                  "actual_salary_restored_at":
                                  __import__("datetime").datetime.utcnow()
                                  .isoformat()}})
        restored += 1
print(f"   ✅ Restored from backup : {restored}")
print(f"   ✅ Cleared (was empty before sync): {cleared}")
print(f"   · Already matching     : {same}")
print(f"   · In backup but not in live DB: {missing}")
PYEOF

echo "==> 3/3 Dropping temp DB..."
mongosh "$MONGO_URL" --quiet --eval "db.getSiblingDB('$TMP_DB').dropDatabase()" >/dev/null 2>&1 || true
echo ""
echo "✅ Actual Salary restore complete. Verify: Legacy Import → green"
echo "   'Actual Salary Comparison' button — portal values should again"
echo "   show your ORIGINAL data (differences vs old DB are expected now)."
