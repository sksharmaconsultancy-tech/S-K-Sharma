#!/bin/bash
# S.K. Sharma & Co. — LEGACY SQL SERVER RESTORE (Iter 299)
# Restores the old payroll software's SQL Server backup (.bak inside a ZIP)
# into a Dockerised SQL Server 2022 Express on this VPS, then wires the
# portal's "Legacy SQL Explorer" to it (read-only browsing before import).
#
# USAGE (on the VPS):
#   bash legacy_setup.sh /path/to/backup.zip
#   (or place the ZIP in /home/sksharma/legacy/ and run without arguments)
set -e

LEG_DIR=/home/sksharma/legacy
APP_DIR=/home/sksharma/app
SQL_CONTAINER=sks-mssql
SQL_PORT=14333
mkdir -p $LEG_DIR/extracted

ZIP_FILE="$1"
if [ -z "$ZIP_FILE" ]; then
  ZIP_FILE=$(ls -S $LEG_DIR/*.zip 2>/dev/null | head -1 || true)
fi
if [ -z "$ZIP_FILE" ] || [ ! -f "$ZIP_FILE" ]; then
  echo "❌ No ZIP found. Copy your backup ZIP to $LEG_DIR/ (WinSCP) or run:"
  echo "   bash legacy_setup.sh /path/to/backup.zip"
  exit 1
fi
echo "==> Using backup: $ZIP_FILE ($(du -h "$ZIP_FILE" | cut -f1))"

echo "==> 1/6 Installing Docker + unzip (if needed)..."
command -v unzip >/dev/null || apt-get install -y -q unzip
command -v docker >/dev/null || (apt-get update -q && apt-get install -y -q docker.io)
systemctl enable --now docker >/dev/null 2>&1 || true

echo "==> 2/6 Starting SQL Server 2022 Express container..."
PASS_FILE=$LEG_DIR/.sa_pass
if [ ! -f "$PASS_FILE" ]; then
  echo "Sk$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 18)!9" > "$PASS_FILE"
  chmod 600 "$PASS_FILE"
fi
SA_PASS=$(cat "$PASS_FILE")
if ! docker ps -a --format '{{.Names}}' | grep -q "^${SQL_CONTAINER}$"; then
  docker run -d --name $SQL_CONTAINER \
    -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=$SA_PASS" -e "MSSQL_PID=Express" \
    -e "MSSQL_MEMORY_LIMIT_MB=4096" \
    -p 127.0.0.1:$SQL_PORT:1433 \
    -v $LEG_DIR:/legacy \
    --restart unless-stopped \
    mcr.microsoft.com/mssql/server:2022-latest
else
  docker start $SQL_CONTAINER >/dev/null 2>&1 || true
fi

SQLCMD="docker exec $SQL_CONTAINER /opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -P $SA_PASS"
echo "   waiting for SQL Server to come up..."
for i in $(seq 1 60); do
  if $SQLCMD -Q "SELECT 1" >/dev/null 2>&1; then break; fi
  sleep 3
  if [ "$i" = "60" ]; then echo "❌ SQL Server did not start — check: docker logs $SQL_CONTAINER"; exit 1; fi
done
echo "   SQL Server is up ✅"

echo "==> 3/6 Extracting ZIP..."
unzip -o -q "$ZIP_FILE" -d $LEG_DIR/extracted
BAKS=$(find $LEG_DIR/extracted -iname "*.bak" -type f)
if [ -z "$BAKS" ]; then
  echo "❌ No .bak file found inside the ZIP. Contents:"
  find $LEG_DIR/extracted -type f | head -20
  exit 1
fi

echo "==> 4/6 Restoring database(s)..."
set +e
for BAK in $BAKS; do
  BASE=$(basename "$BAK")
  DB=$(echo "${BASE%.*}" | tr -cd 'A-Za-z0-9_' | cut -c1-60)
  [ -z "$DB" ] && DB="legacy_db"
  REL=${BAK#$LEG_DIR/}
  echo "   • $BASE  →  database [$DB]"
  # Build MOVE clauses from the backup's logical file list.
  MOVES=""
  IDX=0
  while IFS='|' read -r LNAME TYPE; do
    LNAME=$(echo "$LNAME" | sed 's/^ *//;s/ *$//')
    TYPE=$(echo "$TYPE" | sed 's/^ *//;s/ *$//')
    [ -z "$LNAME" ] && continue
    IDX=$((IDX+1))
    if [ "$TYPE" = "L" ]; then EXT="ldf"; else EXT="mdf"; [ "$IDX" -gt 1 ] && EXT="ndf"; fi
    MOVES="$MOVES, MOVE N'$LNAME' TO N'/var/opt/mssql/data/${DB}_${IDX}.${EXT}'"
  done < <($SQLCMD -h -1 -W -s'|' -Q "SET NOCOUNT ON; RESTORE FILELISTONLY FROM DISK = N'/legacy/$REL'" 2>/dev/null | awk -F'|' 'NF>2 {print $1"|"$3}')
  if [ -z "$MOVES" ]; then echo "     ⚠ could not read file list — skipping $BASE"; continue; fi
  $SQLCMD -Q "RESTORE DATABASE [$DB] FROM DISK = N'/legacy/$REL' WITH REPLACE, RECOVERY $MOVES" -b
  if [ $? -eq 0 ]; then echo "     restored ✅"; else echo "     ❌ restore failed for $BASE (see message above)"; fi
done
set -e

echo "==> 5/6 Wiring the portal to the legacy server..."
ENV=$APP_DIR/backend/.env
grep -q "^LEGACY_MSSQL_HOST=" $ENV || echo "LEGACY_MSSQL_HOST=127.0.0.1" >> $ENV
grep -q "^LEGACY_MSSQL_PORT=" $ENV || echo "LEGACY_MSSQL_PORT=$SQL_PORT" >> $ENV
grep -q "^LEGACY_MSSQL_USER=" $ENV || echo "LEGACY_MSSQL_USER=sa" >> $ENV
if grep -q "^LEGACY_MSSQL_PASSWORD=" $ENV; then
  sed -i "s|^LEGACY_MSSQL_PASSWORD=.*|LEGACY_MSSQL_PASSWORD=$SA_PASS|" $ENV
else
  echo "LEGACY_MSSQL_PASSWORD=$SA_PASS" >> $ENV
fi
$APP_DIR/backend/venv/bin/pip show pymssql >/dev/null 2>&1 || $APP_DIR/backend/venv/bin/pip install -q pymssql
sudo supervisorctl restart sksharma-backend

echo "==> 6/6 Summary of restored databases:"
$SQLCMD -W -Q "SELECT name AS DatabaseName FROM sys.databases WHERE database_id > 4"
echo
echo "🎉 Legacy restore complete."
echo "Open the portal → Import / Export → 'Legacy SQL Explorer' to browse"
echo "every table of the old software (read-only) before we import anything."
